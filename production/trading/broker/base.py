"""
Broker Abstraction Layer — Base Interfaces
==========================================
Abstract interfaces and shared data classes for broker and data feed integration.

To add a new broker:
    1. Create production/trading/broker/<name>.py
    2. Implement BrokerInterface  (order execution)
    3. Implement DataFeedInterface (market data)
    4. Add credentials to .env.paper / .env.live
    5. Register in config.py get_broker() / get_data_feed()

Current implementations:
    tradier.py — TradierBroker, TradierDataFeed, TradierBarPoller  (active)
    alpaca.py  — AlpacaBroker,  AlpacaDataFeed,  AlpacaBarStream   (requires alpaca-py)

Switching brokers requires only a one-line change in .env.paper / .env.live:
    BROKER=tradier   ← default
    BROKER=alpaca
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ── Shared data classes ────────────────────────────────────────────────────────

@dataclass
class OrderResult:
    """
    Normalized order status returned by BrokerInterface methods.

    status values (broker-agnostic):
        'pending'          — submitted, not yet acknowledged by exchange
        'open'             — live on exchange, awaiting fill
        'partially_filled' — some shares filled, remainder still open
        'filled'           — fully filled
        'cancelled'        — cancelled by user or system
        'rejected'         — rejected by broker (bad params, insufficient funds)
        'expired'          — expired at end of day (DAY orders)
    """
    order_id: str
    status: str
    filled_qty: int = 0
    filled_price: float = 0.0


@dataclass
class QuoteResult:
    """Current market quote for a symbol."""
    symbol: str
    bid: float
    ask: float
    last: float
    prev_close: float = 0.0
    volume: float = 0.0  # today's cumulative session volume (premarket + RTH)


@dataclass
class PositionResult:
    """Current open position for a symbol."""
    symbol: str
    qty: int
    avg_price: float


@dataclass
class BarResult:
    """
    Single OHLCV 1-minute bar.

    time is UTC. Use bar.time.astimezone(ET) for Eastern display.
    """
    time: datetime     # UTC
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float = 0.0

    def to_bar_dict(self) -> dict:
        """
        Convert to the standard bar dict used throughout the codebase
        (simulation_engine, entry_engine, exit_engine, live_scanner).
        """
        return {
            'time':   self.time,
            'open':   self.open,
            'high':   self.high,
            'low':    self.low,
            'close':  self.close,
            'volume': self.volume,
            'vwap':   self.vwap,
        }


# ── Abstract interfaces ────────────────────────────────────────────────────────

class BrokerInterface(ABC):
    """
    Abstract interface for order execution.

    Implement once per broker. LiveTradeManager calls these methods without
    knowing which broker is wired in.

    Thread safety: implementations should be safe from a single calling thread.
    LiveTradeManager owns position lifecycle and calls sequentially.
    """

    @abstractmethod
    def place_limit_buy(
        self,
        symbol: str,
        qty: int,
        limit_price: float,
    ) -> OrderResult:
        """
        Place a DAY limit buy order.
        limit_price: max price willing to pay (use ask + buffer for marketable limit).
        Returns OrderResult with order_id and initial status.
        """
        ...

    @abstractmethod
    def place_stop_sell(
        self,
        symbol: str,
        qty: int,
        stop_price: float,
    ) -> OrderResult:
        """
        Place a DAY stop-market sell order.
        Triggers at stop_price, executes as market. Runs server-side on the broker.
        """
        ...

    @abstractmethod
    def place_market_buy(
        self,
        symbol: str,
        qty: int,
    ) -> OrderResult:
        """
        Place a DAY market buy order. Used as fallback when limit entry misses fill.
        """
        ...

    @abstractmethod
    def place_limit_sell(
        self,
        symbol: str,
        qty: int,
        limit_price: float,
    ) -> OrderResult:
        """
        Place a DAY limit sell order.
        limit_price: min price willing to accept. Used for trailing-stop exits to
        match sim fill price and avoid market-order slippage on tiny pullbacks.
        """
        ...

    @abstractmethod
    def place_market_sell(
        self,
        symbol: str,
        qty: int,
    ) -> OrderResult:
        """
        Place a DAY market sell order. Used for soft exits (time decay, EMA cross).
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order. Returns True on success, False if already filled/cancelled.
        """
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> OrderResult:
        """
        Fetch current order status. Used by poll loops waiting for fills.
        """
        ...

    @abstractmethod
    def get_account_balance(self) -> float:
        """Return current cash / buying power."""
        ...

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[PositionResult]:
        """Return current open position for symbol, or None if not held."""
        ...

    @abstractmethod
    def get_all_positions(self) -> list[PositionResult]:
        """All currently open positions on the account."""
        ...

    # ── Shared helpers (concrete — built on the abstract methods above) ──────────

    def start_trade_stream(self):
        """Start real-time trade-update stream (no-op for brokers without one)."""
        pass

    def wait_for_fill(
        self,
        order_id: str,
        timeout: float = 30.0,
    ) -> OrderResult:
        """Wait for an order to fill via streaming, with REST poll fallback."""
        import time as _t
        deadline = _t.time() + timeout
        while _t.time() < deadline:
            _t.sleep(2)
            order = self.get_order(order_id)
            if order.status in ('filled', 'partially_filled', 'cancelled', 'rejected', 'expired'):
                return order
        return self.get_order(order_id)

    def cancel_order_and_wait(
        self,
        order_id: str,
        timeout: float = 5.0,
        poll_interval: float = 0.5,
    ) -> OrderResult:
        """Cancel an order and block until it reaches a terminal state.

        Returns the final OrderResult. A broker only releases the shares a resting
        order holds (held_for_orders) once the cancel actually settles. Alpaca's
        cancel is asynchronous (new → pending_cancel → canceled), so placing a sell
        immediately after cancel_order() returns races 'insufficient qty available'
        (the bug that crashed the 2026-06-25 scalp session and orphaned every other
        open position). Polling until the order is terminal guarantees the shares
        are free before re-selling.

        If the order filled during the cancel race, the returned status is 'filled'
        with filled_qty/filled_price set — callers must adopt that fill instead of
        placing a second sell (which would open a short).
        """
        import time as _t
        terminal = ('cancelled', 'filled', 'rejected', 'expired')
        self.cancel_order(order_id)
        deadline = _t.time() + timeout
        order = self.get_order(order_id)
        while order.status not in terminal and _t.time() < deadline:
            _t.sleep(poll_interval)
            order = self.get_order(order_id)
        return order


class DataFeedInterface(ABC):
    """
    Abstract interface for market data.

    Implement once per data provider. LiveScanner calls these methods during
    premarket scanning and bar-history seeding.

    Note: real-time bar streaming is handled by a separate BarPoller/BarStream
    class per broker (TradierBarPoller, AlpacaBarStream). This interface covers
    bulk and snapshot data needs (premarket scans, prior closes, bar history).
    """

    @abstractmethod
    def get_quotes(self, symbols: list[str]) -> dict[str, QuoteResult]:
        """
        Fetch current quote for each symbol in batch.
        Used for premarket scanning: identify price + gain% movers across ~4000 symbols.
        Implementations must handle large symbol lists via internal batching.
        """
        ...

    @abstractmethod
    def get_bars_since_4am(
        self,
        symbols: list[str],
        until_utc: datetime | None = None,
    ) -> dict[str, list[BarResult]]:
        """
        Fetch 1-minute OHLCV bars from 4:00 AM ET today for each symbol.
        until_utc: optional cutoff (default = now).
        Call for ~10-50 candidates AFTER quote-based prefilter, NOT for all 4000 symbols.
        Returns empty list for symbols with no data.
        """
        ...

    @abstractmethod
    def get_prior_closes(self, symbols: list[str]) -> dict[str, float]:
        """
        Fetch prior trading day's closing price for each symbol.
        Used by LiveScanner for gain% calculation (premarket and intraday).
        May not return all symbols (missing = no data available from this provider).
        """
        ...
