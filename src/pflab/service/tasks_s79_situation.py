"""S79b item 16 job: `situation`, the shared picture of each market and the one report written from it (situation/build.py), mode-aware.

Due when its inputs are newer than its last run (service/ondemand.AFTER: prices, global, forecast_loop, catch_up) or a session closed without a report or a watch trigger
fired (redo_fn). Per market the clock's mode decides the work: pre_open and post_close write the full report (local THINKER), session mode a short one (flagged or after
intraday_minutes), deep mode refreshes the claims by code unless no full report exists for the date. It also scores the predictions that matured (code only), checks the
watch triggers (inside the run) and updates the chain-type hit rates in the knowledge graph. If the local model is down the report is written by code and flagged.
Agenda kinds registered here: `resolve_contradiction`, `watch_fired`, `situation_check` (their items are queued by situation/build.py and report.py).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from pflab.agenda import kinds
from pflab.service.jobs import Ctx, Interval, Job, register


def _rt(ctx: Ctx):
    from pflab.situation import adapters as AD
    return AD._ConRt(ctx.con, ctx.data_root, ctx.now)


def _enabled(ctx: Ctx):
    from pflab.situation import build
    return (build.enabled(), "switched off in configs/s79b.toml [situation]")


def _situation(ctx: Ctx) -> dict:
    from pflab import markets
    from pflab.situation import build, chains, score
    out, failed = {}, {}
    rt = _rt(ctx)
    for m in markets.codes():
        try:
            mode = markets.modes(ctx.now).get(m, "deep")
            r = build.run(rt, m, now=ctx.now, mode=mode)
            out[m] = {"as_of": r.get("as_of"), "plan": r.get("plan"), "coded_only": r.get("coded_only"), "claims": r.get("n_claims"), "flags": len(r.get("flags", [])),
                      "disagreements": len(r.get("contradictions", []))}
            try:
                sc = score.score(ctx.con, m, markets.get(m).session_closed_by(ctx.now), now=ctx.now, root=ctx.data_root)
                chains.update_kg_stats(ctx.con, m, ctx.now)
                out[m]["scored"] = sc["scored"]
            except Exception as e:
                out[m]["score_error"] = f"{type(e).__name__}: {str(e)[:100]}"
        except Exception as e:
            failed[m] = f"{type(e).__name__}: {str(e)[:160]}"
    if failed:
        out["failed"] = failed
    return out


def _redo(ctx: Ctx) -> Optional[str]:
    from pflab import markets
    from pflab.situation import build
    if not build.enabled():
        return None
    for m in markets.codes():
        try:
            why = build.due(ctx.con, m, ctx.now)
            if why:
                return why
        except Exception:
            continue
    return None


register(Job("situation", Interval(120, weekdays_only=False), _situation,
             "the shared situation per market: typed claims from the tools, one report (NOW, WHY, SO WHAT, NEXT, ACT), chains to the graph, predictions scored", cooldown_minutes=20,
             enabled_fn=_enabled, redo_fn=_redo))


# --- agenda kinds ----------------------------------------------------------------------------------------------------------------------------

def _none(con, market, now):
    return []                                        # items are queued by the situation run itself


def _work_watch_fired(rt, item: dict, now: datetime) -> dict:
    from pflab.situation import build
    r = build.run(rt, item["market"], now=now, flags=[item["subject"]], force="short")
    if r.get("off"):
        return {"skip": "the situation is switched off"}
    return {"useful": True, "effect": f"belief: the situation was re-read after {item['subject']} (report {r['report_id']}, {r['plan']})", "outcome": "re-synthesized"}


def _work_resolve(rt, item: dict, now: datetime) -> dict:
    """Ask the THINKER which watch level would settle the disagreement; the triggers pass the same code checks as the report's own."""
    from pflab.situation import claims as C, synth, watch as W
    p = item.get("payload") or {}
    con = rt.cursor()
    as_of = now.date()
    ids = [int(i) for i in p.get("claim_ids", [])]
    cl = C.active(con, item["market"], as_of)
    by_id = {c["claim_id"]: c for c in cl}
    side = [by_id[i] for i in ids if i in by_id]
    lv = [c for c in cl if c["subject"].startswith("level_")]
    if not side or not lv:
        return {"skip": "the claims of this disagreement are no longer live"}
    schema = {"type": "object", "properties": {"watch": synth.SCHEMA["properties"]["act"]["properties"]["watch"]}, "required": ["watch"]}
    system = ("Two sides of the evidence disagree. Propose at most two watch levels that would show which side is right: series from WATCHABLE, op > or <, claim = the id of that series' "
              "level claim, threshold = a level printed in that claim. Return JSON only.")
    user = "DISAGREEMENT:\n" + synth.claims_block(side) + "\n\nLEVELS:\n" + synth.claims_block(lv, 12) + "\n\nWATCHABLE: " + ", ".join(c["subject"][6:] for c in lv)
    try:
        d = json.loads(synth.local_chat(system, user, schema, 400))
    except Exception as e:
        return {"skip": f"the local model is not available ({type(e).__name__})"}
    n = 0
    for w in (d.get("watch") or [])[:2]:
        ok, _ = synth.watch_ok(w, by_id, [c["subject"][6:] for c in lv])
        if ok and W.add(con, item["market"], str(w.get("text", ""))[:200], w["series"], w["op"], float(w["threshold"]), as_of, now, claim_id=int(w["claim"])).get("stored"):
            n += 1
    return {"useful": n > 0, "effect": f"belief: {n} watch level(s) set that would settle the disagreement" if n else "", "outcome": f"{n} trigger(s) set"}


def _work_check(rt, item: dict, now: datetime) -> dict:
    """Re-read the source of a claim the report asked about and see whether its value moved."""
    from pflab.situation import adapters as AD, claims as C
    con = rt.cursor()
    as_of = now.date()
    cl = [c for c in C.active(con, item["market"], as_of) if item["subject"] in (c["subject"], c["kind"])]
    if not cl:
        return {"skip": "no live claim with that subject"}
    before = {c["subject"]: c.get("value") for c in cl}
    runner = AD.Runner(AD.as_rt(rt, now), item["market"], as_of, now)
    AD.run_all(runner, only=sorted({c["source"] for c in cl if c["source"]}))
    after = {c["subject"]: c.get("value") for c in C.active(con, item["market"], as_of) if c["subject"] in before}
    moved = [s for s in before if after.get(s) != before[s]]
    return {"useful": bool(moved), "effect": f"belief: {', '.join(moved[:3])} changed on re-reading" if moved else "", "outcome": "re-read"}


kinds.register("watch_fired", _none, _work_watch_fired, cost_seconds=60, doc="a situation watch trigger fired: the situation is re-read and re-synthesized (short)")
kinds.register("resolve_contradiction", _none, _work_resolve, cost_seconds=90, doc="two agents disagree: the THINKER names a watch level that would settle it (code checks it)")
kinds.register("situation_check", _none, _work_check, cost_seconds=45, doc="the report asked about a claim: its source is read again")
