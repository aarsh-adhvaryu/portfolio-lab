"""S86b C3.5: HIS real gap through the real fast-forward. The app "off" from Sunday 8 Nov 2026 18:00 IST to Wednesday 11 Nov 2026 09:00 IST; a scratch book that holds Nvidia at about 8% of the US part; the
saved raw Google News response of the week (`tests/fixtures/s86/gnews_nvda_week.xml`) and the real daily bars (`nvda_daily_s86.parquet`, `spy_daily_s86.parquet`); the real model look (paid, inside the
workshop cap) for the ghost and the real thinking step for the live decision at Wednesday's last known close. No live web anywhere in the run (a stub answers "no web in this test"): today's web knows the ending.
    python tools/s86b_real_gap.py --out <folder> [--no-model]
Prints each step in order with its time, the ghost's decision and fill, the live decision, and the cost of being off in rupees."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "s86"
PREV = datetime(2026, 11, 8, 18, 0)
NOW = datetime(2026, 11, 11, 9, 0)
ISIN, SYM = "ZZ0001045810", "NVDA"


def rss_until(t: datetime) -> str:
    import lxml.etree as ET
    from datetime import timezone
    root = ET.parse(str(FIX / "gnews_nvda_week.xml")).getroot()
    rows = ""
    for it in root.findall(".//item"):
        pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).replace(tzinfo=None) + timedelta(hours=5, minutes=30)
        if pub <= t:
            rows += ET.tostring(it, encoding="unicode")
    return f"<?xml version='1.0'?><rss version='2.0'><channel>{rows}</channel></rss>"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-model", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "data" / "us" / "raw").mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).resolve().parents[1] / "pm" / "api_budget.toml", out / "api_budget.toml")
    os.environ["PFLAB_PM_DIR"] = str(out)
    os.environ["PFLAB_DATA_DIR"] = str(out / "data")
    import pandas as pd
    for s in ("nvda", "spy"):
        df = pd.read_parquet(FIX / f"{s}_daily_s86.parquet")
        df.to_parquet(out / "data" / "us" / "raw" / f"{s.upper()}.parquet", index=False)
    from pflab import guard
    guard.set_flags(paid=not a.no_model)
    from pflab.ingest import headlines as ing
    from pflab.pm import store
    from pflab.think import alarm, cases, fastforward, session as ts
    from pflab.us import book
    con = store.connect(out / "gap.duckdb")
    nv = pd.read_parquet(FIX / "nvda_daily_s86.parquet")
    fri = nv[nv["date"] == date(2026, 11, 6)].iloc[0]
    con.execute("INSERT INTO fx_rates VALUES (?, 'USDINR_FBIL', 90.4, 'scratch')", [date(2026, 11, 5)])
    con.execute("INSERT INTO paper_cash VALUES (?,?,?,?,?,?)", [store.next_id(con, "paper_cash", "entry_id"), date(2026, 10, 1), 1_000_000.0, "seed", "scratch cash", PREV])
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'FOREIGN', TRUE, ?, 'Nvidia Corp', 'scratch', now())", [ISIN, SYM])
    book.open_account(con, datetime(2026, 11, 6, 22, 0), date(2026, 11, 6), 200_000.0, {"rate": 90.4, "source": "FBIL", "rate_day": date(2026, 11, 5), "label": "scratch"}, 0.10)
    oid = book.place(con, datetime(2026, 11, 6, 22, 0), date(2026, 11, 5), ISIN, SYM, "buy", amount_usd=177.0, reason="scratch stand-in position, about 8% of the US part")
    book.fill_one(con, datetime(2026, 11, 6, 22, 0), date(2026, 11, 6), [o for o in book.open_orders(con) if o["order_id"] == oid][0], float(fri["close"]), 0.0)
    qty = book.positions(con).get(ISIN, 0.0)
    print(f"STEP 0  {PREV:%a %d %b %H:%M}  the app goes off. Book: {qty:.3f} NVDA at {float(fri['close']):.2f} (Fri 6 Nov close) = about 8% of the US part")
    alarm.record_eye(con, "google_news", PREV, ok=True, items=1)                                    # the lane's last look before the gap

    class Net:
        def get(self, url, headers=None, timeout=None):
            class R:
                status_code, headers, text = 200, {}, rss_until(NOW)
            return R()

    def no_web(c, question, now):
        return {"text": "", "cost_rupees": 0.0}

    def live(c, n, cid):
        return ts.think_case(c, n, cid, root=out / "data", web=no_web)

    es = ing.scope_entries(con, NOW.date(), out / "data")
    print(f"STEP 1  {NOW:%a %d %b %H:%M}  the app opens. Scope: {[(e['symbol'], e['held'], round(e['exposure_pct'], 3)) for e in es]}")
    r = alarm.run(con, NOW, out / "data", client=ing.Client(Net(), sleep=lambda s: None, clock=lambda: 0.0), entries=es, sources=("google_news",), think_fn=live, tell_fn=lambda c, n, cid: None,
                  gap=(lambda c, n, root, prev, items: fastforward.run_gap(c, n, root, prev, items, no_model=a.no_model)))
    g = r.get("gap") or {}
    print(f"STEP 2  backlog fetched: {r['new']} new item(s), lanes {r['lanes']}; gap off {g.get('off_from')} to {g.get('off_to')}")
    ff = g.get("fast_forward") or {}
    for c in ff.get("caused", []):
        print(f"STEP 3  what caused what: {c['symbol']} {c['gap_return']:+.1%} over the gap = market part {c['market_part']:+.1%} (beta {c['beta']}) + own part {c['own_part']:+.1%}; sector part not separated")
    for gh in ff.get("ghosts", []):
        print("STEP 4  GHOST:", json.dumps(gh))
    row = con.execute("SELECT decided_at, option, source, code_option, model_class, model_words, model_reason, model_cost, fill_ts, fill_price, qty, live_price, cost_of_being_off_inr FROM ghost_s86").fetchall()
    for x in row:
        print("        ghost row:", [str(v) for v in x])
    print("STEP 5  the message sent:", g.get("message"))
    al = con.execute("SELECT case_id, decided_at, decision FROM alarm_s86").fetchall()
    for case_id, dec_at, dec in al:
        c = cases.get_case(con, case_id)
        print(f"STEP 6  LIVE decision (Wed, last known close): {dec} | case state {c['state']} | decisions {[(d['symbol'], d['acted_option'], d['rule_option'], d['model_option']) for d in c['decisions']]}")
    ob = con.execute("SELECT order_id, side, qty, status, reason FROM us_orders_s81 ORDER BY order_id DESC LIMIT 3").fetchall()
    print("        live US orders:", [(o[0], o[1], round(o[2] or 0, 4), o[3], str(o[4])[:80]) for o in ob])
    px = fastforward._closes(con, {"market": "US", "isin": ISIN, "symbol": SYM}, fastforward.known_day("US", NOW), out / "data")
    print(f"STEP 7  last known close at Wed 09:00 IST: {float(px.iloc[-1]):.2f} on {px.index[-1]:%a %d %b}")
    cost = con.execute("SELECT coalesce(sum(cost_inr),0) FROM api_calls").fetchone()[0]
    print(f"STEP 8  model rupees spent in this run: {cost:.2f} (ghost look {con.execute('select coalesce(sum(model_cost),0) from ghost_s86').fetchone()[0]:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
