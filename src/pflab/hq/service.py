"""HQ's rounds (S59): the same work inside the dashboard (a thread of its runtime) and in the scheduled tick (the `hq`
job) when the window is closed. One round:

    board      the investor's orders and the agents' hand-ons, one task at a time; answers back to where they came from
    watcher    the drop folder -> the inbox (Settings: drop_watch)
    reminders  due ones sent
    texts      every filing of a held or listed company keeps its attachment's text here (free, S60), every READ_EVERY
    readers    unread public documents on held and listed names (Haiku), every READ_EVERY
    brain      wakes only on something new and material (gatekeeper first) or its morning review / weekly reflection
    keeper     predictions and suggestions scored, decisions followed up (outcomes written back), notes kept tidy,
               every KEEP_EVERY
    security   S62: every request that left the PC since the last round re-checked against the egress list (code)

Under the preset 'light' the paid agents (readers, brain) do not run on their own; under 'off' only the investor's own
orders, reminders and the drop folder run.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple

READ_EVERY = timedelta(minutes=15)
BRAIN_EVERY = timedelta(minutes=15)
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


def paid_allowed(rt) -> bool:
    from pflab.agents import analyst as an
    return rt.settings.get("preset", "full") in ("full", "marathon") and an.config()["cap"] > 0


def read_now(rt, limit: int = 40) -> dict:
    from pflab.hq import readers
    from pflab.plan import guards as gd
    held, listed = names(rt)
    return readers.run(rt.cursor(), rt.clock().date(), client(rt), gate(rt), rt.clock(), rt.settings.get("brain", "economy"),
                       held, listed, limit=limit, stock_list=gd.stock_list(), text_dir=rt.data_root / "kg" / "text")


def texts_now(rt) -> dict:
    """Free: the attachments of held and listed companies' filings kept as text on this PC (S60)."""
    from pflab.hq import readers
    held, listed = names(rt)
    return readers.keep_texts(rt.cursor(), held, listed, rt.data_root / "kg" / "text", rt.clock())


def brain_wake(rt) -> dict:
    from pflab.conductor import calendar as mcal
    from pflab.hq import brain
    held, listed = names(rt)
    try:
        cal = mcal.load()
    except Exception:
        cal = None
    return brain.wake(rt, client(rt), gate(rt), held=held, listed=listed, cal=cal)


def brain_now(rt, question: Optional[str] = None, rival: bool = True) -> dict:
    """The investor orders a pass (no gatekeeper: his order is the reason); his words are its event. `ok` says whether a pass
    answered. S62: a question from the AI centre or Telegram runs without the rival (the comparison runs on the
    scheduled passes; a question should not cost twice)."""
    from pflab.hq import brain
    con, now = rt.cursor(), rt.clock()
    if rt.settings.get("brain", "economy") == "off":
        return {"text": "The brain is off (Settings). Set it to economy or normal to order a pass.", "pass": None,
                "ok": False}
    evs = [{"key": f"ask:{now:%Y%m%d%H%M%S}", "kind": "from the investor (question)", "text": question}] if question else []
    g = gate(rt)
    evs, withheld = brain.screen(evs, g)
    main, other = brain.pair()
    pid = brain.think(rt, "asked", evs, client(rt), g, model=main, withheld=withheld)
    if rival:
        brain.think(rt, "asked", evs, client(rt), g, model=other, role="rival", withheld=withheld)
    p = brain.journal(con, 5)
    mine = next((x for x in p if x["id"] == pid), None)
    if mine is None or mine["status"] != "done" or not (mine["note"] or "").strip():
        why = (mine or {}).get("error") or ("no note" if mine else "unknown")
        return {"text": f"No pass was made: {why}", "pass": pid, "ok": False}
    lines = [mine["note"] or "(no note)"]
    lines += [f"- {d['action']}" + (f" ({d['agent']})" if d.get("agent") and d["action"] == "investigate" else "")
              + f": {d['subject']}: {d['reason']}" for d in mine["decisions"] if d["action"] != "nothing"]
    return {"text": "\n".join(lines) + ("\n(Shadow mode: journalled, nothing acted on.)" if brain.SHADOW else ""), "pass": pid,
            "cost": float(mine["cost"] or 0), "ok": True}


def deliver(rt):
    """Send a finished task's answer back to Telegram (through the outbox, so a failure is retried)."""
    from pflab.hq import messenger, roster

    def send(t: dict) -> None:
        if t["channel"] != "telegram":
            return
        who = roster.title(t["to"])[0]
        messenger.send_now(rt, f"{who} (#{t['id']}): {t['result'] or '(no answer)'}", "reply", dedup_key=f"task:{t['id']}")
    return send


def start(rt) -> None:
    from pflab.hq import board
    board.reap(rt.cursor(), rt.clock())


def round_(rt, stop=None, attended: bool = True) -> dict:
    """One HQ round. Each part fails on its own (logged in the result), never the round."""
    from pflab.hq import board, keeper, messenger, roster, security, watcher
    out: dict = {}
    preset = rt.settings.get("preset", "full")

    def part(name, fn):
        try:
            out[name] = fn()
        except Exception as e:                                   # shown in the round's result, never hidden
            out[name] = f"failed: {type(e).__name__}: {str(e)[:200]}"

    part("board", lambda: board.run_all(rt, roster.runners(), deliver(rt), max_n=20 if attended else 8, stop=stop))
    if rt.settings.get("drop_watch", True):
        def drop():
            got = watcher.scan(rt)
            watcher.announce(rt, got)
            return len(got)
        part("drop", drop)
    part("reminders", lambda: messenger.due(rt))
    part("security", lambda: security.egress(rt))               # S62: what left the PC re-checked at once (code)
    if preset != "off" and _due(rt, "texts", READ_EVERY):
        part("texts", lambda: texts_now(rt))                    # free, before the readers: they read the kept text
    if preset != "off" and paid_allowed(rt):
        if _due(rt, "read", READ_EVERY):
            part("readers", lambda: read_now(rt))
        if _due(rt, "brain", BRAIN_EVERY):
            part("brain", lambda: brain_wake(rt))
    if _due(rt, "keep", KEEP_EVERY):
        part("keeper", lambda: keeper.run(rt.cursor(), rt.clock(), rt.data_root))
    return out


def tick_job(ctx) -> dict:
    """The `hq` job of the scheduled tick (window closed): the phone once, then a round."""
    from pflab.hq import desk, phone
    rt = desk.from_ctx(ctx)
    if rt.settings.get("preset", "full") == "off":
        return {"skipped": True, "why": "preset off"}
    start(rt)
    out = {}
    try:
        out["phone"] = phone.poll_once(rt, timeout=0)
    except Exception as e:
        out["phone"] = f"failed: {type(e).__name__}: {str(e)[:200]}"
    out.update(round_(rt, attended=False))
    return {k: (v if isinstance(v, (int, float, str)) else str(v)[:300]) for k, v in out.items()}
