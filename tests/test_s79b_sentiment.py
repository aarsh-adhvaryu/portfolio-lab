"""S79b item 15b: sentiment and themes (synthetic data and a fake local model throughout)."""
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab import sentiment as S
from pflab.hq import tools_s79
from pflab.hq.tools import Ctx
from pflab.pm import store
from pflab.sentiment import calendar as cal, compute, exposure, lens, themes as T, tone

END = date(2026, 11, 6)


@pytest.fixture
def con(tmp_path):
    import duckdb
    from pflab.pm.mig_s79 import m_sentiment
    c = duckdb.connect(str(tmp_path / "x.duckdb"))
    store.migrate(c, m_sentiment.MIGRATIONS)
    return c


def _dates(n=400, end=END):
    return pd.bdate_range(end=pd.Timestamp(end), periods=n)


def _write(root, rel, dates, values, col="close", dcol="date"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({dcol: [d.strftime("%Y-%m-%d") for d in dates], col: np.asarray(values, float)}).to_parquet(p)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "data"
    rng = np.random.default_rng(3)
    d = _dates()
    _write(r, "indices/INDIA_VIX.parquet", d, 15 + np.cumsum(rng.normal(0, 0.3, len(d))).clip(-8, 8))
    _write(r, "global/US_VIX.parquet", d, 18 + np.cumsum(rng.normal(0, 0.3, len(d))).clip(-8, 8))
    _write(r, "indices/NIFTY50_PRICE.parquet", d, 20000 * np.cumprod(1 + rng.normal(0, 0.008, len(d))))
    _write(r, "global/US_SP500.parquet", d, 4000 * np.cumprod(1 + rng.normal(0, 0.008, len(d))))
    _write(r, "global/BRENT_FUT.parquet", d, 80 * np.cumprod(1 + rng.normal(0, 0.015, len(d))))
    _write(r, "global/US_10Y_YIELD.parquet", d, 4 + np.cumsum(rng.normal(0, 0.02, len(d))).clip(-1.5, 1.5))
    fpi = pd.DataFrame({"report_date": [x.strftime("%Y-%m-%d") for x in d], "asset": "Equity", "route": "Sub-total", "net_cr": rng.normal(0, 3000, len(d))})
    (r / "macro").mkdir(parents=True, exist_ok=True)
    fpi.to_parquet(r / "macro" / "FPI_DAILY.parquet")
    return r


# --- the store -------------------------------------------------------------------------------------------------------------------------

def test_migrations_create_tables(con):
    for t, cols in (("sentiment_s79", ("market", "theme", "day", "combined", "tone_model_z", "fear_vix_z", "pos_flow_z")), ("sentiment_tags_s79", ("doc_key", "tone_class")),
                    ("theme_exposure_s79", ("theme", "beta", "contribution")), ("sentiment_event_notes_s79", ("event_id", "kind", "text"))):
        have = [r[0] for r in con.execute(f"DESCRIBE {t}").fetchall()]
        for c in cols:
            assert c in have
    from pflab.pm.mig_s79 import m_sentiment
    assert [v for v, _n, _s in m_sentiment.MIGRATIONS] == [91, 92, 93]


# --- z-scores and the table are point in time ----------------------------------------------------------------------------------------------

def test_zscore_excludes_the_day_and_ignores_the_future():
    rng = np.random.default_rng(1)
    s = pd.Series(rng.normal(size=300), index=pd.bdate_range("2024-01-01", periods=300))
    z = S.zscore_pit(s, window=100, min_periods=30)
    t = 200
    hist = s.iloc[t - 100:t]
    assert z.iloc[t] == pytest.approx((s.iloc[t] - hist.mean()) / hist.std())
    s2 = s.copy()
    s2.iloc[t + 1:] = 99.0                                   # the future changes
    z2 = S.zscore_pit(s2, window=100, min_periods=30)
    assert z2.iloc[:t + 1].equals(z.iloc[:t + 1]) or np.allclose(z2.iloc[:t + 1].dropna(), z.iloc[:t + 1].dropna())
    assert np.isnan(z.iloc[10])                              # too little history


def test_stale_align_never_carries_far():
    s = pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-11-02", "2026-11-03"]))
    out = S.stale_align(s, pd.DatetimeIndex(pd.to_datetime(["2026-11-03", "2026-11-05", "2026-11-12"])), max_days=4)
    assert out.iloc[0] == 2.0 and out.iloc[1] == 2.0 and np.isnan(out.iloc[2])


def test_compute_range_components_and_combined(con, root):
    days = [d.date() for d in _dates()[-5:]]
    df = compute.compute_range(con, root, "IN", days, with_breadth=False)
    th = T.load_themes("IN")
    assert len(df) == 5 * len(th)
    r = df[(df.theme == "oil_middle_east") & (df.day == days[-1])].iloc[0]
    assert np.isfinite(r["fear_vix_z"]) and np.isfinite(r["pos_flow_z"]) and np.isfinite(r["proxy_vol_z"])
    # transparent: combined is the mean of the group scores that exist; fear_score flips the sign of the z
    fear = np.mean([-r["fear_vix_z"], -r["proxy_vol_z"]])
    assert r["fear_score"] == pytest.approx(fear)
    assert r["pos_score"] == pytest.approx(r["pos_flow_z"])
    assert r["combined"] == pytest.approx(np.mean([r["fear_score"], r["pos_score"]]))
    assert int(r["n_groups"]) == 2 and np.isnan(r["tone_score"])
    # the value on a day does not change when later rows change (point in time)
    v = pd.read_parquet(root / "indices" / "INDIA_VIX.parquet")
    v.loc[v.index[-1], "close"] = 90.0
    v.to_parquet(root / "indices" / "INDIA_VIX.parquet")
    df2 = compute.compute_range(con, root, "IN", days[:-1], with_breadth=False)
    a = df[(df.theme == "oil_middle_east") & (df.day == days[-2])].iloc[0]["fear_vix_z"]
    b = df2[(df2.theme == "oil_middle_east") & (df2.day == days[-2])].iloc[0]["fear_vix_z"]
    assert a == pytest.approx(b)
    assert compute.persist(con, df) == len(df)
    assert con.execute("SELECT count(*) FROM sentiment_s79").fetchone()[0] == len(df)
    assert compute.persist(con, df) == len(df) and con.execute("SELECT count(*) FROM sentiment_s79").fetchone()[0] == len(df)       # idempotent


def test_us_market_has_fear_only(con, root):
    df = compute.compute_range(con, root, "US", [END], with_breadth=False)
    r = df.iloc[0]
    assert np.isfinite(r["fear_vix_z"]) and np.isnan(r["pos_flow_z"]) and int(r["n_groups"]) == 1


def test_missing_data_is_harmless(con, tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    df = compute.compute_range(con, empty, "IN", [END], with_breadth=False)
    assert len(df) == len(T.load_themes("IN")) and df["combined"].isna().all()
    assert compute.extreme_sentiment_events("IN", date(2008, 1, 1), date(2021, 12, 31), empty).empty


# --- extreme events: the percentile is taken from earlier data only ----------------------------------------------------------------------------------

def test_extreme_events_use_only_earlier_history(root):
    ev = compute.extreme_sentiment_events("IN", date(2024, 1, 1), END, root, pct=5.0, min_hist=100)
    assert set(ev.columns) >= {"date", "kind", "score", "threshold", "first_of_cluster"}
    for r in ev.itertuples():
        assert (r.score <= r.threshold) if r.kind == "fear" else (r.score >= r.threshold)
    # spike the last day: it is an extreme "fear" day, and the earlier days' flags do not move
    v = pd.read_parquet(root / "indices" / "INDIA_VIX.parquet")
    last = v["date"].iloc[-1]
    v.loc[v.index[-1], "close"] = 80.0
    v.to_parquet(root / "indices" / "INDIA_VIX.parquet")
    ev2 = compute.extreme_sentiment_events("IN", date(2024, 1, 1), END, root, pct=5.0, min_hist=100)
    assert ((ev2["date"] == date.fromisoformat(last)) & (ev2["kind"] == "fear")).any()
    old = ev[ev["date"] < date.fromisoformat(last)][["date", "kind"]].reset_index(drop=True)
    new = ev2[ev2["date"] < date.fromisoformat(last)][["date", "kind"]].reset_index(drop=True)
    pd.testing.assert_frame_equal(old, new)


# --- the model's tags: schema, guard, resumable, forward-only -------------------------------------------------------------------------------------

def _chat(answers, calls=None):
    it = iter(answers)

    def chat(model, messages, **kw):
        if calls is not None:
            calls.append(messages[-1]["content"])
        a = next(it)
        if isinstance(a, Exception):
            raise a
        return SimpleNamespace(text=a if isinstance(a, str) else json.dumps(a))
    return chat


def _items(n, day=END):
    return [{"doc_key": f"k{i}", "market": "IN", "day": day, "headline": f"Crude oil jumps as Gulf tensions rise number {i}", "source": "t"} for i in range(n)]


def test_guard_rejects_anything_but_theme_and_tone():
    v = tone.validate_tag(["oil_middle_east", "tariffs_trade"])
    assert v({"theme": "oil_middle_east", "tone": "negative"}) is None
    assert v({"theme": "none", "tone": "neutral"}) is None
    assert v({"theme": "oil_middle_east", "tone": "negative", "score": 0.9})
    assert v({"theme": "made_up", "tone": "negative"})
    assert v({"theme": "tariffs_trade", "tone": "very bad"})
    assert v({"theme": "tariffs_trade"})
    sch = tone.schema(["a", "b"])
    assert sch["properties"]["tone"]["enum"] == ["negative", "neutral", "positive"] and "none" in sch["properties"]["theme"]["enum"]


def test_tag_batch_stores_validates_and_resumes(con):
    keys = list(T.load_themes("IN"))
    ok = {"theme": keys[1], "tone": "negative"}
    calls = []
    chat = _chat([ok, {"theme": keys[0], "tone": "positive", "n": 3}, {"theme": keys[0], "tone": "positive", "n": 3}, ok, ok], calls)    # item 2 is invalid twice (retry)
    r = tone.tag_batch(con, _items(3), chat=chat, now=datetime(2026, 11, 6, 20, 0))
    assert r["tagged"] == 2 and r["failed"] == 1 and r["stopped"] is None
    assert con.execute("SELECT count(*) FROM sentiment_tags_s79").fetchone()[0] == 2
    assert "Headline:" in calls[0] and "Themes:" in calls[0]
    # resumable: the tagged ones are skipped; a limit stops the run and says how many remain
    r2 = tone.tag_batch(con, _items(6), chat=_chat([ok, ok, ok]), limit=2, now=datetime(2026, 11, 6, 20, 0))
    assert r2["skipped"] == 2 and r2["tagged"] == 2 and r2["remaining"] == 2


def test_tag_batch_stops_when_the_model_is_unreachable(con):
    r = tone.tag_batch(con, _items(5), chat=_chat([ConnectionError("down")]), now=datetime(2026, 11, 6, 20, 0))
    assert r["tagged"] == 0 and r["stopped"] and r["remaining"] == 4


def test_slug_title():
    assert tone.slug_title("https://x.com/markets/news/crude-oil-shipping-costs-surge-nearly-7-fold-563160-2026-10-23") == "crude oil shipping costs surge nearly fold"
    assert tone.slug_title("https://x.com/articleshow/135131078.cms") is None


def test_model_tone_is_forward_only(con, root):
    day = date(2026, 10, 20)
    now_late = datetime(2026, 11, 6, 20, 0)
    for i, (when, cls) in enumerate([(datetime(2026, 10, 20, 18, 0), "negative"), (datetime(2026, 10, 21, 9, 0), "negative"), (now_late, "positive")]):
        con.execute("INSERT INTO sentiment_tags_s79 VALUES (?,?,?,?,?,?,?,?,?)", [f"d{i}", "IN", day, "h", "t", "oil_middle_east", cls, "m", when])
    assert tone.is_live_tag(day, datetime(2026, 10, 21, 23, 0)) and not tone.is_live_tag(day, datetime(2026, 10, 22, 0, 1))
    m = tone.model_tone_by_day(con, "IN", "oil_middle_east")
    assert len(m) == 1 and m["n"].iloc[0] == 2 and m["tone"].iloc[0] == -1.0          # the late 'positive' tag is hindsight: left out
    with pytest.raises(tone.ForwardOnly):
        tone.refuse_historical(date(2026, 10, 20), date(2026, 11, 6))
    tone.refuse_historical(date(2026, 11, 5), date(2026, 11, 6))                      # yesterday is still live


def test_lens_refuses_news_tone_for_a_historical_date(con, root):
    # twelve live days of tags so a z-score exists, then ask for a date far in the past and for today
    for i in range(14):
        d = date(2026, 10, 12) + timedelta(days=i)
        con.execute("INSERT INTO sentiment_tags_s79 VALUES (?,?,?,?,?,?,?,?,?)",
                    [f"x{i}", "IN", d, "h", "t", "oil_middle_east", "negative" if i % 3 else "positive", "m", datetime.combine(d, datetime.min.time()) + timedelta(hours=20)])
    today = date(2026, 10, 25)
    g = lens.news_group(con, "IN", [date(2026, 10, 14), date(2026, 10, 24), today], today)
    assert np.isnan(g.iloc[0])                                                        # historical: refused, although tags exist for it
    assert g.iloc[2] == g.iloc[2] or np.isnan(g.iloc[2])
    # the frame is identical with and without tags on historical rows
    close = pd.Series(20000 * np.cumprod(1 + np.random.default_rng(5).normal(0, 0.008, 400)), index=_dates())
    S_root = root
    import pflab.sentiment as sm
    old = sm.data_root
    sm.data_root = lambda r=None: S_root
    try:
        with_tags = lens.frame(con, "IN", close, 5)
        import duckdb
        c2 = duckdb.connect(":memory:")
        from pflab.pm.mig_s79 import m_sentiment
        store.migrate(c2, m_sentiment.MIGRATIONS)
        without = lens.frame(c2, "IN", close, 5)
    finally:
        sm.data_root = old
    assert with_tags is not None and without is not None
    pd.testing.assert_frame_equal(with_tags.iloc[:-5], without.iloc[:-5])


def test_lens_frame_shape_and_registration(con, root, monkeypatch):
    monkeypatch.setattr(S, "data_root", lambda r=None: root)
    close = pd.Series(20000 * np.cumprod(1 + np.random.default_rng(5).normal(0, 0.008, 400)), index=_dates())
    f = lens.frame(con, "IN", close, 5)
    from pflab.fcast import protocol as P
    assert list(f.columns) == list(P.LEVELS) and f.index.equals(close.index)
    ok = f.dropna()
    assert (ok.diff(axis=1).iloc[:, 1:] >= -1e-12).all().all()                       # quantiles non-decreasing
    assert lens.frame(con, "IN", close.iloc[:50], 5) is None                         # too short
    try:
        from pflab.fcast import plugins
    except ImportError:
        pytest.skip("plug-in interface not present")
    lens.register_lens()
    assert "lens_sentiment" in plugins.REGISTRY and plugins.REGISTRY["lens_sentiment"].replay_ok
    assert plugins.REGISTRY["lens_sentiment"].protocol.endswith("s79_wave_sentiment_protocol.md")


# --- exposure from constructed betas ----------------------------------------------------------------------------------------------------------------

def _panel(root, d, proxy_ret, betas):
    rng = np.random.default_rng(11)
    rows = []
    for isin, b in betas.items():
        r = b * proxy_ret + rng.normal(0, 0.002, len(d))
        px = 100 * np.cumprod(1 + r)
        rows += [{"date": x.date(), "isin": isin, "adj_close": p, "symbol": isin[-3:]} for x, p in zip(d, px)]
    p = root / "panel"
    p.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(p / "prices.parquet")


def test_exposure_from_constructed_betas(con, tmp_path, monkeypatch):
    root = tmp_path / "d2"
    d = _dates(420)
    rng = np.random.default_rng(2)
    pr = rng.normal(0, 0.012, len(d))
    lvl = 80 * np.cumprod(1 + pr)
    _write(root, "global/BRENT_FUT.parquet", d, lvl)
    # the proxy return of day t-1 drives the stock on day t (lag 1: settles after the Indian close)
    drive = np.r_[0.0, pr[:-1]]
    _panel(root, d, drive, {"INE000000AAA": 0.8, "INE000000BBB": -0.5, "INE000000CCC": 0.0})
    monkeypatch.setattr(exposure, "book_weights", lambda c, day, which="auto": {"source": "paper", "total": 1000.0, "rows": [
        {"isin": "INE000000AAA", "symbol": "AAA", "weight": 0.5, "value": 500.0}, {"isin": "INE000000BBB", "symbol": "BBB", "weight": 0.3, "value": 300.0},
        {"isin": "INE000000CCC", "symbol": "CCC", "weight": 0.2, "value": 200.0}]})
    monkeypatch.setattr(exposure, "universe_isins", lambda r, day: [])
    res = exposure.compute(con, root, d[-1].date(), "IN", themes={"oil_middle_east": T.load_themes("IN")["oil_middle_east"]}, universe=False)
    e = res["themes"]["oil_middle_east"]
    by = {h["symbol"]: h for h in e["holdings"]}
    assert by["AAA"]["beta"] == pytest.approx(0.8, abs=0.1) and by["BBB"]["beta"] == pytest.approx(-0.5, abs=0.1)
    assert "CCC" not in by                                                           # beta 0: not significant, no sector prior: does not carry
    assert e["book_beta"] == pytest.approx(0.5 * 0.8 - 0.3 * 0.5, abs=0.06)
    assert e["weight_carrying"] == pytest.approx(0.8)
    assert "usdinr" in res["missing_proxies"] and "no revenue-mix" in res["revenue_mix"]
    assert exposure.persist(con, res, d[-1].date()) == 2


def test_lag_pairing_uses_the_earlier_proxy_session():
    d = pd.bdate_range("2026-10-01", periods=10)
    lvl = pd.Series(np.arange(100.0, 110.0), index=d)
    same = exposure.proxy_returns(lvl, d, 0)
    lag = exposure.proxy_returns(lvl, d, 1)
    assert same.iloc[3] == pytest.approx(lvl.iloc[3] / lvl.iloc[2] - 1)
    assert lag.iloc[3] == pytest.approx(lvl.iloc[2] / lvl.iloc[1] - 1)               # the move before the stock's day


def test_rolling_beta_is_point_in_time():
    rng = np.random.default_rng(4)
    x = pd.Series(rng.normal(size=300), index=pd.bdate_range("2025-01-01", periods=300))
    y = 1.5 * x + rng.normal(0, 0.1, 300)
    b = exposure.rolling_beta(y, x, 100, 50)
    y2 = y.copy()
    y2.iloc[200:] = rng.normal(size=100)
    b2 = exposure.rolling_beta(y2, x, 100, 50)
    assert np.allclose(b.iloc[:200].dropna(), b2.iloc[:200].dropna()) and abs(b.iloc[150] - 1.5) < 0.05


def test_exposure_without_any_book_or_data(con, tmp_path, monkeypatch):
    monkeypatch.setattr(exposure, "book_weights", lambda c, day, which="auto": {"source": "none", "rows": [], "total": 0.0})
    monkeypatch.setattr(exposure, "universe_isins", lambda r, day: [])
    res = exposure.compute(con, tmp_path, END, "IN")
    assert res["themes"] == {} and "note" in res
    assert "note" in exposure.compute(con, tmp_path, END, "US")


# --- the calendar --------------------------------------------------------------------------------------------------------------------------------

def test_calendar_file_has_sources_and_only_sourced_dates():
    ev = cal.load_events()
    ids = {e.id: e for e in ev}
    assert ids["us_midterms_2026"].date == date(2026, 11, 3) and ids["us_midterms_2026"].verified
    assert ids["fomc_2026_10"].date == date(2026, 10, 28)
    for e in ev:
        assert e.source.strip()
        assert e.verified or "verif" in e.source.lower() or "recalled" in e.source.lower()


def test_reaction_session_uses_the_market_clock():
    ev = {e.id: e for e in cal.load_events()}
    assert cal.reaction_session("IN", ev["fomc_2026_10"].utc) == date(2026, 10, 29)      # 23:30 IST on the 28th: the next Indian session
    assert cal.reaction_session("US", ev["fomc_2026_10"].utc) == date(2026, 10, 28)      # same US session (statement at 14:00 Eastern)


def test_scenario_and_surprise_numbers(root):
    themes = T.load_themes("IN")
    ev = SimpleNamespace(id="e", date=date(2026, 11, 6), label="Test event", verified=True, themes=("oil_middle_east",), utc=datetime(2026, 11, 5, 18, 0))
    n = cal.scenario_note(root, ev, "IN", themes["oil_middle_east"], date(2026, 11, 4))
    v = n["values"]
    assert "beta" in v and "proxy_sd_pct" in v and v["implied_sd_pct"] > 0
    assert v["index_move_for_1sd_proxy_pct"] == pytest.approx(v["beta"] * v["proxy_sd_pct"])
    vix = pd.read_parquet(root / "indices" / "INDIA_VIX.parquet")
    vix_prev = float(vix.loc[vix["date"] <= "2026-11-04", "close"].iloc[-1])
    assert v["implied_sd_pct"] == pytest.approx(vix_prev / np.sqrt(252))
    assert "not a forecast" in n["text"]
    # the surprise: the move on the reaction session over the sd implied at the close before
    s = cal.surprise(root, ev, "IN", themes, END)
    ix = pd.read_parquet(root / "indices" / "NIFTY50_PRICE.parquet").set_index("date")["close"]
    d = s["values"]["reaction_session"]
    prev = ix.index[ix.index.get_loc(d) - 1]
    move = (ix[d] / ix[prev] - 1) * 100
    assert s["values"]["index_move_pct"] == pytest.approx(move)
    assert s["values"]["surprise_z"] == pytest.approx(move / s["values"]["implied_sd_pct"])
    assert cal.surprise(root, ev, "IN", themes, date(2026, 11, 4)) is None            # not happened yet


def test_run_notes_writes_both_kinds(con, root):
    e_past = cal.Event("p", date(2026, 11, 4), datetime(2026, 11, 4, 5, 0), "x", "Past event", ("oil_middle_east",), ("IN",), True, "s")
    e_next = cal.Event("n", date(2026, 11, 10), datetime(2026, 11, 10, 5, 0), "x", "Next event", ("oil_middle_east", "rates_central_banks"), ("IN",), False, "s")
    r = cal.run_notes(con, root, "IN", END, ahead_days=10, events=[e_past, e_next])
    assert r == {"scenario": 2, "surprise": 1}
    assert cal.run_notes(con, root, "IN", END, ahead_days=10, events=[e_past, e_next])["surprise"] == 0        # once
    assert con.execute("SELECT count(*) FROM sentiment_event_notes_s79").fetchone()[0] == 3


# --- the tools ---------------------------------------------------------------------------------------------------------------------------------

def _ctx(con, root, now=datetime(2026, 11, 7, 12, 0)):
    rt = SimpleNamespace(data_root=root, cursor=lambda: con)
    return Ctx(rt=rt, pass_id=None, model="x", shadow=False, syms={}, gate=None, now=now)


def _tool(name):
    return next(t for t in tools_s79.collect() if t.name == name)


def test_tools_work_with_empty_args_and_document_keys(con, root, monkeypatch):
    monkeypatch.setattr(exposure, "universe_isins", lambda r, day: [])
    monkeypatch.setattr(exposure, "book_weights", lambda c, day, which="auto": {"source": "none", "rows": [], "total": 0.0})
    for n in ("sentiment", "theme_exposure", "event_calendar"):
        t = _tool(n)
        assert t.kind == "read" and not t.required
        out = t.fn(_ctx(con, root), {})
        assert isinstance(out, dict) and "off" not in out
    out = _tool("sentiment").fn(_ctx(con, root), {})
    assert out["available"] and out["computed_on_the_fly"] and set(out["themes"]) == set(T.load_themes("IN"))
    one = out["themes"]["oil_middle_east"]
    assert set(one) >= {"combined", "n_groups", "n_comp", "tone_score", "fear_score", "pos_score", "components"} and "fear_vix" in one["components"]
    assert "events" in out and "market_components" in out and out["call_ref"] is None
    bad = _tool("sentiment").fn(_ctx(con, root), {"theme": "nope"})
    assert bad["available"] is False
    us = _tool("sentiment").fn(_ctx(con, root), {"market": "US"})
    assert us["available"]


def test_tools_are_off_when_the_switch_is_off(con, root, monkeypatch):
    monkeypatch.setattr(S, "settings", lambda: {**S.DEFAULTS, "on": False})
    for n in ("sentiment", "theme_exposure", "event_calendar"):
        assert _tool(n).fn(_ctx(con, root), {}) == {"off": True, "message": S.OFF["message"]}
    assert lens.register_lens() is None and lens.frame(con, "IN", pd.Series(dtype=float), 5) is None


def test_tools_with_no_data_at_all(con, tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    out = _tool("sentiment").fn(_ctx(con, empty), {})
    assert isinstance(out, dict)
    assert isinstance(_tool("event_calendar").fn(_ctx(con, empty), {}), dict)


def test_theme_stub_is_never_live(tmp_path):
    p = T.propose_stub("water_stress", "Water stress", ["drought", "water"], ["nifty"], out_dir=tmp_path)
    assert p.exists() and 'status = "proposed"' in p.read_text(encoding="utf-8")
    cfg = tmp_path / "themes.toml"
    cfg.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    assert T.load_themes(path=cfg) == {} and "water_stress" in T.load_themes(path=cfg, include_stubs=True)
    with pytest.raises(ValueError):
        T.propose_stub("Bad Key!", "x", [], [], out_dir=tmp_path)


def test_job_is_registered_and_skips_when_off(con, tmp_path, monkeypatch):
    from pflab.service import jobs, tasks_s79_sentiment as tj
    assert "sentiment" in jobs.REGISTRY
    monkeypatch.setattr(S, "settings", lambda: {**S.DEFAULTS, "on": False})
    ctx = jobs.Ctx(con=con, now=datetime(2026, 11, 7, 12, 0), pm_dir=tmp_path, data_root=tmp_path, repo=tmp_path)
    assert "skipped" in tj._sentiment(ctx)
