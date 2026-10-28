"""S65 Phase 7 item 8: `pflab pm reset` moves his record aside, never deletes it, and refuses while the store is held."""
from datetime import date

import pytest

from pflab.pm import reset as rs
from pflab.pm import store

TODAY = date(2026, 10, 28)


@pytest.fixture
def pm(tmp_path):
    p = tmp_path / "pm"
    (p / "reports").mkdir(parents=True)
    store.connect(p / "ledger.duckdb").close()
    (p / "targets.toml").write_text("x = 1\n", encoding="utf-8")
    (p / "reports" / "morning.md").write_text("report", encoding="utf-8")
    return p


def test_without_the_word_it_only_lists(pm):
    r = rs.reset(pm, TODAY)
    assert not r["moved"] and "erase-my-record" in r["note"] and pm.exists()
    assert {n for n, _ in r["files"]} >= {"ledger.duckdb", "targets.toml", "reports\\morning.md" if "\\" in str(pm) else "reports/morning.md"}
    assert (pm / "ledger.duckdb").exists()


def test_with_the_word_the_folder_is_moved_whole_and_an_empty_one_is_left(pm):
    r = rs.reset(pm, TODAY, rs.CONFIRM)
    old = pm.parent / "pm_old_20261028"
    assert r["moved"] and r["to"] == str(old) and old.is_dir()
    assert (old / "ledger.duckdb").exists() and (old / "targets.toml").read_text(encoding="utf-8") == "x = 1\n"
    assert pm.is_dir() and list(pm.iterdir()) == []                                              # empty, ready for a fresh start
    assert "delete it yourself" in r["note"]


def test_a_second_reset_the_same_day_does_not_overwrite_the_first(pm):
    rs.reset(pm, TODAY, rs.CONFIRM)
    (pm / "targets.toml").write_text("y = 2\n", encoding="utf-8")
    r = rs.reset(pm, TODAY, rs.CONFIRM)
    assert r["to"].endswith("pm_old_20261028_2") and (pm.parent / "pm_old_20261028" / "ledger.duckdb").exists()


def test_it_refuses_while_the_store_is_held_and_moves_nothing(pm, monkeypatch):
    monkeypatch.setattr(rs, "holds_store", lambda p: True)
    with pytest.raises(RuntimeError, match="holds the store"):
        rs.reset(pm, TODAY, rs.CONFIRM)
    assert (pm / "ledger.duckdb").exists() and not (pm.parent / "pm_old_20261028").exists()


def test_a_missing_folder_is_an_error_not_a_creation(tmp_path):
    with pytest.raises(FileNotFoundError):
        rs.reset(tmp_path / "nope", TODAY, rs.CONFIRM)
    assert not (tmp_path / "nope").exists()
