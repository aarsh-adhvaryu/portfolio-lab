"""Read-only synthetic audit of the uploaded portfolio_system snapshot.

Usage: python verify_accounting.py /path/to/portfolio_system
No market data, sealed results, network, or source edits are required.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT / "src"))
from pflab.backtest import engine
from pflab.eval.periods import Period
from pflab.execution.costs import CostModel
from pflab.tax.india_lots import LotBook, TaxPolicy

COST = CostModel(multiplier=0.0)
POLICY = TaxPolicy()


def panel(sessions, prices, name="TEST", dividend=None):
    prices = np.asarray(prices, dtype=float)
    return pd.DataFrame({
        "date": sessions, "isin": name, "symbol": name, "series": "EQ",
        "instrument_type": "STK", "open": prices, "high": prices,
        "low": prices, "close": prices,
        "prev_close": np.r_[prices[0], prices[:-1]],
        "volume": 100000, "turnover": 1e10, "adj_factor": 1.0,
        "adj_open": prices, "adj_close": prices,
        "dividend": [float((dividend or {}).get(d, 0.0)) for d in sessions],
    })


def config():
    return {"strategy": {
        "n_hold": 1, "band_exit_rank": 999, "max_buys_per_month": 1,
        "lookback_sessions": 1, "skip_sessions": 0,
        "sip_amount": 10000.0, "initial_cash": 0.0,
        "cash_rate_annual": 0.0, "trend_filter": "off",
        "delisting": "last_close", "delist_confirm_sessions": 250,
    }, "universe": {
        "series": ["EQ"], "min_sessions": 1, "top_n_by_turnover": 500,
        "turnover_window": 1, "min_price": 0.0, "max_adv_fraction": 1.0,
    }}


def run(cfg, p, actions=None):
    return engine.run(cfg, Period("synthetic", min(p.date), max(p.date)),
                      p, None, COST, POLICY, actions=actions)


findings = {}

# An investor making their first purchase ON the split's ex-date should
# receive only the shares purchased, not a second adjustment of those shares.
ss = list(pd.bdate_range("2020-01-01", "2020-02-04").date)
ex = date(2020, 2, 3)
p = panel(ss, [100.0 if d < ex else 50.0 for d in ss])
a = pd.DataFrame([{"isin": "TEST", "ex_date": ex,
                   "factor": 0.5, "source": "purpose"}])
r = run(config(), p, a)
row = r.equity.loc[r.equity.date == ex].iloc[0]
findings["ex_date_purchase_split"] = {
    "contributed": float(r.equity.flow.sum()),
    "value_after_ex_date_purchase": float(row.total),
    "purchased_shares": int(r.trades.loc[r.trades.side == "BUY", "qty"].sum()),
    "shares_credited_by_action": sum(w.get("shares_added", 0) for w in r.warnings),
    "expected_value_before_tax_and_zero_costs": 20000.0,
}

# A first purchase on the dividend's ex-date has no entitlement to it.
p = panel(ss, [100.0 if d < ex else 90.0 for d in ss], dividend={ex: 10.0})
r = run(config(), p)
findings["ex_date_purchase_dividend"] = {
    "dividend_credited_to_first_time_buyer": float(r.equity.dividends.sum()),
    "expected_dividend": 0.0,
}

# A cash-only strategy crosses an FY boundary and the terminal date.
ss_cash = list(pd.bdate_range("2019-01-01", "2020-12-31").date)
cfg = config()
cfg["strategy"]["cash_rate_annual"] = 0.06
cfg["universe"]["min_sessions"] = 100000
r = run(cfg, panel(ss_cash, [100.0] * len(ss_cash)))
findings["cash_interest_tax"] = {
    "contributed": float(r.equity.flow.sum()),
    "cash_earned": float(r.equity.total.iloc[-1] - r.equity.flow.sum()),
    "tax_paid": float(r.equity.tax_paid_cum.iloc[-1]),
    "terminal_tax": float(r.equity.liquidation_tax.iloc[-1]),
}


def terminal_rows():
    return pd.DataFrame({"date": [date(2020, 1, 2), date(2020, 1, 3)],
                         "equity_value": [0.0, 0.0],
                         "cash": [20000.0, 20000.0], "flow": [20000.0, 0.0]})


# Being all cash does not erase capital gains already realised this FY.
b = LotBook(POLICY)
b.buy("TEST", date(2019, 12, 1), 100, 100.0)
b.sell("TEST", date(2020, 1, 2), 100, 200.0)
expected = copy.deepcopy(b).settle_fy(2020).total
e, _ = engine._finalise(terminal_rows(), b, {}, COST, POLICY, [], [])
findings["terminal_tax_after_complete_sale"] = {
    "realised_gain": 10000.0, "actual_terminal_tax": float(e.liquidation_tax.iloc[-1]),
    "tax_due_under_project_policy": float(expected),
}


class BrokenTaxBook(LotBook):
    def simulate_liquidation(self, *args, **kwargs):
        raise RuntimeError("Injected tax computation failure")


b = BrokenTaxBook(POLICY)
b.buy("TEST", date(2019, 1, 1), 1, 100.0)
e, _ = engine._finalise(terminal_rows(), b, {"TEST": 100.0}, COST, POLICY, [], [])
findings["terminal_tax_exception"] = {
    "exception_propagated": False,
    "reported_terminal_tax": float(e.liquidation_tax.iloc[-1]),
}

# Keep another security trading so the market calendar continues after TEST
# disappears. TEST is bought before disappearance; it never returns.
ss_dead = list(pd.bdate_range("2019-01-01", "2020-04-30").date)
cut = date(2019, 2, 5)
p = pd.concat([
    panel([d for d in ss_dead if d < cut], [100.0] * sum(d < cut for d in ss_dead)),
    panel(ss_dead, [1.0] * len(ss_dead), name="CALENDAR"),
], ignore_index=True)
cfg = config()
cfg["universe"]["min_price"] = 10.0
r = run(cfg, p)
sales = r.trades.loc[r.trades.side == "SELL_DELIST"]
findings["suspension_old_price_sale"] = {
    "nontrading_exit_count": int(len(sales)),
    "recovered_cash_gross": float((sales.qty * sales.fill_price).sum()),
    "transactions": sales.to_dict("records"),
    "last_market_quote": "2019-02-04",
    "missing_sessions_before_exit": [w["missing_sessions"] for w in r.warnings
                                      if w["kind"] == "delist_exit"],
}

# The common adjustment does not create distinct zero-basis bonus lots.
b = LotBook(POLICY)
b.buy("TEST", date(2018, 1, 1), 100, 100.0)
b.adjust_shares("TEST", 0.5)
rs = b.sell("TEST", date(2020, 2, 4), 200, 60.0)
findings["bonus_lots"] = {
    "assumed_bonus_allotment": "2020-02-03",
    "realised_lots": [vars(x) | {"gain": x.gain} for x in rs],
    "expected_lot_structure": "100 original shares at basis 100; 100 new shares at basis 0 with their allotment date",
}

# Splitting a consolidation across small lots can retain a zero allocation
# as a positive old lot. Five shares / factor four should not become three.
b = LotBook(POLICY)
for i, qty in enumerate([1, 1, 3]):
    b.buy("TEST", date(2019, 1, i + 1), qty, 100.0)
b.adjust_shares("TEST", 4.0)
findings["consolidation_zero_allocation"] = {
    "shares_before": 5, "factor": 4.0, "shares_after": b.holdings("TEST"),
    "expected_whole_shares_plus_fractional_claim": "1 whole share and a 0.25-share fractional entitlement",
}

assert findings["ex_date_purchase_split"]["value_after_ex_date_purchase"] == 40000.0
assert findings["ex_date_purchase_dividend"]["dividend_credited_to_first_time_buyer"] > 0
assert findings["cash_interest_tax"]["cash_earned"] > 0
assert findings["cash_interest_tax"]["tax_paid"] == 0
assert findings["terminal_tax_after_complete_sale"]["actual_terminal_tax"] == 0
assert findings["terminal_tax_after_complete_sale"]["tax_due_under_project_policy"] == 2080.0
assert findings["suspension_old_price_sale"]["nontrading_exit_count"] == 1
assert findings["consolidation_zero_allocation"]["shares_after"] == 3
print(json.dumps(findings, indent=2, default=str))
