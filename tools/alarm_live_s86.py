"""S86: the alarm lane against the REAL sources for a bounded time, on a scratch store and public names only (the workshop holds no personal record).
    python tools/alarm_live_s86.py --minutes 60 --every 15 --out <folder>
Each pass: what each source returned, the request counts, any refusal, the lanes chosen; a RED is printed for a human to read before it is believed. Never sends a message (the scratch outbox is not
flushed) and never thinks a case through (no model call)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

NAMES = [("INE002A01018", "RELIANCE", "IN", "Reliance Industries"), ("INE467B01029", "TCS", "IN", "Tata Consultancy Services"), ("INE040A01034", "HDFCBANK", "IN", "HDFC Bank"),
         ("INE009A01021", "INFY", "IN", "Infosys"), ("INE154A01025", "ITC", "IN", "ITC"), ("ZZ0001045810", "NVDA", "US", "Nvidia")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--every", type=int, default=15)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    os.environ["PFLAB_PM_DIR"] = str(out / "pm")
    from pflab.ingest import headlines as ing
    from pflab.kg2 import scope as sc
    from pflab.pm import store
    from pflab.think import alarm
    con = store.connect(out / "pm" / "live.duckdb") if (out / "pm").mkdir(exist_ok=True) is None else None
    entries = []
    for isin, sym, mk, name in NAMES:
        al, tk = ing._aliases(name, sym, mk)
        entries.append({"isin": isin, "symbol": sym, "market": mk, "name": name, "held": True, "red_ok": True, "exposure_pct": 0.05, "exposure_inr": 50000.0, "why": "held", "aliases": al, "tickers": tk})
    t_end = time.time() + a.minutes * 60
    k = 0
    log = out / "live.jsonl"
    while True:
        now = datetime.now().replace(microsecond=0)
        r = alarm.run(con, now, out, entries=entries, think_fn=lambda c, n, cid: {"ok": False, "failed": "live test: no model call"}, tell_fn=lambda c, n, cid: None, force=(k == 0))
        rows = con.execute("SELECT symbol, lane, kind, severity, outlet, source, title, published, first_seen FROM headlines_s86 WHERE first_seen >= ? ORDER BY first_seen", [now]).fetchall()
        rec = {"at": str(now), "new": r.get("new"), "lanes": r.get("lanes"), "requests": r.get("requests"), "by_source": r.get("by_source"), "problems": r.get("problems"), "blind": r.get("blind"),
               "alarms": [x.get("alarm_id") for x in r.get("alarms", [])], "gap": bool(r.get("gap"))}
        reds = [x for x in rows if x[1] == "red"]
        rec["red"] = [[str(c) for c in x] for x in reds]
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        print(now, "new", r.get("new"), r.get("lanes"), "requests", r.get("requests"), "problems", (r.get("problems") or [])[:2], flush=True)
        k += 1
        if time.time() + a.every * 60 > t_end:
            break
        time.sleep(a.every * 60)
    print("lanes by source:", con.execute("SELECT source, lane, count(*) FROM headlines_s86 GROUP BY 1,2 ORDER BY 1,2").fetchall())
    print("eyes:\n" + alarm.eyes_text(con, datetime.now()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
