"""Assembling, rendering and storing the situation report (S79b item 16): sections NOW / WHY / SO WHAT / NEXT / ACT, plus the disagreements.

The model's draft (synth.draft) is checked here, item by item, by code. When the model is away, or its draft is empty or rejected, each section falls back to a
code-written version made from the claims (flagged `coded_only` for the whole report when no model text survived). Disagreements and NEXT scenarios are always
code-written: the model only comments on them.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from pflab.pm.store import next_id
from pflab.situation import chains as CH, claims as C, synth, watch as W

SECTIONS = ("now", "why", "so_what", "next", "act")


def short(t: str, n: int = 150) -> str:
    t = " ".join(str(t).split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " ..."


def tag(ids: List[int]) -> str:
    return (" [claim " + ", ".join(str(i) for i in ids) + "]") if ids else ""


# --- NEXT: the scenarios the tools produce ------------------------------------------------------------------------------------------------

def next_candidates(claims: List[dict]) -> List[dict]:
    """Scenarios made from the probability claims (never from the model): {key, event, level, probs{h: p}, claim_ids{h: id}, call_ids, statement, label}."""
    by_sub = {c["subject"]: c for c in claims if c.get("value") is not None}
    out = []
    probs, cids, calls = {}, {}, []
    for h in (1, 5, 20):
        c = by_sub.get(f"p_down_h{h}")
        if c is not None and 0.0 <= c["value"] <= 1.0:
            probs[h], cids[h] = c["value"], c["claim_id"]
            calls += c.get("call_ids") or []
    if probs:
        label = "the index is lower than today's close after " + ", ".join(f"{h} sessions (chance {json.dumps(p)})" for h, p in probs.items())
        out.append({"key": "index_lower", "event": "return_below", "level": 0.0, "probs": probs, "claim_ids": cids, "call_ids": sorted(set(calls)), "statement": label, "label": label})
    c = by_sub.get("fall_risk_20")
    if c is not None and 0.0 <= c["value"] <= 1.0:
        label = f"the index closes at least 5% under today's level within 20 sessions (chance {json.dumps(c['value'])})"
        out.append({"key": "fall5_20", "event": "fall_within", "level": 5.0, "probs": {20: c["value"]}, "claim_ids": {20: c["claim_id"]}, "call_ids": c.get("call_ids") or [], "statement": label, "label": label})
    for s, c in by_sub.items():
        m = re.fullmatch(r"implied_fall_(\d+)_h(\d+)", s)
        if m and 0.0 <= c["value"] <= 1.0:
            x, hz = int(m.group(1)), int(m.group(2))
            label = f"options-implied: the index closes at least {x}% under today's level within {hz} sessions (chance {json.dumps(c['value'])})"
            out.append({"key": f"implied_fall{x}_{hz}", "event": "fall_within", "level": float(x), "probs": {hz: c["value"]}, "claim_ids": {hz: c["claim_id"]}, "call_ids": c.get("call_ids") or [],
                        "statement": label, "label": label})
    return out


# --- disagreements ----------------------------------------------------------------------------------------------------------------------

GROUP = {"regime": "near", "open_gap": "near", "macro_attribution": "near", "market_sentiment": "near", "p_down_h1": "near", "p_down_h5": "mid", "p_down_h20": "long", "fall_risk_20": "long"}


def lean(c: dict) -> Optional[int]:
    """+1 bullish, -1 bearish, 0 neutral, None not directional. By code, per kind of claim; only the claims that carry a direction."""
    v, s, k = c.get("value"), c["subject"], c["kind"]
    if v is None:
        return None
    if s == "regime" or k == "wave" or s == "market_sentiment":
        return (v > 0) - (v < 0) if s != "market_sentiment" or abs(v) >= 0.25 else 0
    if s == "macro_attribution":                      # how the index actually moved on the day: it can contradict what the gap model or the regime said
        return 1 if v >= 0.3 else -1 if v <= -0.3 else 0
    if s.startswith("p_down_h"):
        return -1 if v >= 0.55 else 1 if v <= 0.45 else 0
    if s == "fall_risk_20" or s.startswith("implied_fall_"):
        return -1 if v >= 0.15 else None
    if s == "open_gap":
        return 1 if v >= 0.15 else -1 if v <= -0.15 else 0
    return None


def group_of(c: dict) -> Optional[str]:
    g = GROUP.get(c["subject"])
    if g:
        return g
    if c["subject"].startswith("implied_fall_"):
        return "long"
    return "near" if c["kind"] == "wave" else None


def detect_contradictions(claims: List[dict]) -> List[dict]:
    """Groups (near / mid / long horizon) in which claims from different sources lean opposite ways. Each is kept with both sides and the tools' probabilities for them."""
    groups: Dict[str, Dict[int, List[dict]]] = {}
    for c in claims:
        g, ln = group_of(c), lean(c)
        if g and ln in (1, -1):
            groups.setdefault(g, {}).setdefault(ln, []).append(c)
    out = []
    for g, sides in sorted(groups.items()):
        if 1 not in sides or -1 not in sides:
            continue
        if len({c["source"] for cs in sides.values() for c in cs} | {c["subject"] for cs in sides.values() for c in cs}) < 2:
            continue
        expl = []
        for ln, name in ((-1, "bearish"), (1, "bullish")):
            cs = sorted(sides[ln], key=lambda c: c["claim_id"])
            p = None
            for c in cs:
                if c["subject"].startswith(("p_down_h", "fall_risk", "implied_fall_")):
                    p = c["value"] if ln == -1 else round(1.0 - c["value"], 3)
                    break
            expl.append({"side": name, "claim_ids": [c["claim_id"] for c in cs], "text": "; ".join(c["text"][:110] for c in cs[:2]), "probability": p})
        out.append({"subject": f"{g}-horizon: {expl[0]['side']} versus {expl[1]['side']}", "group": g, "explanations": expl,
                    "claim_ids": [i for e in expl for i in e["claim_ids"]]})
    return out


def store_contradictions(con, report_id: Optional[int], market: str, as_of: date, cons: List[dict], now: datetime) -> None:
    """Keep each contradiction and queue it on the agenda (kind resolve_contradiction); the agenda de-duplicates by day."""
    from pflab.agenda import items
    for c in cons:
        cid = next_id(con, "situation_contradiction", "contradiction_id")
        iid = items.add(con, market, "resolve_contradiction", c["subject"], "agents disagree: " + " | ".join(f"{e['side']} claims {e['claim_ids']}" for e in c["explanations"]), 4.0, 0.0, 90.0, now,
                        {"contradiction_id": cid, "claim_ids": c["claim_ids"], "as_of": str(as_of)})
        con.execute("INSERT INTO situation_contradiction VALUES (?,?,?,?,?,?,?,?,?)", [cid, report_id, market, as_of, c["subject"], json.dumps(c["claim_ids"]),
                                                                                        json.dumps(c["explanations"]), iid, now])
        c.update(contradiction_id=cid, agenda_item_id=iid)


# --- assembling the sections --------------------------------------------------------------------------------------------------------------

CODE_NOW_KINDS = ("wave", "rotation", "regime", "move", "transmission", "macro", "event", "sentiment")


def _now_code(claims: List[dict], limit: int = 5) -> List[dict]:
    order = {k: i for i, k in enumerate(CODE_NOW_KINDS)}
    cs = sorted([c for c in claims if c["kind"] in order and c["subject"] != "regime"], key=lambda c: (order[c["kind"]], c["subject"]))
    cs = [c for c in claims if c["subject"] == "regime"][:1] + cs
    return [{"text": c["text"], "claims": [c["claim_id"]], "by": "code"} for c in cs[:limit]]


def _so_what_code(claims: List[dict]) -> List[dict]:
    out = []
    for c in sorted([c for c in claims if c["kind"] in ("exposure", "book", "allocation")], key=lambda c: (c["kind"], -(c.get("value") or 0.0)))[:5]:
        out.append({"text": c["text"], "claims": [c["claim_id"]], "by": "code"})
    return out


PART_ORDER = (("part_crude", "crude"), ("part_currency", "rupee"), ("part_us10y", "US 10-year"), ("part_nasdaq", "Nasdaq"), ("part_flows", "foreign flows"), ("part_asia", "Asian peers"))


def headline(claims: List[dict]) -> List[dict]:
    """The facts every report opens with, written by code from the claims (never by the model): the index's day move, its parts (crude, rupee, US 10-year, Nasdaq, foreign flows, Asia,
    and the unexplained share), breadth, the wave and rotation flags (or none), the book's change on the day, and the week in one line. A missing fact is said to be missing."""
    by_sub: Dict[str, dict] = {}
    for c in claims:
        by_sub.setdefault(c["subject"], c)
    out: List[dict] = []

    def put(text: str, ids: List[int]) -> None:
        out.append({"text": text, "claims": [i for i in ids if i], "by": "code", "headline": True})

    c = by_sub.get("macro_attribution")
    put(c["text"] if c else "The index's move on the day is not available (the macro attribution has no row for it)", [c["claim_id"]] if c else [])
    parts = [(lab, by_sub[s]) for s, lab in PART_ORDER if s in by_sub and by_sub[s].get("value") is not None]
    if parts:
        put("Parts of that move, in percent of the index (an association, not a proof): " + ", ".join(f"{lab} {json.dumps(p['value'])}" for lab, p in parts), [p["claim_id"] for _, p in parts])
    u = by_sub.get("part_unexplained")
    if u:
        put(u["text"], [u["claim_id"]])
    b = by_sub.get("breadth")
    put(b["text"] if b else "Breadth is not available", [b["claim_id"]] if b else [])
    flags = [x for x in (by_sub.get("wave"), by_sub.get("rotation")) if x and (x.get("value") or 0) != 0]
    if flags:
        for x in flags:
            put(x["text"], [x["claim_id"]])
    else:
        w = by_sub.get("wave")
        put("Wave and rotation flags: none" + (f" ({w['text']})" if w else ""), [w["claim_id"]] if w else [])
    d = by_sub.get("book_day")
    put(d["text"] if d else "The book's change on the day is not available (no marked day, no priced holding)", [d["claim_id"]] if d else [])
    wk = by_sub.get("week")
    if wk:
        put(wk["text"], [wk["claim_id"]])
    return out


def theme_lines(claims: List[dict], limit: int = 4) -> List[dict]:
    """SO WHAT, by code: each theme whose sentiment shifted most over 5 sessions, next to how much of the book carries that theme (the theme_exposure claim of the same theme)."""
    exp = {t: c for c in claims if c["kind"] == "exposure" and c["subject"].startswith("theme_") for t in (c.get("themes") or [])}
    out = []
    for s in sorted([c for c in claims if c["subject"].startswith("theme_shift_") and c.get("value") is not None], key=lambda c: -abs(c["value"]))[:limit]:
        e = exp.get((s.get("themes") or [None])[0])
        out.append({"text": f"Theme shift: {s['text']}. " + (f"The book: {e['text']}." if e else "The book has no measured exposure to this theme."),
                    "claims": [s["claim_id"]] + ([e["claim_id"]] if e else []), "by": "code", "theme": True})
    return out


def miss_lines(claims: List[dict]) -> List[dict]:
    """Contradictions between a model and what happened, as one code-written line each (today: the gap the transmission model expected against the index's move)."""
    return [{"text": "Contradiction: " + c["text"], "claims": [c["claim_id"]], "by": "code"} for c in claims if c["subject"] == "transmission_miss"]


def _checked(items: List[dict], by_id: Dict[int, dict], rejected: List[dict], section: str) -> List[dict]:
    """Code-written lines pass the same citation check as the model's; a refusal is a bug in the claim text and is listed (the line is kept, the fact is true)."""
    for it in items:
        text, rej, _ = synth.verify(it["text"], it["claims"], by_id)
        rejected.extend({**r, "section": section, "stage": "code line"} for r in rej)
    return items


def assemble(claims: List[dict], contradictions: List[dict], cands: List[dict], dr: Optional[dict], series_ok: List[str]) -> Tuple[dict, List[dict], bool]:
    """(sections, rejected, coded_only). `dr` is the model's draft (or None / {'error': ...})."""
    by_id = {c["claim_id"]: c for c in claims}
    rejected: List[dict] = []
    have_model = bool(dr) and "error" not in dr
    sec: dict = {"now": [], "why": [], "so_what": [], "next": [], "act": {}}
    used_model = False

    def prose(items, key):
        nonlocal used_model
        out = []
        for it in (items or [])[:6]:
            if not isinstance(it, dict):
                continue
            text, rej, used = synth.verify(it.get("text", ""), it.get("claims") or [], by_id)
            rejected.extend({**r, "section": key} for r in rej)
            if text:
                out.append({"text": text, "claims": used or [int(i) for i in (it.get("claims") or []) if int(i) in by_id], "by": "model"})
        used_model = used_model or bool(out)
        return out

    head = _checked(headline(claims), by_id, rejected, "now")
    sec["headline"] = head
    comment = prose(dr.get("now"), "now")[:3] if have_model else []
    for x in comment:
        x["commentary"] = True
    sec["now"] = head + comment
    # WHY: only whitelisted cause -> effect types, each cause dated before its effect (state effects excepted, see chains.py); the model's links and the code's own, merged
    model_pairs, links = {}, []
    if have_model:
        for lk in (dr.get("why") or [])[:6]:
            if isinstance(lk, dict):
                try:
                    model_pairs[(int(lk.get("cause")), int(lk.get("effect")))] = lk.get("mechanism", "")
                except (TypeError, ValueError):
                    pass
                links.append({"cause": lk.get("cause"), "effect": lk.get("effect"), "mechanism": lk.get("mechanism", "")})
    seen = {(str(x["cause"]), str(x["effect"])) for x in links}
    links += [x for x in CH.code_links(by_id) if (str(x["cause"]), str(x["effect"])) not in seen]
    chain = CH.make_chain(links, by_id, strict_types=True)
    why = []
    for lk in chain["links"]:
        try:
            pair = (int(lk["cause"]), int(lk["effect"]))
        except (TypeError, ValueError):
            pair = None
        from_model = pair in model_pairs
        if not lk["ok"]:
            if from_model or pair is None:
                rejected.append({"sentence": f"link {lk['cause']} -> {lk['effect']}", "why": lk["reason"], "section": "why"})
            continue
        if len(why) >= 6:
            continue
        mech, rej, _ = synth.verify(model_pairs[pair], [lk["cause"], lk["effect"]], by_id) if from_model else (lk["mechanism"], [], [])
        rejected.extend({**r, "section": "why"} for r in rej)
        c, e = by_id[pair[0]], by_id[pair[1]]
        if from_model and not mech:
            mech = next((m for n, t, m in CH.WHITELIST if n == lk["type"]), "")
        why.append({"cause": c["claim_id"], "effect": e["claim_id"], "mechanism": mech or "mechanism not stated", "cause_date": lk["cause_date"], "effect_date": lk["effect_date"],
                    "type": lk["type"], "cause_text": c["text"], "effect_text": e["text"], "by": "model" if from_model else "code"})
        used_model = used_model or (from_model and bool(mech))
    sec["why"], sec["chain"] = why, chain
    # SO WHAT: the theme shifts against the book's exposure, by code; then the model's reading (at most two)
    th = _checked(theme_lines(claims), by_id, rejected, "so_what")
    used_exp = {i for x in th for i in x["claims"]}
    rest = [x for x in _so_what_code([c for c in claims if c["claim_id"] not in used_exp and c["subject"] != "book_day"])][:3]
    model_sw = prose(dr.get("so_what"), "so_what")[:2] if have_model else []
    sec["so_what"] = th + rest + model_sw
    # NEXT: the tools' scenarios; the model's comment is added when it survives the check
    notes = {}
    if have_model:
        for n in dr.get("next") or []:
            if isinstance(n, dict) and n.get("candidate"):
                ids = [i for i in (n.get("claims") or []) if i in by_id]
                cand = next((c for c in cands if c["key"] == n["candidate"]), None)
                if cand is None:
                    continue
                text, rej, _ = synth.verify(n.get("note", ""), ids or [i for i in cand["claim_ids"].values()], by_id)
                rejected.extend({**r, "section": "next"} for r in rej)
                if text:
                    notes[cand["key"]] = text
                    used_model = True
    sec["contradictions_found"] = _checked(miss_lines(claims), by_id, rejected, "next")
    sec["next"] = [{"key": c["key"], "text": c["label"], "probs": {str(h): p for h, p in c["probs"].items()}, "claims": sorted(set(c["claim_ids"].values())), "call_ids": c["call_ids"],
                    "note": notes.get(c["key"], ""), "event": c["event"], "level": c["level"]} for c in cands[:6]]
    # ACT (the model's proposals, checked)
    act = (dr.get("act") or {}) if have_model else {}
    out_act: dict = {"paper_request": "", "agenda": [], "question": None, "watch": [], "watch_refused": []}
    pr, rej, _ = synth.verify(act.get("paper_request", ""), [], by_id)
    rejected.extend({**r, "section": "act"} for r in rej)
    out_act["paper_request"] = pr
    for a in (act.get("agenda") or [])[:3]:
        if isinstance(a, dict) and a.get("subject"):
            reason, rej, _ = synth.verify(a.get("reason", ""), [], by_id)
            rejected.extend({**r, "section": "act"} for r in rej)
            subj = str(a["subject"]).strip()
            if subj in {c["subject"] for c in claims} | {c["kind"] for c in claims}:
                out_act["agenda"].append({"subject": subj[:150], "reason": reason[:300]})
            else:
                rejected.append({"sentence": f"agenda: {subj[:60]}", "why": "an agenda subject must be the subject or kind of a claim in the situation", "section": "act"})
    q = act.get("question")
    if isinstance(q, dict) and q.get("text") and q.get("default"):
        qt, rej, _ = synth.verify(q["text"], [], by_id)
        qd, rej2, _ = synth.verify(q["default"], [], by_id)
        rejected.extend({**r, "section": "act"} for r in rej + rej2)
        if qt and qd:
            out_act["question"] = {"text": qt, "default": qd}
    for w in (act.get("watch") or [])[:3]:
        if isinstance(w, dict):
            ok, why_not = synth.watch_ok(w, by_id, series_ok)
            if ok:
                out_act["watch"].append({"text": str(w.get("text", ""))[:200], "series": w["series"], "op": w["op"], "threshold": float(w["threshold"]), "claim": int(w["claim"])})
            else:
                out_act["watch_refused"].append({"text": str(w.get("text", ""))[:120], "why": why_not})
    used_model = used_model or bool(out_act["watch"] or out_act["agenda"] or out_act["question"] or out_act["paper_request"])
    sec["act"] = out_act
    sec["disagreements"] = contradictions
    return sec, rejected, not used_model


# --- rendering ----------------------------------------------------------------------------------------------------------------------------------

def render(market: str, as_of: date, mode: str, sec: dict, coded_only: bool, model: str = "", flags: Optional[List[str]] = None, sources: Optional[List[dict]] = None) -> str:
    L = [f"SITUATION {market} {as_of} ({mode})" + (" - written by code from the claims, no model text (flag: coded only)" if coded_only else f" - written by {model or 'the local model'}, every figure checked by code")]
    if flags:
        L.append("Flags: " + "; ".join(flags))
    L.append("NOW")
    heads, comm = [x for x in sec["now"] if x.get("headline")], [x for x in sec["now"] if not x.get("headline")]
    if heads:
        L.append("Headline facts (written by code):")
    L += [f"- {x['text']}{tag(x['claims'])}" for x in heads]
    if comm and heads:
        L.append("Commentary (" + (model or "model") + "):")
    L += [f"- {x['text']}{tag(x['claims'])}" for x in comm] or ([] if heads else ["- the claims say nothing yet"])
    L.append("WHY")
    L += [f"- {short(x['cause_text'])} (dated {x['cause_date']}) led to: {short(x['effect_text'])} (dated {x['effect_date']}). {x['mechanism']}{tag([x['cause'], x['effect']])}" for x in sec["why"]] \
        or ["- no cause that is dated before its effect was found"]
    if sec.get("disagreements"):
        L.append("DISAGREEMENTS (kept, not merged; each is on the agenda)")
        for d in sec["disagreements"]:
            L.append(f"- {d['subject']}: " + " | ".join(f"{e['side']}{tag(e['claim_ids'])}" + (f" probability {json.dumps(e['probability'])}" if e["probability"] is not None else "") for e in d["explanations"]))
    L.append("SO WHAT")
    L += [f"- {x['text']}{tag(x['claims'])}" for x in sec["so_what"]] or ["- no book exposure claim yet"]
    L.append("NEXT (probabilities are the tools'; each is scored at its horizon)")
    for x in sec.get("contradictions_found", []):
        L.append(f"- {x['text']}{tag(x['claims'])}")
    for n in sec["next"]:
        L.append(f"- {n['text']}{tag(n['claims'])}" + (f" {n['note']}" if n.get("note") else ""))
    if not sec["next"]:
        L.append("- no tool gave a probability for the index")
    L.append("ACT")
    a = sec["act"]
    if a.get("paper_request"):
        L.append(f"- Request to the paper team: {a['paper_request']}")
    for x in a.get("agenda", []):
        L.append(f"- Agenda: {x['subject']} ({x['reason']})")
    if a.get("question"):
        L.append(f"- Question for the investor: {a['question']['text']} (default: {a['question']['default']})")
    for w in a.get("watch", []):
        L.append(f"- Watch: {w['text']} ({w['series']} {w['op']} {w['threshold']:g})")
    if not (a.get("paper_request") or a.get("agenda") or a.get("question") or a.get("watch")):
        L.append("- nothing new to do" + ("; the disagreements above are on the agenda" if sec.get("disagreements") else ""))
    if sources:
        L.append("Sources: " + ", ".join(f"{s['source']} {s['status']}" for s in sources if s["status"] != "empty")[:400])
    return "\n".join(L)


# --- storing ------------------------------------------------------------------------------------------------------------------------------------

def store(con, market: str, as_of: date, mode: str, now: datetime, sec: dict, text: str, coded_only: bool, model: str, n_claims: int, sources: List[dict],
          flags: List[str], rejected: List[dict]) -> int:
    rid = next_id(con, "situation_report", "report_id")
    con.execute("INSERT INTO situation_report VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [rid, market, as_of, mode, now, "code" if coded_only else model, coded_only, json.dumps(sec, default=str), text, n_claims, json.dumps(sources), json.dumps(flags),
                 json.dumps(rejected[:30], default=str)])
    return rid


def latest(con, market: str, as_of: Optional[date] = None) -> Optional[dict]:
    q = ("SELECT report_id, market, as_of, mode, created_at, author, coded_only, sections, text, n_claims, sources, flags, rejected FROM situation_report WHERE market=?"
         + (" AND as_of<=?" if as_of else "") + " ORDER BY as_of DESC, report_id DESC LIMIT 1")
    r = con.execute(q, [market, *([as_of] if as_of else [])]).fetchone()
    if not r:
        return None
    return {"report_id": r[0], "market": r[1], "as_of": str(r[2]), "mode": r[3], "created_at": str(r[4])[:16], "author": r[5], "coded_only": bool(r[6]), "sections": json.loads(r[7]),
            "text": r[8], "n_claims": r[9], "sources": json.loads(r[10] or "[]"), "flags": json.loads(r[11] or "[]"), "rejected": json.loads(r[12] or "[]")}


# --- ACT: what the report does ------------------------------------------------------------------------------------------------------------------

def carry_out(con, market: str, as_of: date, now: datetime, report_id: int, sec: dict, cfg: dict, coded_only: bool, root=None) -> dict:
    """The effects of ACT, each limited and logged: watch triggers (the stream), agenda items, one request to the paper team a day, one question to the investor a day.
    Nothing here trades. Returns what was done."""
    from pflab.agenda import items
    done = {"watch": [], "watch_refused": list(sec["act"].get("watch_refused", [])), "agenda": [], "paper_request": None, "question": None}
    a = sec["act"]
    for w in a.get("watch", []):
        r = W.add(con, market, w["text"], w["series"], w["op"], w["threshold"], as_of, now, claim_id=w["claim"], report_id=report_id, root=root)
        (done["watch"] if r.get("stored") else done["watch_refused"]).append({**w, **r})
    for x in a.get("agenda", []):
        iid = items.add(con, market, "situation_check", x["subject"], x["reason"], 2.0, 0.0, 45.0, now, {"report_id": report_id})
        if iid:
            done["agenda"].append({"item_id": iid, **x})
    if a.get("paper_request") and cfg.get("paper_requests", True) and not coded_only:
        n = con.execute("SELECT count(*) FROM paper_inputs WHERE text LIKE 'From the situation report%' AND CAST(logged_at AS DATE)=?", [now.date()]).fetchone()[0]
        if n < int(cfg.get("paper_requests_per_day", 1)):
            try:
                from pflab.paper import manager
                done["paper_request"] = manager.add_input(con, now, f"From the situation report of {as_of} ({market}): {a['paper_request']}")
            except Exception as e:
                done["paper_request"] = {"stored": False, "problem": f"{type(e).__name__}: {str(e)[:100]}"}
    q = a.get("question")
    if q and cfg.get("questions", True) and not coded_only:
        try:
            from pflab.agents import questions
            n = con.execute("SELECT count(*) FROM questions WHERE subject_key LIKE 'situation:%' AND CAST(created_at AS DATE)=?", [now.date()]).fetchone()[0]
        except Exception:
            n = 99
        if n < int(cfg.get("questions_per_day", 1)):
            import hashlib
            key = f"situation:{market}:{as_of}:{hashlib.sha1(q['text'].encode()).hexdigest()[:8]}"
            try:
                done["question"] = {"q_id": questions.ask(con, "situation", key, q["text"], now, default=q["default"], deadline=now + timedelta(hours=18))}
            except Exception as e:
                done["question"] = {"q_id": None, "problem": f"{type(e).__name__}: {str(e)[:100]}"}
    return done


# --- the World screen and the post-close note ---------------------------------------------------------------------------------------------------

def world_view(con, markets_: Optional[List[str]] = None) -> dict:
    """What the World screen shows FIRST: the latest report per market in short form (the sections, the disagreements, how it was written, the flags, the calibration count)."""
    from pflab.situation import build, score, watch as Wt
    if not build.enabled():
        return {"available": False, "off": True}
    if markets_ is None:
        try:
            from pflab import markets as M
            markets_ = M.codes()
        except Exception:
            markets_ = ["IN"]
    out = []
    for m in markets_:
        rep = latest(con, m)
        if not rep:
            continue
        s = rep["sections"]
        out.append({"market": m, "as_of": rep["as_of"], "mode": rep["mode"], "author": rep["author"], "coded_only": rep["coded_only"], "created_at": rep["created_at"],
                    "flags": rep["flags"], "now": s.get("now", [])[:9], "contradictions_found": s.get("contradictions_found", [])[:2], "why": [{k: x[k] for k in ("cause_text", "effect_text", "mechanism", "cause_date", "effect_date")} for x in s.get("why", [])[:3]],
                    "so_what": s.get("so_what", [])[:3], "next": [{k: x.get(k) for k in ("text", "note", "probs")} for x in s.get("next", [])[:4]],
                    "act": {k: v for k, v in (s.get("act") or {}).items() if k in ("paper_request", "agenda", "question", "watch")},
                    "disagreements": [{"subject": d["subject"], "sides": [{"side": e["side"], "probability": e["probability"], "text": e["text"][:140]} for e in d["explanations"]]}
                                      for d in s.get("disagreements", [])[:3]],
                    "calibration": score.calibration(con, m).get("n"), "watch": len([w for w in Wt.active(con, m) if w["status"] == "active"])})
    return {"available": bool(out), "reports": out}


def note_lines(con, market: str = "IN", limit: int = 12) -> List[str]:
    """The situation report for the post-close note, report first: its text, trimmed to `limit` lines. Empty when there is none."""
    rep = latest(con, market)
    return rep["text"].splitlines()[:limit] if rep else []
