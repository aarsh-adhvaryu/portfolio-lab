# S85 migrate (G3): the remaining call sites on the one door

Branch `s85/migrate` (from `pm/s85-entrance`). 2026-11-13. Paid calls tonight: none (scripted fakes only; no cap-safe tiny real call was run, see "Not verified").

## What is built (one site at a time, tests green, one commit each)
1. `hq/converse.py`: the governed tool loop on `hq/llm.call` (`converse()`, `Conv`) had NO caller (the chat's loop is `entrance/intake.converse`, on the gateway). Deleted; the file keeps the helpers other modules use (`as_param`, `unnamed`, `_scrub_ids`, `_scrub_obj`, `KEEP_BLOCKS`). The chat has one loop.
2. `lab/strategist.py`: `gateway.call(role "decide", agent "strategist")`, tools, system block, the cost record (`spent` adds `cost_rupees`), the budget stop and the session row are as before. Same fake client; `test_s80_strategist`, `test_s83_strat`, `test_s83_tools`, `test_s84_desk`, `test_s82_fills` pass UNCHANGED. The engine in use answers (Opus on `claude`: role `decide`); the strategist no longer names its model in code (`[strategist] model` is still written to the session row).
3. `agents/analyst.py`: `ring` (urgent path), `web_search`, `trial_note`, `write_calculation` go through `analyst._door` -> `gateway.call` (new agent `analyst`). Kept exactly: the doorbell's own egress gate (`gate(req, pv)`, `blocked` outcome), `NotAdopted`, reuse of a fresh note (`recent_note`, `_fresh_on_subject`), `only_sourced_numbers`, `web_cited`, the dated note in the graph + memory (`keep_door` links it to the row), `NeedsApproval` / `BudgetRefused` (the door's governor ends in `analyst.check_budget`), the refusal outcome. `web=True` keeps the call on an engine that has a web tool (`claude`) by the door's rule. The overnight batch (`submit_batch`, `collect_batches`, the queued path of `ring` with its one `count_tokens`) stays on the client: the Message Batches API is not behind the door.
4. Also moved (clean moves): `hq/security.review` (agent `reading`, role `read`), `story/reader.cloud_fn_for` (agent `escalation`, role `quick`), `verify.live_model` (agent `reading`; a forced tool choice is refused by these models so the system text asks for the tool), `learner/claims.claude_draft` (agent `reader`), `learner/run.proposal_draft` (agent `worker`), `hq/models.claude_llm` / `claude_chat` (agent `wording` / `worker` / `router`), `hq/roster.word_facts` (agent `wording`).
- `gateway.prefer(con, model)` -> `(override, role)`: a caller that names a Claude model (the slider, the analyst's job) gets that model on an engine that prices it (role `quick`, smallest output floor), else the role of that tier answers (opus: decide, sonnet: read, other: quick).
- Governor: new agent and layer `analyst` (share 1.0 of the cap, Rs 2,500 a day, 500 passes a day, 2M input tokens a call): the analyst's paths were limited only by his cap before and still are. Gateway `AGENTS` now also `analyst, escalation, reader, wording, router, worker`.
- Gateway fix found on the way: a web call that pauses and resumes (`pause_turn`) counted the resumed turn's searches but did not bill them; now it does (`_continue_pause`). The old analyst path priced only the last turn of a paused search (it undercounted); through the door both turns are paid: `test_web_search_keeps_cited_figures...` now expects two calls' tokens and four searches.

## Tests
- New: `tests/test_s85_migrate.py` (the doorbell's row says agent/engine/role/purpose; the gate still stops before the door; his cap refuses through the door; trial note; web search bills every search; a web call on an engine without a web tool stays on `claude`; the model's refusal is an outcome; workshop calculation checks only its gate text; the weekly review; the slider road, the learner and the wording; `prefer`; GREP: no `import anthropic|openai` (any spelling, `src` and `tools`) outside `llm/vendors.py`, no client method called by the migrated modules, `llm.call(` left only in `hq/fetch.py`).
- Rewritten where they inspected the old road: `test_workshop` (the system arrives as a block list), `test_app_ai::test_web_search...` (cost of a resumed turn), `test_s79b_seats::test_analyst_ring_hook` (the teacher log is written by the door's road: source `hq`), `test_s67_local` live-model check (patches the gateway), `test_s61_slider` (patches the gateway).
- Failing before this branch and unchanged: `test_s85_chat::test_a_statement_is_refused_before_any_call_and_not_kept` (the merged branch's list in PLAN.md).

## OFF / left, and why
- `hq/fetch.py` (the brain's `fetch_cited` tool, `hq/tools.py`): uses Anthropic's server-side `web_fetch` tool, which the door does not offer (no engine but `claude` has it). It stays on `hq/llm.call` (still egress-gated, priced, governed, logged) and is the only `llm.call(` left outside `llm/` (grep test pins it). Moving it needs a `web_fetch` feature in the engine table first.
- The overnight batch (`analyst.submit_batch/collect_batches`, `cli.py` collect) and `analyst.ring`'s queued branch: Message Batches API.
- `hq/selfcheck.py` (one `count_tokens` ping) and `hq/service.client`/`llm.client` (the client maker, which already delegates to `llm/vendors.py`): no completion call.
- No retired module was deleted except `converse()` (above); the other retired v1 modules still have callers or tests.

## Decisions (2026-11-13)
- The strategist is role `decide` on the engine in use (Opus on `claude`); if he switches engine, it follows (the engine's exam and shadow record are the safety).
- Callers that name a Claude model ask for it by name only where the engine prices it; otherwise the tier's role answers. Their governor agents keep their old names and limits (`reader`, `wording`, `router`, `worker`, `escalation`); the analyst's paths get their own `analyst` agent with no limit beyond his cap.
- `analyst.ring` etc. pass `private_text=req.question` (the doorbell's gate already checked documents and question); `write_calculation` passes only its `gate_text` (its prompt carries code and made-up rows).

## Shared files touched
`lab/strategist.py`, `agents/analyst.py`, `llm/gateway.py` (AGENTS, `prefer`, `_continue_pause` billing), `hq/governor.py` (agent + layer `analyst`), `hq/converse.py`, `hq/security.py`, `hq/models.py`, `hq/roster.py`, `story/reader.py`, `verify.py`, `learner/claims.py`, `learner/run.py`. No migration. No `core/*`, `service/*`, `app/*`.

## Not verified
- No real call: the real Sonnet path through the strategist was not run (a session needs a store with a book card and costs well over Rs 3; the doorbell and the review calls need a key). Every site is tested with a scripted client on a scratch store.
- Full suite not run (brief): the touched modules' tests and the five engine-protected suites were not affected (no `core/*` engine file touched).

## Lines for PLAN.md / BUILT.md / CLAUDE.md (coordinator)
- BUILT: call sites on the door: chat (intake), strategist, checker, thinking loop and desk, analyst doorbell/web/trial/workshop (agent `analyst`), weekly code review, storyline escalation, learner, slider road, wording, verify ping. Left on `hq/llm.call`: the `fetch_cited` web_fetch tool only. `anthropic`/`openai` are imported only in `llm/vendors.py` (grep test in `test_s85_migrate.py`).
- A55 note: the analyst layer has no day limit beyond his cap (as before).

## Exposed for screens
Nothing new: usage by agent and engine is in `api_calls` (agents `analyst`, `reader`, `wording`, `router`, `worker`, `escalation`, `reading`) and read by `entrance/usage.py`.
