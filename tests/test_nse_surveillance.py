"""NSE surveillance verdicts and snapshot handling. SYNTHETIC records in NSE's JSON shapes."""
from datetime import date

from pflab.data import nse_surveillance as ns

ASM = {"longterm": {"data": [
    {"symbol": "AAA", "isin": "INE000A01011", "survCode": "LTASM - I (13)", "survDesc": "Long Term Additional Surveillance Measure (LTASM) - Stage I"},
    {"symbol": "BBB", "isin": "INE000B01011", "survCode": "LTASM - IV (16)", "survDesc": "Long Term Additional Surveillance Measure (LTASM) - Stage IV"}]},
    "shortterm": {"data": [{"symbol": "CCC", "isin": "INE000C01011", "survCode": "STASM - II (12)", "survDesc": "Short Term Additional Surveillance Measure (STASM) - Stage II"}]}}
GSM = [{"symbol": "DDD", "isin": "INE000D01011", "survCode": "IBC I & GSM 0 (58)", "survDesc": "ASM IBC Stage I and GSM Stage 0"},
       {"symbol": "EEE", "isin": "INE000E01011", "survCode": "GSM - II", "survDesc": "Graded Surveillance Measure - Stage II"},
       {"symbol": "FFF", "isin": "INE000F01011", "survCode": "GSM 0", "survDesc": "Shortlisted under Graded Surveillance Measure"},
       {"symbol": "GGG", "isin": "INE000G01011", "survCode": "ESM II & GSM 0", "survDesc": "ESM Stage II and GSM Stage 0"}]
ESM = [{"symbol": "HHH", "isin": "INE000H01011", "survCode": "ESM - I (34)", "survDesc": "Enhanced Surveillance Measure (ESM) - Stage I"},
       {"symbol": "III", "isin": "INE000I01011", "survCode": "ESM - II (35)", "survDesc": "Enhanced Surveillance Measure (ESM) - Stage II"}]


def test_verdicts_follow_the_listing_text():
    df = ns.rows_from(ASM, GSM, ESM, date(2026, 10, 15))
    v = dict(zip(df["symbol"], df["verdict"]))
    assert v == {"AAA": "caution", "BBB": "block", "CCC": "caution", "DDD": "block", "EEE": "block",
                 "FFF": "caution", "GGG": "block", "HHH": "caution", "III": "block"}
    assert df.loc[df["symbol"] == "DDD", "ibc"].item() and df.loc[df["symbol"] == "BBB", "stage"].item() == 4


def test_status_and_latest_snapshot(tmp_path):
    df = ns.rows_from(ASM, GSM, ESM, date(2026, 10, 15))
    (tmp_path / "surveillance").mkdir()
    df.to_parquet(tmp_path / "surveillance" / "2026-10-15.parquet")
    assert ns.latest(date(2026, 10, 14), tmp_path) is None                 # nothing dated after asof is used
    snap = ns.latest(date(2026, 10, 16), tmp_path)
    assert ns.status("INE000B01011", snap)["verdict"] == "block"
    assert ns.status("INE000A01011", snap)["verdict"] == "caution"
    assert ns.status("INE999Z01011", snap)["verdict"] == "clear"
    assert ns.status("INE999Z01011", None)["verdict"] == "unknown"
