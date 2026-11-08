# The knowledge graph: audit of its inputs and a design to agree (S80, 2026-11-09)

**Status: audit and design only. Nothing was built, changed or switched on. The graph stays OFF and deleted (A46).** The numbers below are read-only measurements of the files the collectors keep (`data/bse_announcements`, `data/bse_scrip_isin`, `data/gkg`), taken on 2026-11-09.

## Why this note exists
You asked that the graph be "complete and reliable, even if that means adding news and filings", looked at carefully. The graph can only be as reliable as what feeds it, so this measures the feed first. A graph built on the feed as it is today would repeat what the 0/10 audit found: links nobody can check.

## What the feed is today
| Source | What it holds | Measured |
|---|---|---|
| BSE filings | 3.59 million announcements, 15 Aug 2015 to 24 Oct 2026, one file a day | Only 4 business days have none (all market holidays). 88% carry an attachment. |
| Scrip-to-ISIN map | 7,500 BSE scrip codes with the ISIN valid on each date | 400 scrips changed ISIN over time (handled by dates). 4.8% have no ISIN. Only 45% are in the market panel. |
| News (GDELT GKG) | 4,366 articles, 9 to 23 Oct 2026 only | About one ISIN per article. 80% are tagged India. No duplicate links. No article text is kept. |

## What is wrong or missing (each affects "reliable")
1. **16% of filings have no dissemination time.** Every filing before Aug 2015 and 5% of 2026's. Rule 1 says announcements use the dissemination timestamp, so these cannot be used point in time. Today they would need a stated fallback or be left out.
2. **15.5% of filings cannot be tied to an ISIN on their date** (checked on a 200,000-filing sample: 84.5% link, none ambiguously). The map's blank ISINs and unmapped scrips are the cause.
3. **4.4% are duplicates** (same scrip, headline and time).
4. **News covers 2 weeks.** "Adding news" means a backfill; the collector's older GDELT files are aggregates, not article-level links. Article text is not collected at all, so no model could read more than the headline and tags.
5. **No check ties a link to its proof.** The old graph kept links without the rule or source that made them, which is why an audit could not tell good links from bad.

## The design to agree (the A46 proposal, made concrete)
Three layers; a thing is in the graph only if it has an ISIN, a source and a date.
- **Facts** by ISIN, from structured sources only: instrument master, sector and industry, index membership, prices, results from the filings' own tables. Each row: source, as-of date.
- **Relations** by rule, with the rule named: same sector, same group, member of an index, supplier or customer only where a filing states it. No relation is written by a model.
- **Events** (filings, news) attached to a company only by a confident rule: a filing by its scrip-to-ISIN on its dissemination date; an article only when its ISIN tag and its organisation name agree. Anything else is kept unlinked and not shown.

**It switches on only when its audit passes.** The audit is code and runs every night. It must show: every node has an ISIN, a source and a date; no event is dated after the day it is used (zero point-in-time violations); at least 95% of events for held and listed names link to an ISIN; duplicates under 1%; a rebuild from the raw files gives the same graph byte for byte; and a hand-checkable sample of 100 links is printed each week with the rule behind each.

**It must also earn its place (rule 10).** A pre-registered study: does the storyline reader attach evidence correctly, and do storyline predictions hold more often, with graph facts than without? If not, the graph stays off, as the 5-6 Nov storyline layer already carries what the graph was meant to.

## What I need from you (none of it blocks anything tonight)
1. Do you agree to the three layers and the rule "nothing without an ISIN, a source and a date"?
2. How complete must it be: the stocks you hold and your list (about 20 names) plus their sector peers first, or all 7,500 scrips? I recommend the first.
3. News backfill: GDELT is free, but article-level history needs a long run on your laptop (hours, a few GB). How far back: 1 year is enough to test the study above.
4. Article text: collect it (the local model reads it, nothing goes to the cloud) or tags only?
5. For filings with no dissemination time: leave them out (my recommendation) or use the file's own date as a labelled estimate?

## What stays as it is
The graph code (`src/pflab/kg/`), its switch and the deletion are unchanged. Documents are kept. Filing-driven investigations stay stopped until you decide.
