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


def e1b_rows() -> dict:
    """E1b's sweep: the base row, E1's nine, then S10 and S11."""
    return {**ROWS, **E1B_EXTRA_ROWS}


BENCHMARKS = {
    "B1": ("NIFTY50_TRI", 0.0),
    "B2": ("NIFTY500_TRI", 0.0),
    "B3": ("NIFTY200_MOMENTUM30_TRI", 0.003),
}


def rows_present(results: dict) -> list:
    """Row names in charter order, restricted to what actually ran.

    E1b adds S10 and S11, so iterating `ROWS` here would drop them from
    summary.md, extras.json, adv_skips.json AND criteria.json -- and
    criteria.json is what §13's C4 and GATE's G3 count rows from. Every
    consumer below goes through this function.
    """
    order = list(e1b_rows())
    named = [r for r in order if r in results]
    extra = [r for r in results
             if r not in order and not r.startswith("_")
             and isinstance(results[r], dict) and "metrics" in results[r]]
    return named + sorted(extra)


def period_for_row(period, row: str):
    """The period a row runs on. Only S13 changes it.

    S13 exists because Nifty 200 membership is published from 2012 and
    derived before it, so the row asks what the answer looks like on the
    published years alone. Every other row runs on the chartered window, and
    a row that silently shortened it would not be comparable to anything.
    """
    change = e1b_rows().get(row, {}).get("period.start")
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


def apply_row(config: dict, row: str) -> dict:
    """A deep copy of `config` with row `row`'s single change applied."""
    import copy
    cfg = copy.deepcopy(config)
    for k, v in e1b_rows()[row].items():
        _set(cfg, k, v)
    return cfg


def run_sweep(config, period, panel, indices, cost_model_factory, tax_policy,
              actions=None, out_dir=None, rows=None, membership=None,
              experiment="E1", overlap_membership=None,
              overlap_index="NIFTY200_MOMENTUM30") -> dict:
    """Run every row. Returns {row: {"result":..., "metrics":..., "error":...}}.

    A row that halts (charter §7 ADV guard) is recorded as halted rather than
    quietly dropped, because a halted row is information about the strategy.
    """
    from pflab.backtest import engine
    from pflab.eval import artifacts

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
        cfg = apply_row(config, row)
        row_period = period_for_row(period, row)
        cm = cost_model_factory(float(cfg.get("costs", {}).get("multiplier", 1.0)))
        # A sweep is twenty minutes of silence otherwise: every artifact is
        # written at the end, so without this there is no way to tell a slow
        # run from a hung one.
        _say(f"  [{n}/{len(rows)}] {row}")
        try:
            res = engine.run(cfg, row_period, panel, trend_index, cm, tax_policy,
                             actions=actions, membership=membership)
            out[row] = {"result": res, "metrics": artifacts.metrics_of(res, bench),
                        "error": None, "adv_skips": artifacts.adv_skip_report(res),
                        "extras": artifacts.extras_report(
                            res, membership=overlap_membership,
                            overlap_index=overlap_index)}
        except Exception as e:
            out[row] = {"result": None, "metrics": None,
                        "error": f"{type(e).__name__}: {e}"}
    # A row that runs on a shorter window cannot be compared with the stack's
    # full-window result, so the stack is re-run on that row's window too.
    for row in rows:
        row_period = period_for_row(period, row)
        if row_period is period or out.get(row, {}).get("error"):
            continue
        try:
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
    if out_dir:
        write_summary(out, Path(out_dir), period, experiment=experiment)
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


def write_summary(results: dict, out_dir: Path, period, experiment="E1") -> Path:
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
    for row in rows_present(results):
        r = results[row]
        rp = period_for_row(period, row)
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
    lines += _extras_section(results)
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Persist each row's skip detail so it survives the process (§7, §15).
    (out_dir / "extras.json").write_text(
        json.dumps({r: (results.get(r) or {}).get("extras")
                    for r in rows_present(results)}, indent=2, default=str),
        encoding="utf-8")
    (out_dir / "adv_skips.json").write_text(
        json.dumps({r: (results.get(r) or {}).get("adv_skips")
                    for r in rows_present(results)}, indent=2, default=str),
        encoding="utf-8")
    (out_dir / "criteria.json").write_text(
        json.dumps(criteria_inputs(results), indent=2, default=str), encoding="utf-8")
    return out_dir / "summary.md"


def criteria_inputs(results: dict) -> dict:
    """Exactly what §13's arithmetic consumes. Written to disk so `classify`
    never recomputes a metric from a different code path."""
    bench = results.get("_benchmarks", {})

    def liq(m):
        return (m or {}).get("paths", {}).get("nav_liq", {})

    out = {"rows": {}, "benchmarks": {k: liq(v) for k, v in bench.items()}}
    for row in rows_present(results):
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


def _extras_section(results: dict) -> list:
    """The extras requested in the development review: reporting only.

    Per row: pre-tax CAGR and tax paid. For the base row: delisting exposure,
    RISK_OFF months and cash share by year, and the median turnover rank of
    holdings by year. Each element is one line; write_summary joins them.
    """
    rows = [(r, (results.get(r) or {}).get("extras")) for r in rows_present(results)
            if (results.get(r) or {}).get("extras")]
    if not rows:
        return []
    out = ["", "## Extras (reporting only, no decision re-run)", "",
           "### Where the return came from, per row", "",
           "Each day's equity P&L and cash P&L as a share of the whole",
           "portfolio, chained. The two ADD UP to the pre-tax return, which is",
           "what separates the signal from the cash carry.", "",
           "The time-weighted sleeve column is reported but is **not** the",
           "headline: it weights every day equally regardless of capital at",
           "risk, so it is distorted whenever §6 has gone to cash.", "",
           "| row | from equity pp | from cash pp | sum | pre-tax CAGR | "
           "mean equity weight | t-w sleeve |",
           "|---|---|---|---|---|---|---|"]
    for name, x in rows:
        e = x.get("equity_sleeve") or {}
        if not e.get("available"):
            out.append(f"| {name} | unavailable: {e.get('reason', '?')} | "
                       f"— | — | — | — | — |")
            continue
        rec = e.get("cagr_pre_tax_for_reconciliation")
        tw = e.get("time_weighted_sleeve_cagr")
        out.append(
            f"| {name} | {e['contribution_equity_pp']:.2f} | "
            f"{e['contribution_cash_pp']:.2f} | "
            f"{e['contribution_sum_pp']:.2f} | "
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
