import requests
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Articles tagged with more symbols than this are likely roundups/listicles
MAX_SYMBOLS_FOR_SPECIFIC_NEWS = 5

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
