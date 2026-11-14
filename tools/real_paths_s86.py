"""S86: the real model paths S85 could not run, once each, inside the workshop's cap (his word of 2026-11-14): a real Haiku reply, a real Opus reply (through the gateway), one public PDF read by the real
model (`entrance/readers.read_attachment`) and one real link check (`readers.check_link`). Public material only; a scratch store; nothing of the investor's.
    python tools/real_paths_s86.py --out <folder> --pdf <a public pdf> --url <a public page>"""
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
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--url", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).resolve().parents[1] / "pm" / "api_budget.toml", out / "api_budget.toml")
    os.environ["PFLAB_PM_DIR"] = str(out)
    from pflab import guard
    guard.set_flags(paid=True)
    from pflab.llm import gateway
    from pflab.pm import store
    con = store.connect(out / "real.duckdb")
    now = datetime.now()
    res = {}
    for role in ("quick", "decide"):
        try:
            r = gateway.call(con, role, "You answer in one short sentence.", [{"role": "user", "content": "In one sentence: what does a stop-loss order do?"}], purpose="s86_real_path", now=now, max_tokens=120)
            res[role] = {"model": r.get("model"), "cost_rupees": r.get("cost_rupees"), "text": (r.get("text") or "")[:160]}
        except Exception as e:
            res[role] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    from pflab.entrance import readers
    try:
        d = readers.read_attachment(con, now, Path(a.pdf), name=Path(a.pdf).name, mime="application/pdf")
        res["pdf"] = {k: (str(v)[:200]) for k, v in d.items() if k in ("kind", "name", "summary", "facts", "cost", "cost_rupees", "pages", "ok", "refused", "ignored")}
    except Exception as e:
        res["pdf"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    try:
        d = readers.check_link(con, now, a.url)
        res["link"] = {k: (str(v)[:200]) for k, v in d.items() if k in ("ok", "summary", "verdict", "source_type", "cost", "cost_rupees", "citations", "error")}
    except Exception as e:
        res["link"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    for k, v in res.items():
        print(k, v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
