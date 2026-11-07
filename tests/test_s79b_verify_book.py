"""S79b item 18E: the system's own book applies splits, bonuses, dividends, ISIN changes, demergers and mergers (found missing, fixed in `paper/corp.py`), and a top-up is
outside money that the next review is told to deploy under the active allocation."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from pflab.paper import verify_book as vb


def test_every_corporate_action_reaches_the_systems_lots_and_cash_once(tmp_path):
    res = vb.run_synthetic(tmp_path / "syn")
    failed = [k for k, v in res["checks"].items() if not v]
    assert res["ok"], failed
    assert {"split", "bonus", "dividend", "isin_change", "cash_credit", "merger", "cash_in_lieu"} >= set(res["applied"]) and {"split", "bonus", "dividend", "isin_change", "cash_credit"} <= set(res["applied"])
    assert res["worst_one_day_move"] < 0.02


def test_the_top_up_is_outside_money_and_the_next_look_is_told_to_deploy_it(tmp_path):
    res = vb.run_topup(tmp_path / "top")
    failed = [k for k, v in res["checks"].items() if not v]
    assert res["ok"], failed
    assert res["cash_pct_after"] < res["cash_pct_before"] - 5.0


def test_without_the_hook_a_split_cuts_the_book_by_its_ratio_which_is_the_bug_that_was_found(tmp_path, monkeypatch):
    """Regression for the FOUND-AND-FIXED line: before `corp.apply_due` the book kept its quantity through a 1:5 split and was marked at the post-split close."""
    import os
    from datetime import date
    from pflab.paper import book, corp
    monkeypatch.setattr(corp, "enabled", lambda: False)
    old = os.environ.get("PFLAB_DATA_DIR")
    try:
        con, root, pm = vb.build(tmp_path / "off")
        os.environ["PFLAB_DATA_DIR"] = str(root)
        book.catch_up(con, vb.DAYS[-1], datetime(2026, 12, 31, 21, 0))
        prev = max(d for d in vb.DAYS if d < vb.EX["split"])
        drop = vb._value(con, vb.EX["split"]) / vb._value(con, prev) - 1.0
        assert drop < -0.05
        assert sum(l[1] for l in vb._lots(con, vb.SPL)) == 100.0
    finally:
        if old is None:
            os.environ.pop("PFLAB_DATA_DIR", None)
        else:
            os.environ["PFLAB_DATA_DIR"] = old


def test_the_switch_off_applies_nothing_and_a_foreign_account_is_skipped(tmp_path, monkeypatch):
    import os
    from pflab.paper import benchmark, corp
    old = os.environ.get("PFLAB_DATA_DIR")
    try:
        con, root, pm = vb.build(tmp_path / "sw")
        os.environ["PFLAB_DATA_DIR"] = str(root)
        monkeypatch.setattr(benchmark, "settings", lambda table="benchmark": {"on": False, "apply_corporate_actions": False})
        assert corp.apply_due(con, vb.DAYS[-1], vb.NOW) == {"off": True}
        monkeypatch.undo()
        from pflab.ledger import system
        monkeypatch.setattr(system, "active", lambda pm_dir=None: False)
        assert "skipped" in corp.apply_due(con, vb.DAYS[-1], vb.NOW)
    finally:
        if old is None:
            os.environ.pop("PFLAB_DATA_DIR", None)
        else:
            os.environ["PFLAB_DATA_DIR"] = old


def test_the_plan_lists_only_what_the_book_held_after_its_start_and_never_twice(tmp_path):
    import os
    from pflab.paper import corp
    old = os.environ.get("PFLAB_DATA_DIR")
    try:
        con, root, pm = vb.build(tmp_path / "plan")
        os.environ["PFLAB_DATA_DIR"] = str(root)
        p = corp.plan(con, vb.DAYS[-1], root)
        refs = sorted(e.ref for e in p["share"] + p["cash"] + p["aliases"])
        assert refs == sorted({corp.ref("split", vb.SPL, vb.EX["split"]), corp.ref("bonus", vb.BON, vb.EX["bonus"]), corp.ref("cash_credit", vb.DEM, vb.EX["demerger"]),
                               corp.ref("isin_change", vb.ALI, vb.EX["alias"])})
        assert [d[0] for d in p["dividends"]] == [vb.DIV] and any(x["isin"] == vb.LFT for x in p["left"])
        assert {x["isin"] for x in p["needs"]} >= {vb.ALI, vb.MRG, vb.DEM}                          # rows that say merger / demerger with no ratio are listed, not guessed
    finally:
        if old is None:
            os.environ.pop("PFLAB_DATA_DIR", None)
        else:
            os.environ["PFLAB_DATA_DIR"] = old


def test_a_deploy_reason_needs_an_active_target_a_new_top_up_and_cash_over_its_weight(tmp_path):
    import os
    from pflab.hq import missions
    from pflab.paper import allocation, funds
    old = os.environ.get("PFLAB_DATA_DIR")
    try:
        con, root, pm = vb.build(tmp_path / "dep")
        os.environ["PFLAB_DATA_DIR"] = str(root)
        (pm / "app").mkdir(exist_ok=True)
        now = datetime(2026, 10, 30, 21, 0)
        funds.topup(con, 10_000, "the investor", vb.DAYS[4], now)
        assert allocation.deploy_reason(con, now) is None                                         # no active target: nothing to deploy under
        t = allocation.propose_allocation(con, {"equity": 70, "gold": 10, "international": 5, "cash": 15}, "x" * 60, now)
        allocation.review_target(con, t["target_id"], "approve", "ok", now)
        assert "top-up of Rs 10,000" in allocation.deploy_reason(con, now + timedelta(minutes=1))
        missions.create(con, now + timedelta(hours=1), "Paper portfolio: review", pm_dir=pm, origin="paper")
        assert allocation.deploy_reason(con, now + timedelta(hours=2)) is None                    # the team has looked since: the reason is spent
    finally:
        if old is None:
            os.environ.pop("PFLAB_DATA_DIR", None)
        else:
            os.environ["PFLAB_DATA_DIR"] = old


def test_a_stale_feed_isin_is_restated_to_the_held_one_only_after_the_old_isin_stopped_trading(tmp_path):
    """Found on the real feed: Nestle India's bonus is listed under the ISIN that stopped trading in 2024."""
    import json
    import os
    from datetime import date
    from pflab.paper import corp
    old = os.environ.get("PFLAB_DATA_DIR")
    try:
        con, root, pm = vb.build(tmp_path / "stale")
        os.environ["PFLAB_DATA_DIR"] = str(root)
        rows = json.loads((root / "corporate_actions" / "raw" / "2026.json").read_text(encoding="utf-8"))
        rows.append(vb._row("INE333A01000", "DIVCO", date(2026, 11, 12), "Bonus 1:1", fv="10"))             # the old ISIN of DIVCO; it has no close after 2026-10-30 below
        (root / "corporate_actions" / "raw" / "2026.json").write_text(json.dumps(rows), encoding="utf-8")
        con.execute("INSERT INTO prices VALUES ('INE333A01000', ?, 800.0, 'EQ', 'nse_bhavcopy', now())", [date(2026, 10, 20)])
        p = corp.plan(con, vb.DAYS[-1], root)
        assert corp.ref("bonus", vb.DIV, date(2026, 11, 12)) in [e.ref for e in p["share"]]
        con.execute("INSERT INTO prices VALUES ('INE333A01000', ?, 800.0, 'EQ', 'nse_bhavcopy', now())", [date(2026, 11, 20)])      # still trading after the ex-date: a different security
        p = corp.plan(con, vb.DAYS[-1], root)
        assert corp.ref("bonus", vb.DIV, date(2026, 11, 12)) not in [e.ref for e in p["share"]]
    finally:
        if old is None:
            os.environ.pop("PFLAB_DATA_DIR", None)
        else:
            os.environ["PFLAB_DATA_DIR"] = old
