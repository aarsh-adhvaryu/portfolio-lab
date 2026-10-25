"""Bank fixed deposits: value, maturity ladder, interest per FY and its TDS (PLAN S33, amendment A3).

Scope: cumulative deposits (interest paid at maturity), compounded quarterly. Deposits paying interest out
monthly or quarterly are not modelled and are refused.

Interest convention (SBI cumulative deposits, checked 2026-10-15 on 13 real deposits): quarter dates are
counted from the term start; each full quarter earns rate/4 on the balance; inside a running quarter
interest accrues pro rata (rate/4 x days elapsed / days in that quarter); a final stub shorter than a quarter,
ending at maturity, earns simple interest rate x days/365. On the real deposits this reproduces the bank's
maturity amounts to Rs 1 and, where no TDS had been taken yet, its current values to the paisa.

TDS: the bank takes TDS out of a cumulative deposit (at each FY end and at maturity), so the balance
compounds on less and the bank's own "maturity amount" (which ignores TDS) overstates the payout. Facts and
estimates are kept apart:
- facts: the bank's current value on the day it was read (`anchor`), its contract maturity amount, and each
  FY's interest and TDS from the bank's interest certificate (`fd_interest` rows);
- estimates (`Estimate`): any other date's value, the payout net of TDS, a FY's interest before its
  certificate exists. A projection starts from the anchor and withdraws TDS at TDS_RATE at each FY end,
  assuming total bank interest is above the TDS threshold and the PAN is on record.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from dateutil.relativedelta import relativedelta

from pflab import _toml
from pflab.pm import estimate as est

TDS_RATE = 0.10                 # resident, PAN furnished (Income-tax Act 2025; bank interest)
TOL_MATURITY = 2.0              # rupees: the model must reproduce the bank's maturity amount
RENEWING = ("auto renewal", "default")


class FDError(ValueError):
    pass


@dataclass(frozen=True)
class FD:
    fd_id: str                          # the bank's account number (last 4 digits are enough to tell them apart)
    principal: float                    # of the current term
    rate: float                         # annual, decimal
    term_start: date
    maturity: date
    maturity_amount: float              # the bank's contract figure, gross of TDS
    bank: str = "SBI"
    payout: str = "cumulative"
    instruction: str = ""               # the bank's maturity instruction, as shown
    status: str = "open"                # open | closed
    closed_on: Optional[date] = None
    closing_amount: Optional[float] = None
    prev_rate: Optional[float] = None   # previous term's rate, for interest earned before a renewal in the FY
    anchor_date: Optional[date] = None  # the day the bank's current value was read
    anchor_value: Optional[float] = None
    opened: Optional[date] = None       # first start of the deposit, before any renewal
    purpose: str = ""                   # e.g. "reserve:phd": held out of the allocation targets

    def __post_init__(self):
        if self.payout != "cumulative":
            raise FDError(f"FD {self.fd_id}: only cumulative deposits are modelled, not {self.payout!r}")
        if self.maturity <= self.term_start or self.principal <= 0 or not 0 < self.rate < 0.2:
            raise FDError(f"FD {self.fd_id}: impossible terms")
        if self.status not in ("open", "closed"):
            raise FDError(f"FD {self.fd_id}: status must be open or closed")
        if self.status == "closed" and (self.closed_on is None or self.closing_amount is None):
            raise FDError(f"FD {self.fd_id}: a closed deposit needs closed_on and closing_amount")
        if (self.anchor_date is None) != (self.anchor_value is None):
            raise FDError(f"FD {self.fd_id}: anchor_date and anchor_value go together")

    @property
    def renews(self) -> bool:
        return self.instruction.strip().lower() in RENEWING


# --- the bank's arithmetic -----------------------------------------------------------------------------------------

def _q(fd: FD, k: int) -> date:
    return fd.term_start + relativedelta(months=3 * k)


def contract_value(fd: FD, on: date) -> float:
    """Value on `on` with no TDS taken (the bank's own projection basis)."""
    if on < fd.term_start:
        raise FDError(f"FD {fd.fd_id}: {on} is before the term start {fd.term_start}")
    on = min(on, fd.maturity)
    bal, k = fd.principal, 0
    while _q(fd, k + 1) <= on:
        bal *= 1 + fd.rate / 4
        k += 1
    a, b = _q(fd, k), _q(fd, k + 1)
    if on == a:
        return bal
    if on == fd.maturity and b > fd.maturity:                       # final stub: simple, days/365
        return bal * (1 + fd.rate * (on - a).days / 365)
    return bal * (1 + fd.rate / 4 * (on - a).days / (b - a).days)


def check(fd: FD) -> float:
    """The model's maturity amount; refuses terms that do not reproduce the bank's figure."""
    m = contract_value(fd, fd.maturity)
    if abs(m - fd.maturity_amount) > TOL_MATURITY:
        raise FDError(f"FD {fd.fd_id}: terms give a maturity amount of {m:,.2f}, the bank shows "
                      f"{fd.maturity_amount:,.2f}: check principal, rate and dates")
    return m


def _fy_ends(a: date, b: date) -> List[date]:
    """31 March dates in (a, b)."""
    out, y = [], a.year
    while date(y, 3, 31) < b:
        if date(y, 3, 31) > a:
            out.append(date(y, 3, 31))
        y += 1
    return out


def _projection(fd: FD, upto: date) -> Tuple[float, List[Tuple[date, float, float]]]:
    """(factor on `upto`, [(fy_end, interest, tds)...]) from the anchor. The factor scales contract_value
    to what the deposit holds after the TDS taken so far."""
    if fd.anchor_date is None:
        raise FDError(f"FD {fd.fd_id}: no bank value read yet (anchor), nothing to project from")
    k = fd.anchor_value / contract_value(fd, fd.anchor_date)
    steps = []
    for t in _fy_ends(fd.anchor_date, min(upto, fd.maturity)):
        # TDS at the FY end is on the whole FY's interest; no TDS is taken inside a FY, so the factor holds
        interest = k * (contract_value(fd, t) - contract_value(fd, max(fd.term_start, date(t.year - 1, 4, 1))))
        tds = TDS_RATE * interest
        k -= tds / contract_value(fd, t)
        steps.append((t, interest, tds))
    return k, steps


def _inputs(fd: FD) -> dict:
    return {"fd": fd.fd_id, "p": fd.principal, "r": fd.rate, "start": fd.term_start, "mat": fd.maturity,
            "anchor": (fd.anchor_date, fd.anchor_value), "tds_rate": TDS_RATE}


def value(fd: FD, on: date) -> Union[float, est.Estimate]:
    """The deposit's value on `on`: the bank's figure on the anchor day (a fact), else an Estimate."""
    if fd.status == "closed" and on >= fd.closed_on:
        return 0.0
    if on < fd.term_start:
        raise FDError(f"FD {fd.fd_id}: {on} is before this term (from {fd.term_start})")
    if on == fd.anchor_date:
        return fd.anchor_value
    if fd.anchor_date and on < fd.anchor_date:
        raise FDError(f"FD {fd.fd_id}: values before the bank's reading ({fd.anchor_date}) are not modelled")
    k, _ = _projection(fd, on)
    return est.Estimate(k * contract_value(fd, on), "SBI quarterly compounding from the bank's value, TDS at "
                        f"{TDS_RATE:.0%} withdrawn each 31 Mar", est.inputs_hash(_inputs(fd)), fd.anchor_date)


def maturity_payout(fd: FD) -> est.Estimate:
    """What reaches the bank account at maturity: contract value less the TDS taken over the term."""
    k, _ = _projection(fd, fd.maturity)
    m = fd.maturity
    fy_start = date(m.year if m.month >= 4 else m.year - 1, 4, 1)
    gross = k * contract_value(fd, m)
    stub_interest = gross - k * contract_value(fd, max(fd.term_start, fy_start))
    return est.Estimate(gross - TDS_RATE * stub_interest, f"maturity amount net of TDS at {TDS_RATE:.0%}",
                        est.inputs_hash(_inputs(fd)), fd.anchor_date, horizon=str(fd.maturity))


# --- interest per FY -------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class FYInterest:
    fd_id: str
    fy: int
    interest: Union[float, est.Estimate]
    tds: Union[float, est.Estimate]
    source: str                         # "certificate" or "estimate"


def fy_interest(fd: FD, fy: int, facts: Dict[Tuple[str, int], dict]) -> Optional[FYInterest]:
    """Interest earned in FY `fy` (FY label = year it ends) and its TDS. A certificate row is a fact and
    wins; otherwise an estimate. None when the deposit earned nothing in that FY."""
    f = facts.get((fd.fd_id, fy))
    if f:
        return FYInterest(fd.fd_id, fy, f["paid"] + f["accrued"], f["tds"], "certificate")
    s, e = date(fy - 1, 4, 1), date(fy, 3, 31)
    end = min(e, fd.maturity, fd.closed_on or e)
    if end < s or (fd.opened or fd.term_start) > e:
        return None
    total = 0.0
    if fd.term_start > s and fd.opened and fd.opened < fd.term_start:   # previous term, up to the renewal
        r = fd.prev_rate or fd.rate
        g = (1 + r / 4) ** ((fd.term_start - s).days / (365 / 4))
        v0 = fd.principal / (g - TDS_RATE * (g - 1))         # renewal principal = value net of TDS taken at renewal
        total += v0 * (g - 1)
    if fd.status == "closed" and fd.closing_amount is not None:
        total += max(fd.closing_amount - fd.principal, 0.0)
    else:
        a = max(s, fd.term_start)
        if fd.anchor_date is None:
            raise FDError(f"FD {fd.fd_id}: no bank value read, FY{fy} interest cannot be estimated")
        if a < date(fd.anchor_date.year - (1 if fd.anchor_date.month < 4 else 0), 4, 1):
            raise FDError(f"FD {fd.fd_id}: FY{fy} is before the bank's reading and has no certificate row")
        k, _ = _projection(fd, a)                         # TDS is taken at FY ends only: one factor all FY
        total += k * (contract_value(fd, end) - contract_value(fd, a))
    method = "SBI convention from the bank's value; " + (
        "previous term at its own rate" if fd.prev_rate or fd.term_start <= s else "previous term at the current rate")
    h = est.inputs_hash({**_inputs(fd), "fy": fy})
    return FYInterest(fd.fd_id, fy, est.Estimate(total, method, h, fd.anchor_date or fd.closed_on, horizon=f"FY{fy}"),
                      est.Estimate(TDS_RATE * total, f"TDS at {TDS_RATE:.0%} of the estimate", h,
                                   fd.anchor_date or fd.closed_on, horizon=f"FY{fy}"), "estimate")


def year_totals(fds: Sequence[FD], fy: int, facts: Dict[Tuple[str, int], dict]) -> dict:
    """Interest and TDS for the FY across deposits, split into certificate facts and estimates."""
    rows = [r for fd in fds if (r := fy_interest(fd, fy, facts))]
    held = {fd.fd_id for fd in fds}
    rows += [FYInterest(i, f, v["paid"] + v["accrued"], v["tds"], "certificate")      # closed before the file
             for (i, f), v in sorted(facts.items()) if f == fy and i not in held]
    num = lambda x: x.value if isinstance(x, est.Estimate) else x
    out = {"fy": fy, "rows": rows,
           "certified_interest": sum(r.interest for r in rows if r.source == "certificate"),
           "certified_tds": sum(r.tds for r in rows if r.source == "certificate"),
           "estimated_interest": sum(num(r.interest) for r in rows if r.source == "estimate"),
           "estimated_tds": sum(num(r.tds) for r in rows if r.source == "estimate")}
    out["interest"] = out["certified_interest"] + out["estimated_interest"]
    out["tds"] = out["certified_tds"] + out["estimated_tds"]
    out["is_estimate"] = any(r.source == "estimate" for r in rows)
    return out


# --- ladder and warnings ---------------------------------------------------------------------------------------------

def ladder(fds: Sequence[FD], on: date) -> List[dict]:
    """Open deposits by maturity: contract amount (fact) and payout net of TDS (estimate)."""
    rows = [{"maturity": fd.maturity, "fd_id": fd.fd_id, "contract_amount": fd.maturity_amount,
             "payout": maturity_payout(fd), "instruction": fd.instruction, "renews": fd.renews, "bank": fd.bank,
             "principal": fd.principal}
            for fd in fds if fd.status == "open" and fd.maturity >= on]
    return sorted(rows, key=lambda r: (r["maturity"], r["fd_id"]))


def warnings(fds: Sequence[FD], on: date, within_days: int = 45) -> List[str]:
    """What needs the investor before a maturity: deposits maturing soon, and any set to renew."""
    out = []
    for r in ladder(fds, on):
        days = (r["maturity"] - on).days
        name = f"{r['bank']} FD of Rs {r['principal']:,.0f}"     # S62: never the deposit's number (these go to Telegram)
        if r["renews"]:
            out.append(f"{name} matures {r['maturity']} with instruction '{r['instruction']}': "
                       "it may renew; change it to credit the account if the money is to be redeployed")
        if days <= within_days:
            out.append(f"{name} matures in {days} days ({r['maturity']}): about "
                       f"Rs {r['payout'].value:,.0f} net of TDS reaches the account")
    return out


# --- input and storage ----------------------------------------------------------------------------------------------

def from_toml(path: Union[str, Path]) -> List[FD]:
    """The investor's deposit file (PFLAB_PM_DIR/fd_holdings.toml): one [[fd]] table per deposit, values as the bank
    shows them, read on `as_of` (the anchor)."""
    d = _toml.load(Path(path))
    as_of = d.get("as_of")
    fds = []
    for t in d.get("fd", []):
        closed = t.get("status", "open") == "closed"
        fd = FD(fd_id=str(t["id"]), principal=float(t["principal"]), rate=float(t["rate_pct"]) / 100,
                term_start=t.get("term_start", t["start"]), maturity=t["maturity"],
                maturity_amount=float(t["maturity_amount"]), bank=t.get("bank", "SBI"),
                instruction=t.get("maturity_instruction", ""), status=t.get("status", "open"),
                closed_on=t.get("closed_on"), closing_amount=t.get("closing_amount"),
                prev_rate=float(t["prev_rate_pct"]) / 100 if "prev_rate_pct" in t else None,
                anchor_date=None if closed or "current_value" not in t else as_of,
                anchor_value=None if closed or "current_value" not in t else float(t["current_value"]),
                opened=t.get("start"), purpose=t.get("purpose", ""))
        check(fd)
        fds.append(fd)
    ids = [f.fd_id for f in fds]
    if len(set(ids)) != len(ids):
        raise FDError("a deposit id appears twice in the file")
    return fds


_COLS = ("fd_id, bank, principal, rate, term_start, maturity, maturity_amount, payout, instruction, status, "
         "closed_on, closing_amount, prev_rate, anchor_date, anchor_value, opened, purpose")


def save(con, fds: Sequence[FD], source: str, now: Optional[datetime] = None) -> int:
    """Replace the deposit master with `fds` (the file is the whole truth about what is held), all or nothing."""
    from pflab.pm.store import transaction
    now = now or datetime.now()
    with transaction(con):
        con.execute("DELETE FROM fds")
        for f in fds:
            con.execute(f"INSERT INTO fds ({_COLS}, source, loaded_at) VALUES ({', '.join('?' * 19)})",
                        [f.fd_id, f.bank, f.principal, f.rate, f.term_start, f.maturity, f.maturity_amount, f.payout,
                         f.instruction, f.status, f.closed_on, f.closing_amount, f.prev_rate, f.anchor_date,
                         f.anchor_value, f.opened, f.purpose, source, now])
    return len(fds)


def load(con) -> List[FD]:
    rows = con.execute(f"SELECT {_COLS} FROM fds ORDER BY maturity, fd_id").fetchall()
    keys = [c.strip() for c in _COLS.split(",")]
    return [FD(**{**dict(zip(keys, r)), "purpose": r[-1] or ""}) for r in rows]


def save_interest(con, fy: int, rows: Sequence[dict], source: str, now: Optional[datetime] = None) -> int:
    """Certificate rows for one FY: {fd_id, paid, accrued, tds}. Re-loading a FY replaces it."""
    from pflab.pm.store import transaction
    now = now or datetime.now()
    with transaction(con):
        con.execute("DELETE FROM fd_interest WHERE fy = ?", [fy])
        for r in rows:
            con.execute("INSERT INTO fd_interest VALUES (?,?,?,?,?,?,?)",
                        [r["fd_id"], fy, r["paid"], r["accrued"], r["tds"], source, now])
    return len(rows)


def interest_facts(con) -> Dict[Tuple[str, int], dict]:
    return {(r[0], r[1]): {"paid": r[2], "accrued": r[3], "tds": r[4]}
            for r in con.execute("SELECT fd_id, fy, paid, accrued, tds FROM fd_interest").fetchall()}


def render(fds: Sequence[FD], on: date, fy: int, facts: Dict[Tuple[str, int], dict]) -> str:
    open_ = [f for f in fds if f.status == "open" and f.maturity >= on]
    vals = [value(f, on) for f in open_]
    num = lambda x: x.value if isinstance(x, est.Estimate) else x
    total = sum(num(v) for v in vals)
    est_any = any(isinstance(v, est.Estimate) for v in vals)
    lines = [f"Fixed deposits on {on}: {len(open_)} open, value {total:,.2f}"
             + (" (ESTIMATE: projected from the bank's values)" if est_any else " (as the bank showed them)")]
    for r in ladder(fds, on):
        lines.append(f"  {r['maturity']}  FD {r['fd_id']}  contract {r['contract_amount']:>13,.2f}  "
                     f"payout ~{r['payout'].value:>13,.2f} net of TDS  [{r['instruction'] or '?'}]")
    t = year_totals(fds, fy, facts)
    lines.append(f"FY{fy - 1}-{str(fy)[2:]} interest {t['interest']:,.2f}, TDS {t['tds']:,.2f}"
                 + (f" (ESTIMATE for {t['estimated_interest']:,.2f} of it)" if t["is_estimate"] else " (certified)"))
    lines += [f"  ! {w}" for w in warnings(fds, on)]
    return "\n".join(lines)
