"""S65 Phase 7 item 4: bank labels by the system: own transfers and broker flows by code, the rest as questions, answers as rules."""
from datetime import date, datetime

import duckdb
import pandas as pd
import pytest

from pflab.agents import questions
from pflab.ingest import bank, bank_labels as bl
from pflab.pm import store

NOW = datetime(2026, 10, 28, 12, 0)


def stmt(rows):
    df = pd.DataFrame([dict(date=d, description=t, debit=db, credit=cr, balance=0.0, ref="", value_date=d) for d, t, db, cr in rows])
    return bank.classify(df, rules=[])                       # no rules: every line is unclassified


def test_the_counterparty_is_the_name_part_of_the_narration():
    assert bl.counterparty("UPI-JOHN DOE-john@ybl-YESB0000001-123456789012-NA") == "JOHN DOE"
    assert bl.counterparty("TO TRANSFER-UPI/DR/123456789012/ACME TRADERS/YESB/q123/payment") == "ACME TRADERS"
    assert bl.counterparty("NEFT CR-HDFC0000001-GLOBEX CORP-N123456") == "GLOBEX CORP"
    assert bl.counterparty("1234567 99999") == "OTHER"


def test_equal_amounts_in_two_accounts_within_two_days_are_his_own_transfer():
    a = stmt([(date(2026, 9, 1), "TRANSFER-X 111", 50_000.0, 0.0), (date(2026, 9, 5), "SOMETHING ELSE", 700.0, 0.0)])
    b = stmt([(date(2026, 9, 2), "BY TRANSFER-Y 222", 0.0, 50_000.0), (date(2026, 9, 9), "LATE", 0.0, 700.0)])   # 4 days: not a pair
    out, rep = bl.auto_label({"A": a, "B": b})
    assert rep == {"own_pairs": 1, "broker": 0, "card_spend": 0}
    assert list(out["A"]["category"]) == ["own_transfer", "unclassified"] and list(out["B"]["category"]) == ["own_transfer", "unclassified"]
    assert out["A"]["rule_id"].iloc[0] == "auto_own"
    assert [t for t in a["category"]] == ["unclassified"] * 2                        # the input is not changed


def test_a_pair_is_one_to_one():
    a = stmt([(date(2026, 9, 1), "OUT ONE", 1000.0, 0.0), (date(2026, 9, 1), "OUT TWO", 1000.0, 0.0)])
    b = stmt([(date(2026, 9, 1), "IN ONE", 0.0, 1000.0)])
    _, rep = bl.auto_label({"A": a, "B": b})
    assert rep["own_pairs"] == 1


def test_a_line_equal_to_a_console_pay_in_or_payout_is_a_broker_transfer():
    a = stmt([(date(2026, 9, 1), "PAYMENT 1", 25_000.0, 0.0), (date(2026, 9, 10), "RECEIPT 2", 0.0, 8_000.0),
              (date(2026, 9, 11), "WRONG WAY", 8_000.0, 0.0)])
    flows = pd.DataFrame({"date": [date(2026, 9, 2), date(2026, 9, 10)], "amount": [25_000.0, -8_000.0]})   # pay-in +, payout -
    out, rep = bl.auto_label({"A": a}, flows)
    assert rep["broker"] == 2 and list(out["A"]["category"]) == ["broker_transfer", "broker_transfer", "unclassified"]


def test_what_is_left_is_grouped_and_only_what_matters_is_asked():
    a = stmt([(date(2026, 9, d), "UPI-ACME TRADERS-x@ybl-1-NA", 0.0, 3000.0) for d in (1, 2, 3)]            # 3 lines
              + [(date(2026, 9, 4), "UPI-BIG PERSON-y@ybl-1-NA", 0.0, 60_000.0)]                            # one big line
              + [(date(2026, 9, 5), "UPI-TEA STALL-z@ybl-1-NA", 40.0, 0.0)])                                # small: not asked
    g = bl.groups({"A": a})
    assert [(x["counterparty"], x["n"], x["total"]) for x in g] == [("BIG PERSON", 1, 60_000.0), ("ACME TRADERS", 3, 9_000.0), ("TEA STALL", 1, 40.0)]
    con = duckdb.connect(":memory:")
    store.migrate(con)
    made = bl.ask(con, g, NOW)
    assert len(made) == 2 and bl.ask(con, g, NOW) == []                                                       # once
    text = con.execute("SELECT text FROM questions WHERE q_id=?", [made[0]]).fetchone()[0]
    assert "BIG PERSON" in text and "salary, own, family, spend, refund, other" in text


def test_no_more_than_a_few_questions_are_open_at_once():
    names = "ALPHA BRAVO CHARLIE DELTA ECHO FOXTROT GOLF HOTEL INDIA JULIET KILO LIMA MIKE NOVEMBER OSCAR PAPA".split()
    a = stmt([(date(2026, 9, 1), f"UPI-{n}-x@ybl-1-NA", 0.0, 30_000.0) for n in names])
    con = duckdb.connect(":memory:")
    store.migrate(con)
    assert len(bl.ask(con, bl.groups({"A": a}), NOW)) == bl.MAX_OPEN


def test_an_answer_becomes_a_rule_that_classifies_the_next_statement(tmp_path):
    a = stmt([(date(2026, 9, 4), "UPI-BIG PERSON-y@ybl-1-NA", 0.0, 60_000.0), (date(2026, 9, 6), "UPI-ACME TRADERS-x@ybl-1-NA", 25_000.0, 0.0)])
    con = duckdb.connect(":memory:")
    store.migrate(con)
    for q in bl.ask(con, bl.groups({"A": a}), NOW):
        who = con.execute("SELECT subject_key FROM questions WHERE q_id=?", [q]).fetchone()[0]
        questions.answer(con, q, "Salary." if "BIG PERSON" in who else "family, my brother", NOW)
    local = tmp_path / "bank_rules.local.toml"
    assert bl.apply_answers(con, local) == 2 and bl.apply_answers(con, local) == 0                           # written once
    rules = bank.load_rules(local=local)
    out = bank.classify(a.drop(columns=["category", "rule_id", "direction", "ref_id"]), rules)
    assert list(out["category"]) == ["salary", "family_transfer"]


def test_a_debit_called_salary_is_other_and_an_unknown_word_writes_nothing(tmp_path):
    a = stmt([(date(2026, 9, 6), "UPI-ACME TRADERS-x@ybl-1-NA", 29_000.0, 0.0), (date(2026, 9, 7), "UPI-GLOBEX CORP-x@ybl-1-NA", 29_000.0, 0.0)])
    con = duckdb.connect(":memory:")
    store.migrate(con)
    qs = bl.ask(con, bl.groups({"A": a}), NOW)
    questions.answer(con, qs[0], "salary", NOW)
    questions.answer(con, qs[1], "no idea", NOW)
    local = tmp_path / "r.toml"
    assert bl.apply_answers(con, local) == 1
    assert 'category = "other"' in local.read_text(encoding="utf-8")
