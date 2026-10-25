"""The thesis tracker (S46, PLAN A7 companion workflow 2): a view the prices cannot show, tracked with evidence.

The investor states a thesis ("AI is a bubble of circular financing") with the words and sectors that mark it, and
optionally a conditional action: keep a share of new money in a liquid fund until the thesis expires. Each night:
    evidence   filings and news of the last 30 days whose title or text carries the thesis words (counted, the latest
               listed with their sources); the model does not judge for or against
    exposure   the share of the investable total in holdings of the named sectors or whose names carry the words
    action     its cost and protection over a year, by the Monte Carlo engine: the target mix against the same mix with
               `hold_cash` of it in debt (median, bad 5%, chance of a fall beyond 35% on any day)
    expiry     on the expiry date a question asks the investor to decide (keep, extend, or end it)
    results    S52 Q6: for the holdings it concerns, the next quarter's revenue and margin range before the result, the
               result against it after (ESTIMATES, quant/tfm2_live.py)
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from pflab.pm.store import next_id


def add(con, text: str, keywords: List[str], sectors: List[str], months: int = 12, hold_cash: float = 0.0,
        now: Optional[datetime] = None) -> int:
    if not keywords:
        raise ValueError("a thesis needs words that mark it in filings and news")
    if not 0 <= hold_cash < 1:
        raise ValueError("hold_cash is a share of new money, between 0 and 1")
    now = now or datetime.now()
    from dateutil.relativedelta import relativedelta
    tid = next_id(con, "theses", "thesis_id")
    exp = now.date() + relativedelta(months=months)
    con.execute("INSERT INTO theses VALUES (?,?,?,?,?,?,?,?,?,?)",
                [tid, now, text, json.dumps([k.lower() for k in keywords]), json.dumps(sectors), hold_cash, exp, "open",
                 None, None])
    return tid


def evidence(con, keywords: List[str], asof: date, days: int = 30, show: int = 5) -> dict:
    rx = re.compile("|".join(re.escape(k) for k in keywords), re.I)
    rows = con.execute("""SELECT kind, published_at, title, source FROM kg_docs WHERE kind IN ('filing','article','analyst_note')
                          AND published_at > ? AND published_at <= ? ORDER BY published_at DESC""",
                       [datetime.combine(asof - timedelta(days=days), datetime.min.time()),
                        datetime.combine(asof, datetime.max.time())]).fetchall()
    hits = [r for r in rows if rx.search(r[2] or "")]
    return {"documents": len(hits), "latest": [f"{r[1]:%d-%b} {r[0]} ({r[3]}): {(r[2] or '')[:140]}" for r in hits[:show]]}


def exposure(con, keywords: List[str], sectors: List[str], asof: date) -> dict:
    from pflab.calc import valuation as val
    from pflab.ledger import events as ev
    from pflab.ledger.book import Ledger
    from pflab.plan import monthly
    pf = val.store_price_fn(con)
    v = val.value_ledger(Ledger.replay(ev.load(con), upto=asof), pf, asof)
    inst = {r[0]: (r[1] or "", r[2] or "") for r in con.execute("SELECT isin, name, sector FROM instruments").fetchall()}
    rx = re.compile("|".join(re.escape(k) for k in keywords), re.I) if keywords else None
    sec = {s.lower() for s in sectors}
    hit, isins = 0.0, []
    for r in v.positions.itertuples():
        name, s = inst.get(r.isin, ("", ""))
        if r.value == r.value and (s.lower() in sec or (rx and rx.search(name))):
            hit += float(r.value)
            isins.append(r.isin)
    total = float(v.total) + sum(monthly.fd_debt(con, asof)[0].values())
    return {"rupees": hit, "share": hit / total if total else 0.0, "isins": sorted(set(isins))}


def results(con, isins: List[str], asof: date) -> List[str]:
    """S52 Q6 lines for the matched companies (their newest quarter: a range before the result, a surprise after)."""
    from pflab.data import data_dir
    from pflab.quant import tfm2_live as fl
    out = []
    for i in isins:
        if not str(i).startswith("INE"):
            continue
        sym = (con.execute("SELECT symbol FROM instruments WHERE isin=?", [i]).fetchone() or [None])[0]
        scrip = fl.scrip_of(data_dir(), i, asof)
        if scrip:
            out += fl.results_lines(con, scrip, sym)
    return out


def action_cost(con, hold_cash: float, root=None) -> Optional[dict]:
    """One year: target mix vs the same with `hold_cash` of it in debt (block engine, any-day falls)."""
    if hold_cash <= 0:
        return None
    from pflab.data import data_dir
    from pflab.plan import targets as tg
    from pflab.risk import montecarlo as mc
    root = root or data_dir()
    t = tg.load()
    base = mc.target_mix(t, mc.fund_names(con, t))
    held = {k: v * (1 - hold_cash) for k, v in base.items()}
    held["debt"] = held.get("debt", 0.0) + hold_cash
    res = mc.simulate(mc.history(root), {"target": base, "with cash": held}, years=1, n=5000,
                      Rd=mc.history_daily(root))
    pick = lambda m: {"median": res[m]["block"]["y1"]["p50"], "bad5": res[m]["block"]["y1"]["p5"],
                      "fall35": res[m]["block"]["p_fall_beyond_limit_any_day"]}
    return {"target": pick("target"), "with_cash": pick("with cash")}


def update(con, asof: date, now: Optional[datetime] = None, with_cost: bool = True) -> List[dict]:
    from pflab.agents import questions as qs
    now = now or datetime.now()
    out = []
    for tid, text, kw, sc, hold, exp in con.execute(
            "SELECT thesis_id, text, keywords_json, sectors_json, hold_cash, expires FROM theses WHERE status='open'").fetchall():
        kw, sc = json.loads(kw), json.loads(sc)
        e = {"evidence": evidence(con, kw, asof), "exposure": exposure(con, kw, sc, asof),
             "action": action_cost(con, hold) if with_cost else None, "expires": str(exp)}
        e["results"] = results(con, e["exposure"]["isins"], asof)
        con.execute("UPDATE theses SET last_checked=?, evidence_json=? WHERE thesis_id=?", [now, json.dumps(e, default=str), tid])
        if asof >= exp:
            qs.ask(con, "thesis", f"thesis:{tid}:expired", f"Thesis #{tid} (\"{text[:80]}\") reached its expiry {exp}: "
                   "keep its action, extend it, or end it?", now)
        out.append({"id": tid, "text": text, **e})
    return out


def render(rows: List[dict]) -> str:
    if not rows:
        return "No open theses. Add one: pflab thesis add \"text\" --keywords a,b [--sectors X] [--hold-cash 0.2] [--months 12]"
    L = []
    for r in rows:
        ex = r["exposure"]
        L.append(f"#{r['id']} {r['text']} (expires {r['expires']})")
        L.append(f"  evidence: {r['evidence']['documents']} filing/news item(s) in 30 days carry its words")
        L += [f"    {x}" for x in r["evidence"]["latest"]]
        L.append(f"  your exposure: Rs {ex['rupees']:,.0f} ({ex['share']:.1%} of the total)")
        L += [f"  results (S52): {x}" for x in r.get("results", [])]
        a = r.get("action")
        if a:
            L.append(f"  its action over a year (ESTIMATE): median Rs 1 -> {a['with_cash']['median']:.3f} vs "
                     f"{a['target']['median']:.3f} without; bad 5% {a['with_cash']['bad5']:.3f} vs {a['target']['bad5']:.3f}; "
                     f"chance of a fall beyond 35% {a['with_cash']['fall35']:.1%} vs {a['target']['fall35']:.1%}")
    return "\n".join(L)
