---
name: tl-save-report
description: |
  Save the results of an in-chat data-exploration session as a TL report. Triggers when the user wants to persist a channels / brands / videos (uploads) / sponsorships list or filtered set they've been working with — phrases like "save this as a report", "save the list", "turn this into a campaign", "persist this", "make a report from what you found", "save the result", "I want to come back to this". Asks the user up front whether to save it as a filter-style report (predicates re-evaluated against live data each run) or a list-style report (a frozen snapshot of the exact entity IDs from the session).
---

# tl-save-report

Persist what the user has been exploring as a saved TL report. The skill assumes the data-exploration phase has already happened — the agent doesn't re-run queries, doesn't re-validate the result set, doesn't ask the user what they were looking for. Its single job is **config-from-session**: build a campaign config that captures the user's intent, post it via `tl reports create --config-file`.

This is intentionally lighter than `tl-report-builder`. Report-builder runs a four-phase orchestration to TURN a natural-language request INTO a config; save-report TAKES a session that already produced data and writes that data out as a saved report. If the user is starting from scratch ("build me a list of …"), hand off to `tl-report-builder` — don't run save-report.

## When to invoke

**Invoke when** the user has been exploring data in the current session (running `tl db pg|fb|es` queries, structured `tl` commands, or both) and now wants to **save the result** as a report they can come back to. Trigger phrases include:

- "save this as a report" / "save the list" / "save the result"
- "turn this into a campaign" / "persist this"
- "make a report from what you found"
- "I want to come back to this" / "set up a report for these"

The entity being saved must be one of: **channels**, **brands**, **videos / uploads / articles**, or **sponsorships / deals**.

**Skip when**:

- The user wants the report **built from scratch** from a natural-language request (no prior session exploration to capture) → hand off to `tl-report-builder`.
- The user wants to **add to an existing report** (`"add these channels to report 1234"`) → hand off to `tl-import`.
- The user only wants the data **shown / counted / analysed in chat** without saving → stay in `tl`; don't invoke this skill.

## Step 1 — Detect the report type

Match the session's primary entity to one of four report types:

| Session entity | Report type | `report_type` code |
| --- | --- | --- |
| Channels | CHANNELS | `3` |
| Brands | BRANDS | `2` |
| Videos / uploads / articles | CONTENT | `1` |
| Sponsorships / deals / adlinks | SPONSORSHIPS | `8` |

If the session joined entities (e.g. channels with their recent sponsorships), pick the **one the user actually wants to save** and ask if unclear. The other side becomes either a column or a filter, not the report subject.

## Step 2 — Ask: filter-style or list-style?

This is the single most important decision; ask the user before assembling anything. Don't pick silently.

**Suggested wording**:

> Two ways to save this:
>
> • **Filter-style** — I map the criteria from this session (subscriber floor, content categories, keywords, date range, etc.) into the report's filters. The report stays live: every time someone re-runs it, the filters re-evaluate against current data and the result set refreshes.
>
> • **List-style** — I snapshot the exact entity IDs we found in this session. The list is frozen — it always shows these IDs, no filter logic. Useful when you've curated the set and don't want re-evaluation.
>
> Which do you want?

The two styles differ in **which part of the FilterSet you populate**:

- **Filter-style → predicate fields populated** (`keywords`, `min_reach`, `country`, dates, demographics, etc.). Through-table M2M fields stay empty.
- **List-style → through-table M2M fields populated** (`channels` / `brands` / `articles` / `sponsorships`). Predicate fields stay empty.

A hybrid (some predicates + some M2M IDs) is *legal* but rarely what the user asked for — confirm before mixing them.

### When filter-style is the right answer

Pick filter-style when the user's session was driven by criteria the platform's FilterSet can express directly — keyword searches over `title` / `summary` / `transcript` / channel description, attribute thresholds (`min_reach`, `min_views`, country / language), categorical scoping (content categories, demographics, MSN status), date ranges, similar-to-channels.

When the user said something like *"channels in the cooking niche with >100K subs, all-time"* — the criteria map cleanly into a FilterSet, and the user almost certainly wants the report to keep refreshing as new channels meet the bar.

### When list-style is the right answer

Pick list-style when:

- The session produced a **specifically curated set** the user wants frozen (manual review, similar-channel walks, cross-reference subtraction, sponsorship-history dedup) — *"these 14 channels are the ones we're pitching, save this exact list"*.
- The session's **filters can't be mapped** into FilterSet fields cleanly (custom raw-SQL joins, multi-source aggregation in `jq`/`duckdb`, anything where the filter logic lived in the shell pipeline rather than in the platform schema). The honest move is list-style.
- The user explicitly said *"snapshot"*, *"freeze"*, *"this exact list"*, *"don't re-evaluate"*.

### Filter-style — mapping session criteria into the FilterSet

The authoritative field catalogues live in the report-builder's references:

- **Types 1 / 2 / 3** (CONTENT, BRANDS, CHANNELS): [`../tl-report-builder/references/intelligence_filterset_schema.json`](../tl-report-builder/references/intelligence_filterset_schema.json)
- **Type 8** (SPONSORSHIPS): [`../tl-report-builder/references/sponsorship_filterset_schema.json`](../tl-report-builder/references/sponsorship_filterset_schema.json)

Don't invent fields. The schema's keys are the only ones the platform accepts; unknown keys come back as `400 Invalid filterset.<field>`.

Common mappings (use the schema file for the full list):

| Session criterion | FilterSet field |
| --- | --- |
| Topic keywords (`"crypto"`, `"biohacking"`) | `keywords[]` + `keyword_operator` (`AND`/`OR`) + `content_fields[]` |
| Subscriber floor | `min_reach` |
| Views / impression floor | `min_views`, `min_impression` |
| Content category | `content_categories[]` |
| Country / language | `country`, `language` |
| MSN-only | `msn_channels_only: true` |
| Demographics (age / gender / geo) | `demographic_male_share`, `demographic_usa_share`, `demographic_geo`, etc. |
| Publication date range | `start_date`, `end_date`, or `days_ago` |
| Sponsorship date range (type 8) | `start_date` / `end_date` (send axis), `createdat_from` / `createdat_to` (created axis) |
| Cross-reference (`"not pitched to brand X"`) | `cross_references[]` |
| Similar-to-channels | `filters_json.similar_to_channels[]` |
| Brand mention filter | `sponsored_brand_mentions[]` (via `filters_json`) |
| Publish-status (sponsorships) | `publish_status` |

If the session used filters that don't map cleanly, tell the user: *"I can't map [the specific predicate] into a FilterSet — the platform doesn't expose that field directly. Want to fall back to list-style for this report?"*

### List-style — populating the M2M

Collect the entity IDs from the session results into a single array and place them in the corresponding through-table M2M field:

| Entity | FilterSet M2M field | ID shape | Exclude variant |
| --- | --- | --- | --- |
| Channels | `channels` | integer IDs | `exclude_channels` |
| Brands | `brands` | integer IDs | `exclude_brands` |
| Videos / uploads / articles | `articles` | composite string `<channel_id>:<youtube_id>` (matches ES `_id`) | `exclude_articles` |
| Sponsorships | `sponsorships` | integer IDs (AdLink IDs) | `exclude_sponsorships` |

**Article IDs are the composite string form**, not bare YouTube video IDs. If the session has YouTube IDs (`dQw4w9WgXcQ`) without channel prefixes, fetch `channel.id` for each via `tl db es` and rebuild the composite form before saving.

All other FilterSet predicate fields stay empty (`null` or omitted). Populating both a predicate AND the M2M creates a hybrid filter — the platform will still accept it, but the result set then becomes "IDs in the M2M that ALSO pass the predicate", which is almost never what the user said they wanted. Confirm before mixing.

The `exclude_*` variants pair with a separate predicate-style FilterSet — useful when the user said *"channels matching X, except these specific IDs"*. That's a hybrid by design; both halves get populated.

## Step 3 — Title and description (mandatory)

`tl reports create` rejects with HTTP 400 if either is missing — the validation regression has happened before. Always generate both:

- **`report_title`** — ≤ 60 chars. Capture the niche or intent: *"TPP fintech channels — May 2026"*, *"Speedcubing channels — curated list"*, *"Q1 2026 sold sponsorships, beauty brands"*.
- **`report_description`** — 1–3 sentences. Summarise what's in the report and how it was assembled. **Mention "filter-style" or "list-style" explicitly** so future readers know what they're looking at (list-style reports can look identical to filter-style ones from the dashboard if nobody documents the choice).

Propose values and let the user edit. Don't ship blank strings.

## Step 4 — Pick columns

Use the type's default column set; agents shouldn't compose columns from scratch when the session didn't specify any. Defaults live in:

- Type 1: [`../tl-report-builder/references/columns_content.md`](../tl-report-builder/references/columns_content.md)
- Type 2: [`../tl-report-builder/references/columns_brands.md`](../tl-report-builder/references/columns_brands.md)
- Type 3: [`../tl-report-builder/references/columns_channels.md`](../tl-report-builder/references/columns_channels.md)
- Type 8: [`../tl-report-builder/references/columns_sponsorships.md`](../tl-report-builder/references/columns_sponsorships.md)

If the session showed the user specific columns (`"show reach, subscribers, country"`), include those PLUS the type's required defaults. Validate that the `sort` value references a column that's actually present in the emitted `columns` dict — otherwise the report fails to render.

For **custom columns** (computed formulas the user defined inline during the session), include them under `columns._custom` per the column-builder convention; consult the type's `columns_<type>.md` for the custom-column shape.

## Step 5 — Pick widgets

Use a default set per report type. Don't over-engineer — the user can refine via `tl reports update` after saving. Widget catalogues:

- Types 1 / 2 / 3: [`../tl-report-builder/references/intelligence_widget_schema.json`](../tl-report-builder/references/intelligence_widget_schema.json)
- Type 8: [`../tl-report-builder/references/sponsorship_widget_schema.json`](../tl-report-builder/references/sponsorship_widget_schema.json)

Pick 4–6 widgets. For type 8 specifically, the schema's `_tl_axis_branching` rules pick the correct axis based on which date field the FilterSet populates (`send_date` for proposals, `purchase_date` for sold).

For **list-style** reports the widgets still render — they aggregate over the frozen ID list. Pick the same defaults as filter-style; the user reading the saved report wants the dashboard view either way.

## Step 6 — Assemble the config

Final config shape (`Campaign` + `FilterSet` + columns + widgets):

```json
{
  "type": 2,
  "report_type": 1 | 2 | 3 | 8,
  "report_title": "...",
  "report_description": "...",
  "filterset": { ... },
  "columns": { ... },
  "widgets": [ ... ],
  "histogram_bucket_size": "month",
  "sort": "-reach"
}
```

`type=2` (DYNAMIC) is the campaign-model contract; don't change it.

Write to a portable temp file and verify the file exists before saving:

```bash
TMP=$(mktemp -t tl-save-report-XXXX.json)
cat > "$TMP" <<'EOF'
{ ...config... }
EOF
ls -la "$TMP"   # verify before save
```

**Don't write the transport file under the user's project directory.** It's a transport, not a deliverable.

## Step 7 — Save

Two save paths, pick by style:

**List-style — `tl reports save-list`** is the simpler path. It accepts an entity + ID file + title + description, builds the minimal config, and POSTs in one call. Skip steps 4–6 entirely when you take this route — the command's defaults handle them, and the user can refine later via `tl reports update`.

```bash
# Write the IDs (one per line — integers for channels/brands/sponsorships;
# composite `<channel_id>:<youtube_id>` strings for articles).
printf '5607\n12345\n67890\n' > "$IDS"

tl reports save-list channels --ids-file "$IDS" \
    --title "TPP fintech — May 2026 curated" \
    --description "List-style: 3 channels hand-picked after the May 2026 review pass." \
    --yes --json
```

**Filter-style — `tl reports create --config-file`** is the path that needs the full config (columns + widgets + sort built from steps 4–6):

```bash
tl reports create --config-file "$TMP" --yes --json
```

- `--yes` skips the confirmation prompt (the user already chose).
- `--json` makes the response parseable so you can extract `report_url` and `campaign_id` cleanly.
- `--config-file` (not `--config`) sidesteps shell-quoting issues with apostrophes / dollar signs / backticks in titles or keywords.

On success the response envelope contains:

```json
{
  "results": [{
    "campaign_id": 12345,
    "report_url": "/dashboard/reports/12345/",
    "unresolved_names": []
  }],
  "usage": { "credits_charged": ..., "balance_remaining": ... }
}
```

On failure (HTTP 4xx / 5xx): **surface the error verbatim**. Do NOT silently report success. Common failure modes:

- `400 Missing required field: report_title` / `report_description` → you skipped step 3, go back.
- `400 Invalid filterset.<field>` → the mapping in step 2 produced an unknown FilterSet field; check against the schema and remove the offending key.
- `400 Invalid columns.<column>` → the chosen column isn't in the type's `columns_<type>.md` catalogue.
- `403 Forbidden` → the user lacks the plan required for this report type (Intelligence for 1/2/3 in some orgs; check `tl whoami`).

## Step 8 — Report back

Echo the saved URL + ID, plus a follow-up offer for refinement:

> Saved as report **12345**: https://app.thoughtleaders.io/dashboard/reports/12345/
>
> Want to refine the columns, widgets, title, or description? Tell me what to change and I'll run `tl reports update`.

The follow-up offer matters because **FilterSet changes (keywords, demographics, M2M lists) can't be patched in place** via `tl reports update` — they require saving a new variant. Surface that limitation only if the user actually asks to change FilterSet fields.

## Self-check before saving

1. `report_title` is non-empty and ≤ 60 chars.
2. `report_description` is non-empty, 1–3 sentences, explicitly says "filter-style" or "list-style".
3. `report_type` matches the session's primary entity (1 / 2 / 3 / 8).
4. `type` is `2` (DYNAMIC).
5. `sort` references a column actually present in `columns`.
6. **For filter-style**: no M2M `channels` / `brands` / `articles` / `sponsorships` populated unless the user explicitly asked for a narrow-to-these-IDs overlay (hybrid case).
7. **For list-style**: no predicate fields (`keywords`, `min_reach`, dates, etc.) populated — the M2M is the entire filter.
8. **For list-style with articles** (type 1): every entry in `filterset.articles` is the composite `<channel_id>:<youtube_id>` form, not a bare YouTube ID.
9. Transport file written to a portable temp path (not the user's working directory) and verified to exist before `tl reports create`.

## What this skill does NOT do

- **No Phase 1–4 orchestration**, no AI-driven keyword research, no name resolution, no `sample_judge` validation pass. The session already produced the data — re-running discovery would be wasted effort. If the user comes in with a natural-language request and no prior session, that's `tl-report-builder`'s job, not this skill's.
- **No editing of existing reports.** If the user wants to refine an already-saved report's columns, widgets, title, or description, run `tl reports update <id>` directly. For FilterSet refinements, the platform requires saving a new variant.
- **No bulk-importing into an existing report.** That's `tl-import`'s role. Save-report only creates new reports.
