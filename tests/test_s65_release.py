r"""S65 Phase 8 (the split): release.toml overrides the environment, the workshop is beta by structure, and the beta guard blocks
Telegram, paid calls and task registration unless told."""
import os
from datetime import datetime
from pathlib import Path

import pytest

from pflab import features, guard, release
from pflab.pm import store
from pflab.service import bot, telegram as tgm


def app_root(tmp_path, channel="stable") -> Path:
    root = tmp_path / "PortfolioLabApp" / "app"
    root.mkdir(parents=True)
    release.write(root, tmp_path / "PortfolioLabApp", "v2026.10.28", channel_=channel)
    return root


def test_a_checkout_with_no_release_file_is_the_workshop_and_beta(tmp_path, monkeypatch):
    monkeypatch.delenv("PFLAB_CHANNEL", raising=False)
    assert release.channel(tmp_path) == "beta" and not release.is_app(tmp_path) and release.load(tmp_path) is None
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    assert release.channel(tmp_path) == "stable"                                   # the suite and a developer's choice
    monkeypatch.setenv("PFLAB_CHANNEL", "nonsense")
    assert release.channel(tmp_path) == "beta"                                     # unknown: the stricter one


def test_the_release_file_wins_over_the_environment_and_sets_the_paths(tmp_path, monkeypatch):
    root = app_root(tmp_path)
    monkeypatch.setenv("PFLAB_CHANNEL", "beta")
    monkeypatch.setenv("PFLAB_DATA_DIR", r"D:\portfolio_lab\data")                 # a user-level variable still pointing at the workshop
    monkeypatch.setenv("PFLAB_PM_DIR", r"D:\portfolio_lab\pm")
    assert release.channel(root) == "stable" and release.is_app(root)
    assert release.apply(root) is True
    assert os.environ["PFLAB_CHANNEL"] == "stable"
    assert Path(os.environ["PFLAB_DATA_DIR"]) == tmp_path / "PortfolioLabApp" / "data"
    assert store.pm_dir() == tmp_path / "PortfolioLabApp" / "pm"
    r = release.load(root)
    assert r["app"]["tag"] == "v2026.10.28" and r["app"]["previous_tag"] == "" and Path(r["app"]["folder"]) == tmp_path / "PortfolioLabApp"


def test_without_a_release_file_nothing_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", "keep")
    assert release.apply(tmp_path) is False and os.environ["PFLAB_PM_DIR"] == "keep"


def test_a_bad_channel_is_refused_when_writing(tmp_path):
    with pytest.raises(ValueError):
        release.write(tmp_path, tmp_path, "v1", channel_="nightly")


def test_features_follow_the_release_channel(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "ROOT", app_root(tmp_path))                        # the app: stable, beta features off
    assert features.channel() == "stable" and not features.enabled("us_sleeve", {})
    monkeypatch.setattr(release, "ROOT", tmp_path / "workshop")
    monkeypatch.delenv("PFLAB_CHANNEL", raising=False)
    assert features.channel() == "beta" and features.enabled("us_sleeve", {})


# --- the guard ---------------------------------------------------------------------------------------------------------------

@pytest.fixture
def beta(monkeypatch):
    monkeypatch.setenv("PFLAB_CHANNEL", "beta")


def test_the_beta_channel_blocks_everything_outward_until_told(beta, monkeypatch):
    for kind in ("telegram", "paid", "register"):
        assert "workshop" in guard.blocked(kind)
        with pytest.raises(guard.OutwardBlocked):
            guard.require(kind)
    guard.set_flags(paid=True)
    assert guard.blocked("paid") is None and guard.blocked("telegram") and guard.blocked("register")
    monkeypatch.setenv("PFLAB_LIVE", "1")
    assert guard.blocked("telegram") is None
    assert guard.blocked("register")                                                    # no flag ever registers a task
    with pytest.raises(ValueError):
        guard.blocked("nonsense")
    monkeypatch.delenv("PFLAB_PAID")


def test_the_stable_channel_is_not_blocked(monkeypatch):
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    assert all(guard.blocked(k) is None for k in ("telegram", "paid", "register"))


class Sec:
    def has(self, s, k):
        return True

    def get(self, s, k):
        return "x"


def test_the_workshop_sends_no_telegram_and_the_messages_stay_pending(beta, tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    tgm.enqueue(con, "a held alert", "guard", dedup_key="k1", now=datetime(2026, 10, 28))
    con.execute("UPDATE outbox SET status='pending'")
    out = tgm.flush(con, tgm.make_sender(Sec()), datetime(2026, 10, 28))
    assert out["sent"] == 0 and out["still_pending"] == 1 and "workshop" in out["error"]
    assert con.execute("SELECT status, attempts FROM outbox").fetchone() == ("pending", 0)            # no attempt burned
    with pytest.raises(guard.OutwardBlocked):
        tgm.requests_transport("https://api.telegram.org/botX/sendMessage", {})
    with pytest.raises(guard.OutwardBlocked):
        bot.poll_transport("https://api.telegram.org/botX/getUpdates", {})


def test_a_fake_transport_still_works_in_the_workshop(beta, tmp_path):
    seen = []
    send = tgm.make_sender(Sec(), transport=lambda url, payload: (seen.append(payload) or (200, {"ok": True})))
    send("hello")
    assert seen and seen[0]["text"] == "hello"                                          # tests and drills use their own transport


def test_the_workshop_makes_no_paid_call_and_has_its_own_cap(beta, tmp_path):
    from pflab.agents import analyst as an
    with pytest.raises(guard.OutwardBlocked, match="--paid"):
        an.make_client(None)
    cfg = tmp_path / "api_budget.toml"
    cfg.write_text("[api]\nmonthly_cap_rupees = 2500\ndev_monthly_cap_rupees = 40\n", encoding="utf-8")
    assert an.config(cfg)["cap"] == 40.0                                                # the workshop counts against its own line
    cfg.write_text("[api]\nmonthly_cap_rupees = 2500\n", encoding="utf-8")
    assert an.config(cfg)["cap"] == 0.0                                                 # default 0: raised only by him


def test_the_app_keeps_the_monthly_cap(monkeypatch, tmp_path):
    from pflab.agents import analyst as an
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    cfg = tmp_path / "api_budget.toml"
    cfg.write_text("[api]\nmonthly_cap_rupees = 2500\ndev_monthly_cap_rupees = 40\n", encoding="utf-8")
    assert an.config(cfg)["cap"] == 2500.0


def test_the_cli_flags_lift_the_guard_for_that_process_only(beta, monkeypatch, tmp_path):
    from pflab import cli
    monkeypatch.setenv("PFLAB_SECRETS_FILE", str(tmp_path / "none.toml"))                # the command run is `setup status`: names only
    monkeypatch.delenv("PFLAB_PAID", raising=False)
    monkeypatch.delenv("PFLAB_LIVE", raising=False)
    assert guard.blocked("paid")
    cli.main(["--paid", "--live", "setup", "status"])
    assert guard.blocked("paid") is None and guard.blocked("telegram") is None
    monkeypatch.delenv("PFLAB_PAID")
    monkeypatch.delenv("PFLAB_LIVE")


def test_the_phone_does_not_poll_from_the_workshop(beta, tmp_path):
    from pflab.hq import phone
    rt = type("RT", (), {"settings": {"telegram_send": True}, "secrets": Sec()})()
    assert phone.poll_once(rt) == 0


def test_every_source_file_is_in_git():
    """The clean-room install found src/pflab/pm/secrets_setup.py hidden by a `secrets*` ignore rule: every .py the code imports must be tracked."""
    import subprocess
    root = Path(__file__).resolve().parents[1]
    try:
        tracked = set(subprocess.run(["git", "ls-files", "src", "tools"], cwd=root, capture_output=True, text=True, check=True).stdout.split())
    except Exception:
        pytest.skip("not a git checkout")
    on_disk = {p.relative_to(root).as_posix() for d in ("src", "tools") for p in (root / d).rglob("*.py") if "__pycache__" not in p.parts}
    assert sorted(on_disk - tracked) == []


def test_the_lock_file_is_what_the_tests_run_on():
    """The app once got DuckDB 2.0 while the tests ran on 1.5 (found in the switch-over): the app installs requirements.lock, which must
    match the libraries this suite is running with."""
    from importlib import metadata
    root = Path(__file__).resolve().parents[1]
    pins = dict(l.split("==", 1) for l in (root / "requirements.lock").read_text(encoding="utf-8").splitlines() if "==" in l and not l.startswith("#"))
    for name in ("duckdb", "pandas", "numpy", "pyarrow", "fastapi", "anthropic", "statsmodels", "openpyxl", "pypdf", "langchain-core"):
        assert pins.get(name) == metadata.version(name), name
