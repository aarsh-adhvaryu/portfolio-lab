"""S65 read-only Gmail: statements found by content, kept through the inbox, protected files handled by password NAME, nothing fetched twice,
the workshop never reads his mail. A fake Gmail; no network."""
import base64
import io
import json
from datetime import datetime
from types import SimpleNamespace

import openpyxl
import pytest

from pflab.agents import questions
from pflab.app import inbox as ib
from pflab.app import runtime
from pflab.ingest import gmail, sniff
from pflab.pm import store

NOW = datetime(2026, 10, 29, 9, 0)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def workbook(rows) -> bytes:
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


TRADEBOOK = b"symbol,isin,trade_date,trade_type,quantity,price,trade_id\nABC,INE0,2026-10-27,buy,1,2,3\n"
LEDGER = workbook([["Particulars", "Posting Date", "Cost Center", "Voucher Type", "Debit", "Credit", "Net Balance"]])
NEWSLETTER = b"%PDF-1.4 not a statement"


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class FakeGmail:
    """messages: id -> (headers, [(filename, bytes, inline?)]); pages of 2 ids."""
    def __init__(self, messages):
        self.messages, self.calls = messages, []

    def get(self, url, params=None, timeout=None):
        path = url.split("/users/me/", 1)[1]
        self.calls.append(path)
        if path == "profile":
            return Resp({"emailAddress": "someone@example.com"})
        if path == "messages":
            ids = list(self.messages)
            start = int(params.get("pageToken", 0) or 0)
            page = {"messages": [{"id": i} for i in ids[start:start + 2]]}
            if start + 2 < len(ids):
                page["nextPageToken"] = str(start + 2)
            return Resp(page)
        parts = path.split("/")
        mid = parts[1]
        heads, files = self.messages[mid]
        if len(parts) == 4:                                       # messages/{id}/attachments/{aid}
            return Resp({"data": b64(files[int(parts[3])][1])})
        payload_parts = []
        for k, (name, data, inline) in enumerate(files):
            payload_parts.append({"filename": name, "body": {"data": b64(data)} if inline else {"attachmentId": str(k)}})
        payload = {"headers": [{"name": "From", "value": heads[0]}, {"name": "Date", "value": heads[1]}],
                   "parts": [{"filename": "", "body": {}, "parts": payload_parts}]}         # nested, as Gmail sends a multipart message
        return Resp({"payload": payload})


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(ib, "_start", lambda rt, iid: None)
    monkeypatch.setattr(sniff, "passwords_from_secrets", lambda: [])
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def test_attachments_are_read_from_nested_parts_and_pages():
    g = FakeGmail({"m1": (("broker", "Mon"), [("tb.csv", TRADEBOOK, False), ("note.txt", b"x", True)]),
                   "m2": (("bank", "Tue"), [("ledger.xlsx", LEDGER, True)]), "m3": (("x", "Wed"), [])})
    assert gmail.message_ids(g, "q") == ["m1", "m2", "m3"]
    meta, files = gmail.attachments(g, "m1")
    assert meta["from"] == "broker" and files == [("tb.csv", TRADEBOOK)]                    # the .txt is not looked at
    assert gmail.attachments(g, "m2")[1] == [("ledger.xlsx", LEDGER)]


def test_statements_come_in_through_the_inbox_and_nothing_else_is_kept(rt):
    g = FakeGmail({"m1": (("Console", "Mon"), [("tb.csv", TRADEBOOK, False), ("ledger.xlsx", LEDGER, False)]),
                   "m2": (("news", "Tue"), [("weekly.pdf", NEWSLETTER, False)])})
    out = gmail.fetch(rt, g, now=NOW)
    assert out["kept"] == 2 and out["dropped"] == 1 and out["locked"] == 0
    kinds = sorted(k for (k,) in rt.cursor().execute("SELECT kind FROM inbox_items").fetchall())
    assert kinds == ["funds_ledger", "tradebook"]                                         # held for Setup or checked, then his press
    assert not list((rt.pm_dir / "inbox").glob("**/weekly.pdf")) and not list(rt.repo.glob("new/weekly.pdf"))   # never written
    again = gmail.fetch(rt, g, now=NOW)
    assert again["messages"] == 0                                                         # nothing fetched twice


def test_protected_files_are_asked_about_once_per_sender_retried_and_closed_when_a_password_opens_them(rt, monkeypatch):
    opens = {"pw": False}
    monkeypatch.setattr(sniff, "is_encrypted", lambda data, name: True)
    monkeypatch.setattr(sniff, "sniff", lambda data, name, pw: {"kind": "cas", "password_name": "NSDL"} if opens["pw"]
                        else {"kind": "other", "why": "no text read (a password, or a scan)"})
    g = FakeGmail({f"m{k}": (("NSDL e-CAS <cas@nsdl.co.in>", "Mon, 10 Nov 2026"), [(f"eCAS{k}.pdf", b"%PDF-1.7 locked " + bytes([48 + k]), False)])
                   for k in range(3)})
    out = gmail.fetch(rt, g, now=NOW)
    assert out["locked"] == 3
    q = questions.open_questions(rt.cursor())
    assert len(q) == 1 and "eCAS0.pdf" in q[0][2] and "'NSDL'" in q[0][2] and "Keys and passwords" in q[0][2]   # one item, not three
    assert gmail.passwords_wanted(rt.cursor()) == ["NSDL"]                                # the slot in Settings > Keys
    assert gmail.fetch(rt, g, now=NOW)["messages"] == 3                                   # not marked seen: tried again
    assert len(questions.open_questions(rt.cursor())) == 1                                # but asked once
    opens["pw"] = True                                                                    # he saved the password
    out = gmail.fetch(rt, g, now=NOW)
    assert out["kept"] == 3 and gmail.passwords_wanted(rt.cursor()) == []                 # opened: the item closed itself
    texts = [t for _, _, t in questions.open_questions(rt.cursor())]
    assert len(texts) == 1 and "Use these accounts" in texts[0]                           # a cold start: approve in Setup
    assert gmail.fetch(rt, g, now=NOW)["messages"] == 0


def test_the_first_look_reads_a_year_and_later_looks_the_last_weeks(rt):
    queries = []
    g = FakeGmail({"m1": (("x", "Mon"), [])})
    real = gmail.message_ids
    gmail.message_ids = lambda sess, q, limit=300: (queries.append((q, limit)), real(sess, q, limit))[1]
    try:
        gmail.fetch(rt, g, now=NOW)
        g.messages["m2"] = (("y", "Tue"), [])
        gmail.fetch(rt, g, now=NOW)
    finally:
        gmail.message_ids = real
    assert "newer_than:400d" in queries[0][0] and queries[0][1] == gmail.FIRST_LIMIT
    assert "newer_than:40d" in queries[1][0] and queries[1][1] == 300


def test_sender_names_are_the_password_slot_names():
    assert gmail.sender_name("NSDL e-CAS <nsdl-cas@nsdl.co.in>") == "NSDL"
    assert gmail.sender_name("SBI <cbssbi.info@alerts.sbi.co.in>") == "SBI"
    assert gmail.sender_name("Kotak <statements@email.kotak.com>") == "KOTAK"
    assert gmail.sender_name("someone") == "EMAIL"


def test_the_workshop_never_reads_his_mail(rt, monkeypatch):
    from pflab import guard
    monkeypatch.setenv("PFLAB_CHANNEL", "beta")
    monkeypatch.delenv("PFLAB_LIVE", raising=False)
    with pytest.raises(guard.OutwardBlocked, match="mail"):
        gmail.fetch(rt, FakeGmail({}), now=NOW)


def test_connect_saves_a_read_only_token_and_refuses_anything_more(tmp_path, monkeypatch):
    monkeypatch.setattr(gmail, "home", lambda: tmp_path / ".pflab")
    monkeypatch.setattr(gmail.Path, "home", lambda: tmp_path)
    with pytest.raises(gmail.MailError, match="client file"):
        gmail.connect()
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "client_secret_123-abc.apps.googleusercontent.com.json").write_text("{}", encoding="utf-8")
    assert gmail.has_client()                                                             # found where Google's download lands

    def flow(scopes):
        creds = SimpleNamespace(scopes=scopes, to_json=lambda: json.dumps({"scopes": scopes}))
        return lambda path, s: SimpleNamespace(run_local_server=lambda **k: creds)
    monkeypatch.setattr(gmail, "session", lambda: FakeGmail({}))
    assert gmail.connect(flow_factory=flow(gmail.SCOPES)) == "someone@example.com"
    assert (tmp_path / ".pflab" / "gmail_client.json").exists()                           # moved beside secrets.toml
    assert json.loads((tmp_path / ".pflab" / "gmail_token.json").read_text(encoding="utf-8"))["scopes"] == gmail.SCOPES
    (tmp_path / ".pflab" / "gmail_token.json").unlink()
    with pytest.raises(gmail.MailError, match="more than read-only"):
        gmail.connect(flow_factory=flow(gmail.SCOPES + ["https://mail.google.com/"]))
    assert not (tmp_path / ".pflab" / "gmail_token.json").exists()


def test_the_job_asks_once_to_be_connected(rt, monkeypatch):
    from pflab.service import tasks
    from pflab.service.jobs import REGISTRY
    monkeypatch.setattr(gmail, "connected", lambda: False)
    ctx = SimpleNamespace(con=rt.cursor(), now=NOW, pm_dir=rt.pm_dir, data_root=rt.data_root, repo=rt.repo, secrets=None)
    assert "not connected" in REGISTRY["mail"].fn(ctx)["skipped"]
    REGISTRY["mail"].fn(ctx)
    assert [t for _, _, t in questions.open_questions(rt.cursor()) if "Connect Gmail" in t].__len__() == 1
