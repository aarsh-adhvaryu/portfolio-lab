"""Containment, proven (S70, amendment A34; the investor 2026-11-01: answering "seen" only acknowledges a message, it validates nothing).

Where each calculation ran is one of four things, and the store says which (`hq_calcs.contained`, the workshop's meta.json, `learn_attempts`):

    docker     True   model-written code ran in the sandbox (Docker: no network, read-only root, job folder read-only)
    host       False  model-written code ran in the uncontained subprocess (the workshop's explicit setting only; refused in an installed app)
    reviewed   NULL   the system's own reviewed code ran (a trusted study, a reviewed measure): no model-written code
    not_run    NULL   nothing ran (a static check failed first, the sandbox was not available)

Until S70 the last two were written as False, so every trusted calculation and every try that never started looked "not contained", and a
question asked the investor to answer "seen". `validate` replaces that: a containment warning is closed only by evidence the system checks
itself, in order: (1) the host path is refused here (asked by use, not read from a flag); (2) no result of model-written code is recorded as
run on the host, and every such result is recorded as run in Docker; (3) a containment probe PASSED FOR THIS RELEASE (the probe's record
names the release and the runner's fingerprint, and the probe itself fails when the image holds another runner). All true: the open
warnings close with that evidence. Any false: they stay, and `blocked_by_probe` keeps generated code from running.
`repair_records` corrects the records the old rule mislabelled, by the evidence each row carries; it lists what it changed.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

FAIL_CLOSED_SINCE = datetime(2026, 10, 30)      # v2026.10.30.x: `sandbox.pick` refuses the host in an installed app and never falls back to it
RESULT = ("checked", "disputed")                # a calculation that produced a result
WORDS = {"docker": "ran in the sandbox (Docker)", "reviewed": "reviewed code ran; no model-written code did",
         "not_run": "did not run", "host": "ran on the host: NOT contained"}


def state_of(contained: Optional[bool], reviewed: bool = False) -> str:
    """docker | host | reviewed | not_run, from the stored value and whether the row is reviewed code."""
    if contained is True:
        return "docker"
    if contained is False:
        return "host"
    return "reviewed" if reviewed else "not_run"


def is_reviewed(check_json) -> bool:
    """A trusted study or a reviewed measure: the row's own check says no model-written code made the result."""
    try:
        cj = json.loads(check_json or "{}")
    except (TypeError, ValueError):
        return False
    return bool(cj.get("trusted") or cj.get("measure"))


def _meta_files(pm_dir: Path):
    from pflab.agents import workshop
    for p in sorted(workshop.folder(pm_dir).glob("*/meta.json")):
        try:
            yield p, json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue


def repair_records(con, pm_dir: Path, now: datetime) -> dict:
    """Correct rows the old `bool(None)` rule marked as run on the host. Reviewed code is `reviewed` by its own check. A try that produced no
    result in an installed app is `not_run`: the host path is refused there (proven by use, here) and has been since FAIL_CLOSED_SINCE, so
    False cannot have been true. A row with a RESULT of model-written code is never repaired: that is exactly what validation must examine."""
    from pflab.agents import sandbox as sb
    closed_here = sb.installed_app() and sb.host_refused()
    fixed = {"reviewed_code": 0, "never_ran": 0, "files": 0}
    for cid, at, status, cj in con.execute("SELECT calc_id, created_at, status, check_json FROM hq_calcs WHERE contained = FALSE").fetchall():
        if is_reviewed(cj):
            fixed["reviewed_code"] += 1
        elif closed_here and status not in RESULT and at is not None and at >= FAIL_CLOSED_SINCE:
            fixed["never_ran"] += 1
        else:
            continue
        con.execute("UPDATE hq_calcs SET contained = NULL WHERE calc_id = ?", [cid])
    for p, m in _meta_files(pm_dir):
        if m.get("contained") is False and closed_here and m.get("status") not in RESULT and str(m.get("created", ""))[:10] >= FAIL_CLOSED_SINCE.date().isoformat():
            m["contained"] = None
            p.write_text(json.dumps(m, indent=1, default=str), encoding="utf-8")
            fixed["files"] += 1
    if any(fixed.values()):
        from pflab.app import system
        system.record_check(con, "containment-records", True, now,
                            f"records corrected: {fixed['reviewed_code']} reviewed-code calculations, {fixed['never_ran']} tries that never ran, "
                            f"{fixed['files']} workshop files (the old rule stored 'nothing ran' as 'not contained')")
    return fixed


def _latest_probe(con) -> Optional[tuple]:
    return con.execute("SELECT ok, detail, checked_at FROM health_checks WHERE connector='sandbox' ORDER BY check_id DESC LIMIT 1").fetchone()


def validate(con, pm_dir: Path, now: datetime) -> dict:
    """The evidence, check by check. `proven` is true only when every check that applies here is true."""
    from pflab.agents import sandbox as sb
    repaired = repair_records(con, pm_dir, now)
    app = sb.installed_app()
    checks: Dict[str, dict] = {}
    checks["host_path_refused"] = {"applies": app, "ok": (sb.host_refused() if app else None),
                                   "says": "asking for the uncontained subprocess is refused here" if app else "the workshop's explicit setting allows it"}
    host = int(con.execute("SELECT count(*) FROM hq_calcs WHERE contained = FALSE").fetchone()[0])
    host += int(con.execute("SELECT count(*) FROM learn_attempts WHERE contained = FALSE").fetchone()[0])
    host += sum(1 for _, m in _meta_files(pm_dir) if m.get("contained") is False and m.get("status") in RESULT)
    checks["no_result_ran_on_the_host"] = {"applies": True, "ok": host == 0, "n": host,
                                           "says": f"{host} result(s) of model-written code recorded as run on the host"}
    unproven = sum(1 for st, cj in con.execute("SELECT status, check_json FROM hq_calcs WHERE contained IS NULL").fetchall()
                   if st in RESULT and not is_reviewed(cj))
    checks["every_model_result_ran_in_docker"] = {"applies": True, "ok": unproven == 0, "n": unproven,
                                                  "says": f"{unproven} result(s) of model-written code with no record of where it ran"}
    marker = sb.release_marker()
    probe = _latest_probe(con)
    ok = bool(probe and probe[0] and marker in (probe[1] or ""))
    checks["probe_passed_for_this_release"] = {
        "applies": True, "ok": ok, "marker": marker,
        "says": (f"the probe of {str(probe[2])[:16]} passed for {marker}" if ok else
                 "no containment probe has passed for this release yet (it runs when Docker is up; `pflab verify` does it too)" if not probe or not probe[0]
                 else f"the last passing probe ({str(probe[2])[:16]}) was for another release or runner than {marker}")}
    needed = [c for c in checks.values() if c["ok"] is not None]
    proven = all(c["ok"] for c in needed)
    return {"proven": proven, "checks": checks, "repaired": repaired, "at": str(now)[:16],
            "evidence": "; ".join(f"{k}: {'ok' if v['ok'] else 'n/a' if v['ok'] is None else 'FAILED'} ({v['says']})" for k, v in checks.items())}


def run(con, pm_dir: Path, now: datetime) -> dict:
    """Validate, keep the verdict (it colours the sandbox on the screen), and close the open containment warnings only when it is proven."""
    from pflab.agents import questions as qs
    from pflab.app import system
    res = validate(con, pm_dir, now)
    system.record_check(con, "containment", res["proven"], now, ("proven: " if res["proven"] else "NOT proven: ") + res["evidence"])
    res["closed"] = qs.close_with_evidence(con, "workshop:uncontained:%", res["evidence"], now) if res["proven"] else 0
    return res
