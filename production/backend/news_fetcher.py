import requests
import time as _time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger(__name__)

# Process-level news cache — shared across all runners in the same Render instance.
# Prevents Finnhub 429s when scalp + VWAP + micro-pullback all scan simultaneously.
_NEWS_CACHE: dict = {}   # symbol -> (articles: list, fetched_at: float)
_CACHE_TTL_S = 600       # 10 minutes — covers the full scan + 9:25 refresh cycle

MAX_SYMBOLS_FOR_SPECIFIC_NEWS = 5

# ── Keyword sets for news tier classification ─────────────────────────────────
_TIER1_KEYWORDS = [
    'fda', 'approval', 'approved', 'clearance', 'cleared',
    'acquisition', 'merger', 'buyout', 'acquired',
    'earnings beat', 'beat estimates', 'raised guidance',
    'reverse split', 'reverse stock split',
    'short squeeze', 'days to cover',
    'bankruptcy', 'chapter 11',
]
_TIER2_KEYWORDS = [
    'contract', 'partnership', 'agreement', 'collaboration',
    'phase 2', 'phase 3', 'clinical trial', 'ind application', 'inda',
    'government contract', 'defense contract', 'military',
    'insider buy', 'form 4', 'director purchase',
    'uplisted', 'uplisting', 'nasdaq listing',
]
_TIER3_KEYWORDS = [
    'sympathy', 'sector', 'industry move',
    'reddit', 'twitter', 'social media', 'wsb', 'wallstreetbets',
    'strategic review', 'exploring options',
]


def classify_news_tier(articles: list) -> str:
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

    return 'presence'


NEWS_CATALYST_TIERS = frozenset({'tier1', 'tier2', 'tier3'})


def has_news_catalyst(tier: str) -> bool:
    return tier in NEWS_CATALYST_TIERS


# ── Source 1: Finnhub ────────────────────────────────────────────────────────

class FinnhubNewsFetcher:
    def __init__(self):
        from config import Config
        self._api_key = Config.FINNHUB_API_KEY
        self._enabled = bool(self._api_key)
        if self._enabled:
            logger.info("FinnhubNewsFetcher initialized")
        else:
            logger.warning("FinnhubNewsFetcher disabled — no FINNHUB_API_KEY")

    def get_news_for_symbol(self, symbol, as_of_date=None, hours_back=48):
        if not self._enabled:
            return []
        try:
            if as_of_date:
                end_date = as_of_date
                start_date = as_of_date - timedelta(hours=hours_back)
            else:
                end_date = datetime.now().date()
                start_date = end_date - timedelta(days=max(hours_back // 24, 2))

            resp = requests.get(
                'https://finnhub.io/api/v1/company-news',
                params={
                    'symbol': symbol,
                    'from': start_date.strftime('%Y-%m-%d'),
                    'to': end_date.strftime('%Y-%m-%d'),
                    'token': self._api_key,
                },
                timeout=5,
            )
            resp.raise_for_status()
            articles = resp.json()
            if not isinstance(articles, list):
                return []

            result = []
            for a in articles:
                result.append({
                    'headline': a.get('headline', ''),
                    'summary': a.get('summary', ''),
                    'url': a.get('url', ''),
                    'source': f"finnhub:{a.get('source', '')}",
                    'created_at': datetime.fromtimestamp(a['datetime'], tz=_ET).isoformat() if a.get('datetime') else None,
                    'symbol_count': 1,
                    'is_specific': True,
                })
            return result

        except Exception as e:
            logger.warning(f"Finnhub news fetch failed for {symbol}: {e}")
            return []


# ── Source 2: Marketaux ──────────────────────────────────────────────────────

class MarketauxNewsFetcher:
    def __init__(self):
        from config import Config
        self._api_key = Config.MARKETAUX_API_KEY
        self._enabled = bool(self._api_key)
        if self._enabled:
            logger.info("MarketauxNewsFetcher initialized")
        else:
            logger.warning("MarketauxNewsFetcher disabled — no MARKETAUX_API_KEY")

    def get_news_for_symbol(self, symbol, as_of_date=None, hours_back=48):
        if not self._enabled:
            return []
        try:
            if as_of_date:
                end_dt = datetime.combine(as_of_date, datetime.max.time())
            else:
                end_dt = datetime.now()
            start_dt = end_dt - timedelta(hours=hours_back)

            resp = requests.get(
                'https://api.marketaux.com/v1/news/all',
                params={
                    'symbols': symbol,
                    'filter_entities': 'true',
                    'published_after': start_dt.strftime('%Y-%m-%dT%H:%M'),
                    'published_before': end_dt.strftime('%Y-%m-%dT%H:%M'),
                    'limit': 10,
                    'api_token': self._api_key,
                },
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            articles = data.get('data', [])
            if not isinstance(articles, list):
                return []

            result = []
            for a in articles:
                entities = a.get('entities', [])
                symbol_count = len(entities) if entities else 1
                result.append({
                    'headline': a.get('title', ''),
                    'summary': a.get('description', ''),
                    'url': a.get('url', ''),
                    'source': f"marketaux:{a.get('source', '')}",
                    'created_at': a.get('published_at', None),
                    'symbol_count': symbol_count,
                    'is_specific': symbol_count <= MAX_SYMBOLS_FOR_SPECIFIC_NEWS,
                })
            return result

        except Exception as e:
            logger.warning(f"Marketaux news fetch failed for {symbol}: {e}")
            return []


# ── Source 3: Alpaca (demoted — weak small-cap coverage) ─────────────────────

class AlpacaNewsFetcher:
    def __init__(self):
        from alpaca.data.historical import NewsClient
        from config import Config

        self._enabled = bool(Config.ALPACA_API_KEY)
        if self._enabled:
            self.news_client = NewsClient(
                Config.ALPACA_API_KEY,
                Config.ALPACA_SECRET_KEY
            )
            logger.info("AlpacaNewsFetcher initialized")
        else:
            self.news_client = None
            logger.warning("AlpacaNewsFetcher disabled — no Alpaca keys")

    def get_news_for_symbol(self, symbol, as_of_date=None, hours_back=48):
        if not self._enabled:
            return []
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
                limit=20,
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
                    'source': f"alpaca:{getattr(a, 'source', '')}",
                    'created_at': a.created_at.isoformat() if getattr(a, 'created_at', None) else None,
                    'symbol_count': symbol_count,
                    'is_specific': symbol_count <= MAX_SYMBOLS_FOR_SPECIFIC_NEWS,
                })

            result.sort(key=lambda x: (not x['is_specific'], x['symbol_count']))
            return result

        except Exception as e:
            logger.error(f"Alpaca news fetch failed for {symbol}: {e}")
            return []


# ── Lookahead bias filter ─────────────────────────────────────────────────────

_ET = ZoneInfo("America/New_York")


def _filter_pre_open(articles: list, as_of_date) -> list:
    """Drop articles published after 9:30 AM ET on as_of_date.

    Backtest sources return full-day results (Finnhub only supports date
    granularity). Live scanner runs premarket and can only see pre-open
    articles, so backtests must match."""
    cutoff = datetime(as_of_date.year, as_of_date.month, as_of_date.day,
                      9, 30, tzinfo=_ET)
    result = []
    for a in articles:
        ts_str = a.get('created_at')
        if ts_str is None:
            result.append(a)
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_ET)  # assume ET for legacy naive timestamps
            if ts <= cutoff:
                result.append(a)
        except (ValueError, TypeError):
            result.append(a)
    return result


# ── Waterfall aggregator ─────────────────────────────────────────────────────

class NewsFetcher:
    """Multi-source news fetcher. Waterfall: Finnhub → Alpaca.
    Stops at first source that returns articles."""

    def __init__(self):
        self._sources = []
        self._source_names = []

        # Order: Finnhub first (best small-cap coverage), Alpaca fallback
        try:
            f = FinnhubNewsFetcher()
            if f._enabled:
                self._sources.append(f)
                self._source_names.append('finnhub')
        except Exception as e:
            logger.warning(f"Failed to init Finnhub: {e}")

        try:
            a = AlpacaNewsFetcher()
            if a._enabled:
                self._sources.append(a)
                self._source_names.append('alpaca')
        except Exception as e:
            logger.warning(f"Failed to init Alpaca: {e}")

        logger.info(f"NewsFetcher waterfall: {' → '.join(self._source_names) or 'NO SOURCES'}")

    def get_news_for_symbol(self, symbol, as_of_date=None, hours_back=48):
        # Check process-level cache first — all three runners share this dict,
        # so parallel scans never double-hit Finnhub for the same symbol.
        cached = _NEWS_CACHE.get(symbol)
        if cached:
            articles, fetched_at = cached
            if _time.time() - fetched_at < _CACHE_TTL_S:
                logger.debug(f"{symbol}: news from cache ({len(articles)} articles)")
                return articles

        for name, source in zip(self._source_names, self._sources):
            try:
                articles = source.get_news_for_symbol(symbol, as_of_date=as_of_date, hours_back=hours_back)
                if as_of_date:
                    articles = _filter_pre_open(articles, as_of_date)
                specific = [a for a in articles if a.get('is_specific', True)]
                if specific:
                    logger.debug(f"{symbol}: news found via {name} ({len(specific)} specific articles)")
                    _NEWS_CACHE[symbol] = (articles, _time.time())
                    return articles
            except Exception as e:
                logger.warning(f"{symbol}: {name} failed: {e}")
                continue

        logger.debug(f"{symbol}: no news from any source")
        _NEWS_CACHE[symbol] = ([], _time.time())
        return []

    def has_catalyst(self, symbol, as_of_date=None, hours_back=48):
        articles = self.get_news_for_symbol(symbol, as_of_date=as_of_date, hours_back=hours_back)
        specific = [a for a in articles if a.get('is_specific', True)]
        has_cat = len(specific) > 0
        return has_cat, articles
