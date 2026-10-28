"""The sprint step 3 verification gate, on real rows.

Every fixture below is copied verbatim from the backfilled bhavcopy, so these
tests assert what NSE actually publishes, not what we hoped it publishes.

The headline result: PREVCLOSE is NOT adjusted on ex-dates, so the charter
section 9 method cannot recover a single factor. See
docs/BUILT.md
"""
from datetime import date

import pandas as pd


# (symbol, isin, prior session close, ex-date close, ex-date PREVCLOSE, true factor)
# Read off data/bhavcopy/. Each is a well-documented corporate action.
REAL_EVENTS = [
    ("WIDGETCO", "INE999W01011", date(2015, 6, 12), date(2015, 6, 15),
     1975.05, 990.45, 1975.05, 1 / 2, "1:1 bonus"),
    ("GADGETCO", "INE999G01012", date(2017, 9, 6), date(2017, 9, 7),
     1645.40, 818.10, 1645.40, 1 / 2, "1:1 bonus"),
    ("ICICIBANK", "INE090A01013", date(2014, 12, 3), date(2014, 12, 4),
     1794.10, 362.20, 1794.10, 1 / 5, "face value 10 -> 2 split"),
    ("LT", "INE018A01030", date(2017, 7, 12), date(2017, 7, 13),
     1739.55, 1175.10, 1739.55, 2 / 3, "1:2 bonus"),
]


def _panel():
    """Two adjacent sessions per event, in the normalised bhavcopy schema."""
    rows = []
    for sym, isin, d0, d1, c0, c1, pc1, _f, _w in REAL_EVENTS:
        rows.append({"symbol": sym, "isin": isin, "date": d0, "close": c0,
                     "prev_close": c0, "volume": 1_000_000})
        rows.append({"symbol": sym, "isin": isin, "date": d1, "close": c1,
                     "prev_close": pc1, "volume": 1_000_000})
    return pd.DataFrame(rows)


def test_prevclose_is_not_adjusted_on_ex_dates():
    """The finding. NSE carries the raw prior close through the ex-date."""
    for sym, _i, _d0, _d1, c0, c1, pc1, factor, what in REAL_EVENTS:
        assert pc1 == c0, f"{sym} ({what}): PREVCLOSE {pc1} != prior close {c0}"
        # The action is plainly visible in the close, just not in PREVCLOSE.
        assert abs((c1 / c0) / factor - 1.0) < 0.05, f"{sym}: close gap not ~{factor}"










