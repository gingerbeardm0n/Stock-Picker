-- TimescaleDB Schema for Stock Trading Data
-- Based on Alpaca API response structures
-- Date: 2026-02-11

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================================
-- TABLE 1: Stock Candles (OHLCV Data)
-- ============================================================================
-- Stores minute, hour, and daily candles
-- Optimized for time-series queries (relative volume, premarket analysis, backtesting)

CREATE TABLE IF NOT EXISTS stock_candles (
    time TIMESTAMPTZ NOT NULL,          -- Candle timestamp (UTC)
    symbol VARCHAR(10) NOT NULL,        -- Stock ticker symbol
    timeframe VARCHAR(5) NOT NULL,      -- '1m', '5m', '15m', '1h', '1d'
    open NUMERIC(12, 4) NOT NULL,       -- Open price
    high NUMERIC(12, 4) NOT NULL,       -- High price
    low NUMERIC(12, 4) NOT NULL,        -- Low price
    close NUMERIC(12, 4) NOT NULL,      -- Close price
    volume BIGINT NOT NULL,             -- Trading volume
    trade_count INTEGER,                -- Number of trades (null for minute bars)
    vwap NUMERIC(12, 6),               -- Volume weighted average price

    -- Primary key constraint
    PRIMARY KEY (time, symbol, timeframe)
);

-- Convert to TimescaleDB hypertable (partitioned by time)
SELECT create_hypertable(
    'stock_candles',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'  -- Partition by day for fast queries
);

-- Create indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_candles_symbol_time
    ON stock_candles (symbol, time DESC);

CREATE INDEX IF NOT EXISTS idx_candles_timeframe
    ON stock_candles (timeframe, time DESC);

-- Composite index for scanner queries (price range + time)
CREATE INDEX IF NOT EXISTS idx_candles_price_range
    ON stock_candles (close, time DESC)
    WHERE timeframe = '1m';

COMMENT ON TABLE stock_candles IS 'Time-series OHLCV candle data for all timeframes';


-- ============================================================================
-- TABLE 2: Real-time Snapshots
-- ============================================================================
-- Stores latest price, quote, and trade data for fast lookups

CREATE TABLE IF NOT EXISTS stock_snapshots (
    time TIMESTAMPTZ NOT NULL,          -- Snapshot timestamp
    symbol VARCHAR(10) NOT NULL,        -- Stock ticker

    -- Latest Trade
    last_trade_price NUMERIC(12, 4),    -- Latest trade price
    last_trade_size INTEGER,            -- Latest trade size
    last_trade_time TIMESTAMPTZ,        -- Latest trade timestamp
    last_trade_exchange VARCHAR(5),     -- Exchange code

    -- Latest Quote (Bid/Ask)
    bid_price NUMERIC(12, 4),           -- Best bid price
    bid_size INTEGER,                   -- Bid size
    ask_price NUMERIC(12, 4),           -- Best ask price
    ask_size INTEGER,                   -- Ask size
    bid_exchange VARCHAR(5),            -- Bid exchange
    ask_exchange VARCHAR(5),            -- Ask exchange

    -- Calculated fields
    spread NUMERIC(12, 4),              -- Ask - Bid

    PRIMARY KEY (time, symbol)
);

-- Convert to hypertable
SELECT create_hypertable(
    'stock_snapshots',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 hour'  -- Snapshot data changes frequently
);

-- Index for latest snapshot lookup
CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_latest
    ON stock_snapshots (symbol, time DESC);

COMMENT ON TABLE stock_snapshots IS 'Real-time price snapshots for quick current price lookups';


-- ============================================================================
-- TABLE 3: Stock Metadata
-- ============================================================================
-- Stores basic stock information (updated daily or on-demand)

CREATE TABLE IF NOT EXISTS stock_metadata (
    symbol VARCHAR(10) PRIMARY KEY,     -- Stock ticker
    name VARCHAR(255),                  -- Company name
    exchange VARCHAR(10),               -- Exchange (NASDAQ, NYSE, etc.)
    asset_class VARCHAR(20),            -- 'us_equity', 'crypto', etc.
    status VARCHAR(20),                 -- 'active', 'inactive'
    tradable BOOLEAN,                   -- Can be traded
    marginable BOOLEAN,                 -- Can be bought on margin
    shortable BOOLEAN,                  -- Can be shorted
    easy_to_borrow BOOLEAN,             -- Easy to borrow for shorting
    fractionable BOOLEAN,               -- Supports fractional shares

    -- Metadata
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_metadata_tradable
    ON stock_metadata (tradable, status);

COMMENT ON TABLE stock_metadata IS 'Stock metadata and attributes';


-- ============================================================================
-- TABLE 4: Premarket Volume Cache
-- ============================================================================
-- Pre-aggregated premarket volume data for fast scanner queries

CREATE TABLE IF NOT EXISTS premarket_volumes (
    date DATE NOT NULL,                 -- Trading date
    symbol VARCHAR(10) NOT NULL,        -- Stock ticker
    pm_volume BIGINT NOT NULL,          -- Total premarket volume (4am-9:30am)
    pm_vwap NUMERIC(12, 6),            -- Premarket VWAP
    pm_high NUMERIC(12, 4),            -- Premarket high
    pm_low NUMERIC(12, 4),             -- Premarket low
    pm_open NUMERIC(12, 4),            -- Premarket open (4am)
    pm_close NUMERIC(12, 4),           -- Premarket close (9:25am)
    yesterday_close NUMERIC(12, 4),    -- Previous day close (for % gain calc)
    pm_gain_pct NUMERIC(8, 4),         -- Premarket gain %

    PRIMARY KEY (date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_pm_date_symbol
    ON premarket_volumes (date DESC, symbol);

CREATE INDEX IF NOT EXISTS idx_pm_gain_pct
    ON premarket_volumes (pm_gain_pct DESC)
    WHERE pm_gain_pct > 5.0;

COMMENT ON TABLE premarket_volumes IS 'Pre-aggregated premarket stats for scanner performance';


-- ============================================================================
-- TABLE 5: Scanner Results Cache
-- ============================================================================
-- Stores scanner results for historical analysis

CREATE TABLE IF NOT EXISTS scanner_results (
    scan_time TIMESTAMPTZ NOT NULL,     -- When the scan was run
    symbol VARCHAR(10) NOT NULL,        -- Stock that passed filters
    price NUMERIC(12, 4),               -- Price at scan time
    pm_gain_pct NUMERIC(8, 4),         -- Premarket gain %
    pm_volume BIGINT,                   -- Premarket volume
    avg_pm_volume BIGINT,               -- Average PM volume (30-day)
    relative_volume NUMERIC(8, 4),      -- Relative volume ratio
    avg_volume BIGINT,                  -- Average daily volume (20-day)

    -- Metadata
    scanner_version VARCHAR(20),        -- For tracking changes to scanner logic

    PRIMARY KEY (scan_time, symbol)
);

SELECT create_hypertable(
    'scanner_results',
    'scan_time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 week'
);

CREATE INDEX IF NOT EXISTS idx_scanner_symbol
    ON scanner_results (symbol, scan_time DESC);

COMMENT ON TABLE scanner_results IS 'Historical scanner results for backtesting and analysis';


-- ============================================================================
-- CONTINUOUS AGGREGATES (Automatic Rollups)
-- ============================================================================
-- Pre-compute common aggregations for performance

-- Daily candles from minute data (auto-rollup)
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_candles
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS day,
    symbol,
    FIRST(open, time) AS open,
    MAX(high) AS high,
    MIN(low) AS low,
    LAST(close, time) AS close,
    SUM(volume) AS volume,
    SUM(trade_count) AS trade_count
FROM stock_candles
WHERE timeframe = '1m'
GROUP BY day, symbol
WITH NO DATA;

-- Refresh policy: Update every hour
SELECT add_continuous_aggregate_policy('daily_candles',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);


-- ============================================================================
-- RETENTION POLICIES
-- ============================================================================
-- Automatically drop old data to save space

-- Keep minute candles for 90 days
SELECT add_retention_policy('stock_candles', INTERVAL '90 days', if_not_exists => TRUE);

-- Keep snapshots for 7 days (we only need recent for real-time)
SELECT add_retention_policy('stock_snapshots', INTERVAL '7 days', if_not_exists => TRUE);

-- Keep scanner results for 1 year
SELECT add_retention_policy('scanner_results', INTERVAL '1 year', if_not_exists => TRUE);


-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to calculate relative volume at specific time
CREATE OR REPLACE FUNCTION get_relative_volume(
    p_symbol VARCHAR(10),
    p_datetime TIMESTAMPTZ,
    p_lookback_days INTEGER DEFAULT 30
)
RETURNS NUMERIC AS $$
DECLARE
    today_volume BIGINT;
    avg_historical_volume NUMERIC;
BEGIN
    -- Get today's volume up to p_datetime
    SELECT COALESCE(SUM(volume), 0) INTO today_volume
    FROM stock_candles
    WHERE symbol = p_symbol
      AND timeframe = '1m'
      AND time <= p_datetime
      AND time >= DATE_TRUNC('day', p_datetime);

    -- Get average volume at same time over past N days
    SELECT AVG(daily_vol) INTO avg_historical_volume
    FROM (
        SELECT SUM(volume) AS daily_vol
        FROM stock_candles
        WHERE symbol = p_symbol
          AND timeframe = '1m'
          AND EXTRACT(HOUR FROM time) * 60 + EXTRACT(MINUTE FROM time)
              <= EXTRACT(HOUR FROM p_datetime) * 60 + EXTRACT(MINUTE FROM p_datetime)
          AND time >= p_datetime - (p_lookback_days || ' days')::INTERVAL
          AND time < p_datetime
        GROUP BY DATE_TRUNC('day', time)
    ) sub;

    -- Calculate relative volume
    IF avg_historical_volume > 0 THEN
        RETURN today_volume / avg_historical_volume;
    ELSE
        RETURN 0;
    END IF;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- VIEWS
-- ============================================================================

-- Latest snapshot for each symbol (for scanner queries)
CREATE OR REPLACE VIEW latest_snapshots AS
SELECT DISTINCT ON (symbol)
    symbol,
    time,
    last_trade_price AS price,
    bid_price,
    ask_price,
    spread
FROM stock_snapshots
ORDER BY symbol, time DESC;

COMMENT ON VIEW latest_snapshots IS 'Latest snapshot for each symbol (fast scanner lookups)';


-- ============================================================================
-- GRANTS (if using non-superuser account)
-- ============================================================================
-- Run these if you create a dedicated app user

-- CREATE USER stock_scanner WITH PASSWORD 'your_secure_password';
-- GRANT CONNECT ON DATABASE stockdata TO stock_scanner;
-- GRANT USAGE ON SCHEMA public TO stock_scanner;
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO stock_scanner;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO stock_scanner;


-- ============================================================================
-- COMPLETE
-- ============================================================================

-- Verify tables
SELECT schemaname, tablename
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;

-- Verify hypertables
SELECT hypertable_name, num_chunks
FROM timescaledb_information.hypertables;

COMMENT ON DATABASE CURRENT_DATABASE() IS 'Stock market data with TimescaleDB for algorithmic trading';
