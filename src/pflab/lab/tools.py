"""The strategist's tools (S80 phase 2): about a dozen, each described in a few lines (the doc: the strategist gets the lab's tools, not the 130 of v1). Every tool returns a small dict;
a lab run returns a scorecard row and its run id, a failed run the error and the last 30 lines, never raw output.

Phase 3 adds `storylines`, `open_storyline`, `adjust_storyline` and `issue_view` through the same registry (`REGISTRY`).
"""
from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from typing import Callable, Dict

from pflab.lab import policy_api, service, toolkit

REGISTRY: Dict[str, tuple] = {}                         # name -> (definition, function)


def tool(name: str, description: str, props: dict, required=()):
    def wrap(fn: Callable):
        REGISTRY[name] = ({"name": name, "description": description, "input_schema": {"type": "object", "properties": props, "required": list(required)}}, fn)
        return fn
    return wrap


S = lambda d: {"type": "string", "description": d}
I = lambda d: {"type": "integer", "description": d}
O = lambda d: {"type": "object", "description": d}


def definitions(extra=()) -> list:
    return [d for n, (d, _) in REGISTRY.items()] + list(extra)


def _toolkit_text() -> str:
    lines = []
    for n in toolkit.TOOLS:
        f = getattr(toolkit, n)
        doc = (inspect.getdoc(f) or "").splitlines()[0] if inspect.getdoc(f) else ""
        lines.append(f"{n}{inspect.signature(f)}: {doc}")
    return "\n".join(lines)


@tool("toolkit_help", "The functions your policy may import from `toolkit` (signatures and one line each), and the state layout decide() receives.", {})
def toolkit_help(ctx, a):
    return {"toolkit": _toolkit_text(), "interface": policy_api.__doc__, "allowed_imports": sorted(policy_api.ALLOWED_IMPORTS - {"__future__"})}


@tool("list_policies", "Every policy that is alive: id, status (draft, challenger, champion, reference), hypothesis, lineage, and its latest history score.", {})
def list_policies(ctx, a):
    rows = []
    for p in service.listing(ctx.con):
        r = service.latest_run(ctx.con, p["policy_id"], "history")
        p["latest"] = None if r is None else {"excess": round(r["score"]["excess_cagr"], 4), "dsr": round(r["score"].get("dsr", 0.0), 3), "worst_fall": round(r["score"]["max_drawdown"], 3)}
        rows.append(p)
    return {"policies": rows, "trials_so_far": service.n_trials(ctx.con)}


@tool("read_policy", "The source code of one policy (so you can edit it into a new variant).", {"policy_id": S("the policy id")}, ["policy_id"])
def read_policy(ctx, a):
    p = service.get(ctx.con, str(a.get("policy_id")))
    if not p or not p["code"]:
        return {"ok": False, "problem": "no such policy"}
    return {"ok": True, "policy_id": p["policy_id"], "status": p["status"], "hypothesis": p["hypothesis"], "params": p["params"], "code": p["code"][:12000]}


@tool("write_policy", "Store a new policy variant (status draft). One Python file defining decide(state, forecasts, sims, storylines, params=None) -> {key: weight}; it may declare "
      "PARAMS = {name: [values]} to stand for a grid (at most 24 combinations, about a minute each; every combination is a trial). An edit is a NEW id with `parent` set. Refused code comes back with the reason.",
      {"policy_id": S("lowercase id, e.g. mom_vol_filter_1"), "code": S("the full Python source"), "hypothesis": S("one line: what it leans on and why"), "parent": S("the id it edits, if any")},
      ["policy_id", "code", "hypothesis"])
def write_policy(ctx, a):
    r = service.add_variant(ctx.con, ctx.pm_dir, ctx.now, str(a.get("policy_id", "")), str(a.get("code", "")), str(a.get("hypothesis", "")), a.get("parent") or None, ctx.session_id)
    if r.get("ok"):
        ctx.stats["variants"] += 1
    return r


@tool("run_lab", "Replay every combination of a policy in the sandbox over 2005-2017 after tax and charges, with shuffled-signal runs, a Monte Carlo and the deflated Sharpe. Returns a scorecard "
      "row per combination plus the plain baseline's row. Every combination counts as a trial. Slow: about a minute per combination.",
      {"policy_id": S("a draft or challenger policy"), "n_shuffles": I("shuffled-signal runs per combination (default 10, 5 to 20)")}, ["policy_id"])
def run_lab(ctx, a):
    n = max(5, min(20, int(a.get("n_shuffles") or 10)))
    r = service.run_lab(ctx.con, ctx.pm_dir, ctx.root, ctx.now, str(a.get("policy_id", "")), n_shuffles=n, session_id=ctx.session_id, data=ctx.data, box=ctx.box)
    if r.get("ok"):
        ctx.stats["lab_runs"] += 1
    return r


@tool("compare", "Side by side: the latest history scorecard of the named policies and the baseline, and whether each clears the registered screen.", {"policy_ids": {"type": "array", "items": {"type": "string"}}},
      ["policy_ids"])
def compare(ctx, a):
    base = service.latest_run(ctx.con, service.BASELINE_ID, "history")
    out = []
    for pid in (a.get("policy_ids") or [])[:6]:
        r = service.latest_run(ctx.con, str(pid), "history")
        if r is None:
            out.append({"policy_id": pid, "problem": "no history run"})
            continue
        row = service.card_row(r)
        row["policy_id"] = pid
        row["screen"] = service.screen(r["score"], r["shuffled"], base["score"]) if base else {"ok": False, "failed": ["no baseline run yet"]}
        row["index_rule"] = service.index_rule(r["score"])             # A50: the two-dimension rule against the index, after tax and charges on both sides
        out.append(row)
    return {"rows": out, "baseline": None if base is None else service.card_row({**base, "run_id": base["run_id"]})}


@tool("propose_allocation", "Propose the system's ALLOCATION (yours; re-examine it weekly): classes (percent: equity, gold, international, cash; sum 100), sleeves (core, longterm; sum 100; "
      "longterm <= 60, core >= 30; gold, international, cash sit inside the core), sectors (each <= 25) and reasons. Code checks the rails and caps, stores it as lab policy "
      "`alloc_t<id>` (run_lab it) and adopts it by the index rule and the final check. The same split again records that it stands.",
      {"classes": O("{equity, gold, international, cash} in percent"), "sleeves": O("{core, longterm} in percent"), "sectors": O("{sector: percent of the book}, may be empty"),
       "reasons": S("what the book should hold and why, and what would change it (40+ characters)")}, ["classes", "sleeves", "reasons"])
def propose_allocation(ctx, a):
    from pflab.lab import alloc_lab
    sleeves, told = _keep_longterm_share(ctx.con, a.get("sleeves") or {})
    r = alloc_lab.propose(ctx.con, ctx.pm_dir, ctx.now, a.get("classes") or {}, sleeves, str(a.get("reasons", "")), sectors=a.get("sectors") or {})
    if r.get("ok"):
        ctx.stats["variants"] += 1 if r.get("variant") else 0
        if told:
            r["longterm_share"] = told
    return r


LONGTERM_TOLD = "the longterm share is set by the picks rule (S83 L5), not by a proposal"


def _keep_longterm_share(con, sleeves: dict) -> tuple:
    """S83 L6: the longterm share belongs to the picks rule (`pick_share.share(con, "IN")`). A proposal that tries to change it is accepted for its other fields and keeps the current share;
    -> (the sleeves to check, a plain sentence or None)."""
    try:
        from pflab.core import pick_share
        if not pick_share.on("IN"):
            return sleeves, None
        live = round(float(pick_share.share(con, "IN")["share"]) * 100.0, 4)
        asked = float(sleeves.get("longterm"))
    except Exception:
        return sleeves, None
    if abs(asked - live) <= 0.05:
        return sleeves, None
    return {**{k: v for k, v in sleeves.items() if k not in ("core", "longterm")}, "core": round(100.0 - live, 4), "longterm": live}, (
        f"{LONGTERM_TOLD}: you asked for {asked:g}% and it stays at {live:g}% (core {100.0 - live:g}%); the rest of the proposal was taken")


@tool("make_challenger", "Put a variant with a scored history run into live shadow as a challenger (at most 5 at once). If it has a grid, name the params you mean.",
      {"policy_id": S("the policy"), "params": O("the grid combination to fix, e.g. {\"n\": 10}; omit if it has no grid"), "why": S("one line")}, ["policy_id"])
def make_challenger(ctx, a):
    r = service.make_challenger(ctx.con, ctx.now, str(a.get("policy_id", "")), a.get("params"), str(a.get("why", "")))
    if r.get("ok"):
        ctx.stats["challengers"] += 1
    return r


@tool("retire", "Drop a draft or challenger you no longer want.", {"policy_id": S("the policy"), "why": S("one line")}, ["policy_id", "why"])
def retire(ctx, a):
    return service.retire(ctx.con, ctx.now, str(a.get("policy_id", "")), str(a.get("why", "")))


@tool("screen_rules", "The registered screen a variant must clear to be promoted, the shadow length and what happens after (the final check is run by code, once; you never see it).", {})
def screen_rules(ctx, a):
    return service.screen_rules()


@tool("read_notes", "Your own notes from earlier sessions (what was tried, what won, what was learned).", {"limit": I("how many, newest first (default 5)")})
def read_notes(ctx, a):
    return {"notes": service.notes(ctx.con, int(a.get("limit") or 5))}


def _learned_needed(con) -> list:
    """The markets whose picks sleeve is on and has five scored picks: the note must then say what the scorecard taught (S83 L3)."""
    from pflab.core import picks
    out = []
    for m in ("IN", "US"):
        try:
            if picks.on(m) and picks.needs_learned(con, m):
                out.append(m)
        except Exception:
            pass
    return out


@tool("write_note", "Write this session's note: what you tried, what won, what you learned. It is the next session's memory. Write it before you finish. `learned` (40+ characters: what the picks scorecard "
      "taught you and what you do differently) is REQUIRED once five picks of a market have a score.", {"text": S("the note"), "learned": S("what the picks scorecard taught you (required once five picks have a score)")}, ["text"])
def write_note(ctx, a):
    learned = " ".join(str(a.get("learned") or "").split())
    need = _learned_needed(ctx.con)
    if need and len(learned) < 40:
        return {"ok": False, "problem": f"five picks have a score ({', '.join(need)}): add `learned`, 40+ characters, what the scorecard taught you and what you do differently, then write the note again"}
    r = service.write_note(ctx.con, ctx.now, ctx.session_id, str(a.get("text", "")), learned=learned or None)
    if r.get("ok"):
        ctx.stats["notes"] += 1
    return r


@tool("finish", "End the session with a one-paragraph summary. Call it once you have run what you wanted and written your note.", {"summary": S("what the session did")}, ["summary"])
def finish(ctx, a):
    ctx.finished = str(a.get("summary", ""))[:1500]
    return {"ok": True}


# --- phase 3: storylines and the tactical lane ----------------------------------------------------------------------------------------

@tool("storylines", "The open storylines (claim, direction, probability, influence, signals, latest evidence, predictions scored so far); give storyline_id for one in full with its evidence.",
      {"storyline_id": I("one storyline in full")})
def storylines(ctx, a):
    from pflab.story import numbers, predict, prob, store
    if a.get("storyline_id"):
        s = store.get(ctx.con, int(a["storyline_id"]))
        if not s:
            return {"ok": False, "problem": "no such storyline"}
        return {"storyline": {k: (str(v) if k in ("opened_on", "status_on") else v) for k, v in s.items()}, "evidence": store.evidence(ctx.con, s["storyline_id"], 10),
                "predictions": predict.record(ctx.con, s["storyline_id"])["predictions"], "probability_path": prob.history(ctx.con, s["storyline_id"])[-15:]}
    return {"summary": numbers.summary_text(ctx.con, ctx.now.date()), "signal_menu": sorted(store.TEMPLATES), "record": store.record_text(ctx.con)}


@tool("open_storyline", "Open a storyline: a claim (one sentence: the cause and what it should do to the Nifty), a direction (1 up, -1 down) and 1 to 3 signals from the signal menu. Code computes its "
      "probability from the signals and the evidence each close and scores its predictions at 5 and 20 sessions.",
      {"claim": S("one sentence"), "direction": I("1 or -1"), "templates": {"type": "array", "items": {"type": "string"}, "description": "signal names from the menu"}}, ["claim", "direction", "templates"])
def open_storyline(ctx, a):
    from pflab.story import predict, store
    r = store.open_storyline(ctx.con, ctx.now, str(a.get("claim", "")), int(a.get("direction") or 0), ctx.now.date(), list(a.get("templates") or []), kind="market", created_by="strategist")
    if r.get("ok"):
        predict.register(ctx.con, ctx.now, r["storyline_id"], ctx.now.date(), ctx.root)
    return r


@tool("adjust_storyline", "Move a storyline's probability with a written reason: delta in log-odds, at most 0.6 either way (about 15 points); the signals and evidence still count.",
      {"storyline_id": I("the storyline"), "delta": {"type": "number", "description": "log-odds, -0.6 to 0.6"}, "reason": S("what the signals miss (20+ characters)")}, ["storyline_id", "delta", "reason"])
def adjust_storyline(ctx, a):
    from pflab.story import prob
    return prob.adjust(ctx.con, ctx.now, int(a.get("storyline_id") or 0), float(a.get("delta") or 0.0), str(a.get("reason", "")))


@tool("issue_view", "A same-day tactical view: direction (1 buy, -1 reduce what is held), 1 to 6 symbols, a size as a share of the TACTICAL BUDGET (0 to 1), a horizon in sessions (3 to 60), a stop "
      "(percent fall that ends it) and the storyline it rests on. Code checks the rails, sizes it and executes it at the next close; it is scored at its horizon against the Nifty 500.",
      {"direction": I("1 or -1"), "symbols": {"type": "array", "items": {"type": "string"}}, "share_of_budget": {"type": "number", "description": "0 to 1 of the tactical budget"},
       "horizon_sessions": I("3 to 60"), "stop_pct": {"type": "number", "description": "1 to 30"}, "storyline_id": I("the storyline it rests on"), "reason": S("why, and what it rests on")},
      ["direction", "symbols", "share_of_budget", "horizon_sessions", "reason"])
def issue_view(ctx, a):
    from pflab.core import views
    return views.issue(ctx.con, ctx.now, ctx.now.date(), direction=int(a.get("direction") or 0), names=list(a.get("symbols") or []), share_of_budget=float(a.get("share_of_budget") or 0),
                       horizon_sessions=int(a.get("horizon_sessions") or 0), stop_pct=float(a.get("stop_pct") or 8.0), storyline_id=a.get("storyline_id"), reason=str(a.get("reason", "")),
                       session_id=ctx.session_id)


# --- S83 L2: what the strategist may look at to choose (lab/screen.py; every number is code, public data, point in time) ----------------------------------------------------

LIMITS = {"screen_stocks": 30000, "company_card": 16000}        # a result is cut at 9,000 characters unless named here (a 40-row screen is longer)


@tool("screen_stocks", "Up to 40 stocks for the picks sleeve (IN: liquid shares, floor Rs 5 crore a day; US: the A62 floor, bars fetched on demand). Every number is code, point in time: returns, 200-day average, volatility, "
      "traded value, size, sector, indices, shareholding, deals, events, red flags, price range, storylines, P/E. Figures describe the past; only 'below its 200-day average earns less' passed a test; deals are context; "
      "US history is survivorship-biased.",
      {"market": S("IN or US"), "filters": O("optional: min_traded_value_inr, min_momentum (126-session return as a fraction), max_volatility (fraction), sector, in_index (NIFTY500, NIFTY200, NIFTY100, NIFTY_MIDCAP100), "
                                             "exclude_held, exclude_flagged, symbols (list), include_suspect_prices; US: grow_universe, fetch_cap"),
       "sort": S("momentum_63, momentum_126 (default), momentum_252, low_volatility, traded_value, market_cap, promoter_change, near_52w_high"), "n": I("rows, at most 40")}, ["market"])
def screen_stocks(ctx, a):
    from pflab.lab import screen
    return screen.screen_stocks(ctx.con, ctx.now, str(a.get("market") or "IN"), a.get("filters") or None, str(a.get("sort") or "momentum_126"), int(a.get("n") or 40), root=ctx.root, detail="brief")


@tool("company_card", "One page for one name: price, 52-week range, liquidity, size, shareholding, deals (context only), results and graph events, red flags, price range, storylines, filed fundamentals (IN) or SEC facts and "
      "filings (US), the A62 floor, and what the rails allow. Every number is code; the same labels as screen_stocks.",
      {"market": S("IN or US"), "symbol": S("the stock's symbol")}, ["market", "symbol"])
def company_card(ctx, a):
    from pflab.lab import screen
    return screen.fit_card(screen.company_card(ctx.con, ctx.now, str(a.get("market") or "IN"), str(a.get("symbol") or ""), root=ctx.root), LIMITS["company_card"] - 500)


# --- S83 L3: the picks sleeve (core/picks.py): the strategist names stocks and writes reasons; code makes every number (A63) ---------------------------------------------------

ITEM = {"type": "object", "properties": {"symbol": {"type": "string"}, "thesis": {"type": "string", "description": "why, 60+ characters"}, "break_condition": {"type": "string", "description": "what would break it"},
                                         "storylines": {"type": "array", "items": {"type": "integer"}, "description": "storyline ids it rests on, may be empty"},
                                         "takes_from": {"type": "string", "description": "20+ characters: what this pick takes from the earlier note or case on the name; required when the company card's 'what we already know' lists one"}},
                                         "required": ["symbol", "thesis", "break_condition"]}


def _session_ref(ctx) -> str:
    return f"strategist session {ctx.session_id}"


@tool("propose_picks", "Name stocks for the picks sleeve of ONE market (IN or US), each with a thesis (60+ characters), what would break it and the storylines it rests on. You never give a size, a price or a weight: code "
      "checks the rails and floors, sizes by risk inside the sleeve's share and buys slowly. Once five picks have a score, `learned_from` (40+ characters: what the scorecard taught you) is required. Refusals come back with the reason.",
      {"market": S("IN or US"), "items": {"type": "array", "items": ITEM, "description": "the stocks"}, "learned_from": S("what the scorecard taught you; required once five picks have a score")}, ["market", "items"])
def propose_picks(ctx, a):
    from pflab.core import picks
    market = str(a.get("market") or "").upper()
    if market not in ("IN", "US"):
        return {"ok": False, "problem": "market must be IN or US"}
    items = [i for i in (a.get("items") or []) if isinstance(i, dict)]
    if not items:
        return {"ok": False, "problem": "name at least one stock: items is a list of {symbol, thesis, break_condition, storylines}"}
    learned = " ".join(str(a.get("learned_from") or "").split())
    if picks.on(market) and picks.needs_learned(ctx.con, market) and len(learned) < picks.MIN_LEARNED:
        return {"ok": False, "problem": f"five picks in {market} have a score now: give `learned_from`, {picks.MIN_LEARNED}+ characters, what the scorecard taught you and what you do differently, then name them again"}
    r = picks.propose(ctx.con, ctx.now, market, items[:12], session_ref=_session_ref(ctx), learned_from=learned or None)
    ctx.stats["picks"] = ctx.stats.get("picks", 0) + len(r["accepted"])
    out = {"ok": bool(r["accepted"]), "market": market, "accepted": r["accepted"], "refused": r["refused"],
           "says": "accepted names are bought slowly by code inside the sleeve's share and the turnover caps; you wrote no size"}
    if not r["accepted"]:
        out["problem"] = "; ".join(f"{x['symbol']}: {x['reason']}" for x in r["refused"])[:900] or "nothing was accepted"
    return out


@tool("withdraw_pick", "You no longer believe a pick's thesis: withdraw it (a reason of 20+ characters). A pick not bought yet is dropped; a held one is sold by code at a close as a 'withdraw' sale, unless the "
      "12-month tax guard makes it wait (a stop or thesis break would not wait), and the sale is scored after tax against holding.",
      {"market": S("IN or US"), "symbol": S("the pick's symbol"), "reason": S("why you no longer believe it")}, ["market", "symbol", "reason"])
def withdraw_pick(ctx, a):
    from pflab.core import picks
    market = str(a.get("market") or "").upper()
    if market not in ("IN", "US"):
        return {"ok": False, "problem": "market must be IN or US"}
    r = picks.withdraw(ctx.con, ctx.now, market, str(a.get("symbol") or ""), str(a.get("reason") or ""), session_ref=_session_ref(ctx))
    if r.get("ok"):
        ctx.stats["picks"] = ctx.stats.get("picks", 0) + 1
    return r


@tool("skip_idea", "Record a stock you looked at and decided NOT to pick, with why (20+ characters). It is never bought: only its price is followed so the scorecard can show whether skipping was right.",
      {"market": S("IN or US"), "symbol": S("the stock's symbol"), "why": S("why you skipped it")}, ["market", "symbol", "why"])
def skip_idea(ctx, a):
    from pflab.core import picks
    market = str(a.get("market") or "").upper()
    if market not in ("IN", "US"):
        return {"ok": False, "problem": "market must be IN or US"}
    r = picks.skip_idea(ctx.con, ctx.now, market, str(a.get("symbol") or ""), str(a.get("why") or ""), session_ref=_session_ref(ctx))
    if r.get("ok"):
        ctx.stats["skips"] = ctx.stats.get("skips", 0) + 1
    return r


def make_ctx(con, pm_dir, root, now, session_id, data=None, box=None) -> SimpleNamespace:
    return SimpleNamespace(con=con, pm_dir=pm_dir, root=root, now=now, session_id=session_id, data=data, box=box, finished=None,
                           stats={"lab_runs": 0, "variants": 0, "challengers": 0, "notes": 0, "picks": 0, "skips": 0})


def run(ctx, name: str, args: dict) -> tuple:
    """-> (text, is_error). The registry's tool, its result as JSON text (cut to 9,000 characters: a result is small by design)."""
    if name not in REGISTRY:
        return json.dumps({"ok": False, "problem": f"no tool named {name}"}), True
    try:
        res = REGISTRY[name][1](ctx, args or {})
    except Exception as e:
        return json.dumps({"ok": False, "problem": f"{type(e).__name__}: {str(e)[:300]}"}), True
    text = json.dumps(res, default=str)
    return text[:LIMITS.get(name, 9000)], bool(isinstance(res, dict) and res.get("ok") is False)
