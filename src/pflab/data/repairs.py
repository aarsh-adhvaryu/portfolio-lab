"""D1 and D2 (approved by the investor 2026-09-27; E1 §15 change log): two data
repairs applied on the path after `periods.truncate_end`, to every config.

**D2 -- BE-series gaps.** The panel is EQ only. When a stock leaves EQ for
the trade-for-trade segment (BE/BZ) and comes back, NSE's PREVCLOSE on the
return is the last BE close, so `prevclose_factors` read the price movement
during the stint as a corporate action: a fall became a cash credit, a rise
a "consolidation". The repair:
  * drops a PREVCLOSE factor whose adjusted prev close equals the stock's
    last BE/BZ close inside that EQ gap (it is price movement, not an action);
  * inserts the BE/BZ rows into the gaps (and after the last EQ row, for a
    stock still in BE at the period end), so a held name is marked and can be
    sold at real prices. The universe filter reads `universe.series`, so a
    BE row never makes a name eligible, and the engine does not BUY on one.

**D1 -- ISIN handovers.** A stock changes ISIN (usually after a face-value
split) and trades under the new one from the next session, same symbol. The
engine read the old ISIN as dead. The repair re-keys the old ISIN's rows and
actions to the successor (CLAUDE.md 8: a dated fact), so the book holds one
security and the universe's session count does not restart. If the price
jumps across the switch by a standard split ratio that no PURPOSE factor
covers, that factor is added as a share-count action on the first new
session; a non-standard jump is not repaired and is reported.

Only rows dated <= the period end are passed in, so nothing here can see
past it; factors dated after the end enter `adj_factor` only as a constant
per-ISIN scale, as they already do in the stored panel.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

NON_EQ = ("BE", "BZ")
PRICE_TOL = 0.002          # D2: adj prev close vs last BE close, relative
PRICE_TICK = 0.05          # ... or within one tick
SAME_PRICE = 0.02          # a prev close inside this of the prior close is unadjusted
JUMP_BAND = (0.80, 1.25)   # D2: a transition open outside this is an action
MAX_GAP_SESSIONS = 10      # D1: new ISIN's first session after the old's last
STANDARD_RATIOS = (1/2, 1/3, 1/4, 1/5, 1/10, 2/3, 3/4, 4/5, 2/5, 1/1.5, 1/2.5)
SNAP_TOL = 0.01


def _snap(r: float) -> Optional[float]:
    for s in STANDARD_RATIOS:
        if abs(r / s - 1.0) <= SNAP_TOL:
            return s
    return None


def _ts(s):
    return pd.to_datetime(s).astype("datetime64[ns]")


def _as_date(s):
    return pd.to_datetime(s).dt.date


def prepare_be(panel: pd.DataFrame, be: pd.DataFrame) -> pd.DataFrame:
    """BE/BZ rows to insert: ISIN from the row, else from the same symbol's
    latest EQ row before it; only after that ISIN's first EQ row, and only on
    dates it has no EQ row."""
    if be is None or len(be) == 0:
        return panel.iloc[0:0].copy()
    b = be[be["series"].isin(NON_EQ)].copy()
    b["date"] = _as_date(b["date"])
    b["symbol"] = b["symbol"].astype(str)
    b["isin"] = b["isin"].astype(object).where(b["isin"].notna() & (b["isin"] != ""), None)
    eq = panel[["date", "symbol", "isin"]].copy()
    eq["symbol"] = eq["symbol"].astype(str)
    eq["_t"] = _ts(eq["date"])
    b["_t"] = _ts(b["date"])
    eq = eq.sort_values("_t")
    b = b.sort_values("_t")
    m = pd.merge_asof(b[["_t", "symbol"]].reset_index(), eq[["_t", "symbol", "isin"]],
                      on="_t", by="symbol", direction="backward")
    fill = pd.Series(m["isin"].values, index=m["index"].values)
    b["isin"] = b["isin"].fillna(fill.reindex(b.index))
    b = b[b["isin"].notna()]
    first = panel.groupby("isin")["date"].min()
    b = b[b["isin"].isin(first.index)]
    b = b[b["date"].values > first.reindex(b["isin"]).values]
    have = pd.MultiIndex.from_arrays([panel["date"], panel["isin"]])
    b = b[~pd.MultiIndex.from_arrays([b["date"], b["isin"]]).isin(have)]
    b = b.drop_duplicates(["date", "isin"], keep="last")
    types = panel.drop_duplicates("isin").set_index("isin").get("instrument_type")
    out = pd.DataFrame({c: b[c].values for c in
                        ("date", "isin", "symbol", "series", "open", "high", "low",
                         "close", "prev_close", "volume", "turnover") if c in b.columns})
    if types is not None:
        out["instrument_type"] = types.reindex(out["isin"]).values
    out["dividend"] = 0.0
    return out


def be_gap_factors(actions: pd.DataFrame, panel_eq: pd.DataFrame,
                   be_rows: pd.DataFrame) -> pd.DataFrame:
    """Every PREVCLOSE factor on the first EQ session after a BE/BZ stint,
    with the stint's last close. `drift` = its adjusted prev close IS that
    close, so the factor is price movement during the stint and is dropped;
    otherwise NSE adjusted the close for an action at the return, and the
    factor is re-based on the last BE close so the drift is not in it."""
    cols = ["isin", "ex_date", "factor", "adj_prev_close", "be_date", "be_close", "drift"]
    if actions is None or len(actions) == 0 or len(be_rows) == 0:
        return pd.DataFrame(columns=cols)
    pc = actions[actions["source"] == "prevclose"].copy()
    pc["ex_date"] = _as_date(pc["ex_date"])
    eq = panel_eq[["isin", "date"]].sort_values(["isin", "date"])
    eq["_prev"] = eq.groupby("isin")["date"].shift(1)
    pc = pc.merge(eq.rename(columns={"date": "ex_date"}), on=["isin", "ex_date"], how="left")
    b = be_rows[["isin", "date", "close"]].sort_values("date")
    b["isin"] = b["isin"].astype(object).astype(str)
    pc["isin"] = pc["isin"].astype(object).astype(str)
    b["_t"] = _ts(b["date"])
    pc["_t"] = _ts(pc["ex_date"]) - pd.Timedelta(days=1)
    pc = pc.sort_values("_t")
    j = pd.merge_asof(pc, b.rename(columns={"date": "be_date", "close": "be_close"}),
                      on="_t", by="isin", direction="backward")
    in_gap = j["be_date"].notna() & (j["_prev"].isna() | (j["be_date"] > j["_prev"]))
    j = j[in_gap].copy()
    j["drift"] = (j["adj_prev_close"] - j["be_close"]).abs() <= np.maximum(
        PRICE_TICK, PRICE_TOL * j["be_close"])
    return j[cols].reset_index(drop=True)


def transition_jumps(p: pd.DataFrame, skip: set) -> pd.DataFrame:
    """D2: an action on the session a stock moves between EQ and BE/BZ.
    SUVEN's 2020 demerger went ex on the day it entered BE (301.45 -> 15.95,
    raw prev close), so neither PREVCLOSE nor the return factor sees it. A
    move is an action if NSE adjusted the prev close (> SAME_PRICE off the
    prior close), or -- on entry to BE/BZ only -- the open is outside
    JUMP_BAND of it, which the price band does not allow without one. On a
    return to EQ, a prev close equal to the last EQ close before the stint
    is stale, not adjusted; on entry, an adjusted prev close counts only if
    the open agrees with it (within JUMP_BAND). `skip`: (isin, date) already
    carrying a factor."""
    q = p[["isin", "date", "series", "open", "close", "prev_close"]]         .sort_values(["isin", "date"], kind="mergesort")
    g = q.groupby("isin", sort=False)
    prev_series, prev_close = g["series"].shift(1), g["close"].shift(1)
    t = q[prev_series.notna() & (prev_series.isin(NON_EQ) != q["series"].isin(NON_EQ))].copy()
    # The last EQ close before the current stint. On a return to EQ, NSE
    # sometimes carries THAT as the prev close rather than the last BE close
    # (GOLDTECH 2008-06-13: 224.80, its 2008-05-15 EQ close, against a last
    # BE close of 246.55). That is a stale value, not an adjustment
    # (2026-09-28; it had produced false cash credits).
    eq_close = q["close"].where(~q["series"].isin(NON_EQ))
    last_eq = eq_close.groupby(q["isin"], sort=False).ffill()
    last_eq = last_eq.groupby(q["isin"], sort=False).shift(1)
    t["prior"] = prev_close.loc[t.index]
    t["last_eq"] = last_eq.loc[t.index]
    t = t[t["prior"] > 0]
    t = t[np.array([(i, d) not in skip for i, d in zip(t["isin"], t["date"])], dtype=bool)]
    px = t["open"].where(t["open"] > 0, t["close"])
    stale = (~t["series"].isin(NON_EQ) & (t["last_eq"] > 0)
             & ((t["prev_close"] / t["last_eq"] - 1).abs() <= SAME_PRICE))
    adjusted = ((t["prev_close"] > 0) & ((t["prev_close"] / t["prior"] - 1).abs() > SAME_PRICE)
                & ~stale)
    # On ENTRY the band holds the first trade near the true prior, so an
    # adjusted prev close the open contradicts is bad data, not an action:
    # 2008-06-13 carried round prev closes (ROHITFERRO 30.00, SHREEASHTA
    # 160.00) on names that opened at their prior close, read as 1:5 and 1:3
    # splits (2026-09-28). The open decides instead, through `out_band`.
    entry = t["series"].isin(NON_EQ)
    agrees = (px / t["prev_close"]).between(*JUMP_BAND)
    adjusted = adjusted & (~entry | agrees)
    jump = px / t["prior"]
    # Only on ENTRY to BE/BZ, where the price band holds the first trade near
    # the prior close; a return to EQ can open through an unbanded call
    # auction, so there only NSE's own adjusted prev close counts.
    out_band = ((jump < JUMP_BAND[0]) | (jump > JUMP_BAND[1])) & t["series"].isin(NON_EQ)
    t["factor"] = np.where(adjusted, t["prev_close"] / t["prior"], jump)
    t = t[adjusted | out_band]
    return pd.DataFrame({"isin": t["isin"].values, "ex_date": t["date"].values,
                         "factor": t["factor"].values, "source": "prevclose",
                         "prior_close": t["prior"].values,
                         "adj_prev_close": (t["prior"] * t["factor"]).values,
                         "series": t["series"].values})


def handovers(panel: pd.DataFrame, actions: Optional[pd.DataFrame]) -> Tuple[list, list]:
    """(events, rejected). One event per same-symbol ISIN switch in which the
    old ISIN's last session is followed within MAX_GAP_SESSIONS by the new
    ISIN's first. ETFs are left to `etf_events`."""
    p = panel
    if "instrument_type" in p.columns:
        p = p[p["instrument_type"] != "ETF"]
    sess = {d: i for i, d in enumerate(sorted(panel["date"].unique()))}
    span = p.groupby("isin").agg(first=("date", "min"), last=("date", "max"))
    last_row = p.sort_values("date").groupby("isin").tail(1).set_index("isin")
    first_row = p.sort_values("date").groupby("isin").head(1).set_index("isin")
    purpose = set()
    if actions is not None and len(actions):
        a = actions[actions["source"] == "purpose"]
        purpose = set(zip(a["isin"], _as_date(a["ex_date"])))
    events, rejected = [], []
    for sym, g in p[["symbol", "isin"]].drop_duplicates().groupby("symbol"):
        isins = list(g["isin"])
        if len(isins) < 2:
            continue
        order = sorted(isins, key=lambda i: span.at[i, "first"])
        for old, new in zip(order, order[1:]):
            lo, fn = span.at[old, "last"], span.at[new, "first"]
            if not (span.at[old, "first"] < fn and lo < fn):
                continue                                # overlapping lives
            gap = sess[fn] - sess[lo]
            if gap < 1 or gap > MAX_GAP_SESSIONS:
                continue
            oc = float(last_row.at[old, "close"])
            npc = float(first_row.at[new, "prev_close"])
            if not (oc > 0) or not (npc > 0):
                npc = float(first_row.at[new, "open"])
            r = npc / oc if oc > 0 else np.nan
            ev = {"symbol": sym, "old_isin": old, "new_isin": new, "old_last": lo,
                  "new_first": fn, "gap_sessions": gap, "ratio": r}
            if abs(r - 1.0) <= SAME_PRICE or (new, fn) in purpose or (old, fn) in purpose:
                events.append({**ev, "factor": 1.0})
            elif (s := _snap(r)) is not None:
                events.append({**ev, "factor": s})
            else:
                rejected.append(ev)
    return events, rejected


def _adj(rows: pd.DataFrame, factors: pd.DataFrame) -> np.ndarray:
    """Cumulative product of factors with ex_date > row date, per ISIN."""
    out = np.ones(len(rows))
    if len(factors) == 0:
        return out
    idx = rows.groupby("isin").indices
    d = rows["date"].values
    for isin, g in factors.groupby("isin"):
        ix = idx.get(isin)
        if ix is None:
            continue
        cum = np.ones(len(ix))
        for ex, fac in zip(g["ex_date"], g["factor"]):
            cum *= np.where(d[ix] < ex, fac, 1.0)
        out[ix] = cum
    return out


def be_dividends(be_rows: pd.DataFrame, dividends: Optional[pd.DataFrame],
                 acts: Optional[pd.DataFrame]) -> pd.Series:
    """Cash per share going ex on each inserted BE/BZ row (2026-09-28).

    The panel's dividend column is joined on EQ rows only, so a dividend
    with its ex-date inside a stint was never credited. It is joined here on
    the row's own ISIN, before D1 re-keys it. A date that also carries an
    action for that ISIN keeps the action alone, as on EQ rows (E1 §15
    2026-09-16: never two on one date)."""
    out = pd.Series(0.0, index=be_rows.index)
    if dividends is None or len(dividends) == 0 or len(be_rows) == 0:
        return out
    d = dividends.rename(columns={"ex_date": "date", "dividend_per_share": "dividend"})
    d = d.assign(date=_as_date(d["date"])).groupby(["isin", "date"])["dividend"].sum()
    keys = pd.MultiIndex.from_arrays([be_rows["isin"].astype(str), be_rows["date"]])
    got = pd.Series(d.reindex(keys).to_numpy(), index=be_rows.index).fillna(0.0)
    if acts is not None and len(acts):
        busy = set(zip(acts["isin"].astype(str), _as_date(acts["ex_date"])))
        hit = [(i, t) in busy for i, t in zip(be_rows["isin"].astype(str), be_rows["date"])]
        got[pd.Series(hit, index=be_rows.index) & got.gt(0)] = 0.0
    return got


def apply(panel: pd.DataFrame, actions: Optional[pd.DataFrame],
          be: Optional[pd.DataFrame], all_factors: Optional[pd.DataFrame] = None,
          dividends: Optional[pd.DataFrame] = None,
          ) -> Tuple[pd.DataFrame, Optional[pd.DataFrame], dict]:
    """(panel, actions, report). `panel`, `actions`, `be` and `dividends` (the
    feed: isin, ex_date, dividend_per_share) are already cut at the period
    end; `all_factors` is the stored factor table (used for `adj_factor`
    exactly as the stored panel uses it; defaults to `actions`)."""
    p = panel.reset_index(drop=True)
    p["date"] = _as_date(p["date"])
    acts = None if actions is None else actions.copy()
    if acts is not None:
        acts["ex_date"] = _as_date(acts["ex_date"])
    allf = (acts if all_factors is None else all_factors)
    allf = (pd.DataFrame(columns=["isin", "ex_date", "factor", "source"])
            if allf is None else allf.copy())
    allf["ex_date"] = _as_date(allf["ex_date"])
    rep = {}

    # D2 -----------------------------------------------------------------
    be_rows = prepare_be(p, be)
    gap = be_gap_factors(acts, p, be_rows) if acts is not None else pd.DataFrame(
        columns=["isin", "ex_date", "drift"])
    drop = gap[gap["drift"]] if len(gap) else gap
    rebase = gap[~gap["drift"].astype(bool)] if len(gap) else gap
    rep["d2_be_rows_inserted"] = int(len(be_rows))
    rep["d2_factors_dropped"] = int(len(drop))
    rep["d2_factors_rebased"] = int(len(rebase))
    touched = set(gap["isin"]) | set(be_rows["isin"])
    dk = set(zip(drop["isin"], drop["ex_date"])) if len(gap) else set()
    rb = ({(i, e): (bc, ap) for i, e, bc, ap in
           zip(rebase["isin"], rebase["ex_date"], rebase["be_close"], rebase["adj_prev_close"])}
          if len(gap) else {})

    def _d2(df):
        if df is None or not (dk or rb):
            return df
        pcm = (df["source"] == "prevclose").to_numpy()
        keys = list(zip(df["isin"].astype(str), df["ex_date"]))
        df = df[np.array([not (m and k in dk) for m, k in zip(pcm, keys)], dtype=bool)].copy()
        for ix, k, m in zip(df.index, zip(df["isin"].astype(str), df["ex_date"]),
                            (df["source"] == "prevclose").to_numpy()):
            if m and k in rb:
                bc, ap = rb[k]
                df.at[ix, "factor"] = ap / bc
                df.at[ix, "prior_close"] = bc
        return df
    acts, allf = _d2(acts), _d2(allf)
    if len(be_rows):
        be_rows["dividend"] = be_dividends(be_rows, dividends, acts)
    rep["d2_be_dividends"] = int((be_rows["dividend"] > 0).sum()) if len(be_rows) else 0
    if len(be_rows):
        p = pd.concat([p, be_rows], ignore_index=True)
    have = set(zip(acts["isin"].astype(str), acts["ex_date"])) if acts is not None else set()
    jumps = transition_jumps(p, have)
    rep["d2_transition_actions"] = int(len(jumps))
    if len(jumps):
        add = jumps.drop(columns=["series"])
        acts = add if acts is None else pd.concat([acts, add], ignore_index=True)
        allf = pd.concat([allf, add], ignore_index=True)
        touched |= set(jumps["isin"])
        # A transition action on a BE row's date wins over its dividend too.
        jk = set(zip(jumps["isin"].astype(str), jumps["ex_date"]))
        clash = (p["series"].isin(NON_EQ).to_numpy() & (p["dividend"] > 0).to_numpy()
                 & np.array([(i, t) in jk for i, t in zip(p["isin"].astype(str), p["date"])],
                            dtype=bool)) if "series" in p.columns else None
        if clash is not None and clash.any():
            p.loc[clash, "dividend"] = 0.0
            rep["d2_be_dividends"] -= int(clash.sum())

    # D1 -----------------------------------------------------------------
    events, rejected = handovers(p, acts)
    rep["d1_handovers"] = len(events)
    rep["d1_rejected"] = rejected
    succ = {e["old_isin"]: e["new_isin"] for e in events}

    def final(i):
        seen = set()
        while i in succ and i not in seen:
            seen.add(i)
            i = succ[i]
        return i
    remap = {o: final(o) for o in succ}
    added = [{"isin": remap.get(e["new_isin"], e["new_isin"]), "ex_date": e["new_first"],
              "factor": e["factor"], "source": "purpose",
              "prior_close": np.nan, "adj_prev_close": np.nan}
             for e in events if e["factor"] != 1.0]
    rep["d1_split_factors_added"] = len(added)
    if remap:
        p["isin"] = p["isin"].map(lambda i: remap.get(i, i))
        for df in (acts, allf):
            if df is not None:
                df["isin"] = df["isin"].map(lambda i: remap.get(i, i))
        touched = {remap.get(i, i) for i in touched} | set(remap.values())
    if added:
        add = pd.DataFrame(added)
        acts = add if acts is None else pd.concat([acts, add], ignore_index=True)
        allf = pd.concat([allf, add], ignore_index=True)
    dup = p.duplicated(["date", "isin"], keep=False)
    if dup.any():
        raise ValueError(f"D1 re-keying produced {int(dup.sum())} duplicate (date, isin) rows")

    # adj_factor for every ISIN the repairs touched --------------------------
    if touched:
        m = p["isin"].isin(touched)
        sub = p.loc[m, ["isin", "date"]].reset_index()
        f = allf[allf["isin"].isin(touched) & (allf["factor"] > 0)]
        adj = _adj(sub, f)
        p.loc[sub["index"].values, "adj_factor"] = adj
    p["adj_close"] = p["close"] * p["adj_factor"]
    if "adj_open" in p.columns:
        p["adj_open"] = p["open"] * p["adj_factor"]
    rep["touched_isins"] = len(touched)
    p = p.sort_values(["date", "isin"], kind="mergesort").reset_index(drop=True)
    if acts is not None:
        acts = acts.reset_index(drop=True)
    rep["dropped"] = drop
    rep["rebased"] = rebase
    rep["jumps"] = jumps
    rep["events"] = events
    return p, acts, rep
