"""Trusted calculations (S68): deterministic code that ships with the application and is registered here by name, so a result is kept in
`hq_calcs` like a sandbox calculation (parameters, the input data with its hash, the result, the library versions) and can be REPRODUCED by the
independent reviewer: the name and parameters are rerun on the kept inputs and every difference listed.

A trusted calculation is not "checked by a second model": it is reviewed code with tests, and the reviewer reruns it. Its place in the three
evaluation contracts is stated in each result (`kind`: calculation or scenario). A hypothesis with no trusted function and no contract goes to the
sandbox as a CALCULATION, or is refused as unsupported; it never borrows another function.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Callable, Dict, Optional

import pandas as pd

from pflab.quant import ipo_policy, policies


def _policies(inputs: Dict[str, pd.DataFrame], params: dict) -> dict:
    return policies.run(**params)


def _ipo(inputs: Dict[str, pd.DataFrame], params: dict) -> dict:
    return ipo_policy.run(inputs["listings"], **params)


TRUSTED: Dict[str, Callable] = {"policy_scenarios": _policies, "ipo_policy": _ipo}
KIND = {"policy_scenarios": "scenario", "ipo_policy": "calculation"}


def plain(x):
    """JSON round trip: what was kept is what a rerun is compared with (numpy numbers and dates become plain values)."""
    return json.loads(json.dumps(x, default=lambda o: float(o) if hasattr(o, "__float__") else str(o), sort_keys=True))


def rerun(name: str, params: dict, inputs: Dict[str, pd.DataFrame]) -> dict:
    if name not in TRUSTED:
        raise LookupError(f"no trusted calculation called {name!r}")
    return plain(TRUSTED[name](inputs, params))


def record(con, cid: Optional[int], now: datetime, name: str, question: str, params: dict, inputs: Dict[str, pd.DataFrame], result: dict) -> int:
    """Keep a trusted calculation as a `hq_calcs` row. Returns the calculation id."""
    import hashlib
    from pflab.hq import cases
    kid = cases._id(con, "hq_calcs", "calc_id")
    code = f"trusted:{name}"
    res = plain(result)
    con.execute("INSERT INTO hq_calcs (calc_id, case_id, created_at, question, code, code_sha, alt_code, datasets_json, params_json, result_json, "
                "status, contained, attempts, check_json, workshop_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [kid, cid, now, question[:600], code, hashlib.sha256(code.encode()).hexdigest(), None, json.dumps(sorted(inputs)),
                 json.dumps(params, default=str, sort_keys=True), json.dumps(res), "checked", False, 1,
                 json.dumps({"trusted": True, "kind": KIND.get(name), "version": res.get("version"), "test": {}}), f"trusted:{name}"])
    con.execute("UPDATE hq_calcs SET versions_json=? WHERE calc_id=?", [json.dumps(cases.runtime_versions()), kid])
    cases.snapshot_inputs(con, kid, inputs)
    if cid is not None:
        cases.add_evidence(con, cid, now, f"{KIND.get(name, 'calculation')} ({name}, trusted code, rerun by the reviewer): " + question[:200],
                           stance="neutral", kind="calculation", source_id=f"calc:{kid}", source_kind="calculation", calc_id=kid,
                           data={"datasets": sorted(inputs), "confirmed": "agrees", "trusted": True})
    return kid
