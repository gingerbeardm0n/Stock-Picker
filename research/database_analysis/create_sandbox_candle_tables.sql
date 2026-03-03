-- Create isolated sandbox candle tables for bootstrap/backfill validation.
-- Run this once in DBeaver before using:
--   python database/bootstrap_single_day_data.py --date 2026-02-20 --schema sandbox --strict

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS sandbox;

-- 1-minute bars
CREATE TABLE IF NOT EXISTS sandbox.stock_candles_1m (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    open NUMERIC(12, 4) NOT NULL,
    high NUMERIC(12, 4) NOT NULL,
    low NUMERIC(12, 4) NOT NULL,
    close NUMERIC(12, 4) NOT NULL,
    volume BIGINT NOT NULL,
    trade_count INTEGER,
    vwap NUMERIC(12, 6),
    PRIMARY KEY (time, symbol)
);

SELECT create_hypertable(
    'sandbox.stock_candles_1m',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS idx_sandbox_1m_symbol_time
    ON sandbox.stock_candles_1m (symbol, time DESC);

-- 1-hour bars
CREATE TABLE IF NOT EXISTS sandbox.stock_candles_1h (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    open NUMERIC(12, 4) NOT NULL,
    high NUMERIC(12, 4) NOT NULL,
    low NUMERIC(12, 4) NOT NULL,
    close NUMERIC(12, 4) NOT NULL,
    volume BIGINT NOT NULL,
    trade_count INTEGER,
    vwap NUMERIC(12, 6),
    PRIMARY KEY (time, symbol)
);

SELECT create_hypertable(
    'sandbox.stock_candles_1h',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '7 days'
);

CREATE INDEX IF NOT EXISTS idx_sandbox_1h_symbol_time
    ON sandbox.stock_candles_1h (symbol, time DESC);

-- 1-day bars
CREATE TABLE IF NOT EXISTS sandbox.stock_candles_1d (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    open NUMERIC(12, 4) NOT NULL,
    high NUMERIC(12, 4) NOT NULL,
    low NUMERIC(12, 4) NOT NULL,
    close NUMERIC(12, 4) NOT NULL,
    volume BIGINT NOT NULL,
    trade_count INTEGER,
    vwap NUMERIC(12, 6),
    PRIMARY KEY (time, symbol)
);

SELECT create_hypertable(
    'sandbox.stock_candles_1d',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '30 days'
);

CREATE INDEX IF NOT EXISTS idx_sandbox_1d_symbol_time
    ON sandbox.stock_candles_1d (symbol, time DESC);

