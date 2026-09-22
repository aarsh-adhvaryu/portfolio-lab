# E1b — Diagnostic note (verdict: REJECT)

Required by GATE.md for a non-ADOPT verdict. No parameter changed. Sealed
untouched. Stack remains E1 base.

## Verdict arithmetic

GATE vs E1 base: G1 fails both periods (+0.13 pp dev, −10.73 pp val); G2
violated in validation; G3 5/14 then 0/14; G4 passes. REJECT.
E1 §13: C1 fails both (+1.40, +0.59 over B2); C2 fails both (−4.01, −4.87 vs
B3); C3 passes dev, fails val; C4 0/14 both. REJECT.

## What the experiment established (both periods, therefore trusted)

1. **The universe was not E1's problem; it was E1's validation return.**
   On Nifty 200 names, E1's rules earn 9.47% (dev) and 15.38% (val). E1's
   26.12% in validation came from names outside the top 200 during the
   2017–2021 small-cap boom. Finding 3 of the E1 diagnostic (median
   holding rank 240–340) was where the money came from, not a defect.
2. **On the fund's own universe, E1's rules trail the fund's rules by a
   consistent 4–5 pp:** −4.01 pp (dev), −4.87 pp (val). First result to
   hold in both periods. The gap is rules, not names.
3. **E1b is operationally healthier and earns less:** ADV skips 3.6% → 0%,
   turnover 1.16 / 1.00, tax drag 0.73 / 1.99 pp, names held 24–32 in
   validation, no delistings. A well-behaved strategy with no edge.
4. **Trend filter:** S6 (off) is worse in development (8.33% / 71.9%) and
   better in validation (18.54% / 40.6%). Same shape as E1: insurance,
   paid for in the years that recover.
5. **Sell-to-cash during RISK_OFF (S7):** better on both metrics in both
   periods for E1b (11.24% / 49.2% dev; 15.59% / 24.1% val vs base 9.47% /
   54.7%; 15.38% / 43.6%), and better drawdown in E1's own sweep. Not
   promotable from a sweep. Recorded for E3, which governs RISK_OFF
   behaviour; added there as a row.
6. **Membership bracket** (S12 vs base): 2.14 pp in development, 0.72 pp in
   validation. Wide in the proxy years, narrow where Nifty 200 is
   published. The verdict does not depend on it (REJECT holds under both
   bounds).
7. **S10 (Nifty 500 members)** 3.91% dev / 17.15% val: the wider universe
   helps exactly when small caps run. Same finding from the other side.

## Caveats

B3's pre-2020 history is backfilled by NSE and carries no tax until sale;
the 4–5 pp gap is measured against a benchmark that may be flattered by an
unknown amount. E1c is chartered to measure that.

## What this unlocks

Next experiment. Order: E1-P (ready, runs on E1 base as the stack), then
E1c (the fund's construction through this engine). E3 gains a row (S7).

---

- 2026-09-22 — **Superseded verdict.** E1b was re-run from scratch under E1
  §15's 2026-09-21 measurement correction and its GATE verdict is now
  **INCONCLUSIVE**, not the REJECT recorded above: see
  `docs/reviews/E1b-verdict-rerun.md`. This note is kept as written; its
  findings on the universe stand.
