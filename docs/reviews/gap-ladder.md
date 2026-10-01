# Gap ladder — E1d and E5-A A0 against B5 (DIAGNOSTIC, NOT PROMOTABLE)

**Registered 2026-10-01 (session 13), before any ladder run.** Not an
experiment: no charter, no verdict, not counted in STATE's tally; `classify`
cannot read it, and no rule changes because of it (CLAUDE.md rule 3).
Tool `tools/gap_ladder.py`; jobs 34–37 in `docs/RUNNING.md`.

## 1. What it measures

The gap diagnosis (`gap-diagnosis.md`) changed one thing per row, so its rows
overlap and do not add up. The ladder adds the frictions **cumulatively, in a
fixed order**, so the steps sum exactly from the frictionless picks to the
base row. Strategies and periods: **E1d** (development 2007–16, validation
2017–21) and **A0** (`e5a_development` 2011–16, validation).

| rung | adds | trend | six-buy cap | costs | tax | how |
|---|---|---|---|---|---|---|
| 0 picks | picks only, frictionless and fully invested | — | — | 0 | 0 | computed (as the gap diagnosis row), ranks read off rung M's decisions |
| M mechanics | engine fills (next open, ADV skip, liquid sleeve residue) | off | off | 0 | 0 | engine |
| 1 brake | + trend brake | as chartered | off | 0 | 0 | engine |
| 2 cap | + six-buy cap | as chartered | as chartered | 0 | 0 | engine |
| 3 costs | + costs | as chartered | as chartered | as chartered | 0 | engine |
| 4 tax | + tax = **the base row** | as chartered | as chartered | as chartered | as chartered | engine |

Rung M is reported between 0 and 1 so that the brake step measures the brake
and not the difference between a computed series and the engine. Rung 0 reads
ranks from rung M (trend off, so every month has ranks); the gap diagnosis
row read the base run's and so froze its names in RISK_OFF months. Rung 4 must
reproduce the gap diagnosis base row (E1d development 8.06% / 54.74%); if it
does not, the run is faulty and is not read.

Each step reports the change in **terminal wealth, XIRR, CAGR and max
drawdown**, and the share of the base row's gap to B5 it accounts for:
(rung before − rung after) ÷ (B5 − base), per measure. B5 as in every sweep.

## 2. Pre-registered rule (Aarsh, 2026-10-01)

Read on **E1d, development, CAGR**:

> brake + cap share = (CAGR at rung M − CAGR at rung 2) ÷ (B5 CAGR − base
> CAGR), from the run's own figures (STATE: 13.73% − 8.06% = 5.67 pp).

- **≥ 60%:** Aarsh may register **one final stack experiment** targeting that
  component (brake, cap or both, whichever the steps show).
- **< 60%:** the research phase **ends** and the fallback build begins
  (`docs/plans/fallback.md`).

The other three runs (E1d validation, A0 both periods) are reported and do not
enter the rule. Nothing in §1 or §2 changes after a run is read.

## 3. Results (jobs 34–37, 2026-10-01, all at `5553d71`, clean)

Read off each run's `summary.md`. Rung 4 reproduces the base row in all four
(E1d 8.06% / 54.74% and 26.21% / 42.96%; A0 12.59% / 14.46% and 7.51% /
26.69%), so all four are read. Runs: `experiments/E1d/diagnostics/gapladder-development-863a39803e5bbffe`,
`gapladder-validation-3adf773132a0743e`; `experiments/E5-A/diagnostics/gapladder-e5a_development-1e80490d6ca3a62a`,
`gapladder-validation-0606eeb8fc5ccb5b`.

Rungs, CAGR / MaxDD (terminal ₹cr):

| rung | E1d dev | E1d val | A0 dev | A0 val |
|---|---|---|---|---|
| 0 picks | 13.49% / 77.01% (1.766) | 27.40% / 42.51% (0.646) | 16.09% / 21.98% (0.611) | 26.22% / 32.00% (0.608) |
| M mechanics | 8.09% / 77.64% (1.145) | 39.20% / 42.07% (0.957) | 15.84% / 21.91% (0.639) | 16.62% / 35.19% (0.476) |
| 1 brake | 14.28% / 53.75% (1.236) | 33.32% / 39.62% (0.805) | 16.00% / 14.91% (0.602) | 17.07% / 27.41% (0.490) |
| 2 cap | 9.59% / 54.53% (1.012) | 29.92% / 42.09% (0.746) | 14.52% / 14.35% (0.559) | 9.77% / 25.65% (0.420) |
| 3 costs | 8.96% / 54.67% (0.984) | 29.61% / 42.66% (0.744) | 14.43% / 14.42% (0.560) | 9.17% / 26.28% (0.413) |
| 4 tax = base | 8.06% / 54.74% (0.915) | 26.21% / 42.96% (0.656) | 12.59% / 14.46% (0.521) | 7.51% / 26.69% (0.387) |
| B5 | 13.73% / 70.15% (1.353) | 22.44% / 38.14% (0.591) | 17.85% / 22.63% (0.619) | 22.44% / 38.14% (0.591) |

Steps, Δ CAGR pp (share of the base's gap to B5; positive = widens a
shortfall). XIRR, terminal and MaxDD per step are in each `summary.md`.

| step | E1d dev (gap −5.68) | E1d val (gap +3.77) | A0 dev (gap −5.26) | A0 val (gap −14.93) |
|---|---|---|---|---|
| picks → mechanics | −5.40 (+95%) | +11.80 (+313%) | −0.25 (+5%) | −9.60 (+64%) |
| mechanics → brake | +6.19 (−109%) | −5.89 (−156%) | +0.16 (−3%) | +0.45 (−3%) |
| brake → cap | −4.69 (+83%) | −3.39 (−90%) | −1.49 (+28%) | −7.30 (+49%) |
| cap → costs | −0.63 (+11%) | −0.31 (−8%) | −0.08 (+2%) | −0.60 (+4%) |
| costs → tax | −0.91 (+16%) | −3.41 (−90%) | −1.84 (+35%) | −1.66 (+11%) |
| **brake + cap** | **−26%** | −246% | +25% | +46% |

### The rule (§2)

**E1d development, brake + cap = (8.09% − 9.59%) ÷ 5.68 pp = −26%, below
60%.** Under the registered rule **the research phase ends and the fallback
build begins** (`docs/plans/fallback.md`). No final stack experiment is open.

### Facts the rule does not weigh (nothing changes because of them)

1. In E1d development the brake **adds** 6.19 pp CAGR (MaxDD 77.6% → 53.8%)
   and the cap takes 4.69 pp back; together they narrow the gap slightly.
2. The largest E1d development step is picks → mechanics (−5.40 pp, 95%),
   yet in E1d validation the same step is +11.80 pp. A step that large and
   that unstable in sign says the computed picks row and the engine differ in
   more than fills (e.g. which names are held, unpriced names held flat), so
   rung 0 is not a reliable floor. It does not enter the rule.
3. The cap is the largest single drag in A0 validation (−7.30 pp) and in E1d
   validation (−3.39 pp); costs never exceed 0.63 pp anywhere.
