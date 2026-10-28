# S65 forward tests: protocol (registered 2026-10-28, before the first formation month-end, 2026-10-30)

**Why forward.** Every year from 2010 to 2025 has been looked at (2010-2017 development and 2018-2021 validation of the learner's tests; 2022-2025 spent by live
use). A new claim chosen after seeing those results cannot be tested on them again. The only data this system has not seen is what happens from now on, so these
claims are tested only on the live record, as months complete, by the system itself. They are slow by construction: a monthly signal gives twelve independent
observations a year. Nothing here is read early.

## The claims (four; all "earns less over the next month than the other Nifty 500 members")
| id | group (the rules and their definitions are those of `learner/templates.rule_frame`, unchanged) | origin | bar |
|---|---|---|---|
| F1 | below the 200-session average (`below_sma200`) | the one rule that PASSED (claim 21): a confirmation, a single pre-specified hypothesis | one-sided t <= -1.65 |
| F2 | month-end traded value over twice the prior 20 sessions' average (`volume_spike_2`) | the failed buy rule, reversed (claim 22 went the other way in both periods): a lead | one-sided t <= -2.13 and the sign in both halves |
| F3 | within 5% of the 250-session low (`near_52w_low_5`) | claim 20 reversed: a lead | one-sided t <= -2.13 and the sign in both halves |
| F4 | 40% or more below the highest close since 2008-06 (`ath_fall_40`) | claim 23 reversed: a lead | one-sided t <= -2.13 and the sign in both halves |
F2-F4 are three new hypotheses drawn from one family of results, so their bar is Bonferroni over three at one-sided 5% (z = 2.13). F1 is one hypothesis fixed before
the new data. The four count in the learner's counter at registration (N goes from 33 to 37; the bar for any new discovery claim rises accordingly).

## Design
- **Formation.** On the last session of each calendar month from 2026-10-30 on, using only sessions up to that day: the universe is the Nifty 500 members of that day
  (point-in-time membership) with at least 200 of the last 252 sessions priced and a price that day; the group is the members for which the rule is true. A month is used
  only if the group has at least 10 names and the universe at least 50. The group and the universe are stored when formed (`forward_months`), before the outcome month exists.
- **No late formation.** A month whose outcome month-end is already in the data when the system gets to form it (a missed run) is marked `late` and is not used.
- **Outcome.** The total return (adjusted close with dividends, the panel's `tr`) of each name from the formation session to the next month-end session; a name that stops
  trading keeps its last value. The month's excess = the group's equal-weight mean minus the universe's equal-weight mean. No charges: avoiding a name is not a trade.
- **Decision, once.** At the first month-end with at least **24** settled valid months (no earlier look; counts only are shown before): the mean excess and its Newey-West
  (1 lag) t. A claim passes if t <= its bar (negative: the group earned less) and, for F2-F4, the mean excess is negative in both the first 12 and the last 12 months.
  A claim not passing is closed: no live feature, "tried forward, did not hold". A pass is wired as a `learned` finding (avoid rule) beside claim 21; an F1 pass is
  recorded as "confirmed forward". F1 not passing at 24 months does not by itself remove the live avoid finding (its power at 24 months is low): it is shown with
  "not confirmed forward after 24 months" and re-decided by the learner's own counter rule (amendment 4).
- **What cannot be concluded.** A pass describes 24 or more months of the live market, not the future. No result may be reported before the decision month.

## Code (committed with this protocol): `src/pflab/learner/forward.py`; table `forward_months` (schema v39); run by the learner's nightly cycle.
