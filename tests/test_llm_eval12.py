"""S42 evaluation harness and research brief with FAKE models (no Ollama needed)."""
import json
import re
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from pflab.agents import brief as br
from pflab.agents import tools as T
from pflab.llm import eval12, guard as g
from pflab.pm import store


def reply(obj):
    return SimpleNamespace(text=json.dumps(obj) if not isinstance(obj, str) else obj, digest="d", tokens_in=1,
                           tokens_out=1, seconds=0.01)


def test_routing_set_is_well_formed():
    rs = eval12.routing_set()
    assert len(rs) == 60 and all(need <= set(T.BY_NAME) and need for _, need in rs)
    assert eval12.route_ok(["fds", "tax"], {"tax", "fds"}) and eval12.route_ok(["tax", "fds", "plan"], {"tax", "fds"})
    assert not eval12.route_ok(["tax"], {"tax", "fds"}) and not eval12.route_ok(["tax", "a", "b"], {"tax"})


def test_extraction_f1_by_hand():
    gold = [{"kind": "dividend", "dividend_per_share": 2.5}, {"kind": "other"}]
    assert eval12.extraction_f1(gold, [{"kind": "dividend", "dividend_per_share": 2.5}, {"kind": "other"}]) == 1.0
    # wrong amount: 2 of 3 gold pairs found, 1 wrong pair predicted
    assert eval12.extraction_f1(gold, [{"kind": "dividend", "dividend_per_share": 25}, {"kind": "other"}]) == \
        pytest.approx(2 * 2 / (2 * 2 + 1 + 1))
    assert eval12.extraction_f1(gold, [None, {"kind": "other", "bonus_new": None}]) == pytest.approx(2 / (2 + 2))


def test_extraction_items_take_gold_from_the_parsers():
    letters = [a + b for a in "ABCDE" for b in "abcde"]                       # 25 unique texts with no digits
    rows = ([f"Interim Dividend - Rs {i}.50 Per Share" for i in range(50)]
            + [f"Bonus {i}:{i + 1}" for i in range(1, 30)]
            + [f"Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs {v}/- Per Share {w}"
               for w in letters[:10] for v in (1, 2, 5)]
            + [f"Scheme Of Arrangement {w}" for w in letters]
            + ["Dividend - 50%", "Div-Rs 2 Per Share", "Interim Dividend Rs 2 Per Share/ Special Dividend Rs 3 Per Share"])
    raw = pd.DataFrame({"subject": rows, "faceVal": "10", "ex_date": "2020-01-01", "series": "EQ"})
    by = {}
    for x in eval12.extraction_items(raw):
        by.setdefault(x["gold"]["kind"], []).append(x)
    assert {k: len(v) for k, v in by.items()} == {"dividend": 40, "bonus": 20, "split": 20, "other": 20}
    d = by["dividend"][0]
    assert d["gold"]["dividend_per_share"] == float(re.search(r"Rs ([\d.]+)", d["text"]).group(1))
    b = by["bonus"][0]
    assert f"{int(b['gold']['bonus_new'])}:{int(b['gold']['bonus_held'])}" in b["text"]
    sp = by["split"][0]
    assert sp["gold"]["face_value_from"] == 10.0 and f"To Rs {int(sp['gold']['face_value_to'])}/-" in sp["text"]
    texts = {x["text"] for x in sum(by.values(), [])}
    assert not texts & {"Dividend - 50%", "Div-Rs 2 Per Share"}                # no percent maths, no "Div" as other
    assert not any("Special Dividend" in t for t in texts)                      # two amounts: nothing to add up


class Perfect:
    """Answers routing, extraction and materiality from the labels: the harness must score it 100%."""
    def __init__(self, ext, mat):
        self.ext = {x["text"]: x["gold"] for x in ext}
        self.mat = {x["text"]: x["gold"] for x in mat}
        self.route = {q: sorted(n) for q, n in eval12.routing_set()}

    def __call__(self, model, messages, **kw):
        user = messages[-1]["content"]
        if user.startswith("Tools:"):
            return reply({"tools": self.route[user.split("Question: ", 1)[1]]})
        if user in self.ext:
            return reply(self.ext[user])
        return reply({"label": self.mat[user]})


def _sets(tmp_path):
    ext = [{"text": "Bonus 1:2", "gold": {"kind": "bonus", "bonus_new": 1.0, "bonus_held": 2.0}},
           {"text": "Interim Dividend - Rs 3 Per Share", "gold": {"kind": "dividend", "dividend_per_share": 3.0}}]
    mat = [{"text": "Outcome: audited results for the year", "gold": "material"},
           {"text": "Copy of newspaper advertisement enclosed", "gold": "routine"}]
    (tmp_path / "llm_eval").mkdir()
    (tmp_path / "llm_eval" / "extraction.json").write_text(json.dumps(ext), encoding="utf-8")
    (tmp_path / "llm_eval" / "materiality.json").write_text(json.dumps(mat), encoding="utf-8")
    return ext, mat


def test_a_perfect_model_scores_full_marks_and_logs_every_call(tmp_path):
    ext, mat = _sets(tmp_path)
    con = store.connect(tmp_path / "l.duckdb")
    chat = eval12.logged(Perfect(ext, mat), con, "eval12")
    rep = eval12.evaluate("m", chat, tmp_path, ("routing", "extraction", "materiality"))
    assert rep.scores["routing"] == 1.0 and rep.scores["extraction_f1"] == 1.0 and rep.scores["materiality"] == 1.0
    assert con.execute("SELECT count(*) FROM llm_runs WHERE role='eval12'").fetchone()[0] == 60 + 2 + 2


def test_round_two_uses_its_own_unseen_sets(tmp_path):
    ext, mat = _sets(tmp_path)
    mat2 = [{"text": "Intimation of credit rating upgrade for bank loans", "gold": "material"}]
    (tmp_path / "llm_eval" / "materiality_r2.json").write_text(json.dumps(mat2), encoding="utf-8")
    perfect = Perfect(ext, mat + mat2)
    perfect.route.update({q: sorted(n) for q, n in eval12.routing_set(eval12.ROUNDS[2]["routing"])})
    rep = eval12.evaluate("m", perfect, tmp_path, ("routing", "materiality"), round_=2)
    assert rep.scores["routing"] == 1.0 and rep.scores["materiality"] == 1.0
    r1 = {q for q, _ in eval12.routing_set()}
    assert not r1 & {q for q, _ in eval12.routing_set(eval12.ROUNDS[2]["routing"])}       # no question reused
    assert eval12.ROUNDS[2]["answers_seed"] != eval12.ROUNDS[1]["answers_seed"]


def test_a_model_that_answers_badly_fails(tmp_path):
    ext, mat = _sets(tmp_path)
    junk = lambda model, messages, **kw: reply("not json at all")
    rep = eval12.evaluate("m", junk, tmp_path, ("routing", "extraction", "materiality"))
    assert rep.scores["routing"] == 0 and rep.scores["extraction_f1"] == 0 and rep.scores["materiality"] == 0
    assert not any(rep.passes().values())


def test_answers_bookkeeping(monkeypatch):
    v = lambda t: g.Violation("number_not_in_facts", t)
    calls = iter([g.Outcome("ok", True, 1, []), g.Outcome(None, False, 3, [[v("1"), v("2")], [v("3")], [v("4")]])] * 25)
    monkeypatch.setattr("pflab.llm.graphs.run", lambda *a, **k: next(calls))
    r = eval12.run_answers("m", lambda *a, **k: reply("x"), n=50)
    assert r["final"] == 0.5 and r["first"] == 0.5 and r["rejected_per_task"] == pytest.approx(4 * 25 / 50)
    assert r["rows"][1]["violations"] == [[["number_not_in_facts", "1"], ["number_not_in_facts", "2"]],
                                          [["number_not_in_facts", "3"]], [["number_not_in_facts", "4"]]]
    assert r["rows"][0]["text"] == "ok" and r["rows"][1]["text"] is None


def test_round_three_runs_the_guard_as_production_does(monkeypatch):
    """S43: rounds 1-2 ran the strict guard while the live centre allows a number from a cited source; round 3
    uses the production setting, rounds 1-2 stay reproducible as they ran."""
    seen = []
    monkeypatch.setattr("pflab.llm.graphs.run", lambda *a, **k: seen.append(k.get("allow_cited_source_numbers"))
                        or g.Outcome("ok", True, 1, []))
    for rnd in (1, 2, 3):
        eval12.evaluate("m", lambda *a, **k: reply("x"), None, ("answers",), round_=rnd)
    assert seen == [False] * 50 + [False] * 50 + [True] * 50
    assert eval12.ROUNDS[3]["answers_seed"] not in (eval12.ROUNDS[1]["answers_seed"], eval12.ROUNDS[2]["answers_seed"])


def test_a_flaky_call_is_retried_and_a_dead_one_raises():
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("ollama restarting")
        return "ok"
    waits = []
    assert eval12.retrying(flaky, sleep=waits.append)() == "ok" and waits == [10.0, 20.0]

    def dead(*a, **k):
        raise ConnectionError("down")
    with pytest.raises(ConnectionError):
        eval12.retrying(dead, sleep=lambda s: None)()


def test_decision_rule():
    ok = {"routing": 0.97, "answers_final": 1.0, "extraction_f1": 0.97, "materiality": 0.93, "latency_p90_s": 12,
          "latency_median_s": 6, "routing_median_s": 0.8}
    reps = [{"model": "big:q4", "scores": ok}, {"model": "small:q8_0", "scores": {**ok, "latency_median_s": 9}},
            {"model": "small:q4", "scores": {**ok, "answers_final": 0.96}},                 # fails one threshold
            {"model": "laya", "scores": {"routing": 0.96, "materiality": 0.91, "routing_median_s": 0.05}}]
    d = eval12.decide(reps, {"big:q4": 9.3, "small:q8_0": 8.9, "small:q4": 5.2, "laya": 0.4})
    assert d["general"] == "small:q8_0" and set(d["passing"]) == {"big:q4", "small:q8_0"}
    assert d["routing_and_tagging"] == "laya"
    assert eval12.decide([reps[2]], {"small:q4": 5.2})["general"] is None


def test_recording_a_decision_switches_the_agents(tmp_path, monkeypatch):
    from datetime import datetime
    from pflab.agents import centre
    from pflab.llm import registry
    f = tmp_path / "picks.toml"
    f.write_text('[[pick]]\nrole = "research"\nmodel = "old"\nregistered_at = 2026-10-06T10:00:00\nevaluated_at = ""\n'
                 'decision = ""\n\n[[pick]]\nrole = "eval12"\nmodel = "m:q4"\nregistered_at = 2026-10-16T17:05:00\n'
                 'evaluated_at = ""\ndecision = ""\n', encoding="utf-8")
    assert registry.chosen("general", f) is None
    assert registry.record_decision("eval12", "m:q4", "chosen general", datetime(2026, 10, 20, 9, 0), f)
    assert registry.chosen("general", f) == "m:q4" and registry.chosen("routing", f) is None
    research = registry.load_picks(f)[0]
    assert research["decision"] == "" and research["evaluated_at"] == ""        # other picks untouched
    assert not registry.record_decision("eval12", "missing", "chosen general", datetime(2026, 10, 20), f)
    # no decision on disk: the centre routes by keywords and answers with facts, calling no model
    monkeypatch.setattr(registry, "chosen", lambda use, path=None: None)
    monkeypatch.setattr(centre.T, "BY_NAME", {"fds": SimpleNamespace(run=lambda con, asof: {"fd.next": "2027-01-30"},
                                                                     uses_question=False)})
    a = centre.ask(None, "when does my FD mature", date(2026, 10, 16))
    assert a.router == "keywords" and not a.verified and "fd.next = 2027-01-30" in a.text and "centre.error" not in a.facts


def test_built_sets_match_the_registered_hashes():
    from pflab.data import data_dir
    proto = (eval12.ROOT / "docs" / "llm" / "model_eval_12gb_protocol.md").read_text(encoding="utf-8")
    for name in ("extraction", "materiality"):
        p = data_dir() / "llm_eval" / f"{name}.json"
        if not p.exists():
            pytest.skip("evaluation sets not built on this machine")
        assert eval12.file_sha(p) in proto


def test_brief_is_facts_only_without_a_model_and_guarded_with_one(monkeypatch):
    facts = {"AAA.q1.net_profit": (120.5, "million"), "AAA.documents": 3}
    monkeypatch.setattr("pflab.kg.build.context", lambda con, s, asof, days=90, per=8: (dict(facts), {"S1": "2026-10-01 filing: results"}))
    monkeypatch.setattr("pflab.llm.registry.chosen", lambda use, path=None: None)   # independent of the live config
    b = br.build(None, "aaa", date(2026, 10, 16), {"verdict": "ok", "reasons": []})
    assert not b.verified and "no model chosen yet" in b.text and "AAA.guard = ok" in b.text
    good = lambda prompt: "Net profit was 120.5 million in the latest quarter [F:AAA.q1.net_profit]."
    assert br.build(None, "AAA", date(2026, 10, 16), llm=good).verified
    bad = lambda prompt: "Net profit was 999 million [F:AAA.q1.net_profit]."
    nb = br.build(None, "AAA", date(2026, 10, 16), llm=bad)
    assert not nb.verified and "no checked written brief" in nb.text
    assert br.chosen_llm() is None                                # nothing chosen: no model


def test_laya_adapter_on_a_fake_systemone(tmp_path):
    _sets(tmp_path)
    need = {q: n for q, n in eval12.routing_set()}

    def transport(method, path, payload, timeout):
        assert path == "/v1/systemone" and payload["model"] == "laya"
        qs = payload["questions"]
        if "materiality" in qs:
            gold = "routine" if "newspaper" in payload["state"] else "material"
            return {"answers": [{"type": "choice", "choice": gold}]}
        return {"answers": {k: {"type": "noul", "noul": 0.9 if k in need[payload["state"]] else 0.1} for k in qs}}

    rep = eval12.evaluate_laya(transport, tmp_path)
    assert rep.scores["routing"] == 1.0 and rep.scores["materiality"] == 1.0
    low = lambda m, p, payload, t: {"answers": {k: {"noul": 0.2 if k == "tax" else 0.1} for k in payload["questions"]}}
    assert eval12.laya_route("anything", low) == ["tax"]                 # the most likely tool is always kept
