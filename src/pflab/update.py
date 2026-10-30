r"""`pflab update` and `pflab update --rollback`: the app updates like an app (S65, docs/PLAN.md section 3).

The app is a clone of the private GitHub repo checked out at a release tag (`vYYYY.MM.DD`, or `vYYYY.MM.DD.N`), with a
`release.toml` (src/pflab/release.py). An update, in order:

    1. refuse in the workshop (no release.toml), while another process holds the store, or with edited files in the clone
    2. back up the store (`ledger.duckdb`) into `<app folder>\backups` (never overwritten)
    3. `git fetch --tags`, pick the newest tag, `git checkout` it, install the requirements
    4. self-test: the program starts, and the new code's migrations are REHEARSED on a COPY of the store (nothing of his is touched
       until they pass; no table may lose a row)
    5. write release.toml (new tag, `previous_tag` = the old one, `backup` = the file of step 2)
    A failure at 3 or 4 puts the old tag back and the store as it was (the backup), and says so.

`--rollback` returns to `previous_tag` and restores the backup of the last update. S67: it then brings back every row written
since the update (rows whose key is not in the backup, table by table, over the columns both versions know), so no ledger event, journal
entry, question or memory made after the upgrade is lost. The store as it was just before the rollback is kept beside it as
`ledger_before_rollback_<date>.duckdb` (nothing is deleted); a table the older version does not have stays only in that file, and this is
said in the result. The live store migrates at the next start, with the backup already taken.
Git, the installer and the self-test are passed in so the whole thing is tested on a temporary repository.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from pflab import release

TAG_RE = re.compile(r"^v\d{4}\.\d{2}\.\d{2}(\.\d+)?$")
Run = Callable[[List[str], Path], Tuple[int, str]]


class UpdateError(RuntimeError):
    pass


def run_cmd(cmd: List[str], cwd: Path) -> Tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr).strip()


def _python(root: Path) -> str:
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        if (Path(root) / rel).exists():
            return str(Path(root) / rel)
    return sys.executable


def default_install(root: Path, run: Run = run_cmd) -> None:
    """The exact library versions the release's tests passed on (requirements.lock), then the program itself without dependencies."""
    lock = Path(root) / "requirements.lock"
    if lock.exists():
        rc, out = run([_python(root), "-m", "pip", "install", "--quiet", "-r", "requirements.lock"], root)
        if rc:
            raise UpdateError(f"installing requirements.lock failed: {out[-300:]}")
    rc, out = run([_python(root), "-m", "pip", "install", "--quiet", "--no-deps", "-e", "."] if lock.exists()
                  else [_python(root), "-m", "pip", "install", "-e", ".", "--quiet"], root)
    if rc:
        raise UpdateError(f"installing the requirements failed: {out[-300:]}")
    import shutil
    if shutil.which("docker") and (Path(root) / "sandbox" / "Dockerfile").exists():   # audit F2: the image carries the runner; it is rebuilt with the release
        rc, out = run(["docker", "build", "-q", "-t", "pflab-sandbox:2", "-f", "sandbox/Dockerfile", "."], root)
        if rc:                                                # not fatal: the sandbox probe then names the stale image and nothing generated runs
            print(f"the sandbox image was not rebuilt ({out[-160:]}); calculations wait until it is")


def default_selftest(root: Path, run: Run = run_cmd, pm_dir: Optional[Path] = None) -> Tuple[bool, str]:
    """The program starts (new code, new libraries), and its migrations run on a COPY of the store: they must pass and no table may lose a
    row. The real store is not opened here."""
    rc, out = run([_python(root), "-m", "pflab.cli", "--help"], root)
    if rc:
        return False, f"the program does not start: {out[-200:]}"
    live = Path(pm_dir) / "ledger.duckdb" if pm_dir is not None else None
    if live is None or not live.exists():
        return True, "program starts; no store yet to rehearse on"
    tmp = Path(tempfile.mkdtemp(prefix="pflab_rehearse_"))
    try:
        copy = tmp / "ledger.duckdb"
        shutil.copy2(live, copy)
        rc, out = run([_python(root), "-m", "pflab.update", "rehearse", str(copy)], root)
        return rc == 0, out[-300:]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _row_counts(path: Path) -> dict:
    import duckdb
    con = duckdb.connect(str(path), read_only=True)
    try:
        return {t: int(con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]) for (t,) in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE'").fetchall()}
    finally:
        con.close()


def rehearse(copy: Path) -> dict:
    """Migrate a COPY of the store with this code and compare: {version, tables, lost: {table: rows lost}}. Raises if a migration fails."""
    from pflab.pm import store
    before = _row_counts(Path(copy))
    con = store.connect(Path(copy))
    version = con.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
    con.close()
    after = _row_counts(Path(copy))
    lost = {t: before[t] - after.get(t, 0) for t in before if after.get(t, 0) < before[t]}
    return {"version": version, "tables": len(after), "lost": lost, "rows": sum(after.values())}


DERIVED = ("lots", "cash_ledger", "income", "fees")             # written by the ledger rebuild from the events; read from the events elsewhere


def rebuild_derived(db: Path) -> dict:
    """Rewrite the tables computed from the events (DERIVED) in a prepared store and reconcile them: the open lots must equal the positions a
    replay of the events gives. Raises when they do not (audit F7: a rollback had kept the backup's lots beside newer events)."""
    import duckdb
    from pflab.ledger import events as ev
    from pflab.ledger.book import Ledger
    from pflab.pm import store
    con = duckdb.connect(str(db))
    try:
        have = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}
        if not {"events", "lots"} <= have:
            return {"events": 0, "positions": 0, "skipped": "no ledger tables in this store"}
        log = ev.load(con)
        led = Ledger.replay(log)
        with store.transaction(con):
            led.write_derived(con)
        want = {k: round(float(q), 6) for k, q in led.positions().items() if abs(q) > 1e-9}
        have = {(a, i): round(float(q), 6) for a, i, q in con.execute(
            "SELECT account_id, isin, sum(qty) FROM lots WHERE qty <> 0 GROUP BY 1, 2").fetchall() if abs(q) > 1e-9}
        if want != have:
            bad = sorted(set(want.items()) ^ set(have.items()))[:5]
            raise UpdateError(f"the rebuilt lots do not match the events: {bad}")
        return {"events": len(log.events) if hasattr(log, "events") else None, "positions": len(want)}
    finally:
        con.close()


def merge_new_rows(kept: Path, live: Path) -> dict:
    """Bring back what happened after the backup: for each table both stores have, over the columns both know, the rows of `kept` that are
    new (added), the rows whose values changed (updated: the later version wins) and the rows `kept` no longer has (deleted: a deletion
    is not undone). A table without a key is compared whole rows; the events by everything but their ids, so a correction replaces the
    old version instead of standing beside it. A table that cannot be reconciled is listed under `errors` and left as the backup has it.
    Returns {added, updated, deleted, errors, only_in_kept, rows}; `rows` counts the rows added."""
    import duckdb
    con = duckdb.connect(str(live))
    try:
        con.execute(f"ATTACH '{Path(kept).as_posix()}' AS kept (READ_ONLY)")
        live_cols = {t: [c for (c,) in con.execute("SELECT column_name FROM information_schema.columns WHERE table_catalog = current_database() "
                                                   "AND table_schema='main' AND table_name=? ORDER BY ordinal_position", [t]).fetchall()]
                     for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog = current_database() "
                                             "AND table_schema='main' AND table_type='BASE TABLE'").fetchall()}
        kept_cols = {t: [c for (c,) in con.execute("SELECT column_name FROM information_schema.columns WHERE table_catalog='kept' "
                                                   "AND table_schema='main' AND table_name=? ORDER BY ordinal_position", [t]).fetchall()]
                     for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog='kept' "
                                             "AND table_schema='main' AND table_type='BASE TABLE'").fetchall()}
        added, only_kept, updated, deleted, errors = {}, sorted(set(kept_cols) - set(live_cols)), {}, {}, {}
        for t in sorted(set(live_cols) & set(kept_cols)):
            if t == "schema_migrations" or t in DERIVED:
                continue                                          # derived from the events (the ledger rebuild writes them): not merged
            cols = [c for c in live_cols[t] if c in kept_cols[t]]
            if not cols:
                continue
            lst = ", ".join(f'"{c}"' for c in cols)
            if t == "events":
                # a ledger rebuild renumbers events, so an id says nothing: an event is the same event when everything but its id and the
                # time it was stored is the same; the ones that are new get the next ids
                nat = [c for c in cols if c not in ("event_id", "ingested_at")]
                nl = ", ".join(f'"{c}"' for c in nat)
                top = con.execute('SELECT coalesce(max(event_id), 0) FROM "events"').fetchone()[0]
                rows = con.execute(f'SELECT {nl}, "ingested_at" FROM (SELECT {nl}, "ingested_at" FROM kept."events" k WHERE NOT EXISTS '
                                   f'(SELECT 1 FROM "events" l WHERE ' + " AND ".join(f'l."{c}" IS NOT DISTINCT FROM k."{c}"' for c in nat) + ")) ORDER BY 1").fetchall()
                for k, r in enumerate(rows, 1):
                    con.execute(f'INSERT INTO "events" ("event_id", {nl}, "ingested_at") VALUES (' + ",".join("?" * (len(nat) + 2)) + ")", [top + k, *r])
                if rows:
                    added[t] = len(rows)
                try:                                              # an event the later store no longer has (a corrected one) is not kept beside its fix
                    gone = con.execute('SELECT count(*) FROM "events" l WHERE NOT EXISTS (SELECT 1 FROM kept."events" k WHERE '
                                       + " AND ".join(f'l."{c}" IS NOT DISTINCT FROM k."{c}"' for c in nat) + ")").fetchone()[0]
                    if gone:
                        con.execute('DELETE FROM "events" WHERE event_id IN (SELECT event_id FROM "events" l WHERE NOT EXISTS (SELECT 1 FROM kept."events" k WHERE '
                                    + " AND ".join(f'l."{c}" IS NOT DISTINCT FROM k."{c}"' for c in nat) + "))")
                        deleted[t] = int(gone)
                except Exception as e:
                    errors[t] = f"{type(e).__name__}: {str(e)[:120]}"
                continue
            pk = [c for (c,) in con.execute("SELECT unnest(constraint_column_names) FROM duckdb_constraints() WHERE database_name = current_database() "
                                            "AND table_name=? AND constraint_type='PRIMARY KEY'", [t]).fetchall()]
            if pk and all(c in cols for c in pk):
                key = ", ".join(f'"{c}"' for c in pk)
                n = con.execute(f'INSERT INTO "{t}" ({lst}) SELECT {lst} FROM kept."{t}" k WHERE NOT EXISTS '
                                f'(SELECT 1 FROM "{t}" l WHERE ' + " AND ".join(f'l."{c}" = k."{c}"' for c in pk) + ")").fetchone()
            else:
                n = con.execute(f'INSERT INTO "{t}" ({lst}) SELECT {lst} FROM (SELECT {lst} FROM kept."{t}" EXCEPT SELECT {lst} FROM "{t}")').fetchone()
            if n and n[0]:
                added[t] = int(n[0])
            if pk and all(c in cols for c in pk):
                same = " AND ".join(f'l."{c}" = k."{c}"' for c in pk)
                try:
                    rest = [c for c in cols if c not in pk]
                    if rest:                                      # changed after the backup: the later version stands
                        diff = " OR ".join(f'l."{c}" IS DISTINCT FROM k."{c}"' for c in rest)
                        m = con.execute(f'SELECT count(*) FROM "{t}" l JOIN kept."{t}" k ON {same} WHERE {diff}').fetchone()[0]
                        if m:
                            con.execute(f'UPDATE "{t}" SET ' + ", ".join(f'"{c}" = k."{c}"' for c in rest)
                                        + f' FROM kept."{t}" k WHERE ' + " AND ".join(f'"{t}"."{c}" = k."{c}"' for c in pk))
                            updated[t] = int(m)
                    g = con.execute(f'SELECT count(*) FROM "{t}" l WHERE NOT EXISTS (SELECT 1 FROM kept."{t}" k WHERE {same})').fetchone()[0]
                    if g:                                         # removed after the backup: not brought back
                        con.execute(f'DELETE FROM "{t}" WHERE NOT EXISTS (SELECT 1 FROM kept."{t}" k WHERE '
                                    + " AND ".join(f'"{t}"."{c}" = k."{c}"' for c in pk) + ")")
                        deleted[t] = int(g)
                except Exception as e:
                    errors[t] = f"{type(e).__name__}: {str(e)[:120]}"
        con.execute("DETACH kept")
        return {"added": added, "updated": updated, "deleted": deleted, "errors": errors, "only_in_kept": only_kept,
                "rows": sum(added.values())}
    finally:
        con.close()


def _git(run: Run, root: Path, *args: str) -> str:
    rc, out = run(["git", *args], root)
    if rc:
        raise UpdateError(f"git {' '.join(args)} failed: {out[-300:]}")
    return out


def tags(root: Path, run: Run = run_cmd) -> List[str]:
    """Release tags, newest first."""
    out = _git(run, root, "tag", "--list", "v*", "--sort=-v:refname")
    return [t for t in out.splitlines() if TAG_RE.match(t.strip())]


def checked_out(root: Path, run: Run = run_cmd) -> str:
    rc, out = run(["git", "describe", "--tags", "--exact-match"], root)
    return out.strip() if rc == 0 else ""


def _set_release(root: Path, tag: str, previous: str, backup: str) -> None:
    r = release.load(root) or {}
    app = r.get("app") or {}
    release.write(root, Path(app.get("folder", root.parent)), tag, previous, app.get("channel", "stable"))
    if backup:
        p = release.path(root)
        p.write_text(p.read_text(encoding="utf-8").replace("\n[paths]", f'backup = \'{backup}\'\n\n[paths]', 1), encoding="utf-8")


def backup_store(pm_dir: Path, folder: Path, tag: str, now: Optional[datetime] = None) -> Path:
    """Copy the ledger beside the app (never over an earlier backup)."""
    now = now or datetime.now()
    src = Path(pm_dir) / "ledger.duckdb"
    dst_dir = Path(folder) / "backups"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"ledger_before_{tag or 'update'}_{now:%Y%m%d_%H%M%S}.duckdb"
    if src.exists():
        shutil.copy2(src, dst)
    return dst


def _guard(root: Path, pm_dir: Path) -> dict:
    r = release.load(root)
    if r is None:
        raise UpdateError("this is the workshop (no release.toml): it is the source of releases, not an app to update")
    from pflab.pm import reset
    if reset.holds_store(pm_dir):
        raise UpdateError("another process holds the store (the dashboard, the bot or a job): close it first")
    return r


def update(root: Path, pm_dir: Path, run: Run = run_cmd, install: Optional[Callable[[Path], None]] = None,
           selftest: Optional[Callable[[Path], Tuple[bool, str]]] = None, check_only: bool = False,
           now: Optional[datetime] = None) -> dict:
    root, pm_dir = Path(root), Path(pm_dir)
    r = _guard(root, pm_dir)
    app = r.get("app") or {}
    cur = str(app.get("tag", "")) or checked_out(root, run)
    if _git(run, root, "status", "--porcelain").strip():
        raise UpdateError("the app's folder has edited files: an app is never edited (git status shows them)")
    _git(run, root, "fetch", "--tags", "--force", "origin")
    found = tags(root, run)
    if not found:
        raise UpdateError("no release tags on GitHub yet")
    newest = found[0]
    out = {"from": cur, "newest": newest, "updated": False}
    if newest == cur or (cur in found and found.index(cur) <= found.index(newest)):
        out["note"] = f"already on the newest release ({cur})"
        return out
    if check_only:
        out["note"] = f"{newest} is available (you are on {cur or 'no tag'}); run pflab update to install it"
        return out
    bk = backup_store(pm_dir, Path(app.get("folder", root.parent)), cur, now)
    out["backup"] = str(bk)
    try:
        _git(run, root, "checkout", "--detach", newest)
        (install or (lambda p: default_install(p, run)))(root)
        ok, msg = (selftest or (lambda p: default_selftest(p, run, pm_dir)))(root)
        if not ok:
            raise UpdateError(f"the self-test failed on {newest}: {msg}")
    except Exception as e:
        _back_out(root, pm_dir, run, cur, bk, install)
        out["error"] = f"{type(e).__name__}: {e}"
        out["note"] = f"update to {newest} failed and was undone: back on {cur or 'the old code'}, the store restored from {bk.name}"
        return out
    _set_release(root, newest, cur, str(bk))
    out.update(updated=True, note=f"updated {cur or '(untagged)'} -> {newest}; the store was backed up first ({bk.name}); "
                                  "undo with pflab update --rollback")
    return out


def _back_out(root: Path, pm_dir: Path, run: Run, tag: str, backup: Path, install) -> None:
    """Put the old tag and the old store back after a failed update."""
    if tag:
        run(["git", "checkout", "--detach", tag], root)
        try:
            (install or (lambda p: default_install(p, run)))(root)
        except Exception:
            pass
    if backup.exists():
        shutil.copy2(backup, Path(pm_dir) / "ledger.duckdb")


def rollback(root: Path, pm_dir: Path, run: Run = run_cmd, install: Optional[Callable[[Path], None]] = None,
             now: Optional[datetime] = None) -> dict:
    root, pm_dir = Path(root), Path(pm_dir)
    r = _guard(root, pm_dir)
    app = r.get("app") or {}
    prev, bk = str(app.get("previous_tag", "")), str(app.get("backup", ""))
    if not prev:
        raise UpdateError("there is no earlier release to return to (previous_tag is empty)")
    now = now or datetime.now()
    kept = None
    live = pm_dir / "ledger.duckdb"
    cand = None
    merged = None
    if bk and Path(bk).exists():
        # S67 local: the restored store is PREPARED beside the live one (backup + everything done since, reconciled) and checked; the live
        # store is replaced only when that is whole. If it cannot be made safely, nothing changes: same code, same store, and it says why.
        cand = pm_dir / "ledger.rollback_candidate.duckdb"
        cand.unlink(missing_ok=True)
        shutil.copy2(bk, cand)
        if live.exists():
            kept = Path(app.get("folder", root.parent)) / "backups" / f"ledger_before_rollback_{now:%Y%m%d_%H%M%S}.duckdb"
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(live, kept)
            try:
                merged = merge_new_rows(kept, cand)
                if merged.get("errors"):
                    raise UpdateError("tables could not be reconciled: " + "; ".join(f"{t}: {e}" for t, e in merged["errors"].items()))
                rebuild_derived(cand)                         # audit F7: lots, cash, income and fees follow the merged events, checked, before the switch
                _row_counts(cand)                             # the prepared store opens and every table can be counted
            except Exception as e:
                cand.unlink(missing_ok=True)
                raise UpdateError(f"the rollback was not done: the earlier release's store could not be prepared safely "
                                  f"({type(e).__name__}: {str(e)[:200]}). Nothing was changed; the current store is kept whole "
                                  f"(a copy is also in {kept.name}).")
    cur = str(app.get("tag", ""))
    inst = install or (lambda p: default_install(p, run))
    _git(run, root, "checkout", "--detach", prev)
    inst(root)
    rebuilt_by = None
    if cand is not None and merged is not None:
        # audit F7: the tables computed from the events are rebuilt by the EARLIER release's own code (the one that will read them), in its own
        # Python, and reconciled there. An earlier release without this command keeps the rebuild already made and checked above, and says so.
        rc, out = run([_python(root), "-m", "pflab.update", "rebuild", str(cand)], root)
        if rc == 0:
            rebuilt_by = prev
        elif "usage" in out.lower():
            rebuilt_by = f"the newer code ({prev} has no rebuild command); checked against the events"
        else:
            try:                                            # nothing may change: back to the release that was running, the store untouched
                _git(run, root, "checkout", "--detach", cur)
                inst(root)
            finally:
                cand.unlink(missing_ok=True)
            raise UpdateError(f"the rollback was not done: {prev} could not rebuild the store's figures ({out[-200:]}). "
                              f"Nothing was changed; {cur} and its store are as they were.")
    if cand is not None:
        import os
        os.replace(cand, live)
    _set_release(root, prev, "", "")
    note = f"back on {prev}" + (f"; holdings, cash and income rebuilt by {rebuilt_by} and checked against the events" if rebuilt_by else "")
    if kept:
        note += f"; the store is the backup from before the update"
        if merged and not merged.get("error"):
            ch = sum((merged.get("updated") or {}).values()), sum((merged.get("deleted") or {}).values())
            note += (f", plus the {merged['rows']} row(s) written since the update"
                     + (f", {ch[0]} changed row(s) and {ch[1]} removal(s) carried over" if ch[0] or ch[1] else "")
                     + (f" (tables the older version does not have stay only in {kept.name}: {', '.join(merged['only_in_kept'])})"
                        if merged["only_in_kept"] else "")
                     + f"; the store as it was is also kept in {kept.name} (nothing was deleted)")
        else:
            note += (f"; what was written since could NOT be merged back ({(merged or {}).get('error', 'unknown')}): it is all in {kept.name} "
                     "(nothing was deleted)")
    return {"from": cur, "to": prev, "note": note, "kept": str(kept) if kept else None, "merged": merged}


def main(argv=None) -> int:
    """`python -m pflab.update rehearse <store copy>`: what the update's self-test runs with the NEW code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] == "rebuild":
        r = rebuild_derived(Path(argv[1]))
        print(f"rebuilt and reconciled: {r}")
        return 0
    if len(argv) == 2 and argv[0] == "rehearse":
        r = rehearse(Path(argv[1]))
        print(f"migrated a copy to schema v{r['version']}: {r['tables']} tables, {r['rows']:,} rows")
        if r["lost"]:
            print(f"ROWS LOST: {r['lost']}")
            return 1
        return 0
    print("usage: python -m pflab.update rehearse <store copy>")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
