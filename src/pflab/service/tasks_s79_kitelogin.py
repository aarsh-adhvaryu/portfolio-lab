"""S79b item K: when Kite is logged out the system says so and asks, once a day.

Job `kite_token` (every 30 minutes, weekends too): looks at the token (`ingest.kite.TokenStore`, the same test as `app.runtime.token_valid`).
  - A valid token: any open `kite_login:*` question is closed with the evidence (the system proved it is logged in); nothing else happens.
  - No token and Kite is wanted (the app has Kite keys, its Kite ability is on, and either a Kite job skipped for a missing login in the last 24 hours or today is an
    exchange day and it is past 08:00): ONE urgent question per day (subject `kite_login:<date>`, goes out on Telegram with buttons, `agents/voice.py`) that says what
    Kite adds, what the system does without it, and how to log in (the app's button, or `tools\\kite_login.py`). An earlier day's still-open question is dropped.
The Kite jobs themselves degrade on their own: `bars_1m` and `live`/`tradecheck` return a stated skip when there is no token. The token is never read into this
module's output; only whether one is valid.
Switch: `configs/s79b.toml [kite] on`; off = the job skips.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Optional, Tuple

from pflab.service.jobs import Ctx, Job, register
from pflab.service.schedule import Interval

ASK_AFTER = time(8, 0)
DEFAULT_ANSWER = "carry on without Kite today"
OPTIONS = ["I have logged in", "remind me tomorrow"]
SKIP_WORDS = ("logged out", "no kite login", "kite is not logged in")
KITE_JOBS = ("live", "tradecheck", "bars_1m")


def settings() -> dict:
    try:
        from pflab import _toml
        p = Path(__file__).resolve().parents[3] / "configs" / "s79b.toml"
        return dict(_toml.load(p).get("kite", {}) or {})
    except Exception:
        return {}


def is_on() -> bool:
    return bool(settings().get("on", True))


def token_valid(now: datetime, store=None) -> bool:
    from pflab.ingest import kite as km
    try:
        return (store or km.TokenStore()).load(now) is not None
    except Exception:
        return False


def kite_wanted(ctx: Ctx) -> Tuple[bool, str]:
    """Does the system need Kite right now? (No question when it does not: a login nobody needs is not asked for.)"""
    if ctx.secrets is None or not ctx.secrets.has("kite", "api_key"):
        return False, "Kite is not set up (no API key in the secrets file)"
    try:
        from pflab.app import settings as _st
        if not _st.ability("kite_live", current=getattr(ctx, "settings", None)):
            return False, "Kite live data is switched off in Settings"
    except Exception:
        pass
    since = ctx.now - timedelta(hours=24)
    try:
        rows = ctx.con.execute("SELECT detail FROM job_runs WHERE job IN ('live','tradecheck','bars_1m') AND started_at >= ? AND detail IS NOT NULL", [since]).fetchall()
        if any(any(w in str(r[0]).lower() for w in SKIP_WORDS) for r in rows):
            return True, "a Kite job found no login in the last 24 hours"
    except Exception:
        pass
    try:
        from pflab import markets
        m = markets.get("IN")
        if m.is_session(ctx.now.date()) and ctx.now.time() >= ASK_AFTER:
            return True, "today is an exchange day"
    except Exception:
        pass
    return False, "no exchange day and no Kite job needed it"


def question_text(day) -> str:
    return (f"Kite is logged out ({day:%a %d %b}). Without it the system uses only the exchange's daily closes: no live prices, no minute bars, and today's "
            "Kite checks are skipped. To log in: open the Portfolio Lab app and press Log in to Kite; or, from the project folder, run "
            r".venv\Scripts\python tools\kite_login.py" " and finish the Kite page that opens.")


def _kite_token(ctx: Ctx, token_store=None) -> dict:
    if not is_on():
        return {"off": True}
    from pflab.agents import questions
    now = ctx.now
    if token_valid(now, token_store):
        n = questions.close_with_evidence(ctx.con, "kite_login:%", "Kite has a valid login now", now)
        return {"token": "valid", "closed_questions": n}
    wanted, why = kite_wanted(ctx)
    if not wanted:
        return {"token": "missing", "asked": False, "why": why}
    key = f"kite_login:{now.date()}"
    for (k,) in ctx.con.execute("SELECT subject_key FROM questions WHERE subject_key LIKE 'kite_login:%' AND subject_key <> ? AND status='open'", [key]).fetchall():
        questions.drop(ctx.con, k, now)                                  # yesterday's is superseded by today's
    qid = questions.ask(ctx.con, "kite", key, question_text(now), now, default=DEFAULT_ANSWER, deadline=datetime.combine(now.date(), time(23, 59)),
                        urgent=True, options=OPTIONS)
    return {"token": "missing", "asked": qid is not None, "question": qid, "why": why}


register(Job("kite_token", Interval(30, weekdays_only=False), _kite_token,
             "is Kite logged in? When not and Kite is needed, one urgent question a day says how to log in; closed when a login appears", cooldown_minutes=10))
