"""S91: the "Rates up 1%" study (protocol: docs/protocols/s91_rates_up_protocol.md, committed before this code). One test in the learner's counter. The rule is in `RULE` and in the protocol's JSON
block (`tests/test_s91_rates.py` compares them). `run` refuses when the protocol changed since it was registered. The result is written to docs/research/rates_study_results_s91.json; the Lab's preset
reads that file (`verdict()`): pass -> the shift is applied, fail or insufficient -> the preset stays off with the recorded reason."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
PROTOCOL = REPO / "docs" / "protocols" / "s91_rates_up_protocol.md"
RESULTS = REPO / "docs" / "research" / "rates_study_results_s91.json"
SERIES_CSV = REPO / "docs" / "research" / "in10y_monthly_fred_s91.csv"
NOTE, TEMPLATE = "s91:rates_up", "rates_s91:india10y"
FRED_ID, FRED_URL = "INDIRLTLT01STM", "https://fred.stlouisfed.org/graph/fredgraph.csv"

RULE = {"rate": "INDIRLTLT01STM", "shock_pp": 1.0, "development": ["2012-01", "2017-12"], "validation": ["2018-01", "2021-12"], "universe": "NIFTY100 members on 2011-12-31 with complete month ends",
        "model": "r = a + b*dy, OLS HC1", "comparator": "development mean", "dev_rule": "abs(t_b) >= counter.t_needed(N)", "val_rule": "paired t of squared-error differences >= 1.65 and same sign of b",
        "min_dev_months": 60, "min_names": 40, "wiring": "first-month shift b/21 per session, b ~ N(b, se^2) per path"}
VAL_T = 1.65


def protocol_sha() -> str:
    if not PROTOCOL.exists():
        raise FileNotFoundError(f"the protocol file is missing: {PROTOCOL}")
    return hashlib.sha256(PROTOCOL.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def register(con, now: datetime) -> List[str]:
    """Count the one test in the learner's counter (origin 'study'); idempotent by note."""
    from pflab.learner import counter
    if not PROTOCOL.exists() or con.execute("SELECT 1 FROM learn_tests WHERE note=?", [NOTE]).fetchone():
        return []
    counter.record(con, now, "study", TEMPLATE, {"protocol": "docs/protocols/s91_rates_up_protocol.md", "protocol_sha256": protocol_sha()}, note=NOTE)
    return [NOTE]


def protocol_ok(con) -> dict:
    r = con.execute("SELECT params_json FROM learn_tests WHERE note=?", [NOTE]).fetchone()
    if not r:
        return {"registered": False, "unchanged": False, "why": "not registered yet"}
    stored = json.loads(r[0] or "{}").get("protocol_sha256")
    same = stored == protocol_sha()
    return {"registered": True, "unchanged": same, "why": None if same else "the protocol file changed after it was registered"}


# --- data ---------------------------------------------------------------------------------------------------------------------------------------------

def fetch_yield(timeout: int = 60) -> pd.Series:
    """The monthly India 10-year yield from FRED's public CSV (no key). Saved beside the result so the study can be reproduced offline."""
    import requests
    r = requests.get(FRED_URL, params={"id": FRED_ID}, timeout=timeout)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["month", "yield"]
    df["yield"] = pd.to_numeric(df["yield"], errors="coerce")
    df = df.dropna()
    SERIES_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SERIES_CSV, index=False)
    return series_of(df)


def series_of(df: pd.DataFrame) -> pd.Series:
    s = pd.Series(df["yield"].to_numpy(float), index=pd.PeriodIndex(pd.to_datetime(df["month"]), freq="M"))
    return s[~s.index.duplicated()].sort_index()


def load_yield(offline: bool = False) -> pd.Series:
    if offline or SERIES_CSV.exists() and not _stale():
        return series_of(pd.read_csv(SERIES_CSV))
    return fetch_yield()


def _stale() -> bool:
    return False


def book_returns(root: Path, members: List[str]) -> pd.DataFrame:
    """Monthly returns (month = PeriodIndex) of each member from the panel's adjusted closes: last close of the month over the previous month's."""
    from pflab import _duck
    p = (Path(root) / "panel" / "prices.parquet").as_posix()
    q = ",".join(f"'{i}'" for i in members)
    d = _duck.sql(f"SELECT isin, date, adj_close FROM '{p}' WHERE isin IN ({q}) AND date >= DATE '2011-11-01' AND date <= DATE '2021-12-31' ORDER BY isin, date").df()
    d["date"] = pd.to_datetime(d["date"])
    d["m"] = d["date"].dt.to_period("M")
    last = d.sort_values("date").groupby(["isin", "m"])["adj_close"].last().unstack(0)
    return last.pct_change(fill_method=None).iloc[1:]


def universe(root: Path) -> List[str]:
    from pflab.data.index_membership import members_at
    t = pd.read_parquet(Path(root) / "index_membership" / "NIFTY100.parquet")
    return sorted(members_at(t, "NIFTY100", date(2011, 12, 31)))


# --- the statistics -----------------------------------------------------------------------------------------------------------------------------------

def ols_hc1(y: np.ndarray, x: np.ndarray) -> dict:
    X = np.column_stack([np.ones(len(x)), x])
    beta = np.linalg.solve(X.T @ X, X.T @ y)
    e = y - X @ beta
    n, k = X.shape
    XtXi = np.linalg.inv(X.T @ X)
    V = XtXi @ (X.T * (e ** 2)) @ X @ XtXi * n / (n - k)
    se = np.sqrt(np.diag(V))
    return {"a": float(beta[0]), "b": float(beta[1]), "se_b": float(se[1]), "t_b": float(beta[1] / se[1]), "n": int(n), "r2": float(1 - (e @ e) / (((y - y.mean()) ** 2).sum()))}


def paired_t(d: np.ndarray) -> float:
    d = np.asarray(d, float)
    sd = d.std(ddof=1)
    return float(d.mean() / (sd / np.sqrt(len(d)))) if sd > 0 else 0.0


def analyse(book: pd.Series, y: pd.Series, n_tests: int, names_used: int, names_in_index: int) -> dict:
    """The protocol's sections 4 and 5 on a monthly equal-weighted book return (PeriodIndex) and the monthly yield (PeriodIndex)."""
    from pflab.learner import counter
    dy = y.diff().dropna()
    dev_lo, dev_hi = (pd.Period(m, "M") for m in RULE["development"])
    val_lo, val_hi = (pd.Period(m, "M") for m in RULE["validation"])
    j = pd.concat([book.rename("r"), dy.rename("dy")], axis=1).dropna()
    dev, val = j[(j.index >= dev_lo) & (j.index <= dev_hi)], j[(j.index >= val_lo) & (j.index <= val_hi)]
    out = {"names_used": int(names_used), "names_in_index": int(names_in_index), "dev_months": int(len(dev)), "val_months": int(len(val)), "dy_sd_pp": float(dy.std()),
           "rule": RULE, "t_bar_dev": counter.t_needed(n_tests), "t_bar_val": VAL_T, "n_tests": int(n_tests)}
    if len(dev) < RULE["min_dev_months"] or names_used < RULE["min_names"] or len(val) < 24:
        out.update(verdict="insufficient", why=f"not tested: {len(dev)} development months (need {RULE['min_dev_months']}), {names_used} names (need {RULE['min_names']}), {len(val)} validation months")
        return out
    m1 = ols_hc1(dev["r"].to_numpy(), dev["dy"].to_numpy())
    a0 = float(dev["r"].mean())
    e0 = val["r"].to_numpy() - a0
    e1 = val["r"].to_numpy() - (m1["a"] + m1["b"] * val["dy"].to_numpy())
    d = e0 ** 2 - e1 ** 2
    t_val = paired_t(d)
    mv = ols_hc1(val["r"].to_numpy(), val["dy"].to_numpy())
    oos_r2 = float(1 - (e1 @ e1) / (e0 @ e0))
    dev_pass = abs(m1["t_b"]) >= out["t_bar_dev"]
    val_pass = t_val >= VAL_T and np.sign(mv["b"]) == np.sign(m1["b"])
    out.update(dev=m1, val_alone={"b": mv["b"], "t_b": mv["t_b"]}, b_ci95=[m1["b"] - 1.96 * m1["se_b"], m1["b"] + 1.96 * m1["se_b"]], paired_t_val=t_val, oos_r2=oos_r2,
               dev_pass=bool(dev_pass), val_pass=bool(val_pass), verdict="pass" if dev_pass and val_pass else "fail")
    out["response_per_100bp_pct"] = m1["b"] * 100
    out["why"] = _plain(out)
    return out


def _plain(o: dict) -> str:
    b, se = o["dev"]["b"] * 100, o["dev"]["se_b"] * 100
    s = (f"Tested on India's 10-year yield and 91 names of the NIFTY 100, 2012-2017 to fit and 2018-2021 to check once: a rise of 1 point moved the book by {b:+.1f}% a month (give or take {1.96 * se:.1f}); "
         f"development t {o['dev']['t_b']:.2f} against a bar of {o['t_bar_dev']:.2f}; on the check years it predicted monthly moves {'better' if o['paired_t_val'] > 0 else 'worse'} than a plain average "
         f"(t {o['paired_t_val']:.2f} against {VAL_T}).")
    return s.replace("91 names", f"{o['names_used']} names")


def run(con, root: Path, now: datetime, y: Optional[pd.Series] = None, write: bool = True) -> dict:
    if not PROTOCOL.exists():
        raise FileNotFoundError("the protocol file is missing")
    ok = protocol_ok(con)
    if not ok["registered"] or not ok["unchanged"]:
        raise RuntimeError(f"the study is not allowed to run: {ok['why']}")
    from pflab.learner import counter
    members = universe(root)
    rets = book_returns(root, members)
    full = rets.dropna(axis=1, how="any")
    book = full.mean(axis=1)
    y = y if y is not None else load_yield()
    res = analyse(book, y, counter.n_tests(con), full.shape[1], len(members))
    res.update(ran_at=str(now)[:19], protocol_sha256=protocol_sha(), series="FRED INDIRLTLT01STM (OECD), monthly average", series_last=str(y.index[-1]))
    if write:
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        RESULTS.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        if res["verdict"] in ("pass", "fail"):                                # an insufficient result is not evidence either way: the row stays open
            con.execute("UPDATE learn_tests SET passed=?, n_dev=?, t_dev=?, threshold_dev=? WHERE note=? AND passed IS NULL",
                        [res["verdict"] == "pass", res["dev"]["n"], res["dev"]["t_b"], res["t_bar_dev"], NOTE])
    return res


# --- what the Lab reads -------------------------------------------------------------------------------------------------------------------------------

def verdict(path: Optional[Path] = None) -> dict:
    """{"enabled": bool, "why": plain words, "b": per-1pp monthly response, "se_b", "r2"}. No result file: not tested yet."""
    p = Path(path) if path else RESULTS
    if not p.exists():
        return {"enabled": False, "why": "not tested yet: the study has not run"}
    r = json.loads(p.read_text(encoding="utf-8"))
    if r.get("verdict") == "pass":
        return {"enabled": True, "why": r["why"], "b": r["dev"]["b"], "se_b": r["dev"]["se_b"], "r2": r["dev"]["r2"], "oos_r2": r.get("oos_r2")}
    return {"enabled": False, "why": r.get("why") or "tested: not supported"}
