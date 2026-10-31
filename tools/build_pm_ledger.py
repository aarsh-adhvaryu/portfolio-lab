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
import re
import sys
import warnings
from datetime import date, timedelta
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
OVERDRAFT_MAX, OVERDRAFT_DAYS = 100.0, 5      # a broker's short debit balance repaid by a pay-in within days (2026-10-31)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _contract_notes(path: Path) -> list:
    """A contract-note workbook (many notes), or one note's PDF (2026-10-31: a PDF was set aside unread), opened with the saved passwords."""
    if path.suffix.lower() != ".pdf":
        return cn.parse_xlsx(path)
    from pflab.ingest import sniff
    for _name, pw in [(None, None)] + list(sniff.passwords_from_secrets()):
        try:
            return [cn.parse(path, pw)]
        except cn.ContractNoteError as e:
            if "password" not in str(e).lower():
                raise
    raise cn.ContractNoteError(f"{path.name}: none of the saved passwords opens this contract note")


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


def _isins_by_symbol() -> dict:
    """Symbol -> ISIN from the exchange's recent daily files (an IPO row in the tradebook carries no ISIN)."""
    try:
        from pflab.data import bhavcopy
        df = bhavcopy.load(date.today() - pd.Timedelta(days=60), None, series=None)
        df = df.sort_values("date")
        return {str(s).upper(): i for s, i in zip(df["symbol"], df["isin"]) if isinstance(i, str) and i}
    except Exception:
        return {}


def build(src: dict, root: Path) -> tuple:
    events, checks, notes = [], [], []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    # --- Zerodha: trades, contract-note levies, other charges --------------------------------------------
    z = src["zerodha"]
    zer = z["account"]
    tbs = [tb.parse(str(root / p)) for p in z.get("tradebooks") or []]
    periods = []                                                         # each statement's own period, for the coverage (S67, audit)

    def period(acc, kind, path, df, col="date"):
        d = df[col] if len(df) else []
        periods.append({"account_id": acc, "kind": kind, "file_sha": _sha(root / path), "first_date": min(d) if len(df) else None,
                        "last_date": max(d) if len(df) else None, "n_rows": int(len(df))})
    for p, t in zip(z.get("tradebooks") or [], tbs):
        period(zer, "tradebook", p, t)
    ipo_rows = [r for t in tbs for r in t.attrs.get("ipo_allotments", [])]
    # a fresh download often overlaps an older one (S54d inbox): the same fill appears twice, so exact repeats go
    tax = lambda isin: ins.classify(isin, instrument_type="STK")[1]
    if tbs:
        trades = pd.concat(tbs, ignore_index=True).drop_duplicates().sort_values(["date", "trade_id"], kind="mergesort")
        names = {r.isin: {"symbol": r.symbol} for r in trades.itertuples()}
        tev, _ = tb.to_events(trades.reset_index(drop=True), zer, tax_class_of=tax,
                              source_doc_sha=",".join(_sha(root / p) for p in z["tradebooks"]))
    else:                                                                # (2026-10-30) no tradebook yet: the rest is still built
        names, tev = {}, []
        check("a Console tradebook is given", False, "no tradebook yet: trades are not in the ledger")
    cnotes = list({n.number: n for p in z.get("contract_notes_xlsx", []) for n in _contract_notes(root / p)}.values())
    tev, rep = cn.apply_fees(tev, cnotes)
    zfiles = ([z["funds_ledger"]] if z.get("funds_ledger") else []) + [p for p in z.get("funds_ledgers") or [] if p != z.get("funds_ledger")]
    zdf = zl.parse_many([root / p for p in zfiles]) if zfiles else None   # several Console ledgers (other years) are one ledger
    # (2026-10-31) a day with no contract note takes its charges from Console's own settlement of that day (the total; STT set apart)
    srep = {"days": {}, "trades": 0, "skipped": []}
    if zdf is not None and rep["without_note"]:
        tev, srep = cn.fees_from_settlements(tev, dict(zip(zl.settlements(zdf)["date"], zl.settlements(zdf)["net"])))
        if srep["days"]:
            notes.append(f"charges of {srep['trades']} trade(s) on {len(srep['days'])} day(s) with no contract note taken from Console's settlement "
                         f"(the day's total; STT estimated at 0.1% of value, the rest as charges): " + ", ".join(f"{d} {t:,.2f}" for d, t in srep["days"].items()))
    still = [(d, r) for d, r in rep["without_note"] if str(d) not in srep["days"]]
    check("every trade's charges are known (contract note or Console settlement)", not still and not rep["note_trades_not_in_tradebook"],
          f"{rep['with_fees']} trades from contract notes, {srep['trades']} from Console's settlement; unknown: {still}; {srep['skipped']}")
    events += tev
    for p in zfiles:
        period(zer, "funds_ledger", p, zl.parse(root / p))
    if zdf is not None:
        events += zl.charge_events(zdf, zer, _sha(root / zfiles[0]))
        settle = dict(zip(zl.settlements(zdf)["date"], zl.settlements(zdf)["net"]))
        # (2026-10-30) compared only where BOTH files speak: a funds ledger from June and contract notes from April are not a difference
        lo = max([min(zdf["date"])] + ([min(n.trade_date for n in cnotes)] if cnotes else []))
        hi = min([max(zdf["date"])] + ([max(n.trade_date for n in cnotes)] if cnotes else []))
        both = [n for n in cnotes if lo <= n.trade_date <= hi]
        settle_both = {d: v for d, v in settle.items() if lo <= d <= hi}
        bad = [(n.trade_date, n.net_amount, settle_both.get(n.trade_date)) for n in both
               if settle_both.get(n.trade_date) is None or abs(settle_both[n.trade_date] - n.net_amount) > TOL]
        check("contract-note nets = Console settlements", not bad and len(settle_both) == len(both),
              f"{len(both)} day(s) in both files' period ({lo} to {hi}); off: {bad}")
    else:
        check("a Console funds ledger is given", False, "no funds ledger yet: Zerodha's cash comes from the bank transfers alone")
    no_flows = pd.DataFrame({"date": pd.Series([], dtype=object), "amount": pd.Series([], dtype=float)})

    # --- banks ------------------------------------------------------------------------------------------------
    rules = bank.load_rules(local=store.pm_dir() / bank.LOCAL_RULES_NAME)
    stm = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        by_acc: dict = {}
        for b in src["bank"]:                                           # one account may have several statement files (other periods)
            files = ([b["file"]] if b.get("file") else []) + [f for f in b.get("files") or [] if f != b.get("file")]
            for f in files:
                one = bank.parse(str(root / f), password=_pw(b.get("password_env")))
                period(b["account"], "bank", f, one)
                by_acc.setdefault(b["account"], []).append(one)
        for acc_, frames in by_acc.items():
            stm[acc_] = bank.classify(bank.merge_parsed(frames), rules)
    stm, lab = bank_labels.auto_label(stm, zl.bank_flows(zdf) if zdf is not None else no_flows)             # S65: own transfers and broker flows by code
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
    # An allotment in the tradebook that he has not entered in Setup's IPO form is still his: booked on the broker account at the IPO price
    # (funded by a deposit there, so no cash is invented), its ISIN found from the exchange's own list by symbol, and named so he can link
    # its bank payment later. Before 2026-10-30 such a row blocked the whole ledger.
    auto, pending_ipo = set(), []
    isin_by_symbol = _isins_by_symbol()
    for r in ipo_rows:
        k = (r["symbol"], r["date"], float(r["qty"]))
        if k in want:
            continue
        isin = isin_by_symbol.get(str(r["symbol"]).upper())
        if not isin:
            pending_ipo.append(r)                              # resolved from the depository statements below, or named
            continue
        cost = round(float(r["qty"]) * float(r["price"]), 2)
        events.append(Event("deposit", zer, r["date"], amount=cost, ref=f"ipo_unlinked:{r['symbol']}:{r['date']}:fund"))
        events.append(Event("buy", zer, r["date"], isin=isin, qty=float(r["qty"]), price=float(r["price"]), ref=f"ipo_unlinked:{r['symbol']}:{r['date']}",
                            tax_class=tax(isin)))
        names.setdefault(isin, {}).setdefault("symbol", r["symbol"])
        auto.add(k)
        notes.append(f"IPO {r['symbol']} x {float(r['qty']):g} at {float(r['price']):,.2f} on {r['date']}: booked from the tradebook; its bank payment is not "
                     "linked (Setup's IPO form links it)")

    for acc, df in stm.items():
        ev, rep = bank.to_events(df, acc, broker_account=zer, existing_refs=skip, source_doc_sha=_sha(root / next(
            b["file"] for b in src["bank"] if b["account"] == acc)))
        events += ev
        un = [u for u in rep["unclassified"] if "credit" in u]
        notes.append(f"{acc}: {len(df)} lines; {len(un)} unclassified credits listed")

    # Zerodha's own ledger is the truth for its cash. A pay-in or payout it shows that no bank statement shows (another bank, or a period not
    # given) is booked on the Zerodha account and named; the bank side stays a visible difference. Before 2026-10-30 one missing bank
    # statement left Zerodha's cash negative and refused the whole ledger.
    seen = sorted((e.date, e.amount if e.counter_account == zer else -e.amount) for e in events
                  if e.kind == "cash_transfer" and zer in (e.account_id, e.counter_account))
    used, unmatched = [False] * len(seen), []
    fl = zl.bank_flows(zdf) if zdf is not None else no_flows
    for d, a in sorted(zip(fl["date"], fl["amount"])):
        hit = next((k for k, (d2, a2) in enumerate(seen) if not used[k] and abs(a - a2) < TOL and abs((d - d2).days) <= 2), None)
        if hit is None:
            unmatched.append((d, float(a)))
        else:
            used[hit] = True
    for n, (d, a) in enumerate(unmatched):
        events.append(Event("deposit" if a > 0 else "withdrawal", zer, d, amount=round(abs(a), 2), ref=f"console_flow:{d}:{n}"))
    if unmatched:
        notes.append(f"{len(unmatched)} Zerodha pay-in(s)/payout(s) booked from the Console ledger; no bank statement given shows them: "
                     + ", ".join(f"{d} {a:+,.2f}" for d, a in unmatched[:6]))

    # --- depository statements: dormant-demat opening lots and holdings checks -----------------------------
    cas_cfg = src.get("cas") or {"files": []}
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
        try:                                                             # each demat this statement covers, for the coverage
            beg = pd.to_datetime(c.statement_period.from_, dayfirst=True).date()
        except Exception:
            beg = end.replace(day=1)
        for acc in sorted(set(snap["account"].dropna())) or sorted(set(alias.values()) - {None}):
            periods.append({"account_id": acc, "kind": "cas", "file_sha": _sha(root / f), "first_date": beg, "last_date": end, "n_rows": int(len(snap))})
    if not snaps:                                                       # (2026-10-30) no depository statement yet: built without opening lots
        check("a depository statement (CAS) is given", False, "no CAS yet: holdings from before the tradebooks are not in the ledger")
        first_end, first = date.min, pd.DataFrame({"account": pd.Series([], dtype=object), "isin": pd.Series([], dtype=object),
                                                   "qty": pd.Series([], dtype=float), "name": pd.Series([], dtype=object)})
    else:
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
    # Shares an active demat already held before the tradebooks begin: the first CAS minus what the trades since the start explain is what
    # was there at the start. Opened at the start at cost 0 (or his [[opening_cost]]) and listed, never guessed (S67, 2026-10-30).
    active = [a for a in set(first["account"].dropna()) if a not in read_only]
    net: dict = {}
    for e in events:
        if e.kind in ("buy", "sell") and e.account_id in active and e.date <= first_end:
            net[(e.account_id, e.isin)] = net.get((e.account_id, e.isin), 0.0) + (e.qty if e.kind == "buy" else -e.qty)
    pre = first[first["account"].isin(active)].copy()
    pre["qty"] = [round(float(r.qty) - net.get((r.account, r.isin), 0.0), 6) for r in pre.itertuples()]
    pre = pre[pre["qty"] > 1e-9]
    if len(pre):
        qty.update({(r.account, r.isin): r.qty for r in pre.itertuples()})
        held_before, unknown2 = casm.opening_events(pre, src["start"], cost_of=cost_of)
        events += held_before
        notes += unknown2
    notes += [f"{o['account']} {o['isin']}: opening cost {float(o['cost_per_unit']):,.2f} a unit from {o['acquired']} "
              f"({o.get('basis', 'basis not stated')})" for o in oc.values()]

    # An IPO whose symbol the exchange list does not know yet: the first depository statement after the allotment shows exactly that many more
    # shares of ONE security on the broker's demat than the trades explain; that is its ISIN. Anything less certain is named, not guessed.
    for r in pending_ipo:
        isin = None
        for end, snap in sorted(snaps, key=lambda x: x[0]):
            if end < r["date"]:
                continue
            have: dict = {}
            for e in events:
                if e.kind in ("buy", "sell") and e.account_id == zer and e.date <= end:
                    have[e.isin] = have.get(e.isin, 0.0) + (e.qty if e.kind == "buy" else -e.qty)
            mine = snap[snap["account"] == zer].groupby("isin")["qty"].sum()
            fits = [i for i, q in mine.items() if abs(float(q) - have.get(i, 0.0) - float(r["qty"])) < 1e-6]
            isin = fits[0] if len(fits) == 1 else None
            break
        if not isin:
            notes.append(f"IPO {r['symbol']} x {float(r['qty']):g} on {r['date']}: its security could not be told from the files; add it in Setup's IPO form")
            continue
        cost = round(float(r["qty"]) * float(r["price"]), 2)
        events.append(Event("deposit", zer, r["date"], amount=cost, ref=f"ipo_unlinked:{r['symbol']}:{r['date']}:fund"))
        events.append(Event("buy", zer, r["date"], isin=isin, qty=float(r["qty"]), price=float(r["price"]), ref=f"ipo_unlinked:{r['symbol']}:{r['date']}",
                            tax_class=tax(isin)))
        names.setdefault(isin, {}).setdefault("symbol", r["symbol"])
        auto.add((r["symbol"], r["date"], float(r["qty"])))
        notes.append(f"IPO {r['symbol']} x {float(r['qty']):g} at {float(r['price']):,.2f} on {r['date']}: booked from the tradebook (security from the "
                     "depository statement); its bank payment is not linked (Setup's IPO form links it)")
    check("tradebook IPO rows all recorded", listed <= (want | auto), f"tradebook {sorted(listed - want - auto)}")

    # Within a day the ledger orders by kind, then insertion: put each day's inflows (deposits, income) before
    # transfers out of the same account, the end-of-day view a statement gives.
    inflow = lambda e: 0 if e.kind in ("deposit", "interest", "dividend") else 1
    log = EventLog()
    for e in sorted(events, key=lambda e: (e.date, inflow(e))):
        log.append(e)
    # (2026-10-30) money the broker spent that no file of his explains (an older tradebook with no funds ledger for that time, say) is funded
    # by a named deposit on the day it was short, so the rest of the record is still built; the difference says how much and when.
    from pflab.ledger.cash import CashError
    unexplained, overdrafts = [], []
    credits_in = lambda d: sorted(e.date for e in events if e.date > d and e.date <= d + timedelta(days=OVERDRAFT_DAYS) and (
        (e.kind == "deposit" and e.account_id == zer) or (e.kind == "cash_transfer" and e.counter_account == zer)))
    for _ in range(400):
        try:
            led = Ledger.replay(log)
            break
        except CashError as e:
            m = re.match(r"(\S+): balance would be (-?[\d.]+) on (\d{4}-\d{2}-\d{2})", str(e))
            if not m or m.group(1) != zer:
                raise
            d, short = date.fromisoformat(m.group(3)), round(-float(m.group(2)) + 0.005, 2)
            later = credits_in(d)
            if short <= OVERDRAFT_MAX and later:
                # (2026-10-31) Zerodha lets the balance dip below zero until the next pay-in (47 paise on one day of his): the dip is
                # carried as the broker's short credit and repaid from that pay-in, so no money is invented and the closing still agrees
                overdrafts.append((d, short))
                events.append(Event("deposit", zer, d, amount=short, ref=f"broker_overdraft:{d}:{len(overdrafts)}"))
                events.append(Event("withdrawal", zer, later[0], amount=short, ref=f"broker_overdraft_repaid:{d}:{len(overdrafts)}"))
            else:
                unexplained.append((d, short))
                events.append(Event("deposit", zer, d, amount=short, ref=f"unexplained_funding:{d}:{len(unexplained)}"))
            log = EventLog()
            for ev_ in sorted(events, key=lambda e: (e.date, inflow(e))):
                log.append(ev_)
    else:
        raise RuntimeError("the record could not be balanced: too many unexplained fundings")
    check("every rupee Zerodha spent has a source in your files", not unexplained,
          "funded with no file showing where from: " + ", ".join(f"{d} {a:,.2f}" for d, a in unexplained[:8]))
    if overdrafts:
        notes.append("Zerodha's balance dipped below zero until the next pay-in (it allows that): " + ", ".join(f"{d} {a:,.2f}" for d, a in overdrafts))

    # --- checks against every source --------------------------------------------------------------------------
    zc = led.cash_balance(zer)
    if zdf is not None:
        check("Zerodha cash = Console closing balance", abs(zc - zdf.attrs["closing"]) <= TOL,
              f"ledger {zc:,.2f} vs Console {zdf.attrs['closing']:,.2f}")
    for acc, df in stm.items():
        r = bank.check_closing_balance(df, led, acc)
        check(f"{acc} cash = statement closing", abs(r["ledger_cash"] - r["statement_closing"]) <= TOL,
              f"ledger {r['ledger_cash']:,.2f} vs statement {r['statement_closing']:,.2f}")
    if zdf is not None:                                                  # the ones no bank statement shows were booked above: named here
        ends = {acc: max(df["date"]) for acc, df in stm.items() if len(df)}
        short = sorted({acc for d, _ in unmatched for acc, e in ends.items() if e < d})
        check("every Zerodha pay-in and payout is in a bank statement", not unmatched,
              "not in any bank statement given: " + ", ".join(f"{d} {a:+,.2f}" for d, a in unmatched)
              + ("; statements that end before these dates: " + ", ".join(f"{a} (ends {ends[a]})" for a in short) if short else ""))
    for end, snap in snaps:
        pos = Ledger.replay(log, upto=end).positions()
        for acc in sorted(set(snap["account"].dropna())):
            want = snap[snap["account"] == acc].groupby("isin")["qty"].sum().to_dict()
            br = reconcile.holdings_breaks(f"CAS {end}", want, pos, account=acc)
            check(f"{acc} holdings = CAS {end}", br.empty, br[["isin", "a_value", "b_value", "note"]].to_dict("records"))
    for i in src.get("ipo", []):
        names.setdefault(i["isin"], {}).setdefault("symbol", i.get("symbol", "NSE"))
    periods.append({"account_id": "*", "kind": "start", "file_sha": None, "first_date": src["start"], "last_date": src["start"], "n_rows": 0})
    src = {**src, "_names": names, "_unlabelled": bank_labels.groups(stm), "_periods": periods}
    return log, led, checks, notes, src


def write(con, log: EventLog, led: Ledger, src: dict) -> None:
    with store.transaction(con):                         # all or nothing (S58 drill 2)
        _write(con, log, led, src)


def _write(con, log: EventLog, led: Ledger, src: dict) -> None:
    con.execute("DELETE FROM events")
    con.execute("DELETE FROM accounts")
    for k, v in src["accounts"].items():
        con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio, dormant, read_only) VALUES (?,?,?,?,?,?)",
                    [k, v["kind"], v.get("provider") or v.get("bank"), v.get("cas_dp") or v.get("last4"),      # a bank's last four: its identity
                     v.get("dormant", False), v.get("read_only", False)])
    save_events(con, log)
    led.write_derived(con)
    con.execute("DELETE FROM statement_periods")                         # the periods of the statements this (checked) build was made from
    for p in src.get("_periods") or []:
        con.execute("INSERT INTO statement_periods (account_id, kind, file_sha, first_date, last_date, n_rows, built_at) VALUES (?,?,?,?,?,?,now())",
                    [p["account_id"], p["kind"], p["file_sha"], p["first_date"], p["last_date"], p["n_rows"]])
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
