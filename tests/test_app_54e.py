"""S54e: simulations (the fan, the batch errors, stress episodes, the nightly run by preset), the presets and the
checklists, and the knowledge-graph view (weights, the time slider, noise and self-naming dropped)."""
import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pflab.app import checklists as cl
from pflab.app import graph, runtime, server, sims
from pflab.app import settings as st
from pflab.pm import store
from pflab.risk import montecarlo as mc

NOW = datetime(2026, 10, 23, 22, 30)


@pytest.fixture
def rt(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def test_presets_choose_the_jobs_and_reject_unknown_values(rt, monkeypatch):
    reg = {"collect": 1, "prices": 1, "kg": 1, "research": 1, "conductor": 1, "outbox": 1}
    assert st.jobs_for("off", reg) == [] and st.jobs_for("full", reg) == list(reg)
    assert set(st.jobs_for("light", reg)) == {"collect", "prices", "conductor"}
    assert rt.set_settings({"preset": "bogus", "sims_hour": "late"})["preset"] == "full"
    from pflab.service import jobs
    seen = []
    monkeypatch.setattr(jobs, "is_due", lambda ctx, job: (True, "test"))
    monkeypatch.setattr(jobs, "tick", lambda ctx, only: seen.append(list(only)) or [])
    rt.set_settings({"preset": "light"})
    rt.scheduler_once()
    assert "kg" not in seen[-1] and "research" not in seen[-1] and "conductor" in seen[-1] and "outbox" not in seen[-1]
    rt.set_settings({"preset": "off"})
    assert rt.scheduler_once() == [] and len(seen) == 1                          # nothing due: no tick at all


def test_checklists_are_separate_from_sticky_notes(rt):
    c = TestClient(server.create_app(rt))
    c.post("/api/notes", json={"text": "a sticky note"})
    name = c.post("/api/checklists", json={"template": "Company research", "subject": "Example Ltd"}).json()["name"]
    assert name == "Company research: Example Ltd"
    assert c.post("/api/checklists", json={"template": "Company research", "subject": "Example Ltd"}).status_code == 400
    assert c.post("/api/checklists", json={"template": "Nope"}).status_code == 400
    assert [n["text"] for n in c.get("/api/command").json()["notes"]] == ["a sticky note"]
    d = c.get("/api/schedule").json()
    lst = d["checklists"][0]
    assert lst["name"] == name and len(lst["items"]) == len(cl.TEMPLATES["Company research"])
    c.post(f"/api/notes/{lst['items'][0]['id']}/toggle")
    assert c.get("/api/schedule").json()["checklists"][0]["items"][0]["done"] is True
    c.post("/api/checklists/close", json={"name": name})
    assert c.get("/api/schedule").json()["checklists"] == []
    assert d["preset"] == "full" and d["sims"]["paths"] == 10_000 and any(j["job"] == "conductor" for j in d["jobs"])


def returns(seed=0, months=180):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2007-04-30", periods=months, freq="ME")
    R = pd.DataFrame({"stocks": rng.normal(0.01, 0.06, months), "n500": rng.normal(0.01, 0.05, months),
                      "mom50": rng.normal(0.012, 0.07, months), "gold": rng.normal(0.008, 0.04, months),
                      "debt": 0.0057, "cash": 0.003}, index=idx)
    days = pd.bdate_range("2007-03-01", "2026-09-30")
    Rd = pd.DataFrame({"stocks": rng.normal(0.0004, 0.012, len(days)), "n500": rng.normal(0.0004, 0.01, len(days)),
                       "mom50": rng.normal(0.0005, 0.013, len(days)), "gold": rng.normal(0.0003, 0.008, len(days)),
                       "debt": 0.00027, "cash": 0.00014}, index=days)
    crash = (Rd.index >= "2020-02-20") & (Rd.index <= "2020-03-23")
    Rd.loc[crash, ["stocks", "n500", "mom50"]] = -0.02                          # a known fall inside the Covid window
    return R, Rd


def test_fan_percentiles_and_batch_errors():
    R, _ = returns()
    w = mc.weights_of({"stocks": 0.6, "debt": 0.4})
    f = sims.fan(R.values, w, 36, 20_000, np.random.default_rng(1))
    for i in range(36):
        assert f["p5"][i] <= f["p25"][i] <= f["p50"][i] <= f["p75"][i] <= f["p95"][i]
    y1 = f["years"]["1"]
    assert set(f["years"]) == {"1", "3"} and 0 < y1["se_p50"] < 0.01             # 20,000 paths: a small error
    debt = sims.fan(R.values, mc.weights_of({"debt": 1.0}), 12, 1_000, np.random.default_rng(1))
    assert debt["p5"][-1] == pytest.approx(1.0057 ** 12) and debt["years"]["1"]["se_p50"] == pytest.approx(0, abs=1e-12)


def test_stress_replays_dated_episodes():
    _, Rd = returns()
    st_ = sims.stress(Rd, mc.weights_of({"stocks": 1.0}))
    covid = next(e for e in st_["episodes"] if e["name"].startswith("2020"))
    assert covid["covered"] and covid["worst_fall"] < -0.3
    assert next(e for e in st_["episodes"] if e["name"].startswith("2008"))["covered"]
    late = sims.stress(Rd[Rd.index >= "2012-01-01"], mc.weights_of({"stocks": 1.0}))
    assert not next(e for e in late["episodes"] if e["name"].startswith("2008"))["covered"]
    assert st_["worst"]["fall"] <= covid["worst_fall"] and st_["worst"]["peak"] < st_["worst"]["trough"]


def test_run_saves_every_mix_and_refuses_bad_input(rt, monkeypatch):
    R, Rd = returns()
    monkeypatch.setattr(mc, "history", lambda root: R)
    monkeypatch.setattr(mc, "history_daily", lambda root: Rd)
    monkeypatch.setattr(sims, "current_mix", lambda con, d: {"stocks": 0.3, "debt": 0.7})
    monkeypatch.setattr(sims, "target_mix", lambda con: {"stocks": 0.5, "n500": 0.2, "gold": 0.15, "debt": 0.15})
    monkeypatch.setattr(sims, "invested", lambda con, d: 1000.0)
    monkeypatch.setattr(sims, "FRONTIER_N", 200)
    with pytest.raises(ValueError):
        sims.run(rt, paths=5_000)
    out = sims.run(rt, paths=10_000, years=2, custom={"gold": 1, "debt": 1})
    assert set(out["mixes"]) == {"current", "target", "what-if"}
    assert out["mixes"]["what-if"]["mix"]["gold"] == pytest.approx(0.5)
    assert out["mixes"]["current"]["fall"]["n"] == 10_000 and len(out["frontier"]) == 200
    assert json.loads(sims.path(rt).read_text(encoding="utf-8"))["at"] == NOW.isoformat(timespec="seconds")
    assert not rt.sims_running


def test_the_nightly_run_follows_the_preset_and_the_hour(rt, monkeypatch):
    calls = []
    monkeypatch.setattr(sims, "run", lambda rt_, paths, years: calls.append(paths) or {"at": NOW.isoformat()})
    rt.set_settings({"preset": "light"})
    assert rt.nightly_sims() is None
    rt.set_settings({"preset": "marathon"})
    rt.clock = lambda: datetime(2026, 10, 23, 21, 0)
    assert rt.nightly_sims() is None                                            # before the hour
    rt.clock = lambda: NOW
    rt.nightly_sims()
    assert calls == [100_000]
    sims.path(rt).parent.mkdir(parents=True, exist_ok=True)
    sims.path(rt).write_text(json.dumps({"at": "2026-10-23T22:10:00"}), encoding="utf-8")
    assert rt.nightly_sims() is None and calls == [100_000]                     # already run tonight


def kg(con):
    t = datetime(2026, 10, 15)
    con.execute("INSERT INTO kg_nodes VALUES ('company:INE000A01001', 'company', 'acme industries', NULL, ?)", [t])
    for n, k in (("org:acme industries ltd", "org"), ("org:big bank", "org"), ("org:one-off co", "org"),
                 ("theme:WB_1804_AIRPORTS", "theme"), ("theme:TAX_FNCACT", "theme"), ("sector:Power", "sector")):
        con.execute("INSERT INTO kg_nodes VALUES (?, ?, ?, NULL, ?)", [n, k, n.split(":", 1)[1], t])
    con.execute("INSERT INTO kg_edges VALUES ('company:INE000A01001', 'in_sector', 'sector:Power', ?, NULL, 'x', NULL, NULL, ?)", [t, t])
    for i, (pub, names) in enumerate((("2025-03-01", ["org:big bank", "org:acme industries ltd", "theme:WB_1804_AIRPORTS",
                                                      "theme:TAX_FNCACT", "org:one-off co"]),
                                      ("2026-02-01", ["org:big bank", "org:acme industries ltd", "theme:WB_1804_AIRPORTS",
                                                      "theme:TAX_FNCACT"]),
                                      ("2026-09-01", ["org:big bank"]))):
        d = f"doc:article:{i}"
        con.execute("INSERT INTO kg_docs (doc_id, kind, title, source, published_at, ingested_at) VALUES (?, 'article', ?, 'x', ?, ?)",
                    [d, f"story {i}", pub, t])
        con.execute("INSERT INTO kg_edges VALUES (?, 'mentions', 'company:INE000A01001', ?, NULL, 'x', NULL, NULL, ?)", [d, t, t])
        for n in names:
            con.execute(f"INSERT INTO kg_edges VALUES (?, '{'has_theme' if n.startswith('theme') else 'names'}', ?, ?, NULL, 'x', NULL, NULL, ?)",
                        [d, n, t, t])


def test_graph_view_weights_noise_and_the_time_slider(rt):
    con = rt.cursor()
    kg(con)
    v = graph.view(con, kinds=graph.KINDS)
    by = {n["id"]: n for n in v["nodes"]}
    assert by["company:INE000A01001"]["docs"] == 3 and "sector:Power" in by
    assert "org:big bank" in by and next(e for e in v["edges"] if e["b"] == "org:big bank")["w"] == 3
    assert "org:one-off co" not in by                                           # named once: not drawn
    assert "org:acme industries ltd" not in by                                  # the company naming itself
    assert "theme:TAX_FNCACT" not in by and by["theme:WB_1804_AIRPORTS"]["label"] == "airports"
    early = graph.view(con, upto=date(2025, 12, 31), kinds=graph.KINDS)
    assert early["totals"]["docs"] == 1 and not any(n["kind"] == "org" for n in early["nodes"])
    d = graph.node(con, "company:INE000A01001")
    assert [x["title"] for x in d["docs"]] == ["story 2", "story 1", "story 0"]
    assert graph.node(con, "org:big bank")["companies"] == [{"id": "company:INE000A01001", "docs": 3}]
    c = TestClient(server.create_app(rt))
    assert c.get("/api/graph?upto=2025-12").json()["totals"]["docs"] == 1
    assert c.get("/api/graph?upto=bad").status_code == 400
    assert c.get("/api/doc?id=doc:article:0").json()["title"] == "story 0"


def test_your_stocks_use_their_own_returns_and_the_proxy_before_listing(tmp_path):
    days = pd.bdate_range("2020-01-01", periods=10)
    proxy = pd.Series(0.01, index=days)
    rows = []
    for i, d in enumerate(days):                                        # A: all ten days, price up 2% a day
        rows.append({"date": d.date(), "isin": "A", "close": 100 * 1.02 ** i, "adj_close": 100 * 1.02 ** i, "dividend": None})
    for i, d in enumerate(days[5:]):                                    # B: lists on day 6, flat, a dividend on day 8
        rows.append({"date": d.date(), "isin": "B", "close": 50.0, "adj_close": 50.0, "dividend": 1.0 if i == 2 else None})
    (tmp_path / "panel").mkdir()
    pd.DataFrame(rows).to_parquet(tmp_path / "panel" / "prices.parquet")
    out, own = sims.mine_daily(tmp_path.as_posix(), {"A": 0.5, "B": 0.5}, proxy)
    assert out.iloc[1] == pytest.approx(0.5 * 0.02 + 0.5 * 0.01)        # B not listed yet: the proxy stands in
    assert out.iloc[5] == pytest.approx(0.5 * 0.02 + 0.5 * 0.01)        # B's first day has no return: still the proxy
    assert out.iloc[6] == pytest.approx(0.5 * 0.02)                     # then its own (flat)
    assert out.iloc[7] == pytest.approx(0.5 * 0.02 + 0.5 * 0.02)        # the dividend counts (1 on 50)
    assert own == pytest.approx(0.5 * 0.9 + 0.5 * 0.4)                  # days with a return of its own
    assert sims.mine_daily(tmp_path.as_posix(), {}, proxy)[1] == 0.0
