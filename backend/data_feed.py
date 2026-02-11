from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from datetime import datetime, timedelta
from config import Config
import pytz
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
            paper=Config.ALPACA_PAPER_TRADING
        )
        trading_mode = "Paper Trading" if Config.ALPACA_PAPER_TRADING else "Live Trading"
        logger.info(f"✅ Alpaca API clients initialized ({trading_mode})")

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
                end=end,
                feed='sip'  # Use SIP feed (Premium subscription)
            )

            bars = self.data_client.get_stock_bars(request)

            if symbol in bars.data:
                symbol_bars = bars.data[symbol]
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
                end=end,
                feed='sip'  # Use SIP feed (Premium subscription)
            )

            bars = self.data_client.get_stock_bars(request)

            if symbol in bars.data:
                symbol_bars = bars.data[symbol]
                if len(symbol_bars) > 0:
                    avg_vol = sum([bar.volume for bar in symbol_bars]) / len(symbol_bars)
                    return avg_vol

            return None
        except Exception as e:
            logger.error(f"Error calculating average volume for {symbol}: {e}")
            return None

    def get_batch_snapshots(self, symbols, chunk_size=1000):
        """Get snapshots for a large list of symbols in batches.
        Each batch counts as 1 API request regardless of symbol count."""
        logger.info(f"📸 Fetching snapshots for {len(symbols)} symbols...")
        all_snapshots = {}
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i + chunk_size]
            try:
                logger.debug(f"  Batch {i // chunk_size + 1}: Requesting snapshots for {len(chunk)} symbols: {chunk[:5]}...")
                request = StockSnapshotRequest(symbol_or_symbols=chunk)
                snapshots = self.data_client.get_stock_snapshot(request)
                if snapshots:
                    all_snapshots.update(snapshots)
                    logger.info(f"Snapshots batch {i // chunk_size + 1}: {len(chunk)} requested, {len(snapshots)} returned")
                else:
                    logger.warning(f"Snapshots batch {i // chunk_size + 1}: Got empty response for {len(chunk)} symbols")
            except Exception as e:
                logger.error(f"Error fetching snapshot batch at index {i}: {e}", exc_info=True)
        logger.info(f"✓ Snapshots complete: {len(all_snapshots)} symbols have data")
        return all_snapshots

    def get_batch_daily_bars(self, symbols, days=20, chunk_size=500):
        """Get daily bars for multiple symbols in batches for avg volume calculation."""
        end = datetime.now()
        start = end - timedelta(days=days + 5)  # pad for weekends/holidays

        logger.info(f"📊 Fetching daily bars from {start.date()} to {end.date()} for {len(symbols)} symbols")

        all_bars = {}
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i + chunk_size]
            try:
                logger.debug(f"  Batch {i // chunk_size + 1}: Requesting bars for {len(chunk)} symbols: {chunk[:5]}...")
                request = StockBarsRequest(
                    symbol_or_symbols=chunk,
                    timeframe=TimeFrame.Day,
                    start=start,
                    end=end,
                    feed='sip'  # Use SIP feed (Premium subscription)
                )
                bars = self.data_client.get_stock_bars(request)

                if bars:
                    symbols_with_data = 0
                    for symbol in chunk:
                        if symbol in bars.data:
                            all_bars[symbol] = bars.data[symbol]
                            symbols_with_data += 1
                    logger.info(f"Daily bars batch {i // chunk_size + 1}: {len(chunk)} requested, {symbols_with_data} returned data")
                else:
                    logger.warning(f"Daily bars batch {i // chunk_size + 1}: Got empty response for {len(chunk)} symbols")
            except Exception as e:
                logger.error(f"Error fetching daily bars batch at index {i}: {e}", exc_info=True)

        logger.info(f"✓ Daily bars complete: {len(all_bars)} symbols have data")
        return all_bars

    def get_batch_premarket_bars(self, symbols, chunk_size=500, days_back=14, simulation_time=None):
        """Get premarket hour bars for multiple symbols.

        Args:
            days_back: Number of historical days to fetch (default 14)
            simulation_time: Optional datetime for testing with historical data

        Returns dict with:
        - 'today': today's PM bars (hourly)
        - 'historical': past N days of PM bars for RV calculation (hourly)
        """
        et = pytz.timezone('US/Eastern')

        # Use simulation time if provided, otherwise use real time
        if simulation_time:
            now_et = simulation_time if simulation_time.tzinfo else et.localize(simulation_time)
            logger.info(f"📅 SIMULATION MODE: Using {now_et.strftime('%Y-%m-%d %H:%M')} ET")
        else:
            now_et = datetime.now(et)

        # Skip if before 4am (unless simulating)
        if not simulation_time and now_et.hour < 4:
            logger.info("Pre-market has not started yet")
            return {'today': {}, 'historical': {}}

        # Today's premarket window
        today_start = now_et.replace(hour=4, minute=0, second=0, microsecond=0)
        today_end = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        if now_et < today_end:
            today_end = now_et

        # Historical premarket (past 30 days, same time window each day)
        hist_end = (now_et - timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
        hist_start = (now_et - timedelta(days=days_back)).replace(hour=4, minute=0, second=0, microsecond=0)

        today_bars = {}
        historical_bars = {}

        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i + chunk_size]
            batch_num = i // chunk_size + 1

            # Fetch today's PM
            try:
                logger.debug(f"  Batch {batch_num}: Requesting TODAY'S PM bars ({today_start.strftime('%H:%M')} - {today_end.strftime('%H:%M')} ET)")
                request = StockBarsRequest(
                    symbol_or_symbols=chunk,
                    timeframe=TimeFrame.Hour,
                    start=today_start.astimezone(pytz.utc).replace(tzinfo=None),
                    end=today_end.astimezone(pytz.utc).replace(tzinfo=None),
                    feed='sip'  # Use SIP feed (Premium subscription)
                )
                bars = self.data_client.get_stock_bars(request)

                # Debug logging
                logger.debug(f"  Today PM API response: bars={bars}, has data attr={hasattr(bars, 'data')}")
                if hasattr(bars, 'data'):
                    logger.debug(f"  bars.data keys: {list(bars.data.keys()) if bars.data else 'empty'}")
                    # Show sample data for first symbol
                    if bars.data:
                        first_symbol = list(bars.data.keys())[0] if bars.data else None
                        if first_symbol:
                            sample_bars = bars.data[first_symbol][:3] if len(bars.data[first_symbol]) > 3 else bars.data[first_symbol]
                            logger.debug(f"  Sample bars for {first_symbol}: {len(bars.data[first_symbol])} total, first 3: {sample_bars}")

                if bars:
                    symbols_with_data = 0
                    for symbol in chunk:
                        if symbol in bars.data:
                            today_bars[symbol] = bars.data[symbol]
                            symbols_with_data += 1
                    logger.info(f"Premarket today batch {batch_num}: {len(chunk)} requested, {symbols_with_data} returned data")
                else:
                    logger.warning(f"Premarket today batch {batch_num}: Got empty response")
            except Exception as e:
                logger.error(f"Error fetching today's PM bars batch {batch_num}: {e}", exc_info=True)

            # Fetch historical PM for relative volume
            try:
                logger.debug(f"  Batch {batch_num}: Requesting HISTORICAL PM bars (past {days_back} days, {hist_start.strftime('%Y-%m-%d')} to {hist_end.strftime('%Y-%m-%d')})")
                request = StockBarsRequest(
                    symbol_or_symbols=chunk,
                    timeframe=TimeFrame.Hour,
                    start=hist_start.astimezone(pytz.utc).replace(tzinfo=None),
                    end=hist_end.astimezone(pytz.utc).replace(tzinfo=None),
                    feed='sip'  # Use SIP feed (Premium subscription)
                )
                bars = self.data_client.get_stock_bars(request)

                # Debug logging
                logger.debug(f"  Historical PM API response: bars={bars}, has data attr={hasattr(bars, 'data')}")
                if hasattr(bars, 'data'):
                    logger.debug(f"  bars.data keys: {list(bars.data.keys())[:5] if bars.data else 'empty'} (showing first 5)")
                    # Show sample data for first symbol
                    if bars.data:
                        first_symbol = list(bars.data.keys())[0] if bars.data else None
                        if first_symbol:
                            sample_bars = bars.data[first_symbol][:3] if len(bars.data[first_symbol]) > 3 else bars.data[first_symbol]
                            logger.debug(f"  Sample bars for {first_symbol}: {len(bars.data[first_symbol])} total bars over {days_back} days")
                            logger.debug(f"  First 3 bars: {sample_bars}")

                if bars:
                    symbols_with_data = 0
                    for symbol in chunk:
                        if symbol in bars.data:
                            historical_bars[symbol] = bars.data[symbol]
                            symbols_with_data += 1
                    logger.info(f"Premarket historical batch {batch_num}: {len(chunk)} requested, {symbols_with_data} returned data")
                else:
                    logger.warning(f"Premarket historical batch {batch_num}: Got empty response")
            except Exception as e:
                logger.error(f"Error fetching historical PM bars batch {batch_num}: {e}", exc_info=True)

        return {'today': today_bars, 'historical': historical_bars}

    def get_batch_premarket_volume(self, symbols, days_back=14, simulation_time=None, chunk_size=500):
        """
        Get premarket volumes for multiple symbols.
        Wrapper around get_batch_premarket_bars() that processes bars into volumes.

        Args:
            days_back: Number of historical days to fetch (default 14)

        Returns dict with format:
        {
            'SYMBOL': {
                'today': total_pm_volume_int,
                'historical': {date: pm_volume, ...}
            }
        }
        """
        et = pytz.timezone('US/Eastern')

        logger.info(f"📊 Fetching premarket volumes for {len(symbols)} symbols (past {days_back} days)")

        # Get raw bar data
        bars_data = self.get_batch_premarket_bars(symbols, chunk_size, days_back, simulation_time)
        today_bars = bars_data['today']
        historical_bars = bars_data['historical']

        # Debug: Log what we got
        logger.info(f"  Raw bar data received: {len(today_bars)} symbols with today bars, {len(historical_bars)} with historical")
        if len(symbols) <= 10:  # Only log details for small batches
            logger.debug(f"  Today bars symbols: {list(today_bars.keys())}")
            logger.debug(f"  Historical bars symbols: {list(historical_bars.keys())}")

        premarket_volumes = {}

        # Process each symbol
        for symbol in symbols:
            try:
                result = {
                    'today': 0,
                    'historical': {}
                }

                # Calculate today's PM volume
                if symbol in today_bars:
                    symbol_today_bars = today_bars[symbol]
                    today_volume = sum(bar.volume for bar in symbol_today_bars)
                    result['today'] = int(today_volume)

                # Calculate historical PM volumes by date
                if symbol in historical_bars:
                    symbol_hist_bars = historical_bars[symbol]

                    # Group bars by date and sum volumes
                    # Note: With hourly bars, we just sum all bars in the requested range
                    # since Alpaca only returns bars within the time window we specified
                    volumes_by_date = {}

                    for bar in symbol_hist_bars:
                        # Convert bar timestamp to ET timezone
                        bar_time = bar.timestamp
                        if bar_time.tzinfo is None:
                            bar_time = pytz.utc.localize(bar_time)
                        bar_time_et = bar_time.astimezone(et)
                        bar_date = bar_time_et.date()

                        # Sum volume for each date
                        if bar_date not in volumes_by_date:
                            volumes_by_date[bar_date] = 0
                        volumes_by_date[bar_date] += bar.volume

                    result['historical'] = {date: int(vol) for date, vol in volumes_by_date.items()}

                    # Debug logging for first few symbols
                    if len(symbols) <= 10:
                        logger.debug(f"  {symbol}: Aggregated {len(symbol_hist_bars)} bars into {len(volumes_by_date)} days")

                # Only add to results if we have some data
                if result['today'] > 0 or result['historical']:
                    premarket_volumes[symbol] = result
                    logger.debug(f"  {symbol}: today_pm_vol={result['today']:,}, historical_days={len(result['historical'])}")
                else:
                    logger.debug(f"  {symbol}: No PM data (today={result['today']}, hist_days={len(result['historical'])})")

            except Exception as e:
                logger.warning(f"Error processing PM volume for {symbol}: {e}")

        logger.info(f"✓ Premarket volumes complete: {len(premarket_volumes)} symbols have data")
        return premarket_volumes
