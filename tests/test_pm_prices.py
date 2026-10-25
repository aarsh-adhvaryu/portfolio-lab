"""S8: price, NAV, gold and live-quote ingestion and staleness. Parsers use real
page excerpts (tests/fixtures); everything else is synthetic."""
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from pflab.pm import instruments as ins
from pflab.pm import prices as px
from pflab.pm import store

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


def _bhav(rows):
    return pd.DataFrame(rows, columns=["date", "isin", "series", "close"])


# --- bhavcopy -------------------------------------------------------------------

def test_bhavcopy_rows_keep_etf_sgb_bond_series_and_drop_bad(con):
    df = _bhav([
        (date(2026, 9, 16), "INE000000011", "EQ", 100.0),
        (date(2026, 9, 16), "INF000000022", "EQ", 50.0),      # ETF
        (date(2026, 9, 16), "IN0020200104", "GB", 15007.61),  # SGB
        (date(2026, 9, 16), "IN0020230010", "GS", 101.2),     # G-sec
        (date(2026, 9, 16), "INE000000039", "N1", 1005.0),    # bond
        (date(2026, 9, 16), None, "EQ", 10.0),                # no ISIN
        (date(2026, 9, 16), "INE000000047", "BE", 0.0),       # no close
    ])
    assert px.load_bhavcopy(con, df) == 5
    assert px.load_bhavcopy(con, df) == 0                      # idempotent
    got = dict(con.execute("SELECT isin, series FROM prices").fetchall())
    assert got["IN0020200104"] == "GB" and "INE000000047" not in got


def test_same_isin_two_series_one_row_per_day(con):
    df = _bhav([(date(2026, 9, 16), "INE000000011", "EQ", 100.0),
                (date(2026, 9, 16), "INE000000011", "BE", 99.0)])
    assert px.load_bhavcopy(con, df) == 1


# --- AMFI -------------------------------------------------------------------------

NAVALL = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Flexi Cap Fund)

Axis Mutual Fund

101;INF000A01AB9;INF000A01AC7;Axis Flexi;Direct Plan;IDCW Option;9.5;05-Oct-2026
"""


def test_navs_from_navall_both_isins(con):
    n = px.navs_from_navall(ins.parse_navall(NAVALL))
    assert sorted(n["isin"]) == ["INF000A01AB9", "INF000A01AC7"] and set(n["nav"]) == {9.5}
    assert px.load_navs(con, n, "amfi_navall") == 2 and px.load_navs(con, n, "amfi_navall") == 0


def test_parse_nav_history_real_excerpt():
    h = px.parse_nav_history((FIX / "amfi_nav_history_excerpt.txt").read_text(encoding="utf-8"))
    assert list(h.columns) == ["isin", "scheme_code", "date", "nav"]
    assert len(h) == 2                       # unclaimed pools have no ISIN: dropped
    assert h["isin"].unique().tolist() == ["INF846K01DP8"]
    assert h.sort_values("date").nav.tolist() == [65.82, 66.11]


def test_nav_history_continuity(con):
    days = list(pd.bdate_range("2026-09-01", "2026-09-30").date)
    rows = [("INF000A01AB9", "101", d, 10.0 + i * 0.01) for i, d in enumerate(days)
            if not (date(2026, 9, 10) <= d <= date(2026, 9, 18))]       # 7 business days missing
    px.load_navs(con, pd.DataFrame(rows, columns=["isin", "scheme_code", "date", "nav"]), "x")
    assert px.nav_gaps(con, "INF000A01AB9") == [(date(2026, 9, 9), date(2026, 9, 21), 7)]
    assert px.nav_gaps(con, "INF000A01AB9", max_gap_business_days=7) == []
    assert px.nav_gaps(con, "INF_NONE") == []


def test_one_missing_day_is_not_a_gap(con):
    rows = [("I", "1", d, 1.0) for d in pd.bdate_range("2026-09-01", "2026-09-10").date if d != date(2026, 9, 4)]
    px.load_navs(con, pd.DataFrame(rows, columns=["isin", "scheme_code", "date", "nav"]), "x")
    assert px.nav_gaps(con, "I") == []


# --- IBJA -------------------------------------------------------------------------

def test_parse_ibja_real_excerpt(con):
    g = px.parse_ibja((FIX / "ibja_page_excerpt.html").read_text(encoding="utf-8"))
    first = g[(g.date == date(2026, 10, 5)) & (g.session == "AM")].set_index("metal").rate
    assert first["gold999"] == 147785 and first["silver999"] == 222934 and first["gold916"] == 135371
    pm = g[(g.date == date(2026, 10, 5)) & (g.session == "PM")].set_index("metal").rate
    assert pm["gold999"] == 148198
    assert set(g[g.metal == "silver999"].unit) == {"per_kg"} and set(g[g.metal == "gold999"].unit) == {"per_10g"}
    assert px.load_gold(con, g) == len(g) and px.load_gold(con, g) == 0


def test_gold_mark_uses_pm_then_am_and_flags_stale(con):
    g = pd.DataFrame([(date(2026, 10, 1), "AM", "gold999", 148687.0, "per_10g"),
                      (date(2026, 10, 5), "AM", "gold999", 147785.0, "per_10g"),
                      (date(2026, 10, 5), "PM", "gold999", 148198.0, "per_10g")],
                     columns=["date", "session", "metal", "rate", "unit"])
    px.load_gold(con, g)
    m = px.gold_mark(con, 25.0, "gold999", date(2026, 10, 6))
    assert m["value"] == pytest.approx(2.5 * 148198.0) and m["session"] == "PM" and m["stale"] is False
    assert px.gold_mark(con, 10.0, "gold999", date(2026, 10, 9))["stale"] is True
    assert px.gold_mark(con, 10.0, "gold999", date(2026, 10, 2))["rate"] == 148687.0
    with pytest.raises(LookupError):
        px.gold_mark(con, 10.0, "gold999", date(2026, 9, 1))


# --- staleness ----------------------------------------------------------------------

def _load_closes(con, isin, days, series="EQ"):
    px.load_bhavcopy(con, _bhav([(d, isin, series, 100.0 + i) for i, d in enumerate(days)]))


def test_close_stale_after_one_session(con):
    days = [date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)]      # Mon-Wed
    _load_closes(con, "A", days)
    _load_closes(con, "B", days[:2])                                       # missed the 16th
    q = px.latest_price(con, "A", date(2026, 9, 16))
    assert (q.kind, q.age, q.stale) == ("close", 0, False)
    q = px.latest_price(con, "B", date(2026, 9, 16))
    assert (q.age, q.stale) == (1, False)                                  # one session old: allowed
    _load_closes(con, "C", days[:1])
    q = px.latest_price(con, "C", date(2026, 9, 16))
    assert (q.age, q.stale) == (2, True)


def test_holiday_is_not_a_session(con):
    # 16 Sep is a Wednesday here; no session on the 15th (holiday): Mon close is 1 session old on Wed.
    _load_closes(con, "A", [date(2026, 9, 14), date(2026, 9, 16)])
    _load_closes(con, "X", [date(2026, 9, 14), date(2026, 9, 16)])
    assert px.latest_price(con, "A", date(2026, 9, 16)).stale is False
    _load_closes(con, "H", [date(2026, 9, 14)])
    assert px.latest_price(con, "H", date(2026, 9, 16)).age == 1           # 15th is not in the calendar


def test_weekdays_beyond_stored_data_count_as_sessions(con):
    _load_closes(con, "A", [date(2026, 9, 16)])
    assert px.latest_price(con, "A", date(2026, 9, 18)).age == 2            # data not collected yet
    assert px.latest_price(con, "A", date(2026, 9, 18)).stale is True
    assert px.latest_price(con, "A", date(2026, 9, 19)).age == 2            # Saturday adds nothing


def test_nav_stale_after_one_business_day(con):
    px.load_navs(con, pd.DataFrame([("F", "1", date(2026, 10, 5), 10.0)],
                                   columns=["isin", "scheme_code", "date", "nav"]), "x")
    assert px.latest_price(con, "F", date(2026, 10, 6)).stale is False
    q = px.latest_price(con, "F", date(2026, 10, 7))
    assert (q.kind, q.age, q.stale) == ("nav", 2, True)
    assert px.latest_price(con, "F", date(2026, 10, 3)) is None            # nothing on or before


def test_etf_prefers_newer_of_close_and_nav_ties_to_close(con):
    _load_closes(con, "E", [date(2026, 9, 16)])
    px.load_navs(con, pd.DataFrame([("E", "9", date(2026, 9, 16), 99.0)],
                                   columns=["isin", "scheme_code", "date", "nav"]), "x")
    assert px.latest_price(con, "E", date(2026, 9, 16)).kind == "close"
    px.load_navs(con, pd.DataFrame([("E", "9", date(2026, 9, 17), 99.5)],
                                   columns=["isin", "scheme_code", "date", "nav"]), "x")
    assert px.latest_price(con, "E", date(2026, 9, 17)).kind == "nav"


def test_coverage_and_acceptance_helper(con):
    _load_closes(con, "A", [date(2026, 9, 16)])
    cov = px.coverage(con, ["A", "Z"], date(2026, 9, 16))
    assert cov.set_index("isin").kind.to_dict() == {"A": "close", "Z": "none"}
    assert px.all_priced_fresh(con, ["A"], date(2026, 9, 16)) is True
    assert px.all_priced_fresh(con, ["A", "Z"], date(2026, 9, 16)) is False
    assert px.all_priced_fresh(con, ["A"], date(2026, 9, 21)) is False


# --- live poller ----------------------------------------------------------------------

def test_market_hours():
    assert px.market_open(datetime(2026, 10, 6, 9, 15)) and px.market_open(datetime(2026, 10, 6, 15, 30))
    assert not px.market_open(datetime(2026, 10, 6, 9, 14)) and not px.market_open(datetime(2026, 10, 6, 15, 31))
    assert not px.market_open(datetime(2026, 10, 10, 11, 0))               # Saturday


def test_poller_batches_and_only_runs_in_hours(con):
    calls = []

    def quote(batch):
        calls.append(len(batch))
        return {i: 10.0 for i in batch}

    p = px.LivePoller(con, [f"I{k}" for k in range(1100)], quote)
    assert p.poll(datetime(2026, 10, 6, 8, 0)) == 0 and calls == []
    assert p.poll(datetime(2026, 10, 6, 10, 0)) == 1100 and calls == [500, 500, 100]
    assert p.poll(datetime(2026, 10, 6, 10, 0)) == 1100                     # same ts: ignored on conflict
    assert con.execute("SELECT count(*) FROM live_quotes").fetchone()[0] == 1100


def test_live_quote_wins_only_for_the_same_day(con):
    _load_closes(con, "A", [date(2026, 10, 5)])
    px.LivePoller(con, ["A"], lambda b: {"A": 123.0}).poll(datetime(2026, 10, 6, 11, 0))
    q = px.latest_price(con, "A", date(2026, 10, 6))
    assert (q.kind, q.value, q.stale) == ("live", 123.0, False)
    assert px.latest_price(con, "A", date(2026, 10, 5)).kind == "close"
