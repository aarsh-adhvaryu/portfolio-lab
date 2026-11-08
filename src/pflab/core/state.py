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


def build(con, day: date, root=None, index: Optional[pd.Series] = None, cfg: Optional[dict] = None) -> dict:
    """The state at the close of `day`."""
    from pflab import core
    from pflab.paper import allocation, book, cadence
    cfg = cfg or core.settings()
    h = book.holdings(con, day)
    rows = []
    for r in h["rows"]:
        buyable = (r["asset_class"] or "") in book.BUYABLE and r["price"] is not None
        rows.append({"isin": r["isin"], "symbol": r["symbol"], "sector": r["sector"], "asset_class": r["asset_class"], "qty": r["qty"], "price": r["price"],
                     "value": r["value"] or 0.0, "weight": r["weight"], "buyable": buyable,
                     "klass": allocation.class_of(r["asset_class"], r["name"], r["symbol"], r["isin"])})
    panel = closes_panel(con, [r["isin"] for r in rows if r["buyable"]], day, int(cfg["baseline"]["vol_window"]))
    act = allocation.active_target(con)
    return {"day": day, "value": h["value"], "cash": h["cash"], "bank": h.get("bank", 0.0), "rows": rows,
            "target": {"classes": act["classes"], "sectors": act["sectors"], "id": act["target_id"]} if act else None,
            "vol": volatilities(panel, day, int(cfg["baseline"]["vol_window"])), "gauge": fall_gauge(index, day, cfg["baseline"]),
            "breaker": cadence.breaker(con), "cfg": cfg}
