# HANDOFF — 2026-09-18

Written at session close for whoever picks this up next. Everything here is
state, not opinion. Where something is unknown or unfinished it says so.

`pytest -q` at close: **362 passed, 0 failed.**

---

## 1. Current stack and every verdict so far

**The adopted stack is E1 base.** Nothing has replaced it.

### E1 — INCONCLUSIVE (2026-09-17)

Charter LOCKED 2026-09-17. Sweeps in `experiments/E1/sweeps/`.

| | development 2007–2016 | validation 2017–2021 |
|---|---|---|
| base CAGR (after tax, liquidation-adjusted) | 9.34% | 26.12% |
| base MaxDD | 55.38% | 39.55% |
| turnover/yr | 1.6952 | 1.3131 |
| B2 (Nifty 500 TRI) | 8.07% | 14.79% |
| B3 (Nifty 200 Momentum 30 TRI, 0.3% drag) | 13.48% | 20.25% |

§13 arithmetic: C1 (≥2 pp over B2) failed in development (+1.27 pp), passed
in validation. C2 (≥2 pp over B3) failed in both. Verdict INCONCLUSIVE
because C1 did not fail in *both* periods, which is what REJECT requires.

Diagnostic at `docs/notes/E1-diagnostic.md`, including the 2026-09-17
correction: finding 6 (under-diversification as capital grows) is **not**
supported by the validation extras — names held recovered to 17.7–29.2 in
2017–2021. Finding 3 (universe rank 240–340 in both periods) stands.

### E1b — REJECT (2026-09-18)

Charter LOCKED 2026-09-18. Verdict at
`experiments/E1b/sweeps/validation-4eaf560fb1319d16/verdict.json`.

GATE vs E1 base:

| period | G1 | G2 | G3 | G4 | CAGR gap | MaxDD gap | rows holding | turnover |
|---|---|---|---|---|---|---|---|---|
| development | ✗ | ✓ | ✗ | ✓ | +0.13 pp | −0.70 pp | 5/14 | 1.16 vs 1.70 |
| validation | ✗ | **✗** | ✗ | ✓ | **−10.73 pp** | **+4.02 pp** | 0/14 | 1.00 vs 1.31 |

REJECT because G1 fails in both periods **and** G2 (do no harm) is violated
in validation.

E1 §13 C1–C4, reported because E1b was a candidate base: C1 fails both
(+1.40, +0.59 pp over B2); C2 fails both (−4.01, −4.87 pp vs B3); C3 passes
development, fails validation (+5.65 pp); C4 **0 of 14 rows** in both.
Verdict REJECT.

E1b base: development 9.47% / 54.67%, validation 15.38% / 43.58%.

**What it means.** E1b confined E1's rules to the Nifty 200. In development
that changed almost nothing (+0.13 pp). In validation it cost **10.7 pp**.
E1's 26.12% in 2017–21 came from holding small caps *outside* the Nifty 200
during a small-cap boom. The diagnostic's "universe drift to rank 240–340"
was not a defect to correct — it was where the money came from. E1b is
mechanically healthy (zero ADV skips in validation, turnover 1.00, 24–32
names held, median turnover rank 100–122, no delistings) and simply earns
less.

Development review at `docs/reviews/E1b-development.md`.

---

## 2. Built and tested vs stubbed

**Built, tested, used in a real run:**
`tax/india_lots.py`, `execution/costs.py`, `eval/periods.py` (incl.
`truncate_end`, `truncate_membership`, seal + journal), `eval/metrics.py`,
`eval/artifacts.py`, `eval/sweep.py`, `eval/classify.py` (§13 C1–C5 and
GATE G1–G4), `signals/momentum.py`, `portfolio/crash_rule.py`,
`portfolio/construct.py`, `backtest/engine.py`, `backtest/hooks.py`,
`backtest/runner.py`, `data/` — `bhavcopy`, `panel`, `universe`,
`instruments`, `symbol_isin`, `indices`, `calendar`, `corporate_actions`,
`nse_corporate_actions`, `dividends`, `red_flags`, and this session's
`index_changes`, `index_captures`, `index_membership`, `name_map`.

**Stubs raising `NotImplementedError` (only these two):**
`execution/paper.py`, `execution/kite.py`. Both are Phase 4, on ADVANCE
only, and nothing has ADVANCED.

**Collectors written but not exercised at scale:** `bse_announcements.py`
(works; only 2026 collected), `gdelt.py` (works; 4 files).

---

## 3. E1-P build state

E1-P was moved **ahead of** E1b on 2026-09-18 (reason recorded in
`ROADMAP.md`): it needs no new data, and blocking a ready experiment on an
unready dataset buys nothing. Order is now E1, E1-P, E1b, E2-A, …
**If E1b had been ADOPTED, E1-P would have been re-run on the E1b base
before its verdict was final. E1b was REJECTED, so that does not apply and
E1 base remains the comparison.**

Charter `charters/E1-P.md`, still **DRAFT — Aarsh has not locked it.**

**Done:**
- `defer_exit` hook is wired at `engine.py:374`, inside the exit loop and
  guarded by `reason == "band"`. §3's "delisting, suspension and red-flag
  exits are never deferred" therefore holds by construction, not by care.
  It receives month-end, ISIN, rank and lot ages in days — exactly §3's
  three conditions.
- The engine records `deferred` per decision, so §7's deferred-lot extras
  are computable from existing artifacts.
- GATE arithmetic (`gate_for_period`, `gate_verdict`) is generic and tested;
  E1-P needs a thin wrapper like `classify_e1b`'s GATE half, not new maths.
- Window, sweep machinery, summary, criteria.json, extras: all generic.

**Missing:**
1. **The §3 rule itself.** `hooks.from_config` builds only `side_sleeve`.
   There is no function implementing the 9–12 month / rank ≤ 100 / still
   eligible test, and no config wiring for it.
2. **N1/N2 controls cannot run.** `intra_month_exit` is declared in
   `hooks.py` but has **no call site in the engine loop** — only
   `defer_exit` and `pre_buy_constraint` are invoked. Separately,
   `EngineState` exposes `date`, `cash`, `positions`, `holdings_value` but
   **not cost basis**, which N1/N2 need for their −20% / +50% triggers. Two
   changes, both touching the E1 path, so the byte-identical-with-hooks-off
   test must be re-asserted afterwards.
3. **S1–S5 rows** do not exist (`sweep.py` has E1's `ROWS` and
   `e1b_rows()`). Mechanical once the rule exists.
4. **Two §7 extras**: forward 3-month return of deferred lots vs the lots E1
   would have sold; N1/N2 sell counts and their following 6-month returns.
   The rest of §7 already exists.

---

## 4. E1c charter status

`docs/strategies/E1c.md` — **DRAFT, written 2026-09-18 by Aarsh. Not
prepped, no code, not in ROADMAP or GATE order.**

It replicates the Nifty 200 Momentum 30 construction through this engine
(volatility-scaled 6+12-month momentum, top 30, score-tilted weights capped
5%, semi-annual rebalance) on E1b's universe, with E1's SIP, costs and tax.

Two things make it unusual and they need reading before any work starts:

- **§6 lets it move E1's bar.** If the replication's gap to B3 exceeds 2 pp
  in both periods, E1 §13's C2 is restated to "B3 as replicated through this
  engine" with a §15 line. That is the only sanctioned route by which an
  experiment may change E1 after its lock, and only downward toward what can
  actually be bought.
- **§3 declares a gap**: free-float shares outstanding are not in the panel,
  so weights are score-proportional capped at 5% rather than the fund's
  free-float tilt. S1 tests equal weight as the sensitivity.

Its S11 ("2012–2016 development only, E1 base re-run on that window") is the
same mechanism as E1b's S13, which is already implemented as
`sweep.period_for_row` plus the `_<row>_stack` companion run — reusable.

**Aarsh's instruction for the next session includes folding E1c's S7 into
E3 §7.** I have not looked at whether E3 §7 can take it; that is unexamined.

---

## 5. Background backfills — honest state

Most of these were **never started**. Stage 3 was redirected to E1b on
2026-09-17 and never resumed. Nothing below is in progress; no job is
running.

| item | state | what it needs |
|---|---|---|
| **BSE announcements 2010 backfill** | **Not done.** `data/bse_announcements/` holds **2026 only** (41 files, 6.3 MB). The collector works. | A backfill run from 2010. Then `red_flags.classify` over it, and the 50 most common flagged headlines into `docs/data/red_flag_sample.md` for Aarsh to review the keyword rules (Phase 1 task 1.5). |
| **GDELT** | Partial. `tools/gdelt_bigquery.sql` is written. `data/gdelt/` has `agg` and `daily` (4 files). | **Aarsh must run the BigQuery SQL** and drop the CSV in `data/gdelt/backfill/`. Nothing else can proceed until then. |
| **Shareholding** | **Not started.** No module, no data directory. | Source decision, then a collector. |
| **Point-in-time fundamentals** | **Not started.** No module, no data directory. | Source decision. Note the panel deliberately carries no shares outstanding (see §3 of E1c, and the `market_cap_proxy` note in every extras report). |
| **Macro** | **Not started.** No module, no data directory. | Source decision (E2-B). |
| **IPO list** | **Not started.** No module, no data directory. | Source decision (E4). |
| **ETF dividends** | **Not started.** `data/dividends/` has one file. ETFs are excluded from the E1 universe by §2/§15 (ISIN prefix `INF`), so this is an E3 input, not an E1 one. | Source decision (E3). |

**Done and current:** bhavcopy (2004-01-01 → 2026-09-16, 5,609 sessions),
panel (8,033,369 rows, 4,380 securities), corporate actions (2004–2026),
indices (6 series), index membership (see below).

---

## 6. Index-membership build

Built this session and **passing its gate**. Full write-up:
`docs/data/index_membership_finding.md`.

**Sources.** NSE's F&O "Change in the Constituents of Indices" circulars are
the *wrong* source — Nifty 200 appears in **zero** of all 98, because those
circulars exist to move F&O contracts and Nifty 200 has no derivatives. The
right source is NSE Indices' press-release archive
(`niftyindices.com/Press_Release/`), **1,486 releases 1998–2026**, plus
**72 Internet Archive captures** of the constituent CSVs (69 parsed) used as
anchors.

**State:** 4,203 changes parsed. Exact-list check — **Nifty 200 4/4, Nifty
100 21/21, Midcap 100 10/10, Nifty 500 13/14** (one miss: 2006-11-08,
`INE588A01016` absent, nothing invented). Nifty 100 = Nifty 50 + Next 50 on
the one date all three were captured. **The build exits zero.**

**Re-run:**

    python tools/build_index_membership.py --download   # network, ~20 min
    python tools/build_index_membership.py --parse      # PDFs -> changes, ~20 min
    python tools/build_index_membership.py --captures   # Internet Archive
    python tools/build_index_membership.py --build      # changes -> tables, ~1 min
    python tools/build_index_membership.py --all

Stages are separate and cached; only `--download` and `--captures` touch the
network. `--build` exits non-zero while the exact-list check fails, and the
fix is always more coverage, never a looser check.

**Key finding that shaped E1b §3/§4:** NSE's methodology says Nifty 200 is
"constituents forming part of Nifty 100 and Nifty Midcap 100" — but that is
written in the present tense. The captures show the two parents **overlapped
by 27 names in 2010 and 32 in 2014, and were disjoint only by 2026**. The
union identity became true at the 2016 restructure. So Nifty 200 membership
is published and exact from **2012-01-01**; before that E1b used a declared
**proxy** universe, labelled as such per month-end in the manifest.

---

## 7. §15 and charter lines added this session (2026-09-18)

**E1's §15 was NOT touched this session.** E1 §2–§13 are untouched since the
2026-09-17 LOCKED line.

E1b (`docs/strategies/E1b.md`, §10 change log), all dated **2026-09-18**:
- **LOCKED. No changes to §3–§7 after this line.**
- §3/§4 (draft, pre-lock): universe is Nifty 200 from 2012-01-01 and a
  declared proxy (CNX 100 ∪ CNX Midcap, point-in-time) for 2007–2011.
  Development stays 2007–2016, validation 2017–2021, with Aarsh's reasoning
  recorded: *the years being removed are the years the hypothesis is about.*
- §6 (draft): **S13** added — development restricted to 2012–2016 with E1
  base re-run on the same window.
- §6 (draft): **S12 revised** — no longer drops guessed-window names; places
  each guessed start at the latest possible date so base and S12 bracket the
  truth.
- §6 (draft): S12 originally added (superseded by the line above).

`CLAUDE.md` rule 7 (both copies), 2026-09-18: **`pypdf` added** to the
allowed dependencies for the NSE constituent-change circulars, with
**`pdfplumber` as a named fallback**, permitted only for a circular whose
tables pypdf returns garbled. Declared in `pyproject.toml`.

`ROADMAP.md` (both copies), 2026-09-18: order changed to **E1, E1-P, E1b,
E2-A, …** with the reason, the re-run-on-adoption rule, and E1b's
three-working-day time-box (which closed on time).

E1c `docs/strategies/E1c.md` §9: draft, 2026-09-18, written by Aarsh.

---

## 8. Open questions I was not comfortable resolving alone

1. **The invested-equity metric took three attempts and the artifacts still
   carry version 2.** See §9 task 1. Versions 1 and 2 were wrong (NaN from
   the sleeve emptying; window starting at the panel start; then a
   time-weighted construction that weights a ₹4,239 stub the same as a fully
   invested day). Version 3 is a capital-weighted decomposition that
   *reconciles* to the pre-tax return, which is the property the first two
   lacked. **The `Invested equity alone` table in both E1b summaries is
   version 2 and should be ignored.**
2. **`write_summary` overwrites unconditionally**, unlike `write_run` which
   verifies and refuses. Both E1 re-runs this session wrote back into their
   original content-addressed directories; the originals survive only
   because I copied them to `experiments/E1/_preregen_backup/` and
   `experiments/E1b/_prererun_backup/` first. This is a real gap against
   principle 9 and I did not change it mid-run.
3. **Momentum-30 overlap (E1b §8) is unavailable and always will be for
   2007–2016.** The Internet Archive has that list only from 2021 and the
   index launched in the 2020s with back-computed levels. Measuring against
   today's 30 names would be a survivorship artefact, so the extras report a
   sentence. Whether that is acceptable for E1c (which replicates the fund)
   is Aarsh's call.
4. **The membership bracket may be wider than anything E1b could measure.**
   In development, base 9.47% vs S12 11.61% — a 2.14 pp spread from
   inclusion-date timing alone. E1b's REJECT rests on validation's −10.73 pp,
   far outside that, so the verdict is safe. But no *small* effect is
   measurable on the 2007–2011 proxy years.
5. **Whether E1's §13 C2 bar is honest at all.** E1c §6 exists to test this.
   If B3's 13.48% / 20.25% does not survive real trading and tax, then C2
   has been failing every experiment against an unbuyable number. I did not
   act on this; it is E1c's job.
6. **E1c's S7 into E3 §7** — Aarsh's instruction. I have not read E3 §7 to
   see whether it can take it.
7. **Nifty 500's membership table is much weaker than Nifty 200's** (56% of
   names have a guessed window; `carry_back` median 676 d,
   `inferred_start` median 1,150 d). E1b's S10 used it. Any future row that
   leans on Nifty 500 membership should be read with that in mind.

---

## 9. The exact next four tasks, in order

**1. Re-run both E1b sweeps with decomposition v3 and persisted equity
curves.** The verdict does not change — it never depended on the extras —
but the `Invested equity alone` column in both summaries is version 2 and is
wrong. `artifacts.equity_sleeve_return` is already rewritten and tested
(base row development, computed offline: equity **8.67 pp/yr**, cash
**1.38 pp/yr**, sum 10.05% against 10.20% pre-tax). While re-running, also
**persist per-row equity curves and trade ledgers** into the sweep
directory, so no future extra ever requires a re-run — this session lost
three sweeps to exactly that. Then update `docs/reviews/E1b-development.md`
with the corrected table.

    python -c "from pflab.backtest import runner; runner.main('configs/e1b.toml','development',sweep=True)"
    python -c "from pflab.backtest import runner; runner.main('configs/e1b.toml','validation',sweep=True)"

**2. E1c into ROADMAP and GATE order, with S7 folded into E3 §7.** Decide
where E1c sits (it calibrates the benchmark, so it plausibly precedes
everything that is judged against B3), update both `ROADMAP.md` copies and
`charters/GATE.md`'s order line, and move E1c's S7 (costs ×2) into E3 §7 as
Aarsh asked — after reading E3 §7 to confirm it fits.

**3. Finish E1-P.** In order: implement §3's rule and wire it through
`hooks.from_config`; add a call site for `intra_month_exit` and cost basis
to `EngineState` so N1/N2 can run; re-assert the byte-identical-with-hooks-
off test; add `e1p_rows()` S1–S5; add the two missing §7 extras; add the
GATE wrapper. Then Aarsh locks and it runs against E1 base.

**4. E1c prep.** Volatility-scaled 6+12 momentum signal, score-tilted
capped weights, semi-annual rebalance, and the eleven sweep rows. Reuse
`sweep.period_for_row` and the `_<row>_stack` companion for S11. Do not run
before Aarsh locks.

---

## 10. Seal

**The sealed period (2022–2025) was never opened.** `research/journal.jsonl`
does not exist, which is the proof: `periods.open_period` creates and
appends to it only on a reveal, and only a sealed period can trigger one.
Zero reveal lines. No run this session used anything but `development` and
`validation`, both unsealed.
