"""S64: the valuation facts the brain reasons with, and the rules of thumb as untested flags."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.hq import valuation as vl


def quarters(scrip="1", start=date(2021, 3, 31), n=24, eps=10.0):
    qe = pd.date_range(start, periods=n, freq="QE")
    return pd.DataFrame({"scrip_code": scrip, "quarter_end": [d.date() for d in qe],
                         "usable_from": [(d + pd.Timedelta(days=45)).date() for d in qe], "eps_basic": eps,
                         "revenue": 100.0, "net_profit": 10.0, "pbt": 12.0, "tax": -2.0})


def test_pe_history_uses_only_quarters_filed_by_each_date():
    q = quarters()
    idx = pd.bdate_range("2021-01-01", "2026-10-01")
    close = pd.Series(np.linspace(200, 400, len(idx)), index=idx)
    h = vl.pe_history(q, "1", close, date(2026, 9, 30))
    assert h.index.min() > pd.Timestamp("2022-01-01")                    # needs four filed quarters first
    first = h.iloc[0]
    assert first == pytest.approx(close[close.index <= h.index[0]].iloc[-1] / 40.0)      # TTM EPS 4 x 10


def test_flags_apply_and_stay_unknown_without_facts():
    fl = vl.flags(62.0, 30.0, {"pe": 22.0}, True, {"ratio": 1.6, "vol_3m_pct": 30, "vol_3y_pct": 19}, -0.30)
    assert all(f["applies"] for f in fl) and all("not tested" in f["status"] for f in fl)
    assert fl[0]["rule"] == "P/E above 50"
    none = vl.flags(None, None, None, None, {"ratio": None}, None)
    assert all(f["applies"] is None for f in none)
    calm = vl.flags(18.0, 34.0, {"pe": 22.0}, False, {"ratio": 1.0, "vol_3m_pct": 20, "vol_3y_pct": 20}, -0.05)
    assert not any(f["applies"] for f in calm)


def test_older_quarters_join_with_a_60_day_lag(monkeypatch, tmp_path):
    from pflab.fundamentals import pit
    old = pd.DataFrame({"scrip_code": "1", "quarter_end": [date(2020, 3, 31), date(2020, 6, 30)], "eps_basic": 5.0})
    monkeypatch.setattr(pit, "load_history", lambda scrip, root=None: old)
    cur = quarters(start=date(2020, 6, 30), n=2)                           # shares the 2020-06-30 quarter
    out = vl.with_older_quarters(cur, "1", tmp_path)
    assert sorted(out["quarter_end"]) == [date(2020, 3, 31), date(2020, 6, 30), date(2020, 9, 30)]
    r = out[out["quarter_end"] == date(2020, 3, 31)].iloc[0]
    assert r["usable_from"] == date(2020, 5, 30)
    assert out[out["quarter_end"] == date(2020, 6, 30)].iloc[0]["eps_basic"] == 10.0     # the store's row wins
