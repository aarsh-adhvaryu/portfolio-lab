# S83 item L1/L5: the picks sleeve is judged LIVE, and its share follows its record (pre-registration)

Written 2026-11-11 (night) BEFORE the first pick is made and before the code that uses it is committed (`core/pick_share.py`, `core/picks.py`). The SHA-256 of this file (line ends
normalised) is stored in the learner's counter (`learn_tests`, origin `study`, notes `s83:picks_live:IN` and `s83:picks_live:US`) when the study is registered
(`learner/s83.register_picks_live`, called when the app starts). An amendment is dated, re-registered, and counts as new tests. Two tests are counted: one per market.

## 1. Claims

**A (India).** The `longterm` sleeve of the system's book (his Kite stocks plus the stocks the system picks itself) beats the Nifty 500, after estimated tax and charges, measured live.
**B (US).** The picks part of the US sub-book (the stocks the system picks beside SPY) beats SPY in rupees, after estimated tax and charges, measured live.
Each claim is one test in the learner's counter. Nothing in this study says the claim is true: the sleeve's share of the book is a risk control that follows the record (section 4), and
the claim becomes a verdict only under section 6.

## 2. What "beats the index" means

* The sleeve's value path is the marked value of its positions (India: every `longterm` holding, the system's picks and his Kite stocks; US: the system's US picks) plus the cash
  its sales produced, after the estimated tax and charges of the paper book (the book's own FIFO tax and charges; sales taxed as they happen, unsold gains taxed as if liquidated at the
  mark, labelled estimates). The index path is the Nifty 500 total-return series held through the Nifty 500 ETF (India) and SPY converted to rupees at the stated FX source (US),
  over the same sessions, with the ETF's own charge on the way in and the same estimated tax on its gain.
* Window: the last 120 sessions of record, or all of them when there are fewer. "Ahead" means the sleeve's return after tax minus the index's return, in percentage points a year
  (`points_a_year`, from `core/pick_score.sleeve_record`, the one place that measures it), is above zero. "Behind" means it is below minus 2.0 points a year. Between the two the record
  is "level".
* History cannot judge a model's picks: a pick made with today's knowledge cannot be replayed without hindsight, and single US stocks carry survivorship bias. So there is no replay and
  no backtest of picks anywhere in this study; the record starts with the first pick and only live sessions count. 2022-2025 is spent and plays no part.

## 3. When it is judged

* The first judgment is made at the first close when the market has 60 sessions of record AND at least one pick of the system has been bought (otherwise the sleeve would be
  judging his Kite stocks alone). After that, every 60 further sessions of record. A close with fewer sessions says "not enough record" and changes nothing.
* A judgment is made by code at the close, by the rule of section 4, and stored as one dated row (`sleeve_share_s83`) with the figures it used, whether the share moved or not.

## 4. What happens to the share (the rule, in code: `core/pick_share.py`)

```json rule
{
  "IN": {"start_share": 0.40, "min_share": 0.20, "max_share": 0.60, "step": 0.05, "of": "the India part of the book (the rupee book)", "against": "Nifty 500 total return, through the Nifty 500 ETF"},
  "US": {"start_share": 0.50, "min_share": 0.30, "max_share": 0.70, "step": 0.05, "of": "the US sub-book", "against": "SPY in rupees", "spy_floor": 0.30},
  "judge_every_sessions": 60,
  "min_sessions_of_record": 60,
  "window_sessions": 120,
  "behind_points_a_year": 2.0,
  "ahead": "share + step (at most max_share)",
  "behind": "share - step (at least min_share)",
  "level": "share unchanged",
  "min_system_picks_bought": 1
}
```

* Ahead: the share rises one step (5 points), up to its maximum. Behind by more than 2 points a year: it falls one step, down to its minimum. Otherwise it stays.
* A shrink never forces a sale. It means: no new picks are accepted until the next judgment, and the money from sales (stops, thesis breaks, withdrawn picks) goes to the core, not to
  other picks. A pick is sold only for its own reasons (a stop, a thesis break, the strategist withdrawing it, a rail), weighed against the 12-month tax guard.
* The US picks share and SPY: SPY is always at least 30% of the sub-book (the picks' maximum share, 70%, leaves it that). A stock is at most 10% of the sub-book and there are at most 12.
* The picks sleeve is OUTSIDE the lab's A50 gate (history cannot judge it); the gate still applies to the core's split and to every coded policy. The index fallback leaves the picks alone.

## 5. Minimum records and how figures are shown

* A count of fewer than 20 scored picks is shown as a count, never as a rate or a hit percentage.
* The share rule needs no minimum number of scored picks (it is a risk control over the sleeve's whole record), only the sessions of section 3.
* Every figure is read from code (`core/pick_score.sleeve_record`); no model writes a number.

## 6. When a verdict is claimed (rule 10)

* Not before 250 sessions of record AND 20 scored picks in the market. Then: the picks' monthly excess return over the index (after tax) against zero, a paired t, compared with the
  learner's bar for N tests (`counter.t_needed(N)`, N counted after this registration). A pass wires nothing new (the picks are already live); it licenses saying "the picks have an
  edge". A fail means the share sits at its minimum by the rule above and the strategist is told so in its card.

## 7. The rule is code

`core/pick_share.py` carries the numbers of section 4 as `RULE`. `tests/test_s83_picks.py` reads the JSON block above and compares it with `RULE` and with the defaults in
`configs/core.toml`. Changing a number here or there without the other fails the test; changing it after registration needs a dated amendment and a re-registration.
