"""
Market Temperature
==================
Classifies each trading session as HOT / NEUTRAL / COLD / CHOP based on
pre-market gap quality and number of qualifying symbols.

Source: concept_market_temperature.md
Key fact: HOT=46%, NEUTRAL=22%, COLD=32% of sessions in 1,799-session corpus.
COLD is the safe default; HOT/NEUTRAL are activated by evidence at 9:15 AM ET.

Temperature drives:
    max_position_pct        — how large positions can be
    max_trades_per_day      — how many completed trades allowed
    session_stop_hour/min   — hard stop for new entries (and force-close open positions)
    daily_loss_limit_pct    — max daily loss before halt
    consecutive_loss_stop   — consecutive losses before upgrading to CHOP
    min_confidence          — minimum pattern confidence score required for entry

Usage (in simulation harness or live scanner):

    from trading.market_temperature import classify_premarket, update_from_trade_result
    from trading.models import MarketTemperatureConfig

    cfg = MarketTemperatureConfig()

    # Called once at 9:15 AM ET
    state = classify_premarket(hot_symbols, prior_close, cfg)

    # Called after each completed trade
    state = update_from_trade_result(state, win=trade.get_pnl() > 0, cfg=cfg)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import pytz

ET = pytz.timezone('US/Eastern')


class Temperature(Enum):
    HOT     = "HOT"
    NEUTRAL = "NEUTRAL"
    COLD    = "COLD"
    CHOP    = "CHOP"


@dataclass
class TemperatureState:
    """
    Live session state for market temperature.

    Starts at COLD (74% of days are cold — conservative is safer).
    Updated at premarket classification (9:15 AM) and after each trade.

    The derived fields (max_position_pct etc.) are set by _apply_params()
    and should NOT be set manually — use classify_premarket() or
    update_from_trade_result() which call _apply_params() internally.
    """
    temperature: Temperature = Temperature.COLD

    # Raw signals (populated at 9:15 AM)
    leading_gapper_pct: float = 0.0       # Best gap % across all qualifying symbols
    qualifying_symbols_count: int = 0     # Count of symbols passing base scanner criteria

    # Runtime state
    consecutive_losses: int = 0
    premarket_classified: bool = False    # True once classify_premarket() has run

    # ── Derived trading parameters (set by _apply_params) ─────────────────────
    # These mirror the SimulationRunner fields they override each minute.
    max_position_pct: float = 10.0        # % of account per position
    max_trades_per_day: int = 3
    session_stop_hour: int = 10           # Hard stop hour (ET)
    session_stop_minute: int = 30         # Hard stop minute (ET)
    daily_loss_limit_pct: float = 1.5
    consecutive_loss_stop: int = 2        # Consecutive losses → CHOP upgrade
    min_confidence: int = 5              # Minimum PatternSignal.confidence for entry


# ── Parameter tables (from concept_market_temperature.md §6) ──────────────────

# session_stop encoded as (hour, minute) ET
_PARAMS: dict[Temperature, dict] = {
    Temperature.HOT: {
        'max_position_pct':     20.0,
        'max_trades_per_day':   10,
        'session_stop_hour':    12,
        'session_stop_minute':  0,
        'daily_loss_limit_pct': 3.0,
        'consecutive_loss_stop': 4,
        'min_confidence':       3,
    },
    Temperature.NEUTRAL: {
        'max_position_pct':     15.0,
        'max_trades_per_day':   5,
        'session_stop_hour':    11,
        'session_stop_minute':  0,
        'daily_loss_limit_pct': 2.0,
        'consecutive_loss_stop': 3,
        'min_confidence':       4,
    },
    Temperature.COLD: {
        'max_position_pct':     10.0,
        'max_trades_per_day':   3,
        'session_stop_hour':    10,
        'session_stop_minute':  30,
        'daily_loss_limit_pct': 1.5,
        'consecutive_loss_stop': 2,
        'min_confidence':       5,
    },
    Temperature.CHOP: {
        'max_position_pct':     5.0,
        'max_trades_per_day':   1,
        'session_stop_hour':    10,
        'session_stop_minute':  0,
        'daily_loss_limit_pct': 1.0,
        'consecutive_loss_stop': 1,
        'min_confidence':       5,
    },
}


def _apply_params(state: TemperatureState, cfg) -> None:
    """
    Copy per-temperature parameter values from cfg overrides (or defaults)
    into the TemperatureState derived fields. Modifies state in place.
    """
    from trading.models import MarketTemperatureConfig  # local import avoids circular
    base = _PARAMS[state.temperature]

    # cfg overrides take precedence where they differ from dataclass defaults
    cfg_defaults = MarketTemperatureConfig()

    def _pick(param_key: str, cfg_attr: str):
        """Use cfg override if it differs from cfg's own default, else use table value."""
        table_val = base[param_key]
        cfg_val = getattr(cfg, cfg_attr, None)
        cfg_def = getattr(cfg_defaults, cfg_attr, None)
        # If cfg value differs from the cfg default, the caller explicitly set it → honour it
        if cfg_val is not None and cfg_val != cfg_def:
            return cfg_val
        return table_val

    state.max_position_pct      = _pick('max_position_pct',     f'{state.temperature.value.lower()}_max_position_pct')
    state.max_trades_per_day    = _pick('max_trades_per_day',    f'{state.temperature.value.lower()}_max_trades')
    state.session_stop_hour     = base['session_stop_hour']
    state.session_stop_minute   = base['session_stop_minute']
    state.daily_loss_limit_pct  = base['daily_loss_limit_pct']
    state.consecutive_loss_stop = base['consecutive_loss_stop']
    state.min_confidence        = base['min_confidence']


def classify_premarket(
    hot_symbols: set,
    prior_close: dict,
    cfg,
    bars_snapshot: list | None = None,
) -> TemperatureState:
    """
    Classify market temperature at ~9:15 AM ET using premarket signals.

    Args:
        hot_symbols     : Set of symbol strings that passed the price/gain pre-filter
                          (built by SimulationRunner._build_hot_symbols()).
        prior_close     : {symbol: prior_close_price} dict.
        cfg             : MarketTemperatureConfig instance.
        bars_snapshot   : Optional list of current bar dicts for leading gapper calc.
                          If provided, leading_gapper_pct uses live close prices.
                          If None, falls back to estimating from hot_symbols count only.

    Returns:
        TemperatureState with temperature set and derived params applied.

    Detection logic (concept_market_temperature.md §2):
        leading_gapper_pct >= hot_gapper_threshold  AND  qualifying >= hot_symbols_min  → HOT
        leading_gapper_pct >= warm_gapper_threshold OR   qualifying >= cold_symbols_max+1 → NEUTRAL
        otherwise → COLD
    """
    state = TemperatureState()
    state.qualifying_symbols_count = len(hot_symbols)

    # Compute leading gapper % from bar snapshot if available
    if bars_snapshot:
        best_gap = 0.0
        for bar in bars_snapshot:
            symbol = bar.get('symbol') or bar[1] if isinstance(bar, (list, tuple)) else bar.get('symbol')
            if not symbol:
                continue
            pc = prior_close.get(symbol)
            if not pc or pc <= 0:
                continue
            try:
                close = float(bar['close']) if isinstance(bar, dict) else float(bar[5])
            except (KeyError, IndexError, TypeError):
                continue
            gap_pct = (close - pc) / pc * 100
            if gap_pct > best_gap:
                best_gap = gap_pct
        state.leading_gapper_pct = best_gap
    else:
        # Estimate from prior_close and the hot_symbols set alone
        # (hot_symbols already filtered to >= 10% gain, so any member is a valid gapper)
        best_gap = 0.0
        for sym in hot_symbols:
            pc = prior_close.get(sym)
            if pc and pc > 0:
                # We don't have a bar here, so we can't compute exact gap.
                # Use 10.0 as a floor (the hot_symbols filter threshold).
                best_gap = max(best_gap, 10.0)
        state.leading_gapper_pct = best_gap

    # ── Classification ────────────────────────────────────────────────────────
    gap = state.leading_gapper_pct
    syms = state.qualifying_symbols_count

    hot_gap   = cfg.hot_gapper_threshold   # default 50%
    warm_gap  = cfg.warm_gapper_threshold  # default 20%
    hot_syms  = cfg.hot_symbols_min        # default 3
    cold_syms = cfg.cold_symbols_max       # default 2

    if gap >= hot_gap and syms >= hot_syms:
        state.temperature = Temperature.HOT
    elif gap >= warm_gap or syms > cold_syms:
        state.temperature = Temperature.NEUTRAL
    else:
        state.temperature = Temperature.COLD

    state.premarket_classified = True
    _apply_params(state, cfg)
    return state


def update_from_trade_result(
    state: TemperatureState,
    win: bool,
    cfg,
) -> TemperatureState:
    """
    Update temperature state after a completed trade.

    Win  → reset consecutive_losses to 0.
    Loss → increment consecutive_losses; if threshold hit, upgrade to CHOP.

    Concept rule: "if first trade fails immediately, downgrade to chop day mode"
                  "2-3 consecutive losses → stop / force CHOP"
    """
    if win:
        state.consecutive_losses = 0
    else:
        state.consecutive_losses += 1
        if state.consecutive_losses >= state.consecutive_loss_stop:
            # Upgrade to CHOP (can only escalate, never de-escalate within session)
            if state.temperature != Temperature.CHOP:
                state.temperature = Temperature.CHOP
                _apply_params(state, cfg)

    return state


def is_session_over(state: TemperatureState, current_time: datetime) -> bool:
    """
    Returns True if the temperature-driven session stop time has been reached.

    Hard stop = no new entries after this time. Callers should also force-close
    open positions when this returns True (handled by the simulation harness).
    """
    et_time = current_time.astimezone(ET)
    stop_h = state.session_stop_hour
    stop_m = state.session_stop_minute
    return (et_time.hour > stop_h or
            (et_time.hour == stop_h and et_time.minute >= stop_m))
