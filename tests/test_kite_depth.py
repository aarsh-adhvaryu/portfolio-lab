"""S41 depth recording, impact and calibration on a FAKE Kite quote payload (Kite's documented shape)."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab.ingest import kite_depth as kd
from pflab.quant import lob


def quote(vol=1000, bid=100.0, ask=100.1):
    lv = lambda p0, step: [{"price": round(p0 + step * i, 2), "quantity": 100 * (i + 1), "orders": 2} for i in range(5)]
    return {"NSE:AAA": {"last_price": 100.05, "volume": vol, "depth": {"buy": lv(bid, -0.05), "sell": lv(ask, 0.05)}}}


class FakeKite:
    def __init__(self):
        self.calls = 0

    def quote(self, instruments):
        self.calls += 1
        return quote(vol=1000 + 50 * self.calls)


def test_rows_from_quote_keeps_five_levels_a_side():
    r = kd.rows_from_quote(quote(), datetime(2026, 10, 16, 10, 0)).iloc[0]
    assert r["buy_px1"] == 100.0 and r["sell_px1"] == 100.1 and r["sell_px5"] == pytest.approx(100.3)
    assert r["buy_qty5"] == 500 and r["sell_orders3"] == 2


def test_record_polls_and_writes_one_file_a_day(tmp_path):
    clock = [datetime(2026, 10, 16, 10, 0)]
    now = lambda: clock[0]
    sleep = lambda s: clock.__setitem__(0, clock[0] + timedelta(seconds=s))
    k = FakeKite()
    n = kd.record(k, ["NSE:AAA"], minutes=1, interval=5, root=tmp_path, now=now, sleep=sleep, flush_every=4)
    assert n == 12 and k.calls == 12
    df = kd.load("NSE:AAA", tmp_path)
    assert len(df) == 12 and (tmp_path / "kite_depth" / "2026-10-16.parquet").exists()


def test_impact_walks_the_recorded_ladder():
    snaps = kd.rows_from_quote(quote(), datetime(2026, 10, 16, 10, 0))
    mid = 100.05
    small = kd.impact(snaps, 100 * mid * 0.5)                  # half the best level: pays the half spread
    assert small["median_bps"] == pytest.approx((100.1 / mid - 1) * 1e4)
    big = kd.impact(snaps, 250 * mid)                          # 100 at 100.10 + 150 at 100.15
    avg = (100 * 100.1 + 150 * 100.15) / 250
    assert big["median_bps"] == pytest.approx((avg / mid - 1) * 1e4, rel=1e-3)
    assert kd.impact(snaps, 10 ** 7)["too_thin"] == 1         # more than the five levels hold
    sell = kd.impact(snaps, 100 * mid * 0.5, side="sell")
    assert sell["median_bps"] == pytest.approx((1 - 100.0 / mid) * 1e4)


class FakeCon:
    rows = {"INE000AAA001": ("AAA", "equity"), "INF000MF0001": ("MF1", "mutual_fund"), "INE000BBB001": ("BBB", "equity")}

    def execute(self, sql, params):
        return SimpleNamespace(fetchone=lambda: self.rows.get(params[0]))


def test_proposal_impact_notes(tmp_path):
    (tmp_path / "kite_depth").mkdir()
    kd.rows_from_quote(quote(), datetime(2026, 10, 19, 10, 0)).to_parquet(tmp_path / "kite_depth" / "2026-10-19.parquet")
    note = kd.impact_note_fn(FakeCon(), tmp_path)
    assert "market impact ~" in note("INE000AAA001", 5000.0) and "measured" in note("INE000AAA001", 5000.0)
    assert note("INF000MF0001", 5000.0) is None                              # bought at NAV: no order book
    assert "not measured" in note("INE000BBB001", 5000.0)                    # nothing recorded for BBB
    assert note("INE999", 5000.0) is None


def test_calibrate_reads_sizes_depth_and_trade_rate():
    rows = [kd.rows_from_quote(quote(vol=1000 + 300 * i), datetime(2026, 10, 16, 10, 0) + timedelta(seconds=5 * i))
            for i in range(20)]
    f = kd.calibrate(pd.concat(rows, ignore_index=True))
    assert f.limit_size == pytest.approx(150.0) and f.start_depth == 300 and f.start_mid == round(100.05 / 0.05)
    a = np.asarray(f.market.alpha)
    each = f.market.mu[0] / (1 - a.sum(axis=1).mean())
    assert each * f.market_size * 2 == pytest.approx(60.0)       # 300 shares every 5 s
    r = lob.simulate(f, 120.0, np.random.default_rng(0))
    assert len(r.snapshots) > 100


def test_recorder_check_mode_saves_nothing(monkeypatch, tmp_path, capsys):
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("rec", pathlib.Path(__file__).parents[1] / "tools" / "kite_depth_record.py")
    rec = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rec)
    monkeypatch.setattr(rec.kite, "client", lambda s: FakeKite())
    monkeypatch.setattr(rec.secrets, "load", lambda: None)
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path))
    assert rec.main(["--check", "--symbols", "AAA"]) == 0
    assert "1 of 1 instruments answered" in capsys.readouterr().out
    assert rec.main(["--check", "--symbols", "AAA", "BBB"]) == 1                # BBB did not answer
    assert not (tmp_path / "kite_depth").exists()
