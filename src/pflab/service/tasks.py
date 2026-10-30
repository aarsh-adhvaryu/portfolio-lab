"""The scheduled jobs (PLAN S9). Each is idempotent and sizes its own look-back from its last success,
so a laptop that slept for days catches up in one run per job. Importing this module registers them."""
from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta
from typing import Optional, Tuple

from pflab.service import backup as bk
from pflab.service import telegram as tgm
from pflab.service.jobs import Ctx, Job, register
from pflab.service.schedule import Daily, Interval


MIN_FREE_GB = 3.0


def _collect(ctx: Ctx) -> dict:
    """NSE bhavcopy, corporate actions and dividends via tools/collect_daily.py (its own lock and log)."""
    import json
    import os
    import re
    import shutil
    free_gb = shutil.disk_usage(ctx.data_root).free / 1e9
    if free_gb < MIN_FREE_GB:                          # S58 drill 4: never fill the drive the ledger lives on
        raise RuntimeError(f"only {free_gb:.1f} GB free: nothing downloaded (needs {MIN_FREE_GB} GB)")
    days = ctx.lookback_days("collect")
    cmd = [ctx.python, str(ctx.repo / "tools" / "collect_daily.py"), "--days", str(days),
           "--sources", "bhavcopy,corporate_actions,dividends,bse_bhavcopy,surveillance,indices,vix,gkg,"
                        "insider,deals,fpi,macro,holders"]
    # S58 drill 1: the news step opened the ledger, which this process holds; it gets the names it needs instead
    from pflab.kg import build as kb
    from pflab.plan import guards as gd
    al = ctx.data_root / "_daily" / "gkg_aliases.json"
    al.parent.mkdir(parents=True, exist_ok=True)
    al.write_text(json.dumps(kb.aliases(kb.universe(ctx.con, gd.stock_list()))), encoding="utf-8")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ctx.repo), env={**os.environ, "PFLAB_GKG_ALIASES": str(al)})
    if r.returncode == 2:
        return {"skipped": True, "why": "another collector run holds the lock"}
    failed = re.findall(r"^\s+(\w+)\s+FAIL (.*)$", r.stdout, re.M)
    if r.returncode != 0 or failed:                   # S58: a failed step is a failed run (retried, shown), never hidden
        what = "; ".join(f"{n}: {e[:160]}" for n, e in failed) or (r.stdout + r.stderr)[-400:]
        raise RuntimeError(f"collect_daily: {what}")
    return {"days": days}


def _prices(ctx: Ctx) -> dict:
    from pflab.pm import prices
    days = ctx.lookback_days("prices")
    out = prices.refresh(ctx.con, days, root=ctx.data_root, network=False)
    return {k: str(v) for k, v in out.items()}


def _nav(ctx: Ctx) -> dict:
    from pflab.pm import prices
    return {k: str(v) for k, v in prices.refresh_nav_gold(ctx.con, ctx.data_root).items()}


def _holdings(ctx: Ctx) -> list:
    from pflab.ledger import events as ev
    from pflab.ledger.book import Ledger
    led = Ledger.replay(ev.load(ctx.con), upto=ctx.now.date())
    return sorted({isin for (_a, isin) in led.positions() if isin.startswith("IN")})


def _filings(ctx: Ctx) -> dict:
    """Collect BSE announcements for the last days, classify those of held and watched names, queue alerts."""
    from pflab.data import bse_announcements, bse_scrip_isin
    from pflab.monitor import filings
    from pflab.plan import guards as gd
    # S44: the stock list (PFLAB_PM_DIR/stock_list.toml) is the watchlist now; configs/watchlist.toml still counts
    names = filings.targets(_holdings(ctx), filings.load_watchlist() + [s["isin"] for s in gd.stock_list()])
    if not filings.alerts_enabled(names):
        return {"skipped": True, "waiting": True, "why": "no holdings and no watchlist yet: alerts start when there is a company to watch"}
    days = ctx.lookback_days("filings", minimum=2, cap=10)
    end = ctx.now.date()
    bse_announcements.collect(end - timedelta(days=days), end, ctx.data_root)
    ann = filings.recent(days + 1, root=ctx.data_root, today=end)
    ev = filings.classify_announcements(ann, names, bse_scrip_isin.load(ctx.data_root))
    queued = 0

    def queue(alert):
        nonlocal queued
        if tgm.enqueue(ctx.con, alert.text(), "filing", dedup_key=alert.event_id, now=ctx.now):
            queued += 1

    filings.dispatch(ctx.con, ev, names, queue, channel="outbox", now=ctx.now)
    return {"names": len(names), "filings": int(len(ev)), "alerts_queued": queued}


def _outbox(ctx: Ctx) -> dict:
    send = tgm.make_sender(ctx.secrets)
    return tgm.flush(ctx.con, send, ctx.now)


def _backup_enabled(ctx: Ctx) -> Tuple[bool, str]:
    return (bk.target_dir() is not None, "no backup target set (The investor sets PFLAB_BACKUP_DIR or configs/service.toml [backup] target)")


def _backup(ctx: Ctx) -> dict:
    return bk.backup(ctx.con, ctx.pm_dir / "ledger.duckdb", bk.target_dir(), ctx.now, bk.keep_count())


register(Job("collect", Daily(19, 30), _collect, "NSE bhavcopy, corporate actions, dividends", cooldown_minutes=60))
register(Job("prices", Daily(20, 15), _prices, "load collected bhavcopy into the PM store"))
register(Job("nav", Daily(22, 45), _nav, "AMFI NAVs and IBJA gold rates"))
# S58b: every 15 minutes (results and material filings land during market hours; a material one starts research)
register(Job("filings", Interval(15, 8, 22), _filings, "BSE filings for held and watched names; queue alerts"))
def _guards(ctx: Ctx) -> dict:
    from pflab.pm import fd as fdm
    from pflab.plan import guards as gd
    asof = ctx.now.date()
    g = gd.check_all(ctx.con, asof, gd.stock_list())
    dip = gd.market_dip(asof, ctx.data_root)
    cl = gd.market_cluster(asof, ctx.data_root)
    n = gd.queue_alerts(ctx.con, asof, g, dip, fdm.warnings(fdm.load(ctx.con), asof), now=ctx.now, cluster=cl)
    return {"names": len(g), "not_ok": sum(x.verdict != "ok" for x in g), "dip_active": dip["active"],
            "market_state": cl["state"] if cl else None, "alerts_queued": n}


def _kg(ctx: Ctx) -> dict:
    from datetime import timedelta as _td
    from pflab.kg import build as kb
    from pflab.kg import text as kt
    from pflab.plan import guards as gd
    asof = ctx.now.date()
    out = kb.refresh(ctx.con, asof, gd.stock_list(), asof - _td(days=30), asof - _td(days=3),
                     guards_list=gd.check_all(ctx.con, asof, gd.stock_list()), root=ctx.data_root, now=ctx.now)
    out["text"] = kt.fetch_texts(ctx.con, ctx.data_root / "kg" / "text", limit=100)
    from pflab.kg import clean
    out["clean"] = clean.run(ctx.con, ctx.now)                          # S57: names, copies, notes; logged
    _cleanup_log(ctx, out["clean"])
    return {k: str(v) for k, v in out.items()}


def _cleanup_log(ctx: Ctx, rep: dict) -> None:
    """The dashboard's cleanup log (Inbox and files): one line a night, the newest 60 kept."""
    import json
    p = ctx.pm_dir / "app" / "cache" / "cleanup_log.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        log = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    except ValueError:
        log = []
    p.write_text(json.dumps(([{"what": "knowledge graph", **rep}] + log)[:60], default=str), encoding="utf-8")


def _kite(ctx: Ctx):
    from pflab.ingest import kite as km
    return km.client(ctx.secrets) if ctx.secrets is not None and ctx.secrets.has("kite", "api_key") else None


def _tradecheck_enabled(ctx: Ctx) -> Tuple[bool, str]:
    return (_kite(ctx) is not None, "no Kite login today (run tools/kite_login.py)")


def _tradecheck(ctx: Ctx) -> dict:
    """S43 trade-check agent: Kite trades and holdings against the ledger; new questions go to Telegram."""
    from pflab.agents import tradecheck as tc
    try:
        tc.zerodha_account(ctx.con)
    except LookupError:                                    # a new profile has no accounts until the statements are read: waiting, not broken
        return {"skipped": True, "waiting": True, "why": "no Zerodha account is set up yet: drop your statements in Inbox and files, then press Use these accounts in Setup"}
    rep = tc.check(ctx.con, _kite(ctx), ctx.now.date(), now=ctx.now)
    if rep.asked or not rep.breaks.empty:
        tgm.enqueue(ctx.con, rep.render(), "tradecheck", dedup_key=f"tradecheck:{ctx.now.date()}:{sorted(rep.asked)}",
                    now=ctx.now)
    if rep.snapshot is None:                               # the snapshot is the point of the run: its failure is a failure
        raise RuntimeError("; ".join(rep.notes) or "no Kite snapshot")
    return {"staged": rep.staged, "resolved": rep.resolved, "pending": len(rep.pending), "breaks": int(len(rep.breaks)),
            "asked": len(rep.asked), "snapshot": rep.snapshot}


def _research(ctx: Ctx) -> dict:
    """S44 researcher: flags since the last success, briefs for flagged or stale companies, one digest."""
    from pflab.agents import brief as br
    from pflab.agents import researcher as rs
    from pflab.plan import guards as gd
    asof = ctx.now.date()
    lst = gd.stock_list()
    gs = {x.symbol: {"verdict": x.verdict, "reasons": x.reasons} for x in gd.check_all(ctx.con, asof, lst)
          if getattr(x, "symbol", None)}
    since = asof - timedelta(days=ctx.lookback_days("research", minimum=1, cap=14))
    from pflab.llm import tuning
    rep = rs.run(ctx.con, asof, lst, since, br.chosen_llm(), gs, now=ctx.now, tagger=tuning.materiality_tagger(),
                 root=ctx.data_root)
    if rep.new_flags:
        tgm.enqueue(ctx.con, rep.digest(), "research", dedup_key=f"research:{asof}", now=ctx.now)
    _ask_for_tijori(ctx, lst)
    deep = {}
    from pflab.agents import analyst as an
    # The investor 2026-10-22: Opus writes the research for what changed. Every run looks at the last 2 days' flags, not only its
    # own (S58 re-run: flags raised by a run before the fresh-note rule never reached Opus)
    if an.config()["adopted"]:
        deep = rs.deep_queue(ctx.con, asof, lst, client=an.make_client(ctx.secrets), now=ctx.now)   # overnight batch
    return {"companies": rep.companies, "new_flags": len(rep.new_flags), "briefs": len(rep.briefs),
            "opus_queued": sum(1 for v in deep.values() if v == "queued")}


def _ask_for_tijori(ctx: Ctx, stocks: list) -> int:
    """S64: the moment a company's detail is missing (fewer than 8 quarters, or no results), ask for its Tijori sheet
    (agents/needs.py; once a company a month). Replaces the S56 ask that waited for a fall."""
    from pflab.agents import needs
    n = 0
    for s in stocks:
        if str(s.get("isin", "")).startswith("INE"):
            n += needs.check_company(ctx.con, ctx.data_root, s["isin"], ctx.now, s.get("symbol")) is not None
    return n


def _analyst_enabled(ctx: Ctx) -> Tuple[bool, str]:
    from pflab.agents import analyst as an
    return (an.config()["adopted"], "the API analyst is not adopted (comparison pending)")


def _analyst_batch(ctx: Ctx) -> dict:
    """Overnight: collect finished batches, then submit what was queued during the day (half price)."""
    from pflab.agents import analyst as an
    client = an.make_client(ctx.secrets)
    got = an.collect_batches(ctx.con, client, now=ctx.now)
    return {**got, "submitted": an.submit_batch(ctx.con, client, ctx.now)}


def _forecast(ctx: Ctx) -> dict:
    """S64 forecasts (quant/forecast.py): price ranges for held and listed stocks by calibrated statistics, the baselines
    for turnover and results, everything due scored. No model runs."""
    from pflab.conductor import calendar as mcal
    from pflab.kg import build as kb
    from pflab.plan import guards as gd
    from pflab.quant import forecast as fl
    r = fl.run(ctx.con, ctx.data_root, ctx.now.date(), kb.universe(ctx.con, gd.stock_list()), mcal.load(), now=ctx.now)
    return {k: r[k] for k in ("asof", "turnover", "revenue", "margin", "stored", "scored", "serving")}


def _plans(ctx: Ctx) -> dict:
    """S55: the ready plans for the next money, kept current (zones from the dashboard's watch list when it has run)."""
    import json

    from pflab.plan import ready
    w = ctx.pm_dir / "app" / "cache" / "watch.json"
    zones = {r["isin"]: r["zone"] for r in json.loads(w.read_text(encoding="utf-8")).get("rows", [])} if w.exists() else {}
    plans = ready.refresh(ctx.con, ctx.now.date(), ctx.data_root, ctx.now, zones, fall_fn=ready.sleeve_fall(ctx.data_root))
    return {"plans": len(plans), "keys": [p["key"] for p in plans]}


register(Job("plans", Daily(21, 30), _plans, "ready plans for the next money (FD tranches, the monthly amount)"))
register(Job("forecast", Daily(21, 0), _forecast, "forecasts: price ranges, turnover for tickets, results before the result; scored when due"))
register(Job("kg", Daily(23, 0), _kg, "knowledge graph: portfolio, filings, results, guards, GKG news, article text"))
register(Job("analyst", Daily(1, 0, weekdays_only=False), _analyst_batch,
             "API analyst: collect last night's batch, submit today's queue", enabled_fn=_analyst_enabled))
register(Job("research", Daily(23, 30), _research, "researcher: material changes, briefs kept current, digest"))
# S58b: every 15 minutes while logged in (and right after the login): each run is the portfolio's snapshot
register(Job("tradecheck", Interval(15, start_hour=8, end_hour=22, weekdays_only=False), _tradecheck,
             "Kite holdings, funds, today's trades and cash: the portfolio today; differences from the ledger asked",
             enabled_fn=_tradecheck_enabled))
register(Job("guards", Daily(20, 45), _guards, "surveillance + safety checks on the stock list; dip and FD alerts"))
register(Job("outbox", Interval(15), _outbox, "deliver queued Telegram messages", cooldown_minutes=5))
register(Job("backup", Daily(23, 30, weekdays_only=False), _backup, "copy and verify the ledger", enabled_fn=_backup_enabled))


def _global(ctx: Ctx) -> dict:
    """World indices, US VIX, commodities, the dollar (Yahoo, `data.global_markets`): by morning IST the US and Europe
    have closed, so a Sunday-evening switch-on sees Friday's close before Monday's open."""
    from pflab.data import global_markets as gm
    out = gm.collect(ctx.data_root)
    bad = {k: v for k, v in out.items() if isinstance(v, str)}
    if len(bad) == len(out):
        raise RuntimeError(f"no series downloaded: {next(iter(bad.values()), '')}")
    return {"series": len(out) - len(bad), "not_updated": sorted(bad)}


register(Job("global", Daily(7, 30, weekdays_only=False), _global, "world markets, US VIX, commodities, dollar (Yahoo)",
             cooldown_minutes=60))


def _conductor(ctx: Ctx) -> dict:
    """S53: mode, sync check, asks to the investor, wake and closing notes, the fact sheet. Registered last: it runs after the
    other jobs of the tick and sees what they did."""
    from pflab.conductor import run as cr
    return cr.conduct(ctx)


def _hq(ctx: Ctx) -> dict:
    """S59 the agent HQ with the window closed: Telegram once, the board, the drop folder, reminders, readers, the
    brain (shadow), the memory keeper (the dashboard runs the same on its own thread)."""
    from pflab.hq import service
    return service.tick_job(ctx)


def _learner(ctx: Ctx) -> dict:
    """S62 the learner: free sources read for testable claims, registered and tested; the record read when due."""
    from pflab.learner import run
    return run.job(ctx)


def _security(ctx: Ctx) -> dict:
    """S62 the security agent: egress re-check, data flows, the repo's privacy grep, the tests; Sunday's code review."""
    from pflab.hq import security
    return security.job(ctx)


def _comove(ctx: Ctx) -> dict:
    """S64 how stocks and sectors move together: rebuilt weekly (the table is skipped while under 6 days old)."""
    from pflab.quant import comove
    return comove.job(ctx)


register(Job("comove", Daily(10, 0, weekdays_only=False), _comove,
             "comove: correlation and cointegration of his names with their peers and of the sectors; weekly",
             cooldown_minutes=120))


def _summary(which: str):
    def run(ctx: Ctx) -> dict:
        """S64: the morning or evening summary, on trading days; the held messages since the last one ride along."""
        from pflab.conductor import calendar as mcal
        from pflab.service import summary
        cal = mcal.load()
        if not cal.is_trading_day(ctx.now.date()):
            return {"skipped": True, "why": cal.why_closed(ctx.now.date())}
        return summary.send(ctx.con, ctx.now.date(), ctx.now, which, cal, ctx.data_root)
    return run


register(Job("summary_morning", Daily(9, 0), _summary("morning"), "Telegram morning summary (trading days)"))
register(Job("summary_evening", Daily(21, 45), _summary("evening"), "Telegram evening summary (trading days)"))
def _watches(ctx: Ctx) -> dict:
    """S64: the price watches against the latest price while the market is open and once at the close (the dashboard checks
    them too every 10 minutes while it runs). A hit is urgent; a watch made by a suggestion carries its ready ticket."""
    from pflab.app import research
    hits = research.check_watches_con(ctx.con, ctx.now, ctx.data_root)
    return {"hits": len(hits)}


IDLE_CASH_MIN, IDLE_CASH_DAYS = 10_000.0, 7


def idle_cash_days(con, now: datetime) -> Optional[Tuple[float, int]]:
    """(the smallest Kite cash over the last 7 days, days covered) when Rs 10,000 or more sat unused for 7 days or more."""
    rows = con.execute("SELECT taken_at, amount FROM kite_snapshots WHERE kind='cash' AND taken_at >= ? ORDER BY taken_at",
                       [now - timedelta(days=IDLE_CASH_DAYS + 1)]).fetchall()
    if not rows or rows[0][0] > now - timedelta(days=IDLE_CASH_DAYS):
        return None                                           # no snapshots reaching back a full week
    low = min(a for _t, a in rows if a is not None)
    return (low, IDLE_CASH_DAYS) if low >= IDLE_CASH_MIN else None


def _idle_cash(ctx: Ctx) -> dict:
    """S64: Kite cash of Rs 10,000 or more unused for a week -> a line in the evening summary (not urgent)."""
    got = idle_cash_days(ctx.con, ctx.now)
    if not got:
        return {"idle": False}
    week = ctx.now.isocalendar()
    tgm.enqueue(ctx.con, f"Idle cash: at least Rs {got[0]:,.0f} has sat unused in your Kite account for {got[1]} days. "
                         "Ready plans and suggestions are on the dashboard; nothing is placed for you.", "idle_cash",
                dedup_key=f"idle_cash:{week[0]}-W{week[1]}", now=ctx.now)
    return {"idle": True, "cash": got[0]}


register(Job("watches", Interval(15, 9, 16, weekdays_only=True), _watches, "price watches against the latest price (market hours)",
             cooldown_minutes=10))
register(Job("watches_close", Daily(16, 0), _watches, "price watches once after the close", cooldown_minutes=30))
register(Job("idle_cash", Daily(20, 30), _idle_cash, "Kite cash unused for a week -> a line in the evening summary"))
def _us_fx(ctx: Ctx) -> dict:
    """S64 Phase 6: the dollar's price in rupees (FRED) into the store, for US lots and the sleeve's value."""
    from pflab.ledger import foreign as lf
    return {"new_rates": lf.load_fx(ctx.con, ctx.data_root)}


register(Job("us_fx", Daily(7, 25, weekdays_only=False), _us_fx, "US sleeve: USDINR rates into the store"))


def _mail(ctx: Ctx) -> dict:
    """S65: read-only Gmail: new statement attachments into the inbox (ingest/gmail.py); asks once to be connected.
    S66: then what the money emails SAY, read by the local model and checked against his record (ingest/mail_read.py)."""
    from pflab import guard
    from pflab.hq import desk, models
    from pflab.ingest import gmail, mail_read
    if guard.blocked("mail"):
        return {"skipped": "the workshop does not read his mail"}
    if not gmail.connected():
        gmail.ask_to_connect(ctx.con, ctx.now)
        return {"skipped": "Gmail not connected (asked once in Needs from you)", "waiting": True, "why": "Gmail is not connected: statements and money emails wait for Connect Gmail in Settings"}
    rt, sess = desk.from_ctx(ctx), gmail.session()
    out = gmail.fetch(rt, sess)
    try:
        out["read"] = mail_read.run(rt, sess, models.model_id("mail_reading"))
    except Exception as e:                                   # the local model off, say: the emails are read at the next try
        out["read"] = f"not read: {type(e).__name__}: {str(e)[:160]}"
        out["failed"] = {"mail_reading": out["read"]}        # S67: the attachments came; the reading did not: the run is a failed one
    if out.get("errors") and out["errors"] >= out.get("messages", 0):                 # every message tried failed: the run did not read mail
        out.setdefault("failed", {})["fetch"] = f"{out['errors']} message(s) could not be fetched or stored"
    return out


register(Job("mail", Daily(21, 15, weekdays_only=False), _mail, "read-only Gmail, once a day: statements that arrived by email into the "
             "inbox (checked, then your press); what money emails say, read on this PC and checked against your record",
             cooldown_minutes=180))


def _backfill(ctx: Ctx) -> dict:
    """S67: market history fills itself, in steps of about 90 seconds (newest sessions first), so a first run needs no long command and
    an interruption costs nothing. The readiness stages and the known gaps are brought up to date with it."""
    from pflab.app import readiness
    from pflab.hq import desk
    out = readiness.backfill_step(ctx.data_root, ctx.now)
    sync = readiness.sync_gaps(desk.from_ctx(ctx), ctx.now)
    res = {**{k: v for k, v in out.items() if k != "last_error"}, "gaps_open": sync["open"], "ready": sync["ready"]}
    if out.get("errors") and not out.get("fetched"):
        res["failed"] = {"bhavcopy": out.get("last_error") or f"{out['errors']} session(s) could not be fetched"}
    return res


def _backfill_enabled(ctx: Ctx) -> Tuple[bool, str]:
    """Enabled only while sessions are missing and the disk has room. Never raises: a data folder that does not exist yet has all of it missing."""
    import shutil
    from pathlib import Path
    from pflab.app import readiness
    probe = Path(ctx.data_root)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        if shutil.disk_usage(probe).free / 1e9 < MIN_FREE_GB:
            return False, f"under {MIN_FREE_GB} GB free"
    except OSError:
        return False, "the data folder's disk cannot be read"
    h = readiness.bhavcopy_holes(ctx.data_root, readiness.HISTORY_START, ctx.now.date() - timedelta(days=1))
    return (bool(h["holes"]), "market history has no holes")


register(Job("backfill", Interval(60, weekdays_only=False), _backfill, "market history fills itself in 90-second steps until no session is missing; "
             "readiness and known gaps updated", cooldown_minutes=30, enabled_fn=_backfill_enabled))


def _sandbox_enabled(ctx: Ctx) -> Tuple[bool, str]:
    import shutil
    return (shutil.which("docker") is not None, "Docker is not installed")


def _sandbox_probe(ctx: Ctx) -> dict:
    """S67: containment proven by use, weekly: a container with the sandbox's flags tries the network, writes to the root and the job
    folder, looks for host paths and secrets, and a loop past its limit must be killed. The result is the sandbox's colour on the screen."""
    from pflab.agents import sandbox as sb
    from pflab.app import system
    r = sb.probe()
    system.record_check(ctx.con, "sandbox", r["ok"], ctx.now, r["why"] if not r["ok"] else "all checks passed: " + ", ".join(sorted(r["checks"])))
    if not r["ok"]:
        raise RuntimeError(f"sandbox containment not proven: {r['why']}")
    return {"checks": len(r["checks"])}


register(Job("sandbox", Daily(6, 40, weekdays_only=False), _sandbox_probe, "proves the calculation sandbox is contained (no network, read-only, killed at its limit)",
             cooldown_minutes=30, enabled_fn=_sandbox_enabled))                  # a failed proof is looked at again in half an hour (Docker may just be starting)


def _twin(ctx: Ctx) -> dict:
    """S65: the scoreboard (plan/twin.py): REAL, SYSTEM (the brain's suggestions on paper), equal-weight Nifty 500 and Nifty 500, same money."""
    from pflab.plan import twin
    return twin.run(ctx.con, ctx.data_root, ctx.now)


register(Job("twin", Daily(20, 55), _twin, "the scoreboard: your book, the brain's suggestions on paper, equal-weight Nifty 500, Nifty 500 (same money, same days)"))


def _companion(ctx: Ctx) -> dict:
    """S64: theme baskets, theme limits, the dip reserve and the pot proposed once and applied after his yes; applied
    limits held to; open pot ideas scored."""
    from pflab.hq import stocks
    from pflab.plan import companion
    from pflab.plan import targets as tg
    try:
        index = stocks.index_series(ctx.data_root)
    except Exception:
        index = None
    try:
        tg.load()
    except tg.TargetsNotSet:                               # his to set, never ours: waiting for him, not a failure
        return {"skipped": True, "waiting": True, "why": "your targets are not set yet: it makes no plan until you set them (it proposes, you say yes)"}
    return companion.run(ctx.con, ctx.data_root, ctx.now.date(), ctx.now, index)


register(Job("companion", Daily(21, 10, weekdays_only=False), _companion,
             "limits: theme baskets and limits, the dip reserve, the opportunity pot (proposals wait for his yes)", cooldown_minutes=120))
def _scans(ctx: Ctx) -> dict:
    """S64: the saved scans (closed set of conditions) over his holdings, his list or the Nifty 500; hits on his names go into
    the evening summary as held lines. Information only: a scan is not evidence until the learner has tested it."""
    import json as _json

    from pflab.quant import scan
    scan.seed_starters(ctx.con, ctx.now)
    out = scan.run_all(ctx.con, ctx.data_root, ctx.now.date(), ctx.now)
    cache = out.pop("_cache")
    p = ctx.pm_dir / "app" / "cache" / "scans.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps({"at": str(ctx.now)[:16], "scans": cache}, default=str), encoding="utf-8")
    return {k: v for k, v in out.items()}


register(Job("scans", Daily(20, 40), _scans, "scanners: saved scans over his names (information, labelled not tested)",
             cooldown_minutes=120))
register(Job("learner", Daily(22, 0, weekdays_only=False), _learner,
             "learner: papers and blogs -> registered tests; proposals from the system's own record", cooldown_minutes=120))
register(Job("security", Daily(21, 15, weekdays_only=False), _security,
             "security: what left the PC, data flows, privacy grep, tests; weekly code review", cooldown_minutes=120))
register(Job("hq", Interval(15, weekdays_only=False), _hq,
             "agent HQ: orders, drop folder, reminders, readers, the brain (shadow), memory keeper", cooldown_minutes=10))
register(Job("conductor", Interval(15, weekdays_only=False), _conductor,
             "conductor: sync check, asks, wake and closing notes, fact sheet", cooldown_minutes=10))
