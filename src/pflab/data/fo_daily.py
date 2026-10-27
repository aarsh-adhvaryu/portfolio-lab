"""NSE F&O daily: futures AND options rows, and the participant-wise open interest file (S64 Phase 5 item 7).

Information for the investor and the brain (open interest, put-call ratio, futures premium, implied volatility, max pain,
build-up class). The month-end futures-only files of `fo_bhavcopy` (the pairs study's carry and eligibility) stay as they are;
this module keeps every session. No signal comes from any of it unless a later registered test passes.

    UDiFF (from 2024-07-08)   content/fo/BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip
    old format                content/historical/DERIVATIVES/{yyyy}/{MON}/fo{dd}{MON}{yyyy}bhav.csv.zip
    participants              content/nsccl/fao_participant_oi_{ddmmyyyy}.csv  (client, DII, FII, Pro; contracts)
Output: data/fo_daily/{date}.parquet and data/fo_participant/{date}.parquet; raw files under data/raw.
"""
from __future__ import annotations

import io
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests

from pflab.data import data_dir
from pflab.data.bhavcopy import FORMAT_SWITCH, HEADERS

COLUMNS = ["date", "symbol", "instrument", "kind", "expiry", "option", "strike", "close", "settle", "prev_close", "underlying",
           "oi", "oi_change", "contracts", "lot"]
PARTICIPANT_URL = "https://archives.nseindia.com/content/nsccl/fao_participant_oi_{ddmmyyyy}.csv"
NEW_URL = "https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip"
OLD_URL = "https://archives.nseindia.com/content/historical/DERIVATIVES/{yyyy}/{MON}/fo{dd}{MON}{yyyy}bhav.csv.zip"
_NEW = {"STF": ("FUT", "stock"), "IDF": ("FUT", "index"), "STO": ("OPT", "stock"), "IDO": ("OPT", "index")}
_OLD = {"FUTSTK": ("FUT", "stock"), "FUTIDX": ("FUT", "index"), "OPTSTK": ("OPT", "stock"), "OPTIDX": ("OPT", "index")}


def _read(raw: bytes) -> pd.DataFrame:
    if raw[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = [c.strip() for c in df.columns]
    return df


def normalize(raw: bytes, session_date: date) -> pd.DataFrame:
    """Every futures and options row of one session's file, either format, in one layout."""
    df = _read(raw)
    if "FinInstrmTp" in df.columns:
        df = df[df["FinInstrmTp"].str.strip().isin(_NEW)]
        tp = df["FinInstrmTp"].str.strip().map(_NEW)
        out = pd.DataFrame({
            "symbol": df["TckrSymb"].str.strip(), "instrument": tp.map(lambda t: t[0]), "kind": tp.map(lambda t: t[1]),
            "expiry": pd.to_datetime(df["XpryDt"]).dt.date, "option": df["OptnTp"].astype("string").str.strip(),
            "strike": df["StrkPric"], "close": df["ClsPric"], "settle": df["SttlmPric"], "prev_close": df["PrvsClsgPric"],
            "underlying": df["UndrlygPric"], "oi": df["OpnIntrst"], "oi_change": df["ChngInOpnIntrst"],
            "contracts": df["TtlTradgVol"], "lot": df.get("NewBrdLotQty")})
    elif "INSTRUMENT" in df.columns:
        df = df[df["INSTRUMENT"].str.strip().isin(_OLD)]
        tp = df["INSTRUMENT"].str.strip().map(_OLD)
        out = pd.DataFrame({
            "symbol": df["SYMBOL"].str.strip(), "instrument": tp.map(lambda t: t[0]), "kind": tp.map(lambda t: t[1]),
            "expiry": pd.to_datetime(df["EXPIRY_DT"].str.strip(), format="%d-%b-%Y").dt.date,
            "option": df["OPTION_TYP"].astype("string").str.strip().replace("XX", pd.NA), "strike": df["STRIKE_PR"],
            "close": df["CLOSE"], "settle": df["SETTLE_PR"], "prev_close": float("nan"), "underlying": float("nan"),
            "oi": df["OPEN_INT"], "oi_change": df["CHG_IN_OI"], "contracts": df["CONTRACTS"], "lot": float("nan")})
    else:
        raise ValueError(f"unrecognised F&O bhavcopy columns: {list(df.columns)[:6]}")
    out.insert(0, "date", session_date)
    out.loc[out["instrument"] == "FUT", ["option", "strike"]] = [pd.NA, float("nan")]
    for c in ("strike", "close", "settle", "prev_close", "underlying", "oi", "oi_change", "contracts", "lot"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["option"] = out["option"].astype(object).where(out["option"].notna(), None)
    return out[COLUMNS].reset_index(drop=True)


def normalize_participants(text: str, session_date: date) -> pd.DataFrame:
    """The participant-wise open interest table: one row per client type (Client, DII, FII, Pro) and column of the file."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    head = next(i for i, ln in enumerate(lines) if ln.lower().startswith("client type"))
    df = pd.read_csv(io.StringIO("\n".join(lines[head:])))
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={"Client Type": "participant"})
    df["participant"] = df["participant"].astype(str).str.strip()
    df = df[df["participant"].isin(["Client", "DII", "FII", "Pro"])]
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.insert(0, "date", session_date)
    return df.reset_index(drop=True)


def urls_for(d: date):
    old = OLD_URL.format(yyyy=d.year, MON=d.strftime("%b").upper(), dd=d.strftime("%d"))
    new = NEW_URL.format(yyyymmdd=d.strftime("%Y%m%d"))
    return (new, old) if d >= FORMAT_SWITCH else (old, new)


def path(d: date, root: Optional[Path] = None) -> Path:
    return (root or data_dir()) / "fo_daily" / f"{d.isoformat()}.parquet"


def participant_path(d: date, root: Optional[Path] = None) -> Path:
    return (root or data_dir()) / "fo_participant" / f"{d.isoformat()}.parquet"


def fetch_day(d: date, session: requests.Session, root: Optional[Path] = None, timeout: int = 40) -> Optional[Path]:
    """One session's file; None when both URL patterns have nothing (a holiday). Idempotent."""
    root = root or data_dir()
    p = path(d, root)
    if p.exists():
        return p
    for url in urls_for(d):
        r = session.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200 and r.content:
            raw_p = root / "raw" / "fo_daily" / f"{d.isoformat()}.zip"
            raw_p.parent.mkdir(parents=True, exist_ok=True)
            raw_p.write_bytes(r.content)
            p.parent.mkdir(parents=True, exist_ok=True)
            normalize(r.content, d).to_parquet(p, index=False)
            return p
    return None


def fetch_participants(d: date, session: requests.Session, root: Optional[Path] = None, timeout: int = 40) -> Optional[Path]:
    root = root or data_dir()
    p = participant_path(d, root)
    if p.exists():
        return p
    r = session.get(PARTICIPANT_URL.format(ddmmyyyy=d.strftime("%d%m%Y")), headers=HEADERS, timeout=timeout)
    if r.status_code != 200 or b"Client Type" not in r.content[:2000]:
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    normalize_participants(r.text, d).to_parquet(p, index=False)
    return p


def collect(start: date, end: date, root: Optional[Path] = None, sleep: float = 0.6, with_participants: bool = True) -> dict:
    """Every weekday from start to end that has no file yet. A date with nothing (holiday, not yet published) is counted as
    missing, not as an error; the next run tries it again."""
    root = root or data_dir()
    s = requests.Session()
    try:
        s.get("https://www.nseindia.com/", headers=HEADERS, timeout=30)
    except Exception:
        pass
    stats = {"ok": 0, "have": 0, "missing": [], "error": [], "participants": 0}
    d = start
    while d <= end:
        if d.weekday() < 5:
            try:
                if path(d, root).exists():
                    stats["have"] += 1
                elif fetch_day(d, s, root):
                    stats["ok"] += 1
                    time.sleep(sleep)
                else:
                    stats["missing"].append(str(d))
                if with_participants and not participant_path(d, root).exists() and fetch_participants(d, s, root):
                    stats["participants"] += 1
                    time.sleep(sleep)
            except Exception as e:
                stats["error"].append(f"{d}: {e!r}")
        d += timedelta(days=1)
    return stats


def load_day(d: date, root: Optional[Path] = None) -> Optional[pd.DataFrame]:
    p = path(d, root)
    return pd.read_parquet(p) if p.exists() else None


def sessions(root: Optional[Path] = None) -> list:
    return sorted(date.fromisoformat(f.stem) for f in ((root or data_dir()) / "fo_daily").glob("*.parquet"))
