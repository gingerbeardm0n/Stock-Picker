"""
Scalp Ranker — Gapper Ranking for Opening Bell Scalp
=====================================================
Scores and ranks premarket gappers to find the #1 candidate.

Scoring weights are FIXED (not tunable) to avoid overfitting.
Based on Ross Cameron's stated priorities: gap %, volume, news, then float.
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

# Fixed scoring weights — NOT tunable parameters.
# Ross's priorities: gap size + volume + news are equally important; float is a tiebreaker.
W_GAP = 0.30
W_RELVOL = 0.30
W_NEWS = 0.30
W_FLOAT = 0.10

# Candidate-screening constants shared by live runners AND simulators.
# Live runners only enrich the top N gappers by gap%% (news API cost) and
# drop absurd gaps as bad quotes; sims must apply the SAME cuts or they
# see candidates live never would (parity gap #2/#4, found 2026-06-12).
ENRICH_TOP_N = 20
MAX_GAP_PCT = 1000.0


def screen_candidates(candidates: list[dict]) -> list[dict]:
    """Apply the shared pre-enrichment screen: drop gap%>MAX_GAP_PCT,
    keep only the top ENRICH_TOP_N by gap%. Input may be unsorted."""
    ok = [c for c in candidates if c.get('gap_pct', 0) <= MAX_GAP_PCT]
    ok.sort(key=lambda c: c.get('gap_pct', 0), reverse=True)
    return ok[:ENRICH_TOP_N]


def _normalize(values: list[float]) -> list[float]:
    """Min-max normalize to [0, 1]. Returns zeros if all values equal."""
    if not values:
        return []
    values = [float(v) for v in values]
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _float_score(float_shares: int | None) -> float:
    """Score float: lower = better for scalps (bigger moves on low float)."""
    if float_shares is None:
        return 0.3  # unknown float — slight penalty
    if float_shares < 5_000_000:
        return 1.0
    if float_shares < 10_000_000:
        return 0.7
    if float_shares < 20_000_000:
        return 0.5
    return 0.2


def _news_score(has_news: bool, news_tier: str | None) -> float:
    """Score news catalyst quality."""
    if not has_news:
        return 0.0
    tier_scores = {
        'tier1': 1.0,
        'tier2': 0.7,
        'tier3': 0.4,
        'presence': 0.2,
        'none': 0.0,
    }
    return tier_scores.get(news_tier or 'none', 0.0)


def rank_candidates(candidates: list[dict]) -> list[dict]:
    """
    Score and rank gapper candidates. Returns sorted list (best first).

    Each candidate dict must have:
        symbol:        str
        gap_pct:       float (% gain vs prior close)
        rel_vol:       float (premarket relative volume)
        float_shares:  int | None
        has_news:      bool
        news_tier:     str | None ('tier1', 'tier2', 'tier3', 'presence', 'none')

    Additional keys are preserved in the output.
    """
    if not candidates:
        return []

    # Normalize gap_pct and rel_vol across today's candidates
    gap_vals = [c['gap_pct'] for c in candidates]
    vol_vals = [c['rel_vol'] for c in candidates]
    gap_norm = _normalize(gap_vals)
    vol_norm = _normalize(vol_vals)

    scored = []
    for i, c in enumerate(candidates):
        news_s = _news_score(c.get('has_news', False), c.get('news_tier'))
        float_s = _float_score(c.get('float_shares'))

        score = (
            W_GAP * gap_norm[i]
            + W_RELVOL * vol_norm[i]
            + W_NEWS * news_s
            + W_FLOAT * float_s
        )

        scored.append({**c, 'scalp_score': round(score, 4)})

    scored.sort(key=lambda x: x['scalp_score'], reverse=True)
    return scored


def get_top_candidate(candidates: list[dict]) -> dict | None:
    """Return #1 ranked candidate or None if no candidates."""
    ranked = rank_candidates(candidates)
    return ranked[0] if ranked else None
