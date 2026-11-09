"""S67 status, staleness, privacy and parity: a failed operation never refreshes a "last good" time or leaves a connector green; a job whose
sub-step failed has failed; retained data is shown as stale with the failure beside it; an email goes out only with provenance and a fresh
identity check (never raw, never by kind alone); the dashboard's Runtime and the background Desk give the same answers through the same tools;
a follow-up in the chat sees the chat. Synthetic data; fakes at the boundaries; no network."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.agents import tools as at
from pflab.app import chat, runtime, system
from pflab.hq import desk as hdesk, egress, governor as gv, service, tools as tl
from pflab.kg import graph as g
from pflab.pm import store
from pflab.service import jobs

NOW = datetime(2026, 11, 4, 21, 0)                   # a Wednesday evening
AAA = "INE000A01011"
CFG = {"model": "claude-opus-5-5", "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True, "tijori_to_analyst": True}


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'ALPHACO', 'Alphaco Industries Limited', 'synthetic', now())""", [AAA])
    con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('ZERODHA', 'demat', 'Zerodha', '12345678')")
    monkeypatch.setattr(system, "_ollama", lambda: {"up": True, "models": ["qwen3:8b-q8_0", "nomic-embed-text:latest"]})
    monkeypatch.setattr(system, "_docker", lambda: "not installed")
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def _job(con, rid, job, when, status, detail=None):
    con.execute("INSERT INTO job_runs (run_id, job, started_at, finished_at, status, detail) VALUES (?,?,?,?,?,?)", [rid, job, when, when, status, detail])


# --- a failed operation is never "last good" ---------------------------------------------------------------------------------------------

def test_kite_is_green_only_when_a_read_worked_not_when_a_login_exists(rt, monkeypatch):
    monkeypatch.setattr(runtime, "token_valid", lambda now=None: True)
    con = rt.cursor()
    k = {c["id"]: c for c in system.connectors(rt, NOW)}["kite"]
    assert k["state"] == system.WARN and "no read has worked" in k["line"]
    con.execute("INSERT INTO kite_snapshots (snap_id, taken_at, account_id, kind, amount) VALUES (1, ?, 'ZERODHA', 'cash', 5000)", [NOW - timedelta(hours=2)])
    assert {c["id"]: c for c in system.connectors(rt, NOW)}["kite"]["state"] == system.OK
    _job(con, 1, "tradecheck", NOW - timedelta(minutes=10), "failed", "KiteException: token expired")
    k = {c["id"]: c for c in system.connectors(rt, NOW)}["kite"]
    assert k["state"] == system.WARN and "token expired" in k["line"]


def test_telegram_api_and_sandbox_colours_come_from_real_use(rt, monkeypatch):
    rt.settings["telegram_send"] = True
    con = rt.cursor()
    con.execute("INSERT INTO outbox (msg_id, created_at, kind, text, dedup_key, status, attempts, last_error) VALUES (1, ?, 'brain', 'x', 'k', 'pending', 3, 'Telegram 401')",
                [NOW])
    cs = {c["id"]: c for c in system.connectors(rt, NOW)}
    assert cs["telegram"]["state"] == system.WARN and "failed to send" in cs["telegram"]["line"]
    assert cs["sandbox"]["state"] == system.WARN and "calculations wait" in cs["sandbox"]["line"]       # no Docker: not "uncontained but fine"
    from pflab.agents import sandbox as sb
    monkeypatch.setattr(system, "_docker", lambda: "running")
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": True, "why": ""})
    assert {c["id"]: c for c in system.connectors(rt, NOW)}["sandbox"]["state"] == system.WARN         # works, but containment not yet proven
    system.record_check(con, "sandbox", True, NOW - timedelta(days=1), "all checks passed")
    assert {c["id"]: c for c in system.connectors(rt, NOW)}["sandbox"]["state"] == system.WARN         # S70: a proof that names no release proves nothing about this one
    system.record_check(con, "sandbox", True, NOW - timedelta(days=1), sb.release_marker() + "; all checks passed")
    assert {c["id"]: c for c in system.connectors(rt, NOW)}["sandbox"]["state"] == system.OK
    system.record_check(con, "sandbox", False, NOW, "network_closed")
    sx = {c["id"]: c for c in system.connectors(rt, NOW)}["sandbox"]
    assert sx["state"] == system.DOWN and "calculations are blocked" in sx["line"]


def test_a_job_with_a_failed_sub_step_has_failed_and_the_screen_says_which(rt, tmp_path):
    from pflab.service import tasks  # noqa: F401  (registers the jobs)
    con = rt.cursor()
    ctx = jobs.Ctx(con, NOW, rt.pm_dir, rt.data_root, rt.repo, "python", None)
    job = jobs.Job("demo", jobs.REGISTRY["hq"].schedule, lambda c: {"ok_part": 3, "failed": {"readers": "RateLimitError: slow down"}})
    res = jobs.run_job(ctx, job)
    assert res.status == "failed" and "readers" in res.detail
    row = con.execute("SELECT status, detail FROM job_runs WHERE job='demo'").fetchone()
    assert row[0] == "failed" and json.loads(row[1])["ok_part"] == 3                     # the finished work is kept in the detail
    w = system.work(rt, NOW)
    assert w["recent"][0]["ok"] is False and "readers: RateLimitError" in w["recent"][0]["says"]
    assert jobs.followers(res) == []                                                     # nothing follows from a failed run
    ok = jobs.run_job(ctx, jobs.Job("demo2", job.schedule, lambda c: {"failed": {}}))
    assert ok.status == "ok"


# --- the same picture and the same tools from the dashboard and the background -------------------------------------------------------------

def _desk(rt, tmp_path):
    return hdesk.Desk(rt.cursor(), rt.pm_dir, rt.data_root, tmp_path, None, {"brain": "economy", "preset": "full"}, clock=lambda: NOW)


def test_system_status_works_in_the_dashboard_and_in_the_background(rt, tmp_path):
    d = _desk(rt, tmp_path)
    for who in (rt, d):
        ctx = SimpleNamespace(rt=who, now=NOW, con=who.cursor())
        s = tl.system_status(ctx, {})
        assert s["verdict"] and s["connectors"] and "recommendations" in s and "tasks" in s and "being_researched" in s
    a, b = system.picture(rt, NOW), system.picture(d, NOW)
    assert [c["state"] for c in a["connectors"]] == [c["state"] for c in b["connectors"]] and a["verdict"] == b["verdict"]


def test_the_ask_centre_answers_a_system_question_from_the_same_tool(rt, tmp_path):
    d = _desk(rt, tmp_path)
    for who in (rt, d):
        out = chat.answer(who, who.cursor(), "Is everything working and in sync?", "ask")
        assert "system" in out["route"][1] or any("tool: system" in r for r in out["route"]), out["route"]
        assert "connector" in out["text"] or "system.verdict" in out["text"] or "working" in out["text"]


def test_a_follow_up_sees_the_chat_and_the_open_work(rt, tmp_path):
    con = rt.cursor()
    cid = chat.create(con, NOW)
    chat._add(con, cid, "me", "ask", "How much of AAA do I hold?", "done", NOW)
    chat._add(con, cid, "ai", "ask", "About 9 percent of your investable money.", "done", NOW)
    q = chat._add(con, cid, "me", "ask", "and is that too much?", "done", NOW)
    h = chat.history_text(con, cid, q)
    assert h.splitlines() == ["he asked: How much of AAA do I hold?", "you answered: About 9 percent of your investable money."]
    seen = {}

    def fake_llm(prompt):
        seen["prompt"] = prompt
        return "x"
    from pflab.agents import centre
    centre.ask(con, "and is that too much?", NOW.date(), llm=fake_llm, tools_override=["system"], history=h)
    assert "EARLIER IN THIS CHAT" in seen["prompt"] and "How much of AAA do I hold?" in seen["prompt"]
    # S80 phase 4: a question outside a chat thread runs the same tool conversation as the chat, with the earlier turns passed in as text
    from pflab.app import assistant
    d = _desk(rt, tmp_path)
    got = {}

    def spy(rt_, con_, cid_, aid_, q_, context="", client=None, gate=None, cfg=None, history=""):
        got.update(cid=cid_, aid=aid_, q=q_, history=history)
        return {"text": "The answer.", "status": "done", "cost": 1.5}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(assistant, "answer", spy)
        out = service.brain_now(d, "and is that too much?", rival=False, history=h)
    assert got == {"cid": None, "aid": None, "q": "and is that too much?", "history": h}
    assert out["ok"] is True and out["text"] == "The answer." and out["cost"] == 1.5


# --- email: provenance, then a fresh identity check, never raw ---------------------------------------------------------------------------

def _json_msg(obj):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(obj))], stop_reason="end_turn", model=gv.HAIKU,
                           usage=SimpleNamespace(input_tokens=500, output_tokens=60, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class Haiku:
    def __init__(self, reply):
        self.reply, self.sent = reply, []
        self.messages = SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=600), create=self._create)

    def _create(self, **kw):
        self.sent.append(json.dumps(kw, default=str))
        return _json_msg(self.reply)


def _email_doc(con, tmp_path, name, body, cleared="auto", attrs_extra=None):
    d = g.doc(con, "email", f"mail:{name}", NOW, f"Alphaco research {name}", source="Research desk",
              attrs={"kind": "research", **({"cleared": hashlib.sha256(body.encode()).hexdigest()} if cleared == "auto" else
                                              {"cleared": cleared} if cleared else {}), **(attrs_extra or {})})
    p = tmp_path / f"{name}.txt"
    p.write_text(body, encoding="utf-8")
    con.execute("UPDATE kg_docs SET text_path=?, text_status='ok' WHERE doc_id=?", [str(p), d])
    g.edge(con, d, "about", f"company:{AAA}", NOW, "mail")
    return d


READ = {"material": "yes", "why": "upgrade", "summary": "Alphaco upgraded.", "figures": []}


def test_the_screen_says_what_stays_on_this_pc_and_what_goes_to_the_cloud(rt):
    p = {x["what"]: x for x in system.processing(rt)}
    assert not any("email" in k.lower() for k in p)                                              # email is gone (2026-10-30)
    assert "never leave" in p["His statements, ledger, tax lots and bank details"]["sends"]
    assert system.picture(rt, NOW)["processing"]


@pytest.fixture(autouse=True)
def _v1_advisor_layers(monkeypatch):
    """S80 switches the v1 advisor layers off by default (`configs/core.toml`); these tests are about the v1 hq round, so they run with the close loop off."""
    from pflab import core
    real = core.settings
    monkeypatch.setattr(core, "settings", lambda: {**real(), "core": {**real()["core"], "on": False, "advisors_off": False, "retire_missions": False}})
