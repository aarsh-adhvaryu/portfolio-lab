"""Byte-identity of E1 base against its stored regression run.

    python tools/e1_identity.py development
    python tools/e1_identity.py validation
    python tools/e1_identity.py development --config configs/e1d.toml         --ref <experiments>/E1d/sweeps/development-924cec1bb3dd9ff9/rows/base

Re-runs E1 base (configs/e1.toml) on the named period with the CURRENT code
and compares it with experiments/E1/regression/<period>-*/rows/base/: the
equity curve, the trade ledger and the decision record, serialised exactly
as `sweep._persist_rows` writes them. Prints IDENTICAL or the first
differences, and exits 0 only when identical.

Why: E3-R (2026-09-27) added a target-equity mechanism and sell-down code to
the engine. Both are reached only when `trend_filter = "gears"`, and
tests/test_engine_golden.py holds E1's synthetic paths byte-for-byte, but
the real-data check is the one that proves no E1 result can have moved.

`--config` and `--ref` (2026-09-30, E3-R §11) point it at another stack's
base row, e.g. E1d's full sweep at c6ef67e, run from a locked worktree. It
prints where `pflab` was imported from, so a run on the live tree shows.

Long job (panel load + one engine run): Aarsh's to run. The two periods can
run side by side.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import pandas as pd


def explain_decisions(got: list, want: list, examples: int = 3) -> list:
    """Where two decision records differ: per field, how many month-ends,
    whether the difference is ORDER only (same content, keys or list items in
    another order) or CONTENT, and the first few examples."""
    lines = []
    if len(got) != len(want):
        lines.append(f"decision count: now {len(got)}, stored {len(want)}")
    canon = lambda x: json.dumps(x, sort_keys=True, default=str)
    per_key: dict = {}
    for a, b in zip(got, want):
        m = a.get("month_end")
        if list(a) != list(b):
            per_key.setdefault("<field order or set>", []).append(
                (m, f"now {list(a)} / stored {list(b)}"))
        for k in sorted(set(a) | set(b)):
            va, vb = a.get(k), b.get(k)
            if json.dumps(va, default=str) == json.dumps(vb, default=str):
                continue
            if canon(va) == canon(vb):
                kind = "order only"
            elif isinstance(va, list) and isinstance(vb, list) and \
                    sorted(map(canon, va)) == sorted(map(canon, vb)):
                kind = "order only (list)"
            else:
                kind = "CONTENT"
            detail = kind
            if kind == "CONTENT" and isinstance(va, dict) and isinstance(vb, dict):
                ch = [x for x in set(va) | set(vb) if va.get(x) != vb.get(x)]
                detail += (f": {len(ch)} entries differ, e.g. "
                           + ", ".join(f"{x}: {vb.get(x)} -> {va.get(x)}" for x in ch[:3]))
            elif kind == "CONTENT":
                detail += f": stored {str(vb)[:120]} -> now {str(va)[:120]}"
            per_key.setdefault(k, []).append((m, detail))
    for k, hits in per_key.items():
        kinds = sorted({h[1].split(":")[0] for h in hits})
        lines.append(f"field {k!r}: {len(hits)} month-ends differ ({', '.join(kinds)})")
        for m, d in hits[:examples]:
            lines.append(f"    {m}: {d}")
    return lines


def main(period_name: str, config: str = "configs/e1.toml",
         ref_dir: str | None = None) -> int:
    import pflab
    from pflab.backtest import engine, runner
    from pflab.data import experiments_dir

    print(f"pflab imported from {Path(pflab.__file__).resolve()}; config {config}")
    cfg = runner.load_config(config)
    period, panel, indices, actions, cost_factory, tax, membership = runner.prepare(
        cfg, period_name)
    res = engine.run(cfg, period, panel, indices.get("NIFTY50_PRICE"),
                     cost_factory(float(cfg.get("costs", {}).get("multiplier", 1.0))),
                     tax, actions=actions, membership=membership)

    ref = [ref_dir] if ref_dir else sorted(glob.glob(str(
        experiments_dir().resolve() / "E1" / "regression"
        / f"{period_name}-*" / "rows" / "base")))
    if len(ref) != 1:
        print(f"expected one stored regression base row for {period_name}, found {ref}")
        return 2
    ref = Path(ref[0])
    problems = []
    for name, got in (("equity", res.equity), ("trades", res.trades)):
        want = pd.read_parquet(ref / f"{name}.parquet")
        try:
            pd.testing.assert_frame_equal(got.reset_index(drop=True),
                                          want.reset_index(drop=True),
                                          check_exact=True, check_dtype=False)
        except AssertionError as e:
            problems.append(f"{name}: {str(e).splitlines()[0:6]}")
    got_d = json.dumps(res.decisions, indent=2, default=str)
    want_d = (ref / "decisions.json").read_text(encoding="utf-8")
    # `reference_close` is built by iterating a set of ISINs, and Python
    # randomises string hashing per process, so its KEY ORDER differs between
    # any two runs of identical code (found 2026-09-27; the same at c33feb3).
    # Content equality ignoring dict key order is therefore the test; a
    # key-order-only difference is reported, never counted as a change.
    canon = lambda s: json.dumps(json.loads(s), sort_keys=True)
    order_only = got_d != want_d and canon(got_d) == canon(want_d)
    if order_only:
        print("  note: decisions.json differs in dict key order only "
              "(reference_close is built from a set; order varies per process)")
    elif got_d != want_d:
        problems.append("decisions.json differs")
        problems.extend(explain_decisions(json.loads(got_d), json.loads(want_d)))
        out = experiments_dir().resolve() / "_identity"
        out.mkdir(parents=True, exist_ok=True)
        stem = period_name if config == "configs/e1.toml" else             f"{Path(config).stem}_{period_name}"
        (out / f"{stem}_decisions_now.json").write_text(got_d, encoding="utf-8")
        problems.append(f"today's decisions saved to {out / (stem + '_decisions_now.json')}")
    if problems:
        print(f"{config} base {period_name}: DIFFERENT from {ref}")
        for p in problems:
            print("  " + p)
        return 1
    print(f"{config} base {period_name}: IDENTICAL to {ref} "
          f"({len(res.equity)} sessions, {len(res.trades)} trades, "
          f"{len(res.decisions)} decisions)")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("period", nargs="?", default="development")
    ap.add_argument("--config", default="configs/e1.toml")
    ap.add_argument("--ref", default=None, help="a stored rows/base directory")
    a = ap.parse_args()
    sys.exit(main(a.period, a.config, a.ref))
