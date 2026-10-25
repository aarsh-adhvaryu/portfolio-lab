"""The numeric guard and the citation checker (PLAN §1: no LLM-made numbers).

Every number in generated text must equal, to the precision shown, a value in the code-produced FACTS
table, or sit inside a quoted span that appears verbatim in a cited source. Derived numbers (sums, ratios,
differences) are not allowed: compute them in code and put them in the table. Text that fails is
rejected, regenerated with the violations named, and dropped after `retries` failures; it never reaches a
note. The checker also rejects any claim sentence without a citation `[S1]` (a source) or `[F:name]` (a
fact), citations that name nothing, and quotes that are not in their source.

Known limits, stated so nobody leans on more than this gives: spelled-out numbers below twenty ("two",
"seven") are not flagged (they are indistinguishable from pronouns), so prompts forbid them; the guard
cannot tell whether a number is attached to the right fact, only that it equals one; direction words
("rose", "fell") are not checked. Reviewers still read the note.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, Iterable, List, Optional, Tuple, Union

MAGNITUDE = {"thousand": 1e3, "k": 1e3, "lakh": 1e5, "lakhs": 1e5, "million": 1e6, "mn": 1e6, "crore": 1e7,
             "crores": 1e7, "cr": 1e7, "billion": 1e9, "bn": 1e9, "trillion": 1e12}
PERCENT = {"%", "percent", "per cent"}

_CITE = re.compile(r"\[(?:S\d+|F:[A-Za-z0-9_.\-]+)\]")
_SRC = re.compile(r"\[(S\d+)\]")
_FACT = re.compile(r"\[F:([A-Za-z0-9_.\-]+)\]")
_INF = re.compile(r"\[inf\]", re.I)
_DATE = re.compile(r"\b\d{1,2}[-/ ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-/ ,]*\d{2,4}\b"
                   r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4}\b"
                   r"|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", re.I)
_SECTION = re.compile(r"\b\d+[A-Z]{0,2}(?:\(\w+\))+")
_NUM = re.compile(r"(?<![\w.])(?:₹|Rs\.?|INR)?\s?(?P<n>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
                  r"(?:\s?(?P<u>%|per cent|percent|thousand|lakhs?|crores?|million|billion|trillion|mn|bn|cr|k)\b|(?P<p>%))?", re.I)
_SPELLED = re.compile(r"\b(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ]\w+)?|hundred|thousand|lakhs?|"
                      r"crores?|million|billion|trillion|dozen|[a-z]+ (?:percent|per cent))\b", re.I)
_QUOTE = re.compile(r"[\"“]([^\"“”]{3,}?)[\"”]\s*(\[S\d+\])")


@dataclass(frozen=True)
class Violation:
    kind: str            # number_not_in_facts | spelled_number | unverified_quote | uncited | bad_citation | section_not_in_sources
    text: str
    detail: str = ""


@dataclass
class GuardResult:
    ok: bool
    violations: List[Violation] = field(default_factory=list)
    numbers_checked: int = 0
    facts_used: List[str] = field(default_factory=list)


Fact = Union[float, int, date, str, Tuple[float, str]]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'").replace("“", '"').replace("”", '"')).strip().lower()


def fact_numbers(value: Fact) -> List[float]:
    """Numeric values a fact makes available to the text as DISPLAYED (a date contributes year, month and day).
    A fact given as `(value, 'million')` is displayed as `value` and means `value x 1e6` (see `fact_absolutes`)."""
    if isinstance(value, bool):
        return []
    if isinstance(value, tuple):
        return [float(value[0])]
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, date):
        return [float(value.year), float(value.month), float(value.day)]
    return [float(m.replace(",", "")) for m in re.findall(r"\d[\d,]*\.?\d*", str(value))]


def fact_absolutes(value: Fact) -> List[float]:
    """Full-magnitude values: `(5687490.0, 'million')` -> 5.68749e12; everything else as displayed."""
    if isinstance(value, tuple):
        return [float(value[0]) * MAGNITUDE[value[1].lower()]]
    return fact_numbers(value)


def _decimals(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


def _matches(n_text: str, unit: Optional[str], value: Fact) -> bool:
    n = float(n_text.replace(",", ""))
    d = _decimals(n_text)
    u = (unit or "").lower()
    raws, abss = [abs(x) for x in fact_numbers(value)], [abs(x) for x in fact_absolutes(value)]

    def close(a: float, b: float, tol: float) -> bool:
        return abs(a - b) < tol - 1e-12 * max(1.0, abs(b))      # strictly inside half a unit of the last digit shown

    half = 0.5 * 10 ** -d
    if u in PERCENT:
        return any(close(n, v, half) or close(n / 100.0, v, half / 100.0) for v in raws + abss)
    if u in MAGNITUDE:
        return any(close(n * MAGNITUDE[u], v, half * MAGNITUDE[u]) for v in abss)
    if any(close(n, v, half) for v in raws + abss):
        return True
    return any(v <= 1.0 and d >= 1 and close(n / 100.0, v, half / 100.0) for v in raws)   # a fraction shown without the % sign


def _strip_for_numbers(text: str) -> str:
    t = _CITE.sub(" ", text)
    t = re.sub(r"(?m)^\s*(?:#+\s*)?\d+[.)]\s+", " ", t)          # list numbering and numbered headings
    t = re.sub(r"[A-Z]{2}[A-Z0-9]{10}", " ", t)                   # ISINs
    return t


def check_numbers(text: str, facts: Dict[str, Fact], sources: Optional[Dict[str, str]] = None) -> GuardResult:
    """The numeric guard."""
    sources = sources or {}
    violations: List[Violation] = []
    used: List[str] = []
    verified_spans: List[str] = []
    for m in _QUOTE.finditer(text):
        span, tag = m.group(1), m.group(2)[1:-1]
        if tag in sources and _norm(span) in _norm(sources[tag]):
            verified_spans.append(span)
        else:
            violations.append(Violation("unverified_quote", span[:80], f"not found in source {tag}" if tag in sources else f"no source {tag}"))
    body = text
    for span in verified_spans:                                   # numbers inside a verified quote are the source's
        body = body.replace(span, " ")
    for m in _SECTION.finditer(body):                              # legal section numbers such as 70(1)(x)
        tok = m.group(0)
        if not any(tok in s for s in sources.values()) and not any(tok in str(v) for v in facts.values()):
            violations.append(Violation("section_not_in_sources", tok, "section reference not found in any source"))
    body = _SECTION.sub(" ", body)
    body = _DATE.sub(lambda m: " " + m.group(0) + " ", body)
    dated = [d for d in _DATE.findall(body)]
    for d in dated:                                                # a date is checked as a date, against facts and sources
        if not any(_norm(d) in _norm(str(v)) for v in facts.values()) and not any(_norm(d) in _norm(s) for s in sources.values()):
            # the same calendar date written another way is fine; scattered parts matching unrelated numbers are not
            known = {v for v in facts.values() if isinstance(v, date)}
            for s_ in sources.values():
                for x in _DATE.findall(s_):
                    try:
                        known.add(pd_date(x))
                    except ValueError:
                        pass
            try:
                ok = pd_date(d) in known
            except ValueError:
                ok = False
            if not ok:
                violations.append(Violation("number_not_in_facts", d, "date not in the facts table or sources"))
        body = body.replace(d, " ", 1)
    body = _strip_for_numbers(body)
    n_checked = 0
    for m in _NUM.finditer(body):
        n_text, unit = m.group("n"), m.group("u") or m.group("p")
        n_checked += 1
        hit = next((k for k, v in facts.items() if _matches(n_text, unit, v)), None)
        if hit is None:
            violations.append(Violation("number_not_in_facts", m.group(0).strip(), "not equal to any value in the facts table"))
        elif hit not in used:
            used.append(hit)
    rest = _NUM.sub(" ", body)                                      # magnitude words after digits are units, not spelled numbers
    for m in _SPELLED.finditer(rest):
        violations.append(Violation("spelled_number", m.group(0), "write numbers as digits so they can be checked"))
    return GuardResult(not violations, violations, n_checked, used)


def _sentences(text: str) -> List[str]:
    out: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("---"):
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“\[(])", line) if s.strip()]
    return out


def check_citations(text: str, sources: Dict[str, str], facts: Dict[str, Fact]) -> GuardResult:
    """Every claim sentence needs a citation that exists; quotes must be verbatim in their source."""
    violations: List[Violation] = []
    for s in _sentences(text):
        if _INF.search(s) or s.endswith("?") or len(s.split()) < 4:
            continue
        tags = _CITE.findall(s)
        if not tags:
            violations.append(Violation("uncited", s[:120], "claim without a [S#] or [F:name] citation (mark inference with [inf])"))
            continue
        for t in _SRC.findall(s):
            if t not in sources:
                violations.append(Violation("bad_citation", t, "no such source"))
        for f in _FACT.findall(s):
            if f not in facts:
                violations.append(Violation("bad_citation", f"F:{f}", "no such fact"))
    for m in _QUOTE.finditer(text):
        span, tag = m.group(1), m.group(2)[1:-1]
        if tag not in sources or _norm(span) not in _norm(sources[tag]):
            violations.append(Violation("unverified_quote", span[:80], f"not found in source {tag}"))
    return GuardResult(not violations, violations)


def pd_date(s: str) -> date:
    from dateutil import parser
    return parser.parse(s, dayfirst=not re.match(r"\d{4}-", s.strip())).date()


def mask_cited_source_numbers(text: str, sources: Dict[str, str]) -> str:
    """Opt-in (S37/S38): in a sentence that cites [S#], a number that appears digit for digit in one of the cited
    sources is the source's, not the model's; it is masked before the numeric check. Sources are verbatim
    documents (filing headlines, article titles), so the number is still verifiable; it simply was not quoted."""
    out = text
    for s in _sentences(text):
        tags = [t for t in _SRC.findall(s) if t in sources]
        if not tags:
            continue
        digits = [re.sub(r"[^\d.]", "", sources[t]) for t in tags]
        # a decimal point needs a digit after it: "Regulation 30." ends a sentence with 30, not "30." (S43 fix)
        src_nums = {re.sub(r",", "", n) for t in tags for n in re.findall(r"\d[\d,]*(?:\.\d+)?", sources[t])}
        masked = s
        src_dates = set()
        for t in tags:
            for d in _DATE.findall(sources[t]):
                try:
                    src_dates.add(pd_date(d))
                except ValueError:
                    pass
        for d in _DATE.findall(s):                                  # the same date written another way
            try:
                if pd_date(d) in src_dates:
                    masked = masked.replace(d, " ", 1)
            except ValueError:
                pass
        for m in _NUM.finditer(masked):
            n = m.group("n").replace(",", "")
            if n in src_nums:
                masked = masked.replace(m.group(0), " ", 1)
        if masked != s:
            out = out.replace(s, masked, 1)
    return out


def check_all(text: str, facts: Dict[str, Fact], sources: Optional[Dict[str, str]] = None,
              allow_cited_source_numbers: bool = False) -> GuardResult:
    sources = sources or {}
    if allow_cited_source_numbers:
        text = mask_cited_source_numbers(text, sources)
    a, b = check_numbers(text, facts, sources), check_citations(text, sources, facts)
    seen, merged = set(), []
    for v in a.violations + b.violations:
        if (v.kind, v.text) not in seen:
            seen.add((v.kind, v.text))
            merged.append(v)
    return GuardResult(not merged, merged, a.numbers_checked, a.facts_used)


# --- regeneration loop ---------------------------------------------------------------------------------------

@dataclass
class Outcome:
    text: Optional[str]          # None = dropped
    ok: bool
    attempts: int
    history: List[List[Violation]] = field(default_factory=list)
    draft: Optional[str] = None  # the last draft, kept or not (S47 pass 3 shows failed drafts to the harness editor)


def feedback(violations: Iterable[Violation]) -> str:
    lines = [f"- {v.kind}: {v.text!r} ({v.detail})" for v in violations]
    return ("Your draft was rejected by the checker:\n" + "\n".join(lines) +
            "\nRewrite it. Use ONLY numbers that appear in the facts table, written as digits; do not derive new numbers; "
            "cite every claim with [S#] or [F:name]; quote sources verbatim with their [S#].")


def guarded_generate(llm: Callable[[str], str], prompt: str, facts: Dict[str, Fact],
                     sources: Optional[Dict[str, str]] = None, retries: int = 2) -> Outcome:
    """Draft, check, and regenerate with the violations named, up to `retries` times. A draft that never
    passes is dropped (text None): nothing unverified is ever returned."""
    history: List[List[Violation]] = []
    cur = prompt
    for attempt in range(1, retries + 2):
        text = llm(cur)
        res = check_all(text, facts, sources)
        if res.ok:
            return Outcome(text, True, attempt, history)
        history.append(res.violations)
        cur = prompt + "\n\n" + feedback(res.violations)
    return Outcome(None, False, retries + 1, history)
