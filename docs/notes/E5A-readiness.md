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
