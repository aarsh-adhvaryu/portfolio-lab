"""S91: five-minute candles of one NSE name, from Kite's own "5minute" history (read only), kept in `bars_5m_s91` and served to the Stock screen.

Times are exchange-local (IST, naive, as everywhere in this system: `markets.get("IN")`). A candle is stamped with its START; the 09:15 candle covers 09:15 to 09:20 and is complete at 09:20.
Honest rules: a candle whose end has not passed is `partial` (shown as forming, never counted as the latest closed one); a missing candle stays missing (the screen shows the gap; nothing is
interpolated); a bar the exchange window does not contain is dropped; duplicates collapse on (isin, ts). Where Kite's 5-minute history is not stored for a session but the minute bars are
(`bars_1m`), the candles of that session are built from the minutes and say so (`src`: minutes). A failed or refused fetch never blanks what is stored: the answer carries the reason.
"""
from __future__ import annotations

import threading
import time as _time
from datetime import date, datetime, time, timedelta
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

OPEN, CLOSE = time(9, 15), time(15, 30)
SLOTS = 75                                   # 09:15 .. 15:30 in five-minute candles
SESSIONS = 3                                 # what the screen shows
MIN_REFRESH_S = 45                           # one name is fetched at most this often (the screen asks every 30 s)
TOKEN_TTL_S = 6 * 3600
COLS = ["ts", "open", "high", "low", "close", "volume"]

DDL = """CREATE TABLE IF NOT EXISTS bars_5m_s91 (isin VARCHAR NOT NULL, ts TIMESTAMP NOT NULL, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, fetched_at TIMESTAMP,
         PRIMARY KEY (isin, ts))"""

_LOCK = threading.Lock()
_BUSY: set = set()
_LAST: Dict[str, Tuple[float, dict]] = {}
_TOK: dict = {"at": 0.0, "eq": {}}


def ensure(con) -> None:
    con.execute(DDL)


def _kind(e: Exception) -> str:
    from pflab.ingest.kite_backfill import _kind as k
    return k(e)


# --- fetching ---------------------------------------------------------------------------------------------------------------------------------------------

def frame_of(rows: List[dict]) -> pd.DataFrame:
    """Kite candles -> ts/open/high/low/close/volume (naive IST), inside the session window, on the five-minute grid, no duplicates, sorted."""
    if not rows:
        return pd.DataFrame({"ts": pd.Series(dtype="datetime64[ns]"), **{c: pd.Series(dtype="float64") for c in COLS[1:]}})
    df = pd.DataFrame(rows)
    ts = pd.to_datetime(df["date"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    df["ts"] = ts.dt.floor("5min")
    tod = df["ts"].dt.time
    df = df[(tod >= OPEN) & (tod < CLOSE)].drop_duplicates("ts", keep="last").sort_values("ts")
    for c in COLS[1:]:
        df[c] = df[c].astype("float64")
    return df[COLS].reset_index(drop=True)


def fetch(kite, token: int, first: date, last: date, retries: int = 2, sleep: Callable[[float], None] = _time.sleep) -> pd.DataFrame:
    """One request for first..last inclusive. A token or permission refusal is raised at once (the caller says so); a rate or network failure is retried with a growing wait."""
    delay = 1.5
    for attempt in range(retries + 1):
        try:
            return frame_of(kite.historical_data(token, datetime.combine(first, OPEN), datetime.combine(last, CLOSE), "5minute") or [])
        except Exception as e:
            kind = _kind(e)
            if kind in ("token", "permission") or kind not in ("rate", "network") or attempt == retries:
                raise
            sleep(delay)
            delay *= 2
    return frame_of([])


def store(con, isin: str, df: pd.DataFrame, now: datetime) -> int:
    ensure(con)
    if df is None or not len(df):
        return 0
    n0 = con.execute("SELECT count(*) FROM bars_5m_s91 WHERE isin=?", [isin]).fetchone()[0]
    d = df.copy()
    d["isin"], d["fetched_at"] = isin, now
    con.register("_b5_new", d[["isin", "ts", "open", "high", "low", "close", "volume", "fetched_at"]])
    try:
        con.execute("INSERT OR REPLACE INTO bars_5m_s91 SELECT isin, ts, open, high, low, close, volume, fetched_at FROM _b5_new")
    finally:
        con.unregister("_b5_new")
    return con.execute("SELECT count(*) FROM bars_5m_s91 WHERE isin=?", [isin]).fetchone()[0] - n0


def _token_of(kite, symbol: str, now: float) -> Optional[int]:
    from pflab.ingest.kite_backfill import instrument_tokens
    if now - _TOK["at"] > TOKEN_TTL_S or not _TOK["eq"]:
        _TOK["eq"], _ = instrument_tokens(kite)
        _TOK["at"] = now
    return _TOK["eq"].get(str(symbol).upper())


def _client(rt, now: datetime):
    from pflab.ingest import kite as km
    sec = getattr(rt, "secrets", None)
    if sec is None:
        from pflab.pm import secrets as sc
        sec = sc.load()
    return km.client(sec, now=now)


def _window(now: datetime, sessions: int = SESSIONS) -> Tuple[date, date]:
    from pflab import markets
    m = markets.get("IN")
    last = now.date() if m.is_session(now.date()) and now.time() >= OPEN else m.session_closed_by(now)
    first = last
    for _ in range(sessions - 1):
        first = m.previous_session(first)
    return first, last


def refresh(rt, con, isin: str, symbol: str, now: datetime, kite=None, force: bool = False, sleep: Callable[[float], None] = _time.sleep) -> dict:
    """Fetch the last few sessions' five-minute candles of one name into the store. -> {"state": ok | needs_login | refused | network | unknown_name | fresh | busy, "rows": added, ...}.
    `fresh`: asked again within MIN_REFRESH_S, or the market is shut and the latest closed session is already stored whole. Never raises: a failure is a state."""
    ensure(con)
    key = isin
    with _LOCK:
        if key in _BUSY:
            return {"state": "busy"}
        last = _LAST.get(key)
        if not force and last and _time.monotonic() - last[0] < MIN_REFRESH_S:
            return {**last[1], "state": "fresh"}
        _BUSY.add(key)
    try:
        first, last_day = _window(now)
        if not force and _complete(con, isin, last_day, now):
            out = {"state": "fresh", "why": "the latest closed session is stored whole"}
        else:
            k = kite if kite is not None else _client(rt, now)
            if k is None:
                out = {"state": "needs_login", "why": "Kite is not logged in today: five-minute candles from before the login are kept; new ones need the login"}
            else:
                tok = _token_of(k, symbol, _time.monotonic())
                if tok is None:
                    out = {"state": "unknown_name", "why": f"{symbol} is not an NSE cash symbol Kite lists"}
                else:
                    df = fetch(k, tok, first, last_day, sleep=sleep)
                    out = {"state": "ok", "rows": store(con, isin, df, now), "got": int(len(df))}
    except Exception as e:
        kind = _kind(e)
        out = {"state": {"token": "needs_login", "permission": "refused", "network": "network", "rate": "network"}.get(kind, "error"),
               "why": {"token": "Kite's login has lapsed: log in again", "permission": "Kite's historical data is not on this Kite plan",
                       "network": "Kite did not answer: the stored candles are shown and it tries again", "rate": "Kite asked for a pause: it tries again"}.get(kind, f"{type(e).__name__}: {str(e)[:120]}")}
    finally:
        with _LOCK:
            _BUSY.discard(key)
    with _LOCK:
        _LAST[key] = (_time.monotonic(), {k: v for k, v in out.items() if k != "state"})
    out["at"] = str(now)[:19]
    return out


def refresh_async(rt, isin: str, symbol: str, now: datetime) -> None:
    """Start a refresh in its own thread (the screen never waits for Kite); the thread uses its own cursor."""
    def run():
        try:
            refresh(rt, rt.cursor(), isin, symbol, now)
            rt.bump("candles")
        except Exception:
            pass
    threading.Thread(target=run, name=f"b5-{symbol}", daemon=True).start()


def _complete(con, isin: str, day: date, now: datetime) -> bool:
    """The session of `day` is closed and its last candle (15:25) is stored."""
    if datetime.combine(day, CLOSE) > now:
        return False
    r = con.execute("SELECT 1 FROM bars_5m_s91 WHERE isin=? AND ts=?", [isin, datetime.combine(day, time(15, 25))]).fetchone()
    return bool(r)


# --- serving ----------------------------------------------------------------------------------------------------------------------------------------------

def _from_minutes(con, isin: str, first: date, last: date) -> pd.DataFrame:
    try:
        t = con.execute("SELECT ts, open, high, low, close, volume FROM bars_1m WHERE market='IN' AND isin=? AND ts>=? AND ts<? ORDER BY ts",
                        [isin, datetime.combine(first, time(0)), datetime.combine(last + timedelta(days=1), time(0))]).fetchdf()
    except Exception:
        return pd.DataFrame(columns=COLS)
    if not len(t):
        return pd.DataFrame(columns=COLS)
    t["b"] = t["ts"].dt.floor("5min")
    g = t.groupby("b").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum"), n=("ts", "count")).reset_index().rename(columns={"b": "ts"})
    return g[g["n"] >= 3][COLS]                                         # a candle with fewer than three minutes behind it is not built: the gap stays a gap


def candles(con, isin: str, now: datetime, sessions: int = SESSIONS) -> dict:
    """The candles to draw: {"bars": [{"d", "t", "o", "h", "l", "c", "v", "slot", "partial", "src"}], "sessions": [dates], "latest_closed", "fetched_at", "gaps"}.
    `slot` is the candle's place in its session (0..74) and `s` the session's index among those shown, so a missing candle is a visible gap."""
    from pflab import markets
    ensure(con)
    m = markets.get("IN")
    first, last = _window(now, sessions)
    days = [d for d in pd.date_range(first, last).date if m.is_session(d)]
    stored = con.execute("SELECT ts, open, high, low, close, volume, fetched_at FROM bars_5m_s91 WHERE isin=? AND ts>=? AND ts<? ORDER BY ts",
                         [isin, datetime.combine(first, time(0)), datetime.combine(last + timedelta(days=1), time(0))]).fetchdf()
    have = set(stored["ts"].dt.date) if len(stored) else set()
    mins = _from_minutes(con, isin, first, last)
    rows = []
    for _, r in stored.iterrows():
        rows.append((r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"], "kite 5-minute"))
    if len(mins):
        for _, r in mins.iterrows():
            if r["ts"].date() not in have:
                rows.append((r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"], "built from minute bars"))
    rows.sort(key=lambda x: x[0])
    sidx = {d: i for i, d in enumerate(days)}
    bars, latest_closed = [], None
    for ts, o, h, l, c, v, src in rows:
        d = ts.date()
        if d not in sidx:
            continue
        end = ts + timedelta(minutes=5)
        partial = bool(end > now)
        if not partial:
            latest_closed = ts
        bars.append({"d": str(d), "t": ts.strftime("%H:%M"), "ts": str(ts)[:16], "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": float(v or 0),
                     "slot": int((ts - datetime.combine(d, OPEN)).total_seconds() // 300), "s": sidx[d], "partial": partial, "src": src})
    fetched = stored["fetched_at"].max() if len(stored) else None
    slots_expected = sum(SLOTS for d in days if datetime.combine(d, CLOSE) <= now) + sum(max(0, min(SLOTS, int((now - datetime.combine(d, OPEN)).total_seconds() // 300))) for d in days if datetime.combine(d, CLOSE) > now and datetime.combine(d, OPEN) <= now)
    return {"bars": bars, "sessions": [str(d) for d in days], "latest_closed": str(latest_closed)[:16] if latest_closed is not None else None,
            "fetched_at": str(fetched)[:19] if fetched is not None else None, "gaps": max(0, slots_expected - len([b for b in bars if not b["partial"]]))}


def latest_closed_any(con, now: Optional[datetime] = None) -> Optional[str]:
    """The newest closed candle over every name (Home's "latest closed candle"): a candle is closed when its five minutes have passed at `now`."""
    try:
        r = con.execute("SELECT max(ts) FROM bars_5m_s91 WHERE ts + INTERVAL 5 MINUTE <= ?", [now or datetime.now()]).fetchone()
        return str(r[0])[:16] if r and r[0] else None
    except Exception:
        return None
