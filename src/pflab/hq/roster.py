"""The agents (S59, PLAN A16): one registry. Each agent is an existing module wired in by import; `run(rt, task)`
returns a board Reply. `rt` is the dashboard's runtime or, with the window closed, `hq.desk.Desk`.

Models: code for every number; the local model for private text; Haiku reads; Sonnet works; Opus is the brain and
deep research. Paid calls go through the doorbell (`agents.analyst`) or HQ's road (`hq.llm`), both priced first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from pflab.hq.board import Reply


@dataclass(frozen=True)
class Agent:
    name: str
    title: str
    model: str
    does: str
    reads: str
    writes: str
    run: Callable


def _status(out: dict) -> str:
    return {"needs_approval": "needs_approval", "failed": "failed", "waiting": "waiting"}.get(out.get("status", "done"), "done")


def _chat(mode: str) -> Callable:
    """The AI centre's own answer for a mode (S54b/S56): ask (escalation chain), web, deep, calc."""
    def run(rt, t: dict) -> Reply:
        from pflab.app import chat
        out = chat.answer(rt, rt.cursor(), t["text"], mode, approved=bool(t["body"].get("approved")))
        return Reply(out["text"], out.get("route", []), {"meta": out.get("meta", ""), "report": out.get("report")},
                     float(out.get("cost") or 0.0), _status(out))
    return run


def _research(rt, t: dict) -> Reply:
    """A bare symbol: what changed lately and the latest brief; a question: deep research (the doorbell)."""
    words = t["text"].split()
    if len(words) == 1 and re.fullmatch(r"[A-Za-z0-9&-]{2,20}", words[0]):
        from pflab.agents import researcher as rs
        return Reply(rs.show(rt.cursor(), words[0].upper(), rt.clock().date()), ["researcher (local)"])
    if not t["text"].strip():
        return Reply("Write the research question (public information only), or a symbol.", status="failed")
    return _chat("deep")(rt, t)


def _analysis(rt, t: dict) -> Reply:
    """A file the investor provided: a screenshot's text summarised (local), an export or PDF described from what was read
    into the graph; its companies handed to the research agent when he asks for research."""
    from pflab.app import inbox as ib
    from pflab.hq.reception import item_ref
    con = rt.cursor()
    iid = item_ref(t["text"]) or (con.execute("SELECT max(item_id) FROM inbox_items WHERE status <> 'removed'").fetchone()[0])
    if not iid:
        return Reply("No file in the inbox yet: drop one in the drop folder or on the Inbox screen.", status="failed")
    it = ib._item(rt, iid)
    if it.get("text"):
        res = ib.summarise(rt, iid)
        return Reply(f"{it['name']}: {res['summary']}", ["inbox item", "local model, checked against the file's text"],
                     {"item": iid})
    r = con.execute("SELECT shape, isins_json, n_rows, n_cols, columns_json FROM datasets WHERE file = ? ORDER BY dataset_id",
                    [it["path"]]).fetchall()
    if not r:
        return Reply(f"{it['name']} ({ib.KIND_LABEL.get(it['kind'], it['kind'])}): {it['status']}. Nothing read from it yet.",
                     ["inbox item"], {"item": iid})
    import json
    isins = sorted({i for row in r for i in json.loads(row[1] or "[]")})
    syms = [s for (s,) in con.execute(f"SELECT symbol FROM instruments WHERE isin IN ({','.join('?' * len(isins))}) "
                                      "AND symbol IS NOT NULL", isins).fetchall()] if isins else []
    lines = [f"{it['name']}: {len(r)} sheet(s) read on this PC into the knowledge graph"]
    for shape, _i, nr, nc, cols in r[:6]:
        lines.append(f"- {shape}: {nr} rows x {nc} columns ({', '.join(json.loads(cols or '[]')[:8])})")
    if syms:
        lines.append("Companies: " + ", ".join(syms[:12]))
    then = []
    if syms and re.search(r"\b(research|analy[sz]e|what does it (say|show)|deep)\b", t["text"], re.I):
        then = [("research", f"What do the latest filings and the new {it['name']} export say about {s}?") for s in syms[:3]]
        lines.append("Handed to the research agent: " + ", ".join(syms[:3]) + ".")
    return Reply("\n".join(lines), ["inbox item", "datasets read on this PC"], {"item": iid}, then=then)


def _sim(rt, t: dict) -> Reply:
    """Monte Carlo of the current and target mixes with the dated stress episodes; 'forecast' shows the kept forecasts and price ranges."""
    text = t["text"].lower()
    if re.search(r"forecast|times ?fm", text):
        rows = rt.cursor().execute(
            "SELECT use, subject, as_of, target, q10, q50, q90, model FROM forecasts WHERE as_of = (SELECT max(as_of) "
            "FROM forecasts) ORDER BY use, subject LIMIT 30").fetchall()
        if not rows:
            return Reply("No forecasts kept yet (the forecast job runs nightly).", ["forecasts (S52)"])
        return Reply("Forecasts of " + str(rows[0][2]) + " (q10 / q50 / q90; the model serving each use is on the "
                     "scoreboard):\n" + "\n".join(f"{u} {s} to {tg}: {a:,.4g} / {b:,.4g} / {c:,.4g} ({m})"
                                                  for u, s, _a, tg, a, b, c, m in rows), ["forecasts (S64, calibrated statistics and baselines)"])
    from pflab.app import sims
    paths = 100_000 if re.search(r"100[, ]?000|marathon", text) else 10_000
    years = int(m.group(1)) if (m := re.search(r"\b([1-5])\s*(?:years?|yrs?)\b", text)) else 5
    out = sims.run(rt, paths=paths, years=years)
    lines = [f"Simulation, {paths:,} paths, {years} years ({out['history']}):"]
    for name, mx in out["mixes"].items():
        f, fan = mx["fall"], mx["fan"]["years"]
        y = fan.get("1", {})
        lines.append(f"{name}: chance of a 35% fall on any day within {years} years: {f.get('text', 'not run')}"
                     + (f"; one rupee after a year: {y['p5']:.2f} / {y['p50']:.2f} / {y['p95']:.2f} (5th / median / 95th)"
                        if y else ""))
        worst = sorted([e for e in mx["stress"]["episodes"] if e.get("covered")], key=lambda e: e["worst_fall"])[:3]
        if worst:
            lines.append("  worst dated episodes: " + "; ".join(f"{e['name']} {e['worst_fall'] * 100:.0f}%" for e in worst))
    return Reply("\n".join(lines), ["simulation on this PC (app/sims.py)"])


def _quant(rt, t: dict) -> Reply:
    from pflab.agents import quant
    if not t["text"].strip():
        return Reply("Write the idea, e.g. 'how do stocks move after downgrades'.", status="failed")
    return Reply(quant.run(t["text"], rt.data_root), ["quant templates (tested studies; a new claim needs a "
                                                       "pre-registered protocol, CLAUDE.md rule 12)"])


def _memory(rt, t: dict) -> Reply:
    from pflab.agents import memory as mem
    from pflab.hq import keeper
    con, now, text = rt.cursor(), rt.clock(), t["text"].strip()
    m = re.match(r"(?:remember|note that|keep in mind)\s*[:,-]?\s*(.+)", text, re.I | re.S)
    d = re.match(r"(?:i|we)\s+(?:have\s+)?(?:decided|chose)\s*(?:to|that|on)?\s*(.+)", text, re.I | re.S)
    if m or d:
        body = (m or d).group(1).strip()
        sub = re.match(r"([A-Z][A-Z0-9&-]{1,19})\s*:\s*(.+)", body, re.S)
        mid = mem.remember(con, "decision" if d else "note", sub.group(2) if sub else body,
                           subject=sub.group(1) if sub else None, source=f"hq ({t['from']})", now=now)
        return Reply(f"Kept as {'decision' if d else 'note'} #{mid}.", ["memory"])
    words = re.sub(r"\b(what|did|do|i|we|decided?|about|my|the|a|on|of|journal|decisions?|show|me|list)\b|[?.,]", " ",
                   text, flags=re.I).strip()
    rows = mem.recall(con, words=words, asof=now.date()) if words else []
    head = []
    if not rows:                                              # nothing on those words: the latest decisions instead
        rows = mem.recall(con, kinds=["decision"], asof=now.date())
        head = [f"Nothing kept on '{words}'; your latest decisions:" if words else "Your latest decisions:"]
    lines = head + [r.line() for r in rows[:12]] or ["Nothing kept yet."]
    fu = [f for f in keeper.followups(con, now.date()) if f["since"]][:6]
    if fu:
        lines.append("Since your decisions:")
        lines += [f"- {f['subject']} ({f['at']:%d %b}): {f['since']['change_pct']:+.1f}% to {f['since']['to']}" for f in fu]
    return Reply("\n".join(lines), ["memory", "memory keeper (follow-ups by code)"])


def _cleanup(rt, t: dict) -> Reply:
    from pflab.kg import clean
    rep = clean.run(rt.cursor(), rt.clock())
    return Reply("Knowledge graph cleaned: " + ", ".join(f"{k} {v}" for k, v in rep.items() if not isinstance(v, (list, dict))),
                 ["kg/clean.py (exact matches merged, unsure ones asked)"], {"report": rep})


def _graph(rt, t: dict) -> Reply:
    from datetime import timedelta
    from pflab.kg import graph as g
    con, now = rt.cursor(), rt.clock()
    m = re.search(r"\b([A-Z][A-Z0-9&-]{1,19})\b", t["text"])
    row = con.execute("SELECT isin, symbol FROM instruments WHERE upper(symbol)=? LIMIT 1", [m.group(1).upper()]).fetchone() if m else None
    if not row:
        return Reply("Name a company by its NSE symbol, e.g. /graph TCS.", status="failed")
    df = g.timeline(con, f"company:{row[0]}", now - timedelta(days=30), kinds=("filing", "result", "article", "reading",
                                                                           "analyst_note", "dataset"), limit=15)
    if df.empty:
        return Reply(f"{row[1]}: nothing in the graph in the last 30 days.", ["knowledge graph"])
    return Reply(f"{row[1]} in the graph, last 30 days:\n" + "\n".join(
        f"{r.published_at:%d %b} {r.kind}: {(r.title or '')[:120]}" for r in df.itertuples()), ["knowledge graph"])


def _messenger(rt, t: dict) -> Reply:
    from pflab.agents import questions as qs
    from pflab.hq import messenger as ms
    con, now, text = rt.cursor(), rt.clock(), t["text"]
    if re.search(r"remind|nudge|ping|forget", text, re.I) or t["body"].get("remind"):
        at = ms.when(text, now)
        if at is None:
            return Reply("When should I remind you? Say e.g. 'remind me to check the results tomorrow at 9'.",
                         status="failed")
        rid = ms.add(con, ms.what(text), at, now, source=t["from"])
        return Reply(f"Reminder #{rid} set for {at:%a %d %b %H:%M}: {ms.what(text)}", ["messenger"])
    lines = ["Reminders: " + ("; ".join(f"#{i} {at:%d %b %H:%M} {tx}" for i, tx, at in ms.upcoming(con)) or "none")]
    oq = qs.open_questions(con)
    lines.append("Open questions: " + ("; ".join(f"#{q} ({a}) {x[:80]}" for q, a, x in oq) or "none"))
    held = con.execute("SELECT count(*) FROM outbox WHERE status='pending'").fetchone()[0]
    lines.append(f"Messages waiting to be sent: {held}")
    return Reply("\n".join(lines), ["messenger"])


def _watcher(rt, t: dict) -> Reply:
    from pflab.hq import watcher
    got = watcher.scan(rt)
    watcher.announce(rt, got)
    return Reply(f"Drop folder {watcher.folder(rt.repo)}: " + ("; ".join(
        f"{g['name']} -> item #{g['item']}" if g.get("item") else f"{g['name']}: {g['skipped']}" for g in got)
        if got else "nothing new."), ["drive watcher"])


WORD_SYSTEM = ("You answer a private investor's question about his own portfolio using ONLY the FACTS given. Copy every "
               "number exactly as it is written in FACTS (never round, convert or compute). Plain English, at most 120 words, "
               "no advice to buy or sell.")


def _num(v) -> str:
    """Rupee-sized numbers in Indian grouping, so the words and the check read the same figures."""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) >= 1000:
        s = f"{abs(v):,.0f}".replace(",", "")
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        return ("-" if v < 0 else "") + ",".join(([head] if head else []) + parts + [tail])
    return f"{v:.4g}" if isinstance(v, float) else str(v)


def word_facts(rt, question: str, facts: dict) -> Tuple[str, float]:
    """S59: Haiku words the facts when the local model's draft fails the guard (The investor 2026-10-24: his portfolio may go
    to the API; the egress list still stops identity and banking details). Every sentence with a number not in the
    facts is removed. Raises when blocked, over a limit, or with nothing left."""
    from pflab.agents import analyst as an
    from pflab.hq import governor as gv, service
    from pflab.llm import gateway
    text = "FACTS:\n" + "\n".join(f"{k} = {_num(v)}" for k, v in facts.items()) + f"\n\nQUESTION: {question}"
    con = rt.cursor()
    override, role = gateway.prefer(con, gv.HAIKU)
    s = gateway.call(con, role, WORD_SYSTEM, [{"role": "user", "content": text}], max_tokens=gv.LIMITS["wording"].max_out, thinking="low", model=override, agent="wording", purpose="portfolio wording",
                     now=rt.clock(), mode=rt.settings.get("brain", "economy"), private_text=text, gate=service.gate(rt), topic="portfolio", question=question, client=service.client(rt))
    out, _ = an.only_sourced_numbers(s["text"], an.Request(text, "portfolio"))
    if not out.strip():
        raise ValueError("nothing left after the number check")
    return out, s["cost_rupees"]


def _portfolio(rt, t: dict) -> Reply:
    from pflab.agents import centre
    q = t["text"] or "Summarise my net worth."
    a = centre.ask(rt.cursor(), q, rt.clock().date(), tools_override=["networth"])
    if a.verified:
        return Reply(a.text, ["portfolio today (ledger + Kite)", "local model, checked"])
    try:
        text, cost = word_facts(rt, q, a.facts)
        return Reply(text, ["portfolio today (ledger + Kite)", "local draft failed the check",
                            "Haiku worded the facts (numbers checked)"], cost=cost)
    except Exception as e:                                   # the facts themselves are the last word
        return Reply(a.text, ["portfolio today (ledger + Kite)", f"facts (no checked wording: {type(e).__name__})"])


def _brain(rt, t: dict) -> Reply:
    from pflab.hq import service
    res = service.brain_now(rt, question=t["text"] or None)
    return Reply(res["text"], ["brain (Opus with tools; never trades)"], res, res.get("cost", 0.0))


def _fetch(rt, t: dict) -> Reply:
    """S60: read a page the system already cites ('URL question'), Sonnet with web fetch, numbers checked."""
    from pflab.hq import fetch, service
    m = re.match(r"\s*(https?://\S+)\s*(.*)", t["text"], re.S)
    if not m:
        return Reply("Give the cited URL first, then the question.", status="failed")
    out = fetch.run(rt.cursor(), m.group(1), m.group(2).strip() or "What does this document say?", service.client(rt),
                    service.gate(rt), rt.clock(), rt.settings.get("brain", "economy"), text_dir=rt.data_root / "kg" / "text")
    return Reply(out["text"] + f"\n\nSource: {out['url']}", [f"cited page by {out.get('how', 'web fetch')} (Sonnet 5.5, "
                                                             "numbers checked)"],
                 out, out["cost"])


def _learner(rt, t: dict) -> Reply:
    """S62: what the learner read and tested; with words, one search on that topic (read on its next run)."""
    from pflab.learner import run
    text = t["text"].strip()
    if text:
        n = run.search_now(rt, text)
        return Reply(f"{n} new source(s) found on '{text}'; read and tested on the learner's next run.\n\n"
                     + run.status(rt.cursor()), ["learner (OpenAlex, free)"])
    return Reply(run.status(rt.cursor()), ["learner"])


def _security(rt, t: dict) -> Reply:
    from pflab.hq import security
    out = security.egress(rt)
    return Reply(f"Re-checked {out['calls']} request(s) and {out['messages']} message(s): {out['hits']} hit(s).\n"
                 + security.status(rt.cursor()), ["security agent (code)"])


def _receptionist(rt, t: dict) -> Reply:
    from pflab.hq.reception import route
    agent, text = route(t["text"])
    if not agent or agent == "receptionist":
        return Reply("I could not tell which agent should take that; ask it in plain words or use /order AGENT text.",
                     status="failed")
    return Reply(f"Sent to the {ROSTER[agent].title.lower()}.", ["receptionist (fixed rules)"], then=[(agent, text)])


ROSTER: Dict[str, Agent] = {a.name: a for a in [
    Agent("receptionist", "Receptionist", "rules (no model)", "routes what the investor says or drops to the right agent",
          "his words", "the board", _receptionist),
    Agent("ask", "Ask centre", "{answers}; then the agents; then {research} or {web} for company and web questions", "answers questions: local first, then escalates",
          "the ledger, tools, notes", "chats", _chat("auto")),
    Agent("web", "Web search", "{web} + web search", "searches the web for public questions, cited pages only",
          "the web", "a cited note in the graph", _chat("web")),
    Agent("research", "Research analyst", "{research} (the doorbell)", "deep research on a company from public documents",
          "filings, results, news, exports", "a cited note in the graph", _research),
    Agent("analysis", "File analyst", "local model; then research", "reads what the investor provides: files, Tijori exports, PDFs, sheets",
          "the inbox", "the graph, the research agent", _analysis),
    Agent("calc", "Calculation", "reviewed measures first; {workshop} writes the code, {workshop_check} writes it again independently; both must agree", "maths only: measures and new calculations as code",
          "prices, the ledger, datasets", "kept calculations", _chat("calc")),
    Agent("sim", "Simulation", "code (Monte Carlo, calibrated statistics)", "Monte Carlo, stress and crash episodes, forecasts",
          "returns history, the mix", "the simulation cache", _sim),
    Agent("quant", "Quant researcher", "code (tested templates)", "hypotheses as pre-registered studies; tested templates",
          "market data", "study results", _quant),
    Agent("memory", "Memory keeper", "code", "keeps decisions and notes, follows them up, scores the brain",
          "memory, prices", "memory, predictions", _memory),
    Agent("cleanup", "Cleanup", "code", "tidies the knowledge graph: names, copies, current notes", "the graph", "the graph",
          _cleanup),
    Agent("graph", "Knowledge graph", "code", "what the graph holds on a company", "the graph", "nothing", _graph),
    Agent("messenger", "Messenger", "code", "reminders, open questions, what must be sent", "the outbox, questions",
          "Telegram, reminders", _messenger),
    Agent("watcher", "Drive watcher", "code", "files in the drop folder go to the inbox", "the drop folder", "the inbox",
          _watcher),
    Agent("portfolio", "Portfolio", "code; local model words it", "the portfolio today (statements, then Kite)",
          "the ledger, Kite snapshots", "nothing", _portfolio),
    Agent("fetch", "Cited-page reader", "{fetch} + web fetch", "reads a page or filing the system already cites",
          "one cited URL", "a note in the graph", _fetch),
    Agent("brain", "Brain", "{brain} with tools ({brain_rival} as its journal-only rival)", "looks with tools, decides what matters and "
          "what next; asks and tells you, orders research; never trades", "the tools: portfolio, every stock's drift / odds / edge, notes, memory",
          "the journal, predictions, suggestions", _brain),
    Agent("learner", "Learner", "{learner_reading} reads (Haiku 5.5 when its reply does not parse); {learner_proposals} words proposals", "reads papers and blogs for testable "
          "claims, registers and tests them; reads the system's record and proposes changes", "arXiv, OpenAlex, blogs, "
          "drop\\learn, the record", "findings, lessons, proposals", _learner),
    Agent("security", "Security", "code; {review} reviews new code weekly", "re-checks what left the PC, data flows, the "
          "repo's privacy, the tests; never changes code or data", "requests sent, jobs, the repo", "Needs from you",
          _security),
]}


# S68 (2026-10-31, his request): the World shows ROLES, not runners. Several runners do one job (the old single-call research doorbell, web search
# and the cited-page reader are all research; calculation, simulation and the quant templates are all quant work), so a map of 20 runners showed
# most of them idle forever. The runners stay (orders, the board and tests name them); the map draws one node per role and adds up its members.
# `order_to`: where an order typed on the role goes ("investigation" starts one; None: the role takes work only from a mission).
ROLES = [
    {"id": "brain", "title": "Brain", "members": ["brain"], "order_to": "brain"},
    {"id": "assistant", "title": "Assistant", "members": ["ask", "receptionist"], "order_to": "ask",
     "does": "talks with you: answers from the record, runs calculations, reads files and the public record"},
    {"id": "research", "title": "Research", "members": ["research", "web", "fetch"], "order_to": "research",
     "does": "gathers and weighs evidence from filings, results, news and the web; cited pages only"},
    {"id": "quant", "title": "Quant", "members": ["calc", "sim", "quant"], "order_to": "calc",
     "does": "calculations (written twice, run in the sandbox), scenarios, simulations and pre-registered strategy experiments"},
    {"id": "readers", "title": "Readers", "members": ["analysis", "watcher"], "order_to": "analysis",
     "does": "reads every file you drop: materiality, figures, summary"},
    {"id": "learner", "title": "Learner", "members": ["learner"], "order_to": "learner"},
    {"id": "memory", "title": "Memory and graph", "members": ["memory", "graph", "cleanup"], "order_to": "graph",
     "does": "keeps decisions and notes, follows them up, and keeps the knowledge graph tidy"},
    {"id": "portfolio", "title": "Portfolio", "members": ["portfolio"], "order_to": "portfolio"},
    {"id": "messenger", "title": "Messenger", "members": ["messenger"], "order_to": "messenger"},
    {"id": "security", "title": "Security", "members": ["security"], "order_to": "security"},
]


def roles(settings=None) -> list:
    """The roles the map draws, each with its members' titles and models (every runner belongs to exactly one role)."""
    out = []
    for r in ROLES:
        ms = [ROSTER[m] for m in r["members"] if m in ROSTER]
        out.append({**r, "does": r.get("does") or (ms[0].does if ms else ""),
                    "made_of": [{"name": a.name, "title": a.title, "model": model_text(a, settings)} for a in ms]})
    return out


def role_of(name: str) -> Optional[str]:
    return next((r["id"] for r in ROLES if name in r["members"]), None)


def runners() -> Dict[str, Callable]:
    return {n: a.run for n, a in ROSTER.items()}


def model_text(a: Agent, settings=None) -> str:
    """The agent's model words with the slider's current choices filled in."""
    from pflab.hq import models
    try:
        return a.model.format(**models.labels(settings))
    except (KeyError, IndexError):
        return a.model


def listing(settings=None) -> list:
    return [{"name": a.name, "title": a.title, "model": model_text(a, settings), "does": a.does, "reads": a.reads, "writes": a.writes}
            for a in ROSTER.values()]


def title(name: str) -> Tuple[str, str]:
    a = ROSTER.get(name)
    return (a.title, model_text(a)) if a else (name, "")
