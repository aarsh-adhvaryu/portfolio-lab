"""Rebuild the Portfolio Manager ledger from the investor's source documents, then check it against every source.

    python tools/build_pm_ledger.py                      # PFLAB_PM_DIR/sources.toml; writes the PM store
    python tools/build_pm_ledger.py --dry-run            # build and check only

The ledger is derived: every event is rebuilt from the documents listed in `sources.toml` (Console tradebooks,
contract notes and funds ledger; bank statements; depository CAS; IPO allotments), so a rebuild after a new
statement arrives is the normal monthly step. Passwords come from the environment variables the source file
names. Checks (any failure exits 1 and writes nothing unless --force):
  - every trade has its contract note and each note's net equals Console's settlement for the day;
  - Zerodha cash equals Console's closing balance; each bank's cash equals its statement's closing balance;
  - pay-ins/payouts in Console's ledger equal the bank statements' broker transfers;
  - demat holdings equal each CAS at its period end.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import warnings
from datetime import date
from pathlib import Path

import pandas as pd

from pflab.ingest import bank, bank_labels, cas as casm, contract_note as cn, tradebook as tb, zerodha_ledger as zl
from pflab.ledger import ipo, reconcile
from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog, save as save_events
from pflab.pm import instruments as ins
from pflab.pm import store

ROOT = Path(__file__).resolve().parents[1]
TOL = 0.05


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _pw(env):
    """A statement password: the environment variable, else the same name under [passwords] in the secrets file
    (%USERPROFILE%\\.pflab\\secrets.toml; the investor 2026-10-17 asked for them to be kept there, outside the repo)."""
    if not env:
        return None
    if os.environ.get(env):
        return os.environ[env]
    from pflab.pm import secrets as sec
    try:
        s = sec.load()
    except sec.SecretsError:
        return None
    return s.get("passwords", env) if s.has("passwords", env) else None


def build(src: dict, root: Path) -> tuple:
    events, checks, notes = [], [], []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    # --- Zerodha: trades, contract-note levies, other charges --------------------------------------------
    z = src["zerodha"]
    zer = z["account"]
    tbs = [tb.parse(str(root / p)) for p in z["tradebooks"]]
    ipo_rows = [r for t in tbs for r in t.attrs.get("ipo_allotments", [])]
    # a fresh download often overlaps an older one (S54d inbox): the same fill appears twice, so exact repeats go
    trades = pd.concat(tbs, ignore_index=True).drop_duplicates().sort_values(["date", "trade_id"], kind="mergesort")
    names = {r.isin: {"symbol": r.symbol} for r in trades.itertuples()}
    tax = lambda isin: ins.classify(isin, instrument_type="STK")[1]
    tev, _ = tb.to_events(trades.reset_index(drop=True), zer, tax_class_of=tax,
                          source_doc_sha=",".join(_sha(root / p) for p in z["tradebooks"]))
    cnotes = list({n.number: n for p in z.get("contract_notes_xlsx", []) for n in cn.parse_xlsx(root / p)}.values())
    tev, rep = cn.apply_fees(tev, cnotes)
    check("every trade has a contract note", not rep["without_note"] and not rep["note_trades_not_in_tradebook"],
          f"{rep['with_fees']} trades with levies; missing {rep['without_note']}")
    events += tev
    zdf = zl.parse(root / z["funds_ledger"])
    events += zl.charge_events(zdf, zer, _sha(root / z["funds_ledger"]))
    settle = dict(zip(zl.settlements(zdf)["date"], zl.settlements(zdf)["net"]))
    bad = [(n.trade_date, n.net_amount, settle.get(n.trade_date)) for n in cnotes
           if settle.get(n.trade_date) is None or abs(settle[n.trade_date] - n.net_amount) > TOL]
    check("contract-note nets = Console settlements", not bad and len(settle) == len(cnotes), f"{len(cnotes)} days; off: {bad}")

    # --- banks ------------------------------------------------------------------------------------------------
    rules = bank.load_rules(local=store.pm_dir() / bank.LOCAL_RULES_NAME)
    stm = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for b in src["bank"]:
            stm[b["account"]] = bank.classify(bank.parse(str(root / b["file"]), password=_pw(b.get("password_env"))), rules)
    stm, lab = bank_labels.auto_label(stm, zl.bank_flows(zdf))             # S65: own transfers and broker flows by code
    notes.append(f"labels by code: {lab['own_pairs']} own transfers, {lab['broker']} broker flows")
    skip = set()
    for p in bank.pair_own_transfers(stm):
        skip |= {p["from_ref"], p["to_ref"]}
        events.append(Event("cash_transfer", p["from_account"], p["date"], amount=p["amount"],
                            counter_account=p["to_account"], ref=f"own:{p['from_ref']}"))

    # --- IPOs: the bank's payment line is replaced by block + allotment ------------------------------------
    for i in src.get("ipo", []):
        df, bl = stm[i["funding_account"]], i["bank_line"]
        hit = df[(df["date"] == bl["date"]) & ((df["debit"] - bl["amount"]).abs() < 0.005)]
        check(f"IPO {i['ipo_id']}: one bank payment line", len(hit) == 1, f"{len(hit)} lines")
        if len(hit) == 1:
            skip.add(f"bank:{i['funding_account']}:{hit['ref_id'].iloc[0]}")
        bid_q, bid_p = i.get("bid_qty", i["qty"]), i.get("bid_price", i["price"])
        events.append(ipo.block(i["ipo_id"], i["funding_account"], i.get("applied", i["allot_date"]), bid_q, bid_p))
        events.append(ipo.allot(i["ipo_id"], i["funding_account"], i["allot_date"], i["isin"], i["qty"], i["price"],
                                i["demat_account"], tax_class=tax(i["isin"])))
        if i.get("assumed"):
            notes.append(f"IPO {i['ipo_id']}: {i['assumed']}")
    listed = {(r["symbol"], r["date"], float(r["qty"])) for r in ipo_rows}
    want = {(i.get("symbol", "NSE"), i["allot_date"], float(i["qty"])) for i in src.get("ipo", [])}
    check("tradebook IPO rows all recorded", listed <= want, f"tradebook {sorted(listed)}")

    for acc, df in stm.items():
        ev, rep = bank.to_events(df, acc, broker_account=zer, existing_refs=skip, source_doc_sha=_sha(root / next(
            b["file"] for b in src["bank"] if b["account"] == acc)))
        events += ev
        un = [u for u in rep["unclassified"] if "credit" in u]
        notes.append(f"{acc}: {len(df)} lines; {len(un)} unclassified credits listed")

    # --- depository statements: dormant-demat opening lots and holdings checks -----------------------------
    cas_cfg = src["cas"]
    dp_alias = {v["cas_dp"]: k for k, v in src["accounts"].items() if v.get("cas_dp")}
    snaps = []
    for f in cas_cfg["files"]:
        c = casm.parse_pdf(root / f, _pw(cas_cfg.get("password_env")))
        alias = {casm.demat_account_id(a): dp_alias.get(a.dp_id) for a in c.accounts}
        snap = casm.holdings_snapshot(c)
        snap["account"] = snap["account"].map(alias)
        for r in snap.itertuples():
            if isinstance(r.name, str) and r.name.strip():
                names.setdefault(r.isin, {})["name"] = r.name
        end = pd.to_datetime(c.statement_period.to, dayfirst=True).date()
        snaps.append((end, snap))
    first_end, first = snaps[0]
    read_only = [k for k, v in src["accounts"].items() if v.get("read_only")]
    # [[opening_cost]] in sources.toml: cost and acquisition date for a holding with no history here (e.g. bonds
    # received from a relative: the previous owner's cost and date carry over); each entry states its basis
    oc = {(o["account"], o["isin"]): o for o in src.get("opening_cost", [])}
    qty = {(r.account, r.isin): r.qty for r in first.itertuples()}
    cost_of = lambda acc, isin: ((oc[(acc, isin)]["acquired"], float(oc[(acc, isin)]["cost_per_unit"]) * qty[(acc, isin)])
                                 if (acc, isin) in oc else None)
    opening, unknown = casm.opening_events(first[first["account"].isin(read_only)], src["start"], cost_of=cost_of)
    events += opening
    notes += unknown
    notes += [f"{o['account']} {o['isin']}: opening cost {float(o['cost_per_unit']):,.2f} a unit from {o['acquired']} "
              f"({o.get('basis', 'basis not stated')})" for o in oc.values()]

    # Within a day the ledger orders by kind, then insertion: put each day's inflows (deposits, income) before
    # transfers out of the same account, the end-of-day view a statement gives.
    inflow = lambda e: 0 if e.kind in ("deposit", "interest", "dividend") else 1
    log = EventLog()
    for e in sorted(events, key=lambda e: (e.date, inflow(e))):
        log.append(e)
    led = Ledger.replay(log)

    # --- checks against every source --------------------------------------------------------------------------
    zc = led.cash_balance(zer)
    check("Zerodha cash = Console closing balance", abs(zc - zdf.attrs["closing"]) <= TOL,
          f"ledger {zc:,.2f} vs Console {zdf.attrs['closing']:,.2f}")
    for acc, df in stm.items():
        r = bank.check_closing_balance(df, led, acc)
        check(f"{acc} cash = statement closing", abs(r["ledger_cash"] - r["statement_closing"]) <= TOL,
              f"ledger {r['ledger_cash']:,.2f} vs statement {r['statement_closing']:,.2f}")
    flows = zl.bank_flows(zdf)
    moved = sorted((e.date, e.amount if e.counter_account == zer else -e.amount) for e in log
                   if e.kind == "cash_transfer" and zer in (e.account_id, e.counter_account))
    check("Console pay-ins/payouts = bank broker transfers",
          len(moved) == len(flows) and all(abs(a - b) < TOL and abs((d1 - d2).days) <= 2
                                           for (d1, a), (d2, b) in zip(moved, sorted(zip(flows["date"], flows["amount"])))),
          f"bank {moved} vs Console {list(zip(flows['date'], flows['amount']))}")
    for end, snap in snaps:
        pos = Ledger.replay(log, upto=end).positions()
        for acc in sorted(set(snap["account"].dropna())):
            want = snap[snap["account"] == acc].groupby("isin")["qty"].sum().to_dict()
            br = reconcile.holdings_breaks(f"CAS {end}", want, pos, account=acc)
            check(f"{acc} holdings = CAS {end}", br.empty, br[["isin", "a_value", "b_value", "note"]].to_dict("records"))
    for i in src.get("ipo", []):
        names.setdefault(i["isin"], {}).setdefault("symbol", i.get("symbol", "NSE"))
    src = {**src, "_names": names, "_unlabelled": bank_labels.groups(stm)}
    return log, led, checks, notes, src


def write(con, log: EventLog, led: Ledger, src: dict) -> None:
    with store.transaction(con):                         # all or nothing (S58 drill 2)
        _write(con, log, led, src)


def _write(con, log: EventLog, led: Ledger, src: dict) -> None:
    con.execute("DELETE FROM events")
    con.execute("DELETE FROM accounts")
    for k, v in src["accounts"].items():
        con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio, dormant, read_only) VALUES (?,?,?,?,?,?)",
                    [k, v["kind"], v.get("provider"), v.get("cas_dp"), v.get("dormant", False), v.get("read_only", False)])
    save_events(con, log)
    led.write_derived(con)
    held = sorted({isin for (_, isin), q in led.positions().items() if q})
    rows = []
    for isin in held:
        s = con.execute("SELECT series FROM prices WHERE isin = ? ORDER BY date DESC LIMIT 1", [isin]).fetchone()
        rows.append({"isin": isin, "series": s[0] if s else None, "listed": True, **src["_names"].get(isin, {})})
    for r in ins.register_missing(con, rows, "build_pm_ledger"):
        print(f"instrument added: {r['isin']} {r['symbol'] or r['name']} -> {r['asset_class']}/{r['tax_class']}")
    from pflab.data import bhavcopy                     # exchange symbols for rows registered without one
    recent = bhavcopy.load(date.today() - pd.Timedelta(days=30), None, series=None)
    sym = dict(zip(recent["isin"], recent["symbol"])) if len(recent) else {}
    for isin in held:
        if sym.get(isin):
            con.execute("UPDATE instruments SET symbol = ? WHERE isin = ? AND symbol IS NULL", [sym[isin], isin])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sources", default=str(store.pm_dir() / "sources.toml"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="write even if a check fails")
    a = ap.parse_args(argv)
    from pflab.ingest import sources as srcs
    src = srcs.load(Path(a.sources))                    # plus sources.app.toml: documents added through the inbox
    log, led, checks, notes, src = build(src, ROOT)
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  -- {detail}"))
    for n in notes:
        print(f"note  {n}")
    print(f"{len(log)} events; positions: " + ", ".join(f"{acc}/{isin} {q:g}" for (acc, isin), q in sorted(led.positions().items()) if q))
    failed = [c for c in checks if not c[1]]
    if a.dry_run or (failed and not a.force):
        print("NOT WRITTEN" + (f": {len(failed)} check(s) failed" if failed else " (dry run)"))
        return 1 if failed else 0
    write(store.connect(), log, led, src)
    print(f"written to {store.db_path()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
