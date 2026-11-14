"""S86b C5: links printed inside a file are followed (free) and said plainly; spreadsheets and PDFs end as read-with-a-fact or the TRUE reason; synthetic fixtures only."""
from __future__ import annotations

import hashlib
import io

import pytest

from pflab.entrance import readers


class _Raw:
    def __init__(self, b):
        self._b = b

    def read(self, n, decode_content=True):
        return self._b[:n]


class _Resp:
    def __init__(self, body, url="https://example.invalid/final.pdf", code=200, ct="application/pdf"):
        self.raw, self.url, self.status_code, self.headers = _Raw(body), url, code, {"Content-Type": ct}


def test_links_printed_in_a_file_are_found():
    assert readers.links_in("Read now: https://go.example.invalid/abc. And (https://x.example.invalid/p).") == ["https://go.example.invalid/abc", "https://x.example.invalid/p"]
    assert readers.links_in("no links here") == []


def test_a_link_that_leads_to_the_same_file_is_said_so(monkeypatch):
    body = b"%PDF-1.7 the same bytes"
    monkeypatch.setattr(readers, "_private_host", lambda h: False)
    r = readers.resolve_link("https://go.example.invalid/abc", hashlib.sha256(body).hexdigest(), getter=lambda url, **k: _Resp(body))
    assert r["same_file"] is True and r["error"] is None and r["final_url"].endswith("final.pdf")
    r2 = readers.resolve_link("https://go.example.invalid/abc", hashlib.sha256(b"other").hexdigest(), getter=lambda url, **k: _Resp(body))
    assert r2["same_file"] is False and r2["error"] is None


def test_a_private_or_failing_link_says_why(monkeypatch):
    assert "not a public web address" in readers.resolve_link("http://127.0.0.1/x", "0")["error"]
    monkeypatch.setattr(readers, "_private_host", lambda h: False)
    assert "404" in readers.resolve_link("https://x.example.invalid/", "0", getter=lambda url, **k: _Resp(b"", code=404))["error"]

    def boom(url, **k):
        raise ConnectionError("login wall")
    assert "ConnectionError" in readers.resolve_link("https://x.example.invalid/", "0", getter=boom)["error"]
