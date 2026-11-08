"""S79 item 13: the registered comparisons of docs/protocols/s79_local_model_protocol.md, run on the existing evaluation sets.

`run_arm` runs the harness tasks (eval12's own prompts, schemas, guard and sets) one at a time for an arm (a model and a sampling choice),
keeping for every raw reply its `diag` label, tokens, seconds and, per scored item, whether it was right. `decide_sampling` and
`decide_moe` are the protocol's rules, in code. Development only (the real local model, free).
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from pflab.llm import diag, eval12

ANSWER_SEEDS = (20261017, 20261018)
TASKS = ("routing", "answers_20261017", "answers_20261018", "extraction", "materiality")
ROUTING_PATH = eval12.ROOT / "configs" / "llm_eval" / "eval12_routing_r2.toml"
PAUSE_TASK_S = 20.0
PAUSE_ARM_S = 90.0
KIND_OF_TASK = {"routing": "json", "extraction": "json", "materiality": "json", "answers": "text"}


class GpuLost(RuntimeError):
    pass


def gpu_state() -> Dict[str, float]:
    """{used_mib, total_mib, temp_c, util} from nvidia-smi; raises GpuLost when the card does not answer."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=30)
    except Exception as e:
        raise GpuLost(f"nvidia-smi failed: {e}") from e
    if out.returncode != 0 or not out.stdout.strip():
        raise GpuLost(f"nvidia-smi returned {out.returncode}: {out.stderr.strip()[:200]}")
    a = [float(x) for x in out.stdout.strip().splitlines()[0].split(",")]
    return {"used_mib": a[0], "total_mib": a[1], "temp_c": a[2], "util": a[3]}


class Sampler(threading.Thread):
    """Peak GPU memory and temperature while a task runs (every few seconds)."""

    def __init__(self, every: float = 5.0) -> None:
        super().__init__(daemon=True)
        self.every, self.peak_mib, self.peak_c, self.stop_ev, self.failed = every, 0.0, 0.0, threading.Event(), False

    def run(self) -> None:
        while not self.stop_ev.wait(self.every):
            try:
                s = gpu_state()
                self.peak_mib, self.peak_c = max(self.peak_mib, s["used_mib"]), max(self.peak_c, s["temp_c"])
            except GpuLost:
                self.failed = True


class Recorder:
    """Wraps `client.chat` for the harness: adds the arm's sampling and keeps every call's reading."""

    def __init__(self, chat: Callable, sampling_for_kind: Callable[[str], object]) -> None:
        self.chat, self.sampling_for_kind, self.calls, self.task = chat, sampling_for_kind, [], ""

    def __call__(self, model, messages, **kw):
        kind = "json" if kw.get("fmt") else "text"
        r = self.chat(model, messages, sampling=self.sampling_for_kind(kind), **kw)
        self.calls.append({"task": self.task, "kind": kind, "label": getattr(r, "label", "ok"), "tokens_out": getattr(r, "tokens_out", 0),
                           "seconds": getattr(r, "seconds", 0.0), "done_reason": getattr(r, "done_reason", "")})
        return r


def sampling_choice(arm: str, kinds: Sequence[str] = ()) -> Callable[[str], object]:
    """A = old default (explicitly off); B = Qwen's recommended sampling on every kind; C = "auto" only on the kinds the comparison adopted."""
    if arm == "A":
        return lambda kind: "off"
    if arm == "B":
        return lambda kind: "auto"
    return lambda kind: "auto" if kind in kinds else "off"


def _task_json(task: str, items: List[bool], calls: List[dict], extra: dict) -> dict:
    sec = [c["seconds"] for c in calls]
    return {"task": task, "n": len(items), "score": float(np.mean(items)) if items else 0.0, "items": [bool(x) for x in items],
            "labels": [c["label"] for c in calls], "kind": KIND_OF_TASK[task.split("_")[0]], "call_seconds": sec,
            "call_tokens_out": [c["tokens_out"] for c in calls], "done_reasons": [c["done_reason"] for c in calls], **extra}


def run_task(task: str, model: str, rec: Recorder, root: Path) -> dict:
    """One harness task; the harness functions are eval12's own."""
    rec.task, rec.calls = task, []
    chat = eval12.retrying(rec)
    extra: dict = {}
    if task == "routing":
        r = eval12.run_routing(model, chat, ROUTING_PATH)
        items = [x["ok"] for x in r["rows"]]
        extra = {"call_median_s": float(np.median([x["s"] for x in r["rows"]]))}
    elif task.startswith("answers_"):
        r = eval12.run_answers(model, chat, seed=int(task.split("_")[1]), production_guard=True)
        items = [x["final"] for x in r["rows"]]
        extra = {"first": r["first"], "median_s": r["median_s"], "p90_s": r["p90_s"], "task_seconds": [x["s"] for x in r["rows"]],
                 "first_items": [x["first"] for x in r["rows"]], "task_ids": [x["task"] for x in r["rows"]]}
    elif task == "extraction":
        data = json.loads((root / "llm_eval" / "extraction.json").read_text(encoding="utf-8"))
        r = eval12.run_extraction(model, chat, data)
        items = [p is not None for p in r["preds"]]
        extra = {"f1": r["f1"]}
    elif task == "materiality":
        data = json.loads((root / "llm_eval" / "materiality_r2.json").read_text(encoding="utf-8"))
        items = []
        for it in data:
            x = chat(model, [{"role": "system", "content": eval12.TAG_SYSTEM}, {"role": "user", "content": it["text"]}],
                     fmt=eval12.TAG_SCHEMA, num_predict=20)
            items.append((eval12._json(x.text) or {}).get("label") == it["gold"])
    else:
        raise ValueError(task)
    return _task_json(task, items, list(rec.calls), extra)


def run_arm(arm: str, model: str, out: Path, root: Path, kinds: Sequence[str] = (), tasks: Sequence[str] = TASKS, chat: Optional[Callable] = None,
            log: Callable[[str], None] = print, pause_task: float = PAUSE_TASK_S, check_gpu: bool = True) -> Dict[str, dict]:
    """Run (or resume) the arm's tasks, one at a time, checking the card before each; a finished task's file is kept."""
    if chat is None:
        from pflab.llm import client
        chat = client.chat
    out.mkdir(parents=True, exist_ok=True)
    rec = Recorder(chat, sampling_choice(arm, kinds))
    res: Dict[str, dict] = {}
    for task in tasks:
        f = out / f"{task}.json"
        if f.exists():
            res[task] = json.loads(f.read_text(encoding="utf-8"))
            log(f"{arm} {model} {task}: kept ({res[task]['score']:.3f})")
            continue
        g0 = gpu_state() if check_gpu else {}
        smp = Sampler()
        if check_gpu:
            smp.start()
        t0 = time.time()
        try:
            r = run_task(task, model, rec, root)
        finally:
            smp.stop_ev.set()
        if check_gpu:
            g1 = gpu_state()                         # raises GpuLost: the task file is not written, the run stops here
            r["gpu_peak_mib"], r["gpu_peak_c"] = max(smp.peak_mib, g1["used_mib"]), max(smp.peak_c, g1["temp_c"])
            if smp.failed:
                raise GpuLost("nvidia-smi failed during the task")
        r.update(arm=arm, model=model, kinds=list(kinds), run_at=datetime.now().isoformat(), wall_s=round(time.time() - t0, 1), gpu_before=g0)
        f.write_text(json.dumps(r, indent=1), encoding="utf-8")
        res[task] = r
        log(f"{arm} {model} {task}: score {r['score']:.3f} n={r['n']} wall {r['wall_s']} s labels {diag.rates(r['labels'])}")
        time.sleep(pause_task)
    return res


# ---- summaries and the protocol's rules ---------------------------------------------------------------------------

def load_arm(d: Path) -> Dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(d).glob("*.json"))}


def _fail_rate(labels: List[str], with_format: bool) -> float:
    bad = ("loop", "truncated", "empty") + (("format",) if with_format else ())
    return sum(1 for x in labels if x in bad) / len(labels) if labels else 0.0


def summarise(arm: Dict[str, dict]) -> dict:
    """The protocol's numbers for one arm."""
    ans = [arm[t] for t in ("answers_20261017", "answers_20261018") if t in arm]
    items = [x for a in ans for x in a["items"]]
    firsts = [x for a in ans for x in a.get("first_items", [])]
    secs = [x for a in ans for x in a.get("task_seconds", [])]
    ans_calls_s = [s for a in ans for s in a["call_seconds"]]
    ans_tok = [t for a in ans for t in a["call_tokens_out"]]
    tps = [t / s for t, s in zip(ans_tok, ans_calls_s) if s > 0 and t > 20]
    text_labels = [x for a in ans for x in a["labels"]]
    json_labels = [x for t in ("routing", "extraction", "materiality") if t in arm for x in arm[t]["labels"]]
    s = {"answers_final": float(np.mean(items)) if items else None, "answers_first": float(np.mean(firsts)) if firsts else None,
         "answers_median_s": float(np.median(secs)) if secs else None, "answers_p90_s": float(np.percentile(secs, 90)) if secs else None,
         "tokens_per_s": float(np.median(tps)) if tps else None,
         "routing": arm["routing"]["score"] if "routing" in arm else None,
         "routing_call_median_s": arm["routing"].get("call_median_s") if "routing" in arm else None,
         "extraction_f1": arm["extraction"]["f1"] if "extraction" in arm else None,
         "materiality": arm["materiality"]["score"] if "materiality" in arm else None,
         "text_fail_rate": _fail_rate(text_labels, False), "json_fail_rate": _fail_rate(json_labels, True),
         "text_labels": diag.rates(text_labels), "json_labels": diag.rates(json_labels),
         "gpu_peak_mib": max([t.get("gpu_peak_mib", 0.0) for t in arm.values()] or [0.0]),
         "gpu_peak_c": max([t.get("gpu_peak_c", 0.0) for t in arm.values()] or [0.0])}
    return s


def sign_p(better: Sequence[bool], base: Sequence[bool]) -> float:
    """Exact one-sided sign test that `better` beats `base` on the paired items (ties dropped)."""
    from scipy.stats import binomtest
    b = sum(1 for x, y in zip(better, base) if x and not y)
    c = sum(1 for x, y in zip(better, base) if y and not x)
    return 1.0 if b + c == 0 else float(binomtest(b, b + c, 0.5, alternative="greater").pvalue)


def decide_sampling(a: Dict[str, dict], b: Dict[str, dict]) -> dict:
    """Arm B (Qwen's sampling) vs A (old default), per call kind. Returns {"adopt_kinds": [...], "checks": {...}}."""
    sa, sb = summarise(a), summarise(b)
    text = {"final_not_lower": sb["answers_final"] >= sa["answers_final"] - 0.02 - 1e-9,
            "first_not_lower": sb["answers_first"] >= sa["answers_first"] - 0.04 - 1e-9,
            "latency_ok": sb["answers_median_s"] <= 1.25 * sa["answers_median_s"],
            "fewer_failures": sb["text_fail_rate"] < sa["text_fail_rate"]}
    js = {"routing_not_lower": sb["routing"] >= sa["routing"] - 1 / 60 - 1e-9,
          "materiality_not_lower": sb["materiality"] >= sa["materiality"] - 0.01 - 1e-9,
          "extraction_not_lower": sb["extraction_f1"] >= sa["extraction_f1"] - 0.01 - 1e-9,
          "fewer_failures": sb["json_fail_rate"] < sa["json_fail_rate"]}
    adopt = [k for k, c in (("text", text), ("json", js)) if all(c.values())]
    return {"adopt_kinds": adopt, "text": text, "json": js, "A": sa, "B": sb}


def _pooled(arm: Dict[str, dict], tasks: Sequence[str]) -> List[bool]:
    return [x for t in tasks for x in arm[t]["items"]]


def decide_moe(base: Dict[str, dict], moe: Dict[str, dict]) -> dict:
    """The MoE vs qwen3:8b-q8_0 under the protocol's four conditions. `chosen` only when all hold."""
    sb, sm = summarise(base), summarise(moe)
    sets = {"routing": ("routing",), "answers": ("answers_20261017", "answers_20261018"), "materiality": ("materiality",)}
    p_better = {k: sign_p(_pooled(moe, t), _pooled(base, t)) for k, t in sets.items()}
    p_worse = {k: sign_p(_pooled(base, t), _pooled(moe, t)) for k, t in sets.items()}
    beats = any(p < 0.05 / 3 for p in p_better.values())
    not_worse = not any(p < 0.05 for p in p_worse.values()) and sm["extraction_f1"] >= sb["extraction_f1"] - 0.01 - 1e-9
    thr = (sm["routing"] >= eval12.THRESHOLDS["routing"] and sm["answers_final"] >= eval12.THRESHOLDS["answers_final"]
           and sm["extraction_f1"] >= eval12.THRESHOLDS["extraction_f1"])
    lat = (sm["answers_p90_s"] <= 20.0 and sm["answers_median_s"] <= 12.0 and sm["routing_call_median_s"] <= 8.0
           and (sm["tokens_per_s"] or 0) >= 10.0)
    fails = (sm["text_fail_rate"] + sm["json_fail_rate"]) <= (sb["text_fail_rate"] + sb["json_fail_rate"]) + 1e-12
    checks = {"beats_on_score": beats, "not_significantly_worse": not_worse, "harness_thresholds": thr, "latency_bound": lat, "failures_not_above": fails}
    return {"chosen": all(checks.values()), "checks": checks, "p_better": p_better, "p_worse": p_worse, "base": sb, "moe": sm}


# ---- S79b item 17: the two seats (docs/protocols/s79_seats_protocol.md) ----------------------------------------------

FAST_MARGINS = {"routing": 1 / 60, "answers_final": 0.02, "extraction_f1": 0.01, "materiality": 0.01}   # the harness's own (decide_sampling)
FAST_P90_CALL_S = 8.0           # routing and extraction, per call
FAST_ANSWER_P90_S = 20.0        # the harness threshold for a written answer
FAST_VRAM_MIB = 11264.0         # 11 GiB of the 12 GiB card, nvidia-smi memory.used (all processes, display included), so the display's allocation fits beside it
THINKER_ANSWER_P90_S = 90.0
THINKER_ROUTING_P90_S = 60.0
THINKER_RAM_HEADROOM_GB = 6.0


def _p90_calls(arm: Dict[str, dict], task: str) -> Optional[float]:
    s = arm.get(task, {}).get("call_seconds") or []
    return float(np.percentile(s, 90)) if s else None


def _mean4(s: dict) -> float:
    return float(np.mean([s[k] for k in FAST_MARGINS]))


def decide_fast(base: Dict[str, dict], cand: Dict[str, dict]) -> dict:
    """FAST seat: does the challenger replace the incumbent (qwen3:8b-q8_0, arm A)? All checks must hold (protocol, section FAST)."""
    sb, sc = summarise(base), summarise(cand)
    complete = all(t in cand for t in TASKS)
    if not complete:
        return {"chosen": False, "checks": {"complete": False}, "base": sb, "cand": sc, "p90": {}}
    p90 = {"routing": _p90_calls(cand, "routing"), "extraction": _p90_calls(cand, "extraction"), "answers": sc["answers_p90_s"]}
    checks = {"not_worse_" + k: sc[k] >= sb[k] - m - 1e-9 for k, m in FAST_MARGINS.items()}
    checks["better_overall"] = _mean4(sc) >= _mean4(sb) + 0.01 - 1e-9
    checks["latency_p90"] = (p90["routing"] <= FAST_P90_CALL_S and p90["extraction"] <= FAST_P90_CALL_S and p90["answers"] <= FAST_ANSWER_P90_S)
    checks["vram"] = 0 < sc["gpu_peak_mib"] <= FAST_VRAM_MIB
    checks["failures_not_above"] = (sc["text_fail_rate"] + sc["json_fail_rate"]) <= (sb["text_fail_rate"] + sb["json_fail_rate"]) + 1e-12
    return {"chosen": all(checks.values()), "checks": checks, "mean4": {"base": _mean4(sb), "cand": _mean4(sc)}, "p90": p90, "base": sb, "cand": sc}


def pick_fast(base: Dict[str, dict], cands: Dict[str, Dict[str, dict]]) -> dict:
    """The FAST winner among the challengers that pass; the best mean of the four scores, ties to the lower routing p90. None: the incumbent stays."""
    ds = {k: decide_fast(base, v) for k, v in cands.items()}
    ok = [k for k, d in ds.items() if d["chosen"]]
    best = max(ok, key=lambda k: (round(ds[k]["mean4"]["cand"], 6), -ds[k]["p90"]["routing"])) if ok else None
    return {"winner": best, "decisions": ds}


def decide_thinker(base: Dict[str, dict], cand: Dict[str, dict], ram_headroom_gb: Optional[float], crashes: int) -> dict:
    """THINKER seat (guarded run): beats the incumbent on score under item 13's sign-test rule, and the latency, RAM headroom and stability bounds."""
    sb, sc = summarise(base), summarise(cand)
    if not all(t in cand for t in TASKS):
        return {"chosen": False, "checks": {"complete": False}, "base": sb, "cand": sc}
    sets = {"routing": ("routing",), "answers": ("answers_20261017", "answers_20261018"), "materiality": ("materiality",)}
    p_better = {k: sign_p(_pooled(cand, t), _pooled(base, t)) for k, t in sets.items()}
    p_worse = {k: sign_p(_pooled(base, t), _pooled(cand, t)) for k, t in sets.items()}
    checks = {"beats_on_score": any(p < 0.05 / 3 for p in p_better.values()),
              "not_significantly_worse": not any(p < 0.05 for p in p_worse.values()) and sc["extraction_f1"] >= sb["extraction_f1"] - 0.01 - 1e-9,
              "answers_final_threshold": sc["answers_final"] >= eval12.THRESHOLDS["answers_final"] - 1e-9,
              "answers_p90": sc["answers_p90_s"] is not None and sc["answers_p90_s"] <= THINKER_ANSWER_P90_S,
              "routing_p90": (_p90_calls(cand, "routing") or 1e9) <= THINKER_ROUTING_P90_S,
              "ram_headroom": ram_headroom_gb is not None and ram_headroom_gb >= THINKER_RAM_HEADROOM_GB,
              "stable": crashes == 0,
              "failures_not_above": (sc["text_fail_rate"] + sc["json_fail_rate"]) <= (sb["text_fail_rate"] + sb["json_fail_rate"]) + 1e-12}
    return {"chosen": all(checks.values()), "checks": checks, "p_better": p_better, "p_worse": p_worse, "base": sb, "cand": sc}


def store_rows(con, comparison: str, arm: str, model: str, summary: dict, when: Optional[datetime] = None) -> int:
    """Keep an arm's numbers in `llm_s79_eval` (migration 77)."""
    when = when or datetime.now()
    n = 0
    for k, v in summary.items():
        if isinstance(v, (int, float)) and v is not None:
            task = k.split("_")[0] if k.split("_")[0] in ("routing", "answers", "extraction", "materiality", "text", "json") else "all"
            con.execute("INSERT INTO llm_s79_eval VALUES ('IN',?,?,?,?,?,?,?,?,?)", [comparison, arm, model, task, k, float(v), None, when, ""])
            n += 1
    return n
