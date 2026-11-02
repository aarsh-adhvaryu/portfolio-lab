---
name: trade-memory-postmortem
description: How the paper portfolio learns from its own decisions. Use when a mission starts (read the lessons first), when a claim has matured, and when a lesson contradicts what you are about to decide.
---

# Trade memory and postmortem

Adapted from the thesis-tracking and postmortem skills in tradermonty/claude-trading-skills (MIT). The system keeps every decision with its claim and scores it at 7, 28, 84 and 182 days against the Nifty 500 (keeping cash is scored against what cash earned). Code writes the lessons; you read them.

## At the start of a mission
- Read `WHAT ITS OWN RECORD HAS TAUGHT IT` in the dossier. If a lesson says a kind of decision in this kind of market has held less than half the time, say so and say why this decision is different, or do not make it.
- Read the open HOLD and WAIT decisions: their reopening conditions may have been met.

## When you decide
- State the claim your decision makes in one sentence a later check can score ("this name beats the index over 28 days"; "waiting gives a better price within 28 days").
- A lesson with fewer than 5 scored claims is a count, not a conclusion. Do not build on it; do not ignore it either.

## The reviewer's record
The lessons include how the reviewer's refusals turned out. If refused decisions keep holding more often than the executed ones, the review may be too strict; if the executed ones keep failing, it may be too lenient. Say which you see; do not change the review yourself.

## After a bad claim
Write what you assumed that turned out wrong (a fact, a price, a result) in the next decision's reasons, so the same mistake is visible.
