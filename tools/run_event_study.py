"""Run E2-A §8a's pre-registered event study for one period.

    python tools/run_event_study.py e2a_development
    python tools/run_event_study.py e2a_validation
    python tools/run_event_study.py development --report-only   # §8a's 2010-2016

The pass condition lives in the charter and in `eval/event_study.py`; this
script only assembles the inputs and writes the result next to the sweep.
Nothing here may be tuned to make a study pass.

**Truncation (§8a, 2026-09-25).** The panel is cut at the period end by
`periods.truncate_end` before anything is computed, and `period_end` is
passed to the study so a horizon running past it is excluded and COUNTED
rather than silently shortened. No forward return reads a price after the
period end.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from pflab.backtest import engine, runner
from pflab.data import calendar as cal_mod, red_flag_events as rfe
from pflab.eval import event_study, periods as P
from pflab.signals.momentum import momentum_panel


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("period", help="a name in configs/evaluation_periods.toml")
    ap.add_argument("--config", default="configs/e2a.toml")
    ap.add_argument("--out", default=None, help="where to write result.json")
    ap.add_argument("--report-only", action="store_true",
                    help="§8a's 2010-2016 block: reported, never gating")
    a = ap.parse_args(argv)

    cfg = runner.load_config(a.config)
    period, panel, idx, actions, cf, tax, memb = runner.prepare(cfg, a.period)
    panel = P.truncate_end(panel, period)          # the only path, per rule 2

    sessions = sorted(pd.to_datetime(panel["date"]).dt.date.unique())
    cal = cal_mod.from_sessions(sessions)
    wide = lambda col: panel.pivot_table(index="date", columns="isin",
                                         values=col, aggfunc="last")
    open_w, adj_w, turn_w = wide("open"), wide("adj_close"), wide("turnover")
    open_w.index = pd.to_datetime(open_w.index).date
    turn_w.index = pd.to_datetime(turn_w.index).date

    mom = momentum_panel(adj_w, lookback=int(cfg["strategy"].get("lookback_sessions", 252)),
                         skip=int(cfg["strategy"].get("skip_sessions", 21)))
    mom.index = pd.to_datetime(mom.index).date

    # E1's eligible universe at each month-end -- the study's population, so
    # it asks about names the strategy could actually have held.
    uni = engine.precompute_universe(panel, cfg, memb)
    month_ends = [m for m in cal.month_ends(period.start, period.end)]

    def elig(m):
        return list(engine.eligible_at(
            uni, m,
            min_sessions=int(cfg["universe"]["min_sessions"]),
            top_n=int(cfg["universe"]["top_n_by_turnover"]),
            min_price=float(cfg["universe"]["min_price"])))

    ev = rfe.load()
    res = event_study.run(ev, month_ends, elig, open_w, turn_w, mom, cal,
                          periods={period.name: (period.start, period.end)},
                          period_end=period.end)
    res["period"] = period.name
    res["period_start"], res["period_end"] = str(period.start), str(period.end)
    res["report_only"] = bool(a.report_only)
    res["flags_frozen_at"] = rfe.red_flags_commit()

    out = Path(a.out) if a.out else Path("experiments/E2-A") / f"event_study_{period.name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "cohort_detail"},
                     indent=2, default=str))
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
