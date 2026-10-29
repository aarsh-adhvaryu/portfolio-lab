"""S1: store migrations, secrets loader, instrument master."""
from datetime import date

import duckdb
import pandas as pd
import pytest

import pandas as pd
from pflab.pm import instruments as ins
from pflab.pm import secrets as sec
from pflab.pm import store

NAVALL = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Flexi Cap Fund)

Axis Mutual Fund

100;INF000A01AA1;-;Axis Flexi;Direct Plan;Growth Option;10.5;05-Oct-2026
101;INF000A01AB9;INF000A01AC7;Axis Flexi;Direct Plan;IDCW Option;9.5;05-Oct-2026

Open Ended Schemes(Exchange Traded Funds (ETFs) - Gold ETF)

Some Mutual Fund

200;INF000B01AA1;-;Some Gold ETF;;;70.0;05-Oct-2026
"""


# --- store -----------------------------------------------------------------

def test_pm_dir_env_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    assert store.pm_dir() == tmp_path
    monkeypatch.delenv("PFLAB_PM_DIR")
    assert str(store.pm_dir()).lower().endswith("portfolio_lab\\pm") or \
        str(store.pm_dir()).replace("\\", "/").endswith("portfolio_lab/pm")


def test_migrations_idempotent(tmp_path):
    p = tmp_path / "x" / "l.duckdb"
    c = store.connect(p)
    n = c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
    assert n == len(store.MIGRATIONS)
    assert store.migrate(c) == []
    c.close()
    c = store.connect(p)  # reopen: nothing re-applied
    assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == n


def test_edited_migration_raises(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    edited = [(1, "instruments_accounts", "SELECT 1")]
    with pytest.raises(RuntimeError, match="edited"):
        store.migrate(c, edited)


def test_failed_migration_rolls_back(tmp_path):
    c = duckdb.connect(str(tmp_path / "l.duckdb"))
    bad = [(1, "bad", "CREATE TABLE t (a INT); SELECT * FROM nope;")]
    with pytest.raises(Exception):
        store.migrate(c, bad)
    assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 0
    assert c.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='t'").fetchone()[0] == 0


# --- secrets ---------------------------------------------------------------

def _write(tmp_path, text='[kite]\napi_key = "KEY123456"\napi_secret = "SECRET987654"\n'):
    p = tmp_path / "secrets.toml"
    p.write_text(text)
    return p


def test_secrets_never_in_repr_or_str(tmp_path):
    s = sec.load(_write(tmp_path))
    for text in (repr(s), str(s), f"{s}", f"{[s]}"):
        assert "KEY123456" not in text and "SECRET987654" not in text
    assert s.names() == ["kite.api_key", "kite.api_secret"]
    assert s.get("kite", "api_key") == "KEY123456"


def test_secrets_redact_scrubs_values(tmp_path):
    s = sec.load(_write(tmp_path))
    out = s.redact("calling with KEY123456 and SECRET987654 done")
    assert "KEY123456" not in out and "SECRET987654" not in out and sec.MASK in out


def test_missing_secret_error_has_no_value(tmp_path):
    s = sec.load(_write(tmp_path))
    with pytest.raises(sec.SecretsError) as e:
        s.get("telegram", "token")
    assert "KEY123456" not in str(e.value)


def test_secrets_file_missing(tmp_path):
    with pytest.raises(sec.SecretsError, match="no secrets file"):
        sec.load(tmp_path / "nope.toml")


def test_secrets_refused_inside_onedrive(tmp_path):
    d = tmp_path / "OneDrive" / "docs"
    d.mkdir(parents=True)
    with pytest.raises(sec.SecretsError, match="OneDrive"):
        sec.load(_write(d))


def test_secrets_refused_inside_git_repo(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(sec.SecretsError, match="git repo"):
        sec.load(_write(tmp_path / "repo"))


def test_secrets_default_path_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PFLAB_SECRETS_FILE", str(tmp_path / "s.toml"))
    assert sec.default_path() == tmp_path / "s.toml"


# --- tax class for every ISIN type -----------------------------------------

@pytest.mark.parametrize("kwargs,asset,tax", [
    (dict(isin="INE999G01012", instrument_type="STK"), "equity", ins.EQUITY),
    (dict(isin="INF204KB14I2", instrument_type="ETF", category="Exchange Traded Funds (ETFs) - Equity ETF"),
     "etf", ins.EQUITY),
    (dict(isin="INF209KB18D3", instrument_type="ETF", category="Exchange Traded Funds (ETFs) - Gold ETF"),
     "etf", ins.LISTED_NONEQUITY),
    (dict(isin="INF000000000", instrument_type="ETF"), "etf", ins.REVIEW),
    (dict(isin="INE000000013", instrument_type="REIT"), "reit", ins.BUSINESS_TRUST),
    (dict(isin="INE000000021", instrument_type="INVIT"), "invit", ins.BUSINESS_TRUST),
    (dict(isin="INF000A01AA1", category="Equity Scheme - Flexi Cap Fund"), "mutual_fund", ins.EQUITY),
    (dict(isin="INF000A01AA2", category="Debt Scheme - Liquid Fund"), "mutual_fund", ins.DEBT_MF),
    (dict(isin="INF000A01AA3", category="Overseas Fund of Funds - Fund of Funds investing overseas"),
     "mutual_fund", ins.OTHER_MF),
    (dict(isin="IN0020150028", series="GB"), "sgb", ins.SGB),
    (dict(isin="IN0020150028", name="SGB 2.50% 2025 SR-I"), "sgb", ins.SGB),
    (dict(isin="IN0020230010", series="GS"), "bond", ins.LISTED_NONEQUITY),
    (dict(isin="INE002A07809", listed=True), "bond", ins.LISTED_NONEQUITY),
    (dict(isin="INE002A07809", listed=False), "bond", ins.UNLISTED_DEBT),
    (dict(isin="INE002A07809"), "bond", ins.REVIEW),
    (dict(isin="ZZ0000000000"), "unknown", ins.REVIEW),
])
def test_classify_every_isin_type(kwargs, asset, tax):
    a, t, why = ins.classify(**kwargs)
    assert (a, t) == (asset, tax) and why
    assert t in ins.TAX_CLASSES


def test_hybrids_not_guessed():
    for cat in ("Hybrid Scheme - Balanced Hybrid Fund",
                "Hybrid Scheme - Dynamic Asset Allocation or Balanced Advantage",
                "Hybrid Scheme - Multi Asset Allocation", "Fund of Funds Scheme (Domestic) - x"):
        assert ins.scheme_class(cat)[1] == ins.REVIEW
    assert ins.scheme_class("Hybrid Scheme - Arbitrage Fund")[1] == ins.EQUITY
    assert ins.scheme_class("Hybrid Scheme - Conservative Hybrid Fund")[1] == ins.DEBT_MF
    assert ins.scheme_class("Something New - Unseen")[1] == ins.REVIEW


# --- AMFI parse and master -------------------------------------------------

def test_parse_navall():
    df = ins.parse_navall(NAVALL)
    assert list(df.scheme_code) == ["100", "101", "200"]
    r = df.set_index("scheme_code")
    assert r.loc["101", "isin_2"] == "INF000A01AC7" and pd.isna(r.loc["100", "isin_2"])
    assert r.loc["100", "amc"] == "Axis Mutual Fund"
    assert r.loc["200", "category"] == "Exchange Traded Funds (ETFs) - Gold ETF"
    assert r.loc["100", "nav_date"] == date(2026, 10, 5) and r.loc["100", "nav"] == 10.5


def _panel():
    return pd.DataFrame([
        dict(isin="INE999G01012", symbol="GADGETCO", series="EQ", instrument_type="STK",
             valid_from=date(2004, 1, 1), valid_to=date(2026, 9, 16)),
        dict(isin="INF000B01AA1", symbol="GOLDX", series="EQ", instrument_type="ETF",
             valid_from=date(2020, 1, 1), valid_to=date(2026, 9, 16)),
        dict(isin="NSE:OLDCO", symbol="OLDCO", series="EQ", instrument_type="STK",
             valid_from=date(2005, 1, 1), valid_to=date(2008, 1, 1)),
    ])


def test_build_master_and_load(tmp_path):
    amfi = ins.parse_navall(NAVALL)
    m = ins.build_master(_panel(), amfi, names={"INE999G01012": "Gadget Industries Limited"},
                         sectors={"INE999G01012": "Oil Gas"})
    r = m.set_index("isin")
    assert r.loc["INE999G01012", "name"] == "Gadget Industries Limited"
    assert r.loc["INF000B01AA1", "tax_class"] == ins.LISTED_NONEQUITY   # panel ETF typed by AMFI
    assert r.loc["INF000B01AA1", "source"] == "panel+amfi"
    assert r.loc["NSE:OLDCO", "key_kind"] == "synthetic"
    # AMFI-only ISINs: both of scheme 101's ISINs and scheme 100's one
    assert {"INF000A01AA1", "INF000A01AB9", "INF000A01AC7"} <= set(m["isin"])
    assert m["isin"].is_unique and m["tax_class"].isin(ins.TAX_CLASSES).all()

    con = store.connect(tmp_path / "l.duckdb")
    ins.load_into_store(con, m, amfi, "sha")
    ins.load_into_store(con, m, amfi, "sha")  # rebuild replaces, not duplicates
    assert con.execute("SELECT count(*) FROM instruments").fetchone()[0] == len(m)
    assert con.execute("SELECT count(*) FROM amfi_schemes").fetchone()[0] == 3


def test_cli_pm_init_and_instruments(monkeypatch, tmp_path, capsys):
    from pflab import cli
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    assert cli.main(["pm", "init"]) == 0
    assert "schema v44" in capsys.readouterr().out
    assert cli.main(["pm", "instruments"]) == 0
    assert "amfi schemes: 0" in capsys.readouterr().out


def test_other_etf_split_by_name_only_for_other_etfs():
    cat = "Exchange Traded Funds (ETFs) - Other ETF"
    assert ins.scheme_class(cat, "Nippon India ETF Gold BeES")[1] == ins.LISTED_NONEQUITY
    assert ins.scheme_class(cat, "ICICI Prudential Liquid ETF")[1] == ins.DEBT_MF
    assert ins.scheme_class(cat, "Nippon India ETF Nifty 50 BeES")[1] == ins.REVIEW
    # an equity scheme whose name says gold is not retyped
    assert ins.scheme_class("Equity Scheme - Sectoral/ Thematic", "Gold Miners Fund")[1] == ins.EQUITY


def test_register_missing_classifies_sgb_and_new_listing_and_keeps_known(tmp_path):
    from pflab.pm import instruments as ins
    con = store.connect(tmp_path / "l.duckdb")
    added = ins.register_missing(con, [
        {"isin": "IN0020200000", "name": "Government of India SGB 2020-21 SERIES XII", "series": "GB", "listed": True},
        {"isin": "INE000X01010", "symbol": "NEWCO", "listed": True},
        {"isin": "INE000X01010", "symbol": "NEWCO"},
        {"isin": "IN9999999999", "name": "MYSTERY"}], "test")
    got = {r["isin"]: (r["asset_class"], r["tax_class"]) for r in added}
    assert got == {"IN0020200000": ("sgb", "SGB"), "INE000X01010": ("equity", "EQUITY"), "IN9999999999": ("unknown", "REVIEW")}
    assert ins.register_missing(con, [{"isin": "IN0020200000", "name": "x"}], "again") == []
