r"""A fresh start that can be undone (S67 local): `pflab pm fresh`.

Builds a NEW personal profile (an empty, migrated store with its own checkpoints, activation pending until the icon is clicked) and
puts the old profile in a verified recovery archive. Nothing is read for its meaning: files are copied and hashed as opaque bytes.
What is kept in the new store is only what must survive so a fresh start cannot reopen a spent test or reset spending: the learner's
test counter (`learn_tests`: how many variants were searched) and a reduced spend record (`api_calls`: when, which model, what it cost;
the question and the request text, which can hold his portfolio, are not carried). The old statements, ledger, accounts, holdings,
graph, embeddings, recommendations, personal findings and watch folders stay in the archive; the new profile never reads them, and
bringing one file back later is a deliberate step (`restore`), not a fallback.

Order: check the store is not held -> copy and hash everything into the archive -> verify the copy -> move the old folder aside (never
deleted) -> create the new profile. Any failure before the move leaves the old profile exactly where it was. The manifest it writes is
sanitized: sizes, hashes, extensions and salted-hash names, never file names (those can hold account ids; the real names are in a
private file inside the archive).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from pflab.pm import reset

CONFIRM = "start-fresh"
# His CHOICES, not his history (2026-10-30: the first fresh start left them behind and the new profile sat idle: no targets, no watch list,
# no analyst, no cap). They go with him into a new profile; the data they were built on does not.
CHOICES = ("api_budget.toml", "targets.toml", "targets_notes.md", "stock_list.toml", "theme_baskets.toml", "groups.toml",
           "fd_holdings.toml")      # (2026-10-31) the deposits he typed are in no statement: left behind, his deposits counted for nothing


def carry_choices(src_pm: Path, dst_pm: Path) -> list:
    """Copy each choice file the new profile does not have yet. Returns the names copied."""
    done = []
    for name in CHOICES:
        s, d = Path(src_pm) / name, Path(dst_pm) / name
        if s.is_file() and not d.exists():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
            done.append(name)
    return done


def restore_missing_choices(pm_dir: Path) -> list:
    """A profile made by an earlier fresh start that lacks his choices takes each missing one from the newest earlier profile beside it that has
    it (`pm_old_*`, moved aside, never deleted). Runs at every start; does nothing once they are there."""
    pm_dir = Path(pm_dir)
    olds = sorted((p for p in pm_dir.parent.glob(pm_dir.name + "_old_*") if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    done = []
    for name in CHOICES:
        if (pm_dir / name).exists():
            continue
        src = next((p for p in olds if (p / name).is_file()), None)
        if src is not None:
            shutil.copy2(src / name, pm_dir / name)
            done.append(f"{name} from {src.name}")
    return done


KEEP_AUDIT = ("learn_tests",)                          # copied whole: counts and thresholds of searches, no personal text
SPEND_COLUMNS = ("call_id", "created_at", "mode", "model", "topic", "status", "batch_id", "input_tokens", "output_tokens",
                 "cost_usd", "cost_inr", "finished_at")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(root: Path) -> List[dict]:
    """Every file under `root` as opaque bytes: relative path, size, sha256. No file is opened for its content except to hash it."""
    root = Path(root)
    return [{"path": str(p.relative_to(root)).replace("\\", "/"), "bytes": p.stat().st_size, "sha256": _sha(p)}
            for p in sorted(root.rglob("*")) if p.is_file()]


def _salted(name: str, salt: str) -> str:
    return hashlib.sha256((salt + name).encode()).hexdigest()[:16]


def sanitized(inv: List[dict], salt: str) -> List[dict]:
    return [{"name": _salted(i["path"], salt), "ext": Path(i["path"]).suffix.lower(), "bytes": i["bytes"], "sha256": i["sha256"]} for i in inv]


def archive(pm_dir: Path, dest: Path, extra: Optional[Dict[str, Path]] = None, now: Optional[datetime] = None) -> dict:
    """Copy the profile (and any named extra folders, such as the downloaded statements) into `dest`, hash both sides and compare.
    `dest` must not exist and must not be inside a folder being archived. Returns the sanitized manifest; raises if any copy differs."""
    now = now or datetime.now()
    dest = Path(dest)
    if dest.exists():
        raise FileExistsError(f"{dest} exists: an archive is never written over")
    sources = {"pm": Path(pm_dir), **{k: Path(v) for k, v in (extra or {}).items()}}
    for name, src in sources.items():
        if not src.exists():
            raise FileNotFoundError(f"{src} does not exist")
        if dest.resolve() == src.resolve() or src.resolve() in dest.resolve().parents:
            raise ValueError(f"the archive may not sit inside {name} ({src}): it would be searched by the new profile")
    dest.mkdir(parents=True)
    salt = hashlib.sha256(f"{now.isoformat()}{os.urandom(8).hex()}".encode()).hexdigest()[:12]
    private, public = {}, {}
    try:
        for name, src in sources.items():
            inv = inventory(src)
            for i in inv:
                target = dest / name / i["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / i["path"], target)
                if _sha(target) != i["sha256"]:
                    raise RuntimeError(f"the copy of one file differs from the original ({_salted(i['path'], salt)}): archive refused")
            private[name], public[name] = inv, sanitized(inv, salt)
        (dest / "names.private.json").write_text(json.dumps({k: [i["path"] for i in v] for k, v in private.items()}), encoding="utf-8")
        manifest = {"made": now.isoformat(timespec="seconds"), "salt_id": salt, "folders": {k: {"files": len(v), "bytes": sum(i["bytes"] for i in v)}
                                                                                              for k, v in public.items()}, "files": public}
        (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)                       # only the half-made archive; the originals were never touched
        raise
    return manifest


def verify_archive(dest: Path) -> dict:
    """Re-hash the archive against its own manifest: {ok, files, problems}. Needs no original."""
    dest = Path(dest)
    m = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    names = json.loads((dest / "names.private.json").read_text(encoding="utf-8"))
    problems, n = [], 0
    for folder, entries in m["files"].items():
        for e, rel in zip(entries, names[folder]):
            n += 1
            f = dest / folder / rel
            if not f.is_file() or f.stat().st_size != e["bytes"] or _sha(f) != e["sha256"]:
                problems.append(e["name"])
    return {"ok": not problems, "files": n, "problems": problems}


def new_profile(new_dir: Path, old_ledger: Optional[Path], profile: str) -> dict:
    """An empty, migrated store plus the audit rows that must survive, and activation pending. Returns what was carried."""
    import duckdb
    from pflab import activation
    from pflab.pm import store
    new_dir = Path(new_dir)
    new_dir.mkdir(parents=True, exist_ok=True)
    con = store.connect(new_dir / "ledger.duckdb")
    carried: Dict[str, int] = {}
    if old_ledger and Path(old_ledger).exists():
        con.execute(f"ATTACH '{Path(old_ledger).as_posix()}' AS old (READ_ONLY)")
        have = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog='old' AND table_schema='main'").fetchall()}
        def common(t: str) -> str:
            mine = [r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_catalog=current_database() "
                                              "AND table_schema='main' AND table_name=? ORDER BY ordinal_position", [t]).fetchall()]
            theirs = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_catalog='old' "
                                                "AND table_schema='main' AND table_name=?", [t]).fetchall()}
            return ", ".join(f'"{c}"' for c in mine if c in theirs)
        for t in KEEP_AUDIT:
            if t in have:
                cols = common(t)
                con.execute(f'INSERT INTO "{t}" ({cols}) SELECT {cols} FROM old."{t}"')
                carried[t] = int(con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0])
        if "api_calls" in have:
            keep = [c for c in SPEND_COLUMNS if c in common("api_calls")]
            cols = ", ".join(keep)
            con.execute(f"INSERT INTO api_calls (question, request_sha, request_json, {cols}) SELECT '[archived]', 'archived', '', {cols} FROM old.api_calls")
            carried["api_calls"] = int(con.execute("SELECT count(*) FROM api_calls").fetchone()[0])
        con.execute("DETACH old")
    con.close()
    if old_ledger:
        carried["choices"] = len(carry_choices(Path(old_ledger).parent, new_dir))
    activation.write_pending(new_dir, profile=profile)
    return carried


def old_inputs(repo: Path, data_root: Optional[Path] = None) -> Dict[str, Path]:
    """The app-owned places outside the profile that hold inputs of the old profile (audit F1): the folder the inbox keeps ledger documents in, the
    watched drop folder, and the text of emails kept for the knowledge graph. Market data is not personal and stays."""
    from pflab.hq import watcher
    out = {"documents": Path(repo) / "new", "drop": watcher.folder(Path(repo))}
    if data_root is not None:
        out["mail_text"] = Path(data_root) / "kg" / "mail"
    return out


def _quarantine(name: str, folder: Path, today: date, shared: bool, dest_root: Path) -> Optional[str]:
    """Move what the old profile left in `folder` aside, so the new profile cannot pick it up; nothing is deleted. An app-owned folder is renamed;
    a folder he chose himself (PFLAB_DROP_DIR) keeps its other content and only its files move into a dated subfolder."""
    folder = Path(folder)
    if not folder.exists() or not any(folder.iterdir()):
        return None
    if shared:
        aside = folder / f"_before_fresh_{today:%Y%m%d}"
        aside.mkdir(exist_ok=True)
        for p in [x for x in folder.iterdir() if x.is_file()]:
            os.replace(p, aside / p.name)
        return str(aside)
    # an app-owned folder goes beside the archive (outside the app's checkout, where an extra folder would stop the next update)
    aside = Path(dest_root) / f"inputs_{today:%Y%m%d}" / name
    n = 1
    while aside.exists():
        n += 1
        aside = Path(dest_root) / f"inputs_{today:%Y%m%d}_{n}" / name
    aside.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(folder), str(aside))
    folder.mkdir(parents=True, exist_ok=True)
    return str(aside)


def fresh(pm_dir: Path, archive_root: Path, today: date, confirm: str = "", extra: Optional[Dict[str, Path]] = None,
          inputs: Optional[Dict[str, Path]] = None) -> dict:
    """Do the whole fresh start. Without the confirmation word it only says what it would do.

    Order (audit F1, 2026-10-30): the new profile is BUILT FIRST beside the old one, with its pending gate inside; then the old profile is archived and
    verified; then the old inputs outside the profile are moved aside; only then are the two folders swapped. A failure before the swap leaves the old
    profile exactly as it was (the half-built new one is removed); there is never an empty active folder without its gate."""
    pm_dir, archive_root = Path(pm_dir), Path(archive_root)
    files = reset.listing(pm_dir)
    inputs = dict(inputs or {})
    out = {"from": str(pm_dir), "files": len(files), "bytes": sum(b for _, b in files), "done": False,
           "inputs": {k: str(v) for k, v in inputs.items()}}
    if confirm != CONFIRM:
        out["note"] = (f"nothing changed: pass --confirm {CONFIRM} to archive this profile and begin a new one; old inputs that will be moved aside: "
                       + (", ".join(f"{k} {v}" for k, v in inputs.items()) or "none"))
        return out
    if reset.holds_store(pm_dir):
        raise RuntimeError("another process holds the store (the dashboard, the bot or a job): close it first")
    staging = pm_dir.parent / f"{pm_dir.name}_new_{today:%Y%m%d}"
    if staging.exists():
        shutil.rmtree(staging)                                      # a half-built one from an interrupted try: never the active profile
    try:
        carried = new_profile(staging, pm_dir / "ledger.duckdb", f"profile_{today:%Y%m%d}")
        from pflab import activation
        if not activation.is_pending(staging):
            raise RuntimeError("the new profile has no pending gate")
        dest = archive_root / f"profile_{today:%Y%m%d}"
        n = 1
        while dest.exists():
            n += 1
            dest = archive_root / f"profile_{today:%Y%m%d}_{n}"
        archive(pm_dir, dest, extra)
        v = verify_archive(dest)
        if not v["ok"]:
            raise RuntimeError(f"the archive did not verify ({len(v['problems'])} file(s)): the old profile was not moved")
        drop_env = bool(os.environ.get("PFLAB_DROP_DIR"))
        moved_inputs = {k: _quarantine(k, p, today, shared=(k == "drop" and drop_env), dest_root=archive_root) for k, p in inputs.items()}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    aside = reset.target_for(pm_dir, today)
    os.replace(pm_dir, aside)                                       # moved, not deleted; the verified archive is the second copy
    try:
        os.replace(staging, pm_dir)
    except Exception:
        os.replace(aside, pm_dir)                                   # put the old one back: never an empty active folder
        raise
    out.update(done=True, archive=str(dest), moved_to=str(aside), carried=carried, verified=v["files"], manifest=str(dest / "manifest.json"),
               inputs_moved={k: m for k, m in moved_inputs.items() if m})
    moved_txt = "; ".join(f"{k} moved to {m}" for k, m in moved_inputs.items() if m) or "no old inputs outside the profile"
    out["note"] = (f"archived and verified ({v['files']} files); the old profile is in {aside.name}; {moved_txt}; the new profile is empty and waits "
                   f"for the desktop icon. Restore into a separate folder with: pflab pm restore {dest} <empty folder>")
    return out


def restore(archive_dir: Path, dest: Path) -> dict:
    """Copy the archived profile into an EMPTY separate folder, verified. It never writes into the active profile."""
    archive_dir, dest = Path(archive_dir), Path(dest)
    v = verify_archive(archive_dir)
    if not v["ok"]:
        raise RuntimeError(f"the archive does not verify ({len(v['problems'])} file(s)): nothing restored")
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"{dest} is not empty")
    shutil.copytree(archive_dir / "pm", dest, dirs_exist_ok=True)
    return {"restored": v["files"], "to": str(dest), "note": "a separate copy: it is not the active profile and nothing reads it unless you point the app at it"}
