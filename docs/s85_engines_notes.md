# S85 engines (G1): any model behind the one door

Branch `s85/engines` (from `pm/s84-thinking`). 2026-11-13. Paid calls tonight: Rs 0.05 (the real path, below); everything else is a scripted fake.

## What is built
- `llm/gateway.py` generalised. Engines are `[engines.<name>]` tables in `configs/core.toml`: `provider` (`anthropic` | `openai_compat`), `vendor`, `base_url`, `key_name` (a field of the secrets file), roles `decide|read|quick` (model, thinking, min_tokens), `effort` map, `features`, `prices.<key>` (dollars per million tokens, `source`, `date`). `[engines] default / fallback / fail_streak (3) / fallback_minutes (30) / case_pin_minutes (30)`.
- Contract of the brief: `call(..., model=, thinking=, engine=, chat_id=, reply_msg_id=, documents=, images=, web=, his_order=, scope=)`; agents `think desk chat strategist checker reading` (governor: new agents `chat`, `reading` and layers `chat` 60%/Rs 400 a day, `reading` 40%/Rs 300; nothing loosened); `models_of(engine)` -> `[{key, model, price_in, price_out, tier}]`; `current_engine(con)`; `fallback_engine`; `engines_status(con)` (JSON-able); `roles(st, engine=)`; `spent(..., engine=)`; `set_client(fake, engine=None)` (one fake per engine for two-vendor tests).
- Result dict adds `provider, vendor, input_tokens, output_tokens, fallback_from, web_searches, text_blocks, chat_id` to the S84 keys. `engine` is now the ENGINE name (`claude`, `openai`); the old value `anthropic` is the provider.
- `llm/openai_compat.py`: the OpenAI wire format. `features.wire = "responses"` (OpenAI itself: gpt-6 models need it for tools) or `"chat"` (any vendor offering Chat Completions; `max_tokens_param` configurable). Canonical messages are Anthropic-style blocks, so a tool loop can move between engines. Degrades by rule: no document blocks -> pypdf text with `[page N]` (scanned page says so); no images -> dropped with a warning; no thinking control -> ignored with a warning; no token count -> labelled estimate (3 chars a token, priced at the worst case); no web tool -> that call stays on the fallback engine and says so in `note`.
- `llm/vendors.py`: the ONLY file importing `anthropic` or `openai` (test proves it over `src/`). `analyst.make_client` delegates (guard still first).
- `hq/llm.py`: `adapter=` hook (count/create/usage/refused per vendor); egress gate, price, governor, record unchanged for every vendor. `scrub()` masks key-shaped text and every secret value in error strings (api_calls.error, engine_events).
- `hq/governor.py`: `register_model()` puts a vendor's prices (and cached rate) in the governor; an engine whose role model has no price cannot be used.
- State (migration 290-294, `pm/mig_s79/m_engines85.py`): `engine_state_s85` (in use, previous), `engine_shadow_s85`, `engine_consent_s85` (vendor, scope exam|shadow|use, dated, wording), `engine_events_s85` (ok/failure per engine+role), `engine_problems_s85`, `engine_exam_s85`; `api_calls` gets `chat_id, reply_msg_id, vendor, fallback_from`.
- Consent: nothing is sent to a vendor without a recorded Yes for the scope (`use` covers `shadow` and `exam`); live calls need `use`; `scope="exam"|"shadow"` is passed by the exam and shadow runners. Seeded: Anthropic `use` (standing); **OpenAI `exam` and `shadow`, dated 2026-11-12 23:59, "his Yes of 2026-11-12 (S85 text)"; never `use`.** `use(con, name, yes=)` shows the one-line notice, needs the exam's form part passed (`record_exam`), keys/prices, and his Yes; going back to `claude` is always allowed. `shadow()`/`unshadow()`.
- Fallback: 3 failures in a row (error, timeout, malformed schema answer) on an engine+role send THAT call to `[engines] fallback` for 30 minutes (then it tries again; a success resets), a row in `engine_problems_s85` (`gateway.open_problems(con)`), one Telegram line a day (`outbox`, dedup `engine_fallback:<day>`). Exam and shadow calls (`scope=`) are never rerouted.
- Mid-case: a call with `case_id` uses the engine of the case's newest step if it is under 30 minutes old, so a case finishes its step where it began (steps already store the engine).
- CLI: `pflab engine list | test NAME [--thinking medium,high] | use NAME [--yes] | shadow NAME [--yes] | unshadow NAME`; `pflab setup secrets --only openai`; `pflab setup status` lists `openai.api_key` set/missing.
- Server (`app/server.py`): `GET /api/engines`, `POST /api/engines/use {name, yes}`, `POST /api/engines/shadow {name, yes, off}`, `POST /api/engines/key {vendor, value}` (answers only "stored"). Settings page (`static/redesign.js`): one list under the abilities with a Use button (confirm shows the notice). No restyle. Not run in a browser (no node here).
- Checker (`core/checker.py`) migrated to the door (role `quick`, agent `checker`).
- Tests `tests/test_s85_engines.py` (36). Changed existing assertions (engine name `claude` instead of `anthropic`; provider now `out["provider"]`): `tests/test_s84_gate.py` (5 lines), `tests/test_s84_case.py` (1 line).

## The OpenAI engine (read from OpenAI's own pages 2026-11-13)
`developers.openai.com/api/docs/models`, `/pricing`, `/models/gpt-6-luna|gpt-6.1-sol|gpt-6-astra`, `/guides/reasoning`, `/api/reference/resources/responses`. decide = `gpt-6.1-sol` ($2/$10; "near-Astra at lower cost"), read = `gpt-6.1-terra` ($1/$5), quick = `gpt-6-luna` ($0.10/$0.50); `gpt-6-astra` ($10/$50) is in the price table for the picker and exam. Decision: decide is Sol, not the flagship Astra (a fifth of the price; the exam can test Astra); change one line to flip. Responses API, `store=false`, `reasoning.effort` low/medium/high/max, structured output `text.format json_schema strict=false`. SDK `openai==3.40.0` (PyPI 2026-10-27), pinned in `pyproject.toml` and `requirements.lock`, installed in the workshop `.venv`.
Real path (key from the secrets file, never printed): one tiny call per role through the gateway with `scope="exam"` on a scratch store: quick, read, decide each returned the correct JSON, and a tool call came back as `tool_use`; total Rs 0.045. Exam/shadow of the engine itself is the `exam` agent's (`llm/exam.py` was absent: `pflab engine test` prints a one-line message until it merges; it calls `exam.run(con, name, thinking=[...], now=...)` and must write its form verdict with `gateway.record_exam(con, name, form_pass=, grade=, cost_rupees=, thinking=)`, which `use` reads).

## OFF / not done (listed, nothing half-migrated)
- Call sites NOT moved to the door (still on `hq/llm.call` / the analyst's own client; they work as before, on Anthropic): `lab/strategist.py` (stays Opus), `agents/analyst.py` (`ring`, `web_search`, `ask_deep`, `trial_note`, `write_calculation`, the overnight batch), `hq/converse.py` and the retired v1 HQ callers (`hq/models.py`, `roster.py`, `security.py`, `fetch.py`, `learner/*`, `story/reader.py`). Reason: the deadline; each needs its own fake-client tests rewritten. Rule 4 holds: `anthropic` is imported only in `llm/`. The door has what they need (`web=True`, `text_blocks` with citations, `web_searches`, `pause_turn` loop, cost of searches).
- Batch price and the vendor's web tool (OpenAI has one) are not wired; `features.batch/web_search` say so. Haiku 5.5 is priced and selectable per call (`model="haiku"`); no role uses it by default.
- Per-engine calibration tables/scorecards (T8) belong to the loop/exam: `engine` is stored on every call, case step and event, and `spent(engine=)` / `failure_streak` are per engine.
- Settings page JS was not run in a browser.

## Decisions (2026-11-13)
- Result `engine` is the engine's name; `provider` is the wire format (4 assertions in two S84 tests changed accordingly).
- Governor Sonnet cache-read share left at 0.2 of input (the claude-api reference now says $0.10): the safe side.
- Checker keeps its governor limit (1,500 output tokens), so it asks as role `quick` (min_tokens 1,500).
- A role whose model is unpriced blocks the engine; an Anthropic engine is not blocked for a missing key (the SDK resolves env/profile).

## Shared files touched
`hq/llm.py` (adapter hook, `scrub`), `hq/governor.py` (agents/layers `chat`, `reading`, `register_model`), `agents/analyst.py` (make_client delegates), `app/server.py` (4 routes), `app/static/redesign.js` (engine list), `cli.py`, `core/checker.py`, `pm/secrets_setup.py` (openai), `configs/core.toml` (`[engines]` rewritten), `pyproject.toml`, `requirements.lock`.

## How to add a vendor
OpenAI-format vendor: add `[engines.<name>]` (provider `openai_compat`, `base_url`, `key_name`, `features.wire = "chat"` if only Chat Completions, roles, `[...prices.<key>]` from its own price page with source+date), add the key field to `pm/secrets_setup.FIELDS`, then `pflab engine test <name>`, `pflab engine shadow <name>` (Yes), later `pflab engine use <name>`. Anthropic-format vendor: same with `provider = "anthropic"` and a `base_url` handled in `llm/vendors.py`. A new wire format: a class with the methods of `OpenAICompatEngine`, registered in `gateway.ENGINES`.

## Commands for him
`pflab engine list` · `pflab setup secrets --only openai` (key) · `pflab engine test openai --thinking medium,high` (when the exam is merged) · `pflab engine shadow openai` (his Yes is recorded for tonight) · `pflab engine use openai --yes` (shows the notice; only when he likes the evidence). Close the dashboard first for CLI work.

## Lines for CLAUDE.md / BUILT.md (coordinator)
Rule 4: `anthropic` and `openai` (pinned) are imported only in `llm/vendors.py`; every model call goes through `llm/gateway.py`. Rule 9: the app's models are whatever the engine in use names; default engine `claude` (quick/read/decide = Sonnet-low / Sonnet / Opus; chat Auto picks Haiku 5.5 by override); a change of engine is a measured decision by the exam and the shadow record; the two local models stay.

## Exposed for screens
`gateway.engines_status(con)`, `gateway.models_of(engine)`, `gateway.current_engine(con)`, `gateway.open_problems(con)`, `gateway.exam_state(con, name)`, routes `/api/engines*`.
