"""
Micro-Pullback RunConfig — Flat-dict serialization for Optuna integration.
Mirrors scalp_run_config.py / the vwap equivalent. Prefix: m_
"""

from __future__ import annotations
import sys
import os
from dataclasses import dataclass, field, asdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))

from trading.micro_pullback_models import MicroPullbackConfig


@dataclass
class MicroPullbackRunConfig:
    """Complete config for one micro-pullback optimization trial."""
    mp: MicroPullbackConfig = field(default_factory=MicroPullbackConfig)
    account_size: float = 5000.0

    def to_flat_dict(self) -> dict:
        """Flatten with m_ prefix."""
        d = {}
        for k, v in asdict(self.mp).items():
            d[f'm_{k}'] = v
        d['account_size'] = self.account_size
        return d

    @classmethod
    def from_flat_dict(cls, d: dict) -> MicroPullbackRunConfig:
        """Reconstruct from flat dict."""
        mp_fields = {}
        for k, v in d.items():
            if k.startswith('m_'):
                mp_fields[k[2:]] = v
        return cls(
            mp=MicroPullbackConfig.from_dict(mp_fields),
            account_size=d.get('account_size', 5000.0),
        )
