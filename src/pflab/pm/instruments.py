"""Instrument master: one row per security key (PLAN §3, §4).

Sources: the price panel (every ISIN NSE has traded, 2004 on), the AMFI scheme
master (`NAVAll.txt`: every mutual fund scheme and ETF with an ISIN), and the
existing name and sector maps. Bonds, SGBs and G-secs enter in S8/S10 through
`classify`.

`tax_class` is a label that S2's dated rule tables key on; no rate lives here.
Where the label depends on facts we do not have (a scheme's actual equity
share, a listed/unlisted bond) it is REVIEW with the reason, never a guess.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

from pflab.data import data_dir

AMFI_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"  # amfiindia.com/spages redirects here

# tax_class labels (rules attach in S2)
EQUITY = "EQUITY"                          # listed equity, equity MF, equity ETF
LISTED_NONEQUITY = "LISTED_NONEQUITY"      # listed bond, gold/silver/foreign ETF
DEBT_MF = "DEBT_MF"                        # specified vs pre-2023 split by purchase date in S2
OTHER_MF = "OTHER_MF"                      # non-equity, non-specified funds
SGB = "SGB"
UNLISTED_DEBT = "UNLISTED_DEBT"
BUSINESS_TRUST = "BUSINESS_TRUST"          # REIT / InvIT units; rule row is S2's to confirm
PHYSICAL_GOLD = "PHYSICAL_GOLD"
REVIEW = "REVIEW"
TAX_CLASSES = (EQUITY, LISTED_NONEQUITY, DEBT_MF, OTHER_MF, SGB, UNLISTED_DEBT,
               BUSINESS_TRUST, PHYSICAL_GOLD, REVIEW)

# asset_class labels
EQUITY_A, ETF_A, REIT_A, INVIT_A, MF_A, SGB_A, BOND_A = (
    "equity", "etf", "reit", "invit", "mutual_fund", "sgb", "bond")

# Ordered: first match on the lower-cased AMFI category wins.
_CATEGORY_RULES = [
    (r"gold etf|silver etf|etfs investing overseas", LISTED_NONEQUITY, "gold/silver/foreign ETF"),
    (r"debt etf", DEBT_MF, "debt ETF"),
    (r"equity etf", EQUITY, "equity ETF"),
    (r"hybrid etf|other\s+etf", REVIEW, "ETF type needs the scheme's asset mix"),
    (r"overseas fund of funds|fof overseas", OTHER_MF, "overseas fund of funds"),
    (r"fund of funds scheme \(domestic\)|fof domestic", REVIEW, "domestic FoF: depends on underlying"),
    (r"index funds - equity", EQUITY, "equity index fund"),
    (r"index funds - debt", DEBT_MF, "debt index fund"),
    (r"index funds - hybrid|other scheme - index funds", REVIEW, "index fund type unknown"),
    (r"arbitrage", EQUITY, "arbitrage: equity-oriented"),
    (r"aggressive hybrid", EQUITY, "65-80% equity by SEBI category"),
    (r"equity savings", EQUITY, "equity incl. arbitrage >= 65% by SEBI category"),
    (r"conservative hybrid", DEBT_MF, "10-25% equity: debt-oriented"),
    (r"balanced|dynamic asset allocation|multi asset", REVIEW, "hybrid: depends on scheme's equity share"),
    (r"solution oriented|life cycle|children|retirement", REVIEW, "solution scheme: depends on scheme"),
    (r"equity scheme|elss", EQUITY, "equity scheme"),
    (r"debt scheme|income/debt|gilt|liquid|money market|overnight|^income$|interval fund", DEBT_MF,
     "debt scheme"),
]
_CATEGORY_RULES = [(re.compile(p), c, r) for p, c, r in _CATEGORY_RULES]


_OTHER_ETF_NAME_RULES = [
    (re.compile(r"\b(gold|silver)\b"), LISTED_NONEQUITY, "gold/silver ETF by scheme name"),
    (re.compile(r"liquid|overnight|gilt|g-?sec|\bsdl\b|treasury|money market|\bbond\b|\bbharat\b"),
     DEBT_MF, "debt ETF by scheme name"),
]


def scheme_class(category: Optional[str], name: Optional[str] = None) -> tuple:
    """(asset_class, tax_class, reason) from an AMFI category string. AMFI files
    most ETFs under 'Other ETFs'; for those only, the scheme name separates
    gold/silver and debt ETFs. Equity ETFs there stay REVIEW (no safe keyword)."""
    cat = (category or "").lower().strip()
    asset = ETF_A if "etf" in cat else MF_A
    if re.search(r"other\s+etf", cat) and name:
        for rx, tax, why in _OTHER_ETF_NAME_RULES:
            if rx.search(name.lower()):
                return asset, tax, f"AMFI 'Other ETFs': {why}"
    for rx, tax, why in _CATEGORY_RULES:
        if rx.search(cat):
            return asset, tax, f"AMFI category: {why}"
    return asset, REVIEW, f"unmapped AMFI category {category!r}"


def classify(isin: str, *, instrument_type: Optional[str] = None, series: Optional[str] = None,
             category: Optional[str] = None, name: Optional[str] = None,
             listed: Optional[bool] = None) -> tuple:
    """(asset_class, tax_class, reason) for any security the system will meet."""
    if category:
        return scheme_class(category, name)
    if instrument_type == "STK":
        return EQUITY_A, EQUITY, "listed equity share"
    if instrument_type == "REIT":
        return REIT_A, BUSINESS_TRUST, "REIT units"
    if instrument_type == "INVIT":
        return INVIT_A, BUSINESS_TRUST, "InvIT units"
    if instrument_type == "ETF":
        return ETF_A, REVIEW, "ETF not found in AMFI scheme master"
    if str(isin).startswith("PHYS:GOLD"):
        return "gold_physical", PHYSICAL_GOLD, "physical gold (no ISIN; key PHYS:GOLD<purity>)"
    nm = (name or "").upper()
    if (series or "").upper() == "GB" or re.search(r"\bSGB\b|SOVEREIGN GOLD", nm):
        return SGB_A, SGB, "sovereign gold bond"
    if (series or "").upper() in ("GS", "TB"):
        return BOND_A, LISTED_NONEQUITY, "government security"
    code = str(isin)[7:9]  # INE + 4-char issuer + series char, then type
    if str(isin).startswith("INE") and code == "07":
        if listed is True:
            return BOND_A, LISTED_NONEQUITY, "listed debenture/bond"
        if listed is False:
            return BOND_A, UNLISTED_DEBT, "unlisted debenture/bond"
        return BOND_A, REVIEW, "debenture: listed status unknown"
    if str(isin).startswith("INE") and code == "01":
        return EQUITY_A, EQUITY, "equity share"
    return "unknown", REVIEW, "ISIN type not recognised"


# --- AMFI -----------------------------------------------------------------

_HEADER = re.compile(r"^(Open Ended|Close Ended|Interval Fund) Schemes?\s*\((.*)\)\s*$")


def parse_navall(text: str) -> pd.DataFrame:
    """NAVAll.txt -> one row per scheme code with amc and category."""
    rows, amc, cat = [], None, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Scheme Code"):
            continue
        if ";" not in line:
            m = _HEADER.match(line)
            if m:
                cat = m.group(2).strip()
            else:
                amc = line
            continue
        f = [x.strip() for x in line.split(";")]
        if len(f) < 8 or not f[0].isdigit():
            continue
        rows.append({"scheme_code": f[0],
                     "isin_1": f[1] if f[1] not in ("", "-") else None,
                     "isin_2": f[2] if f[2] not in ("", "-") else None,
                     "name": f[3], "plan": f[4] or None, "option": f[5] or None,
                     "nav": pd.to_numeric(f[6], errors="coerce"),
                     "nav_date": pd.to_datetime(f[7], format="%d-%b-%Y", errors="coerce"),
                     "amc": amc, "category": cat})
    df = pd.DataFrame(rows, columns=["scheme_code", "isin_1", "isin_2", "name", "plan", "option",
                                     "nav", "nav_date", "amc", "category"])
    df["nav_date"] = df["nav_date"].dt.date
    return df.drop_duplicates("scheme_code", keep="last").reset_index(drop=True)


def fetch_amfi(root: Optional[Path] = None, session=None) -> tuple:
    """Download NAVAll.txt, keep the raw file (immutable, named by date) and
    return (text, sha256)."""
    import requests
    s = session or requests
    r = s.get(AMFI_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    text = r.content.decode("utf-8", errors="replace")
    sha = hashlib.sha256(r.content).hexdigest()
    d = (root or data_dir()) / "amfi"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"NAVAll_{date.today():%Y-%m-%d}.txt").write_bytes(r.content)
    return text, sha


# --- master ---------------------------------------------------------------

def panel_instruments(root: Optional[Path] = None) -> pd.DataFrame:
    """One row per panel key: isin, symbol, series, instrument_type, first/last date."""
    from pflab import _duck
    p = (root or data_dir()) / "panel" / "prices.parquet"
    return _duck.sql(f"""
        SELECT isin, arg_max(symbol, date) AS symbol, arg_max(series, date) AS series,
               arg_max(instrument_type, date) AS instrument_type,
               min(date) AS valid_from, max(date) AS valid_to
        FROM read_parquet('{p.as_posix()}') GROUP BY isin""").df()


def _latest_names(root: Optional[Path]) -> dict:
    try:
        from pflab.data import name_map
        n = name_map.load(root).dropna(subset=["isin"]).sort_values("last_seen")
        return n.drop_duplicates("isin", keep="last").set_index("isin")["name"].to_dict()
    except Exception:
        return {}


def _latest_sectors(root: Optional[Path]) -> dict:
    try:
        from pflab.data import sector_map
        s = sector_map.load(root).sort_values("capture_date")
        return s.drop_duplicates("isin", keep="last").set_index("isin")["industry"].to_dict()
    except Exception:
        return {}


_REAL_ISIN = re.compile(r"^IN[A-Z0-9]{10}$")
MASTER_COLUMNS = ["isin", "key_kind", "asset_class", "tax_class", "tax_class_reason", "listed",
                  "symbol", "name", "issuer", "sector", "scheme_code", "category",
                  "valid_from", "valid_to", "successor_isin", "source", "built_at"]


def build_master(panel: pd.DataFrame, amfi: pd.DataFrame, names: Optional[dict] = None,
                 sectors: Optional[dict] = None, now: Optional[datetime] = None) -> pd.DataFrame:
    names, sectors, now = names or {}, sectors or {}, now or datetime.now()
    by_isin = {}
    for r in amfi.itertuples():
        for i in (r.isin_1, r.isin_2):
            if isinstance(i, str) and i:
                by_isin[i] = r  # amfi is ordered; a later scheme code wins
    rows, seen = [], set()
    for r in panel.itertuples():
        a = by_isin.get(r.isin)
        cat = a.category if a is not None and r.instrument_type == "ETF" else None
        asset, tax, why = classify(r.isin, instrument_type=r.instrument_type, series=r.series,
                                   category=cat, name=a.name if cat else None)
        real = bool(_REAL_ISIN.match(r.isin))
        rows.append(dict(isin=r.isin, key_kind="isin" if real else "synthetic", asset_class=asset,
                         tax_class=tax, tax_class_reason=why, listed=True, symbol=r.symbol,
                         name=names.get(r.isin) or (a.name if a is not None else None),
                         issuer=r.isin[:9] if real else None, sector=sectors.get(r.isin),
                         scheme_code=a.scheme_code if a is not None else None,
                         category=a.category if a is not None else None,
                         valid_from=r.valid_from, valid_to=r.valid_to, successor_isin=None,
                         source="panel+amfi" if a is not None else "panel", built_at=now))
        seen.add(r.isin)
    for i, a in by_isin.items():
        if i in seen:
            continue
        asset, tax, why = scheme_class(a.category, a.name)
        rows.append(dict(isin=i, key_kind="isin", asset_class=asset, tax_class=tax,
                         tax_class_reason=why, listed=asset == ETF_A, symbol=None, name=a.name,
                         issuer=None, sector=None, scheme_code=a.scheme_code, category=a.category,
                         valid_from=None, valid_to=None, successor_isin=None, source="amfi",
                         built_at=now))
    out = pd.DataFrame(rows, columns=MASTER_COLUMNS)
    for c in ("valid_from", "valid_to"):
        out[c] = pd.to_datetime(out[c]).dt.date
    return out


def load_into_store(con, master: pd.DataFrame, amfi: pd.DataFrame, source_sha: str,
                    now: Optional[datetime] = None) -> None:
    """Replace the instruments and amfi_schemes tables (rebuilt from sources each run)."""
    now = now or datetime.now()
    a = amfi.copy()
    a["source_doc_sha"], a["ingested_at"] = source_sha, now
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM instruments")
        con.execute("DELETE FROM amfi_schemes")
        con.register("_m", master)
        con.register("_a", a)
        con.execute(f"INSERT INTO instruments SELECT {', '.join(MASTER_COLUMNS)} FROM _m")
        con.execute("""INSERT INTO amfi_schemes
            SELECT scheme_code, isin_1, isin_2, name, plan, option, amc, category, nav, nav_date,
                   source_doc_sha, ingested_at FROM _a""")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("_m")
        con.unregister("_a")


def build_and_load(con, root: Optional[Path] = None, amfi_text: Optional[str] = None,
                   amfi_sha: Optional[str] = None) -> dict:
    if amfi_text is None:
        amfi_text, amfi_sha = fetch_amfi(root)
    amfi = parse_navall(amfi_text)
    master = build_master(panel_instruments(root), amfi, _latest_names(root), _latest_sectors(root))
    load_into_store(con, master, amfi, amfi_sha or "")
    return {"instruments": len(master), "amfi_schemes": len(amfi),
            "review": int((master.tax_class == REVIEW).sum())}


def register_missing(con, rows: List[dict], source: str, now: Optional[datetime] = None) -> List[dict]:
    """Add held instruments the master does not know yet (SGBs, a new listing such as an IPO allotment).
    Each row: isin, and any of name, symbol, series, listed. Classified by `classify` from the exchange
    series and name only; nothing is guessed (an unrecognised ISIN is stored as REVIEW). Known ISINs are left
    alone. Returns the rows added."""
    now = now or datetime.now()
    have = {r[0] for r in con.execute("SELECT isin FROM instruments").fetchall()}
    added = []
    for r in rows:
        if r["isin"] in have or any(a["isin"] == r["isin"] for a in added):
            continue
        asset, tax, why = classify(r["isin"], series=r.get("series"), name=r.get("name"), listed=r.get("listed"))
        rec = dict(isin=r["isin"], key_kind="isin", asset_class=asset, tax_class=tax, tax_class_reason=why,
                   listed=r.get("listed"), symbol=r.get("symbol"), name=r.get("name"), issuer=r["isin"][:9],
                   sector=None, scheme_code=None, category=None, valid_from=None, valid_to=None,
                   successor_isin=None, source=source, built_at=now)
        con.execute(f"INSERT INTO instruments ({', '.join(MASTER_COLUMNS)}) VALUES ({', '.join('?' * len(MASTER_COLUMNS))})",
                    [rec[c] for c in MASTER_COLUMNS])
        added.append(rec)
    return added
