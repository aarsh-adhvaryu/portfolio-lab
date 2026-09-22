"""Buy-list construction (charter E1 §5): shortfall vs equal-weight target,
at most `max_names` names, integer shares, no selling."""
from __future__ import annotations

import math
from typing import Dict, List, Tuple


def buy_list(target_names: List[str], holdings_value: Dict[str, float], cash: float,
             open_price: Dict[str, float], n_hold: int = 25, max_names: int = 6) -> List[Tuple[str, int]]:
    """target_names: names allowed to receive money on this session (held
    names plus entry candidates in rank order). holdings_value: current
    market value per held name. cash: investable cash. open_price: fill
    price per name. Returns [(isin, qty)] in execution order."""
    if cash <= 0 or not target_names:
        return []
    equity = sum(holdings_value.get(n, 0.0) for n in target_names)
    target_value = (equity + cash) / n_hold
    shortfalls = []
    for i, name in enumerate(target_names):
        sf = target_value - holdings_value.get(name, 0.0)
        if sf > 0 and name in open_price and open_price[name] > 0:
            shortfalls.append((sf, i, name))  # i keeps rank order on ties
    shortfalls.sort(key=lambda t: (-t[0], t[1]))
    out: List[Tuple[str, int]] = []
    remaining = cash
    for sf, _, name in shortfalls[:max_names]:
        px = open_price[name]
        qty = math.floor(min(sf, remaining) / px)
        if qty >= 1:
            out.append((name, qty))
            remaining -= qty * px
        if remaining < min(open_price.values()):
            break
    return out


# -- E1c §3: score-tilted weights ---------------------------------------
class UndefinedWeight(ValueError):
    """No selected score is positive, so §3 has nothing to be proportional to.

    E1c §3 as amended after lock on 2026-09-21 weights names in proportion to
    max(score, 0): a non-positive score simply gets no weight. That leaves one
    case the charter still does not cover -- a selection in which NO score is
    positive -- and there the code halts rather than invent a rule
    (CLAUDE.md 3). Under §3's standardisation within the universe the top
    name's z-score is positive by construction, so this should never fire on
    the chartered rows; if it does, the sweep stops and it is reported.
    """


def score_tilted_weights(scores, cap: float = 0.05,
                         on_negative: str = "zero") -> dict:
    """E1c §3: weights proportional to max(score, 0), capped at `cap`.

    Amended after lock, blind, 2026-09-21: "weights are proportional to
    max(score, 0), capped at 5%. A held name whose score is not positive keeps
    its shares, receives no new money, and leaves only by its row's exit
    rule." Here that means a zero weight: a zero target is never short, so the
    buy list never sends it money, and nothing in E1c sells to rebalance.

    The cap is water-filled: names that would exceed it are fixed at the cap
    and the remainder is shared among the uncapped positive names in
    proportion to their scores, until nothing exceeds it. If there are too few
    positive names for the cap to reach 100% (fewer than 1/cap), every one of
    them sits at the cap and the rest of the book stays in cash -- that is
    what "capped at 5%" means with nothing left to give it to, and a
    read-only check before the run found it on no chartered row-date.

    `on_negative`:
      "zero"            the charter (default)
      "nse_normalised"  NSE's (1+z) / 1/(1-z) mapping -- unadopted; present,
                        and unreachable until a charter line selects it
    """
    import numpy as np

    names = list(scores)
    if not names:
        return {}
    s = np.array([float(scores[n]) for n in names], dtype=float)
    if not (cap > 0):
        raise ValueError(f"weight cap must be positive, got {cap}")
    if on_negative == "zero":
        if not (s > 0).any():
            raise UndefinedWeight(
                f"none of {len(s)} selected names has a positive score "
                f"(best {s.max():.4f}); E1c §3 does not define weights for a "
                f"selection with nothing positive in it")
        s = np.where(s > 0, s, 0.0)
    elif on_negative == "nse_normalised":
        # np.where evaluates both branches and 1/(1-s) divides by zero at
        # s == 1, so the negative branch is computed only where it applies.
        neg = s < 0
        out = 1.0 + s
        out[neg] = 1.0 / (1.0 - s[neg])
        s = out
    else:
        raise ValueError(f"unknown on_negative={on_negative!r}")

    pos = s > 0
    w = np.zeros_like(s)
    w[pos] = s[pos] / s[pos].sum()
    fixed = np.zeros(len(s), dtype=bool)
    for _ in range(len(s) + 1):
        over = (w > cap + 1e-12) & ~fixed
        if not over.any():
            break
        fixed |= over
        w[fixed] = cap
        free = pos & ~fixed
        room = 1.0 - cap * fixed.sum()
        if not free.any() or room <= 0:
            w[free] = 0.0 if room <= 0 else w[free]
            break
        w[free] = room * s[free] / s[free].sum()
    return {n: float(x) for n, x in zip(names, w)}


def buy_list_weighted(target_weights: Dict[str, float],
                      holdings_value: Dict[str, float], cash: float,
                      open_price: Dict[str, float],
                      max_names: int = 6) -> List[Tuple[str, int]]:
    """E1c §3's SIP: the largest shortfalls against TARGET WEIGHTS.

    E1 §5's machinery unchanged except for where the target comes from: E1
    targets an equal share of the book, E1c targets each name's §3 weight.
    Still at most `max_names` names, still integer shares, still no selling
    to rebalance.
    """
    if cash <= 0 or not target_weights:
        return []
    invested = sum(holdings_value.get(n, 0.0) for n in target_weights)
    total = invested + cash
    shortfalls = []
    for i, (name, w) in enumerate(target_weights.items()):
        sf = total * w - holdings_value.get(name, 0.0)
        if sf > 0 and name in open_price and open_price[name] > 0:
            shortfalls.append((sf, i, name))
    shortfalls.sort(key=lambda t: (-t[0], t[1]))
    out: List[Tuple[str, int]] = []
    remaining = cash
    for sf, _, name in shortfalls[:max_names]:
        px = open_price[name]
        qty = math.floor(min(sf, remaining) / px)
        if qty >= 1:
            out.append((name, qty))
            remaining -= qty * px
        if remaining < min(open_price.values()):
            break
    return out
