# E2-D — readiness note (2026-09-26)

E2-D (`docs/strategies/E2-D.md`, DRAFT, with its 2026-09-25 amendments) makes
a name ineligible when promoters or insiders have been heavy net sellers.
**Both datasets are complete.** The build is small. **One line of §3 cannot
be computed as written**, and it is the insider limb's denominator.

**NOT READY TO LOCK** — §3 below needs Aarsh.

> **2026-09-27: superseded.** Aarsh split E2-D into E2-D1 and E2-D2 and
> made §2's three declarations. See `docs/notes/E2D1-readiness.md`. One
> correction to §3 below: the forced month-end exit does **not** need new
> code — `_decide` already exits a held name that has left the eligible
> set, which is how E2-A's exclusion worked too.

**Change-log entries that apply** (CLAUDE.md non-negotiable 1): the
2026-09-16 draft and the **2026-09-25 amendments** — promoter holding and
pledge 2010 onward; an undated quarter usable from the second month-end
after its quarter end; the PIT limb from 2016-01-01; rows S6, S7, S8.

## 1. The data is there

**Shareholding** (`data/bse_shareholding/summary.parquet`): 135,098 usable
scrip-quarters over 2,893 scrips; every one carries promoter percent and
pledged shares.

| year | scrips | all in panel | carry a filing date |
|---|---|---|---|
| 2010 | 1,851 | yes | **0%** |
| 2013 | 1,947 | yes | **0%** |
| 2015 | 2,023 | yes | 25.1% |
| 2016 | 2,036 | yes | **100%** |
| 2019 | 2,096 | yes | **100%** |
| 2021 | 2,140 | yes | **100%** |

Median promoter holding runs 54.1% (2010) to 58.8% (2021), which is the
right shape for Indian listed equity and is the sanity check that the
C1C2 parser fix held across the whole backfill.

The undated years are exactly what §4's amendment anticipated: 2010–2015
has no filing timestamp anywhere, so the charter's **second-month-end
convention** carries them. 53.9% of the 2010–2021 window is dated.

**Insider PIT** (`data/nse_insider/`): 262,283 rows over 1,726 symbols in
2016–2021, of which 261,075 carry a quantity and 260,335 a value. The limb
applies from 2016-01-01 per the amendment, and the data starts 2015-11-19,
so there is no gap at the boundary.

## 2. The line that cannot be computed as written

§3's insider limb: *"net insider transactions (PIT disclosures, sells minus
buys, by value / market cap) exceed 1.0% of market cap"*.

**There is no market-cap series in this project, and §2 of E1 is the reason
there is not.** E1 ranks by *traded value* precisely so that nothing needs
point-in-time shares outstanding, which the panel does not carry — the
sweeps already report `market_cap_proxy: unavailable` for that reason.

It is now *partly* computable, which is new since E2-D was drafted, and the
partly matters:

- **2016 onward**: `shares_outstanding_reported` from the shareholding
  table × the panel close. Sound, and available for the whole PIT window.
- **2010–2015**: only `shares_outstanding_derived` (promoter shares ÷
  promoter percent), whose error scales inversely with the promoter stake —
  a median 0.009% but up to 3.1% where the stake is small. The PIT limb
  does not apply to these years anyway, so this only matters if a future
  row extends it.

So the limb is computable **exactly where the charter applies it**. But
three things must be said in the charter rather than chosen in code:

1. **Which shares count** — total outstanding, or free float? The rule is
   about the market's absorption of insider selling, which argues for free
   float; the data has only total. Free float exists in no dataset here
   (the same finding that closed E1c §6).
2. **Market cap measured when** — at the month-end of the decision, or at
   the transaction date? A name that halved between them gives two very
   different ratios.
3. **Which shares-outstanding figure**, when both a reported and a derived
   one exist. They agree to a median 0.000% where they overlap, so this is
   a declaration rather than a difficulty — but it should be declared.

## 3. The rest of the engine's support

| E2-D line | supported? |
|---|---|
| §3 promoter holding fell > 1.0 pp over the trailing two reported quarters | **needs code** — a point-in-time promoter series keyed on `filing_date` (or §4's convention where undated), then a two-quarter difference |
| §3 net insider value ÷ market cap > 1.0% | **needs code and a charter decision** (§2 above) |
| §3 held names exit at the **next month-end**, not intra-month | **needs code** — the engine's month-end exits come from the band (rank past `band_exit_rank`); there is no "forced exit regardless of rank". E2-A needed the intra-month hook; E2-D needs the opposite and it does not exist |
| §4 bulk/block deals, stored and reported in §7 | **NOT collected** — no module, and §7 reports them |
| §5 window 2010–2016 / 2017–2021 | **yes** — but see §4 below |
| §6 S1–S5, plus S6/S7/S8 from the amendment | **yes**, once the rule exists |
| §7 forward return of excluded names | **yes** — the same machinery as E2-A's §8a |

### Four pieces to build

1. **`data/positioning.py`** — a point-in-time promoter series (holding,
   pledge, shares outstanding) keyed on the date it became usable, and a
   net-insider series from `nse_insider`, both as `usable_from`-style
   tables so nothing downstream reads a raw timestamp. Same shape as
   `red_flag_events`, which worked.
2. **A forced month-end exit** in the engine, distinct from the band.
3. **`classify_e2d`** — GATE against the stack, plus the mandate block.
4. **Bulk and block deals**, if §7's extra is to be reported at all. NSE
   publishes them daily; not started.

## 4. Two things the lock should settle beyond §2

**(a) The window straddles the PIT boundary.** §5 keeps development at
2010–2016 and validation at 2017–2021, while the amendment applies the PIT
limb only from 2016-01-01. So **development is almost entirely the promoter
limb alone** (2010–2015 undated and PIT-free, one year with both), and
validation has both throughout. The two periods are testing materially
different rules.

That is not necessarily wrong — S7 (2016 onward) and S8 (PIT only,
2016–2021) exist precisely to price it — but E2-A's experience is the
warning: its 2010–2016 development window turned out to have almost no
signal in it, and the readiness note caught that only by counting. Here the
count is above: 2010–2015 has full promoter data, so development is not
empty, it is *a different experiment* from validation.

**(b) §7's bulk-deal extra needs data nobody has collected.** Either drop
it from §7 or accept that it is reported as unavailable.

## 5. Readiness

**Not ready to lock**, and the blocker is §3's market-cap denominator
rather than any missing data. The shareholding and PIT backfills are
complete and clean. Once §2's three declarations are made, the build is
four small pieces — materially less than E3-R.
