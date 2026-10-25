"""The pre-registered local-vs-API comparison that decides whether the analyst is adopted
(docs/research/analyst_comparison_protocol.md). Same public question, same public documents, two answers:
the local model (through the guard) and the API analyst (trial call). The investor rates them blind.

    prepare   writes the question set to PFLAB_PM_DIR/analyst_compare/questions.json (list companies' names stay
              out of git) and prints its SHA-256 for the protocol
    run       answers every question both ways; API calls go through the doorbell (gate, budget, log) as trials
    sheet     a blind sheet: each pair as X / Y in a seeded random order; the key is kept apart
    score     reads the investor's choices and applies the registered rule
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

TEMPLATES = (
    "What changed in {name}'s latest quarterly results compared with a year earlier, and what reasons do the "
    "documents give?",
    "What do {name}'s filings and news of the last 90 days say about its business: orders, debt, management, "
    "regulatory matters?",
    "What risks for {name} are visible in its recent filings and news, and what do the documents leave unanswered?",
)
N_QUESTIONS, SEED = 20, 20261017
RULE = {"min_api_share": 0.70, "max_cost_rupees": 400.0}


def folder() -> Path:
    from pflab.pm import store
    p = store.pm_dir() / "analyst_compare"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def prepare(stocks: List[dict], names: Dict[str, str], seed: int = SEED, n: int = N_QUESTIONS) -> Path:
    """Templates x list companies, `n` drawn with a fixed seed. `names`: symbol -> company name."""
    pool = [{"symbol": s["symbol"], "question": t.format(name=names.get(s["symbol"], s["symbol"]))}
            for s in stocks for t in TEMPLATES]
    pick = random.Random(seed).sample(pool, min(n, len(pool)))
    p = folder() / "questions.json"
    p.write_text(json.dumps(pick, indent=1, ensure_ascii=False), encoding="utf-8")
    return p


def run(con, asof: date, local_llm: Callable[[str], str], client, *, cfg: Optional[dict] = None) -> Path:
    from pflab.agents import analyst as an
    from pflab.agents.tradecheck import isin_of
    from pflab.llm import graphs
    qs = json.loads((folder() / "questions.json").read_text(encoding="utf-8"))
    out = []
    for k, q in enumerate(qs, start=1):
        isin = isin_of(con, q["symbol"])
        docs = an.public_docs(con, [isin], asof) if isin else []
        req = an.Request(q["question"], q["symbol"], docs, [isin] if isin else [], urgent=True)
        sources = {f"S{i}": f"{d.published} {d.kind}: {d.title}\n{d.text}" for i, d in enumerate(docs, start=1)}
        prompt = (an.SYSTEM + " End every sentence with the document it rests on, as [S1], [S2] ...\n\nDOCUMENTS:\n"
                  + "\n\n".join(f"[{k_}] {v}" for k_, v in sources.items()) + f"\n\nQUESTION: {q['question']}")
        loc = graphs.run(local_llm, prompt, {}, sources, allow_cited_source_numbers=True)
        api = an.ring(con, req, client, cfg=cfg, trial=True, approved=True)
        out.append({"n": k, "symbol": q["symbol"], "question": q["question"], "documents": len(docs),
                    "local": loc.text or "(no answer passed the guard)", "local_checked": bool(loc.text),
                    "api": api.text, "api_status": api.status, "api_cost_inr": api.cost_inr})
    p = folder() / "answers.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return p


def local_prompt(question: str, sources: Dict[str, str], harness: bool = True) -> str:
    """Amendment 1: the guard exempts a sentence marked [inf]; the analyst instructions ask for inference and for what
    the documents leave open, which the first run's prompt gave no way to mark, so those sentences failed as uncited.
    `harness`: S47 pass 3's adopted research harness, appended as evaluated; studies pass False to reproduce the
    prompt they were registered on."""
    from pflab.agents import analyst as an
    from pflab.llm import adopted
    return (an.SYSTEM + " End every sentence that states something from the documents with the document it rests on, "
            "as [S1], [S2] ... End every sentence of your own inference, or about what the documents do not settle, "
            "with [inf]. Copy numbers exactly as written, with their units (%, crore, million).\n\nDOCUMENTS:\n"
            + "\n\n".join(f"[{k}] {v}" for k, v in sources.items()) + f"\n\nQUESTION: {question}"
            + (adopted.RESEARCH if harness else ""))


def local_llm(model: str) -> Callable[[str], str]:
    """The local model with a context window sized to each prompt (amendment 1: Ollama's 4,096-token default cut the
    documents off) and room for a 400-word answer."""
    from pflab.llm import client

    def llm(prompt: str) -> str:
        ctx = min(32768, ((len(prompt) // 3 + 1500) // 1024 + 1) * 1024)
        return client.chat(model, [{"role": "user", "content": prompt}], num_predict=700, num_ctx=ctx, timeout=1800).text
    return llm


def run_local(con, asof: date, llm: Callable[[str], str]) -> Path:
    """Amendment 1: answer the local half again with the full documents; the paid API answers are kept as they are.
    The first run's answers stay in answers_r0.json."""
    from pflab.agents import analyst as an
    from pflab.agents.tradecheck import isin_of
    from pflab.llm import graphs
    p = folder() / "answers.json"
    r0 = folder() / "answers_r0.json"
    if not r0.exists():
        r0.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    ans = json.loads(r0.read_text(encoding="utf-8"))
    for a in ans:
        isin = isin_of(con, a["symbol"])
        docs = an.public_docs(con, [isin], asof) if isin else []
        sources = {f"S{i}": f"{d.published} {d.kind}: {d.title}\n{d.text}" for i, d in enumerate(docs, start=1)}
        prompt = local_prompt(a["question"], sources, harness=False)
        loc = graphs.run(llm, prompt, {}, sources, allow_cited_source_numbers=True)
        a["local"], a["local_checked"] = loc.text or "(no answer passed the guard)", bool(loc.text)
        a["documents_local"] = len(docs)
    p.write_text(json.dumps(ans, indent=1, ensure_ascii=False), encoding="utf-8")
    return p


def sheet(seed: int = SEED) -> Path:
    ans = json.loads((folder() / "answers.json").read_text(encoding="utf-8"))
    rng = random.Random(seed + 1)
    key, lines = {}, ["# Blind comparison: for each question write X, Y or tie in choices.toml", ""]
    for a in ans:
        api_is_x = rng.random() < 0.5
        key[str(a["n"])] = "X" if api_is_x else "Y"
        x, y = (a["api"], a["local"]) if api_is_x else (a["local"], a["api"])
        lines += [f"## {a['n']}. {a['question']}", "", "**X**", "", x, "", "**Y**", "", y, "", "---", ""]
    (folder() / "key.json").write_text(json.dumps(key), encoding="utf-8")
    p = folder() / "sheet.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    tmpl = folder() / "choices.toml"
    if not tmpl.exists():
        tmpl.write_text("[choices]\n" + "\n".join(f'"{a["n"]}" = ""   # X, Y or tie' for a in ans) + "\n", encoding="utf-8")
    return p


_TAG = re.compile(r"\[(?:S\d+|D\d+|inf|F:[^\]]+)\]", re.I)
_DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> List[str]:
    return [n.replace(",", "").rstrip(".") for n in _DIGITS.findall(_TAG.sub(" ", text))]


def measures(answer: str, known: set) -> Optional[dict]:
    """None for a missing answer; else the share of its numbers found in the documents and the share of its sentences
    (4+ words) that carry a citation (amendment 2)."""
    if not answer or answer.startswith("(no answer"):
        return None
    nums = _numbers(answer)
    sents = [s for s in re.split(r"(?<=[.!?])\s+|\n+", answer) if len(s.split()) >= 4]
    return {"numbers_found": (sum(n in known for n in nums) / len(nums)) if nums else 1.0,
            "cited": (sum(bool(_TAG.search(s)) for s in sents) / len(sents)) if sents else 0.0}


def judge(a: Optional[dict], b: Optional[dict], tol: float = 0.05) -> str:
    """'a', 'b' or 'tie' by the registered rubric."""
    if a is None or b is None:
        return "tie" if a is None and b is None else ("b" if a is None else "a")
    for k in ("numbers_found", "cited"):
        if abs(a[k] - b[k]) > tol:
            return "a" if a[k] > b[k] else "b"
    return "tie"


def auto_rate(con, asof: date) -> Path:
    """Amendment 2: fill choices.toml by the rubric (The investor handed the rating over); details kept in rating.json."""
    from pflab.agents import analyst as an
    from pflab.agents.tradecheck import isin_of
    ans = json.loads((folder() / "answers.json").read_text(encoding="utf-8"))
    key = json.loads((folder() / "key.json").read_text(encoding="utf-8"))
    lines, detail = ["[choices]"], []
    for a in ans:
        isin = isin_of(con, a["symbol"])
        docs = an.public_docs(con, [isin], asof) if isin else []
        known = set(_numbers(" ".join(f"{d.published} {d.title} {d.text}" for d in docs) + " " + a["question"]))
        m_api, m_loc = measures(a["api"], known), measures(a["local"], known)
        w = judge(m_api, m_loc)
        api_label = key[str(a["n"])]
        choice = "tie" if w == "tie" else (api_label if w == "a" else ("Y" if api_label == "X" else "X"))
        lines.append(f'"{a["n"]}" = "{choice}"')
        detail.append({"n": a["n"], "api": m_api, "local": m_loc, "winner": {"a": "api", "b": "local"}.get(w, "tie")})
    (folder() / "choices.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    p = folder() / "rating.json"
    p.write_text(json.dumps(detail, indent=1), encoding="utf-8")
    return p


def score() -> dict:
    from pflab import _toml
    key = json.loads((folder() / "key.json").read_text(encoding="utf-8"))
    ans = {str(a["n"]): a for a in json.loads((folder() / "answers.json").read_text(encoding="utf-8"))}
    ch = _toml.load(folder() / "choices.toml").get("choices", {})
    rated = {n: str(c).strip().upper() for n, c in ch.items() if str(c).strip()}
    if len(rated) < len(key):
        return {"done": False, "rated": len(rated), "of": len(key)}
    pts = sum(1.0 if c == key[n] else 0.5 if c == "TIE" else 0.0 for n, c in rated.items())
    share = pts / len(key)
    spent = sum(a["api_cost_inr"] for a in ans.values())
    adopt = share >= RULE["min_api_share"] and spent <= RULE["max_cost_rupees"]
    return {"done": True, "api_share": round(share, 3), "cost_rupees": round(spent, 1), "adopt": adopt, "rule": RULE}
