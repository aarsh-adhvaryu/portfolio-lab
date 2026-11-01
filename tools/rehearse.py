"""A mission rehearsal on an ISOLATED SYNTHETIC profile (S68 acceptance harness; development only, never the investor's record).

    python tools/rehearse.py seed  --profile <new empty folder> [--window-cap 600]
    python tools/rehearse.py run   --profile <folder> --goal "..." [--wait-min 25] [--port 8791]
    python tools/rehearse.py show  --profile <folder>

`seed` builds a throwaway profile: a store with a few synthetic holdings (real public ISINs, invented quantities) and their public prices, an
api_budget.toml with the bounded acceptance window (the cap given), and settings with no scheduler jobs. `run` starts the REAL runtime and the REAL
server on that profile (only the HQ thread: no collectors, no Telegram), posts the goal to `POST /api/investigations` like the screen does, and
watches the investigation's card until it is done, blocked, or the time is up. Paid calls need `--paid` in the environment (PFLAB_PAID=1) and the
API key in the secrets file; the real Docker sandbox and the real local model are used. Nothing here reads the investor's profile.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path

ISINS = {"HINDUNILVR": ("INE030A01027", 120), "ITC": ("INE154A01025", 600), "LT": ("INE018A01030", 60), "MARUTI": ("INE585B01010", 15),
         "ASIANPAINT": ("INE021A01026", 40), "NESTLEIND": ("INE239A01024", 10)}                    # public identifiers, invented quantities


def seed(profile: Path, window_cap: float) -> None:
    from pflab import _duck
    from pflab.ledger import events as ev
    from pflab.pm import store
    from pflab.data import data_dir
    if profile.exists() and any(profile.iterdir()):
        raise SystemExit(f"{profile} is not empty: a rehearsal profile is always new")
    pm = profile / "pm"
    (pm / "app").mkdir(parents=True)
    con = store.connect(pm / "ledger.duckdb")
    now = datetime.now()
    con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('ZERODHA', 'demat', 'Zerodha', 'SYNTH0001')")
    root = data_dir()
    for sym, (isin, qty) in ISINS.items():
        con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                       VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, ?, ?, 'synthetic rehearsal', now())""", [isin, sym, f"{sym} Limited"])
    rows = _duck.sql(f"select date, isin, close from '{root}/panel/prices.parquet' where isin in ({','.join(repr(v[0]) for v in ISINS.values())}) "
                     f"and date >= '2024-01-01' order by isin, date").df()
    for r in rows.itertuples():
        con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?)", [r.isin, r.date.date() if hasattr(r.date, "date") else r.date, float(r.close), "EQ", "nse_bhavcopy", now])
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZERODHA", date=date(2023, 12, 20), amount=5_000_000.0, ref="SYNTH-FUNDS"))      # invented funds
    for sym, (isin, qty) in ISINS.items():
        first = rows[rows["isin"] == isin].sort_values("date").iloc[0]
        d = first["date"].date() if hasattr(first["date"], "date") else first["date"]
        log.append(ev.Event(kind="buy", account_id="ZERODHA", date=d, isin=isin, qty=float(qty), price=float(first["close"]), ref=f"SYNTH-{sym}"))
    ev.save(con, log, now)
    con.close()
    (pm / "api_budget.toml").write_text(
        "[api]\nmodel = \"claude-opus-5-5\"\nmonthly_cap_rupees = 2500\ndev_monthly_cap_rupees = 0\nask_above_rupees = 100\nusd_inr = 90.0\nadopted = true\n"
        "[egress]\nnames = [\"synthname\", \"synthsurname\"]\naddress = []\n"
        f"[acceptance]\nsince = 2026-10-31T00:00:00\nuntil = 2026-11-07T23:59:00\ncap_rupees = {window_cap}\n", encoding="utf-8")
    (pm / "app" / "settings.json").write_text(json.dumps({"theme": "dark", "port": 8791, "scheduler": True, "preset": "full", "brain": "normal",
                                                           "drop_watch": False, "telegram_send": False, "live_prices": False}), encoding="utf-8")
    (pm / "targets.toml").write_text("# synthetic rehearsal: no targets\n", encoding="utf-8")
    print(f"seeded {profile}: {len(ISINS)} synthetic holdings, window cap Rs {window_cap}")


def run(profile: Path, goal: str, wait_min: float, port: int) -> int:
    os.environ["PFLAB_PM_DIR"] = str(profile / "pm")
    os.environ.pop("PFLAB_CHANNEL", None)
    import requests
    import uvicorn
    from pflab.app.runtime import Runtime
    from pflab.app.server import create_app
    from pflab.data import data_dir
    from pflab.pm import secrets as sec
    from pflab import scrub
    import logging
    logging.basicConfig(filename=profile / "pm" / "app" / "rehearsal.log", level=logging.INFO, encoding="utf-8", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    scrub.install()
    pm = profile / "pm"
    rt = Runtime(pm, data_dir(), Path(__file__).resolve().parents[1], secrets=sec.load())
    app = create_app(rt)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if requests.get(base + "/api/health", timeout=2).ok:
                break
        except Exception:
            time.sleep(0.5)
    from pflab.hq import service
    service.start(rt)                                                  # recover what a stopped process left (the same call the app makes at start)
    from pflab.hq import pool
    pool.start(rt)                                                     # S70: the worker pool also drives the experiments a mission waits for (the app starts it in Runtime.start)
    hq = threading.Thread(target=rt._guard(rt._hq_loop) if hasattr(rt, "_guard") else rt._hq_loop, daemon=True)
    hq.start()
    existing = requests.get(base + "/api/investigations", timeout=10).json()["investigations"]
    if goal and not any(e["goal"].strip().lower() == " ".join(goal.split()).lower() and e["state"] not in ("done", "blocked") for e in existing):
        r = requests.post(base + "/api/investigations", json={"goal": goal}, timeout=30)
        print("POST /api/investigations ->", r.status_code, r.text[:200])
    t0 = time.time()
    last = None
    while time.time() - t0 < wait_min * 60:
        time.sleep(10)
        cards = requests.get(base + "/api/investigations", timeout=10).json()["investigations"]
        line = [(c["case_id"], c["state"], c["owner"], c["blocker"], len(c["outputs"])) for c in cards]
        if line != last:
            print(datetime.now().strftime("%H:%M:%S"), line, flush=True)
            last = line
        if cards and all(c["state"] in ("done", "blocked") for c in cards):
            break
    show(profile, base=base)
    rt.shutdown(30)
    server.should_exit = True
    return 0


def show(profile: Path, base: str = "") -> None:
    import duckdb
    db = profile / "pm" / "ledger.duckdb"
    if base:                                                            # the runtime holds the file: ask through the same connection
        import requests
        d = requests.get(base + "/api/investigations", timeout=10).json()
        print(json.dumps(d, indent=1)[:6000])
        return
    con = duckdb.connect(str(db), read_only=True)
    for t, q in (("tasks", "SELECT task_id, to_agent, status, attempts, wait_kind, cost_inr FROM hq_tasks ORDER BY task_id"),
                 ("artifacts", "SELECT kind, count(*) FROM hq_artifacts GROUP BY 1"),
                 ("calls", "SELECT agent, policy, count(*), round(sum(cost_inr), 1) FROM api_calls WHERE status='done' GROUP BY 1, 2 ORDER BY 1"),
                 ("spend", "SELECT round(sum(cost_inr), 1) FROM api_calls WHERE status='done'")):
        print(t, con.execute(q).fetchall())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["seed", "run", "show"])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--goal", default="")
    ap.add_argument("--window-cap", type=float, default=600.0)
    ap.add_argument("--wait-min", type=float, default=25.0)
    ap.add_argument("--port", type=int, default=8791)
    a = ap.parse_args()
    pr = Path(a.profile)
    if a.cmd == "seed":
        seed(pr, a.window_cap)
    elif a.cmd == "run":
        sys.exit(run(pr, a.goal, a.wait_min, a.port))
    else:
        show(pr)
