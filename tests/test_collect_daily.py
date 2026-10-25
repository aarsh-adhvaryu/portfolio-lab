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


def test_liveness_check_never_signals_on_windows(monkeypatch):
    """os.kill(pid, 0) on Windows is a Ctrl+C to the whole console (it killed the overnight run, 2026-10-16)."""
    import subprocess
    import sys
    from pflab import _lock
    if os.name != "nt":
        pytest.skip("Windows-only behaviour")
    monkeypatch.setattr(os, "kill", lambda *a: pytest.fail("os.kill must not be called on Windows"))
    assert _lock._alive(str(os.getpid()))
    done = subprocess.run([sys.executable, "-c", "pass"])
    assert done.returncode == 0
    assert not _lock._alive("999999") and not _lock._alive("") and not _lock._alive("abc")


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
    """BSE and GDELT endpoints are E2 and unverified; they must not page the investor."""
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


# -- corporate actions: merge, never overwrite (2026-09-28) --------------
def test_daily_corporate_actions_keeps_every_existing_factor(root, monkeypatch):
    """A daily run re-parses PURPOSE text only. It must keep every stored
    PREVCLOSE factor and every stored PURPOSE row the fresh parse lacks."""
    from datetime import date
    import pandas as pd
    from pflab.data import nse_corporate_actions as nca
    na = float("nan")
    stored = pd.DataFrame({
        "isin": ["INE000A", "INE000B", "INE000C", "INE000D"],
        "ex_date": [date(2020, 1, 2), date(2020, 2, 3), date(2021, 3, 4), date(2019, 5, 6)],
        "factor": [0.5, 0.0805, 2.0, 0.25],
        "bonus_factor": [0.5, na, na, 1.0],
        "source": ["purpose", "prevclose", "prevclose", "purpose"],
        "prior_close": [na, 304.2, 10.0, na],
        "adj_prev_close": [na, 24.5, 20.0, na]})
    nca.write(stored, root)
    fresh = pd.DataFrame({"isin": ["INE000A", "INE000E"],
                          "ex_date": [date(2020, 1, 2), date(2026, 9, 25)],
                          "factor": [0.5, 0.2], "bonus_factor": [0.5, 1.0]})
    monkeypatch.setattr(nca, "collect", lambda *a, **k: None)
    monkeypatch.setattr(nca, "factors", lambda r=None, **k: fresh)
    collect_daily._corporate_actions(date(2026, 9, 25), date(2026, 9, 27), root)
    out = nca.load(root)
    got = set(zip(out["isin"], pd.to_datetime(out["ex_date"]).dt.date, out["source"]))
    want = set(zip(stored["isin"], stored["ex_date"], stored["source"])) | {
        ("INE000E", date(2026, 9, 25), "purpose")}
    assert got == want and len(out) == 5
    pc = out[out["source"] == "prevclose"].set_index("isin")
    assert pc.loc["INE000B", "adj_prev_close"] == 24.5


def test_vix_update_tops_up_the_stored_series(tmp_path):
    from datetime import date
    import pandas as pd
    from pflab.data import india_vix
    (tmp_path / "indices").mkdir()
    old = pd.DataFrame({"date": pd.date_range("2026-09-01", "2026-09-21").date, "open": 11.0, "high": 12.0,
                        "low": 10.0, "close": 11.5, "source": "nse"})
    old.to_parquet(tmp_path / "indices" / "INDIA_VIX.parquet", index=False)
    asked = {}

    def fake(start, end=None):
        asked["start"] = start
        d = pd.date_range("2026-09-15", "2026-10-16").date
        return pd.DataFrame({"date": d, "open": 12.0, "high": 13.0, "low": 11.0, "close": 12.5})
    r = india_vix.update(tmp_path, fetch=fake)
    out = pd.read_parquet(tmp_path / "indices" / "INDIA_VIX.parquet")
    assert asked["start"] == date(2026, 9, 11)                       # only the last 10 days are re-fetched
    assert r["last"] == "2026-10-16" and out["date"].is_unique and len(out) == 10 + 32
    assert (out.set_index("date").loc[date(2026, 9, 20), "close"] == 12.5)   # the refetched days replace the old
