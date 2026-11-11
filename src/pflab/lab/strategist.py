"""The strategist (S80 phase 2): one long Opus session that decides by writing and testing policies. It reads the book card, states a hypothesis, writes policy variants, runs them through
the lab in the sandbox, keeps or drops each, and writes a short note that is the next session's memory. It never trades and cannot promote: a challenger is promoted by code
(`promotion.py`) when it clears the registered rules.

Money is tied to outcomes: a session that ends with no lab run is logged `wasted` and the next one gets half the budget until one succeeds; if after `weeks_to_win` weeks no AI-written
variant has cleared the screen against the plain baseline, the budget halves and he is told. Every call goes through `hq/llm.call` (priced first, egress-checked, governed, logged
in `api_calls` under the agent `strategist`). Local data never leaves: the model sees the book card, scorecards and policy code, no raw news, filings or price tables.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from pflab import core
from pflab.lab import promotion, service, shadow, tools

SYSTEM = """You are the STRATEGIST of a small personal-portfolio system (a paper book of Indian shares and ETFs). You do not trade. You may name stocks for the picks sleeve through `propose_picks`, each with a thesis; you never write a size, a price or a weight. You otherwise decide by WRITING POLICIES: short Python programs that turn the state of the market and the book into target weights, which code tests in a lab and, if one wins, runs after every market close.

HOW A SESSION GOES
1. Read the BOOK CARD in the first message (the book, risk, forecasts, storylines, the champion and challengers with scores, recent decisions, what changed) and your own earlier NOTES.
2. State ONE hypothesis in a line: what to lean on and why it should add return after tax and charges or cut the worst fall.
3. Call toolkit_help once, then write_policy: one or more variants. A variant may declare PARAMS = {name: [values]} so one file tests a grid; keep policies simple (a rule of ten lines beats a clever one: every combination you try counts as a trial and raises the bar).
4. run_lab on it. Read the scorecard honestly: the baseline's row is beside yours; "shuffled_beat_it_share" is the luck measure (the share of runs with the signal's information destroyed that did as well); "deflated_sharpe" already corrects for how many variants were tried.
5. Keep, edit (a NEW id with parent set) or drop each variant. make_challenger for the ones worth watching live (they then shadow the champion every close for 20 sessions); retire the rest.
6. THE PICKS STEP (every weekly session, and whenever the first message says so; both markets, India and US). The first message holds the PICKS SCORE (each pick, sale and skipped idea scored after tax against the index) and the PICKS section with each market's share of the sleeve and the room left under it: those numbers come from code, take them as they are. Then: (a) read the scorecard and what it taught; (b) `withdraw_pick` what is broken (its thesis no longer holds: say why); (c) `screen_stocks` for the market, and read a few `company_card`s; (d) `propose_picks` with a thesis, what would break it and the storylines each rests on (60+ characters of thesis, and once five picks have a score, `learned_from`: what the scorecard taught you); no room under the share means no new picks; (e) `skip_idea` for the ones you looked at and left, so the scorecard can tell whether skipping was right. Past returns of a screen are a description, not evidence (US history is survivorship-biased). Code refuses a pick that breaks a rail or the liquidity floor and says why.
7. write_note (what you tried, what won, what you learned; `learned` is required once five picks have a score), then finish.

STORYLINES AND VIEWS. Open storylines (a cause-and-effect hypothesis with signals chosen from a menu) are in the book card; `storylines` shows them in full. You may open one, or adjust a probability with a written reason (bounded). A policy can read them as numbers through `storylines` in its state. For news that cannot wait for the lab you may issue a VIEW with `issue_view`: a direction, 1 to 6 symbols, a share of the TACTICAL budget, a horizon and a stop; code sizes it inside the rails and scores it. Your own view record is in the book card: do not issue views to look busy.

RULES THAT CANNOT BE BENT
- Every number comes from code. You never write a size, a price or a weight into a decision: you write rules, and you name stocks with reasons (`propose_picks`); code sizes, buys, sells and scores them.
- A policy has no network, no files, no clock; only the toolkit, numpy and pandas. Code outside the policy holds the rails (a company 10%, a sector 25%, an ETF 35%, no borrowing, no shorting), the circuit breaker and the turnover caps: you cannot change them.
- You cannot promote and you cannot see the 2018-2021 final check; code runs it once, later. Do not try to overfit the history: a variant that wins only by luck will fail the shuffled-signal measure and the live shadow. Trading the book also needs the history to pass the INDEX RULE (the `index_rule` in compare), after tax and charges on both sides (the index is held as an ETF with its own cost and the tax of a buy-and-hold): the return lag at most 2 points a year with a worst fall no deeper than the index's, OR the lag at most 4 points a year with a worst fall at least a third smaller. It never stops you trying anything; a variant that clears it and the once-only final check trades a probation slice of 5% of the book, which grows to 10% and 20% while its live record is not worse than the champion's and is withdrawn when it is worse.
- THE ALLOCATION IS YOURS. The book is a CORE (index, gold and international ETFs) plus satellite sleeves (longterm stock picks; there is no swing sleeve: its study failed). Every weekly session re-examine it (the first message shows it): call `propose_allocation` with classes, sleeve shares, sectors and reasons to change it, or propose the same split again to record that it stands. Code enforces the rails and the sleeve caps (swing at most 20%, longterm at most 60%, core at least 30%). Your proposal runs in the lab like any policy (`alloc_t<id>`); "hold the index" and the starting split are always in the lab, and code adopts a proposal only when it passes the index rule and the final check and is not below what is in force. New cash and sale proceeds go to the core first; stocks are never sold just to reach a sleeve share.
- The money is limited. Plan the session: a few well-chosen variants, one run each. If you run out of budget the session ends where it is.
- A session that ends with no lab run and no pick named, withdrawn or skipped is logged as wasted and your next budget is halved.
Reply in short plain sentences between tool calls. Do not re-describe tool results at length."""


def settings() -> dict:
    return core.settings()["strategist"]


# --- budget and triggers ----------------------------------------------------------------------------------------------------------

def beat_baseline(con) -> bool:
    """Has any AI-written variant cleared the registered screen against the plain baseline on the history window?"""
    base = service.latest_run(con, service.BASELINE_ID, "history")
    if base is None:
        return False
    for (pid,) in con.execute("SELECT policy_id FROM core_policies_s80 WHERE session_id IS NOT NULL").fetchall():
        if pid in (service.BASELINE_ID, "baseline_v1"):
            continue
        r = service.latest_run(con, pid, "history")
        if r and service.screen(r["score"], r["shuffled"], base["score"])["ok"]:
            return True
    return False


def weeks_without_win(con, now: datetime) -> Optional[float]:
    first = con.execute("SELECT min(started_at) FROM core_sessions_s80").fetchone()[0]
    if first is None or beat_baseline(con):
        return None
    return (now - first).days / 7.0


def session_budget(con, now: datetime) -> dict:
    """What one session may spend: the base, halved after a wasted session (until one succeeds) and halved when 8 weeks passed with no AI-written variant clearing the baseline."""
    st = settings()
    b, why = float(st["session_rupees"]), []
    applied = core.throttle_active(now)                      # A55: function first: the halving rules are recorded but not applied before `[strategist] throttle_after`
    note = "" if applied else f" (recorded, NOT applied before {settings().get('throttle_after')}: function first, A55)"
    last = con.execute("SELECT status FROM core_sessions_s80 WHERE finished_at IS NOT NULL ORDER BY session_id DESC LIMIT 1").fetchone()
    if last and last[0] == "wasted":
        if applied:
            b /= 2
        why.append("the last session ran no lab run: half the budget until one does" + note)
    w = weeks_without_win(con, now)
    if w is not None and w >= float(st["weeks_to_win"]):
        if applied:
            b /= 2
        why.append(f"{w:.0f} weeks and no AI-written variant has cleared the baseline: the budget is halved" + note)
    return {"rupees": b, "why": why, "throttle_applied": applied}


def due(con, now: datetime) -> List[str]:
    """Reasons for a session now (never a bare timer with nothing to work on, but the weekly one is the doc's own first trigger)."""
    st = settings()
    out = []
    try:                                                                    # S81 B6: what he asked in the chat comes first, then the S81 triggers
        from pflab.lab import ondemand, triggers_s81
        out += ondemand.reasons(con) + triggers_s81.reasons(con, now)
    except Exception:
        pass
    last = con.execute("SELECT max(started_at) FROM core_sessions_s80").fetchone()[0]
    if last is None or (now - last) >= timedelta(days=int(st["weekly_days"])):
        out.append("the weekly session (re-examine the allocation)")
    for (pid,) in con.execute("SELECT policy_id FROM core_policies_s80 WHERE status='challenger'").fetchall():
        rec = shadow.record(con, pid)
        if rec["sessions"] >= service.SHADOW_SESSIONS:
            r = service.latest_run(con, pid, "history")
            base = service.latest_run(con, service.BASELINE_ID, "history")
            if r and base and service.screen(r["score"], r["shuffled"], base["score"])["ok"]:
                out.append(f"challenger {pid} has {rec['sessions']} shadow sessions and cleared the history screen: ready for the promotion check")
    row = con.execute("SELECT state_json FROM core_runs_s80 ORDER BY day DESC LIMIT 1").fetchone()
    if row:
        try:
            if json.loads(row[0]).get("gauge", {}).get("fired") and not _recent_gauge_session(con, now):
                out.append("the fall gauge fired")
        except Exception:
            pass
    try:                                                                    # a storyline crossed a set probability since the last session
        last_start = last or datetime(1970, 1, 1)
        for sid, p in con.execute("SELECT s.storyline_id, s.probability FROM storylines_s80 s WHERE s.status='open' AND (s.probability >= 0.75 OR s.probability <= 0.25) "
                                  "AND s.updated_at >= ?", [last_start]).fetchall():
            out.append(f"storyline #{sid} is at {p:.0%}")
    except Exception:
        pass
    try:                                                                    # the champion behind the baseline: the book's result against its own benchmark over the last 20 sessions
        from pflab.paper import benchmark
        b = benchmark.status(con, "IN")
        if b.get("started") and b.get("sessions", 0) >= 20 and (b.get("excess") or 0.0) < -0.05:
            out.append(f"the book is {b['excess']:+.1%} against its own benchmark")
    except Exception:
        pass
    return out


def _recent_gauge_session(con, now: datetime) -> bool:
    r = con.execute("SELECT 1 FROM core_sessions_s80 WHERE reason LIKE '%fall gauge%' AND started_at >= ? LIMIT 1", [now - timedelta(days=5)]).fetchone()
    return bool(r)


# --- the session ------------------------------------------------------------------------------------------------------------------

def _first_message(con, reason: str, budget: float, now: Optional[datetime] = None) -> str:
    from pflab.core import card
    c = card.latest(con) or "(no book card yet: the close loop has not run)"
    notes = service.notes(con, 3)
    now = now or datetime.now()
    try:
        from pflab.lab import alloc_lab
        alloc = alloc_lab.status_text(con, datetime.now()) + "\n\n"
    except Exception:
        alloc = ""
    try:                                                                    # S83 L3: the picks scorecard and the picks sleeve (fresh, both markets), beside the allocation status
        from pflab.core import pick_score, picks_card
        alloc += ("PICKS SCORE (code; after estimated tax, against the index):\n" + "\n".join(pick_score.scorecard_text(con, m) for m in ("IN", "US"))
                  + "\n\n" + picks_card.build(con, now.date())["text"] + "\n\n")
    except Exception as e:
        alloc += f"PICKS: unreadable now ({type(e).__name__})\n\n"
    return (f"WHY THIS SESSION: {reason}\nBUDGET: about Rs {budget:,.0f} for the whole session (it ends when it is used).\n"
            f"TRIALS SO FAR: {service.n_trials(con)} variants (each raises the bar for the next).\n\n{c}\n\n{alloc}"
            "YOUR EARLIER NOTES (newest first):\n" + ("\n".join(f"- ({n['at']}) {n['text']}" + (f" [learned: {n['learned']}]" if n.get("learned") else "") for n in notes) if notes else "none yet: this is the first session.")
            + "\n\nBegin: state your hypothesis, then work.")


def run_session(con, pm_dir: Path, root, now: datetime, reason: str, *, client, gate=None, cfg: Optional[dict] = None, data=None, box=None, budget_inr: Optional[float] = None) -> dict:
    """One strategist session. Returns {session_id, status (done | wasted | budget | failed), cost_inr, lab_runs, ...}."""
    from pflab.agents import analyst as an
    from pflab.hq import converse, egress, llm
    from pflab.pm.store import next_id
    if not core.strategist_on():
        return {"skipped": "the strategist is switched off (configs/core.toml [strategist] or the kill switch)"}
    st = settings()
    service.ensure_baseline(con, now)
    sb = session_budget(con, now)
    budget = float(budget_inr if budget_inr is not None else sb["rupees"])
    if budget < float(st["min_session_rupees"]):
        return {"skipped": f"the session budget (Rs {budget:,.0f}) is under the minimum"}
    cfg = cfg or an.config()
    gate = gate or egress.load(con)
    sid = next_id(con, "core_sessions_s80", "session_id")
    con.execute("INSERT INTO core_sessions_s80 (session_id, started_at, reason, status, model, budget_inr, cost_inr, lab_runs, variants, challengers) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [sid, now, reason[:300], "running", st["model"], budget, 0.0, 0, 0, 0])
    req_ids: list = []
    try:
        from pflab.lab import ondemand
        if ondemand.PREFIX in reason:
            req_ids = ondemand.take(con, now, sid)
    except Exception:
        pass
    ctx = tools.make_ctx(con, pm_dir, root, now, sid, data=data, box=box)
    first = _first_message(con, reason, budget, now)
    messages = [{"role": "user", "content": [{"type": "text", "text": first}]}]
    sys_blocks = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
    spent, status, err, log = 0.0, "done", None, []
    for turn in range(1, int(st["max_turns"]) + 1):
        if spent >= budget:
            status = "budget"
            break
        p = {"model": st["model"], "max_tokens": 6000, "system": sys_blocks, "thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"},
             "tools": tools.definitions(), "messages": messages, "cache_control": {"type": "ephemeral"}}
        if turn == int(st["max_turns"]) or ctx.finished:
            p["tool_choice"] = {"type": "none"}
        try:
            s = llm.call(con, "strategist", p, client, now=now, mode="normal", private_text=first if turn == 1 else "", gate=gate, doc_kinds=("portfolio",), topic="strategist",
                         question=f"strategist session {sid}, turn {turn}", cfg=cfg, turn=turn, egress_skip=("address_word",))
        except Exception as e:                                           # refused, blocked or failed: the session ends here, with what it has
            status, err = "failed", f"{type(e).__name__}: {str(e)[:300]}"
            break
        spent += s.cost_inr
        msg = s.message
        uses = [b for b in msg.content if getattr(b, "type", "") == "tool_use"]
        if getattr(msg, "stop_reason", "") != "tool_use" or not uses:
            log.append({"turn": turn, "says": llm.text_of(msg)[:400]})
            break
        messages.append({"role": "assistant", "content": [converse.as_param(b) for b in msg.content if getattr(b, "type", "") in converse.KEEP_BLOCKS]})
        results = []
        for b in uses:
            text, is_err = tools.run(ctx, b.name, b.input)
            log.append({"turn": turn, "tool": b.name, "ok": not is_err, "result": text[:240]})
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": text, **({"is_error": True} if is_err else {})})
        if spent >= 0.8 * budget and not ctx.finished:
            results.append({"type": "text", "text": f"Budget note: about Rs {spent:,.0f} of Rs {budget:,.0f} is used. Write your note and finish now."})
        messages.append({"role": "user", "content": results})
        if ctx.finished:
            break
    if ctx.stats["notes"] == 0 and (ctx.stats["variants"] or ctx.stats["lab_runs"] or ctx.stats["picks"]):       # a session that worked but wrote no note leaves a code-written one
        service.write_note(con, now, sid, f"(written by code) Session {sid}: {ctx.stats['variants']} variant(s) written, {ctx.stats['lab_runs']} lab run(s), "
                                          f"{ctx.stats['challengers']} challenger(s), {ctx.stats['picks']} pick action(s). The strategist's own summary: {ctx.finished or 'none'}")
    final = status if status in ("failed",) else ("wasted" if ctx.stats["lab_runs"] == 0 and not ctx.stats["picks"] and not ctx.stats["skips"] else ("budget" if status == "budget" else "done"))
    con.execute("UPDATE core_sessions_s80 SET finished_at=?, status=?, cost_inr=?, lab_runs=?, variants=?, challengers=?, note=?, transcript_json=? WHERE session_id=?",
                [now, final, spent, ctx.stats["lab_runs"], ctx.stats["variants"], ctx.stats["challengers"], (err or ctx.finished or "")[:600], json.dumps(log)[:60000], sid])
    if req_ids:
        try:
            from pflab.lab import ondemand
            ondemand.finish(con, now, req_ids, final, (err or ctx.finished or "no note was written")[:800])
        except Exception:
            pass
    out = {"session_id": sid, "status": final, "cost_inr": round(spent, 2), "budget_inr": budget, "turns": len([x for x in log if "tool" in x or "says" in x]), **ctx.stats}
    if final == "wasted":
        out["note"] = ("no lab run: logged as wasted, the next session gets half the budget until one succeeds" if core.throttle_active(now)
                       else f"no lab run: logged as wasted (the halving rule is recorded, not applied before {st.get('throttle_after')})")
    w = weeks_without_win(con, now)
    if w is not None and w >= float(st["weeks_to_win"]) and core.throttle_active(now):
        _tell(con, now, f"The strategist has run for {w:.0f} weeks without an AI-written variant clearing the plain baseline; its budget is halved.", f"strategist8w:{now:%Y%m%d}")
    return out


def _tell(con, now: datetime, text: str, key: str) -> None:
    try:
        from pflab.app import assistant
        assistant.notify(con, now, text, key)
    except Exception:
        pass


def tick(con, pm_dir: Path, root, now: datetime, client_fn, data=None, box=None) -> dict:
    """The job's body: rollback check, promotion check, and a session when there is a reason and room. `client_fn()` makes the SDK client only when a session will really run."""
    out: dict = {}
    if not core.strategist_on():
        return {"off": True}
    rb = promotion.rollback_check(con, now)
    if rb:
        out["rollback"] = rb
    try:                                                                    # S81 (A49-A50): the allocation candidates are replayed and a proposal is adopted by the index rule (code, free)
        from pflab.lab import alloc_lab
        out["allocation"] = alloc_lab.tick(con, pm_dir, root, now, data=data, box=box)
    except Exception as e:
        out["allocation"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    reasons = due(con, now)
    try:                                                                    # S82 C9: the once-only first real session in the app (kept out of `due`, which is the weekly rule's own)
        from pflab.lab import first_session_s82
        reasons = reasons + first_session_s82.reasons(con, now)
    except Exception:
        pass
    if not reasons:
        return {**out, "nothing_due": True}
    try:                                                                    # S82 C9: the first session waits (recorded, tried at a later open) when the paid cap has no room
        from pflab.lab import first_session_s82 as first
        if first.is_first(reasons):
            try:                                                            # S83 L8: his Kite stocks are adopted as picks at the first open (idempotent; also done by the close loop)
                from pflab.core import picks
                if picks.on("IN"):
                    picks.adopt_kite_holdings(con, now)
            except Exception:
                pass
            rm = first.room(con, now)
            if not rm["ok"]:
                keys = first.keys_in(reasons)
                reasons = [r for r in reasons if r not in first.KEYS]
                first.waiting(con, now, rm["why"], keys=keys)
                out["first_session_s82"] = "waiting: " + rm["why"]
                if not reasons:
                    return out
    except Exception:
        pass
    out["reasons"] = reasons
    try:                                                                    # no client (the workshop's paid-call guard, no key, a bad key): the session waits and says why; the job does not fail
        client = client_fn()
    except Exception as e:
        out["skipped"] = f"no cloud client, so no session now ({type(e).__name__}: {str(e)[:200]})"
        try:
            from pflab.lab import first_session_s82 as first
            if first.is_first(reasons):
                first.waiting(con, now, "no cloud client (no API key, or the workshop's paid-call guard)", keys=first.keys_in(reasons))
        except Exception:
            pass
        return out
    out["session"] = run_session(con, pm_dir, root, now, "; ".join(reasons)[:700], client=client, data=data, box=box)
    try:
        from pflab.lab import first_session_s82 as first
        if first.is_first(reasons):
            out["first_session_s82"] = first.after_session(con, now, out["session"], keys=first.keys_in(reasons))
    except Exception:
        pass
    return out


# --- what the screen shows (spend tied to outcomes) --------------------------------------------------------------------------------

def spend_report(con, now: datetime) -> dict:
    """Rupees this month by use, lab runs, challengers and promotions per Rs 100, and the champion's score against the plain baseline."""
    from pflab.agents import analyst as an
    start = an.month_start(now)
    by = {r[0]: float(r[1]) for r in con.execute("SELECT agent, coalesce(sum(cost_inr),0) FROM api_calls WHERE created_at >= ? AND status IN ('done','refused','submitted','queued','sending') "
                                                  "AND agent IN ('strategist','checker','escalation') GROUP BY 1", [start]).fetchall()}
    total = sum(by.values())
    runs = con.execute("SELECT count(*) FROM lab_runs_s80 WHERE ran_at >= ? AND policy_id <> ?", [start, service.BASELINE_ID]).fetchone()[0]
    chal = con.execute("SELECT coalesce(sum(challengers),0) FROM core_sessions_s80 WHERE started_at >= ?", [start]).fetchone()[0]
    promos = con.execute("SELECT count(*) FROM core_promotions_s80 WHERE happened_at >= ? AND kind='promote'", [start]).fetchone()[0]
    per = lambda n: None if total < 1 else round(100.0 * n / total, 2)
    champ = shadow.champion_row(con)
    base = service.latest_run(con, service.BASELINE_ID, "history")
    ch = service.latest_run(con, champ["policy_id"], "history", champ["params"]) if champ and champ["code"] else None
    return {"month_rupees": {"strategist": round(by.get("strategist", 0.0), 2), "checker": round(by.get("checker", 0.0), 2), "escalation": round(by.get("escalation", 0.0), 2), "total": round(total, 2)},
            "lab_runs": runs, "challengers_added": int(chal), "promotions": promos, "lab_runs_per_100_rupees": per(runs), "challengers_per_100_rupees": per(chal), "promotions_per_100_rupees": per(promos),
            "champion": champ["policy_id"] if champ else None,
            "champion_vs_baseline": None if not (base and ch) else {"champion_cagr": round(ch["score"]["cagr"], 4), "baseline_cagr": round(base["score"]["cagr"], 4)},
            "budget": session_budget(con, now)}
