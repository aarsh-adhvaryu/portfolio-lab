"""Run identity pins every consumed input, cut at the period end (audit
Deliverable 1 g): the contents of the policy files, and each side table.
Appending after the end must not move it (seal identity); editing a consumed
row or a policy file must."""
from __future__ import annotations

from datetime import date

import pandas as pd

from pflab.backtest import runner
from pflab.eval import artifacts
from pflab.eval.periods import Period

END = date(2016, 12, 31)
P = Period("development", date(2007, 1, 1), END)


def _root(tmp_path, cost="brokerage = 0.0\n"):
    (tmp_path / "configs").mkdir(exist_ok=True)
    for name, text in [("periods.toml", "x = 1\n"), ("costs.toml", cost),
                       ("tax.toml", "stcg = 0.2\n"), ("e1.toml", "y = 2\n")]:
        (tmp_path / "configs" / name).write_text(text)
    return tmp_path


def _cfg(**extra):
    return {"evaluation": {"periods_path": "configs/periods.toml"},
            "costs": {"path": "configs/costs.toml"},
            "tax": {"path": "configs/tax.toml"}, **extra}


def _fp(root, cfg, actions=None, indices=None):
    return runner.input_fingerprints(cfg, P, indices or {}, actions, None, root=root)


def test_frame_sha_ignores_row_order_but_not_content():
    a = pd.DataFrame({"isin": ["X", "Y"], "factor": [0.5, 2.0]})
    assert artifacts.frame_sha(a) == artifacts.frame_sha(a.iloc[::-1])
    b = a.assign(factor=[0.5, 2.5])
    assert artifacts.frame_sha(a) != artifacts.frame_sha(b)
    assert artifacts.frame_sha(None) != artifacts.frame_sha(a.iloc[:0])


def test_policy_file_contents_are_pinned_not_their_paths(tmp_path):
    before = _fp(_root(tmp_path), _cfg())
    after = _fp(_root(tmp_path, cost="brokerage = 20.0\n"), _cfg())
    assert before["costs_file"] != after["costs_file"]
    assert before["tax_file"] == after["tax_file"]


def test_actions_and_indices_enter_the_identity(tmp_path):
    root = _root(tmp_path)
    act = pd.DataFrame({"isin": ["X"], "ex_date": [date(2010, 1, 4)], "factor": [0.5]})
    idx = {"NIFTY50_PRICE": pd.DataFrame({"date": [date(2010, 1, 4)], "close": [5000.0]})}
    base = _fp(root, _cfg(), act, idx)
    assert _fp(root, _cfg(), act.assign(factor=[0.4]), idx)["actions"] != base["actions"]
    idx2 = {"NIFTY50_PRICE": idx["NIFTY50_PRICE"].assign(close=[5001.0])}
    assert _fp(root, _cfg(), act, idx2)["index:NIFTY50_PRICE"] != base["index:NIFTY50_PRICE"]


def test_side_tables_are_cut_at_the_period_end(tmp_path, monkeypatch):
    root = _root(tmp_path)
    data = tmp_path / "data"
    (data / "red_flag_events").mkdir(parents=True)
    monkeypatch.setenv("PFLAB_DATA_DIR", str(data))
    ev = pd.DataFrame({"isin": ["X"], "flag": ["auditor_resigned"],
                       "usable_from": [date(2012, 5, 2)]})
    path = data / "red_flag_events" / "events.parquet"
    cfg = _cfg(red_flags={"enabled": True})

    ev.to_parquet(path)
    base = _fp(root, cfg)["red_flag_events"]
    later = pd.DataFrame({"isin": ["Y"], "flag": ["default"],
                          "usable_from": [date(2019, 1, 2)]})
    pd.concat([ev, later]).to_parquet(path)
    assert _fp(root, cfg)["red_flag_events"] == base          # seal identity
    ev.assign(flag=["default"]).to_parquet(path)
    assert _fp(root, cfg)["red_flag_events"] != base          # consumed row edited


def test_disabled_side_tables_are_not_read(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "nothing_here"))
    fp = _fp(_root(tmp_path), _cfg())
    assert not {"red_flag_events", "shareholding", "insider_pit", "india_vix"} & set(fp)


def test_data_fingerprint_moves_with_any_input():
    panel = pd.DataFrame({"date": [date(2010, 1, 4)], "isin": ["X"], "close": [10.0]})
    a = artifacts.data_fingerprint(panel, extra={"inputs": {"costs_file": "a"}})
    b = artifacts.data_fingerprint(panel, extra={"inputs": {"costs_file": "b"}})
    assert a != b


def test_repair_inputs_enter_the_identity_cut_at_the_end(tmp_path):
    """2026-09-28: BE rows, the factor table and the dividend feed reach the
    engine only through the repaired panel; each is hashed, cut at the end."""
    root = _root(tmp_path)
    div = pd.DataFrame({"isin": ["X"], "ex_date": [date(2012, 5, 2)],
                        "dividend_per_share": [2.0]})
    be = pd.DataFrame({"date": [date(2012, 5, 2)], "isin": ["X"], "close": [10.0]})
    fac = pd.DataFrame({"isin": ["X"], "ex_date": [date(2011, 1, 3)], "factor": [0.5]})
    ri = {"dividends": div, "be_rows": be, "factor_table": fac}
    fp = lambda r: runner.input_fingerprints(_cfg(), P, {}, None, None, root=root,
                                             repair_inputs=r)
    base = fp(ri)
    later = {"dividends": pd.concat([div, div.assign(ex_date=[date(2018, 1, 1)])]),
             "be_rows": pd.concat([be, be.assign(date=[date(2019, 1, 1)])]),
             "factor_table": pd.concat([fac, fac.assign(ex_date=[date(2020, 1, 1)])])}
    assert fp(later) == base                                   # seal identity
    for key, col, val in (("dividends", "dividend_per_share", 2.5),
                          ("be_rows", "close", 11.0), ("factor_table", "factor", 0.25)):
        edited = {**ri, key: ri[key].assign(**{col: [val]})}
        assert fp(edited)[f"repair:{key}"] != base[f"repair:{key}"], key
