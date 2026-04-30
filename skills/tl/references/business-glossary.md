# ThoughtLeaders Business Glossary

Maps business terms to database concepts.

## Revenue & Deal Lifecycle

| Business Term | DB Concept | Notes |
|--------------|------------|-------|
| **Revenue / Sold ad** | `adlink.publish_status = 3` (SOLD) | Only status=3 counts as real revenue |
| **Gross ads / Gross revenue** | `SUM(adlink.price)` where sold | Total advertiser spend |
| **Net revenue / TL profit** | `price - cost` per adlink | What TL earns as a company |
| **Cost** | `adlink.cost` | What the channel earns |
| **Price** | `adlink.price` | What the advertiser pays |
| **Closed-lost** | `publish_status IN (4, 5, 9)` | All three rejection statuses |
| **Open opportunity** | `publish_status IN (0, 2, 6, 7, 8)` | Pipeline — not revenue, not lost |
| **Proposal Approved** | `publish_status = 6` | AM approved to show to brand — NOT brand approval. Internal gate only. |
| **Pending** | `publish_status = 2` | Brand has agreed — this is the real high-intent signal |
| **Weighted pipeline** | `SUM(weighted_price)` for open opps | Pre-calculated on save |
| **Ad is live** | `publish_date IS NOT NULL` | Until publish_date is set, ad is not on YouTube |
| **Cancellation risk** | Sold but `publish_date IS NULL` | Sold deals without publish_date can still be canceled |

## Performance Grade (`adlink.performance_grade`)

| Value | Label | Description |
|-------|-------|-------------|
| 0 | Pending | Not yet graded (treat as NULL) |
| 1 | Loser | Underperforming ad — do not renew |
| 2 | Neutral | Mixed results — test one more time, ideally at a better rate. Second test determines if channel becomes Loser or Winner |
| 3 | Winner | High-performing ad — should always be renewed |

**Renewal logic:** All Winners should be renewed. Neutrals get one more test (ideally at a lower CPM), then reclassified as Winner or Loser.

## View Guarantees

| Field | Description |
|-------|-------------|
| `adlink.impressions_guarantee` | The number of views guaranteed for the ad (bigint). 0 or NULL = no guarantee. |
| `adlink.view_guarantee_hit_date` | Timestamp when the guarantee was met. NULL = not yet hit or no guarantee. |
| `adlink.projected_views_at_purchase_date` | Projected views at time of purchase (used for CPM estimation). |

## Entities

| Business Term | DB Table | Notes |
|--------------|----------|-------|
| **Deal / Sponsorship** | `thoughtleaders_adlink` | One brand ↔ channel placement |
| **Brand** | `thoughtleaders_brand` | Advertiser entity (the buying-side brand) |
| **Brand profile** | `thoughtleaders_profile` | Advertiser entity / account |
| **Organization** | `thoughtleaders_organization` | Parent entity for profiles |
| **Channel** | `thoughtleaders_channel` | YouTube channel |
| **Ad Spot (Catalogue item)** | `thoughtleaders_adspot` | TL's catalogue of buyable placements. Price/cost on adspot are *list prices* only — each adlink (instance) can have completely different price/cost |
| **Campaign** | `dashboard_campaign` | Groups multiple deals |

## Ad Spots & Channels

- A channel can have **multiple ad spots** because different people sell the same channel (talent manager, direct, multiple agencies)
- Ad spots are the **catalogue** — adlinks are **instances** of catalogue items
- Price/cost on adspot = list/catalog values; price/cost on adlink = actual deal values
- **Only one active adspot with integration=mention per channel at any time** (MSN rule)

## Ownership & Accountability

| Field | Model | Meaning |
|-------|-------|---------|
| `owner_sales_id` | `adlink` | **Most important.** Person responsible for closing the deal and for the revenue. Final accountability. |
| `owner_advertiser_id` | `adlink` | Brand-side owner for this specific deal |
| `owner_publisher_id` | `adlink` | Channel-side owner for this specific deal |
| `owner_advertiser_id` | `profile` | **Account owner.** Who owns the brand relationship overall. Often same person as owner_sales on adlinks, but not always. |
| `owner_publisher_id` | `profile` | Channel relationship owner on the profile level |
| `owner_sales_id` | `profile` | Sales owner at profile level |

**Key insight:** Ownership exists on both `profile` (account-level) and `adlink` (deal-level). For revenue attribution, always use `adlink.owner_sales_id`.

## MSN (Media Selling Network)

- Channels where TL has **≥80% confidence** they can buy an ad tomorrow
- Key data: **who is the contact** to buy the ad from
- `thoughtleaders_channel.media_selling_network_join_date` = when channel joined MSN
- `thoughtleaders_channel.is_tl_channel` = TPP/VIP channel (subset of MSN)
- **Rule:** Only one active adspot with `integration=mention` per channel at any time
- MSN quality depends on having current, accurate contact info

## Channels & Audience

Vocabulary that AMs use about channels, mapped to the actual DB encoding. Most of these are silent-wrong-name traps where the team term doesn't match the column name.

| Business Term | DB Concept | Notes |
|---------------|------------|-------|
| **Subscribers** | `thoughtleaders_channel.reach` (bigint) | ⚠️ There is no `subscribers` column. The DB column is `reach`. |
| **MSN member** | `media_selling_network_join_date IS NOT NULL` | Whole MSN pool. NOT `is_tl_channel = true` — that's the VIP subset only. |
| **TPP / VIP channel** | `is_tl_channel = true` | The small VIP subset of MSN (~144 channels at 100k+ reach). Don't use as a general "MSN" proxy — silently drops ~98% of MSN. |
| **Active channel** | `is_active = true AND last_published >= CURRENT_DATE - INTERVAL '120 days'` | Standard filter for "channel is live and posting." Always include `is_active = true` in channel queries. |
| **Country / Geo of a deal** | `thoughtleaders_channel.country` (ISO 3166-1 alpha-2) | `thoughtleaders_adlink` has NO geo column. Geo for sponsorships almost always means the channel's country. |
| **Language of a channel** | `thoughtleaders_channel.language` (short ISO 639 code) | ⚠️ Short ISO 639 codes — NOT BCP-47. Mostly 2-letter ISO 639-1 (`en`, `pt`, `hi`) for major languages; occasionally 3-letter ISO 639-2/3 (`arc`, `arz`, `ase`, `ceb`) for languages without a 2-letter code. Filtering with BCP-47 (`en-US`/`pt-BR`) returns zero. Don't assume `LENGTH(language) = 2`. |
| **Brand on a deal** | `adlink → creator_profile_id → profile_brands.profile_id → profile_brands.brand_id → brand` | 3-table chain. There is NO direct `brand_id` on adlink. See [postgres-schema.md](postgres-schema.md). |
| **Channel on a deal** | `adlink.ad_spot_id → adspot.channel_id → channel` | NO direct `channel_id` on adlink. |
| **Brand-virgin / VPN-virgin (etc.)** | Channel has no `adlink` row joined to any of the target brand_ids | Used in candidate sourcing ("never sponsored by any VPN brand"). Caveat: only catches TL-brokered deals; channels that ran the brand directly (no TL involvement) appear "virgin" but aren't — cross-check ES `sponsored_brand_mentions` before final outreach. |
| **Channel quality score** *(internal-only)* | `sponsorship_score` on the indexed channel doc + `thoughtleaders_channel.sponsorship_score` (PG) | TL-internal composite score combining engagement, fulfillment, and historical sponsorship performance. **Use it internally to rank/tiebreak candidates, but do NOT quote the raw decimal in AM-facing or external output** — the score isn't documented to AMs and the absolute value isn't meaningful without context. In AM-facing prose, translate to qualitative language: "top-quartile fit," "strongest quality score in the candidate set," "high sponsorship-quality signal." |

## Projected Views (PV) — three related but distinct fields

AMs use "PV" loosely. There are three different DB fields, each meaning something different:

| AM Term | DB Field | What it actually is |
|---------|----------|---------------------|
| **PV (channel baseline)** | `thoughtleaders_channel.impression` | Channel-level "typical views per video" used as CPM denominator. ⚠️ Coverage and freshness vary; cross-check Firebolt longform median for hero-tier deals. |
| **PV (deal-specific)** | `thoughtleaders_adlink.projected_views_at_purchase_date` | Snapshot of projected views at the moment the deal was sold. Use this for historical CPM analysis. |
| **VG (View Guarantee)** | `thoughtleaders_adlink.impressions_guarantee` | The contractual minimum views the brand is guaranteed. 0/NULL = no guarantee. NOT the same as PV — VG is a contractual floor, PV is an estimate. |

When an AM says "what's the PV on this channel?" — they almost always mean `channel.impression`. When they say "what was the PV on this deal?" — they mean `adlink.projected_views_at_purchase_date`. When they say "did we hit the VG?" — they mean `adlink.view_guarantee_hit_date IS NOT NULL`.

## Channel Sponsorship Signals

Two derived metrics on the indexed channel doc that AMs use to qualify a channel before pitching. Both are pre-aggregated in the search index, computed against historical sponsored-content patterns.

| AM Term | Underlying field | Definition | What an AM does with it |
|---------|------------------|------------|--------------------------|
| **Fulfillment rate** | `fulfillment_rate` (channel doc, scaled_float) | The share of a channel's content that is sponsored — `sponsored / all` content over the measurement window, expressed as a fraction. Higher = the channel reliably delivers paid integrations. | Quality signal: a high fulfillment rate means past brands have actually run on this channel, not just been pitched. AMs use it to filter out "looks promising but never closes" channels. |
| **Renewal rate** | `renewal_rate` (channel doc, scaled_float) | The rate at which a brand-channel sponsorship relationship repeats over time, computed from clusters of sponsorship deals between a single subject (channel or brand) and its linked entities, with date-distribution heuristics (default 365-day max interval). | Loyalty signal: a high renewal rate means brands keep coming back to this channel. AMs use it to identify "sticky" channels worth premium positioning, and to flag low-renewal channels as one-shots. |

Both metrics live on the channel side of the indexed video docs (the `channel.*` nested object). Channel pages in TL's product surface these as quality scores; in AM-facing reports, you can quote them as percentages (`0.45 → "45% renewal rate"`).

## Industry Terms vs TL Vocabulary

Some MarTech-industry terms are **NOT used at TL.** When you encounter them in a question, prompt, or message — translate to TL-native vocabulary before querying or answering. If you see one of these on the left, swap to the right.

| Industry term (don't use) | TL-native equivalent | Notes |
|---------------------------|----------------------|-------|
| **Flight** (a single ad-run instance) | **deal** / **sponsorship** / **adlink** | One row in `thoughtleaders_adlink`. "Every flight" → "every deal." |
| **Flight** (a campaign time window) | **window** / **campaign window** | "60-day flight" → "60-day window." Or just specify dates. |
| **Flight cadence** | **deal cadence** / **renewal cadence** | How often deals run on a channel. |
| **Flight-over-flight** | **deal-over-deal** / **renewal-over-renewal** | Comparing successive deals on the same channel. |
| **Post-flight** | **post-publish** / **post-deal** | After the deal/ad has run. |

**General rule:** if you reach for an ad-industry term that isn't already in this glossary, check whether TL actually uses it before introducing it.

## Infrastructure Terms — Translate Before User-Facing Output

AMs and brand-facing readers don't know (or care) what Postgres, Elasticsearch, or Firebolt are. **When surfacing data in any AM-facing or external output, translate infrastructure names and column names to business language.** Internal engineering chats are the only place these raw terms belong.

| Internal term (don't use in AM/external output) | AM-friendly translation | What it actually is |
|---|---|---|
| **PG** / **Postgres** / `thoughtleaders_*` table names / `tl db pg` invocations | **"our deals data"** / **"TL's deals book"** / **"our pipeline"** | The relational DB that holds deals, brands, channels, profiles — the source of truth for what TL has brokered |
| **ES** / **Elasticsearch** / `tl-platform-*` indices / `tl db es` invocations | **"TL's YouTube content tracking"** / **"our video index"** / **"our scraped video data"** | The search index that holds tracked YouTube videos, brand mentions, transcripts — the wider market view |
| **Firebolt** / `article_metrics` / `channel_metrics` / `tl db fb` invocations | **"historical metrics"** / **"view-curve data"** | The data warehouse that stores time-series snapshots — used for trend analysis |
| `sponsored_brand_mentions` (ES field) | **"tracked sponsorships"** / **"logged sponsored mentions"** / **"sponsored videos we tracked"** | Per-video brand-ID tags showing which brands paid for that video |
| `organic_brand_mentions` (ES field) | **"organic / unpaid mentions"** | Brand mentioned in a video without a paid sponsorship |
| `publish_status = 3` | **"sold"** | Already in glossary; never write the integer to AMs |
| `creator_profile_id` chain / 3-table join | **"the brand's record"** | Engineering plumbing for brand lookup; AMs just hear "the brand" |
| `reach` (PG column) | **"subscribers"** | Already in glossary; AMs say subscribers, SQL says reach |
| `impression` (PG column) | **"projected views"** / **"PV"** | Already in glossary; flagged for reliability caveats |

### Common translations in context

When you'd write internally → write this for an AM:

| Internal phrasing | AM-friendly phrasing |
|---|---|
| "Pulling ES `sponsored_brand_mentions` for the market view" | "Cross-checking against our video tracking data" |
| "ES has 11,304 sponsored mentions of Robinhood" | "Robinhood ran 11,304 sponsored videos in the last 12 months" |
| "PG has 139 sold adlinks for brand_id=29332" | "We sold Investing.com 139 sponsorships" |
| "Firebolt `article_metrics` 180-day longform median" | "Recent typical-video views over the last 6 months" |
| "Filter on `publish_status=3` AND `purchase_date>=2025-01-01`" | "Sold deals since the start of 2025" |

**General rule:** if a sentence mentions `tl db pg|fb|es` invocations, table names, column names, or integer codes, ask yourself — *would the AM Slack me a question using this language?* If no, translate. The infrastructure exists to serve the AM; the AM shouldn't have to know it exists.

## Teams & Ownership

### Brand-led Revenue (Sales / Account Management)

These teams close deals and manage brand relationships. Revenue is attributed via `adlink.owner_sales_id`.

**Emma's team:**
| Person | auth_user.id | Owner field |
|--------|-------------|-------------|
| Emma | 11158 | `adlink.owner_sales_id` |
| Orli | 2042 | `adlink.owner_sales_id` |
| Eli | 20836 | `adlink.owner_sales_id` |
| Grace | 20835 | `adlink.owner_sales_id` |
| Mark | 23979 | `adlink.owner_sales_id` |
| Abbie | 23978 | `adlink.owner_sales_id` |
| Ariella | 23977 | `adlink.owner_sales_id` |

**Nicole's team:**
| Person | auth_user.id | Owner field |
|--------|-------------|-------------|
| Nicole | 9929 | `adlink.owner_sales_id` |
| Maika | 5412 | `adlink.owner_sales_id` |
| Yuval | 14252 | `adlink.owner_sales_id` |
| Revital | 14251 | `adlink.owner_sales_id` |

### Network Growth (SDR / Partnerships) — Pauline's team

Responsible for growing the MSN (new channels) and MBN (new brands). SDR outreach on both sides.

| Person | auth_user.id | Role | Owner field |
|--------|-------------|------|-------------|
| Pauline | 218 | Team lead | `adlink.owner_publisher_id` (channel handovers) |
| Morgan | 5710 | Channel SDR | — |
| Jen | 873 | Channel SDR | — |
| Ruby Jean | 9011 | Channel SDR | — |
| Molly | 11361 | Channel SDR | — |
| Pierra | 11323 | Brand SDR | — |
| Nian | 8795 | Brand SDR | — |

### Ad Ops — Jody's team

Manages getting sold ads published. `profile.owner_publisher_id` = ad ops manager of an account.

| Person | auth_user.id | Owner field |
|--------|-------------|-------------|
| Jody | 71 | `profile.owner_publisher_id` (account-level ad ops owner) |
| Kathleen | 9274 | `profile.owner_publisher_id` |
| Shane | 18159 | `profile.owner_publisher_id` |
| Kevin | 5799 | `profile.owner_publisher_id` |
| Airis | 5804 | `profile.owner_publisher_id` |
| Lara | 10743 | `profile.owner_publisher_id` |
| Josh | 11592 | `profile.owner_publisher_id` |

### Querying by team

```sql
-- Emma's team pipeline
SELECT ... FROM thoughtleaders_adlink al
WHERE al.owner_sales_id IN (11158, 2042, 20836, 20835, 23979, 23978, 23977)

-- Nicole's team pipeline
SELECT ... FROM thoughtleaders_adlink al
WHERE al.owner_sales_id IN (9929, 5412, 14252, 14251)

-- All brand-led revenue (both teams)
SELECT ... FROM thoughtleaders_adlink al
WHERE al.owner_sales_id IN (11158, 2042, 20836, 20835, 23979, 23978, 23977, 9929, 5412, 14252, 14251)

-- Pauline's network growth team (channel SDRs)
-- owner_publisher_id on adlink for channel-side work
SELECT ... FROM thoughtleaders_adlink al
WHERE al.owner_publisher_id IN (218, 5710, 873, 9011, 11361)

-- Jody's ad ops team accounts (profile-level ownership)
SELECT ... FROM thoughtleaders_profile p
WHERE p.owner_publisher_id IN (71, 9274, 18159, 5799, 5804, 10743, 11592)
```

