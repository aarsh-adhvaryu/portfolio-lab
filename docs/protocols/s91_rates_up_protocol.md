# S91: "Rates up 1%" for the Lab (pre-registration)

Written 2026-11-15 (night) BEFORE the code that runs it (`lab/rates_study.py`) is written and before any run. The SHA-256 of this file (line ends normalised) is stored in the learner's
counter (`learn_tests`, origin `study`, note `s91:rates_up`) when the study is registered (`learner/s79.py register_all`, called at the app's start); `lab/rates_study.run` refuses to run if the file
changed since it was committed. An amendment is dated, re-registered and counts as a new test. ONE test is counted.

## 1. What is being asked, in plain words
When India's government borrowing rate rises by one percentage point, what does a diversified Indian stock book do in the same month? The Lab's "Rates up 1%" button needs one number for
that, with its uncertainty. It is a description of what history allows, never a forecast and never a trading signal; no decision reads it.

## 2. The rate, its unit and its shock
* **Rate:** India's 10-year government bond yield, monthly average, % a year: FRED series `INDIRLTLT01STM` (OECD, "Long-Term Government Bond Yields: 10-year, India"). It is the ONLY rate
  modelled. The US 10-year yield (`US10Y`) and the Fed funds rate are NOT used: they would answer a different question (a US rate move).
* **Shock:** +100 basis points = +1.00 percentage point, for example 6.78% becoming 7.78%. The model variable is `dy_t = y_t - y_{t-1}` in percentage points.
* **Availability:** the monthly average of month M is only known after month M ends and after OECD publishes it (a lag of weeks). The study is a description of history, so this is stated and
  not corrected; the live scenario is a what-if the investor asks for, and no job or decision reads the series.

## 3. Data and windows
* **Book:** the equal-weighted monthly return of the NIFTY 100 members on 2011-12-31 (`index_membership/NIFTY100.parquet`, point-in-time, `members_at`) that have an adjusted close on every month end
  of 2011-12 to 2021-12 (`panel/prices.parquet`, `adj_close`). Survivorship (members that kept trading) is stated, not corrected. Month return = last close of the month / last close of the previous month - 1.
* **Development:** returns of 2012-01 to 2017-12 (72 months). **Validation:** 2018-01 to 2021-12 (48 months), used ONCE. **2022-2025 is spent and is not touched.** The yield series starts 2011-12,
  so the first `dy` is 2012-01.

## 4. The model and its comparator
* **M1:** `r_t = a + b * dy_t + e_t` (ordinary least squares, heteroskedasticity-robust standard errors HC1), estimated on the development window only.
* **M0 (the simpler comparator):** `r_t = a0 + e_t`, the development mean.
* One specification only: contemporaneous, one factor, no lags, no market control. (A market control would answer "rates with the market held fixed", which is not the question.)

## 5. The rule (both must pass)
1. **Development:** `|t(b)| >= counter.t_needed(N)`, where N is the learner's test count after this registration (the bar rises with N; never under 2.0), and `b < 0` is NOT required (the sign is
   reported either way; the scenario applies the estimated `b` with its sign).
2. **Validation (once):** with `a`, `b` and `a0` fixed from development, the paired t of the 48 monthly differences `d_t = (r_t - a0)^2 - (r_t - a - b*dy_t)^2` (M0's squared error minus M1's) is
   `>= 1.65`, AND the sign of `b` estimated on the validation window alone equals the development sign.
* Also reported, not part of the rule: the out-of-sample R-squared `1 - SSE1/SSE0`, the 95% interval of `b`, the monthly standard deviation of `dy`, the coverage (names used of names in the index).

## 6. What a pass and a fail do
* **Pass:** the Lab's "Rates up 1%" preset is enabled. It runs the existing simulation (block bootstrap of the covered holdings' own history) and adds, to the first month's 21 sessions, a shift of
  `b / 21` a day, with `b` drawn for each path from a normal with the development mean and standard error (so the uncertainty shows in the fan). The screen says: "estimate from India 10-year
  yield changes 2012-2021, a description of the past; it explains R2 of monthly moves; it is not a forecast". The shift is applied to the covered value only, like the rest of the simulation.
* **Fail (either part):** the preset stays off. Its reason on the screen is the recorded result in plain words (what was tested, the validation t against 1.65, the sample size). The code that would
  apply the shift is not wired; the study record stays in `docs/STUDIES.md` and `docs/research/rates_study_results_s91.json`.
* An insufficient result (fewer than 60 development months of usable data, fewer than 40 names, or the series missing) is recorded as "not tested: <what is missing>" and counts as a fail for the
  button, not as evidence for or against.

## 7. Limits stated in advance
Monthly data, one rate, one book; the response of a single stock can differ widely from the equal-weighted book's; rate changes and equity returns share causes (growth, inflation, global
flows), so `b` is an association, not a causal effect of the rate; 72 development months give wide intervals. The scenario therefore carries its interval and its label. Nothing here changes the
investor's targets, limits or stock list.

```json
{"rate": "INDIRLTLT01STM", "shock_pp": 1.0, "development": ["2012-01", "2017-12"], "validation": ["2018-01", "2021-12"], "universe": "NIFTY100 members on 2011-12-31 with complete month ends",
 "model": "r = a + b*dy, OLS HC1", "comparator": "development mean", "dev_rule": "abs(t_b) >= counter.t_needed(N)", "val_rule": "paired t of squared-error differences >= 1.65 and same sign of b",
 "min_dev_months": 60, "min_names": 40, "wiring": "first-month shift b/21 per session, b ~ N(b, se^2) per path"}
```
