"""S81 B5: the lab's daily replay for the swing sleeve, the harvesting rule, the three variants and the registered study (synthetic data only)."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from dateutil.relativedelta import relativedelta

from pflab.lab import engine, harvest_replay as H, policy_api, runner, service, swing, swing_study
from pflab.pm import store
from tests.test_s80_lab import make_data

NOW = datetime(2026, 11, 9, 23, 0)
CFG = {"min_history": 20, "turn_window": 60, "daily_history_rows": 120}


# --- a tiny scripted panel: stock A and a few fillers, the day's range under the test's control -----------------------------------------

def toy(n=160, a_close=None, a_range=None, turnover=1e9, seed=3):
    """Stocks A, B, C; A's close path and its (open, high, low) ratios by session are scripted; B and C wander. Returns the data dict with an `ohlc` block."""
    idx = pd.bdate_range("2012-01-02", periods=n)
    rng = np.random.default_rng(seed)
    close = {"A": np.full(n, 100.0) if a_close is None else np.asarray(a_close, float),
             "B": 100 * np.cumprod(1 + rng.normal(0, 0.005, n)), "C": 100 * np.cumprod(1 + rng.normal(0, 0.005, n))}
    px = pd.DataFrame(close, index=idx)
    o, h, l = (pd.DataFrame(1.0, index=idx, columns=px.columns) for _ in range(3))
    for i, (ro, rh, rl) in (a_range or {}).items():
        o.iloc[i, 0], h.iloc[i, 0], l.iloc[i, 0] = ro, rh, rl
    to = pd.DataFrame(turnover, index=idx, columns=px.columns)
    meta = {k: {"symbol": k, "etf": False, "sector": None, "tax": "EQUITY"} for k in px.columns}
    return {"px": px, "turnover": to, "meta": meta, "index": px["B"], "bench": px["B"], "ohlc": {"open": o, "high": h, "low": l}}


def scripted(entry_day_idx, idx, stop=0.08, target=0.16, max_days=30, key="A", every_day=False):
    """A daily policy that asks for one entry on the decision day `entry_day_idx` (the fill is the NEXT close) and nothing else."""
    day = idx[entry_day_idx].date()

    def decide(state, forecasts, sims, storylines, params=None):
        if (state["day"] == day or every_day) and not state["positions"] and key in state["universe"]:
            return {"entries": [{"key": key, "weight": 0.09, "stop": stop, "target": target, "max_days": max_days}], "exits": []}
        return {"entries": [], "exits": []}
    return decide


def run_daily(data, decide, cfg=None, start=None, end=None):
    idx = data["px"].index
    return swing.replay_daily(decide, {}, data, start or idx[0], end or idx[-1], {**CFG, **(cfg or {})}, None, "daily")


# --- stops, targets, time exits -----------------------------------------------------------------------------------------------------

def test_a_stop_fills_at_the_stop_or_worse_never_better():
    rng = np.random.default_rng(11)
    for trial in range(40):
        gap = trial % 2 == 0
        low = float(rng.uniform(0.70, 0.91))                       # the day's low as a ratio to the close (the stop is 8% below the fill, about 0.92 of 100)
        op = float(rng.uniform(0.70, 1.0)) if gap else 1.0         # a gap: the session OPENS below the stop
        d = toy(a_range={55: (op, 1.0, min(low, op))})
        run = run_daily(d, scripted(50, d["px"].index))
        stops = [t for t in run["trades"] if t["why"] == "stop"]
        assert len(stops) == 1, (trial, run["trades"])
        t = stops[0]
        assert t["exit_px"] <= t["stop"] + 1e-9                    # at the stop or worse
        assert t["exit_px"] <= 100.0 * op + 1e-9                   # and never above the open of the session it gapped through
        assert t["days"] == 4


def test_a_target_a_time_exit_and_stop_first_when_one_session_reaches_both():
    d = toy(a_range={55: (1.0, 1.30, 0.995)})                           # the high reaches the +16% target; the low stays above the stop
    run = run_daily(d, scripted(50, d["px"].index))
    assert [t["why"] for t in run["trades"]] == ["target"] and run["trades"][0]["days"] == 4
    d2 = toy(a_range={55: (1.0, 1.30, 0.80)})                           # one session reaches both: the stop is taken
    run2 = run_daily(d2, scripted(50, d2["px"].index))
    assert [t["why"] for t in run2["trades"]] == ["stop"]
    d3 = toy()                                                          # nothing happens: the time exit at the close of the 7th session held
    run3 = run_daily(d3, scripted(50, d3["px"].index, max_days=7))
    assert [t["why"] for t in run3["trades"]] == ["time"] and run3["trades"][0]["days"] == 7
    assert run3["trades"][0]["ret"] < 0                                 # a flat price: the round trip cost slippage and charges


def test_a_target_fill_is_the_target_minus_slippage_never_above_it():
    d = toy(a_range={55: (1.0, 1.50, 0.995)})                           # a high far above the target: still filled at the target, not higher
    run = run_daily(d, scripted(50, d["px"].index, target=0.10))
    t = run["trades"][0]
    assert t["why"] == "target" and 1.0 + t["ret"] <= 1.10 + 1e-9


# --- no same-day round trip ---------------------------------------------------------------------------------------------------------

def test_no_same_day_round_trip_a_target_on_the_entry_day_waits_but_a_stop_may_fire():
    d = toy(a_range={51: (1.0, 1.40, 0.999), 52: (1.0, 1.40, 0.999)})   # entry fills at the OPEN of session 51; the high there is far over the target
    run = run_daily(d, scripted(50, d["px"].index), cfg={"entry_fill": "open"})
    t = run["trades"][0]
    assert t["why"] == "target" and t["days"] == 1 and t["entry"] != t["exit"]           # the target due on the entry day waited for the next session
    d2 = toy(a_range={51: (1.0, 1.0, 0.70)})                                              # a stop on the entry day itself may fire
    run2 = run_daily(d2, scripted(50, d2["px"].index), cfg={"entry_fill": "open"})
    assert run2["trades"][0]["why"] == "stop" and run2["trades"][0]["days"] == 0
    assert swing.can_exit_today(date(2012, 1, 2), date(2012, 1, 2), "stop") and not swing.can_exit_today(date(2012, 1, 2), date(2012, 1, 2), "target")
    assert swing.can_exit_today(date(2012, 1, 2), date(2012, 1, 3), "time")


def test_a_name_sold_today_is_not_bought_today_and_a_harvest_sale_is_bought_back_next_session(monkeypatch):
    events = []
    orig_sell, orig_buy = swing.TaxBook.sell, swing.TaxBook.buy
    monkeypatch.setattr(swing.TaxBook, "sell", lambda self, k, q, px, day, kind, tc: (events.append((day, k, "sell")), orig_sell(self, k, q, px, day, kind, tc))[1])
    monkeypatch.setattr(swing.TaxBook, "buy", lambda self, k, r, px, day, kind: (events.append((day, k, "buy")), orig_buy(self, k, r, px, day, kind))[1])
    # a security that doubles over three years held by the index control, harvesting on, a small exemption so that it has room: sales happen only in Jan-Mar, rebuys the next session
    idx = pd.bdate_range("2012-01-02", "2015-12-31")
    px = pd.DataFrame({"ETF:IDX": 100 * np.exp(np.linspace(0, 1.2, len(idx))), "B": 100.0}, index=idx)
    d = {"px": px, "turnover": pd.DataFrame(1e10, index=idx, columns=px.columns), "index": px["B"], "bench": px["B"], "index_key": "ETF:IDX",
         "meta": {"ETF:IDX": {"symbol": "IDX", "etf": True, "sector": None, "tax": "EQUITY"}, "B": {"symbol": "B", "etf": False, "sector": None, "tax": "EQUITY"}}}
    run = swing.hold_run(d, "2012-01-02", "2015-12-31", {"min_history": 20, "tax": {"lt_exempt": 50_000.0}}, harvest=True)
    sells = [(day, k) for day, k, s in events if s == "sell"]
    assert sells and all(day.month in (1, 2, 3) for day, _ in sells)
    for day, k in sells:
        later = [e for e in events if e[1] == k and e[2] == "buy" and e[0] > day]
        assert later and later[0][0] > day                          # the same shares come back on a later session, never the same day
        assert not [e for e in events if e[0] == day and e[1] == k and e[2] == "buy"]
    assert run["book"].tax >= 0.0


# --- the monthly engine is untouched ------------------------------------------------------------------------------------------------

def test_the_daily_mode_leaves_monthly_policies_identical(monkeypatch):
    data = make_data(n_days=900)
    fn, _ = policy_api.load(service.baseline_code())
    a = engine.replay(fn, {}, data, "2011-01-01", "2013-06-30")
    # a monthly policy never touches the swing module: evaluate() takes the old path (a swing that raised would fail this)
    monkeypatch.setattr(engine, "_swing", lambda: (_ for _ in ()).throw(AssertionError("the monthly path must not call swing")))
    ev = engine.evaluate(fn, [{}], data, "2011-01-01", "2013-06-30", None, n_shuffles=0, n_mc=0)
    assert ev["runs"][0]["score"]["end_value"] == pytest.approx(float(a["value"].iloc[-1]))
    monkeypatch.undo()
    # and the daily machinery run in monthly cadence reproduces the engine's value path exactly (the one difference, the calendar-month long-term rule, is pinned to the engine's here)
    monkeypatch.setattr(swing, "bucket", lambda tc, acq, day, months=12: engine._bucket(tc, (day - acq).days))
    b = swing.replay_daily(fn, {}, data, "2011-01-01", "2013-06-30", None, None, "monthly")
    assert float((a["value"] - b["value"]).abs().max()) == 0.0
    assert a["book"].tax == b["book"].tax and a["book"].charges == b["book"].charges


# --- slippage and tax ---------------------------------------------------------------------------------------------------------------

def test_slippage_grows_with_the_orders_share_of_turnover_and_is_never_negative():
    s = [swing.slip_fraction(v, 1e8, 0.02) for v in (1e4, 1e5, 1e6, 1e7, 5e7, 1e8)]
    assert all(b > a for a, b in zip(s, s[1:])) and min(s) > 0
    assert swing.slip_fraction(1e6, 1e7, 0.02) > swing.slip_fraction(1e6, 1e9, 0.02)               # a thinner name costs more
    assert swing.slip_fraction(1e6, 1e8, 0.04) > swing.slip_fraction(1e6, 1e8, 0.01)               # a wilder name costs more
    assert swing.slip_fraction(0.0, 1e12, 0.0) >= swing.SLIP["half_spread_base"] - 1e-12           # the floor is the spread
    assert swing.slip_fraction(1e9, 1e6, 0.5) < 5.0                                                # the share is capped


def test_every_fill_is_worse_than_its_reference_price():
    d = toy()
    book_prices = {}
    run = run_daily(d, scripted(50, d["px"].index, max_days=3), cfg={"slippage": "liquidity"})
    t = run["trades"][0]
    assert t["ret"] < 0                                                                              # flat prices: slippage and charges only ever cost
    assert run["book"].slip_paid > 0 and run["value"].iloc[-1] < 1e6 * (1.065 ** (len(run["value"]) / 252)) + 1


def test_the_tax_category_switches_after_twelve_months_and_the_rates_come_from_the_tax_rows():
    d0 = date(2020, 3, 1)
    assert swing.bucket("EQUITY", d0, d0 + relativedelta(months=12)) == "st_eq"                      # on the anniversary: still short-term
    assert swing.bucket("EQUITY", d0, d0 + relativedelta(months=12, days=1)) == "lt_eq"
    assert swing.bucket("LISTED_NONEQUITY", d0, d0 + relativedelta(months=12)) == "slab" and swing.bucket("LISTED_NONEQUITY", d0, d0 + relativedelta(months=13)) == "lt_other"
    b = swing.TaxBook(1e6, {**engine.DEFAULT_CFG, **swing.SWING_CFG})
    b.buy("X", 100_000.0, 100.0, d0, "equity")
    short = b.sell_cost("X", 500.0, 150.0, d0 + relativedelta(months=11), "equity", "EQUITY")
    assert short[2].keys() == {"st_eq"} and short[1] == pytest.approx(0.20 * short[2]["st_eq"])
    long_ = b.sell_cost("X", 1000.0, 400.0, d0 + relativedelta(months=13), "equity", "EQUITY")
    assert long_[2].keys() == {"lt_eq"} and long_[1] == pytest.approx(0.125 * (long_[2]["lt_eq"] - 125_000.0))
    tp = swing_study.tax_params()                                                                    # read from configs/tax, and equal to the engine's constants
    assert (tp["st_rate"], tp["lt_rate"], tp["lt_exempt"]) == (engine.ST_RATE, engine.LT_RATE, engine.LT_EXEMPT) and tp["lt_months"] == 12 and tp["carry_years"] == 8
    for g in ({"st_eq": 50_000.0, "lt_eq": 300_000.0}, {"st_eq": -20_000.0, "lt_eq": 200_000.0}, {"lt_eq": -5000.0, "lt_other": 10_000.0, "slab": 7000.0}):
        assert swing.tax_with(g, tp) == pytest.approx(engine.tax_of(g))


def test_losses_carry_forward_as_the_tax_engines_loss_rule_says():
    tp = swing_study.tax_params()
    cfg = {**engine.DEFAULT_CFG, **swing.SWING_CFG, "tax": tp}
    day = date(2021, 6, 1)                                                                            # financial year 2021 (the year starting April 2021)

    def book(prior):
        b = swing.TaxBook(1e7, cfg)
        b.gains = {fy: dict(g) for fy, g in prior.items()}
        b.buy("X", 100_000.0, 100.0, date(2021, 4, 5), "equity")                                       # a short-term lot: sold two months later at +150%
        return b

    def sale(b):
        return b.sell_cost("X", 1000.0, 250.0, day, "equity", "EQUITY")
    gain = sale(book({}))[2]["st_eq"]
    assert sale(book({}))[1] == pytest.approx(0.20 * gain)                                              # no losses carried: the full short-term tax
    assert sale(book({2020: {"st_eq": -100_000.0}}))[1] == pytest.approx(0.20 * (gain - 100_000.0))     # a short-term loss of the year before is carried in
    assert sale(book({2020: {"lt_eq": -100_000.0}}))[1] == pytest.approx(0.20 * gain)                   # a long-term loss never offsets a short-term gain
    assert sale(book({2012: {"st_eq": -100_000.0}}))[1] == pytest.approx(0.20 * gain)                   # older than 8 years: expired (2021 - 2012 = 9)
    assert sale(book({2013: {"st_eq": -100_000.0}}))[1] == pytest.approx(0.20 * (gain - 100_000.0))     # 2021 - 2013 = 8: still live
    assert sale(book({2019: {"st_eq": -30_000.0}, 2020: {"st_eq": -40_000.0}}))[1] == pytest.approx(0.20 * (gain - 70_000.0))   # losses of two years, carried on
    one_year = swing.TaxBook(1e7, {**engine.DEFAULT_CFG, **swing.SWING_CFG})                            # the default (no carry-forward years) is the lab's one-year netting
    one_year.gains = {2020: {"st_eq": -100_000.0}}
    one_year.buy("X", 100_000.0, 100.0, date(2021, 4, 5), "equity")
    assert one_year.sell_cost("X", 1000.0, 250.0, day, "equity", "EQUITY")[1] == pytest.approx(0.20 * gain)


# --- harvesting -------------------------------------------------------------------------------------------------------------------

def test_harvest_step_uses_the_exemption_room_fifo_and_only_in_the_last_quarter():
    tax = {"st_rate": 0.20, "lt_rate": 0.125, "lt_exempt": 125_000.0}
    lots = {"X": [[date(2020, 1, 10), 1000.0, 100.0], [date(2025, 12, 1), 1000.0, 100.0]], "Y": [[date(2021, 1, 10), 100.0, 500.0]]}
    prices = {"X": 400.0, "Y": 450.0}
    assert H.harvest_step(date(2026, 6, 15), lots, prices, {}, {"tax": tax}) == []                  # outside the window
    out = H.harvest_step(date(2026, 2, 10), lots, prices, {}, {"tax": tax})
    gains = sum(o["expected_gain"] for o in out if o["expected_gain"] > 0)
    assert out and 0 < gains <= 125_000.0 * 0.98 + 1e-6 and all(o["buy_back"] for o in out)
    assert all(o["key"] != "Y" or o["expected_gain"] < 0 for o in out)                                # Y is at a loss: no gain booked on it
    x = [o for o in out if o["key"] == "X"][0]
    assert x["qty"] <= 1000.0 + 1e-9                                                                 # only the OLD lot (long-term): the new one is a short-term winner, never sold
    used = H.harvest_step(date(2026, 2, 10), lots, prices, {"lt_eq": 125_000.0}, {"tax": tax})
    assert not [o for o in used if o["expected_gain"] > 0]                                           # the exemption is already used
    loss = H.harvest_step(date(2026, 2, 10), {"Y": lots["Y"]}, prices, {"st_eq": 40_000.0}, {"tax": tax})
    assert loss and loss[0]["expected_gain"] < 0 and abs(loss[0]["expected_gain"]) <= 40_000.0 + 1e-6
    assert H.harvest_step(date(2026, 2, 10), lots, prices, {}, {"tax": tax}, blocked=("X", "Y")) == []   # a name traded today is left alone
    assert H.is_long_term(date(2020, 3, 1), date(2021, 3, 2)) and not H.is_long_term(date(2020, 3, 1), date(2021, 3, 1))


def test_the_results_a_policy_sees_are_point_in_time_and_the_daily_state_holds_no_later_row():
    seen = []

    def spy(state, forecasts, sims, storylines, params=None):
        seen.append((state["day"], state["prices"].index[-1].date(), max([max(v) for v in state["results"].values()], default=None)))
        return {"entries": [], "exits": []}
    d = toy()
    idx = d["px"].index
    d["results"] = {"A": [str(idx[70].date()), str(idx[100].date())]}
    run_daily(d, spy)
    assert seen and all(p == day for day, p, _ in seen)                                              # the last price row is the decision day's
    assert all(m is None or m <= day for day, _, m in seen)                                          # no results date after the decision day
    assert any(m is not None for _, _, m in seen)


DAILY_CODE = """CADENCE = "daily"
PARAMS = {}


def decide(state, forecasts, sims, storylines, params=None):
    out = {"entries": [], "exits": []}
    held = set(state.get("positions", {}))
    free = [k for k in state["universe"] if k not in held and not state["meta"][k]["etf"]]
    if int(state.get("slots", 0)) > 0 and free:
        out["entries"].append({"key": sorted(free)[0], "weight": 0.09, "stop": 0.08, "target": 0.16, "max_days": 30})
    return out
"""


def test_a_daily_policy_runs_in_the_sandbox_harness_on_a_toy_panel(monkeypatch):
    """The daily-step engine (kept for the C4b stop study) still runs a policy end to end through the runner; the three swing variants it was built for are deleted (A60)."""
    monkeypatch.setenv("PFLAB_SANDBOX", "local")
    data = make_data(n_days=1100, n_stocks=40)
    idx = data["px"].index
    data["results"] = {k: [str(idx[i].date()) for i in range(300, 1100, 63)] for k in list(data["px"].columns)[:20] if not k.startswith("ETF")}
    out = runner.run(data, [{"id": "daily_toy", "code": DAILY_CODE}], ("2012-01-02", "2013-12-31"), {"daily_toy": [{}]},
                     {"min_history": 120, "tax": swing_study.tax_params()}, n_shuffles=2, n_mc=20, time_limit=900)
    assert not out.get("error") and not out.get("errors"), out
    row = out["results"]["daily_toy"]["runs"][0]
    assert {"cagr", "dsr", "max_drawdown", "liq_cagr", "excess_vs_cash", "slippage_paid", "n_trades"} <= set(row["score"]) and row["shuffled"]["n"] == 2
    assert out["results"]["daily_toy"]["cadence"] == "daily"


def test_the_runner_job_folder_carries_the_daily_files_and_the_panel_extras_round_trip(tmp_path):
    d = toy()
    d["results"] = {"A": ["2012-03-01"]}
    d["index_key"] = "A"
    runner.save_panel(d, tmp_path / "p")
    back = runner.load_panel(tmp_path / "p")
    assert back["results"] == {"A": ["2012-03-01"]} and back["index_key"] == "A" and set(back["ohlc"]) == {"open", "high", "low"}
    work = tmp_path / "w"
    work.mkdir()
    runner.write_job(work, d, [{"id": "x", "code": DAILY_CODE}], ("2012-01-02", "2012-06-30"), {"x": [{}]})
    assert {"swing.py", "harvest_replay.py", "engine.py", "lab_runner.py", "results.json", "extra.json", "low_ratio.parquet"} <= {p.name for p in work.iterdir()}


# --- the index control, the paired test, the screen --------------------------------------------------------------------------------

def test_the_index_control_pays_charges_slippage_and_tax_and_the_liquidation_counts_the_tax_owed():
    idx = pd.bdate_range("2012-01-02", "2015-12-31")
    px = pd.DataFrame({"ETF:IDX": 100 * np.exp(np.linspace(0, 0.6, len(idx))), "B": 100.0}, index=idx)
    d = {"px": px, "turnover": pd.DataFrame(1e10, index=idx, columns=px.columns), "index": px["B"], "bench": px["B"], "index_key": "ETF:IDX",
         "meta": {"ETF:IDX": {"symbol": "IDX", "etf": True, "sector": None, "tax": "EQUITY"}, "B": {"symbol": "B", "etf": False, "sector": None, "tax": "EQUITY"}}}
    run = swing.hold_run(d, "2012-01-02", "2015-12-31", {"min_history": 20})
    assert run["book"].charges > 0 and run["book"].slip_paid > 0 and run["book"].tax == 0.0              # bought once, never sold: no tax paid yet
    L, liq = swing.liq_cagr(run, run["value"].index[0], {**engine.DEFAULT_CFG})
    assert liq["tax"] > 0 and liq["value"] < float(run["value"].iloc[-1])                                   # the deferred tax counts as owed on liquidation
    assert 0 < L < float(np.exp(0.6 / 4) - 1)


def test_the_drawdown_difference_has_the_sign_the_screen_reads_negative_means_deeper_than_the_index():
    idx = pd.bdate_range("2012-01-02", "2014-12-31")
    px = pd.DataFrame({"ETF:IDX": 100 * np.exp(-np.linspace(0, 0.5, len(idx))), "B": 100.0}, index=idx)         # an index that only falls
    d = {"px": px, "turnover": pd.DataFrame(1e10, index=idx, columns=px.columns), "index": px["B"], "bench": px["ETF:IDX"], "index_key": "ETF:IDX",
         "meta": {"ETF:IDX": {"symbol": "IDX", "etf": True, "sector": None, "tax": "EQUITY"}, "B": {"symbol": "B", "etf": False, "sector": None, "tax": "EQUITY"}}}
    cfg = {**CFG}
    index_run = swing.hold_run(d, "2012-01-02", "2014-12-31", cfg)
    cash_run = swing.replay_daily(lambda *a, **k: {"entries": [], "exits": []}, {}, d, "2012-01-02", "2014-12-31", cfg, None, "daily")           # never trades: no fall at all
    s = swing.score_swing(cash_run, d, cfg, index_run)
    assert s["max_drawdown"] > s["index_max_drawdown"] and s["extra_drawdown_vs_index"] > 0.2                                                       # shallower than the index: positive
    assert not [f for f in swing_study.screen_variant({**s, "dsr": 1.0, "t_vs_index": 99.0, "excess_L_vs_index": 1.0}, {"beats_real_frac": 0.0, "liq_cagr_p95": -1.0}, 50)["failed"] if "worst fall" in f]
    deeper = swing.score_swing(index_run, d, cfg, cash_run)                                                                                          # the index judged against the cash arm: deeper
    assert deeper["extra_drawdown_vs_index"] < -0.2


def test_the_paired_bootstrap_finds_a_real_edge_and_not_noise():
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2010-01-04", periods=1500)
    base = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.01, 1500)), index=idx)
    edge = base * np.cumprod(1 + np.full(1500, 0.0008))
    noise = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.01, 1500)), index=idx)
    assert swing.paired_t(edge, base)["t"] > 5
    assert abs(swing.paired_t(noise, base)["t"]) < 3


def test_the_screen_is_the_protocols_rule():
    good = {"excess_L_vs_index": 0.03, "t_vs_index": 9.0, "dsr": 0.95, "extra_drawdown_vs_index": -0.01, "liq_cagr": 0.20, "max_drawdown": -0.30, "n_trades": 400}
    sh = {"beats_real_frac": 0.0, "liq_cagr_p95": 0.10}
    assert swing_study.screen_variant(good, sh, 50)["verdict"] == "pass"
    assert swing_study.screen_variant({**good, "n_trades": 10}, sh, 50)["verdict"] == "pass_thin"
    for bad, why in (({"excess_L_vs_index": 0.005}, "beats the index"), ({"t_vs_index": 2.0}, "paired t"), ({"dsr": 0.5}, "deflated"), ({"extra_drawdown_vs_index": -0.08}, "worst fall")):
        r = swing_study.screen_variant({**good, **bad}, sh, 50)
        assert not r["ok"] and why in " ".join(r["failed"]), r
    assert not swing_study.screen_variant(good, {"beats_real_frac": 0.3, "liq_cagr_p95": 0.1}, 50)["ok"]
    assert not swing_study.screen_variant(good, {"beats_real_frac": 0.0, "liq_cagr_p95": 0.25}, 50)["ok"]            # the real run must beat the shuffled 95th percentile
    assert not swing_study.screen_variant(good, {}, 50)["ok"]                                                          # no luck measure, no pass
    assert swing_study.screen_variant(good, sh, 500)["t_bar"] > swing_study.screen_variant(good, sh, 20)["t_bar"]       # the bar rises with N
    assert swing_study.final_screen({"excess_L_vs_index": 0.0, "extra_drawdown_vs_index": 0.0, "n_trades": 30})["ok"]
    assert not swing_study.final_screen({"excess_L_vs_index": -0.01, "extra_drawdown_vs_index": 0.0, "n_trades": 30})["ok"]
    ok = {"index": {"dL": 0.002, "accounting_ok": True, "tax_saved": 9, "extra_costs": 1}, "baseline_lab": {"dL": 0.001, "accounting_ok": True, "tax_saved": 9, "extra_costs": 1}}
    assert swing_study.harvest_verdict(ok)["ok"]
    assert not swing_study.harvest_verdict({**ok, "index": {**ok["index"], "dL": 0.0001}})["ok"]
    assert not swing_study.harvest_verdict({**ok, "baseline_lab": {**ok["baseline_lab"], "accounting_ok": False}})["ok"]


# --- the protocol and the counter ---------------------------------------------------------------------------------------------------

def _protocol_rule():
    text = swing_study.PROTOCOL.read_text(encoding="utf-8")
    blocks = [json.loads(b) for b in re.findall(r"```json rule\n(.*?)\n```", text, re.S)]
    assert len(blocks) == 3
    return blocks[0], blocks[1], blocks[2]


def test_the_protocols_rule_in_code_matches_its_text():
    a, a1, a2 = _protocol_rule()
    assert a == swing_study.RULE and a1 == swing_study.RULE_A1 and a2["fy_start_month"] == 4
    rows = __import__("pflab.tax.rules", fromlist=["load"]).load().t["loss_rule"]
    assert a2["tax_carry_forward_years"].endswith("(%d)" % rows[0]["carry_forward_years"]) and swing_study.tax_params()["carry_years"] == rows[0]["carry_forward_years"]
    # the numbers the replay and the variants actually use are the protocol's
    assert a["slippage"] == swing.SLIP and a["sizing"] == swing.SIZING and a["harvest"] == {k: v for k, v in swing.SWING_CFG["harvest_rule"].items() if k != "min_room"}
    assert a["history"] == [str(x) for x in runner.HISTORY] and a["final"] == [str(x) for x in runner.FINAL]
    assert a["capital"] == engine.DEFAULT_CFG["capital"] and a["cash_rate"] == engine.DEFAULT_CFG["cash_rate"] and a["index_expense_ratio"] == runner.INDEX_EXPENSE_RATIO
    assert a["n_shuffles"] == 20 and a["shuffle_seed"] == 80
    text = swing_study.PROTOCOL.read_text(encoding="utf-8")
    for needle in (">= 1.0`", "5,000 resamples", "at most 10%", "at least 0.90", "not more than 5 points deeper", ">= +0.05` percentage points", "Rs 10,00,000", "0.20% a year"):
        assert needle in text, needle


def test_registration_counts_four_tests_once_the_bar_rises_and_a_changed_protocol_is_caught(tmp_path, monkeypatch):
    from pflab.learner import counter
    con = store.connect(tmp_path / "r.duckdb")
    n0 = counter.n_tests(con)
    assert not swing_study.protocol_ok(con)["registered"]
    added = swing_study.register(con, NOW)
    assert len(added) == 4 and counter.n_tests(con) == n0 + 4 and swing_study.register(con, NOW) == []
    assert counter.t_needed(n0 + 5) >= counter.t_needed(n0 + 1)
    ok = swing_study.protocol_ok(con)
    assert ok["registered"] and ok["unchanged"]
    # the same registrations through the learner's own register_all (the hook the app calls) add nothing more
    from pflab.learner import s79
    s79.register_all(con, NOW)
    assert s79.register_swing(con, NOW) == [] and len(con.execute("SELECT 1 FROM learn_tests WHERE note LIKE 's81:%'").fetchall()) == 4
    # a CRLF checkout of the same text is not an edit; a real edit is
    fake = tmp_path / "p.md"
    raw = swing_study.PROTOCOL.read_bytes().replace(b"\r\n", b"\n")
    fake.write_bytes(raw.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(swing_study, "PROTOCOL", fake)
    assert swing_study.protocol_ok(con)["unchanged"]
    fake.write_bytes(raw + b"\nan edit\n")
    assert not swing_study.protocol_ok(con)["unchanged"]
    assert not callable(getattr(swing_study, "run", None)) and not callable(getattr(swing_study, "seed_variants", None))       # A60: the study is a record; its live paths are deleted


def test_the_recorded_run_is_reproduced_by_the_rule_in_code_and_written_onto_a_store_once(tmp_path):
    from pflab.learner import counter
    rec = json.loads(swing_study.RESULTS.read_text(encoding="utf-8"))
    assert rec["protocol_sha256"] == swing_study.protocol_sha()                                       # the protocol file is the one that was run
    for vid, v in rec["variants"].items():
        again = swing_study.screen_variant(v["run"]["score"], v["run"]["shuffled"], rec["n_tests"])
        assert again["verdict"] == v["verdict"] and again["failed"] == v["failed"], vid               # the stored verdicts follow from the stored scorecards by the registered rule
    assert swing_study.harvest_verdict(rec["harvest"]["arms"])["verdict"] == rec["harvest"]["verdict"]["verdict"]
    con = store.connect(tmp_path / "a.duckdb")
    n0 = counter.n_tests(con)
    assert swing_study.apply_recorded(con, NOW) == 0                                                  # not registered yet: nothing is written
    swing_study.register(con, NOW)
    assert swing_study.apply_recorded(con, NOW) == 4 and swing_study.apply_recorded(con, NOW) == 0     # once
    assert counter.n_tests(con) == n0 + 4 and service.n_trials(con) == 3                               # the three variants are trials in the deflated Sharpe
    assert con.execute("SELECT count(*) FROM learn_tests WHERE note LIKE 's81:%' AND passed IS NOT NULL").fetchone()[0] == 4
    assert swing_study.stored(con, "history", "swing_post_results_drift")["verdict"] == "fail"
