r"""What his emails SAY, not only what they attach (S66; his yes 2026-10-28: "do it").

    find    read-only Gmail: emails of the last days whose subject names a money event (TEXT_QUERY); the body as plain text
    read    the LOCAL model only (his bank and broker emails never leave the PC; no API road exists here): a bounded kind and the
            fields of that kind, as JSON. Every number and date it gives must appear in the email's own text: one that does not
            is dropped (`guard`), never kept. The model names; code decides.
    check   code compares each fact with his record and Kite (`check`):
              trade          kite_trades, then the ledger's buy/sell events (same security and side, +-3 days, same quantity)
              dividend       the ledger's income (same security, +-7 days, the same gross or net)
              interest, bank_debit, bank_credit   the ledger's cash lines (+-3 days, the same amount)
              ipo_allotment  ipo_applications (allotted, the same quantity) or a buy event of the same quantity
              fd_booking, fd_maturity  the deposits on file (the same principal or maturity amount, +-7 days)
              corporate_action, research, ipo_refund   information
    status  matched (the record has it) | pending (the statement or Kite should bring it; checked again each day) | new (still
            missing after the wait: one Needs-from-you item) | conflict (the record has it with another quantity or amount: asked at
            once) | info. Nothing is written to the ledger here: a deposit or IPO allotment he confirms goes in through Setup's forms.
    public  a research or corporate-action email that names no id of his (the egress check) becomes a knowledge-graph document about the
            companies it names; the readers read it like any filing.
"""
from __future__ import annotations

import html
import json
import re
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

KINDS = ("trade", "ipo_allotment", "ipo_refund", "dividend", "interest", "bank_debit", "bank_credit", "fd_booking", "fd_maturity",
         "corporate_action", "research", "other")
NUMBERS = ("quantity", "price", "amount", "rate_pct", "maturity_amount")
DATES = ("date", "maturity_date", "record_date")
TEXTS = ("symbol", "company", "side", "deposit_last4", "action", "ratio")
TEXT_QUERY = ("newer_than:{days}d -category:social subject:(allotment OR allotted OR dividend OR credited OR debited OR \"fixed deposit\" "
              "OR \"term deposit\" OR deposit OR \"contract note\" OR trade OR traded OR executed OR IPO OR refund OR \"record date\" OR bonus "
              "OR split OR buyback OR rights OR interest OR maturity OR matured OR research OR report OR results)")
FIRST_DAYS, DAYS, LIMIT, BUDGET_S = 60, 3, 300, 25 * 60
WAIT = {"trade": 3, "dividend": 10, "interest": 40, "bank_debit": 40, "bank_credit": 40, "ipo_allotment": 0, "fd_booking": 0,
        "fd_maturity": 7}
ASK = ("trade", "ipo_allotment", "fd_booking", "fd_maturity")      # bank lines and dividends come with the statements: shown, not asked
PUBLIC = ("research", "corporate_action")
AGENT = "mail"
MAX_BODY = 6000
SYSTEM = ("You read one email sent to an Indian retail investor and list the financial facts it states, one object each. Copy numbers "
          "and dates exactly as the email writes them; never compute, convert or guess; a field the email does not state is null. "
          "Kinds: trade (a buy or sell that was executed), ipo_allotment, ipo_refund, dividend (paid or credited), interest (credited), "
          "bank_debit, bank_credit, fd_booking (a fixed or term deposit opened), fd_maturity (a deposit matured or closed), "
          "corporate_action (bonus, split, buyback, rights, merger, record date), research (a report, newsletter or market view), "
          "other (promotions, OTPs, statements, anything else: return no facts). side is buy or sell; deposit_last4 is the last "
          "four digits of a deposit number. Each fact lists EVERY field, null where the email does not state it. One fact per event: "
          "never repeat a fact. Example: 'Bought 25 ALPHACO at Rs 1,234.50 on 27-Oct-2026' gives one fact: {kind: trade, symbol: ALPHACO, "
          "company: null, side: buy, quantity: 25, price: 1234.5, amount: null, rate_pct: null, date: 27-Oct-2026, ...null}. Reply in JSON.")
_NULL = lambda t: {"type": [t, "null"]}                                 # noqa: E731
ORDER = ("kind", "symbol", "company", "side", "quantity", "price", "amount", "rate_pct", "date", "maturity_date", "maturity_amount",
         "deposit_last4", "record_date", "action", "ratio")
SCHEMA = {"type": "object", "required": ["facts"], "properties": {"facts": {"type": "array", "maxItems": 4, "items": {
    "type": "object", "required": list(ORDER), "additionalProperties": False,
    "properties": {"kind": {"enum": list(KINDS)}, **{k: _NULL("number") for k in NUMBERS},
                   **{k: _NULL("string") for k in DATES + TEXTS}}}}}}
_NUM = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE_RX = [re.compile(p, re.I) for p in (r"\b\d{4}-\d{2}-\d{2}\b", r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b",
                                         rf"\b\d{{1,2}}(?:st|nd|rd|th)?[- ]{_MON}[-, ]+\d{{2,4}}\b", rf"\b{_MON} \d{{1,2}},? \d{{4}}\b")]


# --- the email as text --------------------------------------------------------------------------------------------------

def body_text(payload: dict) -> str:
    """Plain text of a Gmail message payload: its text/plain part, else its HTML without tags."""
    import base64
    from pflab.ingest.gmail import _parts
    plain, rich = [], []
    for p in _parts(payload):
        data = (p.get("body") or {}).get("data")
        if not data or p.get("filename"):
            continue
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
        (plain if p.get("mimeType") == "text/plain" else rich if p.get("mimeType") == "text/html" else []).append(raw)
    if plain:
        text = "\n".join(plain)
    else:
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", "\n".join(rich))
        text = html.unescape(re.sub(r"(?s)<br\s*/?>|</p>|</tr>|</div>", "\n", text))
        text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()[:MAX_BODY]


# --- the guard: only what the email itself says ----------------------------------------------------------------------------

def numbers_in(text: str) -> List[float]:
    return [float(m.replace(",", "")) for m in _NUM.findall(text or "")]


def dates_in(text: str) -> List[date]:
    from dateutil import parser
    out = []
    for k, rx in enumerate(_DATE_RX):
        for m in rx.findall(text or ""):
            try:
                out.append(date.fromisoformat(m) if k == 0 else parser.parse(m, dayfirst=True).date())
            except (ValueError, OverflowError):
                pass
    return out


def guard(fact: dict, text: str) -> Tuple[dict, List[str]]:
    """The fact with every number and date the email does not itself state set to None; the names of those dropped."""
    nums, days = numbers_in(text), set(dates_in(text))
    out, dropped = {"kind": fact.get("kind") if fact.get("kind") in KINDS else "other"}, []
    for k in NUMBERS:
        v = fact.get(k)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            dropped.append(k)
            continue
        if any(abs(v - n) <= 0.005 for n in nums):
            out[k] = v
        else:
            dropped.append(k)
    for k in DATES:
        v = fact.get(k)
        if not v:
            continue
        try:
            d = date.fromisoformat(str(v)[:10])
        except ValueError:
            d = None
        if d is not None and d in days:
            out[k] = d.isoformat()
        else:
            hits = dates_in(str(v))                          # the model copied the email's own spelling
            if hits and hits[0] in days:
                out[k] = hits[0].isoformat()
            else:
                dropped.append(k)
    for k in TEXTS:
        v = fact.get(k)
        if v not in (None, ""):
            out[k] = str(v).strip()[:120]
    if out.get("side") not in (None, "buy", "sell"):
        out["side"] = {"bought": "buy", "sold": "sell"}.get(str(out["side"]).lower())
    if out.get("deposit_last4") and not re.fullmatch(r"\d{4}", out["deposit_last4"]) or \
            out.get("deposit_last4") and out["deposit_last4"] not in (text or ""):
        out.pop("deposit_last4")
        dropped.append("deposit_last4")
    return out, dropped


def read(text: str, subject: str, model: str, chat=None) -> List[dict]:
    """The local model's facts, guarded. Raises on a model failure (the email is read again tomorrow)."""
    from pflab.llm import client
    from pflab.llm.eval12 import _json
    r = (chat or client.chat)(model, [{"role": "system", "content": SYSTEM},
                                      {"role": "user", "content": f"Subject: {subject}\n\n{text}"}],
                              fmt=SCHEMA, num_predict=700, num_ctx=8192)
    d = _json(r.text)
    if d is None:
        raise ValueError("the local model's reply did not parse")
    out, seen = [], set()
    for f in (d.get("facts") or [])[:4]:
        g, dropped = guard(f, f"{subject}\n{text}")
        key = json.dumps(g, sort_keys=True)
        if g["kind"] != "other" and key not in seen:          # one fact per event: a repeat is dropped
            seen.add(key)
            out.append({**g, **({"dropped": dropped} if dropped else {})})
    return out


# --- the check: code against his record ----------------------------------------------------------------------------------

def _isin(con, f: dict) -> Optional[str]:
    sym = (f.get("symbol") or "").upper().strip()
    if sym:
        r = con.execute("SELECT isin FROM instruments WHERE upper(symbol)=? LIMIT 1", [sym]).fetchone()
        if r:
            return r[0]
    name = (f.get("company") or "").strip()
    if len(name) >= 4:
        r = con.execute("SELECT isin FROM instruments WHERE lower(name) LIKE ? LIMIT 2", [f"%{name.lower()}%"]).fetchall()
        if len(r) == 1:
            return r[0][0]
    return None


def _near(d: date, days: int) -> List[date]:
    return [d - timedelta(days=days), d + timedelta(days=days)]


def check(con, f: dict, received: date, today: date) -> Tuple[str, str]:
    """(status, plain words) for one guarded fact."""
    k = f["kind"]
    d = date.fromisoformat(f["date"]) if f.get("date") else received
    late = (today - d).days > WAIT.get(k, 0)
    wait = ("new", "not in your record or Kite after the wait") if late else ("pending", "the statement or Kite should bring it")
    if k == "trade":
        isin, qty = _isin(con, f), f.get("quantity")
        if not (isin or f.get("symbol")) or not f.get("side"):
            return "info", "a trade without its security or side: shown only"
        rows = con.execute("SELECT qty FROM kite_trades WHERE (isin=? OR upper(symbol)=?) AND lower(side)=? AND trade_date BETWEEN ? AND ?",
                           [isin, (f.get("symbol") or "").upper(), f["side"], *_near(d, 3)]).fetchall()
        rows += con.execute("SELECT qty FROM events WHERE isin=? AND kind=? AND trade_date BETWEEN ? AND ?",
                            [isin, f["side"], *_near(d, 3)]).fetchall() if isin else []
        if qty is None and rows or any(abs(abs(q) - qty) < 1e-6 for (q,) in rows):
            return "matched", "in your record or Kite"
        if rows:
            return "conflict", f"your record has a {f['side']} of {rows[0][0]:g} near that day, the email says {qty:g}"
        return wait
    if k == "dividend":
        isin, amt = _isin(con, f), f.get("amount")
        rows = con.execute("SELECT gross, net FROM income WHERE isin=? AND kind='dividend' AND date BETWEEN ? AND ?",
                           [isin, *_near(d, 7)]).fetchall() if isin else []
        if rows and (amt is None or any(abs(amt - x) < 1 for r in rows for x in r if x is not None)):
            return "matched", "in your record"
        if rows:
            return "conflict", f"your record has a dividend near that day of a different amount ({rows[0][1]:,.2f})"
        return wait
    if k in ("interest", "bank_debit", "bank_credit"):
        amt = f.get("amount")
        if amt is None:
            return "info", "no amount stated"
        r = con.execute("SELECT count(*) FROM cash_ledger WHERE date BETWEEN ? AND ? AND abs(abs(amount) - ?) < 1",
                        [*_near(d, 3), amt]).fetchone()[0]
        return ("matched", "in your record") if r else wait
    if k == "ipo_allotment":
        isin, qty = _isin(con, f), f.get("quantity")
        r = con.execute("SELECT count(*) FROM ipo_applications WHERE (isin=? OR ?) AND allotted_qty=?",
                        [isin, isin is None, qty]).fetchone()[0] if qty is not None else 0
        r += con.execute("SELECT count(*) FROM events WHERE isin=? AND kind='buy' AND qty=?", [isin, qty]).fetchone()[0] \
            if isin and qty is not None else 0
        return ("matched", "in your record") if r else ("new", "not in your record: add it in Setup's IPO form if it is yours")
    if k in ("fd_booking", "fd_maturity"):
        amt = f.get("amount") if k == "fd_booking" else (f.get("maturity_amount") or f.get("amount"))
        col, when = ("principal", "term_start") if k == "fd_booking" else ("maturity_amount", "maturity")
        r = con.execute(f"SELECT count(*) FROM fds WHERE abs({col} - ?) < 1 AND {when} BETWEEN ? AND ?",
                        [amt, *_near(d, 7)]).fetchone()[0] if amt is not None else 0
        if not r and f.get("deposit_last4"):
            r = con.execute("SELECT count(*) FROM fds WHERE fd_id LIKE ?", [f"%{f['deposit_last4']}"]).fetchone()[0]
        if r:
            return "matched", "on your deposit list"
        return ("new", "not on your deposit list: add it in Setup's deposit form") if late or k == "fd_booking" else wait
    return "info", "information"


def say(f: dict) -> str:
    """The fact in plain words (only the fields the email stated)."""
    who = f.get("symbol") or f.get("company") or ""
    bits = {"trade": f"{f.get('side') or 'a trade'} {f.get('quantity', '') or ''} {who} at {f.get('price', '') or '?'}",
            "ipo_allotment": f"IPO allotment: {f.get('quantity', '') or '?'} {who}",
            "dividend": f"dividend from {who}: Rs {f.get('amount', '') or '?'}",
            "fd_booking": f"deposit opened: Rs {f.get('amount', '') or '?'}" + (f" at {f['rate_pct']}%" if f.get("rate_pct") else "")
            + (f", maturing {f['maturity_date']}" if f.get("maturity_date") else "")
            + (f" (Rs {f['maturity_amount']:,.2f})" if f.get("maturity_amount") else ""),
            "fd_maturity": f"deposit matured: Rs {f.get('maturity_amount') or f.get('amount') or '?'}"}
    s = bits.get(f["kind"], f"{f['kind'].replace('_', ' ')} {who} Rs {f.get('amount', '') or ''}")
    return re.sub(r"\s+", " ", s + (f" on {f['date']}" if f.get("date") else "")).strip()


# --- the run --------------------------------------------------------------------------------------------------------------

def _companies(con, text: str, stock_list: List[dict]) -> List[str]:
    """Held and listed companies the email names among its first words."""
    from pflab.kg import build as kb
    held = [i for (i,) in con.execute("SELECT DISTINCT isin FROM lots WHERE qty > 0 AND isin IS NOT NULL").fetchall()]
    isins = list(dict.fromkeys(held + [s["isin"] for s in stock_list if s.get("isin")]))
    if not isins:
        return []
    names = kb.names_for(con, isins, stock_list)
    return [i for i in isins if kb.is_about(text, names.get(i, []), k=40)]


def _public(rt, mid: str, meta: dict, text: str, f: dict, gate) -> Optional[str]:
    """A research or corporate-action email as a knowledge-graph document, when it names no id of his."""
    from pflab.hq import egress as eg
    from pflab.kg import graph as g
    from pflab.plan import guards as gd
    try:
        eg.check(f"{meta.get('subject', '')}\n{text}", gate)
    except eg.EgressBlocked:
        return None
    con = rt.cursor()
    about = _companies(con, f"{meta.get('subject', '')} {text}", gd.stock_list())
    if not about:
        return None
    sender = re.sub(r"<[^>]*>|\S+@\S+", "", meta.get("from", "")).strip(' "') or "email"     # the name only, never an address
    import hashlib
    did = g.doc(con, "email", f"mail:{mid}", rt.clock(), meta.get("subject") or f["kind"], source=sender[:80],
                attrs={"kind": f["kind"], "provenance": "email, checked by the mail reader against his ids",
                       "cleared": hashlib.sha256(text.encode("utf-8")).hexdigest()})   # S67: the hash readers.email_for_api must find again
    p = rt.data_root / "kg" / "mail" / f"{did.split(':')[-1]}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    con.execute("UPDATE kg_docs SET text_path=?, text_status='ok' WHERE doc_id=?", [str(p), did])
    for i in about:
        g.edge(con, did, "about", f"company:{i}", rt.clock(), "mail")
    return did


def recheck(rt, now: datetime) -> int:
    """Facts still pending or new, checked again (the statement or Kite may have brought them); a matched one closes its item."""
    from pflab.agents import questions
    con, n = rt.cursor(), 0
    for fid, kind, fj, rec, status in con.execute("SELECT fact_id, kind, fields_json, received_at, status FROM mail_facts "
                                                  "WHERE status IN ('pending', 'new')").fetchall():
        f = {**json.loads(fj), "kind": kind}
        st, why = check(con, f, rec.date() if isinstance(rec, datetime) else rec, now.date())
        if st != status:
            con.execute("UPDATE mail_facts SET status=?, detail=?, checked_at=? WHERE fact_id=?", [st, why, now, fid])
            n += 1
            if st == "matched":
                questions.drop(con, f"mailfact:{fid}", now)
            elif st in ("new", "conflict") and kind in ASK:
                _ask(con, fid, f, why, now)
    return n


def _ask(con, fid: int, f: dict, why: str, now: datetime, sender: str = "") -> None:
    from pflab.agents import questions
    questions.ask(con, AGENT, f"mailfact:{fid}", f"An email{(' from ' + sender[:60]) if sender else ''} says: {say(f)}. {why[0].upper() + why[1:]}. "
                  "If it is not yours or is wrong, reply so; nothing is written to your record from an email.", now)


def run(rt, sess, model: str, now: Optional[datetime] = None, chat=None) -> dict:
    """Read the money emails not read before (the local model), guard and check each fact, ask what only he can answer."""
    from pflab import guard as og
    from pflab.hq import egress as eg
    from pflab.ingest import gmail
    from pflab.pm.store import next_id
    og.require("mail")
    con, now = rt.cursor(), now or rt.clock()
    first = not con.execute("SELECT 1 FROM mail_facts LIMIT 1").fetchone()
    out = {"emails": 0, "facts": 0, "matched": 0, "pending": 0, "new": 0, "conflict": 0, "info": 0, "public": 0, "errors": 0}
    out["rechecked"] = recheck(rt, now)
    gate = eg.load(con)
    t0 = time.time()
    for mid in gmail.message_ids(sess, TEXT_QUERY.format(days=FIRST_DAYS if first else DAYS), LIMIT):
        if con.execute("SELECT 1 FROM mail_facts WHERE msg_id=?", [mid]).fetchone():
            continue
        if time.time() - t0 > BUDGET_S:                       # the local model takes about 10 s an email: the rest wait for the next run
            out["left"] = out.get("left", 0) + 1
            continue
        try:
            m = gmail._get(sess, f"messages/{mid}", {"format": "full"})
            heads = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
            meta = {"from": heads.get("from", ""), "subject": heads.get("subject", "")}
            text = body_text(m.get("payload", {}))
            facts = read(text, meta["subject"], model, chat)
        except Exception:
            out["errors"] += 1                                # read again tomorrow
            continue
        out["emails"] += 1
        try:
            received = datetime.fromtimestamp(int(m.get("internalDate", 0)) / 1000)
        except (TypeError, ValueError):
            received = now
        for seq, f in enumerate(facts or [{"kind": "other"}]):
            status, why = ("info", "nothing to check") if f["kind"] == "other" else check(con, f, received.date(), now.date())
            fid = next_id(con, "mail_facts", "fact_id")
            con.execute("INSERT INTO mail_facts (fact_id, msg_id, seq, received_at, sender, subject, kind, fields_json, status, detail, "
                        "model, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        [fid, mid, seq, received, meta["from"][:200], meta["subject"][:300], f["kind"],
                         json.dumps({k: v for k, v in f.items() if k != "kind"}), status, why, model, now])
            if f["kind"] == "other":
                continue
            out["facts"] += 1
            out[status] += 1
            if status in ("new", "conflict") and f["kind"] in ASK:
                _ask(con, fid, f, why, now, meta["from"])
            if f["kind"] in PUBLIC and _public(rt, mid, meta, text, f, gate):
                out["public"] += 1
    rt.bump("inbox")
    return out


def summary(con, limit: int = 30) -> dict:
    """For the screen: counts by status and the latest facts (plain words)."""
    counts = dict(con.execute("SELECT status, count(*) FROM mail_facts WHERE kind <> 'other' GROUP BY status").fetchall())
    rows = con.execute("SELECT received_at, kind, fields_json, status, detail, sender FROM mail_facts WHERE kind <> 'other' "
                       "ORDER BY received_at DESC LIMIT ?", [limit]).fetchall()
    return {"counts": counts, "latest": [{"received": str(r[0])[:16], "kind": r[1], "says": say({**json.loads(r[2]), "kind": r[1]}),
                                          "status": r[3], "detail": r[4], "from": (r[5] or "")[:60]} for r in rows]}
