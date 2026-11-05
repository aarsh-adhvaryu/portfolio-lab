"""Playbooks (S71): the plan of a common kind of question, written by code, so the cloud coordinator is not paid to plan what is always planned the same way.

A mission's first task asks the coordinator (Sonnet, about Rs 4) to read the case and call `plan_mission`. For the questions he asks most, the plan is the same
shape every time: verify the premise first, compute his exposure with the reviewed tools, set the idea against evidence AGAINST it and competing explanations,
say what would change the view; add the IPO study when an allotment is the question, the deployment policies when the question is how to put money to work,
the reading of a document when a filing is. `flags` finds which of those the question is about, by words in code; only when no word decides does the local model
choose (a closed list of booleans, checked by code). No flag at all: the coordinator plans, as before. Every playbook plan passes the six structural checks of
`eval/roles.plan_scores` (tested), so a playbook is never a worse-shaped plan than the one Sonnet wrote in the measurement.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

FLAGS = ("shock", "deploy", "ipo", "filing", "review")
WORDS = {
    "shock": r"sell-?off|crash|bubble|burst|plunge|slump|shock|fall(s|ing)?\b|drop(s|ped)?\b|exposed|exposure|ripple|contagion|downturn|recession|war\b|rate (hike|cut)",
    "deploy": r"put (my |the )?(monthly )?(money|sum|amount|savings)|monthly (money|amount|investment)|invest(ing)? (my |the )?(money|sum|bonus|savings|lump)|lump ?sum|"
              r"stagger|phase[ds]? (in|buying)|buy(ing)? the dip|deploy|wait for (a |the )?(dip|fall)|keep (it )?in cash|\bsip\b",
    "ipo": r"\bipo\b|allot(ment|ted)|listing day|listing gain|list(s|ed)? (next|on)",
    "filing": r"\bfiling\b|announcement|results? (were|was|came)|quarterly result|annual report|document|disclosure|order (win|loss)",
    "review": r"re-?visit|review (the |my |our )?(earlier|previous|last)|still (hold|stand)s?|has (it|anything) changed|changed since|update (on|the) (earlier|previous)",
}
SCHEMA = {"type": "object", "properties": {f: {"type": "boolean"} for f in FLAGS}, "required": list(FLAGS)}


def flags_by_words(goal: str) -> Dict[str, bool]:
    return {f: bool(re.search(WORDS[f], goal, re.I)) for f in FLAGS}


def flags_for(goal: str, chat=None) -> Tuple[Dict[str, bool], str]:
    """(flags, how). Words decide when any word applies; otherwise the local model is asked once (booleans only, never a number)."""
    w = flags_by_words(goal)
    if any(w.values()):
        return w, "words"
    from pflab.llm import structured
    r = structured.ask_json(
        "You sort an investor's question into kinds of investigation. Answer with JSON booleans only. shock: a market or sector event, fall or headline risk and what it means for him. "
        "deploy: how or when to put money into shares. ipo: an IPO allotment or listing. filing: a company document or result. review: revisiting an earlier conclusion. "
        "All false if none fits.", f"Question: {goal[:600]}", SCHEMA, lambda o: None if all(isinstance(o.get(f), bool) for f in FLAGS) else "every flag must be true or false",
        purpose="playbook", chat=chat)
    return ({f: bool(r.value[f]) for f in FLAGS}, "local model") if r.ok else ({f: False for f in FLAGS}, "none")


def name_of(fl: Dict[str, bool]) -> str:
    on = [f for f in FLAGS if fl.get(f)]
    return "+".join(on) if on else "none"


def build(goal: str, fl: Dict[str, bool], rec: Optional[dict] = None) -> Tuple[List[dict], str]:
    """The steps (as `plan_mission` takes them) and the approach, for a question and its flags. `rec` is working memory on the subject (kg/memory.recall): a conclusion already
    reached is to be checked, not redone; a calculation already checked is re-run on today's record; evidence that came after the earlier conclusion must be taken up; what was
    left open is carried."""
    q = " ".join(goal.split())[:260]
    steps = [{"key": "premise", "role": "research", "promise": {"evidence": 2}, "depends_on": [],
              "goal": f"Verify what actually happened or is claimed, for this question: {q}. Establish the event, its dates and its size from dated sources, and say what could not be confirmed. "
                      "Never put his holdings or amounts in a web search."}]
    if fl.get("filing"):
        steps.append({"key": "document", "role": "research", "promise": {"evidence": 2}, "depends_on": ["premise"],
                      "goal": f"Read the filing or document this is about and say what it changes, for this question: {q}. Record each finding with its source and the date it was published, "
                              "and check the figures against the document."})
    steps.append({"key": "exposure", "role": "quant", "promise": {"scenario": 1}, "depends_on": ["premise"],
                  "goal": "Compute his exposure with the reviewed tools: the share of his portfolio in the affected area, holding by holding, and the cost of a stated fall over a range of sizes "
                          "(exposure_shock). The falls and sensitivities are stated assumptions, not forecasts; compare against the baseline of doing nothing."})
    if fl.get("deploy"):
        steps.append({"key": "policy", "role": "quant", "promise": {"scenario": 1}, "depends_on": ["premise"],
                      "goal": "Compare ways to put the waiting money to work with policy_scenarios: all at once, his current equal monthly tranches, phased buying with a reserve for a fall, "
                              "and cash until a fall, across a sharp fall, a prolonged decline, a fall and recovery, and no crash. His current monthly approach is the baseline; include costs; "
                              "say which results are hypothetical paths and which are history."})
    if fl.get("ipo"):
        steps.append({"key": "ipo_study", "role": "quant", "promise": {"calc": 1}, "depends_on": ["premise"],
                      "goal": "Run ipo_policy_study: how selling on listing day or holding would have done for large listings since 2016, with selling at the listing close as the baseline. "
                              "Under 20 listings it gives no conclusion; say so. It is history of other companies, not a forecast of this one."})
    changed = (" Also say what has changed since the earlier conclusion on this: new documents, prices and trades, and whether any of them contradicts it."
               if fl.get("review") else "")                   # folded into this step, so a plan never passes six steps
    steps.append({"key": "view", "role": "research", "promise": {"evidence": 1}, "depends_on": ["premise"],
                  "goal": "Look for evidence AGAINST the idea and for competing explanations of what happened; weigh them. Say what would change the view and what would invalidate the "
                          "conclusion, as a price, a date or a document that can be watched." + changed})
    if rec:
        by = {x["key"]: x for x in steps}
        for c in (rec.get("conclusions") or [])[:2]:
            by["premise"]["goal"] += (f" Memory: investigation #{c['case_id']} ({c['at']}) concluded '{c['decision']}': {(c['reason'] or c['answer'])[:160]}. Say whether this still holds on today's facts; "
                                      "do not redo what it established.")
        for m in (rec.get("methods") or [])[:2]:
            if "exposure" in by:
                by["exposure"]["goal"] += f" Memory: a checked {m['tool']} ({m['params']}) exists (calculation #{m['calc_id']}, investigation #{m['case_id']}): re-run it on today's record instead of writing new code."
        extra = "".join(f" Memory: take up this evidence, which came after the earlier conclusion: {x['text'][:160]}." for x in (rec.get("contradictions") or [])[:3])
        extra += "".join(f" Memory: still open from before: {o['what'][:140]}." for o in (rec.get("open") or [])[:3])
        by["view"]["goal"] += extra
    return steps, f"A playbook plan ({name_of(fl)}): verify the premise first, compute his exposure with the reviewed tools, then set the idea against the evidence against it and the competing explanations."


def paper_steps(goal: str) -> Tuple[List[dict], str]:
    """S76: a review of the paper portfolio: what changed (and what he asked) and the ideas worth acting on, researched in parallel with the measures of the book; then
    the quant decides with paper_decide. The review that follows decides what is executed."""
    q = " ".join(goal.split())[:300]
    steps = [
        {"key": "changes", "role": "research", "promise": {"evidence": 2}, "depends_on": [],
         "goal": f"For the paper portfolio ({q}): what has changed for its holdings and for the market since its last review: results, filings, news, prices, from dated sources. "
                 "If the investor asked it to look into something, research that too, with the evidence for and against. Never put amounts in a web search."},
        {"key": "ideas", "role": "research", "promise": {"evidence": 2}, "depends_on": [],
         "goal": "Find a few candidates the paper portfolio does not hold that could serve its long-term aim better than what it holds (listed shares or ETFs, gold included), "
                 "each with dated evidence for it and AGAINST it. A candidate needs a reason, not a story."},
        {"key": "measure", "role": "quant", "promise": {"calc": 1}, "depends_on": [],
         "goal": "Measure the paper portfolio with the reviewed tools (paper_book, stocks_overview, exposure_shock, policy_scenarios): concentration by company and sector, "
                 "valuation of the large holdings, what a market fall would cost it, and how much cash waits. State assumptions; compare with doing nothing."},
        {"key": "decide", "role": "quant", "promise": {"proposal": 1}, "depends_on": ["changes", "ideas", "measure"],
         "goal": "Decide for the paper portfolio with paper_decide: for each holding that needs a decision and each candidate worth acting on, BUY, ADD, REDUCE, SELL, HOLD or WAIT, "
                 "with the evidence, the alternatives and, for HOLD and WAIT, the condition for looking again. Long term (3+ years), after tax and charges; a supported "
                 "HOLD or WAIT is as good as a trade. For an idea worth waiting for, put it on the watchlist with watch_add: a zone, or a fall from the year's high, TAKEN FROM A CALCULATION you name (calc_id), so the system looks again when the price gets there; look at a chart (chart_view) before you decide. If the investor asked something, say plainly whether this follows him or goes against him, and why (his_view)."},
    ]
    try:                                                   # S79 (A45): the system's own allocation target is decided, reviewed and re-examined in the same review
        from pflab.paper import allocation
        steps[-1]["goal"] += " " + allocation.playbook_text()
    except Exception:
        pass
    return steps, "The paper playbook: changes and ideas researched beside the book's measures, then decisions sized by code; the review decides what is executed."


def enabled() -> bool:
    """`[policy] playbooks = "off"` in api_budget.toml sends every plan back to the coordinator."""
    try:
        from pflab.agents import analyst as an
        return str(((an.config().get("policy") or {}).get("playbooks")) or "on").lower() != "off"
    except Exception:
        return True


def try_plan(con, cid: int, coordinator_task: int, now: datetime, chat=None) -> Optional[dict]:
    """Plan the mission from a playbook if the question is of a known kind. Returns {name, how, mission_id} once the plan is stored (the coordinator task is then
    done without a model), else None and the coordinator plans."""
    from pflab.hq import cases, missions
    from pflab.pm.store import next_id
    m = missions.mission_of(con, cid)
    if m is None or m["state"] != "planning":
        return None
    if con.execute("SELECT count(*) FROM hq_tasks WHERE case_id=? AND role IN ('research','quant','review')", [cid]).fetchone()[0]:
        return None                       # not the first plan: an amendment or a reopened review plans only what CHANGES, which takes the coordinator's reading of the case
    if m.get("origin") == "paper":                         # S76: the paper portfolio's review is always the same shape
        steps, approach = paper_steps(m["goal"])
        out = missions.set_plan(con, now, cid, steps, approach)
        if not out.get("stored"):
            return None
        con.execute("INSERT INTO hq_artifacts VALUES (?,?,?,?,?,?,?)",
                    [next_id(con, "hq_artifacts", "artifact_id"), cid, coordinator_task, "plan", str(out["mission_id"]), f"{len(steps)} steps (playbook paper)", now])
        cases.log(con, cid, now, "playbook", "planned from the paper playbook; the coordinator was not asked")
        return {"name": "paper", "how": "origin", "mission_id": out["mission_id"], "steps": len(steps), "memory": False}
    fl, how = flags_for(m["goal"], chat)
    if not any(fl.values()):
        return None
    from pflab.kg import memory
    rec = memory.recall(con, memory.subjects_of(con, m["goal"]), now, exclude_case=cid)
    steps, approach = build(m["goal"], fl, rec)
    out = missions.set_plan(con, now, cid, steps, approach)
    if not out.get("stored"):
        return None
    con.execute("INSERT INTO hq_artifacts VALUES (?,?,?,?,?,?,?)",
                [next_id(con, "hq_artifacts", "artifact_id"), cid, coordinator_task, "plan", str(out["mission_id"]), f"{len(steps)} steps (playbook {name_of(fl)})", now])
    memory.offer(con, now, cid, rec)
    cases.log(con, cid, now, "playbook", f"planned from the playbook {name_of(fl)} (chosen by {how}); the coordinator was not asked"
              + (f"; memory offered {len(rec.get('conclusions', []))} earlier conclusion(s), {len(rec.get('methods', []))} checked method(s)" if rec.get("conclusions") or rec.get("methods") else ""))
    return {"name": name_of(fl), "how": how, "mission_id": out["mission_id"], "steps": len(steps), "memory": bool(rec.get("conclusions") or rec.get("methods"))}
