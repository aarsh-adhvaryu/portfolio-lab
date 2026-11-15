"""S91: the controlled public-web path of the full operator. The SDK's own WebSearch / WebFetch run on his plan (no API key, no paid search); a guard refuses anything of his in the words and any local
or private address; what a page said is the source of its own numbers and of nothing else; every web answer ends with the addresses and the time it was read, and the pages are kept
(`web_evidence_s91`); the Settings switch "Search the web" turns the tools off. A scripted SDK only (the live check is in the drill)."""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from pflab.hq import egress
from pflab.llm import claude_plan as cp
from pflab.oper import perms, session
from test_s87_claude_plan import FakeClient, assistant, result  # noqa: F401

NOW = datetime(2026, 11, 16, 10, 0)


def _mk(cls_name, **kw):
    o = type(cls_name, (), {})()
    o.__dict__.update(kw)
    return o


PAGE = ("AAAA Corp reported quarterly revenue of 12,345 million dollars. Published 2026-11-12. Source: https://example.com/aaaa-results and https://example.org/news/aaaa.")


@pytest.fixture
def con(tmp_path, monkeypatch):
    from pflab.pm import store
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    FakeClient.seen, FakeClient.script, FakeClient.capture_tool = [], [], None
    monkeypatch.setattr(cp, "client_factory", FakeClient)
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": True, "method": "claude.ai", "detail": ""})
    return store.connect(tmp_path / "t.duckdb")


def _ctx():
    return SimpleNamespace(source="the book is Rs 100", decisions=[], problems=[], results={}, images=[], con=None, gate=egress.Gate(ids=set(), names=["zed q example"], address=[]))


def _ask(con, tmp_path, web_on=True):
    from pflab.hq import passes
    ctx = _ctx()
    pid = passes.record(con, NOW, "assistant", [], "m", "assistant", "running")
    rt = SimpleNamespace(data_root=str(tmp_path / "data"), settings={"abilities": {"web": web_on}})
    r = {"role": "read", "model_key": "sonnet", "thinking": "medium", "auto": True, "why": "test", "tools": "all"}
    return session.answer(rt, con, NOW, ctx=ctx, pid=pid, first="HIS MESSAGE:\nwhat did AAAA Corp report?", r=r, model_id="claude-sonnet-5-5", cid=5, aid=1, q="what did AAAA Corp report?", progress=lambda s: None)


def _web_script():
    use = _mk("ToolUseBlock", id="tu1", name="WebSearch", input={"query": "AAAA Corp quarterly revenue"})
    res = _mk("ToolResultBlock", tool_use_id="tu1", content=[{"type": "text", "text": PAGE}], is_error=False)
    return [_mk("AssistantMessage", content=[use], model="claude-sonnet-5-5"), _mk("UserMessage", content=[res]),
            assistant("AAAA reported revenue of 12,345 million dollars (page dated 2026-11-12). It will reach 99,999 million next year."), result("", sid="w1")]


def test_web_results_are_the_source_of_their_own_numbers_and_the_reply_ends_with_the_addresses(con, tmp_path):
    FakeClient.script = _web_script()
    out = _ask(con, tmp_path)
    assert "12,345" in out["text"] and "99,999" not in out["text"] and "removed" in out["text"]                # what the page said stays; the model's own number goes
    assert "Sources, read 16 Nov 2026 10:00" in out["text"] and "https://example.com/aaaa-results" in out["text"] and "https://example.org/news/aaaa" in out["text"]
    rows = con.execute("SELECT tool, query, urls, excerpt FROM web_evidence_s91").fetchall()
    assert len(rows) == 1 and rows[0][0] == "WebSearch" and "AAAA Corp quarterly revenue" in rows[0][1] and "example.com" in rows[0][2] and "12,345" in rows[0][3]
    opts = FakeClient.seen[-1]
    assert "WebSearch" in opts.tools and "WebFetch" in opts.tools and not any(k for k in (opts.env or {}) if k.endswith("_API_KEY") and (opts.env or {})[k])


def test_the_settings_switch_turns_the_web_tools_off(con, tmp_path):
    FakeClient.script = [assistant("No web today."), result("", sid="w2")]
    _ask(con, tmp_path, web_on=False)
    opts = FakeClient.seen[-1]
    assert "WebSearch" not in opts.tools and "WebFetch" not in opts.tools
    ok = asyncio.run(opts.can_use_tool("WebSearch", {"query": "AAAA Corp revenue"}, None))
    assert type(ok).__name__ == "PermissionResultDeny" and "switched off" in ok.message


def test_the_permission_callback_allows_public_questions_and_refuses_his_data_and_private_addresses(con, tmp_path):
    FakeClient.script = [assistant("ok"), result("", sid="w3")]
    _ask(con, tmp_path)
    can = FakeClient.seen[-1].can_use_tool
    run = lambda n, i: asyncio.run(can(n, i, None))
    assert type(run("WebSearch", {"query": "AAAA Corp latest quarterly results"})).__name__ == "PermissionResultAllow"
    assert type(run("WebFetch", {"url": "https://example.com/aaaa-results", "prompt": "revenue"})).__name__ == "PermissionResultAllow"
    for n, i in (("WebSearch", {"query": "I hold 120 shares of AAAA Corp worth Rs 50,000: sell?"}), ("WebSearch", {"query": "my portfolio ABCDE1234F"}),
                 ("WebSearch", {"query": "news about Zed Q Example"}),                                                    # his name (the egress gate)
                 ("WebFetch", {"url": "http://example.com/x", "prompt": "x"}), ("WebFetch", {"url": "https://127.0.0.1:8765/api/mine", "prompt": "x"}),
                 ("WebFetch", {"url": "https://intranet/x", "prompt": "x"}), ("WebFetch", {"url": "https://example.com/x?token=abc", "prompt": "x"})):
        assert type(run(n, i)).__name__ == "PermissionResultDeny", (n, i)
    assert not perms.decide("build", "WebSearch", {"query": "x"}, Path("."))[0]                                              # a build session has no web


def test_an_old_settings_file_that_denied_the_web_is_replaced(tmp_path):
    from pflab.oper import workspace
    r = workspace.root(str(tmp_path))
    (r / ".claude").mkdir(parents=True)
    (r / ".claude" / "settings.json").write_text('{"permissions": {"deny": ["WebSearch", "WebFetch"]}}', encoding="utf-8")
    workspace.ensure(str(tmp_path))
    assert "WebSearch" not in (r / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert "Fresh facts from the public web" in (r / "CLAUDE.md").read_text(encoding="utf-8")


def test_a_failed_search_leaves_no_footer_and_no_invented_sources(con, tmp_path):
    use = _mk("ToolUseBlock", id="tu9", name="WebSearch", input={"query": "AAAA Corp"})
    err = _mk("ToolResultBlock", tool_use_id="tu9", content="web search is unavailable", is_error=True)
    FakeClient.script = [_mk("AssistantMessage", content=[use], model="m"), _mk("UserMessage", content=[err]), assistant("I could not reach the web: the search tool answered that it is unavailable."), result("", sid="w4")]
    out = _ask(con, tmp_path)
    assert "could not reach the web" in out["text"] and "https://" not in out["text"] and "pages returned no addresses" in out["text"]
