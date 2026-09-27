# Portfolio system: audit and route forward

Reviewed 27 September 2026 against the uploaded `code.zip`.

## Decision

Keep the project definition. The goal remains a system that selects and manages Indian equity investments, uses company and world information, manages risk and tax, and earns the mandate's required after-tax advantage. A dashboard or an index-fund recommendation does not complete that goal.

The current evidence does not establish a trustworthy investment engine or the required edge. It also does not establish that the broader project is impossible. The measurement layer has reproducible defects, and the planned learned stock-selection system has not been built. Fixing the former is necessary; testing the latter is a distinct piece of work. Neither guarantees the target return.

## Scope and limits

I inspected the mandate, current state/handoff, relevant strategy charters and change logs, engine, tax lots, costs, provenance, execution stubs, tests, readiness notes, and saved E1 development/validation artifacts. I ran synthetic cases and the supplied test suite. I did not have the raw market database, independently validate its claimed completeness, rerun full historical experiments, or access the sealed period. No original source or charter was changed: 226 Python, TOML and Markdown files compared byte-for-byte with the archive were unchanged.

Archive SHA-256: `d4c3914f250d4a6aa6e788c3058cadf0c24cd52255394f5ded0303e8a3417482`.

The accounting reproducer demonstrates current behavior, not repaired behavior. Saved-artifact calculations reproduce reported arithmetic; they do not validate the trades underneath it.

## The objective and the size of the gap

`docs/MANDATE.md` requires, in development and validation, at least Nifty 500 (B2) +3 percentage points annually and Nifty 500 Momentum 50 (B5) +2 points, after tax and terminal liquidation. Drawdown must be no more than 5 points worse than B2. The stack also needs the required sweep robustness; a base row alone cannot pass the mandate.

Recalculation from the saved E1 regression equity files gives:

| Saved base result | 2007–2016 development | 2017–2021 validation |
|---|---:|---:|
| E1 after-tax CAGR | 8.97% | 27.36% |
| B2 after-tax CAGR | 8.07% | 14.79% |
| B5 after-tax CAGR | 13.74% | 22.48% |
| Required return: max(B2 +3, B5 +2) | 15.74% | 24.48% |
| E1 shortfall to required return | 6.78 pp | −2.88 pp |
| E1 maximum drawdown | 55.40% | 39.82% |
| B2 maximum drawdown | 63.49% | 37.93% |
| Mean daily E1 cash fraction | 27.18% | 19.58% |

These are provisional numbers from the existing, uncorrected simulator. The development return gap is substantial. The cash fraction warrants attribution, but does not prove that investing the cash would close the gap within the drawdown limit.

The return implementation already distinguishes unitized, time-weighted CAGR from investor XIRR. E1 XIRR recomputes to 10.47% and 31.37%, respectively. I did not find support for diagnosing the reported failure as a simple SIP-XIRR versus index-CAGR comparison error. The mandate already discloses B5's back-computed pre-launch history and its 0.30% expense assumption.

## Confirmed accounting defects

### 1. Corporate actions run after that day's trades

Location: `src/pflab/backtest/engine.py`, `run` and `_apply_ex_date_events`.

Month-start execution and intra-month exits precede split/bonus/dividend processing. The event then acts on post-trade holdings. In a synthetic flat-value, zero-cost case, the first purchase on a 2-for-1 split's ex-date buys 400 shares for ₹20,000 and receives another 400 shares. Account value becomes ₹40,000 without an economic gain. A first-time dividend ex-date buyer also receives ₹2,220 of an ineligible dividend in the separate case.

**Acceptance:** establish entitlements from eligible pre-event holdings; apply share transformations before ex-date executions; adjust pending quantities consistently; distinguish dividend receivables from spendable cash and payment dates. Test an existing holder, a first-time buyer, a seller, and a partial sale on the event date. Value and basis must reconcile through each event.

### 2. Non-trading positions become cash at an old price

Location: `engine.py`, suspension/delisting loop.

Under the default `last_close` branch, 250 missing market sessions trigger a sale and cash receipt at the last observed close even though the security still has no quote. A synthetic holding last quoted in February 2019 becomes ₹20,000 cash in January 2020 without returning to trading.

This contradicts the 17 September amendment in `docs/strategies/E1.md`: keep the mark during suspension, exit when trading resumes, and write the position to zero at the specified timeout. The ordinary missing-price execution path also skips the order without maintaining a daily retry, so the promised first-returning-session exit needs a focused check.

The saved base ledgers contain 13 `SELL_DELIST` entries in development and five in validation, with gross cash proceeds of ₹18,87,520.60 and ₹2,92,861.55. The combined ₹21.80 lakh is turnover across two separate simulations, **not** estimated profit inflation or an amount to subtract from terminal wealth. Security remaps, mergers, and actual recoveries must be resolved against the local data before calculating the performance impact.

**Acceptance:** no spendable proceeds without an executable quote or documented cash entitlement. Separate stale marking, zero valuation, actual recovery and legally recognized tax loss; a model write-down must not automatically imply a tax-deductible disposal. Preserve pending exits and test resumption. Reconcile all 18 saved cases.

### 3. Tax remains incomplete despite the previous summary

Locations: `engine.py` cash accrual and `_finalise`; `tax/india_lots.py`; `execution/costs.py`.

* Cash grows at 6% without entering an income-tax ledger. A cash-only two-year case earned ₹15,703.36 on ₹2,40,000 contributions and paid zero tax, including terminal tax. The model needs a specified instrument and explicit gross/net return and tax timing; a generic 6% rate is insufficient.
* `_finalise` calculates terminal tax only when stock positions remain. A book that has sold everything and realized ₹10,000 of short-term gains reports zero final tax, versus ₹2,080 under the project's own policy.
* A broad exception handler converts a terminal-tax computation failure into zero tax. The injected-failure case confirms this. Calculation failure must invalidate a result.
* Splits and bonuses share `adjust_shares`, which spreads basis and retains original dates. A bonus requires distinct lots: the Income Tax Department specifies the allotment date for its holding period and nil acquisition cost for post-2001 bonuses, subject to applicable grandfathering rules. The reproduced 2020 bonus instead becomes one enlarged old lot.
* Buy/sell cost totals include STT and enter capital-gain basis/proceeds without separation. STT reduces cash but is not deductible in computing capital gains under the cited tax provision.

The charter explicitly applies a modern tax policy across history; that declared counterfactual is not itself the defect. The omissions above exist within that policy too. This audit is not a certification that all other tax cases are correct.

**Acceptance:** test all-cash terminal books, outstanding current-FY liability, tax exceptions, cash income, split versus bonus lots, and cash-cost versus tax-deductible-cost reconciliation. Preserve the declared policy assumptions and record accounting corrections explicitly.

Official references checked during review:

* [Income Tax Department: Capital Gain](https://www.incometaxindia.gov.in/w/capital-gain), bonus holding period/cost, demerger basis allocation and transfer expenses.
* [Income Tax Department: Section 48](https://www.incometaxindia.gov.in/w/section-48-65), STT deduction prohibition.

### 4. Small-lot consolidation retains shares that should disappear

Location: `LotBook.adjust_shares`.

For lots of 1, 1 and 3 shares, a four-old-for-one-new consolidation leaves three shares. The theoretical entitlement is one whole share plus a quarter-share fraction. When an allocation rounds to zero, the code leaves the old lot quantity in place; the comment promising a basis transfer is not implemented.

**Acceptance:** reconcile whole shares, fractional claims and total basis across many-lot holdings. Do not liquidate an entire holding at a prior quote as a substitute for processing a fractional entitlement.

## Material model limitations and reproducibility gaps

**Demerger handling is an explicit shortcut, not complete event accounting.** `_apply_ex_date_events` can turn an adjusted-price gap into immediate cash and reduce basis by the price factor. The charter deliberately authorizes this shortcut. It does not track a resulting company's shares, listing delay or event-specific tax-basis allocation. Saved E1 records contain two such credits totaling ₹21,088.30 in development and 12 totaling ₹3,34,880.30 in validation. Each needs reconciliation before calling the data and lot accounting fully corrected for demergers. Replacing the shortcut requires a documented accounting amendment, not an undocumented strategy tweak.

**Run identity does not pin all effective inputs.** `backtest/runner.py::main` fingerprints the panel and configuration containing cost/tax file paths, but does not pass index series, action tables, membership, positioning/event data or external cost/tax file contents into that data fingerprint. Source identity does not substitute for external input identity. Some changes can therefore retain a run ID despite changing effective inputs. Hash all consumed, time-cutoff snapshots and resolved policy contents; distinguish an existing identical result from an attempted overwrite.

**The mandate's universe wording needs reconciliation.** It calls E1's universe “the whole Nifty 500”; E1 actually selects the 500 most liquid eligible NSE stocks. Those are not identical membership rules. Document which existing definition governs, without retrospectively selecting whichever performs better.

**E1c does not isolate a pure tax effect.** Its charter discloses unavailable free-float market-cap weights, substitute weighting, membership approximations, buy limits and incomplete weight rebalancing. Its gap to the index therefore cannot be attributed solely to a retail investor's tax and transaction costs. A claim that “tax keeps only half the fund return” needs a construction-matched control.

## Why the collected information has not yet delivered the intended system

The current adopted decision path is principally a momentum rank with execution and risk rules. `docs/strategies/E5.md` describes a learned cross-sectional ranker, but it remains a draft. Paper/Kite execution adapters are also stubs. The complete system in the original vision has not been tested end to end.

The readiness documents give concrete reasons why attaching more data has not automatically improved decisions:

| Input or module | What the archive actually establishes | Next useful question |
|---|---|---|
| News/fear rule E2-C | Zero incremental risk-off months beyond E1's trend rule in the examined periods | Does a predeclared news feature add information conditional on price/volatility, and change an eligible action? |
| Company flags E2-A | Recorded rejection, misclassification concerns and a reversal around the Covid recovery | Are event type, severity and publication time correct; does each event subtype predict a usable outcome? |
| Promoter positioning E2-D1 | Readiness note flags unexplained share-count contractions in 16% of flagged observations | Separate ownership changes from consolidation, dilution and other capital changes before interpreting sales |
| Insider positioning E2-D2 | 93% of reported sell value is promoter/group; 57% is not a market sale | Separate transaction modes and overlapping promoter signals before testing incremental information |
| Sector/factor constraints E2-B | Point-in-time mapping covers 52.8%/69.5% of held names; some relative-beta caps degenerate near zero | Define missing coverage and a meaningful cap before running an investment experiment |

The percentages above are reported in the supplied readiness/handoff documents; I could not independently rebuild them without the raw data. A redundant news rule is evidence about that rule, not proof that world affairs never contain useful information.

## Concrete next work, keeping the same definition

### Deliverable 1 — Close a bounded accounting repair list

Repair the confirmed event-order, suspension, tax and consolidation cases; resolve demerger accounting and input provenance. Produce an event ledger that reconciles shares, basis, receivables, cash and tax. Define completion by the acceptance cases above, not by improved investment returns or a larger generic test count.

Freeze the corrected code/environment/input identities. Retain old artifacts as historical records and mark affected results provisional. Recompute development/validation baselines and the impacted candidate comparisons from local data. Explain changes by event/accounting cause. Leave the sealed period closed.

### Deliverable 2 — Attribute the return gap before choosing another filter

Keep the current strategy intact and create labeled diagnostic controls that separately quantify selection, deployment/cash, portfolio weighting, transaction costs and tax. Use matching securities and timing wherever a causal comparison is claimed. Report terminal wealth and XIRR alongside the existing mandate CAGR/drawdown metrics.

The 27% development cash fraction is a useful lead, not a conclusion. Establish how much comes from the trend rule, the six-buy limit, rank eligibility and execution skips. Do not promote whichever diagnostic control wins after inspection; a candidate still needs its own charter and gate.

### Deliverable 3 — Make E5-A the next substantive stock-selection candidate

My recommended research priority is the existing E5-A proposal: test whether the information improves which stocks are held under fixed portfolio, liquidity, turnover, cost and tax rules. This is a proposed change in research order, not a change in project definition or an adopted strategy.

Start with a price/volume-only ranker as a control, then predeclare additions of verified issuer events and positioning. Compare each information family against the same control. Keep world data as precisely defined exposure/conditional features; treat “oil changed” plus “this issuer's measured exposure” as a hypothesis, not a trade instruction. An LLM may extract structured facts with source evidence and confidence; the tested model and fixed portfolio rules determine actions, consistent with the mandate.

Before locking E5-A, correct two draft-design issues:

1. A fixed 21-session purge is insufficient for overlapping 3- and 12-month forward-return labels. At every prediction time, training labels must have finished and become observable. Purging must use the actual label intervals. Validation labels must never enter fitting, feature selection or tuning for those predictions.
2. Hyperparameters selected on 2007–2012 cannot make that same interval an out-of-sample evaluation. State exactly which results are exploratory. For a full-period walk-forward claim, initial training/tuning needs genuinely earlier data; do not silently relabel an in-sample period to satisfy the mandate.

Many company/news features do not cover early development years. Store availability and publication time explicitly. A predeclared price-only fallback may be used until a feature has sufficient past observations, but its performance contribution and coverage must be reported separately. Backfilling future knowledge or treating missing records as a clean company would invalidate the comparison.

### Deliverable 4 — Integrate the approved stack into the daily product

After the evidence gates, connect portfolio lot import, reconciliation, a monthly proposed order list, tax/cost estimates, source-backed explanations, and paper execution. Risk gears such as E3-R remain separately measured components. A daily memo is useful operationally, but does not establish investment skill. Preserve the mandate's sealed evaluation and live-paper requirements; the available evidence does not justify real-money deployment today.

The next decision should therefore be based on three concrete outputs: corrected and reconciled measurement, attributed baseline underperformance, and a frozen E5-A experiment capable of testing incremental stock-selection information. No additional blanket backfill is justified merely because more data exists.

## Verification record

The supplied suite collected 599 tests in this environment: 591 passed, seven failed and one skipped. The failures were:

* Three engine golden-hash mismatches. Explicit Windows CSV line endings did not resolve them. Without the original baseline revision/environment I cannot attribute these to economic behavior versus numerical/environment differences; they need reconciliation, not blind snapshot updates.
* Three positioning failures parsing the year-2999 sentinel through pandas nanosecond timestamps.
* One mutually-exclusive-rule test reaching an unavailable private promoter-data file before the intended validation error.

Environment included Python 3.12.14, pandas 2.2.3, NumPy 2.3.5 and PyArrow 25.0.1. These failures do not explain away the independent accounting reproductions. Conversely, most tests passing does not establish economic correctness.

The accompanying bundle contains `verify_accounting.py`, its JSON output, `inspect_saved_results.py`, recalculated saved metrics and ledger entries, and a short README. Both scripts are read-only with respect to the project, require no network, and explicitly avoid sealed results.
