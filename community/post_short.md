Title: Spent months trying to automate Ross Cameron style small cap momentum, I think I finally know why it doesn't work, but want to hear from people who actually tried

So I've been building a bot (with a lot of AI help, being upfront about that) that tries to trade like Ross Cameron, low float gappers with news, and for a while my backtests looked great, like profit factor 3.3 great.. BUT, it turned out my sim was filling every stop exactly at the stop price, and once I fixed that it dropped to 0.58 lol. So that was humbling.

Since then I matched about 2,500 of his actual trades from his videos against historical data and found his edge seems to be mostly premarket stock selection, his picks beat other premarket movers by 1-2%, but nothing mechanical I tried copies it (gap, rel volume, float, news, even an LLM rating the headlines).

Couple questions:
1. Has anyone actually automated this style, and was tape / level 2 the thing that made it work?
2. What do real premarket fills look like for a bot on $2-20 gappers?
3. Is testing tape features worth it, or is it a dead end without full L2?

Happy to share way more detail if anyone wants it, I'm aware I might just be overthinking this.
