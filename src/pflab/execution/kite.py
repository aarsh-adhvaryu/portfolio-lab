"""Kite Connect Personal adapter — Phase 4, only after ADVANCE.

Personal plan: orders, GTT, holdings, funds; no market data. Prices come
from the daily bhavcopy. Access token expires daily; the month-end job
needs a login step. Paper mode logs orders without placing them.
"""
from __future__ import annotations


class KiteAdapter:
    def __init__(self, api_key, access_token, paper=True):
        raise NotImplementedError("Phase 4 — see CLAUDE.md")
