"""Build a chat-format JSONL training set from a COPY of the app's ledger (A41, S79).

    python tools/model_lab/build_dataset.py --ledger C:\\somewhere\\ledger_copy.duckdb [--out tools/model_lab/datasets]

What goes in: the system's own guarded writing, read from the copy, read-only:
  * `briefs` rows that PASSED the numeric/citation guard (`verified = true`). A row the guard rejected is dropped, always.
  * the user turn is the row's `prompt` column when the table has one (a future journal that keeps the prompt with its facts);
    otherwise a plain request built from symbol and date, which teaches style only (see README: a real run needs the facts stored).
What never goes in: anything the guard rejected, anything `pflab.scrub` or `hq/redact.py` would change (the whole example is dropped,
not edited: privacy first), duplicates, very short or very long text, the investor's identity or banking details (none is read).
Split: by time, never random: the latest `--valid-fraction` of examples (by as_of) is the validation set, so validation is never earlier
than training (point-in-time). Writes train.jsonl, valid.jsonl and manifest.json (counts, drops by reason, SHA-256 of both files).
The ledger path must be a copy: the live store of the workshop or of an installed app is refused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_common as lab  # noqa: E402

SYSTEM = ("You write short research briefs for an investor. Every number must come from the facts or sources you are given and carry "
          "its citation tag, [S1] for a source or [F:name] for a fact. Never compute a number yourself.")
MIN_CHARS, MAX_CHARS = 40, 6000


class LedgerRefused(RuntimeError):
    pass


def check_is_copy(path: Path) -> None:
    """Refuse the live store (workshop or app): the lab reads a copy only."""
    p = path.resolve()
    if not p.exists():
        raise LedgerRefused(f"{path} does not exist")
    if "PortfolioLabApp" in p.parts:
        raise LedgerRefused(f"{path} is inside the installed app's folder; copy the ledger elsewhere first")
    try:
        from pflab.pm import store
        live = store.db_path().resolve()
        if live.exists() and p == live:
            raise LedgerRefused(f"{path} is the live store; copy it (the app or bot holds it) and pass the copy")
    except ImportError:                                     # pragma: no cover
        pass


def _columns(con, table: str) -> List[str]:
    return [r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name=?", [table]).fetchall()]


def read_briefs(con) -> Tuple[List[dict], Counter]:
    """Rows of `briefs` with the guard's verdict. Returns (kept rows, drop counts)."""
    cols = _columns(con, "briefs")
    if not cols:
        raise LedgerRefused("the ledger copy has no `briefs` table (nothing guarded to learn from yet)")
    prompt = "prompt" if "prompt" in cols else "NULL"
    rows = con.execute(f"SELECT brief_id, isin, symbol, as_of, verified, text, {prompt} FROM briefs ORDER BY as_of, brief_id").fetchall()
    drops: Counter = Counter()
    out = []
    for bid, isin, sym, as_of, verified, text, prm in rows:
        if not verified:
            drops["guard_rejected"] += 1
            continue
        out.append({"id": int(bid), "isin": isin, "symbol": sym, "as_of": as_of, "text": text or "", "prompt": prm})
    return out, drops


def guard_runs_summary(con) -> Dict[str, int]:
    """For the manifest: how the guard judged the logged model calls (llm_runs.guard_result), for the reader's information."""
    if not _columns(con, "llm_runs"):
        return {}
    return {str(k or "none"): int(n) for k, n in con.execute("SELECT guard_result, count(*) FROM llm_runs GROUP BY 1").fetchall()}


def privacy_clean(text: str) -> bool:
    """True when neither the credential scrubber nor the redactor would change the text."""
    from pflab import scrub
    from pflab.hq import egress, redact
    if scrub.scrub(text) != text:
        return False
    out, counts = redact.redact(text, egress.Gate(), lines=False)
    return out == text and not counts


def to_example(r: dict) -> dict:
    user = r["prompt"] or f"Write the research brief for {r['symbol'] or r['isin']} as of {r['as_of']}."
    return {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user},
                         {"role": "assistant", "content": r["text"].strip()}],
            "meta": {"source": "briefs", "id": r["id"], "isin": r["isin"], "as_of": str(r["as_of"]),
                     "has_prompt": bool(r["prompt"])}}


def build(ledger: Path, out_dir: Path, valid_fraction: float = 0.15) -> dict:
    import duckdb
    check_is_copy(ledger)
    con = duckdb.connect(str(ledger), read_only=True)
    try:
        rows, drops = read_briefs(con)
        runs = guard_runs_summary(con)
    finally:
        con.close()
    seen, kept = set(), []
    for r in rows:
        t = r["text"].strip()
        if not (MIN_CHARS <= len(t) <= MAX_CHARS):
            drops["length"] += 1
        elif hashlib.sha256(t.encode("utf-8")).hexdigest() in seen:
            drops["duplicate"] += 1
        elif not privacy_clean(t + "\n" + (r["prompt"] or "")):
            drops["privacy"] += 1
        else:
            seen.add(hashlib.sha256(t.encode("utf-8")).hexdigest())
            kept.append(r)
    kept.sort(key=lambda r: (str(r["as_of"]), r["id"]))
    n_valid = int(round(len(kept) * valid_fraction)) if len(kept) >= 10 else 0
    train, valid = kept[:len(kept) - n_valid], kept[len(kept) - n_valid:]
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"built_at": datetime.now().isoformat(timespec="seconds"), "ledger_copy": ledger.name, "source": "briefs (verified)",
                "rows_read": len(rows) + drops["guard_rejected"], "kept": len(kept), "train": len(train), "valid": len(valid),
                "dropped": dict(drops), "llm_runs_by_guard_result": runs,
                "split": "by time: the latest examples are validation",
                "train_last_as_of": str(train[-1]["as_of"]) if train else None,
                "valid_first_as_of": str(valid[0]["as_of"]) if valid else None}
    for name, part in (("train", train), ("valid", valid)):
        p = out_dir / f"{name}.jsonl"
        p.write_text("".join(json.dumps(to_example(r), ensure_ascii=False) + "\n" for r in part), encoding="utf-8")
        manifest[f"{name}_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", required=True, type=Path, help="path to a COPY of the ledger (ledger.duckdb)")
    ap.add_argument("--out", type=Path, default=lab.DATASETS)
    ap.add_argument("--valid-fraction", type=float, default=0.15)
    a = ap.parse_args(argv)
    try:
        m = build(a.ledger, a.out, a.valid_fraction)
    except LedgerRefused as e:
        print(f"build_dataset: refused: {e}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in m.items() if not k.endswith("sha256")}, indent=1))
    print(f"wrote {a.out / 'train.jsonl'} ({m['train']}) and {a.out / 'valid.jsonl'} ({m['valid']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
