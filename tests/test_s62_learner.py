"""S62 the learner (PLAN A22): coded tests and their one rule, sources, quoted claims, registration before the test,
wiring of passes, proposals from the system's own record, his answers. Synthetic data, fake models, no network."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pflab.hq import tools as tl
from pflab.hq.desk import Desk
from pflab.learner import claims, live, record, run, sources, templates as tp
from pflab.pm import store

NOW = datetime(2026, 10, 31, 11, 0)          # a Saturday, after the record's hour


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


def _desk(con, tmp_path, **settings):
    s = {"brain": "economy", "preset": "full", "telegram_send": False, **settings}
    return Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, s, clock=lambda: NOW)


# --- templates: the rule and the cross-section engine ----------------------------------------------------------------

def test_check_params_closed_lists():
    assert tp.check_params("cross_section", {"signal": "momentum_12_1", "direction": "high", "months": 1}) is None
    assert "one of" in tp.check_params("cross_section", {"signal": "pe_ratio", "direction": "high", "months": 1})
    assert "exactly" in tp.check_params("calendar", {"effect": "monday"})
    assert "unknown" in tp.check_params("astrology", {})


def test_decide_needs_both_periods_direction_t_and_cost():
    good = {"mean": 0.01, "t": 2.5, "n": 60}
    assert tp.decide(good, {"mean": 0.008, "t": 1.7, "n": 48}, 1, 36, 0.0, "months")[0] == "pass"
    assert "other way" in tp.decide(good, {"mean": -0.002, "t": -1.0, "n": 48}, 1, 36, 0.0, "months")[1]
    assert "under 1.65" in tp.decide(good, {"mean": 0.004, "t": 1.2, "n": 48}, 1, 36, 0.0, "months")[1]
    assert "small numbers" in tp.decide(good, {"mean": 0.01, "t": 3.0, "n": 12}, 1, 36, 0.0, "months")[1]
    assert "cost" in tp.decide(good, {"mean": 0.001, "t": 2.0, "n": 48}, 1, 36, 0.002, "months")[1]
    down = {"mean": -0.02, "t": -2.4, "n": 30}
    assert tp.decide(down, down, -1, 20, 0.001, "events")[0] == "pass"


def _panel(n_names=120, n_days=1500, persist=True, seed=3):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2014-01-01", periods=n_days)
    mu = rng.normal(0.0004, 0.0008, n_names) if persist else np.zeros(n_names)
    r = pd.DataFrame(rng.normal(0, 0.012, (n_days, n_names)) + mu, index=days,
                     columns=[f"INE{i:06d}A0" for i in range(n_names)])
    tr = (1 + r).cumprod()
    w = {"r": r, "tr": tr, "adj": tr.copy(), "turnover": pd.DataFrame(1e8, index=days, columns=r.columns)}
    mem = pd.DataFrame({"isin": r.columns, "from_date": pd.Timestamp("2000-01-01"), "to_date": pd.Timestamp("2099-01-01")})
    return w, mem


def test_holder_events_from_promoter_changes_are_dated_at_the_filing_deadline(tmp_path):
    (tmp_path / "bse_shareholding").mkdir()
    (tmp_path / "bse_scrip_isin").mkdir()
    pd.DataFrame({"scrip_code": ["500001"] * 3, "quarter_end": [pd.Timestamp("2016-03-31").date(),
                                                               pd.Timestamp("2016-06-30").date(), pd.Timestamp("2016-09-30").date()],
                  "status": "ok", "promoter_pct": [50.0, 50.2, 51.0], "pledged_pct_of_promoter": [0.0, 0.0, 2.5]}
                 ).to_parquet(tmp_path / "bse_shareholding" / "summary.parquet")
    pd.DataFrame({"scrip_code": ["500001"], "isin": ["INE000A01011"]}).to_parquet(tmp_path / "bse_scrip_isin" / "map.parquet")
    up = tp.holder_events(tmp_path, "promoter_up", "2015-01-01", "2018-12-31")
    assert list(up["t"]) == [pd.Timestamp("2016-10-21 16:00")]            # +0.2 is under the step; +0.8 counts
    assert len(tp.holder_events(tmp_path, "pledge_up", "2015-01-01", "2018-12-31")) == 1
    assert tp.holder_events(tmp_path, "promoter_down", "2015-01-01", "2018-12-31").empty
    assert tp.check_params("holder_event", {"kind": "bulk_buy", "direction": "up", "sessions": 5}) is None
    assert claims.fits("Stocks rise after bulk deals by funds.", "", "holder_event", {"kind": "bulk_buy"})
    assert not claims.fits("Stocks rise after results.", "", "holder_event", {"kind": "bulk_buy"})


def test_cross_section_finds_persistent_winners_and_not_noise():
    w, mem = _panel(persist=True)
    s = tp.cross_section_series(w, mem, "momentum_12_1", "high", 1, "2015-03-01", "2019-06-30", 0.2)
    m, t, n = tp.nw_t(s.values, 1)
    assert n >= 36 and m > 0 and t > 2                     # stocks with a lasting drift keep winning
    w0, mem0 = _panel(persist=False, seed=5)
    s0 = tp.cross_section_series(w0, mem0, "momentum_12_1", "high", 1, "2015-03-01", "2019-06-30", 0.2)
    assert abs(tp.nw_t(s0.values, 1)[1]) < 2.5             # pure noise: no effect worth the name


def test_signal_uses_only_past_rows():
    w, _ = _panel(n_names=10, n_days=400)
    i = 300
    before = tp.signal_at(w, i, "volatility_12m")
    w2 = {k: v.copy() for k, v in w.items()}
    w2["r"].iloc[i + 1:] = 9.0                              # the future changed: the signal at i must not move
    assert np.allclose(before.values, tp.signal_at(w2, i, "volatility_12m").values)


def test_turn_of_month_days():
    d = pd.bdate_range("2020-01-01", "2020-02-29")
    on = tp.effect_days(d, "turn_of_month")
    assert list(d[on].day) == [1, 2, 3, 31, 3, 4, 5, 28]   # first three sessions and the last of each month


# --- sources ----------------------------------------------------------------------------------------------------------

RSS = """<rss><channel><item><title>Momentum in Indian stocks</title><link>https://blog.example/m</link>
<description>Past winners keep winning: momentum stock returns in India.</description><pubDate>Mon, 20 Oct 2025</pubDate></item>
<item><title>Bitcoin halving</title><link>https://blog.example/b</link><description>crypto stuff</description></item>
</channel></rss>"""
ARXIV = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2510.00001v1</id>
<title>Low volatility anomaly</title><summary>Low volatility stocks earn higher risk-adjusted returns.</summary>
<published>2025-10-01T00:00:00Z</published><author><name>A. Author</name></author></entry></feed>"""


def test_sources_parse_screen_and_keep_once(con, tmp_path):
    feeds = {"https://blog.example/feed": RSS, "http://export.arxiv.org/api/query": ARXIV,
             "https://api.openalex.org/works": json.dumps({"results": [{"id": "https://openalex.org/W1", "title": "PEAD India",
                                                                         "publication_year": 2019, "abstract_inverted_index": {
                                                                             "earnings": [0], "drift": [1], "persists": [2]},
                                                                         "open_access": {"oa_url": "https://x/p.pdf"}}]})}
    cfg = {"rss": {"feeds": ["https://blog.example/feed"]}, "arxiv": {}, "openalex": {"searches": ["pead"]}}
    get = lambda url, params: feeds[url]                       # noqa: E731
    out = sources.collect(con, NOW, tmp_path / "repo", tmp_path / "text", get=get, cfg=cfg)
    assert out == {"arxiv": 1, "openalex": 1, "rss": 2, "drop": 0}
    st = dict(con.execute("SELECT title, status FROM learn_sources").fetchall())
    assert st["Bitcoin halving"] == "skipped" and st["Momentum in Indian stocks"] == "new"
    assert con.execute("SELECT abstract FROM learn_sources WHERE origin='openalex'").fetchone()[0] == "earnings drift persists"
    assert sources.collect(con, NOW, tmp_path / "repo", tmp_path / "text", get=get, cfg=cfg)["rss"] == 0   # kept once


def test_drop_folder_files_are_read_whatever_their_words(con, tmp_path):
    d = tmp_path / "repo" / "drop" / "learn"
    d.mkdir(parents=True)
    (d / "my_book.txt").write_text("A book about gardening and patience.", encoding="utf-8")
    assert sources.drop(con, NOW, tmp_path / "repo", tmp_path / "text") == 1
    assert con.execute("SELECT status, origin FROM learn_sources").fetchone() == ("new", "drop")
    assert sources.drop(con, NOW, tmp_path / "repo", tmp_path / "text") == 0


# --- claims ---------------------------------------------------------------------------------------------------------------

TEXT = ("We study Indian equities from 2001 to 2020. Stocks with the highest past twelve-month returns continue to "
        "outperform the lowest over the following month. Volatility does not explain it.")
CLAIM = {"claim": "Past 12-month winners outperform next month.",
         "quote": "Stocks with the highest past twelve-month returns continue to outperform the lowest over the following month.",
         "template": "cross_section", "signal": "momentum_12_1", "direction": "high", "months": 1, "kind": "", "sessions": 0,
         "effect": "", "needs": ""}


def _source(con, tmp_path, text=TEXT):
    sid = sources._add(con, NOW, "drop", "drop:abc", "A momentum paper", "", 2021, "file", text[:3000])
    p = tmp_path / "t.txt"
    p.write_text(text, encoding="utf-8")
    con.execute("UPDATE learn_sources SET text_path=?, status='screened' WHERE src_id=?", [str(p), sid])
    return sid


def test_read_keeps_only_quoted_claims_and_falls_back_to_haiku(con, tmp_path):
    sid = _source(con, tmp_path)

    def broken(system, prompt, schema):
        raise ValueError("not JSON")
    invented = dict(CLAIM, quote="Momentum is the strongest anomaly in every market ever studied by anyone.")
    haiku = lambda s, p, sc: {"claims": [CLAIM, invented, dict(CLAIM, template="none", needs="intraday data")]}  # noqa: E731
    ids = claims.read(con, [("local", broken), ("haiku", haiku)], sid, TEXT, NOW)
    rows = con.execute("SELECT template, status, model, params_json FROM learn_claims ORDER BY claim_id").fetchall()
    assert len(ids) == 2                                    # the invented quote is dropped
    assert rows[0][:3] == ("cross_section", "proposed", "haiku")
    assert json.loads(rows[0][3]) == {"signal": "momentum_12_1", "direction": "high", "months": 1}
    assert rows[1][1] == "untestable"


def test_register_before_test_then_wire_a_pass(con, tmp_path):
    sid = _source(con, tmp_path)
    [cid] = claims.read(con, [("local", lambda s, p, sc: {"claims": [CLAIM]})], sid, TEXT, NOW)
    assert claims.register(con, cid, tmp_path / "proto", NOW) == "registered"
    proto = json.loads((tmp_path / "proto" / f"claim_{cid}.json").read_text(encoding="utf-8"))
    assert proto["params"]["signal"] == "momentum_12_1" and proto["code_sha256"] == claims.code_sha()
    seen = {}

    def fake_run(root, t, prm):
        seen["args"] = (t, prm)
        return {"decision": "pass", "why": "both periods held", "development": {}, "validation": {}}
    assert claims.test(con, cid, tmp_path, NOW, run=fake_run) == "pass"
    assert seen["args"] == ("cross_section", proto["params"])
    assert "momentum_12_1" in live.brain_text(con) and "TESTED FINDINGS" in live.brain_text(con)
    # the same test from another source is not run twice
    [c2] = claims.read(con, [("local", lambda s, p, sc: {"claims": [CLAIM]})], sid, TEXT, NOW)
    assert claims.register(con, c2, tmp_path / "proto", NOW) == "same"


def test_changed_protocol_is_not_run(con, tmp_path):
    sid = _source(con, tmp_path)
    [cid] = claims.read(con, [("local", lambda s, p, sc: {"claims": [CLAIM]})], sid, TEXT, NOW)
    claims.register(con, cid, tmp_path / "proto", NOW)
    p = tmp_path / "proto" / f"claim_{cid}.json"
    p.write_text(p.read_text(encoding="utf-8").replace("momentum_12_1", "momentum_6_1"), encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed after registration"):
        claims.test(con, cid, tmp_path, NOW, run=lambda *a: {"decision": "pass", "why": ""})


def test_claim_must_name_what_its_test_measures(con, tmp_path):
    sid = _source(con, tmp_path)
    wrong = dict(CLAIM, signal="high_52w")                  # the words say past returns, not the 52-week high
    [cid] = claims.read(con, [("local", lambda s, p, sc: {"claims": [wrong]})], sid, TEXT, NOW)
    assert con.execute("SELECT status FROM learn_claims WHERE claim_id=?", [cid]).fetchone()[0] == "untestable"
    assert claims.fits("stocks near their 52-week high earn more", "", "cross_section", {"signal": "high_52w"})
    assert not claims.fits("old news filtered by an LLM", "", "cross_section", {"signal": "high_52w"})
    assert not claims.fits("returns are not influenced by the January effect", "", "calendar", {"effect": "january"})
    assert claims.fits("High volatility stocks earn more.", "We did not find a low volatility anomaly; the high volatility "
                       "quintile gives high returns.", "cross_section", {"signal": "volatility_12m"})


def test_a_registered_claim_that_does_not_fit_is_withdrawn(con, tmp_path):
    sid = _source(con, tmp_path)
    [cid] = claims.read(con, [("local", lambda s, p, sc: {"claims": [CLAIM]})], sid, TEXT, NOW)
    claims.register(con, cid, tmp_path / "proto", NOW)
    con.execute("UPDATE learn_claims SET claim='LLM news filters', quote='' WHERE claim_id=?", [cid])
    assert claims.test(con, cid, tmp_path, NOW, run=lambda *a: 1 / 0) == "withdrawn"


def test_a_failed_claim_has_no_live_feature(con, tmp_path):
    sid = _source(con, tmp_path)
    [cid] = claims.read(con, [("local", lambda s, p, sc: {"claims": [CLAIM]})], sid, TEXT, NOW)
    claims.register(con, cid, tmp_path / "proto", NOW)
    claims.test(con, cid, tmp_path, NOW, run=lambda *a: {"decision": "fail", "why": "validation: t 0.4"})
    assert live.current(con, ("finding",)) == []
    assert con.execute("SELECT status FROM learn_claims WHERE claim_id=?", [cid]).fetchone()[0] == "failed"


# --- the record: proposals --------------------------------------------------------------------------------------------

def _suggestions(con, kind, good, n, model="claude-opus-5-5", answer="none"):
    from pflab.pm.store import next_id
    for k in range(n):
        sid = next_id(con, "hq_suggestions", "sug_id")
        con.execute("INSERT INTO hq_suggestions (sug_id, model, made_at, kind, text, horizon_days, shadow, answer, outcome, "
                    "scored_at) VALUES (?,?,?,?,?,?,?,?,?,?)", [sid, model, NOW - timedelta(days=60), kind, "x", 30, False,
                                                                answer, "good" if k < good else "bad", NOW])


def test_wilson_interval():
    lo, hi = record.wilson(5, 25)
    assert 0.08 < lo < 0.1 and 0.38 < hi < 0.41


def test_small_numbers_no_lesson_then_lesson_applied(con):
    _suggestions(con, "add", 3, 19)
    assert record.suggestion_rules(con, "claude-opus-5-5") == []          # 19: a count, not a conclusion
    _suggestions(con, "add", 0, 6)                                          # now 3 of 25
    [p] = record.suggestion_rules(con, "claude-opus-5-5")
    assert p["kind"] == "lesson" and p["passed"] and "3 of 25" in p["text"]
    pid = record.keep(con, p, NOW)
    assert con.execute("SELECT status FROM learn_proposals WHERE prop_id=?", [pid]).fetchone()[0] == "applied"
    assert "3 of 25" in live.brain_text(con)
    assert record.keep(con, p, NOW) is None                                 # the same lesson is not kept twice


def test_proposal_to_investor_then_his_yes_applies(con):
    p = record._p("daily_cap", "tell_investor", "lower the messages to 2 a day", {"n": 25}, 25, "rule", True, "2", "investor")
    pid = record.keep(con, p, NOW)
    q = con.execute("SELECT q_id, text FROM questions WHERE subject_key=?", [f"learner:prop:{pid}"]).fetchone()
    assert "Answer yes" in q[1]
    from pflab.agents import questions as qs
    qs.answer(con, q[0], "Yes, do it", NOW)
    assert record.answers(con, NOW)["applied"] == 1
    assert tl.daily_cap(con, "tell_investor") == 2 and tl.daily_cap(con, "ask_investor") == tl.DAILY["ask_investor"]


def test_his_no_declines(con):
    pid = record.keep(con, record._p("instruction", "brain", "Start every morning review from the tax plan.", {}, 0, "model",
                                     True, None, "investor"), NOW)
    from pflab.agents import questions as qs
    qs.answer(con, con.execute("SELECT q_id FROM learn_proposals WHERE prop_id=?", [pid]).fetchone()[0], "no", NOW)
    assert record.answers(con, NOW)["declined"] == 1 and live.current(con, ("instruction",)) == []


def test_record_due_weekly_or_on_outcomes(con):
    assert record.due(con, NOW) == "weekly"
    assert record.due(con, NOW - timedelta(days=1)) is None                 # a Friday, nothing new
    _suggestions(con, "hold", 10, 20)
    assert record.due(con, NOW - timedelta(days=1)) == "outcomes"


# --- the cycle ------------------------------------------------------------------------------------------------------------

def test_cycle_end_to_end_without_network(con, tmp_path, monkeypatch):
    rt = _desk(con, tmp_path)
    (tmp_path / "data").mkdir()
    d = tmp_path / "repo" / "drop" / "learn"
    d.mkdir(parents=True)
    (d / "paper.txt").write_text(TEXT, encoding="utf-8")
    monkeypatch.setattr(run, "drafts", lambda rt, paid: [("local", lambda s, p, sc: {"claims": [CLAIM]} if "claims" in sc
                                                           ["properties"] else {"testable": True, "why": "ok"})])
    monkeypatch.setattr(tp, "run", lambda root, t, prm, threshold_dev=2.0: {"decision": "pass", "why": "held in both", "development": {},
                                                         "validation": {}})
    monkeypatch.setattr(sources, "collect", lambda con, now, repo, text_dir, **k: {"drop": sources.drop(con, now, repo, text_dir)})
    monkeypatch.setattr(run, "proposal_draft", lambda rt: None)
    from pflab.learner import s76
    monkeypatch.setattr(s76, "register_all", lambda con, proto_dir, now: {})      # S76's own claims are tested in test_s76_learner
    out = run.cycle(rt)
    assert out["collected"] == {"drop": 1} and out["claims"] == 1
    assert list(out["tested"].values()) == ["pass"] and out["record"]["why"] == "weekly"
    assert "Past 12-month winners" in run.status(con) and live.current(con, ("finding",))
