"""
Orchestrator — the ONE per-minute decision pipeline (sim + live share it).

All trading logic that used to live in simulator/simulation_engine.py
(`_process_minute` + `_scan_for_entry`) lives here now. The simulator and the live
runner both construct this object and call `on_minute`; they differ ONLY in the
DataFeed (bars in) and the Broker (orders out) they inject.

Hard rule: this module imports ONLY pure engine pieces + the Broker interface. It
NEVER imports the simulator, a DB, or a broker SDK. The one piece of data the sim
precomputes (relative volume) is supplied via an injected `rel_vol_resolver` callback
so no DB access leaks in; live supplies its own resolver (or attaches rel_vol upstream).
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from collections import defaultdict
from datetime import datetime
import pytz

from trading.entry_engine import evaluate_entry
from trading.exit_engine import evaluate_exit
from trading.add_on_engine import evaluate_add_on
from trading.indicators import get_current_ema, calculate_macd, estimate_buy_sell_volume
from trading.models import ScannerConfig, ScoringConfig, MomentumScanConfig
from trading.momentum_scanner import qualifies_momentum
from trading.market_temperature import (
    TemperatureState, classify_premarket, update_from_trade_result, is_session_over,
)
from trading.entry_gate import entry_blocked_reason, PORTFOLIO_RULE
from trading.sizing import cushion_size_multiplier

ET = pytz.timezone('US/Eastern')
logger = logging.getLogger(__name__)

BAR_HISTORY_SIZE = 40  # >= slow26+signal9=35 so MACD computes; matches live BAR_HISTORY_DEPTH


def _noop_rel_vol_resolver(candidates, et_time):
    """Default resolver: no DB. Returns empty avg_vols → rel_vol falls back to bar's
    precomputed rel_vol_30d, else 0.0. Live/sim inject a real one if needed."""
    return {}


class Orchestrator:
    """The shared per-minute decision pipeline. One instance per trading session."""

    def __init__(
        self,
        broker,
        *,
        scanner_config=None,
        entry_config=None,
        exit_config=None,
        scoring_config=None,
        add_on_config=None,
        temp_config=None,
        portfolio_manager=None,
        hot_symbols=None,
        prior_close=None,
        fundamentals=None,
        prior_day_high=None,
        symbol_universe=None,
        news_cache=None,
        rel_vol_resolver=None,
        momentum_config=None,
        max_position_pct: float = 20.0,
        verbose: bool = False,
        debug: bool = False,
    ):
        self.broker = broker  # ALL position/order access via the Broker Protocol (sim OR live)
        self.portfolio_manager = portfolio_manager

        self.scanner_config = scanner_config
        self.entry_config = entry_config
        self.exit_config = exit_config
        self.scoring_config = scoring_config
        self.add_on_config = add_on_config
        from trading.models import MarketTemperatureConfig
        self.temp_config = temp_config or MarketTemperatureConfig()
        self.momentum_config = momentum_config or MomentumScanConfig()

        self.hot_symbols = hot_symbols or set()
        self.prior_close = prior_close or {}
        self.fundamentals = fundamentals or {}
        self.prior_day_high = prior_day_high or {}
        self.symbol_universe = symbol_universe
        self.news_cache = news_cache or {}
        self._rel_vol_resolver = rel_vol_resolver or _noop_rel_vol_resolver

        self.max_position_pct = max_position_pct
        self.verbose = verbose
        self.debug = debug

        # ── Per-session state (was scattered across the sim) ──────────────────────
        self.temp_state = TemperatureState()
        self.bar_history = defaultdict(list)
        self._cumulative_volume = defaultdict(float)
        self._high_of_day = defaultdict(float)   # running per-symbol HOD (time-forward, no lookahead)
        self._last_macd_histogram = defaultdict(lambda: None)
        self.time_decay_exits = set()
        self.stop_hit_counts = {}
        self.trade_log = []
        self._stats = {}

    # ── The per-minute pipeline (ported verbatim from simulation_engine) ──────────
    def on_minute(self, current_time, bars):
        """Process one minute. No lookahead — history updated BEFORE decisions."""
        et_time = current_time.astimezone(ET)

        # Temperature: classify at 9:25 AM ET (once per session)
        if (et_time.hour == 9 and et_time.minute == 25
                and not self.temp_state.premarket_classified):
            self.temp_state = classify_premarket(
                self.hot_symbols,
                self.prior_close,
                self.temp_config,
                bars_snapshot=bars,
            )
            self.max_position_pct = self.temp_state.max_position_pct
            self.broker.set_max_position_pct(self.temp_state.max_position_pct)
            if self.verbose:
                logger.info(
                    f"  09:25 [TEMP] {self.temp_state.temperature.value}"
                    f"  gapper={self.temp_state.leading_gapper_pct:.0f}%"
                    f"  symbols={self.temp_state.qualifying_symbols_count}"
                )

        # Step 1: Update bar history, cumulative volume, and high-of-day
        for bar in bars:
            sym = bar['symbol']
            self.bar_history[sym].append(bar)
            if len(self.bar_history[sym]) > BAR_HISTORY_SIZE:
                self.bar_history[sym].pop(0)
            self._cumulative_volume[sym] += float(bar['volume'])
            bar_high = float(bar.get('high', bar['close']))
            if bar_high > self._high_of_day[sym]:
                self._high_of_day[sym] = bar_high

        # Step 2: Exit check
        if self.broker.position:
            pos = self.broker.position
            pos_bar = next((b for b in bars if b['symbol'] == pos.symbol), None)
            if pos_bar:
                history = self.bar_history.get(pos.symbol, [])
                prices = [float(b['close']) for b in history]
                ema9 = get_current_ema(prices, 9)
                macd = calculate_macd(prices)

                current_price = float(pos_bar['close'])
                if current_price > pos.highest_price_since_entry:
                    pos.highest_price_since_entry = current_price

                avg_buy_vol = None
                if len(history) >= 5:
                    buy_vols = [
                        estimate_buy_sell_volume(
                            b['open'], b['high'], b['low'], b['close'], b['volume']
                        )[0]
                        for b in history[-5:]
                    ]
                    avg_buy_vol = sum(buy_vols) / len(buy_vols)

                macd_hist = macd['histogram'] if macd else None
                macd_line = macd['macd'] if macd else None
                indicators = {
                    'ema9': ema9,
                    'macd_line': macd_line,
                    'macd_histogram': macd_hist,
                    'macd_histogram_prev': self._last_macd_histogram[pos.symbol],
                    'prior_day_high': self.prior_day_high.get(pos.symbol),
                    'avg_buy_vol_5bar': avg_buy_vol,
                }
                self._last_macd_histogram[pos.symbol] = macd_hist

                exit_signal = evaluate_exit(
                    position=pos,
                    current_bar=pos_bar,
                    indicators=indicators,
                    current_time=current_time,
                    config=self.exit_config,
                    temperature=self.temp_state,
                )
                if exit_signal:
                    pnl = self.broker.exit(exit_signal, current_time)
                    self.trade_log.append({
                        'time': current_time,
                        'action': exit_signal.reason,
                        'symbol': pos.symbol,
                        'price': exit_signal.price,
                        'qty': exit_signal.qty,
                        'pnl': round(pnl, 2),
                    })
                    self.portfolio_manager.update(
                        current_time=current_time,
                        pnl_delta=pnl,
                        trades_completed=self.broker.completed_trade_count(),
                    )
                    if exit_signal.reason == 'TIME_DECAY':
                        self.time_decay_exits.add(pos.symbol)
                    if exit_signal.reason == 'STOP_HIT':
                        self.stop_hit_counts[pos.symbol] = \
                            self.stop_hit_counts.get(pos.symbol, 0) + 1
                    if self.broker.position is None and pos.exit_reason:
                        win = pos.get_pnl() > 0
                        self.temp_state = update_from_trade_result(
                            self.temp_state, win, self.temp_config
                        )

        # Step 2b: Add-on check
        if self.broker.position:
            pos = self.broker.position
            pos_bar = next((b for b in bars if b['symbol'] == pos.symbol), None)
            if pos_bar:
                history = self.bar_history.get(pos.symbol, [])
                prices = [float(b['close']) for b in history]
                ema9_ao = get_current_ema(prices, 9)
                macd_ao = calculate_macd(prices)
                indicators_ao = {
                    'ema9': ema9_ao,
                    'macd_line': macd_ao['macd'] if macd_ao else None,
                }
                add_on_sig = evaluate_add_on(
                    position=pos,
                    current_bar=pos_bar,
                    bar_history=history[:-1],
                    indicators=indicators_ao,
                    current_time=current_time,
                    config=self.add_on_config,
                    temperature=self.temp_state,
                )
                if add_on_sig:
                    added_qty = self.broker.add_on(add_on_sig, current_time)
                    if added_qty > 0:
                        self.trade_log.append({
                            'time': current_time,
                            'action': f'ADD_ON_{add_on_sig.reason}',
                            'symbol': pos.symbol,
                            'price': add_on_sig.price,
                            'qty': added_qty,
                            'pnl': 0.0,
                        })
                bar_high = float(pos_bar.get('high', pos_bar['close']))
                if bar_high > pos.session_high_at_add:
                    pos.session_high_at_add = bar_high

        # Step 3: Entry scan — shared gate
        block = entry_blocked_reason(
            can_enter_trade=self.broker.can_enter(),
            premarket_classified=self.temp_state.premarket_classified,
            session_over=is_session_over(self.temp_state, current_time),
            any_rule_fired=self.portfolio_manager.any_rule_fired(),
        )
        if block is None:
            self._scan_for_entry(current_time, bars)

    def _scan_for_entry(self, current_time, bars):
        et_time = current_time.astimezone(ET)
        scfg = self.scanner_config if self.scanner_config is not None else ScannerConfig()
        mcfg = self.momentum_config

        universe_mode = self.symbol_universe is not None

        # ── Step 1: cheap candidate pre-filter ────────────────────────────────────
        # Scanner mode: qualifies_momentum() is the authoritative gate.
        #   rel_vol uses bar['rel_vol_30d'] (precomputed by sim/live upstream) as a
        #   fast estimate; 0.0 if absent means G1 rejects — acceptable fallback since
        #   the sim always attaches this column and live injects it via the resolver.
        # Universe mode: upstream already screened; only structural guards applied.
        candidates = []
        for bar in bars:
            symbol = bar['symbol']
            if not universe_mode:
                if self.hot_symbols and symbol not in self.hot_symbols:
                    continue
            if symbol in self.time_decay_exits:
                continue
            if self.stop_hit_counts.get(symbol, 0) >= 2:
                continue
            history = self.bar_history.get(symbol, [])
            if len(history) < 7:
                continue
            if not universe_mode:
                price = float(bar['close'])
                prior = self.prior_close.get(symbol)
                if prior is None or prior <= 0:
                    continue
                fund = self.fundamentals.get(symbol, {})

                # G1 (rel_vol) pre-filter: use precomputed rel_vol_30d when
                # available (sim bars always carry it). For live bars that don't
                # carry rel_vol_30d, pass exactly the threshold so G1 passes here
                # and the real rel_vol is computed by the injected resolver in
                # Step 2, then verified by evaluate_entry's own rel-vol gate.
                #
                # TODO (BEFORE PAPER TRADING): attach intraday rel_vol to live
                # bars at the bar_poller layer so this pre-filter also gates live
                # candidates correctly (avoids unnecessary evaluate_entry calls
                # for stocks that don't meet the volume threshold).
                rel_vol_30d = bar.get('rel_vol_30d')
                quick_rel_vol = (
                    float(rel_vol_30d)
                    if rel_vol_30d is not None
                    else mcfg.min_relative_volume  # live bars: bypass G1, defer to Step 2
                )

                if not qualifies_momentum(
                    price=price,
                    prior_close=prior,
                    high_of_day=self._high_of_day[symbol],
                    rel_vol=quick_rel_vol,
                    float_shares=fund.get('float_shares'),
                    et_time=et_time,
                    cfg=mcfg,
                ):
                    continue
            candidates.append((symbol, bar, history))

        if not candidates:
            return

        # ── Step 2: relative volume (DB resolution injected — no DB in orchestrator) ─
        avg_vols = {}
        if scfg.enable_relative_volume and not universe_mode:
            avg_vols = self._rel_vol_resolver(candidates, et_time)

        # ── Step 3: full entry evaluation ─────────────────────────────────────────
        best_signal = None
        best_bar = None
        for symbol, bar, history in candidates:
            precomputed = bar.get('rel_vol_30d')
            if precomputed is not None:
                rel_vol = float(precomputed)
            else:
                avg_vol = avg_vols.get(symbol, 0)
                cum_vol = self._cumulative_volume.get(symbol, 0)
                rel_vol = cum_vol / avg_vol if avg_vol > 0 else 0.0

            entry_signal = evaluate_entry(
                symbol=symbol,
                bar_history=history[:-1],
                current_bar=bar,
                fundamentals=self.fundamentals.get(symbol, {}),
                prior_close=self.prior_close.get(symbol),
                current_time=current_time,
                relative_volume=rel_vol,
                scanner_config=self.scanner_config,
                entry_config=self.entry_config,
                temperature=self.temp_state,
                news_tier=self.news_cache.get(symbol, 'unknown'),
                scoring_config=self.scoring_config,
            )
            if entry_signal is None:
                continue
            if (best_signal is None or
                    entry_signal.pattern.confidence > best_signal.pattern.confidence or
                    (entry_signal.pattern.confidence == best_signal.pattern.confidence and
                     entry_signal.pillar_data.get('rel_vol', 0) >
                     best_signal.pillar_data.get('rel_vol', 0))):
                best_signal = entry_signal
                best_bar = bar

        if best_signal and best_bar:
            pat = best_signal.pattern
            fund = self.fundamentals.get(best_signal.symbol, {})

            stop_hit_n = self.stop_hit_counts.get(best_signal.symbol, 0)
            gap14_mult = 0.5 if stop_hit_n == 1 else 1.0

            score_mult = 1.0
            if best_signal.entry_score is not None:
                scoring_cfg = self.scoring_config if self.scoring_config is not None else ScoringConfig()
                score_mult = best_signal.entry_score.size_multiplier(
                    self.temp_state.temperature.value, scoring_cfg
                )

            cushion_mult = cushion_size_multiplier(
                daily_pnl=self.portfolio_manager.daily_pnl,
                daily_goal=self.portfolio_manager.daily_profit_target,
            )

            size_mult = gap14_mult * score_mult * cushion_mult

            trade = self.broker.enter(
                best_signal,
                when=current_time,
                ref_price=pat.entry_price,
                float_shares=fund.get('float_shares'),
                size_multiplier=size_mult,
            )
            if trade:
                self.trade_log.append({
                    'time': current_time,
                    'action': 'ENTRY',
                    'symbol': best_signal.symbol,
                    'pattern': pat.pattern_type,
                    'price': pat.entry_price,
                    'shares': trade.shares,
                    'stop': pat.stop_price,
                    'target1': pat.target1,
                    'target2': pat.target2,
                    'reasoning': pat.reasoning,
                })
