r"""The system as one honest picture (S66; his 2026-10-28 ask: the dashboard must show a system that is alive, working and in sync).

    connectors  Kite, Gmail, Telegram, the local model, the Claude API (spend against his cap), the sandbox (Docker), the release
    freshness   each data source: its latest data against the last session that should have brought it (fresh, late, stale)
    work        what is running now, what finished lately in plain words, what failed in the last day
    needs       what only he can answer, grouped (six Tijori requests are one line)

Everything here is read from the store, the data folder and the machine; nothing is guessed or written. The same picture is the assistant's
`system_status` tool, so the chat and the screen can never disagree.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.request
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

OK, WARN, DOWN, OFF = "ok", "warn", "down", "off"
_CACHE: Dict[str, tuple] = {}


def _cached(key: str, ttl: float, fn):
    t = time.time()
    if key in _CACHE and t - _CACHE[key][0] < ttl:
        return _CACHE[key][1]
    v = fn()
    _CACHE[key] = (t, v)
    return v


# --- the machine ----------------------------------------------------------------------------------------------------------

def _ollama() -> dict:
    def look():
        try:
            with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.5) as r:
                names = [m["name"] for m in json.loads(r.read()).get("models", [])]
            return {"up": True, "models": names}
        except Exception:
            return {"up": False, "models": []}
    return _cached("ollama", 30, look)


def _docker() -> str:
    def look():
        if not shutil.which("docker"):
            return "not installed"
        try:
            r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=4,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return "running" if r.returncode == 0 and r.stdout.strip() else "not running"
        except Exception:
            return "not running"
    return _cached("docker", 300, look)


# --- connectors -------------------------------------------------------------------------------------------------------------

def _last_run(con, job: str):
    return con.execute("SELECT started_at, status FROM job_runs WHERE job=? AND status IN ('ok','failed','skipped') "
                       "ORDER BY started_at DESC LIMIT 1", [job]).fetchone()


def connectors(rt, now: datetime) -> List[dict]:
    from pflab import release
    from pflab.agents import analyst
    from pflab.app import runtime as rtm
    from pflab.ingest import gmail
    from pflab.pm import secrets_setup as ss
    con = rt.cursor()
    out = []
    kite = rtm.token_valid(now)
    out.append({"id": "kite", "name": "Kite", "state": OK if kite else WARN,
                "line": "logged in today: holdings, cash and trades read now" if kite else "not logged in today: figures are from your statements",
                "action": None if kite else "kite"})
    if gmail.connected():
        f = {s: n for s, n in con.execute("SELECT status, count(*) FROM mail_facts WHERE kind <> 'other' GROUP BY status").fetchall()}
        last = _last_run(con, "mail")
        seen = con.execute("SELECT count(*), max(seen_at) FROM mail_seen").fetchone()
        odd = (f.get("conflict", 0) or 0) + (f.get("new", 0) or 0)
        out.append({"id": "gmail", "name": "Gmail (read-only)", "state": WARN if odd else OK,
                    "line": f"{seen[0]} mails looked at" + (f", last {str(seen[1])[:16]}" if seen[1] else "") +
                            (f"; {odd} email fact(s) not in your record" if odd else f"; {f.get('matched', 0)} email facts matched your record"),
                    "action": None})
    else:
        out.append({"id": "gmail", "name": "Gmail (read-only)", "state": WARN if gmail.has_client() else OFF,
                    "line": "not connected: press Connect so statements and money emails arrive by themselves" if gmail.has_client()
                            else "not connected: do the one-time Google step (README step 5), then Connect", "action": "gmail"})
    tg = bool(rt.settings.get("telegram_send"))
    held = con.execute("SELECT count(*) FROM outbox WHERE status='pending'").fetchone()[0]
    out.append({"id": "telegram", "name": "Telegram", "state": OK if tg else WARN,
                "line": ("sending" if tg else "off: messages are held, not sent") + (f"; {held} waiting" if held else ""), "action": None if tg else "settings"})
    ol = _ollama()
    need = {"qwen3:8b-q8_0", "nomic-embed-text:latest"}
    missing = sorted(need - set(ol["models"]))
    out.append({"id": "local", "name": "Local model", "state": OK if ol["up"] and not missing else DOWN,
                "line": ("running on this PC; both models present" if ol["up"] and not missing else
                         "Ollama is not running: local reading, emails and drafts wait" if not ol["up"] else f"missing: {', '.join(missing)}"), "action": None})
    cfg = analyst.config()
    spent = analyst.month_spend_inr(con, now)
    key = ss.status().get("anthropic.api_key", False)
    pct = spent / cfg["cap"] if cfg["cap"] > 0 else 0
    out.append({"id": "api", "name": "Claude API", "state": (DOWN if not key else WARN if pct >= 0.8 else OK) if cfg["cap"] > 0 else OFF,
                "line": (f"Rs {spent:,.0f} of Rs {cfg['cap']:,.0f} this month ({pct:.0%})" if cfg["cap"] > 0 else "no monthly cap set: nothing is sent")
                        + ("" if key else "; no key saved"), "action": None})
    dk = _docker()
    out.append({"id": "sandbox", "name": "Sandbox (Docker)", "state": OK if dk == "running" else WARN,
                "line": "running: calculations run contained" if dk == "running" else f"{dk}: calculations fall back to a local process, marked uncontained",
                "action": None})
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


def freshness(rt, now: datetime) -> List[dict]:
    """Each source's latest data against the last closed session. `gap` is in days; fresh = nothing missing."""
    from pflab.app import views
    from pflab.conductor import calendar as cal
    con = rt.cursor()
    exp = cal.load().last_closed_session(now)
    rows = []

    def add(name: str, latest, kind: str = "market", ok: int = 1, stale: int = 4, line: str = ""):
        d = _d(latest)
        st = _state(d, exp if kind == "market" else now.date(), ok, stale)
        rows.append({"name": name, "latest": str(d) if d else None, "state": st,
                     "line": line or (f"latest {d}" if d else "nothing yet"), "gap": (exp - d).days if d else None})
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
    last = _last_run(con, "mail")
    from pflab.ingest import gmail
    if gmail.connected():
        add("Email", last[0] if last else None, "clock", ok=2, stale=5, line=f"read {str(last[0])[:16]}" if last else "not read yet")
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
    con = rt.cursor()
    running = [{"job": j, "since": str(s)[11:16]} for j, s in con.execute(
        "SELECT job, started_at FROM job_runs WHERE status='running' ORDER BY started_at").fetchall()]
    if rt.busy and not any(r["job"] in rt.busy for r in running):
        running.append({"job": rt.busy, "since": ""})
    recent = [{"at": str(s)[:16], "job": j, "ok": st != "failed", "says": say_job(j, d) if st != "failed" else f"{j.replace('_', ' ')} failed: {(d or '')[:120]}"}
              for j, s, st, d in con.execute(
                  "SELECT job, started_at, status, detail FROM job_runs WHERE status IN ('ok','failed') AND job NOT IN ('outbox', 'conductor') "
                  "ORDER BY started_at DESC LIMIT 8").fetchall()]
    failed = con.execute("SELECT count(*) FROM job_runs WHERE status='failed' AND started_at >= ?", [now - timedelta(days=1)]).fetchone()[0]
    return {"running": running, "recent": recent, "failed_24h": int(failed)}


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


# --- the picture ---------------------------------------------------------------------------------------------------------------

def picture(rt, now: Optional[datetime] = None) -> dict:
    now = now or rt.clock()
    con = rt.cursor()
    cs, fr = connectors(rt, now), freshness(rt, now)
    w, nd = work(rt, now), needs(con)
    bad = [c["name"] for c in cs if c["state"] in (DOWN,)] + [f["name"] for f in fr if f["state"] == DOWN]
    late = [c["name"] for c in cs if c["state"] == WARN] + [f["name"] for f in fr if f["state"] == WARN]
    from pflab.hq import tools as tl
    kinds: Dict[str, int] = {}
    for t in tl.TOOLS.values():
        kinds[t.kind] = kinds.get(t.kind, 0) + 1
    verdict = ("everything is working and in sync" if not bad and not late else
               f"{len(bad)} thing(s) down: {', '.join(bad[:3])}" if bad else f"working; {len(late)} thing(s) late or waiting on you: {', '.join(late[:3])}")
    return {"at": now.isoformat(timespec="seconds"), "verdict": verdict, "state": DOWN if bad else WARN if late else OK,
            "connectors": cs, "freshness": fr, "work": w, "needs": nd, "tools": {"total": len(tl.TOOLS), **kinds}}
