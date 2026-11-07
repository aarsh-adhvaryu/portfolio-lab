"""S79b agent D: the new public-data readers (synthetic data only; no network)."""
import json
from datetime import date

import pandas as pd

from pflab.data import asia, flows, gdelt_s79b as gg, global_markets as gm, vix_in


NSE_ROWS = [
    {"category": "DII", "date": "06-Nov-2026", "buyValue": "18084.32", "sellValue": "24053.02", "netValue": "-5968.7"},
    {"category": "FII/FPI", "date": "06-Nov-2026", "buyValue": "30455.63", "sellValue": "16705.81", "netValue": "13749.82"},
]


def test_parse_nse_one_row_per_date():
    df = flows.parse_nse(NSE_ROWS)
    assert len(df) == 1
    r = df.iloc[0]
    assert r["date"] == date(2026, 11, 6)
    assert r["fii_net_cr"] == 13749.82 and r["dii_net_cr"] == -5968.7
    assert abs(r["fii_buy_cr"] - r["fii_sell_cr"] - r["fii_net_cr"]) < 0.01


def test_parse_groww_next_data():
    data = {"props": {"pageProps": {"initialData": [
        {"fii": {"netBuySell": 1.5, "grossBuy": 11.0, "grossSell": 9.5}, "date": "2026-11-05", "dii": {"grossSell": 5.0, "netBuySell": -1.0, "grossBuy": 4.0}}]}}}
    html = '<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + "</script></html>"
    df = flows.parse_groww(html)
    assert df.iloc[0]["date"] == date(2026, 11, 5) and df.iloc[0]["dii_net_cr"] == -1.0


def test_merge_dedupes_drops_future_and_later_wins():
    a = flows.parse_nse(NSE_ROWS, "old")
    b = flows.parse_nse(NSE_ROWS, "new")
    fut = b.copy()
    fut["date"] = date(2030, 1, 1)
    out = flows.merge(a, b, fut, today=date(2026, 11, 8))
    assert len(out) == 1 and out.iloc[0]["source"] == "new"


def test_collect_survives_one_failing_source(tmp_path):
    def bad():
        raise RuntimeError("down")
    r = flows.collect(tmp_path, get_nse=lambda: flows.parse_nse(NSE_ROWS), get_groww=bad, today=date(2026, 11, 8))
    assert r["rows"] == 1 and "down" in r["groww"]
    assert len(flows.load(tmp_path)) == 1


def test_manifest_merges_by_name(tmp_path):
    flows.record_manifest([{"name": "a", "source": "u", "first": date(2020, 1, 1), "last": date(2020, 2, 1), "rows": 3}], tmp_path)
    flows.record_manifest([{"name": "b", "source": "v", "first": None, "last": None, "rows": 0},
                           {"name": "a", "source": "u2", "first": "2020-01-01", "last": "2020-03-01", "rows": 4}], tmp_path)
    m = json.loads((tmp_path / "_s79b_manifest.json").read_text(encoding="utf-8"))["series"]
    assert [x["name"] for x in m] == ["a", "b"] and m[0]["rows"] == 4 and m[0]["last"] == "2020-03-01" and m[0]["fetched_at"]


def _gfile(root, key, closes):
    (root / "global").mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": [date(2026, 11, 2 + i) for i in range(len(closes))], "close": closes}).to_parquet(root / "global" / f"{key}.parquet", index=False)


def test_asia_closes_upto_and_window_change(tmp_path):
    _gfile(tmp_path, "KR_KOSPI", [100.0, 90.0, 99.0])
    _gfile(tmp_path, "JP_NIKKEI225", [10.0, 11.0, 12.0])
    c = asia.closes(tmp_path, upto=date(2026, 11, 3))
    assert len(c) == 2 and set(c.columns) == {"KR_KOSPI", "JP_NIKKEI225"}
    w = asia.window_change(date(2026, 11, 2), date(2026, 11, 4), tmp_path)
    assert w["KR_KOSPI"]["pct"] == -1.0 and w["JP_NIKKEI225"]["pct"] == 20.0
    r = asia.returns(tmp_path)
    assert abs(r["KR_KOSPI"].iloc[1] + 0.1) < 1e-12


def test_vix_load_upto(tmp_path):
    (tmp_path / "indices").mkdir()
    pd.DataFrame({"date": [date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)], "close": [14.0, 15.0, 16.0]}).to_parquet(tmp_path / "indices" / "INDIA_VIX.parquet", index=False)
    assert vix_in.load(tmp_path, upto=date(2026, 11, 5))["close"].tolist() == [14.0, 15.0]


def test_global_series_needed_by_new_tools():
    for k, sym in {"US_SP500": "^GSPC", "US_NASDAQ": "^IXIC", "US_SOX": "^SOX", "US_10Y_YIELD": "^TNX", "US_VIX": "^VIX", "DOLLAR_INDEX": "DX-Y.NYB",
                   "BRENT_FUT": "BZ=F", "WTI": "CL=F", "FX_USDINR": "INR=X", "GOLD": "GC=F", "KR_KOSPI": "^KS11", "TW_TAIEX": "^TWII",
                   "JP_NIKKEI225": "^N225", "HK_HANGSENG": "^HSI", "CN_SHANGHAI": "000001.SS"}.items():
        assert gm.SERIES[k] == sym


def test_gdelt_event_aggregate_by_day_and_country():
    ev = pd.DataFrame({"sqldate": ["20261030"] * 3, "root": ["01", "14", "14"], "quad": [1, 3, 3], "gold": [1.0, -2.0, -4.0],
                       "narts": [2, 3, 5], "tone": [-1.0, -3.0, -5.0], "country": ["IN", "IN", None], "added": ["20261030000000", "20261030001500", "20261030001500"]})
    by, ty = gg.aggregate_events(ev)
    i = by[by["country"] == "IN"].iloc[0]
    assert i["n_events"] == 2 and i["n_articles"] == 5 and i["q1"] == 1 and i["q3"] == 1 and abs(i["mean_tone"] + 2.0) < 1e-12
    assert "XX" in set(by["country"])
    t = ty[ty["country"] == "IN"].iloc[0]
    assert t["r01"] == 1 and t["r14"] == 1 and t["r20"] == 0


def test_gdelt_theme_groups():
    s = pd.Series(["ECON_STOCKMARKET;TAX_FNCACT", "ENV_OIL;ECON_OILPRICE", "ARMEDCONFLICT;KILL", "TARIFF;ECON_TRADE_DISPUTE", None, "EPU_POLICY_REGULATION"])
    m = gg.tag_themes(s)
    assert m["finance"].tolist() == [True, False, False, True, False, False]
    assert m["energy"].tolist() == [False, True, False, False, False, False]
    assert m["conflict"].tolist() == [False, False, True, False, False, False]
    assert m["trade"].tolist() == [False, False, False, True, False, False]
    assert m["regulation"].tolist() == [False, False, False, False, False, True]
