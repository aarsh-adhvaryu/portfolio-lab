# E3 — readiness note (2026-09-27)

E3 (`docs/strategies/E3.md`, DRAFT) sends RISK_OFF cash to whichever of a
liquid, gold or Nifty 50 ETF is trending strongest. Readiness note only, as
instructed; nothing built.

**The three ETFs are in the panel, but the data has an error that must be
fixed first**: a unit split on 2019-12-19 that the panel does not adjust,
followed by an ISIN change the next day. The tax and cost modules do not yet
distinguish instruments, which §5 already says is new work.

**NOT READY TO LOCK** — §2 is a data fix, §4 lists what the lock must say.

**Change-log entries that apply** (CLAUDE.md non-negotiable 1): the
2026-09-16 draft, and **2026-09-19 — S6 added** (sell-to-cash during
RISK_OFF), on Aarsh's instruction, with its two declared consequences.

## 1. Data coverage

| §3 candidate | in the panel | window notes |
|---|---|---|
| LIQUIDBEES | INF732E01037, 2004-01-01 → 2026-09-16, one missing session in 2008–2021 | price pinned at ₹1,000 (999.51–1,000.88); the return is paid as daily dividend units. **No dividend rows** |
| GOLDBEES | **two ISINs**: INF732E01102 2007-03-19 → 2019-12-19, INF204KB17I5 2019-12-20 → | 10-month return defined from 2008-01; E1's first RISK_OFF month is 2008-03, so gold is available at every RISK_OFF decision. No dividend rows (gold ETFs pay none) |
| NIFTYBEES | **two ISINs**: INF732E01011 2004-01-01 → 2019-12-19, INF204KB14I2 2019-12-20 → | full window. **No dividend rows** — see §3 |

All three are typed `ETF` and excluded from E1's universe, as §3 of E3 and
E1's 2026-09-16 §15 entry intend.

E1 base is RISK_OFF in **40 of 120** development months and **11 of 60**
validation months (its regression decisions), so the sleeve exists often
enough in development for §4 to matter, and in validation it is mostly
2020.

## 2. Data error: the 2019-12-19 unit split

| | 2019-12-18 close | 2019-12-19 close | `adj_factor` | 2019-12-20 |
|---|---|---|---|---|
| NIFTYBEES | 1,292.54 | **130.20** | 1.0 | new ISIN INF204KB14I2 at 130.34 |
| GOLDBEES | 3,359.60 | **33.55** | 1.0 | new ISIN INF204KB17I5 at 33.65 |

A 1:10 split for NIFTYBEES and 1:100 for GOLDBEES (the Reliance → Nippon
scheme transfer). The panel's adjustment factors come from NSE's *equity*
corporate-actions feed, which does not carry ETF unit splits, so the
adjusted series show a **−89.9%** and **−99.0%** one-day fall, and the
engine would then see the old ISIN stop trading — a delisting.

Every other one-day move above 8% in the three series over 2004–2021 is a
real market day (2004-05-17, 2008-10, 2009-05-18's +14.6%, 2020-03-23).

**Why it matters here and not before:** no past result touches it — E1's
universe is stocks only and the benchmarks use index series. But E3 holds
these ETFs, and **S3 ("hold the sleeve through RISK_ON until it breaks its
own 10-month average") would very likely hold gold across December 2019**:
E1 was RISK_OFF in 2019-07/08 and gold was in an uptrend. E3-R's high gear
holds NIFTYBEES too (its decision (c) asks for exactly this check).

**The fix** (to be built with E3-R, which needs it first): a declared ETF
event table — the two splits with their factors, and the two ISIN
successions — applied to ETF rows only, on the path after
`truncate_end`. Stock rows are untouched, so E1's bytes cannot move; a
byte-identity re-run of E1 base proves it. Logged in the charter's change
log when E3 locks, per `GATE.md` ("fixed, logged, re-run from scratch").

## 3. What cannot be run as written

### (a) The liquid ETF is handicapped against the stack's own cash

§5 models the liquid ETF as **5.5% taxed at slab** (31.2%), about **3.8%
after tax**. E1's liquid sleeve — the stack's cash, which STACK holds in
every RISK_OFF month — accrues a **flat 6% untaxed** (`cash_rate_annual`,
E1 §4; the engine applies no tax to it). So whenever no ETF is above its
trend and §4 falls back to the liquid ETF, **CAND's cash earns about
2.2 pp a year less than STACK's by construction**, and the comparison
measures the modelling difference as much as the rule.

The lock should say which it means: the liquid ETF at E1's cash terms (so
the fallback is "stay in cash" and the rule is only the trend switch), or
both books on the 5.5%-at-slab model (which is a change to STACK, i.e. a
second change), or accept the handicap and declare it.

The instruction's note — §5 allows 5.5% at slab if dividend history is
missing — is confirmed: there is no LIQUIDBEES dividend history in the
table.

### (b) NIFTYBEES's return is understated where its dividends were paid out

NIFTYBEES has no dividend rows. Compared on the old ISIN before the split:

| | NIFTYBEES | Nifty 50 price | Nifty 50 TRI |
|---|---|---|---|
| 2004-01 → 2019-12 | 12.64% | 12.20% | 13.68% |
| 2008-01 → 2013-12 | **0.47%** | **0.43%** | 1.58% |
| 2014-01 → 2019-12 | 12.60% | 11.75% | 13.18% |

In 2008–2013 it tracks the **price** index, consistent with dividends paid
out to holders and absent here; from 2014 its gap to the TRI (≈0.6 pp) is
about what expenses and tracking explain. So the Nifty-ETF candidate is
**understated by up to about 1 pp a year in development**, which biases the
sleeve's choice toward gold and cash. This is a statement about the data,
not a correction; the fix would be the scheme's payout history, which is a
source decision.

### (c) The tax and cost modules are equity-only

`tax/india_lots.py` taxes every lot at equity rates, and the
`hooks.tax_class` extension point is declared but consumed nowhere.
`execution/costs.py` charges one STT schedule (0.1% each side, the stock
rate) on everything. §5 needs:

- gold ETF: short-term (≤ 12 months) at slab, long-term 12.5%, no STT;
- Nifty ETF: equity rates, STT on sell only at the ETF rate;
- liquid ETF: per (a);
- per-instrument STT in the cost model.

§5's rates are today's. Before 2023 gold ETFs were taxed like debt funds
(36-month long-term threshold, 20% with indexation). E1 applies today's
equity rules across history, and the charter should say E3 does the same
for gold, declared.

### (d) Two smaller readings

1. **§4 "10-month return"** — month-end to month-end over 10 months, on
   the adjusted close (after §2's fix); and "10-month average price" —
   the mean of the last 10 month-end closes, as E1 §6 computes it for the
   index. Confirm.
2. **The hysteresis rule** ("switched only if a different candidate leads
   by more than 2 pp") needs its reference: 2 pp on the 10-month return,
   and the incumbent keeps the sleeve if it has dropped below its own
   average but no alternative is above its own? §4 is silent on the
   incumbent falling out of trend while RISK_OFF persists.

### (e) The stack E3 is a change to

E3 acts on E1's RISK_OFF. If E3-R is adopted first, "RISK_OFF" is no longer
a state of the stack — the gears replace it — and E3 would need restating
against the cautious gear. Under `GATE.md`'s parallel-running rule 2 that is
a re-run, but here it is also a re-*charter*, since the trigger itself
changes. Worth deciding before E3 locks whether it waits for E3-R's verdict.

## 4. What the lock must settle

1. **§3(a)** — the liquid ETF against the stack's 6% untaxed cash.
2. **§3(b)** — accept and declare NIFTYBEES's understated development
   return, or source its payout history first.
3. **§3(c)** — today's tax rules applied across history for gold, declared.
4. **§3(d)** — the 10-month definitions, and the incumbent-out-of-trend case.
5. **§3(e)** — whether E3 waits for E3-R.
6. **§2's data fix** is not a decision; it is logged in §10 when E3 locks.

## 5. What would need building (not built)

| piece | note |
|---|---|
| ETF split and ISIN-succession table, applied after truncation | built with E3-R (needs it first); byte-identity re-run of E1 base |
| per-security tax class in `india_lots` (slab / 12.5% / equity) | the piece most likely to introduce a tax error; its own tests |
| per-instrument STT in `CostModel` | small |
| sleeve logic: candidate trend, hysteresis, sell at first RISK_ON | an engine path beside the RISK_OFF block |
| §8 extras: months in each sleeve, sleeve vs cash over RISK_OFF months, sleeve tax | small |
| `classify_e3`, `configs/e3.toml`, `sweep.e3_rows()` | small |

**Not ready to lock.** §2's fix will exist after the E3-R build; §4's five
items need Aarsh.
