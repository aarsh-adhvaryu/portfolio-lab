"""S79 item 13: what went wrong with a local call, read from the call itself (never from a model).

`classify(text, tokens_out, num_predict, done_reason, fmt)` returns one label:
    ok          a clean finish
    truncated   the model hit its token cap (Ollama done_reason "length", or tokens_out >= num_predict)
    empty       no text came back
    loop        repeated text (a sentence or a long n-gram said again and again, the failure Qwen warns of under greedy decoding)
    format      a constrained (JSON) call whose text does not parse
Inability (wrong content with a clean finish) cannot be seen from the call; it is what the guard and the scored tasks measure.
The label goes into the `note` of the `llm_runs` row, so the next diagnosis can count loops and truncations without the text.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Optional

LABELS = ("ok", "truncated", "empty", "loop", "format")


def looks_like_loop(text: str, min_words: int = 40) -> bool:
    """Repetition: some 6-word run occurs 3 or more times, or one sentence is repeated 3 or more times, or one word makes up
    over 40% of a long reply. Short replies (under `min_words` words) are never called loops."""
    words = re.findall(r"\S+", text or "")
    if len(words) < min_words:
        return False
    grams = Counter(tuple(words[i:i + 6]) for i in range(len(words) - 5))
    if grams and grams.most_common(1)[0][1] >= 3:
        return True
    sents = [s.strip().lower() for s in re.split(r"(?<=[.!?\n])\s+", text) if len(s.strip()) > 15]
    if sents and Counter(sents).most_common(1)[0][1] >= 3:
        return True
    return Counter(w.lower() for w in words).most_common(1)[0][1] > 0.4 * len(words)


def classify(text: str, tokens_out: int = 0, num_predict: Optional[int] = None, done_reason: str = "", fmt: bool = False) -> str:
    if not (text or "").strip():
        return "truncated" if done_reason == "length" else "empty"
    if done_reason == "length" or (num_predict and tokens_out >= num_predict):
        return "truncated"
    if fmt:
        try:
            json.loads(text)
        except ValueError:
            return "format"
    return "loop" if looks_like_loop(text) else "ok"


def rates(labels: list) -> dict:
    """{label: share} over a list of labels (all labels present)."""
    n = len(labels)
    return {k: (sum(1 for x in labels if x == k) / n if n else 0.0) for k in LABELS}
