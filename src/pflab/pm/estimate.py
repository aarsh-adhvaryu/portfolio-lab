"""The one type for any forecast or modelled number (PLAN §1).

An `Estimate` never behaves like a bare float: `float(e)`, arithmetic and numeric
format specs raise. The only ways out are `e.value` (explicit, for code that stores it
next to its label) and `e.render()` / `str(e)`, which always print the method and date.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional


def inputs_hash(inputs: Any) -> str:
    """Stable short hash of the inputs an estimate came from."""
    blob = json.dumps(inputs, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


@dataclass(frozen=True)
class Estimate:
    value: float
    method: str
    inputs_hash: str
    as_of: date
    horizon: Optional[str] = None
    unit: str = "Rs"

    def render(self, digits: int = 2) -> str:
        h = f", horizon {self.horizon}" if self.horizon else ""
        v = (f"{self.unit} {self.value:,.{digits}f}" if self.unit == "Rs"
             else f"{self.value:,.{digits}f} {self.unit}")
        return f"~{v} (estimate: {self.method}{h}; as of {self.as_of}; inputs {self.inputs_hash})"

    __str__ = render

    def __float__(self):
        raise TypeError("an Estimate is not a bare number: use .value explicitly or .render()")

    __int__ = __float__

    def __format__(self, spec: str) -> str:
        if spec:
            raise TypeError("an Estimate has no numeric format: use .render()")
        return self.render()

    def _no_arith(self, *_):
        raise TypeError("no arithmetic on an Estimate: take .value explicitly and keep the label")

    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _no_arith
    __lt__ = __gt__ = __le__ = __ge__ = _no_arith


def make(value: float, method: str, inputs: Any, as_of: date, horizon: Optional[str] = None,
         unit: str = "Rs") -> Estimate:
    return Estimate(float(value), method, inputs_hash(inputs), as_of, horizon, unit)
