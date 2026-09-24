"""Pre-registered sweep — Phase 2 task 2.6.

Runs the base row and S1-S9 from charter E1 §12 plus all benchmarks, from
ONE config, into experiments/E1/sweeps/<sweep_id>/. Writes summary.md
leading with the base row and labelling everything after it as a stability
check, and criteria.json with the arithmetic for C1-C5.

Every row runs together (principle 3). No row is promotable: the summary
says so in its own heading, and `classify` only ever reads the base row for
C1-C3 and counts rows for C4.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

ROWS = {
    "base": {},
    "S1": {"strategy.lookback_sessions": 189},
    "S2": {"strategy.lookback_sessions": 315},
    "S3": {"strategy.n_hold": 20, "strategy.band_exit_rank": 40},
    "S4": {"strategy.n_hold": 35, "strategy.band_exit_rank": 70},
    "S5": {"costs.multiplier": 2.0},
    "S6": {"strategy.trend_filter": "off"},
    "S7": {"strategy.trend_filter": "sell_to_cash"},
    "S8": {"strategy.cash_rate_annual": 0.04},
    "S9": {"strategy.delisting": "total_loss"},
}

# Charter E1b §6: E1's S1-S9 unchanged, plus two rows of its own.
E1B_EXTRA_ROWS = {
    "S10": {"universe.index": "NIFTY500"},
    "S11": {"universe.mode": "turnover_top_n", "universe.top_n_by_turnover": 200},
    # E1b §6, added 2026-09-18, revised the same day: a guessed start is an
    # INTERVAL, not a missing fact. The base row places each one at the
    # earliest date the name could have joined and S12 at the latest, so the
    # two bracket the truth. Dropping the names instead would have thrown away
    # the part of the universe the reconstruction is least sure about, which is
    # not the same as measuring it.
    "S12": {"universe.membership_bound": "latest"},
    # E1b §6: development restricted to the years Nifty 200 is published
    # rather than derived. E1 base is re-run on the same window so the
    # comparison is like for like.
    "S13": {"period.start": "2012-01-01"},
}


# Charter E1-P §6. The base row is §3's rule as written; each row moves
# exactly one of its terms.
E1P_ROWS = {
    "base": {},
    "S1": {"hooks.patience.min_months": 6},
    "S2": {"hooks.patience.rank_ceiling": 75},
    "S3": {"hooks.patience.rank_ceiling": 150},
    "S4": {"hooks.patience.require_gain": True},
    # §6 S5: "minimum hold of 6 months on every lot regardless of rank
    # (pure patience, tax-blind)". `min_hold_months` replaces the whole base
    # rule -- window, rank and all -- and tests the YOUNGEST lot, because a
    # full-position sale must not sell any lot before the floor.
    "S5": {"hooks.patience.min_hold_months": 6},
}

# Charter E1-P §4. Negative controls: run alongside, reported with the same
# metrics, NEVER adoptable. They are kept out of `e1p_rows()` so that GATE's
# G3 cannot count them -- a control that happened to score well must not push
# the experiment through the gate. Each turns §3's rule OFF, because §4 says
# "everything else as E1".
E1P_CONTROLS = {
    "N1": {"hooks.intra_month_exit": "stop_loss", "hooks.stop_loss_pct": 0.20,
           "hooks.patience.enabled": False},
    "N2": {"hooks.intra_month_exit": "profit_take", "hooks.profit_take_pct": 0.50,
           "hooks.patience.enabled": False},
}


def e1p_rows(include_controls: bool = False) -> dict:
    """E1-P's sweep (§6). §4's controls are not part of it unless asked for."""
    return {**E1P_ROWS, **(E1P_CONTROLS if include_controls else {})}


# Charter E1c §5. Eleven rows, each isolating one of E1's departures from
# the fund's own construction.
E1C_ROWS = {
    "base": {},
    "S1": {"strategy.weighting": "equal"},
    "S2": {"strategy.trend_filter": "sma10"},
    "S3": {"strategy.trend_filter": "sell_to_cash"},
    # S4 is E1's band on the fund's score: back to a monthly cadence, 30 in
    # and 60 out, which is E1's 25/50 scaled to the fund's 30 names.
    "S4": {"strategy.rebalance": "monthly_band", "strategy.n_hold": 30,
           "strategy.band_exit_rank": 60},
    "S5": {"strategy.selection_n": 25},
    # §5 S6 as amended after lock, 2026-09-21: E1's raw 12-1 momentum as the
    # ingredient, through §3's own z-score and ±3 clip, so S6 changes the
    # signal only. As first written it was raw momentum used as the weight
    # itself, which in 2008 had 26 of its top 30 names below zero.
    "S6": {"strategy.signal": "mom_12_1_z"},
    "S7": {"costs.multiplier": 2.0},
    "S8": {"strategy.delisting": "total_loss"},
    "S9": {"strategy.rebalance_months": [3, 6, 9, 12]},
    "S10": {"universe.membership_bound": "latest"},
    # Same mechanism as E1b's S13: `period_for_row` shortens the window and
    # the `_<row>_stack` companion re-runs E1 base on it.
    "S11": {"period.start": "2012-01-01"},
    # §5 S12, added 2026-09-19: NSE standardises each window's ratio and
    # averages the two z-scores; §3 averages the ratios and standardises
    # once. The charter's order stays the base row; this row measures what
    # the other order would have done.
    "S12": {"strategy.score_order": "z_then_average"},
}


def e1c_rows() -> dict:
    """E1c's sweep (§5): the base row plus its eleven."""
    return dict(E1C_ROWS)


# Charter E1d §5. The base row is E1 with ONE change -- E1c §3's
# volatility-scaled 6+12 score replacing raw 12-1 momentum as the RANKING
# signal -- so every row below is E1's own knob except S1, S2 and S8, which
# perturb the new score itself.
E1D_ROWS = {
    "base": {},
    # §5 S1/S2: the score's two components, one at a time. With a single
    # window the two §3 orders coincide, so S8 is not confounded with these.
    "S1": {"strategy.score_windows": [126]},
    "S2": {"strategy.score_windows": [252]},
    "S3": {"strategy.n_hold": 20, "strategy.band_exit_rank": 40},
    "S4": {"strategy.n_hold": 35, "strategy.band_exit_rank": 70},
    "S5": {"costs.multiplier": 2.0},
    "S6": {"strategy.trend_filter": "off"},
    "S7": {"strategy.trend_filter": "sell_to_cash"},
    # §5 S8: NSE's order (z-score each window, then average) against §3's
    # own (average the ratios, then z-score once). E1c ran this as its S12.
    "S8": {"strategy.score_order": "z_then_average"},
    "S9": {"strategy.delisting": "total_loss"},
    # §5 S10: E1b's universe, to show whether the gain depends on holding
    # names outside the Nifty 200 -- which is where E1's 2017-2021 return
    # came from (E1b's verdict). The base row is E1's whole-500 universe
    # (MANDATE §4), so this row switches mode, and configs/e1d.toml carries
    # the [membership] section that `runner.prepare` needs to load the table.
    "S10": {"universe.mode": "index_members", "universe.index": "NIFTY200",
            "universe.membership_bound": "earliest"},
    # §5 S11, added 2026-09-24: S10's development years 2007-2011 run on a
    # declared proxy (CNX 100 union CNX Midcap) because Nifty 200 membership
    # is published and exact only from 2012-01-01, and E1b measured a 2.14 pp
    # development spread from inclusion timing alone -- four times G1's
    # threshold. `period.start` shortens the window and the `_<row>_stack`
    # companion re-runs E1 base on it, the same mechanism as E1b's S13 and
    # E1c's S11.
    "S11": {"universe.mode": "index_members", "universe.index": "NIFTY200",
            "universe.membership_bound": "earliest",
            "period.start": "2012-01-01"},
}


def e1d_rows() -> dict:
    """E1d's sweep (§5): the base row plus its ten."""
    return dict(E1D_ROWS)


def e1b_rows() -> dict:
    """E1b's sweep: the base row, E1's nine, then S10 and S11."""
    return {**ROWS, **E1B_EXTRA_ROWS}


BENCHMARKS = {
    "B1": ("NIFTY50_TRI", 0.0),
    "B2": ("NIFTY500_TRI", 0.0),
    "B3": ("NIFTY200_MOMENTUM30_TRI", 0.003),
    # MANDATE §5 (effective 2026-09-21): Nifty 500 Momentum 50 TRI, the
    # one-click alternative for a whole-500 momentum investor. REPORTED ONLY:
    # never part of GATE or E1 §13's C1-C4; read by classify's mandate block.
    # History before launch is back-computed by NSE (B3's caveat). 0.30% a
    # year expense drag, the same as B3 -- decided by Aarsh 2026-09-21, as
    # the realised annual cost of the index fund it stands for.
    "B5": ("NIFTY500_MOMENTUM50_TRI", 0.003),
}


def rows_present(results: dict, table: Optional[dict] = None) -> list:
    """Row names in charter order, restricted to what actually ran.

    E1b adds S10-S13, so iterating `ROWS` here would drop them from
    summary.md, extras.json, adv_skips.json AND criteria.json -- and
    criteria.json is what §13's C4 and GATE's G3 count rows from. Every
    consumer below goes through this function.

    Rows not in `table` (E1-P's N1/N2, which are deliberately outside its
    sweep) still appear, sorted, after the charter's own order: they are
    reported, just never counted as sweep rows by the charter's arithmetic.
    """
    order = list(table if table is not None else e1b_rows())
    named = [r for r in order if r in results]
    extra = [r for r in results
             if r not in order and not r.startswith("_")
             and isinstance(results[r], dict) and "metrics" in results[r]]
    return named + sorted(extra)


def period_for_row(period, row: str, table: Optional[dict] = None):
    """The period a row runs on. Only a row carrying `period.start` changes it.

    E1b's S13 exists because Nifty 200 membership is published from 2012 and
    derived before it, so the row asks what the answer looks like on the
    published years alone; E1c's S11 is the same mechanism. Every other row
    runs on the chartered window, and a row that silently shortened it would
    not be comparable to anything.

    `table` names the charter's row table. Every charter has an "S1", so a
    lookup that assumed E1b's table would silently apply the wrong change to
    an E1-P or E1c row.
    """
    change = (table if table is not None else e1b_rows()).get(row, {}).get("period.start")
    if not change:
        return period
    from datetime import date as _date
    start = _date.fromisoformat(change) if isinstance(change, str) else change
    if start <= period.start:
        return period
    return type(period)(f"{getattr(period, 'name', '?')}@{start}", start,
                        period.end, *(
                            (period.sealed,) if hasattr(period, "sealed") else ()))


def _say(msg: str) -> None:
    """Progress to stderr, so it never lands in an artifact."""
    print(msg, file=sys.stderr, flush=True)


def _set(cfg: dict, dotted: str, value):
    node = cfg
    parts = dotted.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def apply_row(config: dict, row: str, table: Optional[dict] = None) -> dict:
    """A deep copy of `config` with row `row`'s single change applied.

    `table` is the charter's row table; it defaults to E1/E1b's so existing
    callers are unchanged. Passing it is not optional for E1-P and E1c: row
    names collide across charters and the wrong table would apply the wrong
    change under the right name.
    """
    import copy
    cfg = copy.deepcopy(config)
    for k, v in (table if table is not None else e1b_rows())[row].items():
        _set(cfg, k, v)
    return cfg


_CLOSE_WIDE_CACHE: list = []          # [(panel, close_wide)], length 0 or 1


def _close_wide(panel):
    """The wide close frame E1-P's §7 extras measure forward returns on.

    Cached for one panel at a time: a sweep would otherwise pivot the same
    frame once per row, which on the real panel is minutes of pure
    repetition.

    The cache holds the PANEL ITSELF, not `id(panel)`. Keying on the id and
    storing only the pivot would let a freed panel's id be reused by the next
    period's panel while the stale pivot was still cached -- a validation
    sweep measuring forward returns on development's prices. Holding the
    reference makes that impossible, because the id cannot be reused while
    the object is alive.
    """
    if _CLOSE_WIDE_CACHE and _CLOSE_WIDE_CACHE[0][0] is panel:
        return _CLOSE_WIDE_CACHE[0][1]
    wide = panel.pivot_table(index="date", columns="isin", values="close",
                             aggfunc="last")
    _CLOSE_WIDE_CACHE[:] = [(panel, wide)]
    return wide


class SweepConflict(RuntimeError):
    """A sweep directory already holds a manifest describing different inputs.

    `write_run` has verified-or-refused since Phase 2; `write_summary` did
    not, so a re-run from the same HEAD with edited-but-uncommitted code
    landed on the same content-addressed path and overwrote it silently.
    That cost three sweeps on 2026-09-18. Principle 5 says identical inputs
    verify instead of overwriting; different inputs must not share a path at
    all, so this refuses rather than guessing which one is wanted.
    """


def _persist_rows(results: dict, out_dir: Path,
                  table: Optional[dict] = None) -> dict:
    """Write every row's equity curve and trade ledger under `rows/<row>/`.

    A sweep used to keep only aggregated metrics, so any extra thought of
    later -- the equity/cash decomposition being the case in point -- meant
    re-running twenty minutes of engine to recover curves the run already had
    in memory. These files make the sweep self-sufficient: every extra in §7
    of any charter is computable from them without touching the engine again.

    Reporting only. Nothing reads these back into a decision.
    """
    written = {}
    for row in rows_present(results, table):
        r = results.get(row) or {}
        res = r.get("result")
        if res is None:
            continue
        d = out_dir / "rows" / row
        d.mkdir(parents=True, exist_ok=True)
        eq = res.equity.copy()
        eq.to_parquet(d / "equity.parquet", index=False)
        tr = res.trades.copy()
        tr.to_parquet(d / "trades.parquet", index=False)
        # Decisions as well as curves: E1-P's §7 extra measures the forward
        # return of DEFERRED lots, which lives only in the decision record.
        # Without this the extra would need the re-run this function exists
        # to make unnecessary.
        (d / "decisions.json").write_text(
            json.dumps(res.decisions, indent=2, default=str), encoding="utf-8")
        written[row] = {"equity_rows": int(len(eq)), "trades": int(len(tr)),
                        "decisions": int(len(res.decisions or ()))}
    # Benchmarks too: B1-B4 are engine runs and their curves are as costly to
    # recover as any row's.
    for label, res in (results.get("_benchmark_results") or {}).items():
        d = out_dir / "rows" / f"_{label}"
        d.mkdir(parents=True, exist_ok=True)
        res.equity.to_parquet(d / "equity.parquet", index=False)
        res.trades.to_parquet(d / "trades.parquet", index=False)
        written[f"_{label}"] = {"equity_rows": int(len(res.equity)),
                                "trades": int(len(res.trades))}
    return written


def _check_manifest(out_dir: Path, manifest: Optional[dict]) -> None:
    """Principle 5 for sweeps: identical inputs verify, different ones refuse."""
    if not manifest:
        return
    path = out_dir / "manifest.json"
    if not path.exists():
        return
    prior = json.loads(path.read_text(encoding="utf-8"))
    keys = ("config_sha", "data_fingerprint", "code", "period", "rows")
    diff = [k for k in keys if prior.get(k) != manifest.get(k)]
    if diff:
        raise SweepConflict(
            f"{out_dir} already holds a sweep whose {', '.join(diff)} differ "
            f"from this one. Identical inputs share a directory and verify; "
            f"different inputs must not. Nothing was overwritten. "
            f"Prior code={prior.get('code')}, this code={manifest.get('code')}.")


def run_sweep(config, period, panel, indices, cost_model_factory, tax_policy,
              actions=None, out_dir=None, rows=None, membership=None,
              experiment="E1", overlap_membership=None,
              overlap_index="NIFTY200_MOMENTUM30", manifest=None,
              table=None, stack_config=None) -> dict:
    """Run every row. Returns {row: {"result":..., "metrics":..., "error":...}}.

    A row that halts (charter §7 ADV guard) is recorded as halted rather than
    quietly dropped, because a halted row is information about the strategy.
    """
    from pflab.backtest import engine
    from pflab.eval import artifacts
    from pflab.portfolio.construct import UndefinedWeight

    table = table if table is not None else e1b_rows()
    rows = rows or list(ROWS)
    out: Dict[str, dict] = {}
    _say(f"sweep: {len(rows)} rows, period {getattr(period, 'name', '?')} "
         f"{getattr(period, 'start', '?')}..{getattr(period, 'end', '?')}")
    # §6 reads the Nifty 50 PRICE series, not the whole index dict. Passing the
    # dict silently broke every row whose trend filter was on.
    trend_index = (indices.get("NIFTY50_PRICE")
                   if isinstance(indices, dict) else indices)
    bench = run_benchmarks(config, period, indices, cost_model_factory, tax_policy)
    # B4 needs the panel, not an index series (§10).
    try:
        bench["B4"] = engine.run_equal_weight_universe(
            config, period, panel, cost_model_factory(1.0), tax_policy,
            actions=actions, membership=membership)
    except Exception as e:                       # recorded, never silently absent
        out["_B4_error"] = f"{type(e).__name__}: {e}"
    for n, row in enumerate(rows, 1):
        cfg = apply_row(config, row, table)
        row_period = period_for_row(period, row, table)
        cm = cost_model_factory(float(cfg.get("costs", {}).get("multiplier", 1.0)))
        # A sweep is twenty minutes of silence otherwise: every artifact is
        # written at the end, so without this there is no way to tell a slow
        # run from a hung one.
        _say(f"  [{n}/{len(rows)}] {row}")
        try:
            res = engine.run(cfg, row_period, panel, trend_index, cm, tax_policy,
                             actions=actions, membership=membership)
            extras = artifacts.extras_report(
                res, membership=overlap_membership,
                overlap_index=overlap_index)
            # E1-P §7. Inert for a run that never deferred and never fired a
            # control, so every charter can carry them -- but the close pivot
            # is only built if one of them actually has something to measure.
            # On the real panel that pivot is tens of seconds, and E1 and E1b
            # would otherwise pay it on every sweep to report two zeroes.
            deferred_any = any(d.get("deferred") for d in (res.decisions or ()))
            control_any = (len(res.trades)
                           and (res.trades["side"] == "SELL_INTRA").any())
            cw = _close_wide(panel) if (deferred_any or control_any) else None
            extras["deferred_lots"] = artifacts.deferred_lot_outcomes(res, close_w=cw)
            extras["control_sells"] = artifacts.control_sell_outcomes(res, close_w=cw)
            out[row] = {"result": res, "metrics": artifacts.metrics_of(res, bench),
                        "error": None, "adv_skips": artifacts.adv_skip_report(res),
                        "extras": extras}
        except UndefinedWeight:
            # E1c §3 has no rule for a non-positive selected score, and the
            # code must not invent one (CLAUDE.md 3). That is a question for
            # the charter, not a row that failed, so it STOPS the sweep
            # instead of being recorded and stepped over. Recording it would
            # bury the question under twelve more rows and produce a summary
            # that looked like a result.
            _say(f"  {row}: HALTED by E1c §3 -- stopping the sweep")
            raise
        except Exception as e:
            out[row] = {"result": None, "metrics": None,
                        "error": f"{type(e).__name__}: {e}"}
    # A row that runs on a shorter window cannot be compared with the stack's
    # full-window result, so the stack is re-run on that row's window too.
    for row in rows:
        row_period = period_for_row(period, row, table)
        if row_period is period or out.get(row, {}).get("error"):
            continue
        try:
            # The comparison is the adopted STACK on this window, so it runs
            # the stack's own config. Deriving it from the experiment's config
            # with the universe switched was only right while every experiment
            # shared E1's strategy (E1b did). For E1c it ran E1c's rules on
            # E1's universe under the label "E1 base" (found 2026-09-21).
            if stack_config is not None:
                stack_cfg = stack_config
            else:
                # no stack given (unit tests): the old derivation, which is
                # correct only for an experiment whose strategy is E1's
                stack_cfg = {k: dict(v) if isinstance(v, dict) else v
                             for k, v in config.items()}
                stack_cfg.setdefault("universe", {})
                stack_cfg["universe"] = {**stack_cfg["universe"],
                                         "mode": "turnover_top_n"}
            res = engine.run(stack_cfg, row_period, panel, trend_index,
                             cost_model_factory(1.0), tax_policy, actions=actions)
            # The benchmarks have to move to the row's window too, or the
            # row is being compared with a decade of index return it never saw.
            row_bench = run_benchmarks(config, row_period, indices,
                                       cost_model_factory, tax_policy)
            out[f"_{row}_stack"] = {
                "row": row, "period": str(row_period.start),
                "metrics": artifacts.metrics_of(res, bench),
                "benchmarks": {k: artifacts.metrics_of(v)
                               for k, v in row_bench.items()},
                "note": "E1 base and B1-B3 on the same window, for this "
                        "row's comparison"}
        except Exception as e:
            out[f"_{row}_stack"] = {"row": row, "error": f"{type(e).__name__}: {e}"}

    _say("  benchmarks and artifacts")
    out["_benchmarks"] = {k: artifacts.metrics_of(v) for k, v in bench.items()}
    out["_benchmark_results"] = bench
    if out_dir:
        write_summary(out, Path(out_dir), period, experiment=experiment,
                      manifest=manifest, table=table)
    return out


def run_benchmarks(config, period, indices_by_name, cost_model_factory, tax_policy) -> dict:
    """B1-B3 through the same loop. B4 is added by run_sweep, which has the
    panel it needs."""
    from pflab.backtest import engine
    out = {}
    if not indices_by_name:
        return out
    cm = cost_model_factory(1.0)
    for label, (key, drag) in BENCHMARKS.items():
        series = indices_by_name.get(key) if isinstance(indices_by_name, dict) else None
        if series is None or len(series) == 0:
            continue
        out[label] = engine.run_benchmark(config, period, series, cm, tax_policy,
                                          name=key, expense_ratio=drag)
    return out


def write_summary(results: dict, out_dir: Path, period, experiment="E1",
                  manifest: Optional[dict] = None,
                  table: Optional[dict] = None) -> Path:
    out_dir = Path(out_dir)
    _check_manifest(out_dir, manifest)
    out_dir.mkdir(parents=True, exist_ok=True)
    bench = results.get("_benchmarks", {})
    lines = [f"# {experiment} sweep — {getattr(period, 'name', '?')} "
             f"({getattr(period, 'start', '?')} .. {getattr(period, 'end', '?')})\n",
             "## Base row (the strategy)\n",
             "Everything below the base row is a **stability check**, not a menu.",
             "No row here is promotable to \"the strategy\" (principle 3).\n",
             "| row | window | CAGR (liq) | MaxDD (liq) | turnover/yr | "
             "trades | ADV skips | status |",
             "|---|---|---|---|---|---|---|---|"]
    for row in rows_present(results, table):
        r = results[row]
        rp = period_for_row(period, row, table)
        win = ("full" if rp is period
               else f"{rp.start}..{rp.end}")
        if r.get("error"):
            lines.append(f"| {row} | {win} | — | — | — | — | — | "
                         f"HALTED: {r['error']} |")
            continue
        m = r["metrics"]
        p = m["paths"].get("nav_liq", {})
        sk = r.get("adv_skips") or {}
        lines.append(f"| {row} | {win} | {100*p.get('cagr', float('nan')):.2f}% | "
                     f"{100*p.get('max_drawdown', float('nan')):.2f}% | "
                     f"{m['turnover_annual']:.2f} | {m['trades']['n']} | "
                     f"{sk.get('skips', 0)} | ok |")
    if bench:
        lines += ["\n## Benchmarks (same engine, same SIP, same taxes)\n",
                  "| benchmark | CAGR (liq) | MaxDD (liq) |", "|---|---|---|"]
        for k, m in bench.items():
            p = m["paths"].get("nav_liq", {})
            lines.append(f"| {k} | {100*p.get('cagr', float('nan')):.2f}% | "
                         f"{100*p.get('max_drawdown', float('nan')):.2f}% |")
    stacks = {k: v for k, v in results.items()
              if k.startswith("_") and k.endswith("_stack")}
    if stacks:
        lines += ["", "## Short-window rows: the stack on the same window", "",
                  "A row that runs on a shorter window cannot be compared with",
                  "the stack's full-window result, so E1 base was re-run on",
                  "that row's window for its comparison.", "",
                  "| row | window from | E1 base CAGR (liq) | E1 base MaxDD | "
                  "B1 | B2 | B3 |",
                  "|---|---|---|---|---|---|---|"]
        for k, v in sorted(stacks.items()):
            if v.get("error"):
                lines.append(f"| {v['row']} | — | HALTED: {v['error']} | — | — | — | — |")
                continue
            pp = v["metrics"]["paths"].get("nav_liq", {})
            rb = v.get("benchmarks") or {}

            def _b(key):
                m = (rb.get(key) or {}).get("paths", {}).get("nav_liq", {})
                c = m.get("cagr")
                return f"{100*c:.2f}%" if c is not None else "—"

            lines.append(f"| {v['row']} | {v['period']} | "
                         f"{100*pp.get('cagr', float('nan')):.2f}% | "
                         f"{100*pp.get('max_drawdown', float('nan')):.2f}% | "
                         f"{_b('B1')} | {_b('B2')} | {_b('B3')} |")
    lines += _skip_section(results)
    lines += _extras_section(results, table)
    lines += _patience_section(results, table)
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Persist each row's skip detail so it survives the process (§7, §15).
    (out_dir / "extras.json").write_text(
        json.dumps({r: (results.get(r) or {}).get("extras")
                    for r in rows_present(results, table)}, indent=2, default=str),
        encoding="utf-8")
    (out_dir / "adv_skips.json").write_text(
        json.dumps({r: (results.get(r) or {}).get("adv_skips")
                    for r in rows_present(results, table)}, indent=2, default=str),
        encoding="utf-8")
    (out_dir / "criteria.json").write_text(
        json.dumps(criteria_inputs(results, table), indent=2, default=str),
        encoding="utf-8")
    # Per-row equity curves and trade ledgers, so no future extra needs a
    # re-run to recover a curve this run already had (2026-09-19).
    persisted = _persist_rows(results, out_dir, table)
    if manifest:
        (out_dir / "manifest.json").write_text(
            json.dumps({**manifest, "persisted_rows": persisted}, indent=2,
                       default=str), encoding="utf-8")
    return out_dir / "summary.md"


def criteria_inputs(results: dict, table: Optional[dict] = None) -> dict:
    """Exactly what §13's arithmetic consumes. Written to disk so `classify`
    never recomputes a metric from a different code path."""
    bench = results.get("_benchmarks", {})

    def liq(m):
        return (m or {}).get("paths", {}).get("nav_liq", {})

    out = {"rows": {}, "benchmarks": {k: liq(v) for k, v in bench.items()}}
    for row in rows_present(results, table):
        r = results[row]
        out["rows"][row] = {"error": r.get("error"), **liq(r.get("metrics")),
                            "turnover_annual": (r.get("metrics") or {}).get("turnover_annual")}
    return out


def _skip_section(results: dict) -> list:
    """The §7 skip report: per-year counts, the share of attempted buys
    skipped, and any month where every planned buy was skipped.

    Each element is one line; write_summary joins them, so nothing here
    embeds a newline.
    """
    base = (results.get("base") or {}).get("adv_skips")
    if not base or not base.get("skips"):
        return ["", "## §7 ADV skips", "", "None in the base row."]
    out = ["", "## §7 ADV skips (base row)", "",
           f"{base['skips']} skipped of {base['attempted_buys']} attempted "
           f"buys (**{100 * base['share_skipped']:.1f}%**).", "",
           "| year | skips |", "|---|---|"]
    for y, n in sorted(base["by_year"].items()):
        out.append(f"| {y} | {n} |")
    fully = base.get("months_fully_skipped") or []
    out += ["", f"**Months where every planned buy was skipped: {len(fully)}**"]
    if fully:
        out += ["The SIP went to cash for a liquidity reason, not a strategy",
                "choice, in these months.", "",
                "| date | planned | skipped |", "|---|---|---|"]
        for f in fully[:20]:
            out.append(f"| {f['date']} | {f['planned']} | {f['skipped']} |")
    if base.get("worst"):
        out += ["", "### Ten largest skips by ratio", "",
                "| date | isin | buy value | ADV | ratio |",
                "|---|---|---|---|---|"]
        for w in base["worst"]:
            out.append(f"| {w['date']} | {w['isin']} | {w['buy_value']:,.0f} | "
                       f"{w['adv']:,.0f} | {100 * w['ratio']:.2f}% |")
    return out


def _extras_section(results: dict, table: Optional[dict] = None) -> list:
    """The extras requested in the development review: reporting only.

    Per row: pre-tax CAGR and tax paid. For the base row: delisting exposure,
    RISK_OFF months and cash share by year, and the median turnover rank of
    holdings by year. Each element is one line; write_summary joins them.
    """
    rows = [(r, (results.get(r) or {}).get("extras")) for r in rows_present(results, table)
            if (results.get(r) or {}).get("extras")]
    if not rows:
        return []
    out = ["", "## Extras (reporting only, no decision re-run)", "",
           "### Where the return came from, per row", "",
           "Each day's equity P&L and cash P&L as a share of the whole",
           "portfolio, chained. **The row closes exactly**: equity + cash +",
           "interaction = the after-tax book return, and + tax effect = the",
           "pre-tax CAGR.", "",
           "The **interaction** term is not a residual to ignore. Returns",
           "compose multiplicatively, so two contributions that chain to the",
           "total do not sum to it; the column is the difference between the",
           "product and the plain sum. Version 3 of this table annualised the",
           "two series separately, added the CAGRs, and reconciled the result",
           "against the PRE-tax figure, which the post-tax book can never",
           "reach. The two errors ran opposite ways and cancelled on some",
           "rows, so a row that appeared to close was not evidence that it",
           "did (E1d development: base off by 1.07 pp, S11 by 0.01 pp for no",
           "better reason than luck).", "",
           "The time-weighted sleeve column is reported but is **not** the",
           "headline: it weights every day equally regardless of capital at",
           "risk, so it is distorted whenever §6 has gone to cash.", "",
           "| row | from equity pp | from cash pp | interaction pp | "
           "= after-tax book | tax effect pp | = pre-tax CAGR | "
           "mean equity weight | t-w sleeve |",
           "|---|---|---|---|---|---|---|---|---|"]
    for name, x in rows:
        e = x.get("equity_sleeve") or {}
        if not e.get("available"):
            out.append(f"| {name} | unavailable: {e.get('reason', '?')} | "
                       f"— | — | — | — | — | — | — |")
            continue
        rec = e.get("cagr_pre_tax_for_reconciliation")
        tw = e.get("time_weighted_sleeve_cagr")
        inter = e.get("contribution_interaction_pp")
        book = e.get("cagr_book_after_tax_for_reconciliation")
        taxpp = e.get("tax_effect_pp")
        out.append(
            f"| {name} | {e['contribution_equity_pp']:.2f} | "
            f"{e['contribution_cash_pp']:.2f} | "
            f"{inter:+.2f} | "
            f"{e['contribution_sum_pp']:.2f} | "
            f"{taxpp:+.2f} | "
            f"{(100 * rec):.2f}% | "
            f"{100 * e['mean_equity_weight']:.0f}% | "
            f"{(100 * tw):.2f}% |")

    out += ["", "### Pre-tax CAGR and tax paid, per row", "",
           "| row | CAGR pre-tax | CAGR after tax | tax drag pp | tax paid | "
           "short-term share of gains |",
           "|---|---|---|---|---|---|"]
    for name, x in rows:
        t = x["tax"]
        st = t.get("short_term_share_of_realised_gains_pct")
        out.append(
            f"| {name} | {100 * t['cagr_pre_tax_liq']:.2f}% | "
            f"{100 * t['cagr_after_tax_liq']:.2f}% | {t['tax_drag_pp']:.2f} | "
            f"{t['tax_paid_total']:,.0f} | {('%.1f%%' % st) if st is not None else '-'} |")

    base = dict(rows).get("base")
    if not base:
        return out

    d = base["delisting"]
    out += ["", "### Suspended and delisted holdings (base row)", "",
            f"- names affected: **{d['names']}** "
            f"({d['exits_at_last_close']} exited at last close, "
            f"{d['written_off']} written off)",
            f"- realised P&L on those exits: **{d['realised_pnl']:,.0f}**",
            f"- as a share of contributions: "
            f"{(('%.2f%%' % d['pnl_pct_of_contributions']) if d['pnl_pct_of_contributions'] is not None else '-')}"
            f"; of final value: "
            f"{(('%.2f%%' % d['pnl_pct_of_final_value']) if d['pnl_pct_of_final_value'] is not None else '-')}"]

    r = base["regime"]
    out += ["", "### RISK_OFF months and cash share, by year (base row)", "",
            f"{r['risk_off_months_total']} of {r['months_total']} months were "
            f"RISK_OFF; mean cash share {r['mean_cash_share_pct']:.1f}%.", "",
            "A negative cash share is not an error: section 8 settles the FY tax",
            "bill from the sleeve and allows it to go negative, refilled by later",
            "SIPs before any buy.", "",
            "| year | RISK_OFF months | mean cash share | max cash share |",
            "|---|---|---|---|"]
    for y, v in sorted(r["by_year"].items()):
        out.append(f"| {y} | {v['risk_off_months']} | "
                   f"{v['mean_cash_share_pct']:.1f}% | {v['max_cash_share_pct']:.1f}% |")

    tr = base.get("holdings_turnover_rank") or {}
    if tr:
        out += ["", "### Median turnover rank of holdings, by year (base row)", "",
                "Rank 1 is the most traded name in the eligible universe, so a",
                "rising median means the portfolio drifted into thinner names.", "",
                "| year | median turnover rank | mean names held |", "|---|---|---|"]
        for y, v in sorted(tr.items()):
            out.append(f"| {y} | {v['median_turnover_rank']:.0f} | "
                       f"{v['mean_names_held']:.1f} |")
    ov = base.get("index_overlap")
    if isinstance(ov, dict) and ov.get("by_year"):
        out += ["", f"### Overlap with {ov['index']} constituents, by year (base row)", "",
                "Share of month-end holdings that were constituents of the",
                "momentum index at that month-end (E1b §8). A high share means",
                "E1b is holding what the fund holds; a low one means the gap to",
                "B3 is about selection, not universe.", "",
                f"Overall: **{ov['overall_pct']:.1f}%** of holding-months.", "",
                "| year | overlap | mean names held | mean in index |",
                "|---|---|---|---|"]
        for y, v in sorted(ov["by_year"].items()):
            out.append(f"| {y} | {v['overlap_pct']:.1f}% | {v['mean_names_held']:.1f} | "
                       f"{v['mean_in_index']:.1f} |")
    elif isinstance(ov, str):
        out += ["", "### Overlap with the momentum index (base row)", "", ov]
    out += ["", f"Market-cap proxy: {base['market_cap_proxy']}."]
    return out


def _pct(x, nd=2):
    """Format a number that may legitimately be None. Every extras value can
    be None -- a row where nothing deferred, a forward window with no
    measurable name -- and a bare f-string format would raise on it and take
    the whole summary down with it."""
    return "—" if x is None else f"{x:.{nd}f}"


def _patience_section(results: dict, table: Optional[dict] = None) -> list:
    """E1-P §7's two extras. Silent for any run that never deferred and never
    fired a control, so E1 and E1b summaries are unchanged."""
    rows = [(r, (results.get(r) or {}).get("extras") or {})
            for r in rows_present(results, table)]
    defer = [(r, x.get("deferred_lots") or {}) for r, x in rows]
    ctrl = [(r, x.get("control_sells") or {}) for r, x in rows]
    any_defer = any(d.get("deferrals") for _, d in defer)
    any_ctrl = any(c.get("sells") for _, c in ctrl)
    if not (any_defer or any_ctrl):
        return []

    out = ["", "## E1-P §7 — what patience and impatience did", ""]
    if any_defer:
        out += ["### Deferred lots vs the lots E1 would have sold", "",
                "Forward 3-month return from the month-end, for names §3",
                "deferred against names the same month-end band-sold. A",
                "NEGATIVE gap means the deferred names did worse, i.e. the tax",
                "saving was paid for out of return.", "",
                "| row | deferrals | months with one | deferred fwd % | "
                "band-sold fwd % | gap pp |", "|---|---|---|---|---|---|"]
        for r, d in defer:
            if not d.get("deferrals"):
                continue
            out.append(f"| {r} | {d.get('deferrals')} | "
                       f"{d.get('month_ends_with_a_deferral', '—')} | "
                       f"{_pct(d.get('deferred_forward_mean_pct'))} | "
                       f"{_pct(d.get('band_sold_forward_mean_pct'))} | "
                       f"{_pct(d.get('gap_pp'))} |")
    if any_ctrl:
        out += ["", "### Negative controls (E1-P §4 — never adoptable)", "",
                "Forward 6-month return of the names the control sold, from",
                "the fill. A POSITIVE mean means it sold names that then rose,",
                "so the impatience cost return.", "",
                "| row | sells | names | fwd 6m mean % | fwd 6m median % |",
                "|---|---|---|---|---|"]
        for r, c in ctrl:
            if not c.get("sells"):
                continue
            out.append(f"| {r} | {c.get('sells')} | {c.get('names', '—')} | "
                       f"{_pct(c.get('forward_mean_pct'))} | "
                       f"{_pct(c.get('forward_median_pct'))} |")
    return out
