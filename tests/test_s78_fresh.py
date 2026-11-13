"""S78: a fresh start clears the system's mind and keeps its account; the backup folder is a setting; no console window flashes from child processes. Synthetic data only."""
from __future__ import annotations

import os
import subprocess
from datetime import date, datetime

import pytest

from pflab import winquiet
from pflab.app import settings as st
from pflab.pm import fresh_start, store
from pflab.service import backup as bk

NOW = datetime(2026, 11, 2, 18, 0)


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "f.duckdb")
    c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES ('INE000A01011', 'isin', 'equity', 'EQUITY', TRUE, 'AAA', 'AAA Ltd', 's', now())")
    c.execute("INSERT INTO paper_cash VALUES (1, ?, 500000, 'seed', 'fake starting cash', now())", [date(2026, 10, 30)])
    c.execute("INSERT INTO paper_days VALUES (?, 950045, 500000, 0, 0, '{}')", [date(2026, 10, 30)])
    return c


def _n(con, t):
    return con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]


def test_a_fresh_start_clears_the_mind_and_keeps_the_account_the_money_record_and_the_learner(con):
    con.execute("INSERT INTO chats (chat_id, title, created_at, updated_at) VALUES (1, 'Assistant', now(), now())")
    con.execute("INSERT INTO kg_nodes VALUES ('c:AAA', 'company', 'AAA', NULL, now())")
    con.execute("INSERT INTO paper_decisions (decision_id, made_at, case_id, action, isin, symbol, amount, reason, alternatives, status) VALUES (1, now(), 7, 'WAIT', NULL, NULL, NULL, 'keep cash for now', 'x', 'executed')")
    con.execute("INSERT INTO questions VALUES (1, now(), 'planner', 'k', 'How much will you add each month?', 'open', NULL, NULL)")
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, cost_inr) VALUES (1, now(), 'live', 'm', 'q', 's', '{}', 'done', 12.0)")
    before = fresh_start.plan(con)
    assert before["chat"] >= 1 and before["knowledge graph"] == 1 and before["the paper team's decisions"] == 1 and before["questions, notes and memory"] == 1
    out = fresh_start.apply(con, date(2026, 11, 2), NOW)
    assert out["paper_started"] == "2026-11-02"                                   # the paper clock starts again today
    assert _n(con, "chats") == 0 and _n(con, "kg_nodes") == 0 and _n(con, "paper_decisions") == 0 and _n(con, "questions") == 0
    assert _n(con, "paper_cash") == 1 and _n(con, "instruments") == 1             # the account's own rows stay
    assert _n(con, "api_calls") == 1                                              # the money record stays: the cap needs it
    assert con.execute("SELECT min(day) FROM paper_days").fetchone()[0] == date(2026, 11, 2)


def test_the_backup_folder_is_a_setting_that_the_backup_reads(tmp_path, monkeypatch):
    monkeypatch.delenv("PFLAB_BACKUP_DIR", raising=False)
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    cfg = tmp_path / "service.toml"
    cfg.write_text("[backup]\n", encoding="utf-8")
    assert bk.target_dir(cfg) is None
    out = st.save(tmp_path, {"backup_dir": "D:\\PL_backup"})
    assert out["backup_dir"] == "D:\\PL_backup"
    assert str(bk.target_dir(cfg)) == "D:\\PL_backup"


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_child_processes_get_no_console_window_unless_the_caller_asked_for_one(monkeypatch):
    seen = []
    real = subprocess.Popen.__init__

    def spy(self, *a, **kw):
        seen.append(kw.get("creationflags", 0))
        raise RuntimeError("stop")
    monkeypatch.setattr(subprocess.Popen, "__init__", spy)
    monkeypatch.setattr(winquiet, "_done", False)
    winquiet.apply()
    for kw in ({}, {"creationflags": winquiet.DETACHED_PROCESS}):
        with pytest.raises(RuntimeError):
            subprocess.Popen(["x"], **kw)
    assert seen[0] & winquiet.CREATE_NO_WINDOW and not seen[1] & winquiet.CREATE_NO_WINDOW and seen[1] & winquiet.DETACHED_PROCESS
    monkeypatch.setattr(subprocess.Popen, "__init__", real)
