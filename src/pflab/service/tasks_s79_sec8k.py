"""S85 job `sec_8k`: US company filings from the SEC into the graph (8-K items 5.02, 4.01, 4.02) for the US names the system holds, picks, skips or watches (`pflab/ingest/sec_8k.py`).

Code only, free (public data; the SEC's contact header comes from the secrets file and is never logged). Every two hours on weekdays in the SEC's filing hours, and on the app's start after a gap
(`service/ondemand.py` MAX_AGE_H). Bounded (requests and seconds); a refusal or a failure is a visible line in the job's result, never a failed run. Skips without the `[sec] user_agent` contact."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab.us import instruments as uins
    if not uins.sec_contact_configured():
        return False, "no [sec] user_agent in the secrets file: the SEC refuses a request without a contact (pflab setup secrets)"
    return True, ""


def _run(ctx) -> dict:
    from pflab.ingest import sec_8k
    from pflab.service.jobs import last_success
    try:
        out = sec_8k.run_job(ctx.con, ctx.data_root, ctx.now, last_success=last_success(ctx.con, "sec_8k"))
    except Exception as e:                       # visible, never a failed job: the next run asks again
        return {"problems": [f"sec_8k: {type(e).__name__}: {str(e)[:160]}"]}
    return out


register(Job("sec_8k", Interval(120, weekdays_only=False), _run,
             "US company filings from the SEC: 8-K items 5.02 (officers), 4.01 (auditor), 4.02 (restated accounts) for the US names held, picked, skipped or watched, into the graph (S85; code, free)",
             cooldown_minutes=30, enabled_fn=_enabled))
