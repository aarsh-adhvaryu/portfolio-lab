"""Point-in-time company -> sector map from the captured constituent lists.

Charter E2-B §3 asked for "NSE industry classification, current mapping
applied to history -- declared simplification". The 2026-09-26 instruction
replaced that with a map built from the `Industry` column of the Internet
Archive captures of NSE's constituent lists (the same files E1b's membership
build is anchored on), so a decision at M reads the label NSE published on
or before M rather than today's.

Three things the data forces, each reported rather than resolved here:

1. **NSE changed taxonomy twice.** The captures carry three vocabularies:

       A  <= 2013-08   ~72 fine industries ("TEXTILES - COTTON", "BANKS")
       B  2014-01 .. 2021-06   18-20 upper-case sectors ("IT", "FINANCIAL
                               SERVICES")
       C  >= 2022-07   NSE's 2023 macro-economic sectors, mixed case
                       ("Financial Services", "Capital Goods")

   A decision reads the label in whatever taxonomy its capture used.
   `crosswalk` derives an A->B (or B->C) label map from ISINs captured on
   both sides of a switch, with its purity, so a charter can declare that it
   harmonises; nothing here harmonises by default.

2. **Coverage is partial.** E1's universe is the 500 most traded names, not
   Nifty 500 members, and momentum buys names on the way into the index --
   before any capture lists them. `sector_at` returns `None` for a name no
   usable capture carries.

3. **A later capture is lookahead.** `allow_later=True` lets a name with no
   capture on or before M take its label from its first later capture,
   flagged `approximate`. The label itself barely moves, but *having* a
   later capture means the name later entered a big index, so any rule that
   treats mapped and unmapped names differently leaks future membership.
   `allow_later` therefore has no default: the charter must choose it.

The capture date is the usable-from date: the Wayback crawl proves the list
was public by then.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd

from pflab.data import data_dir
from pflab.data.index_captures import CAPTURE_FILES

TAXONOMY_B = frozenset({
    "AUTOMOBILE", "CEMENT & CEMENT PRODUCTS", "CHEMICALS", "CONSTRUCTION",
    "CONSUMER GOODS", "ENERGY", "FERTILISERS & PESTICIDES",
    "FINANCIAL SERVICES", "HEALTHCARE SERVICES", "INDUSTRIAL MANUFACTURING",
    "IT", "MEDIA & ENTERTAINMENT", "METALS", "OIL & GAS", "PAPER", "PHARMA",
    "POWER", "SERVICES", "TELECOM", "TEXTILES",
})

COLUMNS = ["capture_date", "index", "isin", "issuer", "industry", "taxonomy"]


class SectorMapError(RuntimeError):
    pass


def issuer(isin: str) -> str:
    """ISIN up to the security type: 'INE563J01'. Same company, same equity
    class; the serial after it changes on a face-value split, which is why a
    held ISIN can be missing from a capture that lists the company."""
    return str(isin)[:9]


def taxonomy_of(labels: Iterable[str]) -> str:
    labels = [str(x).strip() for x in labels if isinstance(x, str) and x.strip()]
    if not labels:
        raise SectorMapError("capture has no industry labels")
    if not all(x.isupper() for x in labels):
        return "C"
    if all(x in TAXONOMY_B for x in labels):
        return "B"
    return "A"


def parse_industry(content: bytes) -> pd.DataFrame:
    """One capture -> isin, industry. Empty if the file has no Industry column."""
    lines = content.decode("utf-8", errors="replace").splitlines()
    start = next((i for i, ln in enumerate(lines[:10])
                  if "symbol" in ln.lower() and "isin" in ln.lower()), None)
    if start is None:
        return pd.DataFrame(columns=["isin", "industry"])
    body = "\n".join(ln for ln in lines[start:] if ln.strip())
    df = pd.read_csv(io.StringIO(body), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    if "Industry" not in df.columns or "ISIN Code" not in df.columns:
        return pd.DataFrame(columns=["isin", "industry"])
    df = df.rename(columns={"ISIN Code": "isin", "Industry": "industry"})
    df["isin"] = df["isin"].astype(str).str.strip()
    df["industry"] = df["industry"].astype(str).str.strip()
    df = df[df["isin"].str.match(r"^INE") & (df["industry"] != "")]
    return df[["isin", "industry"]].reset_index(drop=True)


def build(root: Optional[Path] = None) -> pd.DataFrame:
    """Every (capture, ISIN, industry) from the raw capture files on disk."""
    root = root or data_dir()
    raw = root / "index_membership" / "raw" / "captures"
    to_index = {f: k for k, fs in CAPTURE_FILES.items() for f in fs}
    rows = []
    for p in sorted(raw.glob("*.csv")):
        ts, _, fname = p.name.partition("_")
        idx = to_index.get(fname.lower())
        if idx is None:
            continue
        df = parse_industry(p.read_bytes())
        if df.empty:
            continue
        df["capture_date"] = datetime.strptime(ts[:8], "%Y%m%d").date()
        df["index"] = idx
        df["taxonomy"] = taxonomy_of(df["industry"])
        rows.append(df)
    if not rows:
        raise SectorMapError(f"no capture with an Industry column under {raw}")
    out = pd.concat(rows, ignore_index=True)
    out["issuer"] = out["isin"].map(issuer)
    # Two lists captured the same day can both carry a name, and must agree.
    # One ISIN with two labels in one capture is a source error (the
    # 2006-11-08 Nifty 500 file lists Ramco Systems under Ramco Industries'
    # ISIN), so that pair is dropped from that capture -- neither label can
    # be trusted -- and reported in attrs rather than resolved by a guess.
    n_lab = out.groupby(["capture_date", "isin"])["industry"].transform("nunique")
    conflicts = (out[n_lab > 1][["capture_date", "index", "isin", "industry"]]
                 .drop_duplicates().astype({"capture_date": str})
                 .to_dict("records"))
    out = out[n_lab == 1]
    out = (out.sort_values(["capture_date", "index", "isin"])
              .drop_duplicates(["capture_date", "isin"], keep="first"))
    out = out[COLUMNS].reset_index(drop=True)
    out.attrs["conflicts"] = conflicts
    return out


def write(table: pd.DataFrame, root: Optional[Path] = None) -> Path:
    p = (root or data_dir()) / "index_membership" / "sector_map.parquet"
    table.to_parquet(p, index=False)
    return p


def load(root: Optional[Path] = None) -> pd.DataFrame:
    df = pd.read_parquet((root or data_dir()) / "index_membership" / "sector_map.parquet")
    df["capture_date"] = pd.to_datetime(df["capture_date"]).dt.date
    return df


def sector_at(table: pd.DataFrame, isins: Iterable[str], m: date, *,
              allow_later: bool, match_issuer: bool = True) -> pd.DataFrame:
    """Label for each ISIN as of month-end `m`.

    Returns one row per requested ISIN: industry, taxonomy, as_of (capture
    date used), matched_by ('isin' | 'issuer' | None) and approximate (True
    only when the label came from a capture dated after `m`).

    The latest capture on or before `m` wins. An exact ISIN match in that
    capture beats an issuer match; an issuer match is used only when
    `match_issuer` and the ISIN itself is in no usable capture.
    """
    isins = list(dict.fromkeys(isins))
    t = table
    cols = ["isin", "industry", "taxonomy", "as_of", "matched_by", "approximate"]
    out = {i: dict(isin=i, industry=None, taxonomy=None, as_of=None,
                   matched_by=None, approximate=False) for i in isins}

    def _fill(sub, key, how, approx):
        sub = sub.sort_values("capture_date")
        last = sub.groupby(key).tail(1) if not approx else sub.groupby(key).head(1)
        by = dict(zip(last[key], last.itertuples(index=False)))
        for i in isins:
            if out[i]["industry"] is not None:
                continue
            k = i if key == "isin" else issuer(i)
            r = by.get(k)
            if r is not None:
                out[i].update(industry=r.industry, taxonomy=r.taxonomy,
                              as_of=r.capture_date, matched_by=how,
                              approximate=approx)

    before = t[t["capture_date"] <= m]
    _fill(before, "isin", "isin", False)
    if match_issuer:
        _fill(before, "issuer", "issuer", False)
    if allow_later:
        after = t[t["capture_date"] > m]
        _fill(after, "isin", "isin", True)
        if match_issuer:
            _fill(after, "issuer", "issuer", True)
    return pd.DataFrame([out[i] for i in isins], columns=cols)


def crosswalk(table: pd.DataFrame, before: date, after: date) -> pd.DataFrame:
    """Label map between the taxonomies of two capture dates.

    For each label on `before`, the modal label on `after` among ISINs
    carried by both, with n (names in common) and purity (share taking the
    modal label). A charter that harmonises taxonomies declares this table;
    a purity well below 1 means the two vocabularies do not nest.
    """
    a = table[table["capture_date"] == before][["isin", "industry"]]
    b = table[table["capture_date"] == after][["isin", "industry"]]
    if a.empty or b.empty:
        raise SectorMapError(f"no capture on {before} or {after}")
    j = a.merge(b, on="isin", suffixes=("_from", "_to"))
    rows = []
    for lab, g in j.groupby("industry_from"):
        vc = g["industry_to"].value_counts()
        rows.append({"from": lab, "to": vc.index[0], "n": int(len(g)),
                     "purity": float(vc.iloc[0] / len(g))})
    return pd.DataFrame(rows, columns=["from", "to", "n", "purity"]) \
             .sort_values("from").reset_index(drop=True)


def coverage(table: pd.DataFrame, isins_by_month: Dict[date, Iterable[str]], *,
             allow_later: bool) -> pd.DataFrame:
    """Share of each month's names that get a label, and how."""
    rows = []
    for m, names in sorted(isins_by_month.items()):
        names = list(names)
        if not names:
            continue
        s = sector_at(table, names, m, allow_later=allow_later)
        n = len(s)
        rows.append({"month_end": m, "n": n,
                     "mapped": float(s["industry"].notna().sum() / n),
                     "by_issuer": float((s["matched_by"] == "issuer").sum() / n),
                     "approximate": float(s["approximate"].sum() / n)})
    return pd.DataFrame(rows)
