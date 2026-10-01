"""Gap ladder, E1d and E5-A A0 against B5 (registered in
docs/reviews/gap-ladder.md before any run). DIAGNOSTIC, NOT PROMOTABLE: no
row is a charter row, nothing writes criteria.json, `classify` cannot read it.
Aarsh runs it.

    python tools/gap_ladder.py --strategy E1d --period development
    python tools/gap_ladder.py --strategy E1d --period validation
    python tools/gap_ladder.py --strategy A0  --period e5a_development
    python tools/gap_ladder.py --strategy A0  --period validation

Frictions are added cumulatively in a fixed order (RUNGS): picks (computed,
frictionless, fully invested) -> mechanics (engine, all off) -> + trend brake
-> + six-buy cap -> + costs -> + tax (= the base row). Each step reports the
change in terminal wealth, XIRR, CAGR and MaxDD and its share of the base
row's gap to B5. The registered rule reads E1d development: brake + cap share
= (rung mechanics - rung cap) / (B5 - base), CAGR, against 60%.

Output: experiments/<E1d|E5-A>/diagnostics/gapladder-<period>-<run_id>/
results.json, summary.md, manifest.json. Refuses a dirty tree and an unset
PFLAB_EXPERIMENTS_DIR; never touches the sealed period.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import gap_attribution as ga  # noqa: E402
import gap_diagnosis as gd  # noqa: E402

BIG = gd.BIG
THRESHOLD = 0.60
MEASURES = ("terminal", "xirr", "cagr", "max_drawdown")
# name, what it adds, config overrides, costs on, tax on. Cumulative: each
# rung keeps everything the one before it added; the last is the base row.
RUNGS = (
    ("mechanics", "engine fills, all frictions off",
     {"strategy.trend_filter": "off", "strategy.max_buys_per_month": BIG}, False, False),
    ("brake", "+ trend brake", {"strategy.max_buys_per_month": BIG}, False, False),
    ("cap", "+ six-buy cap", {}, False, False),
    ("costs", "+ costs", {}, True, False),
    ("tax", "+ tax (base row)", {}, True, True),
)
ORDER = ("picks",) + tuple(r[0] for r in RUNGS)


def steps(rows: dict, b5: dict) -> list:
    """Consecutive differences along ORDER, with each step's share of the
    base row's gap to B5: (before - after) / (B5 - base)."""
    base = rows[ORDER[-1]]
    out = []
    for a, b in zip(ORDER, ORDER[1:]):
        d = {k: rows[b][k] - rows[a][k] for k in MEASURES}
        share = {}
        for k in ("terminal", "xirr", "cagr"):
            gap = b5[k] - base[k]
            share[k] = None if not gap else (rows[a][k] - rows[b][k]) / gap
        out.append({"from": a, "to": b, "change": d, "share": share})
    return out


def brake_cap_share(rows: dict, b5: dict) -> float | None:
    """The registered rule's figure: (CAGR mechanics - CAGR cap) / (B5 - base)."""
    gap = b5["cagr"] - rows["tax"]["cagr"]
    return None if not gap else (rows["mechanics"]["cagr"] - rows["cap"]["cagr"]) / gap


def summarise(res: dict, strategy: str, period: str, ident: dict) -> str:
    rows, b5 = res["rows"], res["benchmarks"]["B5"]
    pct = lambda x: "—" if x is None else f"{100 * x:+.0f}%"
    base = rows["tax"]
    lines = [f"# Gap ladder — {strategy}, {period} (DIAGNOSTIC, NOT PROMOTABLE)", "",
             f"Commit `{ident['commit'][:12]}`. Registered in `docs/reviews/gap-ladder.md`.",
             "", f"Gap to B5 (base − B5): CAGR {100 * (base['cagr'] - b5['cagr']):+.2f} pp, "
                 f"XIRR {100 * (base['xirr'] - b5['xirr']):+.2f} pp, terminal "
                 f"₹{(base['terminal'] - b5['terminal']) / 1e5:+.1f} L.", "",
             "| rung | terminal ₹cr | XIRR | CAGR | MaxDD | eq. wt |",
             "|---|---:|---:|---:|---:|---:|"]
    for n in ORDER:
        m = rows[n]
        lines.append(f"| {n} | {m['terminal'] / 1e7:.3f} | {100 * m['xirr']:.2f}% | "
                     f"{100 * m['cagr']:.2f}% | {100 * m['max_drawdown']:.2f}% | "
                     f"{100 * m.get('mean_equity_weight', float('nan')):.1f}% |")
    lines += ["", "| step | Δ terminal ₹L | Δ XIRR pp | Δ CAGR pp | Δ MaxDD pp | "
                  "share of gap CAGR / XIRR / terminal |", "|---|---:|---:|---:|---:|---|"]
    for s in res["steps"]:
        c, sh = s["change"], s["share"]
        lines.append(f"| {s['from']} → {s['to']} | {c['terminal'] / 1e5:+.1f} | "
                     f"{100 * c['xirr']:+.2f} | {100 * c['cagr']:+.2f} | "
                     f"{100 * c['max_drawdown']:+.2f} | {pct(sh['cagr'])} / "
                     f"{pct(sh['xirr'])} / {pct(sh['terminal'])} |")
    lines += ["", "| benchmark | terminal ₹cr | XIRR | CAGR | MaxDD |", "|---|---:|---:|---:|---:|"]
    for k, m in res["benchmarks"].items():
        lines.append(f"| {k} | {m['terminal'] / 1e7:.3f} | {100 * m['xirr']:.2f}% | "
                     f"{100 * m['cagr']:.2f}% | {100 * m['max_drawdown']:.2f}% |")
    bc = res["brake_cap_share"]
    lines += ["", f"**Brake + cap share of the CAGR gap (mechanics → cap): {pct(bc)}** "
                  f"(registered threshold {THRESHOLD:.0%}; the rule reads E1d development only)."]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True, choices=sorted(gd.CONFIGS))
    ap.add_argument("--period", required=True)
    a = ap.parse_args()
    if a.period not in gd.PERIODS[a.strategy] or a.period == "e5a_development" and a.strategy == "E1d":
        sys.exit(f"{a.strategy}: period not in the registration")

    ident = ga._guard()
    os.chdir(REPO)
    from pflab.backtest import engine, runner
    from pflab.data import experiments_dir
    from pflab.eval import artifacts
    from pflab.eval.sweep import BENCHMARKS

    cfg0 = runner.load_config(REPO / gd.CONFIGS[a.strategy])
    t0 = time.time()
    period, panel, indices, actions, cost_factory, tax, membership = runner.prepare(cfg0, a.period)
    if period.sealed:
        sys.exit("refusing: the sealed period")
    trend = indices.get("NIFTY50_PRICE")
    provider, _ = runner.e5a_scores(cfg0, period, panel)
    inputs = runner.input_fingerprints(cfg0, period, indices, actions, membership, None)
    fp = artifacts.data_fingerprint(panel, extra={"inputs": inputs})
    spec = json.dumps({"tool": "gap_ladder", "strategy": a.strategy, "rungs": RUNGS},
                      sort_keys=True, default=str)
    rid = artifacts.run_id(spec, fp, ident["commit"], period.name)
    out_dir = (experiments_dir().resolve() / gd.OUT[a.strategy] / "diagnostics"
               / f"gapladder-{a.period}-{rid}")
    print(f"loaded {a.period} in {(time.time() - t0) / 60:.1f} min", flush=True)

    mult = float(cfg0.get("costs", {}).get("multiplier", 1.0))
    out = {"rows": {}, "benchmarks": {}}
    mech = None
    for n, (name, _, over, costs_on, tax_on) in enumerate(RUNGS, 1):
        cfg = copy.deepcopy(cfg0)
        for k, v in over.items():
            ga._set(cfg, k, v)
        t1 = time.time()
        kw = {"scores": provider(cfg, "base")} if provider else {}
        res = engine.run(cfg, period, panel, trend, cost_factory(mult if costs_on else 0.0),
                         tax if tax_on else ga.zero_tax(tax), actions=actions,
                         membership=membership, **kw)
        out["rows"][name] = ga.row_metrics(res)
        if name == "mechanics":
            mech = res
        print(f"  [{n}/{len(RUNGS)}] {name} {(time.time() - t1) / 60:.1f} min", flush=True)

    eq = mech.equity
    sessions = list(pd.to_datetime(eq["date"]))
    flows = [(pd.Timestamp(d), float(f)) for d, f in zip(eq["date"], eq["flow"]) if f]
    st = cfg0["strategy"]
    out["rows"]["picks"] = gd.selection_metrics(mech.decisions, panel, sessions, flows,
                                                int(st["n_hold"]), int(st["band_exit_rank"]))
    out["rows"] = {k: out["rows"][k] for k in ORDER}
    print("  picks computed", flush=True)

    key, drag = BENCHMARKS["B5"]
    res = engine.run_benchmark(cfg0, period, indices[key], cost_factory(1.0), tax,
                               name=key, expense_ratio=drag)
    out["benchmarks"]["B5"] = ga.row_metrics(res)
    out["steps"] = steps(out["rows"], out["benchmarks"]["B5"])
    out["brake_cap_share"] = brake_cap_share(out["rows"], out["benchmarks"]["B5"])

    text = json.dumps(out, indent=1, default=str)
    if (out_dir / "results.json").exists():
        if (out_dir / "results.json").read_text() != text:
            sys.exit(f"CONFLICT: {out_dir} holds different results for identical inputs")
        print(f"VERIFIED -> {out_dir}", flush=True)
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(text)
    (out_dir / "manifest.json").write_text(json.dumps(
        {**ident, "run_id": rid, "data_fingerprint": fp, "inputs": inputs,
         "strategy": a.strategy, "config": gd.CONFIGS[a.strategy], "period": a.period,
         "rungs": list(ORDER), "diagnostic": "NOT PROMOTABLE",
         "minutes": round((time.time() - t0) / 60, 1)}, indent=1, default=str))
    (out_dir / "summary.md").write_text(summarise(out, a.strategy, a.period, ident),
                                        encoding="utf-8")
    print(f"DONE -> {out_dir}", flush=True)


if __name__ == "__main__":
    main()
