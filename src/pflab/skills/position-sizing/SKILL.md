---
name: position-sizing
description: How the paper portfolio decides how much to put into one idea. Use when a BUY or ADD is being decided, or an existing holding is being trimmed. The numbers come from code (paper_decide sizes and cuts them); this skill says how to choose the intent.
---

# Position sizing (rupees, NSE; for the paper portfolio only)

Method adapted from the risk-based and fixed-fractional ideas in tradermonty/claude-trading-skills (MIT). The arithmetic is not yours: `paper_decide` turns your intent into a size and cuts it to the cash and the rails.

## Principles
1. **Size by what you can be wrong about, not by how sure you feel.** Name the price at which the idea is wrong (a level, a result, a filing). The money at risk is the distance to that level times the shares.
2. **No single idea may cost more than about 1% of the account if it is wrong.** For a long-term holding with no stop, use the weight rail instead: 10% a company, 25% a sector, 35% an ETF (code enforces these; do not ask for more).
3. **Start small, add on evidence.** A first buy is at most half of the target weight. Add only when something you named in advance has happened (a result, a filing, a fall to your level), never because the price rose.
4. **Cash is a position.** Say how much cash the account should hold and why; do not spend cash to look busy.
5. **Charges and tax count.** A trade that moves the weight by a few percent costs more in charges than it can gain; skip it. A sale of a holding with a large gain has an estimated tax; say what holding on would cost against selling.

## What to state in a decision
- the amount in rupees (or the target weight), the weight before and after, the price at which the idea is wrong, and what you will do if it is reached;
- the alternative you rejected (waiting, the index, a smaller amount).

## Never
- Averaging down into a holding because it is cheaper, without new evidence.
- Sizing from a model's own estimate of its confidence.
