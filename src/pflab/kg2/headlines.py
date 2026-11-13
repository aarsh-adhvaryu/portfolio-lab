"""Fast headlines in the graph (S86, the alarm lane): the raw files `<data>/headlines_s86/<first-seen day>.jsonl` the collector `ingest/headlines.py` writes, made into events by CODE.

Same pattern as `kg2/sec_8k.py`: the graph is rebuilt from raw files every night and must give the same tables byte for byte, so a headline is first a raw line and the events are made from
the lines here; `sync_store` puts the new ones in the store at once (same ids, same rows as the rebuild) so the watch, `recall`, the storylines and the desk see a headline the day it came.

One event per kept headline:
    isin     the name it was collected for (an Indian ISIN, or ZZ + the 10-digit CIK for a US name)
    source   "headline:<feed>" (google_news, yahoo, gdelt_doc)       ref  the item id
    ts       the FIRST-SEEN time (IST wall time), `ts_rule` = seen_time: a headline counts from when we saw it, never from its own (earlier) publication time
    kind     `classify.rule_kind` on the title (a thesis-break kind stays what the rule says); otherwise `news`, low. A cached model answer (`classify.load_cache`) is used when it exists.
A headline first seen after `known_by(asof)` (the next Indian open) waits for the next day's build, like a US filing.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from pflab.kg2 import classify, filing_time as ft, sec_8k

SOURCE_PREFIX = "headline:"
RAW_DIR = "headlines_s86"
_WS = re.compile(r"\s+")


def is_headline_source(source) -> bool:
    return str(source or "").startswith(SOURCE_PREFIX)


def raw_dir(root) -> Path:
    return Path(root) / RAW_DIR


def raw_files(root) -> List[Path]:
    d = raw_dir(root)
    return sorted(d.glob("*.jsonl")) if d.exists() else []


def norm_title(t: str) -> str:
    """A title without its outlet suffix (" - Reuters"), lower-cased, letters and digits only: two copies of one story give the same string."""
    s = re.sub(r"\s+[-|–—]\s+[^-|–—]{2,40}$", "", str(t or "")).lower()
    return _WS.sub(" ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def item_id(isin: str, title: str) -> str:
    return hashlib.sha1(f"{isin}|{norm_title(title)}".encode("utf-8")).hexdigest()[:16]


def event_id(iid: str) -> str:
    return hashlib.sha1(f"headline|{iid}".encode("utf-8")).hexdigest()[:16]


def read_lines(root) -> List[dict]:
    out: List[dict] = []
    for p in raw_files(root):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        except (OSError, ValueError):
            continue
    return out


def kind_of(title: str, cache_row: Optional[dict] = None) -> Tuple[str, str]:
    k, s = classify.rule_kind(title)
    if k == "other":
        if cache_row and cache_row.get("kind") in classify.KINDS and cache_row.get("severity") in classify.SEVERITIES:
            return cache_row["kind"], cache_row["severity"]
        return "news", "low"
    return k, s


def events(root, asof: date, cache: Optional[Dict[str, dict]] = None) -> Tuple[List[dict], dict]:
    """(events, stats) from the raw lines first seen on or before `known_by(asof)`. Deterministic: sorted, no clock."""
    cutoff = sec_8k.known_by(asof)
    cache = cache or {}
    seen: Dict[str, dict] = {}
    for r in read_lines(root):                                           # the earliest first-seen line of an item wins (a duplicate line is a re-find)
        iid = r.get("id")
        if not iid or not r.get("isin") or not r.get("first_seen"):
            continue
        if iid not in seen or str(r["first_seen"]) < str(seen[iid]["first_seen"]):
            seen[iid] = r
    ev: List[dict] = []
    stats = {"headline_lines": len(seen), "headline_events": 0, "headline_after_asof": 0}
    for iid in sorted(seen):
        r = seen[iid]
        ts = pd.to_datetime(r["first_seen"], errors="coerce")
        if pd.isna(ts):
            continue
        ts = ts.to_pydatetime().replace(tzinfo=None)
        if ts > cutoff:
            stats["headline_after_asof"] += 1
            continue
        eid = event_id(iid)
        kind, sev = kind_of(r.get("title", ""), cache.get(eid))
        title = str(r.get("title", ""))[:500]
        ev.append({"event_id": eid, "isin": r["isin"], "source": SOURCE_PREFIX + str(r.get("source", "feed")), "ref": iid, "ts": ts, "event_date": ts.date(), "kind": kind, "severity": sev,
                   "headline": title, "link_rule": "headline:name_in_title" if r.get("linked") == "title" else "headline:feed_for_name",
                   "link_proof": f"collected for {r.get('symbol') or r['isin']} from {r.get('source')} ({r.get('outlet') or 'outlet unknown'}); published {r.get('published')}; first seen {r['first_seen']}",
                   "dedupe_key": f"{r['isin']}|{norm_title(title)}|{ts.isoformat()}", "ts_rule": ft.RULE_SEEN})
    stats["headline_events"] = len(ev)
    return ev, stats


def nodes_for(ev: List[dict], known) -> List[dict]:
    """A node for each ISIN a headline event names that the graph has no node for (as-of = the date of its first headline: deterministic, so the rebuild gives the same row)."""
    first: Dict[str, date] = {}
    for x in ev:
        if x["isin"] not in known and (x["isin"] not in first or x["event_date"] < first[x["isin"]]):
            first[x["isin"]] = x["event_date"]
    return [{"isin": i, "name": "", "symbol": "", "origin": "headline", "source": "alarm_lane", "as_of": d} for i, d in sorted(first.items())]


def sync_store(con, root, now: datetime) -> dict:
    """Put the raw lines' events the loaded graph does not have yet into the store, the same rows the rebuild makes. Only when the graph is on and its audit passed. Never raises."""
    try:
        from pflab import markets
        from pflab.kg2 import audit, build as kb, switch
        asof = markets.get("IN").session_closed_by(now)
        if not (switch.on() and audit.last_passed(con, asof)):
            return {"graph_loaded": False}
        ev, _st = events(root, asof, classify.load_cache(root))
        have = {r[0] for r in con.execute("SELECT event_id FROM kg2_event WHERE source LIKE ?", [SOURCE_PREFIX + "%"]).fetchall()}
        new = [x for x in ev if x["event_id"] not in have]
        if new:
            known = {r[0] for r in con.execute("SELECT isin FROM kg2_node").fetchall()}
            nodes = nodes_for(ev, known)
            from pflab.pm import store
            with store.transaction(con):
                for key, table, rows in (("node", "kg2_node", nodes), ("event", "kg2_event", new)):
                    if rows:
                        df = pd.DataFrame(rows, columns=kb.TABLES[key])
                        con.register("_hl_df", df)
                        con.execute(f"INSERT INTO {table} ({', '.join(df.columns)}) SELECT {', '.join(df.columns)} FROM _hl_df")
                        con.unregister("_hl_df")
            return {"graph_loaded": True, "events_added": len(new), "nodes_added": len(nodes)}
        return {"graph_loaded": True, "events_added": 0, "nodes_added": 0}
    except Exception as e:
        return {"graph_loaded": None, "sync_problem": f"{type(e).__name__}: {str(e)[:160]}"}
