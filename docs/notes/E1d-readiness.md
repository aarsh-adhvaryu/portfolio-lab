# E1d — readiness note

Written 2026-09-22; **updated 2026-09-24, when the four pieces were built.**

E1d (`docs/strategies/E1d.md`, DRAFT, written by Aarsh 2026-09-21) is E1
with one change: E1c's volatility-scaled 6+12 score, standardised within the
eligible universe and clipped at ±3, replaces raw 12-1 momentum as the
**ranking** signal. Everything else stays E1's, including equal-weight
shortfall buys.

**Status: buildable end to end and ready for Aarsh's lock. NOT RUN.**
All four missing pieces are built and tested; `pytest -q` is **479 passed**.
Nothing about E1d has been executed against real data.

## 1. The four pieces, as built

| # | piece | where | tests |
|---|---|---|---|
| 1 | `strategy.score_windows` (default `[126, 252]`) passed to `vol_scaled_ratios`, so S1 = `[126]` and S2 = `[252]` | `backtest/engine.py`, the signal block | `test_e1d.py` × 4 |
| 2 | `sweep.e1d_rows()` — base plus S1–S10 — and the `strategy.id == "E1d"` branch | `eval/sweep.py` (`E1D_ROWS`), `backtest/runner.py` | `test_e1d.py` × 3 |
| 3 | `configs/e1d.toml` — E1's config plus the score block and a `[membership]` section for S10 | `configs/e1d.toml` | `test_e1d.py` × 4 |
| 4 | `classify.classify_e1d` — GATE vs E1 base, C1–C4, mandate | `eval/classify.py` | `test_e1d.py` × 4 |

Two properties the tests enforce that are worth naming, because they are the
ways E1d could quietly stop being one change:

- **`test_config_is_e1_everywhere_except_the_score`** diffs `e1d.toml`
  against `e1.toml` key by key and fails on any difference outside
  `{id, charter, signal, score_order, score_windows}`. E1d cannot drift into
  a second change without a test failing.
- **`test_no_e1d_row_touches_weighting`** fails if any sweep row sets a
  weighting scheme or `selection_n`. §3 says the score ranks only.

An empty `score_windows` raises rather than silently falling back to the
pair. Benchmarks are unaffected: `run_index_benchmark` builds its strategy
from a whitelist, so a new knob cannot leak into B1–B5 (the defect of
2026-09-21).

**The byte-identity re-assertion was run after the change.** E1 §2–§13 and
E1b §3–§7 are identical to commit `0ae301e`; E1-P §3–§7 and E1c §3–§7 match
their recorded hashes (`bbf90dc8…`, `10c6f6ee…`).

## 2. Every line of E1d against the engine

| E1d line | supported? |
|---|---|
| §3 score: 6+12, vol-scaled, skip a month, averaged, z-scored in the eligible universe, ±3 clip | **yes** — `signal = "vol_scaled_6_12"`; standardisation happens within `eligible_at` at each decision date |
| §3 ranking only | **yes** — no `weighting` key, so E1 §5's equal-weight `buy_list` runs untouched |
| §3 universe top 500 by traded value, N = 25, band 50, monthly | **yes** — E1 defaults, `mode = "turnover_top_n"` |
| §3 buy sizing net of costs (E1 §15, 2026-09-21) | **yes** — `_fit_to_cash` |
| §3 SMA-10 filter, costs, tax, suspension, delisting | **yes** — unchanged E1 paths |
| §4 window 2007–2016 / 2017–2021, sealed untouched | **yes** |
| §4 benchmarks B1–B5 | **yes** — B5 at 0.30% drag, reported only |
| §5 S1, S2 (score components) | **yes** — piece 1 |
| §5 S3–S7, S9 (N/band, costs, trend, delisting) | **yes** — existing E1 knobs |
| §5 S8 NSE's order | **yes** — `score_order = "z_then_average"` |
| §5 S10 Nifty 200 point-in-time | **yes** — see the caveat in §3 below |
| §6 GATE + C1–C4 + mandate | **yes** — piece 4 |
| §8 selection overlap with E1 base each month-end | **yes, post hoc** — both E1 regression directories carry `rows/base/decisions.json` |
| §8 other extras | **yes** — already in every sweep's `extras.json` |

**No line of E1d is unsupported by the engine.** Three things the lock
should nevertheless settle, below.

## 3. Three things for Aarsh to settle at the lock

**(a) §3's "as amended 2026-09-21" is ambiguous, and it defines E1d's one
change.** E1c's change log carries four entries dated 2026-09-21. Three are
about *weighting* — weights proportional to `max(score, 0)` capped at 5%,
S6's raw momentum, S4's weights through the band — and E1d uses none of
them, because it weights equally. The fourth is a **code fix**, declared as
changing no charter text: §3 says the score is standardised "across the
universe", but the implementation standardised across every name in the
panel and restricted to the universe afterwards; it now standardises within
the eligible universe at each decision date.

Only that fourth one touches the score, so E1d §3 resolves to it, and the
engine implements it. But E1d's single change should not rest on a reader
picking the right entry out of four. Suggest the lock replaces "as amended
2026-09-21" with the substance: *standardised within the eligible universe
at the decision date*.

Related, and Aarsh's to judge: E1c's §3–§7 hash is unchanged since the
2026-09-19 lock, yet the 2026-09-21 entries describe amendments to §3's
weighting rule. The rule changed in the change log without §3's text
changing. That is recorded here because it was noticed, not because E1d
depends on it — E1d does not.

**(b) S10's first five years are a declared proxy, not the Nifty 200.**
Nifty 200 membership is published and exact only from 2012-01-01
(`docs/data/index_membership_finding.md`); before it, `index_membership`
substitutes the declared proxy (CNX 100 ∪ CNX Midcap, point-in-time) and
labels every month in the manifest. E1d's development window starts in 2007,
so **five of S10's ten development years run on the proxy.** This is exactly
what E1b did and it is handled automatically, but S10's purpose is to show
whether the gain depends on the universe, and for half of development it
shows that against a reconstruction rather than the index. Read S10's
development number with that in mind; its validation number (2017–2021) is
fully published.

Worth recalling alongside it: E1b measured a 2.14 pp development spread
between `earliest` and `latest` inclusion bounds, so membership timing alone
moves the answer by more than GATE's G1 threshold of 0.5 pp. S10 uses
`earliest`, as E1b's base did.

**(c) §7 is right, and the classifier now carries it.** E1d's hypothesis
came from E1c's S6 on these same development and validation years, so those
years are no longer unseen for this question. `classify_e1d` writes a
`section7` block into the verdict naming the prior exposure and the
consequence, so the number cannot be read later without it. The only clean
test left is the sealed period, which MANDATE §14 reserves for a stack that
meets §3 and §5.

## 4. Two things the lock should know (unchanged from 2026-09-22)

- **The ±3 clip makes ties at the top.** Names whose z-score reaches +3 all
  score exactly 3.0 and are ranked by position among themselves. For ranking
  only this is harmless: they are always well inside the top 25, and it
  never touches the band edge at 50.
- **A pass is weaker evidence than a pass on a fresh hypothesis** (§7 above).

## 5. Readiness

**Ready to lock and run.** After Aarsh settles §3(a) — or decides it needs
no settling — the sequence is the usual one: append the LOCK line to E1d
§10, run the development sweep, Aarsh writes `docs/reviews/E1d-development.md`,
run the validation sweep, classify with `classify_e1d`, write the verdict
note. Do not touch the sealed period.
