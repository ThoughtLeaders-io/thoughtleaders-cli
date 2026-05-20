# ThoughtLeaders CLI — HTTP API

The same endpoints `tl` calls under the hood are reachable directly with `curl` or any HTTP client. This page documents the subset most useful for scripting and BI integrations:

- [`GET /whoami`](#whoami) — current user, profile, org, brands
- [`GET /balance`](#balance) — credit balance + recent usage
- [`POST /raw/pg`](#db-pg) — read-only PostgreSQL `SELECT`
- [`POST /raw/es`](#db-es) — Elasticsearch search body
- [`POST /raw/fb`](#db-fb) — read-only Firebolt `SELECT`
- [`GET /raw/pg/schema`](#schema-pg) — PostgreSQL schema reference
- [`GET /raw/es/schema`](#schema-es) — Elasticsearch document shape
- [`GET /raw/fb/schema`](#schema-fb) — Firebolt schema reference

The full surface is larger (sponsorships, channels, brands, recommender, reports, …). Run `tl describe` from a logged-in CLI for the complete list.

## Base URL & auth

```
Base URL:   https://app.thoughtleaders.io/api/cli/v1
```

All requests must carry both of:

| Header | Value | Why |
| --- | --- | --- |
| `Authorization` | `Bearer <api_key>` | The credential. |
| `X-TL-Auth` | `API-KEY` | Opts into API-key auth. Without it the server interprets the Bearer as an Auth0 JWT and rejects the API-key string. |

Inactive or expired keys return `401`; if the owning user is deactivated the request fails with `403`.

A quick set of shell variables used throughout this page:

```bash
export TL_API_BASE='https://app.thoughtleaders.io/api/cli/v1'
export TL_API_KEY='<your 64-char hex key>'

auth() {
  printf 'Authorization: Bearer %s\nX-TL-Auth: API-KEY\n' "$TL_API_KEY"
}
```

And the Python equivalent (uses `requests`; works the same with `httpx`):

```python
import os
import requests

BASE = 'https://app.thoughtleaders.io/api/cli/v1'
KEY = os.environ['TL_API_KEY']
HEADERS = {
    'Authorization': f'Bearer {KEY}',
    'X-TL-Auth': 'API-KEY',
}

def get(path, params=None):
    r = requests.get(f'{BASE}{path}', headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def post(path, body):
    r = requests.post(f'{BASE}{path}', headers=HEADERS, json=body, timeout=60)
    r.raise_for_status()
    return r.json()
```

## Response envelope

Multi-row responses share one shape:

```json
{
  "results": [ ... rows ... ],
  "total": 1234,
  "limit": 500,
  "offset": 0,
  "usage": {
    "credits_charged": 4.12,
    "credit_rate": 1.4,
    "balance_remaining": 9995.88
  },
  "_breadcrumbs": [
    { "hint": "next page", "command": "..." }
  ]
}
```

- **`results`** is always a list (even for single-row responses).
- **`usage`** is on every metered response. Free endpoints (`whoami`, `balance`, schema) report `credits_charged: 0`.
- **`_breadcrumbs`** is advisory next-step hints; ignore in production scripts.

Error responses are JSON: `{"detail": "<reason>"}`, sometimes with extra structural fields (`reason` for `db/pg` sanitizer rejections, `candidates` for ambiguous-match endpoints, `queued_*` for the channels-find scrape-queue path).

---

## whoami

`GET /whoami` — current user, profile flags, organization, associated profiles, and (for buyers) brands. Free.

```bash
curl -sS "$TL_API_BASE/whoami" \
  -H "Authorization: Bearer $TL_API_KEY" \
  -H 'X-TL-Auth: API-KEY' | jq
```

```python
print(get('/whoami'))
```

```json
{
  "user": {
    "id": 4221,
    "email": "alice@thoughtleaders.io",
    "first_name": "Alice",
    "last_name": "Roe",
    "date_joined": "2024-08-11T12:18:43+00:00"
  },
  "profile": {
    "id": 9117,
    "flags": ["advertiser"],
    "is_paid": true,
    "persona": "Brand",
    "created_at": "2024-08-11T12:18:43+00:00"
  },
  "organization": {
    "id": 311,
    "name": "Acme Marketing",
    "plan": "Intelligence",
    "is_managed_services": false,
    "credits_balance": 9995.88
  },
  "associated_profiles": [ ... ],
  "brands": [ ... ]
}
```

Useful for verifying the API key resolves to the user you expect before kicking off a longer script.

---

## balance

`GET /balance` — credit balance plus the last 10 metered calls for the org. Free.

```bash
curl -sS "$TL_API_BASE/balance" \
  -H "Authorization: Bearer $TL_API_KEY" \
  -H 'X-TL-Auth: API-KEY' | jq
```

```python
print(get('/balance'))
```

```json
{
  "balance": 9_995.88,
  "allow_overage": false,
  "recent_usage": [
    {
      "date": "2026-05-19T14:02:11+00:00",
      "resource": "db_pg",
      "results_count": 500,
      "credits_charged": 33.41
    },
    ...
  ]
}
```

---

## db pg

`POST /raw/pg` — execute a read-only PostgreSQL `SELECT`. Sanitised: SELECT only, no DDL/DML/transactions, `LIMIT ≤ 500`, function allowlist (aggregates, window, string, JSON, math, date/time, array). `OFFSET ≥ 10 000` is rejected with `OFFSET_TOO_DEEP` — paginate with the response's `next_offset` instead.

Body: `{"query": "<sql>"}`.

```bash
curl -sS "$TL_API_BASE/raw/pg" \
  -H "Authorization: Bearer $TL_API_KEY" \
  -H 'X-TL-Auth: API-KEY' \
  -H 'Content-Type: application/json' \
  -d '{
        "query": "SELECT id, channel_name, reach FROM thoughtleaders_channel WHERE is_tl_channel = TRUE ORDER BY reach DESC LIMIT 5 OFFSET 0"
      }' | jq
```

```python
sql = """
SELECT id, channel_name, reach
FROM thoughtleaders_channel
WHERE is_tl_channel = TRUE
ORDER BY reach DESC
LIMIT 5 OFFSET 0
"""
print(post('/raw/pg', {'query': sql}))
```

```json
{
  "results": [
    {"id": 12345, "channel_name": "MrBeast", "reach": 320000000},
    ...
  ],
  "total": 5,
  "limit": 5,
  "offset": 0,
  "usage": { "credits_charged": 1.84, "credit_rate": 1.4, "balance_remaining": 9994.04 }
}
```

### Pricing

PG cost is **per-query**: a base rate plus a surcharge for every priced table and column referenced. Most tables/columns are free; sensitive ones (demographics, channel outreach emails) cost more. The `usage.credit_rate` you get back is the effective multiplier the server applied — it's not the static value from `tl describe`. The `pricing` sub-key, when present, breaks the rate into base/per-table/per-column components.

### Common rejections

- `MISSING_LIMIT` / `LIMIT_TOO_HIGH` — always include `LIMIT N` with `N ≤ 500`.
- `INSERT` / `UPDATE` / `DELETE` / `CREATE` / `DROP` — sanitiser is SELECT-only.
- `LEAKY_CAST` — `::regclass`, `::regprocedure`, etc. are blocked.
- `OFFSET_TOO_DEEP` — paginate via the next-page breadcrumb instead of jumping past 10 000.

Run `GET /raw/pg/schema` (below) or `tl schema pg` for the live column catalogue. SELECT-only schema introspection (`information_schema.columns`, most `pg_*` helpers) is blocked by the sanitiser; use the schema endpoint instead.

---

## db es

`POST /raw/es` — execute an Elasticsearch search against the `tl-platform` index family (videos / channels). Accepts the standard ES query body.

Body: `{"query": <es_body>}` — either a JSON object or a JSON-encoded string in `query`.

```bash
curl -sS "$TL_API_BASE/raw/es" \
  -H "Authorization: Bearer $TL_API_KEY" \
  -H 'X-TL-Auth: API-KEY' \
  -H 'Content-Type: application/json' \
  -d '{
        "query": {
          "size": 20,
          "query": {"term": {"sponsored_brand_mentions": "5612"}},
          "_source": ["title", "channel.id", "publication_date", "views"]
        }
      }' | jq
```

```python
es_body = {
    "size": 20,
    "query": {"term": {"sponsored_brand_mentions": "5612"}},
    "_source": ["title", "channel.id", "publication_date", "views"],
}
print(post('/raw/es', {'query': es_body}))
```

### Accepted query bodies

The server forwards bodies built from `term`, `terms`, `match`, `bool`, `nested`, `range`, `exists`, and standard aggregations. The following are not accepted:

- `query_string`, `regexp`, `wildcard`, `fuzzy`, `more_like_this`
- parent/child joins
- any `script_*`
- multiple aggregations in one body (run multiple calls and combine client-side)

Deep pagination via `scroll` / `pit` is unavailable — use `search_after` with `sort` to walk past 10 000.

---

## db fb

`POST /raw/fb` — execute a read-only Firebolt `SELECT` against the historical-metrics tables (`article_metrics`, `channel_metrics`). Mandatory: queries against `article_metrics` must filter by `channel_id` (and ideally `id`); without it the index requirement fails with `MISSING_INDEXED_FILTER`. `channel_metrics` requires filtering by `id`.

Body: `{"query": "<sql>"}`.

```bash
curl -sS "$TL_API_BASE/raw/fb" \
  -H "Authorization: Bearer $TL_API_KEY" \
  -H 'X-TL-Auth: API-KEY' \
  -H 'Content-Type: application/json' \
  -d '{
        "query": "SELECT id, age, view_count FROM article_metrics WHERE channel_id = 12345 AND id IN ('abc', 'def') ORDER BY id, age"
      }' | jq
```

```python
sql = """
SELECT id, age, view_count
FROM article_metrics
WHERE channel_id = 12345 AND id IN ('abc', 'def')
ORDER BY id, age
"""
print(post('/raw/fb', {'query': sql}))
```

### Workflow note

A typical Firebolt workflow has two steps:

1. Resolve `channel_id` (and optionally video IDs) via `POST /raw/pg` or `POST /raw/es`.
2. Query Firebolt with those IDs.

Calling Firebolt without an indexed filter is rejected before the query runs.

---

## schema pg

`GET /raw/pg/schema` — Markdown-rendered PostgreSQL schema. Free. Pass `?table=<name>` to scope to a single table (matches the `tl schema pg <table>` shape and is dramatically smaller).

```bash
curl -sS "$TL_API_BASE/raw/pg/schema?table=thoughtleaders_channel" \
  -H "Authorization: Bearer $TL_API_KEY" \
  -H 'X-TL-Auth: API-KEY' | jq -r '.content' | less
```

```python
schema = get('/raw/pg/schema', params={'table': 'thoughtleaders_channel'})
print(schema['content'])    # markdown body
```

Response:

```json
{
  "name": "pg",
  "description": "PostgreSQL schema reference for `POST /raw/pg`",
  "content_type": "markdown",
  "content": "# PostgreSQL Schema Reference\n\n..."
}
```

Always pull the table-scoped form when you know which table you need — the unscoped form lists every visible table and is much larger.

---

## schema es

`GET /raw/es/schema` — Markdown reference for the Elasticsearch `tl-platform` index document shape. Free. **No `?table=` parameter** — Elasticsearch is one document shape; passing one returns `400`.

```bash
curl -sS "$TL_API_BASE/raw/es/schema" \
  -H "Authorization: Bearer $TL_API_KEY" \
  -H 'X-TL-Auth: API-KEY' | jq -r '.content' | less
```

```python
print(get('/raw/es/schema')['content'])
```

---

## schema fb

`GET /raw/fb/schema` — Markdown reference for the two Firebolt tables (`article_metrics`, `channel_metrics`). Free. Pass `?table=article_metrics` or `?table=channel_metrics` to scope.

```bash
curl -sS "$TL_API_BASE/raw/fb/schema?table=article_metrics" \
  -H "Authorization: Bearer $TL_API_KEY" \
  -H 'X-TL-Auth: API-KEY' | jq -r '.content'
```

```python
print(get('/raw/fb/schema', params={'table': 'article_metrics'})['content'])
```

---

## End-to-end example

Find Holafly's most-viewed sponsored videos in the past 6 months, then pull their view-curves from Firebolt:

```python
import os, requests

BASE = 'https://app.thoughtleaders.io/api/cli/v1'
H = {'Authorization': f"Bearer {os.environ['TL_API_KEY']}", 'X-TL-Auth': 'API-KEY'}

def post(path, body):
    r = requests.post(f'{BASE}{path}', headers=H, json=body, timeout=60)
    r.raise_for_status()
    return r.json()

# 1) Find Holafly's brand id (free name lookup endpoint covered elsewhere — use db_pg here)
brand = post('/raw/pg', {'query':
    "SELECT id FROM thoughtleaders_brand WHERE name = 'Holafly' LIMIT 1 OFFSET 0"
})['results'][0]['id']

# 2) Pull the top Holafly-sponsored videos from ES, ranked by views.
es_resp = post('/raw/es', {'query': {
    'size': 0,
    'query': {'term': {'sponsored_brand_mentions': str(brand)}},
    'aggs': {'top_videos': {
        'terms': {'field': '_id', 'size': 10, 'order': {'max_views': 'desc'}},
        'aggs': {'max_views': {'max': {'field': 'views'}}},
    }},
}})
video_ids = [b['key'] for b in es_resp['results'][0]['aggregations']['top_videos']['buckets']]

# 3) Each video id is `<channel_id>:<youtube_id>` — split for the Firebolt query.
pairs = [vid.split(':') for vid in video_ids]
channel_ids = sorted({int(c) for c, _ in pairs})
youtube_ids = [y for _, y in pairs]

fb_resp = post('/raw/fb', {'query': f"""
    SELECT id, channel_id, age, view_count
    FROM article_metrics
    WHERE channel_id IN ({','.join(map(str, channel_ids))})
      AND id IN ({','.join(repr(y) for y in youtube_ids)})
    ORDER BY channel_id, id, age
"""})

for row in fb_resp['results']:
    print(row)
```

The same shape works with the synchronous `httpx` client; swap `requests` for `httpx` and the API is the same.

---

## See also

- [README.md](README.md) — install, the `tl` CLI, agent integrations.
- `tl describe` — discover every endpoint, its fields/filters, and current credit rates.
- `tl schema pg|fb|es [<table>]` — fetch the same schema bodies these endpoints serve.
- `tl doctor` — verify auth and latency against the API base from the CLI before integrating.
