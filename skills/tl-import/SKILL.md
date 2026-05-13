---
name: tl-import
description: |
  Bulk-add or exclude a list of channels, brands, uploads (videos), or sponsorships against a ThoughtLeaders report (campaign). Superuser-only.

  Triggers on **two shapes** of request:

  1. **Existing report** — the user names a target report ID or pastes a TL report URL. Examples: "import these channels into report 1234", "add brands to campaign 5678", "exclude these channels from report Z", "bulk-add these videos to report X". This skill handles the request end-to-end.
  2. **New report from a hand-picked list** — the user pastes a list of identifiers (YouTube URLs, `@handles`, `UC…` IDs, brand domains, video URLs, AdLink IDs) and asks to import them into a NEW report, with no filters / keywords / topic criteria. Examples: "import these links into a new report: <URLs>", "build a report from these channels: <list>", "create a campaign with these brands: <domains>", "make a new report containing these videos", "save these channels to a new report". **This is a two-skill pipeline**: `tl-import` runs FIRST to create the bare container and attach the list, then `tl-cli:tl-report-builder` runs SECOND to populate columns/widgets/title-polish/takeaways on the just-created report (via its enrich-existing mode). Identify both at planning time; run them in order; surface a single end-to-end result to the user.

  Both paths are this skill's entry point because `tl bulk-import` already auto-creates channels from YouTube URLs/handles and brands from website domains — no SQL resolution needed.

  **Skip this skill entirely** when the user wants a filter-driven report (keywords, topics, demographic floors, exclusions, look-alikes, date scopes, MSN/TPP scoping) and does NOT paste a hand-picked list. Those go straight to `tl-cli:tl-report-builder`. Rule of thumb: if the request pastes a concrete list of entities, this skill is in the pipeline. If it describes entities by criteria only, this skill is not.
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

### Shape B — new report from a hand-picked list

The user pastes a list of identifiers and asks for a NEW report with no filtering criteria. No keywords, no topics, no demographic / format / date filters — just "these specific entities".

- "Import these links into a new report: <50 YouTube URLs>"
- "Build a report from these channels: @mkbhd, @veritasium, UCXuqSBlHAE6Xw-yeJA0Tunw"
- "Create a campaign with these brands: nike.com, adidas.com, puma.com"
- "Make a new report containing these videos: <video URLs>"
- "Save these channels to a new report"

Shape B works because `tl bulk-import` already resolves YouTube URLs / handles / `UC…` IDs to channels (and auto-creates any that aren't in TL yet) and brand domains to brands. **Do NOT pre-resolve identifiers via raw SQL** — `tl bulk-import` does it server-side in one call.

Single-identifier requests still work (the command accepts one). The reason to keep this skill separate from `tl-report-builder`: this is the only path that auto-creates channels/brands from URLs/domains, and the only path that handles hand-picked lists without trying to invent filters.

## Inputs to gather

Before running, confirm:

1. **Target report** — either an existing ID or new-report intent.
   - **Existing**: a numeric ID from the prompt, or the integer after `campaign=` in a pasted TL URL.
   - **New**: the user said "into a new report" / "build a report from these" / "create a campaign with these" / "make a report containing …" / "save these to a new report", AND no report ID is in the prompt. Go through the "Creating the container report" section below before invoking `tl bulk-import`.
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

## Creating the container report (new-report mode only)

When the target is a new report, build a minimal "naked container" config and POST it via `tl reports create --config-file <path> --yes` BEFORE running `tl bulk-import`. The container holds no filters — the pasted list IS the report's content, attached via the bulk-import step.

### Step 1 — Map entity → report_type

| Entity | `report_type` | User-facing label |
|---|---|---|
| `channels` | `3` | channels report |
| `brands` | `2` | brands report |
| `articles` | `1` | content / videos report |
| `sponsorships` | `8` | sponsorships / deals report |

### Step 2 — Generate title + description

Both fields are **mandatory** — `tl reports create` returns `Error (400): Missing required field: report_title` (or `report_description`) if either is missing or empty. Validate before saving, not at save time.

- **Title** ≤ 60 chars. If the user supplied one ("call it 'Fitness Creators Q2'"), use it verbatim. Otherwise default to `"Imported <entity-label> — <N> <entity>"` (e.g. `"Imported channels — 50 channels"`). Keep it descriptive enough that the user recognises it in their saved-reports list.
- **Description** 1–3 sentences summarising what the report contains and how it was assembled. Default template: `"Hand-picked <entity-label> imported from a user-supplied list on <YYYY-MM-DD>. <N> identifiers submitted. No filters applied — the list itself defines the report's scope."`

### Step 3 — Build the minimal container config

```json
{
  "type": 2,
  "report_type": <int from Step 1>,
  "report_title": "<from Step 2>",
  "report_description": "<from Step 2>",
  "filterset": {}
}
```

- `type: 2` is the `DYNAMIC` Campaign-model contract — always emit this value for skill-created reports.
- `filterset: {}` is intentional. The pasted list is attached by `tl bulk-import` in the next phase; no filter fields are needed.
- Do NOT add `filterset.channels: [...]` / `filterset.brands: [...]` here even if you happen to have IDs. Let `tl bulk-import` own the attachment — it's the single source of truth for what's in the report, and it handles auto-create.
- **Don't pick columns or widgets here.** The container is intentionally bare. `tl-cli:tl-report-builder` picks columns/widgets/title-polish/takeaways in the enrichment step (Step 5 below). Picking them here would mean both skills doing the same job from different reference points.

### Step 4 — Save the container

Write the config to a portable temp path:

```bash
python -c "import tempfile, os; print(os.path.join(tempfile.gettempdir(), 'tl-import-container-<short-slug>.json'))"
```

Capture the printed path verbatim — on Windows it lands in `C:\Users\…\AppData\Local\Temp\`, not `/tmp/`. Write the JSON to that exact path, then:

```bash
tl reports create --config-file <that-exact-path> --yes
```

Capture the `Campaign ID` from the response — this is the `-c` value for the bulk-import step. Capture the URL too — surface it in the final user-facing message.

If `tl reports create` fails:
- **`Error (400): Missing required field: report_title`** — Step 2 didn't generate a title. Generate one, rewrite the file, retry.
- **`Error (400): Missing required field: report_description`** — same as above for the description.
- **`Error (400): Missing required field: columns`** (or `widgets`) — the server requires at least a baseline set. Add the always-include channels columns (`Channel`, `TL Channel Summary`, `Subscribers`) — emitted as `{"Channel": {"index": 0, "display": true}, "TL Channel Summary": {"index": 1, "display": true}, "Subscribers": {"index": 2, "display": true}}` — and retry. `tl-report-builder` will rewrite them in Step 5 anyway.
- **Any other 400** — surface the error verbatim and stop. Don't proceed to bulk-import against a non-existent report.

Now proceed to "How to invoke" below with the captured `Campaign ID` as the `-c` value.

### Step 5 — After bulk-import succeeds, hand off to tl-report-builder

The pipeline for new-report mode is **import + configure**, executed in order:

1. **`tl-import` (this skill)** creates the bare container (Step 4) and runs `tl bulk-import` (the "How to invoke" section below) — the list is now attached to a real report.
2. **`tl-cli:tl-report-builder`** is then invoked in **enrich-existing mode** with the captured `Campaign ID`. It picks the right columns and widgets for `report_type`, polishes the title/description, generates takeaway insights, and persists the updates via `tl reports update <id>`.

After the bulk-import result table has been rendered to the user, invoke `tl-cli:tl-report-builder` with the report ID and let it own the metadata-configuration phase. The user sees: container created → list attached → report fully configured, all in one flow.

Don't try to pick columns/widgets/takeaways from inside `tl-import`. That's `tl-report-builder`'s job and duplicating it here drifts the two skills apart over time.

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

- **Doesn't pick columns, widgets, or takeaways.** That's `tl-cli:tl-report-builder`'s job — both for new-report-mode (where this skill hands off after bulk-import) and for filter-driven reports (where this skill isn't involved at all). The container this skill creates is intentionally bare.
- **Doesn't build filter-driven reports** — keyword search, topic filters, demographic floors, brand exclusions, look-alikes, MSN/TPP scoping, date scopes. Those go to `tl-cli:tl-report-builder` directly. This skill only handles hand-picked lists.
- **Doesn't resolve identifiers ahead of time** — no `tl db pg` / raw SQL to look up channel IDs from URLs / handles. `tl bulk-import` does that server-side and auto-creates anything missing. Pre-resolution wastes credits, misses the auto-create path, and is the kind of detour the skill is designed to avoid.
- **Doesn't validate identifiers ahead of time** either — submit and let the per-row `reason` tell the user which ones failed. Pre-checking with `tl channels show` / etc. is wasteful (metered) and adds latency.
- **Doesn't sweep duplicates** from the user's input list — submit them as-is. The response will mark the second occurrence as `Duplicate`, which is more informative than silently deduping.
