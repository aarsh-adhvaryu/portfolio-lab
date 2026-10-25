"""Quarterly results from BSE's integrated filings (SEBI's "Integrated Filing (Financial)", 2025 on).

BSE's results template (`fundamentals.pit`) is empty for NBFCs, banks and companies listed after 2024. From 2025 every listed company files its results as inline XBRL in the integrated format,
standalone and consolidated, each with a filing timestamp; `Integratedfinancedata/w` lists them. This module reads
the standalone quarterly filings into `pit.COLUMNS` rows, signs as BSE's template files them (expenses, finance
costs and tax negative), Rs million, EPS in rupees.

Point in time: a quarter is usable from the date of its filing timestamp (date_source "bse_filing"), the exchange's
own record of when it was public. lxml (already installed with trafilatura) parses the documents.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd

from pflab.fundamentals import pit

LIST_API = "https://api.bseindia.com/BseIndiaAPI/api/Integratedfinancedata/w"
DOC_BASE = "https://www.bseindia.com"

# pit field -> (XBRL element names, first found wins; sign as BSE's template files it)
TAGS = {
    "revenue": (("RevenueFromOperations", "InterestEarned"), 1),
    "other_income": (("OtherIncome",), 1),
    "total_income": (("Income", "TotalIncome"), 1),
    "expenditure": (("Expenses", "TotalExpenses"), -1),
    "finance_costs": (("FinanceCosts", "InterestExpended"), -1),
    "depreciation": (("DepreciationDepletionAndAmortisationExpense",), -1),
    "pbt": (("ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax"), 1),
    "tax": (("TaxExpense",), -1),
    "net_profit": (("ProfitLossForPeriod", "ProfitLossForThePeriod"), 1),
    "eps_basic": (("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                   "BasicEarningsLossPerShareFromContinuingOperations"), 1),
    "eps_diluted": (("DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                     "DilutedEarningsLossPerShareFromContinuingOperations"), 1),
}
_XBRLI = "{http://www.xbrl.org/2003/instance}"


def filings(listing: dict, basis: str = "Standalone") -> pd.DataFrame:
    """`Integratedfinancedata/w` JSON -> one row per quarterly filing of `basis`: qtr_id, quarter_end, filed_at, url.
    A revised filing keeps its first filing time (the quarter was public from then)."""
    rows = []
    for r in listing.get("Table") or []:
        name = str(r.get("Quarter_Name") or "")
        parts = name.split("-")
        if len(parts) < 4 or parts[0].lower() != basis.lower() or parts[2].lower() != "qtr" or not r.get("xbrlurl"):
            continue
        filed = pd.to_datetime(r.get("filing_date_time"), errors="coerce")
        if pd.isna(filed):
            continue
        qid = float(r.get("Qtrid"))
        rows.append({"qtr_id": qid, "quarter_end": pit.val.quarter_end(qid), "filed_at": filed.to_pydatetime(),
                     "url": DOC_BASE + str(r["xbrlurl"])})
    d = pd.DataFrame(rows, columns=["qtr_id", "quarter_end", "filed_at", "url"])
    return d.sort_values("filed_at").drop_duplicates("quarter_end", keep="first").reset_index(drop=True)


def _number(el) -> Optional[float]:
    txt = "".join(el.itertext()).strip()
    fmt = (el.get("format") or "").lower()
    if txt in ("", "-", "--") or "zero" in fmt:
        return 0.0 if (txt in ("-", "--") or "zero" in fmt) else None
    txt = re.sub(r"[,\s]", "", txt)
    if txt.startswith("(") and txt.endswith(")"):
        txt = "-" + txt[1:-1]
    try:
        x = float(txt)
    except ValueError:
        return None
    x *= 10 ** int(el.get("scale") or 0)
    return -x if el.get("sign") == "-" else x


def parse(content: bytes) -> Dict[str, object]:
    """One inline-XBRL results document -> {quarter_start, quarter_end, nature, audited, <element>: value}, taking
    only facts of the three-month reporting quarter with no dimensions (segment rows are ignored)."""
    from lxml import etree
    root = etree.fromstring(content, etree.XMLParser(recover=True, huge_tree=True))
    ctx = {}
    for c in root.iter(_XBRLI + "context"):
        if c.find(f"{_XBRLI}entity/{_XBRLI}segment") is not None or c.find(f"{_XBRLI}scenario") is not None:
            continue
        s, e = c.findtext(f"{_XBRLI}period/{_XBRLI}startDate"), c.findtext(f"{_XBRLI}period/{_XBRLI}endDate")
        if s and e:
            ctx[c.get("id")] = (date.fromisoformat(s.strip()), date.fromisoformat(e.strip()))
    quarters = [p for p in ctx.values() if 80 <= (p[1] - p[0]).days <= 95]
    if not quarters:
        return {}
    q = max(quarters, key=lambda p: p[1])
    ids = {k for k, v in ctx.items() if v == q}
    out: Dict[str, object] = {"quarter_start": q[0], "quarter_end": q[1]}
    for el in root.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        if not tag.endswith("}nonFraction") and not tag.endswith("}nonNumeric"):
            continue
        name = (el.get("name") or "").split(":")[-1]
        if el.get("contextRef") not in ids or name in out:
            continue
        if tag.endswith("}nonFraction"):
            v = _number(el)
            if v is not None:
                out[name] = v
        elif name in ("NatureOfReportStandaloneConsolidated", "WhetherResultsAreAuditedOrUnaudited"):
            out[name] = "".join(el.itertext()).strip()
    return out


def to_row(facts: Dict[str, object], scrip: str) -> Optional[dict]:
    if not facts or "quarter_end" not in facts:
        return None
    row = {"scrip_code": str(scrip), "quarter_end": facts["quarter_end"],
           "audited": str(facts.get("WhetherResultsAreAuditedOrUnaudited", "")).lower().startswith("audited")}
    for f, (names, sign) in TAGS.items():
        v = next((facts[n] for n in names if n in facts), None)
        if v is None:
            row[f] = None
        elif f.startswith("eps"):
            row[f] = float(v)
        else:
            row[f] = sign * float(v) / 1e6        # a tax credit stays a credit: XBRL files expenses positive
    return row if row["net_profit"] is not None else None


def fetch_quarters(scrip: str, quarter_ends: Optional[List[date]] = None, basis: str = "Standalone",
                   session=None, sleep: float = 0.4) -> pd.DataFrame:
    """Live pull of the integrated filings of one scrip (optionally only the given quarters) -> `pit.COLUMNS` rows
    plus usable_from (filing date) and date_source "bse_filing"."""
    import time

    import requests

    from pflab.data.bse_announcements import HEADERS
    s = session or requests
    r = s.get(LIST_API, params={"scripcode": scrip}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    fl = filings(r.json() if r.text.strip().startswith("{") else {}, basis)
    if quarter_ends is not None:
        fl = fl[fl["quarter_end"].isin(set(quarter_ends))]
    rows = []
    for f in fl.itertuples():
        d = s.get(f.url, headers={**HEADERS, "Accept": "*/*"}, timeout=60)
        d.raise_for_status()
        row = to_row(parse(d.content), scrip)
        if row and row["quarter_end"] == f.quarter_end:
            row["usable_from"] = f.filed_at.date()
            row["date_source"] = "bse_filing"
            rows.append(row)
        time.sleep(sleep)
    return pd.DataFrame(rows, columns=[*pit.COLUMNS, "usable_from", "date_source"])
