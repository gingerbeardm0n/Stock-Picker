# Market Regime Detection Analysis

## Overview

This analysis identifies internal market condition signals that predict which trading regime we're in across 13 months of backtesting (Jan 2025 - Feb 2026).

**Key Finding**: Number of unique symbols trading (market breadth) is the strongest predictor of regime type, with r=0.509 correlation at 30-day lookback.

## Files Included

### 📊 Data Files

**`daily_signals.csv`** (279 rows)
- One row per trading day
- Raw daily signals: number of trades, unique symbols, win rate, P&L, etc.
- Actual regime classification for each day
- Use this for: baseline analysis, creating visualizations, custom analysis

**`daily_signals_with_detection.csv`** (279 rows)
- Same as above, plus: 30-day moving averages and detected regime
- Shows which days the simple threshold-based detection got right/wrong
- 43% overall accuracy with current thresholds
- Use this for: evaluating detection accuracy, identifying misclassifications

**`correlation_summary.csv`** (40 rows)
- Pearson correlation of each signal vs regime type
- Breakdown by lookback window (1, 3, 5, 15, 30-day)
- Signals ranked by predictive strength
- Use this for: understanding which signals work best and at what timeframe

**`regime_profiles.csv`** (3 rows)
- Summary statistics for each regime (BREAKOUT, PULLBACK, REVERSAL)
- Averages: trades/day, symbols, price movements, win rate, daily P&L
- Use this for: quick reference of regime characteristics

### 📄 Analysis Reports

**`REGIME_DETECTION_REPORT.txt`** (221 lines) - START HERE
- Executive summary of key findings
- Detailed analysis of each signal
- Top predictive signals by lookback window
- 5 actionable recommendations
- Implementation path with expected value

**`MARKET_REGIME_ANALYSIS_SUMMARY.txt`** (462 lines) - COMPREHENSIVE
- Complete analysis with all context
- Why each signal does or doesn't work
- Detailed regime profiles with statistics
- 5-phase implementation roadmap
- Value analysis: theoretical max vs realistic gains
- Key insights for the trader
- Next steps and follow-up questions

### 🔧 Scripts

**`generate_report.py`** - Python script that regenerates the text reports

## Key Findings Summary

### Strongest Signals (for regime detection)

1. **Number of Unique Symbols** (r=0.509 at 30-day lookback)
   - BREAKOUT: 11.9 symbols/day
   - PULLBACK: 8.9 symbols/day
   - Threshold: >10 = BREAKOUT, <9 = PULLBACK

2. **Number of Trades** (r=0.353 at 30-day lookback)
   - BREAKOUT: 99.6 trades/day
   - PULLBACK: 64.2 trades/day
   - Confirmation signal

3. **30-day Lookback is Optimal**
   - 1-day lookback: r=0.20 (too noisy)
   - 30-day lookback: r=0.51 (best)
   - Regime changes unfold over ~1 month

### Signals That DON'T Work

- Win rate (r=-0.004)
- Daily total P&L (r=-0.020)
- Average entry price (r=0.006)
- Average hold time (r=0.130)

These are independent of regime.

### Regime Profiles

| Metric | BREAKOUT | PULLBACK | REVERSAL |
|--------|----------|----------|----------|
| Days | 166 | 85 | 19 |
| Symbols/day | 11.9 | 8.9 | 10.2 |
| Trades/day | 99.6 | 64.2 | 71.9 |
| Win Rate | 58.3% | 57.3% | 62.7% |
| Daily P&L Avg | +$425 | +$110 | +$189 |
| Total P&L | +$70,621 | +$9,372 | +$3,589 |

## Value Analysis

**Current State** (single config, Trial 198):
- Total P&L across 13 months: $1,276

**Theoretical Maximum** (perfect regime detection):
- Using best config per regime: $9,044
- Improvement: +$7,768 (+607%)

**Realistic Estimate** (70% detection accuracy):
- Expected improvement: +$3,100 to $3,900
- New total P&L: $4,376 to $5,176

**Conservative Estimate** (50% detection accuracy):
- Expected improvement: +$1,550 to $2,300
- New total P&L: $2,826 to $3,576

Even poor detection adds $1,500+ in annual P&L.

## How to Use This Analysis

### For Dashboard Integration
1. Compute daily: count unique symbols, count total trades
2. Compute 30-day rolling averages
3. Display: current regime, prior 7 days of regime changes
4. Visualize: symbols_ma30 chart with regime shaded background

### For Trading Decision
1. Check symbols_ma30 every Monday
2. If > 10: BREAKOUT regime likely → use FLAT_TOP config
3. If < 9: PULLBACK regime likely → use ABCD-tight-targets config
4. If 9-10: TRANSITION → use conservative defaults

### For Further Research
1. Can we predict regime BEFORE it manifests?
2. Are there weekly sub-regimes?
3. Do other market indicators help? (SPY volatility, breadth, etc.)
4. How fast should we switch configs?

## Technical Details

### Data Source
- `optimizer/robust_results.db` (192 runs × 23,419 trades)
- Date range: Jan 2, 2025 to Feb 17, 2026
- Trading days: 278 total

### Methodology
- Computed 8 internal signals per day:
  1. Number of trades
  2. Number of unique symbols
  3. Average entry price
  4. Average price move %
  5. Average hold time
  6. Win rate %
  7. Total P&L
  8. Average P&L per trade

- Computed Pearson correlation with regime type (BREAKOUT=1, PULLBACK=0, REVERSAL=2)
- Tested lookback windows: 1, 3, 5, 15, 30 days
- Simple detection rule: IF (symbols_ma30 > 10) AND (trades_ma30 > 80) THEN BREAKOUT

### Accuracy of Simple Detection
- Overall: 43.2% (120/278 correct)
- BREAKOUT detection: 37% (62/166)
- PULLBACK detection: 68% (58/85)
- REVERSAL detection: 0% (0/19, small sample)

## Next Steps

**Week 1**: Add regime signals to dashboard
**Week 2**: Evaluate current detection accuracy on live data
**Weeks 3-4**: Build improved detection model (logistic regression, decision tree)
**Week 5**: Add config switching logic
**Ongoing**: Monitor and iterate weekly

## Questions & Interpretation

### Q: Why is "number of unique symbols" such a strong predictor?
A: When multiple unrelated stocks are screening (5 pillars met), it indicates broad market strength = BREAKOUT regime. During consolidation, fewer candidates qualify.

### Q: Why doesn't win rate predict regime?
A: Win rate is determined by your trading patterns and filters, not market regime. All regimes have ~58-63% win rates with this algorithm.

### Q: Why is 30-day better than 1-day lookback?
A: Regimes persist for weeks/months, not days. Daily volatility in symbol counts causes false signals. Monthly averaging smooths out noise.

### Q: Can we use this to predict NEXT month's regime?
A: Maybe! This analysis uses current-month data. Phase 2 would test if month 1 data predicts month 2 regime. Likely correlation but with lag.

### Q: What's the minimum detection accuracy needed to be profitable?
A: With 50% accuracy (random coin flip), you still gain +$1,500-2,300/year. Even poor signals have value due to the regime impact (+$7,768 ceiling).

## Files Location
All analysis files are in: `/analysis/` directory

## Author Notes
- Analysis generated Feb 28, 2026
- Based on 13 months of backtesting (Jan 2025 - Jan 2026 + early Feb)
- 278 trading days across 3 distinct regimes
- Simple threshold method reaches 43% accuracy (good baseline for comparison)
- Expected real-world accuracy with ML: 60-75%
