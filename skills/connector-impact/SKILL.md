---
name: connector-impact
tl-blurb: join Impact performance data to TL sponsorships
description: |
  Join a brand's Impact (impact.com) data to ThoughtLeaders data: each Impact partner matched to a
  TL channel and, where Impact can tell videos apart, to the exact TL sponsorship; otherwise a
  go-live timeline of the creator's TL videos against Impact results. TL views, price and CPM sit
  beside Impact clicks, actions, sales revenue and commission. Also covers creators the brand
  never booked through TL, and brands with no TL bookings. Brand side only: a media-buyer `tl`
  login and a brand (advertiser) Impact account. Invoke when the user wants Impact numbers read
  against TL data: "how did our sponsorships convert in Impact", "Impact performance for
  [creator/brand]", "which TL creators drove the most actions", "actions per 1,000 views",
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
- Renew / don't-renew verdict: build the join here, then apply the renewal rule in the `tl`
  skill's `references/business-glossary.md` (*Performance Grade*). This skill sets no grade.

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

**Open with a number, before any call at all.** The exact cost needs the row count, and the row
count needs a read — so do not wait for it. State the **ceiling** first: the balance from
`tl balance`, the rate (0.3 credits a sponsorship row), and the worst case this run could reach
against the user's ceiling if they gave one. A user who sees tool calls begin before hearing any
number has no moment to stop the run.

**One probe, named in advance, is the only charged call allowed before the exact quote.** The row
count comes from a single bounded read — `tl sponsorships list` scoped to the brand with
`--limit 1`, which returns `total` for 0.3 credits. Name that call and its cost in the opening
line, make it, then give the exact estimate before the real pull begins. Nothing else may be
charged before that estimate: no full first page, no raw SQL to resolve a creator, no
`--pricing` preview. Creator resolution happens inside the scoped pull, after the quote, not
before it.

**Then quote, then read.** Give the estimate in credits beside the balance. IF it is above the
user's stated ceiling, or above a tenth of the balance, stop and ask before reading. `tl db pg
--pricing` / `tl db es --pricing` return a per-row rate and an upper-bound cost without running
the query (1 credit each) — use them to price a raw read, after the estimate, never as a
substitute for it. Keep a running ledger from each response's `usage.credits_charged`, **failed
reads included** — a read that errors is charged like any other — and report the total with the
results. Write "credits"; never "cr".

**Page every read to the end.** Every `tl db pg` call carries both `LIMIT` and `OFFSET`, every
`tl db es` body both `size` and `from`, and every page walks the envelope's `next_offset` until
`has_more` is false. `tl sponsorships list` serves at most 500 rows a page whatever `--limit`
asks for, so page it the same way.

**Refuse loudly on truncation.** IF any read comes back short of its `total` — a page cap, a
rejected offset, an error mid-walk — stop the run, name the read and how many rows are missing,
and ask before going on. Never answer short: a creator silently dropped from the deal set is
classified "not booked through TL", and the report then quotes what the brand paid through
Impact as the source of truth — a confidently wrong cost figure with no error anywhere.

**Personal data stays out.** Never copy a partner's `Contacts[]` into output, and never carry an
action's customer-level fields — `CustomerId`, `CustomerStatus`, `CustomerCountry`,
`CustomerRegion`, `CustomerCity`, `Oid`, `Note` — into a table, a note or a calculation. The
deliverable is per partner and per deal; nothing below that grain leaves Impact.

### 0. Setup

1. Run `tl whoami --json` to confirm the TL login works and read the caller's side from
   `profile.persona` and `profile.flags`.
2. **Seller-side login: stop here.** IF the caller is a publisher / media seller — persona
   creator or creator service, or `publisher` in `flags` without `advertiser` — refuse the run
   and say why: this skill reads a brand's affiliate program against the deals that brand bought,
   and a seller-side login returns the creator's own deals instead. The run would finish and
   produce a complete, plausible report of the wrong org's spend with no error anywhere. A
   media-buyer login is required.
3. Confirm the user's Impact route (schema: *Access routes*). IF none: list the four routes and stop.
4. Never ask for, accept or repeat an Impact token or password. IF the user pastes one, tell them
   to revoke it.
5. **The supported direction is brand → partners.** Identify the account from the API base or the
   web app address (mapping 5). A Brand account (`/Advertisers/`, `/secure/advertiser/`) is the
   only connection this skill runs. IF it is a Partner account, stop and say so: mapping 5's
   Partner column is reference for reading a partner's own figures, not a flow. IF the account
   type differs from the one the user described, stop and tell the user.
6. Resolve the brand with `tl brands find "<name>"`. Never match brand names in SQL.
7. IF creators are named, resolve them to TL channel ids now (stage 1), before any deal read.
8. Record the currency the Impact figures are in and the TL deals' `price_currency`. On a
   report, the figures' currency is its display-currency setting; do not change it. IF the two
   differ, tell the user now and apply mapping 2.3.
9. Quote the run's credit cost (above), then state the scope back: brand, creators, window, view,
   states (approved headline, pending separate), currencies.

### 1. TL side

Pull the brand's sold deals with `tl sponsorships list`. No date filter: videos that went live
before the window still drive sales inside it (mapping 4.2), and sold deals with no
`publish_date` belong in the report too (4.2).

```bash
tl sponsorships list status:sold brand:"<brand name>" --limit 500 --offset 0 --json
```

- IF creators are named: resolve each to its TL channel ids first, then run one paged pull per
  id with `channel:<channel_id>` added. Never pull the brand's whole book and filter in memory.
  Resolve by exact match, `UPPER()` on both sides — the bulk form in the `tl` skill's
  `references/postgres-schema.md`, under *For bulk handle/name lookups in SQL* — on the channel
  name, the handle, the handle in `url`, and the creator's named platform handles, against other
  records' `common_name` and `url`. IF more than one record matches, list them with their URLs
  and ask which to include; "all" means one creator across platforms.
- Project **named platform keys only** out of a channel's `social_links` (`youtube`, `tiktok`,
  `instagram`, …), never the whole object and never its `_emails` array, which holds creators'
  personal e-mail addresses. That array is never selected, never printed and never passed into a
  calculation. The Elasticsearch mirror of the field is sanitised and is the safer source.
- The rows carry `id`, `publish_date`, `price`, `projected_views_at_purchase_date`, `article_id`,
  `channel_id`, `channel`, `common_name`, `brand_id`, `status`, `cpm` and `views`. TL views come
  from here; the video index is only the fallback below.
- `brand:` is a partial name match. Check every row's `brand_id` against the id resolved in
  setup; name any row that does not match and leave it out.
- Partition the pull: deals live on or before the window end feed the scorecard or timeline;
  sold deals with no `publish_date` are not live and are listed under the table (mapping 4.2);
  deals live after the window end are outside it — report their count.
- IF no rows: continue. Every partner goes to "not booked through TL" or "not a TL creator"
  (mapping 4.4).

Then one adlink-only read for the Impact join keys and currency columns the list does not carry,
keyed on the deal ids already pulled:

```sql
SELECT al.id, al.tracking_url, al.media_url, al.price_currency,
       al.conversions, al.revenue, al.revenue_currency
FROM thoughtleaders_adlink al
WHERE al.id IN (<deal ids>)
LIMIT 500 OFFSET 0
```

Join the two result sets on deal id.

- Send at most 500 ids a call and reconcile the ids returned against the ids sent. An id with no
  row back is a truncated read, not a deal without join keys.
- No join to `thoughtleaders_profile_brands`, `thoughtleaders_adspot` or
  `thoughtleaders_channel`: the deal rows are already brand- and org-scoped, and every table a
  query touches is charged on every row it returns.
- Select from `thoughtleaders_adlink` only, and only the columns above. A caller's raw-DB access
  runs against a restricted schema holding fewer columns than `tl schema pg` reports, so a column
  confirmed there still fails at execution with `column does not exist`. Do not widen the select
  to find a field; if the join needs one that is not here, say so and stop.
- TL stores no promo code, so a code is never a deal key: per-video evidence comes from the
  tracking link, a `SharedId` or SubId carrying a TL deal id, or an Ad that names one video
  (mapping 3.3). Impact's own codes still reach the creator (3.2 key 5) and drive 3.4.
- A TL deal carries no platform in scope. Lanes come from Impact's own platform split
  (mapping 4.5); a deal with no TL views is listed as such whatever format it ran in (1.4).
- `publish_date` is a timestamp. In SQL bound a window end with `< <the day after the window
  end>`, never `<= <window end>`, which resolves to midnight and drops the final day.
  `tl sponsorships list`'s `publish-date-end` is inclusive by date and needs no adjustment.
- Run the coverage count (mapping 3.5) and tell the user which deal keys this brand's deals
  have. It is brand-wide even when creators are named: label it so. Quote its cost with the rest
  of the run. IF the keys are thin, the result is a go-live timeline (4.2).

The `views` on a deal row is the video-index value (mapping 1.4). Deals the list returns no
`views` for are looked up in the index once, by video id, before any of them is called "no TL
views":

> A deal's video id is its `article_id`. IF `article_id` is empty, build it as
> `<channel_id>:<youtube_id>`, where `<youtube_id>` is the `v=` value in `media_url` (the video
> link; `urls` holds destination links). The bare `v=` value alone never matches. IF `media_url`
> carries no `v=` value — it can hold a link that is not a YouTube video — the deal has no video
> id and therefore no TL views. Never guess an id from the rest of the link.

```bash
tl db es '{"size": <number of ids>, "from": 0, "query": {"terms": {"id": ["<video id>", "..."]}},
  "_source": ["id", "views", "projected_views", "publication_date"]}' --json
```

> A deal has TL views if and only if its video id resolved to a video-index document carrying a
> `views` value. A deal whose id does not resolve, or whose document carries no `views` field, is
> listed as "no TL views" and left out of views, CPM and per-1,000-view figures; its price still
> counts in Paid to TL.

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

- Match aliases exactly, `UPPER()` on both sides, with the bulk handle/name form named in stage
  1. This lookup adds nothing to TL. Never `ILIKE` on names.
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
1. Scope line: brand, window, states, currencies and conversion rates used, Impact route, and
   the credits this run charged.
2. The chosen views as tables, each followed by its breakdown table and its "All-in cost to
   date" block (mapping 2.2).
   Label every figure TL or Impact, and every money column with its currency.
3. Join table: partner → channel → deal, key, confidence.
4. Creators not booked through TL, then partners that are not TL creators, then TL deals with no
   partner, then sold deals not yet live.
5. Caveats that change the reading: pending share, rates used, shared links (periods, not
   videos), deals with no TL views (mapping 1.4), the creator's codes credited to other partners,
   agencies, low-confidence matches.

**Last-click caveat.** Every cost per action, return on sponsorship and all-in return carries,
beside it or directly under the block it sits in, the note that these come from last-click credit
in the brand's own affiliate account: they count only the sales that closed through the partner's
link or code, and miss every sale the video caused that did not route through it. Naming the
attribution model in the scope line does not cover the figures; the caveat travels with them.

This covers **every** such figure, not only the one in the main table: a headline or summary
figure stated above the table, an alternative or second-basis figure stated below it, and a figure
repeated in a narrative sentence each need the caveat with them. A caveat under a later table does
not reach a number quoted earlier — the reader meets the figure first. Where the same caveat would
repeat several times in one section, mark each figure and carry one note for the section, placed
where a reader meets the first of them.

Use business terms from the `tl` glossary, not table names. IF the user asks for a chart, render
it as SVG.

Write nothing to Impact or TL, set no performance grade, edit no sheet. The only TL write is a
channel added from a link the user gave. IF the user wants results saved, offer and wait for a yes.

## Self-check before finishing

1. No Impact credential passed through chat.
2. The view came from the request or the user's answer (all three under autonomous mode). Scope
   was stated back.
3. The caller is a media buyer and the Impact account is a Brand account; a seller-side login or
   a Partner account stopped the run at setup.
4. A ceiling in credits was stated before any call; the only charge before the exact estimate was
   the single named row-count probe; the estimate came before the pull; and the ledger reported
   with the results counts every read, failed ones included.
5. Every read was paged to the end against its `total`. A truncated read stopped the run and was
   named; nothing was answered short.
6. No creator e-mail address was read or printed, no `Contacts[]`, no customer-level action field.
7. The coverage count was reported, with the scope it covers named.
8. Every partner in scope has a key, a confidence and a group. No name `ILIKE`, no tracking link
   opened, no `tl channels find` on an unknown name, agencies split or asked.
9. Every deal's TL views came from a resolved video-index document carrying a `views` value; the
   rest are listed as "no TL views" with their prices still in Paid to TL.
10. Performance is tied to one deal only where per-video evidence exists. Otherwise it is a
    go-live timeline with the period sentence above it (mapping 4.2).
11. Every cost per action, return on sponsorship and all-in return carries the last-click caveat
    beside the figure — summary figures above the table and alternative figures below it included,
    not only the one in the main table.
12. Every money cell names its currency, including a cell reading 0 and a cell in a row that is
    otherwise empty: a bare `0` does not say which currency it is zero of. A currency named once
    in the table's title covers the table.
13. Mapping 2 holds: views from TL only; Paid to TL and commission in separate columns; all-in
    figures only in the to-date block; converted columns use a shown ECB rate; the TL price is
    never converted.
