"""S84 gate (the one door for model calls, `llm/gateway.py`): version 210 (211-214 are spare).

210  api_calls gets the words the door adds to every call it makes: the ROLE (decide / read / quick), the ENGINE (anthropic), the THINKING level (low / medium / high / max), the cached input tokens
     (cache reads, beside the cost), the case a call was made for and its purpose. Nothing is rewritten: old rows keep NULL here. `cost_inr` stays the one cost column the governor counts.
"""
MIGRATIONS = [
    (210, "api_calls_gateway_s84", """
    ALTER TABLE api_calls ADD COLUMN IF NOT EXISTS role VARCHAR;
    ALTER TABLE api_calls ADD COLUMN IF NOT EXISTS engine VARCHAR;
    ALTER TABLE api_calls ADD COLUMN IF NOT EXISTS thinking VARCHAR;
    ALTER TABLE api_calls ADD COLUMN IF NOT EXISTS cached_tokens BIGINT;
    ALTER TABLE api_calls ADD COLUMN IF NOT EXISTS case_id BIGINT;
    ALTER TABLE api_calls ADD COLUMN IF NOT EXISTS purpose VARCHAR;
    """),
]
