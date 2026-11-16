"""The rupee renderer (`app/front_render.py`), still used by `plan/envelope.py`. Kept from the S71 front's tests when the front itself was deleted (S92)."""
from __future__ import annotations


def test_indian_grouping():
    from pflab.app import front_render as fr
    assert fr.inr(172760.8) == "Rs 1,72,761" and fr.inr(-264000) == "-Rs 2,64,000" and fr.inr(950) == "Rs 950" and fr.inr(10_00_00_000) == "Rs 10,00,00,000"
