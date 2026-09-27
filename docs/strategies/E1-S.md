# E1-S — Sector-trend cap

Status: **DRAFT** 2026-09-27, written by Claude from `docs/MANDATE.md` §7 on
Aarsh's instruction of 2026-09-26 (lane 6). Not reviewed. Locks at its
first development run. Judged by `GATE.md` against STACK = E1 base, and
reported against MANDATE §3 and §5.

**Seven choices in this draft are Claude's readings of one paragraph of the
mandate, marked ◆ and collected in §11. None is settled until Aarsh
settles it.**

## 1. Purpose
MANDATE §7: "a sector whose index closes a month below its own 10-month
average is capped at half its normal weight; the cap lifts when it closes
above again. This is the rule for 'let go of IT when it is being hit harder
than it should, buy back when things normalise', written so it needs no
view on AI. When trend and balance conflict, trend wins." This charter
makes that paragraph a rule the engine can run and the gate can judge.

## 2. Hypothesis
A momentum book concentrates in whatever has been working, and a sector
that has turned down keeps some of its names ranked highly for months
after, because 12-1 momentum looks a year back. Capping exposure to a
sector below its own trend cuts the losses from that lag without giving up
the return of sectors still in trend.

## 3. The one change
At each month-end M, after E1 has decided its target list:

1. **Sector of a name** — its NSE industry label from the point-in-time
   sector map (`pflab/data/sector_map.py`; `docs/notes/E2B-readiness.md`
   §2), mapped to a sector index by §4's table. ◆ A name with no label, or
   whose label maps to no index, is **uncapped** (declared; see §6).
2. **A sector is capped at M** if its index's month-end close is below the
   mean of its last 10 month-end closes including M — E1 §6's rule, applied
   to the sector's index instead of the Nifty 50. ◆ Price index, as E1 §6.
3. **Normal weight** of a sector at M ◆ = the share of E1's equal-weight
   target (N = 25) its names would hold without the cap: k names → k/25.
4. **The cap**: the book's equity value in a capped sector may not exceed
   **half** its normal weight. ◆ Each of its target names is held at half
   the equal weight (names are kept; exposure is halved), rather than
   dropping half the names.
5. **Held names in a capped sector are trimmed** ◆ to the capped weight at
   the next open — partial sells, FIFO within the name (`india_lots.py`,
   unchanged). "Let go of IT" is a sale; a buys-only reading is S4.
6. **Freed capital** ◆ goes to the next-ranked eligible names in uncapped
   sectors through E1's normal shortfall buys, so the rule moves sector
   exposure and not market exposure (that is E3-R's job). Capital left
   after those buys waits in the liquid sleeve. The cash reading is S5.
7. **The cap lifts** at the first month-end the index closes at or above
   its 10-month mean; E1's normal buys then refill the names to full
   weight. No other state.

"When trend and balance conflict, trend wins" ◆ is read as: the cap applies
even when it leaves the book concentrated in fewer sectors; no rule is
added to keep sectors balanced.

Everything else is E1 as locked: universe, N = 25, band 50, 12-1
momentum, SMA-10 RISK_OFF, costs, tax, ADV guard, delisting.

## 4. Sector-index table ◆

Taxonomy B labels (2014-01 → 2021-06). Development before 2014 uses
taxonomy A labels mapped to B by the declared crosswalk
(`sector_map.crosswalk(2010-01-02 → 2014-01-22)`, weighted purity 0.924).

| NSE label (taxonomy B) | sector index (`data/indices/`) | from |
|---|---|---|
| AUTOMOBILE | SECTOR_AUTO | 2004 |
| CHEMICALS | SECTOR_CHEMICALS | 2005-04 |
| CONSTRUCTION | SECTOR_INFRA | 2004 |
| CEMENT & CEMENT PRODUCTS | SECTOR_COMMODITIES ◆ | 2004 |
| CONSUMER GOODS | SECTOR_CONSUMPTION ◆ (FMCG is narrower) | 2006-01 |
| ENERGY, POWER | SECTOR_ENERGY | 2004 |
| OIL & GAS | SECTOR_OIL_GAS | 2005-04 |
| FINANCIAL SERVICES | SECTOR_FIN_SERVICES | 2004 |
| HEALTHCARE SERVICES | SECTOR_HEALTHCARE | 2005-04 |
| PHARMA | SECTOR_PHARMA | 2004 |
| IT | SECTOR_IT | 2004 |
| MEDIA & ENTERTAINMENT | SECTOR_MEDIA | 2005-12 |
| METALS | SECTOR_METAL | 2004 |
| SERVICES, TELECOM | SECTOR_SERVICES ◆ | 2004 |
| INDUSTRIAL MANUFACTURING, TEXTILES, PAPER, FERTILISERS & PESTICIDES | **none — uncapped** | — |

Every mapped index has ten month-end closes before development begins
(2007-01) except SECTOR_CONSUMPTION (first mean 2006-10) — also in time.
Sector indices before their launch dates are back-computed by NSE, the
caveat B3 and B5 carry.

## 5. Window and benchmarks
E1's: development 2007–2016, validation 2017–2021. Sealed untouched.
Benchmarks B1–B5.

## 6. Declared limitation: most of development's holdings may be unmapped
Measured on E1 base's own holdings (`docs/notes/E2B-readiness.md` §2):
the point-in-time map labels **52.8%** of held names in development and
**69.5%** in validation. Momentum buys names on their way into the index,
before any captured list shows them. Under §3.1 the rest are uncapped, so
in development the rule acts on roughly half the book.

Using a name's first *later* label would raise coverage to 77% / 87%, but
leaks the future: a name with a later label is a name that went on to
enter a large index. That is S6, reported and never the base.

## 7. Sweep
| row | change |
|---|---|
| S1 | cap at zero: a capped sector is exited entirely |
| S2 | cap at three quarters of normal weight |
| S3 | 12-month average instead of 10 |
| S4 | buys only: held names are not trimmed; the cap blocks buys into a capped sector |
| S5 | freed capital waits in the liquid sleeve instead of going to uncapped names |
| S6 | a name with no label on or before M takes its first later label (lookahead; flagged) |
| S7 | costs ×2 |
| S8 | sector total-return index instead of price index |

## 8. Verdict
ADOPT / REJECT / INCONCLUSIVE per `GATE.md` against E1 base. MANDATE §3
and §5 block reported. G4 (turnover no more than doubles) is the one to
watch: trimming on a monthly signal can trade a lot.

## 9. Reported extras
Months each sector spent capped; the book's weight in capped sectors
before and after the cap; the return of trimmed shares over the following
3 and 6 months against the names bought with the proceeds; turnover and
short-term share of gains; coverage of held names by the sector map each
month.

## 10. Not claimed
No view on any sector. The rule reacts to a sector index's own trend and
nothing else.

## 11. Open before lock — every ◆

1. Unmapped names uncapped (§3.1, §6), or ineligible while any cap binds.
2. Price index rather than total-return index for the trend (§3.2).
3. Normal weight = the sector's share of E1's equal-weight target (§3.3).
4. Half weight per name rather than half the names (§3.4).
5. Trim held names (§3.5), or buys only (S4).
6. Freed capital to uncapped names (§3.6), or to cash (S5).
7. §4's table, in particular cement, consumer goods, services/telecom, and
   the four labels with no index.

## 12. Change log
- 2026-09-27 — draft (Claude), from MANDATE §7, on Aarsh's instruction of
  2026-09-26. Not reviewed.
