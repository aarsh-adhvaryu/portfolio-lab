# STATE — verdicts and where things stand

One page. Updated 2026-10-01 (session 11: E5-A families registered). The narrative is in `docs/HANDOFF.md`; the
order and reasons in `docs/ROADMAP.md`; the rules for judging in
`docs/strategies/GATE.md` (adoption) and `docs/MANDATE.md` (ADVANCE).

**Figures below are final under every correction to date** (regression at
`c6ef67e`, full sweeps, classified 2026-09-29:
`docs/reviews/regression-2026-09-28-verdicts.md`). Change-log entries that
apply: E1 §15 2026-09-21, 2026-09-27 (determinism; corrections a–d; D1/D2),
2026-09-28 (declared choices confirmed; measurement fixes). No verdict changed.

**Adopted stack: E1 + E1d** (from 2026-09-29; E1d ADOPT by GATE, confirmed by
the final regression; E1d §7 caveat travels). Sealed period (2022–2025) never
opened; `research/journal.jsonl` absent.

## How many experiments have been tested

`GATE.md`'s parallel-running rule 3. **Every added test raises the chance of
a lucky pass**, and from 2026-09-26 several may run at once, which raises it
faster. The sealed period is the correction — seen once, by one stack — and
this count is what a reader needs in order to weigh any pass at all. A stack
that passes on the twentieth attempt is not the evidence a stack that passed
on the second would be.

| | |
|---|---|
| **experiments with a computed verdict** | **8** |
| ADOPTED | **1** (E1d; stack E1 + E1d from 2026-09-29) |
| REJECT | 3 (E1c, E2-A, E3-R) |
| INCONCLUSIVE | 4 (E1, E1b, E1-P, E5-A A0) |
| **registered, no result yet** (2026-10-01, E5-A §14) | **5**: E5-A A1, A2, A3, **E5-A-ALL**, A5 |
| sealed-period reveals used | **0 of 1** |
| stacks meeting MANDATE §3 and §5 | **0** |

Locked: **E5-A A1, A3** (`lock/E5-A-A1`, `-A3`) and **A2, E5-A-ALL** (`lock/E5-A-A2`, `-ALL`), all 2026-10-01. Jobs 17–20 (A1, A3 development; gap E1d) reported done by Aarsh, outputs not yet read. **Running: job 23** (BSE results pull), started 2026-10-01 by Aarsh alongside 17–20. Jobs 21–22 (gap, A0): recorded when Aarsh confirms them. Next: jobs 24–25 (A2, ALL development). **Built and ready to lock** (2026-09-27):
E2-D1, E2-D2 — each note's last section says what the lock must settle.
Readiness notes: E2-B, E3, E5-A (decisions taken 2026-09-28 bar D2, now settled: A0 against E1 + E1d; build next). Drafts: E1-S, E2-E.

**Closed or parked, not counted as tested** (2026-09-27, Aarsh): **E2-C
closed, NOT RUN** — its trigger fired only in months already RISK_OFF, so it
equals the stack; thresholds not loosened. **E2-D2 parked** until E2-D1's
verdict.

**E2-D was split in two on 2026-09-27** (Aarsh): **E2-D1** promoter selling
(2010–2016 / 2017–2021) and **E2-D2** insider selling from PIT (2017–2019 /
2020–2021), because the PIT input exists only from 2016 and one charter
would have tested different rules in its two periods. **The split adds one
to the count of experiments that will be tested**: when both have verdicts
the table above grows by two, not one.

## Verdicts

Computed by `classify`, never typed. Base row after-tax, liquidation-adjusted
CAGR / max drawdown, full sweeps at `c6ef67e`.

| experiment | charter | verdict | development 2007–16 | validation 2017–21 | verdict note |
|---|---|---|---|---|---|
| **E1** | LOCKED 2026-09-17 | **INCONCLUSIVE** (E1 §13: C1 −1.53 pp dev, +6.89 pp val) | 6.53% / 59.29% | 21.66% / 48.76% | `docs/reviews/regression-2026-09-28-verdicts.md` |
| **E1b** | LOCKED 2026-09-18 | **INCONCLUSIVE** (GATE vs E1) | 8.40% / 54.96% | 15.90% / 46.14% | same |
| **E1-P** | LOCKED 2026-09-19 | **INCONCLUSIVE** (GATE vs E1) | 6.93% / 60.10% | 22.19% / 47.99% | same |
| **E1c** | LOCKED 2026-09-19, amended blind 2026-09-21 | **REJECT** (GATE vs E1) | 5.90% / 71.20% | 18.55% / 35.86% | same |
| **E1d** | LOCKED 2026-09-24 | **ADOPT** (GATE vs E1; 11/12, 10/11 rows) | 8.06% / 54.74% | 26.21% / 42.96% | same |
| **E2-A** | LOCKED 2026-09-25 | **REJECT** (GATE **and** §8a) | 8.28% / 38.32% *(2017–19)* | 44.89% / 8.47% *(2020–21)* | same |
| **E3-R** | LOCKED 2026-09-29 | **REJECT** (GATE vs E1 + E1d: G1 and G2 fail in both periods) | 6.82% / 54.16% | 19.62% / 48.08% | `docs/reviews/E3-R-verdict.md` |
| **E5-A A0** | LOCKED 2026-09-29 | **INCONCLUSIVE** (GATE vs E1 + E1d: dev G1–G4 hold; val G2 and G3 fail) | 12.59% / 14.46% *(2011–16)* | 7.51% / 26.69% | `docs/reviews/E5-A0-verdict.md` |

E2-A's windows are its own (§6), so its figures are not comparable with the
rows above. E1 base on **those** windows is 8.13% / 39.54% and 48.74% / 7.36%.
E5-A's development window is 2011–2016 (E5-A §8); the stack on it is
10.69% / 32.94%. E3-R and E5-A A0 are run at their lock tags (`lock/E3-R`,
`lock/E5-A`), not at `c6ef67e`. Mandate for both: not met (E3-R −6.92 /
−2.82 pp vs B5; A0 −5.26 / −14.93 pp).

## Benchmarks, same engine, SIP and tax (final regression)

| | development 2007–16 | validation 2017–21 |
|---|---|---|
| B1 Nifty 50 TRI | 7.84% / 59.22% | 14.88% / 38.06% |
| B2 Nifty 500 TRI (the market; MANDATE §3) | 8.06% / 63.53% | 14.77% / 37.94% |
| B3 Nifty 200 Momentum 30 TRI, 0.30% drag | 13.22% / 67.53% | 20.16% / 33.92% |
| **B5 Nifty 500 Momentum 50 TRI, 0.30% drag** (MANDATE §5) | **13.73% / 70.15%** | **22.44% / 38.14%** |

B4 (equal-weight universe) depends on each experiment's universe and is in
each sweep's summary. B5's history before launch is back-computed by NSE.

### Each base row against B5 (CAGR gap, after tax)

| | development | validation |
|---|---|---|
| E1 base − B5 | −7.20 pp | −0.78 pp |
| E1b base − B5 | −5.33 pp | −6.54 pp |
| E1-P base − B5 | −6.80 pp | −0.25 pp |
| E1c base − B5 | −7.83 pp | −3.89 pp |
| **E1d base − B5 (the stack)** | **−5.67 pp** | **+3.77 pp** |

MANDATE §5 asks the adopted stack for **+2 pp over B5 in both periods**. No
result meets it in development.

## How judging works from 2026-09-21

- **Adoption** (does a change join the stack): `GATE.md` G1–G4, unchanged.
- **ADVANCE** (sealed reveal, live paper year, real money): `MANDATE.md` §3
  (worst fall ≤ B2's + 5 pp **and** return ≥ B2 + 3 pp/yr, base row and two
  thirds of the rows) and §5 (return ≥ B5 + 2 pp/yr), both periods. Replaces
  E1 §13's C1–C4 in that role; C1–C4 are still reported for candidate bases.
- From E1c onward `classify` writes a **mandate** block beside the GATE and
  C1–C4 blocks.

## Next

**E5-A families** (A0 INCONCLUSIVE; each family is judged incrementally
against the frozen A0 and for adoption against E1 + E1d, E5-A §10): A1
(issuer events) and A3 (world exposure) built to ready-to-lock, A2 readiness
note (2026-09-30). Then E2-B, E1-S, E2-D1, E2-D2 (parked), E2-E, E3, E6-V.
E3-R is off the forward list (REJECT). No stack meets the mandate yet.
