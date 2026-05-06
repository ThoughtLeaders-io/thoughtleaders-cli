---
name: tl
description: Query and analyze ThoughtLeaders business data using the `tl` CLI. Default to raw database queries via `tl db pg|fb|es` for anything non-trivial (joins, aggregations, multi-condition filters, anything that would otherwise need post-processing); use the structured resource commands (sponsorships, deals, channels, brands, uploads, snapshots, reports) only for trivially simple lookups (single-record show by ID, plain filtered lists). Triggers on questions about deals, sponsorships, pipeline, revenue, brands, channels, MSN, TPP, uploads/videos, transcripts, brand mentions, view-curves, sales numbers, reports, or any cross-source business analysis ("how many deals", "pipeline report", "weighted pipeline", "channel data", "brand lookup", "view curve", "find mentions of", "investigate this video", "query the database"). You ARE the AI layer — do not use `tl ask`.
---

# ThoughtLeaders Data Analyst

Run the `tl` CLI to query ThoughtLeaders' sponsorship platform data. Use it to answer questions about deals, channels, brands, uploads, metrics, etc.

## Core Principles

**Default to raw database queries.** For anything beyond a trivially simple lookup, reach for `tl db pg|fb|es`. Avoid the structured `tl <resource>` commands (`sponsorships list`, `channels show`, `brands history`, etc.).

Always run `tl schema pg|fb|es` before writing a raw query.

**When you only need the schema of one table, you MUST call `tl schema pg <table>` (or `tl schema fb <table>`) — never the unscoped form**, to reduce token counts. ES has no per-table form (the index is a single document shape) — `tl schema es` is the only call there.

**Process data with shell tools, not your context window.** Don't pull large result sets into your reasoning context just to filter, sort, count, or extract a field — that wastes tokens and slows you down. Pipe `tl … --json` (or `--csv`, or `--toon`) into `jq`, `yq`, `rg`, or `duckdb`, as appropriate, and read only the answer back. Pick the tool by shape:

- **`jq`** — filter, project, and transform JSON. The default for `tl … --json` post-processing.
  ```bash
  tl sponsorships list status:sold --json | jq '.results[] | select(.price > 5000) | {id, brand, price}'
  ```
- **`yq`** — same idea for YAML/TOML, useful when reading config files or `--md` blocks.
- **`rg`** — fast text search across CLI output, transcripts, and the codebase. Better than `grep` for searching large `--csv` exports or transcript dumps.
  ```bash
  tl db es '{"size":500,"query":{"term":{"channel.id":5607}},"_source":["id","transcript"]}' --json | rg -o "NordVPN[^.]*"
  ```
- **`duckdb`** — embedded analytical SQL over CSV/JSON files. Use when you need joins, aggregations, or window functions across multiple `tl` exports without spinning up a database.
  ```bash
  tl deals list purchase-date-start:2026-01 --csv > deals.csv
  duckdb -c "SELECT brand, SUM(price) AS revenue FROM 'deals.csv' GROUP BY brand ORDER BY revenue DESC LIMIT 10"
  ```

The pattern is always: server-side narrowing first (filter in the `tl db` query or the structured filters), then shell tool to shape the result, then read only the final summary into context. If `tl doctor` reports any of these as missing, ask the user to install them — `tl-internal setup` installs all four by default.

Always assume there will be more than 1 page of results. You MUST always use `--limit` and `--offset` options in the `tl list` commands to retrieve the entire data set (all pages, until the total records are fetched). You must also always use pagination in scripts you write to collect results. The maximum number of results per page is 500.

Retry after 5 seconds if the server returns a "connection denied" or a "server error" on any request.

Where possible reference sponsorships, brands, channel by numeric IDs.

## Data Model & Terminology

ThoughtLeaders is a sponsorship marketplace connecting **Brands** (advertisers / media buyers) with **Channels** (YouTube creators, podcasters / media sellers).

The centre of the data model is **Sponsorships** — business relationships between brands and channels. Sponsorships have a funnel of types, from broad to narrow:

- **Sponsorships** — the broadest category, encompassing all stages, stored in the `thoughtleaders_adlink` table.
  - **Matches** — possible brand-channel pairings that ThoughtLeaders thinks could work
  - **Proposals** — matches that have been proposed to both sides to consider
  - **Deals** — contractually agreed-upon sponsorships (sold), either in production or published

Sponsorships are sometimes called "Ads" or "Ad campaigns". **"AdLink"** is another name for the same thing — it's the term the database uses (`thoughtleaders_adlink`) and shows up across internal code, schema docs, and AM Slack threads. Treat "sponsorship" and "adlink" as interchangeable; the user-facing word is "sponsorship," the engineering/DB word is "adlink."

The CLI has shortcut commands for each type: `tl matches`, `tl proposals`, `tl deals`. These filter `tl sponsorships` by status.

Other key concepts:
- **Uploads** — YouTube videos indexed from Elasticsearch
- **Snapshots** — historical time-series metrics for channels and videos (Firebolt)
- **Reports** — saved report configurations that can be re-run
- **Comments** — notes attached to sponsorships
- **Adspots** — types of ads a channel carries (e.g. mention, dedicated video, product placement). Returned by `tl channels show`; each carries price/cost.
- **Profiles** — per-organization actors that own sponsorship records on behalf of either side of a deal. A profile is buyer-side or seller-side:
  - *Buyer-side (brand) profiles* — represent a sponsoring brand. Each brand profile has an M2M link to at most one `Brand` record (which are the actual advertiser identities). On a sponsorship, `creator_profile` is the buyer-side profile.
  - *Seller-side (publisher) profiles* — attached to a `Publication`, which in turn owns one or more `Channel` records. A channel's adspots therefore inherit ownership through `channel.publication.profile`.
  - **How to tell them apart** — three signals on the `thoughtleaders_profile` row, used in this order:
    1. **`persona`** (canonical) — `1=Brand`, `4=Media Agency`, `3=Talent Manager` are buyer-side; `2=Creator`, `5=Creator Service` are seller-side. May be null on legacy rows.
    2. **`is_advertiser` / `is_publisher`** booleans — feature flags; either or both can be true for staff-style profiles, but on normal user profiles they reliably mark side.
  - Org scoping for sponsorships is profile-mediated: a sponsorship belongs to your org if **either** `creator_profile.organization` (brand side) **or** `ad_spot.channel.publication.profile.organization` (publisher side) matches yours.
- **MSN** (Media Selling Network) — the ~11k YouTube channels that have opted in to receive sponsorship offers. A channels is in the MSN group if the `channel.media_selling_network_join_date` field is not null.
- **MBN** (Media Buying Network) — the brand-side counterpart to MSN: brand profiles that have opted in to receive proposed sponsorships. A profile is in the MBN group if the `profile.media_buying_network_join_date` field is not null.
- **TPP** (ThoughtLeaders Partner Program, a.k.a. "TL channels") — the smaller, exclusive ~169 channels TL manages directly. A channel is in the TPP group if the `channel.is_tl_channel` is True.
- **`demographics_updated_at`** (on channel detail) — ISO timestamp of when demographic screenshots were last uploaded and processed via OCR. If non-null, the channel has demographics screenshots on file. If null, no screenshots have been uploaded. Use this to check whether a channel has demographics data from screenshots.
- **`impression`** (on channels) — projected views per video on that channel. Forward-looking estimate. May be null when not yet computed.
- **`views`** (on sponsorships) — actual view count of the sold and published sponsored video, accessible when `article_id` is set.
- **`impressions_guarantee`** (on sponsorships) — projected/guaranteed impressions for the sponsorship. Numeric; rounded to int in list output.
- **Sponsorship detail fields** (returned by `tl sponsorships show <id> --json`) — in addition to the list-view columns, the detail payload includes `integration` (raw int), `publish_count`, `common_name`, `outreach_email`, nested `publisher` (`first_name`, `last_name`, `email`), nested `brand_contact` (`first_name`, `last_name`, `email`), and `brand.organization_name`. Use these when generating IOs, contracts, or outreach.
- **CPM** has two distinct meanings depending on level — pick the one the user actually wants:
  - **Channel CPM** = `(adspot.price / channel.impression) * 1000` — projected price per thousand projected views. Used for pricing decisions **before** a sponsorship is sold. Available for channels with active adspots via `tl channels show <channel_id>`.
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
- **Intelligence plan** is required for accessing information not strictly related to the user's organisation.

When querying sponsorship bookings, query by `status:sold` and filter the the date range only by `purchase_date`. Otherwise, query for state:sold by `created_at`.

## Methodology

Where possible, if searching for a sponsorship match between channels and brands, first search for what do similar brands sponsor / which brands is the channel usually sponsored by. The similarity judgement should be preferably based on similar topics, similar upload frequency, similar channel sizes, and only after all that, on demographics.

Use the `tl channels similar` and `tl brands similar` commands to explore 1:1 similarity between known channels or brands. For category- or topic-driven discovery (e.g. "find me Cooking channels", "who scores high on USA share?"), use `tl recommender top-channels "<tag>"` (or `top-brands`/`top-profiles`) against the recommender — that's faster, ranked by category-strength. Run `tl recommender tags` to discover the valid tag names.

## Workflow

At the start of session, always run `tl --help` to find out which command groups are available, and `tl whoami` to find out what you have access to.

### How to discover commands and subcommands

The CLI exposes three different discovery surfaces — pick by what you actually need:

| You want to know… | Run |
|---|---|
| Top-level command groups (`sponsorships`, `channels`, `db`, `recommender`, etc.) | `tl --help` |
| Subcommands of a group (`tl recommender` → `tags`, `top-channels`, `inspect-brand`, …) | `tl <group> --help` (e.g. `tl recommender --help`, `tl db --help`) |
| Arguments and flags for a specific leaf command | `tl <group> <subcommand> --help` (e.g. `tl recommender top-channels --help`) |
| Fields, filters, credit rates for a **data resource** (sponsorships, uploads, snapshots, reports, comments, recommender) | `tl describe show <resource> --json` |
| The live PG/ES/Firebolt schema for raw `tl db` queries | `tl schema pg` / `tl schema es` / `tl schema fb` |
| The schema of a **single** PG / Firebolt table | **`tl schema pg <table>`** / **`tl schema fb <table>`** — strongly preferred when you only need one |

Notes:
- Use `--help` everywhere — there is no separate `tl help` command. `tl help` returns "No such command 'help'".
- **`tl describe show channels`** and **`tl describe show brands`** intentionally do not list fields/filters — channel and brand search live in raw SQL (`tl db pg`) and the recommender, not in a structured list endpoint. They print a notice steering you there.
- `--help` describes **CLI shape**; `tl describe` describes **data shape**. They don't overlap.

Unless the user specifically asks for running a specific report or showing the result of a specific report, find the data by using other, low-level commands.

1. **Discover first**: Run `tl describe show <resource> --json` to learn available fields, filters, and credit costs before querying. Use `tl schema pg`, `tl schema es`, and `tl schema fb` to find information about the main database (pg), the articles / uploads database (es), and the channel metrics database (fb).
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
tl sponsorships update <id> '<json>'   # Update a sponsorship (2 credits)
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
tl channels show <id-or-name>          # Channel detail (2 credits; accepts numeric ID or name) — for channel search use raw SQL on thoughtleaders_channel
tl channels update <id> '<json>'       # Update a channel (2 credits)
tl channels history <id-or-name>       # Sponsorship history (5 credits/result, linear)
tl channels similar <id-or-name>       # Similarity recommender (25 credits flat; Intelligence plan)
tl brands show <id-or-name>            # Brand detail (1 credit)
tl brands history <id-or-name>         # Sponsorship history (5 credits/result, linear)
tl brands history <query> --channel <id>  # Brand mentions on specific channel
tl brands history-stats <id-or-name>   # Aggregate roll-up: counts, total/avg/median views, first/last seen, by-year, top channels (5 credits flat)
tl brands history-stats <q> --channel <id>  # Same roll-up, narrowed to one channel
tl brands similar <id-or-name>         # Find similar brands via similarity search (25 credits flat)
tl recommender tags [query]            # List similarity tag names — categories, demographics, formats (free)
tl recommender top-channels "<tag>"    # Top channels loaded on a similarity tag (25 credits; Intelligence)
tl recommender top-profiles "<tag>"    # Top brand profiles loaded on a similarity tag (25 credits)
tl recommender top-brands "<tag>"      # Top brands (deduped from profiles) loaded on a similarity tag (25 credits)
tl recommender inspect-channel <ref>   # Show a channel's similarity-profile breakdown (25 credits; Intelligence)
tl recommender inspect-brand <ref>     # Show a brand profile's ideal similarity-profile breakdown (25 credits; Intelligence)
tl recommender similar-to-profile <id> # Channels closest to a brand profile's ideal profile (25 credits; Intelligence)
tl snapshots channel <id>              # Channel metrics over time (Firebolt-backed)
tl snapshots video <id> --channel <id> # Video view curve (--channel required!)
tl reports                             # List saved reports
tl reports run <id>                    # Run a saved report (credits vary)
tl <entity> comment-list <id>          # List comments on a sponsorship/channel/brand/upload
tl <entity> comment-add <id> "msg"     # Add a comment (free)
tl <entity> comment-edit <comment-id> "msg"  # Edit own comment (author or superuser; free)
```

**Credit costs are server-authoritative — run `tl describe` (overview) or `tl describe show <resource>` (one resource) to see the current rates and multipliers for every endpoint. Do not memorise rate values — they change.**

### Updating records

```bash
tl sponsorships update <id> '<json>'   # Edit a sponsorship (adlink)
tl channels update <id> '<json>'       # Edit a channel
```

Examples:
```bash
tl sponsorships update 98765 '{"publish_status": "sold"}'
tl sponsorships update 98765 '{"publish_status": 3}'
tl channels update 12345 '{"demographic_male_share": 62}'
tl channels update 12345 '{"demographic_geo": {"US": 60, "UK": 12, "CA": 8}}'
tl channels update 12345 '{"demographic_male_share": 55, "demographic_usa_share": 70}'
```

Each call costs 2 credits. If a request is rejected with a 400, the response body names the offending key — read it and retry with a smaller body. If the user wants to edit something the API rejects, the change has to be made in the app or by a human with DB access.

### Raw queries (`tl db`)

`tl db pg|fb|es` is the default tool. Reach for it whenever the question is anything beyond a trivially simple lookup — and use the structured commands only for those trivial cases (single-record `show`, plain filtered `list`). Don't paginate-and-reduce in your head when one SQL or ES body would do it server-side.

```bash
tl db pg "<SELECT ...>"     # PostgreSQL — read-only SELECT
tl db fb "<SELECT ...>"     # Firebolt — single-table reads on article_metrics / channel_metrics
tl db es "<JSON body>"      # Elasticsearch — search bodies against the server-fixed alias
```

All three honour `--json`/`--csv`/`--md`/`--toon` and accept `-` to read from stdin (`cat q.sql | tl db fb -`). They share the list-curve at `mult=1.4` (raw queries, no role scoping, wider blast radius).

Reasons to write a raw query (the common case):

- **Aggregations** (counts, sums, avgs, group-bys, percentiles, time histograms) — one `tl db pg` `GROUP BY` or `tl db es` agg body, not a paginated walk + Python reduce.
- **Joins / cross-table data** — `tl db pg` returns brand+channel+deal in one row instead of two structured walks stitched in `jq`.
- **Multi-condition filtering** — compound boolean, `NOT IN`/`EXISTS`, `WHERE col IS NULL` on hidden fields, mixed range + enum + text predicates: write the SQL/ES body, don't over-fetch and post-filter.
- **Fields the structured commands don't expose** — e.g. `media_selling_network_join_date` (only the `msn` boolean is surfaced), `weighted_price`, `tx_data`, raw `publish_status` integer, etc.

Structured commands are still the right tool for: single-record `show` by ID, plain filtered `list` (one or two filters that the structured vocabulary already supports), saved `tl reports run`, and `tl snapshots channel|video` (these wrap interpolation logic you'd otherwise reimplement).

| Need | Use |
|---|---|
| **Aggregations** (counts, sums, group-by, histograms, percentiles) | **`tl db pg` `GROUP BY`** or **`tl db es` agg query** |
| **Joins / cross-table data** | **`tl db pg`** |
| **Multi-condition filtering** the structured filters can't express | **`tl db pg` / `tl db es`** |
| **Fields the structured commands don't expose** (raw `publish_status`, `weighted_price`, `media_selling_network_join_date`, etc.) | **`tl db pg`** |
| Transcript / brand-mention search inside video content | **`tl db es`** (no structured equivalent for content text) |
| Custom Firebolt shape (milestone-age slices, multi-channel growth comparisons) | **`tl db fb`** |
| Single-record detail lookup by ID | `tl <resource> show <id>` |
| Plain filtered list with one or two simple filters | `tl <resource> list` |
| Channel/brand similarity (server-implemented similarity search) | `tl channels similar`, `tl brands similar` |
| Saved reports | `tl reports`, `tl reports run` |
| Time-series view-curve / channel growth (default shape with interpolation) | `tl snapshots channel`, `tl snapshots video` |

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

```bash
# Top brands by deal count
tl db pg "SELECT b.name, COUNT(*) AS deals
          FROM thoughtleaders_adlink a
          JOIN thoughtleaders_profile p ON a.creator_profile_id = p.id
          JOIN thoughtleaders_profile_brands pb ON p.id = pb.profile_id
          JOIN thoughtleaders_brand b ON pb.brand_id = b.id
          WHERE a.publish_status = 3
          GROUP BY b.name
          ORDER BY deals DESC
          LIMIT 20 OFFSET 0"
```

See [references/postgres-schema.md](references/postgres-schema.md) for the accepted-SQL rules and the table/column catalogue. `tl schema pg` prints the live table/column listing visible to the caller.

### Three sources, each authoritative for different things

- **Postgres** — deals, pipeline, brands, channels, users, organizations, profiles, revenue. Source of truth for deal state. Reachable via the structured `tl` commands or raw `tl db pg`.
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

- [references/postgres-schema.md](references/postgres-schema.md) — tables, columns, relationships, `publish_status` constants. Required reading for `tl db pg` queries, and useful for understanding what the structured `tl` commands return.
- [references/elasticsearch-schema.md](references/elasticsearch-schema.md) — index aliases, video/channel fields, common query bodies for `tl db es`.
- [references/firebolt-schema.md](references/firebolt-schema.md) — the two metric tables and their indexes; how to write valid `tl db fb` queries.

Always load the [references/business-glossary.md](references/business-glossary.md) file. It describes how business terms are mapped to database concepts (revenue, weighted pipeline, MSN, TPP, performance grade, team rosters).

### Key business concepts

See [references/business-glossary.md](references/business-glossary.md) for revenue/pipeline definitions, performance grades, ownership fields, MSN/TPP, and team rosters.

### Limitations of the `tl`-only data path

| Capability | Status | Workaround |
|---|---|---|
| Arbitrary read-only `SELECT` on Postgres | **Available** via `tl db pg`. | SELECT-only, mandatory `LIMIT ≤ 500` + `OFFSET`, only certain SQL forms are allowed. See `references/postgres-schema.md`. |
| Cross-reference helpers ("channels proposed to brand X", "channels sponsored by MBN brands in last N days") | **Available** via `tl db pg`. | Write the join: `thoughtleaders_adlink` ↔ `adspot` ↔ `channel` ↔ `profile` ↔ `profile_brands` ↔ `brand`. Filter by `publish_status` for proposed/sold and by date range as needed. See `references/postgres-schema.md` for the exact column names. |
| **AdLink INSERT** with custom price/cost/owner/`weighted_price`/`created_where` | **Unavailable** — `tl sponsorships create` exists but only creates a free *proposal* between a channel and a brand. The `tl db pg` sanitizer accepts SELECT only — no INSERT/UPDATE. | Done in the app or by a human with DB access. |
| Pre-insert validation queries (joining `adspot ↔ channel ↔ profile ↔ org` to confirm MSN, integration=1, persona, plan) | **Available** via `tl db pg`. | One SELECT joining the four tables. Use `thoughtleaders_channel.media_selling_network_join_date IS NOT NULL` for MSN, `thoughtleaders_adspot.integration = 1` for mention adspots, `thoughtleaders_profile.persona` for the persona code (see persona constants in `references/postgres-schema.md`). |
| Firebolt cross-table or join queries; filtering on non-indexed columns in WHERE | **Unavailable** — not accepted. | Fetch a wider slice keyed on `channel_id` (and optionally `id`), filter the rest in `jq`/Python. |
| ES `query_string`, `regexp`, `wildcard`, `fuzzy`, `more_like_this`, parent/child joins; any `script_*`; multiple aggregations in one body | **Unavailable** — not accepted. | Rewrite using `term`/`terms`/`match`/`bool`/`nested`. For multi-agg dashboards, run multiple `tl db es` calls and combine client-side. For "similar"-style queries, try `tl channels similar` / `tl brands similar` (server-implemented similarity search). |
| ES deep pagination beyond `from+size = 10,000` | **Unavailable** via raw — `scroll` and `pit` aren't allowlisted; `search_after` is allowed but `from` is still capped. | Use `search_after` with `sort` to walk past 10k. For huge sweeps, narrow with `publication_date` ranges. |
| ES index introspection (`_cat/indices`, mappings) | **Unavailable** — only `_search` is wired. | Read [references/elasticsearch-schema.md](references/elasticsearch-schema.md). It's manually maintained — update it when you discover new fields. |
| Schema introspection on Postgres (`information_schema.columns`, `pg_class`, …) | **Partial** — catalog-resolving casts and many `pg_*` helpers are blocked. | Use `tl schema pg` for the live table/column listing, or read [references/postgres-schema.md](references/postgres-schema.md). |

If a user asks for one of the **Unavailable** items, say so explicitly and propose the closest `tl`-based approximation rather than silently degrading.

### Discovery & system
```bash
tl describe                            # List all resources with credit costs (free)
tl describe show <resource> --json     # Fields, filters, credit rates (free)
tl schema pg                           # PostgreSQL schema reference for `tl db pg` (free) — every visible table
tl schema pg <table>                   # PostgreSQL schema for a SINGLE table (free) — same markdown shape
tl schema fb                           # Live Firebolt tables and column types for `tl db fb` (free) — both tables
tl schema fb <table>                   # Firebolt schema for a SINGLE table (free) — `article_metrics` or `channel_metrics`
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
Structured list commands accept `key:value` filters (use them for trivially simple lookups):
```bash
tl sponsorships list status:sold brand:"Nike" purchase-date:2026-01
tl uploads list channel:12345 type:longform
```

Date filters accept keywords: `today`, `yesterday`, `tomorrow`.

#### Channel discovery — recommender first, raw SQL second

For category- or demographic-driven discovery, **use the recommender, not `content_category` SQL.** The recommender ranks channels by how strongly they load on a category/demographic tag (similarity scores), instead of forcing exact equality on a single integer code. It also returns the matching brand profiles alongside the channels — useful when the user actually wants to know "who buys this kind of inventory."

```bash
# Discover the right tag name first (free)
tl recommender tags cooking
tl recommender tags "usa"

# Top channels & profiles loaded on a similarity tag (25 credits; Intelligence)
tl recommender top-channels "Cooking" msn:yes --limit 50
tl recommender top-channels "Tech" --limit 30
tl recommender top-brands "USA share" mbn:yes --limit 50
```

Use `tl db pg` only for predicates the recommender can't express — pure attribute filters (`is_tl_channel`, `language`, `demographic_device_primary`), aggregations, and joins. Run `tl schema pg` once to confirm the live column set; the columns referenced below are stable.

```bash
# All TPP (TL-managed) channels — pure attribute filter, not a category query
tl db pg "SELECT id, channel_name, content_category, total_views
          FROM thoughtleaders_channel
          WHERE is_tl_channel = TRUE
          ORDER BY total_views DESC
          LIMIT 200 OFFSET 0"

# Mobile-first non-TPP channels — device share, not topic
tl db pg "SELECT id, channel_name, demographic_device_primary, total_views
          FROM thoughtleaders_channel
          WHERE is_tl_channel = FALSE
            AND demographic_device_primary = 'mobile'
          ORDER BY total_views DESC
          LIMIT 100 OFFSET 0"
```

For per-country share beyond the recommender's "USA share" tag, use the `demographic_geo` jsonb in raw SQL: `(demographic_geo->>'gb')::int >= 25`. Same pattern with `demographic_device->>'mobile'` for non-primary device shares.

**MSN status (`media_selling_network_join_date`) is scrubbed from the advertiser sandbox view.** Raw SQL can't filter on it from an advertiser context. For MSN-only / non-MSN lookups, run the same raw SQL with `media_selling_network_join_date IS [NOT] NULL` from a context that has access to it (full-access role), or rely on the recommender's MSN-aware filters: `tl recommender top-channels "<tag>" msn:yes|no|all`.

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
- **Intelligence plan** required for `tl brands`, the full `tl recommender` surface, and full `tl uploads list`.
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

"Find Cooking channels with US-heavy mobile audiences":
```bash
# Use the recommender for the topic, then narrow with structured filters / SQL on the IDs.
tl recommender top-channels "Cooking" msn:yes --limit 100 --json \
  | jq -r '.results[].channel_id' \
  | paste -sd, - \
  | xargs -I {} tl db pg "SELECT id, channel_name, total_views, demographic_usa_share
                          FROM thoughtleaders_channel
                          WHERE id IN ({})
                            AND demographic_device_primary = 'mobile'
                            AND demographic_usa_share >= 50
                          ORDER BY total_views DESC
                          LIMIT 50 OFFSET 0" --json
```

"Show sold sponsorships targeting mobile US audiences":
```bash
tl sponsorships list status:sold primary-device:mobile min-us-share:60 --json
```

"Find channels similar to one I know" (similarity recommender, 25 credits per call):
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

"Browse the recommender" (categories, demographics, formats — `tl recommender tags` is free):
```bash
tl recommender tags                                            # Full tag list (free)
tl recommender tags cooking                                    # Search tag names by substring
tl recommender top-channels "Cooking" msn:yes --limit 50       # Top channels loaded on a tag (25 credits)
tl recommender top-profiles "Cooking" --limit 30               # Top brand profiles for the tag
tl recommender top-brands "USA share" mbn:yes --limit 30       # Top brands (deduped) — demographic tag, MBN only
tl recommender top-channels "Tech" exclude-for-profile:842     # Drop channels already proposed for profile 842
tl recommender inspect-channel 29834                           # Per-tag breakdown of a channel's vector
tl recommender inspect-brand Nike                              # Per-tag breakdown of a brand's ideal profile
tl recommender similar-to-profile 842 --limit 30               # Channels closest to a brand profile's ideal profile
```
Use `tl recommender top` for category/topic discovery (it's ranked) and `tl channels similar` / `tl brands similar` for 1:1 lookalike searches.
