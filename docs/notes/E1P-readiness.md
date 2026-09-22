# E1-P — readiness note (2026-09-19, updated at the lock)

**E1-P is LOCKED (2026-09-19) and the development sweep has been run.**
§3 carries a per-lot resolution and §10 carries the lock line; §3–§7 do not
change again.

---

## 1. The per-lot question — ANSWERED by the lock

§3 was written per-lot ("a band exit **for a held lot**… **the lot** is
between 9 and 12 months old") while E1 §4 sells a held name **in full**, and
the `defer_exit` hook returns one decision per position. A position built by
a monthly SIP holds several lots of different ages, so the two readings
disagree, and they disagreed in **opposite directions** in two different
rows of the same charter.

**§3 now says, in the charter:**

> Per-lot resolution: a position is deferred when its OLDEST lot falls in the
> 9-12 month window, because FIFO makes that the lot a sale would realise.
> §6 S4 tests the oldest lot's own unrealised gain, not the position average.
> §6 S5's minimum hold uses the YOUNGEST lot, since "every lot held at least
> N months" is exactly that condition. Partial-position exits are out of
> scope.

**What changed in the code because of it.** The base rule and S5 already
matched. **S4 did not**: it had been testing the position-average cost basis,
because the hook is handed lot *ages* and not per-lot costs. `EngineState`
now carries `lots`, and S4 tests the oldest lot's own `cost_per_share`.

That is not a cosmetic difference. A position average can show a gain while
the lot FIFO would actually sell sits at a loss — a later, cheaper top-up
drags the average down. On the average, S4 would defer; on the oldest lot it
sells, which is the short-term capital loss S4 exists to harvest.
`test_s4_tests_the_oldest_lot_not_the_position_average` pins exactly that
case, and its mirror image.

---

## 1b. The locked span, for future verification

E1 and E1b are checked each session by hashing their locked sections against
the commit they were locked at. E1-P now has the same anchor, recorded here
because the lock happened in a dirty tree and the hash is the only thing that
does not depend on a commit existing yet.

    E1-P §3–§7 at the 2026-09-19 LOCK
    chars   2255
    sha256  bbf90dc8a7b6ebdc6784f18fa9364e71565218f1867fa55d1c2782c643230143

Recompute with the same section-span extractor used for E1 and E1b (from the
`## 3.` heading up to, but not including, `## 8.`). A mismatch means §3–§7
moved after the lock, which the charter forbids.

---

## 2. What is built

All of HANDOFF §3's four "missing" items, plus the GATE wrapper.

**§3's rule** — `hooks.patience_defer(...)`, wired through
`hooks.from_config` under `[hooks.patience]`. Absent or `enabled = false`
leaves the inert `_never_defer` in place.

Two of §3's three conditions are free, and deliberately so: the engine calls
`defer_exit` **only** where the exit reason is `"band"`, and a name that
failed §2 exits with reason `"ineligible"` instead. So *"still eligible"*
holds by construction, and §3's *"delisting, suspension and red-flag exits
are never deferred"* holds because those exits never enter that loop at all —
by construction, not by care. `tests/test_e1p.py` asserts it with a defer
rule that says "always" and a name that stops trading.

**The age window is inclusive at both ends.** `is_long_term` is
`sell > buy + 12 months`, so a lot *exactly* 12 months old is still
short-term, and one more month of patience is precisely what turns it long.
An exclusive endpoint would have dropped the lots the rule exists for. Month
arithmetic uses `relativedelta`, the same calendar as `is_long_term`, so
"9–12 months" and "long-term" cannot disagree about what a month is.

**N1/N2** — `hooks.stop_loss(0.20)` and `hooks.profit_take(0.50)`, reached
through a new `intra_month_exit` call site in the daily loop and a new
`cost_basis` field on `EngineState` (per share, quantity-weighted across the
position's lots, because the trigger is a price move).

The call site sits **after** the month-start execution, for two reasons: the
hook's contract is that it decides "from data dated strictly before t", and
at that point `state` still carries session t−1's marks; and running after
the buy list means a name bought at today's open — whose cost basis *is*
today's open — cannot be sold by its own purchase. A test asserts no name is
both bought and control-sold on the same session, with the trigger set to
0.01%.

Control sales are written to the ledger as `SELL_INTRA` with a null
reference price, because there is no month-end reference to measure slippage
against.

**§6 S5 tests the opposite end of the book, and must.** S5 is "a minimum
hold of 6 months on **every** lot regardless of rank". Because §4 sells a
held name in full, the only way no lot is sold before the floor is to wait
until the **youngest** lot reaches it — the opposite end from §3's base rule,
which tests the oldest. It is the same cause as §1 above: whole-position
sales. The first implementation here reused the base rule's window over the
oldest lot, which would have sold a one-month-old lot the moment the oldest
passed six months — precisely what S5 forbids. S5 now takes its own
`min_hold_months` path, which bypasses the window and the rank ceiling
entirely ("pure patience, tax-blind"), and a test pins the decisive case of
an old lot and a young one held together.

**§6 rows S1–S5** — `sweep.e1p_rows()`. §4's N1/N2 live in a separate
`E1P_CONTROLS` table and are **not** part of the sweep unless asked for,
so GATE's G3 two-thirds count cannot include them. §4 says they are never
adoptable; a control that happened to score well must not push the
experiment through the gate.

**GATE wrapper** — `classify.classify_e1p`, GATE only. Unlike E1b and E1c,
E1-P is not a candidate base, so there is no C1–C4 half; E1-P §1 says
"judged by GATE.md" and that is the whole verdict. N1/N2 are stripped before
the arithmetic sees the rows and reported separately.

**§7's two missing extras** — `artifacts.deferred_lot_outcomes` (forward
3-month return of deferred lots against the lots the same month-end
band-sold, which is exactly what E1 would have sold) and
`artifacts.control_sell_outcomes` (N1/N2 sell counts, by year, and the
following 6-month return of those names). Both state their sign convention
in the payload. A name that stops trading inside the forward window is
dropped and counted, never imputed.

**Config** — `configs/e1p.toml`, E1's settings unchanged with
`[hooks.patience]` as the one difference.

---

## 3. Byte-identity, re-asserted

Every engine change here touches the shared loop, so E1 has to be proved
untouched. Two levels:

- **Synthetic** — `test_attaching_the_inert_hook_set_changes_nothing` now
  compares **decisions and taxes** as well as equity and trades, and asserts
  that nothing was deferred and no `SELL_INTRA` appears on the E1 path. A
  rule that changed only which names were chosen, while leaving the curve
  alike by luck, would previously have passed.
- **Real data** — E1 base was re-run on the development window under the
  changed engine and reproduced the stored sweep's CAGR, max drawdown and
  annual turnover exactly (see §5). E1 runs with every hook off, so that is
  the E1 code path on ten years of real prices, not a synthetic proxy.

  Note what this does *not* rest on: the two E1b sweeps re-run earlier the
  same day (`development-1996387124c166df`) were produced **before** these
  engine changes, under task 1's artifact changes only. They show that
  persisting curves and adding a manifest moved nothing — all fourteen rows
  to within 1e-12 — which is a different claim from the one in this section.

---

## 4. Readiness

**Ready to lock and run, once §1 is settled.** After the lock the sequence is
the ordinary one: development sweep, written review, validation sweep,
`classify_e1p`, verdict — against **STACK = E1 base**, which E1b's REJECT
left as the adopted stack.

Not started, and correctly so: no E1-P run of any kind, and no `[hooks]`
entry in `configs/e1.toml` or `configs/e1b.toml` was touched.
