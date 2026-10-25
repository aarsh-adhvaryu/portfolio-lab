"""Monte Carlo and the efficient frontier for the target mix (PLAN S36, amendment A4). Estimates, not forecasts.

Assets, monthly total returns since 2007-04 (joint, so they move together as they did):
    stocks   equal-weight Nifty 500 members of each month (point-in-time): the stand-in for 15-20 direct
             stocks (a real list adds stock-specific risk on top: see the stocks-vs-index study)
    n500     Nifty 500 TRI;  mom50  Nifty 500 Momentum 50 TRI (NSE back-calculated before its 2023 launch)
    gold     Gold BeES ETF (INF732E01102 to 2019-12-19, then INF204KB17I5), price change month to month
    debt     a constant DEBT_RATE a year (FD/liquid assumption); cash: CASH_RATE a year
Engines:
    block    12-month circular block bootstrap of the joint history (keeps crashes clustered: the main engine;
             circular so the first and last months of history are drawn as often as the rest, S43 audit)
    gbm      correlated geometric Brownian motion with the history's mean and covariance of log returns (the
             reference: thin tails, no clustering)
Portfolios are constant-mix (rebalanced monthly to the weights): a simplification of steering with new money.

Falls (S43 audit): a fall measured on month-end values misses falls that recover within the month (2020: Nifty
500 TRI -38% close to close, -29% month-end to month-end). With the daily history (`history_daily`) the chance of
a fall beyond the limit is also measured on every session ("any day"), same engines, 252-session blocks.
"""
from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from pflab import _duck
import numpy as np
import pandas as pd

ASSETS = ("stocks", "n500", "mom50", "gold", "debt", "cash")
DEBT_RATE, CASH_RATE = 0.065, 0.03
FALL_LIMIT = -0.35
BLOCK = 12
SESSIONS = 252                          # sessions a year; 21 a month


def _index(root: Path, key: str) -> pd.Series:
    s = _duck.sql(f"select date, close from '{root}/indices/{key}.parquet' order by date").df()
    return s.assign(date=pd.to_datetime(s["date"])).set_index("date")["close"]


def _gold(root: Path) -> pd.Series:
    px = _duck.sql(f"select date, isin, close from '{root}/panel/prices.parquet' "
                    f"where isin in ('INF732E01102', 'INF204KB17I5') order by date").df()
    px["date"] = pd.to_datetime(px["date"])
    r = px.groupby("isin", group_keys=False).apply(lambda g: g.set_index("date")["close"].pct_change())
    r = r.dropna().sort_index()
    r = r[~r.index.duplicated()]
    # the 1:100 unit split of 2019-12-19 is not adjusted in the panel (3,355 -> 33.55); gold never moves 50%
    # in a day, so such a day is a data break and earns zero
    r[r.abs() > 0.5] = 0.0
    return (1 + r).cumprod()


@functools.lru_cache(maxsize=2)
def _stock_returns(root: Path):
    """Daily total returns of every Nifty 500 member ever (NaN where it has no row) and the membership table."""
    mem = _duck.sql(f"select isin, from_date, coalesce(to_date, DATE '2099-01-01') to_date "
                     f"from '{root}/index_membership/NIFTY500.parquet'").df()
    mem["from_date"], mem["to_date"] = pd.to_datetime(mem["from_date"]), pd.to_datetime(mem["to_date"])
    isins = sorted(set(mem["isin"]))
    px = _duck.sql(f"select date, isin, close, adj_close, dividend from '{root}/panel/prices.parquet' "
                    f"where isin in ({','.join(repr(i) for i in isins)}) and date >= DATE '2006-12-01'").df()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["isin", "date"])
    px["r"] = px.groupby("isin")["adj_close"].pct_change().fillna(0.0)
    px["r"] = (1 + px["r"]) * (1 + (px["dividend"].fillna(0.0) / px["close"]).where(px["close"] > 0, 0.0)) - 1
    return px.pivot(index="date", columns="isin", values="r"), mem


def _live(mem: pd.DataFrame, start: pd.Timestamp, columns) -> List[str]:
    live = mem[(mem["from_date"] <= start) & (mem["to_date"] > start)]["isin"]
    return [c for c in live if c in columns]


def _equal_weight(root: Path) -> pd.Series:
    r, mem = _stock_returns(root)
    tri = (1 + r.fillna(0.0)).cumprod()
    m = tri.resample("ME").last()
    mr = m.pct_change()
    out = {}
    for d in mr.index[1:]:
        cols = _live(mem, d - pd.offsets.MonthEnd(1), mr.columns)
        out[d] = float(mr.loc[d, cols].dropna().mean()) if cols else np.nan
    return pd.Series(out)


def _equal_weight_daily(root: Path) -> pd.Series:
    """Equal weight of the members at the previous month-end, rebalanced daily (each session's mean return of
    the members that traded): the daily twin of `_equal_weight`, used only to measure falls on every session."""
    r, mem = _stock_returns(root)
    parts = []
    for per, block in r.groupby(r.index.to_period("M")):
        cols = _live(mem, per.start_time - pd.Timedelta(days=1), block.columns)
        if cols:
            parts.append(block[cols].mean(axis=1))
    return pd.concat(parts)


def history(root: Path) -> pd.DataFrame:
    """Joint monthly simple returns, one column per asset, months with every risky asset present."""
    me = lambda s: s.resample("ME").last().pct_change()
    df = pd.DataFrame({"stocks": _equal_weight(root), "n500": me(_index(root, "NIFTY500_TRI")),
                       "mom50": me(_index(root, "NIFTY500_MOMENTUM50_TRI")), "gold": me(_gold(root))}).dropna()
    df["debt"] = (1 + DEBT_RATE) ** (1 / 12) - 1
    df["cash"] = (1 + CASH_RATE) ** (1 / 12) - 1
    return df[list(ASSETS)]


def history_daily(root: Path) -> pd.DataFrame:
    """Joint daily simple returns on Nifty 500 sessions (levels carried over a day an asset did not trade),
    from the first session every risky asset has; debt and cash accrue per session."""
    idx = _index(root, "NIFTY500_TRI")
    lv = pd.DataFrame({"stocks": (1 + _equal_weight_daily(root)).cumprod(), "n500": idx,
                       "mom50": _index(root, "NIFTY500_MOMENTUM50_TRI"), "gold": _gold(root)})
    lv = lv.reindex(idx.index).ffill().dropna()
    df = lv.pct_change().iloc[1:]
    df["debt"] = (1 + DEBT_RATE) ** (1 / SESSIONS) - 1
    df["cash"] = (1 + CASH_RATE) ** (1 / SESSIONS) - 1
    return df[list(ASSETS)]


def block_index(T: int, steps: int, n: int, rng: np.random.Generator, block: int) -> np.ndarray:
    """(n, steps) row numbers: blocks of `block` consecutive rows from random starts, wrapping from the end of
    the history to its start (circular block bootstrap, Politis and Romano 1992: every row equally likely)."""
    k = steps // block + 1
    starts = rng.integers(0, T, size=(n, k))
    return ((starts[:, :, None] + np.arange(block)[None, None, :]) % T).reshape(n, -1)[:, :steps]


def block_paths(R: np.ndarray, months: int, n: int, rng: np.random.Generator, block: int = BLOCK) -> np.ndarray:
    return R[block_index(len(R), months, n, rng, block)]           # (n, months, assets)


def _p_fall(draw: Callable[[int], np.ndarray], n: int, chunk: int = 1000) -> float:
    hits = 0
    for s in range(0, n, chunk):
        hits += int(np.sum(max_dd(np.cumprod(1 + draw(min(chunk, n - s)), axis=1)) <= FALL_LIMIT))
    return hits / n


def fall_any_day_block(Rd: np.ndarray, w: np.ndarray, months: int, n: int, rng: np.random.Generator) -> float:
    """Chance of a fall beyond FALL_LIMIT on any session: circular block bootstrap of the daily history in
    one-year blocks, the mix rebalanced daily."""
    r = Rd @ w
    days = months * SESSIONS // 12
    return _p_fall(lambda m: r[block_index(len(r), days, m, rng, SESSIONS)], n)


def fall_any_day_gbm(R: np.ndarray, w: np.ndarray, months: int, n: int, rng: np.random.Generator) -> float:
    """The GBM reference on every session: the monthly log-return mean and covariance divided by 21."""
    L = np.log1p(R)
    risky = L.std(axis=0) > 1e-12
    per = 12 / SESSIONS
    mu, cov = L.mean(axis=0) * per, np.cov(L[:, risky].T) * per
    days = months * SESSIONS // 12

    def draw(m):
        out = np.tile(mu, (m, days, 1))
        out[:, :, risky] = rng.multivariate_normal(mu[risky], cov, size=(m, days))
        return np.expm1(out) @ w
    return _p_fall(draw, n)


def gbm_paths(R: np.ndarray, months: int, n: int, rng: np.random.Generator) -> np.ndarray:
    L = np.log1p(R)
    risky = L.std(axis=0) > 1e-12
    mu, cov = L.mean(axis=0), np.cov(L[:, risky].T)
    out = np.tile(mu, (n, months, 1))
    out[:, :, risky] = rng.multivariate_normal(mu[risky], cov, size=(n, months))
    return np.expm1(out)


def mix_values(paths: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Value of 1 rupee over the months, rebalanced monthly to `w` (constant mix)."""
    return np.cumprod(1 + paths @ w, axis=1)


def max_dd(v: np.ndarray) -> np.ndarray:
    v = np.concatenate([np.ones((v.shape[0], 1)), v], axis=1)
    return (v / np.maximum.accumulate(v, axis=1) - 1).min(axis=1)


def summary(v: np.ndarray, months: int) -> dict:
    dd = max_dd(v)
    out = {"median_cagr": float(np.median(v[:, -1]) ** (12 / months) - 1),
           "p_fall_beyond_limit": float(np.mean(dd <= FALL_LIMIT)), "median_worst_fall": float(np.median(dd)),
           "p_loss_at_end": float(np.mean(v[:, -1] < 1))}
    for y in (1, 3, 5):
        if 12 * y <= months:
            x = v[:, 12 * y - 1]
            out[f"y{y}"] = {"p5": float(np.percentile(x, 5)), "p50": float(np.median(x)), "p95": float(np.percentile(x, 95))}
    return out


def weights_of(mix: Dict[str, float]) -> np.ndarray:
    w = np.array([mix.get(a, 0.0) for a in ASSETS])
    if abs(w.sum() - 1) > 1e-9:
        raise ValueError(f"weights sum to {w.sum():.4f}")
    return w


def fund_names(con, targets) -> Dict[str, str]:
    """isin -> name (instrument master) for every ISIN the targets buy."""
    isins = [i for b in targets.buckets.values() for i, _ in b.buy]
    if not isins:
        return {}
    return dict(con.execute(f"SELECT isin, name FROM instruments WHERE isin IN ({','.join('?' * len(isins))})",
                            isins).fetchall())


def target_mix(targets, names: Optional[Dict[str, str]] = None) -> Dict[str, float]:
    """The investor's buckets as these assets: equity -> stocks; equity_fund split by its buy weights between n500
    and mom50 (a fund whose name says Momentum -> mom50, any other -> n500; `names`: isin -> fund name);
    gold; debt; cash. Weights renormalised to investable. Without names the split is refused rather than
    guessed from the order of the buy list (S43 audit)."""
    t = targets.buckets
    eqf = t.get("equity_fund")
    split = {"n500": 0.5, "mom50": 0.5}
    if eqf is not None and eqf.buy:
        missing = [i for i, _ in eqf.buy if not (names or {}).get(i)]
        if missing:
            raise ValueError(f"equity_fund buys {missing}: fund name unknown, cannot tell Nifty 500 from Momentum 50")
        mom = sum(w for i, w in eqf.buy if "momentum" in names[i].lower())
        split = {"n500": 1.0 - mom, "mom50": mom}
    mix = {"stocks": t["equity"].target if "equity" in t else 0.0,
           "n500": (eqf.target if eqf else 0) * split["n500"], "mom50": (eqf.target if eqf else 0) * split["mom50"],
           "gold": t["gold"].target if "gold" in t else 0.0, "debt": t["debt"].target if "debt" in t else 0.0,
           "cash": t["cash"].target if "cash" in t else 0.0}
    s = sum(mix.values())
    return {k: v / s for k, v in mix.items()}


def simulate(R: pd.DataFrame, mixes: Dict[str, Dict[str, float]], years: int = 5, n: int = 10_000,
             seed: int = 20261015, Rd: Optional[pd.DataFrame] = None) -> Dict[str, dict]:
    """Summaries per mix and engine. With the daily history `Rd`, each also carries
    `p_fall_beyond_limit_any_day` (the same chance measured on every session)."""
    months = 12 * years
    rng = np.random.default_rng(seed)
    X = R.values
    engines = {"block": block_paths(X, months, n, rng), "gbm": gbm_paths(X, months, n, rng)}
    out = {name: {eng: summary(mix_values(p, weights_of(mix)), months) for eng, p in engines.items()}
           for name, mix in mixes.items()}
    if Rd is not None:
        Xd = Rd[list(ASSETS)].values
        for name, mix in mixes.items():
            w = weights_of(mix)
            out[name]["block"]["p_fall_beyond_limit_any_day"] = fall_any_day_block(Xd, w, months, n, rng)
            out[name]["gbm"]["p_fall_beyond_limit_any_day"] = fall_any_day_gbm(X, w, months, n, rng)
    return out


def lump_vs_staged(R: pd.DataFrame, mix: Dict[str, float], months_staged: int = 10, horizon: int = 24,
                   n: int = 10_000, seed: int = 20261016) -> Dict[str, dict]:
    """One pot: all into `mix` at once, or 1/months_staged of it each month (the rest earning the debt rate
    meanwhile). Terminal value after `horizon` months, both engines."""
    rng = np.random.default_rng(seed)
    X = R.values
    w = weights_of(mix)
    d = (1 + DEBT_RATE) ** (1 / 12) - 1
    out = {}
    for eng, p in (("block", block_paths(X, horizon, n, rng)), ("gbm", gbm_paths(X, horizon, n, rng))):
        r = p @ w
        lump = np.prod(1 + r, axis=1)
        staged = np.zeros(n)
        for k in range(months_staged):
            waited = (1 + d) ** k
            staged += waited / months_staged * np.prod(1 + r[:, k:], axis=1)
        out[eng] = {"lump_median": float(np.median(lump)), "staged_median": float(np.median(staged)),
                    "p_staged_beats_lump": float(np.mean(staged > lump)),
                    "lump_p5": float(np.percentile(lump, 5)), "staged_p5": float(np.percentile(staged, 5))}
    return out


FRONTIER_ASSETS = ("stocks", "n500", "mom50", "gold", "debt")


def _worst_falls(X: np.ndarray, W: np.ndarray, chunk: int = 500) -> np.ndarray:
    """Worst peak-to-trough fall of each mix (rows of W) over the history X (rows = periods); the starting value
    counts as a peak, so a fall in the first period is seen (S43 audit)."""
    out = np.empty(len(W))
    for s in range(0, len(W), chunk):
        v = np.cumprod(1 + X @ W[s:s + chunk].T, axis=0)
        v = np.vstack([np.ones((1, v.shape[1])), v])
        out[s:s + chunk] = (v / np.maximum.accumulate(v, axis=0) - 1).min(axis=0)
    return out


def frontier(R: pd.DataFrame, n: int = 5000, seed: int = 20261017, Rd: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """`n` random mixes (Dirichlet) of the five investable assets: annual return and volatility from the
    joint history, and the worst fall each mix actually had over it (constant mix): at month-ends, and on any
    session when the daily history `Rd` is given (`worst_fall_any_day`)."""
    rng = np.random.default_rng(seed)
    X = R[list(FRONTIER_ASSETS)].values
    W = rng.dirichlet(np.ones(len(FRONTIER_ASSETS)), size=n)
    port = X @ W.T                                                     # (months, n)
    ann_ret = np.prod(1 + port, axis=0) ** (12 / len(X)) - 1
    vol = port.std(axis=0, ddof=1) * np.sqrt(12)
    df = pd.DataFrame(W, columns=list(FRONTIER_ASSETS))
    df["ret"], df["vol"], df["worst_fall"] = ann_ret, vol, _worst_falls(X, W)
    if Rd is not None:
        df["worst_fall_any_day"] = _worst_falls(Rd[list(FRONTIER_ASSETS)].values, W)
    df["sharpe"] = (df["ret"] - DEBT_RATE) / df["vol"]
    return df


def point(R: pd.DataFrame, mix: Dict[str, float], Rd: Optional[pd.DataFrame] = None) -> dict:
    """The same numbers for one named mix (cash folded into debt for the frontier map)."""
    m = {a: mix.get(a, 0.0) for a in FRONTIER_ASSETS}
    m["debt"] += mix.get("cash", 0.0)
    w = np.array([m[a] for a in FRONTIER_ASSETS])
    port = R[list(FRONTIER_ASSETS)].values @ w
    out = {"ret": float(np.prod(1 + port) ** (12 / len(port)) - 1), "vol": float(port.std(ddof=1) * np.sqrt(12)),
           "worst_fall": float(_worst_falls(R[list(FRONTIER_ASSETS)].values, w[None, :])[0]), **m}
    if Rd is not None:
        out["worst_fall_any_day"] = float(_worst_falls(Rd[list(FRONTIER_ASSETS)].values, w[None, :])[0])
    return out


def html(fr: pd.DataFrame, marks: Dict[str, dict], R: pd.DataFrame, path: Path) -> Path:
    """A self-contained interactive page (Plotly from cdnjs, pinned): 5,000 mixes coloured by worst fall."""
    pts = fr.round(4).to_dict("records")
    data = json.dumps({"pts": pts, "marks": marks, "months": len(R), "start": str(R.index[0].date()),
                       "end": str(R.index[-1].date())})
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Efficient frontier</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.35.2/plotly.min.js"></script>
<style>body{{font-family:system-ui,sans-serif;margin:16px;background:#fff;color:#111}}#c{{width:100%;height:75vh}}p{{max-width:900px}}</style>
</head><body><h2>Efficient frontier: 5,000 simulated portfolios</h2>
<p id="sub"></p><div id="c"></div>
<p>Each dot is one mix of direct stocks (equal-weight Nifty 500 stand-in), Nifty 500, Momentum 50, gold and debt.
Position: annual return and volatility over the history; colour: the worst fall that mix actually had, on any
day when daily history is available (month-end values miss falls that recover within the month).
Past joint history, not a forecast; Momentum 50 before 2023 is NSE's back-calculation.</p>
<script>
const D={data};
document.getElementById('sub').textContent=`History ${{D.start}} to ${{D.end}} (${{D.months}} months).`;
const wf=p=>(p.worst_fall_any_day ?? p.worst_fall);
const txt=p=>`stocks ${{(100*p.stocks).toFixed(0)}}% · N500 ${{(100*p.n500).toFixed(0)}}% · Mom50 ${{(100*p.mom50).toFixed(0)}}% · gold ${{(100*p.gold).toFixed(0)}}% · debt ${{(100*p.debt).toFixed(0)}}%<br>return ${{(100*p.ret).toFixed(1)}}% · vol ${{(100*p.vol).toFixed(1)}}% · worst fall ${{(100*wf(p)).toFixed(0)}}% (month-end ${{(100*p.worst_fall).toFixed(0)}}%)`;
const cloud={{x:D.pts.map(p=>100*p.vol),y:D.pts.map(p=>100*p.ret),mode:'markers',type:'scattergl',name:'5,000 mixes',
 text:D.pts.map(txt),hoverinfo:'text',marker:{{size:5,color:D.pts.map(p=>100*wf(p)),colorscale:'RdYlGn',cmin:-65,cmax:0,
 colorbar:{{title:'worst fall %'}}}}}};
const marks=Object.entries(D.marks).map(([k,p])=>({{x:[100*p.vol],y:[100*p.ret],mode:'markers+text',type:'scatter',name:k,
 text:[k],textposition:'top center',hovertext:[txt(p)],hoverinfo:'text',marker:{{size:14,symbol:'diamond',line:{{width:2,color:'#000'}}}}}}));
Plotly.newPlot('c',[cloud,...marks],{{xaxis:{{title:'volatility, % a year'}},yaxis:{{title:'return, % a year'}},hovermode:'closest',
 legend:{{orientation:'h'}}}},{{responsive:true}});
</script></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
