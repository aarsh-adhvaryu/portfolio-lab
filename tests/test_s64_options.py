"""S64 Phase 5 item 7: F&O files in both formats, Black-76 implied volatility, max pain, PCR, build-up classes."""
import io
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.data import fo_daily
from pflab.quant import options as op

D = date(2026, 10, 26)


def test_black76_round_trip_and_bounds():
    p = op.black76(100.0, 100.0, 0.25, 0.07, 0.20, True)
    assert op.implied_vol(p, 100.0, 100.0, 0.25, 0.07, True) == pytest.approx(0.20, abs=1e-4)
    pp = op.black76(100.0, 110.0, 0.25, 0.07, 0.35, False)
    assert op.implied_vol(pp, 100.0, 110.0, 0.25, 0.07, False) == pytest.approx(0.35, abs=1e-4)
    assert op.implied_vol(0.0, 100.0, 100.0, 0.25, 0.07, True) is None            # no price
    assert op.implied_vol(5.0, 100.0, 80.0, 0.25, 0.07, True) is None              # below intrinsic


def test_put_call_parity_of_the_prices():
    c, p = op.black76(100, 95, 0.5, 0.06, 0.3, True), op.black76(100, 95, 0.5, 0.06, 0.3, False)
    assert c - p == pytest.approx(np.exp(-0.06 * 0.5) * (100 - 95), abs=1e-9)


def test_max_pain_is_where_holders_gain_least():
    o = pd.DataFrame({"option": ["CE", "CE", "CE", "PE", "PE", "PE"], "strike": [90, 100, 110, 90, 100, 110],
                      "oi": [100, 500, 100, 100, 500, 100]})
    assert op.max_pain(o) == 100.0


def test_buildup_classes():
    assert op.buildup_class(0.02, 0.1) == "long build-up" and op.buildup_class(-0.02, 0.1) == "short build-up"
    assert op.buildup_class(0.02, -0.1) == "short covering" and op.buildup_class(-0.02, -0.1) == "long unwinding"
    assert op.buildup_class(0.0, 0.1) is None and op.buildup_class(float("nan"), 0.1) is None


def row(sym, ins, kind, exp, opt=None, strike=np.nan, close=0.0, settle=0.0, prev=0.0, und=np.nan, oi=0.0, chg=0.0):
    return dict(date=D, symbol=sym, instrument=ins, kind=kind, expiry=exp, option=opt, strike=strike, close=close, settle=settle,
                prev_close=prev, underlying=und, oi=oi, oi_change=chg, contracts=1.0, lot=75.0)


def day_frame():
    e = date(2026, 11, 26)                                       # 31 days out
    T, r, sig, F = 31 / 365.0, 0.07, 0.18, 24_000.0
    rows = [row("NIFTY", "FUT", "index", e, close=F, settle=F, und=23_900.0, oi=1000, chg=10)]
    for k in (23_800.0, 24_000.0, 24_200.0):
        rows.append(row("NIFTY", "OPT", "index", e, "CE", k, settle=op.black76(F, k, T, r, sig, True), und=23_900.0, oi=100, chg=5))
        rows.append(row("NIFTY", "OPT", "index", e, "PE", k, settle=op.black76(F, k, T, r, sig, False), und=23_900.0, oi=150, chg=5))
    near, far = date(2026, 10, 27), date(2026, 11, 26)
    rows += [row("ABC", "FUT", "stock", near, close=102.0, prev=100.0, oi=200, chg=-150),         # rolling out
             row("ABC", "FUT", "stock", far, close=103.0, prev=101.0, oi=700, chg=250)]            # rolling in: total +100
    return pd.DataFrame(rows)


def test_index_day_facts():
    r = op.index_day(day_frame(), D, "NIFTY", 0.07)
    assert r["atm_iv"] == pytest.approx(0.18, abs=0.002) and r["atm_strike"] == 24_000.0
    assert r["pcr"] == pytest.approx(450 / 300)
    assert r["fut_premium_ann"] == pytest.approx((24_000 / 23_900 - 1) * 365 / 31)
    assert r["max_pain"] in (23_800.0, 24_000.0, 24_200.0)


def test_buildup_uses_total_open_interest_across_expiries():
    b = op.buildup_day(day_frame(), D)
    a = b[b["symbol"] == "ABC"].iloc[0]
    assert a["oi"] == 900 and a["oi_change"] == 100 and a["class"] == "long build-up"       # not "long unwinding" from the expiring leg


UDIFF = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,"
         "OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,"
         "TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
         "2026-10-26,2026-10-26,FO,NSE,IDO,1,,NIFTY,,2026-11-26,2026-11-26,24000,CE,x,1,1,1,310,310,300,23900,312.5,100,5,10,1,1,F1,75,,,,,\n"
         "2026-10-26,2026-10-26,FO,NSE,STF,2,,ABC,,2026-10-27,2026-10-27,,,y,1,1,1,102,102,100,101,102,200,-150,10,1,1,F1,500,,,,,\n")


def test_udiff_file_normalizes_to_one_layout():
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("a.csv", UDIFF)
    df = fo_daily.normalize(z.getvalue(), D)
    assert list(df.columns) == fo_daily.COLUMNS and len(df) == 2
    o = df[df["instrument"] == "OPT"].iloc[0]
    assert (o["option"], o["strike"], o["settle"], o["oi_change"]) == ("CE", 24000.0, 312.5, 5.0)
    f = df[df["instrument"] == "FUT"].iloc[0]
    assert f["option"] is None and np.isnan(f["strike"]) and f["prev_close"] == 100.0


def test_participant_oi_table():
    text = ('"Participant wise Open Interest (no. of contracts) in Equity Derivatives as on Oct 26, 2026",,\n'
            'Client Type,Future Index Long,Future Index Short\nClient,10,20\nDII,30,40\nFII,50,60\nPro,70,80\nTOTAL,160,200\n')
    df = fo_daily.normalize_participants(text, D)
    assert list(df["participant"]) == ["Client", "DII", "FII", "Pro"] and df.loc[2, "Future Index Long"] == 50


def test_derive_writes_the_tables_and_the_summary_line(tmp_path, monkeypatch):
    from pflab.data import riskfree
    monkeypatch.setattr(riskfree, "monthly_table", lambda root=None: pd.DataFrame({"rate": [], "label": []}, index=pd.DatetimeIndex([])))
    p = fo_daily.path(D, tmp_path)
    p.parent.mkdir(parents=True)
    day_frame().to_parquet(p, index=False)
    assert op.derive_missing(tmp_path) == 1 and op.derive_missing(tmp_path) == 0           # once
    line = op.line(tmp_path, D)
    assert line.startswith("Nifty IV 18") and "PCR 1.50" in line and "information, not a signal" in line
    assert op.buildup_for(tmp_path, D, ["ABC", "XYZ"])["ABC"]["class"] == "long build-up"
