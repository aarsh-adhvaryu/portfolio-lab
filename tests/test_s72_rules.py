"""S72: house rules. What he tells the system to do from now on is kept in his words, versioned, read by every agent, enforced where code can, and undoable; a rule about money
waits for his yes. Synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from pflab.app import assistant
from pflab.hq import egress, proposals, rules, tools as tl
from tests.test_s68_autonomy import AAA, NOW, con, rt  # noqa: F401  (fixtures)


@pytest.fixture
def sectors(con):
    con.execute("UPDATE instruments SET sector = 'IT - Software' WHERE isin = ?", [AAA])
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at)
                   VALUES ('INE000B01012', 'isin', 'equity', 'listed_equity', TRUE, 'BBB', 'BBB Limited', 'Capital Goods', 'synthetic', now())""")


def _ctx(rt, said):
    return tl.Ctx(rt, 1, "local", False, {}, egress.Gate(), NOW, mode="normal", source=said, role="assistant", allowed=frozenset(assistant.TOOLS), his_text=said)


# --- making, superseding, undoing -----------------------------------------------------------------------------------------------

def test_a_rule_that_touches_no_money_is_active_at_once_and_supersedes_its_earlier_version(con, sectors):
    a = rules.propose(con, NOW, "sector_exclusion", "No new tech until I say", {"terms": ["software", "it"]}, name="no_new_tech")
    assert a["made"] and a["status"] == "active" and not a["needs_yes"] and a["covers"] == ["IT - Software"]
    b = rules.propose(con, NOW, "sector_exclusion", "No new tech or capital goods until I say", {"terms": ["software", "capital goods"]}, name="no_new_tech")
    assert b["version"] == 2 and b["replaces"] == a["rule_id"]
    assert [r["rule_id"] for r in rules.active(con)] == [b["rule_id"]]                         # one active version of a name
    assert con.execute("SELECT status FROM hq_rules WHERE rule_id=?", [a["rule_id"]]).fetchone()[0] == "superseded"
    assert rules.propose(con, NOW, "sector_exclusion", "No new tech or capital goods until I say", {"terms": ["software", "capital goods"]}, name="no_new_tech")["duplicate"]


def test_undo_restores_the_version_it_replaced(con, sectors):
    a = rules.propose(con, NOW, "method", "Always include a 0.5% charge in cost tests", name="costs")
    b = rules.propose(con, NOW, "method", "Always include a 0.3% charge in cost tests", name="costs")
    out = rules.undo(con, NOW, "costs")
    assert out["undone"] and out["restored"] == a["rule_id"]
    assert [r["text"] for r in rules.active(con)] == ["Always include a 0.5% charge in cost tests"]
    assert rules.undo(con, NOW, b["rule_id"])["undone"] is False                               # already undone
    assert rules.undo(con, NOW, "costs")["restored"] is None and rules.active(con) == []


def test_a_rule_about_money_waits_for_his_yes_and_a_no_discards_it(con):
    a = rules.propose(con, NOW, "monthly_envelope", "I invest Rs 50,000 a month till January, unspent carries over", {"amount_rupees": 50000, "until": "2027-01-31", "carry_over": True})
    assert a["made"] and a["status"] == "pending" and a["needs_yes"] and rules.active(con) == [] and len(rules.pending(con)) == 1
    assert rules.decide(con, NOW, a["rule_id"], True)["status"] == "active" and len(rules.active(con)) == 1 and rules.pending(con) == []
    b = rules.propose(con, NOW, "max_position", "No holding above 8% of the portfolio", {"max_weight_pct": 8})
    assert rules.decide(con, NOW, b["rule_id"], False)["status"] == "declined" and len(rules.active(con)) == 1
    assert rules.decide(con, NOW, b["rule_id"], True)["decided"] is False                       # nothing waits any more


def test_bad_rules_are_refused_with_the_reason(con):
    assert "at least one sector" in rules.propose(con, NOW, "sector_exclusion", "No new tech please", {})["why"]
    assert "1 to 50" in rules.propose(con, NOW, "max_position", "A ceiling on any holding", {"max_weight_pct": 90})["why"]
    assert "1,000" in rules.propose(con, NOW, "monthly_envelope", "I invest a little each month", {"amount_rupees": 5})["why"]
    assert "kind is one of" in rules.propose(con, NOW, "magic", "Do something clever", {})["why"]
    assert "sentence" in rules.propose(con, NOW, "note", "hi")["why"]


def test_the_version_changes_with_every_change_and_the_text_is_what_agents_read(con):
    v0 = rules.version(con)
    a = rules.propose(con, NOW, "method", "Never use the forum posts as a source", name="no_forums")
    v1 = rules.version(con)
    rules.undo(con, NOW, "no_forums")
    assert v0 < v1 < rules.version(con)
    assert rules.active_text(con) == ""
    rules.propose(con, NOW, "note", "I prefer index funds for the long money", name="index_pref")
    t = rules.active_text(con)
    assert t.startswith("HOUSE RULES (version") and "[index_pref] I prefer index funds for the long money" in t


def test_the_readable_copy_is_written(con, tmp_path):
    rules.propose(con, NOW, "note", "I prefer index funds for the long money", name="index_pref")
    rules.propose(con, NOW, "max_position", "No holding above 8% of the portfolio", {"max_weight_pct": 8})
    text = rules.render(con, tmp_path).read_text(encoding="utf-8")
    assert "index_pref" in text and "Waiting for your yes" in text and "No holding above 8%" in text


# --- enforcement ----------------------------------------------------------------------------------------------------------------

def test_a_sector_exclusion_stops_new_buying_there_and_nothing_else(con, sectors):
    rules.propose(con, NOW, "sector_exclusion", "No new tech until I say", {"terms": ["software"]}, name="no_new_tech")
    assert "no_new_tech" in rules.violation(con, "BUY", AAA) and "no_new_tech" in rules.violation(con, "add", AAA)
    for action in ("SELL", "REDUCE", "HOLD", "WAIT", "DIVERSIFY"):
        assert rules.violation(con, action, AAA) is None
    assert rules.violation(con, "BUY", "INE000B01012") is None                                   # another sector
    assert rules.violation(con, "BUY", "INE-UNKNOWN") is None                                    # unknown instrument: no guess
    rules.undo(con, NOW, "no_new_tech")
    assert rules.violation(con, "BUY", AAA) is None


def test_whole_words_only_so_it_does_not_catch_a_word_inside_another(con, sectors):
    rules.propose(con, NOW, "sector_exclusion", "No new IT", {"terms": ["it"]}, name="no_it")
    assert rules.violation(con, "BUY", "INE000B01012") is None                                   # 'Capital Goods' contains no whole word 'it'


def _fake_build(monkeypatch, isin, action="BUY", weight_after=0.12, notional=80000.0):
    monkeypatch.setattr(proposals, "build", lambda con_, now, inputs: {"payload": {"action": action, "reason": "x", "portfolio_effect": {"weight_after": weight_after},
                                                                                "size": {"notional": notional}}, "missing": [], "isin": isin, "symbol": "AAA"})


def test_a_proposal_in_an_excluded_sector_is_refused_with_the_rule_named(rt, con, sectors, monkeypatch):
    _fake_build(monkeypatch, AAA)
    rules.propose(con, NOW, "sector_exclusion", "No new tech until I say", {"terms": ["software"]}, name="no_new_tech")
    out = proposals.create(con, NOW, {})
    assert out["stored"] is False and "no_new_tech" in out["problem"] and "WAIT or HOLD" in out["problem"]
    _fake_build(monkeypatch, AAA, action="WAIT")
    assert proposals.create(con, NOW, {}).get("stored") is True                                  # a WAIT in the same sector is still possible


def test_a_ceiling_and_the_envelope_are_noted_on_a_buy(rt, con, sectors, monkeypatch):
    _fake_build(monkeypatch, "INE000B01012", weight_after=0.12, notional=80000.0)
    a = rules.propose(con, NOW, "max_position", "No holding above 8% of the portfolio", {"max_weight_pct": 8})
    b = rules.propose(con, NOW, "monthly_envelope", "I invest Rs 50,000 a month", {"amount_rupees": 50000})
    assert proposals.create(con, NOW, {}).get("missing") == []                                   # both wait for his yes: neither binds yet
    rules.decide(con, NOW, a["rule_id"], True)
    rules.decide(con, NOW, b["rule_id"], True)
    _fake_build(monkeypatch, "INE000B01012", weight_after=0.12, notional=80000.0)
    out = proposals.create(con, NOW, {"y": 2})
    missing = " | ".join(out["missing"])
    assert "above the 8% ceiling" in missing and "above the Rs 50,000 available now" in missing


# --- the tools ------------------------------------------------------------------------------------------------------------------

def test_the_assistant_makes_a_rule_only_from_his_own_message_and_undoes_it_only_when_asked(rt, con, sectors):
    said = "No new tech until I say"
    out, err = tl.run(_ctx(rt, said), "add_rule", {"kind": "sector_exclusion", "text": said, "machine_json": json.dumps({"terms": ["software"]}), "name": "no_new_tech"}, 1)
    res = json.loads(out)
    assert not err and res["made"] and res["status"] == "active" and "IT - Software" in res["note"] and rules.violation(con, "BUY", AAA)
    none, _ = tl.run(_ctx(rt, ""), "add_rule", {"kind": "note", "text": "Something the model made up on its own"}, 1)
    assert json.loads(none)["made"] is False
    no_undo, _ = tl.run(_ctx(rt, "ok thanks"), "undo_rule", {"rule": "no_new_tech"}, 1)
    assert json.loads(no_undo)["undone"] is False and rules.violation(con, "BUY", AAA)
    undone, _ = tl.run(_ctx(rt, "undo the tech rule please"), "undo_rule", {"rule": "no_new_tech"}, 1)
    assert json.loads(undone)["undone"] is True and rules.violation(con, "BUY", AAA) is None


def test_a_money_rule_needs_his_yes_in_his_own_words(rt, con):
    said = "I invest Rs 50,000 a month until January and unspent carries over"
    res = json.loads(tl.run(_ctx(rt, said), "add_rule", {"kind": "monthly_envelope", "text": said, "machine_json": json.dumps({"amount_rupees": 50000, "until": "2027-01-31"})}, 1)[0])
    assert res["status"] == "pending" and "waits for his yes" in res["note"]
    unclear = json.loads(tl.run(_ctx(rt, "hmm let me think"), "decide_rule", {"rule_id": res["rule_id"], "decision": "approve"}, 1)[0])
    assert unclear["decided"] is False and rules.active(con) == []
    yes = json.loads(tl.run(_ctx(rt, "yes, go ahead"), "decide_rule", {"rule_id": res["rule_id"], "decision": "approve"}, 1)[0])
    assert yes["decided"] is True and len(rules.active(con)) == 1


def test_the_rules_reach_the_agents(rt, con):
    rules.propose(con, NOW, "method", "Always include a 0.5% charge in cost tests", name="costs")
    from pflab.hq import missions, workers
    out = missions.create(con, NOW, "Compare phased buying with holding cash", pm_dir=rt.pm_dir)
    assert "[costs] Always include a 0.5% charge in cost tests" in workers._dossier(con, out["case_id"], {"body": {}, "id": 1}, NOW, "quant")
    assert "recall" in assistant.TOOLS and "add_rule" in assistant.TOOLS and "recall" in workers.TOOLS["research"] and "add_rule" not in workers.TOOLS["quant"]
