# E5-A — Learned cross-sectional ranker, one information family at a time

Status: **A0 LOCKED 2026-09-29** (`lock/E5-A`, §2–§13; A1–A3 not locked). Rewritten 2026-09-27 from `E5.md` §2, per the external
audit's Deliverable 3). Judged by `GATE.md`. Readiness:
`docs/notes/E5A-readiness.md`. Items marked **[D n]** are open decisions
for Aarsh, listed in that note; the text states the recommended reading.

## 1. Purpose

Test whether information improves **which stocks are held** while the
portfolio, liquidity, turnover, cost and tax rules stay fixed. A learned
ranker on prices and volume comes first, as the control; each information
family is then added to it alone, against that same control, so its
contribution is measured and not assumed.

## 2. Hypothesis

A model given only prices and volume will roughly reproduce the stack's
rank (H0). A family carries information only if adding it to that model,
with nothing else changed, improves the portfolio under GATE arithmetic.

## 3. Candidates

Each is its own experiment in `docs/STATE.md`'s count (GATE rule 3).

| id | inputs | compared against | window |
|---|---|---|---|
| **A0** control | price/volume only (§6a) | STACK | §8 |
| **A1** issuer events | A0 + §6b | A0, then STACK | §8 |
| **A2** positioning | A0 + §6c | A0, then STACK | §8 |
| **A3** world exposure | A0 + §6d | A0, then STACK | §8 |
| **A4** company news | A0 + §6e | A0, then STACK | not runnable until a source exists **[D 8]** |

- A0 runs first and has a written verdict before any family is locked.
  A0's lock freezes its code, hyperparameters and training schedule; every
  family uses them unchanged. A family changes **only the input columns**.
- Families are added **one at a time and never combined** in E5-A. A
  combined model is a new charter written after the family verdicts.
- Families may run concurrently once A0 has its verdict (GATE parallel
  rule 1): each is measured against the same frozen A0.

## 4. Labels and purging by label interval

For month-end M and horizon h ∈ {1, 3, 12} months, M_h is the h-th
month-end after M.

- **Label.** The return a holding bought at the open of the session after
  M would earn if sold at the open of the session after M_h, under the
  engine's own E1 §9 rules as amended by E1 §15 (2026-09-17; 2026-09-27
  (b)): adjusted prices; dividends as cash on the ex-date, for ex-dates
  after the buy session up to and including the exit session; a name with
  no row at the exit session stays held and is sold at the first open it
  trades again; a held name is written down to zero on its 250th
  consecutive missing session, and the label ends there, worth zero plus
  the dividends received (a recovery after that is ignored). Minus the
  median of the same quantity over U(M).
- **U(M).** The stack's E1 §2 universe at M, restricted to names with a
  panel row at M. The stack's universe forward-fills turnover and so
  carries names whose rows have stopped; a name with no row at M is not in
  U(M), for training or scoring. The restriction follows the turnover
  ranking, so it never promotes a thinner name.
- **No open after M.** A name in U(M) with no EQ open at the session after
  M: if it opens again before its 250th consecutive missing session (a
  BE/BZ session, a short gap), the engine could not have bought it and the
  row has no label; if it never does, it gets the engine's label, −100%,
  with `label_end` and `observable_at` on the 250th missing session.
  Excluding it would train on survivors only.
- **Target.** The model is fit on each cross-section's centred percentile,
  (rank − 0.5)/n − 0.5 with average ranks, computed **at each fit date R
  over the labels of U(M) observable at R**. A label not yet observable at
  R (a pending write-down) is absent from that fit and joins later fits
  once it resolves; it never holds back the rest of its month.
- **Rows.** One per (ISIN, M) with the ISIN in U(M). No name outside U(M)
  enters training.
- **Every label row stores** `label_start` (session after M), `label_end`
  (the session whose open closes the label, or the write-down session),
  and `observable_at` (the open of `label_end`).
- **Purge.** A model fitted at date R trains only on rows with
  `observable_at` ≤ the close of R. Because an h-month label from M closes
  at the open *after* M_h, it is usable at R only when M_h < R — an
  effective gap of h + 1 month-ends, derived from the interval, never from
  a fixed session count. No further embargo: training labels always end
  before the prediction's own label starts.
- **Validation labels never enter fitting, tuning or feature choice for
  the predictions they overlap.** Tuning (§5) is performed on data
  truncated at 2010-12-31 by `truncate_end`, so no later label can reach
  it by construction.

## 5. Model, training and tuning

- LightGBM 4.7.0 regression (L2 objective) on §4's target, one model per
  horizon, `deterministic=true`, `force_row_wise=true`, `num_threads` 1,
  `seed` 20260927 (LightGBM derives its bagging and feature-fraction seeds
  from it); training rows in (M, ISIN) order; features as NaN where
  unavailable (LightGBM's own missing-value handling). The manifest records
  the LightGBM version, every hyperparameter and the SHA-256 of each fitted
  model file (`model_to_string`). `lightgbm` is in CLAUDE.md 7 **[D 3]**.
- **Refit once a year** at the December month-end R; that model scores
  the twelve month-ends that follow **[D 5]**. Training is expanding:
  every row observable by R (§4). S6's monthly refit fits at every
  month-end and that model scores the next one.
- A model is fitted only if its training set holds ≥ 12 month-end
  cross-sections for every horizon; before that, the stack's own rank is
  used. This affects 2007 only, which is exploratory (§8).
- **Tuning, once, before A0 locks** **[D 4]**: on the panel truncated at
  2010-12-31, walk-forward predictions for 2008–2010 are scored by mean
  monthly Spearman rank IC against their own labels, averaged across the
  three horizons, using only labels observable by 2010-12-31 (each month
  scored on the labels observable in it). Grid, eight
  points: `num_leaves` {7, 31} × `min_data_in_leaf` {200, 1000} ×
  `learning_rate` {0.02, 0.05}; fixed: 300 trees, `bagging_fraction` 0.8
  every iteration, `feature_fraction` 0.8. Highest IC wins; within 0.005,
  fewer leaves, then larger `min_data_in_leaf`, then the higher IC. **The
  chosen point is written into §5 of this charter before the lock**, so
  the lock hashes it.
- **Chosen point (tuned 2026-09-29 under §4 as locked, LightGBM 4.7.0,
  `experiments/E5-A/tuning/e5a_exploratory-3d2c02ba01062121`):
  `num_leaves` 7, `min_data_in_leaf` 200, `learning_rate` 0.02** (IC
  +0.00520, the best; 7 / 200 / 0.05 at +0.00256 is inside the band and
  ties on leaves and `min_data_in_leaf`, so the higher IC is taken; scored
  months h1 34, h3 32, h12 23 of 36).
- No feature selection at any stage. Families are never re-tuned.

## 6. Features, availability and the price-only fallback

All features at M use only source records **usable** at M.

- **Feature store.** Long format, one row per (ISIN, M, feature):
  `value`, `available` (bool), `source`, `source_record_id`,
  `published_at` (the source's own timestamp, IST), `usable_from`
  (session). Usable-from rules are the ones already in force: a record
  disseminated after 15:30 is usable the next session; an undated
  shareholding quarter from the second month-end after quarter end (E2-D,
  2026-09-24). Price features are published at that session's close.
- **Missing is not zero.** A source that does not cover the issuer at M
  gives `NaN` and `available = false`; `0` means covered and nothing
  happened. A record's absence is never read as a clean company.
- **Activation** **[D 6]**. A family model is used from refit R only if the
  training set at R holds, for every horizon, ≥ 36 month-end
  cross-sections in which that family is available for ≥ 50% of U(M).
  Until then the family candidate's decisions **are A0's** — the
  predeclared price-only fallback — and are recorded as such. Once active,
  a name without family coverage is scored by the family model with `NaN`
  inputs; the share of such buys is reported.

### (a) Price/volume (A0, every candidate)
Momentum 1, 3, 6 and 12-1 months; realised volatility 21, 63, 252
sessions; traded value 21 over 126 sessions and 126 over 252; distance of
close from its 252-session high; the stack's own score at M. Sector
dummies are **not** included: the point-in-time sector map changes
taxonomy twice and covers 52.8% of held names in development.

Windows, exactly (all on adjusted close, all at M's close):
- **Momentum 1, 3, 6 months**: close at M over close 21, 63, 126 *market*
  sessions earlier, minus 1, no skip (21 sessions to a month, as the
  stack's signal counts). **12-1**: E1 §3's score exactly (252-session
  lookback, 21-session skip).
- **Volatility**: standard deviation of the name's daily returns over its
  own last 21, 63, 252 rows, × √252.
- **Traded value**: mean turnover over the name's own last 21 rows ÷ its
  last 126; last 126 ÷ last 252.
- **Distance from high**: close ÷ the maximum close over the name's own
  last 252 rows, minus 1.
- **Stack score**: E1d §3's volatility-scaled 6+12 score, standardised
  within U(M) by E1d's rule (average then z, clipped at 3).
- Own-row windows count the name's rows, as E1 §2's 250 sessions do. A
  window must be full to give a value; otherwise the feature is `NaN`,
  `available = false`. A name in U(M) with no feature available is not
  scored.

### (b) Issuer events (A1) — BSE announcements, 2010-01-01 onward
Per event subtype of E2-A's classifier: count over the trailing 1, 3 and
12 months, and months since the last one. Covered = scrip resolves to the
ISIN at M; available once the full 12-month window lies after
2010-01-01. **Precondition:** a sampled precision check of each subtype
before A1 locks (audit: event type, severity and publication time).

### (c) Positioning (A2) — promoter shareholding, 2010 onward
Change in promoter **shares** over the trailing one and two reported
quarters, split/bonus restated (E2-D1's measure, as a value, not its 1%
flag); pledge invocations. Covered = a usable quarter pair exists.
**Precondition:** E2-D1 readiness §3 (unexplained share-count
contractions, 16% of flags) settled first. Insider PIT disclosures
(2016 onward) are **not** in A2 **[D 7]**.

### (d) World exposure (A3) — E2-B factors
For each factor in {Brent, USDINR, US 10-year, India VIX, net FII flows}:
the name's trailing beta (`signals/shock_betas.py`, 36 months, ≥ 24), and
beta × the factor's change over the last 1 and 3 months; plus the Nifty
500 beta. Each edge is unavailable before its first beta (VIX 2010-03,
FII 2011-11). An exposure × move value is a hypothesis for the model to
weigh, not a trade instruction.

### (e) Company news (A4)
No issuer-level news source exists in this repo. GDELT holdings are
country-level; BSE filings are A1. Not runnable **[D 8]**.

## 7. Use

Composite score at M = the mean of the three horizon models' percentile
predictions over the scored names of U(M) (§6a). Its descending rank **replaces the stack's ranking
signal** in E1 §4 (entry ≤ 25, exit > 50). Everything else — universe,
band, six-buy limit, trend filter, ADV guard, costs, tax — is the stack's,
unchanged. The stack is the one in force at A0's lock **[D 2]**.

## 8. Windows and benchmarks

| period | dates | role |
|---|---|---|
| exploratory | 2007-01-01 → 2010-12-31 | tuning (§5); results reported and labelled exploratory; **never in any GATE or mandate count** |
| `e5a_development` | 2011-01-01 → 2016-12-31 | development verdict; STACK re-run on the same window |
| `validation` | 2017-01-01 → 2021-12-31 | validation verdict |
| sealed | 2022–2025 | never |

No period is both tuning and evaluation. Benchmarks B1–B5 on each window.

**STACK** is E1 + E1d's base row on the same window, run through the same
engine: on `e5a_development`, `tools/regress_bases.py E1d-e5a-dev`; on
`validation`, **re-run at the lock tag** (`E1d-e5a-val`, from the lock
worktree), not taken from an earlier sweep, so both sides of the
validation comparison run on the same code.

## 9. Sweep (every candidate)

| row | change |
|---|---|
| S1 | 1-month model only |
| S2 | 3-month model only |
| S3 | 12-month model only |
| S4 | untuned: `num_leaves` 15, `min_data_in_leaf` 500, `learning_rate` 0.03 |
| S5 | second seed (20270927) |
| S6 | monthly refit instead of annual |
| S7 | costs ×2 |

A0's rows are compared with STACK's base row, as GATE does. A family's
row k is compared with **A0's row k** (the perturbation applies to both
sides).

## 10. Verdict

- **A0**: GATE G1–G4 against STACK, plus the mandate block.
- **Each family**: two GATE computations — *incremental* (STACK := A0)
  and *adoption* (against the stack in force). It joins the stack only if
  both are ADOPT. The incremental verdict is the recorded evidence on the
  information family whatever the adoption verdict is.

## 11. Reported extras

Rank IC per horizon per year; share of month-end decisions and of buy
value made under the fallback, per period; share of buys whose family
features were unavailable; the family-vs-A0 difference on its active
months only (information, not a verdict); holdings overlap with STACK;
turnover; gain importance per refit (information only).

## 12. Prior, written now

A0 will largely reproduce momentum and fail G1. Families will add little
after costs and tax; A3 is the least likely to help at monthly frequency.
A null result is a result.

## 13. Not claimed

No LLM decides anything; any LLM-extracted feature enters only as a
timestamped record with its source and cutoff. No feature is chosen after
seeing results. E5-A says nothing about E5-B/C/D.

## 14. Change log
- 2026-09-16 — draft (as `E5.md` §2 E5-A).
- 2026-09-27 — rewritten per the audit's Deliverable 3: A0 price/volume
  control, families one at a time against it; purge by label interval
  (replacing the fixed 21-session gap); tuning only on 2007–2010, declared
  exploratory, evaluation from 2011 (replacing "fixed on 2007–2012");
  feature availability and publication time stored; price-only fallback
  with its share reported. Written before any E5-A code or run.
- 2026-09-28 (Aarsh, session 4) — **readiness decisions** (`docs/notes/E5A-readiness.md` §4).
  Taken as recommended: **D1** E5-A is next in GATE and ROADMAP order;
  **D3** `lightgbm` added to CLAUDE.md 7, pinned; **D4** the 8-point grid
  on 2007–2010, S4 its check; **D5** annual refit (S6 monthly); **D6** one
  common window, K = 36 cross-sections at ≥ 50% coverage, fallback share
  reported; **D7** positioning is promoter shares only, insider PIT parked;
  **D9** a family joins the stack only if ADOPT against both A0 and the stack.
  **D8: A4 PARKED, not dropped.** GDELT GKG starts 2015, so A4 could not act
  in the 2011– development window; revisit with an issuer-news source
  covering 2011 onward, or in the live year. §6(e) stands as written until then.
  **D2 (stack) waits** for the re-classification after the 2026-09-28 regression.
  **A2 precondition settled (§6(c)):** A2 carries **both** measures as
  features — the change in promoter **shares** and the change in promoter
  **percent** — plus a flag for a change in total shares with no recorded
  corporate action. **Nothing is thresholded**; the model weighs them. This
  replaces "E2-D1 readiness §3 settled first" as the precondition.
- 2026-09-29 — **D2 settled:** the stack is E1 + E1d (final regression,
  `docs/reviews/regression-2026-09-28-verdicts.md`); A0 is measured against it.
- 2026-09-29 (session 5) — **§5 tuned point written** (7 / 200 / 0.05), from
  `tools/tune_e5a.py` on the store cut at 2010-12-31 (commit `e5a2fab`).
  Every grid point's mean IC is negative (h1 ≈ +0.02; h3 and h12 negative
  over 2008–2010); recorded, nothing changed because of it. Build readings
  the lock must confirm are in `docs/notes/E5A-readiness.md` §5.
- 2026-09-29 (Aarsh, session 6) — **lock decisions** on readiness §5's
  build readings, written into §4–§6 and §8 before the lock:
  1. *Delistings*: labels follow E1 §9 as amended by E1 §15 (sold at the
     first open the name trades again; written to zero on the 250th missing
     session). §4's wording corrected to match.
  2. *Target timing*: the percentile at fit date R is over the labels
     observable at R; a pending write-down joins later fits once it
     resolves and never holds back the rest of its month (replaces the
     build's whole-cross-section `target_observable_at`).
  3. *Universe rows*: a name with no row at M is not in U(M), for training
     or scoring; a name with a row at M and no later open gets −100%,
     observable on the 250th missing session. A name with a row at M that
     opens again, but not at the session after M (a BE/BZ session), keeps
     no label — the engine cannot buy it (`no_buy`); 774 such rows at h1 in
     the exploratory store, 1 `no_open`.
  4. *Unstated choices* written into §5 (objective, determinism, S6's
     monthly schedule, the last tie-break) and §6a (every window).
  5. *Validation STACK* is re-run at the lock tag (§8).
  Decisions 2 and 3 change the target, so **§5 was re-tuned** on the
  rebuilt 2010-12-31 store: **7 / 200 / 0.02** (IC +0.00520; was 7 / 200 /
  0.05 under the superseded target, now void). The grid rule is unchanged.
- 2026-09-29 (session 6) — **A0 LOCKED**: §2–§13, 13,096 chars, SHA-256
  `9455930e65a2edce0d40d1cdebf65b0a1a434a0662d366c57652c2640cb2ec5f`, tag
  `lock/E5-A`, run worktree `D:\pl_runs\E5-A`. Feature stores rebuilt at
  the tag. A family (A1–A3) locks separately, with its own entry here.
- 2026-09-30 (Aarsh, session 7) — **decision 3 confirmed** (entry of
  2026-09-29): a name trading BE/BZ at the session after M keeps no label,
  because it cannot be bought; the 1–2 rows that never open again keep
  −100%. The tuned point **7 / 200 / 0.02** stands by §5's grid rule.
- 2026-09-30 (Aarsh, session 7) — **A1 reader plan decisions**
  (`docs/notes/A1-reader-plan.md` §5). **Jev** is TypeSafe's hosted
  classification model (an API needing `TYPESAFE_API_KEY`), not a person;
  there is no key, so J is dropped and the contest is **K against L**; J can
  be added later. **L = `qwen3.5-9b-16k`**; `gemma4-12b-16k` is run and
  reported but never chosen after its score is seen. The per-flag adoption
  rule is as proposed. The 250-row unflagged recall sample is drawn (seed
  20260930, `docs/data/flag_recall_sample.md`). The ~924-PDF rating
  history fetch is queued for Aarsh (RUNNING.md job 13). Reference labels:
  `docs/data/flag_audit_labels.md` at `a15c775`, reviewed by Aarsh, with a
  SUBTYPE column (AT_COMPANY 182, AGAINST_COMPANY 5, RELATED_ENTITY 7,
  NOT_EVENT 10, UNCLEAR 47).
- 2026-09-30 (Aarsh, session 7) — **§6(b) amended before any A1 run** (no
  A1 result exists; A1 is not locked). §6(b) reads with this entry:
  1. Event features are counted **per flag and per subtype**
     (AT_COMPANY, AGAINST_COMPANY, RELATED_ENTITY; the subtypes of
     `flag_audit_labels.md`). **NOT_EVENT is excluded**: it is not an
     event. The model therefore weighs a lender's loss to a borrower's
     fraud, a subsidiary's insolvency and the company's own fraud
     separately. How a reader's UNCLEAR enters is **open**, for Aarsh
     before A1 locks.
  2. The reader contest scores **subtype accuracy**, not TRUE/FALSE.
  3. Readers also output a **confidence**. It is recorded and reported,
     and is **not** an A1 feature.
  *Reason:* the audit's TRUE/FALSE question counted a lender's loss or a
  subsidiary's insolvency as FALSE, though each is a risk event for the
  company, of a different kind.
- 2026-09-30 (Aarsh, session 8) — **A0 development placebo: PASS**
  (`docs/reviews/E5-A0-development.md`, check (i); not gating). A0 was
  refitted at `lock/E5-A` with labels shuffled within each (M, h),
  seed 20260930 (`tools/e5a_placebo.py`). *Reason:* the placebo exists to
  detect leakage. Its IC is about zero (−0.02 / −0.04 / +0.01) and its CAGR
  is 8.3 pp below the stack's. Its shallower drawdown comes from having 25%
  of NAV invested, not from selection.
- 2026-09-30 (Aarsh, session 10) — **A0 verdict INCONCLUSIVE recorded**
  (`docs/reviews/E5-A0-verdict.md`; STATE, ROADMAP). §3's condition is met,
  so the families start against the frozen A0: A1 and A3 built to ready to
  lock, A2 readiness only.
- 2026-09-30 (Aarsh, session 10) — **A1 reader decisions**
  (`docs/notes/A1-reader-plan.md` §5 items 7–10; no rule changed after the
  scores). (a) The per-flag rule as written: **L reads DEFAULT,
  FORENSIC_AUDIT, REGULATORY_ACTION**; K keeps AUDITOR_RESIGNATION, FRAUD,
  INSOLVENCY, PROMOTER_ENCUMBRANCE, RATING_DOWNGRADE. RESULTS_DELAY: listed
  for L in the instruction, but the rule gives K (L 88.0% < K 88.5%,
  unrounded); K until Aarsh confirms. (b) §6(b)'s open item is closed: K's
  events enter as subtype **UNCLEAR**, never AT_COMPANY; **UNCLEAR is its
  own subtype**, counted separately; NOT_EVENT excluded. (c) Reading rating
  letters (gemma 81%, L 50% with the letter) is a finding for a future
  charter, declared as suggested by these scores; gemma is not chosen.
- 2026-10-01 (Aarsh, session 11) — **family decisions** (no family run
  exists; readiness `docs/notes/E5A-families-readiness.md`).
  (a) **RESULTS_DELAY stays with K**: the pre-set per-flag rule on the
  unrounded scores (L 88.0% < K 88.5%). This supersedes the 2026-09-30
  instruction listing it for L, which misread rounded figures. No extra reads.
  (b) **A1 readings confirmed**: months-since is censored at the month-ends
  since the 2010 feed start (a lower bound, not "never"); coverage requires
  the 12-month window to lie in the feed (from 2010-01-01).
  (c) **A3 readings confirmed** as in readiness §4: transforms (Brent,
  USDINR `pct`; US 10-year, VIX `diff`; FII monthly `sum` of daily net
  equity; Nifty 500 TRI `pct`); the 3-month change uses the same transform as
  the 1-month; FRED and NSDL series usable the next calendar day, VIX and the
  TRI on their own date; month-end returns on adjusted close, no fill.
  (d) **§6(c) amended before any A2 run** (none exists; A2 is not locked).
  Pledge invocations are **dropped, declared**: there is no source (~41 BSE
  headlines 2014–2026). In their place: **pledged shares as % of promoter
  holding**, and its 1- and 2-quarter changes. The total-share change with
  no recorded split or bonus is **carried as a feature** (the value, since a
  flag would need a threshold and nothing is thresholded; a build reading for
  A2's lock). E2-D1 readiness §4 items 1–6 carry over unchanged.
  *Reason:* (a) the rule was set before the scores; (d) a column with no
  source cannot be built, and pledging is measurable from the same filings.
- 2026-10-01 (Aarsh, session 11) — **hypotheses registered before any
  family result exists** (§3; each counts in STATE, GATE rule 3).
  - **A1** issuer events: among stocks with similar momentum, verified
    adverse events distinguish deteriorating businesses.
  - **A2** positioning: genuine ownership changes add information after
    separating dilution, reorganisations and pledging.
  - **A3** world exposure: a global move affects companies differently
    according to previously measured exposure, beyond what prices already
    show.
  - **E5-A-ALL** (new candidate): A0 plus A1's, A2's and A3's columns
    together, with A0's frozen hyperparameters, activation and windows.
    Judged incrementally against A0 and for adoption against the stack in
    force, as §10. Locks once A2 is built. *This amends §3's "never combined
    in E5-A; a combined model is a new charter written after the family
    verdicts"*: the combination is registered now, before any family
    verdict, rather than chosen after them, which removes the freedom that
    rule guarded against. It is one experiment, fixed now, not a search over
    combinations.
  - **A5** valuation (new family, **not part of E5-A-ALL**): among stocks
    with similar momentum, stocks cheap relative to earnings, sales,
    dividends and their own history outperform, and the model learns when
    cheapness is a trap. A0 + valuation columns, against A0 then the stack
    (§10). Its columns and sources are fixed in a §6(f) entry before it
    locks; data probe in the readiness note.
- 2026-10-01 (session 11) — **A1 and A3 LOCKED.** Span §2–§13 unchanged
  (13,096 chars, SHA-256 `9455930e…2cb2ec5f`, A0's); A1 and A3 read with
  every entry above, in particular 2026-09-30 (§6(b) amended; reader
  decisions) and 2026-10-01 (decisions a–c; hypotheses). Tags
  `lock/E5-A-A1` and `lock/E5-A-A3` → `6a29dde`, run worktrees
  `D:\pl_runs\E5-A-A1`, `D:\pl_runs\E5-A-A3`; configs `configs/e5a_a1.toml`,
  `configs/e5a_a3.toml`. **A0-identity at the tag: IDENTICAL** in both
  periods (development 3,232 sessions / 447 trades / 72 decisions,
  validation 4,471 / 541 / 60; pflab from the worktree; logs
  `experiments/_identity/a0_6a29dde_*.log`). A0's store is valid at the tag
  because it rebuilds byte for byte there (`build_e5a_features.py --verify`;
  `engine.py` moved after `lock/E5-A` only in E3-R's gears path). A1 and A3
  stores rebuilt (features byte-identical to the readiness builds).
  Development runs next; validation after each development review.
- 2026-10-01 (Aarsh, session 11, continued) — **A2 readings approved**
  (readiness §3, items 1–4) with two conditions:
  (i) **each quarter is usable from its BSE filing date**;
  (ii) **pledge is 0 only when reported nil, otherwise NaN**.
  (ii) is applied: the parser keeps a null, blank or absent pledge as
  missing (`bse_shareholding._pledge`); in a 200-quarter sample of the API
  (100 per era) no pledge field was null, blank or absent, so every stored 0
  is a reported nil and the stores are unchanged.
  (i) is **not yet applied; A2 is not locked**. No quarter before Sep 2015
  carries a BSE filing date (43,436 old-era rows, `unresolved`), and the
  announcements feed dates shareholding filings only from 2014. Read
  strictly, A2 has no usable quarter in 2010–2014, never activates in
  development (§6 [D 6] needs 36 covered cross-sections per horizon), and
  its development decisions are A0's exactly. For Aarsh: keep (i) as read,
  or name a rule for undated quarters.
- 2026-10-01 (Aarsh, session 11, continued) — **A5 dating rule**, before any
  A5 data is collected. A quarter's results are usable from the **later**
  of (a) the statutory deadline — quarter end + 45 days, + 60 days for the
  March quarter — and (b) the matched results announcement
  (`docs/data/bse_results_finding.md` §3); **unmatched: quarter end + 90
  days.** The pre-2015 rule is Listing Agreement Clause 41: unaudited
  results within 45 days of each quarter; for the last quarter, audited
  annual results within 60 days in place of it. Where an older version
  allowed less time, 45/60 is the later date, so the rule is never earlier
  than the law allowed. **Dividend yield is NaN until its 12-month window
  clears the NSE feed hole** (ex-dates 2009-04-01 → 2010-04-30, 12–28 a month
  against 76–308 in the same months of 2008 and 2010): NaN at month-ends
  2009-04-30 → 2011-03-31, available from 2011-04-30. *Reason:* one sampled
  match was an analyst-call notice dated 9 days before the results.
- 2026-10-01 (Aarsh, session 11, continued) — **E5-A-ALL activation**: each
  family's columns switch on at that family's own activation refit, as when
  run alone (§6 [D 6]: A3 from 2010-12; A1 and A2 from 2014-12), and are
  NaN before it; the model is A0's until the first family is active.
  **Evidence:** A1 and A2 have only **2015–2016** development evidence (A2
  none if condition (i) above stands as read); 2011–2014 development tests
  A3 alone. **ALL is not locked**: it carries A2's columns, so it waits for
  A2's dating, then the build and an A0-identity check.
- 2026-10-01 (session 11) — **A0 store accepted at later code** (logged in
  the lock entry above; stated here on its own). `engine.py`, in the A0
  store's builder hash, changed after `lock/E5-A` (E3-R's gears, `c06c6af`),
  so every later run refused the store. `build_e5a_features.py --verify`
  rebuilt both periods byte for byte at `a01be98` and recorded that builder
  hash beside the original (`store.verified_shas`); the files and the
  original stamp are unchanged, so `lock/E5-A` runs are unaffected.
- 2026-10-01 (Aarsh, session 11, continued) — **A2 dating, pre-run
  amendment** (no A2 run exists), replacing condition (i) of the entry
  above. A quarter with a BSE "Shareholding Pattern" announcement (the feed
  carries them from 2014) is usable from the **later** of that announcement
  (after 15:30: next day) and **quarter end + 21 days** — the filing deadline
  of Listing Agreement Clause 35 before Dec 2015 (verified: "within 21 days
  of the end of each quarter") and LODR Reg 31 after. **Undated quarters
  use E2-D1's rule** (usable from the first day of the second month after
  quarter end). Build reading: a quarter with no announcement but an API
  filing date (`Fld_AuthoriseDate`) is dated like an announced one from that
  date. Matched: 99.8% of 2014 quarters, 95.9% of 2015, 100% of 2016.
  **Check before the lock:** of 23,068 dated 2014–2016 quarters, **319
  (1.38%) were filed after their second month-end** — the undated rule's
  usable point — under the 5% stop threshold. Pledge condition (ii) as above.
- 2026-10-01 (session 11, continued) — **A2 and E5-A-ALL LOCKED.** Span
  §2–§13 unchanged (13,096 chars, `9455930e…2cb2ec5f`); read with every entry
  above, in particular 2026-09-28 and 2026-10-01 (§6(c) amended; A2 dating;
  ALL registration and activation). Tags `lock/E5-A-A2` and `lock/E5-A-ALL`
  → `31a4b7c`; worktrees `D:\pl_runs\E5-A-A2`, `D:\pl_runs\E5-A-ALL`;
  configs `configs/e5a_a2.toml`, `configs/e5a_all.toml`. **A0-identity at
  the tag: IDENTICAL** in both periods (development 3,232 sessions / 447
  trades / 72 decisions, validation 4,471 / 541 / 60; logs
  `experiments/_identity/a0_31a4b7c_*.log`). A2 stores rebuilt at the tag
  (identical to the pre-commit build). ALL reads the A1, A2 and A3 stores,
  each checked against its member's own config (`ranker/combined.py`); each
  member switches on at its own activation refit with its columns NaN
  before (`walk.Spec.groups`). `family.py` unchanged, so the A1 and A3
  locks' stores stay valid. Development runs next.
- 2026-10-01 (Aarsh, session 12) — **§6(f) A5 columns and sources**, before
  any A5 store or run exists (the hypothesis entry above requires them before
  the lock). Eight columns, nothing thresholded: **earnings yield** (TTM EPS
  restated to M's share basis ÷ M's close), **sales yield** (TTM revenue ÷
  market cap), **dividend yield** (TTM, NaN 2009-04-30 → 2011-03-31 as
  decided); **each yield's percentile within the name's own trailing 36
  month-ends** (NaN with fewer than 24 values); **TTM revenue and TTM net
  profit year-on-year change** (÷ |the earlier TTM|), the "trap" context the
  hypothesis names. Sources: BSE quarterly results (RUNNING job 23,
  standalone, BSE's template), dated by the A5 rule above; NSE dividend feed;
  shares outstanding from the latest usable BSE shareholding quarter, dated
  as A2's quarters are; panel close and split/bonus factor. Build readings
  (`ranker/valuation.py`): TTM from the latest usable quarter and the three
  before it, each usable at M, never substituted; per-share figures restated
  by k(then)/k(M), share counts by k(M)/k(then); a name with no dividend in
  the window has yield 0. **Coverage check** on the full pull, every name of
  U(September) 2007–2021: revenue, net profit and EPS all present for
  89.4%–99.5% a year; no year more than 5 pp below the finding's probe (2019
  the closest, −3.6 pp; `probe_bse_results.py coverage-pulled`).
  **Two further decisions (Aarsh, same session, before the lock):** (1) the
  NSE feed is thin before 2007 too (ex-dates 2004: 26, 2005: 398, 2006: 502,
  against 694–1,160 from 2007), so **dividend yield is also NaN at every
  month-end through 2007-12-31**; (2) a non-payer's yield **stays 0**, and §6
  [D 6] activation is applied as written, although that makes dividend yield
  alone cover every name. **Findings:** BSE's endpoint itself lacks 921
  interior quarters (1.6% of the span, 380 scrips); under the no-substitution
  reading each blanks a name's TTM for up to a year. **Point in time:** the
  stores truncated at 2016 and at 2021 agree on all 516,464 shared values,
  and a rebuild is byte-identical.
