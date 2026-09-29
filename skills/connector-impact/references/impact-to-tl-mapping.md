# Impact → TL mapping

The single source for how Impact terms, metrics and IDs map to TL data. Sections 1 and 2 are
vocabulary; sections 3 and 4 are the identity join. TL columns are on `thoughtleaders_adlink`
unless another table is named; confirm an unfamiliar column with `tl schema pg`. TL-only facts
(deal statuses, TL dates, grade codes) live in the `tl` skill's references.

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
| Promo code / `Action.PromoCode` | `cta_text` (web app: promo code) | Rarely filled in TL (3.1). |
| Action, Conversion / `Action` | `conversions` (count only) | One sale, sign-up or install credited to a partner. |
| Event type / `ActionTrackerId`, `ActionTrackerName`, `EventCode` | none | The brand's label ("Online Sale", "App Install"). Never sum across types without saying so. |
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

### 1.3 Action states

| State | Meaning | Rule |
|---|---|---|
| `APPROVED` | Locked or manually approved | Headline numbers |
| `PENDING` | In the brand's review window, can reverse | Shown beside approved, labelled "pending" |
| `REVERSED` | Refund, fraud, duplicate or credited elsewhere | Excluded; report the count |

Impact dashboard totals include pending. Every number states which states it includes.

## 2. Metrics

| Impact metric | Built from | TL counterpart | Rule |
|---|---|---|---|
| Clicks | unique clicks (`UniqueClick` on the Click object) | `total_clicks`, `unique_clicks` | Use Impact's; TL click columns are mostly empty on sold deals. Label "clicks tracked by Impact". |
| Actions | count of Actions, by state | `conversions` | Use Impact's; the TL value is hand-entered on few deals. |
| Action Cost | sum of `Payout` | none | Affiliate commission paid to the creator through Impact. Never the TL price (2.1). |
| Revenue | sum of `Amount` | `revenue` + `revenue_currency` | The brand's sales. In TL, "revenue" means sold deal price. Write "sales revenue (Impact)". |
| Total Cost | sum of `ClientCost` | none | Commission plus Impact fees and bonuses; not the creator's cost. Use only for whole-program cost. A flat fee paid through Impact sits in `Other_Cost`, inside Total Cost: IF it could be the same fee as a TL `price`, ask before adding them. |
| Conversion Rate | Actions ÷ Clicks | none | Impact actions over Impact clicks only. |
| none | | Views: CLI `views` (video index, by `article_id`), `counted_views`, `projected_views_at_purchase_date` | TL only. Impact has no views. |
| none | | Paid to TL: `price` + `price_currency` | TL only. |
| none | | Sponsorship CPM: Paid to TL ÷ the video's current TL views × 1,000 | Always computed. Never from projected views (2.2). |
| none | | `performance_grade` | Never set by this skill. |

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

**Table rows** (scorecard or timeline): Impact clicks, approved actions, pending actions,
conversion rate, sales revenue, commission; TL views, Paid to TL, sponsorship CPM (Paid to TL ÷
TL views × 1,000); actions and clicks per 1,000 views. No figure that adds commission to Paid to TL.

**Block**, one per creator, under the table:

| Line | Definition |
|---|---|
| TL videos included | Every live sold TL deal for this brand and creator, to today |
| Paid to TL | Sum of those prices, in the price currency |
| Commission since the first TL video | Approved, first TL go-live to today, converted (2.3) |
| Commission before the first TL video | Approved, from the start of Impact data to the day before the first go-live. Own line, labelled "outside TL bookings". Not added to any all-in figure |
| All-in cost | Paid to TL + commission since the first TL video |
| Views to date | Current TL views of those videos. Count each video once (same `article_id` or `media_url`); each deal's price still counts. Never channel total views |
| Sponsorship CPM / all-in CPM | Paid to TL ÷ views × 1,000 / all-in cost ÷ views × 1,000 |
| Approved actions since the first TL video | Impact, same dates as the commission |
| Sponsorship / all-in cost per action | Paid to TL ÷ actions / all-in cost ÷ actions |
| Return on sponsorship / all-in return | Sales revenue since the first TL video (converted) ÷ Paid to TL / ÷ all-in cost |

- Always to date, whatever window the table uses. Title it with both dates, e.g. "All-in cost to
  date, as of 30 Sep 2026, since the first TL video on 2 Jun".
- Per video only when that video has per-video evidence (4.1).
- Exclude pending commission and mention it beside the block. IF the route cannot separate
  approved from pending commission, say so.
- Put the note "Commission may include other sales." under the block.
- Never compute a CPM from Action Cost alone or call an Impact cost a CPM.

### 2.3 Currency

First record which currency the Impact figures are in: reports can show them already converted by
Impact. IF they are already in the TL `price_currency`, do not convert again, and say Impact
converted them. IF the Impact currency equals the TL `price_currency`: no conversion. ELSE:

- **Layer 1, always:** every money figure in its own currency, with the currency in the column
  name, e.g. "Paid to TL (USD)", "Sales revenue, Impact (EUR)". Money divided by a count or by
  views (sponsorship CPM, sponsorship cost per action) stays in Layer 1.
- **Layer 2, when money is compared with money** (everything in the all-in block): add a
  converted column beside the Layer 1 column, never in place of it.
  - Convert the Impact figure into the price currency. Never convert the TL price.
  - Rate: the ECB euro reference rate, averaged over the month of the Impact activity. Convert
    each month at its own rate, then sum. Convert other currencies through the euro.
  - Look the rate up; never use one from memory. IF no rate is found, stop at Layer 1 and say a
    rate is needed.
  - Show the rates used in the column name or a note.

## 3. Identity join

Stop at the first key that resolves. Record the key and a confidence.

| # | Impact field | TL field | Resolves | Strength | Notes |
|---|---|---|---|---|---|
| 1 | Partner tracking or vanity link | `tracking_url` | Deal | Strong | Exact match, ignoring `https://`, `www.` and a trailing slash |
| 2 | `Properties[].Url` (YouTube) | `thoughtleaders_channel.url`, `external_channel_id` | Channel | Strong | |
| 3 | Handle in `Properties[]` or `Website` | `thoughtleaders_channel.common_name` | Channel | Strong if exact | |
| 4 | `Action.PromoCode` | `cta_text` | Deal | Strong, rarely present | `UPPER(cta_text) = UPPER('<code>')`. `cta_text` can be a sentence containing the code, so also try `cta_text ILIKE '%<code>%'` and read the hit |
| 5 | `SharedId` (Action, Click), `PartnerRelated.SubId1-3` (Click), `PartnerValues.Value1-3` (Partner) | `adlink.id` or `thoughtleaders_channel.id` | Deal or channel | Strong if a TL id was put there | No standing convention; check a sample first |
| 6 | `MediaPartnerName` | `channel_name` | Channel | Weak | Often a legal name or an agency; needs a second signal |
| 7 | `MediaPartnerId` | none | | | TL stores no Impact partner id |

Look up keys 2, 3 and 6 as SKILL.md stage 3 describes. Never open or resolve a tracking link
(no browser visit, no redirect-following `curl`); a link on the brand's own short domain stays
unresolved.

### 3.1 Coverage count

```sql
SELECT COUNT(*) AS sold,
  COUNT(*) FILTER (WHERE COALESCE(al.tracking_url,'') <> '') AS has_tracking_url,
  COUNT(*) FILTER (WHERE COALESCE(al.cta_text,'') <> '')     AS has_promo_code,
  COUNT(*) FILTER (WHERE COALESCE(al.media_url,'') <> '')    AS has_video_url
FROM thoughtleaders_adlink al
JOIN thoughtleaders_profile_brands pb ON pb.profile_id = al.advertiser_profile_id
WHERE pb.brand_id = <brand_id> AND al.publish_status = 3
LIMIT 5
```

Promo codes are almost never filled and TL click columns are empty; tracking-link coverage varies
by brand. IF keys 1, 4 and 5 are thin, the main path is keys 2, 3 and 6 plus the go-live timeline.

## 4. Dates

Impact knows which creator drove a sale. It knows which video only if each video had its own
link, code or id.

### 4.1 Per-video evidence

Per-video evidence is a tracking link or promo code stored on only one TL deal (keys 1, 4), or a
SharedId or SubId holding the TL deal id (key 5). With it, attribute performance to that deal in
windows from its `publish_date` (default 0 to 30, 31 to 90, over 90 days).

### 4.2 Go-live timeline (no per-video evidence)

Never attribute performance to individual videos. Build one row per go-live date of this brand
and creator, each with Impact's numbers from that date to the day before the next go-live.

- Deals live on the same day share one row with all their deal ids; views are summed, with each
  video's views in brackets. Go-lives on different days are always separate rows, however close.
- IF a TL video went live before the window: the latest such deal is the first row, keeps its
  real date, is marked "went live before the window", and its period starts at the window start.
  ELSE the first row is "before the first TL video" (window start to the day before the first
  go-live).
- The last row runs to the window end. End with a creator total row.
- Sold deals with no `publish_date` are not live: list them under the table.
- Directly above the table, write: "All of this creator's videos use the same Impact link, so
  Impact cannot tell them apart. Each period shows what came in after that go-live and before
  the next one. Earlier videos were still live and may have driven part of it."
- Columns: Go-live date · TL deal(s) · TL views · Paid to TL · Sponsorship CPM · Impact period ·
  Clicks · Approved actions · Pending · Sales revenue, Impact · Affiliate commission, Impact.
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
  - Rebooking signal: the channel's current `projected_views` against each confirmed video's
    `projected_views` (frozen when TL first indexed it), as a percent change.
- Money compared across groups goes into one currency per 2.3, with the rate shown.

## 5. Account type

| | Brand account | Partner account (TL's or a creator's) |
|---|---|---|
| API base | `/Advertisers/{AccountSID}/` | `/Mediapartners/{AccountSID}/` |
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
