"""S79 item 11: the option-implied chances are kept beside what happened (quant/implied_calibration.py): new days recorded, outcomes filled when the horizon passes."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pflab.service.jobs import Ctx, Job, last_success, register
from pflab.service.schedule import Daily


def _implied_calibration(ctx: Ctx) -> dict:
    from pflab.quant import implied, implied_calibration as ic
    return ic.refresh(ctx.con, ctx.data_root, "IN", ctx.now.date()) | {"option_data": ic.has_option_data(ctx.data_root, "IN"), "file": implied.FILE}


def _redo(ctx: Ctx) -> Optional[str]:
    """Due again when the kept option days are newer than the last run."""
    from pflab.quant import implied
    p = ctx.data_root / "derived" / implied.FILE
    last = last_success(ctx.con, "implied_calibration")
    if not p.exists() or last is None:
        return None
    return "new option days kept" if datetime.fromtimestamp(p.stat().st_mtime) > last else None


register(Job("implied_calibration", Daily(23, 10), _implied_calibration, "keeps each day's option-implied fall chances beside what happened (scored when the expiry passes)",
             cooldown_minutes=60, redo_fn=_redo))
