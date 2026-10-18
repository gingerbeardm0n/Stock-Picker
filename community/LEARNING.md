# What the community told us

Sources (updated Oct 18, 13 comments on ours): r/Daytrading post 1x6uae6 (ours, Oct 15) and related post 1x3995y ("I automated Ross
Cameron's small-cap momentum rules into a bot", Oct 11). Raw text: replies_2026-10-16.md.

| Takeaway | Who | Changes anything for us? |
|---|---|---|
| Premarket gappers are an execution game: half a second = 10¢; a big order can sweep the offer from $3.40 to $3.48, so stress-test fills against actual prints, not the trigger price | u/Partnikl | **Yes** — measure fills from Alpaca historical trades/quotes at our signal times; MEASURED Oct 18 (premarket_spread_check.py): median premarket spread 0.71%, a third over 1%; 0.3%/side is about the median half-spread only, optimistic for the wide third |
| Ross's audience (hundreds/thousands) piles in when he enters | u/GamingDisruptor | **Open question** — would explain why his picks continue while look-alikes fade, and why it can't be copied mechanically. Possibly testable: volume surge right after his entry vs look-alikes |
| His system only works in a HOT small-cap market; cold/sideways months he makes little | u/Worldly-Following-63 | **Yes, testable** — split our premarket results by market temperature (e.g. number of 10%+ gappers that morning / that month) |
| Test the pick alone: buy his called names at the open with one fixed stop | u/traderpier | Mostly done: after 9:30 his picks ≈ other gappers; premarket they beat them. Could add the fixed-stop version |
| LULD halts: stops fill at the reopen print, 10%+ away | u/Aggressive_Listen849 (corrected by u/Partnikl: no LULD premarket) | Yes for regular hours; already partly modeled by honest gap fills |
| Order-flow automation found edge at tiny timescales, but needs queue-position modeling → competing with HFT | (1x3995y thread) | Sobering: tape/L2 edge may exist but be unexecutable for us |
| Databento free credit, MBO data; measure tape speed, spread, pulled orders, absorption, icebergs; fragmented books are hard, so one practitioner switched to futures (single book) | u/bobbo6969- (1x3995y) | **Open** — the concrete L2 recipe if we go there; futures as a cleaner venue idea |
| Tick-level Alpaca backtest engine shared with live engine; ORB / break-of-HOD strategies on ~40 liquid tickers positive 2021–2026 | u/FearlessAnalyst7039 (1x3995y) | **Open** — liquid names + ORB, not low-float gappers; same engine for sim/live like our parity work |
| "Ross explains how he decides a stock is 'in play' in his videos, do your homework" | u/Square-Middle-4474 | Rude, but the corpus has an "in play" concept we could re-check. Low priority |
| "Lost cause without L2 + T&S, and still very hard with them." His main entry is waiting for a pullback, then the next green candle making a new high (avoids the flush); news-bump entries dump below their starting price within 3 one-minute candles; "when do you sell without watching tape?"; AI-built bot also failed; this market is tearing Ross up too, flat/negative since September except one ~$50k squeeze | u/keeganm181 | **Yes**: (1) the entry he describes is a micro-pullback, NOT the premarket breakout we tested (that lost), now TESTED Oct 18 (premarket_pullback_test.py): loses about the same as buying the flag, -0.41R with a stop under the pullback low; (2) matches the hot/cold market finding; (3) the exit-without-tape problem is our exit weakness |
| Discretion is what makes discretionary strategies work; expect slippage, delay, partial or no fills; L2 shows walls, support, spreads, thin books | u/Most_Atmosphere8365 | Reinforces L2/tape; answers all three of our questions |
| "How do you know you matched his trades, there's no record beyond YouTube?" | u/Unable_Sympathy2151 | **Yes, a real limitation**: our ledger is the trades he chose to discuss in recaps (self-reported; about a third are losses, so not only highlights); entry times are estimated |
| Bot can't read L2 fast enough; experience and tape reading can't be hard-coded | u/O-L_1337 | No new info, same L2 consensus |
| Rules that look obvious afterwards aren't obvious in real time; make entry and skip conditions measurable | u/Professional-Way1622 | Generic; also mentions a research product, likely a plug. Ignore |
| "Wasting your time, Ross will never be in Market Wizards" | u/Rpark444 | No |

Ignore / skip: meme images, "connect with me" offers (u/auto8ot).
