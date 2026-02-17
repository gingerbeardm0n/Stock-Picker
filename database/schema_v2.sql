-- TimescaleDB Schema v2 - Separate Tables Per Timeframe
-- Based on Alpaca API response structures
-- Date: 2026-02-16
-- Changes: Split stock_candles into separate tables per timeframe

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================================
-- CANDLE TABLES - Separate table per timeframe for cleaner architecture
-- ============================================================================
-- Benefits:
-- - No overlap when backfilling incrementally
-- - Timeframe-specific retention policies
-- - Better query performance (smaller table scans)
-- - Easier to manage and troubleshoot

-- 1-Minute Candles (9am-12pm for Ross Cameron strategy)
CREATE TABLE IF NOT EXISTS stock_candles_1m (
    time TIMESTAMPTZ NOT NULL,          -- Candle timestamp (UTC)
    symbol VARCHAR(10) NOT NULL,        -- Stock ticker symbol
    open NUMERIC(12, 4) NOT NULL,       -- Open price
    high NUMERIC(12, 4) NOT NULL,       -- High price
    low NUMERIC(12, 4) NOT NULL,        -- Low price
    close NUMERIC(12, 4) NOT NULL,      -- Close price
    volume BIGINT NOT NULL,             -- Trading volume
    trade_count INTEGER,                -- Number of trades
    vwap NUMERIC(12, 6),               -- Volume weighted average price

    PRIMARY KEY (time, symbol)
);

SELECT create_hypertable(
    'stock_candles_1m',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS idx_1m_symbol_time
    ON stock_candles_1m (symbol, time DESC);

CREATE INDEX IF NOT EXISTS idx_1m_close
    ON stock_candles_1m (close, time DESC);

COMMENT ON TABLE stock_candles_1m IS '1-minute candles (optimized for 9am-12pm Ross Cameron strategy)';


-- 1-Hour Candles (full trading day 4am-8pm)
CREATE TABLE IF NOT EXISTS stock_candles_1h (
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
    'stock_candles_1h',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '7 days'
);

CREATE INDEX IF NOT EXISTS idx_1h_symbol_time
    ON stock_candles_1h (symbol, time DESC);

COMMENT ON TABLE stock_candles_1h IS '1-hour candles for broader trend analysis';


-- Daily Candles (for volume averages and longer-term analysis)
CREATE TABLE IF NOT EXISTS stock_candles_1d (
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
    'stock_candles_1d',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '30 days'
);

CREATE INDEX IF NOT EXISTS idx_1d_symbol_time
    ON stock_candles_1d (symbol, time DESC);

COMMENT ON TABLE stock_candles_1d IS 'Daily candles for volume calculations and backtesting';


-- Future timeframes (ready for when needed):
-- stock_candles_5m  - 5-minute candles
-- stock_candles_15m - 15-minute candles
-- stock_candles_30m - 30-minute candles


-- ============================================================================
-- TABLE 2: Real-time Snapshots
-- ============================================================================

CREATE TABLE IF NOT EXISTS stock_snapshots (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(10) NOT NULL,

    -- Latest Trade
    last_trade_price NUMERIC(12, 4),
    last_trade_size INTEGER,
    last_trade_time TIMESTAMPTZ,
    last_trade_exchange VARCHAR(5),

    -- Latest Quote (Bid/Ask)
    bid_price NUMERIC(12, 4),
    bid_size INTEGER,
    ask_price NUMERIC(12, 4),
    ask_size INTEGER,
    bid_exchange VARCHAR(5),
    ask_exchange VARCHAR(5),

    -- Calculated fields
    spread NUMERIC(12, 4),

    PRIMARY KEY (time, symbol)
);

SELECT create_hypertable(
    'stock_snapshots',
    'time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 hour'
);

CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_latest
    ON stock_snapshots (symbol, time DESC);

COMMENT ON TABLE stock_snapshots IS 'Real-time price snapshots for quick current price lookups';


-- ============================================================================
-- TABLE 3: Stock Metadata
-- ============================================================================

CREATE TABLE IF NOT EXISTS stock_metadata (
    symbol VARCHAR(10) PRIMARY KEY,
    name VARCHAR(255),
    exchange VARCHAR(10),
    asset_class VARCHAR(20),
    status VARCHAR(20),
    tradable BOOLEAN,
    marginable BOOLEAN,
    shortable BOOLEAN,
    easy_to_borrow BOOLEAN,
    fractionable BOOLEAN,

    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_metadata_tradable
    ON stock_metadata (tradable, status);

COMMENT ON TABLE stock_metadata IS 'Stock metadata and attributes';


-- ============================================================================
-- TABLE 4: Premarket Volume Cache
-- ============================================================================

CREATE TABLE IF NOT EXISTS premarket_volumes (
    date DATE NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    pm_volume BIGINT NOT NULL,
    pm_vwap NUMERIC(12, 6),
    pm_high NUMERIC(12, 4),
    pm_low NUMERIC(12, 4),
    pm_open NUMERIC(12, 4),
    pm_close NUMERIC(12, 4),
    yesterday_close NUMERIC(12, 4),
    pm_gain_pct NUMERIC(8, 4),

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

CREATE TABLE IF NOT EXISTS scanner_results (
    scan_time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    price NUMERIC(12, 4),
    pm_gain_pct NUMERIC(8, 4),
    pm_volume BIGINT,
    avg_pm_volume BIGINT,
    relative_volume NUMERIC(8, 4),
    avg_volume BIGINT,

    scanner_version VARCHAR(20),

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
-- RETENTION POLICIES (Timeframe-specific)
-- ============================================================================

-- Minute candles: 90 days (core trading window data)
SELECT add_retention_policy('stock_candles_1m', INTERVAL '90 days', if_not_exists => TRUE);

-- Hour candles: 1 year (longer-term analysis)
SELECT add_retention_policy('stock_candles_1h', INTERVAL '1 year', if_not_exists => TRUE);

-- Daily candles: 5 years (long-term backtesting)
SELECT add_retention_policy('stock_candles_1d', INTERVAL '5 years', if_not_exists => TRUE);

-- Snapshots: 7 days (only need recent for real-time)
SELECT add_retention_policy('stock_snapshots', INTERVAL '7 days', if_not_exists => TRUE);

-- Scanner results: 1 year
SELECT add_retention_policy('scanner_results', INTERVAL '1 year', if_not_exists => TRUE);


-- ============================================================================
-- HELPER FUNCTIONS (Updated for new table structure)
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
    -- Get today's volume up to p_datetime from 1m table
    SELECT COALESCE(SUM(volume), 0) INTO today_volume
    FROM stock_candles_1m
    WHERE symbol = p_symbol
      AND time <= p_datetime
      AND time >= DATE_TRUNC('day', p_datetime);

    -- Get average volume at same time over past N days
    SELECT AVG(daily_vol) INTO avg_historical_volume
    FROM (
        SELECT SUM(volume) AS daily_vol
        FROM stock_candles_1m
        WHERE symbol = p_symbol
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

-- Latest snapshot for each symbol
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
-- VERIFICATION QUERIES
-- ============================================================================

-- Verify tables
SELECT schemaname, tablename
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename LIKE 'stock_%'
ORDER BY tablename;

-- Verify hypertables
SELECT hypertable_name, num_chunks
FROM timescaledb_information.hypertables
WHERE hypertable_name LIKE 'stock_%'
ORDER BY hypertable_name;

COMMENT ON DATABASE CURRENT_DATABASE() IS 'Stock market data with TimescaleDB - Multi-timeframe architecture';
