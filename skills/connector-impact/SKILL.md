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
  the Impact connection (Impact MCP, Impact API or a CSV export) and a `tl` login. Read-only:
  it never changes anything in Impact. Asks which view (deal scorecard, creator rollup, decay
  over time) when the request doesn't say. Also invoke for help asks about this skill; answered
  from the guide, no queries run.
---

# connector-impact

Impact records what happened after the click (clicks, actions, sales revenue, commission). TL
records what happened before it (creator, video, go-live date, views, price). This skill joins
the two.

Read before any analysis:
- `references/impact-to-tl-mapping.md`: terms, metrics, match keys, dates, costs, currency.
- `references/impact-schema.md`: Impact objects, fields and traps.
- From the `tl` skill: `business-glossary.md`, `postgres-schema.md`, and `elasticsearch-schema.md`
  for video lookups.

Not for: an Impact-only question (Impact's MCP answers it directly); a TL-only question (use the
`tl` skill); a renew or don't-renew verdict (build the join here, then apply *Performance Grade*
in the `tl` skill's glossary; this skill sets no grade).

## Read-only

This skill only reads Impact. It never creates, changes, approves, reverses or deletes anything
there, on any route, whatever the user's login or token would allow. Use only these calls:

| Route | Allowed calls |
|---|---|
| Impact MCP | `query_performance`, `list_partners`, `investigate_order_action`, `list_action_inquiries`, `get_action_inquiry` |
| Impact API | `GET` requests to the resources in the schema |
| CSV export | Reading the files the user supplies (also on the MCP route, stage 2) |

If the user asks for a change in Impact (approve or reverse an action, resolve an inquiry, message
or edit a partner, change a contract, payout or setting), say this skill only reads, point them to
Impact's website, and carry on with the run.

Files the run creates go in a temporary folder that is deleted when the run ends. The user's own
exports stay where they are. If the user wants results saved, offer and wait for a yes.

## Help mode

If the user asks what the skill does, how it works or what they can ask, run no queries: answer from
`references/help.md`, sized to the question, then offer to start. Answer a term question mid-run
from `help.md` or the mapping, then continue.

## Scope and view

- **Brand:** required.
- **Creators:** all, unless the user names some.
- **Window:** as the user states it, counted back from today. Otherwise from the earliest sold
  deal `publish_date` in the last 12 months, to today.
- **Views**, any combination:
  - *Deal scorecard:* one row per sold sponsorship where Impact can tell the videos apart,
    otherwise the go-live timeline (mapping 4).
  - *Creator rollup:* one row per channel across its deals for the brand.
  - *Decay over time:* the go-live timeline week by week, go-live weeks marked.
- A view named in the request runs alone, without asking. Otherwise these words pick it:
  - "per deal", "scorecard", "how did each sponsorship do": deal scorecard
  - "which creators", "top partners", "rank": creator rollup
  - "declining", "over time", "since it went live", "week by week", "renew": decay over time
- If the view is still unknown, ask one question covering every unstated item (view, brand,
  window), with one line per view on what it shows. Never default silently. If only the brand is
  unknown, ask for it.
- `autonomous`, `--auto`, "all of it" or "don't stop to ask": all three views, default window, no
  questions.
- Pending actions count in headline numbers only when the user asks to include pending for this
  run. Then label both states and do not ask. That request wins over a standing line such as
  "keep pending separate unless I ask". "Do not include pending", or the standing line on its own,
  does not turn pending on.

## Rules for every read

- At each stage, state one line: what you are doing and the counts so far. Report each unmatched
  partner, dropped row and currency mismatch when you find it.
- Aggregate at the source (`GROUP BY` in TL SQL, grouped `query_performance` in Impact). Compute
  every sum and ratio with SQL or a code step, never by hand.
- **Credits.** Before any call, state the worst case: the balance from `tl balance`, the rate
  (0.3 credits a sponsorship row), and the most this run could cost, against the user's limit if
  they gave one. The only charged call before the exact quote is one probe, named in advance:
  `tl sponsorships list` for the brand with `--limit 1`, which returns `total` for 0.3 credits.
  Then quote the run (deal pull, adlink read, coverage count, video lookups) beside the balance.
  If the quote is above the user's limit or a tenth of the balance, ask before reading. Price
  any other raw read with `tl db pg --pricing` / `tl db es --pricing` (1 credit each) after the
  quote. Keep a running total from each response's `usage.credits_charged`, failed reads
  included, and report it with the results. Write "credits", never "cr".
- **Paging.** Every `tl db pg` call has `LIMIT` and `OFFSET`; every `tl db es` body has `size`
  and `from`; follow `next_offset` until `has_more` is false. `tl sponsorships list` returns at
  most 500 rows a page, so page it too.
- **Truncation.** If a read returns fewer rows than its `total`, stop, name the read and the
  missing count, and ask before going on. A creator silently dropped becomes "not booked through
  TL" and gets a wrong cost.
- **Personal data.** Never put a partner's `Contacts[]` or an action's customer fields
  (`CustomerId`, `CustomerStatus`, `CustomerCountry`, `CustomerRegion`, `CustomerCity`, `Oid`,
  `Note`) into a table, a note or a calculation; the report is per partner and per deal. Read a channel's `social_links` by named
  platform key only (`youtube`, `tiktok`, `instagram`); never select the whole column or its
  `_emails` array. The video index copy of the links has e-mails removed.

## Workflow

### 0. Setup

1. Run `tl whoami --json` and read `profile.persona` and `profile.flags`.
2. If the caller is a seller (persona creator or creator service, or `publisher` in `flags`
   without `advertiser`), stop and say a media-buyer login is required: a seller login returns
   the creator's own deals, so the report would be about the wrong company.
3. Confirm the Impact route (schema: *Access routes*): Impact MCP, Impact API or a CSV export. If
   there is none, list the three and stop. If the user offers the Impact website, ask for a CSV
   export and name the reports and filters (stage 2). Use the user's token as it is: the run is
   read-only whatever the token allows, so its permissions need no comment.
4. Never ask for, accept or repeat an Impact token or password. If the user pastes one, tell them
   to revoke it.
5. Identify the account from the API base, or from the web app address the user exports from
   (mapping 5). Only a Brand account runs. If it is a Partner account, or not the type the user
   described, stop and say so.
6. Resolve the brand with `tl brands find "<name>"`, never in SQL.
7. Record the currency of the Impact figures (a report's display-currency setting; do not change
   it). The report is in USD. If the Impact figures are not in USD, tell the user now (mapping
   2.3).
8. Quote the credits, then state the scope back: brand, creators, window, view, which action
   states are counted (approved and pending labelled separately), currencies, and this line:
   "Read-only run: <Impact route>, reading <what will be read>."

### 1. TL side

Pull the brand's sold deals with no date filter: earlier videos still drive sales inside the
window, and sold deals with no `publish_date` are listed too (mapping 4.2).

```bash
tl sponsorships list status:sold brand:"<brand name>" --limit 500 --offset 0 --json
```

- **Named creators:** resolve each to its TL channel ids first, matching per mapping 3.1 with the
  bulk form in the `tl` skill's `postgres-schema.md` (*For bulk handle/name lookups in SQL*):
  channel name, handle, the handle in `url` and named platform handles, against `common_name` and
  `url`. If more than one record matches, list them with their URLs and ask which to include
  ("all" means one creator across platforms). Then run one paged pull per channel id with
  `channel:<channel_id>` added, never the brand's whole list filtered afterwards.
- Rows carry `id`, `publish_date`, `price`, `projected_views_at_purchase_date`, `article_id`, `channel_id`, `channel`,
  `common_name`, `brand_id`, `status`, `cpm` and `views`.
- `brand:` is a partial name match. Keep only rows whose `brand_id` is the brand resolved in
  setup, and name any row left out.
- Deals live on or before the window end feed the table. Sold deals with no `publish_date` are
  listed under it (mapping 4.2). Report the count of deals live after the window end.
- No rows: continue. Every partner is then "not booked through TL" or "not a TL creator"
  (mapping 4.4).
- `publish-date-end` on `tl sponsorships list` is inclusive. In SQL, bound dates per mapping 1.2.

Then read the join keys the list lacks, for the deal ids pulled, and join on deal id:

```sql
SELECT al.id, al.tracking_url, al.media_url,
       al.conversions, al.revenue
FROM thoughtleaders_adlink al
WHERE al.id IN (<deal ids>)
LIMIT 500 OFFSET 0
```

- At most 500 ids a call. Check every id came back: a missing id is a truncated read.
- Query `thoughtleaders_adlink` alone, with only these columns. The deal rows are already
  brand-scoped, and every joined table is charged per row. Do not widen the select to find a
  field; if the join needs one that is not here, say so and stop. If a column is rejected, follow
  the mapping's opening rule.
- Run the coverage count (mapping 3.5) and tell the user which deal keys the brand's deals carry,
  labelled brand-wide even when creators are named.
- A deal row's `views` is its TL views. For deals with no `views`, resolve the video id (mapping
  1.4) and look them up once before calling any of them "no TL views":

```bash
tl db es '{"size": <number of ids>, "from": 0, "query": {"terms": {"id": ["<video id>", "..."]}},
  "_source": ["id", "views", "projected_views", "publication_date"]}' --json
```

### 2. Impact side

1. **Partners:** id, name, website, property URLs (`list_partners`, `GET .../MediaPartners`, or a
   partner list export; report partner filters are capped). For named creators, search only for their partners, by alias (mapping
   3.1).
2. **Actions** for the partners in scope: date, state, event type, promo code, Ad, SubIds,
   SharedId, social platform, sale amount, commission. From `GET .../Actions` filtered with
   `ActionDateStart` / `ActionDateEnd`, or the Advanced Action Listing export. On the MCP route,
   ask for that export: no MCP tool returns each action's state, promo code or SharedId. Group by
   partner, date, state and event type.
3. **Clicks** per partner per day from grouped performance (`query_performance`, a ReportExport,
   or a Performance by Partner / by Day report).
4. Map every column to the schema's *Field names* table before any math, and name any column
   that is not in it.

CSV route: name the reports to export (Performance by Partner, Performance by Day, Advanced Action
Listing) with the run's dates, states and partners, plus any column the default view hides.

If the route only gives lifetime totals, say decay over time is unavailable.

### 3. Join

Match each partner to TL with every key in mapping 3.2, then look for per-video evidence (mapping
3.3). Record partner id, channel id(s), key, confidence and group (mapping 4.4).

- Resolve every `Properties[]` URL and handle on the partner, plus its link and name, and collect
  every TL channel any of them reaches, even after a strong match. Two or more channels trigger
  the multi-channel or agency rule below.
- Match aliases per mapping 3.1. Never `ILIKE` on names.
- A partner matching no TL record: "not a TL creator".
- A named creator with no matching partner: ask for their partner name or promo code in Impact.
- A YouTube creator TL lacks: ask for the channel link, add it with `tl channels find "<link>"`,
  say its TL data takes about a day, and report it from Impact only until then. Run
  `tl channels find` only on a channel TL has or a link the user gave: on an unknown name it
  queues a channel for indexing.
- A promo-code match (key 5) needs a second signal, or it is listed as "probable, please confirm".
- **Several TL channels of one creator:** if the partner has approved actions in the window, show
  the candidates with evidence and ask which to include ("all" means one creator across
  platforms). Otherwise list it as unresolved without asking.
- **An agency** (keys pointing to different creators): split its actions by tracking link or
  SharedId, or ask. Never give an agency's actions to one creator.
- Never open or resolve a tracking link (no browser visit, no redirect-following `curl`): it
  registers a click in the brand's account. A link on the brand's own short domain stays
  unresolved.
- Use only promo codes found on Impact actions; never build one from a creator's name, and never
  call a code the creator's unless it is on their own actions. If the
  creator's actions carry no code, say so. List their codes credited to other partners (mapping
  3.4).
- List TL deals with no Impact partner, with the likely reason.

### 4. Dates and 5. Metrics

Apply mapping 4 (per-deal windows with per-video evidence, otherwise the go-live timeline; social
platforms per 4.5; for creators not booked through TL the user confirms which videos they paid
for) and mapping 2. Build periods by summing each partner's daily numbers between go-live dates.
If a TL deal's `conversions` or `revenue` differs from Impact, show both, labelled; never
overwrite or average.

### 6. Deliver

In this order:
1. Scope: brand, window, action states, currencies and rates, Impact route, credits charged.
2. Each chosen view as a table, then its breakdown table and its "All-in cost to date" block
   (mapping 2.2). Label every figure TL or Impact and every money column with its currency.
3. Join table: partner, channel, deal, key, confidence.
4. Creators not booked through TL, partners that are not TL creators, TL deals with no partner,
   sold deals not yet live.
5. Caveats: pending share, reversed and N/A counts above 0, rates used, deals reported as periods,
   deals with no TL views (mapping 1.4), codes credited to other partners, agencies,
   low-confidence matches.

- When some deals are per-video and others are periods (mapping 4.1), any sentence describing
  the split states both counts from the rows built and names the deals in each group. Never say
  Impact can tell every video apart when any row is a period.
- **Last-click caveat.** Next to every cost per action, return on sponsorship and all-in return,
  note that these use last-click credit in the brand's Impact account: they miss sales the video
  caused that did not come through the link or code. This covers summary figures above a table,
  alternative figures below it and figures in sentences. Naming the attribution model in the scope
  does not cover them, and a note under a later table does not reach a figure quoted earlier.
  Within one section, mark each figure and give the note once, where the first one appears.
- Final figures only: if a figure changes while you write, replace it, with no old figure or
  correction note left in the report.
- Use the `tl` glossary's business terms, not table names. Draw a chart only when asked, as SVG.
- Write nothing to Impact. The only TL write is a channel added from a link the user gave. Set no
  performance grade and edit no sheet.

## Self-check before finishing

1. Read-only held: only allowed Impact calls, change requests declined, the "Read-only run" line
   in the scope, the run's own files deleted, no credential passed through chat.
2. Seller login and Partner account stopped at setup.
3. The view came from the request or the user's answer; the scope was stated back.
4. Worst case before any call, one probe before the quote, quote before the pull, credit total
   reported with failed reads included.
5. Every read paged to its `total`; a short read stopped the run.
6. No `Contacts[]`, customer field or e-mail address read or shown.
7. Coverage count reported, labelled brand-wide.
8. Every partner has a key, a confidence and a group; no `ILIKE`; no tracking link opened; no
   `tl channels find` on an unknown name; agencies split or asked.
9. TL views only from resolved video-index documents (mapping 1.4).
10. Performance tied to one deal only with per-video evidence; otherwise a go-live timeline with
    the shared-link sentence above it.
11. Last-click caveat beside every cost per action and return figure, above and below tables too.
12. Mapping 2 and 2.3 hold: currencies named on every money column, Paid to TL and commission
    apart.
13. Promo-code sales count like link sales: approved actions state the promo-code split on every
    table row and in the opening summary, with "by promo code" / "by link" only where Impact shows
    how the sale was credited (mapping 2.2); a withheld conversion rate points to actions per
    1,000 views when available; a creator with codes credited to other partners has the
    "including" line (mapping 3.4).
