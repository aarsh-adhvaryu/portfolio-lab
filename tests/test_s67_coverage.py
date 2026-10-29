"""S67 local: discovery reaches every account the statements show (not only the ones set up), keeps what it cannot use as visible gaps, asks the
investor once for the inventory, and refuses to say "complete" until every condition holds. The scenario of the brief: several banks, two accounts at one
bank, an institution absent from the legacy setup, an overlapping copy, a statement older than 400 days, more messages than the old 1,500 cap, an
unsupported document, a locked file and a month with no statement. A fake Gmail that honours the date window; synthetic mail; no network."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytest

from pflab.agents import questions
from pflab.app import inbox as ib
from pflab.app import runtime
from pflab.ingest import coverage, gmail, sniff
from pflab.pm import store
from tests.test_s67_mail_walk import WindowedGmail

NOW = datetime(2026, 10, 29, 9, 0)
BANKS = {"alpha": ("Alpha Bank", "1111"), "alpha2": ("Alpha Bank", "2222"), "beta": ("Beta Bank", "3333"), "newco": ("Newco Finance", "4444"), "oldco": ("Oldco Bank", "5555")}


def fake_sniff(data, name, pw):
    m = re.match(r"stmt_(\w+?)(?:_copy)?\.pdf", name)
    if m and m.group(1) in BANKS:
        bank, last4 = BANKS[m.group(1)]
        return {"kind": "bank", "bank": bank, "last4": last4, "dp_ids": None}
    return {"kind": "other", "bank": None, "last4": None, "dp_ids": None}


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(sniff, "passwords_from_secrets", lambda: [])
    monkeypatch.setattr(sniff, "sniff", fake_sniff)
    monkeypatch.setattr(sniff, "is_encrypted", lambda data, name: name.startswith("locked_"))
    got = {}

    def receive(rt_, name, data):
        if "newco" in name or "oldco" in name or "alpha2" in name:         # accounts nobody set up: the real inbox refuses and asks
            raise ValueError("which account is this bank statement for?")
        dup = data in got.values()
        if not dup:
            got[name] = data
        return {"duplicate": dup}
    monkeypatch.setattr(ib, "receive", receive)
    monkeypatch.setattr(ib, "_start", lambda rt_, iid: None)
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    monkeypatch.setattr(gmail, "BATCH_MESSAGES", 500)
    r = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)
    r.got = got
    return r


def mailbox():
    today = NOW.date()
    m = {f"n{k}": (today - timedelta(days=k % 900), []) for k in range(1700)}
    m["s_alpha"] = (today - timedelta(days=10), [("stmt_alpha.pdf", b"A 2026-09")])
    m["s_alpha_copy"] = (today - timedelta(days=10), [("stmt_alpha_copy.pdf", b"A 2026-09")])                 # a second mailbox's copy of the same file
    m["s_alpha2"] = (today - timedelta(days=12), [("stmt_alpha2.pdf", b"A2 2026-09")])                        # two accounts at one bank
    m["s_beta"] = (today - timedelta(days=200), [("stmt_beta.pdf", b"B 2026-04")])
    m["s_newco"] = (today - timedelta(days=500), [("stmt_newco.pdf", b"N 2025-06")])                          # an institution the legacy setup never had
    m["s_oldco"] = (today - timedelta(days=700), [("stmt_oldco.pdf", b"O 2024-11")])                          # older than 400 days
    m["promo"] = (today - timedelta(days=30), [("promo.pdf", b"an offer")])                                   # unsupported
    m["locked"] = (today - timedelta(days=45), [("locked_cas.pdf", b"%PDF locked")])                          # locked, no password
    return m


def read_everything(rt, g):
    gmail.fetch(rt, g, now=NOW)
    runs = 1
    while not all(m["reached_horizon"] for m in gmail.coverage(rt.cursor(), NOW)) and runs < 40:
        gmail.fetch(rt, g, now=NOW)
        runs += 1
    return runs


def test_every_account_the_statements_show_is_found_including_ones_never_set_up_and_older_than_400_days(rt):
    g = WindowedGmail(mailbox())
    runs = read_everything(rt, g)
    assert runs > 1
    labels = {r["account"] for r in coverage.matrix(rt.cursor(), NOW)}
    assert labels == {"Alpha Bank bank account ending 1111", "Alpha Bank bank account ending 2222", "Beta Bank bank account ending 3333",
                      "Newco Finance bank account ending 4444", "Oldco Bank bank account ending 5555"}
    rows = coverage.matrix(rt.cursor(), NOW)
    assert all(r["state"] == "discovered, not set up" for r in rows)                                          # nothing was set up: nothing is claimed
    assert not any(len(d) > 4 for r in rows for d in re.findall(r"\d{5,}", r["account"]))                    # masked: no long numbers
    assert len([r for r in rows if "Alpha Bank" in r["account"]]) == 2                                        # two accounts at one bank stay two
    n_alpha = rt.cursor().execute("SELECT n_files FROM account_candidates WHERE last4='1111'").fetchone()[0]
    assert n_alpha == 2                                                                                       # the overlapping copy counts as a file of the same account, not a new account


def test_what_cannot_be_used_stays_visible_and_the_picture_is_never_complete_from_email_alone(rt):
    g = WindowedGmail(mailbox())
    read_everything(rt, g)
    gk = {x["key"].split(":")[1] for x in coverage.gaps(rt.cursor())}
    assert {"locked", "unsupported"} <= gk                                                                    # neither was silently dropped
    s = coverage.status(rt.cursor(), NOW)
    assert s["label"] == "partial" and s["open_gaps"] >= 2
    assert any("not set up" in r for r in s["reasons"]) and any("you have not confirmed" in r for r in s["reasons"])
    assert "email alone cannot show" in s["note"]


def test_the_inventory_is_one_grouped_question_naming_every_account_and_asking_for_what_is_absent(rt):
    g = WindowedGmail(mailbox())
    read_everything(rt, g)
    gmail.fetch(rt, g, now=NOW)
    qs = [t for _, a, t in questions.open_questions(rt.cursor()) if "every account I have found" in t]
    assert len(qs) == 1                                                                                       # asked once, however many runs
    t = qs[0]
    for who in ("Alpha Bank bank account ending 1111", "Alpha Bank bank account ending 2222", "Newco Finance", "Oldco Bank"):
        assert who in t
    assert "NOT in this list" in t and "other email address" in t and "only download as a file" in t


def test_complete_needs_the_walk_the_set_up_the_gaps_closed_and_his_confirmation_and_a_new_account_reopens_it(rt):
    g = WindowedGmail(mailbox())
    read_everything(rt, g)
    con = rt.cursor()
    # set up every account and clear the gaps, but do not confirm: still partial
    for k, (bank, last4) in enumerate(BANKS.values(), 1):
        con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES (?, 'bank', ?, ?)", [f"B{k}", bank, f"00000{last4}"])
        con.execute("INSERT INTO events (event_id, kind, account_id, trade_date, amount, ingested_at) VALUES (?, 'deposit', ?, DATE '2026-09-01', 1.0, now())", [k, f"B{k}"])
    from pflab.app import readiness
    for g_ in coverage.gaps(con):
        readiness.close_gap(con, g_["key"], NOW)
    s = coverage.status(con, NOW)
    assert s["label"] == "partial" and s["reasons"] == ["you have not confirmed that this is every account, mailbox and export"]
    coverage.confirm_inventory(con, NOW)
    assert coverage.status(con, NOW)["label"] == "complete"
    # a statement for an account nobody had listed turns up afterwards
    coverage.note_account(con, {"kind": "bank", "bank": "Gamma Bank", "last4": "9999", "dp_ids": None}, "mail:x", NOW, "abc")
    s2 = coverage.status(con, NOW)
    assert s2["label"] == "partial" and any("not set up" in r for r in s2["reasons"]) and any("confirm again" in r for r in s2["reasons"])


def test_a_month_with_no_activity_inside_an_accounts_history_is_listed_not_assumed_quiet(rt):
    con = rt.cursor()
    con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('A1', 'bank', 'Alpha Bank', '00001111')")
    for k, d in enumerate(("2026-08-05", "2026-10-02"), 1):
        con.execute("INSERT INTO events (event_id, kind, account_id, trade_date, amount, ingested_at) VALUES (?, 'deposit', 'A1', CAST(? AS DATE), 1.0, now())", [k, d])
    row = [r for r in coverage.matrix(con, NOW) if "A1" in r["account"]][0]
    assert row["silent_months"] == ["2026-09"] and row["first_month"] == "2026-08" and row["last_month"] == "2026-10"
    coverage.note_account(con, {"kind": "bank", "bank": "Alpha Bank", "last4": "1111", "dp_ids": None}, "mail:x", NOW, "f")
    assert any("no activity" in r for r in coverage.status(con, NOW)["reasons"])


def test_nothing_is_claimed_before_anything_is_read(rt):
    s = coverage.status(rt.cursor(), NOW)
    assert s["label"] == "nothing read yet" and s["accounts"] == 0
    assert coverage.ask_inventory(rt.cursor(), NOW) is None                                                   # and nothing is asked about an empty inventory
