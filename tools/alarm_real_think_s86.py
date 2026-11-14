"""S86: ONE real alarm through the real thinking step (paid, inside the workshop's cap): a headline of the Nvidia week on a scratch store, the lane's RED path with the real model. Measures the stretch
from first published to heard (Telegram queued) and to a decision, and the price. Public name only; nothing of the investor's. Run with `--paid`:
    python tools/alarm_real_think_s86.py --out <folder>"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).resolve().parents[1] / "pm" / "api_budget.toml"
    shutil.copy(src, out / "api_budget.toml")                       # the workshop's own cap line, copied into the scratch folder (never the app's file)
    os.environ["PFLAB_PM_DIR"] = str(out)
    from pflab import guard
    guard.set_flags(paid=True)                                      # his word of 2026-11-14: the real thinking step, inside the workshop cap
    from pflab.ingest import headlines as ing
    from pflab.pm import store
    from pflab.think import alarm
    con = store.connect(out / "real.duckdb")
    al, tk = ing._aliases("Nvidia Corp", "NVDA", "US")
    e = {"isin": "ZZ0001045810", "symbol": "NVDA", "market": "US", "name": "Nvidia Corp", "held": True, "red_ok": True, "exposure_pct": 0.05, "exposure_inr": 50000.0, "why": "held (US sub-book)",
         "aliases": al, "tickers": tk}
    t0 = datetime.now().replace(microsecond=0)
    title = "Nvidia investigates CEO Jensen Huang's relationship with alleged Chinese spy"

    class Net:
        def get(self, url, headers=None, timeout=None):
            class R:
                status_code = 200
                headers = {}
                text = ("<?xml version='1.0'?><rss version='2.0'><channel><item><title>%s - CNBC</title><link>https://x.invalid/1</link><pubDate>%s</pubDate><source>CNBC</source></item></channel></rss>"
                        % (title, (t0 - timedelta(hours=5, minutes=30) - timedelta(minutes=3)).strftime("%a, %d %b %Y %H:%M:%S GMT")))
            return R()

    r = alarm.run(con, t0, out, client=ing.Client(Net(), sleep=lambda s: None, clock=lambda: 0.0), entries=[e], sources=("google_news",))
    row = con.execute("SELECT published_at, first_seen_at, case_opened_at, telegram_queued_at, decided_at, decision FROM alarm_s86").fetchone()
    print("alarms:", len(r["alarms"]), "thought:", [x.get("thought") for x in r["alarms"]])
    print("times:", row)
    done = datetime.now()
    if row and row[0]:
        print("published -> heard (min):", round((row[3] - row[0]).total_seconds() / 60, 1) if row[3] else None)
        print("published -> decision (min), wall clock incl. the model:", round((done - row[0]).total_seconds() / 60, 1))
    print("cost rupees:", con.execute("SELECT coalesce(sum(cost_rupees),0) FROM think_steps_s84").fetchone()[0])
    print("telegram queued:", [t[:200] for (t,) in con.execute("SELECT text FROM outbox ORDER BY msg_id").fetchall()])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
