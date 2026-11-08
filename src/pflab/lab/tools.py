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
        out.append(row)
    return {"rows": out, "baseline": None if base is None else service.card_row({**base, "run_id": base["run_id"]})}


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


@tool("write_note", "Write this session's note: what you tried, what won, what you learned. It is the next session's memory. Write it before you finish.", {"text": S("the note")}, ["text"])
def write_note(ctx, a):
    r = service.write_note(ctx.con, ctx.now, ctx.session_id, str(a.get("text", "")))
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


def make_ctx(con, pm_dir, root, now, session_id, data=None, box=None) -> SimpleNamespace:
    return SimpleNamespace(con=con, pm_dir=pm_dir, root=root, now=now, session_id=session_id, data=data, box=box, finished=None,
                           stats={"lab_runs": 0, "variants": 0, "challengers": 0, "notes": 0})


def run(ctx, name: str, args: dict) -> tuple:
    """-> (text, is_error). The registry's tool, its result as JSON text (cut to 9,000 characters: a result is small by design)."""
    if name not in REGISTRY:
        return json.dumps({"ok": False, "problem": f"no tool named {name}"}), True
    try:
        res = REGISTRY[name][1](ctx, args or {})
    except Exception as e:
        return json.dumps({"ok": False, "problem": f"{type(e).__name__}: {str(e)[:300]}"}), True
    text = json.dumps(res, default=str)
    return text[:9000], bool(isinstance(res, dict) and res.get("ok") is False)
