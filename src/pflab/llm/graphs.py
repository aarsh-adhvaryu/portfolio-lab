"""LangGraph skeleton for guarded drafting (PLAN S21): draft -> check -> (accept | revise | drop).

The same loop as `guard.guarded_generate`, expressed as a LangGraph state machine so the research, IPO
and filing workflows (S27, S28) can grow nodes (retrieve, outline, critique) around it without changing the
guard. `llm` is any prompt -> text callable: tests pass a script, real runs pass `chat_ollama_llm`.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from pflab.llm import guard as g


class DraftState(TypedDict, total=False):
    prompt: str
    current_prompt: str
    facts: Dict
    sources: Dict[str, str]
    retries: int
    attempts: int
    draft: Optional[str]
    ok: bool
    history: List[list]
    text: Optional[str]
    allow_cited: bool


def build(llm: Callable[[str], str]):
    """Compile the draft/check/revise graph around `llm`."""

    def draft(state: DraftState) -> DraftState:
        return {"draft": llm(state["current_prompt"]), "attempts": state.get("attempts", 0) + 1}

    def check(state: DraftState) -> DraftState:
        res = g.check_all(state["draft"], state["facts"], state.get("sources"),
                          allow_cited_source_numbers=state.get("allow_cited", False))
        hist = list(state.get("history", []))
        if res.ok:
            return {"ok": True, "text": state["draft"], "history": hist}
        hist.append(res.violations)
        return {"ok": False, "history": hist,
                "current_prompt": state["prompt"] + "\n\n" + g.feedback(res.violations)}

    def route(state: DraftState) -> str:
        if state["ok"]:
            return "done"
        return "retry" if state["attempts"] <= state["retries"] else "drop"

    def drop(state: DraftState) -> DraftState:
        return {"text": None}

    gr = StateGraph(DraftState)
    gr.add_node("draft", draft)
    gr.add_node("check", check)
    gr.add_node("drop", drop)
    gr.add_edge(START, "draft")
    gr.add_edge("draft", "check")
    gr.add_conditional_edges("check", route, {"done": END, "retry": "draft", "drop": "drop"})
    gr.add_edge("drop", END)
    return gr.compile()


def run(llm: Callable[[str], str], prompt: str, facts: Dict, sources: Optional[Dict[str, str]] = None,
        retries: int = 2, allow_cited_source_numbers: bool = False) -> g.Outcome:
    out = build(llm).invoke({"prompt": prompt, "current_prompt": prompt, "facts": facts, "sources": sources or {},
                             "retries": retries, "attempts": 0, "history": [],
                             "allow_cited": allow_cited_source_numbers})
    return g.Outcome(out.get("text"), out.get("text") is not None, out["attempts"], out.get("history", []),
                     out.get("draft"))


def chat_ollama_llm(model: str, system: str = "", temperature: float = 0.0, num_predict: int = 400) -> Callable[[str], str]:
    """A prompt -> text callable through `langchain-ollama` (the library the plan adopts), for real runs."""
    from langchain_ollama import ChatOllama
    chat = ChatOllama(model=model, temperature=temperature, num_predict=num_predict, reasoning=False)

    def llm(prompt: str) -> str:
        msgs = ([("system", system)] if system else []) + [("human", prompt)]
        return chat.invoke(msgs).content

    return llm
