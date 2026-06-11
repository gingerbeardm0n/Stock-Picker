"""
Live VWAP Reclaim Runner
=========================
Paper/live trading for the VWAP Reclaim strategy (vwap_v1 trial 173).
Designed to run RIGHT AFTER the Opening Bell Scalp session in the same
scheduled job — scalp owns 9:30-9:40, this owns the 10:00-11:30 window.

Flow:
    ~9:55 (after scalp) - Connect, scan gappers via Tradier quotes,
                          fetch news via Alpaca, rank, take top-3 watchlist
    then  - Poll 1-min bars for all 3 symbols, build running VWAP per symbol
            from the 9:30 bars onward
    bars 10:00-11:30 - evaluate_entry() per bar (the engine itself enforces
            the window on BAR TIME, so the 15-min sandbox delay is harmless)
    on signal - place orders via TradierBroker; manage exits bar-by-bar
    bar time > 11:30 with no position - done for the day

Uses the SAME evaluate_entry/evaluate_exit as the simulator -- only the
data source differs.

Usage:
    python live_vwap_runner.py             # paper trading (default)
    python live_vwap_runner.py --live      # REAL MONEY
    python live_vwap_runner.py --dry-run   # log only, no orders
"""

from __future__ import annotations

import os
import sys
import argparse
import logging
import time
import queue
import threading
from datetime import datetime
from dataclasses import dataclass, field

import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from trading.vwap_models import VwapReclaimConfig, ENTRY_WINDOW_END, WATCH_TOP_N
from trading.vwap_engine import VwapAccumulator, evaluate_entry, evaluate_exit
from trading.scalp_ranker import rank_candidates
from trading.bar_capture import record_bar

ET = pytz.timezone('America/New_York')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


# ── vwap_v1 trial 173 (train 2021-23, selected 2024, sealed-2025 test:
#    151 trades, 90.1% WR, +$2,669, PF 4.76) ───────────────────────────────

TRIAL_173_CONFIG = VwapReclaimConfig(
    min_gap_pct=9.41,
    min_relative_volume=2.79,
    max_price=23.27,
    require_news=True,
    lookback_bars=8,
    min_bars_below=2,
    reclaim_vol_mult=1.91,
    entry_mode='reclaim_close',
    stop_vwap_offset=0.070,
    profit_target_pct=8.87,
    max_hold_bars=47,
    trailing_stop_pct=0.0,
    risk_pct=2.73,
    max_position_pct=37.90,
)


@dataclass
class LiveVwapState:
    """Mutable state for one trading day."""
    watchlist: list[dict] = field(default_factory=list)

    # Trade execution
    symbol: str = ''
    entry_price: float = 0.0
    stop_price: float = 0.0
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


class LiveVwapRunner:
    """Runs the VWAP Reclaim strategy live against Tradier."""

    def __init__(
        self,
        config: VwapReclaimConfig = None,
        dry_run: bool = False,
        live: bool = False,
    ):
        self.config = config or TRIAL_173_CONFIG
        self.dry_run = dry_run
        self.live = live
        self.state = LiveVwapState()

        # Load env (same convention as scalp runner)
        env_file = '.env.live' if live else '.env.paper'
        env_path = os.path.join(os.path.dirname(__file__), '..', env_file)
        if os.path.exists(env_path):
            self._load_env(env_path)

        # Paper mode: orders to sandbox, data feed on production token when
        # available (sandbox quotes are delayed and blind in premarket).
        self.data_delayed = not live and not bool(Config.TRADIER_PRODUCTION_TOKEN)
        if not live:
            from trading.broker.tradier import TradierBroker
            acct = Config.TRADIER_ACCOUNT_ID
            self.broker = None if dry_run else TradierBroker(
                token=Config.TRADIER_PAPER_TOKEN, account_id=acct, sandbox=True)
            self.data_feed = Config.get_data_feed()
            logger.info(f"Data feed: {'sandbox (15-min delayed)' if self.data_delayed else 'production (real-time)'}")
        else:
            self.broker = None if dry_run else Config.get_broker()
            self.data_feed = Config.get_data_feed()

        from backend.news_fetcher import NewsFetcher, classify_news_tier
        self.news_fetcher = NewsFetcher()
        self.classify_news_tier = classify_news_tier

        self._bar_queue = queue.Queue(maxsize=1000)

        logger.info("=" * 60)
        logger.info("VWAP RECLAIM RUNNER")
        logger.info("=" * 60)
        mode = "DRY RUN" if dry_run else ("LIVE" if live else "PAPER")
        logger.info(f"Mode: {mode}")
        logger.info(f"Config: gap>={self.config.min_gap_pct:.1f}% "
                    f"entry={self.config.entry_mode} "
                    f"stop=VWAP-{self.config.stop_vwap_offset:.2f} "
                    f"target={self.config.profit_target_pct:.1f}% "
                    f"hold<={self.config.max_hold_bars} bars")

        if not dry_run:
            balance = self.broker.get_account_balance()
            logger.info(f"Account balance: ${balance:,.2f}")

    # ── Phase 1: Gapper scan + watchlist ─────────────────────────────────────

    def scan_gappers(self):
        """Scan for gap-ups, enrich with news, rank, keep top-N watchlist."""
        logger.info("-" * 40)
        logger.info("PHASE 1: Gapper scan (VWAP watchlist)")
        logger.info("-" * 40)

        from trading.live_scalp_runner import LiveScalpRunner
        symbols = LiveScalpRunner._fetch_nasdaq_symbols()
        if not symbols:
            logger.warning("No symbol universe available.")
            return

        logger.info(f"Fetching quotes for {len(symbols):,} symbols...")
        quotes = self.data_feed.get_quotes(symbols)
        logger.info(f"Got {len(quotes):,} quotes")

        gappers = []
        for sym, q in quotes.items():
            if q.prev_close <= 0 or q.last <= 0:
                continue
            gap_pct = (q.last - q.prev_close) / q.prev_close * 100
            if gap_pct < self.config.min_gap_pct:
                continue
            if gap_pct > 1000:
                continue  # bad quote (sandbox sometimes returns garbage prev_close)
            if q.last > self.config.max_price:
                continue
            gappers.append({
                'symbol': sym,
                'gap_pct': gap_pct,
                'open_price': q.last,
                'prior_close': q.prev_close,
            })

        gappers.sort(key=lambda g: g['gap_pct'], reverse=True)
        logger.info(f"Found {len(gappers)} gappers >= {self.config.min_gap_pct:.1f}%")
        if not gappers:
            return

        top_gappers = gappers[:20]
        logger.info(f"Enriching top {len(top_gappers)} gappers with news...")
        self._enrich_with_news(top_gappers)

        filtered = []
        for g in top_gappers:
            if self.config.require_news and not g.get('has_news', False):
                logger.info(f"  SKIP {g['symbol']} gap={g['gap_pct']:.1f}% -- no news")
                continue
            g['rel_vol'] = 10.0       # no premarket rel-vol source live yet; high default
            g['float_shares'] = None
            filtered.append(g)

        if not filtered:
            logger.warning("No gappers passed news filter.")
            return

        self.state.watchlist = rank_candidates(filtered)[:WATCH_TOP_N]
        logger.info(f"\n>>> VWAP WATCHLIST ({len(self.state.watchlist)}):")
        for i, c in enumerate(self.state.watchlist):
            logger.info(f"  #{i+1} {c['symbol']:6s} gap={c['gap_pct']:.1f}% "
                        f"news={c.get('news_tier', '?')} score={c.get('scalp_score', 0):.3f}")

    # ── Phase 2: Bar-by-bar watch + trade ─────────────────────────────────────

    def execute(self):
        """Poll bars for the watchlist, enter on first reclaim, manage exits."""
        if not self.state.watchlist:
            logger.info("No watchlist — no VWAP trade today.")
            return

        symbols = [c['symbol'] for c in self.state.watchlist]
        by_symbol = {c['symbol']: c for c in self.state.watchlist}

        logger.info("-" * 40)
        logger.info(f"PHASE 2: Watching {symbols} for VWAP reclaim (window 10:00-11:30 bar time)")
        logger.info("-" * 40)

        from trading.broker.tradier import TradierBarPoller
        poller = TradierBarPoller(
            token=Config.TRADIER_PRODUCTION_TOKEN or Config.TRADIER_PAPER_TOKEN,
            sandbox=self.data_delayed,
            bar_queue=self._bar_queue,
        )
        poller.set_watchlist(symbols)
        poller_thread = threading.Thread(target=poller.start, daemon=True)
        poller_thread.start()

        # Per-symbol running state
        accs = {s: VwapAccumulator() for s in symbols}
        bars_hist: dict[str, list[dict]] = {s: [] for s in symbols}

        # Backfill session bars (9:30 ET onward) so VWAP covers the FULL session,
        # not just bars after watch start. Without this the accumulator misses
        # everything from 9:30 to now and computes a wrong VWAP.
        last_seeded: dict[str, datetime] = {}
        logger.info("Backfilling session bars for VWAP seed...")
        try:
            seed_bars = self.data_feed.get_bars_since_4am(symbols)
        except Exception as e:
            logger.warning(f"Session bar backfill failed: {e}")
            seed_bars = {}
        for sym, blist in seed_bars.items():
            for b in blist:
                b_et = b.time.astimezone(ET)
                if b_et.hour < 9 or (b_et.hour == 9 and b_et.minute < 30):
                    continue  # accumulator ignores premarket anyway; skip history too
                bar_dict = b.to_bar_dict()
                bar_dict['symbol'] = sym
                bar_dict['_et'] = b_et
                accs[sym].update(bar_dict)
                bars_hist[sym].append(bar_dict)
                last_seeded[sym] = b.time
                record_bar(sym, bar_dict, source='vwap_seed')
            v = accs[sym].value
            logger.info(f"  {sym}: seeded {len(bars_hist[sym])} session bars, "
                        f"VWAP={v:.2f}" if v else f"  {sym}: no session bars yet")

        window_end_min = ENTRY_WINDOW_END[0] * 60 + ENTRY_WINDOW_END[1]

        while not self.state.trade_done:
            try:
                bar = self._bar_queue.get(timeout=300)  # bars arrive ~1/min/symbol
            except queue.Empty:
                logger.warning("No bar received in 300s -- ending session")
                if self.state.in_position:
                    logger.warning("Timeout while IN POSITION — placing market exit")
                    self._place_exit(self.state.symbol,
                                     {'close': self.state.entry_price},
                                     {'reason': 'BAR_TIMEOUT_SAFETY_EXIT'})
                break

            sym = bar.get('symbol')
            if sym not in accs:
                continue

            bar_time = bar.get('time')
            if isinstance(bar_time, str):
                bar_time = datetime.fromisoformat(bar_time)
            bar_et = bar_time.astimezone(ET) if bar_time else None
            bar['_et'] = bar_et

            # Skip bars already covered by the session backfill seed
            seeded_until = last_seeded.get(sym)
            if seeded_until is not None and bar_time is not None and bar_time <= seeded_until:
                continue

            accs[sym].update(bar)
            bars_hist[sym].append(bar)

            if not self.state.in_position:
                bar_min = bar_et.hour * 60 + bar_et.minute if bar_et else 0
                # Past window with no entry -> done
                if bar_min > window_end_min:
                    logger.info(f"Bar time {bar_et.strftime('%H:%M')} past window end. No entry today.")
                    self.state.trade_done = True
                    break

                signal = evaluate_entry(by_symbol[sym], bars_hist[sym], accs[sym].value, self.config)
                if signal:
                    self._place_entry(sym, bar, signal)
            elif sym == self.state.symbol:
                self.state.bars_held += 1
                if float(bar['high']) > self.state.highest_since_entry:
                    self.state.highest_since_entry = float(bar['high'])

                exit_signal = evaluate_exit(
                    entry_price=self.state.entry_price,
                    stop_price=self.state.stop_price,
                    highest_since_entry=self.state.highest_since_entry,
                    current_bar=bar,
                    bars_held=self.state.bars_held,
                    config=self.config,
                )
                if exit_signal:
                    self._place_exit(sym, bar, exit_signal)

        poller.stop()
        self._print_summary()

    # ── Order placement (same pattern as scalp runner) ────────────────────────

    def _place_entry(self, symbol: str, bar: dict, signal: dict):
        entry_price = signal['entry_price']
        stop_price = signal['stop_price']
        account_balance = 5000.0

        if not self.dry_run:
            try:
                account_balance = self.broker.get_account_balance()
            except Exception:
                pass

        risk_per_share = max(entry_price - stop_price, entry_price * 0.005)
        risk_amount = account_balance * (self.config.risk_pct / 100)
        max_position_value = account_balance * (self.config.max_position_pct / 100)
        shares = min(int(risk_amount / risk_per_share),
                     int(max_position_value / entry_price))

        if shares <= 0:
            logger.warning("Position size = 0 shares. Skipping entry.")
            self.state.trade_done = True
            return

        logger.info(f">>> ENTRY: {shares} shares of {symbol} @ ${entry_price:.2f}")
        logger.info(f"    Reason: {signal.get('reason', '?')}")
        logger.info(f"    Stop: ${stop_price:.2f} (VWAP {signal.get('vwap', 0):.2f} - {self.config.stop_vwap_offset:.2f})")

        if not self.dry_run:
            result = self.broker.place_limit_buy(symbol, shares, entry_price)
            self.state.entry_order_id = result.order_id
            logger.info(f"    Order ID: {result.order_id} Status: {result.status}")

            time.sleep(2)
            fill = self.broker.get_order(result.order_id)
            for _ in range(5):
                if fill.status == 'filled':
                    break
                time.sleep(2)
                fill = self.broker.get_order(result.order_id)
            if fill.status == 'filled':
                entry_price = fill.filled_price
                shares = fill.filled_qty
                logger.info(f"    FILLED: {shares} @ ${entry_price:.2f}")
            else:
                logger.warning("    Entry not filled after 12s. Cancelling.")
                self.broker.cancel_order(result.order_id)
                self.state.trade_done = True
                return

            stop_result = self.broker.place_stop_sell(symbol, shares, round(stop_price, 2))
            self.state.stop_order_id = stop_result.order_id
            logger.info(f"    Stop order: {stop_result.order_id} @ ${stop_price:.2f}")

        self.state.in_position = True
        self.state.symbol = symbol
        self.state.entry_price = entry_price
        self.state.stop_price = stop_price
        self.state.shares = shares
        self.state.entry_time = datetime.now(ET)
        self.state.highest_since_entry = float(bar['high'])
        self.state.bars_held = 0

    def _place_exit(self, symbol: str, bar: dict, exit_signal: dict):
        exit_price = exit_signal.get('exit_price', float(bar['close']))

        logger.info(f">>> EXIT: {self.state.shares} shares of {symbol} @ ${exit_price:.2f}")
        logger.info(f"    Reason: {exit_signal.get('reason', '?')}")

        if not self.dry_run:
            if self.state.stop_order_id:
                try:
                    self.broker.cancel_order(self.state.stop_order_id)
                except Exception as e:
                    logger.warning(f"    Stop cancel failed (may have filled): {e}")

            result = self.broker.place_market_sell(symbol, self.state.shares)
            logger.info(f"    Sell order: {result.order_id} Status: {result.status}")
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

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _enrich_with_news(self, candidates: list[dict]):
        today = datetime.now(ET).date()
        for c in candidates:
            try:
                articles = self.news_fetcher.get_news_for_symbol(
                    c['symbol'], as_of_date=today, hours_back=48,
                )
                if articles:
                    tier = self.classify_news_tier(articles)
                    c['has_news'] = tier in ('tier1', 'tier2', 'presence')
                    c['news_tier'] = tier
                else:
                    c['has_news'] = False
                    c['news_tier'] = 'none'
            except Exception as e:
                logger.warning(f"News fetch failed for {c['symbol']}: {e}")
                c['has_news'] = False
                c['news_tier'] = 'none'
            time.sleep(0.35)

    def _load_env(self, path: str):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, val = line.split('=', 1)
                        os.environ.setdefault(key.strip(), val.strip())
        except Exception as e:
            logger.warning(f"Could not load {path}: {e}")

    def _print_summary(self):
        s = self.state
        logger.info("\n" + "=" * 60)
        logger.info("VWAP RECLAIM SUMMARY")
        logger.info("=" * 60)
        if s.entry_price > 0:
            logger.info(f"Symbol:     {s.symbol}")
            logger.info(f"Entry:      ${s.entry_price:.2f} ({s.shares} shares)")
            logger.info(f"Exit:       ${s.exit_price:.2f}")
            logger.info(f"P&L:        ${s.pnl:+.2f}")
            logger.info(f"Bars held:  {s.bars_held}")
            logger.info(f"Reason:     {s.exit_reason}")
        else:
            logger.info("Result:     NO TRADE")
        logger.info("=" * 60)


def run_vwap_session(dry_run=False, live=False) -> LiveVwapState:
    """
    Run a complete VWAP Reclaim session. Designed to be called right after
    run_scalp_session() in the same scheduled job — no internal start-time
    wait; entry timing is enforced on BAR TIME by the engine's 10:00-11:30
    window check.
    """
    runner = LiveVwapRunner(dry_run=dry_run, live=live)
    runner.scan_gappers()
    runner.execute()
    return runner.state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='VWAP Reclaim - Live Trading')
    parser.add_argument('--live', action='store_true', help='REAL MONEY trading')
    parser.add_argument('--dry-run', action='store_true', help='Log only, no orders')
    args = parser.parse_args()

    run_vwap_session(dry_run=args.dry_run, live=args.live)
