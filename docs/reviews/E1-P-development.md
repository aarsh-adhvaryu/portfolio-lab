# E1-P — Development review (2007-01-01 .. 2016-12-31)

Written before the validation sweep. No parameter proposals; the charter is
locked (§10, 2026-09-19). Sweep:
experiments/E1-P/sweeps/development-f22a7a28de0da1ad/. STACK = E1 base.

## Against the gate (development only; verdict needs both periods)

G1 ✗, G2 ✓, G3 ✗ (1 of 6), G4 ✓. After-tax CAGR 9.3419% vs E1 base
9.3357%: +0.006 pp.

## What the numbers say

The rule did what §2 asked and netted to nothing.

| | E1 base | E1-P base |
|---|---|---|
| CAGR pre-tax | 10.68% | 10.45% |
| CAGR after tax | 9.3357% | 9.3419% |
| tax drag | 1.34 pp | 1.10 pp |
| tax paid | ₹10,27,033 | ₹8,28,785 |
| short-term share of gains | 66.2% | 52.6% |

Tax saved 0.24 pp/yr (a fifth of the bill, 13.6 pp out of the short-term
bucket); pre-tax return given back 0.23 pp. §2 asked whether deferring
saves tax without giving back return. Development answers: it saves the
tax and gives back the return, in almost exactly equal measure.

## Findings

1. **The mechanism is the answer, not the arithmetic.** §7 extra 1:
   deferred lots returned −12.34% over the following three months against
   −1.54% for the lots E1 would have sold, a gap of −10.80 pp on 26
   observations. A name that slips out of the band keeps slipping. The tax
   saving is real and the price of waiting for it is the same size.
   Reported as consistent with the pre-tax gap, not as independent
   evidence; 26 observations cannot carry more than that.
2. **It fires rarely.** 27 deferrals across 120 month-ends. The tax effect
   is path dependence, not a per-trade saving, which is why the two
   effects can cancel so precisely.
3. **S5 (six-month minimum hold, tax-blind) is the worst row at 8.23%**
   and inverts extra 1 (+4.17 pp). Blunt patience loses; this was the
   prediction written into the charter before the run, and it held.
4. **N1 (20% stop-loss) beat the base row on both metrics**: 11.65% /
   41.6% against 9.34% / 55.4%, 154 sells, and the names it cut fell a
   further 12.18% over six months. §4 anticipated this case. It is a
   control: one period, one crash, 38% more turnover, and the published
   momentum-crash literature predicts exactly this shape in a window
   containing 2008. Not adoptable. If validation agrees, it earns a
   pre-registered charter of its own; if not, it was 2008.
5. **N2 (50% profit-take) behaved as predicted**: 7.85%, 97.7% short-term
   gains, and the names it sold rose 9.05% over the following six months.
   Selling winners is the expensive kind of impatience.

## Note on the charter resolution

The oldest-lot resolution forced a correction in S4: it had been testing
the position-average cost basis, which defers when a later cheap top-up
drags the average into a gain even though the lot FIFO would realise sits
at a loss. That is the short-term loss S4 exists to harvest. Fixed before
the run, both directions pinned by tests.

## Implications (recorded, not acted on)

If validation confirms N1, a stop-loss charter is the next candidate after
E1c, and its hypothesis is momentum-crash protection, not loss aversion.
E1-P itself, on development, is a wash: the tax layer is not where the
missing 4 pp lives.

## Decision

Run the validation sweep and classify. Sealed untouched.
