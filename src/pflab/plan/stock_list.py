"""The investor's stock list (PFLAB_PM_DIR/stock_list.toml): add a name and have every agent pick it up (S38).

`add(symbol)` resolves the NSE symbol to its ISIN and BSE scrip (instrument master, BSE scrip map), appends it to
the list, and then runs what a new name needs: the guards (surveillance + filed-results safety, pulling its
results from BSE), and a knowledge-graph refresh (company, sector, filings, results, verdict). News arrives with
the next GKG collection. The list file stays the single source; nothing here buys anything.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from pflab import _duck
from pflab import _toml


def path() -> Path:
    from pflab.pm import store
    return store.pm_dir() / "stock_list.toml"


def load(p: Optional[Path] = None) -> List[dict]:
    p = p or path()
    return _toml.load(p).get("stocks", []) if p.exists() else []


def resolve(con, symbol: str, root=None) -> Dict[str, Optional[str]]:
    """NSE symbol -> isin, name, sector (instrument master, latest listing) and BSE scrip (scrip map)."""
    from pflab.data import data_dir
    root = root or data_dir()
    row = con.execute("SELECT isin, name, sector FROM instruments WHERE upper(symbol) = ? "
                      "ORDER BY valid_to DESC NULLS FIRST LIMIT 1", [symbol.upper()]).fetchone()
    if not row:
        raise LookupError(f"{symbol}: not in the instrument master (is it an NSE symbol?)")
    isin, name, sector = row
    sc = _duck.sql(f"select scrip_code from '{root}/bse_scrip_isin/map.parquet' where isin = '{isin}' limit 1").fetchone()
    return {"symbol": symbol.upper(), "isin": isin, "name": name, "sector": sector, "scrip": sc[0] if sc else None}


def _write(stocks: List[dict], p: Path) -> None:
    head = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("stocks"):
                break
            head.append(line)
    def entry(s: dict) -> str:
        kv = [f'{k} = "{s[k]}"' for k in ("symbol", "isin", "scrip") if s.get(k)]
        if s.get("aliases"):                       # names to match in news and questions (lower case)
            kv.append("aliases = [" + ", ".join(f'"{a}"' for a in s["aliases"]) + "]")
        return "  { " + ", ".join(kv) + " },"
    body = ["stocks = ["] + [entry(s) for s in stocks] + ["]"]
    p.write_text("\n".join(head + body) + "\n", encoding="utf-8")


def add(con, symbol: str, asof: Optional[date] = None, p: Optional[Path] = None, run_agents: bool = True) -> dict:
    p = p or path()
    asof = asof or date.today()
    stocks = load(p)
    if any(s["symbol"].upper() == symbol.upper() for s in stocks):
        return {"added": False, "why": f"{symbol.upper()} is already on the list"}
    r = resolve(con, symbol)
    stocks.append({k: r[k] for k in ("symbol", "isin", "scrip")})
    _write(stocks, p)
    out = {"added": True, **r}
    if run_agents:
        from pflab.kg import build as kb
        from pflab.plan import guards as gd
        gs = gd.check_all(con, asof, [s for s in stocks if s["symbol"] == r["symbol"]])
        out["guard"] = gs[0].verdict
        out["reasons"] = gs[0].reasons
        u = kb.universe(con, stocks)
        u1 = u[u["isin"] == r["isin"]]
        out["graph"] = {"portfolio": kb.portfolio(con, u1, [s for s in stocks if s["symbol"] == r["symbol"]]),
                        "filings": kb.filings(con, u1, asof - timedelta(days=365)), "results": kb.results(con, u1),
                        "guards": kb.guards(con, gs, datetime(asof.year, asof.month, asof.day, 21))}
    return out


def remove(symbol: str, p: Optional[Path] = None) -> bool:
    p = p or path()
    stocks = load(p)
    keep = [s for s in stocks if s["symbol"].upper() != symbol.upper()]
    if len(keep) == len(stocks):
        return False
    _write(keep, p)
    return True
