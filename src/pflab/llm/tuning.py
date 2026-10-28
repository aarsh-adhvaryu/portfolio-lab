"""S47 model tuning, first pass: prompt tuning by measurement (docs/STUDIES.md).

Each task has prompt variants fixed in the protocol before any run, a TRAIN set to choose the variant on and a TEST
set it is judged on once. Nothing here changes what the agents use: the results file is read, and the winning
prompt wired in by hand, only if it passes the registered rule.

    materiality  BSE headline -> material / routine. Train: round-1 set (200); test: round-2 set (200).
    routing      question -> agent tools. Train: round-1 questions (60); test: round-2 questions (60).
    writing      a guarded note (research brief) from the graph's facts and sources. Tasks: list companies x four
                 as-of dates, split by company (seeded) into train and test; metric: guard pass within 3 drafts.
"""
from __future__ import annotations

import json
import random
import time
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

SEED = 20261018
RULE = {"materiality": 0.90, "routing": 0.95, "writing": 0.85, "research": 0.70}

# ---- variants (fixed by the protocol) ------------------------------------------------------------------------------

from pflab.llm.eval12 import TAG_SYSTEM, ROUTE_SYSTEM  # noqa: E402  (the current prompts are variant 0)

MAT_DEFS = (" Material: financial results or their board meeting outcome, credit ratings, acquisitions, mergers, "
            "orders received, dividends, buybacks, changes of directors, auditors or top management, defaults, "
            "insolvency, regulatory action, fund raising. Routine: newspaper advertisements, trading window "
            "closures, compliance certificates and registrar letters, loss or duplicate share certificates, "
            "investor or analyst meet schedules and transcripts, general updates with no figure or decision.")
ROUTE_MULTI = (" Pick EVERY tool that a part of the question needs: a question that asks two things usually needs "
               "two tools. Do not add tools the question does not need.")
WRITE_RULES = ("\nFORMAT: plain sentences only: no headings, no bullet points, no bold. One claim per sentence. End every "
               "sentence that states a fact with its citation, [F:name] or [S#]; end a sentence of your own inference "
               "with [inf]. Copy every number exactly as given, with its unit. Do not mention numbers from the "
               "question or the date range.")
WRITE_EXAMPLE = ("\nEXAMPLE of the format (a different company):\nAcme Pumps reported net profit of 120.5 million for the "
                 "quarter ended 30-Jun-2026 [F:ACME.q1.net_profit]. The company filed a board meeting outcome on "
                 "12 August 2026 [S1]. The filings do not say whether the order book changed [inf].")


def _few_shot(items: List[dict], k: int, seed: int) -> str:
    ex = random.Random(seed).sample(items, k)
    return " Examples: " + " ".join(f'"{e["text"][:120]}" -> {e["gold"]}.' for e in ex)


def materiality_variants(train: List[dict]) -> Dict[str, str]:
    base = TAG_SYSTEM.split(" Reply in JSON.")[0]
    return {"v0": TAG_SYSTEM, "v1": base + MAT_DEFS + " Reply in JSON.",
            "v2": base + MAT_DEFS + _few_shot(train, 8, SEED) + " Reply in JSON."}


def routing_variants(train: Sequence[tuple]) -> Dict[str, str]:
    ex = random.Random(SEED).sample([t for t in train if len(t[1]) > 1], 3) + \
        random.Random(SEED + 1).sample([t for t in train if len(t[1]) == 1], 3)
    shots = " Examples: " + " ".join(f'"{q}" -> {sorted(n)}.' for q, n in ex)
    return {"v0": ROUTE_SYSTEM, "v1": ROUTE_SYSTEM.replace(" Reply in JSON.", ROUTE_MULTI + " Reply in JSON."),
            "v2": ROUTE_SYSTEM.replace(" Reply in JSON.", ROUTE_MULTI + shots + " Reply in JSON.")}


def writing_variants() -> Dict[str, str]:
    """Suffixes added to the brief prompt (v0 = the prompt as used)."""
    return {"v0": "", "v1": WRITE_RULES, "v2": WRITE_RULES + WRITE_EXAMPLE}


RESEARCH_RULES = ("\nFORMAT: plain sentences only: no headings, no bullet points, no bold, no tables. One claim per "
                  "sentence, each ending with its own document tag [S#] or [inf]. Copy figures exactly as a document "
                  "writes them, with units; give no figure that a document does not state.")
RESEARCH_SHORT = (" At most 250 words.\nEXAMPLE of the format (a different company):\nAcme Pumps reported a board meeting "
                  "outcome approving its quarterly results [S2]. A news report said its order book stood at Rs 450 crore "
                  "[S5]. The documents do not say how much of that is export work [inf].")


def research_variants() -> Dict[str, str]:
    return {"v0": "", "v1": RESEARCH_RULES, "v2": RESEARCH_RULES + RESEARCH_SHORT}


def research_tasks() -> Dict[str, list]:
    """The 20 registered comparison questions (PFLAB_PM_DIR/analyst_compare/questions.json), split 10/10 (seeded)."""
    from pflab.agents import analyst_compare as ac
    qs = json.loads((ac.folder() / "questions.json").read_text(encoding="utf-8"))
    idx = list(range(len(qs)))
    random.Random(SEED).shuffle(idx)
    half = len(idx) // 2
    return {"train": [qs[i] for i in idx[:half]], "test": [qs[i] for i in idx[half:]]}


def run_research(con, llm: Callable[[str], str], tasks: Sequence[dict], suffix: str, asof: date) -> float:
    from pflab.agents import analyst as an
    from pflab.agents import analyst_compare as ac
    from pflab.agents.tradecheck import isin_of
    from pflab.llm import graphs
    ok = n = 0
    for q in tasks:
        isin = isin_of(con, q["symbol"])
        docs = an.public_docs(con, [isin], asof) if isin else []
        sources = {f"S{i}": f"{d.published} {d.kind}: {d.title}\n{d.text}" for i, d in enumerate(docs, start=1)}
        out = graphs.run(llm, ac.local_prompt(q["question"], sources, harness=False) + suffix, {}, sources,
                         allow_cited_source_numbers=True)
        n += 1
        ok += bool(out.text)
    return ok / n if n else 0.0


# ---- adopted variants (wired in by hand after the rule passed; docs/STUDIES.md) ----------------------

ADOPTED = {"materiality": "v2"}           # 2026-10-18: test 0.945 vs v0 0.785, threshold 0.90 (pass 1 of 2026-10-17)


def materiality_tagger(model: Optional[str] = None, chat=None, root: Optional[Path] = None
                       ) -> Optional[Callable[[str], Optional[str]]]:
    """The adopted materiality prompt as a callable headline -> 'material' | 'routine' | None (no answer). None when
    no general model is chosen or the train set (which the v2 examples are drawn from) is missing."""
    from pflab.data import data_dir
    from pflab.llm import client, eval12, registry
    model = model or registry.chosen("general")
    p = (root or data_dir()) / "llm_eval" / "materiality.json"
    if not model or not p.exists():
        return None
    system = materiality_variants(json.loads(p.read_text(encoding="utf-8")))[ADOPTED["materiality"]]
    chat = chat or client.chat
    seen: Dict[str, Optional[str]] = {}

    def tag(text: str) -> Optional[str]:
        if text not in seen:
            try:
                r = chat(model, [{"role": "system", "content": system}, {"role": "user", "content": text}],
                         fmt=eval12.TAG_SCHEMA, num_predict=20)
                seen[text] = (eval12._json(r.text) or {}).get("label")
            except Exception:
                seen[text] = None                     # model down: the filing is simply not model-flagged
        return seen[text]
    return tag


# ---- runners ---------------------------------------------------------------------------------------------------------

def run_materiality(model: str, chat, items: List[dict], system: str) -> float:
    from pflab.llm.eval12 import TAG_SCHEMA, _json
    hits = [(_json(chat(model, [{"role": "system", "content": system}, {"role": "user", "content": it["text"]}],
                        fmt=TAG_SCHEMA, num_predict=20).text) or {}).get("label") == it["gold"] for it in items]
    return float(np.mean(hits)) if hits else 0.0


def run_routing(model: str, chat, items: Sequence[tuple], system: str) -> float:
    from pflab.agents import tools as T
    from pflab.llm.eval12 import _json, route_ok
    menu = "\n".join(f"- {t.name}: {t.about}" for t in T.TOOLS)
    schema = {"type": "object", "required": ["tools"], "properties": {"tools": {
        "type": "array", "items": {"enum": [t.name for t in T.TOOLS]}, "minItems": 1, "maxItems": 3}}}
    ok = []
    for q, need in items:
        r = chat(model, [{"role": "system", "content": system}, {"role": "user", "content": f"Tools:\n{menu}\n\nQuestion: {q}"}],
                 fmt=schema, num_predict=60)
        ok.append(route_ok((_json(r.text) or {}).get("tools", []), need))
    return float(np.mean(ok)) if ok else 0.0


def writing_tasks(con, stocks: List[dict], dates: Sequence[date]) -> Dict[str, list]:
    """Brief tasks (symbol, as-of) split by company into train and test (seeded)."""
    syms = sorted(s["symbol"] for s in stocks)
    random.Random(SEED).shuffle(syms)
    half = len(syms) // 2 + len(syms) % 2
    split = {"train": syms[:half], "test": syms[half:]}
    return {k: [(s, d) for s in v for d in dates] for k, v in split.items()}


def run_writing(con, llm: Callable[[str], str], tasks: Sequence[tuple], suffix: str) -> Dict[str, float]:
    from pflab.agents import brief as br
    from pflab.kg import build as kb
    from pflab.llm import graphs
    passed = first = n = 0
    for sym, asof in tasks:
        facts, sources = kb.context(con, [sym], asof, days=90, per=8)
        if not facts:
            continue
        prompt = br.PROMPT.format(symbol=sym, asof=asof, facts=br._table(facts),
                                  sources="\n".join(f"[{k}] {v}" for k, v in sources.items()) or "(none)") + suffix
        out = graphs.run(llm, prompt, facts, sources, allow_cited_source_numbers=True)
        n += 1
        passed += bool(out.text)
        first += bool(out.text) and out.attempts == 1
    return {"pass": passed / n if n else 0.0, "first": first / n if n else 0.0, "n": n}


# ---- the run -------------------------------------------------------------------------------------------------------

def run(task: str, model: str, root: Path, con=None, stocks=None, chat=None, llm_factory=None,
        log: Callable[[str], None] = print) -> dict:
    """Score every variant on TRAIN, pick the best (ties: the lower variant), score it and v0 on TEST once."""
    from pflab.llm import client, eval12
    chat = chat or client.chat
    t0 = time.time()
    if task == "materiality":
        train = json.loads((root / "llm_eval" / "materiality.json").read_text(encoding="utf-8"))
        test = json.loads((root / "llm_eval" / "materiality_r2.json").read_text(encoding="utf-8"))
        variants = materiality_variants(train)
        score = lambda items, v: run_materiality(model, chat, items, variants[v])
    elif task == "routing":
        train, test = eval12.routing_set(eval12.ROUTING), eval12.routing_set(eval12.ROUNDS[2]["routing"])
        variants = routing_variants(train)
        score = lambda items, v: run_routing(model, chat, items, variants[v])
    elif task == "writing":
        dates = [date(2026, 7, 17), date(2026, 8, 17), date(2026, 9, 17), date(2026, 10, 17)]
        split = writing_tasks(con, stocks, dates)
        train, test = split["train"], split["test"]
        variants = writing_variants()
        llm = (llm_factory or (lambda: client.as_llm(model, num_predict=500)))()
        score = lambda items, v: run_writing(con, llm, items, variants[v])["pass"]
    elif task == "research":
        from pflab.agents import analyst_compare as ac
        split = research_tasks()
        train, test = split["train"], split["test"]
        variants = research_variants()
        llm = (llm_factory or (lambda: ac.local_llm(model)))()
        score = lambda items, v: run_research(con, llm, items, variants[v], date(2026, 10, 17))
    else:
        raise ValueError(task)
    on_train = {}
    for v in variants:
        on_train[v] = score(train, v)
        log(f"{task} {v} train {on_train[v]:.3f}")
    best = max(variants, key=lambda v: (on_train[v], -int(v[1:])))
    on_test = {best: score(test, best)}
    if best != "v0":
        on_test["v0"] = score(test, "v0")
    log(f"{task} best {best}: test {on_test[best]:.3f} (v0 test {on_test['v0']:.3f})")
    passes = on_test[best] >= RULE[task] and (best == "v0" or on_test[best] > on_test["v0"])
    out = {"task": task, "model": model, "variants": variants, "train": on_train, "best": best, "test": on_test,
           "rule": RULE[task], "adopt": passes and best != "v0", "passes_threshold": on_test[best] >= RULE[task],
           "minutes": round((time.time() - t0) / 60, 1),
           "train_n": len(train), "test_n": len(test)}
    d = root / "llm_eval" / "tuning"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task}.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return out
