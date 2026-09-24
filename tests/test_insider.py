"""NSE structured insider (PIT) disclosures and the BSE cross-check.

The defect locked down here was found live on 2026-09-23 and is the reason
`fetch_window` returns a union rather than one answer: NSE's whole-month
request silently omits rows that a request for either half returns. It
happened in four months of 2015-2026 (2023-09 by 7 rows, 2023-12 by 1,
2024-10 by 2, 2025-03 by 64). Nothing in the response says so -- there is
no row count to check against -- so only asking twice catches it.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from pflab.data import nse_insider as ni


def _row(did, symbol="ACME", when="15-Mar-2017 10:00", qty="100", who="A Person"):
    return {"did": did, "pid": "p" + str(did), "symbol": symbol, "date": when,
            "secAcq": qty, "acqName": who, "company": "Acme Ltd",
            "personCategory": "Promoters", "acqMode": "Market Purchase",
            "tdpTransactionType": "Buy", "secType": "Equity Shares",
            "secVal": "10000", "buyQuantity": "100", "buyValue": "10000",
            "sellquantity": "0", "sellValue": "0", "befAcqSharesNo": "900",
            "befAcqSharesPer": "1.00", "afterAcqSharesNo": "1000",
            "afterAcqSharesPer": "1.10", "acqfromDt": "14-Mar-2017",
            "acqtoDt": "14-Mar-2017", "intimDt": "15-Mar-2017", "anex": "7(2)",
            "exchange": "NSE", "remarks": "-"}


class _Scripted:
    """Answers a window from a table keyed by (from_date, to_date)."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def get(self, url, params=None, timeout=None):
        key = (params["from_date"], params["to_date"])
        self.calls.append(key)
        rows = self.table.get(key, [])

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"data": rows}

        return R()


def test_whole_window_deficit_is_recovered_not_dropped():
    """The live defect: the halves hold a row the whole month does not."""
    whole = [_row(1), _row(2)]
    h1 = [_row(1), _row(3)]          # row 3 exists only in the first half
    h2 = [_row(2)]
    s = _Scripted({("01-03-2017", "31-03-2017"): whole,
                   ("01-03-2017", "16-03-2017"): h1,
                   ("17-03-2017", "31-03-2017"): h2})
    rows, deficit = ni.fetch_window(s, date(2017, 3, 1), date(2017, 3, 31), sleep=0)
    assert deficit == 1
    assert {r["did"] for r in rows} == {1, 2, 3}


def test_no_deficit_when_the_partition_agrees():
    whole = [_row(1), _row(2)]
    s = _Scripted({("01-03-2017", "31-03-2017"): whole,
                   ("01-03-2017", "16-03-2017"): [_row(1)],
                   ("17-03-2017", "31-03-2017"): [_row(2)]})
    rows, deficit = ni.fetch_window(s, date(2017, 3, 1), date(2017, 3, 31), sleep=0)
    assert deficit == 0
    assert len(rows) == 2


def test_union_never_invents_a_row():
    """Every row in the union came from the source, for a sub-window of the
    same period. The union may only ever be a superset of the whole answer."""
    whole = [_row(1)]
    s = _Scripted({("01-03-2017", "31-03-2017"): whole,
                   ("01-03-2017", "16-03-2017"): [_row(1), _row(9)],
                   ("17-03-2017", "31-03-2017"): []})
    rows, _ = ni.fetch_window(s, date(2017, 3, 1), date(2017, 3, 31), sleep=0)
    served = {1, 9}
    assert {r["did"] for r in rows} <= served


def test_single_day_window_asks_once():
    s = _Scripted({("15-03-2017", "15-03-2017"): [_row(1)]})
    rows, deficit = ni.fetch_window(s, date(2017, 3, 15), date(2017, 3, 15), sleep=0)
    assert deficit == 0 and len(s.calls) == 1


def test_row_key_separates_two_people_in_one_filing():
    """A filing can name several insiders; keying on the filing alone would
    collapse them, which is the mistake bse_announcements made with NEWSID."""
    a, b = _row(5, who="First Person"), _row(5, who="Second Person")
    assert ni.row_key(a) != ni.row_key(b)


def test_normalize_parses_the_broadcast_timestamp_not_the_trade_date():
    df = ni.normalize([_row(1)])
    assert df["broadcast_dt"].iloc[0] == pd.Timestamp("2017-03-15 10:00")
    # the trade happened the day before; it must not become the PIT key
    assert df["from_dt"].iloc[0] == pd.Timestamp("2017-03-14")
    assert df["broadcast_dt"].iloc[0] > df["from_dt"].iloc[0]


def test_normalize_turns_nse_dashes_into_missing_not_zero():
    r = _row(1)
    r["befAcqSharesPer"] = "-"
    r["secVal"] = "-"
    df = ni.normalize([r])
    assert pd.isna(df["pct_before"].iloc[0])
    assert pd.isna(df["value"].iloc[0])


def test_normalize_of_nothing_keeps_the_schema():
    df = ni.normalize([])
    assert list(df.columns) == ni.COLUMNS and len(df) == 0


def test_probed_span_is_recorded_on_the_module():
    """The feed starts 2015-11-19 and stops 2026-05-02 (probed 2026-09-23).
    A collector that defaulted to 2010 would write 60 empty months and call
    them collected."""
    assert ni.FIRST_DATA_DATE == date(2015, 11, 19)
    assert ni.LAST_DATA_DATE == date(2026, 5, 2)
