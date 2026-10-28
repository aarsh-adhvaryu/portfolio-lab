"""What the system lacks about a company, asked for the moment it is missing (S64 Phase 5 item 2).

A company whose stock facts are read with fewer than 8 quarters of results, or none, gets one Needs-from-you item: drop
its Tijori sheet. Each company is asked at most once a month. This replaces the old ask that waited for a fall.
"""
from __future__ import annotations

from datetime import date, datetime
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


CLOSING_KEY = "closing:bank-accounts"


def closing_checklist(con, n_credit: int, n_default: int, kept: str, now: Optional[datetime] = None) -> Optional[int]:
    """One question for the day he closes bank accounts the system has not seen: what to tell it, and what to check first (a
    payout into a closed account is the failure that costs money). Asked once."""
    text = (
        "You will close two bank accounts I have not seen (the ones I know, " + kept + ", stay). Before you do, one reply covering "
        "these is enough:\n"
        "1. Their bank names (no numbers) and roughly what is in them, so their last transfer into your open accounts is recognised "
        "as your own money moving, not guessed. If you can, drop each one's statement up to the closing day in Inbox and files.\n"
        f"2. FD payouts: {n_credit} of your FDs say 'Credit to Account' and {n_default} say 'Default'; my FD file does not say which account "
        "they pay into. Check each with the bank (or in net banking) that none pays into an account you are closing, and change it first. "
        "Tell me when done.\n"
        "3. US wallet: Zerodha takes netbanking only from HDFC, ICICI, IDFC FIRST, Axis or Kotak. HDFC is one you keep; SBI is not on "
        "the list. Keep HDFC open for funding it.\n"
        "4. Also move: the Zerodha payout account, dividend and demat mandates, SIPs, insurance and card auto-debits, and the income-tax "
        "refund account (pre-validate the one you keep).\n"
        "5. Note the interest each account earned this financial year: it is taxed even though the account is closed, and Quicko needs it.")
    return questions.ask(con, AGENT, CLOSING_KEY, text, now or datetime.now())


# --- S65: items that open on a date or on an event, not before (his decisions of 2026-10-28) -----------------------------------

FOREIGN_CHECK_ON = date(2027, 1, 1)
SEC_CONTACT_ON = date(2027, 1, 1)


def _count(con, sql: str) -> int:
    return int(con.execute(sql).fetchone()[0])


def deferred_items(con, now: Optional[datetime] = None) -> dict:
    """The US sleeve's deferred work, each asked once when its trigger arrives: the primary-source check of the foreign-tax rows
    (1 Jan 2027 or the first remittance), the SEC contact (1 Jan 2027 or the first US stock bought by symbol), and the GIFT City
    statement parser (the first such statement in the inbox). Returns which were asked now."""
    now = now or datetime.now()
    out: dict = {}
    if now.date() >= FOREIGN_CHECK_ON or _count(con, "SELECT count(*) FROM us_remittances"):
        try:
            from pflab.tax import foreign as tf
            n = sum(1 for r in tf.rows().values() if r.get("verification") == "secondary")
        except Exception:
            n = 0
        out["foreign_tax_check"] = questions.ask(
            con, AGENT, "us:foreign-tax-primary-check",
            f"Before money goes to the US: {n} rows behind my US tax figures (TCS threshold and rate, the 24-month rule, the 12.5% rate, "
            "dividend withholding, the exchange-rate date, the estate-tax threshold) were read from official wording quoted in search "
            "results or Zerodha's guide, not from the official pages themselves. Quicko files your return, so nothing is filed from "
            "my numbers, but the plan and estimates you see rest on them. Ask Claude Code in a session to check each against "
            "incometaxindia.gov.in and rbi.org.in (a short task), or tell me when Quicko's figures agree.", now) is not None
    if now.date() >= SEC_CONTACT_ON or _count(con, "SELECT count(*) FROM us_trades WHERE isin LIKE 'US:%'"):
        out["sec_contact"] = questions.ask(
            con, AGENT, "us:sec-contact",
            "US company filings come from the SEC, which only answers requests that carry a real contact. Give me a name and an email "
            "you are happy to send to SEC with each request (for example 'Firstname Lastname you@example.com'); it is kept in your "
            "secrets file only. Until then US funds still collect from Yahoo and US stocks stay keyed by symbol.", now) is not None
    if _count(con, "SELECT count(*) FROM inbox_items WHERE kind='gift_city'"):
        out["gift_city_parser"] = questions.ask(
            con, AGENT, "us:gift-city-parser",
            "Your first GIFT City statement is in the inbox. I cannot read it yet: ask Claude Code in a session to build its parser "
            "from this file, and I will then fill the dollar ledger from it instead of by hand.", now) is not None
    return out
