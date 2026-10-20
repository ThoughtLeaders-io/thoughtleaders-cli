# Impact → TL mapping

How Impact terms, metrics and ids map to TL data. Sections 1 and 2 are vocabulary and metrics,
3 and 4 the join. TL columns are on `thoughtleaders_adlink` unless another table is named;
TL-only facts (deal statuses, TL dates, grade codes) are in the `tl` skill's references.

**Columns.** Select only the columns this file and `SKILL.md` name. `tl schema pg` lists every
column, but a caller's query can run against a smaller schema and reject one (`42703`, "column
does not exist"). If that happens, drop the column, re-run, and name the figure that is now
unavailable.

## 1. Vocabulary

### 1.1 Entities

| Impact (UI / API) | TL equivalent | Notes |
|---|---|---|
| Account / `AccountSID` | Brand (`tl brands find`) | A Brand account is one brand |
| Program (older UI: Campaign) / `CampaignId`, `CampaignName`, `ProgramId` | The brand's affiliate program, `thoughtleaders_brand.id` | Not a TL Campaign. A brand can run several Programs |
| Partner / `MediaPartnerId`, `MediaPartnerName` (Actions), `MediaId`, `MediaName` (Clicks) | Channel, via the deal's `channel_id` | Not a brand. Can be an agency holding several channels |
| Partner property / `Properties[].Url`, `.Platform` | `thoughtleaders_channel.url`, `common_name` (@handle) | Strongest partner to channel link |
| Partner website / `Website` | Sometimes the channel URL | Often a personal site |
| Contract / `ContractId`, `ContractName` | none | Commission terms, not a TL IO |
| Ad / `AdId`, `AdName`, `AdType` | Loosely `tracking_url` | A tracking link or creative, not a TL Ad Spot |
| Tracking or vanity link (often `<brand>.sjv.io`) | `tracking_url` | Issued per partner |
| Promo code / `PromoCode` | none | TL stores no promo code. Read against creator aliases (3.2 key 5) |
| Action / `Action` | `conversions` (count only) | One sale, sign-up or install credited to a partner |
| Event type / `ActionTrackerName`, `EventCode` | none | The brand's label ("Online Sale", "Subscription"). Counts shown per type (2) |
| Action inquiry | none | A partner claiming an uncredited sale |
| Transactions, Requests, Content, Refer & Earn, Data Lab | none | Out of scope |

### 1.2 Dates

| Impact field | Meaning | Use |
|---|---|---|
| `EventDate` (Action) | Conversion date | Windows and periods, against `publish_date` |
| `ReferringDate` (Action) | Winning click date | Gap to `EventDate` is the attribution window |
| `EventDate` (Click) | Click date | Against `publish_date` |
| `CreationDate` | When Impact recorded it | Never for windows |
| `LockingDate` | Pending becomes final | The action can change until then |
| `ClearedDate` | Commission paid out | none |

`publish_date` is the only TL date for windows. It is a timestamp, so end a window with
`publish_date < '<day after the window end>'`; `<= '<window end>'` drops the last day.

### 1.3 Action states

| State | Meaning | Rule |
|---|---|---|
| `APPROVED` | Locked or approved | Headline numbers |
| `PENDING` | In the brand's review window, can reverse | Beside approved, labelled "pending" |
| `REVERSED` | Refund, fraud, duplicate or credited elsewhere | Excluded; count in the caveats when above 0 |
| `N/A (Media Source)` | Not commissionable | Excluded; count in the caveats when above 0 |

Match states ignoring case (reports write "Approved", the API `APPROVED`). Impact dashboard totals
include pending, so every number says which states it counts.

### 1.4 TL views on a deal

A deal has TL views only if its video id resolves to a video-index document with a `views` value.
Otherwise it is listed as "no TL views" and left out of views, CPM and per-1,000-view figures; its
price still counts in Paid to TL.

- The video id is `article_id`. If that is empty, it is `<channel_id>:<youtube_id>`, where
  `<youtube_id>` is the `v=` value in `media_url` (the bare `v=` value never matches). If
  `media_url` has no `v=` value, the deal has no video id. Never guess one.
- Podcast, newsletter, TikTok and Instagram documents resolve but have no `views` field.
- The label is "no TL views", never "social post": podcast and newsletter deals are most of this
  group.
- The rule reads the document, not the deal's format, so it also covers an unset format and a
  video TL has not indexed.

## 2. Metrics

| Impact metric | Built from | TL counterpart | Rule |
|---|---|---|---|
| Clicks | Unique clicks (`UniqueClick`) | `total_clicks`, `unique_clicks` | Use Impact's; TL's are mostly empty. Label "clicks tracked by Impact" |
| Actions | Count of actions, by state | `conversions` | Use Impact's; TL's is hand-entered on few deals |
| Action Cost | Sum of `Payout` | none | Commission paid to the creator through Impact. Never the TL price |
| Revenue | Sum of `Amount` | `revenue` + `revenue_currency` | The brand's sales; in TL "revenue" means deal price. Write "sales revenue (Impact)" |
| Total Cost | A grouped report's Total Cost (schema: *Reports*) | none | Action + Click + Other Cost, no Impact platform fee. Never sum `ClientCost` for it. If the route gives neither Total Cost nor all three parts for the same scope, mark it unavailable. Whole-program cost only. A flat fee paid through Impact sits in `Other_Cost`: if it could be the same fee as a TL `price`, ask before adding them |
| Conversion rate | Actions ÷ clicks | none | Impact only; withheld per the rule below |
| none | | Views (1.4); `projected_views_at_purchase_date` | TL only. Impact has no views |
| none | | Paid to TL: `price` + `price_currency` | TL only |
| none | | Sponsorship CPM: Paid to TL ÷ current TL views × 1,000 | On deals with TL views; never from projected views |
| none | | `performance_grade` | Never set by this skill |

**Conversion rate.** Check each rate on screen against its own actions (each period row, each
creator total), counting headline states only. If more than half of those actions carry a promo
code, show `code-tracked (N%)` in the cell instead of a rate, N being that share in whole percent;
exactly half keeps the rate. Explain once: a code sale needs no click, so the rate could count
sales the clicks did not produce; actions per 1,000 views counts code and link sales alike. If the
row has no or zero TL views, say actions per 1,000 views is unavailable; never invent views or
divide by zero.

**Event types.** Approved actions per event type plus "all event types"; sales revenue and
commission sum across types.

**Breakdown table**, under each view, per creator: one section each for event type, promo code and
Ad, with approved actions, pending actions, sales revenue and commission per value. Skip a section
only when the field is blank on every action. Clicks are per partner only.

Actions and clicks per 1,000 views (Impact ÷ TL views × 1,000) go in the table; return on
sponsorship and all-in return only in the block (2.2).

### 2.1 Two costs

| | Paid to TL | Commission (Impact) |
|---|---|---|
| Field | `price` (+ `price_currency`) | Action Cost (sum of `Payout`) |
| Timing | Fixed before the video | Grows with every sale, after the video too |
| Currency | USD | The Impact currency, shown in USD (2.3) |

What the brand paid, by group:

| The creator was | Source of truth | Also shown |
|---|---|---|
| Booked through TL | Paid to TL | Commission, as its own figure |
| Booked through TL and outside TL | Paid to TL, for the TL videos | Impact payments that per-video evidence (4.1) ties to other content, own line labelled "outside TL bookings". Without that evidence they stay in the block's commission, under its "Commission may include other sales" note |
| Never booked through TL | **Impact payments**: the partner's commission plus fixed payments (`Action_Cost` + `Other_Cost`), plus `Click_Cost` when the route reports it | Nothing from TL |

Never replace Paid to TL with an Impact number. Commission sits next to Paid to TL, never inside
it (0 when there is none); the two are added only in the block.

### 2.2 Performance table and the "All-in cost to date" block

**Required columns**, scorecard or timeline, in this order, on every row even when 0 or blank:
Impact clicks, approved actions, pending actions, conversion rate, sales revenue, commission
(approved), TL views, Paid to TL, sponsorship CPM, actions per 1,000 views, clicks per 1,000 views.
A column is never dropped for being all 0 or blank: a reader cannot tell a missing column from
zero. No table figure adds commission to Paid to TL.

**Promo-code split.** A code sale counts like a link sale everywhere. On every row of the table,
each go-live period and the creator total included, and in the opening summary, split approved
actions by the promo-code field: "40 (12 with promo code, 28 without)". Code sales land in the
period of their own date, the same way clicks do.
This is code use, not attribution. Write "by promo code" / "by link" only when Impact shows how
the sale was credited. If the field is unavailable, say the split is unavailable.

**Package pricing.** A row containing a deal priced 0 drops its sponsorship CPM and nothing else.
The creator total row and the block keep their CPM.

**Pending check**, printed under every table: pending summed across rows against the creator
total, e.g. "pending across periods (4) = creator total (4)". If they differ, print the gap and
the rows.

**Block**, one per creator, under the table. Commission builds up while the fee is fixed, so the
two are combined only over the same videos and dates:

| Line | Definition |
|---|---|
| TL videos included | Every live sold TL deal for this brand and creator, across their TL records in scope, to today |
| Paid to TL | Sum of those prices |
| Commission since the first TL video | Approved, first TL go-live to today (2.3) |
| Commission before the first TL video | Approved, partner's first action to the day before the first go-live. Own line, labelled "before the first TL video", in no all-in figure |
| All-in cost | Paid to TL + commission since the first TL video |
| Views to date | Current TL views of those videos, each video once (same `article_id` or `media_url`), each deal's price still counted. Deals with no TL views listed by id and left out. Never channel totals |
| Sponsorship CPM / all-in CPM | Paid to TL ÷ views × 1,000 / all-in cost ÷ views × 1,000 |
| Approved actions since the first TL video | Same dates as the commission |
| Sponsorship / all-in cost per action | Paid to TL ÷ actions / all-in cost ÷ actions |
| Return on sponsorship / all-in return | Sales revenue since the first TL video ÷ Paid to TL / ÷ all-in cost |

- Always to date, whatever the table's window; title it with both dates, e.g. "All-in cost to
  date, as of 30 Sep 2026, since the first TL video on 2 Jun".
- Per video only with per-video evidence (4.1).
- Pending commission is left out and mentioned beside the block. If the route cannot separate it,
  say so.
- If any deal has no TL views, add: its price is in Paid to TL but its views are not in the
  denominator, so both CPMs read higher than what was delivered.
- Under the block: "Commission may include other sales."
- Every CPM here uses Paid to TL. The only CPM on an Impact cost is "CPM on what you paid through
  Impact", for creators not booked through TL (4.4).

### 2.3 Currency

TL prices are USD and the report is in USD. Name the currency on every money heading, e.g. "Paid to
TL (USD)", "Sales revenue, Impact (USD; EUR original)"; a currency in the table title covers the
table. A 0 is still money and needs its currency. If Impact already converted a report (its
display-currency setting), say so.

- Never convert the TL price. If a deal's `price_currency` is not USD, name the deal to the user,
  keep its price in that currency, and hold every USD total or ratio that depends on it until its
  USD price is confirmed. Never relabel it USD, add it to a USD sum, or drop the deal silently.
- Impact figures in USD: no conversion.
- Otherwise (usually EUR): show every Impact money figure in USD with the original beside it,
  e.g. "Commission, Impact (USD 1,352; EUR 1,240)". Use the ECB euro reference rate for USD,
  averaged over the month of the activity; convert each month at its own rate, then sum. Another
  currency goes through the euro. Look the rate up, never from memory. If the monthly average is
  not out yet, average that month's daily rates and say so. With no rate, show the original only,
  say a rate is needed, and hold figures that mix currencies. Show the rates used.

## 3. Identity join

### 3.1 Creator aliases

For each creator in scope, from TL: `channel_name` and `common_name` of each of their TL records
(YouTube and any separate TikTok or Instagram record), the handle in each `url`, and the handles in
`social_links` (named keys, SKILL.md *Personal data*). Match exactly, ignoring case (`UPPER()` on
both sides): try each alias as written and with `@`, spaces and punctuation removed.

### 3.2 Partner to creator

Try every key, and every property on the partner. The strongest key that resolves sets the match
and its confidence. A key that points to another TL channel makes the partner multi-channel
(another record of the same creator) or an agency (a different creator): SKILL.md stage 3.

| # | Impact field | TL field | Strength | Notes |
|---|---|---|---|---|
| 1 | Partner tracking or vanity link | `tracking_url` | Strong | Equal as whole strings, ignoring `https://`, `www.` and a trailing slash, on any domain |
| 2 | `Properties[].Url` | `url` or `external_channel_id` of any of the creator's records | Strong | |
| 3 | Partner name, `Website` or a `Properties[]` handle | An alias (3.1) | Strong if exact | |
| 4 | `SharedId`, SubIds or `PartnerValues` holding a TL id | `adlink.id` or `thoughtleaders_channel.id` | Strong if a TL id is there | Check the first 20 actions first |
| 5 | Promo code on the partner's own actions | Contains an alias (3.1), e.g. "JANE10" for "Jane Cooks" | Medium | Needs a second signal |
| 6 | `MediaPartnerId` | none | | TL stores no Impact partner id |

Second signals for key 5 (at least one):
- The partner's first action is within 14 days after the creator's first TL go-live for the brand.
- The partner's Impact contract name mentions ThoughtLeaders.
- A property URL or country consistent with the TL record.

### 3.3 Action to deal (per-video evidence)

| Impact field | TL field | Notes |
|---|---|---|
| Tracking link | `tracking_url` on only one deal | A link shared across deals identifies the creator, not the video (4.2) |
| `SharedId` or a SubId holding the TL deal id | `adlink.id` | |
| Ad unique to one video | `media_url` of one deal | Only when the Ad's name or link names the video |

A promo code is never per-video evidence: TL stores no codes, so a code reaches the creator, not a
deal. A social platform separates platforms, not videos (4.5).

### 3.4 The creator's codes credited to other partners

The creator's codes are the promo codes on their own actions that contain an alias (3.1). Actions
using them but credited to another partner go on their own line under the creator, "creator's code,
credited to <partner>", with counts, sales revenue and commission, outside the creator's totals.
Under the totals add "including the creator's code credited to other partners": approved actions
and sales revenue with those actions added. The commission stays with the partner it was paid to.

### 3.5 Coverage count

```sql
SELECT COUNT(*) AS sold,
  COUNT(*) FILTER (WHERE COALESCE(al.tracking_url,'') <> '') AS has_tracking_url,
  COUNT(*) FILTER (WHERE COALESCE(al.media_url,'') <> '')    AS has_video_url
FROM thoughtleaders_adlink al
JOIN thoughtleaders_profile_brands pb ON pb.profile_id = al.advertiser_profile_id
WHERE pb.brand_id = <brand_id> AND al.publish_status = 3
LIMIT 1 OFFSET 0
```

Tracking links and video links are the keys worth counting (TL holds no codes and few clicks).
Report the counts as what this login sees, not as the brand's whole history. If the deal keys in
3.3 are thin, the result is a go-live timeline (4.2), or the mixed case when only some deals carry
their own key (4.1).

## 4. Dates

Impact knows which creator drove a sale. It knows which video only if each video had its own link
or id.

### 4.1 Per-video evidence

With a 3.3 key, attribute performance to that deal in windows from its `publish_date` (default 0 to
30, 31 to 90, over 90 days).

**Mixed coverage** is common: some of a creator's deals have their own key and the rest share a
link. Deals with their own key get per-deal windows. The rest become shared-link periods (4.2)
built from those deals' go-live dates and the actions not already attributed. Name which deals are
which in the table and the caveats. Never give a shared-link deal's results to one video, and never
merge the creator into one timeline because some deals share a link.

### 4.2 Go-live timeline (no per-video evidence)

One row per go-live date of this brand and creator, each with Impact's numbers from that date to
the day before the next go-live. If only some deals share the link, use mixed coverage (4.1).

- Directly above the table: "All of this creator's videos use the same Impact link, so Impact
  cannot tell them apart. Each period shows what came in after that go-live and before the next
  one. Earlier videos were still live and may have driven part of it."
- Columns: go-live date, TL deal(s), Impact period, then the required columns (2.2). One approved
  actions column per event type when there is more than one, plus "all event types".
- Deals live on the same day share a row with all their ids. Go-lives on different days are always
  separate rows, however close.
- Views count each video once (same `article_id` or `media_url`), with each video's views in
  brackets. A video on several go-live dates counts on its first row; later rows read "views
  counted on <date>".
- Deals with no TL views are marked in their row and named under the table.
- First row: if a TL video went live before the window, the latest such deal, with its real date,
  marked "went live before the window", its period starting at the window start. Otherwise "before
  the first TL video", from the window start to the day before the first go-live.
- The last row runs to the window end, then a creator total row, then the pending check (2.2).
- Sold deals with no `publish_date` are listed under the table.
- Decay view, or on request: one row per week, go-live weeks marked, same rules.

### 4.3 Lifetime totals

Impact's partner totals are lifetime and hide decay. Never judge a creator on one.

### 4.4 Partner groups

| Group | Definition | Shown |
|---|---|---|
| Booked through TL | TL channel with a sold deal for this brand | Table and block |
| Not booked through TL | TL channel, no sold deal for this brand | Impact results; Impact payments (2.1) in USD as the cost; cost per action = Impact payments ÷ approved actions; the channel's TL subscribers, projected views and whether it is immediately bookable (`is_tpp`, `tl` glossary) |
| Not a TL creator | No TL channel | Impact results and Impact payments only |

- For the last two groups, Paid to TL reads "not booked through TL", never 0. Invent no TL figure.
- Not booked through TL: search TL's video index for the channel's videos in the window that
  mention the brand (`channel.id`, the brand id in `all_brand_mentions`, `publication_date` in
  range; syntax in the `tl` skill's Elasticsearch reference). List date, title and views, ask which
  ones the brand paid for (pasted links also work), and use only confirmed videos:
  - CPM: Impact payments ÷ confirmed videos' TL views × 1,000, labelled "CPM on what you paid
    through Impact".
  - Rebooking signal: each confirmed video's `projected_views` against the channel document's
    current projection, as a percent change: `impression` for a longform video,
    `impression_shorts` for a short, `impression_live` for a live stream. A channel document has
    no `projected_views` field (the query returns nothing, without an error). Skip the signal for a
    video whose format is unknown.
- Money compared across groups is in one currency (2.3), rate shown.

### 4.5 Social platforms

A platform split comes from Impact: the action's social platform, the partner property it came
through, or an Ad used on one platform only. TL deals carry no platform.

- With a split: report YouTube against the TL deals with TL views (4.2), and each social platform
  with Impact's results and what the brand paid through Impact as its cost. A TL deal with no TL views sits under the
  platform its `media_url` names, or outside the split when none is named.
- Without a split: one timeline and one block for the creator across all platforms.

## 5. Account type

| | Brand account (runs) | Partner account (stops) |
|---|---|---|
| API base | `/Advertisers/{AccountSID}/` | `/Mediapartners/{AccountSID}/` |
| Web app address | `/secure/advertiser/` | `/secure/mediapartner/` |

## 6. Do not confuse

- Impact Program ≠ TL Campaign; Impact Ad ≠ TL Ad Spot; Impact Contract ≠ TL IO.
- Impact Partner ≈ TL channel, not brand, and sometimes an agency.
- Impact Revenue (the brand's sales) ≠ TL revenue (deal price).
- Action Cost, Total Cost, Impact payments and the TL price are four different amounts.
- Sponsorship CPM (table) ≠ all-in CPM (block only).
- A go-live period ≠ one video's results.
- "Not booked through TL" ≠ unmatched.

## TL columns this skill relies on

Kept here until they move to the `tl` skill's references.

| Column | Fact |
|---|---|
| `adlink.tracking_url` | The partner's tracking or vanity link on the deal; join key 3.2 #1 |
| `adlink.cta_text` | Call-to-action text, labelled "promo code" in the web app but not a promo code. Never read as one |
| `adlink.media_url` | The sponsored video's link (destination links are in `urls`); source of the video id when `article_id` is empty (1.4) |
| `adlink.conversions` | Action count, hand-entered on few deals |
| `adlink.revenue` + `revenue_currency` | Sales revenue, hand-entered on few deals |
| `adlink.price_currency` | Currency of `price`: USD, never converted (2.3) |
| `adlink.projected_views_at_purchase_date` | TL's projected views for the video, frozen at the purchase date. Never a source for CPM (2.2) |
| `adspot.ad_format` | 4 YouTube, 8 TikTok, 9 Instagram, other values other placements. Not a test for TL views (1.4) |
| `channel.social_links` | Platform keys, an `_other` dict and an `_emails` array; read named keys only (SKILL.md *Personal data*) |
