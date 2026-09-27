# E2-D2 — readiness note (2026-09-27)

E2-D2 (`docs/strategies/E2-D2.md`, DRAFT, split from E2-D by Aarsh on
2026-09-27) makes a name ineligible when net insider selling in NSE's PIT
disclosures over the trailing two quarters exceeds 1.0% of market cap at M.
**Built and tested, with every open §4 choice as a config key that has no
default.** Two findings the lock should see before it sets them.

**READY TO LOCK once §3 is settled.**

**Change-log entries that apply** (CLAUDE.md non-negotiable 1): E2-D2 §9
(2026-09-27: the split; net value = sells minus buys in the trailing two
quarters; denominator = total reported shares outstanding × close at M;
next-month-end exit; bulk deals unavailable) and, from E2-D, 2026-09-24
(the PIT limb from 2016-01-01; NSE's feed the only source with values).

## 1. What was built

| piece | where | tests |
|---|---|---|
| PIT rows → ISIN **joined with the broadcast date** (panel's dated symbol map, rule 8); usable from the broadcast session, the next day after 15:30; signed value (Sell +, Buy −); rows with no positive value dropped and counted | `positioning.insider_rows` | `tests/test_positioning.py` |
| market cap at M = latest **reported** shares outstanding usable at M × close at M; a name with neither has no measure | `positioning.shares_outstanding_at`, `insider_exclusion` | same |
| engine `[insider_selling]`, refusing any missing §4 key and refusing a second exclusion rule alongside it; the decision records each excluded name's net value, market cap and ratio | `backtest/engine.py` | same (20 in the file) |
| `configs/e2d2.toml` (periods `e2a_development` / `e2a_validation`), `sweep.e2d2_rows()` (base, S1, S2), runner dispatch, `classify_e2d2` | | |

**STACK needs no new run**: E1 base on these exact windows is already on
disk as `experiments/E2-A/_stack_sd` and `_stack_sv`, the stack E2-A was
judged against (conditional on `tools/e1_identity.py` confirming E1 has not
moved).

## 2. On the real data (counts only; literal reading: all categories, all modes, six months)

6,731 PIT rows dropped for no positive value and 746 for a symbol with no
ISIN on its date, out of 262,283 in 2016–2021.

| year | names flagged (mean per month-end) | in E1's top-200 ranks | held by E1 base |
|---|---|---|---|
| 2016 | 50.3 | 7.8 | 0.8 |
| 2017 | 74.5 | 13.2 | 1.1 |
| 2018 | 70.2 | 11.2 | 2.8 |
| 2019 | 61.2 | 14.7 | 2.2 |
| 2020 | 51.6 | 14.7 | 3.8 |
| 2021 | 67.6 | 13.4 | 1.9 |

E1 base held a flagged name in **58 of 72** month-ends. The rule will act.

## 3. What the lock must settle

### (a) E2-D2 mostly re-measures E2-D1

Of all insider **sell value** 2016–2021, **79.1% is promoters and 14.0%
promoter group** — 93% together. Employees and designated persons, 62% of
the rows, are 2.5% of the value. So under the literal reading E2-D2's flags
are dominated by the same people E2-D1 measures, through a different
source. That is not wrong, but it means the two experiments are far from
independent tests, and the running count in `STATE.md` should be read with
that in mind. Restricting `categories` to non-promoter insiders would make
E2-D2 a distinct question; that is a change of rule, and the lock's to make.

### (b) Most of the sell value is not a market sale

| `acq_mode` | share of sell value | net of the same mode's buys |
|---|---|---|
| Market Sale | 43.2% | 100% (a sale) |
| Inter-se-Transfer | 25.7% | **−3%** (nets out, as it should) |
| Others | 17.3% | **80% net selling** |
| Off Market | 6.7% | 64% net selling |
| Scheme of amalgamation/merger/… | 5.9% | −62% (net buying) |
| Gift | 0.5% | |

Inter-se transfers net out in aggregate, so "all modes" does not
double-count them overall — but only when both legs land inside the same
six-month window for the same ISIN. "Others" and "Off Market" are a quarter
of the selling and carry no further description in the feed. Choices:
market modes only; all modes; all except schemes and inter-se.

### (c) E2-D2 §4's four items, with the built readings

1. **Window**: six calendar months ending at M (built as `window_months`),
   or the two most recent completed calendar quarters (not built).
2. **Categories**: `"all"` or a list (built).
3. **Modes**: `"all"` or a list (built); see (b).
4. **Rows without a value**: dropped and counted (built). Valuing them at
   quantity × close would need a price on the transaction date — not built.

### (d) S3 is not built

§6's S3 — "insider net buying > 1% as a tiebreak among entry candidates" —
needs a definition first: E1 ranks by 12-1 momentum, where exact ties
almost never occur, so a literal tiebreak does nothing, and anything
stronger (preferring net-buying candidates) is a second rule. The lock
should define it or drop it.

### (e) Close at M

A name that did not trade on the month-end session has no close at M and
therefore no measure. The alternative, its last close on or before M, is a
one-line change; say which.

## 4. Runs, after the lock (Aarsh's)

| run | command (from `D:\portfolio_lab`) |
|---|---|
| E2-D2 development | `.\tools\run_locked.ps1 -Experiment E2-D2 -Period e2a_development` |
| E2-D2 validation (after the development review) | `.\tools\run_locked.ps1 -Experiment E2-D2 -Period e2a_validation` |

`tools/check_lock.py` needs an `E2-D2` entry (§3–§8) at the lock.
