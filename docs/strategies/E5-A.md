# E5-A — Learned cross-sectional ranker, one information family at a time

Status: **DRAFT** (rewritten 2026-09-27 from `E5.md` §2, per the external
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
  engine's own E1 §9 rules (adjusted prices, dividends as cash on ex-date,
  a name whose rows stop exits at its last close on the session after its
  last row). Minus the median of the same quantity over U(M), the stack's
  E1 §2 universe at M. The model is fit on each cross-section's percentile
  of that excess return, centred at 0.
- **Rows.** One per (ISIN, M) with the ISIN in U(M). No name outside U(M)
  enters training.
- **Every label row stores** `label_start` (session after M), `label_end`
  (the session whose open closes the label, or the delisting exit
  session), and `observable_at` (the open of `label_end`; for the
  cross-section median, the latest `observable_at` in U(M)).
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

- LightGBM regression, one model per horizon, `deterministic=true`, fixed
  thread count and seeds (seed 20260927); the manifest records the
  LightGBM version, every hyperparameter and the SHA-256 of each fitted
  model file. Requires adding `lightgbm` to CLAUDE.md 7 **[D 3]**.
- **Refit once a year** at the December month-end R; that model scores
  the twelve month-ends that follow **[D 5]**. Training is expanding:
  every row observable by R (§4).
- A model is fitted only if its training set holds ≥ 12 month-end
  cross-sections for every horizon; before that, the stack's own rank is
  used. This affects 2007 only, which is exploratory (§8).
- **Tuning, once, before A0 locks** **[D 4]**: on the panel truncated at
  2010-12-31, walk-forward predictions for 2008–2010 are scored by mean
  monthly Spearman rank IC against their own labels, averaged across the
  three horizons, using only labels observable by 2010-12-31. Grid, eight
  points: `num_leaves` {7, 31} × `min_data_in_leaf` {200, 1000} ×
  `learning_rate` {0.02, 0.05}; fixed: 300 trees, `bagging_fraction` 0.8
  every iteration, `feature_fraction` 0.8. Highest IC wins; within 0.005,
  fewer leaves, then larger `min_data_in_leaf`. **The chosen point is
  written into §5 of this charter before the lock**, so the lock hashes it.
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
predictions over U(M). Its descending rank **replaces the stack's ranking
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
