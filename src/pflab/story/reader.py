"""The local reader (S80 phase 3): the daily dot-connecting step. For each new evidence item the local model (the fast seat, qwen3:8b) answers ONE structured question with a JSON schema:
attach it to an open storyline (for or against, with a strength WORD), open a new storyline (a claim, a direction and signals CHOSEN from the template menu), or ignore it. Three local
samples are taken; when they disagree the item is escalated to Sonnet (the `escalation` share of the cap), inside the cap and only when a client exists, else the plurality local answer
stands. Code validates everything: a model never writes a number (strength words map to numbers in `store.STRENGTH`; signals and thresholds come from `store.TEMPLATES`), cannot
attach to a storyline that is not open, and cannot open one with an invalid claim. No multi-turn local loops; no raw news goes to a cloud prompt (the item is a code-written sentence).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Callable, List, Optional

from pflab.story import store

SYSTEM = ("You connect one new market fact to the market stories being tracked. Answer with the JSON object only. Choose action 'attach' when the fact clearly supports or contradicts "
          "one of the OPEN stories (give its id, stance 'for' or 'against', and a strength word); 'new' only when the fact points to a clear cause-and-effect story none of them covers "
          "(give the claim as one sentence, direction 1 if the Nifty should rise because of it or -1 if it should fall, and 1 to 3 signals from the menu); otherwise 'ignore'. "
          "Do not invent numbers. When unsure, ignore.")


def schema() -> dict:
    return {"type": "object", "properties": {
        "action": {"enum": ["attach", "new", "ignore"]},
        "storyline_id": {"type": ["integer", "null"]},
        "stance": {"enum": ["for", "against"]},
        "strength": {"enum": list(store.STRENGTH)},
        "new_claim": {"type": ["string", "null"], "maxLength": 300},
        "direction": {"enum": [-1, 1]},
        "templates": {"type": "array", "items": {"enum": sorted(store.TEMPLATES)}, "maxItems": 3}},
        "required": ["action"], "additionalProperties": False}


def prompt(item: dict, open_stories: List[dict]) -> str:
    stories = "\n".join(f"- #{s['storyline_id']} ({'up' if s['direction'] > 0 else 'down'}): {s['claim']}" for s in open_stories) or "(none open)"
    menu = "\n".join(f"- {k}: {v[6]}" for k, v in sorted(store.TEMPLATES.items()))
    return f"OPEN STORIES:\n{stories}\n\nSIGNAL MENU (for a new story):\n{menu}\n\nNEW FACT ({item['date']}, source {item['source_ref']}): {item['text']}"


def validate_for(open_ids: set) -> Callable[[dict], Optional[str]]:
    def v(a: dict) -> Optional[str]:
        if a["action"] == "attach":
            if a.get("storyline_id") not in open_ids:
                return f"storyline_id must be one of the open stories {sorted(open_ids)}"
            if "stance" not in a or "strength" not in a:
                return "attach needs stance and strength"
        if a["action"] == "new":
            if not a.get("new_claim") or "direction" not in a or not a.get("templates"):
                return "new needs new_claim, direction and 1 to 3 templates"
        return None
    return v


def _key(a: dict) -> tuple:
    if a["action"] == "attach":
        return ("attach", a.get("storyline_id"), a.get("stance"))
    if a["action"] == "new":
        return ("new", a.get("direction"), tuple(sorted(a.get("templates") or [])))
    return ("ignore",)


def agree(answers: List[dict]) -> bool:
    return len({_key(a) for a in answers}) == 1


def decide_item(con, item: dict, now: datetime, *, chat: Optional[Callable] = None, cloud_fn: Optional[Callable] = None, cap_ok: Optional[Callable] = None, seat: str = "fast") -> dict:
    """The reader's decision for one item: {answer, rule, outcome, ...} from `llm.escalate.decide`."""
    from pflab.llm import constrained, escalate
    open_stories = store.listing(con, ("open",))
    sch, val = schema(), validate_for({s["storyline_id"] for s in open_stories})
    text = prompt(item, open_stories)

    def local(i: int):
        r = constrained.generate(SYSTEM, text, sch, val, purpose="storyline_reader", seat=seat, num_predict=260, num_ctx=4096, chat=chat)
        if r.ok:
            return r.value
        if re.match(r"^\w*(Error|Exception|Timeout)\b", r.error or ""):          # the model could not be reached (down, busy): no answer, the item stays unread
            return None
        return {"action": "ignore"}                                              # it answered, but not validly twice running: when unsure, ignore

    return escalate.decide(local, samples=3, agree_fn=agree, cloud_fn=cloud_fn, cap_ok=cap_ok, con=con, market="IN", kind="storyline", subject=item["key"], now=now, seat=seat)


def apply(con, now: datetime, item: dict, res: dict, by: str = "local reader") -> dict:
    """Carry out the decision, through the same validators every other path uses. Returns what was done."""
    a = res.get("answer") or {"action": "ignore"}
    if a["action"] == "attach":
        r = store.add_evidence(con, now, int(a["storyline_id"]), item["date"], a["stance"], item["text"], item["source_kind"], item["source_ref"], a["strength"], by)
        return {"did": "attach", "storyline_id": a["storyline_id"], **{k: v for k, v in r.items() if k in ("ok", "problem", "duplicate")}}
    if a["action"] == "new":
        r = store.open_storyline(con, now, a["new_claim"], int(a["direction"]), item["date"], list(a["templates"]), kind="market", created_by=by)
        if r.get("ok"):
            store.add_evidence(con, now, r["storyline_id"], item["date"], "for", item["text"], item["source_kind"], item["source_ref"], "moderate", by)
            return {"did": "new", "storyline_id": r["storyline_id"]}
        return {"did": "refused", "problem": r.get("problem")}
    return {"did": "ignore"}


def process(con, now: datetime, items: List[dict], *, chat=None, cloud_fn=None, cap_ok=None, limit: int = 40) -> dict:
    """Read each item not read before (at most `limit` a day), record it, apply it. The reader's own cost line is local (free) unless an escalation went to the cloud."""
    done = {r[0] for r in con.execute("SELECT item_key FROM storyline_reader_s80").fetchall()}
    out = {"read": 0, "attached": 0, "new": 0, "ignored": 0, "escalated": 0, "refused": 0, "cost_rupees": 0.0, "unavailable": 0}
    for it in items:
        if it["key"] in done or out["read"] >= limit:
            continue
        res = decide_item(con, it, now, chat=chat, cloud_fn=cloud_fn, cap_ok=cap_ok)
        if res.get("rule") == "local_unavailable" and not res.get("cloud_used"):       # the local model could not answer (down, busy): the item is NOT marked read; try again next run
            out["unavailable"] += 1
            break
        did = apply(con, now, it, res)
        con.execute("INSERT OR REPLACE INTO storyline_reader_s80 VALUES (?,?,?,?,?,?,?)", [it["key"], now, did["did"], did.get("storyline_id"), res.get("rule"), res.get("outcome"), float(res.get("cost_rupees") or 0.0)])
        out["read"] += 1
        out[{"attach": "attached", "new": "new", "ignore": "ignored", "refused": "refused"}[did["did"]]] += 1
        out["escalated"] += 1 if res.get("cloud_used") else 0
        out["cost_rupees"] += float(res.get("cost_rupees") or 0.0)
    return out


def cloud_fn_for(con, client, now: datetime, item_provider: Callable[[], dict], gate=None, cfg=None) -> Callable:
    """The Sonnet escalation for a disagreement: one request, the same schema, the same validators (the answer is parsed as JSON and checked by `constrained.check`). It goes through
    `hq/llm.call` as the agent `escalation` (priced first, egress-checked, logged); the item is a code-written sentence, never raw news."""
    def fn(valid: List[dict], rule: str):
        from pflab.agents import analyst as an
        from pflab.hq import egress, governor as gv, llm
        from pflab.llm import constrained
        item = item_provider()
        open_stories = store.listing(con, ("open",))
        txt = prompt(item, open_stories) + f"\n\nThe local reader's samples disagreed ({rule}): {json.dumps(valid)[:600]}\nReply with the JSON object only."
        p = {"model": gv.SONNET, "max_tokens": 400, "system": [{"type": "text", "text": SYSTEM}], "messages": [{"role": "user", "content": [{"type": "text", "text": txt}]}]}
        s = llm.call(con, "escalation", p, client, now=now, mode="normal", private_text=txt, gate=gate or egress.load(con), topic="storyline escalation", question=item["key"], cfg=cfg or an.config())
        obj = llm.json_of(llm.text_of(s.message))
        bad = constrained.check(obj, schema()) or validate_for({x["storyline_id"] for x in open_stories})(obj)
        if bad:
            raise ValueError(f"the escalated answer was refused: {bad}")
        return {"answer": obj, "cost_rupees": s.cost_inr}
    return fn
