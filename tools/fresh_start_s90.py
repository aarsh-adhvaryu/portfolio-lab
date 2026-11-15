"""S90 (his decision, 15 Nov 2026): a FRESH start for the first real week. Run with the app CLOSED (one process holds the store).

    .venv\\Scripts\\python tools\\fresh_start_s90.py --pm <pm folder>                      what would be cleared (changes nothing)
    .venv\\Scripts\\python tools\\fresh_start_s90.py --pm <pm folder> --apply --his-go     do it (needs today's Kite login)

1. backs the store up (a file copy beside it, checked by opening it);
2. re-seeds Claude's book from his Kite holdings ONLY (`paper/reseed.py`, the fake Rs 5,00,000 cash), then DELETES the old book (his words: "no archive, delete"):
   the archive tables, exits, session records, picks, the thinking loop's cases and scores, desk sessions, the twin;
3. clears what is stale: chats and cards, open questions, problems, alarms and their gaps, the intake queue, unsent Telegram messages, the week check (it re-arms
   at the first open on or after Monday 16 Nov), presence and catch-up notes, plans.
Kept: market data (prices, filings, news, quotes), the knowledge graph and storylines, forecasts, the promoted policy, his settings, rules, targets and watchlist.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

BOOK = ("exit_plans_s81", "exit_events_s81", "exit_scores_s81", "probation_s81", "session_adv_s81", "session_exit_fb_s81", "session_fills_s81", "session_log_s81", "session_plans_s81",
        "session_queue_s81", "session_said_s81", "session_triggers_s81", "picks_s83", "pick_scores_s83", "pick_sleeve_daily_s83", "sleeve_share_s83", "skips_s83",
        "think_cases_s84", "think_decisions_s84", "think_scores_s84", "think_calibration_s84", "think_steps_s84", "think_options_s84", "think_signals_s84", "think_misses_s84",
        "think_overrides_s84", "think_freezes_s84", "think_watch_runs_s84", "think_shadow_s85", "think_case_origin_s85", "think_wide_runs_s85", "think_calibration_engine_s85",
        "desk_sessions_s84", "desk_steps_s84", "twin_days", "twin_trades", "decisions", "attribution_s79", "verify_book_s79")
STALE = ("chat_messages", "chats", "cards_s85", "chat_prefs_s85", "chat_summary", "chat_attachments_s85", "intake_queue_s85", "questions", "problems_s86", "alarm_s86", "alarm_gap_s86",
         "ghost_s86", "page_loads_s86", "week_check_s79", "mode_seen_s79", "catchup_s79", "away_digest_s79", "app_presence_s79", "plans_s89", "plan_steps_s89", "operator_builds_s87",
         "from_you_notes_s85", "rules_requests_s85", "inbox_items")


def tables(con) -> set:
    return {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE'").fetchall()}


def plan(con) -> dict:
    t = tables(con)
    arch = sorted(x for x in t if x.endswith("_archive_s79"))
    count = lambda n: con.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0]
    return {"delete_rows": {n: count(n) for n in BOOK + STALE if n in t}, "drop_archives": {n: count(n) for n in arch},
            "unsent_telegram": con.execute("SELECT count(*) FROM outbox WHERE sent_at IS NULL").fetchone()[0] if "outbox" in t else 0}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pm", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--his-go", action="store_true")
    a = ap.parse_args(argv)
    os.environ["PFLAB_PM_DIR"] = str(a.pm)
    from pflab.pm import store
    db = Path(a.pm) / "ledger.duckdb"
    con = store.connect(db)
    p = plan(con)
    print("rows to delete:", ", ".join(f"{k}={v}" for k, v in p["delete_rows"].items() if v) or "none")
    print("old-book archives to empty:", ", ".join(f"{k}={v}" for k, v in p["drop_archives"].items()) or "none", "| unsent Telegram messages:", p["unsent_telegram"])
    if not a.apply:
        print("(preview: nothing changed; add --apply --his-go)")
        return 0
    if not a.his_go:
        raise SystemExit("--apply needs --his-go")
    from reseed_s79 import _holdings_from
    holdings = _holdings_from(argparse.Namespace(holdings=None, from_kite=True))      # read-only Kite; refuses without today's login
    con.close()
    bk = db.with_name(f"ledger_before_fresh_{datetime.now():%Y%m%d_%H%M%S}.duckdb")
    shutil.copy2(db, bk)
    store.connect(bk).close()                                                             # the copy opens
    print("backed up to", bk.name)
    con = store.connect(db)
    from pflab.paper import reseed
    out = reseed.reseed(con, holdings, datetime.now(), pm_dir=Path(a.pm), force=True)
    if not out.get("done"):
        print("re-seed did not run:", {k: v for k, v in out.items() if k != "before"})
        return 1
    t = tables(con)
    con.execute("BEGIN")
    for n in BOOK + STALE:
        if n in t:
            con.execute(f'DELETE FROM "{n}"')
    if "outbox" in t:
        con.execute("DELETE FROM outbox WHERE sent_at IS NULL")
    for n in sorted(x for x in t if x.endswith("_archive_s79")):
        con.execute(f'DELETE FROM "{n}"')                                              # emptied, not dropped: code may still name the table
    con.execute("COMMIT")
    con.execute("CHECKPOINT")
    print(f"fresh: Claude's book re-seeded from {len(holdings)} Kite holdings (seed day {out.get('seed_day')}); old book and stale items deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
