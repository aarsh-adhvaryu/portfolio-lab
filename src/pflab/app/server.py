"""The dashboard's web server: the screens (static files) and their data, on 127.0.0.1 only (S54)."""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from pflab.app import views

STATIC = Path(__file__).resolve().parent / "static"


MAX_UPLOAD = 50 * 2**20


def _quiet(fn, rt, iid) -> None:
    """A slow inbox step on its own thread; a failure is written on the item, never lost."""
    from pflab.app import inbox as ib
    try:
        fn(rt, iid)
    except Exception as e:
        ib.fail(rt, iid, e)


def _month_end(s: str):
    """'2025-06' -> 2025-06-30 (the graph's growth slider); '' -> None (today)."""
    import calendar
    from datetime import date
    if not s:
        return None
    try:
        y, m = int(s[:4]), int(s[5:7])
        return date(y, m, calendar.monthrange(y, m)[1])
    except (ValueError, IndexError):
        raise HTTPException(400, "upto must be YYYY-MM")


def create_app(rt) -> FastAPI:
    app = FastAPI(title="Portfolio Lab", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.rt = rt
    app.state.shutdown_requested = threading.Event()
    app.state.restart_requested = threading.Event()
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.get("/")
    def index():
        """The page asks for its script and styles with their modification time, so the window never runs a cached
        old copy after an update (2026-10-24: the browser kept the old app.js)."""
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for name in ("app.js", "app.css", "ui.js", "world.js", "world.css"):
            html = html.replace(f"/static/{name}\"", f"/static/{name}?v={int((STATIC / name).stat().st_mtime)}\"")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health():
        return {"ok": True, "versions": rt.versions(), "busy": rt.busy, "clients": rt.clients}

    @app.get("/api/command")
    def command():
        return json.loads(json.dumps(views.command(rt), default=str))

    @app.get("/api/portfolio")
    def portfolio(isin: str = ""):
        return json.loads(json.dumps(views.portfolio(rt, isin or None), default=str))

    @app.get("/api/schedule")
    def schedule():
        return json.loads(json.dumps(views.schedule(rt), default=str))

    @app.post("/api/seen")
    def seen():
        """A click or a keypress in the window (S58b): an update waits while the investor is using the screen."""
        rt.last_seen = rt.clock()
        return {"ok": True}

    @app.post("/api/restart")
    def restart():
        """Restart onto the new code (the window closes and a new one opens)."""
        app.state.restart_requested.set()
        app.state.shutdown_requested.set()
        return {"restarting": True}

    @app.post("/api/jobs/{name}/run")
    def run_job_now(name: str):
        try:
            return {"queued": rt.request_run(name)}
        except KeyError:
            raise HTTPException(404, f"no job {name}")
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/checklists")
    def start_checklist(template: str = Body(...), subject: str = Body("")):
        from pflab.app import checklists as cl
        try:
            name = cl.start(rt.cursor(), template, subject, rt.clock())
        except ValueError as e:
            raise HTTPException(400, str(e))
        rt.bump("notes")
        return {"name": name}

    @app.post("/api/checklists/close")
    def close_checklist(name: str = Body(..., embed=True)):
        from pflab.app import checklists as cl
        cl.close(rt.cursor(), name)
        rt.bump("notes")
        return {"ok": True}

    @app.get("/api/graph")
    def graph_view(kinds: str = "", upto: str = ""):
        from pflab.app import graph
        return json.loads(json.dumps(graph.view(rt.cursor(), _month_end(upto), [k for k in kinds.split(",") if k]
                                                or graph.DEFAULT_KINDS), default=str))

    @app.get("/api/graph/node")
    def graph_node(id: str, upto: str = ""):
        from pflab.app import graph
        return json.loads(json.dumps(graph.node(rt.cursor(), id, _month_end(upto)), default=str))

    @app.get("/api/sims")
    def sims_get():
        return views.sims_view(rt)

    @app.post("/api/sims/run")
    def sims_run(paths: int = Body(10_000), years: int = Body(5), custom: dict = Body(None)):
        from pflab.app import sims
        if paths not in sims.PATHS or not 1 <= years <= 5:
            raise HTTPException(400, f"paths one of {sims.PATHS}, years 1 to 5")
        if rt.sims_running:
            raise HTTPException(409, "a simulation is already running")
        if custom:
            try:
                sims.clean_mix(custom)
            except (ValueError, TypeError) as e:
                raise HTTPException(400, str(e))

        def go():
            try:
                sims.run(rt, paths=paths, years=years, custom=custom)
            except Exception as e:                       # shown on the screen, never lost
                rt.sims_error = f"{type(e).__name__}: {str(e)[:300]}"
                rt.bump("sims")
        rt.sims_error = None
        threading.Thread(target=go, name="sims", daemon=True).start()
        return {"started": True}

    @app.post("/api/notes")
    def add_note(text: str = Body(..., embed=True)):
        from pflab.pm.store import next_id
        t = text.strip()[:500]
        if not t:
            raise HTTPException(400, "empty note")
        con = rt.cursor()
        nid = next_id(con, "app_notes", "note_id")
        con.execute("INSERT INTO app_notes (note_id, text, created_at) VALUES (?,?,?)", [nid, t, rt.clock()])
        rt.bump("notes", "command")
        return {"id": nid}

    @app.post("/api/notes/{nid}/toggle")
    def toggle_note(nid: int):
        con = rt.cursor()
        con.execute("UPDATE app_notes SET done = NOT done, done_at = CASE WHEN done THEN NULL ELSE ? END WHERE note_id=?",
                    [rt.clock(), nid])
        rt.bump("notes", "command")
        return {"ok": True}

    @app.delete("/api/notes/{nid}")
    def delete_note(nid: int):
        rt.cursor().execute("UPDATE app_notes SET deleted = true WHERE note_id=?", [nid])
        rt.bump("notes", "command")
        return {"ok": True}

    # --- AI centre (S54b) ---------------------------------------------------------------------------------------------
    @app.get("/api/ai")
    def ai(chat: int = 0):
        return json.loads(json.dumps(views.ai(rt, chat or None), default=str))

    @app.post("/api/chats")
    def new_chat():
        from pflab.app import chat as ch
        cid = ch.create(rt.cursor(), rt.clock())
        rt.bump("chat")
        return {"id": cid}

    @app.delete("/api/chats/{cid}")
    def delete_chat(cid: int):
        from pflab.app import chat as ch
        ch.delete(rt.cursor(), cid)
        rt.bump("chat")
        return {"ok": True}

    @app.post("/api/chats/{cid}/messages")
    def send(cid: int, text: str = Body(...), mode: str = Body("auto"), approved: bool = Body(False)):
        from pflab.app import chat as ch
        try:
            return ch.post(rt, cid, text, mode, approved)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/doc")
    def doc(id: str):
        r = rt.cursor().execute("SELECT kind, title, source, published_at, attrs_json, url, text_path FROM kg_docs "
                                "WHERE doc_id=?", [id]).fetchone()
        if not r:
            raise HTTPException(404, "no such document")
        attrs = json.loads(r[4] or "{}")
        text = attrs.get("answer") or attrs.get("text") or ""
        if not text and r[6] and Path(r[6]).exists():                  # an article's text, kept on this PC (S38)
            text = Path(r[6]).read_text(encoding="utf-8", errors="replace")[:20000]
        return {"kind": r[0], "title": r[1], "source": r[2], "published": str(r[3])[:16], "text": text or (r[5] or ""),
                "documents": attrs.get("documents", [])}

    @app.post("/api/questions/{qid}/answer")
    def answer_question(qid: int, text: str = Body(..., embed=True)):
        from pflab.agents import questions as qs
        if not text.strip():
            raise HTTPException(400, "empty answer")
        qs.answer(rt.cursor(), qid, text.strip(), rt.clock())
        rt.bump("notifications", "command", "chat")
        return {"ok": True}

    # --- watch list, research and plans (S54c) ----------------------------------------------------------------------
    @app.get("/api/watch")
    def watch():
        return json.loads(json.dumps(views.watch(rt), default=str))

    @app.post("/api/watch/refresh")
    def watch_refresh():
        from pflab.app import research as rs
        threading.Thread(target=rs.compute_watch, args=(rt,), name="watch-now", daemon=True).start()
        return {"started": True}

    @app.post("/api/watch/add")
    def watch_add(symbol: str = Body(..., embed=True)):
        """The investor adds a name (his decision): guards and the graph now, the zone with the next refresh."""
        from pflab.app import research as rs
        from pflab.plan import stock_list as slm
        r = slm.add(rt.cursor(), symbol.strip().upper())
        if not r.get("added"):
            raise HTTPException(400, r.get("why", "not added"))
        threading.Thread(target=rs.compute_watch, args=(rt,), name="watch-add", daemon=True).start()
        rt.bump("watch")
        return {"symbol": r["symbol"], "guard": r["guard"], "reasons": r["reasons"]}

    @app.post("/api/watch/remove")
    def watch_remove(symbol: str = Body(..., embed=True)):
        from pflab.app import research as rs
        from pflab.plan import stock_list as slm
        ok = slm.remove(symbol.strip().upper())
        threading.Thread(target=rs.compute_watch, args=(rt,), name="watch-remove", daemon=True).start()
        return {"removed": bool(ok)}

    @app.post("/api/watches")
    def add_watch(isin: str = Body(...), symbol: str = Body(""), kind: str = Body(...), level: float = Body(...),
                  note: str = Body("")):
        from pflab.app import research as rs
        try:
            wid = rs.add_watch(rt.cursor(), isin, symbol, kind, level, note, rt.clock())
        except ValueError as e:
            raise HTTPException(400, str(e))
        rt.bump("watch")
        return {"id": wid}

    @app.delete("/api/watches/{wid}")
    def delete_watch(wid: int):
        rt.cursor().execute("UPDATE watches SET active = false WHERE watch_id=?", [wid])
        rt.bump("watch")
        return {"ok": True}

    @app.get("/api/research")
    def research(isin: str = ""):
        return json.loads(json.dumps(views.research(rt, isin or None), default=str))

    @app.get("/api/system")
    def system_api():
        """S66: the system as one picture: connectors, data freshness, work in progress, what needs you (app/system.py)."""
        from pflab.app import system
        return json.loads(json.dumps(system.picture(rt), default=str))

    @app.get("/api/policy")
    def policy_api():
        """S68: every limit that can refuse a paid call, with its value, where it is set, why, and whether an edit holds at once; the
        acceptance window's spend against its cap while it is open."""
        from pflab.hq import governor
        return json.loads(json.dumps(governor.policy_view(rt.cursor(), rt.clock(), rt.settings.get("brain", "economy")), default=str))

    @app.get("/api/world")
    def world_api():
        """The World screen: every sense, agent, routine, piece of work, guard and check, with its state and what happened last (app/world.py)."""
        from pflab.app import world
        return world.build(rt, rt.clock())

    @app.post("/api/world/pause")
    def world_pause(paused: bool = Body(..., embed=True)):
        """Pause or resume the system's own routines (the scheduler setting). Work already running finishes; nothing new starts while paused."""
        rt.set_settings({"scheduler": not paused})
        return {"paused": paused}

    @app.get("/api/coverage")
    def coverage_api():
        """Every account found, its months, the open gaps, each mailbox's reach, and whether the picture may be called complete."""
        from pflab.app import system
        return json.loads(json.dumps(system._coverage(rt.cursor(), rt.clock()), default=str))

    @app.post("/api/coverage/confirm")
    def coverage_confirm():
        """He presses: this is every account, mailbox and export. Only this call confirms; nothing the system does by itself can."""
        from pflab.ingest import coverage
        coverage.confirm_inventory(rt.cursor(), rt.clock())
        rt.bump("health")
        return {"ok": True, "status": coverage.status(rt.cursor(), rt.clock())}

    @app.post("/api/coverage/leave_out")
    def coverage_leave_out(key: str = Body(None), text: str = Body(None)):
        """His choice: leave an account out for now (a found one by its key, or one he names that no file shows). A file or Add back brings it in later."""
        from pflab.ingest import coverage
        con = rt.cursor()
        if key:
            coverage.leave_out(con, key)
        elif text:
            coverage.declare_left_out(con, text, rt.clock())
        else:
            raise HTTPException(400, "name the account")
        rt.bump("health")
        return {"ok": True}

    @app.post("/api/coverage/add_back")
    def coverage_add_back(key: str = Body(..., embed=True)):
        from pflab.ingest import coverage
        coverage.add_back(rt.cursor(), key)
        rt.bump("health")
        return {"ok": True}

    @app.post("/api/system/seen")
    def system_seen():
        """He has looked: what changed is counted from now (app/system.py `changed_since`)."""
        from pflab.app import system
        system.mark_visit(rt)
        return {"ok": True}

    @app.get("/api/cases/{cid}")
    def case_view(cid: int):
        """One investigation: evidence with its times, requests, calculations, why it changed (hq/cases.py); a mission's card with it (S68)."""
        from pflab.hq import missions, views as hv
        try:
            d = hv.case_detail(rt.cursor(), cid)
        except LookupError as e:
            raise HTTPException(404, str(e))
        return json.loads(json.dumps({**d, "mission": missions.card(rt.cursor(), cid)}, default=str))

    @app.post("/api/investigations")
    def investigate(goal: str = Body(..., embed=True)):
        """S68: one request becomes an investigation carried by a coordinator, research and quant workers and an independent reviewer. Returns the
        case and mission ids at once; the work runs on its own (the HQ round), survives a restart and reports in its card."""
        from pflab.hq import missions
        try:
            out = missions.create(rt.cursor(), rt.clock(), goal, pm_dir=rt.pm_dir)
        except ValueError as e:
            raise HTTPException(400, str(e))
        rt.bump("hq", "chat")
        rt.wake_hq()
        return out

    @app.get("/api/assistant")
    def assistant_history():
        """S68: the assistant's one persistent conversation (app/assistant.py)."""
        from pflab.agents import questions
        from pflab.app import assistant
        h = assistant.history(rt.cursor(), rt.clock())
        h["questions"] = [{"id": q, "agent": a, "text": t, "at": ""} for q, a, t in questions.open_questions(rt.cursor())][:30]
        return json.loads(json.dumps(h, default=str))

    @app.post("/api/assistant")
    def assistant_post(text: str = Body(..., embed=True), context: str = Body("", embed=True)):
        """A message to the assistant; the answer is worked out in the background and appears in the thread (its steps visible while it works)."""
        from pflab.app import assistant
        try:
            return assistant.post(rt, text, context)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/investigations/{cid}/retry")
    def investigation_retry(cid: int):
        """A blocked investigation: try its failed steps again (their checkpoints and what they already made are kept)."""
        from pflab.hq import missions
        out = missions.retry(rt.cursor(), rt.clock(), cid)
        rt.bump("hq")
        rt.wake_hq()
        return out

    @app.post("/api/investigations/{cid}/approve")
    def investigation_approve(cid: int, note: str = Body("", embed=True)):
        """His yes to the plan that waits (once): the workers start. It places no order and changes no target or limit."""
        from pflab.hq import plans, pool
        out = plans.approve(rt.cursor(), rt.clock(), cid, by="the investor (dashboard)", note=note)
        pool.wake()
        rt.bump("hq", "chat")
        rt.wake_hq()
        return out

    @app.post("/api/investigations/{cid}/decline")
    def investigation_decline(cid: int, note: str = Body("", embed=True)):
        from pflab.hq import plans
        out = plans.decline(rt.cursor(), rt.clock(), cid, by="the investor (dashboard)", note=note)
        rt.bump("hq", "chat")
        return out

    @app.post("/api/investigations/{cid}/amend")
    def investigation_amend(cid: int, instruction: str = Body(..., embed=True), scope_change: bool = Body(False, embed=True),
                            financial_policy: bool = Body(False, embed=True)):
        """A changed instruction: the next numbered version of the investigation; the workers replan what it changes. No release, no code."""
        from pflab.hq import plans, pool
        out = plans.amend(rt.cursor(), rt.clock(), cid, instruction, scope_change=scope_change, financial_policy=financial_policy, by="the investor (dashboard)")
        if not out.get("amended") and not out.get("duplicate"):
            raise HTTPException(400, out.get("why", "not amended"))
        pool.wake()
        rt.bump("hq", "chat")
        rt.wake_hq()
        return out

    @app.post("/api/investigations/{cid}/allow")
    def investigation_allow(cid: int, rupees: float = Body(..., embed=True)):
        """More money for one investigation whose own budget is spent: its parked work resumes. A global limit still holds."""
        from pflab.hq import missions, pool
        out = missions.allow_more(rt.cursor(), rt.clock(), cid, float(rupees), by="the investor (dashboard)")
        pool.wake()
        rt.bump("hq")
        rt.wake_hq()
        return out

    @app.get("/api/proposals")
    def proposals_list(status: str = "", case_id: int = 0):
        """The recommendations on record: buy, add, hold, reduce, sell, diversify, wait, each with its status, review and what is missing."""
        from pflab.hq import proposals
        con = rt.cursor()
        rows = proposals.listing(con, status or None, case_id or None, 60)
        for p in rows:
            p["stale"] = proposals.stale_reason(con, p, rt.pm_dir)
        return json.loads(json.dumps({"proposals": rows, "strategy_version": proposals.strategy_version(con)}, default=str))

    @app.post("/api/proposals/{pid}/{decision}")
    def proposal_decide(pid: int, decision: str, note: str = Body("", embed=True)):
        """discuss | accept | reject | withdraw. Accepting is his decision to act himself: nothing is ordered."""
        from pflab.hq import proposals
        con = rt.cursor()
        out = proposals.discuss(con, rt.clock(), pid, note, by="the investor (dashboard)") if decision == "discuss" \
            else proposals.decide(con, rt.clock(), pid, decision, by="the investor (dashboard)", note=note)
        rt.bump("hq")
        return out

    @app.get("/api/routing")
    def routing_log(limit: int = 20):
        """What the local model decided about new files (which investigation, what effect, how: its answer, a retry, the rule, or escalation)."""
        from pflab.hq import arrivals
        return {"decisions": arrivals.recent(rt.cursor(), limit)}

    @app.get("/api/investigations")
    def investigations(limit: int = 20):
        """S68: every mission's card (goal, owner, current action, outputs, blocker, last useful progress, next trigger)."""
        from pflab.hq import missions
        con = rt.cursor()
        ids = [r[0] for r in con.execute("SELECT case_id FROM hq_missions ORDER BY mission_id DESC LIMIT ?", [limit]).fetchall()]
        out = {"investigations": [missions.card(con, c) for c in ids]}
        try:
            from pflab.learner import counter, experiments as ex
            out["experiments"] = [{**e, "contract": ex.contract_of(con, e["id"]) if e.get("id") else None} for e in ex.report(con)[-12:]]
            out["tests_counted"] = counter.n_tests(con)
        except Exception:
            out["experiments"] = []
        out["calcs"] = [{"id": i, "case_id": c, "question": q, "status": st, "at": str(at)[:16], "trusted": str(w or "").startswith("trusted:")}
                        for i, c, q, st, at, w in con.execute("SELECT calc_id, case_id, question, status, created_at, workshop_id FROM hq_calcs ORDER BY calc_id DESC LIMIT 20").fetchall()]
        return json.loads(json.dumps(out, default=str))

    @app.post("/api/hq/tasks/{tid}/release")
    def hq_release(tid: int):
        """A task held at the hop limit runs once (its chain stays counted)."""
        from pflab.hq import board
        try:
            out = board.release(rt.cursor(), tid, rt.clock(), "the investor (dashboard)")
        except ValueError as e:
            raise HTTPException(400, str(e))
        rt.wake_hq()
        rt.bump("hq")
        return out

    @app.post("/api/hq/tasks/{tid}/dismiss")
    def hq_dismiss(tid: int, reason: str = Body("not wanted", embed=True)):
        from pflab.hq import board
        try:
            out = board.dismiss(rt.cursor(), tid, rt.clock(), "the investor (dashboard)", reason)
        except ValueError as e:
            raise HTTPException(400, str(e))
        rt.bump("hq")
        return out

    @app.get("/api/twin")
    def twin_api():
        """S65: the scoreboard (plan/twin.py): four books, the same money on the same days; values until 60 sessions."""
        from pflab.plan import twin
        return json.loads(json.dumps(twin.status(rt.cursor()), default=str))

    @app.get("/api/release")
    def release_api():
        """S65: which release this is (read only; updating needs the store free, so it is done from the Update shortcut)."""
        from pflab import release
        r = release.load() or {}
        a = r.get("app") or {}
        return {"is_app": bool(r), "channel": release.channel(), "tag": a.get("tag", ""), "previous_tag": a.get("previous_tag", ""),
                "installed_on": str(a.get("installed_on", ""))}

    @app.get("/api/features")
    def features_api():
        """S65: the beta features, with his switch and the channel's default."""
        from pflab import features
        return {"channel": features.channel(), "features": features.listing(rt.settings)}

    @app.get("/api/setup")
    def setup_api():
        """S65: the accounts he set up (names, bank, last four digits) and the documents still needed."""
        from pflab.ingest import setup_sources as su
        from pflab.ingest import sources as srcs
        p = rt.pm_dir / "sources.toml"
        if not p.exists():
            return {"exists": False, "needed": ["Set up your accounts first (Setup): the start date and the accounts."],
                    "proposal": su.infer(rt.cursor(), rt.clock().date())}
        src = srcs.load(p)
        return {"exists": True, "start": str(src.get("start")), "accounts": src.get("accounts") or {}, "needed": su.needed(src)}

    @app.post("/api/setup")
    def setup_write(answers: dict = Body(...)):
        """Write sources.toml from his answers (never replacing an existing file) and file the documents still needed."""
        from pflab.ingest import setup_sources as su
        from pflab.ingest import sources as srcs
        p = rt.pm_dir / "sources.toml"
        try:
            su.write(p, answers)
        except su.SetupError as e:
            raise HTTPException(400, str(e))
        merged = srcs.load(p)
        from pflab.app import inbox as ib
        waiting = ib.attach_waiting(rt)                      # S65: the files kept before Setup start their checks now
        asked = su.ask_needed(rt.cursor(), merged, rt.clock())
        ib.close_met_requests(rt)                            # what he dropped before Setup already answers its requests
        return {"needed": su.needed(merged), "asked": asked, "files": waiting}

    @app.get("/api/trace")
    def trace_view():
        """(2026-10-31) Every balance with the file and date it comes from, fact or estimate, and the open differences."""
        from pflab.pm import trace
        return json.loads(json.dumps({"rows": trace.build(rt.cursor(), rt.clock().date())}, default=str))

    @app.get("/api/fd")
    def fd_list():
        """S65: the deposits on file (last four digits, bank, amount, rate, maturity)."""
        from pflab.pm import fd as fdm
        return {"deposits": [{"id": f.fd_id, "bank": f.bank, "principal": f.principal, "rate_pct": round(f.rate * 100, 3), "maturity": str(f.maturity),
                              "status": f.status} for f in fdm.load(rt.cursor())]}

    @app.post("/api/fd")
    def fd_add(fields: dict = Body(...), write: bool = Body(False)):
        """A deposit from the Setup form: checked against the bank's maturity amount; written to his deposit file and the store only with write."""
        from pflab.pm import fd as fdm
        try:
            e = fdm.entry(fields.get("id"), fields.get("bank"), float(fields.get("principal") or 0), float(fields.get("rate_pct") or 0),
                          fields.get("start"), fields.get("maturity"), float(fields.get("maturity_amount") or 0), fields.get("instruction") or "",
                          fields.get("purpose") or "", float(fields["current_value"]) if fields.get("current_value") else None,
                          fields.get("value_on") or None)
        except (ValueError, TypeError) as err:
            raise HTTPException(400, str(err))
        if not write:
            return {"ok": True, "written": False}
        path = rt.pm_dir / "fd_holdings.toml"
        try:
            fdm.add_to_file(path, e)
        except fdm.FDError as err:
            raise HTTPException(400, str(err))
        from pflab.app import inbox as ib
        n = ib.deposits_now(rt).get("deposits")              # (2026-10-31) the whole register, so a summary's deposits are not wiped
        return {"ok": True, "written": True, "deposits": n}

    @app.post("/api/inbox/apply-all")
    def inbox_apply_all():
        """His one press: every checked document into the ledger in one rebuild, written only when every check passes."""
        from pflab.app import inbox as ib
        try:
            return json.loads(json.dumps(ib.apply_all(rt), default=str))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/ledger/ipo")
    def ledger_ipo(fields: dict = Body(...), write: bool = Body(False)):
        """An IPO allotment entered by hand: dry run first, written only on his press (write true) with every check passing."""
        from pflab.app import inbox as ib
        from pflab.ingest import sources as srcs
        try:
            e = srcs.ipo_entry(fields.get("ipo_id"), fields.get("funding_account"), fields.get("demat_account"), fields.get("isin"),
                               int(fields.get("qty") or 0), float(fields.get("price") or 0), fields.get("allot_date"),
                               fields.get("bank_date"), float(fields.get("bank_amount") or 0), fields.get("symbol") or "",
                               fields.get("applied") or None, int(fields["bid_qty"]) if fields.get("bid_qty") else None,
                               float(fields["bid_price"]) if fields.get("bid_price") else None, fields.get("assumed") or "")
            return json.loads(json.dumps(ib.add_entry(rt, "ipo", e, write), default=str))
        except (ValueError, TypeError) as err:
            raise HTTPException(400, str(err))

    @app.post("/api/ledger/opening-cost")
    def ledger_opening_cost(fields: dict = Body(...), write: bool = Body(False)):
        """The cost and date of a holding that has no history here (for example received from a relative), with its stated basis."""
        from pflab.app import inbox as ib
        from pflab.ingest import sources as srcs
        try:
            e = srcs.cost_entry(fields.get("account"), fields.get("isin"), float(fields.get("cost_per_unit") or 0), fields.get("acquired"),
                                fields.get("basis"))
            return json.loads(json.dumps(ib.add_entry(rt, "opening_cost", e, write), default=str))
        except (ValueError, TypeError) as err:
            raise HTTPException(400, str(err))

    @app.get("/api/secrets")
    def secrets_api():
        """S65: which secrets are set (names only; a value is never sent back) and the statement-password names asked for."""
        from pflab.ingest import sources as srcs
        from pflab.pm import secrets_setup as ss
        try:
            asked = ss.password_names(srcs.load(rt.pm_dir / "sources.toml"))
        except Exception:
            asked = []
        return {"status": ss.status(), "passwords_asked": asked, "fields": {s: [[k, what] for k, what, _ in fs] for s, fs in ss.FIELDS.items()}}

    @app.post("/api/secrets")
    def set_secret(section: str = Body(...), key: str = Body(...), value: str = Body(...)):
        """Write one secret (write-only; nothing is echoed or logged)."""
        from pflab.pm import secrets_setup as ss
        try:
            done = ss.set_values({(section, key): value})
        except ss.SetupError as e:
            raise HTTPException(400, str(e))
        opened = 0
        if section == "passwords":                          # S68: a file that was waiting for this password is read at once, no second drop
            try:
                from pflab.app import inbox as ib
                opened = ib.retry_blocked(rt)
            except Exception:
                pass
        return {"set": done, **({"files_opened": opened} if opened else {})}

    @app.get("/api/us")
    def us_api():
        from pflab import features
        from pflab.ledger import foreign as lf
        from pflab.tax import foreign as tf
        if not features.enabled("us_sleeve", rt.settings):
            return {"enabled": False, "note": "BETA: the US sleeve is off. Turn it on in Settings when you want it."}
        from pflab.risk import sleeve
        con, today = rt.cursor(), rt.clock().date()
        rem = lf.remitted_in_fy(con, today)
        try:
            plan = sleeve.plan_now(con, today)
        except Exception:
            plan = None
        return json.loads(json.dumps({"enabled": True, "sleeve_plan": plan,"positions": lf.positions(con, today), "lrs": {**rem, "room_usd": tf.lrs_room(rem["usd"])},
                                      "fx": lf.fx_on(con, today), "fx_label": lf.FX_LABEL}, default=str))

    @app.post("/api/us/trade")
    def us_trade(date: str = Body(...), symbol: str = Body(...), side: str = Body(...), qty: float = Body(...), price: float = Body(...),
                 charges: float = Body(0.0), cik: int = Body(0), etf: bool = Body(False)):
        from datetime import date as _d
        from pflab import features
        from pflab.ledger import foreign as lf
        if not features.enabled("us_sleeve", rt.settings):
            raise HTTPException(403, "the US sleeve is a beta feature and is off (Settings)")
        con = rt.cursor()
        key = lf.pseudo_isin(cik) if cik else f"US:{symbol.strip().upper()}"
        try:
            lf.register_instrument(con, symbol.strip().upper(), key, symbol.strip().upper(), etf=etf)
            tid = lf.add_trade(con, _d.fromisoformat(date), symbol, key, side, qty, price, charges, source="dashboard")
        except ValueError as e:
            raise HTTPException(400, str(e))
        rt.bump("portfolio")
        return {"id": tid, "isin": key}

    @app.post("/api/us/remit")
    def us_remit(date: str = Body(...), usd: float = Body(...), inr: float = Body(...), tcs: float = Body(None), bank: str = Body("")):
        from datetime import date as _d
        from pflab import features
        from pflab.ledger import foreign as lf
        from pflab.tax import foreign as tf
        if not features.enabled("us_sleeve", rt.settings):
            raise HTTPException(403, "the US sleeve is a beta feature and is off (Settings)")
        con = rt.cursor()
        d = _d.fromisoformat(date)
        t = tcs if tcs is not None else tf.tcs(lf.remitted_in_fy(con, d)["inr"], inr)["tcs_rs"]
        return {"id": lf.add_remittance(con, d, usd, inr, t, bank, source="dashboard"), "tcs_inr": t,
                "tcs_basis": "recorded" if tcs is not None else "estimate (configs/tax/foreign.toml)"}

    @app.get("/api/scans")
    def scans_api():
        from pflab.quant import scan
        cache = rt.pm_dir / "app" / "cache" / "scans.json"
        try:
            hits = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {"scans": {}}
        except ValueError:
            hits = {"scans": {}}
        return {"scans": scan.listing(rt.cursor()), "results": hits.get("scans", {}), "at": hits.get("at"),
                "help": scan.__doc__.split("Conditions (name:value):")[1].strip()}

    @app.post("/api/scans")
    def make_scan_api(name: str = Body(...), conditions: str = Body(...), universe: str = Body("list")):
        from pflab.quant import scan
        try:
            sid = scan.make_scan(rt.cursor(), name, conditions, universe, "investor", rt.clock())
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"id": sid}

    @app.post("/api/scans/{sid}/active")
    def scan_active(sid: int, active: bool = Body(..., embed=True)):
        rt.cursor().execute("UPDATE scans SET active=? WHERE scan_id=?", [active, sid])
        return {"ok": True}

    @app.get("/api/scenarios")
    def scenarios_api():
        from pflab.risk import scenarios as sn
        return json.loads(json.dumps(sn.run_all(rt.cursor(), rt.data_root, rt.clock().date()), default=str))

    @app.get("/api/business")
    def business_api(isin: str):
        from pflab.hq import business
        sym = (rt.cursor().execute("SELECT symbol FROM instruments WHERE isin=?", [isin]).fetchone() or [isin])[0]
        return json.loads(json.dumps(business.facts(rt.cursor(), rt.data_root, isin, sym, rt.clock().date(), rt.pm_dir), default=str))

    @app.get("/api/maths")
    def maths(isin: str):
        return json.loads(json.dumps(views.maths(rt, isin), default=str))

    @app.post("/api/plan")
    def replan(amount: float = Body(..., embed=True)):
        from pflab.app import research as rs
        if amount <= 0:
            raise HTTPException(400, "the amount must be positive")
        threading.Thread(target=rs.compute_plan, args=(rt, amount), name="plan-now", daemon=True).start()
        return {"started": True}

    @app.post("/api/idea")
    def idea(text: str = Body(..., embed=True)):
        from pflab.app import research as rs
        return rs.idea(rt, text)

    @app.get("/api/inbox")
    def inbox_view():
        return json.loads(json.dumps(views.inbox(rt), default=str))

    @app.post("/api/inbox/upload")
    async def inbox_upload(request: Request):
        from urllib.parse import unquote
        from pflab.app import inbox as ib
        data = await request.body()
        if not data:
            raise HTTPException(400, "empty file")
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, f"files up to {MAX_UPLOAD // 2**20} MB")
        h = request.headers
        try:
            return ib.receive(rt, unquote(h.get("x-filename", "file")), data, h.get("x-kind", ""),
                              h.get("x-account") or None, int(h["x-chat"]) if h.get("x-chat") else None)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/inbox/{iid}/{action}")
    def inbox_action(iid: int, action: str):
        from pflab.app import inbox as ib
        fn = {"apply": ib.apply, "read": ib.summarise, "research": ib.research}.get(action)
        if fn is None:
            raise HTTPException(404, "unknown action")
        try:
            if action == "research":
                return fn(rt, iid)
            ib.check(rt, iid, action)
        except ValueError as e:
            raise HTTPException(400, str(e))
        threading.Thread(target=_quiet, args=(fn, rt, iid), name=f"inbox-{action}-{iid}", daemon=True).start()
        return {"started": True}

    @app.delete("/api/inbox/{iid}")
    def inbox_remove(iid: int):
        from pflab.app import inbox as ib
        try:
            ib.remove(rt, iid)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/workshop/{calc_id}/promote")
    def promote_calc(calc_id: str):
        from pflab.agents import workshop as wk
        if not wk.re.fullmatch(r"[\w.-]+", calc_id):
            raise HTTPException(400, "bad id")
        try:
            wk.promote(rt.pm_dir, calc_id, "The investor (dashboard)", rt.clock())
        except (FileNotFoundError, ValueError) as e:
            raise HTTPException(400, str(e))
        rt.bump("chat")
        return {"ok": True}

    # --- the agent HQ (S59) --------------------------------------------------------------------------------------------
    @app.get("/api/hq")
    def hq_view():
        from pflab.hq import views as hv
        return hv.as_json(hv.hq(rt))

    @app.post("/api/hq/order")
    def hq_order(agent: str = Body("receptionist"), text: str = Body(...), approved: bool = Body(False)):
        """The investor orders any agent directly; the answer shows on the board (and wherever he asked from)."""
        from pflab.hq import board, roster
        if agent not in roster.ROSTER:
            raise HTTPException(400, f"no agent {agent}")
        if not text.strip() and agent not in ("watcher", "reader", "brain", "cleanup", "messenger", "portfolio", "sim"):
            raise HTTPException(400, "write what you want the agent to do")
        tid = board.post(rt.cursor(), agent, text.strip(), rt.clock(), body={"approved": approved} if approved else None)
        rt.wake_hq()
        rt.bump("hq")
        return {"id": tid}

    @app.post("/api/hq/passes/{pid}/mark")
    def hq_mark_pass(pid: int, mattered: bool = Body(..., embed=True)):
        """The investor marks a brain pass (the shadow protocol's usefulness measure); his latest mark stands."""
        from pflab.hq import brain
        brain.mark(rt.cursor(), pid, mattered, rt.clock())
        rt.bump("hq")
        return {"ok": True}

    @app.post("/api/hq/suggestions/{sid}/answer")
    def hq_answer_suggestion(sid: int, answer: str = Body(..., embed=True)):
        """S60: The investor's answer to a suggestion (taken / declined / none); every one is scored either way."""
        from pflab.hq import suggestions as sg
        try:
            sg.answer(rt.cursor(), sid, answer, rt.clock())
        except (ValueError, LookupError) as e:
            raise HTTPException(400, str(e))
        rt.bump("hq")
        return {"ok": True}

    @app.post("/api/hq/reminders/{rid}/cancel")
    def hq_cancel_reminder(rid: int):
        rt.cursor().execute("UPDATE hq_reminders SET cancelled = true WHERE rem_id=?", [rid])
        rt.bump("hq")
        return {"ok": True}

    @app.get("/api/settings")
    def get_settings():
        return rt.settings

    @app.post("/api/settings")
    def set_settings(changes: dict = Body(...)):
        return rt.set_settings(changes)

    @app.get("/api/models")
    def get_models():
        """S61: the slider, one model per job: the measured default, his choice, the basis."""
        from pflab.hq import models
        return models.listing(rt.settings)

    @app.post("/api/kite/login")
    def kite_login():
        try:
            return {"url": rt.kite_login()}
        except Exception as e:
            raise HTTPException(400, str(e)[:300])

    @app.post("/api/montecarlo/run")
    def mc_run():
        threading.Thread(target=rt.mc_once, name="mc-now", daemon=True).start()
        return {"started": True}

    @app.post("/api/shutdown")
    def shutdown():
        app.state.shutdown_requested.set()
        return {"ok": True}

    @app.get("/api/events")
    async def events(request: Request):
        """Server-sent events: the topics' versions whenever one changes; an open stream means a window is open."""
        async def stream():
            rt.client_open()
            last = None
            yield "retry: 1000\n\n"                       # S59: a dropped stream reconnects in 1 s (the browser's default is 3)
            try:
                while not rt.stop.is_set():
                    if await request.is_disconnected():
                        break
                    v = rt.versions()
                    if v != last:
                        last = v
                        yield f"data: {json.dumps(v)}\n\n"
                    else:
                        yield ": keep-alive\n\n"
                    await asyncio.sleep(1.0)
            finally:
                rt.client_closed()
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    return app
