"""Dated tax rule tables and lookup (PLAN §1, S2).

Rows live in `configs/tax/*.toml`, each with a source and `verified_on`. A
lookup that no row covers raises `RuleGap`; it never falls back to a default
rate. Rates are applied by TRANSFER date; the acquisition date only picks a row
where the law does (specified MFs from 2023-04-01) and sets the holding period.

Coverage: capital-gains rows from `COVERAGE_START` (2024-07-23). Surcharge cap,
cess and basic exemption from 2025-04-01. Earlier dates raise (PLAN §10 A1).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Optional, Union

from pflab.tax.india_lots import fy_of, is_long_term

COVERAGE_START = date(2024, 7, 23)
GENERAL_START = date(2025, 4, 1)
SLAB = "slab"
VERIFICATIONS = ("primary", "secondary", "unverified")
REQUIRED = ("source_url", "source_title", "verification", "verified_on")


class RuleGap(LookupError):
    """No rule row covers the request."""


class AmbiguousRule(RuntimeError):
    """More than one row covers the request: the tables overlap."""


def config_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "configs" / "tax"


@dataclass(frozen=True)
class Rule:
    id: str
    tax_class: str
    effective_from: date
    source_url: str
    source_title: str
    verification: str
    verified_on: date
    stcg_rate: Union[float, str]
    effective_to: Optional[date] = None
    stt_paid: Optional[bool] = None
    listed: Optional[bool] = None
    acquired_from: Optional[date] = None
    acquired_to: Optional[date] = None
    lt_months: Optional[int] = None
    ltcg_rate: Optional[Union[float, str]] = None
    section_old: str = ""
    section_new: str = ""
    note: str = ""

    def covers(self, tax_class: str, transfer: date, acquired: date,
               stt_paid: bool, listed: bool) -> bool:
        return (self.tax_class == tax_class
                and self.effective_from <= transfer
                and (self.effective_to is None or transfer <= self.effective_to)
                and (self.stt_paid is None or self.stt_paid == stt_paid)
                and (self.listed is None or self.listed == listed)
                and (self.acquired_from is None or acquired >= self.acquired_from)
                and (self.acquired_to is None or acquired <= self.acquired_to))

    def holding(self, acquired: date, transfer: date) -> str:
        """'LT' if held MORE than lt_months, else 'ST'. No lt_months: always ST."""
        if self.lt_months is None:
            return "ST"
        return "LT" if is_long_term(acquired, transfer, self.lt_months) else "ST"

    def rate(self, acquired: date, transfer: date) -> Union[float, str, None]:
        """STCG or LTCG rate for this holding: a decimal, 'slab', or None."""
        return self.ltcg_rate if self.holding(acquired, transfer) == "LT" else self.stcg_rate


_RULE_FIELDS = {f.name for f in fields(Rule)}


class RuleBook:
    def __init__(self, tables: dict):
        self.t = tables
        self.rules = [Rule(**{k: v for k, v in r.items() if k in _RULE_FIELDS})
                      for r in tables.get("rule", [])]

    def rows(self):
        """Every row in every table, as dicts (for source/verified_on checks)."""
        for name, lst in self.t.items():
            for r in lst:
                yield name, r


@lru_cache(maxsize=4)
def _load(path: str) -> RuleBook:
    tables: dict = {}
    for p in sorted(Path(path).glob("*.toml")):
        with open(p, "rb") as f:
            for name, rows in tomllib.load(f).items():
                tables.setdefault(name, []).extend(rows)
    return RuleBook(tables)


def load(directory: Optional[Path] = None) -> RuleBook:
    return _load(str(directory or config_dir()))


def lookup(tax_class: str, transfer_date: date, acquired_on: date, *, stt_paid: bool = True,
           listed: bool = True, book: Optional[RuleBook] = None) -> Rule:
    """The one capital-gains rule for this sale, or `RuleGap`."""
    book = book or load()
    if tax_class == "REVIEW":
        raise RuleGap("tax_class REVIEW: the instrument needs a human decision (see "
                      "instruments.tax_class_reason)")
    if transfer_date < COVERAGE_START:
        raise RuleGap(f"transfer on {transfer_date} is before rule coverage starts "
                      f"({COVERAGE_START}); PLAN §10 A1")
    hits = [r for r in book.rules
            if r.covers(tax_class, transfer_date, acquired_on, stt_paid, listed)]
    if not hits:
        raise RuleGap(f"no rule for {tax_class} transfer {transfer_date}, acquired "
                      f"{acquired_on}, stt_paid={stt_paid}, listed={listed}")
    if len(hits) > 1:
        raise AmbiguousRule(f"rules overlap: {[h.id for h in hits]}")
    return hits[0]


def _dated(book: RuleBook, table: str, on: date, **match) -> dict:
    if on < GENERAL_START:
        raise RuleGap(f"{table}: {on} is before coverage starts ({GENERAL_START}); PLAN §10 A1")
    hits = [r for r in book.t.get(table, [])
            if r["effective_from"] <= on and (r.get("effective_to") is None or on <= r["effective_to"])
            and all(r.get(k) == v for k, v in match.items())]
    if not hits:
        raise RuleGap(f"no {table} row for {on} {match}")
    if len(hits) > 1:
        raise AmbiguousRule(f"{table} rows overlap: {[h['id'] for h in hits]}")
    return hits[0]


def exemption(fy: int, rule_id: str = "equity_stt_paid", book: Optional[RuleBook] = None) -> float:
    """Annual exemption for `rule_id`'s gains in FY label `fy` (year the FY ends)."""
    book = book or load()
    rows = [r for r in book.t.get("exemption", []) if r["applies_to"] == rule_id and fy >= r["fy_from"]]
    if not rows:
        raise RuleGap(f"no exemption for {rule_id} in FY{fy}")
    return float(max(rows, key=lambda r: r["fy_from"])["amount"])


def surcharge_cap(on: date, book: Optional[RuleBook] = None) -> float:
    return float(_dated(book or load(), "surcharge_cap", on)["cap"])


def cess_rate(on: date, book: Optional[RuleBook] = None) -> float:
    return float(_dated(book or load(), "cess", on)["rate"])


def basic_exemption(regime: str, on: date, book: Optional[RuleBook] = None) -> float:
    return float(_dated(book or load(), "basic_exemption", on, regime=regime)["amount"])


def sgb_redemption_exempt(redemption_date: date, original_subscriber_held_to_maturity: bool,
                          *, premature: bool = False, book: Optional[RuleBook] = None) -> bool:
    """Is a redemption of an SGB capital-gains exempt?

    Before 2026-04-01: any holder. From 2026-04-01 (Finance Act 2026 s.43,
    Income-tax Act 2025 s.70(1)(x)): only an individual who held from original
    issue till maturity. A premature redemption is not 'till maturity' on the
    text, so it is NOT exempt from that date (open question, PLAN §6).
    """
    book = book or load()
    rows = [r for r in book.t.get("sgb_redemption", [])
            if (r.get("effective_from") is None or r["effective_from"] <= redemption_date)
            and (r.get("effective_to") is None or redemption_date <= r["effective_to"])]
    if len(rows) != 1:
        raise RuleGap(f"sgb_redemption rows for {redemption_date}: {len(rows)}")
    r = rows[0]
    if not r["exempt"]:
        return False
    if r["requires_original_subscriber"]:
        return bool(original_subscriber_held_to_maturity) and not premature
    return True


# --- income-tax tables (S13) --------------------------------------------------------------------------

def slab_rates(regime: str, on: date, age: str = "under60", book: Optional[RuleBook] = None) -> List[tuple]:
    """[(upper_bound or None, rate), ...] for a resident individual. The new regime has one
    table (`age` ignored); the old regime has under60, 60-79 and 80+."""
    book = book or load()
    age = "all" if regime == "new" else age
    row = _dated(book, "slab_table", on, regime=regime, age=age)
    return [(r.get("upto"), float(r["rate"])) for r in row["rates"]]


def tax_on_slabs(income: float, rates: List[tuple]) -> float:
    """Slab tax on `income` (a plain function of the table; no rebate, surcharge or cess)."""
    tax, lower = 0.0, 0.0
    for upto, rate in rates:
        top = income if upto is None else min(income, upto)
        if top > lower:
            tax += (top - lower) * rate
        if upto is None or income <= upto:
            break
        lower = upto
    return tax


def rebate_rule(regime: str, on: date, book: Optional[RuleBook] = None) -> dict:
    return dict(_dated(book or load(), "rebate", on, regime=regime))


def surcharge_tiers(regime: str, on: date, book: Optional[RuleBook] = None) -> dict:
    return dict(_dated(book or load(), "surcharge_tier", on, regime=regime))


def advance_tax_rule(on: date, book: Optional[RuleBook] = None) -> dict:
    return dict(_dated(book or load(), "advance_tax", on))


def dividend_tds_rule(on: date, book: Optional[RuleBook] = None) -> dict:
    return dict(_dated(book or load(), "dividend_tds", on))
