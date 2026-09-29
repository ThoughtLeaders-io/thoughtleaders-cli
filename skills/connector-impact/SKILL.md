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
  the Impact connection (Impact MCP, Impact API, CSV export or the Impact web app) and a `tl` login. Asks which view
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
- TL fields: the `tl` skill's `business-glossary.md` and `postgres-schema.md`;
  `elasticsearch-schema.md` for video lookups.

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

- **Scope:** brand; creators (default: all); window. IF the user states a window ("last 12
  months"), use it as stated, counted back from today. ELSE default: the earliest sold deal
  `publish_date` in the last 12 months, to today.
- **Views** (any combination):
  - *Deal scorecard:* one row per sold sponsorship where Impact can tell the videos apart,
    otherwise the go-live timeline (mapping 4).
  - *Creator rollup:* one row per channel across its deals for the brand.
  - *Decay over time:* the go-live timeline week by week, go-live weeks marked.
- IF the request names a view by name ("deal scorecard", "creator rollup", "decay over time"),
  run only the named views, without asking. ELSE IF it uses these words, run the matching view:
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
2. Confirm the user's Impact route (schema: *Access routes*). IF none: list the four routes and stop.
3. Never ask for, accept or repeat an Impact token or password. IF the user pastes one, tell them
   to revoke it.
4. Identify the account type from the API base or the web app address (mapping 5). IF it differs
   from the account the user described, stop and tell the user.
5. Resolve the brand with `tl brands find "<name>"`. Never match brand names in SQL.
6. Record the currency the Impact figures are in and the TL deals' `price_currency`. On a
   report, the figures' currency is its display-currency setting; do not change it. IF the two
   differ, tell the user now and apply mapping 2.3.
7. State the scope back: brand, window, view, states (approved headline, pending separate),
   currencies.

### 1. TL side

Pull sold deals live up to the window end. No start-date filter: videos that went live before the
window still drive sales inside it (mapping 4.2).

```sql
SELECT al.id, al.publish_date, al.price, al.price_currency, asp.ad_format,
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

- IF creators are named: add `AND asp.channel_id IN (...)` with every TL record of those
  creators. Find records by exact match (the `tl` skill's bulk lookup) on the channel name, the
  handle, and every handle in the channel's `social_links` and `url`, against other records'
  `common_name` and `url`. IF more than one record matches, list them with their URLs and ask
  which to include; "all" means one creator across platforms.
- Each deal's platform comes from its ad spot's `ad_format` (mapping 1.4).
- IF no rows: continue. Every partner goes to "not booked through TL" or "not a TL creator"
  (mapping 4.4).
- Run the coverage count (mapping 3.5) and tell the user which join keys this brand's deals have.

Get views from TL's video index in one call. A YouTube deal's video id is its `article_id`, or
else the id in its `media_url` (the video link; `urls` holds destination links). A deal with
neither, or on another platform, has no TL views (mapping 4.2):

```bash
tl db es '{"size": <number of videos>, "query": {"terms": {"id": ["<article_id>", "..."]}},
  "_source": ["id", "views", "projected_views", "publication_date"]}' --json
```

### 2. Impact side

1. Partners: id, name, website, property URLs (`list_partners`, `GET .../MediaPartners`, or the
   Partners screen search; report partner filters are capped). IF creators are named, search
   only for those creators' partners, by their aliases (mapping 3.1).
2. Action-level data for the partners in scope (Advanced Action Listing, or `GET .../Actions`
   filtered with `ActionDateStart` / `ActionDateEnd`): date, status, event type, promo code, Ad,
   SubIds, SharedId, social platform, sale amount, commission. Group by partner, date, status and
   event type. This is the source of actions, sales revenue and commission.
3. Clicks per partner per day from grouped performance (`query_performance`, ReportExport, or a
   Performance by Partner / by Day report).
4. Map every column to its name in the schema's *Field names by route* table before any math.
   Name any column not in it before using it.

Web app route: before reading a report, set its filters (dates, status, partner, channel) to the
run's scope and add any needed column that the view does not return, on screen only. Never save,
schedule, export or download.

IF the route returns lifetime totals only, tell the user decay over time is unavailable.

### 3. Join

Walk each partner in scope down the creator ladder (mapping 3.2), then look for per-video
evidence (mapping 3.3). Record `partner_id, channel_id(s), key, confidence` and the partner's
group (mapping 4.4).

- Match aliases exactly, `UPPER()` on both sides, with the `tl` skill's bulk lookup. This lookup
  adds nothing to TL. Never `ILIKE` on names.
- A partner that matches no alias: group "not a TL creator".
- IF a creator named in scope has no matching partner: stop and ask the user for the creator's
  partner name or promo code in Impact.
- Run `tl channels find` only on a channel TL already has or on a link the user gave. On an
  unknown channel it queues the channel for indexing.
- IF a YouTube creator is not in TL: ask the user for the channel link, add it with
  `tl channels find "<link>"`, tell the user TL data for it takes about a day, and report that
  creator from Impact only until then.
- Medium and weak keys need a second signal (mapping 3.2), or the match is listed as "probable,
  please confirm".
- A partner whose keys point to different creators is an agency. Split by tracking link or ask.
  Never assign an agency's actions to one creator. Several TL records of one creator are not an
  agency.
- Never open a tracking link: it registers a click in the brand's account.
- IF a partner matches more than one TL channel: IF it has approved actions in the window, show
  the candidates with evidence and ask which to include ("all" means one creator across
  platforms); ELSE list it as unresolved without asking.
- List actions that used the creator's promo codes but are credited to another partner (mapping
  3.4).
- List TL deals with no Impact partner, with the likely reason.

### 4. Dates

Apply mapping 4: per-deal windows only with per-video evidence (4.1), otherwise the go-live
timeline (4.2); social platforms per 4.5; for creators not booked through TL, the user confirms
which videos they paid for (4.4). Build periods by summing each partner's daily numbers between
go-live dates.

### 5. Metrics

Apply mapping 2. IF a TL deal already has `conversions` or `revenue` that differs from Impact,
show both, labelled; never overwrite or average.

### 6. Deliver

In this order:
1. Scope line: brand, window, states, currencies and conversion rates used, Impact route.
2. The chosen views as tables, each followed by its breakdown table and its "All-in cost to
   date" block (mapping 2.2).
   Label every figure TL or Impact, and every money column with its currency.
3. Join table: partner → channel → deal, key, confidence.
4. Creators not booked through TL, then partners that are not TL creators, then TL deals with no
   partner.
5. Caveats that change the reading: pending share, rates used, shared links (periods, not
   videos), deals that are or may be social posts (mapping 4.2), the creator's codes credited to
   other partners, agencies, low-confidence matches.

Use business terms from the `tl` glossary, not table names. IF the user asks for a chart, render
it as SVG.

Write nothing to Impact or TL, set no performance grade, edit no sheet. The only TL write is a
channel added from a link the user gave. IF the user wants results saved, offer and wait for a yes.

## Self-check before finishing

1. No Impact credential passed through chat.
2. The view came from the request or the user's answer (all three under autonomous mode). Scope
   was stated back.
3. The coverage count was reported.
4. Every partner in scope has a key, a confidence and a group. No name `ILIKE`, no tracking link
   opened, no `tl channels find` on an unknown name, agencies split or asked.
5. Performance is tied to one deal only where per-video evidence exists. Otherwise it is a
   go-live timeline with the period sentence above it (mapping 4.2).
6. Mapping 2 holds: views from TL only; Paid to TL and commission in separate columns; all-in
   figures only in the to-date block; every money column names its currency; converted columns
   use a shown ECB rate; the TL price is never converted.
