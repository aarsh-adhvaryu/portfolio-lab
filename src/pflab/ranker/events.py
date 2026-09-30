"""E5-A §6(b) feature store, family A1: issuer events per flag and subtype.

§6(b) as amended 2026-09-30 (E5-A §14) and decided 2026-09-30 (A1 plan §5
items 7-8):

  * the events are E2-A's red-flag table (`red_flag_events`), keyed to the
    session each becomes usable (`usable_from`, the after-15:30 rule);
  * each flag has ONE reader. A flag K keeps enters with subtype UNCLEAR on
    every event -- K cannot resolve a subtype, so never AT_COMPANY. A flag L
    reads enters with L's subtype; L's NOT_EVENT is excluded (not an event)
    and a reply with no valid subtype is UNCLEAR, as the contest scored it;
  * UNCLEAR is its own subtype, counted separately;
  * per (flag, subtype): events in the trailing 1, 3 and 12 month-ends
    (usable_from in (M_-k, M]) and month-ends since the last one.

Coverage (§6(b)): an ISIN is covered at M if a BSE scrip resolves to it at M
(`bse_scrip_isin`, date-ranged) and the whole 12-month window lies on or
after 2010-01-01. Uncovered: NaN, `available = false`. Covered with no event:
counts 0, and months-since is censored at the month-ends since the feed's
first month-end (a lower bound, not "never"; a build reading for the lock).

Nothing here reads a row usable after M: every count is over usable_from <= M,
and the store is cut at the period's end by the builder.
"""
from __future__ import annotations

import hashlib
from bisect import bisect_left, bisect_right
from datetime import date, datetime
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from pflab.ranker.features import CLOSE_IST, STORE_COLUMNS, TZ

FLAGS = ("AUDITOR_RESIGNATION", "DEFAULT", "FORENSIC_AUDIT", "FRAUD", "INSOLVENCY",
         "PROMOTER_ENCUMBRANCE", "RATING_DOWNGRADE", "REGULATORY_ACTION",
         "RESULTS_DELAY")
EVENT_SUBTYPES = ("AT_COMPANY", "AGAINST_COMPANY", "RELATED_ENTITY", "UNCLEAR")
WINDOWS = (1, 3, 12)
FEED_START = date(2010, 1, 1)


def event_id(scrip_code, key_dt, flag: str, headline) -> str:
    """Stable id of one (announcement, flag) row: what a reader's reading is
    joined on."""
    s = f"{str(scrip_code).strip()}|{pd.Timestamp(key_dt).isoformat()}|{flag}|{headline or ''}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:20]


def feature_names(assignment: Mapping[str, str]) -> List[str]:
    """The A1 columns, in a fixed order: flags in FLAGS order, then subtype,
    then window. A K flag has only UNCLEAR; an L flag has all four."""
    out = []
    for f in FLAGS:
        subs = EVENT_SUBTYPES if assignment[f] == "L" else ("UNCLEAR",)
        for s in subs:
            stem = f"ev_{f.lower()}_{s.lower()}"
            out += [f"{stem}_{k}m" for k in WINDOWS] + [f"{stem}_since"]
    return out


def check_assignment(assignment: Mapping[str, str]) -> None:
    bad = {f: r for f, r in assignment.items() if r not in ("K", "L")}
    missing = [f for f in FLAGS if f not in assignment]
    if bad or missing or set(assignment) - set(FLAGS):
        raise ValueError(f"A1 reader assignment must give every flag K or L: "
                         f"bad {bad}, missing {missing}")


def subtyped(events: pd.DataFrame, assignment: Mapping[str, str],
             reads: Optional[Mapping[str, str]], end: date) -> pd.DataFrame:
    """Events usable on or before `end` with the subtype A1 counts them under.

    `reads` maps event_id -> L's subtype. Every event of an L flag must have a
    reading, or the build refuses: an unread event is not a clean company.
    Returns isin, flag, subtype, usable_from, event_id (NOT_EVENT dropped)."""
    check_assignment(assignment)
    ev = events.dropna(subset=["isin", "usable_from"]).copy()
    ev["usable_from"] = [x if type(x) is date else pd.Timestamp(x).date()
                         for x in ev["usable_from"]]
    ev = ev[ev["usable_from"] <= end]
    ev["event_id"] = [event_id(s, k, f, h) for s, k, f, h in
                      zip(ev["scrip_code"], ev["key_dt"], ev["flag"], ev["headline"])]
    sub = []
    unread = []
    for eid, f in zip(ev["event_id"], ev["flag"]):
        if assignment[f] == "K":
            sub.append("UNCLEAR")
            continue
        r = (reads or {}).get(eid)
        if r is None:
            unread.append(eid)
            sub.append(None)
        else:
            sub.append(r if r in EVENT_SUBTYPES or r == "NOT_EVENT" else "UNCLEAR")
    if unread:
        raise ValueError(f"A1: {len(unread)} events of L's flags have no reading "
                         f"(first {unread[:3]}); run tools/a1_read_events.py")
    ev["subtype"] = sub
    ev = ev[ev["subtype"] != "NOT_EVENT"]
    return ev[["isin", "flag", "subtype", "usable_from", "event_id"]].reset_index(drop=True)


def covered(scrip_map: pd.DataFrame, isins: Sequence[str], m: date) -> np.ndarray:
    """ISIN has a BSE scrip resolving to it at m (valid_from <= m <= valid_to)."""
    t = pd.Timestamp(m)
    ok = scrip_map[(scrip_map["valid_from"] <= t) & (scrip_map["valid_to"] >= t)]
    have = set(ok["isin"])
    return np.array([i in have for i in isins], dtype=bool)


def a1_features(events: pd.DataFrame, universe: Mapping[date, Sequence[str]],
                month_ends: Sequence[date], scrip_map: pd.DataFrame,
                assignment: Mapping[str, str]) -> pd.DataFrame:
    """The §6(b) store, long format (STORE_COLUMNS), sorted (M, isin, feature).

    `events` is `subtyped(...)`'s output; `universe` is U(M) per month-end (the
    A0 store's names); `month_ends` is every engine month-end of the panel."""
    names = feature_names(assignment)
    mes = sorted(month_ends)
    first_me = mes[bisect_left(mes, FEED_START)] if mes and mes[-1] >= FEED_START else None

    def me_index(d: date) -> int:        # the first month-end on or after d
        return bisect_left(mes, d)

    ev = events.copy()
    ev["k"] = [me_index(u) for u in ev["usable_from"]]
    groups = {key: g.sort_values("usable_from", kind="mergesort")
              for key, g in ev.groupby(["isin", "flag", "subtype"], sort=True)}
    by_isin: Dict[str, list] = {}
    for (isin, f, s), g in groups.items():
        by_isin.setdefault(isin, []).append((f, s, list(g["usable_from"]),
                                             list(g["k"]), list(g["event_id"])))

    out = []
    for m in sorted(universe):
        i_m = mes.index(m)
        elig = list(universe[m])
        pub = pd.Timestamp(datetime.combine(m, CLOSE_IST), tz=TZ)
        # the 12-month window must lie on or after the feed's start
        start_ok = i_m >= 12 and mes[i_m - 12] >= _prev_month_end(mes, FEED_START)
        cov = covered(scrip_map, elig, m) if start_ok else np.zeros(len(elig), bool)
        vals = {n: np.full(len(elig), np.nan) for n in names}
        rid: List[Optional[str]] = [None] * len(elig)
        censored = float(i_m - mes.index(first_me)) if first_me else np.nan
        for j, isin in enumerate(elig):
            if not cov[j]:
                continue
            for n in names:
                vals[n][j] = censored if n.endswith("_since") else 0.0
            last = None
            for f, s, us, ks, ids in by_isin.get(isin, ()):
                stem = f"ev_{f.lower()}_{s.lower()}"
                if f"{stem}_since" not in vals:
                    continue
                hi = bisect_right(us, m)                  # usable_from <= M
                if hi == 0:
                    continue
                for k in WINDOWS:
                    lo_d = mes[i_m - k]
                    lo = bisect_right(us, lo_d)           # usable_from > M_-k
                    vals[f"{stem}_{k}m"][j] = float(hi - lo)
                vals[f"{stem}_since"][j] = float(i_m - ks[hi - 1])
                if last is None or us[hi - 1] > last[0]:
                    last = (us[hi - 1], ids[hi - 1])
            rid[j] = f"bse:{last[1]}" if last else f"bse:none@{m}"
        for n in names:
            v = vals[n]
            ok = ~np.isnan(v)
            out.append(pd.DataFrame({
                "isin": elig, "month_end": m, "feature": n, "value": v,
                "available": ok, "source": "bse_announcements",
                "source_record_id": [r if o else None for r, o in zip(rid, ok)],
                "published_at": pub, "usable_from": m}))
    if not out:
        return pd.DataFrame(columns=STORE_COLUMNS)
    store = pd.concat(out, ignore_index=True)
    order = {f: k for k, f in enumerate(names)}
    store = (store.assign(_o=store["feature"].map(order))
                  .sort_values(["month_end", "isin", "_o"], kind="mergesort")
                  .drop(columns="_o").reset_index(drop=True))
    return store[STORE_COLUMNS]


def _prev_month_end(mes: Sequence[date], d: date) -> date:
    """The last month-end before d (or d itself if none): a window (M_-12, M]
    with M_-12 >= this lies on or after d."""
    i = bisect_left(mes, d)
    return mes[i - 1] if i > 0 else d
