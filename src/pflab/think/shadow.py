"""S85 E2a shadow: a candidate engine thinks every live case beside the engine in use. Its choice is stored and scored (a second track per engine) and NEVER acts.

    run(con, now, case, first, texts, day) -> list     called by `session.think_case` after the in-use engine's decision is recorded: for each shadow engine (`gateway.shadows`), one `read` call (no tools)
                                                         and one `decide` call (the closed-list answer), validated like the in-use engine's, run through `odds.option_table` and `rule.decide` with
                                                         THAT engine's calibration table, and stored: `think_shadow_s85` (the choice), the option rows `shadow:<engine>` (its choice) and
                                                         `shadow_rule:<engine>` (what the rule would have done on its answer). Nothing is ordered, no freeze set, no message sent.
    spent_today(con, day) -> float                     the shadows' spend today; a shadow call is skipped when it exceeds `[engines] shadow_daily_rupees` (default 25).

A shadow failure (a refusal, the cap, a malformed answer after one more ask) is one line on the case, never an error. `score.score_shadow` scores the tracks at 5, 20 and 60 sessions.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Callable, List, Optional

from pflab import think
from pflab.think import cases

DAILY_DEFAULT = 25.0
DEPS: dict = {}                                       # tests may put `gateway` (an object with `call`, `shadows`, `settings`) here


def _gw():
    if "gateway" in DEPS:
        return DEPS["gateway"]
    from pflab.llm import gateway
    return gateway


def daily_cap() -> float:
    try:
        return float(_gw().settings().get("shadow_daily_rupees", DAILY_DEFAULT))
    except Exception:
        return DAILY_DEFAULT


def spent_today(con, day: date) -> float:
    try:
        return float(con.execute("SELECT coalesce(sum(cost_rupees), 0) FROM think_shadow_s85 WHERE decided_on=?", [day]).fetchone()[0] or 0.0)
    except Exception:
        return 0.0


def _note(con, now, case_id: int, engine: str, text: str) -> None:
    try:
        cases.add_step(con, case_id, now, "shadow_note", payload={"engine": engine, "note": text[:240]})
    except Exception:
        pass


def _ask(con, now, case_id: int, engine: str, role: str, messages: list, *, schema=None, max_tokens: int) -> dict:
    from pflab.think import session
    r = _gw().call(con, role, [{"type": "text", "text": session.SYSTEM}], session.scrub(con, messages), case_id=None, purpose=f"shadow:{case_id}", now=now, max_tokens=max_tokens, schema=schema,
                   agent="think", engine=engine, scope="shadow") or {}
    return r


def _answer(con, now, case, first: str, texts: List[str], engine: str):
    """-> (answer or None, cost, problems)"""
    from pflab.think import session
    cost = 0.0
    r = _ask(con, now, case["case_id"], engine, "read", [{"role": "user", "content": first}], max_tokens=1200)
    cost += float(r.get("cost_rupees") or 0.0)
    reading = str(r.get("text") or "")
    known = first + "\n" + "\n".join(texts) + "\n" + reading
    msgs = [{"role": "user", "content": first + "\n\nYOUR READING SO FAR:\n" + (reading or "(none)") + "\n\nNow give the structured answer."}]
    problems: List[str] = []
    for attempt in (1, 2):
        r = _ask(con, now, case["case_id"], engine, "decide", msgs, schema=session.ANSWER_SCHEMA, max_tokens=1800)
        cost += float(r.get("cost_rupees") or 0.0)
        ans = r.get("json")
        if ans is None and r.get("text"):
            try:
                ans = json.loads(re.search(r"\{.*\}", r["text"], re.S).group(0))
            except Exception:
                ans = None
        problems = session.validate_answer(ans, known)
        if not problems:
            return ans, cost, []
        msgs = msgs + [{"role": "assistant", "content": r.get("text") or json.dumps(ans, default=str)}, {"role": "user", "content": "Your answer was refused: " + "; ".join(problems) + ". Answer again, fixing exactly that."}]
    return None, cost, problems


def _one(con, now: datetime, case: dict, first: str, texts: List[str], day: date, engine: str) -> Optional[dict]:
    from pflab.think import odds, rule, session
    ans, cost, problems = _answer(con, now, case, first, texts, engine)
    if ans is None:
        con.execute("INSERT INTO think_shadow_s85 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [cases._id(con, "think_shadow_s85", "shadow_id"), case["case_id"], engine, day, None, None, None, None, None, cost,
                                                                                      "no valid answer: " + "; ".join(problems[:2])[:200], now, None])
        _note(con, now, case["case_id"], engine, "no valid answer: " + "; ".join(problems[:2]))
        return None
    names = session._isin_map(con, case, ans)
    nans = session._normal(ans, names)
    cases.ENGINE_CTX["engine"] = engine                             # the words are read through THIS engine's own calibration table
    try:
        cache: dict = {}
        table = list(odds.option_table(con, case["case_id"], nans, day, cache=cache) or [])
        ruled = rule.decide(con, case["case_id"], nans, day, cache=cache) or {}
    finally:
        cases.ENGINE_CTX.pop("engine", None)
    per_name = {str(x.get("symbol") or "").upper(): x for x in (ruled.get("all") or [])}
    out = []
    for ch in nans["choices"][:session.MAX_CHOICES]:
        sym, isin = ch["symbol"], ch.get("isin")
        if isin is None and sym != str(case.get("symbol") or "").upper():
            continue
        isin = isin or case.get("isin")
        mine = session._rows_for(table, isin, sym)
        base = next((r for r in mine if r.get("option") == "nothing"), {})
        row = next((r for r in mine if r.get("option") == ch["option"]), None) or {**base, "worst_inr": 0.0, "likely_inr": 0.0, "best_inr": 0.0, "expected_inr": 0.0, "worst_pct_book": 0.0}
        rr = per_name.get(sym) or ruled
        ropt = "nothing" if rr.get("refused") else (rr.get("rule_option") or "nothing")
        rrow = next((r for r in mine if r.get("option") == ropt), None) or base
        session._store_row(con, case["case_id"], now, f"shadow:{engine}", {**row, "isin": isin, "symbol": sym, "option": ch["option"], "size_inr": 0.0}, chosen=True, reason=str(ch.get("reason") or ""), size_inr=0.0)
        session._store_row(con, case["case_id"], now, f"shadow_rule:{engine}", {**rrow, "isin": isin, "symbol": sym, "option": ropt, "size_inr": 0.0}, chosen=True, reason=str(rr.get("reason") or ""), size_inr=0.0)
        con.execute("INSERT INTO think_shadow_s85 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [cases._id(con, "think_shadow_s85", "shadow_id"), case["case_id"], engine, day, isin, sym, ans.get("class"), ch["option"], ropt,
                                                                                      cost / max(1, len(nans["choices"][:session.MAX_CHOICES])), "", now, json.dumps(ans.get("likelihood") or {})])
        out.append({"engine": engine, "symbol": sym, "option": ch["option"], "rule": ropt, "class": ans.get("class")})
    return {"engine": engine, "rows": out, "cost": cost}


def run(con, now: datetime, case: dict, first: str, texts: List[str], day: date) -> List[dict]:
    """Every shadow engine, one after the other. Never raises, never acts."""
    out: List[dict] = []
    try:
        gw = _gw()
        engines = [e for e in gw.shadows(con)]
        cur = gw.current_engine(con) if hasattr(gw, "current_engine") else None
    except Exception:
        return out
    for eng in engines:
        if eng == cur:
            continue
        try:
            if spent_today(con, day) >= daily_cap():
                _note(con, now, case["case_id"], eng, f"skipped: the shadows' spend today is at the cap (Rs {daily_cap():g})")
                continue
            r = _one(con, now, case, first, texts, day, eng)
            if r:
                out.append(r)
        except Exception as e:
            why = f"{type(e).__name__}: {str(e)[:160]}"
            try:
                why = gw.refusal_reason(e) or why
            except Exception:
                pass
            _note(con, now, case["case_id"], eng, "shadow failed: " + why)
    return out
