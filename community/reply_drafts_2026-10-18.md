# Reply drafts (Oct 18, 2026) — new comments on r/Daytrading post 1x6uae6

Same rules as the Oct 16 file. Nothing posted yet. The Oct 16 drafts are 2 days old now, so
post those today too. Post them yourself, spread out, directly under each person's comment.

---

## 1. u/keeganm181 (most useful new comment)

keeganm181 I went and tested the pullback thing since you brought it up, waited for 1 to 4 red candles and then bought the first candle to make a new high, on every premarket mover my scanner flagged over about 500 mornings, and it lost about the same as just buying the flag lol. with a stop right under the pullback low it got stopped out more than half the time, and it only got to roughly breakeven on the stocks Ross actually picked. so I think the edge is more which stock he picks than the entry, but I'm honestly not sure. do you use a hard stop or are you actually watching the tape to get out? and ha, same boat on the AI built bot

---

## 2. u/Unable_Sympathy2151 (how did you match his trades?)

yeah thats fair to push on and honestly I cant fully know. all I have is what he says in his recap videos, I had AI read the transcripts of about 1,800 of them and pull out the ticker, the price, and whether it won or lost, then I matched those to historical price data. so what I really tested is the trades he chose to talk about, not a broker statement, and he could be skipping the ones he doesnt want to show. he does show a lot of red days tho, about a third of the trades I pulled were losers, so I dont think its only highlights, but yeah its his word and a youtube video lol

---

## 3. u/Most_Atmosphere8365 (short and sweet)

thanks Most_Atmosphere8365, that kinda answers all three of my questions at once lol. the walls and thin books thing is what I keep coming back to, I think I'm gonna try the tape data first since I think its free to pull and see if anything shows up before I pay for real level 2

---

## Skip these
- u/Rpark444: troll ("will never be in Market Wizards").
- u/Professional-Way1622: reads like a plug for a research product. Ignore.
- u/O-L_1337: nothing new (L2 consensus). A one-line "ha fair, hopefully not quantum" is fine if you want, not needed.

## Facts behind the drafts
- Premarket pullback test (premarket_pullback_test.py, Oct 18): 1-4 red 1-min candles, depth 2-20%, then a bar whose high exceeds the last red bar's high; buy the next bar's open, 0.3%/side. 3,292 trades over 515 days: -0.69% at 10 min, -1.03% at 30 min; buying at the flag was -0.77% / -1.04%. With stop = pullback low - $0.01, 2R target, 30 min limit: -0.41R/trade, stopped out 55%. Ross's picks (hindsight selection): -0.10R (CI -0.28 to +0.09); other hits -0.46R.
- Ledger: ~1,800 transcripts, summaries of 1,787 entries, 5,261 trades, 1,771 losses (33.7%) per RC_STRATEGY_STATISTICS.md. Entry times are estimated from price touches.
- Tape: Alpaca historical trades on the free key is assumed free but not yet confirmed (minute bars with feed=SIP older than 15 minutes did work), hence "I think its free".
