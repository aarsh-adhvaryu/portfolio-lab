"""Mutual fund look-through from AMC monthly portfolio files (PLAN S16).

AMCs publish each scheme's holdings monthly as spreadsheets (SEBI requires an ISIN column and
the share of net assets). Layouts differ by AMC, so the parser finds the header row by what it
says (an ISIN column and a percent-of-NAV column), not by position, and takes every row with a
valid ISIN plus the cash-like lines. A file whose weights do not sum to about 100% is refused:
a half-read portfolio would silently understate every exposure.

A fund with no loaded file is reported `category-only` with the reason; its exposure stays
under its own category label (see `risk.exposure`). Nothing is spread by guess.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd

ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")
CASH_RE = re.compile(r"net current assets|cash|tri[\s-]*party|treps|cblo|reverse repo|margin|receivable|payable|"
                     r"other current assets|net receivable", re.I)
SUM_LOW, SUM_HIGH = 95.0, 101.0       # weights incl. cash must total about 100%
STALE_DAYS = 45                       # monthly files: older than this is flagged


class PortfolioError(ValueError):
    pass


@dataclass
class PortfolioFile:
    sheet: str
    title: str
    as_of: Optional[date]
    holdings: pd.DataFrame            # isin, name, industry, pct, market_value, kind
    total_pct: float
    issues: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def kind_of(isin: Optional[str], name: str = "") -> str:
    """equity | debt | govt | other | cash, from the ISIN's type code and the line's name."""
    if not isin:
        return "cash" if CASH_RE.search(name or "") else "other"
    if isin.startswith("IN00") or isin.startswith("IN0") and not isin.startswith("INE"):
        return "govt"
    code = isin[7:9]
    if isin.startswith("INE") and code == "01":
        return "equity"
    if isin.startswith("INE") and code in ("07", "08", "14", "15"):
        return "debt"
    if isin.startswith("INF"):
        return "fund_units"
    return "other"


_DATE_PATTERNS = [
    (re.compile(r"(\d{1,2})[-/ ]([A-Za-z]{3,9})[-/ ,]+(\d{4})"), "%d %b %Y"),
    (re.compile(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})"), "%b %d %Y"),
    (re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})"), "%d %m %Y"),
]


def _find_date(text: str) -> Optional[date]:
    for rx, fmt in _DATE_PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        a, b, c = m.groups()
        for f in (fmt, fmt.replace("%b", "%B")):
            try:
                return datetime.strptime(f"{a} {b} {c}", f).date()
            except ValueError:
                continue
    return None


def _to_float(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("%", "")
    if s in ("", "-", "--", "NIL", "Nil", "nil"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _header(rows: List[list]) -> Optional[tuple]:
    for i, r in enumerate(rows[:60]):
        low = [str(c).strip().lower() if c is not None else "" for c in r]
        isin = next((j for j, c in enumerate(low) if "isin" in c), None)
        pct = next((j for j, c in enumerate(low) if re.search(r"%\s*(to|of)\s*(net|nav|aum)|percent|% to", c)
                    or c in ("% to nav", "% of nav", "% nav")), None)
        if isin is not None and pct is not None:
            name = next((j for j, c in enumerate(low) if re.search(r"name of|instrument|security|issuer", c)), None)
            ind = next((j for j, c in enumerate(low) if re.search(r"industry|sector|rating", c)), None)
            mv = next((j for j, c in enumerate(low) if re.search(r"market|fair value|value", c) and j != pct), None)
            return i, isin, pct, name, ind, mv
    return None


def parse_sheet(rows: List[list], sheet: str = "") -> PortfolioFile:
    h = _header(rows)
    if h is None:
        raise PortfolioError(f"sheet {sheet!r}: no header row with an ISIN column and a % of NAV column")
    hi, c_isin, c_pct, c_name, c_ind, c_mv = h
    title_text = " ".join(str(c) for r in rows[:hi] for c in r if c is not None)
    out = []
    for r in rows[hi + 1:]:
        if c_isin >= len(r) or c_pct >= len(r):
            continue
        isin = str(r[c_isin]).strip().upper() if r[c_isin] is not None else ""
        pct = _to_float(r[c_pct])
        name = str(r[c_name]).strip() if c_name is not None and c_name < len(r) and r[c_name] is not None else ""
        if pct is None:
            continue
        if ISIN_RE.match(isin):
            isin_v: Optional[str] = isin
        elif CASH_RE.search(name):
            isin_v = None
        else:
            continue                   # subtotal / heading / unparseable
        out.append({"isin": isin_v, "name": name,
                    "industry": (str(r[c_ind]).strip() if c_ind is not None and c_ind < len(r) and r[c_ind] is not None else None),
                    "pct": pct,
                    "market_value": _to_float(r[c_mv]) if c_mv is not None and c_mv < len(r) else None,
                    "kind": kind_of(isin_v, name)})
    df = pd.DataFrame(out, columns=["isin", "name", "industry", "pct", "market_value", "kind"])
    issues: List[str] = []
    if df.empty:
        issues.append("no holdings rows found")
        return PortfolioFile(sheet, title_text.strip(), _find_date(title_text), df, 0.0, issues)
    if df["pct"].abs().sum() <= 1.5:                       # file stores fractions, not percent
        df["pct"] = df["pct"] * 100.0
    total = float(df["pct"].sum())
    if not SUM_LOW <= total <= SUM_HIGH:
        issues.append(f"weights sum to {total:.2f}%, outside {SUM_LOW}-{SUM_HIGH}%: file refused")
    dup = df[df["isin"].notna()].duplicated("isin", keep=False)
    if dup.any():                                          # the same security on two lines: add them
        agg = df[df["isin"].notna()].groupby("isin", as_index=False).agg(
            name=("name", "first"), industry=("industry", "first"), pct=("pct", "sum"),
            market_value=("market_value", lambda s: s.sum(min_count=1)), kind=("kind", "first"))
        df = pd.concat([agg, df[df["isin"].isna()]], ignore_index=True)
    return PortfolioFile(sheet, title_text.strip(), _find_date(title_text), df, total, issues)


def parse_workbook(source: Union[str, Path, bytes]) -> Dict[str, PortfolioFile]:
    """One PortfolioFile per sheet that looks like a portfolio. Sheets without a recognisable header
    are skipped (cover pages, notes); a workbook with none raises."""
    import openpyxl
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out: Dict[str, PortfolioFile] = {}
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        try:
            out[ws.title] = parse_sheet(rows, ws.title)
        except PortfolioError:
            continue
    if not out:
        raise PortfolioError("no sheet with an ISIN column and a % of NAV column")
    return out


def file_sha(source: Union[str, Path, bytes]) -> str:
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    return hashlib.sha256(data).hexdigest()


# --- store ------------------------------------------------------------------------------------------------

def save(con, fund_isin: str, pf: PortfolioFile, as_of: Optional[date], source_doc_sha: str,
         now: Optional[datetime] = None) -> None:
    """Store a validated file for `fund_isin` at `as_of` (replaces that fund/date)."""
    if not pf.ok:
        raise PortfolioError(f"{fund_isin}: {'; '.join(pf.issues)}")
    as_of = as_of or pf.as_of
    if as_of is None:
        raise PortfolioError("no as-of date in the file: pass one")
    now = now or datetime.now()
    from pflab.pm.store import transaction
    with transaction(con):                               # all or nothing (S58 drill 2)
        con.execute("DELETE FROM fund_holdings WHERE fund_isin=? AND as_of=?", [fund_isin, as_of])
        for r in pf.holdings.itertuples():
            con.execute("INSERT INTO fund_holdings VALUES (?,?,?,?,?,?,?,?,?,?)",
                        [fund_isin, as_of, r.isin, r.name, r.industry, float(r.pct),
                         None if r.market_value != r.market_value else r.market_value, r.kind,
                         source_doc_sha, now])


def lookthrough(con, fund_isins: List[str], asof: date,
                sector_of: Optional[Dict[str, str]] = None) -> tuple:
    """(rows, status). rows: fund_isin, isin, sector, issuer, weight (fraction of the fund) for the
    latest file per fund dated on or before `asof`. status: one row per fund with `status` in
    {look-through, look-through (stale), category-only} and the reason."""
    sector_of = sector_of or {}
    rows, stat = [], []
    for f in fund_isins:
        r = con.execute("SELECT max(as_of) FROM fund_holdings WHERE fund_isin=? AND as_of<=?", [f, asof]).fetchone()[0]
        if r is None:
            stat.append(dict(fund_isin=f, as_of=None, status="category-only",
                             reason="no portfolio file loaded for this fund"))
            continue
        h = con.execute("SELECT isin, name, industry, pct_nav, kind FROM fund_holdings WHERE fund_isin=? AND as_of=?",
                        [f, r]).fetchall()
        for isin, name, industry, pct, kind in h:
            if kind == "equity":
                sector = sector_of.get(isin) or industry or "Unclassified"
                issuer = isin[:9]
            elif kind in ("debt", "govt"):
                sector, issuer = "Debt (via fund)", (isin[:9] if isin and isin.startswith("INE") else "GOI")
            elif kind == "cash":
                sector, issuer = "Cash and equivalents (via fund)", None
            else:
                sector, issuer = "Other (via fund)", (isin[:9] if isin and isin.startswith("INE") else None)
            rows.append(dict(fund_isin=f, isin=isin or f"CASH:{f}", sector=sector, issuer=issuer, weight=pct / 100.0))
        age = (asof - r).days
        stat.append(dict(fund_isin=f, as_of=r, status="look-through" if age <= STALE_DAYS else "look-through (stale)",
                         reason=f"file dated {r}, {age} days old"))
    return (pd.DataFrame(rows, columns=["fund_isin", "isin", "sector", "issuer", "weight"]),
            pd.DataFrame(stat, columns=["fund_isin", "as_of", "status", "reason"]))
