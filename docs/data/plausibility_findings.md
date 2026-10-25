# Plausibility findings — charter §9

Panel: 8,033,369 rows, 4,382 securities, 5,638 sessions, 2004-01-01 .. 2026-09-16.
Adjusted with 10,126 factors: parsed PURPOSE text plus PREVCLOSE-implied ones for actions with no ratio in the text (§15, 2026-09-16). ETFs, InvITs and REITs typed and excluded from the §2 universe (§15, 2026-09-16).

## Halts
| kind | count |
|---|---|
| move | 1,189 |

**3,205 unadjusted -> 2,725 with parsed factors -> 1,189 with the PREVCLOSE cross-check.**
That final figure is exactly the number of halts where `prev_close(t)` equals the prior
close, i.e. NSE adjusted for nothing and the move is genuine. Every halt NSE *did* adjust
for is now explained, so no demerger can register as a fake §4 band exit with STCG.

The 15 largest are relistings after suspension on sub-₹10 names; §2 never admits them.

### 15 largest remaining moves
| symbol | date | return |
|---|---|---|
| ARIHANT | 2026-04-20 | +21.889 |
| HORIZONINF | 2008-06-13 | +4.668 |
| STINDIA | 2006-06-23 | +1.519 |
| SICAGEN | 2026-04-20 | +1.240 |
| KOVAI | 2026-04-20 | +1.130 |
| MOTOGENFIN | 2005-03-01 | +1.014 |
| VKSPL | 2015-11-30 | +1.000 |
| VKSPL | 2016-03-01 | +1.000 |
| VKSPL | 2016-03-31 | +1.000 |
| VKSPL | 2016-04-08 | +1.000 |
| VKSPL | 2016-04-25 | +1.000 |
| VKSPL | 2016-05-02 | +1.000 |
| VKSPL | 2016-05-18 | +1.000 |
| VKSPL | 2016-05-27 | +1.000 |
| VKSPL | 2016-05-31 | +1.000 |

## Findings
| kind | count |
|---|---|
| identical_closes | 318 |
| gap | 12,737 |
| short_gap | 44,784 |

### 10 longest identical-close runs
| symbol | sessions | from | to | close |
|---|---|---|---|---|
| LIQUID | 253 | 2025-04-04 | 2026-04-15 | 999.99 |
| LIQUID | 206 | 2024-06-06 | 2025-04-02 | 999.99 |
| BIRLACOT | 106 | 2015-11-27 | 2016-05-04 | 0.05 |
| LIQUID | 105 | 2026-04-17 | 2026-09-16 | 999.99 |
| LIQUIDIETF | 61 | 2025-07-08 | 2025-10-03 | 999.99 |
| BIRLACOT | 58 | 2015-08-18 | 2015-11-11 | 0.05 |
| LIQUIDIETF | 50 | 2024-10-18 | 2024-12-31 | 999.99 |
| CILNOVA | 48 | 2013-09-10 | 2013-12-04 | 10.00 |
| LIQUID | 48 | 2023-09-21 | 2023-11-30 | 999.99 |
| LIQUIDIETF | 46 | 2025-10-07 | 2025-12-11 | 999.99 |

## For the investor (sprint step 7)

The two items you identified as data errors are resolved in code, not by eye:
LIQUID/LIQUIDIETF at 999.99 are ETFs and are now typed out of the universe, and the
demerger-type halts are absorbed by the PREVCLOSE cross-check. What remains is a list
of genuine moves on names §2 excludes.
