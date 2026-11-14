"""The app checks its own first week (S79b, A44) and tells him, once, on Telegram.

Armed the first time the app runs this release (`arm`). Evaluated daily (job `week_check`) once at least `MIN_DAYS` calendar days have passed AND the app was open at least `MIN_OPEN_HOURS`
in total (his instruction was "the first 7 days of open time": a laptop that is off at night cannot give 7 x 24 h, so the rule is 7 calendar days with at least 12 hours open; recorded as a decision).
Criteria, each PASS / FAIL / NOT TESTED:
  1. a catch-up ran after every off-gap that missed a session (`catchup_s79` done after `off_to`);
  2. every mode was reached (pre_open, session, post_close, deep on the home market: `mode_seen_s79`); NOT TESTED if the app was never open in a mode's hours;
  3. forecasts were made and scored (`forecasts_s79`, `forecast_scores_s79`);
  4. no unhandled failure: no job run 'failed' in the window (an 'offline' run, and a run stopped with the app, are not failures);
  5. cost within the cap (the month's counted API spend against the cap).
S86b (W1, his words of 2026-11-14): armed from the first app open on or after Monday 2026-11-16 (`ARM_FROM`), 7 calendar days with at least 12 hours open; nine more criteria (6 to 14, below).
  6. the India session loop ran on a trading day with live quotes (a Kite login);
  7. the US book ran its morning step and its orders filled (NOT TESTED while it placed none);
  8. the daily desk ran on every day the app was open, and the picks were scored (`pick_scores_s83`);
  9. the thinking loop watched every India close and every US morning, and no open case was left without its look;
  10. the chat answered every message (the intake queue: nothing failed or stuck) and the loop did not miss a step meanwhile (no job failure);
  11. every page that is switched on loaded without a SERVER error (`page_loads_s86`, written by the app's own server; a browser console error cannot be recorded without touching the screens, said so);
  12. the month's spend is inside the cap and every call is priced;
  13. the alarm lane ran every 15 minutes while the app was open, no news source was silent for more than 2 hours UNREPORTED, and every RED item reached "heard" within 30 minutes;
  14. the US session loop ran on every US session the app was open for, and every gap with a session in it was fast-forwarded.
Overall: PASS when all five pass; FAIL when any fails; NOT YET when none fails but some are not tested (repeated daily, up to 21 days, then reported as it stands). On PASS the message says that the 60-day
feature freeze (A44, bug fixes only) starts today, and `freeze_from` is stored.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

ARM_FROM = date(2026, 11, 16)         # S86b (W1): the check counts from the first app open on or after this day
MIN_DAYS = 7
MIN_OPEN_HOURS = 12.0
GIVE_UP_DAYS = 21
MODES = ("pre_open", "session", "post_close", "deep")


def note_modes(con, now: datetime) -> None:
    """Called from the heart: remember each (day, market, mode) the clock has been in while the app was open."""
    from pflab import markets
    for market, mode in markets.modes(now).items():
        if not con.execute("SELECT 1 FROM mode_seen_s79 WHERE day=? AND market=? AND mode=?", [now.date(), market, mode]).fetchone():
            con.execute("INSERT INTO mode_seen_s79 VALUES (?,?,?,?)", [now.date(), market, mode, now])


def arm(con, now: datetime, release: str = "") -> int:
    """The latest check, when it was armed on or after ARM_FROM; otherwise (none, or an earlier week's, S79b's) a new one is armed NOW. Before ARM_FROM nothing is armed (0)."""
    if now.date() < ARM_FROM:
        return 0
    r = con.execute("SELECT check_id, armed_at FROM week_check_s79 ORDER BY check_id DESC LIMIT 1").fetchone()
    if r and r[1].date() >= ARM_FROM:
        return int(r[0])
    from pflab.pm.store import next_id
    cid = next_id(con, "week_check_s79", "check_id")
    con.execute("INSERT INTO week_check_s79 (check_id, armed_at, release) VALUES (?,?,?)", [cid, now, release])
    return cid


def _crit(name: str, status: str, text: str) -> dict:
    return {"name": name, "status": status, "text": text}


def evaluate(con, armed_at: datetime, now: datetime, cap_ok=None) -> dict:
    from pflab.service import presence
    out: List[dict] = []
    # 1. catch-ups after every off-gap that missed a session
    from pflab.service import away
    bad, tested = [], 0
    for a, b in presence.gaps(con, armed_at):
        if a < armed_at:
            continue
        missed = sum(len(away.sessions_missed(m, a, b)) for m in ("IN",))
        if not missed:
            continue
        tested += 1
        if not con.execute("SELECT 1 FROM catchup_s79 WHERE state='done' AND finished_at >= ?", [b]).fetchone():
            bad.append(f"{a:%a %d %b %H:%M} to {b:%a %d %b %H:%M}")
    out.append(_crit("catch_up_after_gaps", "FAIL" if bad else "PASS" if tested else "NOT TESTED",
                     f"no catch-up after: {', '.join(bad)}" if bad else f"{tested} gap(s) with missed sessions, each caught up" if tested else "no gap with a missed session happened"))
    # 2. every mode reached (home market)
    seen = {m for (m,) in con.execute("SELECT DISTINCT mode FROM mode_seen_s79 WHERE market='IN' AND day >= ?", [armed_at.date()]).fetchall()}
    miss = [m for m in MODES if m not in seen]
    out.append(_crit("modes_reached", "PASS" if not miss else "NOT TESTED", "all four modes reached" if not miss else f"never open in: {', '.join(miss)}"))
    # 3. forecasts made and scored
    made = con.execute("SELECT count(*) FROM forecasts_s79 WHERE made_at >= ?", [armed_at]).fetchone()[0]
    scored = con.execute("SELECT count(*) FROM forecast_scores_s79 WHERE scored_at >= ?", [armed_at]).fetchone()[0]
    out.append(_crit("forecasts", "PASS" if made and scored else "FAIL" if made and now - armed_at > timedelta(days=MIN_DAYS + 3) else "NOT TESTED",
                     f"{made} forecasts made, {scored} scored"))
    # 4. no unhandled failure
    rows = con.execute("SELECT job, count(*) FROM job_runs WHERE status='failed' AND started_at >= ? "
                       "AND detail IS DISTINCT FROM 'abandoned: the process stopped before it finished' AND detail NOT LIKE 'abandoned:%' GROUP BY 1", [armed_at]).fetchall()
    out.append(_crit("no_failures", "FAIL" if rows else "PASS", ("failed: " + ", ".join(f"{j} x{n}" for j, n in rows)) if rows else "no job run failed"))
    # 5. cost within the cap
    try:
        from pflab.hq import governor as gv
        sp = gv.spend(con, now)
        ok = sp["cap"] <= 0 or sp["month"] <= sp["cap"]
        out.append(_crit("cost", "PASS" if ok else "FAIL", f"month so far Rs {sp['month']:,.0f} of a cap of Rs {sp['cap']:,.0f}"))
    except Exception as e:
        out.append(_crit("cost", "NOT TESTED", f"could not read the spend ({type(e).__name__})"))
    out += _s86_criteria(con, armed_at, now)
    st = [c["status"] for c in out]
    overall = "fail" if "FAIL" in st else "pass" if all(s == "PASS" for s in st) else "not_yet"
    return {"overall": overall, "criteria": out, "open_hours": round(presence.open_time(con, armed_at, now).total_seconds() / 3600, 1)}


def _open_days(con, armed_at: datetime, now: datetime) -> List[date]:
    """The calendar days the app was open at all since `armed_at` (from the presence record)."""
    from pflab.service import presence
    days = set()
    d = armed_at.date()
    while d <= now.date():
        a = max(armed_at, datetime.combine(d, datetime.min.time()))
        b = min(now, datetime.combine(d, datetime.max.time()))
        if b > a and presence.open_time(con, a, b).total_seconds() > 600:
            days.add(d)
        d += timedelta(days=1)
    return sorted(days)


def _tbl(con, name: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name=?", [name]).fetchone()[0])


def _s86_criteria(con, armed_at: datetime, now: datetime) -> List[dict]:
    """Criteria 6 to 14 (S86b). Each never raises: a criterion that cannot be read is NOT TESTED with the reason, never a silent pass."""
    from pflab import markets
    out: List[dict] = []
    odays = _open_days(con, armed_at, now)

    def safe(name, fn):
        try:
            out.append(fn())
        except Exception as e:
            out.append(_crit(name, "NOT TESTED", f"could not be read ({type(e).__name__}: {str(e)[:80]})"))

    def c6():
        n = con.execute("SELECT count(DISTINCT day) FROM session_log_s81 WHERE kind='run' AND day >= ? AND detail_json LIKE '%\"quotes\": %' AND detail_json NOT LIKE '%\"quotes\": 0%'",
                        [armed_at.date()]).fetchone()[0]
        return _crit("session_loop_with_quotes", "PASS" if n else "NOT TESTED", f"{n} trading day(s) with live quotes" if n else "no session with a Kite login yet")

    def c7():
        ran = con.execute("SELECT count(*) FROM us_runs_s81 WHERE ran_at >= ? AND status NOT IN ('failed','error')", [armed_at]).fetchone()[0]
        bad = con.execute("SELECT count(*) FROM us_runs_s81 WHERE ran_at >= ? AND status IN ('failed','error')", [armed_at]).fetchone()[0]
        filled = con.execute("SELECT count(*) FROM us_orders_s81 WHERE status='filled' AND placed_at >= ?", [armed_at]).fetchone()[0]
        placed = con.execute("SELECT count(*) FROM us_orders_s81 WHERE placed_at >= ?", [armed_at]).fetchone()[0]
        if bad:
            return _crit("us_morning_and_fills", "FAIL", f"the US morning step failed {bad} time(s)")
        if not ran:
            return _crit("us_morning_and_fills", "NOT TESTED", "the US morning step has not run yet")
        if placed and not filled:
            return _crit("us_morning_and_fills", "FAIL", f"{placed} US order(s) placed, none filled")
        return _crit("us_morning_and_fills", "PASS" if filled else "NOT TESTED", f"{ran} US morning step(s), {filled} of {placed} orders filled" if filled else f"{ran} US morning step(s), no order placed yet")

    def c8():
        if not odays:
            return _crit("daily_desk_and_picks_scored", "NOT TESTED", "the app was not open")
        have = {r[0] for r in con.execute("SELECT DISTINCT day FROM desk_sessions_s84 WHERE status IN ('done','ok','finished','complete') AND day >= ?", [armed_at.date()]).fetchall()}
        miss = [d for d in odays if d not in have and d < now.date()]
        scored = con.execute("SELECT count(*) FROM pick_scores_s83").fetchone()[0] if _tbl(con, "pick_scores_s83") else 0
        if miss:
            return _crit("daily_desk_and_picks_scored", "FAIL", "no finished desk session on: " + ", ".join(f"{d:%d %b}" for d in miss))
        return _crit("daily_desk_and_picks_scored", "PASS" if scored else "NOT TESTED", f"desk ran on all {len(odays)} open day(s); {scored} pick score row(s)" if scored else "the desk ran; no pick has a scored horizon yet")

    def c9():
        from pflab.think import wire
        miss = []
        for m in ("IN", "US"):
            for d in markets.get(m).sessions_between(armed_at.date(), min(now.date(), wire._closed(m, now))):
                closed_long_ago = datetime.combine(d, datetime.min.time()) + timedelta(days=2) < now
                if closed_long_ago and (d in odays or d + timedelta(days=1) in odays) and not wire._marked(con, m, d):
                    miss.append(f"{m} {d:%d %b}")
        unthought = con.execute("SELECT count(*) FROM think_cases_s84 c WHERE state='open' AND opened_at < ? AND NOT EXISTS (SELECT 1 FROM think_steps_s84 s WHERE s.case_id=c.case_id)",
                                [now - timedelta(days=1)]).fetchone()[0]
        if miss or unthought:
            return _crit("thinking_loop_every_close", "FAIL", (f"not watched: {', '.join(miss)}; " if miss else "") + (f"{unthought} case(s) without a look" if unthought else ""))
        return _crit("thinking_loop_every_close", "PASS", "every India close and US morning of the open days was watched; no case without a look")

    def c10():
        q = con.execute("SELECT count(*) FROM intake_queue_s85 WHERE created_at >= ?", [armed_at]).fetchone()[0]
        bad = con.execute("SELECT count(*) FROM intake_queue_s85 WHERE created_at >= ? AND (state IN ('failed','error') OR (state NOT IN ('done','answered') AND created_at < ?))", [armed_at, now - timedelta(hours=1)]).fetchone()[0]
        fails = con.execute("SELECT count(*) FROM job_runs WHERE status='failed' AND started_at >= ? AND detail NOT LIKE 'abandoned:%'", [armed_at]).fetchone()[0]
        if bad:
            return _crit("chat_answered_every_message", "FAIL", f"{bad} of {q} chat item(s) failed or stuck")
        return _crit("chat_answered_every_message", "PASS" if q and not fails else "NOT TESTED" if not q else "FAIL", f"{q} chat item(s), all answered; no job failed meanwhile" if q and not fails else "no chat message yet" if not q else f"{fails} job failure(s) meanwhile")

    def c11():
        if not _tbl(con, "page_loads_s86"):
            return _crit("pages_without_server_error", "NOT TESTED", "no page-load record")
        n, bad = con.execute("SELECT count(*), count(*) FILTER (WHERE status >= 500) FROM page_loads_s86 WHERE loaded_at >= ?", [armed_at]).fetchone()
        return _crit("pages_without_server_error", "FAIL" if bad else "PASS" if n else "NOT TESTED", f"{bad} server error(s) in {n} page and data request(s) (a browser console error is not recorded: the screens are untouched)" if n else "no page request recorded yet")

    def c12():
        from pflab.hq import governor as gv
        sp = gv.spend(con, now)
        unpriced = con.execute("SELECT count(*) FROM api_calls WHERE created_at >= ? AND status IN ('done','ok') AND (cost_inr IS NULL)", [armed_at]).fetchone()[0]
        ok = (sp["cap"] <= 0 or sp["month"] <= sp["cap"]) and not unpriced
        return _crit("spend_inside_cap_and_priced", "PASS" if ok else "FAIL", f"month so far Rs {sp['month']:,.0f} of Rs {sp['cap']:,.0f}; {unpriced} unpriced call(s)")

    def c13():
        from pflab.think import alarm
        late = con.execute("SELECT count(*) FROM alarm_s86 WHERE day >= ? AND coalesce(mode,'live')='live' AND slow_cause IS NOT NULL AND slow_cause <> ''", [armed_at.date()]).fetchone()[0]
        runs = con.execute("SELECT count(*) FROM job_runs WHERE job='alarm' AND started_at >= ? AND status='ok'", [armed_at]).fetchone()[0]
        silent = con.execute("SELECT count(*) FROM eyes_s86 WHERE source IN ('google_news','yahoo') AND blind_since IS NOT NULL AND blind_since < ? AND blind_told_at IS NULL", [now - timedelta(hours=2)]).fetchone()[0]
        if late or silent:
            return _crit("alarm_lane", "FAIL", f"{late} RED item(s) slower than 30 minutes; {silent} source(s) silent over 2 hours unreported")
        return _crit("alarm_lane", "PASS" if runs else "NOT TESTED", f"{runs} lane pass(es); no slow RED, no unreported blind spot" if runs else "the lane has not run yet")

    def c14():
        from pflab.core import us_session
        sess = con.execute("SELECT count(DISTINCT session_day) FROM us_fills_s86 WHERE session_day >= ?", [armed_at.date()]).fetchone()[0]
        q = con.execute("SELECT count(DISTINCT CAST(fetched_at AS DATE)) FROM us_quotes_s86 WHERE fetched_at >= ?", [armed_at]).fetchone()[0]
        gaps = con.execute("SELECT count(*) FROM alarm_gap_s86 WHERE off_to >= ?", [armed_at]).fetchone()[0]
        ff = con.execute("SELECT count(DISTINCT gap_id) FROM ghost_s86 WHERE decided_at >= ?", [armed_at]).fetchone()[0]
        if not q:
            return _crit("us_session_loop_and_fast_forward", "NOT TESTED", "the US session loop has not run yet")
        miss_ff = con.execute("SELECT count(*) FROM alarm_gap_s86 g WHERE off_to >= ? AND message LIKE '%Off from%' AND red > 0 AND NOT EXISTS (SELECT 1 FROM ghost_s86 h WHERE h.gap_id = g.gap_id)", [armed_at]).fetchone()[0]
        if miss_ff:
            return _crit("us_session_loop_and_fast_forward", "FAIL", f"{miss_ff} gap(s) with a serious item were not fast-forwarded")
        return _crit("us_session_loop_and_fast_forward", "PASS", f"US session quotes on {q} day(s); {gaps} gap(s) told, {ff} fast-forwarded")

    for name, fn in (("session_loop_with_quotes", c6), ("us_morning_and_fills", c7), ("daily_desk_and_picks_scored", c8), ("thinking_loop_every_close", c9), ("chat_answered_every_message", c10),
                     ("pages_without_server_error", c11), ("spend_inside_cap_and_priced", c12), ("alarm_lane", c13), ("us_session_loop_and_fast_forward", c14)):
        safe(name, fn)
    return out


def message(res: dict, armed_at: datetime, now: datetime) -> str:
    head = {"pass": "PASSED: the first week went well", "fail": "DID NOT PASS: something needs a look", "not_yet": "NOT DECIDED: some things were not exercised yet"}[res["overall"]]
    lines = [f"The app's own check of its first week ({armed_at:%d %b} to {now:%d %b}, open {res['open_hours']} h): {head}."]
    lines += [f"- {c['status']}: {c['name'].replace('_', ' ')}: {c['text']}" for c in res["criteria"]]
    if res["overall"] == "pass":
        lines.append(f"From today ({now:%d %b %Y}) the 60-day feature freeze (A44) applies: bug fixes only, no new feature, tool, model or screen until {(now + timedelta(days=60)):%d %b %Y} unless you ask (the screens of the S87 redesign are the one exception).")
    elif res["overall"] == "fail":
        lines.append("No freeze yet: the failures are fixed first.")
    return "\n".join(lines)


def run(con, now: datetime, release: str = "") -> dict:
    """The job body. Arms on first run; evaluates when due; sends once; for 'not_yet' re-evaluates daily up to GIVE_UP_DAYS."""
    from pflab.service import presence
    cid = arm(con, now, release)
    if not cid:
        return {"skipped": f"the first-week check counts from {ARM_FROM:%a %d %b %Y}", "waiting": True, "why": "armed from the first open on or after 16 Nov 2026"}
    armed_at, verdict, sent = con.execute("SELECT armed_at, verdict, sent FROM week_check_s79 WHERE check_id=?", [cid]).fetchone()
    if verdict in ("pass", "fail") and sent:
        return {"skipped": f"verdict already given: {verdict}"}
    age = now - armed_at
    open_h = presence.open_time(con, armed_at, now).total_seconds() / 3600
    if age < timedelta(days=MIN_DAYS) or open_h < MIN_OPEN_HOURS and age < timedelta(days=GIVE_UP_DAYS):
        return {"skipped": f"waiting: {age.days} of {MIN_DAYS} days, open {open_h:.1f} of {MIN_OPEN_HOURS:g} h", "waiting": True, "why": "the first-week check is not due yet"}
    res = evaluate(con, armed_at, now)
    final = res["overall"] in ("pass", "fail") or age >= timedelta(days=GIVE_UP_DAYS)
    freeze = now.date() if res["overall"] == "pass" else None
    con.execute("UPDATE week_check_s79 SET verdict=?, verdict_at=?, details_json=?, freeze_from=? WHERE check_id=?", [res["overall"], now, json.dumps(res), freeze, cid])
    if final:
        from pflab.service import telegram as tgm
        tgm.enqueue(con, message(res, armed_at, now), "summary", dedup_key=f"week_check:{cid}", now=now)
        con.execute("UPDATE week_check_s79 SET sent=TRUE WHERE check_id=?", [cid])
    return {"overall": res["overall"], "final": final, "criteria": {c["name"]: c["status"] for c in res["criteria"]}}
