"""S67 local: what the system can say about his accounts, from the FILES he drops (email is gone, 2026-10-30) and the STATEMENT PERIODS the ledger
build recorded (audit: transactions alone prove nothing). Accounts are found from what the files show, masked; a hole between statements, a late
start and a stale end are named; the picture is complete only when every account is set up or left out, its statements run whole to a recent
date, nothing is open, and he has confirmed the inventory. Synthetic."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from pflab.agents import questions
from pflab.app import readiness
from pflab.ingest import coverage as cv
from pflab.pm import store

NOW = datetime(2026, 10, 30, 18, 0)


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


def _account(con, aid, kind, provider, ref):
    con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES (?,?,?,?)", [aid, kind, provider, ref])


def _period(con, aid, kind, first, last):
    con.execute("INSERT INTO statement_periods (account_id, kind, file_sha, first_date, last_date, n_rows, built_at) VALUES (?,?,'sha',?,?,10,?)",
                [aid, kind, first, last, NOW])


def test_accounts_are_found_from_the_files_and_shown_masked(con):
    k = cv.note_account(con, {"kind": "bank", "bank": "SBI", "last4": "9001", "dp_ids": None}, "a file you dropped", NOW, "a")
    cv.note_account(con, {"kind": "bank", "bank": "SBI", "last4": "9001", "dp_ids": None}, "a file you dropped", NOW, "b")      # the same account again
    assert cv.note_account(con, {"kind": "other"}, "x", NOW) is None
    rows = cv.matrix(con, NOW)
    assert len(rows) == 1 and rows[0]["account"] == "SBI bank account ending 9001" and rows[0]["files_seen"] == 2 and rows[0]["key"] == k
    assert "12345678" not in str(rows)


def test_statement_periods_show_holes_a_late_start_and_a_stale_end():
    ok = cv.statement_cover([(date(2026, 1, 1), date(2026, 3, 31)), (date(2026, 4, 1), date(2026, 10, 15))], date(2026, 1, 1), date(2026, 10, 30))
    assert ok["holes"] == [] and not ok["stale"] and not ok["late_start"] and ok["from"] == date(2026, 1, 1) and ok["to"] == date(2026, 10, 15)
    hole = cv.statement_cover([(date(2026, 1, 1), date(2026, 3, 31)), (date(2026, 6, 1), date(2026, 10, 15))], date(2026, 1, 1), date(2026, 10, 30))
    assert hole["holes"] == ["2026-04-01 to 2026-05-31"]                                         # April and May: no statement covers them
    old = cv.statement_cover([(date(2026, 1, 1), date(2026, 8, 31))], date(2026, 1, 1), date(2026, 10, 30))
    assert old["stale"]
    late = cv.statement_cover([(date(2026, 6, 1), date(2026, 10, 20))], date(2026, 1, 1), date(2026, 10, 30))
    assert late["late_start"]
    assert cv.statement_cover([], date(2026, 1, 1), date(2026, 10, 30))["from"] is None


def test_an_account_is_verified_by_its_statements_not_by_activity(con):
    _account(con, "SBI_9001", "bank", "SBI", "00009001")
    rows = {r["account"]: r for r in cv.matrix(con, NOW)}
    assert not rows["SBI (SBI_9001)"]["verified"] and "no statement of it" in rows["SBI (SBI_9001)"]["next"]
    _period(con, "SBI_9001", "bank", date(2026, 4, 1), date(2026, 6, 30))
    _period(con, "SBI_9001", "bank", date(2026, 8, 1), date(2026, 10, 25))
    r = {r["account"]: r for r in cv.matrix(con, NOW)}["SBI (SBI_9001)"]
    assert not r["verified"] and r["statement_holes"] == ["2026-07-01 to 2026-07-31"] and "no statement covers 2026-07-01 to 2026-07-31" in r["next"]
    _period(con, "SBI_9001", "bank", date(2026, 7, 1), date(2026, 7, 31))                         # the July statement arrives
    r = {r["account"]: r for r in cv.matrix(con, NOW)}["SBI (SBI_9001)"]
    assert r["verified"] and r["covered_from"] == "2026-04-01" and r["covered_to"] == "2026-10-25" and r["next"] is None


def test_complete_needs_set_up_or_left_out_whole_statements_nothing_open_and_his_confirmation(con):
    _account(con, "SBI_9001", "bank", "SBI", "00009001")
    _period(con, "SBI_9001", "bank", date(2026, 4, 1), date(2026, 10, 25))
    cv.note_account(con, {"kind": "bank", "bank": "SBI", "last4": "9001", "dp_ids": None}, "a file you dropped", NOW, "a")   # the same account
    k2 = cv.note_account(con, {"kind": "bank", "bank": "Old Bank", "last4": "9999", "dp_ids": None}, "a file you dropped", NOW, "b")
    s = cv.status(con, NOW)
    assert s["label"] == "partial" and any("not set up" in r for r in s["reasons"]) and any("not confirmed" in r for r in s["reasons"])
    cv.leave_out(con, k2)                                                                         # inactive: he will add it later
    readiness.open_gap(con, "coverage:locked:abc", "coverage", "a locked file", NOW)
    cv.confirm_inventory(con, NOW)
    assert cv.status(con, NOW)["label"] == "partial" and cv.status(con, NOW)["open_gaps"] == 1
    readiness.close_gap(con, "coverage:locked:abc", NOW)
    s = cv.status(con, NOW)
    assert s["label"] == "complete" and s["left_out"] == ["Old Bank bank account ending 9999"]
    cv.note_account(con, {"kind": "bank", "bank": "Third Bank", "last4": "1234", "dp_ids": None}, "a file you dropped", NOW, "c")
    assert cv.status(con, NOW)["label"] == "partial" and any("confirm again" in r for r in cv.status(con, NOW)["reasons"])


def test_the_inventory_is_one_grouped_question_asked_once(con):
    assert cv.ask_inventory(con, NOW) is None                                                    # nothing found yet: nothing to ask
    cv.note_account(con, {"kind": "bank", "bank": "SBI", "last4": "9001", "dp_ids": None}, "a file you dropped", NOW, "a")
    cv.note_account(con, {"kind": "cas", "bank": None, "last4": None, "dp_ids": "IN300999"}, "a file you dropped", NOW, "b")
    q = cv.ask_inventory(con, NOW)
    t = [t for _, _, t in questions.open_questions(con)][0]
    assert q and "SBI bank account ending 9001" in t and "0999" in t and "NOT in this list" in t and "left out" in t and "email" not in t.lower()
    assert cv.ask_inventory(con, NOW) is None                                                    # never twice
