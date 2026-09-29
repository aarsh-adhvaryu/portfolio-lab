"""E3-R through the engine, on synthetic data (§4 and §11 (a)-(d))."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from conftest import make_panel
from pflab.backtest import engine
from pflab.eval.periods import Period
from pflab.execution.costs import CostModel
from pflab.tax.india_lots import TaxPolicy

ETF = "INF000X01011"


def _panel(seed=2):
    rng = np.random.default_rng(seed)
    sessions = list(pd.bdate_range("2011-01-01", "2019-12-31").date)
    names = [f"INE{i:03d}A01011" for i in range(30)]
    prices = {n: 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.02, len(sessions))))
              for n in names}
    prices[ETF] = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(sessions))))
    p = make_panel(sessions, names + [ETF], prices)
    p.loc[p["isin"] == ETF, "instrument_type"] = "ETF"
    return sessions, p


def _index(sessions):
    x = np.arange(len(sessions))
    return pd.DataFrame({"date": sessions,
                         "close": 100 * (1 + 0.3 * np.sin(x / 110.0)) * (1 + x / 5000)})


GEARS = {"instrument_isin": ETF, "cautious_target": 0.5, "selldown_fraction": 0.5,
         "trigger": "B", "high_gear": True, "high_mode": "instrument",
         "v_source": "realised", "basket_n": 5, "v_window": 60, "v_percentile": 0.8,
         "v_lookback_months": 12, "b_window": 100, "b_level": 1.01,
         "min_cautious_run": 2, "disposal_tranches": 3}


def _cfg(**over):
    g = {**GEARS, **over}
    return {"strategy": {"n_hold": 8, "band_exit_rank": 16, "sip_amount": 50000.0,
                         "trend_filter": "gears", "max_buys_per_month": 6},
            "universe": {"series": ["EQ"], "min_sessions": 120, "top_n_by_turnover": 40,
                         "turnover_window": 60, "min_price": 1.0,
                         "max_adv_fraction": 1.0},
            "gears": g}


def _run(cfg, period=Period("t", date(2013, 1, 1), date(2019, 12, 31))):
    sessions, panel = _panel()
    panel = panel[panel["date"] <= period.end]
    sessions = [d for d in sessions if d <= period.end]
    return engine.run(cfg, period, panel, _index(sessions),
                      CostModel.from_toml("configs/costs_zerodha.toml"),
                      TaxPolicy.from_toml("configs/tax_policy_in.toml"))


@pytest.fixture(scope="module")
def base():
    return _run(_cfg())


def test_every_decision_carries_a_gear_and_all_three_occur(base):
    gears = [d["gear"] for d in base.decisions]
    assert set(gears) == {"cautious", "normal", "high"}
    assert base.regime["months"]


def test_cautious_months_buy_nothing_and_sell_down_by_the_ranking(base):
    tr = base.trades
    for d in base.decisions:
        if d["gear"] != "cautious":
            continue
        s = d["selldown"]
        assert s["amount"] == pytest.approx(0.5 * s["excess"])
        assert s["target_equity"] == pytest.approx(0.5 * s["portfolio"])
    nxt = {m: t for m, t in _next_sessions(base)}
    caut = [nxt[d["month_end"]] for d in base.decisions
            if d["gear"] == "cautious" and d["month_end"] in nxt]
    assert caut
    bought = tr[(tr["side"] == "BUY") & tr["date"].isin(caut)]
    assert bought.empty
    assert (tr["side"] == "SELL_GEAR").any()


def test_high_gear_puts_all_waiting_cash_into_the_instrument(base):
    nxt = dict(_next_sessions(base))
    highs = [nxt[d["month_end"]] for d in base.decisions
             if d["gear"] == "high" and d["month_end"] in nxt]
    assert highs
    tr = base.trades
    for t in highs:
        b = tr[(tr["date"] == t) & (tr["side"] == "BUY")]
        assert set(b["isin"]) == {ETF}
        cash_after = base.equity.set_index("date").loc[t, "cash"]
        assert cash_after < 1.5 * b.iloc[0]["fill_price"] + 1.0


def test_the_instrument_is_never_band_exited_nor_topped_up_by_e1(base):
    for d in base.decisions:
        assert ETF not in {e["isin"] for e in d["exits"]}
    tr = base.trades
    nxt = dict(_next_sessions(base))
    high_days = {nxt[d["month_end"]] for d in base.decisions
                 if d["gear"] == "high" and d["month_end"] in nxt}
    etf_buys = tr[(tr["isin"] == ETF) & (tr["side"] == "BUY")]
    assert set(etf_buys["date"]) <= high_days
    assert (tr[tr["isin"] == ETF]["side"] == "SELL").sum() == 0


def test_long_term_instrument_lots_leave_in_thirds_in_normal_gear(base):
    sells = [d["tranche_sell"] for d in base.decisions
             if d["gear"] == "normal" and d.get("tranche_sell")]
    assert sells, "fixture must hold the instrument past a year"
    assert any(3 in s["lots"].values() for s in sells)


def test_undefined_v_months_are_recorded_and_do_not_fire():
    # B never fires; the window opens before V's 12 prior values exist
    r = _run(_cfg(trigger="V_or_B", b_level=-1.0),
             Period("t", date(2012, 3, 1), date(2016, 12, 31)))
    und = r.regime["v_undefined_months"]
    assert und and und[0].startswith("2012-03")
    assert any(d["gear"] == "cautious" for d in r.decisions),         "V must fire somewhere once defined, or this test proves nothing"
    for d in r.decisions:
        if str(d["month_end"]) in und:
            assert d["gear"] != "cautious"


def test_no_selling_row_keeps_the_book_when_cautious():
    r = _run(_cfg(selldown_fraction=0.0))
    caut = [d for d in r.decisions if d["gear"] == "cautious"]
    assert caut and all(d["selldown"]["plan"] == [] for d in caut)
    nxt = dict(_next_sessions(r))
    days = {nxt[d["month_end"]] for d in caut if d["month_end"] in nxt}
    tr = r.trades
    assert tr[(tr["side"] == "SELL_GEAR") & tr["date"].isin(days)].empty


def test_two_gear_row_has_no_high_month():
    r = _run(_cfg(high_gear=False))
    assert "high" not in {d["gear"] for d in r.decisions}


def test_missing_gear_setting_is_refused():
    cfg = _cfg()
    del cfg["gears"]["cautious_target"]
    with pytest.raises(ValueError, match="cautious_target"):
        _run(cfg)


def _next_sessions(res):
    ds = list(res.equity["date"])
    out = []
    for d in res.decisions:
        m = d["month_end"]
        i = ds.index(m) if m in ds else None
        if i is not None and i + 1 < len(ds):
            out.append((m, ds[i + 1]))
    return out


def test_extras_report_gears_alarms_and_episodes(base):
    from pflab.eval import artifacts
    sessions, _ = _panel()
    x = artifacts.e3r_extras(base, _index(sessions))
    assert sum(sum(v.values()) for v in x["gear_months_by_year"].values()) == len(base.decisions)
    assert x["false_alarms"]["cautious_months_judged"] > 0
    assert set(x["worst_fall_by_episode"]) == {"2008", "2011", "2013", "2015-16", "2018", "2020"}
    assert x["worst_fall_by_episode"]["2013"] <= 0
    assert "short_term_gain" in x["gear_sales_realised"]


def test_row_table_moves_one_term_each_and_config_holds_every_gear_key():
    import tomllib
    from pflab.backtest.engine import GEAR_KEYS
    from pflab.eval import sweep
    t = sweep.e3r_rows()
    assert list(t) == ["base"] + [f"S{i}" for i in range(1, 11)]
    assert all(len(v) == 1 for k, v in t.items() if k != "base")
    with open("configs/e3r.toml", "rb") as f:
        cfg = tomllib.load(f)
    assert set(GEAR_KEYS) <= set(cfg["gears"])
    assert cfg["strategy"]["trend_filter"] == "gears" and cfg["data"]["etf_events"]
    # 2026-09-29: the stack is E1 + E1d; only the trend rule differs from it
    with open("configs/e1d.toml", "rb") as f:
        e1d = tomllib.load(f)
    assert cfg["stack"]["config"] == "configs/e1d.toml"
    for k, v in e1d["strategy"].items():
        if k not in ("trend_filter", "id", "charter"):
            assert cfg["strategy"][k] == v, k
    assert set(cfg["strategy"]) - set(e1d["strategy"]) == set()


def test_classify_e3r_carries_the_prediction(tmp_path):
    import json
    from pflab.eval import classify
    crit = {"rows": {"base": {"cagr": .1, "max_drawdown": -.3, "turnover_annual": 1.0}},
            "benchmarks": {"NIFTY500_TRI": {"cagr": .1, "max_drawdown": -.4},
                           "NIFTY500_MOMENTUM50_TRI": {"cagr": .1, "max_drawdown": -.4}}}
    dirs = []
    for n in ("a", "b", "c", "d"):
        (tmp_path / n).mkdir()
        (tmp_path / n / "criteria.json").write_text(json.dumps(crit), encoding="utf-8")
        dirs.append(tmp_path / n)
    out = classify.classify_e3r(*dirs)
    assert "2017-2021" in out["prediction_2026_09_25"]
    assert "charter_c1_c4" not in out and out["gate"]["stack"] == "E1 + E1d"


def test_gears_on_the_e1d_stack_use_its_score_for_the_basket_and_ties():
    """2026-09-29: on E1 + E1d, V's basket is the top N by E1d's score,
    standardised within U(M), not by 12-1 momentum."""
    stack = {"signal": "vol_scaled_6_12", "skip_sessions": 21,
             "score_order": "average_then_z", "score_windows": [126, 252]}
    a = _run(_cfg(trigger="V", b_level=0.4))
    cfg = _cfg(trigger="V", b_level=0.4)
    cfg["strategy"].update(stack)
    b = _run(cfg)
    va = {m: s["V_raw"] for m, s in a.regime["months"].items()}
    vb = {m: s["V_raw"] for m, s in b.regime["months"].items()}
    assert va.keys() == vb.keys() and va != vb
    assert any(d.get("selldown") for d in b.decisions) or         any(d["gear"] != "normal" for d in b.decisions)
    with pytest.raises(ValueError, match=r"E1 \+ E1d"):
        bad = _cfg()
        bad["strategy"]["signal"] = "mom_12_1_z"
        _run(bad)

