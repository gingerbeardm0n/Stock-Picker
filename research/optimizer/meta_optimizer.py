"""
meta_optimizer.py — ML-guided meta-optimization loop on top of Optuna.

Each round:
  1. Run Optuna (N trials) with the current parameter search space
  2. Use Optuna's PedAnova feature importance to rank which params drive P&L
  3. Lock low-importance bool toggles to their majority value in top trials
  4. Narrow numeric ranges around top-quartile trial values
  5. Widen ranges that hit a boundary
  6. Repeat for R rounds, converging on the best config

State is persisted to meta_state.json after each round so runs are resumable.
Results are written to meta_results.db and meta_optuna.db (separate from
the existing results.db / optuna.db to avoid polluting those).

Usage:
    python optimizer/meta_optimizer.py \\
        --start 2026-02-03 --end 2026-02-18 \\
        --rounds 5 --trials-per-round 50

    # Resume after interruption:
    python optimizer/meta_optimizer.py \\
        --start 2026-02-03 --end 2026-02-18 \\
        --rounds 5 --trials-per-round 50 --resume
"""

from __future__ import annotations
import sys
import os
# Add both research/ and production/ to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))  # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))  # production/

import argparse
import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import numpy as np

try:
    import optuna
    from optuna.samplers import TPESampler
    from optuna.trial import TrialState
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:
    print("ERROR: Optuna not installed. Run: pip install optuna")
    sys.exit(1)

try:
    from optuna.importance import PedAnovaImportanceEvaluator
    _HAS_PEDANOVA = True
except ImportError:
    _HAS_PEDANOVA = False

from optimizer.run_config import RunConfig
from optimizer.results_db import init_db, write_run
from optimizer.simulate_one import run_date_range
from trading.models import ScannerConfig, EntryConfig, ExitConfig


# ── Parameter registry ────────────────────────────────────────────────────────
# Mirrors the exact search space in optuna_run.py:_build_config_from_trial()
# Only params that Optuna actually suggests (not hardcoded) belong here.

PARAM_REGISTRY: dict[str, dict[str, Any]] = {
    # ── Category A: Scanner / 5-pillar (bool toggles) ─────────────────────
    'a_enable_premarket_gain':    {'type': 'bool'},
    'a_enable_relative_volume':   {'type': 'bool'},
    'a_enable_buying_volume':     {'type': 'bool'},
    'a_enable_float_filter':      {'type': 'bool'},
    'a_enable_market_cap_filter': {'type': 'bool'},

    # ── Category A: Scanner (numeric) ──────────────────────────────────────
    'a_min_price':           {'type': 'float', 'low': 1.0,         'high': 5.0},
    'a_max_price':           {'type': 'float', 'low': 15.0,        'high': 25.0},
    'a_min_premarket_gain':  {'type': 'float', 'low': 5.0,         'high': 25.0},
    'a_min_relative_volume': {'type': 'float', 'low': 2.0,         'high': 15.0},
    'a_min_buying_volume':   {'type': 'int',   'low': 10_000,      'high': 200_000,     'step': 5_000},
    'a_max_float':           {'type': 'int',   'low': 5_000_000,   'high': 50_000_000,  'step': 1_000_000},
    'a_max_market_cap':      {'type': 'int',   'low': 100_000_000, 'high': 1_000_000_000, 'step': 50_000_000},

    # ── Category B: Entry / pattern detection (bool toggles) ───────────────
    'b_enable_ema9':          {'type': 'bool'},
    'b_enable_macd':          {'type': 'bool'},
    'b_enable_trend':         {'type': 'bool'},
    'b_enable_bull_flag':     {'type': 'bool'},
    'b_enable_micro_pullback':{'type': 'bool'},
    'b_enable_abcd':          {'type': 'bool'},
    'b_enable_dip_buy':       {'type': 'bool'},
    'b_enable_flat_top':      {'type': 'bool'},

    # ── Category B: Entry (numeric, always suggested) ──────────────────────
    'b_min_rr_ratio':  {'type': 'float', 'low': 1.5,  'high': 4.0},
    'b_stop_buffer':   {'type': 'float', 'low': 0.01, 'high': 0.10},

    # ── Category B: Pattern-specific (conditional on their enable toggle) ──
    'b_bull_flag_light_vol':        {'type': 'float', 'low': 0.40, 'high': 0.90, 'conditional_on': 'b_enable_bull_flag'},
    'b_bull_flag_pole_vol_min':     {'type': 'float', 'low': 0.50, 'high': 1.00, 'conditional_on': 'b_enable_bull_flag'},
    'b_bull_flag_breakout_vol_min': {'type': 'float', 'low': 0.50, 'high': 1.00, 'conditional_on': 'b_enable_bull_flag'},
    'b_micro_pb_green_pct':         {'type': 'float', 'low': 0.40, 'high': 0.90, 'conditional_on': 'b_enable_micro_pullback'},
    'b_micro_pb_light_vol':         {'type': 'float', 'low': 0.40, 'high': 0.90, 'conditional_on': 'b_enable_micro_pullback'},
    'b_micro_pb_swing_tol':         {'type': 'float', 'low': 0.90, 'high': 1.00, 'conditional_on': 'b_enable_micro_pullback'},
    'b_abcd_min_pullback_pct':      {'type': 'float', 'low': 0.05, 'high': 0.30, 'conditional_on': 'b_enable_abcd'},
    'b_abcd_d_light_vol':           {'type': 'float', 'low': 0.50, 'high': 1.00, 'conditional_on': 'b_enable_abcd'},
    'b_dip_buy_light_vol':          {'type': 'float', 'low': 0.40, 'high': 0.90, 'conditional_on': 'b_enable_dip_buy'},
    'b_flat_top_resistance_tol':    {'type': 'float', 'low': 0.01, 'high': 0.10, 'conditional_on': 'b_enable_flat_top'},
    'b_flat_top_vol_increase_tol':  {'type': 'float', 'low': 1.00, 'high': 2.00, 'conditional_on': 'b_enable_flat_top'},

    # ── Category C: Exit (always suggested, not conditional) ───────────────
    'c_target1_ratio':           {'type': 'float', 'low': 1.0,  'high': 3.0},
    'c_target2_ratio':           {'type': 'float', 'low': 2.0,  'high': 5.0},
    'c_target1_qty_pct':         {'type': 'float', 'low': 0.20, 'high': 0.80},
    'c_target2_qty_pct':         {'type': 'float', 'low': 0.10, 'high': 0.50},
    'c_trailing_stop_distance':  {'type': 'float', 'low': 0.00, 'high': 0.50},
    'c_time_decay_hour':         {'type': 'int',   'low': 10,   'high': 13},
    'c_selling_pressure_ratio':  {'type': 'float', 'low': 1.20, 'high': 4.00},
    'c_selling_pressure_qty_pct':{'type': 'float', 'low': 0.20, 'high': 1.00},
}

# Hardcoded (never tuned): enable_price_range, enable_spread_filter,
# enable_last_5min_volume, enable_last_1min_volume, enable_rr,
# c_enable_macd_flip_exit, c_enable_resistance_exit, c_enable_volume_dry_up_exit


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ParamSpec:
    """Tracks the evolving search-space state for one parameter."""
    name: str
    param_type: str          # 'bool' | 'float' | 'int'

    # Bool params
    locked: bool = False
    locked_value: bool = False

    # Numeric params (store as float internally, cast to int at suggest time)
    original_low: float = 0.0
    original_high: float = 1.0
    current_low: float = 0.0
    current_high: float = 1.0
    step: int = 0            # 0 = no step (float); >0 = int step

    # History
    importance_history: list = field(default_factory=list)
    boundary_hits: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ParamSpec:
        return cls(**d)


@dataclass
class MetaParamState:
    """Full persistent state of the meta-optimizer across all rounds."""
    round_num: int = 0
    best_objective: float = -999.0
    best_round: int = -1
    best_params: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)   # str -> ParamSpec (serialized as dict)
    round_history: list = field(default_factory=list)

    def get_spec(self, name: str) -> ParamSpec:
        d = self.params[name]
        if isinstance(d, ParamSpec):
            return d
        return ParamSpec.from_dict(d)

    def set_spec(self, name: str, spec: ParamSpec) -> None:
        self.params[name] = spec.to_dict()

    def to_dict(self) -> dict:
        return {
            'round_num':      self.round_num,
            'best_objective': self.best_objective,
            'best_round':     self.best_round,
            'best_params':    self.best_params,
            'params':         self.params,
            'round_history':  self.round_history,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MetaParamState:
        return cls(
            round_num=d['round_num'],
            best_objective=d['best_objective'],
            best_round=d.get('best_round', -1),
            best_params=d['best_params'],
            params=d['params'],
            round_history=d['round_history'],
        )


# ── State I/O ─────────────────────────────────────────────────────────────────

def build_initial_state() -> MetaParamState:
    """Build a fresh MetaParamState from PARAM_REGISTRY defaults."""
    state = MetaParamState()
    for name, spec_def in PARAM_REGISTRY.items():
        ptype = spec_def['type']
        if ptype == 'bool':
            spec = ParamSpec(name=name, param_type='bool')
        else:
            low  = float(spec_def['low'])
            high = float(spec_def['high'])
            step = int(spec_def.get('step', 0))
            spec = ParamSpec(
                name=name, param_type=ptype,
                original_low=low, original_high=high,
                current_low=low, current_high=high,
                step=step,
            )
        state.params[name] = spec.to_dict()
    return state


def save_state(state: MetaParamState, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(state.to_dict(), f, indent=2)


def load_state(path: str) -> MetaParamState:
    with open(path) as f:
        return MetaParamState.from_dict(json.load(f))


# ── Trial builder ─────────────────────────────────────────────────────────────

def _build_config_from_trial_meta(
    trial: optuna.Trial,
    state: MetaParamState,
    disable_relative_volume: bool = False,
    mode: str = 'full',
) -> RunConfig:
    """
    Like optuna_run._build_config_from_trial() but respects MetaParamState.

    Modes:
      - full: all A/B/C params driven by state (locked bools, narrowed ranges)
      - single-indicator: b_indicator categorical + c_profit categorical;
        Category A entirely skipped (symbol_universe trusted); 9-14 params total

    - Locked bool: use locked_value directly (no trial.suggest_*)
    - Free bool: trial.suggest_categorical(name, [True, False])
    - Numeric: trial.suggest_float/int with state's current_[low|high]
    - Conditional numeric params still check their enable toggle first
    """
    base_scanner = ScannerConfig()
    base_entry   = EntryConfig()
    base_exit    = ExitConfig()

    def get_bool(name: str) -> bool:
        spec = state.get_spec(name)
        if spec.locked:
            return spec.locked_value
        return bool(trial.suggest_categorical(name, [True, False]))

    def get_float(name: str) -> float:
        spec = state.get_spec(name)
        lo, hi = spec.current_low, spec.current_high
        if lo >= hi:
            lo = spec.original_low
            hi = spec.original_high
        return trial.suggest_float(name, lo, hi)

    def get_int(name: str) -> int:
        spec = state.get_spec(name)
        lo, hi = int(spec.current_low), int(spec.current_high)
        step = spec.step if spec.step > 0 else 1
        if lo >= hi:
            lo = int(spec.original_low)
            hi = int(spec.original_high)
        return trial.suggest_int(name, lo, hi, step=step)

    # ── single-indicator mode ─────────────────────────────────────────────
    if mode == 'single-indicator':
        # Category A: all gates off — symbol_universe is already pre-screened
        scanner = ScannerConfig(
            enable_price_range=False,
            enable_premarket_gain=False,
            enable_relative_volume=False,
            enable_buying_volume=False,
            enable_float_filter=False,
            enable_market_cap_filter=False,
            enable_spread_filter=False,
            enable_last_5min_volume=False,
            enable_last_1min_volume=False,
        )

        # Category B: exactly one entry pattern
        b_indicator = trial.suggest_categorical(
            'b_indicator',
            ['bull_flag', 'micro_pullback', 'abcd', 'dip_buy', 'flat_top'],
        )
        enable_bull_flag      = b_indicator == 'bull_flag'
        enable_micro_pullback = b_indicator == 'micro_pullback'
        enable_abcd           = b_indicator == 'abcd'
        enable_dip_buy        = b_indicator == 'dip_buy'
        enable_flat_top       = b_indicator == 'flat_top'

        min_rr_ratio = trial.suggest_float('b_min_rr_ratio', 1.5, 4.0)
        stop_buffer  = trial.suggest_float('b_stop_buffer',  0.01, 0.10)

        bull_flag_light_vol        = trial.suggest_float('b_bull_flag_light_vol',        0.40, 0.90) if enable_bull_flag      else base_entry.bull_flag_light_vol
        bull_flag_pole_vol_min     = trial.suggest_float('b_bull_flag_pole_vol_min',     0.50, 1.00) if enable_bull_flag      else base_entry.bull_flag_pole_vol_min
        bull_flag_breakout_vol_min = trial.suggest_float('b_bull_flag_breakout_vol_min', 0.50, 1.00) if enable_bull_flag      else base_entry.bull_flag_breakout_vol_min
        micro_pb_green_pct         = trial.suggest_float('b_micro_pb_green_pct',         0.40, 0.90) if enable_micro_pullback else base_entry.micro_pb_green_pct
        micro_pb_light_vol         = trial.suggest_float('b_micro_pb_light_vol',         0.40, 0.90) if enable_micro_pullback else base_entry.micro_pb_light_vol
        micro_pb_swing_tol         = trial.suggest_float('b_micro_pb_swing_tol',         0.90, 1.00) if enable_micro_pullback else base_entry.micro_pb_swing_tol
        abcd_min_pullback_pct      = trial.suggest_float('b_abcd_min_pullback_pct',      0.05, 0.30) if enable_abcd           else base_entry.abcd_min_pullback_pct
        abcd_d_light_vol           = trial.suggest_float('b_abcd_d_light_vol',           0.50, 1.00) if enable_abcd           else base_entry.abcd_d_light_vol
        dip_buy_light_vol          = trial.suggest_float('b_dip_buy_light_vol',          0.40, 0.90) if enable_dip_buy        else base_entry.dip_buy_light_vol
        flat_top_resistance_tol    = trial.suggest_float('b_flat_top_resistance_tol',    0.01, 0.10) if enable_flat_top       else base_entry.flat_top_resistance_tol
        flat_top_vol_increase_tol  = trial.suggest_float('b_flat_top_vol_increase_tol',  1.00, 2.00) if enable_flat_top       else base_entry.flat_top_vol_increase_tol

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
            dip_buy_light_vol=dip_buy_light_vol,
            flat_top_resistance_tol=flat_top_resistance_tol,
            flat_top_vol_increase_tol=flat_top_vol_increase_tol,
            enable_ema9=False,
            enable_macd=False,
            enable_trend=False,
            enable_rr=False,
            enable_bull_flag=enable_bull_flag,
            enable_micro_pullback=enable_micro_pullback,
            enable_abcd=enable_abcd,
            enable_dip_buy=enable_dip_buy,
            enable_flat_top=enable_flat_top,
        )

        # Category C: exactly one profit-exit strategy; hard stop always active
        c_profit = trial.suggest_categorical(
            'c_profit',
            ['fixed_target', 'trailing_stop', 'ema_cross', 'macd_flip', 'time_decay'],
        )
        trailing_stop_distance = (
            trial.suggest_float('c_trailing_stop_distance', 0.05, 0.50)
            if c_profit == 'trailing_stop' else 0.0
        )
        target1_ratio   = trial.suggest_float('c_target1_ratio',   1.0, 3.0)
        target1_qty_pct = trial.suggest_float('c_target1_qty_pct', 0.20, 0.80)
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
        time_decay_hour          = trial.suggest_int(  'c_time_decay_hour',          10, 13)
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
            enable_macd_flip_exit    = c_profit == 'macd_flip',
            macd_flip_qty_pct        = macd_flip_qty_pct,
            enable_resistance_exit   = False,
            enable_volume_dry_up_exit= False,
        )

        return RunConfig(scanner=scanner, entry=entry, exit_=exit_)

    # ── full mode ─────────────────────────────────────────────────────────
    # Category A ──────────────────────────────────────────────────────────
    enable_price_range      = base_scanner.enable_price_range   # always on
    enable_premarket_gain   = get_bool('a_enable_premarket_gain')
    if disable_relative_volume:
        enable_relative_volume = False
    else:
        enable_relative_volume = get_bool('a_enable_relative_volume')
    enable_buying_volume    = get_bool('a_enable_buying_volume')
    enable_float_filter     = get_bool('a_enable_float_filter')
    enable_market_cap_filter= get_bool('a_enable_market_cap_filter')
    enable_spread_filter    = base_scanner.enable_spread_filter  # hardcoded off
    enable_last_5min_volume = base_scanner.enable_last_5min_volume
    enable_last_1min_volume = base_scanner.enable_last_1min_volume

    min_price           = get_float('a_min_price')
    max_price           = get_float('a_max_price')
    min_premarket_gain  = get_float('a_min_premarket_gain') if enable_premarket_gain else base_scanner.min_premarket_gain
    min_relative_volume = get_float('a_min_relative_volume') if enable_relative_volume else base_scanner.min_relative_volume
    min_buying_volume   = get_int('a_min_buying_volume') if enable_buying_volume else base_scanner.min_buying_volume
    max_float           = get_int('a_max_float') if enable_float_filter else base_scanner.max_float
    max_market_cap      = get_int('a_max_market_cap') if enable_market_cap_filter else base_scanner.max_market_cap

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

    # Category B ──────────────────────────────────────────────────────────
    enable_ema9          = get_bool('b_enable_ema9')
    enable_macd          = get_bool('b_enable_macd')
    enable_trend         = get_bool('b_enable_trend')
    enable_rr            = base_entry.enable_rr   # always on
    enable_bull_flag     = get_bool('b_enable_bull_flag')
    enable_micro_pullback= get_bool('b_enable_micro_pullback')
    enable_abcd          = get_bool('b_enable_abcd')
    enable_dip_buy       = get_bool('b_enable_dip_buy')
    enable_flat_top      = get_bool('b_enable_flat_top')

    min_rr_ratio  = get_float('b_min_rr_ratio')
    stop_buffer   = get_float('b_stop_buffer')

    bull_flag_light_vol        = get_float('b_bull_flag_light_vol')        if enable_bull_flag      else base_entry.bull_flag_light_vol
    bull_flag_pole_vol_min     = get_float('b_bull_flag_pole_vol_min')     if enable_bull_flag      else base_entry.bull_flag_pole_vol_min
    bull_flag_breakout_vol_min = get_float('b_bull_flag_breakout_vol_min') if enable_bull_flag      else base_entry.bull_flag_breakout_vol_min
    micro_pb_green_pct         = get_float('b_micro_pb_green_pct')         if enable_micro_pullback else base_entry.micro_pb_green_pct
    micro_pb_light_vol         = get_float('b_micro_pb_light_vol')         if enable_micro_pullback else base_entry.micro_pb_light_vol
    micro_pb_swing_tol         = get_float('b_micro_pb_swing_tol')         if enable_micro_pullback else base_entry.micro_pb_swing_tol
    abcd_min_pullback_pct      = get_float('b_abcd_min_pullback_pct')      if enable_abcd           else base_entry.abcd_min_pullback_pct
    abcd_d_light_vol           = get_float('b_abcd_d_light_vol')           if enable_abcd           else base_entry.abcd_d_light_vol
    dip_buy_light_vol          = get_float('b_dip_buy_light_vol')          if enable_dip_buy        else base_entry.dip_buy_light_vol
    flat_top_resistance_tol    = get_float('b_flat_top_resistance_tol')    if enable_flat_top       else base_entry.flat_top_resistance_tol
    flat_top_vol_increase_tol  = get_float('b_flat_top_vol_increase_tol')  if enable_flat_top       else base_entry.flat_top_vol_increase_tol

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
        dip_buy_light_vol=dip_buy_light_vol,
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
    )

    # Category C ──────────────────────────────────────────────────────────
    exit_ = ExitConfig(
        target1_ratio            = get_float('c_target1_ratio'),
        target2_ratio            = get_float('c_target2_ratio'),
        target1_qty_pct          = get_float('c_target1_qty_pct'),
        target2_qty_pct          = get_float('c_target2_qty_pct'),
        trailing_stop_distance   = get_float('c_trailing_stop_distance'),
        time_decay_hour          = get_int('c_time_decay_hour'),
        early_time_decay_hour    = 0,  # Phase 4 — disabled
        selling_pressure_ratio   = get_float('c_selling_pressure_ratio'),
        selling_pressure_qty_pct = get_float('c_selling_pressure_qty_pct'),
        enable_macd_flip_exit    = base_exit.enable_macd_flip_exit,
        enable_resistance_exit   = base_exit.enable_resistance_exit,
        enable_volume_dry_up_exit= base_exit.enable_volume_dry_up_exit,
    )

    return RunConfig(scanner=scanner, entry=entry, exit_=exit_)


# ── Feature importance ────────────────────────────────────────────────────────

def compute_importances(
    study: optuna.Study,
    min_trials: int = 5,
) -> dict[str, float] | None:
    """
    Compute parameter importances using PedAnovaImportanceEvaluator.

    Returns None if too few trials or evaluator unavailable.
    Returns dict mapping param_name -> importance_score (0.0 to 1.0, normalized).
    Pruned trials (TrialPruned / PRUNED state) are excluded from analysis.
    """
    completed = [
        t for t in study.trials
        if t.state == TrialState.COMPLETE and t.value is not None and t.value > -999.0
    ]
    if len(completed) < min_trials:
        print(f"  Skipping importance analysis: only {len(completed)} valid trials (need {min_trials})")
        return None

    if not _HAS_PEDANOVA:
        print("  PedAnovaImportanceEvaluator not available in this Optuna version — skipping importance")
        return None

    try:
        evaluator = PedAnovaImportanceEvaluator(target_quantile=0.25)
        importances = optuna.importance.get_param_importances(study, evaluator=evaluator)
        return dict(importances)
    except Exception as e:
        print(f"  Importance analysis failed: {e}")
        return None


# ── State update ──────────────────────────────────────────────────────────────

def _get_top_quartile_trials(
    study: optuna.Study,
) -> list[optuna.trial.FrozenTrial]:
    """Return the top 25% of completed trials by objective. Excludes pruned trials."""
    completed = [
        t for t in study.trials
        if t.state == TrialState.COMPLETE and t.value is not None and t.value > -999.0
    ]
    if not completed:
        return []
    completed.sort(key=lambda t: t.value, reverse=True)
    n_top = max(1, len(completed) // 4)
    return completed[:n_top]


def update_state_from_importances(
    state: MetaParamState,
    importances: dict[str, float],
    top_trials: list[optuna.trial.FrozenTrial],
    round_num: int,
    bool_lock_threshold: float = 0.03,
    range_narrow_factor: float = 1.5,
    range_widen_factor: float = 0.15,
    boundary_tolerance: float = 0.02,
    min_trials_per_value: int = 5,
) -> tuple[MetaParamState, list[str]]:
    """
    Apply one round of state updates based on feature importances.

    Returns updated state and a list of human-readable change messages.
    """
    changes: list[str] = []

    for name, importance in importances.items():
        if name not in PARAM_REGISTRY:
            continue

        spec = state.get_spec(name)
        spec.importance_history.append(round(importance, 4))
        reg = PARAM_REGISTRY[name]

        if reg['type'] == 'bool':
            # ── Bool toggle decisions ─────────────────────────────────────
            if spec.locked:
                state.set_spec(name, spec)
                continue

            # Collect values from all completed trials (not just top)
            all_completed = [
                t for t in top_trials
                if name in t.params
            ]
            # Use all trials in study for value counts
            all_trials = []
            for study_trial in top_trials:
                if name in study_trial.params:
                    all_trials.append(study_trial.params[name])

            true_count  = sum(1 for v in all_trials if v)
            false_count = sum(1 for v in all_trials if not v)

            if importance < bool_lock_threshold:
                # Low importance — lock if we have enough data both ways
                if true_count >= min_trials_per_value and false_count >= min_trials_per_value:
                    # Lock to majority value in top quartile
                    majority = true_count >= false_count
                    spec.locked = True
                    spec.locked_value = majority
                    state.set_spec(name, spec)
                    changes.append(
                        f"  LOCKED   {name:<40} = {majority}  (importance={importance:.3f}, "
                        f"top-q true={true_count} false={false_count})"
                    )
                else:
                    state.set_spec(name, spec)
            else:
                # High importance — ensure it stays free
                if spec.locked:
                    spec.locked = False
                    state.set_spec(name, spec)
                    changes.append(f"  UNLOCKED {name:<40} (importance={importance:.3f} rose above threshold)")
                else:
                    state.set_spec(name, spec)

        else:
            # ── Numeric range decisions ───────────────────────────────────
            # Collect values from top-quartile trials
            values = [
                t.params[name]
                for t in top_trials
                if name in t.params
            ]
            if len(values) < 3:
                state.set_spec(name, spec)
                continue

            mean = float(np.mean(values))
            std  = float(np.std(values))
            orig_lo = spec.original_low
            orig_hi = spec.original_high
            orig_width = orig_hi - orig_lo
            min_width = orig_width * 0.10

            # Compute narrowed range
            new_lo = mean - range_narrow_factor * std
            new_hi = mean + range_narrow_factor * std

            # Clamp to original bounds
            new_lo = max(orig_lo, new_lo)
            new_hi = min(orig_hi, new_hi)

            # Enforce minimum width
            if (new_hi - new_lo) < min_width:
                center = (new_lo + new_hi) / 2
                new_lo = max(orig_lo, center - min_width / 2)
                new_hi = min(orig_hi, center + min_width / 2)

            # Check boundary hits on current range
            best_value = values[0] if values else mean  # top trial's value
            boundary_lo = spec.current_low
            boundary_hi = spec.current_high
            width = boundary_hi - boundary_lo

            hit_lo = (best_value - boundary_lo) <= boundary_tolerance * width
            hit_hi = (boundary_hi - best_value) <= boundary_tolerance * width

            if hit_lo or hit_hi:
                spec.boundary_hits += 1
                widen = orig_width * range_widen_factor
                if hit_lo:
                    new_lo = max(orig_lo - widen, orig_lo * 0.5 if orig_lo > 0 else orig_lo - widen)
                if hit_hi:
                    new_hi = min(orig_hi + widen, orig_hi * 1.5 if orig_hi > 0 else orig_hi + widen)
                # Re-clamp: allow slight expansion beyond original but flag it
                new_lo = max(orig_lo * 0.8, new_lo)
                new_hi = min(orig_hi * 1.2, new_hi)

            # For int params, round to step boundaries
            if reg['type'] == 'int':
                step = reg.get('step', 1)
                new_lo = round(new_lo / step) * step
                new_hi = round(new_hi / step) * step
                new_lo = max(int(orig_lo), int(new_lo))
                new_hi = min(int(orig_hi * 1.2), int(new_hi))

            old_lo = spec.current_low
            old_hi = spec.current_high

            spec.current_low  = new_lo
            spec.current_high = new_hi
            state.set_spec(name, spec)

            if hit_lo or hit_hi:
                changes.append(
                    f"  WIDENED  {name:<40} [{old_lo:.3g}, {old_hi:.3g}] -> [{new_lo:.3g}, {new_hi:.3g}] (boundary hit)"
                )
            elif abs(new_lo - old_lo) > 1e-9 or abs(new_hi - old_hi) > 1e-9:
                changes.append(
                    f"  NARROWED {name:<40} [{old_lo:.3g}, {old_hi:.3g}] -> [{new_lo:.3g}, {new_hi:.3g}]"
                )

    return state, changes


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_round_report(
    round_num: int,
    n_rounds: int,
    study: optuna.Study,
    importances: dict[str, float] | None,
    changes: list[str],
    prev_best: float,
    new_best: float,
    best_round: int,
) -> None:
    all_trials = study.trials
    completed = [
        t for t in all_trials
        if t.state == TrialState.COMPLETE and t.value is not None
    ]
    pruned = [t for t in all_trials if t.state == TrialState.PRUNED]
    valid = [t for t in completed if t.value > -999.0]

    try:
        round_best = study.best_trial.value
    except Exception:
        round_best = float('nan')

    print(f"\n{'='*62}")
    print(f"ROUND {round_num + 1} / {n_rounds} COMPLETE")
    print(f"{'='*62}")
    n_pruned = len(pruned)
    pruned_str = f", {n_pruned} pruned" if n_pruned else ""
    print(f"  Trials completed          : {len(completed)}  ({len(valid)} with trades{pruned_str})")
    print(f"  Best objective this round : ${round_best:,.0f}" if not math.isnan(round_best) else "  Best this round : N/A")
    if best_round >= 0:
        print(f"  Best objective all-time   : ${new_best:,.0f}  (round {best_round + 1})")
    print()

    if importances:
        print("  Top parameter importances:")
        sorted_imp = sorted(importances.items(), key=lambda x: x[1], reverse=True)
        for i, (pname, score) in enumerate(sorted_imp[:10], 1):
            print(f"    {i:2d}. {pname:<44} {score:.4f}")
        print()

    if changes:
        print("  Search space changes:")
        for c in changes:
            print(c)
    else:
        print("  Search space changes      : (none)")

    print(f"{'='*62}")


# ── Round runner ──────────────────────────────────────────────────────────────

def run_one_round(
    round_num: int,
    n_rounds: int,
    start_date: str,
    end_date: str,
    state: MetaParamState,
    n_trials: int,
    results_conn,
    optuna_db_url: str,
    debug: bool = False,
    cache_data: bool = False,
    cache_dir: str | None = None,
    disable_relative_volume: bool = False,
    bool_lock_threshold: float = 0.03,
    range_narrow_factor: float = 1.5,
    mode: str = 'full',
    symbol_universe: list | None = None,
) -> tuple[MetaParamState, optuna.Study]:
    """Run one full Optuna round with current MetaParamState, then update state."""

    study_name = f"meta_r{round_num:02d}_{start_date}_{end_date}"
    print(f"\n[Round {round_num + 1}/{n_rounds}] Starting Optuna study: {study_name}")

    study = optuna.create_study(
        study_name=study_name,
        direction='maximize',
        storage=optuna_db_url,
        load_if_exists=True,
        sampler=TPESampler(seed=42 + round_num),
        pruner=optuna.pruners.MedianPruner(n_warmup_steps=0),
    )

    n_existing  = len(study.trials)
    n_remaining = max(0, n_trials - n_existing)
    if n_remaining == 0:
        print(f"  All {n_trials} trials already complete for this round.")
    else:
        print(f"  Running {n_remaining} trials ({n_existing} already done)...")

    def objective(trial: optuna.Trial) -> float:
        cfg = _build_config_from_trial_meta(trial, state, disable_relative_volume, mode=mode)
        try:
            result = run_date_range(
                cfg, start_date, end_date,
                verbose=False,
                debug=debug,
                cache_data=cache_data,
                cache_dir=cache_dir,
                symbol_universe=symbol_universe,
            )
        except Exception as e:
            print(f"    Trial {trial.number} ERROR: {e}")
            return -999.0

        if result['total_trades'] == 0:
            raise optuna.TrialPruned()

        trades = result.pop('trades')
        run_id = f"meta_r{round_num:02d}_{trial.number:05d}"
        write_run(results_conn, run_id, start_date, end_date,
                  result, cfg.to_flat_dict(), trades)
        return result['objective']

    if n_remaining > 0:
        study.optimize(objective, n_trials=n_remaining, show_progress_bar=True)

    # ── Importance analysis ───────────────────────────────────────────────
    importances = compute_importances(study, min_trials=5)
    top_trials  = _get_top_quartile_trials(study)

    changes: list[str] = []
    if importances and top_trials:
        state, changes = update_state_from_importances(
            state, importances, top_trials, round_num,
            bool_lock_threshold=bool_lock_threshold,
            range_narrow_factor=range_narrow_factor,
        )

    # ── Track global best ─────────────────────────────────────────────────
    prev_best = state.best_objective
    try:
        round_best = study.best_trial.value
        if round_best > state.best_objective:
            state.best_objective = round_best
            state.best_round     = round_num
            state.best_params    = dict(study.best_trial.params)
    except Exception:
        pass

    state.round_history.append({
        'round':        round_num,
        'study_name':   study_name,
        'n_trials':     len(study.trials),
        'importances':  importances or {},
        'changes':      changes,
    })
    state.round_num = round_num + 1

    print_round_report(
        round_num=round_num,
        n_rounds=n_rounds,
        study=study,
        importances=importances,
        changes=changes,
        prev_best=prev_best,
        new_best=state.best_objective,
        best_round=state.best_round,
    )

    return state, study


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_meta_optimizer(
    start_date: str,
    end_date: str,
    n_rounds: int = 5,
    trials_per_round: int = 50,
    results_db_path: str | None = None,
    optuna_db_url: str | None = None,
    state_path: str | None = None,
    resume: bool = False,
    debug: bool = False,
    cache_data: bool = False,
    cache_dir: str | None = None,
    disable_relative_volume: bool = False,
    bool_lock_threshold: float = 0.03,
    range_narrow_factor: float = 1.5,
    mode: str = 'full',
    symbols_file: str | None = None,
) -> None:
    """Main meta-optimization loop."""

    results_db = results_db_path or str(Path(__file__).parent / 'meta_results.db')
    optuna_url = optuna_db_url   or 'sqlite:///optimizer/meta_optuna.db'
    state_file = state_path      or str(Path(__file__).parent / 'meta_state.json')

    # ── Load symbol universe ──────────────────────────────────────────────
    symbol_universe: list | None = None
    if symbols_file:
        import csv
        with open(symbols_file) as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            symbol_universe = [row[0].strip() for row in reader if row]
        print(f"  Symbol universe   : {len(symbol_universe)} symbols from {symbols_file}")

    # ── Load or build state ───────────────────────────────────────────────
    if resume and Path(state_file).exists():
        state = load_state(state_file)
        print(f"Resumed from round {state.round_num} (state: {state_file})")
    else:
        state = build_initial_state()
        print("Starting fresh meta-optimization run.")

    results_conn = init_db(results_db)

    print(f"\nMeta-Optimizer")
    print(f"  Date range        : {start_date} -> {end_date}")
    print(f"  Mode              : {mode}")
    print(f"  Rounds            : {n_rounds}")
    print(f"  Trials per round  : {trials_per_round}")
    print(f"  Results DB        : {results_db}")
    print(f"  Optuna DB         : {optuna_url}")
    print(f"  State file        : {state_file}")
    print(f"  Cache data        : {cache_data}")
    if mode == 'full':
        print(f"  Disable rel-vol   : {disable_relative_volume}")
        print(f"  Bool lock thresh  : {bool_lock_threshold}")
        print(f"  Range narrow factor: {range_narrow_factor}")

    # ── Round loop ────────────────────────────────────────────────────────
    for round_num in range(state.round_num, n_rounds):
        state, _ = run_one_round(
            round_num=round_num,
            n_rounds=n_rounds,
            start_date=start_date,
            end_date=end_date,
            state=state,
            n_trials=trials_per_round,
            results_conn=results_conn,
            optuna_db_url=optuna_url,
            debug=debug,
            cache_data=cache_data,
            cache_dir=cache_dir,
            disable_relative_volume=disable_relative_volume,
            bool_lock_threshold=bool_lock_threshold,
            range_narrow_factor=range_narrow_factor,
            mode=mode,
            symbol_universe=symbol_universe,
        )
        save_state(state, state_file)

    # ── Final summary ─────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print("META-OPTIMIZATION COMPLETE")
    print(f"{'='*62}")
    print(f"  Best objective : ${state.best_objective:,.0f}  (round {state.best_round + 1})")
    print()
    print("  Best parameter config:")
    for k, v in sorted(state.best_params.items()):
        print(f"    {k:<44} {v}")

    # Print locked toggles
    locked = [
        (name, state.get_spec(name))
        for name in PARAM_REGISTRY
        if PARAM_REGISTRY[name]['type'] == 'bool' and state.get_spec(name).locked
    ]
    if locked:
        print()
        print("  Locked toggles (low importance):")
        for name, spec in sorted(locked):
            print(f"    {name:<44} = {spec.locked_value}")

    print(f"{'='*62}\n")
    results_conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='ML meta-optimizer: iterative Optuna with feature-importance-guided search space refinement'
    )
    parser.add_argument('--start',               required=True,  help='Start date YYYY-MM-DD')
    parser.add_argument('--end',                 required=True,  help='End date YYYY-MM-DD')
    parser.add_argument('--rounds',              type=int, default=5,  help='Number of meta-rounds (default 5)')
    parser.add_argument('--trials-per-round',    type=int, default=50, help='Optuna trials per round (default 50)')
    parser.add_argument('--db',                  default=None, help='Results SQLite path (default: optimizer/meta_results.db)')
    parser.add_argument('--optuna-db',           default=None, help='Optuna storage URL (default: sqlite:///optimizer/meta_optuna.db)')
    parser.add_argument('--state',               default=None, help='State JSON path (default: optimizer/meta_state.json)')
    parser.add_argument('--resume',              action='store_true', help='Resume from existing state file')
    parser.add_argument('--debug',               action='store_true', help='Enable verbose simulation debug logging')
    parser.add_argument('--cache-data',          action='store_true', help='Cache market data in memory per date')
    parser.add_argument('--cache-dir',           default='data/cache', help='Directory for persisted cache files')
    parser.add_argument('--disable-relative-volume', action='store_true', help='Disable relative volume gate (speed, full mode only)')
    parser.add_argument('--bool-lock-threshold', type=float, default=0.03, help='Importance below this locks a toggle (default 0.03, full mode only)')
    parser.add_argument('--range-narrow-factor', type=float, default=1.5,  help='Std-dev multiplier for range narrowing (default 1.5, full mode only)')
    parser.add_argument('--mode',                default='single-indicator', choices=['full', 'single-indicator'],
                        help='Optimization mode: single-indicator (default) or full')
    parser.add_argument('--symbols-file',        default=None,
                        help='CSV file with symbol universe (col 0 = symbol, has header row). '
                             'Bypasses all scanner pre-screens when set.')
    args = parser.parse_args()

    run_meta_optimizer(
        start_date=args.start,
        end_date=args.end,
        n_rounds=args.rounds,
        trials_per_round=args.trials_per_round,
        results_db_path=args.db,
        optuna_db_url=args.optuna_db,
        state_path=args.state,
        resume=args.resume,
        debug=args.debug,
        cache_data=args.cache_data,
        cache_dir=args.cache_dir if args.cache_data else None,
        disable_relative_volume=args.disable_relative_volume,
        bool_lock_threshold=args.bool_lock_threshold,
        range_narrow_factor=args.range_narrow_factor,
        mode=args.mode,
        symbols_file=args.symbols_file,
    )
