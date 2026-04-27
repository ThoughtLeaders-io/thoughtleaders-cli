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

