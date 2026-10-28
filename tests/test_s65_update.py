"""S65 Phase 8 (the split): `pflab update` and `--rollback` on a temporary git repository: backup first, tags, undo on failure."""
import subprocess
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from pflab import release, update as up
from pflab.pm import reset

NOW = datetime(2026, 10, 28, 9, 0, 0)


def g(cwd, *args) -> str:
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args], cwd=str(cwd),
                       capture_output=True, text=True, check=True)
    return p.stdout.strip()


def publish(work: Path, version: str, tag: str) -> None:
    (work / "version.txt").write_text(version, encoding="utf-8")
    g(work, "add", "-A")
    g(work, "commit", "-qm", f"release {tag}")
    g(work, "tag", tag)
    g(work, "push", "-q", "origin", "HEAD:main", "--tags")


@pytest.fixture
def world(tmp_path):
    origin, work, folder = tmp_path / "origin.git", tmp_path / "work", tmp_path / "PortfolioLabApp"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    g(tmp_path, "clone", "-q", str(origin), str(work))
    g(work, "checkout", "-q", "-b", "main")
    (work / ".gitignore").write_text("release.toml\n", encoding="utf-8")
    publish(work, "one", "v2026.10.01")
    app = folder / "app"
    folder.mkdir()
    g(folder, "clone", "-q", str(origin), str(app))
    g(app, "checkout", "-q", "--detach", "v2026.10.01")
    release.write(app, folder, "v2026.10.01")
    pm = folder / "pm"
    pm.mkdir()
    con = duckdb.connect(str(pm / "ledger.duckdb"))
    con.execute("CREATE TABLE record (note VARCHAR)")
    con.execute("INSERT INTO record VALUES ('before')")
    con.close()
    return SimpleNS(origin=origin, work=work, folder=folder, app=app, pm=pm)


class SimpleNS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def notes(pm: Path):
    con = duckdb.connect(str(pm / "ledger.duckdb"))
    try:
        return [r[0] for r in con.execute("SELECT note FROM record ORDER BY rowid").fetchall()]
    finally:
        con.close()


def ok_install(root):
    pass


def good(root):
    return True, "ok"


def test_an_update_backs_up_first_moves_to_the_newest_tag_and_records_it(world):
    publish(world.work, "two", "v2026.10.15")
    r = up.update(world.app, world.pm, install=ok_install, selftest=good, now=NOW)
    assert r["updated"] and r["from"] == "v2026.10.01" and r["newest"] == "v2026.10.15"
    assert (world.app / "version.txt").read_text(encoding="utf-8") == "two"
    rel = release.load(world.app)["app"]
    assert rel["tag"] == "v2026.10.15" and rel["previous_tag"] == "v2026.10.01" and rel["channel"] == "stable"
    bk = Path(rel["backup"])
    assert bk.exists() and bk.parent == world.folder / "backups" and "ledger_before_v2026.10.01_20261028_090000" in bk.name
    assert up.checked_out(world.app) == "v2026.10.15"
    assert Path(release.load(world.app)["paths"]["pm"]) == world.pm                                   # the paths survive the rewrite


def test_nothing_to_do_when_already_newest_and_check_only_changes_nothing(world):
    assert "already on the newest" in up.update(world.app, world.pm, install=ok_install, selftest=good)["note"]
    publish(world.work, "two", "v2026.10.15")
    c = up.update(world.app, world.pm, check_only=True)
    assert not c["updated"] and "v2026.10.15 is available" in c["note"]
    assert (world.app / "version.txt").read_text(encoding="utf-8") == "one" and not (world.folder / "backups").exists()


def test_tags_are_sorted_by_version_and_only_release_tags_count(world):
    publish(world.work, "x", "v2026.10.09")
    publish(world.work, "y", "v2026.10.15.2")
    publish(world.work, "z", "v2026.10.15")
    g(world.work, "tag", "experiment")
    g(world.work, "push", "-q", "origin", "--tags")
    g(world.app, "fetch", "-q", "--tags")
    assert up.tags(world.app) == ["v2026.10.15.2", "v2026.10.15", "v2026.10.09", "v2026.10.01"]


def test_a_failed_self_test_undoes_the_update_and_restores_the_store(world):
    publish(world.work, "two", "v2026.10.15")
    con = duckdb.connect(str(world.pm / "ledger.duckdb"))
    con.execute("INSERT INTO record VALUES ('written by a migration that went wrong')")
    con.close()

    def bad(root):
        return False, "schema v99 not understood"
    r = up.update(world.app, world.pm, install=ok_install, selftest=bad, now=NOW)
    assert not r["updated"] and "self-test failed" in r["error"] and "undone" in r["note"]
    assert (world.app / "version.txt").read_text(encoding="utf-8") == "one" and up.checked_out(world.app) == "v2026.10.01"
    assert notes(world.pm) == ["before", "written by a migration that went wrong"]            # the store is as it was before the update
    assert release.load(world.app)["app"]["tag"] == "v2026.10.01"


def test_a_failed_install_is_undone_too(world):
    publish(world.work, "two", "v2026.10.15")

    def boom(root):
        if (root / "version.txt").read_text(encoding="utf-8") == "two":
            raise up.UpdateError("pip failed")
    r = up.update(world.app, world.pm, install=boom, selftest=good, now=NOW)
    assert not r["updated"] and "pip failed" in r["error"] and (world.app / "version.txt").read_text(encoding="utf-8") == "one"


def test_rollback_returns_to_the_previous_tag_and_keeps_what_was_written_since(world):
    publish(world.work, "two", "v2026.10.15")
    up.update(world.app, world.pm, install=ok_install, selftest=good, now=NOW)
    con = duckdb.connect(str(world.pm / "ledger.duckdb"))
    con.execute("INSERT INTO record VALUES ('after the update')")
    con.close()
    r = up.rollback(world.app, world.pm, install=ok_install, now=datetime(2026, 10, 29, 8, 0, 0))
    assert r["to"] == "v2026.10.01" and up.checked_out(world.app) == "v2026.10.01"
    assert (world.app / "version.txt").read_text(encoding="utf-8") == "one"
    assert notes(world.pm) == ["before"]                                                       # the store before the update
    kept = Path(r["kept"])
    assert kept.exists() and "ledger_before_rollback_20261029_080000" in kept.name
    con = duckdb.connect(str(kept))
    assert [x[0] for x in con.execute("SELECT note FROM record ORDER BY rowid").fetchall()] == ["before", "after the update"]
    con.close()
    assert "nothing was deleted" in r["note"]
    rel = release.load(world.app)["app"]
    assert rel["tag"] == "v2026.10.01" and rel["previous_tag"] == ""
    with pytest.raises(up.UpdateError, match="no earlier release"):
        up.rollback(world.app, world.pm, install=ok_install)


def test_it_refuses_in_the_workshop_with_edited_files_or_while_the_store_is_held(world, monkeypatch):
    with pytest.raises(up.UpdateError, match="workshop"):
        up.update(world.work, world.pm, install=ok_install, selftest=good)
    (world.app / "version.txt").write_text("edited by hand", encoding="utf-8")
    with pytest.raises(up.UpdateError, match="edited files"):
        up.update(world.app, world.pm, install=ok_install, selftest=good)
    g(world.app, "checkout", "--", "version.txt")
    monkeypatch.setattr(reset, "holds_store", lambda p: True)
    with pytest.raises(up.UpdateError, match="holds the store"):
        up.update(world.app, world.pm, install=ok_install, selftest=good)
    with pytest.raises(up.UpdateError, match="holds the store"):
        up.rollback(world.app, world.pm, install=ok_install)
    assert not (world.folder / "backups").exists()                                              # refused before touching anything


def test_the_release_file_is_not_an_edit(world):
    publish(world.work, "two", "v2026.10.15")
    assert g(world.app, "status", "--porcelain") == ""                                          # release.toml is ignored by git
    assert up.update(world.app, world.pm, install=ok_install, selftest=good)["updated"]
