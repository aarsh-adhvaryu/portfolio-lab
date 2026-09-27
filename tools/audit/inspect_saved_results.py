"""Read saved E1 development/validation artifacts; never rerun or open sealed data.

Usage: python inspect_saved_results.py /path/to/portfolio_system
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT / "src"))
from pflab.eval.metrics import cagr, max_drawdown, xirr

RUNS = {
    "development": "development-64343858a094c09e",
    "validation": "validation-303190300ed98ced",
}

out = {}
for period, run in RUNS.items():
    out[period] = {}
    for label, row in (("E1", "base"), ("B2", "_B2"), ("B5", "_B5")):
        folder = ROOT / "experiments/E1/regression" / run / "rows" / row
        eq = pd.read_parquet(folder / "equity.parquet")
        tr = pd.read_parquet(folder / "trades.parquet")
        nav = eq.set_index("date")["nav_liq"]
        terminal = float(eq.total.iloc[-1] - eq.liquidation_tax.iloc[-1]
                         - eq.liquidation_costs.iloc[-1])
        flows = eq.loc[eq.flow != 0, ["date", "flow"]]
        stale = tr.loc[tr.side == "SELL_DELIST"]
        credits = tr.loc[tr.side == "CASH_CREDIT"]
        out[period][label] = {
            "artifact_path": str(folder.relative_to(ROOT)),
            "cagr_after_tax_liquidation": cagr(nav),
            "max_drawdown": max_drawdown(nav),
            "contributions": float(eq.flow.sum()),
            "terminal_net_value": terminal,
            "xirr": xirr(list(flows.date) + [eq.date.iloc[-1]],
                         list(-flows.flow) + [terminal]),
            "mean_daily_cash_fraction": float((eq.cash / eq.total).mean()),
            "tax_paid": float(eq.tax_paid_cum.iloc[-1]),
            "terminal_tax": float(eq.liquidation_tax.iloc[-1]),
            "trade_counts": {str(k): int(v) for k, v in tr.side.value_counts().items()},
            "stale_price_liquidation_gross": float((stale.qty * stale.fill_price).sum()),
            "stale_price_liquidations": stale.to_dict("records"),
            "synthetic_action_credit_gross": float((credits.qty * credits.fill_price).sum()),
        }
    out[period]["mandate_base_return_hurdle"] = max(
        out[period]["B2"]["cagr_after_tax_liquidation"] + .03,
        out[period]["B5"]["cagr_after_tax_liquidation"] + .02,
    )
    out[period]["base_return_gap_to_hurdle"] = (
        out[period]["mandate_base_return_hurdle"]
        - out[period]["E1"]["cagr_after_tax_liquidation"]
    )

print(json.dumps(out, indent=2, default=str))
