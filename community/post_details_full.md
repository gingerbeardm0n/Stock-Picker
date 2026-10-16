# Full details (paste into replies only when someone asks)

## Setup
- Python bot, Alpaca paper for orders, Alpaca free historical SIP data for research.
- Strategies built on Ross Cameron's playbook: opening-bell scalp, VWAP reclaim, micro-pullback,
  all trading from 9:30 on 1-minute bars.

## What I got wrong
- Simulator filled stops exactly at the stop price, no gap-through. Fixing it (stop fills at
  min(stop, next bar open), 0.3% slippage on exits) turned my sealed 2025 test from PF 3.31 to
  PF 0.58. Live paper losers averaged ~$32 vs the old sim's ~$4, so the honest sim matched live.
- My historical database came from a snapshot list of $1–20 tickers, so delisted names were missing.
  Only 41% of Ross's traded stock-days were in it; a targeted backfill got it to 82%.
- Premarket on Alpaca is limit-only, so my 0.3% "slippage on a market order" assumption was the
  wrong model entirely for premarket.

## What I tested (all on 1-min bars, honest fills, hindsight removed)
- Parsed ~5,300 trades from summaries of ~1,800 of his videos; ~3,000 dated; 82% matched to bars.
- Copying his entries one minute late: average slightly positive, typical trade loses.
- After 9:30: his picks are no better than other gappers.
- Premarket (rebuilt a scanner: up 10%+, $1–20, 100k+ shares since 4am, checked every 15 min,
  ~11 flags/morning over 524 days):
  - buying every flag loses (−0.3% to −0.8% over 1–30 min)
  - his picks beat the other flagged stocks the same morning by +1.0% (10 min) / +1.8% (30 min)
- A model predicts WHICH stock he picks well (AUC ~0.85 out of sample), but its picks lose money.
- Buying the premarket breakout (new high after the flag): loses everywhere.
- News (Benzinga via Alpaca, 24h before flag): catalyst movers beat no-news movers by ~1%, but are
  ~flat in absolute terms. No-news movers fade reliably.
- Haiku rated 2,500 masked headlines 1–5: scores didn't sort outcomes; it rated his picks LOWER.
- Point-in-time float from SEC filings: his picks are low float (median ~11M vs ~31M) but low float
  alone or with news doesn't beat other movers.

## Where I think the edge is
Real-time tape / Level 2 in the seconds before he clicks, which 1-minute bars can't see.
Next free test: tape features from Alpaca historical trades; then maybe a Databento L2 pilot.
