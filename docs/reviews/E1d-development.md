# E1d — Development review (2007-01-01 .. 2016-12-31)

Written before the validation sweep. No parameter proposals; the charter is
locked. Sweep: `experiments/E1d/sweeps/development-a8d5d7cda901a63f/`, clean
commit `37d018b`. STACK = E1 base as re-run under the 2026-09-21 measurement
correction (8.97% / 55.40%).

## Against the gate (development only; the verdict needs both periods)

| test | requirement | E1d vs E1 base | status |
|---|---|---|---|
| G1 | CAGR +0.5 pp or MaxDD −2 pp | +2.58 pp and −5.86 pp | met, on both limbs |
| G2 | the other metric within tolerance | neither worsens | met |
| G3 | G1–G2 in two thirds of rows | 11 of 12 | met |
| G4 | turnover at most 2× | 1.79 vs 1.71 | met |

E1 §13 (E1d is a candidate base): C1 +3.48 pp over B2, met; C2 −1.68 pp
against B3, not met; C3 met; C4 1 of 12 rows.

MANDATE: §3 is met by the base row (+3.48 pp over B2; worst fall 13.95 pp
shallower than B2's) but in only 6 of 12 rows, against 8 required. §5 is
not met: −2.19 pp against B5 (13.74%), where +2 is required, so the
shortfall is about 4.2 pp a year.

## What the numbers say

The first candidate in this project to clear every gate test in
development, and on both limbs of G1 rather than one. Measuring momentum
relative to each stock's own volatility, over six and twelve months,
improved E1 by 2.58 pp a year and made its worst fall 5.86 pp shallower,
and the improvement held in 11 of 12 perturbations. It remains behind both
momentum funds.

## Findings

1. **The improvement is broad.** Only S6 (trend filter off) fails the gate
   test; every change of size, cost, order, universe and delisting
   assumption keeps E1d ahead of E1 base.
2. **Where it comes from, as far as two rows can say.** S2 (the 12-month
   window alone, volatility-scaled) against E1 base (the same window, raw):
   +0.60 pp and a worst fall 6.3 pp shallower. So volatility scaling mostly
   bought a smaller drawdown. S1 (the 6-month window alone): 12.05%, 2.5 pp
   above S2. So the shorter window carries most of the extra return, at a
   price: turnover 2.86 against 1.79, and 97.7% of realised gains
   short-term. The base row averages the two. Recorded, not acted on: any
   future charter about lookback must declare it was noticed here.
3. **Still short of what can be bought.** −1.68 pp against B3, −2.19 pp
   against B5. On the published Nifty 200 years alone (S11's window,
   2012–2016) B3 made 20.05%.
4. **The trend filter still earns its place in this decade.** S6: 9.30% /
   68.90% against 11.55% / 49.54%.
5. **Sell-to-cash did not help here.** S7: 10.79% with the same worst fall
   as base, 49.54%, and 35% more turnover. Identical drawdowns suggest the
   worst fall happened before a month-end signal could act, which is the
   limit of any monthly rule in a fast crash. Relevant to E3-R, whose
   signals are also monthly. Recorded, not acted on.
6. **Drift into thinner names, as in E1.** Median turnover rank of holdings
   rose from 167 (2007) to 282 (2016); names held fell to 14.8 in 2011 and
   11.7 in 2016; 68 of 495 buys (13.7%) were skipped on the liquidity
   guard, 20 of them in 2015. E1 showed the same shape in development and
   recovered in validation; watch whether E1d does.
7. **Suspended names matter.** 11 holdings stopped trading and were exited
   at their last close, for a combined gain of ₹4.69 lakh, 7.8% of
   contributions. S9 (treat them as total losses) gives 8.54%, 3.0 pp
   lower. The base row's lead leans on how suspended names are valued. This
   is E2-A's question.
8. **S11, the published Nifty 200 years only:** 15.97% / 16.88% against E1
   base's 11.33% / 31.30% on the same window. S10 (the same universe over
   the full window, half of it the proxy) gives 11.32%. The two answer
   different questions, which is why S11 exists.
9. **S8 (NSE's standardisation order) returns 13.21%,** 1.66 pp above base.
   A stability check, not a menu; §3's order stays.
10. **Tax.** Drag 1.36 pp, 72.9% of realised gains short-term, ₹13.3 lakh
    paid.
11. **Cash.** 40 of 156 months RISK_OFF; mean cash share 29.4%, above half
    in 2008, 2009 and 2016.

## A reporting defect to check before validation is read

The equity-versus-cash decomposition does not reconcile this time: base
row equity 10.90 pp + cash 0.94 pp = 11.84, against a pre-tax CAGR of
12.91%, a gap of 1.07 pp (S1: 1.61 pp). Earlier sweeps reconciled within
0.2–0.3 pp, and S11 (2012–2016) reconciles here within 0.01 pp. The likely
cause is the interaction between two separately chained series, which grows
with volatility and turnover in a window containing 2008, but it should be
confirmed rather than assumed. No verdict reads this table.

## The caveat that travels with every E1d number (§7)

E1d's hypothesis came from E1c's S6, which showed the signal effect in both
development and validation. Neither period is fresh for this question. A
pass is weaker evidence than a pass on a new hypothesis; the only clean test
left is the sealed period, which MANDATE §14 reserves for a stack that meets
§3 and §5.

## Implications (recorded, not acted on)

If E1d is adopted, it becomes the stack and E3-R runs on top of it. Findings
2 and 5 are observations for future charters, declared here as noticed on
development data.

## Decision

Run the validation sweep and classify. Sealed untouched.
