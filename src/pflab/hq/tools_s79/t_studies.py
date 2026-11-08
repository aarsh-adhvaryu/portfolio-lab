"""S79b items 15, 15b, 7b: the read tool `wave_studies`, the verdicts of the pre-registered event studies (docs/protocols/s79_wave_sentiment_protocol.md). Works with {};
`configs/s79b.toml [studies] on = false` gives {"off": true}. A verdict is a description of 2004-2021, not a forecast, and nothing trades on a flag by itself.

RESULT KEYS (agent S reads these): call_ref, market, n_tests_total (11 registered), n_run, results: [{test, market, horizon_sessions, flag, verdict ("followed through: ..." |
  "no reliable follow-through" | "n too small, no conclusion ..." | "not available"), passed (bool), n_events, effect_pct (index return, or points for a share), ci_low_pct, ci_high_pct,
  p_one_sided, t_stat, bar_t (the counter's bar when it ran), n_counter, ran_at}], followed_through: [tests that passed, the only ones the dossier may label "followed through"],
  not_run: {test: reason}, source ('wave_study_results_s79' or 'docs/research/wave_sentiment_results_s79.json'), note. With {"test": "wave_5"} only that test; {"market": "IN"} filters."""
from __future__ import annotations

import json
from pathlib import Path

from pflab.hq.tools import Ctx, Tool, _s

TEST = _s("One test name, e.g. wave_5, wave_20, rotation_5, crude_fall_20, extreme_sentiment_5, value_area_return_1, poc_migration_5. Default: all.", 40)
MARKET = _s("The market: IN or US. Default: all.", enum=("IN", "US"))


def _is_on() -> bool:
    try:
        from pflab import _toml, markets
        return bool((_toml.load(markets.CONFIGS / "s79b.toml").get("studies", {}) or {}).get("on", True))
    except Exception:
        return True


def _row(r: dict) -> dict:
    d = r.get("details") or {}
    pct = 100.0

    def sc(v):
        return None if v is None else round(float(v) * pct, 3)
    return {"test": r.get("test"), "market": r.get("market"), "horizon_sessions": d.get("h"), "flag": d.get("family"), "verdict": r.get("verdict"), "passed": bool(r.get("passed")),
            "n_events": r.get("n_events"), "n_baseline": r.get("n_baseline"), "unit": d.get("unit", "pct"), "effect_pct": sc(r.get("effect")), "ci_low_pct": sc(r.get("ci_low")),
            "ci_high_pct": sc(r.get("ci_high")), "p_one_sided": None if r.get("p") is None else round(float(r["p"]), 5), "t_stat": None if d.get("t_stat") is None else round(float(d["t_stat"]), 3),
            "bar_t": None if r.get("t_needed") is None else round(float(r["t_needed"]), 3), "n_counter": r.get("n_counter"), "range": d.get("range"), "ran_at": r.get("ran_at")}


def _from_file() -> list:
    from pflab.quant import index_event_study as S
    p = S.REPO / S.RESULTS_JSON
    if not p.exists():
        return []
    try:
        return list(json.loads(p.read_text(encoding="utf-8")).get("results", []))
    except Exception:
        return []


def wave_studies(ctx: Ctx, a: dict) -> dict:
    try:
        if not _is_on():
            return {"off": True, "call_ref": ctx.call_ref}
        from pflab.quant import index_event_study as S
        rows = S.results(ctx.con)
        src = "wave_study_results_s79"
        if not rows:
            rows, src = _from_file(), S.RESULTS_JSON
        if a.get("test"):
            rows = [r for r in rows if r.get("test") == str(a["test"])]
        if a.get("market"):
            rows = [r for r in rows if r.get("market") == str(a["market"]).upper()]
        out = [_row(r) for r in rows]
        done = {(r["test"]) for r in out if r["market"] == "IN"}
        not_run = {t: S.NOT_RUN_REASONS.get(t, "not run yet") for t in S.TESTS if t not in done and (not a.get("test") or a["test"] == t)}
        return {"call_ref": ctx.call_ref, "n_tests_total": len(S.TESTS), "n_run": len(out), "results": out,
                "followed_through": [r["test"] for r in out if r["passed"] and r["market"] == "IN"], "not_run": not_run, "source": src,
                "note": ("a description of 2004-2021, not a forecast; a test that did not pass gives the dossier no 'followed through' label; nothing trades on a flag by itself; "
                         "quote an effect with its interval and n and cite the call_ref")}
    except Exception as e:                                                   # noqa: BLE001
        return {"error": repr(e)[:200], "call_ref": ctx.call_ref, "note": "the study verdicts could not be read"}


TOOLS = [
    Tool("wave_studies", "read",
         "The verdicts of the pre-registered event studies on market waves, foreign-flow rotations, large one-day crude falls, extreme sentiment readings, value-area exits and POC migration "
         "(index forward returns 2004-2021, non-overlapping events, moving-block bootstrap, the learner counter's bar). A verdict is 'followed through: N events, effect X%, interval Y' or "
         "'no reliable follow-through' or 'n too small, no conclusion'. Only a test that passed may be called 'followed through'. Result keys: call_ref, n_tests_total, n_run, results "
         "[{test, market, horizon_sessions, flag, verdict, passed, n_events, effect_pct, ci_low_pct, ci_high_pct, p_one_sided, t_stat, bar_t, n_counter}], followed_through, not_run, source. "
         "A description of history, not a forecast. Cite the call_ref.",
         {"test": TEST, "market": MARKET}, (), wave_studies),
]
