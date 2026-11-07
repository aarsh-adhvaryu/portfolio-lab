"""The app checks its own first week (S79b, A44) and tells him, once, on Telegram.

Armed the first time the app runs this release (`arm`). Evaluated daily (job `week_check`) once at least `MIN_DAYS` calendar days have passed AND the app was open at least `MIN_OPEN_HOURS`
in total (his instruction was "the first 7 days of open time": a laptop that is off at night cannot give 7 x 24 h, so the rule is 7 calendar days with at least 12 hours open; recorded as a decision).
Criteria, each PASS / FAIL / NOT TESTED:
  1. a catch-up ran after every off-gap that missed a session (`catchup_s79` done after `off_to`);
  2. every mode was reached (pre_open, session, post_close, deep on the home market: `mode_seen_s79`); NOT TESTED if the app was never open in a mode's hours;
  3. forecasts were made and scored (`forecasts_s79`, `forecast_scores_s79`);
  4. no unhandled failure: no job run 'failed' in the window (an 'offline' run, and a run stopped with the app, are not failures);
  5. cost within the cap (the month's counted API spend against the cap).
Overall: PASS when all five pass; FAIL when any fails; NOT YET when none fails but some are not tested (repeated daily, up to 21 days, then reported as it stands). On PASS the message says that the 60-day
feature freeze (A44, bug fixes only) starts today, and `freeze_from` is stored.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

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
    r = con.execute("SELECT check_id FROM week_check_s79 ORDER BY check_id DESC LIMIT 1").fetchone()
    if r:
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
    st = [c["status"] for c in out]
    overall = "fail" if "FAIL" in st else "pass" if all(s == "PASS" for s in st) else "not_yet"
    return {"overall": overall, "criteria": out, "open_hours": round(presence.open_time(con, armed_at, now).total_seconds() / 3600, 1)}


def message(res: dict, armed_at: datetime, now: datetime) -> str:
    head = {"pass": "PASSED: the first week went well", "fail": "DID NOT PASS: something needs a look", "not_yet": "NOT DECIDED: some things were not exercised yet"}[res["overall"]]
    lines = [f"The app's own check of its first week ({armed_at:%d %b} to {now:%d %b}, open {res['open_hours']} h): {head}."]
    lines += [f"- {c['status']}: {c['name'].replace('_', ' ')}: {c['text']}" for c in res["criteria"]]
    if res["overall"] == "pass":
        lines.append(f"From today ({now:%d %b %Y}) the 60-day feature freeze (A44) applies: bug fixes only, no new features until {(now + timedelta(days=60)):%d %b %Y}.")
    elif res["overall"] == "fail":
        lines.append("No freeze yet: the failures are fixed first.")
    return "\n".join(lines)


def run(con, now: datetime, release: str = "") -> dict:
    """The job body. Arms on first run; evaluates when due; sends once; for 'not_yet' re-evaluates daily up to GIVE_UP_DAYS."""
    from pflab.service import presence
    cid = arm(con, now, release)
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
