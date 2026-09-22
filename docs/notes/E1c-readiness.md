# E1c — readiness note (2026-09-19, updated at the lock)

**E1c is LOCKED (2026-09-19)** with §3 and §6 as amended; §3–§7 do not change
again. Locked-span anchor, for the same verification E1, E1b and E1-P get:

    E1c §3–§7 at the 2026-09-19 LOCK
    chars   3588
    sha256  10c6f6eee677a16c7dad299cc353ec4f864b9a56e913e040ebca24114de96c10

This note said, at prep time, which lines of §3 the data or the engine could
not support as written. The amendments answered them; what follows records
what each one settled, what changed in the code, and the two things that
remain true whatever the charter says.

---

## 1. What the amendments settled

| flagged at prep | amendment | state |
|---|---|---|
| §6 could restate E1 §13's C2 on a gap containing an unmeasurable weighting artefact | **§6: E1c MAY NOT restate C2.** Report the gap, attribute what the run supports, and report base vs S1 as the bound on weighting | **settled** — see §2 |
| "effective the last trading day of June and December" could not be placed by an engine that fills at the next open | **§3: effective at the open of the first session after** the last trading day of June and December | **settled** — E1 §7's convention, no engine change |
| §3 stated two lags where NSE has one | **§3: one lag in total.** The score's skip of the most recent month IS the lag | **settled** — `score_lag_months` now defaults to 0 |
| §3's averaging order differs from NSE's | **§3: the charter's order stands; NSE's is tested as S12**, not adopted | **settled** — new sweep row |
| a selected name with a score ≤ 0 has no weight defined | **the halt stays.** If it fires, stop and report | **settled as policy** — see §4 |

---

## 2. The free-float gap: the amendment fixed the consequence, not the cause

Confirmed at prep and still true: **no dataset anywhere under `data/`
carries shares outstanding, free float or market capitalisation.** Checked
`panel/prices.parquet` (16 columns, none of them), `panel/listing_dates`,
`panel/instrument_exclusions`, `panel/symbol_isin_map`, and every other
`data/` subdirectory. HANDOFF §5 records point-in-time fundamentals as not
started, no module, no data directory.

So the replication reproduces the fund's **signal, selection and cadence**,
but not its **weighting**, and the gap it reports to B3 necessarily contains
a weighting artefact that cannot be measured away.

**§6 now refuses to move E1's bar on that gap**, which is the right
consequence: a bar must not move on an artefact, and C2 moves only on a
replication with real free-float weights. What E1c can still do is measure
everything else and say how big the unmeasured part might be — hence §6's
requirement to report **base against S1 (equal weight)** in both periods.

Read that spread honestly when it arrives. It is the distance between two
weighting schemes that the panel *can* express; the fund's third scheme sits
somewhere unknown, not necessarily between them. It bounds the order of
magnitude, not the sign.

---

## 3. One lag, counted in month-end positions

§3 now has a single lag: the score's skip of the most recent month.
`score_lag_months` defaults to **0**, so the score date is the rebalance
month-end itself and the skip does the lagging.

The charter also kept the rule that any lag is **counted in month-end
positions, never calendar days**, which is worth keeping even at zero.
Subtracting one calendar month from a month-end lands mid-month — one month
back from 2013-06-28 is 2013-05-28 — which is *before* that month's own
month-end session (2013-05-31). Snapping to "the latest month-end at or
before it" therefore skips May entirely and reaches back to April, turning a
one-month lag into a two-month one. That bug was found and fixed at prep;
the position-counting form cannot drift, and a test exercises it at
`score_lag_months = 1` so the machinery stays honest even though the base
row no longer uses it.

---

## 4. The halt stands, and it will probably fire

§3 asks for weights "score-proportional capped at 5%". After cross-sectional
z-scoring, a selected name's score can be negative — in a bad cross-section
the whole top 30 can be — and proportionality is undefined there. NSE maps z
to a positive normalised score ((1+z) for z ≥ 0, 1/(1−z) otherwise), but §3
does not say so, and adopting that mapping because a run needed it would be
adding a rule that is not in the charter (CLAUDE.md 3).

**The code halts** (`construct.UndefinedWeight`), naming the offending names
and the worst score. Aarsh has confirmed the halt stays and that if it fires
the run stops and is reported.

Expect it to fire. Development spans 2008. A z-score is centred by
construction, so the top 30 of a 200-name universe will usually be positive
— but in a cross-section where almost everything has fallen, "least bad" is
still negative. When it happens the run will stop mid-sweep with the date and
the names, and that is the charter asking a question, not a defect. It must
not be answered in code.

The alternative mapping exists behind `weighting_negative = "nse_normalised"`
and is unreachable until a charter line selects it.

---

## 5. What is built

- `signals/vol_scaled.py` — `vol_scaled_score_panel`: 6- and 12-month returns
  each skipping the most recent month, each divided by the annualised daily
  volatility over the *same* span, combined, z-scored cross-sectionally and
  clipped at ±3. `order` selects §3's combination (average the ratios, then
  z-score) or S12's (z-score each, then average); it is a chartered sweep
  row, not a free parameter.
- `portfolio/construct.py` — `score_tilted_weights` (the cap redistributes
  rather than truncates, iterated; verified to sum to 1.0) and
  `buy_list_weighted` (E1 §5's shortfall machinery retargeted from an equal
  share to each name's §3 weight).
- `backtest/engine.py` — `_decide_rebalance`: sells at rebalance only, no
  band, no intra-month exits; targets carry between rebalances and only
  shortfall buys happen. Every new knob defaults to E1's behaviour, so an E1
  or E1b config reaches exactly the code it reached before.
- `eval/sweep.py` — `e1c_rows()`: base plus **S1–S12**. S11 reuses
  `period_for_row` and the `_<row>_stack` companion, as E1b's S13 does.
- `configs/e1c.toml`, `tests/test_e1c.py` (22 tests, all synthetic).

**§5 S4 keeps the fund's weighting.** S4 puts E1's monthly 30-in/60-out band
back on the fund's score. Because E1's decision path had only ever produced
equal-weight targets, the obvious implementation would have made S4 change
the cadence *and* silently drop the score tilt — two changes in a row §5 says
"isolates one of E1's departures". The monthly path now carries the weighting
through, and a test asserts S4's weights stay tilted and capped while E1 and
E1b never receive target weights at all.

The score was also checked against **real prices**, read-only, with no engine
run: a 2012–2016 slice of the 120 most-traded names scored 111 names on the
last date with mean −0.003, standard deviation 0.991 and a maximum of exactly
3.000. Truncating that slice at 2015-06-30 and re-scoring reproduced the
retained rows **exactly** (max absolute difference 0.0) — CLAUDE.md 4 and
principle 5 on real data, not a synthetic proxy.

---

## 6. Readiness

**Locked and running.** Every §3 and §6 item raised at prep was answered by
the amendments, the code matches the amended charter, and 401 tests pass.

**The halt now stops the sweep.** `run_sweep` catches a row's exception,
records it as HALTED and moves on, which is right for a data error and wrong
for this one: a charter question recorded as one failed row would have been
buried under the other twelve and produced a summary that read like a result.
`UndefinedWeight` is therefore re-raised out of `run_sweep`, and the engine
attaches the month-end (and the score date, when they differ) on the way out,
so the report can say *when* §3 ran out of rules as well as which names and
how bad the worst score was.

Two things the lock should go in knowing, neither of which a charter line can
fix:

1. **The replication is of the fund's signal and cadence, not its weighting**
   (§2). §6 already prevents that from moving E1's bar; it does not stop it
   from colouring the attribution, so read base-vs-S1 before reading the gap.
2. **The first run will probably halt** on a non-positive selected score
   (§4), most likely somewhere in 2008. That is expected, and the response is
   to report it to Aarsh, not to pick a mapping.

After the lock: development sweep, written review, validation sweep,
`classify` against GATE and E1 §13 C1–C4, verdict.

---

## 7. The halt, as it fired (2026-09-21)

The first development sweep stopped on the charter, as designed. **No
artifacts were written**, so no strategy metric from any row has been seen.

**Where it fired.** Row **S4**, month-end **2015-12-31**:

    1 of 37 selected names have a score <= 0 (worst -0.0240)
    INE612J01015  REPCOHOME (Repco Home Finance)

Reproduced independently from the panel, read-only: on 2015-12-31, 184
eligible names were scored, only **48 were positive**, and REPCOHOME sat at
**rank 51** with **−0.024** — matching the halt to three decimals. Ranks
1–30 were all comfortably positive (rank 30: +0.164).

**The prediction in §4 was wrong on both count and place.** It said the halt
would probably fire in 2008, and implied the base row. The base row never
reaches the undefined case: its weakest selected score across all 20
development rebalances was +0.164. The halt came from S4, in 2015.

**Why S4, and whose reading that is.** S4 puts E1's 30-in / 60-out band on
the fund's score. A band keeps held names until rank 60, and in a z-scored
cross-section the scores turn negative well before that (at rank 49 here).
S4 halts only because it carries §3's score-proportional weights through the
band, so that it changes one thing — the cadence — as §5 says every row
must. That reading was the implementer's, written down in §5 of this note
before the lock. Had S4 used E1's equal weights, it could never have halted.
The two readings are not equivalent, and choosing between them is not the
code's job.

**Every other row, checked without running them** (read-only; score minima
only, no returns computed). At a rebalance, weights depend only on scores and
eligibility, never on holdings, so each row either shares the base row's
score sets or needs its own check:

| row | outcome | basis |
|---|---|---|
| base, S2, S3, S5, S7, S8, S11 | clean | base row's selections, or a subset |
| S1 | cannot halt | equal weights |
| S9 (quarterly) | clean | 40 rebalances checked; lowest +0.164 |
| S10 (latest bound) | clean | 20 rebalances checked; lowest +0.155 |
| S12 (NSE order) | clean | 20 rebalances checked; lowest +0.121 |
| **S4** | **halted** | 2015-12-31, REPCOHOME, −0.024 |
| **S6** (raw 12-1) | **would halt** | 2008-12-31: **26 of the top 30** non-positive, worst −0.376 |

S6's halt is a different question from S4's. S6 swaps in raw 12-1 momentum,
which is not z-scored, so in a crash the top 30 by momentum are mostly still
negative returns; "proportional to score" has no meaning for 26 of 30 names.

**The decision is still blind, which matters for how it can be made.** No
metric from base, S1, S2 or S3 was written or printed before the sweep
stopped, and the checks above looked at scores, not returns. That is the
condition under which E1 amended §7 after its lock on 2026-09-17 ("amended
after lock, blind: all sweep rows halted ... before any strategy metric
existed"). E1c §9's lock line forbids changes to §3–§7; whether a blind
amendment is permitted here, and what it says, is Aarsh's decision. Nothing
has been changed.

---

## 8. After the amendment and the fix (2026-09-21) — ready to run

**§7 above is superseded in one respect: the halt it describes was caused by
the implementation, not by the charter.** §3 standardises the score "across
the universe"; the code standardised it across every name in the panel with
a score (1,130 on 2015-12-31) and restricted to the 184-name universe only
afterwards. Measured as §3 says, REPCOHOME's score that day is **+0.462**,
not −0.024; 87 of 184 names are positive, not 48; and every score in S4's
60-name band was positive. Declared in E1c §9 as a code fix, before any run.

**What changed in the code** (all before the run; nothing since):

- `signals/vol_scaled.py` builds the raw ingredients once and
  `standardise` z-scores and clips them per date; the engine hands it the
  **eligible universe** at each decision date. A regression test adds 25
  names from outside the universe and asserts not one weight moves.
- **Amendment (1)**: `construct.score_tilted_weights` weights by
  max(score, 0), water-filled under the 5% cap. A non-positive held name gets
  weight 0: it keeps its shares, gets no new money, and leaves by its row's
  exit rule. The halt remains only for a selection with **no** positive
  score.
- **Amendment (2)**: S6 is `mom_12_1_z` — E1's raw 12-1 momentum through
  §3's own z-score and ±3 clip. E1, E1b and E1-P still rank raw `mom_12_1`,
  untouched.
- **(3)** S4 keeps §3's score weights through the band, unchanged.

**Read-only check on the corrected scores** (scores and weights only; no
returns computed):

| row | rebalances | lowest selected score | non-positive selected | weights sum to |
|---|---|---|---|---|
| base, S2, S3, S7, S8, S11 | 20 | +0.566 | 0 | 1.000 |
| S5 (25 names) | 20 | +0.751 | 0 | 1.000 |
| **S6** (12-1, z-scored) | 20 | **+0.014** | 0 | 1.000 |
| S9 (quarterly) | 40 | +0.491 | 0 | 1.000 |
| S10 (latest bound) | 20 | +0.464 | 0 | 1.000 |
| S12 (NSE order) | 20 | +0.533 | 0 | 1.000 |
| **S4** (monthly band) | 120 | top 30 always 30/30 positive | band tail reaches −0.098 | 1.000 |

So the amendment's claim — it changes no row whose selected scores were all
positive — holds on the corrected scores. **S6 now weights every
rebalance.** **S4 now weights every month-end**: its top 30 is always
positive, so its weights always sum to 1, but the bottom of its 60-name band
dips below zero on some month-end, and a name held there gets weight 0 under
(1). That is the one place the amendment has anything to do. The kept halt
fires on no row-date.

**Byte-identity re-asserted after every change**, synthetically (412 tests)
and on real development data, base row against the stored sweep, maximum
absolute difference 0.0 on CAGR, max drawdown and turnover:

| path | stored sweep | exact |
|---|---|---|
| E1 | `development-b7ef1437e30b0fbf` | yes |
| E1b | `development-1996387124c166df` | yes |
| E1-P | `development-f22a7a28de0da1ad` | yes |

**Code frozen at `source_sha 455f61c0803632f2`.** Both E1c sweeps must run on
it; each sweep's `manifest.json` records the value, so a mismatch is visible.
Nothing in `src/` or `tools/` changes until E1c's verdict is written.
