# E1d — verdict: INCONCLUSIVE (2026-09-25)

Charter `docs/strategies/E1d.md`, LOCKED 2026-09-24 (span hash in
`docs/notes/E1d-readiness.md` §0). Computed by `classify.classify_e1d`,
written to
`experiments/E1d/sweeps/validation-7d350769a6907044/verdict.json`.

Sweeps: development `development-a8d5d7cda901a63f` (commit `37d018b`),
validation `validation-7d350769a6907044` (commit `c1f5cd9`). STACK = E1 base
as re-run under the 2026-09-21 measurement correction
(`experiments/E1/regression/`). Development review, written before
validation ran: `docs/reviews/E1d-development.md`.

**Change-log entries that apply** (CLAUDE.md non-negotiable 1): E1d §3 and
§5 as amended 2026-09-24 — the score is standardised and clipped within the
eligible universe at the decision date, and S11 was added. E1c's 2026-09-21
weighting amendments do not reach E1d, which is equal weight.

## The verdict

**GATE: INCONCLUSIVE.** Not ADOPT, because G2 and G3 fail in validation.
Not REJECT, because REJECT needs G1 to fail in both periods or G2 to be
violated in both, and neither happened.

| | development | validation |
|---|---|---|
| G1 (CAGR +0.5 pp **or** MaxDD −2 pp) | ✓ both limbs | ✓ on drawdown only |
| G2 (the other metric within tolerance) | ✓ | **✗** |
| G3 (G1–G2 in two thirds of rows) | ✓ 11/12 | **✗ 2/12** |
| G4 (turnover at most 2×) | ✓ 1.79 vs 1.71 | ✓ 1.46 vs 1.31 |
| CAGR gap vs E1 base | **+2.58 pp** | **−3.09 pp** |
| MaxDD gap vs E1 base | −5.86 pp | −3.10 pp |

E1d base: development 11.55% / 49.54%, validation 24.27% / 36.72%.
E1 base: development 8.97% / 55.40%, validation 27.36% / 39.82%.

## What happened, in one line

**The score bought a shallower drawdown in both periods and a higher return
in only one.** In development it earned 2.58 pp more with a 5.86 pp
shallower worst fall. In validation it gave up 3.09 pp of return for a
3.10 pp shallower fall — a roughly one-for-one trade, which G2's asymmetric
tolerance (0.5 pp of CAGR against 2 pp of drawdown) is written to refuse.

G1 still passes in validation because its drawdown limb is satisfied; it is
G2 that stops the trade being called an improvement. That asymmetry is the
charter's, and it is the right way round: this project's mandate is
long-horizon compounding with continuing contributions, where a permanent
3 pp of return costs more than 3 pp of recoverable fall.

## E1 §13 (reported — E1d is a candidate base)

| | development | validation |
|---|---|---|
| C1 (≥2 pp over B2) | ✓ +3.48 | ✓ **+9.47** |
| C2 (≥2 pp over B3) | ✗ −1.68 | ✓ **+4.08** |
| C3 | ✓ | ✓ |
| C4 (two thirds of rows) | ✗ 1/12 | ✓ 8/12 |

Verdict INCONCLUSIVE: C1 passes in both, so REJECT is not available, and C2
and C4 fail in development, so ADVANCE is not either. From 2026-09-21 these
no longer decide ADVANCE; the mandate does.

## MANDATE §3 and §5 — not met

| | development | validation |
|---|---|---|
| §3 worst fall ≤ B2 + 5 pp | ✓ −13.94 pp | ✓ −1.21 pp |
| §3 return ≥ B2 + 3 pp | ✓ +3.48 | ✓ +9.47 |
| §3 in two thirds of rows | **✗ 6/12** | ✓ 12/12 |
| §5 return ≥ B5 + 2 pp | **✗ −2.19** | **✗ +1.79** |

§5 fails in both periods. Validation comes closest it ever has — +1.79 pp
against B5's 22.48%, needing +2 — but closest is not met, and §3's row test
fails in development. **No stack meets the mandate.**

## Three things worth carrying forward

1. **The one-for-one trade is the finding.** Volatility scaling did the same
   thing in both periods — it bought drawdown with return. Development's
   verdict looked good because that decade's crashes made the purchase
   cheap; validation's looked bad because 2017–2021 punished being out of
   the way. Nothing about the signal changed between them.

2. **S11 is a development-only row, and it silently duplicates S10 in
   validation.** Its `period.start` of 2012-01-01 precedes validation's own
   2017-01-01, so `period_for_row` correctly returns the unchanged period —
   and S11 then runs identical settings to S10 and reports an identical
   19.67% / 32.47% on 458 trades. That is correct behaviour, but it means
   validation's G3 count of 2/12 includes one row counted twice. Both
   copies fail, so the verdict is unaffected; a future charter adding a
   short-window row should say which periods it applies to. **Fixed in
   reporting on 2026-09-25** (`GATE.md`, "A short-window row must say which
   periods it applies to"): such a row is now reported as not applicable and
   excluded from the G3 and C4 counts rather than run as a duplicate. E1d's
   verdict is not revisited.

3. **§7 stands, and cuts the other way now.** E1d's hypothesis came from
   E1c's S6 on these same years, so a *pass* here would have been weak
   evidence. A failure on prior-exposed data is, if anything, stronger
   evidence than a pass would have been: the years that suggested the
   hypothesis did not sustain it. The §7 block is carried in
   `verdict.json`.

## Where the trade came from (reporting only, added 2026-09-25)

Aarsh asked whether volatility scaling tilted away from the most volatile
names in 2017–2021. It did, in every year, and by a wide margin.

Median turnover rank of holdings — rank 1 is the most traded name in the
eligible universe, so **higher means thinner names**:

| year | E1d | E1 base | diff | E1d names | E1 names |
|---|---|---|---|---|---|
| 2017 | 296.5 | 325.0 | −28.5 | 20.8 | 23.5 |
| 2018 | 160.5 | 292.8 | **−132.3** | 26.7 | 29.7 |
| 2019 | 141.5 | 289.0 | **−147.5** | 20.1 | 20.0 |
| 2020 | 233.8 | 242.2 | −8.4 | 17.2 | 18.4 |
| 2021 | 270.0 | 305.0 | −35.0 | 27.8 | 27.1 |
| **mean** | **220.5** | **290.8** | **−70.3** | | |

E1d held names about 70 ranks closer to the top of the traded-value list,
every year, on essentially the same number of positions. Dividing momentum
by each name's own volatility penalises exactly the thin, volatile names
that E1 base was drifting into — the drift E1's own diagnostic recorded
(rank 240–340 in both periods).

**This is the mechanism behind the one-for-one trade, and it also explains
its sign.** A more liquid book falls less, which is the 3.10 pp of drawdown
E1d bought. But 2017–2021 is precisely when the names below rank 200 ran,
which is where E1's 27.36% came from (E1b's verdict established this
directly: confining E1 to the Nifty 200 cost 10.7 pp in exactly these
years). E1d did not confine the universe, but the score tilted within it in
the same direction, and paid a smaller version of the same bill: 3.09 pp.

So E1d and E1b failed validation for the same underlying reason, reached by
different routes — one by rule, one by ranking. Reporting only; it changes
no verdict, and it was measured after the verdict was computed.

## The stack is unchanged

**E1 base remains the adopted stack.** E1d is not adopted. Per `GATE.md`,
an INCONCLUSIVE verdict is written down and not retried with new numbers.
The sealed period was not touched; `research/journal.jsonl` is still
absent.
