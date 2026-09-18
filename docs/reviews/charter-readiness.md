# Charter readiness — E1-P through E5

Written 2026-09-17, after E1's engine was built and the charter locked. No
code was written for this review and no charter was edited. Every proposed
resolution below is a proposal: it needs a §15 line in the charter concerned
before anything acts on it.

## What exists today

`data/panel/prices.parquet` — 8,033,369 rows, 4,380 securities,
2004-01-01 .. 2026-09-16, typed STK 7,612,701 / ETF 405,808 / INVIT 8,927 /
REIT 5,933. Columns: `date, isin, symbol, series, instrument_type, open,
high, low, close, prev_close, volume, turnover, adj_factor, adj_close,
adj_open, dividend`.

Also collected: 1,224 corporate-action factors, 22,514 dividends, six index
series (four price/TRI + two valuation), 5,638 bhavcopy sessions, 40 days of
BSE announcements, 4 days of GDELT.

## Engine hooks Stage 1 built

| hook | for | state |
|---|---|---|
| `intra_month_exit(t, held, state)` | E2-A, E1-P N1/N2 | built, inert, tested |
| `defer_exit(m, isin, rank, lot_ages_days, state)` | E1-P | built, wired to real lot ages |
| `pre_buy_constraint(m, isin, qty, price, state)` | E2-B | built, skips to next candidate |
| `tax_class(isin)` | E3 | **interface only — see E3 §5 below** |
| `side_sleeve` | E4 | built, proven not to touch E1 cash |

---

## E1-P — Patience

**Data:** none new. Runs on the panel as it stands.

**Backfills:** none.

**Hooks:** `defer_exit` (built) for the candidate rule; `intra_month_exit`
(built) for negative controls N1 and N2, which fire on a position's own
drawdown between month-ends.

### Not implementable as written

> §3: "A band exit (rank > 50 on month-end M) for a held **lot** is deferred
> if all three hold: the **lot** is between 9 and 12 months old…"

E1 §4 says a held name "is sold **in full** at the next session's open". A
name bought over several months has lots of different ages, so the two rules
collide: the lot-level test can qualify one lot and not another, while E1
requires the position to go in one piece. The same ambiguity is in sweep row
S5, "minimum hold of 6 months on every lot regardless of rank".

*Proposed resolution (not applied):* state in E1-P §3 which of these it
means — (a) defer the whole position when the **oldest unsold lot** qualifies,
(b) defer when **every** lot qualifies, or (c) allow partial sales, which
would be a change to E1 §4 and needs its own §15 line. (a) is closest to
E1's "in full" and is the only one needing no E1 change.

> §3: "the name is still eligible and **has no red flag (once E2-A exists)**"

E1-P runs before E2-A in the sequence, so this clause is inert at E1-P time.

*Proposed resolution:* say explicitly that the clause is dormant for E1-P's
own run and that adopting E2-A later does not retroactively change E1-P's
verdict.

---

## E2-A — Firm-level red flags

**Data in the panel today:** none of it. Announcements are a separate store.

**Backfills required**

| what | source | status |
|---|---|---|
| BSE announcements 2010-01-01 → today | `api.bseindia.com` AnnSubCategoryGetData (verified working) | 40 days held; **~5,900 days to go** |
| BSE scrip code → ISIN map | BSE equity master | not collected, not yet located |
| NSE announcements (conditional) | NSE | only if BSE coverage < 95% on a 200-name sample |

The scrip-code map is the hard dependency: BSE rows key on `scrip_code`, the
panel keys on ISIN, and CLAUDE.md 8 forbids joining on symbol without a date.

**Hooks:** `intra_month_exit` (built). §3's "sold at the open of the next
session after dissemination" is the only intra-month action in the stack and
the hook exists for exactly it.

### Worth flagging

> §7: "S4–S12 each flag type removed one at a time (nine rows)"

That makes twelve sweep rows with S1–S3. GATE G3 requires "two thirds of the
experiment's sweep rows", so the bar is 8 of 12, not 6 of 9. Arithmetic only,
but it should be stated so the verdict is not computed against the wrong
denominator.

> §4: "the rules in `pflab/data/red_flags.py` **as of the freeze commit**"

The rules were rewritten on 2026-09-16 against a 41,128-announcement sample
(`docs/data/red_flag_sample.md`). The nine flags now match §4's list exactly.
The freeze commit should be named in §4 once E2-A's charter locks.

---

## E2-B — Shock-exposure graph

**Data in the panel today:** prices only. No factor is collected.

**Backfills required**

| what | source | notes |
|---|---|---|
| Brent (USD), USDINR, US 10-year | FRED, CSV, free | daily, full window |
| Net FII equity flows | NSE / NSDL daily reports | monthly aggregation per §3 |
| India VIX | NSE `BindHistoricalIndiaVixData` | **from 2009 only — §3 already declares this** |
| NSE industry classification | NSE sector file | one file; see below |

**Hooks:** `pre_buy_constraint` (built). §4's "a buy that would breach any
factor's cap is skipped and the next entry candidate by rank is tried" is the
hook's exact contract.

**Not built:** a monthly-return panel (the engine works in sessions; §3 wants
"trailing 36 **monthly** returns") and a sector map. Both are derived data,
not backfills.

### Worth flagging

> §3: "sectors (NSE industry classification, **current mapping applied to
> history — declared simplification**)"

This is a knowing lookahead: a company's 2026 sector is applied to its 2008
returns. It is declared, so it is legitimate under the charter — but it is
the one place in the stack where a point-in-time rule is deliberately
suspended, and CLAUDE.md 4 says "point-in-time everywhere". The tension should
be visible in the manifest, not only in the charter text.

> §4: "betas value-weighted by holding size **after the planned buys**"

The cap therefore depends on the buy being tested, and buys are decided in
sequence, so the constraint is path-dependent on the order candidates are
tried. §4 fixes that order ("the next entry candidate by rank"), so it is
well defined — but the implementation must re-evaluate after each accepted
buy, not once per month-end. Worth stating so it is not implemented as a
single pre-check.

---

## E2-C — Event-intensity regime input

**Data in the panel today:** none.

**Backfills required**

| what | source | notes |
|---|---|---|
| GDELT India daily aggregate 2015-02-18 → today | BigQuery, `tools/gdelt_bigquery.sql` (written) | **Aarsh runs it; needs a GCP account** |
| India VIX | NSE | shared with E2-B |

**Hooks:** none. The rule changes how RISK_OFF is computed, which is an input
to the existing §6 logic, not a new action.

### Not implementable as written

> §3: "20-session mean GDELT India tone at M below its trailing **3-year**
> 10th percentile"
> §5: "Development **2015-03-01** .. 2019-12-31"

GDELT 2.0 begins 2015-02-18. A trailing three-year percentile cannot exist
until 2018-02. As written, the first ~35 months of the development window
cannot evaluate the tone leg at all, so the rule silently degrades to
VIX-only for most of its own development period — which is also sweep row S3,
making S3 nearly a duplicate of the base row.

*Proposed resolution (not applied):* either (a) start development 2018-03-01
and accept a shorter window, (b) use an expanding-window percentile with a
declared minimum history, or (c) state that the composite is VIX-only before
2018 and report the two sub-periods separately. This is a real choice about
what the experiment can claim and it should be made before the first run, not
discovered in the results.

---

## E2-D — Positioning

**Data in the panel today:** none.

**Backfills required**

| what | source | from |
|---|---|---|
| Quarterly shareholding patterns (promoter %, shares outstanding) | NSE/BSE, filing date as the PIT key | ~2009 |
| PIT insider disclosures | NSE structured; BSE earlier | **structured only from ~2015** |
| Bulk and block deals | NSE daily | stored, reported, not in the rule |

**Hooks:** none. §3 exits "at the next month-end (not intra-month)", which is
E1's existing path.

### Not implementable as written

> §5: "Development **2010-01-01** .. 2016-12-31"
> §4: "PIT (insider trading) disclosures from NSE… **Structured from ~2015**;
> earlier from BSE."

The rule's second limb (net insider transactions) has no structured source for
2010–2014, which is five of the seven development years. Sweep row S4 is
"PIT only (no shareholding pattern)" — that row is empty for most of its own
development window.

*Proposed resolution (not applied):* declare the PIT limb active from 2015
and report S4 on 2015+ only, or fall back to BSE's earlier unstructured
disclosures with the extraction quality declared. Either way the charter
should say which, since the rule is an OR and a missing limb silently weakens
it rather than failing loudly.

---

## E3 — Defensive sleeve

**Data in the panel today: all three sleeve candidates are present and typed.**

| symbol | rows | from | type |
|---|---|---|---|
| LIQUIDBEES | 5,628 | 2004-01-01 | ETF |
| GOLDBEES | 4,832 | **2007-03-19** | ETF |
| NIFTYBEES | 5,637 | 2004-01-01 | ETF |

SILVERBEES exists from 2022-05-10 and §3 already excludes it.

**Backfills required:** ETF dividend histories for the three, to replace §5's
declared 5.5% liquid-ETF assumption with actuals.

### The one real gap in Stage 1

> §5: "Tax and cost module (**required, new**) — Gold ETF: not equity.
> Gains ≤ 12 months at slab… Nifty ETF: equity rates… Liquid ETF: … taxed at
> slab"

Stage 1 built `tax_class(isin)` as an interface, and the engine can ask it
for a class — but `LotBook` still holds a **single** `TaxPolicy`. Nothing
consumes the answer. E3 needs per-class policies threaded through
`settle_fy` and `simulate_liquidation`, which is real work on the tax engine,
not a hook.

*This is the one place where Stage 1's "so the engine is not rewritten per
experiment" goal is only half met.* Flagging it now rather than discovering it
when E3 starts.

### Worth flagging

> §6: "E1's full window **from 2007** (gold ETF listing). Development
> 2007–2016"

GOLDBEES' first row is 2007-03-19 and E1's development starts 2007-01-01, so
the first ~2.5 months have two candidates, not three. §4's rule ("the
candidate with the highest 10-month return") also needs ten months of history,
so gold cannot actually be selected before 2008-01. Minor, but it should be
declared rather than left to the run.

---

## E4 — IPO listing gains

**Data in the panel today:** listing-day prices only (the first bhavcopy row
of each ISIN), which §5 says is the intended source.

**Backfills required**

| what | source | notes |
|---|---|---|
| NSE mainboard IPO list 2010+ (issue price, lot size, dates, category subscription) | NSE past issues; Chittorgarh cross-check | not collected |
| GMP history 2019+ | IPO Watch / Investorgain archives | fragile; §5 already requires a capture date per value |

**Hooks:** `side_sleeve` (built; ₹2 lakh, tested never to touch E1's cash).

### Not implementable as written

> §3: "the last subscription figure published **before the retail cutoff on
> the final day**"
> §5: "Subscription snapshots: exchange intraday figures **where archived**;
> else the final-day close figure with the lookahead declared and S1 as the
> check."

If intraday snapshots are not archived — and for 2010-era issues they almost
certainly are not — then the main rule cannot be evaluated without using a
figure published after the decision point. §5 acknowledges this and offers S1
(day-2 close) as the check, but the charter still calls the lookahead-bearing
version the main rule.

*Proposed resolution (not applied):* make S1 the main rule wherever intraday
snapshots are unavailable, and report the final-day version as the sweep row,
inverting §3 and S1. That keeps the headline number free of lookahead. The
alternative — keeping §3 as written — means the headline number carries a
declared lookahead, which §8's "this is the number that decides whether it is
worth doing" makes uncomfortable.

---

## E5 — Learned signals

**Data:** everything E5-A needs beyond prices comes from E2-A, E2-B and E2-D,
so E5 inherits all of their backfills. Nothing additional.

**Hooks:** none. E5 replaces the momentum rank, which is a signal swap inside
`_decide`, not a new action.

### Worth flagging

> §2 E5-A: "LightGBM on the cross-section"
> CLAUDE.md 7: "Keep it dependency-light. pandas, pyarrow, duckdb, numpy,
> requests, python-dateutil, tomli/tomllib. **No backtesting frameworks.**"

LightGBM is not a backtesting framework, so it does not breach the letter of
the rule, but it is a substantial new dependency, and E5-B's retrained Kronos
adds a deep-learning stack and a 12 GB GPU requirement.

*Proposed resolution (not applied):* add an `[e5]` optional-dependency group
in `pyproject.toml` so the core harness stays installable without them, and
say so in CLAUDE.md 7 rather than leaving the tension implicit.

> §2 E5-B K1: "**Declared contaminated**… cannot be the basis for adoption.
> Clean evidence comes only from the live year."

This is well handled, but note the live year is twelve monthly observations
(ROADMAP: "Twelve observations do not"), so K1 can never be adopted on the
current plan. That is a coherent position — it should just be stated as
"reported permanently, adoptable never" rather than deferred to a live year
that cannot settle it.

---

## Backfills ranked by wall time

| rank | backfill | estimate | blocking | notes |
|---|---|---|---|---|
| 1 | BSE announcements 2010→today | **~60 hours** | E2-A | ~5,900 days at ~37 s/day, paginated. The single longest job in the roadmap. |
| 2 | GDELT BigQuery export | ~1 hour of Aarsh's time | E2-C | needs a GCP account; SQL written |
| 3 | Quarterly shareholding patterns 2009→ | ~8–12 hours | E2-D | ~68 quarters × ~2,000 names |
| 4 | PIT insider disclosures 2015→ | ~4–6 hours | E2-D | daily endpoint |
| 5 | NSE IPO list 2010→ | ~2 hours | E4 | ~600 issues |
| 6 | Bulk/block deals | ~2 hours | E2-D (reported only) | daily files |
| 7 | GMP history 2019→ | ~2 hours + fragile | E4 (S7 only) | scraped archives, may fail |
| 8 | India VIX | ~15 minutes | E2-B, E2-C | one endpoint, 2009+ |
| 9 | FRED series (Brent, USDINR, US10Y) | ~10 minutes | E2-B | three CSVs |
| 10 | FII flows | ~30 minutes | E2-B | NSE/NSDL |
| 11 | ETF dividend histories (3 names) | ~5 minutes | E3 | already have the feed |
| 12 | BSE scrip→ISIN master | ~10 minutes | E2-A | one file, but a hard dependency |
| 13 | NSE industry classification | ~10 minutes | E2-B | one file |

Everything from rank 8 down is under an hour in total and unblocks four
charters' worth of preparatory work. Rank 1 dominates the critical path and
should start first even though E2-A is third in the sequence.

## Summary of things that need a decision before their run

| charter | issue | severity |
|---|---|---|
| E1-P | lot-level deferral vs E1's "sold in full" | must resolve — changes results |
| E2-C | 3-year percentile cannot exist for the first 35 months of its window | must resolve — changes the window |
| E2-D | PIT limb has no source for 5 of 7 development years | must resolve — weakens the rule silently |
| E4 | main rule may carry a declared lookahead the headline number depends on | must resolve — §3 vs S1 |
| E3 | `LotBook` holds one `TaxPolicy`; per-class tax is unbuilt | build work, not a decision |
| E2-A | sweep is 12 rows, so G3's bar is 8 not 6 | arithmetic, state it |
| E2-B | current sector map applied to history vs CLAUDE.md 4 | declared; surface in manifest |
| E5 | LightGBM/Kronos vs CLAUDE.md 7 | packaging decision |
