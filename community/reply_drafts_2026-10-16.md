# Reply drafts (Oct 16, 2026) — r/Daytrading post 1x6uae6

Written to sound like Joel (see feedback_joel_writing_voice). Edit freely, change any phrase you
wouldn't say out loud. Post them yourself, spread over the day rather than all at once, and reply
directly under each person's comment.

---

## 1. u/Partnikl (execution / the 3.40 → 3.48 example)

the 3.40 to 3.48 thing is exactly what bit me on the exit side Partnikl lol, my sim was filling every stop at exactly the stop price and when I fixed that the whole backtest went from amazing to losing money. havent done the same check on entries yet but I think Alpaca lets you pull the actual historical prints so my plan is to line up my entry times against what really traded and see how far off I am. do you trade premarket with limit orders or is there some way to get market orders through? Alpaca makes me use limits before the open and I honestly have no idea how many I'd miss

---

## 2. u/GamingDisruptor (his crowd piles in when he enters)

honestly hadn't thought about that GamingDisruptor, but it might explain a lot. his picks seem to keep running in my data even when I cant find anything on paper that separates them from stocks that look the same, so maybe some of it is just his crowd piling in right behind him.. BUT, if thats true its kind of depressing because a bot obviously cant copy that lol. I think I can check it a little though, I have rough entry times for a lot of his trades so I could look at volume in the minutes right after he gets in vs similar stocks that morning

---

## 3. u/Worldly-Following-63 (only works in a hot market)  — uses the test finished today

you might be right about this Worldly-Following-63, I went and checked it with my data. when the small cap market was cold (not many gappers day to day) his picks were basically flat, and when it was middle or hot they did way better, and his own numbers say the same thing, in the trades I pulled out of his videos he wins about 72% on hot days and 54% on cold ones. my sample is only about 500 mornings so when I split it by year the error bars get huge and I wouldn't bet money on it, BUT it pointed the same direction in 2022 and 2023 so I don't think its just noise. the other thing I found is that even in hot markets just buying everything my scanner flags still didn't make money, so hot helps him but it doesn't turn a dumb scanner into a good one

---

## 4. u/traderpier (test the pick on its own)

I did kind of a version of this traderpier, took the stocks he traded and bought them at random minutes before the open and they beat the other premarket movers from the same morning by a percent or two, but after the open his picks were basically the same as any other gapper so it only shows up premarket. I also tried a stop right under his entry candle and that came out slightly negative. so I think the picking is where whatever edge there is lives, just not sure how you turn that into something a bot can trade yet

---

## 5. u/Aggressive_Listen849 (halts)  — short, goodwill

good call on halts Aggressive_Listen849, I think Partnikl is right that there arent LULD halts premarket so it matters more after 9:30, but my sim doesnt model halts at all right now so I should probably look at what happens to a stop that sits through a reopen for the regular hours stuff

---

## 6. u/Square-Middle-4474 (the "do your homework" comment)  — OPTIONAL, fine to skip

fair, I have read a ton of what he says about it, I turned about 1,800 of his videos into a trade log so I'm not totally coming in cold lol. the stuff he calls in play (gap, relative volume, float, news) I tested all of it and none of it separates his picks from stocks that look the same on paper, so I figured theres something he does that isn't showing up in the numbers. if you know a specific video where he walks through how he decides I would honestly love the link, I've watched a lot of them but could have missed it

---

## Facts behind each draft (so you can defend them if someone pushes back)

- Sim exit fix: stops used to fill exactly at the stop price; honest fills took the sealed 2025 test from profit factor 3.31 to 0.58 (docs/DEEP_REVIEW_2026_09.md).
- Alpaca premarket = limit orders only (docs.alpaca.markets/docs/orders-at-alpaca).
- His picks vs other premarket movers, same morning, random entry from his pick time to 9:30: +0.96% (10 min), +1.76% (30 min), both with confidence ranges above zero. After 9:30: no difference.
- Stop under his entry candle, 2× target, entering one minute after him: about −0.1R/trade (ross_oracle_entry_test.py).
- Market temperature (market_temperature_test.py): cold ≤10.4 small-cap gappers/day (trailing 20 days), hot >15.4. In cold his picks ≈ flat; middle/hot clearly positive. Same direction in 2022 and 2023, confidence ranges wide when split by year. Buying every flagged stock lost or broke even in all three.
- His "72% hot / 54% cold": RC_STRATEGY_STATISTICS.md §6 (self-reported, and the hot/cold label comes from his own videos, so it's partly circular, which is why the draft says "his own numbers").
- Rough voice tells kept: lowercase starts, dropped apostrophes, "lol", ".." and one capitalized "BUT,". Left out on purpose: em dashes, bullet lists, "great point", tidy sign-offs.
