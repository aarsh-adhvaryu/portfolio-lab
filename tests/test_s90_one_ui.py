"""S90: one UI. The old screens are gone (an old address lands on the new ones); a second Kite login click reuses the login in progress and a stray callback
does not end it; the Settings screen's operator values are validated and read over the configuration; the chat's default road reaches Telegram's messages; the
new endpoints behind Usage, the first-week card and the Kite line answer on an empty store. Synthetic data only."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pflab.app import runtime, server
from pflab.app import settings as st
from pflab.pm import store

NOW = datetime(2026, 11, 16, 10, 0)
STATIC = Path(__file__).resolve().parents[1] / "src" / "pflab" / "app" / "static"


@pytest.fixture
def app(tmp_path, monkeypatch):
    pm, data = tmp_path / "pm", tmp_path / "data"
    (data / "indices").mkdir(parents=True)
    monkeypatch.setenv("PFLAB_DATA_DIR", str(data))
    monkeypatch.setenv("PFLAB_PM_DIR", str(pm))
    from pflab.llm import claude_plan as cp
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": True, "method": "claude.ai", "detail": ""})
    rt = runtime.Runtime(pm, data, tmp_path, con=store.connect(tmp_path / "l.duckdb"), clock=lambda: NOW)
    return rt, TestClient(server.create_app(rt))


def test_only_the_new_screens_exist():
    assert not any((STATIC / f).exists() for f in ("app.js", "app.css", "ui.js", "world.js", "world.css", "redesign.js", "redesign.css", "index.html"))
    tpl = {p.stem for p in (STATIC / "s89" / "tpl").glob("*.html")}
    assert {"home", "money", "manage", "book", "lab", "graph", "chat", "agents", "usage", "settings", "stock"} <= tpl
    for name in ("chat", "agents", "usage", "settings"):                       # each screen is the design's template, filled by its module
        assert f"render(el, '{name}'" in (STATIC / "s89" / f"{name}.js").read_text(encoding="utf-8"), name


class _Secrets:
    def get(self, s, k):
        return {"api_key": "k", "api_secret": "s", "redirect_url": "http://127.0.0.1:5999/redirect"}[k]

    def has(self, s, k):
        return True


def test_a_second_kite_click_reuses_the_login_in_progress(app, monkeypatch):
    rt, c = app
    from pflab.app import runtime as rmod
    from pflab.ingest import kite as k
    made, release = [], threading.Event()

    class Flow:
        def __init__(self, secrets):
            made.append(self)

        def begin(self):
            return f"https://kite.example/login?n={len(made)}"

    monkeypatch.setattr(k, "LoginFlow", Flow)
    monkeypatch.setattr(rmod, "_kite_tools", lambda: type("T", (), {"wait_for_token": staticmethod(lambda flow, redirect, timeout=300: release.wait(5))}))
    rt.secrets = _Secrets()
    u1 = c.post("/api/kite/login").json()["url"]
    u2 = c.post("/api/kite/login").json()["url"]
    assert u1 == u2 and len(made) == 1 and rt.kite_state == "waiting"
    assert c.get("/api/kite/status").json()["login"] == "waiting"
    release.set()
    for _ in range(50):
        if rt.kite_state != "waiting":
            break
        time.sleep(0.05)
    assert rt.kite_state == "done"
    assert c.post("/api/kite/login").json()["url"] != u1 and len(made) == 2   # a finished login starts a fresh one


def test_a_stray_callback_does_not_end_the_wait(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("kl", Path(__file__).resolve().parents[1] / "tools" / "kite_login.py")
    kl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kl)
    from pflab.ingest import kite as k
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()

    class Flow:
        def finish(self, params, now):
            if params.get("state") != "good":
                raise k.LoginError("login callback state does not match: ignoring it")
            return "TOKEN"

    out = {}
    th = threading.Thread(target=lambda: out.setdefault("tok", kl.wait_for_token(Flow(), f"http://127.0.0.1:{port}/redirect", 10)))
    th.start()
    time.sleep(0.5)
    old = urllib.request.urlopen(f"http://127.0.0.1:{port}/redirect?status=success&request_token=x&state=old", timeout=5).read().decode()
    assert "older login" in old and th.is_alive()
    urllib.request.urlopen(f"http://127.0.0.1:{port}/redirect?status=success&request_token=x&state=good", timeout=5).read()
    th.join(5)
    assert out["tok"] == "TOKEN"


def test_settings_operator_values_are_checked_and_read_over_the_configuration(app):
    rt, c = app
    from pflab.llm import claude_plan as cp
    assert c.post("/api/settings", json={"operator": {"budget_chat": 12345, "build_on": False, "nse_mcp_url": "https://nse.example/mcp"}}).status_code == 200
    s = cp.settings()
    assert s["budget_chat"] == 12345 and s["build_on"] is False and s["nse_mcp_url"] == "https://nse.example/mcp"
    for bad in ({"budget_chat": -1}, {"budget_chat": 9_000_000}, {"nse_mcp_url": "http://plain"}, {"build_on": "yes"}, {"unknown": 1}):
        assert c.post("/api/settings", json={"operator": bad}).status_code == 400, bad
    assert c.post("/api/settings", json={"chat_road": "full"}).json()["chat_road"] == "full"
    assert c.post("/api/settings", json={"chat_road": "fast"}).json()["chat_road"] == "full"     # an unknown road is ignored
    from pflab.oper import build
    assert "switched off in Settings" in build.request(rt.cursor(), NOW, "the news top-up times out twice")


def test_the_default_road_reaches_a_message_without_one(app):
    rt, c = app
    st.save(rt.pm_dir, {"chat_road": "full"})
    from pflab.entrance import intake
    out = intake.submit(rt, "telegram", "how is my book doing")
    item = rt.cursor().execute("SELECT payload_json FROM intake_queue_s85 WHERE item_id=?", [out["item_id"]]).fetchone()[0]
    assert json.loads(item)["pick"]["road"] == "full"
    out = intake.submit(rt, "laptop", "and the index", road="auto")                    # Auto chosen on the screen stays Auto
    item = rt.cursor().execute("SELECT payload_json FROM intake_queue_s85 WHERE item_id=?", [out["item_id"]]).fetchone()[0]
    assert json.loads(item)["pick"]["road"] is None


def test_usage_week_and_kite_status_answer_on_an_empty_store(app):
    rt, c = app
    u = c.get("/api/usage/plan").json()
    assert len(u["series"]) == 30 and set(u["budgets"]) == {"desk", "cases", "build", "chat", "chat_light"} and len(u["heat"]) == 5 and all(len(r["cells"]) == 20 for r in u["heat"])
    w = c.get("/api/week").json()
    assert w["of"] == 7 and w["arm_from"] == "2026-11-16" and isinstance(w["criteria"], list)
    k = c.get("/api/kite/status").json()
    assert k["login"] == "idle" and k["token_today"] in (True, False)
    a = c.get("/api/agents").json()
    assert {s["name"] for s in a["skills"]} >= {"case_review"}
