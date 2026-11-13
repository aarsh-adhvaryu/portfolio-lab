"""S85 L1 (1): the WIDE WATCH. T1's NOTICE looks at what the book holds, what it picked and what it passed on. The wide watch looks at the whole of the Nifty 500 and the S&P 500 members too, with
the cheap signals only (code, no model, no cost): a move beyond `move_sigmas` of its usual move (1 day, 5 days), a fall of `fall_pct_10d` in 10 sessions, a move against its index (1 day, 5 days, the
fall against it), a run of `wide_run_pts` points ahead of its index in 20 sessions (`wide_run_20d`: a missed-run style move on a name nobody looked at), a thesis-break event in the graph, a news burst.

    run_pass(con, sig_now, day, until, market, *, root=None) -> {"signals", "cases_opened", "joined", "noticed", "cases_noticed", ...}   one pass (the India close, the US morning); idempotent per
                                                                  (name, signal, day); the hook in `watch._india_close` and `watch._us_morning` calls it behind `[think] wide_watch`
    universe(con, day, market, root=None) -> DataFrame           the names it looks at: index members less what T1 already watches (held, picks), with a weight (a PROXY, `exposure.py`)

The score is what T1 uses, surprise x exposure, but the exposure of a wide name is a labelled RANKING weight: what the book holds of it through funds (`exposure.via_funds`) plus its index weight x
`wide_index_factor` (5%) of the whole book. So a wide name seldom outranks a held one (a held name's exposure is its shares, plus funds). Signals are stored with `"wide": true` in their detail
(only the top `wide_store_top` of a pass, by score, plus every signal of a name that has a case open). Only the top `wide_cases_per_day` (default 1) NEW cases a day come from here, and only when the
day has room under `max_cases_per_day` or the name scores above the weakest case of the day that nobody has thought through yet (that case goes back to "noticed"); the daily cap stays the cap.
Point in time: closes dated on or before `day`; a name whose last bar is not `day` is skipped (a stale bar gives no signal).
"""
from __future__ import annotations

import json
import math
import time as _time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab import think
from pflab.think import cases, exposure, watch

WIDE_DEFAULTS = {
    "wide_watch": False,                # the switch; configs/core.toml [think] turns it on
    "wide_cases_per_day": 1,            # at most this many NEW cases a day come from the wide watch
    "wide_store_top": 60,               # a pass stores its top-scored signals only (the rest are counted)
    "wide_index_factor": 0.05,          # a wide name's ranking exposure: its index weight x this share of the whole book (a labelled ranking weight, not a rupee claim)
    "wide_run_pts": 20.0, "wide_run_sessions": 20,
}
INDEX_OF = {"IN": "NIFTY500", "US": "SP500"}
LABEL = {"IN": "Nifty 500 member", "US": "S&P 500 member"}
WIDE_GROUP = {"wide_run_20d": "missed_run"}          # the case kind of a wide-only signal (watch.GROUP knows the others)


def settings() -> dict:
    out = dict(WIDE_DEFAULTS)
    out.update(watch.settings())
    for k, v in WIDE_DEFAULTS.items():                # a config line wins over the default; watch.settings() already carries wide_watch
        out.setdefault(k, v)
    return out


# --- the universe ----------------------------------------------------------------------------------------------------------------------------------------------------------------

def universe(con, day: date, market: str, root=None) -> pd.DataFrame:
    """[isin, symbol, weight] of the index members (Nifty 500 / S&P 500) on `day`, less the names T1 already watches (held and picked). Empty when the member data is missing."""
    w = exposure.index_weights(INDEX_OF[market], day, root, con)
    if w is None or not len(w):
        return pd.DataFrame(columns=["isin", "symbol", "weight"])
    skip = set()
    for e in watch.scope(con, day, market=market, root=root):
        if e["held"] or "pick" in e["why"]:
            skip.add(e["isin"])
    w = w[~w["isin"].isin(skip)]
    return w[["isin", "symbol", "weight"]].reset_index(drop=True)


# --- the closes (many names at once) ---------------------------------------------------------------------------------------------------------------------------------------------

def _panel_end(root: Path) -> Optional[date]:
    try:
        from pflab import _duck
        p = Path(root) / "panel" / "prices.parquet"
        d = _duck.sql(f"SELECT max(date) AS d FROM '{p.as_posix()}'").df()["d"].iloc[0]
        return None if pd.isna(d) else pd.Timestamp(d).date()
    except Exception:
        return None


def _split_factors(root: Path, isins: List[str], after: Optional[date]) -> Dict[str, list]:
    """isin -> [(ex_date, factor)] for the splits and bonuses that went ex AFTER the panel's last date (the panel's own closes already carry the earlier ones)."""
    out: Dict[str, list] = {}
    try:
        f = pd.read_parquet(Path(root) / "corporate_actions" / "factors.parquet", filters=[("isin", "in", list(isins))])
    except Exception:
        return out
    f = f[f["factor"] > 0]
    f = f.assign(ex_date=pd.to_datetime(f["ex_date"]).dt.date)
    for r in f.itertuples(index=False):
        if abs(float(r.factor) - 1.0) > 1e-9 and (after is None or r.ex_date > after):
            out.setdefault(r.isin, []).append((r.ex_date, float(r.factor)))
    return out


def india_series(con, root: Path, isins: List[str], day: date) -> Dict[str, pd.Series]:
    """Split-safe closes up to `day` of many India names: `lab.screen.india_closes` (the panel joined to the store) and the splits after the panel's end."""
    from pflab.lab import screen
    raw = screen.india_closes(con, Path(root), isins, day, days=440)
    fac = _split_factors(root, isins, _panel_end(root))
    out = {}
    for i, s in raw.items():
        s = s.copy()
        s.index = pd.to_datetime(s.index).normalize()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        s = s[(s.index <= pd.Timestamp(day)) & (s > 0)]
        for ex, f in fac.get(i, []):
            s[s.index < pd.Timestamp(ex)] *= f
        out[i] = s
    return out


def us_series(root: Path, symbols: List[str], day: date) -> Dict[str, pd.Series]:
    """Adjusted closes up to `day` of many US names (the panel `data/us/prices.parquet`, dividends in)."""
    from pflab import _duck
    p = Path(root) / "us" / "prices.parquet"
    out: Dict[str, pd.Series] = {}
    if not p.exists() or not symbols:
        return out
    lo = day - timedelta(days=440)
    lst = ",".join(f"'{s}'" for s in symbols)
    d = _duck.sql(f"SELECT symbol, date, adj_close FROM '{p.as_posix()}' WHERE symbol IN ({lst}) AND date >= DATE '{lo}' AND date <= DATE '{day}' AND adj_close > 0 ORDER BY date").df()
    for sym, g in d.groupby("symbol"):
        out[sym] = pd.Series(g["adj_close"].to_numpy(float), index=pd.to_datetime(g["date"]))
    return out


def _series(con, root, market: str, uni: pd.DataFrame, day: date) -> Dict[str, pd.Series]:
    """isin -> closes. Tests replace this function."""
    if market == "US":
        by_sym = us_series(root, list(uni["symbol"]), day)
        sym_of = dict(zip(uni["isin"], uni["symbol"]))
        return {i: by_sym[s] for i, s in sym_of.items() if s in by_sym}
    return india_series(con, root, list(uni["isin"]), day)


# --- the signals ------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _run_signal(s: pd.Series, ix: Optional[pd.Series], cfg: dict) -> Optional[dict]:
    """The name now `wide_run_pts` points ahead of its index over `wide_run_sessions` sessions (price against the index's level): a run nobody looked at."""
    n = int(cfg["wide_run_sessions"])
    if ix is None or len(s) <= n + 1:
        return None
    last = s.index[-1]
    i1, i0 = watch._at(ix, last), watch._at(ix, s.index[-1 - n])
    if not i1 or not i0:
        return None
    pts = (float(s.iloc[-1]) / float(s.iloc[-1 - n]) - (i1 / i0)) * 100.0
    pts = pts if pts > 0 else 0.0
    thr = float(cfg["wide_run_pts"])
    if pts < thr:
        return None
    return {"signal": "wide_run_20d", "value": pts, "threshold": thr, "surprise": pts / thr,
            "detail": {"px_day": str(last.date()), "points_ahead": round(pts, 1), "sessions": n, "price": float(s.iloc[-1]),
                       "question": "a run in a name nobody looked at: is there a reason the system has not seen?"}}


def _title(sym: str, x: dict) -> str:
    if x["signal"] == "wide_run_20d":
        return f"{sym} is {x['value']:.0f} points ahead of its index over {x['detail'].get('sessions', 20)} sessions (not held, not looked at)"
    return watch._say(sym, x)


def scan(con, day: date, market: str, uni: pd.DataFrame, series: Dict[str, pd.Series], ix: Optional[pd.Series], cfg: dict, whole: float, via: Dict[str, float]) -> dict:
    """The price signals of every name of `uni` on `day`: {"raws": [...], "scanned": n, "stale": n}. A name whose last bar is not `day` is skipped."""
    raws: List[dict] = []
    scanned = stale = 0
    fac = float(cfg["wide_index_factor"])
    for r in uni.itertuples(index=False):
        s = series.get(r.isin)
        if s is None or len(s) < int(cfg["min_history"]):
            continue
        if s.index[-1].date() != day:
            stale += 1
            continue
        scanned += 1
        sigs = watch._price_signals(s, ix, cfg)
        rs = _run_signal(s, ix, cfg)
        if rs:
            sigs.append(rs)
        if not sigs:
            continue
        v = float(via.get(r.isin, 0.0))
        expo = v + float(r.weight) * whole * fac
        e = {"name": r.symbol, "isin": r.isin, "symbol": r.symbol, "market": market, "exposure_inr": expo, "exposure_pct": expo / whole if whole > 0 else 0.0, "held": False,
             "why": f"wide watch ({LABEL[market]})", "via_funds_inr": v, "index_weight": float(r.weight),
             "exposure_basis": f"wide watch ranking weight: through funds Rs {v:,.0f} (estimate) plus {float(r.weight):.2%} index weight (proxy) x {fac:.0%} of the whole book"}
        raws += [{**x, "entry": e, "detail": {**x["detail"], "wide": True}} for x in sigs]
    return {"raws": raws, "scanned": scanned, "stale": stale}


# --- the commit ---------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _wide_cases_today(con, day: date) -> int:
    return int(con.execute("SELECT count(*) FROM think_cases_s84 WHERE opened_on=? AND opened_by='wide' AND state <> 'noticed'", [day]).fetchone()[0])


def _weakest_unthought(con, day: date) -> Optional[dict]:
    """The weakest case opened today that nothing has been thought about yet (it can go back to 'noticed' without losing a thought)."""
    rows = [c for c in cases.open_cases(con) if c["opened_on"] == day and c["state"] == "open" and not cases.steps(con, c["case_id"])]
    rows.sort(key=lambda c: float(c.get("score") or 0.0))
    return rows[0] if rows else None


def commit(con, sig_now: datetime, raws: List[dict], cfg: dict) -> dict:
    """Store the pass's top signals once each (name, signal, day), join the open cases, open the wide cases the day allows (see the module text)."""
    day = sig_now.date()
    res = {"signals": [], "cases_opened": [], "joined": [], "noticed": 0, "cases_noticed": [], "found": len(raws), "dropped_below_top": 0, "demoted": []}      # `noticed` stays 0: a stored wide signal is not a case the cap turned away
    ranked = sorted(raws, key=lambda x: -x["surprise"] * x["entry"]["exposure_inr"])
    top_n = int(cfg["wide_store_top"])
    fresh: Dict[str, List[tuple]] = {}
    ent: Dict[str, dict] = {}
    stored = 0
    for x in ranked:
        e = x["entry"]
        ref = x.get("dedupe_ref")
        if ref:
            if con.execute("SELECT 1 FROM think_signals_s84 WHERE isin=? AND signal=? AND detail_json LIKE ? LIMIT 1", [e["isin"], x["signal"], f'%"ref": "{ref}"%']).fetchone():
                continue
        elif con.execute("SELECT 1 FROM think_signals_s84 WHERE isin=? AND signal=? AND day=? LIMIT 1", [e["isin"], x["signal"], day]).fetchone():
            continue
        has_case = cases.case_for(con, e["isin"]) is not None
        if stored >= top_n and not has_case:
            res["dropped_below_top"] += 1
            continue
        stored += 1
        det = dict(x["detail"])
        det.update({"wide": True, "why_in_scope": e.get("why"), "exposure_basis": e.get("exposure_basis"), "exposure_via_funds_inr": e.get("via_funds_inr", 0.0),
                    "index_weight_proxy": e.get("index_weight")})
        score = x["surprise"] * e["exposure_inr"]
        sid = cases.record_signal(con, sig_now, market=e["market"], isin=e["isin"], symbol=e["symbol"], signal=x["signal"], value=x["value"], threshold=x["threshold"], surprise=x["surprise"],
                                  exposure_inr=e["exposure_inr"], score=score, detail=det, status="not_examined")
        res["signals"].append(sid)
        fresh.setdefault(e["isin"], []).append((sid, x, score))
        ent[e["isin"]] = e
    cands = []
    for isin, items in fresh.items():
        e = ent[isin]
        top = max(items, key=lambda t: t[2])
        oc = cases.case_for(con, isin)
        if oc is not None:
            for sid, _x, _sc in items:
                cases.set_signal(con, sid, case_id=oc["case_id"], status="joined")
            if top[2] > float(oc.get("score") or 0.0):
                cases.set_case(con, oc["case_id"], score=top[2])
            if oc["case_id"] not in res["joined"]:
                res["joined"].append(oc["case_id"])
            continue
        cands.append((top[2], isin, items))
    cands.sort(key=lambda t: (-t[0], -max(x["surprise"] for _sid, x, _sc in t[2])))          # the score; on a tie (a book with no value yet) the bigger surprise
    quota = max(0, int(cfg["wide_cases_per_day"]) - _wide_cases_today(con, day))
    cap = int(cfg["max_cases_per_day"])
    for score, isin, items in cands:
        if quota <= 0:
            break
        room = cap - cases.cases_opened_on(con, day)
        if room <= 0:
            weak = _weakest_unthought(con, day)
            if weak is None or float(weak.get("score") or 0.0) >= score:
                continue                                   # the cap is full and nothing weaker waits: the name stays a stored signal
            cases.set_case(con, weak["case_id"], state="noticed")
            for s in cases.signals(con, case_id=weak["case_id"]):
                cases.set_signal(con, s["signal_id"], status="not_examined")
            res["demoted"].append(weak["case_id"])
        e = ent[isin]
        items.sort(key=lambda t: -t[2])
        title = "; ".join(_title(e["symbol"], x) for _sid, x, _sc in items[:2]) + f" [wide watch: {LABEL[e['market']]}]"
        kind = WIDE_GROUP.get(items[0][1]["signal"]) or watch.GROUP.get(items[0][1]["signal"], "move")
        cid = cases.open_case(con, sig_now, market=e["market"], kind=kind, isin=e["isin"], symbol=e["symbol"], title=title, exposure_inr=e["exposure_inr"], exposure_pct=e["exposure_pct"],
                              score=score, opened_by="wide", signal_ids=[sid for sid, _x, _sc in items], state="open", names=[e["symbol"]])
        res["cases_opened"].append(cid)
        quota -= 1
    return res


# --- one pass ----------------------------------------------------------------------------------------------------------------------------------------------------------------------

def run_pass(con, sig_now: datetime, day: date, until: datetime, market: str, *, root=None) -> dict:
    """The wide watch for one session of `market` (India close, US morning). Never raises; a failure is `res["error"]`. Idempotent."""
    cfg = settings()
    res: dict = {"signals": [], "cases_opened": [], "joined": [], "noticed": 0, "cases_noticed": [], "wide": {"market": market, "day": str(day)}}
    t0 = _time.time()
    try:
        uni = universe(con, day, market, root)
        if not len(uni):
            res["wide"]["note"] = "no member data (the index's list is missing): the wide watch did not run"
            return res
        series = _series(con, root, market, uni, day)
        ix = watch._index(market, root)
        whole = watch._whole_inr(con, day, root)
        try:
            via = exposure.via_funds(con, day, root)
        except Exception:
            via = {}
        sc = scan(con, day, market, uni, series, ix, cfg, whole, via)
        raws = sc["raws"]
        entries = {}
        for r in uni.itertuples(index=False):
            entries[r.isin] = {"name": r.symbol, "isin": r.isin, "symbol": r.symbol, "market": market, "held": False, "why": f"wide watch ({LABEL[market]})", "via_funds_inr": float(via.get(r.isin, 0.0)),
                               "index_weight": float(r.weight), "exposure_inr": float(via.get(r.isin, 0.0)) + float(r.weight) * whole * float(cfg["wide_index_factor"]),
                               "exposure_pct": 0.0, "exposure_basis": "wide watch ranking weight (see the price signals)"}
        ents = list(entries.values())
        for e in ents:
            e["exposure_pct"] = e["exposure_inr"] / whole if whole > 0 else 0.0
        try:                                               # events and news of members, same readers as T1 (a thesis-break kind; a news burst); India news only
            raws += [{**x, "detail": {**x["detail"], "wide": True}} for x in watch._thesis_signals(con, ents, day, until, cfg)]
            if market == "IN":
                raws += [{**x, "detail": {**x["detail"], "wide": True}} for x in watch._news_signals(con, ents, day, until, cfg)]
        except Exception as ex:
            res["wide"]["event_error"] = repr(ex)[:200]
        out = commit(con, sig_now, raws, cfg)
        res.update({k: out[k] for k in ("signals", "cases_opened", "joined", "noticed", "cases_noticed")})
        res["wide"].update({"scanned": sc["scanned"], "stale_bars": sc["stale"], "signals_found": out["found"], "stored": len(out["signals"]), "dropped_below_top": out["dropped_below_top"],
                            "demoted_cases": out["demoted"]})
    except Exception as ex:
        res["wide"]["error"] = repr(ex)[:300]
    secs = _time.time() - t0
    res["wide"]["seconds"] = round(secs, 2)
    try:
        w = res["wide"]
        con.execute("INSERT OR REPLACE INTO think_wide_runs_s85 VALUES (?,?,?,?,?,?,?,?,?,?)", [f"{market}:{day}", market, day, sig_now, int(w.get("scanned", 0)), int(w.get("signals_found", 0)),
                                                                                              int(w.get("stored", 0)), len(res["cases_opened"]), secs, (w.get("note") or w.get("error") or "")[:200]])
    except Exception:
        pass
    return res


def wide_text(con, day: date) -> dict:
    """The wide watch's day in plain words (JSON-able): names scanned, signals stored, cases opened."""
    rows = con.execute("SELECT market, scanned, signals, stored, cases_opened, seconds, note FROM think_wide_runs_s85 WHERE day=? ORDER BY market", [day]).fetchall()
    if not rows:
        return {"day": str(day), "runs": [], "text": "The wide watch has not run today."}
    runs = [{"market": m, "scanned": a, "signals_found": b, "stored": c, "cases_opened": d, "seconds": round(s, 1), "note": n} for m, a, b, c, d, s, n in rows]
    parts = [f"{r['market']}: looked at {r['scanned']} names, {r['signals_found']} signal(s), {r['cases_opened']} case(s) opened" for r in runs]
    return {"day": str(day), "runs": runs, "text": "The wide watch (index members, cheap signals): " + "; ".join(parts) + "."}
