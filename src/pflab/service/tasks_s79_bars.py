"""S79 item 7: the minute bars of what the system holds or watches, recorded after each session (the raw material of "why did it move").

Job `bars_1m`: after a market's close, for the last few closed sessions, fetch Kite's 1-minute candles (read only, `ingest/kite.py`) of every held, listed, watched and
paper-ordered name and of the market's index and benchmark, into `bars_1m`; what each fetch found is written to `bars_1m_runs` (bars returned against a full session's
count), so a missing minute is a stated gap and is never invented or filled. Idempotent: a bar already stored is kept, a name whose day was recorded in full is not asked again.
No Kite login today: the job returns {"skipped": "kite logged out"} and says so; it never fails. Only India has a minute source so far (Kite).
"""
from __future__ import annotations

import time as _time
from datetime import date, datetime, time, timedelta
from typing import Callable, Dict, List, Optional

import pandas as pd

from pflab.service.jobs import Ctx, Job, register
from pflab.service.schedule import Daily

LOOKBACK_SESSIONS = 3
PAUSE = 0.35                                  # Kite allows about 3 historical requests a second
INDEX_PREFIX = "INDEX:"
SOURCE_MARKETS = ("IN",)


def expected_bars(m) -> int:
    from pflab.quant.trajectory import expected_minutes
    return expected_minutes(m.open, m.close)


def wanted(con, market: str, day: date) -> Dict[str, str]:
    """{key: symbol} of what to record: held, listed (stock list), open paper orders, active watches, and the market's indexes. Key is the ISIN, or INDEX:<name>."""
    from pflab import markets
    m = markets.get(market)
    out: Dict[str, str] = {}
    sym = {r[0]: r[1] for r in con.execute("SELECT isin, symbol FROM instruments WHERE symbol IS NOT NULL").fetchall()}
    isins: set = set()
    try:
        from pflab.pm import today as nw
        pos = nw.build(con, day)["positions"]
        isins |= set(pos["isin"]) if len(pos) else set()
    except Exception:
        pass
    try:
        from pflab.plan import guards as gd
        isins |= {s["isin"] for s in gd.stock_list()}
    except Exception:
        pass
    for q in ("SELECT DISTINCT isin FROM paper_orders WHERE status='open'", "SELECT DISTINCT isin FROM paper_watch WHERE status IN ('waiting','near','triggered')"):
        try:
            isins |= {r[0] for r in con.execute(q).fetchall() if r[0]}
        except Exception:
            pass
    for i in sorted(isins):
        if sym.get(i) and not str(i).startswith("ZZ"):                # a US pseudo-ISIN is not on NSE
            out[i] = sym[i]
    for ix in dict.fromkeys([m.index, m.benchmark]):
        out[INDEX_PREFIX + ix.upper()] = ix.upper()
    return out


def tokens(kite) -> Dict[str, int]:
    """Kite instrument tokens: NSE equities by trading symbol, indices by name (the instrument list is fetched once per run)."""
    out: Dict[str, int] = {}
    for r in kite.instruments("NSE") or []:
        seg, name, tok = r.get("segment"), r.get("tradingsymbol"), r.get("instrument_token")
        if not (name and tok):
            continue
        if seg == "NSE":
            out.setdefault(str(name).upper(), int(tok))
        elif seg == "INDICES":
            out.setdefault(INDEX_PREFIX + str(name).upper(), int(tok))
    return out


def fetch_day(kite, token: int, m, day: date) -> pd.DataFrame:
    """One day's 1-minute candles from Kite, inside the session window only (ts: the exchange's wall clock, no timezone)."""
    rows = kite.historical_data(token, datetime.combine(day, time(9, 0)), datetime.combine(day, time(15, 40)), "minute")
    if not rows:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.floor("min")
    lo, hi = datetime.combine(day, m.open), datetime.combine(day, m.close)
    df = df[(df["ts"] >= lo) & (df["ts"] < hi)].drop_duplicates("ts").sort_values("ts")
    return df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def store_bars(con, market: str, key: str, df: pd.DataFrame) -> int:
    """Insert the bars not already stored; a stored bar is never changed. Returns the number of new bars."""
    if df.empty:
        return 0
    b = df.assign(market=market, isin=key)[["market", "isin", "ts", "open", "high", "low", "close", "volume"]]
    n0 = con.execute("SELECT count(*) FROM bars_1m WHERE market=? AND isin=?", [market, key]).fetchone()[0]
    con.register("_bars_new", b)
    try:
        con.execute("INSERT INTO bars_1m SELECT market, isin, ts, open, high, low, close, volume FROM _bars_new ON CONFLICT DO NOTHING")
    finally:
        con.unregister("_bars_new")
    return con.execute("SELECT count(*) FROM bars_1m WHERE market=? AND isin=?", [market, key]).fetchone()[0] - n0


def note_run(con, market: str, key: str, symbol: str, day: date, n: int, expected: int, status: str, note: str, now: datetime) -> None:
    con.execute("DELETE FROM bars_1m_runs WHERE market=? AND isin=? AND day=?", [market, key, day])
    con.execute("INSERT INTO bars_1m_runs VALUES (?,?,?,?,?,?,?,?,?)", [market, key, day, symbol, int(n), int(expected), status, note[:300], now])


def record(con, kite, market: str, days: List[date], names: Dict[str, str], now: datetime, sleep: Callable[[float], None] = _time.sleep) -> dict:
    """Fetch and store the days' bars of the names. A name with no Kite token, a failed fetch and a short day are each recorded in `bars_1m_runs` and counted here."""
    from pflab import markets
    m = markets.get(market)
    exp = expected_bars(m)
    tok = tokens(kite)
    got = {"names": len(names), "days": [str(d) for d in days], "bars_new": 0, "full": 0, "partial": 0, "empty": 0, "no_token": 0, "errors": 0}
    for d in days:
        for key, symbol in names.items():
            done = con.execute("SELECT status FROM bars_1m_runs WHERE market=? AND isin=? AND day=?", [market, key, d]).fetchone()
            if done and done[0] == "full":
                continue
            t = tok.get(key if key.startswith(INDEX_PREFIX) else symbol.upper())
            if t is None:
                note_run(con, market, key, symbol, d, 0, exp, "no_token", "Kite lists no instrument for this symbol", now)
                got["no_token"] += 1
                continue
            try:
                df = fetch_day(kite, t, m, d)
                store_bars(con, market, key, df)
            except Exception as e:                                  # one name's failure must not stop the others
                note_run(con, market, key, symbol, d, 0, exp, "error", f"{type(e).__name__}: {str(e)[:200]}", now)
                got["errors"] += 1
                sleep(PAUSE)
                continue
            n = con.execute("SELECT count(*) FROM bars_1m WHERE market=? AND isin=? AND ts>=? AND ts<?", [market, key, datetime.combine(d, m.open), datetime.combine(d, m.close)]).fetchone()[0]
            status = "full" if n >= exp else "partial" if n else "empty"
            note_run(con, market, key, symbol, d, n, exp, status, "" if status == "full" else f"{exp - n} of {exp} minutes missing: stated, not filled", now)
            got[status] += 1
            got["bars_new"] += len(df)
            sleep(PAUSE)
    return got


def _kite(ctx: Ctx):
    from pflab.ingest import kite as km
    return km.client(ctx.secrets) if ctx.secrets is not None and ctx.secrets.has("kite", "api_key") else None


def _days(m, now: datetime) -> List[date]:
    last = m.session_closed_by(now)
    out = [last]
    while len(out) < LOOKBACK_SESSIONS:
        out.append(m.previous_session(out[-1]))
    return sorted(out)


def _bars_1m(ctx: Ctx, kite=None, sleep: Callable[[float], None] = _time.sleep) -> dict:
    from pflab import markets
    from pflab.app import settings as _st
    try:
        if not _st.ability("kite_live", current=getattr(ctx, "settings", None)):
            return {"skipped": "Kite live data is switched off in Settings"}
    except Exception:
        pass
    kc = kite if kite is not None else _kite(ctx)
    if kc is None:
        return {"skipped": "kite logged out"}
    out: dict = {}
    for code in markets.codes():
        if code not in SOURCE_MARKETS:
            out[code] = {"skipped": "no minute-bar source for this market yet"}
            continue
        m = markets.get(code)
        days = [d for d in _days(m, ctx.now) if datetime.combine(d, m.close) <= ctx.now]
        if not days:
            out[code] = {"skipped": "no session has closed yet"}
            continue
        out[code] = record(ctx.con, kc, code, days, wanted(ctx.con, code, days[-1]), ctx.now, sleep)
    return out


def _redo(ctx: Ctx) -> Optional[str]:
    """The slot's earlier success (a 'kite logged out' skip counts as one) no longer counts when Kite is logged in now and a name of the last closed session was never tried."""
    try:
        from pflab import markets
        from pflab.ingest import kite as km
        if km.TokenStore().load(ctx.now) is None:
            return None
        m = markets.get("IN")
        d = m.session_closed_by(ctx.now)
        if datetime.combine(d, m.close) > ctx.now:
            return None
        names = wanted(ctx.con, "IN", d)
        tried = {r[0] for r in ctx.con.execute("SELECT isin FROM bars_1m_runs WHERE market='IN' AND day=?", [d]).fetchall()}
        missing = [k for k in names if k not in tried]
        return f"{len(missing)} names have no minute bars tried for {d} and Kite is logged in now" if missing else None
    except Exception:
        return None


register(Job("bars_1m", Daily(16, 10), _bars_1m, "minute bars of held, listed and watched names and the index after each session (Kite, read only); a missing minute is stated, never filled",
             cooldown_minutes=60, redo_fn=_redo))
