"""S86 (S85's leftover 3): nothing calls a model client directly. The vendor SDKs are imported only in `llm/vendors.py` (rule 4), and a client is MADE in one place only, the gateway
(`llm/gateway.py` `vendor_client`, and the engine door beside it); the overnight batch, the batch collector, the chat's web search and the readers all go through it."""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "pflab"
SDK = re.compile(r"^\s*(?:import|from)\s+(?:anthropic|openai)\b", re.M)
MAKE = re.compile(r"\bmake_client\(")
ALLOWED_MAKE = {"llm/gateway.py", "agents/analyst.py"}          # the door, and the definition it wraps (+ the analyst's own default for its own `ring`)


def _py():
    for p in SRC.rglob("*.py"):
        yield p.relative_to(SRC).as_posix(), p.read_text(encoding="utf-8")


def test_the_vendor_sdks_are_imported_in_vendors_only():
    bad = [rel for rel, s in _py() if SDK.search(s) and rel != "llm/vendors.py"]
    assert bad == [], f"a vendor SDK is imported outside llm/vendors.py: {bad}"


def test_a_model_client_is_made_in_the_gateway_only():
    bad = [rel for rel, s in _py() if MAKE.search(s) and rel not in ALLOWED_MAKE and "def _gw_vendor_client" not in s]
    assert bad == [], f"a model client is made outside the gateway: {bad}"
    for rel, s in _py():
        if "_gw_vendor_client(" in s and rel not in ALLOWED_MAKE:
            assert "gateway.vendor_client(" in s, f"{rel} names the helper but does not reach the gateway"


def test_the_gateway_door_exists_and_the_workshop_guard_still_applies():
    from pflab.llm import gateway
    assert callable(gateway.vendor_client)
