"""Event log: the ledger's only input (PLAN §3, §4).

Every position, lot and cash balance is derived by replaying events, so the
log is append-only and a restore is `load` + replay. Money is float rupees,
quantities float units (fractional for MFs), dates `datetime.date`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

TRADE_KINDS = ("buy", "sell")
CASH_KINDS = ("deposit", "withdrawal", "dividend", "interest", "charge", "overdraft_limit", "cash_transfer")
OTHER_KINDS = ("transfer", "corp_action", "ipo_block", "ipo_allot", "ipo_release", "ipo_list")  # transfer: in-kind move between accounts, cost and date kept
KINDS = TRADE_KINDS + CASH_KINDS + OTHER_KINDS

# Same-day replay order: money in, then buys, then sells, so a sale never
# precedes the purchase it consumes and a buy is never starved of funds.
_PRIORITY = {"overdraft_limit": 0, "deposit": 1, "cash_transfer": 1, "corp_action": 2, "transfer": 2, "buy": 3, "ipo_block": 3,
             "ipo_allot": 4, "ipo_release": 4, "ipo_list": 5, "sell": 4,
             "dividend": 5, "interest": 5, "charge": 6, "withdrawal": 7}


class EventError(ValueError):
    pass


@dataclass(frozen=True)
class Event:
    kind: str
    account_id: str
    date: date
    isin: Optional[str] = None
    qty: float = 0.0
    price: float = 0.0
    amount: float = 0.0          # cash events: gross amount, positive
    fees: Dict[str, float] = field(default_factory=dict)  # brokerage, stt, ... (tds for dividends)
    ref: str = ""
    source_doc_sha: str = ""
    tax_class: Optional[str] = None
    counter_account: Optional[str] = None  # transfer destination
    params: Dict[str, Any] = field(default_factory=dict)  # corp_action: {"action": ..., ...}
    event_id: int = 0

    def __post_init__(self):
        if self.kind not in KINDS:
            raise EventError(f"unknown event kind {self.kind!r}")
        if not isinstance(self.date, date) or isinstance(self.date, datetime):
            raise EventError("date must be a datetime.date")
        if self.kind in TRADE_KINDS or self.kind == "transfer":
            if not self.isin:
                raise EventError(f"{self.kind} needs an isin")
            if self.qty <= 0:
                raise EventError(f"{self.kind} qty must be positive")
        if self.kind in TRADE_KINDS and self.price < 0:
            raise EventError("price cannot be negative")
        if self.kind in ("transfer", "cash_transfer") and not self.counter_account:
            raise EventError(f"{self.kind} needs counter_account")
        if self.kind == "cash_transfer" and self.amount <= 0:
            raise EventError("cash_transfer needs a positive amount")
        if self.kind in CASH_KINDS and self.amount < 0:
            raise EventError(f"{self.kind} amount is positive; the kind gives the direction")
        if self.kind == "dividend" and not self.isin:
            raise EventError("dividend needs an isin")
        if self.kind.startswith("ipo_") and not self.ref:
            raise EventError(f"{self.kind} needs ref = the IPO id")
        if self.kind == "ipo_block" and self.amount <= 0:
            raise EventError("ipo_block needs a positive amount")
        if self.kind == "ipo_block" and not {"bid_qty", "bid_price"} <= set(self.params):
            raise EventError("ipo_block needs params bid_qty and bid_price")
        if self.kind == "ipo_allot" and (not self.isin or self.qty <= 0 or not self.params.get("demat_account")):
            raise EventError("ipo_allot needs isin, qty and params['demat_account']")
        if self.kind == "ipo_list" and not self.isin:
            raise EventError("ipo_list needs an isin")
        if self.kind == "corp_action" and (not self.isin or not self.params.get("action")):
            raise EventError("corp_action needs an isin and params['action']")
        if any(v < 0 for v in self.fees.values()):
            raise EventError("fees are positive amounts")

    @property
    def fee_total(self) -> float:
        """Every charge paid (moves cash): all fees except TDS."""
        return float(sum(v for k, v in self.fees.items() if k != "tds"))

    @property
    def cost_fee_total(self) -> float:
        """Charges that enter the cost of acquisition or reduce the sale consideration: STT is paid but
        is not deductible in computing capital gains (s.48; same rule as tax.india_lots)."""
        return float(sum(v for k, v in self.fees.items() if k not in ("tds", "stt")))

    @property
    def sort_key(self):
        return (self.date, _PRIORITY[self.kind], self.event_id)


class EventLog:
    """Append-only; ids are assigned in insertion order."""

    def __init__(self, events: Iterable[Event] = ()):
        self._events: List[Event] = []
        self._ids = set()
        for e in events:
            self.append(e)

    def append(self, e: Event) -> Event:
        if e.event_id == 0:
            e = replace(e, event_id=max(self._ids, default=0) + 1)
        if e.event_id in self._ids:
            raise EventError(f"event_id {e.event_id} already used")
        self._ids.add(e.event_id)
        self._events.append(e)
        return e

    def __len__(self):
        return len(self._events)

    def __iter__(self):
        return iter(self.ordered())

    def ordered(self) -> List[Event]:
        return sorted(self._events, key=lambda e: e.sort_key)

    def raw(self) -> List[Event]:
        return list(self._events)


# --- persistence (migration 2) ---------------------------------------------

_COLS = ("event_id, kind, account_id, trade_date, isin, qty, price, amount, fees_json, ref, "
         "source_doc_sha, tax_class, counter_account, params_json, ingested_at")


def save(con, log: EventLog, now: Optional[datetime] = None) -> int:
    """Insert events not yet stored (by event_id). Returns rows inserted."""
    now = now or datetime.now()
    have = {r[0] for r in con.execute("SELECT event_id FROM events").fetchall()}
    new = [e for e in log.raw() if e.event_id not in have]
    for e in new:
        con.execute(f"INSERT INTO events ({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [e.event_id, e.kind, e.account_id, e.date, e.isin, e.qty, e.price, e.amount,
                     json.dumps(e.fees, sort_keys=True), e.ref, e.source_doc_sha, e.tax_class,
                     e.counter_account, json.dumps(e.params, sort_keys=True, default=str), now])
    return len(new)


def _params_load(js) -> Dict[str, Any]:
    p = json.loads(js or "{}")
    for k, v in list(p.items()):          # dates round-trip as ISO strings
        if isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-":
            try:
                p[k] = date.fromisoformat(v)
            except ValueError:
                pass
    return p


def load(con) -> EventLog:
    rows = con.execute(f"SELECT {_COLS} FROM events ORDER BY event_id").fetchall()
    log = EventLog()
    for r in rows:
        log.append(Event(kind=r[1], account_id=r[2], date=r[3], isin=r[4], qty=r[5], price=r[6],
                         amount=r[7], fees=json.loads(r[8] or "{}"), ref=r[9] or "",
                         source_doc_sha=r[10] or "", tax_class=r[11], counter_account=r[12],
                         params=_params_load(r[13]), event_id=r[0]))
    return log
