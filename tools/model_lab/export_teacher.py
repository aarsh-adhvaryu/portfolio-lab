"""Export the teacher log (every cloud call's redacted input/output with its later score) as chat-format JSONL for distillation (S79b item 17).

    python tools/model_lab/export_teacher.py --ledger C:\\somewhere\\ledger_copy.duckdb [--out tools/model_lab/datasets] [--min-score 0.7] [--scored-only]

Reads `teacher_log_s79` from a COPY of the store (the live store of the workshop or an installed app is refused, as in build_dataset.py), read-only. Writes
`teacher.jsonl` (one {"messages": [...], "meta": {...}} per line, split by time is the trainer's job) and `teacher_manifest.json` (counts, SHA-256, score summary).
Text was redacted when it was logged (`pflab.llm.teacher`); No training is run by this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_common as lc  # noqa: E402


def export(ledger: Path, out_dir: Path, *, min_score: Optional[float] = None, scored_only: bool = False) -> dict:
    import duckdb
    from pflab.llm import teacher
    con = duckdb.connect(str(ledger), read_only=True)
    try:
        rows = _rows(con, teacher, min_score, scored_only)
    finally:
        con.close()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "teacher.jsonl"
    kept = dropped = 0
    h = hashlib.sha256()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            if not r["input"] or not r["output"]:
                dropped += 1
                continue
            line = json.dumps(teacher.to_chat(r), ensure_ascii=False, default=str) + "\n"
            f.write(line)
            h.update(line.encode("utf-8"))
            kept += 1
    scores = [r["score"] for r in rows if r.get("score") is not None]
    man = {"examples": kept, "dropped_empty": dropped, "scored": len(scores), "mean_score": (sum(scores) / len(scores)) if scores else None, "sha256": h.hexdigest(),
           "min_score": min_score, "scored_only": scored_only}
    (out_dir / "teacher_manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
    return man


def _rows(con, teacher, min_score, scored_only):
    return teacher.rows(con, scored_only=scored_only, min_score=min_score)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", required=True, type=Path, help="a COPY of the store")
    ap.add_argument("--out", type=Path, default=lc.DATASETS)
    ap.add_argument("--min-score", type=float, default=None)
    ap.add_argument("--scored-only", action="store_true")
    a = ap.parse_args(argv)
    import build_dataset as bd
    try:
        bd.check_is_copy(a.ledger)                # same guard as build_dataset.py: a copy only
    except bd.LedgerRefused as e:
        print(f"export_teacher: refused: {e}", file=sys.stderr)
        return 2
    print(json.dumps(export(a.ledger, a.out, min_score=a.min_score, scored_only=a.scored_only), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
