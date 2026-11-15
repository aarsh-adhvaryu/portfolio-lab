"""S91: the first saved investigation of the day, worked out by code (0 tokens) once fresh data has arrived: a co-movement (pair) study of two of his current holdings, the pair among the largest
five whose test is the strongest. It records its data period, its numbers and its artifact (a note and the series in the operator's `research/` folder) in `investigations_s91`, one row per
(day, kind): a refresh, a second job tick or a restart never runs it twice (`claim`). With no complete snapshot of today, or fewer than two holdings with enough history, it WAITS and says why
(the Home card shows the reason). A run cut off by a crash is taken over after 10 minutes, at most 3 attempts a day."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

KIND = "pair"
TOP = 5
STALE_MIN = 10
MAX_ATTEMPTS = 3
DDL = """CREATE TABLE IF NOT EXISTS investigations_s91 (day DATE NOT NULL, kind VARCHAR NOT NULL, subject VARCHAR, status VARCHAR, attempts INTEGER, started_at TIMESTAMP, finished_at TIMESTAMP,
         period_from DATE, period_to DATE, result_json VARCHAR, artifact VARCHAR, detail VARCHAR, PRIMARY KEY (day, kind))"""


def ensure(con) -> None:
    con.execute(DDL)


def get(con, day: date, kind: str = KIND) -> Optional[dict]:
    ensure(con)
    r = con.execute("SELECT subject, status, attempts, started_at, finished_at, period_from, period_to, result_json, artifact, detail FROM investigations_s91 WHERE day=? AND kind=?", [day, kind]).fetchone()
    if not r:
        return None
    keys = ("subject", "status", "attempts", "started_at", "finished_at", "period_from", "period_to", "result_json", "artifact", "detail")
    d = dict(zip(keys, r))
    d["result"] = json.loads(d.pop("result_json") or "{}")
    return d


def claim(con, now: datetime, kind: str = KIND) -> bool:
    """Take today's slot. False when it is done, running now, or out of attempts."""
    ensure(con)
    day = now.date()
    cur = get(con, day, kind)
    if cur is None:
        try:
            con.execute("INSERT INTO investigations_s91 (day, kind, status, attempts, started_at) VALUES (?,?,?,?,?)", [day, kind, "running", 1, now])
            return True
        except Exception:                                                  # another thread inserted first
            return False
    if cur["status"] == "done" or int(cur["attempts"] or 0) >= MAX_ATTEMPTS:
        return False
    if cur["status"] == "running" and cur["started_at"] and now - cur["started_at"] < timedelta(minutes=STALE_MIN):
        return False
    n = con.execute("UPDATE investigations_s91 SET status='running', attempts=attempts+1, started_at=?, detail=NULL WHERE day=? AND kind=? AND status IN ('running','waiting','failed') RETURNING attempts",
                    [now, day, kind]).fetchall()
    return bool(n)


def _finish(con, day: date, kind: str, status: str, now: datetime, **cols) -> None:
    sets = ", ".join(f"{k}=?" for k in cols)
    con.execute(f"UPDATE investigations_s91 SET status=?, finished_at=?{', ' + sets if sets else ''} WHERE day=? AND kind=?", [status, now, *cols.values(), day, kind])


def waiting_reason(con, now: datetime) -> Optional[str]:
    """Why it cannot run yet, in plain words (None: it can)."""
    try:
        r = con.execute("SELECT count(*), max(snapshot_at) FROM mine_in_s89 WHERE qty > 0").fetchone()
    except Exception:
        return "no snapshot of your holdings yet: log in to Kite"
    if not r or not r[0]:
        return "no snapshot of your holdings yet: log in to Kite"
    if r[1] is None or r[1].date() != now.date():
        return "waiting for today's complete Kite snapshot (the last one is from " + (str(r[1])[:16] if r[1] else "never") + ")"
    if r[0] < 2:
        return "needs at least two holdings"
    return None


def run(rt, con, now: datetime) -> dict:
    """One tick of the job. -> {"state": done | waiting | running | skipped | failed, ...}."""
    ensure(con)
    why = waiting_reason(con, now)
    if why:
        cur = get(con, now.date())
        if cur is None:
            try:
                con.execute("INSERT INTO investigations_s91 (day, kind, status, attempts, detail) VALUES (?,?,?,?,?)", [now.date(), KIND, "waiting", 0, why])
            except Exception:
                pass
        elif cur["status"] == "waiting":
            con.execute("UPDATE investigations_s91 SET detail=? WHERE day=? AND kind=?", [why, now.date(), KIND])
        return {"state": "waiting", "why": why}
    if not claim(con, now):
        cur = get(con, now.date()) or {}
        return {"state": "skipped", "why": f"already {cur.get('status')}"}
    day = now.date()
    try:
        from pflab.app.s89 import pair
        syms = [r[0] for r in con.execute("SELECT symbol FROM mine_in_s89 WHERE qty > 0 ORDER BY qty * last_price DESC LIMIT ?", [TOP]).fetchall()]
        best, tried, errors = None, 0, []
        for i in range(len(syms)):
            for j in range(i + 1, len(syms)):
                try:
                    p = pair(con, rt.data_root, day, syms[i], syms[j])
                except Exception as e:
                    errors.append(f"{syms[i]}/{syms[j]}: {str(e)[:80]}")
                    continue
                tried += 1
                if best is None or p["p_value"] < best["p_value"]:
                    best = p
        if best is None:
            _finish(con, day, KIND, "waiting", now, detail="no pair of your holdings has enough shared price history yet" + (f" ({errors[0]})" if errors else ""))
            return {"state": "waiting", "why": "no pair has enough shared history"}
        art = _artifact(rt, now, best, tried, syms)
        result = {k: best[k] for k in ("a", "b", "days", "gap_z", "p_value", "hedge_ratio", "half_life_days", "correlation", "verdict")}
        result.update(pairs_tried=tried, from_names=syms)
        _finish(con, day, KIND, "done", now, subject=f"{best['a']} and {best['b']}", period_from=date.fromisoformat(best["dates"][0]), period_to=date.fromisoformat(best["dates"][-1]),
                result_json=json.dumps(result), artifact=str(art))
        _tell(con, now, best, art)
        try:
            rt.bump("hq", "chat")
        except Exception:
            pass
        return {"state": "done", "subject": f"{best['a']} and {best['b']}", "verdict": best["verdict"], "artifact": str(art)}
    except Exception as e:
        _finish(con, day, KIND, "failed", now, detail=f"{type(e).__name__}: {str(e)[:200]}")
        return {"state": "failed", "why": f"{type(e).__name__}: {str(e)[:160]}"}


def _artifact(rt, now: datetime, p: dict, tried: int, syms) -> Path:
    from pflab.oper import workspace
    ws = workspace.ensure(str(getattr(rt, "data_root", "") or "") or None)
    stem = f"pair_{p['a']}_{p['b']}_{now:%Y-%m-%d}"
    folder = ws / "research"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stem}.json").write_text(json.dumps({"made_at": str(now)[:19], "method": "Engle-Granger cointegration on 3 years of daily closes (adjusted), hedge ratio by least squares", **p}), encoding="utf-8")
    note = folder / f"{stem}.md"
    half = f"{p['half_life_days']} sessions" if p["half_life_days"] is not None else "no pull back found"
    note.write_text(
        f"# Co-movement of {p['a']} and {p['b']} ({now:%d %b %Y})\n\nWorked out by code on your laptop, 0 tokens. Data: daily adjusted closes {p['dates'][0]} to {p['dates'][-1]} ({p['days']} shared days).\n"
        f"Chosen as the strongest of {tried} pairs among your {len(syms)} largest holdings.\n\n"
        f"- Verdict: **{p['verdict']}** (cointegration p-value {p['p_value']})\n- Correlation of daily moves: {p['correlation']}\n- Hedge ratio: {p['hedge_ratio']}\n"
        f"- Half-life of a gap: {half}\n- Gap today: {p['gap_z']} standard deviations\n\nA description of the past, not a forecast. The series are in the .json beside this note.\n", encoding="utf-8")
    return note


def _tell(con, now: datetime, p: dict, art: Path) -> None:
    try:
        from pflab.entrance import store
        half = f", half a gap closes in about {p['half_life_days']} sessions" if p["half_life_days"] is not None else ""
        store.post_system(con, now, f"Today's saved study: {p['a']} and {p['b']} move {'tied together' if p['verdict'] == 'tied' else 'loosely' if p['verdict'] == 'loose' else 'not tied'} "
                          f"(p-value {p['p_value']}, correlation {p['correlation']}{half}), over {p['dates'][0]} to {p['dates'][-1]}. Note: {art.name}.", kind="investigation", key=f"investigation:{now:%Y-%m-%d}",
                          channels=("laptop",))
    except Exception:
        pass
