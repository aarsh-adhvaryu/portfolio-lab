"""S67 (2026-10-30, after his first real use): the record builds itself and never waits for a perfect set of files.
A missing tradebook, funds ledger or depository statement is a named difference, not a reason to write nothing; a Zerodha pay-in no bank
statement shows is booked from the Console ledger and named; the differences become gaps and ONE request saying what closes each; the
accounts are set up from the files by themselves; his choices survive a fresh start; Kite's holdings feed the research until the statements
are read; a card purchase is spending, not a question. Synthetic files only."""
from __future__ import annotations

import importlib.util
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from pflab.agents import questions
from pflab.app import inbox as ib, readiness, runtime
from pflab.pm import store

NOW = datetime(2026, 10, 30, 21, 0)
REPO = Path(__file__).resolve().parents[1]


def _bpl():
    spec = importlib.util.spec_from_file_location("bpl_test", REPO / "tools" / "build_pm_ledger.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _funds_ledger(path: Path, rows, opening=0.0):
    """A Console funds ledger as Console writes it: a header row, an opening and a closing balance, running balances."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Particulars", "Posting Date", "Cost Center", "Voucher Type", "Debit", "Credit", "Net Balance"])
    ws.append(["Opening Balance", None, None, None, None, None, opening])
    bal = opening
    for part, d, vt, dr, cr in rows:
        bal = bal + cr - dr
        ws.append([part, d.strftime("%Y-%m-%d"), "", vt, dr, cr, bal])
    ws.append(["Closing Balance", None, None, None, None, None, bal])
    wb.save(path)


SRC = {"start": date(2026, 4, 1), "zerodha": {"account": "ZER", "tradebooks": [], "contract_notes_xlsx": []}, "bank": [], "cas": {"files": []},
       "accounts": {"ZER": {"kind": "broker", "provider": "Zerodha"}}}


def test_nothing_but_a_setup_still_builds_and_names_every_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path / "pm"))
    log, led, checks, notes, src = _bpl().build(dict(SRC), tmp_path)
    failed = {n for n, ok, _ in checks if not ok}
    assert len(log) == 0 and {"a Console tradebook is given", "a Console funds ledger is given", "a depository statement (CAS) is given"} <= failed
    assert any(p["kind"] == "start" for p in src["_periods"])


def test_a_pay_in_no_bank_statement_shows_is_booked_from_the_console_ledger_and_named(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path / "pm"))
    _funds_ledger(tmp_path / "ledger.xlsx", [("Funds added using UPI", date(2026, 8, 24), "Bank Receipts", 0.0, 50_000.0),
                                             ("Funds withdrawn", date(2026, 10, 16), "Bank Payments", 20_000.0, 0.0)])
    src = {**SRC, "zerodha": {**SRC["zerodha"], "funds_ledger": "ledger.xlsx"}}
    log, led, checks, notes, _ = _bpl().build(src, tmp_path)
    by = {n: (ok, d) for n, ok, d in checks}
    assert by["Zerodha cash = Console closing balance"][0] is True                             # Zerodha's cash is whole: 30,000
    assert by["every Zerodha pay-in and payout is in a bank statement"][0] is False
    assert "2026-08-24 +50,000.00" in by["every Zerodha pay-in and payout is in a bank statement"][1]
    assert sorted(e.kind for e in log) == ["deposit", "withdrawal"]


def test_differences_are_gaps_and_one_request_that_is_replaced_and_closed(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    checks = [("every trade has a contract note", False, "26 trades"), ("SBI cash = statement closing", True, ""),
              ("every Zerodha pay-in and payout is in a bank statement", False, "2026-10-26 +5,000.00")]
    assert ib.record_differences(con, checks, 1451, NOW) == 2
    q = [t for _, _, t in questions.open_questions(con)]
    assert len(q) == 1 and "1451 entries" in q[0] and "contract notes" in q[0] and "bank statement that shows" in q[0]
    assert {g["key"] for g in readiness.gaps(con, "ledger")} == {"ledger:diff:every-trade-has-a-contract-note",
                                                                 "ledger:diff:every-zerodha-pay-in-and-payout-is-in-a-bank-statement"}
    ib.record_differences(con, [(n, n != "every trade has a contract note", d) for n, _, d in checks], 1460, NOW)   # the pay-in arrived
    assert [g["key"] for g in readiness.gaps(con, "ledger")] == ["ledger:diff:every-trade-has-a-contract-note"]
    assert len(questions.open_questions(con)) == 1 and "1460 entries" in questions.open_questions(con)[0][2]
    ib.record_differences(con, [(n, True, d) for n, _, d in checks], 1470, NOW)
    assert readiness.gaps(con, "ledger") == [] and questions.open_questions(con) == []


def test_the_ledger_job_sets_up_the_accounts_builds_and_writes_without_a_press(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from pflab.ingest import setup_sources as su
    from pflab.service import jobs
    import pflab.service.tasks as tasks
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(ib, "_start", lambda rt_, iid: ib._process(rt_, iid))
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)
    ib.receive(rt, "tradebook-ZZ.csv", b"trade rows", hint="tradebook")
    assert con.execute("SELECT status FROM inbox_items").fetchone()[0] == "awaiting setup"
    monkeypatch.setattr(su, "infer", lambda con_, today: {"answers": {"start": "2026-04-01", "broker": {"account": "ZER"}, "demats": [],
                                                                      "banks": [{"name": "SBI_9001", "bank": "SBI", "last4": "9001"}]}})
    written = {}

    def build(src, root):
        return ["e1", "e2"], None, [("every trade has a contract note", False, "2 trades"), ("SBI_9001 cash = statement closing", True, "")], [], src
    monkeypatch.setattr(ib, "_builder", lambda rt_: SimpleNamespace(build=build, write=lambda c, log, led, src: written.update(n=len(log))))
    ctx = jobs.Ctx(con, NOW, tmp_path / "pm", tmp_path / "data", tmp_path)
    assert tasks._ledger_wanted(ctx)[0] is True
    r = jobs.run_job(ctx, jobs.REGISTRY["ledger"])
    assert r.status == "ok" and written == {"n": 2} and (tmp_path / "pm" / "sources.toml").exists()
    assert con.execute("SELECT status FROM inbox_items").fetchone()[0] == "in the ledger"
    asked = " | ".join(t for _, _, t in questions.open_questions(con))
    assert "I set up your accounts" in asked and "2 entries" in asked and "contract notes" in asked
    assert tasks._ledger_wanted(ctx)[0] is False and jobs.run_job(ctx, jobs.REGISTRY["ledger"]).status == "skipped"


def test_his_choices_survive_a_fresh_start_and_come_back_to_a_profile_that_lost_them(tmp_path):
    from pflab.pm import fresh
    old = tmp_path / "pm_old_20261030"
    old.mkdir()
    for name in ("api_budget.toml", "targets.toml", "stock_list.toml"):
        (old / name).write_text(f"# {name}\n", encoding="utf-8")
    store.connect(old / "ledger.duckdb").close()
    new = tmp_path / "pm"
    out = fresh.new_profile(new, old / "ledger.duckdb", "p")
    assert out["choices"] == 3 and (new / "targets.toml").exists() and (new / "stock_list.toml").exists()
    lost = tmp_path / "pm2"
    lost.mkdir()
    (tmp_path / "pm2_old_20261030").mkdir()
    (tmp_path / "pm2_old_20261030" / "api_budget.toml").write_text("adopted = true\n", encoding="utf-8")
    assert fresh.restore_missing_choices(lost) == ["api_budget.toml from pm2_old_20261030"]
    assert (lost / "api_budget.toml").read_text(encoding="utf-8") == "adopted = true\n" and fresh.restore_missing_choices(lost) == []


def test_kite_holdings_feed_the_research_until_the_statements_are_read(tmp_path):
    from pflab.kg import build as kb
    from pflab.pm import today
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("INSERT INTO kite_snapshots (snap_id, taken_at, account_id, kind, isin, symbol, qty) VALUES (1, ?, 'KITE', 'holding', 'INE000A01011', 'AAA', 5)", [NOW])
    assert today.kite_held(con) == {"INE000A01011"}
    assert list(kb.universe(con, [])["isin"]) == ["INE000A01011"]


def test_a_card_purchase_is_spending_not_a_question():
    from pflab.ingest import bank_labels as bl
    df = pd.DataFrame({"date": [date(2026, 9, 1)] * 3, "description": ["POS ATM PURCH OTHPG 5306 AMAZON", "UPI-RAVI KUMAR-RAVI@OKSBI", "ECOM PUR SHOP"],
                       "debit": [500.0, 30_000.0, 200.0], "credit": [0.0] * 3, "category": ["unclassified"] * 3, "rule_id": [None] * 3,
                       "ref_id": ["a", "b", "c"]})
    out, rep = bl.auto_label({"A": df})
    assert list(out["A"]["category"]) == ["spend", "unclassified", "spend"] and rep["card_spend"] == 2


def test_money_the_broker_spent_with_no_source_in_the_files_is_funded_and_named_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path / "pm"))
    _funds_ledger(tmp_path / "ledger.xlsx", [("DP charges", date(2026, 9, 3), "Journal Entry", 100.0, 0.0)])
    src = {**SRC, "zerodha": {**SRC["zerodha"], "funds_ledger": "ledger.xlsx"}}
    log, led, checks, notes, _ = _bpl().build(src, tmp_path)                                  # before 2026-10-30: CashError, nothing built
    by = {n: (ok, d) for n, ok, d in checks}
    assert by["every rupee Zerodha spent has a source in your files"][0] is False and "2026-09-03 100.00" in by["every rupee Zerodha spent has a source in your files"][1]
    assert any(e.ref.startswith("unexplained_funding:") for e in log)


def test_research_spends_nothing_on_a_text_that_names_no_company_and_names_the_company_when_there_is_one(tmp_path, monkeypatch):
    """Found on his first use: a broker's rulebook was sent to Opus and checked against unrelated filings (Rs 1.76, nothing learned)."""
    from pflab.app import chat
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES ('INE000Z01011', 'isin', 'equity', 'listed_equity', TRUE, 'ZEDCO', 'Zedco Consultancy Services Limited', 'synthetic', now()),
                          ('INE000N01011', 'isin', 'equity', 'listed_equity', TRUE, 'NSE', 'National Stock Exchange of India Limited', 'synthetic', now())""")
    monkeypatch.setattr("pflab.plan.guards.stock_list", lambda path=None: [])
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)
    sent = []
    monkeypatch.setattr(chat, "post", lambda rt_, cid, q, mode, approved=False: sent.append((q, mode)) or {"chat_id": 1})
    texts = iter(["Important: stocks under surveillance move to the T2T segment; check the NSE and BSE lists; price band 5%.",
                  "Zedco Consultancy Services announces its second interim dividend of Rs 12 per share."])
    monkeypatch.setattr(ib, "ocr", lambda rt_, path: next(texts))
    monkeypatch.setattr(ib, "_start", lambda rt_, iid: ib._process(rt_, iid))
    a = ib.receive(rt, "rules.png", b"\x89PNG rules")
    r = ib.research(rt, a["id"])
    assert r["skipped"] and "names no company" in r["why"] and sent == []                     # nothing sent, nothing spent; "NSE" the venue is not NSE the company
    b = ib.receive(rt, "dividend.png", b"\x89PNG dividend")
    ib.research(rt, b["id"])
    assert len(sent) == 1 and sent[0][1] == "deep" and "about ZEDCO" in sent[0][0]


def test_a_summary_hours_late_after_a_restart_is_not_sent(tmp_path, monkeypatch):
    """Seen 2026-10-30: after restarts, the morning and the evening summary both arrived at 14:15."""
    from pflab.conductor import calendar as mcal
    from pflab.service import jobs, summary
    import pflab.service.tasks  # noqa: F401
    sent = []
    monkeypatch.setattr(summary, "send", lambda *a, **k: sent.append(a[3]) or {"sent": True})
    monkeypatch.setattr(mcal, "load", lambda: type("C", (), {"is_trading_day": lambda self, d: True, "why_closed": lambda self, d: ""})())
    con = store.connect(tmp_path / "l.duckdb")
    at = lambda h, m: jobs.Ctx(con, datetime(2026, 10, 30, h, m), tmp_path, tmp_path, tmp_path)   # noqa: E731
    assert jobs.REGISTRY["summary_evening"].fn(at(14, 15))["skipped"]                         # yesterday's evening summary, 16 h late
    assert jobs.REGISTRY["summary_morning"].fn(at(14, 15))["skipped"]                         # this morning's, 5 h late
    jobs.REGISTRY["summary_morning"].fn(at(9, 20))
    jobs.REGISTRY["summary_evening"].fn(at(22, 0))
    assert sent == ["morning", "evening"]


def test_an_ipo_allotment_is_paid_by_the_one_bank_debit_of_its_amount_never_spending_or_money_from_nowhere():
    """2026-10-31: the exchange takes an allotment through his UPI mandate; that debit was asked about as 'OTHER'."""
    from pflab.ingest import bank
    b = _bpl()
    rows = [dict(date=date(2026, 6, 10), value_date=date(2026, 6, 10), description="UPI-000001-ICIABCDEF-50200000000001", ref="", debit=12345.0,
                 credit=0.0, balance=10_000.0),
            dict(date=date(2026, 5, 1), value_date=date(2026, 5, 1), description="UPI-SHOP", ref="", debit=12345.0, credit=0.0, balance=47_485.0)]
    stm = {"HDFC_0001": bank.classify(pd.DataFrame(rows), rules=[])}
    acc, line = b.ipo_payment_line(stm, 12345.0, date(2026, 6, 10))
    assert acc == "HDFC_0001" and line.date == date(2026, 6, 10)                     # the August one is too early
    assert b.ipo_payment_line(stm, 12345.0, date(2026, 6, 10), {("HDFC_0001", line.ref_id)}) is None   # taken once
    stm2 = {"A": stm["HDFC_0001"], "B": stm["HDFC_0001"].copy()}
    assert b.ipo_payment_line(stm2, 12345.0, date(2026, 6, 10)) is None             # two candidates: nothing is guessed


def test_a_label_question_the_code_has_since_explained_is_withdrawn(tmp_path):
    from pflab.ingest import bank, bank_labels as bl
    con = store.connect(tmp_path / "l.duckdb")
    rows = [dict(date=date(2026, 9, d), value_date=date(2026, 9, d), description="UPI-SOMEONE-ABC", ref="", debit=12_000.0, credit=0.0,
                 balance=100_000.0 - 12_000.0 * d) for d in (1, 2, 3)]
    df = bank.classify(pd.DataFrame(rows), rules=[])
    assert len(bl.ask(con, bl.groups({"HDFC_0001": df}), NOW)) == 1
    df["category"] = "ipo_payment"                                                          # explained by the next build
    bl.ask(con, bl.groups({"HDFC_0001": df}), NOW)
    assert [k for k, _, _ in questions.open_questions(con)] == []


def test_a_month_with_no_depository_statement_is_covered_when_the_holdings_did_not_change():
    """2026-10-31: NSDL sends no statement for a month in which nothing changed; that gap kept the picture 'partial' for good."""
    b = _bpl()
    h = {"INE000A01011": 10.0, "INE000A01029": 5.0}
    spans = [("DEMAT_X", date(2026, 6, 1), date(2026, 6, 30), h), ("DEMAT_X", date(2026, 8, 1), date(2026, 8, 31), dict(h)),
             ("ZER", date(2026, 6, 1), date(2026, 6, 30), {"INE000A01011": 1.0}), ("ZER", date(2026, 8, 1), date(2026, 8, 31), {"INE000A01011": 2.0})]
    assert b.bridged_gaps(spans) == [("DEMAT_X", date(2026, 7, 1), date(2026, 7, 31))]          # changed holdings: the hole stays


def test_a_late_first_statement_is_opened_then_once_he_confirms_every_account_and_file(tmp_path):
    from pflab.ingest import coverage as cv
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('SBI_9001', 'bank', 'SBI', '00009001'), "
                "('ZER', 'broker', 'Zerodha', '12000001')")
    for acc, kind, a, b in (("SBI_9001", "bank", date(2026, 4, 1), date(2026, 10, 25)), ("ZER", "funds_ledger", date(2026, 6, 14), date(2026, 10, 25))):
        con.execute("INSERT INTO statement_periods (account_id, kind, file_sha, first_date, last_date, n_rows, built_at) VALUES (?,?,'s',?,?,1,?)",
                    [acc, kind, a, b, NOW])
    zer = lambda: next(r for r in cv.matrix(con, NOW) if "ZER" in r["account"])
    assert not zer()["verified"] and "later than the rest" in zer()["next"]
    cv.confirm_inventory(con, NOW)
    assert zer()["verified"]
