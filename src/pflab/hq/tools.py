"""The brain's tools (S60, PLAN A18): one registry of plain functions, each with a strict JSON schema.

    read     look at the system's facts (all built by code; nothing paid): the portfolio, every stock's drift / odds /
             edge, tax plan, reviewed measures, simulations, forecasts, readings, the graph, notes, memory, its own
             journal and record, ready plans, research flags, price history, quant templates
    journal  the brain's own ledgers, always written: predictions (scored by the keeper), suggestions (the suggestion
             ledger), its working state (memory, superseding the last)
    action   what would change something outside the brain: ask or tell the investor, order research or a calculation, prepare a
             plan, correct a memory row, fetch a cited page. Carried out (The investor 2026-10-25), at most DAILY a day each; the
             rival's (and in shadow mode all) are recorded as decisions only
Inputs are checked here against the schema even though the API's strict mode guarantees them (a test, a replay, a
model without strict mode); results are compact JSON that names its source, redacted (`hq/redact.py`: ids, his name and
address words, PAN, e-mail, phone, UPI, IFSC) and passed through the egress check (the bare word "address" is not read:
public filings name their offices) before they go back to the model; every call is logged in `hq_tool_calls`. Later
turns of a pass send only these checked results, so the API road does not check them a second time.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

RESULT_CHARS = 6_000
KINDS = ("read", "journal", "action")


@dataclass
class Ctx:
    rt: Any
    pass_id: Optional[int]
    model: str
    shadow: bool
    syms: Dict[str, str]                         # symbol -> isin the brain may predict and suggest on
    gate: Any
    now: datetime
    client: Any = None
    mode: str = "economy"
    source: str = ""                             # everything the brain has read this pass (for the number check)
    decisions: List[dict] = field(default_factory=list)
    predictions: List[int] = field(default_factory=list)
    suggestions: List[int] = field(default_factory=list)
    results: Dict[str, str] = field(default_factory=dict)
    problems: List[str] = field(default_factory=list)
    state: Optional[str] = None
    case_ids: List[int] = field(default_factory=list)     # S67: the cases this pass works on (opened or handed to it)
    _book: Any = None

    @property
    def con(self):
        return self.rt.cursor()

    @property
    def asof(self) -> date:
        return self.now.date()

    def book(self):
        if self._book is None:
            from pflab.app import research
            from pflab.hq import stocks
            self._book = stocks.book(self.con, self.asof, research.read_cache(self.rt, "watch"))
        return self._book


@dataclass(frozen=True)
class Tool:
    name: str
    kind: str
    about: str
    params: Dict[str, dict]
    required: Tuple[str, ...]
    fn: Callable[[Ctx, dict], dict]

    def schema(self) -> dict:
        return {"type": "object", "additionalProperties": False, "properties": self.params,
                "required": list(self.required)}

    def definition(self, strict: bool = True) -> dict:
        """For the API: bounds the strict grammar may not take are moved into the descriptions (checked here anyway)."""
        props = {}
        for k, v in self.params.items():
            d = {x: y for x, y in v.items() if x not in ("minimum", "maximum", "maxLength", "maxItems")}
            if "minimum" in v:
                d["description"] = f"{v.get('description', '')} (from {v['minimum']:g} to {v['maximum']:g})".strip()
            elif "maxLength" in v:
                d["description"] = f"{v.get('description', '')} (at most {v['maxLength']} characters)".strip()
            props[k] = d
        d = {"name": self.name, "description": f"[{self.kind}] {self.about}",
             "input_schema": {**self.schema(), "properties": props}}
        if self.required and strict:       # the API takes at most 20 strict tools: the first 20 with required inputs
            d["strict"] = True
        return d


def _s(about: str, max_len: int = 600, enum=None) -> dict:
    d = {"type": "string", "description": about}
    if enum:
        d["enum"] = list(enum)
    else:
        d["maxLength"] = max_len
    return d


def _i(about: str, lo: int, hi: int) -> dict:
    return {"type": "integer", "description": about, "minimum": lo, "maximum": hi}


def _n(about: str, lo: float, hi: float) -> dict:
    return {"type": "number", "description": about, "minimum": lo, "maximum": hi}


_PY = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list}


def validate(tool: Tool, args: Any) -> Optional[str]:
    """None when `args` fits the tool's schema; else what is wrong."""
    if not isinstance(args, dict):
        return "the input must be an object"
    extra = set(args) - set(tool.params)
    if extra:
        return f"unknown field(s): {', '.join(sorted(extra))}"
    missing = [k for k in tool.required if k not in args]
    if missing:
        return f"missing field(s): {', '.join(missing)}"
    for k, v in args.items():
        sch = tool.params[k]
        t = sch["type"]
        if not isinstance(v, _PY[t]) or (t in ("integer", "number") and isinstance(v, bool)):
            return f"{k}: must be {t}"
        if "enum" in sch and v not in sch["enum"]:
            return f"{k}: one of {sch['enum']}"
        if t in ("integer", "number") and not sch.get("minimum", -1e18) <= v <= sch.get("maximum", 1e18):
            return f"{k}: between {sch.get('minimum')} and {sch.get('maximum')}"
        if t == "string" and len(v) > sch.get("maxLength", 10_000):
            return f"{k}: at most {sch['maxLength']} characters"
        if t == "array":
            it = sch.get("items", {})
            if len(v) > sch.get("maxItems", 50) or any(not isinstance(x, str) or ("enum" in it and x not in it["enum"])
                                                       for x in v):
                return f"{k}: a list of {it.get('enum') or 'strings'}"
    return None


# --- read tools ------------------------------------------------------------------------------------------------------

def _rs(x) -> str:
    from pflab.hq.brain import _rs as rs
    return rs(float(x))


def _h(text: str, n: int = 10) -> str:
    """A key that is the same after a restart (Python's hash() is not): the same question or message is asked or sent once."""
    import hashlib
    return hashlib.sha1(text.strip().lower().encode("utf-8")).hexdigest()[:n]


def _isin(ctx: Ctx, symbol: str) -> str:
    i = ctx.syms.get((symbol or "").strip().upper())
    if i:
        return i
    r = ctx.con.execute("SELECT isin FROM instruments WHERE upper(symbol)=? LIMIT 1", [(symbol or "").strip().upper()]).fetchone()
    if not r:
        raise LookupError(f"no instrument with the symbol {symbol!r}")
    return r[0]


def portfolio(ctx: Ctx, a: dict) -> dict:
    from pflab.pm import today
    con = ctx.con
    t = today.build(con, ctx.asof)
    pos = t["positions"]
    pos = pos[pos["value"].notna() & (pos["qty"] > 0)]
    total = float(t["investable"]) or 1.0
    eq = {i for (i,) in con.execute("SELECT isin FROM instruments WHERE asset_class='equity'").fetchall()}
    by = pos.groupby(["symbol", "isin", "bucket"], as_index=False)[["value", "cost"]].sum().sort_values("value", ascending=False)
    hold = [{"symbol": r.symbol, "bucket": r.bucket, "weight_pct": round(r.value / total * 100, 2), "value": _rs(r.value),
             "gain_pct": round((r.value / r.cost - 1) * 100, 1) if r.cost else None} for r in by.head(40).itertuples()]
    st = by[by["isin"].isin(eq)]
    sv, sc = float(st["value"].sum()), float(st["cost"].sum())
    priced = by[by["cost"] > 0]
    av, ac = float(priced["value"].sum()), float(priced["cost"].sum())
    targets = {}
    try:
        from pflab.plan import targets as tg
        targets = {b.bucket: b for b in tg.load().buckets.values()}
    except Exception:
        pass
    buckets = []
    for k, v in sorted(t["buckets"].items(), key=lambda kv: -kv[1]):
        if not v:
            continue
        b = targets.get(k)
        buckets.append({"bucket": k, "weight_pct": round(v / total * 100, 1), "value": _rs(v),
                        **({"target_pct": round(b.target * 100, 1), "soft_band_pct": round(b.soft_band * 100, 1),
                            "hard_band_pct": round(b.hard_band * 100, 1)} if b else {})})
    td = t["today"]
    return {"asof": str(ctx.asof), "source": td["source"], "kite_snapshot_at": td.get("snapshot_at"),
            "statements_to": str(td.get("documents_to")), "investable": _rs(total), "net_worth": _rs(t["net_worth"]),
            "buckets": buckets, "holdings": hold,
            "direct_stocks": {"names": int(len(st)), "value": _rs(sv), "cost": _rs(sc), "unrealised_gain": _rs(sv - sc),
                              "gain_pct": round((sv / sc - 1) * 100, 2) if sc else None},
            "all_priced_holdings": {"value": _rs(av), "cost": _rs(ac), "unrealised_gain": _rs(av - ac),
                                    "gain_pct": round((av / ac - 1) * 100, 2) if ac else None},
            "kite_vs_statements": [f"{d['symbol']}: Kite {d['kite']:g}, statements {d['ledger']:g}" for d in td.get("diffs", [])],
            "fall_limit": "the portfolio is checked against a 35% fall (Monte Carlo)",
            "source_note": "pm/today.py: the ledger with the broker account replaced by the newest Kite snapshot; gains "
                           "are unrealised (cost basis of the lots held); realised gains are in tax_plan"}


def stocks_overview(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import stocks
    return stocks.overview(ctx.con, ctx.rt.data_root, ctx.book())


def stock_facts(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import stocks
    return stocks.facts(ctx.con, ctx.rt.data_root, ctx.book(), a["symbol"], tuple(a.get("parts") or ("drift", "odds", "edge", "valuation", "nudges")))


def comovement(ctx: Ctx, a: dict) -> dict:
    from pflab.quant import comove
    return comove.moves_with(a["symbol"], ctx.rt.data_root)


def tax_plan(ctx: Ctx, a: dict) -> dict:
    from pflab.tax import plan as tp
    return {"lines": tp.render(tp.overview(ctx.con, ctx.asof))[:60],
            "source": "tax/plan.py: the tax engine replays each sale (both regimes), FIFO lots, 112A exemption"}


INDEX_KEYS = {"NIFTY 50": "NIFTY50_PRICE", "NIFTY50": "NIFTY50_PRICE", "NIFTY 500": "NIFTY500_TRI",
              "NIFTY500": "NIFTY500_TRI"}


def _series(ctx: Ctx, name: str):
    import pandas as pd
    key = INDEX_KEYS.get(name.strip().upper())
    if key:
        from pflab.data import indices
        df = indices.load(key, ctx.rt.data_root)
        return df[["date", "close"]], key
    from pflab.hq import stocks
    c = stocks.closes(ctx.con, ctx.rt.data_root, _isin(ctx, name), ctx.asof)
    return pd.DataFrame({"date": c.index, "close": c.values}), name.upper()


def measure(ctx: Ctx, a: dict) -> dict:
    from pflab.calc import measures as ms
    s, label = _series(ctx, a["series"])
    second = None
    if a.get("second"):
        second, l2 = _series(ctx, a["second"])
    vals = {k: a[k] for k in ("start", "end", "fall_pct", "sessions", "level") if k in a}
    out = ms.run(a["measure"], s, vals, second)
    return {"computed": ms.describe(a["measure"], label, vals, a.get("second")), **out,
            "source": "calc/measures.py (reviewed measures)"}


def simulation(ctx: Ctx, a: dict) -> dict:
    from pflab.app import sims
    years = int(a.get("years", 5))
    out = sims.run(ctx.rt, paths=10_000, years=years)
    mixes = {}
    for name, mx in out["mixes"].items():
        y = mx["fan"]["years"].get("1", {})
        worst = sorted([e for e in mx["stress"]["episodes"] if e.get("covered")], key=lambda e: e["worst_fall"])[:3]
        mixes[name] = {"chance_35pct_fall": mx["fall"].get("text"),
                       "one_rupee_after_1y_p5_p50_p95": [round(y[k], 3) for k in ("p5", "p50", "p95")] if y else None,
                       "worst_episodes": [f"{e['name']} {e['worst_fall'] * 100:.0f}%" for e in worst]}
    return {"paths": 10_000, "years": years, "history": out["history"], "mixes": mixes,
            "source": "app/sims.py (block bootstrap, risk/montecarlo.py)"}


def forecasts(ctx: Ctx, a: dict) -> dict:
    from pflab.quant import forecast as fc
    con = ctx.con
    method, label = fc.serving_method(ctx.rt.data_root)
    q = ("SELECT use, subject, as_of, target, q10, q50, q90, model FROM forecasts WHERE as_of = (SELECT max(as_of) "
         "FROM forecasts) AND (model IS NULL OR model IN ('baseline', ?))")
    args: list = [method]
    if a.get("symbol"):
        sym = a["symbol"].strip().upper()
        q += " AND (upper(subject) LIKE ? OR subject = ?)"
        args += [f"%{sym}%", ctx.syms.get(sym, "")]
    rows = con.execute(q + " ORDER BY use, subject LIMIT 30", args).fetchall()
    cover = {f"{m} {h} sessions": c for m in fc.METHODS for h in fc.PRICE_H if (c := fc.coverage(con, m, h))}
    return {"rows": [{"use": u, "subject": s, "as_of": str(a_), "target": str(t), "q10": q1, "q50": q5, "q90": q9,
                      "model": m} for u, s, a_, t, q1, q5, q9, m in rows],
            "price_ranges": f"80% ranges of the price (q10 to q90), method {method}: {label}",
            "rolling_coverage_last_60_scored": {k: f"{v['covered']:.0%} of {v['n']}" for k, v in cover.items()},
            "source": "quant/forecast.py (calibrated statistics: block bootstrap with the CAPM centre; baselines for turnover and results)"}


def readings(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import readers
    isin = _isin(ctx, a["symbol"])
    since = ctx.now - timedelta(days=int(a.get("days", 30)))
    rows = [r for r in readers.recent(ctx.con, since, material_only=False) if isin in r["isins"]][:10]
    from pflab.hq import recency
    return {"readings": recency.stamp([{"kind": r["kind"], "published": str(r["published"])[:10], "material": r.get("material"),
                                        "summary": (r["summary"] or "")[:400], "figures": r["figures"][:4]} for r in rows],
                                      None, ctx.asof),
            "source": "hq/readers.py (Haiku readings; figures kept only when found in the document); stale = older than "
                      "the policy (news 3 days, filings 30, results 100)"}


def graph_timeline(ctx: Ctx, a: dict) -> dict:
    from pflab.kg import graph as g
    isin = _isin(ctx, a["symbol"])
    df = g.timeline(ctx.con, f"company:{isin}", ctx.now - timedelta(days=int(a.get("days", 30))),
                    kinds=("filing", "result", "article", "reading", "analyst_note", "dataset", "deal", "holding"), limit=20)
    from pflab.hq import recency
    items = [{"date": str(r.published_at)[:10], "kind": r.kind, "title": (r.title or "")[:160],
              "url": getattr(r, "url", None)} for r in df.itertuples()]
    return {"items": recency.stamp(items, None, ctx.asof, date_key="date"),
            "source": "knowledge graph (kg/graph.py); stale = older than the policy (news 3 days, filings 30, results 100)"}


def notes(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import memory as mem
    rows = mem.recall(ctx.con, subject=a["symbol"].strip().upper(), kinds=["note"], asof=ctx.asof, limit=2)
    return {"notes": [m.line()[:2000] for m in rows] or ["no analyst note on record"],
            "source": "memory (the analyst's newest cited note per company)"}


def memory_recall(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import memory as mem
    rows = mem.recall(ctx.con, subject=a.get("subject") or None, kinds=[a["kind"]] if a.get("kind") else None,
                      words=a.get("words", ""), asof=ctx.asof, limit=15)
    return {"rows": [m.line()[:400] for m in rows], "source": "memory (rows in force today; #id to correct one)"}


def journal(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import brain, keeper, suggestions as sg
    mine = [p for p in brain.journal(ctx.con, 30) if p["model"] == ctx.model and p["status"] == "done"][:6]
    return {"passes": [{"id": p["id"], "at": str(p["at"])[:16], "trigger": p["trigger"], "note": (p["note"] or "")[:300],
                        "actions": [f"{d['action']}: {d.get('subject', '')}"[:120] for d in p["decisions"]]} for p in mine],
            "scorecard": keeper.scorecard_text(ctx.con, ctx.model), "suggestions": sg.lessons_text(ctx.con, ctx.model),
            "source": "hq_passes, hq_predictions, hq_suggestions"}


def ready_plans(ctx: Ctx, a: dict) -> dict:
    from pflab.plan import ready
    out = []
    for p in ready.current(ctx.con, 4):
        out.append({k: (v[:800] if isinstance(v, str) else v) for k, v in p.items()
                    if isinstance(v, (str, int, float)) and k not in ("inputs_hash",)})
    return {"plans": out, "source": "plan/ready.py (kept current; tickets are entered by the investor)"}


def research_flags(ctx: Ctx, a: dict) -> dict:
    since = ctx.now - timedelta(days=int(a.get("days", 14)))
    q, args = "SELECT symbol, kind, happened_at, detail FROM research_flags WHERE detected_at >= ?", [since]
    if a.get("symbol"):
        q += " AND isin = ?"
        args.append(_isin(ctx, a["symbol"]))
    else:
        mine = list(ctx.syms.values()) or [""]
        q += f" AND isin IN ({','.join('?' * len(mine))})"
        args += mine
    rows = ctx.con.execute(q + " ORDER BY happened_at DESC LIMIT 20", args).fetchall()
    from pflab.hq import recency
    return {"flags": recency.stamp([{"symbol": s, "kind": "flag:" + k, "at": str(h)[:16], "detail": (d or "")[:300]}
                                    for s, k, h, d in rows], None, ctx.asof, date_key="at"),
            "source": "agents/researcher.py (flags found and measured by code)"}


def price_history(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import stocks
    c = stocks.closes(ctx.con, ctx.rt.data_root, _isin(ctx, a["symbol"]), ctx.asof)
    c = c.iloc[-int(a.get("days", 250)):]
    w = c.resample("W").last().dropna().iloc[-40:]
    return {"trend": stocks.trend(c), "weekly_closes": [[str(d.date()), round(float(v), 2)] for d, v in w.items()],
            "source": "prices (research panel's adjusted closes joined to the store's)"}


def quant(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import quant as qn
    return {"text": qn.run(a["idea"], ctx.rt.data_root)[:3000],
            "source": "agents/quant.py (tested templates; a new claim needs a pre-registered study)"}


def who_is_buying(ctx: Ctx, a: dict) -> dict:
    """S63: insider / SAST disclosures, bulk and block deals, promoters and pledges, institutions by quarter."""
    from pflab.hq import context
    sym = a["symbol"].strip().upper()
    return context.holders(ctx.con, ctx.rt.data_root, _isin(ctx, sym), sym, ctx.asof, int(a.get("days", 180)))


def market_context(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import context
    return context.market(ctx.rt.data_root, ctx.asof)


def growth(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import context
    return context.growth(ctx.con, ctx.asof, int(a.get("months", 12)))


def findings(ctx: Ctx, a: dict) -> dict:
    """S62: what the learner tested. Passed claims with, for a stock signal, where each held and listed name sits today;
    failed ones listed so they are not relied on."""
    import json as _json
    from pflab.learner import templates as tp
    con = ctx.con
    rows = con.execute("SELECT c.claim_id, c.claim, c.template, c.params_json, c.decision, c.why, s.title FROM learn_claims c "
                       "JOIN learn_sources s USING (src_id) WHERE c.status IN ('passed','failed') ORDER BY c.decided_at DESC "
                       "LIMIT 30").fetchall()
    passed, failed = [], []
    for cid, claim, t, prm, d, why, title in rows:
        item = {"claim": claim[:300], "test": f"{t} {prm}", "result": (why or "")[:300], "source": (title or "")[:120],
                "claim_id": cid}
        if d == "pass" and t == "cross_section":
            p = _json.loads(prm)
            q = tp.today_quintiles(con, ctx.rt.data_root, p["signal"], list(ctx.syms.values()), ctx.asof)
            names = {v: k for k, v in ctx.syms.items()}
            item["today"] = {names.get(i, i): f"quintile {v['quintile']} of 5 ({p['signal']} {v['value']:.3g}, "
                                              f"breakpoints {v['breakpoints_at']})" for i, v in q.items()}
            item["claimed_quintile"] = 5 if p["direction"] == "high" else 1
        elif d == "pass" and t == "rule_filter":
            from pflab.learner import rules
            p = _json.loads(prm)
            try:
                item["today"] = rules.today(ctx.con, ctx.rt.data_root, p["rule"], ctx.asof) or "none of his names meets it today"
            except Exception as e:
                item["today"] = f"not read ({type(e).__name__})"
            item["claimed"] = ("the names that meet it earn MORE than the rest" if p["direction"] == "out"
                               else "the names that meet it earn LESS than the rest")
        (passed if d == "pass" else failed).append(item)
    from pflab.learner import counter
    return {"passed": passed, "failed": [{k: f[k] for k in ("claim", "result", "claim_id")} for f in failed[:15]],
            "tests_run": counter.n_tests(con), "bar_for_next_test": counter.line(con),
            "source": "learner (claims from reading, each registered before its test; learner/templates.py decides)"}


# --- journal tools ---------------------------------------------------------------------------------------------------

def record_prediction(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import brain, keeper
    pr, problem = brain.check_prediction(a, ctx.syms, ctx.now)
    if problem:
        raise ValueError(problem)
    pid = keeper.add_prediction(ctx.con, ctx.pass_id, ctx.model, pr, ctx.now)
    if pid is None:
        raise ValueError(f"no close on record for {pr['symbol']}: not kept")
    ctx.predictions.append(pid)
    return {"kept": pid, "scored": "on the close at its due date, against the stock's own base rate"}


def record_suggestion(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import analyst as an
    from pflab.hq import keeper, stocks, suggestions as sg
    sym = (a.get("symbol") or "").strip().upper()
    isin = facts = ref = qty = None
    if sym:
        if sym not in ctx.syms:
            raise ValueError(f"{sym} is neither held nor on the stock list")
        isin = ctx.syms[sym]
        bk = ctx.book()
        facts = stocks.facts(ctx.con, ctx.rt.data_root, bk, sym, ("drift", "valuation"))
        s = keeper.closes(ctx.con, isin, ctx.asof, days=15)
        ref = (s.index[-1].date(), float(s.iloc[-1])) if len(s) else None
        qty = float(bk.qtys.get(isin, 0.0))
    text, d1 = an.only_sourced_numbers(a["text"], an.Request(ctx.source, "brain"))
    why, d2 = an.only_sourced_numbers(a["reasoning"], an.Request(ctx.source, "brain"))
    if d1 or d2:
        ctx.problems.append(f"suggestion on {sym or 'the portfolio'}: {d1 + d2} sentence(s) dropped (numbers not read)")
    data = {"rested_on": {n: ctx.results.get(n, "(not called this pass)")[:1500] for n in a.get("rested_on", [])},
            "facts_at_the_time": facts}
    sid = sg.record(ctx.con, pass_id=ctx.pass_id, model=ctx.model, kind=a["kind"], isin=isin, symbol=sym or None,
                    text=text.split("\n\n(")[0], reasoning=why.split("\n\n(")[0], data=data,
                    horizon_days=int(a["horizon_days"]), now=ctx.now, shadow=ctx.shadow, ref=ref, ref_qty=qty, facts=facts,
                    root=ctx.rt.data_root, amount=stocks.order_size(bk, isin) if isin and a["kind"] == "add" else None)
    ctx.suggestions.append(sid)
    q = ctx.con.execute("SELECT quality, quality_why, price_low, price_high, max_buy, amount, wrong_if, watch_id "
                        "FROM hq_suggestions WHERE sug_id=?", [sid]).fetchone()
    st = ctx.con.execute("SELECT stats_json FROM hq_suggestions WHERE sug_id=?", [sid]).fetchone()[0]
    nudges_ = (json.loads(st).get("nudges") if st else None) or []
    return {"kept": sid, "quality_at_the_time": q[0], "why": q[1],
            "nudges": [n["text"] for n in nudges_] or "none apply (tips from unregistered sources cannot be checked)",
            "numbers_by_code": {"price_low": q[2], "price_high": q[3], "highest_buy": q[4], "amount_rs": q[5],
                                "wrong_if": q[6], "price_watch": q[7]},
            "scored": f"in {a['horizon_days']} days against the Nifty 500, taken or not"}


def save_state(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import memory as mem
    from pflab.hq import brain
    subject = f"brain:{ctx.model}"
    prev = ctx.con.execute("SELECT max(mem_id) FROM memory WHERE kind='state' AND subject=? AND valid_to IS NULL",
                           [subject]).fetchone()[0]
    state = brain.unnamed(a["state"], ctx.gate.names)
    mid = mem.remember(ctx.con, "state", state, subject=subject, source=f"brain pass #{ctx.pass_id}", now=ctx.now,
                       supersedes=prev)
    ctx.state = state
    return {"saved": mid, "supersedes": prev}


# --- action tools ----------------------------------------------------------------------------------------------------

def _checked(ctx: Ctx, text: str) -> str:
    from pflab.agents import analyst as an
    out, n = an.only_sourced_numbers(text, an.Request(ctx.source, "brain"))
    if n:
        ctx.problems.append(f"{n} sentence(s) dropped from an action (numbers not read)")
    return out.split("\n\n(")[0] if n else out


# Actions carried out a day at most (The investor 2026-10-25: minimum of him; a noisy day never floods him or the cap).
# Beyond it the decision is kept in the journal ("held") and the brain is told. S62: the learner may propose a change,
# applied only with the investor's yes (`learned` daily_cap); web_search is paid, so few.
DAILY = {"tell_investor": 3, "ask_investor": 2, "change_preference": 3, "order_research": 3, "order_calculation": 3, "fetch_cited": 5, "web_search": 3, "request_report": 5, "case_calculate": 3, "resolve_task": 5, "register_experiment": 2}


def daily_cap(con, tool: str) -> Optional[int]:
    from pflab.learner import live
    v = live.values(con, "daily_cap").get(tool)
    return int(v) if v is not None else DAILY.get(tool)


def acted_today(ctx: Ctx, tool: str) -> int:
    day0 = datetime(ctx.now.year, ctx.now.month, ctx.now.day)
    return int(ctx.con.execute("SELECT count(*) FROM hq_tool_calls WHERE tool=? AND status='ran' AND called_at >= ?",
                               [tool, day0]).fetchone()[0])


def _act(ctx: Ctx, decision: dict, do: Callable[[], Any], tool: str = "") -> dict:
    decision = {**decision, "shadow": ctx.shadow}
    ctx.decisions.append(decision)
    if ctx.shadow:
        return {"recorded": True, "carried_out": False,
                "why": "journal only (shadow mode, or the cheaper rival): not carried out"}
    n = daily_cap(ctx.con, tool) if tool else None
    if n is not None and acted_today(ctx, tool) >= n:
        decision["held"] = f"today's limit of {n} reached"
        return {"recorded": True, "carried_out": False, "why": f"today's limit of {n} for {tool} is reached: kept in "
                                                               "the journal; say it in the note if it matters"}
    decision["done"] = str(do())[:300]
    return {"recorded": True, "carried_out": True, "result": decision["done"]}


def _decision(action: str, agent: str, subject: str, question: str, reason: str, priority: str = "medium") -> dict:
    return {"action": action, "agent": agent, "subject": subject, "question": question, "reason": reason,
            "priority": priority}


def ask_investor(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import questions as qs
    q, why = _checked(ctx, a["question"]), _checked(ctx, a["why"])
    return _act(ctx, _decision("ask", "", "", q, why),
                lambda: qs.ask(ctx.con, "brain", f"brain:{_h(q)}", q, ctx.now), "ask_investor")


def tell_investor(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import messenger
    m = _checked(ctx, a["message"])
    return _act(ctx, _decision("tell", "", "", m, "", a["priority"]),
                lambda: messenger.send_now(ctx.rt, f"Brain: {m}", "brain", dedup_key=f"brain:{_h(m)}:{ctx.now:%Y%m%d}"), "tell_investor")


def order_research(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import board
    q = a["question"]                          # a request to an agent: its numbers are parameters, not claims
    return _act(ctx, _decision("investigate", "research", a["symbol"].upper(), q, _checked(ctx, a.get("why", ""))),
                lambda: board.post(ctx.con, "research", f"{a['symbol'].upper()}: {q}", ctx.now, frm="brain"), "order_research")


def order_calculation(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import board
    q = a["question"]
    return _act(ctx, _decision("investigate", "calc", "", q, _checked(ctx, a.get("why", ""))),
                lambda: board.post(ctx.con, "calc", q, ctx.now, frm="brain"), "order_calculation")


def change_preference(ctx: Ctx, a: dict) -> dict:
    """S65: a change HE asked for, put to him as one exact edit (plan/prefs.py); his yes applies it."""
    from pflab.plan import prefs
    try:
        words = prefs.check(a["kind"], a["key"], a["value"])
    except (prefs.PrefError, ValueError) as e:
        return {"recorded": False, "carried_out": False, "why": f"not a change I can put to him: {e}"}
    return _act(ctx, _decision("ask", "", a["kind"], f"change: {words}", _checked(ctx, a["why"])),
                lambda: f"proposal #{prefs.propose(ctx.con, a['kind'], a['key'], a['value'], a['why'], ctx.now)}: waiting for his yes",
                "change_preference")


def prepare_plan(ctx: Ctx, a: dict) -> dict:
    from pflab.app import research
    amt = a.get("amount")
    def do() -> str:
        res = research.compute_plan(ctx.rt, amt)            # S65: it reports a count, or the error it kept; never "0 plans" for a failure
        if res.get("error"):
            ctx.problems.append(f"prepare_plan failed: {res['error'][:160]}")
            return f"plan refresh FAILED: {res['error'][:200]}"
        return f"{res.get('plans', 0)} plan(s) refreshed" + (f", one for Rs {amt:,.0f}" if amt else "")
    return _act(ctx, _decision("prepare_plan", "", f"Rs {amt:,.0f}" if amt else "the ready plans", "", _checked(ctx, a["why"])), do)


def correct_memory(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import memory as mem
    if not ctx.con.execute("SELECT 1 FROM memory WHERE mem_id=? AND valid_to IS NULL", [a["mem_id"]]).fetchone():
        raise ValueError(f"no memory #{a['mem_id']} in force")
    text, why = _checked(ctx, a["text"]), _checked(ctx, a["reason"])
    return _act(ctx, _decision("correct_memory", "memory", f"#{a['mem_id']}", text, why),
                lambda: mem.correct(ctx.con, int(a["mem_id"]), text, why, by=f"brain pass #{ctx.pass_id} ({ctx.model})",
                                    now=ctx.now))


def fetch_cited(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import fetch
    if a["url"].strip() not in fetch.cited_urls(ctx.con, ctx.now):
        raise ValueError("only a page the system already cites can be fetched")
    q = a["question"]
    return _act(ctx, _decision("investigate", "fetch", a["url"].strip()[:200], q, ""),
                lambda: fetch.run(ctx.con, a["url"], q, ctx.client, ctx.gate, ctx.now, ctx.mode,
                                  text_dir=ctx.rt.data_root / "kg" / "text")["text"], "fetch_cited")


WEB = {"max_uses": 2, "max_tokens": 6000, "effort": "medium"}      # the brain's searches: lighter than the AI centre's


def web_search(ctx: Ctx, a: dict) -> dict:
    """S62 (PLAN A21): a public question searched on the web by the slider's `brain_web` model (Sonnet: the first real
    lookup on Opus cost Rs 23.65, the results being input); priced first against the cap,
    at most DAILY a day; only cited figures kept; the analyst's gate refuses anything of the investor's."""
    from pflab.agents import analyst as an
    q, got = a["question"], {}

    def do():
        from pflab.hq import models
        cfg = {**an.config(), "model": models.model_id("brain_web", ctx.rt.settings)}
        o = an.web_search(ctx.con, q, ctx.client, now=ctx.now, cfg=cfg, topic="brain web", **WEB)
        if o.status != "done":
            raise ValueError(f"web search {o.status}: {o.text[:200]}")
        got["text"] = o.text
        return f"answered with cited pages (Rs {o.cost_inr:.2f})"
    out = _act(ctx, _decision("investigate", "web", "", q, _checked(ctx, a.get("why", ""))), do, "web_search")
    if got:
        out["result"] = got["text"][:4500]                      # the cited answer itself, for the brain to read
        out["recency"] = "web results older than 7 days, or with no date shown, are not a cause of today"
    return out


def themes_tool(ctx: Ctx, a: dict) -> dict:
    """Theme exposure with the applied limits, the dip reserve and the opportunity pot (all by code)."""
    from pflab.plan import pot
    from pflab.risk import themes
    ex = themes.exposure_of(ctx.con, ctx.rt.data_root, ctx.asof)
    lims = {t: themes.applied(ctx.con, "theme_limit", t) for t in ex}
    pend = ctx.con.execute("SELECT kind, key, value, status FROM limit_proposals WHERE status IN ('pending','applied') "
                           "ORDER BY prop_id DESC LIMIT 20").fetchall()
    ideas = ctx.con.execute("SELECT idea_id, symbol, reason, buy_below, exit_above, stop_below, amount, status FROM pot_ideas "
                            "ORDER BY idea_id DESC LIMIT 10").fetchall()
    return {"themes": {t: {"label": e["label"], "share_of_portfolio": round(e["weight"], 4), "limit": lims[t],
                           "holdings": e["holdings"][:8]} for t, e in ex.items()},
            "proposals": [{"kind": k, "key": key, "value": v, "status": s} for k, key, v, s in pend],
            "pot": {"limit_rs": pot.limit(ctx.con), "used_rs": pot.used(ctx.con), "room_rs": pot.room(ctx.con),
                    "ideas": [{"id": i, "symbol": sy, "reason": r, "buy_below": b, "exit_above": x, "stop_below": st,
                               "amount": am, "status": sts} for i, sy, r, b, x, st, am, sts in ideas]},
            "source": "risk/themes.py, plan/pot.py (limits apply only after the investor's yes; history is not a forecast)"}


def propose_pot_idea(ctx: Ctx, a: dict) -> dict:
    """A missed winner or an IPO for the opportunity pot: the reason in words, every price and the amount by code."""
    from pflab.agents import analyst as an
    from pflab.plan import pot
    sym = a["symbol"].strip().upper()
    isin = _isin(ctx, sym)
    reason, dropped = an.only_sourced_numbers(a["reason"], an.Request(ctx.source, "brain"))
    if dropped:
        ctx.problems.append(f"pot idea on {sym}: {dropped} sentence(s) dropped (numbers not read)")
    if ctx.shadow:
        return {"shadow": True, "note": "shadow pass: the idea is not kept"}
    iid = pot.add_idea(ctx.con, ctx.rt.data_root, isin, sym, reason.split("\n\n(")[0], ctx.asof, ctx.now)
    r = ctx.con.execute("SELECT buy_below, exit_above, stop_below, amount, horizon_days FROM pot_ideas WHERE idea_id=?", [iid]).fetchone()
    return {"kept": iid, "buy_below": r[0], "exit_above": r[1], "stop_below": r[2], "amount_rs": r[3], "scored_after_days": r[4],
            "note": "prices and amount by code; an idea for the investor, never an order"}


def record_hypothesis(ctx: Ctx, a: dict) -> dict:
    """The brain's "this seems the cause": kept with its evidence and a date to check by; the keeper tests it later."""
    from pflab.agents import analyst as an
    from pflab.kg import hypotheses as hy
    cause, d1 = an.only_sourced_numbers(a["cause"], an.Request(ctx.source, "brain"))
    effect, d2 = an.only_sourced_numbers(a["effect"], an.Request(ctx.source, "brain"))
    if d1 or d2:
        ctx.problems.append(f"hypothesis on {a['subject']}: {d1 + d2} sentence(s) dropped (numbers not read)")
    if ctx.shadow:
        return {"shadow": True, "note": "shadow pass: the hypothesis is not kept"}
    check_by = date.fromisoformat(a["check_by"])
    series = a.get("series")
    sep = "\n\n("
    hid = hy.record(ctx.con, ctx.pass_id, a["subject"], cause.split(sep)[0], effect.split(sep)[0],
                    list(a.get("evidence", [])), check_by, None if series in (None, "none") else series, ctx.now)
    return {"kept": hid, "checked": ("by code on " if series not in (None, "none") else "by you in a later pass on ") + str(check_by),
            "note": "confirmed or refuted later; a refuted one leaves the graph"}


def ipo_plan(ctx: Ctx, a: dict) -> dict:
    """An IPO allotment and the money around it: the facts and the choices with their numbers (plan/ipo.py)."""
    from pflab.plan import ipo
    r = ipo.strategy(ctx.con, ctx.rt.data_root, ctx.asof, a["name"], int(a["shares"]), float(a["issue_price"]), float(a["budget"]),
                     a.get("group"), ctx.rt.pm_dir)
    r["how_to_use"] = ("Then web_search the public facts listed in to_look_up_with_web_search (never put his shares, amounts or "
                       "holdings in the question; GMP is sentiment, name its date), connect them to the picture, and set out the "
                       "choices with numbers. Do not call it up or down: say what is known and what is not.")
    return r


def picture_tool(ctx: Ctx, a: dict) -> dict:
    """Everything side by side, built by code: the first call of every pass."""
    from pflab.hq import picture
    p = picture.cached(ctx.con, ctx.rt.data_root, ctx.asof, ctx.book(), ctx.rt.pm_dir)
    return {**p, "source": "hq/picture.py: stored and computed facts with their dates, side by side; nothing in it is a forecast"}


def system_status(ctx: Ctx, a: dict) -> dict:
    """The system's own state, built by code (app/system.py): the same picture the Command centre shows, whether this runs in the
    dashboard or in the background tick."""
    from pflab.app import system
    p = system.picture(ctx.rt, ctx.now)
    w = p["work"]
    return {"verdict": p["verdict"], "catching_up": p["catching_up"],
            "connectors": [{k: c[k] for k in ("name", "state", "line")} for c in p["connectors"]],
            "data_freshness": [{k: f[k] for k in ("name", "latest", "state", "line", "retained")} for f in p["freshness"]],
            "running_now": w["running"], "recently_done": [x["says"] + " (" + x["at"] + ")" for x in w["recent"][:6]],
            "failed_last_day": w["failed_24h"], "needs_from_him": [n["title"] for n in p["needs"]["items"]],
            "tasks": w["tasks"], "held_tasks": w["held"], "being_researched": [{k: c[k] for k in ("id", "question", "status", "waiting_for")} for c in w["investigating"]],
            "decided_lately": w["decided"], "recommendations": {k: p["recommendations"][k] for k in ("current", "why", "say")},
            "changed_since_his_last_visit": p["changed"], "tools": p["tools"],
            "source": "app/system.py: read from the store, the data folder and this machine; states: ok, warn (late or waiting on him), down, off; "
            "a recommendation prepared earlier is not current while `recommendations.current` is false"}


def scans_tool(ctx: Ctx, a: dict) -> dict:
    """The saved scans with their tested label and the hits of their last run."""
    from pflab.quant import scan
    p = ctx.rt.pm_dir / "app" / "cache" / "scans.json"
    try:
        res = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        res = {}
    out = []
    for s in scan.listing(ctx.con):
        r = (res.get("scans") or {}).get(str(s["scan_id"]))
        out.append({**s, "last_run": r["at"] if r else None,
                    "hits": [f"{h['symbol']}: {'; '.join(h['why'])}"[:200] for h in (r["hits"][:8] if r else [])]})
    return {"scans": out, "conditions": scan.__doc__.split("Conditions (name:value):")[1].strip(),
            "source": "quant/scan.py: conditions from a closed set, evaluated by code; information until the learner has tested one"}


def make_scan(ctx: Ctx, a: dict) -> dict:
    """The brain makes a scan: information only, labelled not tested; it can never turn one into a rule."""
    from pflab.quant import scan
    if ctx.shadow:
        return {"shadow": True, "note": "shadow pass: the scan is not kept"}
    sid = scan.make_scan(ctx.con, a["name"], a["conditions"], a.get("universe", "list"), f"brain:{ctx.model}", ctx.now)
    return {"kept": sid, "label": scan.LABEL_UNTESTED, "note": "runs each evening; hits on his names reach the evening summary"}


def scenario(ctx: Ctx, a: dict) -> dict:
    from pflab.risk import scenarios as sn
    name = a["name"]
    r = sn.run(ctx.con, ctx.rt.data_root, ctx.asof, name)
    for row in r.get("rows", []):
        row["beta"] = round(row["beta"], 2)
        row["impact"], row["plus_minus"], row["value"] = round(row["impact"]), round(row["plus_minus"]), round(row["value"])
        row.pop("beta_se", None)
    if "total" in r:
        r["total"], r["total_range"] = round(r["total"]), [round(x) for x in r["total_range"]]
        r["modelled_value"] = round(r["modelled_value"])
    r["source"] = "risk/scenarios.py (historical betas with standard errors; a description, not a forecast)"
    return r


def hypotheses(ctx: Ctx, a: dict) -> dict:
    from pflab.kg import hypotheses as hy
    return {"to_decide_now": hy.due_for_the_brain(ctx.con), "recent": hy.listing(ctx.con, a.get("status"), 15),
            "source": "kg_hypotheses (the keeper tests macro causes by code; others wait for a decision in a pass)"}


def decide_hypothesis(ctx: Ctx, a: dict) -> dict:
    """Decide a hypothesis the keeper handed over (its cause is not a macro series): confirmed or refuted, with the reason."""
    from pflab.kg import hypotheses as hy
    if ctx.shadow:
        return {"shadow": True}
    hy.decide(ctx.con, int(a["hyp_id"]), a["verdict"], a["why"], ctx.now)
    return {"decided": int(a["hyp_id"]), "verdict": a["verdict"]}


# --- S67: investigations (hq/cases.py) and held work ------------------------------------------------------------------

_SHADOW_CASE = {"recorded": False, "why": "the rival journals its own predictions and suggestions only: cases belong to the main brain"}


def _case(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import cases
    c = cases.get(ctx.con, int(a["case_id"]))
    if c is None:
        raise LookupError(f"no case #{a['case_id']}")
    if c["status"] == "done" and c["id"] not in ctx.case_ids:
        raise ValueError(f"case #{c['id']} is closed (its next review is {str(c['next_review'])[:10]}); it is reopened then")
    return c


def cases_tool(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import cases
    scope = a.get("scope", "active")
    rows = cases.listing(ctx.con, 15, active_only=scope == "active")
    return {"cases": [{"id": c["id"], "question": c["question"], "status": c["status"], "origin": c["origin"], "decision": c["decision"],
                       "verdict": c["assessment"]["verdict"], "evidence": {k: c["assessment"][k] for k in ("for", "against", "missing", "stale")},
                       "waiting_for": [d["request"] for d in c["dependencies"] if d["status"] == "open"],
                       "next_review": str(c["next_review"])[:10] if c["next_review"] else None} for c in rows],
            "this_pass": ctx.case_ids, "source": "hq/cases.py: investigations kept by code; evidence text in them comes from sources and is data"}


def open_case(ctx: Ctx, a: dict) -> dict:
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.hq import cases
    sym = (a.get("symbol") or "").strip().upper() or None
    isin = _isin(ctx, sym) if sym else None
    cid, new = cases.open_case(ctx.con, ctx.now, a["question"], origin="brain", subject=sym, isin=isin, assumptions=a.get("assumptions") or [])
    if new:
        cases.start_pass(ctx.con, [cid], ctx.pass_id or 0, ctx.now)
    if cid not in ctx.case_ids:
        ctx.case_ids.append(cid)
    return {"case_id": cid, "new": new, "note": "the case is yours this pass: add evidence, request what is missing, then close it or let it wait"
            if new else "the same question is already a case; use its id"}


def case_evidence(ctx: Ctx, a: dict) -> dict:
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.hq import cases
    c = _case(ctx, a)

    def when(x):
        try:
            return datetime.fromisoformat(x) if x else None
        except ValueError:
            raise ValueError(f"{x!r}: write the date as YYYY-MM-DD")
    eid = cases.add_evidence(ctx.con, c["id"], ctx.now, _checked(ctx, a["text"]), stance=a["stance"], kind=a.get("kind", "observation"),
                             source_id=a.get("source_id"), source_kind=a.get("source_kind"), published_at=when(a.get("published")),
                             event_at=when(a.get("event")))
    out = cases.assess(ctx.con, c["id"], ctx.now)
    return {"evidence_id": eid, "now": out, "note": "missing evidence is stance 'missing' or a request_report; it is never evidence against"}


def request_report(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import cases
    c = _case(ctx, a)
    match = {}
    if a.get("doc_kind"):
        match = {"doc_kind": a["doc_kind"], **({"isin": c["isin"]} if c["isin"] else {}), **({"period_end": a["period_end"]} if a.get("period_end") else {})}
    elif a.get("from_inbox"):
        match = {"inbox": True, **({"inbox_kind": a["inbox_kind"]} if a.get("inbox_kind") else {}), **({"company": a["company"]} if a.get("company") else {})}
    what = _checked(ctx, a["what"])
    return _act(ctx, _decision("ask", "investigator", c["subject"] or "", f"case #{c['id']}: {what}", "a named gap in an investigation"),
                lambda: (cases.request(ctx.con, c["id"], ctx.now, a["key"], what, match=match, kind="report" if match else "answer")[1]
                         and f"case #{c['id']} waits for: {what[:120]}") or f"case #{c['id']} already waits for {a['key']}", "request_report")


def case_calculate(ctx: Ctx, a: dict) -> dict:
    """A calculation for a case: reviewed measures first, else code written, run in the sandbox, written a second time and compared
    (agents/workshop.py). The script, datasets, parameters and result are kept (`hq_calcs`). With no sandbox the case waits for it."""
    from pflab.agents import sandbox as sb
    from pflab.agents import workshop as wk
    from pflab.hq import cases
    c = _case(ctx, a)
    got: dict = {}

    def do():
        try:
            out = wk.ask(ctx.con, a["question"], ctx.rt.pm_dir, ctx.rt.data_root, ctx.asof, secrets=ctx.rt.secrets, now=ctx.now)
        except sb.SandboxUnavailable as e:
            cases.request(ctx.con, c["id"], ctx.now, "sandbox", f"the sandbox (Docker) must run: {e}", match={"sandbox": True}, ask_investor=False)
            got["wait"] = str(e)
            return "waiting for the sandbox"
        kid = cases.record_calc(ctx.con, c["id"], ctx.now, a["question"], out)
        got["calc_id"], got["status"] = kid, out.status
        got["result"] = dict(list((out.run.result if out.run else {}).items())[:12])
        return f"calculation #{kid}: {out.status}"
    res = _act(ctx, _decision("investigate", "calc", c["subject"] or "", a["question"], f"case #{c['id']}"), do, "case_calculate")
    return {**res, **got}


def case_close(ctx: Ctx, a: dict) -> dict:
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.hq import cases
    c = _case(ctx, a)
    days = int(a.get("review_days", cases.REVIEW_DAYS))
    out = cases.conclude(ctx.con, c["id"], ctx.now, a["decision"], _checked(ctx, a["reason"]), uncertainty=_checked(ctx, a.get("uncertainty", "")),
                         next_review_at=ctx.now + timedelta(days=days))
    return {**out, "note": "kept with its evidence; it reopens by itself on the review day"}


# --- S67 local: the shared research workspace (chat and background use these same tools and tables) ----------------------------------

def frame_objective(ctx: Ctx, a: dict) -> dict:
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.hq import objectives
    try:
        frame = json.loads(a["frame_json"])
        if not isinstance(frame, dict):
            raise ValueError("not an object")
    except ValueError as e:
        return {"stored": False, "problem": f"frame_json is not a JSON object ({e})"}
    out = objectives.store(ctx.con, ctx.now, a["wish"].strip(), frame, int(a["case_id"]) if a.get("case_id") else None)
    return {**out, "note": "a draft is not tested or recommended against until the numbers are his; the protective limits are never changed here"}


def experiments_tool(ctx: Ctx, a: dict) -> dict:
    from pflab.learner import experiments as ex
    if a.get("experiment_id"):
        eid = int(a["experiment_id"])
        return {"experiment": next((e for e in ex.report(ctx.con) if e["id"] == eid), None),
                "attempts": [{k: v for k, v in x.items() if k != "code"} for x in ex.attempts(ctx.con, eid)]}
    return {"experiments": ex.report(ctx.con)[-12:], "tests_counted": __import__("pflab.learner.counter", fromlist=["x"]).n_tests(ctx.con),
            "note": "a rejection is a result; a kept candidate is shadow research only, never a rule"}


def register_experiment(ctx: Ctx, a: dict) -> dict:
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.learner import experiments as ex
    from pflab.learner.run import folders

    def do():
        eid = ex.register(ctx.con, folders(ctx.rt)[1], ctx.now, hypothesis=a["hypothesis"].strip(), why_it_matters=a["why_it_matters"].strip(),
                          disproof=a["disproof"].strip(), source_kind=a["source"], source_ref=str(a.get("case_id") or ""))
        return f"experiment #{eid} registered (the learner's next cycle runs it in the sandbox; the result is kept either way)"
    return _act(ctx, _decision("investigate", "learner", "", a["hypothesis"], "a registered, bounded experiment"), do, "register_experiment")


def propose_software_change(ctx: Ctx, a: dict) -> dict:
    """The system can say that a tool is missing or something is broken, with the evidence and, if it has one, a patch as TEXT. It never edits
    the application: a person takes the issue to the development workflow."""
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.pm.store import next_id
    iid = next_id(ctx.con, "hq_issues", "issue_id")
    ctx.con.execute("INSERT INTO hq_issues VALUES (?,?,?,?,?,?,?,?,?)",
                    [iid, ctx.now, a["kind"], _checked(ctx, a["title"])[:200], _checked(ctx, a["evidence"])[:1500], a.get("repro", "")[:1500] or None,
                     a.get("proposed_patch", "")[:6000] or None, "proposed", "brain"])
    return {"issue_id": iid, "applied": False, "note": "kept as a proposal for the development workflow; the running application is never edited by itself"}


def resolve_task(ctx: Ctx, a: dict) -> dict:
    """A task the hop limit held: run it once (the chain stays counted) or close it, with the reason kept."""
    from pflab.hq import board
    t = board.get(ctx.con, int(a["task_id"]))
    if t is None or t["status"] != "held":
        raise ValueError(f"task #{a['task_id']} is not held")
    why = _checked(ctx, a["reason"])
    by = f"brain pass #{ctx.pass_id}"
    fn = (lambda: board.release(ctx.con, t["id"], ctx.now, by)) if a["resolution"] == "release" else \
         (lambda: board.dismiss(ctx.con, t["id"], ctx.now, by, why))
    return _act(ctx, _decision("investigate" if a["resolution"] == "release" else "nothing", t["body"].get("meant_for") or "", f"task #{t['id']}",
                               t["text"][:200], f"{a['resolution']}: {why}"), lambda: str(fn()), "resolve_task")


SYMBOL = _s("NSE symbol of a held or listed stock", 20)
DAYS = _i("days back", 1, 365)
TOOLS: Dict[str, Tool] = {t.name: t for t in [
    Tool("portfolio", "read", "The portfolio today: buckets against targets and bands, holdings by weight and gain, "
         "direct stocks' and all holdings' unrealised gain, Kite against the statements.", {}, (), portfolio),
    Tool("stocks_overview", "read", "One row per held and listed stock: weight, its share, gap, gain, 3-month return, "
         "guard, zone, chance of touching 10% below within 63 sessions, edge after costs with n and t; and the market's "
         "tested states (the dip rule, the market state).", {}, (), stocks_overview),
    Tool("stock_facts", "read", "One stock in full: drift (weight against its share and the bucket's bands, trend), odds "
         "(10% moves over 21/63 sessions, touch chances of 5/10/20% falls, the buy zone), edge (excess over the Nifty "
         "500 after costs, n, t; a description, never a signal); also on request capm (beta, alpha with t, the CAPM "
         "expected return) and process (does its price revert to a mean or walk at random: ADF, variance ratios, "
         "half-life; descriptions, never signals); nudges (Kite-style pre-trade warnings: trade-to-trade, surveillance lists, insolvency, split or bonus coming, thin trading, suspension); business (12 quarters of revenue, profit and margins, holders and deals, peers ranked, concall and presentation filings); valuation (P/E now, against its own 5-year range and the "
         "market's, what growth the price assumes, volatility against its norm, and the usual rules of thumb as flags).",
         {"symbol": SYMBOL, "parts": {"type": "array", "items": {"type": "string", "enum": ["drift", "odds", "edge", "capm",
                                                                                          "process", "valuation", "business", "nudges"]},
                                      "description": "which parts (default drift, odds, edge, valuation)"}}, ("symbol",), stock_facts),
    Tool("tax_plan", "read", "Tax plan by code: per holding the FIFO ladder at today's price, long-term dates, what "
         "waiting saves, the 112A exemption left, loss sales.", {}, (), tax_plan),
    Tool("measure", "read", "A reviewed measure of a stock or index (NIFTY 50, NIFTY 500): drawdown, period_return, "
         "volatility, extreme_days, worst_run, var_cvar, chance_of_fall, relation (needs second).",
         {"measure": _s("which measure", enum=["drawdown", "period_return", "volatility", "extreme_days", "worst_run",
                                                "var_cvar", "chance_of_fall", "relation"]),
          "series": _s("a symbol, or NIFTY 50 / NIFTY 500", 30), "second": _s("second series for relation", 30),
          "start": _s("YYYY-MM-DD", 10), "end": _s("YYYY-MM-DD", 10), "fall_pct": _n("fall in percent", 0.5, 90),
          "sessions": _i("sessions", 1, 2520), "level": _n("confidence level", 0.5, 0.999)}, ("measure", "series"), measure),
    Tool("simulation", "read", "Monte Carlo (10,000 paths) of the current, target and your-stocks mixes: the chance of a "
         "35% fall, the one-year fan, the worst dated stress episodes.", {"years": _i("years", 1, 5)}, (), simulation),
    Tool("forecasts", "read", "The latest kept forecasts (turnover, results ranges) with the model serving each.",
         {"symbol": SYMBOL}, (), forecasts),
    Tool("readings", "read", "What the Haiku readers made of a stock's recent public documents (materiality, summary, "
         "checked figures).", {"symbol": SYMBOL, "days": DAYS}, ("symbol",), readings),
    Tool("graph_timeline", "read", "A stock's documents in the knowledge graph (filings, results, articles, notes) with "
         "their URLs.", {"symbol": SYMBOL, "days": DAYS}, ("symbol",), graph_timeline),
    Tool("notes", "read", "The analyst's newest cited note on a company.", {"symbol": SYMBOL}, ("symbol",), notes),
    Tool("memory_recall", "read", "Memory rows in force (decisions, reasons, outcomes, answers, notes) with their ids.",
         {"words": _s("words that must all appear", 200), "subject": _s("subject, e.g. a symbol", 40),
          "kind": _s("kind", enum=["decision", "reason", "outcome", "feedback", "answer", "note", "state"])}, (),
         memory_recall),
    Tool("journal", "read", "Your own recent passes, your prediction scorecard and your suggestions' record.", {}, (),
         journal),
    Tool("ready_plans", "read", "The ready plans kept current (next FD tranche, the monthly amount).", {}, (), ready_plans),
    Tool("research_flags", "read", "Research flags found by code (material filings, results, guards, news spikes, falls).",
         {"symbol": SYMBOL, "days": DAYS}, (), research_flags),
    Tool("price_history", "read", "A stock's trend and weekly closes.", {"symbol": SYMBOL, "days": _i("sessions back", 20, 750)},
         ("symbol",), price_history),
    Tool("quant", "read", "Tested quant templates (event studies, drift checks of adopted rules) for an idea.",
         {"idea": _s("the idea in words", 300)}, ("idea",), quant),
    Tool("record_prediction", "journal", "Keep a prediction: a stock's price change from the last close to the close on "
         "due (return_above / return_below a level in percent), due 5-90 days ahead, your confidence 0-1.",
         {"symbol": SYMBOL, "kind": _s("kind", enum=["return_above", "return_below"]), "level": _n("percent", -90, 500),
          "due": _s("YYYY-MM-DD", 10), "confidence": _n("probability", 0, 1), "claim": _s("the claim in words", 300)},
         ("symbol", "kind", "level", "due", "confidence", "claim"), record_prediction),
    Tool("record_suggestion", "journal", "Keep a suggestion for the investor in the suggestion ledger, scored at its "
         "horizon taken or not. Name the tools it rests on.",
         {"kind": _s("kind", enum=["add", "trim", "hold", "wait", "rebalance", "review", "other"]), "symbol": SYMBOL,
          "text": _s("the suggestion in one or two sentences", 600), "reasoning": _s("why, from the facts read", 1500),
          "horizon_days": _i("days until it is scored", 5, 180),
          "rested_on": {"type": "array", "items": {"type": "string", "enum": []}, "description": "tool names"}},
         ("kind", "text", "reasoning", "horizon_days", "rested_on"), record_suggestion),
    Tool("save_state", "journal", "Save your working state (what you found, what is left to do) to memory; the next "
         "context and the next pass start from it.", {"state": _s("the working state", 3000)}, ("state",), save_state),
    Tool("ask_investor", "action", "Ask the investor something only he can answer.",
         {"question": _s("the question", 400), "why": _s("why it matters", 400)}, ("question", "why"), ask_investor),
    Tool("tell_investor", "action", "Tell the investor something he should know today.",
         {"message": _s("the message", 600), "priority": _s("priority", enum=["low", "medium", "high"])},
         ("message", "priority"), tell_investor),
    Tool("order_research", "action", "Order the research analyst's cited note on a company (paid, priced first).",
         {"symbol": SYMBOL, "question": _s("the question", 400), "why": _s("why", 300)}, ("symbol", "question"),
         order_research),
    Tool("order_calculation", "action", "Order a calculation from the workshop (a reviewed measure or new code with a "
         "second writing).", {"question": _s("the question", 400), "why": _s("why", 300)}, ("question",),
         order_calculation),
    Tool("prepare_plan", "action", "Refresh the ready plans, or prepare one for an amount.",
         {"amount": _n("rupees", 1_000, 1e8), "why": _s("why", 300)}, ("why",), prepare_plan),
    Tool("correct_memory", "action", "Correct a memory row (the old row and your reason are kept).",
         {"mem_id": _i("the row's id", 1, 10 ** 9), "text": _s("the corrected text", 1500), "reason": _s("why", 400)},
         ("mem_id", "text", "reason"), correct_memory),
    Tool("fetch_cited", "action", "Read a page or filing the system already cites (its URL from notes or graph_timeline) "
         "and answer a question from it (paid).", {"url": _s("the cited URL", 600), "question": _s("the question", 400)},
         ("url", "question"), fetch_cited),
    Tool("who_is_buying", "read", "Who is buying or selling a stock: insider and SAST disclosures, bulk and block deals, "
         "promoters' holding and pledges, institutions (funds, FPIs) by quarter. Context, never a signal.",
         {"symbol": SYMBOL, "days": DAYS}, ("symbol",), who_is_buying),
    Tool("market_context", "read", "The market's backdrop: FII / FPI net equity flows (last day, 5 and 20 days), India "
         "VIX, Brent, the rupee, the US 10-year yield, the Nifty 500, each with its date and 30-day change.", {}, (),
         market_context),
    Tool("growth", "read", "Where the portfolio's change came from over a period: money put in, realised and unrealised "
         "gains, income, charges (the statements' ledger).", {"months": _i("months back", 1, 60)}, (), growth),
    Tool("findings", "read", "What the learner tested: claims from papers and blogs that passed a registered test on this "
         "system's data (for a stock signal, where each held and listed name sits today) and those that failed.", {}, (),
         findings),
    Tool("web_search", "action", "Search the web for a public fact the system's data lacks (news, a rule, an event); paid, "
         "a few a day. Never put the investor's holdings, amounts or anything personal in the question.",
         {"question": _s("the public question", 300), "why": _s("why it is needed", 300)}, ("question",), web_search),
    # S64: appended at the end, because the tool order fixes the prompt cache
    Tool("comovement", "read", "The peers a stock moves with (same industry, Nifty 500) from the weekly run: monthly "
         "correlation over 5 years, Engle-Granger cointegration (Benjamini-Hochberg adjusted), how often it held in "
         "rolling windows, the spread's half-life. A description: relations break (9% stayed cointegrated).",
         {"symbol": SYMBOL}, ("symbol",), comovement),
    Tool("ipo_plan", "read", "An IPO allotment and the money around it: what the shares are worth at any listing price, how large IPOs "
         "behaved (listing gain and the next 1-3 months), the overlap with the business group he already holds, tax on a sale, "
         "and what the standard plan does with the rest. Facts and choices, not a prediction.",
         {"name": _s("the company", 80), "shares": _i("shares allotted", 1, 1_000_000), "issue_price": _n("issue price in rupees", 1, 100_000),
          "budget": _n("rupees he wants to invest in all, allotment included", 1_000, 1e8), "group": _s("his business group name, e.g. reliance", 40)},
         ("name", "shares", "issue_price", "budget"), ipo_plan),
    Tool("picture", "read", "THE ONE PICTURE, built by code: the market's state and crash gauges, the news mood (and whether the news "
         "is current), the allocation against targets, every holding with its valuation, trend, news mood and warnings, the themes "
         "against their limits, cash and the dip reserve, what is on offer, what could hurt (scenarios), what changed, what waits "
         "for him, and what the system has learned. Call it FIRST in every pass; then dig into what it shows.", {}, (), picture_tool),
    Tool("scans", "read", "The saved scans (conditions from a closed set: moving averages, RSI, 52-week range, volume spike, P/E "
         "against its own median, alpha sign, futures build-up) with their last hits and whether the learner tested them.",
         {}, (), scans_tool),
    Tool("make_scan", "journal", "Make a scan from the closed set of conditions, as 'price_below_sma:200; volume_spike:2'. "
         "Information only, labelled not tested; hits on his names go into his evening summary.",
         {"name": _s("a short name", 80), "conditions": _s("conditions joined by ';'", 300),
          "universe": _s("universe", enum=["list", "holdings", "nifty500"])}, ("name", "conditions"), make_scan),
    Tool("scenario", "read", "A scenario chain on his holdings: oil_up_30 (Brent +30% in a month), rupee_down_10, us_crash "
         "(S&P 500 -20% in a month through the Nifty 500). Rupee impact per holding and in total with a +-2 standard-error range, "
         "from historical betas: a description, not a forecast.",
         {"name": _s("scenario", enum=["oil_up_30", "rupee_down_10", "us_crash"])}, ("name",), scenario),
    Tool("hypotheses", "read", "Your cause hypotheses: those the keeper handed over to decide now, and the recent ones with "
         "their status.", {"status": _s("status", enum=["open", "review", "confirmed", "refuted", "expired"])}, (), hypotheses),
    Tool("record_hypothesis", "journal", "Record 'this seems the cause' for a move: the subject (a symbol or a topic), the "
         "cause, the effect, the evidence (tool names read), a date to check by within 90 days, and a macro series if the cause "
         "is one (BRENT, USDINR, US_SP500), which the keeper then tests by code.",
         {"subject": _s("a symbol or topic", 60), "cause": _s("the suspected cause", 300), "effect": _s("what it did", 300),
          "evidence": {"type": "array", "items": {"type": "string"}, "description": "tool names or ids read"},
          "check_by": _s("YYYY-MM-DD, within 90 days", 10),
          "series": _s("macro series", enum=["BRENT", "USDINR", "US_SP500", "none"])},
         ("subject", "cause", "effect", "check_by"), record_hypothesis),
    Tool("decide_hypothesis", "journal", "Decide a hypothesis handed to you (hypotheses -> to_decide_now): confirmed or refuted "
         "from the evidence, with the reason.", {"hyp_id": _i("the id", 1, 10 ** 9), "verdict": _s("verdict", enum=["confirmed", "refuted"]),
                                                  "why": _s("the reason", 400)}, ("hyp_id", "verdict", "why"), decide_hypothesis),
    Tool("themes", "read", "Theme exposure (AI and IT, defence, EV and auto-tech) as a share of the portfolio with the limits he "
         "applied, pending proposals (limits, dip reserve, pot), and the opportunity pot with its ideas.", {}, (), themes_tool),
    Tool("propose_pot_idea", "journal", "Put a missed winner or a new listing into the opportunity pot: the reason in words; "
         "buy price, exit, stop and amount are computed by code. Needs the pot's limit applied by the investor.",
         {"symbol": SYMBOL, "reason": _s("why it belongs in the pot", 600)}, ("symbol", "reason"), propose_pot_idea),
    Tool("system_status", "read", "Whether the system itself is working and in sync: connectors (Kite, Telegram, the local model, the "
         "Claude API spend against his cap, the sandbox), how fresh each data source is, what is running, what failed, what needs him.",
         {}, (), system_status),
    Tool("cases", "read", "Your investigations: each open question with its evidence (for / against / missing / stale), what it waits for, its decision "
         "and next review. Look here first in a case pass.", {"scope": _s("which", enum=["active", "all"])}, (), cases_tool),
    Tool("open_case", "journal", "Open an investigation for an unresolved question or opportunity you found (the same question is one case). State the "
         "assumptions it rests on; a case is worked until you close it, it waits for a report, or it runs out of passes.",
         {"question": _s("the question to settle", 500), "symbol": SYMBOL, "assumptions": {"type": "array", "items": {"type": "string"},
          "description": "what the idea assumes, one short sentence each", "maxItems": 8}}, ("question",), open_case),
    Tool("case_evidence", "journal", "Add one piece of evidence to a case: what it says (copied from a tool result), whether it is for the idea, against "
         "it, neutral, or MISSING (looked for and not there: that is not evidence against), where it came from and when it was published.",
         {"case_id": _i("the case", 1, 10 ** 9), "stance": _s("stance", enum=["for", "against", "neutral", "missing"]),
          "text": _s("the evidence in a sentence or two", 700), "source_id": _s("the document or tool it came from", 120),
          "source_kind": _s("kind", enum=["filing", "result", "article", "web", "dataset", "email", "calculation", "observation"]),
          "published": _s("YYYY-MM-DD it was published", 10), "event": _s("YYYY-MM-DD the event happened", 10)},
         ("case_id", "stance", "text", "source_kind"), case_evidence),
    Tool("request_report", "action", "A case cannot go on without something you cannot get: name it. One request per key (asking twice changes nothing); the "
         "case waits and resumes by itself when it arrives. Say exactly what is needed (which report, which period).",
         {"case_id": _i("the case", 1, 10 ** 9), "key": _s("a short stable name for this request", 40), "what": _s("exactly what is needed", 400),
          "doc_kind": _s("if a public document of this kind about the company will do", enum=["filing", "result", "article", "dataset", "email"]),
          "period_end": _s("the date the period the report covers ends (YYYY-MM-DD): only a document published on or after it will do"),
          "inbox_kind": _s("the kind of file he must drop (for example result, cas, bank)"),
          "company": _s("a word that must appear in the file's name or text (the company)"),
          "from_inbox": {"type": "boolean", "description": "true if only a file he drops can supply it"}}, ("case_id", "key", "what"), request_report),
    Tool("case_calculate", "action", "A calculation for a case (reviewed measures first; else code is written, run in the sandbox, written a second time and "
         "compared). Script, data, parameters and result are kept. Needs the sandbox: with none the case waits for it.",
         {"case_id": _i("the case", 1, 10 ** 9), "question": _s("the calculation, defined exactly", 400)}, ("case_id", "question"), case_calculate),
    Tool("case_close", "journal", "Close a case with a decision (nothing, watch, suggest, ask, tell, inconclusive), the reason, what is still uncertain, and "
         "when to look again. Record any suggestion or message through its own tool.",
         {"case_id": _i("the case", 1, 10 ** 9), "decision": _s("decision", enum=["nothing", "watch", "suggest", "ask", "tell", "inconclusive"]),
          "reason": _s("why, from the evidence in the case", 600), "uncertainty": _s("what is still uncertain", 300),
          "review_days": _i("days until it is looked at again", 1, 90)}, ("case_id", "decision", "reason"), case_close),
    Tool("frame_objective", "journal", "Turn a wish (for example 'higher returns') into explicit objectives and the risk he would accept: a JSON frame with objectives "
         "[{measure, target, horizon_months, comparator}], acceptable_risk {max_fall_pct, cash_floor_months}, competing_explanations "
         "[{explanation, supported_by, refuted_by}] (at least two) and would_change_my_view [what evidence would change the recommendation]. A frame without numbers "
         "is kept as a draft and ONE grouped question goes to him; nothing is tested against a draft. A fall above his limit is a proposal; the limit stands.",
         {"wish": _s("his wish in his words", 300), "frame_json": _s("the frame as a JSON object", 3000), "case_id": _i("the case it belongs to, if any", 1, 10**9)},
         ("wish", "frame_json"), frame_objective),
    Tool("experiments", "read", "The bounded experiments: each registered question, its status, every attempt with the evaluator's measured result (not the candidate's claim), "
         "and how many variants have been searched in all (the bar rises with it).", {"experiment_id": _i("one experiment's attempts", 1, 10**9)}, (), experiments_tool),
    Tool("register_experiment", "action", "Register a hypothesis for a bounded experiment BEFORE any result is seen: what, why it matters, what would disprove it. The learner runs it "
         "in the sandbox against a registered comparator in fixed development and validation periods; most will fail, and that is kept. Two a day.",
         {"hypothesis": _s("the question as a testable rule", 400), "why_it_matters": _s("why it matters to him", 400), "disproof": _s("what result would disprove it", 400),
          "source": _s("where it came from", enum=["case", "claim", "data_issue", "process_failure", "investor"]), "case_id": _i("the case, if any", 1, 10**9)},
         ("hypothesis", "why_it_matters", "disproof", "source"), register_experiment),
    Tool("propose_software_change", "journal", "A tool is missing or something is broken: keep a reproducible issue (and a patch as text, if you have one) for the development "
         "workflow. You cannot change the application; this only records the proposal.",
         {"kind": _s("what it is", enum=["missing_tool", "bug", "data_connector", "improvement"]), "title": _s("short title", 200), "evidence": _s("what you saw", 1500),
          "repro": _s("steps to reproduce", 1500), "proposed_patch": _s("a patch or a sketch as text", 6000)}, ("kind", "title", "evidence"), propose_software_change),
    Tool("resolve_task", "action", "A task held at the agents' hop limit: release it (it runs once; what it hands on is held again) or dismiss it, with a reason.",
         {"task_id": _i("the held task", 1, 10 ** 9), "resolution": _s("what to do", enum=["release", "dismiss"]), "reason": _s("why", 300)},
         ("task_id", "resolution", "reason"), resolve_task),
    Tool("change_preference", "action", "ONLY when the investor himself asks to change a preference: put the exact change to him for his yes "
         "(targets as {bucket: weight} for every bucket that changes, the stock list add/remove a symbol, the monthly API cap in rupees). "
         "Never on your own judgement; nothing changes until he says yes.",
         {"kind": {"type": "string", "enum": ["targets", "stock_list", "api_cap"]}, "key": _s("targets: 'weights'; stock_list: add or remove; api_cap: monthly", 20),
          "value": _s("targets: JSON of the new weights; stock_list: the symbol; api_cap: rupees", 300),
          "why": _s("what he asked, in his words", 300)}, ("kind", "key", "value", "why"), change_preference),
]}
TOOLS["record_suggestion"].params["rested_on"]["items"]["enum"] = [n for n, t in TOOLS.items() if t.kind == "read"]


MAX_STRICT = 20


def definitions() -> List[dict]:
    """The API's tool list, in a fixed order (a changed order would break the prompt cache)."""
    out, strict = [], 0
    for t in TOOLS.values():
        on = bool(t.required) and strict < MAX_STRICT              # S64: tools after the 20th are checked by `validate` only
        strict += on
        out.append(t.definition(on))
    return out


def _plain(x):
    """JSON a model can read: NaN and infinities (pandas' missing values) become null."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    return x


def _log(ctx: Ctx, turn: int, tool: str, kind: str, args: Any, status: str, result: str, ms: int) -> None:
    from pflab.pm.store import next_id
    con = ctx.con
    n = next_id(con, "hq_tool_calls", "call_no")
    con.execute("INSERT INTO hq_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                [n, ctx.pass_id, ctx.now, turn, tool, kind, json.dumps(args, default=str)[:4000], status, result[:RESULT_CHARS + 200], ms])


def run(ctx: Ctx, name: str, args: Any, turn: int = 1) -> Tuple[str, bool]:
    """Run one tool call: (result text for the model, is_error)."""
    from pflab.hq import egress, redact
    tool = TOOLS.get(name)
    t0 = time.monotonic()
    if tool is None:
        _log(ctx, turn, name, "?", args, "refused", "unknown tool", 0)
        return f"unknown tool {name!r}", True
    bad = validate(tool, args)
    if bad:
        _log(ctx, turn, name, tool.kind, args, "refused", bad, 0)
        return f"input refused: {bad}", True
    try:
        res = tool.fn(ctx, args)
        status = ("shadow" if ctx.shadow else "held" if res.get("carried_out") is False else "ran") \
            if tool.kind == "action" else "ran"
        err = False
    except Exception as e:                                   # the model sees the failure and may try another way
        res, status, err = {"error": f"{type(e).__name__}: {str(e)[:400]}"}, "error", True
    text = json.dumps(_plain(res), default=str, ensure_ascii=False)
    if len(text) > RESULT_CHARS:
        text = text[:RESULT_CHARS] + f' ... (cut at {RESULT_CHARS} characters; ask for one stock or one part)'
    text, _ = redact.redact(text, ctx.gate, lines=False)
    try:
        egress.check(text, ctx.gate, skip=("address",))
    except egress.EgressBlocked as e:
        text, status, err = f"withheld: the result carried identity or banking details ({e})", "withheld", True
    ctx.results[name] = text
    ctx.source += "\n" + text
    _log(ctx, turn, name, tool.kind, args, status, text, int((time.monotonic() - t0) * 1000))
    return text, err
