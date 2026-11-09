"""S68 P5: with no chat message, a new material filing on a held name and a due review each start or resume an investigation that leaves artifacts; the
reason it was chosen and what would justify revisiting are kept; an unchanged signal is not adopted twice; a day's starts are bounded; Pause stops it.
A scripted model stands in for the API (development test); synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from pflab.agents import analyst as an
from pflab.app import assistant, chat
from pflab.hq import board, cases, egress, governor as gv, roster, service
from pflab.hq.desk import Desk
from pflab.pm import store
from tests.test_s68_missions import Model, PLAN, _fake_calc, _happy_scripts, _say, _use

NOW = datetime(2026, 10, 31, 15, 0)
AAA = "INE000A01011"
CFG = {"model": an.MODEL, "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True, "tijori_to_analyst": True}
REPRO = {"reproduced": True, "basis": "original", "label": "x", "same_as_kept": True, "differences": [], "problems": [], "result": {}, "kept": {}}


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                 VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'AAA Limited', 'synthetic', now())""", [AAA])
    return c


@pytest.fixture
def rt(con, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: CFG)
    monkeypatch.setattr(service, "gate", lambda r: egress.Gate())
    monkeypatch.setattr(service, "names", lambda r: ([AAA], []))
    monkeypatch.setattr(cases, "reproduce", lambda *a, **k: REPRO)
    (tmp_path / "pm" / "app").mkdir(parents=True)
    return Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {"brain": "normal", "preset": "full", "telegram_send": False}, clock=lambda: NOW)


def _insert_reading(con, doc="D1", isin=AAA):
    cols = [r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='hq_readings' ORDER BY ordinal_position").fetchall()]
    vals = {"doc_id": doc, "read_at": NOW - timedelta(hours=1), "material": "yes", "isins_json": json.dumps([isin]), "summary": "AAA reported a large order loss",
            "kind": "result", "model": "m", "cost_inr": 0.0, "status": "done", "facts_json": "[]", "published_at": NOW - timedelta(hours=2)}
    use = [c for c in cols if c in vals]
    con.execute(f"INSERT INTO hq_readings ({','.join(use)}) VALUES ({','.join('?' * len(use))})", [vals[c] for c in use])


def test_pause_stops_the_system_choosing_work(rt, con):
    rt.settings["scheduler"] = False
    _insert_reading(con)
    out = service.round_(rt)
    assert out.get("paused") is True and con.execute("SELECT count(*) FROM hq_missions").fetchone()[0] == 0

