"""
Entry fill model — marketable-limit simulation (docs/SIM_FILL_MODEL_DESIGN.md).

The perfect-fill sims enter at the signal bar's close, instantly, for free.
Live orders are marketable limits (signal close + headroom) that can MISS when
the stock keeps running — adverse selection the perfect model can't see.

`fill_model` on the strategy config selects the behavior:
    'perfect'          — legacy: fill at signal price on the signal bar (default)
    'marketable_limit' — limit at signal price × (1 + entry_headroom_pct/100);
                         resolved against the NEXT bar: open ≤ L fills at open,
                         low ≤ L fills at L, otherwise the order misses and the
                         symbol keeps being evaluated (mirrors the live cancel/
                         re-signal loop). A pending order holds a concurrency
                         slot for that one bar, like live's in-flight wait.

`entry_slippage_pct` adds flat slippage on top of any fill (robustness knob).
"""

from __future__ import annotations


def limit_price(base_price: float, config) -> float:
    """Marketable-limit price for a signal at `base_price`."""
    headroom = getattr(config, 'entry_headroom_pct', 0.25)
    return round(base_price * (1 + headroom / 100), 2)


def resolve_limit_fill(limit: float, next_bar: dict) -> float | None:
    """Fill price against the bar after the signal, or None on a miss.

    open ≤ L  → filled at the open (gap down through the limit)
    low ≤ L   → filled at L (traded through the limit intra-bar)
    else      → miss
    """
    o = float(next_bar['open'])
    if o <= limit:
        return o
    if float(next_bar['low']) <= limit:
        return limit
    return None


def resolve_market_fallback(signal_price: float, next_bar: dict, config) -> float | None:
    """When a limit misses, check if a market retry would fill within the cap.

    Live behavior: if ask ≤ signal × (1 + market_fallback_pct/100), retry
    with market order → fills at the ask. In sim we use next bar's open as
    the market fill price (best available proxy for "immediate market fill").
    """
    cap_pct = getattr(config, 'market_fallback_pct', 0.0)
    if cap_pct <= 0:
        return None
    cap_price = signal_price * (1 + cap_pct / 100)
    bar_open = float(next_bar['open'])
    if bar_open <= cap_price:
        return bar_open
    return None


def apply_slippage(fill_price: float, config) -> float:
    slip = getattr(config, 'entry_slippage_pct', 0.0)
    return fill_price * (1 + slip / 100)


def uses_marketable_limit(config) -> bool:
    return getattr(config, 'fill_model', 'perfect') == 'marketable_limit'


# ── Exit fill model (Gate 0, docs/DEEP_REVIEW_2026_09.md §1/§4) ────────────
#
# All three engines' evaluate_exit() return the TRIGGER level (the stop /
# target / trail price the bar touched, or the bar close for a time_stop /
# end_of_data forced exit) — unchanged, so the live runners (which share
# evaluate_exit) are untouched by any of this.
#
# The simulator decides how that trigger becomes a booked fill:
#   'par'    — legacy: fill AT the trigger level (today's numbers, bit for
#              bit). Never apply exit slippage in this mode.
#   'honest' — NEW DEFAULT:
#     stop_loss:            fill = min(trigger, next_bar_open); if the
#                            TRIGGER bar's own open already gapped through
#                            the stop, fill at that open instead.
#     target/trail/time/EOD: fill = next_bar_open; falls back to the
#                            trigger bar's close if there is no next bar.
#     exit_slippage_pct applied adversely (price * (1 - pct/100)) to every
#     'honest' fill, stop included.

def uses_honest_exit_fill(config) -> bool:
    return getattr(config, 'exit_fill_mode', 'honest') == 'honest'


def apply_exit_slippage(price: float, config) -> float:
    slip = getattr(config, 'exit_slippage_pct', 0.3)
    return price * (1 - slip / 100)


def resolve_honest_exit_fill(
    exit_signal: dict, trigger_bar: dict, next_bar: dict | None, config,
) -> tuple[float, float]:
    """Resolve a triggered exit_signal to (trigger_price, fill_price) under
    'honest' fill rules.

    exit_signal:  dict returned by an engine's evaluate_exit() — must carry
                  'exit_price' (the trigger level) and 'exit_type'.
    trigger_bar:  the bar on which evaluate_exit fired.
    next_bar:     the bar immediately after trigger_bar, or None if the
                  trigger bar was the last available bar for the symbol.
    """
    trigger_price = float(exit_signal['exit_price'])
    reason = exit_signal.get('exit_type')

    if reason == 'stop_loss':
        trig_open = float(trigger_bar['open'])
        if trig_open <= trigger_price:
            raw_fill = trig_open  # gap at open: already through the stop
        elif next_bar is not None:
            raw_fill = min(trigger_price, float(next_bar['open']))
        else:
            raw_fill = float(trigger_bar['close'])
    else:
        # profit_target / trailing_stop / time_stop / end_of_data / other
        if next_bar is not None:
            raw_fill = float(next_bar['open'])
        else:
            raw_fill = float(trigger_bar['close'])

    fill_price = apply_exit_slippage(raw_fill, config)
    return trigger_price, fill_price
