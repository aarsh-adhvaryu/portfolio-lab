"""Predict, score, correct: the daily loop (S79 item 8), by code only.

    post_close(rt_or_con, market, session_date)   after a session's close: refresh the overnight forecast of the session just closed (its driver, the US close,
                                                   is known by the open), score what matured, update the Hedge weights, make the forecasts for the
                                                   next sessions (1, 5, 20), make the fall risk
    catch_up(rt_or_con, market, upto_date)        post_close for EACH missed session in order (score in order, point in time); idempotent

A forecast made at session s with horizon h matures at `markets.get(market).session_after(s, h)`. Forecasts exist for the market's index and for held and
listed names; the Hedge weights come from the index and are shared. Everything written here is source = 'live'.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Optional

import numpy as np
import pandas as pd

from pflab import markets
from pflab.fcast import fall_risk, forecasters as F, protocol as P, score as S, weights as W

SOURCE = "live"
MIN_HISTORY = P.SIGMA_MIN + 5


# --- the data ---------------------------------------------------------------------------------------------------------------------------
def load_series(market: str, root: Optional[Path] = None) -> pd.Series:
    """The market's index closes (IN: NIFTY 50 price index; US: S&P 500 price index), a Series on a DatetimeIndex."""
    from pflab.data import data_dir, indices
    root = Path(root) if root else data_dir()
    if market == "IN":
        df = indices.load("NIFTY50_PRICE", root)
    elif market == "US":
        df = pd.read_parquet(root / "global" / "US_SP500.parquet")
    else:
        raise ValueError(f"no index series for market {market!r}")
    s = pd.Series(df["close"].to_numpy(float), index=pd.to_datetime(df["date"]).dt.normalize())
    return s[~s.index.duplicated(keep="last")].sort_index().dropna()


def load_us(root: Optional[Path] = None) -> pd.Series:
    return load_series("US", root)


def watch_symbols(con, market: str, as_of: date, cap: int = 40) -> Dict[str, str]:
    """{isin: symbol} of held and listed names (IN: the book; US: the sleeve's pseudo-ISINs). Empty when the store cannot say."""
    try:
        if market == "IN":
            from pflab.hq import stocks
            bk = stocks.book(con, as_of)
            items = {i: s for i, s in bk.symbols.items() if i.startswith("INE")}
        else:
            items = {i: s for i, s in con.execute("SELECT isin, symbol FROM instruments WHERE isin LIKE 'ZZ%'").fetchall()}
        return dict(sorted(items.items(), key=lambda kv: kv[1])[:cap])
    except Exception:
        return {}


class Feed:
    """The prices the loop reads. Everything is injectable for tests; nothing is read until asked. `upto(d)` is the point-in-time cut."""

    def __init__(self, market: str, root=None, con=None, index_close: Optional[pd.Series] = None, us_close: Optional[pd.Series] = None,
                 symbols: Optional[Dict[str, str]] = None, symbol_loader: Optional[Callable] = None, horizon_end: Optional[date] = None):
        self.market, self.root, self.con = market, root, con
        self._index, self._us = index_close, us_close
        self._symbols, self._loader, self._sym_cache = symbols, symbol_loader, {}
        self.end = horizon_end

    @property
    def index_close(self) -> pd.Series:
        if self._index is None:
            self._index = load_series(self.market, self.root)
        return self._index

    @property
    def us_close(self) -> Optional[pd.Series]:
        if self.market != "IN":
            return None
        if self._us is None:
            try:
                self._us = load_us(self.root)
            except Exception:
                self._us = pd.Series(dtype=float)
        return self._us

    def index_upto(self, d: date) -> pd.Series:
        s = self.index_close
        return s[s.index <= pd.Timestamp(d)]

    def us_upto(self, d: date) -> Optional[pd.Series]:
        u = self.us_close
        if u is None or len(u) == 0:
            return None
        return u[u.index <= pd.Timestamp(d + timedelta(days=1))]   # US sessions dated before the next home session are known by its open

    def symbols(self, as_of: date) -> Dict[str, str]:
        if self._symbols is None:
            self._symbols = watch_symbols(self.con, self.market, as_of) if self.con is not None else {}
        return self._symbols

    def symbol_series(self, isin: str) -> pd.Series:
        if isin not in self._sym_cache:
            if self._loader is not None:
                s = self._loader(isin)
            else:
                from pflab.app import research
                s = research.closes(self.con, Path(self.root), isin, self.end or date.today(), years=4)
            s = pd.Series(s).astype(float).dropna()
            s.index = pd.to_datetime(s.index).normalize()
            self._sym_cache[isin] = s[~s.index.duplicated(keep="last")].sort_index()
        return self._sym_cache[isin]

    def series(self, subject: str) -> pd.Series:
        return self.index_close if subject == markets.get(self.market).index else self.symbol_series(subject)

    def price_at(self, subject: str, d: date) -> Optional[float]:
        """The close on or just before d; None when the series does not reach d yet (the forecast then stays pending)."""
        try:
            s = self.series(subject)
        except Exception:
            return None
        if len(s) == 0 or s.index[-1] < pd.Timestamp(d):
            return None
        return float(s[s.index <= pd.Timestamp(d)].iloc[-1])


# --- helpers ------------------------------------------------------------------------------------------------------------------------------
def _unpack(rt_or_con):
    """(connection, data root or None). A Runtime has `.cursor()` and `.data_root`."""
    if hasattr(rt_or_con, "cursor") and hasattr(rt_or_con, "data_root"):
        return rt_or_con.cursor(), Path(rt_or_con.data_root)
    return rt_or_con, None


def _insert(con, table: str, df: pd.DataFrame) -> None:
    if len(df):
        con.register("_ins", df)
        try:
            con.execute(f"INSERT INTO {table} SELECT * FROM _ins")
        finally:
            con.unregister("_ins")


def _qjson(q: Dict[float, float]) -> str:
    return json.dumps({str(k): round(float(v), 8) for k, v in q.items()})


def _weights_for(con, market: str, h: int, upto: date, names: tuple, source: str = SOURCE) -> Dict[str, float]:
    full = W.current(con, market, h, source, F.names_for(market, True), upto=upto)
    w = {n: full.get(n, 0.0) for n in names}
    s = sum(w.values()) or 1.0
    return {n: v / s for n, v in w.items()}


# --- making forecasts -----------------------------------------------------------------------------------------------------------------
def make_forecasts(con, feed: Feed, market: str, s: date, now: datetime, source: str = SOURCE) -> dict:
    """The forecasts made at the close of session s (closes up to s): every subject, horizon and forecaster, plus the hedge. Rows that exist are kept."""
    from pflab.pm.store import next_id
    mk = markets.get(market)
    idx_name = mk.index
    have = {(r[0], r[1], r[2]) for r in con.execute(
        "SELECT subject, horizon_sessions, forecaster FROM forecasts_s79 WHERE market=? AND source=? AND as_of=?", [market, source, s]).fetchall()}
    subjects = [(idx_name, None, True, feed.index_upto(s))]
    for isin, sym in feed.symbols(s).items():
        try:
            c = feed.symbol_series(isin)
            subjects.append((isin, sym, False, c[c.index <= pd.Timestamp(s)]))
        except Exception:
            continue
    nxt = mk.next_session(s)
    us = feed.us_upto(s)
    rows, made, ext = [], 0, False
    for subject, sym, is_idx, close in subjects:
        if len(close) < MIN_HISTORY or close.index[-1].date() != s:
            continue
        base = float(close.iloc[-1])
        names = F.names_for(market, is_idx)
        for h in P.HORIZONS:
            frames = F.all_frames(close, h, names, us_close=us, next_date=nxt)
            q = {n: F.last_row(fr) for n, fr in frames.items()}
            if is_idx and "overnight" in q:
                drv = F.last_driver(close, us, nxt)
            else:
                drv = None
            matures = mk.session_after(s, h)
            w = _weights_for(con, market, h, s, names)
            hedge = W.combine({n: v for n, v in q.items() if v is not None}, w)
            allq = dict(q)
            allq[P.COMBINED] = hedge
            for fc, qq in allq.items():
                if qq is None or (subject, h, fc) in have:
                    continue
                meta = {}
                if fc == "overnight":
                    if ext is False:
                        ext = F.EXTERNAL_GAP(con, nxt, market, feed.root)
                    meta = {"driver_ret": drv, "external_gap": ext}
                if fc == P.COMBINED:
                    meta = {"weights": {k: round(v, 4) for k, v in w.items()}}
                rows.append([None, market, source, s, subject, sym, h, fc, _qjson(qq), base, matures, json.dumps(meta), now])
    if rows:
        n0 = next_id(con, "forecasts_s79", "forecast_id")
        for i, r in enumerate(rows):
            r[0] = n0 + i
        _insert(con, "forecasts_s79", pd.DataFrame(rows, columns=["forecast_id", "market", "source", "as_of", "subject", "symbol", "horizon_sessions", "forecaster",
                                                                   "quantiles_json", "base_price", "matures", "meta_json", "made_at"]))
        made = len(rows)
    return {"made": made, "subjects": len(subjects)}


def refresh_overnight(con, feed: Feed, market: str, s: date, now: datetime, source: str = SOURCE) -> int:
    """The overnight forecast made at the close of s without its driver (the US close was not in yet) is remade once the driver is known, with the hedge that
    contains it, as long as it has not been scored. Information is point in time (the US close precedes the next home open); `backfilled` records a remake
    after the target session's own close."""
    if market != "IN":
        return 0
    mk = markets.get(market)
    nxt = mk.next_session(s)
    rows = con.execute(
        "SELECT f.forecast_id, f.horizon_sessions, f.meta_json FROM forecasts_s79 f LEFT JOIN forecast_scores_s79 c ON c.forecast_id=f.forecast_id "
        "WHERE f.market=? AND f.source=? AND f.as_of=? AND f.subject=? AND f.forecaster='overnight' AND c.forecast_id IS NULL",
        [market, source, s, mk.index]).fetchall()
    close, us, n = feed.index_upto(s), feed.us_upto(s), 0
    if len(close) < MIN_HISTORY or close.index[-1].date() != s:
        return 0
    drv = F.last_driver(close, us, nxt)
    if drv is None:
        return 0
    names = F.names_for(market, True)
    for fid, h, mj in rows:
        meta = json.loads(mj or "{}")
        if meta.get("driver_ret") is not None:
            continue
        q = F.last_row(F.overnight(close, h, us_close=us, next_date=nxt))
        if q is None:
            continue
        w_end = mk.window_ist(nxt)
        meta.update(driver_ret=drv, remade_at=str(now), backfilled=bool(w_end and now >= w_end[1]))
        con.execute("UPDATE forecasts_s79 SET quantiles_json=?, meta_json=?, made_at=? WHERE forecast_id=?", [_qjson(q), json.dumps(meta), now, fid])
        # the hedge of this horizon, now with the overnight
        allq = {n: F.last_row(F.all_frames(close, h, (n,), us_close=us, next_date=nxt)[n]) for n in names}
        w = _weights_for(con, market, h, s, names, source)
        hq = W.combine({n: v for n, v in allq.items() if v is not None}, w)
        if hq is not None:
            con.execute("UPDATE forecasts_s79 SET quantiles_json=?, made_at=? WHERE market=? AND source=? AND as_of=? AND subject=? AND horizon_sessions=? "
                        "AND forecaster=?", [_qjson(hq), now, market, source, s, mk.index, h, P.COMBINED])
        n += 1
    return n


# --- correcting: the Hedge update ------------------------------------------------------------------------------------------------------
def update_weights(con, market: str, scored: pd.DataFrame, now: datetime, source: str = SOURCE) -> int:
    """After scoring: for each matured INDEX forecast set (by maturity, in order) one Hedge step per horizon; the weights are stored with that maturity date."""
    if scored is None or scored.empty:
        return 0
    idx = markets.get(market).index
    names = F.names_for(market, True)
    sub = scored[(scored["subject"] == idx) & (scored["forecaster"].isin(names + (P.BENCHMARK,)))]
    done = 0
    for (h, mat, as_of), g in sub.sort_values(["matures", "as_of"]).groupby(["horizon_sessions", "matures", "as_of"], sort=False):
        loss = dict(zip(g["forecaster"], g["pinball_mean"]))
        if P.BENCHMARK not in loss:
            continue
        nl = loss[P.BENCHMARK]
        w = W.current(con, market, int(h), source, names, upto=None)
        vec = np.array([w[n] for n in names])
        ls = np.array([loss.get(n, nl) for n in names])
        new = W.hedge_step(vec, ls, nl, int(h))
        W.store(con, market, source, int(h), mat, dict(zip(names, new)), W.n_updates(con, market, int(h), source) + 1, now)
        done += 1
    return done


# --- the loop ---------------------------------------------------------------------------------------------------------------------------
def post_close(rt_or_con, market: str, session_date: date, now: Optional[datetime] = None, feed: Optional[Feed] = None) -> dict:
    """Everything after a session closed. Idempotent: a second call for the same session changes nothing."""
    con, root = _unpack(rt_or_con)
    now = now or datetime.now()
    mk = markets.get(market)
    if not mk.is_session(session_date):
        return {"market": market, "session": str(session_date), "skipped": "not a session"}
    feed = feed or Feed(market, root, con, horizon_end=session_date)
    out: dict = {"market": market, "session": str(session_date)}
    try:
        P.register(con, now)
    except FileNotFoundError as e:
        out["register"] = str(e)
    close = feed.index_upto(session_date)
    if len(close) == 0 or close.index[-1].date() != session_date:
        return {**out, "no_data": f"no {mk.index} close for {session_date} yet"}
    prev = mk.previous_session(session_date)
    out["overnight_refreshed"] = refresh_overnight(con, feed, market, prev, now)
    scored = S.score_pending(con, feed.price_at, market, session_date, SOURCE, now)
    out["scored"] = int(len(scored))
    out["weight_steps"] = update_weights(con, market, scored, now)
    out["fall_resolved"] = fall_risk.resolve(con, market, close, session_date, SOURCE, now)
    out.update(make_forecasts(con, feed, market, session_date, now))
    fr = fall_risk.make(con, market, close, session_date, SOURCE, now)
    out["fall_risk"] = None if fr is None else {k: (round(v, 4) if isinstance(v, float) else v) for k, v in fr.items()}
    return out


def catch_up(rt_or_con, market: str, upto_date: date, now: Optional[datetime] = None, feed: Optional[Feed] = None, max_back: int = 10) -> dict:
    """post_close for EACH session after the last one done, up to `upto_date`, in order (an unseen first run starts `max_back` sessions back). Stops at the
    first session whose close is not in the data yet, so the order is never broken. Idempotent."""
    con, root = _unpack(rt_or_con)
    now = now or datetime.now()
    mk = markets.get(market)
    last = con.execute("SELECT max(as_of) FROM forecasts_s79 WHERE market=? AND source=?", [market, SOURCE]).fetchone()[0]
    end = mk.last_session_on_or_before(upto_date)
    if last is None:
        sessions = mk.sessions_between(mk.session_after(end, -(max_back - 1)), end)
    else:
        sessions = mk.sessions_between(last + timedelta(days=1), end)
    feed = feed or Feed(market, root, con, horizon_end=end)
    done, stopped = [], None
    for s in sessions:
        r = post_close(con, market, s, now, feed)
        if r.get("no_data"):
            stopped = r["no_data"]
            break
        done.append(r)
    return {"market": market, "sessions_done": [r["session"] for r in done], "stopped": stopped, "results": done}
