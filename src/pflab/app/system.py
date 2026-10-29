r"""The system as one honest picture (S66; his 2026-10-28 ask: the dashboard must show a system that is alive, working and in sync).

    connectors  Kite, Gmail, Telegram, the local model, the Claude API (spend against his cap), the sandbox (Docker), the release
    freshness   each data source: its latest data against the last session that should have brought it (fresh, late, stale)
    work        what is running now, what finished lately in plain words, what failed in the last day
    needs       what only he can answer, grouped (six Tijori requests are one line)

Everything here is read from the store, the data folder and the machine; nothing is guessed or written. The same picture is the assistant's
`system_status` tool, so the chat and the screen can never disagree.

S67: green means an operation SUCCEEDED and its data is usable, not that a token file or a key exists. A failed run never refreshes a
"last good" time (`_attempts` separates the last success from the failures after it); data kept from before a failed refresh is shown as
retained and stale, with the failure beside it; a job whose sub-step failed counts as failed (`jobs.run_job`); a connector's colour comes
from its last real use (a snapshot read, a mail run, a message sent, an API call, the sandbox probe).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

OK, WARN, DOWN, OFF = "ok", "warn", "down", "off"
_CACHE: Dict[str, tuple] = {}
_LOCK = threading.Lock()
_BUSY: set = set()
FIRST_WAIT_S = 0.4          # the very first look waits this long for a slow probe, then answers "not known yet" instead of holding the screen


def _cached(key: str, ttl: float, fn, default=None):
    """Stale-while-revalidate: a probe that talks to another program (Ollama, Docker) can be slow or hang, and the screen asks for the
    picture every few seconds. An expired answer is returned at once while ONE background thread refreshes it; the first ever look waits
    at most FIRST_WAIT_S for it and otherwise answers `default`. The picture is never slower than its slowest cached part."""
    t = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        fresh = hit is not None and t - hit[0] < ttl
        if fresh:
            return hit[1]
        start = key not in _BUSY
        if start:
            _BUSY.add(key)

    def refresh():
        try:
            v = fn()
        except Exception:
            v = default if hit is None else hit[1]
        with _LOCK:
            _CACHE[key] = (time.time(), v)
            _BUSY.discard(key)

    if start:
        th = threading.Thread(target=refresh, name=f"probe-{key}", daemon=True)
        th.start()
        if hit is None:
            th.join(FIRST_WAIT_S)
    if hit is not None:
        return hit[1]
    with _LOCK:
        got = _CACHE.get(key)
    return got[1] if got else default


# --- the machine ----------------------------------------------------------------------------------------------------------

def _ollama() -> dict:
    def look():
        try:
            with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.5) as r:
                names = [m["name"] for m in json.loads(r.read()).get("models", [])]
            return {"up": True, "models": names}
        except Exception:
            return {"up": False, "models": []}
    return _cached("ollama", 30, look, {"up": False, "models": [], "pending": True})


def _docker_probe() -> str:
    if not shutil.which("docker"):
        return "not installed"
    try:
        r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=4,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "running" if r.returncode == 0 and r.stdout.strip() else "not running"
    except Exception:
        return "not running"


def _docker() -> str:
    return _cached("docker", 300, _docker_probe, "checking")


def _sandbox_status() -> dict:
    from pflab.agents import sandbox as sb
    return _cached("sandbox", sb.CACHE_S, lambda: sb.status(force=True), {"ok": False, "why": "still checking"})


def record_check(con, connector: str, ok: bool, now: datetime, detail: str = "", usable: Optional[bool] = None) -> int:
    """Keep the result of a real operation on a connector (a probe, a permitted read): the screen's colour comes from the latest."""
    from pflab.pm.store import next_id
    cid = next_id(con, "health_checks", "check_id")
    con.execute("INSERT INTO health_checks VALUES (?,?,?,?,?,?)", [cid, connector, now, bool(ok), usable, detail[:400]])
    return cid


def latest_check(con, connector: str) -> Optional[dict]:
    r = con.execute("SELECT checked_at, ok, usable, detail FROM health_checks WHERE connector=? ORDER BY check_id DESC LIMIT 1", [connector]).fetchone()
    return {"at": r[0], "ok": r[1], "usable": r[2], "detail": r[3]} if r else None


# --- what really happened --------------------------------------------------------------------------------------------------

def _attempts(con, job: str) -> dict:
    """The last success of a job and the failures after it: {"ok": started_at | None, "failed_at": ..., "why": ...}. A failure BEFORE the last
    success is history; one after it means the data kept since is retained, not refreshed."""
    ok = con.execute("SELECT max(started_at) FROM job_runs WHERE job=? AND status='ok'", [job]).fetchone()[0]
    f = con.execute("SELECT started_at, detail FROM job_runs WHERE job=? AND status='failed' AND "
                    "detail IS DISTINCT FROM 'abandoned: the process stopped before it finished' AND (? IS NULL OR started_at > ?) "
                    "ORDER BY started_at DESC LIMIT 1", [job, ok, ok]).fetchone()
    return {"ok": ok, "failed_at": f[0] if f else None, "why": _short_error(f[1]) if f else None}


def _short_error(detail) -> str:
    """A failed run's reason in a line (the detail is a redacted message, or a JSON dict with a `failed` part)."""
    t = str(detail or "")
    try:
        d = json.loads(t)
        if isinstance(d, dict) and d.get("failed"):
            t = "; ".join(f"{k}: {v}" for k, v in d["failed"].items())
    except ValueError:
        pass
    return re.sub(r"\s+", " ", t)[:140]


# --- connectors -------------------------------------------------------------------------------------------------------------

def _last_run(con, job: str):
    return con.execute("SELECT started_at, status FROM job_runs WHERE job=? AND status IN ('ok','failed','skipped') "
                       "ORDER BY started_at DESC LIMIT 1", [job]).fetchone()


def connectors(rt, now: datetime) -> List[dict]:
    from pflab import release
    from pflab.agents import analyst
    from pflab.agents import sandbox as sb
    from pflab.app import runtime as rtm
    from pflab.ingest import gmail
    from pflab.pm import secrets_setup as ss
    con = rt.cursor()
    out = []

    # Kite: a login that is valid AND a read that worked since (a snapshot of holdings, cash and trades)
    valid = rtm.token_valid(now)
    snap = con.execute("SELECT max(taken_at) FROM kite_snapshots").fetchone()[0]
    tc = _attempts(con, "tradecheck")
    if not valid:
        k = (WARN, "not logged in today: figures are from your statements" + (f"; last read {str(snap)[:16]}" if snap else ""), "kite")
    elif snap is None or now - snap > timedelta(hours=24):
        k = (WARN, "logged in, but no read has worked in the last day" + (f" (last {str(snap)[:16]})" if snap else "")
             + (f"; the last attempt failed: {tc['why']}" if tc["failed_at"] else ""), None)
    elif tc["failed_at"] and tc["failed_at"] > snap:
        k = (WARN, f"logged in; the latest read failed ({tc['why']}); holdings shown are from {str(snap)[:16]}", None)
    else:
        k = (OK, f"logged in today: holdings, cash and trades read {str(snap)[:16]}", None)
    out.append({"id": "kite", "name": "Kite", "state": k[0], "line": k[1], "action": k[2]})

    # Gmail: a saved token is not a working mailbox; the state is the last mail run
    if gmail.connected():
        f = {st: n for st, n in con.execute("SELECT status, count(*) FROM mail_facts WHERE kind <> 'other' GROUP BY status").fetchall()}
        ma = _attempts(con, "mail")
        seen = con.execute("SELECT count(*), max(seen_at) FROM mail_seen").fetchone()
        odd = (f.get("conflict", 0) or 0) + (f.get("new", 0) or 0)
        base = f"{seen[0]} mails looked at" + (f", last {str(seen[1])[:16]}" if seen[1] else "")
        if ma["failed_at"]:
            g = (WARN, f"saved login, but the latest read failed ({ma['why']}); {base}; showing what was read before")
        elif ma["ok"] is None:
            g = (WARN, "connected; no successful read yet")
        elif now - ma["ok"] > timedelta(days=2):
            g = (WARN, f"connected, but not read since {str(ma['ok'])[:16]} (it should run daily); {base}")
        elif odd:
            g = (WARN, f"{base}; {odd} email fact(s) not in your record")
        else:
            g = (OK, f"{base}; {f.get('matched', 0)} email facts matched your record")
        out.append({"id": "gmail", "name": "Gmail (read-only)", "state": g[0], "line": g[1], "action": None})
    else:
        out.append({"id": "gmail", "name": "Gmail (read-only)", "state": WARN if gmail.has_client() else OFF,
                    "line": "not connected: press Connect so statements and money emails arrive by themselves" if gmail.has_client()
                            else "not connected: do the one-time Google step (README step 5), then Connect", "action": "gmail"})

    # Telegram: switched on is not delivering; look at what the outbox could and could not send
    tg = bool(rt.settings.get("telegram_send"))
    held = con.execute("SELECT count(*) FROM outbox WHERE status='pending'").fetchone()[0]
    bad = con.execute("SELECT count(*), max(last_error) FROM outbox WHERE status='pending' AND attempts > 0").fetchone()
    last_sent = con.execute("SELECT max(sent_at) FROM outbox").fetchone()[0]
    if not tg:
        t = (WARN, "off: messages are held, not sent" + (f"; {held} waiting" if held else ""), "settings")
    elif bad[0]:
        t = (WARN, f"on, but {bad[0]} message(s) failed to send ({str(bad[1] or '')[:80]})", None)
    else:
        t = (OK, "sending" + (f"; last delivered {str(last_sent)[:16]}" if last_sent else "; nothing sent yet") + (f"; {held} waiting" if held else ""), None)
    out.append({"id": "telegram", "name": "Telegram", "state": t[0], "line": t[1], "action": t[2]})

    ol = _ollama()
    need = {"qwen3:8b-q8_0", "nomic-embed-text:latest"}
    missing = sorted(need - set(ol["models"]))
    out.append({"id": "local", "name": "Local model", "state": OK if ol["up"] and not missing else DOWN,
                "line": ("running on this PC; both models present" if ol["up"] and not missing else
                         "Ollama is not running: local reading, emails and drafts wait" if not ol["up"] else f"missing: {', '.join(missing)}"), "action": None})

    # Claude API: a key and a cap are not a working road; the last call says
    cfg = analyst.config()
    spent = analyst.month_spend_inr(con, now)
    key = ss.status().get("anthropic.api_key", False)
    pct = spent / cfg["cap"] if cfg["cap"] > 0 else 0
    last = con.execute("SELECT status, finished_at, error FROM api_calls WHERE status IN ('done','failed') ORDER BY call_id DESC LIMIT 1").fetchone()
    if cfg["cap"] <= 0:
        a = (OFF, "no monthly cap set: nothing is sent")
    elif not key:
        a = (DOWN, f"Rs {spent:,.0f} of Rs {cfg['cap']:,.0f} this month ({pct:.0%}); no key saved")
    elif last and last[0] == "failed":
        a = (WARN, f"Rs {spent:,.0f} of Rs {cfg['cap']:,.0f} this month ({pct:.0%}); the last call failed ({str(last[2] or '')[:80]})")
    else:
        a = (WARN if pct >= 0.8 else OK, f"Rs {spent:,.0f} of Rs {cfg['cap']:,.0f} this month ({pct:.0%})"
             + (f"; last call worked {str(last[1])[:16]}" if last else "; not used yet"))
    out.append({"id": "api", "name": "Claude API", "state": a[0], "line": a[1], "action": None})

    # Sandbox: Docker answering and the image built, and a containment probe that passed
    dk = _docker()
    ss_ = _sandbox_status() if dk == "running" else {"ok": False, "why": {"not running": "Docker is not running", "checking": "still checking Docker"}.get(dk, "Docker is not installed")}
    probe = con.execute("SELECT checked_at, ok, detail FROM health_checks WHERE connector='sandbox' ORDER BY check_id DESC LIMIT 1").fetchone()
    if not ss_["ok"]:
        sx = (WARN, f"{ss_['why']}: calculations wait; nothing generated is run outside a container")
    elif probe is None:
        sx = (WARN, "Docker works; containment has not been proven yet (the weekly probe or `pflab verify` does it)")
    elif not probe[1]:
        sx = (DOWN, f"containment probe FAILED {str(probe[0])[:16]}: {str(probe[2])[:100]}; calculations are blocked")
    elif now - probe[0] > timedelta(days=14):
        sx = (WARN, f"containment last proven {str(probe[0])[:10]}: older than two weeks")
    else:
        sx = (OK, f"contained: no network, read-only files (proven {str(probe[0])[:16]})")
    out.append({"id": "sandbox", "name": "Sandbox (Docker)", "state": sx[0], "line": sx[1], "action": None})

    r = release.load()
    out.append({"id": "release", "name": "Release", "state": WARN if rt.update_ready else OK,
                "line": ((r or {}).get("app", {}).get("tag", "") or "workshop") + (" · new code is ready, restarts when quiet" if rt.update_ready else " · updates itself at each start"),
                "action": None})
    return out


# --- freshness ---------------------------------------------------------------------------------------------------------------

def _state(latest: Optional[date], expected: date, ok_days: int = 1, stale_days: int = 4) -> str:
    """ok within the source's normal lag; warn after it; down once it is clearly stale. Nothing yet is waiting (warn), not broken."""
    if latest is None:
        return WARN
    gap = (expected - latest).days
    return OK if gap <= ok_days else WARN if gap <= stale_days else DOWN


def _d(x) -> Optional[date]:
    if x is None:
        return None
    return x.date() if isinstance(x, datetime) else x


JOB_OF = {"Close prices": "prices", "Fund NAVs": "nav", "Gold rates": "nav", "Company filings": "filings", "News": "kg",
          "Kite snapshot": "tradecheck", "Email": "mail"}


def freshness(rt, now: datetime) -> List[dict]:
    """Each source's latest data against the last closed session. `gap` is in days; fresh = nothing missing. A refresh that failed after the
    data was last good makes the row at least `warn` and says so: the data on screen is RETAINED, not current."""
    from pflab.app import views
    from pflab.conductor import calendar as cal
    con = rt.cursor()
    exp = cal.load().last_closed_session(now)
    rows = []

    def add(name: str, latest, kind: str = "market", ok: int = 1, stale: int = 4, line: str = ""):
        d = _d(latest)
        st = _state(d, exp if kind == "market" else now.date(), ok, stale)
        row = {"name": name, "latest": str(d) if d else None, "state": st,
               "line": line or (f"latest {d}" if d else "nothing yet"), "gap": (exp - d).days if d else None, "retained": False}
        job = JOB_OF.get(name)
        if job:
            at = _attempts(con, job)
            if at["failed_at"] is not None:
                row["retained"] = True
                row["state"] = DOWN if st == DOWN else WARN
                row["line"] += f"; showing the last good data: the refresh failed at {str(at['failed_at'])[:16]} ({at['why']})"
                row["refresh_failed_at"] = str(at["failed_at"])[:16]
        rows.append(row)
    add("Close prices", con.execute("SELECT max(date) FROM prices").fetchone()[0])
    for t in views.tickers(rt.data_root, rt.live_indices):
        if t["date"] and t["date"] != "live":
            add(t["name"], date.fromisoformat(t["date"]))
    add("Fund NAVs", con.execute("SELECT max(date) FROM navs").fetchone()[0], ok=2)
    add("Gold rates", con.execute("SELECT max(date) FROM gold_rates").fetchone()[0], ok=2)
    add("Company filings", con.execute("SELECT max(published_at) FROM kg_docs WHERE kind='filing'").fetchone()[0], "clock", ok=3, stale=7,
        line="the latest filing the system holds")
    add("News", con.execute("SELECT max(published_at) FROM kg_docs WHERE kind='article'").fetchone()[0], "clock", ok=2, stale=5)
    snap = con.execute("SELECT max(taken_at) FROM kite_snapshots").fetchone()[0]
    add("Kite snapshot", snap, "clock", ok=3, stale=10, line=f"holdings read from Kite {str(snap)[:16]}" if snap else "never logged in")
    mc = rt.mc_cache()
    add("Fall-limit simulation", (datetime.fromisoformat(str(mc["at"])[:19]) if mc and mc.get("at") else None), "clock", ok=7, stale=30)
    from pflab.ingest import gmail
    if gmail.connected():
        ok_at = _attempts(con, "mail")["ok"]                      # only a SUCCESSFUL run is a read: a failed one does not refresh this
        add("Email", ok_at, "clock", ok=2, stale=5, line=f"last successful read {str(ok_at)[:16]}" if ok_at else "not read yet")
    try:
        from pflab.pm import today
        td = today.build(con, now.date())["today"]
        if td.get("documents_to"):
            add("Your statements (to)", td["documents_to"], "clock", ok=40, stale=75, line=f"statements run to {td['documents_to']}")
    except Exception:
        pass
    return rows


# --- work ----------------------------------------------------------------------------------------------------------------------

def _n(d: dict, *keys) -> int:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, (list, dict)):
            return len(v)
    return 0


SAY = {
    "collect": lambda d: "collected the day's market data" if not d else "collected the day's market data (" + ", ".join(
        f"{k.replace('_', ' ')} {v}" for k, v in list(d.items())[:3] if isinstance(v, (int, float)) and v) + ")",
    "filings": lambda d: f"checked company filings: {_n(d, 'filings')} for {_n(d, 'names')} of your names; {_n(d, 'alerts_queued')} alert(s)",
    "kg": lambda d: "updated the knowledge graph",
    "hq": lambda d: ("the brain thought: nothing new" if "nothing new" in str(d.get("brain", "")) else "the brain ran a pass and wrote to its journal"),
    "conductor": lambda d: f"checked the system's own state: {_n(d, 'ok')} fine, {_n(d, 'warn')} to watch, {_n(d, 'asked')} question(s)",
    "outbox": lambda d: f"messages: {_n(d, 'sent')} sent, {_n(d, 'still_pending')} held",
    "mail": lambda d: "read your email" + (f": {_n(d, 'kept')} statement file(s) kept" if d.get("kept") else ": nothing new"),
    "twin": lambda d: "updated the scoreboard (your book against the paper books)",
    "plans": lambda d: "worked out ready plans for the next money",
    "forecast": lambda d: "scored and made price-range forecasts",
    "prices": lambda d: "loaded the closing prices into your record",
    "nav": lambda d: "loaded fund NAVs and gold rates",
    "guards": lambda d: "checked your holdings against your rules",
    "research": lambda d: "ran the research pass over your names",
    "analyst": lambda d: "the analyst looked over what is new",
    "watches": lambda d: "checked your price watches",
    "tradecheck": lambda d: "compared Kite's trades with your record",
}


def say_job(job: str, detail: Optional[str]) -> str:
    try:
        d = json.loads(detail) if detail else {}
        d = d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        d = {}
    if job in SAY:
        try:
            return SAY[job](d)
        except Exception:
            pass
    shown = [f"{k.replace('_', ' ')} {v}" for k, v in d.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v][:3]
    return f"{job.replace('_', ' ')}: " + (", ".join(shown) if shown else "nothing new")


def work(rt, now: datetime) -> dict:
    from pflab.hq import board, cases
    con = rt.cursor()
    running = [{"job": j, "since": str(s)[11:16]} for j, s in con.execute(
        "SELECT job, started_at FROM job_runs WHERE status='running' ORDER BY started_at").fetchall()]
    if rt.busy and not any(r["job"] in rt.busy for r in running):
        running.append({"job": rt.busy, "since": ""})
    recent = [{"at": str(s)[:16], "job": j, "ok": st != "failed", "says": say_job(j, d) if st != "failed" else f"{j.replace('_', ' ')} failed: {_short_error(d)}"}
              for j, s, st, d in con.execute(
                  "SELECT job, started_at, status, detail FROM job_runs WHERE status IN ('ok','failed') AND job NOT IN ('outbox', 'conductor') "
                  "ORDER BY started_at DESC LIMIT 8").fetchall()]
    failed = con.execute("SELECT count(*) FROM job_runs WHERE status='failed' AND started_at >= ? AND "
                         "detail IS DISTINCT FROM 'abandoned: the process stopped before it finished'", [now - timedelta(days=1)]).fetchone()[0]
    inv = []
    for c in cases.listing(con, 12, active_only=True):
        inv.append({"id": c["id"], "question": c["question"][:160], "status": c["status"], "since": str(c["opened"])[:10],
                    "waiting_for": [d["request"][:120] for d in c["dependencies"] if d["status"] == "open"],
                    "evidence": {k: c["assessment"][k] for k in ("for", "against", "missing", "stale")},
                    "next": str(c["next_review"])[:16] if c["status"] in ("retry",) and c["next_review"] else None,
                    "error": (c["error"] or "")[:120] or None})
    decided = [{"id": c["id"], "question": c["question"][:120], "decision": c["decision"], "reason": (c["reason"] or "")[:160],
                "review": str(c["next_review"])[:10] if c["next_review"] else None}
               for c in cases.listing(con, 6) if c["status"] == "done"]
    return {"running": running, "recent": recent, "failed_24h": int(failed), "tasks": board.counts(con), "held": board.held(con),
            "investigating": inv, "decided": decided}


# --- needs -----------------------------------------------------------------------------------------------------------------------

def _first(text: str, n: int = 170) -> str:
    s = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def needs(con, limit: int = 6) -> dict:
    """Open questions, grouped: the same kind of request is one line with a count."""
    rows = con.execute("SELECT q_id, agent, subject_key, text, created_at FROM questions WHERE status='open' ORDER BY q_id DESC").fetchall()
    groups: Dict[str, dict] = {}
    for qid, agent, key, text, at in rows:
        g = "tijori" if (key or "").startswith("tijori:") else (key or str(qid)).split(":")[0] + ":" + ((key or "").split(":")[1] if (key or "").startswith("mail:") else "")
        if g in groups:
            groups[g]["count"] += 1
            groups[g]["names"].append(re.sub(r".*sheet for (\S+).*", r"\1", text) if g == "tijori" else "")
            continue
        groups[g] = {"id": qid, "agent": agent, "count": 1, "at": str(at)[:16], "title": _first(text), "names": [re.sub(r".*sheet for (\S+).*", r"\1", text)] if g == "tijori" else [],
                     "go": {"mail": "settings", "inbox": "inbox", "tijori": "inbox"}.get(g.split(":")[0], "inbox")}
    out = []
    for g in groups.values():
        if g["count"] > 1 and g["names"] and g["names"][0]:
            g["title"] = f"{g['count']} company sheets are missing (Tijori): " + ", ".join(sorted(set(n for n in g["names"] if n))[:6]) + ". Drop them in Inbox and files."
        out.append({k: v for k, v in g.items() if k != "names"})
    return {"total": len(rows), "groups": len(out), "items": out[:limit]}


# --- is it current? (before anything queued is shown as current) ------------------------------------------------------------------------

def stale_prices(con, now: datetime) -> Optional[str]:
    """Why the closing prices are not current (they exist but are older than the last closed session by more than the normal lag), else None.
    A store with no prices yet is not "stale": it has nothing to be old."""
    from pflab.conductor import calendar as cal
    px = con.execute("SELECT max(date) FROM prices").fetchone()[0]
    if px is None:
        return None
    try:
        exp = cal.load().last_closed_session(now)
    except Exception:
        exp = now.date() - timedelta(days=1)
    if (exp - px).days <= 1:
        return None
    why = f"closing prices are from {px}, the last session was {exp}"
    at = _attempts(con, "prices")
    if at["failed_at"]:
        why += f" (the latest refresh failed: {at['why']})"
    return why


def critical_fresh(con, now: datetime) -> tuple:
    """(True, "") when the data a recommendation stands on is current, else (False, why). Cheap: two small queries. After a sleep or a
    shutdown this is False until the catch-up has brought the data in."""
    if con.execute("SELECT max(date) FROM prices").fetchone()[0] is None:
        return False, "no prices in the record yet"
    why = stale_prices(con, now)
    return (False, why) if why else (True, "")


def recommendations(rt, now: datetime) -> dict:
    """What is waiting for him (suggestions not answered or scored, ready plans) and whether it may be shown as current: not while the
    prices behind it are old or the system is catching up after being off."""
    con = rt.cursor()
    ok, why = critical_fresh(con, now)
    catching = getattr(rt, "catching_up", None)
    if ok and catching:
        ok, why = False, f"catching up: {catching}"
    items = []
    for sid, kind, sym, text, made in con.execute(
            "SELECT sug_id, kind, symbol, text, made_at FROM hq_suggestions WHERE shadow=false AND answer='none' AND scored_at IS NULL "
            "ORDER BY sug_id DESC LIMIT 10").fetchall():
        items.append({"kind": "suggestion", "id": sid, "text": f"{kind} {sym or ''}: {text}"[:200], "made": str(made)[:16]})
    for pid, key, due, amount, created in con.execute(
            "SELECT plan_id, trigger_key, due, amount, created_at FROM ready_plans WHERE status='current' ORDER BY due LIMIT 10").fetchall():
        items.append({"kind": "plan", "id": pid, "text": f"ready plan '{key}' due {due}", "made": str(created)[:16]})
    return {"current": ok, "why": why or None, "items": items,
            "say": None if ok or not items else f"{len(items)} item(s) were prepared earlier and are NOT shown as current: {why}"}


# --- what changed since he last looked ------------------------------------------------------------------------------------------------------

def _visit_path(rt):
    return rt.pm_dir / "app" / "last_visit.json"


def last_visit(rt) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(json.loads(_visit_path(rt).read_text(encoding="utf-8"))["at"])
    except (OSError, ValueError, KeyError):
        return None


def mark_visit(rt, now: Optional[datetime] = None) -> None:
    p = _visit_path(rt)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"at": (now or rt.clock()).isoformat(timespec="seconds")}), encoding="utf-8")


def changed_since(con, since: Optional[datetime], now: datetime, limit: int = 12) -> dict:
    """What happened since `since`, in plain lines, newest first: decisions the system reached, cases opened, suggestions made, questions
    it asked, things that failed. Read from the store; nothing is invented."""
    since = since or (now - timedelta(days=1))
    rows = []
    for cid, q, dec, reason, at in con.execute("SELECT case_id, question, decision, decision_reason, closed_at FROM hq_cases "
                                               "WHERE closed_at >= ? ORDER BY closed_at DESC", [since]).fetchall():
        rows.append((at, "decided", f"Investigation #{cid} decided: {dec}. {q[:100]}"))
    for cid, q, at, origin in con.execute("SELECT case_id, question, opened_at, origin FROM hq_cases WHERE opened_at >= ? ORDER BY opened_at DESC",
                                          [since]).fetchall():
        rows.append((at, "opened", f"Started looking into: {q[:120]} ({'found by the system' if origin in ('code', 'scheduled', 'event', 'brain') else 'you asked'})"))
    for at, kind, sym, text in con.execute("SELECT made_at, kind, symbol, text FROM hq_suggestions WHERE shadow=false AND made_at >= ? "
                                           "ORDER BY made_at DESC", [since]).fetchall():
        rows.append((at, "suggestion", f"Suggestion ({kind} {sym or ''}): {text[:120]}"))
    for at, text in con.execute("SELECT created_at, text FROM questions WHERE created_at >= ? ORDER BY created_at DESC", [since]).fetchall():
        rows.append((at, "question", f"New question for you: {_first(text, 120)}"))
    for at, job, d in con.execute("SELECT started_at, job, detail FROM job_runs WHERE status='failed' AND started_at >= ? AND "
                                  "detail IS DISTINCT FROM 'abandoned: the process stopped before it finished' ORDER BY started_at DESC", [since]).fetchall():
        rows.append((at, "failed", f"{job.replace('_', ' ')} failed: {_short_error(d)}"))
    rows.sort(key=lambda r: r[0], reverse=True)
    return {"since": str(since)[:16], "count": len(rows), "items": [{"at": str(a)[:16], "kind": k, "text": t} for a, k, t in rows[:limit]]}


# --- where each thing is processed ---------------------------------------------------------------------------------------------------------

def processing(rt) -> List[dict]:
    """Which work stays on this PC and which goes to the cloud, in plain words, from the same settings the code obeys (the slider's
    models, the egress rules). The screen shows this list; no label is typed by hand on a page."""
    from pflab.hq import models
    def model(job: str) -> str:
        try:
            return models.model_id(job, rt.settings)
        except Exception:
            return "?"
    return [
        {"what": "His statements, ledger, tax lots and bank details", "where": "this PC", "model": "code", "sends": "nothing: they never leave"},
        {"what": "What his money emails say (trades, deposits, dividends, alerts)", "where": "this PC", "model": model("mail_reading"),
         "sends": "nothing: read by the local model only; each fact checked by code"},
        {"what": "Research or corporate-action emails that name none of his ids", "where": "cloud, after a check", "model": model("materiality"),
         "sends": "a redacted copy, only if the mail reader cleared it and it passes the identity check again at send time"},
        {"what": "Public filings, results and news", "where": "cloud", "model": model("materiality"), "sends": "the public document"},
        {"what": "Ask (local)", "where": "this PC", "model": model("routing"), "sends": "nothing"},
        {"what": "The brain's passes and investigations", "where": "cloud", "model": model("brain"),
         "sends": "his holdings, weights and amounts by name; never his identity, accounts, PAN, contact details or statements"},
        {"what": "Web search and deep research", "where": "cloud", "model": model("brain_web"), "sends": "a public question only"},
        {"what": "Calculations", "where": "code written in the cloud (column names and invented sample rows), run on this PC in a sandbox",
         "model": model("workshop"), "sends": "no rows; with no sandbox nothing is run"},
    ]


def _readiness(rt, now: datetime) -> dict:
    from pflab.app import readiness
    try:
        r = readiness.assess(rt, now)
    except Exception as e:                                      # the picture never fails because one part could not be read
        return {"ready": False, "percent": 0, "stages": [], "remaining": [], "gaps": [], "say": f"readiness could not be read: {type(e).__name__}"}
    return {k: r[k] for k in ("ready", "percent", "stages", "remaining", "say")} | {"gaps": r["gaps"][:8]}


# --- the picture ---------------------------------------------------------------------------------------------------------------

def picture(rt, now: Optional[datetime] = None) -> dict:
    now = now or rt.clock()
    con = rt.cursor()
    cs, fr = connectors(rt, now), freshness(rt, now)
    w, nd = work(rt, now), needs(con)
    rec = recommendations(rt, now)
    bad = [c["name"] for c in cs if c["state"] in (DOWN,)] + [f["name"] for f in fr if f["state"] == DOWN]
    late = [c["name"] for c in cs if c["state"] == WARN] + [f["name"] for f in fr if f["state"] == WARN]
    from pflab.hq import tools as tl
    kinds: Dict[str, int] = {}
    for t in tl.TOOLS.values():
        kinds[t.kind] = kinds.get(t.kind, 0) + 1
    catching = getattr(rt, "catching_up", None)
    verdict = ("everything is working and in sync" if not bad and not late else
               f"{len(bad)} thing(s) down: {', '.join(bad[:3])}" if bad else f"working; {len(late)} thing(s) late or waiting on you: {', '.join(late[:3])}")
    if catching:
        verdict = f"catching up ({catching}); " + verdict
    return {"at": now.isoformat(timespec="seconds"), "verdict": verdict, "state": DOWN if bad else WARN if late or catching else OK,
            "connectors": cs, "freshness": fr, "work": w, "needs": nd, "recommendations": rec, "catching_up": catching,
            "changed": changed_since(con, last_visit(rt), now), "processing": processing(rt), "readiness": _readiness(rt, now), "tools": {"total": len(tl.TOOLS), **kinds}}
