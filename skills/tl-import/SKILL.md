---
name: tl-import
description: |
  Include or exclude a list of channels, brands, uploads (videos), or sponsorships against an **existing** ThoughtLeaders report. Wraps `tl bulk-import`. Superuser-only.

  **This skill does ONE thing**: take a target `report_id` plus a list of identifiers, and attach (or exclude) them via `tl bulk-import`. It does NOT create reports, design filters, pick columns/widgets, or generate report metadata — those are `tl-cli:tl-report-builder`'s responsibilities.

  Triggers on **two shapes** of request:

  1. **Existing report** (this skill alone) — the user names a target report ID or pastes a TL report URL. Examples: "import these channels into report 1234", "add brands to campaign 5678", "exclude these channels from report Z", "bulk-add these videos to report X".
  2. **New report from a hand-picked list** (pipeline with `tl-report-builder`) — the user pastes a list of identifiers (YouTube URLs, `@handles`, `UC…` IDs, brand domains, video URLs, AdLink IDs) and asks to import them into a NEW report, with no filters / keywords / topic criteria. Examples: "import these links into a new report: <URLs>", "build a report from these channels: <list>", "create a campaign with these brands: <domains>", "make a new report containing these videos", "save these channels to a new report". **Execution order**: `tl-cli:tl-report-builder` runs FIRST in its bare-container mode to create the empty report (correct `report_type`, columns, widgets, title, description — empty `filterset`), then `tl-import` runs SECOND against the captured `report_id` to attach the list via `tl bulk-import`. Identify both skills at planning time; chain them in that order.

  Identification cue for shape 2: the user pasted concrete identifiers AND said something like "new report" / "build a report from these" / "create a campaign with these". The presence of identifiers is the strong signal — that's what triggers identifying `tl-import`'s involvement; the "new report" wording is what adds `tl-report-builder` to the chain.

  `tl bulk-import` already auto-creates channels from YouTube URLs/handles and brands from website domains — no SQL resolution needed. The list-paste case never requires a pre-resolution step.

  **Skip this skill entirely** for filter-driven reports with no hand-picked list (keywords, topics, demographic floors, exclusions, look-alikes, date scopes, MSN/TPP scoping). Those are `tl-cli:tl-report-builder` alone.
---

# tl-import

Wraps the `tl bulk-import` command — submits a list of identifiers against a report, polls until done, and renders a per-row result table.

## When to use

Two trigger shapes — both run through this skill.

### Shape A — existing report

The user names a target report ID or pastes a TL report URL (`https://app.thoughtleaders.io/#/thoughtleaders?campaign=23859&…`).

- "Import @mkbhd, @veritasium into report 1234"
- "Add these brands to campaign 5678"
- "Bulk-add this list of channels to report 999"
- "Exclude these channels from report Z"
- "Add these videos to report X"

### Shape B — new report from a hand-picked list (chained with tl-report-builder)

The user pastes a list of identifiers and asks for a NEW report with no filtering criteria. No keywords, no topics, no demographic / format / date filters — just "these specific entities".

- "Import these links into a new report: <50 YouTube URLs>"
- "Build a report from these channels: @mkbhd, @veritasium, UCXuqSBlHAE6Xw-yeJA0Tunw"
- "Create a campaign with these brands: nike.com, adidas.com, puma.com"
- "Make a new report containing these videos: <video URLs>"
- "Save these channels to a new report"

**This skill does NOT create the report.** For Shape B, the agent invokes `tl-cli:tl-report-builder` first (in its bare-container mode — see that skill's frontmatter) to create an empty report container with the correct `report_type` (3 for channels, 2 for brands, 1 for content/videos, 8 for sponsorships), default columns/widgets, polished title, and description. The report is created with an empty `filterset`. `tl-report-builder` returns the new `report_id`.

Then `tl-import` (this skill) runs against that `report_id` and attaches the pasted list via `tl bulk-import`. The single user-facing message after the chain should weave both outputs — "report created (link), 50 channels attached, 47 already in TL, 3 newly created".

`tl bulk-import` resolves YouTube URLs / handles / `UC…` IDs to channels (and auto-creates any that aren't in TL yet) and brand domains to brands. **Do NOT pre-resolve identifiers via raw SQL** — `tl bulk-import` does it server-side in one call.

Single-identifier requests still work (the command accepts one).

## Inputs to gather

Before running, confirm:

1. **Target report ID** — a numeric ID (`--campaign` / `-c`), always required by `tl bulk-import`.
   - **Existing report** (Shape A): pull the ID from the user's prompt — a number, or the integer after `campaign=` in a pasted TL URL.
   - **New report** (Shape B): the ID does NOT exist yet at the start of the turn. Invoke `tl-cli:tl-report-builder` first in its bare-container mode; capture the `report_id` from its response; then continue this skill against that ID.
   - **Ambiguous** (list pasted, no ID, no "new" wording): ask once — *"Add these to a new report, or to an existing one (paste the report ID / URL)?"*
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

   **Do not resolve identifiers ahead of time with `tl db pg` / raw SQL.** `tl bulk-import` handles URL → channel-ID, handle → channel-ID, and domain → brand-ID resolution server-side, and auto-creates missing entities. Pre-resolution wastes credits and time, and is the wrong tool — equality / batch resolution over the `thoughtleaders_channel` table will miss the auto-create case entirely.
4. **Include vs exclude** — default is include (add to the report). Pass `--exclude` only if the user explicitly wants to remove from the report. `--exclude` is invalid in new-report mode (a brand-new report has nothing to exclude from); error early if the user combines them.

## Shape B — handoff from tl-report-builder (don't create reports here)

For Shape B (new-report-from-list), `tl-import` is the **second** step of the pipeline. The first step — creating the empty report container — is `tl-cli:tl-report-builder`'s job, NOT this skill's.

Before invoking `tl bulk-import` for a Shape B request, confirm:

1. `tl-cli:tl-report-builder` has already run in its bare-container mode for this turn.
2. A new `report_id` has come back from that skill's `tl reports create --config-file ... --yes` call.

Then proceed to "How to invoke" below with that `report_id` as the `-c` value.

If the user pastes a Shape B prompt and `tl-report-builder` hasn't run yet in this turn, **invoke it first**. Do NOT call `tl reports create` from inside this skill — that would duplicate `tl-report-builder`'s scope (column/widget/title/description selection) and the two skills would drift apart over time. The only CLI command this skill owns is `tl bulk-import`.

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

- **Doesn't create reports. Ever.** Including bare-container reports for Shape B. The CLI command `tl reports create` is not invoked from this skill. Report creation — full or bare — is `tl-cli:tl-report-builder`'s scope. If a Shape B request arrives and no report exists, hand off to `tl-report-builder` first; come back to this skill once it returns a `report_id`.
- **Doesn't pick columns, widgets, titles, descriptions, or takeaways.** Same reason — those are `tl-report-builder`'s responsibility.
- **Doesn't design filters.** No keyword research, topic matching, demographic floors, brand exclusions, look-alikes, MSN/TPP scoping, date scopes. Filter-driven reports go straight to `tl-report-builder` (no `tl-import` involvement at all).
- **Doesn't resolve identifiers ahead of time.** No `tl db pg` / raw SQL to look up channel IDs from URLs / handles. `tl bulk-import` does that server-side and auto-creates anything missing. Pre-resolution wastes credits, misses the auto-create path, and is the kind of detour the skill is designed to avoid.
- **Doesn't validate identifiers ahead of time** either — submit and let the per-row `reason` tell the user which ones failed. Pre-checking with `tl channels show` / etc. is wasteful (metered) and adds latency.
- **Doesn't sweep duplicates** from the user's input list — submit them as-is. The response will mark the second occurrence as `Duplicate`, which is more informative than silently deduping.
