# Market state: Hawkes chance vs plain volatility (S51): results (2026-10-20)

Run as registered in `market_state_vol_protocol.md` (commit e43ef97, before any number on these indices).

## The registered test: ten foreign indices, validation 2015-2019 (AUC for "a -2% fall within 10 sessions")
| index | EWMA | Hawkes (own 2005-14 fit) | d |
|---|---|---|---|
| US S&P 500 | 0.647 | 0.640 | +0.007 |
| UK FTSE 100 | 0.615 | 0.580 | +0.035 |
| DE DAX | 0.736 | 0.722 | +0.013 |
| JP Nikkei 225 | 0.684 | 0.696 | -0.011 |
| HK Hang Seng | 0.678 | 0.612 | +0.066 |
| KR KOSPI | 0.548 | 0.524 | +0.024 |
| TW TAIEX | 0.648 | 0.649 | -0.001 |
| AU ASX 200 | 0.695 | 0.683 | +0.012 |
| CN Shanghai | 0.818 | 0.753 | +0.065 |
| BR Bovespa | 0.648 | 0.603 | +0.045 |

Pooled mean d +0.025, block-bootstrap p 0.011; EWMA better in 8 of 10. **Plain volatility WINS the registered rule.**

## Calibration for the Nifty (2005-2014, `configs/market_state.toml`, written by `--calibrate`)
Chance = 1/(1+exp(-(11.584 + 1.376 ln EWMA))); T1 0.37 (90% recall of 2005-14 follow-on falls), T2 0.80.

| | follow-on falls warned: volatility chance | Hawkes chance (amendment 2) |
|---|---|---|
| 2005-14 (T1 chosen here) | 90% of 124 | 90% of 124 |
| 2015-19 | 43% of 7 | 57% of 7 |
| 2020-26 | **68% of 28** | **82% of 28** |

## Conflict found before wiring (not anticipated by the protocol)
The registered test measures ranking of all fall windows (AUC), where volatility is better. The market state's own
purpose (amendment 1, the investor: miss no clustering episode) and its drift check measure recall of follow-on falls at T1,
where Hawkes is better since 2020 (82% vs 68%); the volatility chance would fail the drift check's 80% floor at once.
**Not wired: the decision is the investor's** (keep Hawkes as the state and show the volatility chance beside it; switch as
registered; or keep Hawkes alone). The live market state is unchanged meanwhile.
