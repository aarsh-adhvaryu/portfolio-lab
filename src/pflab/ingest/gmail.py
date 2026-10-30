r"""Read-only Gmail: his statements arrive by themselves (S65; his decision 2026-10-28: Google's `gmail.readonly` permission).

    connect   once, his step: Google's sign-in page opens in the browser, he approves READ-ONLY access; the token is kept in
              %USERPROFILE%\.pflab\gmail_token.json (outside the repo, beside secrets.toml); the client file he downloads from Google Cloud is
              %USERPROFILE%\.pflab\gmail_client.json. With this permission the system cannot send, delete, label or mark anything.
    fetch     once a day at 21:15 (job `mail`): messages with an attachment (PDF, Excel, CSV) from the last 40 days that were not seen before; each
              attachment is opened IN MEMORY and kept only if its content is a ledger document (a CAS, a Console tradebook / funds ledger /
              contract note, a bank statement, a deposit interest certificate, a GIFT City statement): anything else is dropped, never written.
    protected the passwords he saved under [passwords] are tried in memory; only the NAME of the one that opened a file is recorded. Protected
              attachments none opens become ONE Needs-from-you item per sender, with a password slot named after it (NSDL, SBI ...) in
              Settings > Keys; saving a password fetches again at once; the item closes itself when the files open.
    cold start the first look (nothing seen yet) reads a year of mail, so Setup can propose his accounts from it: then one item asks him to
              approve them in Setup ("Use these accounts", "Add everything to the ledger"); nothing is written before his press.
    storage   a kept file goes through the inbox exactly like one he drops (`app/inbox.receive`): saved as it arrived, still encrypted, in the app's
              private `new/` folder; checked by a dry run; written to the ledger only on his press. Decrypted only in memory, at a build.

Nothing read here is sent to any model or API. The workshop (beta) never reads his mail unless run with `--live`.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
API = "https://gmail.googleapis.com/gmail/v1/users/me"
QUERY = "has:attachment newer_than:{days}d (filename:pdf OR filename:xlsx OR filename:xls OR filename:csv)"
KEEP = ("cas", "bank", "tradebook", "contract_note", "funds_ledger", "fd_certificate", "gift_city")
EXTS = (".pdf", ".xlsx", ".xls", ".csv")
AGENT = "mail"
FIRST_DAYS, FIRST_LIMIT = 400, 1500          # S65 values, kept for reference: the walk below replaces the single capped look
WINDOW_DAYS = 60                             # one slice of history listed at a time, newest first, saved when finished
HORIZON_DAYS = 3650                          # how far back the walk goes (ten years); the coverage says so, never "all of it"
BATCH_MESSAGES = 600                         # new messages handled per run; the walk resumes where it stopped
RECENT_LIMIT, WINDOW_LIMIT = 2000, 5000
MAIL_WORDS = {"co", "in", "com", "net", "org", "gov", "mail", "mails", "email", "mailer", "mailers", "alerts", "alert", "info", "noreply"}


class MailError(RuntimeError):
    pass


def home() -> Path:
    return Path.home() / ".pflab"


def client_path() -> Path:
    return home() / "gmail_client.json"


def token_path() -> Path:
    return home() / "gmail_token.json"


def enabled() -> bool:
    """Email is OFF (his decision 2026-10-30: he drops every statement and file by hand). Nothing reads, asks about or shows a mailbox unless this
    is switched on deliberately with PFLAB_MAIL=on; the code stays, tested, for the day he wants it back."""
    return os.environ.get("PFLAB_MAIL", "").strip().lower() in ("1", "on", "yes", "true")


def connected() -> bool:
    return enabled() and token_path().exists()


def downloaded_client() -> Optional[Path]:
    """The client file as Google names it in Downloads (client_secret_*.json), newest first, when it was not moved yet."""
    found = sorted((Path.home() / "Downloads").glob("client_secret_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def has_client() -> bool:
    return client_path().exists() or downloaded_client() is not None


def connect(client_file: Optional[Path] = None, flow_factory=None) -> str:
    """His one step: the browser opens Google's page for READ-ONLY access; the token is saved. Returns the address connected."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if client_file is None and not client_path().exists() and downloaded_client():
        home().mkdir(parents=True, exist_ok=True)
        shutil.copyfile(downloaded_client(), client_path())         # moved beside secrets.toml, out of Downloads' reach
    client_file = Path(client_file or client_path())
    if not client_file.exists():
        raise MailError(f"no Google client file at {client_file}: download it from Google Cloud (Credentials, OAuth client, Desktop app)")
    flow = (flow_factory or InstalledAppFlow.from_client_secrets_file)(str(client_file), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent")
    granted = set(getattr(creds, "scopes", None) or SCOPES)
    if granted - set(SCOPES):
        raise MailError(f"Google granted more than read-only ({sorted(granted)}): refused, nothing saved")
    home().mkdir(parents=True, exist_ok=True)
    token_path().write_text(creds.to_json(), encoding="utf-8")
    return profile(session())


def session():
    """An authorised HTTP session (read-only scope), refreshed when its token has expired."""
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials
    from pflab import activation
    activation.guard("reading the mailbox")
    if not connected():
        raise MailError("Gmail is not connected: run `pflab mail connect` (or Settings > Connect Gmail)")
    creds = Credentials.from_authorized_user_file(str(token_path()), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        token_path().write_text(creds.to_json(), encoding="utf-8")
    return AuthorizedSession(creds)


def _get(sess, path: str, params: Optional[dict] = None) -> dict:
    r = sess.get(f"{API}/{path}", params=params or {}, timeout=30)
    if r.status_code != 200:
        raise MailError(f"Gmail answered {r.status_code} for {path.split('/')[0]}")
    return r.json()


def profile(sess) -> str:
    return _get(sess, "profile").get("emailAddress", "")


def message_ids(sess, query: str, limit: int = 300) -> List[str]:
    ids, token = [], None
    while len(ids) < limit:
        d = _get(sess, "messages", {"q": query, "maxResults": 100, **({"pageToken": token} if token else {})})
        ids += [m["id"] for m in d.get("messages", [])]
        token = d.get("nextPageToken")
        if not token:
            break
    return ids[:limit]


def window_query(start: date, end: date) -> str:
    """Attachments dated from `start` up to (not including) `end`: Gmail's after:/before: take days as YYYY/MM/DD."""
    return (f"has:attachment after:{start:%Y/%m/%d} before:{end:%Y/%m/%d} "
            "(filename:pdf OR filename:xlsx OR filename:xls OR filename:csv)")


def mailbox_key(sess) -> str:
    """A stable name for this mailbox's checkpoint (a hash of its address, never the address)."""
    try:
        return "mb:" + hashlib.sha1(profile(sess).lower().encode()).hexdigest()[:10]
    except Exception:
        return "mb:default"


def scan_state(con, mailbox: str) -> dict:
    r = con.execute("SELECT oldest, complete, scanned FROM mail_scan WHERE mailbox=?", [mailbox]).fetchone()
    return {"oldest": r[0], "complete": bool(r[1]), "scanned": int(r[2])} if r else {"oldest": None, "complete": False, "scanned": 0}


def _save_scan(con, mailbox: str, oldest: date, complete: bool, scanned: int, now: datetime) -> None:
    con.execute("INSERT OR REPLACE INTO mail_scan VALUES (?,?,?,?,?)", [mailbox, oldest, complete, scanned, now])


def coverage(con, now: datetime) -> list:
    """Per mailbox: how far back it has been read. Honest about what email alone cannot show: a mailbox walked to the horizon has had
    its ATTACHMENTS read; statements that only came as a link, or with no file, were not looked for here."""
    out = []
    if not enabled():
        return out
    for mb, oldest, complete, scanned, upd in con.execute("SELECT mailbox, oldest, complete, scanned, updated_at FROM mail_scan ORDER BY mailbox").fetchall():
        out.append({"mailbox": mb, "read_back_to": str(oldest), "reached_horizon": bool(complete), "messages": int(scanned),
                    "horizon_days": HORIZON_DAYS, "link_only_or_no_file_mail_checked": False, "updated": str(upd)[:16]})
    return out


def scan_ids(sess, con, mailbox: str, now: datetime, days: int, budget: Optional[int] = None):
    """The message ids to handle this run: the recent weeks first (new mail), then history walked back one window at a time from where
    the last run stopped. A window is marked finished only after every id in it was handed out and handled, so a stop (the budget, a
    crash, a closed lid) resumes inside it; messages already seen are skipped without counting. Old evidence is never starved by the
    newest page: the walk always moves back."""
    budget = BATCH_MESSAGES if budget is None else budget
    today = now.date()
    given: set = set()                                       # an id is handed out once per run, however many windows list it
    for mid in message_ids(sess, window_query(today - timedelta(days=days), today + timedelta(days=1)), RECENT_LIMIT):
        given.add(mid)
        yield mid
    st = scan_state(con, mailbox)
    if st["complete"]:
        return
    oldest = st["oldest"] or (today + timedelta(days=1))
    horizon = today - timedelta(days=HORIZON_DAYS)
    n = 0
    while oldest > horizon:
        start = oldest - timedelta(days=WINDOW_DAYS)
        for mid in message_ids(sess, window_query(start, oldest), WINDOW_LIMIT):
            if mid in given or _seen(con, mid):
                continue
            if n >= budget:
                return                                       # this window stays open: the next run resumes here
            n += 1
            given.add(mid)
            yield mid
        oldest = start
        _save_scan(con, mailbox, oldest, oldest <= horizon, st["scanned"] + n, now)
        if n >= budget:
            return
    _save_scan(con, mailbox, oldest, True, st["scanned"] + n, now)


def _parts(payload: dict) -> Iterable[dict]:
    yield payload
    for p in payload.get("parts", []) or []:
        yield from _parts(p)


def attachments(sess, mid: str) -> Tuple[dict, List[Tuple[str, bytes]]]:
    """(the message's from / date, [(file name, bytes)]) for its PDF, Excel and CSV attachments."""
    m = _get(sess, f"messages/{mid}", {"format": "full"})
    heads = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
    meta = {"from": heads.get("from", ""), "date": heads.get("date", ""), "subject": heads.get("subject", "")}
    out = []
    for p in _parts(m.get("payload", {})):
        name, body = p.get("filename") or "", p.get("body") or {}
        if not name or not name.lower().endswith(EXTS):
            continue
        if body.get("attachmentId"):
            data = _get(sess, f"messages/{mid}/attachments/{body['attachmentId']}").get("data", "")
        else:
            data = body.get("data", "")
        out.append((name, base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))))
    return meta, out


def _seen(con, mid: str) -> bool:
    return bool(con.execute("SELECT 1 FROM mail_seen WHERE msg_id=?", [mid]).fetchone())


def sender_name(sender: str) -> str:
    """'NSDL e-CAS <cas@nsdl.co.in>' -> 'NSDL': the name the password for that sender's files is saved under."""
    m = re.search(r"@([A-Za-z0-9.-]+)", sender or "")
    parts = [p for p in (m.group(1) if m else "").lower().split(".") if p and p not in MAIL_WORDS]
    return re.sub(r"[^A-Z0-9_]", "_", parts[-1].upper())[:24] if parts else "EMAIL"


def passwords_wanted(con) -> List[str]:
    """Password names the locked mail asks for (Settings > Keys shows a slot for each)."""
    return [k.split(":", 2)[2] for (k,) in con.execute("SELECT subject_key FROM questions WHERE status='open' AND subject_key LIKE 'mail:locked:%' "
                                                       "ORDER BY q_id").fetchall()]


def fetch(rt, sess=None, days: int = 40, now: Optional[datetime] = None) -> dict:
    """Bring new statement attachments into the inbox. Returns counts; never raises for one bad message."""
    from pflab import guard
    from pflab.agents import questions
    from pflab.app import inbox as ib
    from pflab.ingest import sniff
    from pflab.pm.store import next_id
    guard.require("mail")
    sess = sess or session()
    con, now = rt.cursor(), now or rt.clock()
    pw = sniff.passwords_from_secrets()
    out = {"messages": 0, "files": 0, "kept": 0, "duplicates": 0, "locked": 0, "dropped": 0, "errors": 0}
    locked_by: dict = {}
    from pflab.app import readiness
    from pflab.ingest import coverage
    mailbox = mailbox_key(sess)
    for mid in scan_ids(sess, con, mailbox, now, days):
        if _seen(con, mid):
            continue
        gap = f"mail:msg:{mid}"
        if readiness.give_up(con, gap):                      # failed three times: left as a visible gap, not retried by itself
            continue
        out["messages"] += 1
        kept, locked = 0, False
        try:
            meta, files = attachments(sess, mid)
        except Exception as e:
            out["errors"] += 1
            readiness.open_gap(con, gap, "mail", f"a message could not be fetched ({type(e).__name__}: {str(e)[:100]})", now)
            continue
        try:
            for name, data in files:
                out["files"] += 1
                info = sniff.sniff(data, name, pw)
                sha12 = hashlib.sha256(data).hexdigest()[:12]
                coverage.note_account(con, info, f"mail:{mailbox}", now, sha12)                       # an account is recorded by what the file shows
                if info["kind"] in KEEP:
                    try:
                        r = ib.receive(rt, name, data)
                        out["duplicates" if r.get("duplicate") else "kept"] += 1
                        kept += 0 if r.get("duplicate") else 1
                    except ValueError:                           # a bank statement for an account not set up: the inbox asked him
                        out["kept"] += 1
                elif sniff.is_encrypted(data, name) and not info.get("password_name"):
                    out["locked"] += 1
                    locked_by.setdefault(sender_name(meta["from"]), (meta, name))
                    locked = True
                    coverage.note_gap(con, "locked", sha12, f"a locked file from {sender_name(meta['from'])} ({meta['date'][:16]}): no saved password opens it", now)
                else:
                    out["dropped"] += 1
                    coverage.note_gap(con, "unsupported", sha12, f"a file from {sender_name(meta['from'])} ({meta['date'][:16]}) that no reader recognises as a statement", now)
        except Exception as e:                                   # S67: one message that cannot be stored never stops the rest; it is a counted gap
            out["errors"] += 1
            readiness.open_gap(con, gap, "mail", f"a message's files could not be stored ({type(e).__name__}: {str(e)[:100]})", now)
            continue
        if not locked:                                       # a message with a locked file is not marked seen: tried again once a password is added
            con.execute("INSERT OR REPLACE INTO mail_seen VALUES (?,?,?,?)", [mid, now, len(files), kept])
            readiness.close_gap(con, gap, now)
    for pname, (meta, name) in locked_by.items():           # one item per sender, however many of its files are locked
        questions.ask(con, AGENT, f"mail:locked:{pname}",
                      f"Password-protected files came by email from {meta['from'][:80]} (for example {name}, {meta['date'][:16]}) and none of "
                      f"your saved passwords opens them. If they are statements, type the password in Settings > Keys and passwords under "
                      f"'{pname}' (the email itself usually says what it is); I try again at once.", now)
    for k in passwords_wanted(con):                          # opened now (a password was added): the item closes itself
        if k not in locked_by:
            questions.drop(con, f"mail:locked:{k}", now)
    waiting = con.execute("SELECT count(*) FROM inbox_items WHERE status='awaiting setup'").fetchone()[0]
    if waiting:
        questions.ask(con, AGENT, "mail:setup",
                      f"Your statements are here ({waiting} file(s), most of them from your email). Open Setup (Settings > Open Setup): I read your "
                      "accounts from them; check them, press 'Use these accounts', then 'Add everything to the ledger'. Nothing is written before "
                      "your press, and Setup lists any file email did not bring.", now)
    elif (rt.pm_dir / "sources.toml").exists():
        questions.drop(con, "mail:setup", now)
    ready = con.execute("SELECT count(*), max(item_id) FROM inbox_items WHERE status='ready' AND kind IN ('cas', 'bank', 'tradebook', "
                        "'contract_note', 'funds_ledger')").fetchone()
    for (k,) in con.execute("SELECT subject_key FROM questions WHERE status='open' AND subject_key LIKE 'mail:ready:%'").fetchall():
        if not ready[0] or k != f"mail:ready:{ready[1]}":   # added, or a newer batch replaces it
            questions.drop(con, k, now)
    if ready[0]:                                             # after Setup: new statements wait, checked, for his press
        questions.ask(con, AGENT, f"mail:ready:{ready[1]}",
                      f"{ready[0]} new statement(s) are checked and ready (see Inbox and files). Press 'Add everything to the ledger' in "
                      "Setup to add them; nothing is written before your press.", now)
    try:                                                     # S67 local: the inventory goes to him once, grouped, as soon as there is one to show
        coverage.ask_inventory(con, now)
    except Exception:
        pass
    rt.bump("inbox")
    return out


def ask_to_connect(con, now: datetime) -> Optional[int]:
    from pflab.agents import questions
    if not enabled():
        return None
    return questions.ask(con, AGENT, "mail:connect",
                         "Connect Gmail so your statements arrive by themselves (read-only: I can never send, delete or change anything). "
                         "Then I read a year of your statement emails, ask for any file password I need, and propose your accounts in Setup "
                         "for your yes. Settings > Connect Gmail, or `pflab mail connect`; the one-time Google steps are in README.", now)
