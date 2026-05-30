"""
optuna_run.py — Bayesian optimization across all A+B+C parameters.

Uses Optuna's TPE (Tree-structured Parzen Estimator) sampler, which learns
which parameter regions produce good results and explores them more heavily.

Results storage:
    - optimizer/optuna.db  — Optuna study (trials, params, values)
      → view live with: optuna-dashboard sqlite:///optimizer/optuna.db
    - optimizer/results.db — Same per-run metrics + per-trade rows as sweep.py

Install requirements:
    pip install optuna tqdm
    pip install optuna-dashboard   # optional: live trial dashboard

Usage:
    python optimizer/optuna_run.py --start 2026-02-03 --end 2026-02-18 --trials 200
    python optimizer/optuna_run.py --start 2025-01-02 --end 2025-09-30 --trials 1500

Walk-forward validation (after finding best config):
    python optimizer/optuna_run.py --start 2025-10-01 --end 2025-12-31 --validate-run optuna_00042
"""

from __future__ import annotations
import sys
import os
# Add both research/ and production/ to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))  # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))  # production/

import argparse
import json
import logging
import sqlite3
import threading
import time
import traceback as _traceback

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:
    print("ERROR: Optuna not installed. Run: pip install optuna tqdm")
    sys.exit(1)

from optimizer.run_config import RunConfig
from optimizer.results_db import init_db, write_run
from optimizer.simulate_one import run_date_range
from trading.models import ScannerConfig, EntryConfig, ExitConfig, ScoringConfig, AddOnConfig


# ── Heartbeat monitor ─────────────────────────────────────────────────────────

class _Heartbeat:
    """Background thread that prints a status line every `interval` seconds.

    Shows: elapsed time, current trial number, and the last date processed.
    Lets you distinguish "slow but working" from "truly hung".
    """
    def __init__(self, interval: int = 30):
        self.interval = interval
        self.trial_num: int = 0
        self.last_date: str = '?'
        self.days_done: int = 0
        self._t0 = time.time()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def update(self, trial_num: int, date: str, days_done: int):
        self.trial_num = trial_num
        self.last_date = date
        self.days_done = days_done

    def _run(self):
        while not self._stop.wait(self.interval):
            elapsed = int(time.time() - self._t0)
            m, s = divmod(elapsed, 60)
            print(
                f"\n  [heartbeat] {m:02d}:{s:02d} elapsed | "
                f"trial {self.trial_num} | last date: {self.last_date} "
                f"({self.days_done} days done)",
                flush=True,
            )


# ── Adaptive trend controller ─────────────────────────────────────────────────

class AdaptiveTrendController:
    """
    Manages b_enable_trend exploration across Optuna trials.

    Phase 1 (trials 0..burn_in-1): let TPE explore True and False freely.
    Phase 2 (after burn_in): analyze top 20% of completed trials, lock to winner.
    Recheck: every recheck_interval trials after locking, force one trial with
             the OPPOSITE setting to verify the conclusion is still correct.

    Usage:
        controller = AdaptiveTrendController(burn_in=50, recheck_interval=25)
        # In objective:
        trend_val = controller.get_value(trial, trial.study)
        locked_params['b_enable_trend'] = trend_val
    """

    def __init__(self, burn_in: int = 50, recheck_interval: int = 25):
        self.burn_in = burn_in
        self.recheck_interval = recheck_interval
        self._locked_to: bool | None = None
        self._lock_decided_at: int | None = None

    def get_value(self, trial: optuna.Trial, study: optuna.Study) -> bool:
        num = trial.number

        # Phase 1: burn-in — explore freely
        if num < self.burn_in:
            return trial.suggest_categorical('b_enable_trend', [True, False])

        # Phase 2: determine winner once at burn_in boundary
        if self._locked_to is None:
            self._locked_to = self._determine_winner(study)
            self._lock_decided_at = num
            print(
                f"\n  [AdaptiveTrend] Trial {num}: locking b_enable_trend={self._locked_to}"
                f" (recheck every {self.recheck_interval} trials)"
            )

        # Periodic recheck: every recheck_interval trials, try the opposite.
        # NOTE: do NOT call trial.suggest_categorical here — Optuna forbids changing
        # the value space after it has been registered. We return the bool directly;
        # the objective puts it in trial_locked and _build_config_from_trial reads
        # it from locked_params (bypassing suggest_categorical entirely).
        trials_since = num - self._lock_decided_at
        if trials_since > 0 and trials_since % self.recheck_interval == 0:
            opposite = not self._locked_to
            print(f"  [AdaptiveTrend] Trial {num}: recheck with b_enable_trend={opposite}")
            return opposite

        # Normal locked phase: return bool directly (no suggest_categorical call).
        return self._locked_to

    def _determine_winner(self, study: optuna.Study) -> bool:
        from optuna.trial import TrialState
        done = [
            t for t in study.trials
            if t.state == TrialState.COMPLETE and t.value is not None
        ]
        if len(done) < 5:
            return False  # default: False is the proven-safer choice

        top_n = max(5, len(done) // 5)  # top 20%
        top = sorted(done, key=lambda t: t.value, reverse=True)[:top_n]
        true_wins  = sum(1 for t in top if t.params.get('b_enable_trend', False))
        false_wins = len(top) - true_wins
        winner = true_wins > false_wins
        print(
            f"  [AdaptiveTrend] Top-{top_n} analysis: "
            f"trend_True={true_wins}, trend_False={false_wins} → locking to {winner}"
        )
        return winner


# ── Search space ──────────────────────────────────────────────────────────────

def _build_config_from_trial(
    trial: optuna.Trial,
    mode: str = 'full',
    disable_relative_volume: bool = False,
    locked_params: dict | None = None,
) -> RunConfig:
    """Map an Optuna trial to a RunConfig — defines the full search space.

    Modes:
      - full: gates + thresholds (default)
      - gates-only: only gate toggles, all numeric params fixed at defaults
      - single-indicator: enable exactly one gate per category (A/B/C)

    locked_params: if provided, params in this dict bypass trial.suggest_* entirely.
    Example: locked_params={'b_enable_trend': False} pins trend filter off for all trials.
    """
    _lp = locked_params or {}

    def _bool(key: str) -> bool:
        return _lp[key] if key in _lp else trial.suggest_categorical(key, [True, False])

    def _float(key: str, lo: float, hi: float, **kw) -> float:
        return _lp[key] if key in _lp else trial.suggest_float(key, lo, hi, **kw)

    def _int(key: str, lo: int, hi: int, **kw) -> int:
        return _lp[key] if key in _lp else trial.suggest_int(key, lo, hi, **kw)

    base_scanner = ScannerConfig()
    base_entry = EntryConfig()
    base_exit = ExitConfig()

    # ── Scanner (Category A) with feature toggles ─────────────────────────
    if mode == 'single-indicator':
        a_choices = [
            'price_range',
            'premarket_gain',
            'relative_volume',
            'buying_volume',
            'float_filter',
            'market_cap_filter',
            'spread_filter',
            'last_5min_volume',
            'last_1min_volume',
        ]
        if disable_relative_volume:
            a_choices = [c for c in a_choices if c != 'relative_volume']
        a_indicator = trial.suggest_categorical('a_indicator', a_choices)
        enable_price_range = a_indicator == 'price_range'
        enable_premarket_gain = a_indicator == 'premarket_gain'
        enable_relative_volume = a_indicator == 'relative_volume'
        enable_buying_volume = a_indicator == 'buying_volume'
        enable_float_filter = a_indicator == 'float_filter'
        enable_market_cap_filter = a_indicator == 'market_cap_filter'
        enable_spread_filter = a_indicator == 'spread_filter'
        enable_last_5min_volume = a_indicator == 'last_5min_volume'
        enable_last_1min_volume = a_indicator == 'last_1min_volume'
    else:
        enable_price_range = base_scanner.enable_price_range
        enable_premarket_gain = _bool('a_enable_premarket_gain')
        enable_relative_volume = False if disable_relative_volume else _bool('a_enable_relative_volume')
        enable_buying_volume = _bool('a_enable_buying_volume')
        enable_float_filter = _bool('a_enable_float_filter')
        enable_market_cap_filter = _bool('a_enable_market_cap_filter')
        enable_spread_filter = base_scanner.enable_spread_filter
        enable_last_5min_volume = base_scanner.enable_last_5min_volume
        enable_last_1min_volume = base_scanner.enable_last_1min_volume

    if mode == 'gates-only':
        min_price = base_scanner.min_price
        max_price = base_scanner.max_price
        min_premarket_gain = base_scanner.min_premarket_gain
        min_relative_volume = base_scanner.min_relative_volume
        min_buying_volume = base_scanner.min_buying_volume
        max_float = base_scanner.max_float
        max_market_cap = base_scanner.max_market_cap
    elif mode == 'single-indicator':
        min_price = trial.suggest_float('a_min_price', 1.0, 5.0) if enable_price_range else base_scanner.min_price
        max_price = trial.suggest_float('a_max_price', 15.0, 25.0) if enable_price_range else base_scanner.max_price
        min_premarket_gain = trial.suggest_float('a_min_premarket_gain', 5.0, 25.0) if enable_premarket_gain else base_scanner.min_premarket_gain
        min_relative_volume = trial.suggest_float('a_min_relative_volume', 2.0, 15.0) if enable_relative_volume else base_scanner.min_relative_volume
        min_buying_volume = trial.suggest_int('a_min_buying_volume', 10_000, 200_000, step=5_000) if enable_buying_volume else base_scanner.min_buying_volume
        max_float = trial.suggest_int('a_max_float', 5_000_000, 50_000_000, step=1_000_000) if enable_float_filter else base_scanner.max_float
        max_market_cap = trial.suggest_int('a_max_market_cap', 100_000_000, 1_000_000_000, step=50_000_000) if enable_market_cap_filter else base_scanner.max_market_cap
    else:
        min_price = _float('a_min_price', 1.0, 5.0)
        max_price = _float('a_max_price', 15.0, 25.0)
        min_premarket_gain = _float('a_min_premarket_gain', 5.0, 25.0) if enable_premarket_gain else base_scanner.min_premarket_gain
        min_relative_volume = _float('a_min_relative_volume', 2.0, 15.0) if enable_relative_volume else base_scanner.min_relative_volume
        min_buying_volume = _int('a_min_buying_volume', 10_000, 200_000, step=5_000) if enable_buying_volume else base_scanner.min_buying_volume
        max_float = _int('a_max_float', 5_000_000, 50_000_000, step=1_000_000) if enable_float_filter else base_scanner.max_float
        max_market_cap = _int('a_max_market_cap', 100_000_000, 1_000_000_000, step=50_000_000) if enable_market_cap_filter else base_scanner.max_market_cap

    scanner = ScannerConfig(
        min_price=min_price,
        max_price=max_price,
        min_premarket_gain=min_premarket_gain,
        min_relative_volume=min_relative_volume,
        min_buying_volume=min_buying_volume,
        max_float=max_float,
        max_market_cap=max_market_cap,
        enable_price_range=enable_price_range,
        enable_premarket_gain=enable_premarket_gain,
        enable_relative_volume=enable_relative_volume,
        enable_buying_volume=enable_buying_volume,
        enable_float_filter=enable_float_filter,
        enable_market_cap_filter=enable_market_cap_filter,
        enable_spread_filter=enable_spread_filter,
        enable_last_5min_volume=enable_last_5min_volume,
        enable_last_1min_volume=enable_last_1min_volume,
    )

    # ── Entry (Category B) with feature toggles ───────────────────────────
    if mode == 'single-indicator':
        b_indicator = trial.suggest_categorical(
            'b_indicator',
            [
                'bull_flag',
                'micro_pullback',
                'abcd',
                'dip_buy',
                'flat_top',
                'vwap_break_curl',
            ],
        )
        enable_ema9 = False
        enable_macd = False
        enable_trend = False
        enable_rr = False
        enable_bull_flag       = b_indicator == 'bull_flag'
        enable_micro_pullback  = b_indicator == 'micro_pullback'
        enable_abcd            = b_indicator == 'abcd'
        enable_dip_buy         = b_indicator == 'dip_buy'
        enable_flat_top        = b_indicator == 'flat_top'
        enable_vwap_break_curl = b_indicator == 'vwap_break_curl'
    else:
        enable_ema9 = _bool('b_enable_ema9')
        enable_macd = _bool('b_enable_macd')
        enable_trend = _bool('b_enable_trend')
        enable_rr = base_entry.enable_rr

        enable_bull_flag       = _bool('b_enable_bull_flag')
        enable_micro_pullback  = _bool('b_enable_micro_pullback')
        enable_abcd            = _bool('b_enable_abcd')
        enable_dip_buy         = _bool('b_enable_dip_buy')
        enable_flat_top        = _bool('b_enable_flat_top')
        enable_vwap_break_curl = _bool('b_enable_vwap_break_curl')

    if mode == 'gates-only':
        min_rr_ratio              = base_entry.min_rr_ratio
        stop_buffer               = base_entry.stop_buffer
        bull_flag_light_vol       = base_entry.bull_flag_light_vol
        bull_flag_pole_vol_min    = base_entry.bull_flag_pole_vol_min
        bull_flag_breakout_vol_min= base_entry.bull_flag_breakout_vol_min
        micro_pb_green_pct        = base_entry.micro_pb_green_pct
        micro_pb_light_vol        = base_entry.micro_pb_light_vol
        micro_pb_swing_tol        = base_entry.micro_pb_swing_tol
        abcd_min_pullback_pct     = base_entry.abcd_min_pullback_pct
        abcd_d_light_vol          = base_entry.abcd_d_light_vol
        # dip_buy_support_tolerance replaces legacy dip_buy_light_vol (GAP-A rewrite)
        dip_buy_support_tolerance = base_entry.dip_buy_support_tolerance
        flat_top_resistance_tol   = base_entry.flat_top_resistance_tol
        flat_top_vol_increase_tol = base_entry.flat_top_vol_increase_tol
        vwap_break_curl_lookback  = base_entry.vwap_break_curl_lookback
        vwap_curl_tolerance       = base_entry.vwap_curl_tolerance
        vwap_break_vol_min        = base_entry.vwap_break_vol_min
    else:
        min_rr_ratio   = _float('b_min_rr_ratio', 1.5, 4.0)
        stop_buffer    = _float('b_stop_buffer', 0.01, 0.10)
        bull_flag_light_vol        = _float('b_bull_flag_light_vol',        0.40, 0.90) if enable_bull_flag else base_entry.bull_flag_light_vol
        bull_flag_pole_vol_min     = _float('b_bull_flag_pole_vol_min',     0.50, 1.00) if enable_bull_flag else base_entry.bull_flag_pole_vol_min
        bull_flag_breakout_vol_min = _float('b_bull_flag_breakout_vol_min', 0.50, 1.00) if enable_bull_flag else base_entry.bull_flag_breakout_vol_min
        micro_pb_green_pct         = _float('b_micro_pb_green_pct',  0.40, 0.90) if enable_micro_pullback else base_entry.micro_pb_green_pct
        micro_pb_light_vol         = _float('b_micro_pb_light_vol',  0.40, 0.90) if enable_micro_pullback else base_entry.micro_pb_light_vol
        micro_pb_swing_tol         = _float('b_micro_pb_swing_tol',  0.90, 1.00) if enable_micro_pullback else base_entry.micro_pb_swing_tol
        abcd_min_pullback_pct      = _float('b_abcd_min_pullback_pct', 0.05, 0.30) if enable_abcd else base_entry.abcd_min_pullback_pct
        abcd_d_light_vol           = _float('b_abcd_d_light_vol',    0.50, 1.00) if enable_abcd else base_entry.abcd_d_light_vol
        # GAP-A: dip_buy_light_vol is no longer used by detect_dip_buy (rewritten to use support levels).
        # Tune dip_buy_support_tolerance (8% tolerance for named support level match) instead.
        dip_buy_support_tolerance  = _float('b_dip_buy_support_tolerance', 0.03, 0.15) if enable_dip_buy else base_entry.dip_buy_support_tolerance
        flat_top_resistance_tol    = _float('b_flat_top_resistance_tol',   0.01, 0.10) if enable_flat_top else base_entry.flat_top_resistance_tol
        flat_top_vol_increase_tol  = _float('b_flat_top_vol_increase_tol', 1.00, 2.00) if enable_flat_top else base_entry.flat_top_vol_increase_tol
        # GAP-K: VWAP break/curl pattern — 78.1% win rate, highest dollar EV.
        vwap_break_curl_lookback   = _int(  'b_vwap_break_curl_lookback', 3, 8)          if enable_vwap_break_curl else base_entry.vwap_break_curl_lookback
        vwap_curl_tolerance        = _float('b_vwap_curl_tolerance',       0.005, 0.030) if enable_vwap_break_curl else base_entry.vwap_curl_tolerance
        vwap_break_vol_min         = _float('b_vwap_break_vol_min',        0.80, 1.50)   if enable_vwap_break_curl else base_entry.vwap_break_vol_min

    entry = EntryConfig(
        min_rr_ratio=min_rr_ratio,
        stop_buffer=stop_buffer,
        bull_flag_light_vol=bull_flag_light_vol,
        bull_flag_pole_vol_min=bull_flag_pole_vol_min,
        bull_flag_breakout_vol_min=bull_flag_breakout_vol_min,
        micro_pb_green_pct=micro_pb_green_pct,
        micro_pb_light_vol=micro_pb_light_vol,
        micro_pb_swing_tol=micro_pb_swing_tol,
        abcd_min_pullback_pct=abcd_min_pullback_pct,
        abcd_d_light_vol=abcd_d_light_vol,
        dip_buy_support_tolerance=dip_buy_support_tolerance,
        flat_top_resistance_tol=flat_top_resistance_tol,
        flat_top_vol_increase_tol=flat_top_vol_increase_tol,
        enable_ema9=enable_ema9,
        enable_macd=enable_macd,
        enable_trend=enable_trend,
        enable_rr=enable_rr,
        enable_bull_flag=enable_bull_flag,
        enable_micro_pullback=enable_micro_pullback,
        enable_abcd=enable_abcd,
        enable_dip_buy=enable_dip_buy,
        enable_flat_top=enable_flat_top,
        enable_vwap_break_curl=enable_vwap_break_curl,
        vwap_break_curl_lookback=vwap_break_curl_lookback,
        vwap_curl_tolerance=vwap_curl_tolerance,
        vwap_break_vol_min=vwap_break_vol_min,
    )

    # In full/gates-only mode these are explored (not locked to False).
    # GAP-L fixed MACD flip to actually sell 75% — now worth exploring.
    exit_macd        = _bool('c_enable_macd_flip_exit') if mode != 'single-indicator' else base_exit.enable_macd_flip_exit
    exit_resistance  = base_exit.enable_resistance_exit
    exit_volume_dry  = base_exit.enable_volume_dry_up_exit

    if mode == 'single-indicator':
        # Category C: choose exactly ONE profit-exit strategy.
        # Hard stop (STOP_HIT) is always active — not a tunable choice.
        # Selling pressure acts as a soft early-exit and is always tuned.
        c_profit = trial.suggest_categorical(
            'c_profit',
            ['fixed_target', 'trailing_stop', 'ema_cross', 'macd_flip', 'time_decay'],
        )
        exit_macd     = c_profit == 'macd_flip'
        exit_resistance = False   # excluded — only tunable in full mode
        exit_volume_dry = False   # excluded — only tunable in full mode

        # Profit-exit numeric params (conditional on c_profit)
        trailing_stop_distance = (
            trial.suggest_float('c_trailing_stop_distance', 0.05, 0.50)
            if c_profit == 'trailing_stop' else 0.0
        )
        target1_ratio   = trial.suggest_float('c_target1_ratio',   1.0, 3.0)
        target1_qty_pct = trial.suggest_float('c_target1_qty_pct', 0.20, 0.80)
        # T2 only meaningful for fixed_target or trailing_stop
        target2_ratio   = (
            trial.suggest_float('c_target2_ratio',   2.0, 5.0)
            if c_profit in ('fixed_target', 'trailing_stop') else base_exit.target2_ratio
        )
        target2_qty_pct = (
            trial.suggest_float('c_target2_qty_pct', 0.10, 0.50)
            if c_profit in ('fixed_target', 'trailing_stop') else base_exit.target2_qty_pct
        )
        macd_flip_qty_pct = (
            trial.suggest_float('c_macd_flip_qty_pct', 0.25, 0.75)
            if c_profit == 'macd_flip' else base_exit.macd_flip_qty_pct
        )
        time_decay_hour = trial.suggest_int('c_time_decay_hour', 10, 13)
        selling_pressure_ratio   = trial.suggest_float('c_selling_pressure_ratio',   1.20, 4.00)
        selling_pressure_qty_pct = trial.suggest_float('c_selling_pressure_qty_pct', 0.20, 1.00)

        exit_ = ExitConfig(
            target1_ratio            = target1_ratio,
            target2_ratio            = target2_ratio,
            target1_qty_pct          = target1_qty_pct,
            target2_qty_pct          = target2_qty_pct,
            trailing_stop_distance   = trailing_stop_distance,
            time_decay_hour          = time_decay_hour,
            early_time_decay_hour    = 0,
            selling_pressure_ratio   = selling_pressure_ratio,
            selling_pressure_qty_pct = selling_pressure_qty_pct,
            enable_macd_flip_exit    = exit_macd,
            macd_flip_qty_pct        = macd_flip_qty_pct,
            enable_resistance_exit   = False,
            enable_volume_dry_up_exit= False,
        )
    else:
        exit_ = ExitConfig(
            target1_ratio            = _float('c_target1_ratio',            1.0, 3.0),
            target2_ratio            = _float('c_target2_ratio',            2.0, 5.0),
            target1_qty_pct          = _float('c_target1_qty_pct',          0.20, 0.80),
            target2_qty_pct          = _float('c_target2_qty_pct',          0.10, 0.50),
            trailing_stop_distance   = _float('c_trailing_stop_distance',   0.00, 0.50),
            time_decay_hour          = _int(  'c_time_decay_hour',          10,   13),
            early_time_decay_hour    = 0,    # Phase 4 — disabled for now
            selling_pressure_ratio   = _float('c_selling_pressure_ratio',   1.20, 4.00),
            selling_pressure_qty_pct = _float('c_selling_pressure_qty_pct', 0.20, 1.00),
            enable_macd_flip_exit    = exit_macd,
            # GAP-L: MACD flip now sells macd_flip_qty_pct (default 75%) immediately.
            # Tune when enabled; use corpus-derived default (0.75) when disabled.
            macd_flip_qty_pct        = _float('c_macd_flip_qty_pct', 0.40, 1.00) if exit_macd else base_exit.macd_flip_qty_pct,
            enable_resistance_exit   = exit_resistance,
            enable_volume_dry_up_exit= exit_volume_dry,
        )

    # ── Scoring (Category F) — composite entry score weights ─────────────────
    # Only the high-leverage params are tuned; pattern weights are fixed at corpus-
    # derived defaults (tuning 30+ dims needs far more trials than A/B/C alone).
    #
    # Thresholds: minimum score to enter, per temperature.
    # Size multipliers: base position size, per temperature.
    # Component weights: the three largest scoring contributors.
    base_scoring = ScoringConfig()

    if mode == 'gates-only':
        # Gates-only mode: keep scoring at defaults — only gate toggles matter.
        scoring = base_scoring
    else:
        scoring = ScoringConfig(
            # ── Temperature score thresholds (min score to enter) ─────────────
            threshold_hot    = _int('f_threshold_hot',    20, 55),
            threshold_neutral = _int('f_threshold_neutral', 40, 65),
            threshold_cold   = _int('f_threshold_cold',   55, 80),
            threshold_chop   = _int('f_threshold_chop',   65, 90),

            # ── Base size multipliers per temperature ─────────────────────────
            size_hot     = _float('f_size_hot',     0.60, 1.50),
            size_neutral = _float('f_size_neutral', 0.40, 1.20),
            size_cold    = _float('f_size_cold',    0.20, 0.80),
            size_chop    = _float('f_size_chop',    0.10, 0.50),
            size_bonus_per_10pts = _float('f_size_bonus_per_10pts', 0.00, 0.25),

            # ── Relative volume score points ──────────────────────────────────
            relvol_pts_100x = _int('f_relvol_pts_100x', 14, 20),
            relvol_pts_25x  = _int('f_relvol_pts_25x',  10, 18),
            relvol_pts_10x  = _int('f_relvol_pts_10x',   6, 14),
            relvol_pts_5x   = _int('f_relvol_pts_5x',    2,  8),

            # ── News tier score points ────────────────────────────────────────
            news_tier1_pts   = _int('f_news_tier1_pts',   12, 20),
            news_tier2_pts   = _int('f_news_tier2_pts',    8, 16),
            news_none_pts    = _int('f_news_none_pts',     0,  4),
            news_unknown_pts = _int('f_news_unknown_pts',  2,  8),

            # ── Fixed at corpus-derived defaults (not yet tuned) ─────────────
            # Pattern weights, float pts, gap pts, MACD pts, time-of-day pts
            # are left at ScoringConfig defaults. Add to search space after
            # the threshold/size/relvol/news tuning converges.
        )

    # ── Add-on / Pyramid (Category E) ────────────────────────────────────────
    # 52.3% of all Ross Cameron trades used add-ons (2,593/4,959).
    # Source: concept_add_on_mechanics.md.
    # Tune gate toggles and sizing tiers. Halt-resume add is excluded (no halt feed).
    base_add_on = AddOnConfig()

    if mode == 'gates-only':
        add_on = base_add_on
    else:
        add_on = AddOnConfig(
            # Gate toggles — which trigger types are active
            enable_new_high        = _bool('e_enable_new_high'),         # 42.8% of triggers
            enable_micro_pb_add    = _bool('e_enable_micro_pb_add'),     # 26.4% of triggers
            enable_vwap_retest     = _bool('e_enable_vwap_retest'),      # 6.5% of triggers
            enable_whole_dollar_add= _bool('e_enable_whole_dollar_add'), # 2.4% of triggers

            # Max adds per trade (corpus: 87% = 1 add, 11% = 2 adds, 2% = 3+)
            max_add_ons            = _int('e_max_add_ons', 1, 4),

            # Morning window cutoff (corpus: <1% of adds after 10:30 ET)
            time_cutoff_minute     = _int('e_time_cutoff_minute', 15, 30),

            # Add sizing tiers (fraction of initial_shares per add)
            add_pct_tier1          = _float('e_add_pct_tier1', 0.10, 0.50),
            add_pct_tier2          = _float('e_add_pct_tier2', 0.10, 0.40),

            # HOT market add size multiplier (concept: 25-50% more in hot market)
            hot_market_multiplier  = _float('e_hot_market_multiplier', 1.00, 1.75),
        )

    return RunConfig(scanner=scanner, entry=entry, exit_=exit_, add_on=add_on, scoring=scoring)


# ── Seed helper ───────────────────────────────────────────────────────────────

def _enqueue_seed_trial(study: optuna.Study, trial_id: str, results_db_path: str) -> None:
    """Load params from results.db and enqueue as the first Optuna trial.

    TPE will evaluate this trial first, then use its result to bias sampling
    toward the proven parameter region.
    """
    # Normalise: '269' -> 'optuna_00269', or pass a full run_id directly
    try:
        run_id = f'optuna_{int(trial_id.strip()):05d}'
    except ValueError:
        run_id = trial_id.strip()

    conn = sqlite3.connect(results_db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT params_json FROM runs WHERE run_id = ?', (run_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        print(f'WARNING: seed trial {run_id} not found in {results_db_path} — skipping seed')
        return

    params = json.loads(row[0])
    study.enqueue_trial(params)
    print(f'  Seeded study with params from {run_id}')


# ── Objective function ─────────────────────────────────────────────────────────

def _make_objective(
    start_date: str,
    end_date: str,
    results_conn,
    mode: str,
    debug: bool,
    cache_data: bool,
    disable_relative_volume: bool,
    cache_dir: str | None,
    symbol_universe: list | dict | None = None,
    locked_params: dict | None = None,
    adaptive_trend_controller: AdaptiveTrendController | None = None,
):
    """Return a closure that Optuna calls for each trial."""

    def objective(trial: optuna.Trial) -> float:
        # Build per-trial locked params (don't mutate the shared dict)
        trial_locked = dict(locked_params or {})
        if adaptive_trend_controller is not None:
            trial_locked['b_enable_trend'] = adaptive_trend_controller.get_value(
                trial, trial.study
            )
        cfg = _build_config_from_trial(trial, mode=mode, disable_relative_volume=disable_relative_volume, locked_params=trial_locked)

        _hb = objective._heartbeat  # attached externally by run_optuna
        _days_done = [0]

        def _day_tick(date: str):
            _days_done[0] += 1
            if _hb is not None:
                _hb.update(trial.number, date, _days_done[0])

        t_start = time.time()
        is_first_trial = (trial.number == 0)
        try:
            result = run_date_range(
                cfg,
                start_date,
                end_date,
                verbose=False,
                debug=debug,
                cache_data=cache_data,
                cache_dir=cache_dir,
                symbol_universe=symbol_universe,
                on_day_complete=_day_tick,
                print_dates=is_first_trial,  # only trial 0: full per-day progress
                # Abort dead configs fast: if 0 trades after 20 data-days, skip rest.
                # Cuts ~80% of dead-trial time from ~130s → ~14s per pruned trial.
                early_abort_days=20,
            )
        except Exception as e:
            elapsed = time.time() - t_start
            print(f"\n  Trial {trial.number} ERROR after {elapsed:.1f}s: {e}", flush=True)
            _traceback.print_exc()
            return -999.0

        if result['total_trades'] == 0:
            raise optuna.TrialPruned()

        trades = result.pop('trades')
        run_id = f"optuna_{trial.number:05d}"
        write_run(results_conn, run_id, start_date, end_date,
                  result, cfg.to_flat_dict(), trades)

        return result['objective']

    objective._heartbeat = None  # type: ignore[attr-defined]  # set externally after creation
    return objective


# ── Main ──────────────────────────────────────────────────────────────────────

def run_optuna(
    start_date: str,
    end_date: str,
    n_trials: int = 500,
    results_db_path: str | None = None,
    optuna_db_url: str | None = None,
    study_name: str | None = None,
    mode: str = 'full',
    debug: bool = False,
    log_file: str | None = None,
    cache_data: bool = False,
    disable_relative_volume: bool = False,
    cache_dir: str | None = None,
    symbols_file: str | None = None,
    seed_trial: str | None = None,
    seed_db_path: str | None = None,
    locked_params: dict | None = None,
    adaptive_trend: bool = False,
    trend_burnin: int = 50,
    trend_recheck: int = 25,
) -> None:
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        file_handler = logging.FileHandler(log_file, mode='a')
        file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        root_logger.addHandler(file_handler)
    results_conn = init_db(results_db_path)

    # ── Load symbol universe ──────────────────────────────────────────────
    symbol_universe: list | dict | None = None
    if symbols_file:
        import csv
        with open(symbols_file) as f:
            reader = csv.reader(f)
            header = next(reader)
            if header[0].strip().lower() == 'date':
                # DATE-SPECIFIC FORMAT: build {date_str: [symbols]} dict
                universe_dict: dict[str, list] = {}
                for row in reader:
                    if len(row) >= 2:
                        universe_dict.setdefault(row[0].strip(), []).append(row[1].strip())
                symbol_universe = universe_dict
                total = sum(len(v) for v in universe_dict.values())
                print(f"Symbol universe : {total} date-symbol pairs across "
                      f"{len(universe_dict)} dates (date-specific mode)")
            else:
                # LEGACY FLAT FORMAT: single column list (backwards compatible)
                symbol_universe = [row[0].strip() for row in reader if row]
                print(f"Symbol universe : {len(symbol_universe)} symbols from {symbols_file}")

    # When date-specific, category-A scanner gates are irrelevant (universe mode
    # bypasses them). Lock them off so Optuna focuses on B/C params only.
    date_specific_mode = isinstance(symbol_universe, dict)
    if date_specific_mode:
        locked_params = dict(locked_params or {})
        for gate in ('a_enable_premarket_gain', 'a_enable_relative_volume',
                     'a_enable_buying_volume', 'a_enable_float_filter',
                     'a_enable_market_cap_filter'):
            locked_params.setdefault(gate, False)
        print("Date-specific mode: category A scanner gates auto-locked off (pre-screen trusted)")

    adaptive_trend_controller = (
        AdaptiveTrendController(burn_in=trend_burnin, recheck_interval=trend_recheck)
        if adaptive_trend else None
    )

    storage = optuna_db_url or 'sqlite:///optimizer/optuna.db'
    sname   = study_name or f'trading_{start_date}_{end_date}'
    if log_file:
        logging.info("=== Optuna run start: %s | mode=%s | cache=%s | debug=%s ===", sname, mode, cache_data, debug)

    study = optuna.create_study(
        study_name=sname,
        direction='maximize',
        storage=storage,
        load_if_exists=True,
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(n_warmup_steps=0),
    )

    # Enqueue seed trial before any TPE sampling
    # seed_db_path defaults to the standard results.db (the Jan 2026 500-trial run)
    # so that --seed-trial 269 works even when --db points to a separate output DB
    if seed_trial:
        db_for_seed = seed_db_path or results_db_path or 'optimizer/results.db'
        _enqueue_seed_trial(study, seed_trial, db_for_seed)

    n_existing = len(study.trials)
    n_remaining = max(0, n_trials - n_existing)

    print(f"\nOptuna optimization: {sname}")
    print(f"Date range : {start_date} -> {end_date}")
    print(f"Trials     : {n_trials} total ({n_existing} already done, {n_remaining} to run)")
    print(f"Storage    : {storage}")
    print(f"Mode       : {mode}")
    if seed_trial:
        print(f"Seed trial : {seed_trial}")
    if locked_params:
        print(f"Locked     : {locked_params}")
    if adaptive_trend_controller:
        print(f"Adaptive trend : burn_in={trend_burnin}, recheck={trend_recheck}")
    print(f"Dashboard  : pip install optuna-dashboard && optuna-dashboard {storage}")
    print()

    if n_remaining == 0:
        print("All trials already complete.")
    else:
        heartbeat = _Heartbeat(interval=30)
        obj_fn = _make_objective(
            start_date, end_date, results_conn, mode, debug, cache_data,
            disable_relative_volume, cache_dir, symbol_universe, locked_params,
            adaptive_trend_controller,
        )
        obj_fn._heartbeat = heartbeat  # type: ignore[attr-defined]
        heartbeat.start()
        try:
            study.optimize(
                obj_fn,
                n_trials=n_remaining,
                show_progress_bar=True,
            )
        finally:
            heartbeat.stop()

    best = study.best_trial
    print(f"\n{'='*60}")
    print(f"Best trial : #{best.number}  objective = ${best.value:,.0f}")
    print(f"Best params:")
    for k, v in sorted(best.params.items()):
        print(f"  {k:<40} {v}")
    print(f"{'='*60}\n")

    results_conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bayesian optimization with Optuna')
    parser.add_argument('--start',       required=True,  help='Start date YYYY-MM-DD')
    parser.add_argument('--end',         required=True,  help='End date   YYYY-MM-DD')
    parser.add_argument('--trials',      type=int, default=500, help='Total trials to run (default 500)')
    parser.add_argument('--db',          default=None,   help='Results SQLite path (default: optimizer/results.db)')
    parser.add_argument('--optuna-db',   default=None,   help='Optuna storage URL (default: sqlite:///optimizer/optuna.db)')
    parser.add_argument('--study-name',  default=None,   help='Optuna study name (default: trading_<start>_<end>)')
    parser.add_argument('--mode',        default='full', choices=['full', 'gates-only', 'single-indicator'],
                        help='Search mode: full, gates-only (toggles only), or single-indicator (one gate per A/B/C)')
    parser.add_argument('--debug',       action='store_true', help='Enable verbose simulation debug logging')
    parser.add_argument('--log-file',    default='optimizer/logs/optuna_debug.log', help='Log file path')
    parser.add_argument('--cache-data',  action='store_true', help='Cache market data in memory per date')
    parser.add_argument('--cache-dir',   default='data/cache', help='Directory for persisted cache files')
    parser.add_argument('--disable-relative-volume', action='store_true', help='Disable relative volume gate (speed)')
    parser.add_argument('--symbols-file', default=None,
                        help='CSV file with symbol universe (col 0 = symbol, has header row). '
                             'Bypasses all scanner pre-screens when set.')
    parser.add_argument('--seed-trial', default=None, metavar='TRIAL_ID',
                        help='Warm-start: enqueue params from an existing results.db trial as '
                             'the first trial (e.g. 269 or optuna_00269). TPE then biases '
                             'sampling toward that proven region.')
    parser.add_argument('--seed-db', default=None, metavar='PATH',
                        help='SQLite results.db to load the seed trial from (default: same as --db, '
                             'or optimizer/results.db if --db not set). Use this when --db points '
                             'to a new output file but the seed trial is in a different DB.')
    parser.add_argument('--lock-params', nargs='*', metavar='KEY=VALUE', default=[],
                        help='Fix params to exact values for all trials, bypassing suggest_*. '
                             'Example: --lock-params b_enable_trend=False c_time_decay_hour=11')
    parser.add_argument('--adaptive-trend', action='store_true',
                        help='Explore b_enable_trend freely for --trend-burnin trials, '
                             'then lock to the winner (top-20%% analysis). Rechecks every '
                             '--trend-recheck trials.')
    parser.add_argument('--trend-burnin', type=int, default=50,
                        help='Trials before locking b_enable_trend (default: 50)')
    parser.add_argument('--trend-recheck', type=int, default=25,
                        help='Re-test opposite trend setting every N trials after lock (default: 25)')
    args = parser.parse_args()

    # Parse --lock-params KEY=VALUE pairs into a typed dict
    locked: dict = {}
    for kv in args.lock_params or []:
        if '=' not in kv:
            print(f'WARNING: --lock-params entry "{kv}" ignored (no = sign)')
            continue
        k, v = kv.split('=', 1)
        if v in ('True', 'true'):
            v = True
        elif v in ('False', 'false'):
            v = False
        else:
            try:
                v = int(v)
            except ValueError:
                try:
                    v = float(v)
                except ValueError:
                    pass
        locked[k] = v

    run_optuna(
        start_date=args.start,
        end_date=args.end,
        n_trials=args.trials,
        results_db_path=args.db,
        optuna_db_url=args.optuna_db,
        study_name=args.study_name,
        mode=args.mode,
        debug=args.debug,
        log_file=args.log_file,
        cache_data=args.cache_data,
        disable_relative_volume=args.disable_relative_volume,
        cache_dir=args.cache_dir if args.cache_data else None,
        symbols_file=args.symbols_file,
        seed_trial=args.seed_trial,
        seed_db_path=args.seed_db,
        locked_params=locked if locked else None,
        adaptive_trend=args.adaptive_trend,
        trend_burnin=args.trend_burnin,
        trend_recheck=args.trend_recheck,
    )
