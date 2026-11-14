"""S86b C5: real files through the real reader (`entrance/readers.read_attachment`), on a scratch store, inside the workshop's cap. A file is READ copy-only (the original is never touched).
    python tools/real_inputs_s86.py --out <folder> [--quiet] file1 file2 ...
`--quiet` prints only type, size, kind, facts count, pages, cost and warnings (for files of his: nothing from their content is printed). Without it the first facts are printed (public files)."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).resolve().parents[1] / "pm" / "api_budget.toml", out / "api_budget.toml")
    os.environ["PFLAB_PM_DIR"] = str(out)
    os.environ["PFLAB_DATA_DIR"] = str(out / "data")
    from pflab import guard
    guard.set_flags(paid=True)
    from pflab.entrance import readers
    from pflab.pm import store
    con = store.connect(out / "real.duckdb")
    for f in a.files:
        p = Path(f)
        scratch = out / "copies" / p.name
        scratch.parent.mkdir(exist_ok=True)
        shutil.copy(p, scratch)
        try:
            r = readers.read_attachment(con, datetime.now(), scratch, name=p.name, mime="")
        except Exception as e:
            print(p.suffix, p.stat().st_size, "ERROR", type(e).__name__, str(e)[:200])
            continue
        print(p.suffix, p.stat().st_size, "kind", r.get("kind"), "facts", len(r.get("facts") or []), "pages", r.get("pages"), "cost_inr", r.get("cost_inr"), "refused", bool(r.get("refused")),
              "warnings", [str(w)[:160] for w in (r.get("warnings") or [])][:4])
        if not a.quiet:
            for fct in (r.get("facts") or [])[:3]:
                print("   fact:", str(fct.get("claim"))[:160], "| page", fct.get("page"))
            print("   links:", r.get("links"))
        elif not r.get("facts"):
            print("   reason (the reader's own words):", str(r.get("summary_text"))[:240].replace(chr(10), " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
