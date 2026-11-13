"""S86 H4: the US session loop against the REAL quote feed for a few ticks, on a scratch store and one public name (the workshop holds no personal record).
    python tools/us_session_live_s86.py --out <folder> --ticks 3 --every 5 [--symbol NVDA]
A stand-in position in the symbol is opened in a scratch sub-book, an exit plan's stop is set ABOVE the live price so it fires on the first tick; the order must fill on a LATER tick's quote (never the one
that triggered it). Prints each tick's quotes with their delay, the stop, the fill with its quote time and delay. Needs the US market to be in regular hours; otherwise it says so and stops."""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--ticks", type=int, default=3)
    ap.add_argument("--every", type=int, default=5)
    ap.add_argument("--symbol", default="NVDA")
    ap.add_argument("--isin", default="ZZ0001045810")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    os.environ["PFLAB_PM_DIR"] = str(out)
    from pflab.core import exits, us_session as uss
    from pflab.pm import store
    from pflab.us import book
    con = store.connect(out / "us_live.duckdb")
    now = datetime.now().replace(microsecond=0)
    ph, d, _w = uss.phase(now)
    print(now, "phase", ph)
    if ph != "regular":
        print("the US market is not in regular hours: nothing to measure now")
        return 0
    q0 = uss.fetch_quote(a.symbol, now)
    px = q0["price"]
    con.execute("INSERT INTO fx_rates VALUES (?, 'USDINR_FBIL', 90.0, 'scratch')", [d - timedelta(days=1)])
    con.execute("INSERT INTO paper_cash VALUES (?,?,?,?,?,?)", [store.next_id(con, "paper_cash", "entry_id"), d - timedelta(days=30), 1_000_000.0, "seed", "scratch cash", now])
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'FOREIGN', TRUE, ?, 'scratch stand-in', 'scratch', now())", [a.isin, a.symbol])
    book.open_account(con, now, d - timedelta(days=1), 200_000.0, {"rate": 90.0, "source": "FBIL", "rate_day": d - timedelta(days=1), "label": "scratch"}, 0.10)
    oid = book.place(con, now - timedelta(days=1), d - timedelta(days=1), a.isin, a.symbol, "buy", amount_usd=1000.0, reason="scratch stand-in position")
    book.fill_one(con, now - timedelta(days=1), d - timedelta(days=1), [o for o in book.open_orders(con) if o["order_id"] == oid][0], px, 0.0)
    exits._plans = lambda con_, market=None, *x, **k: [{"isin": a.isin, "stop": px * 1.05, "plan_id": 1}]            # a stop above the live price: it fires on the first tick
    uss.on = lambda: True
    uss.symbols_for = lambda con_, now_, root_: ["SPY", a.symbol]
    import pflab.think.watch as w
    w.run = lambda *x, **k: {"signals": [], "cases_opened": []}
    for k in range(a.ticks):
        t = datetime.now().replace(microsecond=0)
        r = uss.tick(con, t, out)
        print(t.time(), {x: r.get(x) for x in ("phase", "quotes", "median_delay_min", "stops", "fills", "problems")})
        for f in r.get("fills", []):
            print("   FILL", f)
        if k + 1 < a.ticks:
            time.sleep(a.every * 60)
    print("fills table:", con.execute("SELECT symbol, side, decision_ts, quote_ts, delay_min, quote_price, fill_price, est_bps FROM us_fills_s86").fetchall())
    print("delay report:", uss.delay_report(con, d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
