"""The 2019-12-19 ETF unit split and ISIN switch (E3 readiness §2)."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from conftest import make_panel, flat_index
from pflab.data import etf_events as ee

OLD, NEW = "INF732E01011", "INF204KB14I2"


def _panel():
    sessions = list(pd.bdate_range("2019-12-10", "2019-12-31").date)
    px = np.array([1290.0 + i for i in range(len(sessions))])
    split = sessions.index(date(2019, 12, 19))
    px[split:] = px[split:] / 10.0
    p = make_panel(sessions, [OLD], {OLD: px})
    p["instrument_type"] = "ETF"
    p.loc[p["date"] >= date(2019, 12, 20), "isin"] = NEW
    stock = make_panel(sessions, ["INE000A01011"], {"INE000A01011": np.full(len(sessions), 50.0)})
    return sessions, pd.concat([p, stock], ignore_index=True)


def test_series_is_continuous_and_one_isin_after_the_fix():
    _, p = _panel()
    q, acts, rep = ee.apply(p, None, ee.DECLARED[:1])
    e = q[q["instrument_type"] == "ETF"].sort_values("date")
    assert set(e["isin"]) == {NEW}
    r = e["adj_close"].pct_change().dropna()
    assert r.abs().max() < 0.01
    assert rep[0]["rows_rekeyed"] == 8 and rep[0]["rows_adjusted"] == 7   # 12-10..12-19; before 12-19
    assert acts.iloc[0].to_dict()["factor"] == 0.1


def test_stock_rows_are_untouched():
    _, p = _panel()
    q, _, _ = ee.apply(p, None)
    pd.testing.assert_frame_equal(
        p[p["instrument_type"] == "STK"].reset_index(drop=True),
        q[q["instrument_type"] == "STK"].reset_index(drop=True))


def test_a_holder_keeps_its_value_across_the_split_in_the_engine():
    from pflab.tax.india_lots import LotBook, TaxPolicy
    book = LotBook(TaxPolicy())
    book.buy(NEW, date(2019, 12, 11), 10, 1291.0)
    book.adjust_shares(NEW, 0.1)
    assert book.holdings(NEW) == 100


def test_refuses_a_non_etf_row():
    _, p = _panel()
    p.loc[p["isin"] == OLD, "instrument_type"] = "STK"
    with pytest.raises(ee.ETFEventError):
        ee.apply(p, None, ee.DECLARED[:1])


def test_real_panel_nifty_and_gold_bees_become_continuous():
    """Against the real panel when it is present; skipped in a bare checkout."""
    from pflab.data import data_dir
    f = data_dir() / "panel" / "prices.parquet"
    if not f.exists():
        pytest.skip("no panel on this machine")
    import duckdb
    p = duckdb.sql(f"select * from '{f.as_posix()}' where symbol in "
                   f"('NIFTYBEES','GOLDBEES') and date between '2019-11-01' "
                   f"and '2020-01-31'").df()
    p["date"] = pd.to_datetime(p["date"]).dt.date
    q, acts, rep = ee.apply(p, None)
    for sym in ("NIFTYBEES", "GOLDBEES"):
        s = q[q["symbol"] == sym].sort_values("date")
        assert s["isin"].nunique() == 1
        assert s["adj_close"].pct_change().abs().max() < 0.05, sym
    assert len(acts) == 2
