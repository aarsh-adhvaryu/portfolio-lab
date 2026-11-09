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
                      "fraud_investigation", "large_order_loss")
OTHER_KINDS = ("results", "board_meeting", "dividend", "corporate_action", "order_win", "rating_upgrade", "management_change", "fund_raise", "news", "routine", "other")
KINDS = THESIS_BREAK_KINDS + OTHER_KINDS
SEVERITIES = ("low", "medium", "high")
MODEL_PICKS = THESIS_BREAK_KINDS + ("none",)            # the model's own closed list: a thesis-break kind, or "none"

# (kind, severity, pattern over the lower-cased headline + subject); first match wins, thesis-break kinds first
RULES: List[Tuple[str, str, "re.Pattern"]] = [(k, s, re.compile(p)) for k, s, p in [
    ("auditor_resignation", "high", r"\b(auditor|statutory auditors?)\b.*\bresign|\bresign\w*\b.*\bauditor"),
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
          "and a severity (low, medium, high) for how much it could hurt a long-term holder. Never write numbers. Answer with JSON only.")


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
