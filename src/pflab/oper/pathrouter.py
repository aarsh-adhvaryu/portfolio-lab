"""S88 L2: which road answers a chat message. Rules only, no model call. Pure: the same words give the same answer.

    ack    a one-word reply ("thanks", "ok"): a fixed short reply, no model call
    full   the full operator (Claude Code session with the whole toolset): an attached file or a link; a study / backtest / compare / stress / simulate / "look into" / "move together" / "build:" / "fix" /
           "add a skill" / "add a tool" request; or `/full` at the start
    light  everything else: one short call with five small tools (`oper/light.py`)
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

ACKS = {"thanks", "thank you", "thanks a lot", "thx", "ty", "ok", "okay", "ok thanks", "okay thanks", "great", "cool", "got it", "noted", "fine", "nice", "good", "perfect", "alright", "k", "👍", "🙏"}
ACK_REPLY = "You're welcome."
FULL_PATTERNS = [r"\blook(?:ing)? into\b", r"\bstudy\b", r"\bstudies\b", r"\bbacktest", r"\bcompare\b", r"\bcomparison\b", r"\bstress\b", r"\bsimulat", r"\bmove(?:s)? together\b", r"\bmoves? with\b",
                 r"\bcorrelat", r"\bcointegrat", r"\blead[- ]lag\b", r"^\s*build:", r"\bfix\b", r"\badd (?:a |an )?(?:new )?skill\b", r"\badd (?:a |an )?(?:new )?tool\b", r"\bmonthly review\b"]
LINK = re.compile(r"https?://|\bwww\.", re.I)
FILE_MARK = "FILES HE SENT WITH THIS MESSAGE"
_FULL = [re.compile(p, re.I) for p in FULL_PATTERNS]


def normalise(q: str) -> str:
    return re.sub(r"[\s!.?,;:]+$", "", re.sub(r"^[\s!.?,;:]+", "", (q or "").strip().lower()))


def choose(q: str, *, has_file: bool = False, road: Optional[str] = None) -> Tuple[str, str, str]:
    """-> (path, reason, text): `text` is the message with a leading `/full` removed."""
    raw = (q or "").strip()
    if road == "full" and not raw.lower().startswith("/full"):
        return "full", "you picked the full road", raw
    if road == "quick" and not (has_file or FILE_MARK in raw or LINK.search(raw)):
        return ("ack", "a one-word reply", raw) if normalise(raw) in ACKS else ("light", "you picked the quick road", raw)
    if raw.lower().startswith("/full"):
        return "full", "you asked for the full operator (/full)", raw[5:].strip() or raw
    if has_file or FILE_MARK in raw:
        return "full", "a file is attached", raw
    if LINK.search(raw):
        return "full", "a link needs checking at its source", raw
    for rx in _FULL:
        if rx.search(raw):
            return "full", f"the words need a study or a change ('{rx.pattern.strip('^').strip(chr(92) + 'b')[:24]}')", raw
    if normalise(raw) in ACKS:
        return "ack", "a one-word reply", raw
    return "light", "a plain question", raw


def skills_for(q: str) -> Optional[list]:
    """The skills the full operator should load for this request (others stay off): [] when none fits."""
    t = (q or "").lower()
    out = []
    if re.search(r"\bcase\b|look(?:ing)? into|how did that", t):
        out.append("case_review")
    if re.search(r"move together|correlat|cointegrat|lead[- ]lag|\bcompare\b", t):
        out.append("pair_study")
    if re.search(r"backtest|\bstudy\b|\brule\b", t):
        out.append("backtest")
    if re.search(r"stress|crash|simulat|what if", t):
        out.append("stress_review")
    if "monthly review" in t:
        out.append("monthly_review")
    if re.search(r"add (?:a |an )?(?:new )?(?:skill|tool)", t):
        out.append("add_skill_or_tool")
    return out
