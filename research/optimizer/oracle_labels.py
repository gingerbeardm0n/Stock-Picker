"""
oracle_labels.py — Load market-temperature day labels and build oracle day-sets.

The "oracle test" asks: if we had PERFECT (not predicted) knowledge of each day's
market temperature, could regime-specific configs beat one universal config?

Ground-truth labels come from validate_market_temperature.py, which writes one CSV
per label into research/analysis/outputs/:
    hot_days.csv      neutral_days.csv      cold_days.csv
Each file has header `date,momentum_score,predicted_label` (we use only `date`).

This module loads those CSVs and produces a deterministic chronological
train/test split so every regime study and the universal baseline share the
SAME test universe (universal_test == hot_test ∪ neutral_test ∪ cold_test).

Run validate_market_temperature.py FIRST (after the Phase-1 DB backfill) to
generate the CSVs — they do not exist until then.
"""

from __future__ import annotations
import csv
import os
from dataclasses import dataclass

REGIMES = ('hot', 'neutral', 'cold')

# Repo-root-relative default. Matches validate_market_temperature.py --output-dir.
DEFAULT_OUTPUTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'analysis', 'outputs')
)


@dataclass
class OracleSets:
    """Train/test day lists for every regime plus the universal baseline.

    All dates are 'YYYY-MM-DD' strings, sorted ascending.
    Invariant: universal_test == sorted(union of the three regime test lists),
               universal_train == sorted(union of the three regime train lists).
    """
    train: dict[str, list[str]]   # {'hot': [...], 'neutral': [...], 'cold': [...]}
    test:  dict[str, list[str]]
    universal_train: list[str]
    universal_test:  list[str]

    def days_for(self, regime: str, split: str) -> list[str]:
        """Return the day-list for a regime ('hot'|'neutral'|'cold'|'universal')
        and split ('train'|'test')."""
        regime = regime.lower()
        if split not in ('train', 'test'):
            raise ValueError(f"split must be 'train' or 'test', got {split!r}")
        if regime == 'universal':
            return self.universal_train if split == 'train' else self.universal_test
        if regime not in REGIMES:
            raise ValueError(f"regime must be one of {REGIMES + ('universal',)}, got {regime!r}")
        return (self.train if split == 'train' else self.test)[regime]


def _load_regime_csv(path: str) -> list[str]:
    """Read the `date` column from one label CSV. Returns sorted unique dates."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Label CSV not found: {path}\n"
            f"Run research/analysis/scripts/validate_market_temperature.py first "
            f"(after the DB backfill) to generate hot/neutral/cold _days.csv."
        )
    dates: set[str] = set()
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        if 'date' not in (reader.fieldnames or []):
            raise ValueError(f"{path} missing required 'date' column (got {reader.fieldnames})")
        for row in reader:
            d = (row.get('date') or '').strip()
            if d:
                dates.add(d)
    return sorted(dates)


def load_oracle_sets(
    outputs_dir: str | None = None,
    test_frac: float = 0.30,
) -> OracleSets:
    """Load the three label CSVs and build a deterministic chronological split.

    Split logic (global, then partitioned):
      1. Pool ALL labeled days, keep date -> regime map.
      2. Sort all days ascending; the earliest (1 - test_frac) fraction is TRAIN,
         the latest test_frac fraction is TEST. Chronological — no leakage of
         future days into training.
      3. Each regime's train/test = its days intersected with the global split.

    This guarantees an identical held-out test universe across all 4 studies.
    """
    if not (0.0 < test_frac < 1.0):
        raise ValueError(f"test_frac must be in (0, 1), got {test_frac}")

    outputs_dir = outputs_dir or DEFAULT_OUTPUTS_DIR

    label_of: dict[str, str] = {}
    for regime in REGIMES:
        path = os.path.join(outputs_dir, f'{regime}_days.csv')
        for d in _load_regime_csv(path):
            # If a day somehow appears in two CSVs, last regime wins — but log it.
            if d in label_of and label_of[d] != regime:
                print(f"  [oracle_labels] WARNING: {d} labeled both "
                      f"{label_of[d]} and {regime}; using {regime}")
            label_of[d] = regime

    all_days = sorted(label_of)
    if not all_days:
        raise ValueError(f"No labeled days found in {outputs_dir}")

    n = len(all_days)
    cutoff = int(round(n * (1.0 - test_frac)))
    cutoff = max(1, min(cutoff, n - 1))  # keep both splits non-empty
    train_days = set(all_days[:cutoff])
    test_days  = set(all_days[cutoff:])

    train = {r: [] for r in REGIMES}
    test  = {r: [] for r in REGIMES}
    for d in all_days:
        r = label_of[d]
        (train[r] if d in train_days else test[r]).append(d)

    return OracleSets(
        train=train,
        test=test,
        universal_train=sorted(train_days),
        universal_test=sorted(test_days),
    )


def summarize(sets: OracleSets) -> str:
    """Human-readable counts table for logging."""
    lines = ["  regime    train  test", "  ------    -----  ----"]
    for r in REGIMES:
        lines.append(f"  {r:<8}  {len(sets.train[r]):>5}  {len(sets.test[r]):>4}")
    lines.append(f"  {'universal':<8}{len(sets.universal_train):>7}  {len(sets.universal_test):>4}")
    return '\n'.join(lines)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Inspect oracle day-label splits')
    ap.add_argument('--outputs-dir', default=None)
    ap.add_argument('--test-frac', type=float, default=0.30)
    a = ap.parse_args()
    s = load_oracle_sets(a.outputs_dir, a.test_frac)
    print(summarize(s))
