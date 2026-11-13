"""The scripted model of the S84 replays: a stand-in for the SDK client behind `llm/gateway.py` (`gateway.set_client`), and the scripted readings of the three replays. No number is ever in an
answer (rule 8): a class, an option, a likelihood word, a pending event and a reason. Nothing here sends anything anywhere."""
from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional

NVDA_SYMBOL = "NVDA"


class ScriptMsg:
    """What the vendor's client returns (the fields `hq/llm` and the gateway read)."""

    def __init__(self, blocks, stop: str = "end_turn", model: str = "claude-sonnet-5-5", cached: int = 0):
        self.content, self.stop_reason, self.model = blocks, stop, model
        self.usage = SimpleNamespace(input_tokens=2600, output_tokens=420, cache_read_input_tokens=cached, cache_creation_input_tokens=0)


class ScriptedClient:
    """`responder(call) -> {"text": str} | {"tools": [(name, input)]}`, where `call` has `model`, `schema` (the answer's JSON schema or None), `has_tool_result`, `first` (the first user message), `n`
    (this client's call number) and `tools`. Every answer is counted in `counter["answers"]`: the standing check on paid calls lets exactly these through."""

    def __init__(self, responder: Callable, counter: Optional[dict] = None, fail: Optional[str] = None):
        self.responder, self.counter, self.fail = responder, counter if counter is not None else {}, fail
        self.calls: List[dict] = []
        self.messages = SimpleNamespace(count_tokens=lambda **k: SimpleNamespace(input_tokens=3000), create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: self._create(**{x: y for x, y in k.items() if x not in ("betas", "fallbacks")})))

    def _create(self, **p):
        if self.fail:
            raise RuntimeError(self.fail)
        msgs = p.get("messages") or []
        first = msgs[0]["content"] if msgs else ""
        if isinstance(first, list):
            first = "\n".join(b.get("text", "") for b in first if isinstance(b, dict))
        has_tr = any(isinstance(m.get("content"), list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"]) for m in msgs)
        fmt = ((p.get("output_config") or {}).get("format") or {}).get("schema")
        call = {"model": p.get("model", ""), "schema": fmt, "has_tool_result": has_tr, "first": first, "n": len(self.calls), "tools": bool(p.get("tools")), "messages": msgs}
        out = self.responder(call)
        self.calls.append({"model": call["model"], "schema": bool(fmt), "tools": call["tools"], "has_tool_result": has_tr})
        self.counter["answers"] = self.counter.get("answers", 0) + 1
        if "tools" in out:
            return ScriptMsg([SimpleNamespace(type="tool_use", id=f"tu{len(self.calls)}_{i}", name=n, input=a) for i, (n, a) in enumerate(out["tools"])], "tool_use", call["model"])
        return ScriptMsg([SimpleNamespace(type="text", text=out["text"])], "end_turn", call["model"], cached=2400 if len(self.calls) > 1 else 0)


def case_of(con, first: str) -> Optional[dict]:
    from pflab.think import cases
    m = re.search(r"CASE #(\d+)", first or "")
    return cases.get_case(con, int(m.group(1))) if m else None


class Scenario:
    """The scripted reading of one replay. `answers(case, n)`: the structured answer the n-th time this case is thought through. `read_tools(case)`: what Sonnet looks at before it answers.
    `check`: the independent big-trade checker's verdict ("pass" or "veto")."""

    def __init__(self, name: str, answers: Callable, read_tools: Optional[Callable] = None, reading: Optional[Callable] = None, check: str = "pass"):
        self.name, self.answers, self.check = name, answers, check
        self.read_tools = read_tools or (lambda case: [("recall", {"symbol": case.get("symbol") or ""}), ("graph_events", {"symbol": case.get("symbol") or ""})])
        self.reading = reading or (lambda case: f"Reading of case #{case['case_id']} ({case.get('symbol')}): the stored signals and headlines say what the case title says; I rely on no figure of my own.")
        self.n: Dict[int, int] = {}
        self.log: List[dict] = []

    def responder(self, con) -> Callable:
        def respond(call: dict) -> dict:
            sch = call["schema"]
            props = (sch or {}).get("properties") or {}
            if "verdict" in props:                                                  # the independent big-trade check
                return {"text": json.dumps({"verdict": self.check, "reason": "scripted checker: " + ("no concrete reason against it" if self.check == "pass" else "a scripted veto")})}
            case = case_of(con, call["first"])
            if case is None:
                return {"text": "Done."}
            if not sch:
                if call["tools"] and not call["has_tool_result"]:
                    return {"tools": self.read_tools(case)}
                return {"text": self.reading(case)}
            n = self.n[case["case_id"]] = self.n.get(case["case_id"], 0) + 1
            ans = self.answers(case, n)
            self.log.append({"case_id": case["case_id"], "n": n, "model": call["model"], "class": ans.get("class"), "choices": [(c["symbol"], c["option"]) for c in ans.get("choices", [])]})
            return {"text": json.dumps(ans)}
        return respond


def words(worst: str = "unlikely", likely: str = "likely", best: str = "unlikely", sets: str = "own range",
          why: str = "no event of this kind has enough cases in the store: the name's own range stands in") -> dict:
    return {"worst": worst, "likely": likely, "best": best, "base_rate_set": sets, "reason": why}


def _other(case: dict, klass: str = "market_fear", option: str = "hold") -> dict:
    """Any case that is not the replay's subject (a market-wide move, a synthetic holding): read as ordinary, nothing to do."""
    sym = case.get("symbol") or "the market"
    return {"happened": f"{sym} moved with its market or sector on the day; no company event is stored for it.", "sources": ["the stored closes"], "class": klass,
            "known": "The move is in the stored closes.", "pending": "", "pending_date": "", "other_names": [],
            "choices": [{"symbol": sym, "option": option, "reason": "an ordinary move with no company event behind it"}], "likelihood": words("unlikely", "likely", "unlikely")}


def nvda_held_answers(case: dict, n: int) -> dict:
    sym = case.get("symbol") or NVDA_SYMBOL
    if sym != NVDA_SYMBOL:
        return _other(case)
    return {"happened": "Nvidia's chief executive disclosed a relationship with a former executive of a company US officials suspect of spying for China, and the board opened an investigation (press reports of Sunday evening, US time).",
            "sources": ["press reports of Sunday evening (US)", "the graph's event row"], "class": "damage",
            "known": "The chief executive's disclosure and the board's investigation are public; a class action followed.", "pending": "the board's decision on the chief executive", "pending_date": "",
            "other_names": ["QQQ", "SPY"],
            "choices": [{"symbol": sym, "option": "sell", "reason": "a governance shock at the top of the company is damage until shown otherwise; the break condition of the pick is governance"}],
            "likelihood": words("unlikely", "likely", "unlikely")}


def nvda_not_held_answers(case: dict, n: int) -> dict:
    sym = case.get("symbol") or NVDA_SYMBOL
    if sym != NVDA_SYMBOL:
        return _other(case, "market_fear", "nothing")
    base = {"happened": "Nvidia's chief executive is under a board investigation and the shares fell; the broad index funds the sub-book holds carry it as a large weight (press reports).",
            "sources": ["press reports of the week", "the graph's event rows"], "known": "The investigation and a class action are public; the board's decision is not.",
            "other_names": ["SPY", "QQQ", "XLK"], "class": "unclear", "pending": "the board's decision on the chief executive", "pending_date": "2026-11-12"}
    if n == 1:
        return dict(base, choices=[{"symbol": sym, "option": "wait", "reason": "the board's decision is pending: no buying until it is public and the shares stop making new lows"}],
                    likelihood=words("even", "even", "unlikely"))
    return dict(base, choices=[{"symbol": sym, "option": "buy_in_parts", "reason": "the shares are far under their last close before the news: the model sees a dip; the rule has its own guards"}],
                likelihood=words("even", "likely", "unlikely"))


def ather_answers(case: dict, n: int) -> dict:
    sym = case.get("symbol") or "the name"
    if case.get("kind") != "missed_run":
        return _other(case)
    return {"happened": "Ather Energy has run well ahead of its index since the system looked at it and passed (the skip reason was valuation against negative trailing earnings).",
            "sources": ["the stored skip and its reason", "the stored closes against the index total return"], "class": "temporary",
            "known": "The price has risen a lot; trailing earnings are still negative.", "pending": "", "pending_date": "", "other_names": ["TVSMOTOR", "HEROMOTOCO"],
            "choices": [{"symbol": sym, "option": "buy_in_parts", "reason": "the reason for passing (valuation, negative earnings) has not been answered by results: only the price changed; if anything is bought it is small and in parts"}],
            "likelihood": words("unlikely", "even", "unlikely")}


SCENARIOS = {"nvda_held": nvda_held_answers, "nvda_not_held": nvda_not_held_answers, "ather": ather_answers}
