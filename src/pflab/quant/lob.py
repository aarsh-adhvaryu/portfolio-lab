"""Limit order book simulator (S41): a price-time priority matching engine and Hawkes-driven order flow.

Research and descriptions only: the engine matches simulated orders against each other; nothing here can reach
a broker (the system has no order path).

    Book       limit / market / cancel with price-time priority; prices in integer ticks; fills recorded
    walk       the average price a market order of a given size would get against a depth ladder, unchanged
    Flow       order-flow model: market buys and sells from a bivariate Hawkes process (S40), passive limit
               orders as Poisson arrivals placed a geometric number of ticks behind the opposite best, each resting
               order cancelled at a constant rate (a zero-intelligence model with clustered market orders)
    simulate   run the flow through a Book; one snapshot a second; returns snapshots, fills, market-order log
    measures   spread, depth, the mid's move after a market order by size, fill chance of a passive probe order
"""
from __future__ import annotations

import bisect
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from pflab.quant import hawkes as hk

BUY, SELL = 1, -1


@dataclass
class Order:
    oid: int
    side: int
    price: int
    qty: int
    owner: str
    t: float


@dataclass(frozen=True)
class Fill:
    t: float
    price: int
    qty: int
    aggressor: int              # side of the incoming order
    maker: int                  # resting order id
    taker: int                  # incoming order id (0 for a market order with no id)
    maker_owner: str
    taker_owner: str


class Book:
    def __init__(self):
        self.levels: Dict[int, Dict[int, Deque[Order]]] = {BUY: {}, SELL: {}}
        self.prices: Dict[int, List[int]] = {BUY: [], SELL: []}          # ascending
        self.orders: Dict[int, Order] = {}
        self.fills: List[Fill] = []
        self._next = 1

    # ---- state ----
    def best(self, side: int) -> Optional[int]:
        p = self.prices[side]
        return (p[-1] if side == BUY else p[0]) if p else None

    def mid(self) -> Optional[float]:
        b, a = self.best(BUY), self.best(SELL)
        return None if b is None or a is None else (a + b) / 2

    def spread(self) -> Optional[int]:
        b, a = self.best(BUY), self.best(SELL)
        return None if b is None or a is None else a - b

    def depth(self, side: int, n: int = 5) -> List[Tuple[int, int]]:
        ps = self.prices[side][::-1][:n] if side == BUY else self.prices[side][:n]
        return [(p, sum(o.qty for o in self.levels[side][p])) for p in ps]

    def resting(self) -> int:
        return len(self.orders)

    # ---- actions ----
    def _rest(self, o: Order) -> None:
        lv = self.levels[o.side]
        if o.price not in lv:
            lv[o.price] = deque()
            bisect.insort(self.prices[o.side], o.price)
        lv[o.price].append(o)
        self.orders[o.oid] = o

    def _drop_level(self, side: int, price: int) -> None:
        del self.levels[side][price]
        self.prices[side].pop(bisect.bisect_left(self.prices[side], price))

    def _match(self, side: int, qty: int, limit: Optional[int], taker: int, owner: str, t: float) -> int:
        """Fill against the opposite side while prices cross; returns the quantity left."""
        opp = -side
        while qty > 0:
            best = self.best(opp)
            if best is None or (limit is not None and (best > limit if side == BUY else best < limit)):
                break
            q = self.levels[opp][best]
            while qty > 0 and q:
                m = q[0]
                x = min(qty, m.qty)
                self.fills.append(Fill(t, best, x, side, m.oid, taker, m.owner, owner))
                m.qty -= x
                qty -= x
                if m.qty == 0:
                    q.popleft()
                    del self.orders[m.oid]
            if not q:
                self._drop_level(opp, best)
        return qty

    def limit(self, side: int, price: int, qty: int, owner: str = "", t: float = 0.0) -> Optional[int]:
        """Match what crosses, rest the remainder; returns the resting order id (None when fully filled)."""
        if qty <= 0:
            raise ValueError("quantity must be positive")
        oid = self._next
        self._next += 1
        left = self._match(side, qty, price, oid, owner, t)
        if left == 0:
            return None
        self._rest(Order(oid, side, price, left, owner, t))
        return oid

    def market(self, side: int, qty: int, owner: str = "", t: float = 0.0) -> int:
        """Immediate-or-cancel at any price; returns the quantity filled."""
        oid = self._next
        self._next += 1
        return qty - self._match(side, qty, None, oid, owner, t)

    def cancel(self, oid: int) -> int:
        o = self.orders.pop(oid, None)
        if o is None:
            return 0
        q = self.levels[o.side][o.price]
        q.remove(o)
        if not q:
            self._drop_level(o.side, o.price)
        return o.qty


def walk(ladder: Sequence[Tuple[float, float]], qty: float) -> Tuple[Optional[float], float]:
    """(average price, quantity filled) of a market order of `qty` against a depth ladder [(price, qty), ...],
    best first. The ladder is not changed."""
    got, cost = 0.0, 0.0
    for p, q in ladder:
        x = min(q, qty - got)
        got += x
        cost += x * p
        if got >= qty:
            break
    return (cost / got if got else None), got


@dataclass(frozen=True)
class Flow:
    market: hk.Bi = hk.Bi((0.05, 0.05), ((0.4, 0.1), (0.1, 0.4)), ((0.5, 0.5), (0.5, 0.5)))   # per second
    limit_rate: float = 0.5          # passive limit orders per second, each side
    cancel_rate: float = 0.01        # per resting order per second
    place_p: float = 0.3             # ticks behind the opposite best: Geometric(place_p), so >= 1 (never crosses)
    limit_size: float = 100.0        # mean order size (shares), geometric
    market_size: float = 150.0
    start_mid: int = 2000            # ticks
    start_depth: int = 300           # shares per level, 10 levels a side, at the start


@dataclass
class SimResult:
    snapshots: pd.DataFrame          # t, bid, ask, spread, mid, bid_depth5, ask_depth5
    fills: List[Fill]
    markets: pd.DataFrame            # t, side, qty, filled, mid_before, mid_after_1s, mid_after_10s
    probes: pd.DataFrame = field(default_factory=pd.DataFrame)


def simulate(flow: Flow, T: float, rng: np.random.Generator, probes: Sequence[Tuple[float, int, int]] = ()) -> SimResult:
    """Run `flow` for T seconds. `probes`: (time, side, ticks behind own best) passive orders of the median size
    whose fills are tracked (fill chance and time to fill)."""
    book = Book()
    for k in range(1, 11):
        book.limit(BUY, flow.start_mid - k, flow.start_depth, "init")
        book.limit(SELL, flow.start_mid + k, flow.start_depth, "init")
    mb, ms = hk.simulate_bi(flow.market, T, rng)
    mkt = sorted([(t, BUY) for t in mb] + [(t, SELL) for t in ms])
    probes = sorted(probes)
    probe_ids, probe_rows = {}, []
    snaps, mlog = [], []
    t, mi, pi, next_snap = 0.0, 0, 0, 0.0
    size = lambda mean: int(rng.geometric(1 / mean))

    def place(side):
        opp = book.best(-side)
        ref = opp if opp is not None else (book.best(side) + side if book.best(side) is not None else flow.start_mid)
        k = rng.geometric(flow.place_p)                         # >= 1 tick behind the opposite best
        return ref - side * k

    while True:
        rate = 2 * flow.limit_rate + flow.cancel_rate * book.resting()
        t_lc = t + rng.exponential(1 / rate)
        t_m = mkt[mi][0] if mi < len(mkt) else np.inf
        t_p = probes[pi][0] if pi < len(probes) else np.inf
        t_next = min(t_lc, t_m, t_p)
        while next_snap <= min(t_next, T):
            b, a = book.best(BUY), book.best(SELL)
            snaps.append((next_snap, b, a, book.spread(), book.mid(), sum(q for _, q in book.depth(BUY)),
                           sum(q for _, q in book.depth(SELL))))
            next_snap += 1.0
        if t_next > T:
            break
        t = t_next
        if t == t_p:
            _, side, behind = probes[pi]
            pi += 1
            own = book.best(side)
            if own is not None:
                oid = book.limit(side, own - side * behind, int(flow.limit_size), "probe", t)
                if oid is not None:
                    probe_ids[oid] = len(probe_rows)
                    probe_rows.append({"t": t, "side": side, "behind": behind, "filled_at": None})
        elif t == t_m:
            side = mkt[mi][1]
            mi += 1
            before = book.mid()
            q = size(flow.market_size)
            n0 = len(book.fills)
            got = book.market(side, q, "flow", t)
            for f in book.fills[n0:]:
                if f.maker in probe_ids and probe_rows[probe_ids[f.maker]]["filled_at"] is None and f.maker not in book.orders:
                    probe_rows[probe_ids[f.maker]]["filled_at"] = t
            mlog.append({"t": t, "side": side, "qty": q, "filled": got, "mid_before": before})
        else:
            u = rng.uniform() * rate
            if u < 2 * flow.limit_rate:
                side = BUY if u < flow.limit_rate else SELL
                book.limit(side, place(side), size(flow.limit_size), "flow", t)
            elif book.orders:
                ids = [o for o, x in book.orders.items() if x.owner != "probe"]
                if ids:
                    book.cancel(ids[int(rng.integers(len(ids)))])
    snap = pd.DataFrame(snaps, columns=["t", "bid", "ask", "spread", "mid", "bid_depth5", "ask_depth5"])
    m = pd.DataFrame(mlog, columns=["t", "side", "qty", "filled", "mid_before"])
    if len(m) and len(snap):
        mids = snap.set_index("t")["mid"].ffill()
        for lag in (1, 10):
            m[f"mid_after_{lag}s"] = mids.reindex(np.ceil(m["t"]) + lag - 1, method="ffill").to_numpy()
    return SimResult(snap, book.fills, m, pd.DataFrame(probe_rows))


def measures(r: SimResult, sizes: Sequence[Tuple[int, int]] = ((0, 100), (100, 300), (300, 10 ** 9)),
             horizon: float = 60.0) -> dict:
    """Spread and depth averages; mean signed mid move (ticks, in the order's direction) 10 s after a market order
    by size bucket; fill chance of probe orders within `horizon` seconds by distance behind the best."""
    s = r.snapshots.dropna()
    out = {"spread_mean": float(s["spread"].mean()), "spread_median": float(s["spread"].median()),
           "depth5_mean": float((s["bid_depth5"] + s["ask_depth5"]).mean() / 2), "market_orders": int(len(r.markets))}
    m = r.markets.dropna(subset=["mid_before", "mid_after_10s"])
    move = (m["mid_after_10s"] - m["mid_before"]) * m["side"]
    out["impact_10s"] = {f"{a}-{b}": float(move[(m["qty"] >= a) & (m["qty"] < b)].mean()) if ((m["qty"] >= a) & (m["qty"] < b)).any()
                         else None for a, b in sizes}
    if len(r.probes):
        p = r.probes.copy()
        p["hit"] = p["filled_at"].notna() & ((p["filled_at"] - p["t"]) <= horizon)
        out["fill_chance"] = p.groupby("behind")["hit"].mean().to_dict()
    return out
