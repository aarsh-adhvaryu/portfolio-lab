"""T3 UNDERSTAND and choose, T6 act and tell, T7 come back (S84, A65-A66). One case, one short session with the one door for model calls (`llm/gateway.py`).

    think_case(con, now, case_id)   Sonnet (role `read`) reads first, with tools (the case's signals, what we already know, the graph, a web check, the company card, base rates, the outcome
                                    table); Opus (role `decide`) answers when the book's exposure to the case is over `[think] opus_exposure_share` of the book or the case could spend the
                                    reserve (the book does not hold the name). The answer is STRUCTURED from the closed lists (`think.CLASSES`, `think.OPTIONS`, `think.WORDS`) and carries no
                                    number: a number, a size, an unknown word or a figure the sources do not hold is refused and asked once more. Code then builds the outcome table (`odds`), the
                                    registered rule decides (`rule`), BOTH choices are stored, the rule acts (`act`) unless the loop is advisory (then only a thesis-break sale acts).
    act(con, now, case_id, decision)  orders through the existing paths with the reason "case #N": a sale through the exit manager (kind `case`; the 12-month guard weighs it), a reserve buy as a
                                    paper order inside the rails and the reserve (a sub-book buy as a US order), a freeze as a system-made rule the baseline, the picks and the US step read.
                                    A sale over `[think] big_trade_share` of the book and every reserve buy pass the independent big-trade check first.
    follow_up(con, now, day)        T7: due looks (re-thought only when something changed), the next part of a buy in parts, closing (answered and decided, or quiet).
    tell(con, now, case_id)         the plain Telegram text when a case acts or opens on more than 2% of the book.
    thinking_text(con, day)         the "Thinking about" block and the reserve line for Today and the 15:45 report.

The model's failure, the cap reached or a missing module leaves the case OPEN with a stored "failed" step: the exit manager's own thesis-break sales are not in this path and still act, nothing else changes.
Dependencies are looked up by name (`DEPS`, for tests and for the pieces built beside this one) so a missing module is a visible failure of one case, never an error in the close.
"""
from __future__ import annotations

import importlib
import json
import re
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional

from pflab import think
from pflab.think import cases, reserve

DEPS: Dict[str, object] = {}                       # tests and callers may put a fake here: gateway, recall, odds, rule, score
_MODULES = {"gateway": "pflab.llm.gateway", "recall": "pflab.think.recall", "odds": "pflab.think.odds", "rule": "pflab.think.rule", "score": "pflab.think.score"}
MAX_TOOL_TURNS = 4
MAX_CHOICES = 6
MIN_RESERVE_BUY_INR = 1000.0
FORBIDDEN_KEYS = {"size", "size_inr", "price", "weight", "probability", "p", "amount", "rupees", "inr", "pct", "percent", "quantity", "qty", "target", "stop", "shares", "worst_inr", "likely_inr",
                  "best_inr", "expected_inr"}

SYSTEM = """You are the THINKING DESK of a small paper portfolio of Indian shares and ETFs (and a small US paper sub-book). A situation has been noticed by code: a price move, a news event, a missed run. You read it, connect it with what is already known, and say what kind of situation it is and what to do about each affected holding or chance. You trade nothing and you write no number that a decision rests on: code makes every rupee, size, price and probability; a registered rule in code decides and acts.

WHAT YOU ANSWER (structured, from closed lists only)
- happened: two short lines, with where you read it (sources). Facts only.
- class: market_fear (the market or the sector is afraid, the business is intact) / temporary (a company problem that looks temporary) / damage (damage to the business or its governance) / unclear (not yet clear).
- known and pending: what is known, and what is still PENDING, named (a board decision, a result, a regulator, a date). If the pending outcome has since become public, give the day it did (pending_resolved_on, YYYY-MM-DD); otherwise leave it out.
- other_names: other names touched (peers, funds, suppliers), by symbol.
- choices: for each affected holding or opportunity ONE option from: sell, trim, hold, freeze (no new buying), wait (for the pending event), buy_in_parts, nothing. Give the symbol and a short reason.
- likelihood: for the worst, the likely and the best outcome a likelihood WORD (very unlikely, unlikely, even, likely, very likely), and which base-rate set fits (5, 20 or 60 sessions, or own range) with its reason.
RULES: never write a number, a size, a price, a weight or a probability as a field; do not invent figures in the text (a figure appears only if a tool or the message gave it). A governance shock (the chief executive, chair or a founder investigated, ousted or linked to a crime; a promoter arrested) is damage until shown otherwise. Do not buy a name that is still falling or whose outcome is pending. Use the tools to check, briefly; one web check at most unless it is truly needed. If the notes already known cover the subject and nothing has happened since, say so and do not buy the same facts again."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "happened": {"type": "string", "maxLength": 600},
        "sources": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 8},
        "class": {"enum": list(think.CLASSES)},
        "known": {"type": "string", "maxLength": 500},
        "pending": {"type": "string", "maxLength": 300},
        "pending_date": {"type": "string", "maxLength": 10},
        "pending_resolved_on": {"type": "string", "maxLength": 10},
        "other_names": {"type": "array", "items": {"type": "string", "maxLength": 24}, "maxItems": 8},
        "choices": {"type": "array", "maxItems": MAX_CHOICES, "items": {"type": "object", "properties": {
            "symbol": {"type": "string", "maxLength": 24}, "option": {"enum": list(think.OPTIONS)}, "reason": {"type": "string", "maxLength": 300}}, "required": ["symbol", "option", "reason"]}},
        "likelihood": {"type": "object", "properties": {"worst": {"enum": list(think.WORDS)}, "likely": {"enum": list(think.WORDS)}, "best": {"enum": list(think.WORDS)},
                                                         "base_rate_set": {"enum": ["5", "20", "60", "own range"]}, "reason": {"type": "string", "maxLength": 300}},
                       "required": ["worst", "likely", "best", "base_rate_set", "reason"]},
    },
    "required": ["happened", "class", "pending", "choices", "likelihood"],
}

def _strict(x):
    """The vendor's structured output takes a plain schema: no length limits (`validate_answer` checks the sizes), objects closed with `additionalProperties: false`."""
    if isinstance(x, dict):
        y = {k: _strict(v) for k, v in x.items() if k not in ("maxLength", "minLength", "maxItems", "minItems")}
        if y.get("type") == "object":
            y["additionalProperties"] = False
        return y
    if isinstance(x, list):
        return [_strict(v) for v in x]
    return x


ANSWER_SCHEMA = _strict(ANSWER_SCHEMA)

TOOLS = [
    {"name": "recall", "description": "What the system already knows about a name or topic (earlier notes, graph events, storylines, its pick or skip, earlier cases), newest first, with source and date.",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "topic": {"type": "string"}}, "required": []}},
    {"name": "graph_events", "description": "The knowledge graph's events and relations for a name, its peers and its sector: who else is touched.",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "sector": {"type": "string"}}, "required": []}},
    {"name": "company_card", "description": "One page on a company from the system's sources (valuation facts, liquidity, 52-week range, recent announcements).",
     "input_schema": {"type": "object", "properties": {"market": {"type": "string"}, "symbol": {"type": "string"}}, "required": ["market", "symbol"]}},
    {"name": "base_rates", "description": "What names with this kind of event or move did against their index over the next 5, 20 and 60 sessions (the spread and the count), from the system's own history.",
     "input_schema": {"type": "object", "properties": {"kind": {"type": "string"}, "symbol": {"type": "string"}}, "required": ["kind"]}},
    {"name": "outcome_table", "description": "Worst, likely and best in rupees, and the share of the book, for an option on a name (code computes it, after tax and charges).",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "option": {"enum": list(think.OPTIONS)}}, "required": ["symbol", "option"]}},
    {"name": "web_check", "description": "A public web check of the cause (paid; used only when the notes already known do not cover it; the second ask on an unchanged subject is free).",
     "input_schema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
]


# --- dependencies --------------------------------------------------------------------------------------------------------------------------------------------------------------

def _mod(name: str):
    if name in DEPS:
        return DEPS[name]
    return importlib.import_module(_MODULES[name])


def _tojson(x) -> str:
    return json.dumps(x, default=str, ensure_ascii=False)


def reserve_status(con, market: str, day: date) -> dict:
    """The reserve of a market (see `think/reserve.py`); here too because the loop's wiring reads it through the session module."""
    return reserve.reserve_status(con, market, day)


# --- small helpers -------------------------------------------------------------------------------------------------------------------------------------------------------------

def _whole_book(con, day: date) -> float:
    try:
        from pflab.us import wholebook
        w = float(wholebook.whole_book_inr(con, day).get("whole_inr") or 0.0)
        if w > 0:
            return w
    except Exception:
        pass
    try:
        from pflab.paper import book
        return float(book.holdings(con, day)["value"] or 0.0)
    except Exception:
        return 0.0


def _exposure_share(con, case: dict, day: date) -> float:
    """The case's exposure as a fraction of the whole book (the watch stores rupees and a percentage; rupees over the book is used when both exist)."""
    inr, pct = float(case.get("exposure_inr") or 0.0), float(case.get("exposure_pct") or 0.0)
    whole = _whole_book(con, day)
    if inr > 0 and whole > 0:
        return inr / whole
    return pct / 100.0 if pct > 1.0 else pct


def _held(con, market: str, isin: Optional[str]) -> float:
    """Shares of the name the book holds (0 when none or unreadable)."""
    if not isin:
        return 0.0
    try:
        if market == "US":
            from pflab.us import book as usb
            return float(usb.positions(con).get(isin, 0.0))
        from pflab.paper import book
        return float(book.positions(con).get(isin, 0.0))
    except Exception:
        return 0.0


def _session_after(market: str, day: date, n: int) -> date:
    try:
        from pflab import markets
        return markets.get("US" if market == "US" else "IN").session_after(day, n)
    except Exception:
        return day + timedelta(days=max(1, n))


_INDEX_NAMES = re.compile(r"\b(?:S&P ?(?:500|100|400|600)|Nasdaq[- ]?(?:100|Composite)?|Nifty ?(?:50|100|200|500|Next 50|Midcap ?(?:50|100|150)|Smallcap ?(?:50|100|250))|Dow(?: Jones)?(?: 30)?|Russell ?(?:1000|2000|3000)|FTSE ?(?:100|250)|BSE ?(?:500|100|200)|Sensex ?(?:30)?|Nikkei ?225|CAC ?40|DAX ?40?|Hang Seng ?\d*)\b", re.I)


def _numbers(text: str) -> set:
    """The figures in a text; the digits that are part of an index's NAME (S&P 500, Nasdaq 100, Nifty 500) are names, not figures."""
    return {t.replace(",", "").rstrip(".") for t in re.findall(r"\d[\d,]*\.?\d*", _INDEX_NAMES.sub(" ", text or ""))}


def _walk(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, x


def validate_answer(ans: object, known_text: str = "") -> List[str]:
    """The problems with a structured answer ([] when it fits): closed lists only, no number written as a field, no figure in the prose that the sources did not give."""
    if not isinstance(ans, dict):
        return ["the answer is not a JSON object"]
    out: List[str] = []
    for k in ("happened", "class", "pending", "choices", "likelihood"):
        if k not in ans:
            out.append(f"missing field `{k}`")
    if ans.get("class") not in think.CLASSES:
        out.append(f"class must be one of {list(think.CLASSES)}")
    ch = ans.get("choices")
    if not isinstance(ch, list) or not ch:
        out.append("choices: one option for each affected holding or opportunity (at least one)")
    else:
        for c in ch[:MAX_CHOICES + 1]:
            if not isinstance(c, dict) or not c.get("symbol") or c.get("option") not in think.OPTIONS:
                out.append(f"each choice needs a symbol and an option from {list(think.OPTIONS)}")
                break
    lk = ans.get("likelihood")
    if not isinstance(lk, dict):
        out.append("likelihood: worst, likely and best each need a word from " + str(list(think.WORDS)))
    else:
        for k in ("worst", "likely", "best"):
            if lk.get(k) not in think.WORDS:
                out.append(f"likelihood.{k} must be one of {list(think.WORDS)} (a word, never a number)")
        if str(lk.get("base_rate_set")) not in ("5", "20", "60", "own range"):
            out.append("likelihood.base_rate_set must be 5, 20, 60 or own range")
    for path, v in _walk(ans):
        key = path.rsplit(".", 1)[-1].split("[")[0].lower()
        if key in FORBIDDEN_KEYS:
            out.append(f"`{key}` is a number the model never writes (code makes sizes, prices, weights and probabilities)")
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(f"`{path.lstrip('.')}` is a number: write words or names only")
    known = _numbers(known_text)
    for k in ("happened", "known", "pending"):
        v = ans.get(k)
        if isinstance(v, str):
            bad = sorted(n for n in _numbers(v) if n not in known)
            if bad:
                out.append(f"`{k}` carries figures the sources did not give ({', '.join(bad[:4])}): leave them out or take them from a tool result")
    for i, c in enumerate(ans.get("choices") or []):
        if isinstance(c, dict) and isinstance(c.get("reason"), str):
            bad = sorted(n for n in _numbers(c["reason"]) if n not in known)
            if bad:
                out.append(f"choice {i + 1}'s reason carries figures the sources did not give ({', '.join(bad[:4])})")
    return out[:8]


def _normal(ans: dict, isins: Optional[dict] = None) -> dict:
    """The answer in the shape `odds` and `rule` read (`odds.norm_answer`): {"class", "pending", "pending_resolved_on", "choices": [{"isin", "symbol", "option", "words": {worst, likely, best}, "base_rate_set",
    "reason"}]}. The validated answer carries ONE likelihood for the whole case; every choice gets it as its words. `isins`: symbol -> ISIN (a choice without one would take the case's own name).
    The base-rate set the model names is "5", "20" or "60" (history at that horizon: odds reads its own horizon, 20) or "own range"; odds' vocabulary is "history" | "own range" | an event kind."""
    lk = ans.get("likelihood") or {}
    words = {k: lk.get(k) for k in ("worst", "likely", "best")}
    bset = "own range" if str(lk.get("base_rate_set")) == "own range" else "history"
    choices = [{"isin": (isins or {}).get(str(c.get("symbol")).upper()), "symbol": str(c.get("symbol")).upper(), "option": c.get("option"), "words": words, "base_rate_set": bset, "reason": c.get("reason", "")}
               for c in (ans.get("choices") or []) if isinstance(c, dict)]
    return {**ans, "class": ans.get("class"), "klass": ans.get("class"), "pending": (ans.get("pending") or None), "pending_resolved_on": ans.get("pending_resolved_on") or None, "choices": choices}


def _bet_total(rr: dict) -> float:
    """The whole bet of a buy the rule decided: `size_inr` of its decision is the PART due now, `parts["total_inr"]` the whole bet (`act` buys `total / parts` a part)."""
    p = rr.get("parts")
    if isinstance(p, dict) and p.get("total_inr"):
        return float(p["total_inr"])
    return float(rr.get("size_inr") or 0.0)


# --- the context the model reads -----------------------------------------------------------------------------------------------------------------------------------------------

def _names(con, case: dict) -> List[dict]:
    out = [{"isin": case.get("isin"), "symbol": case.get("symbol"), "market": case.get("market")}]
    try:
        for n in json.loads(case.get("names_json") or "[]"):
            sym = n.get("symbol") if isinstance(n, dict) else str(n)
            if sym and sym != case.get("symbol"):
                out.append({"isin": (n.get("isin") if isinstance(n, dict) else None), "symbol": sym, "market": case.get("market")})
    except Exception:
        pass
    return out[:6]


def _recall_for(con, now: datetime, case: dict, names: List[dict], day: date) -> dict:
    rec = _mod("recall")
    items, parts = [], []
    for n in names:
        try:
            r = rec.recall(con, now, isin=n.get("isin"), symbol=n.get("symbol"), asof=day, limit_chars=3000)
        except Exception as e:
            parts.append(f"{n.get('symbol')}: what we know could not be read ({type(e).__name__})")
            continue
        items += list(r.get("items") or [])
        if r.get("text"):
            parts.append(f"--- {n.get('symbol')} ---\n{r['text']}")
    return {"items": items, "text": "\n".join(parts)[:9000] or "nothing earlier is stored about these names."}


def _first_message(con, now: datetime, case: dict, names: List[dict], recalled: dict, day: date) -> str:
    sig = cases.signals(con, case_id=case["case_id"])
    def _why(s) -> str:
        try:
            w = (json.loads(s.get("detail_json") or "{}") or {}).get("why")
            return f"; {w}" if w else ""
        except Exception:
            return ""
    lines = [f"- {s['signal']} on {s['symbol']} ({s['day']}): value {s['value']:.3g} against threshold {s['threshold']:.3g}" + _why(s) for s in sig[:12]]
    whole = _whole_book(con, day)
    res = " ".join(reserve.reserve_status(con, m, day)["text"] for m in ("IN", "US"))
    held = _held(con, case.get("market") or "IN", case.get("isin"))
    hold_txt = (f"about Rs {float(case.get('exposure_inr') or 0):,.0f} of it ({100 * _exposure_share(con, case, day):.1f}% of the whole book)" if held > 0
                else "none of it: this is a chance, not a holding")
    return (f"CASE #{case['case_id']} (opened {case['opened_on']}, market {case['market']}, kind {case['kind']}): {case['title']}\n"
            f"The book holds {hold_txt}.\n"
            f"The whole book is about Rs {whole:,.0f}. {res}\n\nSIGNALS (from code):\n" + ("\n".join(lines) or "- none stored") +
            f"\n\nWHAT WE ALREADY KNOW (stored notes, graph, storylines, earlier cases; newest first):\n{recalled['text']}\n\n"
            "Read the situation, use the tools if you need them, then say what kind of situation it is. Do not write numbers.")


# --- the tools the model may call ----------------------------------------------------------------------------------------------------------------------------------------------

class _Ctx:
    def __init__(self, con, now: datetime, case: dict, day: date, root, web: Optional[Callable]):
        self.con, self.now, self.case, self.day, self.root, self.web = con, now, case, day, root, web
        self.cost = 0.0
        self.texts: List[str] = []
        self.web_used = 0


def _tool_run(ctx: _Ctx, name: str, a: dict) -> str:
    con, now, case, day = ctx.con, ctx.now, ctx.case, ctx.day
    try:
        if name == "recall":
            r = _mod("recall").recall(con, now, symbol=a.get("symbol") or case.get("symbol"), isin=None if a.get("symbol") else case.get("isin"), topic=a.get("topic"), asof=day, limit_chars=3500)
            return (r.get("text") or "nothing stored")[:3500]
        if name == "graph_events":
            r = _mod("recall").recall(con, now, symbol=a.get("symbol") or case.get("symbol"), isin=None if a.get("symbol") else case.get("isin"), sector=a.get("sector"), asof=day, limit_chars=3500)
            return (r.get("text") or "no graph events stored")[:3500]
        if name == "company_card":
            from pflab.lab import screen
            return _tojson(screen.fit_card(screen.company_card(con, now, str(a.get("market") or case.get("market") or "IN"), str(a.get("symbol") or case.get("symbol") or ""), root=ctx.root), 6000))
        if name == "base_rates":
            r = _mod("odds").base_rates(con, str(a.get("kind") or case.get("kind")), isin=case.get("isin"), asof=day)
            return _tojson(r)[:3000]
        if name == "outcome_table":
            sym = str(a.get("symbol") or case.get("symbol"))
            isin = case.get("isin") if sym == case.get("symbol") else None
            r = _mod("odds").outcomes(con, case, str(a.get("option")), isin=isin, asof=day)
            return _tojson(r)[:2000]
        if name == "web_check":
            return _web(ctx, str(a.get("question") or ""))
    except Exception as e:
        return f"tool {name} failed: {type(e).__name__}: {str(e)[:200]}"
    return f"no tool named {name}"


def _web(ctx: _Ctx, question: str) -> str:
    """A web check, once per case unless the first found nothing; never paid twice for an unchanged subject (`recall.same_subject_fresh`)."""
    if ctx.web_used >= 2:
        return "the web check limit for this case is used"
    try:
        fresh = _mod("recall").same_subject_fresh(ctx.con, ctx.now, isin=ctx.case.get("isin"), topic=question[:80])
    except Exception:
        fresh = None
    if fresh:
        return f"already known, nothing paid: [{fresh.get('source')} {fresh.get('day')}] {fresh.get('title')}: {str(fresh.get('text'))[:1500]}"
    fn = ctx.web or _default_web
    ctx.web_used += 1
    r = fn(ctx.con, question, ctx.now)
    ctx.cost += float(r.get("cost_rupees") or 0.0)
    return str(r.get("text") or r.get("problem") or "no result")[:3500]


def _default_web(con, question: str, now: datetime) -> dict:
    """The paid web check through the analyst (the egress gate, priced first, his cap; it keeps its own note). No client or a refusal is an answer, not an error."""
    try:
        from pflab.agents import analyst as an
        from pflab.hq import llm
        from pflab.pm import secrets
        o = an.web_search(con, question, llm.client(secrets.load()), now=now, topic="case web check")
        return {"text": o.text, "cost_rupees": float(o.cost_inr or 0.0)} if o.status == "done" else {"problem": f"no web check now ({o.status}: {str(o.text)[:120]})"}
    except Exception as e:
        return {"problem": f"no web check now ({type(e).__name__})"}


# --- the model's session --------------------------------------------------------------------------------------------------------------------------------------------------------

_PSEUDO = re.compile(r"(?<![A-Za-z0-9])ZZ\d{10}(?![0-9])")


def scrub(con, obj):
    """A US stock's pseudo-ISIN (`ZZ` + the ten digits of its SEC number) is an "account-like number" to the egress gate: every text sent to the model names the stock by its symbol instead (`US:SYMBOL`;
    "a US stock" when the store has none). Walks strings, lists and dicts; anything else is left alone."""
    if isinstance(obj, str):
        if "ZZ" not in obj:
            return obj

        def sym(m):
            try:
                r = con.execute("SELECT symbol FROM instruments WHERE isin=? LIMIT 1", [m.group(0)]).fetchone()
                if r and r[0]:
                    return "US:" + str(r[0])
            except Exception:
                pass
            return "a US stock"
        return _PSEUDO.sub(sym, obj)
    if isinstance(obj, list):
        return [scrub(con, x) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub(con, v) for k, v in obj.items()}
    return obj


def _gcall(con, now: datetime, case_id: int, role: str, messages: list, *, tools=None, schema=None, purpose: str, max_tokens: int = 1500) -> dict:
    messages = scrub(con, messages)
    r = _mod("gateway").call(con, role, [{"type": "text", "text": SYSTEM}], messages, tools=tools, case_id=case_id, purpose=purpose, now=now, max_tokens=max_tokens, schema=schema, agent="think") or {}
    cases.add_step(con, case_id, now, purpose, engine=str(r.get("engine") or ""), model=str(r.get("model") or ""), thinking=str(r.get("thinking") or ""), cost_rupees=float(r.get("cost_rupees") or 0.0),
                   cached_tokens=int(r.get("cached_tokens") or 0), payload={"role": role, "text": str(r.get("text") or "")[:1500], "tool_calls": [t.get("name") for t in (r.get("tool_calls") or [])]})
    return r


def _read(con, now: datetime, case: dict, first: str, ctx: _Ctx) -> str:
    """Sonnet reads first: a short tool loop; its closing text is the reading the answer is built on."""
    msgs: list = [{"role": "user", "content": first}]
    reading = ""
    for turn in range(MAX_TOOL_TURNS):
        r = _gcall(con, now, case["case_id"], "read", msgs, tools=TOOLS, purpose=f"read{turn + 1}", max_tokens=1200)
        ctx.cost += float(r.get("cost_rupees") or 0.0)
        calls = list(r.get("tool_calls") or [])
        reading = str(r.get("text") or "") or reading
        if not calls:
            break
        msgs.append({"role": "assistant", "content": r.get("assistant_content") or (([{"type": "text", "text": r["text"]}] if r.get("text") else [])
                                                                                    + [{"type": "tool_use", "id": t.get("id") or f"t{i}", "name": t["name"], "input": t.get("input") or {}} for i, t in enumerate(calls)])})
        results = []
        for i, t in enumerate(calls):
            out = _tool_run(ctx, t["name"], t.get("input") or {})
            ctx.texts.append(out)
            cases.add_step(con, case["case_id"], now, f"tool:{t['name']}", payload={"input": t.get("input") or {}, "result": out[:600]})
            results.append({"type": "tool_result", "tool_use_id": t.get("id") or f"t{i}", "content": out})
        msgs.append({"role": "user", "content": results})
    return reading


def _answer(con, now: datetime, case: dict, first: str, reading: str, ctx: _Ctx, role: str) -> tuple:
    """The structured answer: validated; one more ask on a problem. -> (answer or None, problems)."""
    known = first + "\n" + "\n".join(ctx.texts) + "\n" + reading
    msgs = [{"role": "user", "content": first + "\n\nYOUR READING SO FAR:\n" + (reading or "(none)") + "\n\nNow give the structured answer."}]
    problems: List[str] = []
    for attempt in (1, 2):
        r = _gcall(con, now, case["case_id"], role, msgs, schema=ANSWER_SCHEMA, purpose="answer" if attempt == 1 else "answer_retry", max_tokens=1800)
        ctx.cost += float(r.get("cost_rupees") or 0.0)
        ans = r.get("json")
        if ans is None and r.get("text"):
            try:
                ans = json.loads(re.search(r"\{.*\}", r["text"], re.S).group(0))
            except Exception:
                ans = None
        problems = validate_answer(ans, known)
        if not problems:
            return ans, []
        cases.add_step(con, case["case_id"], now, "answer_refused", payload={"attempt": attempt, "problems": problems})
        msgs = msgs + [{"role": "assistant", "content": r.get("text") or _tojson(ans)}, {"role": "user", "content": "Your answer was refused: " + "; ".join(problems) + ". Answer again, fixing exactly that."}]
    return None, problems


# --- the independent big-trade check ---------------------------------------------------------------------------------------------------------------------------------------------

CHECK_SYSTEM = ("You are the independent CHECKER of a small personal paper portfolio. A rule wants to place the order below. Answer 'pass' unless you can name a concrete reason it is a mistake today "
                "(a data error, a stale price, a known event, too concentrated, against the book's own stated risk). Do not second-guess the strategy.")
CHECK_SCHEMA = _strict({"type": "object", "properties": {"verdict": {"enum": ["pass", "veto"]}, "reason": {"type": "string", "maxLength": 240}}, "required": ["verdict", "reason"]})


def big_trade_check(con, now: datetime, case: dict, order: dict) -> dict:
    """-> {"verdict": pass | veto | unchecked, "reason"}. Through the one door (role `quick`); logged in `core_checks_s80` like the close loop's checker."""
    try:
        r = _mod("gateway").call(con, "quick", [{"type": "text", "text": CHECK_SYSTEM}], [{"role": "user", "content": f"Case #{case['case_id']} ({case.get('title')}): {order['side'].upper()} {order['symbol']}, "
                                 f"about Rs {order['value']:,.0f} ({order.get('share', 0.0):.1%} of the whole book). Reason: {order.get('reason', '')[:400]}"}],
                                 case_id=case["case_id"], purpose="big_trade_check", now=now, max_tokens=300, schema=CHECK_SCHEMA, agent="think") or {}
        v = r.get("json") or {}
        verdict, reason = (v.get("verdict") if v.get("verdict") in ("pass", "veto") else "unchecked"), str(v.get("reason") or "no verdict")
        cases.add_step(con, case["case_id"], now, "big_trade_check", engine=str(r.get("engine") or ""), model=str(r.get("model") or ""), thinking=str(r.get("thinking") or ""),
                       cost_rupees=float(r.get("cost_rupees") or 0.0), cached_tokens=int(r.get("cached_tokens") or 0), payload={"order": order["symbol"], "verdict": verdict, "reason": reason})
    except Exception as e:
        verdict, reason = "unchecked", f"{type(e).__name__}: {str(e)[:160]}"
    try:
        from pflab.core import checker
        checker._log(con, now, now.date(), "case_trade", order["symbol"], {"symbol": order["symbol"], "side": order["side"], "value": order["value"], "from_w": None, "to_w": None}, verdict, reason, 0.0, "gateway:quick")
    except Exception:
        pass
    return {"verdict": verdict, "reason": reason}


# --- act ------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _parts_done(con, case_id: int, isin: str) -> List[dict]:
    out = []
    for s in cases.steps(con, case_id):
        if s["step"] == "part":
            try:
                p = json.loads(s["payload_json"] or "{}")
            except Exception:
                continue
            if p.get("isin") == isin:
                out.append(p)
    return out


def _place_india(con, now: datetime, day: date, o: dict, case_id: int) -> int:
    """A paper order for the India book as a decision row plus the order (the way the close loop places one); the fill is the next close's, as for every order."""
    from pflab.core import loop
    from pflab.paper import book
    did = loop._decision(con, now, o, None, day, f"case #{case_id}")
    oid = book.place(con, now, did, o["isin"], o["side"], qty=o.get("qty"), amount=o.get("amount"), note=f"case #{case_id} decision #{did}")
    try:
        from pflab.paper import manager
        manager.register(con, did)
    except Exception:
        pass
    try:
        from pflab.core import sleeves
        sleeves.tag_order(con, o["isin"], day, f"case #{case_id}")
    except Exception:
        pass
    return oid


def _act_sell_in(con, now: datetime, day: date, case: dict, d: dict) -> List[str]:
    from pflab.core import exits
    from pflab.paper import book
    isin, opt = d["isin"], d["option"]
    pos = float(book.positions(con).get(isin, 0.0))
    px = book.close_on(con, isin, day)
    if pos <= 1e-9 or px is None:
        return [f"no order: {d.get('symbol')} is not held or has no close"]
    plans = exits._plans(con, "IN", isin=isin)
    if not plans:
        exits.backfill_plans(con, day, "IN", now)
        plans = exits._plans(con, "IN", isin=isin)
    if not plans:
        return [f"no order: no exit plan for {d.get('symbol')}"]
    price = float(px[1])
    qty = pos if opt == "sell" else min(pos, round(float(d.get("size_inr") or 0.0) / price) or pos / 2.0)
    whole = _whole_book(con, day)
    share = qty * price / whole if whole > 0 else 0.0
    cfg = exits.settings()
    what = f"Case #{case['case_id']} ({case.get('title')}): {d.get('reason') or opt}."
    if share > float(think.settings()["big_trade_share"]) and not d.get("thesis_break_skip_check"):
        chk = big_trade_check(con, now, case, {"side": "sell", "symbol": d.get("symbol"), "value": qty * price, "share": share, "reason": d.get("reason", "")})
        if chk["verdict"] == "veto":
            return [f"no order: the big-trade check vetoed the sale ({chk['reason']})"]
    o = exits._sell(con, now, day, plans[0], isin, "case", qty, pos, price, what, cfg, override_guard=bool(d.get("override_guard")), ref=f"case:{case['case_id']}:{day}")
    if o is None:
        return ["held back: the exit manager did not place the sale (the 12-month guard, a pending order or a same-day rule; see the exit events)"]
    order = {"isin": isin, "symbol": d.get("symbol") or isin, "side": "sell", "qty": o["qty"], "amount": None, "value": o["value"], "risk_cut": False, "charges": float(o.get("est_charges") or 0.0),
             "tax": float(o.get("est_tax") or 0.0), "note": "", "from_w": None, "to_w": None, "reason": o["reason"], "kind": "case", "event_id": o.get("event_id")}
    oid = _place_india(con, now, day, order, case["case_id"])
    return [f"paper_order:{oid}", f"exit_event:{o.get('event_id')}"]


def _worst_pct(d: dict) -> Optional[float]:
    w = d.get("worst_pct_book")
    return None if w is None else abs(float(w))


def _act_buy_in(con, now: datetime, day: date, case: dict, d: dict) -> List[str]:
    from pflab.paper import book, rails
    isin = d["isin"]
    parts = int(d.get("parts") or think.settings()["parts"])
    done = _parts_done(con, case["case_id"], isin)
    if len(done) >= parts:
        return [f"no order: all {parts} parts are bought"]
    n = len(done) + 1
    st = reserve.reserve_status(con, "IN", day)
    part_inr = float(d.get("size_inr") or 0.0) / parts                      # `size_inr` is the whole bet (code: the 1% worst-case limit over the worst-case move); it goes in equal parts
    room = rails.buy_room(con, isin, day)
    amount = min(part_inr, st["free_inr"], room)
    lim = float(think.settings()["bet_worst_pct_book"])
    wp = _worst_pct(d)
    if wp is not None and wp > lim * 1.0001:
        return [f"no order: the worst case would lose {wp:.2%} of the whole book, over the {lim:.0%} limit"]
    if amount < MIN_RESERVE_BUY_INR:
        why = "the reserve has no room" if st["free_inr"] < MIN_RESERVE_BUY_INR else ("a rail leaves no room" if room < MIN_RESERVE_BUY_INR else "the part is too small")
        return [f"no order: {why} (reserve free Rs {st['free_inr']:,.0f}, rail room Rs {room:,.0f})"]
    whole = _whole_book(con, day)
    chk = big_trade_check(con, now, case, {"side": "buy", "symbol": d.get("symbol"), "value": amount, "share": amount / whole if whole > 0 else 0.0, "reason": d.get("reason", "")})
    if chk["verdict"] == "veto":
        return [f"no order: the big-trade check vetoed the buy ({chk['reason']})"]
    if chk["verdict"] == "unchecked":
        return [f"no order yet: the big-trade check could not run ({chk['reason']}); the case stays open"]
    px = book.close_on(con, isin, day)
    order = {"isin": isin, "symbol": d.get("symbol") or isin, "side": "buy", "qty": None, "amount": round(amount, 2), "value": amount, "risk_cut": False, "charges": 0.0, "tax": 0.0, "note": "",
             "from_w": None, "to_w": None, "reason": f"Case #{case['case_id']}, part {n} of {parts} from the opportunity reserve: {d.get('reason') or 'buy in parts'}", "kind": "case", "event_id": None}
    oid = _place_india(con, now, day, order, case["case_id"])
    cases.add_step(con, case["case_id"], now, "part", payload={"isin": isin, "symbol": d.get("symbol"), "n": n, "of": parts, "inr": round(amount, 2), "day": str(day), "order_id": oid, "price": px[1] if px else None})
    return [f"paper_order:{oid}"]


def _act_us(con, now: datetime, day: date, case: dict, d: dict) -> List[str]:
    from pflab.us import book as usb
    try:                                                    # a US order carries the US SESSION's date (the last closed one), as the US step's own orders do: `us.book.fill_orders` fills only
        from pflab.us import clock as uc                    # orders placed on an EARLIER session, so the IST date made an order decided on a Tuesday morning wait a session longer
        day = uc.session_closed_by(now)
    except Exception:
        pass
    isin, sym, opt = d["isin"], d.get("symbol") or d["isin"], d["option"]
    if opt in ("sell", "trim"):
        pos = float(usb.positions(con).get(isin, 0.0))
        if pos <= 1e-9:
            return [f"no order: {sym} is not held"]
        qty = pos if opt == "sell" else pos / 2.0
        oid = usb.place(con, now, day, isin, sym, "sell", qty=round(qty, 6), reason=f"Case #{case['case_id']}: {d.get('reason') or opt} (fills at the next US open; gap risk stated)")
        return [f"us_order:{oid}"]
    parts = int(d.get("parts") or think.settings()["parts"])
    done = _parts_done(con, case["case_id"], isin)
    if len(done) >= parts:
        return [f"no order: all {parts} parts are bought"]
    st = reserve.reserve_status(con, "US", day)
    fx = float(st.get("fx") or 1.0)
    part_inr = float(d.get("size_inr") or 0.0) / parts
    lim = float(think.settings()["bet_worst_pct_book"])
    wp = _worst_pct(d)
    if wp is not None and wp > lim * 1.0001:
        return [f"no order: the worst case would lose {wp:.2%} of the whole book, over the {lim:.0%} limit"]
    amount_inr = min(part_inr, st["free_inr"])
    try:                                                                  # F2: a reserve buy is outside the monthly cap and limited to `exempt_day_share` of the sub-book a day (the US step's own carve-out)
        from pflab import us as _us
        sub_inr = float(st["reserve_inr"]) / max(float(st.get("reserve_points") or 10.0) / 100.0, 1e-9)
        today_inr = sum(float(o.get("amount_usd") or 0.0) for o in usb.open_orders(con) if o["side"] == "buy" and o.get("placed_day") == day) * fx
        amount_inr = min(amount_inr, max(0.0, float(_us.settings()["exempt_day_share"]) * sub_inr - today_inr))
    except Exception:
        pass
    if amount_inr < MIN_RESERVE_BUY_INR:
        return [f"no order: the US reserve has no room (free Rs {st['free_inr']:,.0f})"]
    whole = _whole_book(con, day)
    chk = big_trade_check(con, now, case, {"side": "buy", "symbol": sym, "value": amount_inr, "share": amount_inr / whole if whole > 0 else 0.0, "reason": d.get("reason", "")})
    if chk["verdict"] == "veto":
        return [f"no order: the big-trade check vetoed the buy ({chk['reason']})"]
    if chk["verdict"] == "unchecked":
        return [f"no order yet: the big-trade check could not run ({chk['reason']}); the case stays open"]
    usd = round(amount_inr / fx, 2)
    oid = usb.place(con, now, day, isin, sym, "buy", amount_usd=usd, reason=f"Case #{case['case_id']}, part {len(done) + 1} of {parts} from the US opportunity reserve: {d.get('reason') or 'buy in parts'}")
    cases.add_step(con, case["case_id"], now, "part", payload={"isin": isin, "symbol": sym, "n": len(done) + 1, "of": parts, "inr": round(amount_inr, 2), "day": str(day), "order_id": oid})
    return [f"us_order:{oid}"]


def act(con, now: datetime, case_id: int, decision: dict) -> List[str]:
    """Carry out one decision of a case: `{"isin","symbol","market","option","size_inr","parts","reason","worst_pct_book",...}`. -> refs of what was done (orders, a freeze) or a sentence saying why nothing was."""
    case = cases.get_case(con, case_id) or {}
    d = dict(decision)
    day = now.date()
    market = (d.get("market") or case.get("market") or "IN").upper()
    opt = d.get("option")
    if opt in ("freeze", "wait"):
        until_event = (case.get("pending") or "").strip() or None
        until = None if until_event else _session_after(market, day, int(think.settings()["look_max_sessions"]))
        fid = cases.add_freeze(con, now, isin=d["isin"], symbol=d.get("symbol") or d["isin"], market=market, case_id=case_id, until=until, until_event=until_event,
                               reason=f"case #{case_id}: {d.get('reason') or opt}")
        return [f"freeze:{fid}"]
    if opt in ("sell", "trim", "buy_in_parts"):                                  # S85 E4: his standing instructions (hold_name, pause_buys, no_new_names, cash_floor) bind a case's order too
        try:
            from pflab.core import rules_gate
            held_by = rules_gate.case_block(con, now, isin=d["isin"], symbol=d.get("symbol"), market=market, side="buy" if opt == "buy_in_parts" else "sell", option=opt,
                                            thesis_break=bool(opt == "sell" and (case.get("klass") == "damage" or d.get("thesis_break_skip_check"))),
                                            value=float(d.get("size_inr") or 0.0) / (int(d.get("parts") or think.settings()["parts"]) if opt == "buy_in_parts" else 1))
        except Exception:
            held_by = None
        if held_by:
            cases.add_step(con, case_id, now, "rule_block", payload={"isin": d["isin"], "symbol": d.get("symbol"), "option": opt, "why": held_by})
            return [f"no order: {held_by}"]
    if opt in ("sell", "trim"):
        return _act_us(con, now, day, case, d) if market == "US" else _act_sell_in(con, now, day, case, d)
    if opt == "buy_in_parts":
        for f in cases.active_freezes(con, day, market):               # a buy lifts the system's own freeze on the name (the rule has already weighed the guards)
            if f["isin"] == d["isin"]:
                cases.release_freeze(con, f["freeze_id"])
        return _act_us(con, now, day, case, d) if market == "US" else _act_buy_in(con, now, day, case, d)
    return []


# --- one case, end to end ---------------------------------------------------------------------------------------------------------------------------------------------------------

def _rows_for(table: List[dict], isin, symbol) -> List[dict]:
    mine = [r for r in table if (isin and r.get("isin") == isin) or (symbol and str(r.get("symbol") or "").upper() == str(symbol).upper())]
    return mine or [r for r in table if not r.get("isin") and not r.get("symbol")] or []


def _isin_of(con, market: str, symbol: str, case: dict) -> Optional[str]:
    if symbol and case.get("symbol") and str(symbol).upper() == str(case["symbol"]).upper():
        return case.get("isin")
    try:
        if market == "US":
            from pflab.us import policy as _p  # noqa: F401
            return None
        from pflab.paper import book
        return book.isin_of(con, str(symbol).upper())
    except Exception:
        return None


def _isin_map(con, case: dict, ans: dict) -> dict:
    """symbol -> ISIN for the names of an answer (the case's own name first; another name by the store's symbol lookup, None when it has none)."""
    market = case.get("market") or "IN"
    out = {}
    for ch in (ans.get("choices") or []):
        if isinstance(ch, dict) and ch.get("symbol"):
            sym = str(ch["symbol"]).upper()
            out[sym] = _isin_of(con, market, sym, case)
    return out


def _store_row(con, case_id: int, now: datetime, track: str, r: dict, *, chosen: bool = False, reason: Optional[str] = None, size_inr: Optional[float] = None) -> None:
    cases.add_option(con, case_id, now, track=track, isin=r.get("isin"), symbol=r.get("symbol"), option=str(r.get("option")), worst_inr=float(r.get("worst_inr") or 0.0), likely_inr=float(r.get("likely_inr") or 0.0),
                     best_inr=float(r.get("best_inr") or 0.0), expected_inr=float(r.get("expected_inr") or 0.0), worst_pct_book=float(r.get("worst_pct_book") or 0.0),
                     size_inr=float(r.get("size_inr") or 0.0) if size_inr is None else float(size_inr), reason=str(r.get("basis") or "") if reason is None else reason, chosen=chosen)


def _decide_all(con, now: datetime, day: date, case: dict, ans: dict, advisory: bool) -> dict:
    """OPTIONS (the table), DECIDE (the rule) and ACT for every choice. -> {"decisions": [...], "orders": [...], "acted": bool, "freeze": bool}.
    Stored, as `odds` and `score` agree: EVERY row of the option table (the model's own choice as track "model", chosen; the rest "alt") and the rule's choice as track "rule" (`rule.option_row`).
    ONE cache dict serves the table and the rule of the case (the history scan takes seconds)."""
    odds, rule = _mod("odds"), _mod("rule")
    market = case.get("market") or "IN"
    names = _isin_map(con, case, ans)
    nans = _normal(ans, names)
    cache: dict = {}
    table = list(odds.option_table(con, case["case_id"], nans, day, cache=cache) or [])
    for r in table:
        _store_row(con, case["case_id"], now, "model" if r.get("track") == "model" else "alt", r, chosen=bool(r.get("chosen")), reason=str(ans_reason(ans, r) if r.get("chosen") else r.get("basis") or ""))
    out = {"decisions": [], "orders": [], "acted": False, "freeze": False, "tell_rows": []}
    ruled = rule.decide(con, case["case_id"], nans, day, cache=cache) or {}
    per_name = {str(x.get("symbol") or "").upper(): x for x in (ruled.get("all") or [])}
    for ch in nans["choices"][:MAX_CHOICES]:
        sym, isin = ch["symbol"], ch.get("isin")
        if isin is None and sym != str(case.get("symbol") or "").upper():
            cases.add_step(con, case["case_id"], now, "choice_skipped", payload={"symbol": sym, "why": "no ISIN for this name in the store"})
            continue
        isin = isin or case.get("isin")
        model_opt = ch["option"]
        mine = _rows_for(table, isin, sym)
        if not any(r.get("option") == model_opt for r in mine):       # an option the table does not hold for this name (a sale of something the book does not hold, a market or macro case): the model's
            base = next((r for r in mine if r.get("option") == "nothing"), {})          # track is still stored so T8 can score it, valued as nothing (zero rupees), and says so
            _store_row(con, case["case_id"], now, "model", {**base, "isin": isin, "symbol": sym, "option": model_opt, "worst_inr": 0.0, "likely_inr": 0.0, "best_inr": 0.0, "expected_inr": 0.0,
                                                           "worst_pct_book": 0.0, "size_inr": 0.0}, chosen=True, reason=f"{ch.get('reason') or ''} (not an option for this name: valued as nothing)")
        rr = per_name.get(sym) or ruled
        rule_opt = rr.get("rule_option") or "nothing"
        if rr.get("refused"):
            rule_opt = "nothing"
        trow = next((r for r in _rows_for(table, isin, sym) if r.get("option") == rule_opt), None)
        if rule_opt in ("sell", "trim", "buy_in_parts") and rr.get("outcome") and rule_opt == rr.get("rule_option"):
            rrow = rule.option_row({**rr, "isin": isin, "symbol": sym})        # the rupees the rule's own outcome computed (a buy scaled to the part decided now)
        else:                                                                    # hold, freeze, wait, nothing (and a refused buy): the table's own row of that option, with no size
            rrow = {**(trow or {}), "isin": isin, "symbol": sym, "option": rule_opt, "size_inr": 0.0}
        _store_row(con, case["case_id"], now, "rule", rrow, chosen=True, reason=str(rr.get("reason") or ""))
        held = _held(con, market, isin) > 1e-9
        thesis_sale = (ans.get("class") == "damage" and rule_opt == "sell" and held)
        reason = str(rr.get("reason") or "")
        if model_opt != rule_opt:
            reason = f"the model chose {model_opt}, the rule chose {rule_opt}; the rule acts. " + reason
        wp = (rr.get("outcome") or {}).get("worst_pct_book")                  # of the WHOLE bet (a part's row is scaled), the figure the 1% limit speaks of
        d = {"isin": isin, "symbol": sym, "market": market, "option": rule_opt, "size_inr": _bet_total(rr) if rule_opt == "buy_in_parts" else float(rr.get("size_inr") or 0.0),
             "parts": rr.get("parts"), "reason": reason[:400], "worst_pct_book": wp, "guards": rr.get("guards"), "override_guard": False, "thesis_break_skip_check": False}
        if isinstance(d["parts"], dict):
            d["parts"] = d["parts"].get("n")
        refs: List[str] = []
        acted_opt = rule_opt
        if advisory and not thesis_sale:
            acted_opt = "advisory: no order"
        elif rule_opt in ("sell", "trim", "buy_in_parts", "freeze", "wait"):
            refs = act(con, now, case["case_id"], d)
            out["orders"] += [x for x in refs if ":" in x and not x.startswith("no ")]
            out["acted"] = out["acted"] or any(x.startswith(("paper_order", "us_order", "freeze")) for x in refs)
            out["freeze"] = out["freeze"] or any(x.startswith("freeze") for x in refs)
            if refs and not any(x.startswith(("paper_order", "us_order", "freeze")) for x in refs):
                acted_opt = "nothing (" + refs[0][:120] + ")"
                if "your rule '" in refs[0]:                                      # S85 E4: a standing instruction of his held the order back: the decision's reason says which
                    reason = (reason + " | " + refs[0])[:700]
        cases.record_decision(con, case["case_id"], day, isin=isin, symbol=sym, rule_option=rule_opt, model_option=model_opt, acted_option=acted_opt, order_refs=refs, reason=reason, advisory=bool(advisory))
        out["decisions"].append({"symbol": sym, "rule": rule_opt, "model": model_opt, "acted": acted_opt, "refs": refs, "row": rrow, "reason": reason})
    return out


def ans_reason(ans: dict, r: dict) -> str:
    for c in ans.get("choices") or []:
        if isinstance(c, dict) and str(c.get("symbol") or "").upper() == str(r.get("symbol") or "").upper():
            return str(c.get("reason") or "")
    return ""


def _advisory(con, day: date) -> bool:
    if str(think.settings().get("mode")) == "advisory":
        return True
    try:
        return bool(_mod("score").advisory(con, day))
    except Exception:
        return False


def think_case(con, now: datetime, case_id: int, *, root=None, web: Optional[Callable] = None) -> dict:
    """One case, one short session. Never raises: a failure is stored on the case (state stays open) and returned as `failed`. `web`: a callable `(con, question, now) -> {"text","cost_rupees"}` (default: the analyst)."""
    if not think.on():
        return {"off": True}
    case = cases.get_case(con, case_id)
    if case is None:
        return {"skipped": f"no case #{case_id}"}
    if case["state"] == "closed":
        return {"skipped": f"case #{case_id} is closed"}
    day = now.date()
    market = case.get("market") or "IN"
    ctx = _Ctx(con, now, case, day, root, web)
    try:
        names = _names(con, case)
        recalled = _recall_for(con, now, case, names, day)
        first = _first_message(con, now, case, names, recalled, day)
        reading = _read(con, now, case, first, ctx)
        share = _exposure_share(con, case, day)
        held = _held(con, market, case.get("isin")) > 1e-9
        opus = share > float(think.settings()["opus_exposure_share"]) or not held       # over the line, or a chance that could spend the reserve
        ans, problems = _answer(con, now, case, first, reading, ctx, "decide" if opus else "read")
        if ans is None:
            raise RuntimeError("the answer did not fit the closed lists after one more ask: " + "; ".join(problems[:3]))
        cases.add_step(con, case_id, now, "answer_ok", payload={"answer": ans, "opus": opus, "exposure_share": round(share, 5)})
        try:
            _mod("recall").mark_used(con, recalled["items"], by_kind="case", by_ref=str(case_id), day=day)
        except Exception:
            pass
        adv = _advisory(con, day)
        res = _decide_all(con, now, day, case, ans, adv)
    except Exception as e:
        why = f"{type(e).__name__}: {str(e)[:240]}"
        try:                                                                    # a refusal (his cap, the egress gate, the workshop guard) is said in the door's plain words
            why = _mod("gateway").refusal_reason(e) or why
        except Exception:
            pass
        cases.add_step(con, case_id, now, "failed", payload={"why": why})
        look = _session_after(market, day, 1)
        cases.set_case(con, case_id, state=("open" if case["state"] in ("noticed", "open") else case["state"]), next_look_on=look, summary=f"thinking failed: {why}"[:300])
        return {"case_id": case_id, "ok": False, "failed": why, "cost_rupees": round(ctx.cost, 2)}
    pending = (ans.get("pending") or "").strip()
    look_n = int(think.settings()["look_max_sessions"])
    look = _session_after(market, day, look_n)
    try:
        pd_ = date.fromisoformat(str(ans.get("pending_date") or ""))
        if day < pd_ < look:
            look = max(pd_, _session_after(market, day, 1))
    except Exception:
        pass
    state = "advisory" if adv else ("acted" if res["acted"] else ("waiting" if pending else "open"))
    cases.set_case(con, case_id, state=state, klass=ans["class"], pending=pending or None, next_look_on=look, next_look_cond=pending or None, summary=(ans.get("happened") or "")[:300],
                   names_json=json.dumps([n["symbol"] for n in names] + list(ans.get("other_names") or []), default=str))
    if not res["freeze"]:                                                                  # a decision that is not a freeze lifts this case's earlier freezes
        for f in cases.active_freezes(con, day):
            if f["case_id"] == case_id:
                cases.release_freeze(con, f["freeze_id"])
    try:
        _mod("recall").write_back(con, now, isin=case.get("isin"), symbol=case.get("symbol"), title=f"Case #{case_id}: {case['title']}"[:200],
                                  text=f"{ans.get('happened')}\nClass: {ans['class']}. Pending: {pending or 'nothing named'}.\nDecisions: " + "; ".join(f"{d['symbol']} {d['acted']} (model {d['model']}, rule {d['rule']})" for d in res["decisions"]),
                                  source="case", cost_rupees=ctx.cost, case_id=case_id)
    except Exception:
        pass
    told = False
    try:
        told = tell(con, now, case_id) is not None
    except Exception:
        pass
    return {"case_id": case_id, "ok": True, "class": ans["class"], "state": state, "decisions": res["decisions"], "orders": res["orders"], "advisory": adv, "opus": opus, "told": told,
            "cost_rupees": round(ctx.cost, 2), "next_look_on": str(look)}


# --- tell ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _rs(x: float) -> str:
    return f"Rs {x:,.0f}" if x >= 0 else f"-Rs {abs(x):,.0f}"


def tell(con, now: datetime, case_id: int, *, force: bool = False) -> Optional[int]:
    """Queue the Telegram text when the case ACTED (an order or a freeze) or opened on more than 2% of the book; once per case and stage. -> the outbox id, or None."""
    case = cases.get_case(con, case_id)
    if not case:
        return None
    day = now.date()
    acted = [d for d in case["decisions"] if d["acted_option"] and not d["acted_option"].startswith(("nothing", "advisory", "hold")) and d["decided_on"] == day]
    big = _exposure_share(con, case, day) > float(think.settings()["big_trade_share"])
    if not (acted or big or force):
        return None
    lines = [f"Case #{case_id}: {case['title']}."]
    if case.get("summary"):
        lines.append("What happened: " + case["summary"][:260])
    if case.get("klass"):
        lines.append("Kind: " + case["klass"].replace("_", " ") + (f"; waiting for: {case['pending']}" if case.get("pending") else "") + ".")
    rule_rows = {o["symbol"]: o for o in case["options"] if o["track"] == "rule"}
    hold_rows = {o["symbol"]: o for o in case["options"] if o["track"] in ("model", "alt") and o["option"] == "hold"}
    for d in (acted or case["decisions"][-2:]):
        r = rule_rows.get(d["symbol"])
        lines.append(f"{d['symbol']}: {d['acted_option'].replace('_', ' ')}" + (f" (the rule chose {d['rule_option']}, the model {d['model_option']})" if d["differs"] else "") + ".")
        h = hold_rows.get(d["symbol"])
        if r and r["option"] in ("sell", "trim") and h:                          # a sale's own rupees are only its cost: what matters is what holding would have meant
            lines.append(f"Holding instead: if it goes badly {_rs(h['worst_inr'])}, most likely {_rs(h['likely_inr'])}, if well {_rs(h['best_inr'])} (after tax, over about 20 sessions).")
        elif r and (r["worst_inr"] or r["best_inr"]):
            lines.append(f"If it goes badly {_rs(r['worst_inr'])}, most likely {_rs(r['likely_inr'])}, if well {_rs(r['best_inr'])}.")
    if any(d["advisory"] for d in case["decisions"]):
        lines.append("The loop is advisory now: nothing was ordered.")
    if case.get("next_look_on"):
        lines.append(f"It looks again {case['next_look_on']}.")
    text = "\n".join(lines)[:1500]
    from pflab.service import telegram
    return telegram.enqueue(con, text, kind="watch", dedup_key=f"think_case:{case_id}:{day}:{len(case['decisions'])}", now=now)


# --- come back ------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _last_think_day(con, case_id: int) -> Optional[date]:
    r = con.execute("SELECT max(step_at) FROM think_steps_s84 WHERE case_id=? AND step IN ('answer_ok','failed')", [case_id]).fetchone()[0]
    return r.date() if r else None


def _changed(con, case: dict) -> bool:
    last = con.execute("SELECT max(step_at) FROM think_steps_s84 WHERE case_id=? AND step='answer_ok'", [case["case_id"]]).fetchone()[0]
    if last is None:
        return True
    return any(s["ts"] is not None and s["ts"] > last for s in cases.signals(con, case_id=case["case_id"]))


def _last_answer(con, case_id: int) -> Optional[dict]:
    for s in reversed(cases.steps(con, case_id)):
        if s["step"] == "answer_ok":
            try:
                return json.loads(s["payload_json"]).get("answer")
            except Exception:
                return None
    return None


def _part_plans(con, case_id: int) -> Dict[str, List[dict]]:
    """The parts bought so far, by the name they bought (a market case buys an ETF, not its own pseudo-name): {isin: [part payloads, oldest first]}."""
    out: Dict[str, List[dict]] = {}
    for s in cases.steps(con, case_id):
        if s["step"] == "part":
            try:
                p = json.loads(s["payload_json"] or "{}")
            except Exception:
                continue
            if p.get("isin"):
                out.setdefault(p["isin"], []).append(p)
    return out


def _continue_parts(con, now: datetime, case: dict) -> List[str]:
    """The next part of every buy in parts of the case: the rule weighs its guards again (a later part only while the thesis holds, 5 sessions apart); code buys it."""
    ans = _last_answer(con, case["case_id"])
    if not ans:
        return []
    parts = int(think.settings()["parts"])
    day = now.date()
    out: List[str] = []
    for isin, plan in _part_plans(con, case["case_id"]).items():
        if not plan or len(plan) >= parts:
            continue
        last_day = date.fromisoformat(plan[-1]["day"])
        if day < _session_after(case.get("market") or "IN", last_day, int(think.settings()["parts_gap_sessions"])):
            continue
        sym = str(plan[-1].get("symbol") or (case.get("symbol") if isin == case.get("isin") else "") or "").upper()
        if not sym:
            continue
        nans = _normal({**ans, "choices": [{"symbol": sym, "option": "buy_in_parts", "reason": "the next part"}]}, {sym: isin})
        ruled = _mod("rule").decide(con, case["case_id"], nans, day) or {}
        rr = (ruled.get("all") or [ruled])[0]
        if rr.get("refused") or rr.get("rule_option") != "buy_in_parts":
            out.append(f"part {len(plan) + 1} of {sym} waits: the rule chose {rr.get('rule_option')} ({str(rr.get('reason'))[:120]})")
            continue
        d = {"isin": isin, "symbol": sym, "market": case.get("market"), "option": "buy_in_parts", "size_inr": _bet_total(rr) or float(plan[0]["inr"]) * parts,
             "parts": parts, "reason": str(rr.get("reason") or "next part"), "worst_pct_book": (rr.get("outcome") or {}).get("worst_pct_book")}
        refs = act(con, now, case["case_id"], d)
        bought = any(r.startswith(("paper_order", "us_order")) for r in refs)
        cases.record_decision(con, case["case_id"], day, isin=isin, symbol=sym, rule_option="buy_in_parts", model_option="buy_in_parts",
                              acted_option="buy_in_parts" if bought else "nothing", order_refs=refs, reason=f"part {len(plan) + 1}: " + d["reason"])
        out += refs
        if bought:
            try:
                tell(con, now, case["case_id"])
            except Exception:
                pass
    return out


def _retry_refused(con, now: datetime, case: dict) -> List[str]:
    """A buy the model chose and the rule REFUSED on a timing guard (it still makes new lows, a damage wait, a stretched price) is decided again at the next look, by the rule alone on the stored answer
    (no model call, no cost): the guard clears with time, not with a new signal, so "nothing changed" must not end the case's chance. The first part is bought when the rule now says so."""
    ans = _last_answer(con, case["case_id"])
    day = now.date()
    if not ans or _advisory(con, day):
        return []
    plans = _part_plans(con, case["case_id"])
    latest: Dict[str, dict] = {}
    for d in cases.decisions(con, case["case_id"]):
        if d["isin"]:
            latest[d["isin"]] = d
    out: List[str] = []
    for isin, d in latest.items():
        if d["model_option"] != "buy_in_parts" or d["rule_option"] not in ("nothing", "wait") or isin in plans or d["decided_on"] >= day or not d["symbol"]:
            continue
        sym = str(d["symbol"]).upper()
        nans = _normal({**ans, "choices": [{"symbol": sym, "option": "buy_in_parts", "reason": "looked at again"}]}, {sym: isin})
        ruled = _mod("rule").decide(con, case["case_id"], nans, day) or {}
        rr = (ruled.get("all") or [ruled])[0]
        if rr.get("refused") or rr.get("rule_option") != "buy_in_parts":
            continue
        parts = int(think.settings()["parts"])
        dd = {"isin": isin, "symbol": sym, "market": case.get("market"), "option": "buy_in_parts", "size_inr": _bet_total(rr), "parts": parts,
              "reason": "the guard that held the buy back has cleared: " + str(rr.get("reason") or ""), "worst_pct_book": (rr.get("outcome") or {}).get("worst_pct_book")}
        refs = act(con, now, case["case_id"], dd)
        bought = any(r.startswith(("paper_order", "us_order")) for r in refs)
        cases.record_decision(con, case["case_id"], day, isin=isin, symbol=sym, rule_option="buy_in_parts", model_option="buy_in_parts", acted_option="buy_in_parts" if bought else "nothing",
                              order_refs=refs, reason=dd["reason"][:400])
        out += refs
        if bought:
            try:
                tell(con, now, case["case_id"])
            except Exception:
                pass
    return out


def _unfinished(con, case_id: int) -> bool:
    n = int(think.settings()["parts"])
    return any(len(p) < n for p in _part_plans(con, case_id).values())


def follow_up(con, now: datetime, day: Optional[date] = None, *, root=None, web: Optional[Callable] = None) -> dict:
    """T7: every due look. A look is re-thought only when something changed (a new joined signal since the last answer); a part of a buy in parts is bought when it is due; a case is closed
    when nothing is pending and the position is decided, or after `quiet_close_sessions` quiet sessions. Releases a closed case's freezes. Never raises for one case. Idempotent per day."""
    if not think.on():
        return {"off": True}
    day = day or now.date()
    out = {"looked": 0, "rethought": 0, "parts": 0, "closed": 0, "extended": 0, "failed": []}
    st = think.settings()
    for c in cases.looks_due(con, day):
        cid = c["case_id"]
        try:
            if _last_think_day(con, cid) == day:
                continue
            out["looked"] += 1
            market = c.get("market") or "IN"
            if _changed(con, c):
                r = think_case(con, now, cid, root=root, web=web)
                out["rethought"] += 1
                if not r.get("ok"):
                    out["failed"].append(f"#{cid}: {r.get('failed')}")
                continue
            refs = _continue_parts(con, now, c) + _retry_refused(con, now, c)
            if any(x.startswith(("paper_order", "us_order")) for x in refs):
                out["parts"] += 1
            cases.add_step(con, cid, now, "looked", payload={"changed": False, "day": str(day), "parts": refs})
            quiet_from = _session_after(market, c["opened_on"], int(st["quiet_close_sessions"]))
            unfinished = _unfinished(con, cid)
            last_sig = max([s["day"] for s in cases.signals(con, case_id=cid)] or [c["opened_on"]])
            if day >= _session_after(market, last_sig, int(st["quiet_close_sessions"])) or (day >= quiet_from and not c.get("pending")):
                cases.close_case(con, cid, day, f"quiet for {st['quiet_close_sessions']} sessions")
                out["closed"] += 1
            elif not c.get("pending") and c["state"] in ("acted", "advisory") and not unfinished:
                cases.close_case(con, cid, day, "decided, nothing pending")
                out["closed"] += 1
            else:
                cases.set_case(con, cid, next_look_on=_session_after(market, day, int(st["look_max_sessions"])))
                out["extended"] += 1
            if cases.get_case(con, cid)["state"] == "closed":
                for f in cases.active_freezes(con, day):
                    if f["case_id"] == cid:
                        cases.release_freeze(con, f["freeze_id"])
        except Exception as e:
            out["failed"].append(f"#{cid}: {type(e).__name__}: {str(e)[:120]}")
    return out


# --- what Today and the 15:45 report show ---------------------------------------------------------------------------------------------------------------------------------------

def thinking_text(con, day: Optional[date] = None) -> str:
    """The "Thinking about" block plus the reserve lines (and a failed case's line): plain words, for Today and the 15:45 report."""
    day = day or date.today()
    parts = [cases.thinking_block(con, day)["text"]]
    try:
        failed = [c for c in cases.open_cases(con) if (c.get("summary") or "").startswith("thinking failed")]
        if failed:
            parts.append(f"Thinking failed on {len(failed)} case(s) ({failed[0]['summary'][:90]}): they stay open, thesis-break sales still act, nothing else changes.")
    except Exception:
        pass
    try:
        parts.append(reserve.text(con, day))
    except Exception:
        pass
    return " ".join(x if x.rstrip().endswith((".", "!", "?")) else x.rstrip() + "." for x in parts if x)
