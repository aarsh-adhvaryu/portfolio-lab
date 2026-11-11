"""What the close loop sees (point in time: every row used is dated on or before `day`). Code only; no model, no network."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Optional

import numpy as np
import pandas as pd

FALLBACK_VOL = 0.30                                    # a name with too little history: the same stated, deliberately high number construct uses


def closes_panel(con, isins, day: date, window: int) -> pd.DataFrame:
    """Daily closes of `isins` up to `day` (columns = isin), about `window` sessions back."""
    isins = [i for i in isins if i]
    if not isins:
        return pd.DataFrame()
    ph = ",".join("?" for _ in isins)
    rows = con.execute(f"SELECT isin, date, close FROM prices WHERE isin IN ({ph}) AND date <= ? AND date >= ? AND close > 0",
                       list(isins) + [day, day - timedelta(days=int(window * 1.6) + 10)]).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["isin", "date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot_table(index="date", columns="isin", values="close", aggfunc="last").sort_index()


def volatilities(panel: pd.DataFrame, day: date, window: int) -> Dict[str, float]:
    """Annual volatility per name from the shrunk covariance of daily returns (Ledoit-Wolf, `construct/risk.py`); FALLBACK_VOL for a name without enough history."""
    from pflab.construct import risk
    out: Dict[str, float] = {}
    if panel is not None and panel.shape[1]:
        cov, _ = risk.shrunk_cov(risk.daily_returns(panel, day, window=window))
        for k in cov.columns:
            out[k] = float(np.sqrt(max(cov.loc[k, k], 1e-12)))
    return out


def fall_gauge(index: Optional[pd.Series], day: date, cfg: dict) -> dict:
    """The baseline's fall gauge: fires when the Nifty 500 is `gauge_drawdown` or more below its 252-session high AND below its moving average. A plain rule, not a
    forecast: the baseline needs no proven edge (the doc's rule 10 change); it is replaced only through the lab."""
    if index is None or not len(index):
        return {"fired": False, "why": "no index series"}
    s = index[index.index <= pd.Timestamp(day)]
    ma_n = int(cfg["gauge_below_ma"])
    if len(s) < ma_n:
        return {"fired": False, "why": "not enough index history"}
    last = float(s.iloc[-1])
    dd = last / float(s.tail(252).max()) - 1
    ma = float(s.tail(ma_n).mean())
    fired = dd <= -float(cfg["gauge_drawdown"]) and last < ma
    return {"fired": bool(fired), "drawdown": round(dd, 4), "below_ma": last < ma, "why": f"index {dd:+.1%} from its 252-session high, {'below' if last < ma else 'above'} its {ma_n}-session average"}


def build(con, day: date, root=None, index: Optional[pd.Series] = None, cfg: Optional[dict] = None, extra_isins=()) -> dict:
    """The state at the close of `day`. `extra_isins`: securities the book does not hold but the champion policy may want (they enter as rows with no quantity, so the rails see them)."""
    from pflab import core
    from pflab.core import policy, sleeves
    from pflab.paper import allocation, book, cadence
    cfg = cfg or core.settings()
    h = book.holdings(con, day)
    extra_isins = list(dict.fromkeys(list(extra_isins) + policy.universe(con, day, cfg) + _picks_universe(con, day)))      # S81: the core ETFs the active baseline may buy enter as rows with no quantity; S83: so do the picks not yet held
    rows = []
    for r in h["rows"]:
        buyable = (r["asset_class"] or "") in book.BUYABLE and r["price"] is not None
        rows.append({"isin": r["isin"], "symbol": r["symbol"], "sector": r["sector"], "asset_class": r["asset_class"], "qty": r["qty"], "price": r["price"],
                     "value": r["value"] or 0.0, "weight": r["weight"], "buyable": buyable,
                     "klass": allocation.class_of(r["asset_class"], r["name"], r["symbol"], r["isin"]), "sleeve": sleeves.sleeve_of(con, r["isin"])})
    held = {r["isin"] for r in rows}
    for isin in extra_isins:
        px = book.close_on(con, isin, day) if isin not in held else None
        if px is None:
            continue
        m = book.inst(con, isin)
        rows.append({"isin": isin, "symbol": m["symbol"] or isin, "sector": m["sector"], "asset_class": m["asset_class"], "qty": 0.0, "price": px[1], "value": 0.0, "weight": 0.0,
                     "buyable": (m["asset_class"] or "") in book.BUYABLE, "klass": allocation.class_of(m["asset_class"], m["name"], m["symbol"], isin),
                     "sleeve": sleeves.sleeve_of(con, isin)})
    panel = closes_panel(con, [r["isin"] for r in rows if r["buyable"]], day, int(cfg["baseline"]["vol_window"]))
    act = allocation.active_target(con)
    tgt = {"classes": act["classes"], "sectors": act["sectors"], "id": act["target_id"]} if act else None
    out = {"day": day, "value": h["value"], "cash": h["cash"], "bank": h.get("bank", 0.0), "rows": rows,
           "target": tgt, "sleeve_target": sleeves.target_shares(con, cfg, tgt),
           "vol": volatilities(panel, day, int(cfg["baseline"]["vol_window"])), "gauge": fall_gauge(index, day, cfg["baseline"]),
           "breaker": cadence.breaker(con), "cfg": cfg}
    try:                                                     # S83 L1: the picks' sizing (state["picks"]), merged into the baseline's targets before the rails (core/picks.py)
        from pflab.core import picks
        picks.attach(con, out, "IN")
    except Exception:
        out.pop("picks", None)
    from pflab.us import wholebook                       # S82 (A57): the whole book beside the rupee book: `whole_value`, `us_book_inr`; `value` stays the rupee book's (the weights are its own)
    return wholebook.attach(con, out, root)


def _picks_universe(con, day) -> list:
    """S83: the picked names the book does not hold yet (they enter as rows with no quantity); none when the picks are off or the table is not there."""
    try:
        from pflab.core import picks
        return picks.universe(con, day, "IN")
    except Exception:
        return []
