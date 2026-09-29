"""E5-A §5 tuning: the 8-point grid, once, before A0 locks.

    python tools\\tune_e5a.py --config configs\\e5a_a0.toml

On the store built from the panel truncated at 2010-12-31 (period
`e5a_exploratory`, via `truncate_end`), walk-forward predictions for the
2008-2010 month-ends -- annual refits at December 2007, 2008 and 2009, each
trained only on labels observable by its refit date -- are scored by mean
monthly Spearman rank IC against their own labels, averaged across the three
horizons, using only labels observable by 2010-12-31 (a cross-section counts
only when every label in it is). Highest IC wins; within 0.005, fewer leaves,
then larger `min_data_in_leaf`.

Writes experiments/E5-A/tuning/<period>-<id>/tuning.json and tuning.md. The
chosen point is then written into E5-A §5 and configs/e5a_a0.toml by hand.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import itertools
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pflab.backtest import runner  # noqa: E402
from pflab.eval import artifacts, periods  # noqa: E402
from pflab.ranker import model as mdl, store, walk  # noqa: E402
from pflab.ranker.features import to_wide  # noqa: E402

CUT = date(2010, 12, 31)
SCORED = (date(2008, 1, 1), date(2010, 12, 31))
GRID = {"num_leaves": (7, 31), "min_data_in_leaf": (200, 1000),
        "learning_rate": (0.02, 0.05)}
TIE = 0.005


def grid_points():
    keys = list(GRID)
    return [dict(zip(keys, v)) for v in itertools.product(*(GRID[k] for k in keys))]


def choose(results: list) -> dict:
    """§5's rule: highest IC; within TIE of it, fewer leaves, then larger
    min_data_in_leaf (then the higher IC)."""
    best = max(r["ic"] for r in results)
    near = [r for r in results if r["ic"] >= best - TIE]
    return sorted(near, key=lambda r: (r["point"]["num_leaves"],
                                       -r["point"]["min_data_in_leaf"],
                                       -r["ic"]))[0]


def evaluate(w: walk.Walk, spec: walk.Spec, months, labels) -> dict:
    res = w.score(spec, months)
    L = labels[labels["xs_complete"].astype(bool) & labels["target"].notna()]
    L = L.set_index(["month_end", "h", "isin"])["target"]
    per_h = {}
    for h in spec.horizons:
        ics, by_year = [], {}
        for m in months:
            p = res["predictions"].get((m, h))
            if p is None:
                continue
            try:
                y = L.loc[(m, h)]
            except KeyError:
                continue                         # not observable by the cut
            ic = mdl.spearman(p, y.reindex(p.index))
            if ic is None:
                continue
            ics.append(ic)
            by_year.setdefault(str(m.year), []).append(ic)
        if not ics:
            raise RuntimeError(f"horizon {h}: no month with an observable label")
        per_h[f"h{h}"] = {"mean_ic": float(np.mean(ics)), "months": len(ics),
                          "by_year": {y: round(float(np.mean(v)), 5)
                                      for y, v in sorted(by_year.items())}}
    fits = sorted({(f[0], str(i["refit"]), f[1], f[2], f[3])
                   for i in res["info"].values() for f in i["fits"]})
    return {"ic": float(np.mean([v["mean_ic"] for v in per_h.values()])),
            "horizons": per_h,
            "fallback_months": [str(m) for m, fb in res["fallback"].items() if fb],
            "fits": [{"h": h, "refit": r, "sha256": s, "rows": n, "cross_sections": x}
                     for h, r, s, n, x in fits]}


def tune(config_path: str, period_name: str = "e5a_exploratory") -> Path:
    t0 = time.time()
    cfg = runner.load_config(config_path)
    root = runner._repo_root()
    period = periods.load_periods(root / cfg["evaluation"]["periods_path"])[period_name]
    if period.end != CUT:
        raise SystemExit(f"E5-A §5 tunes on data cut at {CUT}; {period_name} "
                         f"ends {period.end}")
    d = store.store_dir(period_name)
    feats, labels, meta = store.load(d)
    if meta.get("period_end") != str(CUT):
        raise SystemExit(f"store {d} is cut at {meta.get('period_end')}, not {CUT}")
    last = max(x for x in labels["label_end"] if x is not None)
    if max(feats["month_end"]) > CUT or last > CUT:
        raise SystemExit("store carries a row after the cut")
    if json.loads(json.dumps(meta.get("identity"), default=str)) != \
            json.loads(json.dumps(store.identity(cfg), default=str)):
        raise SystemExit("store was built for a different universe or feature list")
    if meta.get("builder_sha") != store.builder_sha():
        raise SystemExit("store was built by different feature/label code; rebuild it")

    fw = to_wide(feats)
    universe = {m: sorted(g["isin"].unique()) for m, g in feats.groupby("month_end")}
    mes = sorted(universe)
    months = [m for m in mes if SCORED[0] <= m <= SCORED[1]]
    w = walk.Walk(fw, labels, universe, mes)
    probe = {**cfg, "e5a": {**cfg["e5a"], "params": grid_points()[0]}}
    base = walk.spec_from_config(probe)

    results = []
    for pt in grid_points():
        spec = dataclasses.replace(base, tuned=tuple(sorted(pt.items())))
        r = evaluate(w, spec, months, labels)
        results.append({"point": pt, **r})
        print(f"  {pt} -> IC {r['ic']:.5f} "
              + " ".join(f"{h}={v['mean_ic']:.4f}/{v['months']}"
                         for h, v in r["horizons"].items()),
              file=sys.stderr, flush=True)
    chosen = choose(results)

    ident = {"store_files": meta["files"], "lightgbm": mdl.lightgbm_version(),
             "code": artifacts.code_identity(artifacts.code_commit()),
             "e5a": {k: v for k, v in cfg["e5a"].items() if k != "params"},
             "grid": GRID, "scored": [str(x) for x in SCORED]}
    tid = hashlib.sha256(json.dumps(ident, sort_keys=True, default=str)
                         .encode()).hexdigest()[:16]
    from pflab.data import experiments_dir
    out = experiments_dir().resolve() / "E5-A" / "tuning" / f"{period_name}-{tid}"
    doc = {"identity": ident, "tuning_id": tid, "period": period_name,
           "cut": str(CUT), "months_scored": [str(m) for m in months],
           "rule": ("highest mean IC (mean of the three horizons' mean monthly "
                    "Spearman IC); within 0.005, fewer leaves, then larger "
                    "min_data_in_leaf"),
           "chosen": chosen["point"], "chosen_ic": chosen["ic"],
           "best_ic": max(r["ic"] for r in results),
           "results": results, "seconds": round(time.time() - t0, 1)}
    body = json.dumps({k: v for k, v in doc.items() if k != "seconds"},
                      indent=2, sort_keys=True, default=str)
    if (out / "tuning.json").exists():
        prior = json.loads((out / "tuning.json").read_text(encoding="utf-8"))
        prior.pop("seconds", None)
        if json.dumps(prior, indent=2, sort_keys=True, default=str) != body:
            raise SystemExit(f"{out} holds a different tuning result for the same "
                             f"inputs; nothing overwritten")
        print(f"verified: {out}", file=sys.stderr)
        return out
    out.mkdir(parents=True, exist_ok=True)
    (out / "tuning.json").write_text(json.dumps(doc, indent=2, sort_keys=True,
                                                default=str), encoding="utf-8")
    lines = [f"# E5-A §5 tuning — {period_name} (cut {CUT})", "",
             f"Scored month-ends {months[0]} .. {months[-1]} ({len(months)}); "
             f"annual refits; LightGBM {ident['lightgbm']}.", "",
             "| num_leaves | min_data_in_leaf | learning_rate | IC (mean of 3) | "
             "h1 | h3 | h12 |", "|---|---|---|---|---|---|---|"]
    for r in results:
        p, hz = r["point"], r["horizons"]
        mark = " **chosen**" if p == chosen["point"] else ""
        lines.append(f"| {p['num_leaves']} | {p['min_data_in_leaf']} | "
                     f"{p['learning_rate']} | {r['ic']:.5f}{mark} | "
                     + " | ".join(f"{hz[h]['mean_ic']:.4f} ({hz[h]['months']})"
                                  for h in ("h1", "h3", "h12")) + " |")
    lines += ["", f"Chosen: {chosen['point']} (IC {chosen['ic']:.5f}; best "
              f"{doc['best_ic']:.5f}; tie band {TIE})."]
    (out / "tuning.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default="configs/e5a_a0.toml")
    ap.add_argument("--period", default="e5a_exploratory")
    a = ap.parse_args(argv)
    out = tune(a.config, a.period)
    print(out)
    print((out / "tuning.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
