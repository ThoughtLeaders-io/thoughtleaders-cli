---
name: bulk-import
description: Bulk-add or exclude a list of channels, brands, articles, or sponsorships from a ThoughtLeaders report (campaign). Superuser-only. Use when a request asks to import / add / exclude a batch of identifiers against a specific report ID — phrasings like "import these channels into report 1234", "add brands to campaign 5678", "exclude these channels from report Z".
---

# Bulk Import

Wraps `tl bulk-import` — submits a list of identifiers against a report and polls until the import finishes. Reports which entities landed and which were skipped or newly created.

## When to use

Trigger on requests like:

- "Import @mkbhd, @veritasium into report 1234"
- "Add these brands to campaign 5678"
- "Bulk-add this list of channels to report 999"
- "Exclude these channels from report Z"

If a single identifier is asked for, `tl bulk-import` still works (it accepts one). The reason to keep this skill separate from other report-edit flows: it's the only path that auto-creates channels from YouTube URLs / handles and brands from website domains.

## Inputs to gather

Before running the command, confirm:

1. **Report ID** (`--campaign`) — required. If the user pastes a TL URL (e.g. `https://app.thoughtleaders.io/#/thoughtleaders?campaign=23859&...`), the integer after `campaign=` is the ID.
2. **Entity type** — one of `channels`, `brands`, `articles`, `sponsorships`. Infer from context:
   - YouTube URLs / handles / `UC…` IDs → `channels`
   - Domains / brand slugs → `brands`
   - Video URLs / IDs → `articles`
   - AdLink integer IDs → `sponsorships`
3. **Identifiers** — the actual list. Accepted shapes per entity:
   - **channels**: numeric DB IDs, YouTube channel IDs (`UC…`), `@handles`, full YouTube URLs (`/@…`, `/channel/UC…`, `/user/…`)
   - **brands**: numeric IDs, slugs, websites/domains (`example.com`)
   - **articles**: video IDs or video URLs
   - **sponsorships**: AdLink IDs (numeric only)
4. **Include vs exclude** — default is include (add to the report). Pass `--exclude` only if the user explicitly wants to remove from the report.

## How to invoke

The command reads identifiers from a file (`--ids-file`) or stdin. For lists of more than a handful, write to a temp file:

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

## Output

`tl bulk-import` prints a JSON envelope on stdout:

| Field | Meaning |
|---|---|
| `task_id` | The import task that ran. |
| `success_ids` | All entity IDs that end up in the report after the import — **mixes newly-added and already-present**. |
| `success_ids_count` | Count of `success_ids`. |
| `newly_created_ids` | Subset of `success_ids` that didn't exist in TL's database and were just created from the external source (YouTube for channels, website for brands). |
| `not_created_channels_count` | Channels that didn't go through the create path because they matched something on file. |
| `failed_ids` / `failed_ids_count` | Entities that couldn't be resolved or created. |

## How to present results

The user wants to know **how much of the list actually changed the report**. `success_ids` alone doesn't answer that — channels that were already in the report are bundled in with newly-added ones. To separate them cleanly, snapshot the report before the import and diff after.

**Workflow:**

1. **Before** running `tl bulk-import`, capture the report's current channel IDs:

   ```bash
   tl reports run <campaign_id> --json --limit 1000
   ```

   Collect each result's `channel_id` (or `brand_id` / `sponsorship_id`) into a set — call it `before`. If the report has more than 1000 entries, paginate with `--offset` or note to the user that "already in report" is a lower bound.

2. Run `tl bulk-import` as documented above. Parse the JSON output.

3. Classify the result into four buckets:

   | Bucket | Definition |
   |---|---|
   | **Newly added** | `success_ids − before` — the report actually gained these. |
   | **Already in report** | `success_ids ∩ before` — no-op for these from the user's POV. |
   | **Newly created in TL** | `newly_created_ids` — always a subset of "Newly added"; flag separately so the user knows enrichment is queued. |
   | **Failed** | `failed_ids` — couldn't be resolved or created. |

4. **Display** as a markdown table — one row per identifier from the user's input list, in input order so they can scan against their original list.

   **Headline first**, then the table:

   ```markdown
   **Bulk-import to report 23859 — done.** Report gained **12** channels (3 already there, 1 failed).

   | # | Status | Identifier | Channel | ID |
   |---|---|---|---|---|
   | 1 | ✅ Added | `@mkbhd` | Marques Brownlee | 4587 |
   | 2 | ✅ Added | `@veritasium` | Veritasium | 1209 |
   | 3 | ↺ Already in report | `@lemmino` | LEMMiNO | 8821 |
   | 4 | 🆕 Created in TL | `@OfficialSaharTV` | SaharTV | 1328906 |
   | 5 | ❌ Failed | `https://example.com/bad-url` | — | — |
   ```

   **Status legend** (use these exact icons + labels):

   | Icon | Label | Means |
   |---|---|---|
   | ✅ | Added | In `success_ids` and **not** in the pre-import snapshot — the report just gained this one. |
   | ↺ | Already in report | In `success_ids` AND in the pre-import snapshot — no-op for this identifier. |
   | 🆕 | Created in TL | Also in `newly_created_ids` — the entity didn't exist in our database before this import; YouTube scrape + AI enrichment is queued for channels, website scrape for brands. Always renders this label over plain "Added" when both apply. |
   | ❌ | Failed | In `failed_ids` — couldn't be resolved or created. |

   **Channel/Brand name column:** populate from the input handle/URL where obvious (`@mkbhd` → "MKBHD" is the handle itself, fine to leave as the identifier). For numeric IDs in the input, leave the name blank rather than burning a credit on `tl channels show <id>` per row. If the user asks "what are these?", THEN look up names.

   **Display rules:**

   - **Small imports (≤30 rows):** render the full table as shown.
   - **Large imports (>30 rows):** lead with a summary table of bucket counts, then render the **per-row table only for the non-Added buckets** ("Already in report", "Created in TL", "Failed") since those are the rows the user cares about. Offer to dump the full "Added" rows on request.

     Summary table for large imports:

     ```markdown
     | Bucket | Count |
     |---|---|
     | ✅ Added | 142 |
     | ↺ Already in report | 7 |
     | 🆕 Created in TL | 3 |
     | ❌ Failed | 2 |
     | **Total submitted** | **154** |
     ```

   - **Omit the legend** in the actual response — it's documented here for you (the skill), not for the user. They should be able to read the icons in context.

**Headline number:** the value the user really cares about is `len(newly_added)` — what the report actually gained. `success_ids_count` alone is misleading when the input overlaps with the existing report.

## Errors

- **403** → caller isn't a superuser. Stop and tell the user; this skill is gated.
- **400** → bad input. Show the `detail` verbatim (usually missing field, unknown entity, or all-empty identifiers).
- **402** → out of credits. Tell the user to top up.
- **Connection failed** → transient network issue. Retry once; if it persists, ask the user.

## What this skill does NOT do

- Doesn't create reports — that's a separate skill (`tl-report-builder`).
- Doesn't change report metadata (title, description, columns, filters).
- Doesn't validate identifiers ahead of time — let `tl bulk-import` do the lookup and report back which ones failed. Pre-checking via `tl channels show` is wasteful.
