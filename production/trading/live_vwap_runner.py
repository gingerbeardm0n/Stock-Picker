"""
Live VWAP Reclaim Runner
=========================
Paper/live trading for the VWAP Reclaim strategy (vwap_v1 trial 56).
Designed to run RIGHT AFTER the Opening Bell Scalp session in the same
scheduled job — scalp owns 9:30-9:40, this owns the 10:00-11:30 window.

Flow:
    ~9:55 (after scalp) - Connect, scan gappers via Tradier quotes,
                          fetch news via Alpaca, rank, take top-3 watchlist
    then  - Poll 1-min bars for all 3 symbols, build running VWAP per symbol
            from the 9:30 bars onward
    bars 10:00-11:30 - evaluate_entry() per bar (the engine itself enforces
            the window on BAR TIME, so the 15-min sandbox delay is harmless)
    on signal - place orders via AlpacaBroker (paper); manage exits bar-by-bar
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
import json as _json
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path

import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from trading.vwap_models import (
    VwapReclaimConfig, ENTRY_WINDOW_END, WATCH_TOP_N, MAX_CONCURRENT,
)
from trading.vwap_engine import VwapAccumulator, evaluate_entry, evaluate_exit
from trading.scalp_ranker import rank_candidates, ENRICH_TOP_N, MAX_GAP_PCT
from trading.bar_capture import record_bar, record_news
from trading.rel_vol_live import fetch_rel_vol_baseline, fetch_missing_floats, DEFAULT_REL_VOL
from trading._positions_lock import try_claim as _claim_position, release as _release_position
from backend.news_fetcher import has_news_catalyst

ET = pytz.timezone('America/New_York')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


# ── vwap_fill_v1 trial 184 (train 2021-23 w/ marketable-limit fill model,
#    plateau-selected on 2024 [+$1,396, PF 1.77, DD $199], sealed-2025:
#    457 trades, 79.0% WR, +$1,844, PF 1.60, DD $389).
#    Replaced Trial 56 (2026-07-02): 56 was tuned assuming perfect fills;
#    under realistic fills its sealed PnL halved (+$1,188, DD $587).
#    See docs/SIM_FILL_MODEL_DESIGN.md + fill_model_diagnostic.txt. ─────────

TRIAL_184_CONFIG = VwapReclaimConfig(
    min_gap_pct=6.044448161357272,
    min_relative_volume=4.810536080054221,
    max_price=28.67209577725149,
    require_news=True,
    lookback_bars=10,
    min_bars_below=3,
    reclaim_vol_mult=1.2481258804099267,
    entry_mode='reclaim_high_break',
    stop_vwap_offset=0.07047963700569011,
    profit_target_pct=10.426314905440028,
    max_hold_bars=55,
    trailing_stop_pct=0.004207618495699649,
    risk_pct=3.3256118117400466,
    max_position_pct=44.85366067989038,
    fill_model='marketable_limit',
    entry_headroom_pct=0.9692522165642825,
)

# Deprecated 2026-07-02 — kept for reference/rollback only.
TRIAL_56_CONFIG = VwapReclaimConfig(
    min_gap_pct=7.67625431374268,
    min_relative_volume=7.4539522822260995,
    max_price=19.03592418572809,
    require_news=True,
    lookback_bars=6,
    min_bars_below=2,
    reclaim_vol_mult=2.036178582468315,
    entry_mode='reclaim_close',
    stop_vwap_offset=0.08317185478388667,
    profit_target_pct=5.259036565301703,
    max_hold_bars=44,
    trailing_stop_pct=0.001028882565589806,
    risk_pct=2.3730539057530393,
    max_position_pct=49.70080747143194,
)


@dataclass
class LiveVwapState:
    """Mutable state for one trading day."""
    watchlist: list[dict] = field(default_factory=list)

    # Multi-position tracking: symbol -> {entry_price, stop_price, shares,
    #   entry_order_id, stop_order_id, highest_since_entry, bars_held, entry_time}
    positions: dict = field(default_factory=dict)

    trade_done: bool = False
    traded_symbols: list[str] = field(default_factory=list)

    # Results
    completed_trades: list[dict] = field(default_factory=list)

    # Backward-compat single-trade fields (last completed trade)
    symbol: str = ''
    entry_price: float = 0.0
    exit_price: float = 0.0
    exit_reason: str = ''
    pnl: float = 0.0
    shares: int = 0
    bars_held: int = 0

    @property
    def in_position(self) -> bool:
        return bool(self.positions)


class LiveVwapRunner:
    """Runs the VWAP Reclaim strategy. Data: Tradier production. Orders: Alpaca paper."""

    def __init__(
        self,
        config: VwapReclaimConfig = None,
        dry_run: bool = False,
        live: bool = False,
    ):
        self.config = config or TRIAL_184_CONFIG
        self.dry_run = dry_run
        self.live = live
        self.state = LiveVwapState()

        # Load env (same convention as scalp runner)
        env_file = '.env.live' if live else '.env.paper'
        env_path = os.path.join(os.path.dirname(__file__), '..', env_file)
        if os.path.exists(env_path):
            self._load_env(env_path)

        # Hybrid architecture: Tradier production for real-time data feed,
        # Alpaca paper for order execution (real-time fills, no 15-min delay).
        # Live mode: uses whatever BROKER= is set to in .env.live.
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

        # Float data (display/data-quality only — VWAP has no max_float filter,
        # never backtested with one, see parity audit's known VWAP-max_float gap).
        # Weekly Neon baseline covers known symbols; fetch_missing_floats() fills
        # in brand-new gappers per-scan. Always a dict, never None.
        baseline = fetch_rel_vol_baseline()
        self._floats = (baseline.get('floats') if baseline else None) or {}

        # Live rel-vol: hybrid feed — today's cumulative volume from Tradier (real-time
        # premarket data), 30-day average at the same minute-of-day from Alpaca historical
        # minute bars (matches the sim's rel_vol_cum_cache denominator), both pinned to the
        # 9:25 ET cutoff to match the sim basis. See rel_vol_live.HybridRelVol and memory
        # rel-vol-lookback-research.
        from trading.rel_vol_live import HybridRelVol
        self._relvol = None
        try:
            self._relvol = HybridRelVol(
                Config._make_tradier_data_feed(),
                Config._make_alpaca_data_feed(),
                lookback_days=30)
            logger.info("Rel-vol: hybrid (Tradier numerator, Alpaca 30-day denominator, 9:25 cutoff)")
        except Exception as e:
            logger.warning(f"HybridRelVol unavailable: {e} — rel_vol falls back to 10.0")

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
            try:
                balance = self.broker.get_account_balance()
                logger.info(f"Account balance: ${balance:,.2f}")
            except Exception as e:
                logger.warning(f"Could not fetch account balance: {e}")

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

        # Prior closes (Alpaca quote snapshots don't include prev_close)
        prior_closes: dict[str, float] = {}
        try:
            prior_closes = self.data_feed.get_prior_closes(symbols)
            logger.info(f"Fetched prior closes for {len(prior_closes):,} symbols")
        except Exception as e:
            logger.warning(f"Prior close fetch failed: {e} — gap scan may find 0 gappers")

        logger.info(f"Fetching quotes for {len(symbols):,} symbols...")
        try:
            quotes = self.data_feed.get_quotes(symbols)
        except Exception as e:
            logger.error(f"Quote fetch failed: {e} — no candidates this scan")
            return
        logger.info(f"Got {len(quotes):,} quotes")

        # Patch prev_close from prior-close fetch (Alpaca returns 0.0 in quote snapshot)
        for sym, q in quotes.items():
            if q.prev_close <= 0 and sym in prior_closes:
                q.prev_close = prior_closes[sym]

        gappers = []
        zero_prev = 0
        zero_last = 0
        over_max_price = 0
        over_max_gap = 0
        all_gaps = []
        for sym, q in quotes.items():
            if q.prev_close <= 0 or q.last <= 0:
                if q.prev_close <= 0:
                    zero_prev += 1
                if q.last <= 0:
                    zero_last += 1
                continue
            # Use midpoint if last is stale (last == prev_close but bid/ask available)
            price = q.last
            if q.last == q.prev_close and q.bid > 0 and q.ask > 0:
                mid = (q.bid + q.ask) / 2
                if abs(mid - q.prev_close) / q.prev_close > 0.005:
                    price = mid
            gap_pct = (price - q.prev_close) / q.prev_close * 100
            if gap_pct >= 5.0:
                all_gaps.append((gap_pct, sym, price, q.prev_close))
            if gap_pct < self.config.min_gap_pct:
                continue
            if gap_pct > MAX_GAP_PCT:
                over_max_gap += 1
                continue
            if price < 1.00:
                continue  # sub-$1 warrants/shells — too illiquid, wide spreads
            if price > self.config.max_price:
                over_max_price += 1
                continue
            gappers.append({
                'symbol': sym,
                'gap_pct': gap_pct,
                'open_price': price,
                'prior_close': q.prev_close,
                'quote_volume': q.volume,  # today's cumulative volume (rel-vol numerator)
            })

        gappers.sort(key=lambda g: g['gap_pct'], reverse=True)
        logger.info(f"Found {len(gappers)} gappers >= {self.config.min_gap_pct:.1f}%")

        if zero_prev or zero_last or over_max_price or over_max_gap:
            logger.info(f"  Filter stats: zero_prev_close={zero_prev}, zero_last={zero_last}, "
                        f"over_max_price={over_max_price}, over_max_gap_1000={over_max_gap}")
        all_gaps.sort(reverse=True)
        if all_gaps:
            logger.info(f"  Top 10 gaps in market (>=5%%):")
            for gap, sym, last, prev in all_gaps[:10]:
                logger.info(f"    {sym}: gap={gap:.1f}% last={last:.2f} prev={prev:.2f}")

        if not gappers:
            return

        top_gappers = gappers[:ENRICH_TOP_N]
        logger.info(f"Enriching top {len(top_gappers)} gappers with news...")
        self._enrich_with_news(top_gappers)

        # Rel-vol (Gap #1 + #3): single-feed Tradier, both numerator and 5-day denominator
        # pinned to the 9:25 ET cutoff (minute 565) so today and history share the same
        # premarket-cumulative basis the sim uses. None → 10.0 fallback.
        now = datetime.now(ET)
        filtered = []
        rv_attempts = rv_fallbacks = 0
        for g in top_gappers:
            if self.config.require_news and not g.get('has_news', False):
                logger.info(f"  SKIP {g['symbol']} gap={g['gap_pct']:.1f}% -- no news")
                continue
            rv = None
            if self._relvol is not None:
                try:
                    self._relvol.invalidate(g['symbol'])
                    rv = self._relvol.compute(g['symbol'], now, cutoff_minute=565)
                except Exception as e:
                    logger.warning(f"  rel-vol compute raised for {g['symbol']}: {e}")
            rv_attempts += 1
            if rv is None:
                rv_fallbacks += 1
            g['rel_vol'] = rv if rv is not None else DEFAULT_REL_VOL
            # Same filter the sim applies — skip thin-volume candidates.
            if g['rel_vol'] < self.config.min_relative_volume:
                logger.info(f"  SKIP {g['symbol']} gap={g['gap_pct']:.1f}% "
                            f"rel_vol={g['rel_vol']:.2f} < {self.config.min_relative_volume:.2f}")
                continue
            filtered.append(g)

        if rv_attempts and rv_fallbacks:
            log = logger.warning if rv_fallbacks == rv_attempts else logger.info
            log(f"Rel-vol: {rv_attempts - rv_fallbacks}/{rv_attempts} computed, "
                f"{rv_fallbacks} fell back to {DEFAULT_REL_VOL:.1f}x"
                + (" — ALL candidates on fallback, filter is a no-op this scan"
                   if rv_fallbacks == rv_attempts else ""))

        if not filtered:
            logger.warning("No gappers passed news filter.")
            return

        # Float (display/data-quality only, see note above self._floats init).
        fetch_missing_floats([g['symbol'] for g in filtered], self._floats)
        for g in filtered:
            g['float_shares'] = self._floats.get(g['symbol'])

        self.state.watchlist = rank_candidates(filtered)[:WATCH_TOP_N]
        logger.info(f"\n>>> VWAP WATCHLIST ({len(self.state.watchlist)}):")
        for i, c in enumerate(self.state.watchlist):
            logger.info(f"  #{i+1} {c['symbol']:6s} gap={c['gap_pct']:.1f}% "
                        f"news={c.get('news_tier', '?')} score={c.get('scalp_score', 0):.3f}")

    def _write_live_state(self):
        """Write vwap_state.json as trades happen, not just once the whole
        session function returns — see live_scalp_runner._write_live_state
        for why (dashboard showed stale premarket data for the entire
        trading window otherwise)."""
        import json as _json
        state_file = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader")) / "vwap_state.json"
        watchlist = []
        for c in (self.state.watchlist or []):
            watchlist.append({k: c.get(k) for k in (
                'symbol', 'gap_pct', 'open_price', 'prior_close', 'rel_vol',
                'float_shares', 'has_news', 'news_tier', 'scalp_score', 'quote_volume',
            )})
        top_sym = self.state.watchlist[0]['symbol'] if self.state.watchlist else None
        completed = self.state.completed_trades or []
        total_pnl = sum(t.get('pnl', 0) for t in completed) if completed else self.state.pnl
        try:
            state_file.write_text(_json.dumps({
                "last_run": datetime.utcnow().isoformat(),
                "strategy": "vwap_reclaim",
                "date": str(datetime.now(ET).date()),
                "last_result": "trade" if completed or (self.state.entry_price or 0) > 0 else "scanning",
                "symbol": self.state.symbol,
                "top_pick": self.state.symbol or top_sym,
                "entry_price": self.state.entry_price,
                "exit_price": self.state.exit_price,
                "pnl": total_pnl,
                "shares": self.state.shares,
                "bars_held": self.state.bars_held,
                "exit_reason": self.state.exit_reason,
                "positions": self.state.positions,
                "watchlist": watchlist,
                "completed_trades": completed,
                "trade_count": len(completed),
            }, default=str))
        except Exception as e:
            logger.warning(f"_write_live_state failed (non-fatal): {e}")

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
            sandbox=False,
            delay_minutes=0,
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
        engine_now = datetime.now(pytz.UTC)
        for sym, blist in seed_bars.items():
            for b in blist:
                b_et = b.time.astimezone(ET)
                if b_et.hour < 9 or (b_et.hour == 9 and b_et.minute < 30):
                    continue  # accumulator ignores premarket anyway; skip history too
                if b.time > engine_now:
                    continue  # ahead of the engine clock — poller will deliver it
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
        # Hard cap, NOT len(symbols): every sealed validation (Trial 184:
        # +$1,844 / PF 1.60 on 2025) ran arm 10 / max 3 concurrent, and
        # position sizing divides max_position_pct by this number. With the
        # watchlist now at 10, len(symbols) would allow 10 tiny unvalidated
        # concurrent positions.
        max_concurrent = MAX_CONCURRENT

        while not self.state.trade_done:
            try:
                bar = self._bar_queue.get(timeout=300)  # bars arrive ~1/min/symbol
            except queue.Empty:
                logger.warning("No bar received in 300s -- ending session")
                if self.state.in_position:
                    logger.warning("Timeout with open positions — placing market exits")
                    for open_sym in list(self.state.positions):
                        try:
                            self._place_exit(open_sym,
                                             {'close': self.state.positions[open_sym]['entry_price']},
                                             {'reason': 'BAR_TIMEOUT_SAFETY_EXIT'})
                        except Exception as e:
                            logger.error(f"  [{open_sym}] Emergency exit failed: {e}", exc_info=True)
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

            bar_min = bar_et.hour * 60 + bar_et.minute if bar_et else 0

            # Unconditional completion check — must run regardless of which
            # symbol's bar just arrived. The old logic only checked this inside
            # `elif sym not in traded_symbols`, so once every watched symbol had
            # been traded, no bar path ever re-evaluated it and the session
            # polled forever (found live 2026-07-06: still running at 3:48pm ET
            # for a 10:00-11:30 window).
            if bar_min > window_end_min and not self.state.positions:
                logger.info(f"Bar time {bar_et.strftime('%H:%M')} past window end, flat. Done.")
                self.state.trade_done = True
                break

            # ── Manage open position for this symbol ──────────────────────────
            if sym in self.state.positions:
                pos = self.state.positions[sym]
                pos['bars_held'] += 1
                if float(bar['high']) > pos['highest_since_entry']:
                    pos['highest_since_entry'] = float(bar['high'])

                exit_signal = evaluate_exit(
                    entry_price=pos['entry_price'],
                    stop_price=pos['stop_price'],
                    highest_since_entry=pos['highest_since_entry'],
                    current_bar=bar,
                    bars_held=pos['bars_held'],
                    config=self.config,
                )
                if exit_signal or bar_min > window_end_min:
                    sig = exit_signal or {'exit_price': float(bar['close']),
                                          'reason': 'WINDOW_CLOSE'}
                    try:
                        self._place_exit(sym, bar, sig)
                    except Exception as e:
                        # One symbol's exit failure must NOT crash the loop and orphan
                        # the other open positions. Keep it; retry exit next bar.
                        logger.error(
                            f"  [{sym}] EXIT FAILED: {e} — keeping position, "
                            f"retry next bar", exc_info=True)

            # ── Check for new entry on this symbol ────────────────────────────
            elif sym not in self.state.traded_symbols:
                if bar_min > window_end_min:
                    # Window closed — if no open positions, we're done
                    if not self.state.positions:
                        logger.info(f"Bar time {bar_et.strftime('%H:%M')} past window end. Done.")
                        self.state.trade_done = True
                        break
                    continue

                if len(self.state.positions) >= max_concurrent:
                    continue

                if not self._can_enter_symbol(sym):
                    continue

                signal = evaluate_entry(by_symbol[sym], bars_hist[sym], accs[sym].value, self.config)
                if signal:
                    try:
                        self._place_entry(sym, bar, signal, max_concurrent)
                    except Exception as e:
                        logger.error(
                            f"  [{sym}] ENTRY FAILED: {e} — skipping symbol",
                            exc_info=True)
                        self.state.traded_symbols.append(sym)

        poller.stop()
        self._print_summary()

    # ── Order placement (same pattern as scalp runner) ────────────────────────

    def _place_entry(self, symbol: str, bar: dict, signal: dict, max_concurrent: int = 1):
        # Atomic cross-strategy claim — must succeed before any order is placed.
        if not _claim_position(symbol, "vwap_reclaim"):
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
        # Divide max_position_pct by max_concurrent so N simultaneous positions
        # use the same total capital as a single position would.
        max_position_value = account_balance * (self.config.max_position_pct / 100) / max_concurrent
        shares = min(int(risk_amount / risk_per_share),
                     int(max_position_value / entry_price))

        if shares <= 0:
            logger.warning(f"Position size = 0 shares for {symbol}. Skipping.")
            self.state.traded_symbols.append(symbol)
            _release_position(symbol)
            return

        logger.info(f">>> ENTRY: {shares} shares of {symbol} @ ${entry_price:.2f}")
        logger.info(f"    Reason: {signal.get('reason', '?')}")
        logger.info(f"    Stop: ${stop_price:.2f} (VWAP {signal.get('vwap', 0):.2f} - {self.config.stop_vwap_offset:.2f})")
        entry_price = round(entry_price, 2)
        # Marketable limit: headroom is the Optuna-tuned slippage budget the
        # sealed backtest already paid for (sim parity: simulator/fill_model.py
        # resolves the same limit against the next bar). Trial 184: ~0.97%.
        headroom = getattr(self.config, 'entry_headroom_pct', 0.0)
        limit_buy_price = round(entry_price * (1 + headroom / 100), 2)
        stop_order_id = ''
        if not self.dry_run:
            result = self.broker.place_limit_buy(symbol, shares, limit_buy_price)
            logger.info(f"    Limit: ${limit_buy_price:.2f} (signal ${entry_price:.2f} +{headroom:.2f}%)")
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
                logger.info(f"    FILLED: {symbol} {shares} @ ${entry_price:.2f}")
            else:
                logger.warning("    Entry not filled after 12s. Cancelling.")
                cancelled = self.broker.cancel_order(result.order_id)
                # A cancel can race a fill — a failed cancel usually means the
                # order already executed. Verify final state; adopt any filled
                # shares rather than leaving an orphan position with no stop.
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
                    # Limit missed — retry with a market order ONLY if the ask is
                    # still within the tuned headroom (the sealed backtest's
                    # slippage budget). The old flat 2% cap was never backtested
                    # and exceeds the strategy's per-trade edge.
                    try:
                        fresh_q = self.data_feed.get_quotes([symbol])
                        current_ask = (fresh_q[symbol].ask
                                       if symbol in fresh_q and fresh_q[symbol].ask > 0
                                       else float(bar['close']))
                    except Exception:
                        current_ask = float(bar['close'])

                    slippage_cap = limit_buy_price
                    if current_ask > slippage_cap:
                        logger.warning(
                            f"    [{symbol}] Moved {(current_ask / entry_price - 1) * 100:.1f}% "
                            f"past limit (ask=${current_ask:.2f} > cap=${slippage_cap:.2f}) — releasing, will re-eval next bar."
                        )
                        # Do NOT add to traded_symbols — if VWAP reclaim signal is
                        # still valid next bar (stock came back), we want to retry.
                        _release_position(symbol)
                        return

                    logger.info(
                        f"    [{symbol}] Limit missed — retrying market order "
                        f"(ask=${current_ask:.2f} ≤ cap=${slippage_cap:.2f})"
                    )
                    result2 = self.broker.place_market_buy(symbol, shares)
                    time.sleep(3)
                    fill2 = self.broker.get_order(result2.order_id)
                    if fill2.status == 'filled':
                        entry_price = fill2.filled_price
                        shares = fill2.filled_qty
                        logger.info(f"    MARKET FILLED: {symbol} {shares} @ ${entry_price:.2f}")
                    else:
                        logger.warning(f"    [{symbol}] Market order also failed. Skipping.")
                        self.state.traded_symbols.append(symbol)
                        _release_position(symbol)
                        return

            try:
                stop_result = self.broker.place_stop_sell(symbol, shares, round(stop_price, 2))
                stop_order_id = stop_result.order_id
                logger.info(f"    Stop order: {stop_result.order_id} @ ${stop_price:.2f}")
            except Exception as e:
                # Broker rejects a stop whose trigger price is already past current
                # market (price crashed between fill and stop placement) — that means
                # the position should already be exiting. Flatten immediately at market
                # instead of leaving it open with no protection at all.
                logger.error(
                    f"    [{symbol}] STOP ORDER FAILED: {e} — attempting emergency market exit")
                try:
                    mkt_result = self.broker.place_market_sell(symbol, shares)
                    time.sleep(2)
                    mkt_fill = self.broker.get_order(mkt_result.order_id)
                    if mkt_fill.status == 'filled':
                        logger.warning(
                            f"    [{symbol}] Emergency market exit FILLED: "
                            f"{mkt_fill.filled_qty} @ ${mkt_fill.filled_price:.2f}")
                        self.state.positions[symbol] = {
                            'entry_price': entry_price,
                            'stop_price': stop_price,
                            'shares': shares,
                            'entry_time': datetime.now(ET),
                            'stop_order_id': '',
                            'highest_since_entry': float(bar['high']),
                            'bars_held': 0,
                        }
                        self._record_trade(
                            symbol, mkt_fill.filled_price, 'STOP_REJECTED_MARKET_EXIT')
                        return  # _record_trade already wrote live state
                    logger.error(
                        f"    [{symbol}] Emergency market exit NOT FILLED "
                        f"(status={mkt_fill.status}) — position UNHEDGED")
                except Exception as e2:
                    logger.error(
                        f"    [{symbol}] Emergency market exit ALSO FAILED: {e2} — position UNHEDGED")

        self.state.positions[symbol] = {
            'entry_price': entry_price,
            'stop_price': stop_price,
            'shares': shares,
            'entry_time': datetime.now(ET),
            'stop_order_id': stop_order_id,
            'highest_since_entry': float(bar['high']),
            'bars_held': 0,
        }
        # Backward-compat single-trade fields (most recent entry)
        self.state.symbol = symbol
        self.state.entry_price = entry_price
        self._write_live_state()

    def _place_exit(self, symbol: str, bar: dict, exit_signal: dict):
        pos = self.state.positions.get(symbol)
        if not pos:
            return
        exit_price = exit_signal.get('exit_price', float(bar['close']))

        logger.info(f">>> EXIT: {pos['shares']} shares of {symbol} @ ${exit_price:.2f}")
        logger.info(f"    Reason: {exit_signal.get('reason', '?')}")

        if not self.dry_run:
            stop_order_id = pos.get('stop_order_id', '')
            if stop_order_id:
                # Cancel the protective stop and WAIT until it settles — the broker
                # only releases the held shares once the cancel is terminal. Selling
                # before that races 'insufficient qty available'.
                final = self.broker.cancel_order_and_wait(stop_order_id)
                if final.status == 'filled':
                    logger.warning(
                        f"    Stop {stop_order_id} filled @ ${final.filled_price:.2f} "
                        f"during cancel — adopting stop fill"
                    )
                    exit_price = final.filled_price
                    self._record_trade(symbol, exit_price, 'STOP_FILLED_SERVER')
                    return

            exit_type = exit_signal.get('exit_type', '')
            if exit_type == 'trailing_stop':
                # Sim assumes fill at trail_price. Use limit sell to match — avoids
                # market-order slippage when 0.001% trail fires on a tiny pullback.
                # Fall back to market if limit unfilled after 5s (stock dropped fast).
                result = self.broker.place_limit_sell(
                    symbol, pos['shares'], round(exit_price, 2))
                logger.info(f"    Limit sell order: {result.order_id} Status: {result.status}")
                time.sleep(5)
                fill = self.broker.get_order(result.order_id)
                if fill.status == 'filled':
                    exit_price = fill.filled_price
                    logger.info(f"    FILLED: {symbol} {fill.filled_qty} @ ${exit_price:.2f}")
                else:
                    logger.warning(
                        f"    Limit sell unfilled after 5s (status={fill.status}) — "
                        f"cancelling, market fallback")
                    self.broker.cancel_order(result.order_id)
                    result2 = self.broker.place_market_sell(symbol, pos['shares'])
                    time.sleep(2)
                    fill2 = self.broker.get_order(result2.order_id)
                    if fill2.status == 'filled':
                        exit_price = fill2.filled_price
                        logger.info(f"    Market fallback FILLED: {symbol} {fill2.filled_qty} @ ${exit_price:.2f}")
            else:
                result = self.broker.place_market_sell(symbol, pos['shares'])
                logger.info(f"    Sell order: {result.order_id} Status: {result.status}")
                time.sleep(2)
                fill = self.broker.get_order(result.order_id)
                if fill.status == 'filled':
                    exit_price = fill.filled_price
                    logger.info(f"    FILLED: {symbol} {fill.filled_qty} @ ${exit_price:.2f}")

        self._record_trade(symbol, exit_price, exit_signal.get('reason', '?'))

    def _record_trade(self, symbol: str, exit_price: float, reason: str):
        """Record completed trade, remove from positions dict."""
        pos = self.state.positions.pop(symbol, None)
        if not pos:
            return
        pnl = (exit_price - pos['entry_price']) * pos['shares']
        trade = {
            'symbol': symbol,
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'shares': pos['shares'],
            'pnl': pnl,
            'bars_held': pos['bars_held'],
            'reason': reason,
            'strategy': 'vwap_reclaim',
        }
        self.state.completed_trades.append(trade)
        self.state.traded_symbols.append(symbol)
        logger.info(f"    Trade #{len(self.state.completed_trades)}: "
                     f"{symbol} P&L ${pnl:+.2f} ({reason})")

        # Backward-compat: keep last-trade fields for session_job.py
        self.state.symbol = symbol
        self.state.exit_price = exit_price
        self.state.exit_reason = reason
        self.state.pnl = sum(t['pnl'] for t in self.state.completed_trades)
        self.state.shares = pos['shares']
        self.state.bars_held = pos['bars_held']
        self._write_live_state()

        # Release cross-strategy claim
        self._clear_active_position(symbol)

    # ── Active Position Blocking (coordinate with other strategies) ──────────

    def _can_enter_symbol(self, symbol: str) -> bool:
        """Fast pre-check (not authoritative — use as hint only)."""
        from trading._positions_lock import is_claimed
        return not is_claimed(symbol)

    def _clear_active_position(self, symbol: str):
        """Remove symbol from active_positions."""
        _release_position(symbol)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _cumulative_volume_through_925(self, symbols: list[str]) -> dict[str, float]:
        """Sum each symbol's session-bar volume from start-of-data through 9:25 ET
        — the SAME basis as the rel_vol_cum_cache denominator (minute_of_day=565,
        premarket-inclusive). Removes the quote-timing skew that made the live
        rel-vol filter a no-op (Gap #3).

        Cross-vendor caveat: bars come from Tradier, the baseline was built from
        Alpaca historical data, so a residual volume-definition offset remains —
        far smaller than the 2-3x timing error this fixes. Symbols with no
        pre-9:25 bars are omitted → rel-vol falls back to the 10.0 default.
        """
        out: dict[str, float] = {}
        try:
            bars_by_sym = self.data_feed.get_bars_since_4am(symbols)
        except Exception as e:
            logger.warning(f"Session-bar fetch for rel-vol failed ({e}); "
                           f"rel_vol will use the 10.0 fallback for all candidates.")
            return out
        for sym, blist in bars_by_sym.items():
            total = 0.0
            for b in blist:
                b_et = b.time.astimezone(ET)
                if b_et.hour * 60 + b_et.minute <= 565:  # through 9:25 ET inclusive
                    total += float(getattr(b, 'volume', 0) or 0)
            if total > 0:
                out[sym] = total
        return out

    def _enrich_with_news(self, candidates: list[dict]):
        today = datetime.now(ET).date()
        for c in candidates:
            try:
                articles = self.news_fetcher.get_news_for_symbol(
                    c['symbol'], as_of_date=today, hours_back=48,
                )
                if articles:
                    tier = self.classify_news_tier(articles)
                    c['has_news'] = has_news_catalyst(tier)  # shared sim/live gate
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
        logger.info("VWAP RECLAIM SUMMARY")
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


def run_vwap_session(dry_run=False, live=False) -> LiveVwapState:
    """
    Run a complete VWAP Reclaim session. Designed to be called right after
    run_scalp_session() in the same scheduled job — no internal start-time
    wait; entry timing is enforced on BAR TIME by the engine's 10:00-11:30
    window check.
    """
    runner = LiveVwapRunner(dry_run=dry_run, live=live)
    runner.scan_gappers()

    # Write live state so dashboard shows watchlist before trading begins
    _vwap_state_file = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader")) / "vwap_state.json"
    _watchlist = []
    for c in (runner.state.watchlist or []):
        _watchlist.append({k: c.get(k) for k in (
            'symbol', 'gap_pct', 'open_price', 'prior_close', 'rel_vol',
            'float_shares', 'has_news', 'news_tier', 'scalp_score', 'quote_volume',
        )})
    _top = runner.state.watchlist[0]['symbol'] if runner.state.watchlist else None
    _vwap_state_file.write_text(_json.dumps({
        "last_run": datetime.utcnow().isoformat(),
        "strategy": "vwap_reclaim",
        "last_result": "scanning",
        "date": str(datetime.now(pytz.timezone('America/New_York')).date()),
        "watchlist": _watchlist,
        "top_pick": _top,
    }, default=str))

    runner.execute()
    return runner.state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='VWAP Reclaim - Live Trading')
    parser.add_argument('--live', action='store_true', help='REAL MONEY trading')
    parser.add_argument('--dry-run', action='store_true', help='Log only, no orders')
    args = parser.parse_args()

    run_vwap_session(dry_run=args.dry_run, live=args.live)
