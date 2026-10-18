# Reply drafts (Oct 18, 2026) — new comments on r/Daytrading post 1x6uae6

Same rules as the Oct 16 file. Nothing posted yet. The Oct 16 drafts are 2 days old now, so
post those today too. Post them yourself, spread out, directly under each person's comment.

---

## 1. u/keeganm181 (most useful new comment)

this is super helpful keeganm181. I did test buying a stock when it breaks its premarket high after getting flagged and it lost money pretty consistently, but now that I read this thats not what you're describing, you wait for the pullback first and then the next green candle to a new high, and I havent tested that one premarket yet so gonna try it. the 3 candle flush thing makes a lot of sense too, I think thats been wrecking my exits. do you use a hard stop or are you actually watching the tape to get out? and ha, same boat on the AI built bot, mine has found a lot of creative ways to lose money lol

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
- Premarket breakout test (new high after the flag): lost for all hits and for Ross look-alikes (ross_confirmation_news_test.py). Micro-pullback premarket: never tested (our MP strategy only trades from 9:30).
- Ledger: ~1,800 transcripts, summaries of 1,787 entries, 5,261 trades, 1,771 losses (33.7%) per RC_STRATEGY_STATISTICS.md. Entry times are estimated from price touches.
- Tape: Alpaca historical trades on the free key is assumed free but not yet confirmed (minute bars with feed=SIP older than 15 minutes did work), hence "I think its free".
