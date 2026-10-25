"""BSE quarterly shareholding patterns (E2-D §4, and whatever E2-E declares).

Point-in-time key is the **filing date**, never the quarter end: a quarter
ending 31 December is filed around 21 January, so dating it by its quarter
end would let the engine see three weeks into the future. A quarter whose
filing date cannot be traced is recorded `filing_date = NaT` with
`filing_date_source = "unresolved"`, and is the caller's problem to exclude
-- it is never dated by its quarter end.

Quarter ids are global and sequential on BSE: 65 = March 2010, 130 = June
2026, so 2010-onward is qtrid 65..130 (66 quarters).

TWO ERAS, AND A TRAP
--------------------
The SEBI format that carries category-wise holding and the number of
shareholders per category begins with the **December 2015** quarter
(qtrid 88). For every quarter before it, `Corp_shpSec_SHPSUMMARY_ng` does
NOT fail -- it returns well-formed JSON with the six correct category
labels and **zero in every numeric field**. Written naively that records
"promoter holding 0%, shares outstanding 0" for every company for
2010-2015; under E2-D §3, whose rule fires when promoter holding falls
more than 1.0 pp, a zero-filled history would flag essentially the whole
universe. It is the 2026-09-22 "throttled answers saved as data" failure
in a new costume, and worse, because it is perfectly reproducible: a
retry returns the same zeros, so counting and retrying cannot catch it.
Only an adds-up check can, which is why `check_adds_up` is a halt.

  era "new" (qtrid >= 88, Dec 2015 on): Corp_shpSec_SHPSUMMARY_ng
      category holding + Fld_NoOfShareHolders + pledge + total shares,
      and Fld_AuthoriseDate as the filing timestamp.
  era "old" (qtrid 65..87, Mar 2010 .. Sep 2015): Corp_ShpPromoters_ng
      promoter entities, shares, percent and pledged shares. No
      category breakdown and no shareholder counts exist here in
      structured form; those fields are written unavailable, not zero.

Schema:
  data/bse_shareholding/summary.parquet   one row per (scrip_code, qtrid)
  data/bse_shareholding/categories.parquet one row per (scrip, qtrid, category)
  data/bse_shareholding/_verified.txt      ledger of completed scrip-quarters
  data/bse_shareholding/_log.jsonl         failures, with reasons
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir
from pflab.data.bse_announcements import HEADERS

BASE = "https://api.bseindia.com/BseIndiaAPI/api"
URL_QTRINFO = BASE + "/Corp_shpSec_shpqtrinfo_ng/w"
URL_SUMMARY = BASE + "/Corp_shpSec_SHPSUMMARY_ng/w"
URL_PROMOTERS = BASE + "/Corp_ShpPromoters_ng/w"

QTRID_2010Q1 = 65           # March 2010, verified against Corp_shpSec_shpqtrinfo_ng
QTRID_NEW_ERA = 88          # December 2015: the SEBI format begins
QTRID_MAX = 130             # June 2026

# adds-up tolerances (halt thresholds, not warnings)
PCT_TOTAL_TOLERANCE = 1.0   # |A+B+C2 - 100| must not exceed this
DERIVE_MIN_PCT = 0.005      # below this a derived total is meaningless

SUMMARY_COLUMNS = [
    "scrip_code", "qtrid", "quarter_end", "era", "status", "reason",
    "promoter_pct", "promoter_shares", "public_pct", "public_shares",
    "nonpromoter_nonpublic_pct", "nonpromoter_nonpublic_shares",
    "pledged_shares", "pledged_pct_of_promoter", "pledged_pct_of_total",
    "n_shareholders_promoter", "n_shareholders_public", "n_shareholders_total",
    "shares_outstanding_reported", "shares_outstanding_derived",
    "shares_outstanding_derivation", "derived_implied_error_pct",
    "filing_date", "filing_date_source", "collected_at",
]
CATEGORY_COLUMNS = [
    "scrip_code", "qtrid", "quarter_end", "code", "category", "subcategory",
    "short_name", "n_shareholders", "shares", "pct_of_total",
    "pledged_shares", "pledged_pct", "is_subtotal",
]


class ShareholdingUnavailable(RuntimeError):
    """The source has no usable record for this scrip-quarter.

    Raised for a genuinely absent filing AND for the zero-filled skeleton.
    The caller records the scrip-quarter as unavailable with the reason and
    counts it; it never writes a number.
    """


class AddsUpFailure(ShareholdingUnavailable):
    """The record does not reconcile, so it is not a record.

    Separate from the plain absence above so the two are counted apart: a
    jump in this one is a finding about BSE's data, not about coverage.
    """


def latest_qtrid(today: Optional[date] = None, lag_days: int = 21) -> int:
    """S63: the newest quarter whose filings are due by `today` (SEBI: 21 days after the quarter end)."""
    today = today or date.today()
    q = QTRID_2010Q1 + (today.year - 2010) * 4 + (today.month - 1) // 3
    while (today - quarter_end(q)).days < lag_days:
        q -= 1
    return q


def quarter_end(qtrid: int) -> date:
    """Quarter-end date for a BSE quarter id. 65 -> 2010-03-31."""
    n = int(round(qtrid)) - QTRID_2010Q1        # 0 = 2010Q1 (Jan-Mar)
    year = 2010 + n // 4
    month = (n % 4 + 1) * 3
    last = {3: 31, 6: 30, 9: 30, 12: 31}[month]
    return date(year, month, last)


def era_of(qtrid: int) -> str:
    return "new" if int(round(qtrid)) >= QTRID_NEW_ERA else "old"


def _get(url: str, params: dict, session: requests.Session, timeout: int) -> dict:
    r = session.get(url, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    try:
        j = r.json()
    except ValueError:
        raise ShareholdingUnavailable(f"non-JSON answer from {url}")
    return j if isinstance(j, dict) else {"_list": j}


def _f(row: dict, key: str, default=None):
    v = row.get(key, default)
    return default if v is None else v


def _pledge(row: dict, key: str, cast):
    """A pledge figure as filed: 0 only when the filing reports nil (a
    numeric 0); null, blank or absent stays None, never 0 (E5-A §14
    2026-10-01). A 200-quarter sample of the API found no null."""
    v = row.get(key)
    if v is None or str(v).strip() == "":
        return None
    return cast(v)


# Fld_Code values in the SEBI-format Table1. The table mixes COMPONENTS with
# SUBTOTALS and a GRAND TOTAL, so summing it double- and triple-counts:
# for Gadget Co Dec-2015 the six rows sum to 6.58bn shares against a real
# 3.24bn. Components are A, B and (C1, C2); C1C2 is their subtotal and ABC
# is the grand total. Only ever read the named row.
CODE_PROMOTER = "STA1A2"       # (A) Promoter & Promoter Group
CODE_PUBLIC = "STB1B2B3"       # (B) Public
CODE_NPNP = "STC1C2"           # (C) Non Promoter-Non Public  = C1 + C2
CODE_TOTAL = "STABC"           # Grand Total (A+B+C)
SUBTOTAL_CODES = {CODE_NPNP, CODE_TOTAL}
OLD_ERA_TOTAL_NAME = "total"   # the promoter table's own trailing Total row


def fetch_new_era(scrip: str, qtrid: int, session: requests.Session,
                  timeout: int = 30) -> tuple:
    """(summary_dict, category_rows) for a SEBI-format quarter, or raise.

    The zero-filled skeleton is caught here: six labelled rows whose shares
    are all zero is what a pre-2016 quarter returns, and it is not data.
    """
    j = _get(URL_SUMMARY, {"scripcode": scrip, "qtrcode": f"{int(qtrid)}.00"},
             session, timeout)
    cats = j.get("Table1") or []
    if not cats:
        raise ShareholdingUnavailable(f"{scrip} q{qtrid}: no Table1")
    by = {r.get("Fld_Code"): r for r in cats}
    if sum(int(_f(r, "Fld_TotalNoOfShares", 0) or 0) for r in cats) == 0:
        raise ShareholdingUnavailable(
            f"{scrip} q{qtrid}: zero-filled skeleton (no SEBI-format filing)")
    grand = by.get(CODE_TOTAL)
    if grand is None:
        raise ShareholdingUnavailable(f"{scrip} q{qtrid}: no {CODE_TOTAL} grand-total row")

    def shares(code):
        r = by.get(code)
        return int(_f(r, "Fld_TotalNoOfShares", 0) or 0) if r else 0

    def pct(code):
        r = by.get(code)
        return float(_f(r, "Fld_TotalPercentageOf_A_B_C2", 0.0) or 0.0) if r else 0.0

    def nsh(code):
        r = by.get(code)
        return int(_f(r, "Fld_NoOfShareHolders", 0) or 0) if r else 0

    prom = by.get(CODE_PROMOTER, {})
    head = (j.get("Table") or [{}])[0]
    # The C1C2 SUBTOTAL row reports its percentage as 0.00 even when C2 is
    # real, so the category percentage must come from the COMPONENTS. Found
    # 2026-09-24: 22 records failed the adds-up check by exactly their C2
    # (shares held by an Employee Trust) -- 500040 by 1.12 pp, 500215 by
    # 4.61, 500214 by 16.18 -- and A + B + C2 comes to 100.00 in every one.
    # The shares on that row ARE right (C1 + C2), so only the percentage is
    # taken from the parts. C1's own percentage is 0.00 by construction:
    # the denominator is A+B+C2, which excludes shares underlying DRs.
    npnp_pct = pct("STC1") + pct("STC2")
    summary = {
        "promoter_pct": pct(CODE_PROMOTER), "promoter_shares": shares(CODE_PROMOTER),
        "public_pct": pct(CODE_PUBLIC), "public_shares": shares(CODE_PUBLIC),
        "nonpromoter_nonpublic_pct": npnp_pct,
        "nonpromoter_nonpublic_shares": shares(CODE_NPNP),
        "pledged_shares": _pledge(prom, "Fld_PledgeEncumberedNoOfShares", int),
        "pledged_pct_of_promoter": _pledge(prom, "Fld_PledgeEncumberedPercentage", float),
        "pledged_pct_of_total": _pledge(prom, "Fld_PledgeEncumberedPercentOfTSC", float),
        "n_shareholders_promoter": nsh(CODE_PROMOTER),
        "n_shareholders_public": nsh(CODE_PUBLIC),
        "n_shareholders_total": nsh(CODE_TOTAL),
        "shares_outstanding_reported": shares(CODE_TOTAL),
        "filing_date": pd.to_datetime(_f(head, "Fld_AuthoriseDate"), errors="coerce"),
        "filing_date_source": "Fld_AuthoriseDate" if _f(head, "Fld_AuthoriseDate") else "unresolved",
    }
    rows = [{
        "code": r.get("Fld_Code"), "category": r.get("FLD_CATEGORY"),
        "subcategory": r.get("FLD_SUBCATEGORY"), "short_name": r.get("Fld_ShortName"),
        "n_shareholders": int(_f(r, "Fld_NoOfShareHolders", 0) or 0),
        "shares": int(_f(r, "Fld_TotalNoOfShares", 0) or 0),
        "pct_of_total": float(_f(r, "Fld_TotalPercentageOf_A_B_C2", 0.0) or 0.0),
        "pledged_shares": _pledge(r, "Fld_PledgeEncumberedNoOfShares", int),
        "pledged_pct": _pledge(r, "Fld_PledgeEncumberedPercentage", float),
        "is_subtotal": r.get("Fld_Code") in SUBTOTAL_CODES,
    } for r in cats]
    return summary, rows


def fetch_old_era(scrip: str, qtrid: int, session: requests.Session,
                  timeout: int = 30) -> tuple:
    """(summary_dict, []) for a pre-2016 quarter from the promoter table.

    The table ends with its own row named "Total"; including it in a sum
    doubles the holding exactly (Gadget Co Mar-2010: 42 rows summing to
    89.52% against a true 44.76%). The Total row is authoritative and the
    entity rows are checked against it.

    Category-wise holding and shareholder counts do not exist here; those
    fields stay None so they read as unavailable rather than zero.
    """
    j = _get(URL_PROMOTERS, {"scripcode": scrip, "qtrid": f"{int(qtrid)}.00"},
             session, timeout)
    rows = j.get("Table") or []
    if not rows:
        # stable across retries in probing, so genuinely absent, not throttling
        raise ShareholdingUnavailable(f"{scrip} q{qtrid}: no promoter rows")
    def nm(r):
        return str(_f(r, "Fld_shareholdername", "") or "").strip().lower()
    totals = [r for r in rows if nm(r) == OLD_ERA_TOTAL_NAME]
    entities = [r for r in rows if nm(r) != OLD_ERA_TOTAL_NAME]
    if totals:
        t = totals[-1]
        shares = int(_f(t, "Fld_NoOfShares", 0) or 0)
        pct = float(_f(t, "Fld_Percentage", 0.0) or 0.0)
        ent_shares = sum(int(_f(r, "Fld_NoOfShares", 0) or 0) for r in entities)
        if shares and abs(ent_shares - shares) > max(1000, 0.001 * shares):
            raise AddsUpFailure(
                f"{scrip} q{qtrid}: promoter entities sum to {ent_shares} "
                f"but the Total row says {shares}")
    else:
        shares = sum(int(_f(r, "Fld_NoOfShares", 0) or 0) for r in entities)
        pct = sum(float(_f(r, "Fld_Percentage", 0.0) or 0.0) for r in entities)
    pl = [_pledge(r, "fld_pledgeencumberednoofshares", int) for r in entities]
    pledged = None if any(v is None for v in pl) else sum(pl)
    summary = {
        "promoter_pct": pct, "promoter_shares": shares,
        "public_pct": None, "public_shares": None,
        "nonpromoter_nonpublic_pct": None, "nonpromoter_nonpublic_shares": None,
        "pledged_shares": pledged,
        "pledged_pct_of_promoter": (100.0 * pledged / shares)
                                   if shares and pledged is not None else None,
        "pledged_pct_of_total": None,
        "n_shareholders_promoter": None, "n_shareholders_public": None,
        "n_shareholders_total": None,
        "shares_outstanding_reported": None,
        "filing_date": pd.NaT, "filing_date_source": "unresolved",
    }
    return summary, []


def check_adds_up(s: dict, era: str) -> None:
    """Halt on a record that is not internally consistent. Raises AddsUpFailure.

    This is the only defence against the zero-filled skeleton and against a
    partially-populated filing, because both parse cleanly.
    """
    pct = s.get("promoter_pct")
    if pct is None or not (0.0 <= float(pct) <= 100.0):
        raise AddsUpFailure(f"promoter_pct {pct!r} outside [0, 100]")
    if era == "new":
        total = s.get("shares_outstanding_reported") or 0
        if total <= 0:
            raise AddsUpFailure(f"shares_outstanding_reported {total!r} is not positive")
        got = (float(s.get("promoter_pct") or 0.0) + float(s.get("public_pct") or 0.0)
               + float(s.get("nonpromoter_nonpublic_pct") or 0.0))
        if abs(got - 100.0) > PCT_TOTAL_TOLERANCE:
            raise AddsUpFailure(f"A+B+C2 = {got:.3f}%, off 100 by more than "
                                f"{PCT_TOTAL_TOLERANCE}")
        if (s.get("promoter_shares") or 0) + (s.get("public_shares") or 0) <= 0:
            raise AddsUpFailure("promoter and public shares are both zero")
        # the grand total must equal its own components, or one of the named
        # rows is not what it claims to be
        comp = ((s.get("promoter_shares") or 0) + (s.get("public_shares") or 0)
                + (s.get("nonpromoter_nonpublic_shares") or 0))
        if abs(comp - total) > max(1000, 0.001 * total):
            raise AddsUpFailure(f"A+B+C shares {comp} != grand total {total}")
    else:
        shares, p = s.get("promoter_shares"), s.get("promoter_pct")
        if not shares or shares <= 0:
            raise AddsUpFailure(f"promoter_shares {shares!r} is not positive")
        if p is None or float(p) <= 0.0:
            raise AddsUpFailure(f"promoter_pct {p!r} is not positive")
    pl = s.get("pledged_shares") or 0
    if pl < 0:
        raise AddsUpFailure(f"pledged_shares {pl!r} is negative")
    if s.get("promoter_shares") and pl > s["promoter_shares"] * 1.001:
        raise AddsUpFailure(f"pledged {pl} exceeds promoter shares {s['promoter_shares']}")


PCT_ROUNDING_HALF_WIDTH = 0.005   # BSE reports promoter percent to 2 decimals


def derive_shares_outstanding(s: dict) -> tuple:
    """(derived, derivation, implied_error_pct) from promoter shares and percent.

    Kept in its OWN column, never merged into the reported one: a reported
    figure is what the company filed, a derived one is arithmetic on a
    rounded percentage. BSE reports the percent to two decimals, so the
    half-width of the rounding interval is 0.005 pp and the implied
    relative error of the derived total is 0.005 / pct -- 0.01% for a 50%
    promoter, but 0.5% for a 1% promoter, which is why the error travels
    with the number. Undefined when promoter holding is zero: there is
    nothing to divide by.
    """
    shares, pct = s.get("promoter_shares"), s.get("promoter_pct")
    if not shares or not pct or float(pct) <= 0.0:
        return None, None, None
    pct = float(pct)
    derived = float(shares) * 100.0 / pct
    err = 100.0 * PCT_ROUNDING_HALF_WIDTH / pct
    return derived, f"promoter_shares / (promoter_pct/100) = {shares} / ({pct}/100)", err


LEDGER = "_verified.txt"


def _ledger_path(root: Path, shard: Optional[int] = None) -> Path:
    name = LEDGER if shard is None else f"_verified.shard{shard}.txt"
    return root / "bse_shareholding" / name


def done_pairs(root: Optional[Path] = None, shard: Optional[int] = None) -> set:
    """Scrip-quarters already settled, as "scrip:qtrid". Makes collect idempotent.

    A pair lands here whether it produced a number or a CONFIRMED
    unavailable, because both are settled answers; a transport failure, or
    an unavailable that did not reconfirm, is left for the next pass.

    Always includes the unsharded ledger, so work done by an earlier
    single-worker run is never repeated when the backfill resumes in shards.
    """
    root = root or data_dir()
    done = set()
    paths = [_ledger_path(root)]
    if shard is not None:
        paths.append(_ledger_path(root, shard))
    for p in paths:
        if p.exists():
            done |= set(p.read_text(encoding="utf-8").split())
    return done


# Reasons a THROTTLED answer could fake. Under parallel load an overloaded
# endpoint can return an empty table instead of refusing, and `collect`
# would then record a real filing as permanently unavailable -- the
# 2026-09-22 "throttled answers saved as data" failure in the one direction
# the adds-up check cannot see, because there is nothing to add up. These
# are re-asked once before being believed.
#
# NOT confirmed: a pre-2016 zero-filled skeleton (structural and
# deterministic -- it reconfirms every time, so confirming it would add a
# request to each of the 23 old-era quarters for nothing), and any
# AddsUpFailure (it carries real numbers, which throttling does not invent).
_ABSENCE_MARKERS = ("no promoter rows", "no Table1", "grand-total row")


def needs_confirmation(reason: Optional[str], qtrid: int) -> bool:
    """True if this 'unavailable' might be a throttled answer, not a fact.

    Narrowed 2026-09-25, on evidence. The rule used to re-ask a zero-filled
    skeleton in the SEBI era on the grounds that a skeleton after Dec 2015
    is unexpected. Measured over the first 110,000 scrip-quarters: **9,850
    of 10,363 unavailable rows were re-asked, 9,121 of them skeletons, and
    not one re-ask ever disagreed** (`unstable` is zero). The cost was about
    four hours of wall clock and rising.

    It was never going to catch anything, because the skeleton is
    SELF-IDENTIFYING: it carries all six correct category labels with zeros
    in every numeric field, which is a shape the endpoint produces only for
    "no filing in this format". A throttled answer does not look like that
    -- under load this endpoint kills the TLS connection (1,103 SSLErrors
    observed, in bursts), or returns an empty or short table. Those are the
    ambiguous shapes, and those are still re-asked.

    So the guard stays exactly where it can distinguish a fact from a
    throttle, and is dropped where the answer identifies itself. This is a
    narrowing on structural grounds, not because the check was inconvenient.
    """
    if not reason:
        return False
    return any(m in reason for m in _ABSENCE_MARKERS)


def _mark(root: Path, scrip: str, qtrid: int, shard: Optional[int] = None) -> None:
    p = _ledger_path(root, shard)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{scrip}:{int(qtrid)}\n")


def collect_one(scrip: str, qtrid: int, session: requests.Session,
                timeout: int = 30) -> tuple:
    """One scrip-quarter: (summary_row, category_rows). Never raises for an
    absent or inconsistent filing -- it returns status 'unavailable' with the
    reason, which is what gets counted."""
    era = era_of(qtrid)
    base = {
        "scrip_code": str(scrip), "qtrid": int(qtrid),
        "quarter_end": quarter_end(qtrid), "era": era,
        "collected_at": datetime.utcnow(),
    }
    try:
        fetch = fetch_new_era if era == "new" else fetch_old_era
        s, cats = fetch(scrip, qtrid, session, timeout)
        check_adds_up(s, era)
    except ShareholdingUnavailable as e:
        row = dict(base, status="unavailable", reason=str(e),
                   **{c: None for c in SUMMARY_COLUMNS
                      if c not in base and c not in ("status", "reason")})
        return row, []
    derived, how, err = derive_shares_outstanding(s)
    row = dict(base, status="ok", reason=None, **s)
    row["shares_outstanding_derived"] = derived
    row["shares_outstanding_derivation"] = how
    row["derived_implied_error_pct"] = err
    for c in cats:
        c.update({"scrip_code": str(scrip), "qtrid": int(qtrid),
                  "quarter_end": quarter_end(qtrid)})
    return row, cats


def _shard_name(stem: str, shard: Optional[int]) -> str:
    return f"{stem}.parquet" if shard is None else f"{stem}.shard{shard}.parquet"


def _flush(root: Path, summaries: list, cats: list, shard: Optional[int] = None) -> None:
    """Append a buffer to this worker's OWN files.

    Each shard writes its own parquet. `_flush` is read-modify-write, so two
    workers sharing one file would interleave and lose rows -- and because
    each writes a valid file, nothing downstream would notice. `merge_shards`
    combines them when the backfill is done.
    """
    d = root / "bse_shareholding"
    d.mkdir(parents=True, exist_ok=True)
    if summaries:
        df = pd.DataFrame(summaries)
        for c in SUMMARY_COLUMNS:
            if c not in df.columns:
                df[c] = None
        df = df[SUMMARY_COLUMNS]
        p = d / _shard_name("summary", shard)
        if p.exists():
            df = pd.concat([pd.read_parquet(p), df], ignore_index=True)
            df = df.drop_duplicates(["scrip_code", "qtrid"], keep="last")
        df.to_parquet(p, index=False)
    if cats:
        df = pd.DataFrame(cats)[CATEGORY_COLUMNS]
        p = d / _shard_name("categories", shard)
        if p.exists():
            df = pd.concat([pd.read_parquet(p), df], ignore_index=True)
            df = df.drop_duplicates(["scrip_code", "qtrid", "code"], keep="last")
        df.to_parquet(p, index=False)


def repair_npnp_pct(root: Optional[Path] = None) -> dict:
    """Re-derive nonpromoter_nonpublic_pct from the stored category rows.

    The C1C2 subtotal reports 0.00% even when C2 (shares held by an
    Employee Trust) is real, so records collected before the 2026-09-24
    parser fix understate that category. Two populations:

      * records recorded `ok` whose error was INSIDE the 1.0 pp tolerance,
        so they carry a wrong number and were never flagged -- the silent
        case, and the reason the tolerance was left alone rather than
        widened;
      * records quarantined as `unavailable` because A+B+C missed 100 by
        more than the tolerance. Those have no category rows stored (a
        failed record writes none), so they cannot be repaired here and are
        released from the ledger to be collected again.

    Checked over 5,968 collected records: summing the components reconciles
    to 100 in 100.00% of them (median deviation 0.0000) against 97.62% for
    the subtotal row, and none then misses by more than 1 pp. The tolerance
    was never the problem.

    Needs no network: the category rows hold the same numbers the fixed
    parser would read.
    """
    root = root or data_dir()
    d = root / "bse_shareholding"
    cats = [pd.read_parquet(f) for f in
            sorted(d.glob("categories.shard*.parquet")) + [d / "categories.parquet"]
            if f.exists()]
    sums = [(f, pd.read_parquet(f)) for f in
            sorted(d.glob("summary.shard*.parquet")) + [d / "summary.parquet"]
            if f.exists()]
    if not cats or not sums:
        return {"repaired": 0, "released": 0}
    c = (pd.concat(cats, ignore_index=True)
           .drop_duplicates(["scrip_code", "qtrid", "code"], keep="last"))
    true = (c[c["code"].isin(["STC1", "STC2"])]
            .groupby(["scrip_code", "qtrid"])["pct_of_total"].sum())

    repaired = released = 0
    for path, s in sums:
        key = list(zip(s["scrip_code"].astype(str), s["qtrid"].astype(int)))
        want = pd.Series([true.get(k, None) for k in key], index=s.index)
        fix = (s["status"] == "ok") & want.notna() & (
            (want.fillna(0) - s["nonpromoter_nonpublic_pct"].fillna(0)).abs() > 1e-9)
        s.loc[fix, "nonpromoter_nonpublic_pct"] = want[fix]
        repaired += int(fix.sum())
        drop = s["reason"].fillna("").str.contains("off 100 by more than")
        released += int(drop.sum())
        s[~drop].to_parquet(path, index=False)
    rebuild_ledger_from_data(root)
    return {"repaired": repaired, "released_for_recollection": released}


def rebuild_ledger_from_data(root: Optional[Path] = None) -> dict:
    """Make the ledger say exactly what the data files contain.

    The ledger is the only thing standing between a gap and a permanent
    gap: a pair listed there is never re-asked. That makes it the one file
    that must not be allowed to drift, and on 2026-09-24 it drifted badly.
    Eighteen workers were started instead of three -- six copies of each
    shard -- so duplicates shared one parquet and one ledger. Two effects,
    both silent:

      * `_flush` is read-modify-write, so one writer's rows were overwritten
        by another's, while BOTH had already appended to the ledger. 972
        scrip-quarters ended up marked settled with no row behind them, and
        nothing would ever have collected them.
      * concurrent appends corrupted the ledger itself, which went
        BACKWARDS (8,400 entries to 4,433).

    The repair is to derive the ledger from the data rather than trust it:
    a pair is settled if and only if a row exists for it. That is
    self-consistent by construction and cannot lose data -- the worst case
    is that a pair is collected twice, which is idempotent.

    Shard ledgers are removed; the single unsharded ledger is authoritative
    afterwards, and `done_pairs` always reads it.
    """
    root = root or data_dir()
    d = root / "bse_shareholding"
    pairs = set()
    for p in sorted(d.glob("summary*.parquet")):
        df = pd.read_parquet(p, columns=["scrip_code", "qtrid"])
        pairs |= {f"{s}:{int(q)}" for s, q in zip(df["scrip_code"].astype(str),
                                                  df["qtrid"])}
    claimed = set()
    for p in sorted(d.glob("_verified*.txt")):
        claimed |= set(p.read_text(encoding="utf-8").split())
    for p in sorted(d.glob("_verified.shard*.txt")):
        p.unlink()
    (d / LEDGER).write_text("\n".join(sorted(pairs)) + "\n", encoding="utf-8")
    return {"settled_from_data": len(pairs),
            "was_claimed": len(claimed),
            "orphans_dropped": len(claimed - pairs),
            "unclaimed_recovered": len(pairs - claimed)}


def shard_of(scrip: str, n: int) -> int:
    """Which worker owns a scrip. Deterministic, so a restart keeps the split
    and two workers can never touch the same scrip-quarter."""
    return int(scrip) % n if str(scrip).isdigit() else hash(str(scrip)) % n


def merge_shards(root: Optional[Path] = None) -> dict:
    """Combine every shard (and any unsharded legacy file) into the canonical
    summary.parquet / categories.parquet. Safe to run while workers run: it
    only reads their files."""
    root = root or data_dir()
    d = root / "bse_shareholding"
    out = {}
    for stem, keys in (("summary", ["scrip_code", "qtrid"]),
                       ("categories", ["scrip_code", "qtrid", "code"])):
        parts = []
        for p in sorted(d.glob(f"{stem}.shard*.parquet")) + [d / f"{stem}.parquet"]:
            if p.exists():
                parts.append(pd.read_parquet(p))
        if not parts:
            continue
        df = pd.concat(parts, ignore_index=True).drop_duplicates(keys, keep="last")
        df.to_parquet(d / f"{stem}.parquet", index=False)
        out[stem] = len(df)
    ledger = set()
    for p in sorted(d.glob("_verified.shard*.txt")) + [d / LEDGER]:
        if p.exists():
            ledger |= set(p.read_text(encoding="utf-8").split())
    (d / LEDGER).write_text("\n".join(sorted(ledger)) + "\n", encoding="utf-8")
    out["settled"] = len(ledger)
    return out


def _log(root: Path, scrip: str, qtrid: int, message: str,
         shard: Optional[int] = None) -> None:
    # Per shard. Three workers appending to one _log.jsonl interleaved their
    # writes and corrupted 26 of 1,166 lines (2026-09-25) -- the same defect
    # the ledger had, in a file nobody reads until something has gone wrong,
    # which is the worst place for it.
    name = "_log.jsonl" if shard is None else f"_log.shard{shard}.jsonl"
    lp = root / "bse_shareholding" / name
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, "a", encoding="utf-8") as f:
        f.write(json.dumps({"scrip": scrip, "qtrid": qtrid, "error": message,
                            "ts": datetime.utcnow().isoformat()}) + "\n")


def collect(scrips, qtrid_from: int = QTRID_2010Q1, qtrid_to: int = QTRID_MAX,
            root: Optional[Path] = None, sleep: float = 0.35,
            flush_every: int = 500, progress=None, shard: Optional[int] = None,
            confirm_sleep: float = 0.5, retries: int = 3,
            retry_backoff: float = 2.0) -> dict:
    """Backfill shareholding for `scrips` over a quarter range. Idempotent.

    Safe to run in parallel **only** as disjoint shards: pass `shard`, give
    each worker the scrips `shard_of` assigns it, and each writes its own
    parquet and its own ledger. Two workers sharing one output file would
    interleave read-modify-write and silently lose rows.

    Parallelism raises a hazard the single-worker version did not have. The
    BSE announcements backfill found that four workers draw throttled
    answers and three do not; a throttled shareholding answer can arrive as
    an EMPTY table, which is indistinguishable from "this company filed
    nothing" and would be ledgered as a permanent `unavailable`. So an
    unavailable whose reason could be faked by throttling (`needs_confirmation`)
    is **re-asked once** before it is believed. If the second answer differs,
    nothing is written and the pair is left for the next pass.
    """
    root = root or data_dir()
    s = requests.Session()
    done = done_pairs(root, shard)
    stats = {"ok": 0, "unavailable": 0, "adds_up_failed": 0, "error": 0,
             "skipped": 0, "confirmed": 0, "unstable": 0, "rescued": 0,
             "retried_ok": 0}
    buf_s, buf_c, n = [], [], 0
    scrips = [str(x) for x in scrips]
    for scrip in scrips:
        for q in range(int(qtrid_from), int(qtrid_to) + 1):
            if f"{scrip}:{q}" in done:
                stats["skipped"] += 1
                continue
            try:
                row, cats = collect_one(scrip, q, s)
                if row["status"] == "unavailable" and needs_confirmation(row["reason"], q):
                    time.sleep(confirm_sleep)
                    row2, cats2 = collect_one(scrip, q, s)
                    if row2["status"] == "ok":
                        # the first answer was a throttle: the filing is real
                        stats["rescued"] += 1
                        row, cats = row2, cats2
                    elif row2["reason"] != row["reason"]:
                        stats["unstable"] += 1
                        _log(root, scrip, q, f"unstable unavailable: "
                                             f"{row['reason']!r} then {row2['reason']!r}", shard)
                        time.sleep(sleep)
                        continue                 # not settled; next pass retries
                    else:
                        stats["confirmed"] += 1
            except Exception as e:
                # Transport failure. Retry IN PLACE with backoff rather than
                # leaving it for the next pass: under load this endpoint kills
                # TLS connections in bursts (1,103 SSLErrors on 2026-09-25,
                # 786 of them in one hour), and deferring every one of those
                # to a second full sweep costs far more than waiting a few
                # seconds here. A pair that still fails after `retries` is
                # left unledgered, so the next pass does pick it up.
                ok = False
                for attempt in range(retries):
                    time.sleep(retry_backoff * (2 ** attempt))
                    try:
                        row, cats = collect_one(scrip, q, s)
                        stats["retried_ok"] += 1
                        ok = True
                        break
                    except Exception:
                        continue
                if not ok:
                    stats["error"] += 1
                    _log(root, scrip, q, repr(e), shard)
                    time.sleep(sleep)
                    continue
            buf_s.append(row)
            buf_c.extend(cats)
            if row["status"] == "ok":
                stats["ok"] += 1
            else:
                stats["unavailable"] += 1
                if _is_adds_up(row["reason"]):
                    stats["adds_up_failed"] += 1
            _mark(root, scrip, q, shard)
            n += 1
            if len(buf_s) >= flush_every:
                _flush(root, buf_s, buf_c, shard)
                buf_s, buf_c = [], []
                if progress:
                    progress(stats, scrip, q)
            time.sleep(sleep)
    _flush(root, buf_s, buf_c, shard)
    return stats


_ADDS_UP_MARKERS = ("outside [0, 100]", "off 100 by more than", "is not positive",
                    "are both zero", "is negative", "exceeds promoter shares")


def _is_adds_up(reason) -> bool:
    return bool(reason) and any(m in str(reason) for m in _ADDS_UP_MARKERS)


# ---------------------------------------------------------------- filing dates

def filing_dates_from_feed(root: Optional[Path] = None) -> pd.DataFrame:
    """Shareholding-pattern submissions in the announcement feed, by scrip and
    quarter, as a SECOND filing-date source.

    Coverage is uneven because BSE changed its taxonomy twice: the
    subcategory "Shareholding" exists only for 2014-2022 (zero rows in
    2010-2013, effectively zero from 2023). So this fills the middle years
    and cross-checks Fld_AuthoriseDate where both exist; it cannot carry
    the whole span on its own.

    The quarter a filing belongs to is inferred from the filing date, not
    asserted: a pattern disseminated in January reports the December
    quarter. Anything landing more than 150 days after a quarter end is
    left unmatched rather than forced.
    """
    root = root or data_dir()
    base = root / "bse_announcements"
    parts = []
    for f in sorted(base.glob("*/*.parquet")):
        d = pd.read_parquet(f, columns=["scrip_code", "category", "subcategory",
                                        "headline", "dissem_dt"])
        if not len(d):
            continue
        m = (d["subcategory"].str.contains("hold", case=False, na=False)
             | d["headline"].str.contains(r"shareholding pattern|share holding pattern",
                                          case=False, na=False, regex=True))
        if m.any():
            parts.append(d[m])
    if not parts:
        return pd.DataFrame(columns=["scrip_code", "qtrid", "feed_filing_date"])
    a = pd.concat(parts, ignore_index=True)
    a["scrip_code"] = a["scrip_code"].astype(str).str.strip()
    a["dissem_dt"] = pd.to_datetime(a["dissem_dt"], errors="coerce")
    a = a.dropna(subset=["dissem_dt"])
    ends = pd.Series({q: pd.Timestamp(quarter_end(q))
                      for q in range(QTRID_2010Q1, QTRID_MAX + 1)})
    rows = []
    for r in a.itertuples(index=False):
        lag = (r.dissem_dt - ends)
        ok = lag[(lag >= pd.Timedelta(0)) & (lag <= pd.Timedelta(days=150))]
        if len(ok):
            rows.append({"scrip_code": r.scrip_code, "qtrid": int(ok.idxmin()),
                         "feed_filing_date": r.dissem_dt})
    if not rows:
        return pd.DataFrame(columns=["scrip_code", "qtrid", "feed_filing_date"])
    out = pd.DataFrame(rows)
    return (out.sort_values("feed_filing_date")
               .drop_duplicates(["scrip_code", "qtrid"], keep="first")
               .reset_index(drop=True))


def attach_feed_filing_dates(summary: pd.DataFrame, feed: pd.DataFrame) -> pd.DataFrame:
    """Fill unresolved filing dates from the feed, and flag disagreements.

    Fld_AuthoriseDate stays primary where it exists; the feed only fills
    gaps. `filing_date_disagreement_days` is reported, never reconciled --
    two sources differing is a finding.
    """
    df = summary.merge(feed, on=["scrip_code", "qtrid"], how="left")
    has_auth = df["filing_date"].notna()
    df["filing_date_disagreement_days"] = None
    both = has_auth & df["feed_filing_date"].notna()
    df.loc[both, "filing_date_disagreement_days"] = (
        (df.loc[both, "feed_filing_date"] - df.loc[both, "filing_date"])
        .dt.total_seconds() / 86400.0)
    fill = (~has_auth) & df["feed_filing_date"].notna()
    df.loc[fill, "filing_date"] = df.loc[fill, "feed_filing_date"]
    df.loc[fill, "filing_date_source"] = "announcement_feed"
    return df
