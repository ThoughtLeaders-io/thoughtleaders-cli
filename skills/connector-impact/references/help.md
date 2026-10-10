# Impact connector: user guide

Present this in plain language, sized to the question. Run no queries in help mode.

## What it does

Impact shows what happened after someone clicked a creator's link: clicks, sales, revenue,
commission. ThoughtLeaders shows what happened before: which creator, which video, when it went
live, views, what the sponsorship cost. This skill lines the two up, so you can ask things like
"which of our sponsorships drove the most sales per 1,000 views?"

## What you need

This reads your own brand's Impact account. If you're a creator rather than a brand, this isn't
the right tool for you.

- Your TL login (the `tl` CLI).
- One way into Impact:
  - Impact's connector for Claude (recommended): add a custom connector with the URL
    `https://mcp.impact.com/mcp` and sign in with your Impact login.
  - The Impact API, with a read-only token you create in Impact (Settings → Technical → API).
  - A CSV export from Impact's Reports (Performance by Partner or by Day), dropped into the chat.
  - The Impact website, open and signed in in your browser. Slowest, but no setup.

Never paste an Impact password or token into the chat.

## What you get

Always: a match list of each Impact partner to its TL channel, how it was matched and how sure
the match is. Each partner is in one group: booked through TL, a creator TL knows but you booked
elsewhere, or not a TL creator (coupon sites, blogs).

Your choice of views (you'll be asked if you don't say):
- **Deal scorecard:** one row per sponsorship, or a go-live timeline when all the creator's
  videos share one link.
- **Creator rollup:** one row per creator across their sponsorships.
- **Decay over time:** week by week after each video went live, to see whether a creator is
  declining. Impact's all-time totals hide this.

Every number above comes from last-click credit in your own Impact account: it counts sales that
arrived through the creator's link, not sales the video caused that reached you some other way.
Treat these figures as a floor on what a sponsorship did, not a verdict on it.

## How matching works

In order: the tracking link, the links on the Impact partner's profile, the creator's handles on
any platform, a TL id stored in the link, a promo code containing the creator's name, and last the
partner's name. The weaker matches are double-checked, for example against the date of the first
TL video. If a partner could be more than one TL channel, you're asked which to include.

YouTube, TikTok and Instagram deals for the same creator are read together, as one creator.
TikTok and Instagram posts have no TL views, so they're listed but left out of view-based
figures. If TL doesn't have a creator's channel yet, you'll be asked for the link; their
TL data takes about a day to fill in.

## Dates

- If each video has its own link or code, results are tied to that exact sponsorship.
- If all the videos share one link (common, but not always), you get a go-live timeline: each
  date the creator went live for you, and what Impact recorded until the next go-live. Earlier
  videos were still live during each period. A video that went live before your date range is
  included, since it can still bring in sales.
- When some videos have their own link and others share one, the ones with their own link are
  reported individually and the rest are reported as periods.
- Sales you can still cancel ("pending") are shown next to approved ones and marked "may still
  change".

## Costs and currencies

- **Booked through TL:** the TL price is the source of truth.
- **Never booked through TL:** what you paid through Impact is the source of truth. You'll be
  shown the creator's videos that mention your brand and asked which ones you paid for. You then
  get the CPM on what you paid, and whether the creator's projected views have risen or fallen
  since.
- The TL price and the Impact commission are always shown separately. They're added together
  only in an "All-in cost to date" box under the table, over the same videos and dates, with an
  as-of date.
- If Impact and TL use different currencies, every money column names its currency. Where money
  is compared with money, a converted column is added at the European Central Bank's monthly
  average rate, with the rate shown. The TL price is never converted.

Costs and CPMs here are last-click numbers from your own Impact account: they count sales that
arrived through the creator's link, not sales the video may have driven some other way. They're a
floor on what a sponsorship did, not the full picture.

## Impact terms in TL language

| Impact says | TL meaning |
|---|---|
| Partner | The creator or channel (sometimes an agency with several) |
| Program (or Campaign) | Your affiliate program, not a TL campaign |
| Action | A conversion: sale, sign-up or install |
| Revenue | Your sales, not TL revenue |
| Action Cost | Commission paid to the creator through Impact, not the TL price |
| Total Cost | That commission plus Impact's fees |
| Ad | A tracking link or creative, not a TL ad spot |
| Contract | Commission terms, not a TL IO |

Views always come from TL; Impact doesn't track them.

## What you can say

| You say | Result |
|---|---|
| "per deal" / "scorecard" | Deal scorecard |
| "which creators" / "top partners" | Creator rollup |
| "is it declining" / "over time" / "for the renewal" | Decay over time |
| "week by week" | Timeline by week, go-lives marked |
| "all of it" / "run autonomously" | All three views, no questions |
| "since June" / "last 90 days" | Date window |
| "include pending" | Pending counted in the headline |
| "just [creator]" | Limited to named creators |

## Example prompts

- "Match our Impact partners to TL channels for [brand]"
- "Deal scorecard for [brand] since June, approved actions only"
- "Is [creator] declining for [brand]? Show actions by week after each video"
- "What's the difference between Action Cost and Total Cost?"
