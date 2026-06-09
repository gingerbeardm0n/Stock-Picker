"""
Scalp RunConfig — Flat-dict serialization for Optuna integration.
"""

from __future__ import annotations
import sys
import os
from dataclasses import dataclass, field, asdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))

from trading.scalp_models import ScalpConfig


@dataclass
class ScalpRunConfig:
    """Complete config for one scalp optimization trial."""
    scalp: ScalpConfig = field(default_factory=ScalpConfig)
    account_size: float = 5000.0

    def to_flat_dict(self) -> dict:
        """Flatten with s_ prefix."""
        d = {}
        for k, v in asdict(self.scalp).items():
            d[f's_{k}'] = v
        d['account_size'] = self.account_size
        return d

    @classmethod
    def from_flat_dict(cls, d: dict) -> ScalpRunConfig:
        """Reconstruct from flat dict."""
        scalp_fields = {}
        for k, v in d.items():
            if k.startswith('s_'):
                scalp_fields[k[2:]] = v

        return cls(
            scalp=ScalpConfig.from_dict(scalp_fields),
            account_size=d.get('account_size', 5000.0),
        )
