"""Build the graph from the raw files, audit it, and print COUNTS only (S81 B7). Never touches the live store: a throw-away in-memory store holds the audit row.

    $env:PYTHONPATH = "<worktree>\\src"
    D:\\portfolio_lab\\.venv\\Scripts\\python.exe tools\\kg2_run.py --root D:\\PortfolioLabApp\\data [--day 2026-11-09] [--classify 40]

Writes `<root>/kg/graph/*.parquet` (the deterministic tables), `<root>/kg/audit_sample.csv` and `<root>/kg/audit_last.json` (the checks). With --store PATH the verdict
and, when the audit passes and the switch is on, the tables go to that store copy (never the live one).
"""
import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import duckdb  # noqa: E402

from pflab.kg2 import audit, build as kb, job  # noqa: E402
from pflab.pm import store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("PFLAB_DATA_DIR", r"D:\PortfolioLabApp\data"))
    ap.add_argument("--day", default=date.today().isoformat())
    ap.add_argument("--classify", type=int, default=0, help="ask the local model about at most N events the rules left open")
    ap.add_argument("--store", default=None, help="a COPY of the store to write the verdict and tables to (default: a throw-away in-memory one)")
    a = ap.parse_args()
    root, day = Path(a.root), date.fromisoformat(a.day)
    con = duckdb.connect(a.store) if a.store else duckdb.connect(":memory:")
    store.migrate(con)
    t0 = time.time()
    out = job.run(con, root, day, classify_limit=a.classify)
    res = json.loads(con.execute("SELECT checks_json FROM kg2_audit WHERE day=?", [day]).fetchone()[0])
    (root / "kg" / "audit_last.json").write_text(json.dumps({"day": day.isoformat(), "passed": out["passed"], "checks": res}, indent=1, default=str), encoding="utf-8")
    print(f"built and audited in {time.time() - t0:.0f}s; passed={out['passed']}; failed={out['failed_checks']}; loaded={out['loaded']}")
    print("counts:", json.dumps(out["counts"], sort_keys=True))
    print("classify:", out["classify"])
    for c in res:
        v = c["value"]
        print(f"  {'PASS' if c['passed'] else 'FAIL'}{'' if c['gating'] else ' (info)'} {c['name']}: {v if not isinstance(v, dict) else json.dumps(v)} (threshold {c['threshold']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
