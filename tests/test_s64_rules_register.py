"""S64: the seven rule claims are registered before any run, scans pick up their claim, labels follow the learner's decision."""
from datetime import datetime

import duckdb
import pytest

from pflab.learner import claims, rules, templates as tp
from pflab.pm import store
from pflab.quant import scan

NOW = datetime(2026, 10, 27, 22, 0)


@pytest.fixture
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "pm.duckdb"))
    store.migrate(c)
    return c


def test_every_claim_fits_its_template_and_is_registered_once_with_its_protocol_file(con, tmp_path):
    for rule, direction, claim, quote in rules.RULE_CLAIMS:
        assert tp.check_params("rule_filter", {"rule": rule, "direction": direction, "months": 1}) is None
        assert claims.fits(claim, quote, "rule_filter", {"rule": rule}), rule
    out = rules.register_all(con, tmp_path / "protocols", NOW)
    assert set(out) == set(tp.RULES) and all(v.endswith(": registered") for v in out.values())
    assert len(list((tmp_path / "protocols").glob("claim_*.json"))) == 7
    again = rules.register_all(con, tmp_path / "protocols", NOW)
    assert all(v.endswith(": registered") and v.split(":")[0] == out[k].split(":")[0] for k, v in again.items())     # same claims, not new
    assert con.execute("SELECT count(*) FROM learn_claims WHERE template='rule_filter'").fetchone()[0] == 7


def test_status_follows_the_learners_decision_not_a_model(con, tmp_path):
    rules.register_all(con, tmp_path / "p", NOW)
    s = rules.status(con, "pe_above_50")
    assert s["label"] == "registered, test pending" and s["direction"] == "under"
    con.execute("UPDATE learn_claims SET status='failed', decision='fail', why='validation: t +0.4, under 1.65' "
                "WHERE json_extract_string(params_json, '$.rule')='pe_above_50'")
    assert rules.status(con, "pe_above_50")["label"] == "failed"
    con.execute("UPDATE learn_claims SET status='passed', decision='pass', why='both periods' "
                "WHERE json_extract_string(params_json, '$.rule')='below_sma200'")
    assert rules.status(con, "below_sma200")["label"] == "passed"
    assert rules.status(con, "no_such_rule")["label"] == "not tested"


def test_starter_scans_carry_their_rules_claim_and_label(con, tmp_path):
    scan.seed_starters(con, NOW)
    assert all(r["tested"] == "not tested" for r in scan.listing(con))
    rules.register_all(con, tmp_path / "p", NOW)
    by = {r["name"]: r for r in scan.listing(con)}
    assert by["Near its 52-week low"]["tested"] == "test pending" and "registered for testing" in by["Near its 52-week low"]["label"]
    assert by["Alpha turned negative"]["tested"] == "not tested"                  # no rule test for it: stays "not tested"
    con.execute("UPDATE learn_claims SET status='passed', decision='pass' WHERE json_extract_string(params_json, '$.rule')='below_sma200'")
    assert {r["name"]: r["label"] for r in scan.listing(con)}["Below its 200-day average"] == "tested: passed"
    sid = scan.make_scan(con, "mine", "volume_spike:2", "holdings", "investor", NOW)                  # a new scan picks its claim up
    assert [r for r in scan.listing(con) if r["scan_id"] == sid][0]["tested"] == "test pending"


def test_the_pe_flag_shows_the_test_status():
    from pflab.hq import valuation as vl
    flag = vl.flags(62.0, 30.0, {"pe": 22.0}, True, {"ratio": 1.6, "vol_3m_pct": 30, "vol_3y_pct": 19}, -0.3,
                    {"pe_above_50": {"label": "failed", "claim_id": 9, "why": "development: t 0.3"}})[0]
    assert flag["rule"] == "P/E above 50" and flag["status"].startswith("TESTED by the learner (claim #9): failed")
    assert "not tested" in vl.flags(62.0, 30.0, None, None, {"ratio": None}, None)[0]["status"]
