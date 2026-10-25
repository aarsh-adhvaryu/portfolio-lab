# Tijori check (S56, PLAN A8): before the investor buys

Checked 2026-10-23 on Tijori's own pages. No page shows a revision date; each carries only "© 2026 Tijori Financial
Services Private Limited". The quotes are as the pages read that day.

## Plans and prices (https://www.tijorifinance.com/plans/)

| plan | price on the page | what it adds |
|---|---|---|
| Free | "₹ 0" | 1 portfolio, 1 watchlist, 5 alerts; 10 years of financial statements and shareholding; the latest period of market share, revenue mix, 1,000+ operational metrics, raw materials, macro, sector research; screener for popular and public queries |
| Monthly | "₹ 330 / month" | everything in Free, plus 5 portfolios, 10 watchlists, unlimited alerts, in-depth comparison of financials, reverse DCF, **historic** data for 6,000+ operational metrics and the other datasets, source links, unlimited screener queries |
| Yearly | "₹ 3,500 / year" ("SAVE 12%", "₹292 /Month") | the same as Monthly |
| Premium | (no price of its own) | the same features under the name used on the feature pages: "Premium" is the paid tier, bought monthly or yearly |

The page shows no GST line: whether tax is added at checkout is not stated (see it at checkout before paying).

## The Excel export

- The plans and features pages do not mention Excel, CSV, export or download.
- The FAQ (https://www.tijorifinance.com/faq/): "Can I download financial data?" "Yes. Financial data downloads are
  available to paid subscribers." Format, limits and which datasets are not stated.
- APIs: "Public developer APIs are currently limited." Enterprise or custom data needs: contact support.
- Some data cannot be shared at all: raw-material prices "because of our licensing agreements".

## Using the data with an AI (https://www.tijorifinance.com/terms-of-use)

- Use is limited to "your own personal, non-commercial use"; other use needs Tijori's prior written permission
  (clause 3).
- Users may not "copy, reproduce, recompile, decompile, assemble, disassemble, distribute" any part of the service
  (clause 2); clause 3 bars using the contents "including copying or storing it" beyond personal use, and to
  "reproduce, publish, transmit, distribute, display, modify" or sell them.
- The terms say nothing about automated access, software, AI or models.

Reading: the system's own use (an export read on this PC into the knowledge graph, for the investor alone) is personal and
non-commercial. Sending an export's contents to the API analyst (Opus) for his own research could be read as a
transmission. **The investor's decision 2026-10-23:** the exports are public company data, not his own, and they go to the
analyst and the research like Screener's; `tijori_to_analyst = false` under `[api]` in `pm\api_budget.toml` stops it.

## Refunds and cancelling

- Cancellation policy (https://www.tijorifinance.com/cancellation-policy): "There would not be any refunds on
  cancellation of your subscription"; cancelling 48 hours before the renewal date stops the next bill.
- The FAQ differs: "Refund requests raised within 48 hours of subscription activation are eligible for a refund".
  The two pages conflict; the narrower reading is the safe one (try Monthly before Yearly).

## For the investor (his call)

1. If bought: Monthly first (₹330) to see the download's format and limits before a year (₹3,500).
2. Drop a download into Inbox and files ("Market-data export"); the system reads it locally into the graph.
3. The analyst reads the export beside the filings (The investor's decision above).
