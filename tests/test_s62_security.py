"""S62 (PLAN A21): the security agent (egress re-check, privacy grep, tests, code review), own-data judgement to the
brain (A20), the brain's web_search and findings tools. Synthetic data, fakes, no network."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from types import SimpleNamespace

import pytest

from pflab.agents import analyst as an, escalate
from pflab.hq import egress, security as sec, tools as tl
from pflab.hq.desk import Desk
from pflab.pm import store

NOW = datetime(2026, 11, 1, 21, 30)                  # a Sunday


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('ZERODHA', 'demat', 'Zerodha', '12081600')")
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('SB12345678', 'bank', 'SBI')")
    return c


def _desk(con, tmp_path, **settings):
    s = {"brain": "economy", "preset": "full", "telegram_send": False, **settings}
    return Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path, None, s, clock=lambda: NOW)


def _gate(con):
    return egress.Gate(ids=egress.load(con).ids, names=["ravi kumar"], address=["kothrud"])


def _call(con, cid, body, status="done"):
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, status, "
                "cost_inr, agent) VALUES (?,?,?,?,?,?,?,?,?,?,?)", [cid, NOW, "live", "m", "t", "q", "", body, status, 0.0, "reader"])


def test_hits_names_kinds_never_values(con):
    g = _gate(con)
    assert sec.hits("holding 12081600 at the depository", g) == ["an account, depository, folio or deposit id"]
    assert sec.hits("Ravi Kumar asked", g) == ["his name"]
    assert sec.hits("near Kothrud", g) == ["his address words"]
    assert sec.hits("PAN " + "ABCP" + "E1234F", g) == ["an individual's PAN"]   # built here: the repo's grep stays clean
    assert sec.hits("the company's PAN AAACR5055K", g) == []                # a company's PAN in a filing is not his


def test_egress_recheck_raises_once_and_moves_on(con, tmp_path, monkeypatch):
    rt = _desk(con, tmp_path)
    sent = []
    monkeypatch.setattr("pflab.hq.messenger.send_now", lambda rt, text, kind, dedup_key=None: sent.append(text))
    _call(con, 1, json.dumps({"messages": [{"content": "an old request naming Ravi Kumar"}]}))
    out = sec.egress(rt, _gate(con))                                         # the first run: one summary, no Telegram
    assert out["hits"] == 1 and sent == []
    assert "first look back" in con.execute("SELECT text FROM sec_findings").fetchone()[0]
    _call(con, 2, json.dumps({"messages": [{"content": "public filing text"}]}))
    _call(con, 3, json.dumps({"messages": [{"content": "account SB12345678 holds"}]}))
    _call(con, 4, json.dumps({"messages": [{"content": "SB12345678"}]}), status="over_limit")   # never sent
    out = sec.egress(rt, _gate(con))
    assert out == {"calls": 2, "messages": 0, "hits": 1}
    assert len(sent) == 1 and "SB12345678" not in sent[0] and "call #3" in sent[0]
    q = [t for a, t in con.execute("SELECT agent, text FROM questions").fetchall() if a == "security"]
    assert len(q) == 2 and not any("SB12345678" in t for t in q)
    assert sec.egress(rt, _gate(con))["calls"] == 0                          # the next round starts after #4


def test_privacy_grep_finds_his_data_in_tracked_files(con, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "docs" / "note.md").write_text("ok line\nhe holds WIDGETCO worth 12,34,567\n", encoding="utf-8")
    (tmp_path / "src" / "a.py").write_text("x = 'WIDGETCO'  # code may name a symbol\nacct = '12081600'\n", encoding="utf-8")
    found = sec.grep([tmp_path / "docs" / "note.md", tmp_path / "src" / "a.py"], _gate(con), [sec.indian(1234567)],
                     ["WIDGETCO"], tmp_path)
    assert ("docs/note.md:2", "a ledger amount") in found and ("docs/note.md:2", "a stock-list name") in found
    assert ("src/a.py:2", "an account, depository, folio or deposit id") in found
    assert ("src/a.py:1", "a stock-list name") in found                     # S63: list names count in code too
    assert sec.indian(1234567) == "12,34,567"


def test_the_push_check_uses_the_apps_terms_file_and_blocks_without_any_list(con, tmp_path, monkeypatch, capsys):
    """S65: the workshop holds no store: the app writes the list beside secrets.toml; with no list at all nothing is pushed."""
    monkeypatch.setattr(sec, "terms_path", lambda: tmp_path / "home" / "privacy_terms.json")
    monkeypatch.setattr(store, "db_path", lambda: tmp_path / "no-store" / "ledger.duckdb")
    monkeypatch.setattr(sec, "symbols", lambda con=None: ["WIDGETCO"])
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(sec, "tracked", lambda r: [repo / "a.md"])
    (repo / "a.md").write_text("nothing personal\n", encoding="utf-8")
    assert sec.push_check(repo) == 1 and "no list of his data" in capsys.readouterr().out
    sec.export_terms(con, _gate(con))
    gate, money, syms = sec.load_terms()
    assert "12081600" in gate.ids and syms == ["WIDGETCO"]
    assert sec.push_check(repo) == 0 and "clean" in capsys.readouterr().out
    (repo / "a.md").write_text("acct 12081600\n", encoding="utf-8")
    assert sec.push_check(repo) == 1 and "push blocked" in capsys.readouterr().out


def test_failed_tests_are_reported(con, tmp_path):
    rt = _desk(con, tmp_path)
    fake = lambda *a, **k: SimpleNamespace(returncode=1, stdout="FAILED tests/test_x.py::test_y - boom\n1 failed, 9 passed")  # noqa
    assert sec.tests(rt, run=fake) == {"ok": False, "summary": "1 failed, 9 passed"}
    assert "test_x.py" in con.execute("SELECT text FROM sec_findings").fetchone()[0]

    def slow(*a, **k):
        raise subprocess.TimeoutExpired("pytest", 1)
    assert sec.tests(rt, run=slow)["ok"] is False


def test_review_blocked_when_the_diff_carries_his_data(con, tmp_path, monkeypatch):
    rt = _desk(con, tmp_path)
    monkeypatch.setattr("pflab.hq.messenger.send_now", lambda *a, **k: None)
    monkeypatch.setattr(sec, "_git", lambda repo, *a: {"rev-parse": "h" * 40}.get(a[0], "+acct = 'SB12345678'"
                                                                                  if a[0] == "diff" else "b" * 40))
    calls = []
    out = sec.review(rt, gate=_gate(con), draft=lambda *a: calls.append(a) or {"findings": []})
    assert out == {"reviewed": 0, "blocked": True} and calls == []


def test_review_sends_clean_code_and_reports_findings(con, tmp_path, monkeypatch):
    rt = _desk(con, tmp_path)
    monkeypatch.setattr(sec, "_git", lambda repo, *a: {"rev-parse": "h" * 40}.get(a[0], "+x = 1 / n" if a[0] == "diff"
                                                                                  else "b" * 40))
    draft = lambda s, p, sc: {"findings": [{"file": "src/x.py", "severity": "high", "problem": "divides by zero"},  # noqa
                                           {"file": "src/y.py", "severity": "low", "problem": "naming"}]}
    out = sec.review(rt, gate=_gate(con), draft=draft)
    assert out["reviewed"] == 1 and out["findings"] == 1
    assert "divides by zero" in con.execute("SELECT text FROM sec_findings").fetchone()[0]
    assert sec.review_due(con, NOW) is False                                 # reviewed today


# --- own-data judgement goes to the brain (A20) --------------------------------------------------------------------------

def _fns(brain):
    local = SimpleNamespace(verified=True, text="local facts", tools=["networth"])
    return {"local": lambda con, q, asof: local, "brain": brain, "note": lambda *a: None}


@pytest.mark.parametrize("q,kind", [("Should I rebalance my portfolio?", "insight"), ("Am I too heavy in my FDs?", "insight"),
                                    ("What is my net worth?", "own"), ("What is the IPO GMP today?", "outside")])
def test_kind_of_insight(q, kind):
    assert escalate.kind_of(q, []) == kind


def test_insight_goes_to_brain_and_falls_back(con, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "deep_request", lambda con, q, asof: an.Request(q, "general", [], [], True))
    r = escalate.run(con, "Should I rebalance my portfolio?", NOW.date(), pm_dir=tmp_path, root=tmp_path,
                     fns=_fns(lambda q: {"ok": True, "text": "Brain: hold; equity is inside its band.", "cost": 9.5}))
    assert r.kind == "insight" and r.text.startswith("Brain:") and r.cost == 9.5
    r = escalate.run(con, "Should I rebalance my portfolio?", NOW.date(), pm_dir=tmp_path, root=tmp_path,
                     fns=_fns(lambda q: {"ok": False, "text": "No pass was made: limit"}))
    assert r.kind == "own" and r.text == "local facts" and r.steps[0].outcome == "no answer"


# --- the brain's new tools -------------------------------------------------------------------------------------------------

def _ctx(con, tmp_path, shadow=False):
    rt = _desk(con, tmp_path)
    return tl.Ctx(rt, 1, "claude-opus-5-5", shadow, {}, _gate(con), NOW, client=object())


def test_web_search_tool_capped_and_light(con, tmp_path, monkeypatch):
    seen = []

    def fake(con_, q, client, **kw):
        seen.append(kw)
        return an.Outcome("done", "RBI held the repo rate [W1]\n\nSources:\n[W1] RBI - https://rbi.org.in", 1, 8.0, [])
    monkeypatch.setattr(an, "web_search", fake)
    ctx = _ctx(con, tmp_path)
    text, err = tl.run(ctx, "web_search", {"question": "Did the RBI change the repo rate this week?"})
    assert not err and "repo rate" in text and seen[0]["max_uses"] == 2 and seen[0]["effort"] == "medium"
    for _ in range(3):
        tl.run(ctx, "web_search", {"question": "Did the RBI change the repo rate this week?"})
    assert len(seen) == 3 and "limit of 3" in tl.run(ctx, "web_search", {"question": "again?"})[0]
    rival = _ctx(con, tmp_path, shadow=True)
    assert "journal only" in tl.run(rival, "web_search", {"question": "Any news?"})[0] and len(seen) == 3


def test_findings_tool_lists_passed_and_failed(con, tmp_path):
    from pflab.learner import sources
    sid = sources._add(con, NOW, "drop", "drop:x", "A paper", "", 2020, "file", "text")
    for cid, d in ((1, "pass"), (2, "fail")):
        con.execute("INSERT INTO learn_claims (claim_id, src_id, made_at, claim, template, params_json, status, decision, why, "
                    "decided_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [cid, sid, NOW, f"claim {cid}", "calendar", json.dumps({"effect": "monday", "direction": "low"}),
                     "passed" if d == "pass" else "failed", d, f"why {cid}", NOW])
    text, err = tl.run(_ctx(con, tmp_path), "findings", {})
    out = json.loads(text)
    assert not err and out["passed"][0]["claim"] == "claim 1" and out["failed"][0]["claim"] == "claim 2"


def test_strict_tools_stay_within_the_api_limit():
    assert sum(1 for d in tl.definitions() if d.get("strict")) <= 20


def test_body_check_stops_his_name_anywhere_in_a_request(con):
    from pflab.hq import llm
    g = _gate(con)
    with pytest.raises(egress.EgressBlocked, match="his name"):
        llm.body_check({"system": "You answer Ravi Kumar's questions", "messages": []}, g)
    with pytest.raises(egress.EgressBlocked, match="account"):
        llm.body_check({"messages": [{"role": "assistant", "content": "SB12345678 holds it"}]}, g)
    llm.body_check({"system": "You answer the investor's questions", "messages": [{"content": "year 1208"}]}, g)
