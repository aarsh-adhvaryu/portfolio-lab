"""Insider / SAST disclosures as BSE announced them, and the NSE cross-check.

BSE's side is not a separate download: the announcements backfill
(2010-01-01 .. 2026-09-22, 6,109 days, every one count-verified) already
holds these under `category = "Insider Trading / SAST"`. This module reads
them out and lines them up against `nse_insider`.

The two sources are NOT interchangeable, and the point of the comparison is
to say exactly where they part company (probed 2026-09-23):

  * BSE carries 2011-2015, which NSE's structured feed does not have at all
    (NSE PIT begins 2015-11-19).
  * NSE stops on 2026-05-02; BSE runs to the present.
  * BSE's row is an announcement -- one filing, headline text, no parsed
    quantity. NSE's row is a parsed disclosure with quantity, value and
    before/after holding. So BSE answers "was something disclosed", NSE
    answers "what was disclosed". E2-D §3's rule needs the second, which is
    why the structured feed is primary where it exists.

Point-in-time key is `dissem_dt` on the BSE side and `broadcast_dt` on the
NSE side. Both are dissemination, so they are comparable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from pflab.data import data_dir

CATEGORY_PATTERN = r"insider|sast"


def load(root: Optional[Path] = None, start_year: int = 2010) -> pd.DataFrame:
    """Every insider/SAST announcement BSE disseminated, from the backfill."""
    root = root or data_dir()
    base = root / "bse_announcements"
    parts = []
    for f in sorted(base.glob("*/*.parquet")):
        try:
            year = int(f.parent.name)
        except ValueError:
            continue
        if year < start_year:
            continue
        d = pd.read_parquet(f, columns=["scrip_code", "company", "headline",
                                        "category", "subcategory", "dissem_dt"])
        if not len(d):
            continue
        m = d["category"].str.contains(CATEGORY_PATTERN, case=False, na=False)
        if m.any():
            parts.append(d[m])
    if not parts:
        return pd.DataFrame(columns=["scrip_code", "company", "headline", "category",
                                     "subcategory", "dissem_dt"])
    out = pd.concat(parts, ignore_index=True)
    out["scrip_code"] = out["scrip_code"].astype(str).str.strip()
    out["dissem_dt"] = pd.to_datetime(out["dissem_dt"], errors="coerce")
    return out.dropna(subset=["dissem_dt"]).reset_index(drop=True)


def coverage_by_year(bse: pd.DataFrame, nse: pd.DataFrame) -> pd.DataFrame:
    """Per year: rows and distinct companies on each side.

    Companies are counted on each source's own key (BSE scrip code, NSE
    symbol) because the two are not joinable without the ISIN map; the
    columns are there to be read side by side, not subtracted.
    """
    b = bse.copy()
    b["year"] = b["dissem_dt"].dt.year
    n = nse.copy()
    n["year"] = n["broadcast_dt"].dt.year
    gb = b.groupby("year").agg(bse_rows=("scrip_code", "size"),
                               bse_companies=("scrip_code", "nunique"))
    gn = n.groupby("year").agg(nse_rows=("symbol", "size"),
                               nse_companies=("symbol", "nunique"))
    out = gb.join(gn, how="outer").fillna(0).astype(int)
    out["only_bse"] = (out["nse_rows"] == 0) & (out["bse_rows"] > 0)
    out["only_nse"] = (out["bse_rows"] == 0) & (out["nse_rows"] > 0)
    return out


def disagreement(bse: pd.DataFrame, nse: pd.DataFrame,
                 scrip_map: pd.DataFrame, tolerance_days: int = 3) -> dict:
    """Where the two sources disagree, at company-day granularity.

    A disclosure is matched when the same security has a row on both sides
    within `tolerance_days` -- the exchanges do not disseminate at the same
    instant, and a filing lodged with both arrives on each in its own time.
    Anything unmatched is reported, never reconciled away.
    """
    m = scrip_map[scrip_map["isin"] != ""][["scrip_code", "isin"]].drop_duplicates()
    b = bse.merge(m, on="scrip_code", how="inner")
    b = b.assign(day=b["dissem_dt"].dt.normalize())

    panel_sym = _symbol_isin(scrip_map)
    n = nse.merge(panel_sym, on="symbol", how="inner")
    n = n.assign(day=n["broadcast_dt"].dt.normalize())

    overlap = (max(b["day"].min(), n["day"].min()), min(b["day"].max(), n["day"].max()))
    b = b[(b["day"] >= overlap[0]) & (b["day"] <= overlap[1])]
    n = n[(n["day"] >= overlap[0]) & (n["day"] <= overlap[1])]

    bkeys = set(zip(b["isin"], b["day"]))
    nkeys = set(zip(n["isin"], n["day"]))
    fuzzy = set()
    for isin, day in nkeys:
        for off in range(-tolerance_days, tolerance_days + 1):
            if (isin, day + pd.Timedelta(days=off)) in bkeys:
                fuzzy.add((isin, day))
                break
    return {
        "overlap_start": overlap[0], "overlap_end": overlap[1],
        "bse_company_days": len(bkeys), "nse_company_days": len(nkeys),
        "nse_matched_in_bse": len(fuzzy),
        "nse_unmatched": len(nkeys - fuzzy),
        "nse_match_rate": (len(fuzzy) / len(nkeys)) if nkeys else float("nan"),
    }


def _symbol_isin(scrip_map: pd.DataFrame) -> pd.DataFrame:
    """symbol -> isin, from the panel, for joining NSE rows to securities."""
    p = data_dir() / "panel" / "prices.parquet"
    df = pd.read_parquet(p, columns=["symbol", "isin", "date"])
    return (df.sort_values("date").drop_duplicates("symbol", keep="last")
              [["symbol", "isin"]].reset_index(drop=True))
