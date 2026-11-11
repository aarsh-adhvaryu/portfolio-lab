"""The plug-in lens interface (S79b item 18D).

Any new indicator is a *lens*: a forecaster plug-in with its own protocol. A lens turns a close series into quantiles of the h-session return (`frame`), is made,
scored and Hedge-weighted in the ensemble tables exactly like the built-in forecasters, but runs in SHADOW: it is left out of the combined `hedge` forecast until
`admitted()` is true (at least MIN_LIVE live sessions of that market AND its live pinball loss with the lens in the combination beats the combination without it by
the learner's bar). Nobody adds a lens to the live combination by hand.

A lens module registers itself with `register(Lens(...))` (by name; again is a replace). Shapes:

    frame(con, market, close_series, horizon_sessions) -> DataFrame indexed like close_series, columns = fcast.protocol.LEVELS
        (quantiles of the h-session RETURN made at each date, point-in-time), or None when it cannot forecast.
        `close_series.name` is the subject's key when it is not the market's index.

What is written, per lens L, for the market's INDEX (live: source 'live', replay: 'replay' with `replay_ok`):
    forecasts_s79 / forecast_scores_s79   forecaster L (the lens's own quantiles) and `hedge+L` (the Hedge combination of the code forecasters AND L, weights below);
                                           `hedge_base` (the code forecasters only) whenever any lens is active; `hedge` = `hedge_base` until a lens is admitted
    forecaster_weights                    source '<source>+L': a Hedge over the code forecasters plus L, so L's weight is learned like any forecaster's (the plain
                                           'live' weights of the code forecasters are untouched)
    lens_admission                        every admission check, with its numbers
Admission: n live sessions of `hedge+L` and `hedge_base` >= MIN_LIVE, the Diebold-Mariano t of (pinball hedge_base - pinball hedge+L) at least the learner counter's
bar `t_needed(N)` with a positive mean. An admitted lens enters `hedge` as `hedge+L` (the first one) and, further ones, as a mix at their own Hedge weight.

The switch is `configs/s79b.toml [lens] on`; off, `active()` is empty and nothing runs."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from pflab.fcast import protocol as P

BASE = "hedge_base"
WITH_PREFIX = "hedge+"


@dataclass(frozen=True)
class Lens:
    name: str                       # forecaster name in the ensemble, e.g. "lens_wave"
    markets: tuple                  # ("IN",) ...
    protocol: str                   # repo-relative path of its pre-registration
    frame: Callable[[Any, str, "pd.Series", int], "Optional[pd.DataFrame]"]
    replay_ok: bool = True          # False: forward-only (e.g. model-read news tone)
    about: str = ""


REGISTRY: Dict[str, Lens] = {}
_BUILTIN: tuple = ()      # modules that provide a lens and a `register_lens()`; empty since A60 (the three shadow lenses were built on features whose studies failed). A lens that passes a registered study is named here.


def register(lens: Lens) -> Lens:
    """Add (or replace by name) a lens. A lens is named lens_<something> and never collides with a built-in forecaster."""
    if lens.name in P.FORECASTERS or lens.name == P.COMBINED or lens.name == BASE or not lens.name.startswith("lens_"):
        raise ValueError(f"{lens.name!r} is not a valid lens name (lens_<something>, not a built-in forecaster)")
    REGISTRY[lens.name] = lens
    return lens


def unregister(name: str) -> None:
    REGISTRY.pop(name, None)


def load_builtin() -> None:
    """Import the modules that provide lenses and call their `register_lens()` (each guarded: a missing or broken module never blocks the ensemble)."""
    import importlib
    for mod in _BUILTIN:
        try:
            m = importlib.import_module(mod)
        except Exception:
            continue
        fn = getattr(m, "register_lens", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass


_LOADED = {"done": False}


def settings() -> dict:
    try:
        from pflab import _toml, markets
        return dict((_toml.load(markets.CONFIGS / "s79b.toml").get("lens", {})) or {})
    except Exception:
        return {}


def is_on() -> bool:
    return bool(settings().get("on", True))


def active(market: Optional[str] = None) -> List[Lens]:
    """The lenses that run (switch on), optionally those covering one market, by name."""
    if not is_on():
        return []
    if not _LOADED["done"]:
        load_builtin()
        _LOADED["done"] = True
    return sorted((l for l in REGISTRY.values() if market is None or market in l.markets), key=lambda l: l.name)


def ext_names(market: str, lens_name: str) -> tuple:
    from pflab.fcast import forecasters as F
    return tuple(F.names_for(market, True)) + (lens_name,)


# --- the series a lens may run on ----------------------------------------------------------------------------------------------------------
REQUIRE_REAL_SERIES = True
_REAL: Dict[tuple, bool] = {}


def is_market_series(market: str, close: pd.Series) -> bool:
    """True when `close` is the market's own index series as held in the data folder (same dates, same level). Lenses read the real files (daily bars and any other input) beside the close they are given; on any other series (a synthetic one in a test, a different index) their inputs would not match it, so none runs. The check is
    cached per (market, first and last date, length)."""
    if not REQUIRE_REAL_SERIES:
        return True
    if close is None or len(close) == 0:
        return False
    k = (market, close.index[0], close.index[-1], len(close))
    if k not in _REAL:
        try:
            from pflab.fcast.run import load_series
            real = load_series(market)
            common = close.index.intersection(real.index)
            ok = len(common) >= 0.9 * len(close) and float(np.nanmedian(np.abs(real.loc[common].to_numpy() / close.loc[common].to_numpy() - 1.0))) < 0.02
        except Exception:
            ok = False
        _REAL[k] = bool(ok)
        if len(_REAL) > 64:
            _REAL.pop(next(iter(_REAL)))
    return _REAL[k]


# --- admission ----------------------------------------------------------------------------------------------------------------------
def with_name(lens_name: str) -> str:
    return WITH_PREFIX + lens_name


def live_sessions(con, name: str, market: str, horizon: int) -> int:
    """Live scored sessions of the lens's own forecasts for the market's index."""
    from pflab import markets
    try:
        r = con.execute("SELECT count(DISTINCT as_of) FROM forecast_scores_s79 WHERE forecaster=? AND market=? AND horizon_sessions=? AND source='live' AND subject=?",
                        [name, market, int(horizon), markets.get(market).index]).fetchone()
        return int(r[0] or 0)
    except Exception:
        return 0


def admission(con, name: str, market: str, horizon: int, log: bool = False, now: Optional[datetime] = None) -> dict:
    """Is the lens admitted for (market, horizon) and why: n live sessions, pinball with and without it, the t and the bar. Never raises."""
    out = {"lens": name, "market": market, "horizon": int(horizon), "n_live": 0, "min_live": P.MIN_LIVE, "admitted": False, "pinball_with": None,
           "pinball_without": None, "t": None, "bar": None, "reason": ""}
    try:
        lens = REGISTRY.get(name)
        if lens is None:
            out["reason"] = "not registered"
        elif not is_on():
            out["reason"] = "switch off"
        elif market not in lens.markets:
            out["reason"] = "market not covered"
        else:
            from pflab.fcast import score as S
            j = S.pairs(con, market, int(horizon), "live", forecaster=with_name(name), versus=BASE)
            out["n_live"] = n = int(len(j))
            if n < P.MIN_LIVE:
                out["reason"] = f"shadow: {n} of {P.MIN_LIVE} live sessions"
            else:
                from pflab.learner import counter
                bar = counter.t_needed(counter.n_tests(con))
                dm = S.dm_stat((j["b"] - j["a"]).to_numpy(), int(horizon))
                out.update(pinball_with=float(j["a"].mean()), pinball_without=float(j["b"].mean()), t=dm["t"], bar=float(bar))
                ok = bool(dm["t"] >= bar and dm["mean"] > 0)
                out["admitted"] = ok
                out["reason"] = "admitted: the combination with it beats the combination without it at the bar" if ok else \
                    "shadow: the combination with it does not beat the combination without it at the bar"
    except Exception as e:
        out["reason"] = f"shadow: could not be decided ({type(e).__name__})"
    if log:
        try:
            if now is None:
                now = datetime.now()
            as_of = con.execute("SELECT max(as_of) FROM forecasts_s79 WHERE market=? AND source='live'", [market]).fetchone()[0]
            if as_of is not None:
                con.execute("DELETE FROM lens_admission WHERE lens=? AND market=? AND horizon_sessions=? AND as_of=?", [name, market, int(horizon), as_of])
                con.execute("INSERT INTO lens_admission VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            [name, market, int(horizon), as_of, out["n_live"], out["pinball_with"], out["pinball_without"], out["t"], out["bar"], out["admitted"],
                             out["reason"], now])
        except Exception:
            pass
    return out


def admitted(con, name: str, market: str, horizon: int) -> bool:
    """True only when the lens is registered with its switch on, has >= MIN_LIVE live sessions in that market and horizon AND its live pinball loss with it in the
    combination beats the combination without it at the learner's bar. False on any doubt."""
    try:
        return bool(admission(con, name, market, horizon)["admitted"])
    except Exception:
        return False


# --- weights ---------------------------------------------------------------------------------------------------------------------------
def weight_source(source: str, lens_name: str) -> str:
    return f"{source}+{lens_name}"


def ext_weights(con, market: str, h: int, source: str, lens_name: str, names: tuple, upto: Optional[date] = None) -> Dict[str, float]:
    """The Hedge weights over the code forecasters and the lens in force: the latest stored for this lens and source on or before `upto` (a live lens starts from its
    replay weights), else uniform. Names with no stored weight take an equal share."""
    def latest(src):
        q = "SELECT forecaster, weight, as_of FROM forecaster_weights WHERE market=? AND source=? AND horizon_sessions=?"
        a: list = [market, src, int(h)]
        if upto is not None:
            q += " AND as_of<=?"
            a.append(upto)
        rows = con.execute(q + " ORDER BY as_of DESC", a).fetchall()
        if not rows:
            return {}
        top = rows[0][2]
        return {f: w for f, w, d in rows if d == top}
    got = latest(weight_source(source, lens_name)) or (latest(weight_source("replay", lens_name)) if source == "live" else {})
    fill = 1.0 / len(names)
    w = {n: (got.get(n) if got.get(n) is not None else fill) for n in names}
    s = sum(w.values())
    return {n: v / s for n, v in w.items()}


# --- live: forecasts ---------------------------------------------------------------------------------------------------------------------
def augment(con, market: str, close: pd.Series, h: int, s: date, built_q: Dict[str, Optional[dict]], w: Dict[str, float], hedge: Optional[dict],
            source: str = "live") -> Optional[dict]:
    """Lens forecasts for the market's index at the close of s, horizon h. `built_q` holds the code forecasters' quantiles, `hedge` their combination.
    Returns {"forecasts": {name: quantiles}, "hedge": the combined forecast to store as `hedge`, "meta": {...}} or None when no lens made a forecast."""
    from pflab.fcast import forecasters as F, weights as W
    ls = active(market)
    if not ls or not is_market_series(market, close):
        return None
    base_q = {n: v for n, v in built_q.items() if v is not None}
    fc: Dict[str, dict] = {}
    meta: Dict[str, Any] = {}
    adm: List[tuple] = []
    for lens in ls:
        try:
            fr = lens.frame(con, market, close, h)
            q = None if fr is None else F.last_row(fr)
        except Exception as e:
            meta[lens.name] = {"error": type(e).__name__}
            continue
        if q is None:
            continue
        names = ext_names(market, lens.name)
        wx = ext_weights(con, market, h, source, lens.name, names, upto=s)
        hx = W.combine({**base_q, lens.name: q}, wx)
        fc[lens.name] = q
        if hx is not None:
            fc[with_name(lens.name)] = hx
        a = admitted(con, lens.name, market, h)
        meta[lens.name] = {"weight": round(wx.get(lens.name, 0.0), 4), "admitted": a}
        if a and hx is not None:
            adm.append((lens.name, q, hx, wx.get(lens.name, 0.0)))
    if not fc and not meta:
        return None
    final = hedge
    for k, (nm, q, hx, wl) in enumerate(adm):
        if k == 0:
            final = hx
        elif final is not None:
            final = {l: (1.0 - wl) * final[l] + wl * q[l] for l in final}
    if hedge is not None:
        fc[BASE] = hedge
    return {"forecasts": fc, "hedge": final, "meta": {"lenses": meta, "admitted": [a[0] for a in adm]} if meta else {}}


def update_lens_weights(con, market: str, scored: pd.DataFrame, now: datetime, source: str = "live") -> int:
    """After scoring: one Hedge step per matured index forecast set for each active lens (the code forecasters and the lens), stored under source '<source>+<lens>'."""
    from pflab import markets
    from pflab.fcast import weights as W
    if scored is None or scored.empty:
        return 0
    idx = markets.get(market).index
    done = 0
    for lens in active(market):
        names = ext_names(market, lens.name)
        sub = scored[(scored["subject"] == idx) & (scored["forecaster"].isin(names + (P.BENCHMARK,)))]
        src = weight_source(source, lens.name)
        for (h, mat, as_of), g in sub.sort_values(["matures", "as_of"]).groupby(["horizon_sessions", "matures", "as_of"], sort=False):
            loss = dict(zip(g["forecaster"], g["pinball_mean"]))
            if P.BENCHMARK not in loss or lens.name not in loss:
                continue
            nl = loss[P.BENCHMARK]
            w = ext_weights(con, market, int(h), source, lens.name, names)
            vec = np.array([w[n] for n in names])
            lv = np.array([loss.get(n, nl) for n in names])
            new = W.hedge_step(vec, lv, nl, int(h))
            W.store(con, market, src, int(h), mat, dict(zip(names, new)), W.n_updates(con, market, int(h), src) + 1, now)
            done += 1
    return done


# --- replay -----------------------------------------------------------------------------------------------------------------------------
def replay_lenses(con, market: str, close: pd.Series, h: int, Q: Dict[str, np.ndarray], pb: Dict[str, np.ndarray], y: np.ndarray, i0: int, names_all: tuple,
                  dates: list, px: np.ndarray, now: datetime, write: bool, fc_rows: list, sc_rows: list, w_rows: list) -> dict:
    """Run every active lens with `replay_ok` over the replay's series (2012-2021 only: the caller has cut the series and refused the spent years). Adds rows to the
    caller's lists (same layout as the code forecasters') when `write`. Returns the board per lens: n, dates, pinball ratios to naive, the Hedge-with-lens gain."""
    from pflab import markets
    from pflab.fcast import replay as R, score as S
    idx = markets.get(market).index
    board: dict = {}
    n = len(close)
    if not is_market_series(market, close):
        return board
    for lens in active(market):
        if not lens.replay_ok:
            board[lens.name] = {"skipped": "forward-only lens (replay_ok = False)"}
            continue
        try:
            fr = lens.frame(con, market, close, h)
        except Exception as e:
            board[lens.name] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
            continue
        if fr is None:
            board[lens.name] = {"skipped": "the lens cannot forecast here (no data)"}
            continue
        Ql = np.sort(fr.reindex(close.index).to_numpy(float), axis=1)
        finite = np.isfinite(Ql).all(1)
        pbl = np.where(finite & np.isfinite(y), R._pinball_matrix(y, Ql).mean(1), np.nan)
        names = tuple(names_all) + (lens.name,)
        Qd = {nm: Q[nm] for nm in names_all}
        Qd[lens.name] = Ql
        pbd = {nm: pb[nm] for nm in names_all}
        pbd[lens.name] = pbl
        valid = np.isfinite(y)
        Wm, steps, updated = R._hedge_path(Qd, pbd, valid, h, i0, names)
        num, den = np.zeros((n, len(P.LEVELS))), np.zeros((n, 1))
        for j, nm in enumerate(names):
            ok = np.isfinite(Qd[nm]).all(1)[:, None]
            num += np.where(ok, Wm[:, [j]] * np.nan_to_num(Qd[nm]), 0.0)
            den += np.where(ok, Wm[:, [j]], 0.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            Qx = np.where(den > 0, num / den, np.nan)
        pbx = np.where(np.isfinite(Qx).all(1) & valid, R._pinball_matrix(y, Qx).mean(1), np.nan)
        cov80 = lambda A: ((A[:, S.I10] <= y) & (y <= A[:, S.I90])).astype(float)
        cov90 = lambda A: ((A[:, S.I05] <= y) & (y <= A[:, S.I95])).astype(float)
        c80l, c80x, c90l, c90x = cov80(Ql), cov80(Qx), cov90(Ql), cov90(Qx)
        ok = np.isfinite(pbl) & np.isfinite(pbx) & np.isfinite(pb[P.BENCHMARK]) & np.isfinite(pb[P.COMBINED])
        ok[:i0] = False
        if ok.any():
            bn = float(np.mean(pb[P.BENCHMARK][ok]))
            dm = S.dm_stat((pb[P.COMBINED] - pbx)[ok], h)
            board[lens.name] = {"n": int(ok.sum()), "from": str(dates[int(np.flatnonzero(ok)[0])]), "to": str(dates[int(np.flatnonzero(ok)[-1])]),
                                "lens_vs_naive": float(np.mean(pbl[ok]) / bn), "hedge_vs_naive": float(np.mean(pb[P.COMBINED][ok]) / bn),
                                "hedge_with_lens_vs_naive": float(np.mean(pbx[ok]) / bn), "lens_coverage_80": float(np.mean(c80l[ok])),
                                "hedge_with_lens_dm_t_vs_hedge": dm.get("t"), "hedge_with_lens_mean_gain": dm.get("mean"),
                                "final_lens_weight": float(Wm[-1, -1]), "note": "a development read: the replay is never evidence and never admits a lens"}
        else:
            board[lens.name] = {"n": 0, "note": "no origin where the lens and every code forecaster could forecast"}
        if write and ok.any():
            for t in np.flatnonzero(ok):
                mat = dates[t + h]
                for fname, A, pbv, c8, c9 in ((lens.name, Ql, pbl, c80l, c90l), (with_name(lens.name), Qx, pbx, c80x, c90x)):
                    row_q = np.sort(A[t])
                    qd = {str(float(l)): round(float(v), 8) for l, v in zip(P.LEVELS, row_q)}
                    fc_rows.append([None, market, "replay", dates[t], idx, None, h, fname, json.dumps(qd), float(px[t]), mat, json.dumps({}), now])
                    sc_rows.append([None, market, "replay", dates[t], mat, idx, h, fname, float(y[t]),
                                    json.dumps([round(float(v), 8) for v in R._pinball_matrix(y[t:t + 1], row_q[None, :])[0]]), float(pbv[t]),
                                    bool(c8[t]), bool(c9[t]), now])
            src = weight_source("replay", lens.name)
            for t in np.flatnonzero(updated):
                for j, nm in enumerate(names):
                    w_rows.append([market, src, h, nm, dates[t], float(Wm[t, j]), int(steps[t]), now])
    return board


# --- the tool's table ---------------------------------------------------------------------------------------------------------------------
def table(con, market: str = "IN") -> dict:
    """The registry with each lens's protocol, n live and replay sessions, state, weight and pinball against naive (index forecasts)."""
    from pflab import markets
    idx = markets.get(market).index
    rows = []
    if not _LOADED["done"]:
        load_builtin()
        _LOADED["done"] = True
    for lens in sorted(REGISTRY.values(), key=lambda l: l.name):
        e = {"lens": lens.name, "markets": list(lens.markets), "protocol": lens.protocol, "replay_ok": lens.replay_ok, "about": lens.about, "horizons": {}}
        for h in P.HORIZONS:
            d: dict = {}
            for src in ("live", "replay"):
                try:
                    r = con.execute("SELECT count(DISTINCT as_of), avg(pinball_mean) FROM forecast_scores_s79 WHERE forecaster=? AND market=? AND horizon_sessions=? "
                                    "AND source=? AND subject=?", [lens.name, market, h, src, idx]).fetchone()
                    nv = con.execute("SELECT avg(pinball_mean) FROM forecast_scores_s79 WHERE forecaster=? AND market=? AND horizon_sessions=? AND source=? AND subject=? "
                                     "AND as_of IN (SELECT as_of FROM forecast_scores_s79 WHERE forecaster=? AND market=? AND horizon_sessions=? AND source=? AND subject=?)",
                                     [P.BENCHMARK, market, h, src, idx, lens.name, market, h, src, idx]).fetchone()[0]
                except Exception:
                    r, nv = (0, None), None
                d[f"n_{src}"] = int(r[0] or 0)
                d[f"pinball_vs_naive_{src}"] = None if not r[1] or not nv else round(float(r[1]) / float(nv), 4)
            a = admission(con, lens.name, market, h) if market in lens.markets else {"admitted": False, "reason": "market not covered"}
            d["state"] = "admitted" if a["admitted"] else "shadow"
            d["reason"] = a["reason"]
            try:
                w = con.execute("SELECT weight FROM forecaster_weights WHERE forecaster=? AND market=? AND horizon_sessions=? AND source IN (?,?) ORDER BY as_of DESC, "
                                "source LIKE 'live+%' DESC LIMIT 1", [lens.name, market, h, weight_source("live", lens.name), weight_source("replay", lens.name)]).fetchone()
            except Exception:
                w = None
            d["weight"] = None if not w else round(float(w[0]), 4)
            e["horizons"][str(h)] = d
        rows.append(e)
    return {"market": market, "on": is_on(), "lenses": rows, "min_live_sessions": P.MIN_LIVE}
