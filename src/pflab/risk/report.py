"""Risk report from the PM store: the single code path behind `pflab pm risk` and the
risk page (S31), so a dashboard number can always be reproduced from the CLI (PLAN S15)."""
from __future__ import annotations

from datetime import date
from typing import Callable, Dict, Optional

import pandas as pd

from pflab.calc import returns as rt
from pflab.calc import valuation as val
from pflab.ledger import events as ev
from pflab.ledger.book import Ledger
from pflab.risk import exposure, stats

BenchLoader = Callable[[], Optional[pd.Series]]


def instruments_frame(con) -> pd.DataFrame:
    return con.execute("SELECT isin, asset_class, tax_class, sector, issuer, name, category, market "
                       "FROM instruments").df()


def nifty50_tri() -> Optional[pd.Series]:
    """Nifty 50 TRI close series from the data dir, or None if not collected."""
    try:
        from pflab.data import indices
        d = indices.load("NIFTY50_TRI")
        s = pd.Series(d["close"].to_numpy(float), index=pd.to_datetime(d["date"]))
        return s
    except Exception:
        return None


def build(con, asof: date, bench_loader: BenchLoader = nifty50_tri, window_sessions: int = 252,
          lookthrough: Optional[pd.DataFrame] = None, capm_root=None) -> Dict[str, object]:
    log = ev.load(con)
    led = Ledger.replay(log, upto=asof)
    pf = val.store_price_fn(con)
    v = val.value_ledger(led, pf, asof)
    inst = instruments_frame(con)
    ex = exposures = exposure.exposures(v, inst, lookthrough)
    stock_w = ex["stock"].set_index("isin")["weight"] if len(ex["stock"]) else pd.Series(dtype=float)
    out: Dict[str, object] = {"asof": asof, "total": v.total, "invested": v.invested, "cash": v.cash_total,
                              "exposure": ex, "concentration": stats.concentration(stock_w),
                              "unpriced": v.unpriced, "stale": v.stale}
    if capm_root is not None:                                    # S64: holdings-weighted beta and alpha (risk/capm.py)
        try:
            from pflab.risk import capm
            out["capm"] = capm.portfolio(con, capm_root, asof)
        except Exception as e:
            out["capm"] = {"beta": None, "note": f"not computed: {type(e).__name__}"}
    # NAV series over the last `window_sessions` price dates
    sessions = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM prices WHERE date <= ? ORDER BY date DESC LIMIT ?", [asof, window_sessions]).fetchall()]
    sessions = sorted(sessions)
    first_event = min((e.date for e in log.raw()), default=None)
    sessions = [d for d in sessions if first_event is not None and d >= first_event]
    if len(sessions) >= 2:
        values, flows = rt.value_series(log, pf, sessions)
        values = values[values > 0]
        if len(values) >= 2:
            nav = rt.twr(values, flows.reindex(values.index).fillna(0.0))
            b = bench_loader() if bench_loader else None
            out["nav_stats"] = stats.summary(nav, b)
            out["nav"] = nav
    return out


def render(rep: Dict[str, object]) -> str:
    lines = [f"Risk as of {rep['asof']}: total Rs {rep['total']:,.2f} "
             f"(invested {rep['invested']:,.2f}, cash {rep['cash']:,.2f})"]
    ex = rep["exposure"]
    for key, title in (("bucket", "By bucket"), ("sector", "By sector"), ("stock", "By stock")):
        lines.append(title + ":")
        for r in ex[key].head(10).itertuples():
            lines.append(f"  {getattr(r, key) if key != 'stock' else r.isin:<40} {r.weight:7.2%}")
    c = rep["concentration"]
    lines.append(f"Concentration: HHI {c['hhi']:.4f}, effective N {c['effective_n']:.1f}, "
                 f"top1 {c['top1']:.2%}, top5 {c['top5']:.2%} ({c['n']} holdings)")
    cp = rep.get("capm")
    if cp and cp.get("beta") is not None:
        lines.append(f"CAPM (direct stocks, Nifty 500 TRI, last 60 months): beta {cp['beta']:.2f}, alpha "
                     f"{cp['alpha_ann'] * 100:+.1f}% a year over {cp['names']} names"
                     + (f" ({len(cp['unfit'])} without 36 months count as beta 1)" if cp.get("unfit") else "")
                     + "; a description, not a forecast")
    ns = rep.get("nav_stats")
    if ns:
        b = ns.get("beta")
        lines.append(f"NAV: vol {ns['vol_annual']:.2%}, max drawdown {ns['max_drawdown']:.2%}, "
                     f"beta vs Nifty 50 TRI {'n/a' if b is None or b != b else f'{b:.2f}'} ({ns['obs']} daily obs)")
    if rep["unpriced"]:
        lines.append(f"UNPRICED (not in any weight): {[u[1] for u in rep['unpriced']]}")
    if rep["stale"]:
        lines.append(f"Stale prices: {rep['stale']}")
    return "\n".join(lines)
