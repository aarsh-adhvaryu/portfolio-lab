"""From reading to a tested claim (S62, PLAN A22; protocol docs/protocols/learner_protocol.md).

    screen     the local model reads a source's title and abstract: does it state a claim about stock returns that
               daily Indian prices, exchange filings or index levels could check? (free)
    read       its full text (kept on this PC) -> at most MAX_CLAIMS claims, each with a verbatim quote that code finds in
               the text (no quote, no claim) and mapped to a coded template with parameters from closed lists, or to
               'none' with the data it would need; the local model first, Haiku when its reply does not parse
    register   before any data is touched: a protocol file (the claim, its quote and source, the template, parameters,
               the decision rule and the code's hash) written once, its hash kept; the same test asked twice is run once
    test       the template runs on the panel; `templates.decide` decides, never a model
    wire       a pass becomes a live finding the brain reads (its cached part and the `findings` tool); a fail is kept as
               tested-and-failed and gets no live feature (CLAUDE.md 12)
Public text only: nothing of the investor's is in a source or a prompt here.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from pflab.learner import counter, templates as tp

MAX_CLAIMS = 3
READ_CHARS = 24_000
MIN_QUOTE = 30

Draft = Callable[[str, str, dict], dict]            # (system, prompt, json schema) -> parsed reply

SCREEN_SYSTEM = ("You screen finance papers and articles for a system that tests claims on Indian stock data (daily "
                 "prices of Nifty 500 stocks since 2010, exchange filings since 2015, index levels). Reply with JSON only.")
SCREEN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["testable", "why"],
                 "properties": {"testable": {"type": "boolean"}, "why": {"type": "string"}}}

READ_SYSTEM = (
    "You read a finance text and list the claims it makes about which stocks earn higher or lower returns, or how prices "
    "move after events or on calendar days. Only claims that an effect exists (some stocks or days earn more or less); "
    "skip claims that an effect is absent. At most 3 claims, the clearest first. For each: the claim in one sentence; a "
    "quote: one sentence copied word for word from the text that states it; and the test that fits it, from this list "
    "only:\n"
    "- cross_section: stocks ranked monthly by a signal; direction 'high' means high values earn more, 'low' means low "
    "values earn more; months 1 or 3 ahead. Signals: " + "; ".join(f"{k} = {v}" for k, v in tp.SIGNALS.items()) + ". "
    "Examples: momentum (past winners keep winning) = momentum_12_1 high; low-volatility stocks earn more = "
    "volatility_12m low; last month's losers rebound = reversal_1m low; stocks near their 52-week high earn more = "
    "high_52w high; lottery-like stocks with big daily jumps earn less = max_day_1m low; illiquid stocks earn more = "
    "illiquidity high.\n"
    "- event_study: prices after a kind of exchange filing; direction up or down; sessions 1, 5 or 20. Kinds: "
    + ", ".join(tp.EVENT_KINDS) + ".\n"
    "- calendar: index returns on some days; direction high or low. Effects: " + ", ".join(tp.EFFECTS) + ".\n"
    "- holder_event: prices after who buys or sells; direction up or down; sessions 1, 5 or 20. Kinds: insider_sast "
    "(insider or SAST disclosures), bulk_buy, bulk_sell, block_buy, block_sell (exchange deals), promoter_up, "
    "promoter_down (promoters' holding changed over a quarter), pledge_up (promoters pledged more).\n"
    "- sector_reversion: a stock cointegrated with its sector index and cheap relative to it earns more than the sector "
    "next month (long only); direction 'low' = the cheapest quintile, 'high' = the dearest.\n"
    "- none: no test above fits; say in 'needs' what data a test would need.\n"
    "Fill only the fields of the chosen test; use \"\" or 0 for the others. Reply with JSON only.")

CLAIM = {"type": "object", "additionalProperties": False,
         "required": ["claim", "quote", "template", "signal", "direction", "months", "kind", "sessions", "effect", "needs"],
         "properties": {"claim": {"type": "string"}, "quote": {"type": "string"},
                        "template": {"type": "string", "enum": ["cross_section", "event_study", "calendar",
                                                                "holder_event", "sector_reversion", "none"]},
                        "signal": {"type": "string", "enum": list(tp.SIGNALS) + [""]},
                        "direction": {"type": "string", "enum": ["high", "low", "up", "down", ""]},
                        "months": {"type": "integer", "enum": [0, 1, 3]},
                        "kind": {"type": "string", "enum": list(tp.EVENT_KINDS) + list(tp.HOLDER_KINDS) + [""]},
                        "sessions": {"type": "integer", "enum": [0, 1, 5, 20]},
                        "effect": {"type": "string", "enum": list(tp.EFFECTS) + [""]},
                        "needs": {"type": "string"}}}
READ_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["claims"],
               "properties": {"claims": {"type": "array", "items": CLAIM}}}


def params_of(c: dict) -> Tuple[str, dict]:
    t = c.get("template", "none")
    keys = {"cross_section": ("signal", "direction", "months"), "event_study": ("kind", "direction", "sessions"),
            "calendar": ("effect", "direction"), "holder_event": ("kind", "direction", "sessions"),
            "sector_reversion": ("direction",), "rule_filter": ("rule", "direction", "months"),
            "fall_response": ("depth", "confirm", "direction", "months"), "rebalance_bands": ("mix", "band", "against", "check")}.get(t, ())
    return t, {k: c.get(k) for k in keys}


# Protocol amendment 1 (2026-10-25, before any test ran): a claim fits a test only when its own words (claim and quote)
# name what the test measures; the first real read showed the local model attaching tests at random.
NAMES = {
    "momentum_12_1": r"momentum|past (winners?|losers?|returns?)|winners?|prior.{0,20}returns?|12[- ]month",
    "momentum_6_1": r"momentum|past (winners?|losers?|returns?)|winners?|prior.{0,20}returns?|6[- ]month|six[- ]month",
    "reversal_1m": r"revers\w*|short[- ]term|last month'?s|one[- ]month|1[- ]month|losers? (rebound|bounce)",
    "volatility_12m": r"volatil\w*|low[- ]risk|beta",
    "high_52w": r"52[- ]week|fifty[- ]two[- ]week|year'?s high|annual high",
    "max_day_1m": r"lottery|max(imum)? (daily )?return|extreme (daily )?return|skew\w*",
    "illiquidity": r"illiquid\w*|liquidity|amihud|turnover",
    "Financial Results": r"earnings|results?|profit|announcement",
    "Credit Rating": r"rating",
    "Acquisition": r"acqui\w*|takeover|merger",
    "Award of Order / Receipt of Order": r"order",
    "Dividend": r"dividend",
    "Change in Management": r"ceo|cfo|management|executive",
    "Resignation of Director": r"director",
    "RATING_DOWNGRADE": r"downgrad\w*",
    "DEFAULT": r"default",
    "AUDITOR_RESIGNATION": r"auditor",
    "INSOLVENCY": r"insolven\w*|bankrupt\w*",
    "FRAUD": r"fraud",
    "RESULTS_DELAY": r"delay",
    "PROMOTER_ENCUMBRANCE": r"pledg\w*|encumb\w*",
    "FORENSIC_AUDIT": r"forensic",
    "REGULATORY_ACTION": r"regulat\w*|sebi|penalt\w*|sanction",
    "turn_of_month": r"turn[- ]of[- ](the[- ])?month|month[- ]end|end of (the )?month",
    "monday": r"monday|weekend",
    "friday": r"friday|weekend",
    "january": r"january",
    "first_half_month": r"first half of (the )?month|half[- ]month|semi[- ]month",
    # amendment 3 (S63): who buys and sells
    "insider_sast": r"insider\w*|sast|takeover regulation",
    "bulk_buy": r"bulk deals?|bulk purchase\w*", "bulk_sell": r"bulk deals?|bulk sale\w*",
    "block_buy": r"block deals?|block purchase\w*", "block_sell": r"block deals?|block sale\w*",
    "promoter_up": r"promoter\w*", "promoter_down": r"promoter\w*",
    "pledge_up": r"pledg\w*|encumb\w*",
    # S64: rules (docs/protocols/s64_rules_protocol.md)
    "pe_above_50": r"p/?e\b|price[- ]to[- ]earnings|times (their |its )?(trailing )?earnings|earnings multiple|expensive|overvalu\w*",
    "pe_below_15": r"p/?e\b|price[- ]to[- ]earnings|times (their |its )?(trailing )?earnings|earnings multiple|cheap|undervalu\w*|value stocks?",
    "near_52w_low_5": r"52[- ]week low|year'?s low|annual low|near (their |its )?lows?",
    "below_sma200": r"200[- ]day|200[- ]session|long[- ]term (moving )?average",
    "volume_spike_2": r"volume (spike|surge|burst)|spike in volume|unusual volume|heavy volume",
    "ath_fall_40": r"all[- ]time high|below (their |its )?(high|peak)|drawdown|rebound",
    "rsi_below_30": r"oversold|rsi|relative strength index",
    # S64: reversion against a cointegrated sector index
    "sector_reversion": r"cointegrat\w*|mean[- ]revers\w*|revert\w*|relative to (its |the )?sector|sector index|sector",
    # S76 (docs/protocols/s76_learner_protocol.md)
    "fall_response": r"fall\w*|fell|fallen|drop\w*|below (their |its )?(one-year |year'?s )?high|drawdown",
    "rebalance_bands": r"rebalanc\w*|drift\w*|bands?",
}


# Amendment 2 (same day, before any test ran): a claim that an effect is absent has nothing to wire, so it is not tested.
ABSENT = re.compile(r"\b(not|no|cannot|can't|never|neither|nor|insignificant|fails? to|absent|disappear\w*|"
                    r"does ?n[o']t|did ?n[o']t|is ?n[o']t|are ?n[o']t|no longer|lack of)\b", re.I)


def fits(claim: str, quote: str, template: str, params: dict) -> bool:
    """The claim and its quote name the signal, filing kind or calendar effect its test measures, and the claim sentence
    says the effect exists (a quote may deny another effect on its way: "no low-volatility anomaly; high volatility pays")."""
    key = params.get("signal") or params.get("kind") or params.get("effect") or params.get("rule") or (
        template if template in ("sector_reversion", "fall_response", "rebalance_bands") else None)
    named = key in NAMES and re.search(r"\b(" + NAMES[key] + r")", f"{claim} {quote}", re.I)
    return bool(named) and not ABSENT.search(claim or "")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def quoted(quote: str, text: str) -> bool:
    """The quote is in the text (case, spacing and punctuation aside) and long enough to mean something."""
    q = _norm(quote)
    return len(q) >= MIN_QUOTE and q in _norm(text)


# --- the models ----------------------------------------------------------------------------------------------------------

def local_draft(model: Optional[str] = None) -> Draft:
    from pflab.hq import models
    from pflab.llm import client

    def draft(system: str, prompt: str, schema: dict) -> dict:
        r = client.chat(model or models.model_id("learner_reading", {"models": {"learner_reading": "local"}}),
                        [{"role": "system", "content": system}, {"role": "user", "content": prompt}], fmt=schema,
                        num_predict=1500, num_ctx=16384, purpose="learner_reading")
        return json.loads(r.text)
    return draft


def claude_draft(con, client, gate, model: str, now: datetime, mode: str = "economy") -> Draft:
    """A Claude model through the one door (public text: nothing private in the prompt; priced, governed as a reader)."""
    from pflab.llm import gateway

    def draft(system: str, prompt: str, schema: dict) -> dict:
        override, role = gateway.prefer(con, model)
        s = gateway.call(con, role, system, [{"role": "user", "content": prompt}], schema=schema, max_tokens=2000, thinking="low", model=override, agent="reader", purpose="learner claims",
                         now=now, mode=mode, private_text="", gate=gate, topic="learner", question=prompt[:200], client=client)
        if s.get("json_error"):
            raise ValueError(s["json_error"])
        return s["json"]
    return draft


def ask(drafts: List[Tuple[str, Draft]], system: str, prompt: str, schema: dict, ok: Callable[[dict], bool]) -> Tuple[dict, str]:
    """The first model whose reply parses and passes `ok`; ({}, 'none') when none does."""
    for name, d in drafts:
        try:
            out = d(system, prompt, schema)
        except Exception:
            continue
        if isinstance(out, dict) and ok(out):
            return out, name
    return {}, "none"


# --- the steps -----------------------------------------------------------------------------------------------------------

def screen(con, drafts, limit: int, now: datetime) -> int:
    n = 0
    for sid, title, abstract in con.execute(       # the standing searches first, then blogs, then arXiv's daily flow
            "SELECT src_id, title, abstract FROM learn_sources WHERE status='new' AND origin <> 'drop' ORDER BY "
            "CASE origin WHEN 'openalex' THEN 0 WHEN 'rss' THEN 1 ELSE 2 END, src_id LIMIT ?", [limit]).fetchall():
        out, who = ask(drafts, SCREEN_SYSTEM, f"TITLE: {title}\nABSTRACT: {(abstract or '')[:3000]}", SCREEN_SCHEMA,
                       lambda o: isinstance(o.get("testable"), bool))
        if not out:
            continue
        con.execute("UPDATE learn_sources SET status=?, why=? WHERE src_id=?",
                    ["screened" if out["testable"] else "skipped", f"{who}: {str(out.get('why', ''))[:300]}", sid])
        n += 1
    con.execute("UPDATE learn_sources SET status='screened' WHERE status='new' AND origin='drop'")   # his files: read
    return n


def _valid_claims(out: dict) -> bool:
    return isinstance(out.get("claims"), list) and all(isinstance(c, dict) and "template" in c for c in out["claims"])


def read(con, drafts, src_id: int, text: str, now: datetime) -> List[int]:
    """The claims of one source, each quoted from it; returns the claim ids kept."""
    from pflab.pm.store import next_id
    out, who = ask(drafts, READ_SYSTEM, text[:READ_CHARS], READ_SCHEMA, _valid_claims)
    kept = []
    for c in (out.get("claims") or [])[:MAX_CLAIMS]:
        if not quoted(c.get("quote", ""), text):
            continue                                             # no quote found in the source: not its claim
        t, prm = params_of(c)
        ok = t != "none" and tp.check_params(t, prm) is None and fits(str(c.get("claim", "")), str(c.get("quote", "")), t, prm)
        status = "proposed" if ok else "untestable"
        cid = next_id(con, "learn_claims", "claim_id")
        con.execute("INSERT INTO learn_claims (claim_id, src_id, made_at, claim, quote, template, params_json, needs, model, "
                    "status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [cid, src_id, now, str(c.get("claim", ""))[:600], str(c.get("quote", ""))[:600], t,
                     json.dumps(prm, sort_keys=True), str(c.get("needs", ""))[:300] or None, who, status])
        kept.append(cid)
    con.execute("UPDATE learn_sources SET status='read', read_at=? WHERE src_id=?", [now, src_id])
    return kept


def code_sha() -> str:
    return hashlib.sha256(Path(tp.__file__).read_bytes()).hexdigest()


def register(con, claim_id: int, proto_dir: Path, now: datetime) -> str:
    """Write the protocol before the test (once): returns 'registered' or 'same' (the test exists: not run twice)."""
    t, prm_json, claim, quote, src = con.execute(
        "SELECT template, params_json, claim, quote, src_id FROM learn_claims WHERE claim_id=?", [claim_id]).fetchone()
    same = con.execute("SELECT min(claim_id) FROM learn_claims WHERE template=? AND params_json=? AND claim_id<>? AND "
                       "status IN ('registered','passed','failed')", [t, prm_json, claim_id]).fetchone()[0]
    if same is not None:
        con.execute("UPDATE learn_claims SET status='same', same_as=? WHERE claim_id=?", [same, claim_id])
        return "same"
    title, url = con.execute("SELECT title, url FROM learn_sources WHERE src_id=?", [src]).fetchone()
    events = t in ("event_study", "holder_event")
    proto = {"claim_id": claim_id, "registered_at": now.isoformat(timespec="seconds"), "claim": claim, "quote": quote,
             "source": {"title": title, "url": url}, "template": t, "params": json.loads(prm_json),
             "periods": {"development": tp.EV_DEV if events else tp.DEV, "validation": tp.EV_VAL if events else tp.VAL},
             "rule": (f"claimed direction in both periods; t >= counter.t_needed(N) (development; never under {tp.T_DEV}, "
                      f"N = the tests in the family 'all' including this one) and >= {tp.T_VAL} (validation); "
                      f"at least {tp.MIN_EVENTS if events else tp.MIN_MONTHS} "
                      f"{'events' if events else 'months'} each; the effect larger than its cost "
                      "(templates.decide; protocol amendment 4)"),
             "tests_run_at_registration": counter.n_tests(con),
             "dev_bar_if_tested_now": round(counter.t_needed(counter.n_tests(con) + 1), 3),
             "code": "src/pflab/learner/templates.py", "code_sha256": code_sha(),
             "protocol": "docs/protocols/learner_protocol.md"}
    proto_dir.mkdir(parents=True, exist_ok=True)
    p = proto_dir / f"claim_{claim_id}.json"
    body = json.dumps(proto, indent=1, sort_keys=True)
    p.write_text(body, encoding="utf-8")
    con.execute("UPDATE learn_claims SET status='registered', protocol_path=?, protocol_sha=?, code_sha=?, registered_at=? "
                "WHERE claim_id=?", [str(p), hashlib.sha256(body.encode()).hexdigest(), proto["code_sha256"], now, claim_id])
    return "registered"


def test(con, claim_id: int, root: Path, now: datetime, run: Optional[Callable] = None) -> str:
    """Run a registered claim's template exactly as registered; the protocol file must be unchanged."""
    t, prm, path, sha, csha, claim, quote = con.execute(
        "SELECT template, params_json, protocol_path, protocol_sha, code_sha, claim, coalesce(quote, '') FROM "
        "learn_claims WHERE claim_id=? AND status='registered'", [claim_id]).fetchone()
    if not fits(claim, quote, t, json.loads(prm)):              # amendments 1-2: registered before the checks existed
        con.execute("UPDATE learn_claims SET status='withdrawn', why=?, decided_at=? WHERE claim_id=?",
                    ["its words do not name what the test measures, or it claims an effect is absent (protocol "
                     "amendments 1-2): not run", now, claim_id])
        return "withdrawn"
    body = Path(path).read_text(encoding="utf-8")
    if hashlib.sha256(body.encode()).hexdigest() != sha:
        raise RuntimeError(f"claim #{claim_id}: its protocol file changed after registration: not run")
    if csha != code_sha():
        raise RuntimeError(f"claim #{claim_id}: the test code changed since registration: register it again")
    n = counter.n_tests(con) + 1                                # amendment 4: this test counts too
    bar = counter.t_needed(n)
    res = (run or functools.partial(tp.run, threshold_dev=bar))(root, t, json.loads(prm))
    d = res["decision"]
    dev, val = res.get("development") or {}, res.get("validation") or {}
    rets = dev.pop("_returns", None)                            # the development series: for the DSR, not stored
    sr = dsr = None
    if rets and len(rets) > 3:
        x = [v for v in rets if math.isfinite(v)]
        sd = (sum((v - sum(x) / len(x)) ** 2 for v in x) / (len(x) - 1)) ** 0.5 if len(x) > 1 else 0.0
        sr = (sum(x) / len(x)) / sd if sd > 0 else None
        dsr = counter.deflated_sharpe(x, counter.sharpe_trials(con))
    res["tests_in_family"], res["dev_bar"] = n, round(bar, 3)
    if dsr is not None and math.isfinite(dsr):
        res["deflated_sharpe"] = round(dsr, 3)
    counter.record(con, now, "learner", t, json.loads(prm), claim_id=claim_id, n_dev=dev.get("n"), t_dev=dev.get("t"),
                   t_val=val.get("t"), sr_dev=sr, dsr=dsr, threshold_dev=bar, passed=d == "pass", note=f"claim:{claim_id}")
    con.execute("UPDATE learn_claims SET status=?, decision=?, why=?, result_json=?, decided_at=? WHERE claim_id=?",
                ["passed" if d == "pass" else "failed", d, res["why"][:600], json.dumps(res, default=str)[:8000], now,
                 claim_id])
    con.execute("UPDATE learn_claims SET decision=?, why=?, decided_at=? WHERE same_as=?",
                [d, f"same test as claim #{claim_id}: {res['why'][:500]}", now, claim_id])
    if d == "pass":
        wire(con, claim_id, now)
    return d


STUDY_SOURCE = "study:s64_reversion"


def register_study(con, template: str, params: dict, claim: str, quote: str, title: str, url: str, now: datetime) -> int:
    """A claim made by the system's own pre-registered study (model 'study'), not read from a paper: a source row and a
    claim row 'proposed' (the same-test check in `register` still applies). Returns the claim id; the existing one if it
    was made before."""
    from pflab.pm.store import next_id
    bad = tp.check_params(template, params)
    if bad:
        raise ValueError(bad)
    pj = json.dumps(params, sort_keys=True)
    old = con.execute("SELECT claim_id FROM learn_claims WHERE template=? AND params_json=? AND model='study' AND status NOT IN "
                      "('untestable', 'withdrawn') ORDER BY claim_id LIMIT 1", [template, pj]).fetchone()
    if old:
        return int(old[0])
    ref = f"{STUDY_SOURCE}:{template}:{pj}"
    row = con.execute("SELECT src_id FROM learn_sources WHERE ref=?", [ref]).fetchone()
    if row:
        sid = int(row[0])
    else:
        sid = next_id(con, "learn_sources", "src_id")
        con.execute("INSERT INTO learn_sources (src_id, found_at, origin, ref, title, authors, year, url, abstract, status, "
                    "why, read_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [sid, now, "study", ref, title, "the system", now.year, url, claim, "read", "pre-registered study", now])
    cid = next_id(con, "learn_claims", "claim_id")
    con.execute("INSERT INTO learn_claims (claim_id, src_id, made_at, claim, quote, template, params_json, model, status) "
                "VALUES (?,?,?,?,?,?,?,?,?)", [cid, sid, now, claim[:600], quote[:600], template, pj, "study", "proposed"])
    return cid


def reregister_stale(con, proto_dir: Path, now: datetime) -> int:
    """Editing templates.py changes `code_sha` and so invalidates every claim registered but not yet tested; none of them
    has run, so each is registered again under the new code (protocol amendment 4). Tested claims are left alone."""
    stale = [r[0] for r in con.execute("SELECT claim_id FROM learn_claims WHERE status='registered' AND code_sha<>? "
                                       "ORDER BY claim_id", [code_sha()]).fetchall()]
    for cid in stale:
        con.execute("UPDATE learn_claims SET status='proposed' WHERE claim_id=?", [cid])
    for cid in stale:
        register(con, cid, proto_dir, now)
    return len(stale)


def redecide_passed(con, now: datetime) -> List[dict]:
    """Amendment 4: an old pass is judged again against the bar of today's N (its stored development t, in the claimed
    direction). One that misses it becomes a fail and its live finding ends. Returns what changed."""
    from pflab.learner import live
    n = counter.n_tests(con)
    bar = counter.t_needed(n)
    changed = []
    for cid, t, prm, res in con.execute("SELECT claim_id, template, params_json, result_json FROM learn_claims WHERE "
                                        "status='passed' ORDER BY claim_id").fetchall():
        try:
            r = json.loads(res or "{}")
            t_dev = float((r.get("development") or {})["t"])
        except Exception:
            continue                                            # no stored t: left as it is, nothing to compare
        p = json.loads(prm or "{}")
        sign = -1 if p.get("direction") in ("down", "low") and t != "cross_section" else 1
        if sign * t_dev >= bar:
            continue
        why = (f"re-decided under protocol amendment 4 ({now.date()}): development t {sign * t_dev:+.2f} is under the bar "
               f"{bar:.2f} for {n} tests run; no live feature")
        con.execute("UPDATE learn_claims SET status='failed', decision='fail', why=?, decided_at=? WHERE claim_id=?",
                    [why, now, cid])
        con.execute("UPDATE learn_claims SET decision='fail', why=?, decided_at=? WHERE same_as=?", [why, now, cid])
        con.execute("UPDATE learn_tests SET passed=false, note=note || ' (re-decided)' WHERE claim_id=?", [cid])
        live.end(con, "finding", f"{t}:{prm}", now)
        changed.append({"claim_id": cid, "t_dev": t_dev, "bar": bar})
    return changed


def wire(con, claim_id: int, now: datetime) -> int:
    """A passed claim, live: a `finding` the brain reads (one per test; a re-test replaces it)."""
    from pflab.learner import live
    claim, t, prm, why, title = con.execute(
        "SELECT c.claim, c.template, c.params_json, c.why, s.title FROM learn_claims c JOIN learn_sources s USING (src_id) "
        "WHERE claim_id=?", [claim_id]).fetchone()
    text = f"{claim} Tested here ({t} {prm}): {why} (source: {title[:120]}; claim #{claim_id})"
    return live.put(con, "finding", f"{t}:{prm}", text, prm, f"claim #{claim_id}", now)


def table(con, limit: int = 30) -> List[dict]:
    rows = con.execute("SELECT c.claim_id, c.made_at, c.claim, c.template, c.params_json, c.status, c.decision, c.why, "
                       "c.needs, s.title, s.url FROM learn_claims c JOIN learn_sources s USING (src_id) "
                       "ORDER BY c.claim_id DESC LIMIT ?", [limit]).fetchall()
    k = ["id", "at", "claim", "template", "params", "status", "decision", "why", "needs", "source", "url"]
    return [dict(zip(k, r)) for r in rows]
