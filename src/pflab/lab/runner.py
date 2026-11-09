"""The host side of the lab (S80 phase 2): builds the replay data once, writes a job folder, runs the policies in the sandbox and reads the scorecards back.

    panel_data(root, pm_dir)        the cleaned wide panel 2004-2021 (adjusted closes, turnover), the four index ETFs, the benchmark, cached under <pm_dir>/lab/
    write_job(work, data, ...)      one job folder (engine, toolkit, runner, data, the policies' files, job.json)
    run(...)                        the sandbox (Docker; the uncontained subprocess only when the workshop asks for it by name, as for every model-written program)

2022-2025 is spent: the panel stops at 2021-12-31 inside the query. The history window is 2004-2017; 2018-2021 is the final check, which `lab/service.py` allows once per variant.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab.agents import sandbox as sb

PANEL_START, PANEL_END = date(2004, 1, 1), date(2021, 12, 31)
HISTORY = (date(2005, 1, 1), date(2017, 12, 31))               # the walk-forward window: the first year only feeds the signals
FINAL = (date(2018, 1, 1), date(2021, 11, 30))                 # the one final check (2022-2025 stays spent)
ETFS = {"NIFTYBEES": "EQUITY", "JUNIORBEES": "EQUITY", "BANKBEES": "EQUITY", "GOLDBEES": "LISTED_NONEQUITY"}
# S81 (A48): the core ETFs the live baseline buys that had NO price history in 2005-2017 (the Nifty 500 ETF listed in 2023, the Nasdaq 100 ETF in 2021). The replay models each as its INDEX
# TOTAL-RETURN series less a stated yearly cost, so the lab can test a core-and-satellite book over the history window: key -> (series, yearly cost, why). The costs are stated
# ESTIMATES (not read from a primary source this session): an Indian index ETF charges roughly 0.04% to 0.25% a year in expenses and tracks slightly below its index; an overseas-index ETF
# about 0.6% plus a larger tracking gap. MON100 is built from the Nasdaq Composite PRICE index times USDINR (no dividends: about 1% a year short of a total-return series).
CORE_SYNTH = {"ETF:MONIFTY500": {"symbol": "MONIFTY500", "series": ("indices", "NIFTY500_TRI"), "cost": 0.0020, "tax": "EQUITY",
                                 "why": "no price history before 2023-10: modelled as the Nifty 500 total-return index less 0.20% a year (estimate)"},
              "ETF:MON100": {"symbol": "MON100", "series": ("global", "US_NASDAQ", "FX_USDINR"), "cost": 0.0060, "tax": "LISTED_NONEQUITY",
                             "why": "no price history before 2021-06: modelled as the Nasdaq Composite (price) in rupees less 0.60% a year (estimate); taxed as a non-equity fund"}}
N_NAMES = 600
LAB_DIR = Path(__file__).resolve().parent
JUMP = 0.60                                                    # a daily move beyond this is a data break and is removed from the path (as `construct/compare.py`)


def lab_dir(pm_dir: Path) -> Path:
    p = Path(pm_dir) / "lab"
    p.mkdir(parents=True, exist_ok=True)
    return p


def build_panel(root: Optional[Path] = None, n_names: int = N_NAMES, start: date = PANEL_START, end: date = PANEL_END) -> dict:
    """Read the market panel and return {px, turnover, meta, index, bench} (wide frames; keys are ISINs for stocks and 'ETF:<symbol>' for the four ETFs)."""
    from pflab import _duck
    from pflab.construct import compare
    from pflab.data import data_dir, indices
    root = Path(root) if root else data_dir()
    p = (root / "panel" / "prices.parquet").as_posix()
    etf = ",".join(repr(s) for s in ETFS)
    df = _duck.sql(f"SELECT date, isin, symbol, instrument_type AS kind, adj_close, turnover FROM '{p}' WHERE date >= DATE '{start}' AND date <= DATE '{end}' AND adj_close > 0 "
                   f"AND ((instrument_type = 'STK' AND series = 'EQ') OR (instrument_type = 'ETF' AND symbol IN ({etf}))) ORDER BY date").df()
    df["date"] = pd.to_datetime(df["date"])
    df["key"] = np.where(df["kind"] == "ETF", "ETF:" + df["symbol"].astype(str), df["isin"].astype(str))
    px = df.pivot_table(index="date", columns="key", values="adj_close", aggfunc="last").sort_index()
    to = df.pivot_table(index="date", columns="key", values="turnover", aggfunc="last").sort_index()
    med = to.median()
    obs = px.notna().sum()
    stocks = [k for k in px.columns if not k.startswith("ETF:") and obs[k] >= 300]
    keep = list(med.reindex(stocks).dropna().nlargest(n_names).index) + [k for k in px.columns if k.startswith("ETF:")]
    px, to = px[keep], to[keep]
    px = compare.clean(px.ffill(), JUMP)
    synth = core_synth_series(root, px.index)
    for k, (ser, _why) in synth.items():
        px[k] = ser
        to[k] = 1.0e9
    meta = {}
    sym = df.drop_duplicates("key").set_index("key")["symbol"]
    for k in keep:
        etf_k = k.startswith("ETF:")
        meta[k] = {"symbol": str(sym.get(k, k)), "etf": etf_k, "sector": None if etf_k else _sector(k), "tax": ETFS.get(str(sym.get(k, "")), "EQUITY") if etf_k else "EQUITY"}
    for k, (_ser, why) in synth.items():
        meta[k] = {"symbol": CORE_SYNTH[k]["symbol"], "etf": True, "sector": None, "tax": CORE_SYNTH[k]["tax"], "modelled": why}
    tri = indices.load("NIFTY500_TRI", root)
    s = tri.assign(date=pd.to_datetime(tri["date"])).set_index("date")["close"].sort_index()
    s = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
    return {"px": px, "turnover": to, "meta": meta, "index": s, "bench": s}


def core_synth_series(root: Path, index: pd.DatetimeIndex) -> dict:
    """{key: (series on the panel's dates, why)} for the core ETFs modelled from their index (see CORE_SYNTH). A series the data folder does not hold is left out."""
    out = {}
    for key, c in CORE_SYNTH.items():
        try:
            if c["series"][0] == "indices":
                d = pd.read_parquet(Path(root) / "indices" / f"{c['series'][1]}.parquet")
                s = d.assign(date=pd.to_datetime(d["date"])).set_index("date")["close"].sort_index()
            else:
                a = pd.read_parquet(Path(root) / "global" / f"{c['series'][1]}.parquet")
                b = pd.read_parquet(Path(root) / "global" / f"{c['series'][2]}.parquet")
                a = a.assign(date=pd.to_datetime(a["date"])).set_index("date")["adj_close"].sort_index()
                b = b.assign(date=pd.to_datetime(b["date"])).set_index("date")["adj_close"].sort_index()
                b = b.reindex(a.index.union(b.index)).ffill().reindex(a.index)
                s = (a * b).dropna()
            s = s[s > 0]
            s = s.reindex(index.union(s.index)).ffill().reindex(index)
            first = s.first_valid_index()
            if first is None:
                continue
            yrs = np.array([(d - first).days for d in s.index], dtype=float) / 365.25
            s = s * (1.0 - float(c["cost"])) ** np.maximum(yrs, 0.0)
            out[key] = (s, c["why"])
        except Exception:
            continue
    return out


def _sector(isin: str) -> Optional[str]:
    try:
        from pflab.paper import book
        return book._industry(isin)
    except Exception:
        return None


def panel_data(root: Optional[Path], pm_dir: Path, force: bool = False) -> dict:
    """The panel, cached in <pm_dir>/lab/ (rebuilt on `force`)."""
    d = lab_dir(pm_dir)
    f = d / "panel"
    if not force and (f / "px.parquet").exists():
        cached = load_panel(f)
        if all(k in cached["meta"] for k in CORE_SYNTH):                    # a panel cached before S81 lacks the modelled core ETFs: rebuilt once
            return cached
    data = build_panel(root)
    f.mkdir(exist_ok=True)
    save_panel(data, f)
    return data


def save_panel(data: dict, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    data["px"].to_parquet(folder / "px.parquet")
    data["turnover"].to_parquet(folder / "turnover.parquet")
    (folder / "meta.json").write_text(json.dumps(data["meta"]), encoding="utf-8")
    data["index"].rename("v").to_frame().to_parquet(folder / "index.parquet")
    data["bench"].rename("v").to_frame().to_parquet(folder / "bench.parquet")


def load_panel(folder: Path) -> dict:
    px, to = pd.read_parquet(folder / "px.parquet"), pd.read_parquet(folder / "turnover.parquet")
    px.index, to.index = pd.to_datetime(px.index), pd.to_datetime(to.index)
    idx = pd.read_parquet(folder / "index.parquet")["v"]
    bench = pd.read_parquet(folder / "bench.parquet")["v"]
    idx.index, bench.index = pd.to_datetime(idx.index), pd.to_datetime(bench.index)
    return {"px": px, "turnover": to, "meta": json.loads((folder / "meta.json").read_text(encoding="utf-8")), "index": idx, "bench": bench}


def cost_config() -> dict:
    """The charges the paper book takes, as flat per-side rates at a typical order (`construct/costs.rate`)."""
    from pflab.construct import costs
    return {"charges": {kind: {side: float(costs.rate(kind, side)) for side in ("buy", "sell")} for kind in ("equity", "etf")}}


def write_job(work: Path, data: dict, policies: List[dict], window, grid: Dict[str, list], cfg: Optional[dict] = None, n_shuffles: int = 20, n_mc: int = 1000, seed: int = 80,
              now_spec: Optional[dict] = None) -> None:
    """`policies`: [{"id", "code"}]. The job folder holds everything the run needs and nothing else (it is mounted read-only)."""
    for name in ("engine.py", "toolkit.py", "lab_runner.py"):
        shutil.copy(LAB_DIR / name, work / name)
    save_panel(data, work)
    files = []
    for i, p in enumerate(policies):
        fn = f"policy_{i}.py"
        (work / fn).write_text(p["code"], encoding="utf-8")
        files.append({"id": p["id"], "file": fn})
    job = {"cfg": cfg or {}, "window": [str(window[0]), str(window[1])] if window else None, "policies": files, "grid": grid, "n_shuffles": n_shuffles, "n_mc": n_mc, "seed": seed}
    job.update(now_spec or {})                                              # shadow: {"mode": "now", "day", "params", "prev"}
    (work / "job.json").write_text(json.dumps(job), encoding="utf-8")


class LabDocker(sb.Docker):
    """The same container and flags as every model-written program; only the script differs (the lab's runner travels in the read-only job folder)."""

    def command(self, work: Path, name: str, out: Path) -> List[str]:
        return sb._flags(name, work, out) + [self.image, "python", "-I", "/work/lab_runner.py", "/work"]


class LabLocal(sb.Local):
    """The uncontained subprocess: the test suite and the workshop's explicit PFLAB_SANDBOX=local only."""

    def run(self, work: Path, time_limit: int) -> subprocess.CompletedProcess:
        import os
        env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "PATH", "TEMP", "TMP")}
        env.update({"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""})
        return self._run([self.python, "-I", str(work / "lab_runner.py"), str(work)], cwd=str(work), env=env, capture_output=True, timeout=time_limit)


def pick_box(box=None):
    box = box or sb.pick()
    if isinstance(box, sb.Docker) and not isinstance(box, LabDocker):
        return LabDocker(box._run, box.image)
    if isinstance(box, sb.Local) and not isinstance(box, LabLocal):
        return LabLocal(box.python, box._run)
    return box


def run(data: dict, policies: List[dict], window, grid: Dict[str, list], cfg: Optional[dict] = None, n_shuffles: int = 20, n_mc: int = 1000, seed: int = 80,
        time_limit: int = 900, box=None, now_spec: Optional[dict] = None) -> dict:
    """Run the policies' grids over `window` in the sandbox. Returns {"results": {id: evaluate()}, "errors": {id: text}, "seconds", "contained": bool} or {"error": why}."""
    box = pick_box(box)
    work = Path(sb.shared_tempdir("pflab_lab_"))
    try:
        write_job(work, data, policies, window, grid, {**cost_config(), **(cfg or {})}, n_shuffles, n_mc, seed, now_spec)
        try:
            box.run(work, time_limit)
        except subprocess.TimeoutExpired:
            return {"error": f"the lab run was stopped after {time_limit} s (too many variants or too slow a policy)", "contained": box.contained}
        out = sb.read_result(work / "out.json")
        if not out:
            return {"error": "the lab run produced no result", "contained": box.contained}
        if "error" in out:
            return {"error": out["error"], "contained": box.contained}
        if out.get("fatal"):
            return {"error": out["fatal"][-400:], "contained": box.contained}
        out["contained"] = box.contained
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
