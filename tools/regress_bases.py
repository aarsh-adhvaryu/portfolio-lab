"""Re-run every verdict's base row and benchmarks under the 2026-09-27
accounting corrections (E1 §15; audit Deliverable 1). Aarsh runs this.

    python tools/regress_bases.py --list
    python tools/regress_bases.py --lane A          # one lane, jobs in order
    python tools/regress_bases.py E1-dev E1-val     # named jobs
    python tools/regress_bases.py --report          # old vs new, base rows
    python tools/regress_bases.py --full --lane A   # every row, for classify

`--full` (2026-09-28) runs each experiment's whole sweep into
experiments/<ID>/sweeps/, so classify has every row (G3, C4); the two
E1-on-E2-A-window jobs stay base-only, since they are only E2-A's STACK.

Four lanes, one per window, run side by side = four sweeps at once (CLAUDE.md).
Each job lands in experiments/<ID>/regression/<period>-<run_id> and drops a
marker experiments/_regress/<job>.json when it finishes; a job with no marker
has not finished. A regression runs on the corrected code at HEAD, not at an
experiment's lock tag: the correction IS the code change. It refuses a dirty
tree, so every result is pinned to one commit, and refuses unless pflab is
imported from this repo and PFLAB_EXPERIMENTS_DIR is set.

Old results are never touched. The sealed period is not in the table.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# job -> (config, period, old base-row directory under experiments/ or None)
JOBS = {
    "E1-dev": ("configs/e1.toml", "development", "E1/regression/development-64343858a094c09e"),
    "E1-val": ("configs/e1.toml", "validation", "E1/regression/validation-303190300ed98ced"),
    "E1b-dev": ("configs/e1b.toml", "development", "E1b/regression/development-1bd44464d9ad3b22"),
    "E1b-val": ("configs/e1b.toml", "validation", "E1b/regression/validation-d9c6819769cffcfb"),
    "E1P-dev": ("configs/e1p.toml", "development", "E1-P/regression/development-fd86c93078e5831f"),
    "E1P-val": ("configs/e1p.toml", "validation", "E1-P/regression/validation-878e107d4d18be5a"),
    "E1c-dev": ("configs/e1c.toml", "development", "E1c/regression/development-efd385871071b039"),
    "E1c-val": ("configs/e1c.toml", "validation", "E1c/regression/validation-6e2e2054c925f2e7"),
    "E1d-dev": ("configs/e1d.toml", "development", "E1d/sweeps/development-a8d5d7cda901a63f"),
    "E1d-val": ("configs/e1d.toml", "validation", "E1d/sweeps/validation-7d350769a6907044"),
    "E2A-dev": ("configs/e2a.toml", "e2a_development", "E2-A/sweeps/e2a_development-9098271bff563780"),
    "E2A-val": ("configs/e2a.toml", "e2a_validation", "E2-A/sweeps/e2a_validation-da6040804aa08fa8"),
    # E2-A's stack: E1 base on E2-A's own windows (STATE.md: 14.60% / 50.04%).
    "E1-e2a-dev": ("configs/e1.toml", "e2a_development", None),
    "E1-e2a-val": ("configs/e1.toml", "e2a_validation", None),
}
# E1 first in every lane that holds it: every GATE comparison is against it.
LANES = {
    "A": ["E1-dev", "E1b-dev", "E1P-dev", "E1-e2a-dev"],
    "B": ["E1-val", "E1b-val", "E1P-val", "E1-e2a-val"],
    "C": ["E1c-dev", "E1d-dev", "E2A-dev"],
    "D": ["E1c-val", "E1d-val", "E2A-val"],
}
REASON = ("E1 §15 2026-09-27 accounting corrections (audit Deliverable 1); "
          "2026-09-28 measurement fixes")


def _experiments() -> Path:
    if not os.environ.get("PFLAB_EXPERIMENTS_DIR"):
        sys.exit("REFUSED: PFLAB_EXPERIMENTS_DIR is not set (CLAUDE.md rule 10)")
    from pflab.data import experiments_dir
    return experiments_dir().resolve()


def _guard() -> dict:
    import pflab
    src = Path(pflab.__file__).resolve()
    if REPO / "src" not in src.parents:
        sys.exit(f"REFUSED: pflab imported from {src}, not {REPO / 'src'}")
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain",
                            "--untracked-files=no"],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        sys.exit("REFUSED: working tree is dirty; commit first so the result "
                 "is pinned to one commit:\n" + dirty)
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return {"pflab": str(src), "commit": head}


def run(job: str, full: bool = False) -> None:
    from pflab.backtest import runner
    cfg, period, _ = JOBS[job]
    full = full and not job.startswith("E1-e2a")
    exp = _experiments()
    ident = _guard()
    marker = exp / "_regress" / f"{job}.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    print(f"== {job}: {cfg} {period}  (pflab {ident['pflab']}, {ident['commit'][:10]})",
          flush=True)
    t0 = time.time()
    os.chdir(REPO)
    out = runner.main(cfg, period, sweep=True, rows=None if full else ["base"],
                      kind="sweeps" if full else "regression",
                      extra_manifest={"regression_of": job, "reason": REASON,
                                      "full": full, "commit": ident["commit"]})
    marker.write_text(json.dumps({"job": job, "config": cfg, "period": period,
                                  "out": out, "full": full, **ident,
                                  "minutes": round((time.time() - t0) / 60, 1),
                                  "finished": time.strftime("%Y-%m-%d %H:%M:%S")},
                                 indent=1))
    print(f"== {job} DONE -> {out}", flush=True)


def _metrics(row_dir: Path) -> dict:
    import pandas as pd
    from pflab.eval.metrics import cagr, max_drawdown
    eq = pd.read_parquet(row_dir / "equity.parquet")
    tr = pd.read_parquet(row_dir / "trades.parquet")
    nav = eq.set_index("date")["nav_liq"]
    return {"cagr": cagr(nav), "mdd": max_drawdown(nav),
            "terminal": float(eq.total.iloc[-1] - eq.liquidation_tax.iloc[-1]
                              - eq.liquidation_costs.iloc[-1]),
            "tax": float(eq.tax_paid_cum.iloc[-1] + eq.liquidation_tax.iloc[-1]),
            "sides": {str(k): int(v) for k, v in tr.side.value_counts().items()}}


def report() -> None:
    exp = _experiments()
    for job, (_, period, old) in JOBS.items():
        m = exp / "_regress" / f"{job}.json"
        new = _metrics(Path(json.loads(m.read_text())["out"]) / "rows" / "base") \
            if m.exists() else None
        was = _metrics(exp / old / "rows" / "base") if old else None
        f = lambda d: (f"{100 * d['cagr']:6.2f}% / {100 * d['mdd']:5.2f}%"
                       if d else "      --       ")
        delta = (f"{100 * (new['cagr'] - was['cagr']):+6.2f} pp"
                 if new and was else "")
        print(f"{job:11s} {period:16s} old {f(was)}   new {f(new)}   {delta}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs", nargs="*")
    ap.add_argument("--lane", choices=sorted(LANES))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()
    if a.list:
        for lane, jobs in LANES.items():
            for j in jobs:
                print(lane, j, *JOBS[j][:2])
        return
    if a.report:
        report()
        return
    jobs = LANES[a.lane] if a.lane else a.jobs
    unknown = [j for j in jobs if j not in JOBS]
    if unknown or not jobs:
        sys.exit(f"unknown or no jobs: {unknown}; see --list")
    for j in jobs:
        run(j, full=a.full)


if __name__ == "__main__":
    main()
