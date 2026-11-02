"""A fresh start for the system's mind (PLAN S78): clears the chat, the knowledge graph, the investigations, the questions and the paper team's decisions, and restarts the paper clock
today. The account, prices, documents, the learner and the house rules stay. Close the app first (one process holds the store).

  .venv\\Scripts\\python tools\\fresh_start.py            # dry run: counts only
  .venv\\Scripts\\python tools\\fresh_start.py --apply    # copies the store to <pm>\\..\\backups first, then clears
"""
from __future__ import annotations

import shutil
import sys
from datetime import date, datetime
from pathlib import Path


def main() -> int:
    from pflab.pm import fresh_start, store
    pm = store.pm_dir()
    db = pm / "ledger.duckdb"
    con = store.connect(db)
    counts = fresh_start.plan(con)
    for k, v in counts.items():
        print(f"{k}: {v} rows")
    if "--apply" not in sys.argv:
        print("dry run: nothing changed (add --apply)")
        return 0
    con.close()
    backups = pm.parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    copy = backups / f"ledger_before_fresh_start_{datetime.now():%Y%m%d_%H%M%S}.duckdb"
    shutil.copy2(db, copy)
    print(f"store copied to {copy}")
    con = store.connect(db)
    out = fresh_start.apply(con, date.today(), datetime.now())
    con.execute("CHECKPOINT")
    print("cleared; paper clock restarted", out["paper_started"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
