import requests
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Articles tagged with more symbols than this are likely roundups/listicles
MAX_SYMBOLS_FOR_SPECIFIC_NEWS = 5

# ── Keyword sets for news tier classification ─────────────────────────────────
# Source: concept_news_catalyst.md Tier 1/2/3 taxonomy
# Checked in order: first match wins. Headlines/summaries searched case-insensitive.

_TIER1_KEYWORDS = [
    'fda', 'approval', 'approved', 'clearance', 'cleared',  # FDA / regulatory
    'acquisition', 'merger', 'buyout', 'acquired',          # M&A
    'earnings beat', 'beat estimates', 'raised guidance',    # Earnings
    'reverse split', 'reverse stock split',                  # Float mechanics
    'short squeeze', 'days to cover',                        # Squeeze confirmation
    'bankruptcy', 'chapter 11',                              # Distress catalyst
]
_TIER2_KEYWORDS = [
    'contract', 'partnership', 'agreement', 'collaboration',  # Business deals
    'phase 2', 'phase 3', 'clinical trial', 'ind application', 'inda',  # Biotech
    'government contract', 'defense contract', 'military',    # Gov / defense
    'insider buy', 'form 4', 'director purchase',             # Insider activity
    'uplisted', 'uplisting', 'nasdaq listing',                # Exchange listing
]
_TIER3_KEYWORDS = [
    'sympathy', 'sector', 'industry move',     # Sector plays
    'reddit', 'twitter', 'social media', 'wsb', 'wallstreetbets',  # Social
    'strategic review', 'exploring options',   # Vague corporate language
]


def classify_news_tier(articles: list) -> str:
    """
    Classify the quality tier of a symbol's news from fetched article data.

    Checks headline + summary text for tier-specific keywords in priority order.
    Only counts articles tagged with ≤ MAX_SYMBOLS_FOR_SPECIFIC_NEWS tickers
    (filters out roundup/listicle content).

    Returns one of:
        'tier1'    — hard catalyst (FDA, M&A, earnings beat, short squeeze)
        'tier2'    — medium catalyst (contract, biotech data, insider buy)
        'tier3'    — weak catalyst (sector sympathy, social media driven)
        'presence' — news present but no tier keywords matched
        'none'     — no specific articles found
    """
    specific = [a for a in articles if a.get('is_specific', True)]
    if not specific:
        return 'none'

    all_text = ' '.join(
        f"{a.get('headline', '')} {a.get('summary', '')}"
        for a in specific
    ).lower()

    for kw in _TIER1_KEYWORDS:
        if kw in all_text:
            return 'tier1'
    for kw in _TIER2_KEYWORDS:
        if kw in all_text:
            return 'tier2'
    for kw in _TIER3_KEYWORDS:
        if kw in all_text:
            return 'tier3'

    return 'presence'  # news found, just doesn't match known tier keywords


# ── Shared sim/live news gate ────────────────────────────────────────────────
# The set of tiers that count as a tradeable catalyst. Includes 'tier3' (weak:
# sector sympathy / social-only) to MATCH the simulator the strategies were
# validated against — the sim gate was `any(is_specific)`, i.e. any article that
# isn't a multi-symbol roundup, which equals any tier != 'none' (tier1/2/3 or
# presence). The live runners previously excluded 'tier3', so they skipped days
# the backtest traded. Unified here.
#
# To exclude tier3 (trade only stronger catalysts), drop it from this set AND
# re-run the optimizer/validation — it changes which days trade.
NEWS_CATALYST_TIERS = frozenset({'tier1', 'tier2', 'tier3', 'presence'})


def has_news_catalyst(tier: str) -> bool:
    """Shared news gate for sim AND live. True if `tier` counts as a catalyst.

    Single source of truth so the simulator's candidate selection and the live
    runners' candidate selection can never diverge on the news filter.
    """
    return tier in NEWS_CATALYST_TIERS


class NewsFetcher:
    def __init__(self):
        from alpaca.data.historical import NewsClient
        from config import Config

        self.news_client = NewsClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_SECRET_KEY
        )

    def get_news_for_symbol(self, symbol, as_of_date=None, hours_back=48):
        """
        Get news for a symbol around a specific date.
        Articles are sorted so specific/direct news appears first.

        Args:
            symbol: Stock ticker
            as_of_date: datetime.date for backtesting (None = today/live mode)
            hours_back: How many hours before as_of_date to look back
        """
        try:
            from alpaca.data.requests import NewsRequest

            if as_of_date:
                end = datetime.combine(as_of_date, datetime.max.time())
                start = end - timedelta(hours=hours_back)
            else:
                end = datetime.now()
                start = end - timedelta(hours=hours_back)

            request = NewsRequest(
                symbols=symbol,
                start=start,
                end=end,
                limit=20  # Fetch more so we have room to sort/filter
            )

            news = self.news_client.get_news(request)
            articles = news.data.get('news', [])

            result = []
            for a in articles:
                symbol_count = len(getattr(a, 'symbols', []) or [])
                result.append({
                    'headline': a.headline,
                    'summary': getattr(a, 'summary', '').strip(),
                    'url': getattr(a, 'url', ''),
                    'source': getattr(a, 'source', ''),
                    'created_at': a.created_at.isoformat() if getattr(a, 'created_at', None) else None,
                    'symbol_count': symbol_count,  # How many tickers this article covers
                    'is_specific': symbol_count <= MAX_SYMBOLS_FOR_SPECIFIC_NEWS,
                })

            # Sort: specific articles (few symbols) first, then by date
            result.sort(key=lambda x: (not x['is_specific'], x['symbol_count']))

            return result

        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
            return []

    def has_catalyst(self, symbol, as_of_date=None, hours_back=48):
        """
        Check if a stock has a specific news catalyst.
        Only counts as a catalyst if there's at least one specific article
        (not just roundup/listicle content).
        """
        articles = self.get_news_for_symbol(symbol, as_of_date=as_of_date, hours_back=hours_back)
        specific = [a for a in articles if a['is_specific']]
        has_cat = len(specific) > 0
        return has_cat, articles  # Return all articles but flag is based on specific ones
