"""E5-A §4 labels, with the interval each one spans.

For month-end M and horizon h, M_h is the h-th month-end after M. The label
is what a holding bought at the open of the session after M earns if sold at
the open of the session after M_h, under the engine's own valuation:

  * adjusted prices (`adj_open`), so splits and bonuses are not returns;
  * dividends as cash on the ex-date, not reinvested, on the holding carried
    into that session: ex-dates in (label_start, label_end];
  * E1 §9 as amended by E1 §15 (2026-09-17 and 2026-09-27 (b)) -- the rule
    the engine now implements. A name with no row at the exit session stays
    held; its exit fills at the open of the first session it trades again;
    on its 250th consecutive missing session it is written down to zero.
    The label then ends at the write-down, worth zero plus the dividends
    received. (§4's parenthesis paraphrases the pre-amendment E1 §9 --
    "exits at its last close on the session after its last row" -- which the
    engine no longer does; see the readiness note.)

Each row stores `label_start`, `label_end` and `observable_at` (the open of
`label_end`). The model is fit on each cross-section's centred percentile of
the excess return over U(M)'s median, so a row's TARGET needs every label in
U(M): `target_observable_at` is the latest `observable_at` in U(M), and is
missing while any label in U(M) is not yet known.

`kind`:
  open        sold at the open of the session after M_h
  resumed     no row then; sold at the first open it traded again
  write_down  250 consecutive missing sessions while held: worth zero
  no_entry    no EQ open at the session after M: the engine could not buy it
  pending     not yet knowable from this panel (never selected for training)
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Sequence

import numpy as np
import pandas as pd

from pflab.backtest import engine
from pflab.ranker.features import dated, month_ends

HORIZONS = (1, 3, 12)
LABEL_COLUMNS = ["isin", "month_end", "h", "kind", "label_start", "label_end",
                 "observable_at", "ret", "excess", "target", "xs_complete",
                 "target_observable_at"]
DEFINED = ("open", "resumed", "write_down")


def _arrays(panel: pd.DataFrame, names, sessions, series) -> dict:
    """Per ISIN, its rows as session positions with what a label reads."""
    sub = panel.loc[panel["isin"].isin(names),
                    ["date", "isin", "series", "open", "adj_open", "adj_factor",
                     "dividend"]].sort_values(["isin", "date"], kind="mergesort")
    sess = np.array(sessions, dtype="datetime64[D]")
    pos = np.searchsorted(sess, np.array(sub["date"].tolist(), dtype="datetime64[D]"))
    open_ok = (sub["open"].to_numpy(dtype=float) > 0) & \
        np.isfinite(sub["adj_open"].to_numpy(dtype=float))
    eq = sub["series"].isin(tuple(series)).to_numpy()
    div = (sub["dividend"].fillna(0.0).to_numpy(dtype=float)
           * sub["adj_factor"].to_numpy(dtype=float))
    out = {}
    isins = sub["isin"].to_numpy()
    bounds = np.flatnonzero(np.r_[True, isins[1:] != isins[:-1], True])
    adj_open = sub["adj_open"].to_numpy(dtype=float)
    for a, b in zip(bounds[:-1], bounds[1:]):
        out[isins[a]] = {"pos": pos[a:b], "adj_open": adj_open[a:b],
                         "open_ok": open_ok[a:b], "eq": eq[a:b],
                         "cumdiv": np.cumsum(np.nan_to_num(div[a:b]))}
    return out


def _one(a: dict, s0: int, exit_at: int, n_sessions: int, confirm: int):
    """(kind, start_pos, end_pos, ret) for one holding: bought at s0's open,
    to be sold at exit_at's open. exit_at None = M_h is beyond the panel."""
    if s0 >= n_sessions:
        return "pending", None, None, np.nan
    pos = a["pos"]
    i0 = int(np.searchsorted(pos, s0))
    if i0 >= len(pos) or pos[i0] != s0 or not a["open_ok"][i0] or not a["eq"][i0]:
        return "no_entry", s0, None, np.nan
    if exit_at is None:
        return "pending", s0, None, np.nan
    buy = a["adj_open"][i0]

    def value(end_pos, price):
        k = int(np.searchsorted(pos, end_pos, side="right")) - 1
        divs = a["cumdiv"][k] - a["cumdiv"][i0]
        return (price + divs) / buy - 1.0

    iE = int(np.searchsorted(pos, exit_at))
    held = pos[i0:iE]                      # rows while held, all before exit_at
    gaps = np.diff(held) - 1
    hit = np.flatnonzero(gaps >= confirm)
    if hit.size:                           # written down before the exit date
        w = int(held[hit[0]]) + confirm
        return "write_down", s0, w, value(w, 0.0)
    prev, j = int(held[-1]), iE
    while True:
        if j >= len(pos):
            w = prev + confirm
            if w < n_sessions:
                return "write_down", s0, w, value(w, 0.0)
            return "pending", s0, None, np.nan
        if pos[j] - prev - 1 >= confirm:
            w = prev + confirm
            return "write_down", s0, w, value(w, 0.0)
        if a["open_ok"][j]:
            e = int(pos[j])
            return ("open" if e == exit_at else "resumed"), s0, e, \
                value(e, a["adj_open"][j])
        prev, j = int(pos[j]), j + 1


def build_labels(panel: pd.DataFrame, config: dict,
                 universe: Dict[date, pd.Index],
                 horizons: Sequence[int] = HORIZONS) -> pd.DataFrame:
    """Every (ISIN in U(M), M, h) label, with its interval (LABEL_COLUMNS)."""
    panel = dated(panel)
    strat = config.get("strategy", {})
    confirm = int(strat.get("delist_confirm_sessions", engine.DELIST_CONFIRM_SESSIONS))
    series = config.get("universe", {}).get("series", ["EQ"])
    sessions = sorted(panel["date"].unique())
    n = len(sessions)
    spos = {d: i for i, d in enumerate(sessions)}
    mes = month_ends(panel)
    mpos = {m: i for i, m in enumerate(mes)}
    names = sorted(set().union(*[set(v) for v in universe.values()])) if universe else []
    arrs = _arrays(panel, names, sessions, series)

    recs = []
    for m in sorted(universe):
        s0 = spos[m] + 1
        for h in horizons:
            j = mpos[m] + h
            exit_at = (spos[mes[j]] + 1) if j < len(mes) else None
            if exit_at is not None and exit_at >= n:
                exit_at = None
            for isin in universe[m]:
                kind, a, b, r = _one(arrs[isin], s0, exit_at, n, confirm)
                recs.append((isin, m, h, kind, a, b, r))
    if not recs:
        return pd.DataFrame(columns=LABEL_COLUMNS)
    df = pd.DataFrame(recs, columns=["isin", "month_end", "h", "kind",
                                     "_s", "_e", "ret"])
    sess = np.array(sessions + [None], dtype=object)
    df["label_start"] = sess[df["_s"].fillna(n).astype(int)]
    df["label_end"] = sess[df["_e"].fillna(n).astype(int)]
    # the open of label_end; for a name the engine could not buy, the open
    # at which that was known
    df["observable_at"] = np.where(df["kind"] == "no_entry", df["label_start"],
                                   df["label_end"])
    df = df.drop(columns=["_s", "_e"])
    return _cross_sections(df)


def _cross_sections(df: pd.DataFrame) -> pd.DataFrame:
    """Excess over U(M)'s median, the centred percentile, and when the whole
    cross-section's target is observable."""
    df = df.copy()
    df["excess"] = np.nan
    df["target"] = np.nan
    df["xs_complete"] = False
    df["target_observable_at"] = None
    for (m, h), g in df.groupby(["month_end", "h"], sort=False):
        if (g["kind"] == "pending").any():
            continue
        ok = g["kind"].isin(DEFINED) & np.isfinite(g["ret"].astype(float))
        idx = g.index[ok]
        df.loc[g.index, "xs_complete"] = True
        df.loc[g.index, "target_observable_at"] = max(g["observable_at"])
        if len(idx) == 0:
            continue
        r = df.loc[idx, "ret"].astype(float)
        df.loc[idx, "excess"] = r - float(np.median(r))
        df.loc[idx, "target"] = (r.rank(method="average") - 0.5) / len(r) - 0.5
    df = df.sort_values(["month_end", "h", "isin"], kind="mergesort").reset_index(drop=True)
    return df[LABEL_COLUMNS]


def summary(labels: pd.DataFrame) -> dict:
    """Counts reported in the store's meta: kinds, and complete cross-sections."""
    if labels.empty:
        return {}
    out = {"kinds": {f"h{h}": {k: int(v) for k, v in g["kind"].value_counts().items()}
                     for h, g in labels.groupby("h")}}
    xs = labels.groupby(["h", "month_end"])["xs_complete"].first()
    out["cross_sections"] = {f"h{h}": {"total": int(len(s)), "complete": int(s.sum())}
                             for h, s in xs.groupby(level=0)}
    return out
