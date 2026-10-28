"""The desktop shortcut's launcher: a start-up failure is logged and shown (pythonw has no console), in plain words when
the ledger is held by another program; children end with the system (checked in a separate process)."""
import subprocess
import sys

from pflab.app import launcher as la
from pflab.pm import store


def test_a_held_ledger_is_explained():
    assert "open in another Portfolio Lab program" in la.why(OSError('IO Error: Could not set lock on file "ledger.duckdb"'))
    assert "being used by another process" not in la.why(ValueError("boom")) and "boom" in la.why(ValueError("boom"))


def test_a_start_failure_is_logged_and_shown(tmp_path, monkeypatch, caplog):
    shown = []
    monkeypatch.setattr(store, "pm_dir", lambda: tmp_path)
    monkeypatch.setattr(la, "alert", shown.append)

    def broken(pm, log):
        raise OSError("Could not set lock on file")
    monkeypatch.setattr(la, "_run", broken)
    assert la.main() == 1
    assert shown and "Close it" in shown[0]
    assert "start failed" in caplog.text


def test_children_end_with_the_system():
    code = ("import subprocess, sys; from pflab.app import launcher as la; assert la.end_children_with_me() is not None; "
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); print(p.pid, flush=True)")
    pid = int(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60).stdout.split()[0])
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    assert str(pid) not in out                               # the parent exited: its child was ended with it


def test_the_one_icon_takes_a_new_release_at_start_and_only_in_the_app(monkeypatch):
    """S65: no "Portfolio Lab Update" icon: the launcher runs `pflab update` first and starts again on a new tag."""
    import logging
    from types import SimpleNamespace
    from pflab import release
    log = logging.getLogger("t")
    state = {"tag": "v2026.10.28.5"}
    monkeypatch.setattr(release, "load", lambda root=None: {"app": {"tag": state["tag"]}})
    calls = []

    def run(cmd, **k):
        calls.append(cmd[-2:])
        state["tag"] = "v2026.10.28.6"
        return SimpleNamespace(returncode=0, stdout="updated", stderr="")
    assert la.update_first(log, run) == "v2026.10.28.6" and calls == [["pflab.cli", "update"]]
    assert la.update_first(log, lambda cmd, **k: SimpleNamespace(returncode=1, stdout="refused: another process holds the store",
                                                                 stderr="")) is None          # starts as it is
    assert la.update_first(log, lambda cmd, **k: (_ for _ in ()).throw(OSError("offline"))) is None
    monkeypatch.setattr(release, "load", lambda root=None: None)                            # the workshop never updates itself
    assert la.update_first(log, lambda cmd, **k: 1 / 0) is None


def test_the_icon_waits_for_a_background_run_to_let_go_of_the_record(tmp_path):
    """S66: a double-click while the tick holds the record waits (the window says "starting"), then starts; it gives up after the limit."""
    import logging
    log, held = logging.getLogger("t"), [True, True, False]
    slept = []
    assert la.wait_for_store(tmp_path, log, free=lambda: not held.pop(0), sleep=slept.append) is True and slept == [5, 5]
    assert la.wait_for_store(tmp_path, log, free=lambda: True, sleep=slept.append) is True
    slept.clear()
    assert la.wait_for_store(tmp_path, log, free=lambda: False, sleep=slept.append, limit_s=15) is False and len(slept) == 3
