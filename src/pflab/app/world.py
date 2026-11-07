"""The World (S67 local): one read-only picture of everything the system runs, for the screen that answers "is everything running, and what is done?".

Nodes are the senses (what brings data in), the minds (the agents and the brain), the work (investigations, experiments, calculations, routines), the
memory (ledger, graph, learned) and the guards (sandbox, privacy, backup, the spend cap). Each has a state computed from the store, never typed:

    working   something is running in it now
    ok        done: its last run succeeded and nothing is due
    late      something is due and has not run
    down      its last run failed
    waiting   it waits for data, for a dependency, or for the investor
    idle      nothing to do (or not started yet); never shown as a problem

Every section is computed on its own: one that fails is named under `errors` and the rest still show. Nothing here writes to the store.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

SENSES = [("markets", "Market data", ["collect", "prices", "nav", "global", "backfill", "instruments", "bars_1m", "data_s79b"], "prices, NAVs, world markets"),
          ("filings", "Filings and news", ["filings", "kg"], "company filings, news, the graph's intake"),
          ("broker", "Kite", ["live", "tradecheck", "idle_cash", "kite_token"], "live prices for what the system holds; his own trades are ignored"),
          ("record", "The account", ["ledger", "deposits"], "the system's own account (statements and deposits stand aside)"),
          ("us", "US sleeve", ["us_fx"], "USDINR rates")]
ROUTINES = [("thinking", "Thinking rounds", ["hq", "conductor", "research", "analyst", "forecast", "comove", "scans", "twin", "paper", "paper_daily", "selfcheck", "companion", "review", "learner", "catch_up", "sentiment", "macro_attribution", "wave_scan", "bear_resolve", "implied_calibration", "forecast_loop", "seats_mode", "benchmark_attr", "situation"],
             "the brain, research, forecasts, the learner"),
            ("plans", "Plans and alerts", ["plans", "guards", "watches", "watches_close"], "ready plans, guards, price watches"),
            ("reports", "Reports", ["summary_morning", "summary_evening", "outbox", "voice", "outgoing"], "the morning and evening summaries")]
SAFETY = [("safety", "Safety routines", ["backup", "sandbox", "security"], "backups, the sandbox proof, the privacy check")]
GROUP_OF = {j: g for g, _l, js, _d in SENSES + ROUTINES + SAFETY for j in js}

TONE = {"working": 1, "down": 4, "late": 3, "waiting": 2, "ok": 0, "idle": 0}


def _benchmark_panel(con, now) -> dict:
    """S79b 18B: 'Result vs its own benchmark': the book and the blended benchmark since the start, the weights in force, last month's split. {'available': False} when off or not recorded."""
    from pflab.paper import benchmark
    s = benchmark.status(con, "IN", now.date())
    if s.get("off"):
        return {"available": False, "off": True}
    if not s.get("started"):
        return {"available": False}
    lm = s.get("latest_month")
    return {"available": True, "since": s["since"], "as_of": s["as_of"], "book": s["book"]["return"], "benchmark": s["benchmark"]["return"], "excess": s["excess"],
            "source": s["benchmark"]["source"], "weights": s["benchmark"]["weights_now"], "stale": s.get("stale_classes") or [],
            "month": None if not lm else {k: lm[k] for k in ("month", "book_return", "bench_return", "allocation", "selection", "timing", "costs", "tax", "residual", "partial")}}


def _sec(out: dict, errors: dict, name: str, fn, default):
    try:
        out[name] = fn()
    except Exception as e:                                   # a section that fails is named; the rest of the world still shows
        errors[name] = f"{type(e).__name__}: {str(e)[:120]}"
        out[name] = default


def _combine(states: List[str]) -> str:
    """A group is working if any part works, down if any failed, late if any is due, waiting if any waits, else ok (or idle when none has run)."""
    for s in ("working", "down", "late", "waiting"):
        if s in states:
            return s
    return "ok" if "ok" in states else "idle"


def jobs_view(rt, now: datetime) -> List[dict]:
    from pflab.service import jobs, tasks  # noqa: F401
    con = rt.cursor()
    ctx = jobs.Ctx(con, now, rt.pm_dir, rt.data_root, rt.repo, secrets=getattr(rt, "secrets", None))
    latest = {j: (s, a, b, d) for j, s, a, b, d in con.execute(
        "SELECT job, status, started_at, finished_at, detail FROM job_runs QUALIFY row_number() OVER "
        "(PARTITION BY job ORDER BY started_at DESC, run_id DESC) = 1").fetchall()}
    from pflab import activation
    paused = not rt.settings.get("scheduler", True)
    waiting_icon = activation.is_pending(rt.pm_dir)
    out = []
    for r in jobs.plan(ctx):
        s = r["schedule"]
        when = f"daily {s.hour:02d}:{s.minute:02d}" if hasattr(s, "hour") else f"every {getattr(s, 'minutes', '?')} min"
        lr = latest.get(r["job"])
        why = str(r["why"])
        waiting_on = None                                   # a run that skipped because it needs him or data (`"waiting": true`) is waiting, not done
        if lr and lr[0] == "skipped":
            try:
                d = json.loads(lr[3] or "{}")
                if isinstance(d, dict) and d.get("waiting"):
                    waiting_on = str(d.get("why") or d.get("skipped") or "waiting")[:140]
            except ValueError:
                pass
        if lr and lr[0] == "running":
            state = "working"
        elif waiting_icon:
            state = "waiting"
        elif waiting_on:
            state, why = "waiting", waiting_on
        elif lr and lr[0] == "failed" and (r["last_success"] is None or lr[1] > r["last_success"]):
            state = "down"
        elif r["due"]:
            state = "late" if not paused else "waiting"
        elif lr is None and r["last_success"] is None:
            state = "idle"
        elif why.startswith("disabled"):
            state = "idle"
        else:
            state = "ok"
        hq_round = getattr(rt, "hq_last_round", None)
        if r["job"] == "hq" and hq_round and not waiting_icon:
            # (2026-10-31) with the window open the HQ runs on its own thread every 30 s, never as this job: the job row stayed "due" forever
            at, failed = hq_round
            when, state = "every 30 s while the window is open", ("down" if failed else "waiting" if paused else "ok")
            why = (f"last round {at:%H:%M:%S}" + (f"; failed: {', '.join(failed)}" if failed else "") + ("; paused" if paused else ""))
            out.append({"job": "hq", "group": GROUP_OF.get("hq", "other"), "when": when, "state": state, "why": why, "last_success": f"{at:%Y-%m-%d %H:%M}",
                        "last": {"status": "failed" if failed else "ok", "at": f"{at:%Y-%m-%d %H:%M}", "seconds": None,
                                 "detail": ", ".join(failed) or None}, "done_today": at.date() == now.date() and not failed})
            continue
        out.append({"job": r["job"], "group": GROUP_OF.get(r["job"], "other"), "when": when, "state": state, "why": why[:140],
                    "last_success": str(r["last_success"])[:16] if r["last_success"] else None,
                    "last": lr and {"status": lr[0], "at": str(lr[1])[:16], "seconds": round((lr[2] - lr[1]).total_seconds(), 1) if lr[2] else None,
                                    "detail": None if lr[0] == "ok" else (lr[3] or "")[:160]},
                    "done_today": bool(r["last_success"] and r["last_success"].date() == now.date() and not waiting_on)})
    return out


def agents_view(rt, now: datetime) -> List[dict]:
    from pflab.hq import roster
    con = rt.cursor()
    since = now - timedelta(hours=24)
    run = {a: n for a, n in con.execute("SELECT to_agent, count(*) FROM hq_tasks WHERE status='running' GROUP BY 1").fetchall()}
    wait = {a: n for a, n in con.execute("SELECT to_agent, count(*) FROM hq_tasks WHERE status IN ('queued','waiting','retry','held') GROUP BY 1").fetchall()}
    done = {a: (n, str(t)[:16]) for a, n, t in con.execute(
        "SELECT to_agent, count(*), max(finished_at) FROM hq_tasks WHERE status='done' AND finished_at >= ? GROUP BY 1", [since]).fetchall()}
    fail = {a: (n, str(t)[:16]) for a, n, t in con.execute(
        "SELECT to_agent, count(*), max(finished_at) FROM hq_tasks WHERE status='failed' AND finished_at >= ? GROUP BY 1", [since]).fetchall()}
    cur = {a: t for a, t in con.execute("SELECT to_agent, arg_max(text, task_id) FROM hq_tasks WHERE status='running' GROUP BY 1").fetchall()}
    out = []
    for r in roster.roles(getattr(rt, "settings", None)):            # one node per role; its members' tasks added up
        ms = r["members"]
        nrun, nwait = sum(run.get(m, 0) for m in ms), sum(wait.get(m, 0) for m in ms)
        ndone, nfail = sum(done.get(m, (0, None))[0] for m in ms), sum(fail.get(m, (0, None))[0] for m in ms)
        last = max([done[m][1] for m in ms if m in done] or [None], key=lambda x: x or "")
        doing = next((cur[m] for m in ms if cur.get(m)), "")
        state = "working" if nrun else "down" if nfail and not ndone else "waiting" if nwait else "ok" if ndone else "idle"
        out.append({"id": r["id"], "label": r["title"], "does": r["does"], "state": state, "running": nrun, "waiting": nwait,
                    "done_24h": ndone, "last_done": last, "failed_24h": nfail, "doing": (doing or "")[:140],
                    "order_to": r["order_to"], "made_of": r["made_of"]})
    return out


def brain_view(rt, now: datetime) -> dict:
    con = rt.cursor()
    p = con.execute("SELECT pass_id, passed_at, status, trigger, role, cost_inr, error FROM hq_passes WHERE role='brain' ORDER BY pass_id DESC LIMIT 1").fetchone()
    recent_calls = con.execute("SELECT count(*), max(tool) FROM hq_tool_calls WHERE called_at >= ?", [now - timedelta(minutes=3)]).fetchone()
    passes_today = con.execute("SELECT count(*) FROM hq_passes WHERE role='brain' AND passed_at >= ?", [datetime(now.year, now.month, now.day)]).fetchone()[0]
    thinking = bool(recent_calls[0])
    return {"state": "working" if thinking else "ok" if p and str(p[2]) not in ("error", "failed") else "down" if p else "idle",
            "mode": rt.settings.get("brain", "economy"), "passes_today": int(passes_today),
            "last": p and {"id": p[0], "at": str(p[1])[:16], "status": p[2], "trigger": p[3], "cost_inr": round(float(p[5] or 0), 2), "error": (p[6] or "")[:120]},
            "using_tool": recent_calls[1] if thinking else None}


def work_view(rt, now: datetime) -> List[dict]:
    con = rt.cursor()
    out = []
    cs = dict(con.execute("SELECT status, count(*) FROM hq_cases GROUP BY 1").fetchall())
    open_n = sum(v for k, v in cs.items() if k not in ("done", "failed"))
    wait_n = cs.get("waiting_data", 0) + cs.get("awaiting_approval", 0)
    out.append({"id": "cases", "zone": "work", "label": "Investigations", "sub": f"{open_n} open · {cs.get('done', 0)} decided",
                "state": "working" if cs.get("running") else "down" if cs.get("failed") and not open_n else "waiting" if wait_n else "ok" if cs else "idle",
                "detail": {"by_status": cs}})
    es = dict(con.execute("SELECT status, count(*) FROM learn_experiments GROUP BY 1").fetchall())
    from pflab.learner import counter
    out.append({"id": "experiments", "zone": "work", "label": "Experiments", "sub": f"{sum(es.values())} registered · {counter.n_tests(con)} variants searched",
                "state": "working" if es.get("running") else "waiting" if es.get("waiting") else "late" if es.get("registered") else "ok" if es else "idle",
                "detail": {"by_status": es}})
    ks = dict(con.execute("SELECT status, count(*) FROM hq_calcs GROUP BY 1").fetchall())
    out.append({"id": "calcs", "zone": "work", "label": "Calculations", "sub": f"{sum(ks.values())} kept · {ks.get('checked', 0)} checked",
                "state": "ok" if ks else "idle", "detail": {"by_status": ks}})
    ts = dict(con.execute("SELECT status, count(*) FROM hq_tasks GROUP BY 1").fetchall())
    live = {k: v for k, v in ts.items() if k in ("queued", "running", "waiting", "retry", "held")}
    out.append({"id": "board", "zone": "work", "label": "The board", "sub": ", ".join(f"{v} {k}" for k, v in live.items()) or "empty",
                "state": "working" if ts.get("running") else "waiting" if live else "ok" if ts else "idle", "detail": {"by_status": ts}})
    return out


def memory_view(rt, now: datetime) -> List[dict]:
    con = rt.cursor()
    n = lambda sql: int(con.execute(sql).fetchone()[0])      # noqa: E731
    ev, ac, docs, learned, mem = n("SELECT count(*) FROM events"), n("SELECT count(*) FROM accounts"), n("SELECT count(*) FROM kg_docs"), \
        n("SELECT count(*) FROM learned WHERE valid_to IS NULL"), n("SELECT count(*) FROM memory WHERE valid_to IS NULL")
    return [{"id": "ledger", "zone": "memory", "label": "Ledger", "sub": f"{ac} accounts · {ev:,} events", "state": "ok" if ev else "idle"},
            {"id": "graph", "zone": "memory", "label": "Knowledge graph", "sub": f"{docs:,} documents", "state": "ok" if docs else "idle"},
            {"id": "learned", "zone": "memory", "label": "Learned", "sub": f"{learned} in force · {mem} notes", "state": "ok" if learned or mem else "idle"}]


def guards_view(rt, now: datetime, pic: dict) -> List[dict]:
    from pflab.agents import sandbox as sb
    from pflab.hq import governor as gv
    con = rt.cursor()
    out = []
    sx = sb.status()
    probe = con.execute("SELECT ok, checked_at FROM health_checks WHERE connector='sandbox' ORDER BY check_id DESC LIMIT 1").fetchone()
    out.append({"id": "sandbox", "zone": "guards", "label": "Sandbox", "sub": "Docker ready" if sx["ok"] else sx["why"][:60],
                "state": "down" if probe and not probe[0] else "ok" if sx["ok"] else "waiting",
                "detail": {"proof": probe and {"ok": bool(probe[0]), "at": str(probe[1])[:16]}}})
    sp = gv.spend(con, now)
    pct = sp["month"] / sp["cap"] if sp["cap"] else 0
    out.append({"id": "spend", "zone": "guards", "label": "Spend", "sub": (f"Rs {sp['month']:,.0f} of Rs {sp['cap']:,.0f} this month" if sp["cap"] else "no monthly cap set: nothing is sent"),
                "state": "down" if pct >= 1 else "late" if pct >= 0.85 else "ok", "detail": {"month": sp["month"], "cap": sp["cap"], "pct": round(pct * 100, 1)}})
    cov = (pic.get("coverage") or {}).get("status") or {}
    out.append({"id": "coverage", "zone": "guards", "label": "Picture of you", "sub": cov.get("label", "nothing read yet"),
                "state": "ok" if cov.get("label") == "complete" else "waiting" if cov.get("label") in ("partial", "discovery in progress") else "idle",
                "detail": {"reasons": cov.get("reasons", [])}})
    from pflab import activation
    out.append({"id": "activation", "zone": "guards", "label": "First launch", "sub": "waiting for the icon" if activation.is_pending(rt.pm_dir) else "active",
                "state": "waiting" if activation.is_pending(rt.pm_dir) else "ok"})
    return out


def looking_into(rt, now: datetime) -> dict:
    """What the system is working on right now, in words: open investigations (with where their evidence stands), experiments, and who is blocked."""
    from pflab.hq import cases
    from pflab.learner import experiments as ex
    con = rt.cursor()
    inv = [{"id": c["id"], "question": c["question"], "status": c["status"], "evidence": {k: c["assessment"][k] for k in ("for", "against", "missing", "stale")},
            "waiting_for": [d["request"] for d in c["dependencies"] if d["status"] == "open"][:2], "since": str(c["opened"])[:16] if c.get("opened") else ""}
           for c in cases.listing(con, 6, active_only=True)]
    exps = [e for e in ex.report(con) if e["status"] in ("registered", "running", "waiting", "kept", "rejected", "deferred")][-5:]
    return {"investigations": inv, "experiments": exps}


def feed(rt, now: datetime, limit: int = 40) -> List[dict]:
    con = rt.cursor()
    ev = []
    for job, st, at, fin, det in con.execute("SELECT job, status, started_at, finished_at, detail FROM job_runs ORDER BY started_at DESC LIMIT 14").fetchall():
        ev.append((fin or at, "routine", job.replace("_", " "), {"ok": "finished", "running": "started", "failed": "failed", "skipped": "skipped"}.get(st, st)
                   + ("" if st in ("ok", "running") else f": {(det or '')[:80]}"), "down" if st == "failed" else "working" if st == "running" else "ok"))
    from pflab.hq import roster
    role_title = {r["id"]: r["title"] for r in roster.ROLES}                     # the feed names the role the map shows
    for tid, to, st, created, fin, text in con.execute("SELECT task_id, to_agent, status, created_at, finished_at, text FROM hq_tasks ORDER BY coalesce(finished_at, created_at) DESC LIMIT 14").fetchall():
        ev.append((fin or created, "agent", role_title.get(roster.role_of(to), to), f"{st}: {text[:90]}", "down" if st == "failed" else "working" if st == "running" else "waiting" if st in ("queued", "waiting", "held", "retry") else "ok"))
    for cid, at, e, det in con.execute("SELECT case_id, logged_at, event, detail FROM hq_case_log ORDER BY log_id DESC LIMIT 10").fetchall():
        ev.append((at, "investigation", f"case #{cid}", f"{e}: {(det or '')[:90]}", "waiting" if e in ("waiting_data", "retry") else "ok"))
    for aid, eid, at, kind, st in con.execute("SELECT attempt_id, exp_id, made_at, kind, status FROM learn_attempts WHERE kind <> 'baseline' ORDER BY attempt_id DESC LIMIT 6").fetchall():
        ev.append((at, "experiment", f"experiment #{eid}", f"{kind} {st}", "down" if st == "crash" else "ok"))
    for tool, at, st in con.execute("SELECT tool, called_at, status FROM hq_tool_calls ORDER BY call_no DESC LIMIT 8").fetchall():
        ev.append((at, "brain", "brain", f"used {tool} ({st})", "down" if st == "error" else "working"))
    ev.sort(key=lambda e: str(e[0]), reverse=True)
    return [{"at": str(a)[:19], "kind": k, "who": w, "text": t, "tone": tone} for a, k, w, t, tone in ev[:limit]]


def checks(pic: dict, jobs: List[dict], agents: List[dict], work: List[dict], now: datetime) -> List[dict]:
    """The checklist: everything that should be true when the system is running well, each as running / done / waiting / not done."""
    rows: List[dict] = []

    def add(group, name, state, detail, done=None):
        rows.append({"group": group, "name": name, "state": state, "detail": detail[:160], "done": done})
    for c in pic.get("connectors", []):
        add("Connections", c["name"], {"ok": "ok", "warn": "late", "down": "down"}.get(c["state"], "idle"), c["line"])
    for f in pic.get("freshness", []):
        add("Data", f["name"], {"ok": "ok", "warn": "late", "down": "down"}.get(f["state"], "idle"), f["line"] or f"latest {f.get('latest')}", f["state"] == "ok")
    for j in sorted(jobs, key=lambda x: x["job"]):
        if j["state"] == "idle" and (j["why"].startswith("disabled") or not j["last"]):
            continue
        add("Today's rounds", j["job"].replace("_", " "), j["state"], f"{j['when']} · " + (j["why"] if j["state"] != "down" else (j["last"] or {}).get("detail") or j["why"]), j["done_today"])
    for a in agents:
        if a["state"] in ("working", "down", "waiting"):
            add("Agents", a["label"], a["state"], a["doing"] or (f"{a['waiting']} waiting" if a["waiting"] else f"{a['failed_24h']} failed in a day"))
    for w in work:
        add("Work", w["label"], w["state"], w["sub"])
    n = pic.get("needs") or {}
    add("You", "Needs from you", "waiting" if n.get("total") else "ok", f"{n.get('total', 0)} open" if n.get("total") else "nothing is waiting on you", not n.get("total"))
    return rows


def build(rt, now: Optional[datetime] = None) -> dict:
    now = now or rt.clock()
    errors: Dict[str, str] = {}
    out: dict = {"at": now.isoformat(timespec="seconds")}
    pic: dict = {}
    try:
        from pflab.app import system
        pic.update(system.picture(rt, now))
    except Exception as e:
        errors["system"] = f"{type(e).__name__}: {str(e)[:120]}"
    jb: List[dict] = []
    _sec(out, errors, "jobs", lambda: jb.extend(jobs_view(rt, now)) or jb, [])
    ag: List[dict] = []
    _sec(out, errors, "agents", lambda: ag.extend(agents_view(rt, now)) or ag, [])
    _sec(out, errors, "brain", lambda: brain_view(rt, now), {"state": "idle"})
    wk: List[dict] = []
    _sec(out, errors, "work_nodes", lambda: wk.extend(work_view(rt, now)) or wk, [])
    _sec(out, errors, "memory_nodes", lambda: memory_view(rt, now), [])
    _sec(out, errors, "guard_nodes", lambda: guards_view(rt, now, pic), [])
    _sec(out, errors, "feed", lambda: feed(rt, now), [])
    _sec(out, errors, "looking_into", lambda: looking_into(rt, now), {"investigations": [], "experiments": []})
    from pflab.agenda import runner as agenda_runner                                         # S79: what it is doing when nothing is urgent
    _sec(out, errors, "agenda", lambda: agenda_runner.snapshot(rt.cursor(), now), {"available": False})
    from pflab.llm import cost as llm_cost                                                   # S79b item 17: cost per useful act, by seat (local seconds, cloud rupees)
    _sec(out, errors, "seat_cost", lambda: llm_cost.world_panel(rt.cursor(), now), {"available": False})
    _sec(out, errors, "benchmark_panel", lambda: _benchmark_panel(rt.cursor(), now), {"available": False})        # S79b 18B: the result against its own benchmark
    from pflab.situation import report as sit_report                                         # S79b item 16: the situation report is shown first
    _sec(out, errors, "situation", lambda: sit_report.world_view(rt.cursor()), {"available": False})
    from pflab.app import onboarding
    _sec(out, errors, "bring", lambda: onboarding.bring_list(rt.cursor()), [])               # what he can bring, with what is already held

    def group_nodes(spec, zone):
        res = []
        for gid, label, names, sub in spec:
            mine = [j for j in jb if j["job"] in names]
            if not mine:
                continue
            st = _combine([j["state"] for j in mine])
            done = sum(1 for j in mine if j["done_today"])
            res.append({"id": gid, "zone": zone, "label": label, "sub": sub, "state": st, "jobs": mine, "done_today": done, "of": len(mine)})
        return res
    out["senses"] = group_nodes(SENSES, "senses")
    out["routines"] = group_nodes(ROUTINES, "work")
    out["safety"] = group_nodes(SAFETY, "guards")
    out["checks"] = checks(pic, jb, ag, wk, now)
    paused = not rt.settings.get("scheduler", True)
    states = [n["state"] for n in out["senses"] + out["routines"] + out["safety"] + ag + wk + out["guard_nodes"]]
    from pflab import activation
    done_today = sum(1 for j in jb if j["done_today"]) + sum(a["done_24h"] for a in ag)
    out["counts"] = {"working": states.count("working"), "waiting": states.count("waiting"), "late": states.count("late"), "down": states.count("down"),
                     "ok": states.count("ok"), "done_today": done_today, "agents": len(ag), "jobs": len(jb)}
    c = out["counts"]
    if activation.is_pending(rt.pm_dir):
        verdict, tone = "Waiting for its first launch from the desktop icon. Nothing runs until then.", "waiting"
    elif paused:
        verdict, tone = "Paused by you. Nothing starts by itself until you resume.", "waiting"
    elif c["down"]:
        verdict, tone = f"{c['down']} thing(s) failed and need a look.", "down"
    elif c["working"]:
        verdict, tone = f"Running itself: {c['working']} thing(s) working right now.", "working"
    elif c["late"]:
        verdict, tone = f"Running, {c['late']} thing(s) are due and will start by themselves.", "late"
    elif c["waiting"]:
        verdict, tone = f"All running; {c['waiting']} thing(s) wait for data or for you.", "waiting"
    else:
        verdict, tone = "Everything is running and everything due is done.", "ok"
    out["pulse"] = {"verdict": verdict, "tone": tone, "paused": paused, "system_verdict": pic.get("verdict"), "catching_up": pic.get("catching_up")}
    try:                                                    # S79: the clock's mode per market and the catch-up, so "analysis in progress" is visible within minutes of opening
        from pflab import markets
        from pflab.service import away, catchup, presence
        con0 = rt.cursor()
        ms = markets.modes(now)
        segs = con0.execute("SELECT opened_at, off_from, off_to FROM app_presence_s79 ORDER BY seg_id DESC LIMIT 1").fetchone()
        out["pulse"]["modes"] = {"modes": ms, "working_by": list(markets.primary(now))}
        out["pulse"]["catch_up"] = {**catchup.status(con0), "opened_at": str(segs[0])[:16] if segs else None,
                                    "off": presence.describe(segs[1], segs[2]) if segs and segs[1] else None, "digest": away.latest(con0)}
    except Exception as e:
        errors["modes"] = f"{type(e).__name__}: {str(e)[:120]}"
    out["needs"] = (pic.get("needs") or {}).get("items", [])[:6]
    out["errors"] = errors
    return json.loads(json.dumps(out, default=str))
