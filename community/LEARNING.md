# What the community told us

Sources: r/Daytrading post 1x6uae6 (ours, Oct 15) and related post 1x3995y ("I automated Ross
Cameron's small-cap momentum rules into a bot", Oct 11). Raw text: replies_2026-10-16.md.

| Takeaway | Who | Changes anything for us? |
|---|---|---|
| Premarket gappers are an execution game: half a second = 10¢; a big order can sweep the offer from $3.40 to $3.48, so stress-test fills against actual prints, not the trigger price | u/Partnikl | **Yes** — measure fills from Alpaca historical trades/quotes at our signal times; our 0.3% slippage is likely optimistic |
| Ross's audience (hundreds/thousands) piles in when he enters | u/GamingDisruptor | **Open question** — would explain why his picks continue while look-alikes fade, and why it can't be copied mechanically. Possibly testable: volume surge right after his entry vs look-alikes |
| His system only works in a HOT small-cap market; cold/sideways months he makes little | u/Worldly-Following-63 | **Yes, testable** — split our premarket results by market temperature (e.g. number of 10%+ gappers that morning / that month) |
| Test the pick alone: buy his called names at the open with one fixed stop | u/traderpier | Mostly done: after 9:30 his picks ≈ other gappers; premarket they beat them. Could add the fixed-stop version |
| LULD halts: stops fill at the reopen print, 10%+ away | u/Aggressive_Listen849 (corrected by u/Partnikl: no LULD premarket) | Yes for regular hours; already partly modeled by honest gap fills |
| Order-flow automation found edge at tiny timescales, but needs queue-position modeling → competing with HFT | (1x3995y thread) | Sobering: tape/L2 edge may exist but be unexecutable for us |
| Databento free credit, MBO data; measure tape speed, spread, pulled orders, absorption, icebergs; fragmented books are hard, so one practitioner switched to futures (single book) | u/bobbo6969- (1x3995y) | **Open** — the concrete L2 recipe if we go there; futures as a cleaner venue idea |
| Tick-level Alpaca backtest engine shared with live engine; ORB / break-of-HOD strategies on ~40 liquid tickers positive 2021–2026 | u/FearlessAnalyst7039 (1x3995y) | **Open** — liquid names + ORB, not low-float gappers; same engine for sim/live like our parity work |
| "Ross explains how he decides a stock is 'in play' in his videos, do your homework" | u/Square-Middle-4474 | Rude, but the corpus has an "in play" concept we could re-check. Low priority |

Ignore / skip: meme images, "connect with me" offers (u/auto8ot).
