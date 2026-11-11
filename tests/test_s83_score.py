"""S83 L4 (the pick scorecard, `core/pick_score.py`) and L7 (stress scenarios, `core/stress.py`). Synthetic data only (rule 7).

India: stock AAA (100 on the pick's first session 2026-01-05, 110 on 2026-02-05, 95 on 2026-04-03), the Nifty 500 total return index (1000, 1030, 1090). The figures after tax are worked
from the engine's own rows: short-term equity 20% (held under a year), sell charges from `book._charges`, buy charges in the cost, no exemption per pick.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab.core import pick_score as ps
from pflab.core import stress, tax_rows
from pflab.paper import book
from pflab.pm import store
from pflab.service import jobs

AAA, BBB, SPL = "INE000A01011", "INE000B01012", "INE000S01013"
DAYS = [d.date() for d in pd.bdate_range("2025-12-01", "2026-09-30")]
D0 = date(2026, 1, 5)          # the first session after the pick was proposed (Fri 2026-01-02)
D1, D3 = date(2026, 2, 5), date(2026, 4, 3)
NOW1, NOW3 = datetime(2026, 2, 10, 20, 0), datetime(2026, 4, 10, 20, 0)


def _path(keys: dict) -> pd.Series:
    s = pd.Series({pd.Timestamp(d): v for d, v in keys.items()}).reindex(pd.DatetimeIndex([pd.Timestamp(d) for d in DAYS] + [pd.Timestamp(k) for k in keys])).sort_index()
    return s[~s.index.duplicated(keep="last")].ffill().bfill()


def _write(root, rel: str, df: pd.DataFrame) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "data"
    idx = _path({D0: 1000.0, D1: 1030.0, D3: 1090.0})
    _write(r, "indices/NIFTY500_TRI.parquet", pd.DataFrame({"date": idx.index.date, "close": idx.to_numpy()}))
    return r


@pytest.fixture
def con(tmp_path, monkeypatch, root):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setenv("PFLAB_DATA_DIR", str(root))
    c = store.connect(tmp_path / "l.duckdb")
    for isin, sym, name in ((AAA, "AAA", "Aaa Ltd"), (BBB, "BBB", "Bbb Ltd"), (SPL, "SPL", "Split Ltd")):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, 'Banks', 'synthetic', now())",
                  [isin, sym, name])
    px = _path({D0: 100.0, D1: 110.0, D3: 95.0})
    for d, v in px.items():
        c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [AAA, d.date(), float(v)])
    c.execute("CREATE TABLE IF NOT EXISTS picks_s83 (pick_id BIGINT PRIMARY KEY, market VARCHAR, isin VARCHAR, symbol VARCHAR, source VARCHAR, thesis VARCHAR, break_condition VARCHAR, "
              "storylines_json VARCHAR, session_ref VARCHAR, learned_from VARCHAR, state VARCHAR, proposed_on DATE, state_changed_on DATE, state_reason VARCHAR)")
    c.execute("CREATE TABLE IF NOT EXISTS skips_s83 (skip_id BIGINT PRIMARY KEY, market VARCHAR, isin VARCHAR, symbol VARCHAR, why VARCHAR, skipped_on DATE, session_ref VARCHAR)")
    return c


def _pick(con, pid=1, market="IN", isin=AAA, symbol="AAA", source="system", state="held", on=date(2026, 1, 2), changed=None):
    con.execute("INSERT INTO picks_s83 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [pid, market, isin, symbol, source, "a thesis of at least sixty characters, written for the test", "breaks if x", "[]", "s1", None, state, on, changed, None])


def _score(con, now, root):
    return ps.score_all(con, now, root)


def _rows(con, kind="pick"):
    cols = "horizon_months, start_on, end_on, return_pct, index_return_pct, excess_pct, tax_charges_pct, after_tax, index_raw_pct"
    return {r[0]: r for r in con.execute(f"SELECT {cols} FROM pick_scores_s83 WHERE kind=? ORDER BY horizon_months", [kind]).fetchall()}


def _hand_in(gross: float, d0: date, d1: date, ac: str = "equity") -> float:
    """The net return of 100,000 put in at d0 and sold at d1: buy charges in the cost, sell charges out of the gain, the engine's row for the tax (no exemption)."""
    rate = tax_rows.rates(d1)["st_eq"]
    buy, v = book._charges(ac, "buy", 100_000.0), 100_000.0 * (1 + gross)
    sell = book._charges(ac, "sell", v)
    return (v - sell - rate * max(0.0, v - 100_000.0 - sell)) / (100_000.0 + buy) - 1.0


# --- a pick, a sale and a skip at one month ---------------------------------------------------------------------------------------------

def test_pick_scored_at_one_month_after_tax(con, root):
    _pick(con)
    out = _score(con, NOW1, root)
    assert out["scored"]["pick"] == 1
    r = _rows(con)[1]
    assert (r[1], r[2]) == (D0, D1)                                    # starts the first session after it was proposed, ends on the last close of the horizon
    assert tax_rows.rates(D1)["st_eq"] == pytest.approx(0.20)          # the engine's row, not a typed number
    want, want_i = _hand_in(0.10, D0, D1), _hand_in(0.03, D0, D1, "etf")
    assert r[3] == pytest.approx(want * 100.0)
    assert r[4] == pytest.approx(want_i * 100.0)
    assert r[5] == pytest.approx((want - want_i) * 100.0)
    assert r[7] is True and r[8] == pytest.approx(3.0)                 # after tax; the raw index figure is kept
    assert 6.5 < r[3] < 8.5 and 0.5 < r[4] < 2.6                       # about +10% less 20% tax and charges; about +3% less the same for the index
    assert r[6] > 2.0                                                  # tax and charges in points of the cost


def test_horizons_score_only_when_elapsed_and_never_twice(con, root):
    _pick(con)
    assert _score(con, date(2026, 2, 4), root)["scored"]["pick"] == 0  # one day short of a month
    assert _score(con, NOW1, root)["scored"]["pick"] == 1
    assert _score(con, NOW1, root)["scored"]["pick"] == 0              # idempotent
    n = con.execute("SELECT count(*) FROM pick_scores_s83").fetchone()[0]
    out = _score(con, NOW3, root)
    assert out["scored"]["pick"] == 1                                  # the 3-month horizon (2026-04-05) is now past; 6 and 12 months are not
    assert sorted(_rows(con)) == [1, 3]
    assert con.execute("SELECT count(*) FROM pick_scores_s83").fetchone()[0] == n + 1
    r3 = _rows(con)[3]
    assert r3[2] == D3 and r3[3] < _rows(con)[1][3]                    # 95 against 100 at the end of three months: a loss
    assert _score(con, NOW3, root)["scored"]["pick"] == 0


def test_a_pick_cut_early_is_measured_to_the_day_it_ended(con, root):
    _pick(con, state="withdrawn", changed=date(2026, 2, 2))
    _score(con, NOW3, root)
    rows = _rows(con)
    assert rows[1][2] == date(2026, 2, 2) and rows[3][2] == date(2026, 2, 2)   # never dropped out of the record: the later horizons carry the same end


def test_a_skip_is_price_only(con, root):
    con.execute("INSERT INTO skips_s83 VALUES (1, 'IN', ?, 'AAA', 'too dear', ?, 's1')", [AAA, date(2026, 1, 2)])
    assert _score(con, NOW1, root)["scored"]["skip"] == 1
    r = _rows(con, "skip")[1]
    assert r[3] == pytest.approx(10.0) and r[4] == pytest.approx(3.0) and r[5] == pytest.approx(7.0)
    assert r[7] is False and r[6] is None                              # no tax and charges on an idea never bought


def _sale(con):
    lots = [{"acq": "2025-12-01", "take": 100.0, "cpu": 90.0, "tax_class": "EQUITY"}]
    con.execute("INSERT INTO paper_trades VALUES (1, ?, NULL, NULL, ?, 'AAA', 'sell', 100, 100.0, 12.0, 988.0, 188.0, ?)", [D0, AAA, json.dumps({"gains": {"st_eq": 988.0}})])
    con.execute("INSERT INTO exit_events_s81 (event_id, plan_id, market, isin, side, kind, day, qty, price, status, trade_id, filled_on, detail_json) "
                "VALUES (1, NULL, 'IN', ?, 'sell', 'stop', ?, 100, 100.0, 'filled', 1, ?, ?)", [AAA, D0, D0, json.dumps({"lots": lots})])


def test_a_sale_is_scored_on_the_shares_it_sold(con, root):
    _sale(con)
    assert _score(con, NOW1, root)["scored"]["sale"] == 1
    r = _rows(con, "sale")[1]
    fee = book._charges("equity", "sell", 100 * 110.0)
    hold = 100 * 110.0 - fee - 0.20 * 100 * (110.0 - 90.0)             # the same shares sold on 2026-02-05: engine tax on a short-term gain of 2,000
    proceeds = 100 * 100.0 - 12.0 - 188.0                              # what the sale actually left after charges and tax
    assert r[3] == pytest.approx((hold / proceeds - 1.0) * 100.0)
    assert r[4] == pytest.approx(_hand_in(0.03, D0, D1, "etf") * 100.0)
    assert r[5] == pytest.approx(r[3] - r[4]) and r[7] is True
    assert r[3] > r[4]                                                 # the shares went on to beat the index: selling cost something
    assert "selling cost something" in ps.scorecard(con, "IN")["recent"][0]["sentence"]


def test_a_split_and_a_dividend_in_the_window(con, root):
    px = {D0: 100.0, date(2026, 1, 19): 104.0, date(2026, 1, 20): 52.0, D1: 55.0}
    for d, v in _path(px).items():
        con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [SPL, d.date(), float(v)])
    _write(root, "corporate_actions/factors.parquet", pd.DataFrame({"isin": [SPL], "ex_date": [date(2026, 1, 20)], "factor": [0.5]}))
    _write(root, "dividends/dividends.parquet", pd.DataFrame({"isin": [SPL], "ex_date": [date(2026, 1, 25)], "dividend_per_share": [2.0]}))
    r = ps.stock_return_in(con, SPL, D0, D1, root)
    assert r["ret"] == pytest.approx((55.0 + 2.0) / (100.0 * 0.5) - 1.0)   # not -45%: the 1:2 split is undone, the cash dividend is added
    assert ps.has_action(SPL, D0, D1, root) and not ps.has_action(AAA, D0, D1, root)


def test_a_us_pick_is_scored_in_rupees(con, root):
    days = [d for d in DAYS]
    xyz, spy, fx = _path({D0: 100.0, D1: 120.0}), _path({D0: 500.0, D1: 510.0}), _path({D0: 83.0, D1: 84.0})
    for sym, s in (("XYZ", xyz), ("SPY", spy)):
        _write(root, f"us/raw/{sym}.parquet", pd.DataFrame({"date": s.index.date, "open": s.to_numpy(), "high": s.to_numpy(), "low": s.to_numpy(), "close": s.to_numpy(),
                                                              "adj_close": s.to_numpy(), "volume": 1e6, "dividend": 0.0}))
    _write(root, "global/FX_USDINR.parquet", pd.DataFrame({"date": fx.index.date, "close": fx.to_numpy()}))
    _pick(con, market="US", isin="ZZ0000000001", symbol="XYZ")
    assert _score(con, NOW1, root)["scored"]["pick"] == 1
    r = _rows(con)[1]
    pre, pre_i = 1.2 * 84.0 / 83.0 - 1.0, 1.02 * 84.0 / 83.0 - 1.0
    assert r[8] == pytest.approx(pre_i * 100.0)                        # SPY in rupees, before tax
    assert r[7] is True and 0.6 * pre * 100 < r[3] < 0.85 * pre * 100  # a short-term gain on the US route is taxed at the slab rate: well under the pre-tax figure
    assert r[4] < pre_i * 100.0 and r[5] == pytest.approx(r[3] - r[4])
    sc = ps.scorecard(con, "US")
    assert sc["picks_scored"] == 1 and "S&P 500" in sc["recent"][0]["sentence"]
    assert days                                                          # (the calendar is the SPY series itself)


# --- the count rule, the scorecard and its words -----------------------------------------------------------------------------------------

def test_under_twenty_scored_is_a_count_not_a_rate(con, root):
    for i in range(1, 20):
        _pick(con, pid=i, source="system" if i % 2 else "kite")
    _score(con, NOW1, root)
    sc = ps.scorecard(con, "IN")
    assert sc["picks_scored"] == 19 and sc["ahead_rate"] is None and sc["note"] == "a count, not a rate"
    assert sc["by_horizon"][1]["scored"] == 19 and sc["by_horizon"][1]["ahead_rate"] is None and sc["by_horizon"][3]["scored"] == 0
    assert "a count, not a rate" in ps.scorecard_text(con, "IN")
    _pick(con, pid=20)
    _score(con, NOW1, root)
    sc = ps.scorecard(con, "IN")
    assert sc["picks_scored"] == 20 and sc["ahead_rate"] == pytest.approx(sc["picks_ahead"] / 20)
    assert set(sc["by_source"]) == {"system", "kite"}


def test_scorecard_sentence_and_json(con, root):
    _pick(con)
    con.execute("INSERT INTO skips_s83 VALUES (1, 'IN', ?, 'AAA', 'x', ?, 's1')", [AAA, date(2026, 1, 2)])
    _sale(con)
    _score(con, NOW3, root)
    sc = ps.scorecard(con, "IN")
    assert set(sc) >= {"market", "picks_scored", "picks_ahead", "ahead_rate", "by_horizon", "sleeve", "recent", "skips"}
    assert set(sc["by_horizon"]) == {1, 3, 6, 12} and set(sc["sleeve"]) >= {"return_vs_index_points_a_year", "worst_fall_sleeve", "worst_fall_index", "sessions"}
    sentences = [r["sentence"] for r in sc["recent"]]
    assert any(s.startswith("PICK AAA, 3 months: ") and "against the Nifty 500's" in s and "(after estimated tax)" in s for s in sentences)
    assert any(s.startswith("SKIP AAA") and "price only" in s for s in sentences)
    json.dumps(sc)
    assert "picks" in ps.scorecard_text(con, "IN")
    assert ps.scorecard(con, "US")["picks_scored"] == 0 and "nothing has been scored" in ps.scorecard_text(con, "US")


def test_missing_tables_mean_nothing_to_score(tmp_path, monkeypatch, root):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    c = store.connect(tmp_path / "x.duckdb")
    out = ps.score_all(c, NOW1, root)
    assert out["scored"] == {"pick": 0, "sale": 0, "skip": 0}
    assert ps.scorecard(c, "IN")["picks_scored"] == 0


# --- the sleeve against the index -------------------------------------------------------------------------------------------------------------

def _sleeve_book(con, root, with_buy=False):
    s = _path({date(2026, 3, 2): 100.0, date(2026, 3, 3): 102.0, date(2026, 3, 4): 99.0})
    idx = _path({date(2026, 3, 2): 1000.0, date(2026, 3, 3): 1010.0, date(2026, 3, 4): 1005.0})
    _write(root, "indices/NIFTY500_TRI.parquet", pd.DataFrame({"date": idx.index.date, "close": idx.to_numpy()}))
    con.execute("DELETE FROM prices")
    for d, v in s.items():
        con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [AAA, d.date(), float(v)])
        con.execute("INSERT INTO prices VALUES (?, ?, 50.0, 'EQ', 'nse_bhavcopy', now())", [BBB, d.date()])
    con.execute("INSERT INTO paper_lots VALUES (1, ?, 'AAA', ?, 100, 90.0, 'EQUITY', 'seed')", [AAA, date(2025, 12, 1)])
    for d in (date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)):
        h = {AAA: 100.0}
        if with_buy and d >= date(2026, 3, 3):
            h[BBB] = 10.0
        con.execute("INSERT INTO paper_days VALUES (?, 100000, 0, 100000, 0, ?)", [d, json.dumps(h)])
    if with_buy:
        con.execute("INSERT INTO paper_lots VALUES (2, ?, 'BBB', ?, 10, 50.1, 'EQUITY', 'buy')", [BBB, date(2026, 3, 3)])
        con.execute("INSERT INTO paper_trades VALUES (5, ?, NULL, NULL, ?, 'BBB', 'buy', 10, 50.0, 0.6, NULL, NULL, '{}')", [date(2026, 3, 3), BBB])


def _at_value(price: float, d: date) -> float:
    rate = tax_rows.rates(d)["st_eq"]
    val, fee = 100 * price, book._charges("equity", "sell", 100 * price)
    return val - fee - rate * max(0.0, 100 * (price - 90.0) - fee)


def test_sleeve_record_after_tax_against_the_index(con, root):
    _sleeve_book(con, root)
    out = ps.update_sleeve_daily(con, datetime(2026, 3, 4, 20), root)
    assert out["IN"] == 3
    assert ps.update_sleeve_daily(con, datetime(2026, 3, 4, 21), root)["IN"] == 0   # incremental: a stored day is never rewritten
    rec = ps.sleeve_record(con, "IN", date(2026, 3, 4))
    r1 = _at_value(102.0, date(2026, 3, 3)) / _at_value(100.0, date(2026, 3, 2)) - 1.0
    r2 = _at_value(99.0, date(2026, 3, 4)) / _at_value(102.0, date(2026, 3, 3)) - 1.0
    assert rec["sessions"] == 2 and rec["sleeve_return_after_tax"] == pytest.approx((1 + r1) * (1 + r2) - 1.0)
    mult = lambda lvl, d: ps.liquidation_in(lvl / 1000.0 - 1.0, date(2026, 3, 2), d, "etf", "EQUITY")["value_multiple"]
    i1, i2 = mult(1010.0, date(2026, 3, 3)) / mult(1000.0, date(2026, 3, 2)) - 1.0, mult(1005.0, date(2026, 3, 4)) / mult(1010.0, date(2026, 3, 3)) - 1.0
    assert rec["index_return"] == pytest.approx((1 + i1) * (1 + i2) - 1.0) and rec["index_return_raw"] == pytest.approx(1005.0 / 1000.0 - 1.0)
    assert rec["worst_fall_sleeve"] == pytest.approx(r2) and r2 < 0        # the last day is a fall from the high
    assert rec["points_a_year"] is None and "too early" in rec["note"]     # 2 sessions: not put on a yearly basis
    assert ps.sleeve_record(con, "US")["sessions"] == 0
    json.dumps(rec)


def test_a_purchase_into_the_sleeve_is_a_flow_not_a_gain(con, root):
    _sleeve_book(con, root, with_buy=True)
    ps.update_sleeve_daily(con, datetime(2026, 3, 4, 20), root)
    rows = con.execute("SELECT day, sleeve_return_after_tax FROM pick_sleeve_daily_s83 WHERE market='IN' ORDER BY day").fetchall()
    a_only = _at_value(102.0, date(2026, 3, 3)) / _at_value(100.0, date(2026, 3, 2)) - 1.0
    assert a_only - 0.003 < rows[1][1] < a_only                        # the Rs 500 bought on day 2 is not a return (it would be +5%); only the new holding's charges (fixed sell fees) cost a little


def test_the_picks_agent_share_rule_can_read_a_window(con, root):
    _sleeve_book(con, root)
    ps.update_sleeve_daily(con, datetime(2026, 3, 4, 20), root)
    last = ps.sleeve_record(con, "IN", window=1)
    assert last["sessions"] == 1 and last["since"] == "2026-03-03"


# --- the job and the card ------------------------------------------------------------------------------------------------------------------------

def test_jobs_are_registered_and_follow_the_close_loop():
    from pflab.service import ondemand, tasks  # noqa: F401  (importing tasks loads every tasks_s79_* module)
    assert "pick_score" in jobs.REGISTRY and "stress_daily" in jobs.REGISTRY
    assert ondemand.AFTER["pick_score"][0] == "core_loop" and ondemand.AFTER["stress_daily"][0] == "core_loop"


def test_the_card_hook_adds_the_scorecard(con, root):
    from pflab.core import card
    _pick(con)
    _score(con, NOW1, root)
    got = card._picks_score(con, date(2026, 2, 10))
    assert got and set(got["json"]) == {"IN", "US"} and "India picks" in got["text"] and "US picks" in got["text"]
    json.dumps(got["json"])


# --- stress ---------------------------------------------------------------------------------------------------------------------------------------------

SDAY = date(2026, 10, 30)
KEYS_N = {"2004-01-01": 100.0, "2008-01-01": 200.0, "2009-03-09": 100.0, "2020-02-19": 300.0, "2020-03-23": 210.0, "2021-11-19": 400.0, "2022-12-28": 360.0, "2026-10-30": 500.0}
KEYS_Q = {"1999-01-01": 2000.0, "2000-03-10": 5000.0, "2002-10-09": 1100.0, "2021-11-19": 16000.0, "2022-12-28": 10500.0, "2026-10-30": 20000.0}


def _daily(keys: dict, start="1999-01-01", end="2026-10-30") -> pd.Series:
    days = pd.bdate_range(start, end)
    k = pd.Series({pd.Timestamp(d): v for d, v in keys.items()})
    s = k.reindex(k.index.union(days)).sort_index().interpolate(method="time").reindex(days)
    return s.dropna()


@pytest.fixture
def sroot(tmp_path):
    r = tmp_path / "sdata"
    n, q = _daily(KEYS_N), _daily(KEYS_Q)
    _write(r, "indices/NIFTY500_TRI.parquet", pd.DataFrame({"date": n.index.date, "close": n.to_numpy()}))
    _write(r, "global/US_NASDAQ.parquet", pd.DataFrame({"date": q.index.date, "close": q.to_numpy()}))
    a = n * 2.0                                                              # AAA moves exactly twice the index level: its own history from 2004
    ret = n[n.index >= "2021-12-01"].pct_change().fillna(0.0)
    b = 50.0 * (1.0 + 1.5 * ret).cumprod()                                   # BBB listed late: history only from 2021-12 and a beta of exactly 1.5 to the index
    panel = pd.concat([pd.DataFrame({"date": a.index.date, "isin": AAA, "adj_close": a.to_numpy()}), pd.DataFrame({"date": b.index.date, "isin": BBB, "adj_close": b.to_numpy()})])
    _write(r, "panel/prices.parquet", panel)
    return r


@pytest.fixture
def scon(tmp_path, monkeypatch, sroot):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setenv("PFLAB_DATA_DIR", str(sroot))
    c = store.connect(tmp_path / "s.duckdb")
    for isin, sym, name in ((AAA, "AAA", "Aaa Ltd"), (BBB, "BBB", "Bbb Ltd")):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, 'Banks', 'synthetic', now())",
                  [isin, sym, name])
        c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, SDAY, 1000.0 if isin == AAA else 50.0])
    c.execute("INSERT INTO paper_lots VALUES (1, ?, 'AAA', ?, 20, 400.0, 'EQUITY', 'seed')", [AAA, date(2024, 1, 1)])     # 20 x 1,000 = 20,000
    c.execute("INSERT INTO paper_lots VALUES (2, ?, 'BBB', ?, 100, 40.0, 'EQUITY', 'seed')", [BBB, date(2024, 1, 1)])     # 100 x 50 = 5,000
    c.execute("INSERT INTO paper_cash VALUES (1, ?, 5000.0, 'seed', 'x', now())", [date(2024, 1, 1)])                    # 5,000 cash: the book is 30,000
    return c


def _res(run_out, scope, name):
    return next(r for r in run_out["scopes"][scope]["scenarios"] if r["scenario"] == name)


def test_scenarios_list_the_five_and_say_which_windows_exist(sroot):
    sc = stress.scenarios(sroot)
    assert [s["name"] for s in sc] == ["AI spending bubble bursts", "2008", "2020", "the dollar falls 10% against the rupee"]
    ai = sc[0]["windows"]
    assert [(w["start"], w["end"]) for w in ai] == [("2000-03-10", "2002-10-09"), ("2021-11-19", "2022-12-28")]
    assert all(w["exists_in_data"] for w in ai) and ai[0]["nasdaq_fall_pct"] == pytest.approx((1100 / 5000 - 1) * 100, abs=0.1)
    assert sc[1]["windows"][0]["start"] == "2008-01-01" and sc[2]["windows"][0]["end"] == "2020-03-23"
    assert sc[3]["kind"] == "fx" and sc[3]["shock_pct"] == -10.0
    json.dumps(sc)


def test_own_history_and_the_estimate_for_a_late_listing(scon, sroot):
    out = stress.run(scon, SDAY, "IN", sroot)
    assert set(out["scopes"]) == {"IN"}
    r = _res(out, "IN", "2008")
    by = {h["symbol"]: h for h in r["holdings"]}
    assert by["AAA"]["basis"] == "own history" and by["AAA"]["fall_pct"] == pytest.approx(-50.0, abs=0.5)       # twice the index level: still -50%
    assert by["BBB"]["basis"] == "estimate" and by["BBB"]["detail"]["beta"] == pytest.approx(1.5, abs=0.01)
    assert by["BBB"]["fall_pct"] == pytest.approx(1.5 * -50.0, abs=1.0)                                          # the index's fall times its beta, labelled an estimate
    want = (20000 * by["AAA"]["fall_pct"] + 5000 * by["BBB"]["fall_pct"]) / 100.0 / 30000.0 * 100.0
    assert r["book_fall_pct"] == pytest.approx(want, abs=0.01) and r["book_value_inr"] == pytest.approx(30000.0)   # cash (5,000 of 30,000) does not fall
    assert r["worst_holding"]["symbol"] == "BBB"
    r20 = _res(out, "IN", "2020")
    assert {h["symbol"]: h["basis"] for h in r20["holdings"]} == {"AAA": "own history", "BBB": "estimate"}
    assert {h["symbol"]: h["fall_pct"] for h in r20["holdings"]}["AAA"] == pytest.approx(-30.0, abs=0.5)


def test_ai_bubble_uses_the_worse_window_and_says_which(scon, sroot):
    out = stress.run(scon, SDAY, "IN", sroot)
    r = _res(out, "IN", "AI spending bubble bursts")
    assert [w["window"] for w in r["windows"]] == ["2000-03-10..2002-10-09", "2021-11-19..2022-12-28"] and r["note"]
    assert r["book_fall_pct"] == min(w["book_fall_pct"] for w in r["windows"])
    by = {h["symbol"]: h for h in r["holdings"]}
    assert r["window"] == "2000-03-10..2002-10-09"                                                               # the 2000-02 fall (-78%) is the worse one
    assert by["AAA"]["basis"] == "estimate" and by["AAA"]["detail"]["market_series"] == "nasdaq"                  # AAA has no history back to 2000: Nasdaq fall times its weekly beta
    assert by["AAA"]["fall_pct"] == pytest.approx(by["AAA"]["detail"]["market_return_pct"] * by["AAA"]["detail"]["beta"], abs=0.01)
    w2 = [w for w in r["windows"] if w["window"].startswith("2021")][0]
    assert w2["book_fall_pct"] > r["book_fall_pct"]


def test_the_dollar_scenario_hits_only_the_us_sub_book(scon, sroot, monkeypatch):
    xyz = _daily({"2021-06-01": 50.0, "2026-10-30": 100.0}, "2021-06-01")
    spy = _daily({"1999-01-01": 100.0, "2008-01-01": 150.0, "2009-03-09": 80.0, "2026-10-30": 600.0})
    fx = _daily({"1999-01-01": 40.0, "2026-10-30": 85.0})
    for sym, s in (("XYZ", xyz), ("SPY", spy)):
        _write(sroot, f"us/raw/{sym}.parquet", pd.DataFrame({"date": s.index.date, "open": s.to_numpy(), "high": s.to_numpy(), "low": s.to_numpy(), "close": s.to_numpy(),
                                                               "adj_close": s.to_numpy(), "volume": 1e6, "dividend": 0.0}))
    _write(sroot, "global/FX_USDINR.parquet", pd.DataFrame({"date": fx.index.date, "close": fx.to_numpy()}))
    _write(sroot, "macro/USDINR.parquet", pd.DataFrame({"date": fx.index.date, "value": fx.to_numpy()}))
    scon.execute("INSERT INTO us_account_s81 VALUES (1, ?, 100000, 80.0, 'MARKET', 1250.0, 0.1, 'x', now())", [date(2026, 9, 1)])
    scon.execute("INSERT INTO us_lots_s81 VALUES (1, 'ZZ0000000001', 'XYZ', ?, 10, 80.0, 80.0, 'x', 'buy')", [date(2026, 9, 2)])
    scon.execute("INSERT INTO us_cash_s81 VALUES (1, ?, 1000.0, 'seed', 'x', now())", [date(2026, 9, 1)])
    out = stress.run(scon, SDAY, "ALL", sroot)
    assert set(out["scopes"]) == {"IN", "US", "ALL"} and "us.wholebook not available" in out["whole_book_source"]
    us_total = (10 * 100.0 + 1000.0) * 85.0                                                                     # 10 shares at USD 100 and USD 1,000 cash at 85
    assert out["scopes"]["US"]["value_inr"] == pytest.approx(us_total)
    fxn = "the dollar falls 10% against the rupee"
    assert _res(out, "US", fxn)["book_fall_pct"] == pytest.approx(-10.0) and _res(out, "IN", fxn)["book_fall_pct"] == 0.0
    assert _res(out, "ALL", fxn)["book_fall_pct"] == pytest.approx(-10.0 * us_total / (30000.0 + us_total), abs=0.01)
    assert _res(out, "US", fxn)["holdings"][0]["basis"] == "stated shock"
    x = {h["symbol"]: h for h in _res(out, "US", "2008")["holdings"]}["XYZ"]
    assert x["basis"] == "estimate" and x["detail"]["market_series"] == "spy"                                   # XYZ has no history in 2008: SPY's fall times its beta
    assert x["detail"]["fx"].startswith("the dollar-rupee move")
    # the whole-book helper is used when another agent's module is importable
    fake = types.SimpleNamespace(whole_book_inr=lambda con, day, root=None: {"rupee_book_inr": 30000.0, "us_book_inr": 2 * us_total})
    monkeypatch.setitem(sys.modules, "pflab.us.wholebook", fake)
    monkeypatch.setattr("pflab.us.wholebook", fake, raising=False)
    out2 = stress.run(scon, SDAY, "ALL", sroot)
    assert out2["whole_book_source"].startswith("the whole book from us.wholebook") and out2["scopes"]["US"]["value_inr"] == pytest.approx(2 * us_total)


def test_stress_is_stored_with_its_holdings_and_read_back(scon, sroot):
    res = stress.run_and_store(scon, SDAY, "IN", sroot)
    assert res["stored"] == 4
    again = stress.run_and_store(scon, SDAY, "IN", sroot)                                                         # a re-run of the day replaces its rows
    assert scon.execute("SELECT count(*) FROM stress_s83").fetchone()[0] == 4
    row = scon.execute("SELECT scope, scenario, fall_pct, detail_json FROM stress_s83 WHERE scenario='2008'").fetchone()
    det = json.loads(row[3])
    assert row[0] == "IN" and row[2] == pytest.approx(_res(again, "IN", "2008")["book_fall_pct"]) and {h["symbol"] for h in det["holdings"]} == {"AAA", "BBB"}
    lt = stress.latest(scon)
    assert lt["day"] == str(SDAY) and len(lt["scopes"]["IN"]["scenarios"]) == 4
    json.dumps(lt)
    json.dumps(again)


def test_latest_with_nothing_stored(scon):
    assert stress.latest(scon)["day"] is None
