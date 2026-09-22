import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

_spec = importlib.util.spec_from_file_location(
    "ingest_gdelt_backfill", Path(__file__).resolve().parents[1] / "tools" / "ingest_gdelt_backfill.py")
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

CSV = ("day,n_events,n_articles,mean_tone,mean_goldstein,q1,q2,q3,q4\n"
       "20150218,5000,20000,-1.5,0.5,3000,700,800,500\n"
       "20150219,5100,21000,-1.4,0.6,3100,700,800,500\n")


def test_ingest_writes_new_days_and_never_overwrites_live(tmp_path):
    csv = tmp_path / "gdelt" / "backfill" / "x.csv"
    csv.parent.mkdir(parents=True)
    csv.write_text(CSV)
    agg = tmp_path / "gdelt" / "agg"
    agg.mkdir(parents=True)
    live = pd.DataFrame([{"date": date(2015, 2, 19), "n_events": 5090, "n_articles": 1,
                          "mean_tone": 0.0, "mean_goldstein": 0.0, "q1": 0, "q2": 0, "q3": 0, "q4": 0}])
    live.to_parquet(agg / "2015-02-19.parquet", index=False)

    r = G.ingest(csv, tmp_path)
    assert r["written"] == 1
    assert r["already_present"] == [{"date": "2015-02-19", "live_events": 5090, "bigquery_events": 5100}]
    new = pd.read_parquet(agg / "2015-02-18.parquet")
    assert list(new.columns) == ["date", *G.COLS] and new["n_events"].iloc[0] == 5000
    assert pd.read_parquet(agg / "2015-02-19.parquet")["n_events"].iloc[0] == 5090
    assert G.ingest(csv, tmp_path)["written"] == 0


def test_ingest_refuses_the_old_event_level_export(tmp_path):
    csv = tmp_path / "old.csv"
    csv.write_text("event_id,sqldate,a1_country\n1,20150218,IND\n")
    with pytest.raises(ValueError, match="missing columns"):
        G.load_csv(csv)
