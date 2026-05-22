"""
RunConfig — Complete optimization configuration for one simulation run.

Combines all three parameter categories into a single object:
    scanner : Category A — stock selection / 5-pillar thresholds + toggles
    entry   : Category B — pattern detection thresholds + toggles
    exit_   : Category C — exit signal thresholds

Used by:
    simulate_one.py  — pass RunConfig into SimulationRunner
    sweep.py         — vary one param at a time, all others at defaults
    optuna_run.py    — suggest values for every param from Optuna trial

Flat dict layout (prefix = category):
    a_<field>  — scanner (Category A)
    b_<field>  — entry   (Category B)
    c_<field>  — exit    (Category C)
"""

from __future__ import annotations
import sys
import os
# Add both research/ and production/ to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))  # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))  # production/

from dataclasses import dataclass, field, asdict
from trading.models import ScannerConfig, EntryConfig, ExitConfig, ScoringConfig


@dataclass
class RunConfig:
    """
    Single config object for one full optimization run.

    Simulation meta-parameters (account_size, risk_pct, max_position_pct)
    are included for reproducibility but are NOT part of the search space.

    Categories:
        A — ScannerConfig  : stock pre-screen thresholds (price, gain, rel-vol, float, ...)
        B — EntryConfig    : pattern detection thresholds and gate toggles
        C — ExitConfig     : exit signal thresholds (targets, trailing stop, time decay, ...)
        F — ScoringConfig  : composite entry score weights and temperature thresholds
    """
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    entry: EntryConfig     = field(default_factory=EntryConfig)
    exit_: ExitConfig      = field(default_factory=ExitConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)

    # Simulation meta (not tuned)
    account_size: float    = 5000.0
    risk_pct: float        = 2.0
    max_position_pct: float = 20.0

    @classmethod
    def defaults(cls) -> RunConfig:
        """Return a RunConfig with all strategy-aligned defaults."""
        return cls()

    def to_flat_dict(self) -> dict:
        """
        Flatten all params into a single dict for SQLite storage.

        Keys are prefixed by category: a_<field>, b_<field>, c_<field>, f_<field>.
        """
        d = {}
        for k, v in asdict(self.scanner).items():
            d[f'a_{k}'] = v
        for k, v in asdict(self.entry).items():
            d[f'b_{k}'] = v
        for k, v in asdict(self.exit_).items():
            d[f'c_{k}'] = v
        for k, v in asdict(self.scoring).items():
            d[f'f_{k}'] = v
        d['account_size']     = self.account_size
        d['risk_pct']         = self.risk_pct
        d['max_position_pct'] = self.max_position_pct
        return d

    @classmethod
    def from_flat_dict(cls, d: dict) -> RunConfig:
        """Reconstruct a RunConfig from a flat dict (e.g. loaded from SQLite)."""
        scanner_fields = {k[2:]: v for k, v in d.items() if k.startswith('a_')}
        entry_fields   = {k[2:]: v for k, v in d.items() if k.startswith('b_')}
        exit_fields    = {k[2:]: v for k, v in d.items() if k.startswith('c_')}
        scoring_fields = {k[2:]: v for k, v in d.items() if k.startswith('f_')}
        return cls(
            scanner=ScannerConfig(**scanner_fields),
            entry=EntryConfig(**entry_fields),
            exit_=ExitConfig(**exit_fields),
            scoring=ScoringConfig(**scoring_fields) if scoring_fields else ScoringConfig(),
            account_size=d.get('account_size', 5000.0),
            risk_pct=d.get('risk_pct', 2.0),
            max_position_pct=d.get('max_position_pct', 20.0),
        )
