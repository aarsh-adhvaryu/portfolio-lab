"""S93: standing orders and repeating plans. The model's own work starts only under an order he can see and switch; a repeated fault is OFFERED as a fix (a card with the cost) and no
build starts by itself unless he switched that on; a plan may repeat on his one Yes. `[jarvis] on = false` gives the behaviour before S93. Synthetic data only."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.llm import claude_plan as cp
from pflab.oper import actions, build, plans, standing

NOW = datetime(2026, 11, 17, 10, 0)


@pytest.fixture
def con(tmp_path, monkeypatch):
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path / "pm"))
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": True, "method": "claude.ai", "detail": ""})
    return store.connect(tmp_path / "t.duckdb")


def _wait(fn, secs: float = 8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < secs:
        if fn():
            return True
        time.sleep(0.02)
    return False


# --- the orders -------------------------------------------------------------------------------------------------------------------------------------------

def test_defaults_three_on_and_fixing_by_itself_off(con):
    assert standing.settings() == {"on": True, "cases": True, "desk": True, "weekly": True, "autofix": False}          # the shipped configs/core.toml [jarvis]
    assert [standing.is_on(con, k) for k in ("cases", "desk", "weekly", "autofix")] == [True, True, True, False]
    assert standing.allowed(con, "desk") == (True, "") and standing.allowed(con, "autofix")[0] is False
    with pytest.raises(KeyError):
        standing.is_on(con, "nothing")


def test_what_he_sets_wins_and_is_shown(con):
    assert standing.set_on(con, NOW, "desk", False)["on"] is False
    assert standing.is_on(con, "desk") is False and "is off" in standing.allowed(con, "desk")[1]
    standing.set_on(con, NOW, "desk", True)
    standing.set_on(con, NOW, "autofix", True, by="him (screen)")
    st = {d["key"]: d for d in standing.state(con, NOW)}
    assert list(st) == ["cases", "desk", "weekly", "autofix"] and st["autofix"]["on"] and st["autofix"]["default"] is False and st["autofix"]["set_by"] == "him (screen)"
    assert st["cases"]["waiting"] == 0 and st["desk"]["tokens_7d"] == 0 and "12,000" in st["cases"]["one_run"]
    assert "Fix a repeated fault by itself: ON" in standing.text(con, NOW)
    with pytest.raises(ValueError):
        standing.set_on(con, NOW, "trade", True)


def test_the_fallback_switch_gives_the_old_behaviour(con, monkeypatch):
    standing.set_on(con, NOW, "cases", False)
    monkeypatch.setattr(standing, "settings", lambda: {**standing.DEFAULTS, "on": False})
    assert all(standing.is_on(con, k) for k in standing.ORDERS)                                                        # automatic builds included, as before S93
    assert "not in use" in standing.text(con, NOW)


# --- the gates --------------------------------------------------------------------------------------------------------------------------------------------

def _stub_sweep(monkeypatch):
    from pflab.think import wire
    monkeypatch.setattr(wire, "_active", lambda: True)
    monkeypatch.setattr(wire, "_mod", lambda name: SimpleNamespace())
    monkeypatch.setattr(wire, "_market_on", lambda m: False)
    monkeypatch.setattr(wire, "_unthought", lambda con, n: [7])
    monkeypatch.setattr(wire, "_think", lambda con, now, ids, root, out: out["thought"].extend(ids))
    monkeypatch.setattr(wire, "_looks_due", lambda con, now: False)
    monkeypatch.setattr(wire, "_learn", lambda con, now, out, new_session: out.update(learned=True))
    return wire


def test_new_cases_wait_while_the_case_worker_is_off_and_his_own_ask_still_thinks(con, monkeypatch):
    wire = _stub_sweep(monkeypatch)
    assert wire.sweep(con, NOW)["thought"] == [7]                                                                     # on by default: as before
    standing.set_on(con, NOW, "cases", False)
    r = wire.sweep(con, NOW)
    assert r["thought"] == [] and r["learned"] is True and not r["failed"]                                            # the code parts (here: the scoring) still ran
    assert wire.sweep(con, NOW, asked=True)["thought"] == [7]                                                         # "think the cases through" from him
    assert wire.sweep(con, NOW, think_cases=False, asked=True)["thought"] == []                                       # the caller's own switch still holds


def test_the_desk_does_not_sit_down_by_itself_while_its_order_is_off(con, monkeypatch):
    from pflab.think import desk
    monkeypatch.setattr(desk, "on", lambda: True)
    monkeypatch.setattr(desk, "mode_for", lambda con, now: ("india_close", None))
    monkeypatch.setattr(desk, "run_desk", lambda con, now, mode, root=None, covers=None: {"ran": mode})
    assert desk.tick_hook(con, NOW) == {"ran": "india_close"}
    standing.set_on(con, NOW, "desk", False)
    assert "is off" in desk.tick_hook(con, NOW)["paused"]


def test_the_weekly_look_waits_while_its_order_is_off(con, monkeypatch):
    from pflab.oper import introspect, learn
    from pflab.service import tasks_s79_operator87 as t
    monkeypatch.setattr(learn, "score_due", lambda con, now, root: 0)
    monkeypatch.setattr(introspect, "due", lambda con, now: True)
    monkeypatch.setattr(introspect, "run", lambda con, now: {"written": True})
    ctx = SimpleNamespace(con=con, now=NOW, data_root=None)
    assert t._weekly(ctx)["written"] is True
    standing.set_on(con, NOW, "weekly", False)
    assert "is off" in t._weekly(ctx)["skipped"]


# --- a repeated fault is offered, not fixed by itself --------------------------------------------------------------------------------------------------------

def _fault(con, at, times=2, key="k1"):
    from pflab.service import problems
    problems._upsert(con, "job_failed", key, "job x failed: KeyError 'a'", "job x", at, at, times)


def test_a_repeated_fault_becomes_a_card_with_the_cost_and_no_build_starts(con):
    build.ensure(con)
    t0 = NOW - timedelta(hours=1)
    _fault(con, t0)
    assert build.scan_problems(con, NOW) == 0
    assert con.execute("SELECT count(*) FROM operator_builds_s87").fetchone()[0] == 0
    cards = con.execute("SELECT c.payload_json, m.text FROM cards_s85 c JOIN chat_messages m ON m.msg_id=c.msg_id WHERE c.kind='decision:fix_offer'").fetchall()
    assert len(cards) == 1 and '"key": "k1"' in cards[0][0] and "failed 2 times" in cards[0][1] and "400,000 to 560,000 tokens" in cards[0][1]
    _fault(con, NOW + timedelta(minutes=20), times=3)                                                                # it repeats: the same card, never a second one
    _fault(con, NOW + timedelta(minutes=20), key="k9")                                                               # another fault the same day: one offer a day
    assert build.scan_problems(con, NOW + timedelta(minutes=30)) == 0
    assert con.execute("SELECT count(*) FROM cards_s85 WHERE kind='decision:fix_offer'").fetchone()[0] == 1
    msg = build.on_fix_yes(con, NOW + timedelta(hours=1), {"key": "k1", "kind": "job_failed"})                       # his Yes: now, and only now, a build is queued
    assert "queued" in msg and con.execute("SELECT source, status FROM operator_builds_s87").fetchall() == [("problems", "requested")]
    assert "no longer" in build.on_fix_yes(con, NOW, {"key": "gone", "kind": "job_failed"})


def test_with_the_order_on_a_build_is_requested_by_itself_as_before(con):
    build.ensure(con)
    standing.set_on(con, NOW, "autofix", True)
    _fault(con, NOW - timedelta(hours=1))
    assert build.scan_problems(con, NOW) == 1
    assert con.execute("SELECT count(*) FROM operator_builds_s87").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM cards_s85 WHERE kind='decision:fix_offer'").fetchone()[0] == 0


# --- repeating plans ----------------------------------------------------------------------------------------------------------------------------------------

STEPS = [{"text": "Read what moved in his holdings", "uses": "portfolio"}, {"text": "Say only what he should look at", "uses": "stock_facts"}]


def _bind(monkeypatch, ran):
    plans.bind(type("R", (), {"bump": lambda self, *a: None, "data_root": None})())
    monkeypatch.setattr(plans, "RUN_STEP", lambda con_, plan, step, prior: (ran.append((plan["plan_id"], step["n"])) or f"result {step['n']}", 100))


def test_a_repeating_plan_runs_again_on_his_one_yes_and_stops_when_he_says(con, monkeypatch):
    ran = []
    _bind(monkeypatch, ran)
    assert plans.propose(con, NOW, "Evening check of my holdings", STEPS, repeat="hourly").startswith("Not proposed")
    msg = plans.propose(con, NOW, "Evening check of my holdings", STEPS, repeat="daily")
    pid = plans.listing(con)[0]["plan_id"]
    assert "repeats daily" in msg and plans.get(con, pid)["repeat"] == "daily" and ran == []
    card = con.execute("SELECT m.text FROM cards_s85 c JOIN chat_messages m ON m.msg_id=c.msg_id WHERE c.kind='decision:plan'").fetchone()[0]
    assert "REPEATS daily" in card and f"stop plan #{pid}" in card
    assert plans.repeat_due(con, NOW + timedelta(days=30)) == 0                                                      # nothing before his Yes, however long it waits
    plans.on_yes(con, NOW, {"plan_id": pid})
    assert _wait(lambda: plans.get(con, pid)["status"] == "done") and _wait(lambda: plans.get(con, pid)["next_due"] is not None)
    assert plans.get(con, pid)["runs"] == 1 and plans.repeat_due(con, datetime.now()) == 0                           # not due yet
    later = datetime.now() + timedelta(days=1, minutes=5)
    assert plans.repeat_due(con, later) == 1
    new = plans.listing(con)[0]["plan_id"]
    assert new != pid and _wait(lambda: plans.get(con, new)["status"] == "done") and _wait(lambda: plans.get(con, new)["runs"] == 2)
    assert [s["text"] for s in plans.get(con, new)["steps"]] == [s["text"] for s in STEPS] and ran == [(pid, 1), (pid, 2), (new, 1), (new, 2)]
    assert plans.repeat_due(con, datetime.now() + timedelta(hours=23)) == 0                                          # the next one is a day after THIS run finished: never doubled
    assert plans.cancel(con, new) == "Stopped: it will not run again."
    assert plans.get(con, new)["repeat"] is None and plans.repeat_due(con, later + timedelta(days=9)) == 0
    assert plans.cancel(con, new) == "Nothing to cancel."


def test_a_closed_laptop_skips_runs_and_never_stacks_them(con, monkeypatch):
    ran = []
    _bind(monkeypatch, ran)
    plans.propose(con, NOW, "Weekly look at the watchlist", STEPS, repeat="weekly")
    pid = plans.listing(con)[0]["plan_id"]
    plans.start(con, NOW, pid)
    assert _wait(lambda: plans.get(con, pid)["next_due"] is not None)
    assert plans.repeat_due(con, datetime.now() + timedelta(days=40)) == 1                                           # five weeks away: one run, not five
    assert _wait(lambda: len(ran) == 4) and len(plans.listing(con)) == 2


def test_a_failed_run_stops_the_repeating_and_says_so(con, monkeypatch):
    plans.bind(type("R", (), {"bump": lambda self, *a: None, "data_root": None})())

    def boom(con_, plan, step, prior):
        raise RuntimeError("the tool broke")
    monkeypatch.setattr(plans, "RUN_STEP", boom)
    plans.propose(con, NOW, "Evening check of my holdings", STEPS, repeat="daily")
    pid = plans.listing(con)[0]["plan_id"]
    plans.start(con, NOW, pid)
    assert _wait(lambda: plans.get(con, pid)["status"] == "failed") and _wait(lambda: pid not in plans._RUNNING)
    assert plans.get(con, pid)["repeat"] is None and plans.repeat_due(con, datetime.now() + timedelta(days=3)) == 0
    assert con.execute("SELECT count(*) FROM chat_messages WHERE text LIKE '%has stopped repeating%'").fetchone()[0] == 1


def test_a_plan_without_repeat_is_as_before(con, monkeypatch):
    ran = []
    _bind(monkeypatch, ran)
    plans.propose(con, NOW, "Test the pairs idea", STEPS)
    pid = plans.listing(con)[0]["plan_id"]
    plans.start(con, NOW, pid)
    assert _wait(lambda: plans.get(con, pid)["status"] == "done")
    p = plans.get(con, pid)
    assert p["repeat"] is None and p["next_due"] is None and plans.repeat_due(con, datetime.now() + timedelta(days=30)) == 0
    assert plans.cancel(con, pid) == "Nothing to cancel."


# --- the chat and the screen can switch an order ------------------------------------------------------------------------------------------------------------

def test_the_chat_action_and_the_screen_switch_an_order(con):
    from pflab.app import s89
    with pytest.raises(ValueError):
        actions.check(con, NOW, "standing_set", {"order": "desk", "on": "no"})
    with pytest.raises(ValueError):
        actions.check(con, NOW, "standing_set", {"order": "trade", "on": True})
    p = actions.check(con, NOW, "standing_set", {"order": "desk", "on": False})
    assert "Switch OFF 'Daily desk'" in actions.describe("standing_set", p) and standing.is_on(con, "desk")           # describing changes nothing
    assert actions.apply(con, NOW, {"kind": "standing_set", "payload": p}) == "'Daily desk' is now OFF." and not standing.is_on(con, "desk")
    j = s89.agents(con, NOW)
    assert [d["key"] for d in j["standing"]] == ["cases", "desk", "weekly", "autofix"] and {d["key"]: d["on"] for d in j["standing"]}["desk"] is False
    assert s89.agents_set(con, NOW, {"order": "desk", "on": True})["on"] is True and standing.is_on(con, "desk")
    with pytest.raises(ValueError):
        s89.agents_set(con, NOW, {"order": "desk", "on": "yes"})


def test_the_week_check_reads_an_order_and_a_fault_counts_as_on(con, monkeypatch):
    from pflab.service import week_check
    standing.set_on(con, NOW, "desk", False)
    assert week_check._order_on(con, "desk") is False and week_check._order_on(con, "cases") is True
    monkeypatch.setattr(standing, "is_on", lambda con, key: 1 / 0)
    assert week_check._order_on(con, "desk") is True
