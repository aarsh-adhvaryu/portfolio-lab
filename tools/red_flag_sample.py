"""Build docs/data/red_flag_sample.md from the BSE announcements on disk.

Phase 1 task 1.5: Aarsh reads this to judge whether the keyword rules in
`pflab/data/red_flags.py` fire on the right things before E2-A freezes them.

The rules are NOT tuned here. This only shows what they currently catch, plus
the highest-volume headlines they do NOT catch, which is where a missing rule
would show up.

    python tools/red_flag_sample.py [--top 50]
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

import pandas as pd

from pflab.data import data_dir, red_flags


def _corpus(root):
    files = sorted((root / "bse_announcements").rglob("*.parquet"))
    if not files:
        raise SystemExit("no BSE announcements collected yet "
                         "(run: pflab collect bse --from ... --to ...)")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    for c in ("headline", "category", "subcategory"):
        df[c] = df[c].fillna("").astype(str)
    return df, files


def _normalise(headline: str) -> str:
    """Strip the company-specific part so near-identical headlines group.

    BSE headlines embed names, dates and amounts; without this every row looks
    unique and nothing is "most common".
    """
    t = re.sub(r"\d+", "#", headline.lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t[:110]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=50)
    a = ap.parse_args(argv)

    root = data_dir()
    df, files = _corpus(root)
    df["flags"] = [red_flags.classify(r.headline, r.category, r.subcategory)
                   for r in df.itertuples(index=False)]
    df["n_flags"] = df["flags"].map(len)
    hit = df[df["n_flags"] > 0].copy()
    miss = df[df["n_flags"] == 0]

    dates = pd.to_datetime(df["news_dt"], errors="coerce")
    by_flag = collections.Counter(f for fl in df["flags"] for f in fl)

    L = []
    L.append("# Red-flag keyword sample — for review\n")
    L.append(f"Corpus: **{len(df):,} BSE announcements** over {len(files)} days, "
             f"{dates.min():%Y-%m-%d} to {dates.max():%Y-%m-%d}.")
    L.append(f"Flagged: **{len(hit):,}** ({100 * len(hit) / len(df):.2f}%).\n")
    L.append("Rules live in `pflab/data/red_flags.py`. They are a first draft and "
             "are **not** tuned against this sample — that is the point of the "
             "review. Nothing here feeds E1; this is E2-A groundwork.\n")

    L.append("## Hits per rule\n")
    L.append("| flag | hits | share of corpus |\n|---|---|---|")
    for f, n in by_flag.most_common():
        L.append(f"| {f} | {n:,} | {100 * n / len(df):.3f}% |")
    silent = sorted(set(red_flags.RULES) - set(by_flag))
    if silent:
        L.append(f"\n**Rules that never fired:** {', '.join(silent)}. "
                 "Either the pattern is wrong or the window is too short to "
                 "contain one.\n")

    L.append(f"\n## The {a.top} most common flagged headlines\n")
    L.append("Digits are replaced with `#` so near-identical headlines group.\n")
    L.append("| n | flags | headline (normalised) |\n|---|---|---|")
    grp = collections.Counter()
    ex = {}
    for r in hit.itertuples(index=False):
        k = _normalise(r.headline)
        grp[k] += 1
        ex.setdefault(k, r.flags)
    for k, n in grp.most_common(a.top):
        L.append(f"| {n} | {', '.join(ex[k])} | {k} |")

    L.append("\n## What to look for\n")
    L.append("1. **False positives.** `PROMOTER_PLEDGE` matches the bare word "
             "`pledge`, so routine SAST 31(1) disclosures score the same as a "
             "distressed pledge invocation. Decide whether that is wanted.")
    L.append("2. **Over-broad abbreviations.** `REGULATORY_ACTION` includes "
             "`\\bed\\b` and `\\bsat\\b`, which are also ordinary English words.")
    L.append("3. **Missing rules.** The table below is the highest-volume "
             "*unflagged* headline shapes; anything in it that should be a red "
             "flag means a rule is absent.\n")

    L.append("## 25 most common unflagged headlines (for comparison)\n")
    L.append("| n | headline (normalised) |\n|---|---|")
    mg = collections.Counter(_normalise(h) for h in miss["headline"])
    for k, n in mg.most_common(25):
        L.append(f"| {n} | {k} |")

    L.append("\n## Caveat on the window\n")
    L.append(f"This is {len(files)} days, not the 2010 backfill the task list "
             "describes; `docs/PHASE1_SPRINT.md` defers that until after the "
             "first development run. It is enough to judge the *shape* of what "
             "the rules catch, not their long-run base rates.\n")

    # Always beside the repo's other docs, never relative to PFLAB_DATA_DIR,
    # which may live on a different drive.
    out = Path(__file__).resolve().parents[1] / "docs" / "data" / "red_flag_sample.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {out}  ({len(df):,} announcements, {len(hit):,} flagged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
