"""Market depth snapshots from Kite (S41): the calibration source for the order book simulator.

Kite's `quote()` (read-only, in the S4 allowlist) returns five price levels a side with quantities and order
counts. `record` polls it for a few instruments and appends one row per instrument per snapshot to
`data/kite_depth/{date}.parquet`. The investor runs `tools/kite_depth_record.py` during market hours when he wants
recordings; nothing schedules it. `impact` walks the recorded ladders to measure what an order of a given rupee
size would have paid over the mid (a measurement from real books, unlike the simulator's synthetic numbers).
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, List, Optional

import numpy as np
import pandas as pd

from pflab.data import data_dir
from pflab.quant import lob

LEVELS = 5


def rows_from_quote(payload: dict, ts: datetime) -> pd.DataFrame:
    rows = []
    for key, q in payload.items():
        d = q.get("depth") or {}
        r = {"ts": ts, "instrument": key, "last_price": q.get("last_price"), "volume": q.get("volume")}
        for side in ("buy", "sell"):
            lv = (d.get(side) or [])[:LEVELS]
            for i in range(LEVELS):
                x = lv[i] if i < len(lv) else {}
                r[f"{side}_px{i + 1}"] = x.get("price")
                r[f"{side}_qty{i + 1}"] = x.get("quantity")
                r[f"{side}_orders{i + 1}"] = x.get("orders")
        rows.append(r)
    return pd.DataFrame(rows)


def record(kite, instruments: List[str], minutes: float, interval: float = 5.0, root: Optional[Path] = None,
           now: Callable[[], datetime] = datetime.now, sleep: Callable[[float], None] = time.sleep,
           flush_every: int = 60) -> int:
    """Poll `kite.quote(instruments)` every `interval` seconds for `minutes`; returns snapshots written."""
    root = root or data_dir()
    out_dir = root / "kite_depth"
    out_dir.mkdir(parents=True, exist_ok=True)
    buf, n, end = [], 0, now().timestamp() + minutes * 60

    def flush():
        if not buf:
            return
        df = pd.concat(buf, ignore_index=True)
        p = out_dir / f"{df['ts'].iloc[0]:%Y-%m-%d}.parquet"
        if p.exists():
            df = pd.concat([pd.read_parquet(p), df], ignore_index=True)
        df.to_parquet(p, index=False)
        buf.clear()

    while now().timestamp() < end:
        buf.append(rows_from_quote(kite.quote(instruments), now()))
        n += 1
        if len(buf) >= flush_every:
            flush()
        sleep(interval)
    flush()
    return n


def load(instrument: str, root: Optional[Path] = None) -> pd.DataFrame:
    files = sorted(((root or data_dir()) / "kite_depth").glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    return df[df["instrument"] == instrument].reset_index(drop=True)


def ladder(row: pd.Series, side: str) -> list:
    return [(row[f"{side}_px{i}"], row[f"{side}_qty{i}"]) for i in range(1, LEVELS + 1)
            if pd.notna(row[f"{side}_px{i}"]) and row[f"{side}_qty{i}"]]


def impact(snaps: pd.DataFrame, amount: float, side: str = "buy") -> dict:
    """Cost over the mid, in basis points, of a market order worth `amount` rupees, walked against each recorded
    ladder (a buy takes the sell side). Snapshots whose five levels are too thin to fill it are counted apart."""
    bps, short = [], 0
    for _, r in snaps.iterrows():
        bid, ask = r["buy_px1"], r["sell_px1"]
        if not (pd.notna(bid) and pd.notna(ask) and bid > 0 and ask > bid):
            continue
        mid = (bid + ask) / 2
        lad = ladder(r, "sell" if side == "buy" else "buy")
        qty = amount / mid
        avg, got = lob.walk(lad, qty)
        if got < qty:
            short += 1
            continue
        bps.append((avg / mid - 1) * 1e4 * (1 if side == "buy" else -1))
    a = np.asarray(bps)
    return {"snapshots": int(len(a) + short), "too_thin": short,
            "median_bps": float(np.median(a)) if len(a) else None, "p90_bps": float(np.percentile(a, 90)) if len(a) else None,
            "half_spread_bps": float(np.median([(r["sell_px1"] - r["buy_px1"]) / (r["sell_px1"] + r["buy_px1"]) * 1e4
                                                for _, r in snaps.iterrows() if pd.notna(r["sell_px1"]) and pd.notna(r["buy_px1"])]))
            if len(snaps) else None}


def impact_note_fn(con, root: Optional[Path] = None) -> Callable[[str, float], Optional[str]]:
    """For the allocation agent's proposals: (isin, rupees) -> a measured impact note for an exchange-traded buy,
    'not measured' when no depth is recorded, None for mutual funds (bought at NAV: no order book)."""
    def note(isin: str, amount: float) -> Optional[str]:
        row = con.execute("SELECT symbol, asset_class FROM instruments WHERE isin = ?", [isin]).fetchone()
        if not row or row[1] == "mutual_fund" or not row[0]:
            return None
        snaps = load(f"NSE:{row[0]}", root)
        if snaps.empty:
            return f"market impact: not measured (no recorded depth for {row[0]})"
        r = impact(snaps, amount)
        if r["median_bps"] is None:
            return f"market impact: five recorded levels too thin for this size ({row[0]})"
        return (f"market impact ~ {r['median_bps']:.1f} bp, Rs {amount * r['median_bps'] / 1e4:,.0f} "
                f"(median over {r['snapshots']} recorded books; measured, not a forecast)")
    return note


def calibrate(snaps: pd.DataFrame, tick: float = 0.05, base: lob.Flow = lob.Flow()) -> lob.Flow:
    """A rough Flow from recordings: order size from quantity per order, depth per level, market-order rate from
    the traded volume between snapshots; Hawkes excitation kept from `base` (quotes do not show order times)."""
    q = [snaps[f"{s}_qty{i}"] for s in ("buy", "sell") for i in range(1, LEVELS + 1)]
    o = [snaps[f"{s}_orders{i}"] for s in ("buy", "sell") for i in range(1, LEVELS + 1)]
    qty, orders = pd.concat(q), pd.concat(o)
    size = float((qty / orders.where(orders > 0)).median())
    depth = int(qty.median())
    s = snaps.sort_values("ts")
    dv = s["volume"].diff().clip(lower=0)
    dt = s["ts"].diff().dt.total_seconds()
    vol_rate = float(dv.sum() / dt.sum()) if dt.sum() > 0 else 0.0                    # shares a second
    m_size = 1.5 * size
    a = np.asarray(base.market.alpha)
    each = vol_rate / m_size / 2                                                       # market orders a second, a side
    mu = each * (1 - a.sum(axis=1).mean())
    mid = float(((s["buy_px1"] + s["sell_px1"]) / 2).median())
    resting = float(sum(o).median()) * 2                                               # 5 levels seen; 10 simulated
    limit_rate = max((each * m_size / size) + base.cancel_rate * resting / 2, 0.01)
    return lob.Flow(market=lob.hk.Bi((mu, mu), base.market.alpha, base.market.beta), limit_rate=limit_rate,
                    cancel_rate=base.cancel_rate, place_p=base.place_p, limit_size=size, market_size=m_size,
                    start_mid=int(round(mid / tick)), start_depth=depth)
