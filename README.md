# Stock-Picker

Autonomous US-equities momentum day-trading system, built research-first and run in paper mode.

## ⚠️ Paper Trading Disclaimer

**This is a paper trading simulation system. No real money is traded and no live brokerage orders are placed.**

- The system runs exclusively against Tradier's **paper trading API**.
- All performance figures produced by backtests, walk-forward validation, or the live paper engine are **simulated results**, not live investment returns.
- Nothing in this repository or its output constitutes investment advice. Simulated performance does not guarantee future results, live or otherwise.

## Tech Stack

- **Python** — core application and strategy logic
- **Flask** — REST API for the trading backend
- **TimescaleDB** — time-series storage for market data (bars, quotes, signals)
- **Tradier API** — brokerage connectivity (paper trading endpoints only)
- **Optuna** — parameter optimization and walk-forward search
- **Render** — deployment target for the API and trading services

## Architecture Overview

The system is organized around a research → validation → deployment pipeline:

1. **Data layer** — historical and streaming market data is collected and persisted in TimescaleDB.
2. **Research & optimizer** — Optuna-driven parameter search over the strategy set, backed by backtests against stored market data.
3. **Backend API** — a Flask service exposes strategy status, signals, and control endpoints, and coordinates the paper trading engine against Tradier.
4. **Trading engine** — evaluates live paper signals during market hours and submits paper orders through Tradier.

## Strategy Overview

Three momentum-based intraday strategies drive signal generation:

- **Opening Bell Scalp** — captures early-session momentum in the first minutes after the open.
- **VWAP Reclaim** — enters on reversion/reclaim of VWAP after a momentum shakeout.
- **Micro-Pullback** — enters on shallow pullbacks within an established intraday trend.

## Research Methodology

Every strategy change follows the same pipeline before it can run in paper mode:

**Hypothesis → Backtest → Walk-Forward Validation → Paper Deployment**

The parameter surface has been intentionally reduced from 126 tunable parameters down to roughly a dozen, following a "plateau, not peak" philosophy — favoring parameter regions that are robust across a wide range of settings over narrow, overfit optima.

## Status

Paper trading only. Not connected to a live brokerage account.
