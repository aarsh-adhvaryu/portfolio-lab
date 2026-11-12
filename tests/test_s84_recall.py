"""S84 recall (`think/recall.py`, T2x: what we already know). Synthetic data only (rule 7): invented companies, notes and events, a scripted client."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS

import pytest

from pflab import think
from pflab.agents import analyst as an
from pflab.pm import store
from pflab.think import cases, recall

NOW = datetime(2026, 11, 12, 18, 0)
AAA, BBB, PEER, SECT = "INE000A01011", "INE000B01012", "INE000P01017", "INE000S01018"
CFG = {"model": an.MODEL, "cap": 1500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True}


@pytest.fixture(autouse=True)
def _graph_on(monkeypatch):
    monkeypatch.setenv("PFLAB_KG", "on")


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "t.duckdb")
    for isin, sym, name in ((AAA, "AAAA", "Aaaa Industries"), (BBB, "BBBB", "Bbbb Foods"), (PEER, "PEERCO", "Peer Co"), (SECT, "SECTCO", "Sector Co")):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, 'synthetic', now())", [isin, sym, name])
        c.execute("INSERT INTO kg2_node VALUES (?,?,?,?,?,?)", [isin, name, sym, "test", "synthetic", date(2026, 1, 1)])
    return c


def note(con, topic: str, isins, text: str, when: datetime, question: str = "How did revenue change and why?", cost_tokens: int = 8000) -> str:
    """An analyst note exactly as `analyst.keep` writes it (graph document + memory row + the api_calls row)."""
    req = an.Request(question, topic, [], list(isins), True)
    cid = an._log(con, req, "live", an.MODEL, "sending", when, {})
    an.keep(con, cid, req, text, NS(input_tokens=cost_tokens, output_tokens=900), False, CFG, when)
    return con.execute("SELECT note_doc FROM api_calls WHERE call_id=?", [cid]).fetchone()[0]


def event(con, eid: str, isin: str, ts: datetime, kind: str, severity: str, headline: str, source: str = "bse_announcement"):
    con.execute("INSERT INTO kg2_event (event_id, isin, source, ref, ts, event_date, kind, severity, headline, link_rule, link_proof, dedupe_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [eid, isin, source, eid, ts, ts.date(), kind, severity, headline, "rule", "proof", eid])


def bars(con, isin: str, days: int, start: float, end: float, last: date = NOW.date()):
    d = last - timedelta(days=days - 1)
    for k in range(days):
        day = d + timedelta(days=k)
        if day.weekday() >= 5:
            continue
        wiggle = 1.0 + (0.004 if k % 2 else -0.004)                                                  # a usual daily move of about 0.8%
        con.execute("INSERT INTO prices VALUES (?,?,?, 'EQ', 'synthetic', now())", [isin, day, (start + (end - start) * k / max(1, days - 1)) * wiggle])


# --- what is returned ---------------------------------------------------------------------------------------------------------------

def test_a_note_on_a_held_name_appears_and_a_note_about_another_name_does_not(con):
    a = note(con, "AAAA", [AAA], "Aaaa's order book is full and margins are widening.", datetime(2026, 11, 5, 21, 0))
    b = note(con, "BBBB", [BBB], "Bbbb faces a price war in staples.", datetime(2026, 11, 6, 21, 0))
    r = recall.recall(con, NOW, isin=AAA)
    ids = {i["id"] for i in r["items"]}
    assert a in ids and b not in ids and "order book" in r["text"] and "price war" not in r["text"]
    it = [i for i in r["items"] if i["id"] == a][0]
    assert it["kind"] == "analyst_note" and it["day"] == "2026-11-05" and it["source"].startswith("analyst") and it["title"]
    assert {i["id"] for i in recall.recall(con, NOW, symbol="bbbb")["items"]} >= {b} and a not in {i["id"] for i in recall.recall(con, NOW, symbol="BBBB")["items"]}


def test_the_graph_being_off_does_not_hide_a_note(con, monkeypatch):
    monkeypatch.setenv("PFLAB_KG", "off")                                    # the old graph writes no edges while it is off: the note is still found by its symbol
    a = note(con, "AAAA,BBBB", [AAA, BBB], "A two-name note.", datetime(2026, 11, 5, 21, 0))
    assert a in {i["id"] for i in recall.recall(con, NOW, isin=AAA)["items"]} and a in {i["id"] for i in recall.recall(con, NOW, isin=BBB)["items"]}


def test_nothing_dated_after_asof_is_returned(con):
    note(con, "AAAA", [AAA], "Old view of Aaaa.", datetime(2026, 11, 1, 21, 0))
    note(con, "AAAA", [AAA], "Newer view of Aaaa.", datetime(2026, 11, 10, 21, 0))
    event(con, "e-late", AAA, datetime(2026, 11, 11, 10, 0), "regulatory_action", "high", "A late order")
    event(con, "e-derived", AAA, datetime(2026, 11, 13, 9, 15), "fraud_investigation", "high", "A filing dated today, usable from the next open")        # A58: held back until its ts
    con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, thesis, break_condition, state, proposed_on) VALUES (1,'IN',?,?,'system','later thesis','later break','proposed',?)", [AAA, "AAAA", date(2026, 11, 11)])
    c = cases.open_case(con, datetime(2026, 11, 11, 10, 0), market="IN", kind="move", isin=AAA, symbol="AAAA", title="a later case")
    r = recall.recall(con, NOW, isin=AAA, asof=date(2026, 11, 9))
    assert [i["day"] for i in r["items"]] == ["2026-11-01"] and "Newer view" not in r["text"]
    assert all(i["day"] <= "2026-11-09" for i in r["items"])
    r2 = recall.recall(con, NOW, isin=AAA)                                                       # asof defaults to now
    kinds = {i["kind"]: i for i in r2["items"]}
    assert "e-late" in {i["id"] for i in r2["items"]} and "e-derived" not in {i["id"] for i in r2["items"]} and f"case:{c}" in {i["id"] for i in r2["items"]}
    assert recall.recall(con, datetime(2026, 11, 13, 9, 30), isin=AAA)["text"].count("e-derived") == 1       # visible once its own time has come
    assert recall.recall(con, NOW, isin=AAA, asof=date(2030, 1, 1))["n"] == r2["n"]               # an asof after now is clamped to now


def test_graph_events_peers_industry_storylines_pick_skip_and_earlier_cases_come_back(con):
    for isin in (AAA, SECT, PEER):
        con.execute("INSERT INTO kg2_fact VALUES (?, 'industry', 'Auto parts', NULL, 'synthetic', ?, ?)", [isin, date(2026, 1, 1), date(2026, 1, 1)])
    con.execute("INSERT INTO kg2_relation VALUES (?,?,?,?,?,?)", [AAA, PEER, "same_group", "both in the Aaaa group", "synthetic", date(2026, 2, 1)])
    event(con, "e-own", AAA, datetime(2026, 11, 10, 10, 0), "guidance_cut", "medium", "Aaaa cuts its guidance")
    event(con, "e-routine", AAA, datetime(2026, 11, 10, 11, 0), "routine", "low", "Trading window closes")
    event(con, "e-peer", PEER, datetime(2026, 11, 9, 10, 0), "regulatory_action", "high", "Peer Co gets a show cause notice")
    event(con, "e-sector", SECT, datetime(2026, 11, 8, 10, 0), "fraud_investigation", "high", "Sector Co raided")
    con.execute("INSERT INTO storylines_s80 (storyline_id, market, claim, kind, direction, subject, opened_on, status, prior, probability, influence) VALUES (7,'IN','Auto demand slows','market',-1,'AUTO',?, 'open',0.5,0.6,0.5)", [date(2026, 10, 1)])
    con.execute("INSERT INTO storyline_exposure_s80 VALUES (7, ?, 0.5, 'test', ?)", [AAA, date(2026, 10, 1)])
    con.execute("INSERT INTO storyline_prob_s80 VALUES (7, ?, 0.61, 0.4, '{}')", [date(2026, 11, 9)])
    con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, thesis, break_condition, state, proposed_on) VALUES (1,'IN',?,?,'system','Order book is full','A margin squeeze','held',?)", [AAA, "AAAA", date(2026, 10, 20)])
    con.execute("INSERT INTO skips_s83 VALUES (1,'IN',?,?, 'Too expensive for now', ?, 's')", [BBB, "BBBB", date(2026, 10, 25)])
    c = cases.open_case(con, datetime(2026, 11, 3, 10, 0), market="IN", kind="move", isin=AAA, symbol="AAAA", title="Aaaa fell 8%")
    cases.set_case(con, c, klass="temporary", summary="a fall on market fear", pending="the results")
    d = cases.record_decision(con, c, date(2026, 11, 4), isin=AAA, symbol="AAAA", rule_option="hold", model_option="hold", acted_option="hold", reason="the business is intact")
    con.execute("INSERT INTO think_scores_s84 VALUES (1, ?, 5, 'rule', 'hold', 1200.0, 300.0, ?)", [d, date(2026, 11, 11)])
    other = cases.open_case(con, datetime(2026, 11, 2, 10, 0), market="IN", kind="move", isin=BBB, symbol="BBBB", title="Bbbb fell 9%")
    r = recall.recall(con, NOW, isin=AAA, kind="move")
    by = {}
    for i in r["items"]:
        by.setdefault(i["kind"], []).append(i)
    assert [i["id"] for i in by["kg2_event"]] == ["e-own"] and "Trading window" not in r["text"]            # the routine one is not material
    assert [i["id"] for i in by["kg2_peer_event"]] == ["e-peer"] and [i["id"] for i in by["kg2_sector_event"]] == ["e-sector"]
    assert by["kg2_relation"][0]["id"] == f"{AAA}>{PEER}:same_group" and "same_group" in by["kg2_relation"][0]["title"]
    assert by["storyline"][0]["id"] == "story:7" and "0.61" not in by["storyline"][0]["text"] and "61%" in by["storyline"][0]["text"]
    assert by["pick"][0]["text"].startswith("thesis: Order book is full | breaks if: A margin squeeze")
    assert f"case:{c}" in {i["id"] for i in by["case"]} and any("scored at 5 sessions" in i["text"] and "300" in i["text"] and "chose hold" in i["text"] for i in by["case"])
    assert f"case:{other}" in {i["id"] for i in by["case_same_kind"]}
    sk = recall.recall(con, NOW, isin=BBB)
    assert any(i["kind"] == "skip" and "Too expensive" in i["text"] for i in sk["items"])
    # by sector and by topic, with no name
    sec = recall.recall(con, NOW, sector="Auto parts")
    assert {i["id"] for i in sec["items"] if i["kind"] == "kg2_sector_event"} == {"e-peer", "e-sector"}                  # the high-severity events of the industry (the medium one is not)
    top = recall.recall(con, NOW, topic="AUTO")
    assert [i["id"] for i in top["items"]] == ["story:7"]


def test_the_result_is_newest_first_and_inside_the_size_limit(con):
    for k in range(12):
        note(con, "AAAA", [AAA], f"Note number {k}: " + "the order book is full and margins are widening. " * 30, datetime(2026, 10, 1 + k, 21, 0), question=f"Question {k} about Aaaa's revenue?")
    r = recall.recall(con, NOW, isin=AAA, limit_chars=2000)
    assert 1 <= r["n"] <= 3 and len(r["text"]) <= 2000 and r["items"] == sorted(r["items"], key=lambda i: i["day"], reverse=True)
    assert all(len(i["text"]) <= think.settings().get("recall_item_chars", 700) for i in r["items"])
    assert r["items"][0]["day"] == "2026-10-12"


def test_recall_never_raises_and_an_unknown_name_returns_nothing(con):
    assert recall.recall(con, NOW, isin="ZZ0000000000") == {"items": [], "text": "", "n": 0, "resolved": {"isin": "ZZ0000000000", "symbol": None, "name": None}}
    assert recall.recall(con, NOW)["n"] == 0
    con.execute("DROP TABLE kg2_event")
    assert recall.recall(con, NOW, isin=AAA)["n"] == 0


# --- stored is not used until something reads it --------------------------------------------------------------------------------------

def test_the_items_a_decision_reads_are_counted_once_and_the_knowledge_line_counts_them(con):
    a = note(con, "AAAA", [AAA], "Aaaa note read by a case.", datetime(2026, 11, 3, 21, 0))
    b = note(con, "BBBB", [BBB], "Bbbb note nobody reads.", datetime(2026, 11, 4, 21, 0), question="What about Bbbb margins?")
    old = note(con, "AAAA", [AAA], "An October note nobody read.", datetime(2026, 9, 20, 21, 0), question="A September question on Aaaa?")
    r = recall.recall(con, NOW, isin=AAA)
    assert {i["id"] for i in r["items"]} == {a, old}                                                     # b is about another name
    read = [i for i in r["items"] if i["id"] == a]
    assert recall.mark_used(con, read, by_kind="case", by_ref="case:1", day=NOW.date()) == 1
    assert recall.mark_used(con, read, by_kind="case", by_ref="case:1", day=NOW.date()) == 0              # once per item, reader and day
    assert con.execute("SELECT count(*) FROM knowledge_use_s84 WHERE item_id=? AND used_by_kind='case'", [a]).fetchone()[0] == 1
    kl = recall.knowledge_line(con, NOW.date())
    inr = con.execute("SELECT cost_inr FROM api_calls WHERE note_doc=?", [old]).fetchone()[0]
    assert kl["paid_notes_this_month"] == 2 and kl["read_by_a_decision"] == 1                           # a and b are this month; only a was read
    assert kl["unread_30d_rupees"] == pytest.approx(inr, abs=0.01) and inr > 0                           # the September note, never read (b is under 30 days old)
    assert "2" in kl["text"] and "1" in kl["text"]
    recall.mark_used(con, [i for i in r["items"] if i["id"] == old], by_kind="desk", by_ref="desk:1", day=NOW.date())
    assert recall.knowledge_line(con, NOW.date())["unread_30d_rupees"] == 0.0                            # read within the 30 days: no longer unread
    assert b not in {i["id"] for i in r["items"]}


def test_an_empty_store_has_a_plain_knowledge_line(con):
    kl = recall.knowledge_line(con, NOW.date())
    assert kl["paid_notes_this_month"] == 0 and kl["read_by_a_decision"] == 0 and kl["unread_30d_rupees"] == 0.0 and "none" in kl["text"]


# --- written back ---------------------------------------------------------------------------------------------------------------------

def test_a_written_back_note_is_found_by_name_symbol_and_topic_and_the_old_chat_reads_it(con):
    doc = recall.write_back(con, NOW, isin=AAA, title="Case 4: the board's decision", text="Class unclear; waiting for the board.", source="think case #4", cost_rupees=12.5, case_id=4)
    topic_doc = recall.write_back(con, NOW, topic="crude oil", title="Web check on crude", text="Brent fell on a supply report [W1].", source="web check")
    for kw in ({"isin": AAA}, {"symbol": "AAAA"}):
        assert doc in {i["id"] for i in recall.recall(con, NOW + timedelta(minutes=1), **kw)["items"]}
    top = recall.recall(con, NOW + timedelta(minutes=1), topic="crude oil")
    assert [i["id"] for i in top["items"]] == [topic_doc] and "supply report" in top["text"]
    assert recall.recall(con, NOW - timedelta(minutes=1), isin=AAA)["n"] == 0                       # not before it was written
    it = [i for i in recall.recall(con, NOW + timedelta(minutes=1), isin=AAA)["items"] if i["id"] == doc][0]
    assert it["kind"] == "note" and it["source"] == "think case #4" and it["day"] == "2026-11-12"
    assert con.execute("SELECT count(*) FROM memory WHERE subject='AAAA' AND source LIKE 'recall:%'").fetchone()[0] == 1       # the old memory
    assert an.latest_note(con, AAA, NOW.date()) is not None and "Class unclear" in an.latest_note(con, AAA, NOW.date())          # the old graph and chat read it too
    with pytest.raises(ValueError):
        recall.write_back(con, NOW, isin=AAA, title="", text="x", source="s")
    # a paid write-back counts in the knowledge line and is never listed twice
    assert recall.knowledge_line(con, NOW.date())["paid_notes_this_month"] == 1 and len([i for i in recall.recall(con, NOW + timedelta(minutes=1), isin=AAA)["items"] if i["id"] == doc]) == 1


# --- never pay twice ------------------------------------------------------------------------------------------------------------------

class FakeClient:
    def __init__(self):
        self.creates = 0
        self.messages = NS(count_tokens=lambda **kw: NS(input_tokens=8000))
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.creates += 1
        text = NS(type="text", text="Revenue rose on the year.", citations=[NS(document_index=0)])
        return NS(content=[NS(type="thinking", thinking=""), text], stop_reason="end_turn", usage=NS(input_tokens=8000, output_tokens=900))


def test_a_note_with_nothing_new_since_is_fresh_and_an_event_a_move_or_age_make_it_stale(con):
    bars(con, AAA, 70, 100.0, 101.0)
    a = note(con, "AAAA", [AAA], "Aaaa is fine.", datetime(2026, 11, 5, 21, 0))
    f = recall.same_subject_fresh(con, NOW, isin=AAA)
    assert f and f["id"] == a and f["age_days"] == pytest.approx(6.9, abs=0.1) and "no event" in f["why"] and f["text"] == "Aaaa is fine."
    assert recall.same_subject_fresh(con, NOW, isin=BBB) is None                                      # another name: no note
    assert recall.same_subject_fresh(con, NOW, isin=AAA, since_move=0.30) is None                     # the caller's own move since is beyond the threshold
    assert recall.same_subject_fresh(con, NOW, isin=AAA, since_move=0.01)["id"] == a
    event(con, "e-routine", AAA, datetime(2026, 11, 9, 10, 0), "routine", "low", "Trading window")
    assert recall.same_subject_fresh(con, NOW, isin=AAA)["id"] == a                                   # a routine filing is not an event
    event(con, "e-res", AAA, datetime(2026, 11, 9, 11, 0), "results", "low", "Quarterly results")
    assert recall.same_subject_fresh(con, NOW, isin=AAA) is None                                      # a result since the note
    assert recall.same_subject_fresh(con, datetime(2026, 11, 8, 12, 0), isin=AAA)["id"] == a          # ... which was not yet public on the 8th
    ch = recall.changed_since(con, NOW, AAA, datetime(2026, 11, 5, 21, 0))
    assert ch["changed"] and [e["event_id"] for e in ch["events"]] == ["e-res"]
    assert recall.same_subject_fresh(con, NOW + timedelta(days=60), isin=AAA) is None                 # too old


def test_a_big_move_since_the_note_makes_it_stale(con):
    bars(con, AAA, 70, 100.0, 100.0, last=date(2026, 11, 5))
    note(con, "AAAA", [AAA], "Aaaa is fine.", datetime(2026, 11, 5, 21, 0))
    bars(con, AAA, 4, 100.0, 80.0, last=NOW.date())                                                   # a 20% fall in the four days since (6-12 Nov)
    assert recall.same_subject_fresh(con, NOW, isin=AAA) is None
    assert recall.same_subject_fresh(con, datetime(2026, 11, 6, 12, 0), isin=AAA) is not None


def test_the_second_paid_call_on_an_unchanged_subject_costs_zero(con):
    bars(con, AAA, 70, 100.0, 101.0)
    c = FakeClient()
    q = lambda text: an.Request(text, "AAAA", [an.Doc("Board outcome", "Aaaa reported quarterly revenue of 1,100.0 million rupees.", "https://x/y.pdf", "2026-11-04", "filing")], [AAA], True)
    first = an.ring(con, q("How did Aaa's revenue change and why?"), c, now=datetime(2026, 11, 8, 21, 0), cfg=CFG)
    assert first.status == "done" and c.creates == 1 and first.cost_inr > 0
    spent = con.execute("SELECT coalesce(sum(cost_inr),0) FROM api_calls").fetchone()[0]
    second = an.ring(con, q("What is the outlook for margins?"), c, now=NOW, cfg=CFG)                # a different question, the same name, nothing new since
    assert second.status == "reused" and c.creates == 1 and "Revenue rose" in second.text
    assert con.execute("SELECT coalesce(sum(cost_inr),0) FROM api_calls").fetchone()[0] == spent          # no new spend, no new api_calls row
    event(con, "e-res", AAA, datetime(2026, 11, 10, 9, 0), "guidance_cut", "medium", "Aaaa cuts guidance")
    third = an.ring(con, q("What does the guidance cut mean for margins?"), c, now=NOW, cfg=CFG)      # an event since: asked again
    assert third.status == "done" and c.creates == 2


def test_a_repeated_web_check_on_an_unchanged_name_costs_zero(con):
    bars(con, AAA, 70, 100.0, 101.0)

    class Web(FakeClient):
        def __init__(self):
            super().__init__()
            self.messages = NS(count_tokens=lambda **kw: NS(input_tokens=2000))

        def _create(self, **kw):
            self.creates += 1
            return NS(content=[NS(type="text", text="The plant started in October.", citations=[NS(type="web_search_result_location", url="https://x.in/a", title="A", cited_text="..")])],
                      stop_reason="end_turn", usage=NS(input_tokens=2000, output_tokens=500, server_tool_use=NS(web_search_requests=1)))
    c = Web()
    q = "Has the second plant of AAAA started?"
    o1 = an.web_search(con, q, c, now=datetime(2026, 11, 8, 21, 0), cfg=CFG, pv=an.Private(), topic="brain web")
    assert o1.status == "done" and c.creates == 1
    o2 = an.web_search(con, q, c, now=NOW, cfg=CFG, pv=an.Private(), topic="brain web")
    assert o2.status == "reused" and c.creates == 1 and "plant started" in o2.text
    o3 = an.web_search(con, "Did the RBI change the repo rate?", c, now=NOW, cfg=CFG, pv=an.Private(), topic="brain web")        # a different question is asked
    assert o3.status == "done" and c.creates == 2
    event(con, "e-news", AAA, datetime(2026, 11, 11, 9, 0), "regulatory_action", "medium", "Aaaa gets a notice")
    o4 = an.web_search(con, q, c, now=NOW, cfg=CFG, pv=an.Private(), topic="brain web")
    assert o4.status == "done" and c.creates == 3                                                    # an event on the name since: paid again


def test_a_note_on_several_names_is_reused_for_the_same_names_within_the_topic_window(con):
    n = note(con, "AAAA,BBBB", [AAA, BBB], "A note on the two names together.", datetime(2026, 11, 9, 21, 0))
    f = recall.same_subject_fresh(con, NOW, topic="AAAA,BBBB")
    assert f and f["id"] == n                                                                          # no single name to check events for: the topic window (14 days) applies
    assert recall.same_subject_fresh(con, NOW + timedelta(days=20), topic="AAAA,BBBB") is None
    assert recall.same_subject_fresh(con, NOW, topic="AAAA,PEERCO") is None
    assert recall.same_subject_fresh(con, NOW, topic="general") is None                                # a generic topic is never "the same subject"
