"""Bank labels by the system (S65, S64 Phase 7 item 4): the hand-made `bank_rules.local.toml` becomes questions.

After the rules of `ingest/bank.py` have run, every line still `unclassified` is looked at here:

    1. a debit in one of his accounts and a credit of the same amount in another within 2 days is his own money moving
       (`own_transfer`); a line equal to a Console pay-in or payout within 2 days is a `broker_transfer`: both by code
    2. what is left is grouped by counterparty and asked about, biggest first, at most MAX_OPEN open at once and only where it
       matters (a group worth Rs 5,000 or more, or three lines or more): salary, own account, family, spend, refund, other
    3. his answer becomes a rule in `PFLAB_PM_DIR/bank_rules.local.toml` (tried before the repo's rules); the next ledger
       dry run uses it

Nothing is guessed: a line with no rule and no pair stays `unclassified` and listed, as before.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from pflab.agents import questions

AGENT = "banklabels"
TOL = 0.005
MIN_TOTAL, MIN_LINES, MAX_OPEN = 20_000.0, 3, 5         # (2026-10-30) only what moves his money matters; at most 5 open
KEY = "banklabel"
CHOICES = {"salary": "salary", "own": "own_transfer", "family": "family_transfer", "spend": "spend", "refund": "refund",
           "other": "other"}
_NOISE = {"UPI", "DR", "CR", "TO", "BY", "TRANSFER", "NEFT", "IMPS", "RTGS", "NA", "PAYMENT", "PAID", "FROM", "REF", "TXN", "INB",
          "MOB", "ATM", "POS", "ACH", "ECS", "CHQ", "CHEQUE", "CLG", "BANK", "LTD", "LIMITED", "PVT", "THE", "AND", "FOR", "OF",
          "DEBIT", "CREDIT", "WDL", "DEP", "TFR", "CASH", "MR", "MRS", "MS", "SHRI", "SMT",
          # the four-letter start of an IFSC code, which SBI narrations print on its own
          "SBIN", "HDFC", "ICIC", "UTIB", "KKBK", "YESB", "PUNB", "BARB", "CNRB", "IDFB", "INDB", "FDRL", "PYTM", "AIRP", "IBKL",
          "UBIN", "BKID", "CBIN", "MAHB", "IOBA", "RATN", "SCBL", "CITI", "HSBC", "DBSS", "KVBL", "SIBL", "TMBL", "USFB", "ESFB"}


def counterparty(description: str) -> str:
    """The name part of a narration ('UPI-JOHN DOE-john@ybl-YESB0000001-1234-NA' -> 'JOHN DOE'): words without digits, '@' or a
    bank-code shape, minus the payment-channel words, first three; 'OTHER' when nothing is left."""
    toks = [t for t in re.split(r"[/\-*\s,;:|]+", str(description).upper()) if t]
    keep = [t for t in toks if t.isalpha() and t not in _NOISE and len(t) > 1]
    return " ".join(keep[:3]) or "OTHER"


# --- 1. by code -------------------------------------------------------------------------------------------------------

def auto_label(statements: Dict[str, pd.DataFrame], broker_flows: Optional[pd.DataFrame] = None, days: int = 2) -> tuple:
    """Relabel unclassified lines that pair up as his own transfers or match a Console flow. Returns (statements, report).
    `broker_flows`: date, amount (pay-in +, payout -) as `zerodha_ledger.bank_flows` gives."""
    out = {a: df.copy() for a, df in statements.items()}
    rep = {"own_pairs": 0, "broker": 0}
    un = lambda df, side: df[(df["category"] == "unclassified") & (df[side] > 0)]            # noqa: E731
    used = set()
    debits = sorted(((a, r) for a, df in out.items() for r in un(df, "debit").itertuples()), key=lambda x: (x[1].date, x[1].ref_id))
    for acc_d, d in debits:
        cands = [(abs((c.date - d.date).days), acc_c, c) for acc_c, df in out.items() if acc_c != acc_d
                 for c in un(df, "credit").itertuples()
                 if (acc_c, c.ref_id) not in used and abs(c.credit - d.debit) < TOL and abs((c.date - d.date).days) <= days]
        if cands:
            _, acc_c, c = min(cands, key=lambda x: (x[0], x[2].ref_id))
            used.add((acc_c, c.ref_id))
            used.add((acc_d, d.ref_id))
            for acc, rid in ((acc_d, d.ref_id), (acc_c, c.ref_id)):
                m = out[acc]["ref_id"] == rid
                out[acc].loc[m, "category"], out[acc].loc[m, "rule_id"] = "own_transfer", "auto_own"
            rep["own_pairs"] += 1
    if broker_flows is not None and len(broker_flows):
        flows = [(f.date, float(f.amount)) for f in broker_flows.itertuples()]
        taken = set()
        for acc, df in out.items():
            # (2026-10-31) a line he labelled 'my own transfer' that is a Console pay-in or payout is one: Zerodha is his own account too
            open_ = (df["category"] == "unclassified") | ((df["category"] == "own_transfer") & (df["rule_id"] != "auto_own"))
            for r in df[open_].itertuples():
                side, amt = ("debit", r.debit) if r.debit > 0 else ("credit", r.credit)
                for i, (fd, fa) in enumerate(flows):
                    if i in taken or abs(abs(fa) - amt) >= TOL or abs((fd - r.date).days) > days or (fa > 0) != (side == "debit"):
                        continue
                    taken.add(i)
                    m = out[acc]["ref_id"] == r.ref_id
                    out[acc].loc[m, "category"], out[acc].loc[m, "rule_id"] = "broker_transfer", "auto_broker"
                    rep["broker"] += 1
                    break
    # (2026-10-30) a card purchase is spending; nobody needs to be asked about Amazon or a shop. Transfers to people stay questions.
    card = r"\b(?:POS|PURCH|ECOM|E-COM|CARD)\b"
    rep["card_spend"] = 0
    for acc, df in out.items():
        m = (df["category"] == "unclassified") & (df["debit"] > 0) & df["description"].astype(str).str.upper().str.contains(card, regex=True)
        out[acc].loc[m, "category"], out[acc].loc[m, "rule_id"] = "spend", "auto_card"
        rep["card_spend"] += int(m.sum())
    return out, rep


# --- 2. what is left: groups and questions -----------------------------------------------------------------------------

def groups(statements: Dict[str, pd.DataFrame]) -> List[dict]:
    """Unclassified lines grouped by (account, direction, counterparty), biggest total first."""
    rows: Dict[tuple, dict] = {}
    for acc, df in statements.items():
        for r in df[df["category"] == "unclassified"].itertuples():
            direction = "credit" if r.credit > 0 else "debit"
            amt = r.credit if r.credit > 0 else r.debit
            g = rows.setdefault((acc, direction, counterparty(r.description)),
                                {"account": acc, "direction": direction, "counterparty": counterparty(r.description), "n": 0, "total": 0.0,
                                 "first": r.date, "last": r.date, "examples": []})
            g["n"] += 1
            g["total"] += float(amt)
            g["first"], g["last"] = min(g["first"], r.date), max(g["last"], r.date)
            if len(g["examples"]) < 3:
                g["examples"].append(str(r.description)[:70])
    return sorted(rows.values(), key=lambda g: -g["total"])


def subject_key(g: dict) -> str:
    return f"{KEY}:{g['account']}:{g['direction']}:{g['counterparty']}"


def ask(con, grps: List[dict], now: Optional[datetime] = None) -> List[int]:
    """One question per group that matters; at most MAX_OPEN of this agent's questions open at once. Returns the new ids."""
    now = now or datetime.now()
    open_now = con.execute("SELECT count(*) FROM questions WHERE agent=? AND status='open'", [AGENT]).fetchone()[0]
    made = []
    for g in grps:
        if open_now + len(made) >= MAX_OPEN:
            break
        if g["total"] < MIN_TOTAL and g["n"] < MIN_LINES:
            continue
        verb = "received from" if g["direction"] == "credit" else "paid to"
        text = (f"In {g['account']}: {g['n']} line(s), Rs {g['total']:,.0f} in all, {g['first']} to {g['last']}, {verb} "
                f"'{g['counterparty']}' (for example: {'; '.join(g['examples'])}). What are these? Reply with one word: "
                + ", ".join(CHOICES) + ". 'own' means your own other account.")
        qid = questions.ask(con, AGENT, subject_key(g), text, now)
        if qid:
            made.append(qid)
    return made


# --- 3. his answer becomes a rule -------------------------------------------------------------------------------------------

def _pattern(counterparty_: str) -> str:
    return r"[\s\-/*]+".join(re.escape(t) for t in counterparty_.split())


def apply_answers(con, local_rules: Path) -> int:
    """Write a rule into `bank_rules.local.toml` for each answered label question not yet written. Returns how many were added."""
    existing = local_rules.read_text(encoding="utf-8") if local_rules.exists() else ""
    added = []
    for subject, answer in con.execute("SELECT subject_key, answer FROM questions WHERE agent=? AND status='answered' ORDER BY q_id",
                                       [AGENT]).fetchall():
        try:
            _, account, direction, who = subject.split(":", 3)
        except ValueError:
            continue
        word = re.split(r"[^a-z]+", (answer or "").strip().lower())[0]
        cat = CHOICES.get(word)
        if cat is None or who == "OTHER":
            continue
        if (cat == "salary" and direction != "credit") or (cat == "spend" and direction != "debit"):
            cat = "other"
        rid = "label_" + hashlib.sha1(f"{direction}|{who}".encode()).hexdigest()[:8]
        if f'id = "{rid}"' in existing or any(f'id = "{rid}"' in a for a in added):
            continue
        added.append(f'\n[[rule]]\nid = "{rid}"\ncategory = "{cat}"\ndirection = "{direction}"\n'
                     f"patterns = ['{_pattern(who)}']\n# his answer '{word}' for {who} ({account})\n")
    if added:
        header = "" if existing else "# Written by the system from his answers (ingest/bank_labels.py); tried before configs/bank_rules.toml.\n"
        local_rules.parent.mkdir(parents=True, exist_ok=True)
        local_rules.write_text(existing + header + "".join(added), encoding="utf-8")
    return len(added)
