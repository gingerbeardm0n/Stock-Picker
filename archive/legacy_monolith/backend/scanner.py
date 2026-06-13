import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from backend.data_feed import AlpacaDataFeed
from backend.news_fetcher import NewsFetcher
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

class MomentumScanner:
    def __init__(self):
        self.data_feed = AlpacaDataFeed()
        self.news_fetcher = NewsFetcher()
        self.criteria = Config.SCANNER_CRITERIA
        logger.info(f"📡 Using Alpaca Premium data feed")

    def scan_stock(self, symbol):
        """Scan a single stock against criteria"""
        try:
            logger.info(f"🔍 Scanning {symbol}...")

            # Get snapshot
            snapshot_data = self.data_feed.get_snapshot([symbol])

            if not snapshot_data or symbol not in snapshot_data:
                logger.warning(f"  ❌ {symbol}: No snapshot data available")
                return None

            snapshot = snapshot_data[symbol]

            # Check price range
            current_price = snapshot.latest_trade.price
            logger.info(f"  💰 {symbol}: Price ${current_price:.2f}")

            if current_price < self.criteria['min_price'] or current_price > self.criteria['max_price']:
                logger.info(f"  ❌ {symbol}: Price ${current_price:.2f} outside range ${self.criteria['min_price']}-${self.criteria['max_price']}")
                return None

            # Get pre-market data
            premarket = self.data_feed.get_premarket_data(symbol)
            if not premarket:
                logger.warning(f"  ❌ {symbol}: No premarket data available")
                return None

            logger.info(f"  📊 {symbol}: Premarket gain {premarket['gain_pct']:.2f}%, volume {premarket['volume']:,}")

            # Check pre-market volume
            if premarket['volume'] < self.criteria['min_premarket_volume']:
                logger.info(f"  ❌ {symbol}: Premarket volume {premarket['volume']:,} < {self.criteria['min_premarket_volume']:,}")
                return None

            # Check pre-market gain
            if premarket['gain_pct'] < self.criteria['min_premarket_gain_pct']:
                logger.info(f"  ❌ {symbol}: Premarket gain {premarket['gain_pct']:.2f}% < {self.criteria['min_premarket_gain_pct']}%")
                return None

            # Get average volume
            avg_volume = self.data_feed.get_average_volume(symbol)
            if not avg_volume:
                logger.warning(f"  ❌ {symbol}: Could not calculate average volume")
                return None

            logger.info(f"  📈 {symbol}: Avg volume {int(avg_volume):,}")

            # NOTE: We don't filter on average volume anymore.
            # Low average volume + high current volume = strong momentum signal.

            # Calculate relative volume
            current_volume = snapshot.latest_trade.volume if hasattr(snapshot.latest_trade, 'volume') else premarket['volume']
            relative_volume = current_volume / avg_volume if avg_volume > 0 else 0

            logger.info(f"  📊 {symbol}: Relative volume {relative_volume:.2f}x")

            if relative_volume < self.criteria['min_relative_volume']:
                logger.info(f"  ❌ {symbol}: Relative volume {relative_volume:.2f}x < {self.criteria['min_relative_volume']}x")
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

    def update_criteria(self, new_criteria):
        """Update scanner criteria with new values."""
        self.criteria.update(new_criteria)
        logger.info(f"Scanner criteria updated: {self.criteria}")

    def run_full_scan(self, progress_callback=None, simulation_time=None):
        """Run a full-universe batch scan with progressive filtering.

        Args:
            simulation_time: Optional datetime for testing with historical data

        Pipeline: all assets -> price filter -> avg volume filter ->
                  premarket filter -> relative volume filter -> news lookup
        """
        import time

        scan_start = time.time()

        def report(stage, msg, pct):
            elapsed = time.time() - scan_start
            logger.info(f"[Stage {stage}] [{elapsed:.1f}s] {msg}")
            if progress_callback:
                progress_callback(stage, msg, pct)

        # Stage 1: Get all tradable symbols
        try:
            report(1, "Fetching all tradable assets...", 5)
            stage_start = time.time()
            all_symbols = self.data_feed.get_active_stocks()
            stage_time = time.time() - stage_start

            if not all_symbols:
                logger.error("❌ No active stocks returned from API")
                return []

            report(1, f"✓ Found {len(all_symbols):,} tradable assets ({stage_time:.1f}s)", 10)
        except Exception as e:
            logger.error(f"❌ Stage 1 failed: {type(e).__name__}: {e}", exc_info=True)
            raise

        # Stage 2: Batch snapshots -> filter by price range
        try:
            report(2, f"Fetching snapshots for {len(all_symbols):,} symbols...", 15)
            stage_start = time.time()
            snapshots = self.data_feed.get_batch_snapshots(all_symbols)
            stage_time = time.time() - stage_start

            price_qualified = {}
            no_price_data = 0
            for symbol, snap in snapshots.items():
                try:
                    if snap.latest_trade and snap.latest_trade.price:
                        price = snap.latest_trade.price
                        if self.criteria['min_price'] <= price <= self.criteria['max_price']:
                            price_qualified[symbol] = snap
                    else:
                        no_price_data += 1
                except Exception:
                    no_price_data += 1

            sample_symbols = list(price_qualified.keys())[:10]
            logger.info(f"  Got {len(snapshots):,} snapshots, {no_price_data:,} had no price data, "
                       f"{len(price_qualified):,} in target range. Sample: {sample_symbols}")
            report(2, f"✓ {len(price_qualified):,} stocks in ${self.criteria['min_price']}-${self.criteria['max_price']} range ({stage_time:.1f}s)", 40)

            if not price_qualified:
                logger.warning("⚠️ No stocks in price range!")
                return []
        except Exception as e:
            logger.error(f"❌ Stage 2 failed: {type(e).__name__}: {e}", exc_info=True)
            raise

        # Stage 3: Batch daily bars -> avg volume filter
        try:
            qualified_symbols = list(price_qualified.keys())
            report(3, f"Fetching 20-day volume data for {len(qualified_symbols):,} stocks...", 45)
            stage_start = time.time()
            daily_bars = self.data_feed.get_batch_daily_bars(qualified_symbols)
            stage_time = time.time() - stage_start

            volume_data = {}
            volume_qualified = []
            no_vol_data = 0

            for symbol in qualified_symbols:
                if symbol in daily_bars and len(daily_bars[symbol]) > 0:
                    bars = daily_bars[symbol]
                    avg_vol = sum(bar.volume for bar in bars) / len(bars)
                    volume_data[symbol] = avg_vol
                    volume_qualified.append(symbol)
                else:
                    no_vol_data += 1

            logger.info(f"  Got volume for {len(daily_bars):,} stocks, {no_vol_data:,} no data, "
                       f"{len(volume_qualified):,} passed")
            report(3, f"✓ {len(volume_qualified):,} stocks passed avg volume filter ({stage_time:.1f}s)", 60)

            if not volume_qualified:
                logger.warning("⚠️ No stocks passed volume filter!")
                return []
        except Exception as e:
            logger.error(f"❌ Stage 3 failed: {type(e).__name__}: {e}", exc_info=True)
            raise

        # Stage 4: Batch premarket data and calculate metrics (NO FILTERING)
        try:
            report(4, f"Fetching premarket data for {len(volume_qualified):,} stocks (hour bars, 14 days)...", 65)
            logger.info(f"  ⏱️ This may take 30-90 seconds for {len(volume_qualified):,} stocks...")
            stage_start = time.time()
            pm_volumes = self.data_feed.get_batch_premarket_volume(volume_qualified, simulation_time=simulation_time)
            stage_time = time.time() - stage_start

            logger.info(f"  ✓ Premarket data fetched in {stage_time:.1f}s ({len(pm_volumes):,} symbols have PM data)")

            if stage_time > 60:
                logger.warning(f"  ⚠️ Slow PM data fetch: {stage_time:.1f}s (expected <60s)")

        except Exception as e:
            logger.error(f"❌ Stage 4 PM data fetch failed: {type(e).__name__}: {e}", exc_info=True)
            raise

        # Calculate metrics for all stocks
        try:
            results = []
            for symbol in volume_qualified:
                snap = price_qualified[symbol]
                avg_daily_vol = volume_data[symbol]
                current_price = snap.latest_trade.price

                # Calculate PM gain from yesterday's close
                yesterday_close = 0
                if symbol in daily_bars and len(daily_bars[symbol]) > 0:
                    yesterday_close = float(daily_bars[symbol][-1].close)

                pm_gain_pct = ((current_price - yesterday_close) / yesterday_close * 100) if yesterday_close > 0 else 0

                # Get PM volume data
                pm_volume = 0
                avg_pm_volume = 0
                relative_volume = 0

                if symbol in pm_volumes:
                    pm_data = pm_volumes[symbol]
                    pm_volume = pm_data.get('today', 0)

                    # Calculate relative volume from historical data
                    historical_pm_vols = pm_data.get('historical', {})
                    if historical_pm_vols and len(historical_pm_vols) > 0:
                        avg_pm_volume = sum(historical_pm_vols.values()) / len(historical_pm_vols)
                        relative_volume = pm_volume / avg_pm_volume if avg_pm_volume > 0 else 0

                # Add all stocks to results with calculated metrics
                results.append({
                    'symbol': symbol,
                    'price': round(current_price, 2),
                    'premarket_gain_pct': round(pm_gain_pct, 2),
                    'premarket_volume': int(pm_volume),
                    'avg_pm_volume': int(avg_pm_volume),
                    'avg_volume': int(avg_daily_vol),
                    'relative_volume': round(relative_volume, 2),
                    'has_news': False,
                    'news_count': 0,
                    'news': [],
                    'bid': snap.latest_quote.bid_price if snap.latest_quote else None,
                    'ask': snap.latest_quote.ask_price if snap.latest_quote else None,
                    'spread': round(snap.latest_quote.ask_price - snap.latest_quote.bid_price, 4)
                        if snap.latest_quote and snap.latest_quote.bid_price and snap.latest_quote.ask_price
                        else None
                })

            report(4, f"✓ Calculated metrics for {len(results):,} stocks", 80)
        except Exception as e:
            logger.error(f"❌ Stage 4 metrics calculation failed: {type(e).__name__}: {e}", exc_info=True)
            raise

        # Stage 5: Sort by relative volume (skip news lookup for large datasets)
        try:
            results.sort(key=lambda x: (x['relative_volume'], x['premarket_gain_pct']), reverse=True)
            total_time = time.time() - scan_start

            # Log scan summary
            logger.info("=" * 60)
            logger.info(f"✅ SCAN COMPLETE")
            logger.info(f"  Total Time: {total_time:.1f}s")
            logger.info(f"  Total Stocks Scanned: {len(all_symbols):,}")
            logger.info(f"  In Price Range: {len(price_qualified):,}")
            logger.info(f"  Passed Volume Filter: {len(volume_qualified):,}")
            logger.info(f"  With Metrics: {len(results):,}")
            if results:
                logger.info(f"  Top RV: {results[0]['symbol']} ({results[0]['relative_volume']:.2f}x)")
                logger.info(f"  Top Gain: {max(results, key=lambda x: x['premarket_gain_pct'])['symbol']} ({max(results, key=lambda x: x['premarket_gain_pct'])['premarket_gain_pct']:.2f}%)")
            logger.info("=" * 60)

            report(5, f"✅ Scan complete: {len(results):,} stocks with metrics ({total_time:.1f}s total)", 100)
            return results
        except Exception as e:
            logger.error(f"❌ Stage 5 failed: {type(e).__name__}: {e}", exc_info=True)
            raise

    def run_debug_scan(self, symbols, simulation_time=None):
        """Debug scan that returns ALL calculated values without filtering.

        Returns raw data for diagnostics:
        - Price, PM Volume, PM Gain %, Relative Volume
        - Shows which filter stage each stock failed at
        """
        logger.info(f"🔍 Starting DEBUG scan for {len(symbols)} stocks...")

        # Stage 1: Get snapshots
        snapshots = self.data_feed.get_batch_snapshots(symbols)

        # Stage 2: Get daily bars for avg volume
        daily_bars = self.data_feed.get_batch_daily_bars(symbols)

        # Stage 3: Get premarket volumes
        pm_volumes = self.data_feed.get_batch_premarket_volume(symbols, simulation_time=simulation_time)

        debug_results = []

        for symbol in symbols:
            result = {
                'symbol': symbol,
                'price': None,
                'pm_volume': None,
                'pm_gain_pct': None,
                'relative_volume': None,
                'avg_volume': None,
                'failed_at': 'Calculated (no filters)',
                'passes': True  # Always pass - we're just calculating
            }

            logger.info(f"\n{'='*60}")
            logger.info(f"CALCULATING: {symbol}")
            logger.info(f"{'='*60}")

            # ========== 1. PRICE ==========
            if symbol not in snapshots or not snapshots[symbol].latest_trade:
                logger.warning(f"{symbol}: No snapshot data - skipping")
                result['failed_at'] = 'No snapshot data'
                result['passes'] = False
                debug_results.append(result)
                continue

            snap = snapshots[symbol]
            result['price'] = round(snap.latest_trade.price, 3)
            logger.info(f"{symbol}: [1/4] Price = ${result['price']}")

            # ========== 2. AVERAGE VOLUME (20-day) ==========
            if symbol not in daily_bars or len(daily_bars[symbol]) == 0:
                logger.warning(f"{symbol}: No daily bars data - cannot calculate avg volume")
                result['failed_at'] = 'No daily bars data'
                result['passes'] = False
                debug_results.append(result)
                continue

            bars = daily_bars[symbol]

            # ========== 2. PREMARKET VOLUME & GAIN ==========
            if symbol not in pm_volumes:
                logger.warning(f"{symbol}: No premarket data - cannot calculate PM metrics")
                result['pm_volume'] = 0
                result['pm_gain_pct'] = 0
                result['avg_volume'] = 0
                result['relative_volume'] = 0
                logger.info(f"{symbol}: [2/4] Premarket Volume = 0 (no data)")
                logger.info(f"{symbol}: [2/4] Premarket Gain = 0.00% (no data)")
                logger.info(f"{symbol}: [3/4] Average PM Volume = 0 (no data)")
                logger.info(f"{symbol}: [4/4] Relative Volume = 0.00x (no data)")
                debug_results.append(result)
                continue

            pm_data = pm_volumes[symbol]
            pm_volume = pm_data.get('today', 0)
            result['pm_volume'] = int(pm_volume)
            logger.info(f"{symbol}: [2/4] Premarket Volume = {int(pm_volume):,}")

            # Calculate PM gain from yesterday close to current price
            pm_gain_pct = 0
            current_price = result['price']
            if len(bars) > 0:
                yesterday_close = float(bars[-1].close)  # Last complete trading day
                pm_gain_pct = ((current_price - yesterday_close) / yesterday_close * 100) if yesterday_close > 0 else 0
                logger.info(f"{symbol}: [2/4] Premarket Gain = {pm_gain_pct:.2f}% (yesterday: ${yesterday_close:.2f} → current: ${current_price:.2f})")
            else:
                logger.warning(f"{symbol}: Cannot calc PM gain - no daily bars data")
                logger.info(f"{symbol}: [2/4] Premarket Gain = 0.00% (insufficient data)")

            result['pm_gain_pct'] = round(pm_gain_pct, 2)

            # ========== 3. AVERAGE PM VOLUME (at this time of day) ==========
            historical_pm_vols = pm_data.get('historical', {})

            if historical_pm_vols and len(historical_pm_vols) > 0:
                avg_pm_volume = sum(historical_pm_vols.values()) / len(historical_pm_vols)
                result['avg_volume'] = int(avg_pm_volume)
                logger.info(f"{symbol}: [3/4] Average PM Volume = {int(avg_pm_volume):,} ({len(historical_pm_vols)} days at {simulation_time.strftime('%H:%M')})")
            else:
                avg_pm_volume = 0
                result['avg_volume'] = 0
                logger.warning(f"{symbol}: Cannot calc avg PM volume - no historical PM data")
                logger.info(f"{symbol}: [3/4] Average PM Volume = 0 (no historical data)")

            # ========== 4. RELATIVE VOLUME ==========
            relative_volume = 0

            if avg_pm_volume > 0:
                relative_volume = pm_volume / avg_pm_volume
                logger.info(f"{symbol}: [4/4] Relative Volume = {relative_volume:.2f}x")
                logger.info(f"{symbol}:       → Today PM: {pm_volume:,} / Avg PM: {int(avg_pm_volume):,} = {relative_volume:.2f}x")
            else:
                logger.warning(f"{symbol}: Cannot calc relative volume - avg PM volume is 0")
                logger.info(f"{symbol}: [4/4] Relative Volume = 0.00x (no avg PM volume)")

            result['relative_volume'] = round(relative_volume, 2)

            # Summary
            logger.info(f"{symbol}: ✓ CALCULATION COMPLETE")
            logger.info(f"{symbol}: Summary:")
            logger.info(f"{symbol}:   Price: ${result['price']}")
            logger.info(f"{symbol}:   PM Volume (today): {result['pm_volume']:,}")
            logger.info(f"{symbol}:   PM Gain: {result['pm_gain_pct']:.2f}%")
            logger.info(f"{symbol}:   Avg PM Volume (at {simulation_time.strftime('%H:%M')}): {result['avg_volume']:,}")
            logger.info(f"{symbol}:   Relative Volume: {result['relative_volume']:.2f}x")

            debug_results.append(result)

        logger.info(f"✓ Debug scan complete: {sum(1 for r in debug_results if r['passes'])} passed, "
                   f"{sum(1 for r in debug_results if not r['passes'])} failed")
        return debug_results
