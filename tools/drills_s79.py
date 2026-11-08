"""S79 phase 2 drills and the accelerated run, on a SYNTHETIC profile with an injectable clock (development only; never the investor's record).

    python tools/drills_s79.py run [--only kill9,net_down] [--out D:\\s79_scratch\\drills\\report.json] [--findings F.md] [--start 2026-10-08]
    python tools/drills_s79.py list

Each drill runs in its own child process on its own clone of one base profile (seed: tools/rehearse.py, then the A45 re-seed rehearsal, then a first
allocation target). The outside world is faked: no network (every request raises ConnectionError), a fake Ollama answering through `requests`, jobs that
fetch are replaced by fakes (the prices job "arrives" the next session's closes from rows held back from the profile). Nothing here touches the app,
the investor's store, the secrets file or the real Kite token. Result of a drill: {name, status PASS|FAIL|OFF|ERROR, evidence, world_says, findings}.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src", REPO / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
SCRATCH = Path(os.environ.get("S79_DRILLS_DIR", r"D:\s79_scratch\drills"))
DEFAULT_START = date(2026, 10, 8)            # a Thursday; Fri, (weekend), Mon, Tue follow: 10-20 is the only holiday near, and it is after
OLLAMA = "http://localhost:11434"
NEW_SYMBOL = "IN0020230099"                  # the synthetic inherited Sovereign Gold Bond


# --- small things -----------------------------------------------------------------------------------------------------------------------

class FakeClock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def set(self, t: datetime) -> datetime:
        self.t = t
        return t


class ErrorCatcher(logging.Handler):
    """Every pflab log record at ERROR, kept (a loop that logged an exception was not 'handled' silently)."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records: List[str] = []

    def emit(self, record):
        if record.name.startswith("pflab") or record.name.startswith("root"):
            txt = f"{record.name}: {record.getMessage()}"
            if record.exc_info:
                txt += " | " + "".join(traceback.format_exception_only(record.exc_info[0], record.exc_info[1])).strip()
            self.records.append(txt[:400])


class Check:
    """Evidence and findings of one drill."""

    def __init__(self, name: str):
        self.name, self.evidence, self.findings, self.world = name, [], [], []

    def ok(self, cond: bool, msg: str, where: str = "", how: str = "") -> bool:
        self.evidence.append(("ok: " if cond else "FAIL: ") + msg)
        if not cond:
            self.findings.append({"what": msg, "where": where or "(see evidence)", "how": how or f"python tools/drills_s79.py run --only {self.name}"})
        return bool(cond)

    def note(self, msg: str) -> None:
        self.evidence.append(msg)

    def says(self, msg: str) -> None:
        if msg and msg not in self.world:
            self.world.append(msg)

    def result(self, started: float, status: Optional[str] = None) -> dict:
        failed = any(e.startswith("FAIL:") for e in self.evidence)
        return {"name": self.name, "status": status or ("FAIL" if failed else "PASS"), "passed": not failed and status in (None, "PASS"),
                "evidence": self.evidence, "world_says": " | ".join(self.world), "findings": self.findings, "seconds": round(time.time() - started, 1)}


# --- the outside world, faked ------------------------------------------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.ok = data, status, status < 400
        self.text, self.headers, self.content = json.dumps(data), {}, json.dumps(data).encode()

    def json(self):
        return self._d

    def raise_for_status(self):
        if not self.ok:
            import requests
            raise requests.exceptions.HTTPError(f"{self.status_code}")


def _gen(schema: dict, prompt: str):
    """A value that satisfies a JSON schema (enough for the local jobs); a 'quote' is a line of the prompt itself."""
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type")
    if t == "object":
        props = schema.get("properties", {})
        out = {}
        for k, v in props.items():
            if k == "quote":
                lines = [ln.strip() for ln in prompt.splitlines() if len(ln.strip()) > 8]
                out[k] = lines[0][:120] if lines else "x"
            else:
                out[k] = _gen(v, prompt)
        return out
    if t == "array":
        return [_gen(schema.get("items", {}), prompt)] if schema.get("minItems", 0) >= 1 else []
    if t == "integer":
        return int(schema.get("minimum", 1))
    if t == "number":
        return float(schema.get("minimum", 0.0))
    if t == "boolean":
        return True
    return "ok"


def fake_chat_text(payload: dict) -> str:
    """What the fake local model says. Debate roles and their JSON steps follow the protocol of agents/debate.py; everything else is plain text with no figures."""
    msgs = payload.get("messages", [])
    sys_ = msgs[0]["content"] if msgs else ""
    user = msgs[-1]["content"] if msgs else ""
    fmt = payload.get("format")
    ids_vals = [(m.group(1), m.group(2).strip()) for m in __import__("re").finditer(r"\[F:([A-Za-z0-9_.\-]+)\][^\n=]*=\s*([^\n]+)", user)]
    if fmt is None and ("BULL analyst" in sys_ or "BEAR analyst" in sys_) and ids_vals:
        pick = ids_vals[:2] if "BULL" in sys_ else ids_vals[::-1][:2]
        return " ".join(f"The recorded value is {v} [F:{i}]." for i, v in pick)
    if fmt is not None:
        if "STANCE" in sys_:
            ids = [ln.split(".")[0] for ln in user.splitlines() if ln[:1] in "BR" and "." in ln[:4]]
            return json.dumps({"stances": [{"id": i, "stance": "favourable" if i[0] == "B" else "unfavourable"} for i in ids]})
        if "CONTRADICT" in sys_:
            return json.dumps({"disagreements": [{"topic": "is the move healthy", "bull": 1, "bear": 1}]})
        if "choose ONE warning" in sys_:
            ids = (user.split("EVIDENCE IDS:")[-1].split("\n")[0].replace(" ", "").split(",") if "EVIDENCE IDS:" in user else [])
            return json.dumps({"warn": True, "kind": "fall", "horizon_sessions": 5, "threshold_pct": 3, "because": ids[:1] or ["x"]})
        return json.dumps(_gen(fmt, user))
    return "The local model has nothing to add beyond the figures already shown; the data does not say why."


class Net:
    """No outside network at all, plus a fake Ollama at its usual address (down on request). Installed once per process."""

    def __init__(self):
        self.ollama_up = True
        self.chat_calls = 0
        self.blocked: List[str] = []
        self._orig: Dict[str, object] = {}

    def _tags(self):
        return {"models": [{"name": "qwen3:8b-q8_0", "digest": "fake-digest", "size": 1, "details": {"parameter_size": "8B", "quantization_level": "Q8_0"}},
                           {"name": "nomic-embed-text:latest", "digest": "fake-embed", "size": 1, "details": {}}]}

    def install(self) -> "Net":
        import requests
        net = self

        def request(self_, method, url, **kw):
            from pflab.llm import client
            if net.ollama_up and str(url).startswith(client.URL) and client.URL == OLLAMA:
                path = str(url)[len(OLLAMA):]
                if path.startswith("/api/tags"):
                    return FakeResponse(net._tags())
                if path.startswith("/api/chat"):
                    net.chat_calls += 1
                    return FakeResponse({"message": {"content": fake_chat_text(kw.get("json") or {})}, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 10})
                return FakeResponse({"embeddings": [[0.0] * 8]})
            net.blocked.append(str(url)[:80])
            raise requests.exceptions.ConnectionError(f"drill: network is down (getaddrinfo failed for {str(url)[:60]})")

        def urlopen(url, *a, **k):
            u = url if isinstance(url, str) else getattr(url, "full_url", str(url))
            if net.ollama_up and u.startswith(OLLAMA + "/api/tags"):
                import io
                return io.BytesIO(json.dumps(net._tags()).encode())
            net.blocked.append(u[:80])
            raise urllib.error.URLError("drill: network is down")

        def _loop(addr) -> bool:
            h = addr[0] if isinstance(addr, tuple) else str(addr)
            return str(h) in ("127.0.0.1", "localhost", "::1")

        def create_connection(address, *a, **k):
            if not _loop(address):
                net.blocked.append(str(address)[:60])
                raise ConnectionError("drill: network is down")
            return self._orig["create_connection"](address, *a, **k)

        self._orig = {"request": requests.sessions.Session.request, "urlopen": urllib.request.urlopen, "create_connection": socket.create_connection}
        requests.sessions.Session.request = request
        urllib.request.urlopen = urlopen
        socket.create_connection = create_connection
        return self

    def uninstall(self) -> None:
        import requests
        if self._orig:
            requests.sessions.Session.request = self._orig["request"]
            urllib.request.urlopen = self._orig["urlopen"]
            socket.create_connection = self._orig["create_connection"]
            self._orig = {}

    def ollama_down(self) -> None:
        from pflab.llm import client
        self.ollama_up = False
        client.URL = "http://127.0.0.1:9"

    def ollama_back(self) -> None:
        from pflab.llm import client
        self.ollama_up = True
        client.URL = OLLAMA


# --- the base profile (built once) and one clone per drill --------------------------------------------------------------------------------

def _is_session(d: date) -> bool:
    from pflab import markets
    return markets.get("IN").is_session(d)


def build_base(base: Path, start: date) -> dict:
    """tools/rehearse.py seed (real public ISINs, the workshop's real prices) -> the prices from `start` on are held back (they 'arrive' later) -> the A45 re-seed
    from synthetic Kite holdings (shares, an ETF, an inherited SGB, a gold ETF) on the session before `start` -> a first allocation target, reviewed -> a thesis."""
    import rehearse as rh
    from pflab import markets
    if base.exists():
        shutil.rmtree(base)
    os.environ["PFLAB_DATA_DIR"] = os.environ.get("PFLAB_DATA_DIR") or str(REPO / "data")
    rh.seed(base, 0.0)
    os.environ["PFLAB_PM_DIR"] = str(base / "pm")
    from pflab.paper import allocation, book, reseed
    from pflab.pm import store
    con = store.connect(base / "pm" / "ledger.duckdb")
    m = markets.get("IN")
    prev = m.previous_session(start)
    held = con.execute("SELECT * FROM prices WHERE date >= ?", [start]).df()
    con.execute("DELETE FROM prices WHERE date >= ?", [start])
    held.to_parquet(base / "held_prices.parquet")
    last = con.execute("SELECT max(date) FROM prices WHERE source='nse_bhavcopy'").fetchone()[0]
    con.execute("INSERT INTO prices VALUES (?, ?, 6150.0, 'GB', 'nse_bhavcopy', now())", [NEW_SYMBOL, last])
    held_sgb = [[NEW_SYMBOL, d, 6150.0 + i, "GB", "nse_bhavcopy", datetime.now()] for i, d in enumerate(sorted(held["date"].unique())) if _is_session(d)]
    import pandas as pd
    extra = pd.DataFrame(held_sgb, columns=list(held.columns))
    pd.concat([held, extra]).to_parquet(base / "held_prices.parquet")
    holdings = [dict(tradingsymbol="HINDUNILVR", exchange="NSE", isin=rh.ISINS["HINDUNILVR"][0], quantity=50, t1_quantity=0, average_price=2300.0, last_price=2400.0),
                dict(tradingsymbol="ITC", exchange="NSE", isin=rh.ISINS["ITC"][0], quantity=300, t1_quantity=0, average_price=380.0, last_price=410.0),
                dict(tradingsymbol="LT", exchange="NSE", isin=rh.ISINS["LT"][0], quantity=20, t1_quantity=0, average_price=3100.0, last_price=3500.0),
                dict(tradingsymbol="NIFTYBEES", exchange="NSE", isin=rh.ETFS["NIFTYBEES"], quantity=400, t1_quantity=0, average_price=250.0, last_price=270.0),
                dict(tradingsymbol="GOLDBEES", exchange="NSE", isin=rh.ETFS["GOLDBEES"], quantity=1500, t1_quantity=0, average_price=60.0, last_price=70.0),
                dict(tradingsymbol="SGBMAR33", exchange="NSE", isin=NEW_SYMBOL, quantity=6, t1_quantity=0, average_price=0.0, last_price=6150.0)]
    now = datetime.combine(prev, datetime.min.time()).replace(hour=21, minute=30)
    out = reseed.reseed(con, holdings, now, pm_dir=base / "pm", backup_dir=base / "backups")
    t = allocation.propose_allocation(con, {"equity": 55, "gold": 20, "international": 10, "cash": 15},
                                      "A drill split with its reasons given in a few plain sentences about gold and cash.", now, sectors={"FMCG": 20, "Capital Goods": 15})
    allocation.review_target(con, t["target_id"], "approve", "drill: the independent review is simulated", now)
    con.execute("INSERT INTO theses (thesis_id, created_at, text, keywords_json, sectors_json, hold_cash, expires, status) VALUES (1, ?, 'FMCG demand holds up', ?, ?, 0, ?, 'open')",
                [now, json.dumps(["fmcg", "consumer"]), json.dumps(["FMCG"]), start + timedelta(days=60)])
    con.execute("CHECKPOINT")
    meta = {"start": str(start), "seeded_on": str(out.get("seed_date")), "target_id": t["target_id"], "isins": [h["isin"] for h in holdings]}
    con.close()
    (base / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def process_setup(run_dir: Path) -> None:
    """Everything a drill process must not do for real: the real home, secrets, Kite token, a worker pool, a paid call."""
    os.environ.setdefault("PFLAB_DATA_DIR", str(REPO / "data"))
    os.environ["PFLAB_SECRETS_FILE"] = str(run_dir / "secrets_absent.toml")
    os.environ["PFLAB_NO_POOL"] = "1"
    for k in ("PFLAB_PAID", "PFLAB_LIVE"):
        os.environ.pop(k, None)
    from pflab.ingest import kite as km
    tok = run_dir / "kite_token.json"
    km.default_token_path = lambda: tok


class Env:
    """One drill's world: a clone of the base profile, a fake clock, a Runtime that is never started with threads, the fakes installed."""

    def __init__(self, name: str, run_root: Path, base: Path, connect: bool = True):
        from pflab import markets  # noqa: F401
        self.name, self.dir, self.base = name, run_root / name, base
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        shutil.copytree(base / "pm", self.dir / "pm")
        shutil.copy(base / "held_prices.parquet", self.dir / "held_prices.parquet")
        self.meta = json.loads((base / "meta.json").read_text(encoding="utf-8"))
        self.start = date.fromisoformat(self.meta["start"])
        self.pm, self.data = self.dir / "pm", Path(os.environ.get("PFLAB_DATA_DIR") or REPO / "data")
        os.environ["PFLAB_PM_DIR"] = str(self.pm)
        process_setup(self.dir)
        self.clock = FakeClock(datetime.combine(self.start, datetime.min.time()).replace(hour=6))
        self.catcher = ErrorCatcher()
        logging.getLogger().addHandler(self.catcher)
        self.exceptions: List[str] = []
        self.net = Net().install()
        self.con = None
        self.rt = None
        self.arrived: List[str] = []
        self.failed_jobs: List[tuple] = []
        if connect:
            self.connect()

    # --- store and runtime
    def connect(self) -> None:
        from pflab.app.runtime import Runtime
        from pflab.pm import secrets as sec, store
        self.con = store.connect(self.pm / "ledger.duckdb")
        self.rt = Runtime(self.pm, self.data, REPO, con=self.con, secrets=sec.Secrets({"kite": {"api_key": "fk-7731-key", "api_secret": "fk-7731-secret"}}), clock=self.clock)
        _fakes(self)

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass
        self.net.uninstall()
        logging.getLogger().removeHandler(self.catcher)

    def cur(self):
        return self.con.cursor()

    # --- the app opening: Runtime.start without its threads (the same on-open code)
    def open_app(self, t: datetime) -> None:
        import pflab.app.runtime as rtm
        self.clock.set(t)

        class NoThread:
            def __init__(self, target=None, name=None, daemon=None, **kw):
                self.name = name or ""

            def start(self):
                pass

            def join(self, t=None):
                pass
        real = rtm.threading.Thread
        rtm.threading.Thread = NoThread
        try:
            self.rt.start()
        finally:
            rtm.threading.Thread = real

    def safe(self, label: str, fn: Callable, *a, **k):
        """A loop body, called the way the app's loop calls it: an exception is recorded (the loop survives), never swallowed unseen."""
        try:
            return fn(*a, **k)
        except Exception:
            self.exceptions.append(f"{self.clock.t:%a %d %b %H:%M} {label}: " + traceback.format_exc(limit=4).strip().splitlines()[-1][:300])
            return None

    def step(self, t: datetime, *, continuous: bool = True, agenda_n: int = 2, hq: bool = False) -> dict:
        """One pass of the app's loops at fake time t: heart, scheduler (+ requested jobs), agenda, voice, paper team's tick. `continuous`: the heart has been
        beating (no wake)."""
        from pflab.agenda import runner
        from pflab.agents import voice
        from pflab.paper import manager
        self.clock.set(t)
        rt = self.rt
        if continuous:
            rt._beat = t - timedelta(seconds=30)
        out = {"t": t, "mode": None}
        out["catching_up"] = self.safe("beat", rt.beat)
        self.safe("run_wanted", rt.run_wanted)
        out["jobs"] = self.safe("scheduler_once", rt.scheduler_once) or []
        self.safe("run_wanted", rt.run_wanted)
        out["agenda"] = [self.safe("agenda", runner.tick, rt, t) for _ in range(agenda_n)]
        self.safe("voice", voice.sweep, self.cur(), t)
        self.safe("paper_tick", manager.tick, rt)
        if hq:
            from pflab.hq import service
            out["hq"] = self.safe("hq_round", service.round_, rt)
        for j in out["jobs"]:
            if j.status == "failed" and not j.detail.startswith("abandoned"):
                self.failed_jobs.append((f"{t:%a %d %b %H:%M}", j.job, j.detail[:200]))
        try:
            with open(self.dir / "progress.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} fake {t:%a %d %b %H:%M} jobs={[(j.job, j.status) for j in out['jobs']]} exc={len(self.exceptions)}\n")
        except OSError:
            pass
        return out

    def job_status(self, name: str) -> Optional[tuple]:
        return self.cur().execute("SELECT status, detail, started_at FROM job_runs WHERE job=? ORDER BY run_id DESC LIMIT 1", [name]).fetchone()

    def world(self) -> dict:
        from pflab.app import world, system
        system._CACHE.clear()
        return world.build(self.rt, self.clock.t)


# jobs replaced by fakes: they fetch, spawn collectors, send, call a paid model or take minutes. The rest of the registry runs for real.
FAKE_JOBS = ("instruments", "collect", "nav", "filings", "live", "tradecheck", "kg", "analyst", "research", "plans", "global", "outbox", "backup", "us_fx", "ledger",
             "deposits", "backfill", "hq", "conductor", "learner", "security", "selfcheck", "comove", "scans", "companion", "outgoing", "sandbox", "twin")
ARRIVAL_HOUR = (20, 15)            # NSE's files are in by the prices job's slot; a session's closes do not arrive before it


def available_through(now: datetime) -> date:
    """The latest session whose closes have arrived by `now` (same day 20:15 onwards)."""
    from pflab import markets
    m = markets.get("IN")
    d = now.date()
    if m.is_session(d) and (now.hour, now.minute) >= ARRIVAL_HOUR:
        return d
    return m.previous_session(d)


def arrive(env: "Env", upto: date) -> list:
    """Insert held-back price rows (and one news article a day for the thesis) for the sessions after what the store has, through `upto`."""
    import pandas as pd
    con = env.cur()
    have = con.execute("SELECT max(date) FROM prices WHERE source='nse_bhavcopy'").fetchone()[0]
    held = pd.read_parquet(env.dir / "held_prices.parquet")
    held["date"] = pd.to_datetime(held["date"]).dt.date
    days = sorted({d for d in held["date"].unique() if (have is None or d > have) and d <= upto})
    for d in days:
        rows = held[held["date"] == d]
        con.register("_arr", rows)
        try:
            con.execute("INSERT INTO prices SELECT * FROM _arr")
        finally:
            con.unregister("_arr")
        con.execute("INSERT OR IGNORE INTO kg_docs (doc_id, kind, title, source, published_at, ingested_at) VALUES (?, 'article', ?, 'drill', ?, ?)",
                    [f"drill-{d}", f"Consumer demand holds up in FMCG on {d}", datetime.combine(d, datetime.min.time()).replace(hour=18), env.clock.t])
        env.arrived.append(str(d))
    return [str(d) for d in days]


def _fakes(env: "Env") -> None:
    from dataclasses import replace
    from pflab.service import jobs, tasks  # noqa: F401
    import importlib
    import pkgutil
    import pflab.service as svc
    for m in pkgutil.iter_modules(svc.__path__):
        if m.name.startswith("tasks"):
            try:
                importlib.import_module(f"pflab.service.{m.name}")
            except Exception as e:  # a broken job module is itself a finding
                env.exceptions.append(f"import pflab.service.{m.name}: {type(e).__name__}: {e}")

    env.real_jobs = dict(jobs.REGISTRY)

    def fake(ctx):
        return {"drill_fake": "fetch/paid/heavy job replaced by a fake"}

    def prices(ctx):
        days = arrive(env, available_through(ctx.now))
        return {"drill_fake": "closes arrive from held rows", "days": days}
    for name, job in list(jobs.REGISTRY.items()):
        if name == "prices":
            jobs.REGISTRY[name] = replace(job, fn=prices)
        elif name in FAKE_JOBS:
            jobs.REGISTRY[name] = replace(job, fn=fake)
    from pflab.app import system
    from pflab.agents import sandbox as sb
    from pflab.agenda import kinds
    env.real_docker_probe, env.real_sb_status = system._docker_probe, sb.status
    system._docker_probe = lambda: "running"
    sb.status = lambda *a, **k: {"ok": True, "why": ""}
    kinds.backfill = lambda root, now, budget_s: {"fetched": 0, "errors": 0, "left": 0}


# --- drills ---------------------------------------------------------------------------------------------------------------------------------

DRILLS: Dict[str, Callable] = {}
ORDER: List[str] = []


def drill(name: str, minutes: float = 4.0):
    def deco(fn):
        fn.drill_name, fn.minutes = name, minutes
        DRILLS[name] = fn
        ORDER.append(name)
        return fn
    return deco


def dt(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m)


@drill("smoke", 5)
def drill_smoke(env: "Env", c: Check) -> None:
    env.open_app(dt(env.start, 6))
    r = env.step(dt(env.start, 7))
    c.ok(not env.exceptions, f"one step ran without an exception ({len(r['jobs'])} jobs due)")
    for j in r["jobs"]:
        c.note(f"job {j.job}: {j.status} {j.detail[:80]}")


def day_times(d: date) -> List[datetime]:
    """The fake clock's steps of one day: every hour 06:00-23:00 on a session day (all four modes), three on a closed day, one at night."""
    hours = [7, 10, 13, 16, 18, 21, 23] if _is_session(d) else [9, 19]          # pre_open, session x2, post_close, deep x3 (IN); a closed day twice
    return [dt(d, h) for h in hours]


def run_days(env: "Env", first: date, last: date, on_step: Optional[Callable] = None, **kw) -> list:
    out, d = [], first
    while d <= last:
        for t in day_times(d):
            if t < env.clock.t:
                continue
            r = env.step(t, **kw)
            out.append(r)
            if on_step:
                env.safe("on_step", on_step, env, t, r)
        d += timedelta(days=1)
    return out


S79B_ITEMS = ("situation", "macro_attribution", "wave_detector", "sentiment", "theme_exposure", "volume_profile", "construct", "benchmark", "provenance", "seats", "lenses")


def switches() -> dict:
    from pflab import _toml
    p = REPO / "configs" / "s79b.toml"
    try:
        return _toml.load(p)
    except Exception:
        return {}


def item_state(key: str, tool_names: list, job_names: list) -> dict:
    """OFF when [key] on = false in configs/s79b.toml; PRESENT when a tool, job or module of that name exists; else ABSENT (not built yet)."""
    import importlib
    cfg = switches().get(key, {})
    toks = {key, key.replace("_detector", ""), key.replace("_attribution", ""), key.replace("_exposure", ""), key.replace("_profile", "")}
    tools = [n for n in tool_names if any(t in n for t in toks)]
    jobs_ = [n for n in job_names if any(t in n for t in toks)]
    mod = None
    for m in (f"pflab.{key}", f"pflab.llm.{key}", f"pflab.fcast.{'plugins' if key == 'lenses' else key}", f"pflab.quant.{key}"):
        try:
            importlib.import_module(m)
            mod = m
            break
        except Exception:
            continue
    state = "OFF" if cfg.get("on") is False else "PRESENT" if (tools or jobs_ or mod) else "ABSENT"
    return {"item": key, "state": state, "tools": tools, "jobs": jobs_, "module": mod}


def tool_ctx(env: "Env", t: datetime):
    from pflab.hq import egress, tools as tl
    try:
        from pflab.hq import service
        gate = service.gate(env.rt)
    except Exception:
        gate = egress.Gate()
    return tl.Ctx(env.rt, None, "drill", False, {}, gate, t, role="research")


BUG_WORDS = ("TypeError", "KeyError", "AttributeError", "NameError", "IndexError", "UnboundLocalError", "ImportError", "ModuleNotFoundError", "ZeroDivisionError",
             "AssertionError", "BinderException", "CatalogException", "ParserException", "ConversionException", "OperationalError")


def sweep_tools(env: "Env", c: Check, t: datetime) -> dict:
    """Every READ tool in the registry, with the self-check's harmless input. A tool that answers an error that names a programming mistake is a finding; one that answers a
    stated 'no data here' is not."""
    import json as _json
    from pflab.hq import selfcheck, tools as tl
    ctx = tool_ctx(env, t)
    res = {}
    for name, tool in list(tl.TOOLS.items()):
        if tool.kind != "read":
            continue
        args = selfcheck.probe_args(env.cur(), name)
        if args is None:
            res[name] = "needs data this profile lacks"
            continue
        t0 = time.time()
        try:
            text, err = tl.run(ctx, name, args)
        except Exception as e:
            text, err = f"{type(e).__name__}: {e}", True
        bug = err and any(w in text[:200] for w in BUG_WORDS)
        res[name] = ("BUG " if bug else "error " if err else "ok ") + text[:80].replace("\n", " ") + f" ({time.time() - t0:.1f}s)"
        if bug:
            c.ok(False, f"read tool {name} answered a programming error: {text[:160]}", f"pflab/hq/tools*.py tool {name}", f"tools.run(ctx, {name!r}, {args})")
    return res


@drill("accelerated", 32)
def drill_accelerated(env: "Env", c: Check) -> None:
    """Five simulated sessions (Thu, Fri, weekend, Mon, Tue), the app open all the time."""
    from pflab import markets
    from pflab.agenda import items as agenda_items
    from pflab.agents import debate, questions, voice
    from pflab.fcast import replay, run as fr, weights as W
    from pflab.hq import tools as tl
    from pflab.paper import allocation, reseed
    from pflab.service import catchup, jobs
    m = markets.get("IN")
    thu = env.start
    fri = m.next_session(thu)
    mon = m.next_session(fri)
    tue = m.next_session(mon)
    c.note(f"sessions simulated: {thu} Thu, {fri} Fri, [weekend], {mon} Mon, {tue} Tue")
    # the re-seeded book and its allocation exist before the first minute
    rs = reseed.already(env.cur())
    c.ok(rs is not None, f"the account is the re-seeded one (seed date {rs and rs['seed_date']})", "paper/reseed.py")
    tgt = allocation.active_target(env.cur())
    c.ok(bool(tgt), "an approved allocation target exists for the system's own book", "paper/allocation.py")
    # replay: a short year inside 2012-2021, written with source 'replay'
    t0 = time.time()
    rp = env.safe("replay", replay.replay, env.cur(), "IN", date(2020, 1, 1), date(2020, 12, 31), None, None, env.data, dt(thu, 6), True)
    n_rp = env.cur().execute("SELECT count(*) FROM forecasts_s79 WHERE source='replay'").fetchone()[0]
    c.ok(bool(rp) and n_rp > 0, f"replay of 2020 ran in {time.time() - t0:.0f} s and wrote {n_rp} forecast rows (source 'replay')", "fcast/replay.py")
    # the app opens Thursday morning
    env.open_app(dt(thu, 6))
    state = {"modes": set(), "prim": set(), "agenda": [], "weights0": None}
    w0 = {h: W.current(env.cur(), "IN", h, "live", fr.F.names_for("IN", True)) for h in (1, 5, 20)}
    asked = {}

    def on_step(e: "Env", t: datetime, r: dict) -> None:
        state["modes"].add(m.mode(t))
        state["prim"].add(markets.primary(t)[1])
        state["agenda"] += [a for a in r["agenda"] if a]
        if t == dt(thu, 10) and "q" not in asked:
            asked["q"] = questions.ask(e.cur(), "paper", "drill:keep_gold", "Keep the gold ETF at its weight?", t, default="keep", deadline=dt(mon, 10), options=["keep", "trim"])
        if t == dt(fri, 18) and "debate" not in asked:
            asked["debate"] = debate.debate_symbol(e.rt, "IN", "HINDUNILVR", e.meta["isins"][0], t)
        if t == dt(tue, 21) and "tools" not in asked:
            asked["tools"] = sweep_tools(e, c, t)
    run_days(env, thu, tue, on_step=on_step)
    cur = env.cur()
    # 1. catch-up ran once on open and never again for the same session
    rows = cur.execute("SELECT market, to_session, state FROM catchup_s79 WHERE market='IN' ORDER BY catch_id").fetchall()
    done_sessions = [str(r[1]) for r in rows if r[2] == "done"]
    c.ok(len(done_sessions) == len(set(done_sessions)) and len(done_sessions) >= 1, f"catch-up rows are one per closed session, done: {done_sessions}", "service/catchup.py")
    first_job = cur.execute("SELECT min(started_at) FROM job_runs WHERE job='catch_up' AND status='ok'").fetchone()[0]
    c.ok(first_job is not None and first_job <= dt(thu, 7), f"the first catch-up finished at the first step after opening ({first_job})", "service/tasks_s79_catchup.py")
    # 2. every mode
    c.ok(state["modes"] >= set(markets.MODES), f"IN modes reached: {sorted(state['modes'])}; the system works by: {sorted(state['prim'])}", "markets.py")
    # 3. the agenda
    done = [a for a in state["agenda"] if a.get("state") == "done"]
    useful = [a for a in done if a.get("useful")]
    skipped = [a for a in state["agenda"] if a.get("state") == "skipped"]
    failed = [a for a in state["agenda"] if a.get("state") in ("failed", "error")]
    c.ok(bool(useful) or bool(skipped), f"agenda: {len(done)} acts done ({len(useful)} useful), {len(skipped)} skipped with a reason, {len(failed)} failed", "agenda/runner.py")
    for a in failed[:3]:
        c.note(f"agenda failure: {a.get('kind')} {a.get('error')}")
    states = {a.get("state") for a in state["agenda"]}
    c.note(f"agenda states seen: {sorted(str(s) for s in states)}")
    # 4. forecasts made and scored, weights moving
    made = {str(r[0]) for r in cur.execute("SELECT DISTINCT as_of FROM forecasts_s79 WHERE market='IN' AND source='live'").fetchall()}
    want = {str(d) for d in (thu, fri, mon, tue)}
    c.ok(want <= made, f"live forecasts exist for each simulated session (missing: {sorted(want - made)})", "fcast/run.py post_close")
    sc = cur.execute("SELECT count(*), count(DISTINCT forecast_id) FROM forecast_scores_s79 WHERE source='live'").fetchone()
    c.ok(sc[0] > 0 and sc[0] == sc[1], f"forecasts scored: {sc[0]} scores for {sc[1]} forecasts (no double scoring)", "fcast/score.py")
    w1 = {h: W.current(cur, "IN", h, "live", fr.F.names_for("IN", True)) for h in (1, 5, 20)}
    moved = [h for h in w0 if any(abs(w0[h][k] - w1[h][k]) > 1e-9 for k in w0[h])]
    c.ok(bool(moved), f"Hedge weights moved for horizons {moved}; updates {[W.n_updates(cur, 'IN', h, 'live') for h in (1, 5, 20)]}", "fcast/run.py update_weights")
    # 5. the question sent and defaulted
    q = asked.get("q")
    qs = cur.execute("SELECT q.status, t.sent_at, t.resolved_by FROM questions q JOIN question_terms_s79 t USING (q_id) WHERE q.q_id=?", [q]).fetchone() if q else None
    c.ok(bool(qs) and qs[1] is not None and qs[0] == "defaulted" and qs[2] == "default", f"question {q}: {qs}; effective = {voice.effective(cur, 'drill:keep_gold')}", "agents/voice.py")
    # 6. the debate
    d = asked.get("debate") or {}
    c.ok(bool(d.get("debate_id")) or bool(d.get("skipped")), f"debate: status {d.get('status') or d.get('skipped')}, {len(d.get('disagreements') or [])} disagreement(s), warning {bool(d.get('bear_warning'))}", "agents/debate.py")
    # 7. the paper book
    pd_ = cur.execute("SELECT count(*), min(day), max(day) FROM paper_days").fetchone()
    c.ok(pd_[0] >= 3, f"the re-seeded book was valued day by day: {pd_}", "paper/manager.py bookkeeping")
    # 8. tools: transmission, implied, fall risk, forecasts
    tools = asked.get("tools") or {}
    for name in ("transmission", "lead_lag", "implied_dist", "cascade", "fall_risk", "forecast_now", "forecast_scoreboard", "system_allocation", "agenda"):
        if name in tl.TOOLS:
            c.ok(not str(tools.get(name, "ok")).startswith("BUG"), f"tool {name}: {tools.get(name, 'not swept')[:110]}", f"hq/tools_s79 ({name})")
    c.note("all read tools: " + "; ".join(f"{k}={v[:30]}" for k, v in tools.items())[:1500])
    # 9. items of tonight
    for key in S79B_ITEMS:
        st = item_state(key, list(tl.TOOLS), list(jobs.REGISTRY))
        c.note(f"item {key}: {st['state']} tools={st['tools']} jobs={st['jobs']} module={st['module']}")
    # 10. zero unhandled exceptions
    c.ok(not env.exceptions, f"unhandled exceptions from the loops: {env.exceptions[:5]}", "(the loop named in the evidence)")
    c.ok(not env.catcher.records, f"errors logged by pflab: {env.catcher.records[:5]}", "(the logger named in the evidence)")
    from pflab.service import jobs as _jobs
    allbad = cur.execute("SELECT job, detail FROM job_runs WHERE status='failed' AND detail NOT LIKE 'abandoned%' ORDER BY run_id").fetchall()
    off = sorted({j for j, dd in allbad if _jobs.offline(dd or "")})
    bad = [(j, dd) for j, dd in allbad if not _jobs.offline(dd or "")]
    if off:
        c.note(f"jobs that failed only because this harness has no network (see the net_down drill): {off}")
    seen = set()
    uniq = [(j, dd) for j, dd in bad if not (j in seen or seen.add(j))]
    c.ok(not bad, f"jobs recorded failed for a reason that is not the network: {[(j, (dd or '')[:140]) for j, dd in uniq[:8]]} ({len(bad)} runs)", "service/jobs run_job: the job named in the evidence")
    api = cur.execute("SELECT count(*) FROM api_calls WHERE status IN ('done','submitted','running')").fetchone()[0]
    c.ok(api == 0, f"no paid call was made ({api})", "hq/governor.py, guard.py")
    w = env.world()
    c.ok(w["errors"] == {}, f"the World payload has no failed section ({w['errors']})", "app/world.py")
    c.says(f"pulse: {w['pulse']['verdict']} | catch-up: {[(x['market'], x['state'], x['stage']) for x in w['pulse'].get('catch_up', {}).get('markets', [])]}")


def run_until(env: "Env", first: date, stop: datetime, **kw) -> None:
    d = first
    while d <= stop.date():
        for t in day_times(d):
            if t > stop:
                return
            if t >= env.clock.t:
                env.step(t, **kw)
        d += timedelta(days=1)


def off_drill(env: "Env", c: Check, resume: datetime, label: str) -> None:
    """The app is open Thursday morning to Friday 16:00, then off until `resume`, then opened again (a new process: Runtime.start's on-open code)."""
    from pflab import markets
    from pflab.service import away, presence
    m = markets.get("IN")
    thu = env.start
    fri = m.next_session(thu)
    env.open_app(dt(thu, 6))
    run_until(env, thu, dt(fri, 16))
    cur = env.cur()
    before = cur.execute("SELECT count(*) FROM forecasts_s79 WHERE source='live'").fetchone()[0]
    last_beat = cur.execute("SELECT max(last_beat) FROM app_presence_s79").fetchone()[0]
    c.note(f"app was open until {last_beat}; {before} live forecast rows so far; the laptop is now off until {resume}")
    # off: nothing runs. A new process opens the app.
    env.con.close()
    env.connect()
    env.open_app(resume)
    seg = env.cur().execute("SELECT off_from, off_to FROM app_presence_s79 ORDER BY seg_id DESC LIMIT 1").fetchone()
    c.ok(seg[0] is not None and seg[1] == resume, f"the gap is recorded as '{presence.describe(seg[0], seg[1]) if seg[0] else None}'", "service/presence.py")
    w0 = env.world()
    c.says(f"{w0['pulse'].get('catch_up', {}).get('off')} | catching up: {w0['pulse'].get('catching_up')}")
    c.ok(bool(w0["pulse"].get("catch_up", {}).get("off")), "the World screen says the app was off, from when to when", "app/world.py pulse.catch_up")
    steps = []
    first = True
    for h in range(resume.hour, 23):
        t = resume.replace(hour=h, minute=0 if h > resume.hour else resume.minute)
        steps.append(env.step(t, continuous=not first))
        first = False
    steps.append(env.step(resume.replace(hour=23, minute=30)))
    cur = env.cur()
    runs = dict(cur.execute("SELECT job, count(*) FROM job_runs WHERE started_at >= ? GROUP BY 1", [resume]).fetchall())
    worst = max(runs.items(), key=lambda kv: kv[1]) if runs else ("-", 0)
    c.ok(worst[1] <= len(steps), f"no stampede: on the day of opening no job ran more often than there were ticks ({len(steps)}); the most was {worst[0]} x{worst[1]}; the first tick started {len(steps[0]['jobs'])} jobs", "service/jobs.py tick, service/ondemand.py AFTER")
    slow = sorted(((j, round(float(s), 1)) for j, s in cur.execute(
        "SELECT job, sum(date_diff('millisecond', started_at, finished_at)) / 1000.0 FROM job_runs WHERE started_at >= ? AND finished_at IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 4", [resume]).fetchall()), key=lambda x: -x[1])
    c.note(f"most time spent on the opening day by job (wall seconds, real clock): {slow}")
    digest = cur.execute("SELECT count(*) FROM away_digest_s79").fetchone()[0]
    c.ok(digest == 1 and away.maybe_send(cur, env.clock.t) is None, f"the 'while you were away' digest was written once ({digest}) and not again", "service/away.py, tasks_s79_catchup.py")
    d = away.latest(cur)
    if d:
        c.says(d["text"].splitlines()[0])
    order = [str(r[0]) for r in cur.execute("SELECT as_of FROM forecasts_s79 WHERE source='live' AND market='IN' AND forecaster IN ('naive','volatility','momentum','reversion') GROUP BY as_of ORDER BY min(forecast_id)").fetchall()]
    c.ok(order == sorted(order), f"sessions were forecast in order (core forecasters, by row id): {order[-8:]}", "fcast/run.py catch_up")
    odd = [str(r[0]) for r in cur.execute("SELECT DISTINCT as_of FROM forecasts_s79 WHERE source='live' AND market='IN'").fetchall() if not m.is_session(r[0])]
    c.ok(not odd, f"no live forecast is dated on a day that is not a session (found: {odd})", "fcast/plugins.py or fcast/run.py: a writer that takes dates from the index series instead of the market calendar (rows for 2026-10-02, a holiday in configs/market_holidays.toml)")
    nowrong = cur.execute("SELECT count(*) FROM forecasts_s79 WHERE source='live' AND made_at > ?", [env.clock.t + timedelta(days=1)]).fetchone()[0]
    c.ok(nowrong == 0, f"forecast rows carry the simulated time as made_at ({nowrong} rows were stamped with the real wall clock)", "service/catchup.py run: fcast.run.catch_up(con, market, closed) is called without now=, so made_at is datetime.now() and the injected clock is ignored")
    sc = cur.execute("SELECT count(*), count(DISTINCT forecast_id) FROM forecast_scores_s79 WHERE source='live'").fetchone()
    c.ok(sc[0] == sc[1], f"no forecast was scored twice ({sc[0]} scores, {sc[1]} forecasts)", "fcast/score.py")
    from pflab.fcast import run as fr
    n_f0 = cur.execute("SELECT count(*) FROM forecasts_s79 WHERE source='live'").fetchone()[0]
    sc_0 = cur.execute("SELECT count(*) FROM forecast_scores_s79 WHERE source='live'").fetchone()[0]
    again = fr.catch_up(cur, "IN", m.session_closed_by(env.clock.t), now=env.clock.t)
    n_f1 = cur.execute("SELECT count(*) FROM forecasts_s79 WHERE source='live'").fetchone()[0]
    sc_1 = cur.execute("SELECT count(*) FROM forecast_scores_s79 WHERE source='live'").fetchone()[0]
    c.ok(n_f1 == n_f0 and sc_1 == sc_0, f"a second catch-up pass changed nothing (forecasts {n_f0}->{n_f1}, scores {sc_0}->{sc_1}; it re-walked {len(again['sessions_done'])} session(s))", "fcast/run.py catch_up idempotence")
    sc2 = cur.execute("SELECT count(*), count(DISTINCT forecast_id) FROM forecast_scores_s79 WHERE source='live'").fetchone()
    c.ok(sc2[0] == sc2[1], f"still one score per forecast after the second pass ({sc2})", "fcast/score.py")
    avail = available_through(env.clock.t)
    made = cur.execute("SELECT max(as_of) FROM forecasts_s79 WHERE source='live'").fetchone()[0]
    c.ok(made is not None and made >= avail, f"forecasts are up to date for the sessions whose closes arrived (latest {made}, closes in the store through {avail})", "fcast/run.py")
    api = cur.execute("SELECT count(*) FROM api_calls WHERE status IN ('done','submitted','running')").fetchone()[0]
    c.ok(api == 0, f"no stampede of paid calls ({api})", "hq/governor.py")
    late = cur.execute("SELECT count(*) FROM outbox WHERE kind='summary' AND dedup_key NOT LIKE 'away:%' AND dedup_key NOT LIKE 'week_check:%' AND created_at >= ?", [resume]).fetchone()[0]
    c.ok(late <= 2, f"after opening only the day's own summaries were queued, not the missed ones ({late} queued since {resume:%a %H:%M}; at most morning and evening)", "service/ondemand.py STALE_SLOT_H")
    c.ok(not env.exceptions and not env.catcher.records, f"zero unhandled exceptions: {env.exceptions[:3]} {env.catcher.records[:3]}", "(named in evidence)")
    w = env.world()
    c.ok(w["errors"] == {}, f"World payload sections all built ({w['errors']})", "app/world.py")
    c.says(f"pulse: {w['pulse']['verdict']}")
    c.note(f"[{label}]")


@drill("off_fri_mon", 22)
def drill_off_fri_mon(env: "Env", c: Check) -> None:
    from pflab import markets
    m = markets.get("IN")
    fri = m.next_session(env.start)
    off_drill(env, c, dt(m.next_session(fri), 9), "Friday 16:00 to Monday 09:00")


@drill("off_10_days", 22)
def drill_off_10_days(env: "Env", c: Check) -> None:
    from pflab import markets
    m = markets.get("IN")
    fri = m.next_session(env.start)
    resume = dt(fri + timedelta(days=10), 9)
    off_drill(env, c, resume, "ten days off")
    # a first run (no forecasts at all) after a long time away is bounded by max_back
    from pflab.fcast import run as fr
    cur = env.cur()
    cur.execute("DELETE FROM forecasts_s79 WHERE source='live'")
    r = fr.catch_up(cur, "IN", m.session_closed_by(env.clock.t), now=env.clock.t, max_back=10)
    c.ok(len(r["sessions_done"]) <= 10, f"an unseen first run after 10 days starts at most max_back=10 sessions back ({len(r['sessions_done'])} done)", "fcast/run.py catch_up")


def run_real_job(env: "Env", name: str, data_root: Optional[Path] = None):
    from pflab.service import jobs
    ctx = jobs.Ctx(env.cur(), env.clock.t, env.pm, data_root or env.data, REPO, sys.executable, env.rt.secrets)
    return jobs.run_job(ctx, env.real_jobs[name])


@drill("net_down", 14)
def drill_net_down(env: "Env", c: Check) -> None:
    """Every request raises ConnectionError (the fake network is down all the time; here the fetching jobs run for real against an empty data folder)."""
    import subprocess as sp
    from pflab import markets
    m = markets.get("IN")
    env.open_app(dt(env.start, 6))
    env.step(dt(env.start, 7))
    t = dt(m.next_session(env.start), 21)
    env.clock.set(t)
    empty = env.dir / "empty_data"
    empty.mkdir(exist_ok=True)
    real_run = sp.run

    def shim(cmd, *a, **k):
        if isinstance(cmd, (list, tuple)) and any("collect_daily.py" in str(x) for x in cmd):
            return sp.CompletedProcess(cmd, 1, stdout="  bhavcopy           FAIL ConnectionError: HTTPSConnectionPool(host='nsearchives.nseindia.com'): NameResolutionError getaddrinfo failed\n", stderr="")
        return real_run(cmd, *a, **k)
    sp.run = shim
    rows = {}
    try:
        for name in ("collect", "global", "us_fx", "nav", "filings", "instruments", "backfill"):
            if name not in env.real_jobs:
                continue
            t0 = time.time()
            r = run_real_job(env, name, empty)
            rows[name] = (r.status, r.detail[:140], round(time.time() - t0, 1))
    finally:
        sp.run = real_run
    from pflab.service import jobs as _jobs
    for name, (st, det, secs) in rows.items():
        offline = st in ("skipped", "offline") and ("offline" in det or "waiting" in det or "no holdings" in det)       # S79b: a Daily job without a connection is the status "offline"
        if st == "failed" and not _jobs.offline(det):          # failed on the harness's empty data folder, not for lack of a network: said, not judged
            c.note(f"{name}: failed for a non-network reason on the empty data folder ({det[:90]})")
            continue
        fine = offline or (st == "ok")
        c.ok(fine, f"{name}: {st} in {secs}s - {det[:100]}", f"service/jobs.py run_job (only Interval jobs become 'skipped: offline'; a Daily job whose every part lost its connection is recorded failed); job {name} in service/tasks.py",
             f"python tools/drills_s79.py run --only net_down")
    w = env.world()
    jobs_view = {j["job"]: j for j in w["jobs"]}
    for name in rows:
        j = jobs_view.get(name)
        if j:
            c.says(f"{name}: {j['state']} ({(j['last'] or {}).get('detail') or j['why']})"[:140])
    # work continues: the offline-safe jobs and the loops after it
    after = env.step(t + timedelta(minutes=30))
    ok_jobs = [x.job for x in after["jobs"] if x.status == "ok"]
    c.ok(not any(isinstance(a, dict) and a.get("state") == "error" for a in after["agenda"]), f"the agenda still ticks ({[a.get('state') for a in after['agenda'] if a]})", "agenda/runner.py")
    c.note(f"jobs that ran after (no network needed): {ok_jobs}")
    off_failed = sorted({n for _, n, d in env.failed_jobs if _jobs.offline(d)})
    c.ok(not off_failed, f"jobs of the normal tick whose every failure is a lost connection are recorded 'failed' (an alert for an offline laptop) instead of 'skipped: offline': {off_failed}",
         "service/jobs.py run_job only converts a job whose schedule is an Interval and whose parts ALL failed offline; a job that also reports a non-failed error part (e.g. data_s79b) stays 'failed'")
    c.ok(len(env.net.blocked) > 0, f"the requests really were refused ({len(env.net.blocked)}): {env.net.blocked[:2]}", "tools/drills_s79.py Net")
    c.ok(not env.exceptions, f"no exception escaped a loop: {env.exceptions[:3]}", "(named)")


@drill("ollama_down", 14)
def drill_ollama_down(env: "Env", c: Check) -> None:
    from pflab.agenda import runner
    from pflab.agents import debate
    from pflab.hq import explain
    from pflab.llm import client
    env.open_app(dt(env.start, 6))
    env.step(dt(env.start, 7))
    t = dt(env.start, 17, 30)
    env.clock.set(t)
    ok_reply = client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "hi"}])
    c.ok(bool(ok_reply.text), "the fake local model answers while it is up", "tools/drills_s79.py Net")
    env.net.ollama_down()
    try:
        client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "hi"}])
        c.ok(False, "the local client raised nothing with Ollama down", "llm/client.py")
    except client.OllamaError as e:
        c.ok("not reachable" in str(e), f"the client says so in words: {str(e)[:100]}", "llm/client.py")
    w = env.world()
    loc = [x for x in w["checks"] if x["name"] == "Local model"]
    c.ok(bool(loc) and loc[0]["state"] == "down", f"World: {loc[0]['state'] if loc else None} - {loc[0]['detail'] if loc else ''}", "app/system.py connectors", "")
    c.says(loc[0]["detail"] if loc else "")
    sym = "HINDUNILVR"
    ex = explain.explain_move(env.rt, "IN", sym, env.start, t)
    c.ok(ex.get("source") == "code" and bool(ex.get("text")), f"explain_move falls back to the code paragraph (source={ex.get('source')}, model_error={ex.get('model_error')})", "hq/explain.py")
    c.ok(bool(ex.get("model_error")), "...and says the model was away (model_error recorded)", "hq/explain.py")
    d = debate.debate_symbol(env.rt, "IN", sym, env.meta["isins"][0], t)
    c.ok(d.get("skipped") == "local model unavailable", f"debate degrades: {d.get('skipped') or d.get('status')}", "agents/debate.py")
    # an agenda item that needs the model: a flagged filing with text
    txt = env.dir / "filing.txt"
    txt.write_text("Board approves a capacity expansion. The company will add a plant.", encoding="utf-8")
    cur = env.cur()
    cur.execute("INSERT INTO kg_docs (doc_id, kind, title, source, published_at, text_path, ingested_at) VALUES ('drill-f1', 'filing', 'Capacity expansion', 'drill', ?, ?, ?)", [t, str(txt), t])
    cur.execute("INSERT INTO research_flags VALUES (1, ?, 'HINDUNILVR', 'material_filing', ?, ?, 'drill-f1', 'capacity expansion announced')", [env.meta["isins"][0], t, t])
    runner._LAST_REFILL.clear()
    outs = [runner.tick(env.rt, t + timedelta(minutes=i), mode="deep") for i in range(4)]
    states = [(o.get("kind"), o.get("state"), (o.get("error") or o.get("why") or "")[:70]) for o in outs]
    c.note(f"agenda ticks with Ollama down: {states}")
    c.ok(not any(o.get("state") == "error" for o in outs), "the agenda loop never raised", "agenda/runner.py")
    hit = [o for o in outs if o.get("kind") == "read_flagged_filing"]
    if hit:
        c.ok(hit[0]["state"] in ("failed", "skipped"), f"the item that needs the model is recorded as {hit[0]['state']}: {hit[0].get('error') or hit[0].get('why')}", "agenda/kinds.py")
        snap = runner.snapshot(env.cur(), t + timedelta(minutes=5))
        shown = json.dumps(snap, default=str)
        c.ok("Ollama" in shown or "read_flagged_filing" in shown, "the World's agenda panel mentions what could not be done", "agenda/runner.py snapshot (shows recent_done and recent_skipped, not failed items)")
    env.net.ollama_back()
    runner._LAST_REFILL.clear()
    after = runner.tick(env.rt, t + timedelta(minutes=30), mode="deep")
    c.ok(after.get("state") != "error", f"after Ollama is back the agenda continues ({after.get('state')})", "agenda/runner.py")
    c.ok(not env.exceptions and not env.catcher.records, f"no unhandled exception: {env.exceptions[:2]} {env.catcher.records[:2]}", "(named)")


@drill("docker_down", 12)
def drill_docker_down(env: "Env", c: Check) -> None:
    import shutil as sh
    import subprocess as sp
    from pflab.agents import sandbox as sb
    from pflab.app import system
    env.open_app(dt(env.start, 6))
    env.step(dt(env.start, 7))
    t = dt(env.start, 12)
    env.clock.set(t)
    real_run, real_which = sp.run, sh.which

    def shim(cmd, *a, **k):
        if isinstance(cmd, (list, tuple)) and cmd and str(cmd[0]) == "docker":
            return sp.CompletedProcess(cmd, 1, stdout=b"", stderr=b"error during connect: Docker Desktop is not running")
        return real_run(cmd, *a, **k)
    sp.run = shim
    sh.which = lambda n, *a, **k: "docker.exe" if n == "docker" else real_which(n, *a, **k)
    system._docker_probe = env.real_docker_probe
    sb.status = env.real_sb_status
    real_probe, real_rebuild = sb.probe, sb.rebuild_image
    sb.probe = lambda *a, **k: real_probe(shim, *a[1:] if a else (), **k)          # (the probe's runner default is bound when the module loads)
    sb.rebuild_image = lambda root, runner=shim, *a, **k: real_rebuild(root, shim, *a, **k)
    try:
        system._CACHE.clear()
        st = sb.status(shim, force=True)
        c.ok(st["ok"] is False and "not running" in st["why"], f"sandbox status says: {st}", "agents/sandbox.py status")
        sb._cache.update({"at": time.time(), "ok": False, "why": st["why"]})
        state, words = system.sandbox_line(env.cur(), t)
        c.ok(state != "ok" and "Docker" in words, f"System screen: {state} - {words}", "app/system.py sandbox_line")
        c.says(words)
        w = env.world()
        node = [n for n in w["guard_nodes"] if n["id"] == "sandbox"]
        c.ok(bool(node) and node[0]["state"] in ("waiting", "down") and "Docker" in node[0]["sub"], f"World guard node: {node[0]['state']} - {node[0]['sub']}" if node else "no sandbox node", "app/world.py guards_view")
        t0 = time.time()
        r = run_real_job(env, "sandbox")
        c.ok(time.time() - t0 < 60 and r.status in ("failed", "skipped") and ("docker" in r.detail.lower() or "sandbox" in r.detail.lower()),
             f"the sandbox probe job did not hang ({time.time() - t0:.1f}s) and recorded {r.status}: {r.detail[:120]}", "service/tasks.py _sandbox_probe")
        c.says(f"sandbox job: {r.status} {r.detail[:100]}")
        c.ok(sb.available(shim, force=True) is False, "calculations are not available (sb.available is False): nothing is run outside a container", "agents/sandbox.py")
    finally:
        sp.run, sh.which = real_run, real_which
        sb.probe, sb.rebuild_image = real_probe, real_rebuild
    after = env.step(t + timedelta(minutes=30))
    fj = [(j.job, j.detail[:90]) for j in after["jobs"] if j.status == "failed"]
    c.ok(not env.exceptions, f"the loops continued with Docker down: {len(after['jobs'])} jobs due ran; failed: {fj}", "(named)")


@drill("kite_logged_out", 12)
def drill_kite_logged_out(env: "Env", c: Check) -> None:
    from pflab import markets
    from pflab.app import runtime as rtm, system
    from pflab.ingest import kite as km
    from pflab.service import jobs
    m = markets.get("IN")
    thu = env.start
    fri = m.next_session(thu)
    env.open_app(dt(thu, 6))
    km.TokenStore().save("drill-token", dt(thu, 8))
    t = dt(thu, 10)
    env.clock.set(t)
    c.ok(rtm.token_valid(t), "a token saved Thursday 08:00 is valid Thursday 10:00", "ingest/kite.py")
    k1 = [x for x in system.connectors(env.rt, t) if x["id"] == "kite"][0]
    c.note(f"Kite while logged in: {k1['state']} - {k1['line']}")
    t2 = dt(fri, 7)
    env.clock.set(t2)
    c.ok(not rtm.token_valid(t2), "the token has lapsed Friday 07:00 (Zerodha tokens end at 06:00)", "ingest/kite.py token_expiry")
    k2 = [x for x in system.connectors(env.rt, t2) if x["id"] == "kite"][0]
    c.ok(k2["state"] != "ok" and "not logged in" in k2["line"], f"System screen: {k2['state']} - {k2['line']}", "app/system.py connectors")
    c.says(k2["line"])
    c.ok(env.rt.live_once() == 0, "the live poller does nothing, quietly, without a login", "app/runtime.py live_once")
    t3 = dt(fri, 17)
    env.clock.set(t3)
    r = run_real_job(env, "bars_1m")
    c.ok(r.status == "skipped" and "kite" in r.detail.lower(), f"bars_1m: {r.status} - {r.detail[:100]}", "service/tasks_s79_bars.py")
    c.says(f"bars_1m: {r.detail[:80]}")
    step = env.step(dt(fri, 18))
    c.ok(not env.exceptions, f"the loops continued ({len(step['jobs'])} jobs due ran)", "(named)")
    login = [n for n in jobs.REGISTRY if n == "kite_token" or ("kite" in n and "login" in n)]
    if not login:
        c.note("OFF/ABSENT: no Kite-login question job in the registry (agent K's service/tasks_s79_kitelogin.py)")
        return
    cur = env.cur()
    open_n, keys, sent = [], [], []
    for tt in (dt(fri, 9), dt(fri, 12), dt(fri, 15), dt(fri + timedelta(days=1), 9)):
        env.clock.set(tt)
        jobs.run_job(jobs.Ctx(cur, tt, env.pm, env.data, REPO, sys.executable, env.rt.secrets), jobs.REGISTRY[login[0]])
        open_n.append(cur.execute("SELECT count(*) FROM questions WHERE subject_key LIKE 'kite_login:%' AND status='open'").fetchone()[0])
        keys.append(cur.execute("SELECT string_agg(subject_key, ',') FROM questions WHERE subject_key LIKE 'kite_login:%' AND status='open'").fetchone()[0])
    sent = cur.execute("SELECT count(*) FROM outbox WHERE kind='question' AND text LIKE 'Kite is logged out%'").fetchone()[0]
    c.ok(open_n == [1, 1, 1, 1] and f"kite_login:{fri}" in str(keys[0]) and f"kite_login:{fri + timedelta(days=1)}" in str(keys[3]),
         f"the login question appears once a day (Friday 09:00, 12:00, 15:00 then Saturday 09:00): open {open_n}, keys {keys[0]} -> {keys[3]}", "service/tasks_s79_kitelogin.py")
    c.ok(sent <= 2, f"it was sent on Telegram at most once a day ({sent} messages for two days)", "agents/voice.py, service/tasks_s79_kitelogin.py")
    w = env.world()
    c.says("Needs: " + "; ".join(str(n)[:90] for n in w.get("needs", []))[:240])


@drill("budget_exhausted", 10)
def drill_budget(env: "Env", c: Check) -> None:
    from pflab import guard
    from pflab.agenda import kinds, runner
    from pflab.agents import analyst as an
    from pflab.hq import governor as gv, workers
    from pflab.pm.store import next_id
    os.environ["PFLAB_PAID"] = "1"          # only so the workshop guard does not answer first; nothing paid is ever sent here
    (env.pm / "api_budget.toml").write_text("[api]\nmodel = \"claude-opus-5-5\"\nmonthly_cap_rupees = 2500\ndev_monthly_cap_rupees = 100\nask_above_rupees = 100\nusd_inr = 90.0\nadopted = true\n"
                                           "[egress]\nnames = [\"synthname\"]\naddress = []\n", encoding="utf-8")
    env.open_app(dt(env.start, 6))
    t = dt(env.start, 21)
    env.clock.set(t)
    cur = env.cur()
    cid = next_id(cur, "api_calls", "call_id")
    cur.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, status, cost_inr, finished_at, agent) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [cid, t - timedelta(hours=3), "live", "m", "drill", "q", "x", "{}", "done", 100.0, t - timedelta(hours=3), "brain"])
    cfg = an.config()
    c.ok(guard.blocked("paid") is None, "(the workshop guard stands aside for this drill: PFLAB_PAID is set in the child only)", "guard.py")
    try:
        gv.check(cur, "brain", 5.0, 1000, 500, t, "normal", cfg)
        c.ok(False, "a paid call was allowed with the month's cap spent", "hq/governor.py check")
    except gv.BudgetRefused as e:
        c.ok(getattr(e, "resume_at", None) is not None, f"the governor refuses with a reason and a resume time: {str(e)[:110]} (resume {getattr(e, 'resume_at', None)})", "hq/governor.py")
        refusal = e
    reply = workers._stopped(env.rt, {"task_id": 1}, refusal, {}, {}, 0.0, t)
    base = getattr(reply, "meta", None) or getattr(reply, "base", None) or {}
    c.ok(getattr(reply, "status", "") == "deferred", f"a worker task parks instead of failing: status {getattr(reply, 'status', None)} ({str(reply)[:140]})", "hq/workers.py _stopped")
    kinds.register("drill_paid", lambda con, market, now: [{"subject": "paid-1", "reason": "a paid look", "expected_value": 9.0, "cost_rupees": 50.0}] if market == "IN" else [],
                   lambda rt, item, now: {"useful": True, "effect": "belief: x", "outcome": "paid"}, cost_rupees=50.0)
    kinds.register("drill_free", lambda con, market, now: [{"subject": "free-1", "reason": "a free look", "expected_value": 1.0}] if market == "IN" else [],
                   lambda rt, item, now: {"useful": True, "effect": "belief: it changed", "outcome": "free work done"})
    runner._LAST_REFILL.clear()
    outs = [runner.tick(env.rt, t + timedelta(minutes=i), mode="deep") for i in range(3)]
    sk = cur.execute("SELECT subject, skip_reason FROM mind_agenda WHERE kind='drill_paid'").fetchall()
    c.ok(bool(sk) and "cap" in str(sk[0][1]), f"the paid agenda item is skipped with its reason: {sk}", "agenda/picker.py budget_refusal")
    outs += [runner.tick(env.rt, t + timedelta(minutes=10 + i), mode="deep") for i in range(4)]
    c.ok(any(o.get("state") == "done" for o in outs) and not any(o.get("kind") == "drill_paid" and o.get("state") == "done" for o in outs),
         f"free work continues, paid work does not: {[(o.get('kind'), o.get('state')) for o in outs]}", "agenda/runner.py, agenda/picker.py")
    w = env.world()
    sp = [n for n in w["guard_nodes"] if n["id"] == "spend"]
    c.ok(bool(sp) and sp[0]["state"] == "down" and "Rs 100" in sp[0]["sub"], f"World: spend {sp[0]['state']} - {sp[0]['sub']}" if sp else "no spend node", "app/world.py guards_view")
    c.says(sp[0]["sub"] if sp else "")
    api = [x for x in w["checks"] if x["name"] == "Claude API"]
    c.says(api[0]["detail"] if api else "")
    c.ok(not env.exceptions and not env.catcher.records, f"no unhandled exception {env.exceptions[:2]} {env.catcher.records[:2]}", "(named)")


GC_SCRIPT = '''
import sys, os, time, threading
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, r"@REPO@\\src")
os.environ["PFLAB_PM_DIR"] = r"@PM@"
from pflab.pm import store
from pflab.service import jobs, presence
from pflab.service.jobs import Ctx, Job
from pflab.service.schedule import Interval
con = store.connect()
now = datetime.fromisoformat("@NOW@")
presence.start(con, now, os.getpid())
presence.beat(con, now + timedelta(minutes=1))
con.execute("CREATE TABLE IF NOT EXISTS drill_wal(id INTEGER, note VARCHAR)")
con.execute("INSERT INTO drill_wal SELECT i, 'committed' FROM range(1000) t(i)")
tx = con.cursor()
tx.execute("BEGIN")
tx.execute("INSERT INTO drill_wal SELECT 1000 + i, 'uncommitted' FROM range(1000) t(i)")
job = Job("catch_up", Interval(5, weekdays_only=False), lambda c: time.sleep(900) or {})
ctx = Ctx(con.cursor(), now + timedelta(minutes=1), Path(r"@PM@"), Path(r"@DATA@"), Path(r"@REPO@"))
threading.Thread(target=lambda: jobs.run_job(ctx, job), daemon=True).start()
while not con.cursor().execute("SELECT 1 FROM job_runs WHERE job='catch_up' AND status='running'").fetchone():
    time.sleep(0.1)
print("RUNNING", flush=True)
time.sleep(900)
'''


@drill("kill9", 10)
def drill_kill9(env: "Env", c: Check) -> None:
    """A child process holds the store, runs a job (sleeping) and holds an open transaction; it is killed with taskkill /F; a new Runtime opens the same store."""
    from pflab.service import jobs
    gc = env.dir / "gc.py"
    now = dt(env.start, 10)
    gc.write_text(GC_SCRIPT.replace("@REPO@", str(REPO)).replace("@PM@", str(env.pm)).replace("@DATA@", str(env.data)).replace("@NOW@", now.isoformat()), encoding="utf-8")
    p = subprocess.Popen([sys.executable, str(gc)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(REPO))
    line = ""
    t0 = time.time()
    while time.time() - t0 < 90:
        line = p.stdout.readline().strip()
        if line == "RUNNING" or p.poll() is not None:
            break
    c.ok(line == "RUNNING", f"the child process holds the store, a job is 'running' and a transaction is open (pid {p.pid})", "tools/drills_s79.py GC_SCRIPT", "")
    if line != "RUNNING":
        c.note("child stderr: " + (p.stderr.read() if p.poll() is not None else "")[-300:])
        return
    k = subprocess.run(["taskkill", "/F", "/PID", str(p.pid)], capture_output=True, text=True)
    p.wait(timeout=30)
    c.ok(p.returncode is not None and p.poll() is not None, f"killed with taskkill /F (exit {p.returncode})", "")
    t1 = time.time()
    try:
        env.connect()
        c.ok(True, f"the store reopened after the kill in {time.time() - t1:.1f} s (WAL replayed)", "pm/store.py")
    except Exception as e:
        c.ok(False, f"the store did not reopen after kill -9: {type(e).__name__}: {str(e)[:160]}", "pm/store.py connect / DuckDB WAL")
        return
    cur = env.cur()
    n_ok = cur.execute("SELECT count(*) FROM drill_wal WHERE note='committed'").fetchone()[0]
    n_un = cur.execute("SELECT count(*) FROM drill_wal WHERE note='uncommitted'").fetchone()[0]
    c.ok(n_ok == 1000 and n_un == 0, f"mid-write recovery: {n_ok} committed rows kept, {n_un} uncommitted rows gone", "DuckDB WAL")
    c.ok(cur.execute("SELECT count(*) FROM job_runs WHERE job='catch_up' AND status='running'").fetchone()[0] == 1, "the dead process left its job 'running'", "")
    resume = now + timedelta(minutes=25)
    env.open_app(resume)
    row = cur.execute("SELECT status, detail FROM job_runs WHERE job='catch_up' ORDER BY run_id LIMIT 1").fetchone()
    c.ok(row[0] == "failed" and "abandoned" in (row[1] or ""), f"on start the dead run is marked: {row}", "service/jobs.py reap_at_start")
    ctx = jobs.Ctx(cur, resume, env.pm, env.data, REPO, sys.executable, env.rt.secrets)
    due, why = jobs.is_due(ctx, jobs.REGISTRY["catch_up"])
    c.ok(due, f"the job is due again at once: {why}", "service/jobs.py is_due")
    w = env.world()
    j = [x for x in w["jobs"] if x["job"] == "catch_up"][0]
    c.says(f"catch up: {j['state']} - {(j['last'] or {}).get('detail') or j['why']}")
    c.says(w["pulse"].get("catch_up", {}).get("off") or "")
    c.ok(bool(w["pulse"].get("catch_up", {}).get("off")), "the World says the app was off from the last beat to now", "app/world.py")
    r = env.step(resume + timedelta(minutes=5), continuous=False)
    st = env.job_status("catch_up")
    c.ok(st[0] in ("ok", "skipped"), f"after a tick the job ran: {st[0]} {str(st[1])[:80]}", "service/jobs.py tick")
    c.ok(not env.exceptions, f"no exception in the loops: {env.exceptions[:2]}", "(named)")


drill_kill9.connect = False


# --- the child and the parent -------------------------------------------------------------------------------------------------------------

def child_main(a) -> int:
    started = time.time()
    run_root, base = Path(a.run_dir), Path(a.base)
    res = {"name": a.drill, "status": "ERROR", "passed": False, "evidence": [], "world_says": "", "findings": [], "seconds": 0}
    c = Check(a.drill)
    env = None
    try:
        env = Env(a.drill, run_root, base, connect=getattr(DRILLS[a.drill], "connect", True))
        DRILLS[a.drill](env, c)
        res = c.result(started)
        res["exceptions"] = env.exceptions[:20]
        res["logged_errors"] = env.catcher.records[:20]
    except BaseException:
        tb = traceback.format_exc()
        res = c.result(started, "ERROR")
        res["evidence"].append("ERROR: the drill itself crashed: " + tb.strip().splitlines()[-1][:300])
        res["findings"].append({"what": "drill crashed: " + tb.strip().splitlines()[-1][:200], "where": "tools/drills_s79.py or the system under test", "how": f"python tools/drills_s79.py run --only {a.drill}",
                                "trace": tb[-1500:]})
    Path(a.out).write_text(json.dumps(res, default=str, indent=1), encoding="utf-8")
    sys.stdout.flush()
    os._exit(0)


def parent_run(a) -> int:
    run_root = SCRATCH / (a.run_name or datetime.now().strftime("run_%m%d_%H%M"))
    run_root.mkdir(parents=True, exist_ok=True)
    start = date.fromisoformat(a.start) if a.start else DEFAULT_START
    base = run_root / "base"
    t0 = time.time()
    print(f"[drills] building the base profile at {base} (start Thursday {start}) ...", flush=True)
    r = subprocess.run([sys.executable, str(Path(__file__)), "base", "--base", str(base), "--start", str(start)], capture_output=True, text=True, cwd=str(REPO))
    if r.returncode != 0 or not (base / "meta.json").exists():
        print(r.stdout[-1500:], r.stderr[-2500:])
        print("[drills] FAILED to build the base profile")
        return 2
    print(f"[drills] base ready in {time.time() - t0:.0f} s", flush=True)
    names = [n for n in (a.only.split(",") if a.only else [x for x in ORDER if x != "smoke"])]
    names = [n for n in names if n in DRILLS]

    def one(n: str) -> dict:
        out = run_root / f"{n}.json"
        t1 = time.time()
        cmd = [sys.executable, str(Path(__file__)), "child", "--drill", n, "--base", str(base), "--run-dir", str(run_root), "--out", str(out)]
        timeout = float(getattr(DRILLS[n], "minutes", 4.0)) * 60
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO), timeout=timeout)
            res = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"name": n, "status": "ERROR", "passed": False, "evidence": [f"ERROR: child exit {p.returncode}: {(p.stderr or p.stdout)[-400:]}"],
                                                                                    "world_says": "", "findings": [{"what": "drill child produced no result", "where": "tools/drills_s79.py", "how": f"run --only {n}"}], "seconds": 0}
        except subprocess.TimeoutExpired:
            res = {"name": n, "status": "FAIL", "passed": False, "evidence": [f"FAIL: the drill did not finish in {timeout / 60:.0f} minutes (something stalled)"], "world_says": "",
                   "findings": [{"what": f"drill {n} stalled for more than {timeout / 60:.0f} minutes", "where": "see progress.log in the drill's folder", "how": f"python tools/drills_s79.py run --only {n}"}], "seconds": timeout}
        res["seconds"] = round(time.time() - t1, 1)
        print(f"[drills] {res['status']:5s} {n:16s} {res['seconds']:6.1f}s  {res['evidence'][-1][:100] if res['evidence'] else ''}", flush=True)
        return res
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, int(a.jobs))) as ex:       # each drill has its own clone of the profile: they can run side by side
        results = list(ex.map(one, names))
    report(results, a)
    return 0 if all(r["status"] in ("PASS", "OFF") for r in results) else 1


def report(results: list, a) -> None:
    out = Path(a.out) if a.out else SCRATCH / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "results": results}, default=str, indent=1), encoding="utf-8")
    print("\n%-14s %-6s %7s  %s" % ("drill", "result", "seconds", "what the World screen says"))
    for r in results:
        print("%-14s %-6s %7.1f  %s" % (r["name"], r["status"], r["seconds"], (r.get("world_says") or "")[:110]))
        for e in r["evidence"]:
            if e.startswith("FAIL") or e.startswith("ERROR"):
                print("      " + e[:200])
    frag = Path(a.findings) if getattr(a, "findings", None) else out.with_suffix(".md")
    lines = ["## Drills and accelerated run (tools/drills_s79.py, %s)" % datetime.now().strftime("%Y-%m-%d %H:%M"), "",
             "| drill | result | seconds |", "|---|---|---|"] + [f"| {r['name']} | {r['status']} | {r['seconds']} |" for r in results] + [""]
    n = 0
    for r in results:
        for f in r.get("findings", []):
            n += 1
            lines += [f"### D{n}. [{r['name']}] {f['what']}", f"- where: {f['where']}", f"- how to reproduce: `{f['how']}`", ""]
    frag.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {out} and {frag}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run")
    r.add_argument("--only", default="")
    r.add_argument("--out", default="")
    r.add_argument("--findings", default="")
    r.add_argument("--start", default="")
    r.add_argument("--run-name", dest="run_name", default="")
    r.add_argument("--jobs", type=int, default=4, help="drills run side by side (each on its own clone)")
    sp.add_parser("list")
    b = sp.add_parser("base")
    b.add_argument("--base", required=True)
    b.add_argument("--start", required=True)
    ch = sp.add_parser("child")
    for k in ("--drill", "--base", "--run-dir", "--out"):
        ch.add_argument(k, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "list":
        print("\n".join(f"{n} ({getattr(DRILLS[n], 'minutes', 4)} min)" for n in ORDER))
        return 0
    if a.cmd == "base":
        os.environ.setdefault("PFLAB_DATA_DIR", str(REPO / "data"))
        print(json.dumps(build_base(Path(a.base), date.fromisoformat(a.start))))
        return 0
    if a.cmd == "child":
        return child_main(a)
    return parent_run(a)


if __name__ == "__main__":
    sys.exit(main())
