# Data plane — schema facts the report-builder skill consults

This file is the canonical home for the table/column-level facts the report-builder skill's orchestration depends on. Per the AGENTS.md skill-content boundary, schema-shaped facts live here in `references/`, not inline in `SKILL.md` or `tools/*.md`. Skill text references entries here by anchor; nothing in skill text should restate columns / fetch SQL / data-plane query templates.

The broader TL data plane (every Postgres table, ES doc type, Firebolt warehouse) is documented in the `tl-cli:tl` skill's `references/postgres-schema.md` / `elasticsearch-schema.md` / `firebolt-schema.md`. **Prefer those when looking up a table the report-builder doesn't already cover here.** This file is a curated subset — only the schema facts the report-builder's orchestration needs in-flow (fetch query templates, key column references for FilterSet validation, etc.). When this file and `tl/references/postgres-schema.md` disagree, the `tl` references win.

---

## Topics table — fetch query (canonical)

The `topic_matcher` conditional tool consumes the live topic list. Use this query verbatim when the orchestration calls for fetching topics:

```bash
tl db pg --json "SELECT id, name, description, keywords FROM thoughtleaders_topics ORDER BY id LIMIT 100 OFFSET 0"
```

The table has fewer than 20 rows; client-side filtering after a full fetch is free. **Do not push name-pattern WHERE clauses into the SQL** — the agent has guessed `WHERE is_active = TRUE` and `WHERE name ILIKE ANY(...)` in past runs and burnt round-trips on hallucinated columns.

### Topics table — columns

| Column | Type | Notes |
|---|---|---|
| `id` | integer | primary key |
| `name` | varchar | topic display name |
| `description` | varchar | one-paragraph description; `topic_matcher` uses it for tie-breaks |
| `keywords` | jsonb | array of curated keyword strings — the matcher's primary signal |
| `created_at` | timestamptz | rarely needed |
| `updated_at` | timestamptz | rarely needed |
| `source` | varchar | provenance, rarely needed |

### Topics table — columns that DO NOT exist

Common hallucinations the agent has tried in real runs (each wasted a round-trip). All return *"column '\<name\>' does not exist"*:

- ❌ `is_active`
- ❌ `type` (topics are not subtyped at the schema level)
- ❌ `parent_id` (topics are flat, not hierarchical)
- ❌ `slug`, `topic_id` (the PK is `id`), `archived`, `is_published`

Cited regression markers:
- AI/marketing channels run: tried `thoughtleaders_topic` (singular — table doesn't exist), then `WHERE is_active = TRUE`. Three round-trips before consulting `information_schema`.
- Travel/digital-nomad run: tried `SELECT id, name, type, parent_id FROM thoughtleaders_topics WHERE name ILIKE ANY(...)`.

If a query against this table errors with *"column '\<X\>' does not exist"*, that's the regression marker — go back to the verbatim fetch above.

---

## Channel table — slug / URL pattern

Sample-table rows hyperlink channel names to the TL platform via:

```
https://app.thoughtleaders.io/youtube/<slug>
```

The slug source is `thoughtleaders_channel.slug`. Phase 2's sample query must include `slug` alongside the rendered fields, otherwise rule 20a's hyperlink mandate can't be satisfied. Falls back to an ID-based TL path if slug is missing — never to the external YouTube URL.

---

## When to use ES vs PG (high-level)

The split between `tl db pg` and `tl db es` for report-builder validation is documented in [`SKILL.md`'s Step 2.V1](../SKILL.md) (intelligence-report routing) and the per-pattern callouts in the Save-or-preview policy. This file holds the schema details those orchestration sections lean on; the routing rules themselves stay in `SKILL.md`.
