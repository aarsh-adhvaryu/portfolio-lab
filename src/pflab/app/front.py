"""The chat front (S71): the local model takes the first turn of the conversation, and the conversation is still the way into the whole system.

The chat is not a question-and-answer box. Behind it is an agent that starts investigations, answers the plan that waits for his yes, changes an instruction
that is already running, runs a calculation, keeps what he tells it. The cloud agent (`app/assistant.answer`, Sonnet with the full tool set) does all of that and
costs a call for every turn. Most turns are one of a few things, so the local model is the FRONT: it recognises which, and does it through the SAME tools, with the
same checks (`hq/tools.run`: the allowed list, redaction, the journal, his own words checked by code for a yes or an acceptance). What it is not sure of, or what is
open-ended, goes to the cloud agent unchanged: nothing the cloud agent could do is lost, it just is not asked first.

    classify   words first (a bare yes while exactly one plan waits; "what is running"), else the local model chooses one intent from a closed list with a confidence
    act        the intent is carried out by tool calls; the numbers in the reply come from the tool results (code), and the local model only words them
    word       a reply the local model wrote is kept only if every number in it is in the tool results or in his message (`llm/guard.check_numbers`); else the cloud agent
    fall back  unsure, below the confidence bar, a precondition not met (two plans waiting and a bare yes), a tool refusing, the model unreachable: the cloud agent

What it never does by itself: a trade, a change of target or limit, a rule (those need his words checked by the tool, or his yes). The confidence bar is higher for
anything that changes state than for what only reads.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Dict, List, Optional

READ_BAR, ACT_BAR = 0.7, 0.85
# What the local model may DO when it is the model that chose the intent (measured, docs/protocols/s71_front_protocol.md): on 40 labelled messages its stated
# confidence was 0.95-1.00 even when wrong ("Sell all my Acme now" as a decline, "Raise my equity target to 60%" as an amendment, an open question as a new
# investigation), so confidence is no safety signal. An intent stays on only where the message itself can be checked by code: a yes must be a clear yes
# (decide_plan), a fall needs a percentage in his words, a deployment a sum, a note cannot be a question, a trade or a target change. `start`, `amend` and a
# model-chosen `decline` scored 57%, 80% and 67% precision and nothing in the message can verify them: they stay with the cloud agent, which judges them
# with the whole conversation. A bare yes or no while exactly one plan waits is decided by words, not by the model, and is not affected by this list.
ENABLED = ("status", "portfolio", "approve", "fall", "deploy", "remember")
INTENTS = ("status", "portfolio", "approve", "decline", "start", "amend", "fall", "deploy", "remember", "other")
ACTING = ("approve", "decline", "start", "amend", "fall", "deploy", "remember")
SCHEMA = {"type": "object", "properties": {"intent": {"type": "string", "enum": list(INTENTS)}, "confidence": {"type": "number"}}, "required": ["intent", "confidence"]}
SYSTEM = (
    "You sort what an investor types into his portfolio assistant into ONE intent. You only choose; you never answer. Intents: "
    "status = asks what is running, what is stuck, what needs him, whether everything works. "
    "portfolio = asks what he holds, what it is worth, the allocation, a holding's weight or gain. "
    "approve = says yes to a plan that waits for his approval. decline = says no to it. "
    "start = asks the system to investigate or research something that needs real work (a risk, a strategy, an IPO decision, a company), in a sentence or more. "
    "amend = changes or adds to an investigation that is already running or finished (also do X, use Y instead, redo it with, ignore Z). "
    "fall = asks what a stated fall of the market or a sector (a percentage) would cost his portfolio. "
    "deploy = asks how to put a stated sum of money into shares (all at once, in parts, wait for a dip). "
    "remember = tells the assistant a fact, goal or preference to keep, with no question. "
    "other = anything else: an open question, a discussion, a request you are not sure of. When unsure choose other. "
    "Answer with JSON {intent, confidence} where confidence is 0 to 1.")
_YES = re.compile(r"^\s*(yes|yep|yeah|y|ok(ay)?|sure|approve[d]?|approved|go ahead|do it|start( it)?|proceed|please do|looks good|go)\W*$", re.I)
_NO = re.compile(r"^\s*(no|nope|decline|reject|cancel|not now|don'?t( start)?|do not( start)?)\W*$", re.I)
_TRADE = re.compile(r"^\s*(please\s+)?(buy|sell|place|transfer|withdraw|exit|book|short|square)\b", re.I)
_MINE = re.compile(r"\b(target|limit|cap|allocation|allocate|stock ?list|watch ?list|gtt|order|transfer|withdraw|rebalance)\b", re.I)
_STATUS = re.compile(r"^\s*(what('?s| is| are) (running|happening|going on|stuck|waiting|the status|you (doing|working on))|status|any (news|updates?)|what needs me|"
                     r"anything (waiting|for me)|is everything (working|ok|fine|okay)|how('?s| is) (it|everything|the system) (going|doing|working))\b", re.I)


def awaiting(con) -> List[dict]:
    """The plans that wait for his yes: [{case_id, goal, version}]."""
    from pflab.hq import missions, plans
    out = []
    for (cid, goal) in con.execute("SELECT case_id, goal FROM hq_missions WHERE state = 'awaiting_approval' ORDER BY case_id").fetchall():
        w = plans.waiting(con, cid)
        if w:
            out.append({"case_id": int(cid), "goal": goal, "version": w["version"]})
    return out


def investigations(con, limit: int = 6) -> List[dict]:
    return [{"case_id": int(c), "goal": g, "state": s} for (c, g, s) in con.execute(
        "SELECT case_id, goal, state FROM hq_missions WHERE state <> 'declined' ORDER BY case_id DESC LIMIT ?", [limit]).fetchall()]


def classify(con, q: str, last_ai: str = "", chat=None) -> Dict[str, object]:
    """{intent, confidence, how}. Words decide the plain cases; otherwise the local model chooses from the closed list."""
    wait = awaiting(con)
    if len(wait) == 1 and _YES.match(q) and re.search(r"plan|approve|go ahead|say yes|nothing runs", last_ai or "", re.I):
        return {"intent": "approve", "confidence": 1.0, "how": "words"}
    if len(wait) == 1 and _NO.match(q) and re.search(r"plan|approve|go ahead|say yes|nothing runs", last_ai or "", re.I):
        return {"intent": "decline", "confidence": 1.0, "how": "words"}
    if _STATUS.match(q):
        return {"intent": "status", "confidence": 1.0, "how": "words"}
    return ask_model(q, len(wait), len(investigations(con)), chat)


def ask_model(q: str, n_waiting: int, n_investigations: int, chat=None) -> Dict[str, object]:
    """The local model's choice of intent (the part `tools/s71_eval.py` measures on a labelled set)."""
    from pflab.llm import structured
    state = (f"{n_waiting} plan(s) wait for his yes. " if n_waiting else "No plan waits for his yes. ") + f"{n_investigations} investigation(s) exist."
    r = structured.ask_json(SYSTEM, f"{state}\nHe typed: {q[:600]}", SCHEMA,
                            lambda o: None if o.get("intent") in INTENTS and isinstance(o.get("confidence"), (int, float)) and 0 <= o["confidence"] <= 1
                            else "intent must be one of the list and confidence a number from 0 to 1", purpose="front", chat=chat)
    if not r.ok:
        return {"intent": "other", "confidence": 0.0, "how": f"unavailable: {r.error}"}
    return {"intent": r.value["intent"], "confidence": float(r.value["confidence"]), "how": "local model"}


# --- code that reads his words ---------------------------------------------------------------------------------------------------

def percents(q: str) -> List[float]:
    """The falls he named, in percent (from his own text only; a number the model made up cannot get in)."""
    return [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*(?:%|per ?cent|percent)", q, re.I) if 0 < float(x) <= 90][:4]


def rupees(q: str) -> Optional[float]:
    """A sum of money in his words: 50k, 50,000, Rs 5 lakh, 1.5 crore."""
    for m in re.finditer(r"(?:rs\.?|₹|inr)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(k|thousand|lakhs?|lacs?|crores?|cr|million)?\b", q, re.I):
        n = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        mult = {"k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7, "million": 1e6}.get(unit, 1.0)
        v = n * mult
        if v >= 1000 and not re.match(r"\s*(%|per ?cent|percent|months?|years?|days?)", q[m.end():m.end() + 10], re.I):
            return v
    return None


# --- acting through the same tools -----------------------------------------------------------------------------------------------

class Run:
    """One turn: a tool context for the assistant role with the local model as its 'model', the tool calls made, and what they said."""

    def __init__(self, rt, con, q: str):
        from pflab.app import assistant
        from pflab.hq import brain, service, tools as tl
        self.rt, self.con, self.q, self.now = rt, con, q, rt.clock()
        self.pid = brain._record(con, self.now, "assistant", [], "local", "assistant", "running")
        self.ctx = tl.Ctx(rt, self.pid, "local", False, {}, service.gate(rt), self.now, client=None, mode=rt.settings.get("brain", "economy"), source=q, case_ids=[],
                          task_id=None, role="assistant", allowed=frozenset(n for n in assistant.TOOLS if n in tl.TOOLS), his_text=q)
        self.steps: List[str] = []
        self.texts: Dict[str, str] = {}

    def call(self, name: str, args: dict):
        from pflab.hq import tools as tl
        text, err = tl.run(self.ctx, name, args, 1)
        self.steps.append(name)
        self.texts[name] = text
        if err:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return {"text": text}

    def close(self, text: str) -> None:
        from pflab.hq import brain
        brain._close(self.con, self.pid, "done", text[:2000], self.ctx.decisions, 0.0, None, None)


def explain(q: str, rendered: str, chat=None) -> Optional[str]:
    """A short plain-words paragraph on what the (code-made) facts mean for him, by the local model, kept only if every number in it is in those facts or in his message.
    None when the model cannot be reached or twice writes a number that is not there: the exact facts then stand alone."""
    from pflab.llm import client, guard, registry
    chat = chat or client.chat
    facts = {"facts": rendered, "his message": q}
    model = registry.chosen("general") or "qwen3:8b-q8_0"
    prompt = (f"HIS QUESTION: {q[:400]}\n\nFACTS (exact, from the system):\n{rendered[:3500]}\n\nIn at most 60 words, say what this means for him, as a capable colleague: what stands out, "
              "what to keep in mind. Do not repeat the list. Use ONLY numbers that appear in FACTS, exactly as written; do not add, subtract or round. If a fall or a path is "
              "an assumption, say so. No advice to buy or sell.")
    why = ""
    for _ in range(2):
        try:
            draft = chat(model, [{"role": "system", "content": "You are the assistant of a private investor's portfolio system in India. You never trade."},
                                 {"role": "user", "content": prompt + why}], num_predict=300, num_ctx=8192, purpose="front").text.strip()
        except Exception:
            return None
        res = guard.check_numbers(draft, facts)
        if draft and res.ok:
            return draft
        why = "\n\nYour draft was rejected: " + "; ".join(f"{v.kind}: {v.text}" for v in res.violations[:4]) + ". Rewrite it using only numbers that are in FACTS."
    return None


def reply(q: str, rendered: str, chat=None, tail: str = "", words: bool = True) -> Optional[str]:
    """The exact facts, then (if asked for and the model's paragraph passes the guard) what they mean, labelled as the local model's wording. No facts, no reply:
    the cloud agent answers. `words=False` for a status or the portfolio: the first real run showed the model misreading "8 thing(s) down" as "NIFTY 50 and BANK NIFTY
    are down 8", a mistake the number guard cannot see, and those facts need no paraphrase."""
    if not rendered.strip():
        return None
    para = explain(q, rendered, chat) if words else None
    return rendered + (f"\n\nIn plain words (written by the local model; the figures above are the exact ones): {para}" if para else "") + tail


# --- the handlers ----------------------------------------------------------------------------------------------------------------

def _status(r: Run, chat) -> Optional[str]:
    from pflab.app import front_render as fr
    return reply(r.q, fr.status(r.call("work_status", {}), r.call("system_status", {})), chat, words=False)


def _portfolio(r: Run, chat) -> Optional[str]:
    from pflab.app import front_render as fr
    return reply(r.q, fr.portfolio(r.call("portfolio", {})), chat, words=False)


def _decide(r: Run, decision: str) -> Optional[str]:
    wait = awaiting(r.con)
    if len(wait) != 1:
        return None
    out = r.call("decide_plan", {"case_id": wait[0]["case_id"], "decision": decision})
    goal = wait[0]["goal"][:140]
    if decision == "approve":
        return f"Approved. The workers are starting on \"{goal}\"; I will tell you when it is done." if out and out.get("approved") is True else None
    return f"Declined. Nothing will run for \"{goal}\"." if out and out.get("declined") is True else None


def _start(r: Run) -> Optional[str]:
    if len(r.q.split()) < 6 or _TRADE.match(r.q):
        return None
    out = r.call("start_investigation", {"goal": r.q[:900]})
    if not out or "case_id" not in out:
        return None
    if out.get("new") is False:
        return f"That is already being investigated (investigation #{out['case_id']}); I will not start it twice."
    return (f"I have started investigation #{out['case_id']}: \"{r.q[:160]}\". It plans first and shows you the plan; nothing runs and nothing costs until you say yes. "
            "A standard investigation is limited to Rs 80.")


def _amend(r: Run, chat) -> Optional[str]:
    from pflab.llm import structured
    if _TRADE.match(r.q) or _MINE.search(r.q):
        return None                                        # a change to his targets or limits, or a trade, is not an instruction to an investigation
    cands = [i for i in investigations(r.con) if i["state"] not in ("blocked",)]
    if not cands:
        return None
    if len(cands) == 1:
        cid = cands[0]["case_id"]
    else:
        listing = "\n".join(f"- case {c['case_id']}: {c['goal'][:140]}" for c in cands)
        res = structured.ask_json("You choose which investigation a message adds to. Answer {case_id, confidence} only; case_id null if none or unsure.",
                                  f"Investigations:\n{listing}\n\nHe typed: {r.q[:500]}",
                                  {"type": "object", "properties": {"case_id": {"type": ["integer", "null"]}, "confidence": {"type": "number"}}, "required": ["case_id", "confidence"]},
                                  lambda o: None if o.get("case_id") is None or o.get("case_id") in [c["case_id"] for c in cands] else "case_id is not in the list",
                                  purpose="front", chat=chat)
        if not res.ok or res.value.get("case_id") is None or float(res.value.get("confidence", 0)) < ACT_BAR:
            return None
        cid = int(res.value["case_id"])
    money = bool(re.search(r"rs\.?\s*\d|₹|\b\d[\d,]*\s*(k|lakh|crore)\b|\blimit|\bcap\b|\bamount\b|per month|monthly", r.q, re.I))
    out = r.call("amend_investigation", {"case_id": cid, "instruction": r.q[:900], "scope_change": True, "financial_policy": money})
    if not out or out.get("amended") is not True:
        return f"That instruction is already recorded on investigation #{cid}." if out and out.get("duplicate") else None
    return (f"Recorded as the next instruction for investigation #{cid}. " + ("It changes what is being asked, so it waits for your yes before the workers act: say approve. "
            if out.get("needs_approval") else "The workers will replan only what changes. ") + "You can see the numbered versions on its card.")


def _fall(r: Run, chat) -> Optional[str]:
    from pflab.app import front_render as fr
    falls = percents(r.q)
    if not falls:
        return None
    ws = r.call("open_workspace", {"topic": r.q[:150]})
    if not ws or "case_id" not in ws:
        return None
    out = r.call("exposure_shock", {"case_id": int(ws["case_id"]), "falls_json": json.dumps(falls), "why": r.q[:150]})
    return reply(r.q, fr.fall(out), chat, "\n\nKept as a reproducible calculation; an independent reviewer can rerun it.")


def _deploy(r: Run, chat) -> Optional[str]:
    from pflab.app import front_render as fr
    amount = rupees(r.q)
    if not amount:
        return None
    ws = r.call("open_workspace", {"topic": r.q[:150]})
    if not ws or "case_id" not in ws:
        return None
    args = {"case_id": int(ws["case_id"]), "why": r.q[:150], "amount": amount}
    fp = percents(r.q)
    if fp:
        args["fall_pct"] = max(3.0, min(60.0, fp[0]))
    out = r.call("policy_scenarios", args)
    return reply(r.q, fr.deploy(out), chat, "\n\nThese are made-up price paths with your sum, not forecasts; the numbers are kept as a reproducible calculation.")


def _remember(r: Run) -> Optional[str]:
    if "?" in r.q or len(r.q.split()) < 4 or _TRADE.match(r.q) or _MINE.search(r.q):
        return None                                        # a trade, or a change to his targets, limits or lists, is for the cloud agent and his yes: never a note
    kind = "goal" if re.search(r"\bgoal\b|\bI want\b|\bI'?d like\b|\bplan to\b|\baim\b", r.q, re.I) else "note"
    out = r.call("remember_fact", {"kind": kind, "text": r.q[:500]})
    return None if not out else f"Kept as a {kind}, in your words: \"{r.q[:200]}\". (Standing rules that change how the agents work arrive in the next release; today it is a note every agent reads.)"


def try_local(rt, con, cid: int, aid: int, q: str, context: str = "", chat=None) -> Optional[dict]:
    """The local front's reply as the same dict `assistant.answer` returns, or None when the cloud agent should answer. Never raises."""
    try:
        last = con.execute("SELECT text FROM chat_messages WHERE chat_id=? AND role='ai' AND msg_id < ? AND status='done' ORDER BY msg_id DESC LIMIT 1", [cid, aid]).fetchone()
        c = classify(con, q, last[0] if last else "", chat)
        bar = ACT_BAR if c["intent"] in ACTING else READ_BAR
        if c["intent"] == "other" or c["confidence"] < bar or (c["how"] != "words" and c["intent"] not in ENABLED) or not precheck(q, c["intent"]):
            return None
        r = Run(rt, con, q)
        try:
            text = {"status": lambda: _status(r, chat), "portfolio": lambda: _portfolio(r, chat), "approve": lambda: _decide(r, "approve"), "decline": lambda: _decide(r, "decline"),
                    "start": lambda: _start(r), "amend": lambda: _amend(r, chat), "fall": lambda: _fall(r, chat), "deploy": lambda: _deploy(r, chat),
                    "remember": lambda: _remember(r)}[c["intent"]]()
        except Exception:
            text = None
        r.close(text or "")
        if not text:
            return None                                    # the tools may have run (their journal rows are kept), but he gets the cloud agent's answer
        return {"text": text, "route": ["local model"] + [f"tool: {s}" for s in r.steps], "cost": 0.0, "status": "done",
                "meta": f"local front · {c['intent']} ({c['how']}, {c['confidence']:.2f}) · {len(r.steps)} tool call(s) · no cloud cost"}
    except Exception:
        return None


def enabled() -> bool:
    """`[policy] local_front = "off"` in api_budget.toml sends every message to the cloud agent, as before S71."""
    try:
        from pflab.agents import analyst as an
        from pflab.app import settings as st
        return str(((an.config().get("policy") or {}).get("local_front")) or "on").lower() != "off" and st.ability("local_first")      # S78: also his switch in Settings
    except Exception:
        return True


def precheck(q: str, intent: str) -> bool:
    """The code checks on HIS WORDS that must hold before an intent the model chose is acted on (the model cannot override them): a note is a statement, not a question,
    a trade or a change to his targets, limits or lists; a fall needs a percentage he wrote; a deployment needs a sum he wrote. `tools/s71_eval.py` measures through this."""
    if intent == "remember":
        return not ("?" in q or len(q.split()) < 4 or _TRADE.match(q) or _MINE.search(q))
    if intent == "fall":
        return bool(percents(q))
    if intent == "deploy":
        return rupees(q) is not None
    if intent in ("start", "amend"):
        return len(q.split()) >= 4 and not (_TRADE.match(q) or _MINE.search(q))
    return True
