"""S67 local: several statements of one account, several Console ledgers. He drops everything by hand, so periods differ and overlap: every file counts,
a line that sits in two files counts once, a real repeat inside one file stays, and no file silently replaces another. Synthetic."""
from __future__ import annotations

from datetime import date

import pandas as pd

from pflab.ingest import bank, sources as srcs, zerodha_ledger as zl


def stmt(rows, opening):
    df = pd.DataFrame(rows, columns=["date", "value_date", "description", "ref", "debit", "credit", "balance"])
    df.attrs["opening_balance"] = opening
    return df


Q1 = [(date(2026, 1, 5), date(2026, 1, 5), "SALARY", "", 0.0, 1000.0, 1000.0),
      (date(2026, 1, 9), date(2026, 1, 9), "UPI TEA", "", 10.0, 0.0, 990.0),
      (date(2026, 1, 9), date(2026, 1, 9), "UPI TEA", "", 10.0, 0.0, 980.0)]                  # a real repeat inside one file: both stay
Q1_Q2 = Q1[1:] + [(date(2026, 2, 1), date(2026, 2, 1), "SALARY", "", 0.0, 1000.0, 1980.0)]     # overlaps Q1 on the two tea lines


def test_overlapping_bank_statements_join_into_one_without_double_counting():
    m = bank.merge_parsed([stmt(Q1_Q2, 990.0), stmt(Q1, 0.0)])                                  # dropped in any order
    assert len(m) == 4 and list(m["date"]) == sorted(m["date"])
    assert list(m["balance"]) == [1000.0, 990.0, 980.0, 1980.0] and m["debit"].sum() == 20.0   # the two real tea lines, once each
    assert m.attrs["opening_balance"] == 0.0                                                    # the earliest file's opening
    assert bank.merge_parsed([stmt(Q1, 0.0)]).equals(stmt(Q1, 0.0))                             # one file: unchanged
    c = bank.classify(m)
    assert c["ref_id"].is_unique and len(c) == 4


def test_two_console_ledgers_are_one_ledger(monkeypatch):
    def led(rows, opening, closing):
        df = pd.DataFrame(rows, columns=["particulars", "date", "voucher", "debit", "credit", "balance"])
        df.attrs.update(opening=opening, closing=closing)
        return df
    a = led([("Funds added", date(2025, 4, 2), "Bank Receipts", 0.0, 500.0, 500.0), ("Charges", date(2025, 4, 9), "Journal Entry", 5.0, 0.0, 495.0)], 0.0, 495.0)
    b = led([("Charges", date(2025, 4, 9), "Journal Entry", 5.0, 0.0, 495.0), ("Funds added", date(2026, 2, 2), "Bank Receipts", 0.0, 100.0, 595.0)], 0.0, 595.0)
    files = {"a.xlsx": a, "b.xlsx": b}
    monkeypatch.setattr(zl, "parse", lambda p: files[str(p)])
    m = zl.parse_many(["b.xlsx", "a.xlsx"])
    assert len(m) == 3 and list(m["date"]) == sorted(m["date"]) and m.attrs == {"opening": 0.0, "closing": 595.0}
    assert len(zl.charge_events(m, "ZER")) == 1                                                  # the overlapping charge is one charge


def test_a_second_bank_statement_or_ledger_is_added_never_swapped_in():
    over = srcs.with_document({}, "bank", "new/jan.xls", "sbi")
    over = srcs.with_document(over, "bank", "new/feb.xls", "sbi")
    over = srcs.with_document(over, "bank", "new/feb.xls", "sbi")                               # the same file again: no repeat
    over = srcs.with_document(over, "bank", "new/hdfc.xls", "hdfc")
    over = srcs.with_document(over, "funds_ledger", "new/l1.xlsx")
    over = srcs.with_document(over, "funds_ledger", "new/l2.xlsx")
    m = srcs.merge({"zerodha": {"account": "zer", "funds_ledger": "new/base.xlsx"}, "bank": [{"account": "sbi", "file": "new/dec.xls", "password_env": "PW"}]}, over)
    sbi = next(b for b in m["bank"] if b["account"] == "sbi")
    assert sbi["files"] == ["new/dec.xls", "new/jan.xls", "new/feb.xls"] and sbi["password_env"] == "PW" and next(b for b in m["bank"] if b["account"] == "hdfc")["file"] == "new/hdfc.xls"
    assert m["zerodha"]["funds_ledger"] == "new/base.xlsx" and m["zerodha"]["funds_ledgers"] == ["new/l1.xlsx", "new/l2.xlsx"]
    text = srcs.dumps(over)                                                                      # and it is written out and read back whole
    import tomllib
    assert tomllib.loads(text)["bank"][0]["files"] == ["new/jan.xls", "new/feb.xls"] and tomllib.loads(text)["zerodha"]["funds_ledgers"] == ["new/l2.xlsx"]
