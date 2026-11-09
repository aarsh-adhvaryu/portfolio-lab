"""The scope of the news collection and the graph: one file, `<data>/kg/scope.json`, which the collector reads on each run.

    {"version": 1, "built": "...", "names": [{"isin","symbol","name","aliases":[...],"text":bool,"origin":str}, ...],
     "extra_isins": [...]}

Origins: `stock_list` (the app's alias file), `nifty100` (the 100 largest current members), `nifty500` (the rest of the index: article tags only,
no text), `etf` (core ETFs), `found` (the system finds them itself: unusual news volume or tone shift in the last 30 days of the collected articles,
at most 40), `held` (passed by the coordinator through `merge_held`; his holdings are never read here). `text` marks the names whose article text is collected
(about 150). An alias belongs to one ISIN only: an alias two ISINs share is dropped for both.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

STRIP = re.compile(r"\b(limited|ltd\.?|company|co\.?|corporation|corp\.?|\(india\)|india limited)\b", re.I)
MIN_ALIAS = 6
TEXT_CAP = 150
FOUND_CAP = 40
CORE_ETFS = {"NIFTYBEES": ["nippon india etf nifty 50 bees", "nifty bees"], "GOLDBEES": ["nippon india etf gold bees", "gold bees"],
             "JUNIORBEES": ["nippon india etf nifty next 50 junior bees"], "BANKBEES": ["nippon india etf bank bees"],
             "MON100": ["motilal oswal nasdaq 100 etf"], "MAFANG": ["mirae asset nyse fang+ etf"],
             "HNGSNGBEES": ["nippon india etf hang seng bees"], "MASPTOP50": ["mirae asset s&p 500 top 50 etf"],
             "N100": ["motilal oswal nasdaq 100 etf"], "SETFNIF50": ["sbi nifty 50 etf"], "GOLDCASE": ["zerodha gold etf"]}


def kg_dir(root: Path) -> Path:
    return Path(root) / "kg"


def scope_path(root: Path) -> Path:
    return kg_dir(root) / "scope.json"


def norm_name(name: str) -> str:
    s = STRIP.sub(" ", str(name or "")).lower()
    s = re.sub(r"[^a-z0-9&+ ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def aliases_for(name: str, extra: Iterable[str] = ()) -> List[str]:
    out: List[str] = []
    for a in [norm_name(name), *[norm_name(x) for x in extra]]:
        if len(a) >= MIN_ALIAS and a not in out:
            out.append(a)
    return out


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def dedupe_aliases(names: List[dict]) -> List[dict]:
    """An alias that two different ISINs carry is ambiguous: dropped for both (a name without an alias is kept but matches nothing)."""
    owner: Dict[str, set] = {}
    for n in names:
        for a in n["aliases"]:
            owner.setdefault(a, set()).add(n["isin"])
    for n in names:
        n["aliases"] = [a for a in n["aliases"] if len(owner[a]) == 1]
    return names


def load(root: Path) -> dict:
    """The scope file, or an empty scope when it does not exist (the collector then does nothing and says so)."""
    p = scope_path(root)
    if not p.exists():
        return {"version": 1, "names": [], "extra_isins": []}
    return json.loads(p.read_text(encoding="utf-8"))


def alias_index(scope: dict) -> Dict[str, str]:
    """alias -> isin for the whole scope (aliases are unique by construction)."""
    out: Dict[str, str] = {}
    for n in dedupe_aliases([dict(x, aliases=list(x.get("aliases", []))) for x in scope.get("names", [])]):
        for a in n["aliases"]:
            out[a] = n["isin"]
    return out


def text_isins(scope: dict) -> set:
    return {n["isin"] for n in scope.get("names", []) if n.get("text")} | set(scope.get("extra_isins", []))


def build_scope(root: Path, alias_file: Optional[Path] = None, today: Optional[date] = None) -> dict:
    """Build `scope.json` from what the app's market data tracks. No holdings are read (the coordinator passes those with `merge_held`)."""
    root = Path(root)
    names: Dict[str, dict] = {}
    idx = root / "index_membership"
    nm = pd.read_parquet(idx / "name_map.parquet").sort_values("last_seen")
    name_of = {r.isin: r.name for r in nm.itertuples()}
    sym_of = {r.isin: r.symbol for r in nm.itertuples()}

    def add(isin: str, name: str, symbol: str, extra: Iterable[str], origin: str, text: bool) -> None:
        if not isin:
            return
        cur = names.get(isin)
        al = aliases_for(name, extra)
        if cur:
            cur["aliases"] = list(dict.fromkeys(cur["aliases"] + al))
            cur["text"] = cur["text"] or text
            return
        names[isin] = {"isin": isin, "symbol": symbol, "name": name, "aliases": al, "text": text, "origin": origin}

    af = alias_file or root / "_daily" / "gkg_aliases.json"
    if af.exists():
        for isin, al in json.loads(af.read_text(encoding="utf-8")).items():
            add(isin, "", sym_of.get(isin, ""), al, "stock_list", True)       # the alias file's own names only (it overrides misleading names)
    n100 = pd.read_parquet(idx / "NIFTY100.parquet")
    for r in n100[n100["to_date"].isna()].sort_values("symbol").itertuples():
        add(r.isin, name_of.get(r.isin, r.symbol), r.symbol, [], "nifty100", True)
    n500 = pd.read_parquet(idx / "NIFTY500.parquet")
    for r in n500[n500["to_date"].isna()].sort_values("symbol").itertuples():
        if r.isin not in names:
            add(r.isin, name_of.get(r.isin, r.symbol), r.symbol, [], "nifty500", False)
    sm = pd.read_parquet(root / "panel" / "symbol_isin_map.parquet")
    for sym, al in CORE_ETFS.items():
        cur = sm[(sm["symbol"] == sym) & (sm["valid_to"].astype(str) >= "2999")]
        if len(cur):
            add(cur.iloc[0]["isin"], sym, sym, al, "etf", True)
    # the text cap: the stock list and the ETFs first, then the index names by symbol, never more than TEXT_CAP
    order = {"stock_list": 0, "etf": 1, "held": 2, "nifty100": 3, "found": 4, "nifty500": 9}
    ranked = sorted(names.values(), key=lambda n: (order.get(n["origin"], 8), n["symbol"] or ""))
    for i, n in enumerate(ranked):
        n["text"] = bool(n["text"]) and i < TEXT_CAP
    out = {"version": 1, "built": (today or date.today()).isoformat(), "names": dedupe_aliases(ranked), "extra_isins": []}
    _atomic_write(scope_path(root), json.dumps(out, indent=1, sort_keys=True))
    return out


def merge_held(root: Path, isins: Iterable[str], names: Optional[Dict[str, List[str]]] = None) -> dict:
    """The coordinator passes his held names (ISINs, optionally aliases): they get text collection and origin `held`."""
    sc = load(root)
    have = {n["isin"]: n for n in sc["names"]}
    for isin in isins:
        if isin in have:
            have[isin]["text"] = True
            if names and isin in names:
                have[isin]["aliases"] = list(dict.fromkeys(have[isin]["aliases"] + aliases_for("", names[isin])))
        else:
            sc["names"].append({"isin": isin, "symbol": "", "name": "", "text": True, "origin": "held",
                                "aliases": aliases_for("", (names or {}).get(isin, []))})
    sc["names"] = dedupe_aliases(sc["names"])
    _atomic_write(scope_path(root), json.dumps(sc, indent=1, sort_keys=True))
    return sc


def find_names(root: Path, today: Optional[date] = None, cap: int = FOUND_CAP, window: int = 30) -> List[dict]:
    """The names the system finds itself: among the NIFTY 500 names (tags only) not already in text scope, those whose article count in the last
    `window` days is unusually high against their own earlier collected history (z >= 2, at least 8 articles), or whose mean tone moved by
    at least 1.5 points against it. At most `cap`, strongest first. Reads only the collected GKG rows (point-in-time by their date)."""
    from pflab.kg2 import news
    today = today or date.today()
    df = news.load_rows(root)
    if df.empty:
        return []
    sc = load(root)
    in_text = text_isins(sc)
    df = df[~df["isin"].isin(in_text)]
    cut = today - timedelta(days=window)
    df["d"] = pd.to_datetime(df["date"]).dt.date
    out = []
    for isin, g in df.groupby("isin"):
        recent, base = g[g["d"] > cut], g[g["d"] <= cut]
        if len(recent) < 8 or base.empty:
            continue
        per = base.groupby("d").size().reindex(pd.date_range(base["d"].min(), cut).date, fill_value=0)
        weeks = per.rolling(window, min_periods=window).sum().dropna()
        mu, sd = (float(weeks.mean()), float(weeks.std())) if len(weeks) > 5 else (float(per.mean() * window), 0.0)
        z = (len(recent) - mu) / (sd if sd > 0 else max(mu ** 0.5, 1.0))
        dt = float(recent["tone"].mean() - base["tone"].mean()) if base["tone"].notna().any() and recent["tone"].notna().any() else 0.0
        if z >= 2 or abs(dt) >= 1.5:
            out.append({"isin": isin, "z_volume": round(z, 2), "tone_shift": round(dt, 2), "n_recent": int(len(recent))})
    out.sort(key=lambda r: (-max(r["z_volume"], abs(r["tone_shift"])), r["isin"]))
    return out[:cap]


def apply_found(root: Path, found: List[dict]) -> int:
    """Mark the found names as text scope (origin `found` kept in `origin` only for names that were tags-only). Returns how many were added."""
    sc = load(root)
    ids = {f["isin"] for f in found}
    n = 0
    for x in sc["names"]:
        if x["isin"] in ids and not x.get("text"):
            x["text"], x["origin"] = True, "found"
            n += 1
    _atomic_write(scope_path(root), json.dumps(sc, indent=1, sort_keys=True))
    return n
