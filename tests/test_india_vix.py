"""India VIX stitching (no network)."""
from datetime import date, timedelta

import pandas as pd
import pytest

from pflab.data import india_vix as V


def _series(start, n, level=15.0, bump=0.0):
    days = [start + timedelta(days=i) for i in range(n)]
    return pd.DataFrame({"date": days, "open": level, "high": level, "low": level,
                         "close": [level + bump + 0.001 * i for i in range(n)]})


def test_nse_wins_where_it_exists_and_yahoo_only_fills_before_it():
    y = _series(date(2008, 3, 3), 2000)             # covers all of NSE's span
    n = _series(date(2010, 7, 19), 700)
    n["close"] = y.set_index("date").loc[n["date"], "close"].values + 0.002
    out, check = V.stitch(n, y)
    assert out["date"].is_monotonic_increasing and out["date"].is_unique
    assert set(out[out["date"] < date(2010, 7, 19)]["source"]) == {"yahoo"}
    assert set(out[out["date"] >= date(2010, 7, 19)]["source"]) == {"nse"}
    assert check["median_abs_diff"] < 0.01


def test_a_disagreeing_overlap_stops_the_build():
    y = _series(date(2008, 3, 3), 1200)
    n = _series(date(2010, 7, 19), 700, bump=0.5)          # sources no longer match
    with pytest.raises(ValueError, match="disagree"):
        V.stitch(n, y)
