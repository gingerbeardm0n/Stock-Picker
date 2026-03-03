"""
Portfolio Manager
=================
Observes portfolio-level state and records when daily risk rules WOULD have fired.

This is an OBSERVER — it never stops a trade or changes simulation behavior.
It logs counterfactual events so we can analyze:
  - Would the daily max loss rule have triggered on this day?
  - Would the green-to-red rule have fired? Did it save or cost us money?
  - Would the give-back-half rule have protected gains?

By comparing pnl_at_fire vs final_day_pnl we can determine, for each rule:
  - saved_or_cost > 0 → following the rule would have SAVED money
  - saved_or_cost < 0 → following the rule would have COST money (exited too early)

This lets us answer the question: does an automated algorithm even need these rules?

Usage (in simulation loop):
    pm = PortfolioManager(account_size=5000, daily_max_loss_pct=3.0, daily_profit_target=150.0)

    # At start of each trading day:
    pm.reset_day()

    # After every trade fill (closed or scaled):
    new_events = pm.update(current_time, pnl_delta, trades_completed_count)

    # At end of trading day:
    summary = pm.get_daily_summary(final_realized_pnl)
"""

from __future__ import annotations
import pytz
from datetime import datetime

ET = pytz.timezone('US/Eastern')


class PortfolioEvent:
    """A single portfolio rule fire event (immutable record)."""
    __slots__ = (
        'rule', 'time', 'pnl_at_fire', 'peak_pnl_before',
        'trades_completed', 'extra',
    )

    def __init__(self, rule: str, time: datetime, pnl_at_fire: float,
                 peak_pnl_before: float, trades_completed: int, extra: dict = None):
        self.rule = rule                          # 'DAILY_MAX_LOSS', 'GREEN_TO_RED', 'GIVE_BACK_HALF'
        self.time = time                          # UTC timestamp of fire
        self.pnl_at_fire = round(pnl_at_fire, 2) # Daily P&L when rule would have fired
        self.peak_pnl_before = round(peak_pnl_before, 2)  # Highest P&L seen today before fire
        self.trades_completed = trades_completed  # Completed trade count at fire time
        self.extra = extra or {}                  # Rule-specific additional context

    def to_dict(self) -> dict:
        et_str = self.time.astimezone(ET).strftime('%H:%M') if self.time else None
        return {
            'rule': self.rule,
            'time_et': et_str,
            'pnl_at_fire': self.pnl_at_fire,
            'peak_pnl_before': self.peak_pnl_before,
            'trades_completed': self.trades_completed,
            **self.extra,
        }


class PortfolioManager:
    """
    Observes daily P&L state and detects when portfolio risk rules would have fired.

    Rules tracked:
        DAILY_MAX_LOSS   — Loss exceeds daily_max_loss_pct of account
        GREEN_TO_RED     — Account was profitable, then dipped negative
        GIVE_BACK_HALF   — Hit daily_profit_target, then gave back >50% of peak

    Parameters
    ----------
    account_size : float
        Starting account balance (used for % thresholds).
    daily_max_loss_pct : float
        Rule fires when daily loss >= this % of account. Default: 3.0%
    daily_profit_target : float | None
        Dollar P&L that must be reached before give-back-half applies.
        Defaults to account_size * 3% (same as daily_max_loss).
        Example: $150 on a $5K account. None = use 3% of account.
    """

    def __init__(self, account_size: float,
                 daily_max_loss_pct: float = 3.0,
                 daily_profit_target: float | None = None):
        self.account_size = account_size
        self.daily_max_loss_threshold = account_size * daily_max_loss_pct / 100.0

        # Give-back-half: default to same dollar amount as max loss
        # (symmetric risk/reward = daily goal matches daily max loss)
        if daily_profit_target is None:
            self.daily_profit_target = self.daily_max_loss_threshold
        else:
            self.daily_profit_target = daily_profit_target

        # State (reset each day via reset_day())
        self._daily_pnl = 0.0         # Running realized P&L today
        self._peak_daily_pnl = 0.0    # Highest realized P&L seen today
        self._was_profitable = False   # True once daily_pnl went positive

        # Per-rule fire state (reset each day)
        self._rule_fired: dict[str, bool] = {
            'DAILY_MAX_LOSS': False,
            'GREEN_TO_RED': False,
            'GIVE_BACK_HALF': False,
        }
        self._rule_fire_pnl: dict[str, float | None] = {
            'DAILY_MAX_LOSS': None,
            'GREEN_TO_RED': None,
            'GIVE_BACK_HALF': None,
        }
        self._rule_fire_time: dict[str, datetime | None] = {
            'DAILY_MAX_LOSS': None,
            'GREEN_TO_RED': None,
            'GIVE_BACK_HALF': None,
        }

        # All events for this day (cleared by reset_day)
        self.events: list[PortfolioEvent] = []
        self._trades_completed = 0

    # ── Day Lifecycle ──────────────────────────────────────────────────────────

    def reset_day(self):
        """Reset all daily state. Call once at the start of each simulated trading day."""
        self._daily_pnl = 0.0
        self._peak_daily_pnl = 0.0
        self._was_profitable = False
        self._trades_completed = 0
        for rule in self._rule_fired:
            self._rule_fired[rule] = False
            self._rule_fire_pnl[rule] = None
            self._rule_fire_time[rule] = None
        self.events = []

    # ── Main Update ────────────────────────────────────────────────────────────

    def update(self, current_time: datetime, pnl_delta: float,
               trades_completed: int) -> list[PortfolioEvent]:
        """
        Update portfolio state after a trade fill. Returns any new events that fired.

        Call this every time a trade closes or scales out (whenever pnl_delta != 0).

        Args:
            current_time      : UTC timestamp of the fill
            pnl_delta         : P&L from this specific fill (positive = win, negative = loss)
            trades_completed  : Total completed trades so far today (for event context)

        Returns:
            List of PortfolioEvent objects for rules that fired THIS update (may be empty).
        """
        self._daily_pnl += pnl_delta
        self._trades_completed = trades_completed

        # Update peak and profitable flag
        if self._daily_pnl > self._peak_daily_pnl:
            self._peak_daily_pnl = self._daily_pnl
        if self._daily_pnl > 0:
            self._was_profitable = True

        return self._check_rules(current_time)

    # ── Rule Evaluation ────────────────────────────────────────────────────────

    def _check_rules(self, current_time: datetime) -> list[PortfolioEvent]:
        """Evaluate all portfolio rules. Each rule fires at most once per day."""
        new_events = []

        # ── Rule 1: Daily Max Loss ─────────────────────────────────────────────
        # Fire when today's realized loss >= daily_max_loss_threshold
        if not self._rule_fired['DAILY_MAX_LOSS']:
            if self._daily_pnl <= -self.daily_max_loss_threshold:
                event = PortfolioEvent(
                    rule='DAILY_MAX_LOSS',
                    time=current_time,
                    pnl_at_fire=self._daily_pnl,
                    peak_pnl_before=self._peak_daily_pnl,
                    trades_completed=self._trades_completed,
                    extra={
                        'threshold': -round(self.daily_max_loss_threshold, 2),
                        'loss_amount': round(-self._daily_pnl, 2),
                    },
                )
                self._rule_fired['DAILY_MAX_LOSS'] = True
                self._rule_fire_pnl['DAILY_MAX_LOSS'] = self._daily_pnl
                self._rule_fire_time['DAILY_MAX_LOSS'] = current_time
                new_events.append(event)
                self.events.append(event)

        # ── Rule 2: Green-to-Red ───────────────────────────────────────────────
        # Fire once: account was profitable today, then dipped below zero
        if not self._rule_fired['GREEN_TO_RED']:
            if self._was_profitable and self._daily_pnl < 0:
                event = PortfolioEvent(
                    rule='GREEN_TO_RED',
                    time=current_time,
                    pnl_at_fire=self._daily_pnl,
                    peak_pnl_before=self._peak_daily_pnl,
                    trades_completed=self._trades_completed,
                    extra={
                        'crossed_zero_by': round(-self._daily_pnl, 2),
                    },
                )
                self._rule_fired['GREEN_TO_RED'] = True
                self._rule_fire_pnl['GREEN_TO_RED'] = self._daily_pnl
                self._rule_fire_time['GREEN_TO_RED'] = current_time
                new_events.append(event)
                self.events.append(event)

        # ── Rule 3: Give-Back-Half ─────────────────────────────────────────────
        # Fire when: peak_pnl reached daily_profit_target AND gave back >50% of peak
        # Condition: peak >= target AND current < peak * 0.50
        if not self._rule_fired['GIVE_BACK_HALF']:
            if (self._peak_daily_pnl >= self.daily_profit_target
                    and self._daily_pnl < self._peak_daily_pnl * 0.5):
                gave_back = self._peak_daily_pnl - self._daily_pnl
                event = PortfolioEvent(
                    rule='GIVE_BACK_HALF',
                    time=current_time,
                    pnl_at_fire=self._daily_pnl,
                    peak_pnl_before=self._peak_daily_pnl,
                    trades_completed=self._trades_completed,
                    extra={
                        'gave_back': round(gave_back, 2),
                        'gave_back_pct': round(gave_back / self._peak_daily_pnl * 100, 1),
                        'target_was': round(self.daily_profit_target, 2),
                    },
                )
                self._rule_fired['GIVE_BACK_HALF'] = True
                self._rule_fire_pnl['GIVE_BACK_HALF'] = self._daily_pnl
                self._rule_fire_time['GIVE_BACK_HALF'] = current_time
                new_events.append(event)
                self.events.append(event)

        return new_events

    # ── End-of-Day Analysis ────────────────────────────────────────────────────

    def get_daily_summary(self, final_realized_pnl: float) -> dict:
        """
        Compute end-of-day analysis for all rules.

        For each rule that fired, calculates:
            saved_or_cost = pnl_at_fire - final_pnl
            > 0 → following the rule would have SAVED money (locked in better P&L)
            < 0 → following the rule would have COST money (exited early, missed gains)

        Args:
            final_realized_pnl: Actual realized P&L at end of trading day.

        Returns:
            Dict with analysis for each rule (see schema below).
        """
        rules_analysis = {}
        any_fired = False

        for rule in ('DAILY_MAX_LOSS', 'GREEN_TO_RED', 'GIVE_BACK_HALF'):
            if self._rule_fired[rule]:
                any_fired = True
                pnl_at_fire = self._rule_fire_pnl[rule]
                fire_time = self._rule_fire_time[rule]
                saved_or_cost = pnl_at_fire - final_realized_pnl
                et_str = fire_time.astimezone(ET).strftime('%H:%M') if fire_time else None
                rules_analysis[rule] = {
                    'fired': True,
                    'fire_time_et': et_str,
                    'pnl_at_fire': round(pnl_at_fire, 2),
                    'final_pnl': round(final_realized_pnl, 2),
                    'saved_or_cost': round(saved_or_cost, 2),
                    'verdict': 'SAVED' if saved_or_cost > 1.0 else (
                               'NEUTRAL' if abs(saved_or_cost) <= 1.0 else 'COST'),
                }
            else:
                rules_analysis[rule] = {'fired': False}

        return {
            'any_rule_fired': any_fired,
            'final_pnl': round(final_realized_pnl, 2),
            'peak_pnl': round(self._peak_daily_pnl, 2),
            'rules': rules_analysis,
            'events': [e.to_dict() for e in self.events],
        }

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def daily_pnl(self) -> float:
        """Current running daily P&L (read-only)."""
        return self._daily_pnl

    @property
    def peak_daily_pnl(self) -> float:
        """Highest realized P&L seen today (read-only)."""
        return self._peak_daily_pnl

    @property
    def was_profitable(self) -> bool:
        """True if daily P&L was positive at any point today."""
        return self._was_profitable

    def any_rule_fired(self) -> bool:
        """True if at least one rule has fired today."""
        return any(self._rule_fired.values())
