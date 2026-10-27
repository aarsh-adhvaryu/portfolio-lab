"""Portfolio Manager ledger store: one DuckDB file under `PFLAB_PM_DIR`,
schema by numbered migrations (PLAN §4).

A migration is applied once and recorded with its SHA. Editing an applied
migration raises: add a new one instead.
"""
from __future__ import annotations

import hashlib
import os
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import duckdb

DEFAULT_PM_DIR = r"D:\portfolio_lab\pm"  # PLAN §10, 2026-10-06
DB_NAME = "ledger.duckdb"

MIGRATIONS = [
    (1, "instruments_accounts", """
    CREATE TABLE instruments (
        isin VARCHAR PRIMARY KEY,
        key_kind VARCHAR NOT NULL,          -- isin | synthetic (pre-2011, no ISIN)
        asset_class VARCHAR NOT NULL,
        tax_class VARCHAR NOT NULL,
        tax_class_reason VARCHAR,
        listed BOOLEAN,
        symbol VARCHAR,
        name VARCHAR,
        issuer VARCHAR,
        sector VARCHAR,
        scheme_code VARCHAR,
        category VARCHAR,
        valid_from DATE,
        valid_to DATE,
        successor_isin VARCHAR,
        source VARCHAR NOT NULL,
        built_at TIMESTAMP NOT NULL
    );
    CREATE TABLE amfi_schemes (
        scheme_code VARCHAR PRIMARY KEY,
        isin_1 VARCHAR,
        isin_2 VARCHAR,
        name VARCHAR NOT NULL,
        plan VARCHAR,
        option VARCHAR,
        amc VARCHAR,
        category VARCHAR,
        nav DOUBLE,
        nav_date DATE,
        source_doc_sha VARCHAR NOT NULL,
        ingested_at TIMESTAMP NOT NULL
    );
    CREATE TABLE accounts (
        account_id VARCHAR PRIMARY KEY,
        kind VARCHAR NOT NULL,              -- demat | folio | bank | physical
        provider VARCHAR,
        dp_or_folio VARCHAR,
        opened DATE,
        closed DATE,
        dormant BOOLEAN DEFAULT FALSE,
        read_only BOOLEAN DEFAULT FALSE
    );
    """),
    (2, "ledger_core", """
    CREATE TABLE events (
        event_id BIGINT PRIMARY KEY,
        kind VARCHAR NOT NULL,
        account_id VARCHAR NOT NULL,
        trade_date DATE NOT NULL,
        isin VARCHAR,
        qty DOUBLE,
        price DOUBLE,
        amount DOUBLE,
        fees_json VARCHAR,
        ref VARCHAR,
        source_doc_sha VARCHAR,
        tax_class VARCHAR,
        counter_account VARCHAR,
        ingested_at TIMESTAMP NOT NULL
    );
    CREATE TABLE lots (
        lot_id BIGINT, account_id VARCHAR, isin VARCHAR, acq_date DATE, qty DOUBLE,
        cost_per_unit DOUBLE, tax_class VARCHAR, origin_event BIGINT
    );
    CREATE TABLE cash_ledger (
        account_id VARCHAR, date DATE, amount DOUBLE, kind VARCHAR, ref VARCHAR, event_id BIGINT
    );
    CREATE TABLE income (
        isin VARCHAR, account_id VARCHAR, kind VARCHAR, date DATE, gross DOUBLE, tds DOUBLE,
        net DOUBLE, event_id BIGINT
    );
    CREATE TABLE fees (
        event_id BIGINT, account_id VARCHAR, date DATE, kind VARCHAR, amount DOUBLE
    );
    """),
    (3, "prices", """
    CREATE TABLE prices (
        isin VARCHAR NOT NULL, date DATE NOT NULL, close DOUBLE NOT NULL, series VARCHAR,
        source VARCHAR NOT NULL, fetched_at TIMESTAMP NOT NULL,
        PRIMARY KEY (isin, date, source)
    );
    CREATE TABLE navs (
        isin VARCHAR NOT NULL, scheme_code VARCHAR, date DATE NOT NULL, nav DOUBLE NOT NULL,
        source VARCHAR NOT NULL, fetched_at TIMESTAMP NOT NULL,
        PRIMARY KEY (isin, date, source)
    );
    CREATE TABLE gold_rates (
        date DATE NOT NULL, session VARCHAR NOT NULL, metal VARCHAR NOT NULL, rate DOUBLE NOT NULL,
        unit VARCHAR NOT NULL, source VARCHAR NOT NULL, fetched_at TIMESTAMP NOT NULL,
        PRIMARY KEY (date, session, metal)
    );
    CREATE TABLE live_quotes (
        isin VARCHAR NOT NULL, ts TIMESTAMP NOT NULL, ltp DOUBLE NOT NULL, source VARCHAR NOT NULL,
        PRIMARY KEY (isin, ts)
    );
    """),
    (4, "corporate_actions", """
    ALTER TABLE events ADD COLUMN params_json VARCHAR;
    CREATE TABLE corporate_actions_applied (
        isin VARCHAR, ex_date DATE, kind VARCHAR, params_json VARCHAR, event_id BIGINT,
        accounts VARCHAR, applied_at TIMESTAMP, source_doc_sha VARCHAR
    );
    """),
    (5, "bonds_sgb", """
    CREATE TABLE bonds (
        isin VARCHAR PRIMARY KEY, name VARCHAR, issuer VARCHAR, issue_date DATE NOT NULL,
        maturity_date DATE NOT NULL, coupon_rate DOUBLE NOT NULL, frequency INTEGER NOT NULL,
        day_count VARCHAR NOT NULL, face_value DOUBLE NOT NULL, listed BOOLEAN,
        source VARCHAR NOT NULL, loaded_at TIMESTAMP NOT NULL
    );
    CREATE TABLE sgb_series (
        isin VARCHAR PRIMARY KEY, series VARCHAR, issue_date DATE NOT NULL, maturity_date DATE NOT NULL,
        issue_price_per_gram DOUBLE NOT NULL, interest_rate DOUBLE NOT NULL,
        source VARCHAR NOT NULL, loaded_at TIMESTAMP NOT NULL
    );
    """),
    (6, "tax_years_lookthrough", """
    CREATE TABLE tax_years (
        fy INTEGER NOT NULL, regime VARCHAR NOT NULL, components_json VARCHAR NOT NULL,
        computed_at TIMESTAMP NOT NULL, rule_rows_used VARCHAR, PRIMARY KEY (fy, regime, computed_at)
    );
    CREATE TABLE carry_forward (
        origin_fy INTEGER NOT NULL, character VARCHAR NOT NULL, amount DOUBLE NOT NULL,
        expires_fy INTEGER NOT NULL, as_of_fy INTEGER NOT NULL, source VARCHAR
    );
    CREATE TABLE fund_holdings (
        fund_isin VARCHAR NOT NULL, as_of DATE NOT NULL, isin VARCHAR, name VARCHAR, industry VARCHAR,
        pct_nav DOUBLE NOT NULL, market_value DOUBLE, kind VARCHAR, source_doc_sha VARCHAR,
        ingested_at TIMESTAMP NOT NULL
    );
    """),
    (7, "quarterly_results", """
    CREATE TABLE quarterly_results (
        scrip_code VARCHAR NOT NULL, quarter_end DATE NOT NULL, audited BOOLEAN,
        revenue DOUBLE, other_income DOUBLE, total_income DOUBLE, expenditure DOUBLE,
        finance_costs DOUBLE, depreciation DOUBLE, pbt DOUBLE, tax DOUBLE, net_profit DOUBLE,
        eps_basic DOUBLE, eps_diluted DOUBLE,
        usable_from DATE NOT NULL, date_source VARCHAR NOT NULL, source VARCHAR NOT NULL,
        fetched_at TIMESTAMP NOT NULL, PRIMARY KEY (scrip_code, quarter_end)
    );
    """),
    (8, "ipo_applications", """
    CREATE TABLE ipo_applications (
        ipo_id VARCHAR PRIMARY KEY, account_id VARCHAR, category VARCHAR, bid_qty DOUBLE, bid_price DOUBLE,
        amount_blocked DOUBLE, blocked_on DATE, mandate_ref VARCHAR, status VARCHAR, allotted_qty DOUBLE,
        allotted_amount DOUBLE, refund_on DATE, listed_on DATE, isin VARCHAR
    );
    """),
    (9, "proposals_targets", """
    CREATE TABLE proposals (
        proposal_id INTEGER PRIMARY KEY, kind VARCHAR NOT NULL, as_of DATE NOT NULL, evidence_sha VARCHAR NOT NULL,
        evidence_json VARCHAR NOT NULL, alternatives_json VARCHAR, created_at TIMESTAMP NOT NULL
    );
    CREATE TABLE decisions (
        proposal_id INTEGER NOT NULL, choice VARCHAR NOT NULL, reason VARCHAR, decided_at TIMESTAMP NOT NULL
    );
    CREATE TABLE targets (
        bucket VARCHAR NOT NULL, target_weight DOUBLE NOT NULL, soft_band DOUBLE NOT NULL, hard_band DOUBLE NOT NULL,
        effective_from DATE NOT NULL, set_by VARCHAR, buy_json VARCHAR
    );
    CREATE SEQUENCE proposal_seq START 1;
    """),
    (10, "alerts_sent", """
    CREATE TABLE alerts_sent (
        event_id VARCHAR PRIMARY KEY, flag VARCHAR, isin VARCHAR, sent_at TIMESTAMP NOT NULL,
        channel VARCHAR, headline VARCHAR
    );
    """),
    (11, "service", """
    CREATE SEQUENCE job_run_seq START 1;
    CREATE SEQUENCE outbox_seq START 1;
    CREATE TABLE job_runs (
        run_id INTEGER PRIMARY KEY, job VARCHAR NOT NULL, slot TIMESTAMP, started_at TIMESTAMP NOT NULL,
        finished_at TIMESTAMP, status VARCHAR NOT NULL, detail VARCHAR
    );
    CREATE TABLE outbox (
        msg_id INTEGER PRIMARY KEY, created_at TIMESTAMP NOT NULL, kind VARCHAR, text VARCHAR NOT NULL,
        dedup_key VARCHAR UNIQUE, status VARCHAR NOT NULL, attempts INTEGER NOT NULL, last_error VARCHAR,
        sent_at TIMESTAMP
    );
    """),
    (12, "recon_breaks", """
    CREATE TABLE recon_breaks (
        run_id VARCHAR NOT NULL, source_a VARCHAR, source_b VARCHAR, isin VARCHAR, account_id VARCHAR,
        field VARCHAR, a_value DOUBLE, b_value DOUBLE, status VARCHAR, note VARCHAR, created_at TIMESTAMP NOT NULL
    );
    """),
    (13, "llm_runs", """
    CREATE SEQUENCE llm_run_seq START 1;
    CREATE TABLE llm_runs (
        run_id INTEGER PRIMARY KEY, started_at TIMESTAMP NOT NULL, role VARCHAR, model VARCHAR NOT NULL,
        model_digest VARCHAR, prompt_name VARCHAR, prompt_sha VARCHAR, sources_json VARCHAR, guard_result VARCHAR,
        attempts INTEGER, tokens_in INTEGER, tokens_out INTEGER, seconds DOUBLE, status VARCHAR, note VARCHAR
    );
    """),
    (14, "fixed_deposits", """
    CREATE TABLE fds (
        fd_id VARCHAR PRIMARY KEY, bank VARCHAR, principal DOUBLE NOT NULL, rate DOUBLE NOT NULL,
        term_start DATE NOT NULL, maturity DATE NOT NULL, maturity_amount DOUBLE NOT NULL, payout VARCHAR,
        instruction VARCHAR, status VARCHAR NOT NULL, closed_on DATE, closing_amount DOUBLE, prev_rate DOUBLE,
        anchor_date DATE, anchor_value DOUBLE, opened DATE, source VARCHAR NOT NULL, loaded_at TIMESTAMP NOT NULL
    );
    CREATE TABLE fd_interest (
        fd_id VARCHAR NOT NULL, fy INTEGER NOT NULL, paid DOUBLE NOT NULL, accrued DOUBLE NOT NULL,
        tds DOUBLE NOT NULL, source VARCHAR NOT NULL, loaded_at TIMESTAMP NOT NULL, PRIMARY KEY (fd_id, fy)
    );
    """),    (15, "fd_purpose", """
    ALTER TABLE fds ADD COLUMN purpose VARCHAR;
    """),    (16, "knowledge_graph", """
    CREATE TABLE kg_nodes (
        node_id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, name VARCHAR, attrs_json VARCHAR,
        updated_at TIMESTAMP NOT NULL
    );
    CREATE TABLE kg_edges (
        src VARCHAR NOT NULL, rel VARCHAR NOT NULL, dst VARCHAR NOT NULL, valid_from TIMESTAMP NOT NULL,
        valid_to TIMESTAMP, source_kind VARCHAR NOT NULL, source_ref VARCHAR, attrs_json VARCHAR,
        ingested_at TIMESTAMP NOT NULL, PRIMARY KEY (src, rel, dst, valid_from)
    );
    CREATE TABLE kg_docs (
        doc_id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, url VARCHAR, title VARCHAR, source VARCHAR,
        published_at TIMESTAMP NOT NULL, tone DOUBLE, themes VARCHAR, attrs_json VARCHAR, text_path VARCHAR,
        text_status VARCHAR, ingested_at TIMESTAMP NOT NULL
    );
    """),
    (17, "agents_s43", """
    CREATE TABLE kite_trades (
        trade_id VARCHAR PRIMARY KEY, order_id VARCHAR, trade_date DATE NOT NULL, symbol VARCHAR, exchange VARCHAR,
        isin VARCHAR, side VARCHAR NOT NULL, qty DOUBLE NOT NULL, price DOUBLE NOT NULL, account_id VARCHAR NOT NULL,
        seen_at TIMESTAMP NOT NULL, status VARCHAR NOT NULL, resolved_at TIMESTAMP
    );
    CREATE SEQUENCE question_seq START 1;
    CREATE TABLE questions (
        q_id INTEGER PRIMARY KEY, created_at TIMESTAMP NOT NULL, agent VARCHAR NOT NULL, subject_key VARCHAR UNIQUE,
        text VARCHAR NOT NULL, status VARCHAR NOT NULL, answer VARCHAR, answered_at TIMESTAMP
    );
    CREATE SEQUENCE memory_seq START 1;
    CREATE TABLE memory (
        mem_id INTEGER PRIMARY KEY, created_at TIMESTAMP NOT NULL, kind VARCHAR NOT NULL, subject VARCHAR,
        text VARCHAR NOT NULL, source VARCHAR NOT NULL, valid_from DATE NOT NULL, valid_to DATE, supersedes INTEGER
    );
    CREATE TABLE bot_updates (
        update_id BIGINT PRIMARY KEY, received_at TIMESTAMP NOT NULL, accepted BOOLEAN NOT NULL, command VARCHAR,
        reply_msg_id INTEGER
    );
    """),
    (18, "researcher_s44", """
    CREATE SEQUENCE research_flag_seq START 1;
    CREATE TABLE research_flags (
        flag_id INTEGER PRIMARY KEY, isin VARCHAR NOT NULL, symbol VARCHAR, kind VARCHAR NOT NULL,
        happened_at TIMESTAMP NOT NULL, detected_at TIMESTAMP NOT NULL, ref VARCHAR NOT NULL, detail VARCHAR NOT NULL,
        UNIQUE (isin, kind, ref)
    );
    CREATE SEQUENCE brief_seq START 1;
    CREATE TABLE briefs (
        brief_id INTEGER PRIMARY KEY, isin VARCHAR NOT NULL, symbol VARCHAR, as_of DATE NOT NULL,
        built_at TIMESTAMP NOT NULL, trigger VARCHAR, verified BOOLEAN NOT NULL, text VARCHAR NOT NULL
    );
    """),
    (19, "analyst_s44", """
    CREATE SEQUENCE api_call_seq START 1;
    CREATE TABLE api_calls (
        call_id INTEGER PRIMARY KEY, created_at TIMESTAMP NOT NULL, mode VARCHAR NOT NULL, model VARCHAR NOT NULL,
        topic VARCHAR, question VARCHAR NOT NULL, request_sha VARCHAR NOT NULL, request_json VARCHAR NOT NULL,
        status VARCHAR NOT NULL, batch_id VARCHAR, input_tokens INTEGER, output_tokens INTEGER, cost_usd DOUBLE,
        cost_inr DOUBLE, note_doc VARCHAR, finished_at TIMESTAMP, error VARCHAR
    );
    """),
    (20, "theses_s46", """
    CREATE TABLE theses (
        thesis_id INTEGER PRIMARY KEY, created_at TIMESTAMP NOT NULL, text VARCHAR NOT NULL, keywords_json VARCHAR NOT NULL,
        sectors_json VARCHAR NOT NULL, hold_cash DOUBLE NOT NULL, expires DATE NOT NULL, status VARCHAR NOT NULL,
        last_checked TIMESTAMP, evidence_json VARCHAR
    );
    """),
    (21, "inbox_datasets", """
    CREATE TABLE datasets (
        dataset_id INTEGER PRIMARY KEY, file VARCHAR NOT NULL, sheet VARCHAR, file_sha VARCHAR NOT NULL, kind VARCHAR,
        shape VARCHAR NOT NULL, isins_json VARCHAR NOT NULL, n_rows INTEGER, n_cols INTEGER, columns_json VARCHAR,
        table_path VARCHAR, doc_id VARCHAR, ingested_at TIMESTAMP NOT NULL, UNIQUE (file_sha, sheet)
    );
    CREATE TABLE dataset_facts (
        dataset_id INTEGER NOT NULL, isin VARCHAR, metric VARCHAR NOT NULL, period VARCHAR, value DOUBLE NOT NULL,
        source VARCHAR NOT NULL
    );
    """),
    # 2026-10-18: standalone and consolidated quarters side by side (safety-check amendment 2); every earlier row is
    # standalone (BSE's template and the standalone integrated filings)
    (22, "results_basis", """
    CREATE TABLE quarterly_results_v22 (
        scrip_code VARCHAR NOT NULL, quarter_end DATE NOT NULL, audited BOOLEAN,
        revenue DOUBLE, other_income DOUBLE, total_income DOUBLE, expenditure DOUBLE,
        finance_costs DOUBLE, depreciation DOUBLE, pbt DOUBLE, tax DOUBLE, net_profit DOUBLE,
        eps_basic DOUBLE, eps_diluted DOUBLE,
        usable_from DATE NOT NULL, date_source VARCHAR NOT NULL, source VARCHAR NOT NULL,
        fetched_at TIMESTAMP NOT NULL, basis VARCHAR NOT NULL DEFAULT 'standalone',
        PRIMARY KEY (scrip_code, quarter_end, basis)
    );
    INSERT INTO quarterly_results_v22 SELECT *, 'standalone' FROM quarterly_results;
    DROP TABLE quarterly_results;
    ALTER TABLE quarterly_results_v22 RENAME TO quarterly_results;
    """),
    # 2026-10-22: S52 live forecasts (Q5 turnover, Q6 results) with the registered baseline beside each, and the
    # scoreboard that switches a use to its baseline (quant/tfm2_live.py)
    (23, "tfm_live_s52", """
    CREATE TABLE tfm_forecasts (
        forecast_id INTEGER PRIMARY KEY, use VARCHAR NOT NULL, subject VARCHAR NOT NULL, as_of DATE NOT NULL,
        target DATE NOT NULL, inputs_last DATE NOT NULL, model VARCHAR, q10 DOUBLE, q50 DOUBLE, q90 DOUBLE, point DOUBLE,
        baseline DOUBLE, baseline_name VARCHAR, actual DOUBLE, loss_model DOUBLE, loss_baseline DOUBLE,
        scored_at TIMESTAMP, created_at TIMESTAMP NOT NULL
    );
    CREATE TABLE tfm_scoreboard (
        use VARCHAR NOT NULL, as_of DATE NOT NULL, matured INTEGER NOT NULL, window_n INTEGER NOT NULL, ratio DOUBLE,
        serving VARCHAR NOT NULL, changed BOOLEAN NOT NULL, updated_at TIMESTAMP NOT NULL
    );
    """),
    # 2026-10-22: S54 dashboard: The investor's sticky notes on the day's checklist
    (24, "app_notes_s54", """
    CREATE TABLE app_notes (
        note_id INTEGER PRIMARY KEY, text VARCHAR NOT NULL, done BOOLEAN NOT NULL DEFAULT false,
        deleted BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMP NOT NULL, done_at TIMESTAMP
    );
    """),
    # 2026-10-22: S54b chats in the AI centre (each message's route kept beside it; tidied into memory after 30 days)
    (25, "chats_s54b", """
    CREATE TABLE chats (
        chat_id INTEGER PRIMARY KEY, title VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL
    );
    CREATE TABLE chat_messages (
        msg_id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, role VARCHAR NOT NULL, mode VARCHAR, text VARCHAR NOT NULL,
        status VARCHAR NOT NULL, route_json VARCHAR, meta VARCHAR, report_doc VARCHAR, cost_inr DOUBLE,
        created_at TIMESTAMP NOT NULL, finished_at TIMESTAMP
    );
    """),
    # 2026-10-22: S54c price watches (The investor's conditions; a hit is a message and a notification, never an order)
    (26, "watches_s54c", """
    CREATE TABLE watches (
        watch_id INTEGER PRIMARY KEY, isin VARCHAR NOT NULL, symbol VARCHAR, kind VARCHAR NOT NULL, level DOUBLE NOT NULL,
        note VARCHAR, active BOOLEAN NOT NULL DEFAULT true, created_at TIMESTAMP NOT NULL, last_hit_at TIMESTAMP,
        hits INTEGER NOT NULL DEFAULT 0
    );
    """),
    # 2026-10-23: S54d inbox: every file the investor drops or pastes, its route and its steps (statements, screenshots, exports)
    (27, "inbox_items_s54d", """
    CREATE TABLE inbox_items (
        item_id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, kind VARCHAR NOT NULL, account VARCHAR, path VARCHAR,
        sha VARCHAR NOT NULL, status VARCHAR NOT NULL, steps_json VARCHAR, text VARCHAR, result_json VARCHAR,
        chat_id INTEGER, created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL, cleaned_at TIMESTAMP
    );
    """),
    # 2026-10-23: S54e checklists: a note may belong to a named list (a preset checklist for a company, a buy, a month)
    (28, "checklists_s54e", """
    ALTER TABLE app_notes ADD COLUMN list_name VARCHAR;
    """),
    # 2026-10-23: S55 ready plans: one current plan per next sum of money, earlier versions kept (what changed)
    (29, "ready_plans_s55", """
    CREATE TABLE ready_plans (
        plan_id INTEGER PRIMARY KEY, trigger_key VARCHAR NOT NULL, kind VARCHAR NOT NULL, due DATE NOT NULL,
        amount DOUBLE NOT NULL, source VARCHAR, inputs_hash VARCHAR NOT NULL, plan_json VARCHAR NOT NULL,
        status VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL, checked_at TIMESTAMP NOT NULL
    );
    """),
    # 2026-10-23: S57 knowledge-graph cleanup: merged names kept as aliases; syndicated copies point at the original
    (30, "kg_cleanup_s57", """
    CREATE TABLE kg_aliases (
        alias VARCHAR PRIMARY KEY, canonical VARCHAR NOT NULL, how VARCHAR NOT NULL, decided_at TIMESTAMP NOT NULL
    );
    ALTER TABLE kg_docs ADD COLUMN dup_of VARCHAR;
    """),
    # 2026-10-24: S58b the portfolio today: what Kite showed at each login and check (holdings, funds, today's trades,
    # cash); the ledger stays the record, this is the broker's view between statements
    (31, "kite_snapshots_s58b", """
    CREATE TABLE kite_snapshots (
        snap_id INTEGER NOT NULL, taken_at TIMESTAMP NOT NULL, account_id VARCHAR NOT NULL, kind VARCHAR NOT NULL,
        isin VARCHAR, symbol VARCHAR, qty DOUBLE, t1 DOUBLE, avg_price DOUBLE, last_price DOUBLE, amount DOUBLE
    );
    """),
    # 2026-10-24: S59 the agent HQ: each paid call names its agent; the board of tasks between agents (and the investor's
    # orders); what the readers made of each public document; the brain's passes and predictions; reminders
    (32, "hq_s59", """
    ALTER TABLE api_calls ADD COLUMN agent VARCHAR;
    CREATE TABLE hq_tasks (
        task_id INTEGER PRIMARY KEY, created_at TIMESTAMP NOT NULL, from_agent VARCHAR NOT NULL, to_agent VARCHAR NOT NULL,
        text VARCHAR NOT NULL, body_json VARCHAR, status VARCHAR NOT NULL, hops INTEGER NOT NULL, parent_id INTEGER,
        channel VARCHAR, result VARCHAR, result_json VARCHAR, cost_inr DOUBLE, started_at TIMESTAMP, finished_at TIMESTAMP,
        replied_at TIMESTAMP
    );
    CREATE TABLE hq_readings (
        doc_id VARCHAR PRIMARY KEY, read_at TIMESTAMP NOT NULL, model VARCHAR NOT NULL, material VARCHAR NOT NULL,
        why VARCHAR, summary VARCHAR, figures_json VARCHAR, dropped INTEGER, call_id INTEGER, isins_json VARCHAR
    );
    CREATE TABLE hq_passes (
        pass_id INTEGER PRIMARY KEY, passed_at TIMESTAMP NOT NULL, trigger VARCHAR NOT NULL, events_json VARCHAR, model VARCHAR NOT NULL,
        role VARCHAR NOT NULL, shadow BOOLEAN NOT NULL, status VARCHAR NOT NULL, note VARCHAR, decisions_json VARCHAR,
        cost_inr DOUBLE, call_id INTEGER, error VARCHAR
    );
    CREATE TABLE hq_predictions (
        pred_id INTEGER PRIMARY KEY, pass_id INTEGER NOT NULL, model VARCHAR NOT NULL, made_at TIMESTAMP NOT NULL,
        claim VARCHAR NOT NULL, check_json VARCHAR NOT NULL, due DATE NOT NULL, confidence DOUBLE NOT NULL,
        base_rate DOUBLE, outcome BOOLEAN, scored_at TIMESTAMP, detail VARCHAR
    );
    CREATE TABLE hq_reminders (
        rem_id INTEGER PRIMARY KEY, text VARCHAR NOT NULL, due_at TIMESTAMP NOT NULL, created_at TIMESTAMP NOT NULL,
        source VARCHAR, sent_at TIMESTAMP, cancelled BOOLEAN NOT NULL DEFAULT false
    );
    """),
    # 2026-10-25: S60 the brain with tools (PLAN A18): the turn of a pass on each paid call (passes a day count first
    # turns); every tool call of a pass; the suggestion ledger (The investor's answer, the outcome, the decision quality)
    (33, "brain_tools_s60", """
    ALTER TABLE api_calls ADD COLUMN turn INTEGER;
    CREATE TABLE hq_tool_calls (
        call_no INTEGER PRIMARY KEY, pass_id INTEGER, called_at TIMESTAMP NOT NULL, turn INTEGER NOT NULL, tool VARCHAR NOT NULL,
        kind VARCHAR NOT NULL, args_json VARCHAR, status VARCHAR NOT NULL, result VARCHAR, ms INTEGER
    );
    CREATE TABLE hq_suggestions (
        sug_id INTEGER PRIMARY KEY, pass_id INTEGER, model VARCHAR NOT NULL, made_at TIMESTAMP NOT NULL, kind VARCHAR NOT NULL,
        isin VARCHAR, symbol VARCHAR, text VARCHAR NOT NULL, reasoning VARCHAR, data_json VARCHAR, horizon_days INTEGER NOT NULL,
        ref_date DATE, ref_close DOUBLE, ref_qty DOUBLE, shadow BOOLEAN NOT NULL, quality VARCHAR, quality_why VARCHAR,
        answer VARCHAR NOT NULL DEFAULT 'none', answered_at TIMESTAMP, answer_source VARCHAR,
        outcome VARCHAR, outcome_json VARCHAR, scored_at TIMESTAMP
    );
    """),
    # 2026-10-25: S62 the learner (PLAN A22): what it read, the claims it found and their registered tests, its
    # proposals from the system's own record, what is live from it; the security agent's runs and findings
    (34, "learner_security_s62", """
    CREATE TABLE learn_sources (
        src_id INTEGER PRIMARY KEY, found_at TIMESTAMP NOT NULL, origin VARCHAR NOT NULL, ref VARCHAR NOT NULL UNIQUE,
        title VARCHAR, authors VARCHAR, year INTEGER, url VARCHAR, abstract VARCHAR, text_path VARCHAR,
        status VARCHAR NOT NULL, why VARCHAR, read_at TIMESTAMP
    );
    CREATE TABLE learn_claims (
        claim_id INTEGER PRIMARY KEY, src_id INTEGER NOT NULL, made_at TIMESTAMP NOT NULL, claim VARCHAR NOT NULL,
        quote VARCHAR, template VARCHAR NOT NULL, params_json VARCHAR, needs VARCHAR, model VARCHAR, status VARCHAR NOT NULL,
        same_as INTEGER, protocol_path VARCHAR, protocol_sha VARCHAR, code_sha VARCHAR, registered_at TIMESTAMP,
        result_json VARCHAR, decision VARCHAR, why VARCHAR, decided_at TIMESTAMP
    );
    CREATE TABLE learn_proposals (
        prop_id INTEGER PRIMARY KEY, made_at TIMESTAMP NOT NULL, kind VARCHAR NOT NULL, target VARCHAR, text VARCHAR NOT NULL,
        value VARCHAR, evidence_json VARCHAR, n INTEGER, rule VARCHAR, passed BOOLEAN NOT NULL, status VARCHAR NOT NULL,
        q_id INTEGER, decided_at TIMESTAMP, by_model VARCHAR
    );
    CREATE TABLE learned (
        learn_id INTEGER PRIMARY KEY, kind VARCHAR NOT NULL, key VARCHAR NOT NULL, text VARCHAR NOT NULL, value VARCHAR,
        source VARCHAR NOT NULL, valid_from TIMESTAMP NOT NULL, valid_to TIMESTAMP
    );
    CREATE TABLE sec_runs (
        run_id INTEGER PRIMARY KEY, run_at TIMESTAMP NOT NULL, kind VARCHAR NOT NULL, status VARCHAR NOT NULL, upto VARCHAR,
        detail_json VARCHAR, cost_inr DOUBLE
    );
    CREATE TABLE sec_findings (
        find_id INTEGER PRIMARY KEY, found_at TIMESTAMP NOT NULL, kind VARCHAR NOT NULL, severity VARCHAR NOT NULL,
        text VARCHAR NOT NULL, ref VARCHAR, q_id INTEGER, sent BOOLEAN NOT NULL DEFAULT false
    );
    """),
    # 2026-10-26: S64 Phase 1: every test ever run in one family, for the learner's Bonferroni bar (protocol amendment 4)
    (35, "learn_tests_s64", """
    CREATE TABLE learn_tests (
        test_id BIGINT PRIMARY KEY, ran_at TIMESTAMP, family VARCHAR, origin VARCHAR, claim_id BIGINT, template VARCHAR,
        params_json VARCHAR, n_dev INTEGER, t_dev DOUBLE, t_val DOUBLE, sr_dev DOUBLE, dsr DOUBLE, threshold_dev DOUBLE,
        passed BOOLEAN, note VARCHAR
    );
    """),
    # 2026-10-26: S64 Phase 3: TimesFM is gone; the forecast table is just `forecasts`. Its `model` column now holds
    # baseline (turnover, results), stats_ewma or stats_plain (price ranges: use price21 / price63 / price252)
    (36, "forecasts_s64", """
    ALTER TABLE tfm_forecasts RENAME TO forecasts;
    """),
    # 2026-10-26: S64 Phase 5 (the companion's gaps): suggestion numbers from code and the watch behind each; cause
    # hypotheses; limit proposals (theme, dip reserve, pot); the opportunity pot; theme baskets; scans. A pass's tool
    # results are already in hq_tool_calls (v33), which the replay bench reads, so hq_passes needs no new column.
    (37, "companion_s64", """
    ALTER TABLE hq_suggestions ADD COLUMN price_low DOUBLE;
    ALTER TABLE hq_suggestions ADD COLUMN price_high DOUBLE;
    ALTER TABLE hq_suggestions ADD COLUMN max_buy DOUBLE;
    ALTER TABLE hq_suggestions ADD COLUMN amount DOUBLE;
    ALTER TABLE hq_suggestions ADD COLUMN wrong_if VARCHAR;
    ALTER TABLE hq_suggestions ADD COLUMN wrong_price DOUBLE;
    ALTER TABLE hq_suggestions ADD COLUMN stats_json VARCHAR;
    ALTER TABLE hq_suggestions ADD COLUMN watch_id BIGINT;
    CREATE TABLE kg_hypotheses (
        hyp_id BIGINT PRIMARY KEY, made_at TIMESTAMP NOT NULL, pass_id BIGINT, subject VARCHAR NOT NULL, cause VARCHAR NOT NULL,
        effect VARCHAR, evidence_json VARCHAR, status VARCHAR NOT NULL, check_by DATE NOT NULL, decided_at TIMESTAMP, why VARCHAR
    );
    CREATE TABLE limit_proposals (
        prop_id BIGINT PRIMARY KEY, kind VARCHAR NOT NULL, key VARCHAR NOT NULL, value VARCHAR, evidence_json VARCHAR,
        status VARCHAR NOT NULL, proposed_at TIMESTAMP NOT NULL, decided_at TIMESTAMP, q_id BIGINT
    );
    CREATE TABLE pot_ideas (
        idea_id BIGINT PRIMARY KEY, made_at TIMESTAMP NOT NULL, isin VARCHAR NOT NULL, symbol VARCHAR, reason VARCHAR,
        ref_close DOUBLE, buy_below DOUBLE, exit_above DOUBLE, stop_below DOUBLE, amount DOUBLE, horizon_days INTEGER,
        status VARCHAR NOT NULL,
        closed_at TIMESTAMP, ret DOUBLE, ret_vs_market DOUBLE
    );
    CREATE TABLE theme_baskets (
        theme VARCHAR NOT NULL, isin VARCHAR NOT NULL, weight DOUBLE, since DATE NOT NULL, until DATE, status VARCHAR NOT NULL
    );
    CREATE TABLE scans (
        scan_id BIGINT PRIMARY KEY, name VARCHAR NOT NULL, conditions_json VARCHAR NOT NULL, universe VARCHAR NOT NULL,
        active BOOLEAN NOT NULL DEFAULT true, created_by VARCHAR, created_at TIMESTAMP NOT NULL, claim_id BIGINT
    );
    """),
]


def pm_dir() -> Path:
    r"""`PFLAB_PM_DIR`, else `D:\portfolio_lab\pm` (absolute on purpose: a
    relative fallback would resolve differently per working directory)."""
    return Path(os.environ.get("PFLAB_PM_DIR", DEFAULT_PM_DIR)).expanduser()


def db_path() -> Path:
    return pm_dir() / DB_NAME


def _sha(sql: str) -> str:
    return hashlib.sha256(sql.encode()).hexdigest()


def migrate(con, migrations=None) -> list:
    """Apply pending migrations in order; return the versions applied."""
    migrations = MIGRATIONS if migrations is None else migrations
    con.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY, name VARCHAR, sha VARCHAR, applied_at TIMESTAMP)""")
    done = {r[0]: r[1] for r in con.execute("SELECT version, sha FROM schema_migrations").fetchall()}
    applied = []
    for version, name, sql in sorted(migrations):
        if version in done:
            if done[version] != _sha(sql):
                raise RuntimeError(f"migration {version} ({name}) was edited after it was applied")
            continue
        con.execute("BEGIN")
        try:
            con.execute(sql)
            con.execute("INSERT INTO schema_migrations VALUES (?, ?, ?, ?)",
                        [version, name, _sha(sql), datetime.now()])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied


def next_id(con, table: str, column: str) -> int:
    """The next id for `table`: its largest `column` + 1. Used instead of DuckDB sequences, which a killed process
    can leave behind its own rows (2026-10-17: after a stopped run, nextval returned 1 while rows 1..63 were kept,
    and every later insert failed). The store has one writer at a time, so max + 1 cannot collide."""
    return int(con.execute(f"SELECT coalesce(max({column}), 0) + 1 FROM {table}").fetchone()[0])


_OPEN_TX: set = set()
_TX_LOCK = threading.Lock()


@contextmanager
def transaction(con):
    """All or nothing (S58 drill 2: a power cut halfway through a ledger rebuild left 100 of 1,383 events). Inside an
    open one on the same connection this joins it, so the outer one decides (a refused nested BEGIN would abort the
    outer transaction in DuckDB, so the open ones are remembered here)."""
    key = id(con)
    with _TX_LOCK:
        nested = key in _OPEN_TX
        _OPEN_TX.add(key)
    if nested:
        yield con
        return
    try:
        con.execute("BEGIN")
        try:
            yield con
        except BaseException:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
    finally:
        with _TX_LOCK:
            _OPEN_TX.discard(key)


def connect(path: Optional[Path] = None, read_only: bool = False):
    """Open (creating if needed) the ledger and bring the schema up to date."""
    p = Path(path) if path else db_path()
    if read_only:
        return duckdb.connect(str(p), read_only=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(p))
    migrate(con)
    return con
