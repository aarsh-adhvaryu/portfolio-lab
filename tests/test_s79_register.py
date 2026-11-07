from datetime import datetime

import duckdb

from pflab.learner import counter, s79
from pflab.pm import store


def test_s79_studies_count_once():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    n0 = counter.n_tests(c)
    got = s79.register_all(c, datetime(2026, 11, 5, 12, 0))
    assert counter.n_tests(c) == n0 + len(got) and len(got) == len(s79.STUDIES)
    assert s79.register_all(c, datetime(2026, 11, 5, 12, 5)) == []


def test_recorded_verdicts_land_once(tmp_path):
    import json
    c = duckdb.connect(":memory:")
    store.migrate(c)
    s79.register_all(c, datetime(2026, 11, 8, 12, 0))
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"results": [{"test": "wave_5", "market": "IN", "n_events": 71, "passed": False, "t_needed": 3.07, "details": {"t_stat": -0.1}},
                                         {"test": "wave_5", "market": "US", "n_events": 0, "passed": False}]}), encoding="utf-8")
    assert s79.apply_verdicts(c, f) == 1 and s79.apply_verdicts(c, f) == 0
    assert c.execute("SELECT passed, n_dev FROM learn_tests WHERE note='s79:wave_sentiment:wave_5'").fetchone() == (False, 71)
