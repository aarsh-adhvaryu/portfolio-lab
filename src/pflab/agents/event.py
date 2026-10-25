"""Event research (S46, PLAN A7 companion workflow 1): The investor sends a piece of news; the agents answer from evidence.

    1 company       the list/held company the text names (aliases), else an NSE symbol written in it
    2 confirmation  an exchange filing of that company in the last 7 days sharing at least two words of substance
                    with the news: CONFIRMED (with the filing), else UNCONFIRMED (no filing says it yet)
    3 peers         same-sector companies in the Nifty 500, and companies named alongside it in the news
    4 history       how the company and its peers moved after filings of the same kind (event-study template)
    5 plan          computed by code: room under the per-stock cap, a maximum price (the last close: the plan does not
                    chase a move) and three staged buys; tickets for the investor to enter himself. It never places an order.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

STOP = set("the a an and or of in on to for with by at from is are was were be has have had its it this that as "
           "company limited ltd india indian shares share stock news says said will would new deal".split())


def words(s: str) -> set:
    return {w for w in re.findall(r"[a-z]{4,}", s.lower()) if w not in STOP}


def find_company(con, text: str) -> Optional[dict]:
    from pflab.agents import tools as T
    from pflab.plan import guards as gd
    lst = gd.stock_list()
    for s in lst:
        if re.search(r"\b" + re.escape(s["symbol"]) + r"\b", text, re.I):
            return s
    for sym, names in T.question_aliases(con, lst).items():
        if any(re.search(r"\b" + re.escape(n) + r"\b", text, re.I) for n in names):
            return next(s for s in lst if s["symbol"] == sym)
    for tok in re.findall(r"\b[A-Z][A-Z0-9&]{2,}\b", text):
        r = con.execute("SELECT isin FROM instruments WHERE symbol = ? ORDER BY valid_to DESC NULLS FIRST LIMIT 1",
                        [tok]).fetchone()
        if r:
            return {"symbol": tok, "isin": r[0]}
    return None


def confirm(con, isin: str, text: str, asof: date, days: int = 7) -> Optional[dict]:
    rows = con.execute("""SELECT d.published_at, d.title, d.url, d.attrs_json FROM kg_edges e JOIN kg_docs d ON d.doc_id = e.src
                          WHERE e.dst = ? AND d.kind = 'filing' AND d.published_at >= ? ORDER BY d.published_at DESC""",
                       [f"company:{isin}", datetime.combine(asof - timedelta(days=days), datetime.min.time())]).fetchall()
    w = words(text)
    best = max(((len(w & words(t or "")), (pub, t, url, a)) for pub, t, url, a in rows), default=(0, None),
               key=lambda x: x[0])
    if best[0] >= 2:
        pub, t, url, a = best[1]
        import json
        return {"at": pub, "title": t, "url": url, "subcategory": (json.loads(a or "{}")).get("subcategory")}
    return None


def peers(con, isin: str, root=None, n: int = 5) -> List[str]:
    sec = con.execute("SELECT sector FROM instruments WHERE isin = ? AND sector IS NOT NULL LIMIT 1", [isin]).fetchone()
    out: List[str] = []
    if sec:
        out = [r[0] for r in con.execute("""SELECT DISTINCT isin FROM instruments WHERE sector = ? AND isin <> ?
                                            AND isin LIKE 'INE%' LIMIT 40""", [sec[0], isin]).fetchall()]
    co = [r[0].split(":", 1)[1] for r in con.execute(
        """SELECT e2.dst FROM kg_edges e1 JOIN kg_edges e2 ON e1.src = e2.src
           WHERE e1.dst = ? AND e1.rel = 'mentions' AND e2.rel = 'mentions' AND e2.dst <> e1.dst
           GROUP BY e2.dst ORDER BY count(*) DESC LIMIT ?""", [f"company:{isin}", n]).fetchall()]
    return list(dict.fromkeys(co + out))[: n + len(co)]


def research(con, text: str, asof: date, root=None) -> str:
    from pflab.data import data_dir
    from pflab.plan import guards as gd
    from pflab.plan import trader
    from pflab.quant import event_study as es
    root = root or data_dir()
    c = find_company(con, text)
    if not c:
        return "I could not tell which company this is about. Name it (or its NSE symbol) and send it again."
    sym, isin = c["symbol"], c["isin"]
    L = [f"Event research: {sym} ({isin}), {asof}"]
    f = confirm(con, isin, text, asof)
    L.append(f"1. CONFIRMED by an exchange filing of {f['at']:%d-%b %H:%M}: \"{f['title']}\" {f['url'] or ''}" if f else
             "1. UNCONFIRMED: no filing of this company in the last 7 days matches the news (check again after the next "
             "filings collection; treat the news as unverified until then).")
    pr = peers(con, isin, root)
    names = dict(con.execute(f"SELECT isin, coalesce(symbol, name) FROM instruments WHERE isin IN "
                             f"({','.join('?' * len(pr)) or "''"})", pr).fetchall()) if pr else {}
    L.append("2. Peers (named alongside it in the news first, then its sector): "
             + (", ".join(names.get(i, i) for i in pr) if pr else "none found in the instrument master"))
    sub = f.get("subcategory") if f else None
    kind = {"subcategories": [sub]} if sub else {"headline_regex": "|".join(sorted(words(text))[:6]) or "x^"}
    for label, who in ((sym, [isin]), ("peers", pr)):
        if not who:
            continue
        res = es.run(root, "2015-01-01", "2025-12-31", isins=who, **kind)
        L.append("3. " + es.render(res, f"History for {label} ({'same filing kind: ' + sub if sub else 'similar headlines'})"))
    g = {x.symbol: x for x in gd.check_all(con, asof, gd.stock_list())}.get(sym)
    L.append(f"4. Safety checks: {g.verdict.upper()}" + (f" ({'; '.join(g.reasons)})" if g and g.reasons else "")
             if g else "4. Safety checks: not on your list, so not checked: add it with pflab list add " + sym)
    L.append("5. " + plan_text(con, sym, isin, asof, g.verdict if g else None))
    return "\n".join(L)


def plan_text(con, sym: str, isin: str, asof: date, verdict: Optional[str]) -> str:
    """Room under the per-stock cap, at most the last close, three staged buys. No buy for a FAIL or unknown name."""
    from pflab import _toml
    from pflab.calc import valuation as val
    from pflab.ledger import events as ev
    from pflab.ledger.book import Ledger
    from pflab.plan import advisor, monthly, rebalance, trader
    from pflab.plan import targets as tg
    from pflab.risk import report as riskreport
    if verdict != "ok":
        return f"Plan: none: the safety verdict is {verdict or 'not available'}; the system proposes buys only for OK names."
    t = tg.load()
    pf = val.store_price_fn(con)
    v = val.value_ledger(Ledger.replay(ev.load(con), upto=asof), pf, asof)
    vals = rebalance.bucket_values(v, riskreport.instruments_frame(con), t, monthly.fd_debt(con, asof)[0])
    cap = float(_toml.load(tg.default_path()).get("stocks", {}).get("max_weight", advisor.DEFAULT_MAX_WEIGHT)) * sum(vals.values())
    held = sum(float(r.value) for r in v.positions.itertuples() if r.isin == isin and r.value == r.value)
    p = pf(isin, asof)
    if p is None:
        return "Plan: no price on record."
    room = max(cap - held, 0.0)
    qty = int(room // p.value)
    if qty < 3:
        return f"Plan: no room: you hold Rs {held:,.0f} against a cap of Rs {cap:,.0f} for one stock."
    parts = [qty // 3 + (1 if k < qty % 3 else 0) for k in range(3)]
    tk = trader.tickets(sym, parts[0], float(p.value), trader.decision())
    return (f"Plan (rules, not a forecast): room under the cap Rs {room:,.0f} = up to {qty} shares at most at the last "
            f"close {p.value:,.2f}; three stages {parts}, the next only after the last fills, none above {p.value:,.2f}. "
            f"First ticket: {tk[0]}")
