"""S86b C6: the US session loop on REAL 1-minute bars (with pre-market and after-hours) of Thursday 12 and Friday 13 Nov 2026 (`tests/fixtures/s86/nvda_1m_s86.json`, `spy_1m_s86.json`, public Yahoo chart
data fetched 14 Nov) on a scratch sub-book that holds Nvidia, with the saved headlines (`gnews_nvda_week.xml`) at their real times through the alarm lane. The case's decision is SCRIPTED (a sale of the
whole position on the first serious headline, then a buy of the same name later the same US day, which must not happen); everything else is the real code: the lane, `core/us_session.tick`, the fills.
The watch on live quotes is stubbed (no signal, no model call). One 25-minute feed stall is injected on Friday 20:30 IST to show that a stale quote never fills.
    python tools/s86b_us_bars.py --out <folder>"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "s86"
ISIN, SYM = "ZZ0001045810", "NVDA"
IST = timedelta(hours=5, minutes=30)
STALL = (datetime(2026, 11, 13, 20, 30), datetime(2026, 11, 13, 20, 55))


def load_bars(sym):
    d = json.loads((FIX / f"{sym.lower()}_1m_s86.json").read_text(encoding="utf-8"))
    return [(datetime.fromtimestamp(t, timezone.utc).replace(tzinfo=None) + IST, float(c)) for t, c in d["bars"]]      # (bar START in IST, close)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    (out / "data" / "us" / "raw").mkdir(parents=True, exist_ok=True)
    os.environ["PFLAB_PM_DIR"] = str(out)
    os.environ["PFLAB_DATA_DIR"] = str(out / "data")
    import pandas as pd
    for s in ("nvda", "spy"):
        pd.read_parquet(FIX / f"{s}_daily_s86.parquet").to_parquet(out / "data" / "us" / "raw" / f"{s.upper()}.parquet", index=False)
    bars = {"NVDA": load_bars("NVDA"), "SPY": load_bars("SPY")}
    from pflab.core import us_session as uss
    from pflab.ingest import headlines as ing
    from pflab.pm import store
    from pflab.think import alarm, cases, session as ts, watch
    from pflab.us import book
    uss.on = lambda: True
    watch.run = lambda *x, **k: {"signals": [], "cases_opened": []}
    con = store.connect(out / "bars.duckdb")
    nv = pd.read_parquet(FIX / "nvda_daily_s86.parquet")
    fri = nv[nv["date"] == date(2026, 11, 6)].iloc[0]
    con.execute("INSERT INTO fx_rates VALUES (?, 'USDINR_FBIL', 90.4, 'scratch')", [date(2026, 11, 5)])
    con.execute("INSERT INTO paper_cash VALUES (?,?,?,?,?,?)", [store.next_id(con, "paper_cash", "entry_id"), date(2026, 10, 1), 1_000_000.0, "seed", "scratch cash", datetime(2026, 11, 6)])
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'FOREIGN', TRUE, ?, 'Nvidia Corp', 'scratch', now())", [ISIN, SYM])
    book.open_account(con, datetime(2026, 11, 6, 22, 0), date(2026, 11, 6), 200_000.0, {"rate": 90.4, "source": "FBIL", "rate_day": date(2026, 11, 5), "label": "scratch"}, 0.10)
    oid = book.place(con, datetime(2026, 11, 6, 22, 0), date(2026, 11, 5), ISIN, SYM, "buy", amount_usd=177.0, reason="scratch stand-in position")
    book.fill_one(con, datetime(2026, 11, 6, 22, 0), date(2026, 11, 6), [o for o in book.open_orders(con) if o["order_id"] == oid][0], float(fri["close"]), 0.0)

    import lxml.etree as ET
    items = []
    for it in ET.parse(str(FIX / "gnews_nvda_week.xml")).getroot().findall(".//item"):
        pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).replace(tzinfo=None) + IST
        items.append((pub, ET.tostring(it, encoding="unicode")))
    clock = {"t": None}

    def get_quote(url):
        sym = url.split("chart/")[1].split("?")[0]
        t = clock["t"]
        if STALL[0] <= t <= STALL[1]:
            t = STALL[0] - timedelta(minutes=1)                                              # the feed stalled: only older bars come back
        good = [(s, c) for s, c in bars[sym] if s + timedelta(minutes=1) <= t]
        tail = good[-3:]
        ts_ = [int((s - IST).replace(tzinfo=timezone.utc).timestamp()) for s, _ in tail]
        return json.dumps({"chart": {"result": [{"timestamp": ts_, "indicators": {"quote": [{"close": [c for _, c in tail]}]}}]}})

    class Net:
        def get(self, url, headers=None, timeout=None):
            class R:
                status_code, headers = 200, {}
                text = ("<?xml version='1.0'?><rss version='2.0'><channel>" + "".join(x for p, x in items if p <= clock["t"]) + "</channel></rss>")
            return R()

    log = []

    def think(c, now, cid):
        case = cases.get_case(c, cid)
        day = ts.uc.session_closed_by(now) if hasattr(ts, "uc") else None
        d = {"isin": ISIN, "symbol": SYM, "option": "sell", "reason": "scripted: the first serious headline sells the whole position"}
        res = ts._act_us(c, now, now.date(), case, d)
        cases.add_step(c, cid, now, "answer_ok", payload={})
        cases.record_decision(c, cid, now.date(), isin=ISIN, symbol=SYM, rule_option="sell", model_option="sell", acted_option="sell", reason="scripted")
        log.append((now, "DECISION sell", res, uss.phase(now)[0]))
        return {"ok": True, "state": "acted"}

    t = datetime(2026, 11, 12, 14, 30)
    end = datetime(2026, 11, 14, 3, 0)
    bought_again = False
    alarm.record_eye(con, "google_news", t - timedelta(minutes=15), ok=True)
    while t <= end:
        clock["t"] = t
        if t.minute % 15 == 0:
            es = ing.scope_entries(con, t.date(), out / "data")
            alarm.run(con, t, out / "data", client=ing.Client(Net(), sleep=lambda s: None, clock=lambda: 0.0), entries=es, sources=("google_news",), think_fn=think, tell_fn=lambda c, n, cid: None,
                      model_fn=lambda title: None)
        r = uss.tick(con, t, out / "data", get=get_quote)
        if r.get("fills"):
            for f in r["fills"]:
                log.append((t, "FILL", {k: f[k] for k in ("symbol", "side", "qty", "price", "quote_ts", "delay_min", "decision_ts")}, r["phase"]))
        if not bought_again and any(x[1] == "FILL" for x in log) and r["phase"] == "regular":
            b = book.place(con, t, uss.phase(t)[1], ISIN, SYM, "buy", amount_usd=100.0, reason="scripted: a buy of the same name on the same US day (must not fill)")
            log.append((t, "ORDER buy (same US day)", b, r["phase"]))
            bought_again = True
        t += timedelta(minutes=5)
    print("time (IST)          phase     event")
    for when, what, detail, ph in log:
        print(f"{when:%a %d %b %H:%M}  {ph:<8}  {what}  {detail}")
    print("\nfills table (decision -> quote -> price, delay in minutes):")
    for r in con.execute("SELECT order_id, side, decision_ts, quote_ts, delay_min, quote_price, fill_price, est_bps, session_day FROM us_fills_s86 ORDER BY order_id").fetchall():
        print("  ", [str(x) for x in r])
    print("open orders at the end:", [(o["order_id"], o["side"], o["reason"][:70]) for o in book.open_orders(con)])
    print("quote delays:", uss.delay_report(con, date(2026, 11, 12)), uss.delay_report(con, date(2026, 11, 13)))
    print("quotes stored:", con.execute("SELECT phase, count(*) FROM us_quotes_s86 GROUP BY 1 ORDER BY 1").fetchall())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
