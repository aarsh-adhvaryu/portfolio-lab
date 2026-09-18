"""Extension points the later charters need, so the engine is written once.

Every hook is inert for E1: the defaults below are no-ops, and each is
reached only when its config flag is on. `HookSet.for_e1()` asserts that all
of them are off, and `tests/test_hooks.py` asserts the engine's behaviour is
byte-identical with hooks absent and with the E1 hook set attached.

  intra_month_exit   E2-A  a red flag sells a held name at the next open
                           rather than waiting for month-end (E2-A §3, the
                           only intra-month action in the stack)
  defer_exit         E1-P  a band exit waits when the lot is 9-12 months old
                           and the name has only slipped to rank <= 100
  tax_class          E3    gold ETF gains are slab, not equity; STT differs
                           by instrument, so both are per-security
  pre_buy_constraint E2-B  a buy that would breach a shock-beta cap is
                           skipped and the next candidate tried
  side_sleeve        E4    IPO capital that never mixes with E1's cash

None of these picks a parameter. Each is a place where a later charter's
one rule attaches.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional, Protocol

# Tax classes. E1 is equity-only; E3 introduces the rest.
EQUITY = "equity"
NON_EQUITY = "non_equity"     # gold/silver ETF: short-term at slab
DEBT = "debt"                 # liquid ETF: return arrives as dividend units


class IntraMonthExit(Protocol):
    """E2-A. Names to sell at the open of session `t`, decided from data
    dated strictly before `t` (dissemination timestamp, §4 point-in-time)."""

    def __call__(self, t: date, held: List[str], state: "EngineState") -> List[str]: ...


class DeferExit(Protocol):
    """E1-P. True keeps a band-exit name held for now. Called once per
    (month-end, name) with the lot ages the engine already has."""

    def __call__(self, m: date, isin: str, rank: Optional[float],
                 lot_ages_days: List[int], state: "EngineState") -> bool: ...


class PreBuyConstraint(Protocol):
    """E2-B. False rejects a planned buy; the engine tries the next candidate
    by rank rather than abandoning the buy slot."""

    def __call__(self, m: date, isin: str, qty: int, price: float,
                 state: "EngineState") -> bool: ...


class TaxClassFn(Protocol):
    """E3. Per-security tax and STT class. E1 answers `equity` for everything."""

    def __call__(self, isin: str) -> str: ...


@dataclass
class SideSleeve:
    """E4. Capital that never touches E1's cash.

    The engine only carries it and reports it; nothing in E1 reads or writes
    it. Keeping it here means E4 does not have to reopen the cash loop.
    """
    enabled: bool = False
    capital: float = 0.0
    cash: float = 0.0
    blocked: float = 0.0
    ledger: List[dict] = field(default_factory=list)

    def accrue(self, rate_annual: float, days: int) -> None:
        if self.enabled and self.cash > 0:
            self.cash *= (1.0 + rate_annual * days / 365.0)


def _no_intra_month_exit(t, held, state) -> List[str]:
    return []


def _never_defer(m, isin, rank, lot_ages_days, state) -> bool:
    return False


def _always_allow(m, isin, qty, price, state) -> bool:
    return True


def _all_equity(isin: str) -> str:
    return EQUITY


@dataclass
class HookSet:
    intra_month_exit: IntraMonthExit = _no_intra_month_exit
    defer_exit: DeferExit = _never_defer
    pre_buy_constraint: PreBuyConstraint = _always_allow
    tax_class: TaxClassFn = _all_equity
    side_sleeve: SideSleeve = field(default_factory=SideSleeve)

    @classmethod
    def for_e1(cls) -> "HookSet":
        """The E1 hook set: every extension point present and inert."""
        h = cls()
        assert h.is_inert(), "E1 must run with every hook off"
        return h

    def is_inert(self) -> bool:
        return (self.intra_month_exit is _no_intra_month_exit
                and self.defer_exit is _never_defer
                and self.pre_buy_constraint is _always_allow
                and self.tax_class is _all_equity
                and not self.side_sleeve.enabled)

    def active(self) -> Dict[str, bool]:
        """What the manifest records, so a run says which rules were live."""
        return {
            "intra_month_exit": self.intra_month_exit is not _no_intra_month_exit,
            "defer_exit": self.defer_exit is not _never_defer,
            "pre_buy_constraint": self.pre_buy_constraint is not _always_allow,
            "tax_class": self.tax_class is not _all_equity,
            "side_sleeve": bool(self.side_sleeve.enabled),
        }


def from_config(config: dict) -> HookSet:
    """Build the hook set from a config's [hooks] table. Absent means off."""
    h = config.get("hooks", {}) or {}
    hs = HookSet()
    if h.get("side_sleeve_capital"):
        hs.side_sleeve = SideSleeve(enabled=True,
                                    capital=float(h["side_sleeve_capital"]),
                                    cash=float(h["side_sleeve_capital"]))
    return hs


class EngineState(Protocol):
    """What a hook may read. Deliberately narrow: a hook sees the portfolio
    as of now, never the future."""
    date: date
    cash: float
    positions: Dict[str, int]
    holdings_value: Dict[str, float]
