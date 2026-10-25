"""S56 escalation chain (PLAN A8): one question goes local -> agents -> Opus, and every step says why it moved on.

    1 local     the ask centre: read-only tools and the local model through the guard. A checked answer about the investor's
                own portfolio ends here. His own data never goes further: a portfolio question that the local model
                cannot word is answered with the facts themselves.
    2 agents    a calculation goes to the workshop (Opus writes code from the data layout, it runs on this PC on the
                real rows, a second method must agree); a company question first looks for an analyst note on the same
                topic from the last 14 days (free, reused).
    3 Opus      company and market questions go through the doorbell (public documents only, the egress gate, priced
                first against the investor's cap); a question about the outside world (an IPO, a rule, a product, a price
                outside our data) goes to Opus with web search, its pages cited.

The kind of a question is decided by fixed rules on its words and the companies it names (no model), so the same
question always takes the same road. Spending stays inside the doorbell: above `ask_above` it waits for his yes.
S62 (PLAN A20): a judgement on his own portfolio or a name on his list ("should I", "am I too heavy in", "what next")
goes first to the brain with its tools (the AI centre's Auto mode and Telegram pass it in as `fns["brain"]`); a basic
fact stays with the local model, then Haiku (the answer chain); with the brain off or failing, the old road answers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

CALC = re.compile(r"\b(calculat\w*|compute|how (much|many|long|often)|what if|cagr|averag\w*|median|correlat\w*|largest|"
                  r"smallest|biggest|worst|best|since|between|compare|ratio|percent(age)?|drawdown|volatil\w*|beta|"
                  r"annuali[sz]ed|return(s)? (over|from|since)|times did|number of)\b", re.I)
OWN = re.compile(r"\b(my|mine|i (own|hold|have|bought|sold)|portfolio|holdings?|net ?worth|fds?|fixed deposits?|tax|"
                 r"targets?|allocation|bucket|ledger|cash)\b", re.I)
WEB = re.compile(r"\b(ipo|gmp|grey market|rbi|sebi|nse circular|budget|policy|fed|us market|nasdaq|s&p|dow|crude|"
                 r"tijori|screener|zerodha|kite|quicko|gift city|lrs|subscription|pricing|plans? of|regulation|rule|"
                 r"latest|today'?s news|this week)\b", re.I)
COMPANY = re.compile(r"\b(why|news|result\w*|outlook|business|risk\w*|happen\w*|fell|rose|drop\w*|jump\w*|guidance|"
                     r"management|order\w*|deal|acquisition|merger|filing\w*|announce\w*|sector|competit\w*|thesis)\b", re.I)
# S62 (PLAN A20): judgement on his own portfolio or a name he holds or lists goes to the brain with its tools
INSIGHT = re.compile(r"\b(should|shall i|worth (it|buying|holding|adding|selling|keeping)|advi[cs]e|recommend\w*|"
                     r"suggest\w*|what do you think|opinion|concern\w*|worr\w*|rebalanc\w*|good idea|bad idea|better off|"
                     r"improve|mistake\w*|strateg\w*|how am i doing|on track|too (much|little|many|few|heavy|light)|"
                     r"heavy in|concentrat\w*|overweight|underweight|diversif\w*|"
                     r"what next|what now|next step\w*|what would you do|is it (time|wise|safe))\b", re.I)


@dataclass
class Step:
    who: str
    outcome: str
    why: str
    cost: float = 0.0


@dataclass
class Result:
    question: str
    kind: str                       # own | calc | company | outside
    text: str
    steps: List[Step] = field(default_factory=list)
    status: str = "done"            # done | needs_approval | failed
    report: Optional[str] = None    # the analyst note's graph id
    cost: float = 0.0


def kind_of(q: str, isins: List[str]) -> str:
    """insight (judgement on his portfolio or a name on his list), own (a fact of his portfolio), calc (a calculation),
    company (a named company's story), outside (the world beyond our data)."""
    if INSIGHT.search(q) and (OWN.search(q) or isins):
        return "insight"
    if CALC.search(q) and not COMPANY.search(q):
        return "calc"
    if isins and (COMPANY.search(q) or not OWN.search(q)):
        return "company"
    if OWN.search(q):
        return "own"
    if WEB.search(q):
        return "outside"
    return "calc" if CALC.search(q) else "own"


def run(con, q: str, asof: date, *, pm_dir: Path, root: Path, secrets=None, approved: bool = False,
        now: Optional[datetime] = None, fns: Optional[Dict[str, Callable]] = None) -> Result:
    """The chain for one question. `fns` replaces a step's function in tests (local, workshop, note, deep, web)."""
    from pflab.agents import analyst as an
    now = now or datetime.now()
    f = {**_defaults(), **(fns or {})}
    req = an.deep_request(con, q, asof)
    kind = kind_of(q, req.isins)
    res = Result(q, kind, "")

    # 0 the brain (S62, PLAN A20): judgement needs its tools; a basic fact stays local --------------------------------
    if kind == "insight":
        b = None
        if "brain" in f:
            try:
                b = f["brain"](q)
            except Exception as e:
                b = {"ok": False, "text": f"{type(e).__name__}: {str(e)[:200]}"}
        if b and b.get("ok"):
            res.cost = float(b.get("cost") or 0.0)
            res.steps.append(Step("brain (tools; never trades)", "answered",
                                  "a judgement on your portfolio: the brain looked with its tools", res.cost))
            res.text = b["text"]
            return res
        res.steps.append(Step("brain", "not asked" if b is None else "no answer",
                              "the brain is not wired here" if b is None else b.get("text", "")[:200]))
        kind = res.kind = "own"                                  # the facts, local first, as before

    # 1 local -------------------------------------------------------------------------------------------------------
    a = f["local"](con, q, asof)
    tools = ", ".join(a.tools)
    if a.verified:
        res.steps.append(Step(f"local ({tools})", "checked answer", "the local model's answer passed the guard"))
        if kind in ("own", "calc") or (kind == "company" and not COMPANY.search(q)):
            res.text = a.text
            return res
        why = {"company": "a company's story needs its filings and news read, which the local tools only list",
               "outside": "the question is about the world outside our data"}.get(kind, "")
        res.steps[-1].why += f"; going further: {why}"
    else:
        res.steps.append(Step(f"local ({tools})", "no checked answer",
                              "the local model could not word an answer that passes the guard"))
        if kind == "own":
            res.text = a.text
            res.steps.append(Step("stop", "facts shown", "it is about your own portfolio: your data does not leave "
                                                        "this PC, so the facts are the answer"))
            return res
    local_text = a.text

    # 2 agents ------------------------------------------------------------------------------------------------------
    if kind == "calc":
        try:
            w = f["workshop"](con, q, pm_dir, root, asof, secrets=secrets, approved=approved, now=now)
        except Exception as e:
            res.steps.append(Step("workshop", "failed", f"{type(e).__name__}: {str(e)[:200]}"))
            res.text, res.status = local_text, "failed"
            return res
        from pflab.agents import workshop as wk
        ok = w.status == "checked"
        res.steps.append(Step(f"workshop ({w.writer or 'no writer'} writes the code; it runs on this PC)",
                              "checked by a second method" if ok else w.status,
                              "a calculation the tools do not have: written as code from the data layout, never the rows"))
        res.text = wk.render(w)
        res.status = "done" if ok else "failed"
        return res
    if kind == "company":
        old = f["note"](con, req, now)
        if old:
            res.steps.append(Step("analyst note (reused)", f"note of {old[1]:%Y-%m-%d}",
                                  "the same question on this company was answered in the last 14 days: not bought twice"))
            res.text = f"{old[2]}"
            return res
        res.steps.append(Step("analyst note", "none recent", "no note on this question in the last 14 days"))

    # 3 Opus --------------------------------------------------------------------------------------------------------
    use = "web" if kind == "outside" else "deep"
    who = "Opus with web search" if use == "web" else "Opus deep research (public documents)"
    try:
        o = f[use](con, req, q, secrets=secrets, approved=approved, now=now)
    except an.NotAdopted as e:
        res.steps.append(Step(who, "off", str(e)))
        res.text, res.status = local_text, "failed"
        return res
    except an.NeedsApproval as e:
        res.steps.append(Step(who, "waits for your yes", str(e)))
        res.text, res.status = f"{e}. Press 'Approve and send' to go ahead.\n\nMeanwhile, the local facts:\n{local_text}", \
            "needs_approval"
        return res
    except an.BudgetRefused as e:
        res.steps.append(Step(who, "not sent", str(e)))
        res.text, res.status = f"Not sent: {e}.\n\n{local_text}", "failed"
        return res
    res.cost = float(o.cost_inr or 0.0)
    if o.status in ("blocked", "refused"):
        res.steps.append(Step(who, o.status, o.text[:200]))
        res.text, res.status = f"{o.text}\n\nThe local facts instead:\n{local_text}", "failed"
        return res
    res.steps.append(Step(who, o.status, "egress check passed: public question only" if o.status != "reused" else
                          "a recent note answered it", res.cost))
    res.text = o.text + "".join(f"\n\nNote: {w}" for w in o.warnings)
    if o.call_id is not None:
        row = con.execute("SELECT note_doc FROM api_calls WHERE call_id=?", [o.call_id]).fetchone()
        res.report = row[0] if row else None
    return res


def _defaults() -> Dict[str, Callable]:
    from pflab.agents import analyst as an
    from pflab.agents import centre
    from pflab.agents import workshop as wk

    def deep(con, req, q, *, secrets, approved, now):
        return an.ring(con, req, an.make_client(secrets), now=now, approved=approved)

    def web(con, req, q, *, secrets, approved, now):
        return an.web_search(con, q, an.make_client(secrets), now=now, approved=approved)

    def workshop(con, q, pm_dir, root, asof, *, secrets, approved, now):
        return wk.ask(con, q, pm_dir, root, asof, writer="auto", secrets=secrets, approved=approved, now=now)

    return {"local": lambda con, q, asof: centre.ask(con, q, asof), "workshop": workshop, "note": an.recent_note,
            "deep": deep, "web": web}


def route(res: Result) -> List[str]:
    """The chips the AI centre shows: who, then what came of it."""
    return [f"{s.who}: {s.outcome}" + (f" · ₹{s.cost:,.2f}" if s.cost else "") for s in res.steps]
