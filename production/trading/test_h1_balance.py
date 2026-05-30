"""
H1 regression — partial scale-outs must NOT be double-counted in current_balance.

No DB. Builds a PositionManager + Trade directly, applies a TARGET_1 partial then a
full close on the remainder, and asserts `current_balance - account == trade.get_pnl()`
realized EXACTLY ONCE. The pre-fix bug added the partial fill's pnl incrementally
(`current_balance += pnl`) AND again via `get_pnl()` at the full close → balance
overstated by the partial amount (inflating avg_daily_pnl reporting).

Run: python production/trading/test_h1_balance.py
"""

from __future__ import annotations
import sys, os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.trading_engine import Trade, PositionManager
from trading.models import ExitSignal


def test_partial_then_stop_not_double_counted():
    """T1 partial (profit) then STOP_HIT remainder (loss) → net -$20, counted once."""
    acct = 5000.0
    pm = PositionManager(account_size=acct)
    t0 = datetime(2025, 1, 2, 9, 40)
    pm.position = Trade('TEST', t0, 10.00, 100, 9.50, 10.50, 11.00)

    # T1 partial: sell 30 @ $10.50, move stop to breakeven
    pm.apply_exit_signal(
        ExitSignal(reason='TARGET_1', price=10.50, qty=30, move_stop_to_breakeven=True),
        t0 + timedelta(minutes=5),
    )
    assert pm.position is not None and pm.position.shares_remaining == 70
    # H1: the partial must NOT be realized into the balance yet.
    assert pm.current_balance == acct, f"partial leaked into balance: {pm.current_balance}"

    # STOP_HIT remainder: 70 @ $9.50 (loss vs $10 entry)
    pm.apply_exit_signal(
        ExitSignal(reason='STOP_HIT', price=9.50, qty=70),
        t0 + timedelta(minutes=10),
    )
    assert pm.position is None
    trade = pm.trades_completed[0]

    expected = 30 * (10.50 - 10.00) + 70 * (9.50 - 10.00)  # +15 - 35 = -20
    assert abs(trade.get_pnl() - expected) < 1e-9, (trade.get_pnl(), expected)
    # The invariant H1 restores: balance delta == trade pnl, exactly once.
    assert abs((pm.current_balance - acct) - trade.get_pnl()) < 1e-9, \
        f"balance delta {pm.current_balance - acct} != pnl {trade.get_pnl()} (double-count!)"
    # Explicit guard vs the OLD bug, which gave acct + 15 (partial) + (-20) (get_pnl) = 4995:
    assert abs(pm.current_balance - 4980.0) < 1e-9, pm.current_balance
    assert abs(pm.daily_loss - 20.0) < 1e-9, pm.daily_loss


def test_partial_then_full_close_net_win():
    """T1 partial then a full close higher (net +$108) → counted once, no daily_loss."""
    acct = 5000.0
    pm = PositionManager(account_size=acct)
    t0 = datetime(2025, 1, 2, 9, 40)
    pm.position = Trade('TEST', t0, 4.00, 200, 3.80, 4.40, 4.80)

    pm.apply_exit_signal(
        ExitSignal(reason='TARGET_1', price=4.40, qty=60, move_stop_to_breakeven=True),
        t0 + timedelta(minutes=3),
    )
    assert pm.current_balance == acct  # partial not realized yet

    pm.apply_exit_signal(
        ExitSignal(reason='EMA_CROSS', price=4.60, qty=140),  # qty==remaining → full close
        t0 + timedelta(minutes=8),
    )
    assert pm.position is None
    trade = pm.trades_completed[0]
    expected = 60 * (4.40 - 4.00) + 140 * (4.60 - 4.00)  # 24 + 84 = 108
    assert abs(trade.get_pnl() - expected) < 1e-9
    assert abs((pm.current_balance - acct) - trade.get_pnl()) < 1e-9
    assert pm.daily_loss == 0.0


def test_single_full_exit_unchanged():
    """No partial: a single STOP_HIT still realizes once (regression guard)."""
    acct = 5000.0
    pm = PositionManager(account_size=acct)
    t0 = datetime(2025, 1, 2, 9, 40)
    pm.position = Trade('TEST', t0, 8.00, 50, 7.60, 8.80, 9.60)
    pm.apply_exit_signal(ExitSignal(reason='STOP_HIT', price=7.60, qty=50), t0 + timedelta(minutes=4))
    trade = pm.trades_completed[0]
    expected = 50 * (7.60 - 8.00)  # -20
    assert abs(trade.get_pnl() - expected) < 1e-9
    assert abs((pm.current_balance - acct) - trade.get_pnl()) < 1e-9
    assert abs(pm.daily_loss - 20.0) < 1e-9


if __name__ == '__main__':
    test_partial_then_stop_not_double_counted()
    test_partial_then_full_close_net_win()
    test_single_full_exit_unchanged()
    print("OK: H1 — partial scale-outs realized exactly once (no double-count); 3/3 pass")
