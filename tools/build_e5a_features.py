"""Build E5-A's feature store and labels for one period (E5-A §4, §6).

    python tools\\build_e5a_features.py --config configs\\e5a_a0.toml --period e5a_exploratory

Reads the panel through `runner.prepare` -- `truncate_end` at the period's
end, then the D1/D2 repairs, exactly as a sweep does -- and writes
PFLAB_DATA_DIR/e5a/<period>/{features_a0.parquet, labels.parquet, meta.json}.
A data build, not a sweep. The sweep refuses a store whose panel fingerprint,
universe or stack score differ from its own.

Rebuilding over an existing store prints whether the new files are identical.

    python tools\build_e5a_features.py --period validation --verify <scratch dir>

`--verify` (2026-10-01) rebuilds into <scratch dir> and compares every file
with the live store. Only if all are byte-identical does it record this
code's builder SHA in the live store's meta (`builder_sha_verified`); the
files and the original stamp are left alone, so the store stays valid for
the tag that built it. Different files: refuses, writes nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pflab.backtest import runner  # noqa: E402
from pflab.eval import artifacts  # noqa: E402
from pflab.ranker import features as ft, labels as lb, store  # noqa: E402

CONVENTIONS = [
    "momentum counts market sessions, 21 to a month, as the stack's 12-1 does",
    "volatility, traded value and the 252-session high count the name's own "
    "rows (E1 §2's convention); a window must be full to give a value",
    "U(M) is the stack's eligible set restricted to names with a panel row at M",
    "labels follow E1 §9 as amended by E1 §15 (2026-09-17, 2026-09-27 b): "
    "exit at the first open after M_h the name trades; written down to zero on "
    "the 250th consecutive missing session",
    "a name with a row at M that never opens again: -100% at its 250th missing session",
    "targets are computed per fit over the labels observable at R (labels.targets_at)",
]


def _say(msg):
    print(msg, file=sys.stderr, flush=True)


def build(config_path: str, period_name: str, root=None) -> dict:
    t0 = time.time()
    cfg = runner.load_config(config_path)
    period, panel, _i, _a, _c, _t, membership = runner.prepare(cfg, period_name)
    _say(f"prepared {len(panel):,} rows to {panel['date'].max()} "
         f"({time.time() - t0:.0f}s)")
    panel = ft.dated(panel)
    uni = ft.universe_by_month(panel, cfg, membership)
    _say(f"U(M) at {len(uni)} month-ends ({time.time() - t0:.0f}s)")
    feats = ft.a0_features(panel, cfg, uni)
    _say(f"features: {len(feats):,} rows ({time.time() - t0:.0f}s)")
    horizons = tuple((cfg.get("e5a") or {}).get("horizons", lb.HORIZONS))
    labels = lb.build_labels(panel, cfg, uni, horizons)
    _say(f"labels: {len(labels):,} rows ({time.time() - t0:.0f}s)")
    fp = artifacts.data_fingerprint(panel)
    meta = {"period": period.name, "period_start": str(period.start),
            "period_end": str(period.end), "config": config_path,
            "panel_fingerprint": fp, "identity": store.identity(cfg),
            "builder_sha": store.builder_sha(),
            "code": artifacts.code_commit(),
            "built_at": datetime.now(timezone.utc).isoformat(),
            "month_ends": {"first": str(min(uni)), "last": str(max(uni)),
                           "n": len(uni)},
            "availability": ft.availability(feats),
            "labels": lb.summary(labels), "conventions": CONVENTIONS}
    d = store.store_dir(period.name, root)
    before = store.file_shas(d)
    shas = store.write(d, feats, labels, meta)
    meta["files"] = shas
    meta["seconds"] = round(time.time() - t0, 1)
    same = before == shas if before else None
    _say(f"wrote {d} ({meta['seconds']}s)"
         + ("" if same is None else f"; identical to the previous build: {same}"))
    return meta


def verify(config_path: str, period_name: str, scratch: str) -> int:
    live = store.store_dir(period_name)
    meta_path = live / store.META
    old = json.loads(meta_path.read_text(encoding="utf-8"))
    new = build(config_path, period_name, root=scratch)
    if new["files"] != old["files"] or new["panel_fingerprint"] != old["panel_fingerprint"]:
        _say(f"REFUSED: the rebuild differs from {live}; nothing written")
        return 1
    sha = store.builder_sha()
    if sha in store.verified_shas(old):
        _say(f"{live}: builder {sha[:12]} already valid")
        return 0
    old.setdefault("builder_sha_verified", []).append(
        {"builder_sha": sha, "code": artifacts.code_commit(),
         "verified_at": datetime.now(timezone.utc).isoformat(),
         "files": new["files"]})
    meta_path.write_text(json.dumps(old, indent=2, default=str), encoding="utf-8")
    _say(f"VERIFIED: {live} rebuilt byte-identical by builder {sha[:12]}; recorded")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default="configs/e5a_a0.toml")
    ap.add_argument("--period", required=True)
    ap.add_argument("--verify", metavar="SCRATCH_DIR")
    a = ap.parse_args(argv)
    if a.verify:
        return verify(a.config, a.period, a.verify)
    meta = build(a.config, a.period)
    print(json.dumps({k: meta[k] for k in ("period", "month_ends", "availability",
                                           "labels", "files", "seconds")},
                     indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
