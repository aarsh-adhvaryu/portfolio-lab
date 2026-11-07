# S79b pre-registration: market waves, rotation, sentiment and the value area (items 15, 15b, 7b)

Registered 2026-11-08 ~00:40 IST, BEFORE any run of the studies below. Code: `src/pflab/quant/index_event_study.py` (written after this file is committed), event
lists from `quant/waves.py` (`wave_events`, `rotation_events`, `crude_fall_events`), `sentiment/` (`extreme_sentiment_events`) and `quant/volume_profile.py`
(`value_area_events`). Each question below is one test in the learner's counter (the bar `t_needed(N)` rises with N); N is read from the counter when the study runs.

## What is claimed, and what would show it
After a **wave flag**, a **rotation flag**, a **large one-day crude fall**, or an **extreme sentiment reading**, the index (IN: Nifty 500 TRI; US: S&P 500) behaves
differently over the next 5 and 20 sessions than after all other days. After a **close outside the value area**, price returns to value more often than after other
days within 1 and 5 sessions; after **POC migration**, the next 5-session direction follows the migration.

Tests (11 in all): {wave, rotation, crude fall, extreme sentiment} x {5, 20 sessions} = 8; value-area exit: return-to-value rate at 1 and 5 sessions = 2; POC
migration: 5-session direction = 1.

## Data, period and rules
- Point in time: an event date is decided from rows dated <= that date; the forward return starts at the next session's close-to-close. Horizons are sessions on the market
  calendar (`pflab.markets`).
- Period: 2004-01-01 to 2021-12-31 only. 2022-2025 is spent and is never used as out-of-sample evidence. Events from 2026 onward are a live forward test, not part of this run.
- Event definitions use thresholds computed from the history BEFORE each date (expanding percentile of the series; no look-ahead tuning). Flag definitions are those in the
  code at the commit that precedes the run; they are not changed after seeing results (a change is a new, later test).
- Crude: a one-day Brent fall in the worst 2% of days (expanding). Sentiment: the combined price-based score (India VIX / US VIX, put-call ratio, breadth, flows,
  open interest where they exist) beyond the 5th or 95th expanding percentile. Model-read news tone is forward-only and is NOT used in this historical run.
- Value area / POC: minute-bar history is short (it exists only from the Kite backfill); where minute bars do not exist the DAILY approximation is used and labelled. The
  value-area and POC tests state n and the date range wherever the history is shorter than the period. A test with fewer than 20 non-overlapping events reports "n too small,
  no conclusion".
- Series with history shorter than the period (flows, India VIX, option data) are used only from their first date; the n and range are printed with every result.

## Method
- Events within h sessions of an earlier event of the same kind are dropped (non-overlapping). The baseline is the forward h-session return after all other days of the
  same period (excluding the event windows).
- Statistic: mean forward return after events minus the baseline mean (and the median, and the hit rate of a positive return). Inference: moving-block bootstrap
  of the baseline (block = h sessions, 10,000 draws, fixed seed 20261108) for the difference in means; also reported: n events, effect, 95% interval, and the
  same-sign check in the two halves of the sample (split at the median event date).
- Value-area: the share of events whose close is back inside the previous value area within 1 / 5 sessions against the same share for all days with a close inside
  the value area's range extended by the same distance (matched on distance outside); POC migration: the sign agreement between the migration direction and the next
  5-session return, against 50% with a binomial test.

## Pass rule (the gate)
A test passes only if ALL hold: n >= 20 non-overlapping events; the bootstrap p-value (one-sided in the claimed direction) clears the counter's bar, i.e.
t_needed(N) at the current N; the effect has the same sign in both halves; and the effect is at least 0.5% (index return) after a cost of 0.2% for acting on it.
Otherwise the result is reported as **"no reliable follow-through"**.

## What a pass allows, and what a fail means
- A pass lets the paper team read that flag as information in its dossier (labelled: "followed through in N events, 2004-2021, effect X%, interval Y"). Nothing
  trades on a flag by itself.
- Each flag/state is also a forecaster lens (`lens_wave`, `lens_sentiment`, `lens_value_area`) in SHADOW mode: scored live and weighted by the ensemble, excluded
  from the combined forecast until it is admitted by its live score (>= 60 live sessions of the market and a live pinball loss that beats the combined forecast
  without it). A failed study does not stop the lens running in shadow; it only means the paper team gets no "followed through" label.
- Results are recorded in `docs/STUDIES.md` and in the learner counter (`origin = study`, template `wave_sentiment_s79:<test>`).

## Honest limits stated in advance
Waves and rotations are rare; with 2004-2021 and the non-overlap rule, several tests may have fewer than 20 events and will say so. The sentiment parts available for
that period are price-based only. An effect found here is a description of history, not a forecast.

## Amendment 1 (2026-11-08 ~00:50, before any study run): the flag definitions as implemented
Written from the code of `quant/waves.py` and `quant/macro_attr.py` (agent W), which was finished before any returns were looked at. The cut-offs were chosen for rarity, not tuned on returns.
- **Wave:** advancing share in the top or bottom 2.5% of earlier sessions; spread around the common move at or below the median; the market part larger than the own part for at least the
  80th-percentile share (and over half) of the 500 most-traded names. Thresholds are percentiles of the sessions BEFORE the day; from 2022 on they stay frozen at the 2004-2021 sample.
- **Rotation:** a 3-session foreign-selling streak followed by a flow at or above the 95th percentile of its z-score (or the mirror image), with India at the 80th (or 20th) percentile of the gap to
  the Asian average. The event is dated when the flow is reported (`known_on`). 2004-2021 gives only 4 such events: the study will state "n too small, no conclusion".
- **Crude fall:** a one-day Brent fall at or below the 2nd percentile of earlier one-day moves (69 events 2004-2021 before the non-overlap rule).
- **Macro attribution:** ridge regression (constant 0.02) over the 250 sessions before the day; unexplained = move minus the parts. Fixed constants, not tuned.
- Event counts before the non-overlap rule, 2004-2021: waves 111 (59 up), rotations 4, crude falls 69.

## Amendment 2 (2026-11-08 ~01:25, before the sentiment and value-area studies run): their definitions as implemented
Written from the code of `sentiment/compute.py` (agent T) and `quant/volume_profile.py` (agent V), finished before any returns were looked at.
- **Extreme sentiment:** the price-based combined score only (India VIX / US VIX, put-call ratio, breadth, FII/DII flows, open interest where they exist; news tone is forward-only and excluded). An event is a day
  whose score is beyond the expanding 5th (fear) or 95th (greed) percentile of EARLIER days, with at least 120 earlier days. First-of-cluster events are the ones kept by the non-overlap rule. 2008-2021 gives
  319 events for India (149 fear, 170 greed) before that rule.
- **Value area / POC (daily approximation, labelled):** with no minute-bar history for 2004-2021, the profile is a rolling 20-session composite of daily bars (each day's traded value spread over its high-low range), bin
  edges anchored so a past profile never changes. "Outside" = the close beyond the PRIOR day's frozen value area; "back in" = a later close inside that same area; "POC migration" = the sign of the change of the composite POC
  versus the previous session. `back_in_1`, `back_in_5` are measured from the event close; the migration test uses the 5-session return starting at the next session's close. Where minute bars exist (the Kite backfill, 2015
  onward for the names covered) they are NOT used in this run, to keep one definition; the minute-bar profile is a forward-only refinement.
- The matched baseline for the value-area test is the same share for all days whose close lies the same distance (in percent) outside a frozen value area, as written above; for POC migration the baseline is 50% with a binomial test.
