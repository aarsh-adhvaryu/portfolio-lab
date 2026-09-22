# STATE — verdicts and where things stand

One page. Updated 2026-09-21. The narrative is in `docs/HANDOFF.md`; the
order and reasons in `docs/ROADMAP.md`; the rules for judging in
`docs/strategies/GATE.md` (adoption) and `docs/MANDATE.md` (ADVANCE).

**Adopted stack: E1 base.** Sealed period (2022–2025) never opened;
`research/journal.jsonl` absent.

## Verdicts

After-tax, liquidation-adjusted CAGR / max drawdown of each base row, as
stored in its sweep. Every verdict was computed by `classify`, never typed,
and none is changed by anything below.

| experiment | charter | verdict | date | development 2007–16 | validation 2017–21 | verdict note |
|---|---|---|---|---|---|---|
| **E1** | LOCKED 2026-09-17 | **INCONCLUSIVE** (E1 §13), unchanged under the 2026-09-21 correction | 2026-09-17 | 9.34% / 55.38% → **8.97% / 55.40%** corrected (the stack) | 26.12% / 39.55% → **27.36% / 39.82%** | `docs/notes/E1-diagnostic.md` |
| **E1b** | LOCKED 2026-09-18 | **INCONCLUSIVE** (GATE vs E1), re-run under the 2026-09-21 measurement correction; was REJECT 2026-09-18 | 2026-09-22 | 9.74% / 54.96% | 15.51% / 43.34% | `docs/reviews/E1b-verdict-rerun.md` |
| **E1-P** | LOCKED 2026-09-19 | **REJECT** (GATE vs E1) | 2026-09-21 | 9.34% / 55.38% | 25.08% / 42.57% | `docs/reviews/E1-P-verdict.md` |
| **E1c** | LOCKED 2026-09-19, amended after lock (blind) 2026-09-21 | **REJECT** (GATE vs E1) | 2026-09-21 | 6.80% / 70.19% | 20.10% / 36.33% | `docs/reviews/E1c-verdict.md` |

## Benchmarks, same engine, SIP and tax

| | development 2007–16 | validation 2017–21 |
|---|---|---|
| B1 Nifty 50 TRI | 7.83% / 59.31% | 14.92% / 38.06% |
| B2 Nifty 500 TRI (the market; MANDATE §3) | 8.07% / 63.49% | 14.79% / 37.93% |
| B3 Nifty 200 Momentum 30 TRI, 0.30% drag | 13.48% / 67.48% | 20.25% / 33.95% |
| **B5 Nifty 500 Momentum 50 TRI** (MANDATE §5) | **15.37% / 70.00%** | **22.82% / 37.65%** |

B4 (equal-weight universe) depends on each experiment's universe and is in
each sweep's summary.

**B5 is information only here.** It was added 2026-09-21, after these
verdicts; no verdict is recomputed and none moves. Its history before launch
is back-computed by NSE (the caveat B3 carries), and it runs with **no
expense drag**, which makes MANDATE §5's +2 pp bar the harder one to clear.
B3 carries 0.30% as the fund it stands for; whether B5 should too is
Aarsh's call.

### The stored results beside B5 (CAGR gap, after tax)

| | development | validation |
|---|---|---|
| E1 base − B5 | −6.03 pp | +3.30 pp |
| E1b base − B5 | −5.90 pp | −7.43 pp |
| E1-P base − B5 | −6.03 pp | +2.26 pp |
| E1c base − B5 | −8.57 pp | −2.72 pp |

**Caveat on B5 and B3 in development (found 2026-09-21, not fixed).** A
benchmark buy sized to use all its cash is skipped when its costs no longer
fit, which comes down to rupee rounding; B5's very first buy (2007-02) was
skipped, so it sat out February 2007's fall by accident. Sized so costs fit,
development B5 is **14.14%, not 15.37%** (+1.23 pp inflated), and B3 13.32%,
not 13.48%. Validation, B1 and B2 are unaffected, and no verdict depends on
it. Details in `docs/reviews/E1c-verdict.md`.

For scale: MANDATE §5 asks the adopted stack for **+2 pp over B5 in both
periods**. In development every stored result is about 6 pp short of B5.
B5's back-computed 2007–2016 of 15.37% is roughly 2 pp above B3's, and its
70% drawdown is the deepest benchmark in the table.

## How judging works from 2026-09-21

- **Adoption** (does a change join the stack): `GATE.md` G1–G4, unchanged.
- **ADVANCE** (sealed reveal, live paper year, real money): `MANDATE.md` §3
  (worst fall ≤ B2's + 5 pp **and** return ≥ B2 + 3 pp/yr, base row and two
  thirds of the rows) and §5 (return ≥ B5 + 2 pp/yr), both periods. Replaces
  E1 §13's C1–C4 in that role; C1–C4 are still reported for candidate bases.
- From E1c onward `classify` writes a **mandate** block beside the GATE and
  C1–C4 blocks.

## Next

**E2-A**, the permanent-loss guard (MANDATE §4). Then E3-R, E2-B, E1-S, E2-C,
E2-D, E2-E, E3, E6-V, E5-A. No stack meets the mandate yet.
