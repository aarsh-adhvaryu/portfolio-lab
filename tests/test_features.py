"""S65: beta features. The channel sets the default, his switch wins, only listed features take a switch, and the US sleeve
(dashboard panel, entry forms, the picture, the brain's US pass) hides and shows with the flag."""
from datetime import date, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pflab import features
from pflab.app import runtime, server, views
from pflab.app import settings as st
from pflab.hq import brain, picture
from pflab.pm import store

NOW = datetime(2026, 10, 22, 11, 30)


def test_the_channel_sets_the_default_and_his_switch_wins(monkeypatch):
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    assert features.channel() == "stable" and not features.enabled("us_sleeve", {})
    monkeypatch.setenv("PFLAB_CHANNEL", "beta")
    assert features.enabled("us_sleeve", {})
    assert not features.enabled("us_sleeve", {"features": {"us_sleeve": False}})          # his off beats the beta default
    assert features.enabled("us_sleeve", {"features": {"us_sleeve": True}}) and features.channel() == "beta"
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    assert features.enabled("us_sleeve", {"features": {"us_sleeve": True}})               # his on beats the stable default
    assert not features.enabled("no_such_feature", {"features": {"no_such_feature": True}})


def test_a_feature_not_marked_beta_is_on_by_default(tmp_path, monkeypatch):
    cfg = tmp_path / "f.toml"
    cfg.write_text('[plain]\ntitle = "Plain"\n[risky]\nbeta = true\ntitle = "Risky"\n', encoding="utf-8")
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    assert features.enabled("plain", {}, cfg) and not features.enabled("risky", {}, cfg)
    assert [(f["name"], f["beta"], f["on"]) for f in features.listing({}, cfg)] == [("plain", False, True), ("risky", True, False)]


def test_settings_keep_only_listed_features_with_true_or_false(tmp_path):
    out = st.save(tmp_path, {"features": {"us_sleeve": True, "nope": True}})
    assert out["features"] == {"us_sleeve": True}
    out = st.save(tmp_path, {"features": {"us_sleeve": "yes"}})
    assert out["features"] == {"us_sleeve": True}                                        # a non-boolean is ignored
    assert st.load(tmp_path)["features"] == {"us_sleeve": True}
    assert st.save(tmp_path, {"features": {"us_sleeve": False}})["features"] == {"us_sleeve": False}


def test_the_picture_leaves_the_sleeve_out_while_it_is_off(monkeypatch):
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    monkeypatch.setenv("PFLAB_PM_DIR", "Z:/no/such/pm")
    out = picture.us_sleeve(None, None, date(2026, 10, 28))                               # returns before touching the store
    assert "beta_off" in out and "positions" not in out


class _Con:
    def execute(self, *a, **k):
        return self

    def fetchone(self):
        return None


def test_the_us_open_pass_needs_the_flag_and_holdings(monkeypatch):
    from pflab.conductor import us_calendar as uc
    from pflab.ledger import foreign as lf
    monkeypatch.setattr(lf, "positions", lambda con, d: [{"symbol": "X"}])
    monkeypatch.setattr(uc.UsCalendar, "pass_time_ist", lambda self, d: datetime(2026, 10, 28, 19, 20))
    now = datetime(2026, 10, 28, 21, 0)
    monkeypatch.setenv("PFLAB_PM_DIR", "Z:/no/such/pm")
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    assert not brain._us_open_due(_Con(), now)                                            # holdings, flag off
    monkeypatch.setenv("PFLAB_CHANNEL", "beta")
    assert brain._us_open_due(_Con(), now)                                                # holdings, flag on
    monkeypatch.setattr(lf, "positions", lambda con, d: [])
    assert not brain._us_open_due(_Con(), now)                                            # flag on, nothing held


@pytest.fixture
def app(tmp_path, monkeypatch):
    pm, data = tmp_path / "pm", tmp_path / "data"
    (data / "indices").mkdir(parents=True)
    pd.DataFrame({"date": [date(2026, 10, 15)], "close": [100.0]}).to_parquet(data / "indices" / "NIFTY50_PRICE.parquet")
    con = store.connect(tmp_path / "l.duckdb")
    rt = runtime.Runtime(pm, data, tmp_path, con=con, clock=lambda: NOW)
    monkeypatch.setattr(views, "market", lambda asof: {"state": "calm", "chance": 0.3, "drawdown": -0.05, "dip_active": False})
    return rt, TestClient(server.create_app(rt))


def test_the_dashboard_hides_and_shows_the_us_panel_and_forms(app, monkeypatch):
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    rt, c = app
    assert c.get("/api/us").json()["enabled"] is False
    assert c.post("/api/us/trade", json={"date": "2026-10-20", "symbol": "SPY", "side": "buy", "qty": 1, "price": 100}).status_code == 403
    assert c.post("/api/us/remit", json={"date": "2026-10-20", "usd": 100, "inr": 8000}).status_code == 403
    listed = c.get("/api/features").json()
    assert listed["channel"] == "stable" and listed["features"][0]["name"] == "us_sleeve" and not listed["features"][0]["on"]
    c.post("/api/settings", json={"features": {"us_sleeve": True}})
    assert c.get("/api/us").json()["enabled"] is True
    assert c.get("/api/features").json()["features"][0]["on"] is True
    assert c.post("/api/us/remit", json={"date": "2026-10-20", "usd": 100, "inr": 8000}).status_code == 200
