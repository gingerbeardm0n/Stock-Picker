# Concept: Daily Risk Rules

**Last updated:** 2026-05-07  
**Source:** RC_STRATEGY_STATISTICS.md — 1,787 sessions; jTrader_Audit_Against_Statistics.md rules #24-26  
**Critical finding:** Max-loss-hit sessions → 30.9% win rate, -$4,454/trade avg over 414 trades

---

## Definition

Daily risk rules are session-level circuit breakers that halt new entries when predefined loss or drawdown thresholds are reached. They are the structural equivalent of Ross Cameron saying "I'm done for the day" — implemented as hard enforcement rather than intention.

**The core insight:** The worst trades of the entire dataset happen AFTER daily risk rules are triggered but not enforced. These are not edge cases — 414 trades (7.9% of all trades) occurred after max-loss was hit, destroying $1.76M in P&L.

---

## The Three Rules

### Rule 1: Max Daily Loss
**Threshold:** Account-specific (typically 2-3% of account or a fixed dollar amount)  
**Trigger:** `daily_pnl <= -max_loss_limit`  
**Action:** Block all new entries for the remainder of the session

**Data:**
| State | Trades | Win Rate | Avg Result | Total P&L |
|-------|--------|----------|------------|-----------|
| Max loss hit = TRUE | 414 | 30.9% | -$4,454 | **-$1,759,282** |
| Max loss hit = FALSE | 4,663 | 68.0% | +$2,479 | +$10,959,810 |

414 trades after max-loss hit = $1.76M destroyed. 4,663 trades before = $10.96M earned.

Ross's own rule: *"When I hit my max loss, I'm done. I don't try to recover it."*

### Rule 2: Green-to-Red
**Threshold:** Session went positive at some point, then crossed back below zero  
**Trigger:** `session_peak_pnl > 0 AND current_daily_pnl <= 0`  
**Action:** Block all new entries for the remainder of the session

**Rationale:** Going green-to-red triggers the same emotional response as a pure loss day — but it's worse, because there's the psychological anchor of "I was up." This creates the most aggressive revenge-trading behavior. Stopping at breakeven is far better than trying to get back to the earlier high.

**Ross's rule:** *"If I go green to red, I'm done. I'd rather finish at breakeven than risk going deeper red chasing a recovery."*

### Rule 3: Give-Back-Half
**Threshold:** Gave back 50% of session peak P&L  
**Trigger:** `session_peak_pnl > 0 AND current_daily_pnl < session_peak_pnl * 0.5`  
**Action:** Block new entries; or reduce position size to minimum

**Example:**
- Session peak: +$3,000 at 9:52am
- Give-back threshold: +$1,500
- If P&L drops to $1,499 → Rule fires
- Remaining trades blocked; day locked in at $1,500+ profit

**Rationale:** Big green days getting erased is the most common "disaster" recap topic in the 1,787 sessions. The emotional difficulty of watching gains disappear leads to larger and more desperate trades. A hard mechanical stop prevents the avalanche.

**Ross's rule:** *"If I give back half, that's a hard stop. I don't negotiate with myself on this one."*

---

## Current jTrader Status: OBSERVE-ONLY

All three rules exist in `PortfolioManager` but only LOG when they would fire — they do not enforce:

```python
# Current broken implementation (production/trading/portfolio_manager.py)
if self.daily_pnl <= -self.max_loss_limit:
    self.logger.warning("MAX_LOSS_HIT")  # logs, does nothing
    # MISSING: self.halt_new_entries = True
```

This means jTrader can observe "I hit max loss" and immediately take another trade anyway. Same for green-to-red and give-back-half. The rules exist in name only.

**Fix required:** `PortfolioManager` must set `halt_new_entries = True` when any rule fires, and `entry_engine.evaluate_entry()` must check this flag before returning a signal.

---

## Rule Interaction and Priority

The three rules are independent — any one firing halts entries:

```
Priority (checked in order):
1. Max loss     — fires at a specific negative number
2. Green-to-red — fires when positive session turns negative
3. Give-back-half — fires when peak gains are halved

Rules are non-resetting: once fired, they stay active for the session.
Rules reset daily at session open.
```

Edge case handling:
- Max loss fires FIRST if P&L is deeply negative (rule 2 can't fire if you never went green)
- Give-back-half fires BEFORE max loss on profitable days that reverse (you were +$2K, now +$900 → give-back-half fires before you reach -max_loss)
- On a day that goes: +$3K → +$500 → -$500 → all three rules would fire in sequence if the trader keeps going

---

## Calibration

These thresholds are not fixed — they should scale with account size and session context:

| Account Size | Max Loss Limit | Notes |
|--------------|----------------|-------|
| $5K–$10K | $250–$500 | 2.5-5% of account |
| $10K–$50K | $500–$2,000 | 2-4% of account |
| $50K–$100K | $1,500–$3,000 | 2-3% of account |
| $100K+ | $2,000–$5,000 | 1.5-2% of account; larger accounts can absorb more |

**Ross's framework:** Max loss = roughly 1 "good trade" worth of profit. If his average good trade makes $2,000, his max loss is $2,000. This keeps worst-case losses bounded to a single mistake.

**Give-back-half calibration:** Fixed at 50% — this is the rule as stated. No need to tune.

**Green-to-red calibration:** Fixed trigger (zero crossing) — but can add a buffer. "If I give back $200 below zero" rather than "exactly at zero" reduces false triggers on volatile days.

---

## Session-Level P&L Tracking Requirements

To enforce these rules, `PortfolioManager` needs to track:

```python
@dataclass
class SessionState:
    daily_pnl: float = 0.0          # Current session P&L
    session_peak_pnl: float = 0.0   # Highest P&L reached this session
    halt_new_entries: bool = False   # Set True when any rule fires
    halt_reason: str = ""           # Which rule fired
    
    def update_pnl(self, realized_pnl_delta: float):
        self.daily_pnl += realized_pnl_delta
        self.session_peak_pnl = max(self.session_peak_pnl, self.daily_pnl)
        self._check_risk_rules()
    
    def _check_risk_rules(self, cfg: RiskConfig):
        if self.halt_new_entries:
            return  # Already halted
        
        # Rule 1: Max loss
        if self.daily_pnl <= -cfg.max_loss_limit:
            self.halt_new_entries = True
            self.halt_reason = f"MAX_LOSS_HIT (pnl=${self.daily_pnl:.0f})"
            return
        
        # Rule 2: Green-to-red
        if self.session_peak_pnl > 0 and self.daily_pnl <= 0:
            self.halt_new_entries = True
            self.halt_reason = f"GREEN_TO_RED (peak=${self.session_peak_pnl:.0f})"
            return
        
        # Rule 3: Give-back-half
        if (self.session_peak_pnl > 0 
                and self.daily_pnl < self.session_peak_pnl * 0.5):
            self.halt_new_entries = True
            self.halt_reason = f"GIVE_BACK_HALF (peak=${self.session_peak_pnl:.0f})"
```

---

## Relationship to Behavioral Deviation

Daily risk rules are the **structural enforcement** of behavioral deviation prevention. See `concept_behavioral_deviation.md` for the full deviation analysis. The connection:

- Deviation sessions: 49.2% win rate
- Max-loss-hit sessions (subset of deviation): 30.9% win rate
- Max-loss-hit is the endpoint of the deviation cascade: bad trade → revenge trade → max loss hit → desperate trades → -$4,454/trade avg

Stopping at max-loss prevents the cascade from reaching its worst point. The 30.9% / -$4,454 avg represents the *continuation* trades after max-loss — trades that should never be taken.

---

## jTrader Implementation Checklist

- [ ] `PortfolioManager._check_risk_rules()` — implement the enforcement, not just logging
- [ ] `entry_engine.evaluate_entry()` — check `portfolio_manager.halt_new_entries` before Gate 1
- [ ] `RiskConfig` dataclass — add `max_loss_limit`, `giveback_pct` (default 0.5) thresholds
- [ ] Session reset — `halt_new_entries = False` at session start each day
- [ ] Logging — emit structured log events when each rule fires (for backtest analysis)
- [ ] Optuna scope — `max_loss_limit` is a Category A parameter (scanner/risk), optimize it

---

## Data Confidence

| Finding | Sample Size | Confidence |
|---------|-------------|------------|
| Max-loss-hit win rate (30.9%) | 414 trades | High |
| Max-loss-hit avg result (-$4,454) | 414 trades | High |
| Non-max-loss win rate (68.0%) | 4,663 trades | Very High |
| Green-to-red / give-back triggers | Qualitative from recaps | Medium |
| Threshold calibration by account size | Inferred from strategy | Low — needs optimization |
