"""
Session persistence — dump all ephemeral session data to TimescaleDB.

Called at the end of run_daily_sessions() so captured bars, news, trades,
candidates, and log buffer survive Render redeploys.

Tables are auto-created on first use (CREATE IF NOT EXISTS).
"""

from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

DB_CONN = os.getenv('NEON_CONNECTION_STRING',
                     os.getenv('TIMESCALE_CONNECTION_STRING',
                               'postgresql://postgres:changeme123@localhost:5432/stockdata'))
STATE_DIR = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader"))

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS session_runs (
    id              SERIAL PRIMARY KEY,
    run_date        DATE NOT NULL,
    strategy        TEXT NOT NULL,
    result          TEXT,
    top_pick        TEXT,
    entry_price     DOUBLE PRECISION,
    exit_price      DOUBLE PRECISION,
    pnl             DOUBLE PRECISION,
    candidates_json JSONB,
    state_json      JSONB,
    persisted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_date, strategy)
);

CREATE TABLE IF NOT EXISTS session_bars (
    symbol      TEXT NOT NULL,
    bar_time    TIMESTAMPTZ NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      BIGINT,
    vwap        DOUBLE PRECISION,
    source      TEXT,
    received_at TIMESTAMPTZ,
    run_date    DATE NOT NULL,
    PRIMARY KEY (symbol, bar_time, run_date)
);

CREATE TABLE IF NOT EXISTS session_news (
    id          SERIAL PRIMARY KEY,
    run_date    DATE NOT NULL,
    symbol      TEXT NOT NULL,
    headline    TEXT,
    source      TEXT,
    news_tier   TEXT,
    created_at  TEXT,
    summary     TEXT,
    url         TEXT,
    symbol_count INTEGER,
    is_specific  BOOLEAN,
    received_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS session_logs (
    id          SERIAL PRIMARY KEY,
    run_date    DATE NOT NULL,
    logged_at   TEXT,
    level       TEXT,
    message     TEXT
);
"""


def _get_conn():
    return psycopg2.connect(DB_CONN, connect_timeout=10)


def _ensure_tables(conn):
    with conn.cursor() as cur:
        cur.execute(_SCHEMA_SQL)
    conn.commit()


def _persist_run(conn, run_date: str, strategy: str, state_data: dict):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO session_runs
                (run_date, strategy, result, top_pick, entry_price, exit_price,
                 pnl, candidates_json, state_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_date, strategy)
            DO UPDATE SET
                result = EXCLUDED.result,
                top_pick = EXCLUDED.top_pick,
                entry_price = EXCLUDED.entry_price,
                exit_price = EXCLUDED.exit_price,
                pnl = EXCLUDED.pnl,
                candidates_json = EXCLUDED.candidates_json,
                state_json = EXCLUDED.state_json,
                persisted_at = NOW()
        """, (
            run_date,
            strategy,
            state_data.get("last_result"),
            state_data.get("top_pick"),
            state_data.get("entry_price"),
            state_data.get("exit_price"),
            state_data.get("pnl"),
            json.dumps(state_data.get("candidates") or state_data.get("watchlist") or []),
            json.dumps(state_data),
        ))


def _persist_bars(conn, run_date: str):
    today_str = run_date.replace("-", "")
    bars_file = STATE_DIR / f"bars_{today_str}.jsonl"
    if not bars_file.exists():
        logger.info("session_persistence: no bars file to persist")
        return 0

    rows = []
    with open(bars_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                rows.append((
                    r.get("symbol"),
                    r.get("t"),
                    r.get("o"),
                    r.get("h"),
                    r.get("l"),
                    r.get("c"),
                    r.get("v"),
                    r.get("vw"),
                    r.get("source"),
                    r.get("received_at"),
                    run_date,
                ))
            except json.JSONDecodeError:
                continue

    if not rows:
        return 0

    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO session_bars
                (symbol, bar_time, open, high, low, close, volume, vwap,
                 source, received_at, run_date)
            VALUES %s
            ON CONFLICT (symbol, bar_time, run_date) DO NOTHING
        """, rows)
    return len(rows)


def _persist_news(conn, run_date: str):
    today_str = run_date.replace("-", "")
    news_file = STATE_DIR / f"news_{today_str}.jsonl"
    if not news_file.exists():
        logger.info("session_persistence: no news file to persist")
        return 0

    rows = []
    with open(news_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                rows.append((
                    run_date,
                    r.get("symbol"),
                    r.get("headline"),
                    r.get("source"),
                    r.get("news_tier"),
                    r.get("created_at"),
                    r.get("summary"),
                    r.get("url"),
                    r.get("symbol_count"),
                    r.get("is_specific"),
                    r.get("received_at"),
                ))
            except json.JSONDecodeError:
                continue

    if not rows:
        return 0

    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO session_news
                (run_date, symbol, headline, source, news_tier, created_at,
                 summary, url, symbol_count, is_specific, received_at)
            VALUES %s
        """, rows)
    return len(rows)


def _persist_logs(conn, run_date: str):
    try:
        from api.dashboard import _LOG_BUFFER
    except Exception:
        _LOG_BUFFER = []

    if not _LOG_BUFFER:
        return 0

    rows = [(run_date, e.get("t"), e.get("level"), e.get("msg")) for e in _LOG_BUFFER]

    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO session_logs (run_date, logged_at, level, message)
            VALUES %s
        """, rows)
    return len(rows)


def persist_session(scalp_state: dict, vwap_state: dict):
    """Persist all session data to TimescaleDB. Never raises — logs errors."""
    run_date = str(datetime.now(timezone.utc).date())
    try:
        conn = _get_conn()
        try:
            _ensure_tables(conn)

            if scalp_state:
                _persist_run(conn, run_date, "opening_bell_scalp", scalp_state)
            if vwap_state:
                _persist_run(conn, run_date, "vwap_reclaim", vwap_state)

            bar_count = _persist_bars(conn, run_date)
            news_count = _persist_news(conn, run_date)

            try:
                log_count = _persist_logs(conn, run_date)
            except Exception as le:
                logger.warning(f"session_persistence: log persist failed (non-fatal): {le}")
                log_count = 0

            conn.commit()
            logger.info(
                f"session_persistence: saved to DB — "
                f"bars={bar_count}, news={news_count}, logs={log_count}"
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"session_persistence FAILED (non-fatal): {e}", exc_info=True)
