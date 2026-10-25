"""Evaluation periods (charter E1 §11). The loader truncates at a period's
end before the engine sees data. Sealed periods need a written reason and
are journaled. This is a procedural safeguard, not security."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from pflab import _toml


class SealedPeriodError(RuntimeError):
    pass


class WindowError(ValueError):
    pass


@dataclass(frozen=True)
class Period:
    name: str
    start: date
    end: date
    sealed: bool = False


def load_periods(path) -> Dict[str, Period]:
    raw = _toml.load(path)["periods"]
    out = {}
    for name, p in raw.items():
        out[name] = Period(name, date.fromisoformat(p["start"]), date.fromisoformat(p["end"]),
                           bool(p.get("sealed", False)))
    return out


def truncate_end(df: pd.DataFrame, period: Period, date_col: str = "date") -> pd.DataFrame:
    """Drop every row dated after the period end. The ONLY sanctioned path
    from raw data to the engine. History before the start is kept: signals
    need it; trading is restricted to the window by the engine."""
    d = pd.to_datetime(df[date_col]).dt.date
    return df.loc[d <= period.end].copy()


def truncate_membership(table: pd.DataFrame, period: Period) -> pd.DataFrame:
    """`truncate_end` for an index-membership table (E1b §3).

    A membership table carries dates on both ends, so truncating it is not a
    row filter: a name included after the period end must be dropped, and a
    name excluded after the period end was still a member as far as this
    period can know, so its `to_date` is reset to None. Without the second
    half the engine would know in 2010 that a name leaves the index in 2024.
    """
    t = table.copy()
    for col in ("from_date", "to_date"):
        t[col] = pd.to_datetime(t[col], errors="coerce").dt.date
    t = t[t["from_date"] <= period.end]
    t.loc[t["to_date"].notna() & (t["to_date"] > period.end), "to_date"] = None
    return t.reset_index(drop=True)


def check_window(period: Period, start: date, end: date) -> None:
    if start < period.start or end > period.end:
        raise WindowError(f"window {start}..{end} outside period {period.name} "
                          f"{period.start}..{period.end}")


def _git_commit() -> Optional[str]:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # pragma: no cover
        return None


def open_period(name: str, periods: Dict[str, Period], journal_path,
                unseal_reason: Optional[str] = None, extra: Optional[dict] = None) -> Period:
    """Return the period, enforcing the seal. A sealed period requires a
    reason of at least 20 characters and appends a journal line."""
    if name not in periods:
        raise KeyError(f"unknown period {name!r}; known: {sorted(periods)}")
    p = periods[name]
    if p.sealed:
        if not unseal_reason or len(unseal_reason.strip()) < 20:
            raise SealedPeriodError(
                f"period {name!r} is sealed; pass --unseal with a written reason (>=20 chars)")
        Path(journal_path).parent.mkdir(parents=True, exist_ok=True)
        line = {"ts": datetime.now(timezone.utc).isoformat(), "period": name,
                "reason": unseal_reason.strip(), "git": _git_commit(), "cwd": os.getcwd()}
        if extra:
            line.update(extra)
        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    return p


def reveals(journal_path) -> int:
    """How many sealed reveals are on record."""
    jp = Path(journal_path)
    if not jp.exists():
        return 0
    return sum(1 for line in jp.read_text(encoding="utf-8").splitlines() if line.strip())
