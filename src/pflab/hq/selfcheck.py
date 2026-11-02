"""Does everything work? (S78; his question 2026-11-02: "how do I make sure all agents, tools and the brain work properly?")

The system tests itself, every night and after every update, and on his button. Three kinds of check, all free of API money (the one paid thing, a cloud generation, is never made here):
    alive    a heartbeat: the loops acted, the jobs ran, the data is fresh, the agents have worked lately
    answers  a harmless known input to every tool; the result must come back in its shape; the local model answers; the cloud model's account answers (token count, free)
    right    known questions with known answers, compared by code (the tax maths, the rails, a planted invented number, a plan's structure, a candle pattern, a forbidden order)
Results are kept (`selfchecks`) and shown on System. A READ tool that fails its probe twice in a row is QUARANTINED: `tools.run` refuses it with the reason until it passes again, so an
agent never works from a tool that is known to be broken. Nothing is ever quarantined by a check that could not run (no Docker, no Kite today): those are warnings, said as such.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

OK, WARN, BAD = "ok", "warn", "bad"
GROUPS = ("Brain and models", "Agents", "Tools", "Data and Kite", "Safety", "Loops and money")
QUARANTINE_AFTER = 2                         # consecutive failures of a read tool's probe before it is refused


class Run:
    """One run's results, in order. `check` runs a function that returns (status, note) or raises."""

    def __init__(self, con, now: datetime):
        self.con, self.now = con, now
        self.run_id = int(con.execute("SELECT coalesce(max(run_id), 0) FROM selfchecks").fetchone()[0]) + 1
        self.rows: List[dict] = []

    def add(self, grp: str, name: str, status: str, note: str, ms: int = 0) -> None:
        from pflab.pm.store import next_id
        cid = next_id(self.con, "selfchecks", "check_id")
        self.con.execute("INSERT INTO selfchecks VALUES (?,?,?,?,?,?,?,?)", [cid, self.run_id, self.now, grp, name, status, note[:400], ms])
        self.rows.append({"grp": grp, "name": name, "status": status, "note": note[:400]})

    def check(self, grp: str, name: str, fn: Callable[[], Tuple[str, str]]) -> None:
        t0 = time.monotonic()
        try:
            status, note = fn()
        except Exception as e:                                          # a check that crashes is a failed check, said with why
            status, note = BAD, f"{type(e).__name__}: {str(e)[:200]}"
        self.add(grp, name, status, note, int((time.monotonic() - t0) * 1000))


# --- quarantine -------------------------------------------------------------------------------------------------------------------------------

def quarantined(con, tool: str) -> Optional[str]:
    """The reason a read tool is refused now: its probe failed QUARANTINE_AFTER runs in a row and has not passed since. None when it may be used."""
    try:
        rows = con.execute("SELECT status, note FROM selfchecks WHERE grp='Tools' AND name=? ORDER BY check_id DESC LIMIT ?", [f"probe: {tool}", QUARANTINE_AFTER]).fetchall()
    except Exception:
        return None
    if len(rows) == QUARANTINE_AFTER and all(r[0] == BAD for r in rows):
        return f"{tool} failed its self-check {QUARANTINE_AFTER} times in a row ({rows[0][1][:120]}) and is not used until it passes again; use another way or say it could not be checked"
    return None


# --- the probes --------------------------------------------------------------------------------------------------------------------------------

def _held_symbol(con) -> Optional[str]:
    r = con.execute("SELECT i.symbol FROM lots l JOIN instruments i ON i.isin = l.isin WHERE l.qty > 0 AND i.symbol IS NOT NULL AND i.asset_class='equity' "
                    "GROUP BY 1 ORDER BY sum(l.qty * l.cost_per_unit) DESC LIMIT 1").fetchone()
    return r[0] if r else None


def probe_args(con, name: str) -> Optional[dict]:
    """Harmless known input for a read tool; None when it needs something this install does not have yet (then only its shape is checked)."""
    sym = _held_symbol(con)
    needs_symbol = {"stock_facts": {"symbol": sym}, "price_history": {"symbol": sym}, "chart_view": {"symbol": sym, "timeframe": "daily", "bars": 40},
                    "readings": {"symbol": sym}, "who_is_buying": {"symbol": sym}, "graph_timeline": {"symbol": sym}, "notes": {"symbol": sym}, "comovement": {"symbol": sym}}
    if name in needs_symbol:
        return needs_symbol[name] if sym else None
    known = {"measure": {"measure": "drawdown", "series": "NIFTY 500"}, "quant": {"idea": "a drop after a results announcement"}, "growth": {"months": 12}, "scenario": {"name": "oil_up_30"},
             "ipo_plan": {"name": "Selfcheck Ltd", "shares": 100, "issue_price": 100.0, "budget": 50000.0}}            # harmless known inputs for the tools that need more than a symbol
    return known.get(name, {})


def run_all(rt, now: datetime, quick: bool = False) -> dict:
    """Every check. `quick` leaves out the local model's answer (it can take a GPU turn). Returns {'run_id', 'ok', 'warn', 'bad', 'total', 'rows'}."""
    con = rt.cursor()
    r = Run(con, now)
    _models(rt, con, r, now, quick)
    _agents(rt, con, r, now)
    _tools(rt, con, r, now)
    _data(rt, con, r, now)
    _safety(rt, con, r, now)
    _loops(rt, con, r, now)
    c = {s: sum(1 for x in r.rows if x["status"] == s) for s in (OK, WARN, BAD)}
    return {"run_id": r.run_id, **c, "total": len(r.rows), "rows": r.rows}


def _models(rt, con, r: Run, now: datetime, quick: bool) -> None:
    G = "Brain and models"

    def local():
        from pflab.llm import client, structured
        have = client.installed()
        miss = [m for m in ("qwen3:8b-q8_0", "nomic-embed-text") if not any(h.startswith(m.split(":")[0]) for h in have)]
        if miss:
            return BAD, f"not installed: {', '.join(miss)}"
        if quick:
            return OK, "installed (the answer test is part of the nightly run)"
        t0 = time.monotonic()
        res = structured.ask_json("Answer with JSON only.", 'Return {"ok": true}.', {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                                  lambda o: None if o.get("ok") is True else "ok must be true", purpose="selfcheck")
        return (OK, f"answered in {time.monotonic() - t0:.1f} s, JSON valid") if res.ok else (BAD, f"did not answer correctly: {getattr(res, 'error', '')}")
    r.check(G, "Local model", local)

    def cloud():
        from pflab.hq import service
        from pflab.agents import analyst as an
        cfg = an.config()
        if not cfg.get("cap"):
            return WARN, "no monthly cap is set: the cloud is switched off"
        cl = service.client(rt)
        n = cl.messages.count_tokens(model="claude-sonnet-5-5", messages=[{"role": "user", "content": "ping"}]).input_tokens
        return OK, f"the account answers (a token count, free): {n} tokens"
    r.check(G, "Cloud model", cloud)

    def numbers():
        from pflab.agents import analyst as an
        req = an.Request(question="What is the weight?", topic="selfcheck", docs=[an.Doc(title="t", text="The weight is 10.5 percent", source="selfcheck", published="2026-11-01", kind="article")])
        txt, dropped = an.only_sourced_numbers("The weight is 10.5 percent. The fall will be 37.25 percent.", req)
        return (OK, "kept the sourced number, removed the invented one") if (dropped == 1 and "10.5" in txt and "37.25" not in txt) else (BAD, f"number guard misbehaved: kept {txt!r}, dropped {dropped}")
    r.check(G, "Number guard", numbers)

    def plan():
        from pflab.hq import missions, playbooks
        steps, approach = playbooks.paper_steps("Paper portfolio: the weekly review")
        keys = [x["key"] for x in steps]
        bad = []
        if not 2 <= len(steps) <= 6:
            bad.append("number of steps")
        if any(x["role"] not in missions.ROLES for x in steps):
            bad.append("a role the system does not have")
        if any(k not in missions.PROMISE_KINDS for x in steps for k in x["promise"]):
            bad.append("a promise it cannot check")
        if any(d not in keys[:i] for i, x in enumerate(steps) for d in x["depends_on"]):
            bad.append("a dependency on a later step")
        return (OK, f"the paper playbook builds a {len(steps)}-step plan the mission machinery accepts") if not bad else (BAD, f"plan failed: {', '.join(bad)}")
    r.check(G, "Plan by code", plan)


def _agents(rt, con, r: Run, now: datetime) -> None:
    G = "Agents"
    for role, label in (("coordinator", "Coordinator"), ("research", "Research"), ("quant", "Quant"), ("review", "Reviewer")):
        def f(role=role):
            row = con.execute("SELECT status, max(coalesce(finished_at, started_at)) FROM hq_tasks WHERE role = ? GROUP BY status ORDER BY 2 DESC LIMIT 1", [role]).fetchone() \
                if _has(con, "hq_tasks", "role") else None
            done = con.execute("SELECT max(finished_at) FROM hq_tasks WHERE role=? AND status='done'", [role]).fetchone()[0] if _has(con, "hq_tasks", "role") else None
            failed = con.execute("SELECT max(finished_at) FROM hq_tasks WHERE role=? AND status='failed'", [role]).fetchone()[0] if _has(con, "hq_tasks", "role") else None
            if done is None and failed is None:
                return WARN, "has not worked yet: nothing to test against until its first task"
            if failed and (done is None or failed > done):
                return BAD, f"its latest task failed ({str(failed)[:16]}) and none has succeeded since"
            age = (now - done).days
            return (OK, f"last task done {str(done)[:16]}") if age <= 14 else (WARN, f"no task for {age} days")
        r.check(G, label, f)

    def assistant():
        n = con.execute("SELECT count(*) FROM chat_messages WHERE role='ai' AND status='done' AND created_at >= ?", [now - timedelta(days=14)]).fetchone()[0]
        return (OK, f"{n} answer(s) in the last 14 days") if n else (WARN, "no answer in the last 14 days")
    r.check(G, "Assistant", assistant)

    def plumbing():
        """The path every agent uses to call a tool (allow-list, validation, redaction, privacy check, the journal): one read tool is called through it."""
        from pflab.hq import egress, tools as tl
        ctx = tl.Ctx(rt, None, "m", False, {}, egress.Gate(), now, role="research", allowed=frozenset({"system_status"}))
        text, err = tl.run(ctx, "system_status", {})
        return (OK, "a read tool ran through the same path the agents use") if not err else (BAD, text[:160])
    r.check(G, "Worker loop path", plumbing)


def _has(con, table: str, col: str) -> bool:
    return bool(con.execute("SELECT 1 FROM information_schema.columns WHERE table_name=? AND column_name=?", [table, col]).fetchone())


def _tools(rt, con, r: Run, now: datetime) -> None:
    from pflab.hq import egress, tools as tl
    G = "Tools"
    ctx = tl.Ctx(rt, None, "m", False, {}, egress.Gate(), now, role="assistant", allowed=frozenset(tl.TOOLS))
    reads = [n for n, t in tl.TOOLS.items() if t.kind == "read"]
    for name in reads:
        def probe(name=name):
            args = probe_args(con, name)
            if args is None:
                return WARN, "needs data this install does not have yet (a holding): only its shape was checked"
            tool = tl.TOOLS[name]
            bad = tl.validate(tool, args)
            if bad:
                return WARN, f"probe input is not valid for it ({bad}): shape only"
            t0 = time.monotonic()
            res = tool.fn(ctx, args)
            if not isinstance(res, dict):
                return BAD, "did not return a result object"
            if "error" in res and len(res) == 1:
                return BAD, f"returned an error: {str(res['error'])[:140]}"
            ctx.images.clear()
            return OK, f"answered in {int((time.monotonic() - t0) * 1000)} ms"
        r.check(G, f"probe: {name}", probe)

    def definitions():
        d = tl.definitions(frozenset(tl.TOOLS))
        bad = [x["name"] for x in d if not x.get("input_schema")]
        return (OK, f"{len(d)} tool definitions build for the model") if not bad else (BAD, f"definition missing a schema: {bad[:3]}")
    r.check(G, "Definitions", definitions)

    def no_order():
        words = ("order", "trade", "gtt", "place", "buy", "sell")
        bad = [n for n in tl.TOOLS if any(w in n for w in words) and n not in ("order_research", "order_calculation", "who_is_buying")]
        return (OK, "no tool can place an order") if not bad else (BAD, f"order-like tool names: {bad}")
    r.check(G, "No order tool", no_order)


def _data(rt, con, r: Run, now: datetime) -> None:
    G = "Data and Kite"
    from pflab.conductor import calendar
    cal = calendar.load()

    def closes():
        last = con.execute("SELECT max(date) FROM prices WHERE source='nse_bhavcopy'").fetchone()[0]
        want = cal.previous_trading_day(now.date() + timedelta(days=1)) if cal.mode(now) in ("after_close", "closed") and cal.is_trading_day(now.date()) and now.hour >= 21 else cal.previous_trading_day(now.date())
        if last is None:
            return BAD, "no exchange closes on record"
        return (OK, f"loaded to {last}") if last >= want else (WARN, f"loaded to {last}; the latest session is {want}")
    r.check(G, "Exchange closes", closes)

    def kite():
        from pflab.app import runtime as rtm
        if not rtm.token_valid(now):
            return WARN, "not logged in today: the system uses the daily closes"
        q = con.execute("SELECT max(ts) FROM live_quotes WHERE source='kite'").fetchone()[0]
        if cal.mode(now) == "market" and (q is None or now - q > timedelta(minutes=20)):
            return BAD, f"logged in, inside a session, but the last live quote is {str(q)[:16]}"
        return OK, "logged in" + (f"; last live quote {str(q)[:16]}" if q else "")
    r.check(G, "Kite live quotes", kite)

    def candles_ok():
        from pflab.quant import candles
        sym = _held_symbol(con)
        if not sym:
            return WARN, "no holding to test with"
        isin = con.execute("SELECT isin FROM instruments WHERE symbol=? LIMIT 1", [sym]).fetchone()[0]
        df = candles.daily(rt.data_root, isin, now.date(), bars=30)
        if df.empty:
            return BAD, f"no daily candles for a held name"
        lag = (now.date() - df["date"].iloc[-1].date()).days
        return (OK, f"daily candles to {df['date'].iloc[-1].date()}") if lag <= 6 else (WARN, f"daily candles end {lag} days ago")
    r.check(G, "Candles for charts", candles_ok)

    def job(name, label, hours):
        def f():
            row = con.execute("SELECT status, finished_at FROM job_runs WHERE job=? ORDER BY run_id DESC LIMIT 1", [name]).fetchone()
            if not row:
                return WARN, "has not run yet"
            if row[0] == "failed":
                return BAD, f"its last run failed ({str(row[1])[:16]})"
            age = (now - (row[1] or now)).total_seconds() / 3600
            return (OK, f"ran {str(row[1])[:16]}") if age <= hours else (WARN, f"last ran {int(age)} hours ago")
        r.check(G, label, f)
    job("filings", "Company filings", 30)
    job("kg", "Knowledge graph", 36)


def _safety(rt, con, r: Run, now: datetime) -> None:
    G = "Safety"

    def sandbox():
        row = con.execute("SELECT ok, detail, checked_at FROM health_checks WHERE connector='sandbox' ORDER BY check_id DESC LIMIT 1").fetchone()
        if not row:
            return WARN, "no containment probe yet"
        return (OK, f"contained, proven {str(row[2])[:16]}") if row[0] else (BAD, f"the last probe failed: {str(row[1])[:120]}")
    r.check(G, "Calculation sandbox", sandbox)

    def guard():
        from pflab.ingest import kite as k
        from types import SimpleNamespace
        name = sorted(k.FORBIDDEN)[0]                                  # a trading method of the SDK, taken from the wrapper's own list
        kk = k.ReadOnlyKite("key", "tok", factory=lambda **kw: SimpleNamespace(**{name: lambda **a: "placed"}))
        try:
            getattr(kk, name)(tradingsymbol="X")
        except k.TradingForbidden:
            return OK, "a forbidden order was refused"
        return BAD, "a forbidden order was NOT refused"
    r.check(G, "No-trading guard", guard)

    def privacy():
        row = con.execute("SELECT status, finished_at FROM job_runs WHERE job='security' ORDER BY run_id DESC LIMIT 1").fetchone()
        if not row:
            return WARN, "the privacy check has not run yet"
        return (OK, f"ran {str(row[1])[:16]}") if row[0] != "failed" else (BAD, "the last privacy check failed")
    r.check(G, "Privacy check", privacy)

    def maths():
        from pflab.paper import book, rails
        t = book.tax_of({"st_eq": 100_000.0, "lt_eq": 200_000.0})
        want = 0.20 * 100_000 + 0.125 * (200_000 - 125_000)
        if abs(t - want) > 0.01:
            return BAD, f"tax maths: got {t}, expected {want}"
        if book.tax_of({"lt_eq": -5000.0, "st_eq": 10_000.0}) != 2000.0:
            return BAD, "tax set-off rule is wrong"
        return OK, "the tax maths and the set-off rule gave the known answers"
    r.check(G, "Tax maths (known answer)", maths)

    def patterns():
        import pandas as pd
        from pflab.quant import chart
        df = pd.DataFrame({"date": pd.bdate_range("2026-01-05", periods=5), "open": [10, 10, 10, 11.0, 9.5], "high": [10.5, 10.5, 10.5, 11.2, 12.2], "low": [9.5, 9.5, 9.5, 10.0, 9.4],
                           "close": [10, 10, 10, 10.1, 12.0], "volume": [1, 1, 1, 1, 1]})
        f = chart.facts(df)
        return (OK, "a planted bullish engulfing was named by the chart facts") if any("bullish engulfing" in o for o in f.get("observations", [])) else (BAD, "the planted candle pattern was missed")
    r.check(G, "Chart facts (known answer)", patterns)

    def backup():
        from pflab.service import backup as bk
        t = bk.target_dir()
        if t is None:
            return WARN, "no backup folder is set"
        last = bk.latest(t)
        if last is None:
            return BAD, "no backup exists"
        age = (now - last[1]).days
        return (OK, f"last copy {str(last[1])[:16]}") if age <= 2 else (WARN, f"last copy {age} days ago")
    r.check(G, "Backup", backup)


def _loops(rt, con, r: Run, now: datetime) -> None:
    G = "Loops and money"
    from pflab.paper import cadence

    def silent():
        s = cadence.silent_loops(con, now)
        return (OK, "every loop of the paper portfolio has acted within its interval") if not s else (BAD, "; ".join(s)[:300])
    r.check(G, "Paper loops", silent)

    def jobs():
        bad = con.execute("SELECT job, max(started_at) FROM job_runs WHERE status='failed' AND started_at >= ? GROUP BY 1", [now - timedelta(days=1)]).fetchall()
        ok_after = {j for (j,) in con.execute("SELECT DISTINCT job FROM job_runs WHERE status IN ('ok','skipped') AND started_at >= ?", [now - timedelta(hours=18)]).fetchall()}
        still = [j for j, _ in bad if j not in ok_after]
        return (OK, "no job is failing") if not still else (BAD, f"failing: {', '.join(sorted(still))[:200]}")
    r.check(G, "Jobs", jobs)

    def spend():
        from pflab.agents import analyst as an
        cfg = an.config()
        spent = an.month_spend_inr(con, now)
        cap = float(cfg.get("cap") or 0)
        if not cap:
            return WARN, "no cap is set"
        pct = spent / cap
        return (OK if pct < 0.8 else WARN, f"Rs {spent:,.0f} of Rs {cap:,.0f} this month")
    r.check(G, "API spend", spend)


# --- the job and the summary -------------------------------------------------------------------------------------------------------------------

def latest(con) -> dict:
    """The newest run, grouped, for the screen."""
    rid = con.execute("SELECT max(run_id) FROM selfchecks").fetchone()[0]
    if rid is None:
        return {"run": None, "groups": [], "counts": {OK: 0, WARN: 0, BAD: 0}}
    rows = con.execute("SELECT grp, name, status, note, logged_at FROM selfchecks WHERE run_id=? ORDER BY check_id", [rid]).fetchall()
    groups = []
    for g in GROUPS:
        items = [{"name": n, "status": s, "note": nt} for gg, n, s, nt, _ in rows if gg == g]
        if items:
            groups.append({"title": g, "ok": sum(1 for i in items if i["status"] == OK), "total": len(items), "bad": sum(1 for i in items if i["status"] == BAD), "items": items})
    counts = {s: sum(1 for x in rows if x[2] == s) for s in (OK, WARN, BAD)}
    return {"run": {"id": int(rid), "at": str(rows[0][4])[:16]}, "groups": groups, "counts": counts, "total": len(rows)}


def job(ctx) -> dict:
    """The nightly job (every day, 02:10) and the button: run everything, alert on what failed, keep the rows."""
    from pflab.hq import desk
    rt = desk.from_ctx(ctx)
    out = run_all(rt, ctx.now)
    if out[BAD]:
        try:
            from pflab.app import assistant
            names = [f"{x['grp']}: {x['name']}" for x in out["rows"] if x["status"] == BAD][:6]
            assistant.notify(ctx.con, ctx.now, f"{out[BAD]} self-check(s) failed: " + "; ".join(names), f"selfcheck:{ctx.now:%Y%m%d}")
        except Exception:
            pass
    return {k: out[k] for k in ("run_id", OK, WARN, BAD, "total")}
