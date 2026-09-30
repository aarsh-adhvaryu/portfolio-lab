"""A1 plan §3, fixed before any reader ran: subtype accuracy (5×5 confusion,
agreement, Cohen's kappa, UNCLEAR rate), per flag and overall; precision
T/(T+F) with TRUE = AT_COMPANY; accuracy by confidence band (L only)."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional

SUBTYPES = ("AT_COMPANY", "AGAINST_COMPANY", "RELATED_ENTITY", "NOT_EVENT", "UNCLEAR")
BANDS = ((0.0, 0.7), (0.7, 0.9), (0.9, 1.01))

_ROW = re.compile(r"^\| (\d+) \| (\w+) \| (TRUE|FALSE|UNSURE) \| (\w+) \| (.*) \|\s*$")


def reference(path) -> Dict[int, dict]:
    """{row: {flag, label, subtype}} from flag_audit_labels.md."""
    out = {}
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        m = _ROW.match(ln)
        if m:
            out[int(m[1])] = {"flag": m[2], "label": m[3], "subtype": m[4]}
    return out


def reference_at(path, commit: str) -> Dict[int, dict]:
    """The reference as committed at `commit` (e.g. a15c775, before the
    rating directions)."""
    import subprocess
    import tempfile
    p = Path(path).resolve()
    root = p.parents[2]
    rel = p.relative_to(root).as_posix()
    txt = subprocess.run(["git", "-C", str(root), "show", f"{commit}:{rel}"],
                         capture_output=True, check=True).stdout.decode("utf-8")
    with tempfile.TemporaryDirectory() as d:
        q = Path(d) / "ref.md"
        q.write_text(txt, encoding="utf-8")
        return reference(q)


def file_sha(path) -> str:
    """SHA-256 of the file with LF line ends (the committed blob's hash)."""
    import hashlib
    b = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(b).hexdigest()


def kappa(pairs: List[tuple]) -> Optional[float]:
    """Cohen's kappa of (reference, reader) pairs; None if undefined."""
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return None if pe == 1 else (po - pe) / (1 - pe)


def _precision(subs: Iterable[str]) -> Optional[float]:
    c = Counter(subs)
    t = c["AT_COMPANY"]
    f = sum(v for k, v in c.items() if k not in ("AT_COMPANY", "UNCLEAR"))
    return t / (t + f) if (t + f) else None


def _at_calls(pairs) -> Optional[float]:
    calls = [a for a, b in pairs if b == "AT_COMPANY" and a != "UNCLEAR"]
    return (sum(a == "AT_COMPANY" for a in calls) / len(calls)) if calls else None


def block(pairs: List[tuple], conf: Optional[List[float]] = None) -> dict:
    """Scores for one set of (reference subtype, reader subtype) pairs."""
    n = len(pairs)
    cm = {r: {c: 0 for c in SUBTYPES} for r in SUBTYPES}
    for a, b in pairs:
        cm[a][b] += 1
    out = {"n": n,
           "agreement": (sum(a == b for a, b in pairs) / n) if n else None,
           "kappa": kappa(pairs),
           "unclear_rate_reader": (sum(b == "UNCLEAR" for _, b in pairs) / n) if n else None,
           "unclear_rate_reference": (sum(a == "UNCLEAR" for a, _ in pairs) / n) if n else None,
           "precision_reader": _precision(b for _, b in pairs),
           "precision_reference": _precision(a for a, _ in pairs),
           # the reader's AT_COMPANY calls that the reference also calls
           # AT_COMPANY, among those the reference resolved (not UNCLEAR):
           # comparable with K's, which is precision_reference
           "at_call_precision": _at_calls(pairs),
           "confusion": cm}
    if conf is not None:
        bands = {}
        for lo, hi in BANDS:
            sel = [(a == b) for (a, b), c in zip(pairs, conf) if c is not None and lo <= c < hi]
            bands[f"{lo:.1f}-{min(hi, 1.0):.1f}"] = {
                "n": len(sel), "agreement": (sum(sel) / len(sel)) if sel else None}
        out["by_confidence"] = bands
    return out


def score(ref: Dict[int, dict], reads: Dict[int, dict], rows=None) -> dict:
    """Per flag and overall. `reads` = {row: {"subtype", "confidence"}};
    a row the reader failed on counts as UNCLEAR (and is counted)."""
    rows = sorted(rows if rows is not None else ref)
    by_flag: Dict[str, list] = {}
    failed = 0
    for r in rows:
        got = reads.get(r) or {}
        sub = got.get("subtype")
        if sub not in SUBTYPES:
            failed += 1
            sub = "UNCLEAR"
        by_flag.setdefault(ref[r]["flag"], []).append(
            (ref[r]["subtype"], sub, got.get("confidence")))
    allp = [x for v in by_flag.values() for x in v]
    fn = lambda v: block([(a, b) for a, b, _ in v], [c for _, _, c in v])
    return {"overall": fn(allp), "failed_reads": failed,
            "flags": {f: fn(v) for f, v in sorted(by_flag.items())}}


def keyword_reader(ref: Dict[int, dict]) -> Dict[int, dict]:
    """K: every audit row was flagged by it, so it asserts AT_COMPANY."""
    return {r: {"subtype": "AT_COMPANY", "confidence": None} for r in ref}
