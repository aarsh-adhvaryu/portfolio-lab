"""S58b switch-on: the scheduled tick stands aside while the dashboard runs the jobs, and obeys the dashboard's
settings (its preset; held messages stay held until Telegram is switched on)."""
import os

from pflab import cli
from pflab.app import settings as st
from pflab.service import runner


def test_the_tick_stands_aside_while_the_dashboard_is_open(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "app.lock").write_text(f"{os.getpid()} 2026-10-24 14:02:48", encoding="utf-8")
    assert runner.dashboard_running(tmp_path).startswith(str(os.getpid()))
    called = []
    monkeypatch.setattr(runner, "make_ctx", lambda *a, **k: called.append(1))
    assert cli.main(["service", "tick"]) == 0 and called == []                      # never opened the ledger
    assert "the dashboard is open" in capsys.readouterr().out
    (tmp_path / "app" / "app.lock").write_text("999999999 2026-10-24 14:02:48", encoding="utf-8")   # a dead holder
    assert runner.dashboard_running(tmp_path) is None


def test_stale_held_messages_can_be_dropped_before_telegram_goes_on(tmp_path, monkeypatch, capsys):
    from datetime import datetime

    from pflab.pm import store
    from pflab.service import telegram as tgm
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    con = store.connect()
    tgm.enqueue(con, "old wake note", "guard", now=datetime(2026, 10, 17, 9, 0))
    tgm.enqueue(con, "today's research", "guard", now=datetime(2026, 10, 24, 9, 0))
    con.close()
    assert cli.main(["pm", "alerts", "--drop-before", "2026-10-24"]) == 0 and "1 held message" in capsys.readouterr().out
    con = store.connect()
    assert [t for _i, _k, t, _a in tgm.pending(con)] == ["today's research"]
    sent = []
    tgm.flush(con, sent.append)
    assert sent == ["today's research"]                                              # the dropped one never goes out


def test_the_tick_obeys_the_dashboards_settings(tmp_path, monkeypatch, capsys):
    only = runner.unattended_jobs(tmp_path)
    assert "outbox" not in only and "collect" in only and "conductor" in only        # messages held by default
    st.save(tmp_path, {"telegram_send": True})
    assert "outbox" in runner.unattended_jobs(tmp_path)
    st.save(tmp_path, {"preset": "light"})
    assert set(runner.unattended_jobs(tmp_path)) == set(st.LIGHT_JOBS)              # data and checks only
    st.save(tmp_path, {"preset": "off"})
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    monkeypatch.setattr(runner, "make_ctx", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    assert cli.main(["service", "tick"]) == 0 and "Off" in capsys.readouterr().out
