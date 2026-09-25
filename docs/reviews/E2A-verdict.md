# E2-A — verdict: REJECT (2026-09-25)

Charter `docs/strategies/E2-A.md`, **LOCKED 2026-09-25** (span hash in
`docs/notes/E2A-readiness.md` §0). Computed by `classify.classify_e2a`,
written to
`experiments/E2-A/sweeps/e2a_validation-da6040804aa08fa8/verdict.json`.

Sweeps: development `e2a_development-9098271bff563780`, validation
`e2a_validation-da6040804aa08fa8`. STACK = E1 base re-run on **each of
E2-A's own windows**, because E2-A's window is not E1's.

**Change-log entries that apply** (CLAUDE.md non-negotiable 1): E2-A §3 as
amended 2026-09-24 (`DissemDT` else `NEWS_DT`, after-15:30 to either); §6,
§7, §8 and §8a as amended 2026-09-25 (window on input availability, S13
removed, lead-time extra, §8a pre-registered and required for ADOPT, and
§8a's truncation rule).

## The verdict

**REJECT.** GATE fails in both periods and §8a fails. ADOPT required both
(§8a), and neither was met.

### GATE — fails in both periods

| | development 2017–2019 | validation 2020–2021 |
|---|---|---|
| E2-A base | 11.85% / 33.18% | 41.84% / 8.41% |
| E1 base, same window | **14.60% / 31.37%** | **50.04% / 7.19%** |
| G1 | ✗ −2.75 pp **and** 1.81 pp deeper | ✗ −8.20 pp **and** 1.22 pp deeper |
| G2 | **✗** | **✗** |
| G3 | ✗ 1 of 13 | ✗ 0 of 13 |
| G4 | ✓ 1.69 vs 1.64 | ✓ 1.13 vs 1.16 |

REJECT is reached the strict way: **G1 fails in both periods and G2 is
violated in both.** Excluding flagged names cost return *and* deepened the
worst fall, in both periods, which is the opposite of the hypothesis on
both counts.

### §8a — the sign reverses between periods

| period | cohorts | events | mean 6-month excess | t (Newey-West, 5 lags) |
|---|---|---|---|---|
| 2017–2019 | 29 | 132 | **−7.73%** | **−3.14** |
| 2020–2021 | 18 | 125 | **+12.16%** | **+3.48** |

The pass condition, written into the charter before the study was
implemented, required negative with t < −2 in 2017–2019 **and** negative in
2020–2021. The first half is **met**. The second is not merely unmet — it is
significantly the wrong way round.

Development was monotonic in horizon (−3.50% at 1m, −6.52% at 3m, −7.73% at
6m), which is what a real effect looks like. Validation was monotonic the
other way.

Edge exclusions, counted per §8a's truncation rule (no forward return reads
a price past the period end): development 4 / 34 / 49 at 1 / 3 / 6 months;
validation 0 / 11 / 26.

## Why this is a more useful REJECT than GATE alone would have been

GATE says "acting on flags lost money". On its own that is consistent with
two very different worlds: flags carry no information, or they carry
information the rule cannot convert. §8a separates them, and the answer is
neither of the simple ones.

**In development the flags carried real information** — −7.73% with t =
−3.14, monotonic — and the rule *still* lost 2.75 pp. So even where the
signal was genuine, exclusion was the wrong way to use it: E1 holds 25 of
~500 names, so a flagged name is usually not held, and excluding it mostly
changes which unflagged name is bought instead.

**In validation the information reversed.** Flagged names beat their matched
peers by 12.16% with t = +3.48. 2020–2021 was the recovery, and distressed
names rebounded hardest. A rule that avoids them avoids the rebound.

That is the finding: **the flags' information is not stable in sign, and
even when it was right the rule could not convert it.**

## Per flag, both periods — reporting only, no decision

6-month excess; t is Newey-West on the monthly cohort series and is `n/a`
where there are too few cohorts to support one. **No flag is dropped or
weighted on this** (§4, §8a).

| flag | dev n | dev mean | dev t | val n | val mean | val t |
|---|---|---|---|---|---|---|
| AUDITOR_RESIGNATION | 10 | −13.51% | −3.11 | 11 | +5.85% | n/a |
| REGULATORY_ACTION | 47 | −12.71% | −2.84 | 15 | +21.19% | +5.78 |
| RATING_DOWNGRADE | 48 | −8.68% | −2.63 | 40 | +8.68% | +1.95 |
| INSOLVENCY | 14 | −8.44% | −2.09 | 20 | +25.00% | +1.72 |
| FRAUD | 21 | **+9.64%** | **+4.02** | 11 | +12.95% | n/a |
| FORENSIC_AUDIT | 2 | +8.76% | n/a | 3 | +18.70% | n/a |
| PROMOTER_ENCUMBRANCE | — | — | — | 42 | +7.42% | +0.74 |
| DEFAULT | — | — | — | 1 | +22.57% | n/a |
| RESULTS_DELAY | — | — | — | — | — | — |

Two things to note without acting on either. **FRAUD ran the wrong way in
both periods** (+9.64% with t = +4.02 in development), which is the one
flag whose sign is consistently opposite to the hypothesis. And
**PROMOTER_ENCUMBRANCE contributes nothing to development** — it is
structurally absent before 2019, exactly as the readiness note predicted,
so 42 of its events fall in validation and none in development.

The sweep rows agree with the per-flag table where they can: development S8
(RATING_DOWNGRADE removed) returns 16.33% / 29.24%, better than E1 base
itself, and S9/S10/S11 (RESULTS_DELAY, FORENSIC_AUDIT, DEFAULT) are
identical to base because those flags never fire in that window.

## By momentum quintile — reporting only, and the most interesting table here

Pooled 6-month excess split by the flagged name's 12-1 momentum quintile at
the event month-end. **Quintile 4 is the one that matters for this fund:
the names a momentum portfolio actually holds.**

| quintile | dev n | dev mean | dev t | val n | val mean | val t |
|---|---|---|---|---|---|---|
| 0 (weakest) | 45 | −9.16% | −2.81 | 37 | +11.32% | +3.69 |
| 1 | 27 | −6.80% | −1.16 | 22 | +11.14% | +1.53 |
| 2 | 27 | −9.92% | −2.56 | 19 | +22.29% | +5.11 |
| 3 | 18 | +5.48% | +1.97 | 29 | +7.86% | +1.09 |
| **4 (strongest)** | **15** | **−16.68%** | **−4.53** | **18** | **−1.02%** | **−0.20** |
| top quintile only | 15 | −16.68% | −4.53 | 18 | −1.02% | −0.20 |
| all other quintiles | 117 | −6.39% | −2.40 | 107 | **+13.13%** | **+4.00** |

**Validation's positive pooled result comes entirely from names a momentum
fund does not hold.** In the top quintile flagged names never outperformed:
sharply negative in development (−16.68%, t = −4.53, the strongest cell in
the whole study) and merely flat in validation (−1.02%, t = −0.20). The
+12.16% pooled figure is driven by the lower four quintiles at +13.13%.

**This does not change the verdict and must not.** §8a's condition is on the
pooled result, it was written before the study, and re-reading it on a
subset after seeing the numbers is exactly what `GATE.md`'s "what never
changes an outcome" forbids. The cells are also thin — 15 and 18
observations — so the point estimates carry little weight on their own.

It is recorded because it is the one result that would justify a *new*
charter: a rule conditioned on flags **within** the names momentum already
selects is a different hypothesis from the one E2-A tested, and it has not
been tested. Any such charter must declare that it was suggested by this
table, on these years.

## §8's lead-time extra

**3 holdings were suspended or delisted in development and none carried a
prior flag.** Three is far too few to mean anything; I read it as no
evidence, not as evidence of no warning. The extra is worth keeping for a
longer window.

## MANDATE — information only

| | development | validation |
|---|---|---|
| §3 | ✗ (rows 0/13) | ✓ |
| §5 vs B5 | ✗ +0.72 pp | ✗ −1.77 pp |

Not met. E2-A is a change on the stack rather than a candidate base, so E1
§13's C1–C4 are not reported.

## The stack is unchanged, and the rules do not move

**E1 base remains the adopted stack.** Per §4, changing a rule after the
first run invalidates the results, so **E2-A stays exactly as locked** and
any fix is a new experiment with a new charter. Per `GATE.md`, a REJECT is
written down and not retried with new numbers.

A precision audit of the keyword rules is drawn and awaiting Aarsh's labels
(`docs/data/flag_audit.md`, 251 events, masked, no returns). It asks whether
the rules fire on the events they name — a question about the *classifier*,
not about E2-A's verdict, which stands either way.

The sealed period was not touched; `research/journal.jsonl` is still absent.
