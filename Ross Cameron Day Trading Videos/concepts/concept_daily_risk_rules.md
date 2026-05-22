# Concept: Daily Risk Rules

**Last updated:** 2026-05-21  
**Source:** Full corpus analysis — TRANSCRIPT_SUMMARIES_0001-1799 (all 1,799 sessions) + RC_STRATEGY_STATISTICS.md  
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

### Rule 4: Daily Profit Goal Reached — Stop (Positive Circuit Breaker)
**Threshold:** Session P&L >= daily_profit_goal  
**Trigger:** `daily_pnl >= daily_profit_goal`  
**Action:** Stop taking new entries; optionally reduce position size if already in a trade

**Data from corpus:**  
"Daily goal reached" is the single most common reason for session end across 1,799 sessions (831 session-end entries reference "goal reached" / "achieved goal" / "daily goal hit"). Sessions that stop at daily goal are overwhelmingly profitable. Sessions that continue past the goal often give back gains — the TWWG example shows scaled from $7→$9.20, "gave back" before final exit at $20,790.

**Ross's rule:** "When I hit my daily goal, I'm done. I'd rather bank the win than chase more." (Observed across many sessions; goal is typically $1K-$2K/day at standard size.)

**Why it belongs with the loss rules:** The asymmetry is that traders enforce MAX LOSS rigorously but ignore daily profit stops. Both sides of the equation matter equally. Continuing to trade after daily goal creates "give-back" risk that rivals a bad loss day.

**Calibration:**
- Conservative: stop at 1x average daily goal (e.g., $500 for a $5K account)
- Moderate: stop at 2x average daily goal; reduce size by 50% at 1x
- Hot day override: if market is HOT, extend goal threshold by 50% (tempting to let winners run, but must still reduce size after goal)

---

## The Risk Cascade (Critical Pattern)

Full-corpus analysis reveals a consistent cascade in max-loss-hit sessions:

```
Trigger event (first bad trade)
    ↓
Position OVERSIZE (to recover quickly)
    ↓
Second bad trade (oversized = larger loss)
    ↓  
REVENGE TRADE (emotional, not setup-based)
    ↓
Max loss hit
    ↓
Continued trading (if rule not enforced)
    ↓
-$4,454/trade avg, 30.9% win rate
```

**Key finding:** In virtually every max_loss_hit session, `behavioral_deviation` includes **both** "oversize" and "revenge-trade". Oversize is always the FIRST behavioral signal — it appears before revenge trading and before max loss. This means:

- **Oversize detection = earliest warning** the day is going wrong
- If jTrader detects position size > planned, flag it before it becomes a loss cascade
- A single bad trade handled at normal size rarely reaches max loss alone

**Context amplifiers (high-risk conditions):**
- `prior_day = loss` → 2x more likely to oversize next session
- `month_context = in-drawdown` → highest frequency of cascade failures
- `acct_state = in-drawdown` → combined with prior-day loss = maximum risk
- Premarket max losses possible (FILE 1019: max loss hit at 8:38am before market open)

---

## Intermediate Soft Rule: Size Reduction

Between "trade normally" and "halt entries" there is a documented intermediate state observed across hundreds of sessions:

**`size_context = "reduced"`** appears in sessions that avoid max loss despite early losses.

**Soft Rule:** After first losing trade where session P&L goes negative:
1. Reduce position size by 50% for all subsequent entries
2. Do not raise size back up until session P&L returns positive
3. If P&L drops below -0.5× max_loss_limit at reduced size: halt entries entirely

This matches Ross's observed pattern of "taking it smaller" on difficult days before fully walking away. It adds a buffer step that can convert a potential max-loss day into a controlled -$200 day.

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

- [ ] `PortfolioManager._check_risk_rules()` — implement enforcement, not just logging
- [ ] `entry_engine.evaluate_entry()` — check `portfolio_manager.halt_new_entries` before Gate 1
- [ ] `RiskConfig` dataclass — add `max_loss_limit`, `giveback_pct` (0.5), `daily_profit_goal` thresholds
- [ ] **Soft rule**: reduce `max_position_pct` by 50% after first losing trade puts session P&L negative
- [ ] **Rule 4**: halt entries when `daily_pnl >= daily_profit_goal`
- [ ] Session reset — `halt_new_entries = False`, `soft_size_reduced = False` at session start each day
- [ ] Premarket coverage — rules must fire 4am–9:30am, not just regular session
- [ ] Logging — emit structured log events when each rule fires (for backtest analysis)
- [ ] Optuna scope — `max_loss_limit` is Category A; `daily_profit_goal` also tunable
- [ ] Context amplifiers — when `prior_day = loss` AND `month_context = in-drawdown`, lower `max_loss_limit` by 25%

---

## Data Confidence

| Finding | Sample Size | Confidence |
|---------|-------------|------------|
| Max-loss-hit win rate (30.9%) | 414 trades | High |
| Max-loss-hit avg result (-$4,454) | 414 trades | High |
| Non-max-loss win rate (68.0%) | 4,663 trades | Very High |
| max_loss_hit=true sessions | ~106 sessions from chunk files | High |
| "Oversize + revenge" cascade pattern | Consistent across all max_loss files | High |
| Daily profit goal as session-end | 831 "goal" session-end entries | High |
| Green-to-red / give-back triggers | Qualitative from recaps | Medium |
| Premarket max loss applicability | 1 confirmed (8:38am) | Low — rare but documented |
| Context amplifier (prior-day loss) | Observed pattern, not quantified | Medium |
| Threshold calibration by account size | Inferred from strategy | Low — needs Optuna optimization |
| Soft size reduction rule | Observed in "reduced" sessions | Medium |
