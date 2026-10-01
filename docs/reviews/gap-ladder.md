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

## 3. Results

Pending (jobs 34–37).
