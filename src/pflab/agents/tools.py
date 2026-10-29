"""The agents' read-only tools (S37). Each returns facts: a flat {name: value} table the centre may quote, and
nothing else. Values are rounded to what a sentence should show (rupees to the rupee, rates as fractions to 3
decimals), because the guard compares numbers at the precision written. No tool writes to the ledger, logs a
proposal or sends anything; no tool can place an order (there is no order path in the system).
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass
from datetime import date
import re
from types import SimpleNamespace
from typing import Callable, Dict, List

from pflab.pm import estimate as est

Facts = Dict[str, object]


@dataclass(frozen=True)
class Tool:
    name: str
    agent: str
    about: str                      # what questions it answers (the router reads this)
    run: Callable[..., Facts]
    uses_question: bool = False     # run(con, asof, question) instead of run(con, asof)


def _num(x):
    return x.value if isinstance(x, est.Estimate) else x


def networth(con, asof: date) -> Facts:
    from pflab.pm import today as nw
    n = nw.build(con, asof)
    fdf = n["fds"]
    fd_inv = float(fdf.loc[~fdf["reserve"], "value"].sum()) if len(fdf) else 0.0
    fd_res = float(fdf.loc[fdf["reserve"], "value"].sum()) if len(fdf) else 0.0
    b = n["buckets"]
    f: Facts = {"asof": asof, "net_worth": round(n["net_worth"]), "investable": round(n["investable"]),
                "stocks_total": round(b.get("equity", 0.0)), "index_funds_total": round(b.get("equity_fund", 0.0)),
                "gold_total": round(b.get("gold", 0.0)), "fd_investable_total": round(fd_inv),
                "fd_phd_reserve_total": round(fd_res), "fd_all_total": round(fd_inv + fd_res),
                "cash_above_floor": round(b.get("cash", 0.0))}
    inv = n["investable"] or 1.0
    for k, bucket in (("stocks", "equity"), ("index_funds", "equity_fund"), ("gold", "gold"), ("debt", "debt"),
                      ("cash", "cash")):
        f[f"{k}_share_of_investable"] = round(b.get(bucket, 0.0) / inv, 3)
    label = {"equity": "stock", "gold": "gold", "equity_fund": "index fund", "debt": "debt"}
    for r in n["positions"].itertuples():
        if r.value is not None and r.value == r.value:
            f[f"holding.{r.symbol}.kind"] = label.get(r.bucket, r.bucket)
            f[f"holding.{r.symbol}.value"] = round(r.value)
            f[f"holding.{r.symbol}.gain"] = round(r.unrealised)
    return f


def guards(con, asof: date) -> Facts:
    from pflab.plan import guards as gd
    g = gd.check_all(con, asof, gd.stock_list())
    dip = gd.market_dip(asof)
    f: Facts = {"market.drawdown": round(dip["drawdown"], 3), "market.asof": dip["date"],
                "dip_rule_active": "yes" if dip["active"] else "no"}
    cl = gd.market_cluster(asof)
    if cl:
        f["market.state"] = cl["state"]
        f["market.chance_2pct_fall_within_10_sessions"] = round(cl["chance"], 2)
        f["market.regular_tranches"] = "unchanged by the market state"
    for x in g:
        f[f"guard.{x.symbol}"] = x.verdict
        if x.reasons:
            f[f"guard.{x.symbol}.why"] = "; ".join(x.reasons)
    return f


def fds(con, asof: date) -> Facts:
    from pflab.pm import fd as fdm
    fl = fdm.load(con)
    f: Facts = {}
    lad = fdm.ladder(fl, asof)
    # batch totals computed here (S43: the model attached one deposit's payout to a whole batch; the guard checks
    # that a number exists, not what it is attached to, so totals must come from code)
    batches: Dict[date, list] = {}
    for r in lad:
        batches.setdefault(r["maturity"], []).append(r)
    for k, (m, rs) in enumerate(sorted(batches.items())[:3], start=1):
        f[f"fd_batch{k}.matures"] = m
        f[f"fd_batch{k}.deposits"] = len(rs)
        f[f"fd_batch{k}.payout_total_est"] = round(sum(r["payout"].value for r in rs))
    for r in lad:
        k = f"fd.{r['fd_id']}"
        f[f"{k}.matures"] = r["maturity"]
        f[f"{k}.payout_est"] = round(r["payout"].value)
        f[f"{k}.instruction"] = r["instruction"]
    fy = asof.year + (1 if asof.month >= 4 else 0)
    t = fdm.year_totals(fl, fy, fdm.interest_facts(con))
    f["fd.interest_this_fy_est"] = round(t["interest"])
    f["fd.tds_this_fy_est"] = round(t["tds"])
    return f


def plan(con, asof: date) -> Facts:
    from pflab.plan import targets as tg
    t = tg.load()
    f: Facts = {"cash_floor": round(t.cash_floor)}
    for b, x in t.buckets.items():
        f[f"target.{b}"] = round(x.target, 3)
    from pflab.plan import monthly
    p, _ = monthly.run(con, asof, 0.0, t, log=False)
    for b, w in p.weights_before.items():
        f[f"weight.{b}"] = round(w, 3)
        f[f"status.{b}"] = p.status_after.get(b, "")
    # S42 round 2: where maturing FD money goes (the deployment schedule; no tool carried it before)
    from pflab.pm import fd as fdm
    from pflab.plan import deploy
    tr = deploy.schedule(fdm.load(con), 10, asof)                     # same default as `pflab pm deploy`
    for k, b in enumerate(sorted({x.batch for x in tr})[:2], start=1):
        xs = [x for x in tr if x.batch == b]
        f[f"deploy.batch{k}.maturity"] = b
        f[f"deploy.batch{k}.months"] = len(xs)
        f[f"deploy.batch{k}.first_month"] = xs[0].month
        f[f"deploy.batch{k}.per_month"] = (round(xs[0].amount), "rupees, estimate")
    return f                                    # each tranche is split by the target.* weights above


def risk(con, asof: date) -> Facts:
    from pflab.data import data_dir
    from pflab.plan import targets as tg
    from pflab.risk import montecarlo as mc
    R, Rd = mc.history(data_dir()), mc.history_daily(data_dir())
    t = tg.load()
    res = mc.simulate(R, {"target": mc.target_mix(t, mc.fund_names(con, t))}, years=5, n=5000, Rd=Rd)["target"]
    f: Facts = {}
    for eng, s in res.items():
        f[f"risk.{eng}.median_return"] = round(s["median_cagr"], 3)
        f[f"risk.{eng}.chance_fall_beyond_35pct_any_day"] = round(s["p_fall_beyond_limit_any_day"], 2)
        f[f"risk.{eng}.chance_fall_beyond_35pct_month_end"] = round(s["p_fall_beyond_limit"], 2)
        f[f"risk.{eng}.bad5_after_5y"] = round(s["y5"]["p5"], 2)
        f[f"risk.{eng}.good5_after_5y"] = round(s["y5"]["p95"], 2)
    from pflab.plan import guards as gd
    cl = gd.market_cluster(asof)                                  # S40: only when the frozen fit exists
    if cl:
        f["risk.cluster.chance_2pct_fall_within_10_sessions"] = round(cl["chance"], 2)
        f["risk.cluster.chance_normal"] = round(cl["normal"], 2)
        f["risk.cluster.market_state"] = cl["state"]
        f["risk.cluster.asof"] = cl["date"]
    return f


def tax(con, asof: date) -> Facts:
    from pflab.tax import report as taxreport
    fy = asof.year + (1 if asof.month >= 4 else 0)
    t = taxreport.build(con, fy)
    f: Facts = {"tax.fy": f"FY{fy - 1}-{str(fy)[2:]}"}
    for reg in ("new", "old"):
        r = t["regimes"][reg]
        f[f"tax.{reg}.total"] = round(r.total_tax)
        f[f"tax.{reg}.balance"] = round(r.balance)
    f["tax.fd_interest"] = round(t["fd"]["interest"]) if t.get("fd") else 0
    f["tax.note"] = "other income such as rent is not included unless entered"
    return f


def taxplan(con, asof: date) -> Facts:
    """S58b: the tax engine's answers to planning questions (pflab.tax.plan), as facts."""
    from pflab.tax import plan as tp
    o = tp.overview(con, asof)
    h = o["harvest"]
    f: Facts = {"taxplan.fy": f"FY{o['fy'] - 1}-{str(o['fy'])[2:]}", "taxplan.exemption_112a": round(h["exemption"]),
                "taxplan.exemption_left": round(h["left"]), "taxplan.tax_free_gain_bookable_now": round(h["gain_booked"])}
    for s in h["sales"]:
        f[f"taxplan.harvest.{s['symbol']}.sell_qty"] = s["qty"]
    for (_acc, _isin, sym), steps in o["ladders"].items():
        last = steps[-1]
        f[f"taxplan.{sym}.extra_tax_if_all_sold_today"] = round(last["extra_tax"])
        f[f"taxplan.{sym}.lots_long_term"] = f"{sum(s['term'] == 'LT' for s in steps)} of {len(steps)}"
        lt = [s["long_term_from"] for s in steps if s["term"] == "ST" and s["long_term_from"]]
        if lt:
            f[f"taxplan.{sym}.all_long_term_from"] = str(max(lt))
    for l in o["losses"]:
        f[f"taxplan.{l['symbol']}.selling_lowers_tax_by"] = round(l["tax_saved"])
    for s in o["turning_long_term"]:
        f[f"taxplan.{s['symbol']}.waiting_until_{s['long_term_from']}_saves"] = round(s["waiting_saves"])
    for d in o["not_in_ledger"]:
        f[f"taxplan.{d['symbol']}.not_in_statements_yet"] = d["kite"] - d["ledger"]
    f["taxplan.note"] = "estimates at today's prices before fees; selling and buying back restarts the holding period"
    return f


def context(con, asof: date, question: str = "") -> Facts:
    """Recent filings, results and news (knowledge graph) for the list companies the question names; the
    documents come back as quotable sources under the key '_sources'."""
    from pflab.kg import build as kb
    from pflab.plan import guards as gd
    stocks = gd.stock_list()
    syms = [s["symbol"] for s in stocks if re.search(r"\b" + re.escape(s["symbol"]) + r"\b", question, re.I)]
    for sym, names in question_aliases(con, stocks).items():
        if sym not in syms and any(re.search(r"\b" + re.escape(n) + r"\b", question, re.I) for n in names):
            syms.append(sym)
    facts, sources = kb.context(con, syms or [], asof)
    # S44: the researcher's flags of the last 30 days, as quotable sources (code wrote them, with their numbers)
    from pflab.agents import researcher as rs
    from pflab.agents.tradecheck import isin_of
    for sym in syms:
        isin = isin_of(con, sym)
        fl = rs.recent_flags(con, isin, asof) if isin else []
        if fl:
            facts[f"{sym}.changes_30d"] = len(fl)
        for t, kind, detail in fl[:6]:
            sources[f"S{len(sources) + 1}"] = f"{pd_date(t)} researcher flag ({kind}): {detail}"
        if isin:                                          # figures from the investor's own files (the inbox), as facts
            from pflab.agents import inbox
            facts.update({f"{sym}.{k}": v for k, v in inbox.facts_for(con, isin, question).items()})
            from pflab.agents import analyst
            note = analyst.latest_note(con, isin, asof)     # the analyst's research, for the local model to cite
            if note:
                sources[f"S{len(sources) + 1}"] = note
    # S49 (adopted 2026-10-18): the best matches for the question itself, by the hybrid look-up, as quotable sources
    from pflab.agents import memory_compare as mc
    for it in mc.lookup(con, question, asof):
        sources[f"S{len(sources) + 1}"] = f"{pd_date(it['at'])} {it['kind']}: {it['text'][:800]}"
    facts["_sources"] = sources
    return facts


def pd_date(t) -> date:
    return t.date() if hasattr(t, "date") else t


def question_aliases(con, stocks: List[dict]) -> Dict[str, List[str]]:
    """symbol -> names a question may use for a list company: the knowledge graph's aliases (legal name and the
    `aliases` in stock_list.toml) plus the name's first word when no other list company shares it (never a
    group name that two listed companies share). No names live in the code."""
    from pflab.kg import build as kb
    u = kb.universe(con, stocks)
    u = u[u["symbol"].isin([s["symbol"] for s in stocks])]
    al = kb.aliases(u)

    def first_word(nm) -> str:
        parts = kb.STRIP.sub("", nm).lower().split() if isinstance(nm, str) else []
        return parts[0].strip(" .,") if parts else ""
    first: Dict[str, List[str]] = {}
    for r in u.itertuples():
        first.setdefault(first_word(getattr(r, "name", None)), []).append(r.symbol)
    out = {}
    for r in u.itertuples():
        names = list(al.get(r.isin, []))
        w = first_word(getattr(r, "name", None))
        if len(w) >= 3 and first.get(w) == [r.symbol] and w not in names:
            names.append(w)
        out[r.symbol] = names
    return out


# S67: the system's own state and the emails' facts, for the ask centre as for the brain. The tools need the runtime (settings, the data
# folder, the clock): the dashboard's `Runtime` or the background `Desk`. `bind(rt)` sets it for the question being answered.
_RT: contextvars.ContextVar = contextvars.ContextVar("pflab_rt", default=None)


def bind(rt):
    """Make `rt` the runtime the system tools read for this thread's question; returns the token for `unbind`."""
    return _RT.set(rt)


def unbind(token) -> None:
    _RT.reset(token)


def _flat(prefix: str, d: dict, out: Facts) -> None:
    for k, v in d.items():
        key = f"{prefix}.{k}"
        if isinstance(v, dict):
            _flat(key, v, out)
        elif isinstance(v, (int, float, bool)) or v is None:
            out[key] = v if v is not None else "none"
        elif isinstance(v, (list, tuple)):
            out[key] = "; ".join(str(x) if not isinstance(x, dict) else ", ".join(f"{a} {b}" for a, b in x.items()) for x in v)[:600] or "none"
        else:
            out[key] = str(v)[:400]


def _ctx(con):
    rt = _RT.get()
    if rt is None:
        return None
    return SimpleNamespace(rt=rt, now=rt.clock(), con=con)


def system(con, asof: date) -> Facts:
    """The same picture as the Command centre and the brain's `system_status`: connectors, data freshness, work, what is current."""
    from pflab.hq import tools as hq
    c = _ctx(con)
    if c is None:
        return {"system.unavailable": "the system's state is not reachable from here"}
    s = hq.system_status(c, {})
    out: Facts = {"system.verdict": s["verdict"], "system.catching_up": s["catching_up"] or "no"}
    for x in s["connectors"]:
        out[f"connector.{x['name']}"] = f"{x['state']}: {x['line']}"
    for x in s["data_freshness"]:
        out[f"data.{x['name']}"] = f"{x['state']}: {x['line']}"
    out["work.failed_last_day"] = s["failed_last_day"]
    out["work.running_now"] = "; ".join(r["job"] for r in s["running_now"]) or "nothing"
    out["work.needs_from_him"] = "; ".join(s["needs_from_him"]) or "nothing"
    out["work.being_researched"] = "; ".join(f"#{c_['id']} {c_['question'][:90]} ({c_['status']})" for c_ in s["being_researched"]) or "nothing"
    out["work.held_tasks"] = len(s["held_tasks"])
    out["recommendations.current"] = s["recommendations"]["current"]
    out["recommendations.note"] = s["recommendations"]["say"] or "nothing prepared earlier is stale"
    return out


def mail(con, asof: date) -> Facts:
    from pflab.hq import tools as hq
    c = _ctx(con)
    if c is None:
        return {"mail.unavailable": "the email facts are not reachable from here"}
    out: Facts = {}
    _flat("mail", {k: v for k, v in hq.mail_facts(c, {}).items() if k != "source"}, out)
    return out


TOOLS: List[Tool] = [
    Tool("networth", "ledger", "net worth, holdings, rupee values of what is owned, gains and losses, cash, buckets",
         networth),
    Tool("guards", "guard", "whether a stock on the list is safe to buy; NSE surveillance (ASM, GSM, ESM); safety "
         "tests; how far the Nifty 500 is below its 1-year high; whether the dip rule is on; market state", guards),
    Tool("fds", "fixed deposits", "fixed deposits: maturity dates, payouts, FD interest and TDS, renewal instructions",
         fds),
    Tool("plan", "allocation", "targets and current weights, what is under or over target, and where money from "
         "maturing FDs goes: the monthly deployment schedule and its split across buckets", plan),
    Tool("risk", "risk", "Monte Carlo risk of the target mix: chance of a big fall, range of outcomes in percent "
         "(combine with networth for rupees); clustering of market falls", risk),
    Tool("tax", "tax", "income tax estimate for this financial year, both regimes", tax),
    Tool("taxplan", "tax planning", "tax if a holding is sold today; when lots turn long-term and what waiting saves; "
         "the long-term gains exemption left this year and gains that fit in it tax-free; losses that lower this "
         "year's tax", taxplan),
    Tool("context", "knowledge", "recent news, filings and results about a named company; why a stock moved", context,
         uses_question=True),
    Tool("system", "system", "whether the system itself is working and in sync: Kite, Gmail, Telegram, the local model, the Claude API, the "
         "sandbox, how fresh each data source is, what is running, what failed, what is being researched, what needs the investor, "
         "whether recommendations are current", system),
    Tool("mail", "mail", "what his money emails said (trades, deposits, dividends, IPO allotments, bank alerts) and whether his record "
         "or Kite has each one", mail),
]
BY_NAME = {t.name: t for t in TOOLS}
