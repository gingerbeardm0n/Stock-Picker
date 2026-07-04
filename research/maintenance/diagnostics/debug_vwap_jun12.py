"""Debug why VWAP sim didn't trade AERT on 2026-06-12."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production'))

from datetime import date
from utils.query_helpers import StockDataDB
from trading.live_vwap_runner import TRIAL_173_CONFIG as cfg
from trading.scalp_ranker import rank_candidates
from trading.vwap_models import WATCH_TOP_N
from simulator.vwap_simulation import VwapSimulationRunner

trade_date = date(2026, 6, 12)
runner = VwapSimulationRunner(trade_date, config=cfg, verbose=True)

with StockDataDB() as db:
    # Phase 1: gappers
    candidates = db.find_gappers(trade_date, min_gap_pct=cfg.min_gap_pct, max_price=cfg.max_price)
    print(f"\n=== Phase 1: {len(candidates)} gappers (min_gap={cfg.min_gap_pct}%, max_price=${cfg.max_price}) ===")
    aert = [c for c in candidates if c['symbol'] == 'AERT']
    if aert:
        print(f"  AERT found: {aert[0]}")
    else:
        print("  AERT NOT in gappers — filtered at Phase 1 (gap% or price)")
        # Check what AERT's actual gap was
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT symbol, open, close, prev_close,
                   CASE WHEN prev_close > 0 THEN (open/prev_close - 1)*100 END as gap_pct
            FROM stock_candles_1d
            WHERE symbol = 'AERT' AND bucket = %s
        """, [trade_date])
        row = cursor.fetchone()
        if row:
            print(f"  AERT daily: open={row[1]}, close={row[2]}, prev_close={row[3]}, gap%={row[4]}")
        else:
            print("  AERT has no daily bar for this date!")
        cursor.close()
        sys.exit(0)

    # Phase 2: enrich
    enriched = runner._enrich_candidates(db, candidates)
    aert_e = [c for c in enriched if c['symbol'] == 'AERT'][0]
    print(f"\n=== Phase 2: enriched AERT ===")
    print(f"  rel_vol={aert_e.get('rel_vol'):.2f} (min={cfg.min_relative_volume})")
    print(f"  has_news={aert_e.get('has_news')} (require={cfg.require_news})")
    print(f"  news_tier={aert_e.get('news_tier')}")
    print(f"  float={aert_e.get('float_shares')}")

    # Phase 3: filter
    filtered = runner._apply_filters(enriched)
    print(f"\n=== Phase 3: {len(filtered)} pass filters ===")
    aert_f = [c for c in filtered if c['symbol'] == 'AERT']
    if not aert_f:
        print("  AERT FILTERED OUT!")
        if aert_e.get('rel_vol', 0) < cfg.min_relative_volume:
            print(f"    -> rel_vol {aert_e.get('rel_vol'):.2f} < {cfg.min_relative_volume}")
        if cfg.require_news and not aert_e.get('has_news', False):
            print(f"    -> require_news=True but has_news={aert_e.get('has_news')}")
        sys.exit(0)

    # Phase 4: rank
    ranked = rank_candidates(filtered)
    top_n = ranked[:WATCH_TOP_N]
    print(f"\n=== Phase 4: top {WATCH_TOP_N} watchlist ===")
    for i, c in enumerate(top_n):
        print(f"  #{i+1}: {c['symbol']} gap={c.get('gap_pct',0):.1f}% rv={c.get('rel_vol',0):.1f} news={c.get('has_news')}")

    aert_rank = next((i for i, c in enumerate(ranked) if c['symbol'] == 'AERT'), None)
    if aert_rank is not None:
        print(f"\n  AERT ranked #{aert_rank+1} of {len(ranked)}")
        if aert_rank >= WATCH_TOP_N:
            print(f"  -> NOT in top {WATCH_TOP_N} watchlist!")

    # Phase 5: check bars exist
    if aert_rank is not None and aert_rank < WATCH_TOP_N:
        bars = db.get_minute_bars(['AERT'], trade_date, start_hour=9, end_hour=13)
        aert_bars = bars.get('AERT', [])
        print(f"\n=== Phase 5: AERT has {len(aert_bars)} minute bars ===")
        if aert_bars:
            print(f"  First: {aert_bars[0].get('time')} o={aert_bars[0].get('open')} c={aert_bars[0].get('close')}")
            print(f"  Last:  {aert_bars[-1].get('time')}")
