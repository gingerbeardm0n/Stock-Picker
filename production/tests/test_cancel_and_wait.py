"""
Tests for BrokerInterface.cancel_order_and_wait — the async-cancel race fix.

Root cause (2026-06-25): Alpaca's cancel_order returns immediately (HTTP 202) but
settles asynchronously (new -> pending_cancel -> canceled). Shares stay
held_for_orders until the cancel is terminal, so a market sell placed right after
cancel_order() returns hits 'insufficient qty available: 0'. That exception
crashed the scalp session and orphaned every other open position.

cancel_order_and_wait() must poll until the order is terminal before returning,
so callers only sell once the shares are actually released.
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.broker.base import BrokerInterface, OrderResult


class _FakeBroker(BrokerInterface):
    """Minimal broker that scripts a sequence of get_order statuses."""

    def __init__(self, statuses, filled_price=0.0, filled_qty=0):
        # statuses: list of status strings returned by successive get_order calls
        self._statuses = list(statuses)
        self._filled_price = filled_price
        self._filled_qty = filled_qty
        self.cancel_called = False
        self.get_order_calls = 0

    def cancel_order(self, order_id):
        self.cancel_called = True
        return True

    def get_order(self, order_id):
        self.get_order_calls += 1
        # Hold on the last status once the script is exhausted
        status = self._statuses[min(self.get_order_calls - 1, len(self._statuses) - 1)]
        return OrderResult(
            order_id=order_id, status=status,
            filled_qty=self._filled_qty if status == 'filled' else 0,
            filled_price=self._filled_price if status == 'filled' else 0.0,
        )

    # Unused abstract methods
    def place_limit_buy(self, *a, **k): ...
    def place_stop_sell(self, *a, **k): ...
    def place_market_buy(self, *a, **k): ...
    def place_limit_sell(self, *a, **k): ...
    def place_market_sell(self, *a, **k): ...
    def get_account_balance(self): return 0.0
    def get_position(self, symbol): return None


def test_waits_through_pending_cancel():
    """The exact race: order is 'pending_cancel' for several polls, then 'cancelled'.
    Must keep polling until terminal, not return on the first non-terminal read."""
    broker = _FakeBroker(['pending_cancel', 'pending_cancel', 'cancelled'])
    result = broker.cancel_order_and_wait('oid', timeout=5.0, poll_interval=0.01)
    assert broker.cancel_called
    assert result.status == 'cancelled'
    assert broker.get_order_calls >= 3   # polled through both pending reads


def test_adopts_fill_when_stop_fills_during_cancel():
    """Price fell through the stop while cancelling — must report 'filled' with the
    fill price so the caller adopts it instead of double-selling (opening a short)."""
    broker = _FakeBroker(['pending_cancel', 'filled'], filled_price=2.67, filled_qty=286)
    result = broker.cancel_order_and_wait('oid', timeout=5.0, poll_interval=0.01)
    assert result.status == 'filled'
    assert result.filled_price == 2.67
    assert result.filled_qty == 286


def test_returns_immediately_when_already_cancelled():
    """Already terminal on first read — no needless waiting."""
    broker = _FakeBroker(['cancelled'])
    result = broker.cancel_order_and_wait('oid', timeout=5.0, poll_interval=0.01)
    assert result.status == 'cancelled'
    assert broker.get_order_calls == 1


def test_gives_up_after_timeout():
    """Cancel never settles — must return the last (non-terminal) state after the
    timeout rather than hanging forever."""
    broker = _FakeBroker(['pending_cancel'])   # never becomes terminal
    result = broker.cancel_order_and_wait('oid', timeout=0.05, poll_interval=0.01)
    assert result.status == 'pending_cancel'   # returned, did not hang


if __name__ == '__main__':
    test_waits_through_pending_cancel()
    test_adopts_fill_when_stop_fills_during_cancel()
    test_returns_immediately_when_already_cancelled()
    test_gives_up_after_timeout()
    print("All cancel_order_and_wait tests passed.")
