# Impact → TL mapping

The single source for how Impact terms, metrics and IDs map to TL data. Sections 1 and 2 are
vocabulary; sections 3 and 4 are the identity join. TL columns are on `thoughtleaders_adlink`
unless another table is named. TL-only facts (deal statuses, TL dates, grade codes) live in the
`tl` skill's references.

Select only the columns this file and `SKILL.md` name. `tl schema pg` prints the full schema to
every caller, but an external caller's query runs against a restricted schema holding fewer
columns, so the listing can show a column the query then rejects (`42703`, "column does not
exist"). IF a query is rejected for a missing column, drop the column and re-run: the schema
listing cannot tell you whether this caller may read it.

## 1. Vocabulary

### 1.1 Entities

| Impact (UI / API) | TL equivalent | Notes |
|---|---|---|
| Account / `AccountSID` | Brand (`tl brands find`) | A Brand account is one brand. |
| Program, older UI Campaign / `CampaignId`, `CampaignName`, `ProgramId` | The brand's affiliate program, `thoughtleaders_brand.id` | Not a TL Campaign (a report or deal group). One brand can run several Programs. |
| Partner, Media Partner / `MediaPartnerId`, `MediaPartnerName` (Actions), `MediaId`, `MediaName` (Clicks) | Channel, via `ad_spot_id → adspot.channel_id` | Not a brand. Can be an agency holding several channels. On a Partner account see section 5. |
| Partner property / `Properties[].Url`, `.Platform` | `thoughtleaders_channel.url`, `common_name` (@handle) | Strongest partner → channel bridge. |
| Partner website / `Website` | Sometimes the channel URL | Often a personal site. |
| Contract / `ContractId`, `ContractName` | none | Commission terms. Not a TL IO. |
| Ad / `AdId`, `AdName`, `AdType` | Loosely `tracking_url` | A tracking link or creative. Not a TL Ad Spot. |
| Tracking or vanity link (often `<brand>.sjv.io`) | `tracking_url` | Issued per partner. |
| Promo code / `Action.PromoCode` | none | TL stores no promo code. The code is Impact's, and is read against creator aliases (3.2 key 5), never against a TL column. |
| Action, Conversion / `Action` | `conversions` (count only) | One sale, sign-up or install credited to a partner. |
| Event type / `ActionTrackerId`, `ActionTrackerName`, `EventCode` | none | The brand's label ("Online Sale", "Subscription", "Top-up"). Counts are shown per type (section 2). |
| Action inquiry / `ActionInquiry` | none | A partner claiming an uncredited sale. |
| Transactions, Requests, Content, Refer & Earn, Data Lab | none | Out of scope. |

### 1.2 Dates

| Impact field | Meaning | Use |
|---|---|---|
| `EventDate` (Action) | Conversion date | Periods and windows, compared with `publish_date` |
| `ReferringDate` (Action) | Winning click date | The gap to `EventDate` is the attribution window |
| `EventDate` (Click) | Click date | Compared with `publish_date` |
| `CreationDate` | Date Impact recorded it | Never for performance windows |
| `LockingDate` | Pending becomes final | Until then the action may still change |
| `ClearedDate` | Commission paid out | none |

`publish_date` is the only TL anchor for performance windows.

`publish_date` is a timestamp, so a window end is written `publish_date < '<day after the window
end>'`. `<= '<window end>'` resolves to midnight and drops the whole last day.

### 1.3 Action states

| State | Meaning | Rule |
|---|---|---|
| `APPROVED` | Locked or manually approved | Headline numbers |
| `PENDING` | In the brand's review window, can reverse | Shown beside approved, labelled "pending" |
| `REVERSED` | Refund, fraud, duplicate or credited elsewhere | Excluded; report the count |
| `N/A (Media Source)` | Not a commissionable state | Excluded from approved and pending; report the count |

Match state values case-insensitively (reports write "Approved", the API `APPROVED`). Impact
dashboard totals include pending. Every number states which states it includes.

### 1.4 TL views on a deal

A deal has TL views if and only if its video id resolved to a video-index document carrying a
`views` value. A deal whose id does not resolve, or whose document carries no `views` field, is
listed as "no TL views" and left out of views, CPM and per-1,000-view figures; its price still
counts in Paid to TL.

- A deal's video id is its `article_id`. IF `article_id` is empty, build it as
  `<channel_id>:<youtube_id>`, where `<youtube_id>` is the `v=` value in `media_url`. The bare
  `v=` value alone never matches. A deal with neither has no video id, so no TL views.
- Documents for other formats — podcast, newsletter, TikTok, Instagram — resolve but carry no
  `views` field at all.
- The label is "no TL views", never "social post": podcast and newsletter are the larger part of
  that population (about 10.7% of sold deals, against 0.5% for TikTok and Instagram together).
- The rule reads the document, not the deal's format, so it also catches a deal whose format is
  unset and a video TL has not indexed.
- Platform lanes come from the Impact side (4.5), not from the TL deal.

## 2. Metrics

| Impact metric | Built from | TL counterpart | Rule |
|---|---|---|---|
| Clicks | unique clicks (`UniqueClick` on the Click object) | `total_clicks`, `unique_clicks` | Use Impact's; TL click columns are mostly empty on sold deals. Label "clicks tracked by Impact". |
| Actions | count of Actions, by state | `conversions` | Use Impact's; the TL value is hand-entered on few deals. |
| Action Cost | sum of `Payout` | none | Affiliate commission paid to the creator through Impact. Never the TL price (2.1). |
| Revenue | sum of `Amount` | `revenue` + `revenue_currency` | The brand's sales. In TL, "revenue" means sold deal price. Write "sales revenue (Impact)". |
| Total Cost | sum of `ClientCost` | none | Commission plus Impact fees and bonuses; not the creator's cost. Use only for whole-program cost. A flat fee paid through Impact sits in `Other_Cost`, inside Total Cost: IF it could be the same fee as a TL `price`, ask before adding them. |
| Conversion Rate | Actions ÷ Clicks | none | Impact actions over Impact clicks only. Suppressed per displayed ratio when the code-tracked share passes half (below). |
| none | | Views: `views` on the video-index document (1.4), `projected_views_at_purchase_date` | TL only. Impact has no views. |
| none | | Paid to TL: `price` + `price_currency` | TL only. |
| none | | Sponsorship CPM: Paid to TL ÷ the video's current TL views × 1,000 | Always computed, on deals with TL views (1.4). Never from projected views (2.2). |
| none | | `performance_grade` | Never set by this skill. |

**Conversion rate, suppressed per displayed ratio.** Test the code-tracked share once per ratio
on screen — each period row against that row's own actions, each creator total against that
creator's actions — never once over the window and applied to every cell.

- The denominator is the headline action states only: approved, or approved plus pending when
  the user asked to include pending. `REVERSED` and `N/A (Media Source)` are out of every
  headline number, here too.
- IF more than half of those actions carry a promo code, render the cell as `code-tracked (N%)`,
  N being the code-tracked share of that same denominator in whole percent. No rate beside it,
  and never a blank cell: the column keeps its shape so the reader can tell suppression from
  absence.
- ELSE print the rate.
- Give the reason once in the output: a sale made with a promo code never had to click, so the
  rate would count conversions the clicks could not have produced.

Event types: show approved actions per event type, plus a total labelled "all event types".
Sales revenue and commission sum across types.

**Breakdown table**, under each view, per creator: one section each for event type, promo code and
Ad, with approved actions, pending actions, sales revenue and commission per value. Skip a section
only when that field is blank on every action. Clicks are not split: Impact counts them per
partner, not per code, type or sale.

Other cross metrics:
- Actions per 1,000 views and clicks per 1,000 views (Impact ÷ TL views × 1,000): in the table.
- Return on sponsorship and all-in return: in the to-date block only (2.2).

### 2.1 Two costs

| | Paid to TL | Affiliate commission through Impact |
|---|---|---|
| Field | `price` (+ `price_currency`) | Action Cost (sum of `Payout`) |
| Timing | Fixed before the video | Grows with every sale, including after the video |
| Currency | The deal's `price_currency` | The Impact account's currency |

Source of truth for what the brand paid:

| The creator was | Source of truth | Also shown |
|---|---|---|
| Booked through TL | Paid to TL, in its own currency | Commission, as its own figure |
| Booked through TL and outside TL | Paid to TL, for the TL videos | Impact payments outside the TL bookings, own line, labelled "outside TL bookings" |
| Never booked through TL | Commission plus fixed payments through Impact (`Other_Cost`) | Nothing from TL |

- Never replace Paid to TL with an Impact number.
- Show commission next to Paid to TL, never inside it. No commission in the window shows 0.
- Paid to TL plus commission appears only in the "All-in cost to date" block (2.2).

### 2.2 Performance table and the "All-in cost to date" block

Commission accumulates while the fee is fixed, so a combined figure is valid only over the same
videos and the same dates.

**Required columns** (scorecard or timeline), in this order, printed on every row even when the
value is 0 or blank: Impact clicks, approved actions, pending actions, conversion rate, sales
revenue, commission (approved only), TL views, Paid to TL, sponsorship CPM, actions per 1,000
views, clicks per 1,000 views. No figure that adds commission to Paid to TL.

**Package pricing** — a row whose deals are priced 0 — drops that row's sponsorship CPM and
nothing else. Pending actions, clicks, views and both per-1,000-view columns stay, on that row
and on every other.

A column is never dropped because its values are all 0 or all blank. A missing column reads as
"not shown", and a reader cannot tell that apart from zero.

**Pending reconciliation**, printed under every table: the pending actions summed across the rows
set against the creator total, e.g. "pending across periods (4) = creator total (4)". IF the two
differ, print the difference and name the rows that disagree. Running the check without printing
it does not satisfy this.

**Block**, one per creator, under the table:

| Line | Definition |
|---|---|
| TL videos included | Every live sold TL deal for this brand and creator, across the creator's TL records in scope, to today |
| Paid to TL | Sum of those prices, in the price currency |
| Commission since the first TL video | Approved, first TL go-live to today, converted (2.3) |
| Commission before the first TL video | Approved, from the partner's first action to the day before the first go-live. Own line, labelled "outside TL bookings". Not added to any all-in figure |
| All-in cost | Paid to TL + commission since the first TL video |
| Views to date | Current TL views of those videos. Count each video once (same `article_id` or `media_url`); each deal's price still counts. Deals with no TL views (1.4) are listed by id and left out. Never channel total views |
| Sponsorship CPM / all-in CPM | Paid to TL ÷ views × 1,000 / all-in cost ÷ views × 1,000 |
| Approved actions since the first TL video | Impact, same dates as the commission |
| Sponsorship / all-in cost per action | Paid to TL ÷ actions / all-in cost ÷ actions |
| Return on sponsorship / all-in return | Sales revenue since the first TL video (converted) ÷ Paid to TL / ÷ all-in cost |

- Always to date, whatever window the table uses. Title it with both dates, e.g. "All-in cost to
  date, as of 30 Sep 2026, since the first TL video on 2 Jun".
- Per video only when that video has per-video evidence (4.1).
- Exclude pending commission and mention it beside the block. IF the route cannot separate
  approved from pending commission, say so.
- IF any deal is listed with no TL views (1.4): add a caveat line saying its price sits inside
  Paid to TL while its views stay outside the denominator, so sponsorship CPM and all-in CPM both
  read higher than the cost per 1,000 views actually delivered.
- Put the note "Commission may include other sales." under the block.
- Never compute a CPM from Action Cost alone or call an Impact cost a CPM.

### 2.3 Currency

Every money heading names its currency, in every case, e.g. "Paid to TL (USD)", "Sales revenue,
Impact (EUR)". A currency named once in the table's title covers that table. A money cell reading
0 is still a money cell: "0" alone does not say which currency it is zero of, and a row that is
otherwise empty — no commission before the first TL video, no sales in the period — is exactly
where the heading is easiest to lose. Record the currency of the Impact figures from the report or
export; reports have a display-currency setting, so say so when Impact has already converted them.

- IF the Impact figures are in the TL `price_currency`: no conversion.
- ELSE, when money is compared with money (everything in the all-in block): add a converted column
  beside the original one, never in place of it. Money divided by a count or by views (sponsorship
  CPM, sponsorship cost per action) is not converted.
  - Convert the Impact figure into the price currency. Never convert the TL price.
  - Rate: the ECB euro reference rate, averaged over the month of the Impact activity. Convert
    each month at its own rate, then sum. Convert other currencies through the euro.
  - Look the rate up; never use one from memory. IF the month's average is not yet published,
    average that month's published daily rates and say so. IF no rate is found, show the original
    currency only and say a rate is needed.
  - Show the rates used in the column name or a note.

## 3. Identity join

Two steps: partner to creator (3.2), then action to deal where the data allows (3.3).

### 3.1 Creator aliases

For each creator in scope, collect from TL: `channel_name` and `common_name` of every TL record of
the creator (the YouTube channel and any separate TikTok or Instagram record), the handle in each
record's `url`, and the handles in `social_links`. Compare case-insensitively, ignoring `@`,
spaces and punctuation.

⚠️ Read `social_links` by **named platform key** (`youtube`, `tiktok`, `instagram`, …). Never
select the column wholesale and never read `_emails`: it holds the creator's contact addresses,
which are not aliases and have no place in a performance report or in a chat transcript. The
video index mirrors the same links with e-mails stripped, so it is the safer source.

### 3.2 Partner to creator

Stop at the first key that resolves.

| # | Impact field | TL field | Strength | Notes |
|---|---|---|---|---|
| 1 | Partner tracking or vanity link | `tracking_url` | Strong | String equality on the whole link, ignoring `https://`, `www.` and a trailing slash. Host-agnostic: it fires wherever TL stored a `tracking_url`, whatever domain the link is on (about 82% of sold deals) |
| 2 | `Properties[].Url` | `url` or `external_channel_id` of any of the creator's records | Strong | |
| 3 | Partner name, `Website` or a `Properties[]` handle | An alias (3.1) | Strong if exact | |
| 4 | `SharedId`, SubIds or `PartnerValues` holding a TL id | `adlink.id` or `thoughtleaders_channel.id` | Strong if a TL id is there | Check a sample first |
| 5 | Promo code on the partner's own actions | Contains an alias (3.1), e.g. code "JANE10" for "Jane Cooks" | Medium | The code is Impact's; the match is against TL aliases, not a TL column. Needs a second signal |
| 6 | Partner name | `channel_name` | Weak | Needs a second signal |
| 7 | `MediaPartnerId` | none | | TL stores no Impact partner id |

Second signals (a medium or weak key needs at least one):
- The partner's first action falls within 14 days after the creator's first TL go-live for the brand.
- The partner's Impact contract name mentions ThoughtLeaders.
- A property URL, country or partner group consistent with the TL record.

### 3.3 Action to deal (per-video evidence)

| Impact field | TL field | Notes |
|---|---|---|
| Tracking link | `tracking_url` on only one deal | A link shared across the creator's deals identifies the creator, not the video (4.2) |
| `SharedId` or a SubId holding the TL deal id | `adlink.id` | |
| Ad unique to one video | `media_url` of one deal | Only when the Ad's name or link identifies the video |
| Social platform or property on the action | none | Separates platform lanes, not videos (4.5) |

A promo code is not a deal key: TL stores no promo code, so a code can reach the creator (3.2 key
5) but never a single deal.

Never open or resolve a tracking link (no browser visit, no redirect-following `curl`); a link on
the brand's own short domain stays unresolved.

### 3.4 The creator's codes credited to other partners

The creator's codes are the promo codes on the creator's own actions that contain an alias
(3.1). They are read from Impact's actions; TL holds no copy of them. Actions using them but
credited to another partner go on their own line under the creator, "creator's code, credited to
<partner>", with counts, sales revenue and commission, not added to the creator's totals.

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

TL click columns are empty on sold deals and TL stores no promo code, so tracking links and video
links are the coverage worth counting. Tracking-link coverage is high overall (about 82% of sold
deals) and varies by brand. IF the deal keys in 3.3 are thin, the result is a go-live timeline
(4.2), or the mixed case when only some deals carry their own key (4.1).

TL channel reads are filtered to active channels for an external caller and not necessarily for an
internal one, so the same brand and window can return different deal counts depending on who runs
it. Report the count as what this caller sees, not as the brand's whole history.

## 4. Dates

Impact knows which creator drove a sale. It knows which video only if each video had its own
link, code or id.

### 4.1 Per-video evidence

Per-video evidence is any deal key in 3.3 except the platform. With it, attribute performance to
that deal in windows from its `publish_date` (default 0 to 30, 31 to 90, over 90 days).

**Mixed coverage.** A creator can have both: some deals carry their own key, the rest share one
link. Among repeat brand × creator pairs 12–22% look like this, so it is the normal third case,
beside per-deal windows and the whole-creator timeline.

- Deals with their own key are attributed per deal, in windows from their own `publish_date`.
- The remaining deals are reported as shared-link periods (4.2), built from those deals' go-live
  dates only, and from the actions not already attributed to a per-video key.
- The output names which deals are per-video and which are periods, in the table and in the
  caveats.
- **Count the table, then write the sentence.** Any opening, summary or narrative line describing
  the split states the two counts taken from the rows actually built — "two of the four bookings
  are scored individually; the other two share a link and are reported as periods" — and names the
  deals in each group. Never describe the split from an impression of the data before the rows
  exist, and never write that Impact can tell every video apart when any row is a period: a
  summary that disagrees with its own table is read first and believed, and it is the one
  statement in the report a buyer repeats to someone else.
- Never attribute a shared-link deal's performance to a single video, and never collapse the
  creator into one timeline because some of their deals share a link.

### 4.2 Go-live timeline (no per-video evidence)

Never attribute performance to individual videos. Build one row per go-live date of this brand
and creator, each with Impact's numbers from that date to the day before the next go-live. IF
only some of the creator's deals share the link, this is the mixed case (4.1), not a whole-creator
timeline.

- Deals live on the same day share one row with all their deal ids. Views are summed counting
  each video once (same `article_id` or `media_url`), with each video's views in brackets.
  Go-lives on different days are always separate rows, however close.
- A video attached to deals on several go-live dates counts its views on its first row only;
  later rows read "views counted on <date>".
- A deal with no TL views (1.4) is listed in its row as "no TL views" and left out of views, CPM
  and per-1,000-view figures.
- IF any deal in the row is priced 0 (package pricing), that row drops its sponsorship CPM and
  keeps every other required column (2.2); the creator total and the block still carry a CPM.
- Under the table, name every deal with no TL views (1.4), as "no TL views".
- IF a TL video went live before the window: the latest such deal is the first row, keeps its
  real date, is marked "went live before the window", and its period starts at the window start.
  ELSE the first row is "before the first TL video" (window start to the day before the first
  go-live).
- The last row runs to the window end. End with a creator total row, then the pending
  reconciliation (2.2).
- Sold deals with no `publish_date` are not live: list them under the table.
- Directly above the table, write: "All of this creator's videos use the same Impact link, so
  Impact cannot tell them apart. Each period shows what came in after that go-live and before
  the next one. Earlier videos were still live and may have driven part of it."
- Columns: go-live date, TL deal(s), Impact period, then the required columns of 2.2. Approved
  actions get one column per event type when there is more than one, plus "all event types".
- Decay view or on request: one row per week, go-live weeks marked, same rules.

### 4.3 Lifetime totals

Impact partner totals are lifetime and hide decay. Never judge a creator on a lifetime total.

### 4.4 Partner groups

| Group | Definition | Shown |
|---|---|---|
| Booked through TL | TL channel with a sold deal for this brand | Scorecard or timeline, and the block |
| Not booked through TL | TL channel, no sold deal for this brand | Impact performance; what the brand paid through Impact as the source of truth, in Impact's currency; cost per action = Impact payments ÷ approved actions; the TL channel's subscribers, projected views and bookability |
| Not a TL creator | No TL channel | Impact performance and Impact cost only |

- For the last two groups, Paid to TL reads "not booked through TL", never 0. Invent no TL figure.
- Videos for "not booked through TL": search TL's video index for the channel's videos in the
  window that mention the brand (channel id, brand id in `all_brand_mentions`, `publication_date`
  in range; syntax in the `tl` skill's Elasticsearch reference). List date, title and views, and
  ask which ones the brand paid for; accept pasted links instead. Use only confirmed videos.
  - CPM: Impact payments ÷ confirmed videos' TL views × 1,000, labelled "CPM on what you paid
    through Impact", in Impact's currency.
  - Rebooking signal: each confirmed video's `projected_views` (frozen when TL first indexed it)
    against the channel document's current projection, as a percent change. The channel
    document's field is `impression`; a `projected_views` field on a channel document matches no
    documents and fails silently, returning nothing rather than an error.
  - Compare like with like: `impression` is the longform projection, and a video's
    `projected_views` is the projection for that video's own format. A longform video goes
    against `impression`, a short against `impression_shorts`, a live stream against
    `impression_live`. IF the video's format is not known, skip the signal for that video — a
    short over a longform baseline is not a meaningful percentage.
- Money compared across groups goes into one currency per 2.3, with the rate shown.

### 4.5 Social platforms

- A lane is an Impact-side platform: the action's social platform, the partner property it came
  through, or an Ad used on one platform only. The TL deal carries no platform in scope.
- IF the creator's actions carry a platform split: report the YouTube lane against the TL deals
  that have TL views (Paid to TL, TL views, 4.2), and each social lane with Impact's results and
  what the brand paid through Impact as its cost. A TL deal with no TL views (1.4) sits in the
  lane its `media_url` names, or outside the lanes when nothing names one, and never carries TL
  views.
- ELSE: one timeline and one block for the creator across all platforms. Deals with no TL views
  are listed as such and named under the table (4.2).

## 5. Account type

| | Brand account | Partner account (TL's or a creator's) |
|---|---|---|
| API base | `/Advertisers/{AccountSID}/` | `/Mediapartners/{AccountSID}/` |
| Web app address | `/secure/advertiser/` | `/secure/mediapartner/` |
| The brand | The account | `CampaignName` on each row, via `tl brands find` |
| The channel | Each partner | Not the partner; use the link, promo code or SharedId |
| `Payout` means | Commission the brand pays | Commission this account earns |
| TL deals in scope | Sold deals with this brand as advertiser | Sold deals TL brokered for the account's brands |

## 6. Do not confuse

- Impact Program ≠ TL Campaign. Impact Ad ≠ TL Ad Spot. Impact Contract ≠ TL IO.
- Impact Partner ≈ TL channel, not brand, and sometimes an agency.
- Impact Revenue (brand's sales) ≠ TL revenue (sold price).
- Action Cost, Total Cost and the TL price are three different amounts.
- Sponsorship CPM (table) ≠ all-in CPM (to-date block only).
- A go-live period ≠ one video's performance.
- "Not booked through TL" ≠ unmatched.
- "No TL views" ≠ a social post: podcast and newsletter deals are most of that group (1.4).

## TL schema facts — temporary hold, to be moved

Schema facts belong in the `tl` skill's `references/`, a managed sync of upstream
`thoughtleaders-skills/tl-data/references/`. These nine are held here only until they are moved
there; add no tenth to this block, and state no schema fact outside it.

| Column | Fact |
|---|---|
| `adlink.tracking_url` | The partner's tracking or vanity link as stored on the deal. Populated on about 82% of sold deals; the strongest join key (3.2 key 1). |
| `adlink.cta_text` | The deal's call-to-action text, labelled "promo code" in the web app. It is CTA prose ("Go check them out at coursera.org"), not a promo code: populated on 64 of 23,305 sold YouTube deals (0.27%), 83% of all populated values are newsletter deals, and the values include junk literals (`"null"`, `"''"`, `"-0"`). Never read as a promo code. Absent from the restricted schema. |
| `adlink.media_url` | The sponsored video's own link; destination links live in `urls`. Its video id is the fallback when `article_id` is null (1.4). |
| `adlink.conversions` | Action count, hand-entered; set on few deals. |
| `adlink.revenue` + `adlink.revenue_currency` | Sales revenue and its currency, hand-entered; set on few deals. Elsewhere in TL "revenue" means the sold price. |
| `adlink.price_currency` | The currency of `price`. Never converted (2.3). |
| `adlink.projected_views_at_purchase_date` | TL's projected views for the video, frozen at the purchase date. Never a source for CPM (2.2). |
| `adspot.ad_format` | The ad spot's format code: 4 YouTube, 8 TikTok, 9 Instagram, other values other placements (newsletter, podcast, stream, X). Nullable, and absent from the restricted schema. Not a source for whether a deal has TL views — that is the video-index document (1.4). |
| `channel.social_links` | JSON of the creator's links: platform keys (`instagram`, `tiktok`, …), an `_other` dict of the labelled links in the channel header, and an `_emails` array. ⚠️ Select named keys only. Never select the column wholesale: `_emails` is contact data and has no place in a performance report. |
