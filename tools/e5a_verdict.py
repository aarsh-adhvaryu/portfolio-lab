"""E5-A §10 verdict for a family, both periods, by `classify.classify_e5a`.

    python tools/e5a_verdict.py --family A1 --dev <sweep> --val <sweep> \
        --stack-dev <dir> --stack-val <dir> --a0-dev <sweep> --a0-val <sweep> --out <json>

Prints the incremental and adoption verdicts, G1-G4 per period, and the
mandate block; writes the full result to --out. Nothing is typed by hand.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pflab.eval import classify


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    for k in ("family", "dev", "val", "stack-dev", "stack-val", "a0-dev", "a0-val", "out"):
        ap.add_argument(f"--{k}", required=k != "out")
    a = ap.parse_args(argv)
    r = classify.classify_e5a(a.dev, a.val, a.stack_dev, a.stack_val,
                              a.a0_dev, a.a0_val, candidate=a.family)
    r["inputs"] = {k: getattr(a, k.replace("-", "_")) for k in
                   ("dev", "val", "stack-dev", "stack-val", "a0-dev", "a0-val")}
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
    g = lambda b: {p: {x: b[p].get(x) for x in ("G1", "G2", "G3", "G4")} for p in ("development", "validation")}
    m = r["mandate"]
    print(json.dumps({"family": a.family, "family_evidence": r["family_evidence"],
                      "joins_stack": r["joins_stack"],
                      "incremental": r["incremental"]["verdict"], "inc_gates": g(r["incremental"]),
                      "adoption": r["adoption"]["verdict"], "adopt_gates": g(r["adoption"]),
                      "mandate": m["verdict"]}, indent=1, default=str))
    return r


if __name__ == "__main__":
    main()
