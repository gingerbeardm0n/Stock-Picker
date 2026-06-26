"""
Live Micro-Pullback Runner
===========================
Paper/live trading for the Micro-Pullback strategy (Strategy #3, vwap_v1 trial).
Designed to run ALONGSIDE the Opening Bell Scalp and VWAP Reclaim sessions.

Flow:
    ~9:55 (after scalp starts) - Connect, scan gappers via Tradier quotes,
                          fetch news via Alpaca, rank, take top-3 watchlist
    then  - Poll 1-min bars for all 3 symbols from 9:30 onward
            Detect micro-pullback patterns: prior peak -> shallow pullback -> breakout
    bars 9:30-11:30 - evaluate_entry() per bar; entry window is flexible (9:30-11:30)
    on signal - place orders via AlpacaBroker (paper); manage exits bar-by-bar
    after 11:30 ET with no position - done for the day

Uses the SAME evaluate_entry/evaluate_exit as the simulator -- only the
data source differs. Coordinated entry blocking via active_positions file
so micro-pullback + VWAP don't double-enter the same symbol.

Usage:
    python live_micro_pullback_runner.py             # paper trading (default)
    python live_micro_pullback_runner.py --live      # REAL MONEY
    python live_micro_pullback_runner.py --dry-run   # log only, no orders
"""

from __future__ import annotations

import os
import sys
import argparse
import logging
import time
import queue
import threading
import json as _json
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
import json

import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from trading.micro_pullback_models import MicroPullbackConfig, ENTRY_WINDOW_END, WATCH_TOP_N
from trading.micro_pullback_engine import evaluate_entry, evaluate_exit
from trading.scalp_ranker import rank_candidates, ENRICH_TOP_N, MAX_GAP_PCT
from trading.bar_capture import record_bar, record_news
from trading.rel_vol_live import fetch_rel_vol_baseline, compute_rel_vol
from trading._positions_lock import try_claim as _claim_position, release as _release_position
from backend.news_fetcher import has_news_catalyst

ET = pytz.timezone('America/New_York')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


# ── Micro-Pullback trial 167 (most trades across all windows — paper trading for data volume) ──
# Swapped from trial 159 for paper trading: 364 total trades vs 339, loosest pullback_retrace (11.1)
# Train 2021-23: 85.8% WR, $11,450 / 233 trades
# Select 2024:   83.0% WR, PF  7.20, $5,321 / 83 trades (OOS validation)
# Seal 2025:     88.0% WR, PF  8.37, $2,755 / 48 trades (Jan-Jun)

TRIAL_167_CONFIG = MicroPullbackConfig(
    min_gap_pct=14.11983453875954,
    min_relative_volume=3.88597983541004,
    max_price=15.217173323934988,
    max_float=40_000_000,
    require_news=True,
    lookback_bars=6,
    max_pullback_bars=3,
    max_pullback_retrace=11.065487667445561,
    pullback_vol_ratio=0.7625515979776143,
    resume_vol_mult=1.6836625745936113,
    profit_target_pct=8.673296419697865,
    max_hold_bars=14,
    trailing_stop_pct=0.003027022522226367,
    risk_pct=2.298919549411626,
    max_position_pct=49.895184791981684,
)


@dataclass
class LiveMicroPullbackState:
    """Mutable state for one trading day."""
    watchlist: list[dict] = field(default_factory=list)

    # Trade execution (current trade)
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
    traded_symbols: list[str] = field(default_factory=list)

    # Results (current/last trade for backward compat)
    exit_price: float = 0.0
    exit_reason: str = ''
    pnl: float = 0.0

    # Multi-trade tracking
    completed_trades: list[dict] = field(default_factory=list)


class LiveMicroPullbackRunner:
    """Runs the Micro-Pullback strategy. Data: Tradier production. Orders: Alpaca paper."""

    def __init__(
        self,
        config: MicroPullbackConfig = None,
        dry_run: bool = False,
        live: bool = False,
    ):
        self.config = config or TRIAL_167_CONFIG
        self.dry_run = dry_run
        self.live = live
        self.state = LiveMicroPullbackState()

        # Load env
        env_file = '.env.live' if live else '.env.paper'
        env_path = os.path.join(os.path.dirname(__file__), '..', env_file)
        if os.path.exists(env_path):
            self._load_env(env_path)

        if not live:
            from trading.broker.alpaca import AlpacaBroker
            self.broker = None if dry_run else AlpacaBroker(
                api_key=Config.ALPACA_PAPER_KEY,
                secret_key=Config.ALPACA_PAPER_SECRET,
            )
            self.data_feed = Config.get_data_feed()
            logger.info("Broker: Alpaca paper (real-time fills)")
            logger.info("Data feed: Tradier production (real-time)")
        else:
            self.broker = None if dry_run else Config.get_broker()
            self.data_feed = Config.get_data_feed()

        from backend.news_fetcher import NewsFetcher, classify_news_tier
        self.news_fetcher = NewsFetcher()
        self.classify_news_tier = classify_news_tier

        baseline = fetch_rel_vol_baseline()
        self._rel_vol_baselines = baseline.get('baselines') if baseline else None
        self._floats = baseline.get('floats') if baseline else None
        if not self._floats:
            logger.warning("Float baseline empty — max_float filter INACTIVE this session (parity gap)")

        self._bar_queue = queue.Queue(maxsize=1000)

        logger.info("=" * 60)
        logger.info("MICRO-PULLBACK RUNNER (Strategy #3)")
        logger.info("=" * 60)
        mode = "DRY RUN" if dry_run else ("LIVE" if live else "PAPER")
        logger.info(f"Mode: {mode}")
        logger.info(f"Config: gap>={self.config.min_gap_pct:.1f}% "
                    f"lookback={self.config.lookback_bars} bars "
                    f"max_pullback={self.config.max_pullback_bars} bars "
                    f"profit={self.config.profit_target_pct:.1f}%")

        if not dry_run:
            try:
                balance = self.broker.get_account_balance()
                logger.info(f"Account balance: ${balance:,.2f}")
            except Exception as e:
                logger.warning(f"Could not fetch account balance: {e}")

    def scan_gappers(self):
        """Scan for gap-ups, enrich with news, rank, keep top-N watchlist."""
        logger.info("-" * 40)
        logger.info("PHASE 1: Gapper scan (micro-pullback watchlist)")
        logger.info("-" * 40)

        from trading.live_scalp_runner import LiveScalpRunner
        symbols = LiveScalpRunner._fetch_nasdaq_symbols()
        if not symbols:
            logger.warning("No symbol universe available.")
            return

        prior_closes: dict[str, float] = {}
        try:
            prior_closes = self.data_feed.get_prior_closes(symbols)
            logger.info(f"Fetched prior closes for {len(prior_closes):,} symbols")
        except Exception as e:
            logger.warning(f"Prior close fetch failed: {e}")

        logger.info(f"Fetching quotes for {len(symbols):,} symbols...")
        try:
            quotes = self.data_feed.get_quotes(symbols)
        except Exception as e:
            logger.error(f"Quote fetch failed: {e} — no candidates this scan")
            return
        logger.info(f"Got {len(quotes):,} quotes")

        for sym, q in quotes.items():
            if q.prev_close <= 0 and sym in prior_closes:
                q.prev_close = prior_closes[sym]

        gappers = []
        for sym, q in quotes.items():
            if q.prev_close <= 0 or q.last <= 0:
                continue
            price = q.last
            if q.last == q.prev_close and q.bid > 0 and q.ask > 0:
                mid = (q.bid + q.ask) / 2
                if abs(mid - q.prev_close) / q.prev_close > 0.005:
                    price = mid
            gap_pct = (price - q.prev_close) / q.prev_close * 100
            if gap_pct < self.config.min_gap_pct:
                continue
            if gap_pct > MAX_GAP_PCT:
                continue
            if price < 1.00:
                continue  # sub-$1 warrants/shells (e.g. EVGOW $0.01) — too illiquid,
                          # wide spreads. This runner scans the raw NASDAQ universe
                          # (no $0.50-$30 prefilter), so the floor must live here too.
            if price > self.config.max_price:
                continue
            gappers.append({
                'symbol': sym,
                'gap_pct': gap_pct,
                'open_price': price,
                'prior_close': q.prev_close,
                'quote_volume': q.volume,
            })

        gappers.sort(key=lambda g: g['gap_pct'], reverse=True)
        logger.info(f"Found {len(gappers)} gappers >= {self.config.min_gap_pct:.1f}%")

        if not gappers:
            return

        top_gappers = gappers[:ENRICH_TOP_N]
        logger.info(f"Enriching top {len(top_gappers)} gappers with news...")
        self._enrich_with_news(top_gappers)

        filtered = []
        for g in top_gappers:
            if self.config.require_news and not g.get('has_news', False):
                logger.info(f"  SKIP {g['symbol']} gap={g['gap_pct']:.1f}% -- no news")
                continue
            g['rel_vol'] = compute_rel_vol(
                g['symbol'], g.get('quote_volume'), self._rel_vol_baselines)
            if g['rel_vol'] < self.config.min_relative_volume:
                logger.info(f"  SKIP {g['symbol']} gap={g['gap_pct']:.1f}% "
                            f"rel_vol={g['rel_vol']:.2f} < {self.config.min_relative_volume:.2f}")
                continue
            float_shares = self._floats.get(g['symbol']) if self._floats else None
            g['float_shares'] = float_shares
            if float_shares and float_shares > self.config.max_float:
                logger.info(f"  SKIP {g['symbol']} gap={g['gap_pct']:.1f}% "
                            f"float={float_shares:,.0f} > {self.config.max_float:,.0f}")
                continue
            filtered.append(g)

        if not filtered:
            logger.warning("No gappers passed filters.")
            return

        self.state.watchlist = rank_candidates(filtered)[:WATCH_TOP_N]
        logger.info(f"\n>>> MICRO-PULLBACK WATCHLIST ({len(self.state.watchlist)}):")
        for i, c in enumerate(self.state.watchlist):
            logger.info(f"  #{i+1} {c['symbol']:6s} gap={c['gap_pct']:.1f}% "
                        f"news={c.get('news_tier', '?')} score={c.get('scalp_score', 0):.3f}")

    def execute(self):
        """Poll bars for the watchlist, detect micro-pullback patterns, enter/exit."""
        if not self.state.watchlist:
            logger.info("No watchlist — no micro-pullback trade today.")
            return

        symbols = [c['symbol'] for c in self.state.watchlist]
        by_symbol = {c['symbol']: c for c in self.state.watchlist}

        logger.info("-" * 40)
        logger.info(f"PHASE 2: Watching {symbols} for micro-pullback (window 9:30-11:30 bar time)")
        logger.info("-" * 40)

        from trading.broker.tradier import TradierBarPoller
        poller = TradierBarPoller(
            token=Config.TRADIER_PRODUCTION_TOKEN or Config.TRADIER_PAPER_TOKEN,
            sandbox=False,
            delay_minutes=0,
            bar_queue=self._bar_queue,
        )
        poller.set_watchlist(symbols)
        poller_thread = threading.Thread(target=poller.start, daemon=True)
        poller_thread.start()

        # Per-symbol bar history
        bars_hist: dict[str, list[dict]] = {s: [] for s in symbols}

        # Backfill session bars (9:30 ET onward)
        last_seeded: dict[str, datetime] = {}
        logger.info("Backfilling session bars...")
        try:
            seed_bars = self.data_feed.get_bars_since_4am(symbols)
        except Exception as e:
            logger.warning(f"Session bar backfill failed: {e}")
            seed_bars = {}
        engine_now = datetime.now(pytz.UTC)
        for sym, blist in seed_bars.items():
            for b in blist:
                b_et = b.time.astimezone(ET)
                if b_et.hour < 9 or (b_et.hour == 9 and b_et.minute < 30):
                    continue
                if b.time > engine_now:
                    continue
                bar_dict = b.to_bar_dict()
                bar_dict['symbol'] = sym
                bar_dict['_et'] = b_et
                bars_hist[sym].append(bar_dict)
                last_seeded[sym] = b.time
                record_bar(sym, bar_dict, source='micro_pullback_seed')
            logger.info(f"  {sym}: seeded {len(bars_hist[sym])} session bars")

        window_end_min = 11 * 60 + 30  # 11:30 ET

        while not self.state.trade_done:
            try:
                bar = self._bar_queue.get(timeout=300)
            except queue.Empty:
                logger.warning("No bar received in 300s -- ending session")
                if self.state.in_position:
                    logger.warning("Timeout while IN POSITION — placing market exit")
                    try:
                        self._place_exit(self.state.symbol,
                                         {'close': self.state.entry_price},
                                         {'reason': 'BAR_TIMEOUT_SAFETY_EXIT'})
                    except Exception as e:
                        logger.error(f"  Emergency exit failed: {e}", exc_info=True)
                break

            sym = bar.get('symbol')
            if sym not in bars_hist:
                continue

            bar_time = bar.get('time')
            if isinstance(bar_time, str):
                bar_time = datetime.fromisoformat(bar_time)
            bar_et = bar_time.astimezone(ET) if bar_time else None
            bar['_et'] = bar_et

            # Skip bars already in seed
            seeded_until = last_seeded.get(sym)
            if seeded_until is not None and bar_time is not None and bar_time <= seeded_until:
                continue

            bars_hist[sym].append(bar)

            if not self.state.in_position:
                # Skip symbols we already traded
                if sym in self.state.traded_symbols:
                    continue

                # Check window end
                bar_min = bar_et.hour * 60 + bar_et.minute if bar_et else 0
                if bar_min > window_end_min:
                    logger.info(f"Bar time {bar_et.strftime('%H:%M')} past window end. Done.")
                    self.state.trade_done = True
                    break

                # Check active_positions blocking (don't enter if another strategy is in this symbol)
                if not self._can_enter_symbol(sym):
                    continue

                # Evaluate entry
                signal = evaluate_entry(by_symbol[sym], bars_hist[sym], self.config)
                if signal:
                    try:
                        self._place_entry(sym, bar, signal)
                    except Exception as e:
                        logger.error(
                            f"  [{sym}] ENTRY FAILED: {e} — skipping symbol",
                            exc_info=True)
                        self.state.traded_symbols.append(sym)
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
                    try:
                        self._place_exit(sym, bar, exit_signal)
                    except Exception as e:
                        # Don't crash the session on an exit failure — keep the
                        # position and retry the exit on the next bar.
                        logger.error(
                            f"  [{sym}] EXIT FAILED: {e} — keeping position, "
                            f"retry next bar", exc_info=True)

        poller.stop()
        self._print_summary()

    def _can_enter_symbol(self, symbol: str) -> bool:
        """Fast pre-check (not authoritative — use as hint only)."""
        from trading._positions_lock import is_claimed
        return not is_claimed(symbol)

    def _clear_active_position(self, symbol: str):
        """Remove symbol from active_positions."""
        _release_position(symbol)

    def _place_entry(self, symbol: str, bar: dict, signal: dict):
        # Atomic cross-strategy claim — must succeed before any order is placed.
        if not _claim_position(symbol, "micro_pullback"):
            logger.info(f"[{symbol}] Already claimed by another strategy — skipping entry")
            return

        entry_price = signal['entry_price']
        stop_price = signal['stop_price']
        account_balance = 5000.0

        if not self.dry_run:
            if Config.PAPER_STARTING_BALANCE > 0:
                account_balance = Config.PAPER_STARTING_BALANCE
            else:
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
            logger.warning(f"Position size = 0 shares for {symbol}. Skipping.")
            self.state.traded_symbols.append(symbol)
            _release_position(symbol)
            return

        logger.info(f">>> ENTRY: {shares} shares of {symbol} @ ${entry_price:.2f}")
        logger.info(f"    Reason: {signal.get('reason', '?')}")
        logger.info(f"    Stop: ${stop_price:.2f}")

        entry_price = round(entry_price, 2)
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
                cancelled = self.broker.cancel_order(result.order_id)
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
                    logger.warning(f"    Entry failed for {symbol}, skipping.")
                    self.state.traded_symbols.append(symbol)
                    _release_position(symbol)
                    return

            try:
                stop_result = self.broker.place_stop_sell(symbol, shares, round(stop_price, 2))
                self.state.stop_order_id = stop_result.order_id
                logger.info(f"    Stop order: {stop_result.order_id} @ ${stop_price:.2f}")
            except Exception as e:
                logger.error(f"    [{symbol}] STOP ORDER FAILED: {e} — position UNHEDGED")

        self.state.in_position = True
        self.state.symbol = symbol
        self.state.entry_price = entry_price
        self.state.stop_price = stop_price
        self.state.shares = shares
        self.state.entry_time = datetime.now(ET)
        self.state.highest_since_entry = float(bar['high'])
        self.state.bars_held = 0
        # Position already claimed atomically at top of _place_entry via _claim_position.

    def _place_exit(self, symbol: str, bar: dict, exit_signal: dict):
        exit_price = exit_signal.get('exit_price', float(bar['close']))

        logger.info(f">>> EXIT: {self.state.shares} shares of {symbol} @ ${exit_price:.2f}")
        logger.info(f"    Reason: {exit_signal.get('reason', '?')}")

        if not self.dry_run:
            if self.state.stop_order_id:
                # Cancel the protective stop and WAIT until it settles — the broker
                # only releases the held shares once the cancel is terminal. Selling
                # before that races 'insufficient qty available'.
                final = self.broker.cancel_order_and_wait(self.state.stop_order_id)
                if final.status == 'filled':
                    logger.warning(
                        f"    Stop {self.state.stop_order_id} filled "
                        f"@ ${final.filled_price:.2f} during cancel — adopting stop fill"
                    )
                    exit_price = final.filled_price
                    self._record_trade(exit_price, 'STOP_FILLED_SERVER')
                    self._clear_active_position(symbol)
                    return

            result = self.broker.place_market_sell(symbol, self.state.shares)
            logger.info(f"    Sell order: {result.order_id} Status: {result.status}")
            time.sleep(2)
            fill = self.broker.get_order(result.order_id)
            if fill.status == 'filled':
                exit_price = fill.filled_price
                logger.info(f"    FILLED: {fill.filled_qty} @ ${exit_price:.2f}")

        self._record_trade(exit_price, exit_signal.get('reason', '?'))
        self._clear_active_position(symbol)

    def _record_trade(self, exit_price: float, reason: str):
        """Record completed trade, reset position state for next trade."""
        pnl = (exit_price - self.state.entry_price) * self.state.shares
        trade = {
            'symbol': self.state.symbol,
            'entry_price': self.state.entry_price,
            'exit_price': exit_price,
            'shares': self.state.shares,
            'pnl': pnl,
            'bars_held': self.state.bars_held,
            'reason': reason,
        }
        self.state.completed_trades.append(trade)
        self.state.traded_symbols.append(self.state.symbol)
        logger.info(f"    Trade #{len(self.state.completed_trades)}: "
                     f"{trade['symbol']} P&L ${pnl:+.2f} ({reason})")

        # Keep last trade in top-level fields for backward compat
        self.state.exit_price = exit_price
        self.state.exit_reason = reason
        self.state.pnl = pnl

        # Reset position for next trade
        self.state.in_position = False
        self.state.symbol = ''
        self.state.entry_price = 0.0
        self.state.stop_price = 0.0
        self.state.shares = 0
        self.state.entry_time = None
        self.state.entry_order_id = ''
        self.state.stop_order_id = ''
        self.state.highest_since_entry = 0.0
        self.state.bars_held = 0

    def _enrich_with_news(self, candidates: list[dict]):
        today = datetime.now(ET).date()
        for c in candidates:
            try:
                articles = self.news_fetcher.get_news_for_symbol(
                    c['symbol'], as_of_date=today, hours_back=48,
                )
                if articles:
                    tier = self.classify_news_tier(articles)
                    c['has_news'] = has_news_catalyst(tier)
                    c['news_tier'] = tier
                    record_news(c['symbol'], articles, tier)
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
        logger.info("MICRO-PULLBACK SUMMARY")
        logger.info("=" * 60)
        if s.completed_trades:
            total_pnl = sum(t['pnl'] for t in s.completed_trades)
            for i, t in enumerate(s.completed_trades, 1):
                logger.info(f"Trade {i}:    {t['symbol']} "
                             f"${t['entry_price']:.2f}→${t['exit_price']:.2f} "
                             f"({t['shares']} sh, {t['bars_held']} bars) "
                             f"P&L ${t['pnl']:+.2f} [{t['reason']}]")
            logger.info(f"Total P&L:  ${total_pnl:+.2f} ({len(s.completed_trades)} trades)")
        else:
            logger.info("Result:     NO TRADE")
        logger.info("=" * 60)


def run_micro_pullback_session(dry_run=False, live=False) -> LiveMicroPullbackState:
    """
    Run a complete Micro-Pullback session. Designed to run concurrently with
    Opening Bell Scalp and VWAP Reclaim sessions.
    """
    runner = LiveMicroPullbackRunner(dry_run=dry_run, live=live)
    runner.scan_gappers()

    # Write live state
    _mp_state_file = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader")) / "micro_pullback_state.json"
    _watchlist = []
    for c in (runner.state.watchlist or []):
        _watchlist.append({k: c.get(k) for k in (
            'symbol', 'gap_pct', 'open_price', 'prior_close', 'rel_vol',
            'float_shares', 'has_news', 'news_tier', 'scalp_score', 'quote_volume',
        )})
    _mp_state_file.write_text(_json.dumps({
        "last_run": datetime.utcnow().isoformat(),
        "strategy": "micro_pullback",
        "last_result": "scanning",
        "date": str(datetime.now(ET).date()),
        "watchlist": _watchlist,
    }, default=str))

    runner.execute()
    return runner.state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Micro-Pullback - Live Trading')
    parser.add_argument('--live', action='store_true', help='REAL MONEY trading')
    parser.add_argument('--dry-run', action='store_true', help='Log only, no orders')
    args = parser.parse_args()

    run_micro_pullback_session(dry_run=args.dry_run, live=args.live)
