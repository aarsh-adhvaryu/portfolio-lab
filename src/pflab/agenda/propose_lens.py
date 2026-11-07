"""Agenda kind `propose_lens` (S79b item 18D): the agenda drafts a candidate lens as a PROTOCOL STUB, never code and never live use.

A stub is a text file under docs/protocols/lens_candidates/<name>.md: the question, the inputs, the features, the quantile output and the admission rule, with the status
"STUB: not registered, no code". A row in `lens_candidates` records it. A candidate enters the ensemble only the long way: the lead (or the investor) turns the stub into a
committed protocol, someone writes the lens against `fcast/plugins.py`, it runs in shadow, and it is admitted only by its live score. The idea bank below is fixed in code
(standard indicators a trader would ask about); the stub's numbers are the ensemble's own constants, nothing is model made.

Switch: configs/s79b.toml [lens] on. Off: the producer finds nothing."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import List

from pflab.agenda import items, kinds

KIND = "propose_lens"

IDEAS = [
    ("lens_vwap_anchor", "Anchored VWAP from the last swing low and swing high",
     "close above/below the volume-weighted average price anchored at the most recent swing point", "daily bars with volume (high, low, close)",
     "distance of the close from each anchored VWAP in daily sigmas; side"),
    ("lens_range_compression", "Volatility compression before expansion",
     "the share of the last 20 sessions' range to the last 250 sessions' range (narrow ranges are said to precede wide ones)", "daily high, low, close",
     "ratio and its expanding percentile; spread of the return quantiles, not their centre"),
    ("lens_gap_fill", "Opening gaps and the fill",
     "after a gap of more than one daily sigma at the open, how often the gap is closed within 1 and 5 sessions", "daily open, prior close",
     "signed gap in sigmas; share of past gaps filled"),
    ("lens_round_levels", "Round-number levels",
     "price clustering near round numbers (for an index: multiples of 500/1000) and what follows a close just under or over one", "daily close",
     "distance to the nearest round level in daily sigmas"),
    ("lens_delivery_trend", "Delivery share of volume",
     "a rising delivery share (bhavcopy) on up days against falling on up days as a sign of holding or of churn", "bhavcopy delivery quantity and traded quantity",
     "20-session change of the delivery share; its expanding percentile"),
    ("lens_relative_strength", "Strength against the sector and the market",
     "a name that has outperformed its sector and the index over 20 and 60 sessions continuing or reverting over the next 5 and 20", "adjusted closes of the name, its sector index and the market index",
     "relative return in the name's sigmas over both windows"),
]


def stub_dir() -> Path:
    from pflab.fcast import protocol as P
    return P.PROTOCOL.parent / "lens_candidates"


def stub_text(name: str, title: str, question: str, inputs: str, features: str, now: datetime) -> str:
    return f"""# Lens candidate (STUB): {name}

Status: STUB drafted by the agenda on {now:%Y-%m-%d}. NOT registered, no code, not live. It becomes a pre-registered protocol only when the lead commits a protocol file for it.

## Idea
{title}: {question}.

## Question to be registered
Does conditioning the centre of the next 1, 5 and 20 session return quantiles on this indicator improve the pinball loss of the combined forecast over the combination without it?

## Inputs (point in time: rows dated on or before the forecast date only)
{inputs}.

## Features
{features}.

## Quantile output
The lens returns quantiles of the h-session return at fcast.protocol.LEVELS: the volatility forecaster's spread, its centre shifted by the mean of the standardised
outcomes that had already matured after the same state, shrunk to zero by n/(n+n0), capped. Fit by code on past data only. (This is the shape of lens_value_area.)

## Admission rule (the generic one, fcast/plugins.py)
Shadow (scored, Hedge-weighted, left out of the combined forecast) until at least 60 live sessions of the market AND the Diebold-Mariano t of the pinball loss of the
combination without it minus the combination with it reaches the learner counter's bar t_needed(N), with a positive mean.

## Before any run
The replay (2012-2021) may run the lens as a development read only. 2022-2025 is spent. Running this as a study counts in the learner's counter.
"""


def _produce(con, market: str, now: datetime) -> List[dict]:
    from pflab.fcast import plugins
    if not plugins.is_on():
        return []
    have = {r[0] for r in con.execute("SELECT name FROM lens_candidates").fetchall()} if _table(con) else set()
    plugins.active()
    out = []
    for name, title, question, inputs, features in IDEAS:
        if name in have or name in plugins.REGISTRY or items.ever_handled(con, market, KIND, f"lens:{name}"):
            continue
        out.append({"subject": f"lens:{name}", "reason": f"draft a protocol stub for {name}: {title}", "expected_value": 1.0, "cost_seconds": 2.0,
                    "payload": {"name": name}})
        if len(out) >= 1:                                   # one stub per round: a candidate is a conversation starter, not a stream
            break
    return out


def _table(con) -> bool:
    try:
        con.execute("SELECT 1 FROM lens_candidates LIMIT 1")
        return True
    except Exception:
        return False


def _work(rt, item: dict, now: datetime) -> dict:
    from pflab.fcast import plugins
    from pflab.pm.store import next_id
    if not plugins.is_on():
        return {"skip": "the lens switch is off"}
    name = str((item.get("payload") or {}).get("name") or "")
    idea = next((i for i in IDEAS if i[0] == name), None)
    if idea is None or not re.fullmatch(r"lens_[a-z0-9_]+", name):
        return {"skip": f"unknown idea {name!r}"}
    con = rt.cursor()
    if con.execute("SELECT 1 FROM lens_candidates WHERE name=?", [name]).fetchone():
        return {"skip": f"{name} already has a stub"}
    d = stub_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.md"
    if path.exists():
        return {"skip": f"{path.name} already exists"}
    path.write_text(stub_text(*idea, now), encoding="utf-8")
    cid = next_id(con, "lens_candidates", "candidate_id")
    con.execute("INSERT INTO lens_candidates VALUES (?,?,?,?,?,?,?,?)",
                [cid, item.get("market") or "IN", name, idea[1], f"docs/protocols/lens_candidates/{path.name}", "stub", now, "protocol stub only; no code, not live"])
    return {"useful": False, "effect": "", "outcome": f"stub filed: docs/protocols/lens_candidates/{path.name} (no code, not live; waits for the lead's protocol)"}


kinds.register(KIND, _produce, _work, cost_seconds=2.0, doc="drafts a candidate lens as a protocol stub (text only; never code, never live)")
