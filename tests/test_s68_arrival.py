"""S68 P4: a request is answered by evidence that EXISTS and is valid, whenever it arrived; a failed or blocked file is not evidence; the same
bytes again retry what failed and sweep the waiting case; a locked file is kept, asked about once, and opens itself when its password is saved.
Synthetic files and passwords only."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pflab.hq import cases
from pflab.pm import store

NOW = datetime(2026, 10, 31, 12, 0)
A = "INE000A01011"


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                 VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'AAA Limited', 'synthetic', now())""", [A])
    return c


def _doc(con, doc_id, kind, isin, published, ingested, attrs=None):
    con.execute("INSERT INTO kg_docs (doc_id, kind, title, published_at, ingested_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?)",
                [doc_id, kind, doc_id, published, ingested, json.dumps(attrs or {})])
    con.execute("INSERT INTO kg_edges VALUES (?, 'about', ?, ?, NULL, 'test', NULL, NULL, ?)", [doc_id, f"company:{isin}", ingested, ingested])


def test_a_report_imported_before_the_request_answers_it_without_a_re_upload(con):
    """Regression: `ingested_at >= requested` ignored a valid report the investor had already supplied."""
    _doc(con, "result:AAA:q2", "result", A, datetime(2026, 10, 27), datetime(2026, 10, 28))                 # supplied BEFORE the request
    cid, _ = cases.open_case(con, NOW, "What did AAA Q2 results say?", subject="AAA", isin=A)
    cases.request(con, cid, NOW, "q2", "AAA Q2 results", match={"doc_kind": "result", "isin": A, "period_end": "2026-09-30"})
    assert cases.sweep(con, NOW) == [(cid, "q2")] and cases.get(con, cid)["status"] == "queued"


def test_an_old_report_still_does_not_answer_a_request_for_the_new_period(con):
    _doc(con, "result:AAA:q1", "result", A, datetime(2026, 7, 30), datetime(2026, 10, 28))
    cid, _ = cases.open_case(con, NOW, "AAA Q2?", subject="AAA", isin=A)
    cases.request(con, cid, NOW, "q2", "AAA Q2 results", match={"doc_kind": "result", "isin": A, "period_end": "2026-09-30"})
    assert cases.sweep(con, NOW) == []


def _item(con, iid, name, kind, status, text=""):
    con.execute("INSERT INTO inbox_items (item_id, name, kind, sha, status, text, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                [iid, name, kind, f"s{iid}", status, text, NOW - timedelta(days=2), NOW - timedelta(days=2)])


def test_a_file_dropped_before_the_request_counts_but_only_if_it_was_read(con):
    cid, _ = cases.open_case(con, NOW, "AAA annual report?", subject="AAA")
    cases.request(con, cid, NOW, "ar", "AAA annual report", match={"inbox": True, "inbox_kind": "result"})
    for iid, status in ((1, "failed"), (2, "working"), (3, "blocked"), (4, "kept")):                      # none of these is evidence
        _item(con, iid, f"AAA_report_{iid}.pdf", "other", status)
    assert cases.sweep(con, NOW) == []
    _item(con, 5, "AAA_report_5.pdf", "other", "in the graph")                                              # read, older than the request
    assert cases.sweep(con, NOW) == [(cid, "ar")]


def test_a_dropped_sheet_about_the_company_for_the_period_asked_resolves_a_result_request(con):
    cid, _ = cases.open_case(con, NOW, "AAA Q2?", subject="AAA", isin=A)
    cases.request(con, cid, NOW, "q2", "AAA Q2 results", match={"doc_kind": "result", "isin": A, "period_end": "2026-09-30"})
    _doc(con, "dataset:x|Sheet1", "dataset", A, NOW - timedelta(days=3), NOW - timedelta(days=3), {"columns": ["Metric", "Jun 2026"]})
    assert cases.sweep(con, NOW) == []                                                                      # the sheet shows another period
    _doc(con, "dataset:y|Sheet1", "dataset", A, NOW - timedelta(days=3), NOW - timedelta(days=3), {"columns": ["Metric", "Jun 2026", "Sep 2026"]})
    assert cases.sweep(con, NOW) == [(cid, "q2")]


# --- the inbox -------------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def rt(tmp_path):
    from pflab.app import runtime
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "pm" / "ledger.duckdb")
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path / "repo", con=con, clock=lambda: NOW)


def test_the_same_bytes_again_retry_a_failed_file_and_sweep_the_waiting_case(rt, monkeypatch):
    from pflab.app import inbox as ib
    started = []
    monkeypatch.setattr(ib, "_start", lambda r, iid: started.append(iid))
    con = rt.cursor()
    p = rt.pm_dir / "inbox"
    p.mkdir(parents=True)
    (p / "AAA_results.pdf").write_bytes(b"%PDF synthetic")
    sha = hashlib.sha256(b"%PDF synthetic").hexdigest()
    con.execute("INSERT INTO inbox_items (item_id, name, kind, path, sha, status, steps_json, created_at, updated_at) VALUES "
                "(1,'AAA_results.pdf','other',?,?,'failed','[]',?,?)", [str(p / "AAA_results.pdf"), sha, NOW, NOW])
    out = ib.receive(rt, "AAA_results.pdf", b"%PDF synthetic")
    assert out["duplicate"] is True and out["retried"] is True and started == [1]                           # not "duplicate, nothing happened"
    assert con.execute("SELECT status FROM inbox_items WHERE item_id=1").fetchone()[0] == "working"


def test_a_locked_file_is_kept_blocked_asked_once_and_opens_itself_when_the_password_is_saved(rt, monkeypatch):
    from pflab.agents import questions
    from pflab.app import inbox as ib
    from pflab.ingest import sniff
    started = []
    monkeypatch.setattr(ib, "_start", lambda r, iid: started.append(iid))
    state = {"pw": None}
    monkeypatch.setattr(sniff, "is_encrypted", lambda data, name: True)
    monkeypatch.setattr(sniff, "sniff", lambda data, name, pw=None: {"kind": "other", "bank": None, "last4": None, "dp_ids": None,
                                                                    **({"password_name": state["pw"]} if state["pw"] else {})})
    con = rt.cursor()
    out = ib.receive(rt, "AAA_results.pdf", b"%PDF locked synthetic")
    assert out["blocked"] and con.execute("SELECT status FROM inbox_items").fetchone()[0] == "blocked"
    assert Path(con.execute("SELECT path FROM inbox_items").fetchone()[0]).read_bytes() == b"%PDF locked synthetic"      # the original is kept
    assert len(questions.open_questions(con)) == 1
    ib.receive(rt, "AAA_results.pdf", b"%PDF locked synthetic")                                              # dropped again, still locked
    assert len(questions.open_questions(con)) == 1                                                          # asked ONCE
    cid, _ = cases.open_case(con, NOW, "AAA?", subject="AAA")
    cases.request(con, cid, NOW, "ar", "AAA report", match={"inbox": True, "inbox_kind": "result"})
    assert cases.sweep(con, NOW) == []                                                                      # blocked is not evidence
    assert ib.retry_blocked(rt) == 0                                                                        # nothing changed
    state["pw"] = "PFLAB_TEST_PASSWORD"                                                                     # the password is saved
    assert ib.retry_blocked(rt) == 1
    sts = [r[0] for r in con.execute("SELECT status FROM inbox_items ORDER BY item_id").fetchall()]
    assert sts[0] == "removed" and sts[-1] == "working" and started                                          # the same file, now being read; nothing duplicated
    assert not any("password-protected" in t for _, _, t in questions.open_questions(con))                  # its request closed
