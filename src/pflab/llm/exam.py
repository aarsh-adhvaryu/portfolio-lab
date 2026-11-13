"""S85 E2a, the exam: what `pflab engine test NAME [--thinking medium,high]` runs before an engine can be switched on (`gateway.use` asks `passed`).

    run(con, engine, *, thinking=("medium",), now=None, fake=None, spend_cap_rupees=60) -> report dict      one report per thinking level, one `engine_exam_s85` row each (`gateway.record_exam`)
    passed(con, engine) -> bool      the form part passed (in the newest exam of any thinking level)
    grade(con, engine) -> str        plain words: "agrees on 5 of 6 decisions, misses 1 fact in 10 documents, 7 times cheaper than claude"

Parts: (a) FORM, pass or fail: a tool call that works, twenty short structured answers that keep to the closed lists (`think.OPTIONS / CLASSES / WORDS`) with no number written where rule 8 forbids it
(`session.validate_answer`), fewer than three malformed; (b) JUDGMENT: stored reference cases (the S84 replays in short form: Nvidia held / not held, Ather's missed run, India rotation, Indian
governance, a market fall: synthetic names, the replays' registered class and option) and up to twenty real cases of the store (the reference is the in-use engine's own stored answer); (c) READING: ten
synthetic documents, five facts and five numbers each: facts found, and every number the engine gives must be in the source (`session._numbers`); (d) COST and TIME per case and the price of a desk day.
The exam sends the system's own stored work to the vendor: it runs only for an engine with a recorded consent for `exam` (`gateway.has_consent`), goes through the gateway (egress gate, governor, his
cap) with `scope="exam"`, never prints a key, and stops at `spend_cap_rupees`. `fake(**call)` replaces `gateway.call` (tests; the scripted drills).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional

from pflab import think

FORM_CALLS = 20
MALFORMED_FAILS = 3
SCOPE = "exam"

# --- the stored reference cases (the replays in short form; synthetic names) -----------------------------------------------------------------------------------------
REFERENCES = [
    {"name": "nvidia_held", "symbol": "NVDA", "held": True, "klass": "damage", "option": "sell",
     "text": "NVDA (a US chip maker, held, 8% of the US sub-book). Sunday evening press reports: the board is looking at its chief executive after a regulator's letter. The shares are down on the open."},
    {"name": "nvidia_not_held", "symbol": "NVDA", "held": False, "klass": "unclear", "option": "wait",
     "text": "NVDA (a US chip maker, NOT held, on the picks list). Press reports of Sunday evening: the board's decision on the chief executive is pending. The shares fell; no result is out."},
    {"name": "ather_missed_run", "symbol": "ATHR", "held": False, "klass": "temporary", "option": "buy_in_parts",
     "text": "ATHR (an Indian electric two-wheeler maker, NOT held, skipped three months ago for valuation). Since the day it was skipped it is 24 points ahead of its index; the reason for passing is not answered by results."},
    {"name": "india_rotation", "symbol": "FINX", "held": True, "klass": "market_fear", "option": "hold",
     "text": "FINX (an Indian private bank, held). The whole banking index fell with it on foreign selling; no company event is stored; its own results are as expected."},
    {"name": "india_governance", "symbol": "TEXO", "held": True, "klass": "damage", "option": "sell",
     "text": "TEXO (an Indian textile group, held). The exchange filing says the auditor resigned citing unexplained related-party payments; the promoter is named in a regulator's notice. Shares are down at the open."},
    {"name": "market_fall", "symbol": "NIFTYBEES", "held": True, "klass": "market_fear", "option": "hold",
     "text": "NIFTYBEES (a Nifty 50 index fund, held in the core). The index fell sharply for three sessions with every sector down together on a global sell-off; no company event."},
]
_NAMES = ["Alder Works", "Birch Foods", "Cedar Pumps", "Dune Telecom", "Elm Chemicals", "Fir Logistics", "Gorse Pharma", "Hazel Steel", "Iris Retail", "Juniper Power"]
CASE_SYSTEM = ("You are a thinking desk of a small paper portfolio. Read the situation and answer in the structured form: what happened, its class, what is pending, one choice per affected name from the "
               "closed menu, and a likelihood WORD for worst, likely and best. Never write a number as a field and never a figure the text did not give.")
TOY_TOOL = {"name": "lookup_close", "description": "The last stored close of a symbol (a toy tool of the exam).",
            "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}


def _doc(i: int) -> dict:
    """A synthetic stored document with five known facts and five numbers (the facts' `key` is a distinctive word the extract must carry)."""
    n = _NAMES[i]
    a, b, c, d, e = 120 + i * 7, 15 + i, 3 + (i % 4), 40 + i * 2, 900 + i * 11
    facts = [("approved", f"The board of {n} approved a dividend of Rs {c}.50 a share"), ("plant", f"{n} opened a new plant in the western region with capacity of {d} thousand tonnes"),
             ("auditor", f"The auditor of {n} gave an unqualified opinion"), ("debt", f"{n} repaid borrowings of Rs {e} crore during the year"),
             ("director", f"A new independent director joined the board of {n}")]
    nums = [f"{c}.50", f"{d}", f"{e}", f"{a}", f"{b}"]
    text = (f"{n} annual note. Revenue was Rs {a} crore and profit after tax Rs {b} crore. " + " ".join(f"{t}." for _, t in facts)
            + f" The note is dated in the year under review. (Reference: {a}, {b}.)")
    return {"company": n, "text": text, "facts": [k for k, _ in facts], "numbers": nums}


def documents() -> List[dict]:
    return [_doc(i) for i in range(10)]


READ_SCHEMA = {"type": "object", "properties": {"facts": {"type": "array", "items": {"type": "string"}}, "numbers": {"type": "array", "items": {"type": "string"}}}, "required": ["facts", "numbers"],
               "additionalProperties": False}


# --- calls ------------------------------------------------------------------------------------------------------------------------------------------------------------
class _Run:
    def __init__(self, con, engine: str, level: str, now, fake, cap: float):
        self.con, self.engine, self.level, self.now, self.fake, self.cap = con, engine, level, now, fake, cap
        self.cost, self.calls, self.secs, self.stopped = 0.0, 0, 0.0, False

    def ask(self, role: str, system, messages, **kw) -> Optional[dict]:
        """One call through the door; None on an error (counted by the caller as malformed), never raises. Stops at the spend cap."""
        if self.cost >= self.cap:
            self.stopped = True
            return None
        t0 = time.perf_counter()
        try:
            if self.fake is not None:
                r = self.fake(role=role, system=system, messages=messages, engine=self.engine, thinking=self.level, **kw)
            else:
                from pflab.llm import gateway
                r = gateway.call(self.con, role, system, messages, now=self.now, engine=self.engine, thinking=self.level, scope=SCOPE, agent="think", purpose="exam", **kw)
        except Exception as e:
            self.secs += time.perf_counter() - t0
            self.calls += 1
            return {"error": f"{type(e).__name__}: {str(e)[:120]}", "cost_rupees": 0.0}
        self.secs += time.perf_counter() - t0
        self.calls += 1
        r = r or {}
        self.cost += float(r.get("cost_rupees") or 0.0)
        return r


def _json_of(r: Optional[dict]):
    if not r or r.get("error"):
        return None
    j = r.get("json")
    if j is None and r.get("text"):
        try:
            j = json.loads(re.search(r"\{.*\}", r["text"], re.S).group(0))
        except Exception:
            j = None
    return j


def _case_prompt(i: int) -> tuple:
    ref = REFERENCES[i % len(REFERENCES)]
    return ref, f"CASE #{i + 1}: {ref['text']}"


def _classify(problems: List[str]) -> str:
    """'ok' | 'number' (a number written where rule 8 forbids) | 'list' (a closed list broken) | 'malformed' (missing fields, not an object)."""
    if not problems:
        return "ok"
    s = " ".join(problems)
    if "is a number" in s or "never writes" in s:
        return "number"
    if "must be one of" in s or "each choice needs" in s or "base_rate_set" in s:
        return "list"
    return "malformed"


def form_part(run: _Run) -> dict:
    from pflab.think import session
    out = {"tool_call": False, "answers": 0, "ok": 0, "number": 0, "list": 0, "malformed": 0, "problems": []}
    # tool loop with the stored toy tool
    msgs = [{"role": "user", "content": "Use the lookup_close tool for the symbol ZZTOY, then say in one short sentence what it returned."}]
    r1 = run.ask("quick", "You answer briefly and use tools when asked.", msgs, tools=[TOY_TOOL], max_tokens=600)
    calls = list((r1 or {}).get("tool_calls") or [])
    if calls and calls[0].get("name") == "lookup_close":
        c0 = calls[0]
        msgs = msgs + [{"role": "assistant", "content": (r1 or {}).get("assistant_content") or [{"type": "tool_use", "id": c0.get("id") or "t1", "name": c0["name"], "input": c0.get("input") or {}}]},
                       {"role": "user", "content": [{"type": "tool_result", "tool_use_id": c0.get("id") or "t1", "content": "close 100.0 on the last session"}]}]
        r2 = run.ask("quick", "You answer briefly and use tools when asked.", msgs, tools=[TOY_TOOL], max_tokens=600)
        out["tool_call"] = bool(r2 and not r2.get("error") and str(r2.get("text") or "").strip())
    for i in range(FORM_CALLS):
        ref, prompt = _case_prompt(i)
        r = run.ask("decide", CASE_SYSTEM, [{"role": "user", "content": prompt}], schema=session.ANSWER_SCHEMA, max_tokens=1500)
        if r is None:                                                     # the spend cap stopped the exam
            break
        out["answers"] += 1
        ans = _json_of(r)
        k = "malformed" if ans is None else _classify(session.validate_answer(ans, prompt))
        if k == "ok":
            out["ok"] += 1
        else:
            out[k] += 1
            out["problems"].append(f"call {i + 1}: {k}")
    out["pass"] = bool(out["tool_call"] and out["answers"] >= FORM_CALLS and out["number"] == 0 and out["list"] == 0 and out["malformed"] < MALFORMED_FAILS)
    if not out["tool_call"]:
        out["problems"].append("the tool call did not work")
    if out["answers"] < FORM_CALLS:
        out["problems"].append(f"only {out['answers']} of {FORM_CALLS} answers were asked (spend cap or an error)")
    return out


def _real_cases(con, n: int = 20) -> List[dict]:
    """The last `n` real cases with a stored decision: reference = the in-use engine's stored model option and class (its answer step)."""
    out: List[dict] = []
    try:
        from pflab.think import cases
        rows = con.execute("SELECT decision_id, case_id, symbol, model_option FROM think_decisions_s84 WHERE model_option IS NOT NULL ORDER BY decision_id DESC LIMIT ?", [n * 3]).fetchall()
        seen = set()
        for did, cid, sym, mopt in rows:
            if cid in seen:
                continue
            seen.add(cid)
            case = cases.get_case(con, cid) or {}
            klass, happened = None, ""
            for st in cases.steps(con, cid):
                try:
                    p = json.loads(st.get("payload_json") or "{}")
                except Exception:
                    continue
                a = p.get("answer") if isinstance(p.get("answer"), dict) else None
                if a:
                    klass, happened = a.get("class"), str(a.get("happened") or "")
            if klass in think.CLASSES:
                out.append({"name": f"case_{cid}", "symbol": str(sym or case.get("symbol") or "").upper(), "klass": klass, "option": mopt,
                            "text": f"{case.get('title') or sym}. {happened}"[:700]})
            if len(out) >= n:
                break
    except Exception:
        pass
    return out


def judgment_part(run: _Run) -> dict:
    from pflab.think import session
    refs = list(REFERENCES) + _real_cases(run.con)
    agree = n = 0
    rows = []
    missing = ["replay: Nvidia held, not held, Ather, India rotation, India governance and market fall are the short stored forms in this file (the full replays need their world data)"]
    for ref in refs:
        r = run.ask("decide", CASE_SYSTEM, [{"role": "user", "content": f"CASE: {ref['text']}"}], schema=session.ANSWER_SCHEMA, max_tokens=1500)
        if r is None:
            break
        ans = _json_of(r)
        if ans is None or session.validate_answer(ans, ref["text"]):
            n += 1
            rows.append({"case": ref["name"], "got": None, "want": ref["option"]})
            continue
        opts = [c.get("option") for c in ans.get("choices") or [] if isinstance(c, dict)]
        got_opt = opts[0] if opts else None
        hit = (got_opt == ref["option"]) and (ans.get("class") == ref["klass"])
        n += 1
        agree += int(hit)
        rows.append({"case": ref["name"], "got": [ans.get("class"), got_opt], "want": [ref["klass"], ref["option"]], "agree": hit})
    return {"agree": agree, "n": n, "rows": rows, "missing": missing}


def reading_part(run: _Run) -> dict:
    from pflab.think import session
    found = total = invented = docs = 0
    for d in documents():
        r = run.ask("read", "Extract the facts and the numbers of the document. Facts: short sentences. Numbers: every figure you use, as written.", [{"role": "user", "content": d["text"]}],
                    schema=READ_SCHEMA, max_tokens=900)
        if r is None:
            break
        docs += 1
        total += len(d["facts"])
        j = _json_of(r) or {}
        blob = " ".join(str(x) for x in (j.get("facts") or [])).lower()
        found += sum(1 for k in d["facts"] if k in blob)
        known = session._numbers(d["text"])
        got = session._numbers(" ".join(str(x) for x in (j.get("numbers") or [])) + " " + blob)
        invented += len([x for x in got if x not in known])
    return {"docs": docs, "facts_total": total, "facts_found": found, "missed": total - found, "invented_numbers": invented}


def cost_part(run: _Run, form: dict, judg: dict, read: dict) -> dict:
    cases_asked = max(1, form["answers"] + judg["n"])
    per_case = run.cost / max(1, run.calls) if run.calls else 0.0
    per_case_s = run.secs / max(1, run.calls)
    st = think.settings()
    per_day = float(st.get("max_cases_per_day", 3))
    desk = 2 * per_case * 4                                       # two desk sessions a day, about four calls each
    return {"calls": run.calls, "cost_rupees": round(run.cost, 4), "cost_per_call": round(per_case, 5), "seconds_per_call": round(per_case_s, 2), "cases_asked": cases_asked,
            "desk_day_rupees": round(per_day * per_case * 6 + desk, 3), "formula": "cases/day x (6 calls a case x cost per call) + desk (2 sessions x 4 calls)"}


# --- run / passed / grade ---------------------------------------------------------------------------------------------------------------------------------------------
def run(con, engine: str, *, thinking=("medium",), now: Optional[datetime] = None, fake: Optional[Callable] = None, spend_cap_rupees: float = 60.0) -> dict:
    """-> {"engine", "refused", "levels": {level: report}, "text"}. Refused (nothing sent) when the engine has no recorded consent for the exam. One row per level in `engine_exam_s85`."""
    from pflab.llm import gateway
    now = now or datetime.now()
    if isinstance(thinking, str):
        thinking = thinking.split(",")
    levels = [str(t).strip() for t in (thinking or []) if t and str(t).strip()] or ["medium"]
    st = gateway.settings()
    if fake is None:
        try:
            vendor = gateway.vendor_of(st, engine)
        except Exception as e:
            return {"engine": engine, "refused": f"the engine is not usable: {e}", "levels": {}, "text": f"{engine}: the engine is not usable ({e})"}
        if not gateway.has_consent(con, vendor, SCOPE):
            return {"engine": engine, "refused": "no recorded consent for the exam: nothing was sent", "levels": {},
                    "text": f"{engine}: the exam sends the system's own work to {vendor}; it needs his recorded Yes first (pflab engine shadow {engine} --yes records it)."}
    out: Dict[str, dict] = {}
    spent = 0.0
    for lv in levels:
        rn = _Run(con, engine, lv, now, fake, max(0.0, spend_cap_rupees - spent))
        form = form_part(rn)
        judg = judgment_part(rn) if not rn.stopped else {"agree": 0, "n": 0, "rows": [], "missing": ["stopped at the spend cap"]}
        read = reading_part(rn) if not rn.stopped else {"docs": 0, "facts_total": 0, "facts_found": 0, "missed": 0, "invented_numbers": 0}
        cost = cost_part(rn, form, judg, read)
        spent += rn.cost
        rep = {"thinking": lv, "form": form, "judgment": judg, "reading": read, "cost": cost, "stopped_at_cap": rn.stopped, "form_pass": bool(form["pass"])}
        rep["cheaper"] = _cheaper(con, engine, cost["cost_per_call"], st)
        rep["grade"] = _grade_text(rep)
        gateway.record_exam(con, engine, thinking=lv, form_pass=rep["form_pass"], grade=rep["grade"], cost_rupees=cost["cost_rupees"], detail=rep, now=now)
        out[lv] = rep
    return {"engine": engine, "refused": None, "levels": out, "text": "\n".join(f"[{lv}] {r['grade']} (form {'PASS' if r['form_pass'] else 'FAIL'}; Rs {r['cost']['cost_per_call']:.3f} a call, "
                                                                          f"Rs {r['cost']['desk_day_rupees']:.0f} a desk day)" for lv, r in out.items())}


def _list_price(st: dict, engine: str) -> Optional[float]:
    """Dollars per million (input + 3 x output) of the engine's decide-role model, or None."""
    try:
        from pflab.llm import gateway
        spec = gateway.roles(st, engine=engine).get("decide") or {}
        m = spec.get("model")
        for p in gateway.models_of(engine, st):
            if p["model"] == m:
                return p["price_in"] + 3.0 * p["price_out"]
    except Exception:
        pass
    return None


def _cheaper(con, engine: str, cost_per_call: float, st: dict) -> Optional[dict]:
    """'x times cheaper than <in-use engine>': the measured cost per call of the in-use engine's own newest exam, else the list-price ratio of the decide models."""
    try:
        from pflab.llm import gateway
        cur = gateway.current_engine(con, st)
        if cur == engine:
            return None
        r = con.execute("SELECT detail_json FROM engine_exam_s85 WHERE engine=? ORDER BY exam_id DESC LIMIT 1", [cur]).fetchone()
        if r:
            c0 = float(((json.loads(r[0] or "{}")).get("cost") or {}).get("cost_per_call") or 0.0)
            if c0 > 0 and cost_per_call > 0:
                return {"times": round(c0 / cost_per_call, 1), "than": cur, "basis": "measured"}
        a, b = _list_price(st, cur), _list_price(st, engine)
        if a and b:
            return {"times": round(a / b, 1), "than": cur, "basis": "list price"}
    except Exception:
        pass
    return None


def _grade_text(rep: dict) -> str:
    j, r = rep["judgment"], rep["reading"]
    parts = [f"agrees on {j['agree']} of {j['n']} decisions", f"misses {r['missed']} fact{'s' if r['missed'] != 1 else ''} in {r['docs']} documents"]
    if r.get("invented_numbers"):
        parts.append(f"{r['invented_numbers']} number(s) not in the source")
    ch = rep.get("cheaper")
    if ch and ch.get("times"):
        parts.append((f"{ch['times']:g} times cheaper than {ch['than']}" if ch["times"] >= 1 else f"{1 / ch['times']:.1f} times dearer than {ch['than']}") + (" (list price)" if ch["basis"] == "list price" else ""))
    return ", ".join(parts)


def _rows(con, engine: str) -> List[dict]:
    try:
        rows = con.execute("SELECT thinking, form_pass, grade, cost_rupees, ts FROM engine_exam_s85 WHERE engine=? ORDER BY exam_id DESC", [engine]).fetchall()
    except Exception:
        return []
    seen, out = set(), []
    for th, fp, g, c, ts in rows:                                  # the newest row of each thinking level
        if th not in seen:
            seen.add(th)
            out.append({"thinking": th, "form_pass": bool(fp), "grade": g, "cost_rupees": c, "ts": ts})
    return out


def passed(con, engine: str) -> bool:
    """The form part passed in the newest exam of at least one thinking level. False when no exam was run."""
    return any(r["form_pass"] for r in _rows(con, engine))


def grade(con, engine: str) -> str:
    """The grade in plain words of the best passing level (else the newest): 'agrees on 17 of 20 decisions, misses 1 fact in 10 documents, 7 times cheaper than claude'; 'not examined' when none."""
    rows = _rows(con, engine)
    if not rows:
        return f"{engine} has not been examined: pflab engine test {engine}"
    good = [r for r in rows if r["form_pass"]]
    r = (good or rows)[0]
    pre = "" if r["form_pass"] else "FAILED the form part (cannot be used): "
    return f"{pre}{r['grade']}" + (f" [thinking {r['thinking']}]" if r["thinking"] else "")
