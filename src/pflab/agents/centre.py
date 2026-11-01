"""The centre (S37): route a question to the agents, run their tools, answer only from what they return.

    route   a bounded choice over the tool menu (JSON-schema-constrained, a 'decision model' job: a local
            Ollama model now; a dedicated decision model such as Laya could take this step later). If the model
            is unavailable or returns nothing usable, a keyword router decides instead.
    run     the chosen tools, as ordinary code (read-only)
    answer  the local model writes from the facts table through the S21 guard (draft, check, revise): every
            number must equal a fact, every claim cites [F:name]. If no draft passes, the facts themselves are
            returned, never unchecked text.
The centre informs; it never decides for the investor and has no order path.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional

from pflab.agents import tools as T

KEYWORDS = {
    "networth": r"net ?worth|worth|holding|portfolio|value|gain|loss|profit|cash|own",
    "guards": r"safe|buy|guard|surveillance|asm|gsm|dip|risky stock|should i",
    "fds": r"\bfd|fixed deposit|matur|deposit|tds",
    "plan": r"target|allocat|weight|underweight|overweight|rebalanc|split|deploy",
    "risk": r"risk|monte|simulat|fall|crash|drawdown|worst|chance",
    "tax": r"\btax|regime|refund|advance",
    "context": r"news|why|filing|announce|result|happen|moved|fell|rose",
    "system": r"working|in sync|status|connected|kite login|telegram|docker|sandbox|stale|fresh|up to date|failing|failed|broken|"
              r"researching|investigat|running now|catching up|everything ok",
}
SYSTEM = ("You answer the investor's questions about his own portfolio using ONLY the FACTS given. Rules: every number you "
          "write must appear in FACTS exactly as given (rupees as given, fractions may be written as percents); do "
          "not add, subtract or estimate anything yourself; end every sentence that states a fact with its "
          "citation, written exactly as [F:name] with the fact's name and nothing else inside the brackets, or [S1] "
          "for a source; never copy a number from a source title (use the FACTS); write numbers as digits; if the "
          "facts do not answer the question, say so. You "
          "inform; you do not tell him to buy or sell, and you never place orders. Be brief.")


@dataclass
class Answer:
    question: str
    tools: List[str]
    text: str
    verified: bool
    facts: Dict[str, object] = field(default_factory=dict)
    router: str = ""
    answered_by: str = ""             # S61: which model of the chain wrote the checked answer


def keyword_route(q: str) -> List[str]:
    hits = [n for n, rx in KEYWORDS.items() if re.search(rx, q, re.I)]
    return hits or ["networth"]


def llm_route(q: str, chat: Optional[Callable] = None, model: str = "") -> List[str]:
    from pflab.llm import client
    chat = chat or client.chat
    menu = "\n".join(f"- {t.name}: {t.about}" for t in T.TOOLS)
    schema = {"type": "object", "properties": {"tools": {"type": "array", "items": {"enum": [t.name for t in T.TOOLS]},
                                                         "minItems": 1, "maxItems": 3}}, "required": ["tools"]}
    r = chat(model, [{"role": "system", "content": "Pick the tools needed to answer the question. Reply in JSON."},
                     {"role": "user", "content": f"Tools:\n{menu}\n\nQuestion: {q}"}], fmt=schema, num_predict=60)
    picked = [t for t in json.loads(r.text).get("tools", []) if t in T.BY_NAME]
    return list(dict.fromkeys(picked))


def facts_table(facts: Dict[str, object]) -> str:
    show = lambda v: f"{v[0]} {v[1]}" if isinstance(v, tuple) else v
    return "\n".join(f"{k} = {show(v)}" for k, v in facts.items())


def ask(con, q: str, asof: date, *, llm: Optional[Callable[[str], str]] = None, chat: Optional[Callable] = None,
        model: Optional[str] = None, tools_override: Optional[List[str]] = None, history: str = "") -> Answer:
    """Real runs take the slider's models (S61, `hq/models.py`: routing; answers drafted by each model of its chain
    until one passes the guard); with no model, routing is by keywords and the answer is the facts themselves. Tests
    pass `chat` / `llm` directly."""
    from pflab.llm import registry
    real = chat is None and llm is None
    chain: List[tuple] = []
    if real and model is None:
        from pflab.hq import models as md
        try:
            rd = md.road(con)
            router_model, chat = md.router(con, r=rd)
            chain = md.answer_chain(con, SYSTEM, r=rd)
        except Exception:                                        # the slider unreadable: the S42 picks, as before
            router_model, chain = registry.chosen("routing"), []
        model = registry.chosen("general")
    else:
        model = model or (registry.chosen("general") if real else "test")
        router_model = registry.chosen("routing") if real else model
    router = "given"
    names = tools_override
    if names is None:
        try:
            if router_model == "laya":
                from pflab.llm import client, eval12
                names, router = eval12.laya_route(q, client.http_transport), "laya"
            elif router_model:
                names, router = llm_route((history[-300:] + "\nFollow-up: " if history else "") + q, chat, router_model), "model"
            else:
                names = []
        except Exception:
            names = []
        if not names:
            names, router = keyword_route(q), "keywords"
    facts: Dict[str, object] = {}
    sources: Dict[str, str] = {}
    for n in names:
        try:
            t = T.BY_NAME[n]
            got = dict(t.run(con, asof, q) if t.uses_question else t.run(con, asof))
            sources.update(got.pop("_sources", {}) or {})
            facts.update(got)
        except Exception as e:                                   # a failing agent is reported, not hidden
            facts[f"{n}.error"] = f"{type(e).__name__}: {e}"[:200]
    src_txt = ("\n\nSOURCES (cite a source as [S1]; quote a title only inside double quotes followed by its tag):\n"
               + "\n".join(f"[{k}] {v}" for k, v in sources.items())) if sources else ""
    earlier = f"EARLIER IN THIS CHAT (for what the question refers to; every number must still come from FACTS):\n{history}\n\n" if history else ""
    prompt = f"{earlier}QUESTION: {q}\n\nFACTS (as of {asof}):\n{facts_table(facts)}{src_txt}"
    from pflab.llm import client, graphs
    if llm is not None:
        chain = [("given", llm)]
    elif not chain and model:
        chain = [("local", client.as_llm(model, SYSTEM, num_predict=500, purpose="answers"))]
    for who, fn in chain:                                        # no model at all: facts only (PLAN A6)
        try:
            out = graphs.run(fn, prompt, facts, sources, allow_cited_source_numbers=True)
            if out.text:
                return Answer(q, names, out.text, True, facts, router, who)
        except Exception as e:                                   # recorded with the facts, never hidden; next model
            facts[f"centre.error.{who}"] = f"{type(e).__name__}: {e}"[:300]
    return Answer(q, names, "No checked answer could be written; these are the facts the agents returned:\n"
                  + facts_table(facts), False, facts, router)
