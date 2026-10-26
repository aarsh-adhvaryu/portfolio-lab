"""NSE F&O bhavcopy at month-end sessions: futures only (S39 pairs study).

Two facts the pairs study needs, both point-in-time:
1. **Which stocks could be shorted overnight.** Cash shares cannot be held short past the day; a short leg
   needs a stock future (or SLB, rarely liquid). A stock with a FUTSTK contract in the month-end file was
   F&O-eligible that day.
2. **What a futures short earns.** A short future gains the futures premium over spot as it converges.
   `carry` turns each near-month stock future's premium into an annual rate and takes the median across
   stocks: the market's own cost-of-carry, used for the short leg and as the cash rate (no Indian short-rate
   series is on FRED any more).

Same archive as the equity bhavcopy (`data.bhavcopy`), same format switch on 2024-07-08:
    old  content/historical/DERIVATIVES/{yyyy}/{MON}/fo{dd}{MON}{yyyy}bhav.csv.zip
    new  content/fo/BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip  (UDiFF)
Options rows are dropped on read. Output: data/fo_bhavcopy/{yyyy-mm-dd}.parquet with
date, symbol, kind ('stock' | 'index'), expiry, close, settle, oi, contracts; raw zips under raw/fo_bhavcopy.
Symbols are as of the file's date: join to ISINs with the date (CLAUDE.md rule 4).
"""
from __future__ import annotations

import io
import time
import zipfile
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests

from pflab.data import data_dir
from pflab.data.bhavcopy import FORMAT_SWITCH, HEADERS

OLD_URL = "https://archives.nseindia.com/content/historical/DERIVATIVES/{yyyy}/{MON}/fo{dd}{MON}{yyyy}bhav.csv.zip"
NEW_URL = "https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip"
COLUMNS = ["date", "symbol", "kind", "expiry", "close", "settle", "oi", "contracts"]
_OLD_KIND = {"FUTSTK": "stock", "FUTIDX": "index"}
_NEW_KIND = {"STF": "stock", "IDF": "index"}


def urls_for(d: date):
    old = OLD_URL.format(yyyy=d.year, MON=d.strftime("%b").upper(), dd=d.strftime("%d"))
    new = NEW_URL.format(yyyymmdd=d.strftime("%Y%m%d"))
    return (new, old) if d >= FORMAT_SWITCH else (old, new)


def normalize(raw: bytes, session_date: date) -> pd.DataFrame:
    """Futures rows of one F&O bhavcopy (zip or csv bytes), either format."""
    if raw[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = [c.strip() for c in df.columns]
    if "INSTRUMENT" in df.columns:
        df = df[df["INSTRUMENT"].str.strip().isin(_OLD_KIND)]
        out = pd.DataFrame({"symbol": df["SYMBOL"].str.strip(), "kind": df["INSTRUMENT"].str.strip().map(_OLD_KIND),
                            "expiry": pd.to_datetime(df["EXPIRY_DT"].str.strip(), format="%d-%b-%Y").dt.date,
                            "close": df["CLOSE"], "settle": df["SETTLE_PR"], "oi": df["OPEN_INT"],
                            "contracts": df["CONTRACTS"]})
    elif "FinInstrmTp" in df.columns:
        df = df[df["FinInstrmTp"].str.strip().isin(_NEW_KIND)]
        out = pd.DataFrame({"symbol": df["TckrSymb"].str.strip(), "kind": df["FinInstrmTp"].str.strip().map(_NEW_KIND),
                            "expiry": pd.to_datetime(df["XpryDt"]).dt.date, "close": df["ClsPric"],
                            "settle": df["SttlmPric"], "oi": df["OpnIntrst"], "contracts": df["TtlTradgVol"]})
    else:
        raise ValueError(f"unrecognised F&O bhavcopy columns: {list(df.columns)[:6]}")
    out.insert(0, "date", session_date)
    for c in ("close", "settle", "oi", "contracts"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out[COLUMNS].reset_index(drop=True)


def _path(d: date, root: Path) -> Path:
    return root / "fo_bhavcopy" / f"{d.isoformat()}.parquet"


def fetch_day(d: date, session: requests.Session, root: Optional[Path] = None, timeout: int = 30) -> Optional[Path]:
    """Download one session's futures rows; None when both URL patterns 404. Idempotent."""
    root = root or data_dir()
    p = _path(d, root)
    if p.exists():
        return p
    for url in urls_for(d):
        r = session.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200 and r.content:
            raw_p = root / "raw" / "fo_bhavcopy" / f"{d.isoformat()}.zip"
            raw_p.parent.mkdir(parents=True, exist_ok=True)
            raw_p.write_bytes(r.content)
            p.parent.mkdir(parents=True, exist_ok=True)
            normalize(r.content, d).to_parquet(p, index=False)
            return p
    return None


def month_end_sessions(start: date, end: date, root: Optional[Path] = None) -> list:
    """Last trading session of each month, from the equity price panel (an exchange calendar fact)."""
    from pflab import _duck
    root = root or data_dir()
    q = (f"select max(date) d from '{root}/panel/prices.parquet' where date between DATE '{start}' and DATE '{end}' "
         f"group by date_trunc('month', date) order by d")
    return [r[0] for r in _duck.sql(q).fetchall()]


def collect(dates: Iterable[date], root: Optional[Path] = None, sleep: float = 0.7) -> dict:
    root = root or data_dir()
    s = requests.Session()
    try:
        s.get("https://www.nseindia.com/", headers=HEADERS, timeout=30)
    except Exception:
        pass
    stats = {"ok": 0, "missing": [], "error": []}
    for d in dates:
        try:
            if _path(d, root).exists() or fetch_day(d, s, root):
                stats["ok"] += 1
            else:
                stats["missing"].append(str(d))
        except Exception as e:                      # keep going; report it
            stats["error"].append(f"{d}: {e!r}")
        time.sleep(sleep)
    return stats


def load(root: Optional[Path] = None) -> pd.DataFrame:
    root = root or data_dir()
    files = sorted((root / "fo_bhavcopy").glob("*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame(columns=COLUMNS)


def eligible(fo: pd.DataFrame) -> pd.DataFrame:
    """(date, symbol) pairs with a stock future that day: the stocks that could be shorted overnight."""
    return fo.loc[fo["kind"] == "stock", ["date", "symbol"]].drop_duplicates().reset_index(drop=True)


def carry(fo: pd.DataFrame, spot: pd.DataFrame, min_days: int = 5) -> pd.Series:
    """Median annualised premium of near-month stock futures over spot, per date (simple rate, 365 days).

    `spot`: date, symbol, close (the equity close the same day). The near month is the first expiry at least
    `min_days` calendar days away (a contract about to expire carries almost no premium and a noisy one)."""
    f = fo[fo["kind"] == "stock"].copy()
    f["days"] = (pd.to_datetime(f["expiry"]) - pd.to_datetime(f["date"])).dt.days
    f = f[f["days"] >= min_days].sort_values("days").drop_duplicates(["date", "symbol"])
    s = spot[["date", "symbol", "close"]].rename(columns={"close": "spot"})
    f = f.merge(s.assign(date=pd.to_datetime(s["date"]).dt.date), on=["date", "symbol"])
    f = f[(f["spot"] > 0) & (f["close"] > 0)]
    f["rate"] = (f["close"] / f["spot"] - 1) * 365 / f["days"]
    return f.groupby("date")["rate"].median().rename("carry").astype(float)
