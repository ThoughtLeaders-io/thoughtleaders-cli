# Report Glossary

Reference for Phases 1 + 2. Disambiguation layer for the vocabulary the skill encounters: report-type synonyms, TL terminology, field-pair choices, deal-stage jargon, and common pitfalls. The schemas (`intelligence_filterset_schema.json` / `sponsorship_filterset_schema.json`) define what's *available*; this file defines what to *prefer* when terms overlap or aliases collide.

If a term or concept isn't here, default to the schema's `_tl_intent_hints` for the field, or surface as a clarifying question.

---

## Report-type synonyms

Users name reports inconsistently. This table is the canonical mapping the skill uses in Phase 1.

| Report type | Canonical name | Common synonyms / aliases | Notes |
|---|---|---|---|
| **1** | CONTENT | "uploads report", "videos report", "content report", "uploads", "video search", "individual videos", "per-video report" | Each row is one upload (video / podcast episode / article). |
| **2** | BRANDS | "brands report", "advertisers report", "sponsors report" *(when used loosely)*, "competitor research" | Each row is one brand, aggregated across mentions. |
| **3** | THOUGHTLEADERS / CHANNELS | "channels report", "creators report", "youtubers report", "publishers report", "channel discovery", "creator search", "TL report" *(loose)* | Each row is one channel. **Default when the user says "report" without qualification + the request is about creators.** |
| **8** | CAMPAIGN_MANAGEMENT / SPONSORSHIPS | "sponsorships report", "deals report", "adlinks report", "deal pipeline", "sales pipeline", "sponsorship management" | Each row is one sponsorship deal (AdLink). Internal users only. |

### Ambiguous / dangerous terms

These can mean different report types depending on context. Phase 1 must surface a clarifying question rather than guess.

| Term | Could mean | Clarifying question |
|---|---|---|
| **"campaign"** / **"campaign report"** | Type 8 (CAMPAIGN_MANAGEMENT — most common when context is deal-tracking) **OR** the generic Django sense (any report — `Campaign` is the umbrella model name) | "Do you want a sponsorship-deal report (each row = one deal), or a different report type?" |
| **"sponsors report"** | Type 2 (brands that sponsor) **OR** type 8 (the sponsorship deals themselves) | "Should the report list the brands (one row per brand) or the individual deals (one row per deal)?" |
| **"creator report"** *(singular)* | Type 3 about a single creator, **OR** the user wants type 1 uploads from a single creator | "Filter to one channel and show their videos (uploads report), or surface them inside a channels list?" |
| **"performance report"** | Type 8 with performance-grade focus, **OR** type 3 with engagement focus | "Are we looking at deal-level performance (won/lost) or channel-level performance (engagement, growth)?" |
| **"pipeline"** *(when no other context)* | Type 8 with active-stage filter | Default to type 8; confirm with the user. |
| **"book of business"** | Type 8 with `tl_sponsorships_only: true` (TL-managed deals only) | Default to type 8 + that filter; confirm scope. |

### TL-specific role / pool synonyms

| Term | Meaning | Where it shows up |
|---|---|---|
| **MSN** | Media Selling Network — broad ~11K opted-in channel pool | `msn_channels_only` |
| **TPP** | ThoughtLeaders Premier Partners — smaller ~169 high-touch managed pool | No first-class field; surface as user clarification |
| **MBN** | Media Buying Network — managed-services advertisers (brand side) | `cross_references` type `include_sponsored_by_mbn` |
| **AM** / **Account Manager** | The advertiser-side owner of a deal | `owner_advertiser_name` (in `filters_json` for type 8) |
| **TM** / **Talent Manager** / **Publisher Manager** | The publisher-side owner of a deal | `owner_publisher_name` (in `filters_json` for type 8) |

---

## TL terminology — use these

| Term | Meaning | Where it shows up |
|---|---|---|
| **Reach** | TL's rolling audience-size metric for a channel. Not raw YouTube subs. | `reach_from` / `reach_to` |
| **Projected Views (PV)** | Pricing estimate for a channel's next video. Drives sponsorship pricing. | `projected_views_from` / `projected_views_to`; column `Projected Views` |
| **View Guarantee (VG)** | Contractual floor on views for a sponsored deal. Always type-8 territory. | Type 8 columns: `Views Guaranteed`, `Views Guarantee Days` |
| **Net revenue** | TL's earned revenue on a deal. NOT "margin." | Type 8 columns: `Revenue` |
| **TL profit** | Profit signal `Price - Cost`. NOT "margin." | Custom formula `{Price} - {Cost}` |
| **Sold sponsorship** | Contractually agreed deal. Type 8 status filter via `filters_json.publish_status`. | — |
| **Match / Proposal / Deal** | Funnel stages — Match (possible) → Proposal (offered to both sides) → Deal (sold). | Encoded in `filters_json.publish_status` for type 8 |

## TL terminology — DON'T use

These are industry-default terms that **don't translate** to TL — never put them in field names, formulas, columns, or user-facing copy:

- ❌ **"flight"** (MarTech term for a campaign window) → say "campaign" or "date range"
- ❌ **"hero / hero-tier / hero channel"** → say "high-priority channel" or "TPP channel" if appropriate
- ❌ **"margin"** (accounting term) → say `Net revenue` or `TL profit` (`{Price} - {Cost}`)
- ❌ **"impressions"** in YouTube context → say `Views` or `Projected Views`

When the user uses one of these, mirror their language in the *clarifying question* but use TL terms in the emitted config.

---

## Deal-stage jargon (type 8)

When users describe deals informally, map to `filters_json.publish_status` IDs. The status enum values are integer IDs the platform recognizes.

| User says | `publish_status` ID(s) | Status name |
|---|---|---|
| "booked" / "sold" / "closed" / "won" | `3` | Sold |
| "proposed" / "approved by creator" | `0` | Creator Approved |
| "pending" | `2` | Pending |
| "rejected" *(any side)* | `4, 5, 9` | Rejected by Brand / Creator / Agency |
| "matched" | `7` | Matched |
| "reached out" / "outreach" | `8` | Reached Out |
| **"pipeline"** *(default scope)* | `0, 2, 6, 7, 8` | All active non-sold statuses |
| **"in progress"** / **"active"** | `0, 2, 3, 6` | Active deal statuses (incl. sold) |

Status reference (for completeness):

| ID | Name |
|---|---|
| 0 | Creator Approved (Proposed) |
| 1 | Unavailable |
| 2 | Pending |
| 3 | Sold |
| 4 | Rejected by Brand |
| 5 | Rejected by Creator |
| 6 | Proposal Approved |
| 7 | Matched |
| 8 | Reached Out |
| 9 | Rejected by Agency |

---

## Field-pair disambiguation

When two fields look similar, use this table to pick.

### Date scopes

| User intent | Fields to use | Why |
|---|---|---|
| "Last 90 days" / "this year" / rolling | `days_ago` (and optionally `days_ago_to`) | Rolling = relative to now; survives report re-runs sensibly. |
| "Between Jan 1 and Mar 31" / specific window | `start_date` + `end_date` | Absolute = fixed window; what the user explicitly anchored on. |
| "Channels created on TL since X" | `createdat_from` (+ `createdat_to`) | This is the TL-side AdLink/Channel record creation, not the YouTube publish date. |
| Sponsorship send/publish | `start_date` / `end_date` (type 8 reuses these for send_date) | Type 8's date semantics shift — the schema docstring explains. |

### Reach / size signals

| User intent | Fields to use | Why |
|---|---|---|
| "Big channels" / "mid-size or bigger" / size floor | `reach_from` (+ `reach_to`) | Reach is TL's preferred size metric — handles podcasts/newsletters too, not just subs. |
| "Channels expecting >X projected views per video" | `projected_views_from` (+ `projected_views_to`) | PV is a forward-looking estimate; better than Reach when intent is sponsor-deal pricing. |
| Raw YouTube views per video | `youtube_views_from` (+ `youtube_views_to`) | Per-upload metric — only meaningful for type 1 (CONTENT). |

### Demographic shares

| User intent | Fields to use | Why |
|---|---|---|
| "Mostly US audience" (single threshold) | `demographic_usa_share` | Single-value field — interpreted as "≥ this share." |
| "USA share between 40 and 80" (range) | `min_demographic_usa_share` + `max_demographic_usa_share` | Range variant — same field family with explicit bounds. |
| Same pattern for male / mobile / computer / TV / tablet / game-console | `min_*_share` + `max_*_share` | Always prefer the min/max pair when the user gives a range. |

### Keyword surfaces

| User intent | Fields to use | Why |
|---|---|---|
| Match keywords against video transcripts/titles | `content_fields` includes `content`, `title`, `transcript` | Standard for type 1 (CONTENT) discovery. |
| Match keywords against channel descriptions only | `content_fields = ["channel_description", "channel_description_ai", "channel_topic_description"]` | Standard for type 3 (CHANNELS) discovery — channel-level signal, not video-level. |
| Different keywords need different fields | `keyword_content_fields_map` (per-position override) | Use when one keyword is a brand name (match `channel.channel_name`) and another is a topic (match descriptions). |
| User says "but not X" | `keywords` includes `X` + `keyword_exclude_map["<index>"] = true` | Substring negation per-position. |
| User wants ALL keywords to match | `keyword_operator = "AND"` | Default is OR; set explicitly when intent calls for it. |

### Sponsorship status (type 8)

The platform filters deal stage through `filters_json.publish_status` — there is **no first-class status field** on FilterSet. Encode in `filters_json` only. See "Deal-stage jargon" above for the canonical NL → status-ID mapping.

---

## Defaults that must always be set (unless contradicted)

| Field | Default | Why |
|---|---|---|
| `languages` | `["en"]` | TL's working market is English-language YouTube. |
| `channel_formats` | `[4]` (Video) | TL's working format is YouTube Video. Other formats (Podcast=3, etc.) are marginal. |
| `days_ago` for type 8 | `365` | Type 8 without a date scope is unbounded and meaningless — will time out. |
| `sort` | Per-type default — see schema `_tl_default_by_report_type` | Reports MUST be sortable. |

If the user contradicts a default ("include Spanish channels too", "look at TikTok"), drop the default. Otherwise keep it.

---

## Filter-source decisions: typed field vs `filters_json`

Always prefer a typed field. `filters_json` is the catch-all and the platform interprets it directly — no validation, no type checks. Use `filters_json` ONLY when:

1. **No first-class field exists** for the user's intent (e.g., type-8 `publish_status`).
2. **A field exists but its semantics don't match** the user's specific request.

Don't put something in `filters_json` that already has a typed field — it confuses precedence and may silently override the typed value.

---

## Common pitfalls

- **Date upper bounds.** `start_date` / `end_date` in the model are `DateField`. The platform's underlying `DateTimeField` filtering uses `__lt next_day`, not `__lte` — so a user saying "through Feb 28" maps cleanly to `end_date = "2026-02-28"`. Don't try to be clever.
- **`is_offline`** is a 5-char string, not a boolean. Preserve the platform's encoding rather than converting.
- **`topics` is a real field.** Phase 2's topic_matcher can emit `topics: [<id>]` directly. Phase 2 may *also* expand the topic's curated `keywords[]` into the keyword fields — both are valid; pick one based on whether the user wants topic-bounded vs keyword-bounded precision.
- **Brand and channel names are NOT IDs.** Always run the `name_resolver` tool to convert `"PewDiePie"` → `<channel_id>` before emitting `channels: [...]` / `brands: [...]`. Type 8 with unresolved names is a hard failure.
- **`tl_sponsorships_only`** restricts to channels TL has sponsorship history with — not "channels currently in MSN." Different from `msn_channels_only`. Pick based on intent.
- **"Campaign" is a colliding term.** In Django, `Campaign` is the umbrella model for ALL reports. In TL business language, "campaign" often means a sponsorship campaign (type 8). Phase 1 must clarify when "campaign report" appears in the user's wording.
