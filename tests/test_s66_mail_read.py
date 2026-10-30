"""S66 what his emails say: the local model names facts, the guard keeps only numbers and dates the email states, code checks each
fact against the record and Kite, only what is missing or disagrees is asked, research naming no id of his feeds the readers.
A fake Gmail and a fake model; no network, no Ollama."""
import base64
import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from pflab.agents import questions
from pflab.app import runtime
from pflab.ingest import mail_read as mr
from pflab.pm import store

NOW = datetime(2026, 11, 3, 21, 15)
AAA = "INE000A01011"


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


class FakeGmail:
    """id -> (from, subject, body, mime, received)."""
    def __init__(self, mails):
        self.mails = mails

    def get(self, url, params=None, timeout=None):
        path = url.split("/users/me/", 1)[1]
        if path == "messages":
            return SimpleNamespace(status_code=200, json=lambda: {"messages": [{"id": i} for i in self.mails]})
        frm, subj, body, mime, rec = self.mails[path.split("/")[1]]
        payload = {"headers": [{"name": "From", "value": frm}, {"name": "Subject", "value": subj}],
                   "parts": [{"mimeType": mime, "filename": "", "body": {"data": b64(body)}}]}
        return SimpleNamespace(status_code=200, json=lambda: {"payload": payload, "internalDate": str(int(rec.timestamp() * 1000))})


def model(replies):
    """A fake local model: the reply for the email whose subject it is given."""
    def chat(name, msgs, **k):
        subj = msgs[1]["content"].split("\n", 1)[0][len("Subject: "):]
        return SimpleNamespace(text=json.dumps({"facts": replies.get(subj, [])}))
    return chat


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'ALPHACO', 'Alphaco Industries Limited', 'synthetic', now())""", [AAA])
    con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('ZERODHA', 'demat', 'Zerodha', '12345678')")
    con.execute("INSERT INTO lots VALUES (1, 'ZERODHA', ?, DATE '2026-01-05', 10, 100, 'listed_equity', 1)", [AAA])
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    monkeypatch.setattr("pflab.plan.guards.stock_list", lambda path=None: [])
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def test_the_body_is_read_as_text_from_plain_or_html():
    assert mr.body_text({"parts": [{"mimeType": "text/plain", "body": {"data": b64("Bought 10 ALPHACO")}}]}) == "Bought 10 ALPHACO"
    h = mr.body_text({"parts": [{"mimeType": "text/html", "body": {"data": b64("<p>Credited&nbsp;Rs 1,250.50</p><style>x{}</style>")}}]})
    assert "Credited" in h and "1,250.50" in h and "<" not in h and "x{}" not in h


def test_the_guard_keeps_only_numbers_and_dates_the_email_states():
    text = "Your order to buy 10 ALPHACO at Rs 1,234.50 was executed on 27-Oct-2026. Deposit no. XXXX4321."
    f, dropped = mr.guard({"kind": "trade", "side": "buy", "symbol": "ALPHACO", "quantity": 10, "price": 1234.5, "amount": 12345,
                           "date": "2026-10-27", "deposit_last4": "4321"}, text)
    assert f["quantity"] == 10 and f["price"] == 1234.5 and f["date"] == "2026-10-27" and f["deposit_last4"] == "4321"
    assert "amount" not in f and dropped == ["amount"]                                   # a number the model computed: dropped
    g, d2 = mr.guard({"kind": "dividend", "date": "2026-10-28", "amount": "lots"}, text)
    assert "date" not in g and set(d2) == {"date", "amount"}
    assert mr.guard({"kind": "nonsense"}, text)[0]["kind"] == "other"


def test_facts_are_checked_against_kite_and_the_record(rt):
    con = rt.cursor()
    t = {"kind": "trade", "side": "buy", "symbol": "ALPHACO", "quantity": 10.0, "date": "2026-10-27"}
    assert mr.check(con, t, date(2026, 10, 27), date(2026, 10, 28))[0] == "pending"        # Kite may bring it
    assert mr.check(con, t, date(2026, 10, 27), date(2026, 11, 3))[0] == "new"             # still missing after the wait
    con.execute("INSERT INTO kite_trades VALUES ('t1', 'o1', DATE '2026-10-27', 'ALPHACO', 'NSE', ?, 'BUY', 10, 1234.5, 'ZERODHA', "
                "now(), 'open', NULL)", [AAA])
    assert mr.check(con, t, date(2026, 10, 27), date(2026, 11, 3))[0] == "matched"
    st, why = mr.check(con, {**t, "quantity": 12.0}, date(2026, 10, 27), date(2026, 11, 3))
    assert st == "conflict" and "12" in why
    fd = {"kind": "fd_booking", "amount": 50000.0, "date": "2026-11-01", "rate_pct": 7.1}
    assert mr.check(con, fd, date(2026, 11, 1), date(2026, 11, 1))[0] == "new"             # not on the deposit list
    con.execute("INSERT INTO fds (fd_id, bank, principal, rate, term_start, maturity, maturity_amount, status, source, loaded_at) "
                "VALUES ('FD0001', 'SBI', 50000, 7.1, DATE '2026-11-01', DATE '2027-11-01', 53600, 'open', 'setup', now())")
    assert mr.check(con, fd, date(2026, 11, 1), date(2026, 11, 1))[0] == "matched"
    assert mr.check(con, {"kind": "bank_debit", "amount": 999.0}, date(2026, 11, 1), date(2026, 11, 2))[0] == "pending"


def test_a_run_reads_checks_asks_and_feeds_the_readers(rt):
    mails = {
        "m1": ("Broker <noreply@broker.example>", "Trade executed", "You bought 10 ALPHACO at Rs 1,234.50 on 27-Oct-2026.",
               "text/plain", datetime(2026, 10, 27, 16)),
        "m2": ("Bank <alerts@bank.example>", "Fixed deposit booked", "Your deposit of Rs 50,000 at 7.10% is booked on 01-Nov-2026, "
               "maturity 01-Nov-2027, maturity amount Rs 53,600.00.", "text/plain", datetime(2026, 11, 1, 10)),
        "m3": ("Research <desk@research.example>", "Alphaco results: research note", "<p>Alphaco Industries beat estimates; margin "
               "18.2%.</p>", "text/html", datetime(2026, 11, 2, 9)),
        "m4": ("Research <desk@research.example>", "Alphaco research for client 12345678", "Alphaco Industries upgrade.", "text/plain",
               datetime(2026, 11, 2, 9)),
        "m5": ("Shop <x@shop.example>", "Interest free EMI offer", "Buy now.", "text/plain", datetime(2026, 11, 2, 9)),
    }
    replies = {"Trade executed": [{"kind": "trade", "side": "buy", "symbol": "ALPHACO", "quantity": 10, "price": 1234.5,
                                   "date": "27-Oct-2026"}],
               "Fixed deposit booked": [{"kind": "fd_booking", "amount": 50000, "rate_pct": 7.1, "date": "2026-11-01",
                                         "maturity_date": "2027-11-01", "maturity_amount": 53600, "deposit_last4": "9999"}],
               "Alphaco results: research note": [{"kind": "research", "company": "Alphaco Industries"}],
               "Alphaco research for client 12345678": [{"kind": "research", "company": "Alphaco Industries"}]}
    out = mr.run(rt, FakeGmail(mails), "qwen3:8b-q8_0", NOW, chat=model(replies))
    assert out["emails"] == 5 and out["facts"] == 4 and out["new"] == 2 and out["public"] == 1 and out["errors"] == 0
    asked = [t for _, _, t in questions.open_questions(rt.cursor())]
    assert len(asked) == 2 and any("buy 10" in t and "ALPHACO" in t for t in asked) and any("deposit opened: Rs 50000" in t for t in asked)
    assert all("nothing is written to your record" in t for t in asked)
    con = rt.cursor()
    fd = json.loads(con.execute("SELECT fields_json FROM mail_facts WHERE kind='fd_booking'").fetchone()[0])
    assert "deposit_last4" not in fd and fd["dropped"] == ["deposit_last4"]                  # 9999 is not in the email
    docs = con.execute("SELECT d.kind, d.title, d.text_path FROM kg_docs d JOIN kg_edges e ON e.src=d.doc_id "
                       "WHERE e.dst=?", [f"company:{AAA}"]).fetchall()
    assert [d[1] for d in docs] == ["Alphaco results: research note"]                        # the one naming his id stays out
    from pflab.hq import readers
    assert [r["title"] for r in readers.pending(con, NOW.date(), [AAA], [], stock_list=[])] == ["Alphaco results: research note"]
    again = mr.run(rt, FakeGmail(mails), "qwen3:8b-q8_0", NOW, chat=model(replies))
    assert again["emails"] == 0                                                              # each email read once
    con.execute("INSERT INTO kite_trades VALUES ('t1', 'o1', DATE '2026-10-27', 'ALPHACO', 'NSE', ?, 'BUY', 10, 1234.5, 'ZERODHA', "
                "now(), 'open', NULL)", [AAA])
    assert mr.recheck(rt, NOW) == 1                                                          # Kite brought it: the item closes
    assert len(questions.open_questions(con)) == 1
    s = mr.summary(con)
    assert s["counts"]["matched"] == 1 and s["latest"][0]["says"]


def test_many_emails_make_one_question_per_kind_and_notices_without_a_quantity_make_none(rt):
    """Found on the first real launch: 30 near-identical questions ("IPO allotment: ? JPL" again and again) buried the few that matter."""
    mails, replies = {}, {}
    rows = [("12.0", "JPL"), ("12.0", "JPL"), ("16.0", "JPL"), (None, "JPL"), (None, "JPL"), (None, None), (None, "NSE"), ("21.0", "NSE")]
    for i, (qty, who) in enumerate(rows):
        subj = f"IPO allotment notice {i}"
        body = f"Allotment: {qty or ''} shares of {who or ''} allotted on 27-Oct-2026."      # the guard keeps only what the email states
        mails[f"m{i}"] = ("Registrar <ipo@registrar.example>", subj, body, "text/plain", datetime(2026, 10, 27, 9, i))
        f = {"kind": "ipo_allotment", "date": "2026-10-27"}
        if qty:
            f["quantity"] = float(qty)
        if who:
            f["symbol"] = who
        replies[subj] = [f]
    mr.run(rt, FakeGmail(mails), "qwen3:8b-q8_0", NOW, chat=model(replies))
    con = rt.cursor()
    asked = [t for _, _, t in questions.open_questions(con)]
    assert len(asked) == 1 and "3 IPO allotments" in asked[0]                                  # 12 JPL (twice, once), 16 JPL, 21 NSE
    assert "?" not in asked[0].split("not in your record")[1].split("If they")[0]              # never a placeholder in the list
    assert "nothing is written to your record" in asked[0]
    again = mr.run(rt, FakeGmail(mails), "qwen3:8b-q8_0", NOW, chat=model(replies))
    assert again["emails"] == 0 and len(questions.open_questions(con)) == 1                    # no second copy
    mr.regroup(con, NOW)
    assert len(questions.open_questions(con)) == 1
    con.execute("INSERT INTO questions VALUES (99, ?, 'mail', 'mailfact:7', 'An email says: old style', 'open', NULL, NULL)", [NOW])
    mr.regroup(con, NOW)                                                                       # a profile that already holds the old per-email ones is tidied
    assert [t for _, _, t in questions.open_questions(con)] == asked


def test_a_model_failure_leaves_the_email_for_tomorrow_and_the_workshop_never_reads(rt, monkeypatch):
    mails = {"m1": ("b", "Dividend credited", "Rs 120 credited", "text/plain", datetime(2026, 11, 2))}

    def broken(*a, **k):
        raise ConnectionError("ollama is off")
    assert mr.run(rt, FakeGmail(mails), "m", NOW, chat=broken)["errors"] == 1
    assert rt.cursor().execute("SELECT count(*) FROM mail_facts").fetchone()[0] == 0
    from pflab import guard
    monkeypatch.setenv("PFLAB_CHANNEL", "beta")
    monkeypatch.delenv("PFLAB_LIVE", raising=False)
    with pytest.raises(guard.OutwardBlocked):
        mr.run(rt, FakeGmail(mails), "m", NOW, chat=model({}))


def test_only_the_local_model_may_read_his_emails():
    from pflab.hq import models
    assert models.JOBS["mail_reading"].choices == ("local",)


def test_a_long_first_look_stops_at_its_time_budget_and_continues_next_run(rt, monkeypatch):
    mails = {f"m{k}": ("b <a@b.example>", f"Dividend credited {k}", "Rs 120 credited on 02-Nov-2026", "text/plain", datetime(2026, 11, 2))
             for k in range(3)}
    monkeypatch.setattr(mr, "BUDGET_S", -1)
    out = mr.run(rt, FakeGmail(mails), "m", NOW, chat=model({}))
    assert out["emails"] == 0 and out["left"] == 3
    monkeypatch.setattr(mr, "BUDGET_S", 600)
    assert mr.run(rt, FakeGmail(mails), "m", NOW, chat=model({}))["emails"] == 3


def test_duplicate_facts_from_one_email_are_kept_once():
    same = {"kind": "trade", "side": "buy", "symbol": "ALPHACO", "quantity": 25, "price": 1234.5, "date": "2026-10-27"}
    chat = lambda name, msgs, **k: SimpleNamespace(text=json.dumps({"facts": [same, dict(same), dict(same)]}))   # noqa: E731
    assert len(mr.read("Bought 25 ALPHACO at Rs 1,234.50 on 27-Oct-2026", "Trade", "m", chat)) == 1
