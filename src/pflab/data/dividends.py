"""Dividends per share on ex-date (charter §8, sprint step 5).

Contract
--------
fetch(symbols_by_isin: dict[str, str], root) -> writes data/dividends/dividends.parquet
    columns: isin, ex_date, dividend_per_share

Two sources, both public feeds as §9 requires:

`from_feed` (default) reads the NSE corporate-actions feed already collected
for the §15 adjustment factors. It is preferred because it reports the amount
**actually paid per share at the time**, keyed by ISIN, and covers names that
later delisted.

`fetch` is the sprint's yfinance path, kept as an independent cross-check.
yfinance reports dividends on the CURRENT share basis: Widget Co paid Rs 29.50
on 2015-06-15, and yfinance returns 7.375, having divided by the 4x of the
two later 2:1 events. Feeding that to the engine would understate §8 dividend
income, because the engine holds the share count of the day. `unadjust`
reverses it using the same factors the panel uses.

NSE writes the amount two ways:
    "Dividend - Rs 5/- Per Share"   an absolute amount
    "Dividend-25%"                  a percentage of FACE VALUE (mostly pre-2010)
Both are parsed; the second needs the feed's `faceVal`.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from pflab.data import data_dir

COLUMNS = ["isin", "ex_date", "dividend_per_share"]

# "Rs 5/- Per Share", "Re 1 Per Share", "Rs 29.50/- Per Share"
_AMOUNT = re.compile(r"(?:rs|re)\.?\s*([\d]+(?:\.\d+)?)\s*/?-?\s*per\s*share", re.I)
# "Dividend-25%", "Dividend - 120 %", "Agm/Dividend-40%"
_PERCENT = re.compile(r"dividend\s*[-–:]?\s*([\d]+(?:\.\d+)?)\s*%", re.I)
# A face-value split reads "From Rs 10/- Per Share To Rs 2/- Per Share", which
# would otherwise look like two dividends. Strip it before matching amounts.
_SPLIT_CLAUSE = re.compile(
    r"from\s*(?:rs|re)\.?\s*[\d.]+\s*/?-?\s*(?:per\s*(?:share)?)?\s*"
    r"to\s*(?:rs|re)\.?\s*[\d.]+\s*/?-?\s*(?:per\s*share)?", re.I)
_IS_DIVIDEND = re.compile(r"dividend", re.I)


def parse_dividend(subject: str, face_value: Optional[float] = None) -> Optional[float]:
    """Rupees per share going ex on this row, or None.

    Several dividends can share an ex-date ("Interim Dividend Rs 2 / Special
    Dividend Rs 5"); they are summed, since the holder receives both.
    """
    if not subject or not _IS_DIVIDEND.search(subject):
        return None
    text = _SPLIT_CLAUSE.sub(" ", subject.replace("\xa0", " "))
    amounts = [float(x) for x in _AMOUNT.findall(text)]
    if amounts:
        return sum(amounts)
    pct = _PERCENT.findall(text)
    if pct and face_value:
        try:
            fv = float(face_value)
        except (TypeError, ValueError):
            return None
        if fv > 0:
            return sum(float(p) for p in pct) / 100.0 * fv
    return None


def from_feed(root: Optional[Path] = None, raw: Optional[pd.DataFrame] = None,
              series: tuple = ("EQ",)) -> pd.DataFrame:
    """(isin, ex_date, dividend_per_share) from the NSE corporate-actions feed."""
    from pflab.data import nse_corporate_actions as nca
    df = raw if raw is not None else nca.load_raw(root)
    if series:
        df = df[df["series"].isin(series)]
    df = df[df["isin"].notna() & df["isin"].ne("-")]
    recs = []
    for r in df.itertuples(index=False):
        amt = parse_dividend(r.subject, getattr(r, "faceVal", None))
        if amt and amt > 0:
            recs.append({"isin": r.isin, "ex_date": r.ex_date,
                         "dividend_per_share": amt})
    if not recs:
        return pd.DataFrame(columns=COLUMNS)
    out = pd.DataFrame(recs)
    # One ex-date can appear twice when NSE revises a purpose; take the larger
    # rather than double-counting the payment.
    out = out.groupby(["isin", "ex_date"], as_index=False)["dividend_per_share"].max()
    return out.sort_values(["isin", "ex_date"]).reset_index(drop=True)[COLUMNS]


# -- yfinance cross-check ----------------------------------------------
def fetch(symbols_by_isin: dict, root: Optional[Path] = None,
          sleep: float = 0.0, limit: Optional[int] = None) -> pd.DataFrame:
    """yfinance dividends for still-listed names (sprint step 5).

    Returns the CURRENT-basis amounts as yfinance reports them; pass the
    result through `unadjust` before comparing with the feed or using it.
    """
    import yfinance as yf
    recs = []
    items = list(symbols_by_isin.items())[:limit]
    for i, (isin, symbol) in enumerate(items):
        try:
            d = yf.Ticker(f"{symbol}.NS").dividends
        except Exception:
            continue
        for ts, amt in d.items():
            if amt and amt > 0:
                recs.append({"isin": isin, "ex_date": ts.date(),
                             "dividend_per_share": float(amt)})
        if sleep:
            import time
            time.sleep(sleep)
    return (pd.DataFrame(recs, columns=COLUMNS) if recs
            else pd.DataFrame(columns=COLUMNS))


def unadjust(div: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """Put current-basis dividends back on the share basis of their ex-date.

    Divides by every factor with ex_date >= the dividend's ex_date -- the
    inclusive bound matters, because a bonus and its dividend routinely share
    an ex-date (Widget Co, 2015-06-15).
    """
    if div.empty or factors is None or factors.empty:
        return div.copy()
    f = factors.copy()
    f["ex_date"] = pd.to_datetime(f["ex_date"]).dt.date
    by = {i: list(zip(g["ex_date"], g["factor"])) for i, g in f.groupby("isin")}
    out = div.copy()
    vals = []
    for r in out.itertuples(index=False):
        cum = 1.0
        for ex, fac in by.get(r.isin, ()):
            if ex >= r.ex_date:
                cum *= fac
        vals.append(r.dividend_per_share / cum if cum else r.dividend_per_share)
    out["dividend_per_share"] = vals
    return out


def listed_symbols(root: Optional[Path] = None, sessions: int = 20) -> dict:
    """isin -> current symbol, for names that traded in the last `sessions`."""
    from pflab.data import bhavcopy, calendar as C
    root = root or data_dir()
    cal = C.from_bhavcopy(root)
    recent = bhavcopy.load(cal[-sessions], cal[-1], root, series=("EQ",))
    recent = recent.dropna(subset=["isin"]).sort_values("date")
    return dict(zip(recent["isin"], recent["symbol"]))


def write(div: pd.DataFrame, root: Optional[Path] = None) -> Path:
    root = root or data_dir()
    p = root / "dividends" / "dividends.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    div.to_parquet(p, index=False)
    return p


def load(root: Optional[Path] = None) -> pd.DataFrame:
    root = root or data_dir()
    return pd.read_parquet(root / "dividends" / "dividends.parquet")


def drop_collisions(div: pd.DataFrame, dropped) -> pd.DataFrame:
    """Remove dividend rows superseded by a PREVCLOSE factor (§9, 2026-09-16).

    `dropped` is the (isin, ex_date) list from
    `nse_corporate_actions.resolve_dividend_collisions`. On those dates the
    cash is already inside the price adjustment.
    """
    if div.empty or not len(dropped):
        return div
    keys = {(i, str(d)) for i, d in dropped}
    mask = [(i, str(d)) not in keys
            for i, d in zip(div["isin"], div["ex_date"])]
    return div[mask].reset_index(drop=True)
