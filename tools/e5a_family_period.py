"""E5-A §10 for one period: a family's two GATE computations and the mandate.

The full verdict (`classify.classify_e5a`) needs both periods. A family's
development review is written before its validation command exists (session
rule), so this prints the period-level blocks the full verdict is built
from, using the same functions:

- incremental: `gate_rowwise(family, A0)` -- row k against A0's row k (§9);
- adoption:    `gate_for_period(family, STACK)` -- against E1 + E1d;
- mandate:     `mandate_for_period(family)` -- §3 and §5, reported only.

It also reports the first month-end at which the family's holdings differ
from A0's in each row: before it the family's decisions are A0's, so the
family's evidence is the window from there to the period end.

    python tools/e5a_family_period.py --family A1 --period development \
        --cand <sweep> --a0 <A0 sweep> --stack <STACK sweep> [--out file.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pflab.eval import classify


def first_divergence(cand_rows: Path, a0_rows: Path) -> dict:
    """Per row: the first month-end whose held set differs from A0's."""
    out = {}
    for d in sorted(p for p in Path(cand_rows).iterdir() if p.is_dir() and not p.name.startswith("_")):
        a = Path(a0_rows) / d.name / "decisions.json"
        if not a.exists():
            out[d.name] = None
            continue
        ca = json.loads((d / "decisions.json").read_text(encoding="utf-8"))
        aa = {x["month_end"]: set(x.get("held") or ()) for x in json.loads(a.read_text(encoding="utf-8"))}
        diff = [x["month_end"] for x in ca if set(x.get("held") or ()) != aa.get(x["month_end"])]
        out[d.name] = {"first": diff[0] if diff else None,
                       "month_ends_differing": len(diff), "month_ends": len(ca)}
    return out


def drawdown_window(sweep: Path, row: str = "base") -> dict:
    """Peak and trough dates of the row's max drawdown on the engine's
    unitised liquidation NAV (`nav_liq`), checked against criteria.json."""
    import pandas as pd
    e = pd.read_parquet(Path(sweep) / "rows" / row / "equity.parquet").set_index("date")
    nav = e["nav_liq"].dropna()
    dd = 1.0 - nav / nav.cummax()
    trough = dd.idxmax()
    peak = nav.loc[:trough].idxmax()
    crit = json.loads((Path(sweep) / "criteria.json").read_text(encoding="utf-8"))["rows"][row]
    return {"max_drawdown": float(dd.max()), "peak": str(peak)[:10], "trough": str(trough)[:10],
            "matches_criteria": abs(float(dd.max()) - abs(crit["max_drawdown"])) < 1e-9}


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", required=True)
    ap.add_argument("--period", required=True, choices=sorted(classify.E5A_PERIODS))
    ap.add_argument("--cand", required=True)
    ap.add_argument("--a0", required=True)
    ap.add_argument("--stack", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    for d in (a.cand, a.a0):
        classify._e5a_period_guard(d, a.period)
    load = lambda d: json.loads((Path(d) / "criteria.json").read_text(encoding="utf-8"))
    cand, a0, stack = load(a.cand), load(a.a0), load(a.stack)
    res = {"family": a.family, "period": a.period,
           "cand": str(a.cand), "a0": str(a.a0), "stack": str(a.stack),
           "incremental": classify.gate_rowwise(cand, a0),
           "adoption": classify.gate_for_period(cand, stack),
           "mandate": classify.mandate_for_period(cand),
           "holdings_overlap_with_stack": classify._holdings_overlap(a.cand, a.stack),
           "holdings_overlap_with_a0": classify._holdings_overlap(a.cand, a.a0),
           "divergence_from_a0": first_divergence(Path(a.cand) / "rows", Path(a.a0) / "rows"),
           "drawdown_window": {"cand": drawdown_window(a.cand), "a0": drawdown_window(a.a0),
                               "stack": drawdown_window(a.stack)},
           "thresholds": classify.GATE_THRESHOLDS}
    text = json.dumps(res, indent=1, default=str)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return res


if __name__ == "__main__":
    main()
