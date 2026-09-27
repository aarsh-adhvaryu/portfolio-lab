# Accounting correction 2 — which saved numbers move, and why

2026-09-27, session 2 of 4. Audit Deliverable 1 (`portfolio_system_audit.md`).
Applies with E1 §15, change-log entry **2026-09-27 "accounting corrections
a–d"** (and the declared choices recorded there: recovery sale, bonus =
ex-date, unnamed standard-ratio factor = split, fraction dated by completing
lot). Nothing below has been re-run; every figure in `docs/STATE.md` is
**provisional until re-run**. Evidence: `tools/audit/reconcile_events.py`
(read-only; saved E1 regression ledgers against local data).

## Decisions needed before the regression means anything

- **D1. ISIN handovers.** 455 times in the panel a security changes ISIN (a
  face-value split, usually) and trades on the next session under the new
  one. The engine treats the old ISIN as dead. 11 of the 18 saved
  SELL_DELIST rows are this. Under correction (b) those holdings are now
  **written to zero**, so a regression on today's code moves E1 *down* for a
  reason that is itself wrong. The same break drops the new ISIN out of the
  universe for ~250 sessions (`min_sessions`, 12-1 momentum restart), and
  split-heavy names are often winners. Proposed fix: re-key the old ISIN's
  rows to the successor with the split factor, the way `etf_events` already
  does for the ETFs. That changes the data, and possibly how E1 §3 reads.
- **D2. BE-series gaps read as corporate actions.** The panel is EQ-only.
  **6,841 of 8,903** PREVCLOSE factors (77%) are simply the last BE/BZ
  (trade-for-trade) close, not a corporate action. A fall during a BE stint
  becomes a cash credit, and a rise becomes a "consolidation" that shrinks
  the share count. Both corrupt `adj_close`, and so momentum. All 14 saved
  CASH_CREDITs are this (table below). Proposed fix: drop a PREVCLOSE factor
  whose adjusted prev close equals the security's last non-EQ close in the
  gap, and price held names from BE rows while they trade there.
- **Run order.** Either (i) run the regression now, to isolate a–d, then
  again after D1/D2, or (ii) decide D1/D2 first and run once. I recommend
  (ii). The a–d-only numbers carry a known, material downward bias from D1.

## Regression result (run 2026-09-27 at 19f1ea2, all 14 jobs; option (i))

Base row after-tax CAGR / max drawdown, old -> new:

| job | old | new | Δ CAGR |
|---|---|---|---:|
| E1 dev / val | 8.97 / 55.40, 27.36 / 39.82 | 2.87 / 55.58, 22.84 / 47.42 | −6.10, −4.52 |
| E1b dev / val | 9.74 / 54.96, 15.51 / 43.34 | 9.03 / 55.00, 15.22 / 43.53 | −0.71, −0.29 |
| E1-P dev / val | 9.14 / 55.78, 25.85 / 43.52 | 3.01 / 57.23, 21.43 / 51.25 | −6.13, −4.41 |
| E1c dev / val | 6.73 / 70.19, 20.10 / 36.33 | 6.19 / 70.38, 18.67 / 35.63 | −0.54, −1.43 |
| E1d dev / val | 11.55 / 49.54, 24.27 / 36.72 | 7.16 / 49.44, 21.59 / 38.41 | −4.39, −2.68 |
| E2-A dev / val | 11.85 / 33.18, 41.84 / 8.41 | 10.72 / 34.86, 39.31 / 10.19 | −1.13, −2.53 |
| E1 on E2-A windows | 14.60 / 31.37, 50.04 / 7.19 (STATE) | 9.39 / 37.07, 48.34 / 7.26 | −5.21, −1.70 |

**Not usable for verdicts.** The E1 dev drop is mostly D1:
13 holdings were written to zero (₹7.8 L at last quote), 8 of them ISIN
handovers (GRAVITA, AJANTPHARM, VIPIND, 20MICRONS, TITAN, GOENKA, TWL,
RAJTV). Terminal wealth fell ₹1.03 cr → ₹0.67 cr, because that capital
never compounded. Validation write-downs are similar: DIXON and VAIBHAVGBL
(splits), TATASTLBSL (merged into Tata Steel), and ADANITRANS and CGPOWER
(in BE at the period end, so D2). E1b and E1c move little because their
index-member universes hold fewer of these names. The a–d-only effect
therefore cannot yet be separated from D1/D2. Re-run after D1/D2
(`regress_bases.py --report` compares against the original dirs).

## Per defect: what moves in the saved results

| defect | status | saved numbers that move | direction / size (E1 base) |
|---|---|---|---|
| a. events before trades | fixed (session 1) | trades on an event date: 4 dev, 2 val of 1,277 | negligible for E1; larger for any row trading more names per month |
| b. stale-price exits | fixed (session 1) | all 18 SELL_DELIST (₹18.88 L dev, ₹2.93 L val gross) become write-downs | **down**, and wrongly so for 13 of 18 until D1 is decided (see f) |
| c. interest untaxed | fixed | every row holding cash; E1 gross interest ≈ ₹6.44 L dev, ₹0.75 L val, taxed at 30% | down ≈ ₹1.9 L dev, ₹0.2 L val before compounding |
| c. STT in basis | fixed | every realised gain rises by the STT paid | down, small (≈0.1% per side × tax rate) |
| c. terminal tax on an all-cash book; errors → zero tax | fixed | none: all 12 saved base rows end invested with non-zero terminal tax | no move in any saved base row |
| c. bonus lots | fixed | bonus shares now nil-cost, dated at allotment → more STCG | down, small; no bonus trade in E1's ledgers |
| d. consolidation fractions | fixed | fractions now settle in cash | negligible; no consolidation in E1's ledgers |
| e. demerger credits | **all 14 wrong** (D2) | ₹21,088 dev, ₹3,34,880 val credited as cash | **overstated**: val credits are 5.2% of terminal wealth; offsetting erased BE gains are not in the ledgers |
| f. SELL_DELIST | reconciled | 11 remap, 2 merger, 5 unresolved | see table |
| g. run identity | fixed | run ids only; no metric | every new run lands in a new directory |
| h. tests | fixed | none | golden re-pinned on a paise fixture, attribution re-proved |

## e. The 14 CASH_CREDITs: none is a demerger

Every one comes after the name left EQ for BE, 6 to 91 sessions. The credit
equals the last EQ close minus the last BE close, so it is price movement.
FRETAIL also had a scheme ex-date (2017-11-29), but NSE carried the
unadjusted close into BE that day, so its whole ₹39.20 is market movement too.

| period | date | name | BE sessions | credit ₹ |
|---|---|---|---:|---:|
| dev | 2012-06-15 | ATLASCYCLE | 53 | 20,398.80 |
| dev | 2014-08-06 | BEML | 26 | 689.50 |
| val | 2017-12-13 | FRETAIL | 10 | 1,685.60 |
| val | 2018-02-07 | TVSELECT | 59 | 8,835.95 |
| val | 2018-10-30 | IBVENTURES | 91 | 6,905.80 |
| val | 2018-10-30 | RAIN | 78 | 4,540.20 |
| val | 2020-12-21 | TANLA | 6 | 79,530.60 |
| val | 2021-09-13 | ADANIGREEN / ATGL / NEULANDLAB | 65 | 1,19,018.05 |
| val | 2021-09-27 | GPIL / TANLA / POONAWALLA | 68 / 7 / 7 | 66,784.90 |
| val | 2021-11-01 | ADANIPOWER | 6 | 47,579.20 |

The chartered shortcut is kept as it stands. It has not yet fired on a real
demerger in these ledgers.

## f. The 18 SELL_DELIST cases

| kind | cases | gross ₹ at stale price | what the local data shows |
|---|---|---:|---|
| **remap** (ISIN change, same symbol, next session) | dev: TITAN, VIPIND, GRAVITA, AJANTPHARM, GOENKA, 20MICRONS, RAJTV, TWL; val: JINDWORLD, PHILIPCARB, LAURUSLABS | 13,46,097 + 2,83,216 | successor ISIN trades from the next session; mostly FV splits in the NSE feed |
| **merger** (scheme) | val: UPERGANGES, OUDHSUG | 9,647 | NCLT scheme approved 2017-03 (BSE); AVADHSUGAR lists 2017-11-22 |
| **unresolved** | dev: TELEDATAIN, BANKRAJAS, UTVSOF, ALFALAVAL, MAHINDUGIN | 5,41,423 | no event in the NSE feed; BSE rows before about 2012 carry no company name to search |

None relisted under the held ISIN. For the five unresolved, recollection
suggests a merger (BANKRAJAS into ICICI Bank, 2010), delisting offers
(UTVSOF, ALFALAVAL, 2012) and a suspension (TELEDATAIN). **Unverified.**
These are genuine exits. The corrected write-down is right for them only if
no exit price was paid.

## g, h

- **g.** `runner.input_fingerprints` hashes, each cut at the period end: the
  period, the contents of the periods, cost and tax files, `e1.toml` (the
  stack companion), actions, membership, overlap membership, every index
  series, and (when enabled) red-flag events, shareholding, scrip map,
  insider PIT, symbol map and INDIA_VIX. The hashes enter `data_fingerprint`
  and are written to the manifest as `inputs`. Tests:
  `tests/test_run_identity.py` (post-end appends do not move the hash; edits
  and policy-file contents do).
- **h. Year-2999 sentinel:** `positioning._as_date` replaces the nanosecond
  `pd.to_datetime` calls. **Private file:** the engine now refuses two
  exclusion rules before reading any table. **Golden hashes:** the audit's
  three mismatches were numerical, not economic. The archive's golden passes
  here under pandas 3.0.5 and under the audit's pandas 2.2.3 / NumPy 2.3.5,
  and under hash seeds 0, 1 and 12345. A 1-ULP change to 30% of the
  fixture's prices changes the digest, and NumPy's SIMD `exp` differs in
  the last bit across CPUs. The fixture is now rounded to paise. Both digest
  sets were re-captured from their own code: current HEAD, and 8dea146 in a
  detached worktree. The corrected engine, with STT in basis and interest
  untaxed, reproduces 8dea146 exactly on all three paths. **Not verified on
  Linux.** Suite: 632 local; 631 + 1 skip under pandas 2.2.3 with no data
  directory.
