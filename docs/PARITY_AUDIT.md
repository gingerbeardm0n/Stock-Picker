# Parity Audit System

## Purpose
Catch divergences between simulation, live trading, and optimizer before they reach production. The system found 11 divergences on first run (June 2026).

## Components

| File | Role |
|------|------|
| `research/maintenance/parity_audit.py` | 25 structural checks across sim/live/optimizer |
| `research/maintenance/parity_baseline.json` | Known failure IDs — only NEW failures trigger warnings |
| `.hooks/pre-commit-parity` | Runs audit on commits touching `production/` or `research/optimizer/` |
| `.git/hooks/pre-commit` | Chain loader that calls `.hooks/pre-commit-parity` |

## How It Works

1. **On commit**: hook runs `parity_audit.py`, compares results vs `parity_baseline.json`
2. **No new failures**: silent pass, commit proceeds
3. **New regression**: prints warning banner, commit still proceeds (never blocks)
4. **Fix a divergence**: run `python research/maintenance/parity_audit.py --update-baseline` to lower known count

## Check Categories

1. **Shared Pipeline** — sim and live both use Orchestrator
2. **Discovery Parity** — qualifies_momentum() used everywhere, no parallel ScannerConfig filtering
3. **Config Consistency** — ScannerConfig and MomentumScanConfig defaults don't conflict
4. **Dead Gates** — _check_5_pillars doesn't re-gate what qualifies_momentum already enforces
5. **Hardcoded Constants** — no magic numbers that should come from config
6. **Optuna Hygiene** — optimizer doesn't tune dead/redundant params

## Commands

```bash
# Run audit (compare vs baseline)
python research/maintenance/parity_audit.py

# Accept current failures as new baseline
python research/maintenance/parity_audit.py --update-baseline
```

## Core Principle

**One function, one config, three callers.** Discovery filtering should go through `qualifies_momentum()` with `MomentumScanConfig`. Entry/exit decisions go through `Orchestrator.on_minute()`. Any parallel filtering logic in live_scanner.py or entry_engine.py using ScannerConfig for the same checks is a divergence.

## History

- **Created**: June 2, 2026
- **Trigger**: Optuna trial 2591 scored 16,374 in-sample but holdout on 2024 data showed -$3,326 (overfit). Investigation found 11 sim/live divergences including redundant gates in entry_engine and live_scanner using different config than optimizer.
- **Fixes applied same day**: removed 4 dead pillar gates from entry_engine._check_5_pillars (price, gain, rel_vol, float — all pre-screened by qualifies_momentum)
