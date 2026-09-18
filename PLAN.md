# Plan — from empty repo to a live paper year

Goal: a personal, tax-aware monthly-SIP portfolio over NSE stocks that
beats a Nifty 500 TRI SIP and a Nifty 200 Momentum 30 index fund after
tax, by a pre-registered margin, in sealed walk-forward tests and then in
a live paper year. Events (E2) and ML/graph (E3) enter only after the
simple baseline (E1) has been judged under the same harness.

Division of labour: **Claude Code writes and runs all code. Aarsh makes
every decision that touches the charter, reviews results, and does the
things that need his accounts.**

## Phase 0 — Done (this session)

- E1 charter (`docs/strategies/E1.md`), E2 pre-definition, principles.
- Repo skeleton with module contracts.
- Verified, unit-tested: India tax lot engine, Zerodha cost model,
  period sealing + journal, metrics (unitized NAV, CAGR, MaxDD, Sharpe,
  XIRR, bootstrap), momentum, crash rule, buy-list construction,
  universe filter, bhavcopy normaliser (both NSE formats).
- Written but not yet run against live endpoints: bhavcopy, BSE
  announcements, GDELT collectors; red-flag keyword classifier.

## Where Claude Code takes over: **Phase 1, task 1.1**

Aarsh, on your machine:
1. `git init`, copy this repo in, `python -m venv .venv`,
   `pip install -e ".[dev]"`, `pytest -q` (should pass).
2. Set `PFLAB_DATA_DIR` to a folder on D:.
3. Open Claude Code in the repo. Its first prompt is:
   *"Read CLAUDE.md and docs/strategies/E1.md. Start Phase 1 task 1.1."*

From that point Claude Code owns every task in `CLAUDE.md`. Your jobs
per phase are listed below.

## Phase 1 — Data (sprint: 2–3 days; see docs/PHASE1_SPRINT.md)

| task | who | done when |
|------|-----|-----------|
| 1.1 bhavcopy collector fixed + 2005→today backfill | Claude Code | `data/bhavcopy/` has ~5,000 daily parquet files, log lists holidays |
| 1.2 corporate-actions collector + purpose parser | Claude Code | parser tests pass on 30 real strings |
| 1.3 adjusted total-return panel + plausibility checks | Claude Code | `data/panel/prices.parquet`; findings report reviewed by Aarsh |
| 1.4 index TRI series ingested | Aarsh downloads CSVs from NSE Indices; Claude Code ingests | calendar assertion passes |
| 1.5 BSE announcements backfill 2010→today | Claude Code | `docs/data/red_flag_sample.md` reviewed by Aarsh |
| 1.6 GDELT backfill via BigQuery | Aarsh creates a GCP account, runs the SQL; Claude Code writes it | `data/gdelt/` daily aggregate exists from 2015 |
| 1.7 daily collector scheduled | Claude Code writes; Aarsh schedules on Windows | it has run three days in a row |

Aarsh's review points: the plausibility findings (1.3) and the red-flag
keyword sample (1.5). Both are half-hour reads.

## Phase 2 — Engine (week 4)

Claude Code implements engine, benchmarks, artifacts, lookahead tests,
random-walk negative control, sweep, classify. Done when `pytest -q`
passes including the lookahead and seal-identity tests, and a synthetic
random-walk run returns roughly the cash rate minus costs.

Aarsh's decision point: **lock the charter.** Read E1 §2–§13 once more.
If C2 (2 points over the momentum index fund) feels wrong, change it now
and log it in §15. After the first development run it cannot change.

## Phase 3 — Runs (week 5)

1. Development sweep (base + S1–S9, all benchmarks).
2. Aarsh writes `docs/reviews/E1-development.md`: what the numbers say,
   what surprised him, no parameter changes.
3. Validation sweep. `pflab classify` prints the verdict.
4. Sealed period stays sealed regardless of verdict.

## Phase 4 — Branch on the verdict

**ADVANCE**
- Claude Code builds `execution/kite.py` (Kite Connect Personal, free
  plan: orders and holdings, no data; prices come from the daily
  bhavcopy). Paper mode: the month-end job writes the order list and
  logs intended fills against the next open.
- Aarsh requests the single sealed reveal in writing
  (`research/journal.jsonl` records it). One run. No re-runs.
- E2-A (red flags) starts as a chartered experiment on top of E1.

**INCONCLUSIVE or REJECT**
- Claude Code writes `docs/notes/E1-diagnostic.md`: turnover, cost drag,
  tax drag, which sweep rows failed, attribution by year.
- Aarsh decides one of: (a) buy the momentum index fund and keep the
  harness for E2 research, (b) charter E1b with a documented reason that
  is not "the number was low". The sealed period is still untouched.

## Phase 5 — Live paper year (Oct 2026 → Sep 2027)

- Month-end job runs automatically; fills are compared to reference
  prices; the ledger accumulates.
- The daily collectors keep running; GDELT and announcements now cover
  the live window in full, which is what E2 needs.
- What the year proves: the machine works, slippage matches assumptions,
  nothing peeked. What it does not prove: alpha. Twelve observations
  cannot. Real money decisions after the year use the sealed-history
  result plus the live year's operational record, not the live year's
  return.

## Standing rules for the whole plan

- Anything that changes a rule is a charter change with a date.
- Sweeps never become menus.
- LLMs (including Claude Code) never pick parameters. They implement,
  test, and report.
