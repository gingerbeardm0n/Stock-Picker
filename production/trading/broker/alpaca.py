"""
Alpaca Broker and Data Feed
============================
Concrete BrokerInterface + DataFeedInterface + AlpacaBarStream using alpaca-py.

Requires: pip install alpaca-py

To re-activate Alpaca:
    1. pip install alpaca-py
    2. Add to .env.paper or .env.live:
           BROKER=alpaca
           APCA_API_KEY_ID=<key>
           APCA_API_SECRET_KEY=<secret>
    3. config.py get_broker() / get_data_feed() will pick up the change.

Usage:
    from trading.broker.alpaca import AlpacaBroker, AlpacaDataFeed, AlpacaBarStream
"""

from __future__ import annotations

import logging
import queue
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytz

from trading.broker.base import (
    BrokerInterface, DataFeedInterface,
    OrderResult, QuoteResult, PositionResult, BarResult,
)

logger = logging.getLogger(__name__)
ET = pytz.timezone('America/New_York')

# Graceful import — module loads even if alpaca-py is not installed.
# Calling any method on AlpacaBroker / AlpacaDataFeed without the package
# raises ImportError with a clear installation message.
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import (
        LimitOrderRequest, MarketOrderRequest, StopOrderRequest,
    )
    from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
    from alpaca.data.timeframe import TimeFrame
    _ALPACA_AVAILABLE = True
except ImportError:
    _ALPACA_AVAILABLE = False


def _require_alpaca():
    if not _ALPACA_AVAILABLE:
        raise ImportError(
            "alpaca-py is required for AlpacaBroker / AlpacaDataFeed.\n"
            "Install with:  pip install alpaca-py\n"
            "Then add BROKER=alpaca to your .env.paper / .env.live."
        )


def _normalize_alpaca_status(status) -> str:
    """Map alpaca OrderStatus enum (or string) to normalized status string."""
    s = str(status).lower().replace('orderstatus.', '')
    if s in ('new', 'pending_new', 'accepted', 'accepted_for_bidding'):
        return 'open'
    if s == 'partially_filled':
        return 'partially_filled'
    if s == 'filled':
        return 'filled'
    if s in ('canceled', 'cancelled', 'done_for_day'):
        return 'cancelled'
    if s in ('expired',):
        return 'expired'
    if s in ('rejected', 'suspended', 'stopped'):
        return 'rejected'
    return s


# ── AlpacaBroker ──────────────────────────────────────────────────────────────

class AlpacaBroker(BrokerInterface):
    """Order execution via Alpaca alpaca-py SDK."""

    ENTRY_LIMIT_BUFFER = 0.10    # Marketable limit: ask + $0.10

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        _require_alpaca()
        self._client = TradingClient(
            api_key=api_key, secret_key=secret_key, paper=paper,
        )
        logger.info(f"AlpacaBroker initialized ({'paper' if paper else 'LIVE'})")

    def place_limit_buy(self, symbol: str, qty: int, limit_price: float) -> OrderResult:
        logger.info(f"LIMIT BUY: {qty} {symbol} @ ${limit_price:.2f}")
        order = self._client.submit_order(LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            limit_price=limit_price,
        ))
        return OrderResult(
            order_id=str(order.id),
            status=_normalize_alpaca_status(order.status),
        )

    def place_stop_sell(self, symbol: str, qty: int, stop_price: float) -> OrderResult:
        logger.info(f"STOP SELL: {qty} {symbol} stop @ ${stop_price:.2f}")
        order = self._client.submit_order(StopOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            type=OrderType.STOP,
            time_in_force=TimeInForce.DAY,
            stop_price=stop_price,
        ))
        return OrderResult(
            order_id=str(order.id),
            status=_normalize_alpaca_status(order.status),
        )

    def place_market_buy(self, symbol: str, qty: int) -> OrderResult:
        logger.info(f"MARKET BUY: {qty} {symbol}")
        order = self._client.submit_order(MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        ))
        return OrderResult(
            order_id=str(order.id),
            status=_normalize_alpaca_status(order.status),
        )

    def place_limit_sell(self, symbol: str, qty: int, limit_price: float) -> OrderResult:
        logger.info(f"LIMIT SELL: {qty} {symbol} @ ${limit_price:.2f}")
        order = self._client.submit_order(LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            limit_price=limit_price,
        ))
        return OrderResult(
            order_id=str(order.id),
            status=_normalize_alpaca_status(order.status),
        )

    def place_market_sell(self, symbol: str, qty: int) -> OrderResult:
        logger.info(f"MARKET SELL: {qty} {symbol}")
        order = self._client.submit_order(MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        ))
        return OrderResult(
            order_id=str(order.id),
            status=_normalize_alpaca_status(order.status),
        )

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._client.cancel_order_by_id(order_id)
            logger.info(f"Cancelled order {order_id}")
            return True
        except Exception as e:
            logger.warning(f"Cancel order {order_id} failed: {e}")
            return False

    def get_order(self, order_id: str) -> OrderResult:
        order = self._client.get_order_by_id(order_id)
        return OrderResult(
            order_id=str(order.id),
            status=_normalize_alpaca_status(order.status),
            filled_qty=int(float(order.filled_qty or 0)),
            filled_price=float(order.filled_avg_price or 0),
        )

    def get_account_balance(self) -> float:
        return float(self._client.get_account().cash)

    def get_position(self, symbol: str) -> Optional[PositionResult]:
        try:
            pos = self._client.get_open_position(symbol)
            return PositionResult(
                symbol=symbol,
                qty=int(pos.qty),
                avg_price=float(pos.avg_entry_price),
            )
        except Exception:
            return None


# ── AlpacaDataFeed ────────────────────────────────────────────────────────────

class AlpacaDataFeed(DataFeedInterface):
    """
    Market data via Alpaca's market data API.

    get_quotes()         — batch snapshot (latest quote)
    get_bars_since_4am() — historical bars from 4am ET today
    get_prior_closes()   — prior day close via daily bars
    """

    QUOTE_BATCH_SIZE = 1000    # Alpaca handles large batches efficiently

    def __init__(self, api_key: str, secret_key: str):
        _require_alpaca()
        self._client = StockHistoricalDataClient(
            api_key=api_key, secret_key=secret_key
        )

    def get_quotes(self, symbols: list[str]) -> dict[str, QuoteResult]:
        results: dict[str, QuoteResult] = {}
        for i in range(0, len(symbols), self.QUOTE_BATCH_SIZE):
            batch = symbols[i : i + self.QUOTE_BATCH_SIZE]
            try:
                resp = self._client.get_stock_latest_quote(
                    StockLatestQuoteRequest(symbol_or_symbols=batch)
                )
                for sym, q in resp.items():
                    ask = float(q.ask_price or 0)
                    bid = float(q.bid_price or 0)
                    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else ask or bid
                    results[sym] = QuoteResult(
                        symbol=sym,
                        bid=bid,
                        ask=ask,
                        last=mid,       # midpoint; latest quote has no last-trade field
                        prev_close=0.0, # not in quote snapshot; caller must get_prior_closes()
                    )
            except Exception as e:
                logger.warning(f"Alpaca quote batch failed: {e}")
        return results

    def get_bars_since_4am(
        self,
        symbols: list[str],
        until_utc: datetime | None = None,
    ) -> dict[str, list[BarResult]]:
        now_et   = (until_utc or datetime.now(timezone.utc)).astimezone(ET)
        today    = now_et.date()
        start_et = ET.localize(datetime(today.year, today.month, today.day, 4, 0))
        results: dict[str, list[BarResult]] = {}
        try:
            resp = self._client.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Minute,
                start=start_et.astimezone(timezone.utc),
                end=until_utc or datetime.now(timezone.utc),
            ))
            bars_data = resp.data if hasattr(resp, 'data') else resp
            for sym, bar_list in bars_data.items():
                bars = [
                    BarResult(
                        time=b.timestamp.replace(tzinfo=timezone.utc)
                             if b.timestamp.tzinfo is None
                             else b.timestamp.astimezone(timezone.utc),
                        open=float(b.open),
                        high=float(b.high),
                        low=float(b.low),
                        close=float(b.close),
                        volume=int(b.volume),
                        vwap=float(b.vwap or 0),
                    )
                    for b in bar_list
                ]
                if bars:
                    results[sym] = bars
        except Exception as e:
            logger.error(f"Alpaca bars fetch failed: {e}")
        return results

    def get_historical_minute_bars(
        self,
        symbols: list[str],
        lookback_days: int = 30,
    ) -> dict[str, list[BarResult]]:
        """
        Fetch minute bars from 4am-12pm ET for the last `lookback_days` trading days.
        Used to build per-symbol cumulative-volume baselines for unknown gappers.
        Returns all days concatenated; caller groups by date.

        NOTE: Alpaca free-tier SIP clamp means today's intraday bars are not
        available. This is fine — we only need the historical avg denominator.
        """
        from datetime import date, timedelta as td
        today = date.today()
        # 2× calendar buffer to clear weekends/holidays
        start_date = today - td(days=lookback_days * 2)
        end_date   = today - td(days=1)   # exclude today (SIP clamp)

        start_et = ET.localize(
            datetime(start_date.year, start_date.month, start_date.day, 4, 0))
        end_et   = ET.localize(
            datetime(end_date.year,   end_date.month,   end_date.day,  12, 0))

        results: dict[str, list[BarResult]] = {}
        BATCH = 5   # small batches — large date range, avoid response-size timeouts
        for i in range(0, len(symbols), BATCH):
            batch = symbols[i : i + BATCH]
            try:
                resp = self._client.get_stock_bars(StockBarsRequest(
                    symbol_or_symbols=batch,
                    timeframe=TimeFrame.Minute,
                    start=start_et.astimezone(timezone.utc),
                    end=end_et.astimezone(timezone.utc),
                ))
                bars_data = resp.data if hasattr(resp, 'data') else resp
                for sym, bar_list in bars_data.items():
                    results[sym] = [
                        BarResult(
                            time=(b.timestamp.replace(tzinfo=timezone.utc)
                                  if b.timestamp.tzinfo is None
                                  else b.timestamp.astimezone(timezone.utc)),
                            open=float(b.open),
                            high=float(b.high),
                            low=float(b.low),
                            close=float(b.close),
                            volume=int(b.volume),
                            vwap=float(b.vwap or 0),
                        )
                        for b in bar_list
                    ]
            except Exception as e:
                logger.warning(f"Historical bar fetch failed for {batch}: {e}")
        return results

    def get_prior_closes(self, symbols: list[str]) -> dict[str, float]:
        """Prior day's close via daily bars (last bar in a 5-day window)."""
        from datetime import date, timedelta as td
        today = date.today()
        start = today - td(days=5)   # handles weekends
        results = {}
        try:
            resp = self._client.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Day,
                start=datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
                end=datetime(today.year, today.month, today.day, tzinfo=timezone.utc),
            ))
            bars_data = resp.data if hasattr(resp, 'data') else resp
            for sym, bar_list in bars_data.items():
                if bar_list:
                    results[sym] = float(bar_list[-1].close)
        except Exception as e:
            logger.error(f"Alpaca prior close fetch failed: {e}")
        return results


# ── AlpacaBarStream ───────────────────────────────────────────────────────────

class AlpacaBarStream:
    """
    WebSocket stream of 1-minute bars from Alpaca.

    Streams minute bars for all subscribed symbols and pushes them to bar_queue
    as dicts. Run start() in a background daemon thread.

    Bar dict format matches TradierBarPoller output (same key names):
        {'symbol', 'time' (UTC datetime), 'open', 'high', 'low', 'close', 'volume', 'vwap'}
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        symbols: list[str],
        bar_queue: queue.Queue,
    ):
        _require_alpaca()
        self._api_key    = api_key
        self._secret_key = secret_key
        self._symbols    = symbols
        self._bar_queue  = bar_queue
        self._stream     = None

    def start(self):
        """Blocking. Run in a background daemon thread."""
        from alpaca.data.live import StockDataStream
        self._stream = StockDataStream(self._api_key, self._secret_key)

        async def _bar_handler(bar):
            ts = bar.timestamp
            bar_dict = {
                'symbol': bar.symbol,
                'time':   ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None
                          else ts.astimezone(timezone.utc),
                'open':   float(bar.open),
                'high':   float(bar.high),
                'low':    float(bar.low),
                'close':  float(bar.close),
                'volume': int(bar.volume),
                'vwap':   float(bar.vwap or 0),
            }
            try:
                self._bar_queue.put_nowait(bar_dict)
            except queue.Full:
                logger.warning(f"Bar queue full — dropping bar for {bar.symbol}")

        self._stream.subscribe_bars(_bar_handler, *self._symbols)
        logger.info(f"AlpacaBarStream subscribed to {len(self._symbols):,} symbols")
        self._stream.run()

    def stop(self):
        if self._stream:
            try:
                self._stream.stop()
            except Exception as e:
                logger.warning(f"AlpacaBarStream stop error: {e}")
