# E3-R — verdict: REJECT (GATE vs E1 + E1d)

**2026-09-30.** Computed by `classify_e3r` (both periods), never typed; saved
as `experiments/E3-R/verdict.json`. Development detail:
`docs/reviews/E3-R-development.md`.

**Change-log entries that apply** (E3-R §11): 2026-09-25 (prediction);
2026-09-27 (Aarsh's four decisions); 2026-09-27 (e) (NIFTYBEES buy split);
2026-09-29 (stack E1 + E1d); 2026-09-29 (LOCKED, `lock/E3-R` → c06c6af,
NIFTYBEES data fix); 2026-09-30 (STACK source: the c6ef67e E1d sweeps,
reproduced IDENTICAL at the tag). For the stack: E1 §15, E1d §10.

## Runs

| | directory | code |
|---|---|---|
| E3-R development | `E3-R/sweeps/development-7abfb3d39c34e018` | `lock/E3-R`, `D:\pl_runs\E3-R` |
| E3-R validation | `E3-R/sweeps/validation-d1e612b69131648d` | same |
| STACK | `E1d/sweeps/development-924cec1bb3dd9ff9`, `E1d/sweeps/validation-a0e0f5aa78dc160f` (base rows) | c6ef67e, IDENTICAL at `lock/E3-R` |

## GATE

| | development 2007–16 | validation 2017–21 |
|---|---|---|
| E3-R base | 6.82% / 54.16% | 19.62% / 48.08% |
| stack base | 8.06% / 54.74% | 26.21% / 42.96% |
| CAGR gap | −1.24 pp | −6.59 pp |
| MaxDD gap | −0.58 pp | +5.12 pp |
| G1 | **no** | **no** |
| G2 | **no** | **no** |
| G3 | no, 1 / 11 | no, 0 / 11 |
| G4 | yes | yes (1.65 vs 1.78) |

G1 fails in both periods and G2 fails in both → **REJECT**.

Validation rows (against the stack's base row):

| row | CAGR | MaxDD | Sharpe |
|---|---|---|---|
| base | 19.62% | 48.08% | 0.97 |
| S1 cautious 30% | 17.59% | 49.01% | 0.89 |
| S2 cautious 70% | 21.61% | 47.39% | 1.03 |
| S3 no selling in cautious | 22.40% | 47.73% | 1.05 |
| S4 V only | 20.00% | 43.34% | 0.93 |
| S5 B only | 20.49% | 48.08% | 1.00 |
| S6 two gears | 26.01% | 45.97% | 1.11 |
| S7 high gear into stack names | 26.58% | 45.45% | 1.11 |
| S8 India VIX | 20.77% | 41.59% | 1.08 |
| S9 costs ×2 | 19.19% | 48.47% | 0.94 |
| S10 sell-down at once | 18.83% | 47.74% | 0.94 |

## MANDATE: not met

| | development | validation |
|---|---|---|
| §3 MaxDD − B2 / CAGR − B2 | −9.37 / −1.24 pp | +10.14 / +4.85 pp |
| §3 rows holding | 0 / 11 | 1 / 11 (S8) |
| §5 CAGR − B5 | −6.92 pp | −2.82 pp |

## §8 extras, validation (base row)

| year | cautious | normal | high | E3-R equity share | stack equity share |
|---|---|---|---|---|---|
| 2017 | 0 | 12 | 0 | 62.5% | 62.5% |
| 2018 | 1 | 11 | 0 | 94.5% | 94.0% |
| 2019 | 4 | 6 | 2 | 63.0% | 66.4% |
| 2020 | 4 | 7 | 1 | 82.4% | 73.9% |
| 2021 | 0 | 12 | 0 | 91.4% | 97.0% |

Worst fall within each episode: 2018 −25.50% (stack −26.73%); 2020 −34.10%
(stack −31.72%). False alarms: **9 of 9** cautious months (2018-10, 2019-01,
2019-02, 2019-07, 2019-08, 2020-03 to 2020-06). Gear sell-downs realised
−₹2.48 lakh short-term and +₹8.90 lakh long-term.

**Prediction recorded 2026-09-25:** "E3-R passes only if the high gear's
recovery return exceeds the cautious gear's cost in 2017–2021." It did not
pass; the base row trails the stack by 6.59 pp.

## Decisions needed (Aarsh)

1. Record the verdict: STATE (REJECT 3), ROADMAP (E3-R off the forward list).
