# Early-warning study: results

Run 2026-10-16 with `tools/early_warning_study.py`, as registered in `early_warning_protocol.md` (commit 589fc8e,
before the run). No amendment. First fall = a Nifty 500 TRI session of -2% or worse after 20 sessions without one;
lift = how much more often a first fall came within the week after a warning than on an ordinary day.

| period | first falls | combined warning: lift / recall / share of days on | pass? |
|---|---|---|---|
| development 2010-14 | 14 | 0.95 / 43% / 16% | no (lift, recall) |
| validation 2015-19 | 9 | 2.24 / 100% / 26% | no (on too often) |
| 2020-26 (not evidence) | 23 | 1.13 / 65% / 37% | - |

**FAILS.** Together the signs did not warn of first falls: in 2010-14 a first fall was no more likely after a
warning than without one, and in 2015-19 the warning was on more than a quarter of the time.

Signals alone (reported, not used to decide): India VIX jump lift 0.31 / 4.28 / 1.07; US fall overnight 1.30 /
2.57 / 1.15; foreign selling 0.19 / 1.80 / 1.01; **US VIX jump 2.41 / 2.63 / 2.55** (recall 29% / 67% / 39%, on
5-8% of days). The US VIX jump is the one consistent sign, but it was picked out after seeing these results, so
it is NOT adopted; using it would need a new registration tested on data not yet seen (for example, other
markets, or the months after today).

Nothing is added to the live system. Protection against an unforeseeable first fall stays the plan itself (the
mix, the cash floor, staging, the safety filters, the dip rule).
