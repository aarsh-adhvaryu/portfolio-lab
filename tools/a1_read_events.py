"""L reads the red-flag event table for the flags it was given (A1 plan §5 item 7).

    python tools\\a1_read_events.py --config configs\\e5a_a1.toml

Reads every event of the config's L flags ([e5a.a1] reader = "L") whose
usable_from is on or before --end (default 2021-12-31, validation's end:
nothing in the sealed period is read). Same model, system prompt, masking
and settings as the contest (`tools/a1_contest.py`, audit task): the
headline is masked with `flag_audit_sample.mask_text`, exactly as the
audit's rows were.

Resumable: every reply is cached in data/a1_readers/<model>.jsonl keyed by
model digest and both prompts, so a stopped run picks up where it stopped.
Writes data/a1_readers/events_<model>.parquet (event_id, flag, subtype,
confidence, reason, digest, system_sha256) at the end.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from pflab.backtest import runner  # noqa: E402
from pflab.ranker import events as ev_mod  # noqa: E402
from pflab.readers import llm  # noqa: E402

LABELS = ROOT / "docs/data/flag_audit_labels.md"


def _mask():
    spec = importlib.util.spec_from_file_location("fas", ROOT / "tools/flag_audit_sample.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.mask_text


def out_path(model: str) -> Path:
    from pflab.data import data_dir
    return data_dir() / "a1_readers" / f"events_{model}.parquet"


def load_reads(model: str) -> dict:
    """event_id -> subtype, for the A1 builder."""
    p = out_path(model)
    if not p.exists():
        return {}
    d = pd.read_parquet(p)
    return dict(zip(d["event_id"], d["subtype"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default="configs/e5a_a1.toml")
    ap.add_argument("--end", default="2021-12-31")
    ap.add_argument("--limit", type=int, default=None, help="first N events only (a timing probe)")
    a = ap.parse_args(argv)
    end = date.fromisoformat(a.end)
    if end > date(2021, 12, 31):
        raise SystemExit("refusing: --end is inside the sealed period")
    cfg = runner.load_config(a.config)
    blk = cfg["e5a"]["a1"]
    model, assign = blk["l_model"], blk["reader"]
    ev_mod.check_assignment(assign)
    flags = [f for f, r in assign.items() if r == "L"]

    from pflab.data import red_flag_events
    ev = red_flag_events.load().dropna(subset=["isin", "usable_from"]).copy()
    ev["usable_from"] = pd.to_datetime(ev["usable_from"]).dt.date
    ev = ev[ev["flag"].isin(flags) & (ev["usable_from"] <= end)]
    ev = ev.sort_values(["usable_from", "scrip_code", "flag"], kind="mergesort")
    if a.limit:
        ev = ev.head(a.limit)
    mask = _mask()
    digest = llm.model_digest(model)
    if not digest.startswith(blk["l_digest"]):
        raise SystemExit(f"{model} digest {digest[:12]} != the contest's {blk['l_digest']}")
    system = llm.system_prompt(LABELS, "audit")
    cache = llm.Cache(out_path(model).parent / f"{model}.jsonl")
    print(f"{model}: {len(ev)} events of {flags} to {end}", flush=True)
    rows, asked, t0 = [], 0, time.time()
    for i, r in enumerate(ev.itertuples(index=False), 1):
        eid = ev_mod.event_id(r.scrip_code, r.key_dt, r.flag, r.headline)
        user = llm.user_prompt({"flag": r.flag, "headline": mask(r.headline, r.company),
                                "category": r.category or "",
                                "subcategory": r.subcategory or ""}, "audit")
        key = cache.key(digest, system, user)
        rec = cache.get(key)
        if rec is None:
            rec = {"key": key, "row": eid, "set": "events",
                   **llm.read(model, system, user, llm.AUDIT_SCHEMA)}
            cache.put(rec)
            asked += 1
        o = rec["output"] or {}
        rows.append({"event_id": eid, "flag": r.flag, "subtype": o.get("subtype"),
                     "confidence": o.get("confidence"), "reason": o.get("reason"),
                     "digest": digest, "system_sha256": llm.sha(system)})
        if i % 50 == 0:
            el = time.time() - t0
            print(f"  {i}/{len(ev)}  {el:.0f} s  (~{el / max(asked, 1) * (len(ev) - i) / 60:.0f} min left)",
                  flush=True)
    df = pd.DataFrame(rows).drop_duplicates("event_id")
    df.to_parquet(out_path(model), index=False)
    print(json.dumps({"events": len(df), "asked": asked, "seconds": round(time.time() - t0, 1),
                      "subtypes": df["subtype"].value_counts(dropna=False).to_dict(),
                      "out": str(out_path(model))}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
