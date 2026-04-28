---
name: tl
description: Query and analyze ThoughtLeaders business data using the `tl` CLI — structured resource commands (sponsorships, deals, channels, brands, uploads, snapshots, reports) plus raw PostgreSQL / Elasticsearch / Firebolt access via `tl db pg|fb|es`. Triggers on questions about deals, sponsorships, pipeline, revenue, brands, channels, MSN, TPP, uploads/videos, transcripts, brand mentions, view-curves, sales numbers, reports, or any cross-source business analysis ("how many deals", "pipeline report", "weighted pipeline", "channel data", "brand lookup", "view curve", "find mentions of", "investigate this video", "query the database"). Use structured tl commands — you ARE the AI layer, not tl ask.
---

# ThoughtLeaders Data Analyst

You have access to the `tl` CLI which queries ThoughtLeaders' sponsorship platform data. Run it to answer questions about deals, channels, brands, uploads, metrics, and more.

## Core Principles

**You are the intelligence layer.** Use structured `tl` commands, not `tl ask`. The `tl ask` command is a server-side LLM fallback for users without Claude — but the user has you. Translate their questions into the right `tl` commands.

Always run `tl describe show <resource>` before running a query against that resource. For raw-db queries, use `tl schema pg|fb|es` to get the database schemas.

Always assume there will be more than 1 page of results. You MUST always use `--limit` and `--offset` options in the `tl list` commands to retrieve the entire data set (all pages, until the total records are fetched). You must also always use pagination in scripts you write to collect results. The maximum number of results per page is 500.

Retry after 5 seconds if the server returns a "connection denied" or a "server error" on any request.

Where possible reference sponsorships, brands, channel by numeric IDs.

## Data Model & Terminology

ThoughtLeaders is a sponsorship marketplace connecting **Brands** (advertisers / media buyers) with **Channels** (YouTube creators, podcasters / media sellers).

The centre of the data model is **Sponsorships** — business relationships between brands and channels. Sponsorships have a funnel of types, from broad to narrow:

- **Sponsorships** — the broadest category, encompassing all stages
  - **Matches** — possible brand-channel pairings that ThoughtLeaders thinks could work
  - **Proposals** — matches that have been proposed to both sides to consider
  - **Deals** — contractually agreed-upon sponsorships (sold), either in production or published

Sponsorships are sometimes called "Ads" or "Ad campaigns".

The CLI has shortcut commands for each type: `tl matches`, `tl proposals`, `tl deals`. These filter `tl sponsorships` by status.

Other key concepts:
- **Uploads** — YouTube videos indexed from Elasticsearch
- **Snapshots** — historical time-series metrics for channels and videos (Firebolt)
- **Reports** — saved report configurations that can be re-run
- **Comments** — notes attached to sponsorships
- **Adspots** — types of ads a channel carries (e.g. mention, dedicated video, product placement). Returned by `tl channels show`; each carries price/cost.
- **MSN** (Media Selling Network) — the ~11k YouTube channels that have opted in to receive sponsorship offers. Returned as a boolean `msn` field on every channel response (list, detail, similar). Derived server-side from whether `Channel.media_selling_network_join_date` is non-null — the timestamp itself isn't exposed over the CLI, just the boolean. Filterable via `msn:` tri-state: `msn:yes` (MSN only — the default on `similar`; on `list` the default is `both`), `msn:no` (non-MSN only), `msn:both` (no filter).
- **TPP** (ThoughtLeaders Partner Program, a.k.a. "TL channels") — the smaller, exclusive ~169 channels TL manages directly. Returned as the `tpp` boolean field on every channel response (list, detail, similar). Filterable via `tpp:` with the same tri-state vocabulary: `tpp:yes` / `tpp:no` / `tpp:both` (default `both`).
- **`demographics_updated_at`** (on channel detail) — ISO timestamp of when demographic screenshots were last uploaded and processed via OCR. If non-null, the channel has demographics screenshots on file. If null, no screenshots have been uploaded. Use this to check whether a channel has demographics data from screenshots.
- **`impression`** (on channels) — projected views per video on that channel. Forward-looking estimate. May be null when not yet computed.
- **`views`** (on sponsorships) — actual view count of the sold and published sponsored video, accessible when `article_id` is set.
- **`impressions_guarantee`** (on sponsorships) — projected/guaranteed impressions for the sponsorship. Numeric; rounded to int in list output.
- **Sponsorship detail fields** (returned by `tl sponsorships show <id> --json`) — in addition to the list-view columns, the detail payload includes `integration` (raw int), `publish_count`, `common_name`, `outreach_email`, nested `publisher` (`first_name`, `last_name`, `email`), nested `brand_contact` (`first_name`, `last_name`, `email`), and `brand.organization_name`. Use these when generating IOs, contracts, or outreach.
- **CPM** has two distinct meanings depending on level — pick the one the user actually wants:
  - **Channel CPM** = `(adspot.price / channel.impression) × 1000` — projected price per thousand projected views. Used for pricing decisions **before** a sponsorship is sold. Available for channels with active adspots via `tl channels show <channel_id>`.
  - **Sponsorship CPM** = calculated in either of two ways: if `views` is present, then CPM is `(sponsorship.price / sponsorship.views) × 1000`, meaning realized cost per thousand actual views, computed post-publication. If `views` is null, Compute from the sponsorship's `price` and the channel's `impression` fields.
  - **CPM does not have a range filter.** To find sponsorships in a CPM range (e.g. "around $15"), fetch the record set with other filters first, then apply the CPM range in post-processing (jq, Python, etc.) on the returned `cpm` field. Plan queries and pagination accordingly — the server cannot reduce the result count based on CPM.
- **Sponsorship dates** — each sponsorship has four distinct dates, useful for different queries:
  - **`created_at`** — when the sponsorship record was created in the system
  - **`purchase_date`** — when the sponsorship was purchased (i.e. when the deal was made); These make up bookings.
  - **`send_date`** — the date the video is/was expected to be published (scheduled)
  - **`publish_date`** — the date the video was actually published; These make up live ads.
- **Credits** — every data query costs credits; use `tl describe` to see rates

Users see data scoped by their organization and plan:
- **Media buyers** see sponsorships where their org is the brand. They see `price` but never `cost`.
- **Media sellers** see sponsorships where their org is the publisher. They see `cost` but never `price`.
- **Intelligence plan** is required for `tl brands`, full channel search, and full uploads.

When querying sponsorship bookings, query by `status:sold` and filter the the date range only by `purchase_date`. Otherwise, query for state:sold by `created_at`.

An obsolete name for "sponsorship" is an "adlink".

## Methodology

Where possible, if searching for a sponsorship match between channels and brand, first search for what do similar brands sponsor / which brands is the channel usually sponsored by. This similarity should be preferably based on similar topics, similar upload frequency, similar channel sizes, and only after all that, on demographics.

## Workflow

At the start of session, always run a `tl help` command to find out which commands are available, and the `tl whoami` command to find out what you have access to.

Unless the user specifically asks for running a specific report or showing the result of a specific report, find the data by using other, low-level commands.

1. **Discover first**: Run `tl describe show <resource> --json` to learn available fields, filters, and credit costs before querying
2. **Check saved reports**: Run `tl reports --json` to see if the user has a saved report that already answers their question
3. **Check credits**: Run `tl balance --json` before expensive queries. Warn the user if a query will cost many credits.
4. **Query with filters**: Use `key:value` filter syntax for structured queries
5. **Always use --json**: Parse JSON output for multi-step analysis.
6. **Chain commands**: For complex questions, chain multiple `tl` commands
7. **Format results**: When the user asks for a list or tabular data, present the results as a well-formatted markdown table. Pick the most relevant columns and use clear headers.

Prefer writing Python code, shell code, or `jq` commands that fetche or analysise large sets of data, instead of analysing it yourself. Create temporary files in `/tmp` that can be analysed later in different ways. Before bulk data analysis by running `jq`, Python or Bash commands, first try fetching just a single result with `--limit 1` without `jq` etc, to see the shape of the data and any error messages.

## Available Commands

### Data queries
```bash
tl sponsorships list [filters...]      # Sponsorships — list curve, mult 1.0
tl sponsorships show <id>              # Sponsorship detail (2 credits)
tl sponsorships create --channel <id> --brand <id>  # Create proposal (free)
tl deals list [filters...]             # Shortcut: agreed-upon sponsorships (status:deal); same curve as sponsorships list
tl deals show <id>                     # Deal detail (2 credits)
tl matches list [filters...]           # Shortcut: possible brand-channel pairings (status:match); same curve
tl matches show <id>                   # Match detail (2 credits)
tl matches create --channel <id> --brand <id>  # Create match (free)
tl proposals list [filters...]         # Shortcut: proposed matches (status:proposal); same curve
tl proposals show <id>                 # Proposal detail (2 credits)
tl proposals create --channel <id> --brand <id>  # Create proposal (free)
tl uploads list [filters...]           # Video uploads from ES — list curve, mult 1.0
tl uploads show <id>                   # Upload detail (2 credits)
tl channels list [filters...]          # Channel search — list curve, mult 1.0
tl channels show <id-or-name>          # Channel detail (2 credits; accepts numeric ID or name)
tl channels history <id-or-name>       # Sponsorship history (5 credits/result, linear)
tl channels similar <id-or-name>       # Vector-similarity recommender (50 credits flat; Intelligence plan)
tl brands show <id-or-name>            # Brand detail (1 credit)
tl brands history <id-or-name>         # Sponsorship history (5 credits/result, linear)
tl brands history <query> --channel <id>  # Brand mentions on specific channel
tl brands similar <id-or-name>         # Find similar brands via profile vector KNN (50 credits flat)
tl snapshots channel <id>              # Channel metrics over time — list curve, mult 1.2 (Firebolt-backed)
tl snapshots video <id> --channel <id> # Video view curve — list curve, mult 1.2 (--channel required!)
tl reports                             # List saved reports — list curve, mult 1.3
tl reports run <id>                    # Run a saved report (credits vary)
tl comments list <adlink-id>           # List comments — list curve, mult 1.0
tl comments add <adlink-id> "msg"      # Add comment (free)
```

**"List curve"** above means non-linear pricing: `cost = 1 + mult × 0.126 × n^1.2`. The flat 1-credit setup applies to every list call; the `mult` reflects per-resource complexity. `tl db {pg,fb,es}` shares the same curve at mult=1.4. Concrete totals:

| Rows | mult=1.0 (channels, brands, comments, uploads, sponsorships) | mult=1.2 (snapshots) | mult=1.3 (reports) | mult=1.4 (db.pg / db.fb / db.es) |
|---:|---:|---:|---:|---:|
| 1 | 1 | 1 | 1 | 1 |
| 10 | 3 | 3 | 4 | 4 |
| 50 | 15 | 18 | 19 | 20 |
| 100 | 33 | 39 | 42 | 45 |
| 200 | 74 | 88 | 96 | 103 |
| 500 | 219 | 263 | 285 | 307 |

The marginal per-row cost is exactly proportional to `mult` — a 1.4× resource costs 1.4× the row part of a 1.0× resource at any size. Splitting a 500-row pull into ten 50-row calls saves ~30% but burns 10 setup floors instead of 1; "narrow the query" is almost always the better move than "fragment the pagination."

### Raw queries (`tl db`)

When a structured `tl <resource>` command can answer the question, prefer it — authoritative, role-scoped, paginated, breadcrumbed. Drop down to `tl db pg|fb|es` only when the high-level command can't express what you need.

```bash
tl db pg "<SELECT ...>"     # PostgreSQL — currently a server-side stub (HTTP 501)
tl db fb "<SELECT ...>"     # Firebolt — single-table reads on article_metrics / channel_metrics
tl db es "<JSON body>"      # Elasticsearch — search bodies against the server-fixed alias
```

All three honour `--json`/`--csv`/`--md`/`--toon` and accept `-` to read from stdin (`cat q.sql | tl db fb -`). They share the list-curve at `mult=1.4` (raw queries, no role scoping, wider blast radius).

**Reach for raw queries — don't simulate them client-side.** The structured `list` commands are great for filtered records. The moment the question turns into **aggregation, joining, or complex multi-condition filtering**, switch to `tl db`:

- **Aggregations** (counts, sums, avgs, group-bys, percentiles, time histograms) — push them into a single `tl db es` agg query or `tl db pg` `GROUP BY`. One server-side aggregation is faster, cheaper (one call vs N pages), and avoids the `from+size=10000` deep-pagination cap in ES.
- **Joins** — "X plus the related Y" belongs in `tl db pg` once it ships. Until then, doing the join client-side via two paginated structured walks is a workaround — flag it as such.
- **Complex filtering** the structured filter vocabulary can't express (compound boolean, `NOT IN`/`EXISTS`, `WHERE col IS NULL` on hidden fields, mixed range + enum + text predicates) — write it as one query rather than over-fetching and post-filtering.

Structured commands stay best for: single-record lookups (`tl <resource> show`), role-scoped filtered lists with simple filters, and anything where breadcrumbs/role-scoping matter.

| Need | Use |
|---|---|
| Single-record detail lookup | `tl <resource> show <id>` |
| Simple filtered list of records | Structured `tl <resource> list` |
| Channel/brand similarity, history | `tl channels similar / history`, `tl brands similar / history` |
| Saved reports | `tl reports`, `tl reports run` |
| Time-series view-curve / channel growth (default shape) | `tl snapshots channel`, `tl snapshots video` |
| **Aggregations** (counts, sums, group-by, histograms, percentiles) | **`tl db es` agg query** or **`tl db pg` `GROUP BY`** — do not paginate-and-roll-up client-side |
| **Joins / cross-table data** | **`tl db pg`** (when shipped) — until then, two paginated structured walks is a workaround |
| **Complex filtering** the structured filters can't express | **`tl db pg` / `tl db es`** rather than over-fetching and post-filtering |
| Transcript / brand-mention search inside video content | `tl db es` (no structured equivalent for content text) |
| Custom Firebolt shape (milestone-age slices, multi-channel growth comparisons) | `tl db fb` |
| Anything requiring a Postgres column the structured commands don't expose | `tl db pg` — **currently unavailable, see Limitations** |

#### `tl db es` — Elasticsearch

The CLI sends your JSON body to the server, which validates it before forwarding to ES. The index is fixed server-side (defaults to `tl-platform`); the client cannot select it. To narrow to a quarter or year, scope inside the body with a `publication_date` range filter rather than picking a different alias.

```bash
# Single video by composite ID
tl db es '{"size":1,"query":{"term":{"id":"1247603:8LskGvKUA9I"}}}'

# Aggregation: count sponsored mentions of brand 5612
tl db es '{"size":0,"track_total_hits":true,"query":{"term":{"sponsored_brand_mentions":"5612"}}}'

# Pipe a larger body
cat query.json | tl db es -
```

See [references/elasticsearch-schema.md](references/elasticsearch-schema.md) for accepted top-level keys, query types, size/depth limits, scripting/aggregation rules, and the field catalogue.

#### `tl db fb` — Firebolt

```bash
# View curve for one video (composite key)
tl db fb "SELECT age, view_count, like_count FROM article_metrics
          WHERE channel_id = 12345 AND id = 'dQw4w9WgXcQ'
          ORDER BY age"

# Channel reach over time
tl db fb "SELECT scrape_date, total_views, reach FROM channel_metrics
          WHERE id = 12345
          ORDER BY scrape_date"
```

See [references/firebolt-schema.md](references/firebolt-schema.md) for accepted-query rules (SELECT-only, single-table, indexed-filter requirements), table schemas, and ID-format details.

#### `tl db pg` — PostgreSQL

**Currently a server-side stub — POSTs return HTTP 501.** Endpoint accepts the same shape as the others (`{"query": "<sql>"}`) and the CLI is wired up, but the server view returns "not yet implemented" until execution support ships.

See [references/postgres-schema.md](references/postgres-schema.md) for the planned accepted-SQL rules and the table/column catalogue.

Until PG raw queries land, answer Postgres-shaped questions through the structured `tl` commands (which already cover sponsorships/channels/brands/profiles/orgs with role scoping). For things those don't expose, see Limitations below.

### Three sources, each authoritative for different things

- **Postgres** — deals, pipeline, brands, channels, users, organizations, profiles, revenue. Source of truth for deal state. Reachable today via the structured `tl` commands; raw `tl db pg` is a stub.
- **Elasticsearch** — videos, transcripts, brand mentions, **current** channel/video metrics, demographics. Reachable via `tl uploads`, `tl channels`, and `tl db es`.
- **Firebolt** — **historical** time-series snapshots only (view curves over time, subscriber-growth trends). Reachable via `tl snapshots` (preferred) or `tl db fb`.

**Use Firebolt only when you need a value AT A POINT IN TIME that no longer exists in the current ES/PG snapshot.** For "current views/subs", use ES.

**Join keys across sources** (you'll be doing the join in `jq`/Python, not in SQL):
- `Postgres channel.id` ↔ `ES channel.id` (on article docs) ↔ `Firebolt article_metrics.channel_id` / `channel_metrics.id`
- `Postgres adlink.article_id` is `<channel_id>:<youtube_id>` — same as ES `_id`. Strip the prefix to get `Firebolt article_metrics.id`.
- `Postgres brand.id` ↔ ES `sponsored_brand_mentions[]` / `organic_brand_mentions[]`.
- `publication_id` is **deprecated** — don't use it.

**Snapshots are sparse**, especially for older videos. Don't assume two arbitrary dates have data points. For approximations, prefer `tl snapshots` which already implements the project's interpolation logic; falling back to raw `tl db fb` means you handle gaps yourself.

### Schema references

Load these on demand — don't read all upfront. Pick the one(s) relevant to the question.

- [references/postgres-schema.md](references/postgres-schema.md) — tables, columns, relationships, `publish_status` constants. Useful even today for understanding what the structured `tl` commands return; required reading when `tl db pg` ships.
- [references/elasticsearch-schema.md](references/elasticsearch-schema.md) — index aliases, video/channel fields, common query bodies for `tl db es`.
- [references/firebolt-schema.md](references/firebolt-schema.md) — the two metric tables and their indexes; how to write valid `tl db fb` queries.

Always load the [references/business-glossary.md](references/business-glossary.md) file. It describes how business terms are mapped to database concepts (revenue, weighted pipeline, MSN, TPP, performance grade, team rosters).

### Key business concepts

See [references/business-glossary.md](references/business-glossary.md) for revenue/pipeline definitions, performance grades, ownership fields, MSN/TPP, and team rosters.

### Limitations of the `tl`-only data path

| Capability | Status | Workaround |
|---|---|---|
| Arbitrary read-only `SELECT` on Postgres (any joins, any tables, `information_schema` introspection) | **Unavailable** — `tl db pg` is a server-side stub (HTTP 501). | Use the structured `tl sponsorships / channels / brands / reports` commands. They cover the majority of business questions, with role scoping the raw queries don't have. For the rest, wait for `tl db pg` to ship — or ask a human to run the SQL. |
| Cross-reference helpers ("channels proposed to brand X", "channels sponsored by MBN brands in last N days") | **Unavailable** — these were stacked PG joins. | Approximate with `tl brands history <brand>` (videos where the brand was detected → extract channel IDs) and `tl sponsorships list brand:<name> status:<...>`. Won't perfectly match (e.g. `media_buying_network_join_date` isn't exposed). |
| **AdLink INSERT** with custom price/cost/owner/`weighted_price`/`created_where` | **Unavailable** — `tl sponsorships create` exists but only creates a free *proposal* between a channel and a brand. It does not let you set price/cost/owner_sales_id/send_date/etc. | Done in the app or by a human with DB access. |
| Pre-insert validation queries (joining `adspot ↔ channel ↔ profile ↔ org` to confirm MSN, integration=1, persona, plan) | **Unavailable** as a single query (needs PG joins). | Partial: `tl channels show <id>` exposes `msn`, `tpp`, and active adspots with `integration` codes. Persona/plan/profile-level checks aren't surfaced. |
| Firebolt cross-table or join queries; filtering on non-indexed columns in WHERE | **Unavailable** — not accepted. | Fetch a wider slice keyed on `channel_id` (and optionally `id`), filter the rest in `jq`/Python. |
| ES `query_string`, `regexp`, `wildcard`, `fuzzy`, `more_like_this`, parent/child joins; any `script_*`; multiple aggregations in one body | **Unavailable** — not accepted. | Rewrite using `term`/`terms`/`match`/`bool`/`nested`. For multi-agg dashboards, run multiple `tl db es` calls and combine client-side. For "similar"-style queries, try `tl channels similar` / `tl brands similar` (vector KNN, server-implemented). |
| ES deep pagination beyond `from+size = 10,000` | **Unavailable** via raw — `scroll` and `pit` aren't allowlisted; `search_after` is allowed but `from` is still capped. | Use `search_after` with `sort` to walk past 10k. For huge sweeps, narrow with `publication_date` ranges. |
| ES index introspection (`_cat/indices`, mappings) | **Unavailable** — only `_search` is wired. | Read [references/elasticsearch-schema.md](references/elasticsearch-schema.md). It's manually maintained — update it when you discover new fields. |
| Schema introspection on Postgres (`information_schema.columns`, `pg_class`, …) | **Unavailable** until `tl db pg` ships, and even then catalog-resolving casts and many `pg_*` helpers are blocked. | Read [references/postgres-schema.md](references/postgres-schema.md). |

If a user asks for one of the **Unavailable** items, say so explicitly and propose the closest `tl`-based approximation rather than silently degrading.

### Discovery & system
```bash
tl describe                            # List all resources with credit costs (free)
tl describe show <resource> --json     # Fields, filters, credit rates (free)
tl schema pg                           # PostgreSQL schema reference for `tl db pg` (free)
tl schema fb                           # Live Firebolt tables and column types for `tl db fb` (free)
tl schema es                           # Elasticsearch document shape for `tl db es` (free)
tl balance --json                      # Credit balance (free)
tl whoami                              # Current user, org, brands (free)
tl auth status                         # Auth check (free)
tl changelog                           # Release notes — current version, or current..latest if behind (free)
tl changelog v0.4.17 v0.4.18           # Notes for explicit versions
tl changelog since v0.4.10             # Notes from v0.4.10 to latest
tl changelog --md > CHANGELOG.md       # Capture for a doc
```

`tl changelog` summaries are LLM-generated server-side from full commit messages and cached per version, so repeat calls are fast and don't re-bill the LLM. The release date and a 2–4 sentence prose summary come back per version.

### Filter syntax
All list commands accept `key:value` filters:
```bash
tl sponsorships list status:sold brand:"Nike" purchase-date:2026-01
tl uploads list channel:12345 type:longform
tl channels list category:cooking min-subs:100k language:en
tl channels list tpp:yes                       # list all TPP (TL-managed) channels
tl channels list tpp:no primary-device:mobile  # mobile-first channels that aren't in TPP
tl channels list msn:yes category:tech         # Media Selling Network channels in tech
tl channels list msn:no min-subs:500k          # big non-MSN channels (not yet opted in)
```

Date filters accept keywords: `today`, `yesterday`, `tomorrow`.

#### Channel demographic filters

These filters apply to both `tl channels list` and `tl sponsorships list` (the latter filters by the associated channel's demographics):

```bash
# Primary device type
tl channels list primary-device:mobile
tl channels list primary-device:desktop
tl channels list primary-device:tablet

# Minimum device audience share (0–100)
tl channels list min-mobile-share:60
tl channels list min-desktop-share:30
tl channels list min-tablet-share:10

# Minimum geo share (0–100, ISO country codes lowercase)
tl channels list min-us-share:70
tl channels list min-gb-share:25

# Combine with other filters
tl channels list category:tech primary-device:mobile min-us-share:50 min-subs:100k
tl sponsorships list status:sold primary-device:mobile min-us-share:60
```

### Output flags
- `--json` — structured JSON (use this for parsing)
- `--csv` — CSV output
- `--md` — Markdown table
- `--limit N` — max results
- `--offset N` — pagination

### Response shape
Successful `--json` responses wrap data in an envelope:

```json
{
  "results": [ { "...": "..." } ],
  "total": 42,
  "usage": { "credits_charged": 2, "balance_remaining": 9998 },
  "_breadcrumbs": [ { "hint": "...", "command": "tl ..." } ]
}
```

Errors return `{"detail": "..."}` with an HTTP status (400 / 401 / 403 / 404).

While analysing results, you must always examine the `results` field in the JSON.

## Credit Awareness

Every query costs credits. Before running expensive queries:
1. Check the credit rate: `tl describe show <resource> --json | jq '.credits'` and the user balance.
2. **List endpoints (sponsorships/channels/uploads/snapshots/comments/reports/db) are priced non-linearly:** `cost = 1 + mult × 0.126 × n^1.2`, where `mult` is the per-resource complexity factor (1.0 for cheap reads, 1.2 for snapshots, 1.3 for reports, 1.4 for raw db). Detail/history/similar endpoints are linear (`rate × results`). See the table in the command list above.
3. Estimate cost from the formula or the table; for non-list endpoints use `results × rate`.
4. If estimated cost is more than 10% of the remaining balance, ask the user to confirm the operation before running.

## Data Scoping

Users only see data their plan allows:
- **Media buyers** see deals where their org is the brand. They see `price` but never `cost`.
- **Media sellers** see deals where their org is the publisher. They see `cost` but never `price`.
- **Intelligence plan** required for `tl brands`, full `tl channels list` search, and full `tl uploads list`.
- **Paid plan** required for `tl snapshots`.

## Important: Status Labels

When presenting sponsorship status data, always use human-readable labels — never raw codes. The `tl` CLI returns lowercase labels (`sold`, `pending`, `matched`, etc.) — capitalize them for display. Full mapping: proposed, unavailable, pending, sold, advertiser_reject → "Rejected by Advertiser", publisher_reject → "Rejected by Publisher", proposal_approved → "Proposal Approved", matched, outreach → "Reached Out", agency_reject → "Rejected by Agency".

## Important: Firebolt Snapshots

`tl snapshots video` **always requires** `--channel`. Without it, the query scans 7.4 billion rows and times out. Always provide the channel ID.

## Examples

"Show me my sold sponsorships this quarter":
```bash
tl deals list purchase-date-start:2026-01-01 --json
```

"What channels does Nike sponsor?":
```bash
tl brands history Nike --json
```

"Compare view curves for two videos":
```bash
tl snapshots video abc123 --channel 456 --json
tl snapshots video def789 --channel 456 --json
```

"Run my Q1 pipeline report":
```bash
tl reports --json  # Find the report ID first
tl reports run 42 --json
```

"Find mobile-first US channels in cooking":
```bash
tl channels list category:cooking primary-device:mobile min-us-share:50 --json
```

"Show sold sponsorships targeting mobile US audiences":
```bash
tl sponsorships list status:sold primary-device:mobile min-us-share:60 --json
```

"Find channels similar to one I know" (vector-similarity recommender, 50 credits per call):
```bash
tl channels similar 29834 --limit 10                         # by ID (defaults to msn:yes, tpp:both)
tl channels similar "Tremending girls" --limit 5             # by unique name
tl channels similar 29834 min-score:0.85 --limit 20          # tighter similarity threshold
tl channels similar 29834 msn:both min-score:0.4 --limit 30  # include both MSN and non-MSN channels
tl channels similar 29834 msn:no --limit 30                  # non-MSN channels only
tl channels similar 29834 tpp:yes --limit 30                 # TPP (TL-managed) channels only
tl channels similar 29834 min-subs:1000000 exclude:477487 --limit 15  # client-side filters
```
**Both `tl channels show` and `tl channels similar` accept either a numeric channel ID or a channel name.** Name arguments are case-insensitive partial matches; if more than one active channel matches, the command prints a candidates table (channel_id, subscribers, name) and exits 1 so you can retry with a specific ID. The `msn` filter on `similar` is tri-state: `yes` (only MSN channels — the default), `no` (only non-MSN channels), `both` (no MSN filter). `tl channels look-alike` is a hidden alias for `similar` that matches the internal "look-alike channels" terminology.
