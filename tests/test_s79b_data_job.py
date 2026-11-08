from datetime import date

from pflab.service import tasks_s79_data as td


def test_parts_run_independently_and_a_failure_is_named(tmp_path):
    calls = []
    out = td.run(tmp_path, date(2026, 11, 9), flows=lambda: calls.append("flows") or {"rows": 20},
                 vix=lambda: (_ for _ in ()).throw(ConnectionError("no route")),
                 world=lambda a, b: calls.append(("world", str(a), str(b))) or {"days": 3}, themes=lambda a, b: calls.append(("themes", str(a), str(b))) or {})
    assert out["flows"] == {"rows": 20} and "india_vix" in out["failed"] and "ConnectionError" in out["failed"]["india_vix"]
    assert ("world", "2026-11-06", "2026-11-08") in calls                      # no file yet: the last 3 days up to yesterday, bounded


def test_gdelt_is_bounded_per_run_and_resumes(tmp_path):
    import pandas as pd
    p = tmp_path / "gdelt" / "world"
    p.mkdir(parents=True)
    pd.DataFrame({"date": pd.to_datetime(["2026-09-22"])}).to_parquet(p / "daily_by_country.parquet")
    seen = []
    td.run(tmp_path, date(2026, 11, 9), flows=lambda: {}, vix=lambda: {}, world=lambda a, b: seen.append((str(a), str(b))) or {}, themes=lambda a, b: {})
    assert seen == [("2026-09-23", "2026-09-25")]                              # three days a run: a long absence catches up over several runs


def test_a_part_with_no_source_answering_is_a_failed_part_so_an_offline_laptop_reads_as_offline(tmp_path):
    out = td.run(tmp_path, date(2026, 11, 9), flows=lambda: {"error": "no source answered", "groww": "ConnectionError('Max retries exceeded')", "nse": "ConnectionError('getaddrinfo failed')"},
                 vix=lambda: (_ for _ in ()).throw(ConnectionError("getaddrinfo failed")), world=lambda a, b: {}, themes=lambda a, b: {})
    from pflab.service import jobs
    assert set(out["failed"]) == {"flows", "india_vix"} and all(jobs.offline(v) for v in out["failed"].values())
