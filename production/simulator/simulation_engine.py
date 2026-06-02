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
from simulator.sim_broker import SimBroker
from trading.orchestrator import Orchestrator, _noop_rel_vol_resolver
from trading.market_temperature import (
    TemperatureState, classify_premarket, update_from_trade_result, is_session_over
)
from trading.entry_gate import entry_blocked_reason, PORTFOLIO_RULE
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
BAR_HISTORY_SIZE = 40  # H0 FIX: was 30 < 35 (=slow26+signal9) so calculate_macd ALWAYS
                       # returned None → MACD entry/exit gates were silently DEAD in the sim
                       # (optimizer tuned with MACD off). 40 matches live BAR_HISTORY_DEPTH.

# Cache to reuse data across trials (keyed by trade date).
_DATA_CACHE: dict = {}          # date → cached day data
_DATA_CACHE_MAX = 250           # LRU safety cap
_PERSIST_CACHE_VERSION = "v2"  # bumped: added rel_vol_30d column

# Global symbol table — maps symbol string ↔ uint16 index.
# Shared across all days so each unique string is allocated once.
_SYM_TO_IDX: dict = {}         # 'TSLA' → 0
_IDX_TO_SYM: list = []         # 0 → 'TSLA'

def _intern_symbol(sym: str) -> int:
    """Return uint16 index for symbol, registering if new."""
    idx = _SYM_TO_IDX.get(sym)
    if idx is None:
        idx = len(_IDX_TO_SYM)
        _SYM_TO_IDX[sym] = idx
        _IDX_TO_SYM.append(sym)
    return idx


def save_memory_cache(path: str) -> int:
    """Persist the full in-memory _DATA_CACHE + symbol table to a pickle file.
    Returns number of days saved. Call after trial 0 completes so subsequent
    process restarts skip the ~2hr warm-up."""
    import pickle
    global _DATA_CACHE, _SYM_TO_IDX, _IDX_TO_SYM
    blob = {
        'version': _PERSIST_CACHE_VERSION,
        'data_cache': _DATA_CACHE,
        'sym_to_idx': _SYM_TO_IDX,
        'idx_to_sym': _IDX_TO_SYM,
    }
    with open(path, 'wb') as f:
        pickle.dump(blob, f, protocol=pickle.HIGHEST_PROTOCOL)
    return len(_DATA_CACHE)


def load_memory_cache(path: str) -> int:
    """Load a previously saved memory cache. Returns number of days loaded,
    or 0 if file doesn't exist or version mismatch."""
    import pickle
    global _DATA_CACHE, _SYM_TO_IDX, _IDX_TO_SYM
    try:
        with open(path, 'rb') as f:
            blob = pickle.load(f)
        if blob.get('version') != _PERSIST_CACHE_VERSION:
            return 0
        _DATA_CACHE = blob['data_cache']
        _SYM_TO_IDX = blob['sym_to_idx']
        _IDX_TO_SYM = blob['idx_to_sym']
        return len(_DATA_CACHE)
    except (FileNotFoundError, EOFError, pickle.UnpicklingError, KeyError):
        return 0




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
                 momentum_config=None,
                 debug=False, cache_data=False, cache_dir: str | None = None,
                 symbol_universe: list | None = None,
                 temp_config=None,
                 enable_news_cache: bool = True):
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%d').date()

        self.date = date
        self.account_size = account_size
        self.risk_pct = risk_pct
        self.max_position_pct = max_position_pct
        self.verbose = verbose

        # Step 3 (de-logic): orders go through the SimBroker adapter, not PositionManager
        # directly. self.position_manager stays pointed at the SAME PM instance so all
        # existing reporting/stat refs are unchanged — only enter/exit/add_on are routed.
        self.broker = SimBroker(
            account_size, risk_pct=risk_pct, max_position_pct=max_position_pct
        )
        self.position_manager = self.broker.position_manager
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
        self.momentum_config = momentum_config  # MomentumScanConfig | None; None = all defaults
        self.debug = debug
        self.cache_data = cache_data
        self.cache_dir = Path(cache_dir) if cache_dir else None
        # Curated symbol list — when set, only load/evaluate these symbols.
        # All scanner pre-screen gates are bypassed (trust the list).
        self.symbol_universe: list | None = symbol_universe
        self._universe_key = frozenset(symbol_universe) if symbol_universe else None

        self.minute_bars = []
        self.minute_array = None   # float64 array: [unix_ts, open, high, low, close, volume, rel_vol, vwap]
        self.minute_syms = None    # object array of symbol strings, parallel to minute_array rows
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


        # Market temperature — classifies HOT/NEUTRAL/COLD/CHOP at 9:25 AM ET
        # and adjusts max_position_pct, session_stop_time dynamically.
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

        # News tier cache: symbol → 'tier1'|'tier2'|'tier3'|'presence'|'none'|'unknown'
        # Populated by _prefetch_news() after hot_symbols is built.
        # enable_news_cache=False disables the Alpaca API call (for fast offline backtests).
        self.news_cache: dict[str, str] = {}
        self.enable_news_cache: bool = enable_news_cache

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
            self.minute_syms = cached['minute_syms']
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
            # Always rebuild hot_symbols from the cached minute_array rather than
            # restoring the saved set. The saved set may be stale if MIN_GAIN changed
            # between runs (e.g. optimizer tuning m_min_intraday_gain). Rebuild is
            # fast (one numpy-backed loop) vs. loading all bars from DB.
            self.hot_symbols = self._build_hot_symbols()
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

        # Split into efficient arrays: float64 numerics + uint16 symbol indices.
        # Avoids ~86 MB/day Python object overhead from dtype=object.
        # Columns: [unix_ts, open, high, low, close, volume, rel_vol_or_nan, vwap]
        if minute_rows:
            self.minute_syms = np.array([_intern_symbol(r[1]) for r in minute_rows], dtype=np.uint16)
            self.minute_array = np.array(
                [(r[0].timestamp(), r[2], r[3], r[4], r[5], r[6],
                  float('nan') if r[7] is None else r[7], r[8])
                 for r in minute_rows],
                dtype=np.float64,
            )
        else:
            self.minute_syms = np.array([], dtype=np.uint16)
            self.minute_array = np.empty((0, 8), dtype=np.float64)
        _ti: dict = {}
        for idx in range(len(self.minute_array)):
            dt = datetime.fromtimestamp(self.minute_array[idx, 0], tz=ET)
            if dt not in _ti:
                _ti[dt] = []
            _ti[dt].append(idx)
        self.time_index = {k: np.array(v, dtype=np.uint32) for k, v in _ti.items()}

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
                'minute_syms': self.minute_syms,
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
            # LRU eviction: keep at most _DATA_CACHE_MAX days in memory
            while len(_DATA_CACHE) > _DATA_CACHE_MAX:
                _DATA_CACHE.pop(next(iter(_DATA_CACHE)))
        if self.cache_data and self.cache_dir:
            self._persist_cache(dict(premarket_volume), symbols)
        return True

    def _build_hot_symbols(self) -> set:
        """
        Scan minute_array once to find symbols that are worth evaluating this day.

        A symbol qualifies if ANY of its bars has price in [min_price, max_price]
        AND gain% >= min_gain vs prior_close.  We use hardcoded defaults regardless
        of the current trial's config so the result can be safely cached and shared
        across all trials in the same process.

        MIN_GAIN must be <= the Optuna search space floor for m_min_intraday_gain
        (currently 2.0) so this set is always a true superset of what
        qualifies_momentum() could approve at any gain threshold Optuna tries.
        qualifies_momentum() is the authoritative gate — this is only a coarse
        pre-filter to avoid scanning all 4000 symbols every minute.
        """
        # TODO (SIM/LIVE DIVERGENCE — low priority):
        # This scans the WHOLE day's bars to build the superset (look-ahead).
        # A stock that surges at 2 PM is in hot_symbols from 9:30 AM. In live
        # trading, symbols are discovered in real-time via the per-minute
        # intraday scan (_run_intraday_momentum_scan). qualifies_momentum()'s
        # time-forward gates (G2 HOD, G3 time, G6 gain) prevent acting on
        # future data, so no incorrect trades result — but the sim evaluates
        # some candidates earlier than live would discover them, which can
        # cause slightly more entries than live. True time-forward sim discovery
        # would require running a streaming intraday scan during simulation.
        MIN_PRICE = 1.0   # match lowest possible a_min_price in Optuna search space
        MAX_PRICE = 25.0  # match highest possible a_max_price in Optuna search space
        MIN_GAIN  = 5.0   # must match Optuna search space floor for m_min_intraday_gain

        hot = set()
        for idx in range(len(self.minute_array)):
            symbol = _IDX_TO_SYM[self.minute_syms[idx]]
            if symbol in hot:
                continue
            prior = self.prior_close.get(symbol)
            if not prior or prior <= 0:
                continue
            close = self.minute_array[idx, 4]   # col 4 = close (0=unix_ts,1=open,2=high,3=low,4=close)
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

    # ── News Pre-Cache ────────────────────────────────────────────────────────

    def _prefetch_news(self):
        """
        Pre-fetch and classify news for all hot_symbols at simulation-day start.

        Populates self.news_cache[symbol] = tier string so _scan_for_entry() can
        pass a real news_tier to evaluate_entry() instead of 'unknown'.

        Graceful degradation: any symbol that fails (API error, rate limit, etc.)
        falls back to 'unknown' (4/20 scoring pts — partial credit).

        Disabled when enable_news_cache=False (fast offline backtests).
        """
        if not self.enable_news_cache or not self.hot_symbols:
            return

        try:
            from backend.news_fetcher import NewsFetcher, classify_news_tier
            fetcher = NewsFetcher()
        except Exception as e:
            logger.warning(f"  [NEWS] Init failed — {e}. All symbols defaulting to 'unknown'.")
            return

        t0 = time.perf_counter()
        symbols = list(self.hot_symbols)
        success = 0
        for symbol in symbols:
            try:
                articles = fetcher.get_news_for_symbol(
                    symbol, as_of_date=self.date, hours_back=48
                )
                self.news_cache[symbol] = classify_news_tier(articles)
                success += 1
            except Exception:
                self.news_cache[symbol] = 'unknown'

        elapsed = time.perf_counter() - t0
        if self.verbose:
            tier_counts: dict[str, int] = {}
            for t in self.news_cache.values():
                tier_counts[t] = tier_counts.get(t, 0) + 1
            logger.info(
                f"  [NEWS] Cached {success}/{len(symbols)} symbols in {elapsed:.1f}s"
                f"  tiers={tier_counts}"
            )

    # ── Simulation Loop ───────────────────────────────────────────────────────

    def run(self):
        if not self.load_minute_bars():
            return False

        # Pre-fetch news tiers for hot_symbols (populates self.news_cache).
        # Skipped when enable_news_cache=False or Alpaca news API unavailable.
        self._prefetch_news()

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

        # De-logic: the per-minute decision pipeline now lives in the shared Orchestrator.
        # It drives the SAME broker/PositionManager (so trades_completed + balance, which
        # reporting reads, are unchanged) and owns fresh per-day decision state. The sim is
        # now only a data-feed loader + SimBroker. rel_vol DB lookups stay in the sim via the
        # injected resolver (orchestrator imports no DB).
        self.orch = Orchestrator(
            broker=self.broker,
            scanner_config=self.scanner_config,
            entry_config=self.entry_config,
            exit_config=self.exit_config,
            scoring_config=self.scoring_config,
            add_on_config=self.add_on_config,
            momentum_config=self.momentum_config,
            temp_config=self.temp_config,
            portfolio_manager=self.portfolio_manager,
            hot_symbols=self.hot_symbols,
            prior_close=self.prior_close,
            fundamentals=self.fundamentals,
            prior_day_high=self.prior_day_high,
            symbol_universe=self.symbol_universe,
            news_cache=self.news_cache,
            # When cache_data=True (optimizer), skip DB rel_vol resolver. Bars already
            # carry precomputed rel_vol_30d; NaN bars get rel_vol=0 (rejected). This
            # eliminates 26s/day of DB queries in the sim loop. Live trading and
            # non-cached sim runs still use the full DB resolver.
            rel_vol_resolver=(
                _noop_rel_vol_resolver if self.cache_data
                else self._resolve_rel_vol
            ),
            max_position_pct=self.max_position_pct,
            verbose=self.verbose,
            debug=self.debug,
        )

        # Keep one DB connection open for the whole simulation loop
        # (rel-vol batch queries use this instead of opening per symbol).
        # When cache_data=True, the noop resolver is used, so no DB needed.
        t0 = time.perf_counter()
        _db_ctx = StockDataDB() if not self.cache_data else None
        _db_obj = _db_ctx.__enter__() if _db_ctx else None
        self._db = _db_obj
        try:
            # Pre-compute relevant symbol set for this day: hot_symbols + any
            # open position symbol (needed for exit evaluation even if not hot).
            relevant_syms = set(self.hot_symbols)

            # ── Pre-filter: build per-symbol-id index, then assemble only hot bars ─
            # Without this, the inner loop iterates all ~3000+ symbols per minute
            # just to find the ~7-50 hot ones (770K+ wasted Python iterations/day).
            # One-time O(N) scan builds sym_id → {minute → [indices]}, then the
            # per-minute loop does O(|hot|) dict lookups instead of O(|all|) scans.
            _sym_to_id = {sname: sid for sid, sname in enumerate(_IDX_TO_SYM)}
            if self.minute_array is not None:
                hot_sym_ids = {_sym_to_id[s] for s in relevant_syms if s in _sym_to_id}

                # sym_id → {minute_time → [row indices]}
                _sym_minute_idx: dict[int, dict] = defaultdict(lambda: defaultdict(list))
                for minute_time, indices in bars_by_time.items():
                    for idx in indices:
                        _sym_minute_idx[self.minute_syms[idx]][minute_time].append(idx)
            else:
                hot_sym_ids = None
                _sym_minute_idx = None

            sorted_minutes = sorted(bars_by_time.keys())
            for minute_time in sorted_minutes:
                # Include open position symbol so exit logic always sees its bars.
                pos = self.orch.broker.position
                if pos is not None and hot_sym_ids is not None:
                    pos_id = _sym_to_id.get(pos.symbol)
                    if pos_id is not None and pos_id not in hot_sym_ids:
                        hot_sym_ids.add(pos_id)

                bars = []
                if self.minute_array is not None:
                    for sym_id in hot_sym_ids:
                        for idx in _sym_minute_idx.get(sym_id, {}).get(minute_time, []):
                            r = self.minute_array[idx]
                            sym = _IDX_TO_SYM[self.minute_syms[idx]]
                            rv = r[6]
                            bars.append({
                                'time': minute_time,
                                'symbol': sym,
                                'open': r[1],
                                'high': r[2],
                                'low': r[3],
                                'close': r[4],
                                'volume': r[5],
                                'rel_vol_30d': None if (rv != rv) else rv,  # NaN → None
                                'vwap': r[7],
                            })
                else:
                    bars = [b for b in bars_by_time[minute_time]
                            if b['symbol'] in relevant_syms]
                self.orch.on_minute(minute_time, bars)
            self._db = None
        finally:
            if _db_ctx is not None:
                _db_ctx.__exit__(None, None, None)
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

    def _resolve_rel_vol(self, candidates, et_time):
        """Injected into the Orchestrator: resolve avg-volume denominators for rel-vol via
        the DB (the one sim/data concern that must NOT live in the engine). Mirrors the old
        _scan_for_entry DB block. Returns {symbol: avg_vol}. Only called for symbols whose
        bar lacks a precomputed rel_vol_30d, in the trading window, in non-universe mode."""
        avg_vols = {}
        in_trading_window = (
            et_time.hour > 9 or (et_time.hour == 9 and et_time.minute >= 30)
        )
        symbols_need_query = (
            [sym for sym, bar, _ in candidates if bar.get('rel_vol_30d') is None]
            if in_trading_window else []
        )
        if symbols_need_query and self._db:
            minute_key = et_time.hour * 60 + et_time.minute
            day_avg_cache = None
            if self.cache_data and self.date in _DATA_CACHE:
                day_avg_cache = _DATA_CACHE[self.date].setdefault('avg_vols_by_minute', {})
                cached_avgs = day_avg_cache.get(minute_key)
                if cached_avgs is not None:
                    avg_vols = cached_avgs
                    symbols_need_query = []
            if symbols_need_query:
                try:
                    avg_vols = self._db.get_avg_volume_at_time_batch(
                        symbols_need_query, self.date,
                        et_time.hour, et_time.minute,
                        lookback_days=20,
                        include_premarket_hourly=True,
                    )
                    if day_avg_cache is not None:
                        day_avg_cache[minute_key] = avg_vols
                except Exception:
                    pass
        return avg_vols

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
        if minute_rows:
            self.minute_syms = np.array([_intern_symbol(r['symbol']) for r in minute_rows], dtype=np.uint16)
            self.minute_array = np.array(
                [(r['time'].timestamp(), r['open'], r['high'], r['low'], r['close'],
                  r['volume'], float('nan') if r.get('rel_vol_30d') is None else r['rel_vol_30d'], r['vwap'])
                 for r in minute_rows],
                dtype=np.float64,
            )
        else:
            self.minute_syms = np.array([], dtype=np.uint16)
            self.minute_array = np.empty((0, 8), dtype=np.float64)
        _ti: dict = {}
        for idx in range(len(self.minute_array)):
            dt = datetime.fromtimestamp(self.minute_array[idx, 0], tz=ET)
            if dt not in _ti:
                _ti[dt] = []
            _ti[dt].append(idx)
        self.time_index = {k: np.array(v, dtype=np.uint32) for k, v in _ti.items()}
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
            'minute_syms': self.minute_syms,
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
        # LRU eviction
        while len(_DATA_CACHE) > _DATA_CACHE_MAX:
            _DATA_CACHE.pop(next(iter(_DATA_CACHE)))
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
                    'time': datetime.fromtimestamp(self.minute_array[i, 0], tz=ET),
                    'symbol': _IDX_TO_SYM[self.minute_syms[i]],
                    'open': self.minute_array[i, 1],
                    'high': self.minute_array[i, 2],
                    'low': self.minute_array[i, 3],
                    'close': self.minute_array[i, 4],
                    'volume': self.minute_array[i, 5],
                    'rel_vol_30d': None if (self.minute_array[i, 6] != self.minute_array[i, 6]) else self.minute_array[i, 6],
                    'vwap': self.minute_array[i, 7],
                }
                for i in range(len(self.minute_array))
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
