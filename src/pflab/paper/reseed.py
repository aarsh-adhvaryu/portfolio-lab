"""Re-seed the system's own account and paper book from his Kite holdings ONLY (S79, A45).

What it does, in this order (nothing is changed unless every earlier step worked):
  1. refuses when the store was already re-seeded (unless `force`);
  2. reads the Kite holdings (shares, ETFs, SGBs, anything Kite lists) and builds the new ledger events in memory and replays them (a failure here changes nothing);
  3. backs the store up to a `backups` folder beside the profile (DuckDB makes the copy; its row counts are checked, and the copy is opened to prove it reads);
  4. in ONE transaction: archives the old paper record (`<table>_archive_s79`, labelled, never deleted) and clears it from the live tables, drops what the account held beyond Kite
     (FDs, statement periods, any other account or folio), replaces the ledger with the starting positions (quantity and Kite's average price; an SGB or any holding without a
     price starts at that day's close, flagged `:cost_unknown` exactly as the system ledger flags an inherited holding) plus the fake bank and broker with the cash, writes the
     profile's `system_account.toml` (since, cash, topup_month_max, seed_date) and marks the first day of the new paper book.
The 40-session gate (`paper.manager.gate` via `paper.book.returns`), the scorecard and the paper claims count only from `paper_days`' first row, which is the new seed day.

Holding dates: Kite gives no purchase date. Each starting lot is dated the seed day (so a sale in the first year is estimated as short-term: the cautious tax estimate, labelled).
A holding may carry `acq_date` if one is known. Cash: the fake Rs 5,00,000 (A36), top-ups up to Rs 50,000 a month by `paper/funds.py`. His `targets.toml` is never touched.
"""
from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from pflab.ledger import events as ev, system
from pflab.ledger.book import Ledger

CASH = system.START_CASH
KEEP_LIVE = ("paper_lessons", "paper_watch", "paper_inputs", "paper_acts")      # state and what it learned or was asked, not the scored record: they stay
ACCOUNT_RECORD_TABLES = ("fds", "fd_interest", "statement_periods", "account_candidates", "recon_breaks", "tax_years", "carry_forward")   # tied to the account being replaced
OWN_EVENTS = "(ref LIKE 'sys:%' OR ref LIKE 'topup:%' OR ref LIKE 'tax estimate for sys:%' OR ref LIKE 'to broker:%')"


# --- helpers -----------------------------------------------------------------------------------------------------------------------------

def _exists(con, table: str) -> bool:
    return bool(con.execute("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]).fetchone())


def _count(con, table: str, where: str = "") -> int:
    return int(con.execute(f"SELECT count(*) FROM {table}" + (f" WHERE {where}" if where else "")).fetchone()[0]) if _exists(con, table) else 0


def already(con) -> Optional[dict]:
    """The last re-seed on record, or None."""
    if not _exists(con, "reseed_s79"):
        return None
    r = con.execute("SELECT reseed_id, applied_at, seed_date, cash, backup_file FROM reseed_s79 ORDER BY reseed_id DESC LIMIT 1").fetchone()
    return dict(zip(("reseed_id", "applied_at", "seed_date", "cash", "backup_file"), r)) if r else None


def normalise(con, kite_holdings) -> List[dict]:
    """Kite's holdings in any of: the raw `kite.holdings()` list (tradingsymbol, quantity, average_price ...), the frame of `ingest.kite.holdings_frame`, or a list of dicts
    with isin, symbol, qty, avg_price, last_price. One row per ISIN (a share held on NSE and BSE is one holding, quantity summed, average price weighted)."""
    import pandas as pd
    rows = kite_holdings.to_dict("records") if hasattr(kite_holdings, "to_dict") else list(kite_holdings or [])
    if rows and any(("tradingsymbol" in r or "quantity" in r) for r in rows):
        from pflab.ingest import kite as km
        rows = km.holdings_frame(rows).to_dict("records")
    out: Dict[str, dict] = {}
    missing = []
    for r in rows:
        qty = float(r.get("qty") or 0.0)
        if qty <= 1e-9 or (isinstance(r.get("qty"), float) and math.isnan(qty)):
            continue
        sym = str(r.get("symbol") or "").strip().upper() or None
        isin = str(r.get("isin") or "").strip().upper() or None
        if not isin and sym:
            q = con.execute("SELECT isin FROM instruments WHERE upper(symbol)=? ORDER BY listed DESC NULLS LAST LIMIT 1", [sym]).fetchone()
            isin = q[0] if q else None
        if not isin:
            missing.append(sym or "?")
            continue
        px = r.get("avg_price")
        px = 0.0 if px is None or (isinstance(px, float) and math.isnan(px)) else float(px)
        last = r.get("last_price")
        last = 0.0 if last is None or (isinstance(last, float) and math.isnan(last)) else float(last)
        a = out.get(isin)
        if a is None:
            out[isin] = {"isin": isin, "symbol": sym, "name": r.get("name"), "qty": qty, "cost": qty * px if px > 0 else 0.0, "priced_qty": qty if px > 0 else 0.0,
                         "last_price": last, "acq_date": r.get("acq_date")}
        else:
            a["qty"] += qty
            a["cost"] += qty * px if px > 0 else 0.0
            a["priced_qty"] += qty if px > 0 else 0.0
            a["last_price"] = a["last_price"] or last
    if missing:
        raise ValueError(f"Kite lists holdings with no ISIN that the record can find: {', '.join(missing)}")
    res = []
    for a in out.values():
        a["avg_price"] = a["cost"] / a["priced_qty"] if a["priced_qty"] > 0 else 0.0
        res.append(a)
    if not res:
        raise ValueError("Kite shows no holdings: there is nothing to seed the account from")
    return sorted(res, key=lambda a: a["isin"])


def seed_day_for(con, now: datetime) -> date:
    """The latest exchange session with a stored close (the paper book is marked at closes), else today."""
    r = con.execute("SELECT max(date) FROM prices WHERE date <= ? AND source='nse_bhavcopy'", [now.date()]).fetchone()[0]
    return r or now.date()


def _register(con, hs: List[dict], now: datetime) -> List[str]:
    """Instruments Kite lists that the master does not know (an SGB, a new ETF): added, classified by their own words (no guess about tax: REVIEW stays REVIEW)."""
    from pflab.pm import instruments as ins
    have = {r[0] for r in con.execute("SELECT isin FROM instruments").fetchall()}
    new = [h for h in hs if h["isin"] not in have]
    rows = [{"isin": h["isin"], "name": h.get("name") or h.get("symbol"), "symbol": h.get("symbol"),
             "series": "GB" if (h.get("symbol") or "").startswith(("SGB", "GOLDBOND")) else None, "listed": True} for h in new]
    ins.register_missing(con, rows, "A45 re-seed from Kite holdings", now)
    for h in new:                                          # an INF.. security the master did not know is a fund traded on the exchange: an ETF (gold or foreign by name)
        if h["isin"].startswith("INF"):
            con.execute("UPDATE instruments SET asset_class='etf', tax_class=CASE WHEN regexp_matches(lower(coalesce(name, symbol, '')), 'gold|silver|nasdaq|s&p|hang|fang|overseas|international|global') "
                        "THEN 'LISTED_NONEQUITY' ELSE tax_class END, tax_class_reason='ETF by its ISIN (INF) and Kite listing' WHERE isin=? AND asset_class='unknown'", [h["isin"]])
    return [h["isin"] for h in new]


def build_events(con, hs: List[dict], seed_day: date, cash: float) -> tuple:
    """The new ledger's events (starting positions, their funding that only lets the replay hold, the fake bank and its transfer), replayed. Returns (log, ledger, summary)."""
    from pflab.paper import book
    buys, unknown, no_price = [], [], []
    for h in hs:
        price, flag = float(h["avg_price"]), ""
        if price <= 0:                                      # inherited (an SGB) or no price from Kite: the day's close, flagged, so no gain is claimed on it
            px = book.close_on(con, h["isin"], seed_day)
            price = float(px[1]) if px else float(h.get("last_price") or 0.0)
            flag = ":cost_unknown"
            unknown.append(h["symbol"] or h["isin"])
            if price <= 0:
                no_price.append(h["symbol"] or h["isin"])
        meta = book.inst(con, h["isin"])
        d = h.get("acq_date") or seed_day
        d = date.fromisoformat(str(d)[:10]) if not isinstance(d, date) else d
        buys.append(ev.Event(kind="buy", account_id=system.SYSBROKER, date=d, isin=h["isin"], qty=float(h["qty"]), price=price,
                             ref=f"seed:kite:{h['symbol'] or h['isin']}{flag}", tax_class=meta["tax_class"]))
    cost = sum(b.qty * b.price for b in buys)
    first = min(b.date for b in buys)
    fund = math.ceil(cost * 100) / 100
    events = [ev.Event(kind="deposit", account_id=system.SYSBROKER, date=first, amount=fund, ref="seed:history (not money: it only lets the starting positions replay)")] + buys
    if fund - cost > 1e-9:
        events.append(ev.Event(kind="withdrawal", account_id=system.SYSBROKER, date=max(b.date for b in buys), amount=fund - cost, ref="seed:history rounding"))
    events += system.opening_cash_events(seed_day, cash)
    log = ev.EventLog()
    for i, e in enumerate(events, start=1):
        log.append(replace(e, event_id=i))
    led = Ledger.replay(log)                                # raises when the positions do not replay: nothing has been changed yet
    broker = round(float(led.cash.balance(system.SYSBROKER)), 2)
    bank = round(float(led.cash.balance(system.SYSBANK)), 2)
    if abs(broker - cash) > 0.01 or abs(bank) > 0.01:
        raise RuntimeError(f"the fake cash is not what was asked: broker {broker}, bank {bank}, wanted {cash}")
    return log, led, {"positions": len(buys), "cost_unknown": unknown, "no_price": no_price, "history_funding": round(cost, 2), "broker_cash": broker, "bank_cash": bank}


def _archive(con, table: str, archive_id: int, label: str, where: str = "", delete: bool = False) -> int:
    """Copy rows into `<table>_archive_s79` (made from the source's own columns the first time; later columns are added), tagged with the archive id and its label."""
    arch = f"{table}_archive_s79"
    src = [r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name=? ORDER BY ordinal_position", [table]).fetchall()]
    if not _exists(con, arch):
        con.execute(f"CREATE TABLE {arch} AS SELECT *, CAST(NULL AS INTEGER) AS archive_id, CAST(NULL AS VARCHAR) AS archive_label FROM {table} WHERE false")
    else:
        have = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name=?", [arch]).fetchall()}
        types = {r[0]: r[1] for r in con.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name=?", [table]).fetchall()}
        for c in src:
            if c not in have:
                con.execute(f"ALTER TABLE {arch} ADD COLUMN {c} {types[c]}")
    w = f" WHERE {where}" if where else ""
    n = int(con.execute(f"SELECT count(*) FROM {table}{w}").fetchone()[0])
    if n:
        cols = ", ".join(src)
        con.execute(f"INSERT INTO {arch} BY NAME SELECT {cols}, ? AS archive_id, ? AS archive_label FROM {table}{w}", [archive_id, label])
        if delete:
            con.execute(f"DELETE FROM {table}{w}")
    return n


def paper_tables(con) -> List[str]:
    return sorted(r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'paper\\_%' ESCAPE '\\' AND table_name NOT LIKE '%\\_archive\\_s79' ESCAPE '\\' "
                                            "AND table_type='BASE TABLE'").fetchall())


def snapshot(con) -> dict:
    """Counts the before/after tables show: accounts, events, lots by owner, cash by account, the paper record, the personal rows."""
    acc = [r[0] for r in con.execute("SELECT account_id FROM accounts ORDER BY 1").fetchall()]
    lots = {r[0]: (int(r[1]), round(float(r[2]), 4)) for r in con.execute("SELECT account_id, count(*), coalesce(sum(qty), 0) FROM lots GROUP BY 1 ORDER BY 1").fetchall()}
    cash = {r[0]: round(float(r[1]), 2) for r in con.execute("SELECT account_id, coalesce(sum(amount), 0) FROM cash_ledger GROUP BY 1 ORDER BY 1").fetchall()}
    return {"accounts": acc, "events": _count(con, "events"), "lots_by_account": lots, "cash_by_account": cash,
            "paper": {t: _count(con, t) for t in paper_tables(con)}, "account_record": {t: _count(con, t) for t in ACCOUNT_RECORD_TABLES if _exists(con, t)},
            "archives": {r[0]: _count(con, r[0]) for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%\\_archive\\_s79' ESCAPE '\\' ORDER BY 1").fetchall()}}


def _flag_text(now: datetime, cash: float, seed_day: date, topup_max: float) -> str:
    return (f'since = "{now:%Y-%m-%dT%H:%M:%S}"\nstart_cash_rupees = {cash:g}\ntopup_month_max = {topup_max:g}\n'
            f'seed_date = "{seed_day:%Y-%m-%d}"\nseeded_from = "kite holdings (A45)"\n')


# --- the re-seed -------------------------------------------------------------------------------------------------------------------------

def reseed(con, kite_holdings, now: datetime, cash: float = CASH, *, pm_dir: Optional[Path] = None, seed_day: Optional[date] = None, force: bool = False,
           backup_dir: Optional[Path] = None, market: str = "IN") -> dict:
    """Re-seed the system's account and paper book from `kite_holdings`. See the module text. Returns a report (counts, never values of anyone's record); `done` False with a
    reason when the store was already re-seeded (give `force=True` to do it again: the paper record since the last seed is archived the same way)."""
    from pflab.paper import book
    from pflab.pm import store
    prev = already(con)
    if prev and not force:
        return {"done": False, "skipped": True, "why": f"already re-seeded on {prev['seed_date']} (applied {str(prev['applied_at'])[:16]}); nothing was changed", "seed_date": str(prev["seed_date"])}
    pm = Path(pm_dir) if pm_dir else store.pm_dir()
    if system.flag_path(pm) != system.flag_path():
        raise ValueError("pm_dir must be the profile the store belongs to (PFLAB_PM_DIR): the paper book reads the account flag from there")
    hs = normalise(con, kite_holdings)
    day = seed_day or seed_day_for(con, now)
    log, led, built = build_events(con, hs, day, float(cash))        # (a failure raises here, before anything is changed)
    before = snapshot(con)

    db = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    db_file = Path(db[0]) if db and db[0] else Path(str(store.db_path()))
    from pflab.service import backup as bk
    bdir = Path(backup_dir) if backup_dir else db_file.resolve().parent.parent / "backups"
    done_bk = bk.backup(con, db_file, bdir, now, keep=30)
    import duckdb
    chk = duckdb.connect(done_bk["file"], read_only=True)                # the copy must open and read
    try:
        events_in_copy = int(chk.execute("SELECT count(*) FROM events").fetchone()[0])
    finally:
        chk.close()

    first_day = prev["seed_date"] if prev else None
    if first_day is None:
        r = con.execute("SELECT min(day) FROM paper_days").fetchone()[0] if _exists(con, "paper_days") else None
        first_day = r or (con.execute("SELECT min(CAST(made_at AS DATE)) FROM paper_decisions").fetchone()[0] if _exists(con, "paper_decisions") else None)
    label = f"paper record {first_day or '2026-11-02'} to {day}, archived by A45"
    flag = system.flag_path(pm)
    old_flag = flag.read_text(encoding="utf-8") if flag.exists() else None
    topup_max = float(system.settings(pm).get("topup_month_max", system.TOPUP_MONTH_MAX))
    rows: Dict[str, int] = {}
    try:
        with store.transaction(con):
            aid = store.next_id(con, "paper_archive_s79", "archive_id")
            paper_cases = "case_id IN (SELECT case_id FROM hq_missions WHERE origin='paper')"
            for t in paper_tables(con):
                rows[t] = _archive(con, t, aid, label, delete=t not in KEEP_LIVE)
            if _exists(con, "hq_claims"):
                rows["hq_claims (paper missions)"] = _archive(con, "hq_claims", aid, label, paper_cases, delete=True)
            if _exists(con, "hq_case_reviews"):
                rows["hq_case_reviews (paper missions)"] = _archive(con, "hq_case_reviews", aid, label, paper_cases)
            rows["events (the system's own)"] = _archive(con, "events", aid, label, OWN_EVENTS)
            con.execute("INSERT INTO paper_archive_s79 VALUES (?,?,?,?,?,?,?)", [aid, market, now, label, first_day, day, json.dumps(rows, sort_keys=True)])
            for t in ACCOUNT_RECORD_TABLES:                                   # the account is Kite's holdings only: no FD, statement or tax-pack rows
                if _exists(con, t):
                    con.execute(f"DELETE FROM {t}")
            added = _register(con, hs, now)
            con.execute("DELETE FROM events")
            con.execute("DELETE FROM accounts")
            con.execute("INSERT INTO accounts (account_id, kind, provider, dormant, read_only) VALUES (?,?,?,?,?)", [system.SYSBANK, "bank", "the system's fake bank", False, False])
            con.execute("INSERT INTO accounts (account_id, kind, provider, dormant, read_only) VALUES (?,?,?,?,?)", [system.SYSBROKER, "demat", "the system's fake broker", False, False])
            ev.save(con, log, now)
            led.write_derived(con, now)
            flag.write_text(_flag_text(now, float(cash), day, topup_max), encoding="utf-8")
            book.mark(con, day)
            rid = store.next_id(con, "reseed_s79", "reseed_id")
            con.execute("INSERT INTO reseed_s79 VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        [rid, market, now, day, float(cash), "kite holdings", json.dumps([{"isin": h["isin"], "symbol": h["symbol"], "qty": h["qty"], "avg_price": round(h["avg_price"], 4)} for h in hs]),
                         aid, done_bk["file"], bool(force), json.dumps({**built, "registered": added}, default=str)])
    except BaseException:
        if old_flag is None:
            flag.unlink(missing_ok=True)
        else:
            flag.write_text(old_flag, encoding="utf-8")
        raise
    return {"done": True, "seed_date": str(day), "cash": float(cash), **built, "registered_instruments": added, "archive": {"id": aid, "label": label, "rows": rows},
            "backup": {"file": done_bk["file"], "rows": done_bk["rows"], "events_in_copy": events_in_copy}, "before": before, "after": snapshot(con),
            "personal_files_present": len(system.personal_paths(pm)), "forced": bool(force)}


def preview(con, kite_holdings, now: datetime, cash: float = CASH, seed_day: Optional[date] = None) -> dict:
    """A dry run: what would be seeded (positions, which are flagged inherited, the funding, the fake cash) and whether the replay holds. Writes nothing, makes no backup."""
    prev = already(con)
    hs = normalise(con, kite_holdings)
    day = seed_day or seed_day_for(con, now)
    _, _, built = build_events(con, hs, day, float(cash))
    return {"would_seed": str(day), "already_reseeded": str(prev["seed_date"]) if prev else None, **built, "snapshot_now": snapshot(con)}
