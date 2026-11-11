# Step back: where an edge could still exist (2026-11-11)

_Written after the 10th failed test in a row. No new data was pulled for this page; it only reads the results
already recorded in `STATUS.md`, `docs/DECISION_2026_10_ROSS_EDGE.md` and the `docs/PREREG_2026_10_*.md` files._

## What the results say when read together

| Test | Hold | Gross (before costs) | Net |
|---|---|---|---|
| Old scalp / VWAP / micro-pullback (honest fills) | minutes | ~0 | negative |
| Ross-style entries, breakouts, pullbacks, float, tape, AI headline rating | minutes | ~0 | negative |
| Liquid news gap-up + opening-range breakout | minutes-hours | ~0 | -0.38% |
| Stocks-in-Play 5-minute ORB (published paper) | intraday | ~0 | -1.01R |
| SPY/QQQ intraday momentum (published paper) | 30 min | ~0 | negative all years |
| No-news gap fade | intraday | +0.29%, CI spans 0 | fails at 0.30%/side |
| Level 2 book imbalance | minutes | +0.09%, CI spans 0 | negative |
| Mid-session catalyst headline drift | 30 min | +0.13% | -0.17% |
| Ross premarket news picks vs other movers | intraday | +1.0-1.8% **paired** | about flat absolute |

Three conclusions:

1. **Every intraday rule is about zero before costs.** That is not bad luck in rule design. Two of the rules
   were published, peer-reviewed results and they did not reproduce either. Liquid US stocks within the day
   are priced by firms that see the same minute bars and the same Benzinga headlines seconds earlier. With
   public data and 1-minute bars we are looking at moves that are already taken.
2. **Small caps have more mispricing, but the spread is the price of it.** Ross's selection edge (+1%) is
   about the size of a premarket round trip (median spread 0.71%). The inefficiency is real; we pay it away.
3. **The one stable finding is news versus no-news.** It held in every universe and every year we looked:
   stocks moving on real news behave better than stocks moving without it. We have only ever tried to
   collect it **within the same day**, which is exactly where the first two points say it gets eaten.

## Where an edge can still live, given our constraints

Constraints: retail account, fully autonomous (no human clicks), free or cheap data (Alpaca SIP bars + Benzinga
news since 2016, about $124 Databento credit that needs Joel's OK per spend), no speed advantage.

- **Faster or better data:** ruled out. We lose any speed race, and the L2 pilot showed book data adds nothing we
  can use.
- **Providing liquidity (limit orders, earn the spread):** in theory it turns the cost into income, but honest
  testing needs queue position and tick data we do not have. Minute bars would flatter it (same trap as the old
  par-fill simulator). Not testable honestly; skip.
- **Longer holds (days, not minutes):** the strongest remaining option. A 0.30% round trip is fatal against a
  +0.13% half-hour drift but small against a multi-day move. Published work fits our own finding closely:
  stocks with real news tend to **keep drifting for days to weeks**, stocks that jump without news tend to
  **reverse** (Chan 2003, "Stock price reaction to news and no-news"; also post-earnings-announcement drift,
  strongest in small, less-covered stocks). This is the same news-vs-no-news split we keep finding, measured on
  the horizon where it is known to survive costs.

## Recommendation

**Stop testing intraday entry rules on public minute bars.** Ten fails are enough evidence that this data at this
horizon has nothing left for us.

**Next test: multi-day drift after news days (the jTrader stock list, held for days).**
- Same selection jTrader already uses: stocks that gap or move on a fresh catalyst headline (premarket news, the
  thing Ross does well), versus movers without news.
- Enter at the **close of the news day** (a slow, autonomous entry, no speed race, no premarket spread), hold
  1 / 5 / 20 trading days, long news movers; report-only short leg on no-news movers.
- Data: Alpaca daily bars (active + inactive assets, to avoid survivorship) and the Benzinga news already
  collected. Free. Daily bars make it fast: hours, not days.
- As always: a pre-registered rule, pass bar and costs committed before any outcome is pulled; one look.

This keeps jTrader's core (Ross-style news selection, autonomous execution) and changes only the holding period.
It overlaps with jSwing in style; it does not replace jTrader.

If this fails too, the honest reading is that the news effect is fully priced at every horizon we can reach, and
the next conversation should be about whether jTrader continues as research at all.
