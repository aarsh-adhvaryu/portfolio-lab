"""S84 (kgkind, A68): the thesis-break kind `leadership_crisis` (a governance shock) in the graph's closed list, the local model's prompt and the exit manager; a securities
class action is `regulatory_action` (medium). Headlines are phrased like the real ones of the Nvidia week (6-12 Nov 2026: public company and executive roles only).
The model is a scripted fake; data is synthetic (rule 7).
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd
import pytest

from pflab.core import exits
from pflab.kg import events as kev
from pflab.kg2 import audit, build as kb, classify, job, news
from pflab.pm import store

from test_s81_exits import DAY as EXIT_DAY, WIN, con as xcon          # noqa: F401  (the fixture is used by name)
from test_s81_kg import A, GROUPS, _filing, _w, root                   # noqa: F401
from test_s82_kg import _add_file, _audit_con

import duckdb

CEO_PROBE = "Nvidia board opens investigation into CEO over relationship with former executive"
BOARD_OUST = "Nvidia board prepares to oust CEO after reports of a second relationship"
CEO_SPY = "CEO told staff of affair with former executive of a company US officials suspect of spying for China"
SPY_EXEC = "Supplier executive linked to espionage case, US officials say"
PROMOTER_ARREST = "Promoter of mid-cap lender arrested by Enforcement Directorate in money laundering case"
CEO_LEAVE = "Chief executive placed on leave as board reviews conduct"
CEO_OUT = "Chief Executive Officer resigns with immediate effect"
CEO_REMOVED = "Board removes chairman after regulator inquiry"
CLASS_ACTION = "Class action lawsuit filed against Nvidia over alleged securities fraud after CEO disclosure"
CLASS_ACTION_2 = "Shareholder class-action suit filed against Alpha Industries in New York"

ORDINARY = ["Nvidia reports record data center revenue for the quarter", "Appointment of Mr Rao as Chief Financial Officer", "Chairman to retire at the end of his term",
            "Resignation of Company Secretary and Compliance Officer", "CEO to present at investor conference in December", "Board approves interim dividend",
            "Company opens new plant; chairman inaugurates it", "Cessation of Independent Director on completion of tenure"]


# ------------------------------------------------------------------ the closed list and the rules

def test_leadership_crisis_is_a_high_thesis_break_kind_in_the_closed_lists():
    assert "leadership_crisis" in classify.THESIS_BREAK_KINDS and "leadership_crisis" in classify.KINDS and "leadership_crisis" in classify.MODEL_PICKS
    assert classify.validate({"kind": "leadership_crisis", "severity": "high"}) is None
    assert "leadership_crisis" in classify.SCHEMA["properties"]["kind"]["enum"]
    assert "leadership_crisis" in classify.SYSTEM and "class action" in classify.SYSTEM


@pytest.mark.parametrize("head", [CEO_PROBE, BOARD_OUST, CEO_SPY, SPY_EXEC, PROMOTER_ARREST, CEO_LEAVE, CEO_OUT, CEO_REMOVED])
def test_governance_shocks_are_leadership_crisis_high(head):
    assert classify.rule_kind(head) == ("leadership_crisis", "high")


@pytest.mark.parametrize("head", [CLASS_ACTION, CLASS_ACTION_2])
def test_a_securities_class_action_is_regulatory_action_medium_not_a_fraud_investigation(head):
    assert classify.rule_kind(head) == ("regulatory_action", "medium")


@pytest.mark.parametrize("head", ORDINARY)
def test_ordinary_news_is_not_a_leadership_crisis(head):
    kind, sev = classify.rule_kind(head)
    assert kind != "leadership_crisis" and kind not in classify.THESIS_BREAK_KINDS and sev == "low"


# shapes found on the real BSE filings 2010-2026 (company names synthetic): they looked like a shock to a first version of the rule and are not one
NOT_SHOCKS = [
    "Alpha Ltd has informed BSE that the Board approved the sanction of the Scheme by the Regional Director, subject to approvals",           # loan / scheme "sanction" + a director
    "Outcome of Board Meeting: Board of Directors approved the sanction letter issued by the bank for a term loan",
    "Mr X, Chief Executive Officer has tendered his resignation due to personal reasons with immediate effect",                           # a stated personal reason
    "Mr X has resigned from the position of Chairman with immediate effect. He will continue as a whole-time director",                   # stays on the board
    "Mr X, Independent Director and Chairman has resigned from the Board with immediate effect",
    "Mr X, Vice Chairman has resigned with immediate effect",
    "Intimation under Regulation 30 in case of Frauds/defaults/arrest(judicial custody) by promoter or KMP",                                # the exchange's template title
    "There have been rumors in the market that an agency is investigating the company and its promoters",                                 # a reply to a rumour
    "Mr X, promoter of the Company passed away following cardiac arrest",
    "Settlement of class action lawsuit in the United States agreed by the company",                                                      # settled / dismissed / won: not new bad news
    "Class action litigation against the subsidiary dismissed by the court in the company's favour",
    "Appointment and Removal / Cessation of Chief Executive Officer",                                                                      # a form title, not an event
    "Request for re-classification of promoter to public category and removal of his name from the promoter group",
]


@pytest.mark.parametrize("head", NOT_SHOCKS)
def test_shapes_that_fooled_a_first_version_on_real_filings_are_not_a_shock(head):
    kind, _ = classify.rule_kind(head)
    assert kind != "leadership_crisis" and not (kind == "regulatory_action" and classify.rule_kind(head)[1] == "medium")


@pytest.mark.parametrize("head", [
    "Managing Director of the Company, with two other employees, has been detained by the State CID in connection with a commercial transaction",
    "Mr X, a promoter of the Company, has been arrested by the Directorate of Enforcement on 24 March",
    "Managing Director of the Company has been remanded under police custody on 29 August",
    "Tax department conducts raids at the residence and office of the chairman of the company",
    "Removal of Shri X, MD & CEO",
    "The Board has approved removal of Mr X as CEO with immediate effect",
    "Mr X, Chief Executive Officer has resigned with immediate effect",
])
def test_real_filing_shapes_that_are_a_shock(head):
    assert classify.rule_kind(head) == ("leadership_crisis", "high")


def test_the_old_rules_still_answer_as_before():
    assert classify.rule_kind("Resignation of Statutory Auditors of the Company")[0] == "auditor_resignation"
    assert classify.rule_kind("Forensic audit appointed by the board") == ("fraud_investigation", "high")
    assert classify.rule_kind("Show cause notice received from SEBI") == ("regulatory_action", "high")
    assert classify.rule_kind("Change in Senior Management")[0] == "management_change"


def test_the_local_model_may_name_the_kind_and_only_from_the_closed_list():
    class R:
        def __init__(self, text):
            self.text = text
    calls = []

    def chat(model, msgs, **kw):
        calls.append(msgs)
        return R(json.dumps({"kind": "scandal", "severity": "high"}) if len(calls) == 1 else json.dumps({"kind": "leadership_crisis", "severity": "high"}))
    got = classify.model_classify("Board in talks about the future of its chief executive", chat=chat)
    assert got == {"kind": "leadership_crisis", "severity": "high"} and len(calls) == 2                 # an off-list answer: one retry
    assert "leadership_crisis" in json.dumps(calls[0])                                                  # the model is shown the kind and its meaning
    assert classify.final_kind(("other", "low"), got) == ("leadership_crisis", "high", "model")


# ------------------------------------------------------------------ the graph

def test_a_bse_filing_on_the_chief_executive_is_stored_as_leadership_crisis_and_the_rebuild_is_identical(root):
    _add_file(root, date(2026, 6, 12), [_filing("500001", "Board initiates investigation into conduct of Managing Director", pd.NaT, news_dt=pd.NaT),
                                         _filing("500001", "Class action filed in United States against the company", pd.NaT, news_dt=pd.NaT)])
    out = kb.build(root, date(2026, 6, 30), groups=GROUPS)
    ev = out["event"]
    r = ev[ev["headline"].str.contains("Managing Director")].iloc[0]
    assert (r["kind"], r["severity"], r["isin"]) == ("leadership_crisis", "high", A)
    assert r["ts"] == datetime(2026, 6, 15, 9, 15)                                                      # no release time: used from the next trading open (A58)
    c = ev[ev["headline"].str.contains("Class action")].iloc[0]
    assert (c["kind"], c["severity"]) == ("regulatory_action", "medium")
    assert kb.hash_tables(out) == kb.hash_tables(kb.build(root, date(2026, 6, 30), groups=GROUPS))
    res = audit.run_audit(_audit_con(), root, date(2026, 6, 30), graph=out, store=False)
    checks = {k["name"]: k for k in res["checks"]}
    assert checks["point_in_time"]["passed"], checks["point_in_time"]


def test_a_headline_keyword_in_an_article_is_a_lead_the_model_confirms_then_it_is_a_thesis_break(root):
    url = "https://n.example/alpha-industries-ceo-ousted"
    rows = [{"date": "2026-06-22", "url": url, "source": "n.example", "isin": A, "org": "alpha industries", "tone": -3.0, "themes": "", "india": True, "numarts": 1}]
    _w(root, "news_s81/gkg1/2026-06-22.parquet", pd.DataFrame(rows))
    p = news.text_path(root, news.url_hash(url))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"url": url, "title": "Alpha Industries CEO ousted by board", "text": "The board of Alpha Industries removed its chief executive. " * 5}), encoding="utf-8")
    g = kb.build(root, date(2026, 6, 30), groups=GROUPS)
    ev = g["event"][g["event"]["ref"] == url].iloc[0]
    assert (ev["kind"], ev["severity"]) == ("news", "low")                                              # the keyword alone is a lead, never a sale

    class R:
        def __init__(self, text):
            self.text = text
    asked = []

    def chat(model, msgs, **kw):
        asked.append(json.dumps(msgs))
        return R(json.dumps({"kind": "leadership_crisis", "severity": "high"}))
    out = job.classify_pending(root, g, limit=1, chat=chat)                                              # limit 1: the governance lead is asked about FIRST
    assert out["classified"] == 1 and "ousted" in asked[0]
    g2 = kb.build(root, date(2026, 6, 30), groups=GROUPS)
    ev2 = g2["event"][g2["event"]["ref"] == url].iloc[0]
    assert (ev2["kind"], ev2["severity"]) == ("leadership_crisis", "high")
    c = _audit_con()
    kb.load_store(c, g2, date(2026, 6, 30))
    seen = kev.material_events(c, [A], datetime(2026, 6, 1))
    assert any(e["kind"] == "leadership_crisis" and e["ref"] == url for e in seen)                      # think/watch and the exit manager see it as a thesis-break event


def test_a_model_that_says_none_leaves_the_article_as_other(root):
    url = "https://n.example/alpha-industries-ceo-ousted"
    _w(root, "news_s81/gkg1/2026-06-22.parquet", pd.DataFrame([{"date": "2026-06-22", "url": url, "source": "n.example", "isin": A, "org": "alpha industries", "tone": 0.0,
                                                                  "themes": "", "india": True, "numarts": 1}]))
    p = news.text_path(root, news.url_hash(url))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"url": url, "title": "Alpha Industries CEO ousted film role", "text": "A film."}), encoding="utf-8")
    g = kb.build(root, date(2026, 6, 30), groups=GROUPS)

    class R:
        def __init__(self, text):
            self.text = text
    job.classify_pending(root, g, limit=1, chat=lambda *a, **k: R(json.dumps({"kind": "none", "severity": "low"})))
    g2 = kb.build(root, date(2026, 6, 30), groups=GROUPS)
    assert g2["event"][g2["event"]["ref"] == url].iloc[0]["kind"] == "other"


# ------------------------------------------------------------------ the exit manager (A58 timing)

def _drill(root, day: date, head: str):
    _add_file(root, day, [_filing("500001", head, pd.NaT, news_dt=pd.NaT)])
    return kb.build(root, day, groups=GROUPS)


def test_exit_defaults_and_config_name_the_kind():
    assert "leadership_crisis" in exits.DEFAULTS["thesis_kinds"] and "leadership_crisis" in exits.settings()["thesis_kinds"]


def test_a_held_name_with_a_governance_shock_is_sold_on_the_next_trading_day_not_before(xcon, root):
    """Held WIN (= A). 'Board prepares to oust chief executive', no release time, dated Fri 30 Oct: Friday's check sees nothing; Monday 2 Nov sells (one sale only)."""
    con = xcon
    exits.backfill_plans(con, EXIT_DAY)
    kb.load_store(con, _drill(root, EXIT_DAY, "Board prepares to oust chief executive, reports say"), EXIT_DAY)
    evs = kev.material_events(con, [WIN], datetime(2026, 10, 25))
    assert len(evs) == 1 and evs[0]["kind"] == "leadership_crisis" and evs[0]["severity"] == "high"
    assert exits.check_thesis(con, EXIT_DAY, evs, prices={WIN: 100.0}) == []
    mon = date(2026, 11, 2)
    o = exits.check_thesis(con, mon, evs, prices={WIN: 100.0})
    assert len(o) == 1 and o[0]["kind"] == "thesis" and o[0]["isin"] == WIN and o[0]["side"] == "sell" and "leadership_crisis" in o[0]["reason"]
    assert exits.check_thesis(con, mon, evs, prices={WIN: 100.0}) == []


def test_a_plan_opened_before_the_kind_existed_still_reads_it(xcon, root):
    """Even a MEDIUM leadership_crisis (kind hit) breaks the thesis of a plan whose stored list lacks the kind (opened before this release)."""
    con = xcon
    exits.backfill_plans(con, EXIT_DAY)
    old = [k for k in exits.settings()["thesis_kinds"] if k != "leadership_crisis"]
    con.execute("UPDATE exit_plans_s81 SET thesis_break_kinds=? WHERE isin=?", [json.dumps(old), WIN])
    ev = [{"isin": WIN, "kind": "leadership_crisis", "severity": "medium", "ts": datetime(2026, 10, 31, 9, 15), "source": "gdelt_gkg1", "ref": "r1", "text": "CEO on leave"}]
    o = exits.check_thesis(con, date(2026, 11, 2), ev, prices={WIN: 100.0})
    assert len(o) == 1 and o[0]["kind"] == "thesis"


def test_ordinary_news_and_a_core_plan_do_not_sell(xcon, root):
    con = xcon
    exits.backfill_plans(con, EXIT_DAY)
    low = [{"isin": WIN, "kind": "news", "severity": "low", "ts": datetime(2026, 10, 31, 9, 15), "source": "bse_announcement", "ref": "r2", "text": "CEO to present"}]
    assert exits.check_thesis(con, date(2026, 11, 2), low, prices={WIN: 100.0}) == []
    con.execute("UPDATE exit_plans_s81 SET thesis_break_kinds='[]' WHERE isin=?", [WIN])                    # a plan with no thesis break (the core) ignores events
    hi = [{"isin": WIN, "kind": "leadership_crisis", "severity": "high", "ts": datetime(2026, 10, 31, 9, 15), "source": "bse_announcement", "ref": "r3", "text": "CEO ousted"}]
    assert exits.check_thesis(con, date(2026, 11, 2), hi, prices={WIN: 100.0}) == []
