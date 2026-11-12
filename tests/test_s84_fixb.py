"""S84 fixb: F2 (the US monthly cap), F3 (a pick is scored from its first fill), F4 (stress estimate bounds). Synthetic data only."""
from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd
import pytest

from pflab.core import pick_score as ps
from pflab.core import picks_card, stress
from pflab.pm import store

# --- F2: the US monthly cap -------------------------------------------------------------------------------------------------------------------------------

DAY = date(2026, 11, 10)


@pytest.fixture
def ucon(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    return store.connect(tmp_path / "u.duckdb")


def _state(spy=9000.0, stk=0.0, cash=500.0, price=50.0, cap=0.10):
    from pflab import core, us
    cfgs = us.settings({"on": True, "min_trade_usd": 25.0})
    total = spy + stk + cash
    rows = [{"isin": "US:SPY", "symbol": "SPY", "sector": None, "asset_class": "etf", "qty": spy / 100.0, "price": 100.0, "value": spy, "weight": spy / total, "buyable": True, "klass": "us_equity"},
            {"isin": "US:STK", "symbol": "STK", "sector": None, "asset_class": "equity", "qty": stk / price, "price": price, "value": stk, "weight": stk / total, "buyable": True, "klass": "us_equity"}]
    return {"day": DAY, "market": "US", "value": total, "cash": cash, "bank": 0.0, "rows": rows, "breaker": {"on": False}, "gauge": {"fired": False}, "cfg": core.settings(),
            "settings": cfgs, "caps": {"US:SPY": 1.0, "US:STK": cap}}, total


def _month_of_rebalancing(con, usd):
    """An untagged (rebalancing) fill this month of `usd` dollars: the monthly cap is used up."""
    con.execute("INSERT INTO us_orders_s81 VALUES (1, ?, now(), 'US:SPY', 'SPY', 'buy', NULL, ?, 'filled', ?, 'us_core_v2: weight 0.0% now, target 95.0%')", [date(2026, 11, 2), usd, date(2026, 11, 3)])
    con.execute("INSERT INTO us_trades_s81 VALUES (1, ?, 1, 'US:SPY', 'SPY', 'buy', ?, 100.0, 1.0, NULL, NULL, NULL, NULL, '{}')", [date(2026, 11, 3), usd / 100.0])


def test_a_pick_named_when_the_sub_book_is_fully_invested_is_bought_within_four_sessions_though_the_month_is_used_up(ucon):
    from pflab.us import policy
    _month_of_rebalancing(ucon, 9000.0)                                       # the build bought 90% of the sub-book this month: the 40% monthly cap is long gone
    st, total = _state(cap=0.60)                                              # a pick that is to reach 60% of the book (a stretch) would take several sessions at 25% a day
    got, sessions = 0.0, 0
    for sessions in range(1, 5):
        out = policy.check(ucon, st, {"weights": {"US:SPY": 0.35, "US:STK": 0.60}})
        buys = [o for o in out["orders"] if o["symbol"] == "STK" and o["side"] == "buy"]
        assert buys, f"session {sessions}: the pick buy must not wait for the month"
        assert buys[0]["value"] <= 0.25 * total + 1e-6                        # limited to 25% of the sub-book a day
        assert "[outside the monthly cap: a named pick's purchase]" in buys[0]["reason"]
        got += buys[0]["value"]
        st, _ = _state(spy=9000.0 - got, stk=got, cash=500.0)
        st["caps"]["US:STK"] = 0.60
        if got >= 0.60 * total - 1.0:
            break
    assert got == pytest.approx(0.60 * total, rel=1e-3) and sessions <= 4


def test_the_usual_pick_of_ten_percent_is_bought_in_one_session_and_funded_by_spy_outside_the_month(ucon):
    from pflab.us import policy
    _month_of_rebalancing(ucon, 9000.0)
    st, total = _state(spy=9500.0, cash=0.0)
    out = policy.check(ucon, st, {"weights": {"US:SPY": 0.90, "US:STK": 0.10}})
    by = {(o["symbol"], o["side"]): o for o in out["orders"]}
    assert by[("STK", "buy")]["value"] == pytest.approx(0.10 * total, rel=1e-3)
    assert "[outside the monthly cap: the sale that funds a pick]" in by[("SPY", "sell")]["reason"]     # the SPY sale that funds it is outside the month too


def test_a_withdrawn_pick_is_sold_whole_within_two_sessions_though_the_month_is_used_up(ucon):
    from pflab.us import policy
    _month_of_rebalancing(ucon, 9000.0)
    st, total = _state(spy=5000.0, stk=5000.0, cash=500.0)                    # a pick that grew to 48% of the sub-book (a stretch): the 25% a day takes two sessions
    held, sessions = 5000.0, 0
    for sessions in range(1, 3):
        out = policy.check(ucon, st, {"weights": {"US:SPY": 0.50, "US:STK": 0.0}})
        sells = [o for o in out["orders"] if o["symbol"] == "STK" and o["side"] == "sell"]
        assert sells and "[outside the monthly cap: the full exit of a withdrawn pick]" in sells[0]["reason"]
        assert sells[0]["value"] <= 0.25 * total + 1e-6 or sells[0]["qty"] * 50.0 >= held - 1e-6
        held -= sells[0]["value"]
        st, _ = _state(spy=5000.0, stk=max(held, 0.0), cash=500.0 + (5000.0 - max(held, 0.0)))     # the proceeds are cash
        if held <= 1e-6:
            break
    assert held <= 1e-6 and sessions <= 2


def test_funding_and_outside_orders_never_count_toward_the_month_but_rebalancing_does(ucon):
    from pflab.us import policy
    ucon.execute("INSERT INTO us_orders_s81 VALUES (1, ?, now(), 'US:SPY', 'SPY', 'buy', NULL, 8000.0, 'filled', ?, 'x [outside the monthly cap: a funding purchase]')", [date(2026, 11, 2), date(2026, 11, 3)])
    ucon.execute("INSERT INTO us_trades_s81 VALUES (1, ?, 1, 'US:SPY', 'SPY', 'buy', 80.0, 100.0, 1.0, NULL, NULL, NULL, NULL, '{}')", [date(2026, 11, 3)])
    assert policy._month_traded(ucon, DAY) == 0.0
    ucon.execute("INSERT INTO us_orders_s81 VALUES (2, ?, now(), 'US:SPY', 'SPY', 'sell', 10.0, NULL, 'filled', ?, 'us_core_v2: trim')", [date(2026, 11, 4), date(2026, 11, 5)])
    ucon.execute("INSERT INTO us_trades_s81 VALUES (2, ?, 2, 'US:SPY', 'SPY', 'sell', 10.0, 100.0, 1.0, NULL, NULL, NULL, NULL, '{}')", [date(2026, 11, 5)])
    assert policy._month_traded(ucon, DAY) == pytest.approx(1000.0)


def test_rebalancing_still_meets_the_monthly_cap_and_the_funding_buys_of_a_deploying_session_are_tagged(ucon):
    from pflab.us import policy
    _month_of_rebalancing(ucon, 4500.0)                                       # 45% of the sub-book traded by rebalancing this month: over the 40% cap
    st, total = _state(spy=5000.0, cash=5000.0)
    st["caps"]["US:STK"] = 0.10
    out = policy.check(ucon, st, {"weights": {"US:SPY": 0.40}})              # a rebalancing trim of SPY (over its target) is stopped by the month
    assert not [o for o in out["orders"] if o["symbol"] == "SPY"]
    dep, _ = _state(spy=0.0, cash=10_000.0)                                   # a fresh account: the build buys are funding purchases, tagged so the month does not count them
    out = policy.check(ucon, dep, {"weights": {"US:SPY": 0.95}})
    assert out["orders"] and all("[outside the monthly cap: a funding purchase]" in o["reason"] for o in out["orders"])


def test_a_reserve_buy_is_outside_the_month_and_limited_to_a_quarter_of_the_sub_book(ucon):
    from pflab.us import policy
    _month_of_rebalancing(ucon, 9000.0)
    st, total = _state(spy=9000.0, cash=1000.0)
    st["rows"][1]["asset_class"] = "etf"                                      # an ETF bought as an opportunity (the thinking loop names the kind)
    st["caps"]["US:STK"] = 0.50
    out = policy.check(ucon, st, {"weights": {"US:SPY": 0.5, "US:STK": 0.50}, "kinds": {"STK": "opportunity"}})
    buy = [o for o in out["orders"] if o["symbol"] == "STK"][0]
    assert "[outside the monthly cap: reserve buy]" in buy["reason"] and buy["value"] <= 0.25 * total + 1e-6


# --- F3: a pick is scored from its first fill ----------------------------------------------------------------------------------------------------------------

AAA, BBB = "INE000A01011", "INE000B01012"
DAYS = [d.date() for d in pd.bdate_range("2025-12-01", "2026-09-30")]
D0, D1 = date(2026, 1, 5), date(2026, 2, 5)
NOW1 = datetime(2026, 2, 10, 20, 0)


def _path(keys: dict) -> pd.Series:
    s = pd.Series({pd.Timestamp(d): v for d, v in keys.items()}).reindex(pd.DatetimeIndex([pd.Timestamp(d) for d in DAYS] + [pd.Timestamp(k) for k in keys])).sort_index()
    return s[~s.index.duplicated(keep="last")].ffill().bfill()


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "data"
    idx = _path({D0: 1000.0, D1: 1030.0})
    p = r / "indices" / "NIFTY500_TRI.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": idx.index.date, "close": idx.to_numpy()}).to_parquet(p, index=False)
    return r


@pytest.fixture
def con(tmp_path, monkeypatch, root):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setenv("PFLAB_DATA_DIR", str(root))
    c = store.connect(tmp_path / "l.duckdb")
    for isin, sym in ((AAA, "AAA"), (BBB, "BBB")):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, 'Banks', 'synthetic', now())",
                  [isin, sym, sym + " Ltd"])
        for d, v in _path({D0: 100.0, date(2026, 1, 12): 100.0, D1: 110.0}).items():
            c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d.date(), float(v)])
    return c


def _pick(con, pid, isin, sym, state, source="system", on=date(2026, 1, 2)):
    con.execute("INSERT INTO picks_s83 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)", [pid, "IN", isin, sym, source, "a thesis of at least sixty characters, written for the test", "breaks if x", "[]", "s1", None, state, on, None, None])


def test_a_named_pick_that_was_never_bought_is_not_in_the_record_and_after_its_first_fill_it_is(con, root):
    _pick(con, 1, AAA, "AAA", "held", source="kite")                          # his stock: held from the start of the book
    _pick(con, 2, BBB, "BBB", "proposed")                                     # named, no fill
    out = ps.score_all(con, NOW1, root)
    assert out["scored"]["pick"] == 1 and out["named_not_held"] == 1
    sc = ps.scorecard(con, "IN")
    assert sc["picks_scored"] == 1 and sc["by_horizon"][1]["scored"] == 1 and sc["named_not_held"] == ["BBB"]
    assert "named, not yet held" in ps.scorecard_text(con, "IN") and "BBB" in ps.scorecard_text(con, "IN")
    # a stored score of the unbought pick from before the fix stays out of the count and the list of recent verdicts
    ps._insert(con, ps._record("pick", 2, "IN", BBB, "BBB", 1, D0, D1, 0.5, 0.01, 0.01, 1.0, True, date(2026, 2, 10), {}))
    sc = ps.scorecard(con, "IN")
    assert sc["picks_scored"] == 1 and sc["picks_ahead"] <= 1 and all(r["symbol"] != "BBB" for r in sc["recent"])
    # the first fill: the pick is in, from the day of the fill
    con.execute("DELETE FROM pick_scores_s83 WHERE ref_id=2")
    con.execute("INSERT INTO paper_trades VALUES (1, ?, NULL, NULL, ?, 'BBB', 'buy', 10, 100.0, 0.5, NULL, NULL, '{}')", [date(2026, 1, 6), BBB])
    out = ps.score_all(con, NOW1, root)
    assert out["scored"]["pick"] == 1
    r = con.execute("SELECT start_on FROM pick_scores_s83 WHERE ref_id=2 AND kind='pick'").fetchone()
    assert r[0] == date(2026, 1, 6)                                          # the record starts at the first fill, not the day after it was named
    sc = ps.scorecard(con, "IN")
    assert sc["picks_scored"] == 2 and sc["named_not_held"] == []


def test_the_card_says_named_not_yet_held_and_the_sleeve_record_does_not_move(con, root):
    _pick(con, 2, BBB, "BBB", "proposed")
    from pflab.core import picks
    st = picks.status(con, "IN", date(2026, 2, 10))
    blk = picks_card.market_block(con, "IN", date(2026, 2, 10))
    assert [p["held_yet"] for p in blk["picks"]] == [False] and blk["picks"][0]["vs_index"] is None
    assert "named, not yet held" in picks_card._market_text(blk) and "days in the book" not in picks_card._market_text(blk)
    assert st["picks"] and ps.sleeve_record(con, "IN")["sessions"] == 0       # nothing held: the sleeve has no record for an unbought pick
    json.dumps(blk)


# --- F4: the stress estimate -----------------------------------------------------------------------------------------------------------------------------

SDAY = date(2026, 10, 30)
KEYS_N = {"2004-01-01": 100.0, "2008-01-01": 200.0, "2009-03-09": 100.0, "2020-02-19": 300.0, "2020-03-23": 210.0, "2021-11-19": 400.0, "2022-12-28": 360.0, "2026-10-30": 500.0}


def _daily(keys: dict, start="1999-01-01", end="2026-10-30") -> pd.Series:
    days = pd.bdate_range(start, end)
    k = pd.Series({pd.Timestamp(d): v for d, v in keys.items()})
    k = k.reindex(k.index.union(days)).sort_index().interpolate(method="time")
    return k.reindex(days).dropna()


@pytest.fixture
def scon(tmp_path, monkeypatch):
    r = tmp_path / "sdata"
    n = _daily(KEYS_N)
    q = _daily({"1999-01-01": 2000.0, "2000-03-10": 5000.0, "2002-10-09": 1100.0, "2021-11-19": 16000.0, "2022-12-28": 10500.0, "2026-10-30": 20000.0})
    for rel, s in (("indices/NIFTY500_TRI.parquet", n), ("global/US_NASDAQ.parquet", q)):
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"date": s.index.date, "close": s.to_numpy()}).to_parquet(p, index=False)
    ret = n[n.index >= "2021-12-01"].pct_change().fillna(0.0)
    frames = []
    for isin, beta in (("INE00H0000001", 3.5), ("INE00L0000002", 0.1)):          # a high-beta late listing (a late listing) and a near-zero-beta one
        b = 50.0 * (1.0 + beta * ret).cumprod()
        frames.append(pd.DataFrame({"date": b.index.date, "isin": isin, "adj_close": b.to_numpy()}))
    p = r / "panel" / "prices.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(frames).to_parquet(p, index=False)
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setenv("PFLAB_DATA_DIR", str(r))
    c = store.connect(tmp_path / "s.duckdb")
    for isin, sym in (("INE00H0000001", "HIGH"), ("INE00L0000002", "LOW")):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, 'Banks', 'synthetic', now())",
                  [isin, sym, sym + " Ltd"])
        c.execute("INSERT INTO prices VALUES (?, ?, 50.0, 'EQ', 'nse_bhavcopy', now())", [isin, SDAY])
        c.execute("INSERT INTO paper_lots VALUES (?, ?, ?, ?, 100, 40.0, 'EQUITY', 'seed')", [1 if sym == "HIGH" else 2, isin, sym, date(2024, 1, 1)])
    c.execute("INSERT INTO paper_cash VALUES (1, ?, 5000.0, 'seed', 'x', now())", [date(2024, 1, 1)])
    return c, r


def test_a_high_beta_name_with_no_own_history_keeps_its_sensitivity_inside_the_bounds_and_never_falls_beyond_ninety_percent(scon):
    con, root = scon
    out = stress.run(con, SDAY, "IN", root)
    r = next(x for x in out["scopes"]["IN"]["scenarios"] if x["scenario"] == "2008")           # the index falls 50% in 2008..2009
    by = {h["symbol"]: h for h in r["holdings"]}
    assert by["HIGH"]["basis"] == "estimate" and by["LOW"]["basis"] == "estimate"            # still an estimate, with its coverage
    assert by["HIGH"]["detail"]["beta_measured"] == pytest.approx(3.5, abs=0.05) and by["HIGH"]["detail"]["beta"] == 2.0
    assert by["HIGH"]["fall_pct"] == pytest.approx(-90.0)                                    # 2.0 x -50% = -100%: held at -90%, not -98% or -100%
    assert by["LOW"]["detail"]["beta"] == 0.5 and by["LOW"]["fall_pct"] == pytest.approx(-25.0, abs=0.5)
    assert "kept at 2.0" in by["HIGH"]["detail"]["beta_note"] and "coverage_pct" in r
    assert all(h["fall_pct"] >= -90.0 for res in out["scopes"]["IN"]["scenarios"] for h in res["holdings"] if h["fall_pct"] is not None)
    json.dumps(out, default=str)
