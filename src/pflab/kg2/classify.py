"""What kind of event is this, and how serious? From a CLOSED list, by code first and by the LOCAL model only where code has no answer.

The model never writes a number or a link: it picks `kind` and `severity` from the lists below; `validate` (code) rejects anything else; one retry that names
the error (`llm/structured.ask_json`), then the event keeps the rule's answer. Answers are cached append-only in `<data>/kg/classified.jsonl` so a rebuild of
the graph from the raw files gives the same graph (the cache is one of the raw inputs).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

THESIS_BREAK_KINDS = ("results_miss", "guidance_cut", "auditor_resignation", "promoter_pledge_increase", "regulatory_action", "rating_downgrade",
                      "fraud_investigation", "large_order_loss", "leadership_crisis",       # S84 (A68): leadership_crisis, a governance shock
                      "accounting_concern")                                    # S85: a US 8-K item 4.02 (the company says its published numbers cannot be relied on); no earlier kind meant that
OTHER_KINDS = ("results", "board_meeting", "dividend", "corporate_action", "order_win", "rating_upgrade", "management_change", "fund_raise", "news", "routine", "other")
KINDS = THESIS_BREAK_KINDS + OTHER_KINDS
SEVERITIES = ("low", "medium", "high")
MODEL_PICKS = THESIS_BREAK_KINDS + ("none",)            # the model's own closed list: a thesis-break kind, or "none"

# (kind, severity, pattern over the lower-cased headline + subject); first match wins, thesis-break kinds first
# S84 (A68). The top of a company: the chief executive, the chair, a founder, a managing director (_EXEC), and a promoter (_TOP adds him).
_EXEC = r"(ceo|chief executive(?: officer)?|chair(?:man|woman|person)?|founder|co-founder|managing director)"
_TOP = r"(?:" + _EXEC + r"|promoters?)"
_NOW = r"(?:immediate effect|effective immediately|with immediate)"
_PERSON = r"(?:executives?|officers?|ceo|cfo|directors?|chairman|chief executive)"
# a securities class action is a regulatory matter of medium weight: it is checked FIRST so the word "fraud" inside it does not make it a fraud investigation
# (a settlement, a dismissal or a ruling in the company's favour is not new bad news: it falls through to the later rules)
_CLASS_ACTION = (r"(?s)^(?!.*(?:settle\w*|dismiss\w*|in favou?r))"
                 r".*?(?:class[- ]action|securities (?:fraud )?(?:suit|lawsuit|litigation)|shareholders?'? (?:lawsuit|suit)|investors? (?:lawsuit|suit)\b)")
# a governance shock = leadership_crisis (high): an investigation of the top person, the chief executive or chair ousted / removed / on leave / leaving at once, a promoter or
# chief executive arrested, an executive tied to espionage, sanctions or a criminal case. A plain appointment or an ordinary resignation stays `management_change` (low).
_INV = r"(?:investigat\w+|probe\w*|inquiry|inquiries)"
# What is NOT a governance shock, checked first (found on the real filings, 2010-2026): the exchange's disclosure TEMPLATES ("in case of arrest of promoter or KMP", SEBI circulars), a
# company's reply to a RUMOUR, loan / scheme "sanction" papers. A plain resignation that gives a personal reason, keeps the person on the board, or is an independent, non-executive or
# vice chair is `management_change`.
_NOT_A_SHOCK = r"(?!.*(?:frauds?/defaults?|appointment and removal|removal ?/ ?cessation|cardiac arrest|passed away|\bdemise\b|\bformat\b|\brumou?rs?\b|\bsanction letter\b))"
_NOT_A_QUIET_EXIT = r"(?!.*(?:personal|health|family|pursue|pursuing|continue|independent|non[- ]executive|vice[- ]chair|retire|other (?:commitments|opportunities|engagements)))"
_GENERAL = "|".join([
    _INV + r".{0,70}\b" + _TOP + r"\b",
    r"\b" + _TOP + r"\b.{0,70}" + _INV,
    r"\b" + _EXEC + r"\b.{0,60}\b(?:ousted|ouster|removed|removal|fired|sacked|dismissed|placed on (?:administrative |medical )?leave|on (?:administrative )?leave)\b",
    r"\b(?:oust\w*|removing|removal of|removed|firing|sacking)\b.{0,40}\b" + _EXEC + r"\b",
    r"board.{0,40}to oust",
    r"\b" + _TOP + r"\b.{0,70}\b(?:arrest\w*|detained|indicted|taken into custody|judicial custody|remanded|police custody)",
    r"\b(?:arrest\w*|detained|indicted|raids?|custody)\b.{0,90}\b" + _TOP + r"\b",
    r"\b" + _PERSON + r"\b.{0,70}\b(?:espionage|spy\w*|sanctions|ofac|criminal (?:case|charges?|complaint|probe))",
    r"\b(?:espionage|spy\w*)\b.{0,70}\b" + _PERSON + r"\b",
])
_QUIT_AT_ONCE = "|".join([
    r"\b" + _EXEC + r"\b.{0,60}\b(?:resign\w*|steps? down|stepping down|exits?|leaves?|leaving|departs?|quits?)\b.{0,30}" + _NOW,
    r"\b(?:resign\w*|removal|termination)\b.{0,40}\b" + _EXEC + r"\b.{0,40}" + _NOW,
])
_LEADERSHIP = r"(?s)^" + _NOT_A_SHOCK + r"(?:.*?(?:" + _GENERAL + r")|" + _NOT_A_QUIET_EXIT + r".*?(?:" + _QUIT_AT_ONCE + r"))"

RULES: List[Tuple[str, str, "re.Pattern"]] = [(k, s, re.compile(p)) for k, s, p in [
    ("regulatory_action", "medium", _CLASS_ACTION),
    ("auditor_resignation", "high", r"\b(auditor|statutory auditors?)\b.*\bresign|\bresign\w*\b.*\bauditor"),
    ("leadership_crisis", "high", _LEADERSHIP),
    ("fraud_investigation", "high", r"\b(fraud|forensic audit|money laundering|enforcement directorate|\bed\b raid|cbi|search and seizure|income tax (search|raid)|seiz\w+)"),
    ("promoter_pledge_increase", "medium", r"(invocation|invoked).{0,40}pledge|pledge.{0,40}(invok|increase|creat)|creation of pledge"),
    ("rating_downgrade", "high", r"downgrad|rating.{0,30}(lowered|withdrawn|watch with negative|negative outlook)"),
    ("regulatory_action", "high", r"(show cause|adjudicat\w+|penalty|penalt\w+ imposed|sebi order|order (passed )?by (sebi|rbi|nclt|cci)|prohibit\w+|suspension of trading|nclt.*insolvency|cirp)"),
    ("guidance_cut", "medium", r"(lower|cut|revis\w+ down|reduc\w+).{0,30}(guidance|outlook|forecast)"),
    ("large_order_loss", "medium", r"(cancel\w+|terminat\w+).{0,40}(order|contract|agreement)"),
    ("rating_upgrade", "low", r"upgrad\w+.{0,30}rating|rating.{0,30}upgrad"),
    ("order_win", "low", r"\b(bags?|secures?|receives?|wins?|awarded|letter of award|work order|new order)\b.{0,50}\b(order|contract|project)"),
    ("results", "low", r"(financial results|quarterly results|results for the (quarter|year|half)|unaudited.*results|audited.*results)"),
    ("dividend", "low", r"\bdividend\b|record date"),
    ("board_meeting", "low", r"board meeting|meeting of the board"),
    ("management_change", "low", r"(appointment|resignation|cessation|change in).{0,40}(director|ceo|cfo|managing director|key managerial|company secretary|chairman)"),
    ("fund_raise", "low", r"\b(rights issue|preferential|qip|ncd|debenture|fund ?rais\w+|allotment of)"),
    ("corporate_action", "low", r"\b(split|bonus|buyback|buy-back|demerger|merger|amalgamation|scheme of arrangement)\b"),
    ("order_win", "low", r"^new order received"),
    ("management_change", "low", r"change in (senior )?management|^cessation|^appointment of"),
    ("routine", "low", r"(investor presentation|^press release|postal ballot|secretarial compliance|business responsibility|certificate under regulation|"
                      r"format of initial disclosure|annual report|notice of (annual|extra)|book closure|newspaper)"),
    ("routine", "low", r"(trading window|intimation of|newspaper publication|compliance certificate|shareholding pattern|loss of share certificate|investor (grievance|complaint)|analyst|schedule of)"),
]]


def rule_kind(headline: str, category: str = "", subcategory: str = "") -> Tuple[str, str]:
    """(kind, severity) by code. `other`/`low` when no rule fits (those are what the local model may be asked about)."""
    text = f"{headline} {subcategory}".lower()
    for kind, sev, rx in RULES:
        if rx.search(text):
            return kind, sev
    cat = f"{category} {subcategory}".lower()
    if "result" in cat:
        return "results", "low"
    if "board meeting" in cat:
        return "board_meeting", "low"
    if "dividend" in cat:
        return "dividend", "low"
    return "other", "low"


def validate(obj: dict) -> Optional[str]:
    if obj.get("kind") not in MODEL_PICKS:
        return f"kind must be one of {list(MODEL_PICKS)}"
    if obj.get("severity") not in SEVERITIES:
        return f"severity must be one of {list(SEVERITIES)}"
    return None


SCHEMA = {"type": "object", "properties": {"kind": {"type": "string", "enum": list(MODEL_PICKS)}, "severity": {"type": "string", "enum": list(SEVERITIES)}},
          "required": ["kind", "severity"], "additionalProperties": False}
SYSTEM = ("You label stock-exchange filings and news about one listed company. Choose ONE kind from the closed list, or 'none' when the item is not one of them, "
          "and a severity (low, medium, high) for how much it could hurt a long-term holder. Never write numbers. Answer with JSON only. "
          "leadership_crisis (severity high) is a governance shock at the top: a board or regulator investigating the chief executive, chair or founder; a chief executive or chair "
          "ousted, removed, put on leave or leaving with immediate effect; an executive linked to espionage, sanctions or a criminal case; a promoter arrested. "
          "accounting_concern (severity high) is a company saying its published financial statements must be restated or can no longer be relied on. A securities class action is regulatory_action with severity medium. An ordinary appointment or a planned retirement is none.")


def model_classify(headline: str, text: str = "", *, chat: Optional[Callable] = None) -> Optional[dict]:
    """The local model's pick, or None when it could not answer validly (the caller keeps the rule's answer)."""
    from pflab.llm import structured
    body = (headline or "").strip()[:600] + ("\n\n" + text.strip()[:1500] if text else "")
    prompt = f"Kinds: {', '.join(MODEL_PICKS)}.\n\nItem:\n{body}"
    r = structured.ask_json(SYSTEM, prompt, SCHEMA, validate, purpose="kg2_event_class", num_predict=60, num_ctx=2048, chat=chat)
    if not r.ok:
        return None
    return {"kind": r.value["kind"], "severity": r.value["severity"]}


def final_kind(rule: Tuple[str, str], model: Optional[dict]) -> Tuple[str, str, str]:
    """Combine (kind, severity, method): a rule's thesis-break answer stands; for `other` the model's valid pick is used ('none' -> other); code decides."""
    rk, rs = rule
    if rk != "other" or model is None:
        return rk, rs, "rule"
    if model["kind"] == "none":
        return "other", "low", "model"
    return model["kind"], model["severity"], "model"


# ------------------------------------------------------------------ the cache

def cache_path(root: Path) -> Path:
    return Path(root) / "kg" / "classified.jsonl"


def load_cache(root: Path) -> Dict[str, dict]:
    p = cache_path(root)
    out: Dict[str, dict] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("kind") in KINDS and d.get("severity") in SEVERITIES:
                    out[d["event_id"]] = d
    return out


def append_cache(root: Path, rows: Iterable[dict]) -> int:
    p = cache_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            if r.get("kind") in KINDS and r.get("severity") in SEVERITIES:
                f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
                n += 1
    return n
