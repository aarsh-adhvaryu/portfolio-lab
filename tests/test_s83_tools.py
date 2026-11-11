"""S83 L2: what the strategist may look at to choose (`lab/screen.py`), the US floor (`us/picks_floor.py`), the daily US collection of held and picked names. Synthetic data, no network:
the SEC and Yahoo are fakes."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab.data import us_prices
from pflab.lab import screen, tools
from pflab.pm import store as pmstore
from pflab.us import picks_floor as pf

DAY = date(2026, 11, 10)
NOW = datetime(2026, 11, 10, 20, 0)
SESS = [d.date() for d in pd.bdate_range(end=pd.Timestamp(DAY), periods=320)]
FUTURE = date(2026, 11, 12)
LATER = [d.date() for d in pd.bdate_range(FUTURE, periods=45)]


def isin(tag: str) -> str:
    return f"INE{tag:0>5}01"[:12].ljust(12, "0")


def _curve(kind: str, k: int = 0) -> np.ndarray:
    i = np.arange(len(SESS), dtype=float)
    rng = np.random.default_rng(k + 7)
    if kind == "up":
        return 100 * 1.002 ** i
    if kind == "down":
        return 100 * 0.998 ** i
    if kind == "wild":
        return 100 * np.cumprod(1 + np.where(np.arange(len(SESS)) % 2 == 0, 0.05, -0.045))
    return 100 * np.cumprod(1 + 0.0004 * (k % 5 - 2) + rng.normal(0, 0.006, len(SESS)))


# name -> (kind, daily traded value in rupees)
NAMES = {"UPCO": ("up", 2e8), "DOWNCO": ("down", 2e8), "WILDCO": ("wild", 2e8), "THINCO": ("up", 1e7), "FLAGCO": ("up", 2e8)}
for _k in range(55):
    NAMES[f"N{_k:02d}"] = ("walk", 1.5e8)


def _bhav_rows(day: date, extra=()):
    rows = []
    for sym, (kind, tv) in NAMES.items():
        cl = _curve(kind, int(sym[1:]) if sym.startswith("N") else 0)[SESS.index(day) if day in SESS else -1]
        rows.append({"date": day, "symbol": sym, "series": "EQ", "isin": isin(sym), "open": cl, "high": cl, "low": cl, "close": cl, "prev_close": cl, "volume": int(tv / cl), "turnover": tv, "trades": 1000})
    for sym, tv in extra:
        rows.append({"date": day, "symbol": sym, "series": "EQ", "isin": isin(sym), "open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0, "prev_close": 50.0, "volume": 1, "turnover": tv, "trades": 1})
    return pd.DataFrame(rows)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "data"
    (r / "bhavcopy" / "2026").mkdir(parents=True)
    (r / "bhavcopy" / "2027").mkdir(parents=True)
    for d in SESS[-70:]:
        df = _bhav_rows(d)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df.to_parquet(r / "bhavcopy" / "2026" / f"{d}.parquet", index=False)
    for d in LATER:                                                                      # files dated AFTER the decision day: never read when asking for DAY
        pd.DataFrame([{"date": d, "symbol": "LATECO", "series": "EQ", "isin": isin("LATECO"), "open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0, "prev_close": 50.0, "volume": 1000000,
                       "turnover": 9e8, "trades": 1}]).to_parquet(r / "bhavcopy" / "2026" / f"{d}.parquet" if d.year == 2026 else r / "bhavcopy" / "2027" / f"{d}.parquet", index=False)
    (r / "index_membership").mkdir()
    pd.DataFrame([{"index": "NIFTY500", "isin": isin(s), "symbol": s, "from_date": date(2020, 1, 1), "to_date": None} for s in ("UPCO", "DOWNCO", "N00", "N01")]).to_parquet(r / "index_membership" / "NIFTY500.parquet", index=False)
    (r / "red_flag_events").mkdir()
    pd.DataFrame([{"isin": isin("FLAGCO"), "scrip_code": "500009", "company": "Flag Co", "flag": "AUDITOR_RESIGNATION", "key_dt": pd.Timestamp("2026-08-01 10:00"), "key_source": "DissemDT",
                   "usable_from": date(2026, 8, 1), "headline": "auditor resigned", "category": "Others", "subcategory": None},
                  {"isin": isin("UPCO"), "scrip_code": "500001", "company": "Up Co", "flag": "RESULTS_DELAY", "key_dt": pd.Timestamp("2026-11-12 10:00"), "key_source": "DissemDT",
                   "usable_from": FUTURE, "headline": "delay", "category": "Others", "subcategory": None}]).to_parquet(r / "red_flag_events" / "events.parquet", index=False)
    (r / "bse_scrip_isin").mkdir()
    pd.DataFrame([{"scrip_code": "500001", "isin": isin("UPCO"), "valid_from": pd.Timestamp("1990-01-01"), "valid_to": pd.Timestamp("2999-12-31"), "last_seen": pd.Timestamp("2026-10-01")}]
                 ).to_parquet(r / "bse_scrip_isin" / "map.parquet", index=False)
    (r / "bse_shareholding").mkdir()
    pd.DataFrame([{"scrip_code": "500001", "quarter_end": date(2026, q[0], q[1]), "status": "ok", "promoter_pct": q[2], "pledged_pct_of_promoter": 1.0, "shares_outstanding_reported": 1e7, "shares_outstanding_derived": None}
                  for q in ((3, 31, 50.0), (6, 30, 52.5), (12, 31, 99.0))]).to_parquet(r / "bse_shareholding" / "summary.parquet", index=False)            # the Dec quarter is in the future
    pd.DataFrame([{"scrip_code": "500001", "quarter_end": date(2026, 3, 31), "inst_pct": 20.0, "mf_pct": 5.0, "fpi_pct": 8.0, "status": "ok"},
                  {"scrip_code": "500001", "quarter_end": date(2026, 6, 30), "inst_pct": 24.0, "mf_pct": 6.0, "fpi_pct": 9.0, "status": "ok"}]).to_parquet(r / "bse_shareholding" / "institutions.parquet", index=False)
    return r


@pytest.fixture
def con(tmp_path, root, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    c = pmstore.connect(tmp_path / "l.duckdb")
    rows = []
    for sym, (kind, _tv) in NAMES.items():
        cl = _curve(kind, int(sym[1:]) if sym.startswith("N") else 0)
        for d, x in zip(SESS, cl):
            rows.append((isin(sym), d, float(x), "EQ", "nse_bhavcopy", NOW))
    rows.append((isin("UPCO"), FUTURE, 99999.0, "EQ", "nse_bhavcopy", NOW))             # a close dated after the decision day
    rows += [(isin("LATECO"), d, 50.0, "EQ", "nse_bhavcopy", NOW) for d in LATER]
    frame = pd.DataFrame(rows, columns=["isin", "date", "close", "series", "source", "fetched_at"])
    c.register("tmp_prices", frame)
    c.execute("INSERT INTO prices SELECT isin, CAST(date AS DATE), close, series, source, fetched_at FROM tmp_prices")
    c.unregister("tmp_prices")
    fc_now = NOW
    from pflab.quant import forecast as fc
    fc._insert(c, fc_now, use="price63", subject=isin("UPCO"), asof=DAY, target=DAY + timedelta(days=90), inputs_last=DAY, model="stats_plain", q10=90.0, q50=100.0, q90=120.0)
    fc._insert(c, fc_now, use="price63", subject=isin("UPCO"), asof=FUTURE, target=DAY + timedelta(days=90), inputs_last=DAY, model="stats_plain", q10=1.0, q50=2.0, q90=3.0)
    c.execute("INSERT INTO storylines_s80 (storyline_id, market, claim, kind, direction, subject, opened_on, status, prior, probability, influence, created_by) VALUES "
              "(1, 'IN', 'Rising demand lifts Up Co and its peers', 'market', 1, 'NIFTY500_TRI', ?, 'open', 0.5, 0.7, 0.5, 'test')", [DAY])
    c.execute("INSERT INTO storyline_exposure_s80 VALUES (1, ?, 0.6, 'test', ?)", [isin("UPCO"), DAY])
    return c


def _screen(con, root, filters=None, sort="momentum_126", n=40, **kw):
    return screen.screen_stocks(con, NOW, "IN", filters, sort, n, root=root, **kw)


# --- the India screen -----------------------------------------------------------------------------------------------------------------------

def test_screen_returns_at_most_40_rows_even_when_more_are_asked_and_more_pass(con, root):
    r = _screen(con, root, n=500)
    assert len(r["rows"]) == screen.MAX_ROWS == 40
    assert r["universe"] > 40 and r["market"] == "IN" and r["asof"] == str(DAY)


def test_india_row_fields_are_present_and_come_from_the_store(con, root):
    r = _screen(con, root, {"symbols": ["UPCO"]})
    row = r["rows"][0]
    for k in ("symbol", "isin", "sector", "indices", "price", "return_63d_pct", "return_126d_pct", "return_252d_pct", "vs_200dma_pct", "below_200dma", "volatility_250d_pct", "from_52w_high_pct",
              "traded_value_inr", "market_cap_cr", "shareholding", "bulk_block_deals_90d", "deals_label", "events", "red_flags", "price_range_63d", "storylines", "fundamentals", "says"):
        assert k in row, k
    assert row["symbol"] == "UPCO" and row["indices"] == ["NIFTY500"] and row["below_200dma"] is False
    assert row["return_126d_pct"] == pytest.approx(((1.002 ** 319) / (1.002 ** (319 - 126)) - 1) * 100, abs=0.2)
    assert row["traded_value_inr"] == 200_000_000 and row["deals_label"].startswith("context, never a signal")
    sh = row["shareholding"]
    assert sh["as_of_quarter"] == "2026-06-30" and sh["promoter_pct"] == 52.5 and sh["promoter_change_pp"] == 2.5       # the Dec-2026 quarter is not yet public
    assert sh["fpi_pct"] == 9.0 and sh["fpi_change_pp"] == 1.0 and sh["dii_pct"] == 15.0 and sh["dii_change_pp"] == 3.0
    assert row["market_cap_cr"] == round(1e7 * row["price"] / 1e7)                                                  # shares x close, in rupees crore
    assert row["price_range_63d"]["low"] == 90.0 and row["price_range_63d"]["high"] == 120.0                         # the range made after the day is not used
    assert [s["id"] for s in row["storylines"]] == [1]
    assert row["red_flags"] == []                                                                                    # UPCO's flag is usable only after the day


def test_a_row_dated_after_the_decision_day_never_appears(con, root):
    r = _screen(con, root, n=500)
    syms = {x["symbol"] for x in r["rows"]}
    assert "LATECO" not in syms                                                                                    # its only bhavcopy and close are dated after the day
    up = _screen(con, root, {"symbols": ["UPCO"]})["rows"][0]
    assert up["price"] < 1000 and up["price_date"] == str(DAY)                                                       # the 99,999 close of 2026-11-12 is ignored
    assert up["shareholding"]["promoter_pct"] != 99.0                                                                # the December quarter is not public yet
    later = screen.screen_stocks(con, datetime(2027, 1, 20, 20, 0), "IN", {"symbols": ["LATECO"]}, root=root)           # the same data asked for on a later day: now the rows exist
    assert [x["symbol"] for x in later["rows"]] == ["LATECO"]


def test_features_use_only_rows_up_to_the_day():
    idx = pd.date_range("2025-01-01", periods=300, freq="B")
    c = pd.Series(np.linspace(100, 200, 300), index=idx)
    f_all = screen.features(c)
    f_cut = screen.features(c.iloc[:250])
    assert f_all["price"] == pytest.approx(200.0) and f_cut["price"] == pytest.approx(c.iloc[249])
    assert f_cut["ret_252"] is None and f_all["ret_252"] is not None                                                  # too little history is None, never a guess
    assert screen.features(pd.Series(dtype=float))["price"] is None


def test_filters_are_honoured(con, root, monkeypatch):
    r = _screen(con, root, n=500)
    syms = {x["symbol"] for x in r["rows"]}
    assert "THINCO" not in syms                                                                                    # Rs 1 crore a day is under the Rs 5 crore floor
    r = _screen(con, root, {"min_traded_value_inr": 1.8e8}, n=500)
    assert {x["symbol"] for x in r["rows"]} <= {"UPCO", "DOWNCO", "WILDCO", "FLAGCO"}                                  # raising the floor works; lowering it below Rs 5 crore does not
    assert "THINCO" not in {x["symbol"] for x in _screen(con, root, {"min_traded_value_inr": 1.0}, n=500)["rows"]}
    r = _screen(con, root, {"min_momentum": 0.2}, n=500)
    assert r["rows"] and all(x["return_126d_pct"] >= 20 for x in r["rows"])
    r = _screen(con, root, {"max_volatility": 0.10}, n=500)
    assert r["rows"] and all(x["volatility_250d_pct"] <= 10 for x in r["rows"]) and "WILDCO" not in {x["symbol"] for x in r["rows"]}
    r = _screen(con, root, {"in_index": "nifty 500"}, n=500)
    assert {x["symbol"] for x in r["rows"]} == {"UPCO", "DOWNCO", "N00", "N01"}
    r = _screen(con, root, {"exclude_flagged": True}, n=500)
    assert "FLAGCO" not in {x["symbol"] for x in r["rows"]} and "FLAGCO" in {x["symbol"] for x in _screen(con, root, n=500)["rows"]}
    flagged = next(x for x in _screen(con, root, {"symbols": ["FLAGCO"]})["rows"])
    assert flagged["red_flags"][0]["flag"] == "AUDITOR_RESIGNATION"
    monkeypatch.setattr(screen, "_held_isins_in", lambda c: {isin("UPCO")})
    assert "UPCO" not in {x["symbol"] for x in _screen(con, root, {"exclude_held": True}, n=500)["rows"]}
    assert next(x for x in _screen(con, root, {"symbols": ["UPCO"]})["rows"])["held"] is True
    r = _screen(con, root, {"sector": "nothing like this"})
    assert r["rows"] == []
    r = _screen(con, root, {"bogus": 1})
    assert "bogus" in r["note"]


def test_sorts(con, root):
    r = _screen(con, root, {"symbols": ["UPCO", "DOWNCO", "WILDCO"]}, sort="momentum_126")
    assert [x["symbol"] for x in r["rows"]][0] == "UPCO" and r["rows"][-1]["symbol"] in ("DOWNCO", "WILDCO")
    r = _screen(con, root, {"symbols": ["UPCO", "WILDCO"]}, sort="low_volatility")
    assert r["rows"][0]["symbol"] == "UPCO"
    assert "unknown sort" in _screen(con, root, sort="nonsense")["note"]


def test_the_screen_is_logged_and_the_brief_form_is_small_and_valid_json(con, root):
    r = _screen(con, root, n=40, detail="brief")
    assert len(json.dumps(r, default=str)) < screen.BRIEF_LIMIT + 3000
    assert all("isin" not in x for x in r["rows"]) and all(None not in x.values() for x in r["rows"])
    assert con.execute("SELECT count(*), max(n_rows) FROM screen_log_s83 WHERE tool='screen_stocks'").fetchone() == (1, 40)


def test_no_failed_rule_is_presented_as_a_signal(con, root):
    leg = screen.labels_text(screen.rule_verdicts(con))
    assert len(leg["only_reading"]) == 1 and "200-day" in leg["only_reading"][0]
    assert "failed" in leg["rule_tests"]["pe_above_50"] and "passed" in leg["rule_tests"]["below_sma200"]
    assert "signal" in leg["trend_and_momentum"] and "never a signal" in leg["insider_and_bulk_deals"] and "survivorship" in leg["us_history"]
    r = _screen(con, root, n=500)
    labelled = [x for x in r["rows"] if x["labels"]]
    assert labelled and all(x["below_200dma"] and "avoid" in x["labels"][0] for x in labelled)                        # only the one passed rule ever labels a row
    for x in r["rows"]:
        assert not any(w in " ".join(x["labels"]) for w in ("P/E", "momentum", "oversold", "volume spike"))
    # a store that says a rule PASSED is believed, and one that says failed is not turned into a reading
    from pflab.learner import rules
    v = screen.rule_verdicts(con)
    assert v["pe_above_50"]["verdict"] == "failed" and v["below_sma200"]["verdict"] == "passed"
    assert rules.status(con, "below_sma200")["label"] in ("not tested", "passed")


def test_pe_label_for_a_high_pe_says_the_rule_failed(con, root, monkeypatch):
    import pflab.fundamentals.pit as pit
    monkeypatch.setattr(pit, "load", lambda c, s, basis="standalone": pd.DataFrame({"x": [1]}))
    monkeypatch.setattr(pit, "last_quarters", lambda q, s, d: q)
    monkeypatch.setattr(pit, "ratios", lambda q: {"eps_ttm": 1.0, "eps_ttm_yoy": 0.1})
    out = screen.fundamentals_light(con, root, "500001", 80.0, DAY, screen.rule_verdicts(con))
    assert out["pe_ttm"] == 80.0 and "failed" in out["pe_label"] and "not a signal" in out["pe_label"]


# --- the company card -------------------------------------------------------------------------------------------------------------------

def test_company_card_india_has_the_page(con, root):
    c = screen.company_card(con, NOW, "IN", "UPCO", root=root)
    assert c["ok"] and c["isin"] == isin("UPCO") and c["indices"] == ["NIFTY500"]
    assert c["liquidity"]["clears_picks_floor"] is True and c["price"]["range_52w"][1] >= c["price"]["range_52w"][0]
    assert c["rails"]["one_stock_max_pct"] == 10.0 and c["shareholding"]["promoter_pct"] == 52.5
    assert c["storylines"] and c["price_range"]["63"]["middle"] == 100.0 and "labels" in c
    assert screen.company_card(con, NOW, "IN", "NOSUCHSYM", root=root)["ok"] is False


def test_fit_card_drops_the_longest_optional_parts_in_order_and_says_so():
    card = {"symbol": "X", "fundamentals": {"rules_of_thumb": ["a" * 3000], "in_plain_words": ["b" * 3000], "pe_ttm": 20.0}, "recent_announcements": ["c" * 500] * 10, "events": [{"k": 1}] * 5}
    small = screen.fit_card(json.loads(json.dumps(card)), 2500)
    assert len(json.dumps(small)) <= 2500 and small["fundamentals"]["pe_ttm"] == 20.0 and len(small["recent_announcements"]) == 3
    assert small["trimmed_to_fit"][:2] == ["fundamentals.rules_of_thumb", "fundamentals.in_plain_words"]
    untouched = screen.fit_card(json.loads(json.dumps(card)), 10 ** 6)
    assert "trimmed_to_fit" not in untouched


# --- the US floor -----------------------------------------------------------------------------------------------------------------------

def _bars(n=300, price=50.0, volume=1_000_000, end=DAY):
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    close = np.full(n, price) * (1 + 0.0001 * np.arange(n))
    return pd.DataFrame({"date": [d.date() for d in idx], "open": close, "high": close, "low": close, "close": close, "adj_close": close, "volume": float(volume), "dividend": 0.0})


def _put(root, sym, df):
    p = root / "us" / "raw"
    p.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p / f"{sym}.parquet", index=False)


def test_us_floor_refuses_a_4_dollar_stock_and_a_thin_one_and_passes_a_good_one(tmp_path):
    _put(tmp_path, "GOOD", _bars(price=50, volume=1_000_000))                          # about USD 50 million a day
    _put(tmp_path, "CHEAP", _bars(price=4.0, volume=5_000_000))                        # USD 20 million a day but a USD 4 price
    _put(tmp_path, "THIN", _bars(price=50, volume=10_000))                             # USD 0.5 million a day
    _put(tmp_path, "NEW", _bars(n=30, price=50, volume=1_000_000))                     # too few sessions
    _put(tmp_path, "OLD", _bars(price=50, volume=1_000_000, end=DAY - timedelta(days=30)))
    ok = pf.check(None, "GOOD", DAY, tmp_path)
    assert ok["ok"] and ok["price"] > 5 and ok["median_value_usd"] > 2e6 and "clears" in ok["reason"]
    cheap = pf.check(None, "CHEAP", DAY, tmp_path)
    assert not cheap["ok"] and "USD 5" in cheap["reason"] and cheap["price"] < 5
    thin = pf.check(None, "THIN", DAY, tmp_path)
    assert not thin["ok"] and "traded value" in thin["reason"] and thin["median_value_usd"] < 2e6
    assert not pf.check(None, "NEW", DAY, tmp_path)["ok"] and "sessions" in pf.check(None, "NEW", DAY, tmp_path)["reason"]
    assert not pf.check(None, "OLD", DAY, tmp_path)["ok"] and "days before" in pf.check(None, "OLD", DAY, tmp_path)["reason"]
    assert not pf.check(None, "NOSUCH", DAY, tmp_path)["ok"]
    assert pf.check(None, "GOOD", DAY - timedelta(days=500), tmp_path)["ok"] is False                           # point in time: no bars that early


def test_us_floor_is_point_in_time(tmp_path):
    df = _bars(price=50, volume=1_000_000)
    df.loc[df.index[-5:], "volume"] = 1.0                                              # the last five days dry up
    _put(tmp_path, "DRY", df)
    assert pf.check(None, "DRY", DAY, tmp_path)["median_value_usd"] > 2e6              # the median over 60 sessions shrugs five days off
    df2 = _bars(price=3.0, volume=1_000_000)
    df2.loc[df2.index[-3:], "close"] = 60.0                                            # a jump AFTER the day being asked about
    _put(tmp_path, "JUMP", df2)
    assert pf.check(None, "JUMP", df2["date"].iloc[-4], tmp_path)["price"] < 5


def test_tradable_note_is_the_assumption_unless_a_gift_city_list_is_found(tmp_path):
    assert pf.tradable_note("AAPL", tmp_path) == "assumed tradable, checked before Phase C"
    (tmp_path / "us").mkdir()
    (tmp_path / "us" / "zerodha_gift_city_us_stocks.csv").write_text("symbol,name\nAAPL,Apple\nMSFT,Microsoft\n", encoding="utf-8")
    assert pf.tradable_note("AAPL", tmp_path).startswith("on Zerodha's GIFT City list")
    assert pf.tradable_note("ZZZZ", tmp_path).startswith("NOT on Zerodha's GIFT City list")
    assert pf.on_list("MSFT", tmp_path) is True and pf.on_list("NOPE", tmp_path) is False


# --- SEC facts, universe, on-demand bars --------------------------------------------------------------------------------------------------

def _facts():
    def item(end, val, form="10-K", filed=None, start=None):
        return {"start": start, "end": end, "val": val, "accn": "x", "fy": 2025, "fp": "FY", "form": form, "filed": filed or end}
    return {"entityName": "Abc Corp", "facts": {
        "us-gaap": {
            "Revenues": {"units": {"USD": [item("2024-12-31", 1000.0, filed="2025-02-20", start="2024-01-01"), item("2025-12-31", 1300.0, filed="2026-02-20", start="2025-01-01"),
                                           item("2026-12-31", 9999.0, filed="2027-02-20", start="2026-01-01"),                                                     # filed after the day
                                           item("2025-09-30", 300.0, form="10-Q", filed="2025-11-01", start="2025-07-01")]}},                                       # a quarter, not a year
            "NetIncomeLoss": {"units": {"USD": [item("2025-12-31", 130.0, filed="2026-02-20", start="2025-01-01")]}},
            "LongTermDebt": {"units": {"USD": [item("2025-12-31", 400.0, filed="2026-02-20"), item("2026-06-30", 450.0, form="10-Q", filed="2026-08-01")]}}},
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [item("2026-10-20", 5_000_000.0, form="10-Q", filed="2026-10-25")]}}}}}


def test_sec_facts_parser_on_a_fake_payload_is_point_in_time():
    out = screen.parse_company_facts(_facts(), DAY)
    assert out["revenue_fy"] == {"end": "2025-12-31", "usd": 1300.0, "filed": "2026-02-20"} and out["revenue_growth_pct"] == 30.0
    assert out["net_income_fy"]["usd"] == 130.0 and out["net_margin_pct"] == 10.0
    assert out["long_term_debt"]["usd"] == 450.0 and out["shares_outstanding"]["shares"] == 5_000_000.0 and out["entity"] == "Abc Corp"
    early = screen.parse_company_facts(_facts(), date(2026, 3, 1))                      # before the June-quarter debt and the October share count were filed
    assert early["revenue_fy"]["usd"] == 1300.0 and "shares_outstanding" not in early and early["long_term_debt"]["usd"] == 400.0
    first = screen.parse_company_facts(_facts(), date(2025, 3, 1))
    assert first["revenue_fy"]["usd"] == 1000.0 and "net_income_fy" not in first and "revenue_growth_pct" not in first
    assert screen.parse_company_facts({}, DAY)["source"].startswith("SEC")


def _sec_get(calls):
    ticker_file = {"0": {"cik_str": 1234, "ticker": "ABC", "title": "Abc Corp"}, "1": {"cik_str": 99, "ticker": "ZED", "title": "Zed Inc"}, "2": {"cik_str": 5, "ticker": "AAA", "title": "Aaa"}}

    def get(url, timeout=60):
        calls.append(url)
        if url == us_prices.SEC_TICKERS:
            return ticker_file
        if "companyfacts" in url:
            return _facts()
        if "submissions" in url:
            return {"filings": {"recent": {"accessionNumber": ["a1", "a2"], "form": ["8-K", "10-Q"], "filingDate": ["2026-11-02", "2027-01-05"],
                                           "acceptanceDateTime": ["2026-11-02T13:30:00.000Z", "2027-01-05T13:30:00.000Z"], "primaryDocument": ["a.htm", "b.htm"], "items": ["2.02", ""]}}}
        raise AssertionError(url)
    return get


def test_the_universe_keeps_the_sec_files_order_and_titles_and_writes_the_cik_cache(tmp_path):
    calls = []
    n = screen.refresh_us_universe(tmp_path, get=_sec_get(calls))
    assert n == 3
    uni = screen.us_universe(tmp_path)
    assert [u["ticker"] for u in uni] == ["ABC", "ZED", "AAA"] and uni[0]["title"] == "Abc Corp" and uni[0]["cik"] == 1234                      # SEC's order, not alphabetical
    from pflab.us import instruments as uins
    assert uins.load_ciks(tmp_path) == {"ABC": 1234, "ZED": 99, "AAA": 5}
    assert calls == [us_prices.SEC_TICKERS]                                                                                                          # one fetch for both caches


def test_the_universe_falls_back_to_the_symbols_on_disk_when_there_is_no_cache(tmp_path):
    _put(tmp_path, "XYZ", _bars())
    assert [u["ticker"] for u in screen.us_universe(tmp_path)] == ["XYZ"]


def test_us_screen_applies_the_floor_and_carries_the_survivorship_warning(con, tmp_path):
    root = tmp_path / "usroot"
    for s, kw in (("GOODA", dict(price=50, volume=1_000_000)), ("GOODB", dict(price=80, volume=2_000_000)), ("CHEAP", dict(price=4, volume=9_000_000)), ("THIN", dict(price=50, volume=1000))):
        _put(root, s, _bars(**kw))
    r = screen.screen_stocks(con, NOW, "US", {}, "momentum_126", 40, root=root, fetch=lambda s, **k: (_ for _ in ()).throw(ConnectionError("down")))
    assert {x["symbol"] for x in r["rows"]} == {"GOODA", "GOODB"}
    assert r["note"].count(screen.US_NOTE) == 1 and "survivorship" in r["note"]
    row = r["rows"][0]
    assert row["floor"].startswith("clears") and row["tradable"] == "assumed tradable, checked before Phase C" and "survivorship" in row["history_warning"]
    assert row["return_126d_pct"] is not None and row["traded_value_usd"] > 2e6 and row["market_cap_usd"] is None


def test_on_demand_download_writes_the_cache_and_falls_back_to_it_when_the_network_is_down(con, tmp_path):
    root = tmp_path / "usroot"
    _put(root, "HAVE", _bars())
    seen = []

    def good(sym, start=None, **k):
        seen.append(sym)
        return _bars(price=30, volume=2_000_000)
    r = screen.screen_stocks(con, NOW, "US", {"symbols": ["NEWA", "HAVE"]}, root=root, fetch=good)
    assert {x["symbol"] for x in r["rows"]} == {"NEWA", "HAVE"} and seen == ["NEWA"] and (root / "us" / "raw" / "NEWA.parquet").exists()
    assert r["fetch"]["fetched"] == ["NEWA"] and "downloaded bars for 1" in r["note"]
    down_calls = []

    def down(sym, start=None, **k):
        down_calls.append(sym)
        raise ConnectionError("network is down")
    r = screen.screen_stocks(con, NOW, "US", {"symbols": ["HAVE", "N1", "N2", "N3", "N4", "N5"]}, root=root, fetch=down)             # never fails the screen
    assert [x["symbol"] for x in r["rows"]] == ["HAVE"] and r["fetch"]["network"] == "down" and "network looks down" in r["note"]
    assert len(down_calls) == 3                                                                                                          # it gave up after three failures in a row
    assert not (root / "us" / "raw" / "N1.parquet").exists()


def test_a_stale_cached_name_is_refreshed_on_demand_else_flagged(con, tmp_path):
    root = tmp_path / "usroot"
    _put(root, "OLDA", _bars(end=DAY - timedelta(days=20)))
    r = screen.screen_stocks(con, NOW, "US", {}, root=root, fetch=lambda s, **k: (_ for _ in ()).throw(ConnectionError("x")))
    assert [x["symbol"] for x in r["rows"]] == ["OLDA"] and "old" in r["rows"][0]["floor"] and "refresh before picking" in r["rows"][0]["floor"]
    r = screen.screen_stocks(con, NOW, "US", {}, root=root, fetch=lambda s, start=None, **k: _bars(price=60, volume=1_000_000))
    assert r["rows"][0]["price_date"] == str(DAY) and r["rows"][0]["floor"].startswith("clears")


def test_us_card_has_sec_facts_filings_and_the_rails_from_fakes(con, tmp_path):
    root = tmp_path / "usroot"
    _put(root, "ABC", _bars(price=50, volume=1_000_000))
    screen.refresh_us_universe(root, get=_sec_get([]))
    con.execute("INSERT INTO us_days_s81 VALUES (?,?,?,?,?,?,?)", [DAY, 100_000.0, 5_000.0, 85.0, "test", 8_500_000.0, "{}"])
    calls = []
    c = screen.company_card(con, NOW, "US", "ABC", root=root, get=_sec_get(calls))
    assert c["ok"] and c["cik"] == 1234 and c["liquidity"]["clears_a62_floor"] is True and c["tradable"].startswith("assumed")
    assert c["sec_facts"]["revenue_fy"]["usd"] == 1300.0 and c["sec_facts"]["shares_outstanding"]["shares"] == 5_000_000.0
    assert c["size"]["market_cap_usd"] == pytest.approx(5_000_000 * c["price"]["last"], rel=1e-3)
    assert c["recent_filings"] == ["2026-11-02 13:30 UTC 8-K"]                                                                       # the filing accepted in 2027 is not known yet
    assert c["rails"]["one_stock_max_pct_of_subbook"] == 10.0 and c["rails"]["max_value_usd_now"] == 10_000 and c["rails"]["max_stocks"] == 12
    assert "survivorship" in c["history_warning"] and any("companyfacts" in u for u in calls)
    # the network down: the cached facts are used and the card still comes back
    def down(url, timeout=60):
        raise ConnectionError("down")
    import os
    p = root / "us" / "sec" / f"facts_{1234:010d}.json"
    os.utime(p, (0, 0))                                                                                                                # make the cache old so a refresh is tried
    c2 = screen.company_card(con, NOW, "US", "ABC", root=root, get=down)
    assert c2["ok"] and c2["sec_facts"]["revenue_fy"]["usd"] == 1300.0 and "could not be fetched" in c2["sec_facts"]["note"]
    assert screen.company_card(con, NOW, "US", "NOPE", root=root, fetch=lambda s, **k: (_ for _ in ()).throw(ConnectionError("x")), get=down)["ok"] is False


# --- the daily US collection ------------------------------------------------------------------------------------------------------------

def test_the_daily_us_collection_includes_held_and_picked_symbols(con, monkeypatch, tmp_path):
    assert us_prices.tracked_symbols(con)[: len(us_prices.ETFS)] == list(us_prices.ETFS)                                              # the ETFs the layer tracked stay
    base = us_prices.tracked_symbols(con)
    assert "SPY" in base and "NVDA" not in base                                                                                      # no table yet: nothing else, no error
    con.execute("INSERT INTO us_lots_s81 VALUES (1, 'ZZ0000789019', 'MSFT', ?, 3, 400.0, NULL, NULL, 'test')", [DAY])
    con.execute("INSERT INTO us_lots_s81 VALUES (2, 'ZZ0001045810', 'SOLD', ?, 0, 100.0, NULL, NULL, 'test')", [DAY])                   # a closed lot: no longer held
    con.execute("CREATE TABLE picks_s83 (pick_id INTEGER, market VARCHAR, isin VARCHAR, symbol VARCHAR, state VARCHAR)")
    con.execute("INSERT INTO picks_s83 VALUES (1, 'US', 'ZZ0001045810', 'NVDA', 'proposed'), (2, 'US', 'ZZ0000320193', 'BRK.B', 'withdrawn'), (3, 'IN', 'INE0INDC0101', 'INDCO', 'held')")
    syms = us_prices.tracked_symbols(con)
    assert {"MSFT", "NVDA", "BRK-B", "SPY"} <= set(syms) and "INDCO" not in syms and "SOLD" not in syms                              # a withdrawn pick is still tracked (it is scored later)
    assert len(syms) == len(set(syms))
    from pflab.service import tasks_s79_us
    got = {}
    monkeypatch.setattr(us_prices, "collect", lambda symbols, root=None, pause=0.5, get=None, recent_days=None: got.update(symbols=list(symbols), recent=recent_days) or {s: (1, "a", "b") for s in symbols})
    monkeypatch.setattr(screen, "refresh_us_universe", lambda root, get=None: (_ for _ in ()).throw(RuntimeError("no contact")))
    res = tasks_s79_us._prices(SimpleNamespace(con=con, data_root=tmp_path))
    assert {"MSFT", "NVDA", "SPY"} <= set(got["symbols"]) and got["recent"] == 10 and res["symbols"] == len(got["symbols"])
    assert "not refreshed" in res["sec_universe"]                                                                                      # a refused SEC file is reported, never fatal


def test_a_picks_table_with_no_market_column_is_read_by_the_key(con):
    con.execute("CREATE TABLE picks_s83 (pick_id INTEGER, isin VARCHAR, symbol VARCHAR)")
    con.execute("INSERT INTO picks_s83 VALUES (1, 'ZZ0001045810', 'NVDA'), (2, 'INE0INDC0101', 'INDCO')")
    assert us_prices.picked_symbols(con) == ["NVDA"]


# --- the tools --------------------------------------------------------------------------------------------------------------------------

def test_the_tools_are_registered_run_and_return_valid_json(con, root, tmp_path):
    assert {"screen_stocks", "company_card"} <= set(tools.REGISTRY)
    assert not ({"propose_picks", "withdraw_pick", "skip_idea"} & set(tools.REGISTRY))                                                # the strategist agent writes those
    for n in ("screen_stocks", "company_card"):
        d = tools.REGISTRY[n][0]
        assert "every number is code" in d["description"].lower() and len(d["description"]) < 480               # the strategist's rule: short descriptions; the full legend is in each result's `labels`
    ctx = tools.make_ctx(con, tmp_path, root, NOW, 1)
    text, err = tools.run(ctx, "screen_stocks", {"market": "IN", "n": 40, "sort": "momentum_63"})
    out = json.loads(text)
    assert not err and len(out["rows"]) == 40 and len(text) <= tools.LIMITS["screen_stocks"] and out["labels"]["only_reading"]
    text, err = tools.run(ctx, "company_card", {"market": "IN", "symbol": "UPCO"})
    card = json.loads(text)
    assert not err and card["symbol"] == "UPCO" and len(text) <= tools.LIMITS["company_card"]
    text, err = tools.run(ctx, "company_card", {"market": "IN", "symbol": "NOSUCH"})
    assert err and json.loads(text)["ok"] is False
    assert tools.run(ctx, "screen_stocks", {"market": "XX"})[1] is True                                                               # a bad market is an error result, not a crash
