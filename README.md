# portfolio-lab (`pflab`)

Personal research harness for a tax-aware, monthly-SIP portfolio over NSE
equities. No free lunch, no magic backtests. See `PLAN.md` for the
roadmap, `CLAUDE.md` for the coding contract, and `docs/strategies/E1.md`
for the first chartered strategy.

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
.venv/bin/pytest -q
export PFLAB_DATA_DIR=/path/on/D/drive
pflab collect bhavcopy --from 2024-06-20 --to 2024-07-20
```

Research software, not investment advice.
