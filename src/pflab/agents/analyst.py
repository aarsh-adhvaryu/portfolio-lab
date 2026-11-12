"""The research analyst behind a doorbell (PLAN A7; the investor 2026-10-17: Claude Opus 5.5, local first, public data only).

The local agents answer first. The doorbell rings the API only for deep research, and only like this:
    1. reuse    a note on the same topic from the last REUSE_DAYS days is returned instead (never bought twice)
    2. public   the request is built from PUBLIC documents in the local graph (exchange filings, filed results,
                news text); nothing from the ledger, FDs, tax or targets is ever read into it
    3. gate     the egress gate rejects the request if the question carries anything personal: The investor's name,
                first-person portfolio wording, PAN / e-mail / phone / long account-like digit runs, his FD and
                account ids, or a rupee amount or quantity that matches his ledger (holdings, cash, deposits, FDs);
                documents may only be public kinds taken from the graph
    4. budget   the request is priced before it is sent (token count, worst-case output): refused above the monthly
                cap, a warning past 80%, and a single job above `ask_above_rupees` needs the investor's yes
    5. send     his own questions go live; everything else waits for the overnight batch (half price)
    6. keep     every answer is stored as a dated, cited note (knowledge graph doc + memory row) for the local model
Off until `adopted = true` in PFLAB_PM_DIR/api_budget.toml, which is set only after the pre-registered local-vs-API
comparison (docs/STUDIES.md) shows a clear gain; trial calls for that comparison are
the exception. Prices are Anthropic's list prices (cached 2026-10-06); rupee costs are estimates at `usd_inr`.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from pflab import _toml

MODEL = "claude-opus-5-5"
PRICE_PER_MTOK_USD = {"input": 4.0, "output": 20.0}
# per model (Anthropic's price list, cached 2026-10-06), dollars per million tokens: the Sonnet comparison prices each
PRICES = {"claude-opus-5-5": {"input": 4.0, "output": 20.0}, "claude-sonnet-5-5": {"input": 2.0, "output": 10.0}}
SONNET = "claude-sonnet-5-5"
BATCH_DISCOUNT = 0.5
MAX_TOKENS = 16000
EFFORT = "high"
REUSE_DAYS = 14
DOC_CHARS = 6000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
SYSTEM = ("You are an equity research analyst writing for a private investor in India. You get one question and "
          "PUBLIC documents (stock exchange filings, filed results, news articles). Answer only from those documents "
          "and cite them for every claim. Say plainly what the documents do not settle. Mark your own inference as "
          "inference. Do not recommend buying or selling and do not give price targets. At most 400 words.")


class EgressBlocked(RuntimeError):
    """The request carries something personal: it never leaves the PC."""


CURRENT_TASK: contextvars.ContextVar = contextvars.ContextVar("pflab_current_task", default=None)   # S69: the worker task a paid call is made for
ADMIT = threading.Lock()                                     # S69: checking a limit and reserving the call's estimate are one step across worker threads


class BudgetRefused(RuntimeError):
    pass


class NeedsApproval(RuntimeError):
    pass


class NotAdopted(RuntimeError):
    pass


@dataclass(frozen=True)
class Doc:
    title: str
    text: str
    source: str
    published: str
    kind: str                     # filing | result | article (public kinds only)


@dataclass
class Request:
    question: str
    topic: str                    # company symbol(s) or theme, used for reuse and for the note's links
    docs: List[Doc] = field(default_factory=list)
    isins: List[str] = field(default_factory=list)
    urgent: bool = False          # the investor's own question: live; otherwise the overnight batch


@dataclass
class Outcome:
    status: str                   # reused | queued | done | refused | blocked
    text: str = ""
    call_id: Optional[int] = None
    cost_inr: float = 0.0
    warnings: List[str] = field(default_factory=list)


PUBLIC_KINDS = ("filing", "result", "article", "dataset")   # dataset: market-data exports marked shareable only


# --- configuration -----------------------------------------------------------------------------------------------

def slider(job: str, fallback: str = MODEL) -> str:
    """S61: the model the slider sets for a paid job (`hq/models.py`); the configured model if it cannot be read."""
    try:
        from pflab.hq import models
        return models.model_id(job)
    except Exception:
        return fallback


def config(path: Optional[Path] = None) -> dict:
    from pflab.pm import store
    p = path or store.pm_dir() / "api_budget.toml"
    c = (_toml.load(p).get("api", {}) if p.exists() else {})
    from pflab import release
    # S65: the Rs 2,500 cap belongs to the app; the workshop counts against its own development line (default 0, raised only by him)
    cap = float(c.get("dev_monthly_cap_rupees", 0.0)) if release.channel() == "beta" else float(c.get("monthly_cap_rupees", 0.0))
    whole = _toml.load(p) if p.exists() else {}
    return {"model": c.get("model", MODEL), "cap": cap,
            "ask_above": float(c.get("ask_above_rupees", 0.0)), "usd_inr": float(c.get("usd_inr", 90.0)),
            "adopted": bool(c.get("adopted", False)),
            # S68: the day limits and the bounded acceptance window are configuration, read on every call (live, no restart)
            "policy": whole.get("policy", {}), "acceptance": whole.get("acceptance", {}),
            "paper": whole.get("paper", {}),               # S76: the paper portfolio's own settings (on, monthly_rupees, mission_rupees, start)
            # the investor 2026-10-23: Tijori exports are public company data, not his; they go to the analyst (set false to stop)
            "tijori_to_analyst": bool(c.get("tijori_to_analyst", True)),
            # S75 (his word 2026-11-01: "reset the limit and usage"): usage is counted from this moment if it is later than the first of the month. Nothing is deleted:
            # the calls stay in `api_calls`, they just stop counting against the new month's cap.
            "counted_since": c.get("counted_since")}


# --- the egress gate -------------------------------------------------------------------------------------------------

# S63: the investor's name is not written in the code; it is read from his own api_budget.toml [egress] names
_PERSONAL = re.compile(r"\b(my (portfolio|holdings?|shares|stocks?|fds?|fixed deposits?|account|money|"
                       r"cash|tax|salary|income|gains?|losses?|position)|i (hold|own|bought|sold|have \d)|we (hold|own))\b",
                       re.I)
_IDS = {"PAN": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
        "e-mail": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
        "phone": re.compile(r"(?<![\d.])(?:\+91[\s-]?)?[6-9]\d{9}(?![\d.])"),
        "account-like number": re.compile(r"(?<![\d.])\d{9,18}(?![\d.])")}
_NUM = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?")
# 2026-10-22: dates and years are not amounts (a year sat within 0.5% of small ledger amounts and blocked every
# workshop question); a number followed by a time unit is a window length, not a holding. Money stays checked.
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b")
_MONEY_BEFORE = re.compile(r"(?:rs\.?|inr|\u20b9)\s*$", re.I)
_TIME_AFTER = re.compile(r"\s*-?\s*(?:trading\s+)?(?:sessions?|days?|weeks?|months?|years?|quarters?)\b", re.I)


@dataclass
class Private:
    amounts: Set[float] = field(default_factory=set)       # rupees >= 1,000, matched within 0.5%
    quantities: Set[float] = field(default_factory=set)    # holdings >= 100 units, matched exactly
    ids: Set[str] = field(default_factory=set)             # FD ids, account ids, depository ids (>= 4 characters)
    names: List[str] = field(default_factory=list)         # his name's words, from api_budget.toml [egress] names


def egress_names() -> List[str]:
    from pflab.pm import store
    p = store.pm_dir() / "api_budget.toml"
    d = _toml.load(p) if p.exists() else {}
    return [str(n).lower() for n in d.get("egress", {}).get("names", []) if str(n).strip()]


def private_values(con) -> Private:
    """What must never leave: read from the ledger, FDs and accounts (the gate's blacklist, kept in memory)."""
    from pflab.ledger import events as ev
    from pflab.ledger.book import Ledger
    pv = Private(names=egress_names())
    log = ev.load(con)
    led = Ledger.replay(log)
    for (acc, _isin), q in led.positions().items():
        if abs(q) >= 100:
            pv.quantities.add(round(float(q), 4))
    for e in log.raw():
        for x in (e.amount, e.qty * e.price):
            if x and abs(x) >= 1000:
                pv.amounts.add(round(abs(float(x)), 2))
    for (acc,) in con.execute("SELECT account_id FROM accounts").fetchall():
        bal = led.cash_balance(acc)
        if abs(bal) >= 1000:
            pv.amounts.add(round(abs(float(bal)), 2))
        if len(acc) >= 4:
            pv.ids.add(acc)
    for (dp,) in con.execute("SELECT dp_or_folio FROM accounts WHERE dp_or_folio IS NOT NULL").fetchall():
        if len(str(dp)) >= 4:
            pv.ids.add(str(dp))
    for fid, p, m in con.execute("SELECT fd_id, principal, maturity_amount FROM fds").fetchall():
        if len(str(fid)) >= 4:
            pv.ids.add(str(fid))
        pv.amounts.update(round(float(x), 2) for x in (p, m) if x and x >= 1000)
    return pv


def gate(req: Request, pv: Private, kinds: Sequence[str] = PUBLIC_KINDS) -> Dict[str, int]:
    """Raise EgressBlocked naming what kind of personal data was found (never the value itself).

    Documents are checked by provenance: only public kinds built from the graph (exchange filings, filed results,
    news) may go; their text is public by construction and full of numbers, company phone numbers and e-mails that
    would trip the personal checks by coincidence. The question and topic, which the investor writes, get every check."""
    found = []
    if any(d.kind not in kinds for d in req.docs):
        found.append("a document that is not a public filing, result or article")
    blob = "\n".join([req.question, req.topic])
    if _PERSONAL.search(blob) or any(re.search(r"\b" + re.escape(n) + r"\b", blob, re.I) for n in pv.names):
        found.append("personal wording (name or first-person portfolio words)")
    for name, rx in _IDS.items():
        if rx.search(blob):
            found.append(name)
    if any(i and i in blob for i in pv.ids):
        found.append("an account or deposit id")
    nums = _DATE.sub(" ", blob)
    for m in _NUM.finditer(nums):
        x = float(m.group(0).replace(",", ""))
        money = bool(_MONEY_BEFORE.search(nums[max(0, m.start() - 6):m.start()]))
        if not money and m.group(0).isdigit() and 1900 <= x <= 2100:
            continue                                         # a calendar year
        if not money and _TIME_AFTER.match(nums, m.end()):
            continue                                         # "200-session", "252 trading days": a window length
        if x >= 1000 and any(abs(x - a) <= 0.005 * a for a in pv.amounts):
            found.append("a rupee amount that matches the ledger")
            break
        if x in pv.quantities:
            found.append("a quantity that matches a holding")
            break
    if found:
        raise EgressBlocked("not sent: " + "; ".join(sorted(set(found))))
    return {"documents": len(req.docs), "characters": len(blob) + sum(len(d.text) for d in req.docs)}


# --- public documents from the local graph -----------------------------------------------------------------------

def public_docs(con, isins: Sequence[str], asof: date, days: int = 90, per: int = 12,
                stock_list: Optional[List[dict]] = None) -> List[Doc]:
    out: List[Doc] = []
    since = datetime.combine(asof - timedelta(days=days), datetime.min.time())
    until = datetime.combine(asof, datetime.max.time())
    unit = {"eps": "rupees per share"}                     # every other result figure is in million rupees
    from pflab.kg import build as kb
    from pflab.plan import guards as gd
    names = kb.names_for(con, list(isins), gd.stock_list() if stock_list is None else stock_list)
    for isin in isins:
        nm = con.execute("SELECT name, symbol FROM instruments WHERE isin = ? LIMIT 1", [isin]).fetchone()
        who = f"{nm[0] or nm[1]} ({nm[1]})" if nm and nm[1] else ((nm[0] if nm else None) or isin)
        rows = con.execute("""SELECT d.kind, d.published_at, d.title, d.source, d.url, d.attrs_json, d.text_path
                              FROM kg_edges e JOIN kg_docs d ON d.doc_id = e.src
                              WHERE e.dst = ? AND d.kind IN ('filing','result','article')
                                AND d.published_at > ? AND d.published_at <= ? AND d.dup_of IS NULL
                              ORDER BY d.published_at DESC""", [f"company:{isin}", since, until]).fetchall()
        # an article counts only when its headline names the company (not a passing mention: venue, peer, sector)
        rows = [r for r in rows if r[0] != "article" or kb.is_about(r[2], names.get(isin, []))]
        rows = balanced([r for r in rows if r[0] != "result" or r in _wanted_results(rows)], per)
        for kind, pub, title, source, url, attrs, text_path in rows:
            body = title or ""
            if kind == "result" and attrs:
                # S44 fix: the company is named and EPS is per share (the analyst flagged both in its first notes);
                # 2026-10-18: basis and dating stated (it read the date it was first fetched as the filing date)
                a = json.loads(attrs)
                basis, src = a.pop("basis", None), a.pop("date_source", None)
                qe = a.pop("quarter_end", None)
                when = (f"filed at BSE on {pub:%Y-%m-%d}" if src == "bse_filing" else
                        f"first fetched by this system on {pub:%Y-%m-%d}; BSE's template gives no filing date, "
                        "so this is not when the company filed it")
                body = (f"{who}: {body} ({basis or 'standalone'} results, BSE's own records"
                        + (f"; quarter ended {qe}" if qe else "") + f"; {when})\n" + ", ".join(
                    f"{k.replace('_', ' ')} {v} {unit.get(k, 'million rupees')}" for k, v in a.items() if v is not None))
            if text_path and Path(text_path).exists():
                body += "\n" + Path(text_path).read_text(encoding="utf-8", errors="replace")[:DOC_CHARS]
            out.append(Doc(title or "", body[:DOC_CHARS], url or source or "", f"{pub:%Y-%m-%d}", kind))
        out += dataset_docs(con, isin)
    return out


def same_story(title: str) -> str:
    """A title reduced to its words (copies of one story differ in case, punctuation and the site's id)."""
    return " ".join(w for w in re.findall(r"[a-z]+", (title or "").lower()) if len(w) > 2)[:80]


def balanced(rows: list, per: int) -> list:
    """S59 thorough test: about 2,000 articles in 90 days filled all 12 slots for a large company and no filing reached
    the analyst. Filings come first (up to half the slots), then the wanted results, then articles, one per story;
    newest first within each, the whole newest first."""
    filings = [r for r in rows if r[0] == "filing"][:max(1, per // 2)]
    results = [r for r in rows if r[0] == "result"]
    seen, articles = set(), []
    for r in rows:
        if r[0] == "article" and same_story(r[2]) not in seen:
            seen.add(same_story(r[2]))
            articles.append(r)
    out = filings + results + articles[:max(0, per - len(filings) - len(results))]
    return sorted(out, key=lambda r: r[1], reverse=True)


def _wanted_results(rows: list) -> list:
    """Of the result rows, the newest quarter and the same quarter a year earlier, for each basis (2026-10-18: live
    quarters are dated when first fetched, so two years of old quarters filled the analyst's document slots)."""
    by_basis: Dict[str, Dict[str, tuple]] = {}
    for r in rows:
        if r[0] == "result" and r[5]:
            a = json.loads(r[5])
            m = re.search(r"quarter ended (\d{4}-\d{2}-\d{2})", r[2] or "")
            qe = a.get("quarter_end") or (m.group(1) if m else None)
            if qe:
                by_basis.setdefault(a.get("basis") or "standalone", {})[qe] = r
    out = []
    for qs in by_basis.values():
        newest = max(qs)
        year_ago = f"{int(newest[:4]) - 1}{newest[4:]}"
        out += [qs[q] for q in (newest, year_ago) if q in qs]
    return out


def latest_note(con, isin: str, asof: date, days: int = 30) -> Optional[str]:
    """The newest analyst note on this company within `days`, as a quotable source line for the local model (the
    local agents answer from the analyst's research; the investor 2026-10-17)."""
    r = con.execute("""SELECT d.published_at, d.attrs_json FROM kg_edges e JOIN kg_docs d ON d.doc_id = e.src
                       WHERE e.dst = ? AND d.kind = 'analyst_note' AND d.published_at >= ? AND d.published_at <= ?
                       ORDER BY d.published_at DESC LIMIT 1""",
                    [f"company:{isin}", datetime.combine(asof - timedelta(days=days), datetime.min.time()),
                     datetime.combine(asof, datetime.max.time())]).fetchone()
    if not r:
        return None
    ans = json.loads(r[1] or "{}").get("answer", "")
    return f"{r[0]:%Y-%m-%d} analyst note (API analyst, public documents): {ans[:2500]}" if ans else None


def dataset_docs(con, isin: str, per: int = 4) -> List[Doc]:
    """Market-data exports from the inbox about this company that `inbox.shareable` allowed (Tijori, Screener), as
    tables in text; the investor's own files are never among them."""
    import pandas as pd
    out = []
    for pub, title, source, attrs in con.execute(
            """SELECT d.published_at, d.title, d.source, d.attrs_json FROM kg_edges e JOIN kg_docs d ON d.doc_id = e.src
               WHERE e.dst = ? AND d.kind = 'dataset' ORDER BY d.published_at DESC LIMIT 20""", [f"company:{isin}"]).fetchall():
        a = json.loads(attrs or "{}")
        if a.get("shareable") is not True or len(out) >= per:     # explicitly shareable only (audit 2026-10-30)
            continue
        body = a.get("text") or ""
        if a.get("table") and Path(a["table"]).exists():
            body = pd.read_parquet(a["table"]).iloc[:60, :20].to_csv(index=False)
        out.append(Doc(title or "", f"{title}\n{body}"[:DOC_CHARS], source or "inbox", f"{pub:%Y-%m-%d}", "dataset"))
    return out


# --- reuse, price, budget ----------------------------------------------------------------------------------------

def _words(s: str) -> Set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 3}


def recent_note(con, req: Request, now: datetime, days: int = REUSE_DAYS) -> Optional[tuple]:
    """(call_id, created_at, answer) of a done call on the same topic in the window whose question shares at least
    half its words with this one; else None."""
    q = _words(req.question)
    for cid, at, question, doc in con.execute(
            "SELECT call_id, created_at, question, note_doc FROM api_calls WHERE status='done' AND topic=? AND created_at > ? "
            "ORDER BY created_at DESC", [req.topic, now - timedelta(days=days)]).fetchall():
        w = _words(question)
        if q and w and len(q & w) / len(q | w) >= 0.5:
            a = con.execute("SELECT attrs_json FROM kg_docs WHERE doc_id=?", [doc]).fetchone()
            return cid, at, json.loads(a[0]).get("answer", "") if a else ""
    return None


def _fresh_on_subject(con, now: datetime, *, isins=(), topic: Optional[str] = None, question: Optional[str] = None) -> Optional[tuple]:
    """S84 (T2x, never pay twice): (call_id or None, written_at, text) of a note on the same subject that no event, result or move beyond the watch's thresholds has outdated, else None.
    `think/recall.same_subject_fresh` decides; any failure means "ask" (it never blocks a call)."""
    try:
        from pflab.think import recall
        isins = [i for i in (isins or []) if i]
        f = recall.same_subject_fresh(con, now, isin=isins[0] if len(isins) == 1 else None, topic=None if len(isins) == 1 else topic, question=question)
        return (None, datetime.fromisoformat(f["written_at"]), f["text"]) if f else None
    except Exception:
        return None


def cost(input_tokens: int, output_tokens: int, batch: bool, usd_inr: float, model: str = MODEL) -> tuple:
    pr = PRICES.get(model, PRICE_PER_MTOK_USD)
    usd = (input_tokens * pr["input"] + output_tokens * pr["output"]) / 1e6
    usd *= BATCH_DISCOUNT if batch else 1.0
    return usd, usd * usd_inr


def month_start(now: datetime, cfg: Optional[dict] = None) -> datetime:
    """Where this month's usage is counted from: the first of the month, or the `[api] counted_since` moment if that is later (and not in the future)."""
    first = datetime(now.year, now.month, 1)
    try:
        since = _when((cfg if cfg is not None else config()).get("counted_since"))
    except Exception:
        since = None
    return since if since is not None and first < since <= now else first


def month_spend_inr(con, now: datetime) -> float:
    start = month_start(now)
    return float(con.execute("SELECT coalesce(sum(cost_inr), 0) FROM api_calls WHERE created_at >= ? AND status IN "
                             "('done','refused','submitted','queued')", [start]).fetchone()[0])


def _when(v) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v
    if hasattr(v, "year") and hasattr(v, "month"):                          # a TOML date
        return datetime(v.year, v.month, v.day, 23, 59, 59)
    try:
        return datetime.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def acceptance(cfg: dict, now: datetime) -> Optional[dict]:
    """S68 (his word 2026-10-31): the bounded acceptance window. While `now` is before `until`, the system's day limits and passes-a-day do
    not hold and the window's own cap (`cap_rupees`, spend since `since`) replaces the monthly cap. It ends by itself; the normal policy
    is then exactly as before. Returns {since, until, cap} or None. A window with no cap is no window."""
    a = (cfg or {}).get("acceptance") or {}
    until, since = _when(a.get("until")), _when(a.get("since")) or datetime(now.year, now.month, now.day)
    cap = float(a.get("cap_rupees", 0) or 0)
    if until is None or cap <= 0 or now > until or now < since:
        return None
    return {"since": since, "until": until, "cap": cap}


def window_spend(con, since: datetime) -> float:
    return float(con.execute("SELECT coalesce(sum(cost_inr), 0) FROM api_calls WHERE created_at >= ? AND status IN "
                             "('done','refused','submitted','queued')", [since]).fetchone()[0])


def check_budget(con, est_inr: float, cfg: dict, now: datetime, approved: bool = False) -> List[str]:
    acc = acceptance(cfg, now)
    if acc:                                                  # the window's cap stands in for the month's
        spent = window_spend(con, acc["since"])
        if spent + est_inr > acc["cap"]:
            raise BudgetRefused(f"the acceptance window's cap would be passed: spent ~Rs {spent:,.0f} since {acc['since']:%Y-%m-%d}, "
                                f"this job up to ~Rs {est_inr:,.0f}, window cap Rs {acc['cap']:,.0f} (ends {acc['until']:%Y-%m-%d})")
        if est_inr > cfg["ask_above"] and not approved:
            raise NeedsApproval(f"this job may cost up to ~Rs {est_inr:,.0f} (your limit for one job is Rs {cfg['ask_above']:,.0f})")
        return [f"over 80% of the acceptance window's budget (~Rs {spent + est_inr:,.0f} of Rs {acc['cap']:,.0f})"] \
            if spent + est_inr >= 0.8 * acc["cap"] else []
    if cfg["cap"] <= 0:
        raise BudgetRefused("no monthly cap is set in api_budget.toml: nothing is sent")
    spent = month_spend_inr(con, now)
    if spent + est_inr > cfg["cap"]:
        raise BudgetRefused(f"this month's cap would be passed: spent ~Rs {spent:,.0f}, this job up to ~Rs {est_inr:,.0f}, "
                            f"cap Rs {cfg['cap']:,.0f}")
    if est_inr > cfg["ask_above"] and not approved:
        raise NeedsApproval(f"this job may cost up to ~Rs {est_inr:,.0f} (your limit for one job is Rs {cfg['ask_above']:,.0f})")
    return [f"over 80% of this month's API budget (~Rs {spent + est_inr:,.0f} of Rs {cfg['cap']:,.0f})"] \
        if spent + est_inr >= 0.8 * cfg["cap"] else []


# --- the request ---------------------------------------------------------------------------------------------------

def params(req: Request, model: str = MODEL) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = [
        {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": d.text or d.title},
         "title": f"D{k} {d.published} {d.kind} ({d.source})"[:500], "citations": {"enabled": True}}
        for k, d in enumerate(req.docs, start=1)]
    content.append({"type": "text", "text": req.question})
    return {"model": model, "max_tokens": MAX_TOKENS, "system": SYSTEM, "thinking": {"type": "adaptive"},
            "output_config": {"effort": EFFORT}, "messages": [{"role": "user", "content": content}]}


def answer_text(message) -> str:
    """Text of the answer with [D#] after each cited passage (document numbers as sent)."""
    parts = []
    for b in message.content:
        if getattr(b, "type", "") != "text":
            continue
        cites = sorted({c.document_index + 1 for c in (getattr(b, "citations", None) or [])
                        if getattr(c, "document_index", None) is not None})
        parts.append(b.text + ("".join(f" [D{i}]" for i in cites) if cites else ""))
    return "".join(parts).strip()


_TAGS = re.compile(r"\[(?:D\d+|S\d+|inf)\]", re.I)
_DIG = re.compile(r"\d[\d,]*(?:\.\d+)?")


def only_sourced_numbers(text: str, req: Request) -> tuple:
    """PLAN section 1 (no model-made numbers) for the API's answers: every sentence carrying a number that is not in
    its documents or the question is removed (S44: in the comparison 0-40% of the analyst's numbers per answer were
    its own arithmetic or recall). Returns (text, sentences removed)."""
    known = {n.replace(",", "").rstrip(".") for n in _DIG.findall(
        " ".join(f"{d.published} {d.title} {d.text}" for d in req.docs) + " " + req.question)}
    keep, dropped = [], 0
    for line in text.split("\n"):
        out = []
        for s in re.split(r"(?<=[.!?])\s+", line):
            nums = [n.replace(",", "").rstrip(".") for n in _DIG.findall(_TAGS.sub(" ", s))]
            if any(n not in known for n in nums):
                dropped += 1
            else:
                out.append(s)
        keep.append(" ".join(out))
    clean = re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()
    if dropped:
        clean += (f"\n\n({dropped} sentence(s) removed: they carried numbers not found in the documents; "
                  "figures are only shown when a source states them.)")
    return clean, dropped


def _log(con, req: Request, mode: str, model: str, status: str, now: datetime, p: dict, cost_inr: float = 0.0) -> int:
    from pflab.pm.store import next_id
    cid = next_id(con, "api_calls", "call_id")
    body = json.dumps(p, sort_keys=True)
    try:
        policy = "acceptance" if acceptance(config(), now) else "normal"        # S68: the analyst's own calls are tagged like the HQ's
    except Exception:
        policy = None
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, status, "
                "cost_inr, policy, task_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",          # named: S59 added the `agent` column
                [cid, now, mode, model, req.topic, req.question, hashlib.sha256(body.encode()).hexdigest(), body, status,
                 cost_inr, policy, CURRENT_TASK.get()])
    return cid


def keep(con, cid: int, req: Request, text: str, usage, batch: bool, cfg: dict, now: datetime) -> float:
    """Store the answer as a dated note (graph doc linked to the companies, and a memory row) and its real cost."""
    from pflab.agents import memory as mem
    from pflab.kg import graph as g
    it, ot = int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)
    usd, inr = cost(it, ot, batch, cfg["usd_inr"], cfg["model"])
    doc = g.doc(con, "analyst_note", f"api-call-{cid}", now, req.question[:200], source=f"analyst ({cfg['model']})",
                attrs={"answer": text, "call_id": cid, "documents": [f"D{k} {d.published} {d.kind} {d.source}"
                                                                     for k, d in enumerate(req.docs, start=1)]}, now=now)
    for isin in req.isins:
        g.edge(con, doc, "about", f"company:{isin}", now, "analyst", f"api-call-{cid}", now=now)
    prev = con.execute("SELECT max(mem_id) FROM memory WHERE kind='note' AND subject=? AND valid_to IS NULL AND source LIKE "
                       "'analyst call #%'", [req.topic]).fetchone()[0]       # S57: the newest note replaces the last one
    mem.remember(con, "note", f"Analyst note on {req.topic} ({now:%Y-%m-%d}): {text[:1500]}", subject=req.topic,
                 source=f"analyst call #{cid}", now=now, supersedes=prev)
    con.execute("UPDATE api_calls SET status='done', input_tokens=?, output_tokens=?, cost_usd=?, cost_inr=?, note_doc=?, "
                "finished_at=? WHERE call_id=?", [it, ot, usd, inr, doc, now, cid])
    return inr


def _teach(con, cid: int, p: dict, msg, source: str, now: datetime, inr: float) -> None:
    """S79b item 17: keep this call's redacted input and output in the teacher log (never blocks or fails the call)."""
    try:
        from pflab.llm import teacher
        teacher.record_message(con, cid, p, msg, source, now, agent="analyst", cost_inr=inr)
    except Exception:
        pass


def ring(con, req: Request, client, *, now: Optional[datetime] = None, approved: bool = False, trial: bool = False,
         cfg: Optional[dict] = None, pv: Optional[Private] = None, reuse: bool = True) -> Outcome:
    """The doorbell. `client`: an anthropic.Anthropic (tests pass a fake). Its model: the slider's `research` job (S61)
    unless the caller passes its own `cfg`."""
    now = now or datetime.now()
    cfg = cfg or {**config(), "model": slider("research")}
    if not (cfg["adopted"] or trial):
        raise NotAdopted("the analyst is off until the pre-registered comparison shows a clear gain")
    old = recent_note(con, req, now) if reuse else None
    if not old and reuse:
        old = _fresh_on_subject(con, now, isins=req.isins, topic=req.topic)               # S84 never pay twice: a note on the same name with no event or move since
    if old:
        return Outcome("reused", f"(note of {old[1]:%Y-%m-%d}, reused) {old[2]}", old[0])
    try:
        gate(req, pv if pv is not None else private_values(con))
    except EgressBlocked as e:
        return Outcome("blocked", str(e))
    p = params(req, cfg["model"])
    n_in = client.messages.count_tokens(model=p["model"], system=p["system"], messages=p["messages"],
                                        thinking=p["thinking"]).input_tokens
    _, est = cost(n_in, MAX_TOKENS, not req.urgent, cfg["usd_inr"], p["model"])
    warn = check_budget(con, est, cfg, now, approved)
    if not req.urgent:
        cid = _log(con, req, "batch", p["model"], "queued", now, p, est)
        return Outcome("queued", "queued for tonight's batch (half price)", cid, est, warn)
    cid = _log(con, req, "live", p["model"], "sending", now, p, est)
    msg = client.beta.messages.create(**p, betas=[FALLBACK_BETA], fallbacks="default")
    if getattr(msg, "stop_reason", "") == "refusal":
        con.execute("UPDATE api_calls SET status='refused', finished_at=? WHERE call_id=?", [now, cid])
        return Outcome("refused", "the analyst declined this request", cid, est, warn)
    text, _ = only_sourced_numbers(answer_text(msg), req)
    inr = keep(con, cid, req, text, msg.usage, False, cfg, now)
    _teach(con, cid, p, msg, "analyst", now, inr)
    return Outcome("done", text, cid, inr, warn)


# --- the Sonnet comparison (docs/STUDIES.md) --------------------------------------------------------

def trial_note(con, req: Request, client, model: str, *, now: Optional[datetime] = None, cfg: Optional[dict] = None,
               pv: Optional[Private] = None) -> dict:
    """One live research answer from `model` for the comparison: the same gate, prompt and logging as `ring`, but
    nothing kept in the graph or memory (two notes per question would double the record). Returns the raw answer,
    the answer after `only_sourced_numbers`, and its cost."""
    now = now or datetime.now()
    cfg = {**(cfg or config()), "model": model}
    gate(req, pv if pv is not None else private_values(con))
    p = params(req, model)
    n_in = client.messages.count_tokens(model=p["model"], system=p["system"], messages=p["messages"],
                                        thinking=p["thinking"]).input_tokens
    _, est = cost(n_in, MAX_TOKENS, False, cfg["usd_inr"], model)
    check_budget(con, est, cfg, now, approved=True)
    cid = _log(con, req, "trial", model, "sending", now, p, est)
    msg = client.beta.messages.create(**p, betas=[FALLBACK_BETA], fallbacks="default")
    raw = answer_text(msg)
    kept, _ = only_sourced_numbers(raw, req)
    it, ot = int(getattr(msg.usage, "input_tokens", 0) or 0), int(getattr(msg.usage, "output_tokens", 0) or 0)
    usd, inr = cost(it, ot, False, cfg["usd_inr"], model)
    con.execute("UPDATE api_calls SET status='done', input_tokens=?, output_tokens=?, cost_usd=?, cost_inr=?, finished_at=? "
                "WHERE call_id=?", [it, ot, usd, inr, now, cid])
    _teach(con, cid, p, msg, "analyst_trial", now, inr)
    return {"model": model, "served_by": getattr(msg, "model", model), "stop": getattr(msg, "stop_reason", ""),
            "raw": raw, "kept": kept, "cost_inr": inr, "call_id": cid}


def write_calculation(con, prompt: str, system: str, client, *, now: Optional[datetime] = None,
                      cfg: Optional[dict] = None, pv: Optional[Private] = None, approved: bool = False,
                      gate_text: Optional[str] = None) -> str:
    """S53 workshop: Opus writes a calculation as code. It sees the (third-person) question and the datasets' schema
    with made-up rows, never real rows; the question passes every check of the gate. Priced first, logged. Its model:
    the slider's `workshop` job (S61) unless the caller passes its own `cfg`."""
    now = now or datetime.now()
    cfg = cfg or {**config(), "model": slider("workshop")}
    if not cfg["adopted"]:
        raise NotAdopted("the analyst is off until the pre-registered comparison shows a clear gain")
    req = Request(prompt, "workshop", [])
    # `gate_text`: the parts that can carry the investor's data (his question, feedback from runs on real rows); the schema
    # and the made-up sample rows are written by code and are not his
    gate(Request(gate_text if gate_text is not None else prompt, "workshop", []), pv if pv is not None else private_values(con))
    p = {"model": cfg["model"], "max_tokens": MAX_TOKENS, "system": system, "thinking": {"type": "adaptive"},
         "output_config": {"effort": EFFORT}, "messages": [{"role": "user", "content": prompt}]}
    n_in = client.messages.count_tokens(model=p["model"], system=p["system"], messages=p["messages"],
                                        thinking=p["thinking"]).input_tokens
    _, est = cost(n_in, MAX_TOKENS, False, cfg["usd_inr"], p["model"])
    check_budget(con, est, cfg, now, approved)
    cid = _log(con, req, "live", p["model"], "sending", now, p, est)
    msg = client.beta.messages.create(**p, betas=[FALLBACK_BETA], fallbacks="default")
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    it, ot = int(getattr(msg.usage, "input_tokens", 0) or 0), int(getattr(msg.usage, "output_tokens", 0) or 0)
    usd, inr = cost(it, ot, False, cfg["usd_inr"], p["model"])
    con.execute("UPDATE api_calls SET status='done', input_tokens=?, output_tokens=?, cost_usd=?, cost_inr=?, "
                "finished_at=? WHERE call_id=?", [it, ot, usd, inr, now, cid])
    return text


def make_client(secrets=None):
    """The SDK client: the key from secrets.toml [anthropic] api_key if present, else the SDK's own resolution
    (ANTHROPIC_API_KEY or an `ant auth login` profile). Only this module talks to the API."""
    from pflab import guard
    guard.require("paid")                       # S65: the workshop makes no paid call unless run with --paid
    import anthropic
    headers = {}
    if secrets is not None and secrets.has("anthropic", "workspace_id"):
        # a key not scoped to a workspace must name one on every request (API error seen 2026-10-17)
        headers["anthropic-workspace-id"] = secrets.get("anthropic", "workspace_id")
    if secrets is not None and secrets.has("anthropic", "api_key"):
        return anthropic.Anthropic(api_key=secrets.get("anthropic", "api_key"), default_headers=headers or None)
    return anthropic.Anthropic(default_headers=headers or None)


def deep_request(con, question: str, asof: date, urgent: bool = True) -> Request:
    """A request for a question about list companies: the companies it names, their public documents."""
    from pflab.agents import tools as T
    from pflab.agents.tradecheck import isin_of
    from pflab.plan import guards as gd
    import re as _re
    stocks = gd.stock_list()
    syms = [s["symbol"] for s in stocks if _re.search(r"\b" + _re.escape(s["symbol"]) + r"\b", question, _re.I)]
    for sym, names in T.question_aliases(con, stocks).items():
        if sym not in syms and any(_re.search(r"\b" + _re.escape(n) + r"\b", question, _re.I) for n in names):
            syms.append(sym)
    isins = [i for i in (isin_of(con, s) for s in syms) if i]
    return Request(question, ",".join(syms) or "general", public_docs(con, isins, asof), isins, urgent)


# --- web search (S54b, the investor 2026-10-22: Opus may search the web for public questions, within the cap) ---------------

# S59 (checked 2026-10-24): the dynamic-filtering variant (web_search_20260209) runs the results through code and returns
# text with no citations, so every figure was dropped (a Rs 26 answer came back empty) and it read ~38k input tokens for
# one search; the basic variant cites each passage's page
WEB_TOOL = "web_search_20250305"
WEB_MAX_USES = 5
WEB_USD_PER_SEARCH = 0.01                        # $10 per 1,000 searches, on top of tokens
WEB_SYSTEM = (SYSTEM + " For this question you may search the web. Prefer primary sources (exchange filings, the "
              "company, regulators); mark anything no primary source confirms as unconfirmed. Every figure must come "
              "from a cited page.")


_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATES_WORDS = re.compile(rf"\b{_MONTH}\s+\d{{4}}\b|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}(?:\s+\d{{4}})?\b|"
                          rf"\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:,?\s+\d{{4}}\b)?|\b(?:19|20)\d{{2}}\b", re.I)


def _no_dates(text: str) -> str:
    """A date or a year is not a figure (S59: 'from 1 April 2026' alone removed a passage)."""
    return _DATES_WORDS.sub(" ", _DATE.sub(" ", text))


def web_cited(message) -> tuple:
    """(text with [W#] after each cited passage, sources [(n, title, url)], sentences dropped): a passage with a number
    and no web citation is removed (no model-made numbers)."""
    srcs: Dict[str, int] = {}
    titles: Dict[str, str] = {}
    parts, dropped = [], 0
    for b in message.content:
        if getattr(b, "type", "") != "text":
            continue
        cites = getattr(b, "citations", None) or []
        nums = []
        for c in cites:
            url = getattr(c, "url", None)
            if url:
                srcs.setdefault(url, len(srcs) + 1)
                titles.setdefault(url, getattr(c, "title", "") or url)
                nums.append(srcs[url])
        if not nums and _DIG.search(_no_dates(b.text or "")):
            dropped += 1
            continue
        parts.append((b.text or "") + "".join(f" [W{n}]" for n in sorted(set(nums))))
    text = "".join(parts).strip()
    if dropped:
        text += f"\n\n({dropped} passage(s) removed: they carried numbers without a cited page.)"
    return text, [(n, titles[u], u) for u, n in sorted(srcs.items(), key=lambda x: x[1])], dropped


def web_search(con, question: str, client, *, now: Optional[datetime] = None, cfg: Optional[dict] = None,
               pv: Optional[Private] = None, approved: bool = False, topic: str = "web", max_uses: int = WEB_MAX_USES,
               max_tokens: int = MAX_TOKENS, effort: str = EFFORT) -> Outcome:
    """A public question answered by Opus with web search: gated, priced first (tokens at the worst case plus every
    allowed search), logged, kept as a cited note. Its model: the slider's `web` job (S61) unless `cfg` is passed.
    S62: the brain's tool asks with fewer searches, a smaller output and medium effort (a third of the cost)."""
    now = now or datetime.now()
    cfg = cfg or {**config(), "model": slider("web")}
    if not cfg["adopted"]:
        raise NotAdopted("the analyst is off until the pre-registered comparison shows a clear gain")
    req = Request(question, topic, [], [], True)
    try:
        gate(req, pv if pv is not None else private_values(con))
    except EgressBlocked as e:
        return Outcome("blocked", str(e))
    old = _fresh_on_subject(con, now, question=question)                  # S84 never pay twice: the same question on a name nothing has moved since costs nothing
    if old:
        return Outcome("reused", f"(note of {old[1]:%Y-%m-%d}, reused) {old[2]}", old[0])
    tools = [{"type": WEB_TOOL, "name": "web_search", "max_uses": int(max_uses)}]
    p = {"model": cfg["model"], "max_tokens": int(max_tokens), "system": WEB_SYSTEM, "thinking": {"type": "adaptive"},
         "output_config": {"effort": effort}, "tools": tools, "messages": [{"role": "user", "content": question}]}
    n_in = client.messages.count_tokens(model=p["model"], system=p["system"], messages=p["messages"], tools=tools,
                                        thinking=p["thinking"]).input_tokens
    _, est = cost(n_in, int(max_tokens), False, cfg["usd_inr"], p["model"])
    est += int(max_uses) * WEB_USD_PER_SEARCH * cfg["usd_inr"]
    warn = check_budget(con, est, cfg, now, approved)
    cid = _log(con, req, "web", p["model"], "sending", now, p, est)
    msgs = list(p["messages"])
    msg = None
    for _ in range(3):                                  # a long server-side search loop pauses; resume it
        msg = client.beta.messages.create(**{**p, "messages": msgs}, betas=[FALLBACK_BETA], fallbacks="default")
        if getattr(msg, "stop_reason", "") != "pause_turn":
            break
        msgs = msgs + [{"role": "assistant", "content": msg.content}]
    if getattr(msg, "stop_reason", "") == "refusal":
        con.execute("UPDATE api_calls SET status='refused', finished_at=? WHERE call_id=?", [now, cid])
        return Outcome("refused", "the analyst declined this request", cid, est, warn)
    text, sources, _ = web_cited(msg)
    if sources:
        text += "\n\nSources:\n" + "\n".join(f"[W{n}] {t} - {u}" for n, t, u in sources)
    searches = int(getattr(getattr(msg.usage, "server_tool_use", None), "web_search_requests", 0) or 0)
    inr = keep(con, cid, req, text, msg.usage, False, cfg, now)
    _teach(con, cid, p, msg, "analyst_web", now, inr)
    extra = searches * WEB_USD_PER_SEARCH
    con.execute("UPDATE api_calls SET cost_usd = coalesce(cost_usd, 0) + ?, cost_inr = coalesce(cost_inr, 0) + ? "
                "WHERE call_id=?", [extra, extra * cfg["usd_inr"], cid])
    return Outcome("done", text, cid, inr + extra * cfg["usd_inr"], warn)


def local_answer(con, req: Request, llm=None) -> Optional[str]:
    """Local first: the local model's guarded answer from the request's public documents, with the research harness
    S47 pass 3 adopted (`analyst_compare.local_prompt`, as evaluated). Nothing leaves the PC. None without documents,
    without a chosen model (facts-only, PLAN A6), or when no draft passes the guard in 3 tries."""
    if not req.docs:
        return None
    from pflab.agents import analyst_compare as ac
    from pflab.llm import graphs
    if llm is None:
        from pflab.llm import registry
        m = registry.chosen("general")
        if not m:
            return None
        llm = ac.local_llm(m)
    sources = {f"S{i}": f"{d.published} {d.kind}: {d.title}\n{d.text}" for i, d in enumerate(req.docs, start=1)}
    out = graphs.run(llm, ac.local_prompt(req.question, sources), {}, sources, allow_cited_source_numbers=True)
    return out.text or None


def _with_local(msg: str, con, req: Request, llm, local: bool) -> str:
    """The doorbell did not ring Opus: say why, then give the local answer when one passes the guard."""
    if not local:
        return msg
    try:
        t = local_answer(con, req, llm)
    except Exception as e:                                       # reported, never hidden
        return f"{msg}\n(local answer failed: {type(e).__name__}: {str(e)[:150]})"
    if not t:
        return msg
    return f"{msg}\n\nLocal model, from the same public documents (every number checked against them):\n{t}"


def ask_deep(con, question: str, asof: date, *, approved: bool = False, secrets=None, client=None,
             now: Optional[datetime] = None, llm=None, local: bool = True) -> str:
    """What /deep and `pflab analyst ask` run: a readable result for every outcome. When Opus is not rung (off, over
    budget, waiting for the investor's yes, blocked by the egress gate, declined), the local answer follows the reason."""
    req = deep_request(con, question, asof)
    try:
        o = ring(con, req, client or make_client(secrets), now=now, approved=approved)
    except NotAdopted as e:
        return _with_local(f"Deep research is off: {e}.", con, req, llm, local)
    except NeedsApproval as e:
        return _with_local(f"{e}. Send it again as /deep! ... to go ahead.", con, req, llm, local)
    except BudgetRefused as e:
        return _with_local(f"Not sent: {e}.", con, req, llm, local)
    if o.status in ("blocked", "refused"):
        return _with_local(o.text, con, req, llm, local)
    tail = f"\n\n(cost ~Rs {o.cost_inr:,.1f})" if o.status == "done" else ""
    return "\n".join([o.text + tail] + [f"Note: {w}" for w in o.warnings])


def recent_notes(con, since: datetime) -> List[tuple]:
    """(call_id, topic, finished_at, cost_inr, answer) of notes finished since `since`, oldest first."""
    rows = con.execute("""SELECT c.call_id, c.topic, c.finished_at, c.cost_inr, d.attrs_json FROM api_calls c
                          JOIN kg_docs d ON d.doc_id = c.note_doc
                          WHERE c.status = 'done' AND c.finished_at >= ? ORDER BY c.finished_at""", [since]).fetchall()
    return [(cid, t, f, inr, json.loads(a).get("answer", "")) for cid, t, f, inr, a in rows]


def newest_per_topic(notes: List[tuple]) -> List[tuple]:
    """`recent_notes` rows reduced to the newest note on each company (the morning report shows one per name)."""
    best = {}
    for n in notes:
        if n[1] not in best or (n[2], n[0]) > (best[n[1]][2], best[n[1]][0]):
            best[n[1]] = n
    return sorted(best.values(), key=lambda n: n[1])


def collect_until_done(connect, client, minutes: float, poll_s: float = 300.0, sleep=None,
                       clock=None) -> Dict[str, int]:
    """Poll the batch until nothing is pending or `minutes` pass; the store is opened only while collecting."""
    import time as _t
    sleep, clock = sleep or _t.sleep, clock or _t.monotonic
    end, total = clock() + minutes * 60, {"done": 0, "failed": 0, "pending": 0}
    while True:
        con = connect()
        try:
            got = collect_batches(con, client)
        finally:
            con.close()
        total["done"] += got["done"]
        total["failed"] += got["failed"]
        total["pending"] = got["pending"]
        if not got["pending"] or clock() >= end:
            return total
        sleep(poll_s)


def topic_isins(con, topic: str) -> List[str]:
    from pflab.agents.tradecheck import isin_of
    return [i for i in (isin_of(con, s.strip()) for s in topic.split(",") if s.strip()) if i]


# --- the overnight batch ------------------------------------------------------------------------------------------

def submit_batch(con, client, now: Optional[datetime] = None) -> Optional[str]:
    rows = con.execute("SELECT call_id, request_json FROM api_calls WHERE status='queued' ORDER BY call_id").fetchall()
    if not rows:
        return None
    batch = client.messages.batches.create(requests=[{"custom_id": f"call-{cid}", "params": json.loads(body)}
                                                     for cid, body in rows])
    for cid, _ in rows:
        con.execute("UPDATE api_calls SET status='submitted', batch_id=? WHERE call_id=?", [batch.id, cid])
    return batch.id


def collect_batches(con, client, cfg: Optional[dict] = None, now: Optional[datetime] = None) -> Dict[str, int]:
    cfg = cfg or config()
    now = now or datetime.now()
    out = {"done": 0, "failed": 0, "pending": 0}
    for (bid,) in con.execute("SELECT DISTINCT batch_id FROM api_calls WHERE status='submitted'").fetchall():
        if client.messages.batches.retrieve(bid).processing_status != "ended":
            out["pending"] += 1
            continue
        for r in client.messages.batches.results(bid):
            cid = int(r.custom_id.split("-", 1)[1])
            topic, question, body, model = con.execute("SELECT topic, question, request_json, model FROM api_calls "
                                                       "WHERE call_id=?", [cid]).fetchone()
            docs = [Doc(b.get("title", ""), b["source"]["data"], "", "", "filing")
                    for b in json.loads(body)["messages"][0]["content"] if b.get("type") == "document"]
            req = Request(question, topic, docs, topic_isins(con, topic))
            if r.result.type == "succeeded" and getattr(r.result.message, "stop_reason", "") != "refusal":
                text, _ = only_sourced_numbers(answer_text(r.result.message), req)
                # S59: priced at the call's own model (a Sonnet note at Sonnet's prices, not the configured Opus)
                keep(con, cid, req, text, r.result.message.usage, True, {**cfg, "model": model or cfg["model"]}, now)
                out["done"] += 1
            else:
                con.execute("UPDATE api_calls SET status='failed', error=?, finished_at=? WHERE call_id=?",
                            [r.result.type, now, cid])
                out["failed"] += 1
    return out
