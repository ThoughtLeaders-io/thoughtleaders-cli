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
| `creator_profile_id` | int FK | → brand/advertiser profile |
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
| `channel_name` | varchar | Display name |
| `external_channel_id` | varchar | YouTube channel ID (`UCxxxxxx`). ⚠️ There is NO `youtube_id` column. |
| `url` | varchar | Channel URL |
| `media_selling_network_join_date` | date/timestamptz | When channel joined MSN |
| `is_tl_channel` | boolean | True = TPP/VIP channel |
| `evergreenness` | float | Cached evergreen score |

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
