"""S79b item 15b: three read tools. `sentiment` (news tone, priced fear and positioning per theme, a transparent combined score), `theme_exposure` (which themes the book carries, by
sector prior and measured beta) and `event_calendar` (scheduled shocks with a scenario note before and a surprise measure after). Every number comes from code
(pflab/sentiment/); the local model only labelled headlines with a theme and a tone class. With `configs/s79b.toml [sentiment] on = false` each returns {"off": true}.

RESULT KEYS (agent S reads these):
 sentiment      -> {market, asof, day, computed_on_the_fly, themes: {theme: {label, combined, n_groups, n_comp, tone_score, fear_score, pos_score,
                    components: {name: {value, z}}, tone_gdelt_n, tone_model_n}}, market_components: {name: {value, z}}, price_score,
                    events: {upcoming: [{id, date, label, verified, scenario: {theme: text}}], recent: [{id, date, label, surprise: text}]},
                    reading, source, call_ref}
 theme_exposure -> {market, asof, source (paper|main|none), themes: {theme: {label, primary_proxy, book_beta, weight_carrying, weight_sector_prior, n_carriers,
                    holdings: [{symbol, isin, weight, sector_prior, beta, t, n, contribution}], universe: {...}}}, missing_proxies, revenue_mix, units, call_ref}
 event_calendar -> {market, asof, upcoming: [...], recent: [...], unverified: [ids], call_ref}"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from pflab.hq.tools import Tool, Ctx, _i, _s

try:                                                         # the lens registers itself; a missing plug-in module never blocks the tools
    from pflab.sentiment import lens as _lens
    _lens.register_lens()
except Exception:                                            # noqa: BLE001
    pass

COMPONENTS = ("tone_gdelt", "tone_country", "tone_model", "fear_vix", "fear_pcr", "fear_skew", "proxy_vol", "pos_flow", "pos_fut", "pos_dii", "pos_oi", "pos_breadth")
MARKET_LEVEL = ("tone_country", "fear_vix", "fear_pcr", "fear_skew", "pos_flow", "pos_fut", "pos_dii", "pos_oi", "pos_breadth")


def _f(x, nd: int = 3):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if np.isfinite(v) else None


def _day(a: dict, ctx: Ctx) -> date:
    try:
        return date.fromisoformat(str(a["date"])) if a.get("date") else ctx.asof
    except ValueError:
        return ctx.asof


def _comp(row, c: str) -> dict:
    return {"value": _f(row.get(c), 4), "z": _f(row.get(f"{c}_z"))}


def sentiment(ctx: Ctx, a: dict) -> dict:
    from pflab import markets
    from pflab import sentiment as S
    from pflab.sentiment import calendar as cal, compute, themes as T
    if not S.is_on():
        return dict(S.OFF)
    market = (a.get("market") or "IN").upper()
    asof = _day(a, ctx)
    root = ctx.rt.data_root
    if market not in markets.codes():
        return {"market": market, "available": False, "message": f"unknown market {market}", "markets": markets.codes()}
    th_all = T.load_themes(market)
    theme = a.get("theme")
    if theme and theme not in th_all:
        return {"market": market, "available": False, "message": f"unknown theme {theme!r}", "themes_available": sorted(th_all)}
    n_days = int(a.get("days", 1))
    con = ctx.con
    last = markets.get(market).last_session_on_or_before(asof)
    df = compute.stored(con, market, asof, theme, n_days)
    fly = False
    if df.empty or pd.Timestamp(df["day"].max()) < pd.Timestamp(last):
        sessions = markets.get(market).sessions_between(last - timedelta(days=int(n_days * 2 + 6)), last)[-n_days:]
        try:
            df = compute.compute_range(con, root, market, sessions, {theme: th_all[theme]} if theme else th_all)
            fly = True
        except Exception as e:
            return {"market": market, "asof": str(asof), "available": False, "message": f"the sentiment could not be computed here ({type(e).__name__}: {str(e)[:120]})",
                    "call_ref": ctx.call_ref}
    if df is None or df.empty:
        return {"market": market, "asof": str(asof), "available": False, "message": "no sentiment rows and no data to compute them on this PC", "themes": {}, "call_ref": ctx.call_ref}
    day = df["day"].max()
    cur = df[df["day"] == day]
    out: dict = {"market": market, "asof": str(asof), "day": str(day), "available": True, "computed_on_the_fly": fly, "themes": {}, "history": {}}
    for r in cur.to_dict("records"):
        out["themes"][r["theme"]] = {"label": th_all[r["theme"]].label if r["theme"] in th_all else r["theme"], "combined": _f(r["combined"]), "n_groups": int(r["n_groups"]) if pd.notna(r["n_groups"]) else 0,
                                     "n_comp": int(r["n_comp"]) if pd.notna(r["n_comp"]) else 0, "tone_score": _f(r["tone_score"]), "fear_score": _f(r["fear_score"]), "pos_score": _f(r["pos_score"]),
                                     "components": {c: _comp(r, c) for c in COMPONENTS}, "tone_gdelt_n": None if pd.isna(r["tone_gdelt_n"]) else int(r["tone_gdelt_n"]),
                                     "tone_model_n": None if pd.isna(r["tone_model_n"]) else int(r["tone_model_n"])}
    first = cur.iloc[0].to_dict()
    out["market_components"] = {c: _comp(first, c) for c in MARKET_LEVEL}
    if n_days > 1:
        for r in df.sort_values("day").to_dict("records"):
            out["history"].setdefault(r["theme"], []).append({"day": str(r["day"]), "combined": _f(r["combined"]), "tone_score": _f(r["tone_score"]), "fear_score": _f(r["fear_score"]),
                                                              "pos_score": _f(r["pos_score"])})
    try:
        ps = compute.price_score(root, market, pd.DatetimeIndex([pd.Timestamp(day)]))
        out["price_score"] = {"score": _f(ps["score"].iloc[0]), "fear_score": _f(ps["fear_score"].iloc[0]), "pos_score": _f(ps["pos_score"].iloc[0]), "n_comp": int(ps["n_comp"].iloc[0])}
    except Exception:
        out["price_score"] = None
    ev = {"upcoming": [], "recent": []}
    try:
        notes = {(r[0], r[1]): r[2] for r in con.execute("SELECT event_id, theme, text FROM sentiment_event_notes_s79 WHERE market=? AND kind='scenario'", [market]).fetchall()}
        snotes = {r[0]: r[1] for r in con.execute("SELECT event_id, text FROM sentiment_event_notes_s79 WHERE market=? AND kind='surprise'", [market]).fetchall()}
    except Exception:
        notes, snotes = {}, {}
    for e in cal.upcoming(asof, 10, market):
        sc = {k: notes.get((e.id, k)) or cal.scenario_note(root, e, market, th_all[k], asof)["text"] for k in e.themes if k in th_all}
        ev["upcoming"].append({"id": e.id, "date": str(e.date), "label": e.label, "verified": e.verified, "scenario": sc})
    for e in cal.recent(asof, 10, market):
        s = snotes.get(e.id)
        if s is None:
            r = cal.surprise(root, e, market, th_all, asof)
            s = r["text"] if r else None
        ev["recent"].append({"id": e.id, "date": str(e.date), "label": e.label, "verified": e.verified, "surprise": s})
    out["events"] = ev
    out["reading"] = ("Scores are z-scores against each component's own trailing history (the day itself excluded); positive = risk-on. combined = mean of the group scores "
                      "(tone, fear with the sign flipped, positioning) that exist, n_groups says how many. Model-read news tone is forward-only and appears only from the days the "
                      "system tagged live. A description of the mood, not a forecast.")
    out["source"] = "pflab/sentiment (GDELT GKG and country tone, India VIX / US VIX, Nifty put-call and skew, NSDL FPI flows, NSE participant OI, F&O build-up, bhavcopy breadth)"
    out["call_ref"] = ctx.call_ref
    return out


def theme_exposure(ctx: Ctx, a: dict) -> dict:
    from pflab import sentiment as S
    from pflab.sentiment import exposure
    if not S.is_on():
        return dict(S.OFF)
    market = (a.get("market") or "IN").upper()
    day = _day(a, ctx)
    try:
        r = exposure.compute(ctx.con, ctx.rt.data_root, day, market, a.get("book", "auto"), universe=bool(a.get("universe", True)), top=int(a.get("top", 5)))
    except Exception as e:
        return {"market": market, "asof": str(day), "available": False, "message": f"the exposure could not be computed here ({type(e).__name__}: {str(e)[:120]})", "themes": {},
                "call_ref": ctx.call_ref}
    r["call_ref"] = ctx.call_ref
    r["reading"] = ("book_beta is the % move of the whole book for a 1% move of the theme's primary proxy, from stocks whose measured beta is significant; weight_carrying is the share "
                    "of the book in holdings that carry the theme (sector prior or measured beta). Betas are history, not a forecast.")
    return r


def event_calendar(ctx: Ctx, a: dict) -> dict:
    from pflab import sentiment as S
    from pflab.sentiment import calendar as cal, themes as T
    if not S.is_on():
        return dict(S.OFF)
    market = (a.get("market") or "IN").upper()
    asof = _day(a, ctx)
    days = int(a.get("days", 30))
    th = T.load_themes(market)
    root = ctx.rt.data_root
    out = {"market": market, "asof": str(asof), "upcoming": [], "recent": [], "unverified": [e.id for e in cal.load_events() if not e.verified], "call_ref": ctx.call_ref}
    for e in cal.upcoming(asof, days, market):
        out["upcoming"].append({"id": e.id, "date": str(e.date), "label": e.label, "kind": e.kind, "verified": e.verified, "source": e.source,
                                "scenario": {k: cal.scenario_note(root, e, market, th[k], asof) for k in e.themes if k in th}})
    for e in cal.recent(asof, days, market):
        s = cal.surprise(root, e, market, th, asof)
        out["recent"].append({"id": e.id, "date": str(e.date), "label": e.label, "kind": e.kind, "verified": e.verified, "source": e.source, "surprise": s})
    return out


_BOOL = lambda about: {"type": "boolean", "description": about}      # noqa: E731

TOOLS = [
    Tool("sentiment", "read", "The mood of the market and of each theme (AI and tech regulation, oil and the Middle East, tariffs and trade, rates and central banks, domestic policy and the Budget): "
         "news tone (GDELT tone; the local model's tagged headlines, live only), priced fear (India VIX or US VIX, put-call ratio, option skew, the theme proxy's realised volatility) and "
         "positioning (FII flows, FII/DII index-futures positions, futures build-up, breadth), each as a value and a z-score against its own trailing history, and a combined score "
         "(positive = risk-on) with the number of groups behind it. Also the next scheduled events with their scenario notes and the last events' surprise. By code; nothing here is a forecast.",
         {"market": _s("IN (default) or US", 4), "theme": _s("one theme key, e.g. oil_middle_east (omit for all)", 60), "date": _s("ISO date (default today)", 10),
          "days": _i("how many recent sessions of combined scores to include (default 1)", 1, 30)}, (), sentiment),
    Tool("theme_exposure", "read", "Which themes the book carries and through which holdings: each holding is mapped to the sentiment themes by sector, revenue mix (where data exists) and its measured "
         "point-in-time beta to the theme's price proxy (Brent crude, Nasdaq or semiconductors, USD/INR, the US 10-year yield, the Nifty). Returns, per theme, the book's beta (% move of the book for a 1% "
         "move of the proxy), the weight that carries the theme, the holdings with their betas and t-statistics, and the same map for the Nifty 500 universe (counts, strongest carriers). "
         "The book is the paper portfolio, else the main one.",
         {"market": _s("IN (default)", 4), "book": _s("auto (default), paper or main", enum=["auto", "paper", "main"]), "date": _s("ISO date (default today)", 10),
          "universe": _BOOL("also map the Nifty 500 universe (default true)"), "top": _i("strongest carriers listed per theme in the universe (default 5)", 1, 20)}, (), theme_exposure),
    Tool("event_calendar", "read", "The calendar of scheduled shocks (elections, Fed and RBI decisions, the Budget) with the source of each date and whether it is verified; for each coming event a "
         "code-written scenario note per theme (the index's measured sensitivity to the theme's proxy, the proxy's typical move, the options-implied one-session move), and for each recent event "
         "the surprise measure (the index move against the move the volatility index implied).",
         {"market": _s("IN (default) or US", 4), "date": _s("ISO date (default today)", 10), "days": _i("window in calendar days either way (default 30)", 1, 400)}, (), event_calendar),
]
