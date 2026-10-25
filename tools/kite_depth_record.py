"""Record five-level market depth from Kite for the order book simulator (S41). The investor runs this; nothing
schedules it.

    python tools/kite_depth_record.py [--minutes 60] [--interval 5] [--symbols WIDGETCO TCS ...] [--check] [--wait-open]

Needs today's Kite login (`python tools/kite_login.py`). Without --symbols it records the names on
PFLAB_PM_DIR/stock_list.toml. Read-only: it only calls quote(). Writes data/kite_depth/{date}.parquet; stops by
itself after --minutes, or at 15:30 IST, whichever is first.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from datetime import time as clock

from pflab.ingest import kite, kite_depth
from pflab.plan import guards
from pflab.pm import secrets

OPEN, CLOSE = clock(9, 15), clock(15, 30)


def target_etfs() -> list:
    """Exchange-traded buy candidates in the targets (ETFs; index funds are bought at NAV and have no book)."""
    try:
        from pflab.plan import targets as tg
        from pflab.pm import store
        con = store.connect(read_only=True)
        isins = [isin for x in tg.load().buckets.values() for isin, _ in x.buy]
        rows = [con.execute("SELECT symbol, asset_class FROM instruments WHERE isin = ?", [i]).fetchone() for i in isins]
        return [r[0] for r in rows if r and r[0] and r[1] != "mutual_fund"]
    except Exception:                                   # no targets yet: the stock list alone
        return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--minutes", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=5.0, help="seconds between snapshots (quote API allows 1/s)")
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--check", action="store_true",
                    help="one quote() call now (works when the market is closed), print what came back, save nothing")
    ap.add_argument("--wait-open", action="store_true", help="started before 09:15 on a weekday: wait for the open")
    a = ap.parse_args(argv)
    k = kite.client(secrets.load())
    if k is None:
        print("no valid Kite token today: run python tools/kite_login.py first (tokens lapse at about 06:00)")
        return 1
    syms = a.symbols or [s["symbol"] for s in guards.stock_list()] + target_etfs()
    inst = [f"NSE:{s.upper()}" for s in syms]
    if a.check:
        rows = kite_depth.rows_from_quote(k.quote(inst), datetime.now())
        missing = sorted(set(inst) - set(rows["instrument"]))
        for r in rows.itertuples():
            print(f"  {r.instrument:<18} last {r.last_price}  best bid {r.buy_px1} x {r.buy_qty1}  best ask {r.sell_px1} x {r.sell_qty1}")
        print(f"check: login ok, {len(rows)} of {len(inst)} instruments answered"
              + (f"; NOT FOUND: {', '.join(missing)}" if missing else "") + ". Nothing saved.")
        return 0 if not missing else 1
    now = datetime.now()
    if a.wait_open and now.weekday() < 5 and now.time() < OPEN:
        wait = (datetime.combine(now.date(), OPEN) - now).total_seconds()
        print(f"waiting {wait / 60:.0f} min for the 09:15 open")
        time.sleep(wait)
        now = datetime.now()
    if not (OPEN <= now.time() < CLOSE) or now.weekday() >= 5:
        print("market closed (09:15-15:30 IST on weekdays): nothing recorded")
        return 1
    left = (datetime.combine(now.date(), CLOSE) - now).total_seconds() / 60
    n = kite_depth.record(k, inst, min(a.minutes, left), a.interval)
    print(f"{n} snapshots of {len(inst)} instruments written to data/kite_depth/{now:%Y-%m-%d}.parquet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
