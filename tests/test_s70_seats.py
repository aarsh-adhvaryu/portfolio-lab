"""S70: which model holds which seat, after the measured comparison (docs/protocols/s70_roles_protocol.md): Sonnet reviews and plans; Opus writes the final answer
and reviews work that ends in a proposal of real money."""
from __future__ import annotations

import pytest

from pflab.agents import analyst as an
from pflab.hq import governor as gv, proposals, workers

CFG = {"model": an.MODEL, "cap": 1000.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True}


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(an, "config", lambda: CFG)


def _proposals(monkeypatch, *rows):
    monkeypatch.setattr(proposals, "listing", lambda con, case_id=None, limit=30, status=None: [
        {"status": st, "payload": {"size": ({"notional": n} if n is not None else None)}} for st, n in rows])


def test_the_defaults_after_the_measurement():
    assert workers.SPECS["review"][1] == gv.SONNET and workers.SPECS["coordinator"][1] == gv.OPUS
    assert workers.SPECS["research"][1] == gv.SONNET and workers.SPECS["quant"][1] == gv.SONNET


def test_the_coordinator_plans_with_sonnet_and_writes_the_answer_with_opus(monkeypatch):
    _proposals(monkeypatch)
    assert workers.seat_model(None, "coordinator", {"step": "plan"}, 1) == gv.SONNET
    assert workers.seat_model(None, "coordinator", {"step": "final"}, 1) == gv.OPUS
    assert workers.seat_model(None, "coordinator", {}, 1) == gv.OPUS                      # an unmarked coordinator task keeps the dearer, safer seat


def test_the_reviewer_is_sonnet_unless_real_money_is_proposed(monkeypatch):
    _proposals(monkeypatch)
    assert workers.seat_model(None, "review", {}, 1) == gv.SONNET                          # no proposal
    _proposals(monkeypatch, ("open", 10_000.0), ("open", None))
    assert workers.seat_model(None, "review", {}, 1) == gv.SONNET                          # small, and one the record could not size
    _proposals(monkeypatch, ("open", 10_000.0), ("open", 25_000.0))
    assert workers.seat_model(None, "review", {}, 1) == gv.OPUS                            # at the threshold: Opus
    _proposals(monkeypatch, ("withdrawn", 90_000.0), ("rejected", 90_000.0))
    assert workers.seat_model(None, "review", {}, 1) == gv.SONNET                          # a proposal he turned down or withdrew no longer counts


def test_the_threshold_is_policy(monkeypatch):
    _proposals(monkeypatch, ("open", 40_000.0))
    monkeypatch.setattr(an, "config", lambda: {**CFG, "policy": {"review_opus_above_rupees": 100_000}})
    assert workers.seat_model(None, "review", {}, 1) == gv.SONNET
    monkeypatch.setattr(an, "config", lambda: {**CFG, "policy": {"review_opus_above_rupees": 30_000}})
    assert workers.seat_model(None, "review", {}, 1) == gv.OPUS


def test_the_workers_keep_their_models(monkeypatch):
    _proposals(monkeypatch, ("open", 90_000.0))
    assert workers.seat_model(None, "research", {}, 1) == gv.SONNET and workers.seat_model(None, "quant", {}, 1) == gv.SONNET
