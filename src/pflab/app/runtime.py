"""The one-process system behind the dashboard (S54).

DuckDB allows one writing process, so everything runs here: the server's reads, the scheduler's jobs, the live-price
poller and the background caches each use their own cursor on one connection (DuckDB's own concurrency control).
Changes are announced by bumping a topic's version; the screens watch the versions and refetch what changed.

Held alerts stay held: the `outbox` job (Telegram delivery) runs only when settings.telegram_send is on.

Any job runs on request (S58, the investor 2026-10-24: the schedule is for when the system is not in use): "Run now" queues it
and the scheduler thread runs it next, so jobs still run one at a time. While the window is open, notes the research
job queues for Opus are submitted straight after it, and a submitted batch is collected every 30 minutes; unattended,
the analyst keeps its 1 AM slot.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
import time as _time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from pflab.app import settings as st

log = logging.getLogger("pflab.app")

INDICES = {"NIFTY 50": "NSE:NIFTY 50", "BANK NIFTY": "NSE:NIFTY BANK", "NIFTY 500": "NSE:NIFTY 500", "INDIA VIX": "NSE:INDIA VIX"}
SCHEDULER_EVERY_S = 60
LIVE_EVERY_S = 60
MC_PATHS, MC_MAX_AGE_H = 10_000, 20
WAKE_GAP = timedelta(minutes=5)     # the heart beats every 30 s and does nothing else: a longer silence is a sleep, never a long job
HEART_EVERY_S = 30
SETTLE_MAX = timedelta(hours=2)     # a wake whose prices are not current by then is recorded as blocked, with what failed
BATCH_POLL_MIN = 30                 # a submitted Opus batch is collected this often while the window is open


_SETTINGS_LOCK = threading.RLock()


class Runtime:
    def __init__(self, pm_dir: Path, data_root: Path, repo: Path, con=None, secrets=None,
                 clock: Callable[[], datetime] = datetime.now):
        from pflab.pm import store
        self.pm_dir, self.data_root, self.repo, self.clock = Path(pm_dir), Path(data_root), Path(repo), clock
        self.con = con if con is not None else store.connect()
        self.secrets = secrets
        self.settings = st.load(self.pm_dir)
        self._v: Dict[str, int] = {}
        self._vlock = threading.Lock()
        self.stop = threading.Event()
        self.threads: List[threading.Thread] = []
        self.live_indices: Dict[str, dict] = {}
        self.clients = 0
        self.last_client = self.clock()
        self.had_client = False
        self.busy: Optional[str] = None             # the job running now, for the activity feed
        self.wanted: List[str] = []                   # jobs asked for ("Run now", follow-ups), run next in order
        self.asked: Dict[str, str] = {}               # job -> what its last requested run did (also when not recorded)
        self._wake = threading.Event()
        self.code_at_start = code_stamp(self.repo)    # S58b: new code on disk -> "update ready", restart when quiet
        self.update_ready = False
        self.last_seen = self.clock()                 # the investor's last click or keypress in the window
        self.kite_state = "idle"                      # idle | waiting | done | failed: <why>
        self.sims_running = False
        self.sims_error: Optional[str] = None
        self.mc_error: Optional[str] = None           # the fall-limit simulation's last failure, for the World screen
        self.hq_last_round: Optional[tuple] = None    # (when, parts that failed) of the HQ thread's last round
        self._hq_wake = threading.Event()             # S59: an order on the board runs at once
        self.catching_up: Optional[str] = None        # S67: set after a wake or a start after a long stop, until the data is current again
        self._beat: Optional[datetime] = None
        self._woke_at: Optional[datetime] = None
        self.pool_active = False                      # S69: the worker pool's threads run the worker tasks (hq/pool.py)

    # --- change signals ----------------------------------------------------------------------------------------------
    def bump(self, *topics: str) -> None:
        with self._vlock:
            for t in topics:
                self._v[t] = self._v.get(t, 0) + 1

    def versions(self) -> Dict[str, int]:
        with self._vlock:
            return dict(self._v)

    def cursor(self):
        return self.con.cursor()

    def set_settings(self, changes: dict) -> dict:
        with _SETTINGS_LOCK:                                   # S78: two changes arriving together (the page posts its theme as he flips a switch) each started from the same old copy and the later one erased the earlier
            self.settings = st.save(self.pm_dir, changes, self.settings)
            out = self.settings
        self.bump("settings")
        return out

    # --- threads --------------------------------------------------------------------------------------------------------
    def _keep_local_calls(self) -> None:
        """S70: every call to the local model is kept in `llm_runs` (the table was never written by the app: its workload was invisible)."""
        from pflab.llm import client, registry

        def keep(d: dict) -> None:
            registry.log_run(self.cursor(), self.clock(), d["model"], role=d.get("purpose") or None, model_digest=d.get("digest"), tokens_in=d.get("tokens_in", 0),
                             tokens_out=d.get("tokens_out", 0), seconds=d.get("seconds", 0.0), status=d.get("status", "ok"), note=d.get("note", ""))
        client.set_sink(keep)

    def start(self) -> None:
        from pflab.service import jobs
        jobs.reap_at_start(self.cursor(), self.clock())     # S66: runs left "running" by a stopped process are due again
        try:                                                 # S68: a credential a failure text carried into a row is rewritten (idempotent)
            from pflab import scrub
            n, _ = scrub.scrub_store(self.cursor())
            if n:
                log.info("scrubbed %d stored text(s) that held a credential-shaped string", n)
        except Exception:
            log.exception("scrub of stored text failed")
        self._keep_local_calls()
        try:                                                 # S79 (A42): app-open time is recorded; the gap since the last beat is "off from X to Y", never an error
            from pflab.service import presence
            seg = presence.start(self.cursor(), self.clock(), os.getpid())
            if seg["off_from"] is not None:
                log.info("opened: %s", presence.describe(seg["off_from"], seg["off_to"]))
        except Exception:
            log.exception("presence record failed")
        try:                                                 # S79 (rule 10): this session's pre-registered studies count in the learner's counter
            from pflab.learner import s79
            s79.register_all(self.cursor(), self.clock())
            s79.register_seats(self.cursor(), self.clock())
            s79.register_swing(self.cursor(), self.clock())            # S81 B5
            from pflab.learner import s83
            s83.register_picks_live(self.cursor(), self.clock())        # S83 L5: the picks sleeve's live test, one per market
            s79.register_c4(self.cursor(), self.clock())               # S82 C4
            s79.apply_verdicts(self.cursor())
        except Exception:
            log.exception("registering S79 studies failed")
        try:                                                 # S84 F1 (his decision 2026-11-12): the dated amendment is counted first, then India's share gets room for the system's own picks, once
            from pflab.core import pick_share
            from pflab.learner import s83 as s83a
            s83a.register_picks_amendment_a1(self.cursor(), self.clock())
            pick_share.set_start_by_decision(self.cursor(), self.clock())
        except Exception:
            log.exception("the S84 F1 start of the India picks share failed")
        last_run = self.cursor().execute("SELECT max(started_at) FROM job_runs").fetchone()[0]
        if last_run is not None and self.clock() - last_run > timedelta(hours=6):
            self.catching_up, self._woke_at = f"started after {int((self.clock() - last_run).total_seconds() // 3600)} h off", self.clock()
        for name, fn in (("heart", self._heart_loop), ("scheduler", self._scheduler_loop), ("live", self._live_loop), ("mc", self._mc_loop),
                         ("research", self._research_loop), ("hq", self._hq_loop), ("phone", self._phone_loop)):
            t = threading.Thread(target=self._guard(fn), name=name, daemon=True)
            t.start()
            self.threads.append(t)

    def shutdown(self, wait_s: float = 30.0, others_s: float = 3.0) -> None:
        """A running job gets `wait_s` to finish (it writes the store); the screen's own computations (watch list,
        Monte Carlo, simulations: caches written whole) get `others_s` and are dropped with the process."""
        self.stop.set()
        self._wake.set()
        try:                                                 # S70: the local-call record belongs to this runtime's store
            from pflab.llm import client
            client.set_sink(None)
        except Exception:
            pass
        end = _time.time() + wait_s
        for t in self.threads:
            t.join(max(0.0, end - _time.time()) if t.name == "scheduler" else others_s)

    def _guard(self, fn):
        def run():
            while not self.stop.is_set():
                try:
                    fn()
                    return
                except Exception:                       # logged; the loop restarts after a pause, never dies silently
                    log.exception("%s loop failed; restarting in 60 s", threading.current_thread().name)
                    self.bump("health")
                    self.stop.wait(60)
        return run

    def paused(self) -> bool:
        """Pause on the World screen: no autonomous work starts (jobs, follow-ups, simulations, research, the HQ's own rounds)."""
        return not self.settings.get("scheduler", True)

    def _heart_loop(self) -> None:
        """Its own thread (audit 2026-10-30): the scheduler's beat was late whenever a job ran long, and that was taken for a sleep."""
        while not self.stop.is_set():
            self.beat()
            self.stop.wait(HEART_EVERY_S)

    def beat(self) -> Optional[str]:
        """Called once a loop. A gap far longer than the loop's own pause means the PC slept (or the process was frozen): recover what was
        running, look for what arrived, and say so until the data is current again. Pure: the clock is the runtime's own, so tests move it."""
        from pflab.app import system
        from pflab.hq import service
        now = self.clock()
        last, self._beat = self._beat, now
        wake, settle = None, None
        if last is not None and now - last > WAKE_GAP:
            mins = int((now - last).total_seconds() // 60)
            self.catching_up, self._woke_at = f"woke after {mins} min away", now
            try:
                from pflab.service import presence
                presence.wake(self.cursor(), now, last_beat=last, pid=os.getpid())
            except Exception:
                log.exception("presence record failed")
            try:
                wake = {"at": now.isoformat(timespec="seconds"), "away_min": mins, "recovered": service.start(self)}
            except Exception:
                log.exception("recovery after wake failed")
                wake = {"at": now.isoformat(timespec="seconds"), "away_min": mins, "recovered": "failed"}
            self.bump("health", "command")
        elif self.catching_up and self._woke_at is not None:
            ok, why = system.critical_fresh(self.cursor(), now)
            if ok:                                         # settled only on current data
                self.catching_up, settle = None, {"settled_at": now.isoformat(timespec="seconds")}
                self.bump("health", "command")
            elif now - self._woke_at > SETTLE_MAX:         # never a silent "settled": blocked, and by what
                self.catching_up = None
                settle = {"blocked_at": now.isoformat(timespec="seconds"), "blocked_by": str(why)[:300]}
                self.bump("health", "command")
        try:
            from pflab.service import presence
            presence.beat(self.cursor(), now)
        except Exception:
            pass
        try:                                                 # S79b: remember which modes the app has actually been open in (the first-week check reads them)
            from pflab.service import week_check
            week_check.note_modes(self.cursor(), now)
        except Exception:
            pass
        try:                                                 # S79 item 4: the clock's mode sets the local model's GPU duty cycle
            from pflab import markets
            from pflab.llm import duty
            duty.set_mode(markets.primary(now)[1])
        except Exception:
            pass
        self._write_beat(now, wake, settle)
        return self.catching_up

    def _write_beat(self, now: datetime, wake: Optional[dict], settle: Optional[dict] = None) -> None:
        """`pm/app/heartbeat.json`: the last beat and the last wake with what was recovered, for `pflab verify --wake-check` (a sleep that
        really happened on this PC is the one thing a cloud test cannot do). Best effort: a full disk never stops the loop."""
        p = self.pm_dir / "app" / "heartbeat.json"
        try:
            old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except (OSError, ValueError):
            old = {}
        pid = __import__("os").getpid()
        same = old.get("pid") == pid                       # the same process: the hour check adds up its beats; a new process starts again
        try:
            gap = (now - datetime.fromisoformat(str(old.get("at"))[:19])).total_seconds() if same and old.get("at") else 0.0
        except ValueError:
            gap = 0.0
        try:                                               # work is a job that finished well; a skip or a failure is not (audit 2026-10-30)
            rows = self.cursor().execute("SELECT job, status FROM job_runs WHERE finished_at >= ? AND status IN ('ok', 'failed')",
                                         [now - timedelta(hours=1)]).fetchall()
            jobs = sum(1 for _, s in rows if s == "ok")
            failed = sorted({j for j, s in rows if s == "failed"})
        except Exception:
            jobs = int(old.get("jobs_last_hour") or 0) if same else 0
            failed = list(old.get("failed_last_hour") or []) if same else []
        doc = {"at": now.isoformat(timespec="seconds"), "pid": pid, "catching_up": self.catching_up,
               "last_wake": wake or old.get("last_wake"), "wakes": int(old.get("wakes", 0)) + (1 if wake else 0),
               "since": old.get("since") if same and old.get("since") else now.isoformat(timespec="seconds"),
               "beats": int(old.get("beats", 0)) + 1 if same else 1, "max_gap_s": max(float(old.get("max_gap_s") or 0) if same else 0.0, gap),
               "jobs_last_hour": jobs, "failed_last_hour": failed, "paused": self.paused()}
        if wake is None and settle and old.get("last_wake"):
            doc["last_wake"] = {**old["last_wake"], **settle}    # the data caught up after that wake, or did not and why
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(doc), encoding="utf-8")
        except OSError:
            pass

    def _scheduler_loop(self) -> None:
        while not self.stop.is_set():
            self.run_wanted()
            if self.settings.get("scheduler", True):
                self.scheduler_once()
                self.poll_batches()
                self.run_wanted()
            self._wake.wait(SCHEDULER_EVERY_S)
            self._wake.clear()

    def _ctx(self):
        from pflab.service import jobs
        return jobs.Ctx(self.cursor(), self.clock(), self.pm_dir, self.data_root, self.repo, _python(), self.secrets)

    def scheduler_once(self) -> list:
        """One tick of the system's jobs (all registered jobs; the outbox only when Telegram is switched on)."""
        from pflab.service import jobs, tasks  # noqa: F401  (importing tasks registers the jobs)
        only = [j for j in st.jobs_for(self.settings.get("preset", "full"), jobs.REGISTRY)
                if (j != "outbox" or self.settings.get("telegram_send")) and j != "hq"]   # S59: HQ has its own thread here
        ctx = self._ctx()
        due = [j for j in only if jobs.is_due(ctx, jobs.REGISTRY[j])[0]]
        if not due:
            return []
        self.busy = ", ".join(due)
        self.bump("activity")
        try:
            results = jobs.tick(ctx, only)
        finally:
            self.busy = None
        self._after(ctx, results)
        return results

    def _after(self, ctx, results: list) -> None:
        from pflab.service import jobs
        from pflab.service import telegram as tgm
        for r in results:
            if r.status == "failed" and r.job != "outbox":
                tgm.enqueue(ctx.con, tgm.format_job_failure(r.job, r.detail, ctx.now), "job_failure",
                            dedup_key=f"jobfail:{r.run_id}", now=ctx.now)
            if self.settings.get("scheduler", True):     # S58b: what the new data feeds runs now (jobs.FOLLOWS)
                allowed = set(st.jobs_for(self.settings.get("preset", "full"), jobs.REGISTRY))
                for f in jobs.followers(r):
                    if f in allowed and f != "outbox":
                        self._want(f)
        self.bump("activity", "portfolio", "command", "notifications")

    # --- jobs on request -----------------------------------------------------------------------------------------------
    def request_run(self, name: str) -> List[str]:
        """'Run now' from the screen: the job runs next on the scheduler thread (one job at a time). Returns the queue."""
        from pflab.service import jobs, tasks  # noqa: F401
        if name not in jobs.REGISTRY:
            raise KeyError(name)
        if name == "outbox" and not self.settings.get("telegram_send"):
            raise ValueError("held messages stay held until Telegram is switched on in Settings")
        self._want(name)
        return list(self.wanted)

    def _want(self, name: str) -> None:
        with self._vlock:
            if name not in self.wanted:
                self.wanted.append(name)
        self._wake.set()
        self.bump("activity")

    def run_wanted(self) -> list:
        """Run the requested jobs in the order asked. A job asked again while it runs runs once."""
        from pflab.service import jobs
        out = []
        while not self.stop.is_set():
            with self._vlock:
                if not self.wanted:
                    break
                name = self.wanted[0]
            ctx = self._ctx()
            self.busy = name
            self.bump("activity")
            try:
                r = jobs.run_job(ctx, jobs.REGISTRY[name])
            finally:
                self.busy = None
                with self._vlock:
                    self.wanted.remove(name)
            self.asked[name] = f"{r.status} at {ctx.now:%H:%M}" + (f": {r.detail[:200]}" if r.status != "ok" else "")
            out.append(r)
            self._after(ctx, [r])
        return out

    # --- updates (S58b: the system picks up new code by itself) -------------------------------------------------------
    def check_update(self) -> bool:
        if not self.update_ready and code_stamp(self.repo) != self.code_at_start:
            self.update_ready = True
            log.info("new code on disk: update ready")
            self.bump("command", "health")
        return self.update_ready

    def quiet(self) -> bool:
        """No job running or waiting, so a restart loses nothing."""
        if self.busy or self.wanted or self.sims_running:
            return False
        con = self.cursor()
        if con.execute("SELECT 1 FROM hq_tasks WHERE status IN ('queued','running') LIMIT 1").fetchone():
            return False                              # S59: an agent at work (a paid call in flight) is not cut off
        if con.execute("SELECT 1 FROM hq_cases WHERE status='running' LIMIT 1").fetchone():
            return False                              # S67: neither is an investigation's pass
        return not con.execute("SELECT 1 FROM job_runs WHERE status='running' LIMIT 1").fetchone()

    def poll_batches(self) -> bool:
        """A submitted Opus batch is collected every BATCH_POLL_MIN minutes while the window is open."""
        con = self.cursor()
        if not con.execute("SELECT 1 FROM api_calls WHERE status='submitted' LIMIT 1").fetchone():
            return False
        last = con.execute("SELECT max(started_at) FROM job_runs WHERE job='analyst'").fetchone()[0]
        if last is not None and self.clock() - last < timedelta(minutes=BATCH_POLL_MIN):
            return False
        self._want("analyst")
        return True

    # --- the agent HQ (S59): the board, the drop folder, reminders, readers, the brain, the keeper; and the phone ---------
    def _hq_loop(self) -> None:
        from pflab.hq import service
        service.start(self)
        while not self.stop.is_set():
            out = service.round_(self, stop=self.stop)
            self.hq_last_round = (self.clock(), sorted((out or {}).get("failed") or {}))   # the World reads the HQ's rounds from here
            self._hq_wake.wait(30)
            self._hq_wake.clear()

    def wake_hq(self) -> None:
        self._hq_wake.set()

    def _phone_loop(self) -> None:
        from pflab.hq import phone
        why = phone.loop(self, self.stop)
        if why:
            log.warning("Telegram phone not started: %s", why)

    def _live_loop(self) -> None:
        while not self.stop.is_set():
            if self.settings.get("live_prices", True):
                self.live_once()
            self.stop.wait(LIVE_EVERY_S)

    def kite(self):
        if self.secrets is None:
            return None
        from pflab.ingest import kite as k
        try:
            return k.client(self.secrets, now=self.clock())
        except Exception:
            return None

    def live_once(self) -> int:
        """In market hours with a Kite login: quotes for every held and list stock, and the main indices."""
        from pflab.pm import prices
        now = self.clock()
        if not prices.market_open(now) or not st.ability("kite_live", current=self.settings):
            return 0
        kc = self.kite()
        if kc is None:
            return 0
        from pflab.ingest import kite as k
        from pflab.plan import guards as gd
        from pflab.pm import today as nw
        cur = self.cursor()
        pos = nw.build(cur, now.date())["positions"]
        isins = sorted(set(pos["isin"]) | {s["isin"] for s in gd.stock_list()})
        sym = {r[0]: r[1] for r in cur.execute("SELECT isin, symbol FROM instruments WHERE symbol IS NOT NULL").fetchall()}
        n = prices.LivePoller(cur, isins, k.make_quote_fn(kc, sym)).poll(now)
        try:
            got = kc.ltp(*INDICES.values())
            back = {v: name for name, v in INDICES.items()}
            for key, v in got.items():
                if key in back and v.get("last_price"):
                    self.live_indices[back[key]] = {"value": float(v["last_price"]), "at": now.isoformat(timespec="seconds")}
        except Exception:
            log.exception("index quotes failed")
        self.bump("live", "portfolio", "command")
        return n

    def _mc_loop(self) -> None:
        while not self.stop.is_set():
            if self.paused():
                self.stop.wait(600)
                continue
            c = self.mc_cache()
            age = (self.clock() - datetime.fromisoformat(c["at"])).total_seconds() / 3600 if c else 1e9
            if age >= MC_MAX_AGE_H:
                try:
                    self.mc_once()
                    self.mc_error = None
                except Exception as e:                           # (2026-10-31) said on the screen as a failure, retried in an hour, never a 60 s loop
                    self.mc_error = f"{type(e).__name__}: {str(e)[:200]}"
                    log.exception("fall-limit simulation failed")
                    self.bump("health", "command")
            from pflab.app import chat, inbox
            if chat.tidy(self.cursor(), self.clock()):            # chats untouched for 30 days -> memory
                self.bump("chat")
            inbox.cleanup(self)                                   # screenshot images after 7 days (their text stays)
            self.nightly_sims()
            self.stop.wait(3600)

    def nightly_sims(self) -> Optional[dict]:
        """Once a night after `sims_hour`: every mix at the preset's paths (none when off or light)."""
        from pflab.app import sims
        now = self.clock()
        paths = st.sims_paths(self.settings.get("preset", "full"))
        if not paths or now.hour < self.settings.get("sims_hour", 22) or self.sims_running:
            return None
        last = (sims.cached(self) or {}).get("at")
        if last and datetime.fromisoformat(last) >= now.replace(hour=self.settings.get("sims_hour", 22), minute=0,
                                                                second=0, microsecond=0):
            return None
        return sims.run(self, paths=paths, years=5)

    def _research_loop(self) -> None:
        """S54c: the watch list every 6 hours, the ready plan every 12, price watches every 10 minutes."""
        from pflab.app import research as rs
        while not self.stop.is_set():
            if self.paused():
                self.stop.wait(600)
                continue
            for name, hours, fn in (("watch", 6, rs.compute_watch), ("plan", 12, rs.compute_plan)):
                c = rs.read_cache(self, name)
                age = (self.clock() - datetime.fromisoformat(c["at"])).total_seconds() / 3600 if c else 1e9
                if age >= hours and not self.stop.is_set():
                    fn(self)
            rs.check_watches(self)
            self.stop.wait(600)

    def mc_path(self) -> Path:
        return self.pm_dir / "app" / "cache" / "montecarlo.json"

    def mc_cache(self) -> Optional[dict]:
        p = self.mc_path()
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except ValueError:
            return None

    def mc_once(self, paths: int = MC_PATHS) -> dict:
        """The current mix over one year (block bootstrap, any-day falls), with the tail chance's standard error."""
        import numpy as np

        from pflab.app import sims
        from pflab.risk import montecarlo as mc
        now = self.clock()
        R, Rd, _ = sims.history(self.cursor(), self.data_root, now.date())
        w = sims.weights(sims.current_mix(self.cursor(), now.date()))
        rng = np.random.default_rng(20261015)
        p = float(mc.fall_any_day_block(Rd.values, w, 12, paths, rng))
        y1 = sims.fan(R.values, w, 12, paths, rng)["years"]["1"]
        out = {"at": now.isoformat(timespec="seconds"), "paths": paths, "years": 1, "p_fall35": p,
               "se_pp": math.sqrt(p * (1 - p) / paths) * 100, "median": y1["p50"], "p5": y1["p5"],
               "p95": y1["p95"], "history": f"{R.index[0]:%b %Y}-{R.index[-1]:%b %Y}",
               "left_out": sims.left_out(self.cursor(), now.date())}
        p_ = self.mc_path()
        p_.parent.mkdir(parents=True, exist_ok=True)
        p_.write_text(json.dumps(out, indent=1), encoding="utf-8")
        self.bump("mc", "command")
        return out

    # --- Kite login from the screen -------------------------------------------------------------------------------------
    def kite_login(self) -> str:
        """Start the day's Kite login: returns the URL to open; a background thread waits for Kite's redirect."""
        from pflab.ingest import kite as k
        if self.secrets is None:
            raise RuntimeError("no secrets file: Kite's api_key and api_secret are needed")
        flow = k.LoginFlow(self.secrets)
        url = flow.begin()
        redirect = self.secrets.get("kite", "redirect_url") if self.secrets.has("kite", "redirect_url") \
            else "http://127.0.0.1:5000/redirect"
        self.kite_state = "waiting"
        self.bump("kite")

        def wait():
            try:
                _kite_tools().wait_for_token(flow, redirect)
                self.kite_state = "done"
                self._want("tradecheck")               # S58b: the portfolio today, straight after the login
            except Exception as e:                      # shown on the screen
                self.kite_state = f"failed: {e}"
            self.bump("kite", "command")
        threading.Thread(target=wait, name="kite-login", daemon=True).start()
        return url

    # --- clients (closing the last window stops the system) ------------------------------------------------------------
    def client_open(self) -> None:
        self.clients += 1
        self.had_client = True

    def client_closed(self) -> None:
        self.clients = max(0, self.clients - 1)
        self.last_client = self.clock()

    def idle_for(self) -> float:
        """Seconds without any open window, once one has been open (0 while one is open)."""
        if self.clients or not self.had_client:
            return 0.0
        return (self.clock() - self.last_client).total_seconds()


def code_stamp(repo: Path) -> float:
    """The newest modification time of the system's code and screen files: it changes when the code is updated."""
    src = Path(repo) / "src" / "pflab"
    try:
        return max((p.stat().st_mtime for p in src.rglob("*") if p.suffix in (".py", ".js", ".css", ".html")), default=0.0)
    except OSError:
        return 0.0


def _python() -> str:
    """The console python beside pythonw (jobs start tools with it)."""
    exe = Path(sys.executable)
    alt = exe.with_name("python.exe")
    return str(alt if exe.name.lower() == "pythonw.exe" and alt.exists() else exe)


def _kite_tools():
    import importlib.util
    p = Path(__file__).resolve().parents[3] / "tools" / "kite_login.py"
    spec = importlib.util.spec_from_file_location("pflab_tools_kite_login", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def token_valid(now: Optional[datetime] = None) -> bool:
    from pflab.ingest import kite as k
    return k.TokenStore().load(now or datetime.now()) is not None


def since(dt: Optional[datetime], now: datetime) -> str:
    if dt is None:
        return "never"
    s = (now - dt).total_seconds()
    return "just now" if s < 90 else f"{int(s // 60)} min ago" if s < 3600 else f"{s / 3600:.1f} h ago" \
        if s < 86400 else dt.strftime("%d %b %H:%M")
