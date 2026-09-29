# Final regression — all six re-classified (2026-09-29)

Computed by `classify`, never typed; `verdict.json` written into each
validation sweep. Full sweeps at `c6ef67e` (RUNNING.md job 6; markers
`experiments/_regress/*.json`). Sealed period untouched. Locked spans verified
2026-09-28.

**Change-log entries that apply:** E1 §15 — 2026-09-17 ADV guard; 2026-09-21
buy sizing net of costs; 2026-09-27 determinism; 2026-09-27 accounting
corrections a–d; 2026-09-27 D1/D2 data repairs; 2026-09-28 declared choices
confirmed; 2026-09-28 measurement fixes (D2 transition data errors, BE-stint
dividends, payment dates declared, sorted dicts, run identity). Each
experiment's own change log as cited in its earlier verdict note (E1d
2026-09-24; E1c 2026-09-21 ×4; E2-A §8a event study reused from 2026-09-25,
since it reads prices only and no engine path).

| experiment | verdict | GATE dev (Δ CAGR / Δ MaxDD, rows) | GATE val | base dev | base val |
|---|---|---|---|---|---|
| E1 | **INCONCLUSIVE** (C1 dev −1.53 pp, val +6.89 pp) | — | — | 6.53 / 59.29 | 21.66 / 48.76 |
| E1b | **INCONCLUSIVE** | ✓ +1.87 / −4.33, 11/14 | G2, G3 fail; −5.76, 1/13 | 8.40 / 54.96 | 15.90 / 46.14 |
| E1-P | **INCONCLUSIVE** | G1, G3 fail; +0.40, 1/6 | G3 fails; +0.52, 3/6 | 6.93 / 60.10 | 22.19 / 47.99 |
| E1c | **REJECT** | G1–G3 fail; −0.63 / +11.91 | G2, G3 fail; −3.12 | 5.90 / 71.20 | 18.55 / 35.86 |
| **E1d** | **ADOPT** | ✓ +1.53 / −4.55, 11/12 | ✓ +4.54 / −5.80, 10/11 | 8.06 / 54.74 | 26.21 / 42.96 |
| E2-A | **REJECT** (GATE and §8a) | G1, G3 fail; +0.16, 0/13 | G1–G3 fail; −3.85 | 8.28 / 38.32 | 44.89 / 8.47 |

No verdict changed from 2026-09-27. E2-A's windows are its own (2017–19 /
2020–21); its stack is E1 base on those windows (8.13 / 39.54, 48.74 / 7.36).

**Stack: E1 + E1d from 2026-09-29** (GATE; E1d §7 caveat travels: its
hypothesis came from E1c's S6 on these years). **Mandate not met:** E1d base
− B5 is −5.67 pp in development and +3.77 pp in validation.
