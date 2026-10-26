"""The researcher (PLAN A7, S44): every night, for each list and held company, find what changed and keep its
brief current. Code finds and measures the changes; a model only writes the brief, through the S21 guard.

Flags (one row each in `research_flags`, never twice; dated by when the market could see them):
    material_filing   a filing whose BSE subcategory is in the registered material map (the S42 labels)
    red_flag:<NAME>   a filing the frozen S20 red-flag rules flag (insolvency, default, auditor, ...)
    results           a new quarterly result (published within FRESH_RESULT_DAYS of its quarter end), with revenue
                      and net profit against the same quarter a year earlier
    guard_change      the safety verdict changed (ok / fail / data gap)
    news_spike        at least NEWS_MIN articles in the last 7 days and NEWS_X times the prior 12-week weekly
                      average, once 13 weeks of news exist: an attention flag, not a signal (no claim that it
                      predicts anything)
    results_range     S52 Q6: the range for the next quarter's revenue and net margin, before the result (ESTIMATE)
    results_surprise  S52 Q6: the result against that range, dated by the result's dissemination
A company with new flags, or whose brief is older than BRIEF_DAYS, gets a new brief (`briefs`). One digest a night
goes to the outbox. Nothing here recommends a trade.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from pflab.data import red_flags
from pflab.llm.eval12 import MATERIAL, ROUTINE

NEWS_MIN, NEWS_X = 5, 3.0
BRIEF_DAYS = 30
FRESH_RESULT_DAYS = 150       # a quarter's results are news only if published within this many days of its end


@dataclass
class Flag:
    isin: str
    symbol: Optional[str]
    kind: str
    happened_at: datetime
    ref: str
    detail: str


@dataclass
class RunReport:
    asof: date
    companies: int = 0
    new_flags: List[Flag] = field(default_factory=list)
    briefs: Dict[str, bool] = field(default_factory=dict)       # symbol -> verified

    def digest(self) -> str:
        if not self.new_flags:
            return f"Research {self.asof}: no material change in {self.companies} companies."
        lines = [f"Research {self.asof}: {len(self.new_flags)} change(s) in {self.companies} companies"]
        for f in sorted(self.new_flags, key=lambda x: (x.symbol or x.isin, x.happened_at)):
            line = f"- {f.symbol or f.isin} {f.happened_at:%d-%b}: {f.detail}"
            if line not in lines:                          # the same notice filed twice on a day: shown once
                lines.append(line)
        if self.briefs:
            lines.append("Briefs updated: " + ", ".join(f"{s}{'' if v else ' (facts only)'}" for s, v in self.briefs.items())
                         + ". Ask about any of them.")
        return "\n".join(lines)


def _docs(con, isin: str, kind: str, start: datetime, end: datetime) -> pd.DataFrame:
    return con.execute("""SELECT d.doc_id, d.published_at, d.title, d.attrs_json FROM kg_edges e
                          JOIN kg_docs d ON d.doc_id = e.src
                          WHERE e.dst = ? AND d.kind = ? AND d.published_at > ? AND d.published_at <= ?
                            AND d.dup_of IS NULL
                          ORDER BY d.published_at""", [f"company:{isin}", kind, start, end]).df()


def filing_flags(con, isin: str, symbol: Optional[str], start: datetime, end: datetime,
                 tagger: Optional[Callable[[str], Optional[str]]] = None) -> List[Flag]:
    """`tagger`: the adopted S47 materiality prompt (`tuning.materiality_tagger`), asked only about a filing whose
    subcategory is in neither registered map and whose headline says something (40+ characters, as in its test)."""
    out = []
    for r in _docs(con, isin, "filing", start, end).itertuples():
        a = json.loads(r.attrs_json or "{}")
        cat, sub = a.get("category") or "", a.get("subcategory") or ""
        title = r.title or ""
        for fl in red_flags.classify(title, cat, sub):
            out.append(Flag(isin, symbol, f"red_flag:{fl}", r.published_at, r.doc_id, f"{fl.lower()}: {title}"[:300]))
        if sub in MATERIAL:
            out.append(Flag(isin, symbol, "material_filing", r.published_at, r.doc_id, f"{sub}: {title}"[:300]))
        elif tagger and sub not in ROUTINE and len(title) >= 40 and tagger(title) == "material":
            out.append(Flag(isin, symbol, "material_filing", r.published_at, r.doc_id,
                            f"{sub or 'no subcategory'} (model-tagged): {title}"[:300]))
    return out


def _pct(a, b) -> Optional[float]:
    return None if a is None or b is None or b == 0 or pd.isna(a) or pd.isna(b) else (a - b) / abs(b)


def _change(label: str, now_v, old_v) -> str:
    """'net profit 80.0 mn (-20% on a year earlier)'; when either side is negative or zero a percentage misleads,
    so the year-earlier figure is given instead."""
    s = f"{label} {now_v:,.1f} mn"
    if old_v is None or pd.isna(old_v):
        return s
    if now_v <= 0 or old_v <= 0:
        return s + f" (a year earlier {old_v:,.1f} mn)"
    return s + f" ({_pct(now_v, old_v):+.0%} on a year earlier)"


def result_flags(con, isin: str, symbol: Optional[str], scrip: Optional[str], start: datetime, end: datetime) -> List[Flag]:
    """A new quarterly result dated by its announcement, against the same quarter a year earlier. Results dated by
    first sight (S24: no matching announcement) are never news by that date: a new quarter shows up as its
    Financial Results filing, which carries the dissemination time."""
    if not scrip:
        return []
    df = con.execute("SELECT quarter_end, usable_from, date_source, revenue, net_profit FROM quarterly_results "
                     "WHERE scrip_code = ? AND basis = 'standalone'", [str(scrip)]).df()   # one flag per quarter
    if df.empty:
        return []
    by_q = {pd.Timestamp(r.quarter_end).date(): r for r in df.itertuples()}
    out = []
    for r in df.itertuples():
        q, pub = pd.Timestamp(r.quarter_end).date(), pd.Timestamp(r.usable_from)
        if r.date_source == "first_seen" or not (start < pub <= end) or (pub.date() - q).days > FRESH_RESULT_DAYS:
            continue
        prev = by_q.get(q.replace(year=q.year - 1))
        bits = [_change(lbl, getattr(r, k), getattr(prev, k) if prev is not None else None)
                for k, lbl in (("revenue", "revenue"), ("net_profit", "net profit")) if getattr(r, k) is not None]
        out.append(Flag(isin, symbol, "results", pub.to_pydatetime(), f"{scrip}|{q}",
                        f"results for the quarter ended {q:%d-%b-%Y}: " + ("; ".join(bits) or "figures not parsed")))
    return out


def forecast_flags(con, isin: str, symbol: Optional[str], scrip: Optional[str], start: datetime, end: datetime) -> List[Flag]:
    """S52 Q6 (quant/forecast.py): what the baseline expects for a quarter when it is made; the result against it once
    scored. One flag per quarter and kind."""
    if not scrip:
        return []
    from pflab.quant import forecast as fl
    out = []
    rows = con.execute("SELECT target, min(created_at), max(scored_at), count(scored_at) FROM forecasts "
                       "WHERE subject=? AND use IN ('revenue', 'margin') GROUP BY target", [str(scrip)]).fetchall()
    for target, made, scored, n_scored in rows:
        tq = str(target)
        mine = fl.results_lines(con, scrip, symbol, target)
        if not mine:
            continue
        if n_scored == 0 and start < made <= end:
            out.append(Flag(isin, symbol, "results_range", made, f"{scrip}|{tq}|range", "; ".join(mine)))
        elif n_scored and scored is not None and start < scored <= end:
            pub = con.execute("SELECT usable_from FROM quarterly_results WHERE scrip_code=? AND quarter_end=? AND "
                              "basis='standalone'", [str(scrip), target]).fetchone()
            when = datetime.combine(pd.Timestamp(pub[0]).date(), datetime.min.time()) if pub else scored
            out.append(Flag(isin, symbol, "results_surprise", when, f"{scrip}|{tq}|surprise", "; ".join(mine)))
    return out


def guard_flags(con, isin: str, symbol: Optional[str], start: datetime, end: datetime) -> List[Flag]:
    from pflab.kg import graph as g
    before, now = g.as_of(con, f"company:{isin}", "guard_status", start), g.as_of(con, f"company:{isin}", "guard_status", end)
    b, n = (before[0].split(":")[1] if before else None), (now[0].split(":")[1] if now else None)
    if n is None or b == n or b is None:
        return []
    return [Flag(isin, symbol, "guard_change", end, f"{b}->{n}@{end:%Y-%m-%d}", f"safety verdict {b} -> {n}")]


def news_flags(con, isin: str, symbol: Optional[str], end: datetime) -> List[Flag]:
    first = con.execute("SELECT min(published_at) FROM kg_docs WHERE kind='article'").fetchone()[0]
    if first is None or first > end - timedelta(days=91):
        return []             # news collection younger than the 13 weeks a baseline needs: no spike can be judged
    week = _docs(con, isin, "article", end - timedelta(days=7), end)
    base = _docs(con, isin, "article", end - timedelta(days=91), end - timedelta(days=7))
    avg = len(base) / 12.0
    if len(week) < NEWS_MIN or len(week) < NEWS_X * max(avg, 1e-9):
        return []
    return [Flag(isin, symbol, "news_spike", end, f"week-{end:%Y-%m-%d}",
                 f"{len(week)} news articles in 7 days against a weekly average of {avg:.1f} over the 12 weeks before")]


FALL_WINDOWS = (5, 20)            # sessions: a week, a month


def market_returns(root) -> pd.Series:
    """The Nifty 500 total-return index's daily returns (the market for the falls classifier)."""
    from pflab.risk import montecarlo as mc
    m = mc._index(Path(root), "NIFTY500_TRI")
    return m.pct_change().dropna()


def fall_flags(con, root, isin: str, symbol: Optional[str], asof: date, market=None) -> List[Flag]:
    """S56: the stock is getting worse on its own. The S20 classifier (`monitor.falls`, fixed thresholds: a fall of 5%
    or more whose market-model residual is 3 standard deviations below its usual noise) over the last 5 and 20
    sessions; a company-specific or mixed fall is a flag with its numbers. A description of what happened, not a
    reason to sell; it sends the name to the researcher and the analyst."""
    from pflab.app import research as rsx
    from pflab.monitor import falls
    px = rsx.closes(con, Path(root), isin, asof, years=2)
    if len(px) < 80:
        return []
    m = market if market is not None else market_returns(root)
    m = m[m.index <= pd.Timestamp(asof)]                           # point in time (S62 review): never after asof
    r = px.pct_change().dropna()
    r = r[r.index <= m.index[-1]]                                  # windows end on the last date both have
    out = []
    for k in FALL_WINDOWS:
        if len(r) < k:
            continue
        start = r.index[-k].date()
        res = falls.classify(isin, r, m, start, k)
        if res is None or res.label not in ("company-specific", "mixed"):
            continue
        end = r.index[-1]
        out.append(Flag(isin, symbol, "fall", end.to_pydatetime(), f"fall{k}@{end:%Y-%m-%d}",
                        f"{res.label} fall: {res.ret:+.1%} over {k} sessions to {end:%d %b}, market {res.market_ret:+.1%}, "
                        f"{res.z:.1f} standard deviations below what the market explains (beta {res.beta:.2f}, "
                        f"{res.n_fit} sessions fitted)"))
        break                                                      # the shorter window speaks first
    return out


def _save(con, f: Flag, now: datetime) -> bool:
    if con.execute("SELECT 1 FROM research_flags WHERE isin=? AND kind=? AND ref=?", [f.isin, f.kind, f.ref]).fetchone():
        return False
    from pflab.pm.store import next_id
    fid = next_id(con, "research_flags", "flag_id")
    con.execute("INSERT INTO research_flags VALUES (?,?,?,?,?,?,?,?)",
                [fid, f.isin, f.symbol, f.kind, f.happened_at, now, f.ref, f.detail])
    return True


def last_brief(con, isin: str) -> Optional[tuple]:
    return con.execute("SELECT as_of, verified, text FROM briefs WHERE isin=? ORDER BY built_at DESC, brief_id DESC LIMIT 1",
                       [isin]).fetchone()


def run(con, asof: date, stock_list: List[dict], since: Optional[date] = None, llm: Optional[Callable[[str], str]] = None,
        guards: Optional[Dict[str, dict]] = None, now: Optional[datetime] = None, write_briefs: bool = True,
        rebrief: bool = False, tagger: Optional[Callable[[str], Optional[str]]] = None, root=None) -> RunReport:
    """Flags since `since` (default: 7 days back) up to the end of `asof`; briefs for flagged or stale companies.
    `guards`: symbol -> {"verdict", "reasons"} for the briefs (optional); `tagger`: see `filing_flags`; `root`: the data
    folder, for the fall flags (S56)."""
    from pflab.agents import brief as br
    from pflab.kg import build as kb
    now = now or datetime.now()
    start = datetime.combine(since or asof - timedelta(days=7), datetime.min.time())
    end = datetime.combine(asof, datetime.max.time()).replace(microsecond=0)
    u = kb.universe(con, stock_list)
    u = u[u["isin"].astype(str).str.startswith("INE")]           # companies; funds, SGBs and ETFs have no filings
    rep = RunReport(asof, companies=int(len(u)))
    market = None
    if root is not None:
        try:
            market = market_returns(root)
        except Exception:                                          # no index file: no fall flags, the rest runs
            market = None
    for r in u.itertuples():
        sym = r.symbol if isinstance(r.symbol, str) else None
        scrip = r.scrip if isinstance(r.scrip, str) and r.scrip else None
        flags = (filing_flags(con, r.isin, sym, start, end, tagger) + result_flags(con, r.isin, sym, scrip, start, end)
                 + guard_flags(con, r.isin, sym, start, end) + news_flags(con, r.isin, sym, end)
                 + forecast_flags(con, r.isin, sym, scrip, start, end)
                 + (fall_flags(con, root, r.isin, sym, asof, market) if market is not None else []))
        new = [f for f in flags if _save(con, f, now)]
        rep.new_flags += new
        lb = last_brief(con, r.isin)
        stale = rebrief or lb is None or (asof - lb[0]).days >= BRIEF_DAYS
        if write_briefs and sym and (new or stale):
            b = br.build(con, sym, asof, (guards or {}).get(sym), llm)
            from pflab.pm.store import next_id
            bid = next_id(con, "briefs", "brief_id")
            con.execute("INSERT INTO briefs VALUES (?,?,?,?,?,?,?,?)",
                        [bid, r.isin, sym, asof, now, ",".join(sorted({f.kind for f in new})) or "refresh", b.verified, b.text])
            rep.briefs[sym] = b.verified
    return rep


DEEP_QUESTION = ("For {name}: what changed over the last 90 days in its exchange filings, filed results and news; what "
                 "drives the business now; which risks are visible; and what do the documents leave unclear? Use only "
                 "the documents, cite them, and give figures only where a document states them.")
DEEP_MAX = 15                     # notes queued in one night (the monthly cap still applies to each)
CHANGE_KINDS = ("results", "results_surprise", "material_filing", "guard_change", "fall")   # and every red_flag:*


def deep_queue(con, asof: date, stock_list: List[dict], everyone: bool = False, max_n: int = DEEP_MAX,
               client=None, now: Optional[datetime] = None) -> Dict[str, str]:
    """Queue in-depth analyst notes for the overnight batch (half price): companies with a flag in the last 2 days,
    or every list company when `everyone` (the weekly sweep). A note on the same company from the last 14 days is
    reused, never bought again, unless a material change (CHANGE_KINDS, a red flag) was flagged after the company's last
    note was asked for (S58 drill 1: results filed after a reused note never reached Opus). Returns symbol -> outcome."""
    from pflab.agents import analyst as an
    from pflab.agents.tradecheck import isin_of
    now = now or datetime.now()
    flagged = {r[0] for r in con.execute("SELECT DISTINCT symbol FROM research_flags WHERE detected_at >= ?",
                                         [now - timedelta(days=2)]).fetchall()}
    out: Dict[str, str] = {}
    client = client or an.make_client(_secrets())
    for s in stock_list:
        sym = s["symbol"]
        if not (everyone or sym in flagged) or len([v for v in out.values() if v == "queued"]) >= max_n:
            continue
        if con.execute("SELECT 1 FROM api_calls WHERE topic=? AND status IN ('queued', 'submitted') LIMIT 1",
                       [sym]).fetchone():                # S58: research may run any time; a note in flight is not bought twice
            out[sym] = "in flight"
            continue
        isin = s.get("isin") or isin_of(con, sym)
        row = con.execute("SELECT name FROM instruments WHERE isin=? LIMIT 1", [isin]).fetchone()
        # a row may carry no name (2026-10-17: a question read "For None"): the list's alias, else the symbol
        name = (row[0] if row and row[0] else None) or ((s.get("aliases") or [""])[0].title() or sym)
        req = an.Request(DEEP_QUESTION.format(name=name), sym, an.public_docs(con, [isin], asof), [isin], urgent=False)
        try:
            last = con.execute("SELECT max(created_at) FROM api_calls WHERE topic=? AND status IN ('done', 'queued', 'submitted')",
                               [sym]).fetchone()[0]
            changed = con.execute(
                f"SELECT 1 FROM research_flags WHERE symbol=? AND detected_at > ? AND (kind IN ({','.join('?' * len(CHANGE_KINDS))}) "
                "OR kind LIKE 'red_flag:%') LIMIT 1", [sym, last or datetime(2000, 1, 1), *CHANGE_KINDS]).fetchone()
            # S59 (PLAN A16): company notes are a worker's job: Sonnet 5.5, in the batch; Opus stays for deep research
            o = an.ring(con, req, client, now=now, reuse=changed is None, cfg={**an.config(), "model": an.slider("notes", an.SONNET)})
            if o.call_id is not None and o.status == "queued":
                con.execute("UPDATE api_calls SET agent='worker' WHERE call_id=?", [o.call_id])
            out[sym] = o.status
        except (an.NotAdopted, an.BudgetRefused, an.NeedsApproval) as e:
            out[sym] = f"not sent: {e}"
    return out


def _secrets():
    from pflab.pm import secrets as sec
    try:
        return sec.load()
    except sec.SecretsError:
        return None


def show(con, symbol: str, asof: date, days: int = 30) -> str:
    """A company's flags of the last `days` and its latest brief (what /research and `pflab research show` print)."""
    from pflab.agents.tradecheck import isin_of
    isin = isin_of(con, symbol)
    if not isin:
        return f"{symbol.upper()}: not in the instrument master"
    lines = [f"{symbol.upper()} ({isin}): changes in the last {days} days"]
    fl = recent_flags(con, isin, asof, days)
    lines += [f"  {t:%d-%b-%Y} {k}: {d}" for t, k, d in fl] or ["  none flagged"]
    lb = last_brief(con, isin)
    lines.append(f"Brief of {lb[0]} ({'checked' if lb[1] else 'facts only'}):\n{lb[2]}" if lb else
                 "No brief yet (pflab research run).")
    return "\n".join(lines)


def digest_since(con, since: datetime) -> str:
    """Every flag detected since `since`, by company (the morning report's research section)."""
    rows = con.execute("SELECT symbol, happened_at, kind, detail FROM research_flags WHERE detected_at >= ? "
                       "ORDER BY symbol, happened_at", [since]).fetchall()
    if not rows:
        return "No new changes found."
    lines, seen = [], set()
    for sym, t, kind, detail in rows:
        line = f"- {sym} {t:%d-%b}: {detail}"
        if line not in seen:
            seen.add(line)
            lines.append(line)
    briefs = con.execute("SELECT symbol, verified FROM briefs WHERE built_at >= ? "
                         "QUALIFY row_number() OVER (PARTITION BY symbol ORDER BY built_at DESC, brief_id DESC) = 1 "
                         "ORDER BY symbol", [since]).fetchall()           # the newest brief per company
    if briefs:
        lines.append("Briefs rewritten: " + ", ".join(f"{s}{'' if v else ' (facts only)'}" for s, v in briefs)
                     + " (pflab research show SYMBOL)")
    return "\n".join(lines)


def recent_flags(con, isin: str, asof: date, days: int = 30) -> List[tuple]:
    return con.execute("SELECT happened_at, kind, detail FROM research_flags WHERE isin=? AND happened_at > ? "
                       "AND happened_at <= ? ORDER BY happened_at DESC",
                       [isin, datetime.combine(asof - timedelta(days=days), datetime.min.time()),
                        datetime.combine(asof, datetime.max.time())]).fetchall()
