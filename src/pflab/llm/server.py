"""S79b item 17: the llama.cpp server wrapper (a larger MoE, with its expert layers kept on the CPU, beside the 12 GB card).

    command(model_cfg, srv)        the argument list (pure; tests read it, nothing runs)
    guard_failures(...)            why it must NOT start now: no exe or model file, caps not applied, free RAM or GPU memory under the floor
    start(model_cfg, ...)          start only when every guard passes (never auto-started otherwise); waits for /health
    health() / stop() / running()
    chat(...)                      one OpenAI-compatible chat call, returned as `client.Reply` (same queue, duty cycle and `llm_runs` sink as Ollama calls)

The server listens on 127.0.0.1 only (the wrapper refuses any other host). Nothing here is imported at start-up and nothing runs in tests: `popen`, `run` and
`transport` are injectable.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

DEFAULT_EXE = "D:/llama.cpp/b12189/bin/llama-server.exe"      # the zip is extracted into bin (confirmed 2026-11-08)
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

_PROC: Optional[subprocess.Popen] = None
_RUNNING: Dict[str, object] = {}                       # {"model": key, "port": int, "pid": int, "started": float}


class ServerError(RuntimeError):
    pass


class GuardRefused(ServerError):
    """A guard said no: the server was not started."""


def srv_settings(cfg: Optional[dict] = None) -> dict:
    d = {"exe": DEFAULT_EXE, "host": "127.0.0.1", "port": 8089, "ctx_size": 8192, "parallel": 1, "ngl": 99, "startup_timeout_s": 240, "threads": 0}
    d.update((cfg or {}).get("llama_server", {}))
    return d


def default_threads() -> int:
    return max(1, (os.cpu_count() or 4) - 2)


def command(model_cfg: dict, srv: Optional[dict] = None) -> List[str]:
    """The llama-server argument list for one model entry (`gguf`, optional `n_cpu_moe`, `ctx_size`, `alias`). Local host only."""
    s = dict(srv or srv_settings())
    host = str(model_cfg.get("host") or s["host"])
    if host not in LOCAL_HOSTS:
        raise ServerError(f"the llama server is local only: refusing host {host!r}")
    gguf = model_cfg.get("gguf")
    if not gguf:
        raise ServerError("the model entry has no gguf path")
    cmd = [str(s["exe"]), "-m", str(gguf), "--host", host, "--port", str(int(model_cfg.get("port") or s["port"])),
           "-ngl", str(int(model_cfg.get("ngl", s["ngl"]))), "--ctx-size", str(int(model_cfg.get("ctx_size", s["ctx_size"]))),
           "--parallel", str(int(s["parallel"])), "--jinja"]
    if model_cfg.get("n_cpu_moe") is not None:
        cmd += ["--n-cpu-moe", str(int(model_cfg["n_cpu_moe"]))]
    threads = int(model_cfg.get("threads") or s.get("threads") or 0) or default_threads()
    cmd += ["-t", str(threads)]
    if model_cfg.get("alias"):
        cmd += ["--alias", str(model_cfg["alias"])]
    return cmd


# --- hardware probes (injectable) --------------------------------------------------------------------------------------

def free_ram_gb() -> float:
    """Free (available) system RAM in GB: psutil when installed, else the Windows API, else /proc/meminfo."""
    try:
        import psutil
        return psutil.virtual_memory().available / 1e9
    except Exception:
        pass
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
        ms = _MS()
        ms.dwLength = ctypes.sizeof(_MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):          # type: ignore[attr-defined]
            return ms.ullAvailPhys / 1e9
    except Exception:
        pass
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024 / 1e9
    except Exception:
        pass
    return float("nan")


def _smi(query: str, run: Callable = subprocess.run) -> Optional[List[float]]:
    try:
        r = run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return None
        return [float(x) for x in r.stdout.strip().splitlines()[0].split(",")]
    except Exception:
        return None


def gpu_free_mib(run: Callable = subprocess.run) -> Optional[float]:
    v = _smi("memory.free", run)
    return v[0] if v else None


def caps_applied(policy: Optional[dict] = None, run: Callable = subprocess.run) -> Tuple[bool, str]:
    """Were the GPU clocks capped (CLAUDE.md: nvidia-smi -lgc 210,2100, -lmc 405,9001)? Yes when nvidia-smi's max SM and memory clocks read at or below the
    cap, or when the lead acknowledged it (`caps_ack = true` in seats.toml, or env PFLAB_GPU_CAPS=ok): a locked clock does not always show in the query,
    so an acknowledgement is accepted but must be given on purpose. Otherwise no."""
    p = policy or {}
    if os.environ.get("PFLAB_GPU_CAPS", "").lower() == "ok" or p.get("caps_ack"):
        return True, "caps acknowledged"
    v = _smi("clocks.max.sm,clocks.max.memory", run)
    if v is None:
        return False, "nvidia-smi gave no clocks (cannot confirm the caps)"
    sm, mem = v[0], v[1] if len(v) > 1 else 0.0
    if sm <= float(p.get("caps_max_sm_mhz", 2100)) + 5 and mem <= float(p.get("caps_max_mem_mhz", 9001)) + 5:
        return True, f"clocks.max sm {sm:.0f} MHz, mem {mem:.0f} MHz are within the caps"
    return False, f"clocks.max reads sm {sm:.0f} MHz, mem {mem:.0f} MHz: caps not confirmed (cap with nvidia-smi -lgc 210,2100 -lmc 405,9001, then set caps_ack)"


def guard_failures(model_cfg: dict, *, policy: Optional[dict] = None, srv: Optional[dict] = None, free_ram: Optional[float] = None,
                   gpu_free: Optional[float] = None, caps: Optional[Tuple[bool, str]] = None, exists: Callable[[str], bool] = os.path.exists) -> List[str]:
    """Every reason the server must not start now ([] means every guard passed). The probes are arguments so a test can set them."""
    p, s = policy or {}, srv or srv_settings()
    out: List[str] = []
    if not exists(str(s["exe"])):
        out.append(f"llama-server.exe not found at {s['exe']}")
    gguf = model_cfg.get("gguf")
    if not gguf or not exists(str(gguf)):
        out.append(f"model file not found: {gguf}")
    ok, why = caps if caps is not None else caps_applied(p)
    if not ok:
        out.append(f"GPU caps: {why}")
    fr = free_ram_gb() if free_ram is None else free_ram
    need = float(model_cfg.get("ram_gb", 0.0)) + float(p.get("ram_floor_gb", 6.0))
    if fr != fr or fr < need:                                    # NaN (unknown) counts as not enough
        out.append(f"free RAM {fr:.1f} GB is under {need:.1f} GB (the model's {model_cfg.get('ram_gb', 0)} GB + the {p.get('ram_floor_gb', 6.0)} GB floor)")
    gf = gpu_free_mib() if gpu_free is None else gpu_free
    floor = float(p.get("gpu_free_floor_mib", 2000))
    if gf is None or gf < floor:
        out.append(f"free GPU memory {gf} MiB is under {floor:.0f} MiB (or unreadable)")
    return out


# --- start / health / stop ----------------------------------------------------------------------------------------------

def base_url(srv: Optional[dict] = None, port: Optional[int] = None) -> str:
    s = srv or srv_settings()
    return f"http://{s['host']}:{int(port or s['port'])}"


def http_transport_for(url: str) -> Callable:
    def transport(method: str, path: str, payload: Optional[dict] = None, timeout: int = 600) -> dict:
        import requests
        r = requests.request(method, url + path, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    return transport


def health(srv: Optional[dict] = None, transport: Optional[Callable] = None, port: Optional[int] = None) -> bool:
    """True when the server answers /health with status ok."""
    t = transport or http_transport_for(base_url(srv, port))
    try:
        j = t("GET", "/health", None, 5)
        return str((j or {}).get("status", "")).lower() == "ok"
    except Exception:
        return False


def running() -> Optional[dict]:
    if _PROC is not None and _PROC.poll() is None:
        return dict(_RUNNING)
    return None


def start(model_key: str, model_cfg: dict, *, policy: Optional[dict] = None, srv: Optional[dict] = None, popen: Callable = subprocess.Popen,
          guards: Optional[List[str]] = None, transport: Optional[Callable] = None, sleep: Callable[[float], None] = time.sleep,
          clock: Callable[[], float] = time.monotonic, dry_run: bool = False) -> dict:
    """Start the server for `model_cfg` after every guard passes. `guards`: precomputed failures (tests); None computes them here.
    `dry_run`: return the command line and the guard result without starting anything. Raises GuardRefused when a guard fails."""
    global _PROC
    s = srv or srv_settings()
    cmd = command(model_cfg, s)
    fails = guard_failures(model_cfg, policy=policy, srv=s) if guards is None else list(guards)
    if dry_run:
        return {"started": False, "dry_run": True, "command": cmd, "guard_failures": fails}
    if fails:
        raise GuardRefused("llama-server not started: " + "; ".join(fails))
    cur = running()
    if cur and cur.get("model") == model_key:
        return {"started": False, "already": True, "command": cmd, **cur}
    if cur:
        stop()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    _PROC = popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags) if flags else popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = int(model_cfg.get("port") or s["port"])
    _RUNNING.clear()
    _RUNNING.update({"model": model_key, "port": port, "pid": getattr(_PROC, "pid", 0), "started": time.time()})
    end = clock() + float(s["startup_timeout_s"])
    while clock() < end:
        if _PROC.poll() is not None:
            _RUNNING.clear()
            raise ServerError(f"llama-server exited at start-up (code {_PROC.returncode})")
        if health(s, transport, port):
            return {"started": True, "command": cmd, **_RUNNING}
        sleep(2.0)
    stop()
    raise ServerError(f"llama-server did not become healthy within {s['startup_timeout_s']} s")


def stop(wait_s: float = 15.0) -> bool:
    """Stop the server this process started. True when something was stopped."""
    global _PROC
    p = _PROC
    _PROC = None
    _RUNNING.clear()
    if p is None or p.poll() is not None:
        return False
    try:
        p.terminate()
        p.wait(timeout=wait_s)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
    return True


# --- one chat call ---------------------------------------------------------------------------------------------------------

def chat_payload(model: str, messages: List[dict], *, think: bool, temperature: float, seed: int, num_predict: int, fmt: Optional[dict], options: Optional[dict]) -> dict:
    """The OpenAI-compatible body. `fmt` (a JSON schema) goes as response_format json_schema, which llama.cpp turns into a grammar: the reply cannot leave the schema."""
    from pflab.llm import constrained
    p = {"model": model, "messages": messages, "stream": False, "temperature": temperature, "seed": seed, "max_tokens": num_predict,
         "chat_template_kwargs": {"enable_thinking": bool(think)}}
    for k in ("top_k", "top_p", "min_p", "presence_penalty"):
        if options and k in options:
            p[k] = options[k]
    if fmt:
        p.update(constrained.llama_format(fmt))
    return p


def chat(model: str, messages: List[dict], *, think: bool = False, temperature: float = 0.0, seed: int = 20261006, num_predict: int = 400,
         fmt: Optional[dict] = None, transport: Optional[Callable] = None, timeout: int = 600, purpose: str = "", options: Optional[dict] = None,
         srv: Optional[dict] = None):
    """One chat completion from the local llama server, as a `client.Reply`. Goes through the same duty cycle, queue and sink as an Ollama call."""
    from pflab.llm import client, diag, duty, queue
    t = transport or http_transport_for(base_url(srv))
    payload = chat_payload(model, messages, think=think, temperature=temperature, seed=seed, num_predict=num_predict, fmt=fmt, options=options)
    t0 = time.time()
    try:
        duty.THROTTLE.before(purpose)
        try:
            with queue.GATE.slot(purpose):
                with duty.THROTTLE.busy():
                    j = t("POST", "/v1/chat/completions", payload, timeout)
        except queue.Busy as b:
            raise client.OllamaError(str(b)) from b
    except Exception as e:
        client._note(model=model, purpose=purpose, status="failed", note=f"{type(e).__name__}: {str(e)[:200]}", seconds=round(time.time() - t0, 2), tokens_in=0, tokens_out=0, digest=None)
        if isinstance(e, client.OllamaError):
            raise
        raise client.OllamaError(f"llama server call failed: {type(e).__name__}: {str(e)[:200]}") from e
    ch = (j.get("choices") or [{}])[0]
    text = (ch.get("message") or {}).get("content") or ""
    fin = str(ch.get("finish_reason") or "")
    dr = "length" if fin == "length" else ("stop" if fin else "")
    u = j.get("usage") or {}
    n_out = int(u.get("completion_tokens", 0))
    label = diag.classify(text, n_out, num_predict, dr, bool(fmt))
    r = client.Reply(text=text, model=model, digest=None, tokens_in=int(u.get("prompt_tokens", 0)), tokens_out=n_out, seconds=round(time.time() - t0, 2), done_reason=dr, label=label)
    client._note(model=model, purpose=purpose, status="ok", note="" if label == "ok" else label, seconds=r.seconds, tokens_in=r.tokens_in, tokens_out=r.tokens_out, digest=None)
    return r
