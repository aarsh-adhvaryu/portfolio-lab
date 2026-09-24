# E1d — E1 with the fund's volatility-scaled momentum score

Status: **LOCKED** 2026-09-24 (see §10). Changes go only through §10. Judged by `GATE.md`
against STACK = E1 base, reported against E1 §13 C1–C4 (candidate base)
and against MANDATE §3 and §5.

## 1. Purpose
E1c's S6 found, in both periods, that E1's raw 12-1 momentum earns about
5 pp a year less than the fund's volatility-scaled 6+12 score, on the
fund's framework, while selecting 76–77% of the same names. It is the
first signal finding in this project that held in both periods. E1d tests
whether it holds in E1's own framework, where E1's other choices (monthly
band, equal weights, the whole-500 universe) stay as they are.

## 2. Hypothesis
Ranking by momentum measured relative to each stock's own volatility,
over 6 and 12 months, picks better names than raw 12-month return. On
E1's framework this raises after-tax CAGR in both periods without
deepening the worst fall.

## 3. The one change
E1 §3's signal is replaced by E1c §3's score: 6- and 12-month price
returns, each skipping the most recent month, each divided by the name's
daily-return volatility over the same window, averaged, then **z-scored
and clipped at ±3 within the eligible universe at the decision date** —
not across the whole panel (E1c's code fix of 2026-09-21, which changed no
charter text). The score is used for **ranking only**.

**E1c's weighting amendments of 2026-09-21 do not apply here.** Those
three entries — weights proportional to max(score, 0) capped at 5%, S6's
raw momentum, S4's weights through the band — are about how E1c turns a
score into a position size. E1d is **equal weight**, so it has no weighting
to amend; the only 2026-09-21 change that reaches E1d is the
standardisation fix above. Everything else is E1 as locked, including:
universe (top 500 by traded value, MANDATE §4), N = 25, exit band 50,
monthly decisions, equal-weight shortfall buys (E1 §5, with the
2026-09-21 buy-sizing correction), SMA-10 trend filter, costs, tax,
suspension and delisting rules.

## 4. Window and benchmarks
E1's: development 2007–2016, validation 2017–2021. Sealed untouched.
Benchmarks B1–B5.

## 5. Sweep
| row | change |
|---|---|
| S1 | 6-month component only |
| S2 | 12-month component only |
| S3 | N = 20 / band 40 |
| S4 | N = 35 / band 70 |
| S5 | costs ×2 |
| S6 | trend filter off |
| S7 | trend filter, sell-to-cash |
| S8 | NSE's order (z-score each window, then average) |
| S9 | delisting = total loss |
| S10 | universe = Nifty 200 point-in-time (E1b's), to show whether the gain depends on the universe |
| S11 | universe = Nifty 200 **published-only**, development 2012–2016, with E1 base re-run on that window as its stack. S10's development years 2007–2011 use a declared proxy (CNX 100 ∪ CNX Midcap), because Nifty 200 membership is published and exact only from 2012-01-01; S11 is the same question asked where the membership is not reconstructed |

## 6. Verdict
- ADOPT / REJECT / INCONCLUSIVE per `GATE.md` against E1 base.
- C1–C4 per E1 §13, both periods, reported.
- MANDATE block: §3 (worst fall within 5 pp of the Nifty 500 fund, return
  at least 3 pp/yr above it) and §5 (at least 2 pp/yr above B5), both
  periods, reported.

## 7. What a pass would and would not mean
This hypothesis was suggested by E1c's rows, run on the same development
and validation years it is now tested on. Those years are no longer
unseen for this question, so a pass here is weaker evidence than a pass
on a fresh hypothesis. The only clean test left is the sealed period,
which MANDATE §14 reserves for a stack that meets §3 and §5. A pass is
read with that in mind, and the verdict note says so.

## 8. Reported extras
Selection overlap with E1 base at each month-end; turnover and
short-term share of gains; tax drag; equity-versus-cash decomposition;
median turnover rank and names held by year; ADV skips.

## 9. Not claimed
No new data and no new information: the same prices, measured
differently. Not a forecast.

## 10. Change log
- 2026-09-21 — draft, written after E1c's verdict from its S6 finding.
- 2026-09-24 — §3: "as amended 2026-09-21" replaced by the substance it
  referred to. That phrase pointed at four E1c change-log entries of that
  date, three of them about weighting, and E1d's single change should not
  depend on a reader picking the right one. §3 now states the
  standardisation directly (within the eligible universe at the decision
  date, clipped at ±3) and records that E1c's weighting amendments do not
  reach E1d, which is equal weight. No rule changed; the engine already
  did exactly this. Requested by Aarsh.
- 2026-09-24 — §5: **S11 added** — Nifty 200 published-only, development
  2012–2016, E1 base re-run on that window. S10 asks whether the gain
  depends on the universe, but five of its ten development years run on a
  declared proxy rather than the index, and E1b measured a 2.14 pp
  development spread from inclusion-date timing alone — four times GATE's
  G1 threshold. S11 asks the same question where membership is published.
  Same mechanism as E1b's S13 and E1c's S11. Requested by Aarsh.
- 2026-09-24 — **LOCKED. No changes to §3–§7 after this line.**
