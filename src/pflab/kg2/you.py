"""What he sends enters the graph as events with source "you" (S85, A69 door a, E3).

A document or a checked fact that the intake (`entrance/readers.py`) read is attached to ISINs ONLY by a confident rule, in code (never a model): the ISIN written in the text, or a scope alias named in
it twice or more (or in its title). The event is usable FROM THE MOMENT IT WAS RECEIVED (`ts` = the received time, `ts_rule` = `received_time`; never earlier). It is written to a RAW file,
`<data>/kg/you_events.jsonl` (append-only, one JSON row per event), which is one of the graph's raw inputs like the classification cache: `build` reads it, so the nightly rebuild keeps these events
and two rebuilds stay byte for byte the same. `add` also puts the rows in the store's `kg2_event` at once when the graph is ON and its audit passed, so the loop reads them at its next step
instead of after the night's rebuild (the rebuild then writes the same rows). `audit.run_audit` counts them and checks their time (`you_events_point_in_time`).
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from pflab.kg2 import classify, filing_time as ft, scope as sc

SOURCE = "you"
FILE = "you_events.jsonl"
MAX_LINKS = 5                      # ISINs attached to one document at most (a document about everything is about nothing)
TITLE_CHARS = 600                  # the "title area": an alias named here counts at once
_LOCK = threading.Lock()
ISIN_RX = re.compile(r"(?<![A-Z0-9])[A-Z]{2}[A-Z0-9]{9}\d(?![A-Z0-9])")


def path(root: Path) -> Path:
    return sc.kg_dir(root) / FILE


def _eid(*parts) -> str:
    from pflab.kg2.build import _eid as e
    return e(*parts)


def link(text: str, scope: dict, *, title: str = "") -> List[dict]:
    """The ISINs the document is confidently about: [{"isin", "rule", "proof", "mentions"}], most named first. `scope` is the graph's scope (`kg2.scope.load`). A literal ISIN in the text is one
    hit; an alias counts when it is named at least twice or appears in the title area (the title, or the first 600 characters)."""
    names = {n["isin"]: n for n in scope.get("names", [])}
    out: Dict[str, dict] = {}
    for m in ISIN_RX.finditer(text or ""):
        i = m.group(0)
        if i in names and i not in out:
            out[i] = {"isin": i, "rule": "you:isin_in_text", "proof": f"the ISIN {i} is written in the document", "mentions": len(re.findall(re.escape(i), text))}
    text = (text or "")[:200_000]
    hay = " " + sc.norm_name(text) + " "
    head = " " + sc.norm_name(f"{title} {text[:TITLE_CHARS]}") + " "
    for alias, isin in sc.alias_index(scope).items():
        if isin in out:
            continue
        n = hay.count(f" {alias} ")
        if n >= 2 or (n >= 1 and f" {alias} " in head):
            cur = out.get(isin)
            if not cur or n > cur["mentions"]:
                out[isin] = {"isin": isin, "rule": "you:alias_exact_in_text", "mentions": n,
                             "proof": f"'{alias}' (an alias of {isin}) is named {n} time(s) in the document" + (", once in its title area" if f" {alias} " in head else "")}
    return sorted(out.values(), key=lambda d: (-d["mentions"], d["isin"]))[:MAX_LINKS]


def row(isin: str, rule: str, proof: str, *, sha: str, received_at: datetime, headline: str, ref: str = "") -> dict:
    """One event row (the graph's EVENT_COLS plus `received_at`) for a document or a checked fact."""
    from pflab.kg2.build import norm_headline
    head = " ".join(str(headline or "").split())[:500] or "(a note from you)"
    kind, sev = classify.rule_kind(head)
    if kind in classify.THESIS_BREAK_KINDS or kind == "other":
        kind, sev = "news", "low"            # a keyword in something he sent is a LEAD for the thinking loop, never a thesis break by itself (the same rule the graph applies to articles)
    return {"event_id": _eid(SOURCE, sha, isin), "isin": isin, "source": SOURCE, "ref": ref or f"you:{sha[:16]}", "ts": received_at.isoformat(timespec="seconds"),
            "event_date": received_at.date().isoformat(), "kind": kind, "severity": sev, "headline": head, "link_rule": rule, "link_proof": proof,
            "dedupe_key": f"{isin}|{norm_headline(head)}|{received_at.date().isoformat()}", "ts_rule": ft.RULE_RECEIVED, "received_at": received_at.isoformat(timespec="seconds")}


def load(root: Path) -> List[dict]:
    p = path(root)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue                     # a torn last line is skipped, never fatal
    return out


def append(root: Path, rows: Iterable[dict]) -> int:
    """Append rows whose event_id is not in the file yet (append-only: a row is never rewritten). Returns how many were written."""
    rows = list(rows)
    if not rows:
        return 0
    p = path(root)
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        have = {r.get("event_id") for r in load(root)}
        new = [r for r in rows if r["event_id"] not in have]
        if new:
            with open(p, "a", encoding="utf-8", newline="\n") as f:
                f.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in new))
                f.flush()
                os.fsync(f.fileno())
    return len(new)


def events(root: Path, asof: date, scope: dict) -> Tuple[List[dict], List[dict], dict]:
    """(events, unlinked, stats) for `build`: the rows received on or before `asof`, for ISINs in the scope. Deterministic: sorted by the caller's frame."""
    isins = {n["isin"] for n in scope.get("names", [])} | set(scope.get("extra_isins", []))
    out = []
    for r in load(root):
        try:
            ts = datetime.fromisoformat(r["received_at"])
        except (KeyError, ValueError):
            continue
        if ts.date() > asof or r.get("isin") not in isins:
            continue
        out.append({"event_id": r["event_id"], "isin": r["isin"], "source": SOURCE, "ref": r.get("ref") or "", "ts": ts, "event_date": ts.date(), "kind": r["kind"],
                    "severity": r["severity"], "headline": r["headline"], "link_rule": r["link_rule"], "link_proof": r["link_proof"], "dedupe_key": r["dedupe_key"],
                    "ts_rule": ft.RULE_RECEIVED})
    return out, [], {"you_events": len(out)}


def to_store(con, rows: Iterable[dict], now: datetime) -> int:
    """Put the rows in `kg2_event` NOW when the graph is on and its audit passed (otherwise nothing from the graph is readable, and the night's rebuild will carry them). The same rows the rebuild writes."""
    from pflab.kg2 import switch
    n = 0
    try:
        if not switch.active(con, now.date()):
            return 0
        for r in rows:
            if con.execute("SELECT 1 FROM kg2_event WHERE event_id=?", [r["event_id"]]).fetchone():
                continue
            con.execute("INSERT INTO kg2_event (event_id, isin, source, ref, ts, event_date, kind, severity, headline, link_rule, link_proof, dedupe_key, ts_rule) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [r["event_id"], r["isin"], SOURCE, r["ref"], datetime.fromisoformat(r["received_at"]), date.fromisoformat(r["event_date"]), r["kind"], r["severity"], r["headline"],
                         r["link_rule"], r["link_proof"], r["dedupe_key"], ft.RULE_RECEIVED])
            n += 1
    except Exception:                        # the graph is optional for the loop; the raw file already holds the row
        return n
    return n


def add(con, root: Path, rows: List[dict], now: datetime) -> int:
    """The door: raw file first (the graph's input), then the store when the graph is live. Returns the rows written to the raw file."""
    n = append(root, rows)
    to_store(con, rows, now)
    return n
