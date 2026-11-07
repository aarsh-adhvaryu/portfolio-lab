"""S79b: the data the overnight items read, kept current by the app itself: FII/DII flows, India VIX, GDELT world events and theme tone (public data over HTTP; no credentials).

Job `data_s79b`: daily, weekends too, and due whenever it has not run in 20 hours (service/ondemand.MAX_AGE_H). Each part is independent: one failing (a site down) is named in `failed`
and the others still run; a lost connection is 'offline', not a failure (service/jobs.offline). GDELT is bounded to a few days per run so a long absence catches up over several runs.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Optional

from pflab.service.jobs import Job, register
from pflab.service.schedule import Daily

MAX_GDELT_DAYS = 3


def _last_date(path) -> Optional[date]:
    try:
        import pandas as pd
        df = pd.read_parquet(path)
        col = "date" if "date" in df.columns else df.columns[0]
        return pd.to_datetime(df[col]).max().date()
    except Exception:
        return None


def run(root, today: date, flows=None, vix=None, world=None, themes=None) -> dict:
    """The job body with injectable parts (tests)."""
    from pathlib import Path
    root = Path(root)
    out: dict = {}
    failed: dict = {}
    from pflab.data import flows as fl, vix_in, gdelt_s79b as g
    for name, fn in (("flows", flows or (lambda: fl.collect(root))), ("india_vix", vix or (lambda: vix_in.refresh(root, today)))):
        try:
            out[name] = fn()
        except Exception as e:
            failed[name] = f"{type(e).__name__}: {e}"
    yesterday = today - timedelta(days=1)
    for name, fn, rel in (("gdelt_world", world or (lambda a, b: g.extend_world(a, b, root, log=lambda *_: None)), "gdelt/world/daily_by_country.parquet"),
                          ("gdelt_themes", themes or (lambda a, b: g.extend_themes(a, b, root, log=lambda *_: None)), "gdelt_s79b/daily_theme_tone.parquet")):
        last = _last_date(root / rel)
        start = (last + timedelta(days=1)) if last else yesterday - timedelta(days=MAX_GDELT_DAYS - 1)
        end = min(yesterday, start + timedelta(days=MAX_GDELT_DAYS - 1))
        if start > end:
            out[name] = {"current_to": str(last)}
            continue
        try:
            out[name] = {"from": str(start), "to": str(end), **(fn(start, end) or {})}
        except Exception as e:
            failed[name] = f"{type(e).__name__}: {e}"
    if failed:
        out["failed"] = failed
    return out


def _data(ctx) -> dict:
    from pflab import _toml
    from pathlib import Path
    cfg = Path(__file__).resolve().parents[3] / "configs" / "s79b.toml"
    try:
        if not _toml.load(cfg).get("data", {}).get("on", True):
            return {"skipped": "switched off ([data] on = false)"}
    except Exception:
        pass
    return run(ctx.data_root, ctx.now.date())


register(Job("data_s79b", Daily(20, 20, weekdays_only=False), _data, "FII/DII flows, India VIX, GDELT world events and theme tone kept current (public data, no credentials; a failing part is named, the rest still run)", cooldown_minutes=60))
