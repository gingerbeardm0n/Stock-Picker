"""
Order Placement Module — bridges strategy signals to BrokerInterface.

Two classes:
  OrderExecutor    — stateless, places individual orders via BrokerInterface
  LiveTradeManager — stateful, manages one full trade lifecycle
                     (entry → stop setup → scale-outs → full exit)

Usage:
    from trading.broker import TradierBroker
    from trading.order_manager import OrderExecutor, LiveTradeManager

    broker   = TradierBroker(token, account_id, sandbox=True)
    executor = OrderExecutor(broker)
    manager  = LiveTradeManager(executor, account_balance=100_000)

    # On entry signal from entry_engine:
    entered = manager.execute_entry(entry_signal, ask_price=8.42)

    # On exit signal from exit_engine:
    pnl = manager.execute_exit(exit_signal, current_time=datetime.now(timezone.utc))

Switching brokers:
    Change the BrokerInterface implementation passed to OrderExecutor —
    no changes needed in this module or anywhere else in the trading stack.
"""

import sys
import os
import time
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.broker.base import BrokerInterface, OrderResult
from trading.trading_engine import Trade
from trading.models import EntrySignal, ExitSignal

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# OrderExecutor — stateless, one job: submit/query orders via BrokerInterface
# ─────────────────────────────────────────────────────────────────────────────

class OrderExecutor:
    """
    Thin domain layer over BrokerInterface.

    Adds Ross Cameron-specific logic on top of the raw broker calls:
    - Marketable limit buffer ($0.10 above ask) on entry
    - Consistent logging across all brokers
    - Simple delegation for everything else

    Stateless — no position tracking here.
    """

    ENTRY_LIMIT_BUFFER = 0.10    # Marketable limit: ask + $0.10 (Ross Cameron standard)

    def __init__(self, broker: BrokerInterface):
        self._broker = broker

    def place_entry(self, symbol: str, shares: int, ask_price: float,
                    buffer: float | None = None) -> OrderResult:
        """
        Marketable limit buy: ask + buffer (default $0.10).
        Fills at best available price up to the limit — protects against
        sudden spike fills on fast-moving momentum stocks.
        """
        buf = buffer if buffer is not None else self.ENTRY_LIMIT_BUFFER
        limit_price = round(ask_price + buf, 2)
        logger.info(f"ENTRY ORDER: BUY {shares} {symbol} @ limit ${limit_price:.2f} "
                    f"(ask ${ask_price:.2f} + ${buf:.2f} buffer)")
        return self._broker.place_limit_buy(symbol, shares, limit_price)

    def place_stop(self, symbol: str, shares: int, stop_price: float) -> OrderResult:
        """
        Stop-market sell — executes on the broker's servers automatically
        when price hits stop_price, even if our process is down.
        """
        stop_price = round(stop_price, 2)
        logger.info(f"STOP ORDER: SELL {shares} {symbol} stop @ ${stop_price:.2f}")
        return self._broker.place_stop_sell(symbol, shares, stop_price)

    def place_exit_market(self, symbol: str, shares: int, reason: str) -> OrderResult:
        """
        Market sell — used for time decay, EMA cross, selling pressure exits
        where speed matters more than price precision.
        """
        logger.info(f"EXIT ORDER ({reason}): SELL {shares} {symbol} @ market")
        return self._broker.place_market_sell(symbol, shares)

    def cancel_order(self, order_id: str) -> bool:
        return self._broker.cancel_order(order_id)

    def get_order(self, order_id: str) -> OrderResult:
        return self._broker.get_order(order_id)

    def get_position(self, symbol: str):
        return self._broker.get_position(symbol)


# ─────────────────────────────────────────────────────────────────────────────
# LiveTradeManager — stateful trade lifecycle manager
# ─────────────────────────────────────────────────────────────────────────────

class LiveTradeManager:
    """
    Manages one active trade from entry signal to full close.

    State machine:
        IDLE → execute_entry() → ENTERED (Trade object created, stop order live)
             → execute_exit()  → IDLE (position closed, stop cancelled)

    Only one position at a time — matches our strategy's single-stock focus.
    """

    def __init__(self, executor: OrderExecutor, account_balance: float,
                 risk_pct: float = 2.0, max_position_pct: float = 20.0,
                 fill_timeout_seconds: int = 30):
        self.executor         = executor
        self.account_balance  = account_balance
        self.risk_pct         = risk_pct
        self.max_position_pct = max_position_pct
        self.fill_timeout     = fill_timeout_seconds

        # Live state
        self.active_trade: Trade | None = None
        self.entry_order_id: str | None = None
        self.stop_order_id: str | None = None
        self.pending_exit_order_ids: list[str] = []

        # Completed trades log
        self.completed_trades: list[Trade] = []
        self.realized_pnl: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def has_open_position(self) -> bool:
        return self.active_trade is not None

    def execute_entry(self, entry_signal: EntrySignal, ask_price: float) -> bool:
        """
        Place entry order and set up stop loss after fill.
        Returns True if position entered, False if order timed out or rejected.
        """
        if self.has_open_position():
            logger.warning("execute_entry called but position already open — skipping")
            return False

        pattern = entry_signal.pattern
        shares  = self._calculate_shares(ask_price, pattern.stop_price)
        if shares <= 0:
            logger.warning(f"Skipping entry for {entry_signal.symbol}: "
                           f"shares=0 (balance=${self.account_balance:.0f}, "
                           f"stop_dist=${ask_price - pattern.stop_price:.3f})")
            return False

        # Place marketable limit entry order
        result            = self.executor.place_entry(entry_signal.symbol, shares, ask_price)
        self.entry_order_id = result.order_id

        # Wait for fill
        filled = self._wait_for_fill(self.entry_order_id)
        if filled is None:
            logger.warning(f"Entry order {self.entry_order_id} for {entry_signal.symbol} "
                           f"timed out or was cancelled — no position entered")
            self.executor.cancel_order(self.entry_order_id)
            self.entry_order_id = None
            return False

        fill_price = filled.filled_price
        fill_qty   = filled.filled_qty
        fill_time  = datetime.now(timezone.utc)

        logger.info(f"FILLED: {fill_qty} {entry_signal.symbol} @ ${fill_price:.2f} "
                    f"({pattern.pattern_type})")

        # Build Trade object (same class used by the simulator — consistent P&L tracking)
        self.active_trade = Trade(
            symbol=entry_signal.symbol,
            entry_time=fill_time,
            entry_price=fill_price,
            shares=fill_qty,
            stop_loss=pattern.stop_price,
            target1=pattern.target1,
            target2=pattern.target2,
            pattern_type=pattern.pattern_type,
        )

        # Place stop loss immediately — runs on the broker's servers even if we crash
        stop_result       = self.executor.place_stop(
            entry_signal.symbol, fill_qty, pattern.stop_price
        )
        self.stop_order_id = stop_result.order_id
        logger.info(f"Stop order placed: {self.stop_order_id} @ ${pattern.stop_price:.2f}")

        return True

    def execute_exit(self, exit_signal: ExitSignal, current_time: datetime) -> float:
        """
        Execute an exit signal from exit_engine.evaluate_exit().

        Handles partial scale-outs (T1, T2, EMA cross) and full closes
        (stop hit, time decay). Cancels stop order when position fully closed.

        Returns realized P&L for this exit (not cumulative).
        """
        if not self.active_trade:
            logger.warning("execute_exit called but no active trade")
            return 0.0

        trade = self.active_trade
        qty   = min(exit_signal.qty, trade.shares_remaining)

        if qty <= 0:
            # Stop tighten only — update Trade and re-place stop order
            if exit_signal.new_stop_price and exit_signal.new_stop_price > trade.stop_loss:
                self._replace_stop(trade.symbol, trade.shares_remaining,
                                   exit_signal.new_stop_price)
                trade.stop_loss = exit_signal.new_stop_price
            return 0.0

        # Cancel the existing stop order BEFORE placing any sell order.
        # Some brokers (e.g. Alpaca) mark all shares as "held" while a stop is active,
        # causing sell orders to be rejected. Cancel first, then sell.
        if self.stop_order_id:
            self.executor.cancel_order(self.stop_order_id)
            self.stop_order_id = None
            time.sleep(0.3)    # give broker time to release the held qty

        # Place exit market sell
        result        = self.executor.place_exit_market(trade.symbol, qty, exit_signal.reason)
        exit_order_id = result.order_id
        self.pending_exit_order_ids.append(exit_order_id)

        # Wait for fill
        filled = self._wait_for_fill(exit_order_id)
        if filled is None:
            logger.error(f"Exit order {exit_order_id} timed out! "
                         f"Manual intervention may be required.")
            return 0.0

        fill_price = filled.filled_price
        fill_qty   = filled.filled_qty
        pnl        = fill_qty * (fill_price - trade.entry_price)

        self.pending_exit_order_ids.remove(exit_order_id)

        is_full_close = (
            exit_signal.reason in ('STOP_HIT', 'TRAILING_STOP', 'TIME_DECAY',
                                   'EARLY_TIME_DECAY', 'TARGET_1_COLD')
            or fill_qty >= trade.shares_remaining
        )

        if is_full_close:
            trade.close_position(fill_price, exit_signal.reason, current_time)
            self._on_position_closed(pnl)
        else:
            trade.scale_out(fill_qty, fill_price, exit_signal.reason, current_time)
            self.account_balance += pnl
            self.realized_pnl    += pnl

            # Move stop to breakeven after T1
            if exit_signal.move_stop_to_breakeven:
                new_stop = trade.entry_price
                self._replace_stop(trade.symbol, trade.shares_remaining, new_stop)
                trade.stop_loss = new_stop
                logger.info(f"Stop moved to breakeven: ${new_stop:.2f}")
            elif exit_signal.new_stop_price and exit_signal.new_stop_price > trade.stop_loss:
                self._replace_stop(trade.symbol, trade.shares_remaining,
                                   exit_signal.new_stop_price)
                trade.stop_loss = exit_signal.new_stop_price

            # If fully scaled out after this fill
            if trade.shares_remaining == 0:
                trade.close_position(fill_price, 'FULLY_SCALED', current_time)
                self._on_position_closed(pnl)

        logger.info(f"EXIT {exit_signal.reason}: {fill_qty} {trade.symbol} "
                    f"@ ${fill_price:.2f} | trade P&L: ${pnl:+.2f}")
        return pnl

    def get_unrealized_pnl(self, current_price: float) -> float:
        """Unrealized P&L on open position for monitoring / display."""
        if not self.active_trade:
            return 0.0
        trade = self.active_trade
        return trade.shares_remaining * (current_price - trade.entry_price)

    def emergency_flatten(self) -> float:
        """
        Immediately market-sell all shares and cancel all open orders.
        Use in error scenarios, process shutdown, or manual intervention.
        """
        if not self.active_trade:
            return 0.0

        trade = self.active_trade
        logger.warning(f"EMERGENCY FLATTEN: closing {trade.shares_remaining} "
                       f"{trade.symbol} at market")

        # Cancel stop + any pending exits first
        for oid in ([self.stop_order_id] + self.pending_exit_order_ids):
            if oid:
                self.executor.cancel_order(oid)

        time.sleep(0.5)    # give broker time to release held qty

        if trade.shares_remaining > 0:
            result = self.executor.place_exit_market(
                trade.symbol, trade.shares_remaining, 'EMERGENCY_FLATTEN'
            )
            filled     = self._wait_for_fill(result.order_id, timeout_seconds=60)
            fill_price = filled.filled_price if filled else trade.entry_price
            pnl        = trade.shares_remaining * (fill_price - trade.entry_price)
            trade.close_position(fill_price, 'EMERGENCY_FLATTEN', datetime.now(timezone.utc))
            self._on_position_closed(pnl)
            return pnl

        return 0.0

    # ── Private helpers ───────────────────────────────────────────────────────

    def _calculate_shares(self, entry_price: float, stop_price: float) -> int:
        """
        Exact same sizing formula as PositionManager in trading_engine.py.
        Risk 2% of account, cap at max_position_pct% of account value.
        """
        stop_distance = entry_price - stop_price
        if stop_distance <= 0:
            return 0

        risk_amount        = self.account_balance * (self.risk_pct / 100.0)
        risk_based_shares  = int(risk_amount / stop_distance)

        max_position_value = self.account_balance * (self.max_position_pct / 100.0)
        max_shares         = int(max_position_value / entry_price)

        shares = min(risk_based_shares, max_shares)

        # Final affordability check
        if shares * entry_price > self.account_balance:
            shares = int(self.account_balance / entry_price)

        return max(0, shares)

    def _wait_for_fill(
        self,
        order_id: str,
        timeout_seconds: int | None = None,
    ) -> OrderResult | None:
        """
        Poll broker until order is 'filled' or a terminal status.
        Returns filled OrderResult or None on timeout/cancellation.
        """
        timeout  = timeout_seconds or self.fill_timeout
        deadline = time.time() + timeout

        while time.time() < deadline:
            result = self.executor.get_order(order_id)
            if result.status == 'filled':
                return result
            if result.status in ('cancelled', 'rejected', 'expired'):
                logger.warning(f"Order {order_id} ended with status: {result.status}")
                return None
            time.sleep(0.5)

        logger.warning(f"Order {order_id} timed out after {timeout}s")
        return None

    def _replace_stop(self, symbol: str, shares: int, new_stop_price: float):
        """Cancel existing stop order and place a new one at updated price."""
        if self.stop_order_id:
            self.executor.cancel_order(self.stop_order_id)
            self.stop_order_id = None
            time.sleep(0.3)    # give broker time to release held qty

        result             = self.executor.place_stop(symbol, shares, new_stop_price)
        self.stop_order_id = result.order_id
        logger.info(f"Stop replaced: {self.stop_order_id} @ ${new_stop_price:.2f}")

    def _on_position_closed(self, pnl: float):
        """Called when position is fully closed. Cleans up all state."""
        self.completed_trades.append(self.active_trade)
        self.account_balance += pnl
        self.realized_pnl    += pnl

        # Cancel stop if still open (e.g. we hit T2 before stop triggered)
        if self.stop_order_id:
            self.executor.cancel_order(self.stop_order_id)
            self.stop_order_id = None

        logger.info(f"Position closed. Session P&L: ${self.realized_pnl:+.2f} | "
                    f"Account: ${self.account_balance:,.2f}")

        self.active_trade   = None
        self.entry_order_id = None
        self.pending_exit_order_ids.clear()
