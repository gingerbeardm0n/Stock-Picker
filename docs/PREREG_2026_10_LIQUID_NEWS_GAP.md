# Pre-registration: news gap-ups in liquid stocks (opening-range breakout)

_Written 2026-10-19, before any data for this test was pulled. This file is committed before the data
scripts run; the commit timestamp is the proof. One look at the results, no changes afterwards._

## Why this test (and why it is a new hypothesis, not a rescue)

- The Ross Cameron line ended on 2026-10-19 (`docs/DECISION_2026_10_ROSS_EDGE.md` §8). The clearest
  thing it taught us: in small caps, catalyst movers beat no-news movers by about 1%, but premarket
  spreads (median 0.71%, about 0.5% per side to cross) eat everything.
- Liquid stocks trade with far tighter spreads. If news-driven continuation exists there, it has a
  much lower cost wall to clear.
- Academic work: news-driven moves tend to continue while no-news moves reverse (Jiang, Li & Wang,
  "News Momentum"; Chan, JFE 2003). Practitioner hints (unverified): opening-range and
  break-of-high strategies on liquid names (u/FearlessAnalyst7039), and "apply the principles to a
  broader scope" (u/keeganm181).
- This targets different stocks, a different time (after the open) and a different entry from the
  Ross tests. Nothing about it was tuned on the Ross data.

## Hypothesis

Liquid US stocks that gap up at least 4% at the open on company-specific overnight news keep rising
after they break their first 5-minute range, by enough to profit after realistic costs.

## Rule (fixed)

**Universe each day**, using only information available before 09:30 ET:
- US common stocks from Alpaca's active and inactive asset lists, listed on NYSE, Nasdaq or NYSE
  American. NYSE Arca and Cboe BZX listings, and names containing ETF, ETN, Fund, Trust, Index,
  ProShares, iShares, SPDR, Direxion, 2X, 3X, Bull or Bear, are excluded. Tickers that aren't plain
  letters (class shares, units, warrants) are excluded.
- Prior close between $10 and $500.
- Average daily dollar volume (close × volume) over the prior 20 trading days of at least $50M.

**Signal**
- Opening gap: open of the first regular-session 1-minute bar (09:30, or 09:31 if 09:30 has no
  trade) is at least 4% above the prior close.
- Catalyst: at least one company-specific article (3 or fewer tagged symbols, not a roundup and not a
  "why shares are moving" reaction piece; the classifier in `premarket_news_test.py`) published
  between 16:00 ET on the prior trading day and 09:29 ET.

**Entry**
- Opening range = high and low of the 09:30–09:34 one-minute bars (at least 3 bars required).
- A buy-stop at the opening-range high + $0.01, live from 09:35 to 10:30. Fill = the greater of the
  trigger bar's open and the opening-range high + $0.01. Regular-hours stop orders are allowed, and
  these names are liquid.

**Exit**
- Stop at the opening-range low − $0.01, checked from the bar after the trigger bar, with honest
  fills: a bar that opens below the stop fills at its open; otherwise the fill is the lower of the
  stop and the next bar's open.
- Otherwise a time exit at the close of the 11:59 bar. No profit target.

**Costs:** 0.15% per side primary; 0.30% per side as the robustness check in criterion (d).
**Counting:** every qualifying stock-day is one trade (no cap per day), equal weight.
**Period:** 2021-01-04 to 2026-10-16. Data: Alpaca SIP daily bars, 1-minute bars and news (Benzinga).

## Pass bar (all five required)

- (a) at least 300 trades;
- (b) mean net return per trade above 0 at 0.15% per side, with the day-clustered 95% CI lower
  bound above 0;
- (c) positive mean net return in at least 4 of the 6 calendar years 2021–2026;
- (d) mean net return still above 0 at 0.30% per side;
- (e) not carried by outliers: the mean after dropping the best 1% of trades is still above 0.

Any failure closes this idea too.

## Report-only (never used to decide)

The same rule without the news requirement (all liquid gap-ups of 4% or more), and news vs no-news
paired by day; gap thresholds of 2% and 6%; a 15-minute opening range; a time exit at 10:30; R-multiple
statistics and exits by type; a sample of real quoted spreads at the entry minute.

## Known limits

Alpaca's inactive asset list misses some delisted tickers, so there is some survivorship, though much
less than for small caps. The headline classifier is keyword-based. Benzinga coverage of large caps
is good but not complete.

## Addendum (2026-10-19, before any data was pulled)

- Raw (unadjusted) prices are used throughout, so a reverse split looks like a +100% or larger gap.
  **Gaps above +60% are excluded** as split artifacts. Dollar volume is unaffected by splits.
- Alpaca's daily open was checked against the 09:30 minute-bar open on four large caps: they match
  exactly. So daily bars pre-screen gaps of 2% or more (the smallest report-only threshold), and
  minute bars and news are pulled only for those stock-days.
- Implementation: `research/analysis/scripts/liquid_gap_orb_test.py`, committed with this addendum.
