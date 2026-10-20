# Impact connector: user guide

Present this in plain language, sized to the question. Run no queries in help mode.

## What it does

Impact shows what happened after someone clicked a creator's link: clicks, sales, revenue,
commission. ThoughtLeaders shows what happened before: which creator, which video, when it went
live, views, what the sponsorship cost. This skill lines the two up, so you can ask things like
"which of our sponsorships drove the most sales per 1,000 views?"

## What you need

This reads your own brand's Impact account; it isn't for creators.

- Your TL login (the `tl` CLI).
- One way into Impact:
  - Impact's connector for Claude: add a custom connector with the URL
    `https://mcp.impact.com/mcp`, enter `mcp-impact-claude` as the OAuth client ID under Advanced
    settings, and sign in. You'll also be asked for one Advanced Action Listing export, the only
    Impact report with each sale's status.
  - The Impact API, with a token you create in Impact (Settings → Technical → API). Read-only
    access is enough.
  - CSV exports from Impact's Reports (Performance by Partner or by Day, plus the Advanced Action
    Listing), dropped into the chat.

It only reads your Impact data and never changes, approves or deletes anything. Never paste an
Impact password or token into the chat.

## What you get

Always: each Impact partner matched to its TL channel, with how it was matched and how sure the
match is. Every partner is in one group: booked through TL, a creator TL knows but you booked
elsewhere, or not a TL creator (coupon sites, blogs).

Your choice of views (you'll be asked if you don't say):
- **Deal scorecard:** one row per sponsorship, or a go-live timeline when the creator's videos
  share one link.
- **Creator rollup:** one row per channel across its sponsorships.
- **Decay over time:** week by week after each video went live, to see whether a creator is
  declining. Impact's all-time totals hide this.

Every figure comes from last-click credit in your own Impact account: it counts sales that came
through the creator's link or code, not sales the video caused some other way. Treat costs and
returns as a floor on what a sponsorship did, not a verdict.

## How matching works

Every clue is checked, strongest first: the tracking link, the links on the Impact partner's
profile, the partner's name or the creator's handles on any platform, a TL id stored in the link,
and a promo code containing the creator's name. A promo-code match is double-checked, for example
against the date of the first TL video. If a partner with approved sales could be more than one TL
channel, you're asked which to include.

A creator's YouTube, TikTok and Instagram deals are read together. Deals that aren't YouTube videos
(podcasts, newsletters, TikTok, Instagram) have no TL views, so they're listed but left out of
view-based figures. If TL doesn't have a creator's channel yet, you'll be asked for the link; its
TL data takes about a day.

## Dates

- If each video has its own link, results are tied to that exact sponsorship.
- If the videos share one link (common), you get a go-live timeline: each date the creator went
  live for you, and what Impact recorded until the next go-live. Earlier videos were still live
  during each period. A video that went live before your date range is included, since it can
  still bring in sales.
- When some videos have their own link and others share one, the first are reported individually
  and the rest as periods.
- Sales that can still be cancelled ("pending") are shown next to approved ones, marked "may still
  change".

## Costs and currencies

- **Booked through TL:** the TL price is the source of truth.
- **Never booked through TL:** what you paid through Impact is. You'll be shown the creator's
  videos that mention your brand and asked which ones you paid for, then get the CPM on what you
  paid and whether the creator's projected views have risen or fallen since.
- The TL price and the Impact commission are shown separately, and added together only in an
  "All-in cost to date" box under the table, over the same videos and dates, with an as-of date.
- Everything is in US dollars, as TL prices are. Impact figures in another currency, such as euros,
  are converted at the European Central Bank's monthly average rate, with the original and the rate
  shown. The TL price is never converted. If a TL deal records another currency, its price stays as recorded and the USD figures
  that depend on it wait for confirmation.

## Impact terms in TL language

| Impact says | TL meaning |
|---|---|
| Partner | The creator or channel (sometimes an agency with several) |
| Program (or Campaign) | Your affiliate program, not a TL campaign |
| Action | A conversion: sale, sign-up or install |
| Revenue | Your sales, not TL revenue |
| Action Cost | Commission paid to the creator through Impact, not the TL price |
| Total Cost | That commission plus per-click, bonus, make-good and fixed payments through Impact. No Impact platform fee |
| Ad | A tracking link or creative, not a TL ad spot |
| Contract | Commission terms, not a TL IO |

Views always come from TL; Impact doesn't track them.

## What you can say

| You say | Result |
|---|---|
| "per deal" / "scorecard" | Deal scorecard |
| "which creators" / "top partners" | Creator rollup |
| "is it declining" / "over time" / "week by week" / "for the renewal" | Decay over time |
| "all of it" / "run autonomously" | All three views, no questions |
| "since June" / "last 90 days" | Date window |
| "include pending" | Pending counted in the headline |
| "just [creator]" | Limited to named creators |

## Example prompts

- "Match our Impact partners to TL channels for [brand]"
- "Deal scorecard for [brand] since June, approved actions only"
- "Is [creator] declining for [brand]? Show actions by week after each video"
- "What's the difference between Action Cost and Total Cost?"
