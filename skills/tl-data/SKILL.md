---
name: tl-data
description: Query and analyze ThoughtLeaders business data using the `tl` CLI — PostgreSQL, Elasticsearch, and Firebolt access via `tl db pg|fb|es`, plus the high-level `tl` resource commands. Use for deals/sponsorships, pipeline, brands, channels, MSN, uploads/videos, transcripts, brand mentions, view-curves, sales numbers, reports, and any cross-source business analysis. Triggers on phrases like "how many deals", "pipeline report", "weighted pipeline", "channel data", "brand lookup", "view curve", "find mentions of", "investigate this video", "query the database".
---

# TL Data Skill (tl-only)

Query ThoughtLeaders' PostgreSQL, Elasticsearch, and Firebolt **exclusively through the `tl` CLI**. No direct DB drivers, no curl, no env-var connection strings — every query goes through `tl`.

This skill complements the higher-level `tl` skill: when a structured `tl <resource>` command can answer the question (e.g. `tl sponsorships list`, `tl channels show`), prefer that. Drop down to `tl db pg|fb|es` only when the high-level command can't express what you need.

## Two layers, one tool

**1. Structured commands** — the primary interface. Authoritative, role-scoped, paginated, breadcrumbed. Use these for everything they cover:

```
tl sponsorships  tl deals  tl matches  tl proposals
tl channels      tl brands  tl uploads
tl snapshots     tl reports  tl comments
tl describe      tl whoami   tl balance
```

See the `tl` skill for filter syntax, pagination rules, status labels, role scoping, and credit awareness — all of that applies here too.

**2. Raw queries** (`tl db`) — for anything the structured commands can't express. Three subcommands:

```bash
tl db pg "<SELECT ...>"               # PostgreSQL — currently a server-side stub (501)
tl db fb "<SELECT ...>"               # Firebolt — single-table reads against article_metrics / channel_metrics
tl db es '<JSON body>'                # Elasticsearch — search bodies against the server-fixed tl-platform alias
```

All three share output flags (`--json`, `--csv`, `--md`, `--toon`) and accept `-` to read the query from stdin (`cat q.sql | tl db fb -`).

**Cost grows non-linearly with result size.** The curve is `cost = setup + mult × 0.126 × n^1.2`, used for `tl db` and every structured `list` endpoint (`tl sponsorships list`, `tl channels list`, `tl uploads list`, `tl snapshots …`, `tl comments list`, `tl reports`). The per-call `setup` is a flat 1 credit for everyone; the per-resource `mult` reflects how heavy that resource is to run server-side:

- **mult = 1.0** — channels, brands, comments, uploads, sponsorships (cheap, indexed reads)
- **mult = 1.2** — snapshots (Firebolt-backed time-series)
- **mult = 1.3** — reports (multi-stage server work)
- **mult = 1.4** — `tl db {pg, fb, es}` (raw queries, no role scoping, wider blast radius)

Per-row cost scales linearly with `mult` at every `n`, so a 1.4× resource is exactly 1.4× the row cost (modulo the 1-credit setup) of a 1.0× resource at any size.

Reference table for raw `tl db {pg,fb,es}` (mult = 1.4):

| Rows returned | Total credits |
|---:|---:|
| 1 | 1 |
| 10 | 4 |
| 50 | 20 |
| 100 | 45 |
| 200 | 103 |
| 500 | 307 |

Implications:
- **Ask for what you need.** A `--limit 50` query is ~15× cheaper than `--limit 500`.
- **Aggregations bill on docs scanned**, not rows returned. ES queries with `aggs` bill on `min(hits.total, 200)` so a `terms` agg over the full index is priced like a medium pull (~103 credits at db's 1.4× mult), not free.
- **Splitting one big call into many small ones is cheaper** but only modestly (10×50 rows ≈ 200 credits vs 1×500 ≈ 307 at db rates — about 35% saved, of which most is from amortising 10 setup floors). Don't over-rotate to micro-batches; the right move is usually "narrow the query".
- **Detail / similar / history endpoints are still linear** (`rate × results`) — only `list`-mode endpoints and `tl db` are on the curve.

**Reach for raw queries — don't simulate them client-side.** Structured `tl <resource> list` is great when the user wants a filtered list of records. The moment the question turns into **aggregation, joining, or complex multi-condition filtering**, switch to `tl db`:

- **Aggregations** (counts, sums, avgs, group-bys, percentiles, time histograms) — push them into a single `tl db es` agg query or a `tl db pg` `GROUP BY` rather than paginating thousands of records and folding them in `jq`/Python. One server-side aggregation is faster, cheaper in credits (one call vs N pages), and avoids `from+size=10000` deep-pagination caps in ES.
- **Joins** — anything that asks "X plus the related Y" (deals plus the campaign, channels plus their adspots' price stats, brands plus the orgs that own them) belongs in `tl db pg` once it ships. Until then, doing the join client-side via two paginated `tl <resource> list` walks is the workaround — but flag it as a workaround, not the right answer.
- **Complex filtering** that the structured filter vocabulary can't express (compound boolean conditions, `NOT IN`/`EXISTS`, `WHERE col IS NULL` on fields not exposed as filters, mixed range + enum + text predicates) — write it as one query rather than over-fetching and post-filtering. Same credit/perf argument.
- **One server query > many client-side roll-ups.** If you find yourself thinking "fetch all, then aggregate", that's the cue to write a `tl db` query instead.

The structured commands stay best for: single-record lookups, role-scoped lists with simple filters, anything with a `tl <resource> show <id>` shape, and anything where the breadcrumbs/role-scoping matter to the answer.

## When to use raw queries vs structured commands

| Need | Use |
|---|---|
| Single-record detail lookup | `tl <resource> show <id>` |
| Simple filtered list of records | Structured `tl <resource> list` |
| Channel/brand similarity, history | `tl channels similar / history`, `tl brands similar / history` |
| Saved reports | `tl reports`, `tl reports run` |
| Time-series view-curve / channel growth (default shape) | `tl snapshots channel`, `tl snapshots video` |
| **Aggregations** (counts, sums, group-by, histograms, percentiles) | **`tl db es` agg query** or **`tl db pg` `GROUP BY`** — do not paginate-and-roll-up client-side |
| **Joins / cross-table data** | **`tl db pg`** (when shipped) — until then, two paginated structured walks is a workaround |
| **Complex filtering** the structured filters can't express (compound bool, `NOT IN`, IS NULL on hidden cols, mixed predicates) | **`tl db pg` / `tl db es`** rather than over-fetching and post-filtering |
| Transcript / brand-mention search inside video content | `tl db es` (no structured equivalent for content text) |
| Custom Firebolt shape (milestone-age slices, multi-channel growth comparisons) | `tl db fb` |
| Anything requiring a Postgres column the structured commands don't expose | `tl db pg` — **currently unavailable, see Limitations** |

## Workflow

1. **Discover.** `tl help` lists all commands. `tl whoami` shows your scoping. `tl describe show <resource> --json` lists fields/filters/credit costs for any resource.
2. **Try structured first.** It's cheaper, role-scoped, and paginated correctly.
3. **Drop to `tl db` only when needed.** Read the relevant schema reference (below) before composing the query.
4. **Always `--json` for parsing.** Pipe to `jq` or load into Python from `/tmp` for any non-trivial analysis.
5. **Pagination still applies.** `tl <resource> list` defaults to 50 results; pass `--limit` (≤500) and `--offset` and loop until you've drained `total`.
6. **Always sanity-check shape with `--limit 1` first** before fanning out a paginated loop or piping into `jq`.

## Raw query reference

### `tl db es` — Elasticsearch

The CLI POSTs your JSON body to `/api/cli/v1/raw/es`. The server validates the body before forwarding to ES.

```bash
# Find a single video by composite ID
tl db es '{"size":1,"query":{"term":{"id":"1247603:8LskGvKUA9I"}}}'

# Aggregation: count sponsored mentions of brand 5612
tl db es '{
  "size":0,
  "track_total_hits":true,
  "query":{"term":{"sponsored_brand_mentions":"5612"}}
}'

# Pipe a larger body from a file
cat query.json | tl db es -
```

The index is fixed server-side (defaults to `tl-platform`) — the client cannot select it. To narrow a query to a quarter or year, scope it inside the body with a `publication_date` range filter rather than picking a different alias.

**Server-side restrictions** (sanitizer in `db_sanitizer.sanitize_es_query`):
- Top-level keys allowed: `query`, `aggs`/`aggregations`, `sort`, `_source`, `size`, `from`, `track_total_hits`, `highlight`, `fields`, `min_score`, `search_after`, `timeout`, `collapse`, `post_filter`. Anything else (`scroll`, `pit`, `runtime_mappings`, `knn`, …) is rejected.
- `size` ≤ 500. `from + size` ≤ 10,000 (deep pagination cap — use `search_after` for deeper).
- Body depth ≤ 16, total node count ≤ 1,000.
- **Blocked query types:** `has_child`, `has_parent`, `parent_id`, `query_string`, `regexp`, `more_like_this`, `fuzzy`, `wildcard`. `nested` is allowed.
- **No scripts of any kind** — any key whose lowercased name contains `script` is rejected. That kills `script_score`, `script_fields`, `scripted_metric`, runtime-script mappings, and `_script` sort.
- **At most one aggregation total**, counted recursively (so a top-level agg with a sub-agg is two and gets rejected). For multi-metric work, run multiple queries.

### `tl db fb` — Firebolt

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

**Server-side restrictions** (`db_sanitizer.sanitize_firebolt_sql`):
- **SELECT only.** No DDL/DML/transactions/locks/SET.
- **Single table.** No JOINs, CTEs (`WITH`), subqueries, set operations, or `LATERAL`.
- **Only known tables:** `article_metrics` (indexed on `channel_id, id`) or `channel_metrics` (indexed on `id`). New tables must be added server-side.
- **WHERE/HAVING may only reference the table's indexed columns** — i.e. `channel_id` / `id` for `article_metrics`, `id` for `channel_metrics`. Filtering by `age`, `publication_date`, `view_count`, etc. in WHERE is rejected with `NON_INDEXED_FILTER:<col>`. Apply those constraints **after** fetching, in `jq`/Python.
- **Leading index column must be equality-or-IN-filtered with literals.** For `article_metrics` that's `channel_id = N` or `channel_id IN (...)`. Without it: `MISSING_INDEXED_FILTER`.
- **Trivial-aggregation exception:** a SELECT whose projected expressions are all aggregates with no GROUP BY / HAVING may omit WHERE entirely. Don't rely on this for anything but tiny check-counts.
- **No LIMIT/OFFSET requirement** (unlike the PG sanitizer), but the underlying engine will still time out on bad plans — keep the leading-index filter selective.

**ID format reminder:** `article_metrics.id` is the bare YouTube video ID (`'dQw4w9WgXcQ'`), not the compound `channel_id:video_id` used in Postgres `adlink.article_id` and ES `_id`. When bridging from Postgres, use `SPLIT_PART(article_id, ':', 2)`.

### `tl db pg` — PostgreSQL

**Currently a server-side stub — POSTs return HTTP 501.** The endpoint accepts the same shape as the others (`{"query": "<sql>"}`) and the CLI is wired up, but the server view returns "not yet implemented" until execution + the strict PG sanitizer ship.

When it does ship, the planned restrictions (per `db_sanitizer.sanitize_pg_sql`):
- **SELECT only**, single statement, no DDL/DML/transactions/SET/COPY/MERGE.
- Function calls gated by an explicit allowlist (aggregates, window, string, JSON, math, date-time, array). No catalog-introspection casts (`::regclass`, `::regprocedure`, …).
- **`LIMIT` is mandatory** and must be an integer literal ≤ 500. **`OFFSET` is mandatory** (use `0` if you don't need to page).
- Max SQL length 50,000 chars. AST depth ≤ 64, node count ≤ 5,000.

**Until PG raw queries land,** answer Postgres-shaped questions through the high-level `tl` commands (which already cover sponsorships/channels/brands/profiles/orgs with role scoping). For things those don't expose — see Limitations below.

## Three sources, each authoritative for different things

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

## Schema references

Load these on demand — don't read all upfront. Pick the one(s) relevant to the question.

- [references/postgres-schema.md](references/postgres-schema.md) — tables, columns, relationships, `publish_status` constants. Useful even today for understanding what the structured `tl` commands return; required reading when `tl db pg` ships.
- [references/elasticsearch-schema.md](references/elasticsearch-schema.md) — index aliases, video/channel fields, common query bodies for `tl db es`.
- [references/firebolt-schema.md](references/firebolt-schema.md) — the two metric tables and their indexes; how to write valid `tl db fb` queries.
- [references/business-glossary.md](references/business-glossary.md) — business terms mapped to database concepts (revenue, weighted pipeline, MSN, TPP, performance grade, team rosters).

## Key business concepts (quick recap)

- **AdLink** = a deal/sponsorship. Source-of-truth table is `thoughtleaders_adlink` (Postgres); the CLI exposes it as `tl sponsorships`.
- **Revenue** = ONLY `publish_status = 3` (SOLD). Everything else is pipeline or lost.
- **Gross revenue** = `SUM(price)` on sold deals. **Net/profit** = `SUM(price - cost)`.
- **Weighted pipeline** = `SUM(weighted_price)` on open opportunities (statuses 0,2,6,7,8). Pre-computed in PG.
- **Closed-lost** = `publish_status IN (4, 5, 9)`.
- **Ad is live on YouTube** = `publish_date IS NOT NULL`. Until then, even sold deals can be canceled.
- **`owner_sales_id`** on adlink = ultimate revenue accountability.
- **Adspots** are catalogue entries (list price/cost). The adlink carries the actual deal price/cost.
- **MSN** (Media Selling Network) = channels with `media_selling_network_join_date IS NOT NULL`. **TPP** = `is_tl_channel = true`.

See [references/business-glossary.md](references/business-glossary.md) for the full mapping plus team rosters.

## Limitations vs the original `tl-data` skill

The original skill connected to PG/ES/Firebolt directly. Going through `tl` exclusively means some things the old skill could do are not currently expressible:

| Original capability | Status under `tl`-only | Workaround |
|---|---|---|
| Arbitrary read-only `SELECT` on Postgres (any joins, any tables, `information_schema` introspection) | **Unavailable** — `tl db pg` is a server-side stub (HTTP 501). | Use the structured `tl sponsorships / channels / brands / reports` commands. They cover the majority of business questions, with role scoping the raw queries don't have. For the rest, wait for `tl db pg` to ship — or ask a human to run the SQL. |
| Cross-reference / source-query helpers (`resolve_cross_refs.py`: "channels proposed to brand X", "channels sponsored by MBN brands in last N days") | **Unavailable** — these were stacked PG joins through `adlink → adspot → profile → profile_brands → brand`. | Approximate with `tl brands history <brand>` (returns videos where the brand was detected → extract channel IDs) and `tl sponsorships list brand:<name> status:<...>`. Won't perfectly match the old logic (e.g. MBN/`media_buying_network_join_date` isn't exposed). |
| **AdLink INSERT** with custom price/cost/owner/`weighted_price`/`created_where` (RLS-enforced) | **Unavailable** — `tl sponsorships create` exists but only creates a free *proposal* between a channel and a brand. It does not let you set price/cost/owner_sales_id/send_date/etc., and there's no other write path through the CLI. | None inside this skill. Done in the app or by a human with DB access. |
| Pre-insert validation queries (joining `adspot ↔ channel ↔ profile ↔ org` to confirm MSN, integration=1, persona, plan) | **Unavailable** as a single query (needs PG joins). | Partial: `tl channels show <id>` exposes `msn`, `tpp`, and active adspots with `integration` codes. Persona/plan/profile-level checks aren't surfaced. |
| Firebolt cross-table or join queries; filtering on non-indexed columns in WHERE | **Unavailable** — sanitizer forbids JOINs/CTEs/subqueries and rejects WHERE/HAVING references to non-indexed columns. | Fetch a wider slice keyed on `channel_id` (and optionally `id`), filter the rest in `jq`/Python. |
| ES `query_string`, `regexp`, `wildcard`, `fuzzy`, `more_like_this`, parent/child joins; any `script_*`; multiple aggregations in one body | **Unavailable** — sanitizer-blocked. | Rewrite using `term`/`terms`/`match`/`bool`/`nested` queries. For multi-agg dashboards, run multiple `tl db es` calls and combine client-side. For "similar"-style queries, try `tl channels similar` / `tl brands similar` (vector KNN, server-implemented). |
| ES deep pagination beyond `from+size = 10,000` | **Unavailable** via raw — `scroll` and `pit` aren't in the top-level allowlist; `search_after` is allowed but `from` is still capped. | Use `search_after` with `sort` to walk past 10k. For huge sweeps, narrow the index (`tl-platform-{year}-q{quarter}`) and add `publication_date` ranges. |
| ES index introspection (`_cat/indices`, mappings) | **Unavailable** — only `_search` is wired. | Read [references/elasticsearch-schema.md](references/elasticsearch-schema.md). It's manually maintained — update it when you discover new fields. |
| Schema introspection on Postgres (`information_schema.columns`, `pg_class`, …) | **Unavailable** until `tl db pg` ships, and even then catalog-resolving casts and many `pg_*` helpers are blocked. | Read [references/postgres-schema.md](references/postgres-schema.md). |
| Free-form `--format table/csv/json` over arbitrary results | **Available** — `tl db {pg,fb,es}` honours `--json`/`--csv`/`--md`/`--toon` like every other `tl` command. ES `aggregations` are rendered after the result rows in TTY/csv/md modes and included in the envelope under `--json`. | — |

If a user asks for one of the **Unavailable** items, say so explicitly and propose the closest `tl`-based approximation rather than silently degrading.
