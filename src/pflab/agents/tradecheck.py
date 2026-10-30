"""The trade-check agent (PLAN A7, S43): after the daily Kite login, compare what Kite shows with the ledger and
ask the investor for anything missing. Read-only: it calls kite.trades(), holdings() and margins() through the
allowlisted client and never touches an order.

The ledger is rebuilt from documents (Console tradebook, contract notes, statements: tools/build_pm_ledger.py),
so a Kite execution is not written into it. It is staged in `kite_trades` as `pending` until a rebuild brings
the same trade in (matched by trade id, else by date, ISIN, side, quantity and price), then marked `in_ledger`.

Each run:
  1. stage today's executions (kite.trades() only returns today's);
  2. mark staged trades that the ledger now has;
  3. ask about a trade still missing from the ledger after STALE_DAYS (add the tradebook, rebuild);
  4. compare Kite holdings with the ledger at the start of today plus staged trades before today (a buy shows
     in Kite holdings from the next day, as T1); every difference becomes a question;
  5. compare Kite's cash balance (margins() live_balance) with the ledger's cash for the account; a gap above a
     rupee becomes a question.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from pflab.agents import questions as qs
from pflab.ingest import kite as km
from pflab.ledger import events as ev
from pflab.ledger import reconcile
from pflab.ledger.book import Ledger

STALE_DAYS = 5
CASH_TOL = 1.0                                   # rupees
AGENT = "trade-check"


@dataclass
class Report:
    asof: date
    account: str
    staged: int = 0
    resolved: int = 0
    pending: List[dict] = field(default_factory=list)
    breaks: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=reconcile.COLUMNS))
    cash: Optional[dict] = None
    asked: List[int] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    snapshot: Optional[dict] = None

    def render(self) -> str:
        lines = [f"Trade check {self.asof} ({self.account}): {self.staged} new Kite trade(s) staged, "
                 f"{self.resolved} now in the ledger, {len(self.pending)} still waiting for the tradebook."]
        if self.breaks.empty:
            lines.append("Holdings: Kite and the ledger agree.")
        for r in self.breaks.itertuples():
            lines.append(f"Holdings differ: {r.isin} ledger {r.a_value:g} vs Kite {r.b_value:g} ({r.note})")
        if self.cash:
            lines.append(f"Cash: Kite balance {self.cash['kite_available']:,.2f}; ledger {self.cash['ledger']:,.2f}")
        if self.asked:
            lines.append(f"{len(self.asked)} new question(s): see /questions")
        return "\n".join(lines + self.notes)


def zerodha_account(con) -> str:
    r = con.execute("SELECT account_id FROM accounts WHERE kind='demat' AND provider ILIKE '%zerodha%' "
                    "AND NOT coalesce(read_only, FALSE) ORDER BY account_id LIMIT 1").fetchone()
    if not r:
        raise LookupError("no Zerodha demat account in the ledger")
    return r[0]


def isin_of(con, symbol: str) -> Optional[str]:
    r = con.execute("SELECT isin FROM instruments WHERE upper(symbol)=upper(?) ORDER BY valid_to DESC NULLS FIRST LIMIT 1",
                    [symbol]).fetchone()
    return r[0] if r else None


def _key(d: date, isin: Optional[str], side: str, qty: float, price: float) -> tuple:
    return (d, isin, side, round(float(qty), 6), round(float(price), 2))


def stage(con, trades: pd.DataFrame, now: datetime) -> int:
    n = 0
    for r in trades.itertuples(index=False):
        if con.execute("SELECT 1 FROM kite_trades WHERE trade_id=?", [r.trade_id]).fetchone():
            continue
        con.execute("INSERT INTO kite_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [r.trade_id, r.order_id, r.date, r.symbol, r.exchange, isin_of(con, r.symbol), r.side, r.qty,
                     r.price, r.account, now, "pending", None])
        n += 1
    return n


def resolve(con, log: ev.EventLog, now: datetime) -> int:
    trades = [e for e in log.raw() if e.kind in ev.TRADE_KINDS]
    refs = {e.ref for e in trades}
    keys = {_key(e.date, e.isin, e.kind, e.qty, e.price) for e in trades}
    n = 0
    for tid, d, isin, side, qty, price in con.execute(
            "SELECT trade_id, trade_date, isin, side, qty, price FROM kite_trades WHERE status='pending'").fetchall():
        if tid in refs or _key(d, isin, side, qty, price) in keys:
            con.execute("UPDATE kite_trades SET status='in_ledger', resolved_at=? WHERE trade_id=?", [now, tid])
            qs.drop(con, f"trade:{tid}", now)
            n += 1
    return n


def expected_holdings(log: ev.EventLog, con, account: str, asof: date) -> Dict[tuple, float]:
    """Ledger positions at the start of `asof` plus staged trades dated before it."""
    pos = {k: q for k, q in Ledger.replay(log, upto=asof - timedelta(days=1)).positions().items() if k[0] == account}
    for isin, side, qty in con.execute("SELECT isin, side, qty FROM kite_trades WHERE status='pending' AND account_id=? "
                                       "AND trade_date < ? AND isin IS NOT NULL", [account, asof]).fetchall():
        pos[(account, isin)] = pos.get((account, isin), 0.0) + (qty if side == "buy" else -qty)
    return pos


def check(con, kite, asof: date, account: Optional[str] = None, now: Optional[datetime] = None) -> Report:
    now = now or datetime.now()
    account = account or zerodha_account(con)
    rep = Report(asof, account)
    from pflab.pm import today                       # S58b: the portfolio today is built on what Kite shows
    try:
        rep.snapshot = today.record(con, kite, account, now)
    except Exception as e:
        rep.notes.append(f"Kite snapshot not stored: {type(e).__name__}: {e}"[:200])
    rep.staged = stage(con, km.trades_frame(kite.trades(), account), now)
    log = ev.load(con)
    rep.resolved = resolve(con, log, now)
    for tid, d, sym, side, qty, price in con.execute(
            "SELECT trade_id, trade_date, symbol, side, qty, price FROM kite_trades WHERE status='pending' "
            "AND account_id=? ORDER BY trade_date, trade_id", [account]).fetchall():
        rep.pending.append({"trade_id": tid, "date": d, "symbol": sym, "side": side, "qty": qty, "price": price})
        if (asof - d).days >= STALE_DAYS:
            q = qs.ask(con, AGENT, f"trade:{tid}",
                       f"Kite trade {tid} ({side} {qty:g} {sym} at {price:,.2f} on {d}) is still not in the ledger after "
                       f"{STALE_DAYS} days. Add the Console tradebook and contract note to sources.toml and run "
                       "tools/build_pm_ledger.py, or tell me why it should not be there.", now)
            if q:
                rep.asked.append(q)
    kq: Dict[str, float] = {}
    t1: Dict[str, float] = {}
    sym: Dict[str, str] = {}
    for r in km.holdings_frame(kite.holdings()).itertuples():
        if r.isin:
            kq[r.isin] = kq.get(r.isin, 0.0) + r.qty
            t1[r.isin] = t1.get(r.isin, 0.0) + r.t1
            sym[r.isin] = r.symbol
    rep.breaks = reconcile.holdings_breaks("kite", kq, expected_holdings(log, con, account, asof), account=account)
    for i, r in rep.breaks.iterrows():
        if t1.get(r["isin"]) and abs((r["b_value"] - r["a_value"]) - t1[r["isin"]]) < 1e-6:
            rep.breaks.loc[i, "note"] = f"a recent buy of {t1[r['isin']]:g} (T1, not yet settled) is not in the ledger"
    reconcile.save_breaks(con, rep.breaks, f"tradecheck:{asof}", now)
    if rep.snapshot is not None:                                   # S67: a difference that has gone is not asked about any more
        current = {f"holding:{r.isin}:{r.a_value:g}:{r.b_value:g}" for r in rep.breaks.itertuples()}
        for (k,) in con.execute("SELECT subject_key FROM questions WHERE status='open' AND subject_key LIKE 'holding:%'").fetchall():
            if k not in current:
                qs.drop(con, k, now)
    for r in rep.breaks.itertuples():
        name = f"{sym.get(r.isin) or ''} ({r.isin})".strip()
        if r.note.startswith("a recent buy"):
            text = (f"Kite holds {r.b_value:g} of {name}, the ledger {r.a_value:g}: {r.note}. Add that day's Console "
                    "tradebook and contract note to sources.toml and run tools/build_pm_ledger.py.")
        else:
            text = (f"Kite holds {r.b_value:g} of {name}, the ledger {r.a_value:g} ({r.note}). Was there a trade, "
                    "transfer, IPO allotment or corporate action I have not seen? Send the document or tell me.")
        q = qs.ask(con, AGENT, f"holding:{r.isin}:{r.a_value:g}:{r.b_value:g}", text, now)
        if q:
            rep.asked.append(q)
    try:
        cash = km.funds_from_margins(kite.margins())
        led = float(Ledger.replay(log, upto=asof).cash_balance(account, asof))
        rep.cash = {"kite_available": cash["live_balance"], "ledger": led}
        if abs(cash["live_balance"] - led) <= CASH_TOL:
            for (k,) in con.execute("SELECT subject_key FROM questions WHERE status='open' AND subject_key LIKE ?", [f"cash:{account}:%"]).fetchall():
                qs.drop(con, k, now)
        if abs(cash["live_balance"] - led) > CASH_TOL:
            q = qs.ask(con, AGENT, f"cash:{account}:{led:.2f}:{cash['live_balance']:.2f}",
                       f"Kite's cash balance is {cash['live_balance']:,.2f}, the ledger's {led:,.2f}. Payouts to the bank, "
                       "buys or charges since the last Console funds statement? Add the latest Console ledger and bank "
                       "statement to sources.toml and run tools/build_pm_ledger.py.", now)
            if q:
                rep.asked.append(q)
    except Exception as e:                                         # cash is information; its failure is reported
        rep.notes.append(f"Cash not compared: {type(e).__name__}: {e}"[:200])
    return rep
