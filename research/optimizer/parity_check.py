"""
parity_check.py — prove sim and live make IDENTICAL decisions on the same bars.

The migration put sim + live on one Orchestrator. golden_baseline proves the SIM path is
unchanged; this proves the LIVE path (Orchestrator + LiveBroker over LiveTradeManager)
produces the same trades as the sim path (Orchestrator + SimBroker), fed the identical bars.

Method (no real orders, no network):
  1. Run the sim for the golden days. A recording hook on Orchestrator.on_minute captures
     the exact (minute, bars) stream AND the sim orchestrator's loaded state/configs.
  2. Replay those bars through a fresh Orchestrator wired to a LiveBroker over a
     LiveTradeManager whose executor is a _DryRunBroker (fills instantly at signal price).
  3. Compare completed trades: symbol / entry / exit / shares / pnl / reason. Must match.

Decision parity, not fill parity: the dry broker fills at the exact signal price
(ENTRY_LIMIT_BUFFER=0) so Ross's intended +$0.10 marketable-limit buffer + real slippage
are excluded — we test whether the ENGINE makes the same calls, not execution cost.

Run from research/:  python optimizer/parity_check.py
Exit 0 = parity; exit 1 = divergence (prints first differing trade).
"""

from __future__ import annotations
import sys, os, copy

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))

from optimizer.run_config import RunConfig
from optimizer.simulate_one import run_date_range
from optimizer.golden_baseline import GOLDEN_DAYS, load_universe, _UNIVERSE_CSV

from trading.orchestrator import Orchestrator
from trading.live_broker import LiveBroker
from trading.order_manager import OrderExecutor, LiveTradeManager
from trading.broker.base import BrokerInterface, OrderResult


class _ExactExecutor(OrderExecutor):
    """Test executor: place entries at the EXACT signal price — no cent-rounding, no +$0.10
    marketable-limit buffer. This isolates ENGINE decision parity from fill-realism
    differences (cent rounding + buffer are real live execution costs, tested separately)."""
    def place_entry(self, symbol, shares, ask_price, buffer=None):
        return self._broker.place_limit_buy(symbol, shares, ask_price)


class _DryRunBroker(BrokerInterface):
    """Instant-fill broker for parity testing. No network, no slippage. Buys fill at the
    limit price (= signal price when buffer=0); market sells fill at `current_price`,
    which the replay loop sets to the held symbol's bar close before each minute."""

    def __init__(self):
        self._n = 0
        self.current_price = 0.0
        self._orders: dict[str, OrderResult] = {}

    def _oid(self) -> str:
        self._n += 1
        return f"dry-{self._n}"

    def place_limit_buy(self, symbol, qty, limit_price):
        oid = self._oid()
        r = OrderResult(order_id=oid, status='filled', filled_qty=qty, filled_price=limit_price)
        self._orders[oid] = r
        return r

    def place_stop_sell(self, symbol, qty, stop_price):
        # In replay the engine emits STOP_HIT itself; the server-side stop is a live-only
        # safety net, so it just rests (never fills here).
        oid = self._oid()
        r = OrderResult(order_id=oid, status='open', filled_qty=0, filled_price=0.0)
        self._orders[oid] = r
        return r

    def place_market_sell(self, symbol, qty):
        oid = self._oid()
        r = OrderResult(order_id=oid, status='filled', filled_qty=qty, filled_price=self.current_price)
        self._orders[oid] = r
        return r

    def cancel_order(self, order_id):
        return True

    def get_order(self, order_id):
        return self._orders[order_id]

    def get_account_balance(self):
        return 0.0

    def get_position(self, symbol):
        return None


def _trade_tuple(t):
    """Comparable signature of a completed Trade (decision-level, rounded)."""
    return (
        t.symbol,
        round(t.entry_price, 4),
        round(t.exit_price or 0.0, 4),
        t.shares,
        round(t.get_pnl(), 2),
        t.exit_reason,
    )


def _capture_sim(day, universe):
    """Run the sim for one day; capture (minute,bars) stream + the sim orchestrator + sim trades."""
    captured = {'bars': [], 'orch': None}
    real_on_minute = Orchestrator.on_minute

    def recording(self, now, bars):
        if captured['orch'] is None:
            captured['orch'] = self
        captured['bars'].append((now, [copy.deepcopy(b) for b in bars]))
        return real_on_minute(self, now, bars)

    Orchestrator.on_minute = recording
    try:
        cfg = RunConfig.defaults()
        result = run_date_range(cfg, day, day, symbol_universe=universe, dates=[day])
    finally:
        Orchestrator.on_minute = real_on_minute
    return captured, result


def _replay_live(captured, day_universe):
    """Replay the captured bars through Orchestrator + LiveBroker(dry-run). Returns live trades."""
    sim_orch = captured['orch']
    if sim_orch is None:
        return []

    pm_sim = sim_orch.broker.position_manager
    acct = pm_sim.account_size
    dry = _DryRunBroker()
    executor = _ExactExecutor(dry)   # exact signal-price fills (no round/buffer) → engine parity
    ltm = LiveTradeManager(
        executor,
        account_balance=acct,
        risk_pct=pm_sim.risk_per_trade_pct,
        max_position_pct=pm_sim.max_position_pct,
    )
    ltm.fill_timeout = 1

    live_broker = LiveBroker(ltm)
    live_orch = Orchestrator(
        broker=live_broker,
        scanner_config=sim_orch.scanner_config,
        entry_config=sim_orch.entry_config,
        exit_config=sim_orch.exit_config,
        scoring_config=sim_orch.scoring_config,
        add_on_config=sim_orch.add_on_config,
        temp_config=sim_orch.temp_config,
        portfolio_manager=sim_orch.portfolio_manager.__class__(
            account_size=acct,
            daily_max_loss_pct=sim_orch.portfolio_manager.daily_max_loss_threshold / acct * 100.0,
            daily_profit_target=sim_orch.portfolio_manager.daily_profit_target,
        ),
        hot_symbols=sim_orch.hot_symbols,
        prior_close=sim_orch.prior_close,
        fundamentals=sim_orch.fundamentals,
        prior_day_high=sim_orch.prior_day_high,
        symbol_universe=sim_orch.symbol_universe,
        news_cache=sim_orch.news_cache,
        rel_vol_resolver=None,   # golden = universe mode; resolver not exercised
        max_position_pct=sim_orch.max_position_pct,
    )

    for now, bars in captured['bars']:
        # Set the dry broker's market-sell fill price to the held symbol's bar close,
        # so a live exit fills at the same price the sim used (exit_signal.price = close).
        pos = live_broker.position
        if pos is not None:
            pb = next((b for b in bars if b['symbol'] == pos.symbol), None)
            if pb is not None:
                dry.current_price = float(pb['close'])
        live_orch.on_minute(now, bars)

    return ltm.completed_trades + ([ltm.active_trade] if ltm.active_trade else [])


def main():
    universe = load_universe(_UNIVERSE_CSV)
    all_ok = True
    for day in GOLDEN_DAYS:
        captured, sim_result = _capture_sim(day, universe)
        sim_trades = [_trade_tuple_from_dict(t) for t in sim_result.get('trades', [])]
        live_trades = [_trade_tuple(t) for t in _replay_live(captured, universe)]

        if sim_trades == live_trades:
            print(f"PASS {day}: {len(sim_trades)} trades identical")
        else:
            all_ok = False
            print(f"FAIL {day}: sim={len(sim_trades)} live={len(live_trades)} trades")
            for i, (a, b) in enumerate(zip(sim_trades, live_trades)):
                if a != b:
                    print(f"  first diff #{i}:\n    sim ={a}\n    live={b}")
                    break
            if len(sim_trades) != len(live_trades):
                print(f"  (count mismatch sim={len(sim_trades)} live={len(live_trades)})")

    if all_ok:
        print("\nPARITY PASS — sim and live make identical decisions on the golden days.")
        sys.exit(0)
    print("\nPARITY FAIL — see diffs above.")
    sys.exit(1)


def _trade_tuple_from_dict(t: dict):
    """Sim trades come back as dicts from run_date_range; match _trade_tuple's shape."""
    return (
        t.get('symbol'),
        round(float(t.get('entry_price', 0)), 4),
        round(float(t.get('exit_price', 0)), 4),
        t.get('shares'),
        round(float(t.get('pnl', 0)), 2),
        t.get('exit_reason'),
    )


if __name__ == '__main__':
    main()
