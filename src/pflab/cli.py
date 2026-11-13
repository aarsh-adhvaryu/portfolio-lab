"""pflab command line."""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta


def _d(s: str) -> date:
    return date.fromisoformat(s)


def main(argv=None):
    p = argparse.ArgumentParser(prog="pflab")
    p.add_argument("--paid", action="store_true", help="workshop only: allow paid API calls (against dev_monthly_cap_rupees); put it before the command")
    p.add_argument("--live", action="store_true", help="workshop only: allow sending Telegram messages; put it before the command")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="run a data collector")
    c.add_argument("source", choices=["bhavcopy", "bse", "gdelt"])
    c.add_argument("--from", dest="start", type=_d, default=date.today() - timedelta(days=3))
    c.add_argument("--to", dest="end", type=_d, default=date.today())

    ak = sub.add_parser("ask", help="ask the agents a question; answered only from their facts")
    ak.add_argument("question")
    ak.add_argument("--asof", type=_d, default=date.today())
    ak.add_argument("--tools", help="comma list to skip routing (networth,guards,fds,plan,risk,tax)")
    ak.add_argument("--show-facts", action="store_true")
    lp = sub.add_parser("list", help="your stock list: add a name (all agents pick it up), remove, show")
    lps = lp.add_subparsers(dest="list_cmd", required=True)
    la = lps.add_parser("add")
    la.add_argument("symbol")
    la.add_argument("--no-brief", action="store_true", help="skip the research brief")
    lr = lps.add_parser("remove")
    lr.add_argument("symbol")
    lps.add_parser("show")
    kgp = sub.add_parser("kg", help="knowledge graph: build from sources, show a company's timeline, fetch text")
    kgs = kgp.add_subparsers(dest="kg_cmd", required=True)
    kb_ = kgs.add_parser("build", help="portfolio, filings, results, guards, GKG articles (idempotent)")
    kb_.add_argument("--filings-since", type=_d, default=date(2025, 1, 1))
    kb_.add_argument("--gkg-since", type=_d, help="add GKG articles collected since this date")
    ks_ = kgs.add_parser("show", help="a company's documents and current links")
    ks_.add_argument("symbol")
    ks_.add_argument("--days", type=int, default=30)
    kt_ = kgs.add_parser("text", help="fetch article text where robots.txt allows")
    kt_.add_argument("--limit", type=int, default=50)
    kv_ = kgs.add_parser("viz", help="interactive 3D graph page (PFLAB_PM_DIR/reports/kg.html)")
    kv_.add_argument("--days", type=int, default=30)
    kv_.add_argument("--entities", action="store_true", help="include themes, organisations and people")
    ko_ = kgs.add_parser("obsidian", help="write an Obsidian vault (PFLAB_PM_DIR/obsidian)")
    ko_.add_argument("--days", type=int, default=30)
    pm = sub.add_parser("pm", help="Portfolio Manager store")
    pmsub = pm.add_subparsers(dest="pm_cmd", required=True)
    pmsub.add_parser("init", help="create or migrate the ledger database")
    qp = pmsub.add_parser("quicko", help="S65: the Quicko pack for a financial year (112A CSV, gains by schedule, income, US rows); reconcile an export")
    qp.add_argument("--fy", type=int, required=True, help="the year the FY ends, e.g. 2026 for April 2025 to March 2026")
    qp.add_argument("--out", help="folder for the files (default PFLAB_PM_DIR/reports/quicko)")
    qp.add_argument("--check", help="a Console or Quicko tax P&L export (.xlsx/.csv) to reconcile against the ledger")
    rs = pmsub.add_parser("reset", help="S65: move the whole PM folder aside (his record is moved, never deleted); lists it without --confirm")
    rs.add_argument("--confirm", default="", help="the word erase-my-record, to move it")
    fr = pmsub.add_parser("fresh", help="S67: archive this profile (verified, opaque bytes) and begin a new empty one that waits for the desktop icon; lists without --confirm")
    fr.add_argument("--archive-to", required=True, help="a folder OUTSIDE the profile and the data folders, for the recovery archive")
    fr.add_argument("--statements", help="a folder of downloaded statements to archive as well")
    fr.add_argument("--confirm", default="", help="the word start-fresh")
    rr = pmsub.add_parser("restore", help="S67: copy an archived profile into an EMPTY separate folder (never the active profile)")
    rr.add_argument("archive")
    rr.add_argument("into")
    i = pmsub.add_parser("instruments", help="instrument master summary")
    i.add_argument("--build", action="store_true",
                   help="fetch AMFI NAVAll and rebuild the master from panel + AMFI")
    i.add_argument("--rows", type=int, default=0, help="also print N rows")
    i.add_argument("--asset-class")

    pr = pmsub.add_parser("prices", help="load prices, NAVs and gold rates; coverage")
    pr.add_argument("--refresh", action="store_true", help="load bhavcopy on disk, AMFI NAVAll, IBJA")
    pr.add_argument("--days", type=int, default=30)
    pr.add_argument("--no-network", action="store_true")

    rk = pmsub.add_parser("risk", help="exposures, concentration, volatility, drawdown, beta")
    rk.add_argument("--asof", type=_d, default=date.today())

    dp = pmsub.add_parser("deploy", help="spread FD maturities over monthly tranches; project the steering")
    dp.add_argument("--months", type=int, default=10)
    dp.add_argument("--batch", type=_d, help="only the FDs maturing on this date")
    dp.add_argument("--asof", type=_d, default=date.today())

    gp = pmsub.add_parser("guards", help="surveillance + safety checks on your stock list; queue alerts")
    gp.add_argument("--asof", type=_d, default=date.today())
    gp.add_argument("--no-alerts", action="store_true")
    ap_ = pmsub.add_parser("alerts", help="alerts waiting in the outbox (until Telegram is set up)")
    ap_.add_argument("--all", action="store_true", help="include sent ones")
    ap_.add_argument("--drop-before", type=_d, help="mark held messages queued before this date as dropped (never sent)")

    imp = pmsub.add_parser("impact", help="what an order of a rupee size paid over the mid, from recorded Kite depth")
    imp.add_argument("symbol")
    imp.add_argument("--amount", type=float, required=True, help="order size in rupees")
    imp.add_argument("--side", choices=["buy", "sell"], default="buy")


    sp = pmsub.add_parser("simulate", help="Monte Carlo (block bootstrap + GBM) and the efficient frontier page")
    sp.add_argument("--years", type=int, default=5)
    sp.add_argument("--paths", type=int, default=10_000)

    nwp = pmsub.add_parser("networth", help="net worth by bucket: holdings, cash, FDs (reserve shown apart)")
    nwp.add_argument("--asof", type=_d, default=date.today())
    trp = pmsub.add_parser("trace", help="every balance with the file and date it comes from, fact or estimate, and the open differences")
    trp.add_argument("--asof", type=_d, default=date.today())

    fdp = pmsub.add_parser("fd", help="fixed deposits: load the deposit file or a certificate, show the ladder")
    fdp.add_argument("action", choices=["load", "cert", "show"])
    fdp.add_argument("--file", help="load: PFLAB_PM_DIR/fd_holdings.toml by default; cert: the certificate PDF")
    fdp.add_argument("--password-env", default="PFLAB_PDF_PASSWORD",
                     help="cert: environment variable holding the PDF password (never a command-line value)")
    fdp.add_argument("--asof", type=_d, default=date.today())
    fdp.add_argument("--fy", type=int, help="show: FY label for interest (default: the FY of --asof)")

    tp = pmsub.add_parser("taxplan", help="tax if sold today by lot, long-term dates, the exemption left, losses (S58b)")
    tp.add_argument("--asof", type=_d, default=date.today())
    tx = pmsub.add_parser("tax", help="income tax for a financial year under both regimes")
    tx.add_argument("--fy", type=int, required=True, help="FY label = year the FY ends (2027 = FY2026-27)")
    tx.add_argument("--other-income", type=float, default=0.0)
    tx.add_argument("--deductions", type=float, default=0.0, help="old-regime deductions (80C etc.)")
    tx.add_argument("--advance-tax", type=float, default=0.0, help="advance tax already paid")
    tx.add_argument("--age", default="under60", choices=["under60", "60-79", "80+"])

    lk = pmsub.add_parser("lookthrough", help="load an AMC monthly portfolio .xlsx for a fund")
    lk.add_argument("--fund", required=True, help="the fund's ISIN")
    lk.add_argument("--file", required=True)
    lk.add_argument("--sheet", help="sheet name (needed when the workbook holds several schemes)")
    lk.add_argument("--as-of", type=_d, help="portfolio date if the file does not state it")

    rs = pmsub.add_parser("results", help="BSE quarterly results for a company (point-in-time) and ratios")
    rs.add_argument("--scrip", required=True, help="BSE scrip code")
    rs.add_argument("--pull", action="store_true", help="fetch the latest quarters from BSE first")
    rs.add_argument("--quarters", type=int, default=8)
    rs.add_argument("--asof", type=_d, default=date.today())

    pp = pmsub.add_parser("propose", help="monthly proposal: steer new money, flag drift, sale options")
    pp.add_argument("--amount", type=float, default=50_000.0, help="this month's contribution")
    pp.add_argument("--asof", type=_d, default=date.today())
    pp.add_argument("--no-log", action="store_true")
    pp.add_argument("--targets", help="targets.toml path (default configs/targets.toml)")
    adp = pmsub.add_parser("advise", help="this month in full: bucket plan, per-stock quantities and order tickets (S45)")
    adp.add_argument("--amount", type=float, help="rupees to invest (default: the next FD deployment tranche)")
    adp.add_argument("--asof", type=_d, default=date.today())

    sv = sub.add_parser("service", help="always-on jobs: tick, run, status (PLAN S9)")
    svsub = sv.add_subparsers(dest="sv_cmd", required=True)
    svsub.add_parser("tick", help="run every job that is due (what Task Scheduler calls)")
    sr = svsub.add_parser("run", help="run one job now")
    sr.add_argument("job")
    svsub.add_parser("plan", help="what a tick would do now, per job")
    svsub.add_parser("status", help="health: jobs, data freshness, outbox, backup, disk")
    svsub.add_parser("test-alert", help="queue and send a Telegram test message")
    svsub.add_parser("backup", help="back up the ledger now (needs a target)")
    ipop = sub.add_parser("ipo", help="S64: an IPO allotment and the money around it")
    ipop.add_argument("action", choices=["plan"])
    ipop.add_argument("--name", required=True)
    ipop.add_argument("--qty", type=int, required=True, help="shares allotted")
    ipop.add_argument("--price", type=float, required=True, help="issue price")
    ipop.add_argument("--budget", type=float, required=True, help="rupees to invest in all, allotment included")
    ipop.add_argument("--group", default=None, help="his business group name (PFLAB_PM_DIR/groups.toml)")
    usp = sub.add_parser("us", help="S64 Phase 6: the US sleeve's trades, remittances, gains and rates")
    usp.add_argument("action", choices=["trade", "remit", "show", "gains", "fx"])
    usp.add_argument("--date"); usp.add_argument("--symbol"); usp.add_argument("--side", choices=["buy", "sell"])
    usp.add_argument("--qty", type=float); usp.add_argument("--price", type=float, help="USD per share")
    usp.add_argument("--charges", type=float, help="USD fees on the trade")
    usp.add_argument("--cik", type=int, help="SEC CIK (makes the pseudo-ISIN ZZ+CIK)"); usp.add_argument("--isin")
    usp.add_argument("--etf", action="store_true")
    usp.add_argument("--usd", type=float); usp.add_argument("--inr", type=float); usp.add_argument("--tcs", type=float)
    usp.add_argument("--bank"); usp.add_argument("--fy", type=int, help="financial year's starting year"); usp.add_argument("--slab", type=float)
    wkp = sub.add_parser("workshop", help="calculation workshop (S53): a model writes the maths as code, it runs here")
    wkp.add_argument("action", choices=["ask", "list", "show", "promote", "rerun"])
    wkp.add_argument("text", nargs="?", default="", help="ask: the question; show/promote/rerun: the calculation id")
    wkp.add_argument("--writer", choices=["auto", "local", "opus"], default="auto")
    wkp.add_argument("--approve", action="store_true", help="go ahead with an Opus job above your per-job limit")
    wkp.add_argument("--asof", type=_d, default=date.today())
    cdp = sub.add_parser("conductor", help="the conductor (S53): what is in step, what it needs from you, the fact sheet")
    cdp.add_argument("action", nargs="?", default="status", choices=["status", "run", "sheet"],
                     help="status: check now, change nothing; run: one pass (asks, notes, sheet); sheet: the last sheet")

    lm = sub.add_parser("llm", help="local models: list, smoke test (PLAN S21)")
    lmsub = lm.add_subparsers(dest="llm_cmd", required=True)
    lmsub.add_parser("models", help="models installed in Ollama and the registered picks")
    sm = lmsub.add_parser("smoke", help="one fixed prompt; logs the run")
    sm.add_argument("--model", required=True)
    ev = lmsub.add_parser("evaluate", help="the pre-registered 40-task drafting evaluation (docs/STUDIES.md); LONG")
    ev.add_argument("--role", required=True, choices=["classify", "research"])
    ev.add_argument("--model", required=True)
    ev.add_argument("--tasks", type=int, default=40)
    e12 = lmsub.add_parser("eval12", help="the pre-registered 12 GB GPU evaluation of one model (docs/STUDIES.md); LONG")
    e12.add_argument("--model", required=True)
    e12.add_argument("--only", nargs="*", choices=["routing", "answers", "extraction", "materiality"])
    e12.add_argument("--round", type=int, choices=[1, 2, 3], default=1,
                     help="2 = the round-2 registration (new sets); 3 = answers with the production guard")
    tu = lmsub.add_parser("tune", help="S47 prompt tuning by measurement (docs/STUDIES.md); LONG")
    tu.add_argument("task", choices=["materiality", "routing", "writing", "research", "report"])
    d12 = lmsub.add_parser("decide12", help="apply the registered decision rule to the eval12 results on disk")
    d12.add_argument("--record", action="store_true", help="write the decision into configs/llm_models.toml")
    d12.add_argument("--round", type=int, choices=[1, 2], default=1)
    bp = sub.add_parser("bot", help="two-way Telegram: answer the investor's messages (read-only; Ctrl+C stops)")
    bp.add_argument("action", nargs="?", default="run", choices=["run"])
    bp.add_argument("--once", action="store_true", help="one poll, answer what is waiting, exit")
    trp = sub.add_parser("trades", help="trade check: Kite trades and holdings against the ledger")
    trp.add_argument("action", choices=["check", "pending"])
    trp.add_argument("--asof", type=_d, default=date.today())
    mp = sub.add_parser("memory", help="decisions, reasons, outcomes and feedback kept for the agents")
    mp.add_argument("action", choices=["show", "add", "compare", "index", "find"])
    mp.add_argument("text", nargs="?", default="", help="add: the text; show: words to search")
    mp.add_argument("--kind", default="note", choices=["decision", "reason", "outcome", "feedback", "answer", "note"])
    mp.add_argument("--subject")
    mp.add_argument("--supersedes", type=int)
    qp = sub.add_parser("questions", help="what the agents need from you; answer one")
    qp.add_argument("--answer", nargs=2, metavar=("N", "TEXT"))
    rp = sub.add_parser("research", help="researcher: material changes and briefs for list and held companies")
    rp.add_argument("action", choices=["run", "show", "deep", "digest"])
    rp.add_argument("--hours", type=float, default=24, help="digest: changes detected in the last N hours")
    rp.add_argument("--all", action="store_true", help="deep: every list company (the weekly sweep), not only flagged")
    rp.add_argument("symbol", nargs="?")
    rp.add_argument("--asof", type=_d, default=date.today())
    rp.add_argument("--since", type=_d, help="run: flags since this date (default 7 days back)")
    rp.add_argument("--no-briefs", action="store_true")
    rp.add_argument("--rebrief", action="store_true", help="run: rewrite every brief (e.g. after new analyst notes)")
    anp = sub.add_parser("analyst", help="the API research analyst behind the doorbell (public data only)")
    anp.add_argument("action", choices=["ask", "submit", "collect", "spend", "compare", "notes"])
    anp.add_argument("--wait", type=float, default=0, help="collect: keep polling the batch up to this many minutes")
    anp.add_argument("--hours", type=float, default=24, help="notes: notes finished in the last N hours")
    anp.add_argument("--all", action="store_true", help="notes: every note, not only the newest per company")
    anp.add_argument("question", nargs="?", help="ask: the question; compare: prepare | run | run-local | sheet | score")
    anp.add_argument("--approve", action="store_true", help="go ahead with a job above your per-job limit")
    anp.add_argument("--asof", type=_d, default=date.today())

    qtp = sub.add_parser("quant", help="quant researcher: map an idea to a tested study template and run it (S46)")
    qtp.add_argument("idea")
    evp = sub.add_parser("event", help="event research: check a piece of news, peers, history, a plan (S46)")
    evp.add_argument("text")
    evp.add_argument("--asof", type=_d, default=date.today())
    thp = sub.add_parser("thesis", help="thesis tracker: add, show, update (S46)")
    thp.add_argument("action", choices=["add", "show", "update", "close"])
    thp.add_argument("text", nargs="?", default="")
    thp.add_argument("--keywords", default="", help="comma list of words that mark the thesis in filings and news")
    thp.add_argument("--sectors", default="", help="comma list of sectors it concerns")
    thp.add_argument("--hold-cash", type=float, default=0.0, help="share of new money kept in a liquid fund meanwhile")
    thp.add_argument("--months", type=int, default=12)
    thp.add_argument("--asof", type=_d, default=date.today())
    sub.add_parser("drift", help="re-test every adopted rule on the data since it was fixed (S46)")
    sub.add_parser("inbox", help="read every file dropped into PFLAB_PM_DIR/inbox into the knowledge graph")
    vp = sub.add_parser("verify", help="S67: local acceptance of a candidate release: prerequisites, sandbox, connector reads, migration and rollback "
                                        "rehearsal on copies, a restart drill; changes nothing of yours, prints a sanitized report")
    vp.add_argument("--app", help="the installed app's folder (default: from release.toml, else PFLAB_PM_DIR)")
    vp.add_argument("--report", help="write the report here (and a .json beside it)")
    vp.add_argument("--wake-check", action="store_true", help="only: did the app see and recover from a real sleep?")
    vp.add_argument("--hour-check", action="store_true", help="only: has the app run an hour on its own, without stalling, doing work?")
    vp.add_argument("--live-model", action="store_true", help="also one small model call through the privacy gate and the budget")
    vp.add_argument("--offline", action="store_true", help="do not contact Kite or Gmail")
    upp = sub.add_parser("update", help="S65: the installed app updates to the newest release tag (store backed up first), or --rollback")
    upp.add_argument("--rollback", action="store_true", help="return to the previous release and the store from before the update")
    upp.add_argument("--check", action="store_true", help="only say whether a newer release exists")
    sup = sub.add_parser("setup", help="S65: secrets (typed, never echoed or printed) and which are set")
    sup.add_argument("action", choices=["secrets", "status"])
    sup.add_argument("--only", nargs="*", choices=["kite", "telegram", "anthropic", "openai", "sec"], help="just these sections")
    sup.add_argument("--change", action="store_true", help="ask again for values already set")
    enp = sub.add_parser("engine", help="S85: the model engines behind the one door: list | test NAME [--thinking medium,high] | use NAME | shadow NAME | unshadow NAME")
    enp.add_argument("action", choices=["list", "test", "use", "shadow", "unshadow"])
    enp.add_argument("name", nargs="?")
    enp.add_argument("--thinking", default="", help="test: thinking levels to grade, comma list (low,medium,high,max)")
    enp.add_argument("--yes", action="store_true", help="use / shadow: his Yes to the notice that is shown (recorded, dated)")
    stp = sub.add_parser("studies", help="results of the S45 split study and the S49 memory comparison")
    stp.add_argument("which", choices=["split", "memory"])
    fcp = sub.add_parser("forecast", help="S64 forecasts: price ranges, turnover (tickets), results; run | show | test (calibration, long)")
    fcp.add_argument("action", choices=["run", "show", "test"])
    fcp.add_argument("--asof", type=_d, default=date.today())

    lp = sub.add_parser("learner", help="S64 the learner's tests: status, register-s64, reregister, test --claim ID, seed")
    lp.add_argument("action", choices=["status", "register-s64", "register-rules", "reregister", "test", "seed"])
    lp.add_argument("--claim", type=int, help="claim id (test)")

    a = p.parse_args(argv)
    from pflab import guard
    guard.set_flags(a.paid, a.live)
    if a.cmd == "setup":
        return _setup(a)
    if a.cmd == "verify":
        from pathlib import Path as _P

        from pflab import verify
        rep = verify.run(_P(a.app) if a.app else None, report=_P(a.report) if a.report else None, wake=a.wake_check, hour=a.hour_check, model=a.live_model,
                         offline=a.offline)
        print(rep.text())
        return verify.exit_code(rep)
    if a.cmd == "engine":
        return _engine(a)
    if a.cmd == "update":
        return _update(a)
    if a.cmd == "learner":
        return _learner(a)
    if a.cmd == "forecast":
        return _forecast(a)
    if a.cmd == "studies":
        import json as _js
        from pflab.data import data_dir
        f = data_dir() / ("research/split_study.json" if a.which == "split" else "llm_eval/memory_compare.json")
        if not f.exists():
            print(f"not run yet ({f.name})")
            return 0
        d = _js.loads(f.read_text(encoding="utf-8"))
        if a.which == "split":
            print("decision:", d["decision"])
            for per, r in d["results"].items():
                print(f"  {per:<12}" + "  ".join(f"{k} {v['mean_bps']:+.1f} bps (t {v['t']:.1f})" for k, v in r.items()))
        else:
            print({k: d[k] for k in ("items", "questions", "dev", "test", "chosen_on_dev", "adopted", "minutes")})
        return 0
    if a.cmd in ("bot", "trades", "memory", "questions", "research", "analyst", "quant", "event", "thesis", "drift",
                 "inbox"):
        return _agents_cli(a)
    if a.cmd == "llm":
        return _llm(a)
    if a.cmd == "service":
        return _service(a)
    if a.cmd == "conductor":
        return _conductor(a)
    if a.cmd == "workshop":
        return _workshop(a)
    if a.cmd == "ipo":
        return _ipo(a)
    if a.cmd == "us":
        return _us(a)
    if a.cmd == "list":
        from pflab.plan import stock_list as slm
        from pflab.pm import store as _store
        if a.list_cmd == "show":
            for s in slm.load():
                print(f"  {s['symbol']:<12} {s['isin']}  BSE {s.get('scrip', '-')}")
            return 0
        if a.list_cmd == "remove":
            print("removed" if slm.remove(a.symbol) else "not on the list")
            return 0
        r = slm.add(_store.connect(), a.symbol)
        if not r["added"]:
            print(r["why"])
            return 1
        print(f"added {r['symbol']} ({r['name']}, {r['sector']}); guard {r['guard'].upper()}"
              + (f": {'; '.join(r['reasons'])}" if r["reasons"] else ""))
        print(f"graph: {r['graph']}; news arrives with the next GKG collection")
        if not a.no_brief:
            from datetime import date as _date
            from pflab.agents import brief as br
            b = br.build(_store.connect(), r["symbol"], _date.today(), {"verdict": r["guard"], "reasons": r["reasons"]},
                         br.chosen_llm())
            print(("research brief (checked):\n" if b.verified else "") + b.text)
        return 0
    if a.cmd == "kg":
        from pflab.kg import build as kbm, graph as kgm
        from pflab.plan import guards as gd
        from pflab.pm import store as _store
        con = _store.connect()
        if a.kg_cmd == "build":
            today = date.today()
            print(kbm.refresh(con, today, gd.stock_list(), a.filings_since, a.gkg_since,
                              guards_list=gd.check_all(con, today, gd.stock_list())))
            print(con.execute("SELECT kind, count(*) FROM kg_nodes GROUP BY 1 ORDER BY 2 DESC").fetchall())
            return 0
        if a.kg_cmd in ("viz", "obsidian"):
            from pflab.kg import viz
            if a.kg_cmd == "viz":
                data = viz.export(con, a.days, with_entities=a.entities)
                p = viz.html(data, _store.pm_dir() / "reports" / "kg.html")
                print(f"{len(data['nodes'])} nodes, {len(data['links'])} links -> {p}")
            else:
                n = viz.obsidian(con, _store.pm_dir() / "obsidian", a.days)
                print(f"{n} notes -> {_store.pm_dir() / 'obsidian'} (open it as a vault, then Graph view)")
            return 0
        if a.kg_cmd == "text":
            from pflab.data import data_dir
            from pflab.kg import text as ktm
            print(ktm.fetch_texts(con, data_dir() / "kg" / "text", a.limit))
            return 0
        row = con.execute("SELECT node_id, name FROM kg_nodes WHERE kind='company' AND "
                          "json_extract_string(attrs_json, '$.symbol') = ?", [a.symbol.upper()]).fetchone()
        if not row:
            print(f"{a.symbol}: not in the graph (run pflab kg build)")
            return 1
        print(f"{row[1]} ({a.symbol.upper()})")
        for r in kgm.neighbours(con, row[0]).itertuples():
            if not str(r.other).startswith("doc:"):
                print(f"  {r.rel:<18} {r.other}  since {r.valid_from:%Y-%m-%d}")
        tl = kgm.timeline(con, row[0], date.today() - timedelta(days=a.days), limit=40)
        for r in tl.itertuples():
            tone = "" if r.tone != r.tone or r.tone is None else f" tone {r.tone:+.1f}"
            print(f"  {r.published_at:%Y-%m-%d %H:%M} {r.kind:<8} {str(r.title)[:90]} ({r.source}{tone})")
        return 0
    if a.cmd == "ask":
        from pflab.agents import centre
        from pflab.pm import store as _store
        ans = centre.ask(_store.connect(read_only=True), a.question, a.asof,
                         tools_override=a.tools.split(",") if a.tools else None)
        print(ans.text)
        print()
        print(f"[agents: {', '.join(ans.tools)} via {ans.router}; "
              f"{'checked by the guard' if ans.verified else 'UNCHECKED: facts only'}]")
        if a.show_facts:
            print(centre.facts_table(ans.facts))
        return 0
    if a.cmd == "pm":
        return _pm(a)
    if a.cmd == "collect":
        if a.source == "bhavcopy":
            from pflab.data import bhavcopy as m
        elif a.source == "bse":
            from pflab.data import bse_announcements as m
        else:
            from pflab.data import gdelt as m
        print(m.collect(a.start, a.end))
        return 0
    return 0


def _llm(a) -> int:
    from pflab.llm import client, registry, smoke
    from pflab.pm import store
    if a.llm_cmd == "models":
        try:
            for name, m in sorted(client.installed().items()):
                print(f"{name:<28} {m['parameter_size']:<8} {m['quantization']:<8} {m['digest'][:12]}")
        except client.OllamaError as e:
            print(e)
        for p in registry.load_picks():
            print(f"pick: {p['role']:<9} {p['model']:<20} registered {p['registered_at']}  evaluated: {p.get('evaluated_at') or 'no'}  decision: {p.get('decision') or '-'}")
        return 0
    if a.llm_cmd == "evaluate":
        from pflab.llm import evalset
        r = evalset.evaluate(store.connect(), a.model, a.role, lambda m: client.as_llm(m), evalset.build(n=a.tasks))
        print(f"{r.model}: first-attempt pass {r.first_pass}/{r.n} = {r.first_attempt_pass_rate:.1%}; "
              f"within 3 attempts {r.within_retries}/{r.n}; {r.seconds:.0f}s; runs {r.run_ids[0]}..{r.run_ids[-1]}")
        return 0
    if a.llm_cmd == "tune":
        from pflab.data import data_dir
        from pflab.llm import tuning
        from pflab.plan import guards as gd
        if a.task == "report":
            import json as _js
            fs = sorted((data_dir() / "llm_eval" / "tuning").glob("*.json"))
            for f in fs:
                r = _js.loads(f.read_text(encoding="utf-8"))
                print(f"{r['task']:<12} train {r['train']}  best {r['best']}  test {r['test']}  rule {r['rule']}  "
                      f"{'ADOPT' if r['adopt'] else ('passes, v0 kept' if r['passes_threshold'] else 'gap remains: QLoRA candidate')}"
                      f"  ({r['minutes']} min)")
            print(f"{len(fs)} task(s) reported" if fs else "no tuning results yet")
            return 0
        m = registry.chosen("general")
        if not m:
            print("no model chosen")
            return 1
        con = store.connect(read_only=True) if a.task in ("writing", "research") else None
        r = tuning.run(a.task, m, data_dir(), con=con, stocks=gd.stock_list() if con is not None else None,
                       log=lambda s: print(s, flush=True))
        print({k: r[k] for k in ("task", "train", "best", "test", "rule", "adopt", "minutes")})
        return 0
    if a.llm_cmd in ("eval12", "decide12"):
        import json as _json
        from datetime import datetime as _dt
        from pflab.data import data_dir
        from pflab.llm import eval12
        out = data_dir() / "llm_eval" / eval12.ROUNDS[a.round]["results"]
        base_role = {1: "eval12", 2: "eval12-r2", 3: "eval12-r3"}[a.round]
        if a.llm_cmd == "decide12":
            reps = [_json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("*.json"))]
            sizes = {p["model"]: p.get("size_gb", 1e9) for p in registry.load_picks() if p["role"].startswith("eval12")}
            d = eval12.decide(reps, sizes)
            print(d)
            if a.record:
                now = _dt.now()
                for r in reps:
                    uses = [u for u, m in (("general", d["general"]), ("routing", d["routing_and_tagging"])) if m == r["model"]]
                    role = "eval12-decision" if r["model"] == "laya" else base_role
                    registry.record_decision(role, r["model"], ("chosen " + "+".join(uses)) if uses else "not chosen", now)
                print("recorded in configs/llm_models.toml: the agents now use "
                      f"{d['general'] or 'no model (facts only)'} for answers, {d['routing_and_tagging'] or 'keywords'} for routing")
            return 0
        role = "eval12-decision" if a.model == "laya" else base_role
        registry.require_registered(role, a.model, _dt.now())
        tasks = a.only or (["routing", "materiality"] if role == "eval12-decision" else
                           ["routing", "answers", "extraction", "materiality"])
        if role == "eval12-decision":                 # Laya answers only on /v1/systemone (protocol amendment 1)
            rep = eval12.evaluate_laya(client.http_transport, data_dir())
        else:
            rep = eval12.evaluate(a.model, eval12.logged(client.chat, store.connect(), role), data_dir(), tasks,
                                  round_=a.round)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{a.model.replace(':', '_')}.json").write_text(
            _json.dumps({"model": a.model, "scores": rep.scores, "passes": rep.passes(), "detail": rep.detail,
                         "run_at": _dt.now().isoformat()}, indent=1, default=str), encoding="utf-8")
        print(a.model, {k: round(v, 3) for k, v in rep.scores.items()}, rep.passes())
        return 0
    if a.llm_cmd == "smoke":
        r = smoke.run(store.connect(), a.model)
        print(r)
        return 0 if r["passed"] else 1
    return 0





def _update(a) -> int:
    """pflab update [--check] | --rollback: only in the installed app; refuses while the dashboard or a job holds the store."""
    from pflab import release, update as upd
    from pflab.pm import store
    try:
        if a.rollback:
            r = upd.rollback(release.ROOT, store.pm_dir())
        else:
            r = upd.update(release.ROOT, store.pm_dir(), check_only=a.check)
    except upd.UpdateError as e:
        print(f"refused: {e}")
        return 1
    print(r["note"])
    if r.get("error"):
        print(f"why: {r['error']}")
        return 1
    return 0


def _setup(a) -> int:
    """pflab setup secrets|status: the secrets file by prompt (getpass), names only on screen. Statement passwords are asked
    for under the names his sources file gives them."""
    from pflab.ingest import sources as srcs
    from pflab.pm import secrets_setup as ss
    from pflab.pm import store
    if a.action == "status":
        for name, ok in ss.status().items():
            print(f"{'set    ' if ok else 'missing'}  {name}")
        return 0
    try:
        names = ss.password_names(srcs.load(store.pm_dir() / "sources.toml"))
    except Exception:
        names = []                                  # no sources file yet: Setup writes it, then run this again for the passwords
    ss.prompt(a.only, None if a.only else names, change=a.change)
    return 0


def _engine(a) -> int:
    """pflab engine list|test|use|shadow|unshadow (S85): the switch. Close the dashboard first (one process holds the store). A key is never printed."""
    from datetime import datetime

    from pflab.llm import gateway
    from pflab.pm import store
    con = store.connect()
    st = gateway.settings()
    if a.action == "list":
        for e in gateway.engines_status(con, st):
            flags = ("IN USE" if e["in_use"] else "") + (" SHADOW" if e["shadow"] else "")
            print(f"{e['name']:8} {e['vendor']:10} key {e['key']:7} {'usable' if e['usable'] else 'NOT usable'} {flags}".rstrip())
            for r, d in e["roles"].items():
                print(f"    {r:7} {d['model']:16} thinking {d['thinking']:6} ${d['price_in']}/{d['price_out']} per million tokens in/out")
            ex = e.get("exam")
            print("    exam:   " + (f"{'passed' if ex['form_pass'] else 'FAILED'} the form part; {ex['grade']}" if ex else "not run (pflab engine test " + e["name"] + ")"))
            if e["lacks"]:
                print("    lacks:  " + ", ".join(e["lacks"]) + " (the door degrades these by rule)")
            for p in e["problems"]:
                print("    problem: " + p)
        return 0
    if not a.name:
        print("name the engine: pflab engine " + a.action + " NAME")
        return 2
    if a.action == "test":
        try:
            from pflab.llm import exam
        except ImportError:
            print("the exam is not built in this checkout yet (llm/exam.py); nothing was run")
            return 1
        levels = [x.strip() for x in a.thinking.split(",") if x.strip()] or None
        r = exam.run(con, a.name, thinking=levels, now=datetime.now())
        print(r if isinstance(r, str) else getattr(r, "text", lambda: str(r))() if callable(getattr(r, "text", None)) else r)
        return 0
    fn = {"use": gateway.use, "shadow": gateway.shadow}.get(a.action)
    r = fn(con, a.name, yes=a.yes, now=datetime.now()) if fn else gateway.unshadow(con, a.name)
    if r.get("notice"):
        print(r["notice"])
    print(r["reason"])
    return 0 if r["ok"] else 1


def _learner(a) -> int:
    """The learner's own commands. `test` is long (the full panel, more than 5 minutes): the investor's."""
    from datetime import datetime
    from pathlib import Path

    from pflab.data import data_dir
    from pflab.learner import claims, counter, run as lrun
    from pflab.pm import store
    con, now = store.connect(), datetime.now()
    proto = data_dir() / "learner" / "protocols"
    if a.action == "status":
        print(lrun.status(con))
        return 0
    if a.action == "seed":
        print(f"seed rows added: {counter.seed(con, now)}; {counter.line(con)}")
        return 0
    if a.action == "reregister":
        print(f"re-registered {claims.reregister_stale(con, proto, now)} claims under the current test code")
        return 0
    if a.action == "register-rules":
        from pflab.learner import rules
        for rule, state in rules.register_all(con, proto, now).items():
            print(f"{rule}: {state}")
        print(counter.line(con))
        return 0
    if a.action == "register-s64":
        url = "docs/protocols/s64_reversion_protocol.md"
        ids = {
            "sector_reversion": claims.register_study(
                con, "sector_reversion", {"direction": "low"},
                "A stock that is cheap relative to a sector index it is cointegrated with earns more than that sector over the "
                "next month.", "The bottom quintile of the spread's z, among names cointegrated with their sector index "
                "(Engle-Granger p < 0.05 over 36 months), against the sector's next-month return.",
                "S64 pre-registered study: sector reversion", url, now),
            "short_term_reversal": claims.register_study(
                con, "cross_section", {"signal": "reversal_1m", "direction": "low", "months": 1},
                "The previous month's losers outperform the previous month's winners over the next month: short-term "
                "reversal.", "Stocks ranked by the last month's total return; the lowest quintile against all members, "
                "one month ahead.", "S64 pre-registered study: short-term reversal", url, now)}
        for name, cid in ids.items():
            print(f"{name}: claim #{cid} -> {claims.register(con, cid, proto, now)}")
        return 0
    if a.claim is None:
        print("pass --claim ID")
        return 2
    print(f"claim #{a.claim}: {claims.test(con, a.claim, data_dir(), now)}")
    row = con.execute("SELECT status, why FROM learn_claims WHERE claim_id=?", [a.claim]).fetchone()
    print(row[0], "-", row[1])
    return 0


def _forecast(a) -> int:
    from pflab.pm import store
    from pflab.quant import forecast as fl
    con = store.connect()
    if a.action == "show":
        print(fl.show(con))
        return 0
    if a.action == "test":                                   # the registered calibration test: long, the investor's
        from datetime import datetime as _dt

        from pflab.data import data_dir
        from pflab.quant import ranges_eval as re_
        res = re_.run_test(data_dir(), con=con, now=_dt.now(), progress=print)
        print(res["text"])
        return 0
    from pflab.conductor import calendar as mcal
    from pflab.data import data_dir
    from pflab.kg import build as kb
    from pflab.plan import guards as gd
    r = fl.run(con, data_dir(), a.asof, kb.universe(con, gd.stock_list()), mcal.load())
    print(f"forecasts as of {r['asof']}: turnover {r['turnover']}, revenue {r['revenue']}, margin {r['margin']} "
          f"(stored {r['stored']}, scored {r['scored']}, skipped {r['skipped']}); price ranges served by {r['serving']}")
    return 0


def _agents_cli(a) -> int:
    from pflab.agents import memory as mem
    from pflab.agents import questions as qs
    from pflab.pm import secrets as sec
    from pflab.pm import store
    if a.cmd == "bot":
        from pflab.service import bot
        n = bot.run(sec.load(), connect=store.connect, once=a.once)
        print(f"{n} message(s) answered")
        return 0
    if a.cmd == "inbox":
        from pflab.agents import inbox
        from pflab.data import data_dir
        from pflab.llm import registry
        reads = inbox.run(store.connect(), store.pm_dir() / "inbox", data_dir(), registry.chosen("general"))
        for r in reads:
            print(f"  {r.file} / {r.sheet}: {r.kind}, {r.shape}, {len(r.isins)} compan(ies), {r.facts} figure(s)")
        err = list((store.pm_dir() / "inbox").glob("*.error.txt"))
        print(f"{len(reads)} sheet(s) read into the graph" + (f"; {len(err)} file(s) failed (see *.error.txt)" if err else ""))
        return 0
    if a.cmd == "quant":
        from pflab.agents import quant
        print(quant.run(a.idea))
        return 0
    if a.cmd == "drift":
        from pflab.quant import drift
        rows = drift.run_all()
        print(drift.render(rows))
        con = store.connect()
        for r in rows:
            if r["drift"]:
                qs.ask(con, "drift", f"drift:{r['rule']}:{date.today():%Y-%m}",
                       f"Drift check: {r['rule']} no longer behaves as registered ({r['detail']}). Keep it, re-study it, "
                       "or retire it?")
        return 0
    if a.cmd == "event":
        from pflab.agents import event
        print(event.research(store.connect(), a.text, a.asof))
        return 0
    if a.cmd == "thesis":
        from pflab.agents import thesis
        con = store.connect()
        if a.action == "add":
            kw = [k.strip() for k in a.keywords.split(",") if k.strip()]
            sc = [s.strip() for s in a.sectors.split(",") if s.strip()]
            tid = thesis.add(con, a.text, kw, sc, a.months, a.hold_cash)
            print(f"thesis #{tid} kept; it is checked every night")
            print(thesis.render(thesis.update(con, a.asof)))
            return 0
        if a.action == "close":
            con.execute("UPDATE theses SET status='closed' WHERE thesis_id=?", [int(a.text)])
            print(f"thesis #{a.text} closed")
            return 0
        rows = thesis.update(con, a.asof, with_cost=a.action == "update")
        print(thesis.render(rows))
        return 0
    if a.cmd == "analyst" and a.action == "collect" and a.wait:
        from pflab.agents import analyst as an
        print(an.collect_until_done(store.connect, an.make_client(sec.load()), a.wait))
        return 0
    con = store.connect()
    if a.cmd == "analyst":
        from datetime import datetime as _dt
        from pflab.agents import analyst as an
        if a.action == "spend":
            cfg = an.config()
            print(f"this month ~Rs {an.month_spend_inr(con, _dt.now()):,.0f} of Rs {cfg['cap']:,.0f}; "
                  f"adopted: {cfg['adopted']}")
            for r in con.execute("SELECT call_id, created_at, mode, status, topic, round(cost_inr, 1) FROM api_calls "
                                 "ORDER BY call_id DESC LIMIT 20").fetchall():
                print("  ", *r)
            return 0
        if a.action == "ask":
            print(an.ask_deep(con, a.question or "", a.asof, approved=a.approve, secrets=sec.load()))
            return 0
        if a.action == "notes":
            notes = an.recent_notes(con, _dt.now() - timedelta(hours=a.hours))
            shown = notes if a.all else an.newest_per_topic(notes)
            for cid, topic, at, inr, text in shown:
                body = re.sub(r"(?m)^#{1,3} ", "#### ", text)      # the note's own headings sit under the company
                print(f"### {topic}  (analyst note #{cid}, {at:%d-%b %H:%M}, ~Rs {inr or 0:,.1f})\n\n{body}\n")
            if len(shown) < len(notes):
                print(f"({len(notes) - len(shown)} earlier note(s) on the same companies not shown: "
                      "pflab analyst notes --all)")
            print(f"{len(notes)} note(s); ~Rs {sum(n[3] or 0 for n in notes):,.1f}; month so far ~Rs "
                  f"{an.month_spend_inr(con, _dt.now()):,.0f} of Rs {an.config()['cap']:,.0f}")
            return 0
        if a.action == "compare":
            from pflab.agents import analyst_compare as ac
            from pflab.agents import brief as br
            from pflab.plan import guards as gd
            stage = a.question or ""
            if stage == "prepare":
                lst = gd.stock_list()
                names = {s["symbol"]: (con.execute("SELECT name FROM instruments WHERE isin=? LIMIT 1", [s["isin"]])
                                       .fetchone() or [s["symbol"]])[0] for s in lst}
                p = ac.prepare(lst, names)
                print(f"{p}\nSHA-256 {ac.sha(p)}: record it in docs/STUDIES.md before 'run'")
            elif stage == "run":
                print(ac.run(con, a.asof, br.chosen_llm(), an.make_client(sec.load())))
            elif stage == "run-local":
                from pflab.llm import registry as _reg
                print(ac.run_local(con, a.asof, ac.local_llm(_reg.chosen("general"))))
            elif stage == "sheet":
                print(ac.sheet())
            elif stage == "auto-rate":
                print(ac.auto_rate(con, a.asof))
            elif stage == "score":
                print(ac.score())
            else:
                print("compare needs a stage: prepare | run | sheet | score")
                return 2
            return 0
        client = an.make_client(sec.load())
        print(an.submit_batch(con, client) if a.action == "submit" else an.collect_batches(con, client))
        return 0
    if a.cmd == "research":
        from pflab.agents import brief as br
        from pflab.agents import researcher as rs
        from pflab.plan import guards as gd
        if a.action == "show":
            if not a.symbol:
                print("research show needs a symbol")
                return 2
            print(rs.show(con, a.symbol, a.asof))
            return 0
        if a.action == "digest":
            from datetime import datetime as _dt2
            print(rs.digest_since(con, _dt2.now() - timedelta(hours=a.hours)))
            return 0
        lst = gd.stock_list()
        if a.action == "deep":
            out = rs.deep_queue(con, a.asof, lst, everyone=a.all)
            for sym, st in out.items():
                print(f"  {sym:<12} {st}")
            print(f"{sum(v == 'queued' for v in out.values())} note(s) queued for the overnight batch; "
                  f"{sum(v == 'reused' for v in out.values())} reused")
            return 0
        gs = {x.symbol: {"verdict": x.verdict, "reasons": x.reasons} for x in gd.check_all(con, a.asof, lst)}
        from pflab.llm import tuning
        rep = rs.run(con, a.asof, lst, a.since, None if a.no_briefs else br.chosen_llm(), gs, write_briefs=not a.no_briefs,
                     rebrief=a.rebrief, tagger=tuning.materiality_tagger())
        print(rep.digest())
        return 0
    if a.cmd == "trades":
        from pflab.agents import tradecheck as tc
        if a.action == "pending":
            for r in con.execute("SELECT trade_date, trade_id, side, qty, symbol, price, status FROM kite_trades "
                                 "ORDER BY trade_date, trade_id").fetchall():
                print("  ".join(str(x) for x in r))
            return 0
        from pflab.ingest import kite as km
        k = km.client(sec.load())
        if k is None:
            print("Kite is not logged in today: run tools/kite_login.py first")
            return 1
        print(tc.check(con, k, a.asof).render())
        return 0
    if a.cmd == "memory":
        if a.action == "compare":
            from pflab.agents import memory_compare as mcmp
            from pflab.data import data_dir
            from pflab.llm import client, registry
            r = mcmp.run(con, a.asof if hasattr(a, "asof") else date.today(),
                         client.as_llm(registry.chosen("general"), num_predict=60), data_dir(),
                         log=lambda s: print(s, flush=True))
            print({k: r[k] for k in ("items", "questions", "dev", "test", "chosen_on_dev", "adopted", "minutes")})
            return 0
        if a.action in ("index", "find"):                  # S49 look-up: warm the index / try a question
            from pflab.agents import memory_compare as mcmp
            hits = mcmp.lookup(con, a.text or "index", date.today())
            if a.action == "find":
                for it in hits:
                    print(f"{str(it['at'])[:10]} {it['kind']}: {it['text'][:200]}")
            else:
                print(f"look-up index current ({len(mcmp.corpus(con, date.today()))} items)")
            return 0
        if a.action == "add":
            print(f"kept as {a.kind} #{mem.remember(con, a.kind, a.text, subject=a.subject, source='cli', supersedes=a.supersedes)}")
            return 0
        for m in mem.recall(con, words=a.text, include_past=True, limit=50):
            print(m.line())
        return 0
    if a.answer:
        print(f"kept as memory #{qs.answer(con, int(a.answer[0]), a.answer[1])}")
        return 0
    for q, agent, txt in qs.open_questions(con):
        print(f"#{q} ({agent}): {txt}")
    return 0


def _service(a) -> int:
    from datetime import datetime

    from pflab.service import backup as bk
    from pflab.service import health, jobs, runner
    from pflab.service import telegram as tgm
    if a.sv_cmd == "tick":                     # S58b: the scheduled tick stands aside while the dashboard runs the jobs
        import sys

        from pflab.pm import store
        if sys.stdout is None:                 # pythonw (the scheduled task): what it says goes to a log
            (store.pm_dir() / "reports").mkdir(parents=True, exist_ok=True)
            sys.stdout = sys.stderr = open(store.pm_dir() / "reports" / "tick.log", "a", encoding="utf-8", buffering=1)
            print(f"--- tick {datetime.now():%Y-%m-%d %H:%M:%S}")
        who = runner.dashboard_running(store.pm_dir())
        if who:
            print(f"the dashboard is open ({who}) and runs the jobs itself: nothing to do")
            return 0
        only = runner.unattended_jobs(store.pm_dir())
        if not only:
            print("the preset in Settings is Off: no jobs run")
            return 0
        ctx = runner.make_ctx()
        jobs.reap_at_start(ctx.con, ctx.now)    # S66: a run that died with an earlier process does not hold its slot
        for r in runner.tick_and_notify(ctx, only):
            print(f"{r.job:<10} {r.status:<8} {r.detail[:200]}")
        return 0
    ctx = runner.make_ctx()
    if a.sv_cmd == "run":
        if a.job not in jobs.REGISTRY:
            print(f"unknown job {a.job!r}; one of {sorted(jobs.REGISTRY)}")
            return 2
        r = jobs.run_job(ctx, jobs.REGISTRY[a.job])
        print(f"{r.job} {r.status} {r.detail[:300]}")
        return 0 if r.status != "failed" else 1
    if a.sv_cmd == "plan":
        for r in jobs.plan(ctx):
            print(f"{r['job']:<10} {'DUE ' if r['due'] else 'idle'} {r['why']}")
        return 0
    if a.sv_cmd == "status":
        items = health.check(ctx)
        print(health.render(items, ctx.now))
        return 0 if health.overall(items) != "FAIL" else 1
    if a.sv_cmd == "test-alert":
        tgm.enqueue(ctx.con, tgm.format_test(), "test", dedup_key=f"test:{datetime.now():%Y%m%d%H%M%S}")
        out = tgm.flush(ctx.con, tgm.make_sender(ctx.secrets), ctx.now)
        print(out)
        return 0 if out.get("sent") else 1
    if a.sv_cmd == "backup":
        t = bk.target_dir()
        if t is None:
            print("no backup target set: set PFLAB_BACKUP_DIR or configs/service.toml [backup] target")
            return 2
        print(bk.backup(ctx.con, ctx.pm_dir / "ledger.duckdb", t, ctx.now, bk.keep_count()))
        return 0
    return 0


def _us(a) -> int:
    """pflab us trade|remit|show|gains|fx: the US sleeve's entries (S64 Phase 6). A statement parser will land in the same tables."""
    import json as _js
    from datetime import date as _date

    from pflab.data import data_dir
    from pflab.ledger import foreign as lf
    from pflab.pm import store
    con = store.connect()
    today = _date.today()
    if a.action == "fx":
        print(f"{lf.load_fx(con, data_dir())} new USDINR rates; {lf.FX_LABEL}")
        return 0
    if a.action == "trade":
        key = a.isin or (lf.pseudo_isin(a.cik) if a.cik else f"US:{a.symbol.upper()}")
        lf.register_instrument(con, a.symbol.upper(), key, a.symbol.upper(), etf=a.etf)
        tid = lf.add_trade(con, _date.fromisoformat(a.date), a.symbol, key, a.side, a.qty, a.price, a.charges or 0.0, source="manual")
        print(f"trade #{tid}: {a.side} {a.qty:g} {a.symbol.upper()} at USD {a.price:g} ({key})")
        return 0
    if a.action == "remit":
        from pflab.tax import foreign as tf
        before = lf.remitted_in_fy(con, _date.fromisoformat(a.date))
        tcs = a.tcs if a.tcs is not None else tf.tcs(before["inr"], a.inr)["tcs_rs"]
        rid = lf.add_remittance(con, _date.fromisoformat(a.date), a.usd, a.inr, tcs, a.bank or "")
        print(f"remittance #{rid}: USD {a.usd:,.0f} (Rs {a.inr:,.0f}), TCS {'recorded' if a.tcs is not None else 'estimated'} Rs {tcs:,.0f}; "
              f"{lf.remitted_in_fy(con, _date.fromisoformat(a.date))}")
        return 0
    if a.action == "gains":
        if a.slab is None:
            print("give your slab rate for short-term gains: --slab 0.30")
            return 2
        print(_js.dumps(lf.gains(con, a.fy or (today.year if today.month >= 4 else today.year - 1), a.slab), indent=1, default=str))
        return 0
    from pflab.tax import foreign as tf
    print(_js.dumps({"positions": lf.positions(con, today), "lrs_this_year": lf.remitted_in_fy(con, today),
                     "lrs_room_usd": tf.lrs_room(lf.remitted_in_fy(con, today)["usd"])}, indent=1, default=str))
    return 0


def _ipo(a) -> int:
    """pflab ipo plan --name N --qty Q --price P --budget B [--group G]: facts and choices for an allotment; no prediction."""
    import json as _js
    from datetime import date as _date

    from pflab.data import data_dir
    from pflab.plan import ipo
    from pflab.pm import store
    r = ipo.strategy(store.connect(), data_dir(), _date.today(), a.name, a.qty, a.price, a.budget, a.group, store.pm_dir())
    print(_js.dumps(r, indent=1, default=str))
    return 0


def _workshop(a) -> int:
    import json as _js

    from pflab.agents import workshop as wk
    from pflab.data import data_dir
    from pflab.pm import store
    pm = store.pm_dir()
    if a.action == "list":
        for r in wk.listing(pm):
            print(f"{r['id']}  [{r['label']}]  {r['question'][:90]}")
        return 0
    if a.action in ("show", "promote", "rerun") and not a.text:
        print("give the calculation id (pflab workshop list)")
        return 2
    if a.action == "show":
        print((wk.folder(pm) / a.text / "meta.json").read_text(encoding="utf-8"))
        return 0
    if a.action == "promote":
        print(_js.dumps(wk.promote(pm, a.text, by="investor"), indent=1))
        return 0
    con = store.connect()
    if a.action == "rerun":
        r = wk.rerun(pm, a.text, lambda names: {n: wk.load_dataset(n, con, data_dir(), a.asof) for n in names})
        print("ok" if r.ok else "failed: " + "; ".join(r.problems))
        for k, v in r.result.items():
            print(f"  {k}: {v}")
        return 0 if r.ok else 1
    if not a.text.strip():
        print('give the question: pflab workshop ask "..."')
        return 2
    from pflab.pm import secrets as sec
    try:
        s = sec.load()
    except sec.SecretsError:
        s = None
    out = wk.ask(con, a.text, pm, data_dir(), a.asof, writer=a.writer, secrets=s, approved=a.approve)
    print(wk.render(out))
    return 0 if out.status == "checked" else 1


def _conductor(a) -> int:
    from pflab.conductor import calendar as cl
    from pflab.conductor import sync
    from pflab.service import jobs, runner
    ctx = runner.make_ctx()
    if a.action == "sheet":
        p = ctx.pm_dir / "reports" / "situation.md"
        print(p.read_text(encoding="utf-8") if p.exists() else "no fact sheet yet: pflab conductor run")
        return 0
    if a.action == "run":
        r = jobs.run_job(ctx, jobs.REGISTRY["conductor"])
        print(f"{r.status} {r.detail[:400]}")
        return 0 if r.status != "failed" else 1
    cal = cl.load()
    gap = sync.offline_gap(ctx.con, ctx.now)
    words = {"market": "open", "pre_open": "not open yet", "after_close": "closed for the day", "closed": "closed today"}
    print(f"{ctx.now:%a %d %b %Y %H:%M}: market {words[cal.mode(ctx.now)]}; next session {cal.next_trading_day(ctx.now.date())}; "
          + ("first start" if gap is None else f"last pass {gap.total_seconds() / 3600:.1f} h ago"))
    print(sync.render(sync.check(ctx, cal)))
    return 0


def _pm(a) -> int:
    from pflab.pm import store
    if a.pm_cmd == "quicko":
        from pathlib import Path as _P

        from pflab.data import data_dir
        from pflab.tax import quicko as qk
        con = store.connect(read_only=not a.check)
        try:
            pack = qk.build(con, a.fy, data_dir())
        except RuntimeError as e:
            print(f"cannot prepare the pack yet: {e}")
            return 1
        out = _P(a.out) if a.out else store.pm_dir() / "reports" / "quicko"
        for p in qk.write_pack(pack, out):
            print(f"wrote {p}")
        print((out / f"summary_FY{a.fy}.txt").read_text(encoding="utf-8"))
        if a.check:
            data = _P(a.check).read_bytes()
            rec = qk.reconcile(pack, data, _P(a.check).name)
            print(f"reconciled {rec['matched']} ISIN(s); {len(rec['differences'])} difference(s) above Rs {rec['tolerance']:g}")
            for r in rec["differences"]:
                print(f"  {r['isin']} {r['name']}: ledger {r['ledger']:,.2f}, file {r['export']:,.2f}, unexplained {r['unexplained']:,.2f}")
            print(f"{qk.ask_differences(con, rec)} new item(s) in Needs from you")
        return 0
    if a.pm_cmd == "reset":
        from pflab.pm import reset as rsm
        try:
            r = rsm.reset(store.pm_dir(), date.today(), a.confirm)
        except (RuntimeError, FileNotFoundError) as e:
            print(f"refused: {e}")
            return 1
        print(f"{r['from']}  ->  {r['to']}")
        for name, size in r["files"]:
            print(f"  {size / 1e6:9.1f} MB  {name}")
        print(f"{len(r['files'])} files, {r['bytes'] / 1e6:.1f} MB: {r['note']}")
        return 0 if r["moved"] or not a.confirm else 1
    if a.pm_cmd == "fresh":
        from pathlib import Path
        from pflab.pm import fresh as frm
        try:
            from pflab.data import data_dir
            repo = Path(__file__).resolve().parents[2]
            r = frm.fresh(store.pm_dir(), Path(a.archive_to), date.today(), a.confirm, {"statements": Path(a.statements)} if a.statements else None,
                          inputs=frm.old_inputs(repo, data_dir()))
        except (RuntimeError, FileNotFoundError, FileExistsError, ValueError) as e:
            print(f"refused: {e}")
            return 1
        print(f"{r['files']} files, {r['bytes'] / 1e6:.1f} MB in {r['from']}: {r['note']}")
        return 0 if r["done"] or not a.confirm else 1
    if a.pm_cmd == "restore":
        from pathlib import Path
        from pflab.pm import fresh as frm
        try:
            r = frm.restore(Path(a.archive), Path(a.into))
        except (RuntimeError, FileExistsError, FileNotFoundError) as e:
            print(f"refused: {e}")
            return 1
        print(f"restored {r['restored']} files to {r['to']}: {r['note']}")
        return 0
    if a.pm_cmd == "init":
        con = store.connect()
        v = con.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
        print(f"{store.db_path()} schema v{v}")
        return 0
    if a.pm_cmd == "instruments":
        from pflab.pm import instruments as ins
        con = store.connect()
        if a.build:
            print(ins.build_and_load(con))
        print(con.execute("""SELECT asset_class, tax_class, count(*) AS n FROM instruments
                             GROUP BY ALL ORDER BY 1, 2""").df().to_string(index=False))
        print("amfi schemes:", con.execute("SELECT count(*) FROM amfi_schemes").fetchone()[0])
        if a.rows:
            q = "SELECT isin, asset_class, tax_class, symbol, name FROM instruments"
            args = []
            if a.asset_class:
                q += " WHERE asset_class = ?"
                args.append(a.asset_class)
            print(con.execute(q + f" ORDER BY isin LIMIT {int(a.rows)}", args).df().to_string(index=False))
        return 0
    if a.pm_cmd == "prices":
        from pflab.pm import prices
        con = store.connect()
        if a.refresh:
            print(prices.refresh(con, a.days, network=not a.no_network))
        for t, c in (("prices", "date"), ("navs", "date"), ("gold_rates", "date")):
            n, lo, hi = con.execute(f"SELECT count(*), min({c}), max({c}) FROM {t}").fetchone()
            print(f"{t}: {n} rows {lo} .. {hi}")
        return 0
    if a.pm_cmd == "advise":
        from pflab.plan import advisor
        con = store.connect()                                                 # guards may save pulled results
        amount = a.amount
        if amount is None:
            from pflab.pm import fd as fdm
            from pflab.plan import deploy
            tr = deploy.schedule(fdm.load(con), 10, a.asof)
            if not tr:
                print("no FD tranche is scheduled: give --amount")
                return 1
            amount = tr[0].amount
            print(f"(the next FD tranche, {tr[0].month:%b %Y}: Rs {amount:,.0f}; priced at today's prices)")
        text, adv, tk = advisor.run(con, a.asof, amount)
        print(text)
        print()
        print(advisor.render(adv, tk))
        return 0
    if a.pm_cmd == "propose":
        from pathlib import Path

        from pflab.plan import monthly
        from pflab.plan import targets as tg
        try:
            t = tg.load(Path(a.targets)) if a.targets else None
            con = store.connect()
            plan, pid = monthly.run(con, a.asof, a.amount, t, log=not a.no_log)
        except (tg.TargetsNotSet, tg.TargetsInvalid) as e:
            print(f"no proposal: {e}")
            return 2
        except Exception as e:
            from pflab.plan.rebalance import PlanError
            if isinstance(e, PlanError):
                print(f"no proposal: {e}")
                return 2
            raise
        from pflab.ingest import kite_depth
        from pflab.plan import guards as gd
        cl = gd.market_cluster(a.asof)
        if cl:
            print(gd.cluster_text(cl, gd.market_dip(a.asof)))
        print(monthly.render(plan, pid, kite_depth.impact_note_fn(con)))
        return 0
    if a.pm_cmd == "results":
        from pflab.fundamentals import pit
        con = store.connect()
        if a.pull:
            hi = pit.latest_qtr_id(a.asof)
            q = pit.fetch_quarters(a.scrip, range(hi - a.quarters - 1, hi + 1))
            print("stored", pit.save(con, pit.date_quarters(q, first_seen=date.today()), "bse_results"), "new quarters")
        dq = pit.load(con, a.scrip)
        last = pit.last_quarters(dq, a.scrip, a.asof, a.quarters)
        if last.empty:
            print(f"no usable quarters for scrip {a.scrip} on {a.asof}")
            return 1
        print(last[["quarter_end", "usable_from", "date_source", "revenue", "pbt", "net_profit", "eps_basic"]].to_string(index=False))
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in pit.ratios(last).items()})
        return 0
    if a.pm_cmd == "lookthrough":
        from pflab.pm import lookthrough as lkt
        sheets = lkt.parse_workbook(a.file)
        if a.sheet:
            pf = sheets[a.sheet]
        elif len(sheets) == 1:
            pf = next(iter(sheets.values()))
        else:
            print(f"workbook has several portfolio sheets, pass --sheet: {sorted(sheets)}")
            return 2
        lkt.save(store.connect(), a.fund, pf, a.as_of, lkt.file_sha(a.file))
        print(f"{a.fund}: {len(pf.holdings)} holdings, weights {pf.total_pct:.2f}%, as of {a.as_of or pf.as_of}")
        return 0
    if a.pm_cmd == "deploy":
        from collections import defaultdict
        from pflab.calc import valuation as val
        from pflab.ledger import events as ev
        from pflab.ledger.book import Ledger
        from pflab.pm import estimate as est
        from pflab.pm import fd as fdm
        from pflab.plan import deploy, monthly, rebalance
        from pflab.plan import targets as tg
        from pflab.risk import report as riskreport
        con = store.connect(read_only=True)
        t = tg.load()
        led = Ledger.replay(ev.load(con), upto=a.asof)
        v = val.value_ledger(led, val.store_price_fn(con), a.asof)
        extra, _ = monthly.fd_debt(con, a.asof)
        values = rebalance.bucket_values(v, riskreport.instruments_frame(con), t, extra)
        fds = fdm.load(con)
        tr = deploy.schedule(fds, a.months, a.asof, a.batch)
        matured = defaultdict(float)
        for f in fds:
            if (f.status == "open" and not f.purpose.startswith("reserve:") and f.maturity >= a.asof
                    and any(x.batch == f.maturity for x in tr)):
                x = fdm.value(f, a.asof)
                matured[f.maturity] += x.value if isinstance(x, est.Estimate) else x
        print(deploy.render(tr, deploy.project(values, t, tr, a.asof, matured), t, a.asof))
        return 0
    if a.pm_cmd == "guards":
        from pflab.pm import fd as fdm
        from pflab.plan import guards as gd
        con = store.connect()
        g = gd.check_all(con, a.asof, gd.stock_list())
        dip = gd.market_dip(a.asof)
        cl = gd.market_cluster(a.asof)
        print(gd.render(g, dip, cl))
        if not a.no_alerts:
            n = gd.queue_alerts(con, a.asof, g, dip, fdm.warnings(fdm.load(con), a.asof), cluster=cl)
            print(f"{n} new alert(s) queued (pflab pm alerts)")
        return 0
    if a.pm_cmd == "alerts":
        if a.drop_before:
            from datetime import datetime as _dt

            from pflab.service import telegram as tgm
            n = tgm.drop_before(store.connect(), _dt.combine(a.drop_before, _dt.min.time()))
            print(f"{n} held message(s) from before {a.drop_before} marked dropped (never sent; --all lists them)")
            return 0
        con = store.connect(read_only=True)
        q = "SELECT msg_id, created_at, kind, status, text FROM outbox " + ("" if a.all else "WHERE status <> 'sent' ") + "ORDER BY msg_id"
        rows = con.execute(q).fetchall()
        for r in rows:
            print(f"#{r[0]} {r[1]:%Y-%m-%d %H:%M} [{r[2]}/{r[3]}] {r[4]}")
        print(f"{len(rows)} alert(s)")
        return 0
    if a.pm_cmd == "impact":
        from pflab.ingest import kite_depth
        snaps = kite_depth.load(f"NSE:{a.symbol.upper()}")
        if snaps.empty:
            print(f"no recorded depth for {a.symbol.upper()}: record some first, during market hours:\n"
                  f"  .venv\\Scripts\\python tools\\kite_depth_record.py --minutes 30 --symbols {a.symbol.upper()}")
            return 1
        r = kite_depth.impact(snaps, a.amount, a.side)
        print(f"{a.side} Rs {a.amount:,.0f} of {a.symbol.upper()} against {r['snapshots']} recorded books "
              f"({snaps['ts'].min():%Y-%m-%d %H:%M} to {snaps['ts'].max():%Y-%m-%d %H:%M}): measured, not simulated")
        if r["median_bps"] is None:
            print(f"  five levels were too thin in all {r['too_thin']} snapshots")
        else:
            print(f"  cost over the mid: median {r['median_bps']:.1f} bp, 90th percentile {r['p90_bps']:.1f} bp "
                  f"(half the spread alone: {r['half_spread_bps']:.1f} bp); too thin in {r['too_thin']} snapshot(s)")
        return 0
    if a.pm_cmd == "simulate":
        from pflab.calc import networth
        from pflab.data import data_dir
        from pflab.plan import targets as tg
        from pflab.risk import montecarlo as mc
        con = store.connect(read_only=True)
        R, Rd = mc.history(data_dir()), mc.history_daily(data_dir())
        t_ = tg.load()
        tm = mc.target_mix(t_, mc.fund_names(con, t_))
        b = networth.build(con, date.today())["buckets"]
        inv = sum(b.values()) or 1.0
        cur = {"stocks": b.get("equity", 0) / inv, "n500": b.get("equity_fund", 0) / inv, "mom50": 0.0,
               "gold": b.get("gold", 0) / inv, "debt": (b.get("debt", 0) + b.get("cash", 0)) / inv, "cash": 0.0}
        res = mc.simulate(R, {"target": tm, "current": cur}, a.years, a.paths, Rd=Rd)
        print(f"Monte Carlo, {a.years} years, {a.paths:,} paths per engine; history {R.index[0]:%b %Y}-{R.index[-1]:%b %Y} "
              "(ESTIMATES from past joint returns, not forecasts)")
        for name, r in res.items():
            for eng, x in r.items():
                y = x.get(f"y{a.years}", {})
                print(f"  {name:<8}{eng:<6} median {x['median_cagr']:.1%}/yr; chance of a fall beyond 35%: "
                      f"{x['p_fall_beyond_limit_any_day']:.0%} on any day ({x['p_fall_beyond_limit']:.0%} at month-ends); "
                      f"Rs 1 after {a.years}y: {y.get('p5', 0):.2f} (bad 5%) / "
                      f"{y.get('p50', 0):.2f} / {y.get('p95', 0):.2f} (good 5%)")
        eq = {k: v for k, v in tm.items() if k not in ("debt", "cash")}
        s_ = sum(eq.values())
        ls = mc.lump_vs_staged(R, {**{k: v / s_ for k, v in eq.items()}, "debt": 0.0, "cash": 0.0})
        for eng, x in ls.items():
            print(f"  10 months vs all at once ({eng}): staged beats lump {x['p_staged_beats_lump']:.0%} of the time; "
                  f"medians {x['staged_median']:.2f} vs {x['lump_median']:.2f}; bad 5% {x['staged_p5']:.2f} vs {x['lump_p5']:.2f}")
        fr = mc.frontier(R, 5000, Rd=Rd)
        t = mc.point(R, tm, Rd)
        marks = {"your target": t, "current": mc.point(R, cur, Rd),
                 "best return per risk": fr.loc[fr["sharpe"].idxmax()].to_dict(),
                 "best within a 35% fall": fr[fr["worst_fall_any_day"] >= -0.35].sort_values("ret").iloc[-1].to_dict()}
        print(f"Frontier page: {mc.html(fr, marks, R, store.pm_dir() / 'reports' / 'frontier.html')}")
        return 0
    if a.pm_cmd == "networth":
        from pflab.calc import networth
        print(networth.render(networth.build(store.connect(read_only=True), a.asof)))
        return 0
    if a.pm_cmd == "trace":
        from pflab.pm import trace
        print(trace.render(trace.build(store.connect(read_only=True), a.asof)))
        return 0
    if a.pm_cmd == "fd":
        import os
        from pflab.pm import fd as fdm
        con = store.connect()
        if a.action == "load":
            path = a.file or str(store.pm_dir() / "fd_holdings.toml")
            fds = fdm.from_toml(path)
            print(f"{fdm.save(con, fds, path)} deposits loaded; each maturity amount reproduces the bank's")
            return 0
        if a.action == "cert":
            from pflab.ingest import sbi_interest_cert as cert
            fy, rows = cert.parse(a.file, os.environ.get(a.password_env))
            n = fdm.save_interest(con, fy, cert.fd_rows(rows), a.file)
            print(f"FY{fy - 1}-{str(fy)[2:]}: {n} deposit rows (interest and TDS as certified)")
            return 0
        fds = fdm.load(con)
        print(fdm.render(fds, a.asof, a.fy or (a.asof.year + (1 if a.asof.month >= 4 else 0)), fdm.interest_facts(con)))
        return 0
    if a.pm_cmd == "tax":
        from pflab.tax import report as taxreport
        print(taxreport.render(taxreport.build(store.connect(), a.fy, other_income=a.other_income,
                                               old_regime_deductions=a.deductions,
                                               advance_tax_paid=a.advance_tax, age=a.age)))
        return 0
    if a.pm_cmd == "risk":
        from pflab.risk import report
        from pflab.data import data_dir
        print(report.render(report.build(store.connect(), a.asof, capm_root=data_dir())))
        return 0
    if a.pm_cmd == "taxplan":
        from pflab.tax import plan as tp
        print("\n".join(tp.render(tp.overview(store.connect(), a.asof))))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
