"""Adapters: the existing (and later) tools read into typed claims (S79b item 16).

An adapter calls a tool BY NAME through `Runner.call` (so the call is journaled in `hq_tool_calls` with its id, and the claim cites it) and turns the result
into claims with `claims.add`. A tool that does not exist (yet) or fails gives no claims and a line in the run's source log; it never stops the build.

Point-in-time: tools that take a date get `as_of`; tools that read "the latest" state with no date (forecast_now, fall_risk, system_allocation, paper_book,
agenda, bear_scorecard) are used only when `as_of` is the latest session at `now`, or when the result itself is dated on or before `as_of`.

Every number in a claim's text is printed exactly as the tool printed it (`js`), so a sentence quoting the claim passes the citation check.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pflab.situation import claims as C

LIVE_ONLY = ("system_allocation", "paper_book", "agenda", "bear_scorecard", "catch_up")


def js(v) -> str:
    """A figure the way the tools print it (JSON)."""
    return json.dumps(v)


class _ConRt:
    """The little a tool needs from the runtime when only a store connection is at hand (tests, scripts)."""

    def __init__(self, con, data_root: Optional[Path] = None, now: Optional[datetime] = None):
        from pflab.data import data_dir
        self.con = con
        self.data_root = Path(data_root) if data_root else data_dir()
        self.pm_dir = Path(".")
        self.repo = Path(".")
        self.settings: dict = {}
        self._now = now or datetime.now()
        self.clock = lambda: self._now

    def cursor(self):
        return self.con


def as_rt(rt_or_con, now: Optional[datetime] = None):
    return rt_or_con if hasattr(rt_or_con, "data_root") else _ConRt(rt_or_con, now=now)


@dataclass
class Runner:
    """What every adapter gets: the runtime, the market, the date, and the means to call a tool and add a claim."""
    rt: Any
    market: str
    as_of: date
    now: datetime
    run_id: Optional[int] = None
    log: List[dict] = field(default_factory=list)
    n_claims: int = 0
    _ctx: Any = None
    current: str = ""

    @property
    def con(self):
        return self.rt.cursor()

    @property
    def live(self) -> bool:
        """True when `as_of` is the latest session (or later) at `now`: tools without a date argument then describe the right day."""
        try:
            from pflab import markets
            return self.as_of >= markets.get(self.market).last_session_on_or_before(self.now.date())
        except Exception:
            return self.as_of >= self.now.date()

    def _tool_ctx(self):
        if self._ctx is None:
            from pflab.hq import egress, tools as tl
            at = self.now if self.as_of >= self.now.date() else datetime.combine(self.as_of, time(23, 59))
            self._ctx = tl.Ctx(self.rt, None, "situation", False, {}, egress.Gate(), at, role="research")
        return self._ctx

    def have(self, name: str) -> bool:
        from pflab.hq import tools as tl
        return name in tl.TOOLS

    def call(self, name: str, args: Optional[dict] = None) -> Tuple[Optional[dict], Optional[int]]:
        """(result dict, call id) or (None, None) when the tool is missing, not usable for this date, or failed. The call is journaled whole by the tool loop's logger."""
        from pflab.hq import tools as tl
        from pflab.pm.store import next_id
        tool = tl.TOOLS.get(name)
        if tool is None:
            self.log.append({"tool": name, "status": "missing"})
            return None, None
        if name in LIVE_ONLY and not self.live:
            self.log.append({"tool": name, "status": "skipped", "why": "no date argument: the latest state is not point-in-time for a past date"})
            return None, None
        ctx = self._tool_ctx()
        t0 = datetime.now()
        try:
            ctx.call_ref = next_id(ctx.con, "hq_tool_calls", "call_no")
            res = tool.fn(ctx, dict(args or {}))
            res = tl._plain(res)
            text = json.dumps(res, default=str, ensure_ascii=False)
            tl._log(ctx, 1, name, tool.kind, args or {}, "ran", text, int((datetime.now() - t0).total_seconds() * 1000))
            cid = ctx.call_ref
        except Exception as e:
            ctx.call_ref = None
            self.log.append({"tool": name, "status": "error", "why": f"{type(e).__name__}: {str(e)[:160]}"})
            return None, None
        ctx.call_ref = None
        if isinstance(res, dict) and res.get("off"):
            self.log.append({"tool": name, "status": "off"})
            return None, None
        if isinstance(res, dict):
            res["call_ref"] = cid
        self.log.append({"tool": name, "status": "ok", "call": cid})
        return res, cid

    def add(self, kind: str, subject: str, text: str, **kw) -> int:
        kw.setdefault("as_of", self.as_of)
        kw.setdefault("now", self.now)
        cid = C.add(self.con, self.market, kind, subject, text, source=self.current, run_id=self.run_id, **kw)
        self.n_claims += 1
        return cid


def _d(x) -> Optional[date]:
    try:
        return date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# --- breadth -> regime ------------------------------------------------------------------------------------------------------------------

def regime_label(adv_pct: float, above50_pct: float) -> Tuple[str, float]:
    """The regime by code: 'weak' when fewer than 40% of names advanced and fewer than 40% are above their 50-day average, 'strong' when more than 60% and 60%, else 'mixed'."""
    if adv_pct < 40 and above50_pct < 40:
        return "weak", -1.0
    if adv_pct > 60 and above50_pct > 60:
        return "strong", 1.0
    return "mixed", 0.0


def a_breadth(r: Runner) -> None:
    res, cid = r.call("breadth", {"market": r.market, "date": str(r.as_of)})
    if not res or "advancers" not in res:
        return
    day = _d(res.get("day")) or r.as_of
    a50 = (res.get("above_sma50") or {}).get("pct")
    a20 = (res.get("above_sma20") or {}).get("pct")
    r.add("regime", "breadth", f"Breadth: advancing_pct {js(res['advancing_pct'])}, advance_decline_ratio {js(res['advance_decline_ratio'])}, above_sma50 pct {js(a50)}, "
          f"above_sma20 pct {js(a20)}, new_high_50d {js(res['new_high_50d'])}, new_low_50d {js(res['new_low_50d'])}", value=float(res["advancing_pct"]),
          call_ids=[cid], as_of=day, ttl_sessions=3)
    if _num(res.get("advancing_pct")) and _num(a50):
        lab, lean = regime_label(float(res["advancing_pct"]), float(a50))
        r.add("regime", "regime", f"Regime by the code's breadth rule: {lab}", value=lean, call_ids=[cid], as_of=day, ttl_sessions=3, confidence=None)


# --- forecasts --------------------------------------------------------------------------------------------------------------------------

def cdf_at(quantiles: Dict[float, float], x: float) -> Optional[float]:
    """P(return <= x) by linear interpolation of the forecast's quantile function (levels -> return). Outside the 5th..95th range the value is clipped to that range's edge
    (a floor or ceiling, never an extrapolation). None when fewer than two quantiles."""
    pts = sorted((float(v), float(k)) for k, v in quantiles.items() if _num(v))
    if len(pts) < 2:
        return None
    vs, ps = [p[0] for p in pts], [p[1] for p in pts]
    if x <= vs[0]:
        return ps[0]
    if x >= vs[-1]:
        return ps[-1]
    for (v0, p0), (v1, p1) in zip(pts, pts[1:]):
        if v0 <= x <= v1:
            return p0 if v1 == v0 else p0 + (p1 - p0) * (x - v0) / (v1 - v0)
    return None


def a_forecast(r: Runner) -> None:
    res, cid = r.call("forecast_now", {"market": r.market})
    if not res or not res.get("horizons"):
        return
    made = _d(res.get("made_at_close_of"))
    if made is None or made > r.as_of:
        r.log.append({"tool": "forecast_now", "status": "skipped", "why": "its forecast is dated after the as-of date"})
        return
    for h, v in sorted(res["horizons"].items(), key=lambda kv: int(kv[0])):
        q = v.get("return_quantiles_percent") or {}
        if not q:
            continue
        pick = lambda lv: q.get(str(lv)) if str(lv) in q else q.get(f"{lv:g}")           # noqa: E731
        med, lo, hi = pick(0.5), pick(0.1), pick(0.9)
        r.add("forecast", f"forecast_h{h}", f"Forecast of the index return over {h} sessions, percent: median {js(med)}, 10th {js(lo)}, 90th {js(hi)}; "
              f"{js(v.get('live_scored', 0))} live sessions scored, verdict {v.get('verdict')}", value=float(med) if _num(med) else None, call_ids=[cid], as_of=made, ttl_sessions=int(h))
        qd = {float(k): float(x) for k, x in q.items() if _num(x)}
        p_down = cdf_at(qd, 0.0)
        if p_down is not None:
            p_down = round(p_down, 3)
            r.add("forecast", f"p_down_h{h}", f"Chance the index is lower after {h} sessions: {js(p_down)} (interpolated by code from the forecast's quantiles; at the edge of "
                  f"the 5th to 95th range it is a floor or a ceiling)", value=p_down, call_ids=[cid], as_of=made, ttl_sessions=int(h),
                  confidence=None)
        w = v.get("weights")
        if isinstance(w, dict) and w:
            r.add("weights", f"weights_h{h}", "Ensemble weights over %s sessions: %s" % (h, ", ".join(f"{k} {js(x)}" for k, x in w.items())), call_ids=[cid], as_of=made, ttl_sessions=int(h))
        elif isinstance(w, str):
            r.add("weights", f"weights_h{h}", f"Ensemble weights over {h} sessions: uniform, no outcome has matured yet", call_ids=[cid], as_of=made, ttl_sessions=int(h))


def a_fall_risk(r: Runner) -> None:
    res, cid = r.call("fall_risk", {"market": r.market})
    if not res or res.get("shown") is None:
        if res and res.get("note"):
            r.add("fall_risk", "fall_risk_20", f"Fall risk: {res['note']}", call_ids=[cid], ttl_sessions=2)
        return
    d = _d(res.get("as_of"))
    if d is None or d > r.as_of:
        return
    r.add("fall_risk", "fall_risk_20", f"Chance the index closes at least 5% under its level within 20 sessions: shown {js(res['shown'])}, p_raw {js(res.get('p_raw'))}, "
          f"calibrated on n_calibration {js(res.get('n_calibration'))} outcomes; resolved {js(res.get('resolved'))}", value=float(res["shown"]), call_ids=[cid], as_of=d, ttl_sessions=5)


def a_implied(r: Runner) -> None:
    res, cid = r.call("implied_dist", {"market": r.market})
    if not res or not res.get("option_data") or not res.get("quantiles"):
        return
    d = _d(res.get("option_day") or res.get("asof")) or r.as_of
    if d > r.as_of:
        return
    qs = res["quantiles"]
    chg = lambda k: (qs.get(k) or {}).get("change_pct")                                  # noqa: E731
    r.add("implied", "implied_dist", f"Options: expiry in {js(res.get('calendar_days_to_expiry'))} days, atm_iv {js(res.get('atm_iv'))}, skew_90_110 {js(res.get('skew_90_110'))}; "
          f"index change at the 5th percentile {js(chg('q05'))} percent, median {js(chg('q50'))}, 95th {js(chg('q95'))} (insurance prices, not a forecast)",
          value=res.get("atm_iv"), call_ids=[cid], as_of=d, ttl_sessions=3)
    for lab, ent in (res.get("fall_probabilities") or {}).items():
        if lab not in ("5%", "10%") or not isinstance(ent, dict):
            continue
        p = ent.get("p_calibrated") if _num(ent.get("p_calibrated")) else ent.get("p_implied")
        if not _num(p):
            continue
        r.add("implied", f"implied_fall_{lab.rstrip('%')}_h{int(ent.get('horizon_sessions') or 20)}", f"Options-implied chance of a fall of {lab} within {js(ent.get('horizon_sessions'))} sessions: p_implied {js(ent.get('p_implied'))}, "
              f"p_calibrated {js(ent.get('p_calibrated'))}, n {js(ent.get('n'))}", value=float(p), call_ids=[cid], as_of=d, ttl_sessions=3)


def a_cascade(r: Runner) -> None:
    res, cid = r.call("cascade", {"market": r.market})
    if not res or not res.get("available"):
        return
    d = _d(res.get("asof")) or r.as_of
    if d > r.as_of:
        return
    prog = bool(res.get("in_progress"))
    r.add("implied", "cascade", f"Cascade model: fall in progress {str(prog).lower()}, branching_ratio {js(res.get('branching_ratio'))}, chance_another_shock {js(res.get('chance_another_shock'))} "
          f"within {js(res.get('horizon_sessions'))} sessions, sessions_since_last_shock {js(res.get('sessions_since_last_shock'))}", value=res.get("chance_another_shock"),
          call_ids=[cid], as_of=d, ttl_sessions=3)
    if prog:
        r.add("wave", "fall_cascade", "A run of -2% sessions is in progress (the cascade model's own rule)", value=-1.0, call_ids=[cid], as_of=d, ttl_sessions=3)


# --- transmission -> macro attribution --------------------------------------------------------------------------------------------------

def a_transmission(r: Runner) -> None:
    res, cid = r.call("transmission", {"market": r.market, "date": str(r.as_of)})
    if not res or "legs" not in res:
        return
    target = _d(res.get("target_session")) or r.as_of
    if target > r.as_of:
        return
    src = _d(res.get("source_session"))
    gap, sd = res.get("expected_gap_pct"), res.get("sd_pct")
    if _num(gap):
        r.add("transmission", "open_gap", f"Expected opening gap of the {res.get('target', 'index')} from the other side's last session: expected_gap_pct {js(gap)} "
              f"(sd_pct {js(sd)}), headline driver {res.get('headline_driver')}", value=float(gap), call_ids=[cid], as_of=target, ttl_sessions=1)
    else:
        r.add("transmission", "open_gap", f"Expected opening gap not available: {res.get('note') or 'no data'}", call_ids=[cid], as_of=target, ttl_sessions=1)
    for leg in res.get("legs") or []:
        if not _num(leg.get("contribution_pct")) or src is None:
            continue
        r.add("macro", f"leg_{leg.get('driver')}", f"{leg.get('label')} moved {js(leg.get('source_move'))} {leg.get('source_move_unit')}; its contribution to the expected gap is "
              f"contribution_pct {js(leg['contribution_pct'])} (beta {js(leg.get('beta'))}, r2 {js(leg.get('r2'))})", value=float(leg["contribution_pct"]), call_ids=[cid],
              entities=[leg.get("driver")], as_of=src, ttl_sessions=2)
    for lk in (res.get("sector_links") or [])[:6]:
        if _num(lk.get("implied_gap_pct")):
            r.add("transmission", f"sector_{lk.get('in_index')}", f"{lk.get('us_etf')} moved {js(lk.get('us_move_pct'))} percent: implied gap for {lk.get('in_index')} implied_gap_pct "
                  f"{js(lk['implied_gap_pct'])}", value=float(lk["implied_gap_pct"]), themes=[str(lk.get("in_index"))], call_ids=[cid], as_of=target, ttl_sessions=1)


# --- the book ---------------------------------------------------------------------------------------------------------------------------

def a_allocation(r: Runner) -> None:
    res, cid = r.call("system_allocation", {"market": r.market})
    if not res:
        return
    act = res.get("active")
    if not act:
        r.add("allocation", "allocation_target", "The system has no allocation target of its own yet; the team proposes the first one", call_ids=[cid], ttl_sessions=3)
        return
    cl = act.get("classes") or {}
    r.add("allocation", "allocation_target", "System allocation target, percent of the book: " + ", ".join(f"{k} {js(v)}" for k, v in cl.items())
          + (f"; review_due {act.get('review_due')}" if act.get("review_due") else ""), call_ids=[cid], ttl_sessions=3)
    for sec, w in (act.get("sectors") or {}).items():
        r.add("allocation", f"target_sector_{sec}", f"Target for {sec}: {js(w)} percent of the book", value=float(w), themes=[sec], call_ids=[cid], ttl_sessions=3)
    drift = res.get("drift")
    if isinstance(drift, dict) and drift:
        flat = {k: v for k, v in drift.items() if _num(v)}
        if flat:
            r.add("allocation", "allocation_drift", "Drift of the book from its target: " + ", ".join(f"{k} {js(v)}" for k, v in list(flat.items())[:6]), call_ids=[cid], ttl_sessions=3)


def a_book(r: Runner) -> None:
    res, cid = r.call("paper_book", {})
    if not res:
        return
    if not res.get("started"):
        r.add("book", "paper_book", "The paper portfolio has not started yet", call_ids=[cid], ttl_sessions=3)
        return
    hs = res.get("holdings") or []
    top = sorted(hs, key=lambda h: -(h.get("weight") or 0))[:5]
    r.add("book", "paper_book", f"Paper book: value {js(res.get('value'))}, cash {js(res.get('cash'))}, {js(len(hs))} holdings; largest: "
          + "; ".join(f"{h['symbol']} weight {js(h['weight'])}" for h in top) + (f"; over a rail: {'; '.join(res['over_rails'])[:160]}" if res.get("over_rails") else ""),
          value=res.get("value"), entities=[h.get("isin") for h in top], call_ids=[cid], ttl_sessions=3)
    # theme exposure of the book by sector, worked here by code when the exposure tool is not there
    if not r.have("theme_exposure"):
        sec: Dict[str, float] = {}
        for h in hs:
            if h.get("sector") and _num(h.get("weight")):
                sec[h["sector"]] = sec.get(h["sector"], 0.0) + float(h["weight"])
        for s, w in sorted(sec.items(), key=lambda kv: -kv[1])[:8]:
            r.add("exposure", f"book_sector_{s}", f"The paper book has {js(round(w, 4))} of its value in {s} (sum of holding weights)", value=round(w, 4), themes=[s], call_ids=[cid], ttl_sessions=3)


def a_agenda(r: Runner) -> None:
    res, cid = r.call("agenda", {})
    if not res or not res.get("available"):
        return
    run = res.get("running")
    q = res.get("queue") or []
    r.add("agenda", "agenda", "Agenda: " + (f"running {run.get('kind')}: {run.get('subject')}; " if run else "nothing running; ") + f"{js(len(q))} queued; useful_today {js(res.get('useful_today', 0))}",
          value=float(len(q)), call_ids=[cid], ttl_sessions=1)


def a_scorecard(r: Runner) -> None:
    res, cid = r.call("bear_scorecard", {"market": r.market})
    if not res or "resolved" not in res:
        return
    r.add("scorecard", "bear_scorecard", f"Bear warnings: resolved {js(res['resolved'])}, hits {js(res.get('hits'))}, open {js(res.get('open'))}; {res.get('note', '')[:120]}",
          call_ids=[cid], ttl_sessions=5)


def a_catch_up(r: Runner) -> None:
    if not r.live:
        return
    try:
        from pflab.service import catchup
        st = catchup.status(r.con)
    except Exception as e:
        r.log.append({"tool": "catch_up", "status": "error", "why": f"{type(e).__name__}: {str(e)[:100]}"})
        return
    for m in st.get("markets", []):
        if m.get("market") != r.market:
            continue
        r.add("state", "catch_up", f"Catch-up of {m['market']}: stage {m.get('stage')}, state {m.get('state')}, missed {js(m.get('missed'))} sessions", value=float(m.get("missed") or 0), ttl_sessions=1)
    r.log.append({"tool": "catch_up", "status": "ok"})


def a_moves(r: Runner) -> None:
    """The two biggest moves of the held and watched names, each decomposed (market part, sector part, own part) by `decompose_move`. India only (the bar files)."""
    if r.market != "IN" or not r.have("decompose_move"):
        return
    try:
        from pflab.hq import explain
        top = explain.biggest_moves(r.con, r.market, r.as_of, n=2, root=r.rt.data_root)
    except Exception as e:
        r.log.append({"tool": "biggest_moves", "status": "error", "why": f"{type(e).__name__}: {str(e)[:100]}"})
        return
    for m in top:
        res, cid = r.call("decompose_move", {"market": r.market, "date": str(r.as_of), "symbol": m["symbol"]})
        if not res or res.get("total_pct") is None:
            continue
        r.add("move", f"move_{m['symbol']}", f"{m['symbol']} moved total_pct {js(res['total_pct'])}: market_pct {js(res.get('market_pct'))}, sector_pct {js(res.get('sector_pct'))}, "
              f"own_pct {js(res.get('own_pct'))}", value=float(res["total_pct"]), entities=[m.get("isin"), m["symbol"]], call_ids=[cid], ttl_sessions=2)


def a_questions(r: Runner) -> None:
    if not r.live:
        return
    try:
        rows = r.con.execute("SELECT q_id, agent, text FROM questions WHERE status='open' ORDER BY q_id DESC LIMIT 5").fetchall()
    except Exception:
        return
    for q_id, agent, text in rows:
        r.add("question", f"question_{q_id}", f"Open question #{q_id} from {agent}: {str(text)[:200]}", ttl_sessions=2)


LEVEL_SERIES = ("WTI", "BRENT_FUT", "US_VIX", "DOLLAR_INDEX", "GOLD", "US_10Y_YIELD", "FX_USDINR", "US_SP500", "NIFTY50_PRICE")


def a_levels(r: Runner) -> None:
    """The levels a watch trigger may use: for each key series the last close and the 20-session high and low, worked here by code from the collected files (no tool call). A watch
    threshold must be one of these figures, on the claim named `level_<series>`."""
    from pflab.situation import watch as W
    for s in LEVEL_SERIES:
        h = W.history(s, r.as_of, r.rt.data_root, 21)
        if len(h) < 10:
            continue
        d, c = h[-1]
        closes = [x for _, x in h]
        r.add("macro", f"level_{s}", f"{s} level: last close {js(round(c, 4))}, 20-session high {js(round(max(closes), 4))}, 20-session low {js(round(min(closes), 4))} (levels a watch may use)",
              value=round(c, 4), entities=[s], as_of=d, ttl_sessions=2)


# --- macro attribution and the wave detector (t_waves.py: documented keys) ---------------------------------------------------------------------

def a_macro(r: Runner) -> None:
    res, cid = r.call("macro_attribution", {"market": r.market, "date": str(r.as_of)})
    if not res or res.get("total_pct") is None:
        return
    d = _d(res.get("session")) or r.as_of
    if d > r.as_of:
        return
    r.add("macro", "macro_attribution", f"Index move total_pct {js(res['total_pct'])} split by code: dominant {res.get('dominant')}, explained_pct {js(res.get('explained_pct'))}, "
          f"unexplained_pct {js(res.get('unexplained_pct'))} (an association, not a proof of cause)", value=float(res["total_pct"]), call_ids=[cid], as_of=d, ttl_sessions=2)
    for name, p in (res.get("parts") or {}).items():
        if isinstance(p, dict) and _num(p.get("pct")):
            r.add("macro", f"part_{name}", f"{p.get('label', name)}: part of the index move pct {js(p['pct'])} (beta {js(p.get('beta'))}, factor_move {js(p.get('factor_move'))}, n {js(p.get('n'))})",
                  value=float(p["pct"]), entities=[name], call_ids=[cid], as_of=d, ttl_sessions=2)


def a_wave(r: Runner) -> None:
    res, cid = r.call("wave_detector", {"market": r.market, "date": str(r.as_of)})
    if not res:
        return
    d = _d(res.get("session")) or r.as_of
    if d > r.as_of or not res.get("decided"):
        return
    st = res.get("stats") or {}
    if res.get("wave"):
        sgn = 1.0 if res.get("direction") == "up" else -1.0
        r.add("wave", "wave", f"Wave flag: the whole market moved as one, direction {res.get('direction')}, adv_share {js(st.get('adv_share'))}, disp_ratio {js(st.get('disp_ratio'))}, "
              f"dom_share {js(st.get('dom_share'))}; a holding's own move says little today", value=sgn, call_ids=[cid], as_of=d, ttl_sessions=3)
    else:
        r.add("wave", "wave", f"No wave: adv_share {js(st.get('adv_share'))}, dom_share {js(st.get('dom_share'))}", value=0.0, call_ids=[cid], as_of=d, ttl_sessions=2)
    rot = res.get("rotation") or {}
    if rot.get("decided") and rot.get("flag") in ("in", "out"):
        r.add("rotation", "rotation", f"Rotation flag {rot['flag']}: foreign flow z {js(rot.get('z'))}, gap_pct {js(rot.get('gap_pct'))} against the Asian peers, sell_streak {js(rot.get('sell_streak'))}, "
              f"buy_streak {js(rot.get('buy_streak'))}", value=1.0 if rot["flag"] == "in" else -1.0, call_ids=[cid], as_of=d, ttl_sessions=5)


# --- sentiment, theme exposure, event calendar, volume profile, construct (documented keys in t_sentiment.py, t_volume.py, t_construct.py) -----------------------------------------

def a_sentiment(r: Runner) -> None:
    res, cid = r.call("sentiment", {"market": r.market, "date": str(r.as_of)})
    if not res or not isinstance(res.get("themes"), dict):
        return
    d = _d(res.get("day") or res.get("asof")) or r.as_of
    if d > r.as_of:
        return
    if res.get("reading"):
        r.add("sentiment", "market_sentiment", f"{str(res['reading'])[:220]}" + (f"; price_score {js(res['price_score'])}" if _num(res.get("price_score")) else ""),
              value=float(res["price_score"]) if _num(res.get("price_score")) else None, call_ids=[cid], as_of=d, ttl_sessions=2)
    ths = [(k, v) for k, v in res["themes"].items() if isinstance(v, dict) and _num(v.get("combined"))]
    for name, v in sorted(ths, key=lambda kv: -abs(kv[1]["combined"]))[:10]:
        r.add("sentiment", f"theme_{name}", f"{v.get('label', name)}: combined {js(v['combined'])}, tone_score {js(v.get('tone_score'))}, fear_score {js(v.get('fear_score'))}, "
              f"pos_score {js(v.get('pos_score'))}", value=float(v["combined"]), themes=[name], call_ids=[cid], as_of=d, ttl_sessions=2)


def a_theme_exposure(r: Runner) -> None:
    res, cid = r.call("theme_exposure", {"market": r.market, "date": str(r.as_of)})
    if not res or not isinstance(res.get("themes"), dict):
        return
    if res.get("source") == "none" or not res["themes"]:
        r.add("exposure", "theme_exposure", "No book to read theme exposure from yet", call_ids=[cid], ttl_sessions=2)
        return
    d = _d(res.get("asof")) or r.as_of
    for name, v in sorted(res["themes"].items(), key=lambda kv: -(kv[1].get("weight_carrying") or 0.0) if isinstance(kv[1], dict) else 0)[:8]:
        if not isinstance(v, dict) or not _num(v.get("weight_carrying")):
            continue
        r.add("exposure", f"theme_{name}", f"{v.get('label', name)}: book carries it with weight_carrying {js(v['weight_carrying'])} (book_beta {js(v.get('book_beta'))}, "
              f"weight_sector_prior {js(v.get('weight_sector_prior'))}, n_carriers {js(v.get('n_carriers'))})", value=float(v["weight_carrying"]), themes=[name], call_ids=[cid],
              as_of=d, ttl_sessions=2)


def a_event_calendar(r: Runner) -> None:
    res, cid = r.call("event_calendar", {"market": r.market, "date": str(r.as_of)})
    if not res:
        return
    for ev in (res.get("upcoming") or [])[:6]:
        if not isinstance(ev, dict) or not ev.get("label"):
            continue
        ed = _d(ev.get("date"))
        ttl = max(1, (ed - r.as_of).days) if ed and ed >= r.as_of else 1
        sc = ev.get("scenario")
        r.add("event", f"event_{ev.get('id', ev['label'])}"[:100], f"Upcoming: {ev['label']} on {ev.get('date')}" + (f" - {'; '.join(f'{k}: {v}' for k, v in list(sc.items())[:2])[:160]}" if isinstance(sc, dict) and sc else ""),
              call_ids=[cid], as_of=r.as_of, ttl_sessions=min(ttl, 10))


def a_volume(r: Runner) -> None:
    res, cid = r.call("volume_profile", {"market": r.market})
    if not res or not isinstance(res.get("features"), dict) or res.get("off"):
        return
    d = _d(res.get("as_of") or res.get("last_session")) or r.as_of
    if d > r.as_of:
        return
    f = res["features"]
    body = ", ".join(f"{k} {js(v)}" for k, v in f.items() if isinstance(v, (int, float, str)) and not isinstance(v, bool) and v is not None)[:300]
    r.add("observation", "volume_profile", f"Volume profile ({res.get('basis')}): {body}", call_ids=[cid], as_of=d, ttl_sessions=2)


def a_construct(r: Runner) -> None:
    res, cid = r.call("construct", {})
    if not res or res.get("off") or not res.get("ok", True) or not res.get("target_weights"):
        return
    tw = sorted(res["target_weights"], key=lambda t: -abs(t.get("change_pct") or 0.0))[:3]
    r.add("book", "construct", f"Sizing advice (not adopted unless stated; status {res.get('status')}): cash_target_pct {js(res.get('cash_target_pct'))}; largest changes "
          + "; ".join(f"{t['symbol']} change_pct {js(t.get('change_pct'))}" for t in tw), call_ids=[cid], ttl_sessions=2)


# --- tools being built alongside (read tolerantly, by documented key names) -------------------------------------------------------------

GENERIC: Dict[str, str] = {}              # tools whose keys are not documented yet are read generically (none now: every tool has an adapter below)
_TEXT_KEYS = ("reading", "summary", "verdict", "headline", "note", "message")
_VAL_KEYS = ("value", "score", "level", "p", "probability")
_LIST_KEYS = ("themes", "items", "rows", "waves", "flags", "sectors", "attribution", "factors", "exposures")
_NAME_KEYS = ("theme", "name", "sector", "driver", "factor", "id", "label")


def _first(d: dict, keys) -> Optional[Any]:
    for k in keys:
        if d.get(k) not in (None, "", [], {}):
            return d[k]
    return None


def a_generic(r: Runner, tool: str, kind: str) -> None:
    if not r.have(tool):
        r.log.append({"tool": tool, "status": "missing"})
        return
    res, cid = r.call(tool, {"market": r.market, "date": str(r.as_of)}) if tool != "construct" else r.call(tool, {"market": r.market})
    if not res or res.get("error") or res.get("skipped"):
        return
    d = _d(res.get("as_of") or res.get("asof") or res.get("day") or res.get("date")) or r.as_of
    if d > r.as_of:
        r.log.append({"tool": tool, "status": "skipped", "why": "dated after the as-of date"})
        return
    text = _first(res, _TEXT_KEYS)
    flat = ", ".join(f"{k} {js(v)}" for k, v in res.items() if _num(v) and k != "call_ref" and not k.startswith("n_") and not k.endswith("_reference"))[:260]
    val = next((float(res[k]) for k in _VAL_KEYS if _num(res.get(k))), None)
    body = (str(text)[:200] if text else "") + ("; " if text and flat else "") + flat
    if body:
        r.add(kind, tool, body, value=val, call_ids=[cid], as_of=d, ttl_sessions=3)
    for lk in _LIST_KEYS:
        lst = res.get(lk)
        if not isinstance(lst, list):
            continue
        for it in lst[:8]:
            if not isinstance(it, dict):
                continue
            name = _first(it, _NAME_KEYS)
            if name is None:
                continue
            v = next((float(it[k]) for k in _VAL_KEYS + ("weight", "contribution_pct", "tone", "share") if _num(it.get(k))), None)
            body = ", ".join(f"{k} {js(x)}" for k, x in it.items() if _num(x))[:200] or str(it.get("reading") or it.get("note") or "")[:200]
            r.add(kind, f"{tool}:{name}"[:100], f"{name}: {body}", value=v, themes=[str(name)], call_ids=[cid], as_of=d, ttl_sessions=3)
        break


ADAPTERS: Dict[str, Callable[[Runner], None]] = {
    "breadth": a_breadth, "forecast_now": a_forecast, "fall_risk": a_fall_risk, "implied_dist": a_implied, "cascade": a_cascade, "transmission": a_transmission,
    "system_allocation": a_allocation, "paper_book": a_book, "agenda": a_agenda, "bear_scorecard": a_scorecard, "catch_up": a_catch_up, "decompose_move": a_moves,
    "questions": a_questions, "macro_attribution": a_macro, "wave_detector": a_wave, "levels": a_levels, "sentiment": a_sentiment, "theme_exposure": a_theme_exposure, "event_calendar": a_event_calendar,
    "volume_profile": a_volume, "construct": a_construct,
}
for _t, _k in GENERIC.items():
    ADAPTERS[_t] = (lambda t, k: (lambda r: a_generic(r, t, k)))(_t, _k)


def run_all(r: Runner, only: Optional[List[str]] = None) -> List[dict]:
    """Run every adapter (or `only`); each one's outcome is a line in the source log: ok (n claims), missing, skipped or error. Nothing raises."""
    out = []
    for name, fn in ADAPTERS.items():
        if only is not None and name not in only:
            continue
        r.current = name
        n0, l0 = r.n_claims, len(r.log)
        try:
            fn(r)
            status = "ok" if r.n_claims > n0 else next((e["status"] for e in reversed(r.log[l0:]) if e.get("tool") in (name, "biggest_moves")), "empty")
            if status == "ok" and r.n_claims == n0:
                status = "empty"
        except Exception as e:
            status = f"error: {type(e).__name__}: {str(e)[:120]}"
        out.append({"source": name, "status": status, "claims": r.n_claims - n0})
    return out
