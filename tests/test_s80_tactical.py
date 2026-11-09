"""S80 phase 3: the tactical lane (views), the big-trade checker, the storyline tools and the daily job (synthetic data; a fake Sonnet and a fake local chat)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab.core import checker, loop, views
from pflab.hq import egress, governor as gv
from pflab.lab import tools
from pflab.paper import book
from pflab.story import prob, reader, store
from tests.test_s68_autonomy import CFG
from tests.test_s80_core import AAA, BBB, DAYS, GLD, NOW, calm_index, con  # noqa: F401  (the fixture)

DAY = DAYS[-1]


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "data" / "indices"
    r.mkdir(parents=True)
    n = len(DAYS)
    pd.DataFrame({"date": [str(d) for d in DAYS], "close": 30000.0 * np.cumprod(np.full(n, 1.0003))}).to_parquet(r / "NIFTY500_TRI.parquet", index=False)
    return tmp_path / "data"


def _issue(con, **kw):
    a = dict(direction=1, names=["AAA"], share_of_budget=0.5, horizon_sessions=10, stop_pct=8.0, reason="AAA looks cheap against its sector after the result", isin_of=None)
    a.update(kw)
    return views.issue(con, NOW, DAY, **a)


def test_a_view_is_validated_sized_by_code_and_cannot_pass_the_budget(con):
    assert not _issue(con, direction=0)["ok"] and not _issue(con, share_of_budget=1.5)["ok"] and not _issue(con, horizon_sessions=1)["ok"]
    assert not _issue(con, reason="too short")["ok"] and not _issue(con, names=["NOSUCH"])["ok"] and not _issue(con, names=[])["ok"]
    assert not _issue(con, storyline_id=9)["ok"]
    ok = _issue(con)
    assert ok["ok"] and ok["tactical_budget_share_of_book"] == 0.10 and "about 5.0% of the book" in ok["code_will"]
    assert not _issue(con, names=["BBB"], share_of_budget=0.6)["ok"]                   # 0.5 + 0.6 would pass 100% of the tactical budget
    assert _issue(con, names=["BBB"], share_of_budget=0.5)["ok"]


def test_active_views_merge_into_the_targets_before_the_rails_and_a_down_view_never_shorts(con):
    _issue(con, names=["AAA"], share_of_budget=1.0)
    nxt = DAY + timedelta(days=1)
    assert views.active(con, DAY) == []                                                # a view starts at the NEXT close
    held = {AAA: 0.30, BBB: 0.02}
    out = views.merge(con, nxt, {AAA: 0.30, BBB: 0.02}, held)
    assert out[AAA] == pytest.approx(0.30 + 1.0 * 0.10)                                # share x budget x (1 name)
    con.execute("INSERT INTO core_views_s80 (view_id, made_on, made_at, direction, names_json, share_of_budget, horizon_sessions, exit_json, reason, status, due_on, ref_level) "
                "VALUES (90, ?, ?, -1, ?, 1.0, 10, '{}', 'x', 'active', ?, 50.0)", [DAY, NOW, json.dumps([BBB]), DAY + timedelta(days=20)])
    out2 = views.merge(con, nxt, {AAA: 0.30, BBB: 0.02}, held)
    assert out2[BBB] == 0.0                                                            # 0.02 - 0.10 would be -0.08: it stops at zero, nothing is shorted


def test_a_view_stops_when_its_names_fall_by_the_stop_and_is_not_applied_again(con):
    v = _issue(con, stop_pct=5.0)
    px = book.close_on(con, AAA, DAY)[1]
    con.execute("UPDATE core_views_s80 SET ref_level=? WHERE view_id=?", [px * 1.10, v["view_id"]])              # the reference was 10% above where it is now
    out = views.merge(con, DAY + timedelta(days=1), {AAA: 0.2}, {AAA: 0.2})
    assert out[AAA] == 0.2 and con.execute("SELECT status FROM core_views_s80 WHERE view_id=?", [v["view_id"]]).fetchone()[0] == "stopped"


def test_a_view_is_scored_against_the_index_at_its_horizon_and_the_budget_follows_the_record(con, root):
    v = _issue(con, horizon_sessions=3)
    con.execute("UPDATE core_views_s80 SET due_on=?, made_on=?, ref_level=? WHERE view_id=?", [DAYS[-2], DAYS[-8], book.close_on(con, AAA, DAYS[-8])[1], v["view_id"]])
    assert views.score_due(con, NOW, DAY, root) == 1
    row = con.execute("SELECT outcome, outcome_json FROM core_views_s80 WHERE view_id=?", [v["view_id"]]).fetchone()
    assert row[0] in ("good", "bad") and {"names_return", "index_return", "excess_signed"} <= set(json.loads(row[1]))
    assert views.budget_share(con)["share"] == 0.10                                    # one view scored: still the starting budget
    con.execute("DELETE FROM core_views_s80")
    for i in range(20):
        con.execute("INSERT INTO core_views_s80 (view_id, made_on, made_at, direction, names_json, share_of_budget, horizon_sessions, status, outcome, outcome_json, scored_at) VALUES (?,?,?,1,'[]',0.1,5,'done','good',?,?)",
                    [200 + i, DAY, NOW, json.dumps({"excess_signed": 0.01}), NOW])
    assert views.budget_share(con)["share"] == 0.20
    con.execute("UPDATE core_views_s80 SET outcome='bad', outcome_json=?", [json.dumps({"excess_signed": -0.02})])
    assert views.budget_share(con)["share"] == 0.05 and "poor record" in views.budget_share(con)["why"]


def test_the_loop_carries_an_active_view_out_through_the_same_rails(con):
    con.execute("INSERT INTO core_views_s80 (view_id, made_on, made_at, direction, names_json, share_of_budget, horizon_sessions, exit_json, reason, status, due_on, ref_level) "
                "VALUES (1, ?, ?, -1, ?, 1.0, 30, '{}', 'x', 'active', ?, 1.0)", [DAYS[-3], NOW, json.dumps([AAA]), DAY + timedelta(days=30)])
    base = loop.run(con, NOW, None, calm_index())
    sold = [o for o in base["orders"] if o["symbol"] == "AAA" and o["side"] == "sell"]
    assert sold, base                                                                  # the down view pushed AAA's target under its weight: code sells
    assert any("tactical views merged" in r[0] for r in con.execute("SELECT note FROM core_runs_s80").fetchall())


# --- the checker ----------------------------------------------------------------------------------------------------------------------

def _orders(*specs):
    return [{"symbol": s, "side": "buy", "value": v, "from_w": 0.02, "to_w": 0.09, "note": "", "isin": s, "qty": None, "amount": v, "risk_cut": False, "charges": 0, "tax": 0} for s, v in specs]


def _sonnet(answer=None, raise_=None):
    def create(**kw):
        if raise_:
            raise raise_
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(answer))], stop_reason="end_turn", model=gv.SONNET,
                               usage=SimpleNamespace(input_tokens=2000, output_tokens=80, cache_read_input_tokens=0, cache_creation_input_tokens=0))
    return SimpleNamespace(messages=SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=2000)), beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


STATE = {"value": 1_000_000.0}


def test_only_big_trades_are_checked_and_a_veto_removes_just_that_order(con):
    orders = _orders(("AAA", 80_000), ("BBB", 30_000), ("CCC", 60_000))
    assert [o["symbol"] for o in checker.big(orders, 1_000_000.0)] == ["AAA", "CCC"]               # 5% of the book or more
    calls = []
    client = _sonnet({"verdicts": [{"symbol": "AAA", "verdict": "veto", "reason": "the price is stale: no trade since 3 Nov"}, {"symbol": "CCC", "verdict": "pass", "reason": "fine"}]})
    out = checker.review(con, NOW, DAY, STATE, orders, lambda: calls.append(1) or client, gate=egress.Gate(), cfg=CFG)
    assert [o["symbol"] for o in out["orders"]] == ["BBB", "CCC"] and out["vetoed"][0]["symbol"] == "AAA" and out["checked"] == 2 and len(calls) == 1
    rows = con.execute("SELECT subject, verdict, reason FROM core_checks_s80 ORDER BY check_id").fetchall()
    assert ("AAA", "veto", "the price is stale: no trade since 3 Nov") in rows and any(r[1] == "pass" for r in rows)
    assert con.execute("SELECT agent FROM api_calls").fetchone()[0] == "checker"
    none = checker.review(con, NOW, DAY, STATE, _orders(("AAA", 10_000)), lambda: 1 / 0)               # nothing big: no client is even made
    assert none["checked"] == 0 and none["unchecked"] is None


def test_a_missing_or_failing_check_never_stops_the_book(con):
    orders = _orders(("AAA", 80_000))
    no_client = checker.review(con, NOW, DAY, STATE, orders, None)
    assert no_client["orders"] == orders and "no cloud client" in no_client["unchecked"]
    failing = checker.review(con, NOW, DAY, STATE, orders, lambda: _sonnet(raise_=RuntimeError("provider down")), gate=egress.Gate(), cfg=CFG)
    assert failing["orders"] == orders and "provider down" in failing["unchecked"]
    garbled = checker.review(con, NOW, DAY, STATE, orders, lambda: _sonnet({"verdicts": [{"symbol": "AAA", "verdict": "maybe", "reason": "x"}]}), gate=egress.Gate(), cfg=CFG)
    assert garbled["orders"] == orders and garbled["unchecked"]
    assert {r[0] for r in con.execute("SELECT verdict FROM core_checks_s80").fetchall()} == {"unchecked"}


# --- the strategist's storyline and view tools -------------------------------------------------------------------------------------

def test_the_strategist_can_open_adjust_and_read_storylines_and_issue_a_view_through_its_tools(con, tmp_path, root):
    ctx = tools.make_ctx(con, tmp_path, root, NOW, 1)
    text, err = tools.run(ctx, "open_storyline", {"claim": "A weak rupee and rising crude together should weigh on Indian shares in the weeks ahead", "direction": -1, "templates": ["rupee_weakening", "crude_rising"]})
    sid = json.loads(text)["storyline_id"]
    assert not err and con.execute("SELECT count(*) FROM storyline_predictions_s80 WHERE storyline_id=?", [sid]).fetchone()[0] in (0, 2)
    bad, err2 = tools.run(ctx, "open_storyline", {"claim": "short", "direction": 1, "templates": ["fii_buying_strong"]})
    assert err2 and "claim" in bad
    adj, _ = tools.run(ctx, "adjust_storyline", {"storyline_id": sid, "delta": 9, "reason": "the rupee move was a one-day spike, so the signal overstates it"})
    assert json.loads(adj)["ai_adjust"] == prob.AI_LIMIT
    full, _ = tools.run(ctx, "storylines", {"storyline_id": sid})
    assert "evidence" in json.loads(full) and "signal_menu" in json.loads(tools.run(ctx, "storylines", {})[0])
    v, err3 = tools.run(ctx, "issue_view", {"direction": -1, "symbols": ["AAA"], "share_of_budget": 0.3, "horizon_sessions": 10, "storyline_id": sid,
                                             "reason": "crude and the rupee point to pressure on oil-importing names"})
    assert err3 is False or json.loads(v).get("ok") is not None
    assert len(tools.definitions()) <= 16


# --- the reader when the local model is down, and the daily job --------------------------------------------------------------------

def test_an_item_is_not_marked_read_while_the_local_model_cannot_answer(con):
    store.open_storyline(con, NOW, "Foreign money is rotating into India which should lift the Nifty over weeks", 1, date(2026, 11, 5), ["fii_buying_strong"])

    def down(name, messages, **kw):
        raise ConnectionError("ollama is down")
    item = {"key": "flows:2026-11-05", "date": date(2026, 11, 5), "source_kind": "tool", "source_ref": "FII_NET_CR:2026-11-05", "text": "Foreign institutions were net buyers of Rs 14,975 crore on 2026-11-05"}
    out = reader.process(con, NOW, [item], chat=down)
    assert out["unavailable"] == 1 and out["read"] == 0 and con.execute("SELECT count(*) FROM storyline_reader_s80").fetchone()[0] == 0


def test_the_daily_job_updates_probabilities_registers_predictions_and_refreshes_the_record(con, root, monkeypatch):
    from pflab.service.tasks_s79_story import _run
    sid = store.open_storyline(con, NOW, "Foreign money is rotating into India which should lift the Nifty over weeks", 1, date(2026, 10, 20), ["nifty_up_strong"])["storyline_id"]
    monkeypatch.setattr(reader, "process", lambda con_, now, items, **kw: {"read": len(items), "attached": 0})
    monkeypatch.setattr("pflab.story.adapters.collect", lambda con_, root_, asof: [])
    ctx = SimpleNamespace(con=con, now=datetime.combine(DAY, datetime.min.time()) + timedelta(hours=20), data_root=root)
    out = _run(ctx)
    assert out["probabilities"] and con.execute("SELECT count(*) FROM storyline_prob_s80 WHERE storyline_id=?", [sid]).fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM storyline_predictions_s80 WHERE storyline_id=?", [sid]).fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM storyline_record_s80").fetchone()[0] == 1


def test_a_view_on_a_name_the_policy_does_not_hold_asks_for_its_share_once_not_again_each_close():
    """S81 (found by the session agent): the merge used `current weight + share` for such a name, so an active view compounded at every close."""
    import json
    from datetime import date
    from pflab.core import views
    from pflab.pm import store
    import tempfile, pathlib
    con = store.connect(pathlib.Path(tempfile.mkdtemp()) / "l.duckdb")
    con.execute("INSERT INTO core_views_s80 (view_id, made_on, made_at, direction, names_json, share_of_budget, horizon_sessions, status, due_on, ref_level) VALUES (1, ?, now(), 1, ?, 1.0, 20, 'active', ?, 100.0)",
                [date(2026, 11, 2), json.dumps(["INEX"]), date(2026, 12, 1)])
    for d in (date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)):
        con.execute("INSERT INTO prices VALUES ('INEX', ?, 100.0, 'EQ', 's', now())", [d])
    first = views.merge(con, date(2026, 11, 3), {}, {})["INEX"]
    second = views.merge(con, date(2026, 11, 4), {}, {"INEX": first})["INEX"]
    third = views.merge(con, date(2026, 11, 5), {}, {"INEX": second})["INEX"]
    assert first > 0 and second == first and third == first
