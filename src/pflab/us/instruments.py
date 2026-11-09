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


def refresh_ciks(root=None, get=None) -> int:
    """Fetch SEC's ticker -> CIK file (needs the contact User-Agent of data/sec_edgar.py) and cache it. Returns how many tickers. A failure keeps the old file."""
    from pflab.data import us_prices
    ciks = us_prices.cik_map(get)
    p = _path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ciks, sort_keys=True), encoding="utf-8")
    return len(ciks)


def key_for(con, symbol: str, ciks: Optional[Dict[str, int]] = None, isins: Optional[Dict[str, str]] = None) -> str:
    """The key to use for `symbol`: the one already registered for it, else a real ISIN given, else ZZ+CIK, else the symbol key."""
    sym = symbol.upper()
    r = con.execute("SELECT isin FROM instruments WHERE symbol=? AND market='US' ORDER BY built_at LIMIT 1", [sym]).fetchone()
    if r:
        return r[0]
    if isins and sym in isins:
        return isins[sym]
    if ciks and sym in ciks:
        return lf.pseudo_isin(ciks[sym])
    return SYMBOL_PREFIX + sym


def ensure(con, symbol: str, name: str = "", etf: bool = False, ciks: Optional[Dict[str, int]] = None, isins: Optional[Dict[str, str]] = None,
           now: Optional[datetime] = None, since: Optional[date] = None) -> str:
    """Register the instrument (market US, currency USD) under its key and return the key. A real ISIN given for a symbol already keyed by its pseudo-ISIN becomes an alias from `since`."""
    sym = symbol.upper()
    key = key_for(con, sym, ciks, isins)
    lf.register_instrument(con, sym, key, name or sym, etf=etf, now=now)
    real = (isins or {}).get(sym)
    if real and real != key and lf.is_pseudo(key):
        lf.add_alias(con, key, real, since or (now or datetime.now()).date())
    return key


def canonical(con, key: str, on: Optional[date] = None) -> str:
    """The real ISIN `key` maps to on `on` (the key itself when it has no alias yet)."""
    return lf.resolve(con, key, on)


def symbol_of(con, key: str) -> Optional[str]:
    r = con.execute("SELECT symbol FROM instruments WHERE isin=?", [key]).fetchone()
    if r and r[0]:
        return r[0]
    return key[len(SYMBOL_PREFIX):] if key.startswith(SYMBOL_PREFIX) else None
