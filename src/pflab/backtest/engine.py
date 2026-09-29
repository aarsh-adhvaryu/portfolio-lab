"""Daily mark-to-market backtest engine — Phase 2 task 2.1.

Contract
--------
run(config, period, panel, indices, cost_model, tax_policy) -> RunResult

Loop over sessions in the truncated panel, trading only inside
[period.start, period.end] (history before start feeds signals):

  each session t:
    0. corporate actions and dividends going ex on t, on the holdings carried
       into t, BEFORE any of t's trades (E1 §15, 2026-09-27); then exits
       deferred for want of a quote are retried at open(t)
    1. if t is the first session of a month:
         a. if t is the first session of a new FY: settle FY(t-1) on the
            LotBook; deduct liability from cash (may go negative)
         b. credit SIP to cash (fills a negative balance first)
         c. execute the decision made on the previous month-end M:
              sells first (band exits, delisting exits) at open(t)
              then buys from portfolio.construct.buy_list at open(t),
              subject to the RISK_OFF flag from M and the ADV guard
            record reference_price=close(M), fill_price=open(t)
    2. suspension: a held name missing for the confirm window is written
       down to zero -- a valuation, not a sale
    3. accrue cash at cash_rate_annual / 365 on a positive balance; the
       interest is taxable income of the FY it accrues in
    4. mark to market; append (t, equity_value, cash, external_flow)
    5. if t is a month-end M: compute eligibility, momentum ranks, RISK_OFF
       and the decision; store it with the inputs it used

  at the end: simulate liquidation tax on the last session (on every book,
  including an all-cash one; a failure raises); produce three
  NAV paths: pre-tax, after-tax (taxes paid), liquidation-adjusted.

Prices
------
Signals read `adj_close` (a continuous series). Execution and marking read
RAW `open` / `close`, because the lot book holds real share counts bought at
real prices, and §7 fixes reference = close(M), fill = open(M+1). Corporate
actions are therefore explicit events on the lot book, not a silent rescaling
of the ledger -- see `_apply_ex_date_events` for the four §9 rules.

Lookahead guarantee: nothing dated after t is read on session t.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab.backtest import hooks as hk
from pflab.data import universe as uni
from pflab.data.index_membership import with_bound as im_with_bound
from pflab.portfolio.construct import buy_list, buy_list_weighted
from pflab.signals.momentum import momentum_panel, rank_desc
from pflab.signals.vol_scaled import (momentum_ratios, standardise,
                                      vol_scaled_ratios)
from pflab.tax.india_lots import LotBook, fy_of

# §9 operational thresholds. A name whose rows stop is not known to have
# stopped until enough sessions pass; the charter's "session after its last
# row" would fire on every one-session gap (44,336 in the panel).
DELIST_CONFIRM_SESSIONS = 250
DELIST_CONFIRM_SESSIONS_S9 = 20
# A PREVCLOSE factor within this of a standard ratio is a share-count action
# the PURPOSE text failed to name, not a cash event.
STANDARD_RATIOS = (1/2, 1/3, 1/4, 1/5, 1/10, 2/3, 3/4, 4/5, 2/5, 1/1.5, 1/2.5)
RATIO_SNAP_TOL = 0.01


class ADVDataError(RuntimeError):
    """A name the engine is about to buy has an ADV of 0 or NaN.

    §7 as amended 2026-09-17 skips a buy that is merely too large, but this is
    a data error, not a size problem: an eligible name has 250 sessions of
    history behind it (§2), so it cannot have no traded value. Halting is the
    only honest response.
    """


@dataclass
class RunResult:
    equity: pd.DataFrame
    trades: pd.DataFrame
    decisions: List[dict]
    taxes: pd.DataFrame
    warnings: List[dict]
    config: dict = field(default_factory=dict)
    hooks_active: Dict[str, bool] = field(default_factory=dict)
    adv_skips: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(
        columns=["date", "isin", "buy_value", "adv", "ratio", "planned"]))
    realised: List = field(default_factory=list)
    universe_pre: Optional[dict] = None
    # E3-R: per-month T/V/B, the gear, and the months V was undefined (§11 (a)).
    # None for every run that is not in gears mode.
    regime: Optional[dict] = None


@dataclass
class _State:
    """What a hook may read (hooks.EngineState)."""
    date: Optional[date] = None
    cash: float = 0.0
    positions: Dict[str, int] = field(default_factory=dict)
    holdings_value: Dict[str, float] = field(default_factory=dict)
    # E1-P §4: N1/N2 trigger on a position's move from its OWN cost basis, so
    # a hook needs the basis as well as the mark. Per share, because the
    # trigger is a price move ("down 20%"), and quantity-weighted across the
    # position's lots, because a full-position sale realises all of them.
    cost_basis: Dict[str, float] = field(default_factory=dict)
    # E1-P §3 as resolved at the 2026-09-19 lock: S4 tests "the oldest lot's
    # own unrealised gain, not the position average", so a hook needs the
    # lots themselves, not just their aggregate. Read-only by contract, and
    # still only ever the portfolio as of now.
    lots: Dict[str, list] = field(default_factory=dict)


def _cfg(config: dict, path: str, default=None):
    node = config
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _snaps_to_standard_ratio(factor: float) -> bool:
    return any(abs(factor / r - 1.0) <= RATIO_SNAP_TOL for r in STANDARD_RATIOS)


def _wide(panel: pd.DataFrame, field_name: str) -> pd.DataFrame:
    return panel.pivot_table(index="date", columns="isin",
                             values=field_name, aggfunc="last")


def precompute_universe(panel: pd.DataFrame, config, membership=None) -> dict:
    """Everything §2's filter needs, computed once instead of per month-end.

    `universe.eligible` re-groups the whole growing panel at every decision,
    which is ~0.9 s on the development panel and does not finish a sweep. The
    same three statistics are per-row cumulative, so they can be computed once
    and read off at each month-end:

        n           rows so far for this ISIN      (cumcount + 1)
        turnover    mean of its last 126 rows      (rolling, min_periods=1)
        close       its most recent close

    Forward-filling reproduces `eligible`'s semantics exactly: a name that has
    stopped trading keeps the statistics of its last row, because `eligible`
    groups every row dated <= M. `tests/test_universe_fastpath.py` asserts the
    two agree at every month-end.
    """
    series = tuple(_cfg(config, "universe.series", ["EQ"]))
    window = int(_cfg(config, "universe.turnover_window", 126))
    from pflab.data import instruments
    d = panel[panel["series"].isin(series)]
    if "instrument_type" in d.columns:
        d = d[d["instrument_type"].isin(instruments.UNIVERSE_TYPES)]
    d = d.sort_values(["isin", "date"], kind="mergesort")
    g = d.groupby("isin", sort=False)
    d = d.assign(
        _n=g.cumcount() + 1,
        _roll=g["turnover"].transform(
            lambda s: s.rolling(window, min_periods=1).mean()))
    idx = sorted(panel["date"].unique())
    def w(col):
        return (d.pivot_table(index="date", columns="isin", values=col,
                              aggfunc="last").reindex(idx).ffill())
    out = {"n": w("_n"), "turnover": w("_roll"), "close": w("close"),
           "mode": str(_cfg(config, "universe.mode", "turnover_top_n"))}
    if out["mode"] == "index_members":
        # E1b §3. The table must already be truncated at the period end by
        # periods.truncate_membership; the engine never loads it itself.
        if membership is None or len(membership) == 0:
            raise ValueError(
                "universe.mode='index_members' (charter E1b §3) needs a "
                "point-in-time membership table; pass membership= to run(), "
                "truncated by pflab.eval.periods.truncate_membership")
        out["membership"] = membership
        out["index"] = str(_cfg(config, "universe.index", "NIFTY200"))
        bound = str(_cfg(config, "universe.membership_bound", "earliest"))
        if bound not in ("earliest", "latest"):
            raise ValueError(f"unknown universe.membership_bound {bound!r}")
        out["membership"] = im_with_bound(membership, bound)
        out["membership_bound"] = bound
    elif out["mode"] != "turnover_top_n":
        raise ValueError("unknown universe.mode %r" % (out["mode"],))
    return out


def eligible_at(pre: dict, m, min_sessions: int, top_n: int, min_price: float,
                exclude=None):
    """§2's eligible set at month-end `m`, from `precompute_universe`.

    `exclude` is E2-A §3's red-flag set: names carrying a flag usable in the
    trailing window at `m`. It is applied AFTER the turnover ranking, not
    before, so excluding a name does not promote a thinner one into the top
    `top_n` -- the universe is still "the 500 most traded", with some of them
    ineligible. Applying it first would silently change §2's universe as well
    as §3's eligibility, which would make E2-A two changes.
    """
    if m not in pre["n"].index:
        return pd.Index([])
    n = pre["n"].loc[m]
    close = pre["close"].loc[m]
    turn = pre["turnover"].loc[m]
    ok = (n >= min_sessions) & (close > min_price)
    if pre.get("mode") == "index_members":
        # §3: membership IS the universe -- no turnover ranking, so a thin
        # member is eligible and a heavily traded non-member is not.
        from pflab.data import index_membership as im
        members = im.members_at(pre["membership"], pre["index"], m)
        if not members:
            return pd.Index([])
        keep = ok.fillna(False) & pd.Series(ok.index.isin(members), index=ok.index)
        sel = ok.index[keep]
        if exclude:
            sel = [i for i in sel if i not in exclude]
        return pd.Index(sorted(sel))
    ranked = turn[ok.fillna(False)].dropna().sort_values(ascending=False).head(top_n)
    idx = ranked.index
    if exclude:
        idx = [i for i in idx if i not in exclude]
    return pd.Index(sorted(idx))


def run(config, period, panel, indices, cost_model, tax_policy,
        actions=None, hooks=None, membership=None, scores=None) -> RunResult:
    """One backtest. `panel` must already be truncated at `period.end` by
    pflab.eval.periods.truncate_end -- the engine never loads data itself.

    `scores` is E5-A's (§5, §7): {"scores": {M: Series}, "fallback": {M: bool}}
    for `strategy.signal = "precomputed"`, and must be None otherwise."""
    hooks = hooks or hk.from_config(config)
    strat = config.get("strategy", {})
    lookback = int(strat.get("lookback_sessions", 252))
    skip = int(strat.get("skip_sessions", 21))
    n_hold = int(strat.get("n_hold", 25))
    band = int(strat.get("band_exit_rank", 50))
    max_buys = int(strat.get("max_buys_per_month", 6))
    sip = float(strat.get("sip_amount", 50_000.0))
    cash_rate = float(strat.get("cash_rate_annual", 0.06))
    trend_filter = strat.get("trend_filter", "sma10")
    delisting = strat.get("delisting", "last_close")
    # Both values now write down at the confirm window and differ only in its
    # default length (E1 §15, 2026-09-27); the names are kept so every config
    # and manifest still reads.
    if delisting not in ("last_close", "total_loss"):
        raise ValueError(f"unknown strategy.delisting={delisting!r}")
    confirm = int(strat.get("delist_confirm_sessions",
                            DELIST_CONFIRM_SESSIONS_S9 if delisting == "total_loss"
                            else DELIST_CONFIRM_SESSIONS))
    max_adv = float(_cfg(config, "universe.max_adv_fraction", 0.01))
    # E1c §3. Every default below is E1's, so an E1 or E1b config reaches
    # exactly the code it reached before.
    signal = strat.get("signal", "mom_12_1")
    rebalance = strat.get("rebalance", "monthly_band")
    # E5-A §5/§7: a ranking computed outside the engine (the learned ranker),
    # with a per-decision fallback to the STACK's own signal, named by
    # `fallback_signal`, until §5's minimum training set exists. Everything
    # below then builds that stack signal, exactly as the stack's own config
    # would, and the precomputed scores are wrapped around it.
    precomputed = signal == "precomputed"
    if precomputed:
        if scores is None:
            raise ValueError("strategy.signal='precomputed' needs scores= "
                             "(E5-A §7): {'scores': {M: Series}, 'fallback': {M: bool}}")
        if rebalance != "monthly_band":
            raise ValueError("a precomputed signal replaces E1 §4's ranking only; "
                             "rebalance must be monthly_band")
        signal = strat.get("fallback_signal")
        if signal is None:
            raise ValueError("strategy.fallback_signal must name the stack's "
                             "signal (E5-A §5: the stack's own rank is the fallback)")
    elif scores is not None:
        raise ValueError(f"scores= given, but strategy.signal={signal!r} is "
                         f"not 'precomputed'")
    weighting = strat.get("weighting", "equal")
    selection_n = int(strat.get("selection_n", n_hold))
    weight_cap = float(strat.get("weight_cap", 0.05))
    rebalance_months = tuple(strat.get("rebalance_months", (6, 12)))
    # E1c §3 as amended 2026-09-19: ONE lag in total. The score's skip of the
    # most recent month IS the lag, so there is no separate score-date lag
    # and the default is 0. Any lag is counted in month-end positions.
    score_lag_months = int(strat.get("score_lag_months", 0))
    score_order = strat.get("score_order", "average_then_z")
    # E1d §5 S1/S2: the two components of the §3 score, one at a time. The
    # default is E1c §3's own pair, so every existing config reaches the
    # identical code path. With a single window the two §3 orders coincide
    # (averaging one z-score is that z-score), which is correct, not a
    # degenerate case to guard against.
    score_windows = tuple(int(w) for w in strat.get("score_windows", (126, 252)))
    if not score_windows:
        raise ValueError("strategy.score_windows must name at least one window")
    # E1c §3 as amended 2026-09-21: weights proportional to max(score, 0).
    on_negative = strat.get("weighting_negative", "zero")

    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"]).dt.date
    if panel.empty:
        raise ValueError("panel is empty after truncation")
    if panel["date"].max() > period.end:
        raise ValueError(f"panel carries {panel['date'].max()} past period end "
                         f"{period.end}; truncate_end is the only loader")

    sessions = sorted(panel["date"].unique())
    close_w = _wide(panel, "close")
    open_w = _wide(panel, "open")
    adj_w = _wide(panel, "adj_close")
    turn_w = _wide(panel, "turnover")
    div_map = _dividend_map(panel)
    act_map = _action_map(actions)
    # D2: sessions on which a name trades outside `universe.series` (BE/BZ
    # rows inserted by data.repairs). Empty for any all-EQ panel.
    no_buy: Dict[date, frozenset] = {}
    if "series" in panel.columns:
        off = panel[~panel["series"].isin(tuple(_cfg(config, "universe.series", ["EQ"])))]
        no_buy = {d: frozenset(g) for d, g in off.groupby("date")["isin"]}

    risk_off = _risk_off_series(indices, sessions, trend_filter)
    # Hoisted out of the loop. momentum_panel is pure backward shifts, so its
    # value at date t is identical whether computed on the full truncated frame
    # or on the frame up to t -- no lookahead is introduced.
    # E1 and every charter before E1c rank raw 12-1 momentum; `score_fn`
    # stays None and the decision functions take exactly the path they took
    # before E1c existed.
    score_fn = None
    if signal == "mom_12_1":
        mom_w = momentum_panel(adj_w, lookback=lookback, skip=skip)
    elif signal == "lottery":
        # DIAGNOSTIC ONLY, never a charter signal (E1 gap attribution,
        # 2026-09-27): a fixed pseudo-random score per ISIN, defined exactly
        # where 12-1 momentum is, so the eligible set, dates, band and cash
        # mechanics are E1's and only WHICH names are picked changes. Fixed
        # per name so the band does not churn on noise.
        mom_w = momentum_panel(adj_w, lookback=lookback, skip=skip)
        seed = str(strat.get("lottery_seed", 0))
        draw = {c: int(hashlib.sha256(f"{seed}:{c}".encode()).hexdigest()[:12], 16)
                / float(16 ** 12) for c in mom_w.columns}
        mom_w = mom_w.notna().mul(pd.Series(draw)).where(mom_w.notna())
    elif signal in ("vol_scaled_6_12", "mom_12_1_z"):
        # E1c §3 (and §5 S6 as amended 2026-09-21). The raw ingredients are
        # built once over the whole panel -- backward shifts and rolling
        # windows only, so no lookahead -- but the z-score and the ±3 clip are
        # applied at each decision date WITHIN THE ELIGIBLE UNIVERSE, which is
        # what §3's "standardised across the universe" means. Standardising
        # across the whole panel, as first implemented, measured names
        # against the entire market (E1c §9, code fix of 2026-09-21).
        parts = (vol_scaled_ratios(adj_w, windows=score_windows, skip=skip)
                 if signal == "vol_scaled_6_12"
                 else momentum_ratios(adj_w, lookback=lookback, skip=skip))
        mom_w = None

        def score_fn(d, elig, _parts=parts, _order=score_order):
            rows = [(pt.loc[d] if d in pt.index else pd.Series(dtype=float))
                    for pt in _parts]
            rows = [r[r.index.isin(elig)] for r in rows]
            return standardise(rows, order=_order, clip=3.0)
    else:
        raise ValueError(f"unknown strategy.signal={signal!r}")
    source_at: Dict[date, str] = {}
    if precomputed:
        stack_fn = score_fn
        if stack_fn is None:
            def stack_fn(d, elig, _w=mom_w):
                s = _w.loc[d].dropna() if d in _w.index else pd.Series(dtype=float)
                return s[s.index.isin(elig)]
        pre_scores, pre_fb = scores.get("scores") or {}, scores.get("fallback") or {}

        def score_fn(d, elig, _stack=stack_fn):
            if d not in pre_fb:
                raise ValueError(f"{d}: no precomputed decision (model or "
                                 f"fallback) for this month-end")
            if pre_fb[d]:
                source_at[d] = "fallback"
                return _stack(d, elig)
            s = pre_scores[d]
            stray = s.index.difference(pd.Index(elig))
            if len(stray):
                raise ValueError(f"{d}: {len(stray)} precomputed names are not in "
                                 f"the engine's universe (e.g. {stray[0]}); the "
                                 f"feature store was built from different data")
            source_at[d] = "model"
            return s
    # E2-A §3: names carrying a flag usable in the trailing window are
    # ineligible at month-end M. `usable_from` carries the point-in-time
    # rule, so nothing here reads a timestamp. Absent config leaves this
    # None and the universe is E1's, untouched.
    exclude_fn = None
    # GATE.md: one change per experiment. Checked before any table is read,
    # so a bad config fails on the config, not on a missing data file.
    _on = [k for k in ("red_flags", "promoter_selling", "insider_selling")
           if (config.get(k) or {}).get("enabled")]
    if len(_on) > 1:
        raise ValueError(f"{' and '.join(_on)} are all enabled; an experiment "
                         f"is ONE change (GATE.md)")
    _rf = (config.get("red_flags") or {})
    if _rf.get("enabled"):
        from pflab.data import red_flag_events as rfe
        _events = rfe.load()
        _months = int(_rf.get("window_months", 12))
        _drop = set(_rf.get("exclude_flags") or ())      # §7 S4-S12
        if _drop:
            _events = _events[~_events["flag"].isin(_drop)]

        def exclude_fn(_m, _e=_events, _w=_months):
            return rfe.flagged_at(_e, _m, months=_w)

    # E2-D1 §3: a name whose promoters' SHARES fell by more than `threshold`
    # of shares outstanding over the trailing two reported quarters is
    # ineligible at M, and a held one leaves through the "ineligible" exit in
    # `_decide`. The threshold has no default: it is the charter's number.
    # Rows usable after the period end are dropped at load (non-negotiable 2).
    _ps_record = None
    _ps = (config.get("promoter_selling") or {})
    if _ps.get("enabled"):
        if exclude_fn is not None:
            raise ValueError("red_flags and promoter_selling are both enabled; "
                             "an experiment is ONE change (GATE.md)")
        from pflab.data import positioning
        if "threshold" not in _ps:
            raise ValueError("promoter_selling.threshold must come from the "
                             "charter's config (E2-D1 §3)")
        exclude_fn, _ps_record = positioning.promoter_exclusion(
            period.end, actions, float(_ps["threshold"]),
            dated_only=bool(_ps.get("dated_only", False)))
    _pos_key = "promoter_selling"

    # E2-D2 §3: net insider selling (NSE PIT) over the trailing window above
    # `threshold` of market cap at M -- total reported shares outstanding x
    # the close at M -- makes a name ineligible. Every §4 choice is a config
    # key without a default. A name with no close at M has no measure.
    _is = (config.get("insider_selling") or {})
    if _is.get("enabled"):
        if exclude_fn is not None:
            raise ValueError("more than one exclusion rule is enabled; an "
                             "experiment is ONE change (GATE.md)")
        from pflab.data import positioning

        def _close_at(i, m, _w=close_w):
            if i not in _w.columns or m not in _w.index:
                return None
            v = _w.at[m, i]
            return None if pd.isna(v) else float(v)
        exclude_fn, _ps_record = positioning.insider_exclusion(
            period.end, _is, _close_at)
        _pos_key = "insider_selling"

    uni_pre = precompute_universe(panel, config, membership)
    traded_by_date = {d: set(g) for d, g in panel.groupby("date")["isin"]}

    # E3-R §4: three exposure gears replace E1 §6's on/off rule. Every other
    # trend_filter value leaves `gears` None and the E1 path untouched
    # (tests/test_engine_golden.py holds its bytes).
    gears = None
    if trend_filter == "gears":
        gears = _gear_setup(config, period, panel, sessions, indices, uni_pre,
                            mom_w, adj_w, signal, rebalance)

    book = LotBook(tax_policy)
    cash = float(strat.get("initial_cash", 0.0))
    pending: Optional[dict] = None
    suspended: Dict[str, int] = {}        # isin -> consecutive missing sessions
    pending_exits: Dict[str, Optional[int]] = {}  # isin -> qty, None = all
    last_close: Dict[str, float] = {}
    trades: List[dict] = []
    decisions: List[dict] = []
    warnings: List[dict] = []
    rows: List[dict] = []
    taxes: List[dict] = []
    skips: List[dict] = []
    state = _State()
    carried_weights: Dict[str, float] = {}   # E1c: targets between rebalances
    seen_fy = set()
    prev_session: Optional[date] = None
    month_ends = _month_ends(sessions)
    month_starts = _month_starts(sessions)

    for t in sessions:
        traded_today = traded_by_date.get(t, set())
        in_window = period.start <= t <= period.end
        flow = 0.0

        # --- 0. ex-date events and dividends (§9), at the START of t ------
        # E1 §15, 2026-09-27 (audit defect 1): entitlements come from the
        # holdings carried into t, so a first buy on the ex-date gets neither
        # the split nor the dividend, and a seller on the ex-date keeps both.
        factors_today: Dict[str, float] = {}
        credited_today, dividends_today = _apply_ex_date_events(
            t, book, act_map, div_map, tax_policy, warnings, trades,
            last_close=last_close, share_factors=factors_today)
        cash += credited_today
        if factors_today:
            pending = _rescale_pending(pending, factors_today)
            for isin, q in list(pending_exits.items()):
                if q is not None and isin in factors_today:
                    pending_exits[isin] = int(math.floor(q / factors_today[isin] + 1e-6))

        # --- 0b. exits waiting for a quote, and written-down names that
        # trade again, execute at open(t) (§9; E1 §15 2026-09-17/27)
        if in_window and (pending_exits or book.written_down):
            cash = _retry_exits(t, book, cash, open_w, cost_model, trades,
                                warnings, pending_exits)
        n_warn = len(warnings)

        # --- 1. month start: FY settlement, SIP, execute the stored decision
        if t in month_starts and in_window:
            fy = fy_of(t)
            if fy not in seen_fy:
                seen_fy.add(fy)
                if len(seen_fy) > 1:
                    prior = fy - 1
                    if prior not in book.settled:
                        ft = book.settle_fy(prior)
                        cash -= ft.total
                        taxes.append({"fy": prior, "stcg": ft.stcg_realised,
                                      "ltcg": ft.ltcg_realised,
                                      "dividends": ft.dividends,
                                      "interest": ft.interest,
                                      "tax": ft.total, "paid_on": t})
            cash += sip
            flow += sip
            if pending is not None:
                if pending.get("gear"):
                    cash = _execute_gears(pending, t, book, cash, open_w, close_w,
                                          turn_w, cost_model, trades, warnings,
                                          max_adv, max_buys, n_hold, hooks, state,
                                          last_close, skips, gears,
                                          no_buy.get(t, frozenset()))
                else:
                    cash = _execute(pending, t, book, cash, open_w, close_w, turn_w,
                                    cost_model, trades, warnings, max_adv, max_buys,
                                    n_hold, hooks, state, last_close, skips,
                                    no_buy.get(t, frozenset()))
                pending = None

        # --- 1b. intra-month exits (E2-A red flags; E1-P §4 N1/N2) ------
        # After the month-start execution on purpose. `state` still carries
        # session t-1's marks here, which is exactly the hook's contract
        # ("decided from data dated strictly before t"), and running after the
        # buy list means a name bought at today's open -- whose cost basis IS
        # today's open -- cannot be sold by its own purchase.
        if in_window:
            cash = _intra_month_exits(t, book, cash, open_w, cost_model,
                                      trades, warnings, hooks, state)

        # An exit that found no quote today is retried every session (§9).
        _register_deferred(warnings[n_warn:], pending_exits)

        # --- 2. suspension (§9; E1 §15 2026-09-17, corrected 2026-09-27) --
        # A held name without a row stays marked at its last close. On the
        # `confirm`-th missing session (250; S9 20) it is written down to
        # zero: no cash moves, because there is no quote to sell at, and no
        # capital loss is booked, because nothing was sold (audit defect 2).
        for isin in list(book.positions()):
            if isin in traded_today:
                suspended.pop(isin, None)
                continue
            n = suspended.get(isin, 0) + 1
            suspended[isin] = n
            if n >= confirm and in_window:
                _write_down(t, book, isin, n, last_close, warnings)
                pending_exits.pop(isin, None)
                suspended.pop(isin, None)

        # --- 3. cash accrual, taxable at slab in its FY -----------------
        if prev_session is not None and cash > 0:
            grown = cash * (1.0 + cash_rate * (t - prev_session).days / 365.0)
            book.interest(t, grown - cash)
            cash = grown
        hooks.side_sleeve.accrue(cash_rate, (t - prev_session).days if prev_session else 0)

        # --- 4. mark to market -----------------------------------------
        for isin in traded_today:
            v = close_w.at[t, isin] if isin in close_w.columns else None
            if v is not None and not pd.isna(v):
                last_close[isin] = float(v)
        positions = book.positions()
        hv = {i: q * last_close.get(i, 0.0) for i, q in positions.items()}
        equity_value = sum(hv.values())
        basis, lots_by_isin = {}, {}
        for i in positions:
            lots = book.lots(i)
            lots_by_isin[i] = lots
            tq = sum(l.qty for l in lots)
            if tq > 0:
                basis[i] = sum(l.qty * l.cost_per_share for l in lots) / tq
        state.date, state.cash, state.positions, state.holdings_value = t, cash, positions, hv
        state.cost_basis = basis
        state.lots = lots_by_isin
        rows.append({"date": t, "equity_value": equity_value, "cash": cash,
                     "flow": flow, "risk_off": bool(risk_off.get(t, False)),
                     "dividends": dividends_today})

        # --- 5. month-end decision -------------------------------------
        if t in month_ends and in_window:
            if rebalance == "semiannual":
                pending = _decide_rebalance(
                    t, mom_w, uni_pre, close_w, positions, risk_off,
                    trend_filter, config, decisions, month_ends,
                    selection_n=selection_n, weighting=weighting,
                    weight_cap=weight_cap, rebalance_months=rebalance_months,
                    score_lag_months=score_lag_months, on_negative=on_negative,
                    carried=carried_weights, score_fn=score_fn,
                    exclude_fn=exclude_fn)
                if pending.get("target_weights"):
                    carried_weights = dict(pending["target_weights"])
            elif rebalance == "monthly_band":
                pending = _decide(t, mom_w, uni_pre, close_w, n_hold, band,
                                  positions, risk_off, trend_filter, config,
                                  hooks, state, decisions, book,
                                  weighting=weighting, weight_cap=weight_cap,
                                  on_negative=on_negative, score_fn=score_fn,
                                  exclude_fn=exclude_fn)
                if precomputed:
                    # E5-A §11: which decisions the fallback made
                    pending["score_source"] = source_at[t]
                if gears is not None:
                    _annotate_gear(pending, t, gears, book, state, close_w,
                                   mom_w, tax_policy)
            else:
                raise ValueError(f"unknown strategy.rebalance={rebalance!r}")
        prev_session = t

    if _ps_record is not None:
        # E2-D1 / E2-D2 §8: which names the rule excluded at each decision,
        # and why.
        for d in decisions:
            d[_pos_key] = {
                i: {k: (str(x) if isinstance(x, date) else x) for k, x in v.items()}
                for i, v in sorted((_ps_record.get(d["month_end"]) or {}).items())}

    equity = pd.DataFrame(rows)
    equity, tax_rows = _finalise(equity, book, last_close, cost_model,
                                 tax_policy, sessions, taxes)
    return RunResult(equity=equity,
                     trades=pd.DataFrame(trades) if trades else _empty_trades(),
                     decisions=decisions,
                     taxes=pd.DataFrame(tax_rows) if tax_rows else pd.DataFrame(
                         columns=["fy", "stcg", "ltcg", "dividends", "interest",
                                  "tax", "paid_on"]),
                     warnings=warnings, config=config,
                     hooks_active=hooks.active(),
                     adv_skips=(pd.DataFrame(skips) if skips else pd.DataFrame(
                         columns=["date", "isin", "buy_value", "adv", "ratio",
                                  "planned"])),
                     realised=list(book.realised), universe_pre=uni_pre,
                     regime=(gears["record"] if gears is not None else None))


# -- decision ----------------------------------------------------------
def _decide(m, mom_w, uni_pre, close_w, n_hold, band, positions,
            risk_off, trend_filter, config, hooks, state, decisions, book,
            weighting="equal", weight_cap=0.05, on_negative="zero",
            score_fn=None, exclude_fn=None) -> dict:
    elig = eligible_at(
        uni_pre, m,
        min_sessions=int(_cfg(config, "universe.min_sessions", 250)),
        top_n=int(_cfg(config, "universe.top_n_by_turnover", 500)),
        min_price=float(_cfg(config, "universe.min_price", 10.0)),
        exclude=(exclude_fn(m) if exclude_fn else None))
    if score_fn is not None:
        scores = score_fn(m, elig)          # E1c: standardised within elig
    else:
        scores = mom_w.loc[m].dropna() if m in mom_w.index else pd.Series(dtype=float)
        scores = scores[scores.index.isin(elig)]
    ranks = rank_desc(scores)

    held = list(positions)
    exits, deferred = [], []
    for isin in held:
        r = float(ranks.get(isin, np.inf))
        reason = None
        if isin not in elig:
            reason = "ineligible"
        elif r > band:
            reason = "band"
        if reason:
            ages = [(m - lot.buy_date).days for lot in book.lots(isin)]
            if reason == "band" and hooks.defer_exit(m, isin, r, ages, state):
                deferred.append(isin)
                continue
            exits.append({"isin": isin, "reason": reason, "rank": None if np.isinf(r) else r})

    entries = [i for i in ranks[ranks <= n_hold].sort_values().index if i not in held]
    ro = bool(risk_off.get(m, False))
    # E1c §5 S4 puts E1's monthly band back on the fund's score. That row is
    # meant to isolate the CADENCE, so the fund's weighting has to survive it;
    # otherwise S4 would silently change two things at once and stop being a
    # one-change row. `weighting` is "equal" for E1 and E1b, which leaves
    # `target_weights` absent and the E1 path exactly as it was.
    tw = None
    if weighting == "score_tilted":
        from pflab.portfolio.construct import score_tilted_weights
        keep = [i for i in held
                if i not in {e["isin"] for e in exits} or i in deferred]
        target = list(dict.fromkeys(keep + entries))
        target = [i for i in target if i in scores.index]
        if target:
            tw = _weights_or_ask({i: float(scores[i]) for i in target},
                                 weight_cap, on_negative, m, None)
    elif weighting != "equal":
        raise ValueError(f"unknown strategy.weighting={weighting!r}")

    d = {"month_end": m, "risk_off": ro, "n_eligible": int(len(elig)),
         "exits": exits, "deferred": deferred, "entries": entries,
         "held": held, "ranks": {i: float(ranks[i]) for i in ranks.index[:200]},
         "reference_close": {i: float(close_w.at[m, i])
                             for i in sorted(set(held) | set(entries))
                             if i in close_w.columns and not pd.isna(close_w.at[m, i])},
         "trend_filter": trend_filter}
    if tw:
        d["target_weights"] = tw
    # DIAGNOSTIC ONLY (E1 gap attribution, 2026-09-27): E1 §5 tops up every
    # held name, including those ranked 26-50 in the band. With a ceiling,
    # held names ranked above it receive no new money. Absent for every
    # charter config, so `no_buy` stays absent and E1's path is unchanged.
    ceiling = _cfg(config, "strategy.topup_max_rank")
    if ceiling is not None:
        nb = [i for i in held if float(ranks.get(i, np.inf)) > float(ceiling)]
        if nb:
            d["no_buy"] = nb
    decisions.append(d)
    return d


def _weights_or_ask(scores, cap, on_negative, m, score_date):
    """E1c §3's weights, with the date attached if §3 cannot answer.

    Since the 2026-09-21 amendment that is only a selection with no positive
    score in it; a merely non-positive score gets weight zero.

    `score_tilted_weights` knows the names and the scores but not when it was
    asked, and "which month did the charter run out of rules?" is the first
    thing anyone will want. The halt is not a failure to be logged and
    stepped over -- it is the charter asking a question -- so the date is
    added and the exception is left to propagate all the way out of the
    sweep.
    """
    from pflab.portfolio.construct import UndefinedWeight, score_tilted_weights
    try:
        return score_tilted_weights(scores, cap=cap, on_negative=on_negative)
    except UndefinedWeight as e:
        when = f"month-end {m}"
        if score_date is not None and score_date != m:
            when += f" (scored at {score_date})"
        raise UndefinedWeight(f"{when}: {e}") from None


def _score_date(m, month_ends, lag_months: int):
    """The month-end whose scores a rebalance at `m` uses (E1c §3's lag).

    Counted in MONTH-ENDS, not in calendar days: the score date is the
    month-end `lag_months` positions before `m`. Subtracting a calendar month
    from a month-end lands mid-month, before that month's own month-end
    session, so snapping to "the latest month-end at or before it" silently
    skips a whole month -- a one-month lag became two. Counting positions is
    what "one-month lag from score date" means and cannot drift.
    """
    if lag_months <= 0:
        return m
    ordered = sorted(month_ends)          # _month_ends returns a set
    try:
        i = ordered.index(m)
    except ValueError:
        return None
    j = i - lag_months
    return ordered[j] if j >= 0 else None


def _decide_rebalance(m, mom_w, uni_pre, close_w, positions, risk_off,
                      trend_filter, config, decisions, month_ends,
                      selection_n, weighting, weight_cap, rebalance_months,
                      score_lag_months, on_negative, carried,
                      score_fn=None, exclude_fn=None) -> dict:
    """E1c §3's decision: sells at rebalance only, no band, no intra-month.

    On a rebalance month-end the universe is re-scored and the top
    `selection_n` become the book; names leaving it are sold at the next
    open. On every other month-end there are no exits and no entries, and
    the SIP buys toward the weights the last rebalance set (§3: "Between
    rebalances, only shortfall buys").

    The scores are taken from the month-end `score_lag_months` earlier, which
    is §3's "one-month lag from score date". NOTE: §3 also says the rebalance
    is "effective the last trading day of June and December", which this
    engine cannot place -- E1 §7 fills at the NEXT session's open. The
    difference is one session, twice a year, and it is flagged in
    docs/notes/E1c-readiness.md rather than resolved here.
    """
    from pflab.portfolio.construct import score_tilted_weights

    held = list(positions)
    is_rebalance = m.month in rebalance_months
    ro = bool(risk_off.get(m, False))

    if not is_rebalance:
        # §3: only shortfall buys. Targets carry over, restricted to what is
        # still held or still targeted.
        d = {"month_end": m, "risk_off": ro, "n_eligible": None,
             "exits": [], "deferred": [], "entries": [],
             "held": held, "ranks": {},
             "target_weights": dict(carried or {}),
             "rebalance": False,
             "reference_close": {i: float(close_w.at[m, i])
                                 for i in sorted(set(held) | set(carried or {}))
                                 if i in close_w.columns
                                 and not pd.isna(close_w.at[m, i])},
             "trend_filter": trend_filter}
        decisions.append(d)
        return d

    elig = eligible_at(
        uni_pre, m,
        min_sessions=int(_cfg(config, "universe.min_sessions", 250)),
        top_n=int(_cfg(config, "universe.top_n_by_turnover", 500)),
        min_price=float(_cfg(config, "universe.min_price", 10.0)),
        exclude=(exclude_fn(m) if exclude_fn else None))
    sd = _score_date(m, month_ends, score_lag_months)
    if score_fn is not None:
        # standardised within the universe being selected from (the eligible
        # set at the decision date; with §3's single lag, sd IS m)
        scores = (score_fn(sd, elig) if sd is not None
                  else pd.Series(dtype=float))
    else:
        scores = (mom_w.loc[sd].dropna() if (sd is not None and sd in mom_w.index)
                  else pd.Series(dtype=float))
        scores = scores[scores.index.isin(elig)]
    ranks = rank_desc(scores)
    selected = list(ranks[ranks <= selection_n].sort_values().index)

    if weighting == "equal":
        tw = {i: 1.0 / len(selected) for i in selected} if selected else {}
    elif weighting == "score_tilted":
        tw = (_weights_or_ask({i: float(scores[i]) for i in selected},
                              weight_cap, on_negative, m, sd)
              if selected else {})
    else:
        raise ValueError(f"unknown strategy.weighting={weighting!r}")

    exits = [{"isin": i, "reason": "rebalance",
              "rank": (None if i not in ranks.index else float(ranks[i]))}
             for i in held if i not in selected]
    entries = [i for i in selected if i not in held]

    d = {"month_end": m, "risk_off": ro, "n_eligible": int(len(elig)),
         "exits": exits, "deferred": [], "entries": entries,
         "held": held, "ranks": {i: float(ranks[i]) for i in ranks.index[:200]},
         "target_weights": tw, "rebalance": True,
         "score_date": sd,
         "reference_close": {i: float(close_w.at[m, i])
                             for i in sorted(set(held) | set(selected))
                             if i in close_w.columns
                             and not pd.isna(close_w.at[m, i])},
         "trend_filter": trend_filter}
    decisions.append(d)
    return d


# -- execution ---------------------------------------------------------
def _execute(dec, t, book, cash, open_w, close_w, turn_w, cost_model, trades,
             warnings, max_adv, max_buys, n_hold, hooks, state, last_close,
             skips, no_buy_today=frozenset()) -> float:
    ro = dec["risk_off"]
    tf = dec.get("trend_filter", "sma10")

    sell_names = [e["isin"] for e in dec["exits"]]
    if tf == "sell_to_cash" and ro:
        sell_names = list(dict.fromkeys(sell_names + list(book.positions())))

    for isin in sell_names:
        qty = book.holdings(isin)
        if qty <= 0:
            continue
        px = _price(open_w, t, isin)
        if px is None:
            # §9 suspension: the exit executes on the first session it trades
            # again, so leave it held rather than inventing a price.
            warnings.append({"kind": "exit_deferred_no_price", "isin": isin, "date": t})
            continue
        proceeds = qty * px
        c = cost_model.sell_cost(proceeds, 1)
        book.sell(isin, t, qty, px, c - cost_model.sell_stt(qty * px))
        cash += proceeds - c
        trades.append(_trade(t, isin, "SELL", qty, dec["reference_close"].get(isin), px, c))

    if ro and tf in ("sma10", "sell_to_cash"):
        return cash          # §6: no equity buys while RISK_OFF

    held = book.positions()
    hv = {i: q * last_close.get(i, 0.0) for i, q in held.items()}
    # E1c §3 targets each name's own weight; E1 §5 targets an equal share.
    # `target_weights` is absent from every E1/E1b decision, so this is the
    # only place the two paths differ and E1 never enters the new one.
    tw = dec.get("target_weights")
    if tw:
        candidates = list(tw)
    else:
        candidates = [i for i in list(held) + dec["entries"]]
    # E3-R §11 (c): the gear's ETF is held by the gear, not by the rank, so
    # E1's shortfall buys never top it up. Absent from every E1 decision.
    if dec.get("no_buy"):
        candidates = [i for i in candidates if i not in dec["no_buy"]]
    # D2 (E1 §15, 2026-09-27): a name trading in BE/BZ today is priced and
    # may be sold there, but is never bought -- the universe is EQ (§2).
    if no_buy_today:
        candidates = [i for i in candidates if i not in no_buy_today]
    prices = {i: p for i in candidates if (p := _price(open_w, t, i)) is not None}
    if not prices or cash <= 0:
        return cash

    # §7 as amended 2026-09-17: a buy above 1% of the name's 20-session ADV is
    # SKIPPED and the next entry candidate by rank is tried. Excluding a name
    # changes the shortfalls, so the list is rebuilt rather than patched.
    available = [c for c in candidates if c in prices]
    excluded: set = set()
    orders: List[tuple] = []
    for _ in range(len(available) + 1):
        usable = [c for c in available if c not in excluded]
        if tw:
            proposed = buy_list_weighted(
                {k: v for k, v in tw.items() if k in usable},
                hv, cash, prices, max_names=max_buys)
        else:
            proposed = buy_list(usable, hv, cash, prices,
                                n_hold=n_hold, max_names=max_buys)
        if not proposed:
            orders = []
            break
        orders, newly_excluded = [], False
        for isin, qty in proposed:
            px = prices[isin]
            adv = _adv(turn_w, t, isin)
            if adv is None or not (adv > 0):
                raise ADVDataError(
                    f"{t} {isin}: 20-session ADV is {adv!r} for a name the engine "
                    f"is about to buy -- charter §7 halt (data error)")
            ratio = qty * px / adv
            if ratio > max_adv:
                skips.append({"date": t, "isin": isin, "buy_value": qty * px,
                              "adv": adv, "ratio": ratio,
                              "planned": len(proposed)})
                excluded.add(isin)
                newly_excluded = True
            else:
                orders.append((isin, qty))
        if not newly_excluded:
            break

    for isin, qty in orders:
        px = prices[isin]
        if not hooks.pre_buy_constraint(t, isin, qty, px, state):
            warnings.append({"kind": "constraint_skip", "isin": isin, "date": t})
            continue
        qty = _fit_to_cash(qty, px, cash, cost_model)
        if qty < 1:
            continue
        notional = qty * px
        c = cost_model.buy_cost(notional)
        book.buy(isin, t, qty, px, c - cost_model.buy_stt(qty * px))
        cash -= notional + c
        trades.append(_trade(t, isin, "BUY", qty, dec["reference_close"].get(isin), px, c))
    return cash


# -- E3-R: risk gears ----------------------------------------------------
GEAR_KEYS = ("instrument_isin", "cautious_target", "selldown_fraction", "trigger",
             "high_gear", "high_mode", "v_source", "basket_n", "v_window",
             "v_percentile", "v_lookback_months", "b_window", "b_level",
             "min_cautious_run", "disposal_tranches")


def _gear_setup(config, period, panel, sessions, indices, uni_pre, mom_w, adj_w,
                signal, rebalance) -> dict:
    """E3-R §3: T, V and B at every month-end in the truncated panel, and the
    gear at every month-end in the window.

    Computed over the whole truncated panel, not just the window, because V's
    percentile needs 36 earlier values; every series is backward-looking, so
    no value at M reads a row after M. The gear machine itself starts at the
    window's first month-end, in normal gear.
    """
    from pflab.signals import regime as rg
    g = config.get("gears") or {}
    missing = [k for k in GEAR_KEYS if k not in g]
    if missing:
        raise ValueError(f"gears.{missing} must come from the charter's config "
                         f"(E3-R §3-§4, §11)")
    if signal != "mom_12_1" or rebalance != "monthly_band":
        raise ValueError("E3-R's gears run on E1's stack: signal mom_12_1, "
                         "monthly band")
    min_s = int(_cfg(config, "universe.min_sessions", 250))
    top_n = int(_cfg(config, "universe.top_n_by_turnover", 500))
    min_px = float(_cfg(config, "universe.min_price", 10.0))
    mes = sorted(_month_ends(sessions))   # a set: the gear path needs order
    t_flags = _risk_off_series(indices, sessions, "sma10")

    elig_by_m, vraw = {}, {}
    vix = None
    if g["v_source"] == "india_vix":                     # §6 S8
        from pflab.data import data_dir
        vix = pd.read_parquet(data_dir() / "indices" / "INDIA_VIX.parquet")
        vix["date"] = pd.to_datetime(vix["date"]).dt.date
        vix = vix[vix["date"] <= period.end].set_index("date")["close"].sort_index()
    elif g["v_source"] != "realised":
        raise ValueError(f"unknown gears.v_source {g['v_source']!r}")
    for m in mes:
        elig = eligible_at(uni_pre, m, min_sessions=min_s, top_n=top_n,
                           min_price=min_px)
        elig_by_m[m] = elig
        if vix is not None:
            prior = vix.loc[:m]
            vraw[m] = float(prior.iloc[-1]) if len(prior) else None
            continue
        sc = mom_w.loc[m].dropna() if m in mom_w.index else pd.Series(dtype=float)
        sc = sc[sc.index.isin(elig)]
        top = list(rank_desc(sc).sort_values().index[:int(g["basket_n"])])
        vraw[m] = (rg.basket_vol(adj_w, m, top, int(g["v_window"]))
                   if len(top) >= int(g["basket_n"]) else None)
    v = rg.above_trailing_percentile(vraw, float(g["v_percentile"]),
                                     int(g["v_lookback_months"]))
    sma = rg.own_sma(panel, int(g["b_window"])).reindex(adj_w.index).ffill()
    adj_ff = adj_w.ffill()
    braw = {m: rg.breadth(adj_ff.loc[m], sma.loc[m], elig_by_m[m]) for m in mes}
    b = rg.below(braw, float(g["b_level"]))

    win = [m for m in mes if period.start <= m <= period.end]
    caut = [rg.cautious_at(bool(t_flags.get(m, False)), v.get(m), b.get(m),
                           g["trigger"]) for m in win]
    path = rg.gear_path(caut, bool(g["high_gear"]), int(g["min_cautious_run"]))
    gear_by_m = dict(zip(win, path))
    record = {
        "v_undefined_months": [str(m) for m in win if v.get(m) is None],
        "b_undefined_months": [str(m) for m in win if b.get(m) is None],
        "months": {str(m): {"gear": gear_by_m[m], "T": bool(t_flags.get(m, False)),
                            "V": v.get(m), "B": b.get(m), "V_raw": vraw.get(m),
                            "B_raw": braw.get(m)} for m in win},
    }
    return {"cfg": g, "gear": gear_by_m, "record": record, "tranches": {}}


def _annotate_gear(d, m, G, book, state, close_w, mom_w, tax_policy) -> None:
    """Attach the gear and its planned sales to E1's own decision at M."""
    from pflab.portfolio import selldown
    from pflab.signals.regime import CAUTIOUS, NORMAL
    from pflab.tax.india_lots import is_long_term
    g, etf = G["cfg"], G["cfg"]["instrument_isin"]
    gear = G["gear"][m]
    d["gear"] = gear
    d["signals"] = G["record"]["months"][str(m)]
    # §11 (c): exempt from §2's eligibility and from the band
    d["exits"] = [e for e in d["exits"] if e["isin"] != etf]
    d["no_buy"] = [etf]
    hv = dict(state.holdings_value)
    equity = float(sum(hv.values()))
    total = equity + float(state.cash)
    d["equity_share"] = equity / total if total > 0 else None
    px_m = {i: float(close_w.at[m, i]) for i in hv
            if i in close_w.columns and not pd.isna(close_w.at[m, i])}
    d.setdefault("reference_close", {}).update(px_m)
    if etf in close_w.columns and not pd.isna(close_w.at[m, etf]):
        d["reference_close"][etf] = float(close_w.at[m, etf])
    if gear == CAUTIOUS:
        exiting = {e["isin"] for e in d["exits"]}
        after = equity - sum(hv.get(i, 0.0) for i in exiting)
        target = float(g["cautious_target"]) * total
        excess = max(0.0, after - target)
        amount = float(g["selldown_fraction"]) * excess
        scores = (mom_w.loc[m].dropna().to_dict() if m in mom_w.index else {})
        lots = {i: book.lots(i) for i in hv if i not in exiting}
        ranked = selldown.rank(lots, px_m, scores, m, tax_policy)
        plan = selldown.plan(ranked, amount)
        d["selldown"] = {
            "equity": equity, "portfolio": total, "target_equity": target,
            "excess": excess, "amount": amount,
            "plan": [[i, q] for i, q in plan],
            "ranked": [[c.isin, selldown.CATEGORY_NAMES[c.category],
                        c.tax_per_rupee] for c in ranked]}
    elif gear == NORMAL:
        # §11 (d): the instrument's lots that have turned long-term are sold
        # in thirds over this and the next two normal month-ends
        tr = G["tranches"]
        lots = book.lots(etf) if book.holdings(etf) > 0 else []
        for lot in lots:
            if (is_long_term(lot.buy_date, m, tax_policy.long_term_months)
                    and lot.buy_date not in tr):
                tr[lot.buy_date] = int(g["disposal_tranches"])
        due = 0
        for lot in lots:
            k = tr.get(lot.buy_date)
            if k:
                due += lot.qty if k == 1 else lot.qty // k
        if due > 0:
            d["tranche_sell"] = {"isin": etf, "qty": int(due),
                                 "lots": {str(k): v for k, v in tr.items()}}


def _execute_gears(dec, t, book, cash, open_w, close_w, turn_w, cost_model, trades,
                   warnings, max_adv, max_buys, n_hold, hooks, state, last_close,
                   skips, G, no_buy_today=frozenset()) -> float:
    """E3-R §4 at the open after M: the gear's own sales, then E1's exits and
    (where the gear allows) E1's buys through `_execute` itself, then the high
    gear's purchase of the instrument."""
    from pflab.signals.regime import CAUTIOUS, HIGH, NORMAL
    g, etf, gear = G["cfg"], G["cfg"]["instrument_isin"], dec["gear"]
    sells = []
    if gear == CAUTIOUS:
        sells = [tuple(x) for x in dec["selldown"]["plan"]]
    elif gear == NORMAL and dec.get("tranche_sell"):
        sells = [(etf, int(dec["tranche_sell"]["qty"]))]
    sold_etf = False
    for isin, qty in sells:
        qty = min(int(qty), book.holdings(isin))
        if qty <= 0:
            continue
        px = _price(open_w, t, isin)
        if px is None:
            warnings.append({"kind": "gear_sell_no_price", "isin": isin, "date": t,
                             "qty": int(qty)})
            continue
        proceeds = qty * px
        c = cost_model.sell_cost(proceeds, 1)
        book.sell(isin, t, qty, px, c - cost_model.sell_stt(qty * px))
        cash += proceeds - c
        trades.append(_trade(t, isin, "SELL_GEAR", qty,
                             dec["reference_close"].get(isin), px, c))
        sold_etf = sold_etf or isin == etf
    if gear == NORMAL and sold_etf:
        live = {l.buy_date for l in book.lots(etf)} if book.holdings(etf) > 0 else set()
        for k in list(G["tranches"]):
            G["tranches"][k] -= 1
            if G["tranches"][k] <= 0 or k not in live:
                del G["tranches"][k]

    stack_high = gear == HIGH and g["high_mode"] == "stack"          # §6 S7
    if g["high_mode"] not in ("instrument", "stack"):
        raise ValueError(f"unknown gears.high_mode {g['high_mode']!r}")
    block = gear == CAUTIOUS or (gear == HIGH and not stack_high)
    dec2 = {**dec, "risk_off": block, "trend_filter": "sma10"}
    cash = _execute(dec2, t, book, cash, open_w, close_w, turn_w, cost_model,
                    trades, warnings, max_adv, n_hold if stack_high else max_buys,
                    n_hold, hooks, state, last_close, skips, no_buy_today)

    if gear == HIGH and g["high_mode"] == "instrument" and cash > 0:
        px = _price(open_w, t, etf)
        if px is None:
            warnings.append({"kind": "gear_buy_no_price", "isin": etf, "date": t})
            return cash
        qty = _fit_to_cash(int(math.floor(cash / px)), px, cash, cost_model)
        if qty < 1:
            return cash
        adv = _adv(turn_w, t, etf)
        if adv is None or not (adv > 0):
            raise ADVDataError(f"{t} {etf}: 20-session ADV is {adv!r} for the "
                               f"high gear's instrument -- §7 halt (data error)")
        ratio = qty * px / adv
        if ratio > max_adv:
            # §11 (c): subject to the ADV guard like any buy. There is no next
            # candidate for the gear's instrument, so the cash waits.
            skips.append({"date": t, "isin": etf, "buy_value": qty * px,
                          "adv": adv, "ratio": ratio, "planned": 1})
            warnings.append({"kind": "high_gear_adv_skip", "date": t,
                             "buy_value": qty * px, "adv": adv})
            return cash
        notional = qty * px
        c = cost_model.buy_cost(notional)
        book.buy(etf, t, qty, px, c - cost_model.buy_stt(qty * px))
        cash -= notional + c
        trades.append(_trade(t, etf, "BUY", qty, dec["reference_close"].get(etf),
                             px, c))
    return cash


def _intra_month_exits(t, book, cash, open_w, cost_model, trades, warnings,
                       hooks, state) -> float:
    """Sell, at the open of `t`, whatever the intra-month hook names.

    Inert for E1: `hooks._no_intra_month_exit` returns [] and this function
    then touches nothing, which is what keeps the E1 path byte-identical
    (tests/test_engine_rules.py).
    """
    held = list(book.positions())
    if not held:
        return cash
    for isin in hooks.intra_month_exit(t, held, state) or ():
        qty = book.holdings(isin)
        if qty <= 0:
            continue
        px = _price(open_w, t, isin)
        if px is None:
            # §9 suspension: it exits on the first session it trades again.
            warnings.append({"kind": "intra_month_exit_no_price",
                             "isin": isin, "date": t})
            continue
        proceeds = qty * px
        c = cost_model.sell_cost(proceeds, 1)
        book.sell(isin, t, qty, px, c - cost_model.sell_stt(qty * px))
        cash += proceeds - c
        # No reference close: this is not a month-end decision, so there is
        # no reference price to measure slippage against.
        trades.append(_trade(t, isin, "SELL_INTRA", qty, None, px, c))
        warnings.append({"kind": "intra_month_exit", "isin": isin, "date": t,
                         "qty": int(qty), "price": px})
    return cash


def _fit_to_cash(qty: int, px: float, cash: float, cost_model) -> int:
    """E1 §15, 2026-09-21: integer shares are sized net of buy costs.

    §5's literal formula, floor(min(shortfall, cash) / price), ignores costs,
    so a buy sized to use all the available cash could no longer pay for
    itself once its costs were added. The engine used to skip such a buy
    outright, which made whether a month was invested come down to rupee
    rounding -- B5 sat out February 2007 that way. Instead the order is
    reduced by whole shares until shares x price + costs fits the cash.

    An error fix, not a rule change: every row and every benchmark takes this
    path. Costs rise with notional, so the first quantity that fits is the
    largest; in practice it is one or two shares below the original.
    """
    q = int(qty)
    while q >= 1 and q * px + cost_model.buy_cost(q * px) > cash:
        q -= 1
    return q


def _price(w, t, isin):
    if isin not in w.columns or t not in w.index:
        return None
    v = w.at[t, isin]
    return None if pd.isna(v) or v <= 0 else float(v)


def _adv(turn_w, t, isin, window: int = 20):
    if isin not in turn_w.columns:
        return None
    s = turn_w.loc[turn_w.index < t, isin].dropna().tail(window)
    return float(s.mean()) if len(s) else None


def _trade(t, isin, side, qty, ref, fill, costs):
    return {"date": t, "isin": isin, "side": side, "qty": int(qty),
            "reference_price": ref, "fill_price": fill, "costs": costs,
            "slippage": (None if ref in (None, 0) else (fill - ref) / ref)}


def _empty_trades():
    return pd.DataFrame(columns=["date", "isin", "side", "qty", "reference_price",
                                 "fill_price", "costs", "slippage"])


# -- §9 ex-date events -------------------------------------------------
def _apply_ex_date_events(t, book, act_map, div_map, tax_policy, warnings,
                          trades, last_close=None, share_factors=None) -> tuple:
    """The four rules, in the charter's precedence. Returns (cash credited,
    dividends). Called at the START of t, on the holdings carried into t.

    purpose factor          -> share count: its bonus part (`bonus_factor`)
                               as a new nil-cost lot dated t, the rest as a
                               split that keeps dates and spreads basis
    prevclose factor < 1    -> cash credit, unless it snaps to a standard
                               ratio, which means it is a split or bonus the
                               PURPOSE text failed to name (treated as a split)
    prevclose factor > 1    -> share count (a consolidation)
    dividend                -> cash
    never two on one date   -> the factor wins; the dividend feed has already
                               had its colliding rows removed upstream

    A fractional entitlement is paid in cash at the post-action price -- the
    prior close times the factor -- and realised against its own basis (E1
    §15, 2026-09-27). `share_factors`, if given, receives {isin: factor} for
    every share-count action applied, so pending quantities can follow.
    """
    credited = 0.0
    for ev in act_map.get(t, ()):
        isin = ev["isin"]
        if book.holdings(isin) == 0:
            continue
        f = float(ev["factor"])
        src = ev.get("source", "purpose")
        if src == "purpose" or f > 1.0 or _snaps_to_standard_ratio(f):
            bf = ev.get("bonus_factor") if src == "purpose" else None
            bf = float(bf) if bf is not None and not pd.isna(bf) and 0 < float(bf) < 1 else 1.0
            sf = f / bf
            prior = (last_close or {}).get(isin)
            if prior is None:
                pc = ev.get("prior_close")
                prior = float(pc) if pc is not None and not pd.isna(pc) else None
            added = 0
            if abs(sf - 1.0) > 1e-12:
                added += book.adjust_shares(isin, sf)
                credited += _settle_fractions(t, book, isin, prior, sf, f, trades, warnings)
            if bf < 1.0:
                added += book.bonus(isin, bf, t)
                credited += _settle_fractions(t, book, isin, prior, f, f, trades, warnings)
            if share_factors is not None:
                share_factors[isin] = share_factors.get(isin, 1.0) * f
            warnings.append({"kind": "share_count_action", "isin": isin, "date": t,
                             "factor": f, "bonus_factor": bf, "source": src,
                             "shares_added": added})
        else:
            per_share = ev.get("cash_per_share")
            if per_share is None:
                prior, adj = ev.get("prior_close"), ev.get("adj_prev_close")
                per_share = (float(prior) - float(adj)) if prior and adj else None
            if not per_share or per_share <= 0:
                warnings.append({"kind": "cash_credit_unpriced", "isin": isin, "date": t})
                continue
            qty = book.holdings(isin)
            amount = qty * per_share
            book.reduce_basis(isin, f)
            credited += amount
            warnings.append({"kind": "cash_credit", "isin": isin, "date": t,
                             "factor": f, "amount": amount})
            trades.append(_trade(t, isin, "CASH_CREDIT", qty, None, per_share, 0.0))

    dividends = 0.0
    for isin, dps in div_map.get(t, ()):
        qty = book.holdings(isin)
        if qty:
            gross = qty * dps
            book.dividend(t, gross)
            credited += gross
            dividends += gross
    # Dividends are returned separately from §9 cash credits because the
    # equity-sleeve return has to add them back: they are a return ON the
    # holding that leaves `equity_value` for cash on the ex-date. Nothing here
    # changes a decision, a cash balance or a tax.
    return credited, dividends


def _settle_fractions(t, book, isin, prior, price_factor, factor, trades,
                      warnings) -> float:
    """Cash in lieu of every open fraction of `isin`, at prior x price_factor.
    A disposal: realised against the fraction's basis, recorded with qty 0."""
    paid = 0.0
    for fr in [x for x in book.fractions if x.isin == isin]:
        if prior is None or not prior > 0:
            raise ValueError(f"{t} {isin}: a fractional entitlement needs the "
                             f"prior close to price it, and there is none")
        px = prior * price_factor
        proceeds = fr.units * px
        book.settle_fraction(fr, t, proceeds)
        paid += proceeds
        trades.append(_trade(t, isin, "SELL_FRACTIONAL", 0, None, px, 0.0))
        warnings.append({"kind": "fractional_entitlement", "isin": isin, "date": t,
                         "factor": factor, "units": fr.units, "price": px,
                         "proceeds": proceeds, "basis": fr.basis})
    return paid


def _rescale_pending(dec, factors):
    """A share-count action between a decision at M and its execution: the
    planned partial quantities and the reference closes follow it, so a
    2-for-1 split does not halve a planned sale or read as -50% slippage.
    Returns a COPY -- the decision as recorded at M is never rewritten with
    what happened after M."""
    if not dec:
        return dec
    d = dict(dec)
    if d.get("reference_close"):
        d["reference_close"] = {i: (v * factors[i] if i in factors else v)
                                for i, v in d["reference_close"].items()}
    if d.get("selldown"):
        d["selldown"] = {**d["selldown"], "plan": [
            [i, int(math.floor(q / factors[i] + 1e-6)) if i in factors else q]
            for i, q in d["selldown"]["plan"]]}
    ts = d.get("tranche_sell")
    if ts and ts.get("isin") in factors:
        d["tranche_sell"] = {**ts, "qty": int(math.floor(ts["qty"] / factors[ts["isin"]] + 1e-6))}
    return d


# Warnings that mean "this exit found no quote today"; qty None = whole holding.
_DEFERRED = ("exit_deferred_no_price", "intra_month_exit_no_price", "gear_sell_no_price")


def _register_deferred(new_warnings, pending_exits) -> None:
    for w in new_warnings:
        if w.get("kind") in _DEFERRED:
            q = w.get("qty")
            prev = pending_exits.get(w["isin"], 0)
            pending_exits[w["isin"]] = (None if q is None or prev is None
                                        else prev + int(q))


def _retry_exits(t, book, cash, open_w, cost_model, trades, warnings,
                 pending_exits) -> float:
    """At open(t): every exit still waiting for a quote, then every
    written-down name that trades again (a recovery, sold at its first real
    quote against its original basis and dates). No quote, no cash."""
    for isin in list(pending_exits):
        held = book.holdings(isin)
        if held <= 0:
            pending_exits.pop(isin)
            continue
        px = _price(open_w, t, isin)
        if px is None:
            continue
        q = pending_exits.pop(isin)
        qty = held if q is None else min(int(q), held)
        if qty <= 0:
            continue
        c = cost_model.sell_cost(qty * px, 1)
        book.sell(isin, t, qty, px, c - cost_model.sell_stt(qty * px))
        cash += qty * px - c
        trades.append(_trade(t, isin, "SELL", qty, None, px, c))
        warnings.append({"kind": "exit_retried", "isin": isin, "date": t,
                         "qty": int(qty), "price": px})
    for isin in list(book.written_down):
        px = _price(open_w, t, isin)
        if px is None:
            continue
        qty = book.recover(isin)
        c = cost_model.sell_cost(qty * px, 1)
        book.sell(isin, t, qty, px, c - cost_model.sell_stt(qty * px))
        cash += qty * px - c
        trades.append(_trade(t, isin, "SELL_RECOVERY", qty, None, px, c))
        warnings.append({"kind": "recovery", "isin": isin, "date": t,
                         "qty": int(qty), "price": px})
    return cash


def _write_down(t, book, isin, n, last_close, warnings) -> None:
    basis = sum(l.qty * l.cost_per_share for l in book.lots(isin))
    qty = book.write_down(isin)
    warnings.append({"kind": "write_down", "isin": isin, "date": t,
                     "missing_sessions": n, "qty": int(qty),
                     "last_close": last_close.get(isin), "basis": basis})


def _action_map(actions) -> Dict[date, List[dict]]:
    out: Dict[date, List[dict]] = {}
    if actions is None or len(actions) == 0:
        return out
    a = actions.copy()
    a["ex_date"] = pd.to_datetime(a["ex_date"]).dt.date
    for r in a.to_dict("records"):
        out.setdefault(r["ex_date"], []).append(r)
    return out


def _dividend_map(panel) -> Dict[date, List[tuple]]:
    out: Dict[date, List[tuple]] = {}
    if "dividend" not in panel.columns:
        return out
    d = panel.loc[panel["dividend"] > 0, ["date", "isin", "dividend"]]
    for r in d.itertuples(index=False):
        out.setdefault(r.date, []).append((r.isin, float(r.dividend)))
    return out


# -- calendar helpers --------------------------------------------------
def _month_ends(sessions):
    out = {}
    for d in sessions:
        out[(d.year, d.month)] = d
    return set(out.values())


def _month_starts(sessions):
    out = {}
    for d in sessions:
        out.setdefault((d.year, d.month), d)
    return set(out.values())


def _risk_off_series(indices, sessions, trend_filter) -> Dict[date, bool]:
    """§6 RISK_OFF, keyed by the engine's month-end SESSIONS.

    `crash_rule` resamples to calendar month-ends (2016-01-31, a Sunday), but
    the decision happens on the last session of the month (2016-01-29). Keying
    the result by (year, month) and re-attaching it to the real session is the
    difference between the filter working and silently never firing.
    """
    if trend_filter == "off" or indices is None or len(indices) == 0:
        return {}
    from pflab.portfolio.crash_rule import month_end_closes, risk_off as ro_fn
    s = indices.copy()
    s["date"] = pd.to_datetime(s["date"]).dt.date
    ser = pd.Series(s["close"].values, index=s["date"])
    flags = ro_fn(month_end_closes(ser))
    by_month = {(ts.year, ts.month): bool(v) for ts, v in flags.items()}
    return {d: by_month.get((d.year, d.month), False) for d in _month_ends(sessions)}


# -- NAV paths ---------------------------------------------------------
def _finalise(equity, book, last_close, cost_model, tax_policy, sessions, taxes):
    from pflab.eval.metrics import unitized_nav
    if equity.empty:
        return equity, taxes
    equity = equity.sort_values("date").reset_index(drop=True)
    equity["total"] = equity["equity_value"] + equity["cash"]

    # Taxes have already left `cash`, so the ledger total IS the after-tax
    # path; the pre-tax path adds the cumulative liability back.
    paid = pd.Series(0.0, index=equity.index)
    by_date: Dict[date, float] = {}
    for r in taxes:
        by_date[r["paid_on"]] = by_date.get(r["paid_on"], 0.0) + r["tax"]
    cum = 0.0
    for i, d in enumerate(equity["date"]):
        cum += by_date.get(d, 0.0)
        paid.iloc[i] = cum
    equity["tax_paid_cum"] = paid
    equity["nav_post"] = unitized_nav(equity["total"], equity["flow"])
    equity["nav_pre"] = unitized_nav(equity["total"] + paid, equity["flow"])

    last = equity["date"].iloc[-1]
    prices = {i: last_close.get(i, 0.0) for i in book.positions()}
    # E1 §15, 2026-09-27 (audit defect 3): every book owes FY(last)'s tax --
    # realised gains, dividends and interest -- whether or not it still holds
    # anything, and a failure here invalidates the run rather than reading as
    # zero tax. The lot book gets the deductible cost only (no STT, s.48).
    ft = book.simulate_liquidation(
        last, prices,
        lambda n: cost_model.sell_cost(n, 1) - cost_model.sell_stt(n))
    liq_tax = ft.total
    sell_costs = sum(cost_model.sell_cost(q * prices.get(i, 0.0), 1)
                     for i, q in book.positions().items())
    adj = equity["total"].copy()
    adj.iloc[-1] = adj.iloc[-1] - liq_tax - sell_costs
    equity["nav_liq"] = unitized_nav(adj, equity["flow"])
    equity["liquidation_tax"] = 0.0
    equity["liquidation_costs"] = 0.0
    equity.loc[equity.index[-1], "liquidation_tax"] = liq_tax
    equity.loc[equity.index[-1], "liquidation_costs"] = sell_costs
    # The pre-tax liquidation path: everything sold on the last session at the
    # same costs, but no tax anywhere -- taxes already paid are added back and
    # the liquidation tax is not charged. This is the path task 2.5's realistic
    # control measures, so the null does not have to model the tax code.
    pre = equity["total"] + paid
    pre.iloc[-1] = pre.iloc[-1] - sell_costs
    equity["nav_liq_pre"] = unitized_nav(pre, equity["flow"])
    return equity, taxes


# -- benchmarks (task 2.2) ---------------------------------------------
def run_benchmark(config, period, index_series, cost_model, tax_policy,
                  name: str, expense_ratio: float = 0.0) -> RunResult:
    """B1-B3: the index as a single synthetic security through the same loop.

    Same SIP, same cash sleeve, same costs and the same tax engine. No band,
    no trend filter, never sold until liquidation (charter §10).
    """
    s = index_series.copy()
    s["date"] = pd.to_datetime(s["date"]).dt.date
    s = s[s["date"] <= period.end].sort_values("date")
    if expense_ratio:
        # The stated rate is the REALISED annual rate: compounded by calendar
        # days elapsed. Counting sessions over 365 (as first written) applied
        # a 0.30% drag as roughly 0.21% a year. Corrected 2026-09-21.
        first = pd.Timestamp(s["date"].iloc[0])
        days = (pd.to_datetime(s["date"]) - first).dt.days.to_numpy()
        s["close"] = s["close"].values * (1.0 - expense_ratio) ** (days / 365.25)
    isin = f"IDX:{name}"
    panel = pd.DataFrame({
        "date": s["date"], "isin": isin, "symbol": name, "series": "EQ",
        "instrument_type": "STK", "open": s["close"], "high": s["close"],
        "low": s["close"], "close": s["close"], "prev_close": s["close"],
        "volume": 1, "turnover": 1e18, "adj_factor": 1.0,
        "adj_close": s["close"], "adj_open": s["close"], "dividend": 0.0})
    # A benchmark shares the experiment's MONEY -- SIP, starting cash, cash
    # rate, delisting treatment -- and nothing about how it picks stocks. The
    # strategy is therefore built from a whitelist, not copied and patched.
    # Copying and patching broke on 2026-09-21: E1c's knobs (signal,
    # rebalance, weighting, selection_n) were not in the patch list, so every
    # benchmark ran E1c's rules on one security, whose z-score is undefined,
    # and never bought (B1-B3 and B5 all read the 6% cash rate). A whitelist
    # cannot leak a knob that a future charter adds. No hooks either: a
    # benchmark is an index, not a candidate.
    SHARED = ("sip_amount", "initial_cash", "cash_rate_annual",
              "delisting", "delist_confirm_sessions")
    src = config.get("strategy", {}) or {}
    strategy = {k: src[k] for k in SHARED if k in src}
    strategy.update({"n_hold": 1, "band_exit_rank": 10**9,
                     "max_buys_per_month": 1, "trend_filter": "off",
                     "lookback_sessions": 1, "skip_sessions": 0})
    universe = {"series": ["EQ"], "min_sessions": 1, "top_n_by_turnover": 1,
                "turnover_window": 1, "min_price": 0.0, "max_adv_fraction": 1.0,
                # the benchmark IS one synthetic security; an index
                # membership table has nothing to say about it
                "mode": "turnover_top_n"}
    cfg = {"strategy": strategy, "universe": universe}
    return run(cfg, period, panel, None, cost_model, tax_policy)


def run_equal_weight_universe(config, period, panel, cost_model, tax_policy,
                              actions=None, membership=None) -> RunResult:
    """B4 (§10): equal weight of the E1 eligible universe, rebalanced monthly.

    Same SIP schedule, same cash sleeve, same costs and the same tax engine as
    E1. It differs from E1 in exactly one way, which is the point of the
    benchmark: it DOES sell to rebalance, so it shows what the universe itself
    did rather than what E1's selection did. Monthly turnover here is expected
    to be far higher than E1's, and its tax bill with it.
    """
    strat = config.get("strategy", {})
    sip = float(strat.get("sip_amount", 50_000.0))
    cash_rate = float(strat.get("cash_rate_annual", 0.06))

    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"]).dt.date
    if panel["date"].max() > period.end:
        raise ValueError("panel carries rows past the period end")
    sessions = sorted(panel["date"].unique())
    close_w, open_w = _wide(panel, "close"), _wide(panel, "open")
    div_map, act_map = _dividend_map(panel), _action_map(actions)

    book = LotBook(tax_policy)
    cash = float(strat.get("initial_cash", 0.0))
    last_close: Dict[str, float] = {}
    trades: List[dict] = []
    warnings: List[dict] = []
    rows: List[dict] = []
    taxes: List[dict] = []
    pending: Optional[list] = None
    seen_fy, prev = set(), None
    month_ends, month_starts = _month_ends(sessions), _month_starts(sessions)
    traded_by_date = {d: set(g) for d, g in panel.groupby("date")["isin"]}
    suspended: Dict[str, int] = {}
    confirm = int(strat.get("delist_confirm_sessions",
                            DELIST_CONFIRM_SESSIONS_S9
                            if strat.get("delisting") == "total_loss"
                            else DELIST_CONFIRM_SESSIONS))

    for t in sessions:
        in_window = period.start <= t <= period.end
        flow = 0.0
        # the same order and the same §9 treatment as `run` (E1 §15, 2026-09-27)
        _credited, _dividends = _apply_ex_date_events(
            t, book, act_map, div_map, tax_policy, warnings, trades,
            last_close=last_close)
        cash += _credited
        if in_window and book.written_down:
            cash = _retry_exits(t, book, cash, open_w, cost_model, trades,
                                warnings, {})
        if t in month_starts and in_window:
            fy = fy_of(t)
            if fy not in seen_fy:
                seen_fy.add(fy)
                if len(seen_fy) > 1 and (fy - 1) not in book.settled:
                    ft = book.settle_fy(fy - 1)
                    cash -= ft.total
                    taxes.append({"fy": fy - 1, "stcg": ft.stcg_realised,
                                  "ltcg": ft.ltcg_realised, "dividends": ft.dividends,
                                  "interest": ft.interest,
                                  "tax": ft.total, "paid_on": t})
            cash += sip
            flow += sip
            if pending:
                cash = _rebalance(pending, t, book, cash, open_w, cost_model, trades)
                pending = None

        traded_today = traded_by_date.get(t, set())
        for isin in list(book.positions()):
            if isin in traded_today:
                suspended.pop(isin, None)
                continue
            suspended[isin] = suspended.get(isin, 0) + 1
            if suspended[isin] >= confirm and in_window:
                _write_down(t, book, isin, suspended.pop(isin), last_close, warnings)
        if prev is not None and cash > 0:
            grown = cash * (1.0 + cash_rate * (t - prev).days / 365.0)
            book.interest(t, grown - cash)
            cash = grown
        for isin in traded_today:
            v = close_w.at[t, isin] if isin in close_w.columns else None
            if v is not None and not pd.isna(v):
                last_close[isin] = float(v)
        hv = {i: q * last_close.get(i, 0.0) for i, q in book.positions().items()}
        rows.append({"date": t, "equity_value": sum(hv.values()), "cash": cash,
                     "flow": flow, "risk_off": False, "dividends": _dividends})

        if t in month_ends and in_window:
            hist = panel[panel["date"] <= t]
            if str(_cfg(config, "universe.mode", "turnover_top_n")) == "index_members":
                # §5: B4 is the E1b universe equal-weighted, not E1's.
                pending = list(uni.eligible_index_members(
                    hist, membership,
                    str(_cfg(config, "universe.index", "NIFTY200")), t,
                    min_sessions=int(_cfg(config, "universe.min_sessions", 250)),
                    min_price=float(_cfg(config, "universe.min_price", 10.0)),
                    series=tuple(_cfg(config, "universe.series", ["EQ"]))))
            else:
                pending = list(uni.eligible(
                    hist, series=tuple(_cfg(config, "universe.series", ["EQ"])),
                    min_sessions=int(_cfg(config, "universe.min_sessions", 250)),
                    top_n=int(_cfg(config, "universe.top_n_by_turnover", 500)),
                    turnover_window=int(_cfg(config, "universe.turnover_window", 126)),
                    min_price=float(_cfg(config, "universe.min_price", 10.0))))
        prev = t

    equity = pd.DataFrame(rows)
    equity, tax_rows = _finalise(equity, book, last_close, cost_model,
                                 tax_policy, sessions, taxes)
    return RunResult(equity=equity,
                     trades=pd.DataFrame(trades) if trades else _empty_trades(),
                     decisions=[], taxes=pd.DataFrame(tax_rows) if tax_rows
                     else pd.DataFrame(columns=["fy", "stcg", "ltcg", "dividends",
                                                "interest", "tax", "paid_on"]),
                     warnings=warnings, config=config,
                     hooks_active=hk.HookSet().active())


def _rebalance(target_names, t, book, cash, open_w, cost_model, trades) -> float:
    """Sell out of names that left the universe, then equal-weight the rest."""
    prices = {i: p for i in set(target_names) | set(book.positions())
              if (p := _price(open_w, t, i)) is not None}
    for isin, qty in list(book.positions().items()):
        if isin in target_names or isin not in prices or qty <= 0:
            continue
        px = prices[isin]
        c = cost_model.sell_cost(qty * px, 1)
        book.sell(isin, t, qty, px, c - cost_model.sell_stt(qty * px))
        cash += qty * px - c
        trades.append(_trade(t, isin, "SELL_REBAL", qty, px, px, c))

    investable = [n for n in target_names if n in prices]
    if not investable:
        return cash
    equity = sum(q * prices[i] for i, q in book.positions().items() if i in prices)
    target = (equity + cash) / len(investable)
    for isin in investable:                       # trim first, to free cash
        px = prices[isin]
        held = book.holdings(isin)
        excess = held * px - target
        if excess > px:
            qty = min(held, int(excess // px))
            if qty > 0:
                c = cost_model.sell_cost(qty * px, 1)
                book.sell(isin, t, qty, px, c - cost_model.sell_stt(qty * px))
                cash += qty * px - c
                trades.append(_trade(t, isin, "SELL_REBAL", qty, px, px, c))
    for isin in investable:
        px = prices[isin]
        short = target - book.holdings(isin) * px
        if short <= px or cash <= 0:
            continue
        qty = int(min(short, cash) // px)
        if qty < 1:
            continue
        qty = _fit_to_cash(qty, px, cash, cost_model)
        if qty < 1:
            continue
        c = cost_model.buy_cost(qty * px)
        book.buy(isin, t, qty, px, c - cost_model.buy_stt(qty * px))
        cash -= qty * px + c
        trades.append(_trade(t, isin, "BUY_REBAL", qty, px, px, c))
    return cash
