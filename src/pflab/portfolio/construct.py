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
