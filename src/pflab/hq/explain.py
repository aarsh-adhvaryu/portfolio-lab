"""Explain a move (S79 item 7): run the four explanation tools, let the LOCAL model write five plain lines from their results, and let no number through that does not
cite the call that produced it.

    explain_move(rt, market, symbol, day, now) -> {"text", "call_ids", "rejected", "source": "model" | "code", "calls": {tool: call id}}

Each tool is run through the tool loop (`tools.run`), so each has a call id in `hq_tool_calls` and prints it as `call_ref`. The model must put `[call N]` after every
sentence that carries a figure, and every figure in the sentence must be found in the result of one of the calls it cites (same value, as printed). A sentence that does not
meet that is rejected, and ANY rejection (or an unavailable model) means the answer is the paragraph code writes from the same results, which cites the same way.
The tool loop's own number guard (`tools._checked`, the pass's `ctx.source`) is run over the final text as well.

`biggest_moves` lists the largest moves of the day among the names the system holds, lists or watches, for the agenda to pick what to explain first.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Tuple

TOOL_NAMES = ("trajectory", "decompose_move", "align_events", "breadth")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_TAG = re.compile(r"\[calls?\s*([\d,\s]+)\]", re.I)
_LEAD = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)")
_DROP = ("rule", "rules", "method", "source", "event_times", "day_type_rule", "burst_rule", "universe")


# --- the citation check ------------------------------------------------------------------------------------------------------------------

def numbers(s: str) -> set:
    """Every figure in a text as the digits it is written with (commas out, no sign: 'fell 3.2' for -3.2), the same way the tool loop's own guard reads them, so
    3.5 and 3.50 are different figures: a figure is quoted as printed."""
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(s)}


def _f(v) -> str:
    """A figure the way the tools print it (JSON), without a sign."""
    return json.dumps(abs(v)) if isinstance(v, float) else str(abs(v))


def _p(v) -> str:
    """A signed figure as the tools print it."""
    return ("-" if v < 0 else "") + _f(v)


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub("", s)).strip()


def check_citations(text: str, results: Dict[int, str]) -> Tuple[str, List[dict], List[int]]:
    """(clean text, rejected [{sentence, why}], call ids cited by the kept sentences). A sentence with a figure must cite at least one known call id, and each of
    its figures must be in the union of the cited calls' results, written the same way. A sentence with no figure needs no citation."""
    have = {cid: numbers(t) for cid, t in results.items()}
    kept_lines, rejected, used = [], [], []
    for line in text.split("\n"):
        kept = []
        for s in re.split(r"(?<=[.!?])\s+", line.strip()):
            if not s:
                continue
            tags = [int(x) for t in _TAG.findall(s) for x in re.findall(r"\d+", t)]
            body = _LEAD.sub("", _TAG.sub(" ", s))
            nums = numbers(body)
            if not nums:
                kept.append(s)
                continue
            if not tags:
                rejected.append({"sentence": s, "why": "a figure with no call id cited"})
                continue
            if any(t not in have for t in tags):
                rejected.append({"sentence": s, "why": f"cites a call that was not made in this pass: {[t for t in tags if t not in have]}"})
                continue
            known = set().union(*(have[t] for t in tags))
            bad = sorted(nums - known)
            if bad:
                rejected.append({"sentence": s, "why": f"figure(s) {bad} not in the cited call(s) {tags}"})
                continue
            kept.append(s)
            used.extend(tags)
        if kept:
            kept_lines.append(" ".join(kept))
    return "\n".join(kept_lines), rejected, sorted(set(used))


# --- running the tools ----------------------------------------------------------------------------------------------------------------

def _ctx(rt, now: datetime):
    from pflab.hq import egress, tools as tl
    try:
        from pflab.hq import service
        gate = service.gate(rt)
    except Exception:
        gate = egress.Gate()
    return tl.Ctx(rt, None, "explain", False, {}, gate, now, role="research", allowed=frozenset(TOOL_NAMES))


def run_tools(rt, market: str, symbol: str, day: date, now: datetime) -> Tuple[object, Dict[str, dict], Dict[int, str]]:
    """(ctx, {tool: result dict}, {call id: result text}). The calls are journaled with ids like any tool call."""
    from pflab.hq import tools as tl
    ctx = _ctx(rt, now)
    base = {"market": market, "date": str(day)}
    out, texts = {}, {}
    for name in TOOL_NAMES:
        args = dict(base) if name == "breadth" else {**base, "symbol": symbol}
        text, err = tl.run(ctx, name, args)
        try:
            res = json.loads(text)
        except ValueError:
            res = {"error": text[:300]}
        if err and "error" not in res:
            res = {"error": text[:300]}
        out[name] = res
        cid = res.get("call_ref") if isinstance(res, dict) else None
        if cid:
            texts[int(cid)] = text
    return ctx, out, texts


# --- the facts as text ------------------------------------------------------------------------------------------------------------------

def _model_view(results: Dict[str, dict]) -> str:
    def slim(x):
        if isinstance(x, dict):
            return {k: slim(v) for k, v in x.items() if k not in _DROP}
        if isinstance(x, list):
            return [slim(v) for v in x]
        return x
    return "\n".join(f"[call {r['call_ref']}] {name}: {json.dumps(slim(r), default=str, ensure_ascii=False)}" for name, r in results.items() if isinstance(r, dict) and r.get("call_ref"))


def _tag(r: dict) -> str:
    return f" [call {r['call_ref']}]" if isinstance(r, dict) and r.get("call_ref") else ""


def factual_paragraph(symbol: str, day: date, res: Dict[str, dict]) -> str:
    """The code-written explanation: plain sentences, every figure followed by the call it came from, every gap said."""
    tj, dc, al, br = (res.get(k) or {} for k in TOOL_NAMES)
    lines: List[str] = []
    total = dc.get("total_pct") if dc.get("total_pct") is not None else tj.get("day_pct")
    src = dc if dc.get("total_pct") is not None else tj
    if total is not None:
        lines.append(f"{symbol} {'rose' if total > 0 else 'fell' if total < 0 else 'was flat'} {_f(total)}% on {day} against the prior close{_tag(src)}.")
    else:
        lines.append(f"No price move for {symbol} on {day} could be worked from the files on this PC.")
    if dc.get("market_pct") is not None:
        sec = f"sector part {_p(dc['sector_pct'])}%" if dc.get("sector_pct") is not None else "sector not split out (it sits inside the own part)"
        s = f"Market part {_p(dc['market_pct'])}% (beta {_f(dc['beta_market'])} on the index's {_p(dc['market_index_pct'])}%), {sec}, own part {_p(dc['own_pct'])}%{_tag(dc)}."
        lines.append(s)
    elif dc.get("note"):
        lines.append(f"The move could not be split into market, sector and own part: {dc['note']}.")
    if tj.get("n_bars"):
        s = f"The day was a {tj['day_type']}"
        if tj.get("gap_pct") is not None:
            s += f", opening {_p(tj['gap_pct'])}% from the prior close"
        od = tj.get("opening_drive")
        if od:
            s += f", the first 30 minutes moved {_p(od['pct'])}% {od['direction']}"
        s += f", the high came at {tj['time_of_high']} and the low at {tj['time_of_low']}, and it closed {_f(tj['close_location'])} of the way up its range{_tag(tj)}." if tj.get("close_location") is not None \
            else f", the high came at {tj['time_of_high']} and the low at {tj['time_of_low']}{_tag(tj)}."
        gaps = (tj.get("gaps") or {}).get("missing")
        if gaps:
            s += f" {gaps} minutes of the session are missing from the record and were not filled{_tag(tj)}."
        lines.append(s)
    else:
        lines.append("No minute bars were recorded for that day, so the path of the day is not known.")
    if al.get("n_bursts"):
        b0 = al["bursts"][0]
        s = f"There were {al['n_bursts']} sudden minute moves; the first at {b0['at']} was {_p(b0['return_pct'])}%"
        if b0["preceded_by"]:
            e = b0["preceded_by"][-1]
            s += f", {e['minutes_before']} minutes after a {e['kind']} ({e['what']})"
        s += f"{_tag(al)}."
        if al["n_unexplained"]:
            s += f" {al['n_unexplained']} of them have no filing or news in the window before them: the data does not say why{_tag(al)}."
        lines.append(s)
    elif tj.get("n_bars"):
        lines.append(f"No minute was far beyond the day's usual moves{_tag(tj)}.")
    if br.get("advancers") is not None:
        s = f"Across the exchange {br['advancers']} names rose and {br['decliners']} fell"
        a50 = br.get("above_sma50") or {}
        if a50.get("pct") is not None:
            s += f", and {_f(a50['pct'])}% of names sit above their 50 day average"
        lines.append(s + f"{_tag(br)}.")
    elif br.get("note"):
        lines.append(f"Market breadth is not available: {br['note']}.")
    return "\n".join(lines)


SYSTEM = ("You explain, for a private investor who is not a trader, why one stock moved on one day. You are given the results of four calculations, each tagged [call N]. "
          "Write exactly 5 short plain lines, one sentence each. Rules: use only facts in the results; copy every figure exactly as printed (same digits) and put the tag "
          "of the result it came from right after the sentence, like [call 12]; never write a figure that is not in a result, never round or compute your own; "
          "the stock's whole move is total_pct; market_pct, sector_pct and own_pct are the parts of it (own = what neither the market nor the sector explains), never call a part the move; "
          "if bursts have no filing or news before them say the data does not say why; if something is missing, say it is missing; no advice, no guesses about causes beyond "
          "what the results show; no lists, no headings, no numbering.")


def explain_move(rt, market: str, symbol: str, day: date, now: datetime, chat: Optional[Callable[[str, str], str]] = None) -> dict:
    """The five-line explanation of one name's move on one session. `chat(system, user) -> text` is the local model (default: Ollama through `pflab.llm.client`)."""
    ctx, res, texts = run_tools(rt, market, symbol, day, now)
    calls = {n: r.get("call_ref") for n, r in res.items() if isinstance(r, dict)}
    out = {"market": market, "symbol": symbol, "day": str(day), "calls": calls, "rejected": [], "source": "code", "call_ids": []}
    fallback = factual_paragraph(symbol, day, res)
    text = None
    try:
        if chat is None:
            chat = _local_chat
        raw = chat(SYSTEM, f"Stock: {symbol}. Session: {day} ({market}).\n\n{_model_view(res)}\n\nWrite the 5 lines now.")
        clean, rejected, used = check_citations(raw or "", texts)
        out["rejected"] = rejected
        if raw and clean and not rejected:
            text, out["call_ids"], out["source"] = clean, used, "model"
    except Exception as e:                                          # the model being away is a normal day: the code paragraph answers
        out["model_error"] = f"{type(e).__name__}: {str(e)[:160]}"
    if text is None:
        text = fallback
        text, rej2, used = check_citations(text, texts)               # the code paragraph meets the same rule (a failure here is a bug and is reported)
        out["call_ids"] = used
        if rej2:
            out["rejected"] = out["rejected"] + [{**r, "stage": "code paragraph"} for r in rej2]
    out["text"] = text
    out["source_guard_dropped"] = check_against_source(ctx, text)
    return out


def check_against_source(ctx, text: str) -> int:
    """How many sentences the tool loop's own number guard (`tools._checked`, over everything read this pass) would drop from the text. 0 for text that passed the citation check."""
    from pflab.agents import analyst as an
    _, n = an.only_sourced_numbers(strip_tags(text), an.Request(ctx.source, "explain"))
    return int(n)


def _local_chat(system: str, user: str) -> str:
    from pflab.llm import client, registry
    model = registry.chosen("general") or "qwen3:8b-q8_0"
    return client.chat(model, [{"role": "system", "content": system}, {"role": "user", "content": user}], num_predict=450, num_ctx=8192, purpose="explain_move", timeout=900).text


# --- what to explain first ------------------------------------------------------------------------------------------------------------

def biggest_moves(con, market: str, day: date, n: int = 5, root=None) -> List[dict]:
    """The largest moves of the day (by |%|, against the exchange's own prior close) among the names the system holds, lists, has ordered or watches. Names without a price that day are left out."""
    if market != "IN":
        return []
    from pflab.data import data_dir
    from pflab.quant import decompose
    from pflab.service.tasks_s79_bars import INDEX_PREFIX, wanted
    root = root or data_dir()
    rows = []
    for isin, sym in wanted(con, market, day).items():
        if isin.startswith(INDEX_PREFIX):
            continue
        r = decompose.bhav_row(root, isin, day)
        if r and r.get("prev_close"):
            rows.append({"symbol": sym, "isin": isin, "day": str(day), "move_pct": round((float(r["close"]) / float(r["prev_close"]) - 1.0) * 100.0, 2)})
    return sorted(rows, key=lambda x: -abs(x["move_pct"]))[:max(0, n)]
