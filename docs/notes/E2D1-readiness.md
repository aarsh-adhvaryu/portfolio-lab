# E2-D1 — readiness note (2026-09-27)

E2-D1 (`docs/strategies/E2-D1.md`, DRAFT, split from E2-D by Aarsh on
2026-09-27) makes a name ineligible when its promoters' **shares** fell by
more than 1.0% of shares outstanding over the trailing two reported
quarters. **Built and tested.** One data problem the lock must settle
before it is run, and four readings to confirm.

**READY TO LOCK once §3 is settled.**

**Change-log entries that apply** (CLAUDE.md non-negotiable 1): E2-D1 §10
(2026-09-27: the split, shares not percent, pledge invocations count,
next-month-end exit, bulk deals unavailable) and, carried from E2-D, the
2026-09-24 amendments (promoter holding 2010 onward; undated quarters
usable from the second month-end after quarter end).

## 1. What was built

| piece | where | tests |
|---|---|---|
| promoter quarters with usable dates; two-quarter change in shares, split/bonus restated; flags at M; scrip → ISIN at M | `src/pflab/data/positioning.py` | `tests/test_positioning.py` |
| engine: `[promoter_selling]` → the exclusion set at each month-end; a held name leaves through `_decide`'s existing "ineligible" exit; each decision records what was excluded and why | `backtest/engine.py` (inert without the config block; refuses a missing threshold, and refuses E2-A's rule alongside it) | same file |
| period `e2d1_development` 2010-01-01 → 2016-12-31 | `configs/evaluation_periods.toml` | |
| config — E1 as locked plus the one block | `configs/e2d1.toml` | |
| §7 rows S1–S4; S4 not applicable in validation (GATE, 2026-09-25) | `sweep.e2d1_rows()`, runner dispatch | yes |
| `classify_e2d1` — GATE vs E1 base plus the mandate block, no C1–C4 | `eval/classify.py` | yes |

15 tests, among them: a bonus between the quarters is restated rather than
read as buying; a new issue with unchanged promoter shares is not selling;
a filing after 15:30 is usable the next day; an undated quarter is usable
only from the second month after; a missing comparison quarter gives no
measure rather than an older pair; nothing usable after the period end
loads; the flag attaches to the ISIN the scrip carries at M; and an engine
run in which a held name trips the rule, exits that month as "ineligible"
and is never bought back.

**A correction to `docs/notes/E2D-readiness.md` §3**, which said a forced
month-end exit "needs code". It does not: `_decide` already exits any held
name that is not in the eligible set, and the exclusion removes it from
that set. E2-A's exclusion used the same path.

## 2. On the real data (counts only; no return computed)

Built from `data/bse_shareholding/summary.parquet` and the NSE
corporate-actions table in 1 s; evaluating all 144 month-ends takes 4 s.

| year | names flagged at a month-end (mean) | of them in E1's top-200 ranks | of them held by E1 base |
|---|---|---|---|
| 2010 | 18.7 | 0.9 | 0.0 |
| 2012 | 88.6 | 5.8 | 0.8 |
| 2014 | 108.8 | 8.0 | 1.2 |
| 2016 | 113.0 | 9.4 | 0.9 |
| 2018 | 177.9 | 14.7 | 3.3 |
| 2020 | 139.1 | 17.2 | 3.2 |
| 2021 | 167.2 | 14.6 | 2.3 |

**E1 base held a flagged name in 92 of 144 month-ends** (215 name-months).
Unlike E2-A, whose flags rarely touched the book, this rule will act.

## 3. The data problem: unexplained share-count falls read as selling

Across 128,908 two-quarter pairs the measure is centred where it should be
(median 0.0), but the tails are not promoter trading: 0.1% of pairs show a
"sale" of more than 62% of the company, the largest over 100 times it. Each
is a quarter in which **shares outstanding itself shrank** — a capital
reduction, a consolidation, a scheme of arrangement — with no share-count
action in the corporate-actions table to restate it.

Among the **5,349 flag pairs** of 2010–2021 (selling > 1%), comparing
shares outstanding before and after, restated for recorded actions:

| shares outstanding, earlier ÷ later | flag pairs |
|---|---|
| grew more than 5% (issuance) | 211 |
| within ±1% (the ordinary case) | 3,993 |
| **shrank 5–50%, unexplained** | **658** |
| **shrank more than 50%, unexplained** | **208** |

So **866 flags (16%) coincide with an unexplained fall in the share count**,
and **124 of the 126 flags above 50% "sold"** are among them. It is not the
dating convention: 13.5% of undated-era flags and 18.2% of dated-era flags.

Some of the 5–50% band will be real — a buyback in which promoters tender
is a promoter sale and shrinks the share count — so this cannot be cleaned
by a rule I choose. Three options for the lock, each a different rule:

1. **Accept and declare**: the measure counts every fall in promoter
   shares, whatever caused it.
2. **No measure where shares outstanding shrank by more than a stated
   amount unexplained** — the pair is treated as unreadable, the name not
   flagged. The amount is the charter's.
3. **Source the missing actions** (capital reductions and schemes from the
   BSE announcements or the NSE feed's unparsed purposes) and restate
   properly. A data build, not a decision.

## 4. Readings to confirm (E2-D1 §4, plus two of mine)

1. Split/bonus restatement with the engine's own share-count rule.
2. Denominator: later quarter's shares outstanding, reported from Dec 2015,
   derived before.
3. "Two reported quarters" = latest usable quarter vs the quarter two
   before, both usable at M; if that one is missing, no measure.
4. Pre-2016 complete promoter exit reads as missing, not as a sale.
5. *(mine)* A filing after 15:30 is usable the next day — E2-A §3's cutoff,
   applied here because a month-end decision is made at the close.
6. *(mine)* "Usable from the second month-end after its quarter end" is
   implemented as usable at the month-end **decision** of that month
   (from its first calendar day), so a month whose last calendar day is a
   Sunday does not slip a month.

## 5. Runs, after the lock (Aarsh's to run)

The engine change is inert without the config block; `pytest -q` covers
E1's identity with hooks off. The byte-identity re-run of E1 base, which
also covers E3-R's engine changes, is in `docs/RUNNING.md`.

| run | command (from `D:\portfolio_lab`) | output |
|---|---|---|
| STACK: E1 base on 2010–2016 | `.\.venv\Scripts\python.exe -c "from pflab.backtest import runner; print(runner.main('configs/e1.toml','e2d1_development',sweep=True,rows=['base'],kind='regression'))"` | `experiments\E1\regression\e2d1_development-*` |
| E2-D1 development | `.\tools\run_locked.ps1 -Experiment E2-D1 -Period e2d1_development` | `experiments\E2-D1\sweeps\e2d1_development-*` |
| E2-D1 validation (after the development review) | `.\tools\run_locked.ps1 -Experiment E2-D1 -Period validation` | `experiments\E2-D1\sweeps\validation-*` |

STACK validation is E1's existing `experiments\E1\regression\validation-*`.
`tools/check_lock.py` needs an `E2-D1` entry (§3–§8) at the lock.
