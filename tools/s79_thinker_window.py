"""S79b item 17 part 2: the GUARDED THINKER-seat model window (docs/protocols/s79_seats_protocol.md, Amendment 1). Development only, local, free.

    python tools/s79_thinker_window.py preflight --model KEY
    python tools/s79_thinker_window.py run --model KEY [--deadline 05:30] [--n-cpu-moe N]
    python tools/s79_thinker_window.py slice-incumbent        # writes AM__qwen3_8b-q8_0 from the incumbent's saved arm A records

Keys: qwen3:30b-a3b (Ollama), qwen3.6-35b-a3b and gemma4-26b-a4b (llama.cpp server). One model, one request at a time. A WATCHDOG thread polls every 5 s:
nvidia-smi must answer, GPU temperature <= 82 C, free RAM >= 2.5 GB, the model process alive, candidate time cap; a trip kills the model process, writes the reason
and ends the candidate as "not verified (<reason>)". The matched subset: routing 60, answers 20 (seed 20261017), extraction first 40, materiality first 60.
Results: <data>/llm_eval/results_s79/AM__<model>/ (task files) and .../decision__thinker/window__<model>.json (the measurements).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

BASE = "qwen3:8b-q8_0"
ARM = "AM"
N_ROUTING, N_ANSWERS, N_EXTRACT, N_MATERIAL = 60, 20, 40, 60
SEED_ANSWERS = 20261017
REQUEST_TIMEOUT_S = 240
CAND_CAP_S = 70 * 60
POLL_S = 5.0
TEMP_START_MAX, TEMP_TRIP = 70.0, 82.0
GPU_START_MAX_MIB = 2500.0
RAM_START_MIN_GB, RAM_TRIP_GB = 10.0, 2.5
CAND = {
    "qwen3:30b-a3b": {"backend": "ollama", "ollama": "qwen3:30b-a3b", "size_gb": 18.0},
    "qwen3.6-35b-a3b": {"backend": "llama_server", "gguf": "D:/llama.cpp/models/qwen3.6-35b-a3b-q4.gguf", "size_gb": 21.7, "ctx_size": 4096},
    "gemma4-26b-a4b": {"backend": "llama_server", "gguf": "D:/llama.cpp/models/gemma4-26b-q4.gguf", "size_gb": 17.1, "ctx_size": 4096},
}
GPU_BUDGET_GB = 8.6           # model weights we let the card hold (the card is 12 GB, the display and CUDA context take ~2 GB); the rest sits in RAM


class Abort(BaseException):
    """Raised inside the harness to end the candidate at once (BaseException so the harness's retry loop does not swallow it)."""


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---- probes ---------------------------------------------------------------------------------------------------------------

def avail_ram_gb() -> float:
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
    ms = MS()
    ms.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))       # type: ignore[attr-defined]
    return ms.ullAvailPhys / 1e9


def gpu(timeout: float = 10.0) -> Dict[str, float]:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"nvidia-smi rc {out.returncode}: {out.stderr.strip()[:150]}")
    a = [float(x) for x in out.stdout.strip().splitlines()[0].split(",")]
    return {"used_mib": a[0], "total_mib": a[1], "temp_c": a[2], "util": a[3]}


def ollama_models() -> List[str]:
    out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=30).stdout.strip().splitlines()[1:]
    return [ln.split()[0] for ln in out if ln.strip()]


def llama_procs() -> List[int]:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" | ? { $_.ExecutablePath -like 'D:\\llama.cpp*' } | Select -Expand ProcessId"],
                       capture_output=True, text=True, timeout=30)
    return [int(x) for x in r.stdout.split() if x.strip().isdigit()]


def kill_ollama_runners() -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name like 'ollama%'\" | ? { $_.CommandLine -match 'runner' } | % { Stop-Process -Id $_.ProcessId -Force }"],
                   capture_output=True, text=True, timeout=60)


def gguf_block_count(path: str) -> Optional[int]:
    """The layer count from the GGUF header (key '<arch>.block_count', uint32), or None."""
    try:
        with open(path, "rb") as f:
            head = f.read(8_000_000)
        i = head.find(b".block_count")
        if i < 0:
            return None
        j = i + len(b".block_count")
        typ = int.from_bytes(head[j:j + 4], "little")
        if typ != 4:
            return None
        return int.from_bytes(head[j + 4:j + 8], "little")
    except Exception:
        return None


# ---- the watchdog ----------------------------------------------------------------------------------------------------------

class Watchdog(threading.Thread):
    def __init__(self, model_key: str, backend: str, deadline_ts: float, out_json: Path) -> None:
        super().__init__(daemon=True)
        self.key, self.backend, self.deadline, self.out_json = model_key, backend, deadline_ts, out_json
        self.t0 = time.time()
        self.stop_ev, self.tripped = threading.Event(), threading.Event()
        self.reason = ""
        self.proc: Optional[subprocess.Popen] = None
        self.min_ram, self.peak_mib, self.peak_c = 1e9, 0.0, 0.0
        self.task_peak_mib, self.task_peak_c = 0.0, 0.0
        self.polls, self.gpu_gone = 0, False

    def reset_task_peaks(self) -> None:
        self.task_peak_mib = self.task_peak_c = 0.0

    def trip(self, reason: str) -> None:
        if self.tripped.is_set():
            return
        self.reason = reason
        self.tripped.set()
        log(f"WATCHDOG TRIP: {reason}; killing the model process")
        self.kill_model()

    def kill_model(self) -> None:
        try:
            if self.proc is not None and self.proc.poll() is None:
                self.proc.kill()
        except Exception:
            pass
        if self.backend == "ollama":
            try:
                subprocess.run(["ollama", "stop", CAND[self.key]["ollama"]], capture_output=True, timeout=20)
            except Exception:
                pass
            kill_ollama_runners()
        else:
            for pid in llama_procs():
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=20)

    def run(self) -> None:
        while not self.stop_ev.wait(POLL_S):
            self.polls += 1
            try:
                s = gpu(10.0)
            except Exception as e:
                self.gpu_gone = True
                self.trip(f"GPU lost: nvidia-smi did not answer ({type(e).__name__}: {str(e)[:100]})")
                return
            self.peak_mib, self.peak_c = max(self.peak_mib, s["used_mib"]), max(self.peak_c, s["temp_c"])
            self.task_peak_mib, self.task_peak_c = max(self.task_peak_mib, s["used_mib"]), max(self.task_peak_c, s["temp_c"])
            ram = avail_ram_gb()
            self.min_ram = min(self.min_ram, ram)
            if s["temp_c"] > TEMP_TRIP:
                self.trip(f"GPU temperature {s['temp_c']:.0f} C > {TEMP_TRIP:.0f} C")
                return
            if ram < RAM_TRIP_GB:
                self.trip(f"free RAM {ram:.2f} GB < {RAM_TRIP_GB} GB")
                return
            if self.proc is not None and self.proc.poll() is not None:
                self.trip(f"the model process exited (code {self.proc.returncode})")
                return
            if time.time() > self.deadline:
                self.trip("candidate time cap or window deadline reached")
                return


# ---- chat adapters ---------------------------------------------------------------------------------------------------------

def make_chat(key: str, wd: Watchdog) -> Callable:
    be = CAND[key]["backend"]

    def chat(model, messages, sampling=None, **kw):
        if wd.tripped.is_set():
            raise Abort(wd.reason)
        kw["timeout"] = REQUEST_TIMEOUT_S
        try:
            if be == "ollama":
                from pflab.llm import client
                return client.chat(CAND[key]["ollama"], messages, sampling="off", **kw)
            from pflab.llm import server
            return server.chat(key, messages, **kw)
        except Exception as e:
            cause = e.__cause__ or e
            name = type(cause).__name__
            if wd.tripped.is_set():
                raise Abort(wd.reason)
            if "Timeout" in name or "Timeout" in str(e)[:120]:
                wd.trip(f"a request exceeded {REQUEST_TIMEOUT_S} s (hung)")
                raise Abort(wd.reason)
            if "Connection" in name or "Connection" in str(e)[:120]:
                wd.trip(f"the model server stopped answering ({name})")
                raise Abort(wd.reason)
            raise
    return chat


# ---- the matched subset ----------------------------------------------------------------------------------------------------

def results_root() -> Path:
    from pflab.data import data_dir
    return data_dir() / "llm_eval" / "results_s79"


def am_dir(model: str) -> Path:
    return results_root() / f"{ARM}__{model.replace(':', '_')}"


def slice_incumbent() -> Path:
    src, out = results_root() / "A__qwen3_8b-q8_0", am_dir(BASE)
    out.mkdir(parents=True, exist_ok=True)
    r = json.loads((src / "routing.json").read_text(encoding="utf-8"))
    r["arm"] = ARM + " (matched subset of arm A)"
    assert r["n"] == N_ROUTING
    (out / "routing.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
    a = json.loads((src / "answers_20261017.json").read_text(encoding="utf-8"))
    n = N_ANSWERS
    assert all(a["first_items"]) and len(a["call_seconds"]) == a["n"]          # one call per task: the first n calls are the first n tasks
    a2 = dict(a, n=n, items=a["items"][:n], first_items=a["first_items"][:n], task_seconds=a["task_seconds"][:n], task_ids=a["task_ids"][:n],
              labels=a["labels"][:n], call_seconds=a["call_seconds"][:n], call_tokens_out=a["call_tokens_out"][:n], done_reasons=a["done_reasons"][:n])
    import numpy as np
    a2.update(score=float(np.mean(a2["items"])), first=float(np.mean(a2["first_items"])), median_s=float(np.median(a2["task_seconds"])),
              p90_s=float(np.percentile(a2["task_seconds"], 90)), arm=ARM + " (first 20 of arm A, seed 20261017)")
    (out / "answers_20261017.json").write_text(json.dumps(a2, indent=1), encoding="utf-8")
    empty = {k: ([] if isinstance(v, list) else v) for k, v in a2.items()}
    empty.update(n=0, score=0.0, task="answers_20261018", first=0.0, note="empty marker: the matched subset uses one seed (Amendment 1)")
    (out / "answers_20261018.json").write_text(json.dumps(empty, indent=1), encoding="utf-8")
    e = json.loads((src / "extraction.json").read_text(encoding="utf-8"))
    assert e["f1"] == 1.0 and all(e["items"][:N_EXTRACT])                      # micro F1 1.0 on all 100: 1.0 on any subset
    k = N_EXTRACT
    e2 = dict(e, n=k, items=e["items"][:k], labels=e["labels"][:k], call_seconds=e["call_seconds"][:k], call_tokens_out=e["call_tokens_out"][:k],
              done_reasons=e["done_reasons"][:k], score=1.0, f1=1.0, arm=ARM + " (first 40 of arm A)")
    (out / "extraction.json").write_text(json.dumps(e2, indent=1), encoding="utf-8")
    m = json.loads((src / "materiality.json").read_text(encoding="utf-8"))
    k = N_MATERIAL
    m2 = dict(m, n=k, items=m["items"][:k], labels=m["labels"][:k], call_seconds=m["call_seconds"][:k], call_tokens_out=m["call_tokens_out"][:k],
              done_reasons=m["done_reasons"][:k], score=float(np.mean(m["items"][:k])), arm=ARM + " (first 60 of arm A)")
    (out / "materiality.json").write_text(json.dumps(m2, indent=1), encoding="utf-8")
    return out


def run_subset_task(task: str, model: str, rec, root: Path) -> dict:
    import numpy as np
    from pflab.llm import eval12, s79_eval as se
    rec.task, rec.calls = task, []
    chat = eval12.retrying(rec)
    extra: dict = {}
    if task == "routing":
        r = eval12.run_routing(model, chat, se.ROUTING_PATH)
        items = [x["ok"] for x in r["rows"]]
        extra = {"call_median_s": float(np.median([x["s"] for x in r["rows"]]))}
    elif task == "answers_20261017":
        r = eval12.run_answers(model, chat, n=N_ANSWERS, seed=SEED_ANSWERS, production_guard=True)
        items = [x["final"] for x in r["rows"]]
        extra = {"first": r["first"], "median_s": r["median_s"], "p90_s": r["p90_s"], "task_seconds": [x["s"] for x in r["rows"]],
                 "first_items": [x["first"] for x in r["rows"]], "task_ids": [x["task"] for x in r["rows"]]}
    elif task == "extraction":
        data = json.loads((root / "llm_eval" / "extraction.json").read_text(encoding="utf-8"))[:N_EXTRACT]
        r = eval12.run_extraction(model, chat, data)
        items = [p is not None for p in r["preds"]]
        extra = {"f1": r["f1"]}
    elif task == "materiality":
        data = json.loads((root / "llm_eval" / "materiality_r2.json").read_text(encoding="utf-8"))[:N_MATERIAL]
        items = []
        for it in data:
            x = chat(model, [{"role": "system", "content": eval12.TAG_SYSTEM}, {"role": "user", "content": it["text"]}], fmt=eval12.TAG_SCHEMA, num_predict=20)
            items.append((eval12._json(x.text) or {}).get("label") == it["gold"])
    else:
        raise ValueError(task)
    return se._task_json(task, items, list(rec.calls), extra)


# ---- preflight and bench ---------------------------------------------------------------------------------------------------

def reassert_caps() -> str:
    a = subprocess.run(["nvidia-smi", "-lgc", "210,2100"], capture_output=True, text=True, timeout=30)
    b = subprocess.run(["nvidia-smi", "-lmc", "405,9001"], capture_output=True, text=True, timeout=30)
    return f"lgc rc {a.returncode} {a.stdout.strip()[:80]} {a.stderr.strip()[:80]} | lmc rc {b.returncode} {b.stdout.strip()[:80]} {b.stderr.strip()[:80]}"


def preflight(key: str, fix: bool = True) -> List[str]:
    fails: List[str] = []
    log("caps: " + reassert_caps())
    if fix:
        for m in ollama_models():
            subprocess.run(["ollama", "stop", m], capture_output=True, timeout=60)
        time.sleep(5)
    if ollama_models():
        fails.append(f"a model is still resident in Ollama: {ollama_models()}")
    if llama_procs():
        fails.append(f"llama-server is running: {llama_procs()}")
    for _ in range(12):                                   # wait for the card to drain
        s = gpu()
        if s["used_mib"] < GPU_START_MAX_MIB:
            break
        time.sleep(5)
    if s["temp_c"] >= TEMP_START_MAX:
        fails.append(f"GPU temperature {s['temp_c']:.0f} C >= {TEMP_START_MAX:.0f}")
    if s["used_mib"] >= GPU_START_MAX_MIB:
        fails.append(f"GPU memory used {s['used_mib']:.0f} MiB >= {GPU_START_MAX_MIB:.0f}")
    ram = avail_ram_gb()
    if ram < RAM_START_MIN_GB:
        fails.append(f"free RAM {ram:.1f} GB < {RAM_START_MIN_GB}")
    cfg = CAND[key]
    if cfg["backend"] == "llama_server":
        if not os.path.exists(cfg["gguf"]):
            fails.append("gguf missing")
        cpu_part = max(0.0, cfg["size_gb"] - GPU_BUDGET_GB) + 0.8
        if ram - cpu_part < RAM_TRIP_GB + 1.0:
            fails.append(f"predicted RAM shortfall: {ram:.1f} GB free, about {cpu_part:.1f} GB of the model must stay in RAM (floor {RAM_TRIP_GB} GB + 1 GB margin)")
    else:
        cpu_part = max(0.0, cfg["size_gb"] - 10.0) + 0.5               # Ollama fills the card to about 10 GB of weights
        if ram - cpu_part < RAM_TRIP_GB + 0.5:
            fails.append(f"predicted RAM shortfall: {ram:.1f} GB free, about {cpu_part:.1f} GB of the model stays in RAM")
    log(f"preflight {key}: temp {s['temp_c']:.0f} C, gpu used {s['used_mib']:.0f} MiB, free RAM {ram:.1f} GB -> {'OK' if not fails else fails}")
    return fails


def bench(key: str) -> dict:
    """Prompt and generation tokens/s on a ~900-token prompt (raw HTTP, so the server's own timings are read)."""
    import requests
    cfg = CAND[key]
    filler = " ".join(f"The company reported item {i} in its quarterly filing with revenue growth and margin detail." for i in range(60))
    msgs = [{"role": "user", "content": f"[{time.time():.0f}] Read this and then write two sentences summarising it.\n{filler}"}]
    if cfg["backend"] == "ollama":
        j = requests.post("http://localhost:11434/api/chat", json={"model": cfg["ollama"], "stream": False, "think": False, "messages": msgs,
                                                                 "options": {"temperature": 0, "num_predict": 160}}, timeout=REQUEST_TIMEOUT_S).json()
        return {"prompt_tokens": j.get("prompt_eval_count"), "prompt_tps": j.get("prompt_eval_count", 0) / max(j.get("prompt_eval_duration", 1) / 1e9, 1e-9),
                "gen_tokens": j.get("eval_count"), "gen_tps": j.get("eval_count", 0) / max(j.get("eval_duration", 1) / 1e9, 1e-9),
                "load_s": j.get("load_duration", 0) / 1e9}
    j = requests.post("http://127.0.0.1:%d/v1/chat/completions" % cfg.get("port", 8089),
                      json={"model": key, "messages": msgs, "max_tokens": 160, "temperature": 0, "cache_prompt": False,
                            "chat_template_kwargs": {"enable_thinking": False}}, timeout=REQUEST_TIMEOUT_S).json()
    t = j.get("timings") or {}
    return {"prompt_tokens": t.get("prompt_n"), "prompt_tps": t.get("prompt_per_second"), "gen_tokens": t.get("predicted_n"), "gen_tps": t.get("predicted_per_second")}


def write_status(path: Path, d: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, indent=1, default=str), encoding="utf-8")


def run_candidate(key: str, deadline_hhmm: str, n_cpu_moe: Optional[int], wait_until: str = "00:00") -> int:
    from pflab.data import data_dir
    from pflab.llm import registry, s79_eval as se, server
    registry.require_registered("seat-thinker-candidate", key, datetime.now())
    cfg = CAND[key]
    status_path = results_root() / "decision__thinker" / f"window__{key.replace(':', '_')}.json"
    st: dict = {"model": key, "backend": cfg["backend"], "started": datetime.now().isoformat(), "verdict": "running", "crashes": 0}
    wait_end = datetime.now().replace(hour=int(wait_until.split(":")[0]), minute=int(wait_until.split(":")[1]), second=0, microsecond=0).timestamp()
    fails = preflight(key)
    while fails and time.time() < wait_end:                               # RAM is held by the investor's browser and the lead's runs: wait for it to fall
        time.sleep(60)
        fails = preflight(key)
    if fails:
        st.update(verdict="not verified", reason="preflight: " + "; ".join(fails), crashes=0)
        write_status(status_path, st)
        log("NOT VERIFIED: " + st["reason"])
        return 3
    h, m = (int(x) for x in deadline_hhmm.split(":"))
    deadline = min(time.time() + CAND_CAP_S, datetime.now().replace(hour=h, minute=m, second=0, microsecond=0).timestamp())
    wd = Watchdog(key, cfg["backend"], deadline, status_path)
    wd.start()
    out = am_dir(key)
    out.mkdir(parents=True, exist_ok=True)
    t_load0 = time.time()
    try:
        if cfg["backend"] == "llama_server":
            nl = gguf_block_count(cfg["gguf"]) or 48
            per_layer = cfg["size_gb"] / nl
            ncm = n_cpu_moe if n_cpu_moe is not None else min(nl, max(0, int(round(nl - (GPU_BUDGET_GB - 1.2) / per_layer))))
            st.update(layers=nl, n_cpu_moe=ncm)
            log(f"{key}: {nl} layers, --n-cpu-moe {ncm}")
            mc = {"gguf": cfg["gguf"], "n_cpu_moe": ncm, "ctx_size": cfg["ctx_size"], "ram_gb": cfg["size_gb"] - GPU_BUDGET_GB}
            srv = server.srv_settings({"llama_server": {"startup_timeout_s": 600}})
            r = server.start(key, mc, policy={"caps_ack": True, "ram_floor_gb": 2.5}, srv=srv, guards=[])    # our preflight and watchdog are the guards (stricter, above)
            wd.proc = server._PROC
            st["command"] = r.get("command")
        else:
            pass
        # warm-up and bench (load time for Ollama = load_duration of the first call)
        b = bench(key)
        st["load_s"] = round(b.get("load_s") or (time.time() - t_load0), 1)
        st["bench"] = b
        st["ram_after_load_gb"] = round(avail_ram_gb(), 2)
        st["gpu_after_load"] = gpu()
        log(f"loaded: {st['load_s']} s; bench {b}; free RAM after load {st['ram_after_load_gb']} GB; gpu {st['gpu_after_load']}")
        write_status(status_path, st)
        if wd.tripped.is_set():
            raise Abort(wd.reason)
        chat = make_chat(key, wd)
        rec = se.Recorder(chat, se.sampling_choice("A"))
        for task in ("routing", "extraction", "materiality", "answers_20261017"):
            f = out / f"{task}.json"
            if f.exists():
                log(f"{task}: kept")
                continue
            wd.reset_task_peaks()
            t0 = time.time()
            r = run_subset_task(task, key, rec, data_dir())
            s = gpu()
            r.update(arm=ARM, model=key, kinds=[], run_at=datetime.now().isoformat(), wall_s=round(time.time() - t0, 1),
                     gpu_peak_mib=max(wd.task_peak_mib, s["used_mib"]), gpu_peak_c=max(wd.task_peak_c, s["temp_c"]), gpu_before={})
            f.write_text(json.dumps(r, indent=1), encoding="utf-8")
            log(f"{task}: score {r['score']:.3f} n={r['n']} wall {r['wall_s']} s p90/call {sorted(r['call_seconds'])[int(0.9 * (len(r['call_seconds']) - 1))]:.1f} s "
                f"free RAM min {wd.min_ram:.2f} GB peak temp {wd.peak_c:.0f} C peak mem {wd.peak_mib:.0f} MiB")
            time.sleep(10.0)
        # the second answers seed is an empty marker (Amendment 1)
        mk = out / "answers_20261018.json"
        if not mk.exists():
            inc = json.loads((am_dir(BASE) / "answers_20261018.json").read_text(encoding="utf-8"))
            mk.write_text(json.dumps(dict(inc, model=key), indent=1), encoding="utf-8")
        st["verdict"] = "completed"
    except Abort as e:
        st.update(verdict="not verified", reason=f"watchdog/abort: {e}", crashes=1)
        log(f"NOT VERIFIED: {e}")
    except BaseException as e:                                         # anything else: stop the model, record, do not retry
        st.update(verdict="not verified", reason=f"{type(e).__name__}: {str(e)[:200]}", crashes=0 if isinstance(e, (server.ServerError,)) else 1)
        log(f"ERROR: {st['reason']}")
        if not wd.tripped.is_set():
            wd.trip(f"error: {st['reason']}")
    finally:
        wd.stop_ev.set()
        st.update(finished=datetime.now().isoformat(), wall_min=round((time.time() - wd.t0) / 60, 1), min_free_ram_gb=round(wd.min_ram, 2), peak_gpu_mib=wd.peak_mib,
                  peak_temp_c=wd.peak_c, watchdog_trip=wd.reason, gpu_lost=wd.gpu_gone)
        # stop the model fully
        try:
            if cfg["backend"] == "llama_server":
                server.stop()
                for pid in llama_procs():
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=20)
            else:
                subprocess.run(["ollama", "stop", cfg["ollama"]], capture_output=True, timeout=60)
        except Exception:
            pass
        write_status(status_path, st)
        for _ in range(24):
            try:
                s = gpu()
                if s["used_mib"] < GPU_START_MAX_MIB:
                    break
            except Exception:
                break
            time.sleep(5)
        try:
            log(f"after stop: gpu {gpu()}, free RAM {avail_ram_gb():.1f} GB, ollama ps {ollama_models()}, llama {llama_procs()}")
        except Exception as e:
            log(f"after stop: nvidia-smi failed {e}")
    return 0 if st["verdict"] == "completed" else 4


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preflight")
    p.add_argument("--model", required=True)
    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--deadline", default="05:30")
    r.add_argument("--n-cpu-moe", type=int, default=None)
    r.add_argument("--wait-until", default="00:00", help="keep re-checking the preflight (every minute) until this time before giving up")
    sub.add_parser("slice-incumbent")
    a = ap.parse_args()
    if a.cmd == "slice-incumbent":
        print(slice_incumbent())
        return 0
    if a.cmd == "preflight":
        return 0 if not preflight(a.model, fix=False) else 3
    return run_candidate(a.model, a.deadline, a.n_cpu_moe, a.wait_until)


if __name__ == "__main__":
    raise SystemExit(main())
