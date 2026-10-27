"""US prices for the US sleeve (S64 Phase 6 item 3): the Yahoo chart request already used for world markets, one file per symbol,
and a panel in the same column layout as the Indian one (data/panel.py PANEL_COLUMNS) keyed by the pseudo-ISIN.

    data/us/raw/{SYMBOL}.parquet   date, open, high, low, close (split-adjusted), adj_close (dividends in too), volume, dividend
    data/us/prices.parquet         PANEL_COLUMNS; isin = "ZZ" + CIK (ledger/foreign.py); series "US"; the exchange's local date

Universe: SPY, QQQ and the eleven SPDR sector funds always; the current S&P 500 members (the public list on Wikipedia, CIKs from
SEC's company_tickers.json) for backfills; and the names on his list or held (PFLAB_PM_DIR/us_list.toml). The S&P list is TODAY's:
a stock-level test on it would carry survivorship bias, so the learner tests only the ETFs (PLAN Phase 6 item 7).
Yahoo is not an official source; a download shorter than the file it would replace is refused (as for world markets).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd
import requests

from pflab.data import data_dir

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
ETFS = {"SPY": "SPDR S&P 500 ETF", "QQQ": "Invesco QQQ (Nasdaq 100)", "XLC": "Communication Services Select Sector SPDR",
        "XLY": "Consumer Discretionary Select Sector SPDR", "XLP": "Consumer Staples Select Sector SPDR",
        "XLE": "Energy Select Sector SPDR", "XLF": "Financial Select Sector SPDR", "XLV": "Health Care Select Sector SPDR",
        "XLI": "Industrial Select Sector SPDR", "XLB": "Materials Select Sector SPDR", "XLRE": "Real Estate Select Sector SPDR",
        "XLK": "Technology Select Sector SPDR", "XLU": "Utilities Select Sector SPDR"}
PANEL_COLUMNS = ["date", "isin", "symbol", "series", "instrument_type", "open", "high", "low", "close", "prev_close", "volume",
                 "turnover", "adj_factor", "adj_close", "adj_open", "dividend"]
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SP500_LIST = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch(sym: str, timeout: int = 60, start: Optional[int] = None) -> pd.DataFrame:
    """Daily bars with dividends, from `start` (a unix time) or the beginning."""
    j = requests.get(URL.format(sym=sym), params={"period1": start or 0, "period2": int(time.time()), "interval": "1d",
                                                  "events": "div|split"}, headers={"User-Agent": UA}, timeout=timeout).json()
    res = j["chart"]["result"][0]
    off = timedelta(seconds=res["meta"].get("gmtoffset", 0))
    day = lambda t: (datetime.fromtimestamp(t, timezone.utc) + off).date()                # noqa: E731
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    df = pd.DataFrame({"date": [day(t) for t in res["timestamp"]], "open": q["open"], "high": q["high"], "low": q["low"],
                       "close": q["close"], "adj_close": adj, "volume": q.get("volume")})
    divs = {day(int(t)): float(v["amount"]) for t, v in ((res.get("events") or {}).get("dividends") or {}).items()}
    df["dividend"] = df["date"].map(divs).fillna(0.0)
    df = df.dropna(subset=["close"])
    return df[df["close"] > 0].drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def collect(symbols: List[str], root: Optional[Path] = None, pause: float = 0.5, get: Optional[Callable] = None,
            recent_days: Optional[int] = None) -> Dict[str, object]:
    """Each symbol's file rewritten whole (or, with `recent_days`, only its last days appended); a failure is reported, not fatal."""
    root = root or data_dir()
    get = get or fetch
    out: Dict[str, object] = {}
    for sym in symbols:
        p = root / "us" / "raw" / f"{sym}.parquet"
        try:
            old = pd.read_parquet(p) if p.exists() else None
            if recent_days and old is not None:
                new = get(sym, start=int((datetime.now() - timedelta(days=recent_days)).timestamp()))
                df = pd.concat([old[~old["date"].isin(set(new["date"]))], new], ignore_index=True).sort_values("date")
            else:
                df = get(sym)
            if old is not None and (len(df) < len(old) or df["date"].max() < old["date"].max()):
                out[sym] = f"kept the file: download has {len(df)} rows to {df['date'].max()}, file {len(old)}"
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(p, index=False)
            out[sym] = (len(df), str(df["date"].min()), str(df["date"].max()))
        except Exception as e:
            out[sym] = repr(e)[:160]
        time.sleep(pause)
    return out


# --- the universe -------------------------------------------------------------------------------------------------------------

def cik_map(get: Optional[Callable] = None) -> Dict[str, int]:
    """ticker -> CIK from SEC's public company_tickers.json (needs the contact User-Agent; see data/sec_edgar.py)."""
    from pflab.data import sec_edgar
    j = (get or sec_edgar.get_json)(SEC_TICKERS)
    return {v["ticker"].upper(): int(v["cik_str"]) for v in j.values()}


def sp500_symbols(get_html: Optional[Callable] = None) -> List[str]:
    """Today's S&P 500 members from the public Wikipedia list (Yahoo style: BRK-B for BRK.B)."""
    html = (get_html or (lambda u: requests.get(u, headers={"User-Agent": UA}, timeout=60).text))(SP500_LIST)
    from io import StringIO
    t = pd.read_html(StringIO(html), match="Symbol")[0]
    return sorted({str(s).strip().replace(".", "-") for s in t["Symbol"] if isinstance(s, str)})


def my_names(pm_dir: Optional[Path]) -> List[str]:
    """His US list (PFLAB_PM_DIR/us_list.toml: symbols = [...]), and nothing else."""
    from pflab import _toml
    p = Path(pm_dir) / "us_list.toml" if pm_dir else None
    return [s.upper() for s in _toml.load(p).get("symbols", [])] if p and p.exists() else []


def universe(pm_dir: Optional[Path] = None, with_sp500: bool = False, get_html: Optional[Callable] = None) -> List[str]:
    syms = list(ETFS) + my_names(pm_dir)
    if with_sp500:
        syms += sp500_symbols(get_html)
    return list(dict.fromkeys(syms))


# --- the panel ----------------------------------------------------------------------------------------------------------------

def build_panel(root: Optional[Path] = None, ciks: Optional[Dict[str, int]] = None, write: bool = True) -> pd.DataFrame:
    """All raw files in the Indian panel's layout. A symbol with no known CIK (a fund) gets a pseudo-key from the symbol's
    own name so that it is still one stable key: 'ZZ' + 'F' fund marker is not used; a fund without a CIK keeps the symbol."""
    from pflab.ledger import foreign as lf
    root = root or data_dir()
    ciks = ciks or {}
    frames = []
    for p in sorted((root / "us" / "raw").glob("*.parquet")):
        sym = p.stem
        df = pd.read_parquet(p)
        key = lf.pseudo_isin(ciks[sym]) if sym in ciks else f"US:{sym}"
        df = df.assign(isin=key, symbol=sym, series="US", instrument_type="ETF" if sym in ETFS else "EQ")
        df["prev_close"] = df["close"].shift(1)
        df["turnover"] = df["close"] * df["volume"].fillna(0.0)
        df["adj_factor"] = df["adj_close"] / df["close"]
        df["adj_open"] = df["open"] * df["adj_factor"]
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=PANEL_COLUMNS)
    panel = pd.concat(frames, ignore_index=True)[PANEL_COLUMNS]
    if write:
        out = root / "us" / "prices.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(out, index=False)
    return panel


def load(root: Optional[Path] = None) -> pd.DataFrame:
    return pd.read_parquet((root or data_dir()) / "us" / "prices.parquet")
