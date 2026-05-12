---
name: tl-import
description: Bulk-add or exclude a list of channels, brands, uploads (videos), or sponsorships against a ThoughtLeaders report (campaign). Superuser-only. Use when a request asks to import / add / exclude a batch of identifiers against a specific report ID — phrasings like "import these channels into report 1234", "add brands to campaign 5678", "exclude these channels from report Z", "bulk-add these videos to report X".
---

# tl-import

Wraps the `tl bulk-import` command — submits a list of identifiers against a report, polls until done, and renders a per-row result table.

## When to use

Trigger on requests like:

- "Import @mkbhd, @veritasium into report 1234"
- "Add these brands to campaign 5678"
- "Bulk-add this list of channels to report 999"
- "Exclude these channels from report Z"
- "Add these videos to report X"

Single-identifier requests still work (the command accepts one). The reason to keep this skill separate from other report-edit flows: it's the only path that auto-creates channels from YouTube URLs / handles, and brands from website domains.

## Inputs to gather

Before running, confirm:

1. **Report ID** (`--campaign` / `-c`) — required. If the user pastes a TL URL (e.g. `https://app.thoughtleaders.io/#/thoughtleaders?campaign=23859&...`), the integer after `campaign=` is the ID.
2. **Entity type** — one of `channels` / `brands` / `articles` / `sponsorships`. Infer from context, but translate user-facing vocabulary:
   - YouTube URLs / handles / `UC…` IDs → `channels`
   - Domains / brand slugs → `brands`
   - "videos" / "uploads" / video URLs / video IDs → `articles` *(the CLI calls them uploads in `tl uploads list`, but `bulk-import` expects `articles` — same concept, legacy naming)*
   - "adlinks" / "deals" / "sponsorships" / numeric AdLink IDs → `sponsorships`
3. **Identifiers** — the list. Accepted shapes per entity:
   - **channels**: numeric DB IDs, YouTube channel IDs (`UC…`), `@handles`, full YouTube URLs (`/@…`, `/channel/UC…`, `/user/…`)
   - **brands**: numeric IDs, slugs, websites / domains (`example.com`)
   - **articles** (uploads): video IDs or video URLs
   - **sponsorships** (adlinks): numeric AdLink IDs only
4. **Include vs exclude** — default is include (add to the report). Pass `--exclude` only if the user explicitly wants to remove from the report.

## How to invoke

The command reads identifiers from a file (`--ids-file`) or stdin:

```bash
# small list — stdin
echo '@mkbhd
@veritasium
@lemmino' | tl bulk-import channels --campaign 1234

# larger list — file
tl bulk-import channels --campaign 1234 --ids-file ./channels.txt

# exclusion
tl bulk-import brands --campaign 5678 -f ./brands.txt --exclude
```

Short flags: `-c` for `--campaign`, `-f` for `--ids-file`.

## Output: the `inputs` envelope

`tl bulk-import` returns a JSON envelope. Use the **`inputs`** array as the source of truth for what to render — it has one row per submitted identifier, in input order, with everything you need to classify and display.

```json
{
  "task_id": "...",
  "mode": "include",
  "inputs": [
    {"input": "@mkbhd",            "resolved_id": 4587,    "reason": "Success",    "newly_created": false},
    {"input": "@veritasium",       "resolved_id": 1209,    "reason": "Duplicate",  "newly_created": false},
    {"input": "@OfficialSaharTV",  "resolved_id": 1328906, "reason": "Success",    "newly_created": true},
    {"input": "https://bad-url",   "resolved_id": null,    "reason": "Not found",  "newly_created": false}
  ],
  "success_ids": [4587, 1328906],
  "newly_created_ids": [1328906],
  "failed_ids": [...],
  ...
}
```

Each `inputs` row's `input` field echoes the raw identifier the user submitted (unchanged). `resolved_id` is the entity ID it matched/created, or `null` for failures. `reason` and `newly_created` drive the row's display label below.

**`mode` echoes back the operation mode** (`"include"` or `"exclude"`). You need this for labelling because the semantics flip:

- include + Success = identifier was just added to the report
- exclude + Success = identifier was just removed from the report
- include + Duplicate = identifier was already in the report (no-op)
- exclude + Duplicate = identifier was already excluded (no-op)

Don't use `success_ids` / `failed_ids` for display — they lose input mapping and miss the include/exclude direction. `inputs` is the canonical surface.

## Classify each row

| `reason` | `newly_created` | `mode` | Icon | Label |
|---|---|---|---|---|
| `Success` | `true` | `include` | 🆕 | Created in TL |
| `Success` | `true` | `exclude` | ⚠️ | Created in TL — unexpected for exclude, verify report state |
| `Success` | `false` | `include` | ✅ | Added |
| `Success` | `false` | `exclude` | ✂️ | Excluded |
| `Duplicate` | any | `include` | ↺ | Already in report |
| `Duplicate` | any | `exclude` | ↺ | Already excluded |
| `Not found` | any | any | ❌ | Not found |
| `Cannot parse` | any | any | ❌ | Bad format |
| `Multiple matches found` | any | any | ❌ | Ambiguous (multiple matches) |
| `Limit exceeded` | any | any | ❌ | Auto-create cap hit |
| starts with `Error:` | any | any | ❌ | Error (show reason verbatim) |
| anything else | any | any | ❌ | Failed (show reason verbatim) |

For 🆕 rows: mention that enrichment (subscriber stats, AI description, demographics for channels; metadata for brands) is queued and will populate over the next few minutes — these entities just entered the database.

For ⚠️ rows: if an exclude import returns `newly_created: true`, treat it as unexpected. Tell the user the channel was created but does not appear to have been excluded — ask them to verify the report and re-submit the exclude against the returned `resolved_id` if needed.

## Display

Per-row markdown table. **Headline first** with the gain count, then the table.

For include mode:

```markdown
**Bulk-import to report 23859 — done.** Report gained **2** rows; **1** was already there; **1** failed.

| # | Status | Input | ID | Reason |
|---|---|---|---|---|
| 1 | ✅ Added | `@mkbhd` | 4587 | Success |
| 2 | ↺ Already in report | `@veritasium` | 1209 | Duplicate |
| 3 | 🆕 Created in TL | `@OfficialSaharTV` | 1328906 | Success — enrichment queued |
| 4 | ❌ Not found | `https://bad-url` | — | Not found |
```

For exclude mode, headline uses "lost" wording:

```markdown
**Bulk-import (exclude) to report 23859 — done.** Report lost **N** rows; **M** were already excluded.
```

Display rules:

- **Use the user's raw `input` value** in the Input column (it's `inputs[i].input` — the raw submitted string, unchanged).
- **Omit any column that's uniformly empty** — for sponsorships, the "Input" and "ID" columns are usually identical (both numeric); the Reason column carries the signal.
- **Small imports (≤30 rows):** render the full table.
- **Large imports (>30 rows):** lead with a summary table of bucket counts; render the per-row table only for **non-bulk-success rows** — i.e. omit the dominant happy-path bucket, which is ✅ Added in include mode and ✂️ Excluded in exclude mode. The rows the user cares about (already-present, newly-created, failed, unexpected) all stay. Offer to dump the omitted rows on request.

  Summary table (include mode example):

  ```markdown
  | Bucket | Count |
  |---|---|
  | ✅ Added | 142 |
  | ↺ Already in report | 7 |
  | 🆕 Created in TL | 3 |
  | ❌ Failed | 2 |
  | **Total submitted** | **154** |
  ```

  Summary table (exclude mode example):

  ```markdown
  | Bucket | Count |
  |---|---|
  | ✂️ Excluded | 142 |
  | ↺ Already excluded | 7 |
  | ❌ Failed | 2 |
  | **Total submitted** | **151** |
  ```

- **Never look up entity names** with extra `tl channels show <id>` / `tl brands show <id>` calls just to populate a "Name" column — those are metered. The user's input column is enough for them to identify each row. If the user explicitly asks "what are these channels called?", then look them up.

## Errors at the command level (before the per-row results)

These are envelope-level failures, distinct from per-row `reason` values:

- **403** → caller isn't a superuser. Stop and tell the user; this command is gated.
- **400** → bad input shape (missing field, unknown entity, all-empty identifiers). Show the `detail` verbatim.
- **402** → out of credits. Tell the user to top up.
- **Connection failed** → transient network issue. Retry once; if it persists, surface to the user.

## What this skill does NOT do

- Doesn't create reports — that's `tl-report-builder`.
- Doesn't change report metadata (title, description, columns, filters).
- Doesn't validate identifiers ahead of time — submit and let the per-row `reason` tell the user which ones failed. Pre-checking with `tl channels show` / etc. is wasteful (metered) and adds latency.
- Doesn't sweep duplicates from the user's input list — submit them as-is. The response will mark the second occurrence as `Duplicate`, which is more informative than silently deduping.
