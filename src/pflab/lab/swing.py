"""The lab's DAILY replay for the swing sleeve (S81 B5; registered in `docs/protocols/s81_selling_swing_protocol.md`). SELF-CONTAINED beside `engine.py`, `toolkit.py` and
`harvest_replay.py` (numpy, pandas, dateutil): the same file runs in the Docker sandbox and on the host in the tests. `engine.py` is NOT changed in its monthly behaviour: a policy runs
here only when it declares `CADENCE = "daily"` (or the job's cfg says `"engine": "swing"`, which the harvesting test uses to run monthly policies through the same machinery).

A daily policy has the usual signature, `decide(state, forecasts, sims, storylines, params) -> {"entries": [...], "exits": [...]}`:

    entries   [{"key": label, "weight": fraction of the sleeve, "stop": 0.08, "target": 0.16, "max_days": 30}, ...] in priority order (stop and target are fractions of the FILL price)
    exits     [label, ...]  positions to leave at the next session's close (a discretionary exit)
    state     the monthly state plus `positions` {label: {entry_day, entry_price, days_held, stop, target, max_days, last_price}}, `slots` (free positions) and `results`
              {label: [dates the name's financial results became known, up to today]} (empty where the data has none).

What the replay does (every assumption is listed in the protocol and recorded in the run's output as `assumptions`):
  * the decision at the close of session t is filled at the close of t+1 (like the monthly lab); stops, targets and time exits are checked on the later sessions from the day's
    open/high/low (adjusted); a stop fills at the stop, or the open if it gaps below, MINUS slippage: never better than the stop; a target fills at the target minus slippage; a
    session that reaches both takes the stop; a time exit fills at the close of the session the position has been held for `max_days` sessions;
  * no same-day round trip in a name: a sale due on the entry day waits for the next session unless it is a stop (only possible with `entry_fill="open"`); a name sold today is not
    bought today, and a harvest sale is bought back the NEXT session;
  * slippage by liquidity: `slip_fraction` below; every fill is worse than its reference by that fraction;
  * tax: the lab's FIFO book with the tax engine's dated rows passed in `cfg["tax"]` (rates and exemption are never typed here; the defaults are the engine's own constants and are
    pinned to the tax rows by a test); a lot is long-term when held MORE than 12 calendar months;
  * per-sleeve accounting: every closed round trip is logged with its sleeve, days held, return and reason.
"""
from __future__ import annotations

import math
import warnings
from bisect import bisect_right
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:                                                               # in the sandbox the files sit side by side; on the host they are in the package
    import engine as E
    import harvest_replay as H
except ImportError:                                                # pragma: no cover - exercised on the host
    from pflab.lab import engine as E
    from pflab.lab import harvest_replay as H

SLIP = {"half_spread_base": 0.0005, "half_spread_cap": 0.005, "turnover_ref": 1e8, "impact_y": 1.0, "sigma_window": 20, "sigma_floor": 0.005}
SIZING = {"weight": 0.09, "max_positions": 10, "max_new_per_day": 3}
SWING_CFG = {"entry_fill": "close", "slippage": None, "harvest": False, "harvest_rule": dict(H.DEFAULT_RULE), "slip": dict(SLIP), "sizing": dict(SIZING), "daily_history_rows": 320,
             "tax": {"st_rate": E.ST_RATE, "lt_rate": E.LT_RATE, "lt_exempt": E.LT_EXEMPT, "slab": E.SLAB, "lt_months": 12, "carry_years": 0}}
ASSUMPTIONS = [
    "fills: decision at the close of t, fill at the close of t+1; stops/targets read the adjusted day range (low/high/open) of the later sessions; both in one session -> the stop",
    "slippage = half_spread + Y * sigma_d * sqrt(order / traded value), half_spread = clip(0.0005 * sqrt(1e8 / traded value), 0.0005, 0.005), Y = 1.0, sigma_d = 20-session daily volatility",
    "tax: the tax engine's dated rows (short-term / long-term rates, yearly exemption) applied to the whole window; a lot is long-term when held MORE than 12 calendar months",
    "no turnover caps in a swing sleeve; one position per name, 9% of the sleeve each, at most 10 positions, at most 3 new entries a day",
    "idle cash earns the lab's cash rate untaxed; dividends are inside the adjusted closes",
]


# --- liquidity and slippage ---------------------------------------------------------------------------------------------------------

def slip_fraction(order_value: float, traded_value: float, sigma_d: float, p: Optional[dict] = None) -> float:
    """The fraction a fill is moved against the trader: a spread that widens as the name trades less, plus a square-root impact in the order's share of the day's traded value.
    Never negative, so a fill is never better than its reference price. Grows with the order's share (a stated assumption, not a measurement)."""
    p = {**SLIP, **(p or {})}
    tv = max(float(traded_value) if traded_value == traded_value else 0.0, 1e6)
    spread = min(max(p["half_spread_base"] * math.sqrt(p["turnover_ref"] / tv), p["half_spread_base"]), p["half_spread_cap"])
    share = min(max(float(order_value), 0.0) / tv, 1.0)
    sigma = max(float(sigma_d) if sigma_d == sigma_d else 0.0, p["sigma_floor"])
    return float(spread + p["impact_y"] * sigma * math.sqrt(share))


def can_exit_today(entry_day, day, kind: str) -> bool:
    """The no-same-day-round-trip rule: the shares bought today may not be sold today, unless a stop fires."""
    return day > entry_day or kind == "stop"


# --- the tax book -------------------------------------------------------------------------------------------------------------------

def tax_with(g: Dict[str, float], tp: dict) -> float:
    """The year's tax on its gains by bucket (the engine's `tax_of`, with the rates and the exemption passed in from the tax engine's rows)."""
    st, lt_eq, lt_o, slab = g.get("st_eq", 0.0), g.get("lt_eq", 0.0), g.get("lt_other", 0.0), g.get("slab", 0.0)
    if st < 0:
        lt_eq, st = lt_eq + st, 0.0
    if lt_eq < 0:
        lt_o, lt_eq = lt_o + lt_eq, 0.0
    if lt_o < 0:
        lt_o = 0.0
    return tp["st_rate"] * st + tp["lt_rate"] * max(0.0, lt_eq - tp["lt_exempt"]) + tp["lt_rate"] * lt_o + tp["slab"] * max(0.0, slab)


ST_BUCKETS, LT_BUCKETS = ("st_eq", "slab"), ("lt_other", "lt_eq")           # the tax engine's ST_111A / ST_SLAB and LT_112 / LT_112A, in its netting order


def net_year(realised: Dict[str, float], carried: List[tuple], fy: int, years: int) -> Tuple[Dict[str, float], List[tuple]]:
    """One financial year's statutory netting with the losses carried in (`tax.gains.net_year`, on the lab's four buckets): within short-term, within long-term, a short-term loss
    against long-term gains, then the carried losses oldest first (a short-term loss against anything, a long-term loss against long-term only; none older than `years`).
    `carried`: [(origin_fy, is_long_term, amount)]. Returns (taxable gains by bucket before the exemption, losses carried out)."""
    b = {k: float(realised.get(k, 0.0)) for k in ST_BUCKETS + LT_BUCKETS}
    for order in (ST_BUCKETS, LT_BUCKETS):
        for k in order:
            if b[k] < 0:
                for g in order:
                    if b[g] > 0:
                        use = min(-b[k], b[g])
                        b[k] += use
                        b[g] -= use
                    if b[k] >= 0:
                        break
    for k in ST_BUCKETS:
        if b[k] < 0:
            for g in LT_BUCKETS:
                if b[g] > 0:
                    use = min(-b[k], b[g])
                    b[k] += use
                    b[g] -= use
                if b[k] >= 0:
                    break
    remaining: List[tuple] = []
    for origin, is_lt, amt in sorted(c for c in carried if fy - c[0] <= years):
        for g in (LT_BUCKETS if is_lt else ST_BUCKETS + LT_BUCKETS):
            if amt <= 1e-12:
                break
            if b[g] > 0:
                use = min(amt, b[g])
                b[g] -= use
                amt -= use
        if amt > 1e-9:
            remaining.append((origin, is_lt, amt))
    st_left = sum(b[k] for k in ST_BUCKETS if b[k] < 0)
    lt_left = sum(b[k] for k in LT_BUCKETS if b[k] < 0)
    if st_left < 0:
        remaining.append((fy, False, -st_left))
    if lt_left < 0:
        remaining.append((fy, True, -lt_left))
    return {k: max(v, 0.0) for k, v in b.items()}, remaining


def tax_from_taxable(t: Dict[str, float], tp: dict) -> float:
    return tp["st_rate"] * t["st_eq"] + tp["lt_rate"] * max(0.0, t["lt_eq"] - tp["lt_exempt"]) + tp["lt_rate"] * t["lt_other"] + tp["slab"] * t["slab"]


def bucket(tax_class: str, acquired, day, months: int = 12) -> str:
    lt = H.is_long_term(acquired, day, months)
    if tax_class == "EQUITY":
        return "lt_eq" if lt else "st_eq"
    return "lt_other" if lt else "slab"


class TaxBook(E.Book):
    """The lab's FIFO book with (a) the tax rates and exemption passed in, (b) the long-term test in calendar months, (c) slippage on every fill, (d) a log of the sleeve's trades."""

    def __init__(self, cash: float, cfg: dict):
        super().__init__(cash, cfg)
        self.tp = {**SWING_CFG["tax"], **(cfg.get("tax") or {})}
        self.slipper: Optional[Callable] = None
        self.slip_paid = 0.0
        self.last_fill = 0.0
        self.trades: List[dict] = []
        self._carried: List[tuple] = []                            # losses carried into the year being traded (A2); empty when the carry-forward years are 0
        self._settled: set = set()

    def carry_in(self, fy: int) -> List[tuple]:
        """The losses carried into financial year `fy`: every earlier year's gains are settled once, in order (the rows are final by then)."""
        years = int(self.tp.get("carry_years", 0))
        if not years:
            return []
        for y in sorted(k for k in self.gains if k < fy and k not in self._settled):
            _, self._carried = net_year(self.gains[y], self._carried, y, years)
            self._settled.add(y)
        return self._carried

    def year_tax(self, fy: int, g: Dict[str, float]) -> float:
        """The tax on financial year `fy`'s running gains `g` given the losses carried in (A2); with no carry-forward years, the lab's one-year netting."""
        if not int(self.tp.get("carry_years", 0)):
            return tax_with(g, self.tp)
        taxable, _ = net_year(g, self.carry_in(fy), fy, int(self.tp["carry_years"]))
        return tax_from_taxable(taxable, self.tp)

    def sell_cost(self, k, qty, px, day, kind, tax_class):
        fee = qty * px * self.rate(kind, "sell")
        gains, left = {}, qty
        for acq, lq, cpu in self.lots.get(k, []):
            take = min(lq, left)
            b = bucket(tax_class, acq, day, self.tp["lt_months"])
            gains[b] = gains.get(b, 0.0) + take * (px - cpu) - fee * take / max(qty, 1e-12)
            left -= take
            if left <= 1e-12:
                break
        before = self.gains.get(E.fin_year(day), {})
        after = dict(before)
        for b, v in gains.items():
            after[b] = after.get(b, 0.0) + v
        fy = E.fin_year(day)
        return fee, max(0.0, self.year_tax(fy, after) - self.year_tax(fy, before)), gains

    def sell(self, k, qty, px, day, kind, tax_class):
        qty = min(qty, self.qty(k))
        if qty <= 1e-12:
            return
        s = self.slipper(k, "sell", qty * px) if self.slipper else 0.0
        self.slip_paid += qty * px * s
        self.last_fill = px * (1.0 - s)
        super().sell(k, qty, self.last_fill, day, kind, tax_class)

    def buy(self, k, rupees, px, day, kind):
        s = self.slipper(k, "buy", rupees) if self.slipper else 0.0
        self.last_fill = px * (1.0 + s)
        before = self.qty(k)
        super().buy(k, rupees, self.last_fill, day, kind)
        if self.qty(k) > before:
            self.slip_paid += rupees * s / (1.0 + s)


def liquidation(book: TaxBook, row: np.ndarray, cidx: dict, meta: dict, day) -> dict:
    """The value if every holding were sold at the last close: charges (no slippage) and the tax on the sale in the year's books. Deferred tax therefore counts as owed."""
    fy = E.fin_year(day)
    gy = dict(book.gains.get(fy, {}))
    before = book.year_tax(fy, gy)
    fees, gross = 0.0, 0.0
    for k in list(book.lots):
        q = book.qty(k)
        if q <= 1e-12 or k not in cidx or np.isnan(row[cidx[k]]):
            continue
        px = float(row[cidx[k]])
        kind = "etf" if meta[k].get("etf") else "equity"
        fee, _, g = book.sell_cost(k, q, px, day, kind, meta[k].get("tax", "EQUITY"))
        fees += fee
        gross += q * px
        for b, v in g.items():
            gy[b] = gy.get(b, 0.0) + v
    tax = max(0.0, book.year_tax(fy, gy) - before)
    return {"value": book.cash + gross - fees - tax, "tax": tax, "charges": fees}


# --- the replay -------------------------------------------------------------------------------------------------------------------

def _arr(df: Optional[pd.DataFrame], px: pd.DataFrame, pxv: np.ndarray) -> np.ndarray:
    """An OHLC ratio frame as a level array on the cleaned adjusted close (a missing ratio = the close itself)."""
    if df is None:
        return pxv
    r = df.reindex(index=px.index, columns=px.columns).to_numpy(float)
    return np.where(np.isfinite(r), pxv * r, pxv)


def replay_daily(decide: Callable, params: dict, data: dict, start, end, cfg: Optional[dict] = None, shuffle_seed: Optional[int] = None, cadence: str = "daily",
                 harvest: Optional[bool] = None) -> dict:
    """Replay `decide` over [start, end] one session at a time. `cadence="monthly"` runs the monthly engine's own decision and rebalance rules (so the harvesting test and the index
    control use the same book); `"daily"` runs the swing mechanics described in the module docstring."""
    cfg = {**E.DEFAULT_CFG, **SWING_CFG, **(cfg or {})}
    cfg["tax"] = {**SWING_CFG["tax"], **(cfg.get("tax") or {})}
    cfg["slip"] = {**SLIP, **(cfg.get("slip") or {})}
    cfg["sizing"] = {**SIZING, **(cfg.get("sizing") or {})}
    cfg["harvest_rule"] = {**H.DEFAULT_RULE, **(cfg.get("harvest_rule") or {})}
    do_harvest = bool(cfg["harvest"] if harvest is None else harvest)
    daily = cadence == "daily"
    slip_on = (cfg["slippage"] or ("liquidity" if daily else "off")) == "liquidity"
    px, to, meta = data["px"], data["turnover"], data["meta"]
    cal = px.index[px.index <= pd.Timestamp(end)]
    pos = {d: i for i, d in enumerate(cal)}
    cols = list(px.columns)
    cidx = {k: i for i, k in enumerate(cols)}
    pxv = px.to_numpy(float)
    tov = to.reindex(index=px.index, columns=px.columns).to_numpy(float)
    ohlc = data.get("ohlc") or {}
    openv, highv, lowv = (_arr(ohlc.get(n), px, pxv) for n in ("open", "high", "low"))
    cnt = px.notna().cumsum()
    cntv = cnt.to_numpy()
    stock_idx = [i for i, k in enumerate(cols) if not meta[k].get("etf")]
    etf_idx = [i for i, k in enumerate(cols) if meta[k].get("etf")]
    results = {k: sorted({pd.Timestamp(x).date() for x in v}) for k, v in (data.get("results") or {}).items()}
    rng = np.random.default_rng(shuffle_seed) if shuffle_seed is not None else None
    rf = (1 + cfg["cash_rate"]) ** (1 / 252) - 1
    book = TaxBook(cfg["capital"], cfg)
    sz = cfg["sizing"]

    if daily:
        sess = cal[(cal >= pd.Timestamp(start))]
        if len(sess) < 3:
            raise ValueError("the window holds too few sessions")
        decision_days = set(sess[:-1])
        loop_start = sess[0]
        by_trade: Dict = {}
    else:
        signals = E.month_ends(cal, start, end)
        trade_day = {d: cal[pos[d] + 1] for d in signals if pos[d] + 1 < len(cal)}
        by_trade = {v: k for k, v in trade_day.items()}
        if not by_trade:
            raise ValueError("the window holds no month-end with a next session")
        decision_days = set()
        loop_start = min(by_trade)

    P: Dict[str, dict] = {}                                       # open swing positions (real keys)
    pend_entries: List[dict] = []
    pend_exits: set = set()
    pend_rebuy: List[Tuple[str, float]] = []
    first_done, month_trade, month_key = False, 0.0, None
    values, dates, n_dec, failures = [], [], 0, 0
    liq_values: List[float] = []                                   # S82 (C4): the liquidation-marked path, each session's value if everything were sold that session (cfg["track_liq"])
    kind_of = lambda k: "etf" if meta[k].get("etf") else "equity"
    taxcls = lambda k: meta[k].get("tax", "EQUITY")

    def make_slipper(i: int):
        def slipper(k: str, side: str, value: float) -> float:
            ci = cidx[k]
            tv = tov[i, ci]
            if not tv == tv or tv <= 0:
                w = tov[max(0, i - 19):i + 1, ci]
                w = w[np.isfinite(w) & (w > 0)]
                tv = float(np.median(w)) if len(w) else 1e6
            lo = max(0, i - cfg["slip"]["sigma_window"])
            seg = pxv[lo:i + 1, ci]
            seg = seg[np.isfinite(seg) & (seg > 0)]
            sig = float(np.std(np.diff(np.log(seg)))) if len(seg) > 5 else float("nan")
            return slip_fraction(value, tv, sig, cfg["slip"])
        return slipper

    def value_now(row):
        return book.cash + sum(book.qty(k) * float(row[cidx[k]]) for k in book.lots if book.qty(k) > 0 and not np.isnan(row[cidx[k]]))

    def close_position(k, ref, D, why):
        q = book.qty(k)
        book.sell(k, q, ref, D.date(), kind_of(k), taxcls(k))
        pi = P.pop(k)
        traded_today.add(k)
        book.trades.append({"sleeve": cfg.get("sleeve", "swing"), "key": k, "entry": str(pi["entry_day"]), "exit": str(D.date()), "days": int(pos[D] - pi["entry_i"]),
                            "ret": float(book.last_fill / pi["entry_px"] - 1.0), "why": why, "entry_px": float(pi["entry_px"]), "exit_px": float(book.last_fill), "stop": float(pi["stop"]),
                            "target": float(pi["target"])})

    for D in cal[cal >= loop_start]:
        i = pos[D]
        row = pxv[i]
        book.cash *= 1 + rf
        book.slipper = make_slipper(i) if slip_on else None
        traded_today: set = set()
        for k, q in pend_rebuy:                                    # a harvested lot is bought back the NEXT session (never the same day)
            if not np.isnan(row[cidx[k]]):
                book.buy(k, q * float(row[cidx[k]]), float(row[cidx[k]]), D.date(), kind_of(k))
                traded_today.add(k)
        pend_rebuy = []

        def run_entries():
            nonlocal pend_entries
            for e in pend_entries:
                k = e["key"]
                ci = cidx[k]
                ref = float((openv if cfg["entry_fill"] == "open" else pxv)[i, ci])
                if k in P or k in traded_today or len(P) >= sz["max_positions"] or not math.isfinite(ref) or ref <= 0:
                    continue
                V = value_now(row)
                w = min(float(e["weight"]), cfg["max_stock"])
                sec = meta[k].get("sector")
                if sec and sum(book.qty(j) * float(row[cidx[j]]) for j in book.lots if meta[j].get("sector") == sec and not np.isnan(row[cidx[j]])) / V + w > cfg["max_sector"] + 1e-9:
                    continue
                before = book.qty(k)
                book.buy(k, w * V, ref, D.date(), kind_of(k))
                if book.qty(k) > before + 1e-12:
                    fill = book.last_fill
                    P[k] = {"entry_i": i, "entry_day": D.date(), "entry_px": fill, "stop": fill * (1.0 - float(e["stop"])), "target": fill * (1.0 + float(e["target"])),
                            "max_days": int(e["max_days"])}
                    traded_today.add(k)
            pend_entries = []

        def run_exits():
            for k in list(P):
                pi = P[k]
                ci = cidx[k]
                lo, hi, op, cl = lowv[i, ci], highv[i, ci], openv[i, ci], pxv[i, ci]
                if not (np.isfinite(lo) and np.isfinite(cl)):
                    continue
                if lo <= pi["stop"]:                                   # a stop always fires, even on the entry day; at the stop, or the open if it gaps below: never better
                    close_position(k, float(min(pi["stop"], op if np.isfinite(op) else pi["stop"])), D, "stop")
                elif pi["entry_i"] == i:                               # entered today: nothing but a stop may sell it (no same-day round trip); the rest waits
                    continue
                elif hi >= pi["target"]:
                    close_position(k, float(pi["target"]), D, "target")
                elif i - pi["entry_i"] >= pi["max_days"]:
                    close_position(k, float(cl), D, "time")
                elif k in pend_exits:
                    close_position(k, float(cl), D, "discretionary")
            pend_exits.clear()

        if daily:
            if cfg["entry_fill"] == "open":
                run_entries()
                run_exits()
            else:
                run_exits()
                run_entries()
        elif D in by_trade and not (cfg.get("deploy_once") and any(book.qty(k) > 0 for k in book.lots)):     # S82 (C4): a buy-and-hold book is deployed once and never rebalanced
            d = by_trade[D]
            mk = (D.year, D.month)
            if mk != month_key:
                month_key, month_trade = mk, 0.0
            try:
                w = E._decide_at(decide, params, data, cfg, book, d, D, row, cidx, cnt, rng, shuffle_seed is not None)
            except Exception as e:
                failures += 1
                w = None
                if failures > 3 and failures > 0.25 * len(signals):
                    raise RuntimeError(f"the policy failed on {failures} decisions; last: {type(e).__name__}: {e}")
            if w is not None:
                held_before = {k for k in book.lots if book.qty(k) > 0}
                month_trade += E._rebalance(book, w, meta, cfg, D, row, cidx, first_done, month_trade)
                first_done = first_done or bool(w) if cfg.get("deploy_once") else True      # a buy-and-hold book's first deployment is the first decision that names something (exempt from the turnover caps)
                n_dec += 1
                traded_today |= held_before | {k for k in book.lots if book.qty(k) > 0}

        if do_harvest and D.date().month in tuple(cfg["harvest_rule"]["window_months"]) and i < len(cal) - 1:
            lots = {k: [list(l) for l in v] for k, v in book.lots.items() if v}
            prices = {k: float(row[cidx[k]]) for k in lots if not np.isnan(row[cidx[k]])}
            gy = book.gains.get(E.fin_year(D.date()), {})
            for o in H.harvest_step(D.date(), lots, prices, gy, {"tax": book.tp, **cfg["harvest_rule"]}, blocked=traded_today | set(P)):
                book.sell(o["key"], o["qty"], prices[o["key"]], D.date(), kind_of(o["key"]), taxcls(o["key"]))
                pend_rebuy.append((o["key"], o["qty"]))

        v = value_now(row)
        values.append(v)
        dates.append(D)
        if cfg.get("track_liq"):
            liq_values.append(liquidation(book, row, cidx, meta, D.date())["value"])

        if daily and D in decision_days:
            try:
                out = _decide_daily(decide, params, data, cfg, book, P, i, D, cidx, cols, cntv, stock_idx, etf_idx, pxv, tov, results, meta, rng, v)
                n_dec += 1
                pend_entries, pend_exits = out["entries"], out["exits"]
            except Exception as e:
                failures += 1
                pend_entries, pend_exits = [], set()
                if failures > 3 and failures > 0.25 * len(decision_days):
                    raise RuntimeError(f"the policy failed on {failures} decisions; last: {type(e).__name__}: {e}")
    return {"value": pd.Series(values, index=dates), "liq_path": pd.Series(liq_values, index=dates) if liq_values else None, "book": book, "decisions": n_dec, "failures": failures, "trades": book.trades, "open": dict(P),
            "last_row": pxv[len(cal) - 1], "last_day": cal[-1].date(), "cidx": cidx, "meta": meta}


def _decide_daily(decide, params, data, cfg, book, P, i, D, cidx, cols, cntv, stock_idx, etf_idx, pxv, tov, results, meta, rng, V) -> dict:
    """The state at the close of session `i` (rows up to i only), the policy's answer, cleaned and mapped back to the real securities."""
    px, to = data["px"], data["turnover"]
    n_hist = cntv[i]
    lo = max(0, i - cfg["turn_window"] + 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)             # an all-empty column has no median
        med = np.nanmedian(np.where(tov[lo:i + 1][:, stock_idx] > 0, tov[lo:i + 1][:, stock_idx], np.nan), axis=0) if len(stock_idx) else np.array([])
    ok = [(float(m), cols[stock_idx[j]]) for j, m in enumerate(med)
          if m == m and n_hist[stock_idx[j]] >= cfg["min_history"] and not np.isnan(pxv[i, stock_idx[j]])]
    liquid = [k for _, k in sorted(ok, key=lambda t: (-t[0], t[1]))[:cfg["n_liquid"]]]
    etfs = [cols[j] for j in etf_idx if n_hist[j] >= cfg["min_history"] and not np.isnan(pxv[i, j])]
    held = [k for k in book.lots if book.qty(k) > 0]
    universe = list(dict.fromkeys(liquid + etfs))
    lab = list(dict.fromkeys(universe + held))
    perm = {k: k for k in lab}
    if rng is not None:
        perm = E._permutation(lab, meta, rng)
    inv = {real: label for label, real in perm.items()}
    rows = cfg["daily_history_rows"]
    prices = px.iloc[max(0, i + 1 - rows):i + 1][lab]
    turn = to.iloc[max(0, i + 1 - rows):i + 1].reindex(columns=lab)
    day = D.date()
    cur = {k: book.qty(k) * float(pxv[i, cidx[k]]) / V for k in held if not np.isnan(pxv[i, cidx[k]])}
    positions = {}
    for k, pi in P.items():
        if k in inv:
            last = float(pxv[i, cidx[k]])
            positions[inv[k]] = {"entry_day": pi["entry_day"], "entry_price": pi["entry_px"], "days_held": int(i - pi["entry_i"]), "stop": pi["stop"], "target": pi["target"],
                                 "max_days": pi["max_days"], "last_price": last, "pnl": last / pi["entry_px"] - 1.0}
    res = {}
    for label in universe:
        ds = results.get(label)                                  # the policy sees the label's own data (prices, results); only where its order LANDS is shuffled
        if ds:
            seen = ds[:bisect_right(ds, day)][-8:]
            if seen:
                res[label] = seen
    state = {"day": day, "prices": prices, "turnover": turn, "weights": {l: cur[perm[l]] for l in lab if perm[l] in cur}, "value": V,
             "meta": {k: {"symbol": meta[k].get("symbol"), "etf": bool(meta[k].get("etf")), "sector": meta[k].get("sector")} for k in lab},
             "universe": list(universe), "index": data["index"].loc[:D].tail(rows), "target": None,
             "caps": {k: E.position_cap(meta[k], cfg) for k in lab}, "positions": positions,
             "slots": max(0, cfg["sizing"]["max_positions"] - len(P)), "results": res}
    w = decide(state, data.get("forecasts") or {}, data.get("sims") or {}, data.get("storylines") or {}, dict(params or {}))
    if not isinstance(w, dict):
        raise ValueError("decide must return a dict")
    entries, exits = [], set()
    for e in (w.get("entries") or []):
        try:
            label, weight = e["key"], float(e["weight"])
            stop, target, md = float(e["stop"]), float(e["target"]), int(e["max_days"])
        except (KeyError, TypeError, ValueError):
            continue
        if label in perm and math.isfinite(weight) and weight > 0 and stop > 0 and target > 0 and md > 0:
            entries.append({"key": perm[label], "weight": weight, "stop": stop, "target": target, "max_days": md})
    for label in (w.get("exits") or []):
        if label in perm:
            exits.add(perm[label])
    seen, clean = set(), []
    for e in entries:
        if e["key"] not in seen and e["key"] not in P:
            seen.add(e["key"])
            clean.append(e)
    return {"entries": clean[:cfg["sizing"]["max_new_per_day"]], "exits": exits}


# --- scoring ------------------------------------------------------------------------------------------------------------------------

def hold_decide(key: str, weight: float = 0.999) -> Callable:
    def decide(state, forecasts, sims, storylines, params=None):
        return {key: weight} if key in state["universe"] else {}
    return decide


def hold_run(data: dict, start, end, cfg: Optional[dict] = None, harvest: Optional[bool] = None) -> dict:
    """The control: the whole capital in the index ETF (`data["index_key"]`), through the same book, charges, slippage and tax (the ETF rail is lifted for this run only)."""
    key = data.get("index_key")
    if not key:
        raise ValueError("the data has no index ETF (build the panel with index_etf=True)")
    c = {**(cfg or {}), "max_etf": 1.0, "slippage": (cfg or {}).get("slippage") or "liquidity", "sleeve": "index"}
    return replay_daily(hold_decide(key), {}, data, start, end, c, None, "monthly", harvest)


def _cagr_between(v0: float, v1: float, n: int) -> float:
    return (v1 / v0) ** (252.0 / max(n, 1)) - 1.0 if v0 > 0 and v1 > 0 else -1.0


def liq_cagr(run: dict, common_start, cfg: dict) -> Tuple[float, dict]:
    """CAGR of the liquidation value over the dates from `common_start` to the end (the start value is the path's value on that day)."""
    v = run["value"]
    v = v[v.index >= pd.Timestamp(common_start)]
    liq = liquidation(run["book"], run["last_row"], run["cidx"], run["meta"], run["last_day"])
    return _cagr_between(float(v.iloc[0]), liq["value"], len(v)), liq


def paired_t(a: pd.Series, b: pd.Series, block: int = 21, resamples: int = 5000, seed: int = 81) -> dict:
    """The paired block bootstrap of the daily return difference a - b: t = mean / standard deviation of the resampled means; p = share of resampled means at or below zero."""
    idx = a.index.intersection(b.index)
    d = (a.reindex(idx).pct_change() - b.reindex(idx).pct_change()).dropna().to_numpy()
    n = len(d)
    if n < 2 * block:
        return {"t": 0.0, "p": 1.0, "n": float(n), "mean_daily": 0.0}
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(n / block))
    means = []
    left = resamples
    while left > 0:
        m = min(left, 500)
        starts = rng.integers(0, n - block + 1, size=(m, nb))
        samp = d[(starts[:, :, None] + np.arange(block)[None, None, :]).reshape(m, -1)[:, :n]]
        means.append(samp.mean(axis=1))
        left -= m
    means = np.concatenate(means)
    sd = float(means.std(ddof=1))
    return {"t": float(d.mean() / sd) if sd > 0 else 0.0, "p": float((means <= 0).mean()), "n": float(n), "mean_daily": float(d.mean())}


def trade_stats(trades: List[dict]) -> dict:
    if not trades:
        return {"n_trades": 0.0, "hit_rate": 0.0, "avg_days_held": 0.0, "avg_ret": 0.0, "stops": 0.0, "targets": 0.0, "time_exits": 0.0}
    r = [t["ret"] for t in trades]
    return {"n_trades": float(len(trades)), "hit_rate": float(np.mean([x > 0 for x in r])), "avg_days_held": float(np.mean([t["days"] for t in trades])), "avg_ret": float(np.mean(r)),
            "stops": float(sum(t["why"] == "stop" for t in trades)), "targets": float(sum(t["why"] == "target" for t in trades)),
            "time_exits": float(sum(t["why"] == "time" for t in trades))}


def score_swing(run: dict, data: dict, cfg: dict, index_run: Optional[dict] = None) -> dict:
    """The scorecard row: the engine's (after tax and charges, vs the benchmark series) plus the sleeve's own: the liquidation CAGR, the cash benchmark, the index ETF control over the
    same days, the slippage paid and the trade statistics."""
    cfg = {**E.DEFAULT_CFG, **SWING_CFG, **cfg}
    s = E.score(run, data, cfg)
    book: TaxBook = run["book"]
    v = run["value"]
    start = v.index[0] if index_run is None else max(v.index[0], index_run["value"].index[0])
    L, liq = liq_cagr(run, start, cfg)
    n = len(v[v.index >= start])
    cash_cagr = float(cfg["cash_rate"])
    s.update({"liq_cagr": L, "liq_value": liq["value"], "liq_tax": liq["tax"], "cash_cagr": cash_cagr, "excess_vs_cash": L - cash_cagr, "slippage_paid": book.slip_paid, "n_obs_common": float(n)})
    s.update(trade_stats(run["trades"]))
    if index_run is not None:
        Li, liqi = liq_cagr(index_run, start, cfg)
        pt = paired_t(v, index_run["value"])
        ddi = float((index_run["value"] / index_run["value"].cummax() - 1).min())
        s.update({"index_liq_cagr": Li, "excess_L_vs_index": L - Li, "t_vs_index": pt["t"], "p_vs_index": pt["p"], "index_max_drawdown": ddi, "extra_drawdown_vs_index": s["max_drawdown"] - ddi,
                  "index_tax_paid": index_run["book"].tax, "index_liq_tax": liqi["tax"]})
    return s


def evaluate(decide: Callable, grid: List[dict], data: dict, start, end, cfg: Optional[dict] = None, n_shuffles: int = 20, n_mc: int = 1000, seed: int = 80,
             cadence: str = "daily") -> dict:
    """Every combination of a policy over the window through the daily replay: scorecard, vs-index measures, shuffled-signal runs, Monte Carlo (the shape of `engine.evaluate`)."""
    cfg = {**E.DEFAULT_CFG, **SWING_CFG, **(cfg or {})}
    index_run = hold_run(data, start, end, cfg) if data.get("index_key") else None
    rows = []
    for p in grid:
        run = replay_daily(decide, p, data, start, end, cfg, None, cadence)
        row = {"params": p, "score": score_swing(run, data, cfg, index_run), "mc": E.monte_carlo(run["value"], n_mc, seed=seed) if n_mc else {}}
        sh = []
        for i in range(n_shuffles):
            r = replay_daily(decide, p, data, start, end, cfg, seed * 1000 + i, cadence)
            st = E.stats(r["value"], cfg["cash_rate"])
            st["liq_cagr"] = liq_cagr(r, run["value"].index[0], cfg)[0]
            sh.append(st)
        if sh:
            real = row["score"]["sharpe_daily"]
            row["shuffled"] = {"n": float(len(sh)), "cagr_mean": float(np.mean([s["cagr"] for s in sh])), "cagr_p95": float(np.percentile([s["cagr"] for s in sh], 95)),
                               "sharpe_p95": float(np.percentile([s["sharpe_daily"] for s in sh], 95)), "beats_real_frac": float(np.mean([s["sharpe_daily"] >= real for s in sh])),
                               "liq_cagr_p95": float(np.percentile([s["liq_cagr"] for s in sh], 95))}
        rows.append(row)
    srs = [r["score"]["sharpe_daily"] for r in rows]
    for r in rows:
        s = r["score"]
        s["dsr"] = E.deflated_sharpe(s["sharpe_daily"], s["n_obs"], s["skew"], s["kurt"], srs)
    return {"runs": rows, "n_trials": len(rows), "notes": list(ASSUMPTIONS), "slippage": cfg["slip"], "sizing": cfg["sizing"], "tax": cfg["tax"], "cadence": cadence}


def harvest_experiment(decides: Dict[str, Callable], data: dict, start, end, cfg: Optional[dict] = None) -> dict:
    """Claim B: each arm (a policy, or "index" for the index ETF held) with harvesting and without, through the same monthly-cadence machinery. -> {arm: {on, off, dL, tax_saved,
    extra_costs, passes_accounting}}."""
    cfg = {**E.DEFAULT_CFG, **SWING_CFG, **(cfg or {})}
    cfg["slippage"] = cfg["slippage"] or "liquidity"
    out = {}
    for arm, dec in decides.items():
        runs = {}
        for flag in (False, True):
            runs[flag] = hold_run(data, start, end, cfg, flag) if dec is None else replay_daily(dec, {}, data, start, end, cfg, None, "monthly", flag)
        t0 = max(r["value"].index[0] for r in runs.values())
        res = {}
        for flag, r in runs.items():
            L, liq = liq_cagr(r, t0, cfg)
            res[flag] = {"liq_cagr": L, "liq_value": liq["value"], "tax_paid": r["book"].tax, "liq_tax": liq["tax"], "charges": r["book"].charges + liq["charges"],
                         "slippage": r["book"].slip_paid, "end_value": float(r["value"].iloc[-1])}
        on, off = res[True], res[False]
        saved = (off["tax_paid"] + off["liq_tax"]) - (on["tax_paid"] + on["liq_tax"])
        extra = (on["charges"] - off["charges"]) + (on["slippage"] - off["slippage"])
        out[arm] = {"on": on, "off": off, "dL": on["liq_cagr"] - off["liq_cagr"], "tax_saved": saved, "extra_costs": extra, "accounting_ok": bool(saved > extra)}
    return out
