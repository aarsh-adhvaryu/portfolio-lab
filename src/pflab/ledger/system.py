"""The system's own account (S77, A36; his decision 2026-11-02: "get rid of my portfolio; the system has an account on Kite with fake money").

One ledger, owned by the system. Its history is seeded ONCE from the lots the record already holds in his Zerodha accounts (real buy dates and prices, SGBs he
inherited at an unknown cost), funded by a history deposit so the replay holds; then a FAKE bank (`SYSBANK`, Rs 5,00,000) moves its cash to a FAKE broker (`SYSBROKER`).
From then on only code appends events (the system's trades, bank-to-broker transfers, top-ups). His own later trades in Kite are ignored.

The switch is a file: `system_account.toml` in the profile. While it exists the statement rebuild, the deposits job, the Kite overlay of `pm/today.build` and the
tradecheck reconciliation stand aside (they would rewrite or contradict the account). Without it everything is as before (tests, the workshop).
"""
from __future__ import annotations

import math
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pflab.ledger import events as ev
from pflab.ledger.book import Ledger

SYSBANK, SYSBROKER = "SYSBANK", "SYSBROKER"
FLAG = "system_account.toml"
START_CASH = 500_000.0
TOPUP_MONTH_MAX = 50_000.0
FOREIGN_PREFIXES = ("ZZ", "US:")


def flag_path(pm_dir: Optional[Path] = None) -> Path:
    from pflab.pm import store
    return Path(pm_dir or store.pm_dir()) / FLAG


def active(pm_dir: Optional[Path] = None) -> bool:
    """True once the profile has been switched to the system's own account."""
    try:
        return flag_path(pm_dir).exists()
    except Exception:
        return False


def settings(pm_dir: Optional[Path] = None) -> dict:
    """`system_account.toml`: start_cash_rupees, topup_month_max, since. Defaults when absent."""
    import tomllib
    out = {"start_cash_rupees": START_CASH, "topup_month_max": TOPUP_MONTH_MAX}
    try:
        out.update(tomllib.loads(flag_path(pm_dir).read_text(encoding="utf-8")))
    except Exception:
        pass
    return out


def _next(con) -> int:
    from pflab.pm.store import next_id
    return next_id(con, "events", "event_id")


# --- the history: his Zerodha lots become the system's opening positions -------------------------------------------------------------

def zerodha_accounts(con) -> List[str]:
    """His Zerodha accounts in the record (demat or Coin folio), never a bank."""
    return [r[0] for r in con.execute("SELECT account_id FROM accounts WHERE provider ILIKE '%zerodha%' AND kind <> 'bank'").fetchall()]


def history_events(con, asof: date) -> Tuple[List[ev.Event], dict]:
    """The opening events from the lots the current record holds in his Zerodha accounts on `asof`: one `buy` per lot at its real date and cost per unit (0 and
    labelled cost-unknown for an inherited holding), and one history deposit before the earliest so the replay never starves. Returns (events, summary)."""
    led = Ledger.replay(ev.load(con), upto=asof)
    zer = set(zerodha_accounts(con))
    unknown = {r[0] for r in con.execute("SELECT event_id FROM events WHERE kind='buy' AND ref LIKE '%:cost_unknown'").fetchall()}
    out: List[ev.Event] = []
    left, n_unknown, cost = [], 0, 0.0
    for lot in sorted(led.lots.all_lots(), key=lambda l: (l.acq_date, l.lot_id)):
        if lot.account_id not in zer:
            continue
        if lot.isin.startswith(FOREIGN_PREFIXES):
            left.append(lot.isin)
            continue
        is_unknown = lot.origin_event in unknown
        price = 0.0 if is_unknown else float(lot.cost_per_unit)
        n_unknown += is_unknown
        cost += lot.qty * price
        out.append(ev.Event(kind="buy", account_id=SYSBROKER, date=lot.acq_date, isin=lot.isin, qty=float(lot.qty), price=price,
                            ref=f"seed:lot{lot.lot_id}" + (":cost_unknown" if is_unknown else ""), tax_class=lot.tax_class))
    if out:
        first = min(e.date for e in out)
        fund = math.ceil(cost * 100) / 100
        out.insert(0, ev.Event(kind="deposit", account_id=SYSBROKER, date=first, amount=fund, ref="seed:history (not money: it only lets the old purchases replay)"))
        if fund - cost > 1e-9:                          # the rounding cent goes straight back out, so the broker starts with exactly the fake cash
            out.append(ev.Event(kind="withdrawal", account_id=SYSBROKER, date=max(e.date for e in out if e.kind == "buy"), amount=fund - cost, ref="seed:history rounding"))
    return out, {"lots": len(out) - (1 if out else 0), "cost_unknown": n_unknown, "history_funding": round(cost, 2), "left_out": left}


def opening_cash_events(asof: date, start_cash: float) -> List[ev.Event]:
    """The fake bank's first deposit and its transfer to the fake broker."""
    return [ev.Event(kind="deposit", account_id=SYSBANK, date=asof, amount=start_cash, ref="start: the system's fake bank"),
            ev.Event(kind="cash_transfer", account_id=SYSBANK, date=asof, amount=start_cash, counter_account=SYSBROKER, ref="start: fake bank to fake broker")]


# --- writing --------------------------------------------------------------------------------------------------------------------------

def _store(con, log: List[ev.Event], now: datetime) -> None:
    import dataclasses
    base = _next(con)
    new = ev.EventLog()
    for i, e in enumerate(log):
        new.append(dataclasses.replace(e, event_id=base + i))
    ev.save(con, new, now)


def derive(con, now: Optional[datetime] = None) -> Ledger:
    """Replay every event and rewrite the derived tables (`lots`, `cash_ledger`, `income`, `fees`)."""
    led = Ledger.replay(ev.load(con))
    led.write_derived(con, now)
    return led


def append(con, events: List[ev.Event], now: Optional[datetime] = None) -> Ledger:
    """Add the system's own events to its ledger and re-derive. Refuses what would overdraw an account (the replay raises) and writes nothing then."""
    now = now or datetime.now()
    probe = ev.load(con)
    import dataclasses
    for e in events:
        probe.append(dataclasses.replace(e, event_id=10 ** 9 + len(probe.raw())))
    Ledger.replay(probe)                                 # raises LotError / CashError before anything is stored
    _store(con, events, now)
    return derive(con, now)


def switch(con, pm_dir: Path, asof: date, now: datetime, start_cash: float = START_CASH, backup_to: Optional[Path] = None) -> dict:
    """Make the profile the system's own account. Safe order: build the new events and replay them FIRST (nothing is changed if that fails), copy the store aside,
    then in one transaction replace events, accounts and the derived tables, and write the flag. Returns what was built."""
    from pflab.pm import store
    new_events, summary = history_events(con, asof)
    if not new_events:
        raise RuntimeError("no Zerodha lots on record to start from")
    cash_day = asof                                      # the account continues the paper book: its opening cash is dated the paper book's first day, so every marked day holds it
    try:
        first = con.execute("SELECT min(day) FROM paper_days").fetchone()[0]
        if first and first < asof:
            cash_day = first
    except Exception:
        pass
    opening = opening_cash_events(cash_day, start_cash)
    log = ev.EventLog()
    import dataclasses
    for i, e in enumerate(new_events + opening, start=1):
        log.append(dataclasses.replace(e, event_id=i))
    led = Ledger.replay(log)                             # raises when the history does not replay
    cash = round(float(led.cash.balance(SYSBROKER)), 2)
    held = sorted({isin for (acc, isin), q in led.positions().items() if q > 0})
    if backup_to is not None:
        from pflab.service import backup as bk                # DuckDB makes the copy itself (the file is locked while it is open), and the row counts are checked
        db = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
        done = bk.backup(con, Path(db[0]) if db and db[0] else Path(str(store.db_path())), backup_to.parent, now, keep=3)
        Path(done["file"]).replace(backup_to)
    with store.transaction(con):
        con.execute("DELETE FROM events")
        con.execute("DELETE FROM accounts")
        con.execute("INSERT INTO accounts (account_id, kind, provider, dormant, read_only) VALUES (?,?,?,?,?)", [SYSBANK, "bank", "the system's fake bank", False, False])
        con.execute("INSERT INTO accounts (account_id, kind, provider, dormant, read_only) VALUES (?,?,?,?,?)", [SYSBROKER, "demat", "the system's fake broker", False, False])
        ev.save(con, log, now)
    led.write_derived(con, now)
    flag = flag_path(pm_dir)
    flag.write_text(f'since = "{now:%Y-%m-%dT%H:%M:%S}"\nstart_cash_rupees = {start_cash:g}\ntopup_month_max = {TOPUP_MONTH_MAX:g}\n', encoding="utf-8")
    return {**summary, "events": len(log), "broker_cash": cash, "bank_cash": round(float(led.cash.balance(SYSBANK)), 2), "positions": len(held), "switched_on": str(asof)}


# --- the removal of his record (the switch, step two) ----------------------------------------------------------------------------------

# Tables that hold HIS record, his answers and his conversations. Kept on purpose: market data, instruments, prices, the knowledge graph, the learner, missions and their
# research, house rules, the paper portfolio's own tables, and the US sleeve's tables (the sleeve stays as a capability).
PERSONAL_TABLES = ("fds", "fd_interest", "statement_periods", "known_gaps", "account_candidates", "recon_breaks", "kite_trades", "kite_snapshots", "tax_years", "carry_forward",
                   "inbox_items", "mail_seen", "mail_facts", "mail_scan", "bot_updates", "app_notes", "questions", "proposals", "decisions", "ready_plans", "limit_proposals",
                   "pot_ideas", "targets", "twin_days", "twin_trades", "hq_proposals", "hq_proposal_log", "hq_claims", "chats", "chat_messages", "chat_summary",
                   "theses", "watches", "hq_reminders")                 # (datasets, dataset_facts and theme_baskets stay: company data sheets and theme lists are public research, not his record)
PERSONAL_FILES = ("sources.toml", "sources.app.toml", "bank_rules.local.toml", "fd_holdings.toml", "targets.toml", "app/deposits.json", "app/ledger_build.json", "house_rules.md")
PERSONAL_DIRS = ("inbox/screens", "inbox/locked")                   # inside the profile folder; `inbox/market` is public company data and stays
APP_ROOT_JUNK = ("pm_old_*", "pm.zip", "backups", "verify")        # in the app's folder: old copies of the record, acceptance copies, the store backups
APP_REPO_DIRS = ("new", "drop")                                    # inside the checkout: his statement files and the dropped files
MEMORY_OWN = "memory(his answers)"


def _exists(con, table: str) -> bool:
    return bool(con.execute("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]).fetchone())


def purge_store(con, dry_run: bool = True) -> Dict[str, int]:
    """Delete his record from the store. Returns the rows each table held (before). The memory table loses only HIS answers; the agents' notes stay."""
    out: Dict[str, int] = {}
    for t in PERSONAL_TABLES:
        if _exists(con, t):
            out[t] = int(con.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
    if _exists(con, "memory"):
        out[MEMORY_OWN] = int(con.execute("SELECT count(*) FROM memory WHERE kind='answer'").fetchone()[0])
    if dry_run:
        return out
    from pflab.pm import store
    with store.transaction(con):
        for t in PERSONAL_TABLES:
            if t in out:
                con.execute(f"DELETE FROM {t}")
        if MEMORY_OWN in out:
            con.execute("DELETE FROM memory WHERE kind='answer'")
    return out


def personal_paths(pm_dir: Path, app_root: Optional[Path] = None, repo: Optional[Path] = None) -> List[Path]:
    """Every file or folder of his record outside the store that exists now."""
    pm_dir = Path(pm_dir)
    found = [pm_dir / f for f in PERSONAL_FILES] + [pm_dir / d for d in PERSONAL_DIRS]
    if (pm_dir / "inbox").is_dir():
        found += [f for f in sorted((pm_dir / "inbox").iterdir()) if f.is_file()]       # statements and tax files dropped straight into the inbox folder
    if app_root:
        for pat in APP_ROOT_JUNK:
            found += sorted(Path(app_root).glob(pat))
    if repo:
        for d in APP_REPO_DIRS:
            p = Path(repo) / d
            if p.exists():
                found += sorted(p.iterdir())                       # the contents, not the folder itself (the watcher needs it)
    return [p for p in found if p.exists()]


def purge_files(paths: List[Path]) -> int:
    n = 0
    for p in paths:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
        n += 1
    return n


def verify(con) -> Dict[str, object]:
    """What the account must look like after the switch. Every entry must hold; `ok` is all of them."""
    accounts = sorted(r[0] for r in con.execute("SELECT account_id FROM accounts").fetchall())
    lots = int(con.execute("SELECT count(*) FROM lots WHERE account_id = ?", [SYSBROKER]).fetchone()[0])
    other = int(con.execute("SELECT count(*) FROM lots WHERE account_id <> ?", [SYSBROKER]).fetchone()[0])
    bank = float(con.execute("SELECT coalesce(sum(amount), 0) FROM cash_ledger WHERE account_id = ?", [SYSBANK]).fetchone()[0])
    broker = float(con.execute("SELECT coalesce(sum(amount), 0) FROM cash_ledger WHERE account_id = ?", [SYSBROKER]).fetchone()[0])
    left = {t: int(con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) for t in PERSONAL_TABLES if _exists(con, t)}
    left = {t: n for t, n in left.items() if n}
    checks = {"only the two system accounts": accounts == [SYSBANK, SYSBROKER], "positions held": lots > 0, "no other lot owner": other == 0,
              "his personal tables are empty": not left,
              "cash is the fake cash": abs((bank + broker) - float(settings().get("start_cash_rupees", START_CASH))) < 1.0}
    return {"ok": all(checks.values()), "checks": checks, "accounts": accounts, "lots": lots, "bank": round(bank, 2), "broker": round(broker, 2), "personal_rows_left": left}


# --- the whole switch, in a safe order ---------------------------------------------------------------------------------------------------

def run_switch(con, pm_dir: Path, app_root: Optional[Path], repo: Optional[Path], now: datetime, apply: bool = False, start_cash: float = START_CASH,
               template_targets: Optional[Path] = None) -> dict:
    """Dry run (default): counts of what would be removed, nothing changed. Apply, in this order so the store can still be restored if anything is wrong:
    1. a safety copy of the store; 2. the new account replaces events and accounts; 3. his rows are deleted from the store and the old paper-only book is cleared;
    4. the account is verified; 5. ONLY THEN his files and the old copies are deleted, a neutral targets file is put back, and the safety copy is removed.
    Prints and returns counts and names of kinds, never his values."""
    from pflab.pm import store
    pm_dir = Path(pm_dir)
    if active(pm_dir):
        return {"done": False, "why": "the profile is already the system's own account"}
    asof = date.today()
    report = {"asof": str(asof), "store_rows": purge_store(con, dry_run=True), "paths": len(personal_paths(pm_dir, app_root, repo)), "applied": False}      # (a count: file names can carry account numbers)
    new_events, summary = history_events(con, asof)
    report["history"] = {k: v for k, v in summary.items() if k != "left_out"} | {"left_out": len(summary["left_out"])}
    if not apply:
        return report
    safety = (Path(app_root) if app_root else pm_dir.parent) / "switch_safety" / "ledger_before_switch.duckdb"
    built = switch(con, pm_dir, asof, now, start_cash=start_cash, backup_to=safety)
    purge_store(con, dry_run=False)
    for t in ("paper_lots", "paper_cash"):                                   # the old paper-only book: the ledger is the book now
        if _exists(con, t):
            con.execute(f"DELETE FROM {t}")
    v = verify(con)
    report.update({"applied": True, "built": built, "verify": v})
    if not v["ok"]:
        report["safety_copy_kept"] = str(safety)
        return report
    report["files_removed"] = purge_files(personal_paths(pm_dir, app_root, repo))
    if template_targets and Path(template_targets).exists():                 # the system has no targets of his: the empty template, so nothing that reads targets fails
        shutil.copy2(template_targets, pm_dir / "targets.toml")
    shutil.rmtree(safety.parent, ignore_errors=True)
    report["safety_copy_removed"] = True
    return report


def redate_opening(con, day: date, now: Optional[datetime] = None) -> int:
    """Move the two opening cash events (the fake bank's first deposit and its transfer to the broker) to `day` and re-derive. Returns events changed."""
    n = con.execute("SELECT count(*) FROM events WHERE ref LIKE 'start:%' AND trade_date <> ?", [day]).fetchone()[0]
    con.execute("UPDATE events SET trade_date = ? WHERE ref LIKE 'start:%'", [day])
    derive(con, now)
    return int(n)
