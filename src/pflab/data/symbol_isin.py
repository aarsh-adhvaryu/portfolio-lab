"""Symbol -> ISIN map for pre-2012 bhavcopy rows (Phase 1 sprint step 4).

NSE added the ISIN column to the bhavcopy between 2011-06 and 2011-10. Earlier
rows carry only a symbol, and symbols are reused: 535 of the ~4,000 symbols in
the ISIN era point at more than one ISIN over time. So the map is date-ranged,
per CLAUDE.md convention 8 -- never join on symbol without a date.

Built from two sources:
  * the ISIN era of the bhavcopy itself, read backwards
  * NSE's symbol-change file, to follow renames forward to a symbol that
    survived into the ISIN era

What cannot be recovered: a company that delisted before ~Oct 2011 has no ISIN
anywhere in the bhavcopy. There were 251 such symbols in 2004-2011, and they
are exactly the names that went to zero -- see `unmapped_report`.
"""
from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir
from pflab.data.bhavcopy import HEADERS

SYMBOL_CHANGE_URL = "https://archives.nseindia.com/content/equities/symbolchange.csv"
MAP_COLUMNS = ["symbol", "isin", "valid_from", "valid_to"]
# Sprint step 4: stop and show the investor if a year loses more than this share.
UNMAPPED_YEAR_TOLERANCE = 0.02

FAR_PAST = date(1990, 1, 1)
FAR_FUTURE = date(2999, 12, 31)


def fetch_symbol_changes(root: Optional[Path] = None, refresh: bool = False) -> pd.DataFrame:
    """NSE's symbol-change history: company, old, new, date. Cached on disk."""
    root = root or data_dir()
    cache = root / "raw" / "symbolchange.csv"
    if refresh or not cache.exists():
        r = requests.get(SYMBOL_CHANGE_URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(r.content)
    txt = cache.read_bytes().decode("latin-1")
    df = pd.read_csv(io.StringIO(txt), header=None,
                     names=["company", "old", "new", "date"], dtype=str)
    for c in ("old", "new"):
        df[c] = df[c].str.strip()
    df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce").dt.date
    return df.dropna(subset=["old", "new"])


def _rename_chain(changes: pd.DataFrame) -> dict:
    """NSE's renames, plus the hand-verified pre-ISIN ones it omits (§9)."""
    chain = dict(zip(changes["old"], changes["new"]))
    # The verified list wins: NSE's file simply has no row for these.
    chain.update(VERIFIED_STITCHES)
    return chain


def build(panel: pd.DataFrame, changes: Optional[pd.DataFrame] = None,
          root: Optional[Path] = None) -> pd.DataFrame:
    """The date-ranged map, from a panel that spans the ISIN era.

    Rows are (symbol, isin, valid_from, valid_to) with inclusive bounds. The
    earliest ISIN a symbol held has its valid_from opened backwards, because
    pre-2012 rows precede the ISIN era entirely.
    """
    if changes is None:
        changes = fetch_symbol_changes(root)
    known = panel.dropna(subset=["isin"])
    if known.empty:
        raise ValueError("panel has no rows carrying an ISIN")

    seen = (known.groupby(["symbol", "isin"])["date"]
                 .agg(["min", "max"]).reset_index()
                 .rename(columns={"min": "valid_from", "max": "valid_to"})
                 .sort_values(["symbol", "valid_from"], kind="mergesort"))

    rows = []
    for sym, g in seen.groupby("symbol", sort=False):
        g = g.sort_values("valid_from", kind="mergesort")
        starts = list(g["valid_from"])
        for i, r in enumerate(g.itertuples(index=False)):
            # first ISIN for this symbol reaches back before the ISIN era;
            # a later one takes over the day it first appears.
            vf = FAR_PAST if i == 0 else r.valid_from
            vt = (starts[i + 1] - timedelta(days=1)) \
                if i + 1 < len(starts) else FAR_FUTURE
            rows.append({"symbol": sym, "isin": r.isin,
                         "valid_from": vf, "valid_to": max(vt, r.valid_to)})

    direct = pd.DataFrame(rows, columns=MAP_COLUMNS)

    # Renamed symbols: follow the chain forward to one that reached the ISIN
    # era, and let the old symbol claim that ISIN up to the rename date.
    fwd = _rename_chain(changes)
    first_isin = {s: g.iloc[0]["isin"]
                  for s, g in direct.sort_values("valid_from").groupby("symbol")}
    alias = []
    for old in set(fwd) - set(first_isin):
        cur, hops, guard = old, 0, set()
        while cur in fwd and cur not in first_isin and cur not in guard and hops < 8:
            guard.add(cur)
            cur = fwd[cur]
            hops += 1
        if cur in first_isin:
            alias.append({"symbol": old, "isin": first_isin[cur],
                          "valid_from": FAR_PAST, "valid_to": FAR_FUTURE})
    out = pd.concat([direct, pd.DataFrame(alias, columns=MAP_COLUMNS)],
                    ignore_index=True) if alias else direct
    return (out.sort_values(["symbol", "valid_from"], kind="mergesort")
               .reset_index(drop=True)[MAP_COLUMNS])


def apply_map(panel: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    """Fill the ISIN of rows that lack one, by symbol and date.

    Rows that stay unmapped keep a null ISIN; the caller decides whether to
    drop them (see `unmapped_report`).
    """
    out = panel.copy()
    miss = out["isin"].isna()
    if not miss.any():
        return out
    need = out.loc[miss, ["symbol", "date"]].reset_index()
    j = need.merge(mapping, on="symbol", how="left")
    j = j[(j["valid_from"] <= j["date"]) & (j["date"] <= j["valid_to"])]
    # A clean map has one candidate per (row); keep the first if ranges overlap.
    j = j.drop_duplicates("index", keep="first").set_index("index")["isin"]
    out.loc[j.index, "isin"] = j
    return out


# Charter §9 / §15, 2026-09-16. Pre-ISIN renames that symbolchange.csv does
# not carry, stitched ONLY where the corporate-actions feed shows the same
# company name on both sides. A merger or scheme of arrangement is not a
# rename and follows the delisting rule instead.
#
# Rejected, deliberately:
#   JINDALIRON -> JINDALSAW   merger, not a rename
#   TV-18      -> TV18BRDCST  merger, not a rename
#   TECHNOELEC -> TECHNOFAB   different companies; the prefix+contiguity
#                             heuristic proposed it, which is why this list
#                             is verified by hand rather than generated.
VERIFIED_STITCHES = {
    "GESHIPPING": "GESHIP",       # Great Eastern Shipping, 2006
    "ESSARSHIP": "ESSARPORTS",    # Essar Shipping Ports & Logistics, 2011
}

SYNTHETIC_PREFIX = "NSESYM:"


def synthetic_key(panel: pd.DataFrame) -> pd.Series:
    """A stable stand-in ISIN for rows the map cannot resolve.

    Every unresolvable symbol delisted before the ISIN era, so none of them
    collides with a real ISIN and none is reused later. Keeping them under a
    synthetic key preserves charter principle 6 -- survivorship is a data
    error, and these are precisely the names that went to zero. Dropping them
    instead is the charter section 9 default.
    """
    miss = panel["isin"].isna()
    return panel["symbol"].where(miss).radd(SYNTHETIC_PREFIX)


def is_synthetic(isin: pd.Series) -> pd.Series:
    return isin.astype("string").str.startswith(SYNTHETIC_PREFIX).fillna(False)


def unmapped_report(panel: pd.DataFrame) -> dict:
    """Per-year share of rows still lacking an ISIN, and the stop decision."""
    d = pd.to_datetime(panel["date"]).dt.date
    year = pd.Series([x.year for x in d], index=panel.index)
    miss = panel["isin"].isna()
    by_year = {}
    for y, g in miss.groupby(year):
        by_year[int(y)] = {"rows": int(len(g)), "unmapped": int(g.sum()),
                           "share": float(g.mean())}
    breaches = {y: v for y, v in by_year.items()
                if v["share"] > UNMAPPED_YEAR_TOLERANCE}
    return {
        "rows": int(len(panel)),
        "unmapped": int(miss.sum()),
        "share": float(miss.mean()) if len(panel) else 0.0,
        "by_year": by_year,
        "tolerance": UNMAPPED_YEAR_TOLERANCE,
        "breaches": breaches,
        "symbols": sorted(panel.loc[miss, "symbol"].dropna().unique().tolist()),
    }


def write(mapping: pd.DataFrame, root: Optional[Path] = None) -> Path:
    root = root or data_dir()
    p = root / "panel" / "symbol_isin_map.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    mapping.to_parquet(p, index=False)
    return p


def load(root: Optional[Path] = None) -> pd.DataFrame:
    root = root or data_dir()
    return pd.read_parquet(root / "panel" / "symbol_isin_map.parquet")
