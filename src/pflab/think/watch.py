"""T1 NOTICE (S84, A65, A67, A68): what just happened to this book? Code only: no model, no cost, nothing reaches a broker.

    run(con, now, *, mode, quotes=None, root=None)
        mode 'session'    the held names on live quotes (cheap: the price signals, the stored forecast ranges and the thesis-break events only)
        mode 'close'      the India close: every signal below for India's scope
        mode 'us_morning' everything since the last US close: the US scope, and the overnight shocks (US indices, dollar-rupee, crude)
        mode 'catchup'    each missed India close and US morning once, in order, point in time (a gap is never replayed twice)
    scope(con, day)       what the watch looks at (name, isin, symbol, market, exposure_inr, exposure_pct, why)

Signals (each is a number with its own threshold in `configs/core.toml [think]`; `surprise` is the number over its threshold, so 1.0 is exactly at the line):
    move_1d / move_5d         the move over 1 or 5 sessions beyond `move_sigmas` times the name's usual daily move (the 5-day line is sigma x sqrt 5)
    rel_1d / rel_5d           the same, for the move against its market's index
    outside_forecast          the move since a stored live forecast (hedge) was made lies outside that forecast's 5%-95% range
    fall_10d                  a fall of `fall_pct_10d` in 10 sessions
    rel_fall_5d               `rel_pts_5d` points worse than its market in 5 sessions
    market_down_20d           the market's index down `market_down_20d` in 20 sessions
    news_burst                linked news today against its own 60-day norm (`news_burst_x`, at least `news_burst_min` items)
    thesis_event              an event of a thesis-break kind (`kg/events.material_events`: the kinds and severities are the graph's)
    storyline_jump            an open storyline's probability moved `storyline_jump_pts` points in a day
    overnight_shock           the US indices, the dollar-rupee or crude moved beyond `move_sigmas` of their usual daily move
    missed_run                a name the system looked at and PASSED ON (a skipped idea, a screened name) now `missed_run_pts` points or more ahead of its index since that day

Score = surprise x exposure in rupees. The exposure of a name the book does not hold is a labelled stand-in (`standin_weight` of the whole book: the index weights are not stored); a market or
macro signal's exposure is `market_exposure_factor` of the equity the book holds (a ranking weight only, never a rupee claim). A new signal on a name with an open case JOINS that case; at most
`max_cases_per_day` NEW cases a day are opened (the largest score first), the rest are stored as state `noticed` (never examined). Every signal is stored once per (name, signal, day).
Point in time: a price, a filing and a probability dated after the pass's day, or after `now`, is never read. Pseudo keys for non-security cases: 'MARKET:IN', 'MARKET:US', 'MACRO:<series>', 'STORY:<id>'.
`[think] wide_watch` (the Nifty 500 and S&P 500 members, S85) is read and stays OFF: no wide-watch code is written here.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab import think
from pflab.think import cases

WATCH_DEFAULTS = {
    "wide_watch": False,                # S85: the Nifty 500 and S&P 500 members. OFF; nothing here reads it beyond saying so.
    "history_sessions": 260, "min_history": 60, "sigma_min_obs": 40,
    "news_burst_min": 3, "news_norm_days": 60,
    "market_exposure_factor": 0.25,     # a market or macro signal's ranking exposure: this share of the equity the book holds
    "standin_weight": 0.001,            # the exposure of a name the book does not hold: this share of the whole book (labelled a stand-in; the index weights are not stored)
    "event_lookback_days": 3, "max_stale_days": 5,
    "screen_lookback_days": 60, "skip_lookback_days": 365, "missed_cooldown_days": 30, "missed_max_names": 300,
    "catchup_max_sessions": 10,
    "forecast_low": "0.05", "forecast_high": "0.95",
}
GROUP = {"move_1d": "move", "move_5d": "move", "rel_1d": "move", "rel_5d": "move", "outside_forecast": "move", "fall_10d": "fall", "rel_fall_5d": "fall", "market_down_20d": "market",
         "news_burst": "news", "thesis_event": "event", "storyline_jump": "storyline", "overnight_shock": "overnight", "missed_run": "missed_run"}
SEV_SURPRISE = {"medium": 2.0, "high": 3.0}
MACRO = (("SP500", "the S&P 500"), ("NASDAQ", "the Nasdaq"), ("USDINR", "the dollar-rupee"), ("BRENT", "crude oil (Brent)"))
EPS = 1e-9


def settings() -> dict:
    out = dict(WATCH_DEFAULTS)
    out.update(think.settings())
    return out


def _on() -> bool:
    try:
        return bool(think.on())
    except Exception:
        return bool(settings().get("on", True))


# --- series ---------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _index(market: str, root=None) -> Optional[pd.Series]:
    """The market's index level (India: the Nifty 500 total return index; US: SPY). Tests replace this function."""
    try:
        from pflab.core import pick_score
        s = pick_score.index_series(market, root)
    except Exception:
        return None
    if s is None or not len(s):
        return None
    s = s.copy()
    s.index = pd.to_datetime(s.index).normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def _panel_end(root, isin: str) -> Optional[date]:
    """The last date of the research panel's adjusted closes for `isin` (those closes already carry every split up to it), None when the panel has nothing."""
    try:
        from pflab import _duck
        from pflab.core import pick_score
        p = pick_score._root(root) / "panel" / "prices.parquet"
        if not p.exists():
            return None
        d = _duck.sql(f"SELECT max(date) AS d FROM '{p.as_posix()}' WHERE isin = '{isin}'").df()["d"].iloc[0]
        return None if pd.isna(d) else pd.Timestamp(d).date()
    except Exception:
        return None


def _adjust(s: pd.Series, isin: str, root, after: Optional[date] = None) -> pd.Series:
    """Earlier closes scaled by each split or bonus factor that went ex after `after` (the panel's own end: it carries the splits before it), so a split is not a fall."""
    try:
        from pflab.core import pick_score
        f = pick_score._factors(isin, pick_score._root(root))
    except Exception:
        return s
    if f is None or not len(f):
        return s
    s = s.copy()
    for r in f.itertuples(index=False):
        if abs(float(r.factor) - 1.0) > EPS and (after is None or r.ex_date > after):
            s[s.index < pd.Timestamp(r.ex_date)] *= float(r.factor)
    return s


def _history(con, market: str, key: str, symbol: Optional[str], day: date, root, cfg: dict, full: bool = False) -> Optional[pd.Series]:
    """Closes up to `day` (never after it), adjusted for splits; None when there are not enough. `full`: the whole stored history (a missed run looks back to the day it was passed on)."""
    n = int(cfg["history_sessions"])
    if market == "US":
        try:
            from pflab.core import pick_score
            s = pick_score.us_series(symbol or key, root)
        except Exception:
            s = None
        if s is None:
            return None
        s = s[s.index <= pd.Timestamp(day)]
    else:
        try:
            from pflab.app import research
            from pflab.core import pick_score
            s = research.closes(con, pick_score._root(root), key, day, years=3 if full else 2)      # the panel's long history joined to the store's recent closes (the join the forecasts use)
        except Exception:
            s = pd.Series(dtype=float)
        s = pd.Series(s).astype(float).dropna()
        if not len(s):
            return None
        s.index = pd.to_datetime(s.index).normalize()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        s = _adjust(s[(s.index <= pd.Timestamp(day)) & (s > 0)], key, root, _panel_end(root, key))
    if not full:
        s = s.tail(n + 1)
    return s if len(s) >= (2 if full else int(cfg["min_history"])) else None


def _at(ix: Optional[pd.Series], ts: pd.Timestamp) -> Optional[float]:
    if ix is None:
        return None
    v = ix[ix.index <= ts]
    return float(v.iloc[-1]) if len(v) else None


# --- the price signals of one name ---------------------------------------------------------------------------------------------------------------------------------------

def _price_signals(s: pd.Series, ix: Optional[pd.Series], cfg: dict, light: bool = False) -> List[dict]:
    """The signals a close series gives (the last bar is 'today'). `ix` is its market's index (None: no relative signals). Never raises."""
    out: List[dict] = []
    try:
        r = s.pct_change().dropna()
        base = r.iloc[-251:-1]
        if len(base) < int(cfg["sigma_min_obs"]):
            return out
        sigma = float(base.std())
        if not sigma > 0 or math.isnan(sigma):
            return out
        k = float(cfg["move_sigmas"])
        last = s.index[-1]
        px = float(s.iloc[-1])
        det = {"px_day": str(last.date()), "price": px, "sigma_daily": round(sigma, 5)}

        def add(sig: str, value: float, thr: float, extra: Optional[dict] = None):
            out.append({"signal": sig, "value": float(value), "threshold": float(thr), "surprise": abs(value) / abs(thr) if thr else 0.0, "detail": {**det, **(extra or {})}})

        r1 = float(r.iloc[-1])
        if abs(r1) > k * sigma:
            add("move_1d", r1, k * sigma, {"sigmas": round(abs(r1) / sigma, 2)})
        r5 = px / float(s.iloc[-6]) - 1.0 if len(s) > 6 else None
        if r5 is not None and abs(r5) > k * sigma * math.sqrt(5):
            add("move_5d", r5, k * sigma * math.sqrt(5), {"sigmas": round(abs(r5) / (sigma * math.sqrt(5)), 2)})
        if len(s) > 11:
            f10 = px / float(s.iloc[-11]) - 1.0
            if f10 <= -float(cfg["fall_pct_10d"]):
                add("fall_10d", f10, -float(cfg["fall_pct_10d"]))
        if ix is not None and len(ix) > 30 and (last - ix.index[-1]).days <= int(cfg["max_stale_days"]):
            ri = ix.pct_change().dropna()
            j = pd.concat([r.rename("a"), ri.rename("b")], axis=1, join="inner").dropna()
            if len(j) >= int(cfg["sigma_min_obs"]) + 1:
                rel = j["a"] - j["b"]
                rs = float(rel.iloc[-251:-1].std())
                if rs > 0 and not math.isnan(rs):
                    if rel.index[-1] == last and abs(float(rel.iloc[-1])) > k * rs:
                        add("rel_1d", float(rel.iloc[-1]), k * rs, {"sigmas": round(abs(float(rel.iloc[-1])) / rs, 2), "against": "its market"})
                    i5, i0 = _at(ix, last), _at(ix, s.index[-6]) if len(s) > 6 else None
                    if r5 is not None and i5 and i0:
                        d5 = r5 - (i5 / i0 - 1.0)
                        if abs(d5) > k * rs * math.sqrt(5):
                            add("rel_5d", d5, k * rs * math.sqrt(5), {"sigmas": round(abs(d5) / (rs * math.sqrt(5)), 2), "against": "its market"})
                        if d5 * 100.0 <= -float(cfg["rel_pts_5d"]):
                            add("rel_fall_5d", d5 * 100.0, -float(cfg["rel_pts_5d"]), {"points_behind_market": round(-d5 * 100.0, 1)})
    except Exception:
        return out
    return out


def _forecast_signal(con, market: str, key: str, price: float, day: date, root, cfg: dict) -> Optional[dict]:
    """The move since a stored live forecast (the hedge) was made, against that forecast's range (5% to 95%): outside it is a signal. Reads only forecasts made before `day`."""
    try:
        rows = con.execute("SELECT as_of, horizon_sessions, quantiles_json, base_price, matures FROM forecasts_s79 WHERE market=? AND source='live' AND forecaster='hedge' AND subject=? "
                           "AND as_of < ? AND matures >= ? AND base_price > 0 ORDER BY as_of DESC, horizon_sessions", [market, key, day, day]).fetchall()
    except Exception:
        return None
    best = None
    for as_of, h, qj, base, matures in rows:
        try:
            q = json.loads(qj)
            lo, hi = float(q[cfg["forecast_low"]]), float(q[cfg["forecast_high"]])
        except Exception:
            continue
        if market == "IN":
            try:
                from pflab.core import pick_score
                if pick_score.has_action(key, as_of, day, root):
                    continue
            except Exception:
                pass
        ret = price / float(base) - 1.0
        half = max((hi - lo) / 2.0, 1e-6)
        if ret > hi:
            sur = 1.0 + (ret - hi) / half
        elif ret < lo:
            sur = 1.0 + (lo - ret) / half
        else:
            continue
        if best is None or sur > best["surprise"]:
            best = {"signal": "outside_forecast", "value": ret, "threshold": hi if ret > hi else lo, "surprise": sur,
                    "detail": {"forecast_made_on": str(as_of), "horizon_sessions": int(h), "matures": str(matures), "range_5_95": [round(lo, 5), round(hi, 5)], "price": price, "px_day": str(day)}}
    return best


# --- the scope -------------------------------------------------------------------------------------------------------------------------------------------------------------

def _whole_inr(con, day: date, root=None) -> float:
    try:
        from pflab.us import wholebook
        v = float(wholebook.whole_book_inr(con, day, root)["whole_inr"])
        if v > 0:
            return v
    except Exception:
        pass
    try:
        from pflab.paper import book
        return float(book.holdings(con, day)["value"] or 0.0)
    except Exception:
        return 0.0


def _us_held(con, day: date, root=None) -> List[dict]:
    """The US sub-book's holdings in rupees at the last close and the stated rate: [{isin, symbol, qty, value_inr}]."""
    out: List[dict] = []
    try:
        from pflab.us import book as ub, data as ud, fx as ufx, instruments as uins
        if ub.account(con) is None:
            return out
        fx = ufx.rate_for(con, day, root, max_age_days=10)
        for key, q in ub.positions(con, day).items():
            if q <= EPS:
                continue
            sym = uins.symbol_of(con, key) or key
            bar = ud.last_on_or_before(ud.bars(sym, root), day)
            px = bar["close"] if bar else None
            out.append({"isin": key, "symbol": sym, "qty": q, "value_inr": (q * px * fx["rate"]) if (px and fx) else 0.0})
    except Exception:
        return out
    return out


def _held_in(con, day: date) -> List[dict]:
    try:
        from pflab.paper import book
        return [{"isin": r["isin"], "symbol": r["symbol"] or r["isin"], "value_inr": float(r["value"] or 0.0), "asset_class": r["asset_class"]} for r in book.holdings(con, day)["rows"]
                if (r["value"] or 0.0) > 0]
    except Exception:
        return []


def _table(con, name: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name=?", [name]).fetchone()[0])


def scope(con, day: date, *, market: Optional[str] = None, root=None, held_only: bool = False) -> List[dict]:
    """What the watch looks at on `day`: the book's holdings (India and the US sub-book), the picks, the ideas it skipped and the names it screened (A67). Each:
    {name, isin, symbol, market, exposure_inr, exposure_pct, why, held, base_day, base_why, ref}. A name the book does not hold carries the labelled stand-in exposure."""
    cfg = settings()
    whole = _whole_inr(con, day, root)
    standin = float(cfg["standin_weight"]) * whole
    out: Dict[tuple, dict] = {}

    def put(mk: str, isin: str, symbol: str, why: str, value: float, held: bool, **extra):
        k = (mk, isin)
        e = out.get(k)
        if e is None:
            e = out[k] = {"name": symbol or isin, "isin": isin, "symbol": symbol or isin, "market": mk, "exposure_inr": 0.0, "exposure_pct": 0.0, "why": [], "held": False,
                          "base_day": None, "base_why": None, "ref": None, "exposure_basis": "held"}
        if held:
            e["held"], e["exposure_inr"], e["exposure_basis"] = True, max(e["exposure_inr"], value), "held"
        if why not in e["why"]:
            e["why"].append(why)
        for kk, vv in extra.items():
            if vv is not None and (e.get(kk) is None or kk in ("base_day", "base_why", "ref") and why.startswith("skipped")):
                e[kk] = vv

    if market in (None, "IN"):
        for r in _held_in(con, day):
            put("IN", r["isin"], r["symbol"], "held", r["value_inr"], True)
    if market in (None, "US"):
        for r in _us_held(con, day, root):
            put("US", r["isin"], r["symbol"], "held (US sub-book)", r["value_inr"], True)
    if not held_only:
        if _table(con, "picks_s83"):
            for mk, isin, sym, st in con.execute("SELECT market, isin, symbol, state FROM picks_s83 WHERE state IN ('proposed','buying','held') AND proposed_on <= ?", [day]).fetchall():
                if market in (None, mk or "IN"):
                    put(mk or "IN", isin, sym, "pick" + ("" if st == "held" else " (named, not yet held)"), 0.0, False)
        if _table(con, "skips_s83"):
            lo = day - timedelta(days=int(cfg["skip_lookback_days"]))
            for mk, isin, sym, why, on, sid in con.execute("SELECT market, isin, symbol, why, skipped_on, skip_id FROM skips_s83 WHERE skipped_on <= ? AND skipped_on >= ? ORDER BY skipped_on, skip_id", [day, lo]).fetchall():
                if market in (None, mk or "IN"):
                    put(mk or "IN", isin, sym, "skipped idea", 0.0, False, base_day=on, base_why=(why or "")[:300], ref=f"skip:{sid}")
        if _table(con, "screen_log_s83"):
            lo = day - timedelta(days=int(cfg["screen_lookback_days"]))
            first: Dict[tuple, date] = {}
            for mk, d0, sj in con.execute("SELECT market, day, symbols_json FROM screen_log_s83 WHERE day <= ? AND day >= ? ORDER BY day, log_id", [day, lo]).fetchall():
                try:
                    syms = json.loads(sj or "[]")
                except Exception:
                    syms = []
                for s in syms:
                    first.setdefault((mk or "IN", str(s).upper()), d0)
            for (mk, sym), d0 in first.items():
                if market not in (None, mk):
                    continue
                r = con.execute("SELECT isin FROM instruments WHERE upper(symbol)=? ORDER BY listed DESC NULLS LAST LIMIT 1", [sym]).fetchone()
                if r:
                    put(mk, r[0], sym, "screened name", 0.0, False, base_day=d0, base_why=f"looked at in a screen on {d0}", ref=f"screen:{mk}:{sym}")
    rows = []
    for e in out.values():
        if not e["held"]:
            e["exposure_inr"], e["exposure_basis"] = standin, f"stand-in {float(cfg['standin_weight']):.1%} of the whole book (index weights are not stored)"
        e["exposure_pct"] = e["exposure_inr"] / whole if whole > 0 else 0.0
        e["why"] = "; ".join(e["why"])
        rows.append(e)
    rows.sort(key=lambda e: (-e["exposure_inr"], e["symbol"] or ""))
    if held_only:
        return [e for e in rows if e["held"]]
    return rows


# --- signals from the store -------------------------------------------------------------------------------------------------------------------------------------------------

def _thesis_signals(con, entries: List[dict], day: date, until: datetime, cfg: dict) -> List[dict]:
    try:
        from pflab.kg import events
        since = datetime.combine(day - timedelta(days=int(cfg["event_lookback_days"])), time(0, 0))
        evs = events.material_events(con, [e["isin"] for e in entries if e["market"] == "IN"], since, until)
    except Exception:
        return []
    by = {e["isin"]: e for e in entries}
    out = []
    for ev in evs:
        e = by.get(ev["isin"])
        if e is None or ev.get("ts") is None or ev["ts"] > until:
            continue
        ref = f"{ev['source']}:{ev['ref']}"
        out.append({"entry": e, "signal": "thesis_event", "value": SEV_SURPRISE.get(ev["severity"], 1.0), "threshold": 1.0, "surprise": SEV_SURPRISE.get(ev["severity"], 1.0),
                    "detail": {"ref": ref, "kind": ev["kind"], "severity": ev["severity"], "event_ts": str(ev["ts"]), "text": (ev.get("text") or "")[:200], "px_day": str(day)}, "dedupe_ref": ref})
    return out


def _news_signals(con, entries: List[dict], day: date, until: datetime, cfg: dict) -> List[dict]:
    """Linked news today against the name's own 60-day norm (news only: a routine filing is not news)."""
    isins = [e["isin"] for e in entries if e["market"] == "IN"]
    if not isins or not _table(con, "kg2_event"):
        return []
    n = int(cfg["news_norm_days"])
    ph = ",".join("?" * len(isins))
    try:
        rows = con.execute(f"SELECT isin, CAST(ts AS DATE) d, count(*) FROM kg2_event WHERE isin IN ({ph}) AND source <> 'bse_announcement' AND ts <= ? AND CAST(ts AS DATE) >= ? GROUP BY 1, 2",
                           [*isins, until, day - timedelta(days=n)]).fetchall()
    except Exception:
        return []
    cnt: Dict[str, Dict[date, int]] = {}
    for i, d, c in rows:
        cnt.setdefault(i, {})[d] = int(c)
    by = {e["isin"]: e for e in entries}
    out = []
    for i, per in cnt.items():
        today = per.get(day, 0)
        norm = sum(c for d, c in per.items() if d < day) / float(n)
        thr = max(float(cfg["news_burst_x"]) * norm, float(cfg["news_burst_min"]))
        if today >= thr:
            out.append({"entry": by[i], "signal": "news_burst", "value": float(today), "threshold": thr, "surprise": today / thr,
                        "detail": {"items_today": today, "norm_per_day": round(norm, 3), "days": n, "px_day": str(day)}})
    return out


def _storyline_signals(con, day: date, market: str, cfg: dict, equity_inr: float, whole: float) -> List[dict]:
    if not _table(con, "storyline_prob_s80"):
        return []
    out = []
    try:
        sl = con.execute("SELECT storyline_id, claim FROM storylines_s80 WHERE market=? AND status='open' AND opened_on <= ?", [market, day]).fetchall()
    except Exception:
        return []
    for sid, claim in sl:
        rows = con.execute("SELECT prob_date, probability FROM storyline_prob_s80 WHERE storyline_id=? AND prob_date <= ? ORDER BY prob_date DESC LIMIT 2", [sid, day]).fetchall()
        if len(rows) < 2 or rows[0][0] != day:
            continue
        jump = (float(rows[0][1]) - float(rows[1][1])) * 100.0
        if abs(jump) < float(cfg["storyline_jump_pts"]):
            continue
        expo = 0.0
        try:
            for isin, x in con.execute("SELECT isin, exposure FROM storyline_exposure_s80 WHERE storyline_id=?", [sid]).fetchall():
                for h in _held_in(con, day):
                    if h["isin"] == isin:
                        expo += abs(float(x or 0.0)) * h["value_inr"]
        except Exception:
            pass
        e = {"name": f"storyline {sid}", "isin": f"STORY:{sid}", "symbol": f"storyline {sid}", "market": market, "exposure_inr": expo, "exposure_pct": expo / whole if whole > 0 else 0.0, "why": "storyline", "held": True}
        out.append({"entry": e, "signal": "storyline_jump", "value": jump, "threshold": float(cfg["storyline_jump_pts"]), "surprise": abs(jump) / float(cfg["storyline_jump_pts"]),
                    "detail": {"storyline_id": int(sid), "claim": (claim or "")[:200], "from": round(float(rows[1][1]), 4), "to": round(float(rows[0][1]), 4), "px_day": str(day)}})
    return out


def _market_signal(ix: Optional[pd.Series], market: str, day: date, cfg: dict, equity_inr: float, whole: float) -> List[dict]:
    if ix is None:
        return []
    s = ix[ix.index <= pd.Timestamp(day)]
    if len(s) < 25 or (pd.Timestamp(day) - s.index[-1]).days > int(cfg["max_stale_days"]):
        return []
    ret = float(s.iloc[-1] / s.iloc[-21] - 1.0)
    if ret > -float(cfg["market_down_20d"]):
        return []
    expo = equity_inr * float(cfg["market_exposure_factor"])
    e = {"name": "the market", "isin": f"MARKET:{market}", "symbol": "Nifty 500" if market == "IN" else "S&P 500", "market": market, "exposure_inr": expo,
         "exposure_pct": expo / whole if whole > 0 else 0.0, "why": "market", "held": True}
    return [{"entry": e, "signal": "market_down_20d", "value": ret, "threshold": -float(cfg["market_down_20d"]), "surprise": ret / -float(cfg["market_down_20d"]),
             "detail": {"px_day": str(s.index[-1].date()), "index_level": float(s.iloc[-1])}}]


def _macro_signals(day: date, now: datetime, cfg: dict, equity_inr: float, whole: float, root) -> List[dict]:
    """The overnight shocks: the US indices, the dollar-rupee, crude, each beyond `move_sigmas` of its usual daily move. Only rows dated on or before `day`."""
    out = []
    try:
        from pflab.story import series
    except Exception:
        return out
    for key, label in MACRO:
        try:
            s = series.load(key, root)
            if s is None:
                continue
            s = s[s.index <= pd.Timestamp(day)]
            if len(s) < int(cfg["min_history"]) or (pd.Timestamp(day) - s.index[-1]).days > int(cfg["max_stale_days"]):
                continue
            r = s.pct_change().dropna()
            base = r.iloc[-251:-1]
            if len(base) < int(cfg["sigma_min_obs"]):
                continue
            sigma, r1 = float(base.std()), float(r.iloc[-1])
            if not sigma > 0 or abs(r1) <= float(cfg["move_sigmas"]) * sigma:
                continue
            expo = equity_inr * float(cfg["market_exposure_factor"])
            e = {"name": label, "isin": f"MACRO:{key}", "symbol": label, "market": "US", "exposure_inr": expo, "exposure_pct": expo / whole if whole > 0 else 0.0, "why": "overnight", "held": True}
            thr = float(cfg["move_sigmas"]) * sigma
            out.append({"entry": e, "signal": "overnight_shock", "value": r1, "threshold": thr, "surprise": abs(r1) / thr,
                        "detail": {"series": key, "px_day": str(s.index[-1].date()), "sigmas": round(abs(r1) / sigma, 2)}})
        except Exception:
            continue
    return out


def _missed_signals(con, entries: List[dict], day: date, market: str, cfg: dict, root) -> List[dict]:
    """A name the system looked at and passed on, now `missed_run_pts` or more ahead of its index since that day. Held names and active picks are not 'passed on'."""
    try:
        from pflab.core import pick_score
    except Exception:
        return []
    ix = _index(market, root)
    if ix is None:
        return []
    cool = day - timedelta(days=int(cfg["missed_cooldown_days"]))
    out = []
    n = 0
    for e in entries:
        if e["held"] or e["market"] != market or not e.get("base_day") or "pick" in e["why"]:
            continue
        n += 1
        if n > int(cfg["missed_max_names"]):
            break
        d0 = e["base_day"]
        if d0 >= day or con.execute("SELECT 1 FROM think_signals_s84 WHERE isin=? AND signal='missed_run' AND day >= ? LIMIT 1", [e["isin"], cool]).fetchone():
            continue
        try:
            if market == "IN":                                   # the panel's adjusted history joined to the store's (the store alone holds only the last weeks): price return, split-safe
                h = _history(con, "IN", e["isin"], e["symbol"], day, root, cfg, full=True)
                a = None if h is None else h[h.index <= pd.Timestamp(d0)]
                s = None if (h is None or a is None or not len(a) or (pd.Timestamp(d0) - a.index[-1]).days > 10 or h.index[-1].date() != day) else {"ret": float(h.iloc[-1] / a.iloc[-1] - 1.0)}
            else:
                s = pick_score.stock_return_us(e["symbol"], d0, day, root)
            ir = pick_score.series_return(ix, d0, day)
        except Exception:
            continue
        if s is None or ir is None:
            continue
        pts = (float(s["ret"]) - ir) * 100.0
        if pts >= float(cfg["missed_run_pts"]):
            out.append({"entry": e, "signal": "missed_run", "value": pts, "threshold": float(cfg["missed_run_pts"]), "surprise": pts / float(cfg["missed_run_pts"]),
                        "detail": {"passed_on": str(d0), "why_passed": e.get("base_why"), "ref": e.get("ref"), "name_return_pct": round(float(s["ret"]) * 100, 1),
                                   "index_return_pct": round(ir * 100, 1), "return_basis": "price only against a total-return index" if market == "IN" else "price (dividends in) in dollars", "points_ahead": round(pts, 1), "px_day": str(day),
                                   "question": "was the reason for passing wrong, or has only the price changed?"}})
    return out


# --- one pass ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def _say(sym: str, x: dict) -> str:
    v, d = x["value"], x["detail"]
    s = x["signal"]
    if s in ("move_1d", "rel_1d"):
        return f"{sym} moved {v:+.1%} in a day{' against its market' if s == 'rel_1d' else ''} ({d.get('sigmas', 0):.1f} times its usual daily move)"
    if s in ("move_5d", "rel_5d"):
        return f"{sym} moved {v:+.1%} in 5 sessions{' against its market' if s == 'rel_5d' else ''} ({d.get('sigmas', 0):.1f} times its usual 5-day move)"
    if s == "fall_10d":
        return f"{sym} fell {-v:.0%} in 10 sessions"
    if s == "rel_fall_5d":
        return f"{sym} is {-v:.0f} points behind its market over 5 sessions"
    if s == "outside_forecast":
        return f"{sym} is {v:+.1%} since its forecast, outside the forecast's range"
    if s == "market_down_20d":
        return f"{sym} is down {-v:.0%} in 20 sessions"
    if s == "news_burst":
        return f"{sym} has {int(v)} news items today against a normal {d['norm_per_day']:.1f} a day"
    if s == "thesis_event":
        return f"{sym}: {d['kind'].replace('_', ' ')} ({d['severity']}): {d.get('text', '')[:90]}"
    if s == "storyline_jump":
        return f"{sym} moved {v:+.0f} points in a day: {d.get('claim', '')[:90]}"
    if s == "overnight_shock":
        return f"{sym} moved {v:+.1%} overnight ({d.get('sigmas', 0):.1f} times its usual daily move)"
    if s == "missed_run":
        return f"{sym}, passed on {d['passed_on']}, is {v:.0f} points ahead of its index since (passed on because: {(d.get('why_passed') or 'no reason stored')[:90]})"
    return f"{sym}: {s}"


def _commit(con, sig_now: datetime, raws: List[dict]) -> dict:
    """Store every new signal once (name, signal, day), join open cases, open the day's cap of new cases (largest score first), store the rest as noticed."""
    cfg = settings()
    day = sig_now.date()
    res = {"signals": [], "cases_opened": [], "joined": [], "cases_noticed": [], "noticed": 0}
    fresh: Dict[str, List[tuple]] = {}
    ent: Dict[str, dict] = {}
    for x in sorted(raws, key=lambda x: -x["surprise"] * x["entry"]["exposure_inr"]):
        e = x["entry"]
        ref = x.get("dedupe_ref")
        if ref:
            if con.execute("SELECT 1 FROM think_signals_s84 WHERE isin=? AND signal=? AND detail_json LIKE ? LIMIT 1", [e["isin"], x["signal"], f'%"ref": "{ref}"%']).fetchone():
                continue
        elif con.execute("SELECT 1 FROM think_signals_s84 WHERE isin=? AND signal=? AND day=? LIMIT 1", [e["isin"], x["signal"], day]).fetchone():
            continue
        det = dict(x["detail"])
        det.update({"why_in_scope": e.get("why"), "exposure_basis": e.get("exposure_basis", "held")})
        score = x["surprise"] * e["exposure_inr"]
        sid = cases.record_signal(con, sig_now, market=e["market"], isin=e["isin"], symbol=e["symbol"], signal=x["signal"], value=x["value"], threshold=x["threshold"], surprise=x["surprise"],
                                  exposure_inr=e["exposure_inr"], score=score, detail=det)
        res["signals"].append(sid)
        fresh.setdefault(e["isin"], []).append((sid, x, score))
        ent[e["isin"]] = e
    cands = []
    for isin, items in fresh.items():
        e = ent[isin]
        top = max(items, key=lambda t: t[2])
        oc = cases.case_for(con, isin)
        if oc is not None:
            for sid, _x, sc in items:
                cases.set_signal(con, sid, case_id=oc["case_id"], status="joined")
            if top[2] > float(oc.get("score") or 0.0):
                cases.set_case(con, oc["case_id"], score=top[2], exposure_inr=e["exposure_inr"], exposure_pct=e["exposure_pct"])
            if oc["case_id"] not in res["joined"]:
                res["joined"].append(oc["case_id"])
            continue
        nc = con.execute("SELECT case_id FROM think_cases_s84 WHERE isin=? AND state='noticed' AND opened_on=? ORDER BY case_id LIMIT 1", [isin, day]).fetchone()
        if nc:
            for sid, _x, sc in items:
                cases.set_signal(con, sid, case_id=nc[0], status="not_examined")
            continue
        cands.append((top[2], isin, items))
    cands.sort(key=lambda t: -t[0])
    room = max(0, int(cfg["max_cases_per_day"]) - cases.cases_opened_on(con, day))
    for k, (score, isin, items) in enumerate(cands):
        e = ent[isin]
        items.sort(key=lambda t: -t[2])
        title = "; ".join(_say(e["symbol"], x) for _sid, x, _sc in items[:2])
        kind = GROUP.get(items[0][1]["signal"], "move")
        ids = [sid for sid, _x, _sc in items]
        if k < room:
            res["cases_opened"].append(cases.open_case(con, sig_now, market=e["market"], kind=kind, isin=e["isin"], symbol=e["symbol"], title=title, exposure_inr=e["exposure_inr"],
                                                       exposure_pct=e["exposure_pct"], score=score, opened_by="watch", signal_ids=ids, state="open", names=[e["symbol"]]))
        else:
            cid = cases.open_case(con, sig_now, market=e["market"], kind=kind, isin=e["isin"], symbol=e["symbol"], title=title, exposure_inr=e["exposure_inr"], exposure_pct=e["exposure_pct"],
                                  score=score, opened_by="watch", signal_ids=ids, state="noticed", names=[e["symbol"]])
            for sid in ids:
                cases.set_signal(con, sid, status="not_examined")
            res["cases_noticed"].append(cid)
            res["noticed"] += 1
    return res


def _equity_inr(entries: List[dict], market: str) -> float:
    return float(sum(e["exposure_inr"] for e in entries if e["held"] and e["market"] == market))


def _india_pass(con, sig_now: datetime, day: date, until: datetime, *, quotes: Optional[dict], light: bool, root, cfg: dict) -> dict:
    entries = scope(con, day, market="IN", root=root, held_only=light)
    whole = _whole_inr(con, day, root)
    ix = _index("IN", root)
    raws: List[dict] = []
    for e in entries:
        if e["isin"].startswith(("MARKET:", "MACRO:", "STORY:")):
            continue
        if not e["held"] and "pick" not in e["why"]:
            continue                                                       # skipped and screened names are watched for a missed run only, not for every wobble
        s = _history(con, "IN", e["isin"], e["symbol"], day, root, cfg)
        if s is None:
            continue
        live = None if not quotes else (quotes.get(e["isin"]) or quotes.get(e["symbol"]))
        if live and live > 0:
            s = s.copy()
            s.loc[pd.Timestamp(day)] = float(live)
            s = s.sort_index()
        if s.index[-1].date() != day:
            continue                                                       # the close of `day` is not in yet (or the name did not trade): no signal on an older bar, the close is rerun when it arrives
        sigs = _price_signals(s, ix, cfg, light)
        fs = _forecast_signal(con, "IN", e["isin"], float(s.iloc[-1]), day, root, cfg) if e["held"] else None
        if fs:
            sigs.append(fs)
        raws += [{**x, "entry": e} for x in sigs]
    held = [e for e in entries if e["held"]]
    raws += _thesis_signals(con, held, day, until, cfg)
    if not light:
        raws += _news_signals(con, held, day, until, cfg)
        raws += _market_signal(ix, "IN", day, cfg, _equity_inr(entries, "IN"), whole)
        raws += _storyline_signals(con, day, "IN", cfg, 0.0, whole)
        raws += _missed_signals(con, entries, day, "IN", cfg, root)
    return _commit(con, sig_now, raws)


def _us_pass(con, sig_now: datetime, s_day: date, until: datetime, *, quotes: Optional[dict], root, cfg: dict) -> dict:
    """`s_day`: the US session just closed. `quotes` (symbol -> price), when given, are the after-hours prices and stand as one more bar after the close."""
    entries = scope(con, s_day, market="US", root=root)
    whole = _whole_inr(con, s_day, root)
    ix = _index("US", root)
    raws: List[dict] = []
    for e in entries:
        if not e["held"] and "pick" not in e["why"]:
            continue
        s = _history(con, "US", e["isin"], e["symbol"], s_day, root, cfg)
        if s is None or s.index[-1].date() != s_day:
            continue                                                       # the bar of the session just closed is not in yet: no signal on an older bar
        live = None if not quotes else (quotes.get(e["symbol"]) or quotes.get(e["isin"]))
        extra = {}
        if live and live > 0:
            s = s.copy()
            s.loc[pd.Timestamp(s_day) + pd.Timedelta(days=1)] = float(live)
            s = s.sort_index()
            extra = {"after_hours_quote": float(live)}
        sigs = _price_signals(s, ix, cfg)
        raws += [{**x, "detail": {**x["detail"], **extra}, "entry": e} for x in sigs]
        if e["held"]:
            fs = _forecast_signal(con, "US", e["isin"], float(s.iloc[-1]), s_day, root, cfg)
            if fs:
                raws.append({**fs, "entry": e})
    us_eq = _equity_inr(entries, "US")
    raws += _market_signal(ix, "US", s_day, cfg, us_eq, whole)
    raws += _macro_signals(s_day, sig_now, cfg, us_eq + _equity_inr(scope(con, s_day, market="IN", root=root, held_only=True), "IN"), whole, root)
    raws += _storyline_signals(con, sig_now.date(), "US", cfg, 0.0, whole)
    raws += _missed_signals(con, entries, s_day, "US", cfg, root)
    return _commit(con, sig_now, raws)


# --- the runs ---------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _log_run(con, now: datetime, mode: str, market: str, day: date, res: dict) -> None:
    con.execute("INSERT OR REPLACE INTO think_watch_runs_s84 VALUES (?,?,?,?,?,?,?,?)", [f"{mode}:{market}:{day}", mode, market, day, now, len(res["signals"]), len(res["cases_opened"]), res["noticed"]])


def _last_run(con, mode: str, market: str) -> Optional[date]:
    try:
        r = con.execute("SELECT max(day) FROM think_watch_runs_s84 WHERE mode=? AND market=?", [mode, market]).fetchone()
    except Exception:
        return None
    return r[0] if r and r[0] else None


def _merge(into: dict, res: dict) -> dict:
    for k in ("signals", "cases_opened", "joined", "cases_noticed"):
        into.setdefault(k, [])
        into[k] += [x for x in res.get(k, []) if x not in into[k]]
    into["noticed"] = into.get("noticed", 0) + res.get("noticed", 0)
    return into


def _india_close(con, now: datetime, d: date, root, cfg: dict) -> dict:
    sig_now = now if d == now.date() else datetime.combine(d, time(15, 45))
    until = now if d == now.date() else datetime.combine(d, time(23, 59, 59))
    res = _india_pass(con, sig_now, d, until, quotes=None, light=False, root=root, cfg=cfg)
    ready = bool(con.execute("SELECT count(*) FROM prices WHERE date=? AND source='nse_bhavcopy'", [d]).fetchone()[0])
    if ready or (now.date() - d).days > 3:                                  # a close whose prices have not arrived is not logged as done: the next catch-up runs it again
        _log_run(con, now, "close", "IN", d, res)
    else:
        res["waiting_for_prices"] = str(d)
    return res


def _us_morning(con, now: datetime, s: date, root, cfg: dict, quotes: Optional[dict] = None) -> dict:
    """The IST morning that follows the US session `s`."""
    try:
        from pflab.us import clock as uc
        c = uc.close_ist(s)
        ist_day = c.date() if c else s + timedelta(days=1)
    except Exception:
        ist_day = s + timedelta(days=1)
    live = ist_day >= now.date()
    sig_now = now if live else datetime.combine(ist_day, time(8, 0))
    res = _us_pass(con, sig_now, s, now if live else datetime.combine(ist_day, time(8, 0)), quotes=quotes if live else None, root=root, cfg=cfg)
    _log_run(con, now, "us_morning", "US", s, res)
    return res


def _missed_days(con, mode: str, market: str, upto: date, cfg: dict) -> List[date]:
    """The sessions after the last logged pass up to `upto`, each once (the newest `catchup_max_sessions`); with no earlier pass, only `upto`."""
    from pflab import markets
    last = _last_run(con, mode, market)
    if last is None:
        return [upto]
    days = markets.get(market).sessions_between(last + timedelta(days=1), upto)
    return days[-int(cfg["catchup_max_sessions"]):]


def run(con, now: datetime, *, mode: str, quotes: Optional[dict] = None, root=None) -> dict:
    """The watch. mode in 'session' | 'close' | 'us_morning' | 'catchup'. Never raises: a failing signal source is skipped and said so in `errors`."""
    from pflab import markets
    cfg = settings()
    out = {"signals": [], "cases_opened": [], "joined": [], "noticed": 0, "cases_noticed": [], "mode": mode, "errors": []}
    if mode not in ("session", "close", "us_morning", "catchup"):
        raise ValueError(f"unknown watch mode {mode!r}")
    if not _on():
        out["off"] = True
        return out
    if cfg.get("wide_watch"):
        out["wide_watch"] = "on in config but not built (S85): ignored"
    try:
        if mode == "session":
            if not quotes:
                out["note"] = "no live quotes: nothing to watch in the session"
                return out
            _merge(out, _india_pass(con, now, now.date(), now, quotes=quotes, light=True, root=root, cfg=cfg))
        elif mode == "close":
            _merge(out, _india_close(con, now, markets.get("IN").session_closed_by(now), root, cfg))
        elif mode == "us_morning":
            from pflab.us import clock as uc
            _merge(out, _us_morning(con, now, uc.session_closed_by(now), root, cfg, quotes))
        else:
            for d in _missed_days(con, "close", "IN", markets.get("IN").session_closed_by(now), cfg):
                _merge(out, _india_close(con, now, d, root, cfg))
            from pflab.us import clock as uc
            for s in _missed_days(con, "us_morning", "US", uc.session_closed_by(now), cfg):
                _merge(out, _us_morning(con, now, s, root, cfg))
    except Exception as ex:                                   # the watch never stops the loop that called it
        out["errors"].append(repr(ex)[:300])
    return out


# --- what Today and the reports show ---------------------------------------------------------------------------------------------------------------------------------------

def watch_text(con, day: date) -> dict:
    """The watch's day in plain words for Today, the 15:45 report and Telegram (a text block, JSON-able): how many things it noticed, how many cases it opened, how many it only logged."""
    sig = cases.signals(con, day=day)
    opened = cases.cases_opened_on(con, day)
    noticed = int(con.execute("SELECT count(*) FROM think_cases_s84 WHERE opened_on=? AND state='noticed'", [day]).fetchone()[0])
    joined = len([s for s in sig if s["status"] == "joined"])
    by: Dict[str, int] = {}
    for s in sig:
        by[s["signal"]] = by.get(s["signal"], 0) + 1
    if not sig:
        text = "The watch noticed nothing out of the ordinary today."
    else:
        text = (f"The watch noticed {len(sig)} thing{'s' if len(sig) != 1 else ''} today: {opened} case{'s' if opened != 1 else ''} opened to think through"
                + (f", {joined} added to a case already open" if joined else "") + (f", {noticed} only logged (the day's limit of {int(settings()['max_cases_per_day'])} cases was reached)" if noticed else "") + ".")
    return {"day": str(day), "signals": len(sig), "cases_opened": opened, "joined": joined, "noticed_not_examined": noticed, "by_signal": by, "text": text}


def missed_runs(con) -> List[dict]:
    """Every missed-run signal ever stored (the scorecard's 'skips that ran' reads these): name, the day it was passed on, why, how far ahead it is."""
    out = []
    for s in cases.signals(con):
        if s["signal"] == "missed_run":
            d = json.loads(s["detail_json"] or "{}")
            out.append({"signal_id": s["signal_id"], "case_id": s["case_id"], "day": s["day_s"], "market": s["market"], "isin": s["isin"], "symbol": s["symbol"], "passed_on": d.get("passed_on"),
                        "why_passed": d.get("why_passed"), "points_ahead": d.get("points_ahead")})
    return out
