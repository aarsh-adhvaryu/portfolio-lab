# E3-R — readiness note (2026-09-26)

E3-R (`docs/strategies/E3-R.md`, DRAFT) replaces E1 §6's on/off trend
filter with three exposure gears. **No new data is needed.** It is
nonetheless the largest build any experiment has required so far, and
**three lines of the charter cannot be run as written**.

**NOT READY TO LOCK.** §3's four open questions need Aarsh first; §5 lists
what to build after.

**Change-log entries that apply** (CLAUDE.md non-negotiable 1): the
2026-09-19 draft, and the **2026-09-25 prediction** recorded before any
run — *E3-R passes only if the high gear's recovery return exceeds the
cautious gear's cost in 2017–2021.*

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
