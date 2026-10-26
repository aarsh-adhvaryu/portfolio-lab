# S64 price ranges: calibration results (run 2026-10-26)

Run as registered in `s64_ranges_protocol.md` (commit 8327c89, before any run) with `pflab forecast test`: monthly
origins, 100 sampled point-in-time Nifty 500 members each, 3,000 paths, horizons 21 and 63 sessions. N = 23 tests in the
family when it ran (development bar t >= 2.85).

| period, horizon | stats_plain covered (80% target) | stats_ewma covered | pinball plain / ewma | DM t (ewma better) |
|---|---|---|---|---|
| development 21 | 83.0% (n 9,600) | 74.9% | 0.02909 / 0.02907 | +0.12 |
| development 63 | 81.5% | 72.8% | 0.05620 / 0.05652 | -0.55 |
| validation 21 | 77.4% (n 4,800) | 75.2% | 0.03170 / 0.03230 | -4.24 |
| validation 63 | 75.9% | 73.3% | 0.05720 / 0.05840 | -2.81 |

**Decision (the registered rule):** `stats_plain` passes coverage in all four cells (75.9% to 83.0%, inside 75-85%);
`stats_ewma` does not (72.8% to 75.2%) and is worse by pinball in validation. The EWMA scaling does not replace the plain
bootstrap. **`stats_plain` serves**, labelled "calibrated: the 80% range covered 75%-85% in testing (2010-2021)".
The 252-session range is served and scored live but was not tested (the protocol says why). Result file:
`PFLAB_DATA_DIR\research\s64_ranges.json`. Reading: validation coverage is at the low edge (a range a little too narrow in
2018-2021), so the live rolling coverage is shown beside every range.
