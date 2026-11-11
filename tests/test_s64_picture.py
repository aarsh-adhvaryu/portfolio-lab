"""S64: the one picture: each section stands alone, the stance comes from the tested states only, stale news is said."""
from datetime import date, datetime, timedelta

import duckdb
import pytest

from pflab.hq import picture
from pflab.pm import store

ASOF = date(2026, 10, 27)


@pytest.fixture
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "pm.duckdb"))
    store.migrate(c)
    return c


def test_a_section_that_cannot_be_built_says_why_and_the_rest_stand():
    out = {}
    picture._try("a", lambda: {"ok": 1}, out)
    picture._try("b", lambda: 1 / 0, out)
    assert out["a"] == {"ok": 1} and "ZeroDivisionError" in out["b"]["not_built"]


def test_news_mood_says_when_the_news_is_not_current(con):
    old = datetime(2026, 10, 20)
    for k in range(3):
        con.execute("INSERT INTO kg_docs (doc_id, kind, title, source, published_at, tone, ingested_at) VALUES (?, 'article', 't', 's', ?, ?, now())",
                    [f"d{k}", old, -2.0])
    m = picture.news_mood(con, ASOF, {})
    assert m["market_last_3_days"] == (None, 0) and m["newest_article"] == "2026-10-20" and "NOT today's" in m["stale"]
    con.execute("INSERT INTO kg_docs (doc_id, kind, title, source, published_at, tone, ingested_at) VALUES ('n', 'article', 't', 's', ?, 1.0, now())",
                [datetime(2026, 10, 26)])
    m2 = picture.news_mood(con, ASOF, {})
    assert m2["market_last_3_days"] == (1.0, 1) and "stale" not in m2 and m2["market_prior_90_days"] == (-2.0, 3)


def test_waiting_and_learning_counts(con):
    con.execute("INSERT INTO questions (q_id, created_at, agent, subject_key, text, status) VALUES (1, now(), 'a', 'k', 't', 'open')")
    assert picture.waiting(con) == {"open_questions": 1, "held_messages": 0}
    assert picture.learning(con)["tests_run"] == 0


def test_headline_is_built_from_the_sections():
    p = {"market": {"stance": "watch", "fall_clustering_state": "calm", "nifty500_below_1y_high_pct": -10.4, "dip_rule_active": True},
         "news_mood": {"stale": "no articles stored for the last 3 days (the newest is 2026-10-20): the news collector is behind"},
         "portfolio": {"buckets": {"equity": {"now_pct": 4.0, "target_pct": 38.0, "state": "under"}}},
         "themes_and_cash": {"themes": {"ai_it": {"label": "AI and IT", "share_of_portfolio_pct": 8.9, "limit_pct": None}}},
         "holdings": [{"symbol": "AAA", "held": True, "guard": "ok"}, {"symbol": "BBB", "held": True, "guard": "block"}],
         "on_offer": {"open_pot_ideas": []}, "waiting_for_him": {"open_questions": 5, "held_messages": 2}}
    h = picture.headline(p)
    assert h[0].startswith("Market: watch") and "dip rule on" in h[0]
    assert "News mood: no articles stored" in h[1] and "equity 4% (target 38%, under)" in h[2]
    assert "AI and IT 8.9% (no limit yet)" in h[3] and "warnings on ['BBB']" in h[4] and "buy zone" not in h[4]       # A60: the zone failed its test and is not on offer
    assert "5 questions; 2 held messages" in h[5]


def test_the_cache_is_reused_only_for_the_same_day_and_a_fresh_file(con, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(picture, "build", lambda *a, **k: (calls.append(1), {"asof": str(ASOF), "headline": []})[1])
    picture.cached(con, tmp_path, ASOF, None, tmp_path)
    picture.cached(con, tmp_path, ASOF, None, tmp_path)
    assert len(calls) == 1
    picture.cached(con, tmp_path, ASOF + timedelta(days=1), None, tmp_path)                # another day: built again
    assert len(calls) == 2
