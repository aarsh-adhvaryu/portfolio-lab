"""S82 C8 (fill-cost calibration, automatic) and C9 (the first real strategist session in the app). Synthetic fills, scripted fake model (rule 7: no real data, no paid call)."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from pflab.core import card, fills, fills_cal, screens, session
from pflab.lab import first_session_s82 as first
from pflab.lab import service as lab
from pflab.lab import strategist
from tests.test_s80_core import AAA, NOW, con  # noqa: F401  (the fixture)
from tests.test_s81_session import CCC, MON, day_bars, db, no_exits  # noqa: F401  (fixtures)

T0 = datetime(2026, 11, 12, 10, 0)


# --- helpers ------------------------------------------------------------------------------------------------------------------------------------

def put_fills(con, n: int, source="live", cfg=None, seed=0, start_id=None, outliers=0, adv_lo=1.5e7, adv_hi=2.0e9, spread_adv=True):
    """`n` synthetic fills priced by the model `fills.model` under `cfg` (the 'truth'), liquidity spread over the scale, orders up to ~8% of a day's turnover."""
    rng = np.random.default_rng(seed)
    cfg = cfg or fills.settings()
    base = int(con.execute("SELECT coalesce(max(fill_id), 0) FROM session_fills_s81").fetchone()[0]) if start_id is None else start_id
    for i in range(n):
        adv = float(np.exp(rng.uniform(np.log(adv_lo), np.log(adv_hi)))) if spread_adv else 1.0e8
        order = float(adv * rng.uniform(0.0005, 0.08))
        side = "buy" if rng.random() < 0.5 else "sell"
        quote = float(rng.uniform(50, 2000))
        m = fills.model(order, adv, cfg)
        px = fills.price_for(side, quote, m)
        if i < outliers:                                    # an odd fill: 800 bp against the order
            px = quote * (1.08 if side == "buy" else 0.92)
        con.execute("INSERT INTO session_fills_s81 (fill_id, ts, market, day, isin, symbol, side, qty, quote, price, half_spread_bps, slippage_bps, adv_rupees, order_rupees, participation, "
                    "cost_rupees, kind, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [base + i + 1, T0, "IN", T0.date(), CCC, "CCC", side, order / quote, quote, px, m["half_spread_bps"], m["slippage_bps"], adv, order, order / adv, 0.0, "test", source])


def values(con):
    return {k: fills.settings(con)[k] for k in fills.FITTED}


# --- C8: fill-cost calibration ------------------------------------------------------------------------------------------------------------------

def test_under_30_real_fills_the_defaults_stand_and_the_job_says_how_many(con):
    put_fills(con, 12)
    r = fills_cal.run(con, T0)
    assert r["waiting"] == "waiting: 12 of 30 real fills" and r["source"] == "defaults"
    assert con.execute("SELECT count(*) FROM fills_calibration_s82").fetchone()[0] == 0
    cs = fills.calibration_status(con)
    assert cs["source"] == "defaults" and cs["n_fills"] == 12 and cs["as_of"] is None and "12 of 30" in cs["text"]
    assert values(con) == {k: fills.settings()[k] for k in fills.FITTED}


def test_test_drill_and_old_rows_are_never_real_fills(con):
    put_fills(con, 29, "live")
    put_fills(con, 40, "injected")
    put_fills(con, 20, "sim")
    put_fills(con, 20, None)                                    # a row written before S82 has no source
    assert fills.real_fill_count(con) == 29
    assert fills_cal.run(con, T0)["waiting"] == "waiting: 29 of 30 real fills"
    put_fills(con, 1, "live")
    assert "waiting" not in fills_cal.run(con, T0)


def test_30_real_fills_fit_inside_the_stated_bounds_and_are_logged(con):
    truth = dict(fills.settings(), half_spread_illiquid_bps=40.0, half_spread_liquid_bps=2.0, impact_bps=40.0)
    put_fills(con, 120, cfg=truth, seed=3)
    r = fills_cal.run(con, T0)
    assert r["accepted"] and r["n_used"] == 120 and set(r["fitted"]) == set(fills.FITTED)
    bd = fills.bounds()
    for k in fills.FITTED:
        assert bd[k][0] - 1e-9 <= r["new"][k] <= bd[k][1] + 1e-9
    assert r["new"]["half_spread_illiquid_bps"] == pytest.approx(40.0, rel=0.15)           # the truth is recovered (the paisa rounding is the only noise)
    assert r["new"]["impact_bps"] == pytest.approx(40.0, rel=0.15)
    assert r["new"]["half_spread_liquid_bps"] == pytest.approx(2.0, abs=0.8)
    row = con.execute("SELECT status, accepted, n_fills, n_used, old_json, new_json, fit_json FROM fills_calibration_s82").fetchone()
    assert row[0] == "accepted" and row[1] and row[2] == 120
    assert json.loads(row[4])["impact_bps"] == 25.0 and json.loads(row[5])["impact_bps"] == pytest.approx(r["new"]["impact_bps"])
    fit = json.loads(row[6])
    assert fit["residual_rms_bps"] is not None and fit["interval"]["impact_bps"][0] <= r["new"]["impact_bps"] <= fit["interval"]["impact_bps"][1]
    # fills.py READS the accepted row
    assert fills.settings(con)["impact_bps"] == pytest.approx(r["new"]["impact_bps"])
    cs = fills.calibration_status(con)
    assert cs["source"] == "calibrated" and cs["n_fills"] == 120 and cs["as_of"] == "2026-11-12" and "calibrated from 120 real fills" in cs["text"]
    assert fills.settings()["impact_bps"] == 25.0                                           # the file's defaults are untouched


def test_the_calibrated_numbers_price_the_next_fill(db):
    truth = dict(fills.settings(), half_spread_illiquid_bps=50.0, impact_bps=50.0)
    put_fills(db, 80, cfg=truth, seed=5)
    fills_cal.run(db, T0)
    t = datetime.combine(MON, time(11, 0))
    liq = {"adv_rupees": 2.0e7, "typical_minute_volume": 1e4}
    r = fills.execute(db, t, CCC, "buy", quote=100.0, qty=300, kind="test", liq=liq)
    assert r["half_spread_bps"] > 20.0                                                       # the defaults would have charged about 23 bp at this liquidity; the fit about 45
    d = fills.model(300 * 100.0, 2.0e7)
    assert r["half_spread_bps"] > d["half_spread_bps"] + 5


def test_odd_fills_cannot_break_the_model(con):
    put_fills(con, 90, seed=7, outliers=6)                                                   # six fills 800 bp away from the quote
    r = fills_cal.run(con, T0)
    assert r["accepted"]
    bd = fills.bounds()
    for k in fills.FITTED:
        assert bd[k][0] - 1e-9 <= r["new"][k] <= bd[k][1] + 1e-9
    assert r["new"]["half_spread_illiquid_bps"] == pytest.approx(25.0, rel=0.25) and r["new"]["impact_bps"] == pytest.approx(25.0, rel=0.35)
    # an absurd world is held at the bounds
    con.execute("DELETE FROM session_fills_s81")
    con.execute("DELETE FROM fills_calibration_s82")
    put_fills(con, 60, cfg=dict(fills.settings(), half_spread_illiquid_bps=900.0, impact_bps=900.0, half_spread_liquid_bps=0.0), seed=8)
    r = fills_cal.run(con, T0)
    bd = fills.bounds()
    assert r["new"]["half_spread_illiquid_bps"] == pytest.approx(bd["half_spread_illiquid_bps"][1], rel=1e-3)
    assert r["new"]["impact_bps"] <= bd["impact_bps"][1] + 1e-9 and r["new"]["half_spread_liquid_bps"] >= 0.5 - 1e-9


def test_the_bounds_are_half_to_three_times_the_default_with_the_floors():
    b = fills.bounds({**fills.DEFAULTS, "half_spread_liquid_bps": 0.6, "impact_bps": 8.0})
    assert b["half_spread_liquid_bps"] == pytest.approx((0.5, 1.8)) and b["impact_bps"] == pytest.approx((5.0, 24.0))
    d = fills.bounds()
    assert d["half_spread_illiquid_bps"] == (12.5, 75.0) and d["impact_bps"] == (12.5, 75.0) and d["half_spread_liquid_bps"] == (0.5, 3.0)


def test_a_stored_row_outside_the_bounds_is_clamped_on_read(con):
    con.execute("INSERT INTO fills_calibration_s82 (cal_id, made_at, market, status, accepted, n_fills, n_used, new_json) VALUES (1, ?, 'IN', 'accepted', TRUE, 50, 50, ?)",
                [T0, json.dumps({"half_spread_liquid_bps": 0.0, "half_spread_illiquid_bps": 1e6, "impact_bps": 1.0})])
    v = values(con)
    assert v["half_spread_liquid_bps"] == 0.5 and v["half_spread_illiquid_bps"] == 75.0 and v["impact_bps"] == 12.5


def test_a_fit_runs_monthly_not_more_often(con):
    put_fills(con, 60, seed=1)
    a = fills_cal.run(con, T0)
    assert a["accepted"]
    b = fills_cal.run(con, T0 + timedelta(days=10))
    assert "skipped" in b and con.execute("SELECT count(*) FROM fills_calibration_s82").fetchone()[0] == 1
    c = fills_cal.run(con, T0 + timedelta(days=31))
    assert c["accepted"] and con.execute("SELECT count(*) FROM fills_calibration_s82").fetchone()[0] == 2


def test_fills_that_cover_one_liquidity_only_fit_what_they_can(con):
    put_fills(con, 40, seed=2, adv_lo=1.0e9, adv_hi=2.0e9)                                   # only liquid names: the illiquid half spread cannot be known
    r = fills_cal.run(con, T0)
    assert r["accepted"] and "half_spread_illiquid_bps" in r["frozen"] and r["new"]["half_spread_illiquid_bps"] == 25.0


def test_a_fill_with_no_known_liquidity_does_not_enter_the_fit(con):
    put_fills(con, 35, seed=4)
    con.execute("UPDATE session_fills_s81 SET adv_rupees = NULL WHERE fill_id <= 10")
    assert fills.real_fill_count(con) == 35 and len(fills_cal.real_fills(con)) == 25
    r = fills_cal.run(con, T0)
    assert "waiting" in r and "35" in r["waiting"] and "25 with a known liquidity" in r["waiting"]


def test_the_session_marks_live_quotes_real_and_injected_ones_not(db, no_exits):
    """Through a tactical view (carried out in session), so the test does not depend on the swing triggers."""
    from pflab.core import views
    from pflab.core import session as ses
    from tests.test_s80_core import DAYS
    from tests.test_s81_session import FakeKite
    liq = {CCC: {"adv_rupees": 1.0e9, "typical_minute_volume": 1e4}}
    ok = views.issue(db, NOW, DAYS[-1], direction=1, names=["CCC"], share_of_budget=0.5, horizon_sessions=10, stop_pct=8.0, reason="CCC looks cheap against its sector after the result",
                     isin_of=lambda s: {"CCC": CCC}.get(s))
    assert ok["ok"]
    bars = {CCC: day_bars(MON, lambda i: 100.0).iloc[:46]}
    t = datetime.combine(MON, time(10, 0))
    r = ses.run_once(db, t, quotes={CCC: 100.0}, bars=bars, liq=liq)                          # injected quotes: a replay or a test
    assert len(r["fills"]) == 1
    assert db.execute("SELECT source FROM session_fills_s81").fetchone()[0] == "injected"
    assert fills.real_fill_count(db) == 0
    db.execute("UPDATE core_views_s80 SET executed_json = NULL")                              # let the view run once more, now on a live (Kite) quote
    r = ses.run_once(db, t + timedelta(minutes=5), kite=FakeKite(), bars=bars, liq=liq)
    assert len(r["fills"]) == 1
    assert [x[0] for x in db.execute("SELECT source FROM session_fills_s81 ORDER BY fill_id").fetchall()] == ["injected", "live"]
    assert fills.real_fill_count(db) == 1


def test_the_job_is_registered_and_reports(con):
    import pflab.service.tasks_s79_fills82  # noqa: F401  (registers the job on import)
    from pflab.service.jobs import REGISTRY
    j = REGISTRY["fills_calibrate"]
    ctx = SimpleNamespace(con=con, now=T0)
    assert j.fn(ctx)["waiting"] == "waiting: 0 of 30 real fills"


def test_today_carries_the_fills_and_the_strategist_blocks(con):
    v = screens.view(con, T0)
    assert v["fills"]["source"] == "defaults" and "defaults" in v["fills"]["text"]
    assert v["strategist"]["note"] is None
    x = card.today_extras(con)
    assert set(x) == {"fills", "strategist"}


# --- C9: the first real strategist session ------------------------------------------------------------------------------------------------------

class Msg:
    def __init__(self, blocks, stop="end_turn"):
        self.content, self.stop_reason, self.model = blocks, stop, "claude-opus-5-5"
        self.usage = SimpleNamespace(input_tokens=2000, output_tokens=400, cache_read_input_tokens=0, cache_creation_input_tokens=0)


class FakeClient:
    """A scripted model: the first turn writes a note, the second ends."""
    def __init__(self):
        self.n = 0
        self.messages = SimpleNamespace(count_tokens=lambda **k: SimpleNamespace(input_tokens=3000))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **p):
        self.n += 1
        if self.n == 1:
            blk = SimpleNamespace(type="tool_use", id="tu1", name="write_note", input={"text": "First session: the allocation stands; nothing in the lab beats the index yet, so no variant is proposed this week."})
            return Msg([blk], "tool_use")
        return Msg([SimpleNamespace(type="text", text="Done.")])


def _api_cfg(cap=500.0):
    return {"model": "claude-opus-5-5", "cap": cap, "ask_above": 1000.0, "usd_inr": 90.0, "adopted": True, "policy": {}, "acceptance": {}, "paper": {}, "tijori_to_analyst": True, "counted_since": None}


@pytest.fixture
def paid(monkeypatch):
    """A cap with room, no real budget file; every call goes through the real governor against the test store."""
    from pflab.agents import analyst as an
    monkeypatch.setattr(an, "config", lambda path=None: _api_cfg())
    return an


@pytest.fixture
def scripted(monkeypatch, paid):
    """run_session's heavy parts replaced by a script (the real llm.call, governor and egress stay)."""
    ran = {"n": 0}

    def fake_run(con, pm_dir, root, now, reason, *, client, **kw):
        ran["n"] += 1
        sid = con.execute("SELECT coalesce(max(session_id),0)+1 FROM core_sessions_s80").fetchone()[0]
        con.execute("INSERT INTO core_sessions_s80 (session_id, started_at, reason, status, model, budget_inr, cost_inr, lab_runs, variants, challengers) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [sid, now, reason[:300], "done", "claude-opus-5-5", 300.0, 12.5, 1, 1, 0])
        lab.write_note(con, now, sid, "First session: the allocation stands; nothing in the lab beats the index yet.")
        return {"session_id": sid, "status": "done", "cost_inr": 12.5, "lab_runs": 1}
    monkeypatch.setattr(strategist, "run_session", fake_run)
    return ran


def tick(con, tmp_path, now, client_fn=lambda: object()):
    return strategist.tick(con, tmp_path, tmp_path, now, client_fn, data={}, box=None)


def test_the_first_session_fires_once_and_a_second_open_does_not(con, tmp_path, scripted, monkeypatch):
    monkeypatch.setattr(strategist, "due", lambda c, n: [])                                  # isolate the trigger from the weekly one
    a = tick(con, tmp_path, T0)
    assert scripted["n"] == 1 and a["first_session_s82"] == "done"
    st = first.state(con)
    assert st["status"] == "done" and st["session_id"] == 1 and st["cost_inr"] == 12.5
    b = tick(con, tmp_path, T0 + timedelta(days=3))                                         # the next open
    assert scripted["n"] == 1 and b.get("nothing_due")
    assert first.reasons(con, T0 + timedelta(days=30)) == []


def test_the_first_session_with_the_weekly_one_is_still_one_session(con, tmp_path, scripted):
    out = tick(con, tmp_path, T0)
    assert scripted["n"] == 1 and out["first_session_s82"] == "done"
    assert first.REASON not in strategist.due(con, T0 + timedelta(hours=2)) and first.reasons(con, T0 + timedelta(hours=2)) == []


def test_a_missing_key_records_waiting_and_tries_again_at_the_next_open(con, tmp_path, scripted, monkeypatch):
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    def no_key():
        raise RuntimeError("no API key in secrets.toml")
    out = tick(con, tmp_path, T0, client_fn=no_key)
    assert scripted["n"] == 0 and "no cloud client" in out["skipped"]
    st = first.state(con)
    assert st["status"] == "waiting" and st["attempts"] == 1 and "no cloud client" in st["detail"]
    assert first.reasons(con, T0 + timedelta(hours=2)) == []                                 # not again the same day (no spam)
    assert tick(con, tmp_path, T0 + timedelta(hours=3), client_fn=no_key).get("nothing_due")
    out = tick(con, tmp_path, T0 + timedelta(days=1))                                        # the key is there at the next open
    assert scripted["n"] == 1 and out["first_session_s82"] == "done" and first.state(con)["attempts"] == 2


def test_an_exhausted_cap_records_waiting_and_never_calls_the_model(con, tmp_path, scripted, monkeypatch):
    from pflab.agents import analyst as an
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    monkeypatch.setattr(an, "config", lambda path=None: _api_cfg(cap=500.0))
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, status, cost_inr, agent, turn) VALUES (1, ?, 'live', 'm', 't', 'q', 's', '{}', 'done', 490.0, 'strategist', 1)", [T0])
    made = []
    out = tick(con, tmp_path, T0 + timedelta(minutes=1), client_fn=lambda: made.append(1) or object())
    assert scripted["n"] == 0 and not made and "paid cap is used up" in out["first_session_s82"]
    assert first.state(con)["status"] == "waiting"
    monkeypatch.setattr(an, "config", lambda path=None: _api_cfg(cap=0.0))
    out = tick(con, tmp_path, T0 + timedelta(days=1))
    assert scripted["n"] == 0 and "no paid cap" in out["first_session_s82"]


def test_a_failed_session_after_spending_is_retried_at_most_twice(con, tmp_path, monkeypatch, paid):
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    monkeypatch.setattr(strategist, "run_session", lambda con, *a, **k: {"session_id": 9, "status": "failed", "cost_inr": 3.0})
    for k in range(4):
        tick(con, tmp_path, T0 + timedelta(days=k))
    st = first.state(con)
    assert st["status"] == "waiting" and st["paid_attempts"] == 2 and st["attempts"] == 2


def test_the_kill_switch_and_the_strategist_switch_stop_it(con, tmp_path, scripted, monkeypatch):
    from pflab import core
    monkeypatch.setattr(core, "strategist_on", lambda: False)
    assert tick(con, tmp_path, T0) == {"off": True} and scripted["n"] == 0 and first.state(con) is None


def test_the_real_session_path_with_a_scripted_model_writes_a_note_and_the_trigger_records_done(con, tmp_path, paid, monkeypatch):
    """The real run_session, llm.call, governor and egress check; only the SDK client is scripted."""
    from pflab import core
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    cl = FakeClient()
    out = strategist.tick(con, tmp_path, tmp_path, T0, lambda: cl, data={}, box=None)
    s = out["session"]
    assert s["session_id"] and s["status"] in ("done", "wasted") and s["cost_inr"] > 0, out
    assert first.state(con)["status"] == "done"
    n = lab.latest_strategist_note(con)
    assert n["note"].startswith("First session") and n["cost_rupees"] == pytest.approx(s["cost_inr"], abs=0.01) and n["when"].startswith("2026-11-12")


def test_latest_strategist_note_and_the_report_line(con):
    assert lab.latest_strategist_note(con) == {"when": None, "note": None, "proposal": None, "cost_rupees": None, "session_id": None, "status": None}
    con.execute("INSERT INTO core_sessions_s80 (session_id, started_at, finished_at, reason, status, model, budget_inr, cost_inr, lab_runs, variants, challengers) VALUES (4, ?, ?, 'x', 'done', 'm', 300, 41.25, 1, 1, 0)",
                [T0, T0 + timedelta(minutes=20)])
    lab.write_note(con, T0 + timedelta(minutes=19), 4, "Tried a pullback variant; it lost to the index after tax, so it was dropped and the allocation stands.")
    con.execute("INSERT INTO system_allocation_s79 (target_id, market, proposed_at, proposed_by, classes_json, sectors_json, reasons, status) VALUES (7, 'IN', ?, 'the strategist', ?, '{}', 'because', 'proposed')",
                [T0 + timedelta(minutes=10), json.dumps({"index": 55.0, "gold": 10.0})])
    n = lab.latest_strategist_note(con)
    assert n["session_id"] == 4 and n["cost_rupees"] == 41.25 and n["proposal"]["target_id"] == 7 and n["proposal"]["classes"]["index"] == 55.0 and n["proposal"]["reaffirmed"] is False
    line = session.strategist_line(con, T0.date())
    assert line.startswith("Strategist (2026-11-12 10:19)") and "proposed an allocation (index 55%, gold 10%)" in line and "Rs 41" in line
    assert session.strategist_line(con, T0.date() + timedelta(days=9)) is None             # an old note is not repeated
    text = session.report_day(con, T0.date())
    assert "Strategist (2026-11-12" in text and text.count("\n") + 1 <= 15 and text.splitlines()[-1].startswith("Post-close loop")
