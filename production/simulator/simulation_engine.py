#!/usr/bin/env python3
"""
Simulation Engine: Discrete Event Backtester
==============================================

Feeds historical minute data one minute at a time (no lookahead) and executes
trading logic at CPU speed. Used to validate entry/exit rules and measure
win rate, profit factor, and optimal trading windows.

This file is now a thin harness. All actual strategy logic lives in trading/:
    trading/entry_engine.py  — entry decisions (5 pillars, technicals, patterns)
    trading/exit_engine.py   — exit decisions (stops, targets, EMA, time decay)
    trading/indicators.py    — EMA, MACD, volume direction
    trading/patterns.py      — Bull Flag, Micro Pullback, ABCD, Dip Buy, Flat Top
    trading/models.py        — PatternSignal, EntrySignal, ExitSignal dataclasses

Usage:
    engine = SimulationRunner(date='2026-02-13', account_size=5000, risk_pct=2.0)
    engine.run()
    engine.print_report()
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.query_helpers import StockDataDB
from trading.entry_engine import evaluate_entry
from trading.exit_engine import evaluate_exit
from trading.add_on_engine import evaluate_add_on, AddOnSignal
from trading.indicators import get_current_ema, calculate_macd, estimate_buy_sell_volume
from trading.portfolio_manager import PortfolioManager
from trading.models import ExitConfig, ScannerConfig, EntryConfig, MarketTemperatureConfig, AddOnConfig, ScoringConfig, ExitSignal
from trading.trading_engine import Trade, PositionManager
from trading.market_temperature import (
    TemperatureState, classify_premarket, update_from_trade_result, is_session_over
)
from datetime import datetime, timedelta
import pytz
from collections import defaultdict
import logging
import time
from pathlib import Path
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

ET = pytz.timezone('US/Eastern')
UTC = pytz.UTC

# How many bars of history to keep per symbol for pattern detection
BAR_HISTORY_SIZE = 30  # 30 minutes is enough for all patterns + MACD seed

# Cache to reuse data across trials (keyed by trade date).
_DATA_CACHE = {}
_PERSIST_CACHE_VERSION = "v2"  # bumped: added rel_vol_30d column


class SimulationRunner:
    """
    Minute-by-minute backtesting harness.

    Loads historical data, feeds bars to the trading/ entry and exit engines,
    and records all decisions for reporting.
    """

    def __init__(self, date, account_size=5000, risk_pct=2.0,
                 max_position_pct=20, verbose=True,
                 daily_max_loss_pct=3.0, daily_profit_target=None,
                 exit_config=None, scanner_config=None, entry_config=None,
                 add_on_config=None,
                 scoring_config=None,
                 debug=False, cache_data=False, cache_dir: str | None = None,
                 symbol_universe: list | None = None,
                 max_trades_per_day: int = 3,
                 temp_config=None):
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%d').date()

        self.date = date
        self.account_size = account_size
        self.risk_pct = risk_pct
        self.max_position_pct = max_position_pct
        self.verbose = verbose

        self.position_manager = PositionManager(
            account_size, risk_pct, max_position_pct=max_position_pct
        )
        self.portfolio_manager = PortfolioManager(
            account_size,
            daily_max_loss_pct=daily_max_loss_pct,
            daily_profit_target=daily_profit_target,
        )
        self.exit_config = exit_config       # ExitConfig | None; None = all defaults
        self.scanner_config = scanner_config  # ScannerConfig | None; None = all defaults
        self.entry_config = entry_config      # EntryConfig | None; None = all defaults
        self.add_on_config = add_on_config    # AddOnConfig | None; None = all defaults
        self.scoring_config = scoring_config  # ScoringConfig | None; None = all defaults
        self.debug = debug
        self.cache_data = cache_data
        self.cache_dir = Path(cache_dir) if cache_dir else None
        # Curated symbol list — when set, only load/evaluate these symbols.
        # All scanner pre-screen gates are bypassed (trust the list).
        self.symbol_universe: list | None = symbol_universe
        self._universe_key = frozenset(symbol_universe) if symbol_universe else None

        self.minute_bars = []
        self.minute_array = None
        self.time_index = None
        self.trade_log = []
        self.portfolio_summary = None   # Populated at end of run()

        # Per-symbol rolling bar history (last BAR_HISTORY_SIZE bars, oldest first)
        self.bar_history = defaultdict(list)

        # Per-symbol cumulative volume from 4am today (used for rel_vol numerator).
        # Correct rel_vol = cumulative_today / avg_cumulative_historical.
        # Using single bar volume as numerator (the old approach) causes rel_vol to
        # collapse below 5x after the opening spike, blocking entries after 9:32am.
        self._cumulative_volume = defaultdict(float)

        # Loaded from DB
        self.fundamentals = {}
        self.prior_close = {}
        self.prior_day_high = {}        # Prior trading day's high per symbol (for resistance exits)
        self.daily_bars_by_symbol = {}

        # Per-symbol state updated each minute during the simulation loop
        self._last_macd_histogram = defaultdict(lambda: None)  # For MACD flip detection

        # Persistent DB connection kept open during simulation loop
        self._db = None

        self.max_trades_per_day = max_trades_per_day

        # Market temperature — classifies HOT/NEUTRAL/COLD/CHOP at 9:15 AM ET
        # and adjusts max_position_pct, max_trades_per_day, session_stop_time dynamically.
        self.temp_config: MarketTemperatureConfig = temp_config or MarketTemperatureConfig()
        self.temp_state: TemperatureState = TemperatureState()  # Starts COLD (safe default)

        # Track symbols that exited via TIME_DECAY to prevent re-entry same day
        self.time_decay_exits = set()
        # GAP-14: track stop-out count per symbol to apply cooldown rules:
        #   1st stop-out → allow 1 re-entry at 50% size
        #   2nd stop-out on same symbol → block re-entry entirely
        self.stop_hit_counts: dict[str, int] = {}
        self._stats = {}

        # Pre-computed set of symbols that pass price/gain filters for this day.
        # Built once at load time to avoid iterating all ~4000 symbols every minute.
        self.hot_symbols: set = set()

    # ── Data Loading ──────────────────────────────────────────────────────────

    def load_minute_bars(self):
        if self.cache_data and self.date in _DATA_CACHE:
            cached = _DATA_CACHE[self.date]
            # Invalidate if the cached universe doesn't match ours
            if cached.get('universe_key') != self._universe_key:
                del _DATA_CACHE[self.date]
            else:
                pass  # fall through to load from cache below
        if self.cache_data and self.date in _DATA_CACHE:
            cached = _DATA_CACHE[self.date]
            self.minute_array = cached['minute_array']
            self.time_index = cached['time_index']
            self.daily_bars_by_symbol = cached['daily_bars_by_symbol']
            self.prior_close = cached['prior_close']
            self.prior_day_high = cached['prior_day_high']
            self.fundamentals = cached['fundamentals']
            premarket_volume = cached['premarket_volume_by_symbol']

            self._cumulative_volume = defaultdict(float)
            for symbol, vol in premarket_volume.items():
                self._cumulative_volume[symbol] = vol

            if self.debug:
                self._stats['load_seconds'] = 0.0
                self._stats['symbols_total'] = cached['symbols_total']
                self._stats['minute_bars_total'] = len(self.minute_array)
                self._stats['hour_symbols_seeded'] = len(premarket_volume)
                self._stats['prior_close_count'] = len(self.prior_close)
                self._stats['fundamentals_count'] = len(self.fundamentals)
                self._stats['historical_load_seconds'] = 0.0
                self._stats['cache_hit'] = True
            if self.verbose:
                logger.info(f"Loaded {len(self.minute_array):,} minute bars for {self.date} (memory cache)")
                logger.info(f"Seeded cumulative volume from 4am-8am hourly bars for {len(premarket_volume)} symbols")
            # hot_symbols is already stored in _DATA_CACHE from a prior load
            self.hot_symbols = cached.get('hot_symbols', set())
            return True

        if self.cache_data and self.cache_dir:
            cached = self._load_persisted_cache()
            if cached:
                return True

        t0 = time.perf_counter()
        with StockDataDB() as db:
            cursor = db.conn.cursor()
            start_et = ET.localize(datetime.combine(self.date, datetime.min.time()).replace(hour=8, minute=0))
            end_et = ET.localize(datetime.combine(self.date, datetime.min.time()).replace(hour=13, minute=0))
            start_utc = start_et.astimezone(UTC)
            end_utc = end_et.astimezone(UTC)
            if self.symbol_universe:
                cursor.execute("""
                    SELECT DISTINCT symbol FROM stock_candles_1m
                    WHERE time >= %s AND time < %s AND symbol = ANY(%s)
                    LIMIT 5000
                """, (start_utc, end_utc, self.symbol_universe))
            else:
                cursor.execute("""
                    SELECT DISTINCT symbol FROM stock_candles_1m
                    WHERE time >= %s AND time < %s
                    LIMIT 5000
                """, (start_utc, end_utc))
            symbols = [row[0] for row in cursor.fetchall()]

            if not symbols:
                cursor.close()
                logger.warning(f"No symbols with data for {self.date}")
                return False

            # Load 8am-12pm minute bars (trading window) as a flat list (faster).
            if self.symbol_universe:
                cursor.execute("""
                    SELECT time, symbol, open, high, low, close, volume, rel_vol_30d, vwap
                    FROM stock_candles_1m
                    WHERE time >= %s AND time < %s AND symbol = ANY(%s)
                    ORDER BY time
                """, (start_utc, end_utc, self.symbol_universe))
            else:
                cursor.execute("""
                    SELECT time, symbol, open, high, low, close, volume, rel_vol_30d, vwap
                    FROM stock_candles_1m
                    WHERE time >= %s AND time < %s
                    ORDER BY time
                """, (start_utc, end_utc))
            minute_rows = cursor.fetchall()

            # Load 4am-8am hourly bars for premarket volume seed (flat list).
            h_start_et = ET.localize(datetime.combine(self.date, datetime.min.time()).replace(hour=4, minute=0))
            h_end_et = ET.localize(datetime.combine(self.date, datetime.min.time()).replace(hour=8, minute=0))
            h_start_utc = h_start_et.astimezone(UTC)
            h_end_utc = h_end_et.astimezone(UTC)
            if self.symbol_universe:
                cursor.execute("""
                    SELECT time, symbol, open, high, low, close, volume, vwap
                    FROM stock_candles_1h
                    WHERE time >= %s AND time < %s AND symbol = ANY(%s)
                    ORDER BY time
                """, (h_start_utc, h_end_utc, self.symbol_universe))
            else:
                cursor.execute("""
                    SELECT time, symbol, open, high, low, close, volume, vwap
                    FROM stock_candles_1h
                    WHERE time >= %s AND time < %s
                    ORDER BY time
                """, (h_start_utc, h_end_utc))
            hour_rows = cursor.fetchall()

            cursor.close()
            self._load_historical_data(db, symbols)

        # Seed cumulative volume with premarket hourly bars (4am-8am)
        self._cumulative_volume = defaultdict(float)
        premarket_volume = defaultdict(float)
        for row in hour_rows:
            symbol = row[1]
            premarket_volume[symbol] += float(row[6])
        for symbol, vol in premarket_volume.items():
            self._cumulative_volume[symbol] = vol

        self.minute_array = np.array(
            minute_rows,
            dtype=object,
        )
        self.time_index = defaultdict(list)
        for idx, row in enumerate(self.minute_array):
            self.time_index[row[0]].append(idx)

        if self.minute_array.size == 0:
            logger.warning(f"No minute bars found for {self.date}")
            return False

        if self.verbose:
            logger.info(f"Loaded {len(self.minute_array):,} minute bars for {self.date}")
            logger.info(f"Seeded cumulative volume from 4am-8am hourly bars for {len(set([r[1] for r in hour_rows]))} symbols")
        if self.debug:
            self._stats['load_seconds'] = time.perf_counter() - t0
            self._stats['symbols_total'] = len(symbols)
            self._stats['minute_bars_total'] = len(self.minute_array)
            self._stats['hour_symbols_seeded'] = len(set([r[1] for r in hour_rows]))
            self._stats['cache_hit'] = False

        self.hot_symbols = self._build_hot_symbols()
        if self.cache_data:
            _DATA_CACHE[self.date] = {
                'minute_array': self.minute_array,
                'time_index': dict(self.time_index),
                'premarket_volume_by_symbol': dict(premarket_volume),
                'daily_bars_by_symbol': self.daily_bars_by_symbol,
                'prior_close': self.prior_close,
                'prior_day_high': self.prior_day_high,
                'fundamentals': self.fundamentals,
                'symbols_total': len(symbols),
                'hot_symbols': self.hot_symbols,
                'universe_key': self._universe_key,
            }
        if self.cache_data and self.cache_dir:
            self._persist_cache(dict(premarket_volume), symbols)
        return True

    def _build_hot_symbols(self) -> set:
        """
        Scan minute_array once to find symbols that are worth evaluating this day.

        A symbol qualifies if ANY of its bars has price in [min_price, max_price]
        AND gain% >= min_gain vs prior_close.  We use hardcoded defaults (price
        $2-$20, gain 10%) regardless of the current trial's scanner_config so the
        result can be safely cached and shared across all trials in the same process.
        This makes hot_symbols a safe superset — the per-minute Stage 1 checks still
        apply the exact trial thresholds as a secondary filter.
        """
        MIN_PRICE = 2.0
        MAX_PRICE = 20.0
        MIN_GAIN  = 10.0

        hot = set()
        for row in self.minute_array:
            symbol = row[1]
            if symbol in hot:
                continue
            prior = self.prior_close.get(symbol)
            if not prior or prior <= 0:
                continue
            close = float(row[5])
            if close < MIN_PRICE or close > MAX_PRICE:
                continue
            if (close - prior) / prior * 100 < MIN_GAIN:
                continue
            hot.add(symbol)
        return hot

    def _load_historical_data(self, db, symbols):
        t0 = time.perf_counter()
        start_date = self.date - timedelta(days=30)
        self.daily_bars_by_symbol = db.get_daily_bars(symbols, start_date, self.date)

        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT MAX(DATE(time)) FROM stock_candles_1d
            WHERE DATE(time) < %s::date
        """, (self.date,))
        result = cursor.fetchone()
        prior_date = result[0] if result[0] else None

        if prior_date:
            cursor.execute("""
                SELECT symbol, close, high FROM stock_candles_1d WHERE DATE(time) = %s
            """, (prior_date,))
            for symbol, close, high in cursor.fetchall():
                self.prior_close[symbol] = float(close)
                self.prior_day_high[symbol] = float(high)

        cursor.execute("""
            SELECT symbol, float_shares, market_cap FROM stock_fundamentals
            WHERE symbol = ANY(%s)
        """, (symbols,))
        for row in cursor.fetchall():
            self.fundamentals[row[0]] = {
                'float_shares': row[1], 'market_cap': row[2]
            }
        cursor.close()

        if self.verbose:
            prior_str = prior_date.strftime('%Y-%m-%d') if prior_date else 'none'
            logger.info(
                f"  Prior close: {prior_str} | "
                f"{len(self.prior_close)} closes, {len(self.fundamentals)} fundamentals"
            )
        if self.debug:
            self._stats['prior_close_count'] = len(self.prior_close)
            self._stats['fundamentals_count'] = len(self.fundamentals)
            self._stats['historical_load_seconds'] = time.perf_counter() - t0

    # ── Simulation Loop ───────────────────────────────────────────────────────

    def run(self):
        if not self.load_minute_bars():
            return False

        if self.verbose:
            logger.info(f"\n{'='*80}")
            logger.info(f"SIMULATION: {self.date.strftime('%Y-%m-%d')}")
            logger.info(f"Account: ${self.account_size:,.0f} | Risk/trade: {self.risk_pct}%")
            logger.info(f"{'='*80}\n")

        bars_by_time = self.time_index if self.time_index is not None else defaultdict(list)

        # Reset daily tracking
        self.time_decay_exits = set()
        self.stop_hit_counts = {}
        self.portfolio_manager.reset_day()

        # Keep one DB connection open for the whole simulation loop
        # (rel-vol batch queries use this instead of opening per symbol)
        t0 = time.perf_counter()
        with StockDataDB() as db:
            self._db = db
            for minute_time in sorted(bars_by_time.keys()):
                bars = []
                if self.minute_array is not None:
                    for idx in bars_by_time[minute_time]:
                        row = self.minute_array[idx]
                        bars.append({
                            'time': row[0],
                            'symbol': row[1],
                            'open': row[2],
                            'high': row[3],
                            'low': row[4],
                            'close': row[5],
                            'volume': row[6],
                            'rel_vol_30d': row[7],
                            'vwap': row[8],
                        })
                else:
                    bars = bars_by_time[minute_time]
                self._process_minute(minute_time, bars)
            self._db = None
        if self.debug:
            self._stats['simulation_seconds'] = time.perf_counter() - t0

        # Finalize portfolio-level analysis (counterfactual rule outcomes)
        final_pnl = self.position_manager.current_balance - self.account_size
        self.portfolio_summary = self.portfolio_manager.get_daily_summary(final_pnl)

        if self.verbose:
            logger.info(f"\n{'='*80}\n")
        if self.debug:
            self._log_debug_summary()
        return True

    def _process_minute(self, current_time, bars):
        """
        Process one minute of data.

        Order (no lookahead — history updated BEFORE decisions):
            1. Update rolling bar history for all symbols
            2. Exit check for open position
            3. Entry scan (9:30am-12pm only, enforced in entry_engine)
        """
        et_time = current_time.astimezone(ET)

        # ── Temperature: classify at 9:15 AM ET (once per session) ───────────
        if (et_time.hour == 9 and et_time.minute == 15
                and not self.temp_state.premarket_classified):
            self.temp_state = classify_premarket(
                self.hot_symbols,
                self.prior_close,
                self.temp_config,
                bars_snapshot=bars,
            )
            # Apply temperature-derived limits (override constructor defaults)
            self.max_trades_per_day = self.temp_state.max_trades_per_day
            self.max_position_pct   = self.temp_state.max_position_pct
            self.position_manager.max_position_pct = self.temp_state.max_position_pct
            if self.verbose:
                logger.info(
                    f"  09:15 [TEMP] {self.temp_state.temperature.value}"
                    f"  gapper={self.temp_state.leading_gapper_pct:.0f}%"
                    f"  symbols={self.temp_state.qualifying_symbols_count}"
                    f"  → max_pos={self.temp_state.max_position_pct:.0f}%"
                    f"  max_trades={self.temp_state.max_trades_per_day}"
                    f"  stop={self.temp_state.session_stop_hour}:{self.temp_state.session_stop_minute:02d}"
                )

        # ── Temperature: force-close open position at session stop time ───────
        if (self.temp_state.premarket_classified
                and is_session_over(self.temp_state, current_time)
                and self.position_manager.position):
            pos = self.position_manager.position
            pos_bar = next((b for b in bars if b['symbol'] == pos.symbol), None)
            close_price = float(pos_bar['close']) if pos_bar else pos.entry_price
            force_exit = ExitSignal(
                reason='SESSION_STOP',
                price=close_price,
                qty=pos.shares_remaining,
            )
            pnl = self.position_manager.apply_exit_signal(force_exit, current_time)
            self.trade_log.append({
                'time': current_time,
                'action': 'SESSION_STOP',
                'symbol': pos.symbol,
                'price': close_price,
                'qty': force_exit.qty,
                'pnl': round(pnl, 2),
            })
            self.portfolio_manager.update(
                current_time=current_time,
                pnl_delta=pnl,
                trades_completed=len(self.position_manager.trades_completed),
            )
            if self.verbose:
                logger.info(
                    f"  {et_time.strftime('%H:%M')} SESSION_STOP"
                    f"  {pos.symbol:6} @ ${close_price:.2f}"
                    f"  P&L ${pnl:+.2f}"
                    f"  ({self.temp_state.temperature.value} session stop)"
                )

        # Step 1: Update bar history and cumulative volume
        for bar in bars:
            sym = bar['symbol']
            self.bar_history[sym].append(bar)
            if len(self.bar_history[sym]) > BAR_HISTORY_SIZE:
                self.bar_history[sym].pop(0)
            self._cumulative_volume[sym] += float(bar['volume'])

        # Step 2: Exit check
        if self.position_manager.position:
            pos = self.position_manager.position
            pos_bar = next((b for b in bars if b['symbol'] == pos.symbol), None)

            if pos_bar:
                history = self.bar_history.get(pos.symbol, [])
                prices = [float(b['close']) for b in history]
                ema9 = get_current_ema(prices, 9)
                macd = calculate_macd(prices)

                # Update highest price seen since entry (for trailing stop)
                current_price = float(pos_bar['close'])
                if current_price > pos.highest_price_since_entry:
                    pos.highest_price_since_entry = current_price

                # Compute avg buying volume of last 5 bars (for volume dry-up check)
                avg_buy_vol = None
                if len(history) >= 5:
                    buy_vols = [
                        estimate_buy_sell_volume(
                            b['open'], b['high'], b['low'], b['close'], b['volume']
                        )[0]
                        for b in history[-5:]
                    ]
                    avg_buy_vol = sum(buy_vols) / len(buy_vols)

                # Build enriched indicators dict
                macd_hist = macd['histogram'] if macd else None
                macd_line = macd['macd_line'] if macd else None
                indicators = {
                    'ema9': ema9,
                    'macd_line': macd_line,
                    'macd_histogram': macd_hist,
                    'macd_histogram_prev': self._last_macd_histogram[pos.symbol],
                    'prior_day_high': self.prior_day_high.get(pos.symbol),
                    'avg_buy_vol_5bar': avg_buy_vol,
                }

                # Advance MACD state for next bar
                self._last_macd_histogram[pos.symbol] = macd_hist

                exit_signal = evaluate_exit(
                    position=pos,
                    current_bar=pos_bar,
                    indicators=indicators,
                    current_time=current_time,
                    config=self.exit_config,
                    temperature=self.temp_state,
                )

                if exit_signal:
                    pnl = self.position_manager.apply_exit_signal(exit_signal, current_time)
                    self.trade_log.append({
                        'time': current_time,
                        'action': exit_signal.reason,
                        'symbol': pos.symbol,
                        'price': exit_signal.price,
                        'qty': exit_signal.qty,
                        'pnl': round(pnl, 2),
                    })
                    # Notify portfolio manager of every fill — rules enforced in Step 3
                    self.portfolio_manager.update(
                        current_time=current_time,
                        pnl_delta=pnl,
                        trades_completed=len(self.position_manager.trades_completed),
                    )
                    # Track TIME_DECAY exits to prevent re-entry same day
                    if exit_signal.reason == 'TIME_DECAY':
                        self.time_decay_exits.add(pos.symbol)
                    # GAP-14: track stop-outs — 1st allows half-size re-entry, 2nd blocks entirely
                    if exit_signal.reason == 'STOP_HIT':
                        self.stop_hit_counts[pos.symbol] = \
                            self.stop_hit_counts.get(pos.symbol, 0) + 1
                    # Temperature update: after a full close, update consecutive losses
                    if self.position_manager.position is None and pos.exit_reason:
                        win = pos.get_pnl() > 0
                        self.temp_state = update_from_trade_result(
                            self.temp_state, win, self.temp_config
                        )
                        if self.temp_state.temperature.value == 'CHOP' and self.verbose:
                            logger.info(
                                f"  {current_time.astimezone(ET).strftime('%H:%M')}"
                                f" [TEMP] upgraded to CHOP after"
                                f" {self.temp_state.consecutive_losses} consecutive"
                                f" losses — reducing to 5% size, max 1 trade"
                            )
                    if self.verbose:
                        logger.info(
                            f"  {current_time.astimezone(ET).strftime('%H:%M')} "
                            f"{exit_signal.reason:20} {pos.symbol:6} "
                            f"@ ${exit_signal.price:.2f} x{exit_signal.qty} "
                            f"P&L ${pnl:+.2f}"
                        )

        # Step 2b: Add-on check
        # Runs only when a position survived the exit check this bar.
        # evaluate_add_on() checks profitability, time window, and trigger gates.
        # After evaluation (add or no-add), advance session_high_at_add watermark.
        if self.position_manager.position:
            pos = self.position_manager.position
            pos_bar = next((b for b in bars if b['symbol'] == pos.symbol), None)
            if pos_bar:
                history = self.bar_history.get(pos.symbol, [])
                # Compute indicators for add-on evaluation
                prices = [float(b['close']) for b in history]
                ema9_ao = get_current_ema(prices, 9)
                macd_ao = calculate_macd(prices)
                indicators_ao = {
                    'ema9': ema9_ao,
                    'macd_line': macd_ao['macd_line'] if macd_ao else None,
                }

                add_on_sig = evaluate_add_on(
                    position=pos,
                    current_bar=pos_bar,
                    bar_history=history[:-1],   # exclude current (no lookahead)
                    indicators=indicators_ao,
                    current_time=current_time,
                    config=self.add_on_config,
                    temperature=self.temp_state,
                )
                if add_on_sig:
                    added_qty = self.position_manager.apply_add_on(add_on_sig, current_time)
                    if added_qty > 0:
                        self.trade_log.append({
                            'time': current_time,
                            'action': f'ADD_ON_{add_on_sig.reason}',
                            'symbol': pos.symbol,
                            'price': add_on_sig.price,
                            'qty': added_qty,
                            'pnl': 0.0,  # Buy — no realized P&L yet
                        })
                        if self.verbose:
                            et_str = current_time.astimezone(ET).strftime('%H:%M')
                            logger.info(
                                f"  {et_str} ADD_ON [{add_on_sig.reason:16}] "
                                f"{pos.symbol:6} @ ${add_on_sig.price:.2f} "
                                f"x{added_qty} (add #{pos.add_on_count}) "
                                f"new_stop=${add_on_sig.new_stop:.2f}"
                            )

                # Always advance high watermark after evaluation (regardless of add)
                bar_high = float(pos_bar.get('high', pos_bar['close']))
                if bar_high > pos.session_high_at_add:
                    pos.session_high_at_add = bar_high

        # Step 3: Entry scan
        # Portfolio rules (DAILY_MAX_LOSS, GREEN_TO_RED, GIVE_BACK_HALF) block
        # all new entries once fired — enforced here, not just observed.
        if self.position_manager.can_enter_trade():
            completed_today = len(self.position_manager.trades_completed)
            # Temperature-driven session stop: no new entries after session_stop_hour:min
            if self.temp_state.premarket_classified and is_session_over(self.temp_state, current_time):
                pass  # silent — session stop already logged on position close
            elif self.portfolio_manager.any_rule_fired():
                if self.verbose:
                    rule = next(
                        r for r, fired in self.portfolio_manager._rule_fired.items() if fired
                    )
                    et_str = current_time.astimezone(ET).strftime('%H:%M')
                    logger.info(
                        f"  {et_str} [HALTED] {rule} fired — no new entries today"
                    )
            elif completed_today >= self.max_trades_per_day:
                if self.verbose:
                    et_str = current_time.astimezone(ET).strftime('%H:%M')
                    logger.info(
                        f"  {et_str} [HALTED] max trades/day reached ({completed_today}/{self.max_trades_per_day})"
                    )
            else:
                self._scan_for_entry(current_time, bars)

    def _scan_for_entry(self, current_time, bars):
        """Evaluate all symbols and enter on the best signal.

        Performance: quick price+gain pre-filter, then ONE batch DB call for
        rel-vol on only the small set of candidates that survive the filter.
        Reduces DB calls from O(symbols × minutes) to ~O(minutes).
        """
        et_time = current_time.astimezone(ET)

        # ── Step 1: Cheap in-memory pre-filter (price + gain %) ──────────────
        # Use scanner_config thresholds if provided, otherwise use defaults.
        # This must mirror the 5-pillar logic in entry_engine._check_5_pillars()
        # so that only genuine candidates reach the expensive DB rel-vol query.
        scfg = self.scanner_config if self.scanner_config is not None else ScannerConfig()
        min_price = scfg.min_price
        max_price = scfg.max_price
        min_gain = scfg.min_premarket_gain

        if self.debug:
            self._stats.setdefault('minutes_processed', 0)
            self._stats.setdefault('bars_seen', 0)
            self._stats.setdefault('candidates_stage1', 0)
            self._stats.setdefault('candidates_stage2', 0)
            self._stats.setdefault('entries_found', 0)
            self._stats.setdefault('entry_evaluations', 0)
            self._stats.setdefault('rel_vol_batch_calls', 0)

        # Universe mode: bypass all scanner pre-screens — trust the curated list.
        # When symbol_universe is set, every symbol in the list is a candidate;
        # only the bar-history minimum and time-decay exclusion still apply.
        universe_mode = self.symbol_universe is not None

        candidates = []
        for bar in bars:
            symbol = bar['symbol']
            if not universe_mode:
                # Fast pre-filter: skip symbols not in the pre-computed hot list.
                if self.hot_symbols and symbol not in self.hot_symbols:
                    continue
            # Skip symbols that exited via TIME_DECAY (no re-entry same day)
            if symbol in self.time_decay_exits:
                continue
            # GAP-14: 2nd stop-out on same symbol → blocked entirely
            if self.stop_hit_counts.get(symbol, 0) >= 2:
                continue
            history = self.bar_history.get(symbol, [])
            if len(history) < 7:  # Need enough bars for patterns
                continue
            if not universe_mode:
                price = float(bar['close'])
                prior = self.prior_close.get(symbol)
                if not prior or prior <= 0:
                    continue
                if scfg.enable_price_range:
                    if price < min_price or price > max_price:
                        continue
                if scfg.enable_premarket_gain:
                    if (price - prior) / prior * 100 < min_gain:
                        continue
            candidates.append((symbol, bar, history))
        if self.debug:
            self._stats['minutes_processed'] += 1
            self._stats['bars_seen'] += len(bars)
            self._stats['candidates_stage1'] += len(candidates)

        if not candidates:
            return

        # ── Step 2: Resolve relative volume for all candidates ────────────────
        # Prefer the pre-computed rel_vol_30d column (backfilled into stock_candles_1m).
        # Fall back to a live batch DB query only for symbols where it is NULL.
        avg_vols = {}

        if scfg.enable_relative_volume and not universe_mode:
            # Determine which symbols need a live DB query (rel_vol_30d is NULL).
            # Skip the DB query before 9:30 AM: evaluate_entry() enforces the trading
            # window gate so any entry would be rejected anyway, making the query wasted.
            # Also skip entirely in universe mode — scanner filters are bypassed.
            in_trading_window = (
                et_time.hour > 9 or (et_time.hour == 9 and et_time.minute >= 30)
            )
            symbols_need_query = (
                [sym for sym, bar, _ in candidates if bar.get('rel_vol_30d') is None]
                if in_trading_window else []
            )
            if symbols_need_query and self._db:
                try:
                    if self.debug:
                        self._stats['rel_vol_batch_calls'] += 1
                    avg_vols = self._db.get_avg_volume_at_time_batch(
                        symbols_need_query, self.date,
                        et_time.hour, et_time.minute,
                        lookback_days=20,
                        include_premarket_hourly=True,
                    )
                except Exception:
                    pass  # Graceful degradation — rel_vol will be 0 for these

        # ── Step 3: Full entry evaluation for remaining candidates ─────────────
        best_signal = None
        best_bar = None

        for symbol, bar, history in candidates:
            if self.debug:
                self._stats['entry_evaluations'] += 1

            # Use pre-computed rel_vol_30d if available; otherwise fall back to
            # live cumulative calculation via avg_vols from the DB query above.
            precomputed = bar.get('rel_vol_30d')
            if precomputed is not None:
                rel_vol = float(precomputed)
            else:
                avg_vol = avg_vols.get(symbol, 0)
                cum_vol = self._cumulative_volume.get(symbol, 0)
                rel_vol = cum_vol / avg_vol if avg_vol > 0 else 0.0

            entry_signal = evaluate_entry(
                symbol=symbol,
                bar_history=history[:-1],   # exclude current (already appended)
                current_bar=bar,
                fundamentals=self.fundamentals.get(symbol, {}),
                prior_close=self.prior_close.get(symbol),
                current_time=current_time,
                relative_volume=rel_vol,
                scanner_config=self.scanner_config,
                entry_config=self.entry_config,
                temperature=self.temp_state,
                # news_tier: defaults to 'unknown' (4 pts) — backtest graceful degradation.
                # Wire live news pre-cache here when news API is enabled.
                news_tier='unknown',
                scoring_config=self.scoring_config,
            )

            if entry_signal is None:
                continue

            if (best_signal is None or
                    entry_signal.pattern.confidence > best_signal.pattern.confidence or
                    (entry_signal.pattern.confidence == best_signal.pattern.confidence and
                     entry_signal.pillar_data.get('rel_vol', 0) >
                     best_signal.pillar_data.get('rel_vol', 0))):
                best_signal = entry_signal
                best_bar = bar

        if best_signal and best_bar:
            if self.debug:
                self._stats['entries_found'] += 1
            pat = best_signal.pattern
            fund = self.fundamentals.get(best_signal.symbol, {})

            # Composite size multiplier = score × GAP-14 cooldown
            # Score drives temperature-adjusted initial sizing (HOT=1.0, COLD=0.5, etc.)
            # GAP-14 further halves on first re-entry after stop-out on same symbol.
            stop_hit_n = self.stop_hit_counts.get(best_signal.symbol, 0)
            gap14_mult = 0.5 if stop_hit_n == 1 else 1.0

            score_mult = 1.0
            if best_signal.entry_score is not None:
                scfg = self.scoring_config if self.scoring_config is not None else ScoringConfig()
                score_mult = best_signal.entry_score.size_multiplier(
                    self.temp_state.temperature.value, scfg
                )

            size_mult = gap14_mult * score_mult

            trade = self.position_manager.enter_position(
                symbol=best_signal.symbol,
                entry_price=pat.entry_price,
                entry_time=current_time,
                stop_loss_price=pat.stop_price,
                target1=pat.target1,
                target2=pat.target2,
                pattern_type=pat.pattern_type,
                float_shares=fund.get('float_shares'),  # GAP-11: float-bucket cap
                size_multiplier=size_mult,               # GAP-14: cooldown sizing
            )
            if trade:
                self.trade_log.append({
                    'time': current_time,
                    'action': 'ENTRY',
                    'symbol': best_signal.symbol,
                    'pattern': pat.pattern_type,
                    'price': pat.entry_price,
                    'shares': trade.shares,
                    'stop': pat.stop_price,
                    'target1': pat.target1,
                    'target2': pat.target2,
                    'reasoning': pat.reasoning,
                })
                if self.verbose:
                    et_str = current_time.astimezone(ET).strftime('%H:%M')
                    logger.info(
                        f"  {et_str} ENTRY [{pat.pattern_type:14}] "
                        f"{best_signal.symbol:6} @ ${pat.entry_price:.2f} "
                        f"x{trade.shares} stop ${pat.stop_price:.2f} | {pat.reasoning}"
                    )
        if self.debug:
            self._stats['candidates_stage2'] += len(candidates)

    def _log_debug_summary(self):
        stats = self._stats
        logger.info("DEBUG SUMMARY")
        logger.info(f"  load_seconds          : {stats.get('load_seconds', 0):.2f}")
        logger.info(f"  historical_load_seconds: {stats.get('historical_load_seconds', 0):.2f}")
        logger.info(f"  simulation_seconds    : {stats.get('simulation_seconds', 0):.2f}")
        logger.info(f"  symbols_total         : {stats.get('symbols_total', 0)}")
        logger.info(f"  minute_bars_total     : {stats.get('minute_bars_total', 0)}")
        logger.info(f"  hour_symbols_seeded   : {stats.get('hour_symbols_seeded', 0)}")
        logger.info(f"  prior_close_count     : {stats.get('prior_close_count', 0)}")
        logger.info(f"  fundamentals_count    : {stats.get('fundamentals_count', 0)}")
        logger.info(f"  minutes_processed     : {stats.get('minutes_processed', 0)}")
        logger.info(f"  bars_seen             : {stats.get('bars_seen', 0)}")
        logger.info(f"  candidates_stage1     : {stats.get('candidates_stage1', 0)}")
        logger.info(f"  candidates_stage2     : {stats.get('candidates_stage2', 0)}")
        logger.info(f"  entry_evaluations     : {stats.get('entry_evaluations', 0)}")
        logger.info(f"  rel_vol_batch_calls   : {stats.get('rel_vol_batch_calls', 0)}")
        logger.info(f"  entries_found         : {stats.get('entries_found', 0)}")
        logger.info(f"  cache_hit             : {stats.get('cache_hit', False)}")

    # ── Persistent Cache ────────────────────────────────────────────────────

    def _cache_prefix(self) -> Path:
        assert self.cache_dir is not None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        date_str = self.date.strftime('%Y-%m-%d')
        return self.cache_dir / f"simcache_{_PERSIST_CACHE_VERSION}_{date_str}"

    def _load_persisted_cache(self) -> bool:
        if not self.cache_dir:
            return False
        prefix = self._cache_prefix()
        minute_path = prefix.with_suffix(".minute.parquet")
        premarket_path = prefix.with_suffix(".premarket.parquet")
        prior_path = prefix.with_suffix(".prior.parquet")
        fundamentals_path = prefix.with_suffix(".fundamentals.parquet")
        if not (minute_path.exists() and premarket_path.exists() and prior_path.exists() and fundamentals_path.exists()):
            return False
        try:
            import pyarrow.parquet as pq
        except Exception:
            logger.warning("PyArrow not available; skipping persisted cache load.")
            return False

        t0 = time.perf_counter()
        minute_tbl = pq.read_table(minute_path)
        premarket_tbl = pq.read_table(premarket_path)
        prior_tbl = pq.read_table(prior_path)
        fundamentals_tbl = pq.read_table(fundamentals_path)

        minute_rows = minute_tbl.to_pylist()
        self.minute_array = np.array(
            [
                (r['time'], r['symbol'], r['open'], r['high'], r['low'], r['close'], r['volume'], r.get('rel_vol_30d'), r['vwap'])
                for r in minute_rows
            ],
            dtype=object,
        )
        self.time_index = defaultdict(list)
        for idx, row in enumerate(self.minute_array):
            self.time_index[row[0]].append(idx)
        premarket_rows = premarket_tbl.to_pylist()
        self.prior_close = {r['symbol']: float(r['close']) for r in prior_tbl.to_pylist()}
        self.prior_day_high = {r['symbol']: float(r['high']) for r in prior_tbl.to_pylist()}
        self.fundamentals = {
            r['symbol']: {
                'float_shares': r.get('float_shares'),
                'market_cap': r.get('market_cap'),
            }
            for r in fundamentals_tbl.to_pylist()
        }

        self._cumulative_volume = defaultdict(float)
        for row in premarket_rows:
            self._cumulative_volume[row['symbol']] = float(row['volume'])

        if self.debug:
            self._stats['load_seconds'] = time.perf_counter() - t0
            self._stats['symbols_total'] = len(self.prior_close)
            self._stats['minute_bars_total'] = len(self.minute_array)
            self._stats['hour_symbols_seeded'] = len(premarket_rows)
            self._stats['prior_close_count'] = len(self.prior_close)
            self._stats['fundamentals_count'] = len(self.fundamentals)
            self._stats['historical_load_seconds'] = 0.0
            self._stats['cache_hit'] = True

        if self.verbose:
            logger.info(f"Loaded {len(self.minute_array):,} minute bars for {self.date} (persisted cache)")
            logger.info(f"Seeded cumulative volume from 4am-8am hourly bars for {len(premarket_rows)} symbols")

        self.hot_symbols = self._build_hot_symbols()
        _DATA_CACHE[self.date] = {
            'minute_array': self.minute_array,
            'time_index': dict(self.time_index),
            'premarket_volume_by_symbol': {r['symbol']: float(r['volume']) for r in premarket_rows},
            'daily_bars_by_symbol': self.daily_bars_by_symbol,
            'prior_close': self.prior_close,
            'prior_day_high': self.prior_day_high,
            'fundamentals': self.fundamentals,
            'symbols_total': len(self.prior_close),
            'hot_symbols': self.hot_symbols,
            'universe_key': self._universe_key,
        }
        return True

    def _persist_cache(self, premarket_volume: dict, symbols: list[str]) -> None:
        if not self.cache_dir:
            return
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except Exception:
            logger.warning("PyArrow not available; skipping persisted cache write.")
            return

        prefix = self._cache_prefix()
        minute_path = prefix.with_suffix(".minute.parquet")
        premarket_path = prefix.with_suffix(".premarket.parquet")
        prior_path = prefix.with_suffix(".prior.parquet")
        fundamentals_path = prefix.with_suffix(".fundamentals.parquet")

        minute_tbl = pa.Table.from_pylist(
            [
                {
                    'time': row[0],
                    'symbol': row[1],
                    'open': row[2],
                    'high': row[3],
                    'low': row[4],
                    'close': row[5],
                    'volume': row[6],
                    'rel_vol_30d': row[7],
                    'vwap': row[8],
                }
                for row in self.minute_array
            ]
        )
        premarket_tbl = pa.Table.from_pylist(
            [{'symbol': s, 'volume': float(v)} for s, v in premarket_volume.items()]
        )
        prior_tbl = pa.Table.from_pylist(
            [{'symbol': s, 'close': self.prior_close.get(s), 'high': self.prior_day_high.get(s)}
             for s in self.prior_close.keys()]
        )
        fundamentals_tbl = pa.Table.from_pylist(
            [{'symbol': s,
              'float_shares': self.fundamentals.get(s, {}).get('float_shares'),
              'market_cap': self.fundamentals.get(s, {}).get('market_cap')}
             for s in self.fundamentals.keys()]
        )

        pq.write_table(minute_tbl, minute_path)
        pq.write_table(premarket_tbl, premarket_path)
        pq.write_table(prior_tbl, prior_path)
        pq.write_table(fundamentals_tbl, fundamentals_path)

    # ── Reporting ─────────────────────────────────────────────────────────────

    def print_report(self):
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

        completed = self.position_manager.trades_completed
        if completed:
            patterns = defaultdict(lambda: {'count': 0, 'pnl': 0.0, 'wins': 0})
            for t in completed:
                p = patterns[t.pattern_type]
                p['count'] += 1
                p['pnl'] += t.get_pnl()
                if t.is_winner():
                    p['wins'] += 1
            logger.info(f"{'─'*60}")
            logger.info(f"  Pattern Breakdown:")
            for ptype, data in sorted(patterns.items(), key=lambda x: -x[1]['pnl']):
                wr = data['wins'] / data['count'] * 100 if data['count'] else 0
                logger.info(
                    f"    {ptype:18} {data['count']:2} trades  "
                    f"WR {wr:.0f}%  P&L ${data['pnl']:+.2f}"
                )

        # ── Portfolio Rule Analysis (counterfactual — no enforcement) ──────────
        ps = self.portfolio_summary
        if ps:
            logger.info(f"\n{'─'*60}")
            logger.info(f"  Portfolio Rule Analysis (would-have-fired, NOT enforced):")
            logger.info(f"    Peak P&L today:    ${ps['peak_pnl']:>+.2f}")

            rule_labels = {
                'DAILY_MAX_LOSS':  'Daily Max Loss  ',
                'GREEN_TO_RED':    'Green-to-Red    ',
                'GIVE_BACK_HALF':  'Give-Back-Half  ',
            }
            for rule, label in rule_labels.items():
                info = ps['rules'].get(rule, {})
                if info.get('fired'):
                    verdict = info['verdict']
                    saved = info['saved_or_cost']
                    logger.info(
                        f"    {label}  WOULD FIRE @ {info['fire_time_et']} "
                        f"(P&L ${info['pnl_at_fire']:+.2f}) → "
                        f"{verdict} ${abs(saved):.2f}"
                    )
                else:
                    logger.info(f"    {label}  did not fire")

        logger.info(f"\n{'='*80}\n")


if __name__ == '__main__':
    runner = SimulationRunner(
        date='2026-02-13',
        account_size=5000,
        risk_pct=2.0,
        verbose=True
    )
    runner.run()
    runner.print_report()
