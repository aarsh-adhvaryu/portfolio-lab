"""What the system lacks about a company, asked for the moment it is missing (S64 Phase 5 item 2).

A company whose stock facts are read with fewer than 8 quarters of results, or none, gets one Needs-from-you item: drop
its Tijori sheet. Each company is asked at most once a month. This replaces the old ask that waited for a fall.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pflab.agents import questions

MIN_QUARTERS = 8
AGENT = "needs"


def quarter_count(con, root, isin: str) -> Optional[int]:
    """Filed quarters (standalone or consolidated, whichever has more) held for the company; None when its BSE scrip is unknown."""
    from pflab.data import bse_scrip_isin
    try:
        m = bse_scrip_isin.load(root)
    except FileNotFoundError:
        return None
    scrips = [str(s) for s in m.loc[m["isin"] == isin, "scrip_code"]]
    if not scrips:
        return None
    ph = ",".join("?" * len(scrips))
    return int(max(con.execute(f"SELECT count(DISTINCT quarter_end) FROM quarterly_results WHERE scrip_code IN ({ph}) "
                               "GROUP BY basis", scrips).fetchall() or [(0,)])[0])


def ask_company_detail(con, isin: str, what: str, now: Optional[datetime] = None, symbol: Optional[str] = None) -> Optional[int]:
    """Open the Tijori ask for `isin` (once a month); None when it was already asked this month."""
    now = now or datetime.now()
    sym = symbol or (con.execute("SELECT symbol FROM instruments WHERE isin=?", [isin]).fetchone() or [isin])[0] or isin
    return questions.ask(con, AGENT, f"tijori:{isin}:{now:%Y-%m}",
                         f"Please drop the Tijori sheet for {sym} (missing: {what}). It stays on this PC; "
                         "put it in Inbox and files.", now)


def check_company(con, root, isin: str, now: Optional[datetime] = None, symbol: Optional[str] = None) -> Optional[int]:
    """Ask when the company has fewer than MIN_QUARTERS quarters, or no results at all."""
    n = quarter_count(con, root, isin)
    if n is None:
        return ask_company_detail(con, isin, "no results data found for it", now, symbol)
    if n < MIN_QUARTERS:
        return ask_company_detail(con, isin, f"only {n} quarters of results, {MIN_QUARTERS} needed", now, symbol)
    return None
