# STATE — verdicts and where things stand

One page. Updated 2026-09-27. The narrative is in `docs/HANDOFF.md`; the
order and reasons in `docs/ROADMAP.md`; the rules for judging in
`docs/strategies/GATE.md` (adoption) and `docs/MANDATE.md` (ADVANCE).

**Adopted stack: E1 base**, read from `experiments/E1/regression/` since the
2026-09-21 measurement correction. Sealed period (2022–2025) never opened;
`research/journal.jsonl` absent.

## How many experiments have been tested

`GATE.md`'s parallel-running rule 3. **Every added test raises the chance of
a lucky pass**, and from 2026-09-26 several may run at once, which raises it
faster. The sealed period is the correction — seen once, by one stack — and
this count is what a reader needs in order to weigh any pass at all. A stack
that passes on the twentieth attempt is not the evidence a stack that passed
on the second would be.

| | |
|---|---|
| **experiments with a computed verdict** | **6** |
| ADOPTED | **0** |
| REJECT | 3 (E1-P, E1c, E2-A) |
| INCONCLUSIVE | 3 (E1, E1b, E1d) |
| sealed-period reveals used | **0 of 1** |
| stacks meeting MANDATE §3 and §5 | **0** |

Locked and awaiting a run: none. **Built and ready to lock** (2026-09-27):
E2-D1, E3-R, E2-D2 — each note's last section says what the lock must settle.
Readiness notes: E2-B, E2-C, E3. Drafts: E1-S, E2-E.

**E2-D was split in two on 2026-09-27** (Aarsh): **E2-D1** promoter selling
(2010–2016 / 2017–2021) and **E2-D2** insider selling from PIT (2017–2019 /
2020–2021), because the PIT input exists only from 2016 and one charter
would have tested different rules in its two periods. **The split adds one
to the count of experiments that will be tested**: when both have verdicts
the table above grows by two, not one.

## Verdicts

Every verdict was computed by `classify`, never typed. Figures are the base
row's after-tax, liquidation-adjusted CAGR / max drawdown **under the
2026-09-21 measurement correction** (E1 §15: buys sized net of costs; expense
drag compounded by calendar days).

| experiment | charter | verdict | under the correction | development 2007–16 | validation 2017–21 | verdict note |
|---|---|---|---|---|---|---|
| **E1** | LOCKED 2026-09-17 | **INCONCLUSIVE** (E1 §13) | **holds** | 8.97% / 55.40% | 27.36% / 39.82% | `docs/notes/E1-diagnostic.md` |
| **E1b** | LOCKED 2026-09-18 | **INCONCLUSIVE** (GATE vs E1) | **changed** from REJECT; re-run from scratch 2026-09-22 | 9.74% / 54.96% | 15.51% / 43.34% | `docs/reviews/E1b-verdict-rerun.md` (supersedes `docs/notes/E1b-diagnostic.md`) |
| **E1-P** | LOCKED 2026-09-19 | **REJECT** (GATE vs E1) | **holds** | 9.14% / 55.78% | 25.85% / 43.52% | `docs/reviews/E1-P-verdict.md` |
| **E1c** | LOCKED 2026-09-19, amended after lock (blind) 2026-09-21 | **REJECT** (GATE vs E1) | **holds** | 6.73% / 70.19% | 20.10% / 36.33% | `docs/reviews/E1c-verdict.md` |
| **E1d** | LOCKED 2026-09-24 | **INCONCLUSIVE** (GATE vs E1) | n/a — run under it | 11.55% / 49.54% | 24.27% / 36.72% | `docs/reviews/E1d-verdict.md` |
| **E2-A** | LOCKED 2026-09-25 | **REJECT** (GATE **and** §8a) | n/a — run under it | 11.85% / 33.18% *(2017–19)* | 41.84% / 8.41% *(2020–21)* | `docs/reviews/E2A-verdict.md` |

E2-A's windows are its own (§6: 2017–2019 / 2020–2021), set by when its
inputs exist, so its figures are not comparable with the rows above. E1
base on **those** windows is 14.60% / 31.37% and 50.04% / 7.19%.

**Why the three that hold need no re-run.** Each is decided by base-row and
benchmark arithmetic alone, which the 2026-09-21 regression re-ran; the other
sweep rows cannot change them.

- **E1:** C1 is +0.90 pp in development (below 2, so not ADVANCE) and
  +12.57 pp in validation (so not REJECT).
- **E1-P:** G1 fails in both periods (+0.17 pp and −1.52 pp against E1
  base). Its development gap moved from +0.006 pp to +0.17 pp, still below
  the +0.5 pp bar, so it does not flip the way E1b did.
- **E1c:** G2 is violated in both periods (−2.23 pp with 14.79 pp deeper
  drawdown; −7.26 pp). Its reported C1–C4 stays INCONCLUSIVE.

E1b changed because its development gap moved from +0.13 pp to +0.77 pp,
past G1's bar.

## Benchmarks, same engine, SIP and tax (corrected)

| | development 2007–16 | validation 2017–21 |
|---|---|---|
| B1 Nifty 50 TRI | 7.83% / 59.31% | 14.92% / 38.06% |
| B2 Nifty 500 TRI (the market; MANDATE §3) | 8.07% / 63.49% | 14.79% / 37.93% |
| B3 Nifty 200 Momentum 30 TRI, 0.30% drag | 13.23% / 67.53% | 20.18% / 33.92% |
| **B5 Nifty 500 Momentum 50 TRI, 0.30% drag** (MANDATE §5) | **13.74% / 70.15%** | **22.48% / 38.12%** |

B4 (equal-weight universe) depends on each experiment's universe and is in
each sweep's summary. B5's history before launch is back-computed by NSE,
the caveat B3 carries.

The earlier caveat that development B5 was overstated by a skipped first
buy no longer applies: the correction fixed it, and these are the corrected
figures (development B5 read 15.37% before).

### Each base row against B5 (CAGR gap, after tax)

| | development | validation |
|---|---|---|
| E1 base − B5 | −4.78 pp | +4.88 pp |
| E1b base − B5 | −4.00 pp | −6.97 pp |
| E1-P base − B5 | −4.60 pp | +3.36 pp |
| E1c base − B5 | −7.01 pp | −2.38 pp |

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

**E1d** (readiness: `docs/notes/E1d-readiness.md`), then E3-R, then E2-A
when its BSE backfill completes, then E2-B, E1-S, E2-C, E2-D, E2-E, E3,
E6-V, E5-A. No stack meets the mandate yet.
