# S64 PEG and the multibagger claim: result (run 2026-10-27, protocol `s64_peg_protocol.md`, committed before the code)

Claim: a stock bought at a PEG below 1 becomes a multibagger (3x total return within 5 years).
Universe: Nifty 500 members of each month end 2010-01 to 2016-12 (84 months, all kept), delisted names included, a defined
PEG from point-in-time filed EPS. Group A: PEG below 1 (about 113 names a month); group B: all others with a defined PEG
(about 70 names a month).

| formation year | A reached 3x | B reached 3x |
|---|---|---|
| 2010 | 20.5% | 19.1% |
| 2011 | 26.6% | 22.0% |
| 2012 | 39.4% | 27.6% |
| 2013 | 38.1% | 24.9% |
| 2014 | 18.9% | 16.2% |
| 2015 | 7.8% | 10.7% |
| 2016 | 18.6% | 18.4% |
| pooled | **24.3%** | **19.8%** |

**Result: FAIL.** A beat B in 6 of 7 years (needs 5, met); the pooled ratio was 1.22 (needs 1.5, not met); the 5th percentile of
the ratio over resampled years was 1.06 (needs above 1, met). One of three conditions missed.

## What it means
- PEG below 1 was a mild advantage, not a multibagger rule: about 1 in 4 of those names tripled in five years, against
  1 in 5 of the rest. That is 22% more likely, not 50% or more, and in 2015 it went the other way.
- The more striking number is the base rate: about **one Nifty 500 stock in five tripled within five years** from a start in
  2010-2016, whatever its PEG. That was a strong period for Indian mid and small caps (the windows ran to 2021). Any
  "multibagger" screen has to be read against that, not against zero.
- Seven starting years, windows overlapping inside each year: weak power. "Not supported on this data" is the honest reading,
  not "PEG is useless". A PEG below 1 stays context in the brain's view, labelled tested: failed, with that caveat.
- The tests run now number 33 in the counter (the next bar: development t >= 2.97).
