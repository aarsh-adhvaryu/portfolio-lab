# SESSION TEMPLATE — standard workflow for every build session

1. **Read** `CLAUDE.md`, `docs/HANDOFF.md` "Start here", and the session's
   entry in `docs/PLAN.md` §9. Do not re-read a file already read.
2. **Check inputs.** List what the investor owes for this session (statements, keys,
   decisions). If something is missing, stop and ask; do not fabricate data.
3. **Branch** `pm/sN-<slug>` from `master`. Never touch `research-archive`
   except by file copy listed in `docs/MIGRATED.md`.
4. **Tests first** for every number: tax, returns, cost, risk, probability.
   Synthetic fixtures; real data only for reconciliation.
5. **Build** the session's files. Prefer maintained libraries over new code;
   pin and record any new dependency in CLAUDE.md. Kept engine modules change
   only with a justifying test.
6. **Test.** `pytest -q` fully green; engine tests unchanged.
7. **Reconcile** if the session touches the ledger: compare with the real
   statements; breaks are zero or explained in `recon_breaks`.
8. **Check the rules** (PLAN §1): no LLM-made number, tax rows sourced and
   dated, estimates labelled, no trading path.
9. **Update** `docs/STATE.md` and `docs/HANDOFF.md` "Start here" (done, next,
   what the investor must run or provide). Jobs over ~5 minutes are the investor's: give
   the exact PowerShell command.
10. **Commit** (10 lines or fewer), push, merge the branch to `master`.
11. **Report** to the investor in 15 lines or fewer: done, tests, breaks, decisions
    needed, what he provides next. **STOP.**
