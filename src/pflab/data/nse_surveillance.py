"""NSE surveillance lists (ASM long/short term, GSM incl. IBC stages, ESM): daily snapshots and a buy verdict.

Endpoints verified 2026-10-15: https://www.nseindia.com/api/reportASM ({"longterm": {"data": [...]},
"shortterm": {...}}), /api/reportGSM and /api/reportESM (lists); a homepage visit first sets the cookies.
Snapshots are saved as data/surveillance/YYYY-MM-DD.parquet, so a point-in-time history builds up from the
first run (there is none before it).

Verdicts (what the exchange and Zerodha impose, support.zerodha.com "surveillance measures", 2026-10-15):
    block    insolvency (IBC) any stage; GSM stage II or higher (Zerodha blocks fresh buys: no ASD collected);
             long-term ASM stage IV and ESM stage II (trade-to-trade, 5% band)
    caution  any other listing (ASM I-III, short-term ASM, ESM I, GSM stage 0 / shortlisted)
    clear    not on any list
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import bhavcopy, data_dir

BASE = "https://www.nseindia.com/api/{}"
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}
COLUMNS = ["date", "list", "symbol", "isin", "code", "desc", "stage", "ibc", "verdict"]


def _stage(text: str) -> Optional[int]:
    m = re.search(r"(?:Stage|-)\s*([IVX]+)\b", text or "")
    return ROMAN.get(m.group(1)) if m else None


def verdict(lst: str, code: str, desc: str) -> str:
    """From the listing text alone (GSM rows also carry ESM/LTASM combinations)."""
    t = f"{code} {desc}".upper()
    if "IBC" in t or "INSOLVENCY" in t:
        return "block"
    if re.search(r"GRADED SURVEILLANCE MEASURE - STAGE (II|III|IV|V|VI|VII|VIII)\b", t) \
            or re.search(r"\bGSM - (II|III|IV|V|VI|VII|VIII)\b", t):
        return "block"
    if re.search(r"LTASM\)? - (STAGE )?IV\b", t) or re.search(r"LTASM STAGE IV\b", t):
        return "block"
    if re.search(r"ESM\)? - (STAGE )?II\b", t) or re.search(r"ESM STAGE II\b", t):
        return "block"
    return "caution"


def rows_from(asm: dict, gsm: list, esm: list, d: date) -> pd.DataFrame:
    out = []
    for key, lst in (("longterm", "LTASM"), ("shortterm", "STASM")):
        for x in (asm.get(key) or {}).get("data", []):
            out.append((lst, x))
    out += [("GSM", x) for x in gsm] + [("ESM", x) for x in esm]
    rows = [dict(date=d, list=lst, symbol=x.get("symbol"), isin=x.get("isin"), code=x.get("survCode", ""),
                 desc=x.get("survDesc", ""), stage=_stage(x.get("survDesc", "")) or _stage(x.get("survCode", "")),
                 ibc="IBC" in (x.get("survCode", "") + x.get("survDesc", "")).upper()
                     or "INSOLVENCY" in x.get("survDesc", "").upper(),
                 verdict=verdict(lst, x.get("survCode", ""), x.get("survDesc", ""))) for lst, x in out]
    return pd.DataFrame(rows, columns=COLUMNS)


def fetch(d: Optional[date] = None, session=None) -> pd.DataFrame:
    s = session or requests.Session()
    s.get("https://www.nseindia.com/", headers=bhavcopy.HEADERS, timeout=30)
    h = {**bhavcopy.HEADERS, "Accept": "application/json", "Referer": "https://www.nseindia.com/reports/asm"}
    get = lambda ep: s.get(BASE.format(ep), headers=h, timeout=30).json()
    return rows_from(get("reportASM"), get("reportGSM"), get("reportESM"), d or date.today())


def collect(start=None, end=None, root: Optional[Path] = None) -> dict:
    """Today's snapshot (the lists are current-only: past days cannot be fetched)."""
    root = root or data_dir()
    d = date.today()
    p = root / "surveillance" / f"{d.isoformat()}.parquet"
    if p.exists():
        return {"skipped": True}
    df = fetch(d)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    return {"rows": len(df), "block": int((df["verdict"] == "block").sum())}


def latest(asof: date, root: Optional[Path] = None) -> Optional[pd.DataFrame]:
    """The newest snapshot dated on or before `asof`, or None."""
    root = root or data_dir()
    files = sorted(p for p in (root / "surveillance").glob("*.parquet") if p.stem <= asof.isoformat())
    return pd.read_parquet(files[-1]) if files else None


def status(isin: str, snap: Optional[pd.DataFrame]) -> dict:
    if snap is None:
        return {"verdict": "unknown", "lists": [], "reason": "no surveillance snapshot on disk"}
    hit = snap[snap["isin"] == isin]
    if hit.empty:
        return {"verdict": "clear", "lists": [], "reason": ""}
    v = "block" if (hit["verdict"] == "block").any() else "caution"
    return {"verdict": v, "lists": hit["desc"].tolist(), "reason": "; ".join(hit["desc"])}
