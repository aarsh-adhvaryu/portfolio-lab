"""Builders that fill the knowledge graph from the system's own sources (S38). Each is idempotent.

    portfolio   person:investor -owns-> company (from the ledger: periods of a non-zero position), -watches-> list
                names, company -in_sector-> sector (instrument master)
    filings     BSE announcements of list/held companies -> doc:filing -about-> company at the dissemination time
                (insider and SAST disclosures among them)
    deals       S63: NSE bulk and block deals -> doc:deal -about-> company on the deal's date
    holdings    S63: quarterly shareholding (promoters, pledges, institutions) -> doc:holding, 21 days after the quarter
    results     filed quarterly results (PM store) -> doc:result -about-> company at usable_from
    guards      company -guard_status-> verdict:<v> (state; a change closes the old verdict)
    articles    GDELT GKG rows -> doc:article -mentions-> company; -has_theme-> theme; -names-> org/person
"""
from __future__ import annotations

import glob
import json
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from pflab import _duck
import pandas as pd

from pflab.kg import clean as kc
from pflab.kg import graph as g

ME = "person:investor"
STRIP = re.compile(r"\b(limited|ltd\.?|company|co\.?)\b", re.I)


def universe(con, stock_list: List[dict]) -> pd.DataFrame:
    """Held and list companies: isin, symbol, name, sector, scrip."""
    from pflab.ledger import events as ev
    from pflab.ledger.book import Ledger
    from pflab.pm import today
    held = {i for (_, i), q in Ledger.replay(ev.load(con)).positions().items() if q} | today.kite_held(con)   # Kite until the statements are read
    rows = {s["isin"]: {"isin": s["isin"], "symbol": s["symbol"], "scrip": s.get("scrip"),
                        "aliases": list(s.get("aliases", []))} for s in stock_list}
    for i in held:
        rows.setdefault(i, {"isin": i, "symbol": None, "scrip": None, "aliases": []})
    inst = con.execute(f"SELECT isin, symbol, name, sector FROM instruments WHERE isin IN ({','.join('?' * len(rows))})",
                       list(rows)).fetchall() if rows else []
    for isin, sym, name, sector in inst:
        rows[isin].update({"symbol": rows[isin]["symbol"] or sym, "name": name, "sector": sector})
    # always these columns, even with no holdings and no list (a fresh profile): callers select u["isin"] without checking
    return pd.DataFrame(list(rows.values())).reindex(columns=["isin", "symbol", "name", "sector", "scrip", "aliases"])


def aliases(u: pd.DataFrame) -> Dict[str, List[str]]:
    out = {}
    for r in u.itertuples():
        if not str(r.isin).startswith("INE"):                  # SGBs and funds: no news aliasing
            continue
        a = [x.lower() for x in (getattr(r, "aliases", None) or [])]   # from stock_list.toml, where the name misleads
        nm = getattr(r, "name", None)
        if isinstance(nm, str) and nm:
            core = STRIP.sub("", nm).strip(" .,").lower()
            if len(core) >= 6 and core not in a:
                a.append(core)
        out[r.isin] = a
    return out


def headline_names(u: pd.DataFrame) -> Dict[str, List[str]]:
    """isin -> names an article headline may use for the company: its aliases, its symbol, and the first word of its
    name when no other company in `u` shares it. No names live in the code."""
    first = lambda nm: (STRIP.sub("", nm).lower().split() or [""])[0].strip(" .,") if isinstance(nm, str) else ""  # noqa: E731
    count: Dict[str, int] = {}
    for r in u.itertuples():
        w = first(getattr(r, "name", None))
        count[w] = count.get(w, 0) + 1
    al, out = aliases(u), {}
    for r in u.itertuples():
        names = list(al.get(r.isin, []))
        if isinstance(r.symbol, str) and r.symbol:
            names.append(r.symbol.lower())
        w = first(getattr(r, "name", None))
        if len(w) >= 4 and count.get(w) == 1:
            names.append(w)
        out[r.isin] = list(dict.fromkeys(names))
    return out


def names_for(con, isins: List[str], stock_list: List[dict]) -> Dict[str, List[str]]:
    """`headline_names` for `isins`, judged against the stock list (so a shared first word is never used)."""
    rows = {s["isin"]: {"isin": s["isin"], "symbol": s["symbol"], "aliases": list(s.get("aliases", []))}
            for s in stock_list}
    for i in isins:
        rows.setdefault(i, {"isin": i, "symbol": None, "aliases": []})
    for isin, sym, name in con.execute(f"SELECT isin, symbol, name FROM instruments WHERE isin IN "
                                       f"({','.join('?' * len(rows))})", list(rows)).fetchall() if rows else []:
        rows[isin].update({"symbol": rows[isin]["symbol"] or sym, "name": name})
    hn = headline_names(pd.DataFrame(list(rows.values())))
    return {i: hn.get(i, []) for i in isins}


HEADLINE_WORDS = 8


def is_about(title: str, names: List[str], k: int = HEADLINE_WORDS) -> bool:
    """True when one of `names` is among the first `k` words of an article's headline (2026-10-18: articles that name
    a company only in passing, as a trading venue, a peer or a sector member, reached the analyst as news about it)."""
    head = " ".join(re.findall(r"[a-z0-9]+", (title or "").lower())[:k])
    return any(re.search(r"\b" + re.escape(" ".join(re.findall(r"[a-z0-9]+", n))) + r"\b", head) for n in names if n)


def portfolio(con, u: pd.DataFrame, stock_list: List[dict], now: Optional[datetime] = None) -> int:
    from pflab.ledger import events as ev
    n = 0
    g.node(con, ME, "person", "The investor", now=now)
    for r in u.itertuples():
        cid = f"company:{r.isin}"
        g.node(con, cid, "company", getattr(r, "name", None) or r.symbol, {"symbol": r.symbol}, now)
        sector = getattr(r, "sector", None)
        if isinstance(sector, str) and sector:
            g.node(con, f"sector:{sector}", "sector", sector, now=now)
            n += g.edge(con, cid, "in_sector", f"sector:{sector}", date(2000, 1, 1), "instruments", now=now)
    # ownership periods from the ledger: a position opening (0 -> >0) and closing (>0 -> 0)
    qty: Dict[str, float] = {}
    for e in ev.load(con):
        if e.kind not in ("buy", "sell", "ipo_allot") or not e.isin:
            continue
        before = qty.get(e.isin, 0.0)
        qty[e.isin] = before + (e.qty if e.kind != "sell" else -e.qty)
        cid = f"company:{e.isin}"
        if before <= 1e-9 < qty[e.isin]:
            g.node(con, cid, "company", now=now)
            n += g.edge(con, ME, "owns", cid, e.date, "ledger", f"event {e.event_id}", now=now)
        elif before > 1e-9 >= qty[e.isin]:
            g.close(con, ME, "owns", cid, e.date)
    for s in stock_list:
        n += g.edge(con, ME, "watches", f"company:{s['isin']}", date.today(), "stock_list", now=now)
    return n + deposits(con, now)


def deposits(con, now: Optional[datetime] = None) -> int:
    """(2026-10-31) His fixed deposits in the graph: one node a deposit, named by bank and maturity, never by number (the graph is read by the
    brain; banking details never leave the PC), owned from its term start; a deposit gone from the register or closed is no longer owned."""
    import hashlib
    from pflab.pm import fd as fdm
    n, today = 0, (now or datetime.now()).date()
    live = set()
    for f in fdm.load(con):
        nid = "deposit:" + hashlib.sha256(f"{f.bank}|{f.fd_id}".encode()).hexdigest()[:10]
        g.node(con, nid, "deposit", f"{f.bank} fixed deposit maturing {f.maturity}",
               {"bank": f.bank, "principal": f.principal, "rate_pct": round(f.rate * 100, 3), "start": str(f.term_start), "maturity": str(f.maturity),
                "maturity_amount": f.maturity_amount, "status": f.status, "reserve": f.purpose.startswith("reserve:")}, now)
        g.node(con, f"bank:{f.bank}", "org", f.bank, now=now)
        n += g.edge(con, nid, "held_at", f"bank:{f.bank}", f.term_start, "deposits", now=now)
        if f.status == "closed" and f.closed_on:
            g.close(con, ME, "owns", nid, f.closed_on)
        else:
            live.add(nid)
            n += g.edge(con, ME, "owns", nid, f.term_start, "deposits", now=now)
    for (dst,) in con.execute("SELECT dst FROM kg_edges WHERE src=? AND rel='owns' AND dst LIKE 'deposit:%' AND valid_to IS NULL", [ME]).fetchall():
        if dst not in live:
            g.close(con, ME, "owns", dst, today)
    return n


def refresh_portfolio(con, now: Optional[datetime] = None) -> int:
    """(2026-10-31) What he owns, at once after the record or the deposits change (the nightly graph job does the rest)."""
    from pflab.plan import guards as gd
    sl = gd.stock_list()
    return portfolio(con, universe(con, sl), sl, now)


def filings(con, u: pd.DataFrame, since: date, root=None, now: Optional[datetime] = None) -> int:
    from pflab.data import data_dir
    root = root or data_dir()
    scrips = {str(s): i for i, s in zip(u["isin"], u["scrip"]) if s}
    if not scrips:
        return 0
    fs = glob.glob(str(root / "bse_announcements" / "**" / "*.parquet"), recursive=True)
    df = _duck.sql(f"""select scrip_code, headline, category, subcategory, dissem_dt, attachment
                        from read_parquet({fs!r}, union_by_name=true)
                        where cast(scrip_code as varchar) in ({','.join(repr(s) for s in scrips)})
                          and dissem_dt >= TIMESTAMP '{since}'""").df()
    n = 0
    for r in df.itertuples():
        key = f"{r.scrip_code}|{r.dissem_dt}|{r.headline}"
        did = g.doc(con, "filing", key, r.dissem_dt, r.headline or "", f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{r.attachment}" if r.attachment else "",
                    "BSE", attrs={"category": r.category, "subcategory": r.subcategory}, now=now)
        n += g.edge(con, did, "about", f"company:{scrips[str(r.scrip_code)]}", r.dissem_dt, "bse_announcements", key, now=now)
    return n


def results(con, u: pd.DataFrame, now: Optional[datetime] = None) -> int:
    scrips = {str(s): i for i, s in zip(u["isin"], u["scrip"]) if s}
    if not scrips:
        return 0
    df = con.execute(f"SELECT * FROM quarterly_results WHERE scrip_code IN ({','.join('?' * len(scrips))})",
                     list(scrips)).df()
    n = 0
    for r in df.itertuples():
        cons = r.basis == "consolidated"
        key = f"{r.scrip_code}|{r.quarter_end}" + ("|consolidated" if cons else "")    # standalone keys unchanged
        title = (f"{'Consolidated results' if cons else 'Results'} for quarter ended "
                 f"{pd.Timestamp(r.quarter_end).date()}: net profit {r.net_profit} mn")
        attrs = {"revenue": r.revenue, "net_profit": r.net_profit, "pbt": r.pbt, "eps": r.eps_basic,
                 "quarter_end": str(pd.Timestamp(r.quarter_end).date()), "basis": r.basis,
                 "date_source": r.date_source}
        did = g.doc(con, "result", key, r.usable_from, title, source="BSE", attrs=attrs, now=now)
        # a parser fix corrects filed figures (2026-10-18); the date the quarter became usable never moves
        con.execute("UPDATE kg_docs SET title=?, attrs_json=? WHERE doc_id=?",
                    [title[:500], json.dumps(attrs, default=str), did])
        n += g.edge(con, did, "about", f"company:{scrips[str(r.scrip_code)]}", r.usable_from, "quarterly_results", key, now=now)
    return n


def guards(con, gs, at: datetime, now: Optional[datetime] = None) -> int:
    n = 0
    for x in gs:
        g.node(con, f"verdict:{x.verdict}", "verdict", x.verdict, now=now)
        n += g.edge(con, f"company:{x.isin}", "guard_status", f"verdict:{x.verdict}", at, "guards",
                    "; ".join(x.reasons)[:500], {"reasons": x.reasons}, now)
    return n


def articles(con, gkg: pd.DataFrame, now: Optional[datetime] = None, max_names: int = 6) -> int:
    n = 0
    for r in gkg.itertuples():
        if pd.isna(r.date):
            continue
        title = (r.url.rstrip("/").split("/")[-1].replace("-", " ")[:200]) if r.url else ""
        did = g.doc(con, "article", r.url, r.date, title, r.url, r.source, None if pd.isna(r.tone) else float(r.tone),
                    r.themes, {"india": bool(r.india), "quotes": r.quotes[:500] if isinstance(r.quotes, str) else ""}, now)
        for isin in str(r.isins).split(";"):
            if isin:
                n += g.edge(con, did, "mentions", f"company:{isin}", r.date, "gdelt_gkg", r.url, now=now)
        for t in [x for x in str(r.themes).split(";") if x][:8]:
            g.node(con, f"theme:{t}", "theme", t, now=now)
            g.edge(con, did, "has_theme", f"theme:{t}", r.date, "gdelt_gkg", r.url, now=now)
        for kind, col in (("org", r.orgs), ("person", r.persons)):
            for nm in [x for x in str(col).split(";") if x][:max_names]:
                nid = kc.canonical(con, f"{kind}:{nm.lower()}")             # S57: a merged name stays merged
                if nid == f"{kind}:{nm.lower()}":
                    g.node(con, nid, kind, nm, now=now)
                g.edge(con, did, "names", nid, r.date, "gdelt_gkg", r.url, now=now)
    return n


def deals(con, u: pd.DataFrame, since: date, root=None, now: Optional[datetime] = None) -> int:
    """S63: NSE bulk and block deals in held and listed names -> doc:deal -about-> company on the deal's date."""
    from pflab.data import data_dir, nse_deals
    syms = {str(s).upper(): i for i, s in zip(u["isin"], u["symbol"]) if isinstance(s, str) and s}
    if not syms:
        return 0
    try:
        d = nse_deals.load(root or data_dir())
    except Exception:
        return 0
    d = d[d["symbol"].isin(set(syms)) & (d["date"] >= pd.Timestamp(since))]
    n = 0
    for r in d.itertuples():
        key = f"{r.symbol}|{r.date:%Y-%m-%d}|{r.kind}|{r.side}|{r.client}|{r.quantity}"
        title = f"{r.kind.title()} deal: {r.client} {'bought' if r.side == 'BUY' else 'sold'} {int(r.quantity):,} at {r.price:g}"
        did = g.doc(con, "deal", key, r.date, title, "", "NSE", attrs={"side": r.side, "kind": r.kind}, now=now)
        n += g.edge(con, did, "about", f"company:{syms[r.symbol]}", r.date, "nse_deals", key, now=now)
    return n


def holdings(con, u: pd.DataFrame, root=None, now: Optional[datetime] = None) -> int:
    """S63: each quarter's shareholding (promoters, pledges, institutions) of held and listed names -> doc:holding
    -about-> company, dated 21 days after the quarter end (when SEBI's filing is due: point in time)."""
    from datetime import timedelta as _td
    from pflab.data import data_dir
    root = root or data_dir()
    scrips = {str(s): i for i, s in zip(u["isin"], u["scrip"]) if s}
    if not scrips:
        return 0
    try:
        s = pd.read_parquet(root / "bse_shareholding" / "summary.parquet",
                            columns=["scrip_code", "quarter_end", "status", "promoter_pct", "pledged_pct_of_promoter"])
        from pflab.data import bse_institutions as bi
        q = bi.load(root)
    except Exception:
        return 0
    s = s[s["scrip_code"].astype(str).isin(set(scrips)) & (s["status"] == "ok")]
    q = q[q["status"] == "ok"]
    q = q.set_index([q["scrip_code"].astype(str), pd.to_datetime(q["quarter_end"])])
    n = 0
    for r in s.sort_values("quarter_end").itertuples():
        qe = pd.Timestamp(r.quarter_end)
        inst = q.loc[(str(r.scrip_code), qe)] if (str(r.scrip_code), qe) in q.index else None
        inst = inst.iloc[0] if isinstance(inst, pd.DataFrame) else inst
        title = (f"Shareholding {qe:%b %Y}: promoters {r.promoter_pct:.2f}%, pledged {(r.pledged_pct_of_promoter or 0):.2f}% "
                 "of theirs" + (f"; institutions {inst['inst_pct']:.2f}% (funds {inst['mf_pct']:.2f}%, FPIs "
                                f"{inst['fpi_pct']:.2f}%)" if inst is not None else ""))
        key = f"{r.scrip_code}|{qe:%Y-%m-%d}"
        at = qe + _td(days=21)
        did = g.doc(con, "holding", key, at, title, "", "BSE", now=now)
        n += g.edge(con, did, "about", f"company:{scrips[str(r.scrip_code)]}", at, "bse_shareholding", key, now=now)
    return n


def refresh(con, asof: date, stock_list: List[dict], since_filings: date, gkg_since: Optional[date] = None,
            guards_list=None, root=None, now: Optional[datetime] = None) -> Dict[str, int]:
    """One pass of every builder (idempotent): what the nightly job runs."""
    from pflab.data import gdelt_gkg
    u = universe(con, stock_list)
    out = {"portfolio": portfolio(con, u, stock_list, now), "filings": filings(con, u, since_filings, root, now),
           "results": results(con, u, now), "deals": deals(con, u, since_filings, root, now),
           "holdings": holdings(con, u, root, now)}
    if guards_list is not None:
        out["guards"] = guards(con, guards_list, datetime(asof.year, asof.month, asof.day, 21), now)
    if gkg_since:
        out["articles"] = articles(con, gdelt_gkg.load(gkg_since, root), now)
    return out


def context(con, symbols: List[str], asof: date, days: int = 30, per: int = 6,
            stock_list: Optional[List[dict]] = None) -> tuple:
    """Facts and quotable sources for the centre: recent filings, results and articles of the named companies.
    Articles count only when their headline names the company (`is_about`); results only once usable on `asof`."""
    from datetime import timedelta
    facts, sources, k = {}, {}, 0
    end = datetime(asof.year, asof.month, asof.day, 23, 59)
    if stock_list is None:
        from pflab.plan import guards as gd
        stock_list = gd.stock_list()
    for sym in symbols:
        row = con.execute("SELECT node_id FROM kg_nodes WHERE kind='company' AND (json_extract_string(attrs_json, '$.symbol') = ? "
                          "OR upper(name) LIKE ?)", [sym, f"%{sym.upper()}%"]).fetchone()
        if not row:
            continue
        names = names_for(con, [row[0].split(":", 1)[1]], stock_list)[row[0].split(":", 1)[1]]
        tl = g.timeline(con, row[0], asof - timedelta(days=days), end, kinds=("filing", "article"), limit=500)
        tl = tl[(tl["kind"] != "article") | tl["title"].map(lambda t: is_about(t, names))].head(per)
        facts["window_days"] = days
        facts[f"{sym}.documents"] = int(len(tl))
        # result figures as facts (the guard checks numbers against facts, not against titles)
        scrip = con.execute("SELECT json_extract_string(attrs_json, '$.symbol') FROM kg_nodes WHERE node_id=?",
                            [row[0]]).fetchone()
        isin = row[0].split(":", 1)[1]
        res = con.execute("""SELECT d.attrs_json, d.title FROM kg_edges e JOIN kg_docs d ON d.doc_id = e.src
                             WHERE e.dst = ? AND d.kind = 'result' AND d.published_at <= ?
                             ORDER BY d.title DESC""", [row[0], end]).fetchall()     # point in time (2026-10-18)
        q_rows, cons = [], {}
        for a, t in res:
            m = re.search(r"quarter ended (\d{4}-\d{2}-\d{2})", t or "")
            if m and a:
                a = json.loads(a)
                if a.get("basis") == "consolidated":       # a separate series: never mixed into the quarters
                    cons[m.group(1)] = a
                else:
                    q_rows.append((m.group(1), a))
        for i, (qe, a) in enumerate(sorted(q_rows, key=lambda x: x[0], reverse=True)[:4], start=1):
            facts[f"{sym}.q{i}.quarter_end"] = date.fromisoformat(qe)
            if a.get("net_profit") is not None:
                facts[f"{sym}.q{i}.net_profit"] = (a["net_profit"], "million")
            if a.get("revenue") is not None:
                facts[f"{sym}.q{i}.revenue"] = (a["revenue"], "million")
            c = cons.get(qe, {})
            if c.get("net_profit") is not None:
                facts[f"{sym}.q{i}.net_profit_consolidated"] = (c["net_profit"], "million")
            if c.get("revenue") is not None:
                facts[f"{sym}.q{i}.revenue_consolidated"] = (c["revenue"], "million")
        tones = tl["tone"].dropna()
        if len(tones):
            facts[f"{sym}.news_tone"] = round(float(tones.mean()), 1)
        cur = g.as_of(con, row[0], "guard_status", datetime(asof.year, asof.month, asof.day, 23, 59))
        if cur:
            facts[f"{sym}.guard"] = cur[0].split(":")[1]
        for r in tl.itertuples():
            k += 1
            sources[f"S{k}"] = f"{pd.Timestamp(r.published_at).date()} {r.kind} ({r.source}): {r.title}"
    return facts, sources
