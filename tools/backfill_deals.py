"""S48 data for arms 2 and 4 (docs/STUDIES.md): institutional holding per company and
quarter (BSE) and bulk / block deals per day (NSE), for the study windows only. Resumable; online.

    .venv\\Scripts\\python tools\\s48_collect.py --source deals          # ~1 h
    .venv\\Scripts\\python tools\\s48_collect.py --source institutions   # ~4 h
    .venv\\Scripts\\python tools\\s48_collect.py --smoke                 # a few requests into a scratch folder
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from pflab.data import bse_institutions as bi
from pflab.data import data_dir
from pflab.data import nse_deals as nd

# signals at month-ends 2016-06 .. 2021-09 and 2026-01 .. 2026-06 (holdout); deals look back 30 days
DEAL_WINDOWS = ((date(2016, 5, 1), date(2021, 9, 30)), (date(2025, 12, 1), date(2026, 6, 30)))
# the two latest filings usable at each signal month-end: Dec 2015 (88) .. Sep 2021 (111); Sep 2025 (127) .. Jun 2026
QTRIDS = list(range(88, 112)) + list(range(127, 131))
MEMBER_WINDOWS = (("2016-06-01", "2021-09-30"), ("2026-01-01", "2026-06-30"))


def scrips() -> list:
    """BSE scrip codes of every Nifty 500 member in the study windows (ISIN -> scrip by the dated map)."""
    root = data_dir()
    cond = " or ".join(f"(from_date <= DATE '{b}' and (to_date is null or to_date >= DATE '{a}'))" for a, b in MEMBER_WINDOWS)
    isins = duckdb.sql(f"select distinct isin from '{root / 'index_membership' / 'NIFTY500.parquet'}' where {cond}").df()["isin"]
    mp = duckdb.sql(f"select scrip_code, isin from '{root / 'bse_scrip_isin' / 'map.parquet'}' where isin like 'INE%'").df()
    return sorted(set(mp[mp["isin"].isin(set(isins))]["scrip_code"].astype(str)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", choices=["deals", "institutions", "both"], default="both")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args(argv)
    say = lambda s: print(s, flush=True)                     # noqa: E731
    if a.smoke:
        root = Path(tempfile.mkdtemp(prefix="s48_smoke_"))
        r1 = nd.collect(date(2017, 3, 1), date(2017, 3, 3), root=root, pause=0.6, log=say)
        d = nd.load(root)
        print("deals:", r1, "| rows by kind", d.groupby("kind").size().to_dict())
        sc = scrips()
        r2 = bi.collect(sc[:2], [100, 129], root=root, log=say)
        print("institutions:", r2, "| scrips in scope", len(sc))
        print(bi.load(root).to_string(index=False))
        print("SMOKE OK", root)
        return 0
    if a.source in ("deals", "both"):
        for s, e in DEAL_WINDOWS:
            say(f"deals {s} .. {e}: {nd.collect(s, e, log=say)}")
    if a.source in ("institutions", "both"):
        sc = scrips()
        say(f"institutions: {len(sc)} scrips x {len(QTRIDS)} quarters")
        say(f"institutions: {bi.collect(sc, QTRIDS, log=say)}")
    print("S48 COLLECT DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
