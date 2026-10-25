"""Point-in-time promoter selling (charter E2-D1 §3-§4).

A name is ineligible at month-end M when its promoters' **shares** fell by
more than a threshold fraction of shares outstanding between the latest
quarterly shareholding pattern usable at M and the pattern two quarters
before it. Shares, not percent: promoter percent also falls when the
company issues shares and promoters sell nothing (The investor, 2026-09-27).

Point-in-time (E2-D §4 as amended 2026-09-24, carried into E2-D1):

* a quarter with a filing timestamp is usable from that session, or the
  next one if it was filed after 15:30 (the E2-A §3 cutoff);
* a quarter without one (2010 -> Sep 2015) is usable from **the second
  month-end after its quarter end** -- here, from the first calendar day of
  that month, so the month-end decision of that month sees it and the one
  before does not.

A split or bonus between the two quarters changes promoter shares without
anyone buying or selling. The earlier count is restated in the later
quarter's units with the corporate actions the engine itself treats as
share-count events (`engine._apply_ex_date_events`'s rule), across every
ISIN the scrip carried.

Nothing here picks a parameter: the threshold and the dated-only switch
come from the charter's config.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

from pflab.data import data_dir

CUTOFF = time(15, 30)
COLUMNS = ["scrip_code", "quarter_end", "usable_from", "dated",
           "promoter_shares", "shares_outstanding", "so_source"]


def _as_date(x) -> date:
    """A date from a date, datetime, Timestamp or ISO string, without going
    through nanosecond Timestamps: the 2999-12-31 open-ended sentinel is out
    of their range, and pandas 2.x raises on it where 3.x does not."""
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, np.datetime64):
        return x.astype("datetime64[D]").astype(object)
    return date.fromisoformat(str(x)[:10])


def _quarter_end(x) -> date:
    return pd.Timestamp(x).date()


def undated_usable_from(q_end: date) -> date:
    """First day of the second month after the quarter's end month."""
    y, m = q_end.year, q_end.month + 2
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return date(y, m, 1)


def filed_usable_from(filed: pd.Timestamp) -> date:
    d = filed.date()
    return d + timedelta(days=1) if filed.time() > CUTOFF else d


def promoter_quarters(summary: pd.DataFrame) -> pd.DataFrame:
    """One row per (scrip, quarter) the rule can read, with its usable date."""
    s = summary[summary["status"] == "ok"].copy()
    s["scrip_code"] = s["scrip_code"].astype(str).str.strip()
    s["quarter_end"] = s["quarter_end"].map(_quarter_end)
    s["dated"] = s["filing_date"].notna()
    s["usable_from"] = [
        filed_usable_from(pd.Timestamp(f)) if pd.notna(f) else undated_usable_from(q)
        for f, q in zip(s["filing_date"], s["quarter_end"])]
    rep = s["shares_outstanding_reported"]
    s["shares_outstanding"] = rep.where(rep > 0, s["shares_outstanding_derived"])
    s["so_source"] = np.where(rep > 0, "reported", "derived")
    s = s[s["promoter_shares"].notna()]
    return (s[COLUMNS].sort_values(["scrip_code", "quarter_end"])
             .drop_duplicates(["scrip_code", "quarter_end"], keep="last")
             .reset_index(drop=True))


def share_count_events(actions: Optional[pd.DataFrame]) -> Dict[str, list]:
    """isin -> [(ex_date, share multiplier)] for the actions the engine
    applies to share counts (`engine._apply_ex_date_events`'s rule)."""
    out: Dict[str, list] = {}
    if actions is None or not len(actions):
        return out
    from pflab.backtest.engine import _snaps_to_standard_ratio
    for r in actions.itertuples(index=False):
        f = float(r.factor)
        src = getattr(r, "source", "purpose")
        if f > 0 and (src == "purpose" or f > 1.0 or _snaps_to_standard_ratio(f)):
            out.setdefault(str(r.isin), []).append(
                (pd.Timestamp(r.ex_date).date(), 1.0 / f))
    return out


def _multiplier(events: Dict[str, list], isins: Iterable[str],
                lo: date, hi: date) -> float:
    """Product of share multipliers for events with lo < ex_date <= hi."""
    mult = 1.0
    for i in isins:
        for ex, k in events.get(i, ()):
            if lo < ex <= hi:
                mult *= k
    return mult


def two_quarter_changes(pq: pd.DataFrame, actions: Optional[pd.DataFrame],
                        isins_by_scrip: Dict[str, list]) -> pd.DataFrame:
    """For each quarter, the promoter-share change against two quarters before.

    Adds: q_prev, prev_usable_from, prev_dated, share_multiplier and
    `sold_frac` = (restated earlier shares - later shares) / later shares
    outstanding. Positive means net selling. NaN when the earlier quarter
    is missing or shares outstanding is not positive.
    """
    df = pq.copy()
    df["q_prev"] = [(pd.Timestamp(q) - pd.offsets.QuarterEnd(2)).date()
                    for q in df["quarter_end"]]
    prev = pq[["scrip_code", "quarter_end", "usable_from", "dated",
               "promoter_shares"]].rename(columns={
        "quarter_end": "q_prev", "usable_from": "prev_usable_from",
        "dated": "prev_dated", "promoter_shares": "prev_promoter_shares"})
    df = df.merge(prev, on=["scrip_code", "q_prev"], how="left")
    events = share_count_events(actions)
    df["share_multiplier"] = [
        np.nan if pd.isna(pp) else
        _multiplier(events, isins_by_scrip.get(sc, ()), qp, qe)
        for sc, pp, qp, qe in zip(df["scrip_code"], df["prev_promoter_shares"],
                                  df["q_prev"], df["quarter_end"])]
    restated = df["prev_promoter_shares"] * df["share_multiplier"]
    so = df["shares_outstanding"].where(df["shares_outstanding"] > 0)
    df["sold_frac"] = (restated - df["promoter_shares"]) / so
    # datetime64 copies of the usable dates, so each month-end's test is one
    # vectorised comparison rather than a Python loop over every quarter
    df["_uf"] = pd.to_datetime(pd.Series(df["usable_from"], dtype="object"))
    df["_puf"] = pd.to_datetime(pd.Series(df["prev_usable_from"], dtype="object"))
    return df


def flagged_at(changes: pd.DataFrame, m: date, threshold: float,
               dated_only: bool = False) -> Dict[str, dict]:
    """Scrips whose latest usable quarter at M shows selling > threshold.

    The latest quarter usable at M is the one read; if ITS comparison
    quarter is not usable at M (or missing), the scrip has no measure --
    an older pair is never substituted.
    """
    t = pd.Timestamp(m)
    c = changes[changes["_uf"] <= t]
    if not len(c):
        return {}
    latest = c.sort_values("quarter_end").groupby("scrip_code").tail(1)
    ok = latest["sold_frac"].notna() & (latest["_puf"] <= t)
    if dated_only:
        ok &= latest["dated"] & latest["prev_dated"].fillna(False).astype(bool)
    hit = latest[ok & (latest["sold_frac"] > threshold)]
    return {r.scrip_code: {"quarter_end": r.quarter_end, "q_prev": r.q_prev,
                           "sold_frac": float(r.sold_frac)}
            for r in hit.itertuples(index=False)}


class ScripResolver:
    """Scrip code -> the ISIN it carried on a date (date-ranged, rule 8)."""

    def __init__(self, scrip_map: pd.DataFrame):
        m = scrip_map[scrip_map["isin"].astype(str) != ""]
        self.by_scrip: Dict[str, list] = {}
        for r in m.itertuples(index=False):
            self.by_scrip.setdefault(str(r.scrip_code), []).append(
                (str(r.isin), _as_date(r.valid_from), _as_date(r.valid_to)))

    def isin_at(self, scrip: str, d: date) -> Optional[str]:
        for isin, lo, hi in self.by_scrip.get(scrip, ()):
            if lo <= d <= hi:
                return isin
        return None

    def all_isins(self) -> Dict[str, list]:
        return {s: [i for i, _, _ in v] for s, v in self.by_scrip.items()}


def promoter_exclusion(period_end: date, actions: Optional[pd.DataFrame],
                       threshold: float, dated_only: bool = False,
                       root: Optional[Path] = None,
                       summary: Optional[pd.DataFrame] = None,
                       scrip_map: Optional[pd.DataFrame] = None):
    """(exclude_fn, record) for the engine.

    Rows usable after `period_end` are dropped at load (non-negotiable 2),
    so nothing beyond the period can reach a decision even by accident.
    `record` collects each month's flags for §8's extras.
    """
    root = root or data_dir()
    if summary is None:
        summary = pd.read_parquet(root / "bse_shareholding" / "summary.parquet")
    if scrip_map is None:
        from pflab.data import bse_scrip_isin
        scrip_map = bse_scrip_isin.load(root)
    pq = promoter_quarters(summary)
    pq = pq[pd.Series([u <= period_end for u in pq["usable_from"]], index=pq.index)]
    res = ScripResolver(scrip_map)
    changes = two_quarter_changes(pq, actions, res.all_isins())
    record: Dict[date, dict] = {}

    def exclude_fn(m: date) -> set:
        hits = flagged_at(changes, m, threshold, dated_only)
        out = {}
        for scrip, detail in hits.items():
            isin = res.isin_at(scrip, m)
            if isin:
                out[isin] = {**detail, "scrip_code": scrip}
        record[m] = out
        return set(out)

    return exclude_fn, record


# -- E2-D2: insider selling from NSE PIT disclosures -----------------------
INSIDER_KEYS = ("threshold", "window_months", "categories", "modes",
                "transaction_types")


def insider_rows(pit: pd.DataFrame, symbol_map: pd.DataFrame, period_end: date,
                 categories, modes, transaction_types) -> pd.DataFrame:
    """PIT disclosures the rule counts, keyed to an ISIN and a usable date.

    * usable from the broadcast session, or the next day if broadcast after
      15:30 (E2-A §3's cutoff);
    * the symbol is joined to an ISIN **with the broadcast date** (rule 8);
    * `categories`, `modes` and `transaction_types` are lists, or "all" --
      E2-D2 §4 leaves them to the lock, so there is no default;
    * signed value: Sell counts +value, Buy -value (net selling positive);
      rows without a positive value are dropped and counted in attrs.
    """
    d = pit.copy()
    d["usable_from"] = [filed_usable_from(pd.Timestamp(x)) if pd.notna(x) else None
                        for x in d["broadcast_dt"]]
    d = d[d["usable_from"].notna()]
    d = d[pd.Series([u <= period_end for u in d["usable_from"]], index=d.index)]
    norm = lambda s: s.astype(str).str.strip().str.lower()
    if categories != "all":
        d = d[norm(d["person_category"]).isin([c.lower() for c in categories])]
    if modes != "all":
        d = d[norm(d["acq_mode"]).isin([c.lower() for c in modes])]
    if transaction_types != "all":
        d = d[norm(d["transaction_type"]).isin([c.lower() for c in transaction_types])]
    tt = norm(d["transaction_type"])
    d = d[tt.isin(["sell", "buy"])]
    no_value = int((~(d["value"] > 0)).sum())
    d = d[d["value"] > 0]
    sign = np.where(norm(d["transaction_type"]) == "sell", 1.0, -1.0)
    d = d.assign(signed_value=sign * d["value"].astype(float))
    m = symbol_map.copy()
    m["valid_from"] = [_as_date(x) for x in m["valid_from"]]
    m["valid_to"] = [_as_date(x) for x in m["valid_to"]]
    by_sym: Dict[str, list] = {}
    for r in m.itertuples(index=False):
        by_sym.setdefault(str(r.symbol), []).append((r.isin, r.valid_from, r.valid_to))
    isins = []
    for sym, bd in zip(d["symbol"].astype(str), d["broadcast_dt"]):
        day = pd.Timestamp(bd).date()
        isins.append(next((i for i, lo, hi in by_sym.get(sym, ()) if lo <= day <= hi), None))
    d["isin"] = isins
    unmapped = int(d["isin"].isna().sum())
    d = d[d["isin"].notna()]
    out = d[["isin", "usable_from", "signed_value", "person_category",
             "acq_mode", "transaction_type"]].reset_index(drop=True)
    out["_uf"] = pd.to_datetime(pd.Series(out["usable_from"], dtype="object"))
    out.attrs.update({"dropped_no_value": no_value, "dropped_unmapped_symbol": unmapped})
    return out


def shares_outstanding_at(summary: pd.DataFrame, resolver: "ScripResolver"):
    """isin -> latest REPORTED shares outstanding usable at M (E2-D2 §3).
    Reported only: before the December 2015 quarter there is no reported
    figure, and E2-D2's window starts in 2017."""
    pq = promoter_quarters(summary)
    pq = pq[pq["so_source"] == "reported"].copy()
    pq["_uf"] = pd.to_datetime(pd.Series(pq["usable_from"], dtype="object"))

    def at(m: date) -> Dict[str, float]:
        c = pq[pq["_uf"] <= pd.Timestamp(m)].sort_values("quarter_end")
        last = c.groupby("scrip_code").tail(1)
        out = {}
        for sc, so in zip(last["scrip_code"], last["shares_outstanding"]):
            isin = resolver.isin_at(sc, m)
            if isin and so > 0:
                out[isin] = float(so)
        return out
    return at


def insider_exclusion(period_end: date, cfg: dict, close_at,
                      root: Optional[Path] = None, pit: Optional[pd.DataFrame] = None,
                      symbol_map: Optional[pd.DataFrame] = None,
                      summary: Optional[pd.DataFrame] = None,
                      scrip_map: Optional[pd.DataFrame] = None):
    """(exclude_fn, record) for E2-D2 §3.

    Net insider value over the trailing `window_months` calendar months
    ending at M, divided by market cap at M = reported shares outstanding
    (latest filing usable at M) x `close_at(isin, M)`. A name with no
    reported shares outstanding or no close at M has no measure.
    """
    missing = [k for k in INSIDER_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"insider_selling.{missing} must come from the charter's "
                         f"config (E2-D2 §3-§4)")
    root = root or data_dir()
    if pit is None:
        from pflab.data import nse_insider
        pit = nse_insider.load(root)
    if symbol_map is None:
        symbol_map = pd.read_parquet(root / "panel" / "symbol_isin_map.parquet")
    if summary is None:
        summary = pd.read_parquet(root / "bse_shareholding" / "summary.parquet")
    if scrip_map is None:
        from pflab.data import bse_scrip_isin
        scrip_map = bse_scrip_isin.load(root)
    rows = insider_rows(pit, symbol_map, period_end, cfg["categories"],
                        cfg["modes"], cfg["transaction_types"])
    so_at = shares_outstanding_at(summary, ScripResolver(scrip_map))
    thr, months = float(cfg["threshold"]), int(cfg["window_months"])
    record: Dict[date, dict] = {"_dropped": dict(rows.attrs)}

    def exclude_fn(m: date) -> set:
        t = pd.Timestamp(m)
        w = rows[(rows["_uf"] <= t) & (rows["_uf"] > t - pd.DateOffset(months=months))]
        net = w.groupby("isin")["signed_value"].sum()
        net = net[net > 0]
        so = so_at(m)
        out = {}
        for isin, v in net.items():
            px = close_at(isin, m)
            if isin not in so or px is None or not (px > 0):
                continue
            frac = float(v) / (so[isin] * px)
            if frac > thr:
                out[isin] = {"net_value": float(v), "market_cap": so[isin] * px,
                             "net_frac": frac}
        record[m] = out
        return set(out)

    return exclude_fn, record
