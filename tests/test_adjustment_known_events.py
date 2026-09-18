"""The sprint step 3 verification gate, on real rows.

Every fixture below is copied verbatim from the backfilled bhavcopy, so these
tests assert what NSE actually publishes, not what we hoped it publishes.

The headline result: PREVCLOSE is NOT adjusted on ex-dates, so the charter
section 9 method cannot recover a single factor. See
docs/data/adjustment_method_finding.md.
"""
from datetime import date

import pandas as pd

from pflab.data import corporate_actions as ca

# (symbol, isin, prior session close, ex-date close, ex-date PREVCLOSE, true factor)
# Read off data/bhavcopy/. Each is a well-documented corporate action.
REAL_EVENTS = [
    ("INFY", "INE009A01021", date(2015, 6, 12), date(2015, 6, 15),
     1975.05, 990.45, 1975.05, 1 / 2, "1:1 bonus"),
    ("RELIANCE", "INE002A01018", date(2017, 9, 6), date(2017, 9, 7),
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


def test_prevclose_method_detects_no_known_event():
    """charter section 9 as written yields nothing on any of the four events."""
    cands = ca.candidates(_panel())
    assert cands.empty, f"unexpectedly found {len(cands)} candidate(s)"


def test_verification_gate_fails_and_names_every_event():
    """The gate must fail loudly rather than let empty factors through."""
    failures = ca.verify_known_events(ca.candidates(_panel()))
    assert len(failures) == len(ca.KNOWN_EVENTS)
    assert all("no candidate detected" in f for f in failures)


def test_snap_pulls_near_misses_onto_common_ratios():
    assert ca.snap(0.4972) == 1 / 2          # RELIANCE, within 1%
    assert ca.snap(0.2005) == 1 / 5
    assert ca.snap(0.6711) == 2 / 3
    # A 2.2% miss stays raw -- this is why the close-gap substitute also fails.
    assert ca.snap(0.4889) == 0.4889
    assert ca.snap(0.2045) == 0.2045


def test_candidates_needs_adjacent_sessions_and_two_sided_volume():
    """A name that did not trade on one side is never a candidate."""
    p = _panel()
    p.loc[p["symbol"] == "INFY", "volume"] = 0
    assert ca.candidates(p).empty


def test_adjustment_factors_multiplies_same_day_actions():
    cands = pd.DataFrame({
        "isin": ["INE1", "INE1"],
        "ex_date": [date(2020, 1, 2)] * 2,
        "raw_ratio": [0.5, 2 / 3],
        "snapped_factor": [0.5, 2 / 3],
        "volume_ratio": [2.0, 1.5],
    })
    out = ca.adjustment_factors(cands)
    assert len(out) == 1
    assert abs(out.loc[0, "factor"] - (0.5 * 2 / 3)) < 1e-12
