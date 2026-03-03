#!/usr/bin/env python3
"""
Debug script: trace each entry gate for ARBE on Jan 6, 2025.
Run: python research/maintenance/diagnostics/debug_arbe.py
"""
import sys
import os
# Add production to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../production')))

from dotenv import load_dotenv
load_dotenv()
from utils.query_helpers import StockDataDB
from trading.indicators import (estimate_buy_sell_volume, is_trending_up,
    volume_on_up_bars_dominates, get_current_ema, calculate_macd)
from trading.patterns import explain_pattern_rejection
from trading.models import EntryConfig
import pytz

DATE = '2025-01-06'
SYMBOL = 'ARBE'
PRIOR_CLOSE = 2.63
MIN_RV = 5.0
MIN_BUYING = 50_000
MIN_GAIN = 10.0
BAR_HISTORY_SIZE = 30   # Must match simulation_engine.BAR_HISTORY_SIZE
ET = pytz.timezone('US/Eastern')

with StockDataDB() as db:
    bars = db.get_minute_bars([SYMBOL], DATE, start_hour=4, end_hour=12).get(SYMBOL, [])
    print(f'Total ARBE bars loaded: {len(bars)}')
    print()
    print('Using SIMULATION-accurate logic: last-%d bars for Gate 3, cumulative vol for rel_vol' % BAR_HISTORY_SIZE)
    print()
    print('Time    Close  Gain%    CumRV    Buy   EMA9   Trend VolUp  MACD      Gate')
    print('-' * 96)

    cum_vol = 0.0  # Accumulated today's volume (matches simulation _cumulative_volume)

    for i, bar in enumerate(bars):
        cum_vol += float(bar['volume'])   # Step 1 of _process_minute

        et = bar['time'].astimezone(ET)
        if et.hour < 9 or (et.hour == 9 and et.minute < 30):
            continue
        if et.hour >= 11:
            break

        price = float(bar['close'])
        gain = (price - PRIOR_CLOSE) / PRIOR_CLOSE * 100

        # rel_vol with CUMULATIVE numerator (the fix)
        avg_vols = db.get_avg_volume_at_time_batch(
            [SYMBOL], DATE, et.hour, et.minute, lookback_days=20
        )
        avg_vol = avg_vols.get(SYMBOL, 0)
        rv = cum_vol / avg_vol if avg_vol > 0 else 0.0

        # Buying pressure on the current bar
        bv, sv = estimate_buy_sell_volume(
            bar['open'], bar['high'], bar['low'], bar['close'], bar['volume']
        )
        buy_ok = (bv >= MIN_BUYING) and (bv > sv)

        # Gate 3: use only the last BAR_HISTORY_SIZE bars (matches rolling window)
        # _process_minute appends THEN evaluates, so bar_history at this point includes current bar.
        # entry_engine receives history[:-1] (excludes current) + current_bar
        all_bars_from_history = bars[max(0, i - BAR_HISTORY_SIZE + 1): i + 1]
        prices = [float(b['close']) for b in all_bars_from_history]
        ema9 = get_current_ema(prices, 9)
        macd = calculate_macd(prices)
        macd_ok = True if macd is None else (macd['histogram'] > 0)
        trend = is_trending_up(all_bars_from_history)
        vol_up = volume_on_up_bars_dominates(all_bars_from_history)

        ema_ok = (ema9 is None) or (price >= ema9)
        g2_pass = gain >= MIN_GAIN and rv >= MIN_RV and buy_ok

        if not g2_pass:
            if rv < MIN_RV:
                gate = 'G2:rv=%.1fx' % rv
            elif not buy_ok:
                gate = 'G2:buyvol'
            else:
                gate = 'G2:other'
        elif not ema_ok:
            gate = 'G3:ema(%.2f)' % ema9
        elif not macd_ok:
            gate = 'G3:macd(%.3f)' % macd['histogram']
        elif not trend:
            gate = 'G3:trend'
        elif not vol_up:
            gate = 'G3:vol_up'
        else:
            gate = 'G4:pattern?'

        ema_str = '%.2f' % ema9 if ema9 else 'N/A  '
        macd_str = '%+.3f' % macd['histogram'] if macd else 'None '
        t_str = 'T' if trend else 'F'
        v_str = 'T' if vol_up else 'F'
        b_str = 'T' if buy_ok else 'F'
        hist_count = len(all_bars_from_history)

        print('%s  %5.2f  %5.1f%%  %7.1fx  %s  %s  %s  %s  %s  %s  [h=%d]' % (
            et.strftime('%H:%M'), price, gain, rv,
            b_str, ema_str, t_str, v_str, macd_str, gate, hist_count
        ))

        # For Gate 4 failures, show WHY each pattern rejected
        if gate == 'G4:pattern?':
            indicators_dict = {
                'ema9': ema9,
                'macd_histogram': macd['histogram'] if macd else None,
                'trending_up': trend,
                'vol_up_dominates': vol_up,
            }
            rejection = explain_pattern_rejection(all_bars_from_history, indicators_dict, EntryConfig())
            for pattern, reason in rejection.items():
                print('         %-16s  %s' % (pattern + ':', reason))
