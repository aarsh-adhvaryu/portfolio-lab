"""S48 arm 1 helpers: symbol to ISIN only with a date; the one-sided Newey-West test. SYNTHETIC."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest





class Resp:
    def __init__(self, j):
        self.j, self.text = j, "{}"

    def json(self):
        return self.j

    def raise_for_status(self):
        pass


def test_deals_collector_asks_day_by_day_flags_the_cap_and_resumes(tmp_path):
    from datetime import date

    from pflab.data import nse_deals as nd
    asked = []

    def get(url, params, timeout):
        asked.append((params["optionType"], params["from"]))
        n = 70 if params["from"] == "03-03-2017" else 2
        return Resp({"data": [{"BD_DT_DATE": params["from"].replace("-03-", "-MAR-"), "BD_SYMBOL": "ABC",
                               "BD_CLIENT_NAME": "X FUND", "BD_BUY_SELL": "BUY", "BD_QTY_TRD": 100, "BD_TP_WATP": 10.0}] * n})
    out = nd.collect(date(2017, 3, 1), date(2017, 3, 8), kinds=("bulk",), root=tmp_path, get=get, pause=0, log=lambda s: None)
    assert out["months"] == 1 and out["capped_days"] == 1 and len(asked) == 6          # weekdays 1-8 March 2017
    df = nd.load(tmp_path)
    assert df["capped"].sum() == 70 and set(df["side"]) == {"BUY"}
    assert nd.collect(date(2017, 3, 1), date(2017, 3, 8), kinds=("bulk",), root=tmp_path, get=get, pause=0,
                      log=lambda s: None)["skipped"] == 1 and len(asked) == 6            # the month is on disk


def test_collectors_ride_out_a_dropped_connection_and_retry_failures_next_run(tmp_path):
    from datetime import date

    from pflab.data import bse_institutions as bi
    from pflab.data import nse_deals as nd
    calls = {"n": 0}

    def flaky_deals(url, params, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("hotspot dropped")
        return Resp({"data": []})
    assert nd.collect(date(2017, 3, 1), date(2017, 3, 1), kinds=("bulk",), root=tmp_path, get=flaky_deals, pause=0,
                      log=lambda s: None)["months"] == 1 and calls["n"] == 2

    def down(url, params, headers, timeout):
        raise ConnectionError("no network")
    bi.collect(["1"], [100], root=tmp_path, get=down, pause=0, log=lambda s: None)
    assert bi.load(tmp_path)["status"].iloc[0].startswith("error")

    class Ok(Resp):
        text = "{}"
    up = lambda url, params, headers, timeout: Ok({"Table1": [{"Fld_Level": "Sub Total B1", "Fld_SubCategory": "Institutions",
                                                               "Fld_TotalPercentageOf_A_B_C2": 25.0}]})
    out = bi.collect(["1"], [100], root=tmp_path, get=up, pause=0, log=lambda s: None)
    assert out["fetched"] == 1 and bi.load(tmp_path)["inst_pct"].iloc[0] == 25.0      # the failed one was fetched again


def test_institutional_holding_sums_the_institution_subtotals_in_both_formats():
    from pflab.data import bse_institutions as bi
    old = [{"Fld_Level": "Sub Total B1", "Fld_SubCategory": "Institutions", "Fld_TotalPercentageOf_A_B_C2": 30.5},
           {"Fld_Level": "Mutual Funds/", "Fld_SubCategory": "Institutions", "Fld_TotalPercentageOf_A_B_C2": 4.0},
           {"Fld_Level": "Sub Total B3", "Fld_SubCategory": "Non-Institutions", "Fld_TotalPercentageOf_A_B_C2": 12.0}]
    new = [{"Fld_Level": "Sub Total B1", "Fld_SubCategory": "Institutions (Domestic)", "Fld_TotalPercentageOf_A_B_C2": 21.0},
           {"Fld_Level": "Sub Total B2", "Fld_SubCategory": "Institutions (Foreign)", "Fld_TotalPercentageOf_A_B_C2": 19.5},
           {"Fld_Level": "Foreign Portfolio Investors Category I", "Fld_SubCategory": "Institutions (Foreign)",
            "Fld_TotalPercentageOf_A_B_C2": 17.0}]
    assert bi.parse(old)["inst_pct"] == pytest.approx(30.5) and bi.parse(old)["mf_pct"] == 4.0
    assert bi.parse(new)["inst_pct"] == pytest.approx(40.5) and bi.parse(new)["fpi_pct"] == 17.0
    assert bi.parse([])["status"] == "no institution subtotal"




