"""HQ's rounds (S59): the same work inside the dashboard (a thread of its runtime) and in the scheduled tick (the `hq`
job) when the window is closed. One round:

    board      the investor's orders and the agents' hand-ons, one task at a time; answers back to where they came from
    watcher    the drop folder -> the inbox (Settings: drop_watch)
    reminders  due ones sent
    keeper     predictions scored, decisions followed up (outcomes written back), notes kept tidy,
               every KEEP_EVERY
    security   S62: every request that left the PC since the last round re-checked against the egress list (code)

Under the preset 'light' the paid agents (the brain) do not run on their own; under 'off' only the investor's own
orders, reminders and the drop folder run.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple

KEEP_EVERY = timedelta(hours=1)
_last: dict = {}


def _due(rt, what: str, every: timedelta) -> bool:
    key = (id(rt), what)
    now = rt.clock()
    if key in _last and now - _last[key] < every:
        return False
    _last[key] = now
    return True


def client(rt):
    from pflab.hq import llm
    c = getattr(rt, "_hq_client", None)
    if c is None:
        c = llm.client(rt.secrets)
        try:
            setattr(rt, "_hq_client", c)
        except AttributeError:
            pass
    return c


def names(rt) -> Tuple[List[str], List[str]]:
    """(held, listed) ISINs: the portfolio today and the stock list."""
    from pflab.plan import guards as gd
    from pflab.pm import today
    pos = today.build(rt.cursor(), rt.clock().date())["positions"]
    held = sorted({i for i, q in zip(pos["isin"], pos["qty"]) if isinstance(i, str) and i.startswith("IN") and q > 0})
    return held, [s["isin"] for s in gd.stock_list() if s["isin"] not in held]


def gate(rt):
    from pflab.hq import egress
    return egress.load(rt.cursor())


def paused(rt) -> bool:
    """Pause (World screen) holds every autonomous start: jobs, the brain, the keeper, agents' hand-offs (audit 2026-10-30).
    What is already running finishes; what he orders himself still runs."""
    return not rt.settings.get("scheduler", True)


def paid_allowed(rt) -> bool:
    from pflab.agents import analyst as an
    cfg = an.config()
    return not paused(rt) and rt.settings.get("preset", "full") in ("full", "marathon") and (cfg["cap"] > 0 or an.acceptance(cfg, rt.clock()) is not None)


def brain_now(rt, question: Optional[str] = None, rival: bool = False, history: str = "") -> dict:
    """A question from the AI centre's Auto road or Telegram's /brain: the same tool conversation as the chat (`app/assistant.ask_once`). `ok` says whether it answered.
    (S80 phase 4: the brain's own passes, its gatekeeper, events and rival are cut; `rival` is kept only so older callers do not break.)"""
    from pflab.app import assistant
    if not (question or "").strip():
        return {"text": "Ask a question: the brain no longer makes passes of its own.", "pass": None, "ok": False}
    out = assistant.ask_once(rt, question, history)
    return {"text": out["text"], "pass": None, "cost": out["cost"], "ok": out["ok"]}


def deliver(rt):
    """Send a finished task's answer back to Telegram (through the outbox, so a failure is retried)."""
    from pflab.hq import messenger, roster

    def send(t: dict) -> None:
        if t["channel"] != "telegram":
            return
        who = roster.title(t["to"])[0]
        messenger.send_now(rt, f"{who} (#{t['id']}): {t['result'] or '(no answer)'}", "reply", dedup_key=f"task:{t['id']}")
    return send


def start(rt) -> dict:
    """Taking the store means any task or case still `running` belongs to a process that died: recover them (retry, bounded), then look
    for what arrived while the system was off. Safe to call again at a wake: it only reads and moves states."""
    from pflab.hq import board, cases
    con, now = rt.cursor(), rt.clock()
    out = {"tasks_recovered": board.reap(con, now), "cases_recovered": cases.reap(con, now), "cases_resumed": len(cases.sweep(con, now))}
    # S68: a paid call the old process was in the middle of (found after a hard kill: a row 'sending' for ever) is closed. The money may have been spent, so it
    # stays counted at its estimate (status 'refused' is counted by the governor), with the reason said.
    out["calls_closed"] = int(con.execute("SELECT count(*) FROM api_calls WHERE status='sending'").fetchone()[0])
    con.execute("UPDATE api_calls SET status='refused', error='interrupted: the process stopped during this call; counted at its estimate', finished_at=? WHERE status='sending'", [now])
    try:                                                   # an experiment a dead process left running continues from its recorded attempts
        from pflab.learner import experiments
        out["experiments_recovered"] = experiments.reap(con, now)
    except Exception:
        out["experiments_recovered"] = 0
    try:                                                   # a new, activated profile gets its one grouped first question
        from pflab.app import onboarding
        out["welcome"] = onboarding.welcome(con, now)
    except Exception:
        out["welcome"] = None
    try:                                                   # his choices (targets, watch list, API cap) come back if a fresh start left them
        from pflab.pm import fresh
        out["choices_restored"] = fresh.restore_missing_choices(rt.pm_dir)
    except Exception:
        out["choices_restored"] = []
    try:                                                   # requests for files he has already dropped close at start too
        from pflab.app import inbox
        out["requests_closed"] = inbox.close_met_requests(rt)
    except Exception:
        out["requests_closed"] = 0
    if out.get("choices_restored") and "fd_holdings.toml" in out["choices_restored"]:
        try:                                               # his deposits came back: counted at once, not at the next job
            from pflab.app import inbox
            out["deposits"] = inbox.deposits_now(rt).get("deposits")
        except Exception:
            out["deposits"] = None
    rt.bump("hq")
    return out


def round_(rt, stop=None, attended: bool = True) -> dict:
    """One HQ round. Each part fails on its own (logged in the result), never the round."""
    from pflab.hq import board, keeper, messenger, roster, security, watcher
    out: dict = {}
    preset = rt.settings.get("preset", "full")
    hold = paused(rt)

    def part(name, fn):
        try:
            out[name] = fn()
        except Exception as e:                                   # shown in the round's result, never hidden
            out[name] = f"failed: {type(e).__name__}: {str(e)[:200]}"
            out.setdefault("failed", {})[name] = out[name][len("failed: "):]

    part("board", lambda: board.run_all(rt, roster.runners(), deliver(rt), max_n=20 if attended else 8, stop=stop, his_only=hold,
                                        skip=None))
    if hold:                                                     # paused: his own orders and the safety checks only
        part("reminders", lambda: messenger.due(rt))
        part("security", lambda: security.egress(rt))
        out["paused"] = True
        return out
    from pflab.hq import cases
    def blocked_files():                                          # S68: a password saved since opens a blocked file by itself
        from pflab.app import inbox
        return inbox.retry_blocked(rt)
    part("blocked_files", blocked_files)
    part("cases", lambda: len(cases.sweep(rt.cursor(), rt.clock())))     # S67: what a waiting investigation needed may have arrived (free, code only)
    if rt.settings.get("drop_watch", True):
        def drop():
            got = watcher.scan(rt)
            watcher.announce(rt, got)
            return len(got)
        part("drop", drop)
    part("reminders", lambda: messenger.due(rt))
    part("security", lambda: security.egress(rt))               # S62: what left the PC re-checked at once (code)
    if _due(rt, "keep", KEEP_EVERY):
        part("keeper", lambda: keeper.run(rt.cursor(), rt.clock(), rt.data_root))
    return out


def tick_job(ctx) -> dict:
    """The `hq` job of the scheduled tick (window closed): the phone once, then a round."""
    from pflab.hq import desk, phone
    rt = desk.from_ctx(ctx)
    if rt.settings.get("preset", "full") == "off":
        return {"skipped": True, "why": "preset off"}
    if paused(rt):
        return {"skipped": True, "why": "paused"}
    start(rt)
    out = {}
    try:
        out["phone"] = phone.poll_once(rt, timeout=0)
    except Exception as e:
        out["phone"] = f"failed: {type(e).__name__}: {str(e)[:200]}"
    out.update(round_(rt, attended=False))
    if isinstance(out.get("phone"), str) and out["phone"].startswith("failed: "):
        out.setdefault("failed", {})["phone"] = out["phone"][len("failed: "):]
    failed = out.pop("failed", None)
    res = {k: (v if isinstance(v, (int, float, str)) else str(v)[:300]) for k, v in out.items()}
    if failed:
        res["failed"] = failed                                   # the job fails with the part that failed (service/jobs.py)
    return res
