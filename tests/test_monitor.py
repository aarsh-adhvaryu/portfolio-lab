"""S20: market-model residuals, fall classification, filings classification and alert dedup.
Synthetic series, except the two real-history checks at the end (skipped if the panel is absent)."""
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pflab.monitor import event_reaction as er
from pflab.monitor import falls, filings
from pflab.pm import store

IDX = pd.bdate_range("2025-01-01", periods=400)
EVENT = IDX[300].date()


def market(seed=1, n=400):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0004, 0.009, n), index=IDX[:n])


def stock(m, beta=1.3, alpha=0.0005, noise=0.006, seed=2, shocks=None):
    rng = np.random.default_rng(seed)
    r = alpha + beta * m + rng.normal(0, noise, len(m))
    s = pd.Series(r, index=m.index)
    for d, x in (shocks or {}).items():
        s[pd.Timestamp(d)] += x
    return s


# --- market model ----------------------------------------------------------------------------------------

def test_fit_recovers_beta_alpha_and_sigma():
    m = market()
    mm = er.fit(stock(m), m, EVENT)
    assert mm.beta == pytest.approx(1.3, abs=0.15) and mm.alpha == pytest.approx(0.0005, abs=0.001)
    assert mm.sigma == pytest.approx(0.006, abs=0.001) and mm.n == er.WINDOW


def test_fit_window_stops_before_the_event_and_ignores_the_run_up():
    m = market()
    base = er.fit(stock(m), m, EVENT)
    # a huge shock inside the gap (the 5 sessions before the event) must not move the fit
    shock = {IDX[298]: -0.30, IDX[299]: -0.30}
    assert er.fit(stock(m, shocks=shock), m, EVENT) == base
    # ... but one before the gap does
    assert er.fit(stock(m, shocks={IDX[250]: -0.30}), m, EVENT) != base


def test_fit_needs_enough_history():
    m = market()
    assert er.fit(stock(m), m, IDX[40].date()) is None            # only 35 sessions before the gap
    assert er.fit(stock(m), pd.Series(0.0, index=m.index), EVENT) is None   # a flat market has no beta


def test_abnormal_and_car_math_is_exact_for_a_noiseless_name():
    m = market()
    s = 2.0 * m                                                   # alpha 0, beta 2, no noise
    s[IDX[300]] += -0.05
    s[IDX[301]] += 0.01
    mm = er.MarketModel(0.0, 2.0, 0.004, 100)
    ab = er.abnormal(s, m, mm)
    assert ab.loc[IDX[300]] == pytest.approx(-0.05) and ab.loc[IDX[299]] == pytest.approx(0.0, abs=1e-12)
    c, se = er.car(s, m, mm, IDX[300].date(), 2)
    assert c == pytest.approx(-0.04) and se == pytest.approx(0.004 * np.sqrt(2))
    assert er.car(s, m, mm, IDX[399].date(), 5) is None            # horizon past the data


def test_newey_west_t():
    assert er.newey_west_t([1.0] * 3) is None and er.newey_west_t([0.5] * 30) is None
    t = er.newey_west_t(list(np.random.default_rng(0).normal(1.0, 1.0, 400)))
    assert t is not None and t > 10


def test_reactions_and_summary():
    m = market()
    shocks = {IDX[300]: -0.04, IDX[330]: -0.04, IDX[360]: -0.04}
    s = stock(m, shocks=shocks)
    wide = pd.DataFrame({"A": s, "B": stock(m, seed=9)})
    ev = pd.DataFrame([dict(isin="A", usable_from=IDX[300].date(), flag="DEFAULT"),
                       dict(isin="A", usable_from=IDX[330].date(), flag="DEFAULT"),
                       dict(isin="A", usable_from=IDX[360].date(), flag="FRAUD"),
                       dict(isin="A", usable_from=IDX[20].date(), flag="FRAUD"),      # no fit possible
                       dict(isin="A", usable_from=IDX[398].date(), flag="DEFAULT"),   # horizons run off the end
                       dict(isin="ZZ", usable_from=IDX[300].date(), flag="DEFAULT")])  # not in the returns
    r = er.reactions(ev, wide, m)
    assert len(r) == 6                                              # nothing dropped
    assert r["car_1"].iloc[0] == pytest.approx(-0.04, abs=0.025)
    assert np.isnan(r["car_1"].iloc[3]) and np.isnan(r["car_21"].iloc[4]) and np.isnan(r["car_1"].iloc[5])
    s = er.summarise(r)
    d1 = s[(s.flag == "DEFAULT") & (s.horizon == 1)].iloc[0]
    assert d1["n"] >= 2 and d1["share_negative"] > 0.5 and d1["mean"] < 0
    assert set(s.columns) == {"flag", "horizon", "n", "mean", "median", "share_negative", "p10", "p90"}


# --- fall classification ------------------------------------------------------------------------------------

def _case(mkt_move, stock_move, noise=0.006):
    m = market()
    m = m.copy()
    m[IDX[300]] = mkt_move
    s = stock(m, beta=1.0, alpha=0.0, noise=noise)
    s[IDX[300]] = stock_move
    return falls.classify("X", s, m, EVENT)


def test_labels():
    assert _case(-0.06, -0.065).label == "market-wide"                 # fell with the market, as expected for beta 1
    assert _case(0.002, -0.12).label == "company-specific"
    assert _case(-0.03, -0.15).label == "mixed"
    assert _case(0.003, -0.02).label == "not a fall"
    r = _case(0.0, -0.055, noise=0.03)                                 # a very noisy name, market quiet
    assert r.label == "normal volatility" and r.z > falls.Z_SPECIFIC


def test_result_numbers_are_the_market_model_split():
    r = _case(-0.06, -0.065)
    assert r.ret == pytest.approx(-0.065) and r.market_ret == pytest.approx(-0.06)
    assert r.expected == pytest.approx(r.beta * -0.06 + 0.0, abs=0.002)
    assert r.residual == pytest.approx(r.ret - r.expected) and r.z == pytest.approx(r.residual / 0.006, abs=1.5)


def test_macro_term_changes_the_expectation():
    plain = _case(0.0, -0.08)
    m = market()
    m[IDX[300]] = 0.0
    s = stock(m, beta=1.0, alpha=0.0)
    s[IDX[300]] = -0.08
    with_macro = falls.classify("X", s, m, EVENT, extra_expected=-0.075)       # a shock the factor betas explain
    assert plain.label == "company-specific" and with_macro.label == "normal volatility"
    assert with_macro.z > plain.z


def test_multi_session_window_and_missing_data():
    m = market()
    s = stock(m, beta=1.0, alpha=0.0)
    for k in range(3):
        s[IDX[300 + k]] -= 0.03
    r = falls.classify("X", s, m, EVENT, sessions=3)
    assert r.sessions == 3 and r.ret < -0.07 and r.label in ("company-specific", "mixed", "market-wide", "normal volatility")
    assert falls.classify("X", s, m, IDX[399].date(), sessions=3) is None
    assert falls.classify("X", s, m, IDX[10].date()) is None


def test_scan_lists_only_falls():
    m = market()
    s = stock(m, beta=1.0, alpha=0.0)
    s[IDX[310]] = -0.15
    df = falls.scan("X", s, m)
    assert IDX[310].date() in set(df["start"]) and (df["ret"] <= falls.FALL).all()


# --- real history (not tuned: thresholds were fixed first) ------------------------------------------------------------

PANEL = Path("D:/portfolio_lab/data/panel/prices.parquet")


def _real(isin):
    import duckdb

    from pflab.data import indices
    m = indices.load("NIFTY50_TRI")
    m["date"] = pd.to_datetime(m["date"])
    mret = m.set_index("date")["close"].pct_change().dropna()
    d = duckdb.sql(f"select date, adj_close from '{PANEL.as_posix()}' where isin='{isin}' order by date").df()
    d["date"] = pd.to_datetime(d["date"])
    return d.set_index("date")["adj_close"].pct_change().dropna(), mret


@pytest.mark.skipif(not PANEL.exists(), reason="panel not on this machine")
@pytest.mark.parametrize("isin,day,label", [
    ("INE040A01034", date(2020, 3, 23), "market-wide"),          # HDFC Bank on the Covid crash day (Nifty -13%)
    ("INE423A01024", date(2023, 1, 27), "company-specific"),     # Adani Enterprises after the Hindenburg report
    ("INE423A01024", date(2023, 2, 1), "company-specific"),
])
def test_historical_falls_are_classified_correctly(isin, day, label):
    r, mret = _real(isin)
    res = falls.classify(isin, r, mret, day)
    assert res is not None and res.label == label, res


# --- filings -------------------------------------------------------------------------------------------------------------

A_ISIN, B_ISIN = "INE111A01011", "INE222B01012"
SCRIP_MAP = pd.DataFrame([
    dict(scrip_code="500001", isin=A_ISIN, valid_from=date(2010, 1, 1), valid_to=date(2999, 12, 31)),
    dict(scrip_code="500002", isin=B_ISIN, valid_from=date(2010, 1, 1), valid_to=date(2020, 12, 31)),
    dict(scrip_code="500002", isin="INE333C01013", valid_from=date(2021, 1, 1), valid_to=date(2999, 12, 31)),   # scrip reused
])


def ann(*rows):
    base = dict(company="Co", category="Company Update", subcategory="", news_dt=pd.Timestamp("2026-09-22 10:00"),
                dissem_dt=pd.Timestamp("2026-09-22 10:00"), attachment="abc.pdf", news_sub="")
    return pd.DataFrame([{**base, **r} for r in rows])


def test_classify_flags_digest_and_watch_filter():
    a = ann(dict(scrip_code="500001", headline="Disclosure of default in payment of interest on NCD"),
            dict(scrip_code="500001", headline="Outcome of Board Meeting"),
            dict(scrip_code="500099", headline="Forensic audit appointed"))             # not watched / not mapped
    ev = filings.classify_announcements(a, [A_ISIN], SCRIP_MAP)
    assert len(ev) == 2 and set(ev["isin"]) == {A_ISIN}
    flagged = ev[ev["flag"].notna()]
    assert list(flagged["flag"]) == ["DEFAULT"] and flagged["link"].iloc[0].endswith("/abc.pdf")
    assert ev[ev["flag"].isna()]["headline"].iloc[0] == "Outcome of Board Meeting"


def test_scrip_reuse_resolves_by_date():
    old = ann(dict(scrip_code="500002", headline="Forensic audit appointed"))
    new = ann(dict(scrip_code="500002", headline="Forensic audit appointed", dissem_dt=pd.Timestamp("2022-05-01 10:00"),
                   news_dt=pd.Timestamp("2022-05-01 10:00")))
    old["dissem_dt"] = pd.Timestamp("2019-05-01 10:00")
    assert filings.classify_announcements(old, [B_ISIN], SCRIP_MAP)["isin"].tolist() == [B_ISIN]
    assert filings.classify_announcements(new, [B_ISIN], SCRIP_MAP).empty                # that scrip is a different ISIN by 2022
    assert filings.classify_announcements(new, ["INE333C01013"], SCRIP_MAP).shape[0] == 1


def test_event_ids_are_stable_and_content_dedup_keeps_the_earliest_per_day():
    a = ann(dict(scrip_code="500001", headline="Forensic audit appointed", dissem_dt=pd.Timestamp("2026-09-22 10:00")),
            dict(scrip_code="500001", headline="FORENSIC audit appointed!", dissem_dt=pd.Timestamp("2026-09-22 15:00")),
            dict(scrip_code="500001", headline="Forensic audit appointed", dissem_dt=pd.Timestamp("2026-09-23 10:00")))
    ev = filings.classify_announcements(a, [A_ISIN], SCRIP_MAP)
    again = filings.classify_announcements(a, [A_ISIN], SCRIP_MAP)
    assert list(ev["event_id"]) == list(again["event_id"]) and ev["event_id"].is_unique
    d = filings.dedup_content(ev)
    assert len(d) == 2 and list(d["t"].dt.day) == [22, 23] and d["t"].iloc[0].hour == 10


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


def _events():
    a = ann(dict(scrip_code="500001", headline="Disclosure of default in payment of interest on NCD"),
            dict(scrip_code="500001", headline="Resignation of statutory auditor", dissem_dt=pd.Timestamp("2026-09-22 11:00")))
    return filings.classify_announcements(a, [A_ISIN], SCRIP_MAP)


def test_alerts_are_off_with_no_watchlist_and_nothing_is_recorded(con):
    names = filings.targets([], filings.load_watchlist())                    # the committed watchlist is empty
    assert names == [] and not filings.alerts_enabled(names)
    sent = []
    assert filings.dispatch(con, _events(), names, sent.append) == [] and sent == []
    assert con.execute("SELECT count(*) FROM alerts_sent").fetchone()[0] == 0


def test_each_flagged_filing_alerts_once(con):
    sent = []
    first = filings.dispatch(con, _events(), [A_ISIN], sent.append)
    assert [a.flag for a in first] == ["DEFAULT", "AUDITOR_RESIGNATION"] and len(sent) == 2
    assert filings.dispatch(con, _events(), [A_ISIN], sent.append) == [] and len(sent) == 2     # re-run: nothing new
    later = _events()
    extra = ann(dict(scrip_code="500001", headline="Forensic audit appointed", dissem_dt=pd.Timestamp("2026-09-24 10:00")))
    both = pd.concat([later, filings.classify_announcements(extra, [A_ISIN], SCRIP_MAP)], ignore_index=True)
    assert [a.flag for a in filings.dispatch(con, both, [A_ISIN], sent.append)] == ["FORENSIC_AUDIT"]
    assert con.execute("SELECT count(*) FROM alerts_sent").fetchone()[0] == 3


def test_a_failed_send_is_retried_not_recorded(con):
    def boom(a):
        raise RuntimeError("telegram down")
    with pytest.raises(RuntimeError):
        filings.dispatch(con, _events(), [A_ISIN], boom)
    assert con.execute("SELECT count(*) FROM alerts_sent").fetchone()[0] == 0
    ok = []
    assert len(filings.dispatch(con, _events(), [A_ISIN], ok.append)) == 2


def test_alert_text_carries_evidence_and_no_verdict(con):
    sent = []
    filings.dispatch(con, _events(), [A_ISIN], sent.append, context_fn=lambda row: ["Past: 12 similar events, median 21-day CAR -4%"])
    t = sent[0].text()
    assert "Default" in t and "Filing: https://www.bseindia.com/xml-data/corpfiling/AttachLive/abc.pdf" in t
    assert "22-Sep-2026" in t and "Past: 12 similar events" in t and "You decide" in t
    assert "sell" not in t.lower() and "buy" not in t.lower()


def test_recent_reads_day_files_already_on_disk(tmp_path):
    d = tmp_path / "bse_announcements" / "2026"
    d.mkdir(parents=True)
    ann(dict(scrip_code="500001", headline="x")).to_parquet(d / "2026-09-22.parquet")
    r = filings.recent(3, root=tmp_path, today=date(2026, 9, 23))
    assert len(r) == 1 and filings.recent(3, root=tmp_path, today=date(2026, 9, 30)).empty
