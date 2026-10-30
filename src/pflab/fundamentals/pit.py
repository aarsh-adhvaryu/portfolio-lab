"""Point-in-time company fundamentals from BSE quarterly results (PLAN S24).

Builds on the migrated `valuation` module (its quarter ids, line-item picker and dating rule).
Source: BSE `Corp_detailedResult_Transpose_ng`, standalone results in BSE's template, Rs million,
one row per line item as filed. The endpoint carries no filing timestamp, so each quarter gets a
`usable_from` date by one of three rules, and a feature at date M uses only quarters with
usable_from <= M (PLAN §1: point in time):

    announcement   later of the statutory deadline (quarter end + 45 days, + 60 for March) and the
                   matched results announcement (valuation.usable_from)
    unmatched_90   quarter end + 90 days, for history with no matched announcement
    first_seen     the date this system first fetched the quarter, for live pulls (never earlier
                   than the data was in hand)

Ratios are facts computed from filed lines. The reverse DCF is a model: its result is an
`Estimate` that states every assumption.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from pflab.fundamentals import valuation as val
from pflab.pm import estimate as est

API = "https://api.bseindia.com/BseIndiaAPI/api/Corp_detailedResult_Transpose_ng/w"

# line items, first prefix match wins (lower-case); values in Rs million as filed, EPS in Rs
FIELDS = {
    "revenue": val.FIELDS["revenue"],
    "other_income": ("other income",),
    "total_income": ("total income",),
    "expenditure": ("expenditure",),
    "finance_costs": ("finance costs", "interest"),
    "depreciation": ("depreciation",),
    "pbt": ("profit (+)/ loss (-) from ordinary activities before tax", "profit before tax",
            "profit/loss before tax"),
    "tax": ("tax",),
    "net_profit": val.FIELDS["net_profit"],
    "eps_basic": val.FIELDS["eps"],
    "eps_diluted": ("diluted eps", "diluted for", "diluted"),
}
FLOW_FIELDS = ("revenue", "other_income", "total_income", "expenditure", "finance_costs", "depreciation",
               "pbt", "tax", "net_profit", "eps_basic", "eps_diluted")
COLUMNS = ["scrip_code", "quarter_end", "audited", *FIELDS]


# --- parsing ----------------------------------------------------------------------------------------

def parse_quarter(lines: Sequence[dict], scrip: str, qtr: float) -> Optional[dict]:
    """One quarter's line items (BSE `table1`) -> a row, or None for an empty/error quarter."""
    desc = [str(x.get("fld_desc", "")) for x in lines]
    values = [x.get("Value") for x in lines]
    if len(desc) <= 3 or "__ERROR__" in desc:
        return None
    qe = val.quarter_end(float(qtr))
    typ = next((v for d, v in zip(desc, values) if d.strip().lower() == "type"), "")
    end_txt = next((v for d, v in zip(desc, values) if d.strip().lower() == "date end"), None)
    if end_txt:                                    # trust the filed quarter end over the id arithmetic
        try:
            qe = datetime.strptime(end_txt, "%d-%b-%y").date()
        except ValueError:
            pass
    row = {"scrip_code": str(scrip), "quarter_end": qe,
           "audited": str(typ).strip().lower() == "audited"}
    for f, keys in FIELDS.items():
        row[f] = val.pick(desc, values, keys)
    # 2026-10-18: the bottom line is the line named exactly "Net Profit" (it agrees with EPS). The prefix rule took
    # "Net Profit (+)/ Loss (-) from Ordinary Activities after Tax" first, which some filers leave at PBT.
    bottom = val.pick([d if d.strip().lower() == "net profit" else "" for d in desc], values, ("net profit",))
    if bottom is not None:
        row["net_profit"] = bottom
    return row


def quarterly_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Stored raw line items (scrip_code, qtr, fld_desc, Value) -> one row per quarter."""
    rows = []
    for (sc, q), g in raw.groupby(["scrip_code", "qtr"], sort=True):
        lines = [{"fld_desc": d, "Value": v} for d, v in zip(g["fld_desc"], g["Value"])]
        r = parse_quarter(lines, str(sc), float(q))
        if r:
            rows.append(r)
    return pd.DataFrame(rows, columns=COLUMNS)


def fetch_quarters(scrip: str, qtr_ids: Sequence[float], session=None, sleep: float = 0.4) -> pd.DataFrame:
    """Live pull of the given BSE quarter ids for one scrip -> `quarterly_frame` rows."""
    import time

    import requests

    from pflab.data.bse_announcements import HEADERS
    s = session or requests
    rows = []
    for q in qtr_ids:
        r = s.get(API, params={"Scrip_cd": scrip, "Qtr": f"{float(q):.2f}"}, headers=HEADERS, timeout=30)
        r.raise_for_status()
        t = r.json().get("table1") or [] if r.text.strip().startswith("{") else []
        row = parse_quarter(t, scrip, q)
        if row:
            rows.append(row)
        time.sleep(sleep)
    return pd.DataFrame(rows, columns=COLUMNS)


def latest_qtr_id(asof: date) -> int:
    """Highest BSE quarter id whose quarter has ended by `asof` (Jun-2000 = 26)."""
    k = (asof.year - 2000) * 4 + (asof.month - 6) // 3
    qid = 26 + k
    return qid if val.quarter_end(qid) <= asof else qid - 1


def load_history(scrip: str, root: Optional[Path] = None) -> pd.DataFrame:
    """Quarters pulled earlier into data/bse_results (history for the research period)."""
    from pflab.data import data_dir
    p = (root or data_dir()) / "bse_results" / f"{scrip}.parquet"
    if not p.exists():
        return pd.DataFrame(columns=COLUMNS)
    return quarterly_frame(pd.read_parquet(p))


# --- dating ---------------------------------------------------------------------------------------------

def date_quarters(q: pd.DataFrame, ann: Optional[pd.DataFrame] = None,
                  first_seen: Optional[date] = None) -> pd.DataFrame:
    """Add usable_from and date_source. With `ann` (BSE announcements: scrip_code, t, category,
    subcategory, headline) quarters take the announcement rule; unmatched ones take quarter end + 90
    days. With `first_seen` and no announcement match, that date is used instead (live pulls)."""
    if q.empty:
        return q.assign(usable_from=pd.Series(dtype=object), date_source=pd.Series(dtype=object))
    matched = val.matched_announcements(ann, q) if ann is not None and len(ann) else \
        pd.DataFrame(columns=["scrip_code", "quarter_end", "announced"])
    dq = val.dated_quarters(q, matched)
    if first_seen is not None:
        m = dq["date_source"] == "unmatched_90"
        dq.loc[m, "usable_from"] = first_seen
        dq.loc[m, "date_source"] = "first_seen"
    return dq


def usable(dq: pd.DataFrame, scrip: str, asof: date) -> pd.DataFrame:
    """Quarters of `scrip` usable on `asof`, newest first. Nothing dated after `asof` is ever returned."""
    d = dq[(dq["scrip_code"].astype(str) == str(scrip)) & (dq["usable_from"] <= asof)]
    return d.sort_values("quarter_end", ascending=False).drop_duplicates("quarter_end").reset_index(drop=True)


def last_quarters(dq: pd.DataFrame, scrip: str, asof: date, n: int = 8) -> pd.DataFrame:
    """The last `n` usable quarters, oldest first. Gaps are kept as gaps (never filled)."""
    return usable(dq, scrip, asof).head(n).sort_values("quarter_end").reset_index(drop=True)


# --- ratios --------------------------------------------------------------------------------------------

def _prior_year(q: date) -> date:
    return (pd.Timestamp(q) - pd.DateOffset(years=1) + pd.offsets.MonthEnd(0)).date()


def _consecutive(qs: pd.DataFrame, n: int) -> Optional[pd.DataFrame]:
    """The newest `n` quarters if they are n consecutive quarters, else None."""
    if len(qs) < n:
        return None
    tail = qs.sort_values("quarter_end").tail(n)
    ends = list(tail["quarter_end"])
    for a, b in zip(ends, ends[1:]):
        if (pd.Timestamp(b) - pd.offsets.QuarterEnd(1)).date() != a:
            return None
    return tail


def _growth(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return None if a is None or b is None or b == 0 or np.isnan(a) or np.isnan(b) else (a - b) / abs(b)


def ratios(qs: pd.DataFrame) -> Dict[str, Optional[float]]:
    """Facts from the usable quarters (oldest first): TTM revenue/net profit/EPS, margins, tax rate,
    year-on-year growth for the latest quarter and for TTM. None where a needed quarter is missing:
    a TTM never substitutes an older quarter for a gap."""
    out: Dict[str, Optional[float]] = {k: None for k in (
        "revenue_ttm", "net_profit_ttm", "eps_ttm", "net_margin_ttm", "pbt_margin_ttm", "tax_rate_ttm",
        "revenue_yoy_q", "net_profit_yoy_q", "eps_yoy_q", "revenue_ttm_yoy", "net_profit_ttm_yoy",
        "eps_ttm_yoy", "latest_quarter")}
    if qs.empty:
        return out
    qs = qs.sort_values("quarter_end")
    out["latest_quarter"] = qs["quarter_end"].iloc[-1]
    t4 = _consecutive(qs, 4)
    t8 = _consecutive(qs, 8)

    def ssum(df, col):
        v = df[col].astype(float)
        return None if v.isna().any() else float(v.sum())

    if t4 is not None:
        out["revenue_ttm"], out["net_profit_ttm"], out["eps_ttm"] = ssum(t4, "revenue"), ssum(t4, "net_profit"), ssum(t4, "eps_basic")
        pbt, tax = ssum(t4, "pbt"), ssum(t4, "tax")
        if out["revenue_ttm"]:
            out["net_margin_ttm"] = None if out["net_profit_ttm"] is None else out["net_profit_ttm"] / out["revenue_ttm"]
            out["pbt_margin_ttm"] = None if pbt is None else pbt / out["revenue_ttm"]
        if pbt and tax is not None:
            out["tax_rate_ttm"] = -tax / pbt            # BSE shows tax as a negative line
    if t8 is not None:
        prev = t8.head(4)
        out["revenue_ttm_yoy"] = _growth(out["revenue_ttm"], ssum(prev, "revenue"))
        out["net_profit_ttm_yoy"] = _growth(out["net_profit_ttm"], ssum(prev, "net_profit"))
        out["eps_ttm_yoy"] = _growth(out["eps_ttm"], ssum(prev, "eps_basic"))
    last = qs.iloc[-1]
    year_ago = qs[qs["quarter_end"] == _prior_year(last["quarter_end"])]
    if len(year_ago):
        ya = year_ago.iloc[-1]
        out["revenue_yoy_q"] = _growth(last["revenue"], ya["revenue"])
        out["net_profit_yoy_q"] = _growth(last["net_profit"], ya["net_profit"])
        out["eps_yoy_q"] = _growth(last["eps_basic"], ya["eps_basic"])
    return out


def valuation_ratios(price: float, eps_ttm: Optional[float], revenue_ttm_mn: Optional[float] = None,
                     shares_outstanding: Optional[float] = None) -> Dict[str, Optional[float]]:
    """Price-based ratios from facts: P/E and earnings yield (only for positive TTM EPS), price to
    sales (needs share count; revenue in Rs million). Not estimates: ratios of a price and a filed number."""
    pe = price / eps_ttm if eps_ttm and eps_ttm > 0 and price > 0 else None
    ps = None
    if revenue_ttm_mn and shares_outstanding and price > 0:
        ps = price * shares_outstanding / (revenue_ttm_mn * 1e6)
    return {"pe_ttm": pe, "earnings_yield_ttm": (eps_ttm / price) if eps_ttm is not None and price > 0 else None,
            "ps_ttm": ps}


# --- implied expectations (reverse DCF) ------------------------------------------------------------------

def _pv_from_growth(eps0: float, g: float, r: float, years: int, gt: float) -> float:
    pv = 0.0
    e = eps0
    for t in range(1, years + 1):
        e *= 1 + g
        pv += e / (1 + r) ** t
    tv = e * (1 + gt) / (r - gt)
    return pv + tv / (1 + r) ** years


def implied_growth(price: float, eps_ttm: float, asof: date, *, discount_rate: float = 0.12,
                   years: int = 10, terminal_growth: float = 0.05) -> est.Estimate:
    """Earnings growth per year, for `years` years, that a share price implies, as an Estimate.

    Model: price = PV of EPS growing at g for N years, then growing at the terminal rate forever,
    discounted at r; EPS stands in for distributable cash flow (no reinvestment need, no dilution).
    The discount rate and terminal growth are ASSUMPTIONS, printed with the result; change them and
    the answer moves. Not a forecast of what will happen."""
    if eps_ttm <= 0 or price <= 0:
        raise ValueError("needs a positive price and positive TTM EPS")
    if discount_rate <= terminal_growth:
        raise ValueError("discount rate must exceed terminal growth")
    lo, hi = -0.5, 1.5
    if _pv_from_growth(eps_ttm, lo, discount_rate, years, terminal_growth) > price:
        raise ValueError("price below the model value even at -50% growth")
    if _pv_from_growth(eps_ttm, hi, discount_rate, years, terminal_growth) < price:
        raise ValueError("price above the model value even at +150% growth")
    for _ in range(200):
        mid = (lo + hi) / 2
        if _pv_from_growth(eps_ttm, mid, discount_rate, years, terminal_growth) < price:
            lo = mid
        else:
            hi = mid
    g = (lo + hi) / 2
    return est.make(g * 100, f"reverse DCF on TTM EPS: growth for {years}y then {terminal_growth:.1%} forever, "
                    f"discount rate {discount_rate:.1%} (assumptions, not forecasts)",
                    {"price": price, "eps_ttm": eps_ttm, "r": discount_rate, "years": years, "gt": terminal_growth},
                    asof, horizon=f"{years} years", unit="% a year")


# --- store ----------------------------------------------------------------------------------------------------

def save(con, dq: pd.DataFrame, source: str, now: Optional[datetime] = None, basis: str = "standalone") -> int:
    """Insert dated quarters; an existing (scrip, quarter, basis) is kept as first stored (so its
    usable_from never moves later)."""
    now = now or datetime.now()
    n0 = con.execute("SELECT count(*) FROM quarterly_results").fetchone()[0]
    d = dq.copy()
    d["source"], d["fetched_at"], d["basis"] = source, now, basis
    # the same quarter twice in ONE batch (BSE lists a re-filed result again) is not covered by ON CONFLICT: DuckDB refuses the commit
    # (seen 2026-10-30, the guards job failed). The first copy is kept, as a stored quarter is.
    d = d.drop_duplicates(["scrip_code", "quarter_end", "basis"], keep="first")
    cols = ["scrip_code", "quarter_end", "audited", *FIELDS, "usable_from", "date_source", "source", "fetched_at",
            "basis"]
    con.register("_q", d[cols])
    con.execute(f"INSERT INTO quarterly_results ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _q ON CONFLICT DO NOTHING")
    con.unregister("_q")
    return con.execute("SELECT count(*) FROM quarterly_results").fetchone()[0] - n0


def correct(con, q: pd.DataFrame) -> int:
    """Overwrite the filed figures of stored quarters with a re-parse of the same filing (a parser fix); the dates
    (usable_from, date_source) never change. Returns the rows updated. BSE's template is standalone."""
    n = 0
    for r in q.to_dict("records"):
        key = [str(r["scrip_code"]), r["quarter_end"]]
        cur = con.execute("SELECT 1 FROM quarterly_results WHERE scrip_code=? AND quarter_end=? AND basis='standalone'",
                          key).fetchone()
        if cur:
            con.execute(f"UPDATE quarterly_results SET {', '.join(f'{f}=?' for f in FIELDS)} "
                        "WHERE scrip_code=? AND quarter_end=? AND basis='standalone'",
                        [None if pd.isna(r[f]) else r[f] for f in FIELDS] + key)
            n += 1
    return n


def load(con, scrip: str, basis: str = "standalone") -> pd.DataFrame:
    d = con.execute("SELECT * EXCLUDE (source, fetched_at, basis) FROM quarterly_results WHERE scrip_code=? AND basis=? "
                    "ORDER BY quarter_end", [str(scrip), basis]).df()
    for c in ("quarter_end", "usable_from"):           # pandas returns Timestamps; the module compares dates
        d[c] = pd.to_datetime(d[c]).dt.date
    return d


def choose(standalone: pd.DataFrame, consolidated: pd.DataFrame, n: int = 8) -> tuple:
    """(quarters, basis) for the safety checks (amendment 2 to the dip-rule protocol, 2026-10-18): consolidated when
    its newest `n` quarters are consecutive and its newest is not older than the newest standalone quarter; else
    standalone, the validated basis."""
    if len(consolidated) and _consecutive(consolidated, n) is not None:
        newest_c = max(consolidated["quarter_end"])
        if not len(standalone) or newest_c >= max(standalone["quarter_end"]):
            return consolidated, "consolidated"
    return standalone, "standalone"
