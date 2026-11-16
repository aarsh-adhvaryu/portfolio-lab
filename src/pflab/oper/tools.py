"""S87 O2: the operator's tools: the system's own functions as in-process tools (the chat's registry, run through `entrance.tools.run` so the allow-list, the redaction, the egress gate and the
journal still apply), plus the operator's own: pair study, the lab's scorecards, Problems, the decision log, usage, a request for a build. Each returns a short plain answer, never raw data.
There is NO order tool for his real account (Kite stays read-only); `web_search` and `fetch_cited` are not offered (the operator has no network except the NSE MCP)."""
from __future__ import annotations

import json
from typing import Callable, List, Optional

NOT_OFFERED = {"web_search", "fetch_cited"}
S = {"type": "string"}


def _short(x, n: int = 5000) -> str:
    t = x if isinstance(x, str) else json.dumps(x, default=str, ensure_ascii=False)
    return t if len(t) <= n else t[:n] + f" ... (cut at {n} characters)"


# --- the operator's own tools -----------------------------------------------------------------------------------------------------------

def pair_study(ctx, a: dict) -> str:
    """Correlation of returns (whole period, rolling range, and in the pair's worst days), lead-lag (-3..+3 days) and Engle-Granger cointegration (statsmodels) for two symbols."""
    import numpy as np
    import pandas as pd
    from pflab.hq import stocks
    from pflab.hq import tools as tl
    years = max(1, min(8, int(a.get("years") or 3)))
    cs = []
    for k in ("a", "b"):
        sym = str(a.get(k) or "").upper()
        c = stocks.closes(ctx.con, ctx.rt.data_root, tl._isin(ctx, sym), ctx.asof)
        cs.append(c.iloc[-252 * years:].rename(sym))
    df = pd.concat(cs, axis=1).dropna()
    if len(df) < 120:
        return f"too little shared history ({len(df)} days) for a pair study"
    na, nb = df.columns
    r = np.log(df).diff().dropna()
    corr = float(r[na].corr(r[nb]))
    roll = r[na].rolling(60).corr(r[nb]).dropna()
    both = r.mean(axis=1)
    fall = r[both <= both.quantile(0.10)]
    lead = {k: round(float(r[na].corr(r[nb].shift(-k))), 3) for k in range(-3, 4)}
    from statsmodels.tsa.stattools import coint
    p = float(coint(np.log(df[na]), np.log(df[nb]))[1])
    best = max(lead, key=lambda k: abs(lead[k]))
    out = {"pair": [na, nb], "days": int(len(r)), "years": years, "correlation_of_daily_returns": round(corr, 3),
           "rolling_60d_range": [round(float(roll.min()), 3), round(float(roll.max()), 3)], "correlation_in_worst_10pct_days": round(float(fall[na].corr(fall[nb])), 3), "n_fall_days": int(len(fall)),
           "lead_lag": {"corr_by_days": lead, "strongest_at": best, "reading": "same-day link only" if best == 0 else f"{na} moves {abs(best)} day(s) {'after' if best < 0 else 'before'} {nb}"},
           "cointegration": {"p_value": round(p, 3), "verdict": "cointegrated at 5%" if p < 0.05 else "not cointegrated at 5%"},
           "source": "prices (adjusted closes), statsmodels coint; a description of the past, not a forecast"}
    return _short(out)


def lab_policies(ctx, a: dict) -> str:
    """The lab's live policies and their latest history scorecards against the baseline, with the A50 rule (against the index, after tax)."""
    from pflab.lab import service, tools as lt
    c = type("C", (), {"con": ctx.con})()
    rows = lt.list_policies(c, {})
    ids = [p["policy_id"] for p in rows["policies"]][:6]
    cmp = lt.compare(c, {"policy_ids": ids}) if ids else {"rows": []}
    return _short({"policies": [{k: p.get(k) for k in ("policy_id", "status", "hypothesis", "latest")} for p in rows["policies"][:12]], "compare": cmp["rows"][:6], "trials_so_far": rows["trials_so_far"],
                   "note": "a pass on the spent 2022-2025 period is not evidence; a new rule is a registered study"})


def problems_list(ctx, a: dict) -> str:
    from pflab.service import problems
    rows = problems.listing(ctx.con)[:12]
    return _short([{"kind": r["kind"], "text": r["text"], "last": str(r["last_seen"])[:16], "times": r["times"]} for r in rows]) if rows else "Problems: none."


def usage_so_far(ctx, a: dict) -> str:
    from pflab.llm import claude_plan as cp
    return _short(cp.state(ctx.con, ctx.now))


def decision_log(ctx, a: dict) -> str:
    cur = ctx.con.execute("SELECT * FROM think_decisions_s84 ORDER BY decided_on DESC, decision_id DESC LIMIT ?", [max(1, min(30, int(a.get("n") or 12)))])
    cols = [d[0] for d in cur.description]
    return _short([{k: (str(v)[:160] if v is not None else None) for k, v in zip(cols, r) if k not in ("detail_json", "answer_json")} for r in cur.fetchall()])


def log_my_decision(ctx, a: dict) -> str:
    from pflab.oper import learn
    return learn.log_decision(ctx.con, ctx.now, str(a.get("symbol") or ""), str(a.get("action") or ""), str(a.get("note") or ""))


def my_decision_scores(ctx, a: dict) -> str:
    from pflab.oper import learn
    return _short(learn.summary(ctx.con))


def propose_action(ctx, a: dict) -> str:
    from pflab.oper import actions
    return actions.propose(ctx.con, ctx.now, str(a.get("kind") or ""), dict(a.get("payload") or {}))


def propose_plan(ctx, a: dict) -> str:
    from pflab.oper import plans
    return plans.propose(ctx.con, ctx.now, str(a.get("title") or ""), list(a.get("steps") or []), getattr(ctx, "chat_id", None), repeat=str(a.get("repeat") or ""))


def standing_orders(ctx, a: dict) -> str:
    from pflab.oper import standing
    return standing.text(ctx.con, ctx.now)


def request_build(ctx, a: dict) -> str:
    from pflab.oper import build
    return build.request(ctx.con, ctx.now, str(a.get("problem") or "").strip(), source="operator")


EXTRA = [
    ("pair_study", "Two symbols: correlation of daily returns (whole period, rolling range, worst 10% days), lead-lag, cointegration.",
     {"type": "object", "properties": {"a": S, "b": S, "years": {"type": "integer"}}, "required": ["a", "b"]}, pair_study),
    ("lab_policies", "The lab's policies and scorecards against the baseline index after tax (the registered tests; no new rule is made here).", {"type": "object", "properties": {}}, lab_policies),
    ("problems_list", "The Problems list: what failed lately, when, how often.", {"type": "object", "properties": {}}, problems_list),
    ("usage_so_far", "The operator's plan usage today by purpose (tokens against the day's budgets) and whether thinking is paused.", {"type": "object", "properties": {}}, usage_so_far),
    ("decision_log", "The thinking loop's recent decisions (what, when, on which case).", {"type": "object", "properties": {"n": {"type": "integer"}}}, decision_log),
    ("log_my_decision", "Log a decision HE made on his real holdings (buy / sell / hold / trim / add / skip, with the symbol and a short note) so it is scored against the index at 5, 20 and 60 sessions. "
     "Only when he says he did or decided it.", {"type": "object", "properties": {"symbol": S, "action": S, "note": S}, "required": ["symbol", "action"]}, log_my_decision),
    ("my_decision_scores", "How his logged decisions scored against the Nifty 500 (5/20/60 sessions), with the tax caveat on sales.", {"type": "object", "properties": {}}, my_decision_scores),
    ("propose_action", "Propose a CHANGE: kind is watch_add / watch_remove (payload symbol, market India|US, why, alerts), us_add / us_set / us_remove (ticker, shares, avg_price, bought_on), agent_set (agent, model, "
     "thinking), run_agent (agent: desk, weekly or case) or standing_set (order: cases, desk, weekly or autofix; on: true or false). It posts a Yes/No card; nothing changes before his Yes. Reading needs no card.",
     {"type": "object", "properties": {"kind": S, "payload": {"type": "object"}}, "required": ["kind", "payload"]}, propose_action),
    ("propose_plan", "A request with several steps ('plan how to test pairs trading', 'look into IT stocks and report'): post a PLAN CARD first (title, steps each with the tool or agent it uses and an estimate). "
     "Nothing runs until he taps Start. Use it instead of doing a long job unasked. When he wants it done regularly ('every day', 'each week', 'keep doing this') set repeat to daily or weekly: "
     "his one Yes then covers the later runs, and 'stop plan #N' ends it.",
     {"type": "object", "properties": {"title": S, "steps": {"type": "array", "items": {"type": "object", "properties": {"text": S, "uses": S, "est_tokens": {"type": "integer"}}, "required": ["text"]}},
                                       "repeat": {"type": "string", "enum": ["", "daily", "weekly"]}}, "required": ["title", "steps"]},
     propose_plan),
    ("standing_orders", "What the model may start BY ITSELF (think new cases through, the daily desk, the weekly look, fixing a repeated fault): on or off, what a run costs, tokens used in 7 days, cases waiting. "
     "To switch one, propose_action kind standing_set.", {"type": "object", "properties": {}}, standing_orders),
    ("request_build", "A bug or a 'build:' request: opens a build session on a branch in the workshop and sends him a Yes/No card. Never edit code yourself.",
     {"type": "object", "properties": {"problem": S}, "required": ["problem"]}, request_build),
]


# S88 L3: the full operator's DEFAULT set (what the questions of S88's measurement and the skills use); every other tool stays reachable by name through `more_tools` (its names are in its description)
DEFAULT = ("portfolio", "paper_book", "picture", "stock_facts", "price_history", "graph_timeline", "what_do_you_know", "thinking_cases", "decision_scorecard", "comovement", "pair_study", "scenario",
           "exposure_shock", "forecasts", "simulation", "lab_policies", "problems_list", "usage_so_far", "decision_log", "log_my_decision", "my_decision_scores", "request_build", "propose_action", "propose_plan", "read_file",
           "read_document", "files", "research_flags", "market_context", "ask_strategist", "look_into")


def items(ctx, kind: str = "all", core_only: bool = True) -> List[tuple]:
    """[(name, description, schema, fn(args)->str)] for the SDK server: the chat's tools bound to this chat's context, then the operator's own. With `core_only` (the default) only DEFAULT is offered
    by name (descriptions shortened to their first sentence) and `more_tools` reaches the rest."""
    from pflab.entrance import tools as ct
    full: List[tuple] = []
    seen = set()
    for d in ct.definitions(kind):
        n = d["name"]
        if n in NOT_OFFERED or n in seen:
            continue
        seen.add(n)

        def run(args, _n=n):
            text, err = ct.run(ctx, _n, args, 1)
            return ("error: " if err else "") + _short(text, 5000)
        full.append((n, d.get("description", ""), d.get("input_schema"), run))
    for n, desc, schema, fn in EXTRA:
        full.append((n, desc, schema, (lambda args, _f=fn: _short(_f(ctx, args, ), 5000))))
    if not core_only:
        return full
    by = {n: (n, d, sc, fn) for n, d, sc, fn in full}
    out = [(n, (by[n][1].split(". ")[0])[:200], by[n][2], by[n][3]) for n in DEFAULT if n in by]
    rest = sorted(n for n in by if n not in DEFAULT)

    def more(args):
        name = str(args.get("name") or "")
        if name == "?" or name not in by or name in DEFAULT:
            return "Other tools: " + ", ".join(rest) + ". Call more_tools with name and args (a JSON object); name='?' lists them; name='<tool>' with no args shows its description and inputs."
        if not args.get("args"):
            return json.dumps({"name": name, "description": by[name][1][:600], "input_schema": by[name][2]}, default=str)[:1500]
        a = args["args"]
        return by[name][3](json.loads(a) if isinstance(a, str) else dict(a))
    out.append(("more_tools", "Reach any other tool by name: " + ", ".join(rest)[:900], {"type": "object", "properties": {"name": {"type": "string"}, "args": {"type": "object"}}, "required": ["name"]}, more))
    return out
