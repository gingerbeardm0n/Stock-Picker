"""
Alpaca REST Data Fetcher
========================
Wraps StockHistoricalDataClient for two live-trading use cases:

  1. get_snapshots_batch()  — current price + prev day close for all symbols
                              (replaces the collect_data.py DB read at 9:25/9:28)

  2. get_bars_since_4am()   — 1-minute bars from 4am ET to now for a symbol list
                              (replaces the DB bar-history / volume seed queries)

The DB is still used for:
  - Prior day closes (stock_candles_1d, from backfill)
  - Fundamentals (stock_fundamentals, from fetch_fundamentals.py)
  - Rel-vol denominator (historical avg volume from past 30 days)

collect_data.py is no longer required for live trading.
"""

import logging
from datetime import datetime, date, time as dtime

import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame

logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')

# Alpaca snapshot endpoint limit per request
_SNAPSHOT_BATCH = 1_000


class AlpacaDataFetcher:
    """
    Thin REST client for fetching today's intraday data directly from Alpaca.
    One instance lives inside LiveScanner for the duration of the session.
    """

    def __init__(self, api_key: str, secret_key: str):
        self._client = StockHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )

    def get_snapshots_batch(self, symbols: list[str]) -> dict:
        """
        Return latest price + previous day close for every symbol.
        Batches into groups of 1,000 to stay within API limits.

        Returns:
            {symbol: {'price': float, 'prev_close': float}}
            Only includes symbols where both values are available.
        """
        out: dict = {}
        total_batches = (len(symbols) + _SNAPSHOT_BATCH - 1) // _SNAPSHOT_BATCH

        for i in range(0, len(symbols), _SNAPSHOT_BATCH):
            batch = symbols[i:i + _SNAPSHOT_BATCH]
            batch_num = i // _SNAPSHOT_BATCH + 1
            try:
                resp = self._client.get_stock_snapshot(
                    StockSnapshotRequest(symbol_or_symbols=batch)
                )
                for sym, snap in resp.items():
                    # Current price: latest trade if available, else latest daily bar close
                    price = None
                    if snap.latest_trade:
                        price = float(snap.latest_trade.price)
                    elif snap.daily_bar:
                        price = float(snap.daily_bar.close)
                    if price:
                        out[sym] = {'price': price}
            except Exception as e:
                logger.warning(
                    f"Snapshot batch {batch_num}/{total_batches} failed "
                    f"(symbols {i}–{i+len(batch)}): {e}"
                )

        return out

    def get_bars_since_4am(self, symbols: list[str], until_utc: datetime = None) -> dict:
        """
        Fetch 1-minute bars from 4:00 AM ET today through until_utc (default: now)
        for the given symbols.

        Uses SIP feed (requires Alpaca premium data subscription).

        Returns:
            {symbol: [bar_dicts]} — same dict format as AlpacaBarStream:
            {'symbol', 'time' (UTC-aware datetime), 'open', 'high', 'low', 'close', 'volume'}
            Only includes symbols that have at least one bar.
        """
        if not symbols:
            return {}

        today_et  = datetime.now(ET).date()
        start_et  = ET.localize(datetime.combine(today_et, dtime(4, 0)))
        end_dt    = until_utc or datetime.now(pytz.UTC)

        try:
            resp = self._client.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols=symbols,
                    timeframe=TimeFrame.Minute,
                    start=start_et,
                    end=end_dt,
                    feed='sip',
                )
            )
        except Exception as e:
            logger.warning(f"get_bars_since_4am failed for {len(symbols)} symbols: {e}")
            return {}

        out: dict = {}
        bars_data = resp.data if hasattr(resp, 'data') else {}
        for sym, bars in bars_data.items():
            if not bars:
                continue
            out[sym] = [
                {
                    'symbol': sym,
                    'time':   bar.timestamp if bar.timestamp.tzinfo
                              else pytz.UTC.localize(bar.timestamp),
                    'open':   float(bar.open),
                    'high':   float(bar.high),
                    'low':    float(bar.low),
                    'close':  float(bar.close),
                    'volume': int(bar.volume),
                }
                for bar in bars
            ]

        return out
