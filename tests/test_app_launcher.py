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
