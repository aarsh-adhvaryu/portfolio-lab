"""S68 P1: the spend policy is configuration read on every call; the bounded acceptance window lifts the day limits (not the cap) and ends by
itself; a pass refused or stopped part-way is `stopped`, its cases WAIT with a resume time and use no attempt. Synthetic."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.agents import analyst as an
from pflab.hq import brain, cases, egress, governor as gv, service, tools as tl
from pflab.hq.desk import Desk
from pflab.pm import store

AAA = "INE000A01011"
NOW = datetime(2026, 10, 31, 15, 0)
CFG = {"model": an.MODEL, "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True, "tijori_to_analyst": True}
WINDOW = {**CFG, "acceptance": {"until": datetime(2026, 11, 7, 23, 59), "since": datetime(2026, 10, 31), "cap_rupees": 1500}}


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                 VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'AAA Limited', 'synthetic', now())""", [AAA])
    return c


def _spend(con, agent, inr, at=NOW, turn=1, his=False, status="done", cid=None):
    n = con.execute("SELECT coalesce(max(call_id), 0) + 1 FROM api_calls").fetchone()[0]
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, cost_inr, agent, turn, his_order) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [n, at, "live", gv.OPUS, "q", "", "{}", status, inr, agent, turn, his])


def test_the_live_failure_the_day_limit_refuses_background_work_with_the_month_nearly_free(con):
    """5 cases sat queued: 'the brain have spent ~Rs 112.6 today ... would pass their Rs 120 a day'."""
    _spend(con, "brain", 112.6)
    with pytest.raises(gv.BudgetRefused, match="a day") as e:
        gv.check(con, "brain", 17.2, 5000, 4000, NOW, "normal", CFG)
    assert e.value.resume_at > NOW and e.value.resume_at.day == 1                    # it names when it can change: tomorrow


def test_the_window_lifts_day_limits_but_not_its_own_cap(con):
    _spend(con, "brain", 112.6)
    _spend(con, "brain", 1.0, turn=1)
    gv.check(con, "brain", 17.2, 5000, 4000, NOW, "economy", WINDOW)                  # two passes a day and Rs 40 a day: not in the window
    _spend(con, "brain", 1490.0)
    with pytest.raises(gv.BudgetRefused, match="acceptance window's cap") as e:
        gv.check(con, "brain", 17.2, 5000, 4000, NOW, "economy", WINDOW)
    assert e.value.resume_at == datetime(2026, 11, 8, 0, 0)                          # after the window, not before
    # the monthly cap of the normal policy is NOT what stops it inside the window: Rs 2,500 is already passed here
    assert an.month_spend_inr(con, NOW) > 1500


def test_the_window_ends_by_itself(con):
    after = datetime(2026, 11, 8, 9, 0)
    _spend(con, "brain", 112.6, at=after)
    assert an.acceptance(WINDOW, after) is None and an.acceptance(WINDOW, NOW) is not None
    with pytest.raises(gv.BudgetRefused, match="a day"):                             # the normal policy again, unchanged
        gv.check(con, "brain", 17.2, 5000, 4000, after, "normal", {**WINDOW, "cap": 2500.0})
    # a window with no cap, a past end or a start in the future is no window
    assert an.acceptance({"acceptance": {"until": datetime(2026, 11, 7), "cap_rupees": 0}}, NOW) is None
    assert an.acceptance({"acceptance": {"until": datetime(2026, 11, 7), "since": datetime(2026, 11, 2), "cap_rupees": 5}}, NOW) is None


def test_limits_are_configuration_read_on_every_call(con):
    _spend(con, "brain", 112.6)
    raised = {**CFG, "policy": {"day_rupees": {"brain": 400}, "passes": {"brain": {"normal": 20}}}}
    gv.check(con, "brain", 17.2, 5000, 4000, NOW, "normal", raised)                  # the same state that refused above now passes
    assert gv.layer_limits(CFG, "brain") == (0.15, 40.0) and gv.passes_per_day(CFG, "brain", "normal") == 3     # S70: two passes a day in economy, three in normal (was 4 and 8)
    assert gv.layer_limits(raised, "brain") == (0.15, 400.0)


def test_his_questions_do_not_use_up_the_systems_day(con):
    for _ in range(4):
        _spend(con, "brain", 20.0, his=True)
    gv.check(con, "brain", 17.2, 5000, 4000, NOW, "economy", CFG)                    # four of his passes: the system's four are untouched
    assert gv.calls_today(con, "brain", NOW) == 0


def test_a_pass_already_begun_is_not_stopped_by_the_days_rupees(con):
    _spend(con, "brain", 118.0)
    gv.check(con, "brain", 17.2, 5000, 4000, NOW, "normal", CFG, turn=2)             # turn 2: only the cap can stop it
    with pytest.raises(gv.BudgetRefused, match="a day"):
        gv.check(con, "brain", 17.2, 5000, 4000, NOW, "normal", CFG, turn=1)


def test_work_tools_get_more_inside_the_window_and_attention_tools_never(con, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: WINDOW)
    assert tl.daily_cap(con, "case_calculate", NOW) == 3 * tl.WINDOW_FACTOR
    assert tl.daily_cap(con, "tell_investor", NOW) == 3 and tl.daily_cap(con, "ask_investor", NOW) == 2
    monkeypatch.setattr(an, "config", lambda: CFG)
    assert tl.daily_cap(con, "case_calculate", NOW) == 3


def test_every_call_is_tagged_with_its_policy(con):
    from pflab.hq import llm

    class C:
        messages = SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=100))
        beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(
            content=[SimpleNamespace(type="text", text="x")], stop_reason="end_turn", model=gv.OPUS,
            usage=SimpleNamespace(input_tokens=100, output_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0))))
    p = {"model": gv.OPUS, "max_tokens": 500, "messages": [{"role": "user", "content": "hi"}]}
    llm.call(con, "brain", p, C(), now=NOW, mode="normal", private_text="", gate=egress.Gate(), cfg=WINDOW, his_order=True)
    llm.call(con, "brain", p, C(), now=NOW, mode="normal", private_text="", gate=egress.Gate(), cfg=CFG)
    assert con.execute("SELECT policy, his_order FROM api_calls ORDER BY call_id").fetchall() == [("acceptance", True), ("normal", False)]


def test_the_dev_cap_key_is_the_one_a_beta_edit_changes(tmp_path, monkeypatch):
    from pflab import release
    from pflab.plan import prefs
    (tmp_path / "api_budget.toml").write_text("[api]\nmonthly_cap_rupees = 2500\ndev_monthly_cap_rupees = 0\n", encoding="utf-8")
    monkeypatch.setattr(prefs, "_pm", lambda: tmp_path)
    monkeypatch.setattr(release, "channel", lambda: "beta")
    prefs._set_cap(300, NOW)
    t = (tmp_path / "api_budget.toml").read_text(encoding="utf-8")
    assert "dev_monthly_cap_rupees = 300" in t and "monthly_cap_rupees = 2500" in t


# --- a pass refused or stopped part-way ----------------------------------------------------------------------------------------------

def _tool_msg(*calls):
    content = [SimpleNamespace(type="thinking", thinking="", signature="sig")]
    content += [SimpleNamespace(type="tool_use", id=f"tu{k}", name=n, input=i) for k, (n, i) in enumerate(calls)]
    return SimpleNamespace(content=content, stop_reason="tool_use", model=gv.OPUS,
                           usage=SimpleNamespace(input_tokens=800, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class _Msgs:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def count_tokens(self, **kw):
        return SimpleNamespace(input_tokens=1000)

    def create(self, **kw):
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Fake:
    def __init__(self, replies=()):
        self.messages = _Msgs(replies)
        self.beta = SimpleNamespace(messages=self.messages)


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(brain, "portfolio_view", lambda con, asof: ("PORTFOLIO: AAA | equity | 9.0 | Rs 90,000 | +50.0", {"AAA": AAA}))
    monkeypatch.setattr(brain, "watch_view", lambda con: ("WATCH LIST: none", {}))
    monkeypatch.setattr(tl.Ctx, "book", lambda self: None)
    monkeypatch.setattr(brain, "due_scheduled", lambda con, now, cal=None: None)
    monkeypatch.setattr(an, "config", lambda: CFG)


def _rt(con, tmp_path):
    return Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None,
                {"brain": "normal", "preset": "full", "telegram_send": False, "drop_watch": True}, clock=lambda: NOW)


def test_a_pass_stopped_by_the_cap_at_turn_two_is_stopped_and_its_case_waits_without_an_attempt(con, tmp_path, quiet):
    cid, _ = cases.open_case(con, NOW, "Is anything unusual in AAA?", subject="AAA", isin=AAA)
    rt = _rt(con, tmp_path)
    def pricey(*a, **k):                    # every turn costs Rs 400 of a Rs 700 cap: the second would pass it
        return 400.0
    tight = {**CFG, "cap": 700.0, "ask_above": 1000.0, "policy": {"share": {"brain": 1.0}, "day_rupees": {"brain": 5000}}}
    import pytest as _p
    with _p.MonkeyPatch.context() as m:
        m.setattr(gv, "cost_inr", pricey)
        pid = brain.think(rt, "case", [], Fake([_tool_msg(("journal", {}))]), egress.Gate(), cfg=tight, case_ids=[cid])
    row = con.execute("SELECT status, error FROM hq_passes WHERE pass_id=?", [pid]).fetchone()
    assert row[0] == "stopped" and "stopped before turn 2" in row[1], row                  # not "done"
    c = cases.get(con, cid)
    assert c["status"] == "waiting_budget" and c["attempts"] == 0 and c["next_review"] > NOW, (c["status"], c["error"], row)
    assert cases.due(con, NOW) == []                                                   # not asked again until it can change
    assert cid in cases.due(con, c["next_review"] + timedelta(minutes=1))               # and picked up when it can
    assert con.execute("SELECT count(*) FROM memory WHERE kind='state'").fetchone()[0] >= 1   # the pass's checkpoint is kept


def test_a_provider_failure_mid_pass_makes_the_case_wait_for_the_provider_not_fail(con, tmp_path, quiet):
    cid, _ = cases.open_case(con, NOW, "Is anything unusual in AAA?", subject="AAA", isin=AAA)
    rt = _rt(con, tmp_path)
    pid = brain.think(rt, "case", [], Fake([_tool_msg(("journal", {})), ConnectionError("provider down")]), egress.Gate(), cfg=CFG,
                      case_ids=[cid])
    assert con.execute("SELECT status FROM hq_passes WHERE pass_id=?", [pid]).fetchone()[0] == "stopped"
    c = cases.get(con, cid)
    assert c["status"] == "waiting_provider" and c["attempts"] == 0


def test_a_bug_mid_pass_still_counts_as_a_failed_attempt(con, tmp_path, quiet):
    cid, _ = cases.open_case(con, NOW, "Is anything unusual in AAA?", subject="AAA", isin=AAA)
    rt = _rt(con, tmp_path)
    brain.think(rt, "case", [], Fake([_tool_msg(("journal", {})), ZeroDivisionError("bug")]), egress.Gate(), cfg=CFG, case_ids=[cid])
    c = cases.get(con, cid)
    assert c["status"] == "retry" and c["attempts"] == 1


def test_the_policy_view_shows_every_limit_and_the_windows_spend(con, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: WINDOW)
    _spend(con, "brain", 112.6)
    v = gv.policy_view(con, NOW, "normal")
    names = {r["limit"] for r in v["limits"]}
    assert v["policy"] == "acceptance" and v["window"]["spent"] == pytest.approx(112.6) and v["window"]["left"] == pytest.approx(1387.4)
    assert {"monthly cap", "brain layer, rupees a day", "brain, calls a day (normal)", "tool case_calculate, a day"} <= names
    day = next(r for r in v["limits"] if r["limit"] == "brain layer, rupees a day")
    assert day["state"] == "lifted by the acceptance window" and day["live"] is True
    monkeypatch.setattr(an, "config", lambda: CFG)
    v = gv.policy_view(con, NOW, "normal")
    assert v["policy"] == "normal" and v["window"] is None and all(r["state"] == "in force" for r in v["limits"])


def test_the_analysts_own_calls_are_tagged_with_the_policy_too(con, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: WINDOW)
    cid = an._log(con, an.Request("q", "workshop"), "live", an.MODEL, "done", NOW, {"model": an.MODEL}, 3.0)
    assert con.execute("SELECT policy FROM api_calls WHERE call_id=?", [cid]).fetchone()[0] == "acceptance"


def test_a_call_a_killed_process_left_sending_is_closed_at_the_next_start_and_still_counted(con, tmp_path):
    _spend(con, "brain", 7.0, status="sending")
    rt = Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {"brain": "normal"}, clock=lambda: NOW)
    (tmp_path / "pm").mkdir(exist_ok=True)
    out = service.start(rt)
    assert out["calls_closed"] == 1
    st, err = con.execute("SELECT status, error FROM api_calls").fetchone()
    assert st == "refused" and "interrupted" in err
    assert an.month_spend_inr(con, NOW) == 7.0                                      # the estimate still counts against the cap
