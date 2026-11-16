"""S93: standing orders. The model works on three triggers only: he asks; a plan he started (`oper/plans.py`, once or on repeat); a RED alarm (`think/alarm.py`, unchanged).
Everything else the model used to start BY ITSELF is a STANDING ORDER: a named piece of work he can see, switch off and switch on, with what it costs and what it used.

    cases    think the day's new cases through (`think/wire.sweep`)         on by default
    desk     the daily desk's working session (`think/desk.tick_hook`)       on by default
    weekly   the weekly look (`oper/introspect.run`)                          on by default
    autofix  start a fix build for a repeated fault (`oper/build.py`)         OFF by default: a repeated fault becomes a Yes/No card that states the cost

An order that is off stops only NEW model work of its kind. Code goes on as before (the watch, the rails, scoring, a part of a buy that is due, a case already being followed),
and so does the alarm lane. Defaults are in `configs/core.toml [jarvis]`; what he sets (chat, `POST /api/agents`) is kept in `standing_s93` and wins.
Safe fallback: `[jarvis] on = false` gives the behaviour before S93 (every order counts as on, automatic builds included)."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "core.toml"
DDL = "CREATE TABLE IF NOT EXISTS standing_s93 (key VARCHAR PRIMARY KEY, is_on BOOLEAN NOT NULL, set_at TIMESTAMP NOT NULL, set_by VARCHAR)"
DEFAULTS = {"on": True, "cases": True, "desk": True, "weekly": True, "autofix": False}
# key -> (label, the agent of the Agents screen, the token class in `[operator]`, what one run costs in his own measured numbers)
ORDERS: Dict[str, Tuple[str, str, str, str]] = {
    "cases": ("Think new cases through", "case", "cases", "about 12,000 tokens a case, at most 3 new cases a day"),
    "desk": ("Daily desk", "desk", "desk", "about 14,000 tokens a run, up to two runs a day"),
    "weekly": ("Weekly look", "weekly", "desk", "one run a week"),
    "autofix": ("Fix a repeated fault by itself", "fixer", "build", "400,000 to 560,000 tokens an attempt"),
}
FIX_TOKENS = "about 400,000 to 560,000 tokens of your plan (measured on two builds)"


def settings() -> dict:
    out = dict(DEFAULTS)
    try:
        from pflab import _toml
        out.update({k: bool(v) for k, v in (_toml.load(CONFIG).get("jarvis") or {}).items() if k in DEFAULTS})
    except Exception:
        pass
    return out


def ensure(con) -> None:
    con.execute(DDL)


def is_on(con, key: str) -> bool:
    """Whether the order may start new model work. With `[jarvis] on = false` every order counts as on (the behaviour before S93)."""
    if key not in ORDERS:
        raise KeyError(key)
    cfg = settings()
    if not cfg["on"]:
        return True
    try:
        ensure(con)
        r = con.execute("SELECT is_on FROM standing_s93 WHERE key=?", [key]).fetchone()
    except Exception:
        r = None
    return bool(r[0]) if r else bool(cfg[key])


def allowed(con, key: str) -> Tuple[bool, str]:
    if is_on(con, key):
        return True, ""
    return False, f"the standing order '{ORDERS[key][0]}' is off (switch it on in the chat or on the Agents screen)"


def set_on(con, now: datetime, key: str, on: bool, by: str = "him") -> dict:
    if key not in ORDERS:
        raise ValueError("order must be one of " + ", ".join(ORDERS))
    ensure(con)
    con.execute("DELETE FROM standing_s93 WHERE key=?", [key])
    con.execute("INSERT INTO standing_s93 VALUES (?,?,?,?)", [key, bool(on), now, str(by)[:40]])
    return {"ok": True, "order": key, "on": bool(on), "label": ORDERS[key][0]}


def _used(con, klass: str, since: datetime) -> Tuple[int, int, Optional[str]]:
    """(tokens, calls, last run) of a token class since a time, from the call log."""
    try:
        r = con.execute("SELECT coalesce(sum(coalesce(input_tokens,0) + coalesce(output_tokens,0)),0), count(*), max(created_at) FROM api_calls WHERE mode='plan' AND topic LIKE ? AND created_at >= ?",
                        [f"plan:{klass}:%", since]).fetchone()
        return int(r[0] or 0), int(r[1] or 0), (str(r[2])[:16] if r[2] else None)
    except Exception:
        return 0, 0, None


def waiting_cases(con) -> List[dict]:
    """Open cases nothing has been thought about yet."""
    try:
        from pflab.think import cases
        return [c for c in cases.open_cases(con) if c["state"] == "open" and not cases.steps(con, c["case_id"])]
    except Exception:
        return []


def state(con, now: datetime) -> List[dict]:
    """For the Agents screen and the chat: each order, on or off, who set it, what one run costs and what its token class used in the last 7 days.
    (`desk` and `weekly` share the class `desk`, `cases` shares its class with the alarm's cases: the tokens are the class's, said so in `class`.)"""
    ensure(con)
    cfg = settings()
    rows = {k: (o, a, b) for k, o, a, b in con.execute("SELECT key, is_on, set_at, set_by FROM standing_s93").fetchall()}
    out = []
    for key, (label, agent, klass, cost) in ORDERS.items():
        tokens, calls, last = _used(con, klass, now - timedelta(days=7))
        r = rows.get(key)
        d = {"key": key, "label": label, "agent": agent, "class": klass, "on": is_on(con, key), "default": bool(cfg[key]), "set_by": (r[2] if r else None),
             "set_at": (str(r[1])[:16] if r else None), "one_run": cost, "tokens_7d": tokens, "calls_7d": calls, "last_run": last}
        if key == "cases":
            d["waiting"] = len(waiting_cases(con))
        out.append(d)
    return out


def text(con, now: datetime) -> str:
    """The same as plain lines, for the chat."""
    if not settings()["on"]:
        return "Standing orders are not in use ([jarvis] on = false): the model's own work runs as before S93."
    lines = []
    for d in state(con, now):
        lines.append(f"- {d['label']}: {'ON' if d['on'] else 'OFF'} ({d['one_run']}); its token class '{d['class']}' used {d['tokens_7d']:,} tokens in {d['calls_7d']} call(s) over 7 days"
                     + (f"; {d['waiting']} case(s) waiting" if d.get("waiting") else ""))
    return "Standing orders (work the model may start by itself):\n" + "\n".join(lines)


def waiting_note(con, now: datetime) -> Optional[int]:
    """While `cases` is off: one line a day in the chat that names the cases waiting for him. Costs nothing. -> how many wait (None when none or already said today)."""
    w = waiting_cases(con)
    if not w:
        return None
    try:
        from pflab.entrance import store
        names = ", ".join(dict.fromkeys(str(c.get("symbol") or c.get("isin") or f"case #{c['case_id']}") for c in w[:6]))
        msg = (f"{len(w)} case(s) noticed and waiting for you: {names}. The case worker is off, so nothing was spent on them. "
               "Say 'think the cases through' to do it once (about 12,000 tokens a case), or 'switch the case worker on'.")
        mid = store.post_system(con, now, msg, kind="standing", key=f"standing:cases:{now.date()}", channels=("laptop", "telegram"))
        return len(w) if mid else None
    except Exception:
        return None
