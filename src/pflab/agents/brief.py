"""Research brief for a name added to the list (S42, PLAN A5 (a)).

Facts come from the knowledge graph (filings, filed results, news tone, the guard verdict) and are made by code.
A model chosen by the S42 evaluation writes a short brief from them through the S21 guard (every number must
be a fact, every sentence cites [F:name] or a source); without a chosen model, or when no draft passes, the
brief is the facts and sources themselves. It informs; it never recommends a trade.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, Optional

PROMPT = ("Write a research brief of at most 5 sentences about {symbol} for an investor who just added it to a watch "
          "list. Cover, where the facts allow: the latest filed results, what the recent filings and news are about, "
          "the main points of the analyst note if one is among the sources, and the safety verdict. Use ONLY the FACTS and SOURCES; every number exactly as given; end every sentence "
          "with [F:name] or [S#]. Do not recommend buying or selling.\n\nFACTS (as of {asof}):\n{facts}\n\nSOURCES:\n{sources}")


@dataclass
class Brief:
    symbol: str
    text: str
    verified: bool                  # True only for a model draft that passed the guard
    facts: Dict[str, object] = field(default_factory=dict)
    sources: Dict[str, str] = field(default_factory=dict)


def _table(d: Dict[str, object]) -> str:
    show = lambda v: f"{v[0]} {v[1]}" if isinstance(v, tuple) else v
    return "\n".join(f"{k} = {show(v)}" for k, v in d.items())


def build(con, symbol: str, asof: date, guard: Optional[dict] = None, llm: Optional[Callable[[str], str]] = None,
          days: int = 90) -> Brief:
    from pflab.kg import build as kb
    symbol = symbol.upper()
    facts, sources = kb.context(con, [symbol], asof, days=days, per=8)
    from pflab.agents import analyst
    from pflab.agents.tradecheck import isin_of
    isin = isin_of(con, symbol) if con is not None else None
    note = analyst.latest_note(con, isin, asof) if isin else None
    if note:                                       # the analyst's research leads; the local model writes from it
        sources[f"S{len(sources) + 1}"] = note
    if guard:
        facts[f"{symbol}.guard"] = guard["verdict"]
        if guard.get("reasons"):
            facts[f"{symbol}.guard_reasons"] = "; ".join(guard["reasons"])
    if not facts:
        return Brief(symbol, f"No graph facts for {symbol} yet (run pflab kg build).", False)
    if llm is not None:
        from pflab.llm import graphs
        prompt = PROMPT.format(symbol=symbol, asof=asof, facts=_table(facts),
                               sources="\n".join(f"[{k}] {v}" for k, v in sources.items()) or "(none)")
        out = graphs.run(llm, prompt, facts, sources, allow_cited_source_numbers=True)
        if out.text:
            return Brief(symbol, out.text, True, facts, sources)
    lines = [f"{symbol}: facts from the graph (no checked written brief"
             + (")" if llm is not None else "; no model chosen yet, S42)")]
    lines += [f"  {k} = {v}" for k, v in facts.items()]
    lines += [f"  [{k}] {v}" for k, v in sources.items()]
    return Brief(symbol, "\n".join(lines), False, facts, sources)


def chosen_llm() -> Optional[Callable[[str], str]]:
    """The general model the S42 evaluation chose (`pflab llm decide12 --record`), else None (facts only)."""
    from pflab.llm import client, registry
    m = registry.chosen("general")
    return client.as_llm(m, num_predict=400) if m else None
