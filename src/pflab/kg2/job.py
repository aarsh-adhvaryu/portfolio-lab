"""The graph's nightly job (S81 B7): classify new events with the local model (bounded), build, audit, and load the store only when the audit passes AND the
switch is on. `run(con, root, day)` is job-ready (the coordinator routes it).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

from pflab.kg2 import audit, build as kb, classify, news, switch


def classify_pending(root: Path, g: dict, limit: int = 40, chat: Optional[Callable] = None) -> dict:
    """Ask the local model about events the rules left as `other`/`news` (newest first, at most `limit`); answers are validated by code and cached.
    A model that cannot answer leaves the rule's answer. Returns counts only."""
    cache = classify.load_cache(root)
    ev = g["event"]
    todo = ev[ev["kind"].isin(["other", "news"]) & ~ev["event_id"].isin(set(cache))].copy()
    # S84: a headline with a governance keyword (the rule's leadership_crisis lead) is asked about FIRST, then newest first
    todo["_lead"] = [0 if classify.rule_kind(str(h or ""))[0] == "leadership_crisis" else 1 for h in todo["headline"]]
    todo = todo.sort_values(["_lead", "ts", "event_id"], ascending=[True, False, True]).head(limit)
    done, failed, rows = 0, 0, []
    for r in todo.itertuples():
        text = ""
        if r.source == "gdelt_gkg1":
            tp = news.text_path(root, news.url_hash(r.ref))
            if tp.exists():
                text = json.loads(tp.read_text(encoding="utf-8")).get("text", "")[:1500]
        pick = classify.model_classify(r.headline or "", text, chat=chat)
        if pick is None:
            failed += 1
            continue
        kind, sev, method = classify.final_kind(("other", "low"), pick)
        rows.append({"event_id": r.event_id, "kind": kind if kind in classify.KINDS else "other", "severity": sev, "method": method, "model": "local",
                     "classified_at": datetime.now().isoformat(timespec="seconds")})
        done += 1
    classify.append_cache(root, rows)
    return {"asked": int(len(todo)), "classified": done, "failed": failed}


def run(con, root: Path, day: date, classify_limit: int = 0, chat: Optional[Callable] = None, now: Optional[datetime] = None) -> dict:
    root = Path(root)
    cl = classify_pending(root, kb.build(root, day), classify_limit, chat) if classify_limit else {"asked": 0}
    g = kb.build(root, day)
    hashes = kb.write(g, root / "kg" / "graph")
    res = audit.run_audit(con, root, day, graph=g)
    loaded = False
    if res["passed"] and switch.on():
        kb.load_store(con, g, day, now)
        loaded = True
    else:                                                         # a failed audit, or the switch off: nothing from the graph is readable
        for t in ("kg2_node", "kg2_fact", "kg2_relation", "kg2_event", "kg2_unlinked"):
            con.execute(f"DELETE FROM {t}")
    failed = [c["name"] for c in res["checks"] if c["gating"] and not c["passed"]]
    return {"passed": res["passed"], "loaded": loaded, "switch_on": switch.on(), "failed_checks": failed, "counts": g["stats"], "classify": cl, "hashes": hashes}
