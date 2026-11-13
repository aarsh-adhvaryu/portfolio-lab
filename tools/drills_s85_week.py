"""S85 `accelerated_week`: one working week of the whole system on a COPY profile, every model and the Bot API scripted (no paid call, nothing leaves the PC).

Registered in tools/drills_s81.py (`python tools/drills_s81.py run --only accelerated_week`). The drill file here holds the week: Thu 15 Oct to Thu 22 Oct 2026 (five Indian sessions, five US mornings,
a weekend, the Tuesday holiday), the app closed every night and for the whole of Monday (its session is caught up on Tuesday morning), chat traffic from both windows at every step (a PDF note
on a held name, 'look into X', a stock suggestion, a standing instruction and its Undo, a question card whose default applies on time), the engine switched claude -> a fake second engine in the middle
of Wednesday with a case in progress finishing its step on the engine that began it. Synthetic names only; the fakes are in this file.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Callable, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

HELD = {"SYNFMCG2": "INE9S2A01011", "SYNCAPG1": "INE9S3A01011", "SYNIT1": "INE9S4A01011", "SYNPICK1": "INE9S7A01011"}
GOLD = "INF9S2B01011"                                    # the synthetic gold ETF (GOLDBEES' stand-in)
Q_KEY = "week:gold_sleeve"
NOTE_QUOTE = "the board has opened an investigation into the order book"


# --- the scripted models -----------------------------------------------------------------------------------------------------------------------

class Week:
    """The state the scripted models and the checks share."""

    def __init__(self, D, env):
        self.D, self.env = D, env
        self.lock = threading.Lock()
        self.calls: Dict[str, int] = {}
        self.busy = 0                                    # chat answers being worked on right now (a model call in flight)
        self.overlap_steps = 0                           # loop steps that ran while a chat model call was in flight
        self.delay = 1.0                                # seconds a chat answer takes (so the loop and the chat really overlap)
        self.sent: List[dict] = []                       # every message he sent: {"channel","text","day"}
        self.step_secs: List[tuple] = []                 # (fake time, wall seconds, chat busy at start)
        self.scen = None
        self.counter: dict = {}
        self.tg_uid = 0
        self.fake_tg = None
        self.ent = None
        self.rule_id: Optional[int] = None

    def note_call(self, engine: str):
        with self.lock:
            self.calls[engine] = self.calls.get(engine, 0) + 1


def case_answers(case: dict, n: int) -> dict:
    sym = case.get("symbol") or "X"
    import replays_s84_model as M
    return {"happened": f"{sym} moved on the day; nothing in the stored record explains more (drill).", "sources": ["the stored closes"], "class": "market_fear", "known": "The move is in the stored closes.",
            "pending": "", "pending_date": "", "other_names": [], "choices": [{"symbol": sym, "option": "hold", "reason": "scripted: an ordinary move"}], "likelihood": M.words("unlikely", "likely", "unlikely")}


def _his_words(first: str) -> str:
    return first.rsplit("HIS MESSAGE:\n", 1)[-1].strip() if "HIS MESSAGE:" in first else first


def _symbol_in(text: str) -> str:
    m = re.search(r"\bSYN[A-Z]+\d\b", text)
    return m.group(0) if m else ""


def respond(W: Week, engine: str, call: dict) -> dict:
    """What the scripted vendor answers: structured forms by their schema, case reading by `CASE #`, the chat by his words. `{"text"}` or `{"tools": [(name, args)]}`."""
    props = set(((call.get("schema") or {}).get("properties")) or {})
    first = call.get("first") or ""
    con = W.env.cur()
    if "loosens" in props:                               # the standing-instruction form (entrance/rules_intake.py)
        gold = "gold" in first.lower()
        return {"text": json.dumps({"kind": "pause_buys", "scope": "class", "value": "gold" if gold else "", "name": "", "market": "both", "until": "2026-10-22", "share_pct": 0, "terms": [],
                                    "amount_rupees": 0, "extra_rupees": 0, "below_high_pct": 0, "max_weight_pct": 0, "carry_over": False, "change_kind": "none", "change_key": "",
                                    "change_value": "", "loosens": False, "summary": "Pause gold buys until 22 October."})}
    if {"thesis", "wait_kind"} <= props:                 # a suggested stock: the read says pass (a verdict from the closed list; the name stays watched)
        return {"text": json.dumps({"verdict": "pass", "why": "the idea is noted; the stored record gives no reason to buy yet", "thesis": "", "break_condition": "", "takes_from": "",
                                    "learned_from": "", "wait_kind": "other_event", "wait_text": ""})}
    if {"facts", "headline"} <= props:                   # a PDF read (entrance/readers.py)
        return {"text": json.dumps({"headline": "Circular on the order book", "summary": "The company circular says the board opened an investigation.",
                                    "facts": [{"claim": "The board opened an investigation into the order book.", "quote": NOTE_QUOTE, "page": 1}]})}
    if "verdict" in props:                               # the independent big-trade check
        return {"text": json.dumps({"verdict": "pass", "reason": "scripted checker: no concrete reason against it"})}
    if "CASE #" in first:                                # the thinking loop (a case)
        out = W.scen.responder(con)(call)
        return out
    if "HIS MESSAGE:" in first:                          # the chat
        with W.lock:
            W.busy += 1
        try:
            time.sleep(W.delay)
            words = _his_words(first)
            low = words.lower()
            if call.get("has_tool_result"):
                return {"text": "Done. I passed that on and the result is in the record."}
            if call.get("tools"):
                sym = _symbol_in(words)
                if "look into" in low and sym:
                    return {"tools": [("look_into", {"name": sym, "why": words})]}
                if "worth a look" in low and sym:
                    return {"tools": [("suggest_stock", {"name": sym, "reason": words})]}
                if "pause" in low and "buys" in low:
                    return {"tools": [("standing_instruction", {"text": words})]}
            return {"text": "Noted: I read it" + (", with the file" if "FILES HE SENT" in first else "") + "."}
        finally:
            with W.lock:
                W.busy -= 1
    return {"text": "Done."}


def make_clients(W: Week):
    import replays_s84_model as M

    def claude_responder(call):
        W.note_call("claude")
        return respond(W, "claude", call)
    claude = M.ScriptedClient(claude_responder, W.counter)

    class ScriptedOpenAI:
        """The OpenAI Responses wire, scripted: the same responder behind it."""

        def __init__(self):
            self.responses = NS(create=self._create)
            self.chat = NS(completions=NS(create=lambda **p: (_ for _ in ()).throw(RuntimeError("drill: the chat wire is not used"))))
            self.sent = 0

        def _create(self, **p):
            items = p.get("input") or []
            first = ""
            for it in items:
                if it.get("role") == "user":
                    c = it.get("content")
                    first = c if isinstance(c, str) else "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                    break
            has_tr = any(it.get("type") == "function_call_output" for it in items)
            schema = ((p.get("text") or {}).get("format") or {}).get("schema")
            W.note_call("openai")
            self.sent += 1
            out = respond(W, "openai", {"model": p["model"], "schema": schema, "has_tool_result": has_tr, "first": first, "tools": bool(p.get("tools")), "messages": items})
            W.counter["answers"] = W.counter.get("answers", 0) + 1
            if "tools" in out:
                body = [NS(type="reasoning")] + [NS(type="function_call", call_id=f"oc{self.sent}_{i}", name=n, arguments=json.dumps(a)) for i, (n, a) in enumerate(out["tools"])]
            else:
                body = [NS(type="reasoning"), NS(type="message", content=[NS(type="output_text", text=out["text"])])]
            return NS(output=body, status="completed", model=p["model"] + "-2026", usage=NS(input_tokens=1500, output_tokens=300, input_tokens_details=NS(cached_tokens=0)))
    return claude, ScriptedOpenAI()


# --- the transports -----------------------------------------------------------------------------------------------------------------------------

def tg_entrance(W: Week):
    from pflab.service import tg_api
    from pflab.service.tg_entrance import Entrance
    env = W.env
    api = tg_api.TgApi(W.fake_tg.token, W.fake_tg.chat_id, W.fake_tg.transport, W.fake_tg.downloader, sleep=lambda s: None)
    return Entrance(api, W.fake_tg.chat_id, rt=env.rt, legacy=lambda t: "legacy: " + t, inbox_dir=env.dir / "tg_inbox")


def tg_poll(W: Week) -> int:
    """The bot's poll: whatever is waiting at the (fake) Bot API goes through `bot.process`, the way the app's bot does it."""
    from pflab.service import bot
    env = W.env
    ups, W.fake_tg.queue = W.fake_tg.queue, []
    if not ups:
        return 0
    if W.ent is None:
        W.ent = tg_entrance(W)
    return bot.process(env.cur(), ups, str(W.fake_tg.chat_id), lambda t: None, lambda t: "OLD PATH", env.clock.t, entrance=W.ent)


def laptop(W: Week, text: str, attachments=None) -> dict:
    from pflab.entrance import intake
    out = intake.submit(W.env.rt, "laptop", text, attachments=attachments)
    W.sent.append({"channel": "laptop", "text": text, "day": str(W.env.clock.t.date()), "item": out["item_id"]})
    return out


def telegram(W: Week, text: str = "", pdf: Optional[bytes] = None, name: str = "circular.pdf") -> None:
    W.tg_uid += 1
    if pdf is not None:
        W.fake_tg.add_document(W.tg_uid, name, pdf, caption=text)
    else:
        W.fake_tg.add_text(W.tg_uid, text)
    W.sent.append({"channel": "telegram", "text": text or name, "day": str(W.env.clock.t.date()), "uid": W.tg_uid})


def wait_idle(W: Week, secs: float = 25.0) -> bool:
    end = time.time() + secs
    cur = W.env.cur()
    while time.time() < end:
        n = cur.execute("SELECT count(*) FROM intake_queue_s85 WHERE state IN ('queued','working')").fetchone()[0]
        if n == 0:
            return True
        time.sleep(0.1)
    return False


# --- the week ------------------------------------------------------------------------------------------------------------------------------------

def run(env, c, D) -> None:
    """`env`: the drill's Env on a clone of the base profile; `c`: its Check; `D`: tools/drills_s81 (the harness)."""
    from pflab import core, markets
    from pflab.entrance import intake
    from pflab.llm import gateway as gate
    from pflab.agents import analyst as an
    from pflab.agents import questions
    from fake_telegram import FakeTelegram
    import replays_s84_model as M
    from tests.test_s85_readers import make_pdf

    W = Week(D, env)
    W.fake_tg = FakeTelegram()
    env.week = W
    W.scen = M.Scenario("week", case_answers)
    claude, oa = make_clients(W)
    gate.set_client(claude, engine="claude")
    gate.set_client(oa, engine="openai")
    cfg = {"model": "claude-opus-5-5", "cap": 300.0, "ask_above": 1000.0, "usd_inr": 90.0, "adopted": True, "policy": {}, "acceptance": {}, "paper": {}, "tijori_to_analyst": True, "counted_since": None}
    an.config = lambda path=None: dict(cfg)
    real_settings = core.settings

    def week_settings():                                 # the drill's copy of the baseline wants more gold (so that a gold buy is due at a close); his targets file is untouched
        s = real_settings()
        b = dict(s["baseline_v2"])
        b["gold_pct"] = 22.0
        return {**s, "baseline_v2": b}
    core.settings = week_settings
    from pflab.core import premium as prem
    real_prem = prem.settings
    prem.settings = lambda cfg=None: {**real_prem(cfg), "unknown": "allow"}                    # the synthetic profile has no NAV series: the premium rail would never let gold be bought (its own tests cover the rail)
    real_key_set = gate.key_set
    gate.key_set = lambda st, name: True                 # the second engine's key is a stand-in: nothing is read from the secrets file and no real client is made (set_client)
    m = markets.get("IN")
    thu, fri = env.start, m.next_session(env.start)
    mon = m.next_session(fri)
    tue = mon + timedelta(days=1)
    wed = m.next_session(mon)
    thu2 = m.next_session(wed)
    c.note(f"the week: Thu {thu}, Fri {fri}, [weekend], Mon {mon} (the app is off all day), Tue {tue} (holiday: the app opens at 09:00), Wed {wed}, Thu {thu2}")
    # his scope for the reader: the held names and their ISINs (so that a PDF can be linked)
    from pflab.kg2 import scope as sc
    scope = {"version": 1, "names": [{"isin": i, "symbol": s, "name": s, "text": True, "aliases": [s.lower()]} for s, i in HELD.items()], "extra_isins": []}
    sp = sc.scope_path(env.data)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(scope), encoding="utf-8")

    pdf = make_pdf([["Company circular about " + HELD["SYNIT1"] + " (SYNIT1).", "This is the one page of the circular.", "On the day " + NOTE_QUOTE + " and will report."]])
    pdf_path = env.dir / "circular.pdf"
    pdf_path.write_bytes(pdf)

    state = {"engine_switched": None, "mid_probe": None, "q_deadline": None, "tg_events": 0}

    def opened(t: datetime) -> None:
        """The app opens (a new process): the runtime starts, the intake's workers come up (and resume what a stop left), the bot's entrance is made again."""
        intake.stop()
        env.open_app(t)
        intake.stop()
        intake.start(env.rt)
        W.ent = None

    def closed() -> None:
        """The app closes: what is in flight finishes (the shutdown waits), then the process ends (the store is released)."""
        wait_idle(W, 30.0)
        intake.stop()
        env.con.close()
        env.connect()

    def at(t: datetime, fn: Callable) -> None:
        pass

    # ---- the script: (day, hour) -> what he does at that step (before the loop's step runs)
    def his(t: datetime) -> None:
        d, h = t.date(), t.hour
        if d == thu and h == 7:
            laptop(W, "Good morning, anything I should know today?")
            telegram(W, "thanks")
        if d == thu and h == 10:
            laptop(W, "look into SYNFMCG2, the price has been weak lately")
            telegram(W, "from the company, for the file", pdf=pdf, name="circular.pdf")
        if d == thu and h == 13:
            laptop(W, "I think SYNPICK1 is worth a look, pharma demand looks strong")
        if d == thu and h == 16:
            telegram(W, "what do you know about SYNIT1?")
        if d == thu and h == 18:
            state["q_deadline"] = dt(fri, 18)
            questions.ask(env.cur(), "auditor", Q_KEY, "Is the gold sleeve to stay as it is?", env.clock.t, default="keep as is", deadline=dt(fri, 18), options=["keep as is", "change"])
        if d == fri and h == 7:
            telegram(W, "good morning from the phone")
        if d == fri and h == 10:
            laptop(W, "pause gold buys till 22 Oct")
        if d == fri and h == 13:
            laptop(W, "look into SYNCAPG1, I read something about its order book")
        if d == fri + timedelta(days=1) and h == 9:                       # Saturday: Undo from the phone's button
            rid = W.rule_id
            W.fake_tg.add_callback(9000 + W.tg_uid + 1, f"undo:{rid}")
            W.tg_uid += 1
            telegram(W, "the Undo is pressed on my phone")
        if d == mon and h == 11:                                          # the app is off: Telegram holds what he sends
            telegram(W, "are you there?")
            telegram(W, "what happened on Monday?")
        if d == wed and h == 10:
            laptop(W, "look into SYNCAPG1 again, is there any news?")
        if d == wed and h == 13:
            telegram(W, "look into SYNPICK1, is it a good time")
            laptop(W, "thanks, that helps")
        if d == thu2 and h == 10:
            telegram(W, "what did the loop decide this week?")

    def dt(d: date, h: int, m: int = 0) -> datetime:
        return datetime(d.year, d.month, d.day, h, m)

    def after_step(t: datetime) -> None:
        """Between steps: the bot's poll, the answers, a rule id remembered, the engine switch."""
        tg_poll(W)
        if W.rule_id is None:
            row = env.cur().execute("SELECT rule_id FROM hq_rules WHERE kind='pause_buys' AND status='active' ORDER BY rule_id DESC LIMIT 1").fetchone()
            if row:
                W.rule_id = int(row[0])
                c.note(f"rule {W.rule_id} in force after his words at {t:%a %d %H:%M}: " + str(env.cur().execute("SELECT name FROM hq_rules WHERE rule_id=?", [W.rule_id]).fetchone()[0]))

    def switch_engine(t: datetime) -> None:
        cur = env.cur()
        before = gate.current_engine(cur)
        gate.grant(cur, "openai", "use", now=t, given_by="his Yes (the drill's script)", wording="drill: the switch is the script's")
        gate.record_exam(cur, "openai", form_pass=True, grade="passed in the drill (scripted)", now=t)
        r = gate.use(cur, "openai", yes=True, now=t)
        c.ok(bool(r.get("ok")) and gate.current_engine(cur) == "openai", f"the engine switched {before} -> openai with his Yes on record and the exam recorded as passed ({r.get('reason') or 'ok'})", "llm/gateway.py use")
        state["engine_switched"] = t
        # a case that began before the switch finishes its step on the engine that began it
        row = cur.execute("SELECT s.case_id, max(s.step_at) FROM think_steps_s84 s WHERE s.engine='claude' AND s.model<>'' GROUP BY 1 ORDER BY 2 DESC LIMIT 1").fetchone()
        if row:
            probe = gate.call(cur, "read", "Scripted mid-case probe.", [{"role": "user", "content": [{"type": "text", "text": f"CASE #{row[0]} mid-case probe"}]}], case_id=int(row[0]), purpose="week_midcase_probe",
                              now=row[1] + timedelta(minutes=5), agent="think")
            state["mid_probe"] = {"case": int(row[0]), "engine": probe.get("engine"), "t": t}
        else:
            state["mid_probe"] = {"case": None, "engine": None, "t": t}

    # ---- run: day by day, the app open from the morning to 23:00 and closed overnight
    last_end = None
    plan = [thu, fri, fri + timedelta(days=1), fri + timedelta(days=2), tue, wed, thu2]
    first_open = True
    for d in plan:
        times = D.day_times(d)
        for i, t in enumerate(times):
            if first_open:
                opened(dt(thu, 6))
                first_open = False
            elif i == 0:
                opened(t)                                                  # the app opens this morning (a new process: the on-open catch-up runs)
            else:
                env.clock.set(t)
            if d == tue and i == 0:
                tg_poll(W)                                                 # the bot's first poll after opening picks up what he sent while it was off
            his(t)
            tg_poll(W)
            busy0 = W.busy
            seen = threading.Event()
            stop_s = threading.Event()

            def sampler():
                while not stop_s.is_set():
                    if W.busy > 0:
                        seen.set()
                    time.sleep(0.03)
            th = threading.Thread(target=sampler, daemon=True)
            th.start()
            t0 = time.time()
            env.step(t, continuous=(i != 0))
            stop_s.set()
            th.join(1)
            W.step_secs.append((t, round(time.time() - t0, 2), busy0))
            if busy0 > 0 or seen.is_set():
                W.overlap_steps += 1
            after_step(t)
            if d == wed and t.hour == 10:
                wait_idle(W, 20.0)
                switch_engine(dt(wed, 10, 10))
            if d == fri and t.hour == 21:
                state["fri_close"] = True
            if d == fri + timedelta(days=1) and t.hour == 9:
                pass
            if t.hour in (7, 10, 13, 16, 18, 9) or True:
                wait_idle(W, 25.0)
        if d == fri + timedelta(days=2):                                   # Sunday night: the app closes, and stays off for all of Monday (his phone still sends)
            his(dt(mon, 11))
            closed()
            continue
        if d != tue or True:
            closed()
    # ---- the checks
    core.settings = real_settings
    prem.settings = real_prem
    gate.key_set = real_key_set
    gate.set_client(None)
    check(env, c, W, D, state, dict(thu=thu, fri=fri, mon=mon, tue=tue, wed=wed, thu2=thu2))


def check(env, c, W: Week, D, state: dict, days: dict) -> None:
    from pflab import markets
    from pflab.entrance import intake, store
    from pflab.hq import rules
    from pflab.agents import voice
    from pflab.think import cases
    m = markets.get("IN")
    cur = env.cur()
    thu, fri, mon, tue, wed, thu2 = (days[k] for k in ("thu", "fri", "mon", "tue", "wed", "thu2"))
    sessions = [thu, fri, mon, wed, thu2]

    # ---- nothing lost
    idle = wait_idle(W, 20.0)
    c.ok(idle, "the intake's queue is empty at the end of the week", "entrance/intake.py")
    items = cur.execute("SELECT item_id, chat_id, msg_id, reply_msg_id, channel, state, error FROM intake_queue_s85 ORDER BY item_id").fetchall()
    c.ok(all(r[5] in ("done", "failed") for r in items), f"every queued message ended done or failed ({sorted({r[5] for r in items})}; {len(items)} items)", "entrance/intake.py")
    n_sent = len(W.sent)
    n_me = cur.execute("SELECT count(*) FROM chat_messages WHERE role='me'").fetchone()[0]
    c.ok(n_me == n_sent, f"every message he sent is stored once: sent {n_sent}, stored {n_me}", "entrance/store.py")
    answers = cur.execute("SELECT m.msg_id, count(a.msg_id) FROM chat_messages m LEFT JOIN chat_messages a ON a.reply_to = m.msg_id AND a.role='ai' WHERE m.role='me' GROUP BY 1").fetchall()
    c.ok(all(n == 1 for _, n in answers), f"every message has exactly one answer ({sorted({n for _, n in answers})} answers per message over {len(answers)} messages)", "entrance/intake.py")
    bad = cur.execute("SELECT msg_id, status, substr(text,1,80) FROM chat_messages WHERE role='ai' AND reply_to IS NOT NULL AND status NOT IN ('done','failed')").fetchall()
    c.ok(not bad, f"no answer is left pending or working ({bad[:3]})", "entrance/store.py")
    failed = cur.execute("SELECT msg_id, substr(text,1,120) FROM chat_messages WHERE role='ai' AND status='failed'").fetchall()
    c.ok(all((t or "").strip() for _, t in failed), f"a failed answer says so in words ({len(failed)} failed)", "entrance/intake.py")
    tg_items = [r for r in items if r[4] == "telegram"]
    n_tg_sent = len([x for x in W.sent if x["channel"] == "telegram"])
    shown = [x for x in W.fake_tg.shown if not x.get("deleted")]
    c.ok(len(shown) >= len(tg_items) and len(tg_items) >= 5, f"Telegram: {len(tg_items)} messages from the phone, {len(shown)} messages shown on it (answers, undo line)", "service/tg_entrance.py")
    c.ok(cur.execute("SELECT count(*) FROM bot_updates").fetchone()[0] == n_tg_sent + 1, f"every update the Bot API held was taken once ({cur.execute('SELECT count(*) FROM bot_updates').fetchone()[0]} for {n_tg_sent} messages and one button press)", "service/bot.py")

    # ---- nothing twice
    dup_case = cur.execute("SELECT isin, opened_on, kind, count(*) FROM think_cases_s84 GROUP BY 1,2,3 HAVING count(*) > 1").fetchall()
    c.ok(not dup_case, f"no case was opened twice for the same name, kind and day ({dup_case[:3]})", "think/cases.py open_or_join")
    dup_dec = cur.execute("SELECT decision_id FROM paper_orders GROUP BY 1 HAVING count(*) > 1").fetchall()
    c.ok(not dup_dec, f"no decision has two orders ({len(dup_dec)})", "core/loop.py")
    dup_ord = cur.execute("SELECT o.isin, o.side, d.ref_date, count(*) FROM paper_orders o JOIN paper_decisions d USING (decision_id) GROUP BY 1,2,3 HAVING count(*) > 1").fetchall()
    c.ok(not dup_ord, f"no order twice for the same name, side and close ({dup_ord[:3]}; {cur.execute('SELECT count(*) FROM paper_orders').fetchone()[0]} orders in all)", "paper/orders")
    dup_sys = cur.execute("SELECT text, count(*) FROM chat_messages WHERE role<>'me' AND kind IN ('loop','card','system') GROUP BY 1 HAVING count(*) > 1").fetchall()
    c.ok(not dup_sys, f"no proactive message was posted twice ({[(t[:50], n) for t, n in dup_sys[:3]]})", "entrance/store.py post_system")
    dup_dec2 = cur.execute("SELECT case_id, decided_on, isin, count(*) FROM think_decisions_s84 GROUP BY 1,2,3 HAVING count(*) > 1").fetchall()
    c.ok(not dup_dec2, f"no case decision was stored twice on a day ({dup_dec2[:3]})", "think/session.py")

    # ---- the sessions: every one closed and marked once, Monday's caught up on Tuesday
    marked = [r[0] for r in cur.execute("SELECT day FROM paper_days WHERE day >= ? ORDER BY day", [thu]).fetchall()]
    c.ok(marked == sessions, f"every Indian session was marked once, Monday's caught up after the day off: {[str(d) for d in marked]}", "paper/book.py catch_up")
    runs = {r[0]: (r[1], r[2]) for r in cur.execute("SELECT day, status, ran_at FROM core_runs_s80 WHERE day >= ?", [thu]).fetchall()}
    c.ok(all(d in runs for d in sessions), f"the close loop ran for every session ({[str(d) for d in sorted(runs)]})", "core/loop.py")
    late = []
    for d in sessions:
        r = runs.get(d)
        limit = dt_of(d, 23, 59) if d != mon else dt_of(tue, 23, 59)
        if r is None or r[1] > limit:
            late.append((str(d), str(r[1]) if r else None))
    c.ok(not late, f"no close was delayed past its own evening (Monday's past the opening Tuesday): late {late}", "core/loop.py, entrance isolation")
    mon_run = runs.get(mon)
    c.ok(mon_run is not None and mon_run[1] >= dt_of(tue, 9), f"Monday's close was caught up once the app opened on Tuesday ({mon_run})", "service/catchup.py")
    c.ok(cur.execute("SELECT count(*) FROM (SELECT day FROM core_runs_s80 GROUP BY 1 HAVING count(*) > 1)").fetchone()[0] == 0, "no session was closed twice", "core/loop.py")
    fc = [r[0] for r in cur.execute("SELECT as_of FROM forecasts_s79 WHERE source='live' AND market='IN' GROUP BY as_of").fetchall()]
    c.ok(all(d in fc for d in sessions), f"every missed session was forecast once the app opened (forecasts: {sorted(str(d) for d in fc)[-6:]})", "service/catchup.py")
    sc = cur.execute("SELECT count(*), count(DISTINCT forecast_id) FROM forecast_scores_s79 WHERE source='live'").fetchone()
    c.ok(sc[0] == sc[1], f"no forecast was scored twice ({sc[0]} scores, {sc[1]} forecasts)", "fcast/score.py")

    # ---- the desk every day, the US mornings, the cases looked at when due
    desk = cur.execute("SELECT day, mode, status FROM desk_sessions_s84 ORDER BY day, session_id").fetchall()
    dd = {}
    for d, mode, st in desk:
        dd.setdefault(d, []).append((mode, st))
    open_days = [thu, fri, fri + timedelta(days=1), tue, wed, thu2]
    c.ok(all(d in dd for d in open_days), f"the daily desk worked on every day the app was open ({ {str(k): [x[0] for x in v] for k, v in dd.items()} })", "think/desk.py")
    notdone = [(str(k), mo, st) for k, v in dd.items() for mo, st in v if st != "done"]
    why = cur.execute("SELECT note FROM desk_sessions_s84 WHERE status<>'done'").fetchall()
    c.ok(not notdone, f"every desk session finished ({notdone}: {why})", "think/desk.py")
    um = sorted(d for d, v in dd.items() if any(x[0] == "us_morning" for x in v))
    c.ok(len(um) >= 5, f"five US mornings were worked ({[str(d) for d in um]})", "think/desk.py")
    c.ok(any(x[0] == "catchup" and d == tue or d == mon for d, v in dd.items() for x in v) or any(d == mon for d in dd), f"Monday's session was worked on after the gap ({[(str(k), [x[0] for x in v]) for k, v in dd.items() if k in (mon, tue)]})", "think/desk.py")
    cs = cases._rows(cur, "think_cases_s84", cases._CASE)
    yours = [x for x in cs if x["opened_by"] == "you"]
    c.ok(len(yours) >= 3, f"his looks, note and suggestions opened cases ({[(x['symbol'], x['state']) for x in yours]})", "think/chat_hooks.py")
    unthought = []
    for x in yours:
        steps = [s for s in cases.steps(cur, x["case_id"]) if s["model"]]
        if x["state"] not in ("noticed",) and not steps:
            unthought.append((x["symbol"], x["state"]))
    c.ok(not unthought, f"every case he asked for was looked at ({unthought})", "think/session.py")
    multi = cur.execute("""SELECT case_id, count(DISTINCT d) FROM (SELECT case_id, CAST(step_at AS DATE) d FROM think_steps_s84 WHERE model <> ''
                           UNION SELECT CAST(substr(ref, 6) AS BIGINT), CAST(step_at AS DATE) FROM desk_steps_s84 WHERE kind='case' AND model <> '' AND ref LIKE 'case:%') GROUP BY 1 HAVING count(DISTINCT d) >= 2""").fetchall()
    c.ok(bool(multi), f"cases were followed up on later days, by the loop or the desk ({len(multi)} case(s) read on two days or more)", "think/wire.py _follow, think/desk.py")
    overdue = []
    for x in cs:
        due = x.get("next_look_on")
        if x["state"] in ("open", "case") and due is not None and due <= wed:
            last = cur.execute("SELECT max(CAST(step_at AS DATE)) FROM think_steps_s84 WHERE case_id=? AND model <> ''", [x["case_id"]]).fetchone()[0]
            if last is None or last < due:
                overdue.append((x["symbol"], str(due), str(last)))
    c.ok(not overdue, f"every case with a look due by Wednesday was looked at on or after its day ({overdue})", "think/wire.py _follow")
    queued = [x["symbol"] for x in cs if x["state"] == "noticed"]
    c.note(f"cases still only noticed (queued behind the day's three, or not yet due): {queued}")
    note_case = cur.execute("SELECT count(*) FROM think_case_origin_s85 o JOIN think_cases_s84 c USING (case_id) WHERE c.isin=?", [HELD["SYNIT1"]]).fetchone()[0]
    c.ok(note_case >= 1, f"his PDF note on a held name (SYNIT1) opened a case ({note_case})", "think/chat_hooks.py note_from_him")
    doc = cur.execute("SELECT status FROM received_docs_s85 ORDER BY doc_id DESC LIMIT 1").fetchone()
    c.ok(doc is not None and doc[0] == "read", f"the PDF was read and kept ({doc})", "entrance/readers.py")
    c.ok(cur.execute("SELECT count(*) FROM watch_from_you_s85 WHERE isin=?", [HELD["SYNPICK1"]]).fetchone()[0] >= 1, "the suggested stock joined the watch list 'from you'", "think/chat_hooks.py suggest_stock")

    # ---- the standing instruction: honoured by the next close, restored by Undo
    held = cur.execute("SELECT rule_id, site, side, day FROM rules_held_back_s85 ORDER BY day").fetchall()
    c.ok(W.rule_id is not None, f"'pause gold buys' became rule {W.rule_id}", "entrance/rules_intake.py")
    gold_orders = cur.execute("SELECT CAST(placed_at AS DATE), side, status FROM paper_orders WHERE isin=? ORDER BY placed_at", [GOLD]).fetchall()
    c.note(f"gold orders: {[(str(a), b) for a, b, _ in gold_orders]}; held back by a rule: {[(r[0], r[1], r[2], str(r[3])) for r in held]}")
    pause_rows = [r for r in held if r[0] == W.rule_id and r[2] == "buy"]
    c.ok(bool(pause_rows), f"the close after his words bought no gold and recorded the rule as the reason ({len(pause_rows)} order(s) held back)", "core/loop.py rules.blocks")
    undone = cur.execute("SELECT status FROM hq_rules WHERE rule_id=?", [W.rule_id]).fetchone()
    c.ok(undone is not None and undone[0] == "undone", f"Undo from the phone's button lifted it ({undone})", "service/tg_entrance.py")
    last_held = max((r[3] for r in pause_rows), default=None)
    later = [x for x in gold_orders if x[1] in ("buy", "BUY") and last_held is not None and x[0] > last_held]
    c.ok(bool(later), f"after Undo the close bought gold again ({[(str(a), b) for a, b, _ in later][:3]})", "hq/rules.py undo, core/loop.py")

    # ---- the question card: the default applied on time
    eff = voice.effective(cur, Q_KEY)
    c.ok(eff[0] == "keep as is" and eff[1] in ("default", "him"), f"the question card's default applied on time ({eff})", "agents/voice.py, entrance/cards.py")
    qm = cur.execute("SELECT count(*) FROM chat_messages WHERE kind='card'").fetchone()[0]
    c.ok(qm >= 1, f"the question was a card in the chat ({qm})", "entrance/cards.py")

    # ---- the engine switch
    sw = state.get("engine_switched")
    c.ok(sw is not None, "the engine was switched in the middle of Wednesday", "tools/drills_s85_week.py")
    mp = state.get("mid_probe") or {}
    c.ok(mp.get("engine") == "claude", f"a case in progress finished its step on the engine that began it ({mp})", "llm/gateway.py case_pin_minutes")
    rows = cur.execute("SELECT engine, count(*) FROM api_calls WHERE status IN ('done','submitted') GROUP BY 1").fetchall()
    by = dict(rows)
    c.ok(by.get("claude", 0) > 0 and by.get("openai", 0) > 0, f"calls are stored per engine ({by}); the fake engines answered {W.calls}", "llm/gateway.py")
    before = cur.execute("SELECT count(*) FROM api_calls WHERE engine='openai' AND created_at < ?", [sw]).fetchone()[0] if sw else None
    c.ok(before == 0, f"nothing went to the second engine before the switch ({before})", "llm/gateway.py")
    nopr = cur.execute("SELECT count(*) FROM api_calls WHERE status='done' AND (coalesce(engine,'')='' OR coalesce(model,'')='' OR cost_inr IS NULL)").fetchone()[0]
    c.ok(nopr == 0, f"every call is stored with its engine, model and price ({nopr} without)", "hq/llm.py record")
    steps_all = cur.execute("SELECT engine, model, thinking, count(*) FROM think_steps_s84 WHERE model<>'' GROUP BY 1,2,3").fetchall()
    c.ok(bool(steps_all) and all(e and mo and th for e, mo, th, _ in steps_all), f"every case step stores its engine, model and thinking level ({steps_all})", "think/session.py")
    after_claude = cur.execute("SELECT count(*) FROM think_steps_s84 s JOIN think_cases_s84 c USING (case_id) WHERE s.engine='claude' AND c.opened_on > ?", [sw.date()]).fetchone()[0] if sw else None
    c.note(f"case steps on claude for cases opened after the switch day: {after_claude}")
    try:
        from pflab.think import score
        be = score.by_engine(cur)
        c.note(f"per-engine scorecard keys after the switch: {sorted(be)}")
        made = score.engine_of_decisions(cur)
        c.note(f"decisions by the engine that read the case: { {e: sum(1 for x in made.values() if x == e) for e in set(made.values())} }")
        c.ok("openai" in be and (set(made.values()) <= set(be)), f"per-engine scorecards stay apart: every engine that decided has its own record ({sorted(be)})", "think/score.py by_engine")
    except Exception as e:
        c.ok(False, f"score.by_engine failed: {type(e).__name__}: {e}", "think/score.py")

    # ---- isolation, no paid call, no error
    over = W.overlap_steps
    c.ok(over >= 3, f"the loop's steps ran while the chat was answering ({over} overlapped); slowest step {max(s[1] for s in W.step_secs)} s", "entrance/intake.py")
    c.ok(max(s[1] for s in W.step_secs) < 60, f"no loop step was held up by the chat (slowest {max(s[1] for s in W.step_secs)} s)", "entrance/intake.py")
    api = cur.execute("SELECT count(*) FROM api_calls WHERE status IN ('done','submitted','running','sending')").fetchone()[0]
    c.ok(api == sum(W.calls.values()), f"every stored call was a scripted answer ({api} stored, {sum(W.calls.values())} scripted: nothing paid)", "hq/governor.py")
    D.jobs_not_failed(cur, c)
    c.ok(not env.failed_jobs, f"no job failed ({env.failed_jobs[:3]})", "service/jobs.py")
    D.clean(env, c, "the week")
    pit = cur.execute("SELECT count(*) FROM paper_decisions WHERE ref_date IS NOT NULL AND ref_date > CAST(made_at AS DATE)").fetchone()[0]
    c.ok(pit == 0, f"point in time: no decision refers to a later close ({pit})", "core/loop.py")


def dt_of(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m)
