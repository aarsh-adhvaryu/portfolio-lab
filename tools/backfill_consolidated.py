"""Store the consolidated integrated filings (BSE, 2025 on) of every stock-list company once (safety amendment 2,
2026-10-18); the guards keep them current afterwards. Dated by filing time; nothing after today is stored.

    .venv\\Scripts\\python tools\\backfill_consolidated.py
"""
import sys
from datetime import date

from pflab.fundamentals import integrated, pit
from pflab.plan import guards as gd
from pflab.pm import store


def main() -> int:
    con = store.connect()
    for s in gd.stock_list():
        if not s.get("scrip"):
            continue
        have = set(pit.load(con, s["scrip"], "consolidated")["quarter_end"])
        f = integrated.fetch_quarters(s["scrip"], basis="Consolidated")
        f = f[(~f["quarter_end"].isin(have)) & (f["usable_from"] <= date.today())]
        n = pit.save(con, f, "bse_filing", basis="consolidated") if len(f) else 0
        print(f"{s['symbol']:<12} {n} consolidated quarter(s) stored; {len(have) + n} on record")
    return 0


if __name__ == "__main__":
    sys.exit(main())
