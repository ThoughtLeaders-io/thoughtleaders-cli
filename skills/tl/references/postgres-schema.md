# ThoughtLeaders PostgreSQL Schema Reference

## How to query

```bash
tl db pg "SELECT id, weighted_price FROM thoughtleaders_adlink
          WHERE publish_status = 2
          LIMIT 50 OFFSET 0"
```

`tl schema pg` prints the live table/column listing visible to your user.

Accepted SQL:
- **SELECT only**, single statement. No DDL/DML/transactions/SET/COPY/MERGE.
- Functions accepted from an explicit list (aggregates, window, string, JSON, math, date-time, array). Catalog-resolving casts (`::regclass`, `::regprocedure`, …) are not accepted.
- `LIMIT` and `OFFSET` are optional. Omit them and the server fills in `LIMIT 50 OFFSET 0`. Explicit `LIMIT` must be an integer literal ≤ 500. Explicit `OFFSET` ≥ 10,000 is rejected with HTTP 403 (`OFFSET_TOO_DEEP`); paginate with the response's `next_offset`/breadcrumbs instead of jumping deep.
- SQL ≤ 50,000 chars; AST depth ≤ 64; node count ≤ 5,000.

## Core Tables

### `thoughtleaders_adlink` (Deals/Sponsorships)

The main deals table. Each row = one sponsorship deal between a brand and a YouTube channel. Also called "AdLink" in code, exposed as **sponsorship** in the CLI.

> 🚨 **Columns that DO NOT exist on `thoughtleaders_adlink` — common hallucinations:**
> - ❌ `brand_id` — there is NO direct brand FK. Brand is reached via `creator_profile_id → profile → profile_brands → brand`.
> - ❌ `organization_id` — there is NO direct org FK. Org is reached via `creator_profile_id → profile.organization_id → organization`.
> - ❌ `channel_id` — channel is reached via `ad_spot_id → adspot.channel_id → channel`.
> - ❌ `youtube_id` (on channel) — use `external_channel_id`.

#### Key Columns

| Column | Type | Description |
|--------|------|-------------|
| `id` | int | Primary key |
| `created_at` | timestamptz | When the deal was created |
| `updated_at` | timestamptz | Last modification |
| `publish_status` | int | Deal status (see constants below) |
| `price` | numeric | Deal price (USD) |
| `price_currency` | varchar | Always USD |
| `weighted_price` | numeric | `price * (status_weight/100)`, pre-calculated on save |
| `weighted_price_currency` | varchar | Always USD |
| `cost` | numeric | Cost to TL |
| `ad_spot_id` | int FK | → `thoughtleaders_adspot.id` |
| `creator_profile_id` | int FK | → `thoughtleaders_profile.id` (the brand/advertiser's profile). ⚠️ The table is named `thoughtleaders_profile`, NOT `creator_profile` — the "creator_" prefix lives on the FK column, not the table. |
| `owner_advertiser_id` | int FK | → `auth_user.id` (brand-side owner) |
| `owner_publisher_id` | int FK | → `auth_user.id` (channel-side owner) |
| `owner_sales_id` | int FK | → `auth_user.id` (sales rep) |
| `send_date` | timestamptz | Scheduled send/publish date |
| `publish_date` | timestamptz | Actual publish date |
| `outreach_date` | timestamptz | When outreach was sent |
| `purchase_date` | timestamptz | When deal was purchased/sold |
| `presented_date` | timestamptz | When presented to brand |
| `rejected_date` | timestamptz | When rejected |
| `proposal_approved_date` | timestamptz | When proposal was approved |
| `draft_expected_date` | date | Expected draft delivery |
| `actual_end_date` | timestamptz | Actual end date |
| `scheduled_end_date` | timestamptz | Scheduled end date |
| `rejection_reason` | int | Rejection reason code |
| `rejection_reason_details` | text | Free-text rejection details |
| `payment_status` | int | 0=Unpaid, 1=Paid |
| `performance_grade` | int | Performance rating (see business-glossary) |
| `article_id` | varchar | Compound `<channel_id>:<youtube_id>` — links to ES `_id` and ES `id` field |
| `dashboard_campaign_id` | int FK | Campaign grouping |
| `created_where` | varchar | Where the deal originated |
| `tx_data` | jsonb | Transaction metadata |

#### `publish_status` Constants

| Value | Constant | Label | Pipeline Weight |
|-------|----------|-------|----------------|
| 0 | PREVIEW | Proposed | 10% |
| 1 | UNAVAILABLE | Unavailable | — |
| 2 | PENDING | Pending | 70% |
| 3 | SOLD | Sold | — |
| 4 | DENY | Rejected by Advertiser | 0% |
| 5 | REJECT | Rejected by Publisher | 0% |
| 6 | PROPOSAL_APPROVED | Proposal Approved | 25% |
| 7 | MATCHED | Matched (default) | 1% |
| 8 | OUTREACH | Reached Out | 5% |
| 9 | REJECTED_AGENCY | Rejected by Agency | 0% |
| -1 | CLIENT_SIDE_AVAILABLE | Client Side Available | — |
| -2 | CLIENT_SIDE_TAKEN | Client Side Taken | — |

#### Pipeline Stages

- **Active pipeline** = statuses with weight > 0: 0, 2, 6, 7, 8.
- **Won** = 3 (Sold).
- **Lost** = 4, 5, 9.

### `thoughtleaders_brand`

| Column | Type | Description |
|--------|------|-------------|
| `id` | int | Primary key |
| `name` | varchar | Brand name |
| `description` | text | Brand description |
| `creator_id` | int FK | User who created it |

#### Junction Tables

| Table | Columns | Purpose |
|-------|---------|---------|
| `thoughtleaders_profile_brands` | `profile_id`, `brand_id` | Profile↔Brand M2M (Django field `profile.brands`). In practice each profile has one brand attached. |
| `thoughtleaders_brand_brands` | `from_brand_id`, `to_brand_id` | Self-referential: related brands. |

### `thoughtleaders_adspot` (Ad Catalogue)

Buyable ad placements. Each adspot links a channel to a seller. Price/cost here are **list prices** — actual deal values live on the adlink.

A channel can have multiple adspots (different sellers: talent manager, direct, multiple agencies).

| Column | Type | Description |
|--------|------|-------------|
| `id` | int | Primary key |
| `channel_id` | int FK | → `thoughtleaders_channel.id` |
| `price` | numeric | List/catalogue price |
| `cost` | numeric | List/catalogue cost |
| `integration` | int | 1=YouTube Mentions (live reads). Only one active mention-type adspot per channel. |
| `is_active` | boolean | Active flag |
| `publisher_id` | int FK | → `auth_user.id` (NOT `thoughtleaders_profile.id` — see gotcha below) |

### `thoughtleaders_channel` (YouTube Channels)

| Column | Type | Description |
|--------|------|-------------|
| `id` | int | Primary key |
| `channel_name` | varchar | Display name. ⚠️ The column is `channel_name`, NOT `name`. |
| `external_channel_id` | varchar | YouTube channel ID (e.g., `UCxxxxxx`). ⚠️ There is NO `youtube_id` column — use this one. |
| `url` | varchar | Channel URL |
| `reach` | bigint | Subscriber count. ⚠️ There is NO `subscribers` column — `reach` is the subscriber count. Many internal docs and outputs use the word "subscribers"; in SQL, always query `reach`. |
| `media_selling_network_join_date` | date/timestamptz | When channel joined MSN. **MSN membership = this column IS NOT NULL.** |
| `is_tl_channel` | boolean | True = TPP/VIP channel (the small VIP subset, ~144 channels at 100k+ reach). ⚠️ **`is_tl_channel` is NOT the MSN flag.** Naive `WHERE is_tl_channel = true` as an "MSN filter" silently drops ~98% of the MSN pool (8,652 → 144 at 100k+). For MSN, use `media_selling_network_join_date IS NOT NULL`. |
| `content_category` | int | Content category code (1–22). See "`content_category` Constants" below for the code → label mapping. ⚠️ **Data-quality notes:** (1) per-row category assignments are often inconsistent with the official label (e.g. cat 15 = Technology, but many top-`reach` channels in cat 15 are clearly Entertainment). (2) Several codes are essentially unused in practice — codes 1, 2, 4, 6, 7, 8, 9, 11, 13 (Backend Development, Design, Frontend Development, Marketing, Mobile Development, Sales, Travel, Photography, Personal Finance) return ~0 active high-reach channels. Most travel creators land under Lifestyle (5), not Travel (9). The label table below is authoritative; the per-row assignment is best-effort. **For topic/category discovery, prefer `tl recommender top-channels "<tag>"` (ranked) over `WHERE content_category = <code>` (equality). |
| `is_active` | boolean | Whether the channel is active. ⚠️ **Always include `is_active = true` in channel queries** unless explicitly looking for archived rows. |
| `country` | varchar | Channel's primary country (ISO 3166-1 alpha-2 code, e.g. `US`, `GB`, `BR`). Often the cleanest answer to "geo" questions on sponsorships (since adlink itself has no geo). May be NULL or blank on ~10% of channels. |
| `language` | varchar | Primary content language. ⚠️ **Short ISO 639 codes — NOT BCP-47.** Mostly 2-letter ISO 639-1 (`en`, `pt`, `hi`) for major languages; occasionally 3-letter ISO 639-2/3 (`arc`, `arz`, `ase`, `ceb`) for languages without a 2-letter code. Filtering with `language = 'en-US'` returns zero rows. **Don't assume `LENGTH(language) = 2`** — that silently drops the 3-letter long-tail. May be NULL on ~10% of channels. |
| `last_published` | date | Date of the channel's most recent video. Use for "is the channel still active?" filters — e.g. `last_published >= CURRENT_DATE - INTERVAL '120 days'`. |
| `sponsorship_score` | double precision | TL-internal channel quality score (higher is better). Useful as a tiebreaker when ranking candidate channels. |
| `description` | text | LLM-generated description of the channel. Sometimes useful as a regex-target for thematic filtering when the integer category is too coarse (e.g. filtering "Technology" cat 15 down to actual tech reviewers via keywords like `tech|gadget|review|software`). |
| `evergreenness` | float | Cached evergreen score |

#### `content_category` Constants

Source of truth: `thoughtleaders.taxonomies.ContentCategory` (Django `IntEnum` in the main `thoughtleaders` repo).

| Value | Constant | Pretty Label |
|-------|----------|--------------|
| 1 | BACKEND_DEVELOPMENT | Backend Development |
| 2 | DESIGN | Design |
| 3 | ENTREPRENEURSHIP | Entrepreneurship |
| 4 | FRONTEND_DEVELOPMENT | Frontend Development |
| 5 | LIFESTYLE | Lifestyle |
| 6 | MARKETING | Marketing |
| 7 | MOBILE_DEVELOPMENT | Mobile Development |
| 8 | SALES | Sales |
| 9 | TRAVEL | Travel |
| 10 | BUSINESS | Business |
| 11 | PHOTOGRAPHY | Photography |
| 12 | GENERAL_KNOWLEDGE | General Knowledge |
| 13 | PERSONAL_FINANCE | Personal Finance |
| 14 | NEWS_POLITICS | News & Politics |
| 15 | TECHNOLOGY | Technology |
| 16 | GAMING | Gaming |
| 17 | FOOD | Food |
| 18 | SPORTS | Sports |
| 19 | HOWTO | How To & Crafts |
| 20 | ENTERTAINMENT | Entertainment |
| 21 | HEALTH_FITNESS | Health & Fitness |
| 22 | MUSIC | Music |

### `auth_user` (Django Users)

Standard Django user table. Used for owner lookups.

| Column | Type | Description |
|--------|------|-------------|
| `id` | int | Primary key |
| `first_name` | varchar | First name |
| `last_name` | varchar | Last name |
| `email` | varchar | Email |

## Top Tables by Row Count

| Rows | Table | Purpose |
|------|-------|---------|
| 1.3M | `thoughtleaders_channel` | YouTube channels |
| 1.2M | `thoughtleaders_historicaladlink` | Audit trail for adlink changes |
| 150K | `thoughtleaders_adlink` | Deals/sponsorships |
| 43K | `thoughtleaders_adspot` | Ad placements |
| 20K | `auth_user` | Users (team + external) |
| 20K | `thoughtleaders_profile` | User profiles |
| 19K | `thoughtleaders_organization` | Organizations |
| 19K | `dashboard_campaign` | Campaign groupings |
| 13K | `thoughtleaders_dailymetric` | Daily performance metrics |
| 12K | `thoughtleaders_leads` | Sales leads |

## Key Relationships

```
thoughtleaders_adlink
  ├── ad_spot_id → thoughtleaders_adspot.id
  │                  └── channel_id → thoughtleaders_channel.id
  ├── owner_advertiser_id → auth_user.id
  ├── owner_publisher_id → auth_user.id
  ├── owner_sales_id → auth_user.id
  └── creator_profile_id → thoughtleaders_profile.id
                              ├── organization_id → thoughtleaders_organization.id
                              └── profile_brands.profile_id → brand.id

⚠️ thoughtleaders_adlink has NO direct brand_id, organization_id, or channel_id column.
⚠️ thoughtleaders_brand has NO organization_id column — org lives on profile.
```

### Common Join Paths

**Adlink → Channel name:**
```sql
JOIN thoughtleaders_adspot s ON a.ad_spot_id = s.id
JOIN thoughtleaders_channel ch ON s.channel_id = ch.id
```

**Adlink → Brand name:**
```sql
JOIN thoughtleaders_profile p ON a.creator_profile_id = p.id
JOIN thoughtleaders_profile_brands pb ON p.id = pb.profile_id
JOIN thoughtleaders_brand b ON pb.brand_id = b.id
-- NEVER: JOIN brand b ON b.id = a.creator_profile_id (different ID spaces, returns wrong data)
```

**Adlink → Organization:**
```sql
JOIN thoughtleaders_profile p ON a.creator_profile_id = p.id
JOIN thoughtleaders_organization o ON p.organization_id = o.id
```

🚨 **`adspot.publisher_id` is a FK to `auth_user`, not `profile`.** To get the publisher's profile, join through user:
```sql
JOIN auth_user au ON au.id = adspot.publisher_id
JOIN thoughtleaders_profile p ON p.user_id = adspot.publisher_id
```
Joining `adspot.publisher_id → profile.id` directly mixes ID spaces and returns garbage.

## `thoughtleaders_profile` persona constants

| Value | Label |
|-------|-------|
| 1 | Direct Brand |
| 2 | Creator |
| 3 | Talent Manager |
| 4 | Media Agency |
| 5 | Creator Service |

## `thoughtleaders_profile_channels` (Profile ↔ Channel M2M)

| Column | Type |
|--------|------|
| `id` | int PK |
| `profile_id` | int FK |
| `channel_id` | int FK |

Note: separate from the adspot publisher relationship. Not always in sync.

## Example queries

**Total weighted pipeline by sales rep:**
```sql
SELECT owner_sales_id, SUM(weighted_price) AS pipeline
FROM thoughtleaders_adlink
WHERE publish_status IN (0, 2, 6, 7, 8)
GROUP BY owner_sales_id
ORDER BY pipeline DESC
LIMIT 100 OFFSET 0
```

**Sold deals this month:**
```sql
SELECT id, price, purchase_date, ad_spot_id, creator_profile_id
FROM thoughtleaders_adlink
WHERE publish_status = 3
  AND purchase_date >= date_trunc('month', CURRENT_DATE)
ORDER BY purchase_date DESC
LIMIT 500 OFFSET 0
```

**MSN channel joins this month:**
```sql
SELECT id, channel_name, media_selling_network_join_date
FROM thoughtleaders_channel
WHERE media_selling_network_join_date >= date_trunc('month', CURRENT_DATE)
ORDER BY media_selling_network_join_date DESC
LIMIT 500 OFFSET 0
```

**Deal with brand and channel name:**
```sql
SELECT a.id, a.price, a.publish_status, b.name AS brand, ch.channel_name
FROM thoughtleaders_adlink a
JOIN thoughtleaders_adspot s ON a.ad_spot_id = s.id
JOIN thoughtleaders_channel ch ON s.channel_id = ch.id
JOIN thoughtleaders_profile p ON a.creator_profile_id = p.id
JOIN thoughtleaders_profile_brands pb ON p.id = pb.profile_id
JOIN thoughtleaders_brand b ON pb.brand_id = b.id
WHERE a.id = 12345
LIMIT 1 OFFSET 0
```
