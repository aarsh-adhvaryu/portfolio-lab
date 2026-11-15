"""S91 job `candles_5m`: while the Indian session runs (and once after it), the five-minute candles of every name he holds, plus the paper book's names, from Kite's history (read only).
It also catches up: opened late or after a gap, one request per name brings the last sessions' candles. A logged-out Kite, a refusal or a network failure is a stated skip, never an error
(the Stock screen and Home say which). Throttled to about 2 requests a second (Kite allows 3)."""
from __future__ import annotations

import time as _time
from datetime import datetime
from typing import Callable, Dict

from pflab.service.jobs import Ctx, Job, register
from pflab.service.schedule import Interval

MAX_NAMES = 30
SPACING_S = 0.5


def names(con) -> Dict[str, str]:
    """{isin: symbol} of his Kite holdings and the paper book's holdings (India)."""
    out: Dict[str, str] = {}
    try:
        for sym, isin in con.execute("SELECT symbol, isin FROM mine_in_s89 WHERE qty > 0").fetchall():
            if sym and isin:
                out[isin] = str(sym)
    except Exception:
        pass
    try:
        sym_of = {r[0]: r[1] for r in con.execute("SELECT isin, symbol FROM instruments WHERE symbol IS NOT NULL").fetchall()}
        for (isin,) in con.execute("SELECT DISTINCT isin FROM paper_lots WHERE qty > 0").fetchall():
            if isin in sym_of:
                out.setdefault(isin, sym_of[isin])
    except Exception:
        pass
    return dict(list(out.items())[:MAX_NAMES])


def _run(ctx: Ctx, kite=None, sleep: Callable[[float], None] = _time.sleep) -> dict:
    from pflab.app import settings as _st
    from pflab.ingest import intraday5 as i5
    from pflab.ingest import kite as km
    try:
        if not _st.ability("kite_live", current=getattr(ctx, "settings", None)):
            return {"skipped": "Kite live data is switched off in Settings"}
    except Exception:
        pass
    kc = kite if kite is not None else (km.client(ctx.secrets, now=ctx.now) if ctx.secrets is not None and ctx.secrets.has("kite", "api_key") else None)
    if kc is None:
        return {"skipped": "kite logged out: five-minute candles wait for the login"}
    want = names(ctx.con)
    if not want:
        return {"skipped": "no holdings yet: they come from the Kite snapshot"}
    states: Dict[str, int] = {}
    why = ""
    for isin, sym in want.items():
        r = i5.refresh(None, ctx.con, isin, sym, ctx.now, kite=kc, sleep=sleep)
        states[r["state"]] = states.get(r["state"], 0) + 1
        if r["state"] in ("needs_login", "refused"):
            why = r.get("why", "")
            break
        sleep(SPACING_S)
    out = {"names": len(want), "states": states, "latest_closed": i5.latest_closed_any(ctx.con, ctx.now)}
    if why:
        out["skipped"] = why
    return out


register(Job("candles_5m", Interval(5, start_hour=9, end_hour=17, weekdays_only=True), _run,
             "S91: five-minute candles of the names he holds, while the session runs and once after it (Kite history, read only); a missing candle is stated, never filled",
             cooldown_minutes=3))
