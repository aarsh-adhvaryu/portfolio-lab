"""The key of a US instrument (CLAUDE.md rule 3, `ledger/foreign.py`).

A US instrument uses its real ISIN when a statement shows one; otherwise its key is the pseudo-ISIN "ZZ" + the 10-digit SEC CIK (12 characters; "ZZ" is no ISO country, so it never
meets a real ISIN), and `instrument_alias` maps the pseudo key to the real ISIN from a date. A fund with no CIK in SEC's ticker file keeps the symbol key the price panel already uses
(`US:SYMBOL`, data/us_prices.py `build_panel`): one stable key, never joined to anything by symbol alone. A position is always counted under `canonical(...)` of its key ON A DATE, so
the same shares held under a pseudo key and bought later under the real one are one position.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Optional

from pflab.ledger import foreign as lf

CIK_FILE = ("us", "cik_map.json")
SYMBOL_PREFIX = "US:"


def _path(root) -> Path:
    if root is None:
        from pflab.data import data_dir
        root = data_dir()
    return Path(root).joinpath(*CIK_FILE)


def load_ciks(root=None) -> Dict[str, int]:
    """ticker -> CIK from the cache file `data/us/cik_map.json` (written by `refresh_ciks`); {} when there is none."""
    p = _path(root)
    try:
        return {k.upper(): int(v) for k, v in json.loads(p.read_text(encoding="utf-8")).items()}
    except Exception:
        return {}


def sec_contact_configured() -> bool:
    """True when SEC's contact User-Agent is set (the environment variable PFLAB_SEC_USER_AGENT or `[sec] user_agent` in the secrets file). Never returns or prints the value:
    SEC answers 403 to every other User-Agent (data/sec_edgar.py), so without it nothing is fetched."""
    import os
    if os.environ.get("PFLAB_SEC_USER_AGENT"):
        return True
    try:
        from pflab.pm import secrets
        return bool(secrets.load().has("sec", "user_agent"))
    except Exception:
        return False


def refresh_ciks(root=None, get=None) -> int:
    """Fetch SEC's ticker -> CIK file with the contact User-Agent of data/sec_edgar.py (`sec_edgar.get_json` builds it from `[sec] user_agent` in the secrets file; it is never printed)
    and cache it. Returns how many tickers. A failure keeps the old file (it raises: `refresh_if_due` is the safe caller)."""
    from pflab.data import us_prices
    ciks = us_prices.cik_map(get)
    p = _path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ciks, sort_keys=True), encoding="utf-8")
    return len(ciks)


def refresh_if_due(root=None, get=None, max_age_days: int = 30, now: Optional[datetime] = None) -> dict:
    """The network step, called by the job (never by the close function, so a test never reaches SEC): refresh the cached map when it is older than `max_age_days` or absent.
    Without the contact User-Agent nothing is fetched and the answer says so (US holdings then keep their `US:SYMBOL` keys). Never raises. `get` is for tests."""
    import time
    p = _path(root)
    if p.exists() and ((now.timestamp() if now else time.time()) - p.stat().st_mtime) < max_age_days * 86400:
        return {"skipped": f"the CIK map is less than {max_age_days} days old"}
    if get is None and not sec_contact_configured():
        return {"skipped": "no [sec] user_agent in the secrets file (or PFLAB_SEC_USER_AGENT): SEC refuses a fetch without a contact, so US holdings keep their US:SYMBOL keys"}
    try:
        return {"refreshed": refresh_ciks(root, get)}
    except Exception as e:
        return {"failed": f"{type(e).__name__}: {str(e)[:160]}", "kept": "the old map and the US:SYMBOL keys"}


def key_for(con, symbol: str, ciks: Optional[Dict[str, int]] = None, isins: Optional[Dict[str, str]] = None, market: str = "US") -> str:
    """The key to use for `symbol`: the one already registered for it, else a real ISIN given, else ZZ+CIK, else the symbol key."""
    sym = symbol.upper()
    r = con.execute("SELECT isin FROM instruments WHERE symbol=? AND market=? ORDER BY (isin LIKE 'US:%'), built_at LIMIT 1", [sym, market]).fetchone()   # a mapped ZZ key beats the old symbol key
    if r:
        return r[0]
    if isins and sym in isins:
        return isins[sym]
    if ciks and sym in ciks:
        return lf.pseudo_isin(ciks[sym])
    return SYMBOL_PREFIX + sym


def ensure(con, symbol: str, name: str = "", etf: bool = False, ciks: Optional[Dict[str, int]] = None, isins: Optional[Dict[str, str]] = None,
           now: Optional[datetime] = None, since: Optional[date] = None, market: str = "US") -> str:
    """Register the instrument (market US, currency USD) under its key and return the key. A real ISIN given for a symbol already keyed by its pseudo-ISIN becomes an alias from `since`."""
    sym = symbol.upper()
    key = key_for(con, sym, ciks, isins, market)
    lf.register_instrument(con, sym, key, name or sym, market=market, currency="USD" if market == "US" else "INR", etf=etf, now=now)
    real = (isins or {}).get(sym)
    if real and real != key and lf.is_pseudo(key):
        lf.add_alias(con, key, real, since or (now or datetime.now()).date())
    return key


def canonical(con, key: str, on: Optional[date] = None) -> str:
    """The key `key` maps to on `on` (the key itself when it has no alias yet). Follows a chain (US:SYMBOL -> ZZ+CIK -> a real ISIN)."""
    for _ in range(4):
        nxt = lf.resolve(con, key, on)
        if nxt == key:
            break
        key = nxt
    return key


def _first_use(con, key: str) -> Optional[date]:
    """The earliest date any row of the sub-book mentions `key` (lots, orders, trades, dividends, events)."""
    best = None
    for q in ("SELECT min(acq_date) FROM us_lots_s81 WHERE isin=?", "SELECT min(placed_day) FROM us_orders_s81 WHERE isin=?", "SELECT min(day) FROM us_trades_s81 WHERE isin=?",
              "SELECT min(day) FROM us_dividends_s81 WHERE isin=?", "SELECT min(day) FROM us_events_s81 WHERE isin=?"):
        try:
            d = con.execute(q, [key]).fetchone()[0]
        except Exception:
            d = None
        if d is not None and (best is None or d < best):
            best = d
    return best


def map_symbol_keys(con, ciks: Dict[str, int], since: Optional[date] = None, now: Optional[datetime] = None) -> list:
    """Every US instrument still under its symbol key (`US:SPY`) whose ticker is in SEC's map is MAPPED to its `ZZ`+10-digit-CIK key by an alias row (`instrument_alias`: the symbol key
    resolves to the ZZ key, or to its real ISIN when it has one, from the date the symbol key was first used, else `since`, else today). The ZZ instrument is registered. No row of any
    table changes its key column: readers count a position under `canonical(...)`. Idempotent: an alias that already points there is left alone (its date is never moved)."""
    out = []
    for isin, sym, asset_class, name in con.execute("SELECT isin, symbol, asset_class, name FROM instruments WHERE market='US' AND isin LIKE 'US:%' ORDER BY isin").fetchall():
        cik = (ciks or {}).get((sym or "").upper())
        if not cik:
            continue
        zz = lf.pseudo_isin(cik)
        lf.register_instrument(con, sym, zz, name or sym, market="US", currency="USD", etf=(asset_class == "etf"), now=now)
        target = canonical(con, zz)
        have = con.execute("SELECT isin, since FROM instrument_alias WHERE alias=?", [isin]).fetchone()
        if have and have[0] == target:
            continue
        frm = _first_use(con, isin) or since or (now or datetime.now()).date()
        con.execute("INSERT INTO instrument_alias VALUES (?,?,?) ON CONFLICT (alias) DO UPDATE SET isin=excluded.isin, since=excluded.since", [isin, target, frm])
        out.append({"symbol": sym, "from_key": isin, "to_key": target, "since": str(frm)})
    return out


def symbol_of(con, key: str) -> Optional[str]:
    r = con.execute("SELECT symbol FROM instruments WHERE isin=?", [key]).fetchone()
    if r and r[0]:
        return r[0]
    return key[len(SYMBOL_PREFIX):] if key.startswith(SYMBOL_PREFIX) else None
