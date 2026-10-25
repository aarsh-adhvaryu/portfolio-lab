"""S44 API analyst behind the doorbell, with a FAKE SDK client: the egress gate, reuse, budget, live and batch."""
from datetime import date, datetime
from types import SimpleNamespace as NS

import pytest

from pflab.agents import analyst as an
from pflab.ledger.events import Event, EventLog, save
from pflab.pm import store

AAA = "INE000A01011"
NOW = datetime(2026, 10, 17, 21, 0)
CFG = {"model": an.MODEL, "cap": 1500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True}


def _store(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('ZERO1', 'demat', 'Zerodha', "
                "'1208160012345678')")
    save(con, EventLog([Event("deposit", "ZERO1", date(2026, 9, 1), amount=250_000.0),
                        Event("buy", "ZERO1", date(2026, 9, 2), isin=AAA, qty=100, price=1_200.0, ref="T1")]))
    return con


def doc(text="Aaa Limited reported quarterly revenue of 1,100.0 million rupees.", kind="filing"):
    return an.Doc("Outcome of board meeting", text, "https://www.bseindia.com/x.pdf", "2026-10-15", kind)


class FakeClient:
    def __init__(self, tokens=8_000, stop="end_turn"):
        self.calls, self.tokens, self.stop = [], tokens, stop
        self.messages = NS(count_tokens=self._count, batches=NS(create=self._bcreate, retrieve=self._bget,
                                                                 results=self._bresults))
        self.beta = NS(messages=NS(create=self._create))
        self.batch = None

    def _count(self, **kw):
        self.calls.append(("count", kw))
        return NS(input_tokens=self.tokens)

    def _create(self, **kw):
        self.calls.append(("create", kw))
        text = NS(type="text", text="Revenue rose on the year.", citations=[NS(document_index=0)])
        return NS(content=[NS(type="thinking", thinking=""), text], stop_reason=self.stop,
                  usage=NS(input_tokens=self.tokens, output_tokens=900))

    def _bcreate(self, requests):
        self.batch = list(requests)
        self.calls.append(("batch", self.batch))
        return NS(id="msgbatch_1")

    def _bget(self, bid):
        return NS(processing_status="ended")

    def _bresults(self, bid):
        msg = NS(content=[NS(type="text", text="Overnight answer.", citations=[])], stop_reason="end_turn",
                 usage=NS(input_tokens=4_000, output_tokens=500))
        return [NS(custom_id=r["custom_id"], result=NS(type="succeeded", message=msg)) for r in self.batch]


def req(question="How did Aaa's revenue change and why?", urgent=True, docs=None):
    return an.Request(question, "AAA", docs if docs is not None else [doc()], [AAA], urgent)


# ---- the egress gate ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("question, docs, what", [
    ("What does Ravi Kumar's position in AAA look like?", None, "personal wording"),
    ("Should I worry, given my portfolio holds AAA?", None, "personal wording"),
    ("I hold AAA: what changed?", None, "personal wording"),
    ("AAA question from ABCDE1234F", None, "PAN"),
    ("Send it to someone@example.com", None, "e-mail"),
    ("Call 9876543210 about AAA", None, "phone"),
    ("Account 1208160012345678 at the depository", None, "account-like number"),
    ("Is 2,50,000 a lot of cash for AAA?", None, "matches the ledger"),
    ("AAA revenue near 2,50,900?", None, "matches the ledger"),             # within 0.5% of a ledger amount
    ("What about 100 shares of AAA?", None, "quantity that matches a holding"),
    ("Is 1,30,000 enough?", None, "matches the ledger"),                     # cash left after the buy
    ("What changed?", [an.Doc("ledger", "x", "ledger", "2026-10-15", "networth")], "not a public"),
    ("What changed in ZERO1 since September?", None, "account or deposit id"),
])
def test_the_gate_stops_anything_personal_and_nothing_is_sent(tmp_path, question, docs, what):
    con = _store(tmp_path)
    c = FakeClient()
    o = an.ring(con, req(question, docs=docs), c, now=NOW, cfg=CFG)
    assert o.status == "blocked" and what in o.text and c.calls == []         # never priced, never sent
    assert con.execute("SELECT count(*) FROM api_calls").fetchone()[0] == 0


def test_a_public_question_passes_the_gate_even_with_busy_public_documents(tmp_path):
    """Real filings carry company phone numbers, e-mails and many figures; some will sit near a ledger amount
    by chance. Public documents pass on provenance; only the question is held to the personal checks."""
    con = _store(tmp_path)
    busy = doc("Contact the company secretary at cs@aaa.co.in or 9876543210. Order worth Rs 2,50,400 received; "
               "CIN L12345MH1990PLC123456; 100 crore capex.")
    assert an.gate(req(docs=[busy]), an.private_values(con))["documents"] == 1


def test_requests_are_built_only_from_public_graph_documents(tmp_path, monkeypatch):
    from pflab.kg import graph as g
    con = _store(tmp_path)
    for kind, title in (("filing", "Board outcome"), ("result", "Results for quarter ended 2026-06-30"),
                        ("article", "Aaa wins an order"), ("analyst_note", "an older note")):
        d = g.doc(con, kind, f"k-{kind}", datetime(2026, 10, 10), title, source="BSE",
                  attrs={"revenue": 1100.0, "eps": 24.06} if kind == "result" else None)
        g.edge(con, d, "about" if kind != "article" else "mentions", f"company:{AAA}", datetime(2026, 10, 10), "test")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'Aaa Limited', 'synthetic', now())""", [AAA])
    docs = an.public_docs(con, [AAA], date(2026, 10, 17))
    assert sorted(d.kind for d in docs) == ["article", "filing", "result"]
    res = [d for d in docs if d.kind == "result"][0].text
    # the analyst's own first notes flagged both: results named no company and gave EPS in million rupees
    assert res.startswith("Aaa Limited (AAA): Results for quarter ended")
    assert "revenue 1100.0 million rupees" in res and "eps 24.06 rupees per share" in res
    # 2026-10-18: it read the fetch date as the filing date; the basis and the dating are stated
    assert "standalone results" in res and "first fetched by this system on 2026-10-10" in res


def test_filed_results_say_when_they_were_filed_and_names_never_read_none(tmp_path):
    from pflab.kg import graph as g
    con = _store(tmp_path)
    d = g.doc(con, "result", "k", datetime(2026, 8, 1), "Results for quarter ended 2026-06-30", source="BSE",
              attrs={"net_profit": 5.0, "quarter_end": "2026-06-30", "basis": "standalone", "date_source": "bse_filing"})
    g.edge(con, d, "about", f"company:{AAA}", datetime(2026, 8, 1), "test")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'AAA', NULL, 'synthetic', now())""", [AAA])
    res = an.public_docs(con, [AAA], date(2026, 10, 17))[0].text
    assert res.startswith("AAA (AAA): ") and "quarter ended 2026-06-30; filed at BSE on 2026-08-01" in res
    assert "net profit 5.0 million rupees" in res and "date source" not in res


def test_articles_that_only_mention_the_company_in_passing_are_left_out(tmp_path):
    from pflab.kg import graph as g
    con = _store(tmp_path)
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'Aaa Holdings Limited', 'synthetic', now())""", [AAA])
    for k, title in enumerate(["Aaa wins a large export order", "Fund house lists a new index ETF on the AAA platform",
                               "Horoscope for the week ahead", "aaa holdings board approves buyback"]):
        d = g.doc(con, "article", f"u{k}", datetime(2026, 10, 10 + k), title, f"https://x.in/{k}", "x.in")
        g.edge(con, d, "mentions", f"company:{AAA}", datetime(2026, 10, 10 + k), "gdelt_gkg")
    titles = [d.title for d in an.public_docs(con, [AAA], date(2026, 10, 17), stock_list=[])]
    assert titles == ["aaa holdings board approves buyback", "Aaa wins a large export order"]


def test_headline_names_never_use_a_first_word_two_companies_share():
    import pandas as pd

    from pflab.kg import build as kb
    u = pd.DataFrame([{"isin": "INE1", "symbol": "GRPPOWER", "name": "Group Power Limited", "aliases": []},
                      {"isin": "INE2", "symbol": "GRPSOFT", "name": "Group Software Services Limited", "aliases": []},
                      {"isin": "INE3", "symbol": "ZETA", "name": "Zetaline Motors Limited", "aliases": ["zeta motors"]}])
    n = kb.headline_names(u)
    assert "group" not in n["INE1"] and "group power" in n["INE1"] and "grppower" in n["INE1"]
    assert n["INE3"][:2] == ["zeta motors", "zetaline motors"] and "zetaline" in n["INE3"]
    assert kb.is_about("Zeta Motors recalls scooters", n["INE3"])
    assert not kb.is_about("Markets: indices close higher as banks, autos and metals gain; Zeta Motors flat", n["INE3"])


def test_the_report_shows_the_newest_note_per_company():
    t = lambda h: datetime(2026, 10, 17, h)
    notes = [(1, "AAA", t(18), 3.0, "old"), (2, "BBB", t(19), 1.0, "b"), (3, "AAA", t(23), 2.0, "new")]
    assert [(n[1], n[4]) for n in an.newest_per_topic(notes)] == [("AAA", "new"), ("BBB", "b")]


def test_the_local_model_gets_the_latest_analyst_note_as_a_source(tmp_path):
    con = _store(tmp_path)
    c = FakeClient()
    an.ring(con, req(), c, now=NOW, cfg=CFG)
    note = an.latest_note(con, AAA, NOW.date())
    assert note.startswith("2026-10-17 analyst note (API analyst, public documents): Revenue rose on the year.")
    assert an.latest_note(con, AAA, date(2026, 12, 31)) is None                        # older than 30 days


def test_sentences_with_numbers_not_in_the_documents_are_removed():
    """PLAN section 1 for API answers: the analyst's own arithmetic or recall never reaches the investor."""
    r = req(docs=[doc("Revenue was 1,100.0 million rupees; the order book stood at Rs 450 crore.")])
    text, n = an.only_sourced_numbers("Revenue was 1,100.0 million [D1]. That is about 12% growth on my estimate. "
                                      "The order book is Rs 450 crore [D1]. Margins are not reported.", r)
    assert n == 1 and "12%" not in text and "1,100.0" in text and "450 crore" in text
    assert "Margins are not reported." in text and "1 sentence(s) removed" in text
    assert an.only_sourced_numbers("No figures here.", r) == ("No figures here.", 0)


# ---- adoption, reuse, budget ----------------------------------------------------------------------------------------

def test_off_until_adopted_except_for_trial_calls(tmp_path):
    con = _store(tmp_path)
    with pytest.raises(an.NotAdopted):
        an.ring(con, req(), FakeClient(), now=NOW, cfg={**CFG, "adopted": False})
    assert an.ring(con, req(), FakeClient(), now=NOW, cfg={**CFG, "adopted": False}, trial=True).status == "done"


def test_live_call_shape_note_kept_and_reused_not_rebought(tmp_path):
    con = _store(tmp_path)
    c = FakeClient()
    o = an.ring(con, req(), c, now=NOW, cfg=CFG)
    assert o.status == "done" and o.text == "Revenue rose on the year. [D1]"
    kw = [k for n, k in c.calls if n == "create"][0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default" and kw["betas"] == [an.FALLBACK_BETA]
    assert kw["thinking"] == {"type": "adaptive"} and kw["output_config"] == {"effort": "high"}
    assert kw["messages"][0]["content"][0]["citations"] == {"enabled": True}
    assert o.cost_inr == pytest.approx((8_000 * 4 + 900 * 20) / 1e6 * 90)
    assert con.execute("SELECT count(*) FROM kg_docs WHERE kind='analyst_note'").fetchone()[0] == 1
    again = an.ring(con, req("Why did Aaa's revenue change?"), c, now=NOW, cfg=CFG)
    assert again.status == "reused" and len([1 for n, _ in c.calls if n == "create"]) == 1


def test_budget_cap_and_per_job_approval(tmp_path):
    con = _store(tmp_path)
    big = FakeClient(tokens=400_000)                                    # ~Rs 173 worst case: over the per-job limit
    with pytest.raises(an.NeedsApproval):
        an.ring(con, req(), big, now=NOW, cfg=CFG)
    assert an.ring(con, req(), big, now=NOW, cfg=CFG, approved=True).status == "done"
    with pytest.raises(an.BudgetRefused):
        an.ring(con, req("A different question on margins"), FakeClient(tokens=4_000_000), now=NOW, cfg=CFG,
                approved=True)
    with pytest.raises(an.BudgetRefused):
        an.ring(con, req("Another one"), FakeClient(), now=NOW, cfg={**CFG, "cap": 0.0})


def test_a_refusal_is_recorded_not_kept_as_a_note(tmp_path):
    con = _store(tmp_path)
    o = an.ring(con, req(), FakeClient(stop="refusal"), now=NOW, cfg=CFG)
    assert o.status == "refused" and con.execute("SELECT status FROM api_calls").fetchone()[0] == "refused"
    assert con.execute("SELECT count(*) FROM kg_docs WHERE kind='analyst_note'").fetchone()[0] == 0


def test_non_urgent_work_waits_for_the_half_price_batch(tmp_path):
    con = _store(tmp_path)
    c = FakeClient()
    o = an.ring(con, req(urgent=False), c, now=NOW, cfg=CFG)
    assert o.status == "queued" and not [1 for n, _ in c.calls if n == "create"]
    assert an.submit_batch(con, c, NOW) == "msgbatch_1" and "fallbacks" not in c.batch[0]["params"]
    assert an.collect_batches(con, c, CFG, NOW) == {"done": 1, "failed": 0, "pending": 0}
    st, inr = con.execute("SELECT status, cost_inr FROM api_calls").fetchone()
    assert st == "done" and inr == pytest.approx((4_000 * 4 + 500 * 20) / 1e6 * 0.5 * 90)


# ---- local first: the adopted research harness when Opus is not rung (2026-10-22) -----------------------------------

def test_local_answer_follows_the_reason_when_opus_is_not_rung(tmp_path, monkeypatch):
    from pflab.llm import adopted
    con = _store(tmp_path)
    prompts = []

    def llm(p):
        prompts.append(p)
        return "Aaa Limited reported quarterly revenue of 1,100.0 million rupees [S1]."

    monkeypatch.setattr(an, "deep_request", lambda con, q, asof: req())

    def off(*a, **k):
        raise an.NotAdopted("off")
    monkeypatch.setattr(an, "ring", off)
    out = an.ask_deep(con, "What did Aaa report?", date(2026, 10, 17), client=FakeClient(), llm=llm)
    assert out.startswith("Deep research is off: off.") and "1,100.0 million rupees [S1]" in out
    assert prompts and prompts[0].endswith(adopted.RESEARCH) and "[S1] 2026-10-15 filing" in prompts[0]
    assert an.ask_deep(con, "q", date(2026, 10, 17), client=FakeClient(), llm=llm, local=False) == \
        "Deep research is off: off."
    monkeypatch.setattr(an, "ring", lambda *a, **k: an.Outcome("blocked", "personal wording"))
    assert "Local model" in an.ask_deep(con, "q", date(2026, 10, 17), client=FakeClient(), llm=llm)
    assert an.local_answer(con, an.Request("q", "AAA"), llm) is None                    # no documents, no answer
    assert an.local_answer(con, req(), lambda p: "Revenue was 9,999 million [S1].") is None   # fails the guard



def test_years_dates_and_window_lengths_are_not_ledger_numbers_but_money_and_holdings_still_are():
    pv = an.Private(amounts={2015.0, 11569.0}, quantities={200.0, 252.0})
    ok = ["What was the maximum drawdown in 2020?", "the close on 2019-12-31", "a 200-session moving average",
          "times the square root of 252 trading days"]
    for q in ok:
        assert an.gate(an.Request(q, "workshop"), pv)
    for q, what in (("if the investor adds Rs 2,020", "rupee amount"), ("what if 11,570 is added", "rupee amount"),
                    ("sell 200 shares", "quantity")):
        with pytest.raises(an.EgressBlocked, match=what):
            an.gate(an.Request(q, "workshop"), pv)


def test_the_workshop_gates_the_question_not_the_made_up_rows(tmp_path):
    from pflab.agents import workshop as wk
    con = _store(tmp_path)
    c = FakeClient()
    prompt = "QUESTION:\nworst fall of the index?\n\nSAMPLE ROWS (made up, for shape only):\n{\"value\": 250000.0}"
    an.write_calculation(con, prompt, wk.WRITER_SYSTEM, c, cfg=CFG, now=NOW, gate_text="QUESTION:\nworst fall of the index?")
    with pytest.raises(an.EgressBlocked):                     # without gate_text the whole prompt is checked
        an.write_calculation(con, prompt, wk.WRITER_SYSTEM, c, cfg=CFG, now=NOW)
