"""FII / DII daily cash-market flows (provisional), and the S79b data manifest.

Sources, read 2026-11-08 (public, no key, nothing sent out):

  * NSE `https://www.nseindia.com/api/fiidiiTradeReact` -- the provisional figures for the LATEST session only (FII/FPI and
    DII, buy / sell / net in Rs crore, NSE + BSE + MSEI together). It needs the cookies a normal page visit sets.
  * Groww `https://groww.in/fii-dii-data` -- the page embeds the last 20 sessions (`__NEXT_DATA__` JSON, `initialData`),
    figures identical to NSE's react feed (checked on 2026-11-06: FII net +13,749.82 and DII net -5,968.70 in both).
    This is the only free source found that works unattended and carries a history; NSE's own history endpoint answers
    503 (probed 2026-11-08), Moneycontrol answers 403, NSDL's archive (`data.fpi_flows`) holds FPI only (no DII).
    A session older than the 20 the page holds cannot be filled from here: the file grows from today on by merging.

Point-in-time: the row dated D is the provisional figure for session D, published by NSE after the close (about 18:00-19:00
IST); a decision at D's close may not read it, a decision at D+1 may. Provisional figures are revised a little later; a
re-read of the same date overwrites (keep="last").

Output: data/flows/FII_DII_CASH.parquet -- date, fii_buy_cr, fii_sell_cr, fii_net_cr, dii_buy_cr, dii_sell_cr, dii_net_cr,
source, fetched_at.

Manifest: `record_manifest` merges into `data/_s79b_manifest.json` (name, source URL, first/last date, rows, fetched_at),
written progressively so other agents can see what exists.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NSE_HOME = "https://www.nseindia.com/"
NSE_PAGE = "https://www.nseindia.com/reports/fii-dii"
NSE_REACT = "https://www.nseindia.com/api/fiidiiTradeReact"
GROWW = "https://groww.in/fii-dii-data"
COLS = ["date", "fii_buy_cr", "fii_sell_cr", "fii_net_cr", "dii_buy_cr", "dii_sell_cr", "dii_net_cr", "source", "fetched_at"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_nse(rows: list, source: str = "nse_react") -> pd.DataFrame:
    """NSE's list of {category, date 'dd-Mon-yyyy', buyValue, sellValue, netValue} (strings) into one row per date."""
    by: dict = {}
    for r in rows or []:
        d = datetime.strptime(r["date"], "%d-%b-%Y").date()
        side = "fii" if str(r["category"]).upper().startswith("FII") else "dii"
        x = by.setdefault(d, {"date": d})
        x[f"{side}_buy_cr"], x[f"{side}_sell_cr"], x[f"{side}_net_cr"] = (float(r["buyValue"]), float(r["sellValue"]), float(r["netValue"]))
    df = pd.DataFrame(list(by.values()))
    if df.empty:
        return pd.DataFrame(columns=COLS)
    df["source"], df["fetched_at"] = source, _now()
    return df[COLS]


def parse_groww(html: str) -> pd.DataFrame:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("no __NEXT_DATA__ on the page")
    data = json.loads(m.group(1))["props"]["pageProps"]["initialData"]
    rows = [{"date": datetime.strptime(x["date"], "%Y-%m-%d").date(),
             "fii_buy_cr": float(x["fii"]["grossBuy"]), "fii_sell_cr": float(x["fii"]["grossSell"]), "fii_net_cr": float(x["fii"]["netBuySell"]),
             "dii_buy_cr": float(x["dii"]["grossBuy"]), "dii_sell_cr": float(x["dii"]["grossSell"]), "dii_net_cr": float(x["dii"]["netBuySell"])}
            for x in data]
    df = pd.DataFrame(rows)
    df["source"], df["fetched_at"] = "groww_page", _now()
    return df[COLS]


def fetch_nse_latest(pause: float = 1.0, timeout: int = 30) -> pd.DataFrame:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
    s.get(NSE_HOME, timeout=timeout)
    time.sleep(pause)
    s.get(NSE_PAGE, timeout=timeout)
    time.sleep(pause)
    s.headers["Referer"] = NSE_PAGE
    r = s.get(NSE_REACT, timeout=timeout)
    r.raise_for_status()
    return parse_nse(r.json(), "nse_react")


def fetch_groww(timeout: int = 40) -> pd.DataFrame:
    r = requests.get(GROWW, headers={"User-Agent": UA, "Accept": "text/html,*/*", "Accept-Language": "en-US,en;q=0.9"}, timeout=timeout)
    r.raise_for_status()
    return parse_groww(r.text)


def merge(old: Optional[pd.DataFrame], *new: pd.DataFrame, today: Optional[date] = None) -> pd.DataFrame:
    """Dedupe on date (the later argument wins), drop any future date, sorted."""
    parts = ([old] if old is not None and len(old) else []) + [n for n in new if n is not None and len(n)]
    if not parts:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[df["date"] <= (today or date.today())]
    return df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def collect(root: Optional[Path] = None, get_nse=None, get_groww=None, today: Optional[date] = None) -> dict:
    """Read both sources (a failing one is reported, not fatal), merge into the stored file. NSE wins on its day."""
    root = Path(root or data_dir())
    p = root / "flows" / "FII_DII_CASH.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_parquet(p) if p.exists() else None
    out, got = {}, []
    for name, fn in (("groww", get_groww or fetch_groww), ("nse", get_nse or fetch_nse_latest)):   # later wins: NSE over Groww
        try:
            df = fn()
            got.append(df)
            out[name] = (len(df), str(df["date"].min()), str(df["date"].max()))
        except Exception as e:
            out[name] = repr(e)[:160]
    if not got:
        return {"error": "no source answered", **out}
    df = merge(old, *got, today=today)
    df.to_parquet(p, index=False)
    out["rows"], out["last"] = len(df), str(df["date"].max())
    return out


def load(root: Optional[Path] = None) -> pd.DataFrame:
    return pd.read_parquet(Path(root or data_dir()) / "flows" / "FII_DII_CASH.parquet")


def record_manifest(entries: list, root: Optional[Path] = None) -> Path:
    """Merge entries [{name, source, first, last, rows, note?}] into data/_s79b_manifest.json (by name); fetched_at is stamped now."""
    root = Path(root or data_dir())
    p = root / "_s79b_manifest.json"
    cur = {}
    if p.exists():
        try:
            cur = {x["name"]: x for x in json.loads(p.read_text(encoding="utf-8")).get("series", [])}
        except Exception:
            cur = {}
    for e in entries:
        e = dict(e)
        e["fetched_at"] = e.get("fetched_at") or _now()
        for k in ("first", "last"):
            if e.get(k) is not None:
                e[k] = str(e[k])
        cur[e["name"]] = e
    p.write_text(json.dumps({"written_at": _now(), "series": sorted(cur.values(), key=lambda x: x["name"])}, indent=1, default=str), encoding="utf-8")
    return p
