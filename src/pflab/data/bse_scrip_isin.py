"""BSE scrip code -> ISIN map (E2-A §5, E2-D §4).

ISIN is the security key (CLAUDE.md rule 8), but every BSE endpoint is
keyed on the numeric scrip code, so nothing collected from BSE can enter
the panel without this map.

**The announcement feed is the primary source of the universe.** It spans
2010-01-01 onward and names every company that filed anything in that
window, including the ones since delisted. The equity master
(`ListofScripData`) is used only to resolve and verify an ISIN for those
codes, never to decide who existed: the master is a snapshot of today, so
taking its scrip list as the universe would quietly drop every company
that died between 2010 and now and put survivorship on the primary path.
The master does serve delisted and suspended scrips (10,895 rows over all
statuses as of 2026-09-23, against 5,045 active), which is why it can
resolve the feed's codes at all.

**The map is date-ranged**, because an ISIN is not stable. A face-value
split issues a new one: KOTAKBANK moved INE237A01028 -> INE237A01036 on
2026-01-14, DRREDDY INE089A01023 -> INE089A01031 on 2024-10-28, CANBK
INE476A01014 -> INE476A01022 on 2024-05-15. The BSE master carries only
today's ISIN, so a flat scrip_code -> isin join silently loses every such
company for all of its history: it cost 1,445 of the panel's 4,380 ISINs
(18.5% of panel rows, including Kotak Mahindra Bank, Dr Reddy's, Canara
Bank and Info Edge) before this was fixed. Each scrip code therefore emits
one row per ISIN that the company's panel symbol ever carried, with the
date range that ISIN was valid, per CLAUDE.md rule 8.

Schema (data/bse_scrip_isin/map.parquet):
  scrip_code, isin, valid_from, valid_to, company, status, first_seen,
  last_seen, n_announcements, source, in_panel, isin_role
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir
from pflab.data.bse_announcements import HEADERS

MASTER_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
STATUSES = ("Active", "Suspended", "Delisted")
COLUMNS = ["scrip_code", "isin", "valid_from", "valid_to", "company", "status",
           "first_seen", "last_seen", "n_announcements", "source", "in_panel",
           "isin_role"]
FAR_PAST = pd.Timestamp("1990-01-01")
FAR_FUTURE = pd.Timestamp("2999-12-31")


class MasterIncomplete(RuntimeError):
    """The equity master answered with too few rows to be the real list.

    Same discipline as bse_announcements.IncompleteDay: a throttled or
    truncated answer must never be written as data. The master carried
    5,045 active scrips on 2026-09-23; an answer with a few hundred rows
    is a failure, not a shrinking exchange.
    """


def fetch_master(session: Optional[requests.Session] = None, timeout: int = 90,
                 min_rows: int = 500) -> pd.DataFrame:
    """Every equity scrip BSE knows, over all three statuses."""
    s = session or requests.Session()
    frames = []
    for status in STATUSES:
        params = {"Group": "", "Scripcode": "", "industry": "",
                  "segment": "Equity", "status": status}
        r = s.get(MASTER_URL, params=params, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or len(rows) < min_rows:
            raise MasterIncomplete(
                f"status={status}: {len(rows) if isinstance(rows, list) else '?'} rows")
        df = pd.DataFrame(rows)
        frames.append(df.assign(_status=status))
    m = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({
        "scrip_code": m["SCRIP_CD"].astype(str).str.strip(),
        "isin": m["ISIN_NUMBER"].fillna("").astype(str).str.strip(),
        "master_name": m["Scrip_Name"].fillna("").astype(str).str.strip(),
        "status": m["_status"],
    })
    # a scrip code can repeat across statuses; prefer the row that carries an ISIN
    out["_has"] = (out["isin"] != "").astype(int)
    out = (out.sort_values(["scrip_code", "_has"], ascending=[True, False])
              .drop_duplicates("scrip_code").drop(columns="_has")
              .reset_index(drop=True))
    return out


def scrip_codes_from_announcements(root: Optional[Path] = None) -> pd.DataFrame:
    """The universe: every scrip code that filed an announcement since 2010.

    This is what makes the map survivorship-free. Counts and first/last
    dates come along so an unresolved code can be judged by how much it
    actually filed.
    """
    root = root or data_dir()
    base = root / "bse_announcements"
    files = sorted(base.glob("*/*.parquet"))
    if not files:
        raise FileNotFoundError(f"no announcement day files under {base}")
    parts = []
    for f in files:
        df = pd.read_parquet(f, columns=["scrip_code", "company", "dissem_dt"])
        if len(df):
            parts.append(df)
    a = pd.concat(parts, ignore_index=True)
    a = a[a["scrip_code"].notna()]
    a["scrip_code"] = a["scrip_code"].astype(str).str.strip()
    a = a[a["scrip_code"] != ""]
    a["dissem_dt"] = pd.to_datetime(a["dissem_dt"], errors="coerce")
    g = a.groupby("scrip_code").agg(
        company=("company", lambda s: s.dropna().iloc[-1] if s.notna().any() else ""),
        first_seen=("dissem_dt", "min"),
        last_seen=("dissem_dt", "max"),
        n_announcements=("scrip_code", "size"),
    ).reset_index()
    return g


def _panel_isin_history(root: Path) -> pd.DataFrame:
    """Every (isin, symbol) the panel carries, with the dates it was valid.

    The chain that lets one BSE scrip code reach its own pre-split ISINs.
    """
    p = root / "panel" / "prices.parquet"
    if not p.exists():
        return pd.DataFrame(columns=["isin", "symbol", "valid_from", "valid_to"])
    df = pd.read_parquet(p, columns=["isin", "symbol", "date"])
    df["date"] = pd.to_datetime(df["date"])
    g = (df.groupby(["isin", "symbol"])["date"].agg(["min", "max"]).reset_index()
           .rename(columns={"min": "valid_from", "max": "valid_to"}))
    return g


def build(root: Optional[Path] = None, session: Optional[requests.Session] = None) -> pd.DataFrame:
    """Feed defines the universe; master resolves the ISIN; the panel supplies
    the ISIN history so a split does not break the key. Writes map.parquet."""
    root = root or data_dir()
    feed = scrip_codes_from_announcements(root)
    master = fetch_master(session)
    df = feed.merge(master, on="scrip_code", how="left")
    df["isin"] = df["isin"].fillna("")
    df["company"] = df["company"].where(df["company"].astype(bool), df["master_name"])
    df["source"] = "announcements+master"
    df.loc[df["isin"] == "", "source"] = "announcements_only"
    df["status"] = df["status"].fillna("unknown")

    hist = _panel_isin_history(root)
    # the symbol each master ISIN belongs to, then that symbol's whole ISIN chain
    sym_of = hist.sort_values("valid_to").drop_duplicates("isin", keep="last")[["isin", "symbol"]]
    chain = hist.merge(sym_of.rename(columns={"isin": "_any"}), on="symbol", how="inner")

    rows = []
    for r in df.itertuples(index=False):
        mates = chain[chain["_any"] == r.isin] if r.isin else chain.iloc[0:0]
        if len(mates):
            for m in mates.drop_duplicates("isin").itertuples(index=False):
                rows.append({
                    "scrip_code": r.scrip_code, "isin": m.isin,
                    "valid_from": FAR_PAST if m.isin == mates["isin"].iloc[0] else m.valid_from,
                    "valid_to": m.valid_to, "company": r.company, "status": r.status,
                    "first_seen": r.first_seen, "last_seen": r.last_seen,
                    "n_announcements": r.n_announcements, "source": r.source,
                    "in_panel": True,
                    "isin_role": "current" if m.isin == r.isin else "historical",
                })
        else:
            rows.append({
                "scrip_code": r.scrip_code, "isin": r.isin,
                "valid_from": FAR_PAST, "valid_to": FAR_FUTURE,
                "company": r.company, "status": r.status, "first_seen": r.first_seen,
                "last_seen": r.last_seen, "n_announcements": r.n_announcements,
                "source": r.source, "in_panel": False,
                "isin_role": "current" if r.isin else "unresolved",
            })
    out = pd.DataFrame(rows)
    # the earliest ISIN of a chain reaches back before the panel began
    out.loc[out.groupby("scrip_code")["valid_from"].idxmin(), "valid_from"] = FAR_PAST
    out.loc[out.groupby("scrip_code")["valid_to"].idxmax(), "valid_to"] = FAR_FUTURE
    out = out[COLUMNS].sort_values(["scrip_code", "valid_from"]).reset_index(drop=True)

    d = root / "bse_scrip_isin"
    d.mkdir(parents=True, exist_ok=True)
    out.to_parquet(d / "map.parquet", index=False)
    (d / "_build.json").write_text(json.dumps({
        "built": datetime.utcnow().isoformat(),
        "feed_scrips": int(len(feed)),
        "master_scrips": int(len(master)),
        "rows": int(len(out)),
        "scrips_resolved": int(out.loc[out["isin"] != "", "scrip_code"].nunique()),
        "scrips_unresolved": int(out.loc[out["isin"] == "", "scrip_code"].nunique()),
        "scrips_in_panel": int(out.loc[out["in_panel"], "scrip_code"].nunique()),
        "panel_isins_covered": int(out.loc[out["in_panel"], "isin"].nunique()),
        "historical_isin_rows": int((out["isin_role"] == "historical").sum()),
    }, indent=2), encoding="utf-8")
    return out


def _panel_isins(root: Path) -> set:
    p = root / "panel" / "prices.parquet"
    if not p.exists():
        return set()
    return set(pd.read_parquet(p, columns=["isin"])["isin"].unique())


def load(root: Optional[Path] = None) -> pd.DataFrame:
    p = (root or data_dir()) / "bse_scrip_isin" / "map.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} not built; run bse_scrip_isin.build()")
    return pd.read_parquet(p)


def panel_universe(root: Optional[Path] = None) -> pd.DataFrame:
    """The scrips worth collecting: resolved to an ISIN the price panel has."""
    df = load(root)
    return df[df["in_panel"]].reset_index(drop=True)


def unresolved_by_year(root: Optional[Path] = None) -> pd.DataFrame:
    """Every scrip code the master could not give an ISIN, by year first seen.

    For the investor to review: a code here is a company whose filings exist but
    which cannot be keyed to a security, so nothing about it can enter the
    panel.
    """
    df = load(root)
    u = df[df["isin"] == ""].copy()
    u["year"] = pd.to_datetime(u["first_seen"]).dt.year
    return u.sort_values(["year", "n_announcements"], ascending=[True, False])
