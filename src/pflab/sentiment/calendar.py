"""The calendar of scheduled shocks (S79b item 15b): dated events with sources (configs/themes_s79b.toml `[[event]]`), a code-written SCENARIO NOTE per theme before each
event and a SURPRISE measure after it.

Only dates with a recorded source are `verified = true`; the others say what would verify them. Nothing is invented.

Scenario note (before the event, for each theme the event touches): from the theme's primary proxy, the proxy's typical daily move (standard deviation of the last 60
sessions), the market index's measured beta to the proxy (trailing `beta_window` sessions, point in time, the proxy's lag as in exposure.py), what that beta times one such
proxy move would do to the index, and the options-implied one-session move of the index (the volatility index of the market / sqrt(252): India VIX for IN, the VIX for US;
for IN also the Nifty option chain's chance of a fall of 5% by its expiry where `quant/implied.py` has a current chain). A description of history and of prices, not a forecast.
Surprise (after the event): the market index's move on the first session that opens after the event time, divided by the one-session move the volatility index implied
at the PREVIOUS close (a z-score: |z| < 1 inside what options expected, 1-2 more than expected, > 2 a surprise), plus the theme proxies' moves against their own typical moves.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab import sentiment as S
from pflab.sentiment import exposure, fear, read_series, themes as T

INDEX_FILE = {"IN": ("indices/NIFTY50_PRICE.parquet", ("close",), "Nifty 50"), "US": ("global/US_SP500.parquet", ("close", "value"), "S&P 500")}


@dataclass(frozen=True)
class Event:
    id: str
    date: date
    utc: datetime
    kind: str
    label: str
    themes: tuple
    markets: tuple
    verified: bool
    source: str


def load_events(path: Optional[Path] = None) -> List[Event]:
    cfg = T.load_config(path)
    out = []
    for e in cfg.get("event", []) or []:
        try:
            d = date.fromisoformat(str(e["date"]))
            utc = datetime.fromisoformat(str(e.get("utc") or f"{d}T00:00"))
        except Exception:
            continue
        out.append(Event(e["id"], d, utc, e.get("kind", ""), e.get("label", e["id"]), tuple(e.get("themes", [])), tuple(e.get("markets", ["IN"])), bool(e.get("verified", False)),
                         e.get("source", "")))
    return sorted(out, key=lambda x: x.date)


def index_level(root, market: str) -> Optional[pd.Series]:
    f, cols, _ = INDEX_FILE.get(market, INDEX_FILE["IN"])
    p = Path(root) / f
    return read_series(p, cols) if p.exists() else None


def reaction_session(market: str, utc: datetime) -> Optional[date]:
    """The first session of the market that is still open or not yet opened when the news is public: the first whose close (IST) is after the event time (IST)."""
    from pflab import markets
    m = markets.get(market)
    ist = utc + timedelta(hours=5, minutes=30)
    d = (ist - timedelta(days=2)).date()
    for _ in range(14):
        w = m.window_ist(d)
        if w is not None and w[1] > ist:
            return d
        d += timedelta(days=1)
    return None


def implied_sd_pct(root, market: str, day: date) -> Optional[dict]:
    """One-session 1-sd move implied by the market's volatility index at the latest print on or before `day`: vix / sqrt(252), in percent."""
    v = fear.vix(root, market)
    if v is None:
        return None
    v = v[v.index <= pd.Timestamp(day)]
    if v.empty or (pd.Timestamp(day) - v.index[-1]).days > 6:
        return None
    return {"vix": float(v.iloc[-1]), "vix_date": str(v.index[-1].date()), "sd_pct": float(v.iloc[-1]) / np.sqrt(252.0), "source": "India VIX" if market == "IN" else "US VIX"}


def _proxy_stats(root, market: str, proxy_key: str, asof: date) -> Optional[dict]:
    """The index's beta to a proxy and the proxy's typical daily move, both from rows dated <= asof."""
    st = S.settings()
    lv = T.load_proxy(root, proxy_key)
    ix = index_level(root, market)
    if lv is None or ix is None:
        return None
    lv, ix = lv[lv.index <= pd.Timestamp(asof)], ix[ix.index <= pd.Timestamp(asof)]
    if len(ix) < 80 or len(lv) < 80:
        return None
    R = ix.astype(float).pct_change(fill_method=None).dropna().to_frame("index")
    x = exposure.proxy_returns(lv, R.index, T.proxy_lag(proxy_key))
    b = exposure.betas(R, x, int(st["beta_window"]), int(st["beta_min"])).iloc[0]
    pr = lv.astype(float).pct_change(fill_method=None).dropna().iloc[-60:]
    return {"proxy": proxy_key, "proxy_label": T.proxy_label(proxy_key), "beta": None if not np.isfinite(b["beta"]) else float(b["beta"]),
            "t": None if not np.isfinite(b["t"]) else float(b["t"]), "r": None if not np.isfinite(b["r"]) else float(b["r"]), "n": int(b["n"]),
            "proxy_sd_pct": float(pr.std() * 100.0) if len(pr) > 10 else None, "proxy_last": str(lv.index[-1].date())}


def scenario_note(root, ev: Event, market: str, theme: T.Theme, asof: date) -> dict:
    """{"text","values"}: the code-written scenario note for one theme before one event."""
    name = INDEX_FILE.get(market, INDEX_FILE["IN"])[2]
    imp = implied_sd_pct(root, market, asof)
    vals: dict = {"event": ev.id, "event_date": str(ev.date), "theme": theme.key, "market": market, "asof": str(asof), "verified_date": ev.verified}
    parts = [f"Before {ev.label} ({ev.date}{'' if ev.verified else ', date not verified'}), theme {theme.label}."]
    ps = _proxy_stats(root, market, theme.primary, asof) if theme.primary else None
    if ps and ps["beta"] is not None and ps["proxy_sd_pct"] is not None:
        shock = ps["beta"] * ps["proxy_sd_pct"]
        vals.update({"proxy": ps["proxy"], "beta": ps["beta"], "t": ps["t"], "r": ps["r"], "n": ps["n"], "proxy_sd_pct": ps["proxy_sd_pct"], "index_move_for_1sd_proxy_pct": shock})
        parts.append(f"Over the last {ps['n']} sessions the {name} has moved {ps['beta']:+.2f}% for a 1% move in {ps['proxy_label']} (t {ps['t']:.1f}); {ps['proxy_label']} has "
                     f"moved {ps['proxy_sd_pct']:.2f}% on a typical day; one such move, applied to that sensitivity, is {shock:+.2f}% on the {name}.")
    else:
        parts.append(f"No measured sensitivity of the {name} to {theme.primary or 'a proxy'} is available on this PC.")
    if imp:
        vals.update({"implied_sd_pct": imp["sd_pct"], "vix": imp["vix"], "vix_date": imp["vix_date"]})
        parts.append(f"The options market ({imp['source']} {imp['vix']:.1f} on {imp['vix_date']}) implies a one-session move of about {imp['sd_pct']:.2f}% (1 sd) for the {name}.")
    if market == "IN":
        try:
            from pflab.quant import implied
            r = implied.latest(root, asof)
            if r:
                vals.update({"nifty_chain_expiry": r["expiry"], "p_below_5": r["p_below_5"], "p_below_10": r["p_below_10"]})
                parts.append(f"The Nifty option chain of {r['date']} prices a {r['p_below_5']:.0%} chance of a fall of more than 5% by {r['expiry']} (risk-neutral: insurance costs extra).")
        except Exception:
            pass
    parts.append("A description of history and of prices, not a forecast.")
    return {"text": " ".join(parts), "values": vals}


def surprise(root, ev: Event, market: str, themes: Dict[str, T.Theme], asof: date) -> Optional[dict]:
    """The surprise measure of an event that has happened: {"text","values"}; None when the reaction session has not closed by `asof` or the data is missing."""
    d = reaction_session(market, ev.utc)
    if d is None or d > asof:
        return None
    ix = index_level(root, market)
    if ix is None or pd.Timestamp(d) not in ix.index:
        return None
    from pflab import markets
    prev = markets.get(market).previous_session(d)
    ix_prev = ix[ix.index < pd.Timestamp(d)]
    if ix_prev.empty:
        return None
    move = float(ix.loc[pd.Timestamp(d)] / ix_prev.iloc[-1] - 1.0) * 100.0
    imp = implied_sd_pct(root, market, prev)
    name = INDEX_FILE.get(market, INDEX_FILE["IN"])[2]
    vals: dict = {"event": ev.id, "market": market, "reaction_session": str(d), "index_move_pct": move, "verified_date": ev.verified}
    z = None
    if imp:
        z = move / imp["sd_pct"]
        vals.update({"implied_sd_pct": imp["sd_pct"], "vix": imp["vix"], "vix_date": imp["vix_date"], "surprise_z": z})
    pm = {}
    for k in ev.themes:
        th = themes.get(k)
        if th is None or not th.primary:
            continue
        lv = T.load_proxy(root, th.primary)
        if lv is None:
            continue
        r = lv.astype(float).pct_change(fill_method=None).dropna()
        hist = r[r.index < pd.Timestamp(d)].iloc[-60:]
        on = r[(r.index >= pd.Timestamp(d) - pd.Timedelta(days=1)) & (r.index <= pd.Timestamp(d))]
        if len(hist) > 10 and len(on):
            mv = float(on.iloc[-1] * 100.0)
            sd = float(hist.std() * 100.0)
            pm[th.primary] = {"move_pct": mv, "typical_sd_pct": sd, "z": mv / sd if sd > 0 else None, "proxy_date": str(on.index[-1].date())}
    vals["proxies"] = pm
    if z is None:
        verdict = "no volatility-index print to compare with"
    else:
        verdict = "inside what options expected" if abs(z) < 1 else ("more than options expected" if abs(z) < 2 else "a surprise against what options expected")
    text = (f"After {ev.label} ({ev.date}): the {name} moved {move:+.2f}% on {d}" + (f", against a one-session move of {imp['sd_pct']:.2f}% (1 sd) implied by {imp['source']} {imp['vix']:.1f} "
            f"at the close before: {z:+.1f} sd, {verdict}." if imp else ". " + verdict + "."))
    for pk, v in pm.items():
        text += f" {T.proxy_label(pk)} moved {v['move_pct']:+.2f}% (typical day {v['typical_sd_pct']:.2f}%)."
    return {"text": text, "values": vals}


def upcoming(asof: date, days: int = 14, market: Optional[str] = None, events: Optional[List[Event]] = None) -> List[Event]:
    ev = events if events is not None else load_events()
    return [e for e in ev if asof <= e.date <= asof + timedelta(days=days) and (market is None or market in e.markets)]


def recent(asof: date, days: int = 14, market: Optional[str] = None, events: Optional[List[Event]] = None) -> List[Event]:
    ev = events if events is not None else load_events()
    return [e for e in ev if asof - timedelta(days=days) <= e.date < asof and (market is None or market in e.markets)]


def _store(con, market: str, ev: Event, kind: str, theme: str, asof: date, note: dict) -> None:
    con.execute("DELETE FROM sentiment_event_notes_s79 WHERE market=? AND event_id=? AND kind=? AND theme=?", [market, ev.id, kind, theme])
    con.execute("INSERT INTO sentiment_event_notes_s79 VALUES (?,?,?,?,?,?,?,?)", [market, ev.id, kind, theme, asof, note["text"], json.dumps(note["values"], default=str), datetime.now()])


def run_notes(con, root, market: str, asof: date, ahead_days: int = 7, back_days: int = 14, events: Optional[List[Event]] = None) -> dict:
    """Write the scenario notes of events in the next `ahead_days` and the surprise notes of events of the last `back_days` that have no surprise note yet."""
    themes = T.load_themes(market)
    out = {"scenario": 0, "surprise": 0}
    for ev in upcoming(asof, ahead_days, market, events):
        for k in ev.themes:
            if k in themes:
                _store(con, market, ev, "scenario", k, asof, scenario_note(root, ev, market, themes[k], asof))
                out["scenario"] += 1
    for ev in recent(asof, back_days, market, events) + [e for e in upcoming(asof, 1, market, events) if e.date == asof]:
        have = con.execute("SELECT 1 FROM sentiment_event_notes_s79 WHERE market=? AND event_id=? AND kind='surprise'", [market, ev.id]).fetchone()
        if have:
            continue
        s = surprise(root, ev, market, themes, asof)
        if s:
            _store(con, market, ev, "surprise", "all", asof, s)
            out["surprise"] += 1
    return out
