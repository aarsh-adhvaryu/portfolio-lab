"""S80 phase 3 job `story_daily`: the storylines' daily upkeep after the close (the dot-connecting step). The adapters bring dated evidence items from the flows, the macro attribution and
the wave scan; the LOCAL reader attaches each to a storyline, opens a new one, or ignores it (a disagreement escalates to Sonnet only inside the cap); then every open storyline's
probability is recomputed by code from the signals and the evidence, new storylines get their predictions at 5 and 20 sessions, due predictions are scored, influence follows the record,
and the record of which kinds of story hold is refreshed. Free except an escalation. Skips when `[core] on = false` or the kill switch is set."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab import core
    if core.killed():
        return False, "the kill switch is set (configs/core.toml [core] kill)"
    return (True, "") if core.on() else (False, "switched off in configs/core.toml [core]")


def _run(ctx) -> dict:
    from pflab import markets
    from pflab.story import adapters, predict, prob, reader, store
    con = ctx.con
    asof = markets.get("IN").session_closed_by(ctx.now)
    items = adapters.collect(con, ctx.data_root, asof)
    out = {"asof": str(asof), "items": len(items), "reader": reader.process(con, ctx.now, items)}
    out["probabilities"] = prob.update_all(con, ctx.now, asof, ctx.data_root)
    for s in store.listing(con, ("open",)):
        if not con.execute("SELECT 1 FROM storyline_predictions_s80 WHERE storyline_id=? LIMIT 1", [s["storyline_id"]]).fetchone():
            predict.register(con, ctx.now, s["storyline_id"], s["opened_on"], ctx.data_root)
    try:                                                                   # exposure: a rotation story points at the domestic-demand names the book holds (a rule, with its source)
        from pflab.paper import book
        from pflab.story import case
        held = [r["isin"] for r in book.holdings(con, ctx.now.date())["rows"]] if book.started(con) else []
        for s in store.listing(con, ("open",)):
            if s["kind"] == "flow_rotation" and held and not con.execute("SELECT 1 FROM storyline_exposure_s80 WHERE storyline_id=? LIMIT 1", [s["storyline_id"]]).fetchone():
                store.exposure_by_sector(con, s["storyline_id"], case.DOMESTIC_EXPOSURE, held, "rule: domestic-demand sectors gain from foreign inflows", asof)
    except Exception:
        pass
    out["scored"] = predict.score_due(con, ctx.now, ctx.now.date(), ctx.data_root)
    store.refresh_record(con, ctx.now)
    return out


def _redo(ctx):
    try:
        from pflab import markets
        asof = markets.get("IN").session_closed_by(ctx.now)
        done = ctx.con.execute("SELECT 1 FROM storyline_prob_s80 WHERE prob_date=? LIMIT 1", [asof]).fetchone()
        if not done and ctx.con.execute("SELECT count(*) FROM storylines_s80 WHERE status='open'").fetchone()[0]:
            return f"the storylines have no probability for {asof} yet"
    except Exception:
        pass
    return None


register(Job("story_daily", Interval(120, weekdays_only=False), _run, "the storylines' daily upkeep: the local reader attaches the day's evidence, probabilities by code, predictions scored (local, free)",
             cooldown_minutes=30, enabled_fn=_enabled, redo_fn=_redo))
