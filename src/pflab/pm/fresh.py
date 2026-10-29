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
    activation.write_pending(new_dir, profile=profile)
    return carried


def fresh(pm_dir: Path, archive_root: Path, today: date, confirm: str = "", extra: Optional[Dict[str, Path]] = None) -> dict:
    """Do the whole fresh start. Without the confirmation word it only says what it would do."""
    pm_dir, archive_root = Path(pm_dir), Path(archive_root)
    files = reset.listing(pm_dir)
    out = {"from": str(pm_dir), "files": len(files), "bytes": sum(b for _, b in files), "done": False}
    if confirm != CONFIRM:
        out["note"] = f"nothing changed: pass --confirm {CONFIRM} to archive this profile and begin a new one"
        return out
    if reset.holds_store(pm_dir):
        raise RuntimeError("another process holds the store (the dashboard, the bot or a job): close it first")
    dest = archive_root / f"profile_{today:%Y%m%d}"
    n = 1
    while dest.exists():
        n += 1
        dest = archive_root / f"profile_{today:%Y%m%d}_{n}"
    manifest = archive(pm_dir, dest, extra)
    v = verify_archive(dest)
    if not v["ok"]:
        raise RuntimeError(f"the archive did not verify ({len(v['problems'])} file(s)): the old profile was not moved")
    aside = reset.target_for(pm_dir, today)
    os.replace(pm_dir, aside)                                       # moved, not deleted; the verified archive is the second copy
    carried = new_profile(pm_dir, aside / "ledger.duckdb", f"profile_{today:%Y%m%d}")
    out.update(done=True, archive=str(dest), moved_to=str(aside), carried=carried, verified=v["files"], manifest=str(dest / "manifest.json"))
    out["note"] = (f"archived and verified ({v['files']} files); the old profile is in {aside.name}; the new profile is empty and waits for the "
                   f"desktop icon. Restore into a separate folder with: pflab pm restore {dest} <empty folder>")
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
