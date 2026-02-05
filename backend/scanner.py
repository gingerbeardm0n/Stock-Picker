from data_feed import AlpacaDataFeed
from news_fetcher import NewsFetcher
from config import Config
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

class MomentumScanner:
    def __init__(self):
        self.data_feed = AlpacaDataFeed()
        self.news_fetcher = NewsFetcher()
        self.criteria = Config.SCANNER_CRITERIA

    def scan_stock(self, symbol):
        """Scan a single stock against criteria"""
        try:
            # Get snapshot
            snapshot_data = self.data_feed.get_snapshot([symbol])

            if not snapshot_data or symbol not in snapshot_data:
                return None

            snapshot = snapshot_data[symbol]

            # Check price range
            current_price = snapshot.latest_trade.price
            if current_price < self.criteria['min_price'] or current_price > self.criteria['max_price']:
                return None

            # Get pre-market data
            premarket = self.data_feed.get_premarket_data(symbol)
            if not premarket:
                return None

            # Check pre-market volume
            if premarket['volume'] < self.criteria['min_premarket_volume']:
                return None

            # Check pre-market gain
            if premarket['gain_pct'] < self.criteria['min_premarket_gain_pct']:
                return None

            # Get average volume
            avg_volume = self.data_feed.get_average_volume(symbol)
            if not avg_volume:
                return None

            # Check average volume range
            if avg_volume < self.criteria['min_avg_volume'] or avg_volume > self.criteria['max_avg_volume']:
                return None

            # Calculate relative volume
            current_volume = snapshot.latest_trade.volume if hasattr(snapshot.latest_trade, 'volume') else premarket['volume']
            relative_volume = current_volume / avg_volume if avg_volume > 0 else 0

            if relative_volume < self.criteria['min_relative_volume']:
                return None

            # Check for news/catalyst
            has_news, news_items = self.news_fetcher.has_catalyst(symbol)

            # Compile stock data
            stock_data = {
                'symbol': symbol,
                'price': current_price,
                'premarket_gain_pct': round(premarket['gain_pct'], 2),
                'premarket_volume': premarket['volume'],
                'avg_volume': int(avg_volume),
                'relative_volume': round(relative_volume, 2),
                'has_news': has_news,
                'news_count': len(news_items),
                'news': news_items[:3] if news_items else [],  # Top 3 news items
                'bid': snapshot.latest_quote.bid_price if snapshot.latest_quote else None,
                'ask': snapshot.latest_quote.ask_price if snapshot.latest_quote else None,
                'spread': round(snapshot.latest_quote.ask_price - snapshot.latest_quote.bid_price, 4) if snapshot.latest_quote else None
            }

            logger.info(f"✓ {symbol} passed scan criteria")
            return stock_data

        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}")
            return None

    def run_scan(self, symbol_list=None):
        """Run the scanner on a list of symbols or all active stocks"""
        logger.info("Starting momentum scan...")

        if symbol_list is None:
            symbol_list = self.data_feed.get_active_stocks()
            logger.info(f"Scanning {len(symbol_list)} active stocks")

        results = []

        # Use threading for parallel scanning (faster)
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_symbol = {
                executor.submit(self.scan_stock, symbol): symbol
                for symbol in symbol_list
            }

            for future in as_completed(future_to_symbol):
                result = future.result()
                if result:
                    results.append(result)

        # Sort by pre-market gain percentage
        results.sort(key=lambda x: x['premarket_gain_pct'], reverse=True)

        logger.info(f"Scan complete. Found {len(results)} matching stocks")
        return results
