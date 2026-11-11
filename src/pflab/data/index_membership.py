"""Point-in-time index membership (charter E1b §3, §4).

E1b replaces E1's top-500-by-traded-value universe with "constituents of the
Nifty 200 as of M". That only means anything if membership is point-in-time:
using today's list over history would make E1b a backtest of the companies
that are in the index NOW, which is the survivorship error principle 6
forbids and would guarantee a flattering result.

The table
---------
    index, isin, symbol, from_date, to_date
`to_date` is None while a name is still a member. `members_at` is the only
way the engine reads it, and it is a half-open window: from_date <= d and
(to_date is None or d < to_date).

Sources
-------
1. CURRENT list -- `archives.nseindia.com/content/indices/ind_*list.csv`,
   which carries ISIN directly. This is the anchor the history is walked back
   from.
2. CHANGE HISTORY -- `pflab.data.index_changes`, parsed from NSE Indices
   press releases. NOT from NSE's F&O "Change in the Constituents of Indices"
   circulars, which cover only derivative-eligible indices and mention Nifty
   200 exactly zero times in twenty years.

Nifty 200 before 2011
---------------------
The Nifty 200 did not exist before 2011, so no source can say who was in it
in 2007. NSE's methodology document defines it exactly:

    "Nifty 200: Constituents forming part of Nifty 100 and Nifty Midcap 100"

-- a union with no further selection and no replacement cap. Nifty 100 changes
are published from 2006 and Nifty Midcap 100 from 2005, so `union_of` rebuilds
Nifty 200 for the pre-2011 years from its own definition rather than carrying
a modern list backwards. The manifest records which years are reconstructed
and which are published, because they are not equally strong evidence.

Validating the walk
-------------------
Each of these indices has a fixed size by construction. A correct
reconstruction therefore holds exactly N names on every date, and
`count_check` reports where it does not. That is a real test of the parse:
a missed or misread change shows up immediately as 199 or 201 members.
"""
from __future__ import annotations

import io
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

import pandas as pd
import requests

from pflab.data import data_dir
from pflab.data.bhavcopy import HEADERS

# NSE has no single naming rule for these files -- the momentum index
# carries an underscore the two broad indices do not -- so the filename is
# stored per index rather than built from a pattern.
CURRENT_LIST_URL = "https://archives.nseindia.com/content/indices/{file}"

INDICES = {"NIFTY200": "ind_nifty200list.csv",
           "NIFTY500": "ind_nifty500list.csv",
           "NIFTY100": "ind_nifty100list.csv",
           "NIFTY_MIDCAP100": "ind_niftymidcap100list.csv",
           # E1b §8 reports overlap of holdings with the momentum fund's own
           # constituents; it is never a universe, only a yardstick.
           "NIFTY200_MOMENTUM30": "ind_nifty200Momentum30_list.csv"}

COLUMNS = ["index", "isin", "symbol", "from_date", "to_date"]
# How each end of a window was established. A window both of whose ends came
# from a published change is OBSERVED; anything else is inferred, and E1b's
# S12 drops the inferred ones so the verdict can see what they were worth.
#   change         a published inclusion/exclusion
#   capture        an archived constituent list pins it: the name is in the
#                  capture on the far side of this end, so the window is
#                  bounded by evidence even though no change notice was found
#   listing_cap    the opening was moved forward to the first traded session,
#                  which is a hard fact about the security
#   carry_back     nothing at all before this point -- no change, no capture
#   inferred_start the name is in this segment's capture but NOT in the
#                  previous one, so it joined somewhere inside the segment and
#                  we placed it at the start. Bounded, but a guess.
#   open           still a member at the as-of date
#   unmatched      the counterpart change was never seen
PROVENANCE = ["from_source", "to_source"]
# A guessed start is not a single date, it is an interval. `from_date` holds
# the EARLIEST the name can have joined (the segment start) and
# `from_date_latest` the LATEST (the capture that first shows it as a member).
# The base row runs on the earliest and S12 on the latest, so the two bracket
# the truth instead of one of them standing in for it.
BOUNDS = ["from_date_latest"]
# Ends that rest on evidence rather than on a guess.
OBSERVED = {"change", "capture", "listing_cap"}
INFERRED = {"carry_back", "inferred_start", "unmatched"}

# A carry-back beyond this is a survivorship problem, not a declared gap.
MAX_CARRY_BACK_DAYS = 400

# NSE methodology, September 2026: "Nifty 200 -- Constituents forming part of
# Nifty 100 and Nifty Midcap 100", with no maximum replacements per review.
UNION_DEFINITION = {"NIFTY200": ("NIFTY100", "NIFTY_MIDCAP100")}

# E1b §4, 2026-09-18. Nifty 200 membership is published and exact from here;
# before it the universe is the declared proxy.
PUBLISHED_FROM = date(2012, 1, 1)


class UnresolvedNamesTooMany(RuntimeError):
    """Too many company names in a year could not be keyed to a security."""


class CarryBackTooLong(RuntimeError):
    """The membership history does not reach far enough back to be usable."""


# -- sources -----------------------------------------------------------
def fetch_current(index: str = "NIFTY200", root: Optional[Path] = None,
                  refresh: bool = False) -> pd.DataFrame:
    """Today's constituent list, with ISIN. Cached on disk."""
    if index not in INDICES:
        raise KeyError(f"unknown index {index!r}; known: {sorted(INDICES)}")
    root = root or data_dir()
    cache = root / "index_membership" / "raw" / f"{index}_current.csv"
    if refresh or not cache.exists():
        r = requests.get(CURRENT_LIST_URL.format(file=INDICES[index]),
                         headers=HEADERS, timeout=60)
        r.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(r.content)
    df = pd.read_csv(io.BytesIO(cache.read_bytes()))
    df.columns = [c.strip() for c in df.columns]
    out = df.rename(columns={"Symbol": "symbol", "ISIN Code": "isin",
                             "Company Name": "company", "Series": "series"})
    out["symbol"] = out["symbol"].astype(str).str.strip()
    out["isin"] = out["isin"].astype(str).str.strip()
    return out[["symbol", "isin", "company"]]


# -- assembly ----------------------------------------------------------
def listing_dates(root: Optional[Path] = None,
                  panel: Optional[pd.DataFrame] = None) -> dict:
    """First bhavcopy row per ISIN. The floor on any membership window.

    A name cannot be an index member before it traded. The walk back has no
    way to know that on its own: a name whose inclusion was never published
    falls through to the carry-back and is recorded as a member from the
    start of time, which is how recent listings (NYKAA, 360ONE, AUBANK) ended
    up in the 2005 Nifty Midcap 100.

    The floor is the first row IN THE PANEL, not the true listing date, so for
    a name that listed before the panel starts it is the panel start. That is
    the right bound anyway: with no prices there is no eligibility.

    Two keys, and both are needed. Keyed on ISIN alone a split looks like a
    new listing -- Bombay Burmah's post-split ISIN first trades in 2012 while
    the symbol BBTC goes back to the start of the panel -- which would cut a
    long-standing member out of every earlier year. 197 of Nifty 500's 1,292
    windows are in that position. The floor is therefore the EARLIER of the
    two, which a split cannot move and a rename cannot move either.
    """
    if panel is None:
        root = root or data_dir()
        panel = pd.read_parquet(root / "panel" / "prices.parquet",
                                columns=["date", "isin", "symbol"])
    d = panel[["date", "isin", "symbol"]].copy()
    d["date"] = pd.to_datetime(d["date"]).dt.date
    return {"by_isin": d.groupby("isin")["date"].min(),
            "by_symbol": d.groupby("symbol")["date"].min()}


def _cap_at_listing(table: pd.DataFrame, listing) -> tuple:
    """Clamp each window's start to the name's first traded session."""
    if not listing or table.empty:
        return table, {"capped": 0, "dropped": 0, "no_listing_date": 0}
    by_isin = listing.get("by_isin")
    by_symbol = listing.get("by_symbol")
    fi = table["isin"].map(by_isin) if by_isin is not None else None
    fs = table["symbol"].map(by_symbol) if by_symbol is not None else None

    floors = []
    for i in range(len(table)):
        cands = [x for x in ((fi.iloc[i] if fi is not None else None),
                             (fs.iloc[i] if fs is not None else None))
                 if x is not None and not pd.isna(x)]
        floors.append(min(cands) if cands else None)

    unknown = sum(1 for f in floors if f is None)
    capped = sum(1 for f, g in zip(floors, table["from_date"])
                 if f is not None and f > g)
    table = table.copy()
    moved = [f is not None and f > g for f, g in zip(floors, table["from_date"])]
    table["from_date"] = [g if (f is None or f <= g) else f
                          for f, g in zip(floors, table["from_date"])]
    if "from_source" in table.columns:
        table["from_source"] = [("listing_cap" if m else v)
                                for m, v in zip(moved, table["from_source"])]
    if "from_date_latest" in table.columns:
        # a name cannot have joined before it traded on either bound
        table["from_date_latest"] = [max(a, b) for a, b in
                                     zip(table["from_date_latest"],
                                         table["from_date"])]
    # a window that ended before the name ever traded is not a window
    keep = table["to_date"].isna() | (table["to_date"] > table["from_date"])
    dropped = int((~keep).sum())
    return (table[keep].reset_index(drop=True),
            {"capped": int(capped), "dropped": dropped,
             "no_listing_date": int(unknown)})



def _key_for(change: dict, name_map=None, symbol_isin=None) -> dict:
    """One change -> {"isin", "symbol", "reason"}.

    The press releases from 2011 on carry a Symbol column, so the normal path
    is symbol + date -> ISIN through the date-ranged map, exactly as CLAUDE.md
    8 requires. The older releases print the company name only; those go
    through the name map, which resolves to a symbol first and then takes the
    same date-ranged path.
    """
    eff = change.get("effective")
    sym = change.get("symbol")
    if sym:
        isin = _isin_for(sym, eff, symbol_isin)
        return {"isin": isin, "symbol": sym,
                "reason": "symbol" if isin else "symbol not in map"}
    if name_map is None or not len(name_map):
        return {"isin": None, "symbol": None, "reason": "no symbol, no name map"}
    from pflab.data import name_map as nm
    r = nm.resolve(change.get("company") or "", name_map, on=eff,
                   symbol_isin=symbol_isin)
    if r["symbol"] and symbol_isin is not None and eff is not None:
        dated = _isin_for(r["symbol"], eff, symbol_isin)
        if dated:
            return {"isin": dated, "symbol": r["symbol"], "reason": "name->symbol"}
    return {"isin": r["isin"], "symbol": r["symbol"],
            "reason": f"name:{r['reason']}"}


def build(index: str = "NIFTY200", changes=None,
          current: Optional[pd.DataFrame] = None, start: date = date(2005, 1, 1),
          asof: Optional[date] = None, symbol_isin: Optional[pd.DataFrame] = None,
          name_map=None, allow_long_carry_back: bool = False,
          unresolved_year_tolerance: float = 0.02,
          listing: Optional[dict] = None) -> tuple:
    """Walk the current list backwards through the changes. (table, manifest).

    A change is applied in reverse: a name INCLUDED on date d was not a member
    before d, and a name EXCLUDED on d was one until d.

    Charter E1b §3 as amended 2026-09-17: a year with more than
    `unresolved_year_tolerance` of its changes unresolved HALTS the build. A
    quiet partial answer here is worse than none -- it would put roughly the
    right names in the universe and nobody would notice the difference.
    """
    asof = asof or date.today()
    current = fetch_current(index) if current is None else current
    if isinstance(changes, pd.DataFrame):
        changes = changes.to_dict("records")
    changes = [c for c in (changes or [])
               if c.get("index") == index and c.get("effective")]
    changes.sort(key=lambda c: c["effective"], reverse=True)

    # Keyed by a STABLE company id, not by symbol. A symbol that was renamed
    # between the change and today never matches its own entry, so the walk
    # back emits a second window instead of closing the first and the index
    # reconstructs with more members than it can have. `count_check` is what
    # made this visible: Nifty 200 came back with ~240 names, never 200.
    live: Dict[str, dict] = {}
    for r in current.itertuples(index=False):
        live[_company_id(r.symbol, r.isin, symbol_isin)] = {
            "isin": r.isin, "symbol": r.symbol, "to_date": None,
            "to_source": "open"}
    rows: List[dict] = []
    unresolved: List[dict] = []
    unmatched_includes: List[dict] = []
    unmatched_excludes: List[dict] = []
    for c in changes:
        k = _key_for(c, name_map, symbol_isin)
        sym, eff = k["symbol"], c["effective"]
        if not sym:
            unresolved.append({"effective": str(eff), "company": c.get("company"),
                               "symbol": c.get("symbol"), "reason": k["reason"],
                               "index": index, "source_file": c.get("source_file")})
            continue
        cid = _company_id(sym, k["isin"], symbol_isin)
        action = str(c["action"]).lower()
        if action.startswith("includ"):
            cur = live.pop(cid, None)
            if cur is None:
                # We are told this name JOINED on `eff`, but walking back from
                # today we never saw it leave and it is not a member now. So
                # its exclusion is missing from what we parsed. Emitting the
                # window anyway means `to_date=None` -- a name that joins and
                # never leaves -- which inflates every later date by one and
                # is invisible. Recording it instead is what makes
                # `count_check` able to say how much of the history is missing.
                unmatched_includes.append(
                    {"effective": str(eff), "symbol": sym,
                     "company": c.get("company"), "index": index,
                     "source_file": c.get("source_file")})
                continue
            rows.append({"index": index,
                         "isin": cur.get("isin") or k["isin"],
                         "symbol": sym, "from_date": eff,
                         "to_date": cur.get("to_date"),
                         "from_source": "change",
                         "to_source": cur.get("to_source", "open")})
        elif action.startswith("exclud"):
            prior = live.get(cid)
            if prior is not None:
                # Two exclusions with no inclusion between them: the inclusion
                # in the middle was missed.
                unmatched_excludes.append(
                    {"effective": str(eff), "symbol": sym,
                     "company": c.get("company"), "index": index,
                     "source_file": c.get("source_file")})
                if prior.get("to_date") is None:
                    # The name is a member TODAY and we are being told it was
                    # excluded on `eff`, so it rejoined afterwards and we did
                    # not see that. Overwriting would close its open window and
                    # drop a name that is in the index right now -- which shows
                    # up as the anchor itself being wrong. Emit the open span
                    # with `eff` as its earliest possible start instead.
                    rows.append({"index": index,
                                 "isin": prior.get("isin") or k["isin"],
                                 "symbol": prior.get("symbol") or sym,
                                 "from_date": eff, "to_date": None,
                                 "from_source": "unmatched",
                                 "to_source": "open"})
            live[cid] = {"isin": k["isin"], "symbol": sym, "to_date": eff,
                         "to_source": "change"}
        else:
            unresolved.append({"effective": str(eff), "company": c.get("company"),
                               "symbol": sym, "reason": f"unknown action {action!r}",
                               "index": index, "source_file": c.get("source_file")})

    by_year = _unresolved_by_year(changes, unresolved)
    breaches = {y: v for y, v in by_year.items()
                if v["share"] > unresolved_year_tolerance}
    if breaches:
        worst = sorted(breaches.items(), key=lambda kv: -kv[1]["share"])[:5]
        raise UnresolvedNamesTooMany(
            f"{index}: {len(breaches)} year(s) exceed the "
            f"{unresolved_year_tolerance:.0%} unresolved-name tolerance "
            f"(E1b §3, amended 2026-09-17): "
            + ", ".join(f"{y} {v['unresolved']}/{v['changes']}" for y, v in worst)
            + ". Verify them in PFLAB_DATA_DIR/index_membership/unresolved.md and extend "
              "the name map; do not lower the tolerance.")

    history_start = min((c["effective"] for c in changes), default=None)
    carry_from = history_start or asof
    carry_back_days = (carry_from - start).days
    if carry_back_days > MAX_CARRY_BACK_DAYS and not allow_long_carry_back:
        raise CarryBackTooLong(
            f"{index}: membership history begins {carry_from}, so the earliest "
            f"list would be carried back {carry_back_days} days "
            f"({carry_back_days/365:.1f} years) to {start}. E1b §4 allows a "
            f"declared gap, but a carry-back this long makes the universe "
            f"'names in the index today', which is the survivorship error "
            f"principle 6 forbids. Pass allow_long_carry_back=True only with a "
            f"§15 line saying why.")

    # `live` is keyed by company id, not by symbol -- the symbol lives in the
    # value. Using the key here wrote an ISIN into the symbol column for every
    # carried-back row.
    for v in live.values():
        rows.append({"index": index, "isin": v["isin"], "symbol": v["symbol"],
                     "from_date": start, "to_date": v["to_date"],
                     "from_source": "carry_back",
                     "to_source": v.get("to_source", "open")})

    table = pd.DataFrame(rows, columns=COLUMNS + PROVENANCE)
    table["from_date_latest"] = table["from_date"]
    dropped = int(table["isin"].isna().sum())
    table = table[table["isin"].notna()].reset_index(drop=True)
    table, cap = _cap_at_listing(table, listing)
    manifest = {
        "index": index,
        "method": "published changes walked back from the current list",
        "members_current": int(len(current)),
        "changes_applied": len(changes) - len(unresolved),
        "changes_seen": len(changes),
        "unresolved": len(unresolved),
        "unresolved_by_year": by_year,
        "unresolved_tolerance": unresolved_year_tolerance,
        # each of these is one change the parse did not see; they are the
        # honest measure of how complete the reconstruction is
        "unmatched_includes": len(unmatched_includes),
        "unmatched_excludes": len(unmatched_excludes),
        "unmatched_sample": (unmatched_includes[:10] + unmatched_excludes[:10]),
        "rows_dropped_no_isin": dropped,
        "listing_cap": cap,
        "history_starts": str(history_start) if history_start else None,
        "carry_back_from": str(carry_from),
        "carry_back_to": str(start),
        "carry_back_days": carry_back_days,
        "carry_back_years": round(carry_back_days / 365.25, 2),
        "rows": int(len(table)),
    }
    return table, manifest, unresolved


def _unresolved_by_year(changes, unresolved) -> dict:
    tot: Dict[int, int] = {}
    bad: Dict[int, int] = {}
    for c in changes:
        y = c["effective"].year
        tot[y] = tot.get(y, 0) + 1
    for u in unresolved:
        y = int(str(u["effective"])[:4])
        bad[y] = bad.get(y, 0) + 1
    return {y: {"changes": n, "unresolved": bad.get(y, 0),
                "share": round(bad.get(y, 0) / n, 4)}
            for y, n in sorted(tot.items())}


def union_of(parts: List[pd.DataFrame], index: str,
             sources: List[str]) -> pd.DataFrame:
    """Rebuild an index that is defined as the union of others (E1b §4).

    NSE's methodology defines Nifty 200 as "Constituents forming part of Nifty
    100 and Nifty Midcap 100" -- not a selection from them, the union of them
    -- so for the years before Nifty 200 was published its membership is
    derivable rather than guessable. Overlapping windows for the same ISIN are
    merged, because a name that moves from Nifty 100 to Nifty Midcap 100 never
    leaves Nifty 200.
    """
    keep = []
    for df, src in zip(parts, sources):
        d = df[df["index"] == src].copy()
        keep.append(d)
    if not keep:
        return pd.DataFrame(columns=COLUMNS)
    d = pd.concat(keep, ignore_index=True)
    d["index"] = index
    out = []
    for isin, g in d.groupby("isin", sort=False):
        spans = sorted(((r.from_date, r.to_date,
                         getattr(r, "from_source", "change"),
                         getattr(r, "to_source", "open"),
                         getattr(r, "from_date_latest", r.from_date))
                        for r in g.itertuples(index=False)),
                       key=lambda x: (x[0], x[1] or date.max))
        cur_from, cur_to, cur_fs, cur_ts, cur_fl = spans[0]
        sym = g["symbol"].iloc[0]
        for f, t, fs, ts, fl in spans[1:]:
            if cur_to is None or f <= cur_to:          # touching or overlapping
                cur_to = None if (cur_to is None or t is None) else max(cur_to, t)
                # a merged window is only observed if both parts were
                cur_ts = ts if (cur_to is not None and t == cur_to) else cur_ts
                if fs not in OBSERVED:
                    cur_fs = cur_fs if cur_fs not in OBSERVED else fs
            else:
                out.append({"index": index, "isin": isin, "symbol": sym,
                            "from_date": cur_from, "to_date": cur_to,
                            "from_source": cur_fs, "to_source": cur_ts,
                            "from_date_latest": cur_fl})
                cur_from, cur_to = f, t
                cur_fs, cur_ts, cur_fl = fs, ts, fl
        out.append({"index": index, "isin": isin, "symbol": sym,
                    "from_date": cur_from, "to_date": cur_to,
                    "from_source": cur_fs, "to_source": cur_ts,
                    "from_date_latest": cur_fl})
    return pd.DataFrame(
        out, columns=COLUMNS + PROVENANCE + BOUNDS).reset_index(drop=True)


def splice(reconstructed: pd.DataFrame, published: pd.DataFrame, index: str,
           cutover: date) -> pd.DataFrame:
    """One table from a reconstructed era and a published one (E1b §4).

    Before `cutover` the membership is derived (Nifty 200 = Nifty 100 union
    Nifty Midcap 100); from `cutover` it is what NSE published. Each side is
    clipped to its own era so neither can speak for the other, and the two are
    then merged per ISIN so a name that spans the boundary keeps one window
    rather than appearing to leave and rejoin on the cutover date.
    """
    a = reconstructed[reconstructed["index"] == index].copy()
    a = a[a["from_date"] < cutover]
    a["to_date"] = a["to_date"].map(
        lambda t: cutover if (t is None or pd.isna(t) or t > cutover) else t)

    b = published[published["index"] == index].copy()
    b["from_date"] = b["from_date"].map(lambda f: max(f, cutover))
    b = b[(b["to_date"].isna()) | (b["to_date"] > b["from_date"])]

    both = pd.concat([a, b], ignore_index=True)
    return union_of([both], index, [index])


def build_segmented(index: str, changes, anchors, start: date,
                    asof: date, symbol_isin=None, name_map=None,
                    listing=None) -> tuple:
    """Walk back from EVERY anchor, not just from the present (E1b §4).

    `anchors` is [(date, DataFrame with symbol+isin), ...] ascending, ending
    with the current list at `asof`. Each adjacent pair defines a segment, and
    the walk back inside a segment starts from that segment's own captured
    list.

    Why this matters: with a single anchor at the present, one missed change
    in 2013 is wrong for every date before 2013 -- the error compounds over
    twenty years. Anchored every couple of years, the same missed change is
    wrong only inside its own segment, and the segments either side are
    unaffected. It also turns the reconstruction into something falsifiable:
    every anchor is a date where the answer is known exactly.
    """
    if isinstance(changes, pd.DataFrame):
        changes = changes.to_dict("records")
    changes = [c for c in changes
               if c.get("index") == index and c.get("effective")]
    anchors = sorted(anchors, key=lambda a: a[0])
    if not anchors:
        raise ValueError(f"{index}: build_segmented needs at least one anchor")

    from datetime import timedelta
    parts, manifests, unresolved = [], [], []
    for i, (a_date, a_list) in enumerate(anchors):
        prev = anchors[i - 1][0] if i > 0 else None
        seg_start = (prev + timedelta(days=1)) if prev else start
        # `members_at` is half-open, so a window that must INCLUDE the anchor
        # date has to end the day after it. Without that the next segment,
        # which starts on the anchor date, would answer for it -- and the
        # capture taken that day is the one thing we know for certain.
        seg_end_excl = a_date + timedelta(days=1)
        seg = [c for c in changes if seg_start <= c["effective"] <= a_date]
        t, man, un = build(index, seg, current=a_list, start=seg_start,
                           asof=a_date, symbol_isin=symbol_isin,
                           name_map=name_map, allow_long_carry_back=True,
                           listing=listing, unresolved_year_tolerance=1.0)
        manifests.append({"anchor": str(a_date), "span": f"{seg_start}..{a_date}",
                          **_seg_stats(man, seg)})
        if t.empty:
            continue
        t = t.copy()
        # nothing a segment says may reach outside its own span
        t["from_date"] = [max(f, seg_start) for f in t["from_date"]]
        # A carry-back inside a segment means "no inclusion was found". That is
        # evidence if the PREVIOUS capture also holds the name -- it was
        # already a member -- and a guess if it does not, because then it
        # joined somewhere inside this segment and we placed it at the start.
        prev_isins = (set(anchors[i - 1][1]["isin"]) if i > 0 else None)
        t["from_source"] = [
            ("carry_back" if (prev_isins is None and v == "carry_back") else
             ("capture" if (v == "carry_back" and isin in prev_isins) else
              ("inferred_start" if v == "carry_back" else v)))
            for v, isin in zip(t["from_source"], t["isin"])]
        # A guessed start is bounded by its own segment: the name is absent
        # from the previous capture and present in this one, so it joined
        # after `seg_start` and by `a_date`.
        # Every inferred start is bounded above by this segment's capture: the
        # name is in that list, so it had joined by then. `carry_back` (nothing
        # at all before the first capture) and `unmatched` (rejoined after an
        # exclusion we saw) are bounded the same way, just more widely.
        t["from_date_latest"] = [
            (a_date if v in INFERRED else f)
            for v, f in zip(t["from_source"], t["from_date"])]
        is_last = (i == len(anchors) - 1)
        clipped = [not (is_last and (x is None or pd.isna(x)))
                   and (x is None or pd.isna(x) or x > seg_end_excl)
                   for x in t["to_date"]]
        t["to_date"] = [
            (None if (is_last and (x is None or pd.isna(x))) else
             (seg_end_excl if (x is None or pd.isna(x) or x > seg_end_excl) else x))
            for x in t["to_date"]]
        # A window still open at the anchor was open BECAUSE the name is in
        # that capture, so the clip is pinned by evidence, not invented.
        if "to_source" in t.columns:
            t["to_source"] = [("capture" if c else v)
                              for c, v in zip(clipped, t["to_source"])]
        t = t[t["to_date"].isna() | (t["to_date"] > t["from_date"])]
        parts.append(t)
        unresolved.extend(un)

    table = (union_of([pd.concat(parts, ignore_index=True)], index, [index])
             if parts else pd.DataFrame(columns=COLUMNS))
    manifest = {
        "index": index,
        "method": "walked back from every capture, segment by segment",
        "anchors": len(anchors),
        "anchor_dates": [str(a[0]) for a in anchors],
        "segments": manifests,
        "changes_seen": len(changes),
        "unresolved": len(unresolved),
        "rows": int(len(table)),
        "first_anchor": str(anchors[0][0]),
        "carry_back_from": str(anchors[0][0]),
        "carry_back_to": str(start),
        "carry_back_days": (anchors[0][0] - start).days,
    }
    return table, manifest, unresolved


def _seg_stats(man: dict, seg) -> dict:
    return {"changes": len(seg),
            "applied": man.get("changes_applied"),
            "unmatched_includes": man.get("unmatched_includes"),
            "unmatched_excludes": man.get("unmatched_excludes"),
            "rows": man.get("rows")}


def anchors_for(index: str, captures: Optional[dict], asof: date,
                current: Optional[pd.DataFrame] = None) -> list:
    """[(date, list)] ascending: every capture, then today's list at `asof`."""
    out = []
    for d, df in sorted(((captures or {}).get(index) or {}).items()):
        if d <= asof:
            out.append((d, df))
    cur = fetch_current(index) if current is None else current
    out = [x for x in out if x[0] < asof]
    out.append((asof, cur))
    return out


def build_index(index: str, changes, start: date, asof: date,
                captures: Optional[dict] = None, symbol_isin=None,
                name_map=None, listing=None) -> tuple:
    """One index, anchored on every capture there is."""
    return build_segmented(index, changes,
                           anchors_for(index, captures, asof),
                           start=start, asof=asof, symbol_isin=symbol_isin,
                           name_map=name_map, listing=listing)


def build_nifty200(changes, symbol_isin=None, name_map=None,
                   start: date = date(2005, 1, 1), asof: Optional[date] = None,
                   cutover: Optional[date] = None,
                   listing: Optional[dict] = None,
                   captures: Optional[dict] = None) -> tuple:
    """Nifty 200 across both eras (E1b §4). (table, manifest).

    NSE published no Nifty 200 constituent change before 2011 because the
    index did not exist. Its methodology defines it exactly -- "Constituents
    forming part of Nifty 100 and Nifty Midcap 100" -- so the earlier years
    are DERIVED from the two parents rather than carried back from a modern
    list, which is what principle 6 forbids.

    Nifty 200 itself is captured only from 2017, but BOTH parents are captured
    from 2006, so the pre-2011 union is anchored even where Nifty 200 is not.

    The manifest records which era each year came from, because a
    reconstructed year and a published year are not equally strong evidence
    and the verdict has to be able to say so.
    """
    if isinstance(changes, pd.DataFrame):
        changes = changes.to_dict("records")
    asof = asof or date.today()
    parts, manifests = {}, {}
    for idx in ("NIFTY100", "NIFTY_MIDCAP100", "NIFTY200"):
        t, man, _ = build_index(idx, changes, start, asof, captures,
                                symbol_isin, name_map, listing)
        parts[idx], manifests[idx] = t, man

    # E1b §4 as amended 2026-09-18: the published era starts 2012-01-01, not
    # at the first published change. Nifty 200's own changes begin 2011-11-22
    # but its reconstruction only holds exactly 200 names from 2012, so the
    # calendar boundary is the honest one and it is stated rather than derived.
    cutover = cutover or PUBLISHED_FROM

    union = union_of([parts["NIFTY100"], parts["NIFTY_MIDCAP100"]],
                     "NIFTY200", ["NIFTY100", "NIFTY_MIDCAP100"])
    table = splice(union, parts["NIFTY200"], "NIFTY200", cutover)
    manifest = {
        "index": "NIFTY200",
        "method": "proxy union before the cutover, published from it; "
                  "both eras anchored on Internet Archive captures",
        "eras": {
            "proxy": {
                "span": f"{start} .. {cutover - timedelta(days=1)}",
                "universe": "point-in-time union of CNX 100 and CNX Midcap",
                "declared": ("a PROXY, not the Nifty 200. The two parents "
                             "overlapped by 27-32 names before the 2016 "
                             "restructure, so their union is smaller than the "
                             "index and is not the same universe."),
            },
            "published": {
                "span": f"{cutover} .. {asof}",
                "universe": "Nifty 200 constituents, point-in-time",
                "declared": "published changes, anchored on captures",
            },
        },
        "definition": ("NSE methodology: Nifty 200 = constituents forming part "
                       "of Nifty 100 and Nifty Midcap 100"),
        "cutover": str(cutover),
        "reconstructed_span": f"{start} .. {cutover}",
        "published_span": f"{cutover} .. {asof}",
        "capture_dates": {
            k: ([str(d) for d in sorted(((captures or {}).get(k) or {}))])
            for k in ("NIFTY100", "NIFTY_MIDCAP100", "NIFTY200")},
        "parents": {k: manifests[k] for k in ("NIFTY100", "NIFTY_MIDCAP100")},
        "published_own": manifests["NIFTY200"],
        "rows": int(len(table)),
    }
    return table, manifest


def unbounded(table: pd.DataFrame, index: Optional[str] = None) -> pd.DataFrame:
    """Windows an end of which was never published (E1b §4, residual).

    An end is evidence when a published change gives it, when an archived
    constituent list on the far side pins it, or when the security's first
    traded session bounds it. An end is a guess when the name appears in one
    capture and not the previous one and no change notice explains it: we know
    it joined somewhere inside that segment, and we put it at the start.

    E1b's S12 drops these names so the sweep can show what the guesses were
    worth. Defining this loosely would make S12 meaningless -- under capture
    anchoring almost every window starts at a segment boundary, so counting
    those as unbounded would drop four names in five.
    """
    t = table if index is None else table[table["index"] == index]
    if "from_source" not in t.columns:
        return t.iloc[0:0]
    bad = t["from_source"].isin(INFERRED) | t["to_source"].isin(INFERRED)
    return t[bad]


def unbounded_isins(table: pd.DataFrame, index: Optional[str] = None) -> set:
    return set(unbounded(table, index)["isin"].dropna())


def era_at(d: date, cutover: date = PUBLISHED_FROM) -> str:
    """Which era a decision date falls in (E1b §4)."""
    return "published" if d >= cutover else "proxy"


def era_labels(month_ends, cutover: date = PUBLISHED_FROM) -> dict:
    """Every month-end labelled with the universe it was decided on.

    The manifest carries this because a proxy month and a published month are
    not the same experiment, and a verdict that averages them has to be able
    to say how many of each it averaged.
    """
    labels = {str(d): era_at(d, cutover) for d in month_ends}
    n_proxy = sum(1 for v in labels.values() if v == "proxy")
    return {"cutover": str(cutover),
            "month_ends": len(labels),
            "proxy": n_proxy,
            "published": len(labels) - n_proxy,
            "labels": labels}


def with_bound(table: pd.DataFrame, bound: str = "earliest") -> pd.DataFrame:
    """The membership table read at one end of its uncertainty (E1b §6).

    "earliest" is the table as built: every guessed start sits at the first
    date the name could have joined. "latest" moves each guessed start to the
    last date it could have joined -- the capture that first shows it as a
    member. Neither is more true than the other; running both is what turns an
    unquantified doubt into a bracket the sweep can show.
    """
    if bound == "earliest" or "from_date_latest" not in table.columns:
        return table
    if bound != "latest":
        raise ValueError(f"unknown membership bound {bound!r}")
    t = table.copy()
    t["from_date"] = t["from_date_latest"]
    # a window that the later bound closes entirely is not a window
    return t[t["to_date"].isna() | (t["to_date"] > t["from_date"])
             ].reset_index(drop=True)


def bounds_report(table: pd.DataFrame, index: Optional[str] = None) -> dict:
    """Per name, how wide the uncertainty on its start actually is."""
    t = table if index is None else table[table["index"] == index]
    if "from_date_latest" not in t.columns:
        return {"names": 0, "guessed": 0, "rows": []}
    g = t[t["from_source"].isin(INFERRED)]
    rows = [{"isin": r.isin, "symbol": r.symbol,
             "earliest": str(r.from_date), "latest": str(r.from_date_latest),
             "days": (r.from_date_latest - r.from_date).days,
             "from_source": r.from_source}
            for r in g.itertuples(index=False)]
    widths = [x["days"] for x in rows if x["days"] > 0]
    by_source = {}
    for src in sorted({x["from_source"] for x in rows}):
        w = [x["days"] for x in rows if x["from_source"] == src]
        by_source[src] = {"rows": len(w),
                          "median_days": int(pd.Series(w).median()) if w else 0,
                          "max_days": max(w) if w else 0}
    return {"names": int(t["isin"].nunique()), "guessed": len(rows),
            "with_an_interval": len(widths),
            "median_days": int(pd.Series(widths).median()) if widths else 0,
            "max_days": max(widths) if widths else 0,
            "by_source": by_source,
            "rows": rows}


def count_check(table: pd.DataFrame, index: str, dates,
                expected: Optional[int] = None) -> dict:
    """Member count on each date against the index's fixed size.

    This is the real test of the parse. These indices hold exactly N names by
    construction, so a reconstruction that drifts to 199 or 201 has missed or
    misread a change. It is reported per date rather than raised, because the
    shape of the drift says which change went wrong.
    """
    from pflab.data.index_changes import INDEX_SIZE
    expected = expected or INDEX_SIZE.get(index)
    counts = {d: len(members_at(table, index, d)) for d in dates}
    off = {str(d): n for d, n in counts.items() if expected and n != expected}
    return {"index": index, "expected": expected,
            "dates": len(counts),
            "exact": sum(1 for n in counts.values() if n == expected),
            "off": off,
            "worst": (max((abs(n - expected) for n in counts.values()), default=0)
                      if expected else None),
            "counts": {str(d): n for d, n in counts.items()}}


def _company_id(symbol, isin, symbol_isin: Optional[pd.DataFrame]) -> str:
    """A key that survives a rename and a split.

    Neither symbol nor ISIN is stable on its own: a company can change its
    symbol (GESHIPPING -> GESHIP) and a split issues it a new ISIN. The symbol
    map already follows renames forward into the ISIN era, so the LAST ISIN a
    symbol resolves to is stable across both, and that is used as the identity
    for the walk back. The emitted `isin` column is still the one valid during
    the window -- this key is bookkeeping, never a join key.
    """
    if symbol_isin is not None and len(symbol_isin) and symbol is not None:
        m = symbol_isin[symbol_isin["symbol"] == symbol]
        if len(m):
            return str(m.sort_values("valid_to")["isin"].iloc[-1])
    return str(isin or symbol)


def _isin_for(symbol: str, on, symbol_isin: Optional[pd.DataFrame]):
    """Symbol -> ISIN at a date (CLAUDE.md 8: never join on symbol alone)."""
    if symbol_isin is None or not len(symbol_isin) or symbol is None:
        return None
    m = symbol_isin[symbol_isin["symbol"] == symbol]
    if on is not None:
        w = m[(m["valid_from"] <= on) & (on <= m["valid_to"])]
        if len(w):
            return w["isin"].iloc[0]
    return m["isin"].iloc[0] if len(m) else None


# -- reading -----------------------------------------------------------
def members_at(table: pd.DataFrame, index: str, d: date) -> Set[str]:
    """ISINs that were members of `index` on `d`. Half-open: [from, to)."""
    if table is None or table.empty:
        return set()
    t = table[table["index"] == index]
    to = t["to_date"]
    live = t[(t["from_date"] <= d) & (to.isna() | (pd.notna(to) & (to > d)))]
    return set(live["isin"].dropna())


def assert_no_membership_leak(table: pd.DataFrame, index: str,
                              eligible_by_date: Dict[date, Iterable[str]]) -> None:
    """E1b §3: a name is eligible only between its inclusion and exclusion.

    Raises on the first violation, naming it, rather than reporting a count --
    one leaked name means the universe is wrong on that date.
    """
    for d, names in eligible_by_date.items():
        allowed = members_at(table, index, d)
        bad = sorted(set(names) - allowed)
        if bad:
            raise AssertionError(
                f"{index} {d}: {len(bad)} name(s) eligible outside their "
                f"membership window, e.g. {bad[:5]}")


def write(table: pd.DataFrame, manifest: dict, root: Optional[Path] = None) -> Path:
    import json
    root = root or data_dir()
    d = root / "index_membership"
    d.mkdir(parents=True, exist_ok=True)
    table.to_parquet(d / f"{manifest['index']}.parquet", index=False)
    (d / f"{manifest['index']}_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return d / f"{manifest['index']}.parquet"


def load(index: str = "NIFTY200", root: Optional[Path] = None) -> pd.DataFrame:
    root = root or data_dir()
    return pd.read_parquet(root / "index_membership" / f"{index}.parquet")
