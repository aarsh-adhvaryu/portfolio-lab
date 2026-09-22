# E1b — E1's rules on the momentum index's universe

Status: DRAFT. Locks at its first development run. Judged by `GATE.md`
against STACK = E1 base, and additionally reported against E1 §13 (C1–C4)
because E1b is a candidate base.

## 1. Purpose
Test whether E1's development gap to the momentum index fund came from the
universe, not the rules. E1 draws from the top 500 by traded value and
drifted to a median holding at rank 340 with 13 names held; the index draws
from Nifty 200. E1b runs E1's rules, unchanged, on Nifty 200 constituents.

## 2. Hypothesis
On Nifty 200 names, E1's rules match or beat the momentum index in
development and give back part of validation's small-cap boom. If so, the
rules are sound and the universe was the problem. If not, E1 is a small-cap
bet and the roadmap should say so.

## 3. The one change (§2 of E1 replaced; everything else identical to E1 as locked)
Eligible on month-end M: constituents of the Nifty 200 index as of M,
taken from NSE's historical constituent-change records (inclusion and
exclusion dates), mapped to ISIN by symbol at that date; series EQ,
instrument type STK, listed ≥ 250 sessions, close > ₹10. No turnover
ranking. Point-in-time: a name is eligible only between its inclusion and
exclusion dates.

Amended 2026-09-17 (draft, not locked): where a constituent-change record
names a company and not a symbol, it is mapped to ISIN by company name via
the name map; unresolved names are listed in the manifest; a year with more
than 2% of its changes unresolved halts the build.
Amended 2026-09-18 (draft, not locked): the universe is the Nifty 200
constituents from **2012-01-01**. For **2007-01-01 to 2011-12-31** it is the
point-in-time union of CNX 100 and CNX Midcap constituents, **declared as a
proxy universe** and not as the Nifty 200. The manifest labels which era each
month-end was decided on.

A guessed inclusion date is an interval, not a missing fact. The base row
places each one at the earliest date the name could have joined; sweep row
S12 places it at the latest. The manifest records both bounds per name.

## 4. Data
NSE index constituent history for Nifty 200 (and Nifty 500 for S10). Where
the published history begins after 2005, the earliest available list is
carried backward and the carry-back span is recorded in the manifest as a
declared gap.

Amended 2026-09-18 (draft, not locked). The history is built from NSE
Indices press releases, anchored on Internet Archive captures of the
constituent CSVs, and every window is floored at the security's first traded
session. The published Nifty 200 era begins 2012-01-01. Before it the
universe is the declared proxy of §3; the manifest records which era each
month-end used, and the build gates on reproducing every captured list
exactly.

## 5. Window and benchmarks
E1's: development 2007–2016, validation 2017–2021, sealed untouched.
Benchmarks B1–B4 unchanged (B4 recomputed on the E1b universe).

## 6. Sweep
E1's S1–S9 unchanged, plus:
| row | change |
|---|---|
| S10 | universe = Nifty 500 constituents (index membership, wider) |
| S11 | universe = top 200 by trailing traded value (separates "large" from "index member") |
| S12 | guessed inclusion dates placed at the latest possible date (the base row uses the earliest); the two bracket the truth |
| S13 | development restricted to 2012–2016, the published Nifty 200 years, with E1 base re-run on the same window |

## 7. Verdict
- ADOPT / REJECT / INCONCLUSIVE per GATE.md against E1 base (G1–G4, both
  periods). If ADOPT, E1b becomes the stack.
- C1–C4 per E1 §13 reported for both periods. ADVANCE (sealed reveal, live
  paper trading) requires C1–C4 in both periods for whichever base is
  current; it is a property of the stack, not of any single experiment.

## 8. Reported extras
Median turnover rank of holdings by year; names held by year; ADV skips;
pre-tax and tax paid; overlap of E1b holdings with the momentum index's
constituents.

## 9. Not claimed
No new signal. No change to N, band, lookback, filter, cash flow or tax.

## 10. Change log
- 2026-09-18 — LOCKED. No changes to §3–§7 after this line.
- 2026-09-17 — draft, written after E1's verdict from its development extras
  (universe drift finding). This is a new hypothesis, not a re-test of E1.
- 2026-09-17 — §3 amended (draft): company-name mapping via the name map,
  with a 2%-per-year unresolved halt. Needed because NSE's pre-2011
  constituent-change records print company names and no symbol.
- 2026-09-18 — §3/§4 (draft): the universe is Nifty 200 from 2012-01-01 and
  a declared proxy (CNX 100 union CNX Midcap, point-in-time) for 2007–2011.
  **Development stays 2007–2016 and validation 2017–2021.** The reasoning for
  keeping them: the years being removed are the years the hypothesis is
  about. E1b exists because E1's development gap to the momentum index
  appeared in 2007–2016; shortening development to 2012 would test the
  universe claim on years where E1 was not obviously failing, and would leave
  the original question unanswered. So the early years are kept, labelled as
  proxy rather than silently blended, and S13 runs the published-only window
  alongside so both readings are on the table.

  What the proxy is NOT: the captures show CNX 100 and CNX Midcap overlapped
  by 27–32 names before the 2016 restructure, so their union is smaller than
  the Nifty 200 and is a different universe. It is a stand-in for the era, not
  a reconstruction of it.
- 2026-09-18 — §6 (draft): S13 added — development restricted to 2012–2016,
  the published Nifty 200 years, with E1 base re-run on the same window so the
  comparison is like for like.
- 2026-09-18 — §6 (draft): S12 revised. It no longer drops guessed-window
  names; it places each guessed start at the latest date it could have been
  instead of the earliest, so the base row and S12 bracket the truth.
- 2026-09-18 — §6 (draft): S12 added. The point-in-time table marks each
  window with how its ends were established; where a change notice was never
  found, the window rests on a carry-back, a listing date or a capture
  boundary. S12 drops those names, so the sweep shows what the residual
  reconstruction gaps were worth rather than leaving it to be argued.
- 2026-09-17 — §4 NOT amended. The window stays 2007–2016 / 2017–2021. The
  Nifty 200 was not published before 2011, but NSE's methodology defines it
  as the union of Nifty 100 and Nifty Midcap 100, whose changes are published
  from 2006 and 2005, so the pre-2011 years are reconstructed from the
  index's own definition rather than carried back. The manifest records which
  years are published and which are reconstructed.
- 2026-09-22 — re-run from scratch, both periods, under E1 §15's
  2026-09-21 measurement correction (buy sizing net of costs; expense drag by
  calendar days), per GATE.md's rule for a measurement error. A base-row
  regression showed the correction moves the development gap to E1 base from
  +0.13 pp to +0.77 pp, which would make the verdict INCONCLUSIVE rather than
  REJECT; the full re-run decides it. Stack: E1 base as re-run under the same
  correction (`experiments/E1/regression/`). §3–§7 unchanged. Aarsh's
  decision.
