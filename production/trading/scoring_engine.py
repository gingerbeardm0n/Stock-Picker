"""
Scoring Engine
==============
Computes a composite 0-100 conviction score for each entry candidate.

Replaces the crude 1-5 pattern confidence stars with a multi-factor grade
that accounts for the full quality of the setup — not just the pattern type.

Call compute_entry_score() after all hard gates pass (5 pillars, pattern,
R/R). The score drives:
    - Entry threshold check (replaces temperature.min_confidence gate)
    - Initial position size (higher score → larger starter)
    - Optuna tuning surface (all weights are ScoringConfig fields)

Score components (max points per component, defaults sum to 100):
    Pattern base     25  — from corpus win-rate ranking
    Relative volume  20  — magnitude, not binary (100x >> 5x)
    News tier        20  — Tier 1/2/3/none (soft modifier, not hard gate)
    Float quality    15  — sub-1M=15 down to 20M+=0
    Gap %            10  — magnitude of premarket gap
    MACD state        5  — positive=confirmed front-side, unknown=partial
    Time of day       5  — 9:30-9:45 best, degrades toward 10:30

Temperature sets minimum score threshold and base size multiplier.
Source: concept_news_catalyst.md, concept_entry_trigger_taxonomy.md,
        concept_float_analysis.md, concept_market_temperature.md
"""

from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytz
from datetime import datetime

from trading.models import EntryScore, ScoringConfig, PatternSignal

ET = pytz.timezone('US/Eastern')

# Default config — used when config=None is passed (backward compatible)
_DEFAULTS = ScoringConfig()

# Map pattern_type strings to ScoringConfig field names
_PATTERN_FIELD = {
    'GAP_AND_GO':        'pattern_gap_and_go',
    'MICRO_PULLBACK':    'pattern_micro_pullback',
    'VWAP_RECLAIM':      'pattern_vwap_reclaim',
    'VWAP_BREAK_CURL':   'pattern_vwap_break_curl',
    'ORB':               'pattern_orb',
    'BULL_FLAG':         'pattern_bull_flag',
    'FLAT_TOP':          'pattern_flat_top',
    'RED_TO_GREEN':      'pattern_red_to_green',
    'DIP_BUY':           'pattern_dip_buy',
    'WHOLE_DOLLAR':      'pattern_whole_dollar',
    'ABCD':              'pattern_abcd',
}

# Valid news tier strings
NEWS_TIERS = {'tier1', 'tier2', 'tier3', 'presence', 'none', 'unknown'}


def compute_entry_score(
    pattern: PatternSignal,
    pillar_data: dict,
    indicators: dict,
    current_time: datetime,
    news_tier: str = 'unknown',
    config: ScoringConfig | None = None,
) -> EntryScore:
    """
    Compute a composite 0-100 conviction score for a confirmed entry setup.

    Args:
        pattern      : Detected PatternSignal (type, entry_price, stops, targets).
        pillar_data  : Dict from _check_5_pillars() — keys include 'rel_vol',
                       'pct_change', 'float_shares'.
        indicators   : Dict from entry_engine — keys include 'macd_line'.
        current_time : UTC datetime of the bar being evaluated.
        news_tier    : One of 'tier1', 'tier2', 'tier3', 'presence', 'none',
                       'unknown'. Default 'unknown' = partial credit (backtest
                       graceful degradation when news API unavailable).
        config       : ScoringConfig weights. None = strategy defaults.

    Returns:
        EntryScore with total (0-100) and components breakdown dict.
    """
    cfg = config if config is not None else _DEFAULTS
    et_time = current_time.astimezone(ET)
    components = {}

    # ── 1. Pattern base ────────────────────────────────────────────────────────
    field = _PATTERN_FIELD.get(pattern.pattern_type, 'pattern_default')
    pts_pattern = getattr(cfg, field, cfg.pattern_default)
    components['pattern'] = pts_pattern

    # ── 2. Relative volume magnitude ──────────────────────────────────────────
    rel_vol = float(pillar_data.get('rel_vol', 0) or 0)
    if rel_vol >= 100:
        pts_relvol = cfg.relvol_pts_100x
    elif rel_vol >= 25:
        pts_relvol = cfg.relvol_pts_25x
    elif rel_vol >= 10:
        pts_relvol = cfg.relvol_pts_10x
    else:
        pts_relvol = cfg.relvol_pts_5x   # assumes ≥5x already passed the hard gate
    components['rel_vol'] = pts_relvol

    # ── 3. News tier ──────────────────────────────────────────────────────────
    tier = news_tier if news_tier in NEWS_TIERS else 'unknown'
    pts_news = {
        'tier1':    cfg.news_tier1_pts,
        'tier2':    cfg.news_tier2_pts,
        'tier3':    cfg.news_tier3_pts,
        'presence': cfg.news_presence_pts,
        'none':     cfg.news_none_pts,
        'unknown':  cfg.news_unknown_pts,
    }[tier]
    components['news'] = pts_news

    # ── 4. Float quality ──────────────────────────────────────────────────────
    float_shares = pillar_data.get('float_shares')
    if float_shares is None:
        pts_float = cfg.float_unknown_pts
    elif float_shares < 1_000_000:
        pts_float = cfg.float_sub1m_pts
    elif float_shares < 5_000_000:
        pts_float = cfg.float_1m_5m_pts
    elif float_shares < 20_000_000:
        pts_float = cfg.float_5m_20m_pts
    else:
        pts_float = cfg.float_20m_plus_pts
    components['float'] = pts_float

    # ── 5. Gap % magnitude ────────────────────────────────────────────────────
    pct_change = float(pillar_data.get('pct_change', 0) or 0)
    if pct_change >= 40:
        pts_gap = cfg.gap_40pct_pts
    elif pct_change >= 20:
        pts_gap = cfg.gap_20pct_pts
    else:
        pts_gap = cfg.gap_10pct_pts    # assumes ≥10% already passed the hard gate
    components['gap_pct'] = pts_gap

    # ── 6. MACD state ─────────────────────────────────────────────────────────
    macd_line = indicators.get('macd_line')
    if macd_line is None:
        pts_macd = cfg.macd_unknown_pts
    elif macd_line > 0:
        pts_macd = cfg.macd_positive_pts
    else:
        pts_macd = cfg.macd_negative_pts
    components['macd'] = pts_macd

    # ── 7. Time of day ────────────────────────────────────────────────────────
    h, m = et_time.hour, et_time.minute
    if h == 9 and m < 45:
        pts_time = cfg.time_930_945_pts
    elif h == 9 and m < 60:
        pts_time = cfg.time_945_1000_pts
    elif h == 10 and m < 30:
        pts_time = cfg.time_1000_1030_pts
    else:
        pts_time = cfg.time_after_1030_pts
    components['time_of_day'] = pts_time

    total = sum(components.values())

    return EntryScore(total=total, components=components)
