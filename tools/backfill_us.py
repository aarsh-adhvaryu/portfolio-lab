"""Backfill the US sleeve's price history: SPY, QQQ, the 11 SPDR sector funds, the current S&P 500 members and his US names.

    .venv\\Scripts\\python tools\\backfill_us.py [--no-sp500]

About 520 symbols, half a second each: more than 5 minutes (the investor's). Safe to stop and start again (a download shorter than
its file is refused; files already complete are rewritten whole). With the S&P 500 list it needs SEC's company list for the
pseudo-ISINs: if SEC refuses (it wants a real contact; see data/sec_edgar.py), the panel keeps the symbol-based keys and says so.
Output: data\\us\\raw\\*.parquet and data\\us\\prices.parquet.
"""
import argparse

from pflab.data import data_dir, us_prices
from pflab.pm import store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sp500", action="store_true")
    a = ap.parse_args()
    root = data_dir()
    syms = us_prices.universe(store.pm_dir(), with_sp500=not a.no_sp500)
    print(f"{len(syms)} symbols", flush=True)
    done = 0
    for k in range(0, len(syms), 25):
        out = us_prices.collect(syms[k:k + 25], root)
        done += len(out)
        bad = {s: v for s, v in out.items() if isinstance(v, str)}
        print(f"{done}/{len(syms)}" + (f"  problems: {bad}" if bad else ""), flush=True)
    ciks = {}
    try:
        ciks = us_prices.cik_map()
    except Exception as e:
        print(f"no CIKs ({type(e).__name__}: {str(e)[:120]}): the panel uses symbol-based keys until SEC answers", flush=True)
    p = us_prices.build_panel(root, ciks)
    print(f"panel: {len(p):,} rows, {p['symbol'].nunique()} symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
