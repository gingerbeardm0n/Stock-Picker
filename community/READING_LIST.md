# jTrader community audit — reading list (Oct 15, 2026)

Research sweep before asking the forums, so we only ask what reading can't answer.
Ranked by usefulness to us.

| # | Item | Takeaway | What it changes for us |
|---|------|----------|------------------------|
| 1 | Jiang, Li & Wang, "News Momentum" (SSRN 2667658, 2018) — https://www1.villanova.edu/dam/villanova/VSB/assets/marc/marc2018/SSRN-id2667658.pdf | News-driven returns continue; no-news returns reverse. Strongest in small firms and overnight news. | Matches our premarket result: catalyst movers beat no-news movers by ~1%, no-news movers fade. Daily horizon, so it doesn't confirm 10–30 min. |
| 2 | Chan, "Stock price reaction to news and no-news" (JFE 2003) | No-news extreme moves partly reverse; effects concentrated in small stocks. | Same direction as our fade finding; monthly horizon. |
| 3 | Barardehi, Bogousslavsky & Muravyev, "Day and Night Signals" (2022) — https://alphaarchitect.com/what-drives-momentum-and-reversal/ | Overnight (news) returns behave differently from intraday (trading) returns; intraday shows short-term reversal. | Supports treating premarket news moves separately from intraday flow. |
| 4 | Barber, Lee, Liu & Odean, "Cross-Section of Speculator Skill" — https://faculty.haas.berkeley.edu/odean/papers/day%20traders/Day%20Trading%20Skill%20110523.pdf | <1% of day traders earn predictable net profits, but the skill that exists is persistent. | Ross can be genuinely skilled and still not be replicable from rules. Consistent with "his picks beat look-alikes, our rules don't". |
| 5 | Alpaca orders docs — https://docs.alpaca.markets/docs/orders-at-alpaca | Extended hours (4:00–9:30) = limit orders only, day/gtc TIF, no brackets, trailing stops don't trigger. | **Our premarket fill model is wrong in kind**, not just in size: must be marketable-limit with non-fill risk, and stops must be client-side. |
| 6 | Barclay & Hendershott, RFS 2003 / JF 2004 | Extended-hours trading: <1/20 the trades, spreads 3–4× daytime. | 0.3%/side slippage is probably optimistic premarket. Measure real spreads from Alpaca historical quotes at our signal times. |
| 7 | Muravyev, Pearson & Pollet (NBER) — https://conference.nber.org/conf_papers/f184100/f184100.pdf | Borrow fees wipe out most short-side anomaly returns. | The "short no-news faders" idea is likely eaten by locate/HTB fees; don't build it without real borrow costs. |
| 8 | SEC Rule 201 (SSR) — https://www.sec.gov/news/press/2010/2010-26.htm | SSR triggers at −10% vs prior close and lasts that day and next. | Short-side constraint, minor for runners until they collapse. |
| 9 | Chordia & Subrahmanyam, "Order imbalance and individual stock returns" (JFE 2004) | Lagged order imbalance predicts short-horizon returns, but costs eat much of it. Classification is noisy per stock. | A tape test is plausible but low prior; premarket sparsity and wide spreads make Lee-Ready unreliable. |
| 10 | Databento pricing — https://databento.com/pricing | Nasdaq TotalView history from 2018-05, $/GB, $125 free credit. | Level 2 pilot is affordable if the tape test shows anything. |

**Answered by reading (don't ask the forums):** whether news vs no-news behave differently (yes);
whether Alpaca supports premarket market orders (no); SSR mechanics; that short-side fade edges
usually die on borrow costs.

**Still open (needs lived experience):**
1. Has anyone actually automated Warrior/Ross-style premarket small-cap momentum, and was tape/L2
   the thing that made it work, or did they conclude it's not automatable?
2. What do real premarket fills look like for a bot on $2–20 gappers (spread, non-fills, partials)?
3. Is a tape-feature test on free historical trades worth it, or is it a dead end without full L2?

Leads: r/algotrading "Reproduced Ross Cameron?" (id 1ke4tsr, 2025-05-03) — archive had no comments.
