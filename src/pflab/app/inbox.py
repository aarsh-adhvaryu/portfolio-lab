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
              "gift_city": "GIFT City statement", "fd_certificate": "deposit interest certificate", "fd_summary": "bank deposit summary",
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


def _accounts(rt) -> dict:
    """The accounts of his sources.toml (name -> kind, bank, last4 ...), or none before Setup."""
    from pflab.ingest import sources as srcs
    try:
        return srcs.load(rt.pm_dir / "sources.toml").get("accounts") or {}
    except Exception:
        return {}


def _store_dir(rt, kind: str) -> Path:
    if kind in LEDGER_KINDS or kind == "fd_certificate":
        return rt.repo / "new"
    if kind == "screenshot":
        return rt.pm_dir / "inbox" / "screens"
    if kind == "market":
        return rt.pm_dir / "inbox" / "market"
    return rt.pm_dir / "inbox"


def _steps(kind: str, done: int, failed: bool = False) -> List[dict]:
    kind = "tradebook" if kind == "fd_certificate" else kind          # a certificate follows the ledger's steps (read, checked, your OK, stored)
    if kind == "fd_summary":
        flow = ["received", "recognised", "checked (rows add up)", "in your deposits"]
        return [{"name": n, "state": "done" if i < done else ("failed" if failed and i == done else "todo")} for i, n in enumerate(flow)]
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
    seen = con.execute("SELECT item_id, status FROM inbox_items WHERE sha=? AND status <> 'removed'", [sha]).fetchone()
    if seen:
        # S68: the same bytes again are not new evidence, but they are not nothing: a file that failed or is blocked is looked at again (a parser
        # fixed, a password saved), and a waiting investigation is swept, so "I dropped it again" resolves what it was for.
        again = False
        if seen[1] in ("failed", BLOCKED):
            again = retry(rt, seen[0])
        try:
            from pflab.hq import cases
            cases.sweep(rt.cursor(), rt.clock())
        except Exception:
            pass
        return {"id": seen[0], "duplicate": True, "retried": again}
    kind = classify(safe, hint)
    info: dict = {}
    if not hint:                                            # S65: the content decides, the name is only the fallback
        from pflab.ingest import coverage, sniff
        info = sniff.sniff(data, safe, sniff.passwords_from_secrets())
        try:
            coverage.note_account(con, info, "a file you dropped", rt.clock(), sha[:12])       # S67: an account is recorded by what the file shows, wherever the file came from
        except Exception:
            pass                                            # the coverage list never stops a file from being received
        from pflab.agents import questions
        from pflab.app import readiness
        if sniff.is_encrypted(data, safe) and not info.get("password_name"):
            # A locked file none of his saved passwords opens: asked ONCE, kept (a copy under pm/inbox/locked, shown as `blocked` with the reason),
            # never evidence; it is read again by itself when a password is saved (S68: no second drop needed).
            reason = "password-protected; none of the saved passwords opens it"
            questions.ask(con, "inbox", f"inbox:locked:{sha[:12]}", f"'{safe}' is password-protected and none of your saved passwords opens it. Add its "
                          "password in Settings > Keys and passwords (any name, for example the bank's); I will open it by myself and carry on.", rt.clock())
            coverage.note_gap(con, "locked", sha[:12], f"{safe}: {reason}", rt.clock())
            iid = _block(rt, con, safe, data, sha, reason)
            return {"id": iid, "kind": "other", "duplicate": False, "blocked": reason}
        questions.drop(con, f"inbox:locked:{sha[:12]}", rt.clock())                            # the same file, now opened: its request and gap close
        readiness.close_gap(con, f"coverage:locked:{sha[:12]}", rt.clock())
        if info["kind"] in KIND_LABEL and info["kind"] != "other":
            kind = info["kind"]
        if kind == "bank" and not account:
            account = sniff.match_account(info, _accounts(rt))
    from pflab.ledger import system
    if system.active() and (kind in LEDGER_KINDS or kind == "fd_certificate"):        # S77: statements are no longer read: the account is the system's own
        if chat_id and con.execute("SELECT 1 FROM chats WHERE chat_id=?", [chat_id]).fetchone():
            from pflab.app import chat
            chat._add(con, chat_id, "me", "ask", f"Attached {safe} ({KIND_LABEL.get(kind, kind)})", "done", rt.clock())
            chat._add(con, chat_id, "ai", "ask", "That is a statement of yours. The system's account is its own now (fake money, its own ledger), so it does not read statements and "
                      "nothing was kept. Anything else (a research note, a screenshot, a company file) it reads here.", "done", rt.clock())
            rt.bump("chat")
        return {"id": None, "kind": kind, "duplicate": False, "ignored": "the account is the system's own: statements are not read"}
    waiting = kind in LEDGER_KINDS and not (rt.pm_dir / "sources.toml").exists()    # S65: a first setup: keep it, Setup proposes the accounts
    if kind == "bank" and not account and not waiting:
        if hint:                                            # he named the kind: the screen asks him for the account
            raise ValueError("which account is this bank statement for?")
        from pflab.agents import questions
        questions.ask(con, "inbox", f"inbox:account:{sha[:12]}",
                      f"Which of your bank accounts is the statement '{safe}'? Reply with the account's name as in Setup, then drop the "
                      "file again with that account chosen.", rt.clock())
        raise ValueError("which account is this bank statement for? It is in Needs from you.")
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
                [iid, safe, kind, account, str(path), sha, "awaiting setup" if waiting else "working", json.dumps(_steps(kind, 1)),
                 json.dumps({**({"existed": True} if existed else {}), "sniff": info}), chat_id, now, now])
    if chat_id and con.execute("SELECT 1 FROM chats WHERE chat_id=?", [chat_id]).fetchone():
        from pflab.app import chat
        chat._add(con, chat_id, "me", "ask", f"Attached {safe} ({KIND_LABEL[kind]})", "done", now)
        rt.bump("chat")
    try:
        close_met_requests(rt)                              # the file just dropped answers its request now, not at the next rebuild
    except Exception:
        pass
    rt.bump("inbox")
    if waiting:
        return {"id": iid, "kind": kind, "duplicate": False, "awaiting_setup": True}
    _start(rt, iid)
    return {"id": iid, "kind": kind, "duplicate": False}


BLOCKED = "blocked"
# the states in which a file counts as evidence for an investigation: it was read and used (or, for a statement, checked). A file that is
# still being worked on, failed, is kept unread or is blocked is NOT evidence (S68).
EVIDENCE_STATES = ("in the ledger", "in the graph", "in the store", "read", "ready")


def _block(rt, con, safe: str, data: bytes, sha: str, reason: str) -> int:
    """Keep a copy of a file that cannot be read yet, in a folder of the profile, and show it as `blocked` with the reason."""
    from pflab.pm.store import next_id
    d = rt.pm_dir / "inbox" / "locked"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{sha[:12]}_{safe}"
    if not path.exists():
        path.write_bytes(data)
    now = rt.clock()
    iid = next_id(con, "inbox_items", "item_id")
    steps = [{"name": "received", "state": "done"}, {"name": "opened", "state": "failed"}]
    con.execute("INSERT INTO inbox_items (item_id, name, kind, account, path, sha, status, steps_json, result_json, chat_id, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [iid, safe, "other", None, str(path), sha, BLOCKED, json.dumps(steps),
                                                      json.dumps({"blocked": reason, "unblocks": "save its password in Settings > Keys and passwords"}),
                                                      None, now, now])
    rt.bump("inbox")
    return iid


def retry(rt, iid: int) -> bool:
    """Read a blocked or failed item again with what is known now (saved passwords, the current readers). True when it was handed on."""
    from pflab.ingest import sniff
    con = rt.cursor()
    r = con.execute("SELECT name, path, status FROM inbox_items WHERE item_id=?", [iid]).fetchone()
    if not r or not r[1] or not Path(r[1]).exists():
        return False
    name, path, status = r
    data = Path(path).read_bytes()
    if status == BLOCKED:
        info = sniff.sniff(data, name, sniff.passwords_from_secrets())
        if sniff.is_encrypted(data, name) and not info.get("password_name"):
            return False                                                            # still locked: nothing changed
        con.execute("UPDATE inbox_items SET status='removed', updated_at=? WHERE item_id=?", [rt.clock(), iid])   # the copy stays; a new row is made
        try:
            receive(rt, name, data)
        except ValueError:
            pass                                                                    # (which bank account? is asked by receive)
        return True
    if status == "failed":
        _update(rt, iid, status="working", steps_json=json.dumps(_steps((_item(rt, iid))["kind"], 1)))
        _start(rt, iid)
        return True
    return False


def retry_blocked(rt) -> int:
    """Every blocked file whose password is now saved is read; cheap when nothing changed (called by the HQ round and when a secret is saved)."""
    n = 0
    for (iid,) in rt.cursor().execute("SELECT item_id FROM inbox_items WHERE status=?", [BLOCKED]).fetchall():
        n += int(retry(rt, iid))
    return n


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
    if action == "apply" and not (it["kind"] in LEDGER_KINDS or (it["kind"] == "fd_certificate" and it["status"] == "ready")):
        raise ValueError("only a statement or a deposit certificate can be added to the ledger")
    if action == "read" and not it.get("text"):
        raise ValueError("no text read from this file")


def _process(rt, iid: int) -> None:
    it = _item(rt, iid)
    try:
        if it["kind"] in LEDGER_KINDS:
            _dry_run(rt, it)
        elif it["kind"] == "fd_certificate":
            _fd_cert(rt, it)
        elif it["kind"] == "fd_summary":
            deposits_now(rt)
        elif it["kind"] == "screenshot":
            _ocr(rt, it)
        elif ((it.get("result") or {}).get("sniff") or {}).get("password_name") and Path(it["path"]).suffix.lower() == ".pdf":
            _update(rt, iid, status="kept", result_json=json.dumps({**it["result"], "note": "password-protected and not a ledger document: kept, "
                                                                     "not read into the graph"}))
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


def _cert_password(it: dict) -> Optional[str]:
    from pflab.ingest import sniff
    name = ((it.get("result") or {}).get("sniff") or {}).get("password_name")
    return dict(sniff.passwords_from_secrets()).get(name) if name else None


def _fd_cert(rt, it: dict, write: bool = False) -> dict:
    """S65: a deposit interest certificate: read and checked (its rows must add up to its TOTAL); stored only on his press (`apply`)."""
    from pflab.ingest import sbi_interest_cert as cert
    from pflab.pm import fd as fdm
    fy, rows = cert.parse(it["path"], _cert_password(it))
    fr = cert.fd_rows(rows)
    res = {**it["result"], "fy": fy, "deposits": len(fr), "checks": [{"name": "the rows add up to the certificate's TOTAL", "ok": True, "detail": ""}],
           "failed": 0}
    if write:
        fdm.save_interest(rt.cursor(), fy, fr, f"inbox: {it['name']}")
        _update(rt, it["id"], status="in the store", steps_json=json.dumps(_steps("fd_certificate", 5)), result_json=json.dumps(res, default=str))
        rt.bump("portfolio")
    else:
        _update(rt, it["id"], status="ready", steps_json=json.dumps(_steps("fd_certificate", 3)), result_json=json.dumps(res, default=str))
        _to_chat(rt, it, f"{it['name']}: interest certificate for FY{fy - 1}-{str(fy)[2:]}, {len(fr)} deposit(s), its rows add up. Press 'Add to "
                 "the ledger' in Inbox and files to keep it.", ["read on this PC", "checked"])
    return res


def _resniff_others(rt) -> int:
    """(2026-10-31) A sheet or PDF filed as 'other' by an older version is looked at again with the current readers, once: a bank's deposit
    summary or a contract-note PDF dropped before its reader existed then counts like one dropped today. Returns how many changed kind."""
    from pflab.ingest import sniff
    con, n = rt.cursor(), 0
    for iid, name, path, res in con.execute("SELECT item_id, name, path, result_json FROM inbox_items WHERE kind='other' AND status <> 'removed'").fetchall():
        r = json.loads(res or "{}")
        if r.get("resniffed") or Path(name).suffix.lower() not in SHEET_EXT | {".pdf"} or not path or not Path(path).exists():
            continue
        info = sniff.sniff(Path(path).read_bytes(), name, sniff.passwords_from_secrets())
        r = {**r, "resniffed": 1, "sniff": info}
        if info.get("kind") == "fd_summary":
            _update(rt, iid, kind="fd_summary", status="working", steps_json=json.dumps(_steps("fd_summary", 2)), result_json=json.dumps(r, default=str))
            n += 1
        elif info.get("kind") == "contract_note":                 # the ledger job reads it with the other statements
            dest = rt.repo / "new" / Path(path).name
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(Path(path).read_bytes())
            _update(rt, iid, kind="contract_note", path=str(dest), status="ready", steps_json=json.dumps(_steps("contract_note", 3)),
                    result_json=json.dumps(r, default=str))
            n += 1
        else:
            _update(rt, iid, result_json=json.dumps(r, default=str))
    return n


def deposits_now(rt) -> dict:
    """(2026-10-31) The deposit register rebuilt from every input that exists: his deposit file (pm/fd_holdings.toml) and each bank deposit
    summary in the inbox. Nothing waits: a summary that does not add up is a named gap; a deposit past its maturity is asked about once."""
    import hashlib as _h
    from pflab.agents import questions
    from pflab.app import readiness
    from pflab.ingest import fd_summary as fs
    from pflab.pm import fd as fdm
    con, now = rt.cursor(), rt.clock()
    out = {"reclassified": _resniff_others(rt)}
    his, path = [], rt.pm_dir / "fd_holdings.toml"
    if path.exists():
        try:
            his = fdm.from_toml(path)
            readiness.close_gap(con, "deposits:file", now)
        except Exception as e:
            readiness.open_gap(con, "deposits:file", "deposits", f"your deposit file cannot be read: {type(e).__name__}: {str(e)[:200]}", now)
    summaries, items = [], []
    for iid, in con.execute("SELECT item_id FROM inbox_items WHERE kind='fd_summary' AND status <> 'removed' ORDER BY item_id").fetchall():
        it = _item(rt, iid)
        try:
            bank, deps = fs.parse(Path(it["path"]).read_bytes(), _cert_password(it))
            summaries.append({"bank": bank, "deposits": deps, "observed": it["created"], "source": it["name"]})
            items.append((it, len(deps), bank))
            readiness.close_gap(con, f"deposits:summary:{it['sha'][:12]}", now)
        except Exception as e:
            readiness.open_gap(con, f"deposits:summary:{it['sha'][:12]}", "deposits", f"{it['name']}: {type(e).__name__}: {str(e)[:200]}", now)
            fail(rt, iid, e)
    if not his and not summaries:
        return {**out, "deposits": 0, "why": "no deposit file and no bank deposit summary yet"}
    fds, notes = fdm.register(his, summaries)
    n = fdm.save(con, fds, f"register: {'your deposit file' if his else 'no deposit file'} + {len(summaries)} bank summary(ies)", now)
    for it, k, bank in items:
        _update(rt, it["id"], status="in the store", steps_json=json.dumps(_steps("fd_summary", 4)),
                result_json=json.dumps({**it["result"], "bank": bank, "deposits": k}, default=str))
    refused = notes["refused"]
    key = "deposits:refused"
    if refused:
        readiness.open_gap(con, key, "deposits", "; ".join(refused)[:600], now)
    else:
        readiness.close_gap(con, key, now)
    late = fdm.unresolved(fds, now.date())
    qk = "deposits:matured:" + _h.sha1("|".join(sorted(f"{f.bank}{f.fd_id}" for f in late)).encode()).hexdigest()[:10]
    for (k,) in con.execute("SELECT subject_key FROM questions WHERE status='open' AND subject_key LIKE 'deposits:matured:%' AND subject_key <> ?", [qk]).fetchall():
        questions.drop(con, k, now)
    if late:
        questions.ask(con, "deposits", qk, f"{len(late)} deposit(s) have passed their maturity date and I cannot see whether they were renewed or paid out: "
                      + ", ".join(f"{f.bank} ending {f.fd_id[-4:]} on {f.maturity}" for f in late[:8])
                      + ". Drop each bank's latest deposit summary (or its statement) in Inbox and files; until then they are left out of the total.", now)
    rt.bump("portfolio", "inbox")
    return {**out, "deposits": n, "from_file": len(his), "from_summaries": notes["from_summaries"], "renewed": len(notes["renewed"]),
            "refused": len(refused), "matured_unresolved": len(late)}


def deposits_fingerprint(rt) -> str:
    """What the register is built from: the deposit file's bytes and the deposit summaries; a change is a reason to rebuild."""
    con = rt.cursor()
    p = rt.pm_dir / "fd_holdings.toml"
    parts = [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "-"]
    parts += [r[0] for r in con.execute("SELECT sha FROM inbox_items WHERE kind='fd_summary' AND status <> 'removed' ORDER BY sha").fetchall()]
    parts.append(str(con.execute("SELECT count(*) FROM inbox_items WHERE kind='other' AND status <> 'removed' AND coalesce(result_json, '') NOT LIKE '%resniffed%'").fetchone()[0]))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _missing(merged: dict) -> List[str]:
    """Documents the ledger build still lacks. Only a first setup (an empty document list) can be incomplete: a file that already
    has its tradebooks, ledger, CAS and bank files is built as before."""
    from pflab.ingest import setup_sources
    return setup_sources.needed(merged, optional=False)


def _rel(rt, path: str) -> str:
    return Path(path).resolve().relative_to(rt.repo.resolve()).as_posix()


def _dry_run(rt, it: dict) -> None:
    """A ledger document is recognised and queued: the `ledger` job rebuilds the whole record from every file (2026-10-30: one build for all,
    written by itself; a difference is named, never a reason to write nothing)."""
    _update(rt, it["id"], status="ready", steps_json=json.dumps(_steps(it["kind"], 3)),
            result_json=json.dumps({**it["result"], "note": "recognised; your record is rebuilt with it in a moment"}, default=str))
    _to_chat(rt, it, f"{it['name']} ({KIND_LABEL[it['kind']]}) is recognised. Your record is rebuilt with it in a moment; anything it cannot "
             "match is listed in Needs from you with what closes it.", ["read on this PC"])
    if hasattr(rt, "wanted"):                               # the app: the job runs next on its own thread (a burst of files makes one build)
        try:
            rt.request_run("ledger")
        except Exception:
            pass


def apply(rt, iid: int) -> dict:
    """The investor's OK: the document joins sources.app.toml and the ledger is rebuilt and written, all checks passing."""
    from pflab.ingest import sources as srcs
    it = _item(rt, iid)
    if it["kind"] == "fd_certificate" and it["status"] == "ready":         # S65: certified interest, his press
        _fd_cert(rt, it, write=True)
        return {"events": 0, "certificate": True}
    if it["kind"] in LEDGER_KINDS:                          # (2026-10-30) the whole record is rebuilt with it, differences named
        return build_now(rt)
    if it["kind"] not in LEDGER_KINDS or it["status"] != "ready":
        raise ValueError("only a ledger document whose dry run passed can be added")
    with _LOCK:
        sources = rt.pm_dir / "sources.toml"
        over = srcs.with_document(srcs.load_overlay(sources), it["kind"], _rel(rt, it["path"]), it["account"])
        merged = srcs.merge(srcs.base(sources), over)
        missing = _missing(merged)
        if missing:                                         # S65: keep the document; the ledger is built when the last one arrives
            srcs.save_overlay(sources, over)
            _update(rt, iid, status="kept", steps_json=json.dumps(_steps(it["kind"], 4)),
                    result_json=json.dumps({**it["result"], "waiting_for": missing}, default=str))
            return {"events": 0, "waiting_for": missing}
        b = _builder(rt)
        log, led, checks, notes, src = b.build(merged, rt.repo)
        failed = [c for c in checks if not c[1]]
        if failed:
            raise ValueError(f"{len(failed)} check(s) fail now: nothing written")
        from pflab.pm.store import transaction
        con = rt.cursor()
        with transaction(con):
            b.write(con, log, led, src)
        srcs.save_overlay(sources, over)
        try:                                                # S65: lines the rules could not place become questions
            from pflab.ingest import bank_labels
            bank_labels.ask(con, src.get("_unlabelled") or [], rt.clock())
        except Exception:
            pass
    _update(rt, iid, status="in the ledger", steps_json=json.dumps(_steps(it["kind"], 5)),
            result_json=json.dumps({**it["result"], "written": len(log)}))
    rt.bump("portfolio", "command", "watch")
    return {"events": len(log)}


def add_entry(rt, section: str, entry: dict, write: bool = False) -> dict:
    """S65: an IPO or an opening cost entered on the dashboard (`ingest/sources.ipo_entry`, `cost_entry`). Without `write` the
    ledger is rebuilt as a DRY RUN with it and the checks are shown; with `write` (his press) and every check passing, the entry
    joins sources.app.toml and the ledger is rewritten in one transaction. Before a first setup is complete it is only kept."""
    from pflab.ingest import sources as srcs
    with _LOCK:
        sources = rt.pm_dir / "sources.toml"
        over = srcs.with_entry(srcs.load_overlay(sources), section, entry)
        merged = srcs.merge(srcs.base(sources), over)
        missing = _missing(merged)
        if missing:
            if write:
                srcs.save_overlay(sources, over)
            return {"checks": [], "failed": 0, "written": False, "kept": bool(write), "waiting_for": missing}
        b = _builder(rt)
        log, led, checks, notes, src = b.build(merged, rt.repo)
        failed = [c for c in checks if not c[1]]
        res = {"checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks], "notes": notes, "events": len(log),
               "failed": len(failed), "written": False}
        if write:
            if failed:
                raise ValueError(f"{len(failed)} check(s) fail: nothing written")
            from pflab.pm.store import transaction
            con = rt.cursor()
            with transaction(con):
                b.write(con, log, led, src)
            srcs.save_overlay(sources, over)
            res["written"] = True
            rt.bump("portfolio", "command", "watch")
    return res


def attach_waiting(rt, inline: bool = False) -> dict:
    """S65: after Setup, the files kept while there was none: each bank statement gets its account by its bank and last four digits (one
    that matches none goes to Needs from you), and every file starts its checks."""
    from pflab.ingest import sniff
    con = rt.cursor()
    accounts = _accounts(rt)
    started, unknown = [], []
    for iid, kind, name, rj in con.execute("SELECT item_id, kind, name, result_json FROM inbox_items WHERE status='awaiting setup' "
                                           "ORDER BY item_id").fetchall():
        info = (json.loads(rj or "{}").get("sniff") or {})
        acc = sniff.match_account(info, accounts) if kind == "bank" else None
        if kind == "bank" and not acc:
            from pflab.agents import questions
            questions.ask(con, "inbox", f"inbox:account:item{iid}", f"Which of your bank accounts is the statement '{name}'? Reply with the "
                          "account's name as in Setup, then drop the file again with that account chosen.", rt.clock())
            unknown.append(name)
            continue
        _update(rt, iid, status="working", account=acc)
        if inline:
            _process(rt, iid)
        else:
            _start(rt, iid)
        started.append(name)
    rt.bump("inbox")
    return {"started": started, "unknown": unknown}


HINTS = [("charges are known", "the Console contract notes (Excel) for the days named, or the Console funds ledger that covers them"),
         ("contract note", "the Console contract notes (Excel) for the days after the last one you gave"),
         ("Console closing", "the contract notes of your latest trades (their charges), or a newer Console funds ledger"),
         ("pay-in", "the bank statement that shows each of these Zerodha pay-ins and payouts"),
         ("statement closing", "the bank statements without a missing month"),
         ("holdings = CAS", "the Console tradebook for that period, or the IPO in Setup's IPO form"),
         ("tradebook is given", "the Console tradebook"), ("funds ledger is given", "the Console funds ledger"),
         ("(CAS) is given", "a depository statement (CAS)"), ("IPO", "Setup's IPO form"),
         ("source in your files", "the Console funds ledger for that time, and the bank statement that paid the money in")]


def record_differences(con, checks, n_events: int, now) -> int:
    """Each check the built ledger does not pass is an open gap (named, with its detail) and ONE grouped request says what closes each; a check
    that passes now closes its gap; the request is replaced when the set changes. Returns the number of open differences."""
    import hashlib
    from pflab.agents import questions
    from pflab.app import readiness
    failed = [(n, d) for n, ok, d in checks if not ok]
    keys = {}
    for n, d in failed:
        k = "ledger:diff:" + re.sub(r"[^a-z0-9]+", "-", n.lower())[:60]
        keys[k] = (n, d)
        readiness.open_gap(con, k, "ledger", f"{n}: {str(d)[:300]}", now)
    for g in readiness.gaps(con, "ledger"):
        if g["key"] not in keys:
            readiness.close_gap(con, g["key"], now)
    qk = "ledger:diffs:" + hashlib.sha1("|".join(sorted(keys)).encode()).hexdigest()[:10]
    for (k,) in con.execute("SELECT subject_key FROM questions WHERE status='open' AND subject_key LIKE 'ledger:diffs:%' AND subject_key <> ?", [qk]).fetchall():
        questions.drop(con, k, now)
    if failed:
        lines = "; ".join(f"{n} -> {next((h for w, h in HINTS if w in n), 'see Inbox and files')}" for n, _ in failed[:8])
        questions.ask(con, "ledger", qk, f"Your record is built ({n_events} entries) and keeps itself up to date. {len(failed)} difference(s) with your "
                      f"files remain; each closes by itself when you drop what it names: {lines}. Nothing else is needed.", now)
    return len(failed)


READERS = ("bank", "bank_labels", "contract_note", "tradebook", "zerodha_ledger", "cas", "fd_summary", "sniff")


def builder_fingerprint(rt) -> str:
    """(2026-10-31) The code that reads his statements into the record: when it changes (an update), every statement is read again by itself,
    so a fix reaches the files he dropped earlier, not only the next one."""
    import importlib
    parts = []
    for p in [rt.repo / "tools" / "build_pm_ledger.py"] + [Path(importlib.import_module(f"pflab.ingest.{m}").__file__) for m in READERS]:
        parts.append(hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "-")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def last_build(rt) -> dict:
    p = rt.pm_dir / "app" / "ledger_build.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def rebuild_due(rt) -> bool:
    """The record was built from statements before, and the reading code has changed since."""
    from pflab.ledger import system
    if system.active(rt.pm_dir):
        return False
    con = rt.cursor()
    built = con.execute("SELECT 1 FROM inbox_items WHERE status='in the ledger' LIMIT 1").fetchone()
    return bool(built) and last_build(rt).get("fingerprint") != builder_fingerprint(rt)


def build_now(rt, force: bool = False) -> dict:
    """Set up the accounts from the files if nobody has, then build and write the whole record from every statement. Called by the `ledger` job
    after any statement arrives, and by the screen's press. Nothing is waited for: a missing file is a named difference."""
    from pflab.agents import questions
    from pflab.ingest import setup_sources as su
    con = rt.cursor()
    sources = rt.pm_dir / "sources.toml"
    kinds = "','".join(LEDGER_KINDS)
    if not sources.exists():
        if not con.execute(f"SELECT 1 FROM inbox_items WHERE kind IN ('{kinds}') AND status <> 'removed' LIMIT 1").fetchone():
            return {"written": False, "skipped": True, "why": "no statement dropped yet"}
        prop = su.infer(con, rt.clock().date())
        try:
            su.write(sources, prop["answers"])
        except su.SetupError as e:                          # (no bank statement yet, say): said once, built as soon as it is possible
            questions.ask(con, "setup", "setup:auto:wait", f"Your accounts cannot be set up from the files yet ({e}). Drop a bank statement, or set "
                          "them up in Settings > Open Setup.", rt.clock())
            return {"written": False, "skipped": True, "why": str(e)}
        a = prop["answers"]
        names = [a["broker"]["account"] + " (Zerodha)"] + [d["name"] for d in a.get("demats", [])] + [b["name"] for b in a.get("banks", [])]
        questions.ask(con, "setup", "setup:auto", "I set up your accounts from the files you dropped: " + ", ".join(names) + f", from {a['start']}. "
                      "If one is wrong or missing, change it in Settings > Open Setup; your record is rebuilt by itself.", rt.clock())
        attach_waiting(rt, inline=True)
    return apply_all(rt, force=force)


def apply_all(rt, force: bool = False) -> dict:
    """S65: every ledger document whose dry run passed or that was kept, added in ONE rebuild: written only when every check passes (his press)."""
    from pflab.ingest import sources as srcs
    from pflab.ledger import system
    if system.active(rt.pm_dir):                          # S77: the ledger is the system's own account; it is never rebuilt from statements
        return {"applied": 0, "skipped": "the ledger is the system's own account"}
    con = rt.cursor()
    items = [_item(rt, r[0]) for r in con.execute("SELECT item_id FROM inbox_items WHERE status IN ('ready', 'kept', 'checks failed') "
                                                  "ORDER BY item_id").fetchall()]
    items = [it for it in items if it["kind"] in LEDGER_KINDS]
    if not items and not force:
        return {"written": False, "why": "no documents waiting"}
    with _LOCK:
        sources = rt.pm_dir / "sources.toml"
        over = srcs.load_overlay(sources)
        for it in items:
            over = srcs.with_document(over, it["kind"], _rel(rt, it["path"]), it["account"])
        merged = srcs.merge(srcs.base(sources), over)
        b = _builder(rt)
        try:
            log, led, checks, notes, src = b.build(merged, rt.repo)
        except Exception as e:                              # a document the build cannot read: said, nothing written
            return {"written": False, "failed": 1, "documents": len(items), "error": f"{type(e).__name__}: {str(e)[:300]}",
                    "checks": [{"name": "every document can be read", "ok": False, "detail": f"{type(e).__name__}: {str(e)[:200]}"}]}
        failed = [c for c in checks if not c[1]]
        res = {"checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks], "notes": notes, "events": len(log), "failed": len(failed),
               "documents": len(items), "written": False}
        from pflab.pm.store import transaction
        with transaction(con):
            b.write(con, log, led, src)
        srcs.save_overlay(sources, over)
        try:
            p = rt.pm_dir / "app" / "ledger_build.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"fingerprint": builder_fingerprint(rt), "at": rt.clock().isoformat(timespec="seconds"), "events": len(log),
                                     "differences": len(failed)}), encoding="utf-8")
        except OSError:
            pass
        for it in items:
            _update(rt, it["id"], status="in the ledger", steps_json=json.dumps(_steps(it["kind"], 5)),
                    result_json=json.dumps({**it["result"], "checks": res["checks"], "events": len(log), "failed": len(failed)}, default=str))
        try:
            record_differences(con, checks, len(log), rt.clock())
        except Exception:
            pass
        try:                                                # the accounts are known now: the one grouped inventory question (asked once)
            from pflab.ingest import coverage
            coverage.ask_inventory(con, rt.clock())
        except Exception:
            pass
        try:
            from pflab.ingest import bank_labels
            bank_labels.ask(con, src.get("_unlabelled") or [], rt.clock())
        except Exception:
            pass
    certs = [_item(rt, r[0]) for r in con.execute("SELECT item_id FROM inbox_items WHERE kind='fd_certificate' AND status='ready'").fetchall()]
    for it in certs:                                        # the deposit interest certificates go in with the same press
        _fd_cert(rt, it, write=True)
    rt.bump("portfolio", "command", "watch", "inbox")
    res.update(written=True, certificates=len(certs))
    return res


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


# Words that name an exchange, a depository or a registrar as often as a listed company: alone they never make a text "about" that company
VENUE_WORDS = {"nse", "bse", "mcx", "cdsl", "nsdl", "cams", "kfintech", "kfin"}


def companies_in(con, text: str) -> List[str]:
    """The listed companies a text is about, by their names in the record (free, on this PC). A rulebook or a notice names none."""
    from pflab.kg import build as kb
    from pflab.plan import guards as gd
    isins = [i for (i,) in con.execute("SELECT DISTINCT isin FROM instruments WHERE isin LIKE 'INE%'").fetchall()]
    if not isins:
        return []
    names = kb.names_for(con, isins, gd.stock_list())
    found = []
    for isin, ns in names.items():
        ns = [n for n in ns if n and n.strip().lower() not in VENUE_WORDS]
        if ns and kb.is_about(text, ns, k=400):
            sym = con.execute("SELECT coalesce(symbol, name) FROM instruments WHERE isin=? LIMIT 1", [isin]).fetchone()
            found.append((sym[0] if sym else None) or isin)
    return sorted(set(found))


def research(rt, iid: int) -> dict:
    """A screenshot's text as a deep-research question, only when it is about a company (2026-10-30: a rulebook was sent to Opus and checked
    against unrelated filings). A free check on this PC first: no company named, nothing is sent and nothing is spent."""
    from pflab.app import chat
    it = _item(rt, iid)
    if not it.get("text"):
        raise ValueError("no text read from this file")
    text = " ".join(it["text"].split())
    names = companies_in(rt.cursor(), text)
    if not names:
        msg = ("Nothing to research: this text names no company (it reads like a general notice or a rule). Nothing was sent and nothing was "
               "spent. To have a rule explained, ask it in the AI centre with Web search.")
        _to_chat(rt, it, msg, ["checked on this PC"])
        return {"skipped": True, "why": msg}
    q = f"Check this news about {', '.join(names[:3])} against its exchange filings and research it: " + text[:900]
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


def close_met_requests(rt) -> int:
    """Count every dropped ledger document (whatever stage it has reached) as present and close the Needs-from-you requests it answers."""
    from pflab.ingest import setup_sources as su, sources as srcs
    sources = rt.pm_dir / "sources.toml"
    if not sources.exists():
        return 0
    con = rt.cursor()
    over = srcs.load_overlay(sources)
    for (iid,) in con.execute("SELECT item_id FROM inbox_items WHERE status <> 'removed' ORDER BY item_id").fetchall():
        it = _item(rt, iid)
        if it["kind"] in LEDGER_KINDS and it["path"]:
            try:
                over = srcs.with_document(over, it["kind"], _rel(rt, it["path"]), it["account"])
            except ValueError:
                continue                                    # a bank statement with no account yet cannot answer a request
    return su.close_met(con, srcs.merge(srcs.base(sources), over), rt.clock())


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
