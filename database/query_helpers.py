#!/usr/bin/env python3
"""
Database Query Helpers
Fetch historical data from TimescaleDB for backtesting and analysis.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz

load_dotenv()

DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:changeme123@localhost:5432/stockdata')

ET = pytz.timezone('America/New_York')


class StockDataDB:
    """Database interface for historical stock data"""

    def __init__(self):
        self.conn = psycopg2.connect(DB_CONN)

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
              AND time::date = %s::date
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') >= %s
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') < %s
            ORDER BY symbol, time
        """

        cursor.execute(query, [symbols, date, start_hour, end_hour])
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


    # ========================================================================
    # UTILITY QUERIES
    # ========================================================================

    def get_trading_days(self, start_date, end_date):
        """
        Get list of trading days (days with data) between dates.

        Returns:
            List of dates
        """
        cursor = self.conn.cursor()

        query = """
            SELECT DISTINCT time::date AS trade_date
            FROM stock_candles_1d
            WHERE time >= %s::date
              AND time <= %s::date
            ORDER BY trade_date
        """

        cursor.execute(query, [start_date, end_date])
        results = cursor.fetchall()
        cursor.close()

        return [row[0] for row in results]

    def get_symbols_with_data(self, date):
        """
        Get list of symbols that have data for a specific date.

        Returns:
            List of symbols
        """
        cursor = self.conn.cursor()

        query = """
            SELECT DISTINCT symbol
            FROM stock_candles_1d
            WHERE time::date = %s::date
            ORDER BY symbol
        """

        cursor.execute(query, [date])
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
