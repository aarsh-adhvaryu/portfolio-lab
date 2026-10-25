# Waiting for the buy zone vs buying at once: results

Protocol: `docs/research/buyzone_wait_protocol.md` (registered 2026-10-23, commit e85ceb3, before the run). Run
2026-10-23 with `tools/zone_study.py` (point-in-time Nifty 500, stock-months whose price was above the zone's top at
the month's start; the waiting money earns 6.5% a year). Output: `data/research/zone_study.json`.

| period | wait | mean saving (bps) | Newey-West t | months | stock-months | filled | if filled | if not | waiting cheaper |
|---|---|---|---|---|---|---|---|---|---|
| development 2010-17 | 1 month | -2.0 | -0.04 | 95 | 27,159 | 24% | +632 | -226 | 56% |
| | 3 months | -124.3 | -0.94 | 93 | 26,375 | 37% | +959 | -808 | 58% |
| | 6 months | -255.6 | -1.07 | 90 | 25,311 | 46% | +1,190 | -1,577 | 61% |
| validation 2018-21 | 1 month | -62.9 | -0.91 | 48 | 12,916 | 24% | +579 | -273 | 54% |
| | 3 months | -237.0 | -1.19 | 46 | 12,194 | 37% | +905 | -992 | 55% |
| | 6 months | -496.0 | -1.07 | 43 | 10,948 | 48% | +1,108 | -2,196 | 58% |
| spent 2022-25 (no say) | 1 month | -41.0 | -0.64 | 48 | 14,430 | 22% | +555 | -220 | 54% |
| | 3 months | -214.1 | -1.14 | 45 | 13,553 | 33% | +875 | -790 | 56% |
| | 6 months | -480.8 | -1.19 | 43 | 12,973 | 40% | +1,140 | -1,640 | 57% |

**Decision (the registered rule):** development chose 1 month (the least bad); on validation it saved -62.9 bps with
t -0.91, short of +50 bps and t 2: **NOT ADOPTED.** The ready plans keep buying at once.

Reading: waiting was cheaper more often than not (54-61% of stock-months), but when the price never came back the
stock had run away, and those misses cost more than the fills saved; the longer the wait, the worse. The same in every
period, including the spent years.

Live consequence (CLAUDE.md 12: what fails has no live feature): the zone never says "wait". A price above the zone is
shown as ABOVE ZONE, a description with this finding beside it; RICH (the price assumes more growth than the company's
own) stays a caution, untested; "check my idea" answers yes above the zone (subject to the guards and the single-stock
cap) and "check" when rich.
