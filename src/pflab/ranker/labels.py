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
    received. (E5-A §14, 2026-09-29: §4 states this rule.)

Each row stores `label_start`, `label_end` and `observable_at` (the open of
`label_end`). The model's TARGET is not stored: it is each cross-section's
centred percentile over the labels observable at the fit date R
(`targets_at`), so a label still pending at R -- a write-down not yet
confirmed -- is simply absent from that fit and joins later ones once it
resolves; it never holds back the rest of its month (§14, 2026-09-29).

U(M) holds only names with a panel row at M (`features.universe_by_month`).
A name with a row at M that never opens again gets the engine's label: -100%,
observable on its 250th consecutive missing session (`no_open`). Dropping it
would train on survivors only.

`kind`:
  open        sold at the open of the session after M_h
  resumed     no row then; sold at the first open it traded again
  write_down  250 consecutive missing sessions while held: worth zero
  no_open     no open at the session after M and none before its 250th
              missing session: -100%
  no_entry    no EQ open at the session after M but it opens later (a BE/BZ
              session, a short gap): the engine could not buy it; no label
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
                 "observable_at", "ret"]
DEFINED = ("open", "resumed", "write_down", "no_open")


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


def _no_entry(a: dict, s0: int, i0: int, n_sessions: int, confirm: int):
    """No EQ open at s0, the session after M (where U(M) guarantees a row).
    If the name opens again before its 250th missing session the engine
    simply could not buy it: `no_entry`, no label, known at that open. If it
    never does, the engine's label: -100% on the 250th missing session."""
    pos, prev, j = a["pos"], s0 - 1, i0
    while True:
        if j >= len(pos) or pos[j] - prev - 1 >= confirm:
            w = prev + confirm
            if w < n_sessions:
                return "no_open", s0, w, -1.0
            return "pending", s0, None, np.nan
        if a["open_ok"][j]:
            return "no_entry", s0, int(pos[j]), np.nan
        prev, j = int(pos[j]), j + 1


def _one(a: dict, s0: int, exit_at: int, n_sessions: int, confirm: int):
    """(kind, start_pos, end_pos, ret) for one holding: bought at s0's open,
    to be sold at exit_at's open. exit_at None = M_h is beyond the panel."""
    if s0 >= n_sessions:
        return "pending", None, None, np.nan
    pos = a["pos"]
    i0 = int(np.searchsorted(pos, s0))
    if i0 >= len(pos) or pos[i0] != s0 or not a["open_ok"][i0] or not a["eq"][i0]:
        return _no_entry(a, s0, i0, n_sessions, confirm)
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
    # at which it traded again (when "could not buy" became "no_entry")
    df["observable_at"] = df["label_end"]
    df.loc[df["kind"] == "no_entry", "label_end"] = None
    df = df.drop(columns=["_s", "_e"])
    df = df.sort_values(["month_end", "h", "isin"], kind="mergesort").reset_index(drop=True)
    return df[LABEL_COLUMNS]


def targets_at(labels: pd.DataFrame, R) -> pd.DataFrame:
    """The labels observable by the close of R, each with its cross-section's
    `excess` (over the median of the observable labels of that (M, h)) and
    `target`, the centred percentile (rank - 0.5)/n - 0.5 among them. What a
    fit at R trains on; a label observable after R is not read at all."""
    L = labels[labels["kind"].isin(DEFINED)]
    ok = np.array([o is not None and o <= R for o in L["observable_at"]], dtype=bool)
    L = L[ok & np.isfinite(L["ret"].to_numpy(dtype=float))].copy()
    g = L.groupby(["month_end", "h"], sort=False)["ret"]
    L["excess"] = L["ret"] - g.transform("median")
    L["target"] = (g.rank(method="average") - 0.5) / g.transform("size") - 0.5
    return L


def summary(labels: pd.DataFrame) -> dict:
    """Counts reported in the store's meta: kinds, and cross-sections with a label."""
    if labels.empty:
        return {}
    out = {"kinds": {f"h{h}": {k: int(v) for k, v in g["kind"].value_counts().items()}
                     for h, g in labels.groupby("h")}}
    d = labels[labels["kind"].isin(DEFINED)]
    out["cross_sections"] = {f"h{h}": {"total": int(labels.loc[labels["h"] == h,
                                                             "month_end"].nunique()),
                                       "with_a_label": int(g["month_end"].nunique())}
                             for h, g in d.groupby("h")}
    return out
