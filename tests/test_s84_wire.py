"""S84 wire: the thinking loop is called by the loops that already run (`think/wire.py` and its few hook lines). The watch, the thinking session, the recall, the desk and the score modules are other
agents' work: here they are scripted fakes put in `sys.modules`, so the wiring is tested alone. Synthetic data only (rule 7)."""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from pflab import think
from pflab.core import session
from pflab.think import cases, wire

from tests.test_s80_core import con  # noqa: F401  (the fixture: a store with the S80 paper book)
from tests.test_s81_session import AAA, MON, db  # noqa: F401  (the fixture: the S80 book with a session's data)

NOW = datetime(2026, 11, 12, 16, 30)          # a Thursday, after the India close
TODAY = NOW.date()


class Fakes:
    """The calls the loops made, in order, and what the scripted modules answer."""

    def __init__(self):
        self.calls = []
        self.opened = {}                      # mode -> case ids the watch "opens"
        self.watch_error = None
        self.think_error = {}                 # case id -> exception
        self.follow_error = None


@pytest.fixture
def fk(monkeypatch):
    f = Fakes()

    def watch_run(con, now, *, mode, quotes=None, root=None):
        f.calls.append(("watch", mode, now))
        if f.watch_error:
            raise f.watch_error
        return {"signals": [1, 2], "cases_opened": list(f.opened.get(mode, [])), "joined": [], "noticed": 0}

    def think_case(con, now, case_id, *, root=None):
        f.calls.append(("think", case_id))
        if case_id in f.think_error:
            raise f.think_error[case_id]
        return {"case_id": case_id}

    def follow_up(con, now, day):
        f.calls.append(("follow", day))
        if f.follow_error:
            raise f.follow_error
        return {"looked": 0}

    monkeypatch.setitem(sys.modules, "pflab.think.watch", SimpleNamespace(run=watch_run, scope=lambda con, day: []))
    monkeypatch.setitem(sys.modules, "pflab.think.session", SimpleNamespace(think_case=think_case, follow_up=follow_up))
    monkeypatch.setattr(wire, "_data_through", lambda con, root, market: {"IN": date(2026, 11, 12), "US": date(2026, 11, 11)}[market])
    return f


def _marked_days(con, market):
    return sorted(w.split()[2] for (w,) in con.execute("SELECT what FROM paper_acts WHERE loop='think_loop' AND what LIKE ?", [f"watch {market} %"]).fetchall())


def _log(con):
    return [r[0] for r in con.execute("SELECT what FROM session_log_s81 ORDER BY log_id").fetchall()]


# --- the close, the US morning, the catch-up ---------------------------------------------------------------------------------------------------------------------------------

def test_the_close_calls_the_watch_then_the_new_cases_then_the_follow_up_in_that_order(con, fk):
    fk.opened["close"] = [11, 12]
    r = wire.sweep(con, NOW, only_market="IN")
    assert [c[:2] for c in fk.calls] == [("watch", "close"), ("think", 11), ("think", 12), ("follow", TODAY)]
    assert r["sessions"] == {"IN": [f"{TODAY}:close"]} and r["thought"] == [11, 12] and not r["failed"]
    assert _marked_days(con, "IN") == [str(TODAY)]


def test_the_us_morning_is_watched_as_us_morning_at_the_latest_us_session(con, fk):
    r = wire.sweep(con, NOW, only_market="US")
    assert fk.calls[0][:2] == ("watch", "us_morning") and r["sessions"] == {"US": ["2026-11-11:us_morning"]}


def test_a_gap_is_caught_up_once_per_missed_session_oldest_first_at_each_sessions_own_close(con, fk):
    wire._mark(con, datetime(2026, 11, 9, 16, 0), "IN", date(2026, 11, 9), "close", {})        # the last session watched was Monday 9 Nov
    wire._mark(con, datetime(2026, 11, 9, 16, 0), "IN", date(2026, 11, 3), "close", {})        # (an older marker does not matter: the newest counts)
    r = wire.sweep(con, NOW, only_market="IN")
    watches = [c for c in fk.calls if c[0] == "watch"]
    assert [w[1] for w in watches] == ["catchup", "close"]                                      # Tue 10 Nov is a holiday in the NSE calendar: Wed 11 as catch-up, Thu 12 as the close
    assert watches[0][2] == datetime(2026, 11, 11, 15, 30)                                      # point-in-time: the missed session at its own close
    assert watches[1][2] == NOW
    assert len([c for c in fk.calls if c[0] == "follow"]) == 1                                  # the follow-up once for the whole gap
    fk.calls.clear()
    assert wire.sweep(con, NOW, only_market="IN")["sessions"] == {} and not [c for c in fk.calls if c[0] == "watch"]      # once per session: nothing is watched twice
    assert _marked_days(con, "IN") == ["2026-11-03", "2026-11-09", "2026-11-11", "2026-11-12"]


def test_the_first_ever_sweep_watches_only_the_latest_session(con, fk):
    wire.sweep(con, NOW, only_market="IN")
    assert [c[1] for c in fk.calls if c[0] == "watch"] == ["close"]


def test_no_closes_in_the_store_yet_means_nothing_is_watched(con, fk, monkeypatch):
    monkeypatch.setattr(wire, "_data_through", lambda con, root, market: None)
    assert wire.sweep(con, NOW)["sessions"] == {} and not fk.calls


def test_at_most_the_daily_cap_of_cases_is_thought_through_in_a_pass_and_the_rest_wait_open(con, fk):
    ids = []
    for i in range(5):
        ids.append(cases.open_case(con, NOW, market="IN", kind="move", isin=f"INE00000{i}01", symbol=f"S{i}", title="x", score=5 - i))
    fk.opened["close"] = ids
    r = wire.sweep(con, NOW, only_market="IN")
    assert r["thought"] == ids[:3] and [c[1] for c in fk.calls if c[0] == "think"] == ids[:3]
    fk.calls.clear()                                                                            # the next pass picks up the open cases nothing was thought about
    fk.opened.clear()
    r = wire.sweep(con, NOW + timedelta(hours=1), only_market="IN")
    assert r["thought"] == ids[:3]                                                              # none of the five has a step stored (the fake stores none): the first three again, bounded
    for cid in ids[:2]:
        cases.add_step(con, cid, NOW, "understand")
    fk.calls.clear()
    wire.sweep(con, NOW + timedelta(hours=2), only_market="IN")
    assert [c[1] for c in fk.calls if c[0] == "think"] == ids[2:5]


# --- failures never stop anything --------------------------------------------------------------------------------------------------------------------------------------------

def test_a_failing_watch_is_a_visible_line_leaves_the_session_unmarked_and_is_tried_again(con, fk):
    fk.watch_error = RuntimeError("prices table locked")
    r = wire.sweep(con, NOW, only_market="IN")
    assert r["failed"] and r["failed"][0].startswith("thinking failed: watch (IN") and "prices table locked" in r["failed"][0]
    assert any(x.startswith("thinking failed: watch") for x in _log(con)) and _marked_days(con, "IN") == []
    fk.watch_error = None
    assert wire.sweep(con, NOW, only_market="IN")["sessions"] == {"IN": [f"{TODAY}:close"]}


def test_a_failing_thinking_step_does_not_stop_the_close_the_other_cases_or_the_follow_up(con, fk):
    fk.opened["close"] = [21, 22]
    fk.think_error[21] = ValueError("the model said nonsense")
    r = wire.sweep(con, NOW, only_market="IN")
    assert r["thought"] == [22] and any("thinking failed: case #21" in x and "nonsense" in x for x in r["failed"])
    assert ("follow", TODAY) in [c[:2] for c in fk.calls] and _marked_days(con, "IN") == [str(TODAY)]
    assert any("thinking failed: case #21" in x for x in _log(con))


def test_a_failing_follow_up_is_a_visible_line_and_nothing_more(con, fk):
    fk.follow_error = RuntimeError("no look possible")
    r = wire.sweep(con, NOW, only_market="IN")
    assert any("thinking failed: follow-up" in x for x in r["failed"])


def test_the_guard_or_the_cap_refusing_pauses_thinking_without_a_failure_and_without_trying_the_next_case(con, fk):
    class OutwardBlocked(RuntimeError):
        pass

    fk.opened["close"] = [31, 32]
    fk.think_error[31] = OutwardBlocked("the workshop (beta channel) does not send outward")
    r = wire.sweep(con, NOW, only_market="IN")
    assert [c[1] for c in fk.calls if c[0] == "think"] == [31]                                  # the second case would be refused too
    assert r["failed"][0].startswith("thinking paused:") and not any(x.startswith("thinking failed") for x in r["failed"])
    fk.calls.clear()
    wire.sweep(con, NOW + timedelta(hours=1), only_market="IN")                                 # the cases stay open: tried again at the next pass
    fk.opened.clear()


def test_the_failure_line_is_said_once_a_day_per_reason(con, fk):
    fk.watch_error = RuntimeError("x")
    for k in range(3):
        wire.session_tick(con, NOW + timedelta(minutes=5 * k), {"INE000A01011": 1.0})
    assert len([x for x in _log(con) if x.startswith("thinking failed")]) == 1


def test_a_missing_module_is_not_a_failure(con, monkeypatch):
    monkeypatch.delitem(sys.modules, "pflab.think.watch", raising=False)
    monkeypatch.setitem(sys.modules, "pflab.think.watch", None)                                 # an import of it raises ImportError (name = the module)
    r = wire.sweep(con, NOW)
    assert r.get("skipped") and not _log(con)


# --- the kill switch --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_kill_switch_and_the_think_switch_stop_everything(con, fk, monkeypatch):
    from pflab import core
    monkeypatch.setattr(core, "killed", lambda: True)
    assert wire.sweep(con, NOW) == {"off": True} and wire.session_tick(con, NOW, {"x": 1.0}) == {"off": True} and not fk.calls
    monkeypatch.setattr(core, "killed", lambda: False)
    monkeypatch.setattr(think, "settings", lambda: {**think.DEFAULTS, "on": False})
    assert wire.sweep(con, NOW) == {"off": True} and wire.session_tick(con, NOW, {"x": 1.0}) == {"off": True} and not fk.calls and wire.today_block(con, TODAY) is None


# --- the session loop's tick --------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_session_tick_watches_the_quotes_thinks_the_new_cases_and_makes_no_follow_up(con, fk):
    fk.opened["session"] = [41]
    r = wire.session_tick(con, datetime(2026, 11, 12, 11, 0), {"INE000A01011": 100.0})
    assert [c[:2] for c in fk.calls] == [("watch", "session"), ("think", 41)] and r["cases_opened"] == [41]
    assert wire.session_tick(con, datetime(2026, 11, 12, 11, 5), {}) == {"skipped": "no live quotes"}


def test_the_session_loop_runs_the_watch_and_survives_it_failing(db, fk):
    t = datetime.combine(MON, time(11, 0))
    liq = {AAA: {"adv_rupees": 1e9, "typical_minute_volume": 1e4}}
    r = session.run_once(db, t, quotes={AAA: 100.0}, bars={}, liq=liq, data_root=None)
    assert [c[:2] for c in fk.calls] == [("watch", "session")] and r["think"]["signals"] == 2
    fk.watch_error = RuntimeError("boom")
    r = session.run_once(db, t + timedelta(minutes=5), quotes={AAA: 100.0}, bars={}, liq=liq, data_root=None)
    assert r["summary"]["quotes"] == 1 and r["think"]["failed"][0].startswith("thinking failed: watch (session)")        # the session check itself finished


# --- Today, the 15:45 report -------------------------------------------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def blocks(monkeypatch):
    monkeypatch.setitem(sys.modules, "pflab.think.session", SimpleNamespace(
        thinking_text=lambda con, day: "Thinking about: SYM1 (damage): fell 12% on a probe; waiting for the board's decision",
        reserve_status=lambda con, market, day: {"text": f"{market} reserve: Rs 100,000 free of Rs 100,000"}))
    monkeypatch.setitem(sys.modules, "pflab.think.recall", SimpleNamespace(knowledge_line=lambda con, day: {"text": "Notes: 2 paid this month, 1 read by a decision."}))
    monkeypatch.setitem(sys.modules, "pflab.think.desk", SimpleNamespace(plan_text=lambda con, day: "Plan: look at SYM1 after the board meets."))
    monkeypatch.setitem(sys.modules, "pflab.think.score", SimpleNamespace(scorecard=lambda con: {"scored": 4, "vs_nothing_inr": 1200.0, "skips_ran": 2, "skips_fell": 1}))


def test_today_carries_the_thinking_block_the_reserve_the_knowledge_line_the_plan_and_the_scorecard(con, blocks):
    from pflab.core import card
    b = card.today_extras(con)["think"]
    assert b["thinking"]["text"].startswith("Thinking about: SYM1") and b["reserve"] == ["IN reserve: Rs 100,000 free of Rs 100,000", "US reserve: Rs 100,000 free of Rs 100,000"]
    assert b["knowledge"].startswith("Notes: 2 paid") and b["plan"].startswith("Plan: look at") and b["scorecard"] == "Decisions: 4 scored, Rs +1,200 against doing nothing, after tax; skipped ideas that ran 2, that fell 1."


def test_today_falls_back_to_the_case_store_when_the_other_modules_are_not_there(con, monkeypatch):
    for m in ("session", "recall", "desk", "score"):
        monkeypatch.setitem(sys.modules, f"pflab.think.{m}", None)
    cases.open_case(con, NOW, market="IN", kind="move", isin="INE000A01011", symbol="AAA", title="AAA fell 9%", exposure_pct=0.05, score=3.0)
    b = wire.today_block(con, TODAY)
    assert "AAA" in b["thinking"]["text"] and b["reserve"] == [] and b["knowledge"] is None and b["plan"] is None and b["scorecard"] is None


def test_the_report_carries_one_line_each_and_keeps_its_fifteen_line_cap(con, blocks):
    cases.open_case(con, NOW, market="IN", kind="move", isin="INE000A01011", symbol="AAA", title="AAA fell 9%", score=3.0)
    text = session.report_day(con, TODAY)
    lines = text.split("\n")
    assert any(x.startswith("Thinking about:") for x in lines) and any(x.startswith("Reserve:") and "IN reserve" in x for x in lines)
    assert any(x.startswith("Decisions: 4 scored") and "Notes: 2 paid" in x for x in lines)
    assert len(lines) <= 15 and lines[-1].startswith("Post-close loop:")


def test_the_report_is_unchanged_when_there_is_nothing_to_say(con, monkeypatch):
    for m in ("session", "recall", "desk", "score"):
        monkeypatch.setitem(sys.modules, f"pflab.think.{m}", None)
    assert wire.report_lines(con, TODAY) == [] and "Thinking" not in session.report_day(con, TODAY)


# --- the job, the catch-up and the US step -------------------------------------------------------------------------------------------------------------------------------------------

def test_the_think_loop_job_is_registered_due_after_the_close_and_on_a_world_node():
    from pflab.app import world
    from pflab.service import ondemand, tasks
    from pflab.service.jobs import REGISTRY
    assert "think_loop" in REGISTRY and world.GROUP_OF["think_loop"] == "thinking"
    assert set(ondemand.AFTER["think_loop"]) == {"core_loop", "us_close", "catch_up"} and "think_loop" in ondemand.MAX_AGE_H


def test_the_job_runs_the_sweep_and_says_when_there_was_nothing(con, fk, monkeypatch):
    from pflab.service import tasks_s79_think84 as tj
    ctx = SimpleNamespace(con=con, now=NOW, data_root=None)
    out = tj._run(ctx)
    assert out["sessions"] and "IN" in out["sessions"] and out["cases_opened"] == 0
    fk.calls.clear()
    assert tj._run(ctx).get("skipped") == "nothing new to watch or think through"
    monkeypatch.setattr(wire, "sweep", lambda *a, **k: {"sessions": {}, "thought": [], "failed": ["thinking failed: watch (IN): x"]})
    assert tj._run(ctx)["thinking_problems"] == ["thinking failed: watch (IN): x"]             # a thinking failure is a note in the result, not a failed job


def test_the_job_is_disabled_by_the_kill_switch(con, monkeypatch):
    from pflab import core
    from pflab.service import tasks_s79_think84 as tj
    monkeypatch.setattr(core, "killed", lambda: True)
    assert tj._enabled(SimpleNamespace(con=con))[0] is False


def test_the_catch_up_runs_the_thinking_sweep_per_market_and_never_stops_on_its_failure(con, fk, monkeypatch):
    from pflab.service import catchup
    r = catchup._think_sweep(con, NOW, None, "IN")
    assert r["sessions"] == {"IN": [f"{TODAY}:close"]}
    monkeypatch.setattr(wire, "sweep", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert "failed" in catchup._think_sweep(con, NOW, None, "IN")


def test_the_us_job_watches_the_us_morning_before_the_us_decisions(con, fk, monkeypatch):
    from pflab.service import tasks_s79_us as tu
    from pflab.us import adapter, instruments as uins
    monkeypatch.setattr(uins, "refresh_if_due", lambda root, now=None: None)
    monkeypatch.setattr(adapter, "close_us", lambda con, now, root: fk.calls.append(("us_decisions",)) or {"skipped": "done"})
    monkeypatch.setattr(wire, "_market_on", lambda m: True)
    out = tu._run(SimpleNamespace(con=con, now=NOW, data_root=None))
    names = [c[0] for c in fk.calls]
    assert names.index("watch") < names.index("us_decisions") and fk.calls[0][1] == "us_morning" and out["thinking"]["sessions"] == {"US": ["2026-11-11:us_morning"]}
