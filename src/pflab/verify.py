r"""`pflab verify`: the local acceptance check of a candidate release (S67). It runs on his PC, against HIS installed app's configuration and a
COPY of his record, and says what is proven, what failed and what only he can do. It changes nothing of his.

What it does, in order (every check is independent and can be run again after a missing step is done: that is how it resumes):

    identity     the candidate commit (and whether the tree is clean), the installed app's release tag, both schema versions. If this code IS
                 the installed app, the report says so: a check of the old installation validates nothing about a candidate.
    prerequisites  Python, git, the pinned libraries, free disk, Ollama and its two models, Docker and the sandbox image
    configuration  release.toml, settings, the monthly cap, which sections of the secrets file exist (never their values)
    sandbox      the containment probe in a real container: no network, read-only files, no host paths or secrets, killed at its limit
    connectors   permitted read-only reads: Kite (holdings count), Gmail (profile and a message-id listing); Telegram is configured-only, a
                 local sink: NO test message is sent. A login or OAuth step that is not done is reported as "needs you" with the exact step.
    freshness    each source's latest data against the last session, the connectors' colours, readiness and known gaps, on the copy
    migration    the candidate's migrations run on a copy; no table loses a row; a simulated upgrade -> write -> rollback on copies keeps the
                 rows written after the upgrade
    recovery     a headless worker on a temporary record is force-killed with work in flight and started again: nothing lost, nothing repeated;
                 then stopped cleanly; a test client coming and going does not matter to it
    live record  the live ledger file's size, time and hash before and after: unchanged
    wake         (--wake-check, after the laptop has really slept) the heartbeat the app wrote across the sleep: the wake was seen and recovered
    model        (--live-model) one tiny call through the app's own outbound privacy gate and budget

The report is short and sanitized: no raw data, no secrets, no amounts, his user folder shown as ~. `--report` names the file (a .json beside it).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

PASS, FAIL, NEEDS, SKIP, INFO = "pass", "fail", "needs you", "skipped", "info"
OPTIONAL_CHECKS = {"live model call", "connector colours"}          # everything else is required: skipped or informational does not accept
HEARTBEAT_MAX_AGE_S = 300                                          # a heartbeat older than this is not evidence the app is running now
ICON = {PASS: "PASS ", FAIL: "FAIL ", NEEDS: "NEEDS", SKIP: "skip ", INFO: "info "}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""


@dataclass
class Report:
    identity: Dict[str, object] = field(default_factory=dict)
    checks: List[Check] = field(default_factory=list)
    started: str = ""

    def add(self, name: str, status: str, detail: str = "", fix: str = "") -> Check:
        c = Check(name, status, sanitize(detail), sanitize(fix))
        self.checks.append(c)
        return c

    def incomplete(self) -> List[str]:
        """Required checks that were skipped or only informational: a check that did not pass is not a pass. Optional ones are named in
        OPTIONAL_CHECKS and never block."""
        return [c.name for c in self.checks if c.name not in OPTIONAL_CHECKS and c.status in (SKIP, INFO)]

    @property
    def verdict(self) -> str:
        if any(c.status == FAIL for c in self.checks):
            return "NOT READY: at least one check failed"
        if any(c.status == NEEDS for c in self.checks):
            return "CLOUD-TESTED CANDIDATE: waiting for steps only you can do (below); run the same command again after them"
        inc = self.incomplete()
        if inc:
            return "NOT ACCEPTED: required check(s) did not pass: " + ", ".join(inc[:6])
        return "ACCEPTED on this PC: every required check passed (optional checks are listed)"

    def text(self) -> str:
        i = self.identity
        lines = [f"Portfolio Lab local acceptance, {self.started}",
                 f"candidate : {i.get('candidate_commit', '?')}{' (EDITED FILES)' if i.get('candidate_dirty') else ''}  {i.get('candidate_describe', '')}  at {i.get('candidate_root', '?')}",
                 f"installed : {i.get('installed_tag') or 'none found'}  (schema v{i.get('installed_schema', '?')}); candidate schema v{i.get('candidate_schema', '?')}",
                 ""]
        for c in self.checks:
            lines.append(f"[{ICON[c.status]}] {c.name}: {c.detail}")
            if c.fix and c.status in (NEEDS, FAIL):
                lines.append(f"          -> {c.fix}")
        lines += ["", self.verdict]
        todo = [c for c in self.checks if c.status == NEEDS and c.fix]
        if todo:
            lines.append("Next, in order:")
            lines += [f"  {n}. {c.fix}" for n, c in enumerate(todo, 1)]
        return "\n".join(lines)

    def as_json(self) -> dict:
        return {"started": self.started, "identity": self.identity, "verdict": self.verdict,
                "checks": [c.__dict__ for c in self.checks]}


def sanitize(text: str) -> str:
    """Nothing personal in a report: his user folder is ~, e-mail addresses, long digit runs (accounts, phones) and PANs are masked."""
    t = str(text)
    home = str(Path.home())
    for h in {home, home.replace("\\", "/")}:
        if h:
            t = t.replace(h, "~")
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email]", t)
    t = re.sub(r"\b[A-Z]{5}\d{4}[A-Z]\b", "[id]", t)
    t = re.sub(r"(?<![\d.])\d{9,18}(?![\d.])", "[number]", t)
    return t


# --- context ---------------------------------------------------------------------------------------------------------------------------

@dataclass
class Ctx:
    code_root: Path                      # the candidate's code (this checkout)
    app_folder: Optional[Path]           # the installed app's folder (app\, data\, pm\, backups\), or None
    pm_live: Path
    data: Path
    now: datetime
    tmp: Path
    offline: bool = False
    run: Callable = subprocess.run
    python: str = sys.executable
    _pm_copy: Optional[Path] = None

    def pm_copy(self) -> Path:
        """One temporary copy of the record and its small config files for everything that opens a store (made on first use)."""
        if self._pm_copy is None:
            self._pm_copy = _copy_pm(self)
        return self._pm_copy

    @property
    def live_db(self) -> Path:
        return self.pm_live / "ledger.duckdb"


def _git(root: Path, *args: str, run: Callable = subprocess.run) -> str:
    try:
        p = run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=20)
        return (p.stdout or "").strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def fingerprint(path: Path) -> Optional[dict]:
    """Size, modified time and SHA-256 of a file: what 'unchanged' means."""
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    st = path.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": h.hexdigest()}


WAKE, HOUR = "Windows sleep and wake", "independent of the coding assistant"
HOUR_S, STALL_S = 3600, 600          # the one-hour run: an hour of uptime with no stall longer than ten minutes, and work done in it


def identity(ctx: Ctx, rep: Report, full: bool = True) -> None:
    from pflab import release
    from pflab.pm import store
    cand_schema = max(m[0] for m in store.MIGRATIONS)
    commit = _git(ctx.code_root, "rev-parse", "HEAD", run=ctx.run)
    dirty = bool(_git(ctx.code_root, "status", "--porcelain", run=ctx.run))
    installed_tag, installed_schema = "", None
    if ctx.app_folder is not None:
        rel = release.load(ctx.app_folder / "app")
        installed_tag = str(((rel or {}).get("app") or {}).get("tag", ""))
    if ctx.live_db.exists():
        try:
            import duckdb
            c = duckdb.connect(str(ctx.live_db), read_only=True)
            installed_schema = c.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
            c.close()
        except Exception:
            installed_schema = "unreadable (the app may hold it)"
    rep.identity = {"candidate_commit": commit[:12] or "unknown", "candidate_dirty": dirty, "candidate_root": str(ctx.code_root),
                    "candidate_describe": _git(ctx.code_root, "describe", "--tags", "--always", run=ctx.run),
                    "installed_tag": installed_tag, "installed_schema": installed_schema, "candidate_schema": cand_schema}
    is_installed = release.is_app(ctx.code_root)
    if is_installed and not full:                            # the wake and hour checks are about the installed app itself: that is what they read
        rep.add("candidate identity", INFO, f"the installed app itself, {commit[:12]} ({installed_tag or 'tag unknown'})")
    elif is_installed:
        rep.add("candidate identity", FAIL, "this code is the INSTALLED app's own clone: a check of the old installation validates nothing about a candidate",
                "run tools\\verify_candidate.ps1: it makes an isolated checkout of the candidate and runs this from there")
    elif not commit:
        rep.add("candidate identity", FAIL, "no git commit found for this code", "run it from a git checkout of the candidate")
    else:
        rep.add("candidate identity", PASS if not dirty else INFO,
                f"{commit[:12]} ({'edited files present, not the pushed commit' if dirty else 'clean'}); installed {installed_tag or 'unknown'}")


# --- checks ----------------------------------------------------------------------------------------------------------------------------------

def prerequisites(ctx: Ctx, rep: Report) -> None:
    import platform
    ok = sys.version_info >= (3, 10)
    rep.add("python", PASS if ok else FAIL, f"{platform.python_version()} ({platform.system()})")
    rep.add("git", PASS if shutil.which("git") else FAIL, "found" if shutil.which("git") else "not found on PATH")
    lock = ctx.code_root / "requirements.lock"
    if lock.exists():
        import importlib.metadata as md
        bad = []
        for line in lock.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;#]+)", line.strip())
            if not m or m.group(1).lower() in ("pywin32",) and os.name != "nt":
                continue
            try:
                have = md.version(m.group(1))
            except md.PackageNotFoundError:
                bad.append(f"{m.group(1)} missing")
                continue
            if have != m.group(2):
                bad.append(f"{m.group(1)} {have} (lock {m.group(2)})")
        rep.add("pinned libraries", PASS if not bad else FAIL, "every library equals requirements.lock" if not bad else f"{len(bad)} differ: " + "; ".join(bad[:5]),
                "" if not bad else "pip install -r requirements.lock in the candidate's environment")
    free = shutil.disk_usage(ctx.tmp).free / 1e9
    rep.add("disk", PASS if free > 5 else FAIL, f"{free:,.1f} GB free")


def configuration(ctx: Ctx, rep: Report) -> None:
    from pflab import release
    from pflab.pm import secrets_setup as ss
    app = ctx.app_folder
    if app is None or not (app / "app").exists():
        rep.add("installed app", NEEDS, "no installed app folder given or found", "run with the app's folder: --app D:\\PortfolioLabApp")
        return
    rel = release.load(app / "app")
    rep.add("release.toml", PASS if rel else FAIL, f"channel {((rel or {}).get('app') or {}).get('channel', '?')}, tag {((rel or {}).get('app') or {}).get('tag', '?')}")
    s = ctx.pm_live / "app" / "settings.json"
    try:
        cfg = json.loads(s.read_text(encoding="utf-8")) if s.exists() else {}
        rep.add("settings", PASS, f"preset {cfg.get('preset', 'full')}, brain {cfg.get('brain', 'economy')}, Telegram {'on' if cfg.get('telegram_send') else 'off'}")
    except (OSError, ValueError):
        rep.add("settings", FAIL, "settings.json cannot be read")
    try:
        have = ss.status()
        sections = sorted({k.split(".")[0] for k, v in have.items() if v})
        rep.add("secrets file", PASS if sections else NEEDS, "sections present: " + (", ".join(sections) or "none") + " (values never read out)",
                "" if sections else "pflab setup secrets")
    except Exception as e:
        rep.add("secrets file", NEEDS, f"cannot be read ({type(e).__name__})", "pflab setup secrets")


def local_model(ctx: Ctx, rep: Report) -> None:
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            names = [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        rep.add("local model (Ollama)", NEEDS, "Ollama does not answer on this PC", "start Ollama, then run this command again")
        return
    miss = sorted({"qwen3:8b-q8_0", "nomic-embed-text:latest"} - set(names))
    if miss:
        rep.add("local model (Ollama)", NEEDS, f"running; missing {', '.join(miss)}", f"ollama pull {miss[0]}")
        return
    # listing the models proves nothing about inference: ask a question with one right answer, and embed a sentence
    try:
        from pflab.llm import client
        t = client.chat("qwen3:8b-q8_0", [{"role": "user", "content": "What is 17 plus 25? Reply with only the number."}], num_predict=20, timeout=180)
        ok_chat = "42" in t.text
        v = client.http_transport("POST", "/api/embed", {"model": "nomic-embed-text", "input": "a sentence to embed"}, 120)
        vec = (v.get("embeddings") or [[]])[0]
        ok_emb = len(vec) >= 100 and any(abs(x) > 0 for x in vec)
    except Exception as e:
        rep.add("local model (Ollama)", FAIL, f"both models are installed but inference failed: {type(e).__name__}: {str(e)[:120]}",
                "restart Ollama; if the GPU dropped off the bus use Restart, not Shut down")
        return
    rep.add("local model (Ollama)", PASS if ok_chat and ok_emb else FAIL,
            f"real inference: answered in {t.seconds:g} s, {t.tokens_out} tokens; embedding of {len(vec)} numbers" if ok_chat and ok_emb
            else f"inference ran but gave a wrong result (answer {t.text[:40]!r}, embedding {len(vec)} numbers)")


def sandbox_checks(ctx: Ctx, rep: Report) -> None:
    from pflab.agents import sandbox as sb
    st = sb.status(force=True)
    if not st["ok"]:
        rep.add("sandbox (Docker)", NEEDS, st["why"], "start Docker Desktop; if the image is missing: docker build -t pflab-sandbox:2 -f sandbox/Dockerfile . (from the candidate folder)")
        return
    r = sb.probe()
    if r["ok"]:
        rep.add("sandbox containment", PASS, "proved in a real container: " + ", ".join(sorted(r["checks"])))
    else:
        rep.add("sandbox containment", FAIL, r["why"] + (" " + ", ".join(k for k, v in r["checks"].items() if v is not True) if r["checks"] else ""),
                "generated code must not run until this passes")


def connectors(ctx: Ctx, rep: Report) -> None:
    from pflab.app import runtime as rtm
    from pflab.pm import secrets as sec
    try:
        secrets = sec.load()
    except Exception:
        secrets = None
    if ctx.offline:
        for n in ("Kite read",):
            rep.add(n, SKIP, "offline run: no connector was contacted")
    else:
        kite_py = "<app>\\app\\.venv\\Scripts\\python tools\\kite_login.py"
        if secrets is None or not secrets.has("kite", "api_key"):
            rep.add("Kite read", NEEDS, "no Kite key in the secrets file", "pflab setup secrets --only kite")
        elif not rtm.token_valid(ctx.now):
            rep.add("Kite read", NEEDS, "no Kite login today (the login is a morning step in the browser)", f"log in to Kite (the dashboard button, or {kite_py}), then run this again")
        else:
            try:
                from pflab.ingest import kite as km
                k = km.client(secrets, now=ctx.now)
                n = len(km.holdings_frame(k.holdings()))
                km.funds_from_margins(k.margins())
                rep.add("Kite read", PASS, f"read-only: {n} holding row(s) and the funds were read (values not shown)")
            except Exception as e:
                rep.add("Kite read", FAIL, f"{type(e).__name__}: {str(e)[:120]}", "log in to Kite again; if it persists the read-only wrapper or the key is wrong")
    tg = bool(secrets and secrets.has("telegram", "token") and secrets.has("telegram", "chat_id"))
    rep.add("Telegram", PASS if tg else NEEDS, "configured; NO test message is sent by this check (a local sink is used for tests)" if tg else "token or chat id missing",
            "" if tg else "pflab setup secrets --only telegram")
    ak = bool(secrets and secrets.has("anthropic", "api_key"))
    rep.add("Claude API key", PASS if ak else NEEDS, "present (no call made unless --live-model)" if ak else "no key in the secrets file", "" if ak else "pflab setup secrets --only anthropic")


def _copy_pm(ctx: Ctx) -> Path:
    """A temporary pm folder: a copy of the ledger and the small config files. The live files are only read."""
    pm = ctx.tmp / "pm_copy"
    pm.mkdir(parents=True, exist_ok=True)
    if ctx.live_db.exists():
        shutil.copy2(ctx.live_db, pm / "ledger.duckdb")
    for p in list(ctx.pm_live.glob("*.toml")) + list(ctx.pm_live.glob("*.json")):
        try:
            shutil.copy2(p, pm / p.name)
        except OSError:
            pass
    sj = ctx.pm_live / "app" / "settings.json"
    if sj.exists():
        (pm / "app").mkdir(exist_ok=True)
        shutil.copy2(sj, pm / "app" / "settings.json")
    return pm


def migration_and_rollback(ctx: Ctx, rep: Report) -> None:
    from pflab import update as up
    from pflab.pm import store
    if not ctx.live_db.exists():
        rep.add("migration rehearsal", SKIP, "no store yet (a first install): nothing to migrate")
        return
    try:
        a = ctx.tmp / "restored.duckdb"
        b = ctx.tmp / "upgraded.duckdb"
        shutil.copy2(ctx.live_db, a)
        shutil.copy2(ctx.live_db, b)
    except OSError as e:
        rep.add("migration rehearsal", NEEDS, f"the store cannot be copied while another program holds it ({type(e).__name__})",
                "close the dashboard and the bot (Stop in the dashboard), then run this again")
        return
    try:
        r = up.rehearse(b)
    except Exception as e:
        rep.add("migration rehearsal", FAIL, f"the candidate's migrations failed on a copy: {type(e).__name__}: {str(e)[:160]}", "do not release; the live store was not touched")
        return
    rep.add("migration rehearsal", PASS if not r["lost"] else FAIL,
            f"a copy migrated to schema v{r['version']} ({r['tables']} tables, {r['rows']:,} rows); " + ("no table lost a row" if not r["lost"] else f"ROWS LOST {r['lost']}"))
    # upgrade -> write -> rollback, on copies: what was written after the upgrade survives the return to the old store
    try:
        con = store.connect(b)
        from pflab.pm.store import next_id
        qid = next_id(con, "questions", "q_id")
        con.execute("INSERT INTO questions VALUES (?,?,?,?,?,?,NULL,NULL)", [qid, ctx.now, "verify", f"verify:rehearsal:{qid}", "written after the upgrade (rehearsal)", "open"])
        mid = next_id(con, "memory", "mem_id")
        con.execute("INSERT INTO memory (mem_id, created_at, kind, subject, text, source, valid_from) VALUES (?,?,?,?,?,?,?)",
                    [mid, ctx.now, "note", "verify", "written after the upgrade (rehearsal)", "pflab verify", ctx.now.date()])
        con.close()
        before = up._row_counts(a)
        m = up.merge_new_rows(b, a)
        after = up._row_counts(a)
        lost = {t: before[t] - after.get(t, 0) for t in before if after.get(t, 0) < before[t]}
        ok = m["added"].get("questions") == 1 and m["added"].get("memory") == 1 and not lost
        rep.add("rollback rehearsal", PASS if ok else FAIL,
                f"after an upgrade and two new records, a rollback to the old store kept both ({m['rows']} row(s) merged back; tables only the new version has: {len(m['only_in_kept'])}); no row lost"
                if ok else f"merged {m['added']}; lost {lost}")
    except Exception as e:
        rep.add("rollback rehearsal", FAIL, f"{type(e).__name__}: {str(e)[:160]}")


def freshness_and_readiness(ctx: Ctx, rep: Report) -> None:
    from pflab.app import readiness, system
    from pflab.app.runtime import Runtime
    from pflab.pm import store
    if not ctx.live_db.exists():
        rep.add("freshness", SKIP, "no store yet")
        return
    pm = ctx.pm_copy()
    try:
        con = store.connect(pm / "ledger.duckdb")
    except Exception as e:
        rep.add("freshness", FAIL, f"the copy could not be opened: {type(e).__name__}")
        return
    try:
        rt = Runtime(pm, ctx.data, ctx.code_root, con=con, clock=lambda: ctx.now)
        pic = system.picture(rt, ctx.now)
        by = {"ok": 0, "warn": 0, "down": 0, "off": 0}
        for f in pic["freshness"]:
            by[f["state"]] = by.get(f["state"], 0) + 1
        stale = [f"{f['name']} ({f['latest'] or 'none'})" for f in pic["freshness"] if f["state"] in ("warn", "down")]
        rep.add("data freshness", PASS if not stale else INFO,
                f"{by['ok']} source(s) current" + (f"; late or retained: {', '.join(stale[:6])}" if stale else ""))
        cs = [f"{c['name']}: {c['state']}" for c in pic["connectors"]]
        rep.add("connector colours", INFO, "; ".join(cs))
        r = readiness.assess(rt, ctx.now)
        rep.add("readiness", PASS if r["ready"] else INFO, r["say"] + (": " + "; ".join(r["remaining"][:3]) if r["remaining"] else ""))
        rec = pic["recommendations"]
        rep.add("recommendations", PASS if rec["current"] else INFO, "prepared items may be shown as current" if rec["current"] else (rec["say"] or rec["why"] or "not current"))
        con.close()
    except Exception as e:
        rep.add("freshness", FAIL, f"{type(e).__name__}: {str(e)[:160]}")


# --- the restart drill: a real worker process, force-killed with work in flight ---------------------------------------------------------------

def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(port: int, path: str, timeout: float = 5.0):
    import urllib.request
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.loads(r.read())


def _post(port: int, path: str, body: Optional[dict] = None, timeout: float = 10.0):
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def _wait_up(port: int, proc, seconds: float = 90.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < seconds:
        if proc.poll() is not None:
            return False
        try:
            _get(port, "/api/system", timeout=3)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def seed_store_for_drill(db: Path, now: datetime) -> None:
    """A temporary record with work in flight when the process dies: a task and an investigation `running`, and a job run that never finished."""
    from pflab.pm import store
    con = store.connect(db)
    con.execute("INSERT INTO hq_tasks (task_id, created_at, from_agent, to_agent, text, body_json, status, hops, channel, attempts, started_at) "
                "VALUES (1, ?, 'investor', 'graph', 'drill task', '{}', 'running', 0, 'dashboard', 1, ?)", [now, now])          # a real, code-only agent
    con.execute("INSERT INTO hq_cases (case_id, subject_key, opened_at, updated_at, origin, question, status, attempts, max_attempts, steps) "
                "VALUES (1, 'drill:case', ?, ?, 'code', 'drill question', 'running', 1, 3, 0)", [now, now])
    con.execute("INSERT INTO hq_effects (effect_key, task_id, kind, done_at, detail, state) VALUES ('drill:effect', 1, 'message', ?, 'sent before the stop', 'done')", [now])
    con.execute("INSERT INTO hq_effects (effect_key, task_id, kind, done_at, detail, state) VALUES ('drill:halfway', 1, 'message', ?, 'stopped between started and done', 'started')", [now])
    con.execute("INSERT INTO learn_experiments (exp_id, key, registered_at, hypothesis, why_it_matters, disproof, source_kind, dataset, max_attempts, protocol_path, "
                "protocol_sha, evaluator_sha, status) VALUES (1, 'drill', ?, 'drill hypothesis', 'w', 'd', 'investor', 'index:NIFTY50_TRI', 3, 'none', 'x', 'x', 'running')", [now])
    con.execute("INSERT INTO learn_attempts (attempt_id, exp_id, n, made_at, kind, status, note) VALUES (1, 1, 1, ?, 'candidate', 'rejected', 'recorded before the stop')", [now])
    con.execute("INSERT INTO job_runs (run_id, job, started_at, status) VALUES (1, 'collect', ?, 'running')", [now])
    con.execute("INSERT INTO questions VALUES (1, ?, 'drill', 'drill:q', 'asked once', 'open', NULL, NULL)", [now])
    con.close()


def _drill_store_checks(db: Path, steps: list) -> bool:
    """After the clean stop: the experiment the dead process left running continues from its recorded attempt, the effect that stopped halfway is
    listed and was not repeated, and the effect that was done is still the one row."""
    import duckdb
    try:
        con = duckdb.connect(str(db), read_only=True)
        exp = con.execute("SELECT status FROM learn_experiments WHERE exp_id=1").fetchone()[0]
        n_att = con.execute("SELECT count(*) FROM learn_attempts WHERE exp_id=1").fetchone()[0]
        eff = dict(con.execute("SELECT effect_key, state FROM hq_effects").fetchall())
        con.close()
    except Exception as e:
        steps.append(f"the store could not be read after the stop ({type(e).__name__})")
        return False
    ok_exp = exp == "registered" and n_att == 1
    ok_eff = eff.get("drill:halfway") == "started" and eff.get("drill:effect") == "done" and len(eff) == 2
    steps.append("experiment resumes from its recorded attempt" if ok_exp else f"experiment is {exp} with {n_att} attempt(s): NOT recovered")
    steps.append("a halfway effect is listed, not repeated" if ok_eff else f"effects {eff}: NOT as expected")
    return ok_exp and ok_eff


def restart_drill(ctx: Ctx, rep: Report, *, python: Optional[str] = None, cwd: Optional[Path] = None, seconds: float = 90.0) -> None:
    """Start the headless worker on a temporary record, check it serves a client that then goes away, force-kill it, start it again, check
    that what was in flight was recovered once (not repeated, not lost), then stop it cleanly. Nothing here touches his record or data."""
    root = ctx.tmp / "drill"
    pm, data = root / "pm", root / "data"
    (pm / "app").mkdir(parents=True)
    data.mkdir(parents=True)
    port = free_port()
    (pm / "app" / "settings.json").write_text(json.dumps({"port": port, "scheduler": False, "live_prices": False, "preset": "off",
                                                           "brain": "off", "drop_watch": False}), encoding="utf-8")
    now = datetime.now()
    seed_store_for_drill(pm / "ledger.duckdb", now)
    env = {**os.environ, "PFLAB_PM_DIR": str(pm), "PFLAB_DATA_DIR": str(data), "PFLAB_CHANNEL": "stable", "PFLAB_SANDBOX": "local"}
    env.pop("PFLAB_LIVE", None)
    env.pop("PFLAB_PAID", None)
    cmd = [python or ctx.python, "-m", "pflab.app.worker"]
    kw = {"cwd": str(cwd or ctx.code_root), "env": env, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    steps = []
    p1 = subprocess.Popen(cmd, **kw)
    try:
        if not _wait_up(port, p1, seconds):
            rep.add("restart drill", FAIL, "the headless worker did not start on a temporary record", "see worker.log in the drill folder (kept only while this runs)")
            return
        steps.append("worker started")
        a = _get(port, "/api/system")                    # a client comes ...
        steps.append("client served")
        time.sleep(1.0)
        b = _get(port, "/api/system")                    # ... goes away; another comes: the worker did not depend on the first
        tasks = {t["id"]: t for t in _get(port, "/api/hq")["tasks"]}
        t1 = tasks.get(1, {})
        recovered = t1.get("attempts", 0) >= 2 and ("interrupted" in str(t1.get("progress") or "") or t1.get("status") in ("retry", "failed", "done"))
        steps.append("work in flight recovered at start" if recovered else "recovery NOT seen")
        p1.kill()                                        # force-stop: no cleanup
        p1.wait(15)
        steps.append("force-killed")
        p2 = subprocess.Popen(cmd, **kw)
        try:
            if not _wait_up(port, p2, seconds):
                rep.add("restart drill", FAIL, "; ".join(steps) + "; the worker did not start again after a force-kill")
                return
            steps.append("restarted")
            hq = _get(port, "/api/hq")
            t = {x["id"]: x for x in hq["tasks"]}.get(1, {})
            once = len({x["id"] for x in hq["tasks"]}) == len(hq["tasks"])
            q = [x for x in _get(port, "/api/system")["needs"]["items"]]
            steps.append(f"task #1 is {t.get('status')} after {t.get('attempts')} attempt(s)")
            _post(port, "/api/shutdown")
            try:
                rc = p2.wait(60)
            except subprocess.TimeoutExpired:
                p2.kill()
                rc = None
            steps.append("stopped cleanly" if rc == 0 else f"did not stop cleanly (exit {rc})")
            extra_ok = _drill_store_checks(pm / "ledger.duckdb", steps)
            ok = recovered and rc == 0 and once and t.get("attempts", 0) <= 3 and extra_ok
            rep.add("restart drill", PASS if ok else FAIL, "; ".join(steps))
        finally:
            if p2.poll() is None:
                p2.kill()
    except Exception as e:
        rep.add("restart drill", FAIL, "; ".join(steps) + f"; {type(e).__name__}: {str(e)[:120]}")
    finally:
        if p1.poll() is None:
            p1.kill()


def wake_check(ctx: Ctx, rep: Report) -> None:
    """After the laptop has REALLY slept with the app open: did the app see the wake, recover, and catch up? Reads the heartbeat file the app wrote."""
    p = ctx.pm_live / "app" / "heartbeat.json"
    if not p.exists():
        rep.add(WAKE, NEEDS, "the app has written no heartbeat yet (it was not running, or is an older version)",
                "start Portfolio Lab, leave it open, sleep the laptop for at least 5 minutes, wake it, wait 2 minutes, run `pflab verify --wake-check`")
        return
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rep.add(WAKE, FAIL, "heartbeat.json cannot be read")
        return
    try:                                                           # liveness: an old settled heartbeat from a stopped app proves nothing now
        age = (ctx.now - datetime.fromisoformat(str(d.get("at"))[:19])).total_seconds()
    except (TypeError, ValueError):
        rep.add(WAKE, FAIL, "the heartbeat has no readable time")
        return
    from pflab._lock import _alive
    if age > HEARTBEAT_MAX_AGE_S or not _alive(str(d.get("pid", ""))):
        rep.add(WAKE, NEEDS,
                f"the last beat was {int(age // 60)} min ago" + (" and its process is gone" if not _alive(str(d.get("pid", ""))) else "")
                + ": this is an old heartbeat, not evidence about the app now",
                "start Portfolio Lab, leave it open, then run `pflab verify --wake-check` again")
        return
    w = d.get("last_wake")
    if not w:
        rep.add(WAKE, NEEDS, f"no wake has been seen yet (last beat {d.get('at')})",
                "with the app open, sleep the laptop for at least 5 minutes, wake it, wait 2 minutes, run `pflab verify --wake-check`")
        return
    if w.get("recovered") == "failed":
        rep.add(WAKE, FAIL, f"a wake at {w.get('at')} was seen but recovery failed")
        return
    if w.get("blocked_at"):                                        # the data never caught up: that wake is not a pass
        rep.add(WAKE, FAIL, f"a wake at {w.get('at')} was seen, but the data was still not current by {w.get('blocked_at')}: {w.get('blocked_by')}")
        return
    settled = bool(w.get("settled_at")) and d.get("catching_up") is None
    rep.add(WAKE, PASS if settled else NEEDS,
            f"wake seen at {w.get('at')} after {w.get('away_min')} min; recovered {w.get('recovered')}; " + ("data caught up" if settled else "still catching up"),
            "" if settled else "wait a few minutes with the app open, then run `pflab verify --wake-check` again")


def hour_check(ctx: Ctx, rep: Report) -> None:
    """The one-hour run without the coding assistant, from what the app itself wrote: the same process up for an hour, never stalled longer than
    STALL_S (a sleep counts as a stall), and jobs finished within the last hour. Run it after the hour; it is evidence, not a promise."""
    p = ctx.pm_live / "app" / "heartbeat.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        at = datetime.fromisoformat(str(d.get("at"))[:19])
        since = datetime.fromisoformat(str(d.get("since"))[:19]) if d.get("since") else None
    except (OSError, ValueError, TypeError):
        rep.add(HOUR, NEEDS, "no heartbeat from the app yet (or an older version that does not record its start)", "start Portfolio Lab from its icon and leave it an hour")
        return
    from pflab._lock import _alive
    if (ctx.now - at).total_seconds() > HEARTBEAT_MAX_AGE_S or not _alive(str(d.get("pid", ""))):
        rep.add(HOUR, NEEDS, "the app is not running now: the hour must be measured while it runs", "start Portfolio Lab and leave it an hour, then run this again")
        return
    up = (at - since).total_seconds() if since else 0
    gap, jobs, failed = float(d.get("max_gap_s") or 0), int(d.get("jobs_last_hour") or 0), list(d.get("failed_last_hour") or [])
    if up < HOUR_S:
        rep.add(HOUR, NEEDS, f"running {int(up // 60)} min so far", f"leave it running; run `pflab verify --hour-check` after {int((HOUR_S - up) // 60) + 1} more minutes")
    elif gap > STALL_S:
        rep.add(HOUR, FAIL, f"up {int(up // 60)} min, but it stalled for {int(gap // 60)} min at one point (a sleep, a freeze or a hang)",
                "keep the laptop awake and run the hour again (the app must be restarted for a new count)")
    elif d.get("paused"):
        rep.add(HOUR, NEEDS, f"up {int(up // 60)} min, but paused on the World screen: a paused hour is not a working hour", "press Resume and run the hour again")
    elif jobs < 1:
        rep.add(HOUR, FAIL, f"up {int(up // 60)} min but no job finished well in the last hour: it was alive, not working"
                + (f" (failed: {', '.join(failed)})" if failed else ""))
    elif failed:
        rep.add(HOUR, FAIL, f"up {int(up // 60)} min, {jobs} job run(s) finished well, but these failed in the last hour: {', '.join(failed)}")
    else:
        rep.add(HOUR, PASS, f"uptime: {int(up // 60)} min in one process, longest pause {int(gap)} s; work: {jobs} job run(s) finished well in the last hour, none failed")


EVIDENCE = "acceptance.json"


def _binding(ctx: Ctx, rep: Report) -> dict:
    from pflab import activation
    try:
        prof = activation.read(ctx.pm_live).get("profile", "")
    except Exception:
        prof = ""
    return {"commit": rep.identity.get("candidate_commit"), "pm": str(ctx.pm_live), "profile": prof}


def accumulate(ctx: Ctx, rep: Report) -> Report:
    """The acceptance record grows across runs (audit): the full check, then the sleep check, then the hour check each add their evidence to ONE
    record bound to the candidate, the profile and its folder. A later pass replaces an earlier pending; a later skip or pending never erases a
    pass; a later failure replaces a pass. A different candidate or profile starts a new record."""
    p = ctx.pm_live / "app" / EVIDENCE
    bind = _binding(ctx, rep)
    try:
        old = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    prev = {c["name"]: c for c in old.get("checks", [])} if old.get("binding") == bind else {}
    rank = {FAIL: 3, PASS: 2, INFO: 1, NEEDS: 0, SKIP: 0}
    merged = dict(prev)
    for c in rep.checks:
        o = prev.get(c.name)
        if o is None or c.status == FAIL or rank.get(c.status, 0) >= rank.get(o["status"], 0) or o["status"] == FAIL and c.status == PASS:
            merged[c.name] = {**c.__dict__, "at": rep.started}
        # else: an earlier pass stands against a later skip or pending
    out = Report(started=rep.started)
    out.identity = dict(rep.identity, evidence_from=sorted({m.get("at", rep.started) for m in merged.values()}))
    for c in merged.values():
        out.add(c["name"], c["status"], c.get("detail", ""), c.get("fix", ""))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"binding": bind, "checks": [{**c.__dict__, "at": merged[c.name].get("at")} for c in out.checks]}, indent=1, default=str),
                     encoding="utf-8")
    except OSError:
        pass
    return out


def live_model(ctx: Ctx, rep: Report) -> None:
    """One tiny call through the app's own outbound gate and budget (the same road a brain pass takes). Only with --live-model."""
    from pflab.agents import analyst as an
    from pflab.hq import egress
    from pflab.llm import gateway
    from pflab.pm import secrets as sec, store
    try:
        secrets = sec.load()
        pm = ctx.pm_copy()
        con = store.connect(pm / "ledger.duckdb")
        gate = egress.load(con)
        client = an.make_client(secrets)
        nonce = f"v{ctx.now:%H%M%S}"
        tool = {"name": "echo_code", "description": "Report the verification code you were given.",
                "input_schema": {"type": "object", "additionalProperties": False, "properties": {"code": {"type": "string"}}, "required": ["code"]}}
        # S85 (G3): through the door (role quick of the engine in use; a forced tool choice is refused by these models, so the system text says to call it)
        s = gateway.call(con, "quick", "You must call the tool echo_code with the code you are given, and say nothing else.", [{"role": "user", "content": f"The verification code is {nonce}."}],
                         tools=[tool], max_tokens=300, thinking="low", agent="reading", purpose="verify tool call", now=ctx.now, mode="economy", private_text="", gate=gate,
                         topic="verify", question="verify tool call", client=client)
        con.close()
        used = [c for c in s["tool_calls"] if c["name"] == "echo_code"]
        ok = bool(used) and (used[0]["input"] or {}).get("code") == nonce
        rep.add("live model call", PASS if ok else FAIL,
                (f"the model chose the tool and used it correctly through the privacy gate and the budget (cost Rs {s['cost_rupees']:.2f}; recorded on the copy only)"
                 if ok else "the model answered but did not call the tool with the given code: a ping is not tool use"))
    except Exception as e:
        rep.add("live model call", FAIL, f"{type(e).__name__}: {str(e)[:160]}", "check the key, the monthly cap and the network")


def live_unchanged(ctx: Ctx, rep: Report, before: Optional[dict]) -> None:
    after = fingerprint(ctx.live_db)
    if before is None and after is None:
        rep.add("live record untouched", SKIP, "no store yet")
    else:
        rep.add("live record untouched", PASS if before == after else FAIL,
                "the live ledger's size, time and hash are the same before and after this check" if before == after else "THE LIVE LEDGER CHANGED during verification (stop and look)")


# --- the run ---------------------------------------------------------------------------------------------------------------------------------

def run(app: Optional[Path] = None, *, report: Optional[Path] = None, wake: bool = False, model: bool = False, offline: bool = False,
        now: Optional[datetime] = None, drill_python: Optional[str] = None, skip: tuple = (), hour: bool = False, keep: bool = True) -> Report:
    from pflab import release
    from pflab.data import data_dir
    from pflab.pm import store
    now = now or datetime.now()
    code_root = release.ROOT
    if app is None:
        r = release.load(code_root)
        app = Path(r["app"]["folder"]) if r and (r.get("app") or {}).get("folder") else None
    if app is not None and (Path(app) / "pm").exists():
        pm_live, data = Path(app) / "pm", Path(app) / "data"
    else:
        pm_live, data = store.pm_dir(), data_dir()
    tmp = Path(tempfile.mkdtemp(prefix="pflab_verify_"))
    ctx = Ctx(code_root, Path(app) if app else None, pm_live, data, now, tmp, offline=offline)
    rep = Report(started=f"{now:%Y-%m-%d %H:%M}")
    before = fingerprint(ctx.live_db)
    saved_env = {k: os.environ.get(k) for k in ("PFLAB_PM_DIR", "PFLAB_DATA_DIR")}
    try:
        identity(ctx, rep, full=not (wake or hour))
        if not (wake or hour) and ctx.live_db.exists():
            try:                                           # from here every default-path read (budget, stock list, targets) goes to the COPY
                os.environ["PFLAB_PM_DIR"] = str(ctx.pm_copy())
            except OSError:
                pass                                       # the store is held by the app: the migration check says so and asks him to stop it
        os.environ["PFLAB_DATA_DIR"] = str(ctx.data)
        if wake or hour:
            if wake:
                wake_check(ctx, rep)
            if hour:
                hour_check(ctx, rep)
        else:
            steps = [("prerequisites", prerequisites), ("configuration", configuration), ("local model", local_model),
                     ("sandbox", sandbox_checks), ("connectors", connectors), ("migration", migration_and_rollback),
                     ("freshness", freshness_and_readiness)]
            for name, fn in steps:
                if name in skip:
                    rep.add(name, SKIP, "skipped by request")
                    continue
                try:
                    fn(ctx, rep)
                except Exception as e:                     # one check failing never hides the others
                    rep.add(name, FAIL, f"the check itself failed: {type(e).__name__}: {str(e)[:140]}")
            if "recovery" not in skip:
                try:
                    restart_drill(ctx, rep, python=drill_python)
                except Exception as e:
                    rep.add("restart drill", FAIL, f"{type(e).__name__}: {str(e)[:140]}")
            if model:
                live_model(ctx, rep)
            else:
                rep.add("live model call", SKIP, "not asked for (add --live-model for one small call through the privacy gate and the budget)")
            rep.add(WAKE, NEEDS, "cannot be done by a program: it needs the laptop to really sleep",
                    "with the app open: sleep the laptop 5+ minutes, wake it, wait 2 minutes, run `pflab verify --wake-check`")
            rep.add(HOUR, NEEDS, "only you can close it", "close Claude Code and the terminal, leave Portfolio Lab running one hour (laptop awake), "
                    "then run `pflab verify --hour-check`")
        if not (wake or hour):
            live_unchanged(ctx, rep, before)
        if keep:
            rep = accumulate(ctx, rep)
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
    if report:
        report = Path(report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(rep.text(), encoding="utf-8")
        report.with_suffix(".json").write_text(json.dumps(rep.as_json(), indent=1, default=str), encoding="utf-8")
    return rep


def exit_code(rep: "Report") -> int:
    """0 only when accepted; 1 a failure; 2 pending (a step only he can do, or a required check skipped): pending is never success (audit)."""
    if any(c.status == FAIL for c in rep.checks):
        return 1
    return 0 if rep.verdict.startswith("ACCEPTED") else 2


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="pflab verify", description="local acceptance check of a candidate release (changes nothing of yours)")
    ap.add_argument("--app", help="the installed app's folder (default: from release.toml, else PFLAB_PM_DIR)")
    ap.add_argument("--report", help="write the sanitized report here (and a .json beside it)")
    ap.add_argument("--wake-check", action="store_true", help="only: did the app see and recover from a real sleep? (run it after sleeping the laptop)")
    ap.add_argument("--hour-check", action="store_true", help="only: has the app run an hour on its own, without stalling, doing work?")
    ap.add_argument("--live-model", action="store_true", help="also make one small model call through the privacy gate and the budget")
    ap.add_argument("--offline", action="store_true", help="do not contact Kite or Gmail")
    a = ap.parse_args(argv)
    rep = run(Path(a.app) if a.app else None, report=Path(a.report) if a.report else None, wake=a.wake_check, hour=a.hour_check, model=a.live_model, offline=a.offline)
    print(rep.text())
    return exit_code(rep)


if __name__ == "__main__":
    raise SystemExit(main())
