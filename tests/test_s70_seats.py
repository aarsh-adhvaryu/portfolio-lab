"""S70: which model holds which seat, after the measured comparison (docs/protocols/s70_roles_protocol.md): Sonnet reviews and plans; Opus writes the final answer.
(S80 phase 4: the rule "Opus reviews work that ends in a proposal of real money" went with the proposals.)"""
from __future__ import annotations

import pytest

from pflab.agents import analyst as an
from pflab.hq import governor as gv, workers

CFG = {"model": an.MODEL, "cap": 1000.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True}


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(an, "config", lambda: CFG)


def test_the_defaults_after_the_measurement():
    assert workers.SPECS["review"][1] == gv.SONNET and workers.SPECS["coordinator"][1] == gv.OPUS
    assert workers.SPECS["research"][1] == gv.SONNET and workers.SPECS["quant"][1] == gv.SONNET


def test_the_coordinator_plans_with_sonnet_and_writes_the_answer_with_opus():
    assert workers.seat_model(None, "coordinator", {"step": "plan"}, 1) == gv.SONNET
    assert workers.seat_model(None, "coordinator", {"step": "final"}, 1) == gv.OPUS
    assert workers.seat_model(None, "coordinator", {}, 1) == gv.OPUS                      # an unmarked coordinator task keeps the dearer, safer seat


def test_the_reviewer_and_the_other_workers_keep_their_models():
    for role in ("review", "research", "quant"):
        assert workers.seat_model(None, role, {}, 1) == gv.SONNET
