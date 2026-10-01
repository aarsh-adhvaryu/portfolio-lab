# E5-A families — readiness (2026-09-30; updated 2026-10-01)

**2026-10-01: A1 and A3 LOCKED** (`lock/E5-A-A1`, `lock/E5-A-A3` → `6a29dde`;
A0-identity IDENTICAL, E5-A §14). **A2 BUILT, READY TO
LOCK** once §3's build readings are confirmed. No family run exists.

**Change-log entries that apply** (E5-A §14): 2026-09-27 (rewrite);
2026-09-28 (D1, D3–D9; A2's precondition replaced); 2026-09-29 (D2: stack
E1 + E1d); 2026-09-29 (A0 LOCKED, `lock/E5-A`); 2026-09-30 (A1 plan
decisions; **§6(b) amended**: per flag × subtype, NOT_EVENT excluded);
2026-09-30 session 10 (**A0 verdict recorded; A1 reader decisions** — L
reads DEFAULT, FORENSIC_AUDIT, REGULATORY_ACTION; K's events are UNCLEAR;
UNCLEAR its own subtype); **2026-10-01 session 11** (RESULTS_DELAY K;
A1 and A3 readings confirmed; **§6(c) amended**: pledge invocations dropped,
pledge share added; hypotheses for A1–A3, **E5-A-ALL** and **A5** registered).
A1 plan: `docs/notes/A1-reader-plan.md` §5 items 7–10.

## 1. What was built (shared)

| piece | where |
|---|---|
| family store beside A0's (`features_a1/a3.parquet`, `meta_a1/a3.json`), built over A0's verified U(M), SHA-checked, refuses a different A0 store, builder code or config | `ranker/family.py`, `tools/build_e5a_family.py` |
| §6 [D 6] activation: family model from refit R only if every horizon's training set has ≥ 36 cross-sections with the family available for ≥ 50% of U(M); otherwise **A0's decisions exactly** | `walk.Walk.family_active`, `walk.a0_spec` |
| runner loads A0's store checked against the A0 part of the config, then the family's | `backtest/runner.py` |
| §11 extras: family-active decisions, share of buy value without family coverage | `walk.SweepScores.row_extras` |
| configs = A0's byte for byte except `family`, `features`, `[e5a.activation]`, the family block and `output_dir` (`experiments/E5-A/<fam>`) | `configs/e5a_a1.toml`, `configs/e5a_a3.toml` |

A0's code path is unchanged (a spec with no family columns takes the old
branch); `classify_e5a(..., candidate="A1")` already gives the incremental
(vs A0, row by row) and adoption verdicts. Tests: `tests/test_e5a_families.py`
(10). `pytest -q`: 704 passed. **The lock must show A0 reproduces IDENTICAL
at the family's tag** (as E3-R's STACK did), since the family tag carries
new code.

## 2. A1 — issuer events (§6(b))

- **Columns (72):** per flag × subtype, counts over 1, 3, 12 month-ends and
  month-ends since the last. K's six flags: UNCLEAR only (24). L's three:
  AT_COMPANY, AGAINST_COMPANY, RELATED_ENTITY, UNCLEAR (48).
- **Reads:** L over its three flags, 2010-01-01 → 2021-12-31 (**710
  events**; nothing in the sealed period), same prompt, masking and digest
  as the contest. Probe: 10 events in 53 s (5 NOT_EVENT, 4 AT_COMPANY, 1
  UNCLEAR). **Job 15, Aarsh.** The builder refuses while any is unread.
- **Real data** (all-K smoke; the final build waits for job 15):
  development store in 7 s; covered share of U(M) 88% in 2011 → 97% in
  2016. **Activation: first at the 2014-12 refit** (h12 has exactly 36
  covered cross-sections), so **2011–2014's development decisions are A0's
  by construction** and A1 decides 24 of 72. Validation: active throughout.
- **Finding:** in U(M) 2011–16 DEFAULT and PROMOTER_ENCUMBRANCE have **zero**
  events and RESULTS_DELAY one (their disclosure regimes start around
  2019); INSOLVENCY 47 event-months. Those columns are constant in
  development training.

- **Job 15 done (2026-09-30):** 710 of 710 read. L's subtypes, events to
  2021: DEFAULT 260 AT_COMPANY / 5 RELATED / 3 UNCLEAR / 3 NOT_EVENT;
  FORENSIC_AUDIT 19 / 2 AGAINST / 5 RELATED / 9 UNCLEAR / 2 NOT_EVENT;
  REGULATORY_ACTION 171 / 9 AGAINST / 36 RELATED / 81 UNCLEAR / **105
  NOT_EVENT (26%)**. **A1 stores built:** `e5a_development` (11 s; events to
  2016: REGULATORY_ACTION 62 AT_COMPANY, FORENSIC_AUDIT 2, DEFAULT 0) and
  `validation` (17 s).

## 3. A2 — positioning (§6(c) as amended 2026-10-01): BUILT

- **Columns (9)** (`ranker/holdings.py`, `configs/e5a_a2.toml`): promoter
  shares change 1q, 2q (restated, ÷ later shares outstanding, + = buying);
  promoter percent change 1q, 2q (points); pledged % of promoter holding,
  level and 1q, 2q change (points); unexplained shares-outstanding change
  1q, 2q (later ÷ restated earlier − 1). Pledge invocations dropped.
- **Stores built** (`e5a_development` 33 s): coverage of U(M) 86% (2011) →
  97% (2016). **Activation at the 2014-12 refit** (h12: 31 covered
  cross-sections at 2013-12, 43 at 2014-12), so 2011–2014 decisions are
  A0's, as for A1. Tails as E2-D1 found: promoter-shares change down to
  −4.7 (an unexplained share-count fall), unexplained change up to +19;
  carried, not cleaned (decision 1d).
- **Build readings for A2's lock to confirm** (none in the charter):
  1. The unexplained share change is a **value**, not §14 2026-09-28's flag
     (a flag needs a threshold).
  2. Sign: promoter-shares change is E2-D1's `sold_frac` negated.
  3. Each column needs its own pair; the level (pledge %) needs only the
     latest usable quarter. Two scrips on one ISIN: the lower code is read.
  4. Restatement uses the engine's split/bonus rule for shares outstanding
     too (E2-D1 readiness §4 item 1).
- Tests: 4 (lookahead and 15:30, restatement, no substitution, columns).

## 4. A3 — world exposure (§6(d))

- **Columns (16):** β to Brent, USDINR, US 10-year, India VIX, net FII
  equity flow; β × the factor's 1- and 3-month change; β to the Nifty 500.
  36 month-ends, ≥ 24 pairs (`signals/shock_betas.py`).
- **Built:** `e5a_development` (43 s) and `validation` (55 s) stores.
  First available: Brent, USDINR, US10Y, Nifty 500 2006-01; VIX 2010-03;
  FII 2011-11 (as E2-B readiness §1). Coverage 84–99% of U(M).
  **Activation: from the 2010-12 refit**, so A3 decides every development
  and validation month.
- **Build readings for the lock to confirm** (none is in the charter):
  1. Transforms: Brent, USDINR `pct`; US10Y, VIX `diff`; FII monthly `sum`
     of daily net equity (Equity / Sub-total); Nifty 500 TRI `pct`.
  2. 3-month change: level ratio − 1, level difference, or 3-month sum.
  3. **Timing:** FRED Brent, USDINR (noon New York), US10Y and NSDL's FPI
     report print after 15:30 IST, so each is usable from the next
     calendar day; VIX and the Nifty 500 TRI on their own date.
  4. Stock returns month-end to month-end on adjusted close, no fill.

## 5. For Aarsh (2026-10-01)

1. Run RUNNING jobs 17–18 (A1, A3 development; locked 2026-10-01).
2. Confirm A2's build readings (§3) to make it ready to lock.
3. E5-A-ALL: how activation reads with three families (§6).
4. A5: the dating rule (`docs/data/bse_results_finding.md` §3), then the pull
   (job 23) and a §6(f) entry fixing A5's columns.

## 6. Session 11 (2026-10-01)

- Decisions 1a–d recorded in E5-A §14. Hypotheses registered (§14): A1,
  A2, A3, **E5-A-ALL** (A0 + A1–A3 columns; amends §3's "never combined")
  and **A5** valuation (a family, not in ALL). STATE count: 5 registered.
- **A0-identity tool:** `tools/e1_identity.py` now scores an E5-A config
  through `runner.e5a_scores` (extracted from `runner.main`, the sweep's
  own path). A1, A2 and A3 share one candidate commit, so one check per
  period covers every family tag. `family.py` changed (A2), so the A1 and
  A3 stores were rebuilt at that commit.
- **Open for E5-A-ALL's lock:** how activation reads with three families
  (each family's columns from its own activation refit, or one model from
  the refit where all three are active, 2014-12) — Aarsh's.
- **A0 store and later code:** `engine.py` (in the A0 store's builder hash)
  moved after `lock/E5-A` in E3-R's gears path only, so every later commit
  refused the store. `build_e5a_features.py --verify` rebuilt both periods
  byte for byte at `a01be98` and recorded the hash; `store.check` accepts
  it. Then A0-identity IDENTICAL at `6a29dde` and A1, A3 locked there.
