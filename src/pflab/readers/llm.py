"""Reader L (A1 plan §1): a local LLM through Ollama, temperature 0, fixed seed.

The prompt is built from `flag_audit_labels.md`: the "Criteria, fixed before
labelling" section verbatim (the question, TRUE/FALSE/UNSURE, the per-flag
table), and the subtype table's "means" column verbatim. The subtype table's
row lists and counts are left out, because they are the reference answers.
Output is constrained to a JSON schema. `reason` is asked for first, so the
model states its reading before it commits to a label.

Declared build choices: Ollama's `think` is off (the plan's 1–2 s a row
assumes no reasoning trace); `num_predict` caps each reply at 400 tokens.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Optional

import requests

from pflab.readers.score import SUBTYPES

URL = "http://localhost:11434"
SEED = 20260930
FLAGS = ("AUDITOR_RESIGNATION", "DEFAULT", "FORENSIC_AUDIT", "FRAUD", "INSOLVENCY",
         "PROMOTER_ENCUMBRANCE", "RATING_DOWNGRADE", "REGULATORY_ACTION",
         "RESULTS_DELAY")

AUDIT_SCHEMA = {"type": "object", "properties": {
    "reason": {"type": "string"},
    "label": {"type": "string", "enum": ["TRUE", "FALSE", "UNSURE"]},
    "subtype": {"type": "string", "enum": list(SUBTYPES)},
    "confidence": {"type": "number"}},
    "required": ["reason", "label", "subtype", "confidence"]}
RECALL_SCHEMA = {"type": "object", "properties": {
    "reason": {"type": "string"},
    "flag": {"type": "string", "enum": list(FLAGS) + ["NONE"]},
    "subtype": {"type": "string", "enum": list(SUBTYPES)},
    "confidence": {"type": "number"}},
    "required": ["reason", "flag", "subtype", "confidence"]}


def _section(text: str, start: str, stop: str) -> str:
    i = text.index(start)
    return text[i:text.index(stop, i)].strip()


def subtype_means(text: str) -> str:
    """The subtype table's 'means' column, without its row lists or counts."""
    out = []
    for ln in _section(text, "| subtype | means |", "| **all**").splitlines()[2:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        means = re.sub(r"\s*\(\d[^)]*\)\s*$", "", cells[1])     # row lists
        out.append(f"- **{cells[0]}**: {means}")
    return "\n".join(out)


def system_prompt(labels_md: Path, task: str) -> str:
    text = Path(labels_md).read_text(encoding="utf-8")
    crit = _section(text, "## Criteria, fixed before labelling", "## Summary of the labels")
    subs = subtype_means(text)
    head = ("You label Indian stock-exchange announcements for a research audit. "
            "Company names and dates are masked as [CO] and [DATE]. Judge only "
            "the text given.\n\n")
    tail = ("\n\n## Subtype\n\nEvery row also gets exactly one subtype. TRUE is "
            "always AT_COMPANY; UNSURE is always UNCLEAR; FALSE is one of "
            "AGAINST_COMPANY, RELATED_ENTITY or NOT_EVENT.\n\n" + subs)
    if task == "audit":
        ask = ("\n\n## Answer\n\nYou are given the flag a keyword rule raised and "
               "the announcement. Reply in JSON: `reason` (one sentence), "
               "`label`, `subtype`, and `confidence` (0 to 1).")
    else:
        ask = ("\n\n## Answer\n\nNo flag is given. Decide which flag's event, if "
               "any, this announcement reports, using the per-flag table. If "
               "none, answer flag NONE with subtype NOT_EVENT. Otherwise give "
               "the subtype as above. Reply in JSON: `reason` (one sentence), "
               "`flag`, `subtype`, and `confidence` (0 to 1).")
    return head + crit + tail + ask


def user_prompt(row: dict, task: str, attachment: Optional[str] = None) -> str:
    parts = []
    if task == "audit":
        parts.append(f"Flag: {row['flag']}")
    parts += [f"Headline: {row['headline']}",
              f"Category: {row.get('category', '')} / {row.get('subcategory', '')}"]
    if attachment:
        parts.append("Attached letter (masked text):\n" + attachment)
    return "\n".join(parts)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def model_digest(model: str) -> str:
    tags = requests.get(f"{URL}/api/tags", timeout=30).json()["models"]
    for m in tags:
        if m["name"] in (model, f"{model}:latest"):
            return m["digest"]
    raise KeyError(f"{model} is not installed in Ollama")


def read(model: str, system: str, user: str, schema: dict,
         seed: int = SEED) -> dict:
    t0 = time.time()
    r = requests.post(f"{URL}/api/chat", timeout=600, json={
        "model": model, "stream": False, "think": False, "format": schema,
        "options": {"temperature": 0, "seed": seed, "num_predict": 400},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}]})
    r.raise_for_status()
    raw = r.json()["message"]["content"]
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {}
    return {"output": out, "raw": raw, "seconds": round(time.time() - t0, 2)}


class Cache:
    """JSONL keyed by (model digest, system SHA, user SHA): a re-run with
    identical inputs reads instead of asking again."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.d = {}
        if self.path.exists():
            for ln in self.path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(ln)
                self.d[rec["key"]] = rec

    @staticmethod
    def key(digest: str, system: str, user: str) -> str:
        return sha(digest + "\x00" + sha(system) + "\x00" + sha(user))

    def get(self, k):
        return self.d.get(k)

    def put(self, rec: dict) -> None:
        self.d[rec["key"]] = rec
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
