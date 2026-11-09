"""USD/INR for the sub-book, with the source stated on every rate.

Valuation and conversion at the start: the FBIL reference rate (the RBI's reference rate since 2018-07-10: RBI press release of 2018-07-04), when a row is entered in `fx_rates` as
pair `USDINR_FBIL` (from the RBI's reference-rate archive download); else the market USD/INR daily close (Yahoo `INR=X`, `data/global/FX_USDINR.parquet`, current to the last
session), labelled as a stand-in; else FRED's noon-New-York rate (`fx_rates` pair `USDINR`, about a week late). The first source with a rate no older than `max_age_days` wins.

Tax: the SBI telegraphic-transfer BUYING rate of the last day of the month before an event (Rule 115, Rule 206 from FY 2026-27). That rate is not in our data, so the same
series at that date stands in and the figure says ESTIMATE.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

FBIL_PAIR, FRED_PAIR = "USDINR_FBIL", "USDINR"
MARKET_FILE = ("global", "FX_USDINR.parquet")
LABELS = {
    "FBIL": "FBIL reference rate",
    "MARKET": "estimate: the market USD/INR close (Yahoo INR=X) stands in for the FBIL reference rate",
    "FRED": "estimate: FRED's noon New York rate (DEXINUS) stands in for the FBIL reference rate",
}


def _row(con, pair: str, day: date) -> Optional[tuple]:
    r = con.execute("SELECT rate, date FROM fx_rates WHERE pair=? AND date<=? AND rate > 0 ORDER BY date DESC LIMIT 1", [pair, day]).fetchone()
    return (float(r[0]), r[1]) if r else None


def _market(root, day: date) -> Optional[tuple]:
    if root is None:
        from pflab.data import data_dir
        root = data_dir()
    p = Path(root).joinpath(*MARKET_FILE)
    if not p.exists():
        return None
    df = pd.read_parquet(p, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[(df["date"] <= day) & (df["close"] > 0)]
    if df.empty:
        return None
    r = df.sort_values("date").iloc[-1]
    return float(r["close"]), r["date"]


def rate_for(con, day: date, root=None, max_age_days: int = 4) -> Optional[dict]:
    """{'rate', 'source', 'rate_day', 'age_days', 'label'} for `day`: the first source (FBIL, market close, FRED) with a rate at most `max_age_days` old; None when there is none."""
    cands = (("FBIL", lambda: _row(con, FBIL_PAIR, day)), ("MARKET", lambda: _market(root, day)), ("FRED", lambda: _row(con, FRED_PAIR, day)))
    for src, get in cands:
        got = get()
        if got is None:
            continue
        age = (day - got[1]).days
        if age <= max_age_days:
            return {"rate": got[0], "source": src, "rate_day": got[1], "age_days": age, "label": LABELS[src]}
    return None


def tax_date(event: date) -> date:
    """The last day of the month BEFORE the month of `event` (the date whose SBI TT buying rate converts a sale, a purchase or a dividend)."""
    return date.fromordinal(event.replace(day=1).toordinal() - 1)


def tax_rate(con, event: date, root=None) -> Optional[dict]:
    """The rupees per dollar for the Indian tax on an event: the rate of the month-end before it (an ESTIMATE of the SBI TT buying rate)."""
    d = tax_date(event)
    got = rate_for(con, d, root, max_age_days=10)
    if got is None:
        return None
    return {**got, "tax_date": d, "label": "estimate: " + got["label"].replace("estimate: ", "") + f", at {d} (the month-end before {event}), standing in for the SBI TT buying rate (rule 115 / rule 206)"}
