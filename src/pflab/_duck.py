"""DuckDB queries over parquet files, one in-memory connection per thread (S58b).

`duckdb.sql` runs on the module's one default connection, which is not safe across threads: in the dashboard the
jobs, the Monte Carlo loop, the research loop and the server's requests query at once, and on 2026-10-24 the Monte
Carlo loop failed at start-up with "Attempting to execute an unsuccessful or closed pending query result" while the
conductor read file dates. Every such query goes through `sql` here instead. (The PM store has its own connection.)
"""
from __future__ import annotations

import threading

import duckdb

_local = threading.local()


def sql(query: str):
    con = getattr(_local, "con", None)
    if con is None:
        con = _local.con = duckdb.connect()
    try:
        return con.sql(query)
    except duckdb.TransactionException:                    # S85: a thread's connection left in an aborted transaction by an earlier failed statement: roll back, then once more
        try:
            con.execute("ROLLBACK")
        except Exception:
            con = _local.con = duckdb.connect()
        return con.sql(query)
