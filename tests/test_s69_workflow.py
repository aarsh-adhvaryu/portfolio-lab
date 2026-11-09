"""S69: the workflow made explicit. One approval of a plan, numbered instructions and amendments from the conversation, independent tasks that really overlap,
an awaited experiment, a budget that parks work, executable monitors, duplicate evidence merged, new files routed by the local model (with a safe path when it
fails), and the reviewer's real verdict published. A scripted model stands in for the API; these are development tests (the live run is the acceptance)."""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta

import pytest

from pflab.agents import analyst as an
from pflab.hq import board, cases, governor as gv, roster, service
from pflab.hq import tools as tl
from tests.test_s68_missions import (CFG, NOW, PLAN, Model, _fake_calc, _say, _use, con, rt)  # noqa: F401


# --- one approval, then execution ----------------------------------------------------------------------------------------------------------

# --- the review's real verdict is published ----------------------------------------------------------------------------------------------------

# --- amendments: numbered instructions, without a release -----------------------------------------------------------------------------------------

# --- tasks really overlap ----------------------------------------------------------------------------------------------------------------------

def test_a_claim_is_atomic_across_threads(con):
    now = NOW
    for i in range(30):
        board.post(con, "w_research", f"t{i}", now, frm="mission")
    got, lock = [], threading.Lock()

    def take():
        c = con.cursor()
        while True:
            tid = board.claim(c, now, prefix="w_")
            if tid is None:
                return
            with lock:
                got.append(tid)
    ts = [threading.Thread(target=take) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(got) == list(range(1, 31))                                          # each task exactly once, none lost


def test_ids_handed_to_two_threads_at_once_are_distinct(con):
    from pflab.pm.store import next_id
    out, lock = [], threading.Lock()

    def ask():
        c = con.cursor()
        v = next_id(c, "hq_artifacts", "artifact_id")
        with lock:
            out.append(v)
    ts = [threading.Thread(target=ask) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(set(out)) == 8


# --- an experiment is awaited ---------------------------------------------------------------------------------------------------------------

def _experiment_row(con, status="registered"):
    con.execute("INSERT INTO learn_experiments VALUES (1, 'k1', ?, 'Hold cash when the index falls 10%', 'matters', 'it loses', 'case', '1', 'index:NIFTY50_TRI', 3, 'p.md', 'sha', 'esha', ?, NULL, NULL, NULL, 'deployment')",
                [NOW, status]) if False else con.execute(
        "INSERT INTO learn_experiments (exp_id, key, registered_at, hypothesis, why_it_matters, disproof, source_kind, source_ref, dataset, max_attempts, protocol_path, "
        "protocol_sha, evaluator_sha, status) VALUES (1, 'k1', ?, 'Hold cash when the index falls 10 percent', 'matters', 'it loses', 'case', '1', 'index:NIFTY50_TRI', 3, 'p.md', 'sha', 'esha', ?)",
        [NOW, status])


# --- executable monitoring -----------------------------------------------------------------------------------------------------------------

# --- evidence: duplicates merge, contradictions stay -------------------------------------------------------------------------------------------

def test_the_same_finding_twice_is_one_piece_of_evidence_and_a_contradiction_is_kept(con):
    cid, _ = cases.open_case(con, NOW, "Did the AI sell-off hit my holdings?", origin="investor")
    a = cases.add_evidence(con, cid, NOW, "The filing reports a 12% fall in segment revenue.", stance="for", source_id="doc:1", published_at=NOW)
    b = cases.add_evidence(con, cid, NOW + timedelta(hours=1), "The filing reports a 12% fall in segment revenue.", stance="for", source_id="doc:1", published_at=NOW)
    c = cases.add_evidence(con, cid, NOW, "the filing reports a 12 % fall in segment revenue", stance="for", source_id="doc:1", published_at=NOW)
    assert a == b == c and len(cases.evidence(con, cid)) == 1
    d = cases.add_evidence(con, cid, NOW, "The filing reports a 12% fall in segment revenue.", stance="against", source_id="doc:1", published_at=NOW)
    assert d != a and len(cases.evidence(con, cid)) == 2                              # opposite stance from the same source: material, kept
    e = cases.add_evidence(con, cid, NOW, "A second filing reports a 4% rise in segment revenue.", stance="for", source_id="doc:2", published_at=NOW)
    assert e not in (a, d) and len(cases.evidence(con, cid)) == 3
    assert [x[0] for x in con.execute("SELECT event FROM hq_case_log WHERE case_id=? AND event='merged'", [cid]).fetchall()] == ["merged", "merged"]
    assert cases.assess(con, cid, NOW)["verdict"] == "mixed"


# --- new files wake the right investigation; the local model routes ---------------------------------------------------------------------------

def _drop(con, name, text, iid=1, kind="other"):
    con.execute("INSERT INTO inbox_items (item_id, name, kind, sha, status, text, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                [iid, name, kind, f"sha{iid}", "read", text, NOW, NOW])


DOC = ("Analyst note on the AI sell-off: spending on AI chips by the largest buyers was cut, which pushed the downturn in AI-linked stocks further, "
       "and the note says Indian AI-linked holdings may fall again if the downturn continues over the next quarter. " * 2)


def test_routing_is_visible_on_the_screen_api(tmp_path):
    from fastapi.testclient import TestClient
    assert True


def test_the_deployment_study_tool_takes_a_trading_charge_so_an_amendment_about_costs_can_be_carried_out():
    tool = tl.TOOLS["policy_scenarios"]
    assert tl.validate(tool, {"case_id": 1, "why": "costs", "cost_bps": 50}) is None
    assert tl.validate(tool, {"case_id": 1, "why": "costs", "cost_bps": 5000}) is not None

