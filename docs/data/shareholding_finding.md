# BSE quarterly shareholding patterns — sources, traps, coverage

Built 2026-09-23/24. `pflab/data/bse_shareholding.py`, backfilled by
`tools/backfill_shareholding.py`. **The backfill is still running**; the
coverage numbers in §5 are from the completed portion and are provisional.
Everything in §1–§4 is settled.

The endpoints are undocumented. They were recovered from BSE's own Angular
bundle (`chunk-SCEKLEXO`, the service layer; `chunk-HMENO5C7`, the
components), which is where the parameter names came from too.

## 1. Quarter ids

BSE keys shareholding on a global sequential quarter id, not a date:
**65 = March 2010**, **130 = June 2026**, so 2010-onward is 66 quarters.
Verified against `Corp_shpSec_shpqtrinfo_ng` at 17 points; `quarter_end()`
reproduces all of them.

## 2. Two eras, and a trap that retries cannot catch

The SEBI format carrying category-wise holding and the number of
shareholders per category begins with the **December 2015** quarter
(qtrid 88).

| era | quarters | endpoint | what it carries |
|---|---|---|---|
| **new** | 88–130 (Dec 2015 → Jun 2026) | `Corp_shpSec_SHPSUMMARY_ng` | category holding, `Fld_NoOfShareHolders` per category, pledge, total shares, `Fld_AuthoriseDate` |
| **old** | 65–87 (Mar 2010 → Sep 2015) | `Corp_ShpPromoters_ng` | promoter entities, shares, percent, pledged shares. **No category breakdown, no shareholder counts** |

**The trap.** For a pre-2016 quarter, `SHPSUMMARY` does not fail. It returns
well-formed JSON with the six correct category labels and **zero in every
numeric field**. Written naively that records *promoter holding 0%, shares
outstanding 0* for every company for 2010–2015. Under E2-D §3, whose rule
fires when promoter holding falls more than 1.0 pp, a zero-filled history
would flag essentially the entire universe.

This is the 2026-09-22 "throttled answers saved as data" failure in a new
costume, and worse: it is perfectly reproducible. A retry returns the same
zeros, and the row count is correct, so counting and retrying cannot catch
it. Only an adds-up check can.

Per the investor's instruction, pre-2016 category and shareholder-count fields are
written **explicitly unavailable (None), never zero**.

## 3. Two double-counting defects, both found by the numbers not adding up

Both would have passed any schema or count check.

**New era — the table mixes components with subtotals and a grand total.**
`Table1` holds six rows: A (`STA1A2`), B (`STB1B2B3`), C1, C2, their
subtotal C (`STC1C2`) and the grand total (`STABC`). Summing the table
double- and triple-counts: Gadget Co Dec-2015 summed to 6.58bn shares
against a true 3.24bn. The collector reads **named rows only**.

**Old era — the promoter table ends with its own `Total` row.** Gadget Co
March-2010 returns 42 rows; the 42nd is named `Total`, 1,463,920,323 shares
at 44.76%. Summing all 42 gives 2,927,840,646 at **89.52%** — exactly
double, and still inside [0, 100], so a range check alone would have passed
it. The collector reads the `Total` row and **checks the entity rows sum to
it**, halting if they do not.

After the fix, the series is continuous across the era boundary, which is
the real test:

| scrip | Mar 2010 | Sep 2012 | Sep 2015 | **Dec 2015** | Dec 2018 | Dec 2025 |
|---|---|---|---|---|---|---|
| Gadget Co (599325) | 44.76 | 45.24 | 45.21 | **46.66** | 47.19 | 50.01 |
| TCS (532540) | 74.12 | 73.96 | 73.86 | **73.42** | 72.05 | 71.77 |
| HDFC Bank (500180) | 23.73 | 23.00 | 21.57 | **26.47** | 26.54 | 0.00 |

(HDFC Bank's 0.00% from 2023 is correct — it has had no promoter since the
merger, and it is why the derived figure must be undefined there.)

## 4. The adds-up check is a halt

A record that fails is written `status = "unavailable"` with the reason and
counted; **no number is ever recorded for it.** The conditions:

- promoter percent in [0, 100]
- **new era**: grand total > 0; A + B + C within 1.0 pp of 100; A + B + C
  shares equal the grand total to 0.1%; promoter and public shares not both zero
- **old era**: promoter shares > 0 and percent > 0, and the entity rows sum
  to the `Total` row
- pledged shares non-negative and not exceeding promoter shares

It is already earning its place. In the completed portion, failures split as:

| reason | count |
|---|---|
| zero-filled skeleton (pre-2016) | 200 |
| promoter shares not positive (old era) | 23 |
| no promoter rows | 17 |
| **A + B + C2 off 100 by more than 1.0 pp** | **9** |

The last group is the interesting one: real SEBI-format filings whose
category percentages sum to 98.88–98.98%. They are just over the 1.0 pp
tolerance. **I have not moved the tolerance** — changing a threshold after
seeing which records it rejects is exactly what must not happen. Flagged
for the investor: either the tolerance is wrong, or those filings are.

## 5. Coverage (provisional — backfill in progress)

Universe: 2,940 scrip codes that resolve to an ISIN the price panel holds
(`bse_scrip_isin.panel_universe()`). 66 quarters each = 194,040
scrip-quarters.

**Run as three shards** (2026-09-24, on the investor's instruction: one worker's
~37 h was not acceptable). Measured **205/min against 85/min single, so
~15.4 hours.** Three is the evidence-backed maximum -- the announcements
backfill found four workers draw throttled answers and three do not
(2026-09-22). Going past three re-opens a failure this repo has already
paid for.

    python tools/backfill_shareholding.py --shard 0 --of 3
    python tools/backfill_shareholding.py --shard 1 --of 3
    python tools/backfill_shareholding.py --shard 2 --of 3
    python tools/backfill_shareholding.py --merge     # when they finish
    python tools/backfill_shareholding.py --check     # coverage report

Shards are disjoint by `scrip_code % 3`, each writes its own parquet and
ledger, and `done_pairs` also reads the unsharded legacy ledger so nothing
the earlier single-worker run finished is repeated.

**The parallel hazard, and what answers it.** A throttled shareholding
answer can arrive as an EMPTY table, which is indistinguishable from "this
company filed nothing" and would be ledgered as a permanent `unavailable` --
the 2026-09-22 failure in the one direction the adds-up check cannot see,
because there is nothing to add up. So an `unavailable` whose reason
throttling could fake (`needs_confirmation`: an empty promoter table, a
missing `Table1` or grand total, or a post-2015 skeleton) is **re-asked once
before it is believed**. If the second answer is `ok` the first was a
throttle and the row is rescued; if the two disagree, nothing is written and
the pair is retried next pass. A pre-2016 skeleton is not re-asked (it is
structural and deterministic) and neither is an adds-up failure (it carries
real numbers, which throttling does not invent). `rescued` and `unstable`
are counted in the run stats, so throttling under three workers would show
up rather than pass silently.

**Incident, 2026-09-24 — eighteen workers, and 972 silent gaps.** The three
commands above were run several times over, leaving **18 processes, six per
shard**. Duplicates on one shard share a parquet and a ledger, and `_flush`
is read-modify-write, so one writer's rows were overwritten by another's
**while both had already appended to the ledger**. 972 scrip-quarters ended
up marked settled with nothing behind them, and because the ledger is what
stops a pair being re-asked, those gaps would have been permanent. The
ledger itself also went backwards under concurrent appends (8,400 entries
to 4,433). Nothing in any worker's output said so -- each printed healthy
progress throughout.

Repaired by `rebuild_ledger_from_data()`, which derives the ledger from the
parquet rather than trusting it: a pair is settled if and only if a row
exists for it. 972 orphans dropped, 0 rows lost, ledger and data now agree
exactly at 7,278.

**The data that survived was not poisoned.** Zero `unstable` entries, three
log lines in total, and the ok-rate over the 18-worker window was *higher*
than the single-worker baseline (97.8% against 91.5%), which is the opposite
of what throttling produces. The confirmation net and the adds-up halt both
held; what failed was file concurrency, which no amount of re-asking
addresses.

**Prevented from recurring:** a shard now takes a pid lock and a second copy
**refuses to start** rather than corrupting silently; a stale lock from a
killed worker is reclaimed automatically. Note that the venv `python.exe` is
a launcher shim, so each worker shows as two processes (a 1-thread parent
and the real 42-thread interpreter) -- count the **locks**, not the
processes.

From the completed portion (35 scrips, 2,264 scrip-quarters, 2,015 ok):

| era | quarters/yr recorded | share ok | **share carrying a real filing date** |
|---|---|---|---|
| 2010–2014 | 108 | 95–96% | **0%** |
| 2015 | 108 | 96% | 24% (the Dec-2015 quarter only) |
| 2016–2022 | 106–108 | 86–93% | **86–93%** |
| 2023–2026 | 52–104 | 78–81% | **78–81%** |

**Filing dates.** The point-in-time key is `Fld_AuthoriseDate` from
`SHPSUMMARY` — a genuine per-filing timestamp, landing ~3 weeks after
quarter end (Dec-2025 quarter authorised 2026-01-21). It exists for the
whole new era and **not at all** for the old one. A quarter with no
traceable filing date is recorded `NaT` / `"unresolved"` and **is never
dated by its quarter end**.

**What reaching 95% would take.** For 2016 onward, nothing: `Fld_AuthoriseDate`
already covers 78–93%, and the shortfall is quarters with no filing at all
(a company not yet listed, or delisted), not dated filings we failed to
date. Filling those is not possible because there is nothing to date.

For **2010–2015 it cannot be reached from these sources.** The announcement
feed's `subcategory = "Shareholding"` label exists only for 2014–2022 — zero
rows in 2010–2013, effectively zero from 2023 — and even in 2024 only 201
scrips a year mention a shareholding pattern in a headline. And pre-2016
announcements carry no `DissemDT` at all
(`insider_finding.md` §3), so even a matched announcement could not supply a
dissemination timestamp. Reaching 95% for 2010–2015 would require the
Clause-35 filing attachments, which the investor has ruled out of scope; E2-E can
declare a 2016-onward window instead.

## 6. Shares outstanding: reported and derived are separate columns

`shares_outstanding_reported` (the `STABC` grand total, new era only) and
`shares_outstanding_derived` (`promoter_shares / (promoter_pct/100)`) are
**never merged**, and `shares_outstanding_derivation` stores the arithmetic.
Derived is **undefined when promoter holding is zero** — there is nothing to
divide by, and HDFC Bank since 2023 is the live case.

**Implied error.** BSE reports the percent to two decimals, so the rounding
half-width is 0.005 pp and the derived total's relative error is 0.005/pct:
0.01% for a 50% promoter, 0.5% for a 1% promoter. Observed over 1,978
derived figures: median **0.0091%**, p90 0.0128%, p99 0.0324%, max 3.125%,
with 0.05% of rows above 1%. The error travels with the number in
`derived_implied_error_pct`, because it is entirely driven by how small the
promoter stake is.

**The overlap check.** Where both exist (1,214 scrip-quarters in the new
era), derived against reported:

| statistic | relative difference |
|---|---|
| median | **−0.000%** |
| p05 / p95 | −0.011% / +0.010% |
| median absolute | 0.005% |
| within 1% | **99.9%** |

So the derivation is validated against the reported figure to about five
thousandths of a percent, which is as good as the rounding allows. That is
the evidence that the pre-2016 derived series — where no reported figure
exists — can be trusted to the same precision, with the caveat that its
error scales inversely with the promoter stake.

## 7. The scrip-code → ISIN map

`pflab/data/bse_scrip_isin.py`, `data/bse_scrip_isin/map.parquet`.

The **announcement feed is the primary source of the universe** (7,067 scrip
codes that filed anything since 2010, including companies since delisted);
the equity master only resolves and verifies ISINs. Taking the master's
scrip list as the universe would put survivorship on the primary path — it
is a snapshot of today. The master does serve delisted and suspended scrips
(10,895 rows over all statuses against 5,045 active), which is why it can
resolve the feed's codes at all. 6,705 of 7,067 resolved; 362 unresolved.

**The map is date-ranged, because an ISIN is not stable.** A face-value
split issues a new one — KOTAKBANK INE237A01028 → INE237A01036 on
2026-01-14, DRREDDY INE089A01023 → INE089A01031 on 2024-10-28, CANBK
INE476A01014 → INE476A01022 on 2024-05-15. The master carries only today's
ISIN, so a flat join silently lost 1,445 of the panel's 4,380 ISINs — 18.5%
of panel rows, including Kotak Mahindra Bank, Dr Reddy's, Canara Bank and
Info Edge. Each scrip code now emits one row per ISIN its panel symbol ever
carried, with the dates that ISIN was valid (CLAUDE.md rule 8).

**Coverage against the price panel**, equities only (ISINs beginning `INE`;
`INF` mutual-fund and ETF units have no shareholding pattern):

| | count | share |
|---|---|---|
| panel equity ISINs | 3,683 | |
| covered by the map | 3,361 | **91.3%** |

By year the covered share runs **93.2–95.8%** (2010: 93.3%, 2018: 95.8%,
2026: 94.1%). The residual is 351 equities with no BSE presence the map
could find, plus 587 fund/ETF units and 249 panel pseudo-ISINs that are
correctly excluded.

`bse_scrip_isin.unresolved_by_year()` lists every unresolved code with the
year it was first seen and how much it filed, for the investor's review.
