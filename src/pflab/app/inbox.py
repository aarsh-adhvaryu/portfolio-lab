"""S54d: the inbox. Every file the investor drops, pastes or attaches in a chat is read on this PC and routed:

    ledger documents   Console tradebooks, contract notes, the funds ledger, CAS PDFs, bank statements: saved in the
                       repo's `new/` (gitignored), added to `sources.app.toml`, and the ledger rebuilt as a DRY RUN with
                       every cross-check shown; the ledger is written only when the investor presses "Add to the ledger" and
                       every check passes (one transaction: a failure leaves the ledger as it was)
    screenshots        read by Windows' own OCR (`tools/ocr.ps1`); the text is kept, the image is deleted after
                       IMAGE_DAYS; "read it" gives the local model's guarded summary, "research it" sends the text to
                       deep research (the egress gate decides what may leave)
    market exports     Tijori / Screener files go to inbox/market (the analyst may read them) and into the graph
    anything else      into the knowledge graph through the inbox agent (`agents.inbox`), kept on this PC

Files whose bytes were seen before are not processed twice. Results that came from a chat go back to that chat.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
SHEET_EXT = {".xlsx", ".xls", ".csv"}
IMAGE_DAYS = 7
LEDGER_KINDS = ("tradebook", "contract_note", "funds_ledger", "cas", "bank")
KIND_LABEL = {"tradebook": "Console tradebook", "contract_note": "contract notes", "funds_ledger": "Console funds ledger",
              "cas": "depository CAS", "bank": "bank statement", "screenshot": "screenshot", "market": "market-data export",
              "other": "other file"}
_LOCK = threading.Lock()


def classify(name: str, hint: str = "") -> str:
    """A kind from the file name (Zerodha's and the depositories' own names), or the investor's hint."""
    if hint in KIND_LABEL:
        return hint
    n = name.lower()
    ext = Path(n).suffix
    if ext in IMAGE_EXT:
        return "screenshot"
    if n.startswith("tradebook"):
        return "tradebook"
    if n.startswith("ledger") and ext in SHEET_EXT:
        return "funds_ledger"
    if re.match(r"^[a-z]{2,4}\d{2,4}_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.xlsx$", n):
        return "contract_note"
    if "cas" in n and ext == ".pdf":
        return "cas"
    if "tijori" in n or "screener" in n:
        return "market"
    return "other"


def _store_dir(rt, kind: str) -> Path:
    if kind in LEDGER_KINDS:
        return rt.repo / "new"
    if kind == "screenshot":
        return rt.pm_dir / "inbox" / "screens"
    if kind == "market":
        return rt.pm_dir / "inbox" / "market"
    return rt.pm_dir / "inbox"


def _steps(kind: str, done: int, failed: bool = False) -> List[dict]:
    names = {"ledger": ["received", "recognised", "checked (dry run)", "your OK", "in the ledger"],
             "screenshot": ["received", "read on this PC", "summarised", "image deleted"],
             "graph": ["received", "recognised", "in the knowledge graph"]}
    flow = names["ledger" if kind in LEDGER_KINDS else "screenshot" if kind == "screenshot" else "graph"]
    return [{"name": n, "state": "done" if i < done else ("failed" if failed and i == done else "todo")} for i, n in enumerate(flow)]


def receive(rt, name: str, data: bytes, hint: str = "", account: Optional[str] = None, chat_id: Optional[int] = None) -> dict:
    """Save the file where its kind belongs and start reading it."""
    from pflab.pm.store import next_id
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name).name)[:120] or "file"
    sha = hashlib.sha256(data).hexdigest()
    con = rt.cursor()
    seen = con.execute("SELECT item_id FROM inbox_items WHERE sha=? AND status <> 'removed'", [sha]).fetchone()
    if seen:
        return {"id": seen[0], "duplicate": True}
    kind = classify(safe, hint)
    if kind == "bank" and not account:
        raise ValueError("which account is this bank statement for?")
    d = _store_dir(rt, kind)
    d.mkdir(parents=True, exist_ok=True)
    path = d / safe
    existed = path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha   # already there: never deleted
    if path.exists() and not existed:
        path = d / f"{path.stem}-{sha[:6]}{path.suffix}"
    if not existed:
        path.write_bytes(data)
    now = rt.clock()
    iid = next_id(con, "inbox_items", "item_id")
    con.execute("INSERT INTO inbox_items (item_id, name, kind, account, path, sha, status, steps_json, result_json, chat_id, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [iid, safe, kind, account, str(path), sha, "working", json.dumps(_steps(kind, 1)),
                 json.dumps({"existed": True} if existed else {}), chat_id, now, now])
    if chat_id and con.execute("SELECT 1 FROM chats WHERE chat_id=?", [chat_id]).fetchone():
        from pflab.app import chat
        chat._add(con, chat_id, "me", "ask", f"Attached {safe} ({KIND_LABEL[kind]})", "done", now)
        rt.bump("chat")
    rt.bump("inbox")
    _start(rt, iid)
    return {"id": iid, "kind": kind, "duplicate": False}


def _start(rt, iid: int) -> None:
    threading.Thread(target=_process, args=(rt, iid), name=f"inbox-{iid}", daemon=True).start()


def _update(rt, iid: int, **f) -> None:
    sets = ", ".join(f"{k}=?" for k in f) + ", updated_at=?"
    rt.cursor().execute(f"UPDATE inbox_items SET {sets} WHERE item_id=?", list(f.values()) + [rt.clock(), iid])
    rt.bump("inbox")


def _item(rt, iid: int) -> dict:
    r = rt.cursor().execute("SELECT item_id, name, kind, account, path, sha, status, steps_json, text, result_json, chat_id, "
                            "created_at, updated_at, cleaned_at FROM inbox_items WHERE item_id=?", [iid]).fetchone()
    keys = ["id", "name", "kind", "account", "path", "sha", "status", "steps", "text", "result", "chat_id", "created",
            "updated", "cleaned"]
    d = dict(zip(keys, r))
    d["steps"] = json.loads(d["steps"] or "[]")
    d["result"] = json.loads(d["result"] or "{}")
    return d


def _to_chat(rt, it: dict, text: str, route: List[str]) -> None:
    if not it.get("chat_id"):
        return
    from pflab.app import chat
    con = rt.cursor()
    if con.execute("SELECT 1 FROM chats WHERE chat_id=?", [it["chat_id"]]).fetchone() is None:
        return
    mid = chat._add(con, it["chat_id"], "ai", "ask", text, "done", rt.clock())
    chat._finish(con, mid, text, route, f"inbox item {it['id']}", rt.clock())
    rt.bump("chat")


def fail(rt, iid: int, e: Exception) -> None:
    """Shown on the screen, never hidden; the step that failed is the first one not done."""
    it = _item(rt, iid)
    done = sum(s["state"] == "done" for s in it["steps"]) or 1
    _update(rt, iid, status="failed", result_json=json.dumps({**it["result"], "error": f"{type(e).__name__}: {str(e)[:400]}"}),
            steps_json=json.dumps(_steps(it["kind"], done, failed=True)))


def check(rt, iid: int, action: str) -> None:
    """Refuse at once what cannot be done (the slow work then runs on its own thread)."""
    it = _item(rt, iid)
    if action == "apply" and (it["kind"] not in LEDGER_KINDS or it["status"] != "ready"):
        raise ValueError("only a ledger document whose dry run passed can be added")
    if action == "read" and not it.get("text"):
        raise ValueError("no text read from this file")


def _process(rt, iid: int) -> None:
    it = _item(rt, iid)
    try:
        if it["kind"] in LEDGER_KINDS:
            _dry_run(rt, it)
        elif it["kind"] == "screenshot":
            _ocr(rt, it)
        else:
            _graph(rt, it)
    except Exception as e:
        fail(rt, iid, e)


# --- ledger documents ---------------------------------------------------------------------------------------------------

def _builder(rt):
    import importlib.util
    p = rt.repo / "tools" / "build_pm_ledger.py"
    spec = importlib.util.spec_from_file_location("pflab_tools_build_pm_ledger", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _rel(rt, path: str) -> str:
    return Path(path).resolve().relative_to(rt.repo.resolve()).as_posix()


def _dry_run(rt, it: dict) -> None:
    from pflab.ingest import sources as srcs
    with _LOCK:
        sources = rt.pm_dir / "sources.toml"
        over = srcs.with_document(srcs.load_overlay(sources), it["kind"], _rel(rt, it["path"]), it["account"])
        log, led, checks, notes, _ = _builder(rt).build(srcs.merge(srcs.base(sources), over), rt.repo)
    failed = [c for c in checks if not c[1]]
    res = {**it["result"], "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks], "notes": notes,
           "events": len(log), "failed": len(failed)}
    _update(rt, it["id"], status="checks failed" if failed else "ready", result_json=json.dumps(res, default=str),
            steps_json=json.dumps(_steps(it["kind"], 3 if not failed else 2, failed=bool(failed))))
    _to_chat(rt, it, f"{it['name']} ({KIND_LABEL[it['kind']]}): the ledger rebuilt as a dry run with it: "
             + (f"{len(failed)} of {len(checks)} checks failed; see Inbox and files." if failed else
                f"all {len(checks)} checks pass. Press 'Add to the ledger' in Inbox and files to write it."),
             ["read on this PC", "ledger dry run"])


def apply(rt, iid: int) -> dict:
    """The investor's OK: the document joins sources.app.toml and the ledger is rebuilt and written, all checks passing."""
    from pflab.ingest import sources as srcs
    it = _item(rt, iid)
    if it["kind"] not in LEDGER_KINDS or it["status"] != "ready":
        raise ValueError("only a ledger document whose dry run passed can be added")
    with _LOCK:
        sources = rt.pm_dir / "sources.toml"
        over = srcs.with_document(srcs.load_overlay(sources), it["kind"], _rel(rt, it["path"]), it["account"])
        b = _builder(rt)
        log, led, checks, notes, src = b.build(srcs.merge(srcs.base(sources), over), rt.repo)
        failed = [c for c in checks if not c[1]]
        if failed:
            raise ValueError(f"{len(failed)} check(s) fail now: nothing written")
        from pflab.pm.store import transaction
        con = rt.cursor()
        with transaction(con):
            b.write(con, log, led, src)
        srcs.save_overlay(sources, over)
    _update(rt, iid, status="in the ledger", steps_json=json.dumps(_steps(it["kind"], 5)),
            result_json=json.dumps({**it["result"], "written": len(log)}))
    rt.bump("portfolio", "command", "watch")
    return {"events": len(log)}


# --- screenshots --------------------------------------------------------------------------------------------------------

def ocr(rt, path: Path) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(rt.repo / "tools" / "ocr.ps1"),
                        "-Path", str(path)], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"Windows OCR failed: {r.stderr.decode('utf-8', 'replace')[-300:]}")
    return r.stdout.decode("utf-8", "replace").strip()


def _ocr(rt, it: dict) -> None:
    text = ocr(rt, Path(it["path"]))
    _update(rt, it["id"], status="read", text=text, steps_json=json.dumps(_steps("screenshot", 2)))
    _to_chat(rt, it, f"Screenshot {it['name']}, read on this PC:\n\n{text or '(no text found)'}\n\nAsk me about it, or use "
                     "'Read it' / 'Research it' in Inbox and files.", ["Windows OCR on this PC"])


def summarise(rt, iid: int, llm=None) -> dict:
    """The local model's guarded summary of a screenshot's text (the text is its only source; nothing leaves the PC)."""
    from pflab.llm import graphs
    it = _item(rt, iid)
    if not it.get("text"):
        raise ValueError("no text read from this file")
    if llm is None:
        from pflab.agents import brief
        llm = brief.chosen_llm()
        if llm is None:
            raise RuntimeError("no local model chosen")
    prompt = ("Say in 2-4 plain sentences what this screenshot shows: what happened, when, how much, and which company or "
              "account it concerns. Put [S1] at the end of each sentence, before its full stop. Copy every number exactly "
              "as written.\n\nSOURCE:\n[S1] " + it["text"][:4000])
    out = graphs.run(llm, prompt, {}, {"S1": it["text"]}, allow_cited_source_numbers=True)
    summary = out.text or "No checked summary could be written; the text above is what the screenshot says."
    res = {**it["result"], "summary": summary, "checked": bool(out.text)}
    _update(rt, iid, result_json=json.dumps(res), steps_json=json.dumps(_steps("screenshot", 3)))
    _to_chat(rt, it, summary, ["local model, checked against the screenshot's text"])
    return res


def research(rt, iid: int) -> dict:
    """The screenshot's text as a deep-research question (news to verify); the egress gate decides what may leave."""
    from pflab.app import chat
    it = _item(rt, iid)
    if not it.get("text"):
        raise ValueError("no text read from this file")
    q = "Check this news against exchange filings and research it: " + " ".join(it["text"].split())[:900]
    return chat.post(rt, it.get("chat_id") or 0, q, "deep")


# --- graph --------------------------------------------------------------------------------------------------------------

def _graph(rt, it: dict) -> None:
    from pflab.agents import inbox as agent
    from pflab.llm import registry
    reads = agent.ingest_file(rt.cursor(), Path(it["path"]), rt.data_root / "inbox", rt.clock(), registry.chosen("general"),
                              market=it["kind"] == "market")
    facts = sum(r.facts for r in reads)
    res = {**it["result"], "sheets": len(reads), "facts": facts, "kinds": sorted({r.kind for r in reads}),
           "companies": len({i for r in reads for i in r.isins})}
    _update(rt, it["id"], status="in the graph", result_json=json.dumps(res), steps_json=json.dumps(_steps(it["kind"], 3)))
    _to_chat(rt, it, f"{it['name']}: {len(reads)} sheet(s) read into the knowledge graph, {facts} figure(s), "
             f"{res['companies']} company link(s).", ["read on this PC", "knowledge graph"])


# --- listing and cleanup ------------------------------------------------------------------------------------------------

def listing(rt, limit: int = 40) -> List[dict]:
    ids = [r[0] for r in rt.cursor().execute("SELECT item_id FROM inbox_items WHERE status <> 'removed' ORDER BY item_id DESC "
                                             "LIMIT ?", [limit]).fetchall()]
    out = []
    for i in ids:
        d = _item(rt, i)
        d.pop("sha", None)
        d["label"] = KIND_LABEL.get(d["kind"], d["kind"])
        out.append(d)
    return out


def remove(rt, iid: int) -> None:
    it = _item(rt, iid)
    if it["status"] == "in the ledger":
        raise ValueError("this document is part of the ledger now: remove it from sources.app.toml with a rebuild")
    if it["path"] and Path(it["path"]).exists() and not it["result"].get("existed"):   # a file that was there stays
        Path(it["path"]).unlink()
    _update(rt, iid, status="removed")


def cleanup(rt, now: Optional[datetime] = None) -> List[str]:
    """Screenshots read more than IMAGE_DAYS ago lose their image (the text stays): The investor's rule, personal inputs go once
    used. Ledger documents stay: every rebuild reads them again."""
    now = now or rt.clock()
    con = rt.cursor()
    done = []
    for iid, name, path in con.execute(
            "SELECT item_id, name, path FROM inbox_items WHERE kind='screenshot' AND cleaned_at IS NULL AND status <> 'removed' "
            "AND text IS NOT NULL AND created_at < ?", [now - timedelta(days=IMAGE_DAYS)]).fetchall():
        if path and Path(path).exists():
            Path(path).unlink()
        con.execute("UPDATE inbox_items SET cleaned_at=?, steps_json=? WHERE item_id=?",
                    [now, json.dumps(_steps("screenshot", 4)), iid])
        done.append(f"screenshot {name}: image deleted, its text kept")
    if done:
        rt.bump("inbox")
    return done


__all__ = ["classify", "receive", "apply", "summarise", "research", "listing", "remove", "cleanup", "ocr"]
