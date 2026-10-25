"""E5-A §6(c) feature store, family A2: promoter positioning.

§6(c) as amended 2026-09-28 and, before any A2 run, 2026-10-01 (E5-A §14):

  * change in promoter **shares** over the trailing one and two reported
    quarters, split/bonus restated, as a fraction of the later quarter's
    shares outstanding (E2-D1's measure as a value, sign reversed so that
    positive is buying);
  * change in promoter **percent** over the same quarters (points);
  * pledged shares as % of promoter holding at the latest quarter, and its
    1- and 2-quarter changes (points). Pledge invocations are dropped,
    declared: there is no source (~41 BSE headlines 2014-2026);
  * the change in total shares outstanding that no recorded split or bonus
    explains, over the same quarters (later / restated earlier - 1). §14
    2026-09-28 calls it a flag; it is carried as the value, because a flag
    needs a threshold and §14 says nothing is thresholded (build reading).

Dating (E5-A §14 2026-10-01, pre-run amendment; replaces E2-D1 §4 items 5-6
for A2 only): a quarter with a BSE "Shareholding Pattern" announcement (the
feed carries them from 2014) is usable from the LATER of that announcement
(after 15:30: next day) and quarter end + 21 days, the filing deadline of
Listing Agreement Clause 35 and, from Dec 2015, LODR Reg 31. A quarter with
no announcement but a filing date in the API (`Fld_AuthoriseDate`) is dated
the same way from that date (build reading). An undated quarter keeps E2-D1's
rule: usable from the first calendar day of the second month after its
quarter end. Pledge: 0 only when reported nil, else NaN (the parser).

E2-D1 readiness §4 items 1-4 carry over unchanged (2026-10-01): the engine's
split/bonus rule; denominator the later quarter's shares outstanding,
reported from Dec 2015, derived before; the latest quarter usable at M
against the quarter k before it, both usable at M, else no measure (an older
pair is never substituted); a pre-2016 complete promoter exit reads as
missing; a filing after 15:30 usable the next day; an undated quarter usable
from the first calendar day of the second month after its quarter end.

Covered = the ISIN's BSE scrip (date-ranged at M) has a usable quarter; each
column is NaN, `available = false`, when its own pair does not exist.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from pflab.data import positioning as pos
from pflab._store_consts import CLOSE_IST, STORE_COLUMNS, TZ

QUARTERS = (1, 2)
DEADLINE_DAYS = 21
_AS_ON = re.compile(r"(?:as\s+(?:on|at)|period\s+ended|quarter\s+ended)\s+"
                    r"([A-Za-z]+)\s*(\d{1,2}),?\s*(\d{4})", re.I)


def announced_quarter(headline: str) -> Optional[date]:
    """The quarter a Shareholding Pattern headline names ("... as on March
    31, 2014", "... for the Period Ended December 31, 2016")."""
    m = _AS_ON.search(headline or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}",
                                 "%b %d %Y").date()
    except ValueError:
        return None


def announcement_dates(ann: pd.DataFrame) -> pd.DataFrame:
    """(scrip_code, quarter_end) -> the first announcement time naming it.
    `ann`: scrip_code, t (dissemination, else news time), headline."""
    a = ann.assign(scrip_code=ann["scrip_code"].astype(str).str.strip(),
                   quarter_end=ann["headline"].map(announced_quarter))
    a = a.dropna(subset=["quarter_end", "t"])
    return (a.sort_values("t", kind="mergesort")
             .groupby(["scrip_code", "quarter_end"], sort=True)["t"].first()
             .rename("announced").reset_index())


def usable_from(q_end: date, announced, filed) -> tuple:
    """(usable date, dated, source) under the 2026-10-01 rule."""
    floor = q_end + timedelta(days=DEADLINE_DAYS)
    for t, src in ((announced, "announcement"), (filed, "Fld_AuthoriseDate")):
        if t is not None and not pd.isna(t):
            return max(pos.filed_usable_from(pd.Timestamp(t)), floor), True, src
    return pos.undated_usable_from(q_end), False, "second_month_rule"
EXTRA = ["promoter_pct", "pledged_pct_of_promoter"]


def feature_names() -> List[str]:
    out = []
    for k in QUARTERS:
        out += [f"prom_shares_chg_{k}q", f"prom_pct_chg_{k}q"]
    out.append("pledge_pct")
    out += [f"pledge_pct_chg_{k}q" for k in QUARTERS]
    out += [f"so_unexplained_chg_{k}q" for k in QUARTERS]
    return out


def quarters(summary: pd.DataFrame, announced: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """`positioning.promoter_quarters` (the E2-D1 rows and denominator) with
    promoter percent and the pledge share joined on, re-dated by
    `usable_from` (`announced` from `announcement_dates`)."""
    pq = pos.promoter_quarters(summary)
    fd = summary[summary["status"] == "ok"].assign(
        scrip_code=lambda d: d["scrip_code"].astype(str).str.strip(),
        quarter_end=lambda d: d["quarter_end"].map(pos._quarter_end))
    fd = fd[["scrip_code", "quarter_end", "filing_date"]].drop_duplicates(
        ["scrip_code", "quarter_end"], keep="last")
    pq = pq.merge(fd, on=["scrip_code", "quarter_end"], how="left")
    if announced is not None and len(announced):
        pq = pq.merge(announced, on=["scrip_code", "quarter_end"], how="left")
    else:
        pq["announced"] = pd.NaT
    u = [usable_from(q, a, f) for q, a, f in
         zip(pq["quarter_end"], pq["announced"], pq["filing_date"])]
    pq["usable_from"] = [x[0] for x in u]
    pq["dated"] = [x[1] for x in u]
    pq["date_source"] = [x[2] for x in u]
    pq = pq.drop(columns=["filing_date", "announced"])
    s = summary[summary["status"] == "ok"].copy()
    s["scrip_code"] = s["scrip_code"].astype(str).str.strip()
    s["quarter_end"] = s["quarter_end"].map(pos._quarter_end)
    s = (s[["scrip_code", "quarter_end"] + EXTRA]
         .drop_duplicates(["scrip_code", "quarter_end"], keep="last"))
    return pq.merge(s, on=["scrip_code", "quarter_end"], how="left")


def pairs(pq: pd.DataFrame, actions: Optional[pd.DataFrame],
          isins_by_scrip: Dict[str, list]) -> pd.DataFrame:
    """Each quarter with its k-quarter-earlier pair, for k in QUARTERS: the
    restated change columns and the earlier quarter's usable date."""
    df = pq.copy()
    events = pos.share_count_events(actions)
    so = df["shares_outstanding"].where(df["shares_outstanding"] > 0)
    for k in QUARTERS:
        qp = [(pd.Timestamp(q) - pd.offsets.QuarterEnd(k)).date() for q in df["quarter_end"]]
        prev = pq[["scrip_code", "quarter_end", "usable_from", "promoter_shares",
                   "shares_outstanding"] + EXTRA].rename(columns={
            "quarter_end": f"_qp{k}", "usable_from": f"_puf{k}",
            "promoter_shares": "_pps", "shares_outstanding": "_pso",
            "promoter_pct": "_ppct", "pledged_pct_of_promoter": "_ppl"})
        m = df[["scrip_code"]].assign(**{f"_qp{k}": qp}).merge(
            prev, on=["scrip_code", f"_qp{k}"], how="left")
        mult = np.array([
            np.nan if pd.isna(pp) else
            pos._multiplier(events, isins_by_scrip.get(sc, ()), q0, q1)
            for sc, pp, q0, q1 in zip(df["scrip_code"], m["_pps"], qp, df["quarter_end"])])
        pso = m["_pso"].where(m["_pso"] > 0).to_numpy()
        df[f"prom_shares_chg_{k}q"] = (df["promoter_shares"].to_numpy()
                                       - m["_pps"].to_numpy() * mult) / so.to_numpy()
        df[f"prom_pct_chg_{k}q"] = df["promoter_pct"].to_numpy() - m["_ppct"].to_numpy()
        df[f"pledge_pct_chg_{k}q"] = (df["pledged_pct_of_promoter"].to_numpy()
                                      - m["_ppl"].to_numpy())
        df[f"so_unexplained_chg_{k}q"] = so.to_numpy() / (pso * mult) - 1.0
        df[f"_puf{k}"] = pd.to_datetime(pd.Series(m[f"_puf{k}"].to_numpy(), dtype="object"))
    df["pledge_pct"] = df["pledged_pct_of_promoter"]
    df["_uf"] = pd.to_datetime(pd.Series(df["usable_from"], dtype="object"))
    return df


def at(pr: pd.DataFrame, m: date) -> pd.DataFrame:
    """Per scrip, the latest quarter usable at M; a k-quarter column is kept
    only if its earlier quarter is also usable at M (never substituted)."""
    t = pd.Timestamp(m)
    c = pr[pr["_uf"] <= t]
    if not len(c):
        return c
    last = c.sort_values(["scrip_code", "quarter_end"], kind="mergesort") \
            .groupby("scrip_code").tail(1).copy()
    for k in QUARTERS:
        bad = ~(last[f"_puf{k}"] <= t)
        for n in (f"prom_shares_chg_{k}q", f"prom_pct_chg_{k}q",
                  f"pledge_pct_chg_{k}q", f"so_unexplained_chg_{k}q"):
            last.loc[bad, n] = np.nan
    return last


def a2_features(pr: pd.DataFrame, universe: Mapping[date, Sequence[str]],
                resolver: "pos.ScripResolver") -> pd.DataFrame:
    """The §6(c) store, long format (STORE_COLUMNS), sorted (M, isin, feature).

    `pr` is `pairs(...)`'s output; `universe` is U(M) per month-end (the A0
    store's names). A scrip enters at M through the ISIN it carried at M; if
    two scrips resolve to one ISIN, the lower scrip code is read."""
    names = feature_names()
    out = []
    for m in sorted(universe):
        elig = list(universe[m])
        pub = pd.Timestamp(datetime.combine(m, CLOSE_IST), tz=TZ)
        last = at(pr, m)
        by_isin: Dict[str, tuple] = {}
        for r in last.sort_values("scrip_code", kind="mergesort").itertuples(index=False):
            isin = resolver.isin_at(r.scrip_code, m)
            if isin and isin not in by_isin:
                by_isin[isin] = r
        rid = [f"bse_shp:{by_isin[i].scrip_code}@{by_isin[i].quarter_end}"
               if i in by_isin else None for i in elig]
        for n in names:
            v = np.array([float(getattr(by_isin[i], n)) if i in by_isin else np.nan
                          for i in elig], dtype=float)
            v = np.where(np.isfinite(v), v, np.nan)
            ok = ~np.isnan(v)
            out.append(pd.DataFrame({
                "isin": elig, "month_end": m, "feature": n, "value": v,
                "available": ok, "source": "bse_shareholding",
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
