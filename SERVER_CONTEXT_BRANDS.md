# Server Context: Brands CLI Endpoint

This file provides context for a session working on the **thoughtleaders** server repository.
It describes what the `tl-cli` brands command expects from the server API.

## Current State

The CLI has a working `tl brands show <query>` command that calls:

```
GET /api/cli/v1/brands/{query}?limit=50&offset=0
GET /api/cli/v1/brands/{query}?limit=50&offset=0&channel_id=12345
```

This endpoint works. It returns matching channels with sponsored mentions of the queried brand.

**Confirmed working example:**
`tl brands show manscaped` returns channel mentions with fields: `channel`, `mentions`, `type`, `latest_date`, `views`.

## What the CLI Now Needs

### 1. New Endpoint: `GET /api/cli/v1/brands`

The CLI now has a `tl brands list [filters...]` command that calls `GET /api/cli/v1/brands` with query parameters for filtering and pagination. This endpoint does not exist yet on the server.

**Purpose:** Allow users to search and browse brands (e.g., "show me tech brands", "list brands with at least 10 sponsorships") before drilling into a specific brand with `tl brands show`.

**Expected query parameters:**
- `limit` (int, default 50, max 200) — pagination page size
- `offset` (int, default 0) — pagination offset
- `name` (string, optional) — partial match on brand name
- `category` (string, optional) — filter by brand category
- `min-channels` (int, optional) — minimum number of channels with mentions
- `min-sponsorships` (int, optional) — minimum sponsorship count
- `since` (date string, optional) — only brands with activity after this date

**Expected response envelope** (same as all other CLI endpoints):
```json
{
  "results": [
    {
      "name": "Manscaped",
      "category": "Personal Care",
      "channels": 142,
      "sponsorships": 387,
      "latest_activity": "2026-04-01"
    }
  ],
  "total": 1500,
  "limit": 50,
  "offset": 0,
  "usage": {
    "credits_charged": 250,
    "credit_rate": 5,
    "balance_remaining": 4750
  },
  "_breadcrumbs": [
    {
      "hint": "Research a specific brand",
      "command": "tl brands show Manscaped"
    }
  ]
}
```

**Expected result fields per brand:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Brand name |
| `category` | string | Brand category (e.g., "Tech", "Personal Care") |
| `channels` | int | Number of channels with mentions |
| `sponsorships` | int | Total sponsorship count |
| `latest_activity` | date string | Most recent sponsorship or mention date |

### 2. Update `tl describe show brands`

The `/api/cli/v1/describe/brands` endpoint should be updated to include:
- The new `list` action with its filters and fields
- Filter metadata (name, type, description, allowed values) for the list endpoint
- Credit rates for the list endpoint

### 3. Optional Enhancements to Existing Show Endpoint

Consider adding these filter parameters to `GET /api/cli/v1/brands/{query}`:
- `since` (date) — only show mentions after this date
- `until` (date) — only show mentions before this date
- `type` (string) — filter by sponsorship type

These would be exposed as `--since`, `--until`, `--type` flags on the CLI side in a follow-up.

## CLI Validation

The CLI now validates arguments before calling the API:
- `query` (show): must be non-empty, non-whitespace
- `limit`: must be 1–200
- `offset`: must be >= 0
- `channel`: must be > 0 if provided

The server should also validate these on its side and return appropriate error responses (400 for invalid params, 404 for unknown brands, 403 for plans without Intelligence access).

## Reference: Other CLI Endpoints

For consistency, the brands list endpoint should follow the same patterns as:
- `GET /api/cli/v1/channels` — channel search with filters
- `GET /api/cli/v1/sponsorships` — sponsorship list with filters
- `GET /api/cli/v1/uploads` — upload list with filters

All use the same response envelope with `results`, `total`, `limit`, `offset`, `usage`, and `_breadcrumbs`.
