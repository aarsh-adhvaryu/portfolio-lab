# S79 item 12: the bear's warnings (pre-registered, written before any warning is scored)

**Claim.** When a local-model "bear" analyst, given only a block of code-made numbers, warns about a stock, the warning comes true more often than the
stock's own history makes that statement come true by chance.

**The statement (chosen from closed lists, written by code).** kind `underperform`: the stock's return from the last close before the warning to the close
H sessions later is below its benchmark's return over the same dates. kind `fall`: some close within the next H sessions is more than Y% below the
reference close. H in {5, 10, 20} sessions of the market's own calendar (`markets.get(m).session_after`); Y in {3, 5, 10}.

**Resolution (code, `agents/debate.py::resolve_open`).** Prices dated after the warning only. The close used is the one on the target session, or the last
before it within 4 days, and the data must reach the target. No close near the target 10 days after it: void, never guessed.

**Baseline.** For each warning, the share of the stock's own last 3 years of rolling windows (at least 250) in which the same statement came true.

**Rule.** Fewer than 20 resolved warnings (with a base rate): the count and no conclusion. From 20: z = (hits - sum of base rates) / sqrt(sum p(1-p)); a
conclusion only at |z| >= 1.96; the learner's bar for a new claim applies and rises with its counter. A pass would wire the bear's warning
weight into the agents; a fail leaves the debate as a reading aid with no weight.

**Not claimed.** That the disagreements help the reviewer decide; that the bull's arguments are scored (they are not).
