"""A1 reader contest (docs/notes/A1-reader-plan.md §3–§6).

    read   --model M   L on the 251 audit rows (headline only) and on the 16
                       readable rating letters (headline + masked attachment)
    recall --model M   L on the 250-row recall sample
    score              docs/notes/A1-reader-scores.md from what has been read
    recall-sheet       docs/data/recall_labels.md: the rows L flags plus 30
                       others at random (seed 20260930), for Aarsh to label

Reads are cached in data/a1_readers/<model>.jsonl (gitignored), keyed by
model digest and the SHA-256 of both prompts, so a re-run with the same
inputs asks nothing. Nothing here reads a return or a company name.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pflab.readers import llm, score as sc  # noqa: E402

LABELS = ROOT / "docs/data/flag_audit_labels.md"
AUDIT = ROOT / "docs/data/flag_audit.md"
RECALL = ROOT / "docs/data/flag_recall_sample.md"
RATING = ROOT / "docs/data/rating_pdf_labels.md"
SCORES = ROOT / "docs/notes/A1-reader-scores.md"
SHEET = ROOT / "docs/data/recall_labels.md"
L_MODEL, ALSO = "qwen3.5-9b-16k", "gemma4-12b-16k"
SEED = 20260930
LETTER_CHARS = 5000


def _out_dir() -> Path:
    from pflab.data import data_dir
    return data_dir() / "a1_readers"


def _cells(ln: str) -> list:
    return [c.strip() for c in re.split(r"(?<!\\)\|", ln.strip())[1:-1]]


def audit_rows() -> dict:
    out = {}
    for ln in AUDIT.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\| \d+ \| [A-Z_]+ \|", ln):
            c = _cells(ln)
            out[int(c[0])] = {"flag": c[1], "headline": " | ".join(c[2:-3]),
                              "category": c[-3], "subcategory": c[-2]}
    return out


def recall_rows() -> dict:
    out = {}
    for ln in RECALL.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\| R\d+ \|", ln):
            c = _cells(ln)
            out[c[0]] = {"headline": " | ".join(c[1:-4]),
                         "category": c[-4], "subcategory": c[-3]}
    return out


def readable_letters() -> dict:
    """{row: masked letter text} for the rating rows whose PDF has text."""
    spec = importlib.util.spec_from_file_location("rating_pdfs", ROOT / "tools/rating_pdfs.py")
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    root = rp._root()
    meta = json.loads((root / "audit_rows.json").read_text(encoding="utf-8"))
    out = {}
    for r in meta:
        p = root / r["attachment"]
        if not (p.exists() and p.stat().st_size):
            continue
        text, _ = rp.extract(p)
        if not text.strip():
            continue
        m = rp.mask_pdf(text, r["company"], r.get("also_mask"))
        # what mask_pdf misses in a full letter: a CIN garbled by the text
        # layer, and a named entity split across lines ("Automotive" / "Pic")
        m = re.sub(r"\bCIN\b[:\s-]*\S+", "[CIN]", m)
        words = {w for t in r.get("also_mask") or () for w in re.findall(r"[A-Za-z]{3,}", t)}
        for w in sorted(words, key=len, reverse=True):
            m = re.sub(rf"\b{re.escape(w)}\b", "[ENTITY]", m, flags=re.I)
        keep = [ln for ln in m.splitlines() if not rp._SKIP_LINE.search(ln)]
        out[int(r["row"])] = "\n".join(keep)[:LETTER_CHARS]
    return out


def run(model: str, task: str, items: dict, attach: dict | None, tag: str) -> dict:
    digest = llm.model_digest(model)
    system = llm.system_prompt(LABELS, task)
    schema = llm.AUDIT_SCHEMA if task == "audit" else llm.RECALL_SCHEMA
    cache = llm.Cache(_out_dir() / f"{model}.jsonl")
    reads, asked, t0 = {}, 0, time.time()
    for i, (k, row) in enumerate(items.items(), 1):
        user = llm.user_prompt(row, task, (attach or {}).get(k))
        key = cache.key(digest, system, user)
        rec = cache.get(key)
        if rec is None:
            rec = {"key": key, "row": str(k), "set": tag, **llm.read(model, system, user, schema)}
            cache.put(rec)
            asked += 1
        reads[str(k)] = {**rec["output"], "seconds": rec["seconds"]}
        if i % 25 == 0:
            print(f"  {tag}: {i}/{len(items)}  {time.time() - t0:.0f} s", flush=True)
    meta = {"model": model, "digest": digest, "system_sha256": llm.sha(system),
            "seed": llm.SEED, "think": False, "temperature": 0, "set": tag,
            "rows": len(items), "asked": asked, "seconds": round(time.time() - t0, 1)}
    (_out_dir() / f"{model}_{tag}.json").write_text(
        json.dumps({"meta": meta, "reads": reads}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(f"{model} {tag}: {len(items)} rows, {asked} asked, {meta['seconds']} s", flush=True)
    return meta


def cmd_read(model: str) -> None:
    rows = audit_rows()
    assert len(rows) == 251, len(rows)
    run(model, "audit", rows, None, "audit")
    letters = readable_letters()
    assert len(letters) == 16, sorted(letters)
    run(model, "audit", {r: rows[r] for r in sorted(letters)}, letters, "letters")


def cmd_recall(model: str) -> None:
    rows = recall_rows()
    assert len(rows) == 250, len(rows)
    run(model, "recall", rows, None, "recall")


def _load(model: str, tag: str):
    p = _out_dir() / f"{model}_{tag}.json"
    if not p.exists():
        return None, None
    d = json.loads(p.read_text(encoding="utf-8"))
    return d["meta"], {int(k) if k.isdigit() else k: v for k, v in d["reads"].items()}


def _pct(x):
    return "—" if x is None else f"{100 * x:.0f}%"


def _k(x):
    return "—" if x is None else f"{x:.2f}"


def cmd_score() -> None:
    ref = sc.reference(LABELS)
    old = sc.reference_at(LABELS, "a15c775")
    readers = {"K (keywords)": (None, sc.keyword_reader(ref))}
    for m in (L_MODEL, ALSO):
        meta, reads = _load(m, "audit")
        if reads:
            readers[f"L {m}" if m == L_MODEL else f"{m} (reported)"] = (meta, reads)
    letters = {}
    for m in (L_MODEL, ALSO):
        meta, reads = _load(m, "letters")
        if reads:
            letters[m] = (meta, reads)
    lines = ["# A1 reader contest — scores (numbers only)", "",
             f"Scored by `tools/a1_contest.py score`, "
             f"{time.strftime('%Y-%m-%d')}. Plan: `docs/notes/A1-reader-plan.md` §3 "
             "(fixed before any reader ran). Reference: `flag_audit_labels.md`, "
             f"SHA-256 `{sc.file_sha(LABELS)}`. **Nothing is decided here.**", ""]
    lines += ["## Readers", "", "| reader | model digest | system prompt SHA-256 | rows | seconds |",
              "|---|---|---|---|---|"]
    for name, (meta, _) in list(readers.items()) + [(f"{m} letters", v) for m, v in letters.items()]:
        if meta:
            lines.append(f"| {name} | `{meta['digest'][:12]}` | `{meta['system_sha256'][:16]}…` "
                         f"| {meta['rows']} | {meta['seconds']} |")
    lines += ["", "L settings: temperature 0, seed 20260930, Ollama `think` off, "
              "JSON schema, reason first. A row with no valid subtype counts as UNCLEAR.", ""]

    def overall_table(title, ref_, rows, note=""):
        out = [f"## {title}", "", note, "",
               "| reader | n | agreement | κ | reader UNCLEAR | reference UNCLEAR | precision (reader) | precision (reference) | failed |",
               "|---|---|---|---|---|---|---|---|---|"]
        res = {}
        for name, (_, reads) in readers.items():
            s = sc.score(ref_, reads, rows)
            res[name] = s
            o = s["overall"]
            out.append(f"| {name} | {o['n']} | {_pct(o['agreement'])} | {_k(o['kappa'])} | "
                       f"{_pct(o['unclear_rate_reader'])} | {_pct(o['unclear_rate_reference'])} | "
                       f"{_pct(o['precision_reader'])} | {_pct(o['precision_reference'])} | "
                       f"{s['failed_reads']} |")
        return out, res

    t, res = overall_table("1. Headline only, 251 rows, current reference", ref, None,
                           "The primary score (plan §3): subtype accuracy.")
    lines += t
    lines += ["", "### Per flag (agreement / κ / reader UNCLEAR / reader precision; reference precision)", "",
              "| flag | n | ref precision | " + " | ".join(readers) + " |",
              "|---|---|---|" + "---|" * len(readers)]
    for f in sorted(res["K (keywords)"]["flags"]):
        first = res["K (keywords)"]["flags"][f]
        cells = [f"{_pct(v['flags'][f]['agreement'])} / {_k(v['flags'][f]['kappa'])} / "
                 f"{_pct(v['flags'][f]['unclear_rate_reader'])} / {_pct(v['flags'][f]['precision_reader'])}"
                 for v in res.values()]
        lines.append(f"| {f} | {first['n']} | {_pct(first['precision_reference'])} | " + " | ".join(cells) + " |")
    for name, s in res.items():
        if name.startswith("K"):
            continue
        cm = s["overall"]["confusion"]
        lines += ["", f"### Confusion, {name} (rows: reference; columns: reader)", "",
                  "| reference \\ reader | " + " | ".join(sc.SUBTYPES) + " |",
                  "|---|" + "---|" * len(sc.SUBTYPES)]
        for r in sc.SUBTYPES:
            lines.append(f"| {r} | " + " | ".join(str(cm[r][c]) for c in sc.SUBTYPES) + " |")
        bands = s["overall"].get("by_confidence") or {}
        lines += ["", "Agreement by stated confidence: " + "; ".join(
            f"{b}: {_pct(v['agreement'])} (n {v['n']})" for b, v in bands.items())]

    t, _ = overall_table("2. Headline only, 251 rows, reference before the rating directions (a15c775)",
                         old, None, "For continuity: the 21 revision rows were UNCLEAR in this reference.")
    lines += [""] + t
    rows16 = sorted(letters[L_MODEL][1]) if L_MODEL in letters else []
    if rows16:
        lines += ["", "## 3. The 16 readable rating letters, current reference", "",
                  "| reader | input | n | agreement | κ | reader UNCLEAR |", "|---|---|---|---|---|---|"]
        for name, (_, reads) in readers.items():
            o = sc.score(ref, reads, rows16)["overall"]
            lines.append(f"| {name} | headline | {o['n']} | {_pct(o['agreement'])} | {_k(o['kappa'])} | {_pct(o['unclear_rate_reader'])} |")
        for m, (_, reads) in letters.items():
            o = sc.score(ref, reads, rows16)["overall"]
            lines.append(f"| {m} | headline + letter | {o['n']} | {_pct(o['agreement'])} | {_k(o['kappa'])} | {_pct(o['unclear_rate_reader'])} |")
        lines += ["", "| row | reference | " + " | ".join(f"{m} + letter" for m in letters) + " |",
                  "|---|---|" + "---|" * len(letters)]
        for r in rows16:
            lines.append(f"| {r} | {ref[r]['subtype']} | " + " | ".join(
                str(reads.get(r, {}).get("subtype")) for _, reads in letters.values()) + " |")
    for m in (L_MODEL, ALSO):
        meta, reads = _load(m, "recall")
        if reads:
            c = {}
            for v in reads.values():
                c[v.get("flag", "?")] = c.get(v.get("flag", "?"), 0) + 1
            lines += ["", f"## 4. Recall sample, {m}: flags raised on 250 unflagged rows", "",
                      ", ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1])),
                      f"({meta['seconds']} s). No reference yet: Aarsh labels `docs/data/recall_labels.md`."]
    SCORES.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"-> {SCORES}")


def cmd_sheet() -> None:
    meta, reads = _load(L_MODEL, "recall")
    rows = recall_rows()
    flagged = [k for k in rows if reads[k].get("flag") not in (None, "NONE")]
    rest = sorted(set(rows) - set(flagged), key=lambda k: int(k[1:]))
    others = sorted(random.Random(SEED).sample(rest, 30), key=lambda k: int(k[1:]))
    pick = sorted(set(flagged) | set(others), key=lambda k: int(k[1:]))
    lines = ["# Recall sample — rows for Aarsh to label", "",
             f"From `flag_recall_sample.md` (250 unflagged announcements). **{len(flagged)}** rows "
             f"that L (`{L_MODEL}`, digest `{meta['digest'][:12]}`) flags, plus **30** of the "
             f"other {len(rest)} at random (seed {SEED}), in row order, "
             f"{len(pick)} in all. L's reading is **not shown**, so the label is blind; it is in "
             "`data/a1_readers/` and is joined after labelling.", "",
             "Mark each row with the flag whose event it is, or **NONE**, and a subtype from "
             "`flag_audit_labels.md` (AT_COMPANY, AGAINST_COMPANY, RELATED_ENTITY, NOT_EVENT, UNCLEAR).", "",
             "| row | headline (masked) | category | subcategory | flag or NONE | subtype |",
             "|---|---|---|---|---|---|"]
    for k in pick:
        r = rows[k]
        lines.append(f"| {k} | {r['headline']} | {r['category']} | {r['subcategory']} |  |  |")
    SHEET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(flagged)} flagged + 30 others -> {SHEET}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["read", "recall", "score", "recall-sheet"])
    ap.add_argument("--model", default=L_MODEL)
    a = ap.parse_args(argv)
    {"read": lambda: cmd_read(a.model), "recall": lambda: cmd_recall(a.model),
     "score": cmd_score, "recall-sheet": cmd_sheet}[a.cmd]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
