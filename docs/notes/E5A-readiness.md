# E5-A — readiness note (2026-09-27)

E5-A (`docs/strategies/E5-A.md`, DRAFT, rewritten today from `E5.md` §2
per the audit's Deliverable 3). **No runs, no code.** **Not ready to
lock:** nine decisions below, then a build. A0 and A3 need no new data;
A1 and A2 each have a data precondition; A4 has no source.

**Change-log entries that apply** (CLAUDE.md non-negotiable 1): E5-A §14
— 2026-09-16 draft, 2026-09-27 rewrite. For the stack the ranker plugs
into, E1 §15 — 2026-09-17 ADV guard (blind, after lock); 2026-09-21 buy
sizing net of costs; 2026-09-27 determinism; 2026-09-27 audit corrections
a–d; 2026-09-27 D1/D2 data repairs. If the stack becomes E1 + E1d, E1d
§10's entries apply too.

## 1. What the rewrite changes, and why

| draft (2026-09-16) | rewrite | audit point |
|---|---|---|
| one model with every feature | A0 price/volume control; each family alone on A0 | compare each family against the same control |
| fixed 21-session purge | purge by stored label interval: usable at R only if `observable_at` ≤ R; gap is h + 1 month-ends | 21 sessions leaks 3- and 12-month labels |
| hyperparameters fixed on 2007–2012, evaluated on 2007–2016 | tuned on data truncated at 2010-12-31; 2007–2010 exploratory; development verdict on 2011–2016 | no period both tuning and evaluation |
| features assumed present | feature store with `available`, `published_at`, `usable_from`; NaN ≠ 0; A0 fallback until 36 cross-sections; share reported | early years lack company data |
| sector dummies, E2-D positioning, insider | dropped / promoter only | coverage and data-quality findings |

## 2. When each family can first act (from documented start dates)

Estimated from the sources' documented first dates under §4 and §6's
rules; the build computes the exact dates.

| candidate | first feature | first refit with 36 12-month cross-sections | active share of `e5a_development` (2011–16) | validation |
|---|---|---|---|---|
| A0 | 2005-01 | before 2011 | 6 of 6 years | full |
| A3 world | 2007-01 (3 factors) | Dec 2011 | 5 of 6 | full |
| A2 promoter | 2010-11 | Dec 2014 | 2 of 6 | full |
| A1 events | 2010-12 (12-month window) | Dec 2014 | 2 of 6 | full; flag rates 0.8% (2010) → 5.9% (2016) |
| insider PIT | 2016-01 | Dec 2020 | 0 | 2021 only |

A1 and A2 will be mostly fallback in development, so their development
result is low-power and diluted toward A0. That is the conservative
direction.

## 3. Build (after the decisions)

1. `tools/build_e5a_features.py` → a feature store under `data/` (a data
   build, not a sweep), one file per family, with the §6 columns and tests
   that a record published after M cannot change M's features.
2. Labels with `label_start` / `label_end` / `observable_at` from the
   engine's own §9 valuation, delisting included.
3. Training-set selector plus the **mandatory lookahead tests**: changing a
   label that becomes observable after R leaves the model fitted at R
   byte-identical; two fits with the same inputs give identical bytes.
4. Tuning tool on `truncate_end(2010-12-31)`; its output is written into
   §5 before the lock.
5. Engine: a precomputed-score signal (the `signal=` knob exists) with a
   per-decision fallback flag; `sweep.e5a_rows`, `classify_e5a` (two GATE
   blocks plus the mandate block), `configs/e5a*.toml`, periods
   `e5a_exploratory` and `e5a_development`.
6. The manifest hashes every consumed input — feature files, labels,
   models. This closes the audit's run-identity gap for E5-A.

Compute is small: roughly 100k rows per fit, 3 fits × 15 refits per row.

## 4. Decisions for Aarsh

**Decided 2026-09-28** (E5-A §14): 1, 3, 4, 5, 6, 7, 9 as recommended;
**8: A4 PARKED** (GKG starts 2015; revisit with a 2011-onward source or in
the live year); **2: E1 + E1d** (settled 2026-09-29). A2's
precondition is settled: both measures (promoter-share change, promoter-%
change) and an unexplained total-share-change flag, as features, nothing
thresholded.

1. **Order.** GATE's order puts E5-A last; the audit recommends it next.
   Needs a dated line in GATE and ROADMAP. *Recommended: next, once the stack is settled.*
2. **Stack.** Is A0 measured against E1 base or E1 + E1d? *Confirm E1d first,
   then lock A0 against whichever stack is in force.*
3. **Dependency.** Add `lightgbm` to CLAUDE.md 7 (not installed; brings
   scipy). *Recommended: yes, pinned.*
4. **Tuning.** An 8-point grid on 2007–2010, or no tuning at all (the S4
   defaults as the base). *Recommended: the grid; S4 is its check.*
5. **Refit.** Annual (S6 monthly), or monthly as the base. *Recommended:
   annual.*
6. **Activation and windows.** K = 36 cross-sections at ≥ 50% coverage,
   one common window with the fallback reported; or A1/A2 get their own
   later windows (the E2-A precedent). *Recommended: common window.*
7. **Positioning scope.** Promoter shares only; insider PIT parked, as
   E2-D2 is. *Recommended: yes.*
8. **Company news (A4).** There is no issuer-level source. Options: an
   issuer-news source with entity linking (GDELT GKG exists only from
   2015; it would be a new backfill); LLM extraction from BSE filing text
   (overlaps A1); or drop A4. *Recommended: drop A4 from E5-A.*
9. **Family adoption rule.** A family joins the stack only if it is
   ADOPT both against A0 and against the stack. *Recommended: yes.*

Preconditions that are not decisions: A1 needs a sampled precision check
of E2-A's subtypes; A2 needs E2-D1 readiness §3 settled. The count: A0 +
A1–A3 adds **four** experiments to STATE when all have verdicts.

## 5. Build (2026-09-29, session 5) — A0 ready to lock

Built at `64707cb`/`e5a2fab` (+ docs): `pflab/ranker/`, engine signal
`precomputed`, `sweep.e5a_rows`, `classify_e5a`, `configs/e5a_a0.toml`,
periods `e5a_exploratory` / `e5a_development`, `tools/build_e5a_features.py`,
`tools/tune_e5a.py`. `lightgbm==4.7.0` pinned. `pytest -q`: 683 passed.
Stores for all three periods (22–70 s) under `data/e5a/<period>/`. Tuning re-run: all 72 fits
byte-identical.

**§5 tuned point: 7 / 200 / 0.05.** Every point's mean IC is negative
(h1 ≈ +0.02; h3 ≈ −0.03; h12 ≈ −0.08, 2008–2010). Recorded, not acted on.

### Lines the build could not follow as written (the lock must confirm)

1. **§4's delisting parenthesis** paraphrases pre-amendment E1 §9 ("exits
   at its last close on the session after its last row"). The engine now
   follows E1 §15 (2026-09-17, 2026-09-27 b), and so do the labels: sold at
   the first open it trades again; written down to zero on the 250th missing
   session (recovery after that is ignored). Reading the old text literally
   would need hindsight (is a gap a stop?).
2. **The percentile target needs the whole cross-section**, not just the
   median: `target_observable_at` = latest `observable_at` in U(M). A
   pending write-down holds its cross-section back up to 250 sessions. At
   the 2010 cut, 3 of 73 h1, 7 of 73 h3 and 7 of 73 h12 cross-sections are
   held back beyond the structural end-of-panel ones; tuning scored 31 / 25
   / 16 of 36 months.
3. **U(M) carries names whose rows have stopped** (the stack's universe
   forward-fills turnover): 8% of U(M) rows have no open after M
   (`no_entry`). They get no label and no score, as the stack cannot rank them.
4. **§6a window conventions** (unspecified): momentum 1/3/6 months on market
   sessions (21 a month), no skip; 12-1 exactly E1's; volatility, traded
   value and the 252-session high on the name's own rows, full windows only.
5. **Unscored names**: a name with no row at M publishes nothing at M.
6. **Tie-break past §5's rule**: 7/200/0.02 and 7/200/0.05 tied on leaves
   and `min_data_in_leaf`; the higher IC was taken.
7. **Model details** §5 leaves open: L2 regression; target
   (rank − 0.5)/n − 0.5; `num_threads` 1; S6 refits at every month-end and
   scores the next.

### The lock must also settle
- STACK for development: `regress_bases.py E1d-e5a-dev` (new, base only).
  STACK for validation: E1d's job-6 sweep, or a re-run at the lock tag.
- Rebuild the three stores at the lock tag (the store refuses other code).

## 6. Lock (2026-09-29, session 6) — A0 LOCKED

**Change-log entries that apply** (read with the locked text): E5-A §14 —
2026-09-16, 2026-09-27 rewrite, 2026-09-28 readiness decisions, 2026-09-29
D2 (stack E1 + E1d), 2026-09-29 session 5 (first tuning, now void),
2026-09-29 session 6 lock decisions 1–5 and the lock. For the stack: E1 §15
(2026-09-17 ADV guard; 2026-09-21 net-of-cost buys; 2026-09-27 determinism,
corrections a–d, D1/D2 repairs; 2026-09-28 measurement fixes) and E1d §10.

- **Span**: E5-A §2–§13, 13,096 chars, SHA-256 `9455930e…cb2ec5f`
  (`tools/check_lock.py` REGISTRY `E5-A`). Tag `lock/E5-A`; worktree
  `D:\pl_runs\E5-A`.
- **Readings 1–7 of §5** are settled by §14's session-6 entry: 1 → §4;
  2 → per-fit percentile (§4 Target); 3 and 5 → §4 U(M) and "No open after
  M"; 4 and 7 → §5/§6a text; 6 → §5 tie-break.
- **Re-tuned** under the locked §4: 7 / 200 / 0.02, IC +0.00520 (all eight
  points: h1 and h3 positive, h12 negative, −0.045 to −0.061). The old point
  (7 / 200 / 0.05) was fit to the superseded target.
- **STACK**: development = `E1d-e5a-dev` (job 7, `19ac284`; backtest,
  signals, eval, data and the E1/E1d configs are byte-identical at the tag);
  validation = `E1d-e5a-val`, re-run from the lock worktree.
- **Stores** rebuilt at the tag for `e5a_exploratory`, `e5a_development`,
  `validation`.
