# E1d — readiness note (2026-09-22)

E1d (`docs/strategies/E1d.md`, DRAFT, written by Aarsh 2026-09-21) is E1
with one change: E1c's volatility-scaled 6+12 score, standardised within
the eligible universe and clipped at ±3, replaces raw 12-1 momentum as the
**ranking** signal. Everything else stays E1's, including equal-weight
shortfall buys.

**Not run, and not yet buildable end to end** — four small pieces of code
are missing (§2). None needs new data.

## 1. What the engine already supports, line by line

| E1d line | supported? | how |
|---|---|---|
| §3 score: E1c §3 as amended, z-scored within the eligible universe, ±3 clip | **yes** | `strategy.signal = "vol_scaled_6_12"`; the engine standardises within `eligible_at` at every decision date (E1c §9 fix, 2026-09-21) |
| §3 ranking only | **yes** | `strategy.weighting = "equal"` (the default): no target weights, so E1 §5's equal-weight `buy_list` runs unchanged |
| §3 E1's universe, N = 25, band 50, monthly decisions | **yes** | `rebalance = "monthly_band"` (the default) takes `_decide`, which now ranks by `score_fn` when one is set |
| §3 buy-sizing correction | **yes** | `_fit_to_cash`, E1 §15 2026-09-21 |
| §3 SMA-10 trend filter, costs, tax, suspension, delisting | **yes** | unchanged E1 paths |
| §4 window, B1–B5 | **yes** | B5 now at 0.30% drag |
| §5 S3, S4 (N/band), S5 (costs ×2), S6, S7 (trend filter), S9 (delisting) | **yes** | existing strategy knobs |
| §5 S8 NSE's order | **yes** | `strategy.score_order = "z_then_average"` |
| §5 **S1** 6-month component only, **S2** 12-month only | **NO — needs code** | the engine hard-codes `windows=(126, 252)`; needs a `strategy.score_windows` knob |
| §5 **S10** universe = Nifty 200 point-in-time | **needs config** | `runner.prepare` loads the membership table only when the BASE config asks for it; `configs/e1d.toml` must carry a `[membership]` section, which the turnover-ranked base row then ignores |
| §6 verdict: GATE + C1–C4 + mandate | **needs a thin wrapper** | `classify_e1c` has all three blocks plus an E1c-only §6 block; E1d wants the three without it |
| §8 selection overlap with E1 base at each month-end | **yes, post hoc** | from `rows/base/decisions.json` of the E1d sweep and of E1 base's **regression** re-run (the original E1 sweeps predate decision persistence) |
| §8 other extras | **yes** | already in every sweep's `extras.json` |

## 2. Code needed before E1d's first run

1. `strategy.score_windows` (default `[126, 252]`) passed to
   `vol_scaled_ratios`, so S1 = `[126]` and S2 = `[252]`. With one window
   the two §3 orders coincide, which is correct.
2. `sweep.e1d_rows()` — base plus S1–S10 — and a runner branch for
   `strategy.id = "E1d"`.
3. `configs/e1d.toml` — E1's config plus `signal = "vol_scaled_6_12"` and a
   `[membership]` section for S10.
4. `classify.classify_e1d` — GATE vs E1 base (read from the 2026-09-21
   regression re-run), C1–C4, mandate.

Plus the usual: a byte-identity re-assertion for E1, E1b, E1-P and E1c after
the change.

## 3. Two things the lock should know

- **The ±3 clip makes ties at the top.** Names whose z-score reaches +3 all
  score exactly 3.0 and are ranked by position among themselves. For
  ranking only this is harmless: they are always well inside the top 25.
  It never touches the band edge at 50.
- **§7 is right, and worth keeping in view.** E1d's hypothesis came from
  E1c's S6 on these same years. A pass is weaker evidence than a pass on a
  fresh hypothesis, and the sealed period is reserved (MANDATE §14).

## 4. Readiness

Ready to build, not to run. After the four pieces above and a clean suite,
Aarsh locks and runs it. Next session.
