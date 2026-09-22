# Finding: the bhavcopy PREVCLOSE is not adjusted on ex-dates

**Date:** 2026-09-16
**Affects:** charter E1 §9, `docs/PHASE1_SPRINT.md` step 3, Phase 1 task 1.2
**Status:** blocked, needs Aarsh's decision
**Verification gate:** `tests/test_adjustment_known_events.py` — fails, by design

## What the charter assumes

Charter §9 and sprint step 3 both say:

> On an ex-date NSE publishes an adjusted `PREVCLOSE`, so
> `factor = prev_close(t) / close(t-1)` on rows where the two differ by more
> than 2% and the name traded both days.

Sprint step 3 also requires: *"**Verify** on three known events before trusting
it (a 1:1 bonus, a 10→2 split, a 1:2 bonus) and put the check in a test."*

That verification has been run. **It fails.**

## What NSE actually publishes

Infosys had a 1:1 bonus with ex-date 2015-06-15. Raw bhavcopy rows:

```
12-JUN-2015  INFY,EQ,2005.00,2025.55,1955.50,1975.05,1978.05,1997.65,...
15-JUN-2015  INFY,EQ, 976.95, 998.80, 968.00, 990.45, 994.00,1975.05,...
                       ^open                  ^close          ^PREVCLOSE
```

On the ex-date the stock opens at 976.95 (already halved) and closes at 990.45,
but `PREVCLOSE` reads **1975.05** — the *unadjusted* prior close. The charter's
formula therefore evaluates to `1975.05 / 1975.05 = 1.000` and detects nothing.

This is not specific to Infosys. Restricting to genuinely adjacent trading
sessions (the confound below) over 2012–2020:

| large down-gaps (close ratio 0.15–0.62) | `PREVCLOSE` unadjusted |
|---|---|
| 451 | **450 (99.8%)** |

The single exception is a coincidence, not an adjustment. Every well-known
action behaves the same way:

| event | prior close | ex-date close | ex-date PREVCLOSE |
|---|---|---|---|
| RELIANCE 1:1 bonus, 2017-09-07 | 1645.40 | 818.10 | 1645.40 |
| INFY 1:1 bonus, 2015-06-15 | 1975.05 | 990.45 | 1975.05 |
| ICICIBANK FV 10→2, 2014-12-04 | 1794.10 | 362.20 | 1794.10 |
| LT 1:2 bonus, 2017-07-13 | 1739.55 | 1175.10 | 1739.55 |
| AXISBANK FV 10→2, 2014-07-28 | 1985.75 | 395.35 | 1985.75 |
| BANKBARODA FV 10→2, 2015-01-22 | 1127.90 | 223.85 | 1127.90 |

### A confound worth recording

A first pass suggested only ~50% of gaps were unadjusted. That was an artefact:
`PREVCLOSE` refers to the **previous session**, whereas the previous *row* for
an illiquid name can be weeks earlier. Constraining to adjacent sessions in the
trading calendar raises the figure to 99.8%. Any future work here must apply the
same constraint.

## The obvious substitute also fails

If `PREVCLOSE` is unadjusted, the action is still visible in the close-to-close
gap, `close(t) / close(t-1)`. That does not work either, for two reasons.

**1. It cannot recover the factor.** The gap is the action *times that day's
return*, so it only lands on the true ratio when the stock happens to move less
than 1%. Of the six known events tested, three miss the 1% snap tolerance:

```
RELIANCE 2017-09-07  gap=0.4972 -> 0.5000  SNAP
INFY     2015-06-15  gap=0.5015 -> 0.5000  SNAP
RECLTD   2016-09-28  gap=0.5001 -> 0.5000  SNAP
INFY     2014-12-02  gap=0.4889  NO-SNAP   (2.2% off 0.5)
CADILAHC 2015-10-06  gap=0.2045  NO-SNAP   (2.2% off 0.2)
MINDTREE 2014-06-03  gap=0.5114  NO-SNAP   (2.3% off 0.5)
```

**2. It cannot tell an action from a crash.** Across 2012–2020 it snaps 1,306
times, of which 739 land on 0.8 — overwhelmingly ordinary −20% sessions, not
1:4 bonuses. A concrete false positive: `IBULHSGFIN 2020-03-19`, gap 0.6626,
which is the COVID crash, not a 1:2 bonus. There is no threshold that separates
the two, because a −33% day and a 1:2 bonus are the same number.

Both failures bias E1 in the **wrong** direction. An undetected bonus leaves a
fabricated −50% return in the momentum signal, which would push a healthy name
to the bottom of the 12-1 rank. Charter §9's declared simplifications are all
meant to bias *against* E1; this one does not.

## Options

**A. Adopt the NSE corporate-actions feed.** The sprint already names this as
the designated fallback — *"NSE corporate-actions scraper (only if the PREVCLOSE
method fails verification)"* — currently under "Deferred". This finding is
exactly the trigger condition, so it moves onto the critical path. It parses
`PURPOSE` strings (`Bonus 1:1`, `Face Value Split ... From Rs 10/- To Rs 2/-`)
into exact factors with no inference from prices. Cost: roughly a day, plus the
ex-date alignment check against the observed gaps — which the backfill now makes
easy to verify.

**B. Take adjusted prices from a feed** (e.g. yfinance, already a dependency for
dividends in step 5). Cheaper, but it is a second unaudited price source whose
adjustments cannot be point-in-time verified, and it has no coverage for
delisted names — which charter principle 6 treats as a survivorship error.

**C. Gap detection plus manual review.** Emit every snapped candidate to
`adjustment_candidates.parquet` for review. Sprint step 7 already budgets a
review, but it assumed a short list of non-snapping oddities, not ~1,300
candidates that are mostly false positives across 2012–2020 alone, and it still
misses half the real events.

**Recommendation: A.** It is the charter's own declared fallback, it is the only
option that yields exact factors, and it keeps the price source single and
auditable.

## What this needs from Aarsh

Charter §9 names the PREVCLOSE method explicitly, and CLAUDE.md non-negotiable 1
forbids changing §2–§13 except by appending to §15, with a date and a reason,
and only when Aarsh asks. So this is a decision, not a code change:

1. Confirm option A (or another), and
2. authorise the §15 entry recording that the PREVCLOSE method failed its
   mandated verification and what replaces it.

Nothing in `corporate_actions.py` has been changed away from the charter. It
still implements §9 as written; `verify_known_events()` is the gate that catches
the failure, and the tests assert the failure rather than paper over it.

## Reproducing

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_adjustment_known_events.py
```

The fixtures are real rows copied out of `data/bhavcopy/`, so the tests are fast
and need no data directory.
