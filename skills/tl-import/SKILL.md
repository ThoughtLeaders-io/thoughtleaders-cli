---
name: tl-import
description: Import a list of channels, brands, uploads (videos), or sponsorships into a ThoughtLeaders report — either an existing report (caller supplies `campaign_id` or a TL report URL) or a fresh new one (skill creates a minimal container, then populates). Superuser-only. **Trigger on explicit intent to import the listed entities into a report**, NOT on the mere presence of a list (a user can paste a list and want analysis, comparison, or similar-channel discovery — those go to `tl-cli:tl-report-builder` or `tl-cli:tl`). The deciding question is: *would the user be satisfied if those exact entities ended up as the report's contents, no transformation?* If yes, this is the skill. Phrasings: "import these channels into report 1234", "add brands to campaign 5678", "exclude these channels from report Z", "bulk-add these videos to report X", "create a new report with these channels: <list>", "make a campaign containing these brands: <list>".
---

# tl-import

Imports a list of identifiers (channels / brands / articles / sponsorships) into a report. Two flows depending on whether the user references an existing report or wants a new one — see "Decide which flow" below. Both end in the same step: `tl bulk-import` submits the identifiers, polls until done, and the skill renders a per-row result table.

## When to use

The deciding test is the **user's intent**, not just what they pasted. The user must want the listed entities to land in a report as-given — no filtering, no analysis, no similarity expansion on top.

Trigger on:

- "Import @mkbhd, @veritasium into report 1234" → **existing-report flow**
- "Add these brands to campaign 5678" → **existing-report flow**
- "Bulk-add this list of channels to report 999" → **existing-report flow**
- "Exclude these channels from report Z" → **existing-report flow**
- "Create a new report with these channels: \<list\>" → **new-report flow**
- "Make a campaign containing these brands: \<list\>" → **new-report flow**
- "Build me a report from these adlinks: \<list\>" → **new-report flow** *(the verb "build" doesn't matter — what matters is that the user wants exactly those adlinks in the report.)*

**Do NOT trigger** when the user pastes a list but wants something other than direct import — those belong to `tl-cli:tl-report-builder` or `tl-cli:tl`:

- *"Find me channels similar to these: \<list\>"* — discovery using the list as a seed, not as the answer.
- *"Build a report of TPP channels in the same niche as these: \<list\>"* — discovery with filters and similarity expansion.
- *"Compare engagement across these channels"* — analysis on top of the list.
- *"Show me which of these have sponsored fintech brands"* — filtered lookup.

If you're about to do anything beyond "put these exact entities into a report", the wrong skill is running.

Single-identifier requests still work for the import intent (the command accepts one). The reason to keep this skill separate from other report-edit flows: it's the only path that auto-creates channels from YouTube URLs / handles, and brands from website domains.

## Decide which flow

Look at the user's request and pick exactly one of three responses:

| Signal | Response |
|---|---|
| User references an existing report (campaign ID number, `?campaign=<id>` in a pasted URL, "report X", "this campaign") | **Existing-report flow** — skip to "Inputs to gather" |
| User explicitly asks for a new report ("new report", "a new campaign", "create a report with…", "make a campaign of…") | **New-report flow** — read "Create a fresh container first" below, then continue |
| User provides a list with no destination cue at all (no campaign reference AND no "new" wording) | **Ambiguous — ask once** before proceeding: *"Should I add these to an existing report (give me the report ID or URL), or create a new one?"* Wait for the answer. Then dispatch to the matching flow above. |

Never silently create a new report when the destination is ambiguous; never silently use an existing report when none was referenced. The skill's only acceptable action without a clear destination is to ask.

## Create a fresh container first (new-report flow only)

The user wants the report to contain exactly the identifiers they're about to import — nothing else. No keyword research, no discovery query, no review pipeline. Just a minimal container that holds the list. **The persistence step uses the same primitive `tl-cli:tl-report-builder` calls at the end of its workflow** (`tl reports create --config-file`), but with a tiny config and none of the upstream phases.

Steps:

1. **Title.** If the user gave one (e.g. *"create a Q1 cohort report with…"* → title *"Q1 cohort"*), use it. Otherwise ask once: *"What should I name the new report?"* Title must be ≤ 60 chars, non-empty.
2. **Description.** Auto-generate a 1-sentence description; don't ask the user. Format: `"Bulk-imported list of <N> <entity> (<YYYY-MM-DD>)."`. Required by the platform on save (not optional).
3. **Map entity → `report_type`:**
   - `channels` → **3** (THOUGHTLEADERS)
   - `brands` → **2** (BRANDS)
   - `articles` (uploads/videos) → **1** (CONTENT)
   - `sponsorships` (adlinks/deals) → **8** (CAMPAIGN_MANAGEMENT)
4. **Pick default columns.** Read the matching columns reference file in the sibling `tl-report-builder` skill and use its **"Defaults — always include"** section — that's where the canonical column list lives per type; do NOT restate it here. The four files:
   - channels → `../tl-report-builder/references/columns_channels.md`
   - brands → `../tl-report-builder/references/columns_brands.md`
   - articles → `../tl-report-builder/references/columns_content.md`
   - sponsorships → `../tl-report-builder/references/columns_sponsorships.md`

   Convert each display name from the "Defaults — always include" list into a column entry shape **`{"display": true, "width": "default"}`** — the `width` field is required by the dashboard's column renderer; without it, columns sometimes resolve but cells render empty. Use `"wide"` for narrative columns (e.g. `TL Channel Summary`, `Channel Description`, `Topic Descriptions`); use `"narrow"` for short numeric columns (e.g. `Status`, `Country`); `"default"` everywhere else is safe.

5. **Pick `dataset_structure`.** This block tells the dashboard's data plane how to query each row's cell values. **Without it the report saves but rows render empty** — see the bottom-of-section sanity check. Shape:

   ```json
   "dataset_structure": {
     "report_type": <same as the top-level report_type>,
     "page_size": 50,
     "sort": "<backend_code field, optionally -prefixed for descending>"
   }
   ```

   Per-type default sort. **Critical invariant:** the `sort` field must reference a `backend_code` whose display-name column is in the column set you emitted in step 4. The dashboard's renderer rejects sorts pointing at columns that aren't present in the report. So pick the intersection of (a) the type's "Defaults — always include" columns from `columns_<type>.md` and (b) sortable columns from `../tl-report-builder/references/sortable_columns.json`:

   | report_type | entity | default `sort` | maps to (must be in column set) |
   |---|---|---|---|
   | 3 | channels | `-reach` | `Subscribers` (in defaults) |
   | 2 | brands | `-doc_count` | `Mentions` (in defaults) |
   | 1 | articles | `-publication_date` | `Date` (in defaults) |
   | 8 | sponsorships | `-send_date` | `Scheduled Date` (in defaults) |

   If the user explicitly asked for a different sort, honor that — but if their preferred sort column isn't in the type's defaults, **add that column to the column set in step 4** before emitting the config. Sort pointing at an absent column re-creates the original render-failure bug.

6. **Compose the minimal config:**

   ```json
   {
     "report_title": "<from step 1>",
     "report_description": "<from step 2>",
     "report_type": <from step 3>,
     "type": 2,
     "filterset": {},
     "columns": <from step 4>,
     "dataset_structure": <from step 5>
   }
   ```

   `type: 2` is DYNAMIC (the only valid campaign type for save). `filterset: {}` is intentional — no keyword/topic/demographic filters; the report's contents will come entirely from the include list bulk-import populates next. **`dataset_structure` is what makes the rows render with actual values** — leave it out and the dashboard shows row numbers but blank cells.
7. **Persist via the same primitive `tl-report-builder` uses.** Write the config dict to a temp file using your file-writing tool — **do not use shell `echo` or heredocs**, those break on titles containing apostrophes, dollar signs, backticks, etc. The whole point of `--config-file` is to bypass shell quoting entirely. Pick any temp path the agent's filesystem tool can write to (e.g. `/tmp/tl-import-container.json` on Unix, the OS temp dir on Windows).

   Then run:

   ```bash
   tl reports create --config-file <path-you-just-wrote> --yes --json
   ```

   With `--yes --json` the CLI emits a single JSON document on stdout containing the save response — parse it with one `json.loads()` and pull out `campaign_id` (and `report_url` for the summary). If `tl reports create` returns HTTP 400 with `Missing required field: report_title` or `…report_description`, the config is malformed — re-check step 1/2.

8. **Run bulk-import, capture the result — but DO NOT render the success summary yet.** Hand off to the bulk-import path with the new `campaign_id` and execute "Inputs to gather" + the bulk-import call + the JSON-envelope parse. **Stop before** rendering the per-row classification table or any "import done" message. Step 9 below must run first; only then do you render the summary. If you find yourself about to emit the success markdown straight out of the bulk-import flow, stop — you skipped step 9.

9. **Post-import render check (must execute before any success summary is emitted).** The save accepts the config; the renderer can still drop columns silently (e.g. `sort` points at a column you didn't emit, or `width` is missing on entries that needed it). Run:

   ```bash
   tl reports run <campaign_id> --limit 3 --json
   ```

   - If `results` is non-empty AND each row has fields beyond just an ID → render works. Now surface the bulk-import success summary (headline + per-row classification table) plus the new report URL.
   - If `results` is non-empty but each row is mostly null/empty fields → the config has a render bug. Surface to the user **instead of** the normal success message: *"The bulk-import succeeded but the report is rendering with empty cells. Add columns via the dashboard UI, or delete and re-run the import."* Don't hide this — the import already happened; the user needs to know they have a partially-broken report. Still include the bulk-import's `inputs` classification table so they see what landed.
   - If `results` is unexpectedly empty (shouldn't happen post-bulk-import unless every row failed) → surface the bulk-import's `inputs` table to explain which rows failed; skip the "Created [report] and imported N" headline since N=0.

   *Cost: a small report-run credit. Worth it — silently handing the user a report whose cells are blank is worse than telling them upfront.*

Once step 9 passes, surface the new report URL alongside the bulk-import results in the final summary, e.g. *"Created [Q1 cohort](https://app.thoughtleaders.io/#/thoughtleaders?campaign=23859) and imported 50 channels:"* followed by the per-row table.

## Inputs to gather

Before running, confirm:

1. **Report ID** (`--campaign` / `-c`) — required. If the user pastes a TL URL (e.g. `https://app.thoughtleaders.io/#/thoughtleaders?campaign=23859&...`), the integer after `campaign=` is the ID. In the new-report flow, use the `campaign_id` returned by `tl reports create` above.
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

- Doesn't run `tl-report-builder`'s discovery pipeline (keyword research, topic matching, validation cycles, review). When a user gives a fixed list of identifiers, they've already done the discovery themselves — the report is a container for their list, not a query result. Use `tl-report-builder` only when the user wants you to *find* channels/brands/etc. by criteria.
- Doesn't change existing report metadata (title, description, columns, filters) after creation. For that, use the platform UI or a dedicated edit flow. The new-report flow in this skill sets minimum-required metadata once at creation and never revisits it.
- Doesn't validate identifiers ahead of time — submit and let the per-row `reason` tell the user which ones failed. Pre-checking with `tl channels show` / etc. is wasteful (metered) and adds latency.
- Doesn't sweep duplicates from the user's input list — submit them as-is. The response will mark the second occurrence as `Duplicate`, which is more informative than silently deduping.
