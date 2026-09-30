"""E5-A A0 placebo (development review check, 2026-09-30; reported, never gating).

A0 is refitted exactly as locked, except that every training label is
shuffled within its own cross-section (month-end M, horizon h) with a fixed
seed. The shuffled model's rank IC is scored against the TRUE labels. If A0's
edge is real and the pipeline has no leak, the placebo's IC is near zero and
its portfolio is no better than the stack's.

    --ic-only   the store alone (no panel, ~1-2 min): IC per horizon per year
    (default)   also the base row through the engine, written as a one-row
                sweep under experiments/E5-A/diagnostics/placebo-<period>-s<seed>

Run on the locked code, like RUNNING.md job 12:
    cd D:\\pl_runs\\E5-A; $env:PYTHONPATH='D:\\pl_runs\\E5-A\\src';
    $env:PFLAB_EXPERIMENTS_DIR='D:\\portfolio_lab\\experiments';
    D:\\portfolio_lab\\.venv\\Scripts\\python.exe -u D:\\portfolio_lab\\tools\\e5a_placebo.py
The first line names the pflab that imported; outside D:\\pl_runs\\E5-A the
run is refused unless --allow-live.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260930


def shuffle_within(labels: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    """Permute `ret` among the defined, finite labels of each (M, h). Kind,
    interval and observability stay with their row, so every fit trains on
    the same rows at the same dates -- only which name earned what is lost."""
    from pflab.ranker.labels import DEFINED
    rng = np.random.default_rng(seed)
    out = labels.copy()
    ret = out["ret"].to_numpy(dtype=float).copy()
    ok = out["kind"].isin(DEFINED).to_numpy() & np.isfinite(ret)
    for _, idx in out[ok].groupby(["month_end", "h"], sort=True).indices.items():
        pos = np.flatnonzero(ok)[idx]
        ret[pos] = ret[pos][rng.permutation(len(pos))]
    out["ret"] = ret
    return out


def _ic_summary(ic: dict) -> dict:
    """Overall mean monthly IC per horizon, weighted by months."""
    out = {}
    for h, ys in ic.items():
        n = sum(v["months"] for v in ys.values())
        out[h] = {"mean_ic": sum(v["mean_ic"] * v["months"] for v in ys.values()) / n,
                  "months": n}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="e5a_development")
    ap.add_argument("--config", default="configs/e5a_a0.toml")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--ic-only", action="store_true")
    ap.add_argument("--allow-live", action="store_true")
    a = ap.parse_args(argv)

    import pflab
    src = Path(pflab.__file__).resolve()
    print(f"pflab imported from {src}", flush=True)
    if "pl_runs" not in str(src).lower() and not a.allow_live:
        print("REFUSED: not the locked worktree (--allow-live to override)")
        return 2

    from pflab.backtest import runner
    from pflab.backtest.runner import load_config
    from pflab.eval import periods
    from pflab.ranker import store as e5s, walk as e5w

    t0 = time.time()
    cfg = load_config(runner._repo_root() / a.config)
    root = runner._repo_root()
    period = periods.load_periods(root / cfg["evaluation"]["periods_path"])[a.period]
    if period.name == "sealed":
        raise SystemExit("never the sealed period")
    feats, labels, meta = e5s.load(e5s.store_dir(period.name))
    fake = shuffle_within(labels, a.seed)

    class Placebo(e5w.SweepScores):
        def row_extras(self, row, res):
            ex = super().row_extras(row, res)
            ex["rank_ic_vs_shuffled"] = ex.get("rank_ic")
            v = self.rows[row]
            ex["rank_ic"] = e5w.ic_by_year(v["result"]["predictions"], labels,
                                          v["spec"].horizons)
            return ex

    prov = Placebo(feats, fake, period)
    spec = e5w.spec_from_config(cfg)
    res = prov.walk.score(spec, prov.months)
    ic = e5w.ic_by_year(res["predictions"], labels, spec.horizons)
    report = {"period": period.name, "seed": a.seed, "code": str(src),
              "store_files": meta.get("files"),
              "fallback_months": sum(res["fallback"].values()),
              "decisions": len(res["fallback"]),
              "rank_ic_true_labels": ic, "rank_ic_overall": _ic_summary(ic),
              "seconds_ic": round(time.time() - t0, 1)}
    print(json.dumps(report["rank_ic_overall"], indent=1), flush=True)

    from pflab.data import experiments_dir
    out = experiments_dir().resolve() / "E5-A" / "diagnostics" / \
        f"placebo-{period.name}-s{a.seed}"
    out.mkdir(parents=True, exist_ok=True)
    if a.ic_only:
        (out / "placebo_ic.json").write_text(json.dumps(report, indent=1, default=str),
                                             encoding="utf-8")
        print(f"DONE -> {out}  ({report['seconds_ic']} s)")
        return 0

    # the base row through the engine, exactly as the sweep runs it
    from pflab.eval import artifacts, sweep as sweep_mod
    period_, panel, indices, actions, cost_factory, tax, membership = runner.prepare(
        cfg, period.name, None, inputs={})
    e5s.check(meta, cfg, period_, artifacts.data_fingerprint(panel))
    stack_cfg = load_config(runner._repo_root() / (cfg.get("stack") or {}).get(
        "config", "configs/e1.toml"))
    prov = Placebo(feats, fake, period_)
    manifest = {"diagnostic": "E5-A A0 placebo: labels shuffled within (M, h)",
                "seed": a.seed, "code_path": str(src.parent.parent),
                "period": period_.name, "rows": ["base"],
                "store_files": meta.get("files")}
    sweep_mod.run_sweep(cfg, period_, panel, indices, cost_factory, tax,
                        actions=actions, out_dir=out / "sweep", rows=["base"],
                        membership=membership, experiment="E5-A",
                        manifest=manifest, table=sweep_mod.e5a_rows(),
                        stack_config=stack_cfg, score_provider=prov)
    report["seconds_total"] = round(time.time() - t0, 1)
    (out / "placebo_ic.json").write_text(json.dumps(report, indent=1, default=str),
                                         encoding="utf-8")
    print(f"DONE -> {out}  ({report['seconds_total']} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
