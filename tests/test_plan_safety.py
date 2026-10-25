"""Live safety checks (S34 Fsafe) on SYNTHETIC filed quarters."""
from datetime import date

import pandas as pd

from pflab.plan import safety


def quarters(nps, pbt=None, fc=None, start="2024-09-30"):
    ends = pd.date_range(start, periods=len(nps), freq="QE")
    return pd.DataFrame({"quarter_end": ends.date, "net_profit": nps, "pbt": pbt or [x * 1.3 for x in nps],
                         "finance_costs": fc or [1.0] * len(nps)})


def test_a_healthy_company_passes():
    c = safety.evaluate("X", "X", quarters([10, 10, 10, 10, 12, 12, 12, 12]), -0.2)
    assert c.ok and c.ttm_np == 48 and c.ttm_np_prev == 40 and c.latest_quarter == date(2026, 6, 30)


def test_each_test_can_fail_on_its_own():
    assert "F1" in safety.evaluate("X", "X", quarters([1, 1, 1, 1, -1, -1, -1, -1]), 0.0).reasons[0]
    collapse = safety.evaluate("X", "X", quarters([10, 10, 10, 10, 4, 4, 4, 4]), 0.0)
    assert any("F2" in r for r in collapse.reasons)
    debt = safety.evaluate("X", "X", quarters([5] * 8, pbt=[2] * 8, fc=[-3] * 8), 0.0)   # filed negative: abs used
    assert any("F3" in r for r in debt.reasons) and debt.cover == (8 + 12) / 12
    assert any("F4" in r for r in safety.evaluate("X", "X", quarters([10] * 8), -0.6).reasons)


def test_financials_skip_interest_cover_in_every_nse_taxonomy():
    for label in ("BANKS", "FINANCE - HOUSING", "FINANCIAL INSTITUTION", "FINANCIAL SERVICES", "Financial Services"):
        assert safety.is_financial(label), label
    for label in ("Capital Goods", "IT", "POWER", None, ""):
        assert not safety.is_financial(label), label
    lender = quarters([5] * 8, pbt=[2] * 8, fc=[3] * 8)
    assert safety.evaluate("X", "X", lender, 0.0, financial=True).ok


def test_unknown_is_not_safe():
    c = safety.evaluate("X", "X", pd.DataFrame(columns=["quarter_end", "net_profit", "pbt", "finance_costs"]), None)
    assert not c.ok and any("unknown" in r for r in c.reasons)
    gap = quarters([10, 10, 10, 10, 10, 10, 10, 10])
    gap = gap.drop(index=5)                                           # a missing quarter breaks the chain
    assert not safety.evaluate("X", "X", gap, 0.0).ok
