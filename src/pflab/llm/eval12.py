"""S42: the pre-registered model evaluation for the 12 GB GPU (docs/llm/model_eval_12gb_protocol.md).

Four tasks, each with labels that come from this system or the exchanges, never from a model:
    routing      60 questions labelled with the agent tools they need (configs/llm_eval/eval12_routing.toml)
    answers      50 guarded drafting tasks (llm.evalset, seed 20261006) through the draft-check-revise loop
    extraction   100 NSE corporate-action texts; gold fields from the tested parsers (dividend per share, bonus
                 ratio, split face values, or "other")
    materiality  200 BSE announcement headlines; material or routine from BSE's own subcategory (fixed map)
Latency is measured on the answers task. `decide` applies the thresholds fixed in the protocol.
`build_sets` writes the extraction and materiality sets to data/llm_eval/ (exchange text: data, not code);
their SHA-256 are recorded in the protocol so the sets cannot change unnoticed.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from pflab import _toml

ROOT = Path(__file__).resolve().parents[3]
ROUTING = ROOT / "configs" / "llm_eval" / "eval12_routing.toml"
SEED = 20261016
THRESHOLDS = {"routing": 0.95, "answers_final": 0.98, "extraction_f1": 0.95, "materiality": 0.90, "latency_p90_s": 20.0}
# Round 2 (docs/llm/model_eval_12gb_round2.md): new routing questions, new materiality headlines (2023, unseen),
# new drafting seed; extraction unchanged (every candidate passed it, nothing was tuned on it). Same thresholds.
ROUNDS = {1: {"routing": ROUTING, "materiality": "materiality.json", "answers_seed": 20261006, "results": "results"},
          2: {"routing": ROOT / "configs" / "llm_eval" / "eval12_routing_r2.toml", "materiality": "materiality_r2.json",
              "answers_seed": 20261017, "results": "results_r2"},
          # Round 3 (docs/llm/model_decision_2026-10-17.md): answers only, new seed, the production guard
          3: {"routing": ROOT / "configs" / "llm_eval" / "eval12_routing_r2.toml", "materiality": "materiality_r2.json",
              "answers_seed": 20261018, "results": "results_r3", "production_guard": True}}

MATERIAL = ("Financial Results", "Credit Rating", "Acquisition", "Award of Order / Receipt of Order", "Dividend",
            "Change in Management", "Resignation of Director")
ROUTINE = ("Newspaper Publication", "Closure of Trading Window",
           "Certificate under Reg. 74 (5) of SEBI (DP) Regulations, 2018",
           "Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate",
           "Reg.24(A)-Annual Secretarial Compliance",
           "Reg. 40 (10) - PCS Certificate for Transfer / Transmission / Transposition",
           "Format of the Initial Disclosure to be made by an entity identified as a Large Corporate : Annexure A",
           "Analyst / Investor Meet")

EXTRACT_SYSTEM = ("Read one corporate-action text from the stock exchange and return JSON only. kind is one of "
                  "dividend, bonus, split, other. For a dividend give dividend_per_share in rupees exactly as written. "
                  "For a bonus 'X:Y' give bonus_new = X and "
                  "bonus_held = Y. For a face-value split give face_value_from and face_value_to. Leave every field "
                  "that does not apply null. Never compute a number that is not written.")
EXTRACT_SCHEMA = {"type": "object", "required": ["kind"], "properties": {
    "kind": {"enum": ["dividend", "bonus", "split", "other"]},
    "dividend_per_share": {"type": ["number", "null"]}, "bonus_new": {"type": ["number", "null"]},
    "bonus_held": {"type": ["number", "null"]}, "face_value_from": {"type": ["number", "null"]},
    "face_value_to": {"type": ["number", "null"]}}}
TAG_SYSTEM = ("You sort company announcements. 'material' means it can change what the company is worth or what a "
              "shareholder receives (results, ratings, deals, orders, dividends, top management changes). 'routine' "
              "means a compliance or administrative notice. Reply in JSON.")
TAG_SCHEMA = {"type": "object", "required": ["label"], "properties": {"label": {"enum": ["material", "routine"]}}}
ROUTE_SYSTEM = "Pick the tools needed to answer the question. Reply in JSON."


def file_sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---- task sets -------------------------------------------------------------------------------------------------

def routing_set(path: Path = ROUTING) -> List[tuple]:
    return [(q, set(t)) for q, t in _toml.load(path)["q"]]


def extraction_items(raw, seed: int = SEED) -> List[dict]:
    """100 items: 40 dividends written in rupees, 20 bonuses, 20 splits, 20 others, from the NSE feed 2015 on."""
    from pflab.data import dividends as dv
    from pflab.data import nse_corporate_actions as ca
    r = raw[(raw["ex_date"].astype(str) >= "2015-01-01") & (raw.get("series", "EQ") == "EQ")]
    pools = {"dividend": [], "bonus": [], "split": [], "other": []}
    for s, fv in zip(r["subject"], r.get("faceVal", [None] * len(r))):
        if not s or len(s) > 200:
            continue
        kinds = ca.parse_purpose(s)
        amt = dv.parse_dividend(s, fv)
        if kinds and len(kinds) == 1 and amt is None:
            k = kinds[0][0]
            if k == "bonus":
                a, b = ca._BONUS.findall(s)[0]
                pools["bonus"].append({"text": s, "gold": {"kind": "bonus", "bonus_new": float(a), "bonus_held": float(b)}})
            else:
                old, new = next((o, n) for o, n in ca._SPLIT.findall(s) if ca._plausible_face_values(float(o), float(n)))
                pools["split"].append({"text": s, "gold": {"kind": "split", "face_value_from": float(old),
                                                           "face_value_to": float(new)}})
        elif (amt is not None and not kinds and re.search(r"\b(?:rs|re)\b", s, re.I) and "%" not in s
              and len(dv._AMOUNT.findall(s)) == 1):                  # one amount: nothing to add up (no model maths)
            pools["dividend"].append({"text": s, "gold": {"kind": "dividend", "dividend_per_share": round(amt, 4)}})
        elif not kinds and amt is None and not re.search(r"div|bon|spl|split|rights|buy ?back|\brs\b|\bre\b|\d", s, re.I):
            pools["other"].append({"text": s, "gold": {"kind": "other"}})
    rng = random.Random(seed)
    out = []
    for k, n in (("dividend", 40), ("bonus", 20), ("split", 20), ("other", 20)):
        uniq = list({x["text"]: x for x in pools[k]}.values())
        uniq.sort(key=lambda x: x["text"])
        out += rng.sample(uniq, n)
    return out


def materiality_items(ann, seed: int = SEED) -> List[dict]:
    """200 headlines (100 material, 100 routine by BSE subcategory), at least 40 characters, 2024-01 to 2026-09."""
    a = ann[(ann["headline"].fillna("").str.len() >= 40)]
    rng = random.Random(seed)
    out = []
    for label, subs in (("material", MATERIAL), ("routine", ROUTINE)):
        pool = sorted({h.strip() for h in a[a["subcategory"].isin(subs)]["headline"]})
        out += [{"text": h[:600], "gold": label} for h in rng.sample(pool, 100)]
    return out


def build_sets_r2(root: Path) -> Dict[str, str]:
    """Round 2: 200 NEW headlines from 2023 (round 1 used 2024-01 to 2026-09), same map and rule, new seed."""
    from pflab import _duck
    ann = _duck.sql(f"select headline, subcategory from read_parquet('{root}/bse_announcements/**/*.parquet', "
                     f"union_by_name=true) where dissem_dt >= TIMESTAMP '2023-01-01' and dissem_dt < TIMESTAMP '2024-01-01'").df()
    p = root / "llm_eval" / "materiality_r2.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(materiality_items(ann, seed=20261017), indent=0, ensure_ascii=False), encoding="utf-8")
    return {"materiality_r2": file_sha(p)}


def build_sets(root: Path) -> Dict[str, str]:
    """Write data/llm_eval/{extraction,materiality}.json; returns their SHA-256."""
    from pflab import _duck
    from pflab.data import nse_corporate_actions as ca
    out = root / "llm_eval"
    out.mkdir(parents=True, exist_ok=True)
    ext = extraction_items(ca.load_raw(root))
    ann = _duck.sql(f"select headline, subcategory from read_parquet('{root}/bse_announcements/**/*.parquet', "
                     f"union_by_name=true) where dissem_dt >= TIMESTAMP '2024-01-01' and dissem_dt < TIMESTAMP '2026-10-01'").df()
    mat = materiality_items(ann)
    shas = {}
    for name, items in (("extraction", ext), ("materiality", mat)):
        p = out / f"{name}.json"
        p.write_text(json.dumps(items, indent=0, ensure_ascii=False), encoding="utf-8")
        shas[name] = file_sha(p)
    return shas


# ---- scoring ---------------------------------------------------------------------------------------------------

def route_ok(picked: Sequence[str], need: set) -> bool:
    p = set(picked)
    return need <= p and len(p - need) <= 1


def extraction_f1(golds: List[dict], preds: List[Optional[dict]]) -> float:
    """Micro F1 over (field, value) pairs; numbers match to 1e-6 relative; null fields are absent."""
    tp = fp = fn = 0
    for g, p in zip(golds, preds):
        gs = {(k, v) for k, v in g.items() if v is not None}
        ps = {(k, v) for k, v in (p or {}).items() if v is not None and k in EXTRACT_SCHEMA["properties"]}
        match = 0
        for k, v in gs:
            if any(k == k2 and (v == v2 or (isinstance(v, float) and isinstance(v2, (int, float))
                                            and abs(v - v2) <= 1e-6 * max(1.0, abs(v)))) for k2, v2 in ps):
                match += 1
        tp += match
        fn += len(gs) - match
        fp += len(ps) - match
    return 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 1.0


@dataclass
class Report:
    model: str
    scores: Dict[str, float] = field(default_factory=dict)
    detail: Dict[str, object] = field(default_factory=dict)

    def passes(self) -> Dict[str, bool]:
        s = self.scores
        return {"routing": s.get("routing", 0) >= THRESHOLDS["routing"],
                "answers_final": s.get("answers_final", 0) >= THRESHOLDS["answers_final"],
                "extraction_f1": s.get("extraction_f1", 0) >= THRESHOLDS["extraction_f1"],
                "materiality": s.get("materiality", 0) >= THRESHOLDS["materiality"],
                "latency_p90_s": s.get("latency_p90_s", 1e9) <= THRESHOLDS["latency_p90_s"]}


# ---- running ---------------------------------------------------------------------------------------------------

Chat = Callable[..., object]          # llm.client.chat signature: chat(model, messages, fmt=..., num_predict=...)


def _json(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        m = re.search(r"\{.*\}", text or "", re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except ValueError:
            return None


def run_routing(model: str, chat: Chat, path: Path = ROUTING) -> dict:
    from pflab.agents import tools as T
    menu = "\n".join(f"- {t.name}: {t.about}" for t in T.TOOLS)
    schema = {"type": "object", "required": ["tools"], "properties": {"tools": {
        "type": "array", "items": {"enum": [t.name for t in T.TOOLS]}, "minItems": 1, "maxItems": 3}}}
    rows = []
    for q, need in routing_set(path):
        t0 = time.time()
        r = chat(model, [{"role": "system", "content": ROUTE_SYSTEM},
                         {"role": "user", "content": f"Tools:\n{menu}\n\nQuestion: {q}"}], fmt=schema, num_predict=60)
        picked = (_json(r.text) or {}).get("tools", [])
        rows.append({"q": q, "need": sorted(need), "picked": picked, "ok": route_ok(picked, need), "s": time.time() - t0})
    return {"score": float(np.mean([x["ok"] for x in rows])), "rows": rows}


def run_answers(model: str, chat: Chat, n: int = 50, seed: int = 20261006, production_guard: bool = False) -> dict:
    from pflab.llm import evalset, graphs
    rows = []
    for task in evalset.build(seed=seed, n=n):
        llm = lambda prompt: chat(model, [{"role": "user", "content": prompt}], num_predict=400).text
        t0 = time.time()
        # the guard exactly as the live centre and brief run it (cited-source numbers allowed; S43: rounds 1-2
        # ran it stricter than production), and every rejection kept so a failure's cause can be read
        out = graphs.run(llm, task.prompt, task.facts, task.sources, allow_cited_source_numbers=production_guard)
        rows.append({"task": task.task_id, "final": out.ok, "attempts": out.attempts, "s": time.time() - t0,
                     "first": out.ok and out.attempts == 1, "rejected": sum(len(v) for v in out.history),
                     "violations": [[[v.kind, v.text] for v in h] for h in out.history], "text": out.text})
    secs = [x["s"] for x in rows]
    return {"final": float(np.mean([x["final"] for x in rows])), "first": float(np.mean([x["first"] for x in rows])),
            "rejected_per_task": float(np.mean([x["rejected"] for x in rows])),
            "p90_s": float(np.percentile(secs, 90)), "median_s": float(np.median(secs)), "rows": rows}


def run_extraction(model: str, chat: Chat, items: List[dict]) -> dict:
    preds = []
    for it in items:
        r = chat(model, [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": it["text"]}],
                 fmt=EXTRACT_SCHEMA, num_predict=120)
        preds.append(_json(r.text))
    return {"f1": extraction_f1([it["gold"] for it in items], preds), "preds": preds}


def run_materiality(model: str, chat: Chat, items: List[dict]) -> dict:
    hits = []
    for it in items:
        r = chat(model, [{"role": "system", "content": TAG_SYSTEM}, {"role": "user", "content": it["text"]}],
                 fmt=TAG_SCHEMA, num_predict=20)
        hits.append((_json(r.text) or {}).get("label") == it["gold"])
    return {"accuracy": float(np.mean(hits)), "n": len(hits)}


# ---- Laya (decision model; protocol amendment 1): Ollama serves it only on /v1/systemone -------------------------

def _laya_answers(resp: dict, names: Sequence[str]) -> Dict[str, dict]:
    a = resp.get("answers", {})
    return a if isinstance(a, dict) else dict(zip(names, a))


def laya_route(q: str, transport: Callable) -> List[str]:
    """One true/false question per tool; tools with p(true) >= 0.5, at most 3, the most likely always kept."""
    from pflab.agents import tools as T
    qs = {t.name: {"type": "noul", "instructions": f"Is the '{t.name}' tool ({t.about}) needed to answer this question?"}
          for t in T.TOOLS}
    ans = _laya_answers(transport("POST", "/v1/systemone", {"model": "laya", "state": q, "questions": qs}, 120), list(qs))
    p = {k: float(v.get("noul", 0.0)) for k, v in ans.items()}
    ranked = sorted(p, key=p.get, reverse=True)
    return [ranked[0]] + [k for k in ranked[1:3] if p[k] >= 0.5]


def laya_tag(text: str, transport: Callable) -> Optional[str]:
    qs = {"materiality": {"type": "choice", "instructions": TAG_SYSTEM.split(" Reply in JSON.")[0],
                          "criteria": {"material": "can change what the company is worth or what a shareholder receives",
                                       "routine": "a compliance or administrative notice"}}}
    ans = _laya_answers(transport("POST", "/v1/systemone", {"model": "laya", "state": text, "questions": qs}, 120), list(qs))
    return ans.get("materiality", {}).get("choice")


def evaluate_laya(transport: Callable, root: Path) -> Report:
    transport = retrying(transport)
    rep = Report("laya")
    rows = []
    for q, need in routing_set():
        t0 = time.time()
        picked = laya_route(q, transport)
        rows.append({"q": q, "need": sorted(need), "picked": picked, "ok": route_ok(picked, need), "s": time.time() - t0})
    rep.scores["routing"] = float(np.mean([x["ok"] for x in rows]))
    rep.scores["routing_median_s"] = float(np.median([x["s"] for x in rows]))
    rep.detail["routing"] = rows
    items = json.loads((root / "llm_eval" / "materiality.json").read_text(encoding="utf-8"))
    rep.scores["materiality"] = float(np.mean([laya_tag(it["text"], transport) == it["gold"] for it in items]))
    return rep


def retrying(call: Callable, tries: int = 3, wait: float = 10.0, sleep: Callable[[float], None] = time.sleep) -> Callable:
    """Retry a model call on a transient error (Ollama busy or restarting); after `tries` failures the error is
    raised, which ends that model's run (the runner logs it and moves on; a rerun resumes)."""
    def call_(*a, **k):
        for i in range(tries):
            try:
                return call(*a, **k)
            except Exception:
                if i == tries - 1:
                    raise
                sleep(wait * (i + 1))
    return call_


def evaluate(model: str, chat: Chat, root: Path, tasks: Sequence[str] = ("routing", "answers", "extraction", "materiality"),
             round_: int = 1) -> Report:
    cfg = ROUNDS[round_]
    chat = retrying(chat)
    rep = Report(model)
    if "routing" in tasks:
        r = run_routing(model, chat, cfg["routing"])
        rep.scores["routing"], rep.detail["routing"] = r["score"], r["rows"]
        rep.scores["routing_median_s"] = float(np.median([x["s"] for x in r["rows"]]))
    if "answers" in tasks:
        r = run_answers(model, chat, seed=cfg["answers_seed"], production_guard=cfg.get("production_guard", False))
        rep.scores.update(answers_final=r["final"], answers_first=r["first"], latency_p90_s=r["p90_s"],
                          latency_median_s=r["median_s"], rejected_per_task=r["rejected_per_task"])
        rep.detail["answers"] = r["rows"]
    if "extraction" in tasks:
        items = json.loads((root / "llm_eval" / "extraction.json").read_text(encoding="utf-8"))
        r = run_extraction(model, chat, items)
        rep.scores["extraction_f1"], rep.detail["extraction"] = r["f1"], r["preds"]
    if "materiality" in tasks:
        items = json.loads((root / "llm_eval" / cfg["materiality"]).read_text(encoding="utf-8"))
        rep.scores["materiality"] = run_materiality(model, chat, items)["accuracy"]
    return rep


def logged(chat: Chat, con, role: str) -> Chat:
    """Wrap `chat` so every call is recorded in `llm_runs` (model digest, tokens, seconds)."""
    from datetime import datetime
    from pflab.llm import registry as reg

    def call(model, messages, **kw):
        started = datetime.now()
        r = chat(model, messages, **kw)
        reg.log_run(con, started, model, role=role, model_digest=getattr(r, "digest", None), prompt_name="eval12",
                    prompt_sha=reg.sha(json.dumps(messages, sort_keys=True)), tokens_in=getattr(r, "tokens_in", 0),
                    tokens_out=getattr(r, "tokens_out", 0), seconds=getattr(r, "seconds", 0.0), note="S42 eval12")
        return r
    return call


def decide(reports: List[dict], sizes_gb: Dict[str, float]) -> dict:
    """The registered rule: among models passing every task, the smallest download, then the faster median answer,
    then the higher-bit version. Laya (decision-only) takes routing and materiality if it passes both and routes
    faster than the chosen general model."""
    full = [r for r in reports if all(Report(r["model"], r["scores"]).passes().values())]
    bits = lambda m: 8 if "q8" in m else 4
    choice = min(full, key=lambda r: (sizes_gb.get(r["model"], 1e9), r["scores"].get("latency_median_s", 1e9),
                                      -bits(r["model"]))) if full else None
    out = {"general": choice["model"] if choice else None, "passing": [r["model"] for r in full],
           "routing_and_tagging": choice["model"] if choice else None}
    for r in reports:
        if r["model"] == "laya":
            p = Report("laya", r["scores"]).passes()
            faster = choice is None or r["scores"].get("routing_median_s", 1e9) < choice["scores"].get("routing_median_s", 1e9)
            if p["routing"] and p["materiality"] and faster:
                out["routing_and_tagging"] = "laya"
    return out
