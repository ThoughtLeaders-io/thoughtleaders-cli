---
name: connector-impact
tl-blurb: join Impact performance data to TL sponsorships
description: |
  Join a brand's Impact (impact.com) data to ThoughtLeaders data: each Impact partner matched to a
  TL channel and, where Impact can tell videos apart, to the exact TL sponsorship; otherwise a
  go-live timeline of the creator's TL videos against Impact results. TL views, price and CPM sit
  beside Impact clicks, actions, sales revenue and commission. Also covers creators the brand
  never booked through TL, and brands with no TL bookings. Invoke when the user wants Impact
  numbers read against TL data: "how did our sponsorships convert in Impact", "Impact performance
  for [creator/brand]", "which TL creators drove the most actions", "actions per 1,000 views",
  "cost per action on our sponsorships", "is [creator] declining", "match Impact partners to our
  channels", "what does [Impact term] mean in TL", or any question mixing Impact terms (Partner,
  Action, Action Cost, Total Cost, Program, PromoCode, SharedId) with TL data. The user supplies
  the Impact connection (Impact MCP, Impact API or CSV export) and a `tl` login. Asks which view
  (deal scorecard, creator rollup, decay over time) when the request doesn't say. Also invoke for
  help asks about this skill; answered from the guide, no queries run.
---

# connector-impact

Impact records what happened after the click (clicks, actions, sales revenue, commission). TL
records what happened before it (creator, video, go-live date, views, price). This skill
translates Impact terms into TL terms and joins the two datasets.

Read before any analysis:
- `references/impact-to-tl-mapping.md`: vocabulary, metric rules, join keys, dates, costs, currency.
- `references/impact-schema.md`: Impact objects, fields, filters and traps.
- TL fields: the `tl` skill's references.

## When to use

Use when a question needs both Impact and TL data, or Impact terms translated into TL terms,
including for a brand with no TL bookings.

Do not use:
- Impact-only question with no TL angle: tell the user Impact's MCP answers it directly.
- TL-only question: use the `tl` skill.
- Renew / don't-renew verdict: build the join here, then hand the deal scorecard to the renewal skill.

## Help mode

IF the user asks what the skill does, how it works or what they can ask: run no queries, answer
from `references/help.md` sized to the question, then offer to start. Answer mid-run term
questions from `help.md` or the mapping file, then continue the run.

## Scope and view

- **Scope:** brand; creators (default: all); window (default: the earliest sold deal
  `publish_date` in the last 12 months, to today).
- **Views** (any combination):
  - *Deal scorecard:* one row per sold sponsorship where Impact can tell the videos apart,
    otherwise the go-live timeline (mapping 4).
  - *Creator rollup:* one row per channel across its deals for the brand.
  - *Decay over time:* the go-live timeline week by week, go-live weeks marked.
- IF the request names a view, run it without asking:
  - "per deal", "scorecard", "how did each sponsorship do" → deal scorecard
  - "which creators", "top partners", "rank" → creator rollup
  - "declining", "over time", "since it went live", "renew" → decay over time
- ELSE ask ONE question covering every unstated item (view, brand, window), one line per view on
  what it shows. Never default silently.
- IF `autonomous`, `--auto` or "don't stop to ask": all three views, default window, no questions.
- IF the user says "include pending": count pending actions in the headline numbers.

## Workflow

At each stage transition, state one line: what you are doing and the counts so far. Report each
unmatched partner, dropped row and currency mismatch when it is found.

Aggregate at the source: `GROUP BY` in TL SQL, grouped `query_performance` in Impact. Compute
every sum and ratio with a calculation (SQL or a quick code step), never by hand.

### 0. Setup

1. Run `tl whoami` to confirm the TL login works.
2. Confirm the user's Impact route (schema: *Access routes*). IF none: list the three routes and stop.
3. Never ask for, accept or repeat an Impact token or password. IF the user pastes one, tell them
   to revoke it.
4. Identify the account type: Brand (`/Advertisers/`) or Partner (`/Mediapartners/`), mapping 5.
5. Resolve the brand with `tl brands find "<name>"`. Never match brand names in SQL.
6. Record the Impact account currency and the TL deals' `price_currency`. IF they differ, tell
   the user now and apply mapping 2.3.
7. State the scope back: brand, window, view, states (approved headline, pending separate),
   currencies.

### 1. TL side

Pull sold deals live up to the window end. No start-date filter: videos that went live before the
window still drive sales inside it (mapping 4.2).

```sql
SELECT al.id, al.publish_date, al.price, al.price_currency,
       al.projected_views_at_purchase_date, al.tracking_url, al.cta_text,
       al.media_url, al.article_id, al.conversions, al.revenue, al.revenue_currency,
       asp.channel_id, ch.channel_name, ch.url, ch.common_name
FROM thoughtleaders_adlink al
JOIN thoughtleaders_profile_brands pb ON pb.profile_id = al.advertiser_profile_id
JOIN thoughtleaders_adspot asp ON asp.id = al.ad_spot_id
JOIN thoughtleaders_channel ch ON ch.id = asp.channel_id
WHERE pb.brand_id = <brand_id> AND al.publish_status = 3
  AND al.publish_date IS NOT NULL AND al.publish_date <= '<window_end>'
ORDER BY asp.channel_id, al.publish_date
LIMIT 1000
```

- IF no rows: continue. Every partner goes to "not booked through TL" or "not a TL creator"
  (mapping 4.4).
- Run the coverage count (mapping 3.1) and tell the user which join keys this brand's deals have.

Get views from TL's video index in one call, by the deals' `article_id`:

```bash
tl db es '{"size": <number of videos>, "query": {"terms": {"id": ["<article_id>", "..."]}},
  "_source": ["id", "views", "projected_views", "publication_date"]}' --json
```

### 2. Impact side

1. Partners: id, name, website, property URLs (`list_partners`, `GET .../MediaPartners`, or the
   Partners export).
2. Performance per partner per day or week across the window: clicks, actions, revenue, payout
   (`query_performance`, ReportExport, or a Performance by Partner / by Day CSV).
3. Approved and pending split: IF the grouped numbers mix them (Impact's performance reports
   do), get the split from action-level data (Advanced Action Listing, or `GET .../Actions`)
   grouped by partner, date and status.
4. Other action-level rows only for promo-code, SubId or SharedId joins or a disputed partner.
   Filter Actions API calls with `ActionDateStart` / `ActionDateEnd`.

Name any field not listed in `impact-schema.md` before using it. IF the route returns lifetime
totals only, tell the user decay over time is unavailable.

### 3. Join

Walk each partner down the key ladder (mapping 3). Stop at the first key that resolves. Record
`partner_id, channel_id, key, confidence` and the partner's group (mapping 4.4).

- Look up every partner by exact match of its YouTube URLs, handles and name against TL's
  channels (the `tl` skill's bulk lookup, `UPPER()` on both sides). This lookup adds nothing to
  TL. Never `ILIKE` on names.
- A partner with no match and no YouTube link on its Impact profile: group "not a TL creator".
- Run `tl channels find` only on a channel TL already has or on a link the user gave. On an
  unknown channel it queues the channel for indexing.
- IF a YouTube creator is not in TL: ask the user for the channel link, add it with
  `tl channels find "<link>"`, tell the user TL data for it takes about a day, and report that
  creator from Impact only until then.
- Name-only match: low confidence. Confirm with a second signal (property URL, country, deal
  dates) or list it as "probable, please confirm".
- Partner whose properties point to several channels: an agency. Split by tracking link or ask.
  Never assign an agency's actions to one channel.
- Never open a tracking link: it registers a click in the brand's account.
- IF a partner matches more than one TL channel: IF it has approved actions in the window, show
  the candidates with evidence and ask; ELSE list it as unresolved without asking.
- List TL deals with no Impact partner, with the likely reason.

### 4. Dates

Apply mapping 4: per-deal windows only with per-video evidence (4.1), otherwise the go-live
timeline (4.2); for creators not booked through TL, the user confirms which videos they paid for
(4.4). Build periods by summing each partner's daily numbers between go-live dates.

### 5. Metrics

Apply mapping 2. IF a TL deal already has `conversions` or `revenue` that differs from Impact,
show both, labelled; never overwrite or average.

### 6. Deliver

In this order:
1. Scope line: brand, window, states, currencies and conversion rates used, Impact route.
2. The chosen views as tables, each followed by its "All-in cost to date" block (mapping 2.2).
   Label every figure TL or Impact, and every money column with its currency.
3. Join table: partner → channel → deal, key, confidence.
4. Creators not booked through TL, then partners that are not TL creators, then TL deals with no
   partner.
5. Caveats that change the reading: pending share, rates used, shared links (periods, not
   videos), agencies, low-confidence matches.

Use business terms from the `tl` glossary, not table names. IF the user asks for a chart, render
it as SVG.

Write nothing to Impact or TL, set no performance grade, edit no sheet. The only TL write is a
channel added from a link the user gave. IF the user wants results saved, offer and wait for a yes.

## Self-check before finishing

1. No Impact credential passed through chat.
2. The view came from the request or the user's answer (all three under autonomous mode). Scope
   was stated back.
3. The coverage count was reported.
4. Every partner has a key, a confidence and a group. No name `ILIKE`, no tracking link opened,
   no `tl channels find` on an unknown name, agencies split or asked.
5. Performance is tied to one deal only where per-video evidence exists. Otherwise it is a
   go-live timeline with the period sentence above it (mapping 4.2).
6. Mapping 2 holds: views from TL only; Paid to TL and commission in separate columns; all-in
   figures only in the to-date block; every money column names its currency; converted columns
   use a shown ECB rate; the TL price is never converted.
