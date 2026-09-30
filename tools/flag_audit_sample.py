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


def eligible_isins() -> set:
    """E1's eligible names at any month-end in WINDOW (the audit's universe)."""
    from pflab.backtest import engine, runner
    from pflab.eval import periods as P
    from pflab.data import calendar as cal_mod

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
    return eligible


def build(root: Path | None = None, per_flag: int = PER_FLAG,
          seed: int = SEED, eligible: set | None = None) -> pd.DataFrame:
    """The audit sample. `_scrip_code` and `_key_dt` identify each row's
    announcement (for fetching its attachment); `write` never prints them."""
    from pflab.data import data_dir, red_flag_events as rfe

    root = root or data_dir()
    ev = rfe.load(root)
    ev = ev.dropna(subset=["isin", "usable_from"]).copy()
    ev["usable_from"] = pd.to_datetime(ev["usable_from"]).dt.date
    ev = ev[(ev["usable_from"] >= WINDOW[0]) & (ev["usable_from"] <= WINDOW[1])]

    # restrict to E1's eligible names, so the audit is about events the
    # strategy could actually have acted on
    eligible = eligible_isins() if eligible is None else eligible
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
                "_scrip_code": str(r.scrip_code),
                "_key_dt": r.key_dt,
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


_SHORT_OK = {"Ltd", "LTD", "Co", "CO", "The", "THE", "and", "AND", "of", "OF", "&"}


def mask_strict(s: str, company: str = "", symbols: tuple = ()) -> str:
    """mask_text plus what it lets through (found 2026-09-30 on the recall
    draw): the company's 2-3 letter tokens ("KNR"), its NSE symbols, ISINs,
    web links (which carry the scrip code) and 6-digit codes. Not used for
    flag_audit.md, whose masking stays as drawn."""
    t = str(s or "")
    t = re.sub(r"<a\s[^>]*>|</a>", " ", t, flags=re.I)
    t = re.sub(r"(?:https?://|www\.)\S+", "[WEB]", t, flags=re.I)
    t = re.sub(r"\bIN[A-Z0-9]\d{3}[A-Z0-9]{5}\d\b", "[ISIN]", t)
    t = re.sub(r"\b\d{6}\b", "[CODE]", t)
    for sym in sorted({x for x in symbols if x}, key=len, reverse=True):
        t = re.sub(r"\b" + re.escape(sym) + r"\b", "[CO]", t, flags=re.I)
    for part in str(company or "").replace(".", " ").split():
        if 2 <= len(part) <= 3 and part not in _SHORT_OK and part.isalpha():
            t = re.sub(r"\b" + re.escape(part) + r"[A-Z]*\b", "[CO]", t)
    # SAST disclosures end with the acquirers, usually the promoter group,
    # which names the company as surely as its own name does
    t = re.sub(r"(Takeovers\)?\s*Regulations,?\s*(?:\S+\s*)?for)\s.+$",
               r"\1 [ACQUIRER]", t, flags=re.I)
    return mask_text(t, company)


RECALL_SEED = 20260930
RECALL_N = 250


def build_recall(eligible: set, n: int = RECALL_N, seed: int = RECALL_SEED,
                 root: Path | None = None) -> pd.DataFrame:
    """A1 plan §5.4 (2026-09-30): announcements in WINDOW, on the audit's
    names, that NO keyword rule flags -- the only place a missed event can
    show up. Keyed as red_flag_events keys them (DissemDT, else NEWS_DT),
    de-duplicated, sorted, then drawn with a fixed seed."""
    from pflab.data import data_dir, red_flags
    from pflab.data.red_flag_events import _resolve_isin
    from pflab.data import bse_scrip_isin

    root = root or data_dir()
    m = bse_scrip_isin.load(root)
    m = m[m["isin"] != ""]
    by_scrip: dict = {}
    for r in m.itertuples(index=False):
        by_scrip.setdefault(str(r.scrip_code), []).append(
            (r.isin, pd.Timestamp(r.valid_from), pd.Timestamp(r.valid_to)))
    parts = []
    for y in range(WINDOW[0].year, WINDOW[1].year + 1):
        for f in sorted((root / "bse_announcements" / str(y)).glob("*.parquet")):
            d = pd.read_parquet(f, columns=["scrip_code", "company", "headline",
                                            "category", "subcategory",
                                            "news_dt", "dissem_dt", "attachment"])
            if len(d):
                parts.append(d)
    a = pd.concat(parts, ignore_index=True)
    a["scrip_code"] = a["scrip_code"].astype(str).str.strip()
    a["key_dt"] = pd.to_datetime(a["dissem_dt"], errors="coerce").fillna(
        pd.to_datetime(a["news_dt"], errors="coerce"))
    a = a.dropna(subset=["key_dt"])
    a = a[(a["key_dt"].dt.date >= WINDOW[0]) & (a["key_dt"].dt.date <= WINDOW[1])]
    a = a.drop_duplicates(["scrip_code", "key_dt", "headline"])
    a["isin"] = [_resolve_isin(s, k, by_scrip)
                 for s, k in zip(a["scrip_code"], a["key_dt"])]
    a = a[a["isin"].isin(eligible)]
    flagged = [bool(red_flags.classify(str(h or ""), str(c or ""), str(s or "")))
               for h, c, s in zip(a["headline"], a["category"], a["subcategory"])]
    a = a[~pd.Series(flagged, index=a.index)]
    a = a.sort_values(["key_dt", "scrip_code", "headline"]).reset_index(drop=True)
    rng = np.random.default_rng(seed)
    take = a.iloc[sorted(rng.choice(len(a), size=n, replace=False))]
    import pyarrow.dataset as ds
    sym = ds.dataset(root / "panel" / "prices.parquet").to_table(
        columns=["isin", "symbol"],
        filter=ds.field("isin").isin(sorted(set(take["isin"])))).to_pandas()
    syms = sym.dropna().drop_duplicates().groupby("isin")["symbol"].apply(tuple).to_dict()
    out = pd.DataFrame({
        "row": [f"R{i}" for i in range(1, n + 1)],
        "headline": [mask_strict(h, c, syms.get(i, ()))
                     for h, c, i in zip(take["headline"], take["company"], take["isin"])],
        "category": take["category"].fillna("").values,
        "subcategory": take["subcategory"].fillna("").values,
        "_scrip_code": take["scrip_code"].values,
        "_key_dt": take["key_dt"].values,
        "_attachment": take["attachment"].fillna("").values,
        "_company": take["company"].values,
    })
    out.attrs["population"] = int(len(a))
    return out


def write_recall(df: pd.DataFrame, path: Path, universe_note: str) -> Path:
    lines = [
        "# Red-flag recall sample — unflagged announcements",
        "",
        f"Drawn {pd.Timestamp.today():%Y-%m-%d} by `tools/flag_audit_sample.py --recall`.",
        f"Seed **{RECALL_SEED}**, fixed and recorded. {len(df)} of "
        f"{df.attrs.get('population', '?'):,} announcements dated",
        "2017-01-01 .. 2021-12-31 on the audit's names that **no keyword rule",
        f"flags**. {universe_note}",
        "",
        "A1 plan §5.4: K cannot see an event it missed, so this sample is the",
        "only place recall shows. Masked as `flag_audit.md` is; **no returns and",
        "no company names** (`mask_strict`: `mask_text` plus symbols, short name",
        "tokens, ISINs, links and codes). Readers mark each row with the flag whose event it",
        "is (or NONE) and a subtype from `flag_audit_labels.md`.",
        "",
        "| row | headline (masked) | category | subcategory | flag or NONE | subtype |",
        "|---|---|---|---|---|---|",
    ]
    for r in df.itertuples(index=False):
        h = str(r.headline).replace("|", "\\|")[:300]
        lines.append(f"| {r.row} | {h} | {r.category} | {r.subcategory} |  |  |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--per-flag", type=int, default=PER_FLAG)
    ap.add_argument("--recall", action="store_true",
                    help="draw the unflagged recall sample instead")
    a = ap.parse_args(argv)
    if a.recall:
        # The audit's universe is E1's eligible set as drawn at 041ec33; the
        # 2026-09-27 repairs widened it, so it is read from the saved list.
        from pflab.data import data_dir
        import hashlib as _h
        src = data_dir() / "flag_audit" / "eligible_041ec33.json"
        isins = sorted(json.loads(src.read_text(encoding="utf-8")))
        digest = _h.sha256("\n".join(isins).encode()).hexdigest()
        df = build_recall(set(isins))
        note = (f"Universe: the audit's {len(isins)} names (E1's eligible set as "
                f"drawn at 041ec33; ISIN list SHA-256 `{digest[:16]}…`).")
        p = write_recall(df, Path(a.out or "docs/data/flag_recall_sample.md"), note)
        keep = df[[c for c in df.columns if c.startswith("_") or c == "row"]].copy()
        keep["_key_dt"] = keep["_key_dt"].astype(str)
        (src.parent / "recall_rows.json").write_text(
            keep.to_json(orient="records", indent=1), encoding="utf-8")
        print(f"{len(df)} of {df.attrs['population']} unflagged -> {p}")
        return 0
    df = build(per_flag=a.per_flag)
    a.out = a.out or "docs/data/flag_audit.md"
    p = write(df, Path(a.out))
    print(f"{len(df)} rows across {df['flag'].nunique()} flags -> {p}")
    print(json.dumps(df.attrs.get("population", {}), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
