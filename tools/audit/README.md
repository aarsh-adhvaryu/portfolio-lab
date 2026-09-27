# Portfolio audit reproductions

These files accompany `portfolio_system_audit.md` for the uploaded 27 September 2026 snapshot. The source project was reviewed, not patched.

Run with the project's dependencies installed:

```sh
python verify_accounting.py /absolute/path/to/portfolio_system
python inspect_saved_results.py /absolute/path/to/portfolio_system
```

Both commands print JSON. They do not edit project source, download data, place orders, or open sealed results.

`verify_accounting.py` uses generated prices/lots only. Its assertions deliberately identify the original defective behavior; they are not acceptance tests for a repaired engine. After fixing the engine, change the assertions to the economically correct outcomes described in the report. In the exception case, correct behavior is to raise an error, rather than report zero tax.

`inspect_saved_results.py` reads only the two explicit E1 regression artifact directories named in the script. It recalculates metrics from saved outputs; it is not a raw-data rerun. Values are fractions unless identified as currency, quantities or counts. Stale-price liquidation proceeds are gross turnover, not a measure of profit overstatement.

Included JSON files record the observed results on the uploaded snapshot. No raw private market database is included.

Archive SHA-256: `d4c3914f250d4a6aa6e788c3058cadf0c24cd52255394f5ded0303e8a3417482`.
