# Tool: database_query (cross-reference query)

A conditional tool invoked by Phase 2 (Schema Phase) when the user's request includes a **cross-reference** condition — a prerequisite filter on sponsorship/proposal history (or arbitrary other-report data) that needs to be applied as include/exclude on the main report.

The tool's job is to compose the **v1-shaped payload** (`cross_references` entry, or `multi_step_query` block) that the backend will resolve at report-execution time. The backend runs the DB lookup; the tool emits the correctly-shaped instruction.

> The mechanism itself isn't new — v1 already supports cross_references and multi_step_query inside the create_report payload. The only thing that changed in v2: this logic is extracted into a dedicated tool file rather than being inlined in the system prompt.

You produce **JSON only**.

---

## Two mechanisms (mirroring v1 exactly)

### 1. `cross_references` — fixed catalog, channels & content reports only

A list of named cross-reference objects at the top level of the report config (alongside `filterset` / `filters_json`). The backend resolves each entry against the database and applies the resulting channel IDs. **Only valid on `report_type ∈ {1, 3}`.**

The catalog is fixed — only these types are supported:

| Type | Purpose | Required fields | Optional fields |
|---|---|---|---|
| `exclude_proposed_to_brand` | Exclude channels that have been proposed/sold to a specific brand | `brand_names` (list of strings) | `statuses` (list of publish_status IDs; default `[0, 2, 3, 6, 7, 8]`) |
| `include_proposed_to_brand` | Only show channels that HAVE been proposed/sold to a brand (re-pitch / upsell) | `brand_names` | `statuses` (default `[0, 2, 3, 6, 7, 8]`) |
| `include_sponsored_by_mbn` | Only show channels with sponsorships from MBN (Media Buying Network) brands — i.e., managed-services advertisers | — | `statuses` (default `[0, 2, 3, 6, 7, 8]`), `days_ago` (default `365`) |

**Deprecated entries** (do NOT emit — use the FilterSet field instead):
- `exclude_msn_channels` → use `filterset.msn_channels_only: false`
- `include_msn_channels` → use `filterset.msn_channels_only: true`

Multiple `cross_references` entries can be combined; each is applied independently.

### 2. `multi_step_query` — flexible source query

For cross-references that need **arbitrary filters** (price ranges, status combos, owner filters, date windows that the named catalog doesn't expose). The source query can be any report type with any filters; the backend runs it, extracts the requested ID set, and applies it to the main report.

```json
{
  "action": "multi_step_query",
  "source_query": {
    "report_type": <int>,           // any: 1, 2, 3, or 8
    "filterset": { ... },           // full FilterSet shape for the source report type
    "filters_json": { ... },        // any filters_json for the source report type
    "extract": "channel_ids"        // currently the only supported extract; reserves space for future
  },
  "main_report": {
    "report_type": <int>,
    "filterset": { ... },
    "columns": { ... },
    "widgets": [ ... ],
    "apply_as": "channels" | "exclude_channels"
    // ... other main-report fields
  }
}
```

**`apply_as`** is the single direction for the whole source-query result — there's no per-entry direction. If you need both inclusion and exclusion from different prerequisites, use one `multi_step_query` for the part that needs flexibility plus `cross_references` entries for the parts the named catalog covers.

---

## When to use which

| Situation | Mechanism |
|---|---|
| "Channels NOT proposed to Brand X" | `cross_references: [{ type: "exclude_proposed_to_brand", brand_names: ["X"] }]` |
| "Channels we've sold to Brand X" (re-pitch) | `cross_references: [{ type: "include_proposed_to_brand", brand_names: ["X"], statuses: [3] }]` |
| "Channels MBN brands are buying" | `cross_references: [{ type: "include_sponsored_by_mbn" }]` (combine with `msn_channels_only: false` to surface non-network channels MBN brands buy — the recruitment use case) |
| "Channels from our 2025 gaming pipeline with >$5K price" | `multi_step_query` — needs price filter + date range that named catalog can't express |
| "Channels with active pipeline sponsorships" | `multi_step_query` — needs date constraint (the named catalog doesn't take dates directly) |
| MSN inclusion / exclusion | NEITHER — use `filterset.msn_channels_only` directly |

**Critical rule from v1**: do NOT use `multi_step_query` when `cross_references` can handle it. The named catalog is purpose-built; reach for `multi_step_query` only when arbitrary filters are required.

---

## Invoke when

The user's request mentions a sponsorship/proposal/pipeline history condition that filters channels for a CONTENT or CHANNELS report:
- "NOT proposed to / haven't been pitched to / exclude channels already proposed to **[brand]**"
- "Channels we've sold to / proposed to / re-pitch **[brand]**"
- "Channels MBN brands are working with"
- "From our [year] [niche] pipeline" (use multi_step_query)
- "With active / live deals" (use multi_step_query — needs date)

Skip when:
- The condition is a name lookup (use `name_resolver`).
- The condition is expressible as a typed FilterSet field (`tl_sponsorships_only`, `msn_channels_only`).
- The main report is type 2 (BRANDS) or type 8 (SPONSORSHIPS) — `cross_references` only applies to types 1 and 3.

---

## Inputs

The caller provides:

1. **`MAIN_REPORT_TYPE`** — `1` or `3` for `cross_references`; can be any type for `multi_step_query`.
2. **`INTENT_NL`** — natural-language description of the cross-reference, e.g. `"exclude channels we've proposed to Logitech in the last 12 months"`.
3. **`MECHANISM`** — `cross_references` | `multi_step_query`. Determined by the table above.
4. **For `cross_references`**: the catalog `type`, plus `brand_names` / `statuses` / `days_ago` per the type's schema.
5. **For `multi_step_query`**: the full `source_query` shape (`report_type`, `filterset`, `filters_json`, `extract`) and the `apply_as` direction. Note: `source_query.filterset` MUST include a date filter when sponsorship-related — see Hard rules.

---

## Process

### `cross_references` path

1. Validate `MAIN_REPORT_TYPE ∈ {1, 3}`. Reject otherwise.
2. Validate the entry's `type` is in the catalog. Reject deprecated MSN types — return a hint to use `msn_channels_only` instead.
3. For `*_proposed_to_brand` types: validate `brand_names` is non-empty; if `statuses` is omitted, **don't** fill it in — let the backend apply the default (so the emit stays minimal and forward-compatible if the default changes server-side).
4. For `include_sponsored_by_mbn`: same — only emit `statuses`/`days_ago` if the user gave a non-default value.

### `multi_step_query` path

1. Validate the source query shape: `report_type` is one of {1, 2, 3, 8}, `filterset` is present, `extract == "channel_ids"`.
2. **Date enforcement** for sponsorship-side source queries (`source_query.report_type == 8`): if the user's framing is "currently / active / right now / in the pipeline" without explicit dates, default `source_query.filterset.start_date = <one year ago>`. If the user said "ever / all-time", omit the date filter (rare).
3. Validate `apply_as ∈ {"channels", "exclude_channels"}`.
4. **Page through the source query if it can return more than 500 IDs.** The sandboxed read endpoints cap a single SELECT at `LIMIT 500`. A source query like "channels we've pitched in the last 12 months" routinely returns thousands of IDs (verified against live data: ~4,500 distinct channels in active pipeline last 12 months). The orchestration paginates: `LIMIT 500 OFFSET 0`, `LIMIT 500 OFFSET 500`, ... until a page returns fewer than 500 rows. Concatenate the pages into one ID list before injecting as `apply_as`. Cap total IDs at `MAX_IDS` (default 10000); surface a warning if truncated.
5. Compose the wrapper.

---

## Output

### For `cross_references`

```json
{
  "mechanism": "cross_references",
  "intent_nl": "<echo>",
  "cross_references_entry": {
    "type": "exclude_proposed_to_brand" | "include_proposed_to_brand" | "include_sponsored_by_mbn",
    "brand_names": ["..."],
    "statuses": [...],          // present only if user specified non-default
    "days_ago": <int>           // present only on include_sponsored_by_mbn AND user specified non-default
  }
}
```

The caller appends `cross_references_entry` to the top-level `cross_references` array of the create_report payload.

### For `multi_step_query`

```json
{
  "mechanism": "multi_step_query",
  "intent_nl": "<echo>",
  "payload": {
    "action": "multi_step_query",
    "source_query": {
      "report_type": <int>,
      "filterset": { ... },
      "filters_json": { ... },
      "extract": "channel_ids"
    },
    "main_report": {
      // ... fields composed by the caller; this tool only fills in `apply_as`
      "apply_as": "channels" | "exclude_channels"
    }
  }
}
```

The caller uses the wrapper as the outermost shape of the response (replacing `create_report` for that turn).

### Errors

```json
{
  "errors": [
    "Cross-references only valid for report types 1 and 3 (received: 8)",
    "Type 'exclude_msn_channels' is deprecated — use filterset.msn_channels_only: false instead",
    "..."
  ]
}
```

---

## v1 status ID reference

For `statuses` arrays in the `*_proposed_to_brand` catalog entries:

| ID | Meaning |
|---|---|
| 0 | Proposed |
| 1 | Unavailable |
| 2 | Pending |
| 3 | Sold |
| 4 | Rejected by Advertiser |
| 5 | Rejected by Publisher |
| 6 | Proposal Approved |
| 7 | Matched |
| 8 | Reached Out |
| 9 | Rejected by Agency |

Default "active" set (when `statuses` is omitted): `[0, 2, 3, 6, 7, 8]` — excludes rejected/unavailable.

---

## Hard rules

1. **`cross_references` only applies to report types 1 and 3.** Reject for types 2 and 8.
2. **Don't emit deprecated MSN types** (`exclude_msn_channels` / `include_msn_channels`). Redirect the caller to `filterset.msn_channels_only`.
3. **Don't fill in defaults the user didn't request.** If `statuses` is omitted in the user's intent, leave it omitted — the backend applies the active-set default. This keeps the emit minimal and resilient if server defaults change.
4. **Date enforcement for sponsorship-side `multi_step_query` source queries.** "Currently / active / in pipeline" framings without explicit dates default to the last 12 months (per v1 line 112). "Ever / all-time" framings explicitly opt out.
5. **One `multi_step_query` per response.** Multiple cross-references that all need flexibility go through `cross_references` entries (when possible) or get split across requests. The wrapper supports a single `apply_as` direction.
6. **Composability**: a single create_report response can have `cross_references` entries AND `filters_json.similar_to_channels` AND the FilterSet's `exclude_brands` array (resolved IDs from `name_resolver`) simultaneously — they are independent. Don't collapse them into a `multi_step_query`.
7. **`extract` is fixed**: today only `"channel_ids"` is supported. Don't invent other extract types.
8. **Don't run the SQL yourself.** This tool composes the v1-shaped payload; the backend resolves the cross-reference at report-execution time.
