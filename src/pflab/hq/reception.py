"""The receptionist (S59): whatever the investor says or drops goes to the agent that takes it. Fixed rules on the words
(no model), so the same words always take the same road; what no rule claims goes to the ask centre's escalation chain
(`agents.escalate`: local first, then the agents, then Opus), which has its own rules.

    /calc /sim /web /research /analyse /quant /memory /graph /clean /remind /brain /portfolio /read /watch /learn
    /security:
        straight to that agent;  /order AGENT text: any agent by name
    plain words: the rules below, in order
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

COMMANDS = {"calc": "calc", "calculate": "calc", "sim": "sim", "simulate": "sim", "web": "web", "research": "research",
            "deep": "research", "analyse": "analysis", "analyze": "analysis", "analysis": "analysis", "quant": "quant",
            "memory": "memory", "journal": "memory", "graph": "graph", "clean": "cleanup", "cleanup": "cleanup",
            "remind": "messenger", "reminders": "messenger", "brain": "brain", "portfolio": "portfolio",
            "read": "reader", "watch": "watcher", "ask": "ask", "learn": "learner", "learner": "learner",
            "security": "security"}

RULES = [
    ("messenger", re.compile(r"\b(remind me|reminder|don'?t let me forget|ping me|nudge me)\b", re.I)),
    ("memory", re.compile(r"^\s*(remember|note that|i (decided|have decided|chose)|we decided|keep in mind)\b|"
                          r"\b(what did (i|we) decide|my decisions?|the journal)\b", re.I)),
    ("sim", re.compile(r"\b(simulat\w*|monte ?carlo|stress[- ]?test\w*|crash(es)?|after[- ]crash|what happens if the market|"
                       r"fan chart|fall chance|times ?fm|forecast\w*)\b", re.I)),
    ("web", re.compile(r"\b(search the web|on the web|google|look (it )?up online|internet)\b", re.I)),
    ("analysis", re.compile(r"\b(this file|the file|attached|attachment|export|tijori|screener|p/?e sheet|spreadsheet|"
                            r"pdf|the sheet|inbox item)\b", re.I)),
    ("quant", re.compile(r"\b(hypothes\w+|backtest\w*|pre-?regist\w*|does .{1,60} predict|event study|anomal\w+|factor)\b", re.I)),
    ("cleanup", re.compile(r"\b(clean ?up|tidy|duplicate\w*|merge (the )?names?)\b", re.I)),
    ("graph", re.compile(r"\b(knowledge graph|the graph|connections?|linked to|related to)\b", re.I)),
    ("brain", re.compile(r"\b(what matters|what should i (watch|worry)|big picture|the brain)\b", re.I)),
]


def route(text: str) -> Tuple[str, str]:
    """(agent, the text for it). A slash command names its agent; plain words go by the rules, else to `ask`."""
    t = text.strip()
    if t.startswith("/"):
        head, _, rest = t.partition(" ")
        cmd = head[1:].split("@")[0].lower()
        if cmd == "order":
            agent, _, body = rest.strip().partition(" ")
            return agent.lower(), body.strip()
        if cmd in COMMANDS:
            return COMMANDS[cmd], rest.strip()
        return "", t
    for agent, rx in RULES:
        if rx.search(t):
            return agent, t
    return "ask", t


def is_hq_command(text: str) -> bool:
    t = text.strip()
    if not t.startswith("/"):
        return False
    cmd = t.split(" ", 1)[0][1:].split("@")[0].lower()
    return cmd == "order" or cmd in COMMANDS


def item_ref(text: str) -> Optional[int]:
    """'#12', 'item 12' -> 12 (an inbox item)."""
    m = re.search(r"(?:#|\bitem\s+)(\d+)\b", text, re.I)
    return int(m.group(1)) if m else None
