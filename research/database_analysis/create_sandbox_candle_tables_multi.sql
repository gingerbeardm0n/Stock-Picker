-- Create separate sandbox schemas for IEX and SIP runs
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS sandbox_iex;
CREATE SCHEMA IF NOT EXISTS sandbox_sip;

-- ===== sandbox_iex =====
CREATE TABLE IF NOT EXISTS sandbox_iex.stock_candles_1m (
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
    'sandbox_iex.stock_candles_1m',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS idx_sandbox_iex_1m_symbol_time
    ON sandbox_iex.stock_candles_1m (symbol, time DESC);

CREATE TABLE IF NOT EXISTS sandbox_iex.stock_candles_1h (
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
    'sandbox_iex.stock_candles_1h',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '7 days'
);

CREATE INDEX IF NOT EXISTS idx_sandbox_iex_1h_symbol_time
    ON sandbox_iex.stock_candles_1h (symbol, time DESC);

CREATE TABLE IF NOT EXISTS sandbox_iex.stock_candles_1d (
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
    'sandbox_iex.stock_candles_1d',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '30 days'
);

CREATE INDEX IF NOT EXISTS idx_sandbox_iex_1d_symbol_time
    ON sandbox_iex.stock_candles_1d (symbol, time DESC);

-- ===== sandbox_sip =====
CREATE TABLE IF NOT EXISTS sandbox_sip.stock_candles_1m (
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
    'sandbox_sip.stock_candles_1m',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS idx_sandbox_sip_1m_symbol_time
    ON sandbox_sip.stock_candles_1m (symbol, time DESC);

CREATE TABLE IF NOT EXISTS sandbox_sip.stock_candles_1h (
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
    'sandbox_sip.stock_candles_1h',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '7 days'
);

CREATE INDEX IF NOT EXISTS idx_sandbox_sip_1h_symbol_time
    ON sandbox_sip.stock_candles_1h (symbol, time DESC);

CREATE TABLE IF NOT EXISTS sandbox_sip.stock_candles_1d (
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
    'sandbox_sip.stock_candles_1d',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '30 days'
);

CREATE INDEX IF NOT EXISTS idx_sandbox_sip_1d_symbol_time
    ON sandbox_sip.stock_candles_1d (symbol, time DESC);
