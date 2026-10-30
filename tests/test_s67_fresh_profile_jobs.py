"""S67 local: the first real launch of a NEW empty profile (found live on 2026-10-30): the jobs that need holdings, a broker account or his targets
must wait and say so, not fail with KeyError / LookupError. Synthetic; no network."""
from __future__ import annotations

from datetime import datetime

import pytest

from pflab import activation
from pflab.kg import build as kb
from pflab.pm import fresh, store
from pflab.service import jobs, runner
import pflab.service.tasks  # noqa: F401  (registers the jobs)

NOW = datetime(2026, 10, 30, 10, 35)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path / "pm"))
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    fresh.new_profile(tmp_path / "pm", None, "scratch")
    activation.activate(tmp_path / "pm", via="icon")
    con = store.connect(tmp_path / "pm" / "ledger.duckdb")
    c = runner.make_ctx(con=con, now=NOW)
    c.secrets = None                                            # never this PC's real keys: no Kite or any other real call from a test
    return c


def test_the_universe_of_an_empty_profile_has_its_columns(ctx):
    u = kb.universe(ctx.con, [])
    assert u.empty and {"isin", "symbol", "name", "sector", "scrip", "aliases"} <= set(u.columns)
    assert u[u["isin"].astype(str).str.startswith("INE")].empty                      # what researcher and forecast do first


def test_a_profile_with_no_broker_account_waits_instead_of_failing(ctx):
    out = jobs.REGISTRY["tradecheck"].fn(ctx)
    assert out["skipped"] and out["waiting"] and "Inbox and files" in out["why"]
    assert jobs.run_job(ctx, jobs.REGISTRY["tradecheck"]).status in ("skipped", "failed")   # (no Kite login here: disabled) never an exception


def test_targets_not_set_is_waiting_for_him_not_a_failure(ctx, monkeypatch):
    from pflab.plan import targets as tg

    def not_set(*a, **k):
        raise tg.TargetsNotSet("no targets are set")
    monkeypatch.setattr(tg, "load", not_set)
    out = jobs.REGISTRY["companion"].fn(ctx)
    assert out["skipped"] and "not set" in out["why"]


class _Kite:
    def holdings(self):
        return [{"isin": "INE000A01011", "tradingsymbol": "AAA", "exchange": "NSE", "quantity": 6, "t1_quantity": 0, "average_price": 100.0, "last_price": 119.0}]

    def positions(self):
        return {"net": []}

    def mf_holdings(self):
        return []

    def margins(self):
        return {"equity": {"available": {"cash": 0, "opening_balance": 5000.0, "live_balance": 5000.0}}}

    def trades(self):
        return []


def test_kite_still_shows_what_you_hold_before_any_statement_has_set_up_an_account(ctx, monkeypatch):
    """The first real launch: 'why can't it look at my portfolio from Kite?' It can: the snapshot is kept and labelled as not yet matched."""
    from pflab.pm import today
    from pflab.service import tasks
    monkeypatch.setattr(tasks, "_kite", lambda c: _Kite())
    out = jobs.REGISTRY["tradecheck"].fn(ctx)
    assert out["kite_only"] and out["snapshot"]["rows"] >= 2 and "matched to your statements" in out["note"]
    assert today.broker(ctx.con) == today.KITE_ONLY
    t = today.build(ctx.con, NOW.date())
    assert t["today"]["source"] == "kite" and t["today"]["account"] == today.KITE_ONLY
    assert [r.isin for r in t["positions"].itertuples()] == ["INE000A01011"]


def test_email_is_off_by_default_and_nothing_asks_to_connect_it(ctx, monkeypatch):
    from pflab.agents import questions
    from pflab.ingest import gmail
    from pflab.app import system
    monkeypatch.delenv("PFLAB_MAIL", raising=False)
    assert gmail.enabled() is False and gmail.connected() is False and gmail.coverage(ctx.con, NOW) == []
    assert gmail.ask_to_connect(ctx.con, NOW) is None and questions.open_questions(ctx.con) == []
    ok, why = jobs.REGISTRY["mail"].enabled_fn(ctx)
    assert ok is False and "by hand" in why
    assert jobs.run_job(ctx, jobs.REGISTRY["mail"]).status == "skipped"
    from pflab.app import runtime
    rt = runtime.Runtime(ctx.pm_dir, ctx.data_root, ctx.repo, con=ctx.con, clock=lambda: NOW)
    g = next(c for c in system.picture(rt, NOW)["connectors"] if c["id"] == "gmail")
    assert g["state"] == system.OFF and "by hand" in g["line"] and g["action"] is None


def test_an_account_can_be_left_out_and_is_never_a_gap_or_a_question(ctx):
    from pflab.ingest import coverage
    k = coverage.note_account(ctx.con, {"kind": "bank", "bank": "Old Bank", "last4": "9999", "dp_ids": None}, "a file you dropped", NOW, "abc")
    assert coverage.status(ctx.con, NOW)["label"] == "partial" and any("not set up" in r for r in coverage.status(ctx.con, NOW)["reasons"])
    assert coverage.leave_out(ctx.con, k) is True
    st = coverage.status(ctx.con, NOW)
    assert not any("not set up" in r for r in st["reasons"]) and st["left_out"] and "9999" in st["left_out"][0]
    row = next(r for r in coverage.matrix(ctx.con, NOW) if "9999" in r["account"])
    assert row["state"].startswith("left out") and row["key"] == k
    d = coverage.declare_left_out(ctx.con, "Inactive demat at a second broker", NOW)                       # one no file will ever show
    assert d and any("Inactive demat" in r["account"] for r in coverage.matrix(ctx.con, NOW))
    coverage.confirm_inventory(ctx.con, NOW)
    assert coverage._confirmed_covers_all(ctx.con)                                                          # left-out accounts never reopen the question
    coverage.note_account(ctx.con, {"kind": "bank", "bank": "Old Bank", "last4": "9999", "dp_ids": None}, "a file you dropped", NOW, "def")
    assert next(r for r in coverage.matrix(ctx.con, NOW) if "9999" in r["account"])["state"].startswith("discovered")   # a file for it brings it back
    assert coverage.add_back(ctx.con, d) is True


def test_a_file_dropped_by_hand_records_the_account_it_shows(ctx, tmp_path, monkeypatch):
    from pflab.app import inbox as ib, runtime
    from pflab.ingest import coverage, sniff
    rt = runtime.Runtime(ctx.pm_dir, ctx.data_root, ctx.repo, con=ctx.con, clock=lambda: NOW)
    monkeypatch.setattr(sniff, "sniff", lambda data, name, pw=None: {"kind": "bank", "bank": "Alpha Bank", "last4": "1111", "dp_ids": None})
    monkeypatch.setattr(ib, "_start", lambda *a, **k: None)
    monkeypatch.setattr(ib, "_accounts", lambda r: {})
    try:
        ib.receive(rt, "statement.pdf", b"%PDF-1.4 synthetic")
    except ValueError:
        pass                                                                                                # "which account?" is asked: the account is still noted
    assert any("Alpha Bank" in r["account"] for r in coverage.matrix(ctx.con, NOW))


def test_the_bring_list_is_computed_from_what_is_in_inbox_and_says_what_is_missing(ctx):
    from pflab.app import onboarding
    items = {b["id"]: b for b in onboarding.bring_list(ctx.con)}
    assert items["tradebook"]["state"] == "missing" and items["cas"]["state"] == "missing" and items["kite"]["detail"]
    ctx.con.execute("INSERT INTO inbox_items (item_id, name, kind, account, path, sha, status, steps_json, result_json, chat_id, created_at, updated_at) "
                    "VALUES (1,'t.csv','tradebook',NULL,'p','s','done','[]','{}',NULL,?,?)", [NOW, NOW])
    items = {b["id"]: b for b in onboarding.bring_list(ctx.con)}
    assert items["tradebook"]["state"] == "have" and items["funds"]["state"] == "missing"
    assert "email" not in onboarding.WELCOME.lower() and "left out" in onboarding.WELCOME
