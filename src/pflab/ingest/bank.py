"""Bank statement import (PLAN S6): parse an SBI export, classify every line by rule, build ledger events,
match dividend credits to the NSE dividend feed times the quantity held.

Parsing: a CSV, XLSX (SBI's is password-encrypted: decrypted in memory) or legacy XLS (HDFC) whose table has
date, description (Description/Narration/Details), debit (Debit/Withdrawal), credit (Credit/Deposit) and
balance columns. The running balance is checked line by
line: a statement that does not add up is refused, because every later number would carry the error.

Classification is by ordered regex rules (`configs/bank_rules.toml`); nothing that matches no rule is
guessed: it is `unclassified` and listed (`acceptance`). Events: the bank is a cash account; broker
transfers are `cash_transfer`s (internal); other credits and debits are `deposit`/`withdrawal`, income is
`interest` or `dividend`, bank fees are `charge`. After import the ledger's bank cash equals the
statement's closing balance (`check_closing_balance`).
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Union

import pandas as pd

from pflab import _toml
from pflab.ledger.events import Event

RULES_PATH = Path(__file__).resolve().parents[3] / "configs" / "bank_rules.toml"
TOL = 0.005


class StatementError(ValueError):
    pass


# --- parse -----------------------------------------------------------------------------------------------------

def _num(v) -> float:
    if v is None or (isinstance(v, float) and v != v):
        return 0.0
    s = str(v).replace(",", "").strip()
    if s in ("", "-", "--"):
        return 0.0
    s = re.sub(r"\s*(DR|CR)\.?$", "", s, flags=re.I)
    return float(s)


def _date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%d %b %Y", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %B %Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise StatementError(f"unparseable date {v!r}")


def _unwrap(v) -> str:
    """SBI wraps a narration at a fixed width, mid-word, and starts the continuation with one space
    ('INTERES\\n T CREDIT'); removing exactly that rebuilds the text."""
    return re.sub(r"\r?\n ?", "", str(v)).strip()


OLE_MAGIC =b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"      # legacy .xls, and the container of an encrypted .xlsx


def _sheet_rows(raw: bytes, password: Optional[str]) -> List[list]:
    """Workbook bytes -> rows of the first sheet. A password-protected file (SBI) is decrypted in memory
    (msoffcrypto); nothing decrypted is written to disk. Legacy .xls (HDFC) is read with xlrd."""
    if raw[:8] == OLE_MAGIC:
        import msoffcrypto
        office = msoffcrypto.OfficeFile(io.BytesIO(raw))
        if office.is_encrypted():
            if not password:
                raise StatementError("the statement is password-protected: pass its password")
            out = io.BytesIO()
            try:
                office.load_key(password=password)
                office.decrypt(out)
            except Exception as e:
                raise StatementError(f"could not decrypt the statement (wrong password?): {type(e).__name__}") from None
            raw = out.getvalue()
    if raw[:2] == b"PK":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
        return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    if raw[:8] == OLE_MAGIC:
        import xlrd
        sh = xlrd.open_workbook(file_contents=raw).sheet_by_index(0)
        return [sh.row_values(i) for i in range(sh.nrows)]
    raise StatementError("not an Excel workbook")


def _rows_from(source: Union[str, Path, bytes], password: Optional[str] = None) -> List[list]:
    import csv
    if isinstance(source, bytes):
        return _sheet_rows(source, password)
    s = str(source)
    if chr(10) not in s and Path(s).suffix.lower() in (".xlsx", ".xls", ".csv"):
        p = Path(s)
        if p.suffix.lower() in (".xlsx", ".xls"):
            return _sheet_rows(p.read_bytes(), password)
        s = p.read_text(encoding="utf-8-sig")
    return [r for r in csv.reader(io.StringIO(s))]


DESC_NAMES = ("description", "narration", "details", "particulars")
DEBIT_NAMES = ("debit", "withdrawal")                  # HDFC: Withdrawal Amt.
CREDIT_NAMES = ("credit", "deposit")                   # HDFC: Deposit Amt.


def parse(source: Union[str, Path, bytes], opening_balance: Optional[float] = None,
          password: Optional[str] = None) -> pd.DataFrame:
    """Statement -> date, value_date, description, ref, debit, credit, balance (chronological, balance-checked).
    `password`: for an encrypted export (SBI); it is used in memory only."""
    rows = _rows_from(source, password)
    hi = None
    for i, r in enumerate(rows[:80]):
        low = [str(c).strip().lower() for c in r if c is not None]
        if any("txn date" in c or c == "date" for c in low) and any(n in c for c in low for n in DESC_NAMES) \
                and any(n in c for c in low for n in CREDIT_NAMES) and any(n in c for c in low for n in DEBIT_NAMES):
            hi = i
            break
    if hi is None:
        raise StatementError("no header row with Txn Date, Description, Debit and Credit")
    head = [str(c).strip().lower() if c is not None else "" for c in rows[hi]]

    def col(*names):
        for n in names:
            for j, h in enumerate(head):
                if n in h:
                    return j
        return None

    c_date, c_val, c_desc = col("txn date", "date"), col("value date", "value dt"), col(*DESC_NAMES)
    c_ref, c_deb, c_cre, c_bal = col("ref", "cheque", "chq"), col(*DEBIT_NAMES), col(*CREDIT_NAMES), col("balance")
    if None in (c_date, c_desc, c_deb, c_cre, c_bal):
        raise StatementError(f"missing columns in header {head}")
    out = []
    for r in rows[hi + 1:]:
        if len(r) <= max(c_date, c_desc, c_deb, c_cre, c_bal) or not str(r[c_date]).strip():
            continue
        try:
            d = _date(r[c_date])
        except StatementError:
            continue                              # footer text such as "Statement Summary"
        out.append(dict(date=d, value_date=_date(r[c_val]) if c_val is not None and str(r[c_val]).strip() else d,
                        description=_unwrap(r[c_desc]), ref=str(r[c_ref]).strip() if c_ref is not None else "",
                        debit=_num(r[c_deb]), credit=_num(r[c_cre]), balance=_num(r[c_bal])))
    df = pd.DataFrame(out, columns=["date", "value_date", "description", "ref", "debit", "credit", "balance"])
    if df.empty:
        raise StatementError("no transaction rows")
    df = df.reset_index(drop=True)
    prev = opening_balance if opening_balance is not None else df["balance"].iloc[0] - df["credit"].iloc[0] + df["debit"].iloc[0]
    for i, r in df.iterrows():
        if abs(prev + r["credit"] - r["debit"] - r["balance"]) > TOL:
            raise StatementError(f"balance breaks at row {i + 1} ({r['date']} {r['description'][:40]!r}): "
                                 f"{prev:,.2f} + {r['credit']:,.2f} - {r['debit']:,.2f} != {r['balance']:,.2f}")
        prev = r["balance"]
    df.attrs["opening_balance"] = (opening_balance if opening_balance is not None
                                   else df["balance"].iloc[0] - df["credit"].iloc[0] + df["debit"].iloc[0])
    return df


# --- classify ---------------------------------------------------------------------------------------------------

LOCAL_RULES_NAME = "bank_rules.local.toml"     # under PFLAB_PM_DIR: rules naming people or own accounts


def load_rules(path: Path = RULES_PATH, local: Optional[Path] = None) -> List[dict]:
    """Repo rules, with `local` rules (same format, kept out of git: they name the investor, his accounts and
    counterparties) placed FIRST so they win. A missing local file is no rules, not an error."""
    rules = _toml.load(path).get("rule", [])
    if local is not None and Path(local).exists():
        rules = _toml.load(local).get("rule", []) + rules
    return [dict(r, _rx=[re.compile(p, re.I) for p in r["patterns"]]) for r in rules]


def classify(df: pd.DataFrame, rules: Optional[List[dict]] = None) -> pd.DataFrame:
    rules = rules if rules is not None else load_rules()
    cats, ids = [], []
    for r in df.itertuples():
        direction = "credit" if r.credit > 0 else "debit"
        hit = next((rl for rl in rules if rl["direction"] == direction and any(x.search(r.description) for x in rl["_rx"])), None)
        cats.append(hit["category"] if hit else "unclassified")
        ids.append(hit["id"] if hit else None)
    out = df.copy()
    out["direction"] = ["credit" if c > 0 else "debit" for c in df["credit"]]
    out["category"], out["rule_id"] = cats, ids
    out["ref_id"] = [hashlib.sha1(f"{d}|{t}|{c:.2f}|{db:.2f}|{b:.2f}|{n}".encode()).hexdigest()[:16]
                     for n, (d, t, c, db, b) in enumerate(zip(df["date"], df["description"], df["credit"], df["debit"], df["balance"]))]
    return out


def acceptance(df: pd.DataFrame, since: date) -> dict:
    """PLAN S6 acceptance: every credit since `since` is classified or listed. Returns the counts and the
    explicit list of unclassified credits (the 'listed' half)."""
    c = df[(df["credit"] > 0) & (df["date"] >= since)]
    un = c[c["category"] == "unclassified"]
    return {"credits": len(c), "classified": int((c["category"] != "unclassified").sum()), "unclassified": len(un),
            "unclassified_lines": un[["date", "description", "credit"]].to_dict("records"),
            "all_classified_or_listed": True}


# --- events -----------------------------------------------------------------------------------------------------------

_INCOME = {"interest", "sgb_interest", "bond_interest"}


def to_events(df: pd.DataFrame, bank_account: str, broker_account: Optional[str] = None,
              matches: Optional[Dict[str, dict]] = None, existing_refs: Optional[Set[str]] = None,
              source_doc_sha: str = "", with_opening: bool = True) -> Tuple[List[Event], dict]:
    """Ledger events for a classified statement. `matches`: ref_id -> {"isin","gross","tds"} from `match_dividends`;
    a dividend credit with no match is posted as `interest` (same slab tax) and listed in the report."""
    matches, existing = matches or {}, existing_refs or set()
    evs: List[Event] = []
    report = {"unmatched_dividends": [], "unclassified": [], "skipped_existing": 0}
    if with_opening and f"bank_open:{bank_account}:{df['date'].iloc[0]}" not in existing:
        ob = df.attrs.get("opening_balance", 0.0)
        if ob > 0:
            evs.append(Event("deposit", bank_account, df["date"].iloc[0], amount=float(ob),
                             ref=f"bank_open:{bank_account}:{df['date'].iloc[0]}", source_doc_sha=source_doc_sha))
    for r in df.itertuples():
        ref = f"bank:{bank_account}:{r.ref_id}"
        if ref in existing:
            report["skipped_existing"] += 1
            continue
        kw = dict(ref=ref, source_doc_sha=source_doc_sha)
        d, cat = r.date, r.category
        if cat == "broker_transfer":
            if not broker_account:
                raise StatementError("a broker transfer needs the broker account id")
            src, dst, amt = (bank_account, broker_account, r.debit) if r.debit > 0 else (broker_account, bank_account, r.credit)
            evs.append(Event("cash_transfer", src, d, amount=amt, counter_account=dst, **kw))
        elif cat == "dividend":
            m = matches.get(r.ref_id)
            if m:
                evs.append(Event("dividend", bank_account, d, isin=m["isin"], amount=float(m["gross"]),
                                 fees={"tds": float(m["tds"])} if m["tds"] > 0 else {}, **kw))
            else:
                evs.append(Event("interest", bank_account, d, amount=r.credit, **kw))
                report["unmatched_dividends"].append({"date": d, "description": r.description, "credit": r.credit})
        elif cat in _INCOME:
            evs.append(Event("interest", bank_account, d, amount=r.credit, **kw))
        elif cat == "bank_charges":
            evs.append(Event("charge", bank_account, d, amount=r.debit, **{**kw, "ref": ref}))
        elif r.credit > 0:
            evs.append(Event("deposit", bank_account, d, amount=r.credit, **kw))
            if cat == "unclassified":
                report["unclassified"].append({"date": d, "description": r.description, "credit": r.credit})
        else:
            evs.append(Event("withdrawal", bank_account, d, amount=r.debit, **kw))
            if cat == "unclassified":
                report["unclassified"].append({"date": d, "description": r.description, "debit": r.debit})
    return evs, report


def pair_own_transfers(statements: Dict[str, pd.DataFrame], days: int = 2,
                       category: str = "own_transfer") -> List[dict]:
    """Transfers between two of the investor's bank accounts appear on both statements. Pair a debit on one with a
    credit of the same amount on another within `days` (one-to-one, nearest date first) so the ledger posts one
    `cash_transfer` instead of a withdrawal plus a deposit. Unpaired lines stay deposits/withdrawals."""
    debits = [(acc, r) for acc, df in statements.items() for r in df[(df["category"] == category) & (df["debit"] > 0)].itertuples()]
    credits = [(acc, r) for acc, df in statements.items() for r in df[(df["category"] == category) & (df["credit"] > 0)].itertuples()]
    used, pairs = set(), []
    for acc_d, d in sorted(debits, key=lambda x: (x[1].date, x[1].ref_id)):
        cands = [(abs((c.date - d.date).days), acc_c, c) for acc_c, c in credits
                 if acc_c != acc_d and (acc_c, c.ref_id) not in used and abs(c.credit - d.debit) < TOL
                 and abs((c.date - d.date).days) <= days]
        if cands:
            _, acc_c, c = min(cands, key=lambda x: (x[0], x[2].ref_id))
            used.add((acc_c, c.ref_id))
            pairs.append({"date": d.date, "amount": float(d.debit), "from_account": acc_d,
                          "from_ref": f"bank:{acc_d}:{d.ref_id}", "to_account": acc_c, "to_ref": f"bank:{acc_c}:{c.ref_id}"})
    return pairs


def check_closing_balance(df: pd.DataFrame, ledger, bank_account: str, tol: float = 0.01) -> dict:
    """After the whole statement is in the ledger, the bank account's cash must equal its closing balance."""
    want = float(df["balance"].iloc[-1])
    have = ledger.cash_balance(bank_account, df["date"].iloc[-1])
    return {"statement_closing": want, "ledger_cash": have, "ok": abs(want - have) <= tol}


# --- dividends --------------------------------------------------------------------------------------------------------------

def match_dividends(df: pd.DataFrame, feed: pd.DataFrame, qty_on: Callable[[str, date], float],
                    symbols: Optional[Dict[str, str]] = None, window_days: int = 75,
                    tds_rate: float = 0.10, tol_abs: float = 1.0, tol_pct: float = 0.005) -> pd.DataFrame:
    """Match dividend credits to feed rows: a credit equals dividend_per_share x quantity held the day before
    the ex-date, gross or net of TDS, and arrives within `window_days` after the ex-date. `qty_on(isin, day)`
    is the quantity held at the end of `day` (ledger). `symbols` {isin: trading symbol} lets a name in the
    narration break a tie. Returns ref_id, isin, ex_date, qty, gross, tds, kind, ambiguous."""
    symbols = symbols or {}
    rows = []
    credits = df[df["category"] == "dividend"]
    f = feed.copy()
    f["ex_date"] = pd.to_datetime(f["ex_date"]).dt.date
    for r in credits.itertuples():
        lo, hi = r.date - timedelta(days=window_days), r.date
        cand = f[(f["ex_date"] >= lo) & (f["ex_date"] <= hi)]
        hits = []
        for c in cand.itertuples():
            qty = qty_on(c.isin, c.ex_date - timedelta(days=1))
            if qty <= 0:
                continue
            gross = c.dividend_per_share * qty
            for kind, expect in (("gross", gross), ("net_tds", gross * (1 - tds_rate))):
                diff = abs(r.credit - expect)
                if diff <= max(tol_abs, tol_pct * expect):
                    named = symbols.get(c.isin, "") and re.search(rf"\b{re.escape(symbols[c.isin])}\b", r.description, re.I) is not None
                    hits.append((0 if named else 1, diff, c.isin, c.ex_date, qty, gross, kind))
        if not hits:
            continue
        hits.sort()
        best = hits[0]
        amb = len(hits) > 1 and hits[1][:2] == best[:2] or (len({h[2] for h in hits}) > 1 and hits[0][0] == hits[1][0])
        _, _, isin, ex, qty, gross, kind = best
        rows.append(dict(ref_id=r.ref_id, isin=isin, ex_date=ex, qty=qty, gross=gross, tds=gross - r.credit if kind == "net_tds" else 0.0,
                         kind=kind, ambiguous=bool(amb)))
    return pd.DataFrame(rows, columns=["ref_id", "isin", "ex_date", "qty", "gross", "tds", "kind", "ambiguous"])
