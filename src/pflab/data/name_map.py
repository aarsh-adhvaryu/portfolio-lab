"""Company name -> (symbol, ISIN), for sources that publish names only.

Charter E1b §3 as amended 2026-09-17. NSE's index constituent-change notices
from 2006-2009 name companies and nothing else ("Container Corporation of
India Ltd."), so there is no symbol to key on and CLAUDE.md 8's rule -- ISIN
is the security key, never join on symbol without a date -- cannot be applied
directly. This module is the bridge, and it is deliberately a separate,
auditable table rather than a lookup buried in a parser.

Three sources, in descending order of trust:

1. CORPORATE ACTIONS feed -- carries company name, symbol AND ISIN on the
   same row, with a date. 42k rows from 2004. This is the only source that
   ties all three together at a point in time, so it is preferred wherever it
   has an answer.
2. EQUITY MASTER (`EQUITY_L.csv`) -- name, symbol, ISIN for every currently
   listed name. Authoritative but present-tense: a company delisted in 2011
   is simply absent, which is exactly the survivorship hole principle 6 warns
   about, so it never overrides source 1.
3. CURRENT INDEX LISTS -- name and ISIN for today's Nifty 200 / 500 /
   Momentum 30. Smallest and also present-tense; it is here because index
   notices use the same house style for company names as the index lists do.

Normalisation
-------------
`normalise` strips the corporate-form suffix (Ltd / Limited / Pvt / Corp),
punctuation, a leading "The", and case, and maps "&" to "and". It is
deliberately conservative: it never drops a word that could distinguish two
companies (no stripping of "India", "Industries" or "Corporation" as a whole
word), because a false match silently puts the wrong security in the
portfolio while a miss merely lands in the unresolved list for the investor.

Ambiguity is never guessed. A normalised name that resolves to more than one
ISIN is returned as unresolved with its candidates attached, the same way
`symbol_isin.VERIFIED_STITCHES` requires a human to confirm a rename.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from pflab.data import data_dir

EQUITY_MASTER_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

COLUMNS = ["norm_name", "name", "symbol", "isin", "source", "first_seen", "last_seen"]

# Corporate-form suffixes only. Anything that could distinguish two companies
# stays: "India", "Industries", "Corporation", "Enterprises" are all kept.
_SUFFIXES = r"(?:ltd|limited|pvt|private|plc|inc|corp|corpn|incorporated)"
_SUFFIX_RE = re.compile(r"\b" + _SUFFIXES + r"\b\.?", re.I)
# A period or apostrophe inside a name is dropped, not turned into a space:
# the releases write "J.B. Chemicals" where the equity master writes "JB
# Chemicals", and a space there makes the two names never match. Every other
# punctuation mark becomes a space, because it separates real words.
_DROP_RE = re.compile(r"[.'’]")
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_THE_RE = re.compile(r"^the\b", re.I)


def normalise(name: str) -> str:
    """A comparison key for a company name. Empty string for anything unusable."""
    if not isinstance(name, str):
        return ""
    s = name.strip()
    if not s:
        return ""
    s = _THE_RE.sub(" ", s)
    s = s.replace("&", " and ")
    s = _SUFFIX_RE.sub(" ", s)
    s = s.lower()
    s = _DROP_RE.sub("", s)
    s = _PUNCT_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


# -- sources -----------------------------------------------------------
def from_corporate_actions(raw: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Source 1: name + symbol + ISIN + date, all on one row."""
    if raw is None:
        from pflab.data import nse_corporate_actions as ca
        raw = ca.load_raw()
    d = raw[["comp", "symbol", "isin", "ex_date"]].copy()
    d.columns = ["name", "symbol", "isin", "seen"]
    d["seen"] = pd.to_datetime(d["seen"], errors="coerce").dt.date
    d["source"] = "corporate_actions"
    return d


def from_equity_master(root: Optional[Path] = None,
                       refresh: bool = False) -> pd.DataFrame:
    """Source 2: today's listed universe. Cached on disk."""
    import io

    import requests

    from pflab.data.bhavcopy import HEADERS
    root = root or data_dir()
    cache = root / "index_membership" / "raw" / "EQUITY_L.csv"
    if refresh or not cache.exists():
        r = requests.get(EQUITY_MASTER_URL, headers=HEADERS, timeout=90)
        r.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(r.content)
    df = pd.read_csv(io.BytesIO(cache.read_bytes()))
    df.columns = [c.strip() for c in df.columns]
    d = df.rename(columns={"NAME OF COMPANY": "name", "SYMBOL": "symbol",
                           "ISIN NUMBER": "isin", "DATE OF LISTING": "seen"})
    d = d[["name", "symbol", "isin", "seen"]].copy()
    d["seen"] = pd.to_datetime(d["seen"], errors="coerce", format="mixed").dt.date
    d["source"] = "equity_master"
    return d


def from_index_lists(indices=None) -> pd.DataFrame:
    """Source 3: name + ISIN from the current constituent lists (no symbol
    date, so `seen` is left empty)."""
    from pflab.data import index_membership as im
    out = []
    for key in (indices or list(im.INDICES)):
        try:
            df = im.fetch_current(key)
        except Exception:
            continue
        d = df.rename(columns={"company": "name"})[["name", "symbol", "isin"]].copy()
        d["seen"] = pd.NaT
        d["source"] = f"index_list:{key}"
        out.append(d)
    if not out:
        return pd.DataFrame(columns=["name", "symbol", "isin", "seen", "source"])
    return pd.concat(out, ignore_index=True)


# -- assembly ----------------------------------------------------------
SOURCE_RANK = {"corporate_actions": 0, "equity_master": 1}


def build(raw_ca: Optional[pd.DataFrame] = None, root: Optional[Path] = None,
          refresh: bool = False) -> pd.DataFrame:
    """One row per (norm_name, isin), with the window it was seen over."""
    parts = [from_corporate_actions(raw_ca)]
    try:
        parts.append(from_equity_master(root, refresh))
    except Exception:
        pass                     # a network failure must not silently empty the map
    parts.append(from_index_lists())
    d = pd.concat(parts, ignore_index=True)

    d["norm_name"] = d["name"].map(normalise)
    d = d[(d["norm_name"] != "") & d["isin"].notna()]
    d = d[d["isin"].astype(str).str.match(r"^IN[EF0-9]")]
    # the three sources carry `seen` as date, string and NaT; min/max over a
    # mixed object column raises, so normalise the dtype before grouping
    d["seen"] = pd.to_datetime(d["seen"], errors="coerce")

    d["rank"] = d["source"].map(lambda s: SOURCE_RANK.get(s, 2))
    d = d.sort_values(["norm_name", "isin", "rank"])
    g = d.groupby(["norm_name", "isin"], sort=False)
    out = pd.DataFrame({
        "name": g["name"].first(),
        "symbol": g["symbol"].first(),
        "source": g["source"].first(),
        "first_seen": g["seen"].min(),
        "last_seen": g["seen"].max(),
    }).reset_index()
    for c in ("first_seen", "last_seen"):
        out[c] = out[c].dt.date
    return out[COLUMNS].sort_values(["norm_name", "isin"]).reset_index(drop=True)


def resolve(name: str, table: pd.DataFrame, on: Optional[date] = None,
            symbol_isin: Optional[pd.DataFrame] = None) -> dict:
    """One company name -> {"isin", "symbol", "reason", "candidates"}.

    Two steps, in this order, and the order is the point:

      name -> SYMBOL      here, by normalised name
      symbol + date -> ISIN   by `symbol_isin`, the existing date-ranged map

    Going straight from name to ISIN looks simpler and is wrong. A split or
    consolidation issues a new ISIN for the same company, so 579 of 3,324
    names in the map carry more than one ISIN -- but only 114 carry more than
    one SYMBOL. Resolving to the symbol first collapses four fifths of the
    ambiguity, and handing the date to `symbol_isin` is exactly CLAUDE.md 8:
    never join on symbol without a date.

    `isin` is None whenever the answer is not unique. Ambiguity is reported,
    never broken by a coin flip: putting the wrong security in the portfolio
    is silent, while an unresolved name lands in a list the investor reviews.
    """
    key = normalise(name)
    if not key:
        return {"isin": None, "symbol": None, "reason": "unparseable name",
                "candidates": []}
    hits = table[table["norm_name"] == key]
    if hits.empty:
        return {"isin": None, "symbol": None, "reason": "no match",
                "candidates": []}

    symbols = sorted(set(hits["symbol"].dropna()))
    if len(symbols) > 1:
        return {"isin": None, "symbol": None, "reason": "ambiguous symbol",
                "candidates": hits[["isin", "symbol", "name"]].to_dict("records")}
    symbol = symbols[0] if symbols else None

    isins = sorted(set(hits["isin"].dropna()))
    if len(isins) == 1:
        return {"isin": isins[0], "symbol": symbol, "reason": "exact",
                "candidates": []}

    # One company, several ISINs. Only the date-ranged map can say which one
    # was live on the change date.
    if symbol and on is not None and symbol_isin is not None and len(symbol_isin):
        m = symbol_isin[(symbol_isin["symbol"] == symbol)
                        & (symbol_isin["valid_from"] <= on)
                        & (on <= symbol_isin["valid_to"])]
        live = sorted(set(m["isin"]) & set(isins)) or sorted(set(m["isin"]))
        if len(live) == 1:
            return {"isin": live[0], "symbol": symbol,
                    "reason": "date-disambiguated", "candidates": []}
    return {"isin": None, "symbol": symbol, "reason": "ambiguous isin",
            "candidates": hits[["isin", "symbol", "name"]].to_dict("records")}


def write(table: pd.DataFrame, root: Optional[Path] = None) -> Path:
    root = root or data_dir()
    p = root / "index_membership" / "name_map.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(p, index=False)
    return p


def load(root: Optional[Path] = None) -> pd.DataFrame:
    root = root or data_dir()
    return pd.read_parquet(root / "index_membership" / "name_map.parquet")
