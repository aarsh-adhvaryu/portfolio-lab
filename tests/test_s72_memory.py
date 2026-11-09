"""S72: working memory. The five questions (what did we conclude and why, what goes against it, what was already checked, what changed, what is open), the graph links, and the
measure that matters: whether memory changed the next piece of work. Synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

from pflab.hq import board, cases, roster, rules
from pflab.kg import memory
from pflab.quant import trusted
from tests.test_s68_autonomy import AAA, NOW, con, rt  # noqa: F401  (fixtures)

EARLIER = NOW - timedelta(days=20)
Q1 = "Is AAA Limited exposed to a sell-off in software stocks, and should I change how I invest?"


@pytest.fixture
def world(con):
    con.execute("UPDATE instruments SET sector = 'IT - Software' WHERE isin = ?", [AAA])
    for d in range(30):
        con.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [AAA, (EARLIER - timedelta(days=2) + timedelta(days=d)).date(), 100.0 + d])
    return con


def _past_case(con, question=Q1, decision="watch", reason="exposure is modest and a fall is survivable", at=EARLIER, tool="exposure_shock", with_calc=True, key="k1"):
    """An investigation that was concluded `at` a past date, with a checked trusted calculation and one piece of evidence against."""
    cid, _ = cases.open_case(con, at, question, origin="investor", isin=AAA, key=key)
    cases.add_evidence(con, cid, at, "Brokerage note warns of seat-based revenue loss", stance="against", source_id="doc:note-1", published_at=at)
    if with_calc:
        trusted.record(con, cid, at, tool, "worst fall", {"falls_json": "[20, 35]"}, {"x": pd.DataFrame({"a": [1.0]})}, {"v": 1})
    cases.conclude(con, cid, at, decision, reason, uncertainty="one quarter only", next_review_at=at + timedelta(days=14))
    return cid


# --- subjects --------------------------------------------------------------------------------------------------------------------

def test_subjects_are_found_by_symbol_name_sector_and_theme(world):
    assert "company:" + AAA in memory.subjects_of(world, "How is AAA doing?")
    assert "company:" + AAA in memory.subjects_of(world, "what about AAA Limited's results")
    assert "sector:IT - Software" in memory.subjects_of(world, "any risk in it - software this quarter?")
    assert "theme:ai_it" in memory.subjects_of(world, "the AI bubble bursting")
    assert memory.subjects_of(world, "What is the weather like?") == []


# --- the five answers ------------------------------------------------------------------------------------------------------------

def test_recall_answers_what_was_concluded_and_why(world):
    cid = _past_case(world)
    rec = memory.recall(world, "Should I buy more AAA now?", NOW)
    c = rec["conclusions"][0]
    assert c["case_id"] == cid and c["decision"] == "watch" and "survivable" in c["reason"] and c["status"] == "current" and c["at"] == str(EARLIER)[:10]


def test_an_older_conclusion_is_marked_when_a_newer_one_covers_the_same_subject(world):
    old = _past_case(world, at=EARLIER - timedelta(days=60), key="old")
    new = _past_case(world, question="AAA again: results came in", decision="watch", reason="results were fine", at=EARLIER, key="new")
    cs = {c["case_id"]: c for c in memory.recall(world, "AAA", NOW)["conclusions"]}
    assert cs[new]["status"] == "current" and cs[old]["status"] == "older" and cs[old]["newer_case"] == new


def test_a_conclusion_about_something_else_is_not_recalled(world):
    _past_case(world)
    assert memory.recall(world, "What is a good hedge in a war?", NOW)["conclusions"] == []
    assert memory.brief(memory.recall(world, "What is a good hedge in a war?", NOW)) == ""


def test_evidence_against_and_new_documents_after_the_conclusion_are_the_contradictions(world):
    _past_case(world)
    world.execute("INSERT INTO hq_readings (doc_id, read_at, model, material, summary, isins_json) VALUES ('doc:filing-9', ?, 'm', 'yes', 'AAA cut its guidance for the year', ?)",
                  [NOW - timedelta(days=2), json.dumps([AAA])])
    rec = memory.recall(world, "AAA", NOW)
    texts = " | ".join(x["text"] for x in rec["contradictions"])
    assert "Brokerage note warns" in texts and "cut its guidance" in texts and any(x["after_conclusion"] for x in rec["contradictions"] if x["source"] == "doc:filing-9")


def test_a_checked_method_is_offered_for_re_running_not_rewriting(world):
    cid = _past_case(world)
    m = memory.recall(world, "AAA", NOW)["methods"]
    assert len(m) == 1 and m[0]["tool"] == "exposure_shock" and m[0]["case_id"] == cid and "re-run on today's record" in m[0]["how"] and "[20, 35]" in m[0]["params"]
    failed = _past_case(world, question="AAA once more, a failed attempt", key="f", with_calc=False)
    world.execute("INSERT INTO hq_calcs (calc_id, case_id, created_at, question, code, code_sha, datasets_json, params_json, result_json, status, contained, attempts, check_json) "
                  "VALUES (9001, ?, ?, 'q', 'x = 1', 's', '[]', '{}', '{}', 'failed', TRUE, 4, '{}')", [failed, EARLIER])
    assert all(x["calc_id"] != 9001 for x in memory.recall(world, "AAA", NOW)["methods"])                     # a failed calculation is never offered


def test_what_changed_since_the_conclusion(world):
    _past_case(world)
    world.execute("INSERT INTO events (event_id, kind, account_id, trade_date, isin, qty, price, amount, ingested_at) VALUES (1, 'buy', 'Z', ?, ?, 10, 120, 1200, now())", [(NOW - timedelta(days=3)).date(), AAA])
    rules.propose(world, NOW - timedelta(days=1), "note", "I prefer index funds for the long money", name="idx")
    ch = " | ".join(memory.recall(world, "AAA", NOW)["changed"])
    assert "AAA moved" in ch and "1 trade(s) in AAA" in ch and "1 house rule(s)" in ch


def test_what_is_still_open(world):
    cid = _past_case(world)
    cases.add_evidence(world, cid, EARLIER, "the company's segment revenue", stance="missing")
    world.execute("INSERT INTO hq_case_deps (dep_id, case_id, dep_key, kind, request, status, requested_at) VALUES (1, ?, 'report', 'report', 'the Q2 segment report for AAA', 'open', ?)", [cid, EARLIER])
    o = " | ".join(x["what"] for x in memory.recall(world, "AAA", NOW)["open"])
    assert "waiting for: the Q2 segment report" in o and "evidence missing: the company's segment revenue" in o and f"review of #{cid} was due" in o


def test_the_brief_is_short_and_names_its_sources(world):
    _past_case(world)
    b = memory.brief(memory.recall(world, "AAA", NOW))
    assert b.startswith("MEMORY") and "Earlier investigation #" in b and "Already checked: exposure_shock" in b and len(b) <= 2200


# --- the graph -------------------------------------------------------------------------------------------------------------------

def test_the_case_is_linked_into_the_graph_once(world):
    cid = _past_case(world)
    n = memory.record_case(world, cid, NOW)
    assert n > 0 and memory.record_case(world, cid, NOW) == 0                                          # idempotent
    edges = {(s, r, d) for s, r, d in world.execute("SELECT src, rel, dst FROM kg_edges WHERE src LIKE 'inv:%' OR src LIKE 'concl:%'").fetchall()}
    assert (f"inv:{cid}", "about", f"company:{AAA}") in edges and (f"inv:{cid}", "concluded", f"concl:{cid}") in edges
    assert any(r == "used" and d.startswith("method:") for _, r, d in edges) and any(r == "contradicts" for _, r, _d in edges)


# --- effects: did memory change the work? ---------------------------------------------------------------------------------------
