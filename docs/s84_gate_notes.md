# S84 gate notes: the one door for model calls (`src/pflab/llm/gateway.py`)

Branch `s84/gate` (based on `pm/s84-thinking`, e2551bc). 2026-11-12. No paid call was made (real path: none); every model in a test is a scripted fake.

## What is built
- `llm/gateway.py`: `call(con, role, system, messages, *, tools, case_id, purpose, now, max_tokens, schema, ...)`, `roles()`, `settings()`, `resolve()`, `set_client(fake)` / `client_override`, `refusal_reason(e)`, `refusals()`, `spent(con, since, agent=, case_id=, purpose=)`, `ENGINES`, `AnthropicEngine`.
- The call is the OLD road, unchanged: it ends in `hq/llm.call` (egress gate on the first user message and on the whole body, price by `count_tokens` and the worst-case output, `governor.check`, the send with the server-side fallback, the real cost with cache reads and writes priced, the teacher log). The workshop guard (`guard.require("paid")`) fires inside `analyst.make_client`, which the door calls only when no client was passed or injected (an injected client is a test double). Nothing is sent before the egress gate, the price and the governor passed.
- Roles and thinking: `[engines.claude.decide|read|quick]` in `configs/core.toml` (model, thinking level, `min_tokens`). decide = claude-opus-5-5 / high, read = claude-sonnet-5-5 / medium, quick = claude-sonnet-5-5 / low. One scale low / medium / high / max, mapped by `[engines.claude.effort]` to the vendor word.
- Vendor mapping (SDK 1.15.0; checked against the claude-api reference, not guessed): `thinking: {"type": "adaptive"}` plus `output_config: {"effort": <word>}`. Opus 5.5 and Sonnet 5.5 reject a fixed thinking budget (HTTP 400) and a forced `tool_choice` (any / a named tool); the door sends neither and refuses a forced `tool_choice` up front (only None / "auto" / "none"). Effort words accepted by these models: low, medium, high, xhigh, max; the scale has no `xhigh` (the table is data, so it can be set).
- Caching: the system text (a string becomes one block), the last tool and the whole conversation (top-level `cache_control`) are marked, at most 4 markers in a request (a caller's own marker, such as on a book card, counts). Cache reads come back as `cached_tokens` and are written to `api_calls.cached_tokens`; the cost already prices them (`governor.cost_inr`). `[engines.claude] cache = false` turns it off.
- Result: `{"text", "json", "json_error", "tool_calls" [{id,name,input}], "assistant_content", "cost_rupees", "cached_tokens", "cache_written_tokens", "engine", "model", "thinking", "requested_model", "role", "role_used", "stop_reason", "truncated", "call_id", "warnings", "note"}`. `thinking` is the LEVEL (a word); `model` is the model the vendor says served it (a fallback shows). `assistant_content` is what a caller appends as the assistant turn of its tool loop. `json` is parsed only when a `schema` was passed (sent as `output_config.format` json_schema); an unparsable answer gives `{}` and a `json_error`, never an exception.
- Migration 210 (`pm/mig_s79/m_gate84.py`): `api_calls` gets `role, engine, thinking, cached_tokens, case_id, purpose` (ADD COLUMN IF NOT EXISTS, old rows NULL). Written after every call.
- Governor (shared file `hq/governor.py`, 7 lines): new agents `think` and `desk` (layer `thinking`: day Rs 400, 60% of the monthly cap; passes a day 60 economy / 200 normal / 0 off; 120,000 in / 20,000 out per call) so the strategist's own 2-a-day and layer figures are untouched.
- Tests `tests/test_s84_gate.py` (28): roles map to models and levels; the toml equals the code defaults; fallback to the next role up with a note; level off the scale refused; adaptive thinking + effort, never a budget or forced tool; `max_tokens` floor per role; cost, cached tokens, engine, model and level returned and logged; schema parse and bad-JSON handling; tool calls pass through; a tool loop is one governor pass; a fake injectable by argument or `set_client`; model refusal raises; caching marks and the 4-marker limit, caller lists untouched, off switch; workshop without `--paid` refused before anything is sent; egress gate refuses (account-like digits, his name, system text naming him) with the fake never called; governor refuses at the cap (priced, never sent, `over_limit` logged, `resume_at` in the reason) and at a spent month, brain setting off, an input over the limit; unknown agent refused; no client call anywhere in `think/` or in the door except through `hq/llm.call`; a second engine can be registered behind the same door; migration columns exist.
  Also ran green: `test_s68_policy`, `test_s60_brain`, `test_s84_cases` (see the report for the wider set).

## Decisions (dated 2026-11-12)
- The contract's `thinking` return value is the level word, not the vendor's thinking text (the display is "omitted" by default on these models anyway; nothing reads reasoning text).
- Agent names for the governor are `think` (cases) and `desk` (the daily desk): the `agent` argument of `call`; default `think`. A name outside them is refused up front. `agent="desk"` is what the desk agent must pass; the desk's daily budget reads `gateway.spent(con, day_start, agent="desk")`.
- `max_tokens` is raised to the role's `min_tokens` (decide 8000, read 4000, quick 1500): thinking counts as output and 1,500 would cut an Opus decision off mid-thought. The worst case is priced and governed at the raised figure.
- `private_text` (what the egress gate reads) defaults to the FIRST user message (the strategist's rule: the book card). A caller whose first message is public text passes `private_text=""`. `body_check` (his name, long ids) always reads the whole request.
- The brain setting is the `mode` argument (default "normal", as the strategist); "off" refuses like every other paid call.
- A role switched off (`enabled = false`) or without a model falls back to the next role up (quick -> read -> decide) with a note in the result; nothing above it left means `ValueError`.
- Failures are not swallowed: the caller catches `Exception`, keeps its case open and uses `refusal_reason(e)` for the stored reason (None means an ordinary error).
- The test that no code under `think/` calls a client directly is in my test file and will also guard the other agents' modules once merged (it scans `src/pflab/think/*.py` for `messages.create`, `import anthropic`, `make_client`, `beta.messages`, `llm.call(`). Callers must use `gateway.call`.

## What is OFF and why
Nothing is switched off: the door has no caller yet (the coordinator and S85 migrate the existing call sites; I did not touch them). Other roles of the code base (the strategist, the analyst, the checker) still use `hq/llm.call` directly.

## How S85 adds a vendor
1. Write a class like `AnthropicEngine` with `name`, `effort(level, st)`, `params(spec, st, system, messages, tools, max_tokens, schema, tool_choice)`, `make_client()`, `send(con, *, agent, params, client, now, mode, private_text, gate, topic, question, cfg, approved, turn)` returning an object with `.message`, `.call_id`, `.cost_inr`, `.warnings` (use the same egress, price, governor and `api_calls` record as `hq/llm.call`), and `read(sent)` returning the dict `AnthropicEngine.read` returns.
2. `gateway.ENGINES["<name>"] = Engine()`.
3. In `configs/core.toml` give the roles of that vendor `engine = "<name>"` (and its effort map). `call` and every caller stay as they are: they store `engine`, `model` and `thinking` off the result.
4. Price the vendor's models in `hq/governor.PRICES` (a model not there is priced as Opus, the safe side).

## Shared files touched
`configs/core.toml` (appended `[engines]` tables at the end), `src/pflab/hq/governor.py` (layer `thinking`, agents `think` and `desk`). New: `llm/gateway.py`, `pm/mig_s79/m_gate84.py`, `tests/test_s84_gate.py`, this file.

## Exposed for screens
- `gateway.roles()` -> `{role: {role, role_used, engine, model, thinking, min_tokens, note}}` (JSON-able; Settings or a status line can show which model and level each role runs).
- `gateway.spent(con, since, agent=, case_id=, purpose=)` -> rupees (the desk budget, a case's cost).
- Cost per call and its cached tokens are on `api_calls` (`cost_inr`, `cached_tokens`, `role`, `engine`, `thinking`, `case_id`, `purpose`); `governor.spend` and `policy_view` list the new `think` / `desk` agents and the `thinking` layer on their own.

## Could not verify
- A real call (none made, by the brief): the exact vendor behaviour of `output_config.format` together with adaptive thinking and top-level `cache_control` on Sonnet 5.5 is as documented and as the strategist and `security.py` already send it; the first real call is the S84 real path of the coordinator.
- Haiku has no server-side fallback: `hq/llm.call` already sends it plainly; no role uses it tonight.
