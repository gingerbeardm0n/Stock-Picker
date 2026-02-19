#!/usr/bin/env python3
"""
Simulation Engine: Discrete Event Backtester
==============================================

Feeds historical minute data one minute at a time (no lookahead) and executes
trading logic at CPU speed. Used to validate entry/exit rules and measure
win rate, profit factor, and optimal trading windows.

Key Features:
- Time-forward constraint: Only sees data up to current minute
- Position management: Tracks entries, exits, scaling, stop losses
- Risk rules: Enforces daily max loss, position sizing, profit targets
- Statistics: Win rate, avg winner/loser, profit factor, by-time analysis

Usage:
    engine = SimulationRunner(date='2026-02-13', account_size=5000, risk_pct=2.0)
    engine.run()
    engine.print_report()
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.query_helpers import StockDataDB
from datetime import datetime, timedelta
import pytz
from collections import defaultdict
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

ET = pytz.timezone('US/Eastern')
UTC = pytz.UTC

# Ross Cameron's 5 Pillars - Scanner Criteria
SCANNER_CRITERIA = {
    'min_price': 1.0,               # was 2.0 - allow gappers/penny stocks
    'max_price': 20.0,              # Ross: $2-$20 sweet spot (adjusted)
    'min_morning_volume': 100_000,  # 4am-current volume minimum
    'min_relative_volume': 3.0,     # was 5.0 - will revert to 5 after data maturity
                                    # Ross: 5x minimum (10x+ preferred)
    'min_premarket_gain': 10.0,     # Ross: up 10%+ from prior close
    'max_float': 50_000_000,        # was 20M - relax to allow more small caps
    'max_market_cap': 500_000_000,  # Ross: <$500M (micro-cap)
    'max_spread': 0.15,             # Ross: <15 cents
}


class Trade:
    """Represents a single completed trade"""

    def __init__(self, symbol, entry_time, entry_price, shares, stop_loss,
                 target1, target2, daily_high=None):
        self.symbol = symbol
        self.entry_time = entry_time
        self.entry_price = entry_price
        self.shares = shares
        self.stop_loss = stop_loss
        self.target1 = target1
        self.target2 = target2
        self.daily_high = daily_high or entry_price

        # Exit tracking
        self.exit_time = None
        self.exit_price = None
        self.exit_reason = None
        self.shares_remaining = shares
        self.fills = []  # List of (qty, price, reason, time)

    def scale_out(self, qty, price, reason, time):
        """Record a partial exit"""
        self.fills.append({
            'qty': qty,
            'price': price,
            'reason': reason,
            'time': time
        })
        self.shares_remaining -= qty

    def close_position(self, price, reason, time):
        """Close remaining shares"""
        if self.shares_remaining > 0:
            self.fills.append({
                'qty': self.shares_remaining,
                'price': price,
                'reason': reason,
                'time': time
            })
        self.exit_time = time
        self.exit_price = price
        self.exit_reason = reason
        self.shares_remaining = 0

    def get_pnl(self):
        """Calculate total P&L across all fills"""
        if not self.fills:
            return 0
        return sum(f['qty'] * (f['price'] - self.entry_price) for f in self.fills)

    def get_exit_time_minutes(self):
        """Minutes held before exit"""
        if not self.exit_time:
            return 0
        return int((self.exit_time - self.entry_time).total_seconds() / 60)

    def is_winner(self):
        """True if trade made money"""
        return self.get_pnl() > 0


class PositionManager:
    """Manages open positions, entries, exits, and scaling"""

    def __init__(self, account_size, risk_per_trade_pct=2.0, daily_max_loss_pct=3.0, max_position_pct=1.5):
        self.account_size = account_size
        self.current_balance = account_size
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_position_pct = max_position_pct  # Cap position to 1-2% of account balance
        self.daily_max_loss = account_size * (daily_max_loss_pct / 100.0)

        # Position tracking
        self.position = None  # Current Trade object
        self.trades_completed = []  # List of completed Trade objects
        self.daily_loss = 0.0

    def can_enter_trade(self):
        """Check if we can enter a new trade"""
        return self.position is None and self.daily_loss < self.daily_max_loss

    def enter_position(self, symbol, entry_price, entry_time, stop_loss_price, daily_high):
        """
        Enter a new position

        Args:
            symbol: Stock symbol
            entry_price: Entry price
            entry_time: Entry datetime
            stop_loss_price: Stop loss price
            daily_high: Highest price seen so far today (for comparison)

        Returns:
            Trade object, or None if can't enter
        """
        if not self.can_enter_trade():
            return None

        # Calculate position size based on risk
        risk_per_trade = self.current_balance * (self.risk_per_trade_pct / 100.0)
        stop_distance = entry_price - stop_loss_price

        if stop_distance <= 0:
            return None

        # Position sizing: shares = risk / stop_distance
        risk_based_shares = int(risk_per_trade / stop_distance)
        if risk_based_shares <= 0:
            return None

        # CRITICAL: Cap position to max % of account balance (default 1.5%)
        # This prevents over-leveraging while maintaining risk management
        max_position_value = self.current_balance * (self.max_position_pct / 100.0)
        max_position_shares = int(max_position_value / entry_price)

        # Use the smaller of risk-based shares vs account percentage cap
        shares = min(risk_based_shares, max_position_shares)
        if shares <= 0:
            return None

        # Final check: ensure we have enough capital to buy these shares
        capital_needed = shares * entry_price
        if capital_needed > self.current_balance:
            # This should rarely happen now, but keep as safety net
            shares = int(self.current_balance / entry_price)
            if shares <= 0:
                return None

        # Calculate profit targets (2:1 and 3:1 R/R)
        target1 = entry_price + (stop_distance * 2)
        target2 = entry_price + (stop_distance * 3)

        # Create trade
        self.position = Trade(
            symbol=symbol,
            entry_time=entry_time,
            entry_price=entry_price,
            shares=shares,
            stop_loss=stop_loss_price,
            target1=target1,
            target2=target2,
            daily_high=daily_high
        )

        return self.position

    def update_position_state(self, current_price, current_time, ema_9=None,
                             volume_current=None, volume_avg=None):
        """
        Update position state based on current price and technical signals

        Returns:
            (action, details) where action is 'scale_out_1', 'scale_out_2', 'exit', or None
        """
        if not self.position:
            return None, None

        # Convert Decimal to float
        current_price = float(current_price)

        pos = self.position

        # Check stop loss (hard stop - must exit immediately)
        if current_price <= pos.stop_loss:
            pnl = pos.shares_remaining * (current_price - pos.entry_price)
            self.daily_loss += abs(pnl) if pnl < 0 else 0
            pos.close_position(current_price, 'STOP_HIT', current_time)
            self.trades_completed.append(pos)
            self.current_balance += pos.get_pnl()
            self.position = None
            return 'exit', f'Stop hit at ${current_price:.2f}'

        # Check target 1 (2:1 R/R) - scale out 50%
        if current_price >= pos.target1 and pos.shares_remaining == pos.shares:
            qty_to_sell = pos.shares // 2
            pnl_partial = qty_to_sell * (current_price - pos.entry_price)
            pos.scale_out(qty_to_sell, current_price, 'TARGET_1', current_time)
            self.current_balance += pnl_partial
            # Move stop to breakeven on remainder
            pos.stop_loss = pos.entry_price
            return 'scale_out_1', f'Sold 50% at ${current_price:.2f}, stop to breakeven'

        # Check target 2 (3:1 R/R) - scale out another 25%
        if (current_price >= pos.target2 and pos.shares_remaining > 0 and
            pos.shares_remaining < pos.shares):
            qty_to_sell = max(1, pos.shares // 4)
            pnl_partial = qty_to_sell * (current_price - pos.entry_price)
            pos.scale_out(qty_to_sell, current_price, 'TARGET_2', current_time)
            self.current_balance += pnl_partial
            return 'scale_out_2', f'Sold 25% at ${current_price:.2f}'

        # Update daily high for subsequent checks
        if current_price > pos.daily_high:
            pos.daily_high = current_price

        return None, None

    def exit_position(self, current_price, current_time, reason):
        """Close remaining position at current price"""
        if not self.position:
            return False

        pos = self.position
        pnl = pos.shares_remaining * (current_price - pos.entry_price)
        self.daily_loss += abs(pnl) if pnl < 0 else 0
        pos.close_position(current_price, reason, current_time)
        self.trades_completed.append(pos)
        self.current_balance += pos.get_pnl()
        self.position = None
        return True

    def get_current_pnl(self, current_price=None):
        """Get unrealized P&L on current position"""
        if not self.position or not current_price:
            return 0
        return self.position.shares_remaining * (current_price - self.position.entry_price)

    def get_stats(self):
        """Calculate statistics from completed trades"""
        if not self.trades_completed:
            return {
                'total_trades': 0,
                'winners': 0,
                'losers': 0,
                'win_rate': 0,
                'avg_winner': 0,
                'avg_loser': 0,
                'profit_factor': 0,
                'total_pnl': 0,
                'best_trade': 0,
                'worst_trade': 0
            }

        trades = self.trades_completed
        winners = [t for t in trades if t.is_winner()]
        losers = [t for t in trades if not t.is_winner()]

        total_wins = sum(t.get_pnl() for t in winners) if winners else 0
        total_losses = sum(t.get_pnl() for t in losers) if losers else 0

        return {
            'total_trades': len(trades),
            'winners': len(winners),
            'losers': len(losers),
            'win_rate': len(winners) / len(trades) * 100 if trades else 0,
            'avg_winner': total_wins / len(winners) if winners else 0,
            'avg_loser': total_losses / len(losers) if losers else 0,
            'profit_factor': abs(total_wins / total_losses) if total_losses != 0 else 0,
            'total_pnl': total_wins + total_losses,
            'best_trade': max((t.get_pnl() for t in trades), default=0),
            'worst_trade': min((t.get_pnl() for t in trades), default=0)
        }


class SimulationRunner:
    """Runs minute-by-minute simulation"""

    def __init__(self, date, account_size=5000, risk_pct=2.0, max_position_pct=1.5, verbose=True):
        """
        Initialize simulator

        Args:
            date: datetime.date or string 'YYYY-MM-DD'
            account_size: Starting account balance
            risk_pct: Risk per trade as % of account
            max_position_pct: Maximum position size as % of account (default 1.5%)
            verbose: Print details during simulation
        """
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%d').date()

        self.date = date
        self.account_size = account_size
        self.risk_pct = risk_pct
        self.max_position_pct = max_position_pct
        self.verbose = verbose

        self.position_manager = PositionManager(account_size, risk_pct, max_position_pct=max_position_pct)
        self.minute_bars = []  # Loaded from DB
        self.scanner_results = {}  # Cached scanner results by minute
        self.trade_log = []  # Detailed log of all decisions

        # Historical data for filtering
        self.daily_bars_by_symbol = {}  # For avg volume baseline
        self.fundamentals = {}  # Float, market cap from DB
        self.prior_close = {}  # Previous day close by symbol

    def load_minute_bars(self):
        """Load all minute bars for the trading day"""
        with StockDataDB() as db:
            # First get all symbols with data for this date
            cursor = db.conn.cursor()
            cursor.execute("""
                SELECT DISTINCT symbol FROM stock_candles_1m
                WHERE DATE(time) = %s
                LIMIT 5000
            """, (self.date,))
            symbols = [row[0] for row in cursor.fetchall()]
            cursor.close()

            if not symbols:
                logger.warning(f"No symbols with data for {self.date}")
                return False

            # Get all minute bars for these symbols (4am-12pm ET window)
            bars_by_symbol = db.get_minute_bars(
                symbols,
                self.date,
                start_hour=4,
                end_hour=13  # 13 means up to 12:59 (< 13:00)
            )

            # Load historical data for filtering
            self._load_historical_data(db, symbols)

        # Flatten to list for easier iteration
        self.minute_bars = []
        for symbol, bars in bars_by_symbol.items():
            self.minute_bars.extend(bars)

        if not self.minute_bars:
            logger.warning(f"No minute bars found for {self.date}")
            return False

        # Sort by time
        self.minute_bars.sort(key=lambda x: x['time'])
        logger.info(f"Loaded {len(self.minute_bars)} minute bars for {self.date}")
        return True

    def _load_historical_data(self, db, symbols):
        """Load 20 days of daily data, fundamentals, and prior close"""
        # Get 20 days of daily bars for avg volume calculation
        start_date = self.date - timedelta(days=30)
        daily_bars = db.get_daily_bars(symbols, start_date, self.date)
        self.daily_bars_by_symbol = daily_bars

        # Get prior day close for each symbol
        # Instead of assuming yesterday, find the most recent trading day with data
        # This handles weekends and holidays automatically
        cursor = db.conn.cursor()

        # First, find the most recent date before today that has daily bar data
        cursor.execute("""
            SELECT MAX(DATE(time))
            FROM stock_candles_1d
            WHERE DATE(time) < %s::date
        """, (self.date,))
        result = cursor.fetchone()
        prior_date = result[0] if result[0] else None

        if prior_date:
            cursor.execute("""
                SELECT symbol, close
                FROM stock_candles_1d
                WHERE DATE(time) = %s
            """, (prior_date,))
            for symbol, close in cursor.fetchall():
                self.prior_close[symbol] = float(close)

        # Get fundamentals (float, market cap)
        cursor.execute("""
            SELECT symbol, float_shares, market_cap
            FROM stock_fundamentals
            WHERE symbol = ANY(%s)
        """, (symbols,))
        for row in cursor.fetchall():
            self.fundamentals[row[0]] = {
                'float_shares': row[1],
                'market_cap': row[2]
            }
        cursor.close()

        if self.verbose:
            prior_date_str = prior_date.strftime('%Y-%m-%d') if prior_date else 'none'
            logger.info(f"  Prior close date: {prior_date_str} | Loaded {len(self.prior_close)} prior closes, {len(self.fundamentals)} fundamentals")

    def _calculate_avg_volume(self, symbol):
        """Calculate 20-day average volume for a symbol"""
        bars = self.daily_bars_by_symbol.get(symbol, [])
        if not bars or len(bars) < 5:
            return 0
        volumes = [float(b['volume']) for b in bars[-20:]]
        return sum(volumes) / len(volumes) if volumes else 0

    def _estimate_buy_sell_volume(self, open_price, high, low, close, total_volume):
        """
        Estimate buying vs selling volume from OHLC data

        Buying volume = total_volume × (close - low) / (high - low)
        Selling volume = total_volume × (1 - position)

        Position near 1.0 = close near top = buying pressure
        Position near 0.0 = close near bottom = selling pressure
        """
        open_price = float(open_price)
        high = float(high)
        low = float(low)
        close = float(close)
        total_volume = float(total_volume)

        if high <= low or total_volume == 0:
            # Doji or no volume - assume 50/50 split
            return total_volume * 0.5, total_volume * 0.5

        # Calculate bar position (0 to 1, where 1 = top)
        position = (close - low) / (high - low)
        position = max(0, min(1, position))  # Clamp to 0-1

        buying_volume = total_volume * position
        selling_volume = total_volume * (1 - position)

        return buying_volume, selling_volume

    def _get_volume_direction(self, bar):
        """
        Determine if a bar is bullish (buying) or bearish (selling)

        Returns: ('BULLISH', buying_vol, selling_vol) or ('BEARISH', ...)
        """
        buying_vol, selling_vol = self._estimate_buy_sell_volume(
            bar['open'], bar['high'], bar['low'], bar['close'], bar['volume']
        )

        if buying_vol > selling_vol:
            return 'BULLISH', buying_vol, selling_vol
        elif selling_vol > buying_vol:
            return 'BEARISH', buying_vol, selling_vol
        else:
            return 'NEUTRAL', buying_vol, selling_vol

    def _calculate_relative_volume_at_minute(self, symbol, current_time, current_bars):
        """
        Calculate relative volume at current minute (TIME-OF-DAY ADJUSTED)

        CORRECT formula (NOW FIXED):
            Relative Volume = (volume at time X today) / (avg volume from 4am to time X over last 20 days)

        Example:
            Volume 4am-9:15am today / Avg volume 4am-9:15am over last 20 days

        This accounts for natural volume variation throughout the day:
        - 4am-6am: very low volume
        - 9:30am-10am: peak volume
        - 12pm+: declining volume
        """
        # Get current minute's volume for this symbol
        current_bar = next((b for b in current_bars if b['symbol'] == symbol), None)
        if not current_bar:
            return 0

        current_vol = float(current_bar['volume'])

        # Get historical average volume at this same time of day using database method
        # This is the SAME method used in backtest_scanner.py
        with StockDataDB() as db:
            avg_at_time = db.get_avg_volume_at_time_batch(
                [symbol],
                self.date,
                current_time.hour,
                current_time.minute,
                lookback_days=20
            )

        avg_vol = avg_at_time.get(symbol, 0)
        if avg_vol <= 0:
            return 0

        return current_vol / avg_vol

    def _evaluate_stock_at_minute(self, symbol, current_time, current_bars):
        """
        Evaluate if a stock passes all 5 Ross Cameron pillars at current minute

        Returns:
            (passes: bool, data: dict) where data contains all filter results
        """
        # Find current bar for this symbol
        bar = next((b for b in current_bars if b['symbol'] == symbol), None)
        if not bar:
            return False, {'reason': 'No bar at this minute'}

        current_price = float(bar['close'])

        # PILLAR 1: Price $2-$20
        if current_price < SCANNER_CRITERIA['min_price'] or current_price > SCANNER_CRITERIA['max_price']:
            return False, {'reason': f"Price ${current_price:.2f} outside $2-$20 range"}

        # Get prior close for premarket gain calculation
        prior_close = self.prior_close.get(symbol)
        if prior_close is None:
            return False, {'reason': 'No prior close data'}

        # PILLAR 2: Up 10%+ from prior close
        pct_change = ((current_price - prior_close) / prior_close) * 100
        if pct_change < SCANNER_CRITERIA['min_premarket_gain']:
            return False, {'reason': f"% change {pct_change:.1f}% < 10% min"}

        # PILLAR 3: Relative volume 5x+
        rel_vol = self._calculate_relative_volume_at_minute(symbol, current_time, current_bars)
        if rel_vol < SCANNER_CRITERIA['min_relative_volume']:
            return False, {'reason': f"Relative vol {rel_vol:.1f}x < 5x min"}

        # Volume direction check: Must have BUYING volume, not just total volume
        # This is critical: 200K shares selling ≠ 200K shares buying
        direction, buying_vol, selling_vol = self._get_volume_direction(bar)
        if direction == 'BEARISH' or buying_vol < 50_000:
            return False, {'reason': f"Selling pressure: {direction}, buying vol {buying_vol:,.0f}"}

        # NOTE: We don't filter on average volume anymore.
        # Low average volume + high current volume = strong momentum signal.
        # We use average volume ONLY for calculating relative volume.

        # PILLAR 4: Float <20M shares
        fund = self.fundamentals.get(symbol)
        if fund and fund.get('float_shares'):
            float_shares = fund['float_shares']
            if float_shares > SCANNER_CRITERIA['max_float']:
                return False, {'reason': f"Float {float_shares/1e6:.1f}M > 20M max"}

        # Market cap <$500M
        if fund and fund.get('market_cap'):
            mkt_cap = fund['market_cap']
            if mkt_cap > SCANNER_CRITERIA['max_market_cap']:
                return False, {'reason': f"Market cap ${mkt_cap/1e6:.0f}M > $500M max"}

        # PILLAR 5: News catalyst (TODO - for now, skip)
        # News data would come from news_fetcher

        # All filters passed!
        return True, {
            'symbol': symbol,
            'price': current_price,
            'pct_change': pct_change,
            'rel_vol': rel_vol,
            'float_shares': fund.get('float_shares') if fund else None,
            'market_cap': fund.get('market_cap') if fund else None,
            'volume_direction': direction,
            'buying_volume': buying_vol,
            'selling_volume': selling_vol,
        }

    def run(self):
        """Execute the simulation minute-by-minute"""
        if not self.load_minute_bars():
            return False

        logger.info(f"\n{'='*80}")
        logger.info(f"SIMULATION: {self.date.strftime('%Y-%m-%d')}")
        logger.info(f"Account: ${self.account_size:,.0f}")
        logger.info(f"Risk/trade: {self.risk_pct}%")
        logger.info(f"{'='*80}\n")

        # Group bars by time, get earliest time for each symbol
        bars_by_time = defaultdict(list)
        for bar in self.minute_bars:
            bars_by_time[bar['time']].append(bar)

        # Process each minute
        for minute_time in sorted(bars_by_time.keys()):
            bars_this_minute = bars_by_time[minute_time]
            self._process_minute(minute_time, bars_this_minute)

        logger.info(f"\n{'='*80}\n")
        return True

    def _process_minute(self, current_time, bars):
        """Process a single minute of data"""
        # First, check if position needs to exit on technicals or loss
        if self.position_manager.position:
            pos = self.position_manager.position

            # Find this position's current bar
            pos_bar = next((b for b in bars if b['symbol'] == pos.symbol), None)
            if pos_bar:
                action, detail = self.position_manager.update_position_state(
                    pos_bar['close'],
                    current_time
                )

                # Additional exit signal: selling volume collapse (give back half rule)
                # If in a profitable position and see heavy selling volume
                if not action and self.position_manager.position:  # Only if not already exiting
                    direction, buying_vol, selling_vol = self._get_volume_direction(pos_bar)
                    current_pnl = self.position_manager.get_current_pnl(float(pos_bar['close']))
                    current_price = float(pos_bar['close'])

                    # If profitable and selling volume exceeds buying: exit half
                    if current_pnl > 0 and direction == 'BEARISH' and selling_vol > buying_vol:
                        qty_to_exit = max(1, pos.shares_remaining // 2)
                        if qty_to_exit > 0:
                            self.position_manager.position.scale_out(
                                qty_to_exit,
                                current_price,
                                'SELLING_PRESSURE',
                                current_time
                            )
                            pnl_scale = qty_to_exit * (current_price - pos.entry_price)
                            self.position_manager.current_balance += pnl_scale
                            action = 'scale_out_sell'
                            detail = f"Selling pressure, scaled out {qty_to_exit} shares at ${current_price:.2f}"

                    # CRITICAL: If all shares sold via scaling, close the position and finalize trade
                    if self.position_manager.position and self.position_manager.position.shares_remaining == 0:
                        current_price = float(pos_bar['close'])
                        self.position_manager.position.close_position(current_price, 'FULLY_SCALED', current_time)
                        self.position_manager.trades_completed.append(self.position_manager.position)
                        # NOTE: Don't add get_pnl() again - it was already added during individual scale-outs
                        self.position_manager.position = None
                        if not action:  # Only log if we didn't already log a scale-out
                            action = 'exit'
                            detail = f'Fully exited via scaling at ${current_price:.2f}'

                if action:
                    self.trade_log.append({
                        'time': current_time,
                        'action': action,
                        'detail': detail,
                        'symbol': pos.symbol
                    })
                    if self.verbose:
                        logger.info(f"  {current_time.strftime('%H:%M')} {action:15} {pos.symbol:6} {detail}")

        # Second, check scanner for new signals (only if no position, every 5 minutes for speed)
        # TRADING WINDOW: 9:00 AM - 12:00 PM ET only
        trading_start_hour = 9
        trading_end_hour = 12
        is_trading_hours = trading_start_hour <= current_time.hour < trading_end_hour

        if not self.position_manager.position and current_time.minute % 5 == 0 and is_trading_hours:
            # Get scanner results for this minute
            # This will call the scanner with data up to this minute
            scanner_results = self._get_scanner_signals(current_time, bars)

            # Try to enter a position on best signal
            if scanner_results:
                best = scanner_results[0]  # Best signal by rank

                # Find the bar for this stock
                entry_bar = next((b for b in bars if b['symbol'] == best['symbol']), None)
                if entry_bar:
                    # Calculate entry and stop
                    entry_price = float(entry_bar['close'])
                    # Stop at low of current bar minus 1 cent
                    stop_loss = float(entry_bar['low']) - 0.01

                    # Get day's high so far
                    daily_high = self._get_daily_high_so_far(best['symbol'], current_time)

                    # Try to enter
                    trade = self.position_manager.enter_position(
                        best['symbol'],
                        entry_price,
                        current_time,
                        stop_loss,
                        daily_high
                    )

                    if trade:
                        self.trade_log.append({
                            'time': current_time,
                            'action': 'ENTRY',
                            'symbol': best['symbol'],
                            'price': entry_price,
                            'shares': trade.shares,
                            'stop': stop_loss,
                            'target1': trade.target1,
                            'target2': trade.target2
                        })
                        if self.verbose:
                            logger.info(f"  {current_time.strftime('%H:%M')} ENTRY        {best['symbol']:6} "
                                      f"@ ${entry_price:.2f} x{trade.shares} (stop ${stop_loss:.2f})")

    def _get_scanner_signals(self, current_time, current_bars):
        """
        Get scanner signals for the current minute
        Evaluates Ross Cameron's 5 Pillars: Price, Gain%, Relative Volume, Float, News
        """
        candidates = []

        # Get unique symbols in current bars
        symbols = list(set(b['symbol'] for b in current_bars))

        # Evaluate each symbol against all 5 pillars
        for symbol in symbols:
            passes, data = self._evaluate_stock_at_minute(symbol, current_time, current_bars)
            if passes:
                candidates.append(data)

        # Sort by relative volume (strongest signals first)
        candidates.sort(key=lambda x: x['rel_vol'], reverse=True)

        if candidates and self.verbose:
            logger.info(f"  {current_time.strftime('%H:%M')} Scanner found {len(candidates)} candidates")

        return candidates[:5]  # Return top 5 by relative volume

    def _get_daily_high_so_far(self, symbol, up_to_time):
        """Get the highest close price for symbol up to current time"""
        relevant_bars = [
            b for b in self.minute_bars
            if b['symbol'] == symbol and b['time'] <= up_to_time
        ]

        if not relevant_bars:
            return 0

        return max(b['close'] for b in relevant_bars)

    def print_report(self):
        """Print summary report"""
        stats = self.position_manager.get_stats()

        logger.info(f"\n{'='*80}")
        logger.info(f"RESULTS: {self.date.strftime('%Y-%m-%d')}")
        logger.info(f"{'='*80}\n")

        logger.info(f"Account Start:     ${self.account_size:>12,.0f}")
        logger.info(f"Account End:       ${self.position_manager.current_balance:>12,.0f}")
        profit = self.position_manager.current_balance - self.account_size
        pct = (profit / self.account_size * 100) if self.account_size else 0
        logger.info(f"Total Profit:      ${profit:>12,.0f} ({pct:+.1f}%)\n")

        logger.info(f"Total Trades:      {stats['total_trades']:>12}")
        logger.info(f"  Winners:         {stats['winners']:>12}")
        logger.info(f"  Losers:          {stats['losers']:>12}")
        logger.info(f"Win Rate:          {stats['win_rate']:>12.1f}%")
        logger.info(f"Avg Winner:        ${stats['avg_winner']:>12,.2f}")
        logger.info(f"Avg Loser:         ${stats['avg_loser']:>12,.2f}")
        logger.info(f"Profit Factor:     {stats['profit_factor']:>12.2f}x\n")

        logger.info(f"Best Trade:        ${stats['best_trade']:>12,.2f}")
        logger.info(f"Worst Trade:       ${stats['worst_trade']:>12,.2f}\n")

        logger.info(f"{'='*80}\n")


if __name__ == '__main__':
    # Test: Run simulation for Feb 13 (known good day)
    runner = SimulationRunner(
        date='2026-02-13',
        account_size=5000,
        risk_pct=2.0,
        verbose=True
    )

    runner.run()
    runner.print_report()
