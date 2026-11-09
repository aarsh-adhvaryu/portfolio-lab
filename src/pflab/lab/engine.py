"""The lab's replay harness and scorecard (S80 phase 2). SELF-CONTAINED (numpy, pandas, math; scipy only inside `deflated_sharpe`): the same file runs in the Docker sandbox beside the
policy and the toolkit and on the host in the tests.

A policy is replayed point in time over a window: at each month-end close it is handed the state known on that day (nothing later), its weights are clipped by the rails and
traded at the NEXT session's close with Zerodha-style charges and the FIFO tax of the paper book (`paper/book.py` rules; a test pins `tax_of` to the book's). Cash earns a stated
rate. The first deployment is exempt from the turnover caps (an empty book has to be built once); every later rebalance obeys them. Prices are adjusted closes (dividends are
reinvested inside them, so dividend income and its tax are not modelled: stated in the result).

Luck is measured, not assumed: a `shuffled` run lets the policy decide as usual but lands each weight on a random OTHER security of the same kind (stocks among stocks, ETFs among
ETFs; the policy sees its holdings through the same mapping), so what its signal knew about WHICH security is destroyed while its shape (how many names, how concentrated, when it
moves) is kept. `monte_carlo` block-bootstraps the replay's own daily returns into one-year paths.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

LT_EXEMPT, ST_RATE, LT_RATE, SLAB = 125_000.0, 0.20, 0.125, 0.30                      # the paper book's tax constants (paper/book.py)
DEFAULT_CFG = {"capital": 1_000_000.0, "cash_rate": 0.065, "n_liquid": 60, "min_history": 300, "turn_window": 250, "max_stock": 0.10, "max_etf": 0.35, "max_sector": 0.25,
               "turnover_day": 0.10, "turnover_month": 0.40, "min_trade": 0.001, "min_trade_rupees": 2000.0, "max_cost_share": 0.02, "history_rows": 800,
               "charges": {"equity": {"buy": 0.0012, "sell": 0.0012}, "etf": {"buy": 0.0003, "sell": 0.0003}},
               # S81 (A50): the index the policy is measured against is HELD AS AN ETF: its yearly cost is taken out of the total-return index and its buy and sell charges and the tax of a
               # buy-and-hold (one sale at the end of the window, long-term, above the exemption) are charged. A stated ESTIMATE (Indian index ETFs charge 0.04% to 0.25% a year in
               # expenses and track slightly below their index), not read from a primary source in this session.
               "index_etf_cost": 0.0020}


# --- tax and the book -------------------------------------------------------------------------------------------------------------

def tax_of(g: Dict[str, float]) -> float:
    """The year's tax on its gains by bucket (set-off as the law allows): the same function as `paper.book.tax_of` (pinned by a test)."""
    st, lt_eq, lt_o, slab = g.get("st_eq", 0.0), g.get("lt_eq", 0.0), g.get("lt_other", 0.0), g.get("slab", 0.0)
    if st < 0:
        lt_eq, st = lt_eq + st, 0.0
    if lt_eq < 0:
        lt_o, lt_eq = lt_o + lt_eq, 0.0
    if lt_o < 0:
        lt_o = 0.0
    return ST_RATE * st + LT_RATE * max(0.0, lt_eq - LT_EXEMPT) + LT_RATE * lt_o + SLAB * max(0.0, slab)


def _bucket(tax_class: str, held_days: int) -> str:
    if tax_class == "EQUITY":
        return "lt_eq" if held_days > 365 else "st_eq"
    return "lt_other" if held_days > 365 else "slab"


def fin_year(d) -> int:
    return d.year if d.month >= 4 else d.year - 1


class Book:
    def __init__(self, cash: float, cfg: dict):
        self.cash, self.cfg = cash, cfg
        self.lots: Dict[str, List[list]] = {}                 # key -> [[acq_date, qty, cost_per_unit], ...] oldest first
        self.gains: Dict[int, Dict[str, float]] = {}
        self.charges = self.tax = self.traded = 0.0

    def qty(self, k: str) -> float:
        return sum(l[1] for l in self.lots.get(k, []))

    def rate(self, kind: str, side: str) -> float:
        return float(self.cfg["charges"][kind][side])

    def sell_cost(self, k: str, qty: float, px: float, day, kind: str, tax_class: str) -> Tuple[float, float, Dict[str, float]]:
        """(charges, tax, gains by bucket) of selling `qty` of `k` at `px`, without changing the book."""
        fee = qty * px * self.rate(kind, "sell")
        gains, left = {}, qty
        for acq, lq, cpu in self.lots.get(k, []):
            take = min(lq, left)
            b = _bucket(tax_class, (day - acq).days)
            gains[b] = gains.get(b, 0.0) + take * (px - cpu) - fee * take / max(qty, 1e-12)
            left -= take
            if left <= 1e-12:
                break
        before = self.gains.get(fin_year(day), {})
        after = dict(before)
        for b, v in gains.items():
            after[b] = after.get(b, 0.0) + v
        return fee, max(0.0, tax_of(after) - tax_of(before)), gains

    def sell(self, k: str, qty: float, px: float, day, kind: str, tax_class: str) -> None:
        qty = min(qty, self.qty(k))
        if qty <= 1e-12:
            return
        fee, tax, gains = self.sell_cost(k, qty, px, day, kind, tax_class)
        left = qty
        for lot in self.lots[k]:
            take = min(lot[1], left)
            lot[1] -= take
            left -= take
            if left <= 1e-12:
                break
        self.lots[k] = [l for l in self.lots[k] if l[1] > 1e-9]
        gy = self.gains.setdefault(fin_year(day), {})
        for b, v in gains.items():
            gy[b] = gy.get(b, 0.0) + v
        self.cash += qty * px - fee - tax
        self.charges += fee
        self.tax += tax
        self.traded += qty * px

    def buy(self, k: str, rupees: float, px: float, day, kind: str) -> None:
        r = self.rate(kind, "buy")
        if rupees * (1 + r) > self.cash:
            rupees = max(0.0, (self.cash - 2.0) / (1 + r))
        if rupees < 1.0:
            return
        fee = rupees * r
        q = rupees / px
        self.lots.setdefault(k, []).append([day, q, (rupees + fee) / q])
        self.cash -= rupees + fee
        self.charges += fee
        self.traded += rupees


# --- the rails, as the replay applies them ----------------------------------------------------------------------------------------

def clip_weights(w: Dict[str, float], meta: Dict[str, dict], cfg: dict, current: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """The hard rails on target weights: a company at most 10%, an ETF 35%, a sector 25% (increases scaled back; a position already over stays where it is, never bought), no
    negative weight, the total at most 100% (nothing is borrowed)."""
    cur = current or {}
    out = {}
    for k, v in w.items():
        if v <= 0 or k not in meta:
            continue
        lim = cfg["max_etf"] if meta[k].get("etf") else cfg["max_stock"]
        out[k] = min(v, max(lim, cur.get(k, 0.0)))
    sec: Dict[str, List[str]] = {}
    for k in out:
        if meta[k].get("sector") and not meta[k].get("etf"):
            sec.setdefault(meta[k]["sector"], []).append(k)
    for s, ks in sec.items():
        held = sum(cur.get(k, 0.0) for k in ks)
        lim = max(cfg["max_sector"], held)
        tot = sum(out[k] for k in ks)
        up = sum(max(0.0, out[k] - cur.get(k, 0.0)) for k in ks)
        if tot > lim + 1e-12 and up > 0:
            f = max(0.0, 1 - (tot - lim) / up)
            for k in ks:
                inc = max(0.0, out[k] - cur.get(k, 0.0))
                out[k] = cur.get(k, 0.0) + inc * f if inc else out[k]
    s = sum(out.values())
    if s > 1.0 + 1e-12:
        out = {k: v / s for k, v in out.items()}
    return out


# --- the replay -------------------------------------------------------------------------------------------------------------------

def month_ends(index: pd.DatetimeIndex, a, b) -> List[pd.Timestamp]:
    s = pd.Series(index, index=index)
    s = s[(s >= pd.Timestamp(a)) & (s <= pd.Timestamp(b))]
    return [pd.Timestamp(x) for x in s.groupby([s.index.year, s.index.month]).last().values]


def _permutation(keys: List[str], meta: Dict[str, dict], rng: np.random.Generator) -> Dict[str, str]:
    """label -> real key, a random permutation inside each kind (stocks, ETFs)."""
    out = {}
    for kind in (False, True):
        ks = [k for k in keys if bool(meta[k].get("etf")) == kind]
        shuffled = list(rng.permutation(ks)) if ks else []
        out.update(dict(zip(ks, shuffled)))
    return out


def replay(decide: Callable, params: dict, data: dict, start, end, cfg: Optional[dict] = None, shuffle_seed: Optional[int] = None) -> dict:
    """Replay `decide` over [start, end]: first signal at the first month-end on or after `start`, last day `end`. `data`: px (adjusted closes, wide, ffilled), turnover (wide),
    meta {key: {symbol, etf, sector, tax}}, index (Series, the market the gauge reads), bench (Series, the benchmark total-return index), forecasts/sims/storylines (dicts)."""
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    px, to, meta = data["px"], data["turnover"], data["meta"]
    cal = px.index
    cal = cal[(cal <= pd.Timestamp(end))]
    signals = month_ends(cal, start, end)
    pos = {d: i for i, d in enumerate(cal)}
    trade_day = {d: cal[pos[d] + 1] for d in signals if pos[d] + 1 < len(cal)}
    by_trade = {v: k for k, v in trade_day.items()}
    if not by_trade:
        raise ValueError("the window holds no month-end with a next session")
    first = min(by_trade)
    book = Book(cfg["capital"], cfg)
    rng = np.random.default_rng(shuffle_seed) if shuffle_seed is not None else None
    cols = list(px.columns)
    cidx = {k: i for i, k in enumerate(cols)}
    pxv = px.to_numpy(float)
    rf = (1 + cfg["cash_rate"]) ** (1 / 252) - 1
    cnt = px.notna().cumsum()
    first_done, month_trade, month_key = False, 0.0, None
    values, dates, trades_log, failures = [], [], 0, 0
    for D in cal[cal >= first]:
        row = pxv[pos[D]]
        book.cash *= 1 + rf
        if D in by_trade:
            d = by_trade[D]
            mk = (D.year, D.month)
            if mk != month_key:
                month_key, month_trade = mk, 0.0
            try:
                w = _decide_at(decide, params, data, cfg, book, d, D, row, cidx, cnt, rng, shuffle_seed is not None)
            except Exception as e:                                           # a policy that raises holds its book for the month and is counted
                failures += 1
                w = None
                if failures > 3 and failures > 0.25 * len(signals):
                    raise RuntimeError(f"the policy failed on {failures} decisions; last: {type(e).__name__}: {e}")
            if w is not None:
                month_trade += _rebalance(book, w, meta, cfg, D, row, cidx, first_done, month_trade)
                first_done = True
                trades_log += 1
        v = book.cash + sum(book.qty(k) * float(row[cidx[k]]) for k in book.lots if not np.isnan(row[cidx[k]]))
        values.append(v)
        dates.append(D)
    s = pd.Series(values, index=dates)
    return {"value": s, "book": book, "decisions": trades_log, "failures": failures}


def _decide_at(decide, params, data, cfg, book, d, D, row, cidx, cnt, rng, shuffled) -> Dict[str, float]:
    px, to, meta = data["px"], data["turnover"], data["meta"]
    hist = px.loc[:d]
    n_hist = cnt.loc[d]
    last = hist.iloc[-1]
    med = to.loc[:d].tail(cfg["turn_window"]).median()
    stock_cols = [k for k in px.columns if not meta[k].get("etf")]
    ok = (n_hist[stock_cols] >= cfg["min_history"]) & med.reindex(stock_cols).notna() & last[stock_cols].notna()
    liquid = med.reindex(stock_cols)[ok].nlargest(cfg["n_liquid"]).index.tolist()
    etfs = [k for k in px.columns if meta[k].get("etf") and n_hist[k] >= cfg["min_history"] and not np.isnan(last[k])]
    held = [k for k in book.lots if book.qty(k) > 0]
    universe = list(dict.fromkeys(liquid + etfs))
    cols = list(dict.fromkeys(universe + held))
    V = book.cash + sum(book.qty(k) * float(px.at[d, k]) for k in held if not np.isnan(px.at[d, k]))
    cur = {k: book.qty(k) * float(px.at[d, k]) / V for k in held if not np.isnan(px.at[d, k])}
    perm = {k: k for k in cols}                                              # label (what the policy sees and names) -> the real security its weight lands on
    if shuffled:
        perm = _permutation(cols, meta, rng)
    prices = hist[cols].tail(cfg["history_rows"])
    turn = to.loc[:d, cols].tail(cfg["history_rows"])
    state = {"day": d.date(), "prices": prices, "turnover": turn, "weights": {l: cur[perm[l]] for l in cols if perm[l] in cur}, "value": V,
             "meta": {k: {"symbol": meta[k].get("symbol"), "etf": bool(meta[k].get("etf")), "sector": meta[k].get("sector")} for k in cols},
             "universe": list(universe), "index": data["index"].loc[:d].tail(cfg["history_rows"]), "target": None,
             "caps": {k: (cfg["max_etf"] if meta[k].get("etf") else cfg["max_stock"]) for k in cols}}
    w = decide(state, data.get("forecasts") or {}, data.get("sims") or {}, data.get("storylines") or {}, dict(params or {}))
    if not isinstance(w, dict):
        raise ValueError("decide must return a dict")
    out = {}
    for lbl, x in w.items():
        try:
            x = float(x)
        except (TypeError, ValueError):
            continue
        if lbl in perm and math.isfinite(x) and x > 0:
            out[perm[lbl]] = out.get(perm[lbl], 0.0) + x                   # the weight lands on the real security behind the label
    return out


def decision_now(decide: Callable, params: dict, data: dict, day, prev_weights: Optional[Dict[str, float]] = None, cfg: Optional[dict] = None) -> Dict[str, float]:
    """The target weights `decide` gives on `day` (the last row of the data it is handed), starting from `prev_weights` (its own shadow book). The same state the replay builds."""
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    px = data["px"]
    d = px.index[px.index <= pd.Timestamp(day)][-1]
    V = 1_000_000.0
    book = Book(V, cfg)
    for k, w in (prev_weights or {}).items():
        if k in px.columns and w > 0 and not np.isnan(px.at[d, k]):
            book.lots[k] = [[d.date(), w * V / float(px.at[d, k]), float(px.at[d, k])]]
            book.cash -= w * V
    cidx = {k: i for i, k in enumerate(px.columns)}
    return _decide_at(decide, params, data, cfg, book, d, d, px.loc[d].to_numpy(float), cidx, px.notna().cumsum(), None, False)


def _rebalance(book: Book, w: Dict[str, float], meta: dict, cfg: dict, D, row, cidx, first_done: bool, month_trade: float) -> float:
    held = [k for k in book.lots if book.qty(k) > 0]
    price = {k: float(row[cidx[k]]) for k in set(held) | set(w) if k in cidx and not np.isnan(row[cidx[k]])}
    V = book.cash + sum(book.qty(k) * price.get(k, 0.0) for k in held)
    cur = {k: book.qty(k) * price.get(k, 0.0) / V for k in held}
    w = clip_weights({k: v for k, v in w.items() if k in price}, meta, cfg, cur)
    sells, buys = [], []
    for k in sorted(set(held) | set(w)):
        if k not in price:
            continue
        diff = (w.get(k, 0.0) - cur.get(k, 0.0)) * V
        if diff < -cfg["min_trade"] * V or (w.get(k, 0.0) == 0.0 and cur.get(k, 0.0) > 0):
            sells.append((k, min(book.qty(k), -diff / price[k])))
        elif diff > cfg["min_trade"] * V:
            buys.append((k, diff))
    kind = lambda k: "etf" if meta[k].get("etf") else "equity"
    kept = []
    for k, q in sells:                                                       # the cost filter: a trim whose charges and tax are over the share is skipped (an exit is not)
        fee, tax, _ = book.sell_cost(k, q, price[k], D.date(), kind(k), meta[k].get("tax", "EQUITY"))
        exit_all = w.get(k, 0.0) == 0.0
        if not exit_all and (fee + tax) > cfg["max_cost_share"] * q * price[k]:
            continue
        kept.append((k, q))
    sells = kept
    total = sum(q * price[k] for k, q in sells) + sum(v for _, v in buys)
    if first_done and total > 0:
        cap = min(cfg["turnover_day"] * V, max(0.0, cfg["turnover_month"] * V - month_trade))
        if total > cap:
            f = cap / total
            sells = [(k, q * f) for k, q in sells]
            buys = [(k, v * f) for k, v in buys]
    traded = 0.0
    for k, q in sells:
        if q * price[k] >= cfg["min_trade_rupees"] or q >= book.qty(k) - 1e-9:
            traded += q * price[k]
            book.sell(k, q, price[k], D.date(), kind(k), meta[k].get("tax", "EQUITY"))
    for k, v in sorted(buys, key=lambda kv: -kv[1]):
        if v >= cfg["min_trade_rupees"]:
            traded += v
            book.buy(k, v, price[k], D.date(), kind(k))
    return traded


# --- the scorecard ----------------------------------------------------------------------------------------------------------------

def _cagr(end: float, start: float, n: int) -> float:
    return (end / start) ** (252.0 / max(n, 1)) - 1.0 if start > 0 and end > 0 else -1.0


def stats(v: pd.Series, cash_rate: float) -> dict:
    r = v.pct_change().dropna()
    ex = r - ((1 + cash_rate) ** (1 / 252) - 1)
    sd = float(ex.std())
    dd = v / v.cummax() - 1
    trough = dd.idxmin()
    peak_before = v.loc[:trough].idxmax()
    rec = v.loc[trough:][v.loc[trough:] >= v.loc[peak_before]]
    rec_days = float((rec.index[0] - trough).days) if len(rec) else -1.0
    return {"cagr": _cagr(float(v.iloc[-1]), float(v.iloc[0]), len(v)), "sharpe_daily": float(ex.mean() / sd) if sd > 0 else 0.0, "sharpe": float(ex.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0,
            "vol": float(r.std() * math.sqrt(252)), "max_drawdown": float(dd.min()), "recovery_days": rec_days, "n_obs": float(len(r)),
            "skew": float(r.skew()) if len(r) > 3 else 0.0, "kurt": float(r.kurt() + 3.0) if len(r) > 3 else 3.0}


def index_after_tax(bench: pd.Series, v: pd.Series, cfg: dict) -> dict:
    """The index held as an ETF over the policy's own days, after its charges and the tax of a buy-and-hold (S81, A50): the total-return index less the yearly ETF cost, bought on the first
    day (buy charge), sold on the last (sell charge, then the long-term tax above the exemption on the whole gain, as a buy-and-hold pays when it is finally sold). -> the path (a Series)
    and the figures. The policy side is liquidated the same way (`liquidation`), so both sides are measured as money in hand after tax."""
    b = bench.reindex(v.index).ffill().bfill().dropna()
    cap = float(cfg["capital"])
    if len(b) < 30:
        return {}
    buy, sell = float(cfg["charges"]["etf"]["buy"]), float(cfg["charges"]["etf"]["sell"])
    days = np.array([(d - b.index[0]).days for d in b.index], dtype=float)
    path = cap * (1 - buy) * (b / float(b.iloc[0])) * (1.0 - float(cfg["index_etf_cost"])) ** (days / 365.25)
    end = float(path.iloc[-1])
    fee = end * sell
    held = (b.index[-1] - b.index[0]).days
    gain = end - fee - cap
    tax = tax_of({"lt_eq" if held > 365 else "st_eq": gain})
    n = len(path)
    st = stats(path, cfg["cash_rate"])
    return {"path": path, "bench_cagr_liq": _cagr(end - fee - tax, cap, n), "bench_cagr_net": st["cagr"], "bench_max_drawdown_net": st["max_drawdown"], "index_tax_at_end": tax,
            "index_charges": cap * buy + fee, "index_etf_cost": float(cfg["index_etf_cost"]), "bench_end_after_tax": end - fee - tax}


def liquidation(book: Book, px_row: pd.Series, day, meta: dict) -> Tuple[float, float]:
    """(charges, tax) if the whole book were sold at `px_row` on `day`: the same FIFO lots and tax buckets, the tax on the sum of the gains with the year's set-off."""
    fee_tot, gains_tot = 0.0, {}
    for k in [k for k in book.lots if book.qty(k) > 1e-9]:
        p = float(px_row.get(k, float("nan")))
        if p != p:
            continue
        kind = "etf" if meta[k].get("etf") else "equity"
        fee, _, gains = book.sell_cost(k, book.qty(k), p, day, kind, meta[k].get("tax", "EQUITY"))
        fee_tot += fee
        for b, x in gains.items():
            gains_tot[b] = gains_tot.get(b, 0.0) + x
    before = book.gains.get(fin_year(day), {})
    after = dict(before)
    for b, x in gains_tot.items():
        after[b] = after.get(b, 0.0) + x
    return fee_tot, max(0.0, tax_of(after) - tax_of(before))


def score(run: dict, data: dict, cfg: dict) -> dict:
    """The scorecard row of one replay: after tax and charges (the value path already carries both), against the benchmark over the same days.
    S81 adds the money-in-hand figures of A50: `cagr_liq` (the policy sold out on the last day, charges and tax paid) against `bench_cagr_liq` (the index held as an ETF, the same), and the
    index's worst fall as an ETF (`bench_max_drawdown_net`). The old fields are unchanged."""
    cfg = {**DEFAULT_CFG, **cfg}
    v = run["value"]
    out = stats(v, cfg["cash_rate"])
    b = data["bench"].reindex(v.index).ffill().dropna()
    bs = stats(b, cfg["cash_rate"]) if len(b) > 30 else {"cagr": 0.0, "max_drawdown": 0.0, "sharpe": 0.0}
    years = max(len(v) / 252.0, 1e-9)
    out.update({"bench_cagr": bs["cagr"], "bench_max_drawdown": bs["max_drawdown"], "bench_sharpe": bs["sharpe"], "excess_cagr": out["cagr"] - bs["cagr"],
                "tax_paid": run["book"].tax, "charges": run["book"].charges, "turnover_per_year": run["book"].traded / years / float(v.mean()), "end_value": float(v.iloc[-1]),
                "decisions": float(run["decisions"]), "failures": float(run["failures"])})
    try:
        ix = index_after_tax(data["bench"], v, cfg)
        if ix:
            fee, tax = liquidation(run["book"], data["px"].loc[v.index[-1]], v.index[-1].date(), data["meta"])
            end = float(v.iloc[-1]) - fee - tax
            cl = _cagr(end, float(v.iloc[0]), len(v))
            out.update({"cagr_liq": cl, "policy_tax_at_end": tax, "policy_charges_at_end": fee, "end_after_tax": end, "bench_cagr_liq": ix["bench_cagr_liq"],
                        "bench_cagr_net": ix["bench_cagr_net"], "bench_max_drawdown_net": ix["bench_max_drawdown_net"], "index_tax_at_end": ix["index_tax_at_end"],
                        "index_charges": ix["index_charges"], "index_etf_cost": ix["index_etf_cost"], "bench_end_after_tax": ix["bench_end_after_tax"],
                        "excess_liq": cl - ix["bench_cagr_liq"]})
    except Exception as e:                                                     # the older fields stand; the two-dimension rule then says the figures are missing
        out["index_figures_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return out


def monte_carlo(v: pd.Series, n: int = 1000, horizon: int = 252, block: int = 21, seed: int = 80) -> dict:
    """Block-bootstrap the replay's own daily returns into `n` one-year paths: the spread of what this policy's returns could have produced (not a forecast)."""
    r = v.pct_change().dropna().to_numpy()
    if len(r) < horizon // 2:
        return {}
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(horizon / block))
    starts = rng.integers(0, len(r) - block, size=(n, nb))
    paths = np.concatenate([r[s[:, None] + np.arange(block)] for s in starts.T], axis=1)[:, :horizon]
    cum = np.cumprod(1 + paths, axis=1)
    worst = (cum / np.maximum.accumulate(cum, axis=1) - 1).min(axis=1)
    end = cum[:, -1] - 1
    return {"mc_1y_p5": float(np.percentile(end, 5)), "mc_1y_p50": float(np.percentile(end, 50)), "mc_1y_p95": float(np.percentile(end, 95)), "mc_worst_fall_p50": float(np.percentile(worst, 50)),
            "mc_worst_fall_p5": float(np.percentile(worst, 5)), "mc_prob_loss": float((end < 0).mean())}


def deflated_sharpe(sr_daily: float, n_obs: float, skew: float, kurt: float, trial_srs: List[float]) -> float:
    """Bailey and Lopez de Prado's deflated Sharpe ratio: the probability that the true Sharpe is above zero after the best of `len(trial_srs)` tried variants is picked (the
    expected maximum of that many unskilled trials is the bar). `trial_srs` are the daily Sharpe ratios of EVERY variant tried, this one included."""
    from scipy.stats import norm
    n_trials = max(1, len(trial_srs))
    g = 0.5772156649015329
    var = float(np.var(trial_srs, ddof=1)) if n_trials > 1 else 0.0
    sr0 = math.sqrt(var) * ((1 - g) * norm.ppf(1 - 1.0 / n_trials) + g * norm.ppf(1 - 1.0 / (n_trials * math.e))) if n_trials > 1 and var > 0 else 0.0
    denom = math.sqrt(max(1e-12, 1 - skew * sr_daily + (kurt - 1) / 4.0 * sr_daily ** 2))
    return float(norm.cdf((sr_daily - sr0) * math.sqrt(max(n_obs - 1, 1)) / denom))


def evaluate(decide: Callable, grid: List[dict], data: dict, start, end, cfg: Optional[dict] = None, n_shuffles: int = 20, n_mc: int = 1000, seed: int = 80) -> dict:
    """Every combination of a policy over the window: its scorecard, its shuffled-signal runs and its Monte Carlo. The deflated Sharpe is over ALL combinations tried here (the
    caller adds earlier trials of the session by passing `trial_srs` to `deflated_sharpe` again)."""
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    rows = []
    for p in grid:
        run = replay(decide, p, data, start, end, cfg)
        row = {"params": p, "score": score(run, data, cfg)}
        row["mc"] = monte_carlo(run["value"], n_mc, seed=seed)
        sh = []
        for i in range(n_shuffles):
            r = replay(decide, p, data, start, end, cfg, shuffle_seed=seed * 1000 + i)
            sh.append(stats(r["value"], cfg["cash_rate"]))
        if sh:
            real = row["score"]["sharpe_daily"]
            row["shuffled"] = {"n": float(len(sh)), "cagr_mean": float(np.mean([s["cagr"] for s in sh])), "cagr_p95": float(np.percentile([s["cagr"] for s in sh], 95)),
                               "sharpe_p95": float(np.percentile([s["sharpe_daily"] for s in sh], 95)), "beats_real_frac": float(np.mean([s["sharpe_daily"] >= real for s in sh]))}
        rows.append(row)
    srs = [r["score"]["sharpe_daily"] for r in rows]
    for r in rows:
        s = r["score"]
        s["dsr"] = deflated_sharpe(s["sharpe_daily"], s["n_obs"], s["skew"], s["kurt"], srs)
    return {"runs": rows, "n_trials": len(rows), "notes": ["adjusted closes: dividends are reinvested inside them, so dividend income and its tax are not modelled",
                                                           "charges are flat per-side rates; tax is the book's FIFO estimate (cess and surcharge not added)",
                                                           "sector labels are the current classification (static)", "the first deployment is exempt from the turnover caps"]}
