# ThoughtLeaders Elasticsearch Schema Reference

## How to query

All ES access goes through the `tl` CLI:

```bash
tl db es '{"size": 1, "query": {"match_all": {}}}' --json

# Read body from stdin
cat query.json | tl db es -
```

The index is **fixed server-side**. The client cannot select an index — there is no `--index` flag.

Cost grows non-linearly with result size (raw db queries use the list curve at `mult=1.4`). Aggregation queries bill on `min(hits.total, 200)` instead of `len(hits)`. See `SKILL.md` for the curve formula and the row-count → credits table.

Output flags: `--json`, `--csv`, `--md`, `--toon`. The CLI flattens hits into rows of `{_id, _score, ...source}`; aggregations come back in the response envelope and are rendered after the rows in TTY mode.

## Accepted query bodies

See the output of `tl db es`" for the object schema. Highlights:

- **Top-level keys** accepted: `query`, `aggs`/`aggregations`, `sort`, `_source`, `size`, `from`, `track_total_hits`, `highlight`, `fields`, `min_score`, `search_after`, `timeout`, `collapse`, `post_filter`. Anything else (incl. `scroll`, `pit`, `runtime_mappings`, `knn`) is not accepted.
- `size` ≤ 500. `from + size` ≤ 10,000. Use `search_after` to page deeper.
- **Accepted query types** include `term`/`terms`/`match`/`bool`/`nested`/`range`/`exists`/`match_phrase`. `query_string`, `regexp`, `wildcard`, `fuzzy`, `more_like_this`, `has_child`, `has_parent`, `parent_id` are not accepted.
- **No scripts** — any key whose name contains `script` is not accepted.
- **At most one aggregation total** counted recursively (top-level + sub-agg = 2 = not accepted). Run multiple calls for multi-metric work.

### ElasticSearch document structure ("articles")

The `doc_type` join field distinguishes video uploads ("articles") from channel data — channel docs are parents, article docs are their children. Filter with `{"term": {"doc_type": "article"}}` or `{"term": {"doc_type": "channel"}}`. ⚠️ Term-querying `doc_type.name` matches nothing — even though article docs' `_source` shows `doc_type` as an object with a `name` key, that's join-field syntax, not a queryable subfield.

#### Upload/video Fields (selected — 73 total)

Filter with `{"term": {"doc_type": "article"}}`.

| Field | Type | Description |
|-------|------|-------------|
| `id` | keyword | Video/article ID. Compound form `<channel_id>:<youtube_id>` (matches PG `adlink.article_id` and ES `_id`). |
| `title` | text | Video title |
| `description` | text | Video description |
| `content` | text | Full content/transcript text |
| `transcript` | text | Raw transcript |
| `transcript_language` | keyword | Transcript language code |
| `summary` | text | AI-generated summary |
| `publication_date` | date | When video was published |
| `discovery_time` | date | When TL discovered/indexed it |
| `url` | object | Video URL |
| `image_url` | object | Thumbnail URL |
| `views` | long | View count |
| `total_views` | long | Total views |
| `projected_views` | long | Projected views |
| `likes` | long | Like count |
| `comments` | integer | Comment count |
| `engagement` | long | Engagement metric |
| `duration` | integer | Duration in seconds |
| `duration_live` | integer | Live stream duration |
| `duration_longform` | integer | Long-form duration |
| `duration_shorts` | integer | Shorts duration |
| `content_type` | keyword | longform / short / live |
| `content_category` | keyword | Content category |
| `content_aspects` | keyword | Content features/aspects |
| `language` | keyword | Content language |
| `country` | keyword | Creator country |
| `format` | keyword | Platform format |
| `hashtags` | keyword | Hashtags used |
| `face_on_screen` | boolean | Whether creator shows face |

#### Brand Mention Fields

| Field | Type | Description |
|-------|------|-------------|
| `brand_mentions` | nested | Full brand mention objects |
| `all_brand_mentions` | keyword | All brand IDs mentioned |
| `sponsored_brand_mentions` | keyword | Sponsored brand IDs |
| `organic_brand_mentions` | keyword | Organic brand IDs |
| `banner_ads` | object | Banner ad data |
| `not_sponsored_by` | object | Explicitly not sponsored by |

#### Channel Fields

Filter with `{"term": {"doc_type": "channel"}}`.

Contains a denormalized subset of the PostgreSQL channel data.

### Channel fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | text | Channel name |
| `channel` | object | Channel metadata (nested on article docs) |
| `reach` | long | Subscriber count. ⚠️ NOT ad-industry "reach" (unique audience exposed) — this is the channel's subscriber count. |
| `impression` | long | Projected views per longform video — forward-looking estimate. ⚠️ NOT actual views and NOT ad-industry "impressions"; for actual views see `total_views` / the video docs. |
| `impression_live` | long | Projected views per live stream (forward-looking estimate) |
| `impression_shorts` | long | Projected views per short (forward-looking estimate) |
| `is_tl_channel` | boolean | TPP partner channel |
| `is_active` | boolean | Channel is active |
| `media_selling_network_join_date` | date | MSN join date |
| `has_outreach_email` | boolean | Has outreach email |
| `outreach_email` | text | Contact email |
| `social_links` | text | Social media links |
| `male_share` | byte | Male audience % |
| `usa_share` | byte | US audience % |
| `sponsorship_price` | scaled_float | Sponsorship price |
| `sponsorship_score` | scaled_float | Sponsorship quality score |
| `evergreenness` | float | Evergreen score |
| `evergreenness_live` | scaled_float | Live evergreen score |
| `evergreenness_longform` | scaled_float | Longform evergreen score |
| `evergreenness_shorts` | scaled_float | Shorts evergreen score |
| `trend` | float | Growth trend |
| `trend_live` | scaled_float | Live trend |
| `trend_shorts` | scaled_float | Shorts trend |
| `posts_per_90_days` | integer | Upload frequency |
| `posts_per_90_days_live` | integer | Live frequency |
| `posts_per_90_days_shorts` | integer | Shorts frequency |
| `fulfillment_rate` | scaled_float | Fulfillment rate |
| `renewal_rate` | scaled_float | Renewal rate |
| `metrics_update_period` | byte | How often metrics update |
| `offline_since` | date | When channel went offline |

#### AI & Enrichment Fields

| Field | Type | Description |
|-------|------|-------------|
| `ai` | object | AI-generated metadata |
| `applied_enrichments` | keyword | Which enrichments have been applied |
| `article_category` | object | Categorization data |

#### System Fields

| Field | Type | Description |
|-------|------|-------------|
| `@timestamp` | date | Index timestamp |
| `doc_type` | join | Parent-child join (channel→video) |
| `es_index_tag` | object | Index routing metadata |

## Common Query Patterns

### Search videos by sponsored brand mention

```bash
tl db es '{
  "size": 50,
  "query": {"term": {"sponsored_brand_mentions": "5612"}},
  "_source": ["title", "channel.id", "publication_date", "views"],
  "sort": [{"publication_date": "desc"}]
}'
```

### Search videos for a single channel

```bash
tl db es '{
  "size": 100,
  "query": {"term": {"channel.id": 12345}},
  "sort": [{"publication_date": "desc"}]
}'
```

### Count sponsored mentions for a brand (size:0 + track_total_hits)

```bash
tl db es '{
  "size": 0,
  "track_total_hits": true,
  "query": {"term": {"sponsored_brand_mentions": "5612"}}
}'
```

### Full-text search on title/description/summary/content

```bash
tl db es '{
  "size": 20,
  "query": {
    "multi_match": {
      "query": "ergonomic keyboard review",
      "fields": ["title^3", "description", "summary", "content"]
    }
  },
  "_source": ["title", "channel.id", "publication_date"]
}'
```

### Filter by date range

```bash
tl db es '{
  "size": 100,
  "query": {
    "bool": {
      "filter": [
        {"term": {"channel.id": 12345}},
        {"range": {"publication_date": {"gte": "2026-01-01", "lte": "2026-03-31"}}}
      ]
    }
  }
}'
```

### Single top-level aggregation (only one aggregation per request is accepted)

```bash
tl db es '{
  "size": 0,
  "aggs": {
    "by_channel": {
      "terms": {"field": "channel.id", "size": 20}
    }
  },
  "query": {"term": {"sponsored_brand_mentions": "5612"}}
}'
```

For more dimensions, run multiple `tl db es` calls and join client-side.

### Deep pagination via `search_after`

```bash
# First page — sort must include a tiebreaker on _id for stability
tl db es '{
  "size": 500,
  "query": {"term": {"channel.id": 12345}},
  "sort": [{"publication_date": "desc"}, {"_id": "asc"}]
}'

# Subsequent pages — pass the last hit's sort values as search_after
tl db es '{
  "size": 500,
  "query": {"term": {"channel.id": 12345}},
  "sort": [{"publication_date": "desc"}, {"_id": "asc"}],
  "search_after": ["2025-09-14", "12345:abc123"]
}'
```

## Text analyzer behavior

`text` fields on article docs (`title`, `summary`, `transcript`) appear to use the `standard` analyzer (tokenize + lowercase, no stemmer, no English-possessive filter), so inflections, plurals, and possessives are each indexed as distinct terms. For example: `bitcoin` (4,466,300) vs `bitcoins` (489,262). For stemming-style recall, expand the query side with a `bool.should` over the variants.

## Notes & gotchas

- **Composite IDs:** `tl-platform.id` and `_id` are `<channel_id>:<youtube_id>`. The `youtube_id` portion alone is what Firebolt's `article_metrics.id` stores.
- **Add a `publication_date` range filter** whenever the question is time-bounded — the alias is fixed, so this is the only way to narrow the search.
- `sponsored_brand_mentions` and `organic_brand_mentions` are keyword arrays — use `term` queries.
- For brand mention details (position, snippet, detection_tool), the data is in the `brand_mentions` nested field.
- **`publication_id` is deprecated** — don't use for joins.
- No write access. The CLI only exposes `_search` against `tl-platform-*`.
