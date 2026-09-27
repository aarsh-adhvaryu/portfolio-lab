"""E1 development gap attribution (audit Deliverable 2). DIAGNOSTIC, NOT
PROMOTABLE: no row here is a charter row, nothing writes criteria.json, and
`classify` cannot read the output. Aarsh runs it.

    python tools/gap_attribution.py                  # every control, development
    python tools/gap_attribution.py --rows base trend_off   # smoke / subset
    python tools/gap_attribution.py --list

Each control changes ONE thing from E1 base (configs/e1.toml) on the same
panel, universe and decision dates; `deploy_all_off` and `frictionless` are
the combined rows that show the interaction. Benchmarks B2/B5 are run twice:
as in every sweep (costs, tax, B5's 0.30% drag) and frictionless (no costs,
no tax, no drag), so the selection-plus-weighting residual can be read
against the index on the same footing.

Output: experiments/E1/diagnostics/gap-<period>-<run_id>/ with
results.json, summary.md, manifest.json. Refuses a dirty tree (the result is
pinned to one commit) and refuses unless PFLAB_EXPERIMENTS_DIR is set.
Never touches the sealed period: only development and validation are allowed.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BIG = 10 ** 6

# row -> (group, one-line description, {dotted config override}, special)
# special: None | "costs0" | "tax0" | "both0"
DEPLOY = {"strategy.trend_filter": "off", "strategy.max_buys_per_month": BIG,
          "strategy.topup_max_rank": 25, "universe.max_adv_fraction": 1e18}
CONTROLS = {
    "base": ("base", "E1 base as chartered", {}, None),
    "trend_off": ("deployment", "s6 trend filter off (never RISK_OFF)",
                  {"strategy.trend_filter": "off"}, None),
    "cap_off": ("deployment", "s5 six-buy cap removed (every shortfall filled)",
                {"strategy.max_buys_per_month": BIG}, None),
    "topup_top25": ("deployment", "rank eligibility: held names ranked 26-50 get no top-up",
                    {"strategy.topup_max_rank": 25}, None),
    "adv_off": ("deployment", "s7 liquidity skips off (no ADV ceiling)",
                {"universe.max_adv_fraction": 1e18}, None),
    "deploy_all_off": ("deployment", "all four deployment changes together", DEPLOY, None),
    **{f"lottery_{s}": ("selection", f"fixed random score per ISIN, seed {s}",
                        {"strategy.signal": "lottery", "strategy.lottery_seed": s}, None)
       for s in range(1, 6)},
    "mom_weighted": ("weighting",
                     "weights proportional to momentum (NSE-normalised, 5% cap) instead of equal",
                     {"strategy.weighting": "score_tilted",
                      "strategy.weighting_negative": "nse_normalised",
                      "strategy.weight_cap": 0.05}, None),
    "costs_0": ("costs", "all costs zero (STT, charges, stamp, DP)", {}, "costs0"),
    "tax_0": ("tax", "all tax zero (gains, dividends, interest)", {}, "tax0"),
    "frictionless": ("combined", "deployment changes + zero costs + zero tax",
                     DEPLOY, "both0"),
}


def _set(cfg: dict, dotted: str, value) -> None:
    node = cfg
    *head, last = dotted.split(".")
    for k in head:
        node = node.setdefault(k, {})
    node[last] = value


def _guard() -> dict:
    if not os.environ.get("PFLAB_EXPERIMENTS_DIR"):
        sys.exit("REFUSED: PFLAB_EXPERIMENTS_DIR is not set (CLAUDE.md rule 10)")
    import pflab
    src = Path(pflab.__file__).resolve()
    if REPO / "src" not in src.parents:
        sys.exit(f"REFUSED: pflab imported from {src}, not {REPO / 'src'}")
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain",
                            "--untracked-files=no"],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        sys.exit("REFUSED: working tree is dirty; commit first:\n" + dirty)
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return {"pflab": str(src), "commit": head}


def zero_tax(policy):
    return replace(policy, stcg_rate=0.0, ltcg_rate=0.0, cess=0.0,
                   dividend_rate=0.0, interest_rate=0.0)


def row_metrics(res) -> dict:
    """CAGR and MaxDD of the liquidation-adjusted NAV (the sweeps' basis),
    plus terminal wealth after liquidation and the SIP's XIRR."""
    import pandas as pd
    from pflab.eval import metrics as M
    eq = res.equity
    nav = pd.Series(eq["nav_liq"].values, index=pd.to_datetime(eq["date"])).dropna()
    terminal = float(eq["total"].iloc[-1] - eq["liquidation_tax"].iloc[-1]
                     - eq["liquidation_costs"].iloc[-1])
    flows = eq[eq["flow"] != 0]
    dates = list(flows["date"]) + [eq["date"].iloc[-1]]
    amounts = [-float(f) for f in flows["flow"]] + [terminal]
    tr = res.trades
    total = eq["equity_value"] + eq["cash"]
    ew = (eq["equity_value"] / total.where(total > 0)).mean()
    return {"cagr": M.cagr(nav), "max_drawdown": M.max_drawdown(nav),
            "terminal": terminal, "contributed": float(eq["flow"].sum()),
            "xirr": M.xirr(dates, amounts),
            "mean_equity_weight": float(ew),
            "trades": int(len(tr)),
            "buys": int((tr["side"] == "BUY").sum()) if len(tr) else 0,
            "costs": float(tr["costs"].sum()) if len(tr) else 0.0,
            "tax": float(res.taxes["tax"].sum() if len(res.taxes) else 0.0)
                   + float(eq["liquidation_tax"].iloc[-1]),
            "adv_skips": int(len(res.adv_skips)),
            "write_downs": sum(1 for w in (res.warnings or ())
                               if w.get("kind") in ("write_off", "write_down"))}


def required(bench: dict) -> dict:
    """MANDATE §3 (B2 + 3 pp) and §5 (B5 + 2 pp), on CAGR and on XIRR."""
    out = {}
    for label, key, pp in (("§3 B2+3", "B2", 0.03), ("§5 B5+2", "B5", 0.02)):
        b = bench[key]
        out[label] = {"cagr": b["cagr"] + pp, "xirr": b["xirr"] + pp}
    out["binding"] = max(("§3 B2+3", "§5 B5+2"), key=lambda k: out[k]["cagr"])
    return out


def terminal_at(rate: float, flows) -> float:
    """Wealth at the last date if every contribution compounded at `rate`."""
    import pandas as pd
    end = pd.Timestamp(flows[-1][0])
    return sum(a * (1 + rate) ** ((end - pd.Timestamp(d)).days / 365.0)
               for d, a in flows[:-1])


def summarise(res: dict, req: dict, period: str, ident: dict) -> str:
    base = res["rows"]["base"]
    b = req[req["binding"]]
    lines = [f"# E1 gap attribution — {period} (DIAGNOSTIC, NOT PROMOTABLE)", "",
             f"Commit `{ident['commit'][:12]}`. One change per row from E1 base; "
             "Δ is the row minus base. Nothing here is a charter row.", "",
             f"Required ({req['binding']}): CAGR {100*b['cagr']:.2f}%, XIRR "
             f"{100*b['xirr']:.2f}%, terminal ₹{(req['required_terminal'] or 0)/1e7:.2f} cr. "
             f"Base: CAGR {100*base['cagr']:.2f}%, XIRR {100*base['xirr']:.2f}%, "
             f"terminal ₹{base['terminal']/1e7:.2f} cr.", "",
             "| row | group | CAGR | Δ pp | MaxDD | XIRR | Δ pp | terminal ₹cr | Δ ₹L | eq. wt | trades | skips | write-downs |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, m in res["rows"].items():
        if m.get("error"):
            lines.append(f"| {name} | {CONTROLS[name][0]} | error: {m['error']} |")
            continue
        lines.append(
            f"| {name} | {CONTROLS[name][0]} | {100*m['cagr']:.2f}% | "
            f"{100*(m['cagr']-base['cagr']):+.2f} | {100*m['max_drawdown']:.2f}% | "
            f"{100*m['xirr']:.2f}% | {100*(m['xirr']-base['xirr']):+.2f} | "
            f"{m['terminal']/1e7:.3f} | {(m['terminal']-base['terminal'])/1e5:+.1f} | "
            f"{100*m['mean_equity_weight']:.0f}% | {m['trades']} | {m['adv_skips']} | "
            f"{m['write_downs']} |")
    lines += ["", "| benchmark | CAGR | MaxDD | XIRR | terminal ₹cr |",
              "|---|---:|---:|---:|---:|"]
    for k, m in res["benchmarks"].items():
        lines.append(f"| {k} | {100*m['cagr']:.2f}% | {100*m['max_drawdown']:.2f}% | "
                     f"{100*m['xirr']:.2f}% | {m['terminal']/1e7:.3f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="development",
                    choices=["development", "validation"])
    ap.add_argument("--rows", nargs="*")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for k, (g, d, _, _) in CONTROLS.items():
            print(f"{k:15s} {g:11s} {d}")
        return
    rows = a.rows or list(CONTROLS)
    bad = [r for r in rows if r not in CONTROLS]
    if bad:
        sys.exit(f"unknown rows {bad}; see --list")
    if "base" not in rows:
        rows = ["base"] + rows

    ident = _guard()
    os.chdir(REPO)
    from pflab.backtest import engine, runner
    from pflab.data import experiments_dir
    from pflab.eval.sweep import BENCHMARKS

    cfg0 = runner.load_config(REPO / "configs" / "e1.toml")
    t0 = time.time()
    period, panel, indices, actions, cost_factory, tax, membership = runner.prepare(
        cfg0, a.period)
    trend = indices.get("NIFTY50_PRICE")
    # Principle 5: the directory is named by everything that can change the
    # result -- rows and their overrides, every input cut at period end, and
    # the commit -- and an existing one is verified, never overwritten.
    from pflab.eval import artifacts
    inputs = runner.input_fingerprints(cfg0, period, indices, actions, membership, None)
    fp = artifacts.data_fingerprint(panel, extra={"inputs": inputs})
    spec = json.dumps({r: [CONTROLS[r][2], CONTROLS[r][3]] for r in rows},
                      sort_keys=True, default=str)
    rid = artifacts.run_id(spec, fp, ident["commit"], period.name)
    exp = experiments_dir().resolve() / "E1" / "diagnostics" / f"gap-{a.period}-{rid}"
    print(f"loaded {a.period} in {(time.time()-t0)/60:.1f} min", flush=True)

    out = {"rows": {}, "benchmarks": {}}
    base_flows = None
    for n, row in enumerate(rows, 1):
        _, _, over, special = CONTROLS[row]
        cfg = copy.deepcopy(cfg0)
        for k, v in over.items():
            _set(cfg, k, v)
        cm = cost_factory(0.0 if special in ("costs0", "both0") else 1.0)
        tp = zero_tax(tax) if special in ("tax0", "both0") else tax
        t1 = time.time()
        try:
            res = engine.run(cfg, period, panel, trend, cm, tp,
                             actions=actions, membership=membership)
            out["rows"][row] = row_metrics(res)
            if row == "base":
                eq = res.equity
                base_flows = [(d, float(f)) for d, f in zip(eq["date"], eq["flow"]) if f]
                base_flows.append((eq["date"].iloc[-1], 0.0))
        except Exception as e:                  # recorded, never dropped
            out["rows"][row] = {"error": f"{type(e).__name__}: {e}"}
        print(f"  [{n}/{len(rows)}] {row} {(time.time()-t1)/60:.1f} min", flush=True)

    for label in ("B2", "B5"):
        key, drag = BENCHMARKS[label]
        for tag, cm, tp, dr in (("", cost_factory(1.0), tax, drag),
                                (" frictionless", cost_factory(0.0), zero_tax(tax), 0.0)):
            res = engine.run_benchmark(cfg0, period, indices[key], cm, tp,
                                       name=key, expense_ratio=dr)
            out["benchmarks"][label + tag] = row_metrics(res)

    req = required(out["benchmarks"])
    # Required terminal wealth: the base row's own contributions compounded
    # at the binding requirement's XIRR, valued on the base row's last day.
    req["required_terminal"] = (terminal_at(req[req["binding"]]["xirr"], base_flows)
                                if base_flows else None)
    out["required"] = req

    text = json.dumps(out, indent=1, default=str)
    if (exp / "results.json").exists():
        if (exp / "results.json").read_text() != text:
            sys.exit(f"CONFLICT: {exp} holds different results for identical inputs")
        print(f"VERIFIED -> {exp}", flush=True)
        return
    exp.mkdir(parents=True, exist_ok=True)
    (exp / "results.json").write_text(text)
    (exp / "manifest.json").write_text(json.dumps(
        {**ident, "run_id": rid, "data_fingerprint": fp, "inputs": inputs,
         "period": a.period, "rows": rows, "controls":
         {r: CONTROLS[r][2] | ({"special": CONTROLS[r][3]} if CONTROLS[r][3] else {})
          for r in rows},
         "diagnostic": "NOT PROMOTABLE", "minutes": round((time.time()-t0)/60, 1)},
        indent=1, default=str))
    (exp / "summary.md").write_text(summarise(out, req, a.period, ident), encoding="utf-8")
    print(f"DONE -> {exp}", flush=True)


if __name__ == "__main__":
    main()
