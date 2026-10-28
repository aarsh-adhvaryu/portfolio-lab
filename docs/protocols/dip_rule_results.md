# Dip-buy rule study: results (S34)

Run 2026-10-15 with `tools/dip_rule_study.py`, exactly as registered in `dip_rule_protocol.md` (commit c3cf0a2,
pushed before the run). No amendment. Universe: Nifty 500 members on each month-end; 114,730 stock-months.
Figures are medians and rates over events; R12x = 12-month total return minus the Nifty 500 TRI's.

## Baseline (an ordinary month-end buy of a Nifty 500 stock)
| period | events | median R12x | ruin (24m) | knife (6m) |
|---|---|---|---|---|
| development 2008-14 | 39,521 | -3.9% | 9.8% | 37.2% |
| validation 2015-19 | 29,022 | -9.3% | 11.8% | 38.2% |
| 2020-26 (not evidence) | 32,241 | -2.3% | 2.4% | 23.4% |

The median single stock trails the index (a few big winners carry the index), as in the stocks-vs-index study.

## Safety filters on ordinary buys (no dip trigger)
| filter | dev ruin | dev knife | dev median | val ruin | val knife | val median |
|---|---|---|---|---|---|---|
| none | 9.8% | 37.2% | -3.9% | 11.8% | 38.2% | -9.3% |
| Fsafe (all four) | 7.0% | 28.4% | -3.4% | 8.6% | 34.6% | -6.6% |

Fsafe = trailing profit > 0, profit not below half of a year earlier, interest cover >= 2 (or no debt cost),
not more than 50% below the 1-year high. It cuts ruin by about a quarter to a third and does not cost return.

## Dip triggers (selected rows; full table in the tool's output)
| rule | dev n | dev median | dev ruin | dev knife | val n | val median | val ruin | val knife | pass |
|---|---|---|---|---|---|---|---|---|---|
| stock 10% below 1y high, Fsafe | 717 | -2.4% | 7.4% | 25.5% | 1,013 | -5.0% | 7.1% | 25.3% | yes |
| stock 10% below 1y high, F2 | 804 | -3.1% | 7.8% | 27.9% | 1,085 | -5.9% | 7.1% | 25.8% | yes |
| stock 20% below 1y high, none | 1,646 | -9.0% | 14.6% | 43.6% | 1,358 | -10.2% | 13.4% | 33.2% | no |
| stock 30% below 1y high, none | 1,419 | -11.3% | 16.3% | 54.5% | 1,004 | -13.7% | 16.5% | 42.5% | no |
| stock falls 20% more than market (63d), none | 1,888 | -7.7% | 14.7% | 47.6% | 1,187 | -16.7% | 20.0% | 49.6% | no |
| **market 10% below 1y high, Fsafe** | 649 | -2.4% | **5.1%** | **12.8%** | 877 | -8.2% | 9.5% | 26.1% | **yes, chosen** |

Chosen by the registered rule (lowest development ruin among passing rules): **buy extra only when the whole
market (Nifty 500 TRI) is at least 10% below its 1-year high, and only stocks that pass Fsafe.** Median R12x
difference to baseline, 95% bootstrap interval: development -5.7 to +23.1 points (not distinguishable from
zero), validation +0.7 to +4.0 points. In 2020-26 (not evidence) its median was -5.8% against the baseline's
-2.3%, ruin 2.5% against 2.4%.

## Reading
1. **The filters are the protection, not the dip.** A company's own deep fall (20%+ below its high, or falling far
   more than the market) had MORE later ruin and more further falls: buying those is the falling-knife case.
2. **Market-wide dips are the safer dips**: everything is cheaper, not just one troubled company. With the
   filters, that rule had the lowest ruin and knife rates of all.
3. **The return gain from dip buying is small and uncertain**; the extra quarter-tranche is about buying more at
   lower prices with less risk, not about beating the market.
4. Nothing gives certainty: even the chosen rule had about 5-10% ruin and 13-26% knife rates per event, which is
   why buys are spread over 15-20 names and why the live surveillance guards are added on top.

## Addendum 2026-10-16: re-run with amendment 1 (F3 not applied to financials)
Run with `tools/dip_rule_study.py --financials pit` as registered in the protocol (commit a6296e6, before the
run). Same panel (114,730 stock-months) and baseline as above. 14.0% of stock-months are financial by their
point-in-time NSE label (15.4% if later labels are allowed). The numbers above are kept as the first run.

| rule | dev n | dev median | dev ruin | dev knife | val n | val median | val ruin | val knife | pass |
|---|---|---|---|---|---|---|---|---|---|
| Fsafe on ordinary buys (no trigger) | 15,239 | -4.1% | 6.8% | 29.1% | 19,369 | -7.1% | 8.8% | 35.1% | (not a rule) |
| stock 10% below 1y high, Fsafe | 762 | -3.1% | 7.2% | 26.9% | 1,066 | -5.8% | 7.1% | 25.6% | yes |
| stock 10% below 1y high, F2 | 804 | -3.1% | 7.8% | 27.9% | 1,085 | -5.9% | 7.1% | 25.8% | yes |
| **market 10% below 1y high, Fsafe** | 690 | -3.8% | **4.8%** | **12.8%** | 913 | -7.8% | 9.9% | 25.6% | **yes, chosen** |

**The chosen rule is unchanged:** extra buys only on a market-wide 10% dip, only into stocks passing Fsafe (now
with F3 skipped for financials, as the live guard already does). Median R12x difference to baseline, 95%
bootstrap interval: development -6.3 to +21.3 points, validation +2.2 to +3.7 points. 2020-26 (not evidence):
median -4.8%, ruin 2.5%, knife 17.9%.

**What changed, and a caution.** Letting financials through F3 adds about 40 development events, and they
lower the rule's development median from -2.4% to -3.8%, now only 0.1 points above the baseline's -3.9%.
In the sensitivity run (later labels allowed, 9 more financial events) that median drops to -4.7%, the rule
fails the return test, and the registered selection would instead pick "stock 10% below its 1-year high,
Fsafe" (which passes in both runs). Reading: the **safety** result is robust: ruin and knife rates are
well below baseline in every variant. The **return** edge of the market-dip rule over ordinary buying is
not: it rests on a margin smaller than the noise. The extra quarter-tranche remains a way to buy more at
lower prices with less risk, not a way to beat the market.
