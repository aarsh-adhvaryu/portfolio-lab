"""The scheduled jobs (PLAN S9). Each is idempotent and sizes its own look-back from its last success,
so a laptop that slept for days catches up in one run per job. Importing this module registers them."""
from __future__ import annotations

import subprocess
from datetime import date, timedelta
from typing import Tuple

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
        return {"skipped": True, "why": "no holdings and no watchlist: alerts are off"}
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
    _ask_for_tijori(ctx, [f for f in rep.new_flags if f.kind == "fall"])
    deep = {}
    from pflab.agents import analyst as an
    # The investor 2026-10-22: Opus writes the research for what changed. Every run looks at the last 2 days' flags, not only its
    # own (S58 re-run: flags raised by a run before the fresh-note rule never reached Opus)
    if an.config()["adopted"]:
        deep = rs.deep_queue(ctx.con, asof, lst, client=an.make_client(ctx.secrets), now=ctx.now)   # overnight batch
    return {"companies": rep.companies, "new_flags": len(rep.new_flags), "briefs": len(rep.briefs),
            "opus_queued": sum(1 for v in deep.values() if v == "queued")}


def _ask_for_tijori(ctx: Ctx, falls: list) -> int:
    """S56: a stock falling on its own -> ask the investor for its Tijori export before Opus writes the night's note (The investor
    2026-10-20). Only once he has Tijori (an export has reached the inbox before), once per company a month."""
    from pflab.agents import questions as qs
    inbox = ctx.pm_dir / "inbox"
    if not inbox.exists() or not any("tijori" in p.name.lower() for p in inbox.rglob("*") if p.is_file()):
        return 0
    n = 0
    for f in falls:
        n += qs.ask(ctx.con, "researcher", f"tijori:{f.isin}:{ctx.now:%Y-%m}",
                    f"{f.symbol or f.isin} is falling on its own ({f.detail}). If you can, drop its Tijori export in Inbox "
                    "and files tonight: it stays on this PC, and the researcher reads it beside the filings.", ctx.now) is not None
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
    """S52 live forecasts (quant/tfm2_live.py): TimesFM in .venv-train on the CPU, the baselines, scoring, the
    scoreboard; a switch to or from the baseline goes to the outbox. TimesFM failing leaves the baseline serving."""
    from pflab.conductor import calendar as mcal
    from pflab.kg import build as kb
    from pflab.plan import guards as gd
    from pflab.quant import tfm2_live as fl
    r = fl.run(ctx.con, ctx.data_root, ctx.now.date(), kb.universe(ctx.con, gd.stock_list()), mcal.load(),
               fl.timesfm_subprocess(ctx.repo, ctx.data_root / "forecasts" / "live"), now=ctx.now)
    for m in r["changes"]:
        tgm.enqueue(ctx.con, m, "forecast", dedup_key=f"forecast:{r['asof']}:{m[:40]}", now=ctx.now)
    from pflab.agents import questions as qs                 # S63: a refresh due is asked once a month per reason
    for key, why in fl.refresh_due(ctx.con, ctx.data_root, ctx.now.date()):
        qs.ask(ctx.con, "forecaster", f"tfm:refresh:{key}:{ctx.now:%Y-%m}", why + " Answer 'seen' when noted.", ctx.now)
    if r["error"]:
        raise RuntimeError(f"TimesFM did not run (the baseline serves): {r['error']}")
    return {k: r[k] for k in ("asof", "turnover", "revenue", "margin", "stored", "scored")}


def _plans(ctx: Ctx) -> dict:
    """S55: the ready plans for the next money, kept current (zones from the dashboard's watch list when it has run)."""
    import json

    from pflab.plan import ready
    w = ctx.pm_dir / "app" / "cache" / "watch.json"
    zones = {r["isin"]: r["zone"] for r in json.loads(w.read_text(encoding="utf-8")).get("rows", [])} if w.exists() else {}
    plans = ready.refresh(ctx.con, ctx.now.date(), ctx.data_root, ctx.now, zones, fall_fn=ready.sleeve_fall(ctx.data_root))
    return {"plans": len(plans), "keys": [p["key"] for p in plans]}


register(Job("plans", Daily(21, 30), _plans, "ready plans for the next money (FD tranches, the monthly amount)"))
register(Job("forecast", Daily(21, 0), _forecast, "S52 forecasts: turnover for tickets, results ranges; scoreboard"))
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


register(Job("learner", Daily(22, 0, weekdays_only=False), _learner,
             "learner: papers and blogs -> registered tests; proposals from the system's own record", cooldown_minutes=120))
register(Job("security", Daily(21, 15, weekdays_only=False), _security,
             "security: what left the PC, data flows, privacy grep, tests; weekly code review", cooldown_minutes=120))
register(Job("hq", Interval(15, weekdays_only=False), _hq,
             "agent HQ: orders, drop folder, reminders, readers, the brain (shadow), memory keeper", cooldown_minutes=10))
register(Job("conductor", Interval(15, weekdays_only=False), _conductor,
             "conductor: sync check, asks, wake and closing notes, fact sheet", cooldown_minutes=10))
