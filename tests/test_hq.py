"""S59 the agent HQ (PLAN A16): egress list, governor, the API road, board, receptionist, messenger, drop folder,
readers, brain (shadow), memory keeper, phone, rounds. Synthetic data, a fake API client."""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from pflab.agents import analyst as an
from pflab.hq import board, brain, egress, governor as gv, keeper, llm, messenger, readers, reception
from pflab.hq.board import Reply
from pflab.hq.desk import Desk
from pflab.pm import store

AAA, BBB = "INE000A01011", "INE000B01012"
NOW = datetime(2026, 10, 26, 10, 0)          # a Monday
CFG = {"model": an.MODEL, "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True, "tijori_to_analyst": True}


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    for isin, sym in ((AAA, "AAA"), (BBB, "BBB")):
        c.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                     VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, ?, ?, 'synthetic', now())""", [isin, sym, f"{sym} Limited"])
    c.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('ZERODHA', 'demat', 'Zerodha', '12081600')")
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('SB12345678', 'bank', 'SBI')")
    return c


def _prices(con, isin, start: date, closes):
    d = start
    for x in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?)", [isin, d, float(x), "EQ", "nse_bhavcopy", NOW])
        d += timedelta(days=1)


class _Msgs:
    def __init__(self, replies, n_in=1000):
        self.replies, self.sent, self.n_in = list(replies), [], n_in

    def count_tokens(self, **kw):
        return SimpleNamespace(input_tokens=self.n_in)

    def create(self, **kw):
        self.sent.append(kw)
        r = self.replies.pop(0)
        text = r if isinstance(r, str) else json.dumps(r)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn", model=kw["model"],
                               usage=SimpleNamespace(input_tokens=800, output_tokens=200, cache_read_input_tokens=100,
                                                     cache_creation_input_tokens=100))


class Fake:
    def __init__(self, replies=(), n_in=1000):
        self.messages = _Msgs(replies, n_in)
        self.beta = SimpleNamespace(messages=self.messages)


def _desk(con, tmp_path, **settings):
    s = {"brain": "economy", "preset": "full", "telegram_send": False, "drop_watch": True, **settings}
    return Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, s, clock=lambda: NOW)


# --- egress -----------------------------------------------------------------------------------------------------------

def test_egress_blocks_identity_and_banking_lets_portfolio_go(con, tmp_path):
    p = tmp_path / "api_budget.toml"
    p.write_text('[egress]\nnames = ["Testname"]\n', encoding="utf-8")
    g = egress.load(con, p)
    assert "SB12345678" in g.ids and "12081600" in g.ids and "ZERODHA" not in g.ids     # a broker's name is not an id
    egress.check("AAA | equity | 12.5 | Rs 1,25,000 | +8.0\nBBB 4.1% of the portfolio; ZERODHA holdings", g)
    for bad, what in [("PAN ABCDE1234F", "PAN"), ("mail me at a.b@example.com", "e-mail"), ("call 9876543210", "phone"),
                      ("IFSC HDFC0001234", "IFSC"), ("pay to someone@oksbi", "UPI"), ("my account number is", "bank account"),
                      ("pin code near", "address"), ("for Testname only", "name"), ("from SB12345678", "id"),
                      ("depository 12081600", "id")]:
        with pytest.raises(egress.EgressBlocked, match="not sent"):
            egress.check(bad, g)
    with pytest.raises(egress.EgressBlocked, match="statement files never"):
        egress.check("ok", g, doc_kinds=("statement",))
    egress.check("ok", g, doc_kinds=("filing", "portfolio"))


# --- governor ---------------------------------------------------------------------------------------------------------

def test_cost_prices_cache_and_batch():
    assert gv.cost_inr(gv.OPUS, 1_000_000, 0, 1.0) == pytest.approx(4.0)
    assert gv.cost_inr(gv.HAIKU, 0, 1_000_000, 1.0) == pytest.approx(0.5)
    assert gv.cost_inr(gv.SONNET, 0, 0, 1.0, cache_read=1_000_000) == pytest.approx(0.2)
    assert gv.cost_inr(gv.OPUS, 0, 0, 1.0, cache_read=1_000_000) == pytest.approx(0.2)    # S70: Opus 5.5 reads at 0.05x ($0.20 of $4.00), not a tenth
    assert gv.cost_inr(gv.SONNET, 0, 0, 1.0, cache_write=1_000_000) == pytest.approx(2.5)
    assert gv.cost_inr(gv.OPUS, 1_000_000, 0, 90.0, batch=True) == pytest.approx(180.0)


def test_governor_limits_in_order(con):
    with pytest.raises(gv.BudgetRefused, match="input tokens"):
        gv.check(con, "reader", 0.1, 50_000, 100, NOW, "economy", CFG)
    with pytest.raises(gv.BudgetRefused, match="does not run"):
        gv.check(con, "brain", 1.0, 100, 100, NOW, "off", CFG)
    gv.check(con, "brain", 1.0, 100, 100, NOW, "economy", CFG)
    for k in range(4):                                       # economy: 2 brain passes a day (S70); four rows, for the month's sums below
        con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, "
                    "cost_inr, agent) VALUES (?,?,?,?,?,?,?,?,?,?)", [k + 1, NOW, "live", gv.OPUS, "q", "", "{}", "done", 5.0, "brain"])
    with pytest.raises(gv.BudgetRefused, match="calls today"):
        gv.check(con, "brain", 1.0, 100, 100, NOW, "economy", CFG)
    assert gv.check(con, "brain_rival", 1.0, 100, 100, NOW, "normal", CFG) == []
    with pytest.raises(gv.BudgetRefused, match="a day"):    # the layer's day: 20 spent + 101 > 120
        gv.check(con, "brain_rival", 101.0, 100, 100, NOW, "normal", CFG)
    con.execute("UPDATE api_calls SET created_at=? WHERE call_id < 4", [NOW - timedelta(days=3)])
    con.execute("UPDATE api_calls SET cost_inr=120 WHERE call_id < 4")    # month 365 of the brain's 375 (15% of 2,500; S70)
    with pytest.raises(gv.BudgetRefused, match="share"):
        gv.check(con, "brain_rival", 20.0, 100, 100, NOW, "normal", CFG)
    with pytest.raises(gv.BudgetRefused, match="cap"):      # the system cap, whatever the layer
        gv.check(con, "reader", 0.1, 100, 100, NOW, "economy", {**CFG, "cap": 300.0})



def test_his_own_question_is_not_held_by_the_brains_day_limits_but_the_month_and_cap_still_hold(con):
    for k in range(4):                                       # the brain's own passes used its day (4 passes, Rs 116)
        con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, "
                    "cost_inr, agent) VALUES (?,?,?,?,?,?,?,?,?,?)", [k + 1, NOW, "live", gv.OPUS, "q", "", "{}", "done", 29.0, "brain"])
    with pytest.raises(gv.BudgetRefused, match="calls today"):
        gv.check(con, "brain", 16.0, 100, 100, NOW, "economy", CFG)
    assert gv.check(con, "brain", 16.0, 100, 100, NOW, "economy", CFG, his_order=True) == []      # 2026-10-31: his question still runs
    con.execute("UPDATE api_calls SET cost_inr=249 WHERE call_id=1")                                 # month 336 of the brain's 1,000
    with pytest.raises(gv.BudgetRefused, match="cap"):
        gv.check(con, "brain", 16.0, 100, 100, NOW, "economy", {**CFG, "cap": 340.0}, his_order=True)

def test_spend_names_old_calls_by_how_they_were_made(con):
    rows = [(1, "web", gv.OPUS, "web", None, 9.0), (2, "batch", gv.SONNET, "AAA", "worker", 3.0),
            (3, "live", gv.SONNET, "workshop", None, 2.0), (4, "live", gv.HAIKU, "AAA", "reader", 0.01)]
    for cid, mode, model, topic, agent, inr in rows:
        con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, "
                    "status, cost_inr, agent) VALUES (?,?,?,?,?,?,?,?,?,?,?)", [cid, NOW, mode, model, topic, "q", "", "{}",
                                                                              "done", inr, agent])
    gv.log_refusal(con, "brain", gv.OPUS, "brain", "q", "over", NOW)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(an, "config", lambda: CFG)
        s = gv.spend(con, NOW)
    names = {a["agent"]: a for a in s["agents"]}
    assert set(names) == {"web search", "worker", "workshop (second writing)", "reader", "brain"}
    assert names["brain"]["over_limit"] == 1 and names["brain"]["month"] == 0
    assert s["month"] == pytest.approx(14.01) and s["cap"] == 2500.0


# --- the API road -------------------------------------------------------------------------------------------------------

def test_llm_call_gates_prices_logs_and_records(con):
    g = egress.Gate(names=["testname"])
    c = Fake(['{"ok": true}'])
    s = llm.call(con, "reader", {"model": gv.HAIKU, "max_tokens": 500, "messages": [{"role": "user", "content": "x"}]}, c,
                 now=NOW, mode="economy", private_text="", gate=g, doc_kinds=("filing",), topic="AAA", cfg=CFG)
    assert s.json() == {"ok": True} and "betas" not in c.messages.sent[0]          # Haiku: no server fallback
    row = con.execute("SELECT agent, status, input_tokens, output_tokens, cost_inr FROM api_calls").fetchone()
    assert row[:4] == ("reader", "done", 1000, 200)
    assert row[4] == pytest.approx(gv.cost_inr(gv.HAIKU, 800, 200, 90.0, 100, 100))
    c2 = Fake(['{}'])
    llm.call(con, "brain", {"model": gv.OPUS, "max_tokens": 500, "messages": []}, c2, now=NOW, mode="economy",
             private_text="AAA 10%", gate=g, cfg=CFG)
    assert c2.messages.sent[0]["fallbacks"] == "default"
    with pytest.raises(egress.EgressBlocked):              # blocked before it is even priced
        llm.call(con, "brain", {"model": gv.OPUS, "max_tokens": 500, "messages": []}, Fake([]), now=NOW, mode="economy",
                 private_text="for Testname", gate=g, cfg=CFG)
    with pytest.raises(gv.BudgetRefused):
        llm.call(con, "brain", {"model": gv.OPUS, "max_tokens": 50_000, "messages": []}, Fake([]), now=NOW,
                 mode="economy", private_text="", gate=g, cfg=CFG)
    assert con.execute("SELECT count(*) FROM api_calls WHERE status='over_limit' AND agent='brain'").fetchone()[0] == 1


# --- board and receptionist ----------------------------------------------------------------------------------------------

def test_board_runs_hands_on_and_holds_long_chains(con, tmp_path):
    rt = _desk(con, tmp_path)
    sent = []
    agents = {"a": lambda rt, t: Reply("A did it", ["a"], then=[("b", "next")]),
              "b": lambda rt, t: Reply("B did it", ["b"], then=[("b", "again")]),
              "bad": lambda rt, t: 1 / 0}
    tid = board.post(con, "a", "start", NOW, channel="telegram")
    n = board.run_all(rt, agents, deliver=lambda t: sent.append(t["id"]), max_n=10)
    rows = board.recent(con, 10)
    by = {r["id"]: r for r in rows}
    assert by[tid]["status"] == "done" and by[tid]["result"] == "A did it" and by[tid]["replied"] is not None
    assert [r["hops"] for r in sorted(rows, key=lambda r: r["id"])] == [0, 1, 2, 3, 4]
    last = max(rows, key=lambda r: r["id"])
    assert last["to"] == "brain" and last["status"] == "held" and last["body"]["meant_for"] == "b"
    assert n == 4 and all(by[i]["channel"] == "telegram" for i in by) and len(sent) == 4
    bid = board.post(con, "bad", "x", NOW)
    board.run_one(rt, agents)
    assert board.get(con, bid)["status"] == "failed" and "ZeroDivisionError" in board.get(con, bid)["result"]
    con.execute("UPDATE hq_tasks SET status='running' WHERE task_id=?", [bid])
    assert board.reap(con, NOW) == 1


def test_reception_routes_by_fixed_rules():
    r = reception.route
    assert r("/calc CAGR of NIFTY since 2020") == ("calc", "CAGR of NIFTY since 2020")
    assert r("/order quant does momentum predict returns") == ("quant", "does momentum predict returns")
    assert r("/deep why did AAA fall") == ("research", "why did AAA fall")
    assert r("/nonsense")[0] == ""
    assert r("remind me to file taxes tomorrow at 9")[0] == "messenger"
    assert r("I decided AAA: hold through the results")[0] == "memory"
    assert r("run a stress test on my mix")[0] == "sim"
    assert r("analyse the tijori export")[0] == "analysis"
    assert r("what is my net worth")[0] == "ask"
    assert reception.is_hq_command("/sim 1 year") and not reception.is_hq_command("/networth")
    assert reception.item_ref("look at #12 please") == 12 and reception.item_ref("item 7") == 7


# --- messenger --------------------------------------------------------------------------------------------------------

def test_reminder_times_from_words():
    w = messenger.when
    assert w("remind me in 2 hours", NOW) == NOW + timedelta(hours=2)
    assert w("remind me tomorrow at 9", NOW) == datetime(2026, 10, 27, 9, 0)
    assert w("ping me at 5pm", NOW) == datetime(2026, 10, 26, 17, 0)
    assert w("ping me at 8am", NOW) == datetime(2026, 10, 27, 8, 0)            # already past today: tomorrow
    assert w("remind me on friday", NOW) == datetime(2026, 10, 30, 9, 0)
    assert w("remind me on 3 Nov at 4pm", NOW) == datetime(2026, 11, 3, 16, 0)
    assert w("remind me to check the results", NOW) is None
    assert messenger.what("remind me to check AAA results tomorrow") == "check AAA results tomorrow"


def test_reminders_sent_once_through_the_outbox(con, tmp_path):
    rt = _desk(con, tmp_path)
    messenger.add(con, "call the bank", NOW - timedelta(minutes=1), NOW)
    messenger.add(con, "later", NOW + timedelta(days=1), NOW)
    assert messenger.due(rt) == 1 and messenger.due(rt) == 0
    assert con.execute("SELECT kind, status, text FROM outbox").fetchall() == [("reminder", "pending", "Reminder: call the bank")]
    assert [r[1] for r in messenger.upcoming(con)] == ["later"]


# --- drop folder ---------------------------------------------------------------------------------------------------------

def test_drop_folder_files_reach_the_inbox_once_settled(con, tmp_path, monkeypatch):
    from pflab.app import inbox as ib
    from pflab.hq import watcher
    rt = _desk(con, tmp_path)
    got = []
    monkeypatch.setattr(ib, "receive", lambda rt, name, data, *a, **k: got.append((name, data)) or {"id": len(got)})
    d = watcher.folder(rt.repo)
    assert watcher.scan(rt) == [] and (d / "taken").exists()             # created on first look
    (d / "tradebook-AB.csv").write_bytes(b"a,b\n1,2\n")
    (d / "half.pdf.crdownload").write_bytes(b"x")
    (d / "fresh.pdf").write_bytes(b"y")
    old = time.time() - 60
    os.utime(d / "tradebook-AB.csv", (old, old))
    os.utime(d / "half.pdf.crdownload", (old, old))
    out = watcher.scan(rt)
    assert out == [{"name": "tradebook-AB.csv", "item": 1, "duplicate": False}] and got[0][0] == "tradebook-AB.csv"
    assert (d / "taken" / "tradebook-AB.csv").exists() and not (d / "tradebook-AB.csv").exists()
    assert (d / "fresh.pdf").exists() and (d / "half.pdf.crdownload").exists()
    watcher.announce(rt, out)
    assert "tradebook-AB.csv" in con.execute("SELECT text FROM outbox WHERE kind='inbox'").fetchone()[0]


# --- readers --------------------------------------------------------------------------------------------------------------

def test_figures_kept_only_when_found_in_the_document():
    text = "Revenue from operations rose to Rs 1,234.5 crore in Q2 FY27, up from 1,100 crore."
    figs = [{"name": "revenue", "value": "1,234.5", "unit": "crore", "period": "Q2", "quote": "rose to Rs 1,234.5 crore"},
            {"name": "profit", "value": "99", "unit": "crore", "period": "Q2", "quote": "profit 99"},
            {"name": "prior", "value": "1100", "unit": "crore", "period": "Q2 FY26", "quote": "up from 1,100 crore"},
            {"name": "wrong quote", "value": "1,100", "unit": "crore", "period": "", "quote": "rose to Rs 1,234.5 crore"}]
    keep, dropped = readers.check_figures(figs, text)
    assert [f["name"] for f in keep] == ["revenue", "prior"] and dropped == 2


def test_figures_checked_on_the_page_they_name():
    text = "[page 1]\nNotice of the board meeting.\n[page 2]\nRevenue rose to Rs 1,234.5 crore."
    figs = [{"name": "rev", "value": "Rs 1,234.5 crore", "page": "page 2", "quote": "rose to Rs 1,234.5 crore"},
            {"name": "page said wrong", "value": "1,234.5", "page": "1", "quote": "Rs 1,234.5 crore"},
            {"name": "no quote", "value": "1,234.5", "page": "2", "quote": ""},
            {"name": "number not in its quote", "value": "99", "page": "2", "quote": "rose to Rs 1,234.5 crore"}]
    keep, gone = readers.split_figures(figs, text)
    assert [(f["name"], f["page"]) for f in keep] == [("rev", "2"), ("page said wrong", "2")]   # the page is code's
    assert [f["name"] for f in gone] == ["no quote", "number not in its quote"]


def test_filing_attachment_read_by_page(con, tmp_path, monkeypatch):
    import pypdf
    from pflab.kg import graph as g
    d = g.doc(con, "filing", "f1", NOW, "AAA: Outcome of board meeting", url="https://www.bseindia.com/x/a.pdf", source="BSE",
              attrs={"category": "Result", "subcategory": "Financial Results"})
    g.edge(con, d, "about", f"company:{AAA}", NOW, "test")
    pages = [SimpleNamespace(extract_text=lambda: "Board approved results."),
             SimpleNamespace(extract_text=lambda: "Revenue Rs 1,234.5 crore for the quarter.")]
    monkeypatch.setattr(pypdf, "PdfReader", lambda f: SimpleNamespace(pages=pages))
    row = readers.pending(con, NOW.date(), [AAA], [], stock_list=[])[0]
    text = readers.fetch_filing_text(con, row, tmp_path / "text", get=lambda u: SimpleNamespace(status_code=200, content=b"%PDF"))
    assert text.startswith("[page 1]") and "[page 2]\nRevenue" in text
    assert con.execute("SELECT text_status FROM kg_docs WHERE doc_id=?", [d]).fetchone()[0] == "ok"
    body = readers.doc_text(row)
    assert "BSE category: Result / Financial Results" in body and "[page 2]" in body
    assert readers.fetch_filing_text(con, {"doc_id": d, "url": "https://b/y.html"}, tmp_path) is None   # not a PDF
    assert readers.fetch_filing_text(con, {"doc_id": d, "url": "https://b/x.pdf"}, tmp_path,
                                     get=lambda u: SimpleNamespace(status_code=404, content=b"")) is None
    assert con.execute("SELECT text_status FROM kg_docs WHERE doc_id=?", [d]).fetchone()[0] == "fetch_error"


def test_readers_read_held_first_and_keep_readings(con, tmp_path, monkeypatch):
    from pflab.kg import graph as g
    (tmp_path / "api_budget.toml").write_text("[api]\nmonthly_cap_rupees = 2500\ndev_monthly_cap_rupees = 100\nask_above_rupees = 50\nadopted = true\n",
                                              encoding="utf-8")
    monkeypatch.setattr(store, "pm_dir", lambda: tmp_path)          # its own budget, not the workshop's store folder
    for k, (isin, kind, title) in enumerate([(BBB, "filing", "BBB: trading window closure"),
                                             (AAA, "filing", "AAA wins order worth Rs 500 crore"),
                                             (AAA, "article", "Weather today")]):
        d = g.doc(con, kind, f"k{k}", NOW - timedelta(hours=k + 1), title, source="BSE")
        g.edge(con, d, "about", f"company:{isin}", NOW, "test")
    rows = readers.pending(con, NOW.date(), [AAA], [BBB], stock_list=[])
    assert [r["title"] for r in rows] == ["AAA wins order worth Rs 500 crore", "BBB: trading window closure"]
    c = Fake([{"material": "yes", "why": "a large order", "summary": "AAA won an order.",
               "figures": [{"name": "order", "value": "500", "unit": "crore", "period": "", "quote": "worth Rs 500 crore"},
                           {"name": "made up", "value": "42", "unit": "", "period": "", "quote": ""}]},
              {"material": "no", "why": "routine", "summary": "Trading window.", "figures": []}])
    rep = readers.run(con, NOW.date(), c, egress.Gate(), NOW, "economy", [AAA], [BBB], stock_list=[])
    assert rep["read"] == 2 and rep["material"] == 1 and len(rep["material_held"]) == 1, rep
    sent = c.messages.sent[0]
    assert sent["model"] == gv.HAIKU and sent["output_config"]["format"]["type"] == "json_schema"
    r = readers.recent(con, NOW - timedelta(days=1))
    assert len(r) == 1 and r[0]["isins"] == [AAA] and [f["name"] for f in r[0]["figures"]] == ["order"]
    assert con.execute("SELECT count(*) FROM kg_docs WHERE kind='reading'").fetchone()[0] == 2
    assert readers.pending(con, NOW.date(), [AAA], [BBB], stock_list=[]) == []          # read once


# --- brain ------------------------------------------------------------------------------------------------------------

@pytest.fixture
def brain_input(monkeypatch):
    monkeypatch.setattr(brain, "portfolio_view", lambda con, asof: ("PORTFOLIO: AAA | equity | 60.0 | Rs 6,00,000 | +12.0",
                                                                    {"AAA": AAA}))
    monkeypatch.setattr(brain, "watch_view", lambda con: ("WATCH LIST: BBB", {"BBB": BBB}))


def test_brain_predictions_checked_by_code():
    syms = {"AAA": AAA, "BBB": BBB}
    pr, problem = brain.check_prediction({"symbol": "aaa", "kind": "return_below", "level": -5, "due": "2026-11-20",
                                          "confidence": 0.6, "claim": "AAA falls 5%"}, syms, NOW)
    assert problem is None and pr["symbol"] == "AAA" and pr["isin"] == AAA and pr["due"] == date(2026, 11, 20)
    for p, why in [({"symbol": "ZZZ", "kind": "return_above", "level": 5, "due": "2026-11-20", "confidence": 0.6}, "ZZZ"),
                   ({"symbol": "BBB", "kind": "return_above", "level": 5, "due": "2026-10-27", "confidence": 0.6}, "outside"),
                   ({"symbol": "BBB", "kind": "up", "level": 5, "due": "2026-11-20", "confidence": 0.6}, "kind"),
                   ({"symbol": "BBB", "kind": "return_above", "level": 5, "due": "soon", "confidence": 0.6}, "unreadable"),
                   ({"symbol": "BBB", "kind": "return_above", "level": 5, "due": "2026-11-20", "confidence": 1.2}, "range")]:
        assert brain.check_prediction(p, syms, NOW)[1] and why in brain.check_prediction(p, syms, NOW)[1]


def test_brain_wakes_only_on_new_material_events(con, tmp_path, brain_input, monkeypatch):
    from pflab.app import system
    monkeypatch.setattr(system, "stale_prices", lambda con_, now_: None)       # S67 has its own test: old prices stop a pass (test_s67_cycle)
    rt = _desk(con, tmp_path, brain="off")
    assert brain.wake(rt, Fake(), egress.Gate(), held=[AAA], listed=[BBB], cfg=CFG)["pass"] is None
    rt.settings["brain"] = "economy"
    rt.clock = lambda: datetime(2026, 10, 25, 10, 0)             # a Sunday: no morning review
    assert brain.wake(rt, Fake(), egress.Gate(), held=[AAA], listed=[BBB], cfg=CFG)["why"] == "nothing new"
    con.execute("INSERT INTO research_flags VALUES (1, ?, 'AAA', 'fall', ?, ?, 'r1', 'AAA fell 9% in 5 sessions on its own')",
                [AAA, rt.clock(), rt.clock()])
    r = brain.wake(rt, Fake([{"wake": False, "why": "minor"}]), egress.Gate(), held=[AAA], listed=[BBB], cfg=CFG)
    assert r["pass"] is None and "minor" in r["why"]
    assert brain.wake(rt, Fake(), egress.Gate(), held=[AAA], listed=[BBB], cfg=CFG)["why"] == "nothing new"   # seen once
    _prices(con, AAA, date(2023, 1, 2), 100 + np.cumsum(np.random.default_rng(1).normal(0, 1, 980)))
    con.execute("INSERT INTO research_flags VALUES (2, ?, 'AAA', 'results', ?, ?, 'r2', 'AAA filed results')",
                [AAA, rt.clock(), rt.clock()])
    c = Fake([{"wake": True, "why": "results"}, "AAA filed results.", "AAA filed results."])   # S60: the note, no tools
    r = brain.wake(rt, c, egress.Gate(), held=[AAA], listed=[BBB], cfg=CFG)
    assert r["trigger"] == "events" and r["pass"] and r["rival"]
    assert [m["model"] for m in c.messages.sent] == [gv.HAIKU, gv.OPUS, gv.SONNET]
    blocks = c.messages.sent[1]["messages"][0]["content"]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"} and "AAA filed results" in blocks[1]["text"]
    assert c.messages.sent[1]["tools"] and c.messages.sent[2]["tools"] == c.messages.sent[1]["tools"]   # the same tools
    j = brain.journal(con)
    assert [p["role"] for p in j[:3]] == ["rival", "brain", "gate"] and j[1]["note"] == "AAA filed results."
    assert con.execute("SELECT count(*) FROM hq_tasks").fetchone()[0] == 0          # shadow: nothing acted on
    brain.mark(con, j[1]["id"], False, rt.clock())
    brain.mark(con, j[1]["id"], True, rt.clock())                                   # his latest mark stands
    assert brain.journal(con)[1]["mattered"] is True and brain.journal(con)[0]["mattered"] is None
    assert not [e for e in brain.events(con, rt.clock() - timedelta(hours=1), rt.clock(), [AAA], [BBB])
                if e["key"].startswith("memory:")]                                  # a mark never wakes the brain


def test_scheduled_passes_once_each():
    class C:
        def __init__(self, rows):
            self.rows = rows

        def execute(self, q, a):
            return SimpleNamespace(fetchone=lambda: (1,) if any(t in q for t in self.rows) else None)
    assert brain.due_scheduled(C([]), datetime(2026, 10, 26, 8, 0)) is None
    assert brain.due_scheduled(C([]), datetime(2026, 10, 26, 9, 0)) == "morning"
    assert brain.due_scheduled(C(["'morning'"]), datetime(2026, 10, 26, 9, 0)) is None
    worked = "trigger <> 'reflection'"
    assert brain.due_scheduled(C([]), datetime(2026, 10, 31, 9, 30)) is None             # no pass this week: nothing to reflect on
    assert brain.due_scheduled(C([worked]), datetime(2026, 10, 31, 9, 30)) == "reflection"
    assert brain.due_scheduled(C([worked, "trigger='reflection'"]), datetime(2026, 10, 31, 9, 30)) is None   # once


# --- memory keeper -------------------------------------------------------------------------------------------------------

def test_predictions_scored_after_they_were_made(con):
    _prices(con, AAA, date(2026, 10, 1), [100.0] * 18 + [110.0] * 8)
    pid = keeper.add_prediction(con, 1, gv.OPUS, {"isin": AAA, "symbol": "AAA", "kind": "return_above", "level": 5.0,
                                                   "due": date(2026, 11, 2), "confidence": 0.7, "claim": "AAA +5%"},
                                datetime(2026, 10, 20, 18, 0))
    row = con.execute("SELECT base_rate, check_json FROM hq_predictions WHERE pred_id=?", [pid]).fetchone()
    assert row[0] is None and json.loads(row[1])["ref_close"] == 100.0          # under 250 windows: no base rate
    assert keeper.score_due(con, datetime(2026, 10, 30)) == 0                   # not due yet
    assert keeper.score_due(con, datetime(2026, 11, 3)) == 1
    out, detail = con.execute("SELECT outcome, detail FROM hq_predictions").fetchone()
    assert out is True and "+10.00%" in detail
    sc = keeper.scorecard(con)["models"][gv.OPUS]
    assert sc["n"] == 1 and sc["brier"] == pytest.approx(0.09)
    assert "1 of 1" in keeper.scorecard_text(con, gv.OPUS) and "too few" in keeper.scorecard_text(con, gv.OPUS)


def test_base_rate_counts_the_stocks_own_history():
    import pandas as pd
    s = pd.Series(np.r_[np.full(300, 100.0), np.full(300, 120.0)], index=pd.bdate_range("2023-01-02", periods=600))
    br = keeper.base_rate(s, 5, "return_above", 10.0)
    assert br == pytest.approx(5 / 595)                                          # only the 5 windows over the jump
    assert keeper.base_rate(s[:200], 5, "return_above", 10.0) is None


def test_decisions_followed_up_and_notes_tidied(con):
    from pflab.agents import memory as mem
    _prices(con, AAA, date(2026, 10, 1), [100.0] * 10 + [92.0] * 6)
    mem.remember(con, "decision", "hold through the results", subject="AAA", now=datetime(2026, 10, 5, 12))
    mem.remember(con, "decision", "something", subject="Not a symbol", now=datetime(2026, 10, 5, 12))
    for k in range(3):
        mem.remember(con, "note", f"note {k}", subject="AAA", source=f"analyst call #{k}", now=datetime(2026, 10, 1 + k))
    fu = keeper.followups(con, date(2026, 10, 26))
    a = next(f for f in fu if f["subject"] == "AAA")
    assert a["since"]["change_pct"] == pytest.approx(-8.0)
    assert next(f for f in fu if f["subject"] == "Not a symbol")["unknown_subject"]
    assert keeper.tidy_notes(con, NOW) == 2 and keeper.tidy_notes(con, NOW) == 0


def test_filings_reach_the_analyst_through_a_flood_of_news():
    words = ["alpha", "beta", "gamma", "delta", "omega", "sigma", "kappa"]
    rows = [("article", datetime(2026, 10, 20, h), f"AAA story {words[h % 7]}!", "", "", None, None) for h in range(20)]
    rows += [("filing", datetime(2026, 10, k, 9), f"AAA filing {k}", "", "", None, None) for k in range(1, 10)]
    rows += [("result", datetime(2026, 8, 1), "AAA results", "", "", None, None)]
    rows.sort(key=lambda r: r[1], reverse=True)
    out = an.balanced(rows, 12)
    kinds = [r[0] for r in out]
    assert kinds.count("filing") == 6 and kinds.count("result") == 1 and kinds.count("article") == 5
    assert len({an.same_story(r[2]) for r in out if r[0] == "article"}) == 5          # one per story
    assert [r[1] for r in out] == sorted((r[1] for r in out), reverse=True)


def test_readers_skip_bare_headlines_and_stories_already_read(con, tmp_path):
    from pflab.kg import graph as g
    con.execute("UPDATE instruments SET name='AAA Limited' WHERE isin=?", [AAA])
    p = tmp_path / "t.txt"
    p.write_text("AAA wins a big order.", encoding="utf-8")
    for k, title in enumerate(["AAA wins big order", "aaa wins big order!", "AAA bare headline only"]):
        d = g.doc(con, "article", f"a{k}", NOW - timedelta(hours=k + 1), title, url=f"https://x.in/{k}")
        g.edge(con, d, "about", f"company:{AAA}", NOW, "test")
        if k < 2:
            con.execute("UPDATE kg_docs SET text_path=?, text_status='ok' WHERE doc_id=?", [str(p), d])
    rows = readers.pending(con, NOW.date(), [AAA], [], stock_list=[{"symbol": "AAA", "isin": AAA, "aliases": ["aaa"]}])
    assert [r["title"] for r in rows] == ["AAA wins big order"]                      # the copy and the bare one skipped


def test_web_answers_keep_dates_but_not_uncited_figures():
    cite = SimpleNamespace(url="https://x.in/a", title="A")
    msg = SimpleNamespace(content=[
        SimpleNamespace(type="text", text="From 1 April 2026, in October 2026 and on Nov 3, ", citations=None),
        SimpleNamespace(type="text", text="the cap fell to 0.90%", citations=[cite]),
        SimpleNamespace(type="text", text=" and fees fell 12%.", citations=None)])
    text, sources, dropped = an.web_cited(msg)
    assert text.startswith("From 1 April 2026") and "0.90% [W1]" in text and "12%" not in text and dropped == 1
    assert sources == [(1, "A", "https://x.in/a")] and an.WEB_TOOL == "web_search_20250305"


# --- workers ------------------------------------------------------------------------------------------------------------

def test_company_notes_are_sonnet_work_in_the_batch(con, monkeypatch):
    from pflab.agents import researcher as rs
    seen = []

    def ring(con, req, client, now, reuse=True, cfg=None):
        seen.append(cfg["model"])
        cid = an._log(con, req, "batch", cfg["model"], "queued", now, {"x": 1}, 0.5)
        return an.Outcome("queued", "", cid, 0.5)
    monkeypatch.setattr(an, "ring", ring)
    monkeypatch.setattr(an, "config", lambda: CFG)
    con.execute("INSERT INTO research_flags VALUES (1, ?, 'AAA', 'results', ?, ?, 'r', 'filed')", [AAA, NOW, NOW])
    out = rs.deep_queue(con, NOW.date(), [{"symbol": "AAA", "isin": AAA}], client=object(), now=NOW)
    assert out == {"AAA": "queued"} and seen == [an.SONNET]
    assert con.execute("SELECT agent, model FROM api_calls").fetchone() == ("worker", an.SONNET)


def test_batch_results_priced_at_the_calls_own_model(con):
    req = an.Request("What changed?", "AAA", [], [AAA])
    cid = an._log(con, req, "batch", an.SONNET, "submitted", NOW, {"messages": [{"content": [{"type": "text", "text": "q"}]}]})
    con.execute("UPDATE api_calls SET batch_id='b1' WHERE call_id=?", [cid])
    msg = SimpleNamespace(content=[SimpleNamespace(type="text", text="Revenue rose.", citations=None)], stop_reason="end_turn",
                          usage=SimpleNamespace(input_tokens=1000, output_tokens=1000))
    client = SimpleNamespace(messages=SimpleNamespace(batches=SimpleNamespace(
        retrieve=lambda b: SimpleNamespace(processing_status="ended"),
        results=lambda b: [SimpleNamespace(custom_id=f"call-{cid}", result=SimpleNamespace(type="succeeded", message=msg))])))
    assert an.collect_batches(con, client, cfg=CFG, now=NOW)["done"] == 1
    assert con.execute("SELECT cost_inr FROM api_calls").fetchone()[0] == pytest.approx((1000 * 2 + 1000 * 10) / 1e6 * 0.5 * 90)


# --- phone and rounds ---------------------------------------------------------------------------------------------------

def test_phone_posts_orders_and_keeps_the_bots_commands(con, tmp_path, monkeypatch):
    from pflab.hq import phone
    from pflab.service import bot
    rt = _desk(con, tmp_path)
    monkeypatch.setattr(bot, "handle", lambda con, t, asof, **k: f"bot: {t}")
    assert "on it (task #1)" in phone.reply_for(rt, "/calc CAGR of NIFTY 50 since 2020")
    assert "on it (task #2)" in phone.reply_for(rt, "remind me to call tomorrow at 9")
    assert phone.reply_for(rt, "/networth") == "bot: /networth"
    assert "/calc" in phone.reply_for(rt, "/help") and "Simulation" in phone.reply_for(rt, "/agents")
    assert phone.reply_for(rt, "/order nobody hi").startswith("No agent")
    t = board.recent(con)
    assert [(x["to"], x["channel"]) for x in reversed(t)] == [("calc", "telegram"), ("messenger", "telegram")]


def test_round_runs_orders_and_free_work_without_paid_agents(con, tmp_path, monkeypatch):
    from pflab.hq import service
    monkeypatch.setattr(an, "config", lambda: {**CFG, "cap": 0.0})
    rt = _desk(con, tmp_path)
    board.post(con, "messenger", "remind me to check AAA in 1 hour", NOW)
    out = service.round_(rt, attended=False)
    assert out["board"] == 1 and "readers" not in out and "brain" not in out
    assert con.execute("SELECT text FROM hq_reminders").fetchone()[0] == "check AAA in 1 hour"
    assert out["keeper"]["scored"] == 0


def test_settings_brain_switch_and_light_preset(tmp_path):
    from pflab.app import settings as st
    from pflab.service import jobs, tasks  # noqa: F401
    assert st.load(tmp_path)["brain"] == "economy"
    assert st.save(tmp_path, {"brain": "normal"})["brain"] == "normal"
    assert st.save(tmp_path, {"brain": "always"})["brain"] == "normal"                 # not a choice: ignored
    assert "hq" in st.jobs_for("light", jobs.REGISTRY) and list(jobs.REGISTRY)[-1] == "conductor"
