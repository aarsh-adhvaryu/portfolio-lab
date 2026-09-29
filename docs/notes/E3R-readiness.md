# E3-R — readiness note (2026-09-26)

E3-R (`docs/strategies/E3-R.md`, DRAFT) replaces E1 §6's on/off trend
filter with three exposure gears. **No new data is needed.** It is
nonetheless the largest build any experiment has required so far, and
**three lines of the charter cannot be run as written**.

**2026-09-27: BUILT — READY TO LOCK once §8 is settled.** Aarsh decided §3's
four questions (E3-R §11, 2026-09-27); the build is §7, what the lock must
settle is §8. §1–§6 below are the original note, kept as written.

**Change-log entries that apply** (CLAUDE.md non-negotiable 1): the
2026-09-19 draft, and the **2026-09-25 prediction** recorded before any
run — *E3-R passes only if the high gear's recovery return exceeds the
cautious gear's cost in 2017–2021.* **From 2026-09-29 (§9): LOCKED against E1 + E1d**;
every §11 entry applies — 2026-09-19, 2026-09-25, 2026-09-27 (a)–(d),
2026-09-27 (e), 2026-09-29 stack, 2026-09-29 lock — plus E1 §15 and E1d §10
for the stack.

## 1. The evidence in §2 still holds under the measurement correction

§2 rests partly on this project's own S7 rows, and those were quoted from
sweeps that predate the 2026-09-21 correction. Re-read from the corrected
re-runs:

| §2 quotes | corrected re-run | holds? |
|---|---|---|
| E1b validation 24.1% vs 43.6% | **24.31% vs 43.34%** | yes |
| E1b development 49.2% vs 54.7% | **49.51% vs 54.96%** | yes |

The drawdowns are within rounding of the quoted figures, so the
hypothesis's own evidence is intact. Worth having checked: E1b's *verdict*
did change under the correction (REJECT → INCONCLUSIVE), so its rows could
have moved too.

## 2. What the engine already supports

| E3-R line | supported? |
|---|---|
| §3 **T** — Nifty 50 month-end below its 10-month average | **yes** — `crash_rule.risk_off`, E1 §6 unchanged |
| §5 window, benchmarks B1–B5 | **yes** |
| §6 S9 costs ×2 | **yes** |
| §6 S8 India VIX | **data yes** — `data/indices/INDIA_VIX.parquet`, 2008-03-03 onward; the charter already declares S8 "from 2009" |
| §8 extras (gear months, exposure, tax paid) | **mostly** — needs a gear column on the decision record |

## 3. Four things that cannot be run as written

### (a) The V signal cannot exist for the first months of development

§3's **V** is the 126-session realised volatility of a top-25 basket,
compared with **its own trailing 36-month 80th percentile**. That series
needs 126 sessions to produce its first value and then 36 further months
before a percentile exists. The panel starts 2004-01-01, so:

- first V value ≈ 2004-07
- first V *percentile* ≈ **2007-07**

Development starts **2007-01-01**. So for roughly the first six months of
development, **V is undefined** — and §4's cautious condition is
`T and (V or B)`, which does not say what to do when one input has no
value yet.

Three readings, and the charter must pick one: treat undefined V as
false (cautious then needs T and B); require both V and B to be defined
before any cautious month (no cautious gear until 2007-07); or start
development at 2007-07. **I have not chosen** — each changes the 2008
result, which is the period the hypothesis is most about.

### (b) The sell-down lot order is cross-name, and the book is FIFO per name

§4 orders sell-down lots "realised loss first, then long-term lots, then
short-term lots with the smallest gain". That is a ranking **across the
whole book**, and `tax/india_lots.py` sells FIFO **within one ISIN**. There
is no existing path that says "raise ₹X from wherever it is cheapest to
raise it", and building one touches the tax module, which every other
result depends on.

The charter is also silent on a tie-break within a category and on whether
a partial lot may be sold. Both change the tax bill, so both need saying.

### (c) The high gear holds an index as a position, and the engine cannot

§4's high gear buys "the Nifty 500 index security (as used for B2)". In
this engine an index is **not a holdable security**: `run_index_benchmark`
builds a synthetic one-row panel with an `IDX:` ISIN and runs a separate
backtest on it. To hold it inside the strategy, the index must be injected
into the main panel as a tradeable row, which then puts it in front of the
universe filter, the ADV guard and the turnover-rank extras.

None of that is hard, but it is not "no new data and no new mechanism",
and the decisions it forces are the charter's: is the index row exempt
from §2's eligibility, and from the ADV guard? It has no traded value in
the panel, so as written the guard would skip every buy.

### (d) The high-gear holding has its own disposal schedule

"sold only once it is long-term, in thirds over the following three
month-ends" is a position with a lifecycle no other holding has: it
ignores the band, ignores the score, and is disposed on a clock. That is
new engine state, and the charter should say what happens if the gear
turns cautious again while it is still being sold down.

## 4. One thing the charter gets right that is worth naming

§4's cautious gear sells "at most half the excess per month", which means
a crash that arrives faster than two months is only half-hedged by the
time it is over. That is a real limit and the charter does not hide it —
and E1d's verdict is the reason to expect it to bite: **S7 there
(sell-to-cash) produced an identical worst fall to the base row**, 49.54%,
because the fall happened before a month-end signal could act. E3-R's
gears are monthly too. The prediction recorded on 2026-09-25 is the right
frame: the cautious gear will cost something, and the high gear has to pay
for it.

## 5. What to build, once §3 is settled

1. **`signals/regime.py`** — V and B as point-in-time series, with V's
   percentile window declared and its undefined period explicit rather
   than silently false.
2. **A target-equity mechanism** in the engine: today `risk_off` is a
   boolean that blocks buys. E3-R needs a target level, a sell-down
   schedule and a gear recorded per month-end.
3. **Cross-book lot selection** for the sell-down order, in `tax/`, with
   its own tests — this is the piece most likely to introduce a
   tax-accounting error, because it is the first code that chooses lots
   for a reason other than FIFO.
4. **A holdable index position**: inject B2's series into the panel under
   a declared ISIN, exempt where the charter says so, with the expense
   drag and equity tax class applied.
5. **`classify_e3r`** — GATE against the stack plus the mandate block.
6. **`configs/e3r.toml`** and `sweep.e3r_rows()` for §6's ten rows.

Estimated: the largest of the four lanes, and (2) and (3) are the ones
that can quietly change results elsewhere, so both need byte-identity
re-runs of E1 base afterwards.

## 6. Readiness

**Not ready to lock.** Nothing here is blocked on data. It is blocked on
four charter decisions — V's undefined period, the lot-order tie-breaks,
the index position's exemptions, and what interrupts the high-gear
disposal — and each one changes a number, so none should be decided by
whoever writes the code.

---

## 7. Build (2026-09-27), after Aarsh's four decisions

**Change-log entries that apply:** E3-R §11 — 2026-09-19 draft,
2026-09-25 prediction, **2026-09-27 decisions (a)–(d)**.

| piece | where | tests |
|---|---|---|
| T, V, B as month-end series; undefined kept as `None` and counted as not firing; the gear state machine | `signals/regime.py` | `tests/test_regime.py` (6) |
| sell-down: names ranked by FIFO tax cost per rupee (loss → long-term → short-term, lowest tax per rupee, weakest score), whole names then one partial in whole shares | `portfolio/selldown.py`; `india_lots.py` **unchanged** | `tests/test_selldown.py` (5, incl. FIFO within the chosen name) |
| target-equity mechanism: `trend_filter = "gears"`; each decision carries its gear, signals, equity share, sell-down plan or NIFTYBEES tranche; execution through a wrapper that calls E1's own `_execute` for exits and buys | `backtest/engine.py` (`_gear_setup`, `_annotate_gear`, `_execute_gears`) | `tests/test_e3r_engine.py` (12) |
| the 2019-12-19 ETF split and ISIN switch, declared, ETF rows only, applied after truncation when a config sets `data.etf_events` | `data/etf_events.py`, `runner.prepare` | `tests/test_etf_events.py` (5, incl. the real panel) |
| months with undefined V, per row, in the sweep manifest | `sweep.run_sweep` | |
| §8 extras: gear months and equity share by year, false alarms, gains realised by gear sales, worst fall in each named episode | `artifacts.e3r_extras` | yes |
| `configs/e3r.toml`, `sweep.e3r_rows()` (base + S1–S10), runner dispatch, `classify_e3r` (GATE + mandate + the 2026-09-25 prediction) | | yes |

**Byte-identity of E1.** `tests/test_engine_golden.py` holds three E1
configurations (SMA-10, sell-to-cash, filter off, RISK_OFF firing in 29
months) to digests captured from the engine **before** these changes and
confirmed on HEAD c33feb3's own code in a detached worktree. They still
match after the target-equity mechanism and after the sell-down code. The
real-data check — E1 base development and validation against
`experiments/E1/regression/` — is `tools/e1_identity.py`, queued in
`docs/RUNNING.md` for Aarsh (a long job).

**Bug caught by a test during the build**: the engine's `_month_ends`
returns a set, so the first gear path ran over month-ends out of order —
which breaks "two consecutive cautious month-ends". Fixed by sorting;
`test_undefined_v_months_are_recorded_and_do_not_fire` is the guard.

### On the real data (signals only, no returns; 30 s)

| | development 2007–2016 | validation 2017–2021 |
|---|---|---|
| months V undefined (§11 (a)) | **11: 2007-01 → 2007-11** | 0 |
| T / V / B fire | 40 / 33 / 31 | 11 / 6 / 11 |
| cautious / normal / high months | **35 / 78 / 7** | **9 / 48 / 3** |
| cautious spells | 2008-03→2009-03, 2011, 2013-07→09, 2015-04→2016-03 | 2018-10, 2019-01/02, 2019-07/08, 2020-03→06 |

V is undefined longer than the "about 2007-07" §3(a) estimated, because V's
basket is the top 25 **by the stack's score**, and 12-1 momentum needs 252
sessions before it exists; V's first value is 2004-12, and its percentile
over 36 previous values first exists in 2007-12.
**T does not fire before 2008-03**, so decision (a) changes no gear in
practice.

NIFTYBEES's adjusted series is continuous after the fix (largest one-day
move 14.6%, the 2009-05-18 election rally).

## 8. What the lock must settle

1. **The ADV guard may block the high gear where it matters most.** §11 (c)
   applies E1 §7's guard to NIFTYBEES, and §7 *skips* a buy over 1% of
   20-session traded value — it never fills part of one. At the seven
   development high months that 1% was **₹3.3–6.8 lakh**:

   | high month | 1% of NIFTYBEES 20-session ADV |
   |---|---|
   | 2009-04 | ₹6.82 lakh |
   | 2011-03 / 07 / 10 | ₹6.08 / 3.86 / 4.91 lakh |
   | 2012-02 | ₹6.63 lakh |
   | 2013-10 | ₹3.32 lakh |
   | 2016-04 | ₹5.90 lakh |
   | validation 2019-03 / 09, 2020-07 | ₹8.14 / 14.73 / 26.23 lakh |

   After 2008–09's thirteen cautious months the waiting cash is at least
   the SIP alone (₹6.5 lakh) plus the sell-downs, so **the 2009-04 high
   month — the one the hypothesis is most about — is likely skipped**, and
   the cash then re-enters through E1's six-a-month buys, i.e. S6. I have
   not run the engine to confirm, since that is the run. The lock can
   accept it (the guard is the guard), or say whether a high-gear buy is
   filled up to the guard's limit instead of skipped.
2. **Readings built in, to confirm** (each is in the code's docstrings):
   V's percentile over the 36 *previous* month-end values, all required;
   V's basket rebalanced daily, sample std of 126 daily returns; B over each
   name's own 200 rows; the sell-down amount = fraction × (equity after the
   month's band exits − target × (equity + cash)), priced at M's close; lots
   long- or short-term as of M; tax per rupee = 20% × short-term gain +
   12.5% × long-term gain over the position, before set-off and exemption;
   tranches sell this month-end and the next two **normal** ones, waiting
   through cautious and high months; the high month still runs the band
   exits, buys no stock, and puts all cash into NIFTYBEES; S7's high month
   buys the stack's names with no six-name cap; the gear machine starts
   each period in normal gear.
3. **Costs**: the cost model charges the stock STT (0.1% each side) on
   NIFTYBEES; the ETF rate is 0.001% on the sell only. The high gear's costs
   are overstated by about 0.2% a round trip. Declared in `classify_e3r`.
4. **Dividends**: NIFTYBEES has **no dividend rows**. It tracks the Nifty 50
   *price* index over 2008–2013 (0.47% vs 0.43% price vs 1.58% TRI), so the
   high gear is understated there by up to ~1 pp a year of holding
   (`docs/notes/E3-readiness.md` §3(b)). Declared in `classify_e3r`.
5. **S8** (India VIX): its percentile exists from **2011-03** (VIX begins
   2008-03), not 2009 as §6 says; before that S8's cautious gear is T and B.
6. **The ETF fix is a data fix**, logged in §11 at the lock with its
   evidence (`data/etf_events.DECLARED`).
7. `tools/check_lock.py` needs an `E3-R` entry (§3–§7) at the lock.

## 9. Stack move and lock (2026-09-29, session 6)

**Change-log entries that apply:** E3-R §11 — 2026-09-19 draft,
2026-09-25 prediction, 2026-09-27 (a)–(d), 2026-09-27 (e) split high-gear
buy, **2026-09-29 stack E1 + E1d**, **2026-09-29 lock** (§8 readings 2–6
accepted as built). Stack: E1 §15 (through 2026-09-28) and E1d §10.

- **Stack**: `configs/e3r.toml` is `configs/e1d.toml` plus `trend_filter =
  "gears"` and the `[gears]`/`[data]` blocks; `[stack]` names `e1d.toml`.
  The engine's gear path reads the stack's score through `score_fn` (V's
  basket; the sell-down tie-break); E1's path is unchanged
  (`test_engine_golden.py`). New test: the basket moves with the signal.
- **Signals on today's panel** (no returns):

  | | development 2007–2016 | validation 2017–2021 |
  |---|---|---|
  | V undefined | 11: 2007-01 → 2007-11 | 0 |
  | T / V / B fire (E1 + E1d) | 40 / 32 / 34 | 11 / 7 / 12 |
  | cautious / normal / high | **38 / 77 / 5** | 9 / 48 / 3 |
  | high months | 2009-04, 2011-03, 2012-02, 2013-10, 2016-05 | 2019-03, 2019-09, 2020-07 |

  E1's score on today's panel gives the same gears (V fires 34); §7's
  35 / 78 / 7 predates the 2026-09-27 D1/D2 panel repairs.
- **Span**: §3–§7, 2,757 chars, SHA-256 `e1cf6470…c9599df`
  (`check_lock` `E3-R`). Tag `lock/E3-R`; worktree `D:\pl_runs\E3-R`.
- **STACK for `classify_e3r`**: E1d's full sweeps at `c6ef67e`
  (`experiments\E1d\sweeps\development-924cec1bb3dd9ff9`,
  `validation-a0e0f5aa78dc160f`). The engine has changed since, behind
  flags only (E5-A's `precomputed` signal; the gear path's `score_fn`).
  **Decision for Aarsh:** use those, or re-run E1d base at `lock/E3-R` as
  E5-A §8 does.
