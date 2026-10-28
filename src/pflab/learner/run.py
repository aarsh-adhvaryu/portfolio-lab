"""The learner's run (S62, PLAN A22): the `learner` job, nightly, and the investor's orders on the board.

    1 answers   his yes / no to earlier proposals applied (free)
    2 collect   new sources: arXiv, OpenAlex, blog feeds, the drop folder's `learn` sub-folder (free)
    3 screen    abstracts screened (the learner_reading model: local first, Haiku when its reply does not parse)
    4 read      screened sources read in full; claims quoted and mapped to coded tests
    5 test      claims registered (protocol file and hash first), then tested by code; passes go live
    6 record    the system's own record read when due (weekly, or 20 new outcomes): proposals
Limits per run in configs/learner.toml [limits]. It never trades, moves money, or changes targets or money limits.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple


def drafts(rt, paid: bool) -> List[Tuple[str, object]]:
    """The reading chain from the slider: local then Haiku (when paid work is allowed), or the one Claude model chosen."""
    from pflab.hq import governor as gv, models, service
    from pflab.learner import claims
    c = models.choice("learner_reading", rt.settings)
    out = []
    if c == "local":
        out.append(("local", claims.local_draft()))
    if paid:
        try:
            m = gv.HAIKU if c == "local" else models.IDS[c]
            out.append((c if c != "local" else "haiku",
                        claims.claude_draft(rt.cursor(), service.client(rt), service.gate(rt), m, rt.clock(),
                                            rt.settings.get("brain", "economy"))))
        except Exception:                                    # no key on this PC: the local model alone
            pass
    return out


def proposal_draft(rt):
    from pflab.hq import llm, models, service

    def draft(system: str, prompt: str, schema: dict) -> dict:
        p = {"model": models.model_id("learner_proposals", rt.settings), "max_tokens": 3000, "system": system,
             "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
             "messages": [{"role": "user", "content": prompt}]}
        g = service.gate(rt)
        return llm.call(rt.cursor(), "worker", p, service.client(rt), now=rt.clock(), mode=rt.settings.get("brain", "economy"),
                        private_text=prompt, gate=g, doc_kinds=("portfolio",), topic="learner",
                        question="the learner's proposals").json()
    return draft


def folders(rt) -> Tuple[Path, Path]:
    base = Path(rt.data_root) / "learner"
    return base / "text", base / "protocols"


def cycle(rt, collect: bool = True, get=None) -> dict:
    from pflab.hq import service
    from pflab.learner import claims, record, sources
    con, now = rt.cursor(), rt.clock()
    lim = sources.config().get("limits", {})
    text_dir, proto_dir = folders(rt)
    out: dict = {"answers": record.answers(con, now)}
    try:                                     # S65: a fresh install starts with the past tests counted (idempotent; counter.CARRIED)
        from pflab.learner import counter
        out["seeded"] = counter.seed(con, now)
    except Exception as e:
        out["seeded"] = f"not run: {type(e).__name__}"
    paid = service.paid_allowed(rt)
    if collect:
        out["collected"] = sources.collect(con, now, rt.repo, text_dir, **({"get": get} if get else {}))
    ds = drafts(rt, paid)
    out["screened"] = claims.screen(con, ds, int(lim.get("screen_per_run", 25)), now) if ds else 0
    read = []
    for (sid,) in con.execute("SELECT src_id FROM learn_sources WHERE status='screened' ORDER BY (origin='drop') DESC, "
                              "src_id LIMIT ?", [int(lim.get("read_per_run", 6))]).fetchall():
        try:
            read += claims.read(con, ds, sid, sources.fetch_text(con, sid, text_dir, **({"get": get} if get else {})), now)
        except Exception as e:
            con.execute("UPDATE learn_sources SET status='failed', why=? WHERE src_id=?", [f"{type(e).__name__}: {e}"[:300], sid])
    out["claims"] = len(read)
    for (cid,) in con.execute("SELECT claim_id FROM learn_claims WHERE status='proposed' ORDER BY claim_id").fetchall():
        claims.register(con, cid, proto_dir, now)
    tested = {}
    for (cid,) in con.execute("SELECT claim_id FROM learn_claims WHERE status='registered' ORDER BY claim_id LIMIT ?",
                              [int(lim.get("tests_per_run", 3))]).fetchall():
        try:
            tested[cid] = claims.test(con, cid, rt.data_root, now)
        except Exception as e:                               # kept registered; the reason shown
            tested[cid] = f"not run: {type(e).__name__}: {str(e)[:150]}"
    out["tested"] = tested
    try:                                     # S65: the forward tests (docs/protocols/s65_forward_protocol.md): form, settle, decide
        from pflab.learner import forward
        out["forward"] = forward.cycle(con, rt.data_root, now)
    except Exception as e:
        out["forward"] = f"not run: {type(e).__name__}: {str(e)[:150]}"
    try:                                     # S65: forward test F5, the stress-gauge hedge on paper (docs/protocols/s65_hedge_forward_protocol.md)
        from pflab.quant import stress_hedge
        out["hedge"] = stress_hedge.cycle(con, rt.data_root, now)
    except Exception as e:
        out["hedge"] = f"not run: {type(e).__name__}: {str(e)[:150]}"
    why = record.due(con, now)
    if why:
        out["record"] = record.run(con, now, proposal_draft(rt) if paid else None, why)
    return out


def job(ctx) -> dict:
    from pflab.hq import desk
    rt = desk.from_ctx(ctx)
    if rt.settings.get("preset", "full") == "off":
        return {"skipped": True, "why": "preset off"}
    out = cycle(rt)
    return {k: (v if isinstance(v, (int, float, str)) else str(v)[:300]) for k, v in out.items()}


def status(con, limit: int = 8) -> str:
    from pflab.learner import claims, counter, live
    n = dict(con.execute("SELECT status, count(*) FROM learn_sources GROUP BY status").fetchall())
    c = dict(con.execute("SELECT status, count(*) FROM learn_claims GROUP BY status").fetchall())
    lines = ["Sources: " + (", ".join(f"{k} {v}" for k, v in sorted(n.items())) or "none yet"),
             "Claims: " + (", ".join(f"{k} {v}" for k, v in sorted(c.items())) or "none yet")]
    for r in claims.table(con, limit):
        lines.append(f"#{r['id']} [{r['status']}] {r['claim'][:140]}" + (f" -> {r['why'][:160]}" if r["why"] else ""))
    lines.append(counter.line(con))
    try:                                     # S65: forward tests: counts only until the decision month (never a running result)
        from pflab.learner import forward
        lines.append("Forward tests (live data only; decided once at 24 months): " + "; ".join(
            f"{f['id']} {f['settled']}/{f['needs']}" + (" " + ("passed" if f["verdict"]["passed"] else "did not hold") if f["verdict"] else "")
            for f in forward.status(con)))
    except Exception:
        pass
    lines.append(live.brain_text(con))
    pend = con.execute("SELECT prop_id, kind, text FROM learn_proposals WHERE status='to_investor' ORDER BY prop_id").fetchall()
    if pend:
        lines.append("Waiting for your answer: " + "; ".join(f"#{i} ({k}) {t[:100]}" for i, k, t in pend))
    return "\n".join(lines)


def search_now(rt, topic: str, get=None) -> int:
    """The investor's order: one OpenAlex search on his topic, read on the next run."""
    from pflab.learner import sources
    cfg = {"openalex": {**sources.config().get("openalex", {}), "searches": [topic]}}
    return sources.openalex(rt.cursor(), rt.clock(), **({"get": get} if get else {}), cfg=cfg)
