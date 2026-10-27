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
        for name in ("app.js", "app.css"):
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

    @app.get("/api/scenarios")
    def scenarios_api():
        from pflab.risk import scenarios as sn
        return json.loads(json.dumps(sn.run_all(rt.cursor(), rt.data_root, rt.clock().date()), default=str))

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
