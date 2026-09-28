# HANDOFF — 2026-09-27, session 2 of 4 (audit repairs)

`pytest -q`: **632 passed** (626 + 6); under the audit's pandas 2.2.3 with no
data dir, 631 + 1 skip. Sealed period untouched. Nothing running.

## Start here (2026-09-28, session 4, part B done — STOP for the regression)

**Recorded** (change logs dated 2026-09-28): E1 §15 declared choices
confirmed. Unnamed standard-ratio factors: 13 dev / 15 val. No base row
holds one. Treating them as bonuses moves CAGR ≤ 0.0001 pp. IIFL
2019-05-30 is a real demerger read as a split (declared). E5-A §14: D1, 3–7
and 9 as recommended. **A4 parked.** D2 waits for C. The A2 precondition is
settled. GATE and ROADMAP now put **E5-A next**. CLAUDE.md 7 adds lightgbm.

**Fixed** (E1 §15 2026-09-28): `collect_daily` now merges factors; BE-stint
dividends are credited; set-built dicts are sorted; the run id hashes the
repair inputs. Two D2 data errors are fixed: a stale prev close on return
to EQ, and a garbage prev close on entry that the open contradicts
(2008-06-13; ROHITFERRO 1:5, SHREEASHTA 1:3). All 4 saved CASH_CREDITs were
the first error. Transition actions ≤ 2016: 131 → 57. Payment dates:
declared, not built. `pytest -q`: 655 passed.

**ADV skips 39 → 83** (E1 dev), by cause:
- 21 are on D1 successor ISINs, which can now be bought;
- ~19 are bigger buys (median buy +35% in 2013), because written-down names
  now compound;
- only 4 have BE rows in the ADV window, and 1 of those would pass on
  EQ-only ADV.

By year: 2012 +2, 2013 +22, 2014 +2, 2015 +14, 2016 +5.

**Next:** Aarsh runs RUNNING.md job 6 (4 lanes, full sweeps). Then part C:
re-classify all six. If E1d still ADOPTs, move the stack to E1 + E1d in
GATE, ROADMAP, STATE and HANDOFF, and refresh every STATE figure.

## Start here (2026-09-27, session 4 of 4)

**E5-A readiness only, no code, no runs.** E5-A now has its own charter,
`docs/strategies/E5-A.md` (DRAFT; `E5.md` points to it). It covers: A0, a
price/volume control; issuer events, positioning, world exposure and
company news each added alone against A0; purging by stored label
interval; tuning on data truncated at 2010-12-31, with 2007–2010
exploratory and development from 2011; a feature store holding
availability and publication time; a price-only fallback with its share
reported.

**Not ready to lock.** Nine decisions are in `docs/notes/E5A-readiness.md`
§4 (order, stack, lightgbm, tuning, refit, activation/windows, positioning
scope, A4 source, adoption rule); the build list is §3. Still open from
session 3: the E1 + E1d stack confirmation and STATE refresh.

## Start here (2026-09-27, session 3 of 4, final)

**Full re-runs done (commit `1a6ce55`) and classified.** **E1d: ADOPT** (GATE
11/12 dev, 10/11 val; mandate not met; E1d §7 caveat). **E1-P: INCONCLUSIVE**
(was REJECT). Notes: `docs/reviews/E1d-verdict-rerun.md`,
`E1-P-verdict-rerun.md`; STATE counts updated.

**Decision for Aarsh:** confirm E1 + E1d as the stack. If confirmed:
`runner.main`'s `stack_config` line, `configs/`, STATE banner and every later
readiness note move to E1d base.
**Session 4:** that switch; refresh STATE's other figures to D1/D2 numbers
(E1, E1b, E1c, E2-A, benchmarks); the three open items below.

## Start here (2026-09-27, session 3 of 4, closing)

**Session 3 is done.** D1/D2 are approved, implemented and regressed (14/14 at
`0926a5b`); the gap attribution was re-run. Everything is in
`docs/reviews/E1-gap-attribution.md` §3. `pytest -q`: 648 passed. Nothing running.

- On base rows, **E1-P flips REJECT → INCONCLUSIVE** (G1 val +0.52 pp,
  knife-edge) and **E1d is a candidate ADOPT**. Both need full sweeps under
  E1b's procedure (RUNNING.md job 5). E2-A's a–d flip did not survive.
- Gap (dev): 10.52 pp XIRR. Frictions explain 2.0 pp; tax is the largest.
  Momentum selection is indistinguishable from random.

**Next (session 4):** Aarsh decides whether to run job 5. Then `classify_e1p` /
`classify_e1d` against the E1 regression base, verdict notes, STATE. Still
open from earlier: `collect_daily` factor overwrite (session 1 finding 1),
dividends inside BE stints, and the ADV-skip rise (§3).

## Start here (2026-09-27, session 3 of 4, D1/D2 implemented)

**D1/D2 approved by Aarsh and implemented** (`pflab/data/repairs.py`, E1 §15
entry, `tests/test_repairs.py`; 648 passed). Smoke: E1 dev base 6.43% / 59.02%,
XIRR 7.01%, 6 write-downs (was 2.87% / 13). ADV skips 39 -> 83 (BE turnover
now in the 20-session ADV); read it in the regression. **Next: Aarsh re-runs
`regress_bases.py` (4 lanes) and `gap_attribution.py`; then re-read E2-A's
flip and the selection finding.**

## Start here (2026-09-27, session 3 of 4)

D1/D2 still undecided, so session 3 did the audit's other two items on the
a–d numbers, all marked provisional. `docs/reviews/E1-gap-attribution.md`.

### Done
- §1 of that note: old vs a–d base and stack numbers for every experiment.
  **Only E2-A flips**: GATE REJECT → INCONCLUSIVE, because its stack fell
  5.21 pp in 2017–19 and E2-A fell 1.13 pp. That makes the overall verdict
  INCONCLUSIVE. STATE keeps REJECT (provisional) until E1b's procedure is
  followed.
- `tools/gap_attribution.py` (diagnostic, not promotable) plus two
  diagnostic-only engine knobs (`signal="lottery"`, `topup_max_rank`);
  `tests/test_gap_attribution.py`; golden digests unchanged.

### Decisions for Aarsh
D1/D2 (unchanged). Whether E2-A gets full re-runs if the flip survives D1/D2.
Two readings in the note's design (rank eligibility, weighting control).

### Next
Aarsh runs RUNNING.md job 3 (gap attribution); session 4 fills in the note's
Results. After D1/D2, re-run `regress_bases.py` and job 3.

---

## Start here (2026-09-27, session 2 of 4)

**Every verdict is provisional until re-run** (STATE.md banner). Nothing re-run.

### Done
- e/f: `tools/audit/reconcile_events.py`; results in
  `docs/reviews/accounting-correction-2.md`. All 14 CASH_CREDITs are
  BE-series gaps, not demergers. Of the 18 SELL_DELISTs, 11 are ISIN
  handovers, 2 a merger scheme, 5 unresolved from local data.
- g: `runner.input_fingerprints` — every consumed input, cut at period end,
  plus policy-file contents, in the run id and the manifest (`inputs`).
- h: 2999 sentinel (`positioning._as_date`); exclusivity checked before I/O;
  golden explained (last-bit `np.exp`), fixture rounded to paise,
  attribution re-proved against 8dea146.
- `tools/regress_bases.py` (14 jobs, lanes A–D, `--report`).

### Regression (run by Aarsh, 14/14 at 19f1ea2)
Every base row fell; E1 dev 8.97% → 2.87%. Mostly D1/D2 write-downs, so
**not usable for verdicts**; see `accounting-correction-2.md` "Regression result".

### Decisions for Aarsh
D1 ISIN handovers and D2 BE-series factors: `accounting-correction-2.md`
top. Running before them bakes in a known downward bias (live holdings
written to zero).

### Next
Aarsh: decide D1/D2. Session 3: implement them if approved, then Aarsh
re-runs `regress_bases.py` (all four lanes) and session 3 re-classifies.

---

# HANDOFF — 2026-09-27, session 1 of 4 (audit repairs)

`pytest -q`: **626 passed** (599 + 27). Six locked spans verify. Sealed
period untouched. Nothing running. Everything committed.

## Start here (2026-09-27, session 1 of 4)

**Adopted stack: still E1 base — but every saved result is now provisional**
(E1 §15, 2026-09-27: four accounting corrections). Nothing re-run.

### Done
- Step 0: audit at `docs/reviews/portfolio_system_audit.md`; reproducer at
  `tools/audit/`; "Working style" in CLAUDE.md.
- Step 1: Aarsh's decisions in change logs (E2-D1, E2-D2 parked, E2-C closed
  NOT RUN, E3-R (e), E2-B, E3, MANDATE §4, E1 determinism). Recorded only.
- Step 2: `tools/scan_etf_events.py`, `docs/data/etf_splits.md`. NIFTYBEES /
  GOLDBEES / LIQUIDBEES clean; 31 unused ETFs carry the same unrepaired
  split pattern; benchmarks read index series only.
- Step 3: defects a–d fixed (`tests/test_accounting_audit.py`, 24 cases;
  golden change attributed to STT + interest tax alone).

### Findings for Aarsh
1. `tools/collect_daily.py` writes `nca.factors()` (PURPOSE only) over
   `factors.parquet`, which holds 8,903 PREVCLOSE factors too. A scheduled
   run would silently drop them. Not fixed; decide before scheduling.
2. Declared choices to confirm (E1 §15 2026-09-27): recovery sale if a
   written-down name trades again (S9 too); bonus allotment = ex-date;
   unnamed standard-ratio factors = splits; fraction share dated by the
   completing lot.
3. Not done from the audit: dividend payment dates/receivables, demerger
   shortcut, input provenance (runner hashes), determinism build, E1-P side
   sleeve interest (inert).

### Next
Session 2: re-run E1 regression (dev + validation) and benchmarks under the
corrections — Aarsh's to run; RUNNING.md job 1 now compares against stale
numbers.

---

# HANDOFF — 2026-09-27, second session

`pytest -q`: **599 passed** (530 at the start + 69 new). All six locked spans
verify. Sealed period untouched; `research/journal.jsonl` absent. Nothing
was running at the start or the end (`tools\status.ps1`). **Nothing in this
session is committed.**

## Start here (2026-09-27, second session)

**Adopted stack: still E1 base. Nothing locked, nothing run.** Every
remaining charter question is now in front of Aarsh at once, as the
instruction asked.

### Done this session

- **Lanes 3–6** of the 2026-09-26 instruction:
  - **E2-B** readiness (`docs/notes/E2B-readiness.md`), plus the
    point-in-time **sector map** (`data/sector_map.py`, written to
    `data/index_membership/sector_map.parquet`) and the **factor betas**
    (`signals/shock_betas.py`), both tested. Findings: three NSE taxonomies;
    only **52.8% / 69.5%** of E1's held names are mapped point-in-time; and
    two of the five caps (Brent, US 10-year) are **degenerate** — the index's
    own beta crosses zero 16 and 11 times.
  - **E2-C** readiness (`docs/notes/E2C-readiness.md`): as read, the
    composite adds **zero** RISK_OFF months to E1's in either period.
  - **E3** readiness (`docs/notes/E3-readiness.md`): a **data error** —
    NIFTYBEES and GOLDBEES split 1:10 / 1:100 on 2019-12-19 and changed ISIN
    the next day, unadjusted in the panel (fixed for ETF rows by
    `data/etf_events.py`, built with E3-R); the liquid-ETF fallback earns
    ~2.2 pp less than the stack's own cash by construction.
  - **Drafts**: `docs/strategies/E1-S.md` (seven ◆ readings of MANDATE §7
    for Aarsh) and `docs/strategies/E2-E.md` (retail crowding,
    cross-sectional top decile proposed on priors).
- **Decisions recorded**: E3-R §11 (a)–(d), with pointers in §3/§4; E2-D
  split into **`E2-D1.md`** and **`E2-D2.md`**, `E2-D.md` marked superseded;
  `STATE.md` notes the split adds one to the count.
- **Built, tested, ready to lock** — each note's last section is what the
  lock must settle:
  - **E2-D1** (`docs/notes/E2D1-readiness.md`): the rule acts (a held name
    flagged in 92 of 144 months), but **16% of flags coincide with an
    unexplained fall in shares outstanding** (capital reductions,
    consolidations) that reads as promoter selling.
  - **E3-R** (`docs/notes/E3R-readiness.md` §7–§8): 35 cautious / 7 high
    months in development, 9 / 3 in validation; **the ADV guard likely
    skips the 2009-04 high month** (1% of NIFTYBEES ADV was ₹6.8 lakh);
    E1's paths byte-identical on synthetic data (`tests/test_engine_golden.py`).
  - **E2-D2** (`docs/notes/E2D2-readiness.md`): **93% of insider sell value
    is promoters**, so it largely re-measures E2-D1; 57% of sell value is
    not a market sale.

### Waiting on Aarsh

1. ~~Run the E1 identity check~~ **Done 2026-09-27, PASS in both periods**:
   equity and trades identical; decisions identical in content. The only
   difference is the key order inside `reference_close`, which is built
   from a Python set and so varies between any two processes (the same at
   `c33feb3`; not this session's). Logs in `experiments\_identity\`.
2. **Locks**: E2-D1 (§3: the share-count problem), E3-R (§8: ADV guard and
   the readings), E2-D2 (§3: categories, modes, S3). Each needs a
   `tools/check_lock.py` entry at its lock.
3. **Readiness decisions**: E2-B (six items), E2-C (whether to run a rule
   that as read never acts), E3 (five items).
4. **Draft reviews**: E1-S (seven ◆), E2-E (three ◆).
5. **Unchanged from the first session**: `docs/data/flag_audit_labels.md`
   is Claude's draft; Section C stays untriggered until Aarsh says
   "labels reviewed".

---

# HANDOFF — 2026-09-27

`pytest -q`: **530 passed.** Sealed period untouched; `research/journal.jsonl`
still absent. All six locked spans verify (`python tools/check_lock.py --all`).

## Start here (2026-09-27)

**Adopted stack: still E1 base. Nothing has been adopted, ever.**
`docs/STATE.md` now carries the running count: 6 experiments tested,
**0 adopted**, 3 REJECT, 3 INCONCLUSIVE, 0 of 1 sealed reveals used.

### Finished this session

- **E2-A: REJECT** (`docs/reviews/E2A-verdict.md`). GATE fails in both
  periods the strict way, and §8a fails because the flags' information
  **reverses sign**: −7.73% (t −3.14) in 2017–2019, +12.16% (t +3.48) in
  2020–2021. The useful part: in development the flags carried real
  information and the rule *still* lost 2.75 pp, because E1 holds 25 of
  ~500 names so excluding one mostly changes which unflagged name is
  bought instead.
- **Parallel running is now allowed** (`GATE.md`, 2026-09-26): experiments
  may be locked and run concurrently, each one change on the stack in
  force at its lock; an adoption forces a re-run of anything in flight.
- **Locked-run infrastructure**, tested live: `tools/check_lock.py`,
  `tools/run_locked.ps1`, `tools/status.ps1`, `PFLAB_EXPERIMENTS_DIR`,
  `docs/RUNNING.md`. Four concurrent sweeps is the measured ceiling.

### Waiting on Aarsh — nothing proceeds without these

1. **`docs/data/flag_audit_labels.md`** holds *Claude's draft* labels, not
   Aarsh's. **Section C of the 2026-09-26 instruction is not triggered
   until Aarsh has reviewed them.** Read the caution in that file's header
   and in this session's report: the draft was labelled after seeing
   E2-A's per-flag results, and 22 of 30 RATING_DOWNGRADE rows were marked
   UNSURE — RATING_DOWNGRADE being exactly the flag the sweep showed was
   costliest. That pattern is what bias would produce. RATING_DOWNGRADE
   and FRAUD need Aarsh's eyes first.
2. **E3-R: four charter decisions** (`docs/notes/E3R-readiness.md` §3) —
   V's undefined first six months, the cross-book lot-order tie-breaks,
   the index position's exemptions, and what interrupts the high-gear
   disposal. Each changes a number.
3. **E2-D: three declarations** (`docs/notes/E2D-readiness.md` §2) — total
   shares or free float, market cap at which date, and which
   shares-outstanding figure. §3's insider limb cannot be computed
   without them.

### Next, unstarted

Lanes 3–6 of the 2026-09-26 instruction: **E2-B** readiness (including a
point-in-time sector map from the captured Nifty 500 industry field),
then **E2-C** and **E3** readiness notes, then drafts of **E1-S** and
**E2-E**. None started.

---

# HANDOFF — 2026-09-24

## Start here (2026-09-24 session)

`pytest -q`: **479 passed** (was 440; +15 shareholding, +15 E1d, +9 insider).
Sealed period still untouched; `research/journal.jsonl` still absent. All four
locked charter spans re-verified after the code changes.

1. **E2-A is DONE: REJECT** (2026-09-25). `docs/reviews/E2A-verdict.md`.
   GATE fails in BOTH periods the strict way (G1 fails both, G2 violated
   both): development 11.85% / 33.18% against E1 base's 14.60% / 31.37%,
   validation 41.84% / 8.41% against 50.04% / 7.19%. **§8a also fails, and
   it is the informative part**: flagged names underperformed by 7.73%
   (t = −3.14) in 2017–2019 and OUTPERFORMED by 12.16% (t = +3.48) in
   2020–2021. The flags' information is not stable in sign, and even where
   it was genuine the rule could not convert it. **E1d is DONE:
   INCONCLUSIVE** (2026-09-25), `docs/reviews/E1d-verdict.md`. **The
   adopted stack is still E1 base.** Next: E3-R.

   **Waiting on Aarsh: `docs/data/flag_audit.md`** — 251 masked events, no
   returns, an empty label column. Precision per flag and the false-positive
   patterns get reported once it is labelled. No new charter until then.

2. **A shareholding backfill is RUNNING as three shards**
   (`tools/backfill_shareholding.py --shard i --of 3`), ~12.6 h at 247/min,
   resumable. **Three is the maximum** (four throttle, 2026-09-22). A shard
   takes a pid lock and a duplicate refuses; the venv python is a launcher
   shim, so each worker shows as two processes -- **count the locks in
   `data/bse_shareholding/_lock.shard*`, not the processes.** On 2026-09-24
   eighteen workers were started by accident and left 972 scrip-quarters
   ledgered with no data behind them; repaired by
   `bse_shareholding.rebuild_ledger_from_data()`. If the ledger and
   `summary.parquet` ever disagree, run that. Findings:
   `docs/data/shareholding_finding.md` §5.
3. **Insider disclosures are COLLECTED**: NSE structured PIT 2015-11-19 →
   2026-05-02 (338,986 rows) and BSE insider/SAST out of the announcements
   backfill. Findings and the source disagreement:
   `docs/data/insider_finding.md`.
4. **XBRL was probed, not collected** — deliberately.
   `docs/data/xbrl_results_finding.md` has the field list and the answer to
   the cash-flow question (**half-yearly, never quarterly**) and a decision
   for Aarsh about the window.
5. **E6-V (value: operating cash flow yield) — not chartered; blocked on a
   historical fundamentals source.** Exchange XBRL resolves from 2018,
   operating cash flow half-yearly from 2020, no balance sheet. Routes: BSE
   XBRL probe for 2011-2017 (queued after the shareholding backfill); a
   licensed database such as CMIE Prowess, pending a point-in-time check.
   See `docs/data/xbrl_results_finding.md`.

6. **Two things Aarsh must decide** before E2-A and E2-D can run as chartered:
   - **E2-A §3 names `DissemDT` as the point-in-time key, and BSE returns it
     as null for every announcement before 2016** — six of the seven years of
     E2-A's own development window. `NEWS_DT` is a near-perfect substitute
     (median gap 5.1 s, 0.009% cross a session boundary) but §3 is law.
   - **XBRL does not reach 2011.** Documents resolve only from 2018, and
     cash flow only from 2020.

---

# HANDOFF — 2026-09-23

Written at session close for whoever picks this up next. Everything here is
state, not opinion. Where something is unknown or unfinished it says so.

`pytest -q` at close: **440 passed, 0 failed.**

## Start here (2026-09-23)

1. **E1b re-run is DONE: INCONCLUSIVE** (was REJECT), recorded in
   `docs/reviews/E1b-verdict-rerun.md`. **The BSE backfill is COMPLETE**
   (2026-09-23): 6,109 of 6,109 days verified, 2010-01-01 → 2026-09-22 (§5).
   **E2-A is unblocked.** The world data (§5) is in too.
2. **Measurement correction of 2026-09-21 (E1 §15):** buys are sized net of
   costs instead of being skipped when costs don't fit, and expense drag
   compounds by calendar days; B3 and B5 both carry 0.30% a year. **The
   stack is now read from `experiments/E1/regression/`** (E1 base re-run
   under the correction): development **8.97% / 55.40%**, validation
   **27.36% / 39.82%**. Every stored number that moved is in
   `docs/STATE.md`.
3. **Repo:** github.com/aarsh-adhvaryu/portfolio_system (PRIVATE), branch
   `master`. A fresh clone passes all 425 tests. Until 2026-09-22 the
   unanchored `data/` in `.gitignore` also hid `src/pflab/data/` and
   `docs/data/`, so they had never been committed; the pattern is now
   `/data/`. Never re-widen it.
4. **Next experiment: E1d** (`docs/strategies/E1d.md`, draft). Four small
   code pieces before its first run: `docs/notes/E1d-readiness.md`. E1b is
   classified, so the code is free to change.

## 2026-09-19 session, in one paragraph

`PFLAB_DATA_DIR` is now set explicitly (CLAUDE.md "Repo layout"). Both E1b
sweeps were re-run with the corrected equity/cash decomposition and with
per-row equity curves, trade ledgers and decision records persisted; **every
row reproduced to within 1e-12, so E1b's REJECT is untouched.** E1c was
slotted after E1-P in `ROADMAP.md` and `GATE.md`, and E1b's S7 (sell-to-cash
during RISK_OFF) was added to E3 §7 as S6. **E1-P is finished** — §3's rule,
N1/N2, the sweep rows, the GATE wrapper and both missing §7 extras — and
**E1c is prepped** — the volatility-scaled 6+12 score, semi-annual rebalance,
capped score-tilted weights and eleven rows. Neither has been run; both wait
on Aarsh's lock, and each has a readiness note listing exactly what the lock
must settle. Sealed period untouched; `research/journal.jsonl` still absent.

**2026-09-19 — repo consolidated; paths in this file are current.** The
repository root is now `D:\portfolio_lab`. Previously the code sat two levels
down in `portfolio-lab/portfolio-lab/` while the charters, ROADMAP and GATE
also existed as separate top-level copies outside version control, so an edit
could land on the copy that was not law. Everything is now single-copy inside
the repo: charters and `GATE.md` in `docs/strategies/`, `docs/ROADMAP.md`, and
the superseded 2026-09-16 pre-lock E1 draft in `docs/archive/` clearly marked
as not law. E1 §2–§13 and E1b §3–§7 were verified byte-identical to commit
`0ae301e` through the move, and `pytest -q` re-ran green (362) from the new
root. See CLAUDE.md "Repo layout".

---

## 1. Current stack and every verdict so far

**The adopted stack is E1 base.** Nothing has replaced it.

### E1 — INCONCLUSIVE (2026-09-17)

Charter LOCKED 2026-09-17. Sweeps in `experiments/E1/sweeps/`.

| | development 2007–2016 | validation 2017–2021 |
|---|---|---|
| base CAGR (after tax, liquidation-adjusted) | 9.34% | 26.12% |
| base MaxDD | 55.38% | 39.55% |
| turnover/yr | 1.6952 | 1.3131 |
| B2 (Nifty 500 TRI) | 8.07% | 14.79% |
| B3 (Nifty 200 Momentum 30 TRI, 0.3% drag) | 13.48% | 20.25% |

§13 arithmetic: C1 (≥2 pp over B2) failed in development (+1.27 pp), passed
in validation. C2 (≥2 pp over B3) failed in both. Verdict INCONCLUSIVE
because C1 did not fail in *both* periods, which is what REJECT requires.

Diagnostic at `docs/notes/E1-diagnostic.md`, including the 2026-09-17
correction: finding 6 (under-diversification as capital grows) is **not**
supported by the validation extras — names held recovered to 17.7–29.2 in
2017–2021. Finding 3 (universe rank 240–340 in both periods) stands.

### E1b — REJECT (2026-09-18)

Charter LOCKED 2026-09-18. Verdict at
`experiments/E1b/sweeps/validation-4eaf560fb1319d16/verdict.json`.

GATE vs E1 base:

| period | G1 | G2 | G3 | G4 | CAGR gap | MaxDD gap | rows holding | turnover |
|---|---|---|---|---|---|---|---|---|
| development | ✗ | ✓ | ✗ | ✓ | +0.13 pp | −0.70 pp | 5/14 | 1.16 vs 1.70 |
| validation | ✗ | **✗** | ✗ | ✓ | **−10.73 pp** | **+4.02 pp** | 0/14 | 1.00 vs 1.31 |

REJECT because G1 fails in both periods **and** G2 (do no harm) is violated
in validation.

E1 §13 C1–C4, reported because E1b was a candidate base: C1 fails both
(+1.40, +0.59 pp over B2); C2 fails both (−4.01, −4.87 pp vs B3); C3 passes
development, fails validation (+5.65 pp); C4 **0 of 14 rows** in both.
Verdict REJECT.

E1b base: development 9.47% / 54.67%, validation 15.38% / 43.58%.

**What it means.** E1b confined E1's rules to the Nifty 200. In development
that changed almost nothing (+0.13 pp). In validation it cost **10.7 pp**.
E1's 26.12% in 2017–21 came from holding small caps *outside* the Nifty 200
during a small-cap boom. The diagnostic's "universe drift to rank 240–340"
was not a defect to correct — it was where the money came from. E1b is
mechanically healthy (zero ADV skips in validation, turnover 1.00, 24–32
names held, median turnover rank 100–122, no delistings) and simply earns
less.

Development review at `docs/reviews/E1b-development.md`.

**Both sweeps re-run 2026-09-19** with decomposition v3 and persisted
artifacts: `development-1996387124c166df` and `validation-14c240592c8fc806`.
**All fourteen rows and all four benchmarks reproduced to within 1e-12 in
both periods**, so every number above stands and the REJECT is untouched.
The originals (`development-26b23d4fbc273fea`,
`validation-4eaf560fb1319d16`) were NOT overwritten — the run id now carries
a source fingerprint, so changed code lands in a new directory. The verdict
still lives in the original validation directory.

---

## 2. Built and tested vs stubbed

**Built, tested, used in a real run:**
`tax/india_lots.py`, `execution/costs.py`, `eval/periods.py` (incl.
`truncate_end`, `truncate_membership`, seal + journal), `eval/metrics.py`,
`eval/artifacts.py`, `eval/sweep.py`, `eval/classify.py` (§13 C1–C5 and
GATE G1–G4), `signals/momentum.py`, `portfolio/crash_rule.py`,
`portfolio/construct.py`, `backtest/engine.py`, `backtest/hooks.py`,
`backtest/runner.py`, `data/` — `bhavcopy`, `panel`, `universe`,
`instruments`, `symbol_isin`, `indices`, `calendar`, `corporate_actions`,
`nse_corporate_actions`, `dividends`, `red_flags`, and this session's
`index_changes`, `index_captures`, `index_membership`, `name_map`.

**Stubs raising `NotImplementedError` (only these two):**
`execution/paper.py`, `execution/kite.py`. Both are Phase 4, on ADVANCE
only, and nothing has ADVANCED.

**Collectors exercised at scale 2026-09-22/23:** `bse_announcements.py`
(6,109 days, every one count-verified), `gdelt.py` (English + translingual,
matching the BigQuery backfill exactly).

---

## 3. E1-P — REJECT (2026-09-21)

LOCKED 2026-09-19; both sweeps run on the same code (`source_sha
a3945e6f1bb5b64c`). Verdict computed by `classify.classify_e1p` and written to
`experiments/E1-P/sweeps/validation-708202782ce1ef66/verdict.json`. Verdict
note: **`docs/reviews/E1-P-verdict.md`**; development review (Aarsh's):
`docs/reviews/E1-P-development.md`.

| period | G1 | G2 | G3 | G4 | CAGR gap | MaxDD gap |
|---|---|---|---|---|---|---|
| development | ✗ | ✓ | ✗ (1/6) | ✓ | +0.006 pp | +0.007 pp |
| validation | ✗ | **✗** | ✗ (0/6) | ✓ | **−1.04 pp** | **+3.02 pp** |

REJECT: G1 fails in both periods; G2 also violated in validation.

- The tax saving was not stable (0.24 pp in development, 0.06 pp in
  validation); the return cost was (0.23 pp, then 1.10 pp).
- §7 extra 1 has the same sign in both periods: deferred names underperform
  the names sold at the same month-end (−10.80 pp, −7.33 pp).
- **N1 (stop-loss) did not survive validation**: −4.74 pp against base, and
  the names it sold rose 9.5% afterwards. "If not, it was 2008" — it was.
- N2 (profit-take) was expensive in both periods.

**The stack stays E1 base.**

## 4. E1c — REJECT (2026-09-21)

Verdict computed by `classify.classify_e1c`, written to
`experiments/E1c/sweeps/validation-d1bff14844336e54/verdict.json`; note
**`docs/reviews/E1c-verdict.md`**. Both sweeps on frozen code
`455f61c0803632f2`; the development re-run reproduced all 13 rows exactly.

- **GATE: REJECT** — G2 violated in both periods (−2.54 pp / +14.81 pp
  deeper; then −6.02 pp).
- **C1–C4: INCONCLUSIVE.** **Mandate: not met** (§3 fails in development,
  §5 fails in both, with or without a B5 drag).
- **§6:** the fund's construction as a taxed SIP keeps about half of B3 in
  development (−6.68 pp) and nearly all of it in validation (−0.15 pp). C2
  is not restated. Weighting is worth 1–3 pp a year with no stable sign.
- Held in both periods: E1's raw 12-1 signal costs about 5 pp a year on the
  fund's cadence; E1's monthly band earns 1–2.5 pp over semi-annual.

**Open measurement flaw, not fixed** (E1 §5 buy sizing, Aarsh's call): a
benchmark buy that uses all its cash is skipped when costs don't fit, by
rupee rounding. Development B5 is overstated by 1.23 pp (15.37% should read
about 14.14%), B3 by 0.15 pp; nothing else moves and no verdict depends on
it. The benchmark expense drag also compounds per session over 365, so
B3's 0.30% applies as about 0.21%.

## 5. Backfills — state at 2026-09-23

**BSE announcements 2010-01-01 → 2026-09-22 (E2-A's input): COMPLETE.**
`python tools/backfill_bse.py --check 2010-01-01 2026-09-22` reports
**6,109 of 6,109 days verified, 0 missing, 0 blank** (2026-09-23). Every day
matches the API's own `Table1.ROWCNT`, recorded in the ledger
`data/bse_announcements/_verified.txt`. **E2-A is no longer blocked on data.**

Two collector defects were found and fixed while it ran; both are covered by
`tests/test_bse_collector.py`:

- **2026-09-22 — throttled answers saved as data.** Four parallel workers drew
  throttled responses that carried one all-null row, and 529 day files were
  written from them. `fetch_day` now keeps a day only if its announcements
  equal `Table1.ROWCNT` (a genuinely empty day reports 0) and raises
  `IncompleteDay` otherwise; `verify_file` re-checks saved days; the ledger
  records what is confirmed. Three workers proved safe; four throttle.
- **2026-09-23 — one day could never complete.** 2015-08-29 collected 113 of
  its 114 announcements on every pass. BSE had re-disseminated one
  announcement later the same day (Andhra Cements results, 14:58:51 and
  15:10:13), repeating its `NEWSID` with a new `DissemDT`, and `ROWCNT`
  counts both; de-duplicating on `NEWSID` alone dropped the second copy for
  ever. The key is now `(NEWSID, DissemDT)`. Identical repeats from paging
  overlap are still dropped. Re-collected: 114 of 114, verified.

**Collected by code 2026-09-22 (no Aarsh action needed):**

| item | file(s) | coverage | source, module |
|---|---|---|---|
| India VIX | `data/indices/INDIA_VIX.parquet` | 2008-03-03 → 2026-09-21, 4,586 sessions | NSE `historicalOR/vixhistory` (monthly: it caps answers at 70 rows, serves from 2010-07-19) + Yahoo `^INDIAVIX` only before that; overlap 3,971 days agree to median 0.0025 pt. `pflab/data/india_vix.py` |
| Brent, USDINR, US 10y | `data/macro/{BRENT,USDINR,US10Y}.parquet` | 1987 / 1973 / 1962 → mid-Sep 2026 | FRED `fredgraph.csv` (DCOILBRENTEU, DEXINUS, DGS10). NY-close prints: a month-end decision should read the previous day's. `pflab/data/macro.py` |
| FPI (FII) daily flows | `data/macro/FPI_DAILY.parquet` | 2009-12-01 → 2026-09-22, 4,049 report dates, 202 months, none failed; annual equity sums match published FPI totals | NSDL archive form, one post per month; keyed on custodian **report date** (covers trades up to the previous session). `pflab/data/fpi_flows.py` |
| GDELT India daily aggregate | `data/gdelt/agg/*.parquet` (4,216 day files) | 2015-02-18 → 2026-09-21; **18 days absent in GDELT itself** (2017-08-29, and 17 days from 2025-06-15), BigQuery has no rows for them either | Aarsh ran `tools/gdelt_bigquery.sql` 2026-09-22 (daily aggregate, keyed on DATEADDED); `tools/ingest_gdelt_backfill.py` loaded it (provenance `data/gdelt/backfill/_ingest.json`). **Collector fix:** `gdelt.py` now fetches the translingual feed as well as English (BigQuery holds both); English-only had undercounted by ~15%. Re-collected 2026-09-14/15 match BigQuery on every field |
| World markets (Yahoo) | `data/global/*.parquet`, 30 series | S&P 500, Nasdaq, Nikkei from 1970-71; FTSE, DAX, Hang Seng, CAC, ASX, Bovespa, KOSPI, Shanghai, TAIEX 1984-97; US VIX 1990; MOVE, EEM, LQD, TLT 2002-03; HYG, STOXX 50, Brent futures 2007; gold, silver, copper, WTI, gas, wheat 2000; dollar index, US 10y 1970-71; bitcoin 2014 | `pflab/data/global_markets.py`. Dates are the exchange's local date. **Point-in-time:** Asia closes before the NSE (day M usable at M); Europe, US, Brazil close after (use M-1). Cross-checked against FRED: VIX identical on 9,246 days, Nasdaq median difference 0 |
| More FRED (`macro.py`) | `data/macro/*.parquet`, 23 series | US VIX, WTI, broad dollar, 10y-2y and 10y-3m curves, fed funds, TED spread (ends 2022), Nasdaq, 30y mortgage, CNY/JPY/EUR; **REVISED (latest vintage only, not point-in-time):** St Louis stress, NFCI, Case-Shiller, housing starts, mortgage delinquency, unemployment, jobless claims, copper monthly | Revised series are for explanation; deciding on one needs ALFRED vintages (free FRED API key). ICE credit spreads skipped: FRED serves only 3 years; HYG/LQD stand in |
| GDELT world by country | `data/gdelt/world/daily_by_country.parquet` | 2015-02-18 → 2026-09-21, 980,954 rows, 266 countries (Aarsh, 2026-09-22). Checked: material-conflict events rose 21x (Ukraine, Feb 2022), 14x (Israel, Oct 2023), 23x (Iran, Jun 2025) | `tools/gdelt_world_bigquery.sql`, `tools/ingest_gdelt_world.py world` |
| GDELT world event types (20 CAMEO root codes) | `data/gdelt/world/daily_event_types.parquet` | 2015-02-18 → 2026-09-22, 981,187 rows (Aarsh, 2026-09-23). Checked against the world file: the 20 type counts reproduce `n_events` on all but 218 of 980,954 rows, 298 events of 912.7M unaccounted (codes outside 01–20) | `tools/gdelt_world_types_bigquery.sql`, `ingest_gdelt_world.py types` |
| GDELT bilateral (who acted against whom) | `data/gdelt/world/daily_bilateral.parquet` | 2015-02-18 → 2026-09-22, 2,902,731 rows, 18,133 country pairs, pairs with ≥10 events a day (Aarsh, 2026-09-23). Checked: RUS→UKR violence 36/day → 2,482 at the Feb-2022 invasion; ISR→IRN 13 → 2,012 in Jun 2025; IND→PAK 2 → 137 in May 2025 | `tools/gdelt_bilateral_bigquery.sql`, `ingest_gdelt_world.py bilateral` |
| **Known gap** | world-by-country file ends 2026-09-21, the other two end 2026-09-22 | the world query ran a day earlier; re-run `gdelt_world_bigquery.sql` when convenient. The daily collector keeps India only, so world days do not fill themselves | |
| GDELT GKG (topics, company names) | not collected | far larger table; needs a one-month size test before any pull | for the explanation layer |
| GDELT 1.0 India 1979–2015 | `tools/gdelt_v1_bigquery.sql` → `data/gdelt/v1_backfill/` | **waiting on Aarsh**; inspection only, not point-in-time before 2013 | |
| 23 sector indices, price + TRI | `data/indices/SECTOR_*_{PRICE,TRI}.parquet` (46 files) | 2004-01-01 → 2026-09-22 for most; Private Bank, Healthcare, Oil & Gas, Consumer Durables, Chemicals from 2005-04; Media 2005-12; Consumption 2006-01; Realty 2006-12; CPSE 2009-01 | niftyindices, `indices.SECTOR_SERIES` / `collect_sectors()`; not in `SERIES`, so `collect_all()` and the engine are unchanged. Which sectors, and price or TRI, is E1-S's charter to choose |

Re-run any of them: `india_vix.collect()`, `macro.collect()`,
`fpi_flows.collect()`, `indices.collect_sectors()` — each rewrites its files
whole. Not yet in `tools/collect_daily.py`.

**Everything else, unchanged since 2026-09-18 — needs Aarsh:**

| item | state | what it needs |
|---|---|---|
| Shareholding patterns | not started, no module | source decision (E2-D) |
| Point-in-time fundamentals | not started, no module | source decision |
| ETF dividends | not started (`data/dividends/` is equity dividends) | source decision (E3) |

## 6. Index-membership build

Built this session and **passing its gate**. Full write-up:
`docs/data/index_membership_finding.md`.

**Sources.** NSE's F&O "Change in the Constituents of Indices" circulars are
the *wrong* source — Nifty 200 appears in **zero** of all 98, because those
circulars exist to move F&O contracts and Nifty 200 has no derivatives. The
right source is NSE Indices' press-release archive
(`niftyindices.com/Press_Release/`), **1,486 releases 1998–2026**, plus
**72 Internet Archive captures** of the constituent CSVs (69 parsed) used as
anchors.

**State:** 4,203 changes parsed. Exact-list check — **Nifty 200 4/4, Nifty
100 21/21, Midcap 100 10/10, Nifty 500 13/14** (one miss: 2006-11-08,
`INE588A01016` absent, nothing invented). Nifty 100 = Nifty 50 + Next 50 on
the one date all three were captured. **The build exits zero.**

**Re-run:**

    python tools/build_index_membership.py --download   # network, ~20 min
    python tools/build_index_membership.py --parse      # PDFs -> changes, ~20 min
    python tools/build_index_membership.py --captures   # Internet Archive
    python tools/build_index_membership.py --build      # changes -> tables, ~1 min
    python tools/build_index_membership.py --all

Stages are separate and cached; only `--download` and `--captures` touch the
network. `--build` exits non-zero while the exact-list check fails, and the
fix is always more coverage, never a looser check.

**Key finding that shaped E1b §3/§4:** NSE's methodology says Nifty 200 is
"constituents forming part of Nifty 100 and Nifty Midcap 100" — but that is
written in the present tense. The captures show the two parents **overlapped
by 27 names in 2010 and 32 in 2014, and were disjoint only by 2026**. The
union identity became true at the 2016 restructure. So Nifty 200 membership
is published and exact from **2012-01-01**; before that E1b used a declared
**proxy** universe, labelled as such per month-end in the manifest.

---

## 7. Charter and doc lines added, by session

### 2026-09-19

**No §15 line was added to any LOCKED charter.** E1 §2–§13 and E1b §3–§7 were
re-verified byte-identical to `0ae301e` at the close, and neither file was
modified at all.

Changes landed only in DRAFT documents and in the map:
- `docs/strategies/E3.md` §7 — **S6 added** (sell-to-cash during RISK_OFF,
  E1/E1b's S7), on Aarsh's instruction, with two consequences declared and a
  §10 change-log line. E3 is DRAFT, so §7 is not law.
- `docs/ROADMAP.md` — order change **E1c after E1-P**, with the reasoning;
  E1b's entry corrected from "BLOCKED on data" to its REJECT verdict; an E1c
  section added; a broken link to the E1 diagnostic fixed.
- `docs/strategies/GATE.md` — order line corrected. It had carried the
  **pre-2026-09-18** order "E1, E1b, E1-P" since the swap, i.e. it was stale
  against ROADMAP for a day. Now E1, E1-P, E1c, with an "Order, and how it
  has changed" section so a stale copy is recognisable as stale.
- `CLAUDE.md` — `PFLAB_DATA_DIR` made explicit and documented; state section
  refreshed.
- New: `docs/notes/E1P-readiness.md`, `docs/notes/E1c-readiness.md`.

### 2026-09-18

**E1's §15 was NOT touched this session.** E1 §2–§13 are untouched since the
2026-09-17 LOCKED line.

E1b (`docs/strategies/E1b.md`, §10 change log), all dated **2026-09-18**:
- **LOCKED. No changes to §3–§7 after this line.**
- §3/§4 (draft, pre-lock): universe is Nifty 200 from 2012-01-01 and a
  declared proxy (CNX 100 ∪ CNX Midcap, point-in-time) for 2007–2011.
  Development stays 2007–2016, validation 2017–2021, with Aarsh's reasoning
  recorded: *the years being removed are the years the hypothesis is about.*
- §6 (draft): **S13** added — development restricted to 2012–2016 with E1
  base re-run on the same window.
- §6 (draft): **S12 revised** — no longer drops guessed-window names; places
  each guessed start at the latest possible date so base and S12 bracket the
  truth.
- §6 (draft): S12 originally added (superseded by the line above).

`CLAUDE.md` rule 7, 2026-09-18: **`pypdf` added** to the
allowed dependencies for the NSE constituent-change circulars, with
**`pdfplumber` as a named fallback**, permitted only for a circular whose
tables pypdf returns garbled. Declared in `pyproject.toml`.

`docs/ROADMAP.md`, 2026-09-18: order changed to **E1, E1-P, E1b,
E2-A, …** with the reason, the re-run-on-adoption rule, and E1b's
three-working-day time-box (which closed on time).

E1c `docs/strategies/E1c.md` §9: draft, 2026-09-18, written by Aarsh.

---

## 8. Open questions I was not comfortable resolving alone

1. ~~**The invested-equity metric took three attempts…**~~ **RESOLVED
   2026-09-19.** Version 3 shipped and both E1b sweeps were re-run on it.
   The base row reconciles: equity 8.67 pp + cash 1.38 pp = 10.05 against
   10.20% pre-tax (development). The corrected table is in
   `docs/reviews/E1b-development.md`; the version-2 `Invested equity alone`
   table survives only in the two ORIGINAL sweep directories and should still
   be ignored there.
2. ~~**`write_summary` overwrites unconditionally.**~~ **RESOLVED
   2026-09-19**, and the underlying hole was worse than described. A sweep
   now writes a `manifest.json` and **refuses** to overwrite a directory
   whose config, data, code or rows differ (`sweep.SweepConflict`).
   Separately, `run_id` hashed only `git rev-parse HEAD`, so **two different
   working trees at the same commit produced the same run id** — which is
   every session in progress. `artifacts.source_fingerprint()` now hashes
   every `.py` under `src/pflab` and `tools`, and `code_identity()` appends
   it whenever the tree is dirty, so changed code lands in a new directory
   instead of on top of the old one. Principle 9 says a run's identity is the
   hash of its config, data **and code**; it now is.
3. **Momentum-30 overlap (E1b §8) is unavailable and always will be for
   2007–2016.** The Internet Archive has that list only from 2021 and the
   index launched in the 2020s with back-computed levels. Measuring against
   today's 30 names would be a survivorship artefact, so the extras report a
   sentence. Whether that is acceptable for E1c (which replicates the fund)
   is Aarsh's call.
4. **The membership bracket may be wider than anything E1b could measure.**
   In development, base 9.47% vs S12 11.61% — a 2.14 pp spread from
   inclusion-date timing alone. E1b's REJECT rests on validation's −10.73 pp,
   far outside that, so the verdict is safe. But no *small* effect is
   measurable on the 2007–2011 proxy years.
5. **Whether E1's §13 C2 bar is honest at all.** E1c §6 exists to test this.
   If B3's 13.48% / 20.25% does not survive real trading and tax, then C2
   has been failing every experiment against an unbuyable number. I did not
   act on this; it is E1c's job.
6. ~~**E1c's S7 into E3 §7**~~ **RESOLVED 2026-09-19, with a correction.**
   The instruction was for **E1b's** S7 (sell-to-cash during RISK_OFF), not
   E1c's S7 (costs ×2) as this file previously said. E1b's S7 is the one that
   belongs in a charter about where RISK_OFF money goes. Added to E3 §7 as
   **S6**, with its two consequences declared (the sleeve carries realised
   equity gains, so §5's tax module sees a far larger flow; and re-entry is
   capped at six names a month, so a liquidated book takes months to
   rebuild). E3 is DRAFT, so §7 is not law yet. E1c's S7 stays costs ×2.
7. **Nifty 500's membership table is much weaker than Nifty 200's** (56% of
   names have a guessed window; `carry_back` median 676 d,
   `inferred_start` median 1,150 d). E1b's S10 used it. Any future row that
   leans on Nifty 500 membership should be read with that in mind.

---

## 9. The exact next tasks, in order

**1. E1b re-run — DONE 2026-09-22: INCONCLUSIVE** (`docs/reviews/E1b-verdict-rerun.md`).

**2. BSE backfill — DONE 2026-09-23** (§5): 6,109 of 6,109 days verified.
To extend it to today, run the same tool for the new range; it is idempotent:

    python tools/backfill_bse.py 2026-09-23 <today> data/_bse/progress_r1.jsonl

**3. E1d build, lock, run** (`docs/notes/E1d-readiness.md`).

**4. E3-R**, then **E2-A** (its data is ready), then the rest
(`docs/ROADMAP.md`).

**5. Data sources Aarsh owes** (§5): decisions on shareholding and
fundamentals only. Everything else was collected by code on 2026-09-22/23:
BSE, GDELT (India, world by country, event types, bilateral), India VIX,
FRED macro, FPI flows, sector indices, 30 world market series.

### Two notes for whoever runs a sweep next

- **Sweeps now persist per-row artifacts** under `rows/<row>/`:
  `equity.parquet`, `trades.parquet` and `decisions.json`, plus the four
  benchmarks. No future extra should ever need a re-run to recover a curve
  the run already had — three sweeps were lost to exactly that on
  2026-09-18. The two E1b directories re-run on 2026-09-19 carry curves and
  ledgers; `decisions.json` was added a few hours later, so they do not have
  it, and nothing E1b still needs reads it.
- **A sweep now refuses to overwrite a different run.** If you get a
  `SweepConflict`, the inputs genuinely differ — do not force it; look at
  what changed.

## 10. Seal

**The sealed period (2022–2025) has never been opened.**
`research/journal.jsonl` does not exist, which is the proof:
`periods.open_period` creates and appends to it only on a reveal, and only a
sealed period can trigger one. Zero reveal lines.

Re-verified at the 2026-09-19 close. Every run this session used
`development` or `validation`, both unsealed: two E1b sweeps and one single
E1 base run for the byte-identity check. Nothing under `experiments/*/sealed*`
was read or written.
