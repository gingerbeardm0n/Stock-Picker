# Legacy Monolith (Archived Jun 13, 2026)

126-parameter multi-pattern trading system. Replaced by standalone strategy
pipelines (scalp, VWAP reclaim, micro-pullback) with ~13 params each.

## Why archived
- Overfit: train +497 / validate median -1593, 14% positive (v8b trial 180)
- Trial 206 (best after 5-year opt): zero trades on 2025 OOS
- Root cause: too many params + patterns + no holdout
- See `docs/ANTI_OVERFITTING_PLAYBOOK.md` for full post-mortem

## What's here
- `simulator/` — SimulationRunner, date range wrappers, intent tests
- `trading/` — Orchestrator, LiveScanner, EntryEngine, patterns, indicators,
  order management, broker integration
- `backend/` — Flask app, MomentumScanner, AlpacaDataFeed
- `tests/` — unit tests for the above
- `run_trading.py` — old entry point

## When to revisit
When building multi-strategy coordination (running scalp + VWAP + micro-pullback
simultaneously), review `orchestrator.py` and `order_manager.py` for patterns
around position management, execution routing, and session lifecycle. The
individual strategy engines are intentionally decoupled, but the coordination
layer will need similar concepts — don't rebuild from scratch.

Also review `exit_engine.py` (still in production/trading/) for shared exit
logic patterns if strategies need unified exit handling.

## DO NOT re-activate without
1. Cutting params to <15
2. Walk-forward validation (train/select/seal)
3. Plateau selection, not peak
