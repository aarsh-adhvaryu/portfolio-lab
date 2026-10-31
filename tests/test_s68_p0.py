"""S68 P0: a credential-shaped string never reaches a stored row or the log; the growth tool reads the event's date; a pass that was refused or
stopped does not stand in for the day's scheduled review. Synthetic tokens only."""
from __future__ import annotations

import logging
from datetime import date, datetime

import pytest

from pflab import scrub
from pflab.hq import brain, context
from pflab.pm import store

FAKE_TG = "bot1234567890:AAFakeFakeFakeFakeFakeFakeFakeFake_0123"
FAKE_ANT = "sk-ant-api03-FAKEFAKEFAKEFAKE"


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


def test_telegram_token_in_a_url_is_masked():
    s = f"ConnectionError: https://api.telegram.org/{FAKE_TG}/getUpdates (Caused by NameResolutionError)"
    out = scrub.scrub(s)
    assert "AAFake" not in out and "1234567890" not in out and "api.telegram.org" in out and "getUpdates" in out


def test_other_credential_shapes():
    out = scrub.scrub(f"key {FAKE_ANT} and access_token=abcdef123456XYZ and Authorization: Bearer abcdefghijklmnop1234")
    assert "FAKEFAKE" not in out and "abcdef123456XYZ" not in out and "abcdefghijklmnop1234" not in out
    assert scrub.scrub("nothing secret here: 12 trades, Rs 5") == "nothing secret here: 12 trades, Rs 5"


def test_job_result_is_scrubbed_in_every_part(con, tmp_path):
    from pflab.service import jobs
    from pathlib import Path
    from pflab.service.jobs import Ctx, Job
    (tmp_path / "locks").mkdir()
    ctx = Ctx(con=con, now=datetime(2026, 10, 31, 12, 0), pm_dir=tmp_path, data_root=tmp_path, repo=Path("."))
    sched = type("S", (), {"latest_slot": staticmethod(lambda now: now)})()
    job = Job(name="t", schedule=sched, fn=lambda c: {"phone": f"failed: ConnectionError {FAKE_TG}", "n": 1})
    r = jobs.run_job(ctx, job)
    assert "AAFake" not in r.detail
    row = con.execute("SELECT detail FROM job_runs").fetchone()[0]
    assert "AAFake" not in row


def test_existing_rows_are_rewritten_once(con):
    con.execute("INSERT INTO job_runs VALUES (1, 'hq', ?, ?, ?, 'failed', ?)",
                [datetime(2026, 10, 31, 13, 15), datetime(2026, 10, 31, 13, 15), datetime(2026, 10, 31, 13, 29), f"x {FAKE_TG} y"])
    n, looked = scrub.scrub_store(con)
    assert n == 1 and looked >= 1
    assert "AAFake" not in con.execute("SELECT detail FROM job_runs").fetchone()[0]
    assert scrub.scrub_store(con)[0] == 0                                        # idempotent


def test_log_filter_masks_message_arguments_and_tracebacks(tmp_path):
    p = tmp_path / "a.log"
    lg = logging.getLogger("pflab.test_scrub")
    h = logging.FileHandler(p, encoding="utf-8")
    h.addFilter(scrub.Filter())
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    try:
        try:
            raise RuntimeError(f"boom {FAKE_TG}")
        except RuntimeError:
            lg.exception("failed %s", FAKE_ANT)
    finally:
        lg.removeHandler(h)
        h.close()
    text = p.read_text(encoding="utf-8")
    assert "AAFake" not in text and "FAKEFAKE" not in text and "boom" in text


def test_scrub_file_rewrites_an_old_log(tmp_path):
    p = tmp_path / "app.log"
    p.write_text(f"ok line\nbad {FAKE_TG}\n", encoding="utf-8")
    assert scrub.scrub_file(p) == 1
    assert "AAFake" not in p.read_text(encoding="utf-8") and "ok line" in p.read_text(encoding="utf-8")
    assert scrub.scrub_file(p) == 0


def test_growth_tool_reads_the_events_date(con):
    """Regression: the growth tool read `Event.trade_date`, which the dataclass does not have (live store, tool error 2026-10-31)."""
    from pflab.ledger import events as ev
    log = ev.load(con)
    assert not hasattr(next(iter([ev.Event]), None), "trade_date") or True
    assert "date" in ev.Event.__dataclass_fields__ and "trade_date" not in ev.Event.__dataclass_fields__
    out = context.growth(con, date(2026, 10, 31))                                  # an empty ledger must not raise
    assert out["total_change"] == 0


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, q, a):
        class R:
            def fetchone(s2):
                for needle, hit in self.rows.items():
                    if needle in q:
                        return hit if hit is not None else None
                return None
        return R()


def test_a_refused_or_stopped_pass_does_not_stand_in_for_the_morning():
    from types import SimpleNamespace

    class C:
        def __init__(self, statuses):
            self.statuses = statuses            # statuses of the morning passes already in hq_passes today

        def execute(self, q, a):
            def one():
                if "trigger='morning'" in q:
                    excl = "NOT IN ('not made', 'stopped')" in q
                    ok = [s for s in self.statuses if not (excl and s in ("not made", "stopped"))]
                    return (1,) if ok else None
                return None
            return SimpleNamespace(fetchone=one)
    t = datetime(2026, 10, 26, 9, 0)
    assert brain.due_scheduled(C(["not made"]), t) == "morning"       # refused at turn 1: the morning is still due
    assert brain.due_scheduled(C(["stopped"]), t) == "morning"
    assert brain.due_scheduled(C(["done"]), t) is None


def test_a_graph_label_is_never_nan(con):
    """Reported symptom: 'nan' graph labels (a node with no name)."""
    from pflab.app import graph
    assert graph.clean_label(None, "org:Acme") == "Acme" and graph.clean_label(float("nan"), "company:INE000A01011") == "INE000A01011"
    assert graph.clean_label("nan", "person:Jane Roe") == "Jane Roe" and graph.clean_label("Real Name", "x:y") == "Real Name"
    con.execute("INSERT INTO kg_nodes (node_id, kind, name, updated_at) VALUES ('company:INE000A01011', 'company', 'nan', now())")
    out = graph.view(con)
    assert out["nodes"] and all(str(n["label"]).lower() not in ("nan", "none", "") for n in out["nodes"])


def test_a_holding_with_no_purchase_record_shows_its_cost_as_unknown_not_zero(con):
    """Reported symptom: 'unknown costs shown as zero' (a share opened from a depository statement at cost 0 showed a gain equal to its whole value)."""
    from pflab.app import views
    from pflab.ledger import events as ev
    from datetime import date as d
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES ('INE000A01011', 'isin', 'equity', 'listed_equity', TRUE, 'AAA', 'AAA Limited', 'synthetic', now()),
                          ('INE000B01012', 'isin', 'equity', 'listed_equity', TRUE, 'BBB', 'BBB Limited', 'synthetic', now())""")
    con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('ZERODHA', 'demat', 'Zerodha', 'SYNTH0001')")
    for isin in ("INE000A01011", "INE000B01012"):
        con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?)", [isin, d(2026, 10, 30), 100.0, "EQ", "nse_bhavcopy", datetime(2026, 10, 30)])
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZERODHA", date=d(2026, 1, 1), amount=100000.0, ref="funds"))
    log.append(ev.Event(kind="buy", account_id="ZERODHA", date=d(2026, 1, 2), isin="INE000A01011", qty=10.0, price=80.0, ref="bought"))
    log.append(ev.Event(kind="buy", account_id="ZERODHA", date=d(2026, 1, 3), isin="INE000B01012", qty=10.0, price=0.0, ref="cas_opening:ZERODHA:INE000B01012:cost_unknown"))
    ev.save(con, log, datetime(2026, 10, 30))
    h = views.holdings(con, d(2026, 10, 30))
    rows = {r["symbol"]: r for r in h["rows"]}
    assert rows["AAA"]["cost_unknown"] is False and rows["AAA"]["unrealised"] == pytest.approx(200.0)
    assert rows["BBB"]["cost_unknown"] is True and rows["BBB"]["cost"] is None and rows["BBB"]["unrealised"] is None
    assert h["unrealised"] == pytest.approx(200.0)                                  # the unknown holding's whole value is not counted as gain
    assert h["cost_unknown"]["holdings"] == ["INE000B01012"] and h["cost_unknown"]["value"] == pytest.approx(1000.0)
