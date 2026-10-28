"""Adjusted total-return panel builder — Phase 1 task 1.3.

Contract
--------
build(root) -> writes data/panel/prices.parquet, long format:
    date, isin, symbol, open, high, low, close, prev_close, volume,
    turnover, adj_factor, adj_close, adj_open, dividend

    * one row per (date, isin) for series EQ
    * isin filled for pre-2011 rows via the symbol->ISIN map
      (data/panel/symbol_isin_map.parquet: symbol, isin, valid_from, valid_to);
      unmapped rows kept under a synthetic key and counted (section 15,
      2026-09-16; the stub's "dropped" predates that entry)
    * adj_factor = cumulative product of corporate-action factors with
      ex_date > date (so today's factor is 1.0)
    * dividend = cash per share going ex on that date, else 0

plausibility(panel) -> (halts: list[dict], findings: list[dict])
    halts: |session return| > 0.40 with no corporate action on that date;
           fill price of 0
    findings: >= 10 identical consecutive closes; every session gap

    Charter section 9 also halts on "a missing session for a HELD name". The
    panel does not know what is held, so gaps are findings here and `gaps()`
    hands the engine the table it halts on. The stub's original wording made
    this a panel-level halt; the charter wins (CLAUDE.md 1), and on real data
    it fires 42,826 times -- illiquid names skip sessions constantly.

wide(panel, field, start=None, end=None) -> DataFrame sessions x isin
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from pflab.data import data_dir

PANEL_COLUMNS = ["date", "isin", "symbol", "series", "instrument_type",
                 "open", "high", "low", "close", "prev_close", "volume", "turnover",
                 "adj_factor", "adj_close", "adj_open", "dividend"]

# Charter section 9 thresholds.
MOVE_HALT = 0.40          # a one-session move beyond +/-40% with no action
IDENTICAL_CLOSES = 10     # >= 10 identical consecutive closes is a finding
GAP_FINDING = 5           # a gap longer than this many sessions is a finding


# -- adjustment factors -------------------------------------------------
def adj_factor_series(panel: pd.DataFrame, factors: Optional[pd.DataFrame]) -> pd.Series:
    """Cumulative product of every factor with ex_date > the row's date.

    Multiplying a price by this puts it on today's share basis, so the
    most recent rows carry 1.0. Walking backwards from the end means a name
    with no actions costs nothing.
    """
    out = pd.Series(1.0, index=panel.index)
    if factors is None or len(factors) == 0:
        return out
    f = factors.copy()
    f["ex_date"] = pd.to_datetime(f["ex_date"]).dt.date
    f = f[f["factor"] > 0]
    for isin, g in f.groupby("isin", sort=False):
        rows = panel.index[panel["isin"].values == isin]
        if len(rows) == 0:
            continue
        dates = panel.loc[rows, "date"].values
        cum = np.ones(len(rows))
        for ex, fac in zip(g["ex_date"], g["factor"]):
            cum *= np.where(dates < ex, fac, 1.0)
        out.loc[rows] = cum
    return out


# -- build --------------------------------------------------------------
def build(root: Optional[Path] = None, start: Optional[date] = None,
          end: Optional[date] = None, factors: Optional[pd.DataFrame] = None,
          dividends: Optional[pd.DataFrame] = None, mapping: Optional[pd.DataFrame] = None,
          unmapped: str = "synthetic", write: bool = True) -> tuple:
    """Assemble the long panel. Returns (panel, report).

    `factors` is the corporate-action table (isin, ex_date, factor). Phase 1
    task 1.2 is unresolved -- the charter section 9 PREVCLOSE method fails its
    verification (docs/BUILT.md) -- so when it is None
    every adj_factor is 1.0 and the report says the panel is UNADJUSTED. The
    engine must refuse an unadjusted panel; a missed 1:1 bonus is a fabricated
    -50% in the section 3 momentum signal.
    """
    from pflab.data import bhavcopy, symbol_isin

    root = root or data_dir()
    from pflab.data import instruments
    raw = bhavcopy.load(start, end, root, series=instruments.PANEL_SERIES)
    raw["date"] = pd.to_datetime(raw["date"]).dt.date

    if mapping is None:
        mapping = _mapping(root)
    filled = symbol_isin.apply_map(raw, mapping)
    report = {"raw_rows": int(len(raw)),
              "mapping": symbol_isin.unmapped_report(filled)}

    # Charter section 15, 2026-09-16: unmapped rows are RETAINED under a
    # synthetic key, not dropped. All 251 unresolvable symbols delisted before
    # the ISIN era, so dropping them is survivorship bias (principle 6), worth
    # up to 14.6% of the section 2 universe. "drop" is kept for comparison.
    if unmapped == "drop":
        filled = filled[filled["isin"].notna()].copy()
    elif unmapped == "synthetic":
        syn = symbol_isin.synthetic_key(filled)
        filled = filled.copy()
        filled["isin"] = filled["isin"].astype("string").fillna(syn)
        filled = filled[filled["isin"].notna()]
    else:
        raise ValueError(f"unmapped must be 'drop' or 'synthetic', not {unmapped!r}")
    report["unmapped_policy"] = unmapped
    report["rows_after_map"] = int(len(filled))

    # One row per (date, isin). A same-day duplicate means two symbols shared
    # an ISIN; keep the more heavily traded line.
    dupes = filled.duplicated(subset=["date", "isin"], keep=False)
    report["duplicate_date_isin"] = int(dupes.sum())
    if dupes.any():
        filled = (filled.sort_values(["date", "isin", "turnover"],
                                     ascending=[True, True, False], kind="mergesort")
                        .drop_duplicates(["date", "isin"], keep="first"))

    p = filled.sort_values(["isin", "date"], kind="mergesort").reset_index(drop=True)
    # §2 / §15 2026-09-16: type every row, keep them all, and let the universe
    # filter select STK. ETFs trade under series EQ and would otherwise rank.
    p["instrument_type"] = instruments.classify(p["series"], p["isin"])
    report["instrument_types"] = p["instrument_type"].value_counts().to_dict()
    report["untyped_isin_rows"] = instruments.unknown_isin_rows(p)

    p["adj_factor"] = adj_factor_series(p, factors)
    report["adjusted"] = factors is not None and len(factors) > 0
    report["adjustment_events"] = 0 if factors is None else int(len(factors))

    p["adj_close"] = p["close"] * p["adj_factor"]
    p["adj_open"] = p["open"] * p["adj_factor"]
    p["dividend"], div_join = _dividend_column(p, dividends, root)
    report["dividend_rows"] = int((p["dividend"] > 0).sum())
    report["dividends"] = div_join

    p = p[PANEL_COLUMNS]
    if write:
        out = root / "panel" / "prices.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        p.to_parquet(out, index=False)
        report["path"] = str(out)
    report["rows"] = int(len(p))
    report["securities"] = int(p["isin"].nunique())
    report["sessions"] = int(p["date"].nunique())
    return p, report


def _mapping(root: Path) -> pd.DataFrame:
    """The symbol->ISIN map, built from the WHOLE bhavcopy and cached.

    Deliberately not truncated with the panel. It is identity reference data,
    not a feature: knowing a symbol's ISIN in 2015 leaks no return information
    into a 2008 decision, and charter section 9 mandates using the symbol-change
    history, which is inherently later-dated. Truncating it would instead drop
    every pre-2012 name by construction.
    """
    from pflab.data import bhavcopy, symbol_isin
    cached = root / "panel" / "symbol_isin_map.parquet"
    if cached.exists():
        return symbol_isin.load(root)
    full = bhavcopy.load(None, None, root, series=("EQ",))
    full["date"] = pd.to_datetime(full["date"]).dt.date
    mapping = symbol_isin.build(full, root=root)
    symbol_isin.write(mapping, root)
    return mapping


def _dividend_column(p: pd.DataFrame, dividends, root):
    """(column, join_report). §9 2026-09-16: dividend rows that cannot be
    joined to a panel ISIN are dropped and counted in the manifest."""
    empty = {"feed_rows": 0, "joined": 0, "dropped": 0, "join_rate": None}
    if dividends is None:
        f = root / "dividends" / "dividends.parquet"
        if not f.exists():
            return pd.Series(0.0, index=p.index), empty
        dividends = pd.read_parquet(f)
    if len(dividends) == 0:
        return pd.Series(0.0, index=p.index), empty
    d = dividends.rename(columns={"ex_date": "date",
                                  "dividend_per_share": "dividend"}).copy()
    d["date"] = pd.to_datetime(d["date"]).dt.date
    d = d.groupby(["isin", "date"], as_index=False)["dividend"].sum()
    panel_isins = set(p["isin"].dropna().unique())
    joinable = d["isin"].isin(panel_isins)
    rep = {"feed_rows": int(len(d)), "joined": int(joinable.sum()),
           "dropped": int((~joinable).sum()),
           "join_rate": round(float(joinable.mean()), 4),
           "dropped_isins": int(d.loc[~joinable, "isin"].nunique())}
    merged = p[["isin", "date"]].merge(d[joinable], on=["isin", "date"], how="left")
    return merged["dividend"].fillna(0.0).values, rep


# -- plausibility (charter section 9) -----------------------------------
def plausibility(panel: pd.DataFrame, factors: Optional[pd.DataFrame] = None,
                 calendar=None) -> tuple:
    """(halts, findings). A halt stops a run; a finding goes in the manifest."""
    halts: list[dict] = []
    findings: list[dict] = []
    p = panel.sort_values(["isin", "date"], kind="mergesort")

    action = set()
    if factors is not None and len(factors):
        f = factors.copy()
        f["ex_date"] = pd.to_datetime(f["ex_date"]).dt.date
        action = set(zip(f["isin"], f["ex_date"]))

    # fill price of 0
    for col in ("open", "close"):
        bad = p[(p[col].notna()) & (p[col] <= 0)]
        for r in bad.itertuples(index=False):
            halts.append({"kind": "zero_price", "isin": r.isin, "date": r.date,
                          "field": col, "value": getattr(r, col)})

    g = p.groupby("isin", sort=False)
    prev_close = g["adj_close"].shift(1)
    ret = p["adj_close"] / prev_close - 1.0
    big = p[(ret.abs() > MOVE_HALT) & prev_close.notna()]
    for r, rr in zip(big.itertuples(index=False), ret[big.index]):
        if (r.isin, r.date) in action:
            continue          # explained by a corporate action
        halts.append({"kind": "move", "isin": r.isin, "date": r.date,
                      "symbol": r.symbol, "return": float(rr)})

    # identical consecutive closes. Only the long runs are aggregated: a
    # groupby over all ~8M single-row runs costs minutes for nothing.
    # to_numpy: the isin column is pyarrow-backed once synthetic keys are
    # filled in, and pyarrow booleans have no cumsum kernel.
    same = (p["close"].eq(g["close"].shift(1))
            & p["isin"].eq(p["isin"].shift(1))).to_numpy(dtype=bool, na_value=False)
    run_id = pd.Series((~same).cumsum(), index=p.index)
    counts = run_id.value_counts()
    long_runs = counts.index[counts >= IDENTICAL_CLOSES]
    if len(long_runs):
        sub = p[run_id.isin(long_runs)].assign(_r=run_id[run_id.isin(long_runs)])
        for _r, gg in sub.groupby("_r", sort=False):
            findings.append({"kind": "identical_closes", "isin": gg["isin"].iloc[0],
                             "symbol": gg["symbol"].iloc[0], "sessions": int(len(gg)),
                             "from": gg["date"].min(), "to": gg["date"].max(),
                             "close": float(gg["close"].iloc[0])})

    # Session gaps. Charter section 9 halts on "a missing session for a HELD
    # name", which only the engine knows, so every gap is reported as a
    # finding here and `gaps()` gives the engine what it needs to halt.
    findings.extend(gaps(p, calendar) if calendar is not None else [])
    return halts, findings


def gaps(panel: pd.DataFrame, calendar) -> list[dict]:
    """Sessions a name skipped while the market was open.

    The engine halts when one of these belongs to a name it holds; a long gap
    at the end of a name's life is a delisting, handled by charter section 9.
    """
    pos = {d: i for i, d in enumerate(calendar.sessions)}
    p = panel.sort_values(["isin", "date"], kind="mergesort")
    p = p[p["date"].isin(pos)]
    ipos = p["date"].map(pos)
    gap = ipos.groupby(p["isin"].values).diff()
    hit = gap > 1
    if not hit.any():
        return []
    rows = p[hit]
    out = []
    for r, gg in zip(rows.itertuples(index=False), gap[hit]):
        n = int(gg) - 1
        out.append({"kind": "gap" if n > GAP_FINDING else "short_gap",
                    "isin": r.isin, "symbol": r.symbol, "date": r.date,
                    "missing_sessions": n})
    return out


# -- access -------------------------------------------------------------
def wide(panel: pd.DataFrame, field: str, start: Optional[date] = None,
         end: Optional[date] = None) -> pd.DataFrame:
    """sessions x isin matrix of one field."""
    p = panel
    if start is not None:
        p = p[p["date"] >= start]
    if end is not None:
        p = p[p["date"] <= end]
    return p.pivot_table(index="date", columns="isin", values=field, aggfunc="last")


def load(root: Optional[Path] = None) -> pd.DataFrame:
    root = root or data_dir()
    return pd.read_parquet(root / "panel" / "prices.parquet")


# -- keeping it current (S65) -----------------------------------------------
def _sig(df: Optional[pd.DataFrame]) -> str:
    """A short fingerprint of a table's rows (order does not matter)."""
    import hashlib
    if df is None or len(df) == 0:
        return "empty"
    h = pd.util.hash_pandas_object(df.reset_index(drop=True).astype(str), index=False).sort_values().to_numpy()
    return hashlib.sha256(h.tobytes()).hexdigest()[:16]


def _last_date(path: Path) -> Optional[date]:
    import pyarrow.parquet as pq
    if not path.exists():
        return None
    d = pq.read_table(path, columns=["date"]).column("date").to_pandas()
    return pd.to_datetime(d).max().date()


def refresh(root: Optional[Path] = None, max_age_days: int = 30, today: Optional[date] = None, build_fn=None) -> dict:
    """Keep `panel/prices.parquet` current without anyone building it by hand (the collector calls this nightly).

    Prices are back-adjusted to today's share basis, so a new split or bonus rewrites every earlier row of that name: the panel is
    rebuilt WHOLE (about 4 minutes) when the corporate-action factors changed, when a dividend with an ex-date inside the panel's
    range arrived late, when there is no panel yet, or every `max_age_days`. Otherwise only the new sessions are built and appended
    (seconds). The file is replaced atomically, so a reader never sees half of it. A record of what it was built from is kept in
    `panel/build_state.json`."""
    import json
    root = root or data_dir()
    today = today or date.today()
    build_fn = build_fn or build
    path = root / "panel" / "prices.parquet"
    state_path = root / "panel" / "build_state.json"
    fpath, dpath = root / "corporate_actions" / "factors.parquet", root / "dividends" / "dividends.parquet"
    factors = pd.read_parquet(fpath) if fpath.exists() else None
    divs = pd.read_parquet(dpath) if dpath.exists() else None
    last = _last_date(path)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    def divs_to(d: Optional[date]) -> Optional[pd.DataFrame]:
        if divs is None or d is None or "ex_date" not in divs:
            return divs
        return divs[pd.to_datetime(divs["ex_date"]).dt.date <= d]

    reason = None
    if last is None:
        reason = "no panel yet"
    elif not state:
        reason = "no build record"
    elif state.get("factors") != _sig(factors):
        reason = "corporate actions changed"
    elif state.get("dividends") != _sig(divs_to(last)):
        reason = "a dividend inside the panel's range arrived late"
    elif (today - date.fromisoformat(state["built_on"])).days > max_age_days:
        reason = f"older than {max_age_days} days"

    if reason:
        p, rep = build_fn(root, factors=factors, dividends=divs, write=False)
        mode = "full"
    else:
        p, rep = build_fn(root, start=last + pd.Timedelta(days=1).to_pytimedelta(), factors=factors, dividends=divs, write=False)
        mode = "append"
        if len(p) == 0:
            return {"mode": "current", "last": str(last)}
        old = pd.read_parquet(path)
        old["date"] = pd.to_datetime(old["date"]).dt.date
        p = pd.concat([old, p[p["date"] > last]], ignore_index=True).sort_values(["isin", "date"], kind="mergesort").reset_index(drop=True)
    new_last = pd.to_datetime(p["date"]).max().date()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("prices.parquet.tmp")
    p.to_parquet(tmp, index=False)
    tmp.replace(path)
    state = {"factors": _sig(factors), "dividends": _sig(divs_to(new_last)), "last_date": str(new_last),
             "built_on": today.isoformat() if mode == "full" else state["built_on"]}
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return {"mode": mode, "why": reason, "rows": int(len(p)), "last": str(new_last)}
