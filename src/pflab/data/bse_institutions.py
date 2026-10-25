"""Institutional holding per company and quarter from BSE's public-shareholder table (S48 arm 2).

Endpoint (found in BSE's own site code 2026-10-20): `Corp_shpSec_SHPPubShold_ng/w?scripcode=&qtrcode=<qtrid>.00`,
Table1 rows of SEBI's Table III. Institutional holding = the "Sub Total" rows of the institution categories, as a
percent of all shares (`Fld_TotalPercentageOf_A_B_C2`): one "Institutions" subtotal in the older format, "Institutions
(Domestic)" plus "Institutions (Foreign)" in the newer one. Mutual funds and foreign portfolio investors are kept too.
Dating is not here: a study takes the filing date from the shareholding summary (`bse_shareholding`).

File: data/bse_shareholding/institutions.parquet, one row per (scrip_code, qtrid); a stopped run resumes.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd

from pflab.data import data_dir
from pflab.data import bse_shareholding as bs

URL = "https://api.bseindia.com/BseIndiaAPI/api/Corp_shpSec_SHPPubShold_ng/w"
INSTITUTIONS = ("institutions", "institutions (domestic)", "institutions (foreign)")
COLUMNS = ["scrip_code", "qtrid", "quarter_end", "inst_pct", "mf_pct", "fpi_pct", "status"]
RETRY_WAITS = (3, 10, 30, 60, 120, 300, 300)              # ~14 min per request: rides out a mobile-hotspot drop


def parse(rows: list) -> dict:
    def pct(r):
        try:
            return float(r.get("Fld_TotalPercentageOf_A_B_C2") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    sub = [r for r in rows if str(r.get("Fld_Level") or "").startswith("Sub Total")
           and str(r.get("Fld_SubCategory") or "").strip().lower() in INSTITUTIONS]
    agg = [r for r in rows if not r.get("Fld_ShareHolderName")]
    mf = sum(pct(r) for r in agg if "mutual fund" in str(r.get("Fld_Level") or "").lower())
    fpi = sum(pct(r) for r in agg if "foreign portfolio" in str(r.get("Fld_Level") or "").lower())
    if not sub:
        return {"inst_pct": None, "mf_pct": None, "fpi_pct": None, "status": "no institution subtotal"}
    return {"inst_pct": sum(pct(r) for r in sub), "mf_pct": mf, "fpi_pct": fpi, "status": "ok"}


def fetch(get: Callable, scrip: str, qtrid: int) -> dict:
    from pflab.data.bse_announcements import HEADERS
    r = get(URL, params={"scripcode": scrip, "qtrcode": f"{int(qtrid)}.00"}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    j = r.json() if r.text.strip().startswith("{") else {}
    return {"scrip_code": str(scrip), "qtrid": int(qtrid), "quarter_end": bs.quarter_end(qtrid), **parse(j.get("Table1") or [])}


def path(root: Optional[Path] = None) -> Path:
    return (root or data_dir()) / "bse_shareholding" / "institutions.parquet"


def load(root: Optional[Path] = None) -> pd.DataFrame:
    p = path(root)
    return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=COLUMNS)


def collect(scrips: Iterable[str], qtrids: Iterable[int], root: Optional[Path] = None, get: Optional[Callable] = None,
            pause: float = 0.4, every: int = 200, log: Callable[[str], None] = print) -> dict:
    """Every (scrip, quarter) not yet on disk; saved every `every` answers, so a stop loses little."""
    import requests
    live = get is None
    get = get or requests.Session().get
    have = load(root)
    have = have[~have["status"].astype(str).str.startswith("error")]       # failed fetches are tried again
    done = set(zip(have["scrip_code"].astype(str), have["qtrid"].astype(int)))
    todo = [(str(s), int(q)) for s in scrips for q in qtrids if (str(s), int(q)) not in done]
    rows, n_ok = [], 0

    def flush():
        nonlocal rows
        if rows:
            df = pd.concat([load(root), pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True)
            df = df.drop_duplicates(["scrip_code", "qtrid"], keep="last")
            path(root).parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(path(root), index=False)
            rows = []
    waits = RETRY_WAITS if live else (0, 0, 0)
    for k, (s, q) in enumerate(todo, start=1):
        for attempt, w in enumerate(waits):
            try:
                row = fetch(get, s, q)
                break
            except Exception as e:                        # a dropped connection: wait, then try again
                row = {"scrip_code": s, "qtrid": q, "quarter_end": bs.quarter_end(q), "inst_pct": None, "mf_pct": None,
                       "fpi_pct": None, "status": f"error: {type(e).__name__}"}
                if attempt < len(waits) - 1:
                    if w >= 30:
                        log(f"{s} q{q}: {type(e).__name__}; waiting {w} s (connection?)")
                    time.sleep(w)
        rows.append(row)
        n_ok += row["status"] == "ok"
        if k % every == 0:
            flush()
            log(f"{k}/{len(todo)} done ({n_ok} with institutional rows)")
        time.sleep(pause)
    flush()
    return {"fetched": len(todo), "ok": n_ok, "already": len(done)}
