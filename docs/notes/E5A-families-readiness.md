# E5-A families — readiness (2026-09-30)

**A1: READY TO LOCK once L's reads are in (job 15) and §4 is confirmed.
A3: READY TO LOCK once §4 is confirmed. A2: NOT READY — readiness only
(§3).** No family run exists.

**Change-log entries that apply** (E5-A §14): 2026-09-27 (rewrite);
2026-09-28 (D1, D3–D9; A2's precondition replaced); 2026-09-29 (D2: stack
E1 + E1d); 2026-09-29 (A0 LOCKED, `lock/E5-A`); 2026-09-30 (A1 plan
decisions; **§6(b) amended**: per flag × subtype, NOT_EVENT excluded);
2026-09-30 session 10 (**A0 verdict recorded; A1 reader decisions** — L
reads DEFAULT, FORENSIC_AUDIT, REGULATORY_ACTION; K's events are UNCLEAR;
UNCLEAR its own subtype). A1 plan: `docs/notes/A1-reader-plan.md` §5 items
7–10.

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

## 3. A2 — positioning (§6(c)): readiness only

- **Data:** `bse_shareholding/summary.parquet`, 194,035 scrip-quarters
  2010-03 → 2026-06; 135,098 `ok`, 58,937 `unavailable`; promoter shares,
  percent, pledged shares and shares outstanding. The quarter pairing,
  usable dates and split/bonus restatement exist (`data/positioning.py`,
  E2-D1). §14 2026-09-28 fixes the columns: Δ promoter shares and Δ promoter
  percent (1 and 2 quarters) and a flag for a change in total shares with no
  recorded action; nothing thresholded.
- **Decisions needed (Aarsh) before a build:**
  1. **Pledge invocations** (§6(c)) have no source: only ~41 BSE headlines
     2014–2026 mention one. Options: (a) drop the column, declared; (b) a
     proxy — a quarter's fall in pledged shares together with a fall in
     promoter shares; (c) read SAST Reg 31 attachments (a data build).
  2. **The unexplained share-count fall** (E2-D1 readiness §3: 16% of
     large moves): A2's "change in total shares with no recorded action"
     column carries it as a feature, so no cleaning is needed — **confirm**.
  3. Denominator and dating readings as E2-D1 readiness §4 1–6 — confirm
     they carry over unchanged.

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

## 5. For Aarsh

1. RESULTS_DELAY: K (rule as written, 88.0% < 88.5%) or L (instruction)?
   L would add 269 events (~15 min) to job 15.
2. Run job 15; then Claude builds the A1 stores and reports.
3. Confirm A3 §4 and A1's readings (censored months-since; coverage from
   2010 window) and lock A1 and A3 (append to E5-A §14, tags
   `lock/E5-A-A1`, `lock/E5-A-A3`); the A0-identity check first.
4. A2: §3's three decisions.
