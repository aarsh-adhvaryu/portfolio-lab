"""US company filings in the graph (S85, `sec`): 8-K items 5.02, 4.01 and 4.02, read from the raw files the collector `ingest/sec_8k.py` writes, classified by CODE.

Why raw files: the graph is rebuilt from raw files every night and the rebuild must give the same tables byte for byte (`kg2/audit.py`, `rebuild_identical`). So an 8-K is first a raw file,
`<data>/sec_8k/<accession>.json` (the filing's own text of the wanted items, its acceptance time, its CIK key), and the graph's events are made from those files here, like the BSE filings.

One event per (filing, item):
    isin         ZZ + the 10-digit SEC CIK (CLAUDE.md rule 3); readers resolve aliases (`kg/events.material_events`)
    source       "SEC EDGAR 8-K item 5.02" (4.01, 4.02)            ref  the accession number, the document key
    ts           the SEC's ACCEPTANCE time (UTC in the index) as IST wall time, the system's clock; `ts_rule` = release_time. A filing with a date and no acceptance time is used from the
                 next US trading day's open (A58), `ts_rule` = next_open_no_release_time, its date on the row
    kind/severity by the rules below (no model: the item number and keywords)

Rules (`classify_item`), written from the 8-K item definitions and the language filings use:
  4.02  non-reliance on previously issued financial statements: `accounting_concern`, high (always: the company itself says its numbers cannot be relied on)
  4.01  change of the auditor: the auditor RESIGNED -> `auditor_resignation` high; declined to stand for re-election -> medium; DISMISSED over a stated disagreement or a reportable event ->
        high; an ordinary dismissal (the company chose another firm) -> `routine`, low. The standard sentence "there were no disagreements" is not a disagreement (negation is read).
  5.02  officers and directors: the chief executive, chief financial officer, chair or a founder TERMINATED, removed, dismissed, on leave, under investigation, resigning "effective
        immediately" without a personal / health / retirement reason, or resigning over a stated disagreement -> `leadership_crisis` high. Other departures of those roles ->
        `management_change` medium; ordinary appointments and compensation -> `management_change` low (`routine` when nothing but a plan or a payment is described).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from pflab.kg2 import filing_time as ft

ITEMS = ("5.02", "4.01", "4.02")
SOURCE_PREFIX = "SEC EDGAR 8-K item "
RAW_DIR = "sec_8k"
IST_OFFSET = timedelta(hours=5, minutes=30)
FILING_MARKET = "US"
_WS = re.compile(r"\s+")


def is_sec_source(source) -> bool:
    return str(source or "").startswith(SOURCE_PREFIX)


def _norm(text: str) -> str:
    return _WS.sub(" ", str(text or "").lower()).strip()


# ------------------------------------------------------------------ the rules

_TOP = (r"(?:chief executive officer|chief executive|\bceo\b|principal executive officer|chief financial officer|\bcfo\b|principal financial officer|"
        r"(?<!vice )(?<!vice-)(?<!lead )(?<!committee )\bchair(?:man|woman|person)?\b(?!\s+of\s+(?:the\s+)?(?:\w+\s+){0,3}committee)|\bfounder\b|\bco-founder\b)")
_STRONG = (r"(?:terminat\w+\b(?!\W+(?:\w+\W+){0,4}(?:agreement|plan|arrangement|letter|award|policy|program|lease|contract|offer)s?\b)|remov\w+|dismiss\w+|ousted|ouster|fired|"
           r"for cause|without cause|leave of absence|administrative leave|placed on (?:paid )?leave|suspended|relieved of)")
_INVEST = r"(?:investigat\w+|inquir(?:y|ies)|\bprobe\b|subpoena\w*|wells notice|indict\w*|arrest\w*|criminal (?:charges?|complaint|investigation)|misconduct)"
_QUIT = r"(?:resign\w*|step(?:s|ped|ping)? down|depart\w*|\bleav(?:e|es|ing)\b|ceas\w+ to (?:serve|be|hold)|\bexit\w*|separat\w+)"
_NOW = r"(?:effective immediately|with immediate effect|immediate effect|effective as of (?:the )?(?:close of business )?today)"
_GUARD = (r"(?:personal|health|medical|family|retire\w*|pursue|pursuing|other (?:business )?(?:opportunit\w+|commitments|interests|endeavou?rs|professional)|succession|"
          r"transition(?:ing)? (?:plan|period)|planned|passed away|\bdeath\b|deceased|will remain|continue to serve|remains? (?:as )?(?:a |an |the )?(?:director|advisor|consultant|employee|chair))")
_W = 200            # characters within which a role and what happened to it belong together

_RX = {
    "strong": re.compile(r"(?:\b" + _TOP + r".{0," + str(_W) + r"}\b" + _STRONG + r"\b|\b" + _STRONG + r"\b.{0," + str(_W) + r"}" + _TOP + r")"),
    "invest": re.compile(r"(?:" + _TOP + r".{0," + str(_W) + r"}\b" + _INVEST + r"|\b" + _INVEST + r".{0," + str(_W) + r"}" + _TOP + r")"),
    "quit_now": re.compile(r"(?:" + _TOP + r".{0," + str(_W) + r"}\b" + _QUIT + r".{0,80}" + _NOW + r"|" + _NOW + r".{0,80}\b" + _QUIT + r".{0," + str(_W) + r"}" + _TOP +
                           r"|" + _NOW + r".{0,120}" + _TOP + r".{0,80}\b" + _QUIT + r"|\b" + _QUIT + r".{0,120}" + _TOP + r".{0,80}" + _NOW + r")"),
    "quit": re.compile(r"(?:" + _TOP + r".{0," + str(_W) + r"}\b" + _QUIT + r"|\b" + _QUIT + r".{0," + str(_W) + r"}" + _TOP + r")"),
    "retire": re.compile(r"(?:" + _TOP + r".{0," + str(_W) + r"}\bretire\w*|\bretire\w*.{0," + str(_W) + r"}" + _TOP + r")"),
    "guard": re.compile(_GUARD),
    "officer": re.compile(r"\b(?:appoint\w*|elect\w*|named|resign\w*|retire\w*|step(?:s|ped|ping)? down|depart\w*|terminat\w+|remov\w+|ceas\w+|succeed\w*|promot\w+|designat\w+)\b"),
}
_NEG = re.compile(r"\b(?:no|not|never|without|neither|nor|none)\b")
_DISAGREE_POS = re.compile(r"(?:disagreed with|\b(?:had|there (?:was|were)|was|were|reflecting|following|expressed)\s+(?:a|an|one|certain|some|several|the following|material)\s+(?:\w+\s+)?disagreements?)")
_REPORTABLE = re.compile(r"(?:reportable events?|material weakness\w*)")
_ABBR = "".join(rf"(?<!\b{a}\.)" for a in ("mr", "ms", "mrs", "dr", "inc", "corp", "ltd", "jr", "sr", "co", "no", "st", "u.s", "[a-z]"))       # "Mr. Poe", "John A. Smith", "Inc." end no sentence
_SENT = re.compile(r"(?<=\.)" + _ABBR + r"\s+")                                    # only a full stop ends a sentence: a negation before a semicolon still governs the clause after it
_COND = re.compile(r"\b(?:if|in the event|whether|would|should|eligible|participants?|plan|policy|upon|entitled|change in control|good reason)\b")           # a plan or a policy says what happens IF someone is terminated: not an event


def _sentences(t: str) -> List[str]:
    return [s for s in _SENT.split(t) if s]


def _disagreement(t: str) -> bool:
    """A STATED disagreement or reportable event, not the standard "there were no disagreements" sentence (read sentence by sentence: a negation makes a sentence not positive, except an
    explicit "had a disagreement")."""
    for s in _sentences(t):
        if "consulted" in s:                                            # the standard line about the NEW auditor ("has not consulted ... any matter that was the subject of a disagreement")
            continue
        if _DISAGREE_POS.search(s) and not re.search(r"\b(?:no|not|never|without)\b\W+(?:\w+\W+){0,2}disagreements?", s):
            return True
        if _REPORTABLE.search(s) and not _NEG.search(s):
            return True
    return False


def _item_402(t: str) -> Tuple[str, str, str]:
    return "accounting_concern", "high", "4.02: the company says previously issued financial statements should no longer be relied on"


def _item_401(t: str) -> Tuple[str, str, str]:
    resigned = bool(re.search(r"\bresign\w*", t))
    declined = bool(re.search(r"declin\w+ to (?:stand|stood|seek)|(?:will|would|does|do|did) not (?:stand|seek) (?:for )?re-?(?:election|appointment)|not (?:to )?(?:stand|seek) re-?(?:election|appointment)", t))
    dismissed = bool(re.search(r"\b(?:dismiss\w*|discharg\w+|terminat\w+)", t))                 # item 4.01 is about the auditor only, so any dismissal word is about it
    bad = _disagreement(t)
    if resigned:
        return "auditor_resignation", "high", "4.01: the auditor resigned" + ("; a disagreement or reportable event is stated" if bad else "")
    if dismissed and bad:
        return "auditor_resignation", "high", "4.01: the auditor was dismissed and a disagreement or reportable event is stated"
    if declined:
        return "auditor_resignation", "medium", "4.01: the auditor declined to stand for re-election"
    return "routine", "low", "4.01: an ordinary change of auditor (no resignation, no stated disagreement)"


_REASON_NEXT = re.compile(r"^(?:his|her|their|the|this)\s+(?:resignation|departure|decision|retirement|separation)\b")


def _where_told(t: str, m: "re.Match") -> str:
    """The sentence(s) around a match, and the next sentence when it speaks of the same departure ("His resignation was due to ...")."""
    start = max(t.rfind(". ", 0, m.start()), t.rfind("; ", 0, m.start()), -2) + 2
    nxt = t.find(". ", m.end())
    end = len(t) if nxt < 0 else nxt + 1
    rest = t[end:].lstrip()
    if rest and _REASON_NEXT.match(rest):
        nn = rest.find(". ")
        end += 1 + (len(rest) if nn < 0 else nn + 1)
    return t[start:end]


def _item_502(t: str) -> Tuple[str, str, str]:
    sents = _sentences(t)
    if any(_RX["strong"].search(s) and not _COND.search(s) for s in sents):          # the role and what happened to it in ONE sentence ("CEO onboarding ... his termination date" is another person's)
        return "leadership_crisis", "high", "5.02: a chief executive, chief financial officer, chair or founder terminated, removed, dismissed or on leave"
    if any(_RX["invest"].search(s) for s in sents):
        return "leadership_crisis", "high", "5.02: a chief executive, chief financial officer, chair or founder is named with an investigation"
    if _RX["quit"].search(t) and _disagreement(t):
        return "leadership_crisis", "high", "5.02: a chief executive, chief financial officer, chair or founder leaves over a stated disagreement"
    m = _RX["quit_now"].search(t)
    if m and not _RX["guard"].search(_where_told(t, m)):                                 # a reason is read where the departure is told, not in a later biography ("a private family office")
        return "leadership_crisis", "high", "5.02: a chief executive, chief financial officer, chair or founder leaves with immediate effect and no personal, health or retirement reason is given"
    if _RX["quit"].search(t) or _RX["retire"].search(t):
        return "management_change", "medium", "5.02: a chief executive, chief financial officer or chair leaves in an ordinary way (a reason, a date or a successor is given)"
    if _RX["officer"].search(t):
        return "management_change", "low", "5.02: an appointment, election or an ordinary departure of an officer or director"
    return "routine", "low", "5.02: compensation or a plan, no change of officer"


def classify_item(item: str, text: str) -> Tuple[str, str, str]:
    """(kind, severity, why) for one 8-K item's text. Code only; kinds are on the closed list (`classify.KINDS`)."""
    t = _norm(text)
    if item == "4.02":
        return _item_402(t)
    if item == "4.01":
        return _item_401(t)
    if item == "5.02":
        return _item_502(t)
    return "other", "low", f"item {item} is not read"


_TITLE = re.compile(r"^(?:departure of directors|changes? (?:in|to) registrant|non-reliance on previously)", re.I)
_HEAD = re.compile(r"^\s*item\s+\d\.\d\d\.?[\s—–:.-]*", re.I)


def headline(item: str, text: str, limit: int = 200) -> str:
    """"8-K item 5.02: <the first words of the item's own text, the heading line removed>"."""
    body = str(text or "")
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    title = ""
    if lines and _HEAD.match(lines[0]):
        title = _HEAD.sub("", lines[0]).strip()
        lines = lines[1:]                                               # the heading line is the item's printed title ("Departure of Directors or Certain Officers; ..."), not what happened
    while lines and _TITLE.match(lines[0]):                             # the title may sit on the next line (a table cell of its own)
        title = title or lines[0]
        lines = lines[1:]
    snippet = _WS.sub(" ", " ".join(lines)).strip() or title
    return f"8-K item {item}: {snippet[:limit]}".rstrip()


# ------------------------------------------------------------------ the raw files and the events

def raw_dir(root) -> Path:
    return Path(root) / RAW_DIR


def raw_files(root) -> List[Path]:
    d = raw_dir(root)
    return sorted(d.glob("*.json")) if d.exists() else []


def _eid(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def _norm_head(h: str) -> str:
    return _WS.sub(" ", re.sub(r"[^a-z0-9 ]", " ", str(h or "").lower())).strip()


def filing_ts(accepted_utc: Optional[str], filed: Optional[str]) -> Tuple[Optional[datetime], Optional[str], Optional[date]]:
    """(ts in IST wall time, rule, own date). The acceptance time (UTC) + 5:30 is the moment the filing was public; with no acceptance time the filing's own date is all there is and it is used
    from the next US trading day's open (A58). Nothing usable: (None, None, None)."""
    t = pd.to_datetime(accepted_utc, errors="coerce") if accepted_utc else pd.NaT
    if not pd.isna(t):
        ts = t.to_pydatetime().replace(tzinfo=None) + IST_OFFSET
        return ts, ft.RULE_RELEASE, ts.date()
    d = pd.to_datetime(filed, errors="coerce") if filed else pd.NaT
    if pd.isna(d):
        return None, None, None
    return ft.next_open(d.date(), FILING_MARKET), ft.RULE_DERIVED, d.date()


def known_by(asof: date) -> datetime:
    """The graph's as-of moment for a US filing: the next Indian open after `asof` (09:15 IST). The graph is built for the Indian close of `asof`, but a US filing accepted that evening (New York
    time) lands in the small hours of the next Indian day: it is a row of the graph from then on, and readers hold it back until its own time `ts` (`kg.events.material_events(until=...)`), the
    same way they hold back a BSE filing with a derived time. A filing accepted after this moment waits for the next day's build."""
    return ft.next_open(asof, "IN")


def events(root, asof: date) -> Tuple[List[dict], List[dict], dict]:
    """(events, nodes, stats) from the raw files whose own date is on or before `asof` (point in time: a filing accepted after `known_by(asof)` is not read). Deterministic: sorted, no clock."""
    cutoff = known_by(asof)
    ev: List[dict] = []
    first_seen: Dict[str, dict] = {}
    stats = {"sec_8k_files": 0, "sec_8k_events": 0, "sec_8k_derived_time": 0, "sec_8k_after_asof": 0, "sec_8k_unreadable": 0}
    for p in raw_files(root):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stats["sec_8k_unreadable"] += 1
            continue
        stats["sec_8k_files"] += 1
        isin, acc = r.get("isin"), r.get("accession")
        ts, rule, day = filing_ts(r.get("accepted_utc"), r.get("filed"))
        if not isin or not acc or ts is None:
            stats["sec_8k_unreadable"] += 1
            continue
        if ts > cutoff:
            stats["sec_8k_after_asof"] += 1
            continue
        for item in sorted(r.get("sections") or {}):
            if item not in ITEMS:
                continue
            text = r["sections"][item]
            kind, sev, why = classify_item(item, text)
            head = headline(item, text)
            derived = rule == ft.RULE_DERIVED
            ev.append({"event_id": _eid("sec_8k", acc, item), "isin": isin, "source": SOURCE_PREFIX + item, "ref": acc, "ts": ts, "event_date": day, "kind": kind, "severity": sev,
                       "headline": head[:500], "link_rule": "sec:cik_pseudo_isin" + ("_no_acceptance_time" if derived else ""),
                       "link_proof": f"CIK {str(r.get('cik', '')).zfill(10)} -> {isin} (ZZ + 10-digit CIK); accession {acc}; {why}" + (f"; no acceptance time: used from {ts:%Y-%m-%d %H:%M} (next US trading open)" if derived else ""),
                       "dedupe_key": f"{isin}|{_norm_head(head)}|{ts.isoformat()}", "ts_rule": rule})
            stats["sec_8k_derived_time"] += int(derived)
        if isin not in first_seen or str(r.get("filed")) < str(first_seen[isin].get("filed")):
            first_seen[isin] = r
    nodes = []
    for isin, r in sorted(first_seen.items()):
        filed = pd.to_datetime(r.get("filed"), errors="coerce")
        nodes.append({"isin": isin, "name": r.get("company") or "", "symbol": r.get("symbol") or "", "origin": "us_filing", "source": "sec_edgar:submissions",
                      "as_of": filed.date() if not pd.isna(filed) else asof})
    stats["sec_8k_events"] = len(ev)
    return ev, nodes, stats
