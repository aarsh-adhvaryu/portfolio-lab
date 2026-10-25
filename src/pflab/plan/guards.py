"""Guards before any buy, and the alerts they raise (PLAN S35).

For every name on the investor's stock list (PFLAB_PM_DIR/stock_list.toml):
    surveillance  NSE ASM/GSM/ESM/IBC status from the latest daily snapshot (data.nse_surveillance)
    safety        the validated Fsafe tests on filed BSE results (plan.safety); results are cached in the PM
                  store (`quarterly_results`) and pulled again only when a newer quarter should be filed
verdict: block (surveillance block) > fail (a safety test failed) > unknown (data gap: never bought
automatically) > caution (surveillance caution) > ok.

Alerts go to the S9 outbox (sent once Telegram is configured; `pflab pm alerts` shows them meanwhile), each
with a dedup key so a state is reported once: a guard verdict change, the market-wide dip rule switching on
(Nifty 500 TRI 10% or more below its 1-year high), and fixed deposits maturing within 45 days or set to renew.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from pflab import _toml
from pflab.data import nse_surveillance as surv
from pflab.fundamentals import pit
from pflab.plan import safety

ORDER = {"block": 0, "fail": 1, "unknown": 2, "caution": 3, "ok": 4}
DIP = -0.10


@dataclass
class Guard:
    symbol: str
    isin: str
    verdict: str
    surveillance: str
    safety_ok: Optional[bool]
    reasons: List[str] = field(default_factory=list)


def stock_list(path: Optional[Path] = None) -> List[dict]:
    from pflab.pm import store
    p = path or (store.pm_dir() / "stock_list.toml")
    return _toml.load(p).get("stocks", []) if p.exists() else []


def _retry(f, *args):
    for attempt in range(3):
        try:
            return f(*args)
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None


def quarters(con, scrip: str, asof: date, fetch: Callable = pit.fetch_quarters, n: int = 9,
             filed: Optional[Callable] = None, filed_cons: Optional[Callable] = None) -> pd.DataFrame:
    """Filed standalone quarters for `scrip`: cached in the store, topped up from BSE when the newest expected
    quarter is missing (a quarter is expected 60 days after it ends). Quarters BSE's template lacks (NBFCs, banks,
    recent listings) come from the integrated XBRL filings (`filed`), dated by their filing time. Consolidated
    integrated filings (`filed_cons`) are kept beside them (safety amendment 2): topped up with the standalone ones,
    and re-tried while a company that files them lags. With the live template fetch both default to
    `integrated.fetch_quarters`; with an injected fetch (tests) nothing unless given."""
    from pflab.fundamentals import valuation as val
    want = pit.latest_qtr_id(asof - timedelta(days=60))
    expected = val.quarter_end(want)
    current = lambda d: bool(len(d)) and max(d["quarter_end"]) >= expected      # noqa: E731
    have, cons = pit.load(con, scrip), pit.load(con, scrip, "consolidated")
    if current(have) and (cons.empty or current(cons)):
        return have
    if fetch is pit.fetch_quarters:
        from functools import partial

        from pflab.fundamentals import integrated
        filed = filed or integrated.fetch_quarters
        filed_cons = filed_cons or partial(integrated.fetch_quarters, basis="Consolidated")
    window = [val.quarter_end(k) for k in range(want - n + 1, want + 2)]
    if not current(have):
        q = _retry(fetch, scrip, list(range(want - n + 1, want + 1)))
        if q is not None and not q.empty:
            pit.save(con, pit.date_quarters(q, first_seen=asof), "bse_live")
        if filed is not None:
            got = set(pit.load(con, scrip)["quarter_end"])
            missing = [e for e in window if e not in got]
            f = _retry(filed, scrip, missing) if missing else None
            if f is not None and not f.empty:
                pit.save(con, f[f["usable_from"] <= asof], "bse_filing")
    if filed_cons is not None:
        missing = [e for e in window if e not in set(cons["quarter_end"])]
        f = _retry(filed_cons, scrip, missing) if missing else None
        if f is not None and not f.empty:
            pit.save(con, f[f["usable_from"] <= asof], "bse_filing", basis="consolidated")
    return pit.load(con, scrip)


def check_all(con, asof: date, stocks: List[dict], fetch: Callable = pit.fetch_quarters,
              snap: Optional[pd.DataFrame] = None, drawdown_fn: Callable = safety.drawdown) -> List[Guard]:
    snap = surv.latest(asof) if snap is None else snap
    sectors = dict(con.execute("SELECT isin, sector FROM instruments").fetchall()) if stocks else {}
    out = []
    for s in stocks:
        st = surv.status(s["isin"], snap)
        q, basis = pd.DataFrame(), "standalone"
        if s.get("scrip"):
            q, basis = pit.choose(quarters(con, s["scrip"], asof, fetch), pit.load(con, s["scrip"], "consolidated"))
        c = safety.evaluate(s["isin"], s["symbol"], q, drawdown_fn(s["isin"], asof),
                            financial=safety.is_financial(sectors.get(s["isin"])), basis=basis)
        reasons = ([f"surveillance: {st['reason']}"] if st["verdict"] in ("block", "caution", "unknown") else []) + c.reasons
        unknown = not c.ok and all("unknown" in r for r in c.reasons)
        if st["verdict"] == "block":
            v = "block"
        elif not c.ok and not unknown:
            v = "fail"
        elif unknown or st["verdict"] == "unknown":
            v = "unknown"
        elif st["verdict"] == "caution":
            v = "caution"
        else:
            v = "ok"
        out.append(Guard(s["symbol"], s["isin"], v, st["verdict"], c.ok if not unknown else None, reasons))
    return sorted(out, key=lambda g: (ORDER[g.verdict], g.symbol))


def market_dip(asof: date, root=None) -> Dict[str, object]:
    from pflab.data import indices
    df = indices.load("NIFTY500_TRI", root)
    s = df.assign(date=pd.to_datetime(df["date"])).set_index("date")["close"].sort_index()
    s = s[(s.index <= pd.Timestamp(asof)) & (s.index > pd.Timestamp(asof) - pd.Timedelta(days=366))]
    dd = float(s.iloc[-1] / s.max() - 1)
    return {"date": s.index[-1].date(), "drawdown": dd, "active": dd <= DIP}


CLUSTER_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "hawkes_market.toml"


def _state(chance: float, c: dict) -> str:
    return "high" if chance >= c["t2"] else ("elevated" if chance >= c["t1"] else "calm")


def market_cluster(asof: date, root=None, config: Path = CLUSTER_CONFIG, lookback: int = 5) -> Optional[Dict[str, object]]:
    """Market state from clustering of big falls (S40, amendment 1): the chance of another Nifty 500 TRI session
    of -2% or worse within 10 sessions, from the frozen 2005-2019 Hawkes fit; calm / elevated / high by the
    registered thresholds. `changed_on`: the session (within `lookback`) where the state last changed, if any.
    None when no frozen fit exists. ESTIMATES."""
    if not config.exists():
        return None
    import numpy as np
    from pflab.data import indices
    from pflab.quant import hawkes as hk
    c = _toml.load(config)["market"]
    df = indices.load("NIFTY500_TRI", root)
    s = df.assign(date=pd.to_datetime(df["date"])).set_index("date")["close"].sort_index()
    r = s[s.index <= pd.Timestamp(asof)].pct_change().dropna()
    ev = np.flatnonzero((r <= c["threshold"]).to_numpy()) + 0.5      # mid-session, as fitted (uniform placement)
    p = hk.Uni(c["mu"], c["alpha"], c["beta"])
    h = int(c["horizon"])
    hist = [(r.index[k].date(), hk.chance_within(p, ev, float(k + 1), h)) for k in range(max(len(r) - lookback - 1, 0), len(r))]
    states = [_state(x, c) for _, x in hist]
    changed = next((hist[k][0] for k in range(len(hist) - 1, 0, -1) if states[k] != states[k - 1]), None)
    prev = next((states[k - 1] for k in range(len(hist) - 1, 0, -1) if states[k] != states[k - 1]), None)
    last = r.index[int(ev[-1])].date() if len(ev) else None
    return {"date": hist[-1][0], "chance": hist[-1][1], "state": states[-1], "changed_on": changed, "previous": prev,
            "horizon": h, "last_fall": last, "threshold": c["threshold"],
            "normal": float(1 - np.exp(-c["poisson_rate"] * h)), "vol_chance": vol_chance(r)}


VOL_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "market_state.toml"


def vol_chance(r: pd.Series, config: Path = VOL_CONFIG) -> Optional[float]:
    """S51 amendment 3 (The investor 2026-10-20): the volatility-based chance of a -2% fall within 10 sessions, shown beside
    the Hawkes state as information (it ranks fall risk better across ten markets; Hawkes stays the state because it
    warns before more follow-on falls since 2020). Frozen logistic map of ln EWMA(r^2), fitted on 2005-2014."""
    if not config.exists() or len(r) < 22:
        return None
    import numpy as np
    from pflab.quant import vol_study as vs
    c = _toml.load(config)["volatility"]
    ew = vs.ewma(r.to_numpy(), lam=float(c["lam"]), warm=int(c["warm"]))[-1]
    return float(1 / (1 + np.exp(-(c["a"] + c["b"] * np.log(max(ew, vs.FLOOR))))))


PLAN_NOTE = "Your plan does not change: regular monthly tranches continue"


def cluster_text(cl: Dict[str, object], dip: Optional[Dict[str, object]] = None) -> str:
    """One plain message: the market state, what it means, and what the plan does (dip rule unchanged: the
    wait-for-calm test failed, docs/research/hawkes_results.md)."""
    what = {"calm": "big falls are not clustering", "elevated": "big falls are clustering",
            "high": "big falls are clustering strongly (crash-like)"}[cl["state"]]
    txt = (f"Market state {cl['state'].upper()} on {cl['date']}" + (f" (was {cl['previous']})" if cl.get("previous") else "")
           + f": {what}. Chance of another {abs(cl['threshold']):.0%} fall of the Nifty 500 within {cl['horizon']} "
           f"sessions: {cl['chance']:.0%} (normal about {cl['normal']:.0%})"
           + (f"; from recent volatility {cl['vol_chance']:.0%}" if cl.get("vol_chance") is not None else "")
           + (f"; last such fall {cl['last_fall']}" if cl.get("last_fall") else "") + ". ")
    if dip is not None:
        txt += (f"Nifty 500 is {abs(dip['drawdown']):.1%} below its 1-year high: dip rule "
                + ("ACTIVE, the extra quarter-tranche into list names passing every guard is allowed. " if dip["active"]
                   else "off. "))
    return txt + PLAN_NOTE + ". ESTIMATE from a model of past falls, not a forecast of prices."


def queue_alerts(con, asof: date, guards: List[Guard], dip: Dict[str, object], fd_warnings: List[str],
                 now: Optional[datetime] = None, cluster: Optional[Dict[str, object]] = None) -> int:
    from pflab.service import telegram as tgm
    n = 0
    for g in guards:
        if g.verdict in ("block", "fail", "caution"):
            txt = f"Guard {g.verdict.upper()}: {g.symbol}: " + "; ".join(g.reasons)
            n += bool(tgm.enqueue(con, txt, "guard", dedup_key=f"guard:{g.isin}:{g.verdict}:{'|'.join(g.reasons)}", now=now))
    if dip["active"]:
        wk = dip["date"].isocalendar()
        n += bool(tgm.enqueue(con, f"Market-wide dip: Nifty 500 is {dip['drawdown']:.1%} below its 1-year high "
                                   f"({dip['date']}). The dip rule allows one extra quarter-tranche into list names "
                                   "that pass every guard.", "dip", dedup_key=f"dip:{wk[0]}-W{wk[1]}", now=now))
    for w in fd_warnings:
        n += bool(tgm.enqueue(con, w, "fd", dedup_key=f"fd:{w}", now=now))
    if cluster and cluster["changed_on"]:                       # one message per change of state, never repeats
        n += bool(tgm.enqueue(con, cluster_text(cluster, dip), "market_state",
                              dedup_key=f"state:{cluster['changed_on']}:{cluster['state']}", now=now))
    return n


def render(guards: List[Guard], dip: Dict[str, object], cluster: Optional[Dict[str, object]] = None) -> str:
    lines = [f"Guards on {len(guards)} list names; market: Nifty 500 {dip['drawdown']:.1%} from its 1-year high "
             f"on {dip['date']} (dip rule {'ACTIVE' if dip['active'] else 'off'})"]
    if cluster:
        lines.append(f"  market state {cluster['state'].upper()}: chance of another {abs(cluster['threshold']):.0%} fall "
                     f"within {cluster['horizon']} sessions {cluster['chance']:.0%} (normal about {cluster['normal']:.0%}"
                     + (f"; from recent volatility {cluster['vol_chance']:.0%}" if cluster.get("vol_chance") is not None
                        else "") + "; ESTIMATE). Regular tranches unchanged.")
    for g in guards:
        lines.append(f"  {g.verdict.upper():<8}{g.symbol:<12}" + ("; ".join(g.reasons) if g.reasons else "all checks pass"))
    return "\n".join(lines)
