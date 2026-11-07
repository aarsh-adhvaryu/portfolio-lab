"""S79b item 16 tool: `situation`, the shared picture of a market (typed claims) and the one report written from it. Read only; works with {}; returns {"off": true} when
`configs/s79b.toml [situation] on = false`.

Result keys: call_ref, market, available, as_of, mode, author ("code" when no model text), coded_only, created_at, flags, sections {now[{text,claims}], why[{cause,effect,
mechanism,cause_date,effect_date,type}], so_what, next[{key,text,probs{horizon:p},claims,note}], act{paper_request,agenda,question,watch}, disagreements[{subject,explanations[
{side,claim_ids,probability}]}]}, text (the rendered report), claims [{claim_id,kind,subject,text,value,as_of,call_ids}] (when claims=true), watch (active triggers),
calibration {n, brier ... (n only under 20 outcomes)}, chain_types {type: {n, hits, hit_rate}}. The report is built by the `situation` job, never by this tool. Cite the call_ref."""
from __future__ import annotations

from datetime import date

from pflab.hq.tools import Ctx, Tool, _s


def situation(ctx: Ctx, a: dict) -> dict:
    try:
        from pflab.situation import build, chains, claims as C, report, score, watch
        if not build.enabled():
            return {"off": True, "call_ref": ctx.call_ref}
        con = ctx.con
        market = str(a.get("market") or "IN").upper()
        market = market if market in ("IN", "US") else "IN"
        d = date.fromisoformat(str(a["date"])[:10]) if a.get("date") else None
        rep = report.latest(con, market, d)
        out = {"call_ref": ctx.call_ref, "market": market, "available": rep is not None}
        if rep is None:
            out["note"] = "no situation report has been written yet; the job `situation` writes one when its inputs are newer"
        else:
            part = str(a.get("part") or "all")
            secs = rep["sections"]
            out.update(as_of=rep["as_of"], mode=rep["mode"], author=rep["author"], coded_only=rep["coded_only"], created_at=rep["created_at"], flags=rep["flags"],
                       sections=secs if part == "all" else {part: secs.get(part)})
            out["text"] = rep["text"]
        if a.get("claims"):
            cl = C.active(con, market, d or ctx.asof, [a["kind"]] if a.get("kind") else None)
            out["claims"] = [{"claim_id": c["claim_id"], "kind": c["kind"], "subject": c["subject"], "text": c["text"], "value": c["value"], "as_of": str(c["as_of"]),
                              "call_ids": c["call_ids"]} for c in cl[:60]]
        out["watch"] = [{"watch_id": w["watch_id"], "text": w["text"], "series": w["series"], "op": w["op"], "threshold": w["threshold"], "status": w["status"]}
                        for w in watch.active(con, market)[:12]]
        out["calibration"] = score.calibration(con, market)
        out["chain_types"] = chains.type_stats(con, market)
        out["source"] = "situation/ (claims from the tools by adapters; synthesis by the local THINKER, every figure checked by code; predictions scored at their horizons)"
        return out
    except Exception as e:
        return {"call_ref": ctx.call_ref, "available": False, "error": repr(e)[:200], "note": "the situation could not be read"}


TOOLS = [
    Tool("situation", "read",
         "The shared situation of a market: the latest report with sections NOW (what happened), WHY (causal links, each cause dated before its effect), SO WHAT (for the paper book), "
         "NEXT (scenarios with probabilities that come from the tools, scored at their horizons), ACT (requests, agenda items, watch triggers), plus the DISAGREEMENTS between agents "
         "(kept, each on the agenda), the active watch triggers, the synthesizer's calibration (count only under 20 outcomes) and the hit rate per chain type. Result keys: call_ref, "
         "market, available, as_of, mode, author, coded_only, flags, sections, text, claims (with claims=true), watch, calibration, chain_types. Quote figures exactly and cite the call_ref.",
         {"market": _s("IN or US (default IN)", 4, enum=("IN", "US")), "date": _s("the report on or before this date, YYYY-MM-DD (default the latest)", 10),
          "part": _s("one section only: now, why, so_what, next, act or disagreements (default all)", 14), "claims": {"type": "boolean", "description": "also list the live typed claims"},
          "kind": _s("with claims: only this kind (regime, wave, rotation, macro, sentiment, exposure, forecast, fall_risk, implied, transmission, event, book, allocation ...)", 20)},
         (), situation),
]
