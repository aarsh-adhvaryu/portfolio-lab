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
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
API = "https://gmail.googleapis.com/gmail/v1/users/me"
QUERY = "has:attachment newer_than:{days}d (filename:pdf OR filename:xlsx OR filename:xls OR filename:csv)"
KEEP = ("cas", "bank", "tradebook", "contract_note", "funds_ledger", "fd_certificate", "gift_city")
EXTS = (".pdf", ".xlsx", ".xls", ".csv")
AGENT = "mail"
FIRST_DAYS, FIRST_LIMIT = 400, 1500          # the first look (a cold start): a year of statements, so Setup and the tax year have their history
MAIL_WORDS = {"co", "in", "com", "net", "org", "gov", "mail", "mails", "email", "mailer", "mailers", "alerts", "alert", "info", "noreply"}


class MailError(RuntimeError):
    pass


def home() -> Path:
    return Path.home() / ".pflab"


def client_path() -> Path:
    return home() / "gmail_client.json"


def token_path() -> Path:
    return home() / "gmail_token.json"


def connected() -> bool:
    return token_path().exists()


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
    first = not con.execute("SELECT 1 FROM mail_seen LIMIT 1").fetchone()
    locked_by: dict = {}
    from pflab.app import readiness
    for mid in message_ids(sess, QUERY.format(days=FIRST_DAYS if first else days), FIRST_LIMIT if first else 300):
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
                else:
                    out["dropped"] += 1
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
    rt.bump("inbox")
    return out


def ask_to_connect(con, now: datetime) -> Optional[int]:
    from pflab.agents import questions
    return questions.ask(con, AGENT, "mail:connect",
                         "Connect Gmail so your statements arrive by themselves (read-only: I can never send, delete or change anything). "
                         "Then I read a year of your statement emails, ask for any file password I need, and propose your accounts in Setup "
                         "for your yes. Settings > Connect Gmail, or `pflab mail connect`; the one-time Google steps are in README.", now)
