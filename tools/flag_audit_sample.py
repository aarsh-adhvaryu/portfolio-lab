"""Draw a blind precision sample of red-flag events for Aarsh to label.

    python tools/flag_audit_sample.py

Writes `docs/data/flag_audit.md`: up to 30 events per flag, drawn at random
from 2017-2021 among E1's eligible names, with **company names and dates
masked** and **no returns anywhere in the file**.

WHY MASKED, AND WHY NO RETURNS
------------------------------
The question is whether the headline is the event the flag names -- a
question about the keyword rules, not about the company or the outcome. A
labeller who can see the name can recall what happened to it; one who can
see the return is being asked a different question and will answer it. So
the file carries the headline, the category and the subcategory, and
nothing else.

Nothing in this script computes a return, and nothing reads one. The
regex that caught each row is recorded separately, in the report written
AFTER labelling, so it cannot prime the label either.

The seed is fixed and recorded in the file, so the sample is reproducible
and cannot be redrawn until it looks better.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260925
PER_FLAG = 30
WINDOW = (date(2017, 1, 1), date(2021, 12, 31))


def _mask_company(name: str, salt: str = "flagaudit") -> str:
    """A stable pseudonym, so the same company reads the same across rows
    without ever naming it."""
    if not name:
        return "COMPANY-?"
    h = hashlib.sha256((salt + str(name).strip().lower()).encode()).hexdigest()
    return "COMPANY-" + h[:6].upper()


_DATE_PATTERNS = [
    # Dot-separated dates FIRST, and before the bare-year rule. Getting the
    # order wrong left "26.10.[DATE]" in the first draft: the year matched
    # the bare-year rule and the day and month survived it. A half-masked
    # date is worse than an unmasked one, because it looks deliberate.
    re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b"),
    re.compile(r"\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\b"),
    # and a day.month left stranded beside an already-masked year
    re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\s*(?=\[DATE\])"),
    re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?[ ,-]+"
               r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
               r"[ ,-]*\d{0,4}", re.I),
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
               r"[ ,-]+\d{1,2}(?:st|nd|rd|th)?[ ,-]*\d{0,4}", re.I),
    re.compile(r"\b(?:FY|Q[1-4])\s?\d{2,4}\b", re.I),
    re.compile(r"\b(?:19|20)\d{2}\b"),
]


def mask_text(s: str, company: str = "") -> str:
    """Remove the company name and every date from a headline.

    A headline usually leads with the company, and often carries the date of
    the event; either would let a labeller identify the name and recall the
    outcome.
    """
    t = str(s or "")
    if company:
        for part in sorted(str(company).split(), key=len, reverse=True):
            if len(part) > 3:
                t = re.sub(re.escape(part), "[CO]", t, flags=re.I)
        t = re.sub(re.escape(str(company)), "[CO]", t, flags=re.I)
    for p in _DATE_PATTERNS:
        t = p.sub("[DATE]", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def build(root: Path | None = None, per_flag: int = PER_FLAG,
          seed: int = SEED) -> pd.DataFrame:
    from pflab.data import data_dir, red_flag_events as rfe
    from pflab.backtest import engine, runner
    from pflab.eval import periods as P
    from pflab.data import calendar as cal_mod

    root = root or data_dir()
    ev = rfe.load(root)
    ev = ev.dropna(subset=["isin", "usable_from"]).copy()
    ev["usable_from"] = pd.to_datetime(ev["usable_from"]).dt.date
    ev = ev[(ev["usable_from"] >= WINDOW[0]) & (ev["usable_from"] <= WINDOW[1])]

    # restrict to E1's eligible names, so the audit is about events the
    # strategy could actually have acted on
    cfg = runner.load_config("configs/e2a.toml")
    period, panel, _, _, _, _, memb = runner.prepare(cfg, "e2a_validation")
    full = P.truncate_end(panel, P.Period("audit", WINDOW[0], WINDOW[1], False))
    uni = engine.precompute_universe(full, cfg, memb)
    cal = cal_mod.from_sessions(pd.to_datetime(full["date"]).dt.date.unique())
    eligible = set()
    for m in cal.month_ends(WINDOW[0], WINDOW[1]):
        eligible |= set(engine.eligible_at(
            uni, m,
            min_sessions=int(cfg["universe"]["min_sessions"]),
            top_n=int(cfg["universe"]["top_n_by_turnover"]),
            min_price=float(cfg["universe"]["min_price"])))
    ev = ev[ev["isin"].isin(eligible)]

    rng = np.random.default_rng(seed)
    rows, n_by_flag = [], {}
    for flag in sorted(ev["flag"].unique()):
        sub = ev[ev["flag"] == flag]
        n_by_flag[flag] = int(len(sub))
        take = sub if len(sub) <= per_flag else sub.iloc[
            sorted(rng.choice(len(sub), size=per_flag, replace=False))]
        for r in take.itertuples(index=False):
            rows.append({
                "flag": flag,
                "headline": mask_text(r.headline, r.company),
                "category": r.category or "",
                "subcategory": r.subcategory or "",
                "_company_masked": _mask_company(r.company),
            })
    out = pd.DataFrame(rows)
    out.insert(0, "row", range(1, len(out) + 1))
    out.attrs["population"] = n_by_flag
    return out


def write(df: pd.DataFrame, path: Path) -> Path:
    pop = df.attrs.get("population", {})
    lines = [
        "# Red-flag precision audit — for Aarsh to label",
        "",
        f"Drawn {pd.Timestamp.today():%Y-%m-%d}. Seed **{SEED}**, fixed and",
        "recorded, so the sample is reproducible and cannot be redrawn until it",
        "looks better.",
        "",
        "Up to 30 events per flag, at random from **2017-01-01 .. 2021-12-31**,",
        "restricted to names in E1's eligible universe at some month-end in the",
        "window — so every row is an event the strategy could have acted on.",
        "",
        "**Company names and dates are masked, and there are no returns",
        "anywhere in this file.** The question is whether the headline is the",
        "event the flag names: a question about the keyword rules, not about the",
        "company or the outcome. A labeller who can see the name can recall what",
        "happened to it, and one who can see the return is being asked a",
        "different question. The regex that caught each row is deliberately NOT",
        "shown here either; it goes in the report written after labelling.",
        "",
        "## How to label",
        "",
        "Put one of these in the **label** column:",
        "",
        "- **TRUE** — the headline is the event the flag names.",
        "- **FALSE** — it is not.",
        "- **UNSURE** — the headline does not say enough to tell.",
        "",
        "UNSURE is a real answer, not a failure to decide: a headline that",
        "cannot be judged from its own text is itself a finding about the rule.",
        "",
        "## Population each flag was drawn from",
        "",
        "| flag | events in window | sampled |",
        "|---|---|---|",
    ]
    for flag in sorted(pop):
        n = pop[flag]
        lines.append(f"| {flag} | {n} | {min(n, PER_FLAG)} |")
    lines += ["", "## The sample", "",
              "| row | flag | headline (masked) | category | subcategory | label |",
              "|---|---|---|---|---|---|"]
    for r in df.itertuples(index=False):
        h = str(r.headline).replace("|", "\\|")[:300]
        lines.append(f"| {r.row} | {r.flag} | {h} | {r.category} | "
                     f"{r.subcategory} |  |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/data/flag_audit.md")
    ap.add_argument("--per-flag", type=int, default=PER_FLAG)
    a = ap.parse_args(argv)
    df = build(per_flag=a.per_flag)
    p = write(df, Path(a.out))
    print(f"{len(df)} rows across {df['flag'].nunique()} flags -> {p}")
    print(json.dumps(df.attrs.get("population", {}), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
