"""The one picture (S64; the investor: "wired to all, in sync, like a brain").

Everything the system knows, laid side by side by CODE in one structure before any model thinks: the market's state and the
crash-risk gauges, the mood of the news, where the portfolio stands against its targets, each holding (price against its own
history, valuation in plain words, news mood, warnings), the themes against their limits, the cash and the dip reserve, what
is on offer (buy zones, scans, new listings, the opportunity pot), what could hurt (scenarios, warnings), what changed, what is
waiting for him, and what the system has learned. Each section is built on its own: one that cannot be built says why and the
rest stand. Every number is a stored or computed fact with its date; nothing here is a forecast and nothing is a model's.

`stance` is a label from the tested market states only (the fall-clustering state of S40 and the dip rule of S34): calm, watch or
stressed. It describes the market today; it does not predict a crash.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd


def _try(name: str, fn: Callable, out: dict) -> None:
    try:
        out[name] = fn()
    except Exception as e:                       # the rest of the picture stands
        out[name] = {"not_built": f"{type(e).__name__}: {str(e)[:120]}"}


def market(con, root: Path, asof: date) -> dict:
    from pflab.hq import context
    from pflab.plan import guards as gd
    from pflab.quant import options
    cl, dip = gd.market_cluster(asof, root), gd.market_dip(asof, root)
    state = cl["state"] if cl else None
    stance = "stressed" if state == "high" else ("watch" if state == "elevated" or dip["active"] else "calm")
    out = {"stance": stance, "fall_clustering_state": state,
           "chance_another_2pct_fall_in_10_sessions": None if not cl else round(cl["chance"], 3),
           "normal_chance": None if not cl else round(cl["normal"], 3),
           "nifty500_below_1y_high_pct": round(dip["drawdown"] * 100, 1), "dip_rule_active": bool(dip["active"]),
           "context": {k: v for k, v in context.market(root, asof).items() if k != "source"},
           "stance_rule": "stressed = fall-clustering state high; watch = elevated or the dip rule on; else calm (tested states, S34 and S40)"}
    fo = options.line(root, asof)
    if fo:
        out["options_line"] = fo
    from pflab.quant import implied
    im = implied.latest(root, asof)
    if im:
        sc = implied.scorecard(root)
        out["options_implied"] = {"line": implied.line(root, asof),
                                  **{k: im[k] for k in ("expiry", "days", "p_below_10", "p_below_5", "p_above_5", "skew_90_110")},
                                  "record": {k: sc["levels"][k] for k in ("below_5", "below_10")} if sc.get("levels") else None,
                                  "record_n": f"{sc.get('scored', 0)} days over {sc.get('expiries', 0)} expiries"}
    return out


def gauges_block(root: Path, asof: date) -> dict:
    """IPO froth, breadth and past correction lengths (quant/gauges.py): descriptions from our own data, each on its own."""
    from pflab.quant import gauges
    out: dict = {}
    for name, fn in (("ipo_froth", lambda: gauges.ipo_froth(root, asof)), ("breadth", lambda: gauges.breadth(root, asof)),
                     ("corrections", lambda: gauges.corrections(root, asof))):
        _try(name, fn, out)
    return out


def us_sleeve(con, root: Path, asof: date) -> dict:
    """The US sleeve: positions in dollars and rupees, the LRS year so far, whether the US market is open, and the pending study."""
    from pflab.conductor import us_calendar as uc
    from pflab.ledger import foreign as lf
    from pflab.tax import foreign as tf
    out: dict = {}
    pos = lf.positions(con, asof)
    cal = uc.load()
    now = datetime.now()
    out["us_market_now"] = cal.mode(now)
    nxt = asof if cal.is_trading_day(asof) else cal.next_trading_day(asof)
    sess = cal.session_ist(nxt)
    if sess:
        out["next_session_ist"] = f"{sess[0]:%a %d %b %H:%M} to {sess[1]:%H:%M}"
    rem = lf.remitted_in_fy(con, asof)
    out["lrs"] = {**rem, "room_usd": tf.lrs_room(rem["usd"])}
    out["positions"] = pos
    if not pos and not rem["usd"]:
        out["note"] = "no US holdings and nothing sent abroad yet"
    pend = con.execute("SELECT prop_id FROM limit_proposals WHERE kind='us_sleeve' AND status='pending'").fetchone()
    if pend:
        out["study_waiting_for_his_answer"] = True
    return out


def news_mood(con, asof: date, holdings: Dict[str, str]) -> dict:
    """Average news tone (GDELT) of the last 3 days against the last 90 days, for the market and for each holding."""
    def mean(q, args):
        r = con.execute(q, args).fetchone()
        return (None if r[0] is None else round(float(r[0]), 2), int(r[1]))
    t0, t3, t90 = pd.Timestamp(asof) + pd.Timedelta(days=1), pd.Timestamp(asof) - pd.Timedelta(days=3), pd.Timestamp(asof) - pd.Timedelta(days=90)
    base = "SELECT avg(tone), count(tone) FROM kg_docs WHERE kind='article' AND dup_of IS NULL AND tone IS NOT NULL AND published_at "
    now3, then90 = mean(base + "BETWEEN ? AND ?", [t3, t0]), mean(base + "BETWEEN ? AND ?", [t90, t3])
    newest = con.execute("SELECT max(published_at) FROM kg_docs WHERE kind='article'").fetchone()[0]
    out = {"market_last_3_days": now3, "market_prior_90_days": then90, "unit": "(average tone, number of articles); below 0 is negative",
           "newest_article": None if newest is None else str(newest)[:10], "holdings": {}}
    if now3[1] == 0:
        out["stale"] = (f"no articles stored for the last 3 days (the newest is {out['newest_article']}): the news collector is "
                        "behind, so the mood below is NOT today's")
    for isin, sym in holdings.items():
        q = ("SELECT avg(d.tone), count(d.tone) FROM kg_edges e JOIN kg_docs d ON d.doc_id = e.src WHERE e.dst = ? AND e.rel IN "
             "('about','mentions') AND d.kind='article' AND d.dup_of IS NULL AND d.tone IS NOT NULL AND d.published_at BETWEEN ? AND ?")
        a, b = mean(q, [f"company:{isin}", t3, t0]), mean(q, [f"company:{isin}", t90, t3])
        if a[1] >= 3:
            out["holdings"][sym] = {"last_3_days": a, "prior_90_days": b}
    return out


def portfolio(con, asof: date) -> dict:
    from pflab.agents import tools as at
    from pflab.pm import today
    from pflab.plan import targets as tg
    nw, t = at.networth(con, asof), tg.load()
    n = today.build(con, asof)
    inv = n["investable"] or 1.0
    rows = {}
    for b, bt in t.buckets.items():
        have = n["buckets"].get(b, 0.0) / inv
        rows[b] = {"now_pct": round(have * 100, 1), "target_pct": round(bt.target * 100, 1),
                   "state": "over" if have > bt.target + bt.soft_band else ("under" if have < bt.target - bt.soft_band else "inside the band")}
    return {"buckets": rows, "net_worth_rs": nw.get("net_worth"), "investable_rs": nw.get("investable"),
            "note": "shares of investable money; the FDs not yet deployed sit in debt, which is why equity is under its target"}


def holdings(con, root: Path, asof: date, bk, mood: dict) -> List[dict]:
    from pflab.hq import stocks, valuation
    from pflab.plan import nudges
    from pflab.quant import forecast as fc
    rows = []
    for r in stocks.overview(con, root, bk, paths=4_000)["stocks"]:
        isin = next((i for i, s in bk.symbols.items() if s == r["symbol"]), None)
        item = {k: r.get(k) for k in ("symbol", "held", "weight_pct", "share_pct", "gap_pct", "gain_pct", "return_3m_pct",
                                      "from_52w_high_pct", "guard", "zone")}
        if isin:
            try:
                v = valuation.facts(con, root, isin, r["symbol"], stocks.closes(con, root, isin, asof), asof)
                own = v.get("pe_own_5y") if isinstance(v.get("pe_own_5y"), dict) else {}
                item["pe"], item["pe_vs_own_5y_pct_rank"] = v.get("pe_ttm"), own.get("percentile_now")
                item["flags_on"] = [f["rule"] for f in v.get("rules_of_thumb", []) if f.get("applies")]
                item["futures_buildup"] = (v.get("futures_buildup") or {}).get("class")
            except Exception:
                pass
            n = nudges.check(root, isin, asof, scrip=fc.scrip_of(root, isin, asof))
            if n:
                item["warnings"] = [x["kind"] for x in n]
            m = mood["holdings"].get(r["symbol"])
            if m:
                item["news_tone_3d_vs_90d"] = [m["last_3_days"][0], m["prior_90_days"][0]]
        rows.append(item)
    return rows


def themes_block(con, root: Path, asof: date) -> dict:
    from pflab.plan import pot, reserve
    from pflab.risk import themes
    ex = themes.exposure_of(con, root, asof)
    out = {"themes": {t: {"label": e["label"], "share_of_portfolio_pct": round(e["weight"] * 100, 1),
                          "limit_pct": None if themes.applied(con, "theme_limit", t) is None else round(themes.applied(con, "theme_limit", t) * 100, 1)}
                      for t, e in ex.items()},
           "opportunity_pot": {"limit_rs": pot.limit(con), "used_rs": pot.used(con), "room_rs": pot.room(con)},
           "dip_reserve_trigger": reserve.trigger(asof, root)}
    pend = con.execute("SELECT kind, key FROM limit_proposals WHERE status='pending'").fetchall()
    if pend:
        out["waiting_for_his_yes"] = [f"{k}:{key}" for k, key in pend]
    return out


def on_offer(con, root: Path, asof: date, rows: List[dict], pm_dir: Optional[Path]) -> dict:
    import json
    out = {"in_buy_zone_and_guard_ok": [r["symbol"] for r in rows if r.get("zone") == "IN ZONE" and r.get("guard") == "ok"],
           "open_pot_ideas": [dict(zip(("symbol", "buy_below", "exit_above", "stop_below", "amount"), x)) for x in con.execute(
               "SELECT symbol, buy_below, exit_above, stop_below, amount FROM pot_ideas WHERE status='open'").fetchall()]}
    try:
        from pflab.plan import pot
        out["new_listings_with_20_sessions"] = len(pot.ipo_candidates(con, root, asof))
    except Exception:
        pass
    p = Path(pm_dir) / "app" / "cache" / "scans.json" if pm_dir else None
    if p and p.exists():
        sc = json.loads(p.read_text(encoding="utf-8"))
        out["scan_hits_on_his_names"] = {v["name"]: [h["symbol"] for h in v["hits"]] for v in sc.get("scans", {}).values() if v["hits"]}
    out["ready_plans"] = [{"source": q[0], "due": str(q[1]), "amount_rs": q[2]} for q in con.execute(
        "SELECT source, due, amount FROM ready_plans WHERE status='current' ORDER BY due LIMIT 4").fetchall()]
    return out


def risks(con, root: Path, asof: date, rows: List[dict]) -> dict:
    from pflab.risk import scenarios
    sc = scenarios.run_all(con, root, asof)
    return {"scenarios_rs_on_stocks_and_index_funds": {k: (v["error"] if "error" in v else
            {"total": round(v["total"]), "range": [round(x) for x in v["total_range"]], "pct_of_modelled": round(v["total_pct_of_modelled"] * 100, 1)})
            for k, v in sc.items()},
            "scenario_label": "from historical betas; a description, not a forecast",
            "names_with_guard_not_ok": [r["symbol"] for r in rows if r.get("guard") not in ("ok", "not checked", None)],
            "names_with_warnings": {r["symbol"]: r["warnings"] for r in rows if r.get("warnings")}}


def changed(con, asof: date, days: int = 3) -> dict:
    since = datetime.combine(asof, datetime.min.time()) - timedelta(days=days)
    q = lambda s, a=(): con.execute(s, list(a)).fetchone()[0]          # noqa: E731
    return {"research_flags": q("SELECT count(*) FROM research_flags WHERE detected_at >= ?", [since]),
            "material_readings": q("SELECT count(*) FROM hq_readings WHERE material='yes' AND read_at >= ?", [since]),
            "hypotheses_to_decide": q("SELECT count(*) FROM kg_hypotheses WHERE status='review'"),
            "days": days}


def waiting(con) -> dict:
    return {"open_questions": con.execute("SELECT count(*) FROM questions WHERE status='open'").fetchone()[0],
            "held_messages": con.execute("SELECT count(*) FROM outbox WHERE status='held'").fetchone()[0]}


def learning(con) -> dict:
    from pflab.learner import counter
    return {"tests_run": counter.n_tests(con), "bar_for_next": counter.line(con),
            "tested_findings_in_force": con.execute("SELECT count(*) FROM learned WHERE kind='finding' AND valid_to IS NULL").fetchone()[0],
            "suggestions_open": con.execute("SELECT count(*) FROM hq_suggestions WHERE outcome IS NULL AND NOT shadow").fetchone()[0],
            "predictions_open": con.execute("SELECT count(*) FROM hq_predictions WHERE outcome IS NULL").fetchone()[0]}


def cached(con, root: Path, asof: date, bk=None, pm_dir: Optional[Path] = None, max_age_min: int = 30) -> dict:
    """The picture, reused for `max_age_min` minutes (a full build takes about a minute)."""
    import json
    p = (Path(pm_dir) / "app" / "cache" / "picture.json") if pm_dir else None
    if p is not None and p.exists() and (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() < max_age_min * 60:
        try:
            got = json.loads(p.read_text(encoding="utf-8"))
            if got.get("asof") == str(asof):
                return got
        except ValueError:
            pass
    out = build(con, root, asof, bk, pm_dir)
    if p is not None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, default=str), encoding="utf-8")
    return out


def build(con, root: Path, asof: date, bk=None, pm_dir: Optional[Path] = None) -> dict:
    root = Path(root)
    out: dict = {"asof": str(asof)}
    _try("market", lambda: market(con, root, asof), out)
    held = {}
    if bk is not None:
        held = {i: s for i, s in bk.symbols.items() if i in bk.values or i in bk.on_list}
    _try("gauges", lambda: gauges_block(root, asof), out)
    _try("us_sleeve", lambda: us_sleeve(con, root, asof), out)
    _try("news_mood", lambda: news_mood(con, asof, held), out)
    _try("portfolio", lambda: portfolio(con, asof), out)
    mood = out["news_mood"] if "holdings" in out.get("news_mood", {}) else {"holdings": {}}
    rows: List[dict] = []
    if bk is not None:
        try:
            rows = holdings(con, root, asof, bk, mood)
            out["holdings"] = rows
        except Exception as e:
            out["holdings"] = {"not_built": f"{type(e).__name__}: {str(e)[:120]}"}
    _try("themes_and_cash", lambda: themes_block(con, root, asof), out)
    _try("on_offer", lambda: on_offer(con, root, asof, rows, pm_dir), out)
    _try("could_hurt", lambda: risks(con, root, asof, rows), out)
    _try("changed", lambda: changed(con, asof), out)
    _try("waiting_for_him", lambda: waiting(con), out)
    _try("learned", lambda: learning(con), out)
    out["headline"] = headline(out)
    return out


def headline(p: dict) -> List[str]:
    """The picture in a few lines, by code."""
    m = p.get("market", {})
    lines = []
    if m.get("options_implied"):
        lines.append(m["options_implied"]["line"])
    if "stance" in m:
        lines.append(f"Market: {m['stance']} (fall-clustering {m.get('fall_clustering_state')}, Nifty 500 {m.get('nifty500_below_1y_high_pct')}% "
                     f"below its 1-year high, dip rule {'on' if m.get('dip_rule_active') else 'off'}).")
    g = p.get("gauges", {})
    b = g.get("breadth", {})
    if "above_200d_pct" in b:
        lines.append(f"Breadth: {b['above_200d_pct']}% of the Nifty 500 above its 200-day average, {b['above_50d_pct']}% above the 50-day "
                     f"(the 200-day share is lower than on {100 - b['above_200d_percentile_1y']}% of days this year): {b['read']}.")
    f = g.get("ipo_froth", {})
    if f.get("ratio") is not None:
        lines.append(f"IPOs: {f['per_quarter_now']} large listings a quarter against {f['per_quarter_prior_5_years']} in the 5 years before: "
                     f"{f['read']}; median listing gain {f['median_listing_gain_now_pct']}%.")
    c = g.get("corrections", {}).get("indices", {}).get("Nifty500")
    if c:
        lines.append(f"Nifty 500 is {abs(c['now_below_peak_pct'])}% below its peak, {c['sessions_since_peak']} sessions in; past falls of 10%+ "
                     f"took a median {c.get('median_sessions_peak_to_trough')} sessions down and {c.get('median_sessions_trough_to_new_high')} "
                     f"back to a new high (longest {c.get('longest_peak_to_new_high')}).")
    nm = p.get("news_mood", {})
    if nm.get("stale"):
        lines.append("News mood: " + nm["stale"] + ".")
    elif nm.get("market_last_3_days") and nm["market_last_3_days"][0] is not None:
        lines.append(f"News mood: {nm['market_last_3_days'][0]:+.1f} over 3 days against {nm['market_prior_90_days'][0]:+.1f} over 90.")
    pf = p.get("portfolio", {}).get("buckets")
    if pf:
        lines.append("Allocation: " + ", ".join(f"{b} {v['now_pct']:.0f}% (target {v['target_pct']:.0f}%, {v['state']})" for b, v in pf.items()) + ".")
    th = p.get("themes_and_cash", {}).get("themes")
    if th:
        lines.append("Themes: " + ", ".join(f"{v['label']} {v['share_of_portfolio_pct']}%" + (f" of {v['limit_pct']}% limit" if v["limit_pct"] else " (no limit yet)")
                                             for v in th.values()) + ".")
    h = p.get("holdings")
    if isinstance(h, list):
        flagged = [r["symbol"] for r in h if r.get("held") and (r.get("warnings") or r.get("guard") not in ("ok", "not checked", None))]
        zone = p.get("on_offer", {}).get("in_buy_zone_and_guard_ok") or []
        lines.append(f"Holdings: {sum(1 for r in h if r.get('held'))} held; warnings on {flagged or 'none'}; in buy zone: {zone or 'none'}.")
    w = p.get("waiting_for_him", {})
    if w:
        lines.append(f"Waiting for him: {w['open_questions']} questions; {w['held_messages']} held messages.")
    return lines
