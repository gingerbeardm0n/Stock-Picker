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
        Checks both 1m and 1d tables so live-collected data is found
        even before daily bars are written.

        Returns:
            List of dates
        """
        cursor = self.conn.cursor()

        # Union both tables - 1m catches today's live data, 1d catches backfilled history
        query = """
            SELECT DISTINCT trade_date FROM (
                SELECT time::date AS trade_date FROM stock_candles_1m
                WHERE time >= %s::date AND time <= %s::date
                UNION
                SELECT time::date AS trade_date FROM stock_candles_1d
                WHERE time >= %s::date AND time <= %s::date
            ) combined
            ORDER BY trade_date
        """

        cursor.execute(query, [start_date, end_date, start_date, end_date])
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
