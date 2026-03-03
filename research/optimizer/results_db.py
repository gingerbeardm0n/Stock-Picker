"""
Results Database — SQLite storage for optimization runs.

Schema:
    runs   — one row per simulation run (aggregate metrics + all params as JSON)
    trades — one row per trade (linked to run_id)

Why SQLite:
    - Zero dependencies (stdlib)
    - Directly queryable with Python or any SQL tool
    - Optuna natively supports sqlite:/// storage URLs
    - Enables optuna-dashboard for live trial visualization

Usage:
    conn = init_db()                          # creates optimizer/results.db
    write_run(conn, run_id, ...)
    conn.close()
"""

from __future__ import annotations
import sqlite3
import json
from datetime import datetime
from pathlib import Path

# Default DB location (optimizer/results.db — next to this file)
DEFAULT_DB_PATH = Path(__file__).parent / 'results.db'

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    UNIQUE NOT NULL,
    created_at  TEXT    NOT NULL,
    start_date  TEXT,
    end_date    TEXT,

    -- Aggregate metrics
    total_trades  INTEGER,
    winners       INTEGER,
    losers        INTEGER,
    win_rate      REAL,
    profit_factor REAL,
    total_pnl     REAL,
    avg_daily_pnl REAL,
    max_drawdown  REAL,
    days_traded   INTEGER,

    -- Single optimization objective (higher = better)
    objective     REAL,

    -- All params flattened (a_*, b_*, c_* prefixed keys)
    params_json   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL,
    date         TEXT    NOT NULL,
    symbol       TEXT,
    pattern      TEXT,
    entry_price  REAL,
    exit_price   REAL,
    shares       INTEGER,
    pnl          REAL,
    exit_reason  TEXT,
    hold_minutes INTEGER,
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE INDEX IF NOT EXISTS idx_trades_run_id  ON trades (run_id);
CREATE INDEX IF NOT EXISTS idx_runs_objective ON runs (objective DESC);
CREATE INDEX IF NOT EXISTS idx_runs_created   ON runs (created_at);
"""


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """
    Open (or create) the results SQLite database.

    Returns an open connection. Caller is responsible for conn.close().
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def write_run(
    conn: sqlite3.Connection,
    run_id: str,
    start_date: str,
    end_date: str,
    metrics: dict,
    params: dict,
    trades: list[dict],
) -> None:
    """
    Persist a completed optimization run.

    Args:
        conn       : Open SQLite connection from init_db()
        run_id     : Unique identifier (e.g. "sweep__scanner__min_relative_volume__03")
        start_date : Training period start (YYYY-MM-DD string)
        end_date   : Training period end   (YYYY-MM-DD string)
        metrics    : Dict with keys: total_trades, winners, losers, win_rate,
                     profit_factor, total_pnl, avg_daily_pnl, max_drawdown,
                     days_traded, objective
        params     : Flat dict from RunConfig.to_flat_dict()
        trades     : List of per-trade dicts with keys: date, symbol, pattern,
                     entry_price, exit_price, shares, pnl, exit_reason, hold_minutes
    """
    now = datetime.utcnow().isoformat()

    conn.execute(
        """
        INSERT OR REPLACE INTO runs
            (run_id, created_at, start_date, end_date,
             total_trades, winners, losers, win_rate, profit_factor,
             total_pnl, avg_daily_pnl, max_drawdown, days_traded,
             objective, params_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, now, str(start_date), str(end_date),
            metrics.get('total_trades', 0),
            metrics.get('winners', 0),
            metrics.get('losers', 0),
            metrics.get('win_rate', 0.0),
            metrics.get('profit_factor', 0.0),
            metrics.get('total_pnl', 0.0),
            metrics.get('avg_daily_pnl', 0.0),
            metrics.get('max_drawdown', 0.0),
            metrics.get('days_traded', 0),
            metrics.get('objective', 0.0),
            json.dumps(params),
        ),
    )

    if trades:
        conn.executemany(
            """
            INSERT INTO trades
                (run_id, date, symbol, pattern, entry_price, exit_price,
                 shares, pnl, exit_reason, hold_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    t.get('date', ''),
                    t.get('symbol', ''),
                    t.get('pattern', ''),
                    t.get('entry_price', 0.0),
                    t.get('exit_price', 0.0),
                    t.get('shares', 0),
                    t.get('pnl', 0.0),
                    t.get('exit_reason', ''),
                    t.get('hold_minutes', 0),
                )
                for t in trades
            ],
        )

    conn.commit()


def run_exists(conn: sqlite3.Connection, run_id: str) -> bool:
    """Return True if this run_id is already in the DB (for resuming sweeps)."""
    row = conn.execute(
        "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    return row is not None
