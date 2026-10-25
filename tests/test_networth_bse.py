"""Net worth buckets and the BSE bhavcopy collector (SYNTHETIC: no network, fake session)."""
from datetime import date

import pytest

from pflab.calc import networth as nw
from pflab.data import bse_bhavcopy as bse

UDIFF = (b"TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,"
         b"PrvsClsgPric,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd\n"
         b"2026-10-14,2026-10-14,CM,BSE,STK,500001,INE000X01010,NEWCO,A,100,110,95,105.5,100,1000,105500,50\n")


class FakeResp:
    def __init__(self, code, content):
        self.status_code, self.content = code, content


class FakeSession:
    def __init__(self, by_day):
        self.by_day, self.calls = by_day, 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        return self.by_day.get(url.split("_0_0_0_")[1][:8], FakeResp(404, b""))


def test_bse_day_is_normalised_kept_apart_and_idempotent(tmp_path):
    s = FakeSession({"20261014": FakeResp(200, UDIFF), "20261015": FakeResp(200, b"<html>error</html>")})
    assert bse.collect(date(2026, 10, 13), date(2026, 10, 15), root=tmp_path, sleep=0, session=s) == \
        {"ok": 1, "missing": 2, "error": 0}
    assert (tmp_path / "bse_bhavcopy" / "2026" / "2026-10-14.parquet").exists()
    assert not (tmp_path / "bhavcopy").exists()                     # never mixed into the NSE panel
    df = bse.load(root=tmp_path)
    assert df["isin"].tolist() == ["INE000X01010"] and df["close"].tolist() == [105.5]
    calls = s.calls
    bse.fetch_day(date(2026, 10, 14), s, root=tmp_path)
    assert s.calls == calls                                          # already on disk: no network call


@pytest.mark.parametrize("asset,tax,name,want", [
    ("equity", "EQUITY", "", "equity"), ("sgb", "SGB", "", "gold"),
    ("etf", "LISTED_NONEQUITY", "NIPPON INDIA GOLD BEES", "gold"), ("bond", "LISTED_NONEQUITY", "", "debt"),
    ("mutual_fund", "DEBT_MF", "", "debt"), ("unknown", "REVIEW", "", "review")])
def test_buckets(asset, tax, name, want):
    assert nw.bucket(asset, tax, name) == want
