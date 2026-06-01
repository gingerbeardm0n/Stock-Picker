"""
Live Scanner
============
Real-time gap-run detection, relative volume calculation, and
entry/exit signal orchestration for live/paper trading.

Two classes:
  GapRunTracker  — per-symbol stateful streaming gap-run detector
  LiveScanner    — main orchestrator: consumes bars from AlpacaBarStream,
                   maintains state, calls entry_engine / exit_engine,
                   feeds signals to LiveTradeManager

Data Flow:
    AlpacaBarStream (queue) → LiveScanner.process_bar()
        → GapRunTracker.update()            (4am–9:29am: detect ≥5% gap-run)
        → evaluate_entry() from entry_engine (9:30am–11am: look for patterns)
        → LiveTradeManager.execute_entry()   (place paper/live order)
        → evaluate_exit()  from exit_engine  (while position open)
        → LiveTradeManager.execute_exit()    (scale out or close)

Relative Volume:
    Numerator:   cumulative volume tracked in _today_volume[symbol]
    Denominator: get_avg_volume_at_time_batch() from query_helpers.py
                 (same batch DB query used by the simulator — no change needed)
    Cached once per minute across all hot symbols.

Usage:
    scanner = LiveScanner(trade_manager, symbols)
    scanner.startup_preload()   # load prior closes + fundamentals from DB
    # Then per bar:
    scanner.process_bar(bar_dict)
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from collections import defaultdict, deque
from datetime import datetime, date
from typing import Optional

import pytz

from trading.entry_engine import evaluate_entry
from trading.exit_engine import evaluate_exit
from trading.indicators import get_current_ema, calculate_macd, estimate_buy_sell_volume, is_trending_up
from trading.models import (
    ScannerConfig, EntryConfig, ExitConfig, ScoringConfig, AddOnConfig, MarketTemperatureConfig,
    MomentumScanConfig,
)
from trading.momentum_scanner import qualifies_momentum
from trading.order_manager import LiveTradeManager
from trading.broker.base import DataFeedInterface
from trading.orchestrator import Orchestrator
from trading.live_broker import LiveBroker
from trading.portfolio_manager import PortfolioManager
from utils.query_helpers import StockDataDB

logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')

# Bar history depth — enough for pattern detection + EMA/MACD
BAR_HISTORY_DEPTH = 40

# Gap-run: consecutive green candles totalling ≥ MIN_GAPRUN_GAIN_PCT
MIN_GAPRUN_GAIN_PCT = 5.0

# Allow up to 90s between bars before breaking a streak
# (premarket data can arrive late)
MAX_CONSECUTIVE_GAP_SECS = 90

# Premarket DB scan: snapshot times (ET hour, minute) before market open
PREMARKET_SCAN_TIMES = [(9, 25), (9, 28)]

# Premarket DB scan thresholds (Pillars 2, 3, 4)
PREMARKET_MIN_GAIN_PCT   = 10.0          # Pillar 2: up 10%+ from prior close
PREMARKET_MIN_REL_VOL    = 5.0           # Pillar 3: 5x relative volume minimum
PREMARKET_MAX_FLOAT      = 100_000_000   # Pillar 4: 100M share float cap (skip if no data)

# Maximum total watchlist size for bar_poller (1 HTTP/symbol/min -> cap protects 1-min cycle)
# The SCAN itself runs every minute (cheap: ~20 batched quote calls for 4000 symbols).
# The CAP limits how many symbols the poller tracks after discovery.
INTRADAY_WATCHLIST_CAP = 50


# ─────────────────────────────────────────────────────────────────────────────
# GapRunTracker — per-symbol streaming gap-run state machine
# ─────────────────────────────────────────────────────────────────────────────

class GapRunTracker:
    """
    Stateful gap-run detector for a single symbol.

    A gap-run is a streak of consecutive green candles (close > open) where
    the cumulative gain from the streak's first open to the current close ≥ 5%.

    Streaming equivalent of find_gap_runs() in generate_daily_gaprun_universe.py.
    Reset at start of each trading day via reset().
    """

    def __init__(self):
        self.run_start_open: float | None = None
        self.last_bar_time: datetime | None = None
        self.max_gain_seen: float = 0.0   # Track peak gain for logging

    def reset(self):
        """Call at start of each new trading day."""
        self.run_start_open = None
        self.last_bar_time = None
        self.max_gain_seen = 0.0

    def update(self, bar: dict) -> float | None:
        """
        Update state with a new bar.

        Returns cumulative gain % if the bar completes a qualifying gap-run
        (≥ MIN_GAPRUN_GAIN_PCT), else None.

        Resets the run if:
          - bar is red (close <= open), OR
          - gap > MAX_CONSECUTIVE_GAP_SECS since last bar (non-consecutive)
        """
        is_green = bar['close'] > bar['open']

        # Check consecutiveness — allow some slack for late premarket data
        if self.last_bar_time is not None:
            gap_secs = (bar['time'] - self.last_bar_time).total_seconds()
            is_consecutive = gap_secs <= MAX_CONSECUTIVE_GAP_SECS
        else:
            is_consecutive = True

        self.last_bar_time = bar['time']

        if not is_green or not is_consecutive:
            self.run_start_open = None
            return None

        # Extend or start streak
        if self.run_start_open is None:
            self.run_start_open = bar['open']

        if self.run_start_open <= 0:
            return None

        gain = (bar['close'] / self.run_start_open - 1.0) * 100.0
        if gain > self.max_gain_seen:
            self.max_gain_seen = gain

        return gain if gain >= MIN_GAPRUN_GAIN_PCT else None


# ─────────────────────────────────────────────────────────────────────────────
# LiveScanner — main orchestrator
# ─────────────────────────────────────────────────────────────────────────────

class LiveScanner:
    """
    Consumes 1-minute bars from AlpacaBarStream's queue and:
      - Tracks per-symbol bar history and cumulative volume
      - Detects gap-runs in premarket (4am–9:29am ET)
      - Calls evaluate_entry() for gap-run qualified symbols at market open
      - Calls evaluate_exit() while a position is open
      - Calls LiveTradeManager.execute_entry() / execute_exit() on signals

    Only one position at a time (strategy constraint).
    """

    def __init__(
        self,
        trade_manager: LiveTradeManager,
        symbols: list[str],
        data_feed: DataFeedInterface | None = None,
        scanner_config: ScannerConfig | None = None,
        entry_config: EntryConfig | None = None,
        exit_config: ExitConfig | None = None,
        entry_hour_end: int = 11,
        dry_run: bool = False,
        momentum_config: MomentumScanConfig | None = None,
    ):
        self._trade_manager  = trade_manager
        self._symbols        = symbols
        self._data_feed      = data_feed        # DataFeedInterface — used for premarket scanning
        self._scanner_config = scanner_config   # None = use evaluate_entry() defaults
        self._entry_config   = entry_config
        self._exit_config    = exit_config
        self._entry_hour_end = entry_hour_end   # ET hour to stop looking for entries (default 11am)
        self._dry_run        = dry_run          # If True: log signals but don't place orders
        self._momentum_config = momentum_config or MomentumScanConfig()  # intraday scanner config

        # Per-symbol rolling bar history (oldest first)
        self._bar_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=BAR_HISTORY_DEPTH)
        )

        # Cumulative volume since 4am today (for relative volume numerator)
        self._today_volume: dict[str, int] = defaultdict(int)

        # Gap-run state machine per symbol
        self._gap_trackers: dict[str, GapRunTracker] = defaultdict(GapRunTracker)

        # Symbols that have passed ≥5% gap-run detection (WebSocket streamer)
        self._gaprun_qualified: set[str] = set()

        # Symbols added by the DB premarket scan (9:25 / 9:28 snapshots)
        self._premarket_qualified: set[str] = set()

        # Tracks which (hour, minute) premarket scans have already run today
        self._premarket_scans_done: set[tuple] = set()

        # Dedup: last (hour, minute) the intraday scan ran — prevents firing twice
        # in the same minute when multiple bars arrive for different symbols.
        self._last_intraday_scan_minute: tuple[int, int] | None = None

        # Prior day close prices (pre-loaded from DB at startup)
        self._prior_close: dict[str, float] = {}

        # Float + market cap fundamentals (pre-loaded from DB at startup)
        self._fundamentals: dict[str, dict] = {}

        # Relative volume denominator cache — refreshed once per minute
        self._avg_vol_cache: dict[str, float] = {}
        self._avg_vol_cache_minute: tuple[int, int] | None = None

        # Track which day we last reset (to reset state at start of each day)
        self._current_trade_date: date | None = None

        # DB connection (persistent — used for historical avg vol, prior closes, fundamentals)
        self._db = StockDataDB()

        # Diagnostic: track last minute we logged a gate failure per symbol (avoid spam)
        self._diag_last_minute: dict[str, tuple[int, int]] = {}

        # Last gate failure reason per symbol (for status JSON export)
        self._last_gate: dict[str, str] = {}

        # ── Per-minute best-signal selection (mirrors simulator's _scan_for_entry) ──
        # Bars arrive from WebSocket roughly alphabetically. Without this buffer,
        # we'd enter on the FIRST passing signal each minute rather than the STRONGEST.
        # We collect all signals for the current minute and execute the best one at
        # the start of the NEXT minute (after all symbols have had a chance to be seen).
        self._best_signal_candidate: dict | None = None   # {signal, symbol, bar}
        self._scan_minute: tuple[int, int] | None = None  # (hour, minute) of current batch

        # ── Orchestrator path (de-logic flip), flag-gated — default OFF (old path runs) ──
        # When True, process_bar batches the minute's bars and runs the shared Orchestrator
        # (full strategy: temperature/scoring/add-ons/portfolio) instead of the per-bar
        # collect/execute/exit code. Flip to True from run_trading only after a dry-run
        # session has been verified against a sim of the same day.
        self._use_orchestrator: bool = False
        self._minute_bars: list[dict] = []
        self._minute_bars_ts = None

        # Symbols that exited via TIME_DECAY — blocked from re-entry same day
        # (matches simulator's time_decay_exits set)
        self._time_decay_exits: set[str] = set()

        # Set to True after a premarket scan completes — run_trading.py checks
        # this to write session_status.json immediately (don't wait for heartbeat)
        self.status_write_requested: bool = False

        logger.info(f"LiveScanner initialized for {len(symbols):,} symbols")

    # ── Public API ────────────────────────────────────────────────────────────

    def startup_preload(self):
        """
        Pre-load static reference data from DB and rebuild watchlist if restarting
        after the premarket scan window has already passed.

        collect_data.py is no longer required — today's bars and volume come directly
        from the Alpaca REST API inside _run_premarket_db_snapshot().
        """
        now_et = datetime.now(pytz.UTC).astimezone(ET)
        self._current_trade_date = now_et.date()

        logger.info("Pre-loading prior closes from stock_candles_1d...")
        self._prior_close = self._db.get_latest_prices(symbols=self._symbols)
        logger.info(f"  Loaded prior closes for {len(self._prior_close):,} symbols")

        logger.info("Pre-loading fundamentals (float, market cap)...")
        self._fundamentals = self._db.get_fundamentals_batch(self._symbols)
        logger.info(f"  Loaded fundamentals for {len(self._fundamentals):,} symbols")

        # Always run the premarket scan at startup to immediately build the watchlist
        # and verify the Alpaca REST API is working. The 9:25 / 9:28 scheduled scans
        # will still fire and refresh the list closer to open.
        past_first_scan = now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= PREMARKET_SCAN_TIMES[0][1])
        self._run_premarket_db_snapshot(now_et)
        if past_first_scan:
            # Already past scheduled scan window — mark done so they don't re-fire
            self._premarket_scans_done.update(PREMARKET_SCAN_TIMES)

    def process_bar(self, bar: dict):
        """
        Main per-bar callback. Call once per bar from the main processing loop.

        bar dict format: {'symbol', 'time' (UTC datetime), 'open', 'high',
                          'low', 'close', 'volume'}
        """
        symbol  = bar['symbol']
        now_utc = bar['time']
        now_et  = now_utc.astimezone(ET)

        # ── Day rollover ──────────────────────────────────────────────────────
        today = now_et.date()
        if today != self._current_trade_date:
            self._on_new_day(today)

        # ── Update rolling state ──────────────────────────────────────────────
        self._bar_history[symbol].append(bar)
        self._today_volume[symbol] += bar['volume']

        # ── Gap-run / momentum detection (all hours: 4am onward) ────────────
        # Runs during premarket AND market hours — catches both premarket gappers
        # and intraday momentum stocks (consecutive green candles totalling ≥5%).
        in_premarket = now_et.hour < 9 or (now_et.hour == 9 and now_et.minute < 30)
        gain = self._gap_trackers[symbol].update(bar)
        if gain is not None and symbol not in self._gaprun_qualified:
            self._gaprun_qualified.add(symbol)
            phase = "PREMARKET GAPRUN" if in_premarket else "INTRADAY GAPRUN"
            logger.info(f"{phase} DETECTED: {symbol} +{gain:.1f}% cumulative "
                        f"(streak from ${self._gap_trackers[symbol].run_start_open:.2f} "
                        f"to ${bar['close']:.2f})")

        # ── Premarket DB snapshot at 9:25 and 9:28 ───────────────────────────
        hm = (now_et.hour, now_et.minute)
        if hm in PREMARKET_SCAN_TIMES and hm not in self._premarket_scans_done:
            self._run_premarket_db_snapshot(now_et)
            self._premarket_scans_done.add(hm)
            self.status_write_requested = True   # signal main loop to flush status now

        # ── Intraday momentum scan — every minute 9:30–11:00 ────────────────
        # The quote batch (~20 calls for 4000 symbols) is fast enough to run every
        # minute. Only bar fetches happen for NEW off-watchlist candidates, so cost
        # is near-zero when nothing new is moving. The watchlist cap (50) protects
        # the per-minute bar_poller cycle regardless of scan frequency.
        after_open_for_scan = now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)
        before_scan_end = now_et.hour < self._momentum_config.scan_end_hour
        if after_open_for_scan and before_scan_end:
            scan_minute = (now_et.hour, now_et.minute)
            if scan_minute != self._last_intraday_scan_minute:
                self._last_intraday_scan_minute = scan_minute
                self._run_intraday_momentum_scan(now_et)
                # status_write_requested set inside only when new symbols added;
                # run_trading.py syncs bar_poller.set_watchlist() on next loop iter

        # ── Orchestrator path (flag-gated) ───────────────────────────────────
        # Batch the minute's bars; at the minute boundary run the shared engine once.
        # Replaces the per-bar collect/execute/exit path below. Default OFF.
        if self._use_orchestrator:
            minute_key = (now_et.hour, now_et.minute)
            if self._scan_minute is not None and minute_key != self._scan_minute and self._minute_bars:
                self._ensure_orchestrator().on_minute(self._minute_bars_ts, self._minute_bars)
                self._minute_bars = []
            self._scan_minute = minute_key
            if not self._minute_bars:
                self._minute_bars_ts = now_utc
            self._minute_bars.append(bar)
            return

        # ── Entry evaluation (9:30am up to entry_hour_end, gap-run symbols) ────
        after_open    = now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)
        before_cutoff = now_et.hour < self._entry_hour_end
        in_entry_window = after_open and before_cutoff

        # Detect minute boundary: when the minute rolls over, execute the best
        # signal collected from the previous minute — same logic as the simulator's
        # _scan_for_entry() which evaluates all candidates and picks the strongest.
        minute_key = (now_et.hour, now_et.minute)
        if self._scan_minute is not None and minute_key != self._scan_minute:
            self._execute_pending_entry()
        self._scan_minute = minute_key

        if (in_entry_window
                and not self._trade_manager.has_open_position()
                and symbol in self._gaprun_qualified
                and symbol not in self._time_decay_exits):
            self._collect_entry_candidate(symbol, bar, now_et)

        # ── Exit evaluation (any time, active position on this symbol) ────────
        if (self._trade_manager.has_open_position()
                and self._trade_manager.active_trade is not None
                and self._trade_manager.active_trade.symbol == symbol):
            self._try_exit(bar, now_et)

    def get_watchlist(self) -> set[str]:
        """
        Return the current set of gap-run qualified symbols.
        Used by run_trading.py to keep TradierBarPoller watchlist in sync.
        """
        return set(self._gaprun_qualified)

    def close(self):
        """Close the DB connection cleanly."""
        if self._db:
            self._db.close()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _on_new_day(self, today: date):
        """Reset daily state at the start of each new trading day."""
        logger.info(f"New trading day: {today}. Resetting daily state.")
        self._today_volume.clear()
        self._gaprun_qualified.clear()
        self._premarket_qualified.clear()
        self._premarket_scans_done.clear()
        self._last_intraday_scan_minute = None
        self._avg_vol_cache.clear()
        self._avg_vol_cache_minute = None
        self._best_signal_candidate = None
        self._scan_minute = None
        self._time_decay_exits.clear()
        for tracker in self._gap_trackers.values():
            tracker.reset()
        self._current_trade_date = today

    def _collect_entry_candidate(self, symbol: str, bar: dict, now_et: datetime):
        """
        Evaluate entry for this symbol and track it as a candidate for this minute.

        Mirrors simulator's _scan_for_entry(): we don't execute immediately — we
        collect all passing signals for the current minute and let
        _execute_pending_entry() pick the strongest one (highest confidence) when
        the minute rolls over.
        """
        bars = list(self._bar_history[symbol])
        if len(bars) < 7:  # Matches simulator's 7-bar minimum (was 5)
            return

        rel_vol      = self._get_relative_volume(symbol, now_et)
        prior_close  = self._prior_close.get(symbol)
        fundamentals = self._fundamentals.get(symbol, {})

        signal = evaluate_entry(
            symbol=symbol,
            bar_history=bars[:-1],      # history excluding current bar
            current_bar=bars[-1],
            fundamentals=fundamentals,
            prior_close=prior_close,
            current_time=bar['time'],
            relative_volume=rel_vol,
            scanner_config=self._scanner_config,
            entry_config=self._entry_config,
        )

        if signal:
            prev = self._best_signal_candidate
            prev_sig = prev['signal'] if prev is not None else None
            # M5: mirror the simulator's selection exactly (simulation_engine
            # _scan_for_entry, ~line 936): confidence primary, rel_vol tiebreak.
            # NOTE: the sim uses entry_score for SIZING (size_multiplier), NOT for
            # selection — so selecting by entry_score here would BREAK sim/live
            # parity. The real selection gap was the missing rel_vol tiebreak.
            # (The separate live SIZING gap — live ignores entry_score's multiplier
            # — is audit item H2, deferred to the live-parity wave.)
            better = (
                prev_sig is None or
                signal.pattern.confidence > prev_sig.pattern.confidence or
                (signal.pattern.confidence == prev_sig.pattern.confidence and
                 signal.pillar_data.get('rel_vol', 0) >
                 prev_sig.pillar_data.get('rel_vol', 0))
            )
            if better:
                if prev_sig is not None:
                    logger.info(
                        f"  [SIGNAL UPGRADE] {symbol} {signal.pattern.pattern_type} "
                        f"conf={signal.pattern.confidence:.2f} "
                        f"rvol={signal.pillar_data.get('rel_vol', 0):.1f} beats "
                        f"{prev['symbol']} {prev_sig.pattern.pattern_type} "
                        f"conf={prev_sig.pattern.confidence:.2f}"
                    )
                self._best_signal_candidate = {
                    'signal': signal,
                    'symbol': symbol,
                    'bar':    bar,
                }
        else:
            self._log_entry_diagnostic(symbol, bars, now_et, rel_vol, prior_close)

    def _execute_pending_entry(self):
        """
        Execute the best entry signal collected for the completed minute.

        Called at the start of each new minute, after all symbols' bars for the
        previous minute have been evaluated. Mirrors the simulator's approach of
        picking the highest-confidence signal rather than the first one.
        """
        candidate = self._best_signal_candidate
        self._best_signal_candidate = None  # always clear

        if candidate is None:
            return
        if self._trade_manager.has_open_position():
            return  # Position already open (exit signal may have closed it)

        signal = candidate['signal']
        symbol = candidate['symbol']
        bar    = candidate['bar']

        logger.info(f"ENTRY SIGNAL: {symbol} | pattern={signal.pattern.pattern_type} "
                    f"| entry=${signal.pattern.entry_price:.2f} "
                    f"| stop=${signal.pattern.stop_price:.2f} "
                    f"| T1=${signal.pattern.target1:.2f} "
                    f"| confidence={signal.pattern.confidence:.2f}")
        if self._dry_run:
            logger.info(f"  [DRY RUN] Would place order — skipping actual execution")
        else:
            self._trade_manager.execute_entry(signal, ask_price=bar['close'])

    def _log_entry_diagnostic(
        self, symbol: str, bars: list, now_et: datetime,
        rel_vol: float, prior_close: float | None,
    ):
        """
        Log which gate is blocking entry for a watchlist symbol.
        Fires once per minute per symbol to avoid flooding the log.
        """
        minute_key = (now_et.hour, now_et.minute)
        if self._diag_last_minute.get(symbol) == minute_key:
            return
        self._diag_last_minute[symbol] = minute_key

        scfg = self._scanner_config or ScannerConfig()
        ecfg = self._entry_config   or EntryConfig()
        bar  = bars[-1]
        price = float(bar['close'])

        # Gate 2: 5 Pillars
        if scfg.enable_price_range and not (scfg.min_price <= price <= scfg.max_price):
            reason = f"Gate2 PRICE ${price:.2f} outside ${scfg.min_price}-${scfg.max_price}"
            self._last_gate[symbol] = reason
            logger.info(f"  [{symbol}] {reason}")
            return
        if prior_close is None or prior_close <= 0:
            reason = "Gate2 NO PRIOR CLOSE"
            self._last_gate[symbol] = reason
            logger.info(f"  [{symbol}] {reason}")
            return
        pct = (price / prior_close - 1.0) * 100
        if scfg.enable_premarket_gain and pct < scfg.min_premarket_gain:
            reason = f"Gate2 GAIN {pct:.1f}% < {scfg.min_premarket_gain}% min"
            self._last_gate[symbol] = reason
            logger.info(f"  [{symbol}] {reason}")
            return
        if scfg.enable_relative_volume and rel_vol < scfg.min_relative_volume:
            reason = f"Gate2 REL_VOL {rel_vol:.2f}x < {scfg.min_relative_volume}x min"
            self._last_gate[symbol] = reason
            logger.info(f"  [{symbol}] {reason}")
            return

        # Gate 3: Technical indicators
        prices = [float(b['close']) for b in bars]
        ema9 = get_current_ema(prices, period=9)
        macd_data = calculate_macd(prices)
        trending = is_trending_up(bars)

        if ecfg.enable_ema9 and ema9 is not None and price < ema9:
            reason = f"Gate3 EMA9 price ${price:.2f} < ema9 ${ema9:.2f}"
            self._last_gate[symbol] = reason
            logger.info(f"  [{symbol}] {reason}")
            return
        if ecfg.enable_macd:
            if macd_data is None:
                reason = f"Gate3 MACD not calculable yet ({len(bars)} bars, need 35)"
                self._last_gate[symbol] = reason
                logger.info(f"  [{symbol}] {reason}")
                return
            # M3: report the MACD LINE (12EMA-26EMA), which is the real entry gate
            # (front side > 0). calculate_macd returns it under key 'macd'. The old
            # diagnostic logged 'histogram', so it reported a different blocking reason
            # than the gate that actually fires in entry_engine.
            if macd_data['macd'] <= 0:
                reason = f"Gate3 MACD line {macd_data['macd']:.4f} <= 0 (back side)"
                self._last_gate[symbol] = reason
                logger.info(f"  [{symbol}] {reason}")
                return
        if ecfg.enable_trend and not trending:
            reason = f"Gate3 TREND not trending up ({len(bars)} bars)"
            self._last_gate[symbol] = reason
            logger.info(f"  [{symbol}] {reason}")
            return

        # Gate 4: Pattern detection
        reason = f"Gate4 NO PATTERN (price=${price:.2f} gain={pct:+.1f}% rvol={rel_vol:.1f}x bars={len(bars)})"
        self._last_gate[symbol] = reason
        logger.info(f"  [{symbol}] {reason}")

    def get_status_snapshot(self, now_et: datetime) -> dict:
        """
        Return a JSON-serialisable snapshot of current scanner state.
        Called by run_trading.py every heartbeat to write session_status.json.
        """
        watchlist = []
        for symbol in sorted(self._gaprun_qualified):
            bars  = list(self._bar_history.get(symbol, []))
            price = float(bars[-1]['close']) if bars else 0.0
            prior = self._prior_close.get(symbol)
            gain  = ((price / prior - 1.0) * 100.0) if prior and prior > 0 else 0.0
            rel_vol = self._get_relative_volume(symbol, now_et)
            watchlist.append({
                'symbol':    symbol,
                'price':     round(price, 2),
                'gain_pct':  round(gain, 1),
                'rel_vol':   round(rel_vol, 1),
                'last_gate': self._last_gate.get(symbol, ''),
            })

        active = None
        trade = self._trade_manager.active_trade
        if trade:
            active = {
                'symbol':      trade.symbol,
                'pattern':     trade.pattern_type,
                'entry_price': round(trade.entry_price, 2),
                'shares':      trade.shares,
                'stop_loss':   round(trade.stop_loss, 2),
                'target1':     round(trade.target1, 2),
            }

        return {
            'as_of':           now_et.strftime('%H:%M:%S'),
            'session_running': True,
            'gaprun_symbols':  sorted(self._gaprun_qualified),
            'watchlist':       watchlist,
            'active_position': active,
        }

    def _try_exit(self, bar: dict, now_et: datetime):
        """
        Call evaluate_exit() for the active position.
        On signal, call LiveTradeManager.execute_exit().
        """
        trade  = self._trade_manager.active_trade
        symbol = trade.symbol
        bars   = list(self._bar_history[symbol])

        if not bars:
            return

        closes = [b['close'] for b in bars]

        # Build indicators dict expected by evaluate_exit()
        macd_result = calculate_macd(closes)
        macd_hist   = macd_result['histogram'] if macd_result else None

        # Prior bar's histogram for flip detection
        if len(closes) >= 2:
            macd_prev = calculate_macd(closes[:-1])
            macd_hist_prev = macd_prev['histogram'] if macd_prev else None
        else:
            macd_hist_prev = None

        # 5-bar average buying volume
        recent_bars = bars[-5:]
        avg_buy_vol = 0.0
        if recent_bars:
            buy_vols = [
                estimate_buy_sell_volume(b['open'], b['high'], b['low'],
                                         b['close'], b['volume'])[0]
                for b in recent_bars
            ]
            avg_buy_vol = sum(buy_vols) / len(buy_vols)

        indicators = {
            'ema9':                get_current_ema(closes),
            'macd_histogram':      macd_hist,
            'macd_histogram_prev': macd_hist_prev,
            'prior_day_high':      None,  # Not tracked yet; resistance exit disabled by default
            'avg_buy_vol_5bar':    avg_buy_vol,
        }

        signal = evaluate_exit(
            position=trade,
            current_bar=bar,
            indicators=indicators,
            current_time=bar['time'],
            config=self._exit_config,
        )

        if signal:
            logger.info(f"EXIT SIGNAL: {symbol} | reason={signal.reason} "
                        f"| qty={signal.qty} | price=${signal.price:.2f}")
            # Block re-entry for TIME_DECAY exits (matches simulator behaviour)
            if signal.reason in ('TIME_DECAY', 'EARLY_TIME_DECAY'):
                self._time_decay_exits.add(symbol)
                logger.info(f"  [{symbol}] Added to time_decay_exits — no re-entry today")
            if self._dry_run:
                logger.info(f"  [DRY RUN] Would place exit order — skipping actual execution")
            else:
                try:
                    self._trade_manager.execute_exit(signal, bar['time'])
                except Exception as exc:
                    # Log the error but NEVER let an Alpaca API rejection crash the process.
                    # The position remains open and will be retried on the next bar.
                    logger.error(f"execute_exit FAILED for {symbol} ({signal.reason}): {exc}")

    def _run_premarket_db_snapshot(self, now_et: datetime):
        """
        Premarket scan at 9:25 and 9:28 ET (also called on restart to rebuild watchlist).

        Uses Alpaca REST API directly — collect_data.py is NOT required.

        Step 1: get_snapshots_batch() → current price for all ~4,000 symbols (batched)
        Step 2: filter to Pillar 1 (price $1–$20) + Pillar 2 (up 10%+) → ~10–50 candidates
        Step 3: get_bars_since_4am() → 1-min bars for candidates only → volume + bar history
        Step 4: DB query for historical avg vol denominator (Pillar 3 — unchanged)
        Step 5: apply Pillar 3 (rel vol ≥ 5x) + Pillar 4 (float) filters
        Step 6: add qualified symbols to watchlist, seed _today_volume + _bar_history
        """
        label = f"{now_et.hour}:{now_et.minute:02d}"
        logger.info(f"=== PREMARKET SCAN ({label} ET) ===")

        # M2: use the (optimized) ScannerConfig thresholds, not module constants, so the
        # tuned Category-A pillars actually reach live. Falls back to ScannerConfig()
        # defaults (which equal the old constants except max_float: 20M vs 100M).
        scfg = self._scanner_config or ScannerConfig()

        today   = now_et.date()
        now_utc = now_et.astimezone(pytz.UTC)

        if self._data_feed is None:
            logger.warning("  No data feed configured — skipping premarket scan. "
                           "Pass data_feed= to LiveScanner to enable.")
            logger.info(f"=== END PREMARKET SCAN ({label}) ===")
            return

        # ── Step 1: quotes for all symbols ───────────────────────────────────
        logger.info(f"  Fetching quotes for {len(self._symbols):,} symbols...")
        quotes = self._data_feed.get_quotes(self._symbols)
        logger.info(f"  Got quotes for {len(quotes):,} symbols")

        if not quotes:
            logger.warning("  No quote data returned — check data feed / connection")
            return

        # ── Step 2: quick filter (price + gain%) ─────────────────────────────
        price_gain_candidates = []
        for symbol, quote in quotes.items():
            price = quote.last or quote.ask    # last price (or ask if last unavailable)

            if not (scfg.min_price <= price <= scfg.max_price):
                continue

            # Use prior close from DB (already loaded in startup_preload)
            prior_close = self._prior_close.get(symbol)
            if not prior_close or prior_close <= 0:
                continue
            pct_gain = (price / prior_close - 1.0) * 100.0
            if pct_gain < scfg.min_premarket_gain:
                continue

            price_gain_candidates.append((symbol, price, prior_close, pct_gain))

        logger.info(f"  {len(price_gain_candidates)} symbols up {scfg.min_premarket_gain}%+ "
                    f"in ${scfg.min_price}–${scfg.max_price} range")

        if not price_gain_candidates:
            logger.info("  No premarket movers found — quiet morning")
            logger.info(f"=== END PREMARKET SCAN ({label}) ===")
            return

        candidate_symbols = [s for s, *_ in price_gain_candidates]

        # ── Step 3: fetch today's bars for candidates ─────────────────────────
        logger.info(f"  Fetching 4am–{label} bars for {len(candidate_symbols)} candidates...")
        bar_results = self._data_feed.get_bars_since_4am(candidate_symbols, until_utc=now_utc)
        # Convert BarResult objects → standard bar dicts used throughout the codebase
        bars_today = {sym: [b.to_bar_dict() for b in bars]
                      for sym, bars in bar_results.items()}
        logger.info(f"  Got bars for {len(bar_results)} symbols")

        # ── Step 4: historical avg vol for rel-vol denominator ────────────────
        try:
            avg_vols = self._db.get_avg_volume_at_time_batch(
                symbols=candidate_symbols,
                as_of_date=today,
                current_hour=now_et.hour,
                current_minute=now_et.minute,
                lookback_days=30,
            )
        except Exception as e:
            logger.warning(f"  Avg volume query failed: {e} — rel_vol will be skipped")
            avg_vols = {}

        # ── Step 5: apply Pillar 3 + 4 filters ───────────────────────────────
        qualified = []
        for symbol, price, prev_close, pct_gain in price_gain_candidates:
            bars = bars_today.get(symbol, [])
            total_vol = sum(b['volume'] for b in bars)

            avg_vol = avg_vols.get(symbol, 0.0)
            rel_vol = (total_vol / avg_vol) if avg_vol > 0 else 0.0
            if rel_vol < scfg.min_relative_volume:
                continue

            fund         = self._fundamentals.get(symbol, {})
            float_shares = fund.get('float_shares')
            if float_shares and float_shares > scfg.max_float:
                continue

            qualified.append((symbol, pct_gain, rel_vol, price, float_shares))

            # ── Step 6: seed watchlist, volume, and bar history ───────────────
            if symbol not in self._gaprun_qualified:
                self._gaprun_qualified.add(symbol)
                self._premarket_qualified.add(symbol)

            # Seed cumulative volume (authoritative from API — overwrite WebSocket tally)
            if total_vol > 0:
                self._today_volume[symbol] = total_vol

            # Seed bar history (clear and repopulate — API data is more complete than
            # whatever the WebSocket accumulated since startup)
            if bars:
                self._bar_history[symbol].clear()
                for bar in bars:
                    self._bar_history[symbol].append(bar)

        # ── Log results ───────────────────────────────────────────────────────
        qualified.sort(key=lambda x: x[1], reverse=True)
        new_count = sum(1 for sym, *_ in qualified if sym in self._premarket_qualified)
        logger.info(
            f"  Passed all filters: {len(qualified)} symbols "
            f"({new_count} newly added to watchlist)"
        )

        if qualified:
            logger.info(f"  Top premarket candidates at {label}:")
            for sym, gain, rvol, price, flt in qualified[:15]:
                flt_str = f"{flt/1e6:.1f}M" if flt else "no float data"
                tag = " [already in watchlist]" if sym not in self._premarket_qualified else ""
                logger.info(
                    f"    {sym:<8}  +{gain:.1f}%  rvol={rvol:.1f}x  "
                    f"${price:.2f}  float={flt_str}{tag}"
                )
        else:
            logger.info("  No stocks passed all premarket filters")

        logger.info(f"=== END PREMARKET SCAN ({label}) ===")

    def _run_intraday_momentum_scan(self, now_et: datetime):
        """
        Intraday high-day-momo scan — adds off-watchlist surgers discovered mid-session.

        Mirrors _run_premarket_db_snapshot structure but uses qualifies_momentum()
        (the ONE shared function also called by Orchestrator._scan_for_entry in
        scanner mode), guaranteeing sim/live discovery parity.

        Flow:
          Step 1: get_quotes all ~4000 symbols (batched, ~20 HTTP calls)
          Step 2: cheap pre-filter (price + gain%) -> small candidate list
          Step 3: get_bars_since_4am for candidates -> cumulative volume + HOD
          Step 4: DB batch for historical avg vol denominator (rel_vol)
          Step 5: qualifies_momentum() gate + rank by momentum score
          Step 6: add top-N to watchlist up to INTRADAY_WATCHLIST_CAP; seed state

        Sets status_write_requested=True so run_trading.py syncs bar_poller.
        """
        label = f"{now_et.hour}:{now_et.minute:02d}"
        logger.debug(f"=== INTRADAY MOMENTUM SCAN ({label} ET) ===")

        mcfg = self._momentum_config
        today = now_et.date()
        now_utc = now_et.astimezone(pytz.UTC)

        if self._data_feed is None:
            logger.warning("  No data feed configured — skipping intraday scan.")
            logger.info(f"=== END INTRADAY SCAN ({label}) ===")
            return

        # ── Step 1: quotes for all symbols ───────────────────────────────────
        logger.debug(f"  Fetching quotes for {len(self._symbols):,} symbols...")
        quotes = self._data_feed.get_quotes(self._symbols)
        logger.debug(f"  Got {len(quotes):,} quotes")

        if not quotes:
            logger.warning("  No quote data returned — check data feed")
            return

        # ── Step 2: cheap filter (price range + gain%) ────────────────────────
        price_gain_candidates = []
        for symbol, quote in quotes.items():
            price = quote.last or quote.ask
            if not price or price <= 0:
                continue
            if not (mcfg.min_price <= price <= mcfg.max_price):
                continue
            prior_close = self._prior_close.get(symbol)
            if not prior_close or prior_close <= 0:
                continue
            gain_pct = (price / prior_close - 1.0) * 100.0
            if gain_pct < mcfg.min_intraday_gain:
                continue
            price_gain_candidates.append((symbol, price, prior_close, gain_pct))

        logger.debug(
            f"  {len(price_gain_candidates)} symbols up {mcfg.min_intraday_gain:.0f}%+"
            f" in ${mcfg.min_price}-${mcfg.max_price}"
        )

        if not price_gain_candidates:
            logger.debug(f"  No intraday movers — quiet at {label}")
            logger.debug(f"=== END INTRADAY SCAN ({label}) ===")
            return

        candidate_symbols = [s for s, *_ in price_gain_candidates]

        # ── Step 3: bars for NEW off-watchlist candidates only ────────────────
        # Already-tracked symbols have _today_volume + _bar_history from the
        # WebSocket stream — no need to re-fetch their bars every minute.
        # Only fetch bars for symbols we haven't seen yet (volume would be 0 otherwise).
        new_candidate_symbols = [
            s for s in candidate_symbols if s not in self._gaprun_qualified
        ]
        bars_today: dict[str, list] = {}
        if new_candidate_symbols:
            logger.debug(
                f"  Fetching bars for {len(new_candidate_symbols)} new candidates "
                f"({len(candidate_symbols) - len(new_candidate_symbols)} already tracked)"
            )
            try:
                bar_results = self._data_feed.get_bars_since_4am(
                    new_candidate_symbols, until_utc=now_utc
                )
                bars_today = {
                    sym: [b.to_bar_dict() for b in sym_bars]
                    for sym, sym_bars in bar_results.items()
                }
            except Exception as e:
                logger.warning(f"  get_bars_since_4am failed: {e} — new movers skipped")

        # ── Step 4: historical avg vol for rel-vol denominator ────────────────
        # Only query for symbols where we don't have volume from the WebSocket.
        symbols_needing_avg_vol = new_candidate_symbols if new_candidate_symbols else []
        avg_vols: dict[str, float] = {}
        if symbols_needing_avg_vol:
            try:
                avg_vols = self._db.get_avg_volume_at_time_batch(
                    symbols=symbols_needing_avg_vol,
                    as_of_date=today,
                    current_hour=now_et.hour,
                    current_minute=now_et.minute,
                    lookback_days=30,
                )
            except Exception as e:
                logger.warning(f"  Avg volume query failed: {e} — rel_vol will be 0 for new movers")

        # ── Step 5: qualifies_momentum gate + rank ───────────────────────────
        qualified = []
        for symbol, price, prior_close, gain_pct in price_gain_candidates:
            already_tracked = symbol in self._gaprun_qualified
            if already_tracked:
                # Use live-accumulated volume and bar history
                today_vol = self._today_volume.get(symbol, 0)
                history = list(self._bar_history.get(symbol, []))
                high_of_day = (
                    max(float(b.get('high', b['close'])) for b in history)
                    if history else price
                )
                # Rel vol from live cache (refreshed per-minute in _get_relative_volume)
                avg_vol = self._avg_vol_cache.get(symbol, 0.0)
                rel_vol = (today_vol / avg_vol) if avg_vol > 0 else 0.0
                bars_for_seed: list = []
                total_vol = today_vol
            else:
                bars = bars_today.get(symbol, [])
                total_vol = sum(b['volume'] for b in bars)
                high_of_day = (
                    max(float(b.get('high', b['close'])) for b in bars)
                    if bars else price
                )
                avg_vol = avg_vols.get(symbol, 0.0)
                rel_vol = (total_vol / avg_vol) if avg_vol > 0 else 0.0
                bars_for_seed = bars

            fund = self._fundamentals.get(symbol, {})
            float_shares = fund.get('float_shares')

            if not qualifies_momentum(
                price=price,
                prior_close=prior_close,
                high_of_day=high_of_day,
                rel_vol=rel_vol,
                float_shares=float_shares,
                et_time=now_et,
                cfg=mcfg,
            ):
                continue

            # Momentum score for ranking: rel_vol * gain (high vol + high move = best)
            momentum_score = rel_vol * gain_pct
            qualified.append((symbol, price, gain_pct, rel_vol, float_shares,
                               momentum_score, bars_for_seed, total_vol, already_tracked))

        # ── Step 6: cap to top-N; add NEW symbols to watchlist; seed state ─────
        qualified.sort(key=lambda x: x[5], reverse=True)  # sort by momentum_score desc

        slots_remaining = max(0, INTRADAY_WATCHLIST_CAP - len(self._gaprun_qualified))
        new_count = 0

        for symbol, price, gain_pct, rel_vol, flt, score, bars, total_vol, already_tracked in qualified:
            if already_tracked:
                continue  # already on watchlist — nothing to add
            if new_count >= slots_remaining:
                break

            self._gaprun_qualified.add(symbol)
            new_count += 1

            # Seed volume and bar history (same as premarket scan)
            if total_vol > 0:
                self._today_volume[symbol] = total_vol
            if bars:
                self._bar_history[symbol].clear()
                for bar in bars:
                    self._bar_history[symbol].append(bar)

            flt_str = f"{flt/1e6:.1f}M" if flt else "no float data"
            logger.info(
                f"  [INTRADAY ADD] {symbol:<8}  +{gain_pct:.1f}%  "
                f"rvol={rel_vol:.1f}x  ${price:.2f}  float={flt_str}  score={score:.0f}"
            )

        if new_count:
            logger.info(
                f"  Added {new_count} new symbols "
                f"(watchlist now {len(self._gaprun_qualified)}, cap={INTRADAY_WATCHLIST_CAP})"
            )
            # Only sync bar_poller when watchlist actually changed
            self.status_write_requested = True
        elif qualified:
            # All qualifying symbols already on watchlist (common case every minute)
            logger.debug(
                f"  {len(qualified)} qualifying symbols already tracked — no watchlist change"
            )
        else:
            logger.debug(f"  No new intraday movers at {label}")

        if slots_remaining == 0 and any(not x[8] for x in qualified):
            logger.info(
                f"  Watchlist at cap ({INTRADAY_WATCHLIST_CAP}) — "
                f"top new mover not added: {next(x[0] for x in qualified if not x[8])} "
                f"score={next(x[5] for x in qualified if not x[8]):.0f}"
            )

        logger.debug(f"=== END INTRADAY SCAN ({label}) ===")

    # ── Orchestrator wiring (de-logic: live runs the SAME engine as the sim) ─────
    # Additive for now: built lazily, used by the (pending) on_minute path in process_bar.
    # The existing per-bar _collect/_execute/_try_exit path remains until the rewire flips over.

    def _live_rel_vol_resolver(self, candidates, et_time):
        """rel_vol resolver injected into the Orchestrator (keeps DB out of the engine).
        candidates = [(symbol, bar, history), ...]. Returns {symbol: avg_vol} via the same
        batch query live already uses, cached per minute. Orchestrator computes
        rel_vol = cumulative_volume / avg_vol from this."""
        minute_key = (et_time.hour, et_time.minute)
        if self._avg_vol_cache_minute != minute_key:
            syms = [c[0] for c in candidates] or list(self._gaprun_qualified)
            try:
                self._avg_vol_cache = self._db.get_avg_volume_at_time_batch(
                    symbols=syms, as_of_date=et_time.date(),
                    current_hour=et_time.hour, current_minute=et_time.minute,
                    lookback_days=20, include_premarket_hourly=True,
                )
            except Exception as e:
                logger.warning(f"rel-vol resolver DB query failed: {e}")
                self._avg_vol_cache = {}
            self._avg_vol_cache_minute = minute_key
        return self._avg_vol_cache

    def _ensure_orchestrator(self) -> Orchestrator:
        """Build the shared Orchestrator over a LiveBroker once. Gives live the FULL strategy
        (temperature, scoring-sized entries, add-ons, portfolio risk rules) the old live path
        lacked — and which parity_check proved matches the sim. hot_symbols is the live
        gap-run watchlist (shared set, grows as the scanner qualifies symbols)."""
        if getattr(self, '_orch', None) is None:
            self._orch = Orchestrator(
                broker=LiveBroker(self._trade_manager),
                scanner_config=self._scanner_config,
                entry_config=self._entry_config,
                exit_config=self._exit_config,
                scoring_config=ScoringConfig(),
                add_on_config=AddOnConfig(),
                temp_config=MarketTemperatureConfig(),
                portfolio_manager=PortfolioManager(account_size=self._trade_manager.account_balance),
                hot_symbols=self._gaprun_qualified,       # shared ref — live watchlist
                prior_close=self._prior_close,
                fundamentals=self._fundamentals,
                prior_day_high={},                        # resistance exit off by default
                symbol_universe=None,                     # live = scanner mode (hot_symbols + gates)
                news_cache={},
                rel_vol_resolver=self._live_rel_vol_resolver,
                max_position_pct=self._trade_manager.max_position_pct,
                verbose=False,
            )
        return self._orch

    def _get_relative_volume(self, symbol: str, now_et: datetime) -> float:
        """
        Relative volume = today_volume[symbol] / avg_volume_at_this_time_historically.

        Uses get_avg_volume_at_time_batch() — the same batch DB query used by
        the simulator in simulation_engine.py. Cached once per minute across
        all gaprun-qualified symbols to minimize DB calls.
        """
        minute_key = (now_et.hour, now_et.minute)

        if self._avg_vol_cache_minute != minute_key:
            # Refresh cache for all qualified symbols this minute
            hot_symbols = list(self._gaprun_qualified) if self._gaprun_qualified else [symbol]
            try:
                self._avg_vol_cache = self._db.get_avg_volume_at_time_batch(
                    symbols=hot_symbols,
                    as_of_date=now_et.date(),
                    current_hour=now_et.hour,
                    current_minute=now_et.minute,
                    lookback_days=20,                # Matches simulator (was 30)
                    include_premarket_hourly=True,   # Matches simulator (was False)
                )
            except Exception as e:
                logger.warning(f"Relative volume DB query failed: {e}")
                self._avg_vol_cache = {}
            self._avg_vol_cache_minute = minute_key

        avg_vol   = self._avg_vol_cache.get(symbol, 0.0)
        today_vol = self._today_volume.get(symbol, 0)

        if avg_vol > 0:
            return today_vol / avg_vol
        return 0.0
