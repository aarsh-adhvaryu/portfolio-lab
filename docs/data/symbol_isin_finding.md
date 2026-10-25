# Finding: dropping unmapped pre-2012 rows removes the survivorship set

**Date:** 2026-09-16
**Affects:** charter E1 §9 (last bullet), `docs/PHASE1_SPRINT.md` step 4, task 1.3
**Status:** implemented both ways, default follows the charter, needs a decision

## The rule and the trigger

Charter §9 ends: *"Pre-2011 bhavcopies have no ISIN column; symbols are mapped
to ISIN via the symbol-change history. **Unmapped rows are dropped and counted
in the manifest.**"*

Sprint step 4 adds a tripwire: *"If the count exceeds 2% of rows in any year,
stop and show the investor."* **That tripwire has fired for six consecutive years.**

## The map

Built from the ISIN era of the bhavcopy read backwards, plus NSE's
symbol-change file followed forward through renames. Date-ranged, because 535
of ~4,000 symbols point at more than one ISIN over time.

| stage | resolved rows |
|---|---|
| direct symbol match only | 86.29% |
| plus symbol-change chains | **93.67%** |

Per-year unmapped share of pre-ISIN-era rows:

| year | unmapped | | year | unmapped |
|---|---|---|---|---|
| 2004 | **18.67%** | | 2008 | **5.22%** |
| 2005 | **13.48%** | | 2009 | **3.99%** |
| 2006 | **10.25%** | | 2010 | 1.77% |
| 2007 | **6.97%** | | 2011 | 0.15% |

## Why the remainder cannot be recovered

251 symbols never resolve. Checking each one's last-ever bhavcopy row:

```
unresolved symbols: 251
  last trade BEFORE 2011-10-01 (delisted pre-ISIN era): 251
  still trading after 2011-10-01:                         0
```

**All of them, without exception, delisted before NSE added the ISIN column.**
There is no ISIN for them anywhere in the bhavcopy, so no amount of additional
mapping work recovers them. The 93.67% is the ceiling for this method.

That also means the unmapped set is not a random sample. It is precisely the
set of companies that died between 2004 and 2011.

## What dropping them costs

Rebuilding §2's universe (top 500 by trailing 126-session mean traded value)
for each month-end 2005–2011 and counting how many *would have been eligible*:

```
month-ends checked: 84
unmapped names inside the top-500 universe: mean 24.3, max 73
months with at least one:                   78 of 84
```

At the worst month-end (2005-01-31) **73 of the 500 eligible names — 14.6% of
the universe — are silently absent.** These are not micro-caps below the
liquidity filter; they cleared it.

This collides with principle 6: *"Survivorship is a data error. The universe
includes every name that ever traded, including the ones that went to zero."*
A backtest on the dropped panel can never hold a company that went to zero in
2004–2011, which inflates E1's measured return in exactly the period the
development window covers (2007–2016).

Note the direction. §9's other declared simplifications are argued to bias
*against* E1. This one biases *for* it.

## Options

**A. Keep the charter default (`unmapped="drop"`).** Faithful to §9 as written.
Accepts a survivorship bias of up to 14.6% of the early universe, concentrated
in 2004–2009, and therefore in the development period.

**B. Synthetic security key (`unmapped="synthetic"`).** Unresolvable rows keep a
stand-in key, `NSESYM:<symbol>`. Safe because all 251 delisted before the ISIN
era: none collides with a real ISIN and none is reused later. They stay in the
universe, can be held, and can go to zero under §9's delisting rule. Still
honours CLAUDE.md 8 — the key is symbol *plus* date range, never a bare symbol
join. Cost: the key is not a real ISIN, so these names cannot join to any
external ISIN-keyed source (dividends, for one — though sprint step 5 already
assumes delisted names paid none).

**Recommendation: B.** Principle 6 calls survivorship a data error, and this is
survivorship in its purest form — the dropped rows are the dead companies. A
synthetic key is a labelling problem; dropping is a measurement problem.

## Status in code

Both are implemented and tested. `panel.build(unmapped=...)` takes `"drop"`
(default, charter-faithful) or `"synthetic"`. Over 2004–2008:

```
drop       rows 1,017,052  securities 1,220
synthetic  rows 1,131,825  securities 1,463
```

Every build reports `mapping.breaches`, so the tripwire is visible in the
manifest whichever way it is set. `docs/strategies/E1.md` is untouched;
switching the default would need a §15 entry.
