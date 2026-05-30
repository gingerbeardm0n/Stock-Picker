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

from trading.sizing import compute_shares, FLOAT_BUCKET_CAPS


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
        self.fills = []  # List of {qty, price, reason, time} — exit fills only

        # Tracking for exit_engine features
        self.original_stop_loss = stop_loss            # Immutable — stop_loss moves after T1
        self.highest_price_since_entry = entry_price   # Updated each bar; used by trailing stop
        self.resistance_touches = 0                    # Count of prior-day-high touch events

        # Add-on / pyramid tracking (GAP-03)
        self.initial_shares = shares                   # Immutable — used to size each add tier
        self.add_on_count = 0                          # Number of adds executed this trade
        self.add_on_fills = []                         # List of {qty, price, reason, time} — buy fills
        self.t1_hit = False                            # True after first TARGET_1 partial exit fires
        self.session_high_at_add = entry_price         # High watermark for NEW_HIGH gate

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

    def apply_add_on(self, qty, price, new_stop, reason, time):
        """Record an add-on buy: increase position size and tighten stop."""
        self.add_on_fills.append({'qty': qty, 'price': price, 'reason': reason, 'time': time})
        self.shares += qty
        self.shares_remaining += qty
        self.add_on_count += 1
        if new_stop > self.stop_loss:
            self.stop_loss = new_stop
        # Advance high watermark so next bar must break even higher
        if price > self.session_high_at_add:
            self.session_high_at_add = price

    def get_pnl(self):
        """
        Total realized P&L across all exit fills, corrected for add-on cost basis.

        Without correction, all exit fills would be priced as if bought at entry_price,
        overstating gains on add-on shares that were actually bought at higher prices.
        Correction: subtract the extra cost premium paid for each add-on lot.
        """
        raw = sum(f['qty'] * (f['price'] - self.entry_price) for f in self.fills)
        add_on_premium = sum(
            a['qty'] * (a['price'] - self.entry_price) for a in self.add_on_fills
        )
        return raw - add_on_premium

    def get_exit_time_minutes(self):
        if not self.exit_time:
            return 0
        return int((self.exit_time - self.entry_time).total_seconds() / 60)

    def is_winner(self):
        return self.get_pnl() > 0


class PositionManager:
    """Manages capital, open position, and daily risk rules."""

    # GAP-11: Float-bucket hard caps on position value. Single source of truth now
    # lives in trading.sizing.FLOAT_BUCKET_CAPS (used by sizing.compute_shares, which
    # both the sim and live brokers call). Kept as a class attr for backward compat.
    FLOAT_BUCKET_CAPS = FLOAT_BUCKET_CAPS

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

        # GAP-16: track first-loss-of-day for half-size rule
        self._had_loss_today = False

    def can_enter_trade(self):
        return self.position is None and self.daily_loss < self.daily_max_loss

    def enter_position(self, symbol, entry_price, entry_time,
                       stop_loss_price, target1, target2,
                       pattern_type='UNKNOWN', daily_high=None,
                       float_shares: int | None = None,
                       size_multiplier: float = 1.0):
        """Enter a new position using pattern-specific stop/targets from EntrySignal.

        Args:
            float_shares: company's public float (shares). Used for GAP-11 bucket caps.
                          Pass None to skip float-based capping (float unknown).
            size_multiplier: extra scaling applied after all other sizing rules.
                             Pass 0.5 for GAP-14 half-size re-entry after a stop-out.
        """
        if not self.can_enter_trade():
            return None

        # Sizing is delegated to trading.sizing.compute_shares — the single source of
        # truth shared by the sim broker and the live broker (proven identical to the
        # original inline math by test_sizing.py). GAP-11/14/16 all live in there.
        shares = compute_shares(
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            current_balance=self.current_balance,
            risk_pct=self.risk_per_trade_pct,
            max_position_pct=self.max_position_pct,
            float_shares=float_shares,
            size_multiplier=size_multiplier,
            had_loss_today=self._had_loss_today,
        )
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
            trade_pnl = pos.get_pnl()
            self.current_balance += trade_pnl
            if trade_pnl < 0:
                self.daily_loss += abs(trade_pnl)
                self._had_loss_today = True   # GAP-16: triggers half-size next entry
            self.position = None
        else:
            pos.scale_out(qty, price, exit_signal.reason, current_time)
            # H1 FIX: do NOT realize P&L incrementally on partial scale-outs.
            # current_balance / daily_loss are realized ONCE at trade completion via
            # get_pnl() (the full_close branch above, or the fully-scaled close below).
            # The old `current_balance += pnl` here was ALSO included by get_pnl() when
            # the remainder later closed via full_close → the partial was counted twice
            # (inflated current_balance → inflated avg_daily_pnl reporting). The per-fill
            # `pnl` is still returned below for callers, just not summed into the balance.

            # GAP-03: mark T1 hit so add-on engine knows a partial has been taken
            if exit_signal.reason in ('TARGET_1', 'TARGET_1_COLD'):
                pos.t1_hit = True

            if exit_signal.move_stop_to_breakeven:
                pos.stop_loss = pos.entry_price
            if exit_signal.new_stop_price is not None:
                if exit_signal.new_stop_price > pos.stop_loss:
                    pos.stop_loss = exit_signal.new_stop_price

            if pos.shares_remaining == 0:
                pos.close_position(price, 'FULLY_SCALED', current_time)
                self.trades_completed.append(pos)
                # Realize the full trade P&L exactly once (mirrors the full_close branch).
                # Previously this branch never updated current_balance/daily_loss at all,
                # relying on the now-removed incremental partial adds.
                trade_pnl = pos.get_pnl()
                self.current_balance += trade_pnl
                if trade_pnl < 0:
                    self.daily_loss += abs(trade_pnl)
                    self._had_loss_today = True
                self.position = None

        return pnl

    def apply_add_on(self, add_on_signal, current_time) -> int:
        """
        Apply an AddOnSignal from add_on_engine.evaluate_add_on().

        Returns the number of shares actually added (may be less than requested if
        the add would push position value over max_position_pct cap).
        Returns 0 if add was skipped entirely.
        """
        if not self.position:
            return 0
        pos = self.position
        qty = add_on_signal.qty
        if qty <= 0:
            return 0

        # Cap: don't exceed 3× initial_shares total (concept page: "max_position_size * 3")
        # We use shares (not dollar value) for this cap — the position has already grown
        # in value and using a dollar cap would block all adds after any price increase.
        if pos.shares >= pos.initial_shares * 3:
            return 0
        max_add = pos.initial_shares * 3 - pos.shares
        qty = min(qty, max_add)
        if qty <= 0:
            return 0

        pos.apply_add_on(qty, add_on_signal.price, add_on_signal.new_stop,
                         add_on_signal.reason, current_time)
        return qty

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
