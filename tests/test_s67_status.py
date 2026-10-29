"""S67 status, staleness, privacy and parity: a failed operation never refreshes a "last good" time or leaves a connector green; a job whose
sub-step failed has failed; retained data is shown as stale with the failure beside it; an email goes out only with provenance and a fresh
identity check (never raw, never by kind alone); the dashboard's Runtime and the background Desk give the same answers through the same tools;
a follow-up in the chat sees the chat. Synthetic data; fakes at the boundaries; no network."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.agents import tools as at
from pflab.app import chat, runtime, system
from pflab.hq import desk as hdesk, egress, governor as gv, readers, service, tools as tl
from pflab.kg import graph as g
from pflab.pm import store
from pflab.service import jobs

NOW = datetime(2026, 11, 4, 21, 0)                   # a Wednesday evening
AAA = "INE000A01011"
CFG = {"model": "claude-opus-5-5", "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True, "tijori_to_analyst": True}


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'ALPHACO', 'Alphaco Industries Limited', 'synthetic', now())""", [AAA])
    con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('ZERODHA', 'demat', 'Zerodha', '12345678')")
    monkeypatch.setattr(system, "_ollama", lambda: {"up": True, "models": ["qwen3:8b-q8_0", "nomic-embed-text:latest"]})
    monkeypatch.setattr(system, "_docker", lambda: "not installed")
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def _job(con, rid, job, when, status, detail=None):
    con.execute("INSERT INTO job_runs (run_id, job, started_at, finished_at, status, detail) VALUES (?,?,?,?,?,?)", [rid, job, when, when, status, detail])


# --- a failed operation is never "last good" ---------------------------------------------------------------------------------------------

def test_a_failed_mail_run_does_not_refresh_the_email_time_or_keep_gmail_green(rt, monkeypatch):
    from pflab.ingest import gmail
    monkeypatch.setattr(gmail, "connected", lambda: True)                            # a token file exists
    con = rt.cursor()
    _job(con, 1, "mail", NOW - timedelta(days=3), "ok", "{}")
    _job(con, 2, "mail", NOW - timedelta(hours=1), "failed", "MailError: Gmail answered 401 for messages")
    fr = {f["name"]: f for f in system.freshness(rt, NOW)}
    assert fr["Email"]["latest"] == str((NOW - timedelta(days=3)).date())             # the failed run did not move it
    assert fr["Email"]["retained"] and fr["Email"]["state"] in (system.WARN, system.DOWN) and "refresh failed" in fr["Email"]["line"]
    assert "401" in fr["Email"]["line"]
    gm = {c["id"]: c for c in system.connectors(rt, NOW)}["gmail"]
    assert gm["state"] == system.WARN and "latest read failed" in gm["line"]           # a saved login is not a working mailbox
    _job(con, 3, "mail", NOW - timedelta(minutes=5), "ok", "{}")
    gm = {c["id"]: c for c in system.connectors(rt, NOW)}["gmail"]
    assert gm["state"] == system.OK                                                    # only a success turns it green again


def test_kite_is_green_only_when_a_read_worked_not_when_a_login_exists(rt, monkeypatch):
    monkeypatch.setattr(runtime, "token_valid", lambda now=None: True)
    con = rt.cursor()
    k = {c["id"]: c for c in system.connectors(rt, NOW)}["kite"]
    assert k["state"] == system.WARN and "no read has worked" in k["line"]
    con.execute("INSERT INTO kite_snapshots (snap_id, taken_at, account_id, kind, amount) VALUES (1, ?, 'ZERODHA', 'cash', 5000)", [NOW - timedelta(hours=2)])
    assert {c["id"]: c for c in system.connectors(rt, NOW)}["kite"]["state"] == system.OK
    _job(con, 1, "tradecheck", NOW - timedelta(minutes=10), "failed", "KiteException: token expired")
    k = {c["id"]: c for c in system.connectors(rt, NOW)}["kite"]
    assert k["state"] == system.WARN and "token expired" in k["line"]


def test_telegram_api_and_sandbox_colours_come_from_real_use(rt, monkeypatch):
    rt.settings["telegram_send"] = True
    con = rt.cursor()
    con.execute("INSERT INTO outbox (msg_id, created_at, kind, text, dedup_key, status, attempts, last_error) VALUES (1, ?, 'brain', 'x', 'k', 'pending', 3, 'Telegram 401')",
                [NOW])
    cs = {c["id"]: c for c in system.connectors(rt, NOW)}
    assert cs["telegram"]["state"] == system.WARN and "failed to send" in cs["telegram"]["line"]
    assert cs["sandbox"]["state"] == system.WARN and "calculations wait" in cs["sandbox"]["line"]       # no Docker: not "uncontained but fine"
    from pflab.agents import sandbox as sb
    monkeypatch.setattr(system, "_docker", lambda: "running")
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": True, "why": ""})
    assert {c["id"]: c for c in system.connectors(rt, NOW)}["sandbox"]["state"] == system.WARN         # works, but containment not yet proven
    system.record_check(con, "sandbox", True, NOW - timedelta(days=1), "all checks passed")
    assert {c["id"]: c for c in system.connectors(rt, NOW)}["sandbox"]["state"] == system.OK
    system.record_check(con, "sandbox", False, NOW, "network_closed")
    sx = {c["id"]: c for c in system.connectors(rt, NOW)}["sandbox"]
    assert sx["state"] == system.DOWN and "calculations are blocked" in sx["line"]


def test_a_job_with_a_failed_sub_step_has_failed_and_the_screen_says_which(rt, tmp_path):
    from pflab.service import tasks  # noqa: F401  (registers the jobs)
    con = rt.cursor()
    ctx = jobs.Ctx(con, NOW, rt.pm_dir, rt.data_root, rt.repo, "python", None)
    job = jobs.Job("demo", jobs.REGISTRY["hq"].schedule, lambda c: {"ok_part": 3, "failed": {"readers": "RateLimitError: slow down"}})
    res = jobs.run_job(ctx, job)
    assert res.status == "failed" and "readers" in res.detail
    row = con.execute("SELECT status, detail FROM job_runs WHERE job='demo'").fetchone()
    assert row[0] == "failed" and json.loads(row[1])["ok_part"] == 3                     # the finished work is kept in the detail
    w = system.work(rt, NOW)
    assert w["recent"][0]["ok"] is False and "readers: RateLimitError" in w["recent"][0]["says"]
    assert jobs.followers(res) == []                                                     # nothing follows from a failed run
    ok = jobs.run_job(ctx, jobs.Job("demo2", job.schedule, lambda c: {"failed": {}}))
    assert ok.status == "ok"


def test_the_hq_job_fails_when_a_part_fails_instead_of_reporting_a_success(rt, monkeypatch):
    monkeypatch.setattr(service, "paid_allowed", lambda r: True)

    def boom(r, limit=40):
        raise ConnectionError("api.anthropic.com unreachable")
    monkeypatch.setattr(service, "read_now", boom)
    monkeypatch.setattr(service, "brain_wake", lambda r: {"pass": None, "why": "nothing new"})
    monkeypatch.setattr("pflab.hq.phone.poll_once", lambda r, timeout=0: 0)
    monkeypatch.setattr("pflab.hq.security.egress", lambda r: {})
    ctx = jobs.Ctx(rt.cursor(), NOW, rt.pm_dir, rt.data_root, rt.repo, "python", None)
    out = service.tick_job(ctx)
    assert "readers" in out["failed"] and "unreachable" in out["failed"]["readers"]
    assert jobs.run_job(ctx, jobs.Job("hq_demo", jobs.REGISTRY["hq"].schedule, service.tick_job)).status == "failed"


# --- the same picture and the same tools from the dashboard and the background -------------------------------------------------------------

def _desk(rt, tmp_path):
    return hdesk.Desk(rt.cursor(), rt.pm_dir, rt.data_root, tmp_path, None, {"brain": "economy", "preset": "full"}, clock=lambda: NOW)


def test_system_status_and_mail_facts_work_in_the_dashboard_and_in_the_background(rt, tmp_path):
    d = _desk(rt, tmp_path)
    for who in (rt, d):
        ctx = SimpleNamespace(rt=who, now=NOW, con=who.cursor())
        s = tl.system_status(ctx, {})
        assert s["verdict"] and s["connectors"] and "recommendations" in s and "tasks" in s and "being_researched" in s
        assert tl.mail_facts(ctx, {})["counts"] == {}
    a, b = system.picture(rt, NOW), system.picture(d, NOW)
    assert [c["state"] for c in a["connectors"]] == [c["state"] for c in b["connectors"]] and a["verdict"] == b["verdict"]


def test_the_ask_centre_answers_a_system_question_from_the_same_tool(rt, tmp_path):
    d = _desk(rt, tmp_path)
    for who in (rt, d):
        out = chat.answer(who, who.cursor(), "Is everything working and in sync?", "ask")
        assert "system" in out["route"][1] or any("tool: system" in r for r in out["route"]), out["route"]
        assert "connector" in out["text"] or "system.verdict" in out["text"] or "working" in out["text"]
    out = chat.answer(rt, rt.cursor(), "Did my bank emails arrive?", "ask")
    assert any("tool: mail" in r for r in out["route"])


def test_a_follow_up_sees_the_chat_and_the_open_work(rt, tmp_path):
    con = rt.cursor()
    cid = chat.create(con, NOW)
    chat._add(con, cid, "me", "ask", "How much of AAA do I hold?", "done", NOW)
    chat._add(con, cid, "ai", "ask", "About 9 percent of your investable money.", "done", NOW)
    q = chat._add(con, cid, "me", "ask", "and is that too much?", "done", NOW)
    h = chat.history_text(con, cid, q)
    assert h.splitlines() == ["he asked: How much of AAA do I hold?", "you answered: About 9 percent of your investable money."]
    seen = {}

    def fake_llm(prompt):
        seen["prompt"] = prompt
        return "x"
    from pflab.agents import centre
    centre.ask(con, "and is that too much?", NOW.date(), llm=fake_llm, tools_override=["system"], history=h)
    assert "EARLIER IN THIS CHAT" in seen["prompt"] and "How much of AAA do I hold?" in seen["prompt"]
    # the brain gets the same history and the open investigations as events of its pass
    from pflab.hq import brain, cases
    cases.open_case(con, NOW, "Is AAA's margin trend real?", subject="AAA", isin=AAA)
    got = {}
    d = _desk(rt, tmp_path)

    def spy(rt_, trigger, evs, client, gate, **kw):
        got["evs"] = evs
        return 1
    import pflab.hq.service as sv
    sv.client = lambda r: object()
    orig = brain.think
    brain.think = spy
    try:
        con.execute("INSERT INTO hq_passes VALUES (1, ?, 'asked', '[]', 'm', 'brain', false, 'done', 'The answer.', '[]', 0, NULL, NULL)", [NOW])
        service.brain_now(d, "and is that too much?", rival=False, history=h)
    finally:
        brain.think = orig
    kinds = [e["kind"] for e in got["evs"]]
    assert kinds == ["from the investor (question)", "the conversation so far", "your open investigations"]
    assert "Is AAA's margin trend real?" in got["evs"][2]["text"]


# --- email: provenance, then a fresh identity check, never raw ---------------------------------------------------------------------------

def _json_msg(obj):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(obj))], stop_reason="end_turn", model=gv.HAIKU,
                           usage=SimpleNamespace(input_tokens=500, output_tokens=60, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class Haiku:
    def __init__(self, reply):
        self.reply, self.sent = reply, []
        self.messages = SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=600), create=self._create)

    def _create(self, **kw):
        self.sent.append(json.dumps(kw, default=str))
        return _json_msg(self.reply)


def _email_doc(con, tmp_path, name, body, cleared="auto", attrs_extra=None):
    d = g.doc(con, "email", f"mail:{name}", NOW, f"Alphaco research {name}", source="Research desk",
              attrs={"kind": "research", **({"cleared": hashlib.sha256(body.encode()).hexdigest()} if cleared == "auto" else
                                              {"cleared": cleared} if cleared else {}), **(attrs_extra or {})})
    p = tmp_path / f"{name}.txt"
    p.write_text(body, encoding="utf-8")
    con.execute("UPDATE kg_docs SET text_path=?, text_status='ok' WHERE doc_id=?", [str(p), d])
    g.edge(con, d, "about", f"company:{AAA}", NOW, "mail")
    return d


READ = {"material": "yes", "why": "upgrade", "summary": "Alphaco upgraded.", "figures": []}


def test_an_email_goes_out_only_with_clearance_and_a_fresh_identity_check(rt, tmp_path, monkeypatch):
    con = rt.cursor()
    monkeypatch.setattr(store, "pm_dir", lambda: tmp_path)
    (tmp_path / "api_budget.toml").write_text("[api]\nmonthly_cap_rupees = 2500\ndev_monthly_cap_rupees = 100\nask_above_rupees = 50\nadopted = true\n", encoding="utf-8")
    gate = egress.load(con)
    body = "Alphaco Industries is upgraded to buy on margin expansion. Contact the desk at desk@research.example or +91 98765 43210."
    good = _email_doc(con, tmp_path, "good", body)
    no_clear = _email_doc(con, tmp_path, "noclear", body, cleared=None)
    stale = _email_doc(con, tmp_path, "stale", body, cleared="0" * 64)
    leaky = _email_doc(con, tmp_path, "leaky", "Alphaco note for client 12345678 about your holding.")
    rows = {r["doc_id"]: r for r in readers.pending(con, NOW.date(), [AAA], [], stock_list=[])}
    assert set(rows) == {good, no_clear, stale, leaky}
    client = Haiku(READ)
    out = {k: readers.read_one(con, rows[d], client, gate, NOW, "economy", CFG) for k, d in
           (("good", good), ("noclear", no_clear), ("stale", stale), ("leaky", leaky))}
    assert out["good"]["material"] == "yes" and "withheld" not in out["good"]
    assert len(client.sent) == 1                                                       # only the cleared one reached the API
    sent = client.sent[0]
    assert "desk@research.example" not in sent and "98765" not in sent and "[EMAIL]" in sent and "[PHONE]" in sent   # redacted copy, never raw
    for k, why in (("noclear", "provenance missing"), ("stale", "changed after it was cleared"), ("leaky", "account number")):
        assert out[k]["withheld"] and why in out[k]["withheld"], out[k]
    rows2 = con.execute("SELECT doc_id, material, why FROM hq_readings WHERE why LIKE 'withheld%'").fetchall()
    assert len(rows2) == 3                                                             # kept, so they are not retried every round
    assert readers.pending(con, NOW.date(), [AAA], [], stock_list=[]) == []
    run_report = readers.run(con, NOW.date(), Haiku(READ), gate, NOW, "economy", [AAA], [], stock_list=[])
    assert run_report["read"] == 0
    assert not egress.DOC_KINDS.count("email")                                         # email is still not a public kind


def test_the_mail_reader_stamps_the_clearance_the_readers_check(rt, tmp_path):
    from pflab.ingest import mail_read as mr
    rt.cursor().execute("INSERT INTO lots VALUES (1, 'ZERODHA', ?, DATE '2026-01-05', 10, 100, 'listed_equity', 1)", [AAA])
    meta = {"from": "Research <desk@research.example>", "subject": "Alphaco Industries results: research note"}
    text = "Alphaco Industries beat estimates; margins widened."
    import pflab.plan.guards as gd
    gd_orig = gd.stock_list
    gd.stock_list = lambda path=None: []
    try:
        did = mr._public(rt, "m9", meta, text, {"kind": "research"}, egress.load(rt.cursor()))
    finally:
        gd.stock_list = gd_orig
    assert did
    attrs = json.loads(rt.cursor().execute("SELECT attrs_json FROM kg_docs WHERE doc_id=?", [did]).fetchone()[0])
    assert attrs["cleared"] == hashlib.sha256(text.encode()).hexdigest() and "mail reader" in attrs["provenance"]


def test_the_screen_says_what_stays_on_this_pc_and_what_goes_to_the_cloud(rt):
    p = {x["what"]: x for x in system.processing(rt)}
    assert p["What his money emails say (trades, deposits, dividends, alerts)"]["where"] == "this PC"
    assert "never leave" in p["His statements, ledger, tax lots and bank details"]["sends"]
    assert p["Research or corporate-action emails that name none of his ids"]["where"].startswith("cloud")
    assert "redacted" in p["Research or corporate-action emails that name none of his ids"]["sends"]
    assert system.picture(rt, NOW)["processing"]
