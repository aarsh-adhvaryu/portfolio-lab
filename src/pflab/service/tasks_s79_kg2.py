"""S81 B7 jobs for the rebuilt knowledge graph (`pflab/kg2`), both code only and free:

`kg2_nightly`    classify new events with the local model (bounded), build the graph from the raw files, audit it, and load the store ONLY when the audit passes and the switch
                 (`configs/kg2.toml` [kg] on) is on; otherwise nothing from the graph is readable. Due when filings or collectors have brought new input (service/ondemand.py) or once a day.
`news_s81_topup` the daily top-up of the news collection (the last three days, article text inside the cap), run as the collector tool in its own process so the app's loops are not
                 held; skipped while another collection is running. Bounded to 30 minutes.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab.kg2 import switch
    return (True, "") if switch.on() else (False, "the graph is OFF (configs/kg2.toml [kg] on = false)")


def _enabled_out_of_session(ctx):
    """The scheduler thread is shared with the 5-minute session loop (stops, entries): a job that takes minutes waits for the session to end (S81)."""
    ok, why = _enabled(ctx)
    if not ok:
        return ok, why
    from pflab.paper import book
    if book.session_open(ctx.now):
        return False, "the market is in session: a long job waits for the close so the session loop is not held"
    return True, ""


def _missing_inputs(root) -> str:
    """The graph's raw inputs are files the collectors bring (the instrument names behind the index membership). A data folder without them is waiting for them, not broken (drill, S81)."""
    p = Path(root) / "index_membership" / "name_map.parquet"
    return "" if p.exists() else f"the graph's raw inputs are not there yet ({p.name} under {p.parent.name}): waiting for the collectors"


def _nightly(ctx) -> dict:
    from pflab import markets
    from pflab.kg2 import job
    why = _missing_inputs(ctx.data_root)
    if why:
        return {"skipped": why, "waiting": True}
    day = markets.get("IN").session_closed_by(ctx.now)
    return job.run(ctx.con, ctx.data_root, day, classify_limit=40, now=ctx.now)


def _topup(ctx) -> dict:
    root = Path(ctx.data_root)
    why = _missing_inputs(root)
    if why:
        return {"skipped": why, "waiting": True}
    tool = Path(__file__).resolve().parents[3] / "tools" / "news_s81_run.py"
    pid_file = root / "news_s81" / "run.pid"
    if pid_file.exists():
        try:
            os.kill(int(pid_file.read_text().strip()), 0)
            return {"skipped": "a news collection is already running"}
        except (ValueError, OSError):
            pass
    if not tool.exists():
        return {"skipped": "tools/news_s81_run.py is not in this install"}
    until = (ctx.now + timedelta(minutes=30)).strftime("%H:%M")
    log = root / "news_s81" / "topup.out"
    log.parent.mkdir(parents=True, exist_ok=True)
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) if os.name == "nt" else 0
    with open(log, "ab") as fh:                                  # started detached and not waited for: the scheduler thread is shared with the session loop (S81)
        p = subprocess.Popen([sys.executable, str(tool), "--root", str(root), "--days", "3", "--until", until], stdout=fh, stderr=fh, stdin=subprocess.DEVNULL, creationflags=flags)
    return {"started": True, "pid": p.pid, "until": until, "log": str(log)}


register(Job("kg2_nightly", Interval(360, weekdays_only=False), _nightly, "the rebuilt knowledge graph: classify, build, audit, load only when the audit passes (S81; code, local model)",
             cooldown_minutes=120, enabled_fn=_enabled_out_of_session))
register(Job("news_s81_topup", Interval(720, weekdays_only=False), _topup, "the daily news top-up (last 3 days, article text inside the cap) as its own process (S81)", cooldown_minutes=180,
             enabled_fn=_enabled))
