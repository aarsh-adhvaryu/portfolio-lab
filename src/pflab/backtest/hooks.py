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


# -- E1-P §3: tax-aware patience ---------------------------------------
def patience_defer(min_months: int = 9, max_months: int = 12,
                   rank_ceiling: float = 100.0, require_gain: bool = False,
                   min_hold_months: Optional[int] = None) -> DeferExit:
    """Charter E1-P §3. A band exit waits when waiting is cheap and the tax
    saving is large.

    Three conditions in §3; the engine gives two of them for free. It calls
    `defer_exit` ONLY where the exit reason is "band", and a name that failed
    §2 exits with reason "ineligible" instead, so "still eligible" holds by
    construction. Delisting and suspension never enter that loop at all, so
    §3's "never deferred" holds the same way -- by construction, not by care.

    THE AGE WINDOW IS INCLUSIVE AT BOTH ENDS. `is_long_term` is
    `sell > buy + 12 months`, so a lot exactly 12 months old is still
    SHORT-term and one more month of patience is precisely what turns it
    long. Excluding the endpoint would drop the lots the rule exists for.

    WHICH LOT: settled by §3's per-lot resolution, appended at the
    2026-09-19 LOCK. §3 is written per-lot while E1 §4 sells a held name IN
    FULL, and this hook returns one decision per position, so the charter now
    says which lot each test uses:

      * the base rule and S4 use the OLDEST lot, because FIFO makes it the
        lot a sale would realise;
      * S5's minimum hold uses the YOUNGEST lot, because "every lot held at
        least N months" is exactly that condition;
      * partial-position exits are out of scope.

    This is charter text now, not an implementer's reading.

    Month arithmetic uses `relativedelta`, the same calendar as
    `tax.india_lots.is_long_term`, so "9-12 months" and "long-term" cannot
    disagree about what a month is.
    """
    from datetime import timedelta
    from dateutil.relativedelta import relativedelta

    def _defer(m, isin, rank, lot_ages_days, state) -> bool:
        if not lot_ages_days:
            return False

        # §6 S5: "a minimum hold of 6 months on EVERY lot regardless of rank
        # (pure patience, tax-blind)". Because §4 sells a held name IN FULL,
        # the only way no lot is sold before the floor is to wait until the
        # YOUNGEST lot reaches it -- the opposite end of the book from the
        # base rule below, and for the same reason: whole-position sales.
        # Tested here rather than folded into the window, because a window
        # over the oldest lot would sell a one-month-old lot as soon as the
        # oldest passed six months, which is what S5 forbids.
        if min_hold_months is not None:
            youngest = m - timedelta(days=int(min(lot_ages_days)))
            return youngest > (m - relativedelta(months=min_hold_months))

        buy = m - timedelta(days=int(max(lot_ages_days)))   # the oldest lot
        if not ((m - relativedelta(months=max_months)) <= buy
                <= (m - relativedelta(months=min_months))):
            return False
        if rank is None:
            return False                          # off the ranked list entirely
        try:
            if float(rank) > float(rank_ceiling):
                return False
        except (TypeError, ValueError):
            return False
        if require_gain:
            # §6 S4: a loss is sold, because the STCL is worth harvesting.
            # §3 as resolved at the lock: "S4 tests the OLDEST lot's own
            # unrealised gain, not the position average." The oldest lot is
            # the one FIFO realises, so its gain is the gain the sale would
            # actually book; a position average can show a gain while the lot
            # being sold is at a loss, and then S4 would defer exactly the
            # harvest it exists to take.
            lots = (getattr(state, "lots", None) or {}).get(isin) or []
            qty = (getattr(state, "positions", None) or {}).get(isin)
            value = (getattr(state, "holdings_value", None) or {}).get(isin)
            if not lots or not qty or value is None:
                return False
            oldest = min(lots, key=lambda l: l.buy_date)
            if (value / qty) <= oldest.cost_per_share:
                return False
        return True

    return _defer


# -- E1-P §4: negative controls, run alongside, never adoptable --------
def _threshold_exit(direction: int, pct: float) -> IntraMonthExit:
    """Shared body for N1/N2. direction -1 = stop-loss, +1 = profit-taking.

    Reads only `state`, which the engine leaves at the PREVIOUS session's
    marks when the intra-month hook runs, so the decision is made from data
    dated strictly before the fill -- the hook's contract, and §4 of E1.
    """
    def _exit(t, held, state) -> List[str]:
        basis = getattr(state, "cost_basis", None) or {}
        value = getattr(state, "holdings_value", None) or {}
        pos = getattr(state, "positions", None) or {}
        out = []
        for isin in held:
            b, q = basis.get(isin), pos.get(isin)
            if not b or not q or isin not in value:
                continue          # bought today: no prior mark, nothing to test
            move = (value[isin] / q) / b - 1.0
            if (direction < 0 and move <= -pct) or (direction > 0 and move >= pct):
                out.append(isin)
        return out
    return _exit


def stop_loss(pct: float = 0.20) -> IntraMonthExit:
    """E1-P §4 N1. Sell at the next open when down `pct` from cost basis."""
    return _threshold_exit(-1, pct)


def profit_take(pct: float = 0.50) -> IntraMonthExit:
    """E1-P §4 N2. Sell at the next open when up `pct` from cost basis."""
    return _threshold_exit(+1, pct)


def from_config(config: dict) -> HookSet:
    """Build the hook set from a config's [hooks] table. Absent means off."""
    h = config.get("hooks", {}) or {}
    hs = HookSet()
    if h.get("side_sleeve_capital"):
        hs.side_sleeve = SideSleeve(enabled=True,
                                    capital=float(h["side_sleeve_capital"]),
                                    cash=float(h["side_sleeve_capital"]))
    # E1-P §3. Absent, or explicitly disabled, leaves `_never_defer` in place,
    # which is what keeps E1 byte-identical.
    p = h.get("patience") or {}
    if p.get("enabled"):
        hs.defer_exit = patience_defer(
            min_months=int(p.get("min_months", 9)),
            max_months=int(p.get("max_months", 12)),
            rank_ceiling=float(p.get("rank_ceiling", 100.0)),
            require_gain=bool(p.get("require_gain", False)),
            min_hold_months=(int(p["min_hold_months"])
                             if p.get("min_hold_months") is not None else None))
    # E1-P §4 controls. Named, never inferred: an unknown name is an error
    # rather than a silently inert run.
    name = h.get("intra_month_exit")
    if name:
        if name == "stop_loss":
            hs.intra_month_exit = stop_loss(float(h.get("stop_loss_pct", 0.20)))
        elif name == "profit_take":
            hs.intra_month_exit = profit_take(float(h.get("profit_take_pct", 0.50)))
        else:
            raise ValueError(f"unknown hooks.intra_month_exit={name!r}")
    return hs


class EngineState(Protocol):
    """What a hook may read. Deliberately narrow: a hook sees the portfolio
    as of now, never the future."""
    date: date
    cash: float
    positions: Dict[str, int]
    holdings_value: Dict[str, float]
    # E1-P §4: N1/N2 trigger on a move from the position's own cost basis.
    # Per share, quantity-weighted across the position's lots.
    cost_basis: Dict[str, float]
    # E1-P §3 (locked 2026-09-19): S4 tests the OLDEST lot's own gain, which
    # the aggregate above cannot answer. Read-only.
    lots: Dict[str, list]
