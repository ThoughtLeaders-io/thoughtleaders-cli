# Report Glossary

Disambiguation reference: report-type synonyms, TL terminology, field-pair choices, deal-stage jargon, common pitfalls. The schemas (`*_filterset_schema.json`) define what's available; this file defines what to prefer when terms overlap. If a term isn't here, default to the schema's `_tl_intent_hints` or ask the user.

## Report-type synonyms

| Type | Canonical | Common synonyms / aliases | Notes |
|---|---|---|---|
| **1** | CONTENT | "uploads", "videos", "content", "video search", "individual videos", "per-video" | Each row is one upload (video / podcast / article). |
| **2** | BRANDS | "brands", "advertisers", "sponsors" *(loose)*, "competitor research" | Each row is one brand, aggregated across mentions. |
| **3** | THOUGHTLEADERS / CHANNELS | "channels", "creators", "youtubers", "publishers", "channel discovery", "TL report" *(loose)* | Each row is one channel. **Default when "report" + creators context.** |
| **8** | CAMPAIGN_MANAGEMENT / SPONSORSHIPS | "sponsorships", "deals", "adlinks", "deal pipeline", "sales pipeline" | Each row is one sponsorship deal. Internal users only. |

### Ambiguous terms — ask, don't guess

| Term | Could mean | Clarifying question |
|---|---|---|
| **"campaign"** / **"campaign report"** | Type 8 (most common in deal-tracking) **OR** generic Django sense (any report) | "Do you want a sponsorship-deal report (one row per deal), or a different report type?" |
| **"sponsors report"** | Type 2 (brands) **OR** type 8 (deals) | "List the brands (one row per brand) or the deals (one row per deal)?" |
| **"creator report"** *(singular)* | Type 3 of one creator **OR** type 1 uploads from one creator | "Filter to one channel and show their videos, or surface them inside a channels list?" |
| **"performance report"** | Type 8 (deal performance) **OR** type 3 (channel engagement) | "Deal-level performance (won/lost) or channel-level (engagement, growth)?" |
| **"pipeline"** *(no other context)* | Type 8 with active-stage filter | Default to type 8; confirm. |
| **"book of business"** | Type 8 with `tl_sponsorships_only: true` | Default to type 8 + filter; confirm scope. |

### TL role / pool synonyms + TL terminology

> **Canonical source**: [`tl/references/business-glossary.md`](../../tl/references/business-glossary.md) — the canonical home for TL business terminology (MSN, TPP, MBN, AM/TM ownership, View Guarantees, Net revenue, TL profit, performance grade, industry-vs-TL vocabulary translations). Do NOT redefine these terms here; this skill defers to the glossary.

Quick **FilterSet-mapping reference** (where these business terms land in a saved report config — for full definitions see the canonical glossary):

| Term | FilterSet / `filters_json` mapping in this skill |
|---|---|
| **MSN** | `msn_channels_only: true` |
| **TPP** | resolve-and-pin pattern — `SELECT id FROM thoughtleaders_channel WHERE is_tpp = TRUE AND is_active = TRUE ORDER BY id` → put IDs in `filterset.channels` |
| **MBN** | `cross_references` type `include_sponsored_by_mbn` |
| **AM** / Account Manager | `owner_advertiser_name` (in `filters_json` for type 8) |
| **TM** / Talent Manager | `owner_publisher_name` (in `filters_json` for type 8) |
| **Reach** | `subscribers_from` / `subscribers_to` (narrate as "subscribers" per business-glossary) |
| **Projected Views (PV)** | `projected_views_from` / `projected_views_to`; column `Projected Views` |
| **View Guarantee (VG)** | Type 8 columns: `Views Guaranteed`, `Views Guarantee Days` |
| **Net revenue** | Type 8 column: `Revenue` |
| **TL profit** | Custom formula `{Price} - {Cost}` (NOT "margin" — see glossary) |
| **Sold sponsorship / Match / Proposal / Deal** | `filters_json.publish_status` (see "Deal-stage jargon" below for ID mapping) |

### Industry terms — DON'T emit in config

Industry-default terms that don't translate; never put in field names, formulas, columns, or user-facing copy:

- ❌ **"flight"** (MarTech) → say "campaign" or "date range" (full flight-variant translation lives in [`business-glossary.md`](../../tl/references/business-glossary.md) "Industry Terms vs TL Vocabulary")
- ❌ **"hero / hero-tier / hero channel"** → say "high-priority" or "TPP" if appropriate
- ❌ **"margin"** (accounting) → say `Net revenue` or `TL profit`
- ❌ **"impressions"** in YouTube context → say `Views` or `Projected Views`

Mirror the user's language in the *clarifying question*; emit TL terms in the config.

## Deal-stage jargon (type 8)

Map informal descriptions → `filters_json.publish_status` IDs (integer; platform doesn't accept string labels):

| User says | `publish_status` ID(s) | Other `filters_json` | Status name |
|---|---|---|---|
| "booked" / "sold" / "closed" / "won" | `3` | — | Sold |
| "open" / "in negotiation" | `10` | — | Open |
| "rejected" *(any side)* | `4, 5, 9` | — | Rejected by Brand / Creator / Agency |
| "matched" | `7` | — | Matched |
| **"pipeline"** *(default)* | `7, 10` | — | Matched + Open (pre-sale) |
| **"in progress"** / **"active"** | `3, 7, 10` | — | Active incl. sold |
| **"live"** / **"currently running"** | `3` | `ad_publish_status: "0"` | Sold AND published |

### Open and per-party approvals

A deal at **Open** (`publish_status` `10`) is an active, in-negotiation deal. Its progress is tracked by three independent per-party approval fields, each `PENDING`, `APPROVED`, `FINISHED`, or unset (`null`):

- `brand_approval` — the advertiser's sign-off
- `channel_approval` — the creator's sign-off
- `agency_approval` — the agency's sign-off (when an agency is involved)

These are **first-class FilterSet properties** — set directly on the report, not as keys inside `filters_json`. Each takes a comma list of `PENDING`/`APPROVED`/`FINISHED` (or ints `1`/`2`/`3`), plus `0`/`null`/`none` to match unset. They narrow the Open rows only and have no effect unless `publish_status` includes `10`.

The `committed` flag is a `filters_json` key (like `publish_status`): `filters_json.committed: "1"` selects Sold deals together with Open deals the brand has approved.

Users often name a deal by where it sits inside Open. Map those phrases to `publish_status` `10` plus the matching approval state:

| User says | `publish_status` | Approval filter (first-class) | Meaning |
|---|---|---|---|
| "reached out" / "outreach" | `10` | `channel_approval = PENDING` | Creator contacted, awaiting their reply |
| "proposed" / "creator approved" | `10` | `channel_approval = APPROVED` | Creator has agreed |
| "proposal approved" | `10` | `brand_approval = PENDING` | Brand is reviewing |
| "pending" | `10` | `brand_approval = APPROVED` | Brand has committed |

The `publish_status` set is `{3, 4, 5, 7, 9, 10}` (3 Sold, 4 Rejected by Brand, 5 Rejected by Creator, 7 Matched, 9 Rejected by Agency, 10 Open). The canonical schema home is [`tl/references/postgres-schema.md` → `publish_status` Constants](../../tl/references/postgres-schema.md#publish_status-constants); refer to it for the full enum.

## Field-pair disambiguation

### Date scopes

| User intent | Fields | Why |
|---|---|---|
| "Last 90 days" / rolling | `days_ago` (+ optionally `days_ago_to`) | Rolling = relative to now |
| "Between Jan 1 and Mar 31" | `start_date` + `end_date` | Absolute window |
| "Channels created on TL since X" | `createdat_from` (+ `createdat_to`) | TL-side record creation, not YouTube publish |
| Sponsorship send/publish | `start_date` / `end_date` (type 8 reuses for scheduled_date) | Type 8 semantics shift — see schema |

### Channel-size signals

> SQL/internal term = `subscribers`; user-facing term = **subscribers** (see business-glossary canonical mapping). Emit `subscribers_from` / `subscribers_to` in FilterSet; narrate as "subscribers" everywhere user-facing (sample headers, takeaways, summaries).

| User intent | Field | Narrate as |
|---|---|---|
| "100K+ subscribers" / size floor | `subscribers_from` (+ `subscribers_to`) | "subscribers" / "channel size" |
| "Channels expecting >X projected views" | `projected_views_from` (+ `projected_views_to`) | "projected views" — forward-looking pricing estimate |
| Raw YouTube views per video | `youtube_views_from` (+ `youtube_views_to`) | "views per video" — per-upload, type 1 only |

### Demographic shares

| User intent | Fields | Why |
|---|---|---|
| "Mostly US audience" (single threshold) | `demographic_usa_share` | Interpreted as ≥ this share |
| "USA share between 40 and 80" (range) | `min_demographic_usa_share` + `max_demographic_usa_share` | Range variant |
| Same pattern for male / mobile / computer / TV / tablet / game-console | `min_*_share` + `max_*_share` | Prefer min/max pair on ranges |

### Keyword surfaces

| User intent | Fields | Why |
|---|---|---|
| Match keywords in video transcripts/titles | `content_fields` includes `title`, `transcript` (add `summary` for the video's description text; `content` is podcast-only) | Standard type 1 |
| Match channel descriptions only | `content_fields = ["channel_description", "channel_description_ai", "channel_topic_description"]` | Standard type 3 |
| Different keywords need different fields | `keyword_content_fields_map` (per-position) | E.g., brand name → `channel.channel_name`; topic → descriptions |
| "But not X" | `keywords` includes `X` + `keyword_exclude_map["<index>"] = true` | Substring negation per-position |
| User wants ALL keywords to match | `keyword_operator = "AND"` | Default is OR |

### Sponsorship status (type 8)

No first-class status field — encode in `filters_json.publish_status` only. See "Deal-stage jargon" for the NL → ID mapping.

## Defaults (unless contradicted)

| Field | Default | Why |
|---|---|---|
| `languages` | `["en"]` | TL's working market |
| `channel_formats` | `[4]` (Video) | TL's working format |
| `days_ago` for type 8 | `365` | Type 8 without date scope is unbounded |
| `sort` | Per-type default — see `_tl_default_by_report_type` | Reports must be sortable |

Drop a default only if the user contradicts it ("include Spanish too", "look at TikTok").

## Filter-source decisions: typed field vs `filters_json`

Always prefer typed fields. `filters_json` is the catch-all (no validation, no type checks). Use ONLY when:

1. No first-class field exists (e.g., type-8 `publish_status`)
2. A field exists but its semantics don't match the request

Never put something in `filters_json` that has a typed field — confuses precedence, may silently override.

## Common pitfalls

- **Date upper bounds** — `start_date`/`end_date` are `DateField`; platform uses `__lt next_day`, not `__lte`. "Through Feb 28" → `end_date = "2026-02-28"`. Don't be clever.
- **`is_offline`** — 5-char string, not boolean. Preserve platform encoding.
- **`topics` is a real field** — emit `topics: [<id>]` directly when the user named a curated topic, OR expand to `keywords[]` when their intent is broader. Both valid; pick by intent (topic-bounded vs keyword-bounded precision).
- **Brand/channel names ≠ IDs** — always resolve names → IDs via `tl brands find <name>` / `tl channels find <name>` before emitting `channels: [...]` / `brands: [...]`. Type 8 with unresolved names is a hard failure (saved report will return zero rows).
- **`tl_sponsorships_only`** ≠ `msn_channels_only`. First restricts to channels with TL sponsorship history; second to MSN-network channels. Pick by intent.
- **"Campaign" is colliding** — Django umbrella model vs TL business sense (type 8). Confirm with the user when they say "campaign report" — they probably mean type 8 (deals), but the platform also uses "Campaign" as the umbrella model for *every* saved report.
- **Free-text niches → keywords only, NEVER `content_categories` as pre-filter.** Niches like "motorcycle vlogging" scatter across LIFESTYLE / SPORTS / HOWTO / ENTERTAINMENT. Using `content_categories` as a pre-filter excludes channels that fit the niche but are tagged in a sibling bucket. Only use `content_categories` when the user explicitly names a TL category label (e.g., "Lifestyle channels"). Otherwise match via `keyword_groups` against `content_fields`.
