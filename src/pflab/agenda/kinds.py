"""What can be on the agenda. A KIND is a producer (finds candidate items from the store) and a worker (does one). Register more with `register`.

    producer(con, market, now) -> list of candidates: {"subject", "reason", "expected_value", ["cost_rupees", "cost_seconds", "payload"]}
    worker(rt, item, now)      -> {"useful": bool, "effect": "<belief|forecast_weight|decision|answered_him>: what changed", "outcome": "what happened"}
                                  (or {"skip": "reason"} when the item cannot be done after all)

Built in, where the code already exists: recheck_thesis (agents/thesis.py), read_flagged_filing (research flags + the local model, a quote must be in the text),
draft_learner_claim (the learner's reader, local model), fill_data_gap (the backfill's helper), explain_move (`pflab.hq.explain.explain_move`, a plugin: the kind
produces nothing while that module is absent). `custom` kinds are whatever is registered. Everything built in is free and local; a kind that spends rupees
says so in `cost_rupees` and the picker prices it against the governor first.
"""
from __future__ import annotations

import importlib
import inspect
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from pflab.agenda import items

Producer = Callable[[object, str, datetime], List[dict]]
Worker = Callable[[object, dict, datetime], dict]


@dataclass(frozen=True)
class Kind:
    name: str
    producer: Producer
    worker: Worker
    cost_rupees: float = 0.0
    cost_seconds: float = 10.0
    doc: str = ""


REGISTRY: Dict[str, Kind] = {}


def register(kind: str, producer: Producer, worker: Worker, *, cost_rupees: float = 0.0, cost_seconds: float = 10.0, doc: str = "") -> Kind:
    """Add (or replace) a kind. Candidates without their own costs get these."""
    REGISTRY[kind] = Kind(kind, producer, worker, float(cost_rupees), float(cost_seconds), doc)
    return REGISTRY[kind]


def unregister(kind: str) -> None:
    REGISTRY.pop(kind, None)


def names() -> List[str]:
    return sorted(REGISTRY)


def produce(con, market: str, now: datetime) -> Dict[str, int]:
    """Run every producer and queue its candidates (deduplicated); {kind: items added}. A producer that raises adds nothing and does not stop the others."""
    added: Dict[str, int] = {}
    for k in list(REGISTRY.values()):
        n = 0
        try:
            for c in k.producer(con, market, now) or []:
                iid = items.add(con, market, k.name, str(c["subject"]), str(c.get("reason") or ""), float(c.get("expected_value", 1.0)),
                                float(c.get("cost_rupees", k.cost_rupees)), float(c.get("cost_seconds", k.cost_seconds)), now, c.get("payload"))
                n += 1 if iid else 0
        except Exception:
            n = 0
        added[k.name] = n
    return added


# --- the local model, one short call (tests replace this) ---------------------------------------------------------------------------------

def local_json(system: str, prompt: str, schema: dict, num_predict: int = 500) -> dict:
    from pflab.hq import models
    from pflab.llm import client
    model = models.model_id("learner_reading", {"models": {"learner_reading": "local"}})
    r = client.chat(model, [{"role": "system", "content": system}, {"role": "user", "content": prompt}], fmt=schema, num_predict=num_predict,
                    num_ctx=8192, purpose="agenda")
    return json.loads(r.text)


# --- recheck_thesis --------------------------------------------------------------------------------------------------------------------

def _theses_due(con, market: str, now: datetime) -> List[dict]:
    if market != "IN":
        return []
    out = []
    for tid, text, expires, last in con.execute("SELECT thesis_id, text, expires, last_checked FROM theses WHERE status='open'").fetchall():
        age = (now - last).total_seconds() / 86400 if last else 3.0
        if last and age < 0.8:
            continue
        near = 2.0 if expires and 0 <= (expires - now.date()).days <= 14 else 0.0
        out.append({"subject": f"thesis:{tid}", "reason": f"thesis #{tid} (\"{text[:60]}\") " + (f"last checked {age:.0f} day(s) ago" if last else "never checked")
                    + (", expires soon" if near else ""), "expected_value": 2.0 + min(age, 5.0) + near, "cost_seconds": 5.0, "payload": {"thesis_id": int(tid)}})
    return out


def _recheck_thesis(rt, item: dict, now: datetime) -> dict:
    from pflab.agents import thesis
    con = rt.cursor()
    tid = int(item["payload"]["thesis_id"])
    row = con.execute("SELECT text, keywords_json, sectors_json, status, evidence_json FROM theses WHERE thesis_id=?", [tid]).fetchone()
    if not row or row[3] != "open":
        return {"skip": f"thesis #{tid} is no longer open"}
    kw, sc = json.loads(row[1]), json.loads(row[2])
    old = json.loads(row[4]) if row[4] else {}
    ev = thesis.evidence(con, kw, now.date())
    new = dict(old)
    new["evidence"] = ev
    try:
        new["exposure"] = thesis.exposure(con, kw, sc, now.date())
    except Exception:                                        # no ledger on this PC: the evidence alone still counts
        pass
    con.execute("UPDATE theses SET last_checked=?, evidence_json=? WHERE thesis_id=?", [now, json.dumps(new, default=str), tid])
    before = (old.get("evidence") or {}).get("documents")
    changed = before is None and ev["documents"] > 0 or (before is not None and (before != ev["documents"] or (old.get("evidence") or {}).get("latest") != ev["latest"]))
    if changed:
        was = "no earlier count" if before is None else f"{before} document(s) before"
        return {"useful": True, "effect": f"belief: thesis #{tid} now has {ev['documents']} matching document(s) in 30 days ({was})",
                "outcome": f"evidence moved; newest: {(ev['latest'] or ['-'])[0][:120]}"}
    return {"useful": False, "effect": "", "outcome": f"thesis #{tid}: nothing new ({ev['documents']} matching document(s))"}


# --- read_flagged_filing ---------------------------------------------------------------------------------------------------------------

FILING_KINDS = ("material_filing", "results", "results_surprise", "guard_change")
FILING_SCHEMA = {"type": "object", "properties": {"material": {"type": "string", "enum": ["yes", "no", "unsure"]}, "what_changed": {"type": "string"},
                                                  "quote": {"type": "string"}}, "required": ["material", "what_changed", "quote"]}
FILING_SYSTEM = ("You read one company filing for an investor who holds shares. Say whether it changes how the business should be seen (material: yes, no or unsure), "
                 "in at most two plain sentences what changed, and copy one sentence of the filing word for word as the quote. Use only the filing. Give no figures that the filing does not state.")


def _flags_to_read(con, market: str, now: datetime) -> List[dict]:
    if market != "IN":
        return []
    out = []
    for fid, isin, sym, kind, happened, ref, detail in con.execute(
            "SELECT flag_id, isin, symbol, kind, happened_at, ref, detail FROM research_flags WHERE detected_at >= ? ORDER BY detected_at DESC LIMIT 60",
            [now - timedelta(days=7)]).fetchall():
        if not (kind in FILING_KINDS or kind.startswith("red_flag:")):
            continue
        subject = f"flag:{fid}"
        if items.ever_handled(con, market, "read_flagged_filing", subject):
            continue
        w = 6.0 if kind.startswith("red_flag:") else 5.0 if kind == "material_filing" else 4.0
        out.append({"subject": subject, "reason": f"{sym or isin}: {detail[:110]}", "expected_value": w, "cost_seconds": 40.0,
                    "payload": {"flag_id": int(fid), "doc_id": ref, "kind": kind, "symbol": sym}})
    return out


def _doc_text(con, doc_id: str) -> Optional[str]:
    r = con.execute("SELECT title, text_path FROM kg_docs WHERE doc_id=?", [doc_id]).fetchone()
    if not r or not r[1] or not Path(r[1]).exists():
        return None
    return f"{r[0] or ''}\n{Path(r[1]).read_text(encoding='utf-8', errors='replace')}"[:7000]


def _read_flagged_filing(rt, item: dict, now: datetime) -> dict:
    from pflab.agents import memory
    from pflab.learner import claims
    con = rt.cursor()
    p = item["payload"]
    text = _doc_text(con, str(p.get("doc_id")))
    if not text:
        return {"skip": "no stored text for this filing (only a headline): nothing to read"}
    out = local_json(FILING_SYSTEM, text, FILING_SCHEMA)
    material = out.get("material") if out.get("material") in ("yes", "no", "unsure") else "unsure"
    if not claims.quoted(str(out.get("quote", "")), text):
        return {"useful": False, "effect": "", "outcome": "the model's quote is not in the filing: reading discarded"}
    what = re.sub(r"\s+", " ", str(out.get("what_changed", ""))).strip()[:300]
    if material == "yes":
        mid = memory.remember(con, "note", f"{p.get('symbol') or ''} filing read: {what}", subject=f"filing:{p.get('doc_id')}", source="agenda", now=now)
        return {"useful": True, "effect": f"belief: a material filing of {p.get('symbol') or 'a company'} read and kept as memory #{mid}", "outcome": what}
    return {"useful": False, "effect": "", "outcome": f"read, {material}: {what}"[:300]}


# --- draft_learner_claim -------------------------------------------------------------------------------------------------------------

def _sources_to_draft(con, market: str, now: datetime) -> List[dict]:
    if market != "IN":
        return []
    return [{"subject": f"source:{sid}", "reason": f"learner source #{sid} is screened and unread: \"{(title or '')[:80]}\"", "expected_value": 3.0, "cost_seconds": 90.0,
             "payload": {"src_id": int(sid)}}
            for sid, title in con.execute("SELECT src_id, title FROM learn_sources WHERE status='screened' ORDER BY (origin='drop') DESC, src_id LIMIT 3").fetchall()]


def _draft_learner_claim(rt, item: dict, now: datetime) -> dict:
    from pflab.learner import claims, run, sources
    con = rt.cursor()
    sid = int(item["payload"]["src_id"])
    st = con.execute("SELECT status FROM learn_sources WHERE src_id=?", [sid]).fetchone()
    if not st or st[0] != "screened":
        return {"skip": f"source #{sid} is no longer waiting to be read"}
    text_dir, _ = run.folders(rt)
    text = sources.fetch_text(con, sid, text_dir)
    kept = claims.read(con, [("local", claims.local_draft())], sid, text, now)
    if kept:
        return {"useful": True, "effect": f"belief: {len(kept)} claim(s) drafted from source #{sid}, proposed for the learner to register and test", "outcome": f"claims {kept}"}
    return {"useful": False, "effect": "", "outcome": f"source #{sid} read: no testable claim"}


# --- fill_data_gap ---------------------------------------------------------------------------------------------------------------------

BACKFILL_SECONDS = 30.0


def backfill(root, now, budget_s):
    from pflab.app import readiness
    return readiness.backfill_step(root, now, budget_s=budget_s)


def _gaps(con, market: str, now: datetime) -> List[dict]:
    if market != "IN":
        return []
    from pflab import data
    from pflab.app import readiness
    root = data.data_dir()
    if not (root / "bhavcopy").exists():
        return []
    h = readiness.bhavcopy_holes(root, readiness.HISTORY_START, now.date() - timedelta(days=1))["holes"]
    if not h:
        return []
    newest = max(h)
    recent = (now.date() - newest).days <= 5
    return [{"subject": f"bhavcopy:{newest}", "reason": f"{len(h)} market-history session(s) are missing; the newest is {newest}",
             "expected_value": 2.0 + min(len(h), 400) / 200.0 + (3.0 if recent else 0.0), "cost_seconds": BACKFILL_SECONDS + 5}]


def _fill_data_gap(rt, item: dict, now: datetime) -> dict:
    out = backfill(rt.data_root, now, BACKFILL_SECONDS)
    n = int(out.get("fetched", 0))
    if n > 0:
        return {"useful": True, "effect": f"belief: {n} missing session(s) of market history are now held ({out.get('left', '?')} still missing)", "outcome": str(out)[:300]}
    return {"useful": False, "effect": "", "outcome": f"nothing fetched ({out.get('errors', 0)} error(s), {out.get('left', '?')} missing)"}


# --- explain_move (a plugin: pflab.hq.explain.explain_move, provided by another item) ---------------------------------------------------

def _explain_module():
    try:
        m = importlib.import_module("pflab.hq.explain")
    except ImportError:
        return None
    return m if callable(getattr(m, "explain_move", None)) else None


def call_flex(fn, **kw):
    """Call `fn` with the keyword arguments its signature accepts (the plugin's exact signature is the other item's to choose)."""
    params = inspect.signature(fn).parameters
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return fn(**kw)
    return fn(**{k: v for k, v in kw.items() if k in params})


def _moves_to_explain(con, market: str, now: datetime) -> List[dict]:
    m = _explain_module()
    if m is None or market != "IN":
        return []
    out = []
    if callable(getattr(m, "biggest_moves", None)):                 # the plugin's own list: the largest moves of the last closed session among the names the system follows
        from pflab import markets
        day = markets.get(market).session_closed_by(now)
        for c in call_flex(m.biggest_moves, con=con, market=market, day=day, n=5) or []:
            out.append({"subject": f"move:{c['symbol']}:{c['day']}", "reason": f"{c['symbol']} moved {c['move_pct']:+.1f}% on {c['day']}",
                        "expected_value": 3.0 + min(abs(float(c["move_pct"])), 10.0) / 2.0, "cost_seconds": 60.0,
                        "payload": {"isin": c.get("isin"), "symbol": c["symbol"], "day": c["day"]}})
        return out
    if callable(getattr(m, "unexplained", None)):
        for c in call_flex(m.unexplained, con=con, market=market, now=now) or []:
            out.append({"subject": str(c["subject"]), "reason": str(c.get("reason", "an unexplained move")), "expected_value": float(c.get("expected_value", 5.0)),
                        "cost_seconds": float(c.get("cost_seconds", 60.0)), "payload": c.get("payload") or {k: v for k, v in c.items() if k not in ("reason",)}})
        return out
    for fid, isin, sym, happened, detail in con.execute("SELECT flag_id, isin, symbol, happened_at, detail FROM research_flags WHERE kind='fall' AND detected_at >= ? "
                                                         "ORDER BY detected_at DESC LIMIT 10", [now - timedelta(days=3)]).fetchall():
        out.append({"subject": f"move:{sym or isin}:{happened:%Y-%m-%d}", "reason": f"{sym or isin} fell: {detail[:100]}", "expected_value": 5.0, "cost_seconds": 60.0,
                    "payload": {"isin": isin, "symbol": sym, "day": str(happened.date())}})
    return out


def _explain_move(rt, item: dict, now: datetime) -> dict:
    m = _explain_module()
    if m is None:
        return {"skip": "pflab.hq.explain is not installed"}
    p = item["payload"]
    res = call_flex(m.explain_move, rt=rt, con=rt.cursor(), market=item["market"], now=now, isin=p.get("isin"), symbol=p.get("symbol"),
                    day=date.fromisoformat(p["day"]) if p.get("day") else None, item=item)
    text = res if isinstance(res, str) else (res or {}).get("explanation") or (res or {}).get("text") or ""
    if text:
        return {"useful": True, "effect": f"belief: the move of {p.get('symbol') or p.get('isin') or item['subject']} is explained", "outcome": str(text)[:300]}
    return {"useful": False, "effect": "", "outcome": "no explanation was found"}


def _install() -> None:
    register("recheck_thesis", _theses_due, _recheck_thesis, cost_seconds=5, doc="open theses not checked today: evidence and exposure again")
    register("read_flagged_filing", _flags_to_read, _read_flagged_filing, cost_seconds=40, doc="a flagged filing read by the local model, a quote required")
    register("draft_learner_claim", _sources_to_draft, _draft_learner_claim, cost_seconds=90, doc="a screened learner source read for testable claims (local)")
    register("fill_data_gap", _gaps, _fill_data_gap, cost_seconds=35, doc="missing market-history sessions fetched in a short step")
    register("explain_move", _moves_to_explain, _explain_move, cost_seconds=60, doc="an unexplained move explained (needs pflab.hq.explain)")


_install()

try:                                                  # S79b 18D: the kind that drafts lens candidates as protocol stubs (text only)
    import pflab.agenda.propose_lens  # noqa: F401
except Exception:                                     # pragma: no cover
    pass
