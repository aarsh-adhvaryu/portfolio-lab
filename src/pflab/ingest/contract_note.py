"""Zerodha contract note PDF -> trades and the charges actually levied (PLAN S4).

The contract note is the truth for charges (the tradebook carries none). One note per trading day: a
per-ISIN summary, the levies block (NET TOTAL column) and Annexure A with one line per execution, whose
Trade No equals the Console tradebook's trade_id. The PDF is password-protected (PAN); it is decrypted in
memory by pypdf and nothing is written.

Checks, any failure refuses the note: annexure trades sum to the per-ISIN summary; pay-in/pay-out
obligation plus the levies equals the net amount (to the paisa per levy line).

Allocation to trades (`allocate`): the note gives levies for the day, not per trade. Stamp duty is a buy-side
levy and goes to buys only; every other levy is split by trade value. Per-trade amounts are rounded to the
paisa and the residual goes to the largest trade, so each levy's allocation sums exactly to the note.
Built from one real note (2026-09-29, a single BSE buy); sell and multi-trade shapes are tested on synthetic
text in the same layout.
"""
from __future__ import annotations

import dataclasses
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

import pandas as pd

from pflab.ledger.events import Event

TOL = 0.011                      # rupees per levy line: the note prints levies rounded to the paisa

LEVIES = [                       # (label at the start of the line, fee key)
    ("Taxable value of Supply (Brokerage)", "brokerage"),
    ("Exchange transaction charges", "exchange_txn"),
    ("Clearing charges", "clearing"),
    ("CGST", "cgst"),
    ("SGST", "sgst"),
    ("IGST", "igst"),
    ("Securities transaction tax", "stt"),
    ("SEBI turnover fees", "sebi"),
    ("Stamp duty", "stamp_duty"),
]
BUY_ONLY = {"stamp_duty"}

_NUM = r"\(?[−-]?[\d,]+\.\d+\)?"
_SUMMARY = re.compile(r"^(IN[A-Z0-9]{10})\s+(.+?)\s+(\d+)\s+([\d.]+)\s+[\d.]+\s+[\d.]+\s+([\d,]+\.\d+)\s+"
                      r"(\d+)\s+([\d.]+)\s+[\d.]+\s+[\d.]+\s+([\d,]+\.\d+)\s+([−-]?\d+)\s+([−-]?[\d,]+\.\d+)\s*$")
_TRADE = re.compile(r"^(\d+)\s+(\d\d:\d\d:\d\d)\s+(\d+)\s+(\d\d:\d\d:\d\d)\s+(\S+?)/(IN[A-Z0-9]{10})\s+([BS])\s+"
                    r"(NSE|BSE)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+(?:[\d.]+\s+)?(\(?[\d,]+\.\d+\)?)")


class ContractNoteError(ValueError):
    pass


@dataclass
class ContractNote:
    number: str
    trade_date: date
    settlement_date: Optional[date]
    trades: pd.DataFrame                       # trade_id, order_id, trade_time, isin, side, exchange, qty, price, value
    levies: Dict[str, float]                   # fee key -> rupees (positive = paid)
    obligation: float                          # + receivable / - payable, before levies
    net_amount: float                          # + receivable / - payable by the client
    summary: List[dict] = field(default_factory=list)


def _amount(s: str) -> float:
    """'(17690.00)' -> -17690.0 (payable); '−17690.00' -> -17690.0; '123.40' -> 123.4."""
    s = s.strip().replace(",", "").replace("−", "-")
    neg = s.startswith("(") and s.endswith(")")
    v = float(s.strip("()"))
    return -abs(v) if neg else v


def read_text(path: Union[str, Path], password: Optional[str] = None) -> str:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(Path(path).read_bytes()))
    if r.is_encrypted:
        if not password or not r.decrypt(password):
            raise ContractNoteError("the contract note is password-protected (PAN): pass the right password")
    return "\n".join(pg.extract_text() or "" for pg in r.pages)


def _checked(number: str, trade_date: date, settlement_date: Optional[date], rows: List[dict],
             levies: Dict[str, float], obligation: float, net: float, summary: List[dict]) -> ContractNote:
    """The reconciliation every note must pass, whatever file it came from."""
    trades = pd.DataFrame(rows, columns=["trade_id", "order_id", "trade_time", "isin", "side", "exchange", "qty", "price", "value"])
    if trades.empty:
        raise ContractNoteError("no trades in Annexure A")
    if trades["trade_id"].duplicated().any():
        raise ContractNoteError("a trade number appears twice in Annexure A")

    for s in summary:
        g = trades[trades["isin"] == s["isin"]]
        b, sl = g[g["side"] == "buy"], g[g["side"] == "sell"]
        if int(b["qty"].sum()) != s["buy_qty"] or int(sl["qty"].sum()) != s["sell_qty"] \
                or abs(b["value"].sum() - s["buy_value"]) > TOL or abs(sl["value"].sum() - s["sell_value"]) > TOL:
            raise ContractNoteError(f"Annexure A trades for {s['isin']} do not add up to the summary")
    if summary and set(trades["isin"]) != {s["isin"] for s in summary}:
        raise ContractNoteError("Annexure A and the summary list different ISINs")
    flows = trades["value"].where(trades["side"] == "sell", -trades["value"]).sum()
    if abs(flows - obligation) > TOL:
        raise ContractNoteError(f"trades net to {flows:,.2f} but the obligation is {obligation:,.2f}")
    if abs(obligation - sum(levies.values()) - net) > TOL * max(len(levies), 1):
        raise ContractNoteError(f"obligation {obligation:,.2f} less levies {sum(levies.values()):,.2f} "
                                f"is not the net amount {net:,.2f}")
    return ContractNote(number, trade_date, settlement_date, trades, levies, obligation, net, summary)


def parse_text(text: str) -> ContractNote:
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    m = re.search(r"Contract Note No:\s*(\S+)", text)
    td = re.search(r"Trade Date:\s*(\d\d/\d\d/\d{4})", text)
    if not m or not td:
        raise ContractNoteError("not a Zerodha contract note: no Contract Note No / Trade Date")
    sd = re.search(r"Settlement Date:\s*(\d\d/\d\d/\d{4})", text)
    as_date = lambda s: datetime.strptime(s, "%d/%m/%Y").date()

    def last_amount(label: str) -> Optional[float]:
        for ln in lines:
            if ln.startswith(label):
                nums = re.findall(_NUM, ln[len(label):])
                return _amount(nums[-1]) if nums else 0.0
        return None

    levies: Dict[str, float] = {}
    for label, key in LEVIES:
        v = last_amount(label)
        if v:
            levies[key] = round(abs(v), 2)
    obligation, net = last_amount("Pay in/Pay out obligation"), last_amount("Net amount receivable/(payable by client)")
    if obligation is None or net is None:
        raise ContractNoteError("levies block not found (Pay in/Pay out obligation, Net amount)")

    summary = []
    for ln in lines:
        s = _SUMMARY.match(ln)
        if s:
            summary.append(dict(isin=s[1], symbol=s[2], buy_qty=int(s[3]), buy_value=_amount(s[5]),
                                sell_qty=int(s[6]), sell_value=_amount(s[8]), net_qty=int(s[9].replace("−", "-")),
                                net_obligation=_amount(s[10])))
    rows = []
    for ln in lines:
        t = _TRADE.match(ln)
        if t:
            qty, price = int(t[9]), float(t[11])
            rows.append(dict(trade_id=t[3], order_id=t[1], trade_time=t[4], isin=t[6], side="buy" if t[7] == "B" else "sell",
                             exchange=t[8], qty=qty, price=price, value=round(abs(_amount(t[12])), 2)))
    return _checked(m[1], as_date(td[1]), as_date(sd[1]) if sd else None, rows, levies, obligation, net, summary)


def parse(path: Union[str, Path], password: Optional[str] = None) -> ContractNote:
    return parse_text(read_text(path, password))


def _xl_date(v) -> Optional[date]:
    if v is None or str(v).strip() == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    raise ContractNoteError(f"unparseable date {v!r}")


def _sheet_note(rows: List[list]) -> Optional[ContractNote]:
    cells = [[("" if c is None else str(c).strip()) for c in r] for r in rows]

    def after(label: str) -> Optional[str]:
        for r in cells:
            for j, c in enumerate(r):
                if c.upper().startswith(label.upper()):
                    rest = [x for x in r[j + 1:] if x]
                    return rest[0] if rest else None
        return None

    number = after("CONTRACT NOTE NO")
    if not number:
        return None
    td = _xl_date(after("Trade Date"))
    if td is None:
        raise ContractNoteError(f"contract note {number}: no trade date")
    head = next((i for i, r in enumerate(cells) if r and r[0] == "Order No."), None)
    if head is None:
        raise ContractNoteError(f"contract note {number}: no trade table")
    col = {name: j for j, name in enumerate(cells[head])}

    def at(r, prefix):
        j = next((j for n, j in col.items() if n.startswith(prefix)), None)
        if j is None:
            raise ContractNoteError(f"contract note {number}: no '{prefix}' column")
        return r[j] if j < len(r) else ""

    trades, i = [], head + 1
    while i < len(cells) and not cells[i][0].startswith("Pay in/Pay out obligation"):
        r = cells[i]
        if r[0].isdigit():
            desc = at(r, "Security/Contract Description")
            m = re.search(r"/(IN[A-Z0-9]{10})$", desc)
            if not m:
                raise ContractNoteError(f"contract note {number}: '{desc}' is not an equity ISIN line")
            trades.append(dict(trade_id=at(r, "Trade No"), order_id=r[0], trade_time=at(r, "Trade Time"), isin=m[1],
                               side="buy" if at(r, "Buy(B)") == "B" else "sell", exchange=at(r, "Exchange"),
                               qty=int(float(at(r, "Quantity"))), price=float(at(r, "Gross Rate")),
                               value=round(abs(float(at(r, "Net Total"))), 2)))
        i += 1

    def last_amount(label: str) -> Optional[float]:
        for r in cells:
            if r and r[0].startswith(label):
                vals = [x for x in r[1:] if x]
                return float(vals[-1].replace(",", "")) if vals else 0.0
        return None

    levies = {key: round(abs(v), 2) for label, key in LEVIES if (v := last_amount(label))}
    obligation, net = last_amount("Pay in/Pay out obligation"), last_amount("Net amount receivable/(payable by client")
    if obligation is None or net is None:
        raise ContractNoteError(f"contract note {number}: levies block not found")
    return _checked(number, td, _xl_date(after("Settlement Date")), trades, levies, obligation, net, [])


def parse_xlsx(path: Union[str, Path]) -> List[ContractNote]:
    """Console's contract-note Excel download: one sheet per trading day, trades then the levies block
    (NET TOTAL column, payable negative). No per-ISIN summary, so the checks are the obligation ones."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(Path(path).read_bytes()), data_only=True)
    notes = [n for ws in wb.worksheets if (n := _sheet_note([list(r) for r in ws.iter_rows(values_only=True)]))]
    if not notes:
        raise ContractNoteError("no contract note in the workbook")
    return notes


def allocate(note: ContractNote) -> Dict[str, Dict[str, float]]:
    """trade_id -> fee dict (the Event `fees` shape). Each levy's allocations sum exactly to the note."""
    out: Dict[str, Dict[str, float]] = {t: {} for t in note.trades["trade_id"]}
    for key, total in note.levies.items():
        base = note.trades[note.trades["side"] == "buy"] if key in BUY_ONLY else note.trades
        if base.empty or base["value"].sum() <= 0:
            raise ContractNoteError(f"{key} of Rs {total:,.2f} has no {'buy ' if key in BUY_ONLY else ''}trade to go to")
        shares = {r.trade_id: float(round(total * r.value / base["value"].sum(), 2)) for r in base.itertuples()}
        biggest = base.loc[base["value"].idxmax(), "trade_id"]
        shares[biggest] = float(round(shares[biggest] + total - sum(shares.values()), 2))
        for tid, v in shares.items():
            if v:
                out[tid][key] = v
    return out


def apply_fees(events: List[Event], notes: Iterable[ContractNote]) -> Tuple[List[Event], dict]:
    """Tradebook buy/sell events (ref = trade_id) with their contract-note levies set as `fees`. A note trade
    whose side, ISIN or quantity differs from the event is refused; trades with no note are reported."""
    alloc, by_id = {}, {}
    for n in notes:
        for tid, fees in allocate(n).items():
            alloc[tid] = fees
        by_id.update({r.trade_id: r for r in n.trades.itertuples()})
    out, matched = [], set()
    for e in events:
        if e.kind in ("buy", "sell") and e.ref in alloc:
            t = by_id[e.ref]
            if (t.side, t.isin, float(t.qty)) != (e.kind, e.isin, float(e.qty)) or abs(t.price - e.price) > 0.005:
                raise ContractNoteError(f"trade {e.ref}: the contract note and the tradebook disagree")
            e = dataclasses.replace(e, fees={**e.fees, **alloc[e.ref]})
            matched.add(e.ref)
        out.append(e)
    trades = [e for e in events if e.kind in ("buy", "sell")]
    return out, {"with_fees": len(matched),
                 "without_note": sorted({(e.date, e.ref) for e in trades if e.ref not in alloc}),
                 "note_trades_not_in_tradebook": sorted(set(alloc) - {e.ref for e in trades})}
