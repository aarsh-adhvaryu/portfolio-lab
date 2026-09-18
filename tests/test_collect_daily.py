"""Daily collector job and the shared PID lock (Phase 1 task 1.7)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import collect_daily  # noqa: E402

from pflab._lock import FileLock, LockBusy  # noqa: E402


# -- lock ---------------------------------------------------------------
def test_lock_is_released_on_exit(tmp_path):
    p = tmp_path / "x.lock"
    with FileLock(p, "job"):
        assert p.exists()
    assert not p.exists()


def test_lock_refuses_a_live_holder(tmp_path):
    p = tmp_path / "x.lock"
    p.write_text(f"{os.getpid()} now", encoding="utf-8")
    with pytest.raises(LockBusy, match="already running"):
        with FileLock(p, "job"):
            pass


def test_lock_clears_a_stale_holder(tmp_path):
    """A machine that lost power leaves a lock behind; it must not wedge."""
    p = tmp_path / "x.lock"
    p.write_text("999999 long ago", encoding="utf-8")
    with FileLock(p, "job"):
        assert p.read_text(encoding="utf-8").startswith(str(os.getpid()))


def test_lock_released_even_when_the_body_raises(tmp_path):
    p = tmp_path / "x.lock"
    with pytest.raises(RuntimeError):
        with FileLock(p, "job"):
            raise RuntimeError("boom")
    assert not p.exists()


# -- job orchestration --------------------------------------------------
@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(collect_daily, "data_dir", lambda: tmp_path)
    return tmp_path


def _sources(monkeypatch, mapping):
    monkeypatch.setattr(collect_daily, "SOURCES", mapping)


def test_all_sources_succeed(root, monkeypatch, capsys):
    calls = []
    _sources(monkeypatch, {"bhavcopy": lambda s, e, r: calls.append("b") or {"ok": 1},
                           "gdelt": lambda s, e, r: calls.append("g") or {"ok": 2}})
    assert collect_daily.main(["--days", "2"]) == 0
    assert calls == ["b", "g"]


def test_non_critical_failure_does_not_fail_the_job(root, monkeypatch):
    """BSE and GDELT endpoints are E2 and unverified; they must not page Aarsh."""
    def boom(s, e, r):
        raise RuntimeError("endpoint moved")
    _sources(monkeypatch, {"bhavcopy": lambda s, e, r: {"ok": 1}, "gdelt": boom})
    assert collect_daily.main(["--days", "1"]) == 0


def test_critical_failure_sets_a_nonzero_exit(root, monkeypatch):
    def boom(s, e, r):
        raise RuntimeError("NSE down")
    _sources(monkeypatch, {"bhavcopy": boom, "gdelt": lambda s, e, r: {"ok": 1}})
    assert collect_daily.main(["--days", "1"]) == 1


def test_one_source_failing_still_runs_the_rest(root, monkeypatch):
    seen = []

    def boom(s, e, r):
        seen.append("bse")
        raise RuntimeError("nope")
    _sources(monkeypatch, {"bse": boom, "gdelt": lambda s, e, r: seen.append("gdelt")})
    collect_daily.main(["--days", "1"])
    assert seen == ["bse", "gdelt"]


def test_every_attempt_is_journalled(root, monkeypatch):
    def boom(s, e, r):
        raise RuntimeError("nope")
    _sources(monkeypatch, {"bhavcopy": lambda s, e, r: {"ok": 3}, "gdelt": boom})
    collect_daily.main(["--days", "1"])
    lines = (root / "_daily" / "collect_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    import json
    recs = [json.loads(x) for x in lines]
    assert [r["ok"] for r in recs] == [True, False]
    assert "nope" in recs[1]["error"]


def test_busy_lock_exits_two_without_running_anything(root, monkeypatch):
    (root / "_daily").mkdir(parents=True, exist_ok=True)
    (root / "_daily" / "collect.lock").write_text(f"{os.getpid()} now", encoding="utf-8")
    ran = []
    _sources(monkeypatch, {"bhavcopy": lambda s, e, r: ran.append("b")})
    assert collect_daily.main(["--days", "1"]) == 2
    assert ran == []


def test_unknown_source_is_rejected(root):
    assert collect_daily.main(["--sources", "nope"]) == 1


def test_bhavcopy_and_corporate_actions_are_the_critical_ones():
    """Charter section 15 made factors load-bearing: a missed split silently
    misadjusts the panel, so a stale feed is a critical failure."""
    assert collect_daily.CRITICAL == {"bhavcopy", "corporate_actions"}
    assert "bse" not in collect_daily.CRITICAL
    assert "gdelt" not in collect_daily.CRITICAL
