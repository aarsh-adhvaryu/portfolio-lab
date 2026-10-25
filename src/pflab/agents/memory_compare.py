"""S49: memory retrieval, ours (word matching) vs local embeddings vs a hybrid (docs/research/memory_compare_protocol.md).

Everything runs on this PC: the corpus is the PM store, the questions are written by the local model, the
embeddings come from Ollama (`nomic-embed-text`, pulled once). Results: data/llm_eval/memory_compare.json.
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

SEED, N, DEV = 20261018, 80, 40
EMBED_MODEL = "nomic-embed-text"
STOP = set("what which when where does did have has with from that this about their there were will would could "
           "should into than then them they your company limited india shares".split())
QPROMPT = ("Read the text below. Write ONE question, at most 20 words, that a person would ask and that this text "
           "answers. Do not copy the title; use your own words. Reply with the question only.\n\nTEXT:\n{text}")


def corpus(con, asof: date, days: int = 120) -> List[dict]:
    since = datetime.combine(asof - timedelta(days=days), datetime.min.time())
    items = []
    for did, kind, pub, title, attrs in con.execute(
            """SELECT doc_id, kind, published_at, title, attrs_json FROM kg_docs
               WHERE kind IN ('filing','result','article','analyst_note') AND published_at >= ?""", [since]).fetchall():
        a = json.loads(attrs or "{}")
        text = (title or "") + ("\n" + a["answer"][:2000] if a.get("answer") else "")
        items.append({"id": f"doc:{did}", "kind": kind, "at": pub, "text": text})
    for mid, at, kind, subject, text in con.execute(
            "SELECT mem_id, created_at, kind, subject, text FROM memory").fetchall():
        items.append({"id": f"mem:{mid}", "kind": f"memory/{kind}", "at": at, "text": f"{subject or ''}: {text}"})
    for bid, sym, at, text in con.execute("SELECT brief_id, symbol, built_at, text FROM briefs").fetchall():
        items.append({"id": f"brief:{bid}", "kind": "brief", "at": at, "text": f"{sym} brief: {text[:2000]}"})
    return [i for i in items if len(i["text"]) >= 30]


def words(s: str) -> set:
    return {w for w in re.findall(r"[a-z]{4,}", s.lower()) if w not in STOP}


def rank_words(q: str, items: Sequence[dict]) -> List[int]:
    qw = words(q)
    score = [(len(qw & words(it["text"])), it["at"].timestamp() if hasattr(it["at"], "timestamp") else 0.0, k)
             for k, it in enumerate(items)]
    return [k for _, _, k in sorted(score, key=lambda x: (-x[0], -x[1]))]


def embed(texts: Sequence[str], transport=None, batch: int = 64) -> np.ndarray:
    from pflab.llm import client
    tr = transport or client.http_transport
    out = []
    for i in range(0, len(texts), batch):
        r = tr("POST", "/api/embed", {"model": EMBED_MODEL, "input": [t[:2000] for t in texts[i:i + batch]]}, 600)
        out += r["embeddings"]
    m = np.asarray(out, dtype=float)
    return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-12)


def rank_embed(qv: np.ndarray, M: np.ndarray) -> List[int]:
    return list(np.argsort(-(M @ qv)))


def fuse(*ranks: List[int], k: int = 60) -> List[int]:
    s: Dict[int, float] = {}
    for r in ranks:
        for pos, i in enumerate(r):
            s[i] = s.get(i, 0.0) + 1.0 / (k + pos + 1)
    return sorted(s, key=lambda i: -s[i])


# ---- the adopted look-up (2026-10-18: hybrid passed the rule, test recall@5 0.575 vs words 0.425) -------------------

ADOPTED = "hybrid"


def _key(it: dict) -> str:
    import hashlib
    return hashlib.sha1((it["id"] + "\n" + it["text"][:2000]).encode()).hexdigest()[:20]


def vectors(items: Sequence[dict], cache: Path, transport=None) -> np.ndarray:
    """Embeddings of `items`, cached in `cache` (an .npz in PFLAB_PM_DIR: the corpus holds the investor's memory rows, so
    the index never goes to the repo or the data folder). Only items not seen before are embedded."""
    have: Dict[str, np.ndarray] = {}
    if cache.exists():
        z = np.load(cache, allow_pickle=False)
        have = dict(zip(z["keys"].tolist(), z["vecs"]))
    keys = [_key(it) for it in items]
    new = [(k, it) for k, it in zip(keys, items) if k not in have]
    if new:
        for (k, _), v in zip(new, embed([it["text"] for _, it in new], transport)):
            have[k] = v
        cache.parent.mkdir(parents=True, exist_ok=True)
        live = set(keys)                                    # items older than the window drop out of the cache
        kk = [k for k in have if k in live]
        tmp = cache.with_name(cache.stem + ".tmp.npz")
        np.savez(tmp, keys=np.asarray(kk), vecs=np.asarray([have[k] for k in kk]))
        tmp.replace(cache)
    return np.asarray([have[k] for k in keys])


def lookup(con, question: str, asof: date, k: int = 5, cache: Optional[Path] = None, transport=None) -> List[dict]:
    """The agents' look-up: the `k` corpus items (graph documents, analyst notes, memory rows, briefs of the last
    120 days) that best answer `question`, by the adopted hybrid (word overlap fused with embeddings). Ollama down:
    word overlap alone (the registered baseline)."""
    from pflab.pm import store
    items = [it for it in corpus(con, asof) if it["at"] is None or _day(it["at"]) <= asof]
    if not items or not question.strip():
        return []
    wr = rank_words(question, items)
    try:
        M = vectors(items, cache or store.pm_dir() / "index" / "lookup.npz", transport)
        order = fuse(wr, rank_embed(embed([question], transport)[0], M))
    except Exception:
        order = wr
    return [items[i] for i in order[:k]]


def _day(t) -> date:
    return t.date() if isinstance(t, datetime) else t


def metrics(ranks: List[List[int]], gold: List[int]) -> dict:
    pos = [r.index(g) if g in r else 10 ** 9 for r, g in zip(ranks, gold)]
    return {"recall@5": float(np.mean([p < 5 for p in pos])), "mrr": float(np.mean([1 / (p + 1) for p in pos]))}


def run(con, asof: date, llm: Callable[[str], str], root: Path, transport=None, log=print) -> dict:
    t0 = time.time()
    items = corpus(con, asof)
    pick = random.Random(SEED).sample(range(len(items)), min(N, len(items)))
    qs = []
    for k in pick:
        q = llm(QPROMPT.format(text=items[k]["text"][:1500])).strip().split("\n")[0][:300]
        qs.append((q, k))
    log(f"{len(items)} items, {len(qs)} questions ({time.time() - t0:.0f}s)")
    M = embed([it["text"] for it in items], transport)
    Q = embed([q for q, _ in qs], transport)
    systems: Dict[str, List[List[int]]] = {"words": [], "embed": [], "hybrid": []}
    for (q, _), qv in zip(qs, Q):
        w, e = rank_words(q, items), rank_embed(qv, M)
        systems["words"].append(w)
        systems["embed"].append(e)
        systems["hybrid"].append(fuse(w, e))
    gold = [k for _, k in qs]
    dev = {s: metrics(r[:DEV], gold[:DEV]) for s, r in systems.items()}
    test = {s: metrics(r[DEV:], gold[DEV:]) for s, r in systems.items()}
    best = max(("embed", "hybrid"), key=lambda s: dev[s]["recall@5"])
    adopt = test[best]["recall@5"] >= test["words"]["recall@5"] + 0.10
    out = {"items": len(items), "questions": len(qs), "dev": dev, "test": test, "chosen_on_dev": best,
           "adopted": best if adopt else None, "minutes": round((time.time() - t0) / 60, 1),
           "examples": [{"q": q, "item": items[k]["text"][:120]} for q, k in qs[:5]]}
    p = root / "llm_eval" / "memory_compare.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return out
