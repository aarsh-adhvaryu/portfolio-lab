"""Wire a config to a run: load, truncate, run, write artifacts.

This is the ONLY place that turns a config file into data on the engine's
desk, so the seal is enforced in one place (CLAUDE.md 2): the period comes
from `periods.open_period`, which refuses a sealed period without a written
reason and journals the reveal, and the panel reaches the engine only through
`periods.truncate_end`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from pflab import _toml
from pflab.eval import artifacts, periods


def load_config(path) -> dict:
    return _toml.load(path)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def prepare(config: dict, period_name: Optional[str] = None,
            unseal_reason: Optional[str] = None):
    """(period, panel, indices, actions, cost_factory, tax_policy, membership).

    Nothing here reads a row dated after the period end. That includes the
    index-membership table: `truncate_membership` drops names included after
    the end AND reopens windows that closed after it, so a run cannot know in
    2010 that a name leaves the index in 2024.
    """
    from pflab.data import panel as panel_mod, indices as idx_mod
    from pflab.data import nse_corporate_actions as nca
    from pflab.execution.costs import CostModel
    from pflab.tax.india_lots import TaxPolicy

    root = _repo_root()
    name = period_name or config.get("evaluation", {}).get("period", "development")
    regs = periods.load_periods(root / config["evaluation"]["periods_path"])
    period = periods.open_period(name, regs, root / "research" / "journal.jsonl",
                                 unseal_reason=unseal_reason)

    full = panel_mod.load()
    panel = periods.truncate_end(full, period)

    indices = {}
    for key in idx_mod.SERIES:
        try:
            s = idx_mod.load(key)
        except Exception:
            continue
        s = s[pd.to_datetime(s["date"]).dt.date <= period.end]
        indices[key] = s

    try:
        actions = nca.load()
        actions = actions[pd.to_datetime(actions["ex_date"]).dt.date <= period.end]
    except Exception:
        actions = None

    cost_path = root / config["costs"]["path"]
    tax = TaxPolicy.from_toml(root / config["tax"]["path"])

    def cost_factory(mult: float = 1.0):
        return CostModel.from_toml(cost_path, multiplier=mult)

    membership = None
    mcfg = config.get("membership") or {}
    if str(config.get("universe", {}).get("mode", "")) == "index_members" or mcfg:
        from pflab.data import index_membership as im
        parts = []
        for key in {mcfg.get("index", "NIFTY200"),
                    config.get("universe", {}).get("index", "NIFTY200"),
                    "NIFTY500"}:
            try:
                parts.append(im.load(key))
            except Exception:
                continue
        if parts:
            membership = periods.truncate_membership(
                pd.concat(parts, ignore_index=True), period)

    return period, panel, indices, actions, cost_factory, tax, membership


def main(config_path, period_name=None, unseal_reason=None, sweep=False,
         rows=None, kind="sweeps") -> str:
    """`rows` restricts a sweep to named rows; `kind` is the directory the
    run lands in. A regression re-run (the base row and the benchmarks only,
    2026-09-21) uses rows=["base"], kind="regression", so it can never be
    mistaken for, or collide with, an experiment's sweep."""
    from pflab.backtest import engine
    from pflab.eval import sweep as sweep_mod

    cfg = load_config(config_path)
    period, panel, indices, actions, cost_factory, tax, membership = prepare(
        cfg, period_name, unseal_reason)
    out_root = _repo_root() / cfg.get("report", {}).get("output_dir", "experiments/E1")

    cfg_text = json.dumps(cfg, sort_keys=True, default=str)
    fp = artifacts.data_fingerprint(panel)
    commit = artifacts.code_commit()
    # A dirty tree is not pinned by its commit hash, so the code identity
    # carries the source fingerprint too (principle 5).
    rid = artifacts.run_id(cfg_text, fp, artifacts.code_identity(commit),
                           period.name)

    if sweep:
        out = out_root / kind / f"{period.name}-{rid}"
        experiment = str(cfg.get("strategy", {}).get("id", "E1"))
        # Each charter has its own row table, and every charter has an "S1",
        # so the table travels with the rows rather than being looked up by
        # name later (sweep.apply_row).
        if experiment == "E1b":
            table = sweep_mod.e1b_rows()
        elif experiment == "E1-P":
            # §4's N1/N2 run alongside but are not sweep rows; classify_e1p
            # strips them before GATE's G3 counts anything.
            table = sweep_mod.e1p_rows(include_controls=True)
        elif experiment == "E1c":
            table = sweep_mod.e1c_rows()
        elif experiment == "E1d":
            table = sweep_mod.e1d_rows()
        elif experiment == "E2-A":
            table = sweep_mod.e2a_rows()
        else:
            table = sweep_mod.ROWS
        rows = list(table) if rows is None else [r for r in table if r in rows]
        mcfg = cfg.get("membership") or {}
        overlap = None
        if mcfg.get("overlap_index"):
            from pflab.data import index_membership as im
            try:
                overlap = periods.truncate_membership(
                    im.load(mcfg["overlap_index"]), period)
            except Exception:
                overlap = None      # reported as unavailable, never invented
        # Principle 5: a sweep now carries the same manifest a single run
        # does, so re-running the same inputs verifies and different inputs
        # refuse rather than overwriting (see sweep.SweepConflict).
        manifest = {
            "run_id": rid, "experiment": experiment, "period": period.name,
            "period_start": str(period.start), "period_end": str(period.end),
            "config_sha": artifacts._sha(cfg_text), "data_fingerprint": fp,
            "code": commit, "rows": list(rows),
            "first_session": str(panel["date"].min()),
            "last_session": str(panel["date"].max()),
        }
        # STACK = the adopted stack, currently E1 base (E1b and E1-P were
        # REJECTED). Used for the short-window companion runs; change this
        # line, with a dated note, when a change is adopted.
        stack_config = load_config(_repo_root() / "configs" / "e1.toml")
        sweep_mod.run_sweep(cfg, period, panel, indices, cost_factory, tax,
                            actions=actions, out_dir=out, rows=rows,
                            membership=membership, experiment=experiment,
                            overlap_membership=overlap,
                            overlap_index=mcfg.get("overlap_index",
                                                   "NIFTY200_MOMENTUM30"),
                            manifest=manifest, table=table,
                            stack_config=stack_config)
        return str(out)

    res = engine.run(cfg, period, panel, indices.get("NIFTY50_PRICE"),
                     cost_factory(float(cfg.get("costs", {}).get("multiplier", 1.0))),
                     tax, actions=actions, membership=membership)
    bench = sweep_mod.run_benchmarks(cfg, period, indices, cost_factory, tax)
    out = out_root / "runs" / f"{period.name}-{rid}"
    artifacts.write_run(out, res, {
        "run_id": rid, "period": period.name,
        "period_start": period.start, "period_end": period.end,
        "config": cfg, "config_sha": fp, "code": commit,
        "first_session": str(panel["date"].min()),
        "last_session": str(panel["date"].max()),
    }, benchmarks=bench)
    return str(out)
