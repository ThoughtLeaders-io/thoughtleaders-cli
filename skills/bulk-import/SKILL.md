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

JSON envelope on stdout:

```json
{
  "task_id": "...",
  "success_ids": [<int>, ...],
  "success_ids_count": <int>,
  "failed_ids": [...],
  "failed_ids_count": <int>,
  "newly_created_ids": [<int>, ...],
  "not_created_channels_count": <int>
}
```

Surface to the user:

- **`success_ids_count`** — how many identifiers landed in the report.
- **`newly_created_ids`** — channels/brands that didn't exist before and were created by this import. Mention that enrichment (subscriber stats, AI description, demographics for channels; logo/website metadata for brands) is queued and will populate over the next few minutes.
- **`failed_ids` / `not_created_channels_count`** — anything that couldn't be resolved or created. Show them so the user can fix and retry.

## Errors

- **403** → caller isn't a superuser. Stop and tell the user; this skill is gated.
- **400** → bad input. Show the `detail` verbatim (usually missing field, unknown entity, or all-empty identifiers).
- **402** → out of credits. Tell the user to top up.
- **Connection failed** → transient network issue. Retry once; if it persists, ask the user.

## What this skill does NOT do

- Doesn't create reports — that's a separate skill (`tl-report-builder`).
- Doesn't change report metadata (title, description, columns, filters).
- Doesn't validate identifiers ahead of time — let `tl bulk-import` do the lookup and report back which ones failed. Pre-checking via `tl channels show` is wasteful.
