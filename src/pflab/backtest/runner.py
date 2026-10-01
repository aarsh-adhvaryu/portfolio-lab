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
            unseal_reason: Optional[str] = None, inputs: Optional[dict] = None):
    """(period, panel, indices, actions, cost_factory, tax_policy, membership).

    Nothing here reads a row dated after the period end. That includes the
    index-membership table: `truncate_membership` drops names included after
    the end AND reopens windows that closed after it, so a run cannot know in
    2010 that a name leaves the index in 2024.

    `inputs`, if given, receives the repair inputs that reach the engine only
    through the repaired panel -- BE/BZ rows, the stored factor table and the
    dividend feed -- each cut at the period end, for the run identity.
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

    # D1/D2 (E1 §15, 2026-09-27, approved by Aarsh): BE/BZ stints and ISIN
    # handovers, repaired for every config on the truncated data. The BE rows
    # pass through truncate_end like the panel; the stored factor table only
    # sets adj_factor's constant per-ISIN scale, as it already does.
    from pflab.data import bhavcopy, repairs
    be = periods.truncate_end(bhavcopy.load(end=period.end, series=repairs.NON_EQ), period)
    try:
        all_factors = nca.load()
    except Exception:
        all_factors = None
    # Dividends going ex inside a BE stint are credited (2026-09-28); the
    # feed is cut at the period end like everything else.
    from pflab.data import dividends as dv
    try:
        divs = _upto(dv.load(), "ex_date", period.end)
    except Exception:
        divs = None
    if inputs is not None:
        inputs.update({"be_rows": be, "dividends": divs,
                       "factor_table": None if all_factors is None
                       else _upto(all_factors, "ex_date", period.end)})
    panel, actions, _rep = repairs.apply(panel, actions, be, all_factors, divs)

    # E3-R §11 (c) / E3 §3: the declared ETF split and ISIN switch of
    # 2019-12-19/20, applied after truncation and only for a config that holds
    # ETFs, so every stock-only config sees the panel exactly as before.
    if (config.get("data") or {}).get("etf_events"):
        from pflab.data import etf_events
        panel, actions, _ = etf_events.apply(panel, actions)

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


def _upto(df, col, end):
    """Rows of `df` dated <= end in `col` (a snapshot cut at the period end)."""
    d = pd.to_datetime(pd.Series(df[col], dtype="object"), errors="coerce").dt.date
    return df[pd.Series([x is not None and not pd.isna(x) and x <= end for x in d],
                        index=df.index)]


def _valid_upto(df, end):
    """A dated mapping cut at `end`: rows valid from on or before it, with a
    validity that closes later clipped to end, so a mapping change after the
    period cannot reach the hash."""
    d = _upto(df, "valid_from", end).copy()
    vt = pd.to_datetime(pd.Series(d["valid_to"], dtype="object"), errors="coerce").dt.date
    d["valid_to"] = [min(x, end) if x is not None and not pd.isna(x) else end for x in vt]
    return d


def input_fingerprints(cfg: dict, period, indices, actions, membership,
                       overlap=None, root: Optional[Path] = None,
                       repair_inputs: Optional[dict] = None) -> dict:
    """{input: sha} for everything the run consumes besides the panel, each
    cut at the period end, and the CONTENTS of the policy files (audit
    Deliverable 1 g). Appending data after the end changes nothing here, so
    seal identity holds; editing any consumed input changes the run id."""
    from pflab.data import data_dir
    sha = artifacts.frame_sha
    root = root or _repo_root()
    droot = data_dir()
    end = period.end
    fp = {
        "period": f"{period.name}:{period.start}:{period.end}",
        "periods_file": artifacts.file_sha(root / cfg["evaluation"]["periods_path"]),
        "costs_file": artifacts.file_sha(root / cfg["costs"]["path"]),
        "tax_file": artifacts.file_sha(root / cfg["tax"]["path"]),
        "stack_config": artifacts.file_sha(root / "configs" / "e1.toml"),
        # 2026-09-29 (Aarsh, session 5): the stack is E1 + E1d, so the run
        # identity covers e1d.toml too. Every run id from here on changes;
        # saved runs keep theirs.
        "stack_config_e1d": artifacts.file_sha(root / "configs" / "e1d.toml"),
        "actions": sha(actions),
        "membership": sha(membership),
        "overlap_membership": sha(overlap),
    }
    for key in sorted(indices):
        fp[f"index:{key}"] = sha(indices[key])
    # D1/D2 inputs (2026-09-28): cut at the end again here, so a caller that
    # passes an uncut frame still cannot move the hash by appending.
    for key, col in (("be_rows", "date"), ("factor_table", "ex_date"),
                     ("dividends", "ex_date")):
        if repair_inputs and key in repair_inputs:
            df = repair_inputs[key]
            fp[f"repair:{key}"] = sha(None if df is None else _upto(df, col, end))
    # Tables the engine or its hooks load for themselves, when enabled.
    rf = (cfg.get("red_flags") or {}).get("enabled") or \
        (cfg.get("hooks") or {}).get("intra_month_exit") == "red_flag"
    if rf:
        from pflab.data import red_flag_events as rfe
        fp["red_flag_events"] = sha(_upto(rfe.load(droot), "usable_from", end))
    ps = (cfg.get("promoter_selling") or {}).get("enabled")
    ins = (cfg.get("insider_selling") or {}).get("enabled")
    if ps or ins:
        from pflab.data import bse_scrip_isin
        summ = pd.read_parquet(droot / "bse_shareholding" / "summary.parquet")
        fp["shareholding"] = sha(_upto(summ, "quarter_end", end))
        fp["scrip_isin"] = sha(_valid_upto(bse_scrip_isin.load(droot), end))
    if ins:
        from pflab.data import nse_insider
        fp["insider_pit"] = sha(_upto(nse_insider.load(droot), "broadcast_dt", end))
        fp["symbol_isin"] = sha(_valid_upto(
            pd.read_parquet(droot / "panel" / "symbol_isin_map.parquet"), end))
    if (cfg.get("gears") or {}).get("v_source") == "india_vix":
        fp["india_vix"] = sha(_upto(
            pd.read_parquet(droot / "indices" / "INDIA_VIX.parquet"), "date", end))
    if cfg.get("e5a"):
        # E5-A §5/§6: the feature and label files the models are fitted on,
        # and the LightGBM that fits them, are inputs like any other. The
        # store is built per period from the truncated panel, so appending
        # data after the end cannot reach these hashes either.
        from pflab.ranker import model as e5m, store as e5s
        for f, h in sorted(e5s.file_shas(e5s.store_dir(period.name, droot)).items()):
            fp[f"e5a:{f}"] = h
        from pflab.ranker import family as e5f
        fam = e5f.family_of(cfg)
        members = (("A1", "A2", "A3") if fam == "ALL"      # E5-A-ALL reads all three
                   else () if fam == "A0" else (fam,))
        for m in members:           # a family's own columns (§6b-d)
            fp[f"e5a:{e5f.features_file(m)}"] = e5f.file_sha(
                e5s.store_dir(period.name, droot), m)
        fp["lightgbm"] = e5m.lightgbm_version()
    return fp


def e5a_scores(cfg: dict, period, panel):
    """E5-A's score provider and manifest block, or (None, None) for any
    other config. The feature store must describe THIS panel and universe,
    or the models would be fitted on one dataset and traded on another.
    Shared by `main` and `tools/e1_identity.py`, so an identity check runs
    exactly the sweep's scores."""
    if not cfg.get("e5a"):
        return None, None
    from pflab.ranker import family as e5f, store as e5s, walk as e5w
    from pflab.ranker.features import A0_FEATURES
    sdir = e5s.store_dir(period.name)
    feats, labels, smeta = e5s.load(sdir)
    fam = e5f.family_of(cfg)
    # a family checks A0's store against the A0 part of its config
    e5s.check(smeta, cfg if fam == "A0" else e5f.base_config(cfg), period,
              artifacts.data_fingerprint(panel))
    cols = A0_FEATURES
    e5a_manifest = {"store": str(sdir), "store_files": smeta["files"],
                    "store_code": smeta.get("code"),
                    "store_panel_fingerprint": smeta.get("panel_fingerprint")}
    if fam == "ALL":                # E5-A-ALL: every member's store, each checked
        from pflab.ranker import combined
        ffeats, metas = combined.load(sdir, cfg, period, smeta)
        feats = pd.concat([feats, ffeats], ignore_index=True)
        cols = tuple(combined.columns(cfg))
        e5a_manifest.update({"family": fam, "members": metas})
        del ffeats
    elif fam != "A0":
        ffeats, fmeta = e5f.load(sdir, fam)
        e5f.check(fmeta, cfg, period, smeta)
        feats = pd.concat([feats, ffeats], ignore_index=True)
        cols = tuple(A0_FEATURES) + tuple(e5f.family_features(cfg))
        e5a_manifest.update({"family": fam, "family_file": fmeta["file"],
                             "family_code": fmeta.get("code")})
        del ffeats
    provider = e5w.SweepScores(feats, labels, period, cols)
    del feats
    return provider, e5a_manifest


def main(config_path, period_name=None, unseal_reason=None, sweep=False,
         extra_manifest=None,
         rows=None, kind="sweeps") -> str:
    """`rows` restricts a sweep to named rows; `kind` is the directory the
    run lands in. A regression re-run (the base row and the benchmarks only,
    2026-09-21) uses rows=["base"], kind="regression", so it can never be
    mistaken for, or collide with, an experiment's sweep."""
    from pflab.backtest import engine
    from pflab.eval import sweep as sweep_mod

    cfg = load_config(config_path)
    repair_inputs: dict = {}
    period, panel, indices, actions, cost_factory, tax, membership = prepare(
        cfg, period_name, unseal_reason, inputs=repair_inputs)
    # PFLAB_EXPERIMENTS_DIR (2026-09-26). A locked run executes from a
    # detached worktree, so `_repo_root()` is that worktree, not the repo --
    # results would land inside it and be lost to the next `git worktree
    # prune`. The env var names the one real experiments directory; the
    # config still says which experiment's subdirectory.
    from pflab.data import experiments_dir
    rel = cfg.get("report", {}).get("output_dir", "experiments/E1")
    rel = rel[len("experiments/"):] if rel.startswith("experiments/") else rel
    out_root = experiments_dir().resolve() / rel

    mcfg = cfg.get("membership") or {}
    overlap = None
    if sweep and mcfg.get("overlap_index"):
        from pflab.data import index_membership as im
        try:
            overlap = periods.truncate_membership(
                im.load(mcfg["overlap_index"]), period)
        except Exception:
            overlap = None      # reported as unavailable, never invented

    provider, e5a_manifest = e5a_scores(cfg, period, panel)

    cfg_text = json.dumps(cfg, sort_keys=True, default=str)
    # Audit Deliverable 1 g (2026-09-27): the data identity covers every
    # consumed input cut at the period end, not the panel alone.
    inputs = input_fingerprints(cfg, period, indices, actions, membership, overlap,
                                repair_inputs=repair_inputs)
    fp = artifacts.data_fingerprint(panel, extra={"inputs": inputs})
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
        elif experiment == "E2-D1":
            table = sweep_mod.e2d1_rows()
        elif experiment == "E3-R":
            table = sweep_mod.e3r_rows()
        elif experiment == "E2-D2":
            table = sweep_mod.e2d2_rows()
        elif experiment == "E5-A":
            table = sweep_mod.e5a_rows()
        else:
            table = sweep_mod.ROWS
        rows = list(table) if rows is None else [r for r in table if r in rows]
        # Principle 5: a sweep now carries the same manifest a single run
        # does, so re-running the same inputs verifies and different inputs
        # refuse rather than overwriting (see sweep.SweepConflict).
        manifest = {
            # GATE.md rule 4 (2026-09-26): a locked run records WHICH frozen
            # code produced it, so a result can be traced to the tag it was
            # computed at rather than to whatever the tree held afterwards.
            **(extra_manifest or {}),
            "run_id": rid, "experiment": experiment, "period": period.name,
            "period_start": str(period.start), "period_end": str(period.end),
            "config_sha": artifacts._sha(cfg_text), "data_fingerprint": fp,
            "inputs": inputs,
            "code": commit, "rows": list(rows),
            "first_session": str(panel["date"].min()),
            "last_session": str(panel["date"].max()),
        }
        if (cfg.get("data") or {}).get("etf_events"):
            from pflab.data import etf_events
            manifest["etf_events"] = [{k: str(v) for k, v in e.items()}
                                      for e in etf_events.DECLARED]
        if e5a_manifest is not None:
            manifest["e5a"] = e5a_manifest
        # STACK = the adopted stack, used for the short-window companion runs.
        # E1 base by default, which is what every experiment before E5-A was
        # judged against. From 2026-09-29 the stack is E1 + E1d, and a config
        # judged against it says so in its [stack] block (configs/e5a_a0.toml).
        stack_path = (cfg.get("stack") or {}).get("config", "configs/e1.toml")
        stack_config = load_config(_repo_root() / stack_path)
        sweep_mod.run_sweep(cfg, period, panel, indices, cost_factory, tax,
                            actions=actions, out_dir=out, rows=rows,
                            membership=membership, experiment=experiment,
                            overlap_membership=overlap,
                            overlap_index=mcfg.get("overlap_index",
                                                   "NIFTY200_MOMENTUM30"),
                            manifest=manifest, table=table,
                            stack_config=stack_config,
                            score_provider=provider)
        return str(out)

    res = engine.run(cfg, period, panel, indices.get("NIFTY50_PRICE"),
                     cost_factory(float(cfg.get("costs", {}).get("multiplier", 1.0))),
                     tax, actions=actions, membership=membership,
                     scores=(provider(cfg, "base") if provider else None))
    bench = sweep_mod.run_benchmarks(cfg, period, indices, cost_factory, tax)
    out = out_root / "runs" / f"{period.name}-{rid}"
    artifacts.write_run(out, res, {
        "run_id": rid, "period": period.name,
        "period_start": period.start, "period_end": period.end,
        "config": cfg, "config_sha": artifacts._sha(cfg_text),
        "data_fingerprint": fp, "inputs": inputs, "code": commit,
        "first_session": str(panel["date"].min()),
        "last_session": str(panel["date"].max()),
    }, benchmarks=bench)
    return str(out)
