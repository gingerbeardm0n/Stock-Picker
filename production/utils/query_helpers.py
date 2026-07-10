#!/usr/bin/env python3
"""
Database Query Helpers
Fetch historical data from TimescaleDB for backtesting and analysis.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
import socket as _socket
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz

load_dotenv()

DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:changeme123@localhost:5432/stockdata')

ET = pytz.timezone('America/New_York')


class StockDataDB:
    """Database interface for historical stock data"""

    def __init__(self, socket_timeout: float = 60.0):
        # socket.setdefaulttimeout() applies to all sockets created in this call,
        # including psycopg2's internal socket — works on Windows unlike fromfd().
        _prev = _socket.getdefaulttimeout()
        if socket_timeout > 0:
            _socket.setdefaulttimeout(socket_timeout)
        try:
            self.conn = psycopg2.connect(
                DB_CONN,
                connect_timeout=10,
                options="-c statement_timeout=55000",
            )
        finally:
            _socket.setdefaulttimeout(_prev)  # restore global default

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


    # ========================================================================
    # SNAPSHOT QUERIES (Current Prices)
    # ========================================================================

    def get_latest_prices(self, symbols=None, as_of_date=None):
        """
        Get latest prices for symbols from daily data.

        Args:
            symbols: List of symbols (None = all symbols)
            as_of_date: Date to get prices for (None = most recent)

        Returns:
            Dict of {symbol: price}
        """
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        if as_of_date:
            # Get close price for specific date
            query = """
                SELECT DISTINCT ON (symbol)
                    symbol,
                    close AS price,
                    time
                FROM stock_candles_1d
                WHERE time::date <= %s::date
                {}
                ORDER BY symbol, time DESC
            """.format("AND symbol = ANY(%s)" if symbols else "")

            params = [as_of_date] + ([symbols] if symbols else [])
        else:
            # Get most recent close price
            query = """
                SELECT DISTINCT ON (symbol)
                    symbol,
                    close AS price,
                    time
                FROM stock_candles_1d
                {}
                ORDER BY symbol, time DESC
            """.format("WHERE symbol = ANY(%s)" if symbols else "")

            params = [symbols] if symbols else []

        cursor.execute(query, params)
        results = cursor.fetchall()
        cursor.close()

        return {row['symbol']: float(row['price']) for row in results}


    # ========================================================================
    # DAILY BAR QUERIES
    # ========================================================================

    def get_daily_bars(self, symbols, start_date, end_date):
        """
        Get daily OHLCV bars for symbols in date range.

        Returns:
            Dict of {symbol: [bars]} where each bar is a dict with OHLCV data
        """
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT
                time,
                symbol,
                open,
                high,
                low,
                close,
                volume,
                vwap
            FROM stock_candles_1d
            WHERE symbol = ANY(%s)
              AND time >= %s::date
              AND time <= %s::date
            ORDER BY symbol, time
        """

        cursor.execute(query, [symbols, start_date, end_date])
        results = cursor.fetchall()
        cursor.close()

        # Group by symbol
        data = {}
        for row in results:
            symbol = row['symbol']
            if symbol not in data:
                data[symbol] = []
            data[symbol].append(dict(row))

        return data

    def calculate_avg_volume(self, symbol, as_of_date, days_back=20):
        """
        Calculate average daily volume over past N days.

        Args:
            symbol: Stock symbol
            as_of_date: Date to calculate from
            days_back: Number of days to average (default 20)

        Returns:
            Average volume (int)
        """
        cursor = self.conn.cursor()

        query = """
            SELECT AVG(volume)::bigint AS avg_volume
            FROM (
                SELECT volume
                FROM stock_candles_1d
                WHERE symbol = %s
                  AND time < %s::date
                ORDER BY time DESC
                LIMIT %s
            ) sub
        """

        cursor.execute(query, [symbol, as_of_date, days_back])
        result = cursor.fetchone()
        cursor.close()

        return result[0] if result[0] else 0


    # ========================================================================
    # MINUTE BAR QUERIES (9am-12pm window)
    # ========================================================================

    def get_minute_bars(self, symbols, date, start_hour=9, end_hour=12):
        """
        Get minute bars for specific date and time window.

        Args:
            symbols: List of symbols
            date: Date to fetch (datetime.date or string 'YYYY-MM-DD')
            start_hour: Start hour (default 9 for 9am)
            end_hour: End hour (default 12 for 12pm)

        Returns:
            Dict of {symbol: [bars]}
        """
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        if isinstance(date, str):
            trade_date = datetime.strptime(date, '%Y-%m-%d').date()
        elif isinstance(date, datetime):
            trade_date = date.date()
        else:
            trade_date = date
        start_et = ET.localize(datetime.combine(trade_date, datetime.min.time()).replace(hour=start_hour, minute=0))
        end_et = ET.localize(datetime.combine(trade_date, datetime.min.time()).replace(hour=end_hour, minute=0))
        start_utc = start_et.astimezone(pytz.UTC)
        end_utc = end_et.astimezone(pytz.UTC)

        query = """
            SELECT
                time,
                symbol,
                open,
                high,
                low,
                close,
                volume,
                vwap
            FROM stock_candles_1m
            WHERE symbol = ANY(%s)
              AND time >= %s
              AND time < %s
            ORDER BY symbol, time
        """

        cursor.execute(query, [symbols, start_utc, end_utc])
        results = cursor.fetchall()
        cursor.close()

        # Group by symbol
        data = {}
        for row in results:
            symbol = row['symbol']
            if symbol not in data:
                data[symbol] = []
            data[symbol].append(dict(row))

        return data

    def get_hour_bars(self, symbols, date, start_hour=4, end_hour=8):
        """
        Get hourly bars for specific date and time window.

        Args:
            symbols: List of symbols
            date: Date to fetch (datetime.date or string 'YYYY-MM-DD')
            start_hour: Start hour (default 4 for 4am)
            end_hour: End hour (default 8 for 8am)

        Returns:
            Dict of {symbol: [bars]}
        """
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        if isinstance(date, str):
            trade_date = datetime.strptime(date, '%Y-%m-%d').date()
        elif isinstance(date, datetime):
            trade_date = date.date()
        else:
            trade_date = date
        start_et = ET.localize(datetime.combine(trade_date, datetime.min.time()).replace(hour=start_hour, minute=0))
        end_et = ET.localize(datetime.combine(trade_date, datetime.min.time()).replace(hour=end_hour, minute=0))
        start_utc = start_et.astimezone(pytz.UTC)
        end_utc = end_et.astimezone(pytz.UTC)

        query = """
            SELECT
                time,
                symbol,
                open,
                high,
                low,
                close,
                volume,
                vwap
            FROM stock_candles_1h
            WHERE symbol = ANY(%s)
              AND time >= %s
              AND time < %s
            ORDER BY symbol, time
        """

        cursor.execute(query, [symbols, start_utc, end_utc])
        results = cursor.fetchall()
        cursor.close()

        data = {}
        for row in results:
            symbol = row['symbol']
            if symbol not in data:
                data[symbol] = []
            data[symbol].append(dict(row))

        return data

    def calculate_morning_volume(self, symbol, date, start_hour=9, end_hour=12):
        """
        Calculate total volume during morning window (9am-12pm by default).

        Returns:
            Total volume (int)
        """
        cursor = self.conn.cursor()

        query = """
            SELECT COALESCE(SUM(volume), 0)::bigint AS total_volume
            FROM stock_candles_1m
            WHERE symbol = %s
              AND time::date = %s::date
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') >= %s
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') < %s
        """

        cursor.execute(query, [symbol, date, start_hour, end_hour])
        result = cursor.fetchone()
        cursor.close()

        return result[0] if result else 0


    # ========================================================================
    # RELATIVE VOLUME CALCULATION
    # ========================================================================

    def calculate_relative_volume(self, symbol, date, current_time_et, lookback_days=30):
        """
        Calculate Ross Cameron's relative volume metric.

        Relative Volume = (Volume so far today) / (Avg volume at this time over past N days)

        Args:
            symbol: Stock symbol
            date: Trading date
            current_time_et: Current time (datetime with ET timezone)
            lookback_days: Number of days to average (default 30)

        Returns:
            Relative volume ratio (float)
        """
        cursor = self.conn.cursor()

        # Get volume so far today up to current_time
        today_query = """
            SELECT COALESCE(SUM(volume), 0)::bigint AS today_volume
            FROM stock_candles_1m
            WHERE symbol = %s
              AND time::date = %s::date
              AND time <= %s
        """

        cursor.execute(today_query, [symbol, date, current_time_et])
        today_result = cursor.fetchone()
        today_volume = today_result[0] if today_result else 0

        # Get average volume at same time over past N days
        current_hour = current_time_et.hour
        current_minute = current_time_et.minute

        avg_query = """
            SELECT AVG(daily_vol)::numeric AS avg_volume
            FROM (
                SELECT DATE(time) AS trade_date, SUM(volume) AS daily_vol
                FROM stock_candles_1m
                WHERE symbol = %s
                  AND time::date < %s::date
                  AND time::date >= (%s::date - INTERVAL '%s days')
                  AND (
                      EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York')::int * 60 +
                      EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York')::int
                  ) <= (%s * 60 + %s)
                GROUP BY DATE(time)
            ) sub
        """

        cursor.execute(avg_query, [
            symbol,
            date,
            date,
            lookback_days,
            current_hour,
            current_minute
        ])
        avg_result = cursor.fetchone()
        avg_volume = float(avg_result[0]) if avg_result and avg_result[0] else 0

        cursor.close()

        # Calculate relative volume
        if avg_volume > 0:
            return today_volume / avg_volume
        else:
            return 0.0


    def get_avg_volume_at_time_batch(self, symbols, as_of_date, current_hour, current_minute, lookback_days=20,
                                     include_premarket_hourly: bool = False):
        """
        For each symbol, calculate the average volume from market open (4am ET)
        up to current_hour:current_minute, averaged over the past lookback_days.

        This is the correct denominator for Ross Cameron's relative volume:
            rel_vol = volume_so_far_today / avg_volume_at_this_time_historically

        Args:
            symbols:         List of stock tickers
            as_of_date:      The date being scanned (today or backtest date)
            current_hour:    ET hour of the scan (e.g. 9 for 9am)
            current_minute:  ET minute of the scan (e.g. 25 for 9:25am)
            lookback_days:   How many historical days to average over

        Returns:
            Dict of {symbol: avg_volume_float}
        """
        cursor = self.conn.cursor()

        if include_premarket_hourly:
            # Use hourly 4am-8am volume + minute 8am->current_time volume
            # This avoids relying on 1m data for 4am-8am when only 1h bars exist.
            hourly_query = """
                SELECT
                    symbol,
                    AVG(day_vol)::float AS avg_hourly_vol
                FROM (
                    SELECT
                        symbol,
                        time::date AS trade_date,
                        SUM(volume) AS day_vol
                    FROM stock_candles_1h
                    WHERE symbol = ANY(%s)
                      AND time::date >= %s::date - INTERVAL '%s days'
                      AND time::date < %s::date
                      AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') >= 4
                      AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') < 8
                    GROUP BY symbol, time::date
                ) daily_vols
                GROUP BY symbol
            """
            cursor.execute(hourly_query, [symbols, as_of_date, lookback_days, as_of_date])
            hourly_rows = cursor.fetchall()
            hourly_avg = {row[0]: float(row[1]) for row in hourly_rows}

            # Minute volume from 8am to current time
            minute_query = """
                SELECT
                    symbol,
                    AVG(day_vol)::float AS avg_minute_vol
                FROM (
                    SELECT
                        symbol,
                        time::date AS trade_date,
                        SUM(volume) AS day_vol
                    FROM stock_candles_1m
                    WHERE symbol = ANY(%s)
                      AND time::date >= %s::date - INTERVAL '%s days'
                      AND time::date < %s::date
                      AND (
                          EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') > 8
                          OR (
                              EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') = 8
                              AND EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York') >= 0
                          )
                      )
                      AND (
                          EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') < %s
                          OR (
                              EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') = %s
                              AND EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York') <= %s
                          )
                      )
                    GROUP BY symbol, time::date
                ) daily_vols
                GROUP BY symbol
            """
            cursor.execute(minute_query, [
                symbols,
                as_of_date, lookback_days, as_of_date,
                current_hour, current_hour, current_minute
            ])
            minute_rows = cursor.fetchall()
            minute_avg = {row[0]: float(row[1]) for row in minute_rows}
            cursor.close()

            combined = {}
            for sym in set(list(hourly_avg.keys()) + list(minute_avg.keys())):
                combined[sym] = hourly_avg.get(sym, 0.0) + minute_avg.get(sym, 0.0)
            return combined

        query = """
            SELECT
                symbol,
                AVG(day_vol)::float AS avg_vol_at_time
            FROM (
                SELECT
                    symbol,
                    time::date AS trade_date,
                    SUM(volume) AS day_vol
                FROM stock_candles_1m
                WHERE symbol = ANY(%s)
                  AND time::date >= %s::date - INTERVAL '%s days'
                  AND time::date < %s::date
                  AND (
                      EXTRACT(HOUR   FROM time AT TIME ZONE 'America/New_York') > 4
                      OR (
                          EXTRACT(HOUR   FROM time AT TIME ZONE 'America/New_York') = 4
                          AND EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York') >= 0
                      )
                  )
                  AND (
                      EXTRACT(HOUR   FROM time AT TIME ZONE 'America/New_York') < %s
                      OR (
                          EXTRACT(HOUR   FROM time AT TIME ZONE 'America/New_York') = %s
                          AND EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York') <= %s
                      )
                  )
                GROUP BY symbol, time::date
            ) daily_vols
            GROUP BY symbol
        """

        cursor.execute(query, [
            symbols,
            as_of_date, lookback_days, as_of_date,
            current_hour, current_hour, current_minute
        ])
        rows = cursor.fetchall()
        cursor.close()

        return {row[0]: float(row[1]) for row in rows}

    # ========================================================================
    # FUNDAMENTALS QUERIES (Float + Market Cap)
    # ========================================================================

    def get_fundamentals_batch(self, symbols):
        """
        Get float and market cap for a list of symbols from stock_fundamentals table.

        Returns:
            Dict of {symbol: {'float_shares': int, 'market_cap': int, 'company_name': str}}
            Only includes symbols that have data in the table.
        """
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT symbol, float_shares, market_cap, company_name, industry
            FROM stock_fundamentals
            WHERE symbol = ANY(%s)
        """

        cursor.execute(query, [symbols])
        results = cursor.fetchall()
        cursor.close()

        return {
            row['symbol']: {
                'float_shares': row['float_shares'],
                'market_cap':   row['market_cap'],
                'company_name': row['company_name'],
                'industry':     row['industry'],
            }
            for row in results
        }

    def get_intraday_bars_batch(self, symbols: list, trade_date, until_utc) -> dict:
        """
        Get all 1-minute bars for symbols from 4am ET on trade_date up to until_utc.

        Used by LiveScanner.startup_preload() to seed _bar_history on restart so
        patterns/trend/EMA/MACD are calculable immediately rather than waiting
        35–40 minutes for enough bars to accumulate via WebSocket.

        Returns:
            Dict of {symbol: [bar_dicts]} where each bar dict matches AlpacaBarStream
            output: {'symbol', 'time' (UTC-aware), 'open', 'high', 'low', 'close', 'volume'}
        """
        from datetime import time as dtime
        start_et  = ET.localize(datetime.combine(trade_date, dtime(4, 0)))
        start_utc = start_et.astimezone(pytz.UTC)

        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        query = """
            SELECT time, symbol, open, high, low, close, volume
            FROM stock_candles_1m
            WHERE symbol = ANY(%s)
              AND time >= %s
              AND time <= %s
            ORDER BY symbol, time
        """
        cursor.execute(query, [symbols, start_utc, until_utc])
        rows = cursor.fetchall()
        cursor.close()

        data: dict = {}
        for row in rows:
            sym = row['symbol']
            if sym not in data:
                data[sym] = []
            t = row['time']
            if t.tzinfo is None:
                t = pytz.UTC.localize(t)
            data[sym].append({
                'symbol': sym,
                'time':   t,
                'open':   float(row['open']),
                'high':   float(row['high']),
                'low':    float(row['low']),
                'close':  float(row['close']),
                'volume': int(row['volume']),
            })

        return data

    def get_premarket_snapshot(self, trade_date, snapshot_time_utc):
        """
        Get premarket state for all symbols: last price and cumulative volume
        from 4am ET up to snapshot_time_utc.

        Used by the 9:25 / 9:28 premarket DB scan to build the watchlist
        before market open. Reads from what collect_data.py has already written.

        Returns:
            Dict of {symbol: {'last_close': float, 'total_volume': int}}
        """
        from datetime import time as dtime
        start_et = ET.localize(datetime.combine(trade_date, dtime(4, 0)))
        start_utc = start_et.astimezone(pytz.UTC)

        cursor = self.conn.cursor()
        query = """
            SELECT
                symbol,
                SUM(volume)                               AS total_volume,
                (array_agg(close ORDER BY time DESC))[1]  AS last_close
            FROM stock_candles_1m
            WHERE time >= %s
              AND time <= %s
            GROUP BY symbol
            HAVING SUM(volume) > 0
        """
        cursor.execute(query, [start_utc, snapshot_time_utc])
        rows = cursor.fetchall()
        cursor.close()

        return {
            row[0]: {'last_close': float(row[2]), 'total_volume': int(row[1])}
            for row in rows
            if row[2] is not None
        }

    # ========================================================================
    # UTILITY QUERIES
    # ========================================================================

    def get_trading_days(self, start_date, end_date):
        """
        Get list of trading days (days with data) between dates.

        Strategy: try daily_gappers cache first (instant), then stock_candles_1d,
        then stock_candles_1m as last resort. The 1m table DISTINCT scan is very
        slow on large datasets so we avoid it when possible.

        Returns:
            List of dates
        """
        cursor = self.conn.cursor()

        # 1) Try daily_gappers cache (fastest — already indexed by trade_date)
        cursor.execute("""
            SELECT DISTINCT trade_date FROM daily_gappers
            WHERE trade_date >= %s::date AND trade_date <= %s::date
            ORDER BY trade_date
        """, [start_date, end_date])
        results = cursor.fetchall()
        if results:
            cursor.close()
            return [row[0] for row in results]

        # 2) Fall back to stock_candles_1d (fast — much smaller than 1m)
        cursor.execute("""
            SELECT DISTINCT time::date AS trade_date FROM stock_candles_1d
            WHERE time >= %s::date AND time <= %s::date
            ORDER BY trade_date
        """, [start_date, end_date])
        results = cursor.fetchall()
        if results:
            cursor.close()
            return [row[0] for row in results]

        # 3) Last resort — 1m table (slow but catches live-only data)
        cursor.execute("""
            SELECT DISTINCT time::date AS trade_date FROM stock_candles_1m
            WHERE time >= %s::date AND time <= %s::date
            ORDER BY trade_date
        """, [start_date, end_date])
        results = cursor.fetchall()
        cursor.close()

        return [row[0] for row in results]

    def get_symbols_with_data(self, date):
        """
        Get list of symbols that have data for a specific date.
        Checks both 1m and 1d tables so today's live data is found
        even before daily bars are written.

        Returns:
            List of symbols
        """
        cursor = self.conn.cursor()

        query = """
            SELECT DISTINCT symbol FROM (
                SELECT DISTINCT symbol FROM stock_candles_1d
                WHERE time::date = %s::date
                UNION
                SELECT DISTINCT symbol FROM stock_candles_1m
                WHERE time::date = %s::date
            ) combined
            ORDER BY symbol
        """

        cursor.execute(query, [date, date])
        results = cursor.fetchall()
        cursor.close()

        return [row[0] for row in results]


    # ========================================================================
    # GAPPER DISCOVERY (shared by scalp simulation + news backfill)
    # ========================================================================

    def find_gappers(self, trade_date, min_gap_pct: float = 10.0,
                     max_price: float = 50.0, limit: int = 50):
        """
        Find stocks gapping up >= min_gap_pct on a given date.

        Reads from the `daily_gappers` cache table (pre-computed, ~1-5ms).
        Falls back to live computation from stock_candles_1d if cache miss.

        This is the SINGLE SOURCE OF TRUTH for gapper discovery.
        Used by scalp_simulation.py, backfill_news.py, and Optuna optimizer.

        Args:
            trade_date:   date or string 'YYYY-MM-DD'
            min_gap_pct:  minimum gap % to qualify (default 10%)
            max_price:    maximum stock price (default $50)
            limit:        max candidates returned (default 50)

        Returns:
            List of dicts sorted by gap_pct DESC:
            [{symbol, open_price, prior_close, gap_pct, daily_volume}, ...]
        """
        # Try cache first (fast path: ~1-5ms vs ~500ms-2s)
        result = self._find_gappers_cached(trade_date, min_gap_pct, max_price, limit)
        if result is not None:
            return result

        # Fallback: live computation (for dates not yet in cache)
        return self._find_gappers_live(trade_date, min_gap_pct, max_price, limit)

    def _find_gappers_cached(self, trade_date, min_gap_pct, max_price, limit):
        """Read from daily_gappers cache table. Returns None on cache miss."""
        cursor = self.conn.cursor()

        # Check if this date exists in cache
        cursor.execute(
            "SELECT COUNT(*) FROM daily_gappers WHERE trade_date = %s::date",
            [trade_date],
        )
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.close()
            return None  # cache miss — caller will use live path

        query = """
            SELECT symbol, open_price, prior_close, gap_pct, daily_volume
            FROM daily_gappers
            WHERE trade_date = %s::date
              AND gap_pct >= %s
              AND open_price <= %s
            ORDER BY gap_pct DESC
            LIMIT %s
        """
        cursor.execute(query, [trade_date, min_gap_pct, max_price, limit])
        rows = cursor.fetchall()
        cursor.close()

        return [
            {
                'symbol': row[0],
                'open_price': float(row[1]),
                'prior_close': float(row[2]),
                'gap_pct': float(row[3]),
                'daily_volume': int(row[4]),
            }
            for row in rows
        ]

    def _find_gappers_live(self, trade_date, min_gap_pct, max_price, limit):
        """Compute gappers from stock_candles_1d (slow path, for uncached dates)."""
        cursor = self.conn.cursor()

        query = """
            WITH today AS (
                SELECT symbol, open, high, close, volume
                FROM stock_candles_1d
                WHERE time::date = %s::date
                  AND open > 0
            ),
            yesterday AS (
                SELECT DISTINCT ON (symbol) symbol, close AS prior_close
                FROM stock_candles_1d
                WHERE time::date < %s::date
                ORDER BY symbol, time DESC
            )
            SELECT
                t.symbol,
                t.open AS open_price,
                y.prior_close,
                CASE WHEN y.prior_close > 0
                     THEN ((t.open - y.prior_close) / y.prior_close * 100)
                     ELSE 0 END AS gap_pct,
                t.volume
            FROM today t
            JOIN yesterday y ON t.symbol = y.symbol
            WHERE y.prior_close > 0
              AND t.open > 0
              AND t.open <= %s
              AND ((t.open - y.prior_close) / y.prior_close * 100) >= %s
            ORDER BY gap_pct DESC
            LIMIT %s
        """

        cursor.execute(query, [trade_date, trade_date, max_price, min_gap_pct, limit])
        rows = cursor.fetchall()
        cursor.close()

        return [
            {
                'symbol': row[0],
                'open_price': float(row[1]),
                'prior_close': float(row[2]),
                'gap_pct': float(row[3]),
                'daily_volume': int(row[4]),
            }
            for row in rows
        ]

    def refresh_daily_gappers(self, trade_date, min_gap_pct: float = 5.0):
        """
        Recompute and cache daily_gappers for a single date.
        Used for backfilling new dates or refreshing stale data.
        Stores all gappers >= min_gap_pct (default 5%) so Optuna can
        tune the threshold without re-caching.
        """
        gappers = self._find_gappers_live(trade_date, min_gap_pct, max_price=9999, limit=9999)
        if not gappers:
            return 0

        cursor = self.conn.cursor()
        inserted = 0
        for g in gappers:
            cursor.execute("""
                INSERT INTO daily_gappers
                    (trade_date, symbol, open_price, prior_close, gap_pct, daily_volume)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (trade_date, symbol) DO NOTHING
            """, [
                trade_date, g['symbol'], g['open_price'],
                g['prior_close'], g['gap_pct'], g['daily_volume'],
            ])
            inserted += 1
        self.conn.commit()
        cursor.close()
        return inserted

    # ========================================================================
    # NEWS QUERIES (for Opening Bell Scalp strategy)
    # ========================================================================

    def get_news_for_symbol(self, symbol, before_time, hours_back=24):
        """
        Get cached news articles for a symbol in a time window.

        Args:
            symbol:      Stock ticker
            before_time: Upper bound (datetime, tz-aware)
            hours_back:  How many hours before before_time to search

        Returns:
            List of dicts with headline, source, created_at, news_tier, etc.
        """
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        start_time = before_time - timedelta(hours=hours_back)

        query = """
            SELECT symbol, headline, source, created_at, summary, url,
                   symbol_count, is_specific, news_tier
            FROM stock_news
            WHERE symbol = %s
              AND created_at >= %s
              AND created_at <= %s
            ORDER BY created_at DESC
        """
        cursor.execute(query, [symbol, start_time, before_time])
        results = [dict(row) for row in cursor.fetchall()]
        cursor.close()
        return results

    def get_news_tier(self, symbol, before_time, hours_back=24):
        """
        Get the best news tier for a symbol in a time window.
        Returns the highest-quality tier found: tier1 > tier2 > tier3 > presence > none.
        """
        articles = self.get_news_for_symbol(symbol, before_time, hours_back)
        if not articles:
            return 'none'

        tier_priority = {'tier1': 0, 'tier2': 1, 'tier3': 2, 'presence': 3, 'none': 4}
        best = min(articles, key=lambda a: tier_priority.get(a.get('news_tier', 'none'), 4))
        return best.get('news_tier', 'none')

    def get_news_tier_and_confidence(self, symbol, before_time, hours_back=24):
        """
        Get best news tier + source agreement count for a symbol.

        Returns (tier: str, sources_with_hits: int).
        sources_with_hits counts distinct source prefixes (finnhub, alpaca, etc.)
        that had specific articles. 2+ = corroborated catalyst.
        """
        articles = self.get_news_for_symbol(symbol, before_time, hours_back)
        if not articles:
            return 'none', 0

        tier_priority = {'tier1': 0, 'tier2': 1, 'tier3': 2, 'presence': 3, 'none': 4}
        best = min(articles, key=lambda a: tier_priority.get(a.get('news_tier', 'none'), 4))
        tier = best.get('news_tier', 'none')

        source_prefixes = set()
        for a in articles:
            src = a.get('source', '')
            if src and ':' in src:
                source_prefixes.add(src.split(':')[0])
            elif src:
                source_prefixes.add(src)
        sources_with_hits = len(source_prefixes)

        return tier, sources_with_hits

    def insert_news_batch(self, articles):
        """
        Batch-insert news articles into stock_news table.
        Skips duplicates via ON CONFLICT.

        Args:
            articles: List of dicts with keys: symbol, headline, source,
                     created_at, summary, url, symbol_count, is_specific, news_tier
        """
        if not articles:
            return 0

        cursor = self.conn.cursor()
        inserted = 0
        for a in articles:
            try:
                cursor.execute("""
                    INSERT INTO stock_news
                        (symbol, headline, source, created_at, summary, url,
                         symbol_count, is_specific, news_tier)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol, headline, created_at) DO NOTHING
                """, [
                    a['symbol'], a['headline'], a.get('source'),
                    a['created_at'], a.get('summary'), a.get('url'),
                    a.get('symbol_count'), a.get('is_specific'),
                    a.get('news_tier', 'none'),
                ])
                inserted += 1
            except Exception:
                self.conn.rollback()
                continue
        self.conn.commit()
        cursor.close()
        return inserted

    def get_news_coverage_stats(self, start_date, end_date):
        """Get news coverage stats for a date range. Useful for backfill monitoring."""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        query = """
            SELECT
                created_at::date AS news_date,
                COUNT(*) AS article_count,
                COUNT(DISTINCT symbol) AS symbol_count,
                COUNT(*) FILTER (WHERE news_tier IN ('tier1', 'tier2')) AS catalyst_count
            FROM stock_news
            WHERE created_at >= %s::date
              AND created_at < %s::date + INTERVAL '1 day'
            GROUP BY created_at::date
            ORDER BY news_date
        """
        cursor.execute(query, [start_date, end_date])
        results = [dict(row) for row in cursor.fetchall()]
        cursor.close()
        return results


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def get_backtest_data(symbol, date):
    """
    Get all data needed for backtesting a single stock on a specific date.

    Returns:
        Dict with:
        - daily_bars: 20 days of daily data (for avg volume)
        - minute_bars: Morning window bars (9am-12pm)
        - avg_volume: 20-day average volume
        - morning_volume: Total morning volume
        - relative_volume: Calculated at 12pm
    """
    with StockDataDB() as db:
        # Get 20 days of daily bars
        start = date - timedelta(days=30)
        daily_data = db.get_daily_bars([symbol], start, date)
        daily_bars = daily_data.get(symbol, [])

        # Get minute bars for the date
        minute_data = db.get_minute_bars([symbol], date)
        minute_bars = minute_data.get(symbol, [])

        # Calculate metrics
        avg_volume = db.calculate_avg_volume(symbol, date, days_back=20)
        morning_volume = db.calculate_morning_volume(symbol, date)

        # Calculate relative volume at 12pm ET
        noon_et = ET.localize(datetime.combine(date, datetime.min.time().replace(hour=12)))
        relative_volume = db.calculate_relative_volume(symbol, date, noon_et)

        return {
            'symbol': symbol,
            'date': date,
            'daily_bars': daily_bars,
            'minute_bars': minute_bars,
            'avg_volume': avg_volume,
            'morning_volume': morning_volume,
            'relative_volume': relative_volume
        }
