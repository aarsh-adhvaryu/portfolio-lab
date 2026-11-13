"""S86: the Nvidia week, honestly. The RAW source responses of 8-13 Nov 2026 (fixtures of public news, fetched on 13 Nov: `tests/fixtures/s86/gnews_nvda_week.xml`) are fed to the alarm lane at their
REAL times through the collector, one 15-minute tick at a time from Sunday 8 Nov 18:00 IST, on a scratch store: a book that holds the name and a book that does not. Nothing is written as a
finished event; no model is called (a stub decides "hold" and records the time); nothing is sent.
    python tools/s86_nvidia_week.py --out <folder>
Prints, per book: the first publication of the first serious headline, when "Heard" was queued, when the case opened, and the same for the later serious headlines of the week (the resignation on
Thursday 12 Nov). The lane-OFF timeline is derived from the code's own rules (docs/s86_alarm_notes.md), because with the lane off the headlines never reach the store at all."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "s86"


def items():
    import lxml.etree as ET
    from datetime import timezone
    root = ET.parse(str(FIX / "gnews_nvda_week.xml")).getroot()
    out = []
    for it in root.findall(".//item"):
        pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).replace(tzinfo=None) + timedelta(hours=5, minutes=30)
        out.append((pub, it))
    return sorted(out, key=lambda x: x[0])


def xml_until(all_items, t: datetime, hours: int):
    import lxml.etree as ET
    rows = "".join(ET.tostring(it, encoding="unicode") for pub, it in all_items if t - timedelta(hours=hours) < pub <= t)
    return f"<?xml version='1.0'?><rss version='2.0'><channel>{rows}</channel></rss>"


class Resp:
    def __init__(self, text):
        self.text, self.status_code, self.headers = text, 200, {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--end", default="2026-11-13 12:00")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    os.environ["PFLAB_PM_DIR"] = str(out)
    from pflab.ingest import headlines as ing
    from pflab.pm import store
    from pflab.think import alarm, cases
    all_items = items()
    result = {}
    for book, held in (("holds_nvidia", True), ("does_not_hold", False)):
        con = store.connect(out / f"{book}.duckdb")
        al, tk = ing._aliases("Nvidia Corp", "NVDA", "US")
        e = {"isin": "ZZ0001045810", "symbol": "NVDA", "market": "US", "name": "Nvidia Corp", "held": held, "red_ok": held, "exposure_pct": 0.05 if held else 0.0, "exposure_inr": 50000.0 if held else 0.0,
             "why": "held (US sub-book)" if held else "screened name", "aliases": al, "tickers": tk}
        t = datetime(2026, 11, 8, 18, 0)
        end = datetime.strptime(a.end, "%Y-%m-%d %H:%M")
        thought = []

        def think(c, now, cid):
            cases.add_step(c, cid, now, "answer_ok", payload={})
            cases.record_decision(c, cid, now.date(), isin=e["isin"], symbol="NVDA", rule_option="hold", model_option="hold", acted_option="hold", reason="stub")
            thought.append((cid, now))
            return {"ok": True, "state": "open"}

        while t <= end:
            class Net:
                def get(self, url, headers=None, timeout=None, _t=t):
                    return Resp(xml_until(all_items, _t, 24 * 7 if "when%3A7d" in url else 6))
            alarm.run(con, t, out, client=ing.Client(Net(), sleep=lambda s: None, clock=lambda: 0.0), entries=[e], sources=("google_news",), think_fn=think, tell_fn=lambda c, n, cid: None)
            t += timedelta(minutes=15)
        rows = con.execute("SELECT alarm_id, published_at, first_seen_at, case_opened_at, telegram_queued_at, decided_at, headline, outlet, joined_items, decision FROM alarm_s86 ORDER BY alarm_id").fetchall()
        msgs = [(str(r[0]), r[1][:160]) for r in con.execute("SELECT ts, text FROM outbox WHERE kind='alarm' ORDER BY msg_id").fetchall()] if _has(con, "outbox", "ts") else []
        lanes = con.execute("SELECT lane, count(*) FROM headlines_s86 GROUP BY 1 ORDER BY 1").fetchall()
        result[book] = {"alarms": [[str(x) for x in r] for r in rows], "messages": msgs, "lanes": lanes, "cases": len(thought)}
        print("\n==", book, "lanes", lanes, "cases", len(thought))
        for r in rows:
            pub, heard = r[1], r[4]
            m = None if pub is None or heard is None else round((heard - pub).total_seconds() / 60.0, 1)
            print(f"  alarm {r[0]}: first published {pub:%a %d %b %H:%M} IST | seen {r[2]:%H:%M} | case {r[3] and r[3]:%a %H:%M} | heard {heard and heard:%a %H:%M} ({m} min) | joined {r[8]} | {r[6][:90]} ({r[7]})")
    (out / "nvidia_week.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return 0


def _has(con, table, col) -> bool:
    try:
        con.execute(f"SELECT {col} FROM {table} LIMIT 1")
        return True
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
