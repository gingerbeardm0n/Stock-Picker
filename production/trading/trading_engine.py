"""
Trading Engine
==============
Core position management classes used by both the simulation harness and
(eventually) the live trading system.

    Trade           — represents a single open or completed position
    PositionManager — manages capital, sizing, fills, and daily loss tracking

These were previously embedded in simulator/simulation_engine.py.
Moving them here makes them reusable from live_scanner.py without importing
the simulation harness.

Usage:
    from trading.trading_engine import Trade, PositionManager
"""


class Trade:
    """Represents a single completed (or open) trade."""

    def __init__(self, symbol, entry_time, entry_price, shares, stop_loss,
                 target1, target2, pattern_type='UNKNOWN', daily_high=None):
        self.symbol = symbol
        self.entry_time = entry_time
        self.entry_price = entry_price
        self.shares = shares
        self.stop_loss = stop_loss
        self.target1 = target1
        self.target2 = target2
        self.pattern_type = pattern_type
        self.daily_high = daily_high or entry_price

        self.exit_time = None
        self.exit_price = None
        self.exit_reason = None
        self.shares_remaining = shares
        self.fills = []  # List of {qty, price, reason, time}

        # Tracking for exit_engine features
        self.original_stop_loss = stop_loss            # Immutable — stop_loss moves after T1
        self.highest_price_since_entry = entry_price   # Updated each bar; used by trailing stop
        self.resistance_touches = 0                    # Count of prior-day-high touch events

    def scale_out(self, qty, price, reason, time):
        """Record a partial exit."""
        self.fills.append({'qty': qty, 'price': price, 'reason': reason, 'time': time})
        self.shares_remaining -= qty

    def close_position(self, price, reason, time):
        """Close remaining shares."""
        if self.shares_remaining > 0:
            self.fills.append({
                'qty': self.shares_remaining, 'price': price,
                'reason': reason, 'time': time
            })
        self.exit_time = time
        self.exit_price = price
        self.exit_reason = reason
        self.shares_remaining = 0

    def get_pnl(self):
        """Total realized P&L across all fills."""
        return sum(f['qty'] * (f['price'] - self.entry_price) for f in self.fills)

    def get_exit_time_minutes(self):
        if not self.exit_time:
            return 0
        return int((self.exit_time - self.entry_time).total_seconds() / 60)

    def is_winner(self):
        return self.get_pnl() > 0


class PositionManager:
    """Manages capital, open position, and daily risk rules."""

    def __init__(self, account_size, risk_per_trade_pct=2.0,
                 daily_max_loss_pct=3.0, max_position_pct=1.5):
        self.account_size = account_size
        self.current_balance = account_size
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_position_pct = max_position_pct
        self.daily_max_loss = account_size * (daily_max_loss_pct / 100.0)

        self.position = None
        self.trades_completed = []
        self.daily_loss = 0.0

    def can_enter_trade(self):
        return self.position is None and self.daily_loss < self.daily_max_loss

    def enter_position(self, symbol, entry_price, entry_time,
                       stop_loss_price, target1, target2,
                       pattern_type='UNKNOWN', daily_high=None):
        """Enter a new position using pattern-specific stop/targets from EntrySignal."""
        if not self.can_enter_trade():
            return None

        stop_distance = entry_price - stop_loss_price
        if stop_distance <= 0:
            return None

        risk_per_trade = self.current_balance * (self.risk_per_trade_pct / 100.0)
        risk_based_shares = int(risk_per_trade / stop_distance)

        max_position_value = self.current_balance * (self.max_position_pct / 100.0)
        max_position_shares = int(max_position_value / entry_price)

        shares = min(risk_based_shares, max_position_shares)
        if shares <= 0:
            return None

        if shares * entry_price > self.current_balance:
            shares = int(self.current_balance / entry_price)
            if shares <= 0:
                return None

        self.position = Trade(
            symbol=symbol,
            entry_time=entry_time,
            entry_price=entry_price,
            shares=shares,
            stop_loss=stop_loss_price,
            target1=target1,
            target2=target2,
            pattern_type=pattern_type,
            daily_high=daily_high or entry_price,
        )
        return self.position

    def apply_exit_signal(self, exit_signal, current_time):
        """Apply an ExitSignal from exit_engine.evaluate_exit(). Returns realized P&L."""
        if not self.position:
            return 0.0

        pos = self.position
        qty = min(exit_signal.qty, pos.shares_remaining)
        if qty <= 0:
            # Allow stop tightening without a fill
            if exit_signal.new_stop_price is not None:
                if exit_signal.new_stop_price > pos.stop_loss:
                    pos.stop_loss = exit_signal.new_stop_price
            return 0.0

        price = exit_signal.price
        pnl = qty * (price - pos.entry_price)

        is_full_close = (exit_signal.reason == 'STOP_HIT' or qty >= pos.shares_remaining)

        if is_full_close:
            pos.close_position(price, exit_signal.reason, current_time)
            self.trades_completed.append(pos)
            self.current_balance += pos.get_pnl()
            if pnl < 0:
                self.daily_loss += abs(pnl)
            self.position = None
        else:
            pos.scale_out(qty, price, exit_signal.reason, current_time)
            self.current_balance += pnl
            if pnl < 0:
                self.daily_loss += abs(pnl)

            if exit_signal.move_stop_to_breakeven:
                pos.stop_loss = pos.entry_price
            if exit_signal.new_stop_price is not None:
                if exit_signal.new_stop_price > pos.stop_loss:
                    pos.stop_loss = exit_signal.new_stop_price

            if pos.shares_remaining == 0:
                pos.close_position(price, 'FULLY_SCALED', current_time)
                self.trades_completed.append(pos)
                self.position = None

        return pnl

    def get_stats(self):
        trades = self.trades_completed
        if not trades:
            return {
                'total_trades': 0, 'winners': 0, 'losers': 0,
                'win_rate': 0, 'avg_winner': 0, 'avg_loser': 0,
                'profit_factor': 0, 'total_pnl': 0,
                'best_trade': 0, 'worst_trade': 0,
            }
        winners = [t for t in trades if t.is_winner()]
        losers = [t for t in trades if not t.is_winner()]
        total_wins = sum(t.get_pnl() for t in winners)
        total_losses = sum(t.get_pnl() for t in losers)
        return {
            'total_trades': len(trades),
            'winners': len(winners),
            'losers': len(losers),
            'win_rate': len(winners) / len(trades) * 100,
            'avg_winner': total_wins / len(winners) if winners else 0,
            'avg_loser': total_losses / len(losers) if losers else 0,
            'profit_factor': abs(total_wins / total_losses) if total_losses != 0 else 0,
            'total_pnl': total_wins + total_losses,
            'best_trade': max((t.get_pnl() for t in trades), default=0),
            'worst_trade': min((t.get_pnl() for t in trades), default=0),
        }
