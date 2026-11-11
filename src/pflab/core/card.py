"""The book card (S80): about 4,000-6,000 tokens of plain text written by code at each close, the one picture the strategist reads (phase 2). The same layout every time (so
a cached prompt prefix stays valid). Code only; nothing here calls a model. Sections: BOOK, ALLOCATION TARGET, RISK, FORECAST, STORYLINES, POLICIES, LAST 10 DECISIONS, CHANGED.
STORYLINES says "none yet" until phase 3 lands; CHALLENGERS say none until phase 2.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace
from typing import Dict, Optional

import numpy as np

MAX_CHARS = 24000                                       # about 6,000 tokens (4 characters a token)


def _pct(x: Optional[float], d: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def portfolio_vol(state: dict) -> Optional[float]:
    """Annual volatility of the book from the shrunk covariance of its priced holdings (cash counts as zero risk)."""
    from pflab.construct import risk
    from pflab.core import state as st
    rows = [r for r in state["rows"] if r["buyable"] and r["value"] > 0]
    if not rows or state["value"] <= 0:
        return None
    panel = st.closes_panel(state["con"], [r["isin"] for r in rows], state["day"], int(state["cfg"]["baseline"]["vol_window"])) if state.get("con") is not None else None
    if panel is None or not panel.shape[1]:
        return None
    cov, _ = risk.shrunk_cov(risk.daily_returns(panel, state["day"], window=int(state["cfg"]["baseline"]["vol_window"])))
    have = [r for r in rows if r["isin"] in cov.columns]
    if not have:
        return None
    w = np.array([r["value"] / state["value"] for r in have])
    c = cov.loc[[r["isin"] for r in have], [r["isin"] for r in have]].to_numpy(float)
    return float(np.sqrt(max(w @ c @ w, 0.0)))


def _forecast_lines(con) -> str:
    try:
        from pflab.hq.tools_s79 import t_forecast
        f = t_forecast.forecast_now(SimpleNamespace(con=con), {})
        hs = f.get("horizons") or {}
        if not hs:
            return "none made yet"
        bits = []
        for h in sorted(hs, key=int):
            q = hs[h].get("return_quantiles_percent") or {}
            ks = sorted(q, key=lambda k: float(k))
            if ks:
                bits.append(f"{h} sessions: median {q[min(ks, key=lambda k: abs(float(k) - 0.5))]:+.2f}%, 80% range {q[ks[0]]:+.2f}% to {q[ks[-1]]:+.2f}%")
        return f"{f.get('subject')} from the close of {f.get('made_at_close_of')}: " + "; ".join(bits) if bits else "none made yet"
    except Exception:
        return "unreadable"


def _views(con) -> str:
    try:
        from pflab.core import views
        return views.record_text(con)
    except Exception:
        return "unreadable"


def _storylines(con, day) -> str:
    try:
        from pflab.story import numbers
        return numbers.summary_text(con, day)
    except Exception:
        return "unreadable"


def _decisions(con) -> str:
    rows = con.execute("SELECT d.decision_id, d.made_at, d.action, d.symbol, d.status, c7.outcome, c28.outcome FROM paper_decisions d "
                       "LEFT JOIN paper_claims c7 ON c7.decision_id = d.decision_id AND c7.horizon_days = 7 "
                       "LEFT JOIN paper_claims c28 ON c28.decision_id = d.decision_id AND c28.horizon_days = 28 ORDER BY d.decision_id DESC LIMIT 10").fetchall()
    if not rows:
        return "none yet"
    return "\n".join(f"  #{i} {str(t)[:10]} {a} {s or 'cash'} ({st}); 7-day claim: {o7 or 'not due'}; 28-day claim: {o28 or 'not due'}" for i, t, a, s, st, o7, o28 in rows)


def _policies(con, day: date) -> str:
    from pflab.paper import benchmark
    pol = con.execute("SELECT policy_id, status, promoted_at FROM core_policies_s80 ORDER BY status, policy_id").fetchall()
    champ = next((p for p in pol if p[1] == "champion"), None)
    chal = []
    for p in pol:
        if p[1] != "challenger":
            continue
        try:
            from pflab.lab import service as lab, shadow
            rec, hist = shadow.record(con, p[0]), lab.latest_run(con, p[0], "history")
            chal.append(f"{p[0]} (history excess {hist['score']['excess_cagr']:+.1%}, deflated Sharpe {hist['score'].get('dsr', 0):.2f}; shadow {rec['sessions']} session(s), {rec['excess']:+.2%} vs the champion's stand-in)"
                        if hist else p[0])
        except Exception:
            chal.append(p[0])
    try:
        b = benchmark.status(con, "IN", day)
    except Exception:
        b = {}
    score = (f"book {_pct(b['book']['return'], 2)} vs its benchmark {_pct(b['benchmark']['return'], 2)} (excess {_pct(b['excess'], 2)}) since {b['since']}; worst fall {_pct(b.get('worst_fall_book'), 1)}"
             if b.get("started") and b.get("book", {}).get("return") is not None else "no score yet (the benchmark is recorded once the book has marked days)")
    runs = con.execute("SELECT count(*), count(*) FILTER (WHERE status='traded') FROM core_runs_s80").fetchone()
    return (f"champion: {champ[0] if champ else 'none'}" + (f" since {str(champ[2])[:10]}" if champ and champ[2] else "") + f"; {runs[0]} close(s) run, {runs[1]} with trades\n"
            f"  score: {score}\n  challengers: {'; '.join(chal) if chal else 'none'}")


def _changed(con, facts: dict, prev: Optional[dict]) -> str:
    if not prev:
        return "first card: nothing to compare with"
    out = []
    v0, v1 = prev.get("value"), facts["value"]
    if v0:
        out.append(f"value {(v1 / v0 - 1) * 100:+.2f}% (Rs {v0:,.0f} to Rs {v1:,.0f}; includes any top-up)")
    moved = []
    for k in sorted(set(prev.get("weights", {})) | set(facts["weights"])):
        a, b = prev.get("weights", {}).get(k, 0.0), facts["weights"].get(k, 0.0)
        if abs(b - a) >= 0.01:
            moved.append(f"{facts['symbols'].get(k) or prev.get('symbols', {}).get(k) or k} {a * 100:.1f}% to {b * 100:.1f}%")
    out.append("weights moved 1 point or more: " + (", ".join(moved) if moved else "none"))
    if prev.get("gauge") != facts["gauge"]:
        out.append(f"fall gauge {'FIRED' if facts['gauge'] else 'cleared'}")
    if prev.get("breaker") != facts["breaker"]:
        out.append(f"circuit breaker {'ON' if facts['breaker'] else 'off'}")
    out.append(f"orders placed at this close: {facts['orders']}")
    return "; ".join(out)


def _us(con, day) -> Optional[dict]:
    """S82 (A57): the US sub-book and the whole book for the card (`pflab.us.report.card_summary`); None when unreadable."""
    try:
        from pflab.us import report
        return report.card_summary(con, day)
    except Exception:
        return None


def _us_lines(us: Optional[dict]) -> tuple:
    if not us:
        return "WHOLE BOOK: unreadable", "US SUB-BOOK: unreadable"
    w, ish = us.get("whole_book") or {}, us.get("international_share") or {}
    whole = (f"WHOLE BOOK (rupee book + US sub-book in rupees): Rs {w['whole_inr']:,.0f} = rupee book Rs {w['rupee_book_inr']:,.0f} + US sub-book Rs {w['us_book_inr']:,.0f}"
             + (f" at USD/INR {w['fx']:.2f} ({w['fx_source']})" if w.get("fx") else "") + f"; international share {_pct(ish.get('share'))} of the whole book, target {_pct(ish.get('target'), 0)}: {ish.get('reason') or 'n/a'}"
             if w.get("whole_inr") is not None else "WHOLE BOOK: unreadable")
    if not us.get("open"):
        return whole, "US SUB-BOOK: not open yet (it opens by a transfer out of the rupee book's cash)"
    hs = "; ".join(f"{h['symbol']} {h['shares']:g} shares USD {h['value_usd'] or 0:,.0f}" for h in us.get("holdings", [])) or "no shares yet"
    cash = us.get("cash") or {}
    return whole, f"US SUB-BOOK: {hs}; cash USD {cash.get('usd', 0):,.0f}; {us.get('open_orders', 0)} open order(s); {us.get('gap_risk')}"


def build(con, state: dict, decision: dict, placed: list, prev: Optional[dict] = None) -> tuple:
    """-> (text, facts). `state` is `core.state.build`, `decision` the policy's output, `placed` the orders of this close."""
    from pflab.paper import book
    day, total = state["day"], state["value"]
    state = dict(state, con=con)
    facts = {"value": total, "weights": {r["isin"]: r["value"] / total for r in state["rows"] if total > 0}, "symbols": {r["isin"]: r["symbol"] for r in state["rows"]},
             "gauge": bool(state["gauge"]["fired"]), "breaker": bool(state["breaker"]["on"]), "orders": len(placed)}
    held = "; ".join(f"{r['symbol']} {r['value'] / total * 100:.1f}% ({r['klass']})" for r in sorted(state["rows"], key=lambda r: -r["value"])) if total > 0 else "none"
    cash = (state["cash"] + state["bank"]) / total if total > 0 else 0.0
    tgt = state["target"]
    ret = book.returns(con)
    vol = portfolio_vol(state)
    us = _us(con, day)
    facts["us"] = us
    whole_line, us_line = _us_lines(us)
    lines = [
        f"BOOK CARD, close of {day} (written by code; the same layout every day)",
        f"BOOK: value Rs {total:,.0f}; cash and bank {cash * 100:.1f}%; holdings: {held}",
        whole_line,
        us_line,
        "ALLOCATION TARGET: " + (f"#{tgt['id']} " + ", ".join(f"{k} {v:g}%" for k, v in tgt["classes"].items()) + (("; sectors " + ", ".join(f"{k} {v:g}%" for k, v in tgt["sectors"].items())) if tgt["sectors"] else "")
                                if tgt else "none active: the baseline holds the class mix the book has"),
        f"RISK: book volatility {_pct(vol)} a year (shrunk covariance of daily returns); worst fall so far {_pct(ret['worst_fall'] if ret else None)}; "
        f"drawdown from its high {_pct(state['breaker'].get('drawdown'))}, circuit breaker {'ON (no buying)' if state['breaker']['on'] else 'off'}; fall gauge: {state['gauge']['why']} ({'FIRED' if state['gauge']['fired'] else 'not fired'})",
        "FORECAST: " + _forecast_lines(con),
        "STORYLINES: " + _storylines(con, day),
        "POLICIES: " + _policies(con, day),
        "TACTICAL VIEWS: " + _views(con),
        "LAST 10 DECISIONS (with how their claims scored):\n" + _decisions(con),
        "CHANGED SINCE THE LAST CARD: " + _changed(con, facts, prev),
    ]
    ps = _picks_score(con, day)                                  # S83 L4: the picks scorecard (the picks agent adds the PICKS section under facts["picks"]; not here)
    if ps:
        facts["picks_score"] = ps["json"]
        lines.append("PICKS SCORE (after estimated tax, against the index):\n" + ps["text"])
    pk = _picks(con, day)                                        # S83 L3: the PICKS section (each pick, the sleeve's share and why, the last "what I learned")
    if pk:
        facts["picks"] = {k: v for k, v in pk.items() if k != "text"}
        lines.append(pk["text"])
    return "\n".join(lines)[:MAX_CHARS], facts


def _picks(con, day) -> Optional[dict]:
    """The PICKS section (`core/picks_card.build`); None when it cannot be read (the card never fails for it)."""
    try:
        from pflab.core import picks_card
        return picks_card.build(con, day)
    except Exception:
        return None


def _picks_score(con, day) -> Optional[dict]:
    """The scorecard of each market for the card: {'json': {market: scorecard}, 'text': plain words}. None when it cannot be read (the card never fails for it)."""
    try:
        from pflab.core import pick_score
        return {"json": {m: pick_score.scorecard(con, m, day) for m in ("IN", "US")}, "text": "\n".join(pick_score.scorecard_text(con, m) for m in ("IN", "US"))}
    except Exception:
        return None


def write(con, now: datetime, state: dict, decision: dict, placed: list) -> dict:
    """Build today's card and store it (`core_cards_s80`, one row a day; a re-run replaces it). Never raises into the loop."""
    prev = None
    r = con.execute("SELECT facts_json FROM core_cards_s80 WHERE day < ? ORDER BY day DESC LIMIT 1", [state["day"]]).fetchone()
    if r and r[0]:
        prev = json.loads(r[0])
    text, facts = build(con, state, decision, placed, prev)
    con.execute("DELETE FROM core_cards_s80 WHERE day=?", [state["day"]])
    con.execute("INSERT INTO core_cards_s80 VALUES (?,?,?,?,?)", [state["day"], now, text, len(text) // 4, json.dumps(facts)])
    return {"tokens": len(text) // 4}


def today_extras(con) -> dict:
    """S82: the two small JSON blocks Today shows beside the book: `fills` (is the fill-cost model calibrated from real fills, or the defaults: `core.fills.calibration_status`) and
    `strategist` (its newest note, any allocation it put forward and the session's cost: `lab.service.latest_strategist_note`). Each is None when unreadable; never raises."""
    from pflab.core import fills
    from pflab.lab import service
    out: dict = {}
    for key, fn in (("fills", lambda: fills.calibration_status(con)), ("strategist", lambda: service.latest_strategist_note(con))):
        try:
            out[key] = fn()
        except Exception:
            out[key] = None
    try:                                                                    # S83 L8: "no picks yet: <reason>" until the system has named a pick; the sleeve's share and its picks per market
        from pflab.core import picks_card
        from pflab.lab import first_session_s82
        b = picks_card.build(con, date.today())
        out["picks"] = {"line": first_session_s82.picks_line(con), "IN": b["IN"], "US": b["US"], "learned": b["learned"]}
    except Exception:
        out["picks"] = None
    return out


def latest(con) -> Optional[str]:
    r = con.execute("SELECT text FROM core_cards_s80 ORDER BY day DESC LIMIT 1").fetchone()
    return r[0] if r else None
