"""The synthesizer (S79b item 16): the local THINKER reads the situation (typed claims, never raw agent text) and returns ONE structured report draft; code checks it.

What the model may do: choose which claims matter, say in words what happened (NOW), name cause -> effect pairs between claims (WHY), say what that means for the book
(SO WHAT), comment on the scenarios the tools produced (NEXT), and propose actions (ACT). What it may not do: make a number. Therefore
  - every prose item carries claim ids; the sentence is checked with the repo's citation check (`hq/explain.check_citations`): a figure must be in the cited claims,
    written the same way, else the sentence is dropped and listed in `rejected`;
  - NEXT probabilities are not written by the model at all: the scenarios are built from the tools' probability claims and the model only comments;
  - a WHY pair is accepted only if code finds the cause dated before the effect (`chains.validate_link`);
  - a watch threshold must be a figure printed in the claim it cites; an agenda or paper request with a figure needs the same citation.
The model is the role `thinker` in `configs/llm_models.toml` when a pick exists, else the general local model (qwen3:8b-q8_0). No paid call is made here.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from pflab.hq import explain

PSEUDO = 1_000_000                       # claim N is presented to the citation check as call PSEUDO+N
LOCAL_DEFAULT = "qwen3:8b-q8_0"

SCHEMA = {
    "type": "object",
    "properties": {
        "now": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}, "claims": {"type": "array", "items": {"type": "integer"}}},
                                           "required": ["text", "claims"]}},
        "why": {"type": "array", "items": {"type": "object", "properties": {"cause": {"type": "integer"}, "effect": {"type": "integer"}, "mechanism": {"type": "string"}},
                                           "required": ["cause", "effect", "mechanism"]}},
        "so_what": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}, "claims": {"type": "array", "items": {"type": "integer"}}},
                                               "required": ["text", "claims"]}},
        "next": {"type": "array", "items": {"type": "object", "properties": {"candidate": {"type": "string"}, "note": {"type": "string"},
                                                                              "claims": {"type": "array", "items": {"type": "integer"}}}, "required": ["candidate", "note"]}},
        "act": {"type": "object", "properties": {
            "paper_request": {"type": "string"},
            "agenda": {"type": "array", "items": {"type": "object", "properties": {"subject": {"type": "string"}, "reason": {"type": "string"}}, "required": ["subject", "reason"]}},
            "question": {"type": "object", "properties": {"text": {"type": "string"}, "default": {"type": "string"}}},
            "watch": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}, "series": {"type": "string"}, "op": {"type": "string", "enum": [">", "<"]},
                                                                                   "threshold": {"type": "number"}, "claim": {"type": "integer"}}, "required": ["text", "series", "op", "threshold", "claim"]}}}},
    },
    "required": ["now", "why", "so_what", "next", "act"],
}

SYSTEM = (
    "You are the synthesizer for a private investor who is not a trader. You read typed CLAIMS about one market, each with an id, and you write one structured report as JSON. "
    "Rules. (1) Use only claim ids that are listed. (2) Write plain words and never write a number or a date yourself; if a figure is needed, copy it exactly as printed in the claim and list that claim's id in 'claims'. "
    "(3) now: the HEADLINE FACTS (the index move, its parts, breadth, flags, the book, the week) are already written by code; add at most 3 short commentary items that CONNECT them (what ties the week to the day), each with the ids it rests on, and do not repeat the headline. (4) why: cause -> effect pairs of claim ids where the cause is an EARLIER event than the effect and the pair is one of the allowed types (us_close>nse_gap, foreign_flows>index_move, crude>oil_theme_exposure, asia>relative_performance); any other pair is refused; "
    "give the mechanism in words; never link two things from the same day. (5) so_what: what it means for the paper book, using exposure and book claims. "
    "(6) next: for each scenario in the list of SCENARIOS you want to comment on, give its key in 'candidate' and one sentence in 'note'; you cannot change a probability. "
    "(7) act: paper_request (empty if none; one request to the paper team to look into something), agenda (things the system should look into itself: the subject must be the subject of a claim, "
    "e.g. fall_risk_20 or macro_attribution), question (leave it EMPTY unless the answer depends on the investor's own money, goals or limits, never a market question; give a default), "
    "watch (a level to watch: series from the WATCHABLE list, op > or <, claim = the id of that series' level claim, threshold = one of the levels printed in that claim: the last close, the 20-session high or low). "
    "(8) Disagreements between claims are real: never merge them into one story; mention both sides. If the claims do not say, say the data does not say. No advice to trade.")


def thinker_model() -> str:
    """The pick registered for role `thinker` (latest), else the general local model, else qwen3:8b-q8_0."""
    try:
        from pflab.llm import registry
        ps = [p for p in registry.load_picks() if p.get("role") == "thinker" and p.get("model")]
        if ps:
            return max(ps, key=lambda p: str(p.get("registered_at", "")))["model"]
        return registry.chosen("general") or LOCAL_DEFAULT
    except Exception:
        return LOCAL_DEFAULT


def local_chat(system: str, user: str, schema: dict, num_predict: int = 1800) -> str:
    from pflab.llm import client
    r = client.chat(thinker_model(), [{"role": "system", "content": system}, {"role": "user", "content": user}], fmt=schema, num_predict=num_predict, num_ctx=8192,
                    purpose="situation", timeout=900)
    return r.text


def claims_block(claims: List[dict], limit: int = 42, text_chars: int = 190) -> str:
    """One line per claim: [claim id] kind/subject (dated D): text. The most decision-relevant kinds first."""
    order = {k: i for i, k in enumerate(("regime", "wave", "rotation", "macro", "transmission", "move", "sentiment", "forecast", "fall_risk", "implied", "exposure", "book",
                                         "allocation", "weights", "event", "question", "scorecard", "agenda", "state", "observation"))}
    cs = sorted(claims, key=lambda c: (order.get(c["kind"], 99), c["subject"]))[:limit]
    return "\n".join(f"[claim {c['claim_id']}] {c['kind']}/{c['subject']} (dated {c['as_of']}): {c['text'][:text_chars]}" for c in cs)


def prompt(market: str, as_of: date, mode: str, claims: List[dict], contradictions: List[dict], cands: List[dict], watchable: List[str], short: bool,
           headline: Optional[List[dict]] = None) -> str:
    hid = {i for h in (headline or []) for i in h.get("claims", [])}
    rest = [c for c in claims if c["claim_id"] not in hid and not c["subject"].startswith(("leg_", "sector_"))] + [c for c in claims if c["subject"].startswith("leg_")][:3]
    parts = [f"Market {market}. Date {as_of}. Mode {mode}." + (" Short intraday read: keep it to the few items that changed." if short else "")]
    if headline:
        parts.append("HEADLINE FACTS (already written by code; do not repeat):\n" + "\n".join(f"- {h['text']} [claim {', '.join(str(i) for i in h['claims'])}]" for h in headline))
    parts.append("OTHER CLAIMS:\n" + claims_block(rest, 26 if short else 46))
    if contradictions:
        parts.append("DISAGREEMENTS (keep both sides, do not resolve):\n" + "\n".join(
            f"- {c['subject']}: " + " VERSUS ".join(f"{s['side']} [claim {', '.join(str(i) for i in s['claim_ids'])}]" for s in c["explanations"]) for c in contradictions[:5]))
    if cands:
        parts.append("SCENARIOS (probabilities are the tools'; comment only):\n" + "\n".join(f"- {c['key']}: {c['label']}" for c in cands))
    if watchable:
        parts.append("WATCHABLE series (each has a level claim): " + ", ".join(watchable[:30]))
    parts.append("Write the JSON report now. Empty arrays are fine.")
    return "\n\n".join(parts)


# --- the checks ---------------------------------------------------------------------------------------------------------------------------

def evidence_results(by_id: Dict[int, dict], ids: List[int]) -> Dict[int, str]:
    """What the citation check should treat as the text of 'call PSEUDO+id' for each claim id: the claim's text and its value as printed."""
    out = {}
    for i in ids:
        c = by_id.get(i)
        if c:
            out[PSEUDO + i] = c["text"] + (" " + json.dumps(c["value"]) if c.get("value") is not None else "")
    return out


def verify(text: str, ids: List[int], by_id: Dict[int, dict]) -> Tuple[str, List[dict], List[int]]:
    """(clean text, rejected, claim ids used). Sentences without a figure pass; a sentence with a figure needs the cited claims to hold that figure."""
    text = " ".join(str(text or "").split())
    inline = [int(x) for t in re.findall(r"\[claims?\s*([\d,\s]+)\]", text, flags=re.I) for x in re.findall(r"\d+", t)]       # the model often writes its citations in the sentence: they are ids, not figures
    text = " ".join(re.sub(r"\s*\[claims?\s*[\d,\s]+\]", "", text, flags=re.I).split())
    ids = [int(i) for i in list(ids or []) + inline if int(i) in by_id]
    ids = list(dict.fromkeys(ids))
    if not text:
        return "", [], []
    res = evidence_results(by_id, ids)
    tg = f" [call {', '.join(str(PSEUDO + i) for i in ids)}]" if ids else ""
    tagged = " ".join(s.rstrip() + tg if re.search(r"[.!?]$", s.rstrip()) is None else s.rstrip()[:-1] + tg + s.rstrip()[-1] for s in re.split(r"(?<=[.!?])\s+", text) if s.strip())
    clean, rejected, used = explain.check_citations(tagged, res)
    return re.sub(r"\s+([.!?])", r"\1", explain.strip_tags(clean)), rejected, sorted({u - PSEUDO for u in used})


def watch_ok(w: dict, by_id: Dict[int, dict], series_ok: List[str]) -> Tuple[bool, str]:
    c = by_id.get(int(w.get("claim") or -1))
    if c is None:
        return False, "the trigger cites no known claim"
    if w.get("series") not in series_ok:
        return False, f"series {w.get('series')!r} is not watchable"
    if c["subject"] != f"level_{w.get('series')}":
        return False, f"a threshold must come from the level claim of the series (level_{w.get('series')}), not claim {c['claim_id']} ({c['subject']})"
    if w.get("op") not in (">", "<"):
        return False, "op must be > or <"
    try:
        th = float(w["threshold"])
    except (KeyError, TypeError, ValueError):
        return False, "no threshold"
    known = explain.numbers(c["text"] + (" " + json.dumps(c["value"]) if c.get("value") is not None else ""))
    printed = {json.dumps(th), f"{th:g}", str(th).rstrip("0").rstrip(".")}
    if not (printed & known or any(abs(float(k) - abs(th)) < 1e-9 for k in known if re.fullmatch(r"\d+(\.\d+)?", k))):
        return False, f"the threshold {th:g} is not a figure in claim {c['claim_id']}"
    return True, ""


def draft(market: str, as_of: date, mode: str, claims: List[dict], contradictions: List[dict], cands: List[dict], watchable: List[str], short: bool = False,
          chat: Optional[Callable[[str, str, dict], str]] = None, headline: Optional[List[dict]] = None) -> dict:
    """The model's raw draft as a dict, or {'error': why} when the model is not available or its output is not JSON of the schema's shape."""
    chat = chat or local_chat
    try:
        raw = chat(SYSTEM, prompt(market, as_of, mode, claims, contradictions, cands, watchable, short, headline), SCHEMA)
    except Exception as e:                                                      # the model being away is a normal day: the code-written report answers
        return {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    try:
        d = json.loads(raw)
        if not isinstance(d, dict):
            raise ValueError("not an object")
    except ValueError as e:
        return {"error": f"the model did not return JSON ({str(e)[:80]})"}
    for k in ("now", "why", "so_what", "next"):
        if not isinstance(d.get(k), list):
            d[k] = []
    if not isinstance(d.get("act"), dict):
        d["act"] = {}
    return d
