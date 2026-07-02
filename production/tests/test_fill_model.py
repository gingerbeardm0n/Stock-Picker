"""Unit tests for simulator/fill_model.py (docs/SIM_FILL_MODEL_DESIGN.md)."""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dataclasses import dataclass

from simulator.fill_model import (
    limit_price, resolve_limit_fill, apply_slippage, uses_marketable_limit,
)


@dataclass
class Cfg:
    fill_model: str = 'perfect'
    entry_headroom_pct: float = 0.25
    entry_slippage_pct: float = 0.0


def test_limit_price_headroom():
    assert limit_price(10.00, Cfg()) == 10.02          # 10.025 float -> 10.02
    assert limit_price(4.00, Cfg()) == 4.01
    # Sub-$4: 0.25% < half a cent -> rounds back to the signal price
    assert limit_price(1.24, Cfg()) == 1.24
    assert limit_price(10.00, Cfg(entry_headroom_pct=1.0)) == 10.10


def test_fill_at_open_when_open_below_limit():
    # Gap down through the limit -> pay the (better) open
    bar = {'open': 9.95, 'low': 9.90, 'high': 10.20, 'close': 10.10}
    assert resolve_limit_fill(10.03, bar) == 9.95


def test_fill_at_limit_when_traded_through():
    # Open above the limit but bar trades down through it -> fill at L
    bar = {'open': 10.10, 'low': 10.00, 'high': 10.30, 'close': 10.25}
    assert resolve_limit_fill(10.03, bar) == 10.03


def test_miss_when_price_ran():
    # Stock kept running: never came back to the limit -> no fill
    bar = {'open': 10.20, 'low': 10.10, 'high': 10.60, 'close': 10.55}
    assert resolve_limit_fill(10.03, bar) is None


def test_slippage_applied():
    assert abs(apply_slippage(10.00, Cfg(entry_slippage_pct=0.5)) - 10.05) < 1e-9
    assert apply_slippage(10.00, Cfg()) == 10.00


def test_model_flag():
    assert not uses_marketable_limit(Cfg())
    assert uses_marketable_limit(Cfg(fill_model='marketable_limit'))
    # Configs without the fields (legacy dicts/objects) default to perfect
    class Legacy: pass
    assert not uses_marketable_limit(Legacy())


def test_real_configs_default_perfect():
    from trading.scalp_models import ScalpConfig
    from trading.vwap_models import VwapReclaimConfig
    from trading.micro_pullback_models import MicroPullbackConfig
    for cfg in (ScalpConfig(), VwapReclaimConfig(), MicroPullbackConfig()):
        assert cfg.fill_model == 'perfect'
        assert not uses_marketable_limit(cfg)


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print(f"PASS {name}")
    print("all fill_model tests passed")
