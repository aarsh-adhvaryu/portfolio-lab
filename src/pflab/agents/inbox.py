"""The inbox: The investor drops any data file (a Tijori or Screener export, a broker sheet, a PDF) into PFLAB_PM_DIR/inbox;
the system reads it into the knowledge graph. Numbers come from the file, never from a model.

For every sheet (or file):
    companies   found by NSE symbol, ISIN or company name in the file name, the sheet name or the table itself
    shape       metrics x periods  (rows are metrics, two or more columns are periods: 'Mar 2024', 'FY24', 'Q1FY25')
                                    -> one fact per (company, metric, period, value)
                one row per company (a screener list: one column holds symbols or names)
                                    -> one fact per (company, column, value), dated by the file
                other               -> the whole sheet kept as one node, with its table saved
    kind        a label from a fixed list (financials, segments, operational, shareholding, market share, screener,
                other), chosen by the local model from the headers only, or by keywords without a model
    graph       a 'dataset' document node linked to every company found; the parsed table is saved as parquet
Processed files move to inbox/done/<date>/. A file already read (same bytes) is skipped.
Sharing (The investor 2026-10-17): market-data exports (put in inbox/market/, or a Tijori/Screener file name) go to the API
analyst for expert analysis; anything that looks like a portfolio or carries personal details, and every other file,
stays on this PC (`shareable`).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from pflab.pm.store import next_id

KINDS = ("financials", "segments", "operational", "shareholding", "market share", "screener", "other")
KIND_WORDS = {                                         # most specific first: "revenue mix" is segments, not financials
    "market share": r"market share", "segments": r"segment|revenue mix|division|geograph",
    "shareholding": r"promoter|fii|dii|holding|pledge",
    "operational": r"volume|capacity|utili|stores|subscribers|users|production|units|aum|arpu",
    "screener": r"market cap|p/e|pe ratio|roce|roe",
    "financials": r"revenue|sales|profit|ebitda|eps|balance sheet|cash flow|income"}
MARKET_NAME = re.compile(r"tijori|screener", re.I)
PORTFOLIO_COLS = re.compile(r"\b(qty|quantity|avg\.?\s*(cost|price)|average\s+(cost|price)|invested|buy\s+(price|value)|"
                            r"p\s*&\s*l|pnl|unreali[sz]ed|reali[sz]ed|holding\s+value|current\s+value|my\s+)", re.I)
PERSONAL = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b|[\w.+-]+@[\w-]+\.[\w.]+|(?<!\d)[6-9]\d{9}(?!\d)")
PERIOD = re.compile(r"^(q[1-4]\s*'?\s*(fy)?\s*\d{2,4}|h[12]\s*(fy)?\s*\d{2,4}|fy\s*'?\d{2,4}|"
                    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s'\-]*\d{2,4}|"
                    r"(19|20)\d{2}(-\d{2}(-\d{2})?)?|ttm)$", re.I)
SUFFIX = re.compile(r"\b(limited|ltd\.?|the)\b", re.I)


@dataclass
class Sheet:
    name: str
    frame: pd.DataFrame                    # raw cells, no header
    text: str = ""                         # PDFs and text files
    pages: List[str] = field(default_factory=list)     # a PDF's text page by page


@dataclass
class Read:
    file: str
    sheet: str
    shape: str
    isins: List[str] = field(default_factory=list)
    facts: int = 0
    kind: str = "other"
    pages: int = 0
    chars: int = 0


# ---- reading -------------------------------------------------------------------------------------------------

def sheets(path: Path) -> List[Sheet]:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        book = pd.read_excel(path, sheet_name=None, header=None)
        return [Sheet(str(n), df.dropna(how="all").dropna(axis=1, how="all")) for n, df in book.items()]
    if ext == ".csv":
        return [Sheet(path.stem, pd.read_csv(path, header=None, dtype=str, keep_default_na=False).replace("", None))]
    if ext == ".pdf":
        from pypdf import PdfReader
        pages = [(p.extract_text() or "") for p in PdfReader(str(path)).pages]
        return [Sheet(path.stem, pd.DataFrame(), "\n".join(pages), pages)]
    if ext in (".txt", ".md"):
        return [Sheet(path.stem, pd.DataFrame(), path.read_text(encoding="utf-8", errors="replace"))]
    return []


def header_row(df: pd.DataFrame) -> Optional[int]:
    """The first row with two or more text cells followed by a row with a number (looked for in the first 15)."""
    for i in range(min(15, len(df) - 1)):
        row, nxt = df.iloc[i], df.iloc[i + 1]
        texts = sum(isinstance(v, str) and v.strip() != "" for v in row)
        nums = sum(_num(v) is not None for v in nxt)
        if texts >= 2 and nums >= 1:
            return i
    return None


def _num(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip().replace(",", "").replace("%", "").replace("₹", "")
    if re.fullmatch(r"\(?-?\d+(\.\d+)?\)?", s):
        neg = s.startswith("(") and s.endswith(")")
        return -float(s.strip("()")) if neg else float(s.strip("()"))
    return None


def table(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    h = header_row(df)
    if h is None:
        return None
    cols, seen = [], {}
    for k, v in enumerate(df.iloc[h]):
        name = str(v).strip() if isinstance(v, str) or (v is not None and not pd.isna(v)) else f"col{k}"
        if isinstance(v, (datetime, pd.Timestamp)):
            name = pd.Timestamp(v).strftime("%b %Y")
        seen[name] = seen.get(name, 0) + 1
        cols.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    t = df.iloc[h + 1:].copy()
    t.columns = cols
    return t.dropna(how="all").reset_index(drop=True)


# ---- companies -----------------------------------------------------------------------------------------------

def name_index(con) -> Tuple[Dict[str, str], Dict[str, str], List[Tuple[str, str]]]:
    """symbol -> isin, isin -> isin, and (normalised name, isin) for listed equities."""
    rows = con.execute("SELECT DISTINCT symbol, isin, name FROM instruments WHERE isin LIKE 'INE%'").fetchall()
    sym = {s.upper(): i for s, i, _ in rows if s}
    names = sorted({(SUFFIX.sub("", n).lower().strip(" .,"), i) for _, i, n in rows if n and len(n) > 5},
                   key=lambda x: -len(x[0]))
    return sym, {i: i for _, i, _ in rows}, names


def match_cell(v, sym: Dict[str, str], isins: Dict[str, str], names: List[Tuple[str, str]]) -> Optional[str]:
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip()
    if s.upper() in sym:
        return sym[s.upper()]
    if s.upper() in isins:
        return s.upper()
    low = SUFFIX.sub("", s).lower().strip(" .,")
    for n, i in names:
        if low == n:
            return i
    return None


def find_companies(text: str, sym, isins, names, limit: int = 20) -> List[str]:
    found: List[str] = []
    for m in re.findall(r"\bINE[A-Z0-9]{9}\b", text):
        found.append(m)
    for tok in re.findall(r"\b[A-Z][A-Z0-9&]{2,}\b", text):
        if tok in sym:
            found.append(sym[tok])
    low = " " + re.sub(r"[^a-z0-9 ]", " ", text.lower()) + " "
    for n, i in names:
        if len(n) >= 8 and f" {n} " in low:
            found.append(i)
        if len(set(found)) >= limit:
            break
    return list(dict.fromkeys(found))


# ---- kinds ---------------------------------------------------------------------------------------------------

def kind_by_words(text: str) -> str:
    s = text.lower()
    for k, rx in KIND_WORDS.items():
        if re.search(rx, s):
            return k
    return "other"


def kind_by_model(headers: str, chat=None, model: Optional[str] = None) -> Optional[str]:
    """A bounded choice from KINDS on the headers only (no numbers are written by the model); None on any failure."""
    if not model:
        return None
    try:
        from pflab.llm import client
        from pflab.llm.eval12 import _json
        r = (chat or client.chat)(model, [{"role": "system", "content": "Which kind of financial data sheet is this? "
                                           "Reply in JSON."}, {"role": "user", "content": headers[:1500]}],
                                  fmt={"type": "object", "required": ["kind"], "properties": {"kind": {"enum": list(KINDS)}}},
                                  num_predict=20)
        k = (_json(r.text) or {}).get("kind")
        return k if k in KINDS else None
    except Exception:
        return None


# ---- one file ------------------------------------------------------------------------------------------------

def shareable(path: Path, market: bool, t: Optional[pd.DataFrame], text: str) -> bool:
    """May this sheet go to the API analyst? Only market-data exports (inbox/market/, or a Tijori/Screener file name),
    never one that looks like a portfolio (quantity, average cost, invested, P&L columns) or carries a PAN, e-mail or
    phone number (The investor 2026-10-17: expert analysis on licensed market data goes to the analyst; his own data never).
    A Tijori export goes too unless `tijori_to_analyst = false` in api_budget.toml (The investor 2026-10-23)."""
    if not (market or MARKET_NAME.search(path.name)):
        return False
    if "tijori" in (path.name + " " + text[:200]).lower():
        from pflab.agents import analyst as an
        if not an.config().get("tijori_to_analyst", True):             # his switch (on: The investor 2026-10-23)
            return False
    cols = " ".join(str(c) for c in t.columns) if t is not None else ""
    cells = " ".join(str(v) for v in t.to_numpy().ravel()[:5000]) if t is not None else ""
    return not PORTFOLIO_COLS.search(cols) and not PERSONAL.search(cols + " " + cells + " " + text)


def ingest_file(con, path: Path, out_dir: Path, now: Optional[datetime] = None, model: Optional[str] = None,
                chat=None, market: bool = False) -> List[Read]:
    from pflab.kg import graph as g
    now = now or datetime.now()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    sym, isins, names = name_index(con)
    source = ("Tijori export" if "tijori" in path.name.lower() else "Screener export" if "screener" in path.name.lower()
              else f"file {path.name}")
    reads: List[Read] = []
    for sh in sheets(path):
        if con.execute("SELECT 1 FROM datasets WHERE file_sha=? AND sheet=?", [sha, sh.name]).fetchone():
            continue
        t = table(sh.frame) if len(sh.frame) else None
        head_text = f"{stem_words(path)} {sh.name} " + (" ".join(str(c) for c in t.columns) if t is not None else "") \
            + " " + " ".join(str(v) for v in sh.frame.head(8).to_numpy().ravel() if isinstance(v, str))
        companies = find_companies(head_text + " " + sh.text[:5000], sym, isins, names)
        if not companies:
            companies = company_from_name(con, stem_words(path), names)       # 'muthoot_stand_6575.xlsx': the one company whose name starts so (the held one, if several do)
        shape, facts = "sheet", []
        if t is not None:
            periods = [c for c in t.columns[1:] if PERIOD.match(str(c).strip())]
            key_col = next((c for c in t.columns if sum(match_cell(v, sym, isins, names) is not None
                                                         for v in t[c]) >= max(2, 0.5 * len(t))), None)
            if len(periods) >= 2:
                shape = "metrics x periods"
                owner = companies[0] if len(companies) == 1 else None
                for _, r in t.iterrows():
                    metric = str(r.iloc[0]).strip()
                    if not metric or metric == "nan":
                        continue
                    for p in periods:
                        v = _num(r[p])
                        if v is not None:
                            facts.append((owner, metric, str(p), v))
            elif key_col is not None:
                shape = "one row per company"
                for _, r in t.iterrows():
                    isin = match_cell(r[key_col], sym, isins, names)
                    if not isin:
                        continue
                    companies.append(isin)
                    for c in t.columns:
                        v = _num(r[c]) if c != key_col else None
                        if v is not None:
                            facts.append((isin, str(c), now.strftime("%Y-%m-%d"), v))
                companies = list(dict.fromkeys(companies))
        kind = kind_by_model(head_text, chat, model) or kind_by_words(head_text + " " + sh.text[:2000])
        did = next_id(con, "datasets", "dataset_id")
        tpath = None
        if t is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            tpath = out_dir / f"{sha}_{re.sub(r'[^A-Za-z0-9]+', '_', sh.name)[:40]}.parquet"
            t.astype(str).to_parquet(tpath)
        title = f"{path.name} / {sh.name}: {kind}" + (f" ({len(facts)} figures)" if facts else "")
        doc = g.doc(con, "dataset", f"{sha}|{sh.name}", now, title, source=source,
                    attrs={"kind": kind, "shape": shape, "pages": len(sh.pages), "chars": len(sh.text or ""), "columns": [str(c) for c in t.columns][:60] if t is not None else [],
                           "rows": int(len(t)) if t is not None else 0, "table": str(tpath) if tpath else None,
                           "text": sh.text[:4000] if sh.text else None,
                           "shareable": shareable(path, market, t, sh.text)})
        for i in companies:
            g.edge(con, doc, "about", f"company:{i}", now, "inbox", f"{sha}|{sh.name}", now=now)
        con.execute("INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [did, path.name, sh.name, sha, kind, shape, json.dumps(companies),
                     int(len(t)) if t is not None else 0, int(len(t.columns)) if t is not None else 0,
                     json.dumps([str(c) for c in t.columns][:200]) if t is not None else "[]",
                     str(tpath) if tpath else None, doc, now])
        for isin, metric, period, v in facts:
            con.execute("INSERT INTO dataset_facts VALUES (?,?,?,?,?,?)", [did, isin, metric[:200], period, v, source])
        if sh.pages:                                              # the whole text, page by page: an agent can read any page back (read_file)
            con.execute("DELETE FROM file_pages WHERE file_sha = ?", [sha])
            for n, txt in enumerate(sh.pages, 1):
                if txt.strip():
                    con.execute("INSERT INTO file_pages VALUES (?,?,?,?,?)", [sha, path.name, n, txt, now])
        reads.append(Read(path.name, sh.name, shape, companies, len(facts), kind, len(sh.pages), len(sh.text or "")))
    return reads


def company_from_name(con, stem: str, names) -> List[str]:
    s = re.sub(r"[^a-z0-9 ]", " ", stem.lower()).strip()
    if len(s) < 5:
        return []
    cands = list(dict.fromkeys(i for n, i in names if n.startswith(s)))
    if len(cands) > 1:
        held = {r[0] for r in con.execute("SELECT DISTINCT isin FROM lots WHERE qty > 1e-9").fetchall()}
        cands = [i for i in cands if i in held]
    return cands if len(cands) == 1 else []


def stem_words(path: Path) -> str:
    """The company a file is named after: 'Acme_Energy_stand_58348' -> 'Acme Energy' (a Tijori export's own name; 'stand' and 'cons' are standalone and consolidated, the number its id)."""
    w = re.sub(r"[_\-]+", " ", path.stem)
    w = re.sub(r"\b(stand|standalone|cons|consolidated|report|xlsx|pdf)\b", " ", w, flags=re.I)
    w = re.sub(r"\b\d+\b|\(\d+\)|\s_\d+_", " ", w)
    return " ".join(w.split())


def forget_file(con, sha: str) -> int:
    """Remove what was read from a file (its datasets, figures, pages and graph document) so that it can be read again with better knowledge of the companies."""
    n = 0
    for did, doc in con.execute("SELECT dataset_id, doc_id FROM datasets WHERE file_sha = ?", [sha]).fetchall():
        con.execute("DELETE FROM dataset_facts WHERE dataset_id = ?", [did])
        for t, c in (("kg_edges", "src"), ("kg_docs", "doc_id"), ("kg_nodes", "node_id")):
            try:
                con.execute(f"DELETE FROM {t} WHERE {c} = ?", [doc])
            except Exception:
                pass
        con.execute("DELETE FROM datasets WHERE dataset_id = ?", [did])
        n += 1
    con.execute("DELETE FROM file_pages WHERE file_sha = ?", [sha])
    return n


def reingest_unlinked(con, folders, out_dir: Path, now: Optional[datetime] = None) -> dict:
    """Read the files in `folders` that were never read, or were read when no company could be recognised (no company link: figures with no owner, a report about no one)."""
    now = now or datetime.now()
    done, again, new = [], 0, 0
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            if not f.is_file() or f.suffix.lower() not in (".pdf", ".xlsx", ".xlsm", ".xls", ".csv", ".txt", ".md"):
                continue
            sha = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
            rows = con.execute("SELECT isins_json FROM datasets WHERE file_sha = ?", [sha]).fetchall()
            if rows and not any(r[0] in ("[]", "", None) for r in rows):
                continue
            if rows:
                forget_file(con, sha)
                again += 1
            else:
                new += 1
            try:
                reads = ingest_file(con, f, out_dir, now, None, market=folder.name == "market")
                done.append({"file": f.name, "sheets": len(reads), "figures": sum(r.facts for r in reads), "companies": len({i for r in reads for i in r.isins}),
                             "pages": sum(r.pages for r in reads), "chars": sum(r.chars for r in reads)})
            except Exception as e:                                      # one unreadable file does not stop the others
                done.append({"file": f.name, "error": f"{type(e).__name__}: {str(e)[:120]}"})
    return {"read_again": again, "read_new": new, "files": done}


def run(con, inbox: Path, data_root: Path, model: Optional[str] = None, now: Optional[datetime] = None) -> List[Read]:
    """Every file in the inbox; each moves to inbox/done/<date>/ once read (a failing file stays, with a .error note)."""
    now = now or datetime.now()
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "market").mkdir(exist_ok=True)
    out: List[Read] = []
    files = [(x, False) for x in inbox.iterdir()] + [(x, True) for x in (inbox / "market").iterdir()]
    for p, market in sorted((f for f in files if f[0].is_file() and not f[0].name.endswith(".error.txt")),
                            key=lambda f: f[0].name):
        try:
            out += ingest_file(con, p, data_root / "inbox", now, model, market=market)
            dest = inbox / "done" / now.strftime("%Y-%m-%d")
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest / p.name))
        except Exception as e:
            (p.parent / f"{p.name}.error.txt").write_text(f"{type(e).__name__}: {e}", encoding="utf-8")
    return out


def facts_for(con, isin: str, words: str = "", limit: int = 12) -> Dict[str, object]:
    """Figures from the investor's files for a company, the metrics the question names first (for the agents' facts)."""
    rows = con.execute("""SELECT f.metric, f.period, f.value, d.file FROM dataset_facts f JOIN datasets d USING (dataset_id)
                          WHERE f.isin = ? ORDER BY d.ingested_at DESC""", [isin]).fetchall()
    ws = {w for w in re.findall(r"[a-z]{4,}", words.lower())}
    rows.sort(key=lambda r: -len(ws & set(re.findall(r"[a-z]{4,}", r[0].lower()))))
    return {f"file.{re.sub(r'[^A-Za-z0-9]+', '_', m)[:40]}.{re.sub(r'[^A-Za-z0-9]+', '_', p)}": v
            for m, p, v, _ in rows[:limit]}
