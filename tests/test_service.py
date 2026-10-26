"""S9: schedule slots, job engine (idempotence, catch-up, cooldown, locks), Telegram outbox with a MOCKED
transport, backup, health. Nothing here contacts Telegram, the network, Task Scheduler or a real backup target."""
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from pflab.monitor import filings
from pflab.pm import secrets as sec
from pflab.pm import store
from pflab.service import backup as bk
from pflab.service import health, jobs, runner
from pflab.service import telegram as tgm
from pflab.service.schedule import Daily, Interval

WED = datetime(2026, 10, 7, 21, 0)          # a Wednesday evening


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "ledger.duckdb")


def ctx_of(con, tmp_path, now, secrets=None):
    return jobs.Ctx(con, now, tmp_path, tmp_path / "data", tmp_path, "python", secrets)


# --- schedule ---------------------------------------------------------------------------------------------

def test_daily_latest_slot_weekdays_and_weekends():
    d = Daily(19, 30)
    assert d.latest_slot(datetime(2026, 10, 7, 21, 0)) == datetime(2026, 10, 7, 19, 30)
    assert d.latest_slot(datetime(2026, 10, 7, 19, 29)) == datetime(2026, 10, 6, 19, 30)         # not yet today
    assert d.latest_slot(datetime(2026, 10, 10, 12, 0)) == datetime(2026, 10, 9, 19, 30)         # Saturday -> Friday
    assert d.latest_slot(datetime(2026, 10, 12, 8, 0)) == datetime(2026, 10, 9, 19, 30)          # Monday morning -> Friday
    assert Daily(23, 30, weekdays_only=False).latest_slot(datetime(2026, 10, 10, 12, 0)) == datetime(2026, 10, 9, 23, 30)
    assert Daily(23, 30, weekdays_only=False).latest_slot(datetime(2026, 10, 10, 23, 31)) == datetime(2026, 10, 10, 23, 30)


def test_interval_slots_inside_the_window():
    i = Interval(60, 8, 22)
    assert i.latest_slot(datetime(2026, 10, 7, 13, 25)) == datetime(2026, 10, 7, 13, 0)
    assert i.latest_slot(datetime(2026, 10, 7, 23, 50)) == datetime(2026, 10, 7, 21, 0)          # after the window: last slot
    assert i.latest_slot(datetime(2026, 10, 7, 6, 0)) == datetime(2026, 10, 6, 21, 0)            # before it: yesterday's last
    assert i.latest_slot(datetime(2026, 10, 10, 12, 0)) == datetime(2026, 10, 9, 21, 0)          # weekend
    assert Interval(15).latest_slot(datetime(2026, 10, 7, 10, 44)) == datetime(2026, 10, 7, 10, 30)


# --- job engine ---------------------------------------------------------------------------------------------

def make_job(calls, name="j", fn=None, **kw):
    def default(ctx):
        calls.append(ctx.now)
        return {"n": len(calls)}
    return jobs.Job(name, kw.pop("schedule", Daily(19, 30)), fn or default, **kw)


@pytest.fixture(autouse=True)
def clean_registry():
    saved = dict(jobs.REGISTRY)
    jobs.REGISTRY.clear()
    yield
    jobs.REGISTRY.clear()
    jobs.REGISTRY.update(saved)


def test_job_runs_once_per_slot_then_is_idle(con, tmp_path):
    calls = []
    jobs.register(make_job(calls))
    c = ctx_of(con, tmp_path, WED)
    assert [r.status for r in jobs.tick(c)] == ["ok"] and len(calls) == 1
    assert jobs.tick(c) == [] and jobs.tick(ctx_of(con, tmp_path, WED + timedelta(hours=1))) == []     # idempotent within the slot
    nxt = ctx_of(con, tmp_path, datetime(2026, 10, 8, 19, 31))                                            # next day's slot
    assert [r.status for r in jobs.tick(nxt)] == ["ok"] and len(calls) == 2


def test_catch_up_after_sleep_runs_once_not_once_per_missed_day(con, tmp_path):
    calls = []
    jobs.register(make_job(calls))
    jobs.tick(ctx_of(con, tmp_path, datetime(2026, 10, 2, 20, 0)))                       # Friday
    woke = ctx_of(con, tmp_path, datetime(2026, 10, 7, 9, 0))                            # laptop asleep until Wednesday
    assert [r.status for r in jobs.tick(woke)] == ["ok"] and len(calls) == 2             # one run, for Tuesday's slot
    assert jobs.tick(woke) == []


def test_lookback_covers_the_gap(con, tmp_path):
    calls = []
    jobs.register(make_job(calls, name="collect"))
    jobs.tick(ctx_of(con, tmp_path, datetime(2026, 10, 2, 20, 0)))
    c = ctx_of(con, tmp_path, datetime(2026, 10, 7, 9, 0))
    assert c.lookback_days("collect") == 6                                               # 4 whole days since + 2 margin
    assert c.lookback_days("never_ran") == 40 and c.lookback_days("collect", minimum=10) == 10


def test_failure_is_recorded_not_fatal_and_cools_down(con, tmp_path):
    n = []

    def boom(ctx):
        n.append(1)
        raise RuntimeError("endpoint down")

    jobs.register(make_job([], name="bad", fn=boom, cooldown_minutes=30))
    ok = []
    jobs.register(make_job(ok, name="good"))
    r = jobs.tick(ctx_of(con, tmp_path, WED))
    assert {x.job: x.status for x in r} == {"bad": "failed", "good": "ok"}               # one failure does not stop the others
    assert "endpoint down" in r[0].detail
    assert jobs.tick(ctx_of(con, tmp_path, WED + timedelta(minutes=10))) == []           # cooling down
    again = jobs.tick(ctx_of(con, tmp_path, WED + timedelta(minutes=31)))
    assert [x.job for x in again] == ["bad"] and len(n) == 2                              # retried after the cooldown


def test_secrets_never_reach_the_job_record(con, tmp_path):
    s = sec.Secrets({"telegram": {"token": "SECRET-TOKEN-123", "chat_id": "42"}})

    def leaks(ctx):
        raise RuntimeError("POST failed for https://api.telegram.org/botSECRET-TOKEN-123/sendMessage")

    jobs.register(make_job([], name="leaky", fn=leaks))
    r = jobs.tick(ctx_of(con, tmp_path, WED, secrets=s))
    assert "SECRET-TOKEN-123" not in r[0].detail and "***" in r[0].detail
    assert "SECRET-TOKEN-123" not in str(con.execute("SELECT detail FROM job_runs").fetchall())


def test_a_second_instance_is_skipped_while_the_lock_is_held(con, tmp_path):
    calls = []
    j = make_job(calls)
    jobs.register(j)
    from pflab._lock import FileLock
    with FileLock(tmp_path / "locks" / "j.lock", "j"):
        r = jobs.run_job(ctx_of(con, tmp_path, WED), j)
        assert r.status == "skipped" and "already running" in r.detail and calls == []
    assert jobs.run_job(ctx_of(con, tmp_path, WED), j).status == "ok"


def test_died_process_is_reaped_as_failed(con, tmp_path):
    con.execute("INSERT INTO job_runs VALUES (99, 'j', NULL, ?, NULL, 'running', NULL)", [WED - timedelta(hours=3)])
    assert jobs.reap_abandoned(con, WED) == 1
    assert con.execute("SELECT status, detail FROM job_runs WHERE run_id=99").fetchone() == ("failed", "abandoned: the process died")


def test_disabled_job_is_idle_and_run_is_skipped(con, tmp_path):
    calls = []
    j = make_job(calls, enabled_fn=lambda c: (False, "no target"))
    jobs.register(j)
    c = ctx_of(con, tmp_path, WED)
    assert jobs.tick(c) == [] and jobs.run_job(c, j).status == "skipped" and calls == []
    assert jobs.plan(c)[0]["why"] == "disabled: no target"


def test_a_job_that_finds_nothing_to_do_satisfies_the_slot(con, tmp_path):
    jobs.register(make_job([], fn=lambda c: {"skipped": True, "why": "nothing"}))
    c = ctx_of(con, tmp_path, WED)
    assert [r.status for r in jobs.tick(c)] == ["skipped"] and jobs.tick(c) == []


def test_registered_jobs_include_the_planned_set_with_backup_gated():
    import importlib

    from pflab.service import tasks
    importlib.reload(tasks)
    assert {"collect", "prices", "nav", "filings", "outbox", "backup"} <= set(jobs.REGISTRY)
    assert jobs.REGISTRY["backup"].enabled_fn is not None


# --- telegram -----------------------------------------------------------------------------------------------------

class Wire:
    """A mock Bot API: records every request, answers from a script."""

    def __init__(self, *answers):
        self.sent, self.answers = [], list(answers)

    def __call__(self, url, payload):
        self.sent.append((url, payload))
        return self.answers.pop(0) if self.answers else (200, {"ok": True})


def secrets_of(tmp_path, token="123:ABCSECRET", chat="777"):
    f = tmp_path / "secrets.toml"
    f.write_text(f'[telegram]\ntoken = "{token}"\nchat_id = "{chat}"\n')
    return sec.load(f)


def test_send_posts_to_the_bot_api_with_token_and_chat(tmp_path):
    w = Wire()
    s = secrets_of(tmp_path)
    tgm.make_sender(s, w)("hello")
    url, payload = w.sent[0]
    assert url == "https://api.telegram.org/bot123:ABCSECRET/sendMessage"
    assert payload == {"chat_id": "777", "text": "hello", "disable_web_page_preview": True}


def test_long_messages_are_split_on_lines():
    text = "\n".join(f"line {i:04d} " + "x" * 90 for i in range(200))
    parts = tgm.split_message(text, 4096)
    assert len(parts) > 1 and all(len(p) <= 4096 for p in parts) and "\n".join(parts) == text
    assert tgm.split_message("short") == ["short"]
    assert [len(p) for p in tgm.split_message("a" * 9000, 4096)] == [4096, 4096, 808]


def test_rate_limit_waits_retry_after_then_succeeds(tmp_path):
    waits = []
    w = Wire((429, {"parameters": {"retry_after": 3}}), (200, {"ok": True}))
    tgm.make_sender(secrets_of(tmp_path), w, sleep=waits.append)("x")
    assert waits == [3.0] and len(w.sent) == 2


def test_permanent_error_raises_with_the_token_scrubbed(tmp_path):
    w = Wire((401, {"description": "Unauthorized: bad token 123:ABCSECRET"}))
    with pytest.raises(RuntimeError) as e:
        tgm.make_sender(secrets_of(tmp_path), w)("x")
    assert "123:ABCSECRET" not in str(e.value) and "401" in str(e.value)


def test_unconfigured_sender_says_so():
    with pytest.raises(tgm.TelegramNotConfigured):
        tgm.make_sender(None)("x")


def test_outbox_delivers_oldest_first_and_dedups(con, tmp_path):
    assert tgm.enqueue(con, "first", "guard", "k1") == 1 and tgm.enqueue(con, "second", "guard", "k2") == 2
    assert tgm.enqueue(con, "first again", "guard", "k1") is None                            # same key: not queued twice
    w = Wire()
    out = tgm.flush(con, tgm.make_sender(secrets_of(tmp_path), w))
    assert out == {"sent": 2, "still_pending": 0, "failed": 0}
    assert [p["text"] for _, p in w.sent] == ["first", "second"] and tgm.undelivered(con) == 0


def test_failed_delivery_stays_queued_then_fails_visibly(con, tmp_path):
    tgm.enqueue(con, "msg", "guard", "k")
    send = tgm.make_sender(secrets_of(tmp_path), Wire(*[(500, {"description": "oops"})] * 10))
    for i in range(tgm.MAX_ATTEMPTS - 1):
        assert tgm.flush(con, send)["still_pending"] == 1
    assert tgm.flush(con, send) == {"sent": 0, "still_pending": 0, "failed": 1}
    assert tgm.undelivered(con) == 1                                                       # failed still counts as undelivered
    assert con.execute("SELECT status, attempts FROM outbox").fetchone() == ("failed", tgm.MAX_ATTEMPTS)


def test_no_config_keeps_everything_pending(con):
    tgm.enqueue(con, "msg", "guard", "k")
    out = tgm.flush(con, tgm.make_sender(None))
    assert out["still_pending"] == 1 and "not in the secrets file" in out["error"] and tgm.undelivered(con) == 1


def test_a_test_alert_arrives(con, tmp_path):
    tgm.enqueue(con, tgm.format_test(), "test", "t1")
    w = Wire()
    tgm.flush(con, tgm.make_sender(secrets_of(tmp_path), w))
    assert "test alert" in w.sent[0][1]["text"] and "No action needed" in w.sent[0][1]["text"]


def test_filing_alert_message_carries_the_evidence_link(con, tmp_path):
    a = filings.Alert("e1", "INE111A01011", "Acme Ltd", "DEFAULT", "Disclosure of default on NCD interest",
                      datetime(2026, 9, 22, 10, 5), "https://www.bseindia.com/xml-data/corpfiling/AttachLive/x.pdf",
                      ["Past: 8 similar events, median 21-day CAR -4.1%"])
    tgm.enqueue(con, a.text(), "guard", a.event_id)
    w = Wire()
    tgm.flush(con, tgm.make_sender(secrets_of(tmp_path), w))
    t = w.sent[0][1]["text"]
    assert "Acme Ltd: Default" in t and "AttachLive/x.pdf" in t and "22-Sep-2026 10:05" in t and "You decide" in t


def test_failed_job_is_reported_once_and_delivered(con, tmp_path):
    jobs.register(make_job([], name="bad", fn=lambda c: (_ for _ in ()).throw(RuntimeError("down"))))
    w = Wire()
    c = ctx_of(con, tmp_path, WED, secrets_of(tmp_path))
    runner.tick_and_notify(c, send=tgm.make_sender(c.secrets, w))
    assert len(w.sent) == 1 and "job 'bad' failed" in w.sent[0][1]["text"]
    runner.tick_and_notify(ctx_of(con, tmp_path, WED + timedelta(minutes=45), c.secrets), send=tgm.make_sender(c.secrets, w))
    assert len(w.sent) == 2                                                                  # second failure after cooldown: a new run id


# --- backup ---------------------------------------------------------------------------------------------------------------

def test_backup_verifies_prunes_and_restores(tmp_path):
    pm = tmp_path / "pm"
    con = store.connect(pm / "ledger.duckdb")
    con.execute("INSERT INTO accounts (account_id, kind) VALUES ('A', 'demat')")
    tgt = tmp_path / "usb" / "pflab"
    for k in range(4):
        r = bk.backup(con, pm / "ledger.duckdb", tgt, datetime(2026, 10, 1 + k, 23, 30), keep=3)
    assert r["tables"] > 10 and r["pruned"] == 1 and len(bk.listing(tgt)) == 3
    f, when = bk.latest(tgt)
    assert when == datetime(2026, 10, 4, 23, 30)
    res = bk.restore_check(f, tmp_path / "scratch")
    assert res["counts"]["accounts"] == 1 and res["tables"] == r["tables"]


def test_backup_refuses_a_target_inside_the_pm_dir(tmp_path):
    con = store.connect(tmp_path / "pm" / "ledger.duckdb")
    with pytest.raises(bk.BackupError, match="inside the PM directory"):
        bk.backup(con, tmp_path / "pm" / "ledger.duckdb", tmp_path / "pm" / "backups", WED)


def test_backup_that_does_not_match_is_deleted(tmp_path, monkeypatch):
    con = store.connect(tmp_path / "pm" / "ledger.duckdb")
    real = bk._counts
    calls = {"n": 0}

    def tampered(p):
        calls["n"] += 1
        c = real(p)
        if calls["n"] == 1:
            c["accounts"] = c.get("accounts", 0) + 1
        return c

    monkeypatch.setattr(bk, "_counts", tampered)
    with pytest.raises(bk.BackupError, match="does not match"):
        bk.backup(con, tmp_path / "pm" / "ledger.duckdb", tmp_path / "usb", WED)
    assert bk.listing(tmp_path / "usb") == []


def test_backup_target_comes_from_env_or_config(tmp_path, monkeypatch):
    monkeypatch.delenv("PFLAB_BACKUP_DIR", raising=False)
    cfg = tmp_path / "service.toml"
    cfg.write_text('[backup]\ntarget = ""\nkeep = 7\n')
    assert bk.target_dir(cfg) is None and bk.keep_count(cfg) == 7
    cfg.write_text('[backup]\ntarget = "E:/pflab"\n')
    assert bk.target_dir(cfg) == Path("E:/pflab")
    monkeypatch.setenv("PFLAB_BACKUP_DIR", str(tmp_path / "env"))
    assert bk.target_dir(cfg) == tmp_path / "env"
    assert bk.target_dir(Path(__file__).parents[1] / "configs" / "service.toml") == tmp_path / "env"


def test_shipped_service_config_has_no_backup_target(monkeypatch):
    monkeypatch.delenv("PFLAB_BACKUP_DIR", raising=False)
    assert bk.target_dir() is None                           # disabled until the investor sets one


# --- health ------------------------------------------------------------------------------------------------------------------

def test_health_warns_on_missing_backup_and_fails_on_a_failed_job(con, tmp_path, monkeypatch):
    monkeypatch.delenv("PFLAB_BACKUP_DIR", raising=False)
    import importlib

    from pflab.service import tasks
    importlib.reload(tasks)
    c = ctx_of(con, tmp_path, WED)
    items = {i.name: i for i in health.check(c)}
    assert items["backup"].status == "WARN" and "NO backup" in items["backup"].detail
    assert items["job:backup"].status == "WARN" and items["telegram config"].status == "WARN"
    assert health.overall(list(items.values())) == "WARN"
    con.execute("INSERT INTO job_runs VALUES (1, 'collect', ?, ?, ?, 'failed', 'boom')", [WED, WED, WED])
    items = {i.name: i for i in health.check(c)}
    assert items["job:collect"].status == "FAIL" and "boom" in items["job:collect"].detail
    assert health.overall(list(items.values())) == "FAIL"
    assert "FAIL" in health.render(list(items.values()), WED)


def test_health_data_freshness(con, tmp_path):
    from pflab.pm import prices
    prices.load_bhavcopy(con, pd.DataFrame([(date(2026, 10, 7), "INE000000011", "EQ", 10.0)], columns=["date", "isin", "series", "close"]))
    items = {i.name: i for i in health.check(ctx_of(con, tmp_path, WED))}
    assert items["prices"].status == "OK"
    items = {i.name: i for i in health.check(ctx_of(con, tmp_path, datetime(2026, 10, 9, 21, 0)))}      # Friday evening: 2 days behind
    assert items["prices"].status == "WARN" and "behind" in items["prices"].detail
    items = {i.name: i for i in health.check(ctx_of(con, tmp_path, datetime(2026, 10, 20, 21, 0)))}
    assert items["prices"].status == "FAIL"


def test_health_backup_age(con, tmp_path):
    pm = tmp_path / "pm"
    c2 = store.connect(pm / "ledger.duckdb")
    tgt = tmp_path / "usb"
    bk.backup(c2, pm / "ledger.duckdb", tgt, WED - timedelta(hours=2))
    ctx = jobs.Ctx(con, WED, pm, tmp_path / "data", tmp_path)
    assert {i.name: i for i in health.check(ctx, backup_target=tgt)}["backup"].status == "OK"
    ctx2 = jobs.Ctx(con, WED + timedelta(days=3), pm, tmp_path / "data", tmp_path)
    assert {i.name: i for i in health.check(ctx2, backup_target=tgt)}["backup"].status == "FAIL"
    assert {i.name: i for i in health.check(ctx, backup_target=tmp_path / "empty")}["backup"].status == "FAIL"


def test_cli_service_status_and_plan(tmp_path, monkeypatch, capsys):
    import importlib

    from pflab import cli
    from pflab.service import tasks
    importlib.reload(tasks)                                  # the autouse fixture emptied the registry
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.delenv("PFLAB_BACKUP_DIR", raising=False)
    assert cli.main(["service", "plan"]) == 0
    assert "collect" in capsys.readouterr().out
    assert cli.main(["service", "status"]) == 0
    assert "Portfolio Manager health" in capsys.readouterr().out
    assert cli.main(["service", "run", "nope"]) == 2
    assert cli.main(["service", "backup"]) == 2
