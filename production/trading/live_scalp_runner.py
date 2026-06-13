"""
Live Opening Bell Scalp Runner
===============================
Paper/live trading for the Opening Bell Scalp strategy (Trial 173).

Flow:
    9:00 AM  - Start up, connect to Tradier, log account balance
    9:00-9:25 - Scan for premarket gappers via Tradier quotes
               Fetch news for top gappers via Alpaca
               Rank candidates, display watchlist
    9:25     - Lock in #1 pick, start bar polling for that symbol
    9:30     - First bar arrives, run evaluate_entry()
    9:30-9:40 - Bar-by-bar entry/exit via scalp_engine
               Place orders via TradierBroker
    9:40     - Time stop if still in, done for the day

Usage:
    python live_scalp_runner.py                  # paper trading (default)
    python live_scalp_runner.py --live            # REAL MONEY
    python live_scalp_runner.py --dry-run         # log only, no orders
    python live_scalp_runner.py --start-time 9:15 # start scanning earlier
"""

from __future__ import annotations

import os
import sys
import argparse
import logging
import time
import queue
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass

import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from trading.scalp_models import ScalpConfig
from trading.scalp_engine import evaluate_entry, evaluate_exit, get_premarket_high
from trading.scalp_ranker import rank_candidates, get_top_candidate, ENRICH_TOP_N, MAX_GAP_PCT
from trading.bar_capture import record_news
from trading.broker.base import OrderResult

ET = pytz.timezone('America/New_York')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


# ── Trial 173 config (trained 2021-2022, validated 2023-2025) ────────────────

TRIAL_173_CONFIG = ScalpConfig(
    min_gap_pct=11.65,
    min_relative_volume=3.61,
    max_float=50_000_000,
    max_price=24.69,
    require_news=True,
    entry_mode='first_green',
    # PAPER-TESTING OVERRIDE: validated value is 4 (entry by 9:34). Extended to
    # 30 so the scalp keeps hunting until 10:00 bar time, when the VWAP Reclaim
    # window opens — more paper data per day. Restore to 4 before live money.
    max_entry_bars=30,
    min_pm_high_break_pct=0.09,
    profit_target_pct=9.88,
    stop_loss_pct=4.70,
    max_hold_bars=6,
    trailing_stop_pct=0.07,
    risk_pct=2.63,
    max_position_pct=48.63,
)


# ── Live state tracking ─────────────────────────────────────────────────────

@dataclass
class LiveScalpState:
    """Mutable state for one trading day."""
    # Pre-market
    candidates: list[dict] = None
    top_pick: dict | None = None

    # Trade execution
    entry_price: float = 0.0
    shares: int = 0
    entry_time: datetime | None = None
    entry_order_id: str = ''
    stop_order_id: str = ''
    highest_since_entry: float = 0.0
    bars_held: int = 0
    in_position: bool = False
    trade_done: bool = False

    # Results
    exit_price: float = 0.0
    exit_reason: str = ''
    pnl: float = 0.0

    def __post_init__(self):
        if self.candidates is None:
            self.candidates = []


# ── Main runner ──────────────────────────────────────────────────────────────

class LiveScalpRunner:
    """
    Runs the Opening Bell Scalp strategy live against Tradier.

    Uses the SAME evaluate_entry/evaluate_exit/rank_candidates functions
    as the simulator -- only the data source differs.
    """

    def __init__(
        self,
        config: ScalpConfig = None,
        dry_run: bool = False,
        live: bool = False,
    ):
        self.config = config or TRIAL_173_CONFIG
        self.dry_run = dry_run
        self.live = live
        self.state = LiveScalpState()

        # Load env
        env_file = '.env.live' if live else '.env.paper'
        env_path = os.path.join(os.path.dirname(__file__), '..', env_file)
        if os.path.exists(env_path):
            self._load_env(env_path)

        # Connect broker + data feed
        # Paper mode: orders go to sandbox, but the DATA FEED uses the
        # production token when available (sandbox quotes are 15-min delayed
        # AND blind in premarket — gap% reads 0% before 9:30, so the scan
        # never finds candidates). Falls back to the delayed sandbox feed
        # if no production token is set.
        self.data_delayed = not live and not bool(Config.TRADIER_PRODUCTION_TOKEN)
        # Engine clock delay: in paper mode the sandbox fills orders against
        # quotes that run 15 min behind real time. Even with the real-time
        # production data feed, the ENGINE must consume bars 15 min late so
        # the price it decides on matches the price the sandbox fills at.
        # Live mode: no delay.
        self.engine_delay_min = 0 if live else 15
        if not live:
            from trading.broker.tradier import TradierBroker
            acct = Config.TRADIER_ACCOUNT_ID
            if not dry_run:
                self.broker = TradierBroker(token=Config.TRADIER_PAPER_TOKEN,
                                            account_id=acct, sandbox=True)
            else:
                self.broker = None
            self.data_feed = Config.get_data_feed()
            logger.info(f"Data feed: {'sandbox (15-min delayed)' if self.data_delayed else 'production (real-time)'}")
        else:
            if not dry_run:
                self.broker = Config.get_broker()
            else:
                self.broker = None
            self.data_feed = Config.get_data_feed()

        # News fetcher (Alpaca -- free tier)
        from backend.news_fetcher import NewsFetcher, classify_news_tier
        self.news_fetcher = NewsFetcher()
        self.classify_news_tier = classify_news_tier

        # Symbol list for scanning
        self._symbols = self._load_symbols()

        # Bar queue for live bar polling
        self._bar_queue = queue.Queue(maxsize=1000)

        logger.info("=" * 60)
        logger.info("OPENING BELL SCALP RUNNER")
        logger.info("=" * 60)
        mode = "DRY RUN" if dry_run else ("LIVE" if live else "PAPER")
        logger.info(f"Mode: {mode}")
        logger.info(f"Config: gap>={self.config.min_gap_pct:.1f}% "
                     f"entry={self.config.entry_mode} "
                     f"stop={self.config.stop_loss_pct:.1f}% "
                     f"target={self.config.profit_target_pct:.1f}%")

        if not dry_run:
            balance = self.broker.get_account_balance()
            logger.info(f"Account balance: ${balance:,.2f}")

    # ── Phase 1: Premarket scan (9:00 - 9:25) ───────────────────────────────

    def scan_premarket(self):
        """
        Scan all symbols for gap-ups, fetch news, rank candidates.
        Call this at ~9:00-9:15 AM to build the watchlist.
        """
        logger.info("-" * 40)
        logger.info("PHASE 1: Premarket Gapper Scan")
        logger.info("-" * 40)

        # Step 1: Get quotes for all symbols (batched)
        logger.info(f"Fetching quotes for {len(self._symbols):,} symbols...")
        quotes = self.data_feed.get_quotes(self._symbols)
        logger.info(f"Got {len(quotes):,} quotes")

        # Step 2: Compute gaps
        gappers = []
        for sym, q in quotes.items():
            if q.prev_close <= 0 or q.last <= 0:
                continue
            gap_pct = (q.last - q.prev_close) / q.prev_close * 100

            if gap_pct < self.config.min_gap_pct:
                continue
            if gap_pct > MAX_GAP_PCT:
                continue  # bad quote (sandbox sometimes returns garbage prev_close)
            if q.last > self.config.max_price:
                continue

            gappers.append({
                'symbol': sym,
                'gap_pct': gap_pct,
                'open_price': q.last,  # current price as proxy for open
                'prior_close': q.prev_close,
                'bid': q.bid,
                'ask': q.ask,
            })

        gappers.sort(key=lambda g: g['gap_pct'], reverse=True)
        logger.info(f"Found {len(gappers)} gappers >= {self.config.min_gap_pct:.1f}%")

        if not gappers:
            logger.warning("No gappers found this scan.")
            return

        # Step 3: Enrich top 20 with news + fundamentals
        top_gappers = gappers[:ENRICH_TOP_N]
        logger.info(f"Enriching top {len(top_gappers)} gappers with news...")
        self._enrich_with_news(top_gappers)

        # Step 4: Apply filters
        filtered = []
        for g in top_gappers:
            if self.config.require_news and not g.get('has_news', False):
                logger.info(f"  SKIP {g['symbol']} gap={g['gap_pct']:.1f}% -- no news")
                continue
            filtered.append(g)

        if not filtered:
            logger.warning("No gappers passed news filter this scan.")
            return

        # Step 5: Rank and pick #1
        # Add rel_vol placeholder (will refine at 9:25 with volume data)
        for g in filtered:
            g['rel_vol'] = 10.0  # high default, refined later
            g['float_shares'] = None  # TODO: fetch from fundamentals

        ranked = rank_candidates(filtered)
        self.state.candidates = ranked

        logger.info(f"\n{'='*60}")
        logger.info("WATCHLIST (ranked)")
        logger.info(f"{'='*60}")
        for i, c in enumerate(ranked[:10]):
            news_str = c.get('news_tier', 'none')
            logger.info(
                f"  #{i+1} {c['symbol']:6s} "
                f"gap={c['gap_pct']:.1f}% "
                f"news={news_str} "
                f"score={c.get('scalp_score', 0):.3f}"
            )

        top = get_top_candidate(filtered)
        self.state.top_pick = top
        logger.info(f"\n>>> TOP PICK: {top['symbol']} "
                     f"gap={top['gap_pct']:.1f}% "
                     f"news={top.get('news_tier', '?')}")

    def refresh_top_pick(self):
        """
        Re-scan at 9:25 with updated prices/volume. Locks in final pick.
        """
        logger.info("-" * 40)
        logger.info("PHASE 1b: Refresh pick (9:25)")
        logger.info("-" * 40)

        if not self.state.candidates:
            logger.warning("No candidates to refresh.")
            return

        # Re-fetch quotes for candidates only
        symbols = [c['symbol'] for c in self.state.candidates]
        quotes = self.data_feed.get_quotes(symbols)

        for c in self.state.candidates:
            q = quotes.get(c['symbol'])
            if q:
                c['open_price'] = q.last
                # Recalculate gap with latest price
                if q.prev_close > 0:
                    c['gap_pct'] = (q.last - q.prev_close) / q.prev_close * 100

        # Re-rank
        ranked = rank_candidates(self.state.candidates)
        self.state.candidates = ranked
        top = get_top_candidate(ranked)

        if top:
            self.state.top_pick = top
            logger.info(f">>> LOCKED IN: {top['symbol']} "
                         f"gap={top['gap_pct']:.1f}% "
                         f"price=${top['open_price']:.2f}")
        else:
            logger.warning("No candidates after refresh. No trade today.")
            self.state.trade_done = True

    # ── Phase 2: Execute trade (9:30 - 9:40) ────────────────────────────────

    def execute_trade(self):
        """
        Monitor minute bars for the top pick, enter/exit per scalp_engine.
        Blocks until trade is done or max_hold_bars reached.
        """
        if self.state.trade_done or not self.state.top_pick:
            logger.info("No trade to execute today.")
            return

        symbol = self.state.top_pick['symbol']
        logger.info("-" * 40)
        logger.info(f"PHASE 2: Execute trade -- {symbol}")
        logger.info("-" * 40)

        # Fetch premarket bars to compute premarket high
        logger.info(f"Fetching premarket bars for {symbol}...")
        pm_bars_dict = self.data_feed.get_bars_since_4am([symbol])
        pm_bars = pm_bars_dict.get(symbol, [])

        if pm_bars:
            # Convert to dict format expected by get_premarket_high
            pm_bar_dicts = []
            for b in pm_bars:
                bar_et = b.time.astimezone(ET)
                if bar_et.hour < 9 or (bar_et.hour == 9 and bar_et.minute < 30):
                    pm_bar_dicts.append({
                        'open': b.open, 'high': b.high,
                        'low': b.low, 'close': b.close,
                        'volume': b.volume,
                    })
            premarket_high = get_premarket_high(pm_bar_dicts) if pm_bar_dicts else None
        else:
            premarket_high = None

        logger.info(f"Premarket high: ${premarket_high:.2f}" if premarket_high else
                     "Premarket high: N/A")

        # Start bar poller for this symbol
        from trading.broker.tradier import TradierBarPoller
        poller = TradierBarPoller(
            token=Config.TRADIER_PRODUCTION_TOKEN or Config.TRADIER_PAPER_TOKEN,
            sandbox=self.data_delayed,
            delay_minutes=self.engine_delay_min,
            bar_queue=self._bar_queue,
        )
        poller.set_watchlist([symbol])
        poller_thread = threading.Thread(target=poller.start, daemon=True)
        poller_thread.start()

        # Wait for 9:30 market open (sandbox: wait for 9:45 wall clock = 9:30 delayed)
        self._wait_for_market_open()

        # Process bars
        bars_since_open = 0
        logger.info(f"Listening for {symbol} bars...")

        while not self.state.trade_done:
            try:
                bar = self._bar_queue.get(timeout=180)  # 3 min timeout (sandbox bars arrive slowly)
            except queue.Empty:
                logger.warning("No bar received in 180s -- timeout")
                if self.state.in_position:
                    logger.warning("Timeout while IN POSITION — placing market exit")
                    self._place_exit(symbol, {'close': self.state.entry_price},
                                     {'reason': 'BAR_TIMEOUT_SAFETY_EXIT'})
                break

            if bar.get('symbol') != symbol:
                continue

            bar_time = bar.get('time', datetime.now(ET))
            if isinstance(bar_time, str):
                bar_time = datetime.fromisoformat(bar_time)

            # Skip premarket bars (poller uses session_filter='all'): they must
            # not count as bars_since_open or trigger first_green entries.
            bar_et = bar_time.astimezone(ET) if hasattr(bar_time, 'astimezone') else None
            if bar_et is not None and (bar_et.hour < 9 or (bar_et.hour == 9 and bar_et.minute < 30)):
                logger.info(f"  Premarket bar {bar_et.strftime('%H:%M')} "
                            f"C={bar['close']:.2f} V={bar.get('volume', 0):,} — data flowing, skipping")
                continue

            bars_since_open += 1

            logger.info(
                f"  Bar {bars_since_open}: "
                f"O={bar['open']:.2f} H={bar['high']:.2f} "
                f"L={bar['low']:.2f} C={bar['close']:.2f} "
                f"V={bar.get('volume', 0):,}"
            )

            if not self.state.in_position:
                # Try entry
                entry = evaluate_entry(
                    candidate=self.state.top_pick,
                    current_bar=bar,
                    premarket_high=premarket_high,
                    bars_since_open=bars_since_open,
                    config=self.config,
                )
                if entry:
                    self._place_entry(symbol, bar, entry)
                elif bars_since_open >= self.config.max_entry_bars:
                    logger.info(f"Max entry bars ({self.config.max_entry_bars}) reached. No entry.")
                    self.state.trade_done = True
            else:
                # Update tracking
                self.state.bars_held += 1
                if bar['high'] > self.state.highest_since_entry:
                    self.state.highest_since_entry = bar['high']

                # Check exit
                exit_signal = evaluate_exit(
                    entry_price=self.state.entry_price,
                    highest_since_entry=self.state.highest_since_entry,
                    current_bar=bar,
                    bars_held=self.state.bars_held,
                    config=self.config,
                )
                if exit_signal:
                    self._place_exit(symbol, bar, exit_signal)

        # Cleanup
        poller.stop()

        # Summary
        self._print_summary()

    # ── Order placement ──────────────────────────────────────────────────────

    def _place_entry(self, symbol: str, bar: dict, entry: dict):
        """Place entry order."""
        entry_price = bar['close']  # enter at bar close
        account_balance = 5000.0  # default

        if not self.dry_run:
            try:
                account_balance = self.broker.get_account_balance()
            except Exception:
                pass

        # Position sizing (same as sim)
        risk_amount = account_balance * (self.config.risk_pct / 100)
        stop_distance = entry_price * (self.config.stop_loss_pct / 100)
        shares_by_risk = int(risk_amount / stop_distance) if stop_distance > 0 else 0
        max_position_value = account_balance * (self.config.max_position_pct / 100)
        shares_by_position = int(max_position_value / entry_price) if entry_price > 0 else 0
        shares = min(shares_by_risk, shares_by_position)

        if shares <= 0:
            logger.warning("Position size = 0 shares. Skipping entry.")
            self.state.trade_done = True
            return

        logger.info(f">>> ENTRY: {shares} shares of {symbol} @ ${entry_price:.2f}")
        logger.info(f"    Reason: {entry.get('reason', '?')}")
        logger.info(f"    Risk: ${risk_amount:.2f} | Position: ${shares * entry_price:.2f}")

        if not self.dry_run:
            # Place limit buy at ask (aggressive entry)
            result = self.broker.place_limit_buy(symbol, shares, entry_price)
            self.state.entry_order_id = result.order_id
            logger.info(f"    Order ID: {result.order_id} Status: {result.status}")

            # Wait briefly for fill
            time.sleep(2)
            fill = self.broker.get_order(result.order_id)
            if fill.status == 'filled':
                entry_price = fill.filled_price
                shares = fill.filled_qty
                logger.info(f"    FILLED: {shares} @ ${entry_price:.2f}")
            else:
                logger.info(f"    Order status: {fill.status} -- waiting...")
                # Wait up to 10s for fill
                for _ in range(5):
                    time.sleep(2)
                    fill = self.broker.get_order(result.order_id)
                    if fill.status == 'filled':
                        entry_price = fill.filled_price
                        shares = fill.filled_qty
                        logger.info(f"    FILLED: {shares} @ ${entry_price:.2f}")
                        break
                else:
                    logger.warning("    Entry not filled after 10s. Cancelling.")
                    cancelled = self.broker.cancel_order(result.order_id)
                    # A cancel can race a fill — a failed cancel usually means
                    # the order already executed. Verify the order's final
                    # state; anything filled must be adopted and managed,
                    # never left as an orphan position with no stop.
                    time.sleep(2)
                    fill = self.broker.get_order(result.order_id)
                    if fill.status in ('filled', 'partially_filled') and fill.filled_qty > 0:
                        entry_price = fill.filled_price or entry_price
                        shares = fill.filled_qty
                        logger.warning(
                            f"    Cancel raced a fill ({fill.status}, cancel ok={cancelled}): "
                            f"{shares} @ ${entry_price:.2f} — adopting position."
                        )
                    else:
                        self.state.trade_done = True
                        return

            # Place stop loss order
            stop_price = round(entry_price * (1 - self.config.stop_loss_pct / 100), 2)
            stop_result = self.broker.place_stop_sell(symbol, shares, stop_price)
            self.state.stop_order_id = stop_result.order_id
            logger.info(f"    Stop order: {stop_result.order_id} @ ${stop_price:.2f}")

        self.state.in_position = True
        self.state.entry_price = entry_price
        self.state.shares = shares
        self.state.entry_time = datetime.now(ET)
        self.state.highest_since_entry = bar['high']
        self.state.bars_held = 0

    def _place_exit(self, symbol: str, bar: dict, exit_signal: dict):
        """Place exit order."""
        exit_price = exit_signal.get('exit_price', bar['close'])

        logger.info(f">>> EXIT: {self.state.shares} shares of {symbol} @ ${exit_price:.2f}")
        logger.info(f"    Reason: {exit_signal.get('reason', '?')}")

        if not self.dry_run:
            # Cancel existing stop order
            if self.state.stop_order_id:
                self.broker.cancel_order(self.state.stop_order_id)

            # Place market sell
            result = self.broker.place_market_sell(symbol, self.state.shares)
            logger.info(f"    Sell order: {result.order_id} Status: {result.status}")

            # Wait for fill
            time.sleep(2)
            fill = self.broker.get_order(result.order_id)
            if fill.status == 'filled':
                exit_price = fill.filled_price
                logger.info(f"    FILLED: {fill.filled_qty} @ ${exit_price:.2f}")

        self.state.exit_price = exit_price
        self.state.exit_reason = exit_signal.get('reason', '?')
        self.state.pnl = (exit_price - self.state.entry_price) * self.state.shares
        self.state.in_position = False
        self.state.trade_done = True

    # ── News enrichment ──────────────────────────────────────────────────────

    def _enrich_with_news(self, candidates: list[dict]):
        """Fetch news for each candidate via Alpaca API."""
        today = datetime.now(ET).date()
        for c in candidates:
            try:
                articles = self.news_fetcher.get_news_for_symbol(
                    c['symbol'],
                    as_of_date=today,
                    hours_back=48,
                )
                if articles:
                    tier = self.classify_news_tier(articles)
                    c['has_news'] = tier in ('tier1', 'tier2', 'presence')
                    c['news_tier'] = tier
                    record_news(c['symbol'], articles, tier)
                else:
                    c['has_news'] = False
                    c['news_tier'] = 'none'
            except Exception as e:
                logger.warning(f"News fetch failed for {c['symbol']}: {e}")
                c['has_news'] = False
                c['news_tier'] = 'none'

            # Rate limit
            time.sleep(0.35)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _wait_for_market_open(self):
        """Sleep until market open bars are available.

        Live (no engine delay): wait until 9:30 AM ET.
        Paper (engine delayed to match sandbox fills): wait until 9:30 + delay.
        """
        now = datetime.now(ET)
        target = (now.replace(hour=9, minute=30, second=0, microsecond=0)
                  + timedelta(minutes=self.engine_delay_min))

        if now >= target:
            logger.info(f"Market {'open (engine delayed)' if self.engine_delay_min else 'open'} — bars available.")
            return

        wait = (target - now).total_seconds()
        label = (f"{target.strftime('%H:%M')} ET (9:30 + {self.engine_delay_min}-min engine delay)"
                 if self.engine_delay_min else "9:30 AM ET")
        logger.info(f"Waiting {wait:.0f}s for {label}...")
        time.sleep(wait)
        logger.info("Market open — bars available!")

    def _load_symbols(self) -> list[str]:
        """Fetch fresh US stock universe from NASDAQ, then filter by live price."""
        symbols = self._fetch_nasdaq_symbols()
        if not symbols:
            # Fallback to static file
            paths = [
                os.path.join(os.path.dirname(__file__), '..', 'services', 'stocks_in_price_range.txt'),
                os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'stocks_1_to_20.txt'),
            ]
            for p in paths:
                if os.path.exists(p):
                    with open(p) as f:
                        symbols = [line.strip() for line in f if line.strip()]
                    logger.warning(f"Using static fallback: {len(symbols):,} symbols from {os.path.basename(p)}")
                    break

        if not symbols:
            logger.warning("No symbols available.")
            return []

        # Live-filter: keep only symbols with price $0.50-$30
        if self.data_feed:
            logger.info(f"Fetching live quotes for {len(symbols):,} symbols to filter by price...")
            quotes = self.data_feed.get_quotes(symbols)
            alive = [s for s, q in quotes.items() if 0.50 <= q.last <= 30.0]
            logger.info(f"Live universe: {len(alive):,} stocks in $0.50-$30 range")
            return alive

        return symbols

    @staticmethod
    def _fetch_nasdaq_symbols() -> list[str]:
        """Fetch full US stock list from NASDAQ trader (updated daily, free)."""
        import requests as req
        url = 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt'
        try:
            r = req.get(url, timeout=15)
            r.raise_for_status()
            lines = r.text.strip().split('\n')
            symbols = []
            for line in lines[1:-1]:  # skip header + footer
                parts = line.split('|')
                if len(parts) < 8:
                    continue
                sym = parts[1]
                is_etf = parts[5] == 'Y'
                is_test = parts[7] == 'Y'
                # Keep non-ETF, non-test, normal ticker symbols
                if (not is_etf and not is_test and sym and ' ' not in sym
                        and '$' not in sym and '.' not in sym and len(sym) <= 5):
                    symbols.append(sym)
            logger.info(f"Fetched {len(symbols):,} symbols from NASDAQ trader")
            return symbols
        except Exception as e:
            logger.warning(f"Failed to fetch NASDAQ symbol list: {e}")
            return []

    def _load_env(self, path: str):
        """Load .env file into os.environ."""
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, val = line.split('=', 1)
                        os.environ.setdefault(key.strip(), val.strip())
            logger.info(f"Loaded env from {os.path.basename(path)}")
        except Exception as e:
            logger.warning(f"Could not load {path}: {e}")

    def _print_summary(self):
        """Print end-of-day summary."""
        s = self.state
        logger.info("\n" + "=" * 60)
        logger.info("DAILY SUMMARY")
        logger.info("=" * 60)

        if s.top_pick:
            logger.info(f"Symbol:     {s.top_pick['symbol']}")
            logger.info(f"Gap:        {s.top_pick['gap_pct']:.1f}%")
            logger.info(f"News:       {s.top_pick.get('news_tier', '?')}")

        if s.entry_price > 0:
            logger.info(f"Entry:      ${s.entry_price:.2f} ({s.shares} shares)")
            logger.info(f"Exit:       ${s.exit_price:.2f}")
            logger.info(f"P&L:        ${s.pnl:+.2f}")
            logger.info(f"Bars held:  {s.bars_held}")
            logger.info(f"Reason:     {s.exit_reason}")
        else:
            logger.info("Result:     NO TRADE")

        logger.info("=" * 60)


# ── Main entry point ─────────────────────────────────────────────────────────

def run_scalp_session(dry_run=False, live=False, start_time='9:00'):
    """
    Run a complete scalp trading session.

    Can be called programmatically or from CLI.
    """
    runner = LiveScalpRunner(dry_run=dry_run, live=live)

    # Parse start time
    hour, minute = map(int, start_time.split(':'))
    now = datetime.now(ET)
    start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if now < start:
        wait = (start - now).total_seconds()
        logger.info(f"Waiting {wait:.0f}s until {start_time} ET to start scanning...")
        time.sleep(wait)

    # Phase 1: Premarket scan — rescan until 9:25 so late gappers still make
    # the watchlist. Every 60s while empty, every 5 min once we have candidates
    # (full scan = quotes for ~8k symbols + news, too heavy to run each minute).
    scan_cutoff = now.replace(hour=9, minute=25, second=0, microsecond=0)

    while True:
        runner.state.trade_done = False  # reset for rescan
        runner.scan_premarket()

        now = datetime.now(ET)
        if now >= scan_cutoff:
            if not runner.state.candidates:
                logger.info("9:25 ET reached, no gappers found. No trade today.")
                runner.state.trade_done = True
            break

        scan_interval = 300 if runner.state.candidates else 60
        next_scan = min(scan_interval, (scan_cutoff - now).total_seconds())
        logger.info(f"Rescanning in {next_scan:.0f}s...")
        time.sleep(next_scan)

    if not runner.state.trade_done:
        # Refresh at 9:25
        now = datetime.now(ET)
        refresh_time = now.replace(hour=9, minute=25, second=0, microsecond=0)
        if now < refresh_time:
            wait = (refresh_time - now).total_seconds()
            logger.info(f"Waiting {wait:.0f}s until 9:25 for final refresh...")
            time.sleep(wait)

        runner.refresh_top_pick()

    if not runner.state.trade_done:
        # Phase 2: Execute trade
        runner.execute_trade()

    return runner.state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Opening Bell Scalp - Live Trading')
    parser.add_argument('--live', action='store_true',
                        help='Use LIVE credentials (real money)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Log signals only, no orders placed')
    parser.add_argument('--start-time', default='9:00',
                        help='When to start scanning (HH:MM ET, default 9:00)')

    args = parser.parse_args()

    if args.live and not args.dry_run:
        print("\n" + "!" * 60)
        print("WARNING: LIVE TRADING MODE - REAL MONEY")
        print("!" * 60)
        confirm = input("Type 'YES' to confirm: ")
        if confirm != 'YES':
            print("Aborted.")
            sys.exit(0)

    state = run_scalp_session(
        dry_run=args.dry_run,
        live=args.live,
        start_time=args.start_time,
    )
