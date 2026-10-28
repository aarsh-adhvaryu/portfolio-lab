# S65 forward test F5: the stress-gauge futures hedge, on paper (registered 2026-10-28, before the first forward session, 2026-10-29)

**Origin.** The investor's research project Q_Alpha_Research found one positive result: keep the shares (no capital-gains tax) and, while a cross-asset
stress gauge stays high, hold a short index-futures position of half the book; on the index it cut the 2008 and COVID drawdowns with little return given up
(its own pre-registered bar, 1997-2026). That history includes the years this system treats as spent (2022-2025) and was never tested here, so it is
**not** evidence here. The gauge is **coincident**: it rises during a crash, not before. F5 tests the rule only forward, on paper, from 2026-10-29. Nothing
is traded; F&O trading stays a no (the investor's frame); a hedge would be proposed for his yes only after a pass.

## The rule (fixed now)
- **Gauge (the STRESS composite).** On each Nifty 50 session, the mean of the available causal percentile ranks (trailing 1,000 sessions, at least 252)
  of: US VIX; MOVE; India VIX; credit stress (minus the drawdown of HYG/LQD from its 252-session high); USD-INR's 21-session change; the dollar index's
  21-session change; Nifty 50's drawdown from its 252-session high; the 63-session correlation of Nifty 50 and S&P 500 daily returns. **US-market series
  are lagged one session** (a value dated d is used from the first Nifty session after d), because the US closes after India.
- **State.** The hedge is on after the gauge holds >= 0.70 for 5 consecutive sessions, and off on the first session it is below 0.70.
- **Paper position.** Decided after the close of the gauge's session, entered at the close of the next session: the first return it earns is the one
  after that (two sessions after the gauge's day). Book: Nifty 50 TRI. Hedge: short Nifty futures of 0.5 x the book's value; its daily return is
  -0.5 x Nifty 50's price return (basis and carry are not modelled). Costs: 0.03% of notional at each entry and exit, 0.05% at each month-end roll;
  tax: 30% of each episode's net hedge gain (F&O is business income).
- **Kept daily:** the gauge, the state, the hedged and unhedged equity from 2026-10-29.

## Decision, once
At the first month-end with **both** at least 24 months since 2026-10-29 **and** at least 2 completed hedge episodes (if the second never comes within 60
months, F5 closes as "not enough stress to judge", no pass). **Pass** if the hedged book's worst drawdown over the forward period is at least 5 points
shallower than the unhedged book's **and** its annualised return is no more than 1.0 point a year lower. A pass becomes a `learned` finding (described,
with its n of episodes); the system may then propose a hedge plan for the investor's yes. A fail: no live feature, "tried forward, did not hold".
Before the decision only the gauge and the paper state are shown, labelled "information: a forward paper test, not a recommendation".
F5 counts in the learner's counter at registration.

## Code (committed with this protocol): `src/pflab/quant/stress_hedge.py`, run in the learner's nightly forward step.
