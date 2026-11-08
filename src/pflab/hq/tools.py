"""The brain's tools (S60, PLAN A18): one registry of plain functions, each with a strict JSON schema.

    read     look at the system's facts (all built by code; nothing paid): the portfolio, every stock's drift / odds /
             edge, tax plan, reviewed measures, simulations, forecasts, readings, the graph, notes, memory, its own
             journal and record, ready plans, research flags, price history, quant templates
    journal  the brain's own ledgers, always written: predictions (scored by the keeper), suggestions (the suggestion
             ledger), its working state (memory, superseding the last)
    action   what would change something outside the brain: ask or tell the investor, order research or a calculation, prepare a
             plan, correct a memory row, fetch a cited page. Carried out (The investor 2026-10-25), at most DAILY a day each; the
             rival's (and in shadow mode all) are recorded as decisions only
Inputs are checked here against the schema even though the API's strict mode guarantees them (a test, a replay, a
model without strict mode); results are compact JSON that names its source, redacted (`hq/redact.py`: ids, his name and
address words, PAN, e-mail, phone, UPI, IFSC) and passed through the egress check (the bare word "address" is not read:
public filings name their offices) before they go back to the model; every call is logged in `hq_tool_calls`. Later
turns of a pass send only these checked results, so the API road does not check them a second time.
"""
from __future__ import annotations

import json
from pathlib import Path
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

RESULT_CHARS = 6_000
KINDS = ("read", "journal", "action")


@dataclass
class Ctx:
    rt: Any
    pass_id: Optional[int]
    model: str
    shadow: bool
    syms: Dict[str, str]                         # symbol -> isin the brain may predict and suggest on
    gate: Any
    now: datetime
    client: Any = None
    mode: str = "economy"
    source: str = ""                             # everything the brain has read this pass (for the number check)
    decisions: List[dict] = field(default_factory=list)
    predictions: List[int] = field(default_factory=list)
    suggestions: List[int] = field(default_factory=list)
    results: Dict[str, str] = field(default_factory=dict)
    problems: List[str] = field(default_factory=list)
    state: Optional[str] = None
    case_ids: List[int] = field(default_factory=list)     # S67: the cases this pass works on (opened or handed to it)
    task_id: Optional[int] = None                        # S68: the worker task this pass is carrying out (artifacts are credited to it)
    role: str = ""                                       # S68: coordinator | research | quant | review | assistant
    his_text: str = ""                                   # S69: what he typed in this turn, exactly (approval and acceptance are checked against it, never against tool output)
    wait_for: Optional[str] = None                       # S68: a condition the task now waits on ("sandbox", "task:<id>"); the loop ends and the task parks
    limit_hit: Optional[tuple] = None                    # S68: (tool, cap) when today's cap for a tool refused a worker's call: the task waits for tomorrow, it does not fail
    allowed: Optional[frozenset] = None                  # S68: a worker may call only its role's tools (None: the brain's)
    images: List[dict] = field(default_factory=list)     # S78: pictures a tool made for the model (chart_view); `workers.converse` sends them back inside the tool result
    call_ref: Optional[int] = None                       # S79: the id (hq_tool_calls.call_no) the running tool call will be journaled under; a tool may put it in its result so agent text can cite it
    _book: Any = None

    @property
    def con(self):
        return self.rt.cursor()

    @property
    def asof(self) -> date:
        return self.now.date()

    def book(self):
        if self._book is None:
            from pflab.app import research
            from pflab.hq import stocks
            self._book = stocks.book(self.con, self.asof, research.read_cache(self.rt, "watch"))
        return self._book


def note_artifact(ctx: "Ctx", case_id: Optional[int], kind: str, ref, detail: str = "") -> None:
    """S68: what a worker produced is indexed (kind, reference, the task that made it): a task is DONE when the artifacts it promised exist
    (evidence, calc, scenario, experiment, review, answer), not when the model stops talking."""
    from pflab.pm.store import next_id
    if ctx.shadow:
        return
    ctx.con.execute("INSERT INTO hq_artifacts VALUES (?,?,?,?,?,?,?)",
                    [next_id(ctx.con, "hq_artifacts", "artifact_id"), case_id, ctx.task_id, kind, str(ref), detail[:300], ctx.now])


@dataclass(frozen=True)
class Tool:
    name: str
    kind: str
    about: str
    params: Dict[str, dict]
    required: Tuple[str, ...]
    fn: Callable[[Ctx, dict], dict]

    def schema(self) -> dict:
        return {"type": "object", "additionalProperties": False, "properties": self.params,
                "required": list(self.required)}

    def definition(self, strict: bool = True) -> dict:
        """For the API: bounds the strict grammar may not take are moved into the descriptions (checked here anyway)."""
        props = {}
        for k, v in self.params.items():
            d = {x: y for x, y in v.items() if x not in ("minimum", "maximum", "maxLength", "maxItems")}
            if "minimum" in v:
                d["description"] = f"{v.get('description', '')} (from {v['minimum']:g} to {v['maximum']:g})".strip()
            elif "maxLength" in v:
                d["description"] = f"{v.get('description', '')} (at most {v['maxLength']} characters)".strip()
            props[k] = d
        d = {"name": self.name, "description": f"[{self.kind}] {self.about}",
             "input_schema": {**self.schema(), "properties": props}}
        if self.required and strict:       # the API takes at most 20 strict tools: the first 20 with required inputs
            d["strict"] = True
        return d


def _s(about: str, max_len: int = 600, enum=None) -> dict:
    d = {"type": "string", "description": about}
    if enum:
        d["enum"] = list(enum)
    else:
        d["maxLength"] = max_len
    return d


def _i(about: str, lo: int, hi: int) -> dict:
    return {"type": "integer", "description": about, "minimum": lo, "maximum": hi}


def _n(about: str, lo: float, hi: float) -> dict:
    return {"type": "number", "description": about, "minimum": lo, "maximum": hi}


_PY = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list}


def validate(tool: Tool, args: Any) -> Optional[str]:
    """None when `args` fits the tool's schema; else what is wrong."""
    if not isinstance(args, dict):
        return "the input must be an object"
    extra = set(args) - set(tool.params)
    if extra:
        return f"unknown field(s): {', '.join(sorted(extra))}"
    missing = [k for k in tool.required if k not in args]
    if missing:
        return f"missing field(s): {', '.join(missing)}"
    for k, v in args.items():
        sch = tool.params[k]
        t = sch["type"]
        if not isinstance(v, _PY[t]) or (t in ("integer", "number") and isinstance(v, bool)):
            return f"{k}: must be {t}"
        if "enum" in sch and v not in sch["enum"]:
            return f"{k}: one of {sch['enum']}"
        if t in ("integer", "number") and not sch.get("minimum", -1e18) <= v <= sch.get("maximum", 1e18):
            return f"{k}: between {sch.get('minimum')} and {sch.get('maximum')}"
        if t == "string" and len(v) > sch.get("maxLength", 10_000):
            return f"{k}: at most {sch['maxLength']} characters"
        if t == "array":
            it = sch.get("items", {})
            if len(v) > sch.get("maxItems", 50) or any(not isinstance(x, str) or ("enum" in it and x not in it["enum"])
                                                       for x in v):
                return f"{k}: a list of {it.get('enum') or 'strings'}"
    return None


# --- read tools ------------------------------------------------------------------------------------------------------

def _rs(x) -> str:
    from pflab.hq.brain import _rs as rs
    return rs(float(x))


def _h(text: str, n: int = 10) -> str:
    """A key that is the same after a restart (Python's hash() is not): the same question or message is asked or sent once."""
    import hashlib
    return hashlib.sha1(text.strip().lower().encode("utf-8")).hexdigest()[:n]


def _isin(ctx: Ctx, symbol: str) -> str:
    i = ctx.syms.get((symbol or "").strip().upper())
    if i:
        return i
    r = ctx.con.execute("SELECT isin FROM instruments WHERE upper(symbol)=? LIMIT 1", [(symbol or "").strip().upper()]).fetchone()
    if not r:
        raise LookupError(f"no instrument with the symbol {symbol!r}")
    return r[0]


def portfolio(ctx: Ctx, a: dict) -> dict:
    from pflab.pm import today
    con = ctx.con
    t = today.build(con, ctx.asof)
    pos = t["positions"]
    pos = pos[pos["value"].notna() & (pos["qty"] > 0)]
    total = float(t["investable"]) or 1.0
    eq = {i for (i,) in con.execute("SELECT isin FROM instruments WHERE asset_class='equity'").fetchall()}
    by = pos.groupby(["symbol", "isin", "bucket"], as_index=False)[["value", "cost"]].sum().sort_values("value", ascending=False)
    hold = [{"symbol": r.symbol, "bucket": r.bucket, "weight_pct": round(r.value / total * 100, 2), "value": _rs(r.value),
             "gain_pct": round((r.value / r.cost - 1) * 100, 1) if r.cost else None} for r in by.head(40).itertuples()]
    st = by[by["isin"].isin(eq)]
    sv, sc = float(st["value"].sum()), float(st["cost"].sum())
    priced = by[by["cost"] > 0]
    av, ac = float(priced["value"].sum()), float(priced["cost"].sum())
    targets = {}
    try:
        from pflab.plan import targets as tg
        targets = {b.bucket: b for b in tg.load().buckets.values()}
    except Exception:
        pass
    buckets = []
    for k, v in sorted(t["buckets"].items(), key=lambda kv: -kv[1]):
        if not v:
            continue
        b = targets.get(k)
        buckets.append({"bucket": k, "weight_pct": round(v / total * 100, 1), "value": _rs(v),
                        **({"target_pct": round(b.target * 100, 1), "soft_band_pct": round(b.soft_band * 100, 1),
                            "hard_band_pct": round(b.hard_band * 100, 1)} if b else {})})
    td = t["today"]
    return {"asof": str(ctx.asof), "source": td["source"], "kite_snapshot_at": td.get("snapshot_at"),
            "statements_to": str(td.get("documents_to")), "investable": _rs(total), "net_worth": _rs(t["net_worth"]),
            "buckets": buckets, "holdings": hold,
            "direct_stocks": {"names": int(len(st)), "value": _rs(sv), "cost": _rs(sc), "unrealised_gain": _rs(sv - sc),
                              "gain_pct": round((sv / sc - 1) * 100, 2) if sc else None},
            "all_priced_holdings": {"value": _rs(av), "cost": _rs(ac), "unrealised_gain": _rs(av - ac),
                                    "gain_pct": round((av / ac - 1) * 100, 2) if ac else None},
            "kite_vs_statements": [f"{d['symbol']}: Kite {d['kite']:g}, statements {d['ledger']:g}" for d in td.get("diffs", [])],
            "fall_limit": "the portfolio is checked against a 35% fall (Monte Carlo)",
            "source_note": "pm/today.py: the ledger with the broker account replaced by the newest Kite snapshot; gains "
                           "are unrealised (cost basis of the lots held); realised gains are in tax_plan"}


def stocks_overview(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import stocks
    return stocks.overview(ctx.con, ctx.rt.data_root, ctx.book())


def stock_facts(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import stocks
    return stocks.facts(ctx.con, ctx.rt.data_root, ctx.book(), a["symbol"], tuple(a.get("parts") or ("drift", "odds", "edge", "valuation", "nudges")))


def comovement(ctx: Ctx, a: dict) -> dict:
    from pflab.quant import comove
    return comove.moves_with(a["symbol"], ctx.rt.data_root)


def tax_plan(ctx: Ctx, a: dict) -> dict:
    from pflab.tax import kite_estimate as ke, plan as tp
    out = {"source": "tax/plan.py: the tax engine replays each sale (both regimes), FIFO lots, 112A exemption"}
    try:
        out["lines"] = tp.render(tp.overview(ctx.con, ctx.asof))[:60]
    except Exception as e:                                 # a gap in the rules or the record must not hide the Kite estimate: it is said, not raised
        out["lines"] = []
        out["engine_error"] = f"the tax engine could not run on the record: {type(e).__name__}: {str(e)[:160]}"
    try:                                                   # shares Kite shows and the statements do not yet: a labelled provisional figure, never a lot
        est = ke.estimates(ctx.con, ctx.asof)
    except Exception as e:
        est = []
        out["kite_estimate_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    if est:
        out["kite_estimates"] = est
        out["kite_estimate_lines"] = ke.lines(est)
        out["kite_estimate_note"] = ("ESTIMATE, from Kite: these shares are in Kite but not yet in the statements, so the tax engine cannot work on them. Kite's quantity and "
                                     "average price are used, short-term rate assumed; the engine's own figure replaces this when the statements arrive")
    return out


INDEX_KEYS = {"NIFTY 50": "NIFTY50_PRICE", "NIFTY50": "NIFTY50_PRICE", "NIFTY 500": "NIFTY500_TRI",
              "NIFTY500": "NIFTY500_TRI"}


def _series(ctx: Ctx, name: str):
    import pandas as pd
    key = INDEX_KEYS.get(name.strip().upper())
    if key:
        from pflab.data import indices
        df = indices.load(key, ctx.rt.data_root)
        return df[["date", "close"]], key
    from pflab.hq import stocks
    c = stocks.closes(ctx.con, ctx.rt.data_root, _isin(ctx, name), ctx.asof)
    return pd.DataFrame({"date": c.index, "close": c.values}), name.upper()


def measure(ctx: Ctx, a: dict) -> dict:
    from pflab.calc import measures as ms
    s, label = _series(ctx, a["series"])
    second = None
    if a.get("second"):
        second, l2 = _series(ctx, a["second"])
    vals = {k: a[k] for k in ("start", "end", "fall_pct", "sessions", "level") if k in a}
    out = ms.run(a["measure"], s, vals, second)
    return {"computed": ms.describe(a["measure"], label, vals, a.get("second")), **out,
            "source": "calc/measures.py (reviewed measures)"}


def simulation(ctx: Ctx, a: dict) -> dict:
    from pflab.app import sims
    years = int(a.get("years", 5))
    out = sims.run(ctx.rt, paths=10_000, years=years)
    mixes = {}
    for name, mx in out["mixes"].items():
        y = mx["fan"]["years"].get("1", {})
        worst = sorted([e for e in mx["stress"]["episodes"] if e.get("covered")], key=lambda e: e["worst_fall"])[:3]
        mixes[name] = {"chance_35pct_fall": mx["fall"].get("text"),
                       "one_rupee_after_1y_p5_p50_p95": [round(y[k], 3) for k in ("p5", "p50", "p95")] if y else None,
                       "worst_episodes": [f"{e['name']} {e['worst_fall'] * 100:.0f}%" for e in worst]}
    return {"paths": 10_000, "years": years, "history": out["history"], "mixes": mixes,
            "source": "app/sims.py (block bootstrap, risk/montecarlo.py)"}


def forecasts(ctx: Ctx, a: dict) -> dict:
    from pflab.quant import forecast as fc
    con = ctx.con
    method, label = fc.serving_method(ctx.rt.data_root)
    q = ("SELECT use, subject, as_of, target, q10, q50, q90, model FROM forecasts WHERE as_of = (SELECT max(as_of) "
         "FROM forecasts) AND (model IS NULL OR model IN ('baseline', ?))")
    args: list = [method]
    if a.get("symbol"):
        sym = a["symbol"].strip().upper()
        q += " AND (upper(subject) LIKE ? OR subject = ?)"
        args += [f"%{sym}%", ctx.syms.get(sym, "")]
    rows = con.execute(q + " ORDER BY use, subject LIMIT 30", args).fetchall()
    cover = {f"{m} {h} sessions": c for m in fc.METHODS for h in fc.PRICE_H if (c := fc.coverage(con, m, h))}
    return {"rows": [{"use": u, "subject": s, "as_of": str(a_), "target": str(t), "q10": q1, "q50": q5, "q90": q9,
                      "model": m} for u, s, a_, t, q1, q5, q9, m in rows],
            "price_ranges": f"80% ranges of the price (q10 to q90), method {method}: {label}",
            "rolling_coverage_last_60_scored": {k: f"{v['covered']:.0%} of {v['n']}" for k, v in cover.items()},
            "source": "quant/forecast.py (calibrated statistics: block bootstrap with the CAPM centre; baselines for turnover and results)"}


def readings(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import readers
    isin = _isin(ctx, a["symbol"])
    since = ctx.now - timedelta(days=int(a.get("days", 30)))
    rows = [r for r in readers.recent(ctx.con, since, material_only=False) if isin in r["isins"]][:10]
    from pflab.hq import recency
    return {"readings": recency.stamp([{"kind": r["kind"], "published": str(r["published"])[:10], "material": r.get("material"),
                                        "summary": (r["summary"] or "")[:400], "figures": r["figures"][:4]} for r in rows],
                                      None, ctx.asof),
            "source": "hq/readers.py (Haiku readings; figures kept only when found in the document); stale = older than "
                      "the policy (news 3 days, filings 30, results 100)"}


def graph_timeline(ctx: Ctx, a: dict) -> dict:
    from pflab.kg import graph as g
    isin = _isin(ctx, a["symbol"])
    df = g.timeline(ctx.con, f"company:{isin}", ctx.now - timedelta(days=int(a.get("days", 30))),
                    kinds=("filing", "result", "article", "reading", "analyst_note", "dataset", "deal", "holding"), limit=20)
    from pflab.hq import recency
    items = [{"date": str(r.published_at)[:10], "kind": r.kind, "title": (r.title or "")[:160],
              "url": getattr(r, "url", None), "doc_id": getattr(r, "doc_id", None)} for r in df.itertuples()]
    return {"items": recency.stamp(items, None, ctx.asof, date_key="date"),
            "source": "knowledge graph (kg/graph.py); stale = older than the policy (news 3 days, filings 30, results 100)"}


def notes(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import memory as mem
    rows = mem.recall(ctx.con, subject=a["symbol"].strip().upper(), kinds=["note"], asof=ctx.asof, limit=2)
    return {"notes": [m.line()[:2000] for m in rows] or ["no analyst note on record"],
            "source": "memory (the analyst's newest cited note per company)"}


DOC_PART = 6000


def read_document(ctx: Ctx, a: dict) -> dict:
    """A document in the knowledge graph (a filing, a result, an article) read IN FULL, a part at a time: parts of 6,000 characters (part=N), or the places a word appears (find=word).
    The document comes from graph_timeline (its doc_id) or by company and words of its title."""
    con = ctx.con
    if a.get("doc_id"):
        r = con.execute("SELECT doc_id, kind, title, url, text_path, published_at FROM kg_docs WHERE doc_id = ?", [a["doc_id"].strip()]).fetchone()
    else:
        if not a.get("symbol"):
            return {"note": "give a doc_id (from graph_timeline) or a symbol with words of the title", "documents": []}
        isin = _isin(ctx, a["symbol"])
        words = [w for w in (a.get("title_words") or "").lower().split() if w]
        q = ("SELECT d.doc_id, d.kind, d.title, d.url, d.text_path, d.published_at FROM kg_docs d JOIN kg_edges e ON e.src = d.doc_id AND e.rel = 'about' AND e.dst = ? "
             + "".join(" AND lower(d.title) LIKE ?" for _ in words) + " ORDER BY d.published_at DESC LIMIT 1")
        r = con.execute(q, [f"company:{isin}"] + [f"%{w}%" for w in words]).fetchone()
    if r is None:
        return {"note": "no such document in the knowledge graph", "documents": []}
    doc_id, kind, title, url, tpath, pub = r
    text = None
    if tpath and Path(tpath).exists():
        text = Path(tpath).read_text(encoding="utf-8", errors="replace")
    elif kind in ("filing", "result") and url:
        try:
            from pflab.hq import fetch as _f
            text = _f.local_text(con, url, ctx.rt.data_root / "kg" / "text")
        except Exception:
            text = None
    head = {"doc_id": doc_id, "kind": kind, "title": (title or "")[:200], "published": str(pub)[:10], "url": url}
    if not text:
        return {**head, "note": "no text of this document is kept (a scanned image, or not fetched yet); readings has the reader's summary of it"}
    parts = max(1, -(-len(text) // DOC_PART))
    find = (a.get("find") or "").strip().lower()
    if find:
        low, snips, i = text.lower(), [], 0
        i = low.find(find)
        while i >= 0 and len(snips) < 10:
            snips.append({"part": i // DOC_PART + 1, "text": text[max(0, i - 300): i + 500]})
            i = low.find(find, i + 800)
        return {**head, "parts": parts, "found": snips or [f"'{a['find']}' does not appear in this document"], "source": "the document's own text, kept on this PC"}
    n = min(max(int(a.get("part") or 1), 1), parts)
    return {**head, "parts": parts, "part": n, "text": text[(n - 1) * DOC_PART: n * DOC_PART], "source": "the document's own text, kept on this PC; ask for part=N to continue"}


def _file_rows(con, name: str):
    """The newest received file whose name contains `name`: (file, sha) or None."""
    r = con.execute("SELECT file, file_sha FROM datasets WHERE lower(file) LIKE ? ORDER BY ingested_at DESC, dataset_id DESC LIMIT 1", [f"%{name.strip().lower()}%"]).fetchone()
    return r


def files_tool(ctx: Ctx, a: dict) -> dict:
    """What he has dropped and what was read from each: pages and characters of a PDF, sheets, rows and figures of a spreadsheet, the companies it was linked to."""
    con = ctx.con
    out = []
    q = (a.get("about") or "").strip().lower()
    for f, sha, kinds, n_sheets, rows, at in con.execute(
            "SELECT file, file_sha, string_agg(DISTINCT kind, ', '), count(*), sum(n_rows), max(ingested_at) FROM datasets GROUP BY file, file_sha ORDER BY max(ingested_at) DESC LIMIT 60").fetchall():
        if q and q not in f.lower():
            continue
        pages = con.execute("SELECT count(*), coalesce(sum(length(text)), 0) FROM file_pages WHERE file_sha = ?", [sha]).fetchone()
        figs = con.execute("SELECT count(*) FROM dataset_facts WHERE dataset_id IN (SELECT dataset_id FROM datasets WHERE file_sha = ?)", [sha]).fetchone()[0]
        isins = set()
        for (j,) in con.execute("SELECT isins_json FROM datasets WHERE file_sha = ?", [sha]).fetchall():
            try:
                isins |= set(json.loads(j or "[]"))
            except ValueError:
                pass
        syms = [r[0] or r[1] for r in con.execute("SELECT symbol, name FROM instruments WHERE isin IN (SELECT unnest(?))", [sorted(isins)]).fetchall()] if isins else []
        out.append({"file": f, "kind": kinds, "sheets": int(n_sheets), "table_rows": int(rows or 0), "figures": int(figs), "pdf_pages": int(pages[0]), "pdf_characters": int(pages[1]),
                    "companies": syms[:6], "read_at": str(at)[:16]})
    return {"files": out[:30] or ["no file has been read yet"], "source": "the files he dropped, read on this PC (read_file shows what is in one; file_figures the figures by company)"}


def read_file(ctx: Ctx, a: dict) -> dict:
    """What a dropped file says: a PDF page by page (page=N, or find=word for the places it appears), a spreadsheet's rows (find=a row label)."""
    con = ctx.con
    hit = _file_rows(con, a["name"])
    if hit is None:
        names = [r[0] for r in con.execute("SELECT DISTINCT file FROM datasets ORDER BY 1 LIMIT 30").fetchall()]
        return {"files": names or ["no file has been read yet"], "note": f"no received file has '{a['name']}' in its name; these are the files"}
    f, sha = hit
    pages = con.execute("SELECT page, text FROM file_pages WHERE file_sha = ? ORDER BY page", [sha]).fetchall()
    find = (a.get("find") or "").strip().lower()
    if pages:
        if a.get("page"):
            p = [t for n, t in pages if n == int(a["page"])]
            return {"file": f, "pages_in_file": len(pages), "page": int(a["page"]), "text": (p[0] if p else "no text on that page")[:7000], "source": f"the file {f}, read on this PC"}
        if find:
            snips = []
            for n, t in pages:
                low = t.lower()
                i = low.find(find)
                while i >= 0 and len(snips) < 10:
                    snips.append({"page": n, "text": t[max(0, i - 250): i + 450]})
                    i = low.find(find, i + 700)
            return {"file": f, "pages_in_file": len(pages), "found": snips or [f"'{a['find']}' does not appear in the file's text"], "source": f"the file {f}"}
        return {"file": f, "pages_in_file": len(pages), "outline": [{"page": n, "starts": " ".join(t.split())[:140]} for n, t in pages], "page_1": pages[0][1][:4500],
                "source": f"the file {f}; ask for page=N or find=word for more"}
    out = []
    for sheet, path, ncols, nrows in con.execute("SELECT sheet, table_path, n_cols, n_rows FROM datasets WHERE file_sha = ? ORDER BY dataset_id", [sha]).fetchall():
        if not path:
            out.append({"sheet": sheet, "note": "no table was found in this sheet"})
            continue
        try:
            import pandas as pd
            df = pd.read_parquet(path)
        except Exception as e:
            out.append({"sheet": sheet, "note": f"could not open its table: {type(e).__name__}"})
            continue
        if find:
            df = df[df.iloc[:, 0].astype(str).str.lower().str.contains(find, regex=False)]
        blk = max(int(a.get("page") or 1), 1)
        out.append({"sheet": sheet, "rows": int(nrows), "block": blk, "blocks": max(1, -(-len(df) // 40)), "columns": [str(c) for c in df.columns][:14],
                    "table": df.iloc[(blk - 1) * 40: blk * 40, :14].astype(str).values.tolist()})
    return {"file": f, "sheets": out[:6], "source": f"the file {f}, read on this PC"}


def file_figures(ctx: Ctx, a: dict) -> dict:
    """Figures read from dropped spreadsheets (Tijori and Screener exports) for a company: metric, period, value."""
    con = ctx.con
    sym = a["symbol"].strip().upper()
    r = con.execute("SELECT isin, symbol FROM instruments WHERE upper(symbol) = ? OR upper(name) LIKE ? LIMIT 1", [sym, f"%{sym.lower()}%".upper()]).fetchone()
    if r is None:
        return {"error_note": f"{a['symbol']} is not in the instrument master", "figures": []}
    q, args = "SELECT metric, period, value, source FROM dataset_facts WHERE isin = ?", [r[0]]
    if a.get("metric"):
        q += " AND lower(metric) LIKE ?"
        args.append(f"%{a['metric'].lower()}%")
    if a.get("period"):
        q += " AND lower(period) LIKE ?"
        args.append(f"%{a['period'].lower()}%")
    rows = con.execute(q + " ORDER BY metric, period LIMIT 120", args).fetchall()
    return {"symbol": r[1], "figures": [{"metric": m, "period": p, "value": v} for m, p, v, _ in rows] or ["no figure for this company in the dropped files"],
            "source": "dropped spreadsheets, read on this PC"}


def memory_recall(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import memory as mem
    rows = mem.recall(ctx.con, subject=a.get("subject") or None, kinds=[a["kind"]] if a.get("kind") else None,
                      words=a.get("words", ""), asof=ctx.asof, limit=15)
    return {"rows": [m.line()[:400] for m in rows], "source": "memory (rows in force today; #id to correct one)"}


def journal(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import brain, keeper, suggestions as sg
    mine = [p for p in brain.journal(ctx.con, 30) if p["model"] == ctx.model and p["status"] == "done"][:6]
    return {"passes": [{"id": p["id"], "at": str(p["at"])[:16], "trigger": p["trigger"], "note": (p["note"] or "")[:300],
                        "actions": [f"{d['action']}: {d.get('subject', '')}"[:120] for d in p["decisions"]]} for p in mine],
            "scorecard": keeper.scorecard_text(ctx.con, ctx.model), "suggestions": sg.lessons_text(ctx.con, ctx.model),
            "source": "hq_passes, hq_predictions, hq_suggestions"}


def ready_plans(ctx: Ctx, a: dict) -> dict:
    from pflab.plan import ready
    out = []
    for p in ready.current(ctx.con, 4):
        out.append({k: (v[:800] if isinstance(v, str) else v) for k, v in p.items()
                    if isinstance(v, (str, int, float)) and k not in ("inputs_hash",)})
    return {"plans": out, "source": "plan/ready.py (kept current; tickets are entered by the investor)"}


def research_flags(ctx: Ctx, a: dict) -> dict:
    since = ctx.now - timedelta(days=int(a.get("days", 14)))
    q, args = "SELECT symbol, kind, happened_at, detail FROM research_flags WHERE detected_at >= ?", [since]
    if a.get("symbol"):
        q += " AND isin = ?"
        args.append(_isin(ctx, a["symbol"]))
    else:
        mine = list(ctx.syms.values()) or [""]
        q += f" AND isin IN ({','.join('?' * len(mine))})"
        args += mine
    rows = ctx.con.execute(q + " ORDER BY happened_at DESC LIMIT 20", args).fetchall()
    from pflab.hq import recency
    return {"flags": recency.stamp([{"symbol": s, "kind": "flag:" + k, "at": str(h)[:16], "detail": (d or "")[:300]}
                                    for s, k, h, d in rows], None, ctx.asof, date_key="at"),
            "source": "agents/researcher.py (flags found and measured by code)"}


def price_history(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import stocks
    c = stocks.closes(ctx.con, ctx.rt.data_root, _isin(ctx, a["symbol"]), ctx.asof)
    c = c.iloc[-int(a.get("days", 250)):]
    w = c.resample("W").last().dropna().iloc[-40:]
    return {"trend": stocks.trend(c), "weekly_closes": [[str(d.date()), round(float(v), 2)] for d, v in w.items()],
            "source": "prices (research panel's adjusted closes joined to the store's)"}


def quant(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import quant as qn
    return {"text": qn.run(a["idea"], ctx.rt.data_root)[:3000],
            "source": "agents/quant.py (tested templates; a new claim needs a pre-registered study)"}


def who_is_buying(ctx: Ctx, a: dict) -> dict:
    """S63: insider / SAST disclosures, bulk and block deals, promoters and pledges, institutions by quarter."""
    from pflab.hq import context
    sym = a["symbol"].strip().upper()
    return context.holders(ctx.con, ctx.rt.data_root, _isin(ctx, sym), sym, ctx.asof, int(a.get("days", 180)))


def market_context(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import context
    return context.market(ctx.rt.data_root, ctx.asof)


def growth(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import context
    return context.growth(ctx.con, ctx.asof, int(a.get("months", 12)))


def findings(ctx: Ctx, a: dict) -> dict:
    """S62: what the learner tested. Passed claims with, for a stock signal, where each held and listed name sits today;
    failed ones listed so they are not relied on."""
    import json as _json
    from pflab.learner import templates as tp
    con = ctx.con
    rows = con.execute("SELECT c.claim_id, c.claim, c.template, c.params_json, c.decision, c.why, s.title FROM learn_claims c "
                       "JOIN learn_sources s USING (src_id) WHERE c.status IN ('passed','failed') ORDER BY c.decided_at DESC "
                       "LIMIT 30").fetchall()
    passed, failed = [], []
    for cid, claim, t, prm, d, why, title in rows:
        item = {"claim": claim[:300], "test": f"{t} {prm}", "result": (why or "")[:300], "source": (title or "")[:120],
                "claim_id": cid}
        if d == "pass" and t == "cross_section":
            p = _json.loads(prm)
            q = tp.today_quintiles(con, ctx.rt.data_root, p["signal"], list(ctx.syms.values()), ctx.asof)
            names = {v: k for k, v in ctx.syms.items()}
            item["today"] = {names.get(i, i): f"quintile {v['quintile']} of 5 ({p['signal']} {v['value']:.3g}, "
                                              f"breakpoints {v['breakpoints_at']})" for i, v in q.items()}
            item["claimed_quintile"] = 5 if p["direction"] == "high" else 1
        elif d == "pass" and t == "rule_filter":
            from pflab.learner import rules
            p = _json.loads(prm)
            try:
                item["today"] = rules.today(ctx.con, ctx.rt.data_root, p["rule"], ctx.asof) or "none of his names meets it today"
            except Exception as e:
                item["today"] = f"not read ({type(e).__name__})"
            item["claimed"] = ("the names that meet it earn MORE than the rest" if p["direction"] == "out"
                               else "the names that meet it earn LESS than the rest")
        (passed if d == "pass" else failed).append(item)
    from pflab.learner import counter
    return {"passed": passed, "failed": [{k: f[k] for k in ("claim", "result", "claim_id")} for f in failed[:15]],
            "tests_run": counter.n_tests(con), "bar_for_next_test": counter.line(con),
            "source": "learner (claims from reading, each registered before its test; learner/templates.py decides)"}


# --- journal tools ---------------------------------------------------------------------------------------------------

def record_prediction(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import brain, keeper
    pr, problem = brain.check_prediction(a, ctx.syms, ctx.now)
    if problem:
        raise ValueError(problem)
    pid = keeper.add_prediction(ctx.con, ctx.pass_id, ctx.model, pr, ctx.now)
    if pid is None:
        raise ValueError(f"no close on record for {pr['symbol']}: not kept")
    ctx.predictions.append(pid)
    return {"kept": pid, "scored": "on the close at its due date, against the stock's own base rate"}


def record_suggestion(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import analyst as an
    from pflab.hq import keeper, stocks, suggestions as sg
    sym = (a.get("symbol") or "").strip().upper()
    isin = facts = ref = qty = None
    if sym:
        if sym not in ctx.syms:
            raise ValueError(f"{sym} is neither held nor on the stock list")
        isin = ctx.syms[sym]
        bk = ctx.book()
        facts = stocks.facts(ctx.con, ctx.rt.data_root, bk, sym, ("drift", "valuation"))
        s = keeper.closes(ctx.con, isin, ctx.asof, days=15)
        ref = (s.index[-1].date(), float(s.iloc[-1])) if len(s) else None
        qty = float(bk.qtys.get(isin, 0.0))
    text, d1 = an.only_sourced_numbers(a["text"], an.Request(ctx.source, "brain"))
    why, d2 = an.only_sourced_numbers(a["reasoning"], an.Request(ctx.source, "brain"))
    if d1 or d2:
        ctx.problems.append(f"suggestion on {sym or 'the portfolio'}: {d1 + d2} sentence(s) dropped (numbers not read)")
    data = {"rested_on": {n: ctx.results.get(n, "(not called this pass)")[:1500] for n in a.get("rested_on", [])},
            "facts_at_the_time": facts}
    sid = sg.record(ctx.con, pass_id=ctx.pass_id, model=ctx.model, kind=a["kind"], isin=isin, symbol=sym or None,
                    text=text.split("\n\n(")[0], reasoning=why.split("\n\n(")[0], data=data,
                    horizon_days=int(a["horizon_days"]), now=ctx.now, shadow=ctx.shadow, ref=ref, ref_qty=qty, facts=facts,
                    root=ctx.rt.data_root, amount=stocks.order_size(bk, isin) if isin and a["kind"] == "add" else None)
    ctx.suggestions.append(sid)
    q = ctx.con.execute("SELECT quality, quality_why, price_low, price_high, max_buy, amount, wrong_if, watch_id "
                        "FROM hq_suggestions WHERE sug_id=?", [sid]).fetchone()
    st = ctx.con.execute("SELECT stats_json FROM hq_suggestions WHERE sug_id=?", [sid]).fetchone()[0]
    nudges_ = (json.loads(st).get("nudges") if st else None) or []
    return {"kept": sid, "quality_at_the_time": q[0], "why": q[1],
            "nudges": [n["text"] for n in nudges_] or "none apply (tips from unregistered sources cannot be checked)",
            "numbers_by_code": {"price_low": q[2], "price_high": q[3], "highest_buy": q[4], "amount_rs": q[5],
                                "wrong_if": q[6], "price_watch": q[7]},
            "scored": f"in {a['horizon_days']} days against the Nifty 500, taken or not"}


def save_state(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import memory as mem
    from pflab.hq import brain
    subject = f"brain:{ctx.model}"
    prev = ctx.con.execute("SELECT max(mem_id) FROM memory WHERE kind='state' AND subject=? AND valid_to IS NULL",
                           [subject]).fetchone()[0]
    state = brain.unnamed(a["state"], ctx.gate.names)
    mid = mem.remember(ctx.con, "state", state, subject=subject, source=f"brain pass #{ctx.pass_id}", now=ctx.now,
                       supersedes=prev)
    ctx.state = state
    return {"saved": mid, "supersedes": prev}


# --- action tools ----------------------------------------------------------------------------------------------------

def _checked(ctx: Ctx, text: str) -> str:
    from pflab.agents import analyst as an
    out, n = an.only_sourced_numbers(text, an.Request(ctx.source, "brain"))
    if n:
        ctx.problems.append(f"{n} sentence(s) dropped from an action (numbers not read)")
    return out.split("\n\n(")[0] if n else out


# Actions carried out a day at most (The investor 2026-10-25: minimum of him; a noisy day never floods him or the cap).
# Beyond it the decision is kept in the journal ("held") and the brain is told. S62: the learner may propose a change,
# applied only with the investor's yes (`learned` daily_cap); web_search is paid, so few.
DAILY = {"tell_investor": 3, "ask_investor": 2, "change_preference": 3, "order_research": 3, "order_calculation": 3, "fetch_cited": 5, "web_search": 3, "request_report": 5, "case_calculate": 3, "resolve_task": 5, "register_experiment": 2}


# S68: in the bounded acceptance window the tools that DO work (search, calculate, investigate) get this many times their daily cap; the tools that
# take his attention (tell, ask, change a preference) never do.
WORK_TOOLS = ("order_research", "order_calculation", "fetch_cited", "web_search", "request_report", "case_calculate", "resolve_task", "register_experiment")
WINDOW_FACTOR = 6


def daily_cap(con, tool: str, now: Optional[datetime] = None) -> Optional[int]:
    from pflab.agents import analyst as an
    from pflab.learner import live
    cfg = an.config()
    own = ((cfg.get("policy") or {}).get("tool_caps") or {}).get(tool)         # api_budget.toml [policy.tool_caps]
    v = live.values(con, "daily_cap").get(tool)
    n = int(own) if own is not None else int(v) if v is not None else DAILY.get(tool)
    if n is not None and tool in WORK_TOOLS and an.acceptance(cfg, now or datetime.now()):
        n *= WINDOW_FACTOR
    return n


def acted_today(ctx: Ctx, tool: str) -> int:
    day0 = datetime(ctx.now.year, ctx.now.month, ctx.now.day)
    return int(ctx.con.execute("SELECT count(*) FROM hq_tool_calls WHERE tool=? AND status='ran' AND called_at >= ?",
                               [tool, day0]).fetchone()[0])


def _act(ctx: Ctx, decision: dict, do: Callable[[], Any], tool: str = "") -> dict:
    decision = {**decision, "shadow": ctx.shadow}
    ctx.decisions.append(decision)
    if ctx.shadow:
        return {"recorded": True, "carried_out": False,
                "why": "journal only (shadow mode, or the cheaper rival): not carried out"}
    n = daily_cap(ctx.con, tool, ctx.now) if tool else None
    if n is not None and acted_today(ctx, tool) >= n:
        decision["held"] = f"today's limit of {n} reached"
        if ctx.task_id:
            ctx.limit_hit = (tool, n)
        return {"recorded": True, "carried_out": False, "why": f"today's limit of {n} for {tool} is reached: kept in "
                                                               "the journal; say it in the note if it matters"}
    decision["done"] = str(do())[:300]
    return {"recorded": True, "carried_out": True, "result": decision["done"]}


def _decision(action: str, agent: str, subject: str, question: str, reason: str, priority: str = "medium") -> dict:
    return {"action": action, "agent": agent, "subject": subject, "question": question, "reason": reason,
            "priority": priority}


def ask_investor(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import questions as qs
    q, why = _checked(ctx, a["question"]), _checked(ctx, a["why"])
    return _act(ctx, _decision("ask", "", "", q, why),
                lambda: qs.ask(ctx.con, "brain", f"brain:{_h(q)}", q, ctx.now), "ask_investor")


def tell_investor(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import messenger
    m = _checked(ctx, a["message"])
    return _act(ctx, _decision("tell", "", "", m, "", a["priority"]),
                lambda: messenger.send_now(ctx.rt, f"Brain: {m}", "brain", dedup_key=f"brain:{_h(m)}:{ctx.now:%Y%m%d}"), "tell_investor")


def order_research(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import board
    q = a["question"]                          # a request to an agent: its numbers are parameters, not claims
    return _act(ctx, _decision("investigate", "research", a["symbol"].upper(), q, _checked(ctx, a.get("why", ""))),
                lambda: board.post(ctx.con, "research", f"{a['symbol'].upper()}: {q}", ctx.now, frm="brain"), "order_research")


def order_calculation(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import board
    q = a["question"]
    return _act(ctx, _decision("investigate", "calc", "", q, _checked(ctx, a.get("why", ""))),
                lambda: board.post(ctx.con, "calc", q, ctx.now, frm="brain"), "order_calculation")


def change_preference(ctx: Ctx, a: dict) -> dict:
    """S65: a change HE asked for, put to him as one exact edit (plan/prefs.py); his yes applies it."""
    from pflab.plan import prefs
    try:
        words = prefs.check(a["kind"], a["key"], a["value"])
    except (prefs.PrefError, ValueError) as e:
        return {"recorded": False, "carried_out": False, "why": f"not a change I can put to him: {e}"}
    return _act(ctx, _decision("ask", "", a["kind"], f"change: {words}", _checked(ctx, a["why"])),
                lambda: f"proposal #{prefs.propose(ctx.con, a['kind'], a['key'], a['value'], a['why'], ctx.now)}: waiting for his yes",
                "change_preference")


def prepare_plan(ctx: Ctx, a: dict) -> dict:
    from pflab.app import research
    amt = a.get("amount")
    def do() -> str:
        res = research.compute_plan(ctx.rt, amt)            # S65: it reports a count, or the error it kept; never "0 plans" for a failure
        if res.get("error"):
            ctx.problems.append(f"prepare_plan failed: {res['error'][:160]}")
            return f"plan refresh FAILED: {res['error'][:200]}"
        return f"{res.get('plans', 0)} plan(s) refreshed" + (f", one for Rs {amt:,.0f}" if amt else "")
    return _act(ctx, _decision("prepare_plan", "", f"Rs {amt:,.0f}" if amt else "the ready plans", "", _checked(ctx, a["why"])), do)


def correct_memory(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import memory as mem
    if not ctx.con.execute("SELECT 1 FROM memory WHERE mem_id=? AND valid_to IS NULL", [a["mem_id"]]).fetchone():
        raise ValueError(f"no memory #{a['mem_id']} in force")
    text, why = _checked(ctx, a["text"]), _checked(ctx, a["reason"])
    return _act(ctx, _decision("correct_memory", "memory", f"#{a['mem_id']}", text, why),
                lambda: mem.correct(ctx.con, int(a["mem_id"]), text, why, by=f"brain pass #{ctx.pass_id} ({ctx.model})",
                                    now=ctx.now))


def fetch_cited(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import fetch
    if a["url"].strip() not in fetch.cited_urls(ctx.con, ctx.now):
        raise ValueError("only a page the system already cites can be fetched")
    q = a["question"]
    return _act(ctx, _decision("investigate", "fetch", a["url"].strip()[:200], q, ""),
                lambda: fetch.run(ctx.con, a["url"], q, ctx.client, ctx.gate, ctx.now, ctx.mode,
                                  text_dir=ctx.rt.data_root / "kg" / "text")["text"], "fetch_cited")


WEB = {"max_uses": 2, "max_tokens": 6000, "effort": "medium"}      # the brain's searches: lighter than the AI centre's


def web_search(ctx: Ctx, a: dict) -> dict:
    """S62 (PLAN A21): a public question searched on the web by the slider's `brain_web` model (Sonnet: the first real
    lookup on Opus cost Rs 23.65, the results being input); priced first against the cap,
    at most DAILY a day; only cited figures kept; the analyst's gate refuses anything of the investor's."""
    from pflab.agents import analyst as an
    q, got = a["question"], {}

    def do():
        from pflab.hq import models
        cfg = {**an.config(), "model": models.model_id("brain_web", ctx.rt.settings)}
        o = an.web_search(ctx.con, q, ctx.client, now=ctx.now, cfg=cfg, topic="brain web", **WEB)
        if o.status != "done":
            raise ValueError(f"web search {o.status}: {o.text[:200]}")
        got["text"] = o.text
        return f"answered with cited pages (Rs {o.cost_inr:.2f})"
    out = _act(ctx, _decision("investigate", "web", "", q, _checked(ctx, a.get("why", ""))), do, "web_search")
    if got:
        out["result"] = got["text"][:4500]                      # the cited answer itself, for the brain to read
        out["recency"] = "web results older than 7 days, or with no date shown, are not a cause of today"
    return out


def themes_tool(ctx: Ctx, a: dict) -> dict:
    """Theme exposure with the applied limits, the dip reserve and the opportunity pot (all by code)."""
    from pflab.plan import pot
    from pflab.risk import themes
    ex = themes.exposure_of(ctx.con, ctx.rt.data_root, ctx.asof)
    lims = {t: themes.applied(ctx.con, "theme_limit", t) for t in ex}
    pend = ctx.con.execute("SELECT kind, key, value, status FROM limit_proposals WHERE status IN ('pending','applied') "
                           "ORDER BY prop_id DESC LIMIT 20").fetchall()
    ideas = ctx.con.execute("SELECT idea_id, symbol, reason, buy_below, exit_above, stop_below, amount, status FROM pot_ideas "
                            "ORDER BY idea_id DESC LIMIT 10").fetchall()
    return {"themes": {t: {"label": e["label"], "share_of_portfolio": round(e["weight"], 4), "limit": lims[t],
                           "holdings": e["holdings"][:8]} for t, e in ex.items()},
            "proposals": [{"kind": k, "key": key, "value": v, "status": s} for k, key, v, s in pend],
            "pot": {"limit_rs": pot.limit(ctx.con), "used_rs": pot.used(ctx.con), "room_rs": pot.room(ctx.con),
                    "ideas": [{"id": i, "symbol": sy, "reason": r, "buy_below": b, "exit_above": x, "stop_below": st,
                               "amount": am, "status": sts} for i, sy, r, b, x, st, am, sts in ideas]},
            "source": "risk/themes.py, plan/pot.py (limits apply only after the investor's yes; history is not a forecast)"}


def propose_pot_idea(ctx: Ctx, a: dict) -> dict:
    """A missed winner or an IPO for the opportunity pot: the reason in words, every price and the amount by code."""
    from pflab.agents import analyst as an
    from pflab.plan import pot
    sym = a["symbol"].strip().upper()
    isin = _isin(ctx, sym)
    reason, dropped = an.only_sourced_numbers(a["reason"], an.Request(ctx.source, "brain"))
    if dropped:
        ctx.problems.append(f"pot idea on {sym}: {dropped} sentence(s) dropped (numbers not read)")
    if ctx.shadow:
        return {"shadow": True, "note": "shadow pass: the idea is not kept"}
    iid = pot.add_idea(ctx.con, ctx.rt.data_root, isin, sym, reason.split("\n\n(")[0], ctx.asof, ctx.now)
    r = ctx.con.execute("SELECT buy_below, exit_above, stop_below, amount, horizon_days FROM pot_ideas WHERE idea_id=?", [iid]).fetchone()
    return {"kept": iid, "buy_below": r[0], "exit_above": r[1], "stop_below": r[2], "amount_rs": r[3], "scored_after_days": r[4],
            "note": "prices and amount by code; an idea for the investor, never an order"}


def record_hypothesis(ctx: Ctx, a: dict) -> dict:
    """The brain's "this seems the cause": kept with its evidence and a date to check by; the keeper tests it later."""
    from pflab.agents import analyst as an
    from pflab.kg import hypotheses as hy
    cause, d1 = an.only_sourced_numbers(a["cause"], an.Request(ctx.source, "brain"))
    effect, d2 = an.only_sourced_numbers(a["effect"], an.Request(ctx.source, "brain"))
    if d1 or d2:
        ctx.problems.append(f"hypothesis on {a['subject']}: {d1 + d2} sentence(s) dropped (numbers not read)")
    if ctx.shadow:
        return {"shadow": True, "note": "shadow pass: the hypothesis is not kept"}
    check_by = date.fromisoformat(a["check_by"])
    series = a.get("series")
    sep = "\n\n("
    hid = hy.record(ctx.con, ctx.pass_id, a["subject"], cause.split(sep)[0], effect.split(sep)[0],
                    list(a.get("evidence", [])), check_by, None if series in (None, "none") else series, ctx.now)
    return {"kept": hid, "checked": ("by code on " if series not in (None, "none") else "by you in a later pass on ") + str(check_by),
            "note": "confirmed or refuted later; a refuted one leaves the graph"}


def ipo_plan(ctx: Ctx, a: dict) -> dict:
    """An IPO allotment and the money around it: the facts and the choices with their numbers (plan/ipo.py)."""
    from pflab.plan import ipo
    r = ipo.strategy(ctx.con, ctx.rt.data_root, ctx.asof, a["name"], int(a["shares"]), float(a["issue_price"]), float(a["budget"]),
                     a.get("group"), ctx.rt.pm_dir)
    r["how_to_use"] = ("Then web_search the public facts listed in to_look_up_with_web_search (never put his shares, amounts or "
                       "holdings in the question; GMP is sentiment, name its date), connect them to the picture, and set out the "
                       "choices with numbers. Do not call it up or down: say what is known and what is not.")
    return r


def picture_tool(ctx: Ctx, a: dict) -> dict:
    """Everything side by side, built by code: the first call of every pass."""
    from pflab.hq import picture
    p = picture.cached(ctx.con, ctx.rt.data_root, ctx.asof, ctx.book(), ctx.rt.pm_dir)
    return {**p, "source": "hq/picture.py: stored and computed facts with their dates, side by side; nothing in it is a forecast"}


def system_status(ctx: Ctx, a: dict) -> dict:
    """The system's own state, built by code (app/system.py): the same picture the Command centre shows, whether this runs in the
    dashboard or in the background tick."""
    from pflab.app import system
    p = system.picture(ctx.rt, ctx.now)
    w = p["work"]
    return {"verdict": p["verdict"], "catching_up": p["catching_up"],
            "connectors": [{k: c[k] for k in ("name", "state", "line")} for c in p["connectors"]],
            "data_freshness": [{k: f[k] for k in ("name", "latest", "state", "line", "retained")} for f in p["freshness"]],
            "running_now": w["running"], "recently_done": [x["says"] + " (" + x["at"] + ")" for x in w["recent"][:6]],
            "failed_last_day": w["failed_24h"], "needs_from_him": [n["title"] for n in p["needs"]["items"]],
            "tasks": w["tasks"], "held_tasks": w["held"], "being_researched": [{k: c[k] for k in ("id", "question", "status", "waiting_for")} for c in w["investigating"]],
            "decided_lately": w["decided"], "recommendations": {k: p["recommendations"][k] for k in ("current", "why", "say")},
            "changed_since_his_last_visit": p["changed"], "tools": p["tools"],
            "source": "app/system.py: read from the store, the data folder and this machine; states: ok, warn (late or waiting on him), down, off; "
            "a recommendation prepared earlier is not current while `recommendations.current` is false"}


def scans_tool(ctx: Ctx, a: dict) -> dict:
    """The saved scans with their tested label and the hits of their last run."""
    from pflab.quant import scan
    p = ctx.rt.pm_dir / "app" / "cache" / "scans.json"
    try:
        res = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        res = {}
    out = []
    for s in scan.listing(ctx.con):
        r = (res.get("scans") or {}).get(str(s["scan_id"]))
        out.append({**s, "last_run": r["at"] if r else None,
                    "hits": [f"{h['symbol']}: {'; '.join(h['why'])}"[:200] for h in (r["hits"][:8] if r else [])]})
    return {"scans": out, "conditions": scan.__doc__.split("Conditions (name:value):")[1].strip(),
            "source": "quant/scan.py: conditions from a closed set, evaluated by code; information until the learner has tested one"}


def make_scan(ctx: Ctx, a: dict) -> dict:
    """The brain makes a scan: information only, labelled not tested; it can never turn one into a rule."""
    from pflab.quant import scan
    if ctx.shadow:
        return {"shadow": True, "note": "shadow pass: the scan is not kept"}
    sid = scan.make_scan(ctx.con, a["name"], a["conditions"], a.get("universe", "list"), f"brain:{ctx.model}", ctx.now)
    return {"kept": sid, "label": scan.LABEL_UNTESTED, "note": "runs each evening; hits on his names reach the evening summary"}


def scenario(ctx: Ctx, a: dict) -> dict:
    from pflab.risk import scenarios as sn
    name = a["name"]
    r = sn.run(ctx.con, ctx.rt.data_root, ctx.asof, name)
    for row in r.get("rows", []):
        row["beta"] = round(row["beta"], 2)
        row["impact"], row["plus_minus"], row["value"] = round(row["impact"]), round(row["plus_minus"]), round(row["value"])
        row.pop("beta_se", None)
    if "total" in r:
        r["total"], r["total_range"] = round(r["total"]), [round(x) for x in r["total_range"]]
        r["modelled_value"] = round(r["modelled_value"])
    r["source"] = "risk/scenarios.py (historical betas with standard errors; a description, not a forecast)"
    return r


def hypotheses(ctx: Ctx, a: dict) -> dict:
    from pflab.kg import hypotheses as hy
    return {"to_decide_now": hy.due_for_the_brain(ctx.con), "recent": hy.listing(ctx.con, a.get("status"), 15),
            "source": "kg_hypotheses (the keeper tests macro causes by code; others wait for a decision in a pass)"}


def decide_hypothesis(ctx: Ctx, a: dict) -> dict:
    """Decide a hypothesis the keeper handed over (its cause is not a macro series): confirmed or refuted, with the reason."""
    from pflab.kg import hypotheses as hy
    if ctx.shadow:
        return {"shadow": True}
    hy.decide(ctx.con, int(a["hyp_id"]), a["verdict"], a["why"], ctx.now)
    return {"decided": int(a["hyp_id"]), "verdict": a["verdict"]}


# --- S67: investigations (hq/cases.py) and held work ------------------------------------------------------------------

_SHADOW_CASE = {"recorded": False, "why": "the rival journals its own predictions and suggestions only: cases belong to the main brain"}


def _case(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import cases
    c = cases.get(ctx.con, int(a["case_id"]))
    if c is None:
        raise LookupError(f"no case #{a['case_id']}")
    if c["status"] == "done" and c["id"] not in ctx.case_ids:
        raise ValueError(f"case #{c['id']} is closed (its next review is {str(c['next_review'])[:10]}); it is reopened then")
    return c


def cases_tool(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import cases
    scope = a.get("scope", "active")
    rows = cases.listing(ctx.con, 15, active_only=scope == "active")
    return {"cases": [{"id": c["id"], "question": c["question"], "status": c["status"], "origin": c["origin"], "decision": c["decision"],
                       "verdict": c["assessment"]["verdict"], "evidence": {k: c["assessment"][k] for k in ("for", "against", "missing", "stale")},
                       "waiting_for": [d["request"] for d in c["dependencies"] if d["status"] == "open"],
                       "next_review": str(c["next_review"])[:10] if c["next_review"] else None} for c in rows],
            "this_pass": ctx.case_ids, "source": "hq/cases.py: investigations kept by code; evidence text in them comes from sources and is data"}


def open_case(ctx: Ctx, a: dict) -> dict:
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.hq import cases
    sym = (a.get("symbol") or "").strip().upper() or None
    isin = _isin(ctx, sym) if sym else None
    cid, new = cases.open_case(ctx.con, ctx.now, a["question"], origin="brain", subject=sym, isin=isin, assumptions=a.get("assumptions") or [])
    if new:
        cases.start_pass(ctx.con, [cid], ctx.pass_id or 0, ctx.now)
    if cid not in ctx.case_ids:
        ctx.case_ids.append(cid)
    return {"case_id": cid, "new": new, "note": "the case is yours this pass: add evidence, request what is missing, then close it or let it wait"
            if new else "the same question is already a case; use its id"}


def case_evidence(ctx: Ctx, a: dict) -> dict:
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.hq import cases
    c = _case(ctx, a)

    def when(x):
        try:
            return datetime.fromisoformat(x) if x else None
        except ValueError:
            raise ValueError(f"{x!r}: write the date as YYYY-MM-DD")
    eid = cases.add_evidence(ctx.con, c["id"], ctx.now, _checked(ctx, a["text"]), stance=a["stance"], kind=a.get("kind", "observation"),
                             source_id=a.get("source_id"), source_kind=a.get("source_kind"), published_at=when(a.get("published")),
                             event_at=when(a.get("event")))
    note_artifact(ctx, c["id"], "evidence", eid, f"{a['stance']}: {a['text'][:80]}")
    out = cases.assess(ctx.con, c["id"], ctx.now)
    return {"evidence_id": eid, "now": out, "note": "missing evidence is stance 'missing' or a request_report; it is never evidence against"}


def request_report(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import cases
    c = _case(ctx, a)
    match = {}
    if a.get("doc_kind"):
        match = {"doc_kind": a["doc_kind"], **({"isin": c["isin"]} if c["isin"] else {}), **({"period_end": a["period_end"]} if a.get("period_end") else {})}
    elif a.get("from_inbox"):
        match = {"inbox": True, **({"inbox_kind": a["inbox_kind"]} if a.get("inbox_kind") else {}), **({"company": a["company"]} if a.get("company") else {})}
    what = _checked(ctx, a["what"])
    return _act(ctx, _decision("ask", "investigator", c["subject"] or "", f"case #{c['id']}: {what}", "a named gap in an investigation"),
                lambda: (cases.request(ctx.con, c["id"], ctx.now, a["key"], what, match=match, kind="report" if match else "answer")[1]
                         and f"case #{c['id']} waits for: {what[:120]}") or f"case #{c['id']} already waits for {a['key']}", "request_report")


def case_calculate(ctx: Ctx, a: dict) -> dict:
    """A calculation for a case: reviewed measures first, else code written, run in the sandbox, written a second time and compared
    (agents/workshop.py). The script, datasets, parameters and result are kept (`hq_calcs`). With no sandbox the case waits for it."""
    from pflab.agents import sandbox as sb
    from pflab.agents import workshop as wk
    from pflab.hq import cases
    c = _case(ctx, a)
    got: dict = {}

    def do():
        try:
            out = wk.ask(ctx.con, a["question"], ctx.rt.pm_dir, ctx.rt.data_root, ctx.asof, secrets=ctx.rt.secrets, now=ctx.now)
        except sb.SandboxUnavailable as e:
            cases.request(ctx.con, c["id"], ctx.now, "sandbox", f"the sandbox (Docker) must run: {e}", match={"sandbox": True}, ask_investor=False)
            got["wait"] = str(e)
            ctx.wait_for = "sandbox"                    # a worker task parks on it (missing Docker is a wait, never a failure or a host run)
            return "waiting for the sandbox"
        kid = cases.record_calc(ctx.con, c["id"], ctx.now, a["question"], out)
        got["calc_id"], got["status"] = kid, out.status
        note_artifact(ctx, c["id"], "calc", kid, out.status)
        got["result"] = dict(list((out.run.result if out.run else {}).items())[:12])
        return f"calculation #{kid}: {out.status}"
    res = _act(ctx, _decision("investigate", "calc", c["subject"] or "", a["question"], f"case #{c['id']}"), do, "case_calculate")
    return {**res, **got}


def case_close(ctx: Ctx, a: dict) -> dict:
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.hq import cases
    c = _case(ctx, a)
    days = int(a.get("review_days", cases.REVIEW_DAYS))
    out = cases.conclude(ctx.con, c["id"], ctx.now, a["decision"], _checked(ctx, a["reason"]), uncertainty=_checked(ctx, a.get("uncertainty", "")),
                         next_review_at=ctx.now + timedelta(days=days))
    return {**out, "note": "kept with its evidence; it reopens by itself on the review day"}


# --- S67 local: the shared research workspace (chat and background use these same tools and tables) ----------------------------------

def frame_objective(ctx: Ctx, a: dict) -> dict:
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.hq import objectives
    try:
        frame = json.loads(a["frame_json"])
        if not isinstance(frame, dict):
            raise ValueError("not an object")
    except ValueError as e:
        return {"stored": False, "problem": f"frame_json is not a JSON object ({e})"}
    out = objectives.store(ctx.con, ctx.now, a["wish"].strip(), frame, int(a["case_id"]) if a.get("case_id") else None)
    return {**out, "note": "a draft is not tested or recommended against until the numbers are his; the protective limits are never changed here"}


def experiments_tool(ctx: Ctx, a: dict) -> dict:
    from pflab.learner import experiments as ex
    if a.get("experiment_id"):
        eid = int(a["experiment_id"])
        return {"experiment": next((e for e in ex.report(ctx.con) if e["id"] == eid), None),
                "attempts": [{k: v for k, v in x.items() if k != "code"} for x in ex.attempts(ctx.con, eid)]}
    return {"experiments": ex.report(ctx.con)[-12:], "tests_counted": __import__("pflab.learner.counter", fromlist=["x"]).n_tests(ctx.con),
            "note": "a rejection is a result; a kept candidate is shadow research only, never a rule"}


def register_experiment(ctx: Ctx, a: dict) -> dict:
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.learner import experiments as ex
    from pflab.learner.run import folders

    def do():
        eid = ex.register(ctx.con, folders(ctx.rt)[1], ctx.now, hypothesis=a["hypothesis"].strip(), why_it_matters=a["why_it_matters"].strip(),
                          disproof=a["disproof"].strip(), source_kind=a["source"], source_ref=str(a.get("case_id") or ""), contract=a.get("contract") or None)
        st, why = ctx.con.execute("SELECT status, coalesce(decision_why, '') FROM learn_experiments WHERE exp_id=?", [eid]).fetchone()
        if st == "unsupported":                         # recorded, never run through another contract's template
            ctx.problems.append(f"experiment #{eid} is unsupported")
            note_artifact(ctx, a.get("case_id"), "experiment_unsupported", eid, why[:200])
            return f"experiment #{eid} NOT registered for running: unsupported. {why}"
        note_artifact(ctx, a.get("case_id"), "experiment", eid, "registered")
        return f"experiment #{eid} registered (the learner's next cycle runs it in the sandbox; the result is kept either way)"
    return _act(ctx, _decision("investigate", "learner", "", a["hypothesis"], "a registered, bounded experiment"), do, "register_experiment")


# --- S68: what the workers use to hand work on, judge it and finish (hq/workers.py, hq/missions.py) ---------------------------------------

def reproduce_calc(ctx: Ctx, a: dict) -> dict:
    """The reviewer's tool: run a kept calculation again on the data it originally ran on and list every difference."""
    from pflab.agents import sandbox as sb
    from pflab.hq import cases
    try:
        out = cases.reproduce(ctx.con, int(a["calc_id"]), basis="original")
    except sb.SandboxUnavailable as e:
        ctx.wait_for = "sandbox"
        return {"waiting": True, "why": f"the sandbox (Docker) must run: {e}"}
    except LookupError as e:
        return {"error": str(e)}
    return {k: out[k] for k in ("reproduced", "basis", "label", "same_as_kept", "differences", "problems") if k in out} \
        | {"result": dict(list((out.get("result") or {}).items())[:12]), "kept": dict(list((out.get("kept") or {}).items())[:12])}


def submit_review(ctx: Ctx, a: dict) -> dict:
    """The independent reviewer's verdict on a mission's work: approve, or revise with specific requests (each names a role and what to fix).
    Saved as a review artifact; a revision request becomes a new task for that role (hq/missions.py)."""
    from pflab.hq import cases
    from pflab.pm.store import next_id
    c = _case(ctx, a)
    reqs = []
    try:
        reqs = json.loads(a.get("revisions_json") or "[]")
        if not isinstance(reqs, list):
            raise ValueError("not a list")
    except ValueError as e:
        return {"stored": False, "problem": f"revisions_json must be a JSON list of {{role, what}} ({e})"}
    if a["verdict"] == "revise" and not reqs:
        return {"stored": False, "problem": "a revise verdict names at least one specific request {role, what}"}
    rid = next_id(ctx.con, "hq_case_reviews", "review_id")
    note = _checked(ctx, a["findings"])
    ctx.con.execute("INSERT INTO hq_case_reviews VALUES (?,?,?,?,?,?)",
                    [rid, c["id"], ctx.now, json.dumps({"independent": True, "model": ctx.model, "checks": a.get("checks", ""), "revisions": reqs[:6]}),
                     {"approve": "approved", "revise": "revise", "reject": "rejected"}[a["verdict"]], note])
    cases.log(ctx.con, c["id"], ctx.now, "independent review", f"{a['verdict']}: {note[:300]}")
    note_artifact(ctx, c["id"], "review", rid, a["verdict"])
    from pflab.hq import proposals
    proposals.review_case(ctx.con, ctx.now, c["id"], a["verdict"], note)
    return {"stored": True, "review_id": rid, "verdict": a["verdict"]}


def request_artifact(ctx: Ctx, a: dict) -> dict:
    """A worker needs another worker's product (the quant needs the research's evidence; the research needs a number): a task for that role is
    queued and THIS task parks until it is done; it resumes with the artifact in its dossier. Not a loop: bounded per mission."""
    from pflab.hq import missions
    if not ctx.task_id:
        return {"queued": False, "problem": "only a worker task can wait for another's work"}
    if ctx.role and a["role"] == ctx.role:                  # S76: the first paper rehearsal chained eight quant tasks, each asking the next for the same thing; do it yourself
        return {"queued": False, "problem": f"you are the {ctx.role}: do this yourself, and ask another role only for what is theirs (evidence from research, a calculation from the quant)"}
    out = missions.add_task(ctx.con, ctx.now, int(a["case_id"]), a["role"], _checked(ctx, a["what"]), promise=json.loads(a.get("promise_json") or "{}"),
                            asked_by=ctx.task_id)
    if not out.get("task_id"):
        return {"queued": False, **out}
    ctx.wait_for = f"task:{out['task_id']}"
    return {"queued": True, "task_id": out["task_id"], "note": "finish this turn: your task parks until it is done, then resumes with its artifact in the dossier"}


def plan_mission(ctx: Ctx, a: dict) -> dict:
    """The coordinator's plan: the steps (role, goal, what each must produce, what it depends on). Code validates and creates the tasks."""
    from pflab.hq import missions
    try:
        steps = json.loads(a["steps_json"])
    except ValueError as e:
        return {"stored": False, "problem": f"steps_json is not JSON ({e})"}
    out = missions.set_plan(ctx.con, ctx.now, int(a["case_id"]), steps, _checked(ctx, a.get("approach", "")))
    if out.get("stored"):
        note_artifact(ctx, int(a["case_id"]), "plan", out["mission_id"], f"{len(steps)} steps")
    return out


def submit_answer(ctx: Ctx, a: dict) -> dict:
    """The coordinator's final answer for the investor: plain words, only numbers that the case's artifacts hold; what ran, what could
    invalidate it, what is monitored next. Closing the case with `case_close` follows."""
    from pflab.hq import missions
    c = _case(ctx, a)
    try:
        trig = json.loads(a.get("triggers_json") or "[]")
        if not isinstance(trig, list):
            raise ValueError("not a list")
    except ValueError as e:
        return {"stored": False, "problem": f"triggers_json must be a JSON list of trigger objects ({e})"}
    out = missions.set_answer(ctx.con, ctx.now, c["id"], _checked(ctx, a["answer"]), _checked(ctx, a["limitations"]), _checked(ctx, a["monitor_next"]),
                              triggers=trig, change=a.get("change", ""))
    if out.get("stored"):
        note_artifact(ctx, c["id"], "answer", out["mission_id"], "final")
    return out


def _his_message(ctx: Ctx) -> str:
    """What he just typed, as the assistant received it. Approval is his word, not the model's, and not a tool result's."""
    return (ctx.his_text or "").strip()


_YES = __import__("re").compile(r"\b(approve[ds]?|yes|yep|yeah|go ahead|go on|proceed|do it|okay|ok|sure|start it|run it|looks good|fine by me|accept(ed)?)\b", __import__("re").I)
_NO = __import__("re").compile(r"\b(no|not|don't|dont|do not|wait|stop|hold off|reject|decline|cancel|withdraw|never)\b", __import__("re").I)


def _said_yes(ctx: Ctx) -> bool:
    m = _his_message(ctx)
    return bool(m) and bool(_YES.search(m)) and not _NO.search(m)


def _said_no(ctx: Ctx) -> bool:
    m = _his_message(ctx)
    return bool(m) and bool(_NO.search(m))


def amend_investigation(ctx: Ctx, a: dict) -> dict:
    """He changes an instruction in conversation ("also look at X", "use a smaller amount", "ignore the first source"): it becomes the next numbered version of that
    investigation and persists, without any release. The coordinator replans only what changes. A change of scope or a financial policy waits for his yes again."""
    from pflab.hq import plans, pool
    out = plans.amend(ctx.con, ctx.now, int(a["case_id"]), _checked(ctx, a["instruction"]), scope_change=bool(a.get("scope_change")),
                      financial_policy=bool(a.get("financial_policy")), by="the investor (chat)")
    if out.get("amended"):
        pool.wake()
        wake = getattr(ctx.rt, "wake_hq", None)
        if wake:
            wake()
    return out


def decide_plan(ctx: Ctx, a: dict) -> dict:
    """His yes (or no) to the plan that waits. Only his own words in this message count: the tool checks them, the model's say-so is not enough."""
    from pflab.hq import plans, pool
    if a["decision"] == "approve":
        if not _said_yes(ctx):
            return {"approved": False, "why": "his message does not clearly approve; ask him to say 'approve' (or 'no' to decline)"}
        out = plans.approve(ctx.con, ctx.now, int(a["case_id"]), by="the investor (chat)", note=_his_message(ctx)[:120])
        pool.wake()
    else:
        if not _said_no(ctx):
            return {"declined": False, "why": "his message does not clearly decline the plan"}
        out = plans.decline(ctx.con, ctx.now, int(a["case_id"]), by="the investor (chat)", note=_his_message(ctx)[:120])
    wake = getattr(ctx.rt, "wake_hq", None)
    if wake:
        wake()
    return out


def make_proposal(ctx: Ctx, a: dict) -> dict:
    """A buy, add, hold, reduce, sell, diversify or wait recommendation. You give the direction, the company and the reasons; the system computes every number
    (price and date, cash, size, charges, weights, tax from the lots) from the record, and says what is missing. Never an order."""
    from pflab.hq import proposals
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.hq import cases as _cases
    cid = int(a["case_id"]) if a.get("case_id") else None
    if cid and _cases.get(ctx.con, cid) is None:               # a recommendation may be linked to a finished investigation (it is a link, not new evidence in it)
        return {"stored": False, "problem": f"no case #{cid}"}
    from pflab.paper import manager as _pm
    if _pm.is_paper(ctx.con, cid):                              # S76: a paper mission decides for the paper portfolio, never for his money
        return {"stored": False, "problem": "this mission manages the paper portfolio: record the decision with paper_decide"}
    inputs = {k: a.get(k) for k in ("action", "symbol", "isin", "qty", "amount_rupees", "full_exit", "assumptions", "review_condition")}
    inputs["reason"] = _checked(ctx, a.get("reason", ""))
    inputs["alternatives"] = _checked(ctx, a.get("alternatives", ""))
    try:
        inputs["evidence_ids"] = json.loads(a.get("evidence_ids_json") or "[]")
    except ValueError:
        inputs["evidence_ids"] = []
    if a.get("proposal_id"):
        old = proposals.get(ctx.con, int(a["proposal_id"]))
        if not old or old["status"] != "proposed":
            return {"stored": False, "problem": "only a proposal that is still open can be amended"}
        b = proposals.build(ctx.con, ctx.now, {**inputs, "isin": old["isin"]})
        if "problem" in b:
            return {"stored": False, "problem": b["problem"]}
        from pflab.hq import missions
        snap = missions.snapshot_id(ctx.con, ctx.rt.pm_dir)
        b["payload"]["portfolio"] = {**(b["payload"].get("portfolio") or {}), "snapshot": snap}
        out = proposals.amend_stored(ctx.con, ctx.now, int(a["proposal_id"]), b, snap, f"{ctx.role or 'assistant'}", why=inputs["reason"][:160])
    else:
        out = proposals.create(ctx.con, ctx.now, inputs, pm_dir=ctx.rt.pm_dir, case_id=cid, by=ctx.role or "assistant")
    if out.get("stored") and cid:
        note_artifact(ctx, cid, "proposal", out["proposal_id"], f"{str(a['action']).upper()} v{out['version']}")
    return out


def paper_book_tool(ctx: Ctx, a: dict) -> dict:
    """S76: the paper portfolio the system runs by itself: holdings, cash, rails, open orders, recent decisions, its record and the gate to his money."""
    from pflab.paper import book, manager
    if not book.started(ctx.con):
        return {"started": False, "note": "the paper portfolio has not started yet"}
    v = manager.book_view(ctx.con, ctx.now.date())
    v["gate"] = manager.gate(ctx.con, ctx.rt.data_root)
    return v


def paper_decide(ctx: Ctx, a: dict) -> dict:
    """S76: one decision for the paper portfolio (a paper mission only): code sizes it; it is executed at the close only if the review approves the mission."""
    from pflab.paper import manager
    if ctx.shadow:
        return _SHADOW_CASE
    cid = int(a["case_id"]) if a.get("case_id") else None
    if cid is None:
        r = ctx.con.execute("SELECT case_id FROM hq_tasks WHERE task_id=?", [ctx.task_id]).fetchone() if ctx.task_id else None
        cid = int(r[0]) if r and r[0] else None
    inputs = dict(a)
    inputs["reason"] = _checked(ctx, a.get("reason", ""))
    inputs["alternatives"] = _checked(ctx, a.get("alternatives", ""))
    inputs["_prov"] = {"pass_id": ctx.pass_id, "task_id": ctx.task_id, "role": ctx.role, "model": ctx.model, "call_ref": ctx.call_ref,        # S79b 18C: who is deciding (provenance)
                       "cited_text": f"{a.get('reason', '')} {a.get('alternatives', '')}"}
    out = manager.decide(ctx.con, ctx.now, cid, inputs, manager._index(ctx.rt.data_root))
    if out.get("stored"):
        note_artifact(ctx, cid, "proposal", out["decision_id"], f"paper {out['action']}")
    return out


def paper_ask(ctx: Ctx, a: dict) -> dict:
    """S76: he asks the paper portfolio to look into something (one input it may overrule)."""
    from pflab.paper import manager
    if ctx.shadow:
        return _SHADOW_CASE
    return manager.add_input(ctx.con, ctx.now, a.get("text", ""))


def chart_view(ctx: Ctx, a: dict) -> dict:
    """S78: look at a candlestick chart. The picture is attached to this tool's result (the model sees it); the facts about the same candles come back as numbers to quote.
    Daily and weekly come from the exchange's files; 15 minute and 1 hour from Kite when there is a login today (read only)."""
    import base64
    from pflab.quant import candles, chart
    sym = str(a.get("symbol") or "").strip().upper()
    isin = _isin(ctx, sym)
    tf = a.get("timeframe") or "daily"
    bars = int(a.get("bars") or 90)
    kite = None
    if tf in ("60min", "15min"):
        try:
            from pflab.ingest import kite as km
            kite = km.client(ctx.rt.secrets, now=ctx.now) if getattr(ctx.rt, "secrets", None) is not None else None
        except Exception:
            kite = None
    df, source = candles.get(ctx.rt.data_root, isin, sym, tf, ctx.now, bars, kite=kite)
    if df.empty:
        return {"seen": False, "problem": source if "Kite" in source else f"no {tf} candles on record for {sym}", "source": source}
    f = chart.facts(df, tf)
    png = chart.render(df, f"{sym}", tf)
    ctx.images.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode("ascii")}})
    return {"seen": True, "symbol": sym, "source": source, "picture": "attached to this result: candlesticks, volume, SMA20 (amber) and SMA50 (blue), the range's high and low dashed",
            "facts": f, "how_to_use": "say what you SEE (trend, support, gaps, volume) and quote the numbers from `facts`; a claim the facts do not support is not evidence"}


def watchlist_tool(ctx: Ctx, a: dict) -> dict:
    """S78: the system's watchlist: ideas it waits on, each with the point its own calculation set, its price now and its status."""
    from pflab.paper import watch
    return {"watchlist": watch.listing(ctx.con, ctx.now), "how": "each item is checked every round; TRIGGERED means the price reached its point and the team should look again; nothing is bought by itself"}


def watch_add(ctx: Ctx, a: dict) -> dict:
    """S78: put an idea on the watchlist. The team names the calculation its numbers come from (checked by code); he may give his own numbers in the chat."""
    from pflab.paper import manager, watch
    if ctx.shadow:
        return _SHADOW_CASE
    cid = int(a["case_id"]) if a.get("case_id") else None
    his = ctx.role == "assistant"
    return watch.add(ctx.con, ctx.now, symbol=a.get("symbol"), kind=a.get("kind", "zone"), reason=_checked(ctx, a.get("reason", "")) if not his else str(a.get("reason", "")),
                     by="the investor" if his else (ctx.role or "the team"), zone_low=a.get("zone_low"), zone_high=a.get("zone_high"), fall_pct=a.get("fall_pct"),
                     calc_id=int(a["calc_id"]) if a.get("calc_id") else None, case_id=cid, his_numbers=his)


def watch_remove(ctx: Ctx, a: dict) -> dict:
    """S78: take an idea off the watchlist (by id or symbol), with the reason."""
    from pflab.paper import watch
    if ctx.shadow:
        return _SHADOW_CASE
    return watch.remove(ctx.con, ctx.now, a.get("watch"), a.get("why", ""))


def proposals_tool(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import proposals
    from pflab.paper import manager as _pm
    cid = int(a["case_id"]) if a.get("case_id") else (ctx.con.execute("SELECT case_id FROM hq_tasks WHERE task_id=?", [ctx.task_id]).fetchone() or [None])[0] if ctx.task_id else None
    if _pm.is_paper(ctx.con, cid):                              # S76: a paper mission's decisions are paper decisions, not proposals for his money
        return {"paper_decisions": _pm.decisions_of(ctx.con, int(cid)), "note": "these are the paper portfolio's decisions for this mission; they are executed on paper only if the review approves"}
    if a.get("proposal_id"):
        p = proposals.get(ctx.con, int(a["proposal_id"]))
        return {"proposal": p, "stale": proposals.stale_reason(ctx.con, p, ctx.rt.pm_dir) if p else None} if p else {"error": "no such proposal"}
    rows = proposals.listing(ctx.con, status=a.get("status"), case_id=int(a["case_id"]) if a.get("case_id") else None, limit=12)
    return {"proposals": [{"id": p["proposal_id"], "action": p["action"], "symbol": p["symbol"], "status": p["status"], "review": p["review_status"], "version": p["version"],
                           "snapshot": p["snapshot_id"], "strategy": p["strategy_version"], "case": p["case_id"], "missing": p["missing"][:3],
                           "size": (p["payload"].get("size") or {}).get("qty"), "made": p["created_at"][:10]} for p in rows]}


def decide_proposal(ctx: Ctx, a: dict) -> dict:
    """Discuss, accept, reject or withdraw a proposal. Accept and reject are his decisions: they need his own words in this message. Accepting records that HE
    will act; it places no order."""
    from pflab.hq import proposals
    pid = int(a["proposal_id"])
    d = a["decision"]
    if d == "discuss":
        return proposals.discuss(ctx.con, ctx.now, pid, _checked(ctx, a.get("note", ""))[:500], by="the investor (chat)")
    if d == "accept" and not _said_yes(ctx):
        return {"ok": False, "why": "his message does not clearly accept; ask him to say 'accept' (nothing is ordered either way)"}
    if d in ("reject", "withdraw") and not _said_no(ctx):
        return {"ok": False, "why": "his message does not clearly reject or withdraw it"}
    return proposals.decide(ctx.con, ctx.now, pid, d, by="the investor (chat)", note=_his_message(ctx)[:160])


def policy_scenarios(ctx: Ctx, a: dict) -> dict:
    """The deployment-policy scenario study (quant/policies.py): his current staged approach, phased buying under explicit rules, holding cash until a
    fall, and all-in-now, across a sharp fall, a prolonged decline, a fall and recovery, and no crash. Trusted code; the paths and the rest are
    assumptions you state. Kept as a reproducible calculation."""
    from pflab.hq import missions
    from pflab.quant import policies, trusted
    keys = ("amount", "horizon_months", "fall_pct", "fall_months", "decline_pct", "decline_months", "recover_months", "drift_pa", "vol_pa", "cash_rate_pa",
            "cost_bps", "staged_months", "base_months", "reserve_share", "dip_trigger", "wait_trigger", "max_wait")
    prm = {("amount" if k == "amount" else k): a[k] for k in keys if a.get(k) is not None}
    if "amount" in prm:
        prm["amount"] = float(prm["amount"])
    prm["label"] = f"snapshot {missions.snapshot_id(ctx.con, ctx.rt.pm_dir)}"
    res = trusted.plain(policies.run(**prm))
    c = _case(ctx, a)
    kid = trusted.record(ctx.con, c["id"], ctx.now, "policy_scenarios", a.get("why", "deployment policies across market paths")[:300], prm, {}, res)
    note_artifact(ctx, c["id"], "scenario", kid, "checked")
    note_artifact(ctx, c["id"], "calc", kid, "checked")
    return {"calc_id": kid, "kind": "scenario", "assumptions": res["assumptions"], "policies": res["policies"], "best_terminal_by_path": res["best_terminal_by_path"],
            "table": [{k: r[k] for k in ("path", "policy", "return_pct", "worst_value_vs_amount_pct", "max_drawdown_pct", "months_below_amount")} for r in res["table"]],
            "weights_note": "no probability is attached to any path; a weighting would be an assumption",
            "note": "a hypothetical scenario study, not a forecast and not a backtest; the reviewer reruns it from calc #" + str(kid)}


def exposure_shock_tool(ctx: Ctx, a: dict) -> dict:
    """What a stated equity fall would cost the portfolio as it stands now (hypothetical scenario, trusted code, reproducible): each holding falls by the
    stated fall times its beta (default 1). Use it instead of writing code for the arithmetic of a fall."""
    from pflab.hq import missions
    from pflab.pm import today
    from pflab.quant import trusted
    t = today.build(ctx.con, ctx.asof)
    pos = t["positions"]
    pos = pos[pos["value"].notna() & (pos["qty"] > 0)].groupby("symbol", as_index=False)["value"].sum()
    cash = float(t["buckets"].get("cash", 0.0)) + float(t["buckets"].get("debt", 0.0))
    try:
        betas = json.loads(a.get("betas_json") or "{}")
        falls = [float(x) for x in json.loads(a["falls_json"])]
    except (ValueError, TypeError):
        return {"error": "falls_json must be a JSON list of numbers and betas_json a JSON object {symbol: beta}"}
    prm = {"cash": cash, "falls_pct": falls, "betas": betas, "default_beta": float(a.get("default_beta", 1.0)),
           "label": f"snapshot {missions.snapshot_id(ctx.con, ctx.rt.pm_dir)}"}
    res = trusted.plain(trusted.TRUSTED["exposure_shock"]({"positions": pos}, prm))
    c = _case(ctx, a)
    kid = trusted.record(ctx.con, c["id"], ctx.now, "exposure_shock", a.get("why", "loss from a stated equity fall")[:300], prm, {"positions": pos}, res)
    note_artifact(ctx, c["id"], "scenario", kid, "checked")
    note_artifact(ctx, c["id"], "calc", kid, "checked")
    return {"calc_id": kid, "kind": "scenario", "total_rupees": res["total_rupees"], "equity_rupees": res["equity_rupees"], "cash_and_debt_rupees": res["cash_rupees"],
            "table": [{k: r[k] for k in ("index_fall_pct", "loss_rupees", "loss_pct_of_total")} for r in res["table"]], "assumptions": res["assumptions"]}


def ipo_policy_study(ctx: Ctx, a: dict) -> dict:
    """Sell-or-hold policies for an IPO allotment evaluated on the history of large listings since 2016 (quant/ipo_policy.py): development 2016-2019,
    validation 2020-2021, baseline sell at the listing close; listing-day information only. Trusted code; kept as a reproducible calculation."""
    from pflab.plan import ipo
    from pflab.quant import ipo_policy, trusted
    t = ipo.big_listings(ipo.listing_table(ctx.rt.data_root))
    t = t[t["date"] < "2022-01-01"][["isin", "date", "gain_open", "gain_close", "r5", "r20", "r60"]].reset_index(drop=True)
    stcg = None
    try:
        from pflab import _toml
        from pathlib import Path
        stcg = float(_toml.load(Path(__file__).resolve().parents[3] / "configs" / "tax_policy_in.toml")["tax"]["stcg_rate"])
    except Exception:
        pass
    prm = {k: a[k] for k in ("qty", "issue") if a.get(k) is not None}
    if stcg is not None:
        prm["stcg"] = stcg
    res = trusted.plain(ipo_policy.run(t, **prm))
    c = _case(ctx, a)
    kid = trusted.record(ctx.con, c["id"], ctx.now, "ipo_policy", "IPO sell or hold policies on listing history", prm, {"listings": t}, res)
    note_artifact(ctx, c["id"], "calc", kid, "checked")
    return {"calc_id": kid, "kind": "calculation", "periods": {k: {"window": v["window"], "listings": v["listings"],
                                                                 "policies": {p: {x: y for x, y in d.items() if x != "vs_baseline"} for p, d in v["policies"].items()}}
                                                     for k, v in res["periods"].items()},
            "verdict": res["verdict"], "limits": res["limits"], "tests_in_this_study": res["tests_in_this_study"]}


def start_investigation(ctx: Ctx, a: dict) -> dict:
    """The assistant starts a mission (research, quant and an independent review run in the background; results come back into the conversation)."""
    from pflab.hq import missions
    out = missions.create(ctx.con, ctx.now, _checked(ctx, a["goal"]), pm_dir=ctx.rt.pm_dir)
    wake = getattr(ctx.rt, "wake_hq", None)
    if wake:
        wake()
    return {**out, "note": "it runs by itself; its progress and result will appear in this conversation"}


def open_workspace(ctx: Ctx, a: dict) -> dict:
    """A scratch case for a calculation or a scenario asked in conversation (the case tools need one). The brain's case pass never takes it."""
    from pflab.hq import cases
    cid, new = cases.open_case(ctx.con, ctx.now, _checked(ctx, a["topic"]), origin="chat", key=f"workspace:{_h(a['topic'])}:{ctx.now:%Y%m%d}")
    if new:
        cases.set_status(ctx.con, cid, "workspace", ctx.now, "the assistant's scratch case")
    if cid not in ctx.case_ids:
        ctx.case_ids.append(cid)
    return {"case_id": cid, "new": new, "note": "use this case_id with the calculation and scenario tools"}


def work_status(ctx: Ctx, a: dict) -> dict:
    """What is being worked on and what waits for him, from the store."""
    from pflab.hq import missions
    con = ctx.con
    ids = [r[0] for r in con.execute("SELECT case_id FROM hq_missions ORDER BY mission_id DESC LIMIT 8").fetchall()]
    cards = []
    for cid in ids:
        c = missions.card(con, cid)
        cards.append({k: c[k] for k in ("case_id", "goal", "state", "owner", "current_action", "blocker", "next_trigger", "last_useful_progress")}
                     | {"outputs": len(c["outputs"]), "answer": (c["answer"] or {}).get("answer", "")[:400] if c["answer"] else None})
    from pflab.agents import questions
    needs = [{"q_id": q, "text": t[:200]} for q, _, t in questions.open_questions(con)][:6]
    return {"investigations": cards, "needs_from_him": needs, "source": "hq_missions, the board and the questions"}


def remember_fact(ctx: Ctx, a: dict) -> dict:
    """Keep what he said so it survives restarts: a goal, an answered fact, or a hypothesis. Appends only; it never changes a target or a limit."""
    from pflab.agents import memory as mem
    kind = {"goal": "note", "answer": "answer", "hypothesis": "note", "note": "note"}[a["kind"]]
    mid = mem.remember(ctx.con, kind, f"[{a['kind']}] {_checked(ctx, a['text'])}", subject=a["kind"], source="the assistant, from his words", now=ctx.now)
    return {"remembered": mid, "note": "kept; this does not change any target, limit or the stock list"}


def recall_tool(ctx: Ctx, a: dict) -> dict:
    """Working memory on a subject (S72): what the system concluded before and why, what goes against it, which checked calculations can be re-run, what changed, what is open."""
    from pflab.kg import memory
    rec = memory.recall(ctx.con, (a.get("about") or ctx.source or "")[:1500], ctx.now, exclude_case=(ctx.case_ids[0] if ctx.case_ids else None))
    return {"brief": memory.brief(rec) or "nothing earlier on this subject", "subjects": rec["subjects"], "conclusions": rec["conclusions"], "contradictions": rec["contradictions"],
            "methods": rec["methods"], "changed": rec["changed"], "open": rec["open"], "effects_last_30_days": memory.effects_summary(ctx.con, 30, ctx.now),
            "note": "a conclusion marked older has a newer investigation on the same subject; a method listed is re-run on today's record, not rewritten"}


def rules_tool(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import rules
    return {"version": rules.version(ctx.con), "active": [{k: r[k] for k in ("rule_id", "kind", "name", "text", "version")} for r in rules.active(ctx.con)],
            "waiting_for_his_yes": [{k: r[k] for k in ("rule_id", "kind", "name", "text")} for r in rules.pending(ctx.con)]}


def envelope_tool(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import stocks
    from pflab.plan import envelope
    try:
        index = stocks.index_series(ctx.rt.data_root)
    except Exception:
        index = None
    s = envelope.status(ctx.con, ctx.now.date(), index)
    return {**s, "in_words": envelope.explain(s)}


def scorecard_tool(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import scorecard
    n = ctx.con.execute("SELECT count(*), count(*) FILTER (WHERE outcome IN ('good', 'bad')) FROM hq_claims").fetchone()
    return {"claims_stated": int(n[0]), "claims_scored": int(n[1]), "by_decision_and_market_state": scorecard.table(ctx.con),
            "note": "a rate is shown only from 20 scored claims; the skeptical rate is the 20th percentile of Beta(1+good, 1+bad); it describes, it never changes a limit"}


_UNDO = __import__("re").compile(r"\b(undo|remove|cancel|drop|forget|revoke|delete|stop (that|this|the)|never ?mind|take (that|it) back|no longer)\b", __import__("re").I)


def add_rule(ctx: Ctx, a: dict) -> dict:
    """He tells the system how to work from now on (a house rule). Not about money: active at once, with an Undo. About an amount or a limit: it waits for his yes."""
    from pflab.hq import rules
    if not _his_message(ctx):
        return {"made": False, "why": "a house rule is made from his own message in this turn"}
    try:
        machine = json.loads(a.get("machine_json") or "{}")
    except ValueError:
        return {"made": False, "why": "machine_json must be a JSON object"}
    out = rules.propose(ctx.con, ctx.now, a["kind"], a["text"], machine if isinstance(machine, dict) else {}, name=a.get("name", ""), by="the investor (chat)", source=_his_message(ctx))
    if out.get("made"):
        rules.render(ctx.con, ctx.rt.pm_dir)
        out["note"] = ("It waits for his yes because it is about money: ask him to say yes, then call decide_rule." if out["needs_yes"]
                       else "It is active now and every agent reads it; he can undo it by saying so. " + (f"It covers these sectors: {', '.join(out['covers'])}." if out.get("covers") else ""))
    return out


def undo_rule(ctx: Ctx, a: dict) -> dict:
    from pflab.hq import rules
    if not _UNDO.search(_his_message(ctx)):
        return {"undone": False, "why": "his message does not ask to undo a rule; ask him"}
    out = rules.undo(ctx.con, ctx.now, a["rule"])
    if out.get("undone"):
        rules.render(ctx.con, ctx.rt.pm_dir)
    return out


def decide_rule(ctx: Ctx, a: dict) -> dict:
    """His yes or no to a house rule about money. Only his own words in this message count."""
    from pflab.hq import rules
    yes = a["decision"] == "approve"
    if (yes and not _said_yes(ctx)) or (not yes and not _said_no(ctx)):
        return {"decided": False, "why": "his message does not clearly say " + ("yes" if yes else "no") + " to this rule"}
    out = rules.decide(ctx.con, ctx.now, int(a["rule_id"]), yes)
    if out.get("decided"):
        rules.render(ctx.con, ctx.rt.pm_dir)
    return out


def waiting_tool(ctx: Ctx, a: dict) -> dict:
    """What waits for his yes about limits, theme baskets and the opportunity pot, each with its Q# (say the Q# when you put it to him: his answer is accepted only for a question he was just shown)."""
    rows = ctx.con.execute("SELECT q_id, text, created_at FROM questions WHERE status = 'open' AND agent = 'limits' ORDER BY q_id").fetchall()
    return {"waiting_for_his_yes": [{"q": f"Q#{q}", "text": t, "since": str(c)[:10]} for q, t, c in rows],
            "how": "put one to him in plain words with its Q#; when he says yes or no in his next message, call answer_question"}


def answer_question(ctx: Ctx, a: dict) -> dict:
    """His yes or no to a limit, theme basket or the opportunity pot, the same act as the Needs-from-you button. Only his own clear yes or no counts, and only for a question
    that was shown to him in the last few messages of this conversation (its Q# appears there)."""
    from pflab.agents import questions as qs
    from pflab.app import assistant
    from pflab.risk import themes
    qid = int(a["q_id"])
    q = ctx.con.execute("SELECT agent, status, text FROM questions WHERE q_id = ?", [qid]).fetchone()
    if q is None or q[1] != "open" or q[0] != "limits":
        return {"answered": False, "why": "no open limit or pot question with that number"}
    yes = a["answer"] == "yes"
    if (yes and not _said_yes(ctx)) or (not yes and not _said_no(ctx)):
        return {"answered": False, "why": "his message does not clearly say " + a["answer"]}
    shown = " ".join(t for (t,) in ctx.con.execute("SELECT text FROM chat_messages WHERE chat_id = ? AND role = 'ai' AND status = 'done' ORDER BY msg_id DESC LIMIT 4",
                                                    [assistant.thread(ctx.con, ctx.now)]).fetchall())
    if f"Q#{qid}" not in shown:
        return {"answered": False, "why": f"Q#{qid} was not put to him in this conversation just now; tell him what it is (with its Q#) and ask"}
    qs.answer(ctx.con, qid, a["answer"], ctx.now)
    return {"answered": True, "q": f"Q#{qid}", "applied": themes.resolve(ctx.con, ctx.now), "what": q[2][:200]}


def propose_software_change(ctx: Ctx, a: dict) -> dict:
    """The system can say that a tool is missing or something is broken, with the evidence and, if it has one, a patch as TEXT. It never edits
    the application: a person takes the issue to the development workflow."""
    if ctx.shadow:
        return _SHADOW_CASE
    from pflab.pm.store import next_id
    iid = next_id(ctx.con, "hq_issues", "issue_id")
    ctx.con.execute("INSERT INTO hq_issues VALUES (?,?,?,?,?,?,?,?,?)",
                    [iid, ctx.now, a["kind"], _checked(ctx, a["title"])[:200], _checked(ctx, a["evidence"])[:1500], a.get("repro", "")[:1500] or None,
                     a.get("proposed_patch", "")[:6000] or None, "proposed", "brain"])
    return {"issue_id": iid, "applied": False, "note": "kept as a proposal for the development workflow; the running application is never edited by itself"}


def resolve_task(ctx: Ctx, a: dict) -> dict:
    """A task the hop limit held: run it once (the chain stays counted) or close it, with the reason kept."""
    from pflab.hq import board
    t = board.get(ctx.con, int(a["task_id"]))
    if t is None or t["status"] != "held":
        raise ValueError(f"task #{a['task_id']} is not held")
    why = _checked(ctx, a["reason"])
    by = f"brain pass #{ctx.pass_id}"
    fn = (lambda: board.release(ctx.con, t["id"], ctx.now, by)) if a["resolution"] == "release" else \
         (lambda: board.dismiss(ctx.con, t["id"], ctx.now, by, why))
    return _act(ctx, _decision("investigate" if a["resolution"] == "release" else "nothing", t["body"].get("meant_for") or "", f"task #{t['id']}",
                               t["text"][:200], f"{a['resolution']}: {why}"), lambda: str(fn()), "resolve_task")


SYMBOL = _s("NSE symbol of a held or listed stock", 20)
DAYS = _i("days back", 1, 365)
TOOLS: Dict[str, Tool] = {t.name: t for t in [
    Tool("portfolio", "read", "The portfolio today: buckets against targets and bands, holdings by weight and gain, "
         "direct stocks' and all holdings' unrealised gain, Kite against the statements.", {}, (), portfolio),
    Tool("stocks_overview", "read", "One row per held and listed stock: weight, its share, gap, gain, 3-month return, "
         "guard, zone, chance of touching 10% below within 63 sessions, edge after costs with n and t; and the market's "
         "tested states (the dip rule, the market state).", {}, (), stocks_overview),
    Tool("stock_facts", "read", "One stock in full: drift (weight against its share and the bucket's bands, trend), odds "
         "(10% moves over 21/63 sessions, touch chances of 5/10/20% falls, the buy zone), edge (excess over the Nifty "
         "500 after costs, n, t; a description, never a signal); also on request capm (beta, alpha with t, the CAPM "
         "expected return) and process (does its price revert to a mean or walk at random: ADF, variance ratios, "
         "half-life; descriptions, never signals); nudges (Kite-style pre-trade warnings: trade-to-trade, surveillance lists, insolvency, split or bonus coming, thin trading, suspension); business (12 quarters of revenue, profit and margins, holders and deals, peers ranked, concall and presentation filings); valuation (P/E now, against its own 5-year range and the "
         "market's, what growth the price assumes, volatility against its norm, and the usual rules of thumb as flags).",
         {"symbol": SYMBOL, "parts": {"type": "array", "items": {"type": "string", "enum": ["drift", "odds", "edge", "capm",
                                                                                          "process", "valuation", "business", "nudges"]},
                                      "description": "which parts (default drift, odds, edge, valuation)"}}, ("symbol",), stock_facts),
    Tool("tax_plan", "read", "Tax plan by code: per holding the FIFO ladder at today's price, long-term dates, what "
         "waiting saves, the 112A exemption left, loss sales.", {}, (), tax_plan),
    Tool("measure", "read", "A reviewed measure of a stock or index (NIFTY 50, NIFTY 500): drawdown, period_return, "
         "volatility, extreme_days, worst_run, var_cvar, chance_of_fall, relation (needs second).",
         {"measure": _s("which measure", enum=["drawdown", "period_return", "volatility", "extreme_days", "worst_run",
                                                "var_cvar", "chance_of_fall", "relation"]),
          "series": _s("a symbol, or NIFTY 50 / NIFTY 500", 30), "second": _s("second series for relation", 30),
          "start": _s("YYYY-MM-DD", 10), "end": _s("YYYY-MM-DD", 10), "fall_pct": _n("fall in percent", 0.5, 90),
          "sessions": _i("sessions", 1, 2520), "level": _n("confidence level", 0.5, 0.999)}, ("measure", "series"), measure),
    Tool("simulation", "read", "Monte Carlo (10,000 paths) of the current, target and your-stocks mixes: the chance of a "
         "35% fall, the one-year fan, the worst dated stress episodes.", {"years": _i("years", 1, 5)}, (), simulation),
    Tool("forecasts", "read", "The latest kept forecasts (turnover, results ranges) with the model serving each.",
         {"symbol": SYMBOL}, (), forecasts),
    Tool("readings", "read", "What the Haiku readers made of a stock's recent public documents (materiality, summary, "
         "checked figures).", {"symbol": SYMBOL, "days": DAYS}, ("symbol",), readings),
    Tool("graph_timeline", "read", "A stock's documents in the knowledge graph (filings, results, articles, notes) with "
         "their URLs.", {"symbol": SYMBOL, "days": DAYS}, ("symbol",), graph_timeline),
    Tool("notes", "read", "The analyst's newest cited note on a company.", {"symbol": SYMBOL}, ("symbol",), notes),
    Tool("memory_recall", "read", "Memory rows in force (decisions, reasons, outcomes, answers, notes) with their ids.",
         {"words": _s("words that must all appear", 200), "subject": _s("subject, e.g. a symbol", 40),
          "kind": _s("kind", enum=["decision", "reason", "outcome", "feedback", "answer", "note", "state"])}, (),
         memory_recall),
    Tool("journal", "read", "Your own recent passes, your prediction scorecard and your suggestions' record.", {}, (),
         journal),
    Tool("ready_plans", "read", "The ready plans kept current (next FD tranche, the monthly amount).", {}, (), ready_plans),
    Tool("research_flags", "read", "Research flags found by code (material filings, results, guards, news spikes, falls).",
         {"symbol": SYMBOL, "days": DAYS}, (), research_flags),
    Tool("price_history", "read", "A stock's trend and weekly closes.", {"symbol": SYMBOL, "days": _i("sessions back", 20, 750)},
         ("symbol",), price_history),
    Tool("quant", "read", "Tested quant templates (event studies, drift checks of adopted rules) for an idea.",
         {"idea": _s("the idea in words", 300)}, ("idea",), quant),
    Tool("record_prediction", "journal", "Keep a prediction: a stock's price change from the last close to the close on "
         "due (return_above / return_below a level in percent), due 5-90 days ahead, your confidence 0-1.",
         {"symbol": SYMBOL, "kind": _s("kind", enum=["return_above", "return_below"]), "level": _n("percent", -90, 500),
          "due": _s("YYYY-MM-DD", 10), "confidence": _n("probability", 0, 1), "claim": _s("the claim in words", 300)},
         ("symbol", "kind", "level", "due", "confidence", "claim"), record_prediction),
    Tool("record_suggestion", "journal", "Keep a suggestion for the investor in the suggestion ledger, scored at its "
         "horizon taken or not. Name the tools it rests on.",
         {"kind": _s("kind", enum=["add", "trim", "hold", "wait", "rebalance", "review", "other"]), "symbol": SYMBOL,
          "text": _s("the suggestion in one or two sentences", 600), "reasoning": _s("why, from the facts read", 1500),
          "horizon_days": _i("days until it is scored", 5, 180),
          "rested_on": {"type": "array", "items": {"type": "string", "enum": []}, "description": "tool names"}},
         ("kind", "text", "reasoning", "horizon_days", "rested_on"), record_suggestion),
    Tool("save_state", "journal", "Save your working state (what you found, what is left to do) to memory; the next "
         "context and the next pass start from it.", {"state": _s("the working state", 3000)}, ("state",), save_state),
    Tool("ask_investor", "action", "Ask the investor something only he can answer.",
         {"question": _s("the question", 400), "why": _s("why it matters", 400)}, ("question", "why"), ask_investor),
    Tool("tell_investor", "action", "Tell the investor something he should know today.",
         {"message": _s("the message", 600), "priority": _s("priority", enum=["low", "medium", "high"])},
         ("message", "priority"), tell_investor),
    Tool("order_research", "action", "Order the research analyst's cited note on a company (paid, priced first).",
         {"symbol": SYMBOL, "question": _s("the question", 400), "why": _s("why", 300)}, ("symbol", "question"),
         order_research),
    Tool("order_calculation", "action", "Order a calculation from the workshop (a reviewed measure or new code with a "
         "second writing).", {"question": _s("the question", 400), "why": _s("why", 300)}, ("question",),
         order_calculation),
    Tool("prepare_plan", "action", "Refresh the ready plans, or prepare one for an amount.",
         {"amount": _n("rupees", 1_000, 1e8), "why": _s("why", 300)}, ("why",), prepare_plan),
    Tool("correct_memory", "action", "Correct a memory row (the old row and your reason are kept).",
         {"mem_id": _i("the row's id", 1, 10 ** 9), "text": _s("the corrected text", 1500), "reason": _s("why", 400)},
         ("mem_id", "text", "reason"), correct_memory),
    Tool("fetch_cited", "action", "Read a page or filing the system already cites (its URL from notes or graph_timeline) "
         "and answer a question from it (paid).", {"url": _s("the cited URL", 600), "question": _s("the question", 400)},
         ("url", "question"), fetch_cited),
    Tool("who_is_buying", "read", "Who is buying or selling a stock: insider and SAST disclosures, bulk and block deals, "
         "promoters' holding and pledges, institutions (funds, FPIs) by quarter. Context, never a signal.",
         {"symbol": SYMBOL, "days": DAYS}, ("symbol",), who_is_buying),
    Tool("market_context", "read", "The market's backdrop: FII / FPI net equity flows (last day, 5 and 20 days), India "
         "VIX, Brent, the rupee, the US 10-year yield, the Nifty 500, each with its date and 30-day change.", {}, (),
         market_context),
    Tool("growth", "read", "Where the portfolio's change came from over a period: money put in, realised and unrealised "
         "gains, income, charges (the statements' ledger).", {"months": _i("months back", 1, 60)}, (), growth),
    Tool("findings", "read", "What the learner tested: claims from papers and blogs that passed a registered test on this "
         "system's data (for a stock signal, where each held and listed name sits today) and those that failed.", {}, (),
         findings),
    Tool("web_search", "action", "Search the web for a public fact the system's data lacks (news, a rule, an event); paid, "
         "a few a day. Never put the investor's holdings, amounts or anything personal in the question.",
         {"question": _s("the public question", 300), "why": _s("why it is needed", 300)}, ("question",), web_search),
    # S64: appended at the end, because the tool order fixes the prompt cache
    Tool("comovement", "read", "The peers a stock moves with (same industry, Nifty 500) from the weekly run: monthly "
         "correlation over 5 years, Engle-Granger cointegration (Benjamini-Hochberg adjusted), how often it held in "
         "rolling windows, the spread's half-life. A description: relations break (9% stayed cointegrated).",
         {"symbol": SYMBOL}, ("symbol",), comovement),
    Tool("ipo_plan", "read", "An IPO allotment and the money around it: what the shares are worth at any listing price, how large IPOs "
         "behaved (listing gain and the next 1-3 months), the overlap with the business group he already holds, tax on a sale, "
         "and what the standard plan does with the rest. Facts and choices, not a prediction.",
         {"name": _s("the company", 80), "shares": _i("shares allotted", 1, 1_000_000), "issue_price": _n("issue price in rupees", 1, 100_000),
          "budget": _n("rupees he wants to invest in all, allotment included", 1_000, 1e8), "group": _s("his business group name, e.g. reliance", 40)},
         ("name", "shares", "issue_price", "budget"), ipo_plan),
    Tool("picture", "read", "THE ONE PICTURE, built by code: the market's state and crash gauges, the news mood (and whether the news "
         "is current), the allocation against targets, every holding with its valuation, trend, news mood and warnings, the themes "
         "against their limits, cash and the dip reserve, what is on offer, what could hurt (scenarios), what changed, what waits "
         "for him, and what the system has learned. Call it FIRST in every pass; then dig into what it shows.", {}, (), picture_tool),
    Tool("scans", "read", "The saved scans (conditions from a closed set: moving averages, RSI, 52-week range, volume spike, P/E "
         "against its own median, alpha sign, futures build-up) with their last hits and whether the learner tested them.",
         {}, (), scans_tool),
    Tool("make_scan", "journal", "Make a scan from the closed set of conditions, as 'price_below_sma:200; volume_spike:2'. "
         "Information only, labelled not tested; hits on his names go into his evening summary.",
         {"name": _s("a short name", 80), "conditions": _s("conditions joined by ';'", 300),
          "universe": _s("universe", enum=["list", "holdings", "nifty500"])}, ("name", "conditions"), make_scan),
    Tool("scenario", "read", "A scenario chain on his holdings: oil_up_30 (Brent +30% in a month), rupee_down_10, us_crash "
         "(S&P 500 -20% in a month through the Nifty 500). Rupee impact per holding and in total with a +-2 standard-error range, "
         "from historical betas: a description, not a forecast.",
         {"name": _s("scenario", enum=["oil_up_30", "rupee_down_10", "us_crash"])}, ("name",), scenario),
    Tool("hypotheses", "read", "Your cause hypotheses: those the keeper handed over to decide now, and the recent ones with "
         "their status.", {"status": _s("status", enum=["open", "review", "confirmed", "refuted", "expired"])}, (), hypotheses),
    Tool("record_hypothesis", "journal", "Record 'this seems the cause' for a move: the subject (a symbol or a topic), the "
         "cause, the effect, the evidence (tool names read), a date to check by within 90 days, and a macro series if the cause "
         "is one (BRENT, USDINR, US_SP500), which the keeper then tests by code.",
         {"subject": _s("a symbol or topic", 60), "cause": _s("the suspected cause", 300), "effect": _s("what it did", 300),
          "evidence": {"type": "array", "items": {"type": "string"}, "description": "tool names or ids read"},
          "check_by": _s("YYYY-MM-DD, within 90 days", 10),
          "series": _s("macro series", enum=["BRENT", "USDINR", "US_SP500", "none"])},
         ("subject", "cause", "effect", "check_by"), record_hypothesis),
    Tool("decide_hypothesis", "journal", "Decide a hypothesis handed to you (hypotheses -> to_decide_now): confirmed or refuted "
         "from the evidence, with the reason.", {"hyp_id": _i("the id", 1, 10 ** 9), "verdict": _s("verdict", enum=["confirmed", "refuted"]),
                                                  "why": _s("the reason", 400)}, ("hyp_id", "verdict", "why"), decide_hypothesis),
    Tool("themes", "read", "Theme exposure (AI and IT, defence, EV and auto-tech) as a share of the portfolio with the limits he "
         "applied, pending proposals (limits, dip reserve, pot), and the opportunity pot with its ideas.", {}, (), themes_tool),
    Tool("propose_pot_idea", "journal", "Put a missed winner or a new listing into the opportunity pot: the reason in words; "
         "buy price, exit, stop and amount are computed by code. Needs the pot's limit applied by the investor.",
         {"symbol": SYMBOL, "reason": _s("why it belongs in the pot", 600)}, ("symbol", "reason"), propose_pot_idea),
    Tool("system_status", "read", "Whether the system itself is working and in sync: connectors (Kite, Telegram, the local model, the "
         "Claude API spend against his cap, the sandbox), how fresh each data source is, what is running, what failed, what needs him.",
         {}, (), system_status),
    Tool("cases", "read", "Your investigations: each open question with its evidence (for / against / missing / stale), what it waits for, its decision "
         "and next review. Look here first in a case pass.", {"scope": _s("which", enum=["active", "all"])}, (), cases_tool),
    Tool("open_case", "journal", "Open an investigation for an unresolved question or opportunity you found (the same question is one case). State the "
         "assumptions it rests on; a case is worked until you close it, it waits for a report, or it runs out of passes.",
         {"question": _s("the question to settle", 500), "symbol": SYMBOL, "assumptions": {"type": "array", "items": {"type": "string"},
          "description": "what the idea assumes, one short sentence each", "maxItems": 8}}, ("question",), open_case),
    Tool("case_evidence", "journal", "Add one piece of evidence to a case: what it says (copied from a tool result), whether it is for the idea, against "
         "it, neutral, or MISSING (looked for and not there: that is not evidence against), where it came from and when it was published.",
         {"case_id": _i("the case", 1, 10 ** 9), "stance": _s("stance", enum=["for", "against", "neutral", "missing"]),
          "text": _s("the evidence in a sentence or two", 700), "source_id": _s("the document or tool it came from", 120),
          "source_kind": _s("kind", enum=["filing", "result", "article", "web", "dataset", "email", "calculation", "observation"]),
          "published": _s("YYYY-MM-DD it was published", 10), "event": _s("YYYY-MM-DD the event happened", 10)},
         ("case_id", "stance", "text", "source_kind"), case_evidence),
    Tool("request_report", "action", "A case cannot go on without something you cannot get: name it. One request per key (asking twice changes nothing); the "
         "case waits and resumes by itself when it arrives. Say exactly what is needed (which report, which period).",
         {"case_id": _i("the case", 1, 10 ** 9), "key": _s("a short stable name for this request", 40), "what": _s("exactly what is needed", 400),
          "doc_kind": _s("if a public document of this kind about the company will do", enum=["filing", "result", "article", "dataset", "email"]),
          "period_end": _s("the date the period the report covers ends (YYYY-MM-DD): only a document published on or after it will do"),
          "inbox_kind": _s("the kind of file he must drop (for example result, cas, bank)"),
          "company": _s("a word that must appear in the file's name or text (the company)"),
          "from_inbox": {"type": "boolean", "description": "true if only a file he drops can supply it"}}, ("case_id", "key", "what"), request_report),
    Tool("case_calculate", "action", "A calculation for a case (reviewed measures first; else code is written, run in the sandbox, written a second time and "
         "compared). Script, data, parameters and result are kept. Needs the sandbox: with none the case waits for it.",
         {"case_id": _i("the case", 1, 10 ** 9), "question": _s("the calculation, defined exactly", 400)}, ("case_id", "question"), case_calculate),
    Tool("case_close", "journal", "Close a case with a decision (nothing, watch, suggest, ask, tell, inconclusive), the reason, what is still uncertain, and "
         "when to look again. Record any suggestion or message through its own tool.",
         {"case_id": _i("the case", 1, 10 ** 9), "decision": _s("decision", enum=["nothing", "watch", "suggest", "ask", "tell", "inconclusive"]),
          "reason": _s("why, from the evidence in the case", 600), "uncertainty": _s("what is still uncertain", 300),
          "review_days": _i("days until it is looked at again", 1, 90)}, ("case_id", "decision", "reason"), case_close),
    Tool("frame_objective", "journal", "Turn a wish (for example 'higher returns') into explicit objectives and the risk he would accept: a JSON frame with objectives "
         "[{measure, target, horizon_months, comparator}], acceptable_risk {max_fall_pct, cash_floor_months}, competing_explanations "
         "[{explanation, supported_by, refuted_by}] (at least two) and would_change_my_view [what evidence would change the recommendation]. A frame without numbers "
         "is kept as a draft and ONE grouped question goes to him; nothing is tested against a draft. A fall above his limit is a proposal; the limit stands.",
         {"wish": _s("his wish in his words", 300), "frame_json": _s("the frame as a JSON object", 3000), "case_id": _i("the case it belongs to, if any", 1, 10**9)},
         ("wish", "frame_json"), frame_objective),
    Tool("experiments", "read", "The bounded experiments: each registered question, its status, every attempt with the evaluator's measured result (not the candidate's claim), "
         "and how many variants have been searched in all (the bar rises with it).", {"experiment_id": _i("one experiment's attempts", 1, 10**9)}, (), experiments_tool),
    Tool("register_experiment", "action", "Register a hypothesis for a bounded experiment BEFORE any result is seen: what, why it matters, what would disprove it. The learner runs it "
         "in the sandbox against a registered comparator in fixed development and validation periods; most will fail, and that is kept. Two a day.",
         {"hypothesis": _s("the question as a testable rule", 400), "why_it_matters": _s("why it matters to him", 400), "disproof": _s("what result would disprove it", 400),
          "source": _s("where it came from", enum=["case", "claim", "data_issue", "process_failure", "investor"]), "case_id": _i("the case, if any", 1, 10**9),
         "contract": _s("the evaluation that judges it: index_timing (be in or out each month vs always invested) or deployment (how much of a waiting sum to put in each "
                        "month vs all at the start). A question of another kind is not an experiment: ask for a scenario or a calculation", enum=["index_timing", "deployment"])},
         ("hypothesis", "why_it_matters", "disproof", "source", "contract"), register_experiment),
    Tool("reproduce_calc", "action", "Run a kept calculation again on the data it originally ran on (the kept snapshot) and list every difference from the kept result. "
         "Use it to check a calculation before approving it.", {"calc_id": _i("the calculation", 1, 10 ** 9)}, ("calc_id",), reproduce_calc),
    Tool("submit_review", "journal", "Your independent review of the mission's work, with its own context: verdict approve, revise (with specific requests, each for a role) or "
         "reject. Check that every number in the evidence and calculations traces to a source or calc, that assumptions are labelled, that a baseline exists for any test, and that "
         "conclusions do not outrun the evidence.",
         {"case_id": _i("the case", 1, 10 ** 9), "verdict": _s("verdict", enum=["approve", "revise", "reject"]), "findings": _s("what you checked and found", 1500),
          "checks": _s("the checks you ran (reproductions, recomputations)", 600),
          "revisions_json": _s("JSON list of {role: research|quant, what: the specific fix} when revising", 1500)}, ("case_id", "verdict", "findings"), submit_review),
    Tool("request_artifact", "action", "You need another worker's product to go on: name the role (research or quant) and exactly what you need; a task is queued and yours "
         "parks until it is done, then resumes. Use it rather than guessing a number or evidence.",
         {"case_id": _i("the case", 1, 10 ** 9), "role": _s("who", enum=["research", "quant"]), "what": _s("exactly what is needed", 500),
          "promise_json": _s("what that task must produce, as JSON, for example {\"evidence\": 2} or {\"calc\": 1}", 200)}, ("case_id", "role", "what"), request_artifact),
    Tool("plan_mission", "journal", "The coordinator's plan for a mission: a JSON list of steps [{key, role (research|quant), goal, promise {evidence|calc|scenario|experiment: n}, "
         "depends_on [keys]}]. The review and the final answer are added by the system after them. Competing explanations, the baseline and what would change the view belong in the goals.",
         {"case_id": _i("the case", 1, 10 ** 9), "steps_json": _s("the steps as a JSON list", 4000), "approach": _s("the approach in two sentences", 500)},
         ("case_id", "steps_json"), plan_mission),
    Tool("submit_answer", "journal", "The final answer for the investor, in plain words he can act on: what the evidence and calculations show with their ids, assumptions, what ran, "
         "what could invalidate it, and what you will watch next. Only numbers that the case's artifacts hold.",
         {"case_id": _i("the case", 1, 10 ** 9), "answer": _s("the answer", 3500), "limitations": _s("what could invalidate the conclusion", 800),
          "monitor_next": _s("what will be monitored next and the trigger for looking again", 600),
          "triggers_json": _s("the monitors the system will actually check, as a JSON list: {kind: price_below|price_above (symbol, value), move_pct (symbol, pct), "
                              "new_document (symbol), review_on (date YYYY-MM-DD)}. A monitoring sentence with no trigger here is not a monitor", 800),
          "change": _s("on a review or an update: did the conclusion change", enum=["first", "changed", "unchanged"])},
         ("case_id", "answer", "limitations", "monitor_next"), submit_answer),
    Tool("amend_investigation", "action", "He changed an instruction in conversation (also look at X, use a different amount, drop a source): record it as the next "
         "numbered version of that investigation. It persists and the workers replan only what changes. Set scope_change when it changes the question or adds a "
         "different kind of work, and financial_policy when it touches an amount, rule or limit of his money: those wait for his yes again.",
         {"case_id": _i("the investigation", 1, 10 ** 9), "instruction": _s("the new instruction in his words", 900),
          "scope_change": {"type": "boolean", "description": "changes the question or adds a different kind of work"},
          "financial_policy": {"type": "boolean", "description": "touches an amount, rule or limit of his money"}}, ("case_id", "instruction"), amend_investigation),
    Tool("decide_plan", "action", "His yes or no to a plan that waits for approval. Use it only when his message in this turn says so; the system checks his words.",
         {"case_id": _i("the investigation", 1, 10 ** 9), "decision": _s("his decision", enum=["approve", "decline"])}, ("case_id", "decision"), decide_plan),
    Tool("make_proposal", "journal", "A buy, add, hold, reduce, sell, diversify or wait recommendation for the investor, with the evidence and the alternatives. You choose the "
         "direction and give the reasons; the system computes every number from his record (price and date, cash, size, charges, weights, tax from the lots) and lists what is "
         "missing. HOLD, WAIT and DIVERSIFY need a concrete condition for looking again. It is advice, never an order. To change an open proposal pass its proposal_id.",
         {"action": _s("the decision", enum=["BUY", "ADD", "HOLD", "REDUCE", "SELL", "DIVERSIFY", "WAIT"]), "symbol": _s("the company's symbol", 20),
          "reason": _s("the evidence and reason in plain words", 1200), "alternatives": _s("what else was considered: waiting, holding, doing less, and why not", 800),
          "review_condition": _s("for HOLD, WAIT, DIVERSIFY: the concrete condition (a price, date, document or cash) that reopens it", 300),
          "qty": _n("shares, for BUY/ADD/REDUCE", 1, 10 ** 7), "amount_rupees": _n("an amount instead of shares", 1, 10 ** 9),
          "full_exit": {"type": "boolean", "description": "SELL the whole holding"}, "assumptions": _s("assumptions made", 500),
          "evidence_ids_json": _s("JSON list of the case's evidence ids it rests on", 200), "case_id": _i("the investigation", 1, 10 ** 9),
          "proposal_id": _i("amend this open proposal", 1, 10 ** 9)}, ("action", "reason", "alternatives"), make_proposal),
    Tool("proposals", "read", "The recommendations on record (buy, add, hold, reduce, sell, diversify, wait): status, review, the snapshot and strategy version they used, "
         "what is missing. With proposal_id: all of one, with its log.", {"proposal_id": _i("one proposal", 1, 10 ** 9), "status": _s("filter", enum=["proposed", "accepted",
         "rejected", "withdrawn", "executed", "partly_executed", "superseded"]), "case_id": _i("one investigation", 1, 10 ** 9)}, (), proposals_tool),
    Tool("decide_proposal", "action", "Discuss a proposal with him, or record his accept, reject or withdraw (his own words in this message are required for those). "
         "Accepting places no order: he enters any trade himself.",
         {"proposal_id": _i("the proposal", 1, 10 ** 9), "decision": _s("what", enum=["discuss", "accept", "reject", "withdraw"]), "note": _s("his comment, if discussing", 400)},
         ("proposal_id", "decision"), decide_proposal),
    Tool("policy_scenarios", "journal", "A HYPOTHETICAL SCENARIO study of how to put a waiting sum into shares: all-in now, his current equal monthly tranches, phased buying "
         "under explicit rules (a reserve bought on a fall) and cash held until a fall, across a sharp fall, a prolonged decline, a fall and recovery, and no crash. You state "
         "the assumptions (the sum, the size of the fall, the horizon, rates); they are shown with the results and nothing is a forecast. Kept as a reproducible calculation.",
         {"case_id": _i("the case", 1, 10 ** 9), "why": _s("what question this answers", 300), "amount": _n("the sum in rupees (an assumption unless it comes from his plan)", 1000, 10 ** 9),
          "horizon_months": _i("months", 6, 60), "fall_pct": _n("size of the sharp fall, percent", 3, 60), "fall_months": _i("months the sharp fall takes", 1, 6),
          "decline_pct": _n("size of the prolonged decline, percent", 5, 60), "decline_months": _i("months the decline takes", 6, 36),
          "recover_months": _i("months to recover after the fall", 3, 36), "drift_pa": _n("yearly drift of the base path, as a fraction", -0.1, 0.3),
          "vol_pa": _n("yearly noise around each path, as a fraction", 0.0, 0.5), "cash_rate_pa": _n("what waiting cash earns, yearly fraction", 0.0, 0.15),
          "staged_months": _i("months of his current staged approach", 2, 24), "dip_trigger": _n("fall from the peak that releases the reserve, as a fraction", 0.02, 0.4),
          "wait_trigger": _n("fall from the start at which held cash goes in, as a fraction", 0.02, 0.5),
          "cost_bps": _n("charge on every trade, in basis points (50 = 0.5 percent)", 0, 500)}, ("case_id", "why"), policy_scenarios),
    Tool("exposure_shock", "journal", "What a stated equity fall (for example 10, 20 and 35 percent) would cost the portfolio as it stands, holding by holding, using each "
         "holding beta (default 1). Trusted code on the current snapshot, reproducible by the reviewer; the falls and betas are your stated assumptions. Use it for the "
         "arithmetic of a fall instead of writing code.", {"case_id": _i("the case", 1, 10 ** 9), "falls_json": _s("JSON list of index falls in percent, e.g. [10, 20, 35]", 60),
                                                           "betas_json": _s("JSON object {symbol: beta} for holdings whose beta you know", 400), "default_beta": _n("beta for the others", 0.0, 3.0),
                                                           "why": _s("what question this answers", 200)}, ("case_id", "falls_json"), exposure_shock_tool),
    Tool("ipo_policy_study", "journal", "How selling at listing, holding 5, 20 or 60 sessions, selling half, or a listing-day-gain rule would have done for large IPO listings since 2016 "
         "(development 2016-2019, validation 2020-2021, baseline: sell at the listing close; under 20 listings: no conclusion). History of other companies, not a forecast of this one. "
         "Kept as a reproducible calculation.", {"case_id": _i("the case", 1, 10 ** 9), "qty": _i("shares allotted, if known", 1, 10 ** 7), "issue": _n("issue price, if known", 1, 10 ** 6)},
         ("case_id",), ipo_policy_study),
    Tool("start_investigation", "action", "Start an investigation for something that needs research and judgement (a headline risk, a strategy, an IPO decision): "
         "a coordinator plans it, research and quant workers do it, an independent reviewer checks it; it runs in the background and reports back here. State his "
         "goal in his own words. Once per question.", {"goal": _s("his goal in his words", 900)}, ("goal",), start_investigation),
    Tool("open_workspace", "journal", "A scratch case for a calculation or scenario he asked for in conversation (policy_scenarios, ipo_policy_study and case_calculate need a "
         "case_id).", {"topic": _s("what it is for", 200)}, ("topic",), open_workspace),
    Tool("work_status", "read", "What is being worked on (each investigation's state, owner, current action, blocker, next trigger, answer if finished) and what waits "
         "for him.", {}, (), work_status),
    Tool("remember_fact", "journal", "Keep what he told you so it survives restarts: kind goal, answer, hypothesis or note, in his words. It never changes a target or limit.",
         {"kind": _s("kind", enum=["goal", "answer", "hypothesis", "note"]), "text": _s("what to keep", 500)}, ("kind", "text"), remember_fact),
    Tool("propose_software_change", "journal", "A tool is missing or something is broken: keep a reproducible issue (and a patch as text, if you have one) for the development "
         "workflow. You cannot change the application; this only records the proposal.",
         {"kind": _s("what it is", enum=["missing_tool", "bug", "data_connector", "improvement"]), "title": _s("short title", 200), "evidence": _s("what you saw", 1500),
          "repro": _s("steps to reproduce", 1500), "proposed_patch": _s("a patch or a sketch as text", 6000)}, ("kind", "title", "evidence"), propose_software_change),
    Tool("resolve_task", "action", "A task held at the agents' hop limit: release it (it runs once; what it hands on is held again) or dismiss it, with a reason.",
         {"task_id": _i("the held task", 1, 10 ** 9), "resolution": _s("what to do", enum=["release", "dismiss"]), "reason": _s("why", 300)},
         ("task_id", "resolution", "reason"), resolve_task),
    Tool("change_preference", "action", "ONLY when the investor himself asks to change a preference: put the exact change to him for his yes "
         "(targets as {bucket: weight} for every bucket that changes, the stock list add/remove a symbol, the monthly API cap in rupees). "
         "Never on your own judgement; nothing changes until he says yes.",
         {"kind": {"type": "string", "enum": ["targets", "stock_list", "api_cap"]}, "key": _s("targets: 'weights'; stock_list: add or remove; api_cap: monthly", 20),
          "value": _s("targets: JSON of the new weights; stock_list: the symbol; api_cap: rupees", 300),
          "why": _s("what he asked, in his words", 300)}, ("kind", "key", "value", "why"), change_preference),
    Tool("recall", "read", "WORKING MEMORY on a subject: what the system concluded before and why (an older view is marked), what evidence goes against it, which checked calculations "
         "can be re-run on today's record instead of written again, what changed since, what is still open. Look here before you start work on a company, a sector or a question that "
         "may have been looked at; say in your answer whether the earlier conclusion still holds.", {"about": _s("the company, sector, theme or the question itself (default: this task)", 300)}, (), recall_tool),
    Tool("waiting", "read", "What waits for his yes about limits, theme baskets and the opportunity pot, each with its Q#. Put one to him in plain words WITH its Q#, then call "
         "answer_question when his next message says yes or no.", {}, (), waiting_tool),
    Tool("answer_question", "action", "His yes or no to a limit, theme basket or opportunity-pot question that waits (the same act as the Needs-from-you button). Only his own clear "
         "yes or no in this message counts, and only for a question whose Q# you showed him in the last few messages.",
         {"q_id": _i("the question number (the digits of its Q#)", 1, 10 ** 9), "answer": _s("his answer", enum=["yes", "no"])}, ("q_id", "answer"), answer_question),
    Tool("rules", "read", "The house rules he has made (what every agent must do from now on) and those waiting for his yes.", {}, (), rules_tool),
    Tool("envelope", "read", "His monthly envelope for shares: the sum set aside, what the months so far have made available, what he has bought, what is available now, and whether the "
         "dip tranche is triggered.", {}, (), envelope_tool),
    Tool("scorecard", "read", "How the system's recommendations turned out: claims stated and scored at 5, 20 and 60 sessions, by kind of decision and market state, with n and a "
         "skeptical rate (a count only under 20).", {}, (), scorecard_tool),
    Tool("add_rule", "action", "He tells the system how to work from now on (for example 'no new tech until I say', 'always include a 0.5% charge in cost tests'): keep it as a house rule in "
         "his words. Not about money: it takes effect at once and he can undo it. About an amount or a limit (a max position, the monthly envelope, a dip tranche): it waits for his yes.",
         {"kind": _s("which kind", enum=["sector_exclusion", "max_position", "monthly_envelope", "dip_tranche", "method", "note"]), "text": _s("the rule in his words", 400),
          "machine_json": _s("sector_exclusion: {\"terms\": [\"tech\", \"software\"]}; max_position: {\"max_weight_pct\": 8}; monthly_envelope: {\"amount_rupees\": 50000, \"until\": \"2027-01-31\", "
                             "\"carry_over\": true}; dip_tranche: {\"extra_rupees\": 25000, \"below_high_pct\": 10}; method and note: {}", 400), "name": _s("a short name", 40)},
         ("kind", "text"), add_rule),
    Tool("chart_view", "read", "LOOK at a candlestick chart of a stock or ETF: the picture (candles, volume, 20 and 50 bar averages, the range's high and low) is attached to the result for you to see, "
         "and the facts about the same candles (trend, position against the averages, gaps, candle shapes, volume against its average) come back as numbers. Say what you see and quote the facts. "
         "Daily and weekly always; 15 minute and 1 hour only when Kite is logged in today.",
         {"symbol": _s("the symbol", 20), "timeframe": _s("candle size", enum=["daily", "weekly", "60min", "15min"]), "bars": _i("how many candles", 20, 250)}, ("symbol",), chart_view),
    Tool("watchlist", "read", "The system's watchlist: ideas it likes but waits on, each with the point its own calculation set (a price zone, a fall from the year's high, or a market fall), its "
         "price now, its gap and its status (waiting, near, triggered).", {}, (), watchlist_tool),
    Tool("watch_add", "action", "Put an idea on the watchlist to wait for the right time. kind zone: zone_high (and zone_low) in rupees; fall_from_high: fall_pct from the year's high; market_fall: "
         "fall_pct of the Nifty 500 from its high (to spend cash in tranches). The numbers must come from a stored calculation: name it with calc_id (code checks the number is in its result). "
         "When the price reaches the point the team looks again; nothing is bought by itself.",
         {"symbol": _s("the symbol (none for market_fall)", 20), "kind": _s("which point", enum=["zone", "fall_from_high", "market_fall"]), "reason": _s("why it is worth waiting for", 500),
          "zone_low": _n("the bottom of the zone, rupees", 0.01, 10 ** 7), "zone_high": _n("the top of the zone, rupees: the point that triggers it", 0.01, 10 ** 7),
          "fall_pct": _n("percent fall that triggers it", 2, 60), "calc_id": _i("the calculation the numbers come from", 1, 10 ** 9), "case_id": _i("the investigation", 1, 10 ** 9)},
         ("kind", "reason"), watch_add),
    Tool("watch_remove", "action", "Take an idea off the watchlist when its reason is gone (by id or symbol), saying why.",
         {"watch": _s("the watch id or the symbol", 20), "why": _s("why it comes off", 300)}, ("watch",), watch_remove),
    Tool("paper_book", "read", "The paper portfolio the system runs by itself (a copy of his portfolio without FDs): holdings with weights and gains, cash, the rails, "
         "holdings over a rail, open orders, recent decisions, its record (decisions scored later) and the gate to his real money.", {}, (), paper_book_tool),
    Tool("paper_decide", "action", "A decision for the PAPER portfolio (paper missions only): BUY, ADD, REDUCE, SELL, HOLD or WAIT with the evidence, the alternatives and, for HOLD and WAIT, "
         "the condition for looking again. You choose the direction; code sizes it against the cash and the rails and tells you the numbers. It is executed on paper at the close "
         "only if the independent review approves the mission.",
         {"action": _s("the decision", enum=["BUY", "ADD", "REDUCE", "SELL", "HOLD", "WAIT"]), "symbol": _s("the company or ETF symbol (none for WAIT in cash)", 20),
          "reason": _s("the evidence and reason in plain words", 1200), "alternatives": _s("what else was considered and why not", 800),
          "amount_rupees": _n("for BUY/ADD: rupees to put in", 1, 10 ** 9), "target_weight_pct": _n("for BUY/ADD: the weight to reach instead of an amount", 0.1, 35),
          "fraction": _n("for REDUCE: the share of the holding to sell", 0.01, 1), "review_condition": _s("for HOLD and WAIT: what reopens it", 300),
          "his_view": _s("if he asked about this: what he said and whether this follows or goes against it, and why", 400), "case_id": _i("the mission's investigation", 1, 10 ** 9)},
         ("action", "reason", "alternatives"), paper_decide),
    Tool("paper_ask", "action", "He asks the paper portfolio to look into something (for example 'is there an AI bubble, should it invest in AI names and how much'). It is one input: "
         "the paper team decides, and may go against him with reasons. Use only when his message asks for the paper portfolio.",
         {"text": _s("what he asked, in his words", 1000)}, ("text",), paper_ask),
    Tool("files", "read", "The files he has dropped and what was read from each: a PDF's pages and characters, a spreadsheet's sheets, rows and figures, and the companies each was "
         "linked to. Start here when he mentions a file, a sheet or a PDF he gave you.", {"about": _s("part of a file name", 60)}, (), files_tool),
    Tool("read_file", "read", "What a dropped file SAYS: a PDF page by page (page=N, or find=a word to see where it appears), a spreadsheet's rows (find=a row label such as 'Net Sales'). "
         "Quote its numbers from this result; say if it holds nothing readable.", {"name": _s("part of the file's name", 80), "page": _i("a PDF page", 1, 500), "find": _s("a word or row label to look for", 60)},
         ("name",), read_file),
    Tool("file_figures", "read", "Figures read from his dropped spreadsheets for one company (a Tijori or Screener export): metric, period, value. Narrow with metric and period words.",
         {"symbol": SYMBOL, "metric": _s("part of a metric name, e.g. net sales", 60), "period": _s("part of a period, e.g. Mar 2026", 20)}, ("symbol",), file_figures),
    Tool("read_document", "read", "A knowledge-graph document (a filing, a result, an article) read IN FULL a part at a time (part=N of 6,000 characters) or by word (find=): use it when the reader's "
         "summary is not enough. Take the doc_id from graph_timeline, or give the symbol and words of the title.",
         {"doc_id": _s("the document's id from graph_timeline", 80), "symbol": SYMBOL, "title_words": _s("words of the title", 80), "part": _i("which part", 1, 400), "find": _s("a word to look for", 60)},
         (), read_document),
    Tool("undo_rule", "action", "He asks to undo a house rule (by its id or name); the version it replaced comes back. Only when his message says so.",
         {"rule": _s("the rule's id or name", 60)}, ("rule",), undo_rule),
    Tool("decide_rule", "action", "His yes or no to a house rule about money that waits for it. Use it only when his message in this turn says so; the system checks his words.",
         {"rule_id": _i("the rule", 1, 10 ** 9), "decision": _s("his decision", enum=["approve", "decline"])}, ("rule_id", "decision"), decide_rule),
]}
from pflab.hq import tools_s79 as _t79  # noqa: E402  (S79: new tools live one module per item)
TOOLS.update({t.name: t for t in _t79.collect()})
TOOLS["record_suggestion"].params["rested_on"]["items"]["enum"] = [n for n, t in TOOLS.items() if t.kind == "read"]


MAX_STRICT = 20
MAX_OPTIONAL = 24                                  # optional parameters across the strict tools of one request


WORKER_ONLY = ("reproduce_calc", "submit_review", "request_artifact", "plan_mission", "submit_answer", "start_investigation", "open_workspace", "work_status",
               "remember_fact", "amend_investigation", "decide_plan", "make_proposal", "proposals", "decide_proposal",
               "add_rule", "undo_rule", "decide_rule", "answer_question", "paper_decide", "paper_ask", "watch_add", "watch_remove", "propose_allocation")      # S68: the workers' tools; the brain's list is unchanged


def definitions(names=None) -> List[dict]:
    """The API's tool list, in a fixed order (a changed order would break the prompt cache). `names`: a worker's own subset; the brain's list
    (no names) leaves the workers' tools out."""
    out, strict, optional = [], 0, 0
    for t in TOOLS.values():
        if (names is None and t.name in WORKER_ONLY) or (names is not None and t.name not in names):
            continue
        opt = len(t.params) - len(t.required)
        # S64: tools after the 20th are checked by `validate` only. S68: the API also refuses a request whose strict tools carry too many OPTIONAL
        # parameters in all (found live: 33 -> "grammar too large"), so a strict tool that would pass MAX_OPTIONAL is sent non-strict (checked here)
        on = names is None and bool(t.required) and strict < MAX_STRICT and optional + opt <= MAX_OPTIONAL      # a worker's list is never strict (the API refused a compiled grammar of 37 tools); `validate` checks every input here anyway
        strict += on
        optional += opt if on else 0
        out.append(t.definition(on))
    return out


def _plain(x):
    """JSON a model can read: NaN and infinities (pandas' missing values) become null."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    return x


def _log(ctx: Ctx, turn: int, tool: str, kind: str, args: Any, status: str, result: str, ms: int) -> None:
    from pflab.pm.store import next_id
    con = ctx.con
    n = ctx.call_ref or next_id(con, "hq_tool_calls", "call_no")             # S79: the id reserved before the tool ran, when it was
    con.execute("INSERT INTO hq_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                [n, ctx.pass_id, ctx.now, turn, tool, kind, json.dumps(args, default=str)[:4000], status, result[:RESULT_CHARS + 200], ms])


TOOL_ABILITY = {"chart_view": "charts", "web_search": "web", "fetch_cited": "web", "case_calculate": "calculations", "register_experiment": "calculations"}
TASK_CAPS = {"case_calculate": 4, "web_search": 4, "fetch_cited": 4, "register_experiment": 1, "policy_scenarios": 4, "ipo_policy_study": 2, "chart_view": 6}


def task_cap_reached(ctx: "Ctx", tool: str) -> Optional[str]:
    """A worker task may make only so many of the costly calls in all (across its resumed runs). The message tells it what to do instead."""
    n = TASK_CAPS.get(tool)
    if n is None or not ctx.task_id:
        return None
    if tool == "case_calculate":                              # two calculations that did not run are enough: more writing would only cost
        bad = ctx.con.execute("SELECT count(*) FROM hq_artifacts WHERE task_id=? AND kind='calc' AND coalesce(detail, '') <> 'checked'", [ctx.task_id]).fetchone()[0]
        if bad >= 2:
            return ("two of this task's calculations did not run. Do not write more code for this: use exposure_shock or policy_scenarios for a fall, or report what "
                    "you could not measure and why")
    from pflab.pm.store import next_id  # noqa: F401
    used = ctx.con.execute("SELECT count(*) FROM hq_tool_calls c JOIN hq_passes p ON p.pass_id = c.pass_id WHERE p.trigger=? AND c.tool=? AND c.status IN ('ran','error')",
                           [f"task:{ctx.task_id}", tool]).fetchone()[0]
    if used >= n:
        return (f"this task has already used its {n} {tool} calls: stop calling it; write your report with what you have, name what is still missing, "
                "or ask another worker with request_artifact")
    return None


def run(ctx: Ctx, name: str, args: Any, turn: int = 1) -> Tuple[str, bool]:
    """Run one tool call: (result text for the model, is_error)."""
    from pflab.hq import egress, redact
    tool = TOOLS.get(name)
    t0 = time.monotonic()
    if tool is None:
        _log(ctx, turn, name, "?", args, "refused", "unknown tool", 0)
        return f"unknown tool {name!r}", True
    if (ctx.allowed is not None and name not in ctx.allowed) or (ctx.allowed is None and name in WORKER_ONLY and not ctx.task_id):
        _log(ctx, turn, name, tool.kind, args, "refused", "not a tool of this role", 0)
        return f"{name} is not a tool of this role", True
    bad = validate(tool, args)
    if bad:
        _log(ctx, turn, name, tool.kind, args, "refused", bad, 0)
        return f"input refused: {bad}", True
    ab = TOOL_ABILITY.get(name)
    if ab:                                                     # S78: an ability he switched off in Settings is not available to any agent
        try:
            from pflab.app import settings as _st
            on = _st.ability(ab, current=getattr(ctx.rt, "settings", None))
        except Exception:
            on = True
        if not on:
            _log(ctx, turn, name, tool.kind, args, "refused", f"switched off in Settings: {ab}", 0)
            return f"{name} is switched off in Settings (ability: {ab}); work without it and say what you could not check", True
    if tool.kind == "read":                                    # S78: a read tool whose self-check failed twice in a row is not used until it passes again
        try:
            from pflab.hq import selfcheck
            why = selfcheck.quarantined(ctx.con, name)
        except Exception:
            why = None
        if why:
            _log(ctx, turn, name, tool.kind, args, "refused", why, 0)
            return why, True
    over = task_cap_reached(ctx, name)
    if over:                                                   # S68: a worker's task has a bounded number of the dear calls (it was Rs 450 for one mission)
        _log(ctx, turn, name, tool.kind, args, "refused", over, 0)
        return over, True
    try:
        from pflab.pm.store import next_id as _next_id
        ctx.call_ref = _next_id(ctx.con, "hq_tool_calls", "call_no")        # S79: reserved now, so the tool can print its own call id and the log uses the same one
    except Exception:
        ctx.call_ref = None
    try:
        res = tool.fn(ctx, args)
        status = ("shadow" if ctx.shadow else "held" if res.get("carried_out") is False else "ran") \
            if tool.kind == "action" else "ran"
        err = False
    except Exception as e:                                   # the model sees the failure and may try another way
        res, status, err = {"error": f"{type(e).__name__}: {str(e)[:400]}"}, "error", True
    text = json.dumps(_plain(res), default=str, ensure_ascii=False)
    if len(text) > RESULT_CHARS:
        text = text[:RESULT_CHARS] + f' ... (cut at {RESULT_CHARS} characters; ask for one stock or one part)'
    text, _ = redact.redact(text, ctx.gate, lines=False)
    try:
        egress.check(text, ctx.gate, skip=("address",))
    except egress.EgressBlocked as e:
        text, status, err = f"withheld: the result carried identity or banking details ({e})", "withheld", True
    ctx.results[name] = text
    ctx.source += "\n" + text
    _log(ctx, turn, name, tool.kind, args, status, text, int((time.monotonic() - t0) * 1000))
    ctx.call_ref = None
    return text, err
