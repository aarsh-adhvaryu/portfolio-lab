"""Delete the knowledge graph (his decision 2026-11-08). Run with the app CLOSED (one process holds the store).

    .venv\\Scripts\\python tools\\kg_delete.py --pm <pm folder>            preview: what would be deleted; changes nothing
    .venv\\Scripts\\python tools\\kg_delete.py --pm <pm folder> --apply    copy the store to <pm>\\..\\backups first, then delete

Deleted: every row of kg_nodes, kg_edges, kg_aliases and kg_hypotheses (news organisations, people, themes, the links of documents to companies, investigation memory),
and the open name questions the graph asked him ('kg-same:'). KEPT: kg_docs (the filing and news texts) and every other table. The graph stays off afterwards
(configs/kg.toml), so nothing refills it. Prints counts only, never contents.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

TABLES = ("kg_edges", "kg_nodes", "kg_aliases", "kg_hypotheses")


def counts(con) -> dict:
    out = {t: int(con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) for t in TABLES + ("kg_docs",)}
    out["nodes_by_kind"] = dict(con.execute("SELECT kind, count(*) FROM kg_nodes GROUP BY 1 ORDER BY 2 DESC").fetchall())
    out["open_name_questions"] = int(con.execute("SELECT count(*) FROM questions WHERE status='open' AND subject_key LIKE 'kg-same:%'").fetchone()[0])
    return out


def delete(con, now: datetime) -> dict:
    from pflab.agents import questions as qs
    from pflab.pm.store import transaction
    with transaction(con):
        for t in TABLES:
            con.execute(f"DELETE FROM {t}")
    dropped = 0
    for (key,) in con.execute("SELECT subject_key FROM questions WHERE status='open' AND subject_key LIKE 'kg-same:%'").fetchall():
        dropped += int(qs.drop(con, key, now))
    con.execute("CHECKPOINT")
    return {"questions_dropped": dropped}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pm", required=True, type=Path)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    ledger = a.pm / "ledger.duckdb"
    if not ledger.exists():
        print(f"no store at {ledger}")
        return 2
    os.environ["PFLAB_PM_DIR"] = str(a.pm)
    backup = None
    if a.apply:                                                # the copy is taken before the store is even opened
        bdir = a.pm.parent / "backups"
        bdir.mkdir(parents=True, exist_ok=True)
        backup = bdir / f"ledger-{datetime.now():%Y%m%d-%H%M%S}-before-kg-delete.duckdb"
        shutil.copy2(ledger, backup)
        if backup.stat().st_size != ledger.stat().st_size:
            print("the backup copy is not the same size as the store: nothing deleted")
            return 1
    from pflab.pm import store
    try:
        con = store.connect(ledger)
    except Exception as e:
        print(f"cannot open the store ({type(e).__name__}): close Portfolio Lab first. Nothing deleted.")
        return 1
    before = counts(con)
    print("before:", before)
    if not a.apply:
        print("(preview: nothing changed; add --apply to delete)")
        return 0
    res = delete(con, datetime.now())
    after = counts(con)
    print("after: ", after)
    print("backup:", backup, "|", res)
    ok = all(after[t] == 0 for t in TABLES) and after["kg_docs"] == before["kg_docs"] and after["open_name_questions"] == 0
    print("DELETED: the graph is empty; documents kept" if ok else "NOT CLEAN: see the counts above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
