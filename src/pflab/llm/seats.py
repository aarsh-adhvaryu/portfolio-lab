"""S79b item 17: the two local model seats, FAST and THINKER, and which one is loaded in which mode.

    seat("fast" | "thinker")  -> {seat, key, model, backend, options, fallback, reason, requested}
    chat_target("fast")       -> the same, with a llama server that is not answering replaced by the fallback (what `client.chat` uses for "seat:fast")
    for_mode("session")       -> the plan {mode, want, action: keep|swap|hold|none, load, unload, reason}  (a dry run; `apply` carries it out)

A seat's model is a registered, measured pick (configs/llm_models.toml: role "seat-fast" / "seat-thinker", decision "chosen ...") described in configs/seats.toml
([model."<key>"]: backend 'ollama' or 'llama_server', gguf, n_cpu_moe, options, ram_gb). Until a pick exists the seat uses its `default`. Whenever a seat's model is missing,
its file or Ollama tag is not there, or the RAM that would be left is under the floor (or, for a llama server, any start guard fails), the seat is the fallback
qwen3:8b-q8_0 and says why. FAST is resident in pre_open/session, THINKER in post_close/deep; never both; a swap is held for `hysteresis_s` after the last one
and until the new mode has lasted `mode_dwell_s`, so a mode edge does not thrash the card. Nothing here starts a model unless `apply(...)` is called.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from pflab import _toml

CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs"
SEATS_PATH = CONFIG_DIR / "seats.toml"
S79B_PATH = CONFIG_DIR / "s79b.toml"
SEATS = ("fast", "thinker")
PREFIX = "seat:"
FALLBACK = "qwen3:8b-q8_0"

_LOCK = threading.RLock()
STATE: Dict[str, object] = {"resident_seat": None, "resident_key": None, "swapped_at": None, "mode": None, "mode_since": None}
_CACHE: Dict[str, tuple] = {}
CACHE_S = 30.0


def load_config(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else SEATS_PATH
    return _toml.load(p) if p.exists() else {}


def load_picks(path: Optional[Path] = None) -> List[dict]:
    from pflab.llm import registry
    p = Path(path) if path else registry.PICKS_PATH
    return list(_toml.load(p).get("pick", [])) if p.exists() else []


def switch(path: Optional[Path] = None) -> dict:
    """The [seats] table of configs/s79b.toml ({} when absent). `on` defaults to true."""
    p = Path(path) if path else S79B_PATH
    try:
        return dict(_toml.load(p).get("seats", {})) if p.exists() else {}
    except Exception:
        return {}


def is_on(path: Optional[Path] = None) -> bool:
    return bool(switch(path).get("on", True))


def is_seat_name(model: str) -> bool:
    return isinstance(model, str) and model.startswith(PREFIX) and model[len(PREFIX):] in SEATS


def chosen_pick(seat_name: str, picks: List[dict]) -> Optional[dict]:
    """The newest registered pick for the seat whose decision starts with 'chosen'."""
    rows = [p for p in picks if str(p.get("role", "")).replace("_", "-") == f"seat-{seat_name}" and str(p.get("decision", "")).lower().startswith("chosen")]
    return max(rows, key=lambda p: str(p.get("registered_at", ""))) if rows else None


def model_entry(key: str, cfg: dict) -> dict:
    """The seats.toml entry for a model key; an unknown key is an Ollama model of that name."""
    e = dict((cfg.get("model") or {}).get(key) or {})
    e.setdefault("backend", "ollama")
    if e["backend"] == "ollama":
        e.setdefault("ollama", key)
    return e


def requested_key(seat_name: str, cfg: dict, picks: List[dict]) -> tuple:
    pk = chosen_pick(seat_name, picks)
    if pk and pk.get("model"):
        return str(pk["model"]), f"pick registered {pk.get('registered_at', '')}"
    d = ((cfg.get("seat") or {}).get(seat_name) or {}).get("default") or (cfg.get("policy") or {}).get("fallback_model", FALLBACK)
    return str(d), "default (no chosen pick yet)"


def _fallback(cfg: dict) -> dict:
    pol = cfg.get("policy") or {}
    key = str(pol.get("fallback_model", FALLBACK))
    e = model_entry(key, cfg)
    e["backend"] = pol.get("fallback_backend", e.get("backend", "ollama"))
    return {"key": key, "model": e.get("ollama", key) if e["backend"] == "ollama" else key, "backend": e["backend"], "options": dict(e.get("options") or {}), "entry": e}


def seat(name: str, *, cfg: Optional[dict] = None, picks: Optional[List[dict]] = None, installed: Optional[Dict[str, dict]] = None,
         free_ram: Optional[float] = None, exists: Callable[[str], bool] = os.path.exists, guards: Optional[List[str]] = None,
         resident_key: Optional[str] = None) -> dict:
    """Resolve one seat. `installed`: Ollama's installed models (None: asked once, a failure counts as none). `free_ram`: GB (None: measured). `guards`: llama-server
    guard failures (None: computed for a llama-server model that is not running). `resident_key`: the model key already loaded (its RAM is already spent)."""
    if name not in SEATS:
        raise ValueError(f"unknown seat {name!r}; known: {SEATS}")
    cached = cfg is None and picks is None and installed is None and free_ram is None and guards is None and resident_key is None
    if cached:
        hit = _CACHE.get(name)
        if hit and time.monotonic() - hit[0] < CACHE_S:
            return dict(hit[1])
    cfg = load_config() if cfg is None else cfg
    picks = load_picks() if picks is None else picks
    pol = cfg.get("policy") or {}
    key, why = requested_key(name, cfg, picks)
    e = model_entry(key, cfg)
    be = e["backend"]
    fb = _fallback(cfg)
    problem: Optional[str] = None
    cur = STATE.get("resident_key") if resident_key is None else resident_key

    if key == fb["key"]:
        out = {"seat": name, "key": fb["key"], "model": fb["model"], "backend": fb["backend"], "options": fb["options"], "fallback": False, "reason": why, "requested": key}
    else:
        if be == "ollama":
            if installed is None:
                try:
                    from pflab.llm import client
                    installed = client.installed()
                except Exception:
                    installed = {}
            from pflab.llm import client as _c
            if _c.resolve(e["ollama"], installed) is None:
                problem = f"{e['ollama']} is not installed in Ollama (or Ollama is not reachable)"
        elif be == "llama_server":
            from pflab.llm import server
            fails = guards if guards is not None else ([] if (server.running() or {}).get("model") == key else
                                                       server.guard_failures(e, policy=pol, srv=server.srv_settings(cfg), free_ram=free_ram, exists=exists))
            if fails:
                problem = "llama server cannot start: " + "; ".join(fails)
        else:
            problem = f"unknown backend {be!r}"
        if problem is None and be == "ollama" and cur != key:
            from pflab.llm import server
            fr = server.free_ram_gb() if free_ram is None else free_ram
            need = float(e.get("ram_gb", 0.0)) + float(pol.get("ram_floor_gb", 6.0))
            if fr != fr or fr < need:
                problem = f"free RAM {fr:.1f} GB is under the {need:.1f} GB the model needs plus the floor"
        if problem:
            out = {"seat": name, "key": fb["key"], "model": fb["model"], "backend": fb["backend"], "options": fb["options"], "fallback": True,
                   "reason": f"{key}: {problem}; using {fb['key']}", "requested": key}
        else:
            out = {"seat": name, "key": key, "model": e["ollama"] if be == "ollama" else key, "backend": be, "options": dict(e.get("options") or {}),
                   "fallback": False, "reason": why, "requested": key}
    if cached:
        _CACHE[name] = (time.monotonic(), dict(out))
    return out


def alias_if_picked(seat_name: str) -> Optional[str]:
    """"seat:<name>" when a chosen pick is registered for the seat and the seats are on, else None (callers keep their own default). Never raises."""
    try:
        return f"{PREFIX}{seat_name}" if is_on() and chosen_pick(seat_name, load_picks()) else None
    except Exception:
        return None


def clear_cache() -> None:
    _CACHE.clear()


def chat_target(alias: str, *, health: Optional[Callable[[], bool]] = None, **kw) -> dict:
    """What `client.chat` calls for model "seat:fast": the seat, except that a llama-server seat whose server is not answering becomes the fallback
    (a call never waits on a server nobody started)."""
    name = alias[len(PREFIX):] if is_seat_name(alias) else alias
    s = seat(name, **kw)
    if s["backend"] == "llama_server":
        from pflab.llm import server
        up = health() if health else server.health()
        if not up:
            fb = _fallback(load_config() if kw.get("cfg") is None else kw["cfg"])
            return {**s, "key": fb["key"], "model": fb["model"], "backend": fb["backend"], "options": fb["options"], "fallback": True,
                    "reason": f"{s['key']}: the llama server is not running; using {fb['key']}"}
    return s


# --- modes ---------------------------------------------------------------------------------------------------------------

def seat_for_mode(mode: str, cfg: Optional[dict] = None) -> str:
    cfg = load_config() if cfg is None else cfg
    return str((cfg.get("mode_seat") or {}).get(mode) or "fast")


def for_mode(mode: str, *, now: Optional[float] = None, cfg: Optional[dict] = None, state: Optional[dict] = None, **seat_kw) -> dict:
    """The plan for `mode`: which seat should be resident and what to load/unload. A dry run (changes only the mode clock in STATE).
    action: 'keep' (already resident), 'swap' (unload `unload`, load `load`), 'hold' (hysteresis or the mode has not lasted long enough), 'none' (unknown mode)."""
    cfg = load_config() if cfg is None else cfg
    pol = cfg.get("policy") or {}
    st = STATE if state is None else state
    now = time.monotonic() if now is None else now
    with _LOCK:
        if st.get("mode") != mode:
            st["mode"], st["mode_since"] = mode, now
        if mode not in (cfg.get("mode_seat") or {}):
            return {"mode": mode, "want": None, "action": "none", "load": None, "unload": [], "reason": f"no seat is set for mode {mode!r}"}
        want = seat_for_mode(mode, cfg)
        other = "thinker" if want == "fast" else "fast"
        tgt = seat(want, cfg=cfg, resident_key=st.get("resident_key"), **seat_kw)
        oth = seat(other, cfg=cfg, resident_key=st.get("resident_key"), **seat_kw)
        res_key = st.get("resident_key")
        plan = {"mode": mode, "want": want, "target": tgt, "load": None, "unload": [], "action": "keep", "reason": ""}
        if res_key == tgt["key"]:
            plan["reason"] = f"{tgt['key']} is already resident"
            return plan
        swapped = st.get("swapped_at")
        if swapped is not None and now - float(swapped) < float(pol.get("hysteresis_s", 900)):
            plan.update(action="hold", reason=f"held: last swap {now - float(swapped):.0f} s ago (hysteresis {pol.get('hysteresis_s', 900)} s)")
            return plan
        since = st.get("mode_since")
        if res_key is not None and since is not None and now - float(since) < float(pol.get("mode_dwell_s", 120)):
            plan.update(action="hold", reason=f"held: mode {mode} has lasted {now - float(since):.0f} s (needs {pol.get('mode_dwell_s', 120)} s)")
            return plan
        plan["load"] = {"seat": want, "key": tgt["key"], "model": tgt["model"], "backend": tgt["backend"], "options": tgt["options"], "fallback": tgt["fallback"]}
        if res_key is not None:
            plan["unload"] = [_unload_spec(res_key, cfg)]
        elif oth["key"] != tgt["key"]:
            plan["unload"] = [_unload_spec(oth["key"], cfg)]                  # never both: the other seat's model is made absent too
        plan["action"] = "swap"
        plan["reason"] = f"mode {mode} wants {want} ({tgt['key']})" + (f"; {tgt['reason']}" if tgt["fallback"] else "")
        return plan


def _unload_spec(key: str, cfg: dict) -> dict:
    e = model_entry(key, cfg)
    return {"key": key, "backend": e["backend"], "model": e.get("ollama", key) if e["backend"] == "ollama" else key}


def ollama_transport_default():
    from pflab.llm import client
    return client.http_transport


def apply(plan: dict, *, cfg: Optional[dict] = None, transport: Optional[Callable] = None, now: Optional[float] = None, state: Optional[dict] = None,
          server_mod=None, dry_run: bool = False) -> List[dict]:
    """Carry out a 'swap' plan: unload the other model (Ollama keep_alive=0 or stop the llama server), then load the target (Ollama keep_alive preload, or start the
    llama server after every guard). Returns the events [{action, key, backend, applied, reason}]. A load that fails leaves the old state and says why."""
    cfg = load_config() if cfg is None else cfg
    pol = cfg.get("policy") or {}
    st = STATE if state is None else state
    tr = transport or ollama_transport_default()
    sv = server_mod
    if sv is None:
        from pflab.llm import server as sv
    events: List[dict] = []
    if plan.get("action") != "swap":
        return events
    now = time.monotonic() if now is None else now
    for u in plan.get("unload") or []:
        ev = {"action": "unload", "key": u["key"], "backend": u["backend"], "applied": False, "reason": ""}
        try:
            if dry_run:
                ev["reason"] = "dry run"
            elif u["backend"] == "ollama":
                tr("POST", "/api/generate", {"model": u["model"], "keep_alive": pol.get("unload_keep_alive", 0)}, 60)
                ev["applied"] = True
            else:
                ev["applied"] = bool(sv.stop())
        except Exception as e:
            ev["reason"] = f"{type(e).__name__}: {str(e)[:160]}"
        events.append(ev)
    ld = plan.get("load")
    if ld:
        ev = {"action": "load", "key": ld["key"], "backend": ld["backend"], "applied": False, "reason": ""}
        try:
            if dry_run:
                ev["reason"] = "dry run"
            elif ld["backend"] == "ollama":
                tr("POST", "/api/generate", {"model": ld["model"], "prompt": "", "keep_alive": pol.get("fast_keep_alive", "30m"), "stream": False}, 600)
                ev["applied"] = True
            else:
                e = model_entry(ld["key"], cfg)
                r = sv.start(ld["key"], e, policy=pol, srv=sv.srv_settings(cfg))
                ev["applied"] = bool(r.get("started") or r.get("already"))
        except Exception as ex:
            ev["reason"] = f"{type(ex).__name__}: {str(ex)[:200]}"
        events.append(ev)
        if ev["applied"]:
            with _LOCK:
                st["resident_seat"], st["resident_key"], st["swapped_at"] = ld["seat"], ld["key"], now
    return events


def log_events(con, market: str, now, mode: str, plan: dict, events: List[dict], free_ram: Optional[float] = None) -> int:
    """Keep the plan and what was done in `seat_event_s79` (one row per action; a 'keep'/'hold' plan is one row with applied false)."""
    from pflab.pm.store import next_id
    rows = events or [{"action": plan.get("action", "none"), "key": (plan.get("target") or {}).get("key"), "backend": (plan.get("target") or {}).get("backend"), "applied": False, "reason": plan.get("reason", "")}]
    for ev in rows:
        eid = next_id(con, "seat_event_s79", "event_id")
        con.execute("INSERT INTO seat_event_s79 VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [eid, market, now, mode, plan.get("want"), ev.get("key"), ev.get("backend"), ev.get("action"), bool(ev.get("applied")),
                     None if free_ram is None or free_ram != free_ram else float(free_ram), (ev.get("reason") or plan.get("reason") or "")[:300]])
    return len(rows)


def model_to_seat(model: str, cfg: Optional[dict] = None, picks: Optional[List[dict]] = None) -> str:
    """Which seat a logged model name belongs to ('fast', 'thinker', or 'other'); a model that serves both (the fallback) counts as 'fast'."""
    cfg = load_config() if cfg is None else cfg
    picks = load_picks() if picks is None else picks
    names = {}
    for s in SEATS:
        k, _ = requested_key(s, cfg, picks)
        e = model_entry(k, cfg)
        names.setdefault(s, {k, e.get("ollama", k), (e.get("ollama", k) or "") + ":latest"})
    fb = str((cfg.get("policy") or {}).get("fallback_model", FALLBACK))
    if model in names["thinker"] and model not in names["fast"]:
        return "thinker"
    if model in names["fast"] or model == fb:
        return "fast"
    return "other"
