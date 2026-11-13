"""Standing instructions from the chat (S85 E4, A69 door b): his words -> a typed rule -> checked by code -> in force at the next order, with Undo and Change date.

    parse(con, now, text, *, gateway_call=None, apply=False) -> {"kind", "params", "until", "summary", "needs_yes", "refused", "reason", ...}
    standing_instruction(con, now, text, *, gateway_call=None) = parse(..., apply=True): the chat's tool

THE MODEL ONLY READS: through the gateway (role `quick`, structured output) it names one KIND from a closed list, the target in his own words, an end date as ISO text and the numbers he wrote.
CODE DECIDES: the kind and params are checked against `hq/rules.py`; a name is resolved to its ISIN by code (never the model's guess); a class is checked against the book's closed list; the date is
parsed (the model's ISO date, else code reads "till 20 Nov") and sanity-checked (not past, at most 400 days; none given = 30 days, said so); every number must appear in his own words;
and the TIGHTENING test: a rule may only tighten. Anything that loosens a rail, the kill switch or his cap is refused with the reason (the model's `loosens` flag OR a code pattern);
a rule about money (an amount, a limit) waits for his Yes (`waiting_yes`); a request to change his targets, limits or stock list becomes a Yes/No question (`plan/prefs.py`, a `limit_proposals`
preference row the cards show) and nothing changes unless he says yes; anything that fits no kind becomes a NOTE the strategist reads at its next session (`rules_notes_s85`).
`apply=False` only checks (nothing is written): the screen or a test can show what would happen.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional

from pflab.hq import rules

KINDS_ASKED = ("pause_buys", "hold_name", "no_new_names", "cash_floor", "sector_exclusion", "max_position", "monthly_envelope", "dip_tranche", "change_request", "note")
CLASS_WORDS = {"gold": "gold", "bullion": "gold", "international": "international", "foreign": "international", "global": "international", "us": "international", "nasdaq": "international",
               "index": "index", "indices": "index", "nifty": "index", "etf": "index", "etfs": "index", "stocks": "stocks", "stock": "stocks", "shares": "stocks", "share": "stocks",
               "equity": "stocks", "equities": "stocks", "all": "all", "everything": "all"}
RAIL_STOCK = 0.10                                                                              # one company (paper/rails.py MAX_STOCK): a house rule may be tighter, never looser

SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {
              "kind": {"enum": list(KINDS_ASKED) + ["none"]},
              "scope": {"enum": ["class", "sleeve", "name", "all", "none"]},
              "value": {"type": "string"},
              "name": {"type": "string"},
              "market": {"enum": ["IN", "US", "both"]},
              "until": {"type": "string"},
              "share_pct": {"type": "number"},
              "terms": {"type": "array", "items": {"type": "string"}},
              "amount_rupees": {"type": "number"},
              "extra_rupees": {"type": "number"},
              "below_high_pct": {"type": "number"},
              "max_weight_pct": {"type": "number"},
              "carry_over": {"type": "boolean"},
              "change_kind": {"enum": ["targets", "stock_list", "api_cap", "none"]},
              "change_key": {"type": "string"},
              "change_value": {"type": "string"},
              "loosens": {"type": "boolean"},
              "summary": {"type": "string"}},
          "required": ["kind", "scope", "value", "name", "market", "until", "share_pct", "terms", "amount_rupees", "extra_rupees", "below_high_pct", "max_weight_pct", "carry_over",
                       "change_kind", "change_key", "change_value", "loosens", "summary"]}

SYSTEM = (
    "You read ONE message from an investor about how his paper portfolio should behave from now on and fill a form. Never decide anything and never invent: copy what he wrote.\n"
    "kind: pause_buys (stop buying a class, a sleeve or one name for a while: scope class with value gold|international|index|stocks, scope sleeve with value core|longterm, scope name with the "
    "company or symbol in `name`, or scope all), hold_name (do not sell one named holding: name), no_new_names (do not add new companies), cash_floor (keep a share of the book in cash: share_pct), "
    "sector_exclusion (no new buying in named sectors: terms), max_position (a ceiling per holding: max_weight_pct), monthly_envelope (a sum to invest each month: amount_rupees), dip_tranche "
    "(an extra sum on a fall: extra_rupees and below_high_pct), change_request (he asks to change his targets, a limit, the stock list or the monthly cap: change_kind targets|stock_list|api_cap, "
    "change_key, change_value as text: targets is a JSON object of bucket weights between 0 and 1, stock_list uses key add or remove and a symbol, api_cap a rupee number), note (a wish or a "
    "preference that is none of these), none (not an instruction).\n"
    "until: the end date as YYYY-MM-DD if he gave one (today's date is given below; a day and month with no year means the next time it comes round), else an empty string. market: IN or US if he "
    "named one, else both. loosens: true if the message would loosen a safety rail, the kill switch, a stop, the circuit breaker or the monthly cap for paid calls (a rule may only tighten). "
    "Unused numbers are 0, unused texts are empty strings, scope none. summary: his instruction in one plain sentence of at most 20 words.")

_LOOSEN = [
    re.compile(r"\bkill[- ]?switch\b", re.I),
    re.compile(r"\b(turn(ed)? off|switch(ed)? off|disable|ignore|bypass|override|remove|drop|lift|relax|loosen|suspend|go (above|over|past)|exceed|break)\b.{0,40}\b(rails?|circuit[- ]?breaker|stop[- ]?loss(es)?|stops?|guards?|position limits?|safety)\b", re.I),
    re.compile(r"\b(rails?|circuit[- ]?breaker|stop[- ]?loss(es)?|guards?)\b.{0,30}\b(off|away|do(es)? not apply|ignored)\b", re.I),
    re.compile(r"\b(no|without (any|a)|ignore the)\s+(limit|cap|rail)s?\b", re.I),
]


def _gateway(con, now):
    def call(system, messages, schema):
        from pflab.llm import gateway
        r = gateway.call(con, "quick", [{"type": "text", "text": system}], messages, purpose="standing_instruction", now=now, max_tokens=700, schema=schema) or {}
        return r.get("json") if r.get("json") is not None else r.get("text")
    return call


def _answer(raw) -> Optional[dict]:
    if isinstance(raw, dict) and "json" in raw and isinstance(raw["json"], dict):
        raw = raw["json"]
    if isinstance(raw, str):
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            raw = json.loads(m.group(0)) if m else None
        except ValueError:
            raw = None
    return raw if isinstance(raw, dict) else None


def loosens_by_pattern(text: str) -> Optional[str]:
    """The reason when his words themselves ask to loosen a rail, the kill switch or a stop (code, independent of the model); None otherwise."""
    t = text or ""
    if _LOOSEN[0].search(t) and re.search(r"\b(off|disable|remove|ignore|bypass|override|turn|switch|stop|suspend|without|no)\b", t, re.I):
        return "the kill switch sits above every rule; no instruction can turn it off or work around it"
    for p in _LOOSEN[1:]:
        if p.search(t):
            return "a rule can only tighten: the rails, the stops and the circuit breaker stay as they are, so I cannot loosen or switch them off"
    return None


# --- code's reading of the model's form ----------------------------------------------------------------------------------------------------------------

def _numbers(text: str) -> List[float]:
    out = []
    for m in re.finditer(r"(\d[\d,]*\.?\d*)", text or ""):
        try:
            out.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return out


def _in_words(text: str, x: float) -> bool:
    """A number the model gives must be a number he wrote (rule 8: no number of the model's own); lakh and crore are read."""
    t = (text or "").lower()
    ns = _numbers(t)
    if any(abs(n - x) < 1e-6 for n in ns):
        return True
    for m in re.finditer(r"(\d[\d,]*\.?\d*)\s*(k|thousand|lakh|lakhs|lac|crore|crores|cr)\b", t):
        mult = {"k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7}[m.group(2)]
        if abs(float(m.group(1).replace(",", "")) * mult - x) < 1e-6:
            return True
    return False


def _until_from_text(text: str, today: date) -> Optional[date]:
    """'till 20 Nov', 'until Dec 5', 'by 2026-12-01': read by code; a day and month already past mean next year."""
    m = re.search(r"\b(?:till|until|to|by|upto|up to)\s+(\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}(?:\s+\d{4})?|[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)\b", text or "", re.I)
    if not m:
        return None
    raw = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", m.group(1))
    try:
        from dateutil import parser as dp
        d = dp.parse(raw, default=datetime(today.year, 1, 1), dayfirst=True).date()
    except (ValueError, OverflowError):
        return None
    if not re.search(r"\d{4}", raw) and d < today:
        d = d.replace(year=d.year + 1)
    return d


def resolve_name(con, name: str, market: str = "both") -> dict:
    """A name in his words -> {"isin","symbol","market"} by code, or {"error": reason}. A symbol first, then the instrument's name (one match only); a US name by a registered US symbol or the CIK map."""
    n = " ".join((name or "").split())
    if not n:
        return {"error": "no name was given"}
    if market in ("IN", "both"):
        from pflab.paper import book
        isin = book.isin_of(con, n)
        if isin:
            return {"isin": isin, "symbol": (book.inst(con, isin)["symbol"] or n).upper(), "market": "IN"}
        like = "%" + re.sub(r"[^a-z0-9 ]", "", n.lower()).replace(" ", "%") + "%"
        rows = con.execute("SELECT isin, symbol, name FROM instruments WHERE lower(name) LIKE ? AND coalesce(listed, TRUE) AND asset_class IN ('equity', 'etf') AND coalesce(market, 'NSE') <> 'US' "
                           "ORDER BY length(name) LIMIT 4", [like]).fetchall()
        if len(rows) == 1:
            return {"isin": rows[0][0], "symbol": (rows[0][1] or n).upper(), "market": "IN"}
        if len(rows) > 1:
            return {"error": f"'{n}' could be " + " or ".join(f"{r[2]} ({r[1]})" for r in rows[:3]) + ": say which one"}
    if market in ("US", "both") and re.fullmatch(r"[A-Za-z.]{1,6}", n):
        sym = n.upper()
        r = con.execute("SELECT isin FROM instruments WHERE upper(symbol)=? AND market='US' LIMIT 1", [sym]).fetchone()
        if r:
            return {"isin": r[0], "symbol": sym, "market": "US"}
        try:
            from pflab.us import instruments as uins
            if sym in uins.load_ciks():
                return {"isin": uins.key_for(con, sym, ciks=uins.load_ciks()), "symbol": sym, "market": "US"}
        except Exception:
            pass
    return {"error": f"I do not know a listed name '{n}' in this book (give the exchange symbol)"}


def _out(**kw) -> dict:
    base = {"kind": None, "params": {}, "until": None, "summary": "", "needs_yes": False, "refused": False, "reason": None, "made": False}
    base.update(kw)
    return base


def _refuse(reason: str, **kw) -> dict:
    return _out(refused=True, reason=reason, summary=kw.pop("summary", ""), **kw)


def parse(con, now: datetime, text: str, *, gateway_call: Optional[Callable] = None, apply: bool = False, chat_id: Optional[int] = None) -> dict:
    """His words -> the typed rule, checked. With `apply=True` the rule is made (active at once with Undo; a money rule waits for Yes; a change request becomes a Yes/No question; the rest a note)."""
    text = " ".join((text or "").split())
    if len(text) < 4:
        return _refuse("say what the system should do from now on, in a sentence")
    why = loosens_by_pattern(text)
    if why:
        return _refuse(why, kind="refused_loosen")
    call = gateway_call or _gateway(con, now)
    today = now.date()
    try:
        raw = call(SYSTEM + f"\nToday is {today:%A %d %B %Y} ({today.isoformat()}).", [{"role": "user", "content": text[:1200]}], SCHEMA)
    except Exception as e:
        return _refuse(f"I could not read that just now ({type(e).__name__}); nothing was changed. Try again in a moment.", kind="unread")
    a = _answer(raw)
    if a is None:
        return _refuse("I could not turn that into a rule; nothing was changed. Say it as one plain instruction.", kind="unread")
    if a.get("loosens"):
        return _refuse("a rule can only tighten: it cannot loosen a rail, the kill switch, a stop or the monthly cap, so I did not make it", kind="refused_loosen")
    kind = a.get("kind")
    if kind in ("none", None) or kind not in KINDS_ASKED:
        return _to_note(con, now, text, a, apply, chat_id, "that is not an instruction about buying or selling")
    if kind == "note":
        return _to_note(con, now, text, a, apply, chat_id, "that fits none of the rule kinds")
    if kind == "change_request":
        return _change_request(con, now, text, a, apply)
    market = a.get("market") if a.get("market") in ("IN", "US") else None
    until_d, defaulted, err = _until(text, a, today)
    if err:
        return _refuse(err, kind=kind)
    params: Dict[str, object] = {}
    if kind == "pause_buys":
        scope, val = a.get("scope"), (a.get("value") or "").strip().lower()
        if scope == "class":
            val = CLASS_WORDS.get(val, val)
            params = {"scope": "class", "value": val}
        elif scope == "sleeve":
            params = {"scope": "sleeve", "value": val}
        elif scope == "all":
            params = {"scope": "all"}
        elif scope == "name":
            res = resolve_name(con, a.get("name") or "", market or "both")
            if "error" in res:
                return _refuse(res["error"], kind=kind)
            params = {"scope": "name", "isin": res["isin"], "symbol": res["symbol"]}
            market = market or (res["market"] if res["market"] == "US" else None)
        else:
            return _to_note(con, now, text, a, apply, chat_id, "I could not tell what to stop buying (a class, a sleeve or a name)")
    elif kind == "hold_name":
        res = resolve_name(con, a.get("name") or "", market or "both")
        if "error" in res:
            return _refuse(res["error"], kind=kind)
        params = {"isin": res["isin"], "symbol": res["symbol"]}
        market = market or (res["market"] if res["market"] == "US" else None)
    elif kind == "no_new_names":
        params = {}
    elif kind == "cash_floor":
        v = float(a.get("share_pct") or 0.0)
        if not _in_words(text, v):
            return _refuse(f"I read {v:g}% but that number is not in what you wrote: say the share of the book to keep in cash", kind=kind)
        params = {"share_pct": v}
    elif kind == "sector_exclusion":
        terms = [t.strip() for t in (a.get("terms") or []) if isinstance(t, str) and t.strip()]
        params = {"terms": terms}
    elif kind == "max_position":
        v = float(a.get("max_weight_pct") or 0.0)
        if not _in_words(text, v):
            return _refuse(f"I read {v:g}% but that number is not in what you wrote", kind=kind)
        if v > RAIL_STOCK * 100:
            return _refuse(f"the company rail is {RAIL_STOCK:.0%} of the book and a rule can only be tighter: {v:g}% would loosen it", kind=kind)
        params = {"max_weight_pct": v}
    elif kind == "monthly_envelope":
        v = float(a.get("amount_rupees") or 0.0)
        if not _in_words(text, v):
            return _refuse(f"I read Rs {v:,.0f} but that amount is not in what you wrote", kind=kind)
        params = {"amount_rupees": v, "carry_over": bool(a.get("carry_over"))}
        if until_d and not defaulted:
            params["until"] = until_d.isoformat()
    elif kind == "dip_tranche":
        x, y = float(a.get("extra_rupees") or 0.0), float(a.get("below_high_pct") or 0.0)
        if not (_in_words(text, x) and _in_words(text, y)):
            return _refuse("an amount or a percentage I read is not in what you wrote", kind=kind)
        params = {"extra_rupees": x, "below_high_pct": y}
    if market and kind in rules.NEW_KINDS:
        params["market"] = market
    bad = rules.check(kind, params)
    if bad:
        return _refuse(bad, kind=kind)
    until_out = until_d if kind in rules.NEW_KINDS else None
    probe = {"kind": kind, "machine": params, "until": until_out, "text": ""}
    summary = rules.describe(probe) if kind in rules.NEW_KINDS else _plain(kind, params, text)
    needs_yes = kind in rules.MONEY
    res = _out(kind=kind, params=params, until=until_out, summary=summary, needs_yes=needs_yes, until_defaulted=defaulted if kind in rules.NEW_KINDS else False)
    if not apply:
        return res
    made = rules.propose(con, now, kind, summary[:300], params, by="the investor (chat)", source=text[:300], until=until_out)
    if not made.get("made"):
        return {**res, "refused": True, "reason": made.get("why"), "duplicate": bool(made.get("duplicate")), "rule_id": made.get("rule_id")}
    res.update(made=True, rule_id=made["rule_id"], name=made["name"], state="waiting_yes" if needs_yes else "active", covers=made.get("covers") or [], replaces=made.get("replaces"))
    res["message"] = reply_text(res)
    return res


def _plain(kind: str, p: dict, text: str) -> str:
    if kind == "sector_exclusion":
        return "no new buying in " + ", ".join(p.get("terms") or [])
    if kind == "max_position":
        return f"no holding above {p.get('max_weight_pct'):g}% of the book"
    if kind == "monthly_envelope":
        return f"invest Rs {p.get('amount_rupees'):,.0f} a month" + (" (unspent carries over)" if p.get("carry_over") else "") + (f" until {p['until']}" if p.get("until") else "")
    if kind == "dip_tranche":
        return f"an extra Rs {p.get('extra_rupees'):,.0f} when the market is {p.get('below_high_pct'):g}% below its high"
    return text[:200]


def _until(text: str, a: dict, today: date):
    """(date, defaulted, error): the model's ISO date if code can parse it, else code's reading of his words, else DEFAULT_DAYS from today (shown as such)."""
    raw = (a.get("until") or "").strip()
    d = rules.as_date(raw) if raw else None
    if raw and d is None:
        d = _until_from_text(text, today)
    if d is None and not raw:
        d = _until_from_text(text, today)
    if d is None:
        return today + timedelta(days=rules.DEFAULT_DAYS), True, None
    if d < today:
        return None, False, f"{d:%d %b %Y} is already past: tell me an end date that is still ahead"
    if d > today + timedelta(days=rules.MAX_DAYS):
        return None, False, f"a rule runs at most {rules.MAX_DAYS} days: ask again nearer the time"
    return d, False, None


def _to_note(con, now: datetime, text: str, a: dict, apply: bool, chat_id: Optional[int], why: str) -> dict:
    res = _out(kind="note", params={}, summary=f"kept as a note for the strategist: {text[:160]}", reason=why)
    if apply:
        res.update(note_id=add_note(con, now, text, "the chat", chat_id), made=True)
        res["message"] = reply_text(res)
    return res


def _change_request(con, now: datetime, text: str, a: dict, apply: bool) -> dict:
    from pflab.plan import prefs
    ck, key, val = a.get("change_kind"), (a.get("change_key") or "").strip(), (a.get("change_value") or "").strip()
    if ck not in prefs.KINDS:
        return _refuse("I could not tell which of your targets, limits or stock list you want changed: say, for example, 'set the equity target to 55%'", kind="change_request")
    try:
        if ck == "targets":
            w = json.loads(val)
            if not isinstance(w, dict) or not all(_in_words(text, float(v) * 100.0) or _in_words(text, float(v)) for v in w.values()):
                return _refuse("a weight I read is not a number you wrote: say the target again with its percentage", kind="change_request")
            val = json.dumps(w)
        elif ck == "api_cap":
            if not _in_words(text, float(val)):
                return _refuse("the amount I read is not in what you wrote", kind="change_request")
        words = prefs.check(ck, key, val)
    except (prefs.PrefError, ValueError, TypeError) as e:
        return _refuse(f"that change cannot be made as asked ({str(e)[:160]})", kind="change_request")
    res = _out(kind="change_request", params={"prefs_kind": ck, "key": key, "value": val}, summary=f"you asked me to {words}", needs_yes=True,
               reason="your targets, limits and stock list change only with your Yes: nothing has changed")
    if not apply:
        return res
    from pflab.pm.store import next_id
    pid = prefs.propose(con, ck, key, val, text[:300], now)
    q = con.execute("SELECT q_id FROM limit_proposals WHERE prop_id = ?", [pid]).fetchone() if pid else None
    rid = next_id(con, "rules_requests_s85", "request_id")
    con.execute("INSERT INTO rules_requests_s85 VALUES (?,?,?,?,?,?,?,?,?,?)", [rid, now, text[:300], ck, key, val, pid, q[0] if q else None, "waiting_yes" if pid else "duplicate", None])
    res.update(made=bool(pid), request_id=rid, proposal_id=pid, question_id=q[0] if q else None, state="waiting_yes", duplicate=pid is None)
    res["message"] = reply_text(res)
    return res


def reply_text(r: dict) -> str:
    """What the chat says back (plain; the numbers are the rule's own)."""
    if r.get("refused"):
        return "I did not make that rule: " + str(r.get("reason"))
    k = r.get("kind")
    if k == "note":
        return "That is not one of the rules I can enforce in code, so I kept it as a note: the strategist reads it at its next session."
    if k == "change_request":
        return (f"{r['summary'].capitalize()}. That changes something that is yours, so nothing has changed: it waits for your Yes or No." if not r.get("duplicate")
                else "That change is already waiting for your Yes or No.")
    if r.get("needs_yes") or r.get("state") == "waiting_yes":
        return f"{str(r['summary']).capitalize()}. This one is about money, so it waits for your Yes; until then nothing changes."
    until = r.get("until")
    has_date = isinstance(until, date) and "until" in str(r.get("summary"))
    end = "" if has_date else (f" until {until:%d %b %Y}" if isinstance(until, date) else "")
    said = " (you gave no end date: I used 30 days)" if r.get("until_defaulted") else ""
    return f"Done: {r['summary']}{end}{said}. It acts at the next order; say 'undo' or press Undo to lift it, or give me a new end date."


# --- notes the strategist reads ------------------------------------------------------------------------------------------------------------------------

def add_note(con, now: datetime, text: str, source: str = "the chat", chat_id: Optional[int] = None) -> int:
    from pflab.pm.store import next_id
    nid = next_id(con, "rules_notes_s85", "note_id")
    con.execute("INSERT INTO rules_notes_s85 VALUES (?,?,?,?,?,?,?,?)", [nid, now, " ".join(text.split())[:600], source, chat_id, "unread", None, None])
    return nid


def unread_notes(con) -> List[dict]:
    return [{"note_id": r[0], "at": r[1], "text": r[2], "source": r[3]} for r in con.execute("SELECT note_id, created_at, text, source FROM rules_notes_s85 WHERE status = 'unread' ORDER BY note_id").fetchall()]


def take_notes_text(con, now: datetime, by: str = "strategist") -> str:
    """The unread notes as the strategist's first-message block; marks them read. Empty when there are none."""
    ns = unread_notes(con)
    if not ns:
        return ""
    con.execute("UPDATE rules_notes_s85 SET status = 'read', read_at = ?, read_by = ? WHERE status = 'unread'", [now, by])
    return ("HIS NOTES TO YOU (he said these in the chat; they fit no standing rule, so no code enforces them: weigh them in this session and say what you did with each):\n"
            + "\n".join(f"- ({n['at']:%d %b}) {n['text']}" for n in ns) + "\n\n")


# --- the chat's tool -------------------------------------------------------------------------------------------------------------------------------------------

TOOL = {"name": "standing_instruction",
        "description": ("He tells the system how to behave from now on (for example 'pause gold buys till 20 Nov', 'do not sell <name>', 'no new names this month', 'keep 15% in cash'). The rule is "
                        "checked by code and acts at the next order; it only ever tightens, a money rule waits for his Yes, a request to change his targets becomes a Yes/No question. "
                        "Pass his own words."),
        "input_schema": {"type": "object", "properties": {"text": {"type": "string", "description": "his instruction in his own words"}}, "required": ["text"]}}


def standing_instruction(con, now: datetime, text: str, *, gateway_call: Optional[Callable] = None, chat_id: Optional[int] = None) -> dict:
    """The tool function: parse and apply. -> parse's dict with `message` (what to say back)."""
    r = parse(con, now, text, gateway_call=gateway_call, apply=True, chat_id=chat_id)
    r.setdefault("message", reply_text(r))
    return r


def run_tool(con, now: datetime, args: dict, **kw) -> dict:
    return standing_instruction(con, now, str((args or {}).get("text") or ""), **kw)


def undo_by_words(con, now: datetime, ref) -> dict:
    """Undo (an id or a name) and say what happened: the next order meets the rule gone."""
    out = rules.undo(con, now, ref)
    out["message"] = (f"Undone: {out['name']}. The next order is made as if it had never been said." if out.get("undone") else "I found no active rule with that id or name.")
    return out
