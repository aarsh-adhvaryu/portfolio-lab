"""S86b C5.2: two real link checks (one true and one false claim) against a public page, through `readers.check_link`, on a scratch store inside the workshop's cap. Public material only.
    python tools/real_links_s86.py --out <folder> --url <public page> --true "<claim>" --false "<claim>" """
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
    ap.add_argument("--url", required=True)
    ap.add_argument("--true", dest="t", required=True)
    ap.add_argument("--false", dest="f", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).resolve().parents[1] / "pm" / "api_budget.toml", out / "api_budget.toml")
    os.environ["PFLAB_PM_DIR"] = str(out)
    from pflab import guard
    guard.set_flags(paid=True)
    from pflab.entrance import readers
    from pflab.pm import store
    con = store.connect(out / "real.duckdb")
    for label, claim in (("TRUE claim", a.t), ("FALSE claim", a.f)):
        r = readers.check_link(con, datetime.now(), a.url, claim, web=False)
        print(label, "->", r.get("verdict"), "| cost_inr", r.get("cost_inr"), "| sources", [(s.get("source"), s.get("kind")) for s in r.get("sources", [])][:3])
        print("   answer:", str(r.get("answer"))[:300].replace(chr(10), " "))
        print("   warnings:", [str(w)[:120] for w in r.get("warnings", [])][:2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
