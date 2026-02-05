import requests
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class NewsFetcher:
    def __init__(self):
        # We'll use Alpaca's news endpoint (included in their API)
        # For more comprehensive news, you could add Benzinga, NewsAPI, etc.
        from alpaca.data.historical import NewsClient
        from config import Config

        self.news_client = NewsClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_SECRET_KEY
        )

    def get_news_for_symbol(self, symbol, hours_back=24):
        """Get recent news for a symbol"""
        try:
            from alpaca.data.requests import NewsRequest

            end = datetime.now()
            start = end - timedelta(hours=hours_back)

            request = NewsRequest(
                symbols=symbol,
                start=start,
                end=end,
                limit=10
            )

            news = self.news_client.get_news(request)

            return [{
                'headline': article.headline,
                'summary': article.summary,
                'url': article.url,
                'created_at': article.created_at
            } for article in news]

        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
            return []

    def has_catalyst(self, symbol):
        """Check if stock has recent news (potential catalyst)"""
        news = self.get_news_for_symbol(symbol, hours_back=24)
        return len(news) > 0, news
