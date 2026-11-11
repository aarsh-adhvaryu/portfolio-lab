"""The A62 floor for a US pick (S83, his decision 2026-11-10): a stock the picks sleeve may hold has a price of at least USD 5 and a median daily traded value of at least USD 2 million over its
last 60 sessions, from the daily bars in `data/us/raw` (`us/data.py`). Point in time: only bars dated on or before the decision day. Code only; no network.

    check(con, symbol, day)   -> {"ok", "reason", "price", "median_value_usd", "sessions", "last_bar"}   (the picks agent calls this)
    tradable_note(symbol)     -> "assumed tradable, checked before Phase C", or what Zerodha's published GIFT City list says when a file of it is found under `data/us/`

The traded value of a day is close x volume (Yahoo's volume is the consolidated tape's). A name with fewer than 60 sessions of bars, or whose last bar is more than 10 days old, does not clear
the floor: it is not known to be liquid.
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Set, Tuple

import pandas as pd

MIN_PRICE = 5.0
MIN_MEDIAN_VALUE = 2_000_000.0
SESSIONS = 60
STALE_DAYS = 10
ASSUMED = "assumed tradable, checked before Phase C"


def _day(day) -> date:
    return day.date() if hasattr(day, "date") and callable(day.date) else day


def check(con, symbol: str, day, root=None) -> dict:
    """The floor for `symbol` on `day`: {"ok", "reason", "price", "median_value_usd", "sessions", "last_bar", "symbol"}. `con` is accepted for the picks agent's call shape (the floor reads the bars, not the store)."""
    from pflab.us import data as usdata
    sym = (symbol or "").strip().upper().replace(".", "-")
    return floor_from_bars(sym, usdata.bars(sym, root) if sym else None, day)


def floor_from_bars(sym: str, df, day, max_age_days: Optional[int] = STALE_DAYS) -> dict:
    """The floor on bars already read (`us/data.bars` layout: `date` as datetime.date, close, volume). Only bars dated on or before `day` count."""
    day = _day(day)
    out = {"ok": False, "reason": "", "price": None, "median_value_usd": None, "sessions": 0, "last_bar": None, "symbol": sym}
    if df is None or df.empty:
        out["reason"] = f"no daily bars for {sym or 'the name'} under data/us (they must be downloaded first)"
        return out
    df = df[df["date"] <= day]
    if df.empty:
        out["reason"] = f"{sym} has no bar on or before {day}"
        return out
    last = df.iloc[-1]
    out["last_bar"] = str(last["date"])
    out["price"] = float(last["close"])
    win = df.tail(SESSIONS)
    vol = win["volume"].fillna(0.0) if "volume" in win.columns else pd.Series([0.0] * len(win), index=win.index)
    out["sessions"] = int(len(win))
    out["median_value_usd"] = float((win["close"] * vol).median())
    problems = []
    if max_age_days is not None and (day - last["date"]).days > max_age_days:
        problems.append(f"its last bar is {last['date']}, more than {max_age_days} days before {day}")
    if out["price"] < MIN_PRICE:
        problems.append(f"price USD {out['price']:.2f} is under the USD {MIN_PRICE:g} floor")
    if len(win) < SESSIONS:
        problems.append(f"only {len(win)} sessions of bars ({SESSIONS} needed to know its traded value)")
    if out["median_value_usd"] < MIN_MEDIAN_VALUE:
        problems.append(f"median daily traded value USD {out['median_value_usd'] / 1e6:.2f} million is under the USD {MIN_MEDIAN_VALUE / 1e6:g} million floor")
    out["ok"] = not problems
    out["reason"] = ("; ".join(problems) if problems else
                     f"price USD {out['price']:.2f} and median daily traded value USD {out['median_value_usd'] / 1e6:.1f} million over {len(win)} sessions: clears the floor")
    return out


# --- the GIFT City list ------------------------------------------------------------------------------------------------------------

_TOKEN = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")


def _list_files(root=None) -> list:
    from pflab.data import data_dir
    base = Path(root or data_dir()) / "us"
    if not base.exists():
        return []
    return sorted(p for p in base.iterdir() if p.is_file() and "gift" in p.name.lower() and p.suffix.lower() in (".csv", ".txt", ".json", ".xlsx", ".xls"))


def gift_list(root=None) -> Tuple[Optional[Path], Set[str]]:
    """(the file, the symbols in it) of Zerodha's published GIFT City US-stock list when one sits under `data/us/` (a file with 'gift' in its name: csv, txt, json or xlsx); else (None, {})."""
    for p in _list_files(root):
        try:
            if p.suffix.lower() in (".xlsx", ".xls"):
                cells = [str(v) for v in pd.read_excel(p, header=None).to_numpy().ravel()]
            else:
                cells = re.split(r"[\s,;|\"'\[\]{}:]+", p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        syms = {t for c in cells for t in _TOKEN.findall(str(c).strip().upper()) if _TOKEN.fullmatch(t)}
        if syms:
            return p, syms
    return None, set()


def tradable_note(symbol: str, root=None) -> str:
    """Whether the GIFT City route can trade `symbol`: Zerodha's list when a file of it is found, else the stated assumption."""
    p, syms = gift_list(root)
    if p is None:
        return ASSUMED
    sym = (symbol or "").strip().upper().replace("-", ".")
    if sym in syms or sym.replace(".", "-") in syms:
        return f"on Zerodha's GIFT City list ({p.name})"
    return f"NOT on Zerodha's GIFT City list ({p.name}): not tradable by that route"


def on_list(symbol: str, root=None) -> Optional[bool]:
    """True / False when a list file is found, None when there is none (then the name is only assumed tradable)."""
    p, syms = gift_list(root)
    if p is None:
        return None
    sym = (symbol or "").strip().upper()
    return sym in syms or sym.replace("-", ".") in syms
