from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from datetime import datetime, timedelta
from config import Config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AlpacaDataFeed:
    def __init__(self):
        logger.info(f"🔑 Initializing Alpaca API with key: {Config.ALPACA_API_KEY[:8]}...{Config.ALPACA_API_KEY[-4:]}")
        self.data_client = StockHistoricalDataClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_SECRET_KEY
        )
        self.trading_client = TradingClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_SECRET_KEY,
            paper=True
        )
        logger.info("✅ Alpaca API clients initialized")

    def get_active_stocks(self):
        """Get list of active, tradable stocks"""
        try:
            assets = self.trading_client.get_all_assets()
            # Filter for active, tradable US stocks
            active_stocks = [
                asset.symbol for asset in assets
                if asset.tradable and asset.status == 'active'
                and asset.exchange in ['NASDAQ', 'NYSE', 'ARCA']
            ]
            return active_stocks
        except Exception as e:
            logger.error(f"Error getting active stocks: {e}")
            return []

    def get_snapshot(self, symbols):
        """Get current snapshot for multiple symbols"""
        try:
            request = StockSnapshotRequest(symbol_or_symbols=symbols)
            snapshots = self.data_client.get_stock_snapshot(request)
            logger.debug(f"✅ Got snapshot for {symbols}")
            return snapshots
        except Exception as e:
            logger.error(f"❌ Error getting snapshots for {symbols}: {type(e).__name__}: {e}")
            return {}

    def get_premarket_data(self, symbol):
        """Get pre-market data for a symbol"""
        try:
            now = datetime.now()
            # Get today's pre-market (4am - 9:30am ET)
            start = now.replace(hour=4, minute=0, second=0, microsecond=0)
            end = now.replace(hour=9, minute=30, second=0, microsecond=0)

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=start,
                end=end
            )

            bars = self.data_client.get_stock_bars(request)

            if symbol in bars:
                symbol_bars = bars[symbol]
                if len(symbol_bars) > 0:
                    premarket_volume = sum([bar.volume for bar in symbol_bars])
                    open_price = symbol_bars[0].open
                    current_price = symbol_bars[-1].close
                    gain_pct = ((current_price - open_price) / open_price) * 100

                    return {
                        'volume': premarket_volume,
                        'gain_pct': gain_pct,
                        'open': open_price,
                        'current': current_price
                    }

            return None
        except Exception as e:
            logger.error(f"Error getting premarket data for {symbol}: {e}")
            return None

    def get_average_volume(self, symbol, days=20):
        """Calculate average daily volume over past N days"""
        try:
            end = datetime.now()
            start = end - timedelta(days=days)

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=start,
                end=end
            )

            bars = self.data_client.get_stock_bars(request)

            if symbol in bars:
                symbol_bars = bars[symbol]
                if len(symbol_bars) > 0:
                    avg_vol = sum([bar.volume for bar in symbol_bars]) / len(symbol_bars)
                    return avg_vol

            return None
        except Exception as e:
            logger.error(f"Error calculating average volume for {symbol}: {e}")
            return None
