"""India VIX, current to the last session (S79b agent D).

The history and its NSE/Yahoo stitching live in `data.india_vix` (file `data/indices/INDIA_VIX.parquet`, NSE's
`api/historicalOR/vixhistory`). This module is the safe top-up: it tries NSE through `india_vix.update`, and when NSE refuses
(it does at times) takes only the missing recent days from Yahoo `^INDIAVIX`, marking the row's `source`.

Point-in-time: NSE publishes the close of session D at the end of D; the row dated D is knowable at D's close, never before.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir, india_vix


def load(root: Optional[Path] = None, upto: Optional[date] = None) -> pd.DataFrame:
    df = pd.read_parquet(Path(root or data_dir()) / "indices" / "INDIA_VIX.parquet")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    if upto is not None:
        df = df[df["date"] <= upto]
    return df.sort_values("date").reset_index(drop=True)


def _yahoo_recent() -> pd.DataFrame:
    j = requests.get(india_vix.YAHOO, params={"range": "1mo", "interval": "1d"}, headers={"User-Agent": india_vix.UA}, timeout=40).json()
    res = j["chart"]["result"][0]
    from datetime import datetime, timedelta, timezone
    off = timedelta(seconds=res["meta"].get("gmtoffset", 0))
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"date": [(datetime.fromtimestamp(t, timezone.utc) + off).date() for t in res["timestamp"]],
                       "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"]}).dropna(subset=["close"])
    df["source"] = "yahoo"
    return df


def refresh(root: Optional[Path] = None, today: Optional[date] = None) -> dict:
    """NSE first; on failure append the days after the stored last date from Yahoo. Never writes a future date or a duplicate."""
    root = Path(root or data_dir())
    today = today or date.today()
    try:
        r = india_vix.update(root=root)
        return {"via": "nse", **r}
    except Exception as e:
        err = repr(e)[:120]
    old = load(root)
    new = _yahoo_recent()
    new = new[(new["date"] > old["date"].max()) & (new["date"] <= today)]
    if len(new):
        df = pd.concat([old, new], ignore_index=True).drop_duplicates("date", keep="last").sort_values("date")
        df.to_parquet(root / "indices" / "INDIA_VIX.parquet", index=False)
    return {"via": "yahoo", "nse_error": err, "added": int(len(new)), "last": str(max(old["date"].max(), *(new["date"] if len(new) else [old["date"].max()])))}
