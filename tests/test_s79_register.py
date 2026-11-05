from datetime import datetime

import duckdb

from pflab.learner import counter, s79
from pflab.pm import store


def test_s79_studies_count_once():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    n0 = counter.n_tests(c)
    got = s79.register_all(c, datetime(2026, 11, 5, 12, 0))
    assert counter.n_tests(c) == n0 + len(got) and len(got) == 2
    assert s79.register_all(c, datetime(2026, 11, 5, 12, 5)) == []
