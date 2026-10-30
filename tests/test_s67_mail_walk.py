"""S67 local: the mailbox is walked back through its history in saved windows, so a statement older than the old 400-day / 1,500-message
look is reached, overlapping copies are not stored twice, an unsupported file stays visible as dropped, and the walk never says it has
read everything. A fake Gmail that honours the date window; synthetic mail; no network."""
from __future__ import annotations

import base64
import re
from datetime import date, datetime, timedelta

import pytest

from pflab.app import inbox as ib
from pflab.app import runtime
from pflab.ingest import gmail, sniff
from pflab.pm import store

NOW = datetime(2026, 10, 29, 9, 0)


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class WindowedGmail:
    """messages: id -> (day, [(filename, bytes)]). Lists only what falls in the query's after:/before: window, 100 per page."""
    def __init__(self, messages, address="me@example.com"):
        self.messages, self.address, self.queries = messages, address, []

    def get(self, url, params=None, timeout=None):
        path = url.split("/users/me/", 1)[1]
        if path == "profile":
            return Resp({"emailAddress": self.address})
        if path == "messages":
            q = params["q"]
            self.queries.append(q)
            a = re.search(r"after:(\d{4})/(\d\d)/(\d\d)", q)
            b = re.search(r"before:(\d{4})/(\d\d)/(\d\d)", q)
            lo, hi = date(*map(int, a.groups())), date(*map(int, b.groups()))
            ids = [i for i, (day, _f) in self.messages.items() if lo <= day < hi]
            start = int(params.get("pageToken", 0) or 0)
            page = {"messages": [{"id": i} for i in ids[start:start + 100]]}
            if start + 100 < len(ids):
                page["nextPageToken"] = str(start + 100)
            return Resp(page)
        parts = path.split("/")
        day, files = self.messages[parts[1]]
        if len(parts) == 4:
            return Resp({"data": b64(files[int(parts[3])][1])})
        pp = [{"filename": n, "body": {"attachmentId": str(k)}} for k, (n, _d) in enumerate(files)]
        return Resp({"payload": {"headers": [{"name": "From", "value": "bank"}, {"name": "Date", "value": str(day)}], "parts": pp}})


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(sniff, "passwords_from_secrets", lambda: [])
    monkeypatch.setattr(sniff, "sniff", lambda data, name, pw: {"kind": "bank"} if name.startswith("stmt") else {"kind": "other"})
    monkeypatch.setattr(sniff, "is_encrypted", lambda data, name: False)
    got = {}

    def receive(rt_, name, data):
        dup = data in got.values()
        if not dup:
            got[name] = data
        return {"duplicate": dup}
    monkeypatch.setattr(ib, "receive", receive)
    monkeypatch.setattr(ib, "_start", lambda rt_, iid: None)
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    r = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)
    r.got = got
    return r


def _mailbox():
    today = NOW.date()
    m = {f"n{k}": (today - timedelta(days=k % 900), []) for k in range(1700)}        # more than the old 1,500 cap, none a statement
    # five banks, two accounts at one of them, one bank the legacy setup never knew; one statement 700 days old
    m["s_a1"] = (today - timedelta(days=10), [("stmt_bankA_acct1.pdf", b"A1 2026-09")])
    m["s_a2"] = (today - timedelta(days=12), [("stmt_bankA_acct2.pdf", b"A2 2026-09")])
    m["s_b"] = (today - timedelta(days=200), [("stmt_bankB.pdf", b"B 2026-04")])
    m["s_c_old"] = (today - timedelta(days=700), [("stmt_bankC_old.pdf", b"C 2024-11")])
    m["s_new_bank"] = (today - timedelta(days=500), [("stmt_newbank.pdf", b"NEW 2025-06")])
    m["s_a1_copy"] = (today - timedelta(days=10), [("stmt_bankA_acct1_copy.pdf", b"A1 2026-09")])    # the same file, a second mailbox's copy
    m["promo"] = (today - timedelta(days=30), [("promo.pdf", b"an offer")])                          # a file nobody can read as a statement
    return m


def count(rt, table):
    return rt.cursor().execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_the_walk_reaches_old_evidence_stores_each_statement_once_and_never_claims_everything(rt, monkeypatch):
    monkeypatch.setattr(gmail, "BATCH_MESSAGES", 400)
    g = WindowedGmail(_mailbox())
    gmail.fetch(rt, g, now=NOW)
    st = gmail.coverage(rt.cursor(), NOW)[0]
    assert "stmt_bankC_old.pdf" not in rt.got and st["reached_horizon"] is False        # one batch is not the whole history
    runs = 1
    while not gmail.coverage(rt.cursor(), NOW)[0]["reached_horizon"] and runs < 40:
        gmail.fetch(rt, g, now=NOW)
        runs += 1
    assert runs > 1 and gmail.coverage(rt.cursor(), NOW)[0]["reached_horizon"] is True
    names = set(rt.got)
    assert {"stmt_bankA_acct1.pdf", "stmt_bankA_acct2.pdf", "stmt_bankB.pdf", "stmt_bankC_old.pdf", "stmt_newbank.pdf"} <= names
    assert "stmt_bankA_acct1_copy.pdf" not in names                                      # the overlapping copy was seen as a duplicate
    assert count(rt, "mail_seen") == 1700 + 7                                             # every message read exactly once, none lost to a cap
    cov = gmail.coverage(rt.cursor(), NOW)[0]
    assert cov["link_only_or_no_file_mail_checked"] is False and cov["horizon_days"] == gmail.HORIZON_DAYS
    again = gmail.fetch(rt, g, now=NOW)
    assert again["messages"] == 0 and again["kept"] == 0                                  # a repeat creates nothing new


def test_a_stop_in_the_middle_resumes_in_the_same_window_without_skipping(rt, monkeypatch):
    monkeypatch.setattr(gmail, "BATCH_MESSAGES", 50)
    g = WindowedGmail(_mailbox())
    gmail.fetch(rt, g, now=NOW)
    seen1 = count(rt, "mail_seen")
    gmail.fetch(rt, g, now=NOW)                                                           # a second run (after a restart) carries on
    assert seen1 < count(rt, "mail_seen") <= seen1 + 120


def test_two_mailboxes_keep_separate_checkpoints(rt, monkeypatch):
    monkeypatch.setattr(gmail, "BATCH_MESSAGES", 60)
    g1, g2 = WindowedGmail(_mailbox(), "one@example.com"), WindowedGmail({}, "two@example.com")
    gmail.fetch(rt, g1, now=NOW)
    gmail.fetch(rt, g2, now=NOW)
    cov = {c["mailbox"]: c for c in gmail.coverage(rt.cursor(), NOW)}
    assert len(cov) == 2 and gmail.mailbox_key(g1) != gmail.mailbox_key(g2)
    assert cov[gmail.mailbox_key(g2)]["reached_horizon"] is True and cov[gmail.mailbox_key(g1)]["reached_horizon"] is False
