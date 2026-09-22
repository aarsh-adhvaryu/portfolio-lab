"""Instrument typing (charter §2, §15 2026-09-16).

ETFs, InvITs and REITs are kept in the panel but excluded from E1's universe.
Two reasons, neither of them purity:

  * A gold ETF would have ranked top-25 on 12-1 momentum in 2020 and again in
    2024-25. E1 beating Nifty 500 TRI on that is an asset-allocation result,
    not a verdict on the stock rule E1 exists to test.
  * The §8 tax engine is equity-only (20/12.5, STT 0.1% each side). Gold and
    silver ETFs are not equity for tax, and REIT/InvIT distributions split
    into interest, dividend and return of capital. Every after-tax number for
    such a position would be silently wrong.

How each type is identified, in order of reliability:

  REIT   series RR   |  InvIT  series IV
      NSE gives these their own series, so charter §2's existing "series EQ
      only" already excluded them. They were never in the universe.

  ETF    series EQ and ISIN starting INF
      Indian ETFs are mutual-fund schemes, so they carry an INF ISIN rather
      than an INE one. This is exact and needs no name list: on 2026-09-16 it
      typed all 348 ETFs including ones a name rule would miss entirely
      (ICICIB22, NIFTY1, PSUBANK, MOMENTUM30, TOP100CASE).

A NAME PATTERN IS NOT USED, deliberately. Matching BEES/ETF/IETF/LIQUID/GOLD/
SILVER against the symbol wrongly catches six real companies trading on
2026-09-16 -- SKYGOLD, GOLDIAM, SHANTIGOLD, SILVERTUC, DECNGOLD and
JETFREIGHT -- which would drop genuine stocks out of the universe.

The pre-2011 rows carry no ISIN, so an ETF there cannot be typed by prefix.
That is immaterial in practice: the first Indian ETF (NIFTYBEES, 2002) and its
few peers are far below the §2 top-500 traded-value cut in that era, and
`unknown_isin_rows` reports the exposure so it stays visible in the manifest.
"""
from __future__ import annotations

import pandas as pd

STK, ETF, REIT, INVIT = "STK", "ETF", "REIT", "INVIT"

# Series NSE gives to unit-based instruments.
REIT_SERIES = "RR"
INVIT_SERIES = "IV"
# Series carried in the panel: equities plus the unit instruments the
# defensive-sleeve experiment will want.
PANEL_SERIES = ("EQ", REIT_SERIES, INVIT_SERIES)
# E1's universe (§2).
UNIVERSE_TYPES = (STK,)

ETF_ISIN_PREFIX = "INF"


def classify(series: pd.Series, isin: pd.Series) -> pd.Series:
    """STK / ETF / REIT / INVIT, one per row."""
    s = series.astype("string").str.strip()
    i = isin.astype("string").str.strip()
    out = pd.Series(STK, index=series.index, dtype="object")
    out[i.str.startswith(ETF_ISIN_PREFIX).fillna(False)] = ETF
    out[s.eq(REIT_SERIES).fillna(False)] = REIT
    out[s.eq(INVIT_SERIES).fillna(False)] = INVIT
    return out


def unknown_isin_rows(panel: pd.DataFrame) -> int:
    """Rows typed STK only because no ISIN was available to check."""
    if "isin" not in panel.columns:
        return 0
    i = panel["isin"].astype("string")
    return int((i.isna() | ~i.str.startswith(("INE", "INF", "IN9"), na=False)).sum())


def exclusion_list(panel: pd.DataFrame) -> pd.DataFrame:
    """The excluded instruments, for the run manifest (§15)."""
    if "instrument_type" not in panel.columns:
        raise ValueError("panel has no instrument_type column")
    ex = panel[~panel["instrument_type"].isin(UNIVERSE_TYPES)]
    if ex.empty:
        return pd.DataFrame(columns=["isin", "symbol", "instrument_type",
                                     "first_date", "last_date", "sessions"])
    return (ex.groupby(["isin", "instrument_type"])
              .agg(symbol=("symbol", "last"), first_date=("date", "min"),
                   last_date=("date", "max"), sessions=("date", "size"))
              .reset_index()
              .sort_values(["instrument_type", "symbol"])
              .reset_index(drop=True))
