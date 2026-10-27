"""Each screen's data, from the system's own tested functions (no new maths here). JSON-ready dicts.

Rupee figures are plain floats; the screen formats them (Indian grouping) and hides them in privacy mode.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from pflab.calc import smalln

TICKERS = [("NIFTY 50", "indices", "NIFTY50_PRICE"), ("BANK NIFTY", "indices", "SECTOR_BANK_PRICE"),
           ("NIFTY 500", "indices", "NIFTY500_TRI"), ("INDIA VIX", "indices", "INDIA_VIX"),
           ("USD / INR", "global", "USD_INR"), ("GOLD (USD)", "global", "GOLD"), ("S&P 500", "global", "US_SP500")]
LIVE_NAME = {"NIFTY 50": "NIFTY 50", "BANK NIFTY": "BANK NIFTY", "INDIA VIX": "INDIA VIX"}


def _f(x) -> Optional[float]:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _clean(s) -> Optional[str]:
    """Names from exchange files can carry control or replacement characters: shown as a space."""
    if not isinstance(s, str):
        return s
    return " ".join("".join(" " if (ord(c) < 32 or c in "�\x7f") else c for c in s).split())


def _last_two(root: Path, sub: str, name: str):
    p = root / sub / f"{name}.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p, columns=["date", "close"]).dropna().sort_values("date").tail(2)
    if d.empty:
        return None
    last = d.iloc[-1]
    prev = d.iloc[0] if len(d) == 2 else None
    return {"value": float(last["close"]), "date": str(last["date"])[:10],
            "change": (float(last["close"]) / float(prev["close"]) - 1) if prev is not None else None}


def tickers(root: Path, live: Dict[str, dict]) -> List[dict]:
    out = []
    for label, sub, name in TICKERS:
        t = _last_two(root, sub, name)
        if t is None:
            continue
        lv = live.get(LIVE_NAME.get(label, ""))
        if lv:                                         # live value against the last close
            base = t["value"]
            t = {"value": lv["value"], "date": "live", "change": lv["value"] / base - 1 if base else None}
        out.append({"name": label, **t})
    return out


def holdings(con, asof: date) -> dict:
    """Positions summed across accounts, with today's move against the previous close and a 20-session line."""
    from pflab.pm import today as nw
    n = nw.build(con, asof)
    pos = n["positions"]
    inst = {r[0]: (r[1], r[2]) for r in con.execute("SELECT isin, sector, name FROM instruments").fetchall()}
    rows = []
    if len(pos):
        g = pos.groupby("isin", as_index=False).agg(symbol=("symbol", "first"), bucket=("bucket", "first"),
                                                    qty=("qty", "sum"), cost=("cost", "sum"), value=("value", "sum"),
                                                    unrealised=("unrealised", "sum"), price=("price", "first"),
                                                    kind=("price_kind", "first"), price_date=("price_date", "first"),
                                                    stale=("stale", "max"))
        total = float(g["value"].dropna().sum()) or 1.0
        for r in g.itertuples():
            closes = [c for (c,) in con.execute("SELECT close FROM prices WHERE isin=? AND date<=? ORDER BY date DESC "
                                                "LIMIT 21", [r.isin, asof]).fetchall()][::-1]
            price = _f(r.price)
            if r.kind == "live":
                prev = closes[-1] if closes else None
            else:
                prev = closes[-2] if len(closes) >= 2 else None
            chg = (price / prev - 1) if price and prev else None
            sec, name = inst.get(r.isin, (None, None))
            rows.append({"isin": r.isin, "symbol": _clean(r.symbol), "name": _clean(name), "sector": sec, "bucket": r.bucket,
                         "qty": _f(r.qty), "price": price, "price_kind": r.kind, "price_date": str(r.price_date)[:10],
                         "stale": bool(r.stale), "change": chg, "day_rs": (price - prev) * r.qty if chg is not None else None,
                         "value": _f(r.value), "cost": _f(r.cost), "unrealised": _f(r.unrealised),
                         "weight": (_f(r.value) or 0) / total, "spark": [float(c) for c in closes[-20:]]})
        rows.sort(key=lambda x: -(x["value"] or 0))
    v = n["valuation"]
    fds = n["fds"]
    return {"asof": str(asof), "net_worth": n["net_worth"], "investable": n["investable"], "reserve": n["reserve"],
            "buckets": n["buckets"], "invested_cost": float(pos["cost"].sum()) if len(pos) else 0.0,
            "unrealised": float(pos["unrealised"].dropna().sum()) if len(pos) else 0.0,
            "day_change": sum(x["day_rs"] for x in rows if x["day_rs"] is not None),
            "cash": float(v.cash_total), "unpriced": len(v.unpriced), "stale": len(v.stale),
            "today": {**n["today"], "lines": nw.summary(n["today"])},
            "fd_estimated": n["fd_estimated"], "rows": rows,
            "fds": [{"maturity": str(r.maturity), "value": _f(r.value), "estimate": bool(r.estimate),
                     "reserve": bool(r.reserve)} for r in fds.itertuples()] if len(fds) else []}


def mix(con, asof: date) -> dict:
    """Current weights against the investor's targets (the monthly planner's own weights; nothing logged)."""
    from pflab.plan import monthly
    from pflab.plan import targets as tg
    try:
        t = tg.load()
        plan, _ = monthly.run(con, asof, 0.0, t, log=False)
    except Exception as e:                              # targets not set, an unpriced holding: said, not hidden
        return {"error": f"{type(e).__name__}: {e}"[:300], "rows": []}
    rows = [{"bucket": b, "weight": plan.weights_before.get(b, 0.0), "target": bt.target, "soft": bt.soft_band,
             "status": plan.status_after.get(b, "")} for b, bt in t.buckets.items()]
    return {"rows": rows, "set_by": t.set_by, "effective_from": str(t.effective_from)}


def market(asof: date) -> dict:
    from pflab.plan import guards as gd
    out: dict = {}
    try:
        cl = gd.market_cluster(asof)
        if cl:
            out.update(state=cl["state"], chance=cl["chance"], vol_chance=cl.get("vol_chance"), date=str(cl["date"]),
                       horizon=cl["horizon"])
        dp = gd.market_dip(asof)
        out.update(drawdown=dp["drawdown"], dip_active=dp["active"])
    except Exception as e:
        out["error"] = str(e)[:200]
    try:                                                   # S64: Nifty IV, PCR, futures premium (information only)
        from pflab.data import data_dir
        from pflab.quant import options
        out["fo_line"] = options.line(data_dir(), asof)
    except Exception:
        pass
    return out


def notifications(con, now: datetime, limit: int = 8) -> List[dict]:
    out = []
    for qid, created, agent, text in con.execute(
            "SELECT q_id, created_at, agent, text FROM questions WHERE status='open' ORDER BY created_at DESC LIMIT 5").fetchall():
        out.append({"kind": "question", "text": text, "meta": f"{agent} · asks you", "at": str(created)[:16]})
    for sym, happened, kind, detail in con.execute(
            "SELECT symbol, happened_at, kind, detail FROM research_flags WHERE detected_at >= ? ORDER BY happened_at DESC "
            "LIMIT 6", [now - timedelta(days=3)]).fetchall():
        out.append({"kind": kind, "text": f"{sym or ''} {detail}".strip(), "meta": f"research · {kind}", "at": str(happened)[:16]})
    for sym, kind, level, hit in con.execute(
            "SELECT symbol, kind, level, last_hit_at FROM watches WHERE last_hit_at >= ? ORDER BY last_hit_at DESC LIMIT 4",
            [now - timedelta(days=1)]).fetchall():
        out.append({"kind": "watch", "text": f"{sym} is {kind} {level:,.2f}", "meta": "your watch", "at": str(hit)[:16]})
    for created, source, due, js in con.execute(
            "SELECT created_at, source, due, plan_json FROM ready_plans WHERE status='current' AND trigger_key NOT LIKE 'custom:%' "
            "AND (created_at >= ? OR due <= ?) ORDER BY due LIMIT 3", [now - timedelta(days=1), now.date() + timedelta(days=7)]).fetchall():
        ch = json.loads(js).get("changes") or []
        out.append({"kind": "plan", "text": f"Ready plan for {source} (due {due}): {'; '.join(ch)[:160]}",
                    "meta": "planner · open Research and plans", "at": str(created)[:16]})
    for created, kind, text in con.execute(
            "SELECT created_at, kind, text FROM outbox WHERE status='pending' AND kind NOT IN ('watch', 'ready_plan') "
            "ORDER BY created_at DESC LIMIT 4").fetchall():
        out.append({"kind": "held", "text": text.split("\n")[0][:200], "meta": f"{kind} · held, not sent", "at": str(created)[:16]})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out[:limit]


def activity(con, busy: Optional[str], limit: int = 10) -> List[dict]:
    rows = [{"job": busy, "status": "running", "at": "now", "detail": ""}] if busy else []
    for job, started, finished, status, detail in con.execute(
            "SELECT job, started_at, finished_at, status, detail FROM job_runs ORDER BY started_at DESC LIMIT ?", [limit]).fetchall():
        took = f"{(finished - started).total_seconds() / 60:.1f} min" if finished and started else ""
        rows.append({"job": job, "status": status, "at": str(started)[:16], "took": took, "detail": (detail or "")[:160]})
    return rows[:limit]


def notes(con) -> List[dict]:
    return [{"id": i, "text": t, "done": bool(d), "at": str(c)[:16]} for i, t, d, c in con.execute(
        "SELECT note_id, text, done, created_at FROM app_notes WHERE deleted = false AND list_name IS NULL "
        "ORDER BY created_at").fetchall()]


def schedule(rt, now: Optional[datetime] = None) -> dict:
    """The jobs (and which the preset runs), the preset, how long the system was off (missed jobs catch up on the next
    tick), the checklists and their templates, the nightly simulation."""
    from pflab.app import checklists as cl
    from pflab.app import settings as st
    from pflab.app import sims
    from pflab.conductor import sync
    from pflab.service import jobs, tasks  # noqa: F401
    now = now or rt.clock()
    con = rt.cursor()
    ctx = jobs.Ctx(con, now, rt.pm_dir, rt.data_root, rt.repo, secrets=rt.secrets)   # S58b: the login check needs them
    preset = rt.settings.get("preset", "full")
    runs = set(st.jobs_for(preset, jobs.REGISTRY))
    latest = {j: (s, a, b, d) for j, s, a, b, d in con.execute(
        "SELECT job, status, started_at, finished_at, detail FROM job_runs QUALIFY row_number() OVER "
        "(PARTITION BY job ORDER BY started_at DESC, run_id DESC) = 1").fetchall()}
    rows = []
    for r in jobs.plan(ctx):
        s = r["schedule"]
        when = f"daily {s.hour:02d}:{s.minute:02d}" if hasattr(s, "hour") else f"every {getattr(s, 'minutes', '?')} min"
        on = r["job"] in runs and (r["job"] != "outbox" or rt.settings.get("telegram_send"))
        lr = latest.get(r["job"])
        rows.append({"job": r["job"], "due": bool(r["due"]), "why": r["why"], "when": when, "on": on,
                     "last_success": str(r["last_success"])[:16] if r["last_success"] else None,
                     "last_run": lr and {"status": lr[0], "at": str(lr[1])[:16],
                                         "seconds": round((lr[2] - lr[1]).total_seconds(), 1) if lr[2] else None,
                                         "detail": None if lr[0] == "ok" else (lr[3] or "")[:200]},
                     "asked": rt.asked.get(r["job"]), "queued": r["job"] in rt.wanted,
                     "runnable": r["job"] != "outbox" or bool(rt.settings.get("telegram_send"))})
    gap = sync.offline_gap(con, now)
    last = (sims.cached(rt) or {})
    return {"jobs": rows, "preset": preset, "presets": st.PRESETS, "sims_hour": rt.settings.get("sims_hour", 22),
            "sims": {"paths": st.sims_paths(preset), "last": last.get("at"), "last_paths": last.get("paths"),
                     "running": rt.sims_running},
            "offline_h": round(gap.total_seconds() / 3600, 1) if gap else None,
            "catch_up": [r["job"] for r in rows if r["due"] and r["on"]], "wanted": list(rt.wanted), "busy": rt.busy,
            "checklists": cl.lists(con), "templates": {k: len(v) for k, v in cl.TEMPLATES.items()}}


def sims_view(rt) -> dict:
    from pflab.app import settings as st
    from pflab.app import sims
    return {"result": sims.cached(rt), "running": rt.sims_running, "error": rt.sims_error, "paths_choices": list(sims.PATHS),
            "preset": rt.settings.get("preset", "full"), "nightly_paths": st.sims_paths(rt.settings.get("preset", "full")),
            "sims_hour": rt.settings.get("sims_hour", 22)}


def inbox(rt) -> dict:
    """Inbox and files: what the investor dropped and where each went, the bank accounts a statement can belong to, and what
    the system needs from him (the conductor's asks and the agents' open questions)."""
    from pflab.app import inbox as ib
    from pflab.ingest import sources as srcs
    con = rt.cursor()
    try:
        accounts = srcs.bank_accounts(rt.pm_dir / "sources.toml")
    except Exception:
        accounts = []
    needs = [{"id": q, "at": str(c)[:16], "agent": a, "text": t} for q, c, a, t in con.execute(
        "SELECT q_id, created_at, agent, text FROM questions WHERE status='open' ORDER BY created_at DESC").fetchall()]
    log_p = rt.pm_dir / "app" / "cache" / "cleanup_log.json"
    try:
        log = json.loads(log_p.read_text(encoding="utf-8"))[:10] if log_p.exists() else []
    except ValueError:
        log = []
    return {"items": ib.listing(rt), "accounts": accounts, "needs": needs, "image_days": ib.IMAGE_DAYS,
            "kinds": ib.KIND_LABEL, "cleanup": log}


def _nudges(rt, n: int = 4) -> List[dict]:
    from pflab.app import research as rs
    w = rs.read_cache(rt, "watch") or {}
    out = []
    for r in w.get("rows", []):
        z = r.get("zone") or {}
        if z.get("verdict") in ("IN ZONE", "RICH", "NO"):
            out.append({"symbol": r["symbol"], "verdict": z["verdict"], "text": z.get("headline", ""), "price": z.get("price")})
    return out[:n]


def command(rt, now: Optional[datetime] = None) -> dict:
    from pflab.app import runtime as rtm
    from pflab.conductor import calendar as cal
    now = now or rt.clock()
    con = rt.cursor()
    c = cal.load()
    mc = rt.mc_cache()
    tail = smalln.tail(mc["p_fall35"], mc["paths"]) if mc else smalln.tail(None, 0)
    h = holdings(con, now.date())
    return {"now": now.isoformat(timespec="seconds"), "mode": c.mode(now), "next_session": str(c.next_trading_day(now.date())),
            "kite": {"logged_in": rtm.token_valid(now), "state": rt.kite_state}, "update_ready": rt.update_ready,
            "market": market(now.date()), "tickers": tickers(rt.data_root, rt.live_indices), "holdings": h,
            "mix": mix(con, now.date()), "notifications": notifications(con, now), "activity": activity(con, rt.busy),
            "notes": notes(con), "montecarlo": {**(mc or {}), "tail": tail}, "nudges": _nudges(rt),
            "settings": {k: rt.settings[k] for k in ("privacy", "theme", "telegram_send")}}


# PLAN A9's roster: agent, its jobs (None: runs inside the app or on demand), model, autonomy, what checks it, duty
ROSTER = [
    ("Collector", ["collect", "prices", "nav", "global"], "none", "acts", "sync check", "prices, actions, dividends, NAVs, gold, world markets, news"),
    ("Filings monitor", ["filings"], "local tagger", "acts (alerts)", "red-flag rules, S47", "BSE filings for held and list names"),
    ("Portfolio keeper", None, "none", "acts", "maths audit (S43)", "live values every minute in market hours (Kite), the rest at the close"),
    ("Risk manager", ["guards"], "none", "acts (alerts)", "S34, S40, S51", "guards, market state, surveillance, dip and FD alerts"),
    ("Simulator", None, "none", "acts", "closed forms (S43)", "Monte Carlo of the current mix, refreshed daily"),
    ("Forecaster", ["forecast"], "statistics", "acts", "live coverage score", "price ranges, turnover for tickets, results before the result"),
    ("Researcher", ["research"], "Opus notes for what changed (batch); local guarded brief", "acts", "S42, S47",
     "what changed per company; Opus researches it overnight, the brief cites the note"),
    ("Watch list", None, "none", "acts (nudges)", "buy-zone v1 (an estimate)", "buy zones, yes / wait / no, price watches"),
    ("Analyst (Opus)", ["analyst"], "Opus", "acts within the cap", "adopted comparison", "deep notes and web search on public data"),
    ("Knowledge graph", ["kg"], "none", "acts", "point-in-time links", "filings, results, news, notes linked and dated"),
    ("Trade check", ["tradecheck"], "none", "asks", "reconciliation", "Kite trades and holdings against the ledger"),
    ("Conductor", ["conductor"], "none", "acts", "sync check", "runs and catches up jobs, asks for files, notes"),
    ("Workshop", None, "Opus writes code", "proposes", "acceptance 10/10", "new calculations as code, run on this PC"),
    ("Telegram outbox", ["outbox"], "none", "acts", "held until switch-on", "delivers messages (text only)"),
    ("Backup", ["backup"], "none", "acts", "verify after copy", "copies the ledger (needs a target)"),
    ("Learner", ["learner"], "local, then Haiku; Sonnet words proposals", "acts by rule, asks the rest",
     "registered tests (learner_protocol.md)", "papers and blogs -> tested claims; the system's record -> proposals"),
    ("Security", ["security"], "code; Sonnet code review weekly", "reports only", "never changes code or data",
     "what left the PC, data flows, repo privacy, the tests"),
]


def ai(rt, chat_id: Optional[int] = None, now: Optional[datetime] = None) -> dict:
    """The AI centre: chats, the open chat's messages, the agents and their last runs, questions, API spend."""
    from pflab.agents import analyst as an
    from pflab.app import chat
    now = now or rt.clock()
    con = rt.cursor()
    chats = chat.listing(con)
    cur = chat_id if chat_id and any(c["id"] == chat_id for c in chats) else (chats[0]["id"] if chats else None)
    last = {j: (s, str(t)[:16], (d or "")[:160]) for j, s, t, d in con.execute(
        "SELECT job, status, started_at, detail FROM (SELECT *, row_number() OVER (PARTITION BY job ORDER BY started_at DESC) rn "
        "FROM job_runs) WHERE rn = 1").fetchall()}
    agents = []
    for name, js, model, autonomy, check, duty in ROSTER:
        runs = [(j, *last[j]) for j in (js or []) if j in last]
        latest = max(runs, key=lambda r: r[2]) if runs else None
        state = "running" if rt.busy and any(j in (rt.busy or "") for j in (js or [])) else \
            (latest[1] if latest else ("in the app" if js is None else "never run"))
        detail = latest[3] if latest else ""
        if name == "Learner":                                  # S64: how many tests have run and the bar now
            from pflab.learner import counter
            try:
                detail = f"{counter.line(con)} {detail}".strip()
            except Exception:                                  # a store before v35
                pass
        agents.append({"name": name, "jobs": js or [], "model": model, "autonomy": autonomy, "check": check, "duty": duty,
                       "state": state, "last": latest[2] if latest else None, "detail": detail})
    cfg = an.config()
    qs = [{"id": i, "agent": a, "text": t, "at": str(c)[:16]} for i, c, a, t in con.execute(
        "SELECT q_id, created_at, agent, text FROM questions WHERE status='open' ORDER BY created_at DESC").fetchall()]
    return {"chats": chats, "chat_id": cur, "messages": chat.messages(con, cur) if cur else [], "agents": agents,
            "questions": qs, "spend": {"month": an.month_spend_inr(con, now), "cap": cfg["cap"], "adopted": cfg["adopted"]},
            "calcs": calcs(rt)}


def calcs(rt, n: int = 12) -> List[dict]:
    """The workshop's kept calculations, newest first: what each answers, reviewed or not, reused or written."""
    import json as _json
    from pflab.agents import workshop as wk
    out = []
    for d in sorted(wk.folder(rt.pm_dir).glob("*/meta.json"), reverse=True)[:n]:
        m = _json.loads(d.read_text(encoding="utf-8"))
        out.append({"id": d.parent.name, "question": m["question"], "status": m["status"], "label": m["label"],
                    "writer": m.get("writer", ""), "params": sorted((m.get("params") or {}).keys()),
                    "reused_from": m.get("reused_from"), "at": m.get("created", "")[:16].replace("T", " ")})
    return out


def watch(rt) -> dict:
    """The watch list from its cache (computed in the background), with the investor's price watches."""
    from pflab.app import research as rs
    w = rs.read_cache(rt, "watch")
    con = rt.cursor()
    ws = [{"id": i, "isin": s, "symbol": y, "kind": k, "level": lv, "note": n, "hits": h, "last_hit": str(t)[:16] if t else None}
          for i, s, y, k, lv, n, h, t in con.execute(
              "SELECT watch_id, isin, symbol, kind, level, note, hits, last_hit_at FROM watches WHERE active ORDER BY watch_id").fetchall()]
    return {"computing": w is None, "at": (w or {}).get("at"), "paths": (w or {}).get("paths"), "rows": (w or {}).get("rows", []),
            "watches": ws}


def maths(rt, isin: str, now: Optional[datetime] = None) -> dict:
    """The stock page's maths block (S64): CAPM, the process it follows, who it moves with, and the series to draw.
    Tools only (no model): every number is from code, each part carries its source and label."""
    import numpy as np
    from pflab.app import research as rs
    from pflab.hq import stocks
    from pflab.quant import comove, process
    from pflab.risk import capm
    now = now or rt.clock()
    asof, root, con = now.date(), rt.data_root, rt.cursor()
    row = con.execute("SELECT symbol FROM instruments WHERE isin=? ORDER BY valid_to DESC NULLS FIRST LIMIT 1", [isin]).fetchone()
    sym = row[0] if row else isin
    c = rs.closes(con, root, isin, asof, years=4)
    out = {"isin": isin, "symbol": sym, "asof": str(asof), "capm": stocks.capm_part(root, isin, asof),
           "process": stocks.process_part(root, isin, c, asof), "moves_with": comove.moves_with(sym, root), "plots": {}}
    try:
        rb = capm.rolling_beta(root, isin, asof)
        if len(rb):
            out["plots"]["rolling_beta"] = {"title": "Beta over the trailing 36 months", "dates": [str(d.date()) for d in rb.index],
                                            "lines": [{"name": "beta", "y": [round(float(v), 3) for v in rb.values]}],
                                            "guides": [{"y": 1.0, "label": "market"}]}
    except Exception as e:
        out["plots"]["rolling_beta"] = {"error": f"{type(e).__name__}"}
    try:
        from pflab.quant import forecast as fcst
        fan = fcst.fan(con, isin, root)
        if fan["ranges"]:
            px0 = fan["ranges"][0]["price"]
            out["plots"]["price_fan"] = {
                "title": f"Price range, 80% (q10, middle, q90) at 21, 63 and 252 sessions: {fan['method']}, {fan['label']}",
                "dates": ["now"] + [f"{r['sessions']} sessions" for r in fan["ranges"]],
                "lines": [{"name": n, "y": [round(px0, 2)] + [round(r[k], 2) for r in fan["ranges"]]}
                          for n, k in (("q90", "q90"), ("middle", "q50"), ("q10", "q10"))],
                "guides": [{"y": round(px0, 2), "label": "price now"}]}
    except Exception as e:
        out["plots"]["price_fan"] = {"error": f"{type(e).__name__}"}
    try:
        ind, key = comove.sector_index_for(root, isin, asof)
        if key:
            from pflab.data import indices
            d = indices.load(key, root)
            idx = d.assign(date=pd.to_datetime(d["date"])).set_index("date")["close"].sort_index()
            sp, _ = process.spread(c.dropna().iloc[-stocks.ODDS_SESSIONS:], idx[idx.index <= pd.Timestamp(asof)])
            if len(sp) > 60:
                z = (sp - sp.mean()) / sp.std(ddof=1)
                z = z.iloc[::3]
                out["plots"]["spread_z"] = {"title": f"Spread to {key.replace('SECTOR_', '').replace('_TRI', '')} index, in standard deviations",
                                            "dates": [str(x.date()) for x in z.index],
                                            "lines": [{"name": "z", "y": [round(float(v), 2) for v in z.values]}],
                                            "guides": [{"y": 2.0, "label": "+2"}, {"y": 0.0, "label": "mean"}, {"y": -2.0, "label": "-2"}]}
    except Exception as e:
        out["plots"]["spread_z"] = {"error": f"{type(e).__name__}"}
    return out


def research(rt, isin: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    """Research and plans: the ready plan and what not to buy now, results ranges, flags, notes, a stock's technicals."""
    from pflab.app import research as rs
    from pflab.quant import technicals
    now = now or rt.clock()
    con = rt.cursor()
    from pflab.plan import ready
    w = rs.read_cache(rt, "watch")
    status = rs.read_cache(rt, "plan") or {}
    flags = [{"symbol": s, "at": str(h)[:16], "kind": k, "detail": d} for s, h, k, d in con.execute(
        "SELECT symbol, happened_at, kind, detail FROM research_flags WHERE happened_at >= ? ORDER BY happened_at DESC LIMIT 40",
        [now - timedelta(days=7)]).fetchall()]
    notes = [{"id": i, "title": t, "source": s, "at": str(p)[:16]} for i, t, s, p in con.execute(
        "SELECT doc_id, title, source, published_at FROM kg_docs WHERE kind='analyst_note' ORDER BY published_at DESC LIMIT 8").fetchall()]
    results = [x for r in (w or {}).get("rows", []) for x in r.get("results", [])]
    names_ = [{"isin": r["isin"], "symbol": r["symbol"]} for r in (w or {}).get("rows", [])]
    sel = isin or (names_[0]["isin"] if names_ else None)
    tech = technicals.for_isin(rt.data_root, sel, now.date()) if sel else None
    zones = {r["symbol"]: {"verdict": r["zone"].get("verdict"), "headline": r["zone"].get("headline", "")}
             for r in (w or {}).get("rows", [])}
    return {"plans": ready.current(con), "plan_status": status, "hold_off": rs.hold_off(w, con, now), "results": results,
            "flags": flags, "notes": notes,
            "names": names_, "selected": sel, "technicals": tech, "zones": zones}


def portfolio(rt, isin: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    """The granular view: buckets, sectors, every position, a stock's tax lots, FDs, the year's tax so far."""
    from pflab.ledger import events as ev
    from pflab.ledger.book import Ledger
    now = now or rt.clock()
    con = rt.cursor()
    asof = now.date()
    h = holdings(con, asof)
    sectors: Dict[str, float] = {}
    for r in h["rows"]:
        if r["bucket"] == "equity" and r["value"]:
            sectors[r["sector"] or "Unclassified"] = sectors.get(r["sector"] or "Unclassified", 0.0) + r["value"]
    eq = sum(sectors.values()) or 1.0
    lots = []
    sel = isin or (h["rows"][0]["isin"] if h["rows"] else None)
    # S58b: the tax planner (the tax engine's answers): each lot's term from its rule, the tax of selling through it
    from pflab.tax import plan as tp
    try:
        o = tp.overview(con, asof)
        taxplan = {"lines": tp.render(o), "left": o["harvest"]["left"], "exemption": o["harvest"]["exemption"],
                   "harvest": o["harvest"]["sales"], "losses": o["losses"], "soon": o["turning_long_term"]}
    except Exception as e:                              # a rule gap or an unclassified holding: said, not hidden
        o, taxplan = None, {"error": f"{type(e).__name__}: {e}"[:300]}
    if sel:
        led = Ledger.replay(ev.load(con), upto=asof)
        price = next((r["price"] for r in h["rows"] if r["isin"] == sel), None)
        tc = (con.execute("SELECT tax_class FROM instruments WHERE isin=?", [sel]).fetchone() or [None])[0]
        steps = {(acc, s["bought"], s["qty"]): s for (acc, i, _sym), st in ((o or {}).get("ladders") or {}).items()
                 if i == sel for s in st}
        for l in sorted((l for l in led.lots.all_lots() if l.isin == sel), key=lambda l: (l.acq_date, l.lot_id)):
            held = (asof - l.acq_date).days
            lt_on = tp.long_term_from(tp.rule_of(tc, l.acq_date, asof), l.acq_date) if tc else None
            s = steps.get((l.account_id, l.acq_date, l.qty), {})
            lots.append({"bought": str(l.acq_date), "qty": l.qty, "cost_per_unit": l.cost_per_unit,
                         "value": l.qty * price if price else None, "gain": (price - l.cost_per_unit) * l.qty if price else None,
                         "held_days": held, "long_term_from": str(lt_on) if lt_on else None,
                         "long_term": bool(lt_on and asof >= lt_on), "account": l.account_id,
                         "tax_through": s.get("extra_tax"), "waiting_saves": s.get("waiting_saves")})
    tax = {}
    try:
        from pflab.tax import report as tr
        fy = asof.year + 1 if asof.month >= 4 else asof.year
        t = tr.build(con, fy)
        tax = {"fy": fy, "new": t["regimes"]["new"].total_tax, "old": t["regimes"]["old"].total_tax,
               "cheaper": t["regimes"]["cheaper"], "realised": dict(t["gains"].realised),
               "exemption_used": getattr(t["gains"], "exemption_used", None),
               "fd_interest": (t.get("fd") or {}).get("interest"), "fd_estimate": (t.get("fd") or {}).get("is_estimate")}
    except Exception as e:
        tax = {"error": str(e)[:200]}
    try:                                                # S63: where the year's change came from (calc/growth.py)
        from pflab.hq import context
        growth = context.growth(con, asof, 12)
    except Exception as e:
        growth = {"error": f"{type(e).__name__}: {e}"[:200]}
    return {"asof": str(asof), "holdings": h, "mix": mix(con, asof),
            "sectors": sorted(({"sector": k, "value": v, "weight": v / eq} for k, v in sectors.items()), key=lambda x: -x["value"]),
            "selected": sel, "lots": lots, "tax": tax, "taxplan": taxplan, "growth": growth}
