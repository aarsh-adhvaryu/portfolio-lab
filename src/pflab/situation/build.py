"""Building the situation of a market at a date, and the report from it (S79b item 16).

    build.run(rt_or_con, market, as_of, now, mode)       callable for any past date, point-in-time (only claims dated <= as_of; tools given the date)

One run: check the watch triggers (a fired one is an event on the stream and a flag), run the adapters (each tool by name, a missing one is skipped), read the live
claims, find the disagreements, make the scenarios, then synthesize (full, short, or code only), check, store, write chains to the graph, store the predictions,
carry out ACT. Nothing here makes a paid call; the model is the local THINKER.

    plan(...)  full    pre_open, post_close, any flag (a fired trigger, a wave or rotation claim newer than the last report)
               short   session mode, flagged or after intraday_minutes
               code    deep mode when a full report for the date already exists (claims refreshed, no model)
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from pflab import _toml
from pflab.pm.store import next_id
from pflab.situation import adapters as AD, chains as CH, claims as C, report as R, score as SC, synth, watch as W

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "s79b.toml"
DEFAULTS = {"on": True, "model": True, "paper_requests": True, "paper_requests_per_day": 1, "questions": True, "questions_per_day": 1, "short_intraday": True,
            "intraday_minutes": 90, "max_watch": 12, "kg": True}


def config(path: Optional[Path] = None) -> dict:
    try:
        t = _toml.load(path or CONFIG).get("situation", {})
    except (OSError, ValueError):
        t = {}
    return {**DEFAULTS, **t}


def enabled(path: Optional[Path] = None) -> bool:
    return bool(config(path).get("on", True))


def flags_for(con, market: str, as_of: date, since: Optional[datetime]) -> List[str]:
    """Why this run is flag-triggered: fired watch triggers not yet reacted to, and wave or rotation claims newer than the last report."""
    fl = [f"watch fired: {w['text'][:80]}" for w in W.unreacted(con, market)]
    q = "SELECT subject FROM situation_claim WHERE market=? AND kind IN ('wave','rotation') AND coalesce(value,0)<>0 AND as_of<=? AND expires_on>=?" + (" AND created_at>?" if since else "")
    for (s,) in con.execute(q, [market, as_of, as_of, *([since] if since else [])]).fetchall():
        fl.append(f"{s} flagged")
    return fl


def plan(mode: str, flags: Sequence[str], con, market: str, as_of: date, now: datetime, cfg: dict) -> str:
    if not cfg.get("model", True):
        return "code"
    if mode in ("pre_open", "post_close") or flags:
        return "full" if mode != "session" else "short"
    if mode == "session":
        if not cfg.get("short_intraday", True):
            return "code"
        last = con.execute("SELECT max(created_at) FROM situation_report WHERE market=? AND as_of=? AND coded_only=FALSE", [market, as_of]).fetchone()[0]
        return "short" if last is None or now - last >= timedelta(minutes=int(cfg.get("intraday_minutes", 90))) else "code"
    have = con.execute("SELECT 1 FROM situation_report WHERE market=? AND as_of=? AND coded_only=FALSE LIMIT 1", [market, as_of]).fetchone()       # deep
    return "code" if have else "full"


def run(rt_or_con, market: str = "IN", as_of: Optional[date] = None, now: Optional[datetime] = None, mode: Optional[str] = None, flags: Sequence[str] = (),
        chat: Optional[Callable[[str, str, dict], str]] = None, use_model: bool = True, root: Optional[Path] = None, cfg: Optional[dict] = None, force: Optional[str] = None) -> dict:
    """Build the situation and write the report. `as_of` may be any past session (point-in-time). `chat(system, user, schema) -> JSON text` replaces the local model (tests).
    `force` is 'full', 'short' or 'code'. Returns {'report_id', 'text', 'sections', 'coded_only', 'sources', 'n_claims', 'plan', ...} or {'off': True}."""
    from pflab import markets
    cfg = cfg or config()
    if not cfg.get("on", True):
        return {"off": True}
    rt = AD.as_rt(rt_or_con, now)
    con = rt.cursor()
    now = now or rt.clock()
    mk = markets.get(market)
    mode = mode or markets.modes(now).get(market, "deep")
    as_of = as_of or (mk.session_closed_by(now) if mode in ("post_close", "deep") else mk.last_session_on_or_before(now.date()))
    live = as_of >= mk.last_session_on_or_before(now.date())
    root = Path(root) if root else Path(rt.data_root)
    run_id = next_id(con, "situation_run", "run_id")
    con.execute("INSERT INTO situation_run (run_id, market, as_of, mode, started_at) VALUES (?,?,?,?,?)", [run_id, market, as_of, mode, now])

    fired = W.check(con, market, as_of, now, root=root) if live else []
    last = con.execute("SELECT max(created_at) FROM situation_report WHERE market=?", [market]).fetchone()[0] if live else None
    fl = list(flags) + (flags_for(con, market, as_of, last) if live else [])
    fl += [f"watch fired just now: {w['text'][:80]}" for w in fired]

    runner = AD.Runner(rt, market, as_of, now, run_id=run_id)
    sources = AD.run_all(runner)
    claims = C.active(con, market, as_of)
    by_id = {c["claim_id"]: c for c in claims}
    cons = R.detect_contradictions(claims)
    cands = R.next_candidates(claims)
    pl = force or (plan(mode, fl, con, market, as_of, now, cfg) if use_model else "code")
    dr = None
    if pl in ("full", "short") and use_model:
        wl = sorted({c["subject"][len("level_"):] for c in claims if c["subject"].startswith("level_")})
        use = [c for c in claims if pl == "full" or c["kind"] in ("regime", "wave", "rotation", "move", "macro", "transmission", "sentiment", "event", "exposure", "book", "forecast", "fall_risk")]
        dr = synth.draft(market, as_of, mode, use, cons, cands if pl == "full" else [], wl, short=(pl == "short"), chat=chat, headline=R.headline(claims))
    sec, rejected, coded_only = R.assemble(claims, cons, cands, dr, sorted({c["subject"][len("level_"):] for c in claims if c["subject"].startswith("level_")}))
    model = synth.thinker_model() if dr and "error" not in dr else ""
    if dr and "error" in dr:
        rejected.append({"sentence": "(the model)", "why": dr["error"], "section": "model"})
    text = R.render(market, as_of, mode, sec, coded_only or not dr or "error" in (dr or {}), model, fl, sources)
    coded_only = coded_only or not dr or "error" in (dr or {})
    rid = R.store(con, market, as_of, mode, now, sec, text, coded_only, model, len(claims), [*sources, *runner.log[:0]], fl, rejected)
    # contradictions to the table and the agenda; chains to the table and the graph; predictions for scoring
    if live:
        R.store_contradictions(con, rid, market, as_of, cons, now)
    else:
        for c in cons:
            c.update(contradiction_id=None, agenda_item_id=None)
    chain = sec.get("chain") or {"links": [], "ok": False, "types": []}
    chain_id = None
    if chain["links"]:
        chain_id = CH.store(con, rid, market, as_of, chain, now)
        if cfg.get("kg", True) and chain["ok"]:
            try:
                CH.to_kg(con, chain_id, chain, by_id, market, now)
            except Exception as e:
                rejected.append({"sentence": "(knowledge graph)", "why": f"{type(e).__name__}: {str(e)[:100]}", "section": "kg"})
    ctype = ",".join(chain.get("types") or []) or "none"
    preds = [pid for pid in (SC.store_prediction(con, rid, market, as_of, c, ctype, now) for c in cands) if pid]
    done = R.carry_out(con, market, as_of, now, rid, sec, cfg, coded_only, root=root) if live else {"note": "past date: no effects carried out"}
    con.execute("UPDATE situation_run SET finished_at=?, report_id=?, n_claims=?, sources=?, note=? WHERE run_id=?",
                [datetime.now() if live else now, rid, len(claims), json.dumps(sources), f"{pl}; {len(fl)} flag(s)", run_id])
    return {"report_id": rid, "run_id": run_id, "market": market, "as_of": str(as_of), "mode": mode, "plan": pl, "text": text, "sections": sec, "coded_only": coded_only,
            "model": model, "sources": sources, "tool_log": runner.log, "n_claims": len(claims), "flags": fl, "rejected": rejected, "predictions": preds, "chain_id": chain_id,
            "acted": done, "contradictions": cons}


def due(con, market: str, now: datetime) -> Optional[str]:
    """Why a run is due now (None: not). Inputs newer than the last run: a closed session without a report, new fcast or prices after the last report, or a flag."""
    from pflab import markets
    mk = markets.get(market)
    closed = mk.session_closed_by(now)
    r = con.execute("SELECT max(as_of), max(created_at) FROM situation_report WHERE market=?", [market]).fetchone()
    if r[0] is None or r[0] < closed:
        return f"{market}: session {closed} closed, last report {r[0]}"
    for job in ("forecast_loop", "prices", "global", "catch_up"):
        j = con.execute("SELECT max(finished_at) FROM job_runs WHERE job=? AND status='ok'", [job]).fetchone()[0]
        if j is not None and r[1] is not None and j > r[1]:
            return f"{market}: {job} finished after the last report"
    if W.unreacted(con, market):
        return f"{market}: a watch trigger fired"
    return None
