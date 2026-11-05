"""Re-seed the system's own account and paper book from his Kite holdings ONLY (S79, A45). Run with the dashboard CLOSED (one process holds the store).

    .venv\\Scripts\\python tools\\reseed_s79.py --rehearse <new folder>                       rehearse the whole re-seed on a synthetic store in that folder (a COPY; nothing real)
    .venv\\Scripts\\python tools\\reseed_s79.py --pm <pm folder> --holdings <kite.json>        preview only: what would be seeded; changes nothing
    .venv\\Scripts\\python tools\\reseed_s79.py --pm <pm folder> --from-kite                   preview, holdings read from Kite (read-only; needs today's login)
    ... --apply --confirm-his-go                                                             do it (needs both flags: his Kite login and his "go"; the store is backed up first)

`--holdings` is the JSON of kite.holdings() (a list of {tradingsymbol, isin, quantity, t1_quantity, average_price, last_price}). Cash defaults to the fake Rs 5,00,000.
It prints counts and the starting positions of the SYSTEM's account, never anything of a personal record.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _table(title: str, snap: dict) -> None:
    print(f"\n== {title}")
    print("  accounts:", ", ".join(snap["accounts"]) or "(none)")
    print(f"  events: {snap['events']}")
    print("  lots (rows, units) by account:", "; ".join(f"{a}: {n} / {q:g}" for a, (n, q) in snap["lots_by_account"].items()) or "(none)")
    print("  cash by account:", "; ".join(f"{a}: Rs {c:,.2f}" for a, c in snap["cash_by_account"].items()) or "(none)")
    print("  paper record rows:", ", ".join(f"{t[6:]}={n}" for t, n in snap["paper"].items()))
    print("  account-record rows (FDs, statements, tax packs):", ", ".join(f"{t}={n}" for t, n in snap["account_record"].items()) or "(none)")
    if snap["archives"]:
        print("  archives:", ", ".join(f"{t.replace('_archive_s79', '')}={n}" for t, n in snap["archives"].items() if t != "paper_archive_s79"))


def _holdings_from(a):
    if a.holdings:
        return json.loads(Path(a.holdings).read_text(encoding="utf-8"))
    if a.from_kite:
        from pflab.ingest import kite as km
        from pflab.pm import secrets as sec
        k = km.client(sec.load())
        if k is None:
            raise SystemExit("Kite is not logged in today: run tools/kite_login.py first")
        return k.holdings()
    raise SystemExit("give --holdings <json> or --from-kite")


def rehearse(folder: Path) -> int:
    """Build a synthetic old store (statement accounts, an FD, a Coin folio, a bank, the old paper record) with the repo's rehearsal seed, then re-seed it from SYNTHETIC Kite holdings
    (shares, ETFs, an inherited SGB with no purchase price, a gold ETF), print the tables before and after, run it again (it must do nothing), and walk the allocation target."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import rehearse as rh
    rh.seed(folder, 600)
    os.environ["PFLAB_PM_DIR"] = str(folder / "pm")
    from datetime import date
    from pflab import _duck
    from pflab.data import data_dir
    from pflab.ledger import events as ev, system
    from pflab.paper import allocation, book, manager, reseed
    from pflab.pm import store
    con = store.connect(folder / "pm" / "ledger.duckdb")
    now = datetime.now()
    # the OLD store: more than Kite shows (a bank, an off-Kite folio, an FD) and a paper record since 2026-11-02
    con.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('SYNTHBANK', 'bank', 'synthetic bank')")
    con.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('SYNTHFOLIO', 'folio', 'synthetic folio')")
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="SYNTHFOLIO", date=date(2024, 1, 2), amount=50_000.0, ref="SYNTH"))
    log.append(ev.Event(kind="deposit", account_id="SYNTHBANK", date=date(2024, 1, 2), amount=900_000.0, ref="SYNTH"))
    log.append(ev.Event(kind="buy", account_id="ZERODHA", date=date(2026, 11, 3), isin=rh.ISINS["ITC"][0], qty=10.0, price=400.0, ref="sys:order:1"))
    system._store(con, log.raw(), now)                                       # (new ids after the seed's own)
    system.derive(con, now)
    con.execute("INSERT INTO fds (fd_id, bank, principal, rate, term_start, maturity, maturity_amount, status, source, loaded_at) VALUES ('SYNTHFD', 'synthetic bank', 100000, 7.0, ?, ?, 107000, 'open', 'synthetic', now())",
                [date(2025, 1, 1), date(2027, 1, 1)])
    for d in (date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)):
        con.execute("INSERT OR REPLACE INTO paper_days VALUES (?, 650000, 500000, 150000, 0, '{}')", [d])
    con.execute("INSERT INTO paper_decisions (decision_id, made_at, case_id, action, isin, symbol, reason, status) VALUES (1, ?, NULL, 'BUY', ?, 'ITC', 'a synthetic old decision', 'executed')",
                [datetime(2026, 11, 2, 10), rh.ISINS["ITC"][0]])
    # SYNTHETIC Kite holdings: shares and ETFs the rehearsal store has prices for, plus an inherited SGB (no purchase price) not in the instrument master
    sgb = "IN0020230099"
    last = con.execute("SELECT max(date) FROM prices WHERE source='nse_bhavcopy'").fetchone()[0]
    con.execute("INSERT INTO prices VALUES (?, ?, 6150.0, 'GB', 'nse_bhavcopy', now())", [sgb, last])
    holdings = [dict(tradingsymbol="HINDUNILVR", exchange="NSE", isin=rh.ISINS["HINDUNILVR"][0], quantity=50, t1_quantity=0, average_price=2300.0, last_price=2400.0),
                dict(tradingsymbol="ITC", exchange="NSE", isin=rh.ISINS["ITC"][0], quantity=300, t1_quantity=10, average_price=380.0, last_price=410.0),
                dict(tradingsymbol="LT", exchange="NSE", isin=rh.ISINS["LT"][0], quantity=20, t1_quantity=0, average_price=3100.0, last_price=3500.0),
                dict(tradingsymbol="NIFTYBEES", exchange="NSE", isin=rh.ETFS["NIFTYBEES"], quantity=400, t1_quantity=0, average_price=250.0, last_price=270.0),
                dict(tradingsymbol="GOLDBEES", exchange="NSE", isin=rh.ETFS["GOLDBEES"], quantity=1500, t1_quantity=0, average_price=60.0, last_price=70.0),
                dict(tradingsymbol="SGBMAR33", exchange="NSE", isin=sgb, quantity=6, t1_quantity=0, average_price=0.0, last_price=6150.0)]
    import copy
    store_copy = folder / "pm" / "ledger_before.duckdb"                       # the COPY the rehearsal works on is the store itself; this file is only a read-only picture of "before"
    con.execute("CHECKPOINT")
    print("REHEARSAL on a synthetic store:", folder / "pm" / "ledger.duckdb")
    pre = reseed.preview(con, copy.deepcopy(holdings), now)
    print("\n== preview (nothing written):", json.dumps({k: v for k, v in pre.items() if k != "snapshot_now"}, default=str))
    before = reseed.snapshot(con)
    _table("BEFORE", before)
    out = reseed.reseed(con, copy.deepcopy(holdings), now, pm_dir=folder / "pm", backup_dir=folder / "backups")
    _table("AFTER", out["after"])
    print("\n== done:", out["done"], "| seed date:", out["seed_date"], "| cash Rs", f"{out['cash']:,.0f}", "| inherited (no price):", out["cost_unknown"], "| registered:", out["registered_instruments"])
    print("== archive:", out["archive"]["label"], json.dumps(out["archive"]["rows"]))
    print("== backup:", Path(out["backup"]["file"]).name, "rows", out["backup"]["rows"], "(events in the copy:", out["backup"]["events_in_copy"], ")")
    h = book.holdings(con, datetime.fromisoformat(out["seed_date"]).date())
    print("\n== the new paper book on", out["seed_date"], f"(value Rs {h['value']:,.0f}, cash Rs {h['cash']:,.0f}, bank Rs {h['bank']:,.0f})")
    for r in h["rows"]:
        print(f"  {r['symbol']:<12} {r['asset_class'] or '?':<7} qty {r['qty']:>8g}  price {r['price'] or 0:>9,.2f}  value Rs {r['value'] or 0:>11,.0f}  weight {r['weight']:.1%}")
    print("== the gate:", manager.gate(con, None)["status"])
    again = reseed.reseed(con, copy.deepcopy(holdings), now, pm_dir=folder / "pm", backup_dir=folder / "backups")
    print("\n== run again:", again["done"], "-", again["why"])
    print("\n== allocation: first review has no target:", allocation.review_due(con, now)["why"])
    ok = allocation.validate_target({"equity": 55, "gold": 20, "international": 10, "cash": 15}, {"FMCG": 20, "Capital Goods": 15})
    bad = allocation.validate_target({"equity": 80, "gold": 30, "international": 0, "cash": -10, "futures": 5})
    print("   validate (fine split):", ok["ok"], "| validate (broken split):", bad["ok"], "-", "; ".join(bad["problems"])[:200])
    t = allocation.propose_allocation(con, {"equity": 55, "gold": 20, "international": 10, "cash": 15}, "A rehearsal split with reasons given in a few plain sentences about gold and cash.", now,
                                      sectors={"FMCG": 20, "Capital Goods": 15})
    allocation.review_target(con, t["target_id"], "approve", "rehearsal: the independent review is simulated", now)
    g = allocation.trade_toward(book.holdings(con, datetime.fromisoformat(out["seed_date"]).date()), allocation.active_target(con))
    print("   active target #%d; gap beyond the band:" % t["target_id"],
          "; ".join(f"{x['name']} {x['gap_pct']:+.1f} pts (Rs {x['gap_rupees']:,.0f})" for x in g["add"] + g["trim"]))
    con.close()
    return 0 if out["done"] and again["done"] is False else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rehearse", metavar="FOLDER", help="rehearse on a synthetic store in a NEW folder")
    ap.add_argument("--pm", help="the profile's pm folder (the real store: needs --apply and --confirm-his-go to change it)")
    ap.add_argument("--holdings", help="JSON of kite.holdings()")
    ap.add_argument("--from-kite", action="store_true", help="read the holdings from Kite (read-only)")
    ap.add_argument("--cash", type=float, default=500_000.0)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm-his-go", action="store_true", help="his explicit go (and his Kite login) was given")
    ap.add_argument("--force", action="store_true", help="re-seed again even if already done")
    a = ap.parse_args(argv)
    if a.rehearse:
        folder = Path(a.rehearse)
        if folder.exists() and any(folder.iterdir()):
            raise SystemExit(f"{folder} is not empty: a rehearsal folder is always new")
        return rehearse(folder)
    if not a.pm:
        ap.error("give --rehearse <folder> or --pm <pm folder>")
    if a.apply and not a.confirm_his_go:
        raise SystemExit("--apply needs --confirm-his-go: the real re-seed waits for his Kite login and his go")
    os.environ["PFLAB_PM_DIR"] = str(a.pm)
    from pflab.paper import reseed
    from pflab.pm import store
    con = store.connect()
    holdings, now = _holdings_from(a), datetime.now()
    if not a.apply:
        print(json.dumps({k: v for k, v in reseed.preview(con, holdings, now, a.cash).items() if k != "snapshot_now"}, indent=1, default=str))
        print("(preview: nothing changed; add --apply --confirm-his-go to do it)")
        return 0
    out = reseed.reseed(con, holdings, now, a.cash, pm_dir=Path(a.pm), force=a.force)
    print(json.dumps({k: v for k, v in out.items() if k not in ("before",)}, indent=1, default=str))
    return 0 if out.get("done") else 1


if __name__ == "__main__":
    sys.exit(main())
