"""Gap diagnosis, E1d and E5-A A0 against B5 (audit Deliverable 2).
DIAGNOSTIC, NOT PROMOTABLE: no row here is a charter row, nothing writes
criteria.json, and `classify` cannot read the output. Aarsh runs it.

    python tools/gap_diagnosis.py --strategy E1d --period development
    python tools/gap_diagnosis.py --strategy E1d --period validation
    python tools/gap_diagnosis.py --strategy A0  --period e5a_development
    python tools/gap_diagnosis.py --strategy A0  --period validation

One-change controls from the strategy's base row, on the same panel,
universe and decision dates (each changes ONE thing):

  selection   the names the base run's own ranks choose under the band rule
              (hold the top n_hold, exit past band_exit_rank), equal weight,
              rebalanced at each month-end close, fully invested, no costs,
              no tax, no cash, the base row's SIP dates and amounts. Daily
              total return from the truncated panel (adjusted close plus
              dividends); a name with no price that day is flat. Computed,
              not an engine run.
  trend_off   no trend filter (never RISK_OFF)              -- cash
  cap_off     no six-buy cap (every shortfall filled)        -- cash
  costs_0     every cost zero
  tax_0       every tax zero (pre-tax)

A0 also runs the stack (configs/e1d.toml) on the same panel and reports
`equity_share`: A0's equity-sleeve daily return blended with cash at the
STACK's daily equity weight, against the same blend at A0's own weight. The
difference is what A0's lower equity share costs, on one footing (sleeve
pre-tax; costs stay where the base row paid them).

B5 is run as in every sweep (costs, tax on liquidation, 0.30% drag) and
frictionless (no costs, tax or drag). B5 is a fund taxed only when sold, so
fund-level deferral is already inside the comparison.

Output: experiments/<E1d|E5-A>/diagnostics/gapdiag-<period>-<run_id>/
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

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import gap_attribution as ga  # noqa: E402

BIG = 10 ** 6
CONFIGS = {"E1d": "configs/e1d.toml", "A0": "configs/e5a_a0.toml"}
OUT = {"E1d": "E1d", "A0": "E5-A"}
PERIODS = {"E1d": ("development", "validation", "e5a_development"),
           "A0": ("e5a_development", "validation")}
CONTROLS = {
    "base": ("base", "as chartered", {}, None),
    "trend_off": ("cash", "trend filter off (never RISK_OFF)",
                  {"strategy.trend_filter": "off"}, None),
    "cap_off": ("cash", "six-buy cap removed",
                {"strategy.max_buys_per_month": BIG}, None),
    "costs_0": ("costs", "all costs zero", {}, "costs0"),
    "tax_0": ("tax", "all tax zero (pre-tax)", {}, "tax0"),
}


# -- selection control -------------------------------------------------------
def chosen_names(decisions: list, n_hold: int, band: int) -> dict:
    """month_end -> the names the band rule holds after M's decision, read off
    the base run's own ranks. No cap, no trend filter, no liquidity skip."""
    held: list = []
    out = {}
    for d in decisions:
        ranks = d.get("ranks") or {}
        if ranks:
            keep = [i for i in held if ranks.get(i, np.inf) <= band]
            new = [i for i, _ in sorted(ranks.items(), key=lambda kv: (kv[1], kv[0]))
                   if i not in keep]
            held = keep + new[:max(0, n_hold - len(keep))]
        out[pd.Timestamp(d["month_end"])] = list(held)
    return out


def total_return_wide(panel: pd.DataFrame, isins) -> pd.DataFrame:
    """Daily total-return factor (sessions x ISIN): adjusted close plus the
    day's dividend in adjusted units, over the previous adjusted close."""
    p = panel.loc[panel["isin"].isin(set(isins)),
                  ["date", "isin", "adj_close", "dividend", "adj_factor"]].copy()
    p["date"] = pd.to_datetime(p["date"])
    p = p.sort_values(["isin", "date"])
    div = p["dividend"].fillna(0.0) * p["adj_factor"]
    prev = p.groupby("isin")["adj_close"].shift(1)
    p["f"] = (p["adj_close"] + div) / prev
    return p.pivot_table(index="date", columns="isin", values="f", aggfunc="last")


def selection_metrics(decisions, panel, sessions, flows, n_hold, band) -> dict:
    from pflab.eval import metrics as M
    chosen = chosen_names(decisions, n_hold, band)
    names = sorted(set().union(*map(set, chosen.values()))) if chosen else []
    tr = total_return_wide(panel, names).reindex(sessions).fillna(1.0)
    mes = sorted(chosen)
    w = pd.Series(dtype=float)
    idx, wealth = [], []
    I, W = 1.0, 0.0
    flow = dict(flows)
    k = 0
    for t in sessions:
        if len(w):
            f = tr.loc[t, w.index].to_numpy()
            gross = float((w.to_numpy() * f).sum())
            I *= gross
            W *= gross
            w = w * f / gross
        W += flow.get(t, 0.0)
        while k < len(mes) and mes[k] <= t:          # decision at M's close
            ns = chosen[mes[k]]
            w = pd.Series(1.0 / len(ns), index=ns) if ns else pd.Series(dtype=float)
            k += 1
        idx.append(I)
        wealth.append(W)
    nav = pd.Series(idx, index=sessions)
    start = mes[0] if mes else sessions[0]
    nav = nav[nav.index >= start]
    dates = [d for d, _ in flows] + [sessions[-1]]
    amounts = [-a for _, a in flows] + [wealth[-1]]
    return {"cagr": M.cagr(nav), "max_drawdown": M.max_drawdown(nav),
            "terminal": float(wealth[-1]), "contributed": float(sum(a for _, a in flows)),
            "xirr": M.xirr(dates, amounts), "mean_equity_weight": 1.0,
            "names_per_month": float(np.mean([len(v) for v in chosen.values()])) if chosen else 0.0}


# -- A0's equity share -------------------------------------------------------
def sleeve_returns(res) -> tuple:
    """(daily equity-sleeve return, daily equity weight) from a run: the
    sleeve's value net of the day's buys and sells, plus its dividends."""
    eq = res.equity.copy()
    eq["date"] = pd.to_datetime(eq["date"])
    tr = res.trades.copy()
    if len(tr):
        tr["date"] = pd.to_datetime(tr["date"])
        tr["v"] = tr["qty"] * tr["fill_price"] * np.where(tr["side"] == "BUY", 1.0, -1.0)
        net = tr.groupby("date")["v"].sum()
    else:
        net = pd.Series(dtype=float)
    e = eq.set_index("date")
    net = net.reindex(e.index).fillna(0.0)
    prev = e["equity_value"].shift(1)
    r = (e["equity_value"] - net + e["dividends"].fillna(0.0)) / prev - 1.0
    r = r.where(prev > 0, 0.0).fillna(0.0)
    tot = e["equity_value"] + e["cash"]
    wt = (e["equity_value"] / tot.where(tot > 0)).fillna(0.0)
    return r, wt, e["flow"]


def blend(r_eq: pd.Series, weight: pd.Series, flow: pd.Series, cash_rate: float) -> dict:
    from pflab.eval import metrics as M
    days = pd.Series(r_eq.index, index=r_eq.index).diff().dt.days.fillna(0)
    rc = (1 + cash_rate) ** (days / 365.0) - 1
    w = weight.reindex(r_eq.index).ffill().fillna(0.0).shift(1).fillna(0.0)
    r = w * r_eq + (1 - w) * rc
    I, W, idx, wealth = 1.0, 0.0, [], []
    for t in r.index:
        I *= 1 + r[t]
        W = W * (1 + r[t]) + float(flow.get(t, 0.0))
        idx.append(I)
        wealth.append(W)
    nav = pd.Series(idx, index=r.index)
    fl = flow[flow != 0]
    dates = list(fl.index) + [r.index[-1]]
    amounts = [-float(a) for a in fl] + [wealth[-1]]
    return {"cagr": M.cagr(nav), "max_drawdown": M.max_drawdown(nav),
            "terminal": float(wealth[-1]), "xirr": M.xirr(dates, amounts),
            "mean_equity_weight": float(weight.mean())}


# -- report ----------------------------------------------------------------
def explained(row: dict, base: dict, b5: dict) -> dict:
    """Share of the base row's gap to B5 that the control closes, per measure."""
    out = {}
    for k in ("cagr", "xirr", "terminal"):
        gap = b5[k] - base[k]
        out[k] = None if not gap else (row[k] - base[k]) / gap
    return out


def summarise(res: dict, strategy: str, period: str, ident: dict) -> str:
    base, b5 = res["rows"]["base"], res["benchmarks"]["B5"]
    b5f = res["benchmarks"]["B5 frictionless"]
    pct = lambda x: "—" if x is None else f"{100 * x:+.0f}%"
    lines = [f"# Gap diagnosis — {strategy}, {period} (DIAGNOSTIC, NOT PROMOTABLE)", "",
             f"Commit `{ident['commit'][:12]}`. One change per row from {strategy} base. "
             "\"Explains\" = (row − base) ÷ (B5 − base): the share of the gap to B5 "
             "(as in every sweep) that the change closes. A selection row is compared "
             "with B5 frictionless as well.", "",
             f"Gap to B5: CAGR {100 * (base['cagr'] - b5['cagr']):+.2f} pp, XIRR "
             f"{100 * (base['xirr'] - b5['xirr']):+.2f} pp, terminal "
             f"₹{(base['terminal'] - b5['terminal']) / 1e5:+.1f} L.", "",
             "| row | group | terminal ₹cr | XIRR | CAGR | MaxDD | eq. wt | explains CAGR | XIRR | terminal |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, m in res["rows"].items():
        if m.get("error"):
            lines.append(f"| {name} | | error: {m['error']} |")
            continue
        e = explained(m, base, b5)
        grp = CONTROLS.get(name, ("selection" if name == "selection" else "equity share",))[0]
        lines.append(f"| {name} | {grp} | {m['terminal'] / 1e7:.3f} | {100 * m['xirr']:.2f}% | "
                     f"{100 * m['cagr']:.2f}% | {100 * m['max_drawdown']:.2f}% | "
                     f"{100 * m.get('mean_equity_weight', float('nan')):.1f}% | "
                     f"{pct(e['cagr'])} | {pct(e['xirr'])} | {pct(e['terminal'])} |")
    lines += ["", "| benchmark | terminal ₹cr | XIRR | CAGR | MaxDD |", "|---|---:|---:|---:|---:|"]
    for k, m in res["benchmarks"].items():
        lines.append(f"| {k} | {m['terminal'] / 1e7:.3f} | {100 * m['xirr']:.2f}% | "
                     f"{100 * m['cagr']:.2f}% | {100 * m['max_drawdown']:.2f}% |")
    s = res["rows"].get("selection")
    if s and not s.get("error"):
        lines += ["", f"Selection vs B5 frictionless: CAGR {100 * (s['cagr'] - b5f['cagr']):+.2f} pp, "
                      f"XIRR {100 * (s['xirr'] - b5f['xirr']):+.2f} pp."]
    es = res.get("equity_share")
    if es:
        lines += ["", "**Equity share (A0's sleeve, cash at the cash rate):** at A0's own weight "
                      f"({100 * es['own']['mean_equity_weight']:.1f}%) CAGR {100 * es['own']['cagr']:.2f}%, "
                      f"terminal ₹{es['own']['terminal'] / 1e7:.3f} cr; at the stack's weight "
                      f"({100 * es['stack']['mean_equity_weight']:.1f}%) CAGR {100 * es['stack']['cagr']:.2f}%, "
                      f"terminal ₹{es['stack']['terminal'] / 1e7:.3f} cr. Difference: "
                      f"{100 * (es['stack']['cagr'] - es['own']['cagr']):+.2f} pp CAGR, "
                      f"{100 * (es['stack']['xirr'] - es['own']['xirr']):+.2f} pp XIRR."]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True, choices=sorted(CONFIGS))
    ap.add_argument("--period", required=True)
    ap.add_argument("--rows", nargs="*", help="subset of engine controls (smoke)")
    a = ap.parse_args()
    if a.period not in PERIODS[a.strategy]:
        sys.exit(f"{a.strategy}: period must be one of {PERIODS[a.strategy]}")
    rows = ["base"] + [r for r in (a.rows or CONTROLS) if r != "base"]

    ident = ga._guard()
    os.chdir(REPO)
    from pflab.backtest import engine, runner
    from pflab.data import experiments_dir
    from pflab.eval import artifacts
    from pflab.eval.sweep import BENCHMARKS

    cfg0 = runner.load_config(REPO / CONFIGS[a.strategy])
    t0 = time.time()
    period, panel, indices, actions, cost_factory, tax, membership = runner.prepare(cfg0, a.period)
    if period.sealed:
        sys.exit("refusing: the sealed period")
    trend = indices.get("NIFTY50_PRICE")
    provider, _ = runner.e5a_scores(cfg0, period, panel)
    inputs = runner.input_fingerprints(cfg0, period, indices, actions, membership, None)
    fp = artifacts.data_fingerprint(panel, extra={"inputs": inputs})
    spec = json.dumps({"strategy": a.strategy, "rows": {r: CONTROLS[r][2:] for r in rows},
                       "selection": True}, sort_keys=True, default=str)
    rid = artifacts.run_id(spec, fp, ident["commit"], period.name)
    out_dir = (experiments_dir().resolve() / OUT[a.strategy] / "diagnostics"
               / f"gapdiag-{a.period}-{rid}")
    print(f"loaded {a.period} in {(time.time() - t0) / 60:.1f} min", flush=True)

    out = {"rows": {}, "benchmarks": {}}
    base_res = None
    for n, row in enumerate(rows, 1):
        _, _, over, special = CONTROLS[row]
        cfg = copy.deepcopy(cfg0)
        for k, v in over.items():
            ga._set(cfg, k, v)
        cm = cost_factory(0.0 if special == "costs0" else
                          float(cfg.get("costs", {}).get("multiplier", 1.0)))
        tp = ga.zero_tax(tax) if special == "tax0" else tax
        t1 = time.time()
        try:
            kw = {"scores": provider(cfg, "base")} if provider else {}
            res = engine.run(cfg, period, panel, trend, cm, tp, actions=actions,
                             membership=membership, **kw)
            out["rows"][row] = ga.row_metrics(res)
            if row == "base":
                base_res = res
        except Exception as e:                       # recorded, never dropped
            out["rows"][row] = {"error": f"{type(e).__name__}: {e}"}
        print(f"  [{n}/{len(rows)}] {row} {(time.time() - t1) / 60:.1f} min", flush=True)

    if base_res is not None:
        eq = base_res.equity
        sessions = list(pd.to_datetime(eq["date"]))
        flows = [(pd.Timestamp(d), float(f)) for d, f in zip(eq["date"], eq["flow"]) if f]
        st = cfg0["strategy"]
        try:
            out["rows"]["selection"] = selection_metrics(
                base_res.decisions, panel, sessions, flows,
                int(st["n_hold"]), int(st["band_exit_rank"]))
        except Exception as e:
            out["rows"]["selection"] = {"error": f"{type(e).__name__}: {e}"}
        print("  selection computed", flush=True)

        if a.strategy == "A0":
            scfg = runner.load_config(REPO / CONFIGS["E1d"])
            sres = engine.run(scfg, period, panel, trend,
                              cost_factory(float(scfg.get("costs", {}).get("multiplier", 1.0))),
                              tax, actions=actions, membership=membership)
            out["stack"] = ga.row_metrics(sres)
            r_eq, w_own, flow = sleeve_returns(base_res)
            _, w_stack, _ = sleeve_returns(sres)
            rate = float(st.get("cash_rate_annual", 0.06))
            out["equity_share"] = {"own": blend(r_eq, w_own, flow, rate),
                                   "stack": blend(r_eq, w_stack, flow, rate)}
            print("  stack and equity share computed", flush=True)

    for label in ("B5",):
        key, drag = BENCHMARKS[label]
        for tag, cm, tp, dr in (("", cost_factory(1.0), tax, drag),
                                (" frictionless", cost_factory(0.0), ga.zero_tax(tax), 0.0)):
            res = engine.run_benchmark(cfg0, period, indices[key], cm, tp, name=key,
                                       expense_ratio=dr)
            out["benchmarks"][label + tag] = ga.row_metrics(res)

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
         "strategy": a.strategy, "config": CONFIGS[a.strategy], "period": a.period,
         "rows": rows, "diagnostic": "NOT PROMOTABLE",
         "minutes": round((time.time() - t0) / 60, 1)}, indent=1, default=str))
    (out_dir / "summary.md").write_text(summarise(out, a.strategy, a.period, ident),
                                        encoding="utf-8")
    print(f"DONE -> {out_dir}", flush=True)


if __name__ == "__main__":
    main()
