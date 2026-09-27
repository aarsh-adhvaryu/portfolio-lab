"""E2-D1 §3-§4: promoter selling in shares, point-in-time."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.data import positioning as pos

ISIN = "INE000A01011"


def _row(q, prom, so_rep=None, so_der=None, filed=None, scrip="500001"):
    return {"scrip_code": scrip, "quarter_end": q, "status": "ok",
            "promoter_shares": prom, "shares_outstanding_reported": so_rep,
            "shares_outstanding_derived": so_der if so_der is not None else so_rep,
            "filing_date": pd.Timestamp(filed) if filed else pd.NaT}


def _map(scrip="500001", isin=ISIN):
    return pd.DataFrame([{"scrip_code": scrip, "isin": isin,
                          "valid_from": "1990-01-01", "valid_to": "2999-12-31"}])


def _fn(rows, threshold=0.01, actions=None, end=date(2030, 1, 1), **kw):
    return pos.promoter_exclusion(end, actions, threshold, summary=pd.DataFrame(rows),
                                  scrip_map=_map(), **kw)


def test_undated_quarter_usable_from_second_month_after():
    assert pos.undated_usable_from(date(2012, 9, 30)) == date(2012, 11, 1)
    assert pos.undated_usable_from(date(2012, 12, 31)) == date(2013, 2, 1)


def test_filing_after_1530_is_usable_next_day():
    assert pos.filed_usable_from(pd.Timestamp("2017-01-20 15:30")) == date(2017, 1, 20)
    assert pos.filed_usable_from(pd.Timestamp("2017-01-20 15:31")) == date(2017, 1, 21)


def test_selling_more_than_threshold_flags_only_once_both_quarters_usable():
    rows = [_row("2016-12-31", 600, 1000, filed="2017-01-20 10:00"),
            _row("2017-03-31", 590, 1000, filed="2017-04-20 10:00"),
            _row("2017-06-30", 580, 1000, filed="2017-07-21 10:00")]
    fn, rec = _fn(rows)
    assert fn(date(2017, 6, 30)) == set()          # Jun-17 not yet filed
    assert fn(date(2017, 7, 31)) == {ISIN}         # 600 -> 580 = 2.0% > 1.0%
    assert rec[date(2017, 7, 31)][ISIN]["sold_frac"] == pytest.approx(0.02)


def test_new_issue_is_not_selling():
    # promoter shares unchanged while the company issues 25% more shares:
    # promoter PERCENT falls 12 pp, promoter SHARES do not fall at all
    rows = [_row("2016-12-31", 600, 1000, filed="2017-01-20"),
            _row("2017-03-31", 600, 1100, filed="2017-04-20"),
            _row("2017-06-30", 600, 1250, filed="2017-07-20")]
    fn, _ = _fn(rows)
    assert fn(date(2017, 7, 31)) == set()


def test_bonus_between_quarters_is_restated_not_counted():
    # 1:1 bonus in Feb-17 doubles promoter shares; promoters then sell 1% of
    # the enlarged count. Unrestated this would look like a 100% purchase;
    # restated it is 1,200 -> 1,180 = 1.0% of 2,000, not above the threshold.
    rows = [_row("2016-12-31", 600, 1000, filed="2017-01-20"),
            _row("2017-03-31", 1200, 2000, filed="2017-04-20"),
            _row("2017-06-30", 1180, 2000, filed="2017-07-20")]
    actions = pd.DataFrame([{"isin": ISIN, "ex_date": date(2017, 2, 15),
                             "factor": 0.5, "source": "purpose"}])
    fn, rec = _fn(rows, actions=actions)
    fn(date(2017, 7, 31))
    assert rec[date(2017, 7, 31)] == {}
    fn2, rec2 = _fn(rows, threshold=0.005, actions=actions)
    assert fn2(date(2017, 7, 31)) == {ISIN}
    assert rec2[date(2017, 7, 31)][ISIN]["sold_frac"] == pytest.approx(0.01)


def test_a_cash_distribution_is_not_a_share_count_event():
    ev = pos.share_count_events(pd.DataFrame([
        {"isin": ISIN, "ex_date": date(2017, 2, 15), "factor": 0.97, "source": "prevclose"}]))
    assert ev == {}


def test_missing_comparison_quarter_is_no_measure_not_an_older_pair():
    rows = [_row("2016-09-30", 700, 1000, filed="2016-10-20"),
            _row("2016-12-31", 600, 1000, filed="2017-01-20"),
            # Mar-17 is missing. At 2017-10-31 the latest quarter is Sep-17,
            # whose pair (Mar-17) does not exist, so there is no measure --
            # even though Jun-17 vs Dec-16 or an older pair would show selling.
            _row("2017-06-30", 600, 1000, filed="2017-07-20"),
            _row("2017-09-30", 500, 1000, filed="2017-10-20")]
    fn, _ = _fn(rows)
    assert fn(date(2017, 10, 31)) == set()


def test_undated_quarters_and_dated_only_row():
    rows = [_row("2012-03-31", 600, so_der=1000),
            _row("2012-06-30", 590, so_der=1000),
            _row("2012-09-30", 570, so_der=1000)]
    fn, _ = _fn(rows)
    assert fn(date(2012, 10, 31)) == set()          # Sep-12 usable from Nov
    assert fn(date(2012, 11, 30)) == {ISIN}
    fn2, _ = _fn(rows, dated_only=True)
    assert fn2(date(2012, 11, 30)) == set()


def test_rows_usable_after_period_end_never_load():
    rows = [_row("2016-12-31", 600, 1000, filed="2017-01-20"),
            _row("2017-03-31", 590, 1000, filed="2017-04-20"),
            _row("2017-06-30", 500, 1000, filed="2017-07-20")]
    fn, _ = _fn(rows, end=date(2017, 6, 30))
    assert fn(date(2017, 7, 31)) == set()


def test_flag_attaches_to_the_isin_carried_at_the_decision_date():
    m = pd.DataFrame([
        {"scrip_code": "500001", "isin": "INE000A01011",
         "valid_from": "1990-01-01", "valid_to": "2017-07-15"},
        {"scrip_code": "500001", "isin": "INE000A01029",
         "valid_from": "2017-07-16", "valid_to": "2999-12-31"}])
    rows = [_row("2016-12-31", 600, 1000, filed="2017-01-20"),
            _row("2017-03-31", 590, 1000, filed="2017-04-20"),
            _row("2017-06-30", 580, 1000, filed="2017-07-10")]
    fn, _ = pos.promoter_exclusion(date(2030, 1, 1), None, 0.01,
                                   summary=pd.DataFrame(rows), scrip_map=m)
    assert fn(date(2017, 7, 31)) == {"INE000A01029"}


def _engine_run(cfg, monkeypatch=None, rows=None, isin=None):
    from pflab.backtest import engine
    from pflab.eval.periods import Period
    from pflab.execution.costs import CostModel
    from pflab.tax.india_lots import TaxPolicy
    from conftest import flat_index, random_walk_panel
    sessions, names, panel = random_walk_panel(seed=5, n_names=30,
                                               start="2014-01-01", end="2018-12-31")
    if monkeypatch is not None:
        real = pos.promoter_exclusion
        smap = pd.DataFrame([{"scrip_code": "500001", "isin": isin,
                              "valid_from": "1990-01-01", "valid_to": "2999-12-31"}])
        monkeypatch.setattr(pos, "promoter_exclusion",
                            lambda end, actions, thr, dated_only=False: real(
                                end, actions, thr, dated_only,
                                summary=pd.DataFrame(rows), scrip_map=smap))
    return engine.run(cfg, Period("t", date(2016, 1, 1), date(2018, 12, 31)), panel,
                      flat_index(sessions),
                      CostModel.from_toml("configs/costs_zerodha.toml"),
                      TaxPolicy.from_toml("configs/tax_policy_in.toml"))


def _cfg(**ps):
    cfg = {"strategy": {"n_hold": 5, "band_exit_rank": 10, "sip_amount": 50000.0,
                        "trend_filter": "off"},
           "universe": {"series": ["EQ"], "min_sessions": 100, "top_n_by_turnover": 30,
                        "turnover_window": 60, "min_price": 1.0, "max_adv_fraction": 1.0}}
    if ps:
        cfg["promoter_selling"] = ps
    return cfg


def test_engine_exits_a_held_name_at_the_month_end_the_rule_trips(monkeypatch):
    plain = _engine_run(_cfg())
    # a name E1 holds going into a month-end on or after 2017-10-31, the
    # first month-end at which a Sep-17 quarter filed in October is usable
    d0 = next(d for d in plain.decisions
              if d["month_end"] >= date(2017, 10, 31) and d["held"])
    m, victim = d0["month_end"], d0["held"][0]
    rows = [_row("2017-03-31", 600, 1000, filed="2017-04-10"),
            _row("2017-06-30", 600, 1000, filed="2017-07-10"),
            _row("2017-09-30", 500, 1000, filed=f"{m} 10:00")]   # sold 10%
    got = _engine_run(_cfg(enabled=True, threshold=0.01), monkeypatch, rows, victim)
    d = next(x for x in got.decisions if x["month_end"] == m)
    assert victim in d["promoter_selling"]
    assert d["promoter_selling"][victim]["sold_frac"] == pytest.approx(0.10)
    assert any(e["isin"] == victim and e["reason"] == "ineligible" for e in d["exits"])
    # nothing earlier saw it: the filing is dated m
    assert all(not x["promoter_selling"] for x in got.decisions if x["month_end"] < m)
    # no later filing, so Sep-17 stays the latest quarter and the name is
    # never bought back
    assert all(victim not in x["entries"]
               for x in got.decisions if x["month_end"] > m)


def test_engine_without_the_rule_records_nothing():
    res = _engine_run(_cfg())
    assert all("promoter_selling" not in d for d in res.decisions)


def test_engine_refuses_a_missing_threshold():
    with pytest.raises(ValueError, match="threshold"):
        _engine_run(_cfg(enabled=True))


def test_s4_is_not_applicable_in_validation_and_applies_in_development():
    from pflab.eval import sweep
    from pflab.eval.periods import Period
    t = sweep.e2d1_rows()
    dev = Period("e2d1_development", date(2010, 1, 1), date(2016, 12, 31))
    val = Period("validation", date(2017, 1, 1), date(2021, 12, 31))
    assert sweep.row_applies(dev, "S4", t) and not sweep.row_applies(val, "S4", t)
    assert sweep.period_for_row(dev, "S4", t).start == date(2016, 1, 1)
    assert sweep.apply_row({}, "S3", t) == {"promoter_selling": {"dated_only": True}}


def test_classify_e2d1_is_gate_and_mandate_only(tmp_path):
    import json
    from pflab.eval import classify
    crit = lambda c, dd: {"rows": {"base": {"cagr": c, "max_drawdown": dd,
                                            "turnover_annual": 1.5}},
                          "benchmarks": {"NIFTY500_TRI": {"cagr": .10, "max_drawdown": -.40},
                                         "NIFTY500_MOMENTUM50_TRI": {"cagr": .12,
                                                                     "max_drawdown": -.40}}}
    dirs = []
    for name, c in (("cd", crit(.20, .30)), ("cv", crit(.20, .30)),
                    ("sd", crit(.10, .40)), ("sv", crit(.10, .40))):
        d = tmp_path / name
        d.mkdir()
        (d / "criteria.json").write_text(json.dumps(c), encoding="utf-8")
        dirs.append(d)
    out = classify.classify_e2d1(*dirs)
    assert out["verdict"] == "ADOPT" and out["gate"]["stack"] == "E1 base"
    assert "mandate" in out and "charter_c1_c4" not in out


# -- E2-D2 ---------------------------------------------------------------
SYM_MAP = pd.DataFrame([{"symbol": "ABC", "isin": "INE000A01011",
                         "valid_from": "1990-01-01", "valid_to": "2018-06-30"},
                        {"symbol": "ABC", "isin": "INE000A01029",
                         "valid_from": "2018-07-01", "valid_to": "2999-12-31"}])


def _pit(*rows):
    cols = ["broadcast_dt", "symbol", "person_category", "acq_mode",
            "transaction_type", "value"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows])


def _so(isin_scrip="500001"):
    return pd.DataFrame([_row("2017-03-31", 500, 1000, filed="2017-04-20", scrip=isin_scrip)])


ALL = {"threshold": 0.01, "window_months": 6, "categories": "all",
       "modes": "all", "transaction_types": "all"}


def test_insider_rows_cutoff_sign_and_dated_symbol_join():
    r = pos.insider_rows(_pit(
        ("2018-03-01 15:30", "ABC", "Promoters", "Market Sale", "Sell", 100.0),
        ("2018-03-01 17:00", "ABC", "Director", "Market Purchase", "Buy", 40.0),
        ("2018-07-02 10:00", "ABC", "Director", "Market Sale", "Sell", 5.0),
        ("2018-03-05 10:00", "ABC", "Director", "Pledge Creation", "Pledge", 999.0),
        ("2018-03-06 10:00", "ABC", "Director", "Market Sale", "Sell", float("nan"))),
        SYM_MAP, date(2030, 1, 1), "all", "all", "all")
    assert list(r["usable_from"]) == [date(2018, 3, 1), date(2018, 3, 2), date(2018, 7, 2)]
    assert list(r["signed_value"]) == [100.0, -40.0, 5.0]
    assert list(r["isin"]) == ["INE000A01011", "INE000A01011", "INE000A01029"]
    assert r.attrs["dropped_no_value"] == 1


def test_insider_filters_are_explicit():
    rows = _pit(("2018-03-01 10:00", "ABC", "Employees/Designated Employees", "ESOP", "Sell", 50.0),
                ("2018-03-01 10:00", "ABC", "Promoters", "Market Sale", "Sell", 30.0))
    r = pos.insider_rows(rows, SYM_MAP, date(2030, 1, 1), ["promoters"], "all", "all")
    assert list(r["signed_value"]) == [30.0]
    r = pos.insider_rows(rows, SYM_MAP, date(2030, 1, 1), "all", ["market sale"], "all")
    assert list(r["signed_value"]) == [30.0]


def test_insider_exclusion_uses_market_cap_at_m_and_the_window():
    smap = pd.DataFrame([{"scrip_code": "500001", "isin": "INE000A01011",
                          "valid_from": "1990-01-01", "valid_to": "2999-12-31"}])
    pit = _pit(("2017-09-15 10:00", "ABC", "Promoters", "Market Sale", "Sell", 1500.0),
               ("2017-10-10 10:00", "ABC", "Promoters", "Market Purchase", "Buy", 300.0))
    fn, rec = pos.insider_exclusion(date(2030, 1, 1), ALL, lambda i, m: 100.0,
                                    pit=pit, symbol_map=SYM_MAP, summary=_so(),
                                    scrip_map=smap)
    # net 1,200 over market cap 1,000 x 100 = 1.2% > 1.0%
    assert fn(date(2017, 10, 31)) == {"INE000A01011"}
    assert rec[date(2017, 10, 31)]["INE000A01011"]["net_frac"] == pytest.approx(0.012)
    # before the sale was broadcast: nothing
    assert fn(date(2017, 8, 31)) == set()
    # six months later the sale has left the window; the buy alone is net buying
    assert fn(date(2018, 3, 31)) == set()
    # at a higher price the same selling is under the threshold
    fn2, _ = pos.insider_exclusion(date(2030, 1, 1), ALL, lambda i, m: 200.0, pit=pit,
                                   symbol_map=SYM_MAP, summary=_so(), scrip_map=smap)
    assert fn2(date(2017, 10, 31)) == set()


def test_insider_config_has_no_defaults():
    with pytest.raises(ValueError, match="categories"):
        pos.insider_exclusion(date(2030, 1, 1), {"threshold": 0.01, "window_months": 6,
                                                 "modes": "all", "transaction_types": "all"},
                              lambda i, m: 1.0, pit=_pit(), symbol_map=SYM_MAP,
                              summary=_so(), scrip_map=_map())


def test_engine_refuses_two_exclusion_rules_at_once():
    cfg = _cfg(enabled=True, threshold=0.01)
    cfg["insider_selling"] = {"enabled": True, **ALL}
    with pytest.raises(ValueError, match="ONE change"):
        _engine_run(cfg)
