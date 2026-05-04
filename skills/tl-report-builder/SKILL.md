---
name: tl-report-builder
description: Build TL saved-report configurations from natural-language requests. Generates a valid JSON campaign schema (filterset + columns + widgets + pagination) for the four report types — content (1), brands (2), channels (3), sponsorships (8) — plus a few key takeaway insights about the result. Use when a TL team member asks to build, create, or save a report. Triggers on phrasings like "build a report", "create a campaign", "make a report on", "save a dashboard for", "find me channels for outreach", "all sponsorships for X", "report on Y brand", "channels matching Z".
---

# TL Report Builder Skill

Translate natural-language report requests into the campaign config JSON the TL dashboard accepts (a `Campaign` + `FilterSet` payload, ready to commit). The skill owns the orchestration end-to-end; sub-tools are invoked conditionally from within the Schema phase based on explicit criteria. Every phase may pause for follow-up interaction with the user when input is ambiguous, incomplete, or invalid.

## Core Objective

Produce two artifacts on every successful run:

1. **A valid campaign config JSON** matching the platform's `dashboard.models.Campaign` + `dashboard.models.FilterSet` schemas. Ready to commit via the campaign_maker INSERT path when running in a TL_DATABASE_URI-equipped runtime; otherwise displayed for manual save.
2. **A short list of key takeaway insights** about the resulting dataset — db_count, count_classification, top sample channels/deals, noise warnings, narrow-result notes, tool-output flags worth surfacing, and any unresolved follow-ups the user should know about.

## Architecture & Separation of Concerns

```
tl-report-builder/
├── SKILL.md          ← this file: orchestrates the 4 phases; defines tool-invocation criteria; describes follow-up rules
├── references/       ← supporting schemas, column definitions, glossaries — consumed by the phases
└── tools/            ← conditional executable markdown files; invoked from inside Phase 2 only when criteria fire
```

- **Scripts (the four phases) are deterministic functions as much as possible.** Each phase has a defined input contract, output contract, and a small set of decision rules. LLM judgment is reserved for cases where the input genuinely warrants it.
- **`references/` is the single source of truth** for schemas (filterset shape per report type) and column definitions. Phases consume them; phases don't duplicate or override them.
- **`tools/` are optional enrichments**, not phases. They live separately so they can be added or removed without touching the phase orchestration.

## Process Flow (Strictly Sequential)

Each phase consumes the previous phase's output. No phase runs out of order. No phase runs in parallel. Every phase may pause for a follow-up question with the user before proceeding.

```
USER_QUERY
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 1 — Report Selection                                              │
│   Input:    USER_QUERY                                                  │
│   Output:   ReportType ∈ {1 CONTENT | 2 BRANDS | 3 CHANNELS | 8 SPONS}  │
│   Tools:    none (heuristic over USER_QUERY only)                       │
│   ↘ FOLLOW-UP TRIGGER: report type ambiguous / input invalid → ask user │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │  ReportType
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 2 — Schema Phase + Validation                                     │
│   Input:    USER_QUERY, ReportType                                      │
│   Output:   { filterset, filters_json, cross_references,                │
│               _routing_metadata, _validation }                          │
│   Loads:    references/<intelligence|sponsorship>_schema.json           │
│             references/report_glossary.md (on-demand)                   │
│             tools/sample_judge.md (validation sub-step)                 │
│                                                                          │
│   Responsibilities:                                                     │
│     • Compose the FilterSet (filterset + filters_json + cross_refs)     │
│     • Apply defaults per ReportType (days_ago, channel_formats, sort)   │
│     • VALIDATE the FilterSet against live data:                         │
│         – db_count → threshold classify                                 │
│         – db_sample (LIMIT 10) → sample_judge                           │
│         – Decide: proceed | retry | alternatives | fail                 │
│         – Retry with feedback to T1/T2 (cap 3) on empty/too_broad       │
│                                                                          │
│   ┌─── Conditional Tool Invocation (within Phase 2 only) ─────────────┐ │
│   │   T1  tools/topic_matcher.md           — fires per criteria       │ │
│   │   T2  tools/keyword_research.md        — fires per criteria       │ │
│   │   T3  tools/database_query.md          — cross-reference query    │ │
│   │   T4  tools/name_resolver.md           — fires per criteria       │ │
│   │   T5  tools/similar_channels.md        — fires per criteria       │ │
│   │   sample_judge  tools/sample_judge.md  — validation sub-step      │ │
│   │                                                                    │ │
│   │   Tools are NOT phases. See "Conditional Tool Invocation" below   │ │
│   │   for explicit criteria. Tool warnings propagate to Phase 4.      │ │
│   └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│   ↘ FOLLOW-UP TRIGGERS:                                                 │
│      • Filters missing or incomplete (e.g., no topic + no entity-name) │
│      • Filter inputs ambiguous (vague keywords, unclear targeting)     │
│      • Tool-output requires confirming an assumption before proceeding │
│      • Multi-candidate name resolution surfaced an ambiguity (T4)      │
│      • Cross-reference query (T3) returned an unexpected size or       │
│        timed out — confirm narrowing with the user                     │
│      • Validation: sample_judge returned looks_wrong → Mode B prompt   │
│        (save anyway / refine / cancel)                                 │
│      • Validation: 3 retries exhausted on empty/too_broad → fail mode  │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │  validated schema
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 3 — Columns Phase                                                 │
│   Input:    validated schema, ReportType                                │
│   Output:   { columns, dataset_structure, pending_refinement_sugg. }    │
│   Loads:    tools/column_builder.md (always — picks the columns)        │
│             references/columns_<type>.md (catalog)                      │
│             references/sortable_columns.json                            │
│                                                                          │
│   Responsibilities:                                                     │
│     • Select relevant columns based on ReportType + filters + intent   │
│     • Ensure selected columns are valid for the chosen ReportType      │
│     • Ensure compatibility between selected columns                    │
│     • Prepare dataset structure aligned with the selected columns      │
│     • Run validation:                                                  │
│         – Schema compliance (all columns exist for ReportType)         │
│         – Data consistency (column types align with sort + filters)    │
│         – Pagination defaults applied per ReportType                   │
│                                                                          │
│   ↘ FOLLOW-UP TRIGGERS:                                                 │
│      • Column selection requires user confirmation (e.g., template     │
│        reference + extra columns user enumerated explicitly)           │
│      • Selected columns incompatible with each other or with filters   │
│      • No columns provided AND no clear intent → suggest defaults      │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │  + columns
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 4 — Widget Phase (FINAL)                                          │
│   Input:    validated schema, columns, ReportType                       │
│   Output:   FINAL { campaign_config_json, takeaways }                   │
│   Loads:    tools/widget_builder.md (always — picks the widgets)       │
│             references/widgets.md (catalog consumed by widget_builder)  │
│             references/<schema>.json (final-validation source of truth) │
│                                                                          │
│   Responsibilities:                                                     │
│     • Define aggregations (sums, averages, counts, breakdowns)          │
│     • Configure widgets aligned to ReportType + filters + columns      │
│     • Type-3: subscriber/views aggregators                             │
│     • Type-8: count_sponsorships, sum_price (axis branches on          │
│       publish_status — send_date for proposals, purchase_date for sold)│
│     • histogram_bucket_size set per date range                         │
│     • PERFORM FINAL JSON-SHAPE VALIDATION of the campaign config:      │
│         – All Phase 2 + Phase 3 + Phase 4 outputs compose validly      │
│         – campaign_maker RLS pre-check (created_by_campaign_maker=TRUE,│
│           type=2 DYNAMIC, valid report_type, non-empty columns)        │
│     • Generate report_title + report_description from final config     │
│     • Compose key takeaway insights                                    │
│                                                                          │
│   ↘ FOLLOW-UP TRIGGERS:                                                 │
│      • Widget or aggregation preferences need user confirmation        │
│      • Desired breakdowns/groupings ambiguous                          │
│      • No aggregation requested → suggest defaults per ReportType      │
│      • Final validation surfaced issues that need user resolution      │
└─────────────────────────────────────────────────────────────────────────┘
```

There is no fifth phase. Phase 4's output IS the deliverable: a complete, validated campaign config + takeaways. Display + save are runtime concerns around the output (handled by the calling environment: SantaClaw commits via campaign_maker; humans copy JSON).

## Phase 1 — Report Type Selection (detail)

Phase 1 is heuristic-only — no `tl db pg`, no tool prompts. It reads `USER_QUERY` and emits one of `{1, 2, 3, 8}` (or asks a clarifying question). Phase 1's correctness is the foundation everything downstream rests on; getting the type wrong forces the wrong schema, the wrong column catalog, and the wrong widget catalog.

### Routing logic

Read `USER_QUERY` and apply in order:

1. **Explicit type signals** — if the user said "uploads / videos / individual videos / per-video" → type 1. "Brands report / advertisers report / competitor research" → type 2. "Channels / creators / youtubers / publishers" → type 3. "Sponsorships / deals / adlinks / pipeline / sales pipeline / sponsorship management" → type 8.
2. **Deal-stage jargon** — see `report_glossary.md` "Deal-stage jargon" table. If the user says "booked / sold / won / closed / proposed / pending / matched / reached out / partnership / partnerships", they almost certainly mean type 8 — the deal pipeline. **Don't let "channels" / "creators" inside the same sentence override this** — "partnerships with beauty creators" is type 8 with a clarification opportunity, not type 3 with keyword-routing.
3. **Ambiguous terms from `report_glossary.md` "Ambiguous / dangerous terms"** → surface a clarifying question rather than guess. Examples: "campaign report", "sponsors report", "creator report" (singular), "performance report", "pipeline" without context.
4. **Default when "report" is unqualified + the request is about creators** → type 3.
5. **Vague / under-specified** ("Build me a report") → ask: "What kind of report? Channels (creators), uploads (videos), brands, or sponsorship deals?"

### Authoritative routing examples

These two examples anchor the highest-risk routing failures. The skill MUST handle them per the expected behavior.

#### G07 — partnership routing (silent-ship trap)

**`USER_QUERY`**: `"Show me partnerships from last quarter for beauty creators"`

**Trap**: a naïve heuristic sees "creators" → routes to type 3 (CHANNELS). That's wrong.

**Correct routing**: type 8 (SPONSORSHIPS). "Partnerships" is type-8 deal-stage jargon per `report_glossary.md`. The "beauty creators" phrase is a *channel-filter clarification opportunity*, not a topic-keyword for a channels report.

**Phase 1 output**:
```
report_type: 8
clarifying_question (optional): "Which beauty creators specifically — by name, or filter by content_categories: ['beauty']?"
```

This is a v1-known weakness (`_SPONSORSHIP_KEYWORDS = {pipeline, deal, deals, adlink, adlinks}` did NOT contain "partnership") that the v2 skill must catch.

#### G06 — vague query (ask, don't guess)

**`USER_QUERY`**: `"Build me a report"`

**Trap**: hallucinate a default report type and start emitting filters.

**Correct routing**: surface a follow-up question, do not proceed to Phase 2.

**Phase 1 output**:
```
follow_up: "What kind of report would you like? Choose one:
  - Channels (creators) — find YouTube channels matching some criteria
  - Uploads (videos) — find specific videos
  - Brands — find advertisers / sponsors aggregated across mentions
  - Sponsorships — track deal pipeline and sold deals"
```

Phase 2 doesn't fire until the user picks.

### Hand-off to Phase 2

Phase 1 emits `{ report_type: <int>, clarifying_questions: [...] | [] }`. Phase 2 reads `report_type` to pick the right schema (`intelligence_schema.json` for 1/2/3, `sponsorship_schema.json` for 8) and to gate which Phase 2 tools fire (e.g., `topic_matcher` skips for type 8; `keyword_research` skips for type 8).

## Conditional Tool Invocation

Tools are optional enrichments invoked from inside Phase 2. Each fires only when its criteria are explicitly met. Each may emit `warnings: [...]` that propagate to Phase 4's takeaways.

### T1 — `tools/topic_matcher.md`
**Fires when**: `ReportType ∈ {1, 2, 3}` AND USER_QUERY mentions a topic concept that could plausibly map to a curated topic in `thoughtleaders_topics`.
**Skipped when**: `ReportType == 8` (sponsorships don't use topic matching at the SQL level) OR USER_QUERY is purely an entity-name lookup ("emails for these channels").
**Output**: per-topic verdicts (strong/weak/none) + summary. If `summary.strong_matches` non-empty, the topic's curated `keywords[]` array drives the keyword_groups in the filterset.

### T2 — `tools/keyword_research.md`
**Fires when**: `ReportType ∈ {1, 2, 3}` AND `topic_matcher.summary.strong_matches.length == 0` AND no entity-name anchor (`channel_names` / `brand_names` / `similar_to_channels`) is present in USER_QUERY.
**Skipped when**: any of the above conditions fail. **Crucially, skipped when the user enumerates specific channels or brands** — those provide the filter anchor; keyword research is wasted work.
**Output**: validated `KeywordSet` (head/sub_segment/long_tail + content_fields + recommended_operator + per-keyword `db_count`).

### T3 — `tools/database_query.md` (cross-reference query)
**Fires when**: the user's request includes a **cross-reference** condition — a sponsorship/proposal/pipeline history filter that gates the main report's channel set. Examples: "NOT proposed to Brand X" → `cross_references` entry; "channels from our 2025 gaming pipeline with >$5K price" → `multi_step_query`.
**Skipped when**: the main report is type 2 (BRANDS) or type 8 (SPONSORSHIPS) — `cross_references` only applies to types 1 and 3. Also skipped when the condition is expressible as a typed FilterSet field (`msn_channels_only`, `tl_sponsorships_only`) or is a name lookup (T4).
**Behavior**: mirrors v1's existing cross_references catalog (`exclude_proposed_to_brand`, `include_proposed_to_brand`, `include_sponsored_by_mbn`) and `multi_step_query` mechanism. The only thing v2 changed is **extracting this logic to a dedicated tool file**; the catalog, defaults, and status IDs are unchanged.
**Output**: a `cross_references_entry` to append at the top level of the create_report config, OR a full `multi_step_query` payload that wraps the create_report. Caller composes into the final response.
**Hard rule**: sponsorship-side `multi_step_query` source queries default to the last 12 months when the user's framing is "currently / active" without explicit dates (v1 line 112).

### T4 — `tools/name_resolver.md`
**Fires when**: USER_QUERY enumerates specific channel or brand names that need to be resolved to IDs.
**Skipped when**: no entity names mentioned.
**Behavior**: progressive matching — exact → ILIKE substring → emoji-stripped → fuzzy. Surfaces match-quality and ambiguity (>1 active candidate) explicitly.
**Output**: `{ name → entity_id }` mapping per entity type, plus an `ambiguities: [...]` list when user disambiguation is required (FOLLOW-UP trigger).

### T5 — `tools/similar_channels.md`
**Fires when**: USER_QUERY contains "like X" / "similar to X" / "creators inspired by X" / "channels in the style of X" patterns AND the seed channel(s) resolve via T4.
**Skipped when**: no similarity phrasing, or the report type is 8.
**Behavior**: simple wrapper. Resolves seed names via T4, then emits `filters_json: { similar_to_channels: [<canonical names>] }` for the platform's vector-similarity engine to expand at execution time.
**Output**: `{ filterset_patch: { filters_json: { similar_to_channels: [...] } }, anti_overlap: { drop_if_present: [...] } }`. Caller merges the patch and drops any overlapping keyword/topic fields.

### Phase 2 validation sub-tool

**`tools/sample_judge.md`** — fires inside Phase 2's validation step.
**Fires when**: `ReportType ∈ {1, 2, 3}` AND `db_count` classification is `narrow` / `normal` / `broad` (i.e., not `empty` and not `too_broad` — those go straight to retry without sample inspection).
**Skipped when**: type 8 (deal sample shape ≠ channel sample shape) OR `db_count` was `empty` / `too_broad` (retry path).
**Output**: `{ judgment: matches_intent | looks_wrong | uncertain, reasoning, noise_signals, matching_signals }`. `looks_wrong` triggers a Phase 2 follow-up to the user with structured options (save anyway / refine / cancel). `widget_builder` (Phase 4) only fires once Phase 2 emits a validated FilterSet.

### Phase 3 sub-tool

**`tools/column_builder.md`** — always fires in Phase 3.
**Behavior**: same builder-prompt pattern as `widget_builder`. Reads `REPORT_TYPE`, `FILTERSET`, `ROUTING_METADATA`, plus `references/columns_<type>.md` and `references/sortable_columns.json`. Picks 5–10 standard columns (up to 13 with intent), validates sort, queues custom-formula refinement suggestions.
**Output**: `{ columns: {...}, dataset_structure: {...}, pending_refinement_suggestions: [...], _column_metadata: {...} }`.

### Phase 4 sub-tool

**`tools/widget_builder.md`** — always fires in Phase 4. Phase 2's validation already cleared the FilterSet, so widget_builder runs unconditionally.
**Behavior**: mirrors v1's widget-builder approach. Reads `REPORT_TYPE`, `FILTERSET`, `COLUMNS`, `ROUTING_METADATA`, plus `references/widgets.md`. Picks 4–6 widgets from the type's catalog, applies intent-driven swaps, handles type-8 axis branching, sets `histogram_bucket_size`.
**Output**: `{ widgets: [...], histogram_bucket_size: "week"|"month"|"year", _widget_metadata: {...} }`.

## Phase 2 — Validation step (detail)

Phase 2's validation step is the **mandatory gate** between FilterSet composition and downstream phases. The skill MUST validate the composed FilterSet against live data before handing off to Phase 3 — silent emission of a broken FilterSet is the failure mode this step exists to prevent.

### Step 2.V1 — Translate FilterSet to count + sample SQL

Determined by `report_type`. Phase 2 builds two queries: `db_count` (scalar) and `db_sample` (LIMIT 10).

For type 3 (CHANNELS):
```sql
-- db_count
SELECT COUNT(*) FROM thoughtleaders_channel WHERE <predicate> LIMIT 1 OFFSET 0
-- db_sample
SELECT id, channel_name, reach FROM thoughtleaders_channel WHERE <predicate>
ORDER BY reach DESC NULLS LAST LIMIT 10 OFFSET 0
```

For types 1 / 2: same predicate against `thoughtleaders_channel` as a channel-level proxy (production runs against ES; the proxy is sufficient for a Phase 2 smoke check).

For type 8: predicate against `thoughtleaders_adlink` joined to brand + channel; date filter required.

### Step 2.V2 — Run `db_count` (with timeout retry)

```
tl db pg --json "<count_sql>"
```

If the query times out:
1. Drop the `channel_name ILIKE` half of each keyword predicate (description-only).
2. Retry once.
3. If still timing out: split predicate by `AND`, run sides separately, estimate intersection arithmetically.
4. If that fails too: `decision: "fail"` with diagnostic.

### Step 2.V3 — Apply threshold rules

| `db_count` | classification | next |
|---|---|---|
| 0 | `empty` | Step 2.V5 (retry — broaden) |
| 1–4 | `very_narrow` | Step 2.V4 (sample); proceed with warning |
| 5–50 | `narrow` | Step 2.V4 (sample); proceed with note |
| 51–10000 | `normal` | Step 2.V4 (sample) |
| 10001–50000 | `broad` | Step 2.V4 (sample); proceed with narrow-suggest |
| > 50000 | `too_broad` | Step 2.V5 (retry — narrow) |

### Step 2.V4 — Run `db_sample`, then `sample_judge`

```
tl db pg --json "<sample_sql>"
```

Pipe the sample (≤ 10 rows) into `tools/sample_judge.md` with `USER_QUERY`, `DB_SAMPLE`, and `VALIDATION_CONCERNS` (inherited from `keyword_research`'s warnings, if any).

Decision based on judgment:
- `matches_intent` → `decision: "proceed"` — emit validated FilterSet to Phase 3.
- `looks_wrong` → `decision: "alternatives"` — Mode-B follow-up to user (save anyway / refine / cancel). Skip Phase 3 + Phase 4.
- `uncertain` → `decision: "alternatives"` favoring "Refine" — surface ambiguity rather than ship silently.

### Step 2.V5 — Retry orchestration (cap: 3)

When `db_count` is `empty` or `too_broad`, emit structured feedback to whichever upstream signal produced the failing FilterSet:

| Source | Retry target | Feedback shape |
|---|---|---|
| Matched topics → keyword_groups | re-compose FilterSet with broader keywords from `topic.keywords[]` (beyond head) or relax operator AND→OR | `{issue, suggestion, previous_filterset}` |
| `keyword_research` output | re-invoke T2 with the failing keywords + retry hint | `{issue, suggestion}` |

Cap at **3 retries total**. After 3, `decision: "fail"` with diagnostic — better to honestly fail than infinite-loop.

**What does NOT trigger retry**:
- `sample_judge` returning `looks_wrong` — substantive failure (data sparsity or noise), not a shape failure. Retrying produces more noise. Go straight to `alternatives`.
- `db_count` in `narrow` (1–4) — proceed with warning; retry would lose the small but real signal.

### Step 2.V6 — Compose decision output

```json
{
  "decision": "proceed" | "alternatives" | "fail",
  "_validation": {
    "db_count": <int>,
    "db_sample": [<rows>],
    "count_classification": "empty" | "very_narrow" | "narrow" | "normal" | "broad" | "too_broad",
    "sample_judgment": "matches_intent" | "looks_wrong" | "uncertain" | null,
    "sample_judgment_reasoning": "<from sample_judge>",
    "validation_concerns": [/* accumulated from T2 + sample_judge */],
    "retries": <int>,
    "errors": [/* if fail */]
  },
  "alternatives_for_user": { /* present iff decision == "alternatives" */ }
}
```

Phase 3 reads `decision == "proceed"` to know it's safe to run. The `_validation` block carries through to Phase 4's takeaways (narrow-result notes, noise warnings, etc.).

### Phase 2 validation edge cases

| Case | Behavior |
|---|---|
| Type 8 with no date scope | Reject upfront (`decision: "fail"`) — sponsorship queries without dates are unbounded and meaningless. |
| Cross-references present | Resolve cross-reference IDs first via T3, then count/sample the main predicate. Adds 1–2 preliminary queries. |
| Brand/channel name lookups | All string-name resolutions happen via T4 BEFORE this validation step. The FilterSet entering validation has IDs, not names. |
| Inherited `validation_concerns` from T2 | Pass through to `sample_judge`'s `VALIDATION_CONCERNS` input verbatim. The judge biases toward `looks_wrong` when these are present and confirmed in samples. |

### Authoritative validation example — G11 (substring noise → Mode B)

This example anchors the canonical silent-ship-risk that Phase 2 validation exists to prevent. The skill MUST handle it per the expected behavior.

**`USER_QUERY`**: `"channels about IRS tax debt forgiveness programs"`

**Phase 2 composes a FilterSet**:
```json
{
  "filterset": {
    "keywords": ["IRS", "tax debt", "tax debt forgiveness", "tax debt relief"],
    "keyword_operator": "OR",
    "content_fields": ["channel_description", "channel_description_ai", "channel_topic_description"],
    "languages": ["en"],
    "channel_formats": [4],
    "sort": "-reach"
  },
  "_routing_metadata": {
    "intent_signal": null,
    "tool_warnings": [],
    "validation_concerns": [
      "'IRS' is a 3-character keyword and risks substring noise (matches 'first', 'irish', etc.) — keyword_research flagged this"
    ]
  }
}
```

**Step 2.V2 — `db_count`**:
```sql
SELECT COUNT(*) FROM thoughtleaders_channel
WHERE is_active = TRUE
  AND (description ILIKE '%IRS%' OR channel_name ILIKE '%IRS%' OR ...)
  AND language = 'en'
```
Returns `6,601`. Classification: `normal` (51–10000 bucket).

**Step 2.V4 — `db_sample` + `sample_judge`**:

`db_sample` returns the top 10 channels by reach. Top results include:
```
Cocomelon, Bad Bunny, Bruno Mars, BRIGHT SIDE, Selena Gomez,
That Little Puff, Taarak Mehta Ka Ooltah Chashmah, ...
```

`sample_judge` is invoked with `USER_QUERY` + `DB_SAMPLE` + `VALIDATION_CONCERNS`. It returns:

```json
{
  "judgment": "looks_wrong",
  "reasoning": "All 10 samples are music artists, children's content, or general entertainment — none are about IRS tax debt or financial services. Confirms the substring-noise warning from keyword_research: 'IRS' is matching inside 'first', 'irish', etc.",
  "noise_signals": ["3-char keyword 'IRS' matching unrelated channel descriptions"],
  "matching_signals": []
}
```

**Step 2.V6 — Decision**:

```json
{
  "decision": "alternatives",
  "_validation": {
    "db_count": 6601,
    "count_classification": "normal",
    "sample_judgment": "looks_wrong",
    "sample_judgment_reasoning": "Top 10 by reach: Cocomelon, Bad Bunny, Bruno Mars... — none about IRS tax debt; substring noise from short keyword 'IRS'",
    "validation_concerns": ["'IRS' substring noise confirmed in samples"]
  },
  "alternatives_for_user": {
    "mode": "B",
    "options": [
      "Save anyway — useful if you want to inspect the long tail manually",
      "Refine — drop 'IRS' as a standalone keyword; keep 'tax debt' / 'tax debt forgiveness' / 'tax debt relief' (longer phrases, less noise)",
      "Cancel — TL data may not have meaningful coverage for this niche"
    ]
  }
}
```

**Phase 3 and Phase 4 do NOT fire.** The skill surfaces the Mode-B prompt to the user. This is the architectural promise: catch substring-noise silent ships at validation time, before columns and widgets are wasted on a broken FilterSet.

This is the canonical regression test. Whenever Phase 2 validation changes, walk this example through and verify the outcome is still `decision: "alternatives"` with a Mode-B prompt — not a silent emit.

## Phase 3 — Columns Phase (detail)

Phase 3 picks the columns the saved report displays and the dataset shape that hangs off them. It runs after Phase 2 has produced a validated FilterSet and before Phase 4 emits widgets.

### Inputs

- `REPORT_TYPE` (1 / 2 / 3 / 8) from Phase 1.
- The validated schema produced by Phase 2: `filterset` + `filters_json` + `cross_references` (if any) + `_routing_metadata` (carries `intent_signal`, tool warnings, etc.).
- **Loaded on demand**:
  - `tools/column_builder.md` — the column-selection prompt (always invoked).
  - `references/columns_<type>.md` — full column catalog for the report type, consumed by `column_builder`.
  - `references/sortable_columns.json` — sort metadata, consumed by `column_builder` for sort validation.

### Process

1. **Pick columns via `tools/column_builder.md`.** Inject `REPORT_TYPE`, `FILTERSET`, `ROUTING_METADATA`, the `references/columns_<type>.md` content, and `references/sortable_columns.json`. The builder emits `{ columns, dataset_structure, pending_refinement_suggestions, _column_metadata }`. The builder handles default sets, intent-driven additions, niche-driven additions, sort validation, and custom-formula proactivity internally — don't pre-process those signals.
2. **Hand off to Phase 4.** The `pending_refinement_suggestions` carry through to Phase 4's takeaway message; the `columns` dict and `dataset_structure` feed `widget_builder` and final composition.

### Follow-up triggers (Phase 3)

These triggers are surfaced by `column_builder` when conditions arise:

- The user enumerated specific columns AND the type's default set differs → ask: "Use the template's columns, the columns you listed, or both?"
- A requested column doesn't exist for the report type (e.g., user asked for `Views` on a type-3 report) → ask: "[column] isn't available for [report type]; closest is [alternative]"
- No columns specified AND no clear intent → ask: "I'll use [type]'s default set unless you want a different focus (outreach / discovery / sponsorship-pitch)"
- Sort field references a column not in the emitted set → `column_builder` adds the column and flags in `_column_metadata.concerns_surfaced`; if the direction is invalid, surfaces a follow-up.

(The full output schema, hard rules, worked examples, and self-check live in [`tools/column_builder.md`](tools/column_builder.md). SKILL.md owns orchestration; the tool file owns the selection rules.)

## Phase 4 — Widget Phase + FINAL Validation (detail)

Phase 4 is the terminal phase. It picks widgets, performs FINAL JSON-shape validation against both schemas, and composes the user-facing deliverable: the campaign config + key-takeaway insights. (The live-data validation already happened in Phase 2 — Phase 4 trusts the FilterSet.)

### Inputs

- All Phase 2 + Phase 3 outputs (Phase 2's output is already validated against live data — no re-validation here).
- **Loaded on demand**:
  - `tools/widget_builder.md` — the widget-selection prompt (always invoked).
  - `references/widgets.md` — aggregator catalog + intent-driven widget patterns + type-8 axis branching (consumed by `widget_builder`).
  - `references/intelligence_schema.json` and `references/sponsorship_schema.json` — final JSON-shape validation source of truth.

### Process

1. **Pick widgets via `tools/widget_builder.md`.** Inject `REPORT_TYPE`, `FILTERSET`, `COLUMNS`, `ROUTING_METADATA`, and the `references/widgets.md` content. The builder emits `{ widgets, histogram_bucket_size, _widget_metadata }`. The builder handles type-8 axis branching and intent-driven swaps internally — don't pre-process those signals.
2. **FINAL JSON-shape validation pass.** Verify the composed config:
   - Every field in `filterset` exists in the schema and matches its declared type.
   - Every column in `columns` is in the type's column file.
   - Every aggregator in `widgets` is in the matching catalog (intelligence for 1/2/3, sponsorship for 8).
   - `sort` references an emitted column with allowed direction.
   - Type 8 has a date scope (`days_ago` or `start_date`/`end_date`).
   - When `cross_references` is present, `report_type ∈ {1, 3}`.
   - When `filters_json.similar_to_channels` is present, no overlapping `keywords` / `topics` fields.
   - `created_by_campaign_maker = TRUE`, `type = 2` (DYNAMIC), `report_type ∈ {1, 2, 3, 8}` — campaign_maker RLS prerequisites.
3. **Generate `report_title` and `report_description`** from the FilterSet + the user's original NL request. Title ≤ 60 chars; description 1–3 sentences summarizing intent + key filters.
4. **Compose key takeaway insights** — see "Takeaway-composition rules" below. These are the headline observations the user reads in the Phase 4 message. The `_validation` block from Phase 2 carries through here — narrow-result notes, sample_judge reasoning, and validation_concerns are all surfaced as takeaways.
5. **Emit the final deliverable.**

### Takeaway-composition rules

Takeaways are 2–4 plain-language insights drawn from the validated config + sample. Each takeaway falls into one of these patterns:

| Pattern | Example |
|---|---|
| **Result size** | "Found 247 channels matching your criteria — a normal-size result, ready to act on." |
| **Intent reflection** | "Optimized for outreach: the column set emphasizes deal history (`Sponsorships Sold`, `Last Sold Sponsorship`, `Outreach Email`) and demographic fit." |
| **Tool-warning surface** | "⚠️ The seed channel 'Sanky' had three TL candidates — confirmed with you that you meant the 1.2M-reach US channel." |
| **Sample-judge note** | "Top 10 sample channels look on-target — content matches the intended niche; no obvious noise." |
| **Narrow / broad note** | "📌 Result is narrow (8 channels). Consider broadening the reach floor or expanding the keyword set." |
| **Refinement nudge** | "Want a 'Views Per Subscriber' custom column to spot high-engagement creators? Reply 'add formula' and I'll add it." |

Keep it tight: 2–4 takeaways total. Don't write essays. Cite specific numbers/names so the user can verify.

### Follow-up triggers (Phase 4)

- Aggregation/widget preferences need confirmation — "Default widgets for [type] are [list]; want to add/remove anything?"
- FINAL JSON-shape validation surfaced an unfixable issue (e.g., emitted column doesn't exist, aggregator from wrong catalog) → "Can't ship config because [reason]. Fix [thing]?"

(The `sample_judge looks_wrong` Mode-B follow-up is a Phase 2 trigger now — it surfaces upstream of Phase 3 / Phase 4.)

### Output (the deliverable)

```json
{
  "campaign_config_json": {
    "type": 2,
    "report_type": <int>,
    "report_title": "<string ≤ 60 chars>",
    "report_description": "<1–3 sentences>",
    "filterset": { /* validated, from Phase 2 */ },
    "filters_json": { /* validated, from Phase 2 */ },
    "cross_references": [ /* optional, from T3 */ ],
    "columns": { /* from Phase 3 */ },
    "widgets": [ /* from Phase 4 */ ],
    "histogram_bucket_size": "week" | "month" | "year",
    "created_by_campaign_maker": true
  },
  "takeaways": [
    "<insight 1>",
    "<insight 2>",
    "<optional insight 3>",
    "<optional insight 4>"
  ],
  "_phase4_metadata": {
    "json_shape_validation_passed": <bool>,
    "tool_warnings_surfaced": [ /* the ones from _routing_metadata that ended up in takeaways */ ],
    "validation_inherited_from_phase2": {
      "db_count": <int>,
      "count_classification": "narrow" | "normal" | "broad" | ...,
      "sample_judgment": "matches_intent" | null
    }
  }
}
```

### Hard rules (Phase 4)

1. **`campaign_config_json` is the deliverable**, not a draft. After Phase 4, no further skill steps modify it.
2. **`type: 2` (DYNAMIC) and `created_by_campaign_maker: true`** are non-negotiable for the direct-DB-write path. Both are enforced by RLS server-side; emitting them keeps the skill consistent with the platform.
3. **Trust Phase 2's validation.** Phase 4 does NOT re-run db_count / db_sample / sample_judge — those already passed upstream. If Phase 2 emitted `decision: "proceed"`, the FilterSet is good. (Sample-judging is the architectural promise to catch silent ships of bad samples — it just lives in Phase 2 now.)
4. **JSON-shape validation rejection is a stop, not a warn.** If the final-shape validation finds an unfixable problem (column doesn't exist, aggregator from wrong catalog, missing required field), Phase 4 emits an error follow-up rather than emitting a partial config.
5. **Takeaways cite specifics.** Numbers, names, intent labels. Vague takeaways ("the report looks good") add no value.
6. **No new filters or columns in Phase 4.** Phase 4 doesn't reshape the FilterSet or add columns — it picks widgets, validates, and composes. Reshape requires looping back to Phase 2 or 3.
7. **Type-8 axis consistency.** Both `_over_<axis>` histograms in the same type-8 report use the SAME axis (per widgets.md type-8 axis branching).

## Follow-Up Interactions

Every phase has explicit conditions where it must pause and ask the user, rather than guess. Follow-ups are not failures — they're a design feature that prevents silent-ship regressions.

| Phase | Follow-up trigger | What the skill asks |
|---|---|---|
| **1** | ReportType ambiguous (e.g., "show me Nike" — brand report? sponsorship deals?) | "Should this be a [type X] report or [type Y]?" + 2–3 suggested options |
| **1** | Input invalid (no recognizable ReportType signal) | Suggest valid types with one-sentence each |
| **2** | Required filter missing (e.g., type 8 without a date range — unbounded query) | "What time period should I cover?" |
| **2** | Filter input vague (e.g., "high-engagement channels" — what threshold?) | "Define [threshold]: by [metric A] above N? by [metric B]?" |
| **2** | T4 returned ambiguous name resolution (>1 active candidate per name) | "Which one of these did you mean?" + option list |
| **2** | T3 cross-reference returned unexpectedly large or zero result set | "The preliminary query matched [N] entities — narrow the date range or status filter?" |
| **2** | Validation: sample_judge returned `looks_wrong` (G11-class noise) | Mode B prompt: save anyway / refine / cancel — with reason citing 2–3 specific noise samples |
| **2** | Validation: 3 retries exhausted on empty/too_broad | Surface diagnostic + suggest the user reformulate the request |
| **3** | Column template + extra columns the user listed differ from each other | "Use the template's columns, the columns you listed, or both?" |
| **3** | Selected columns incompatible (e.g., requested `Views` on a type 3 report) | "[column] isn't available for [report type]; closest is [alternative]" |
| **3** | No columns provided AND no clear intent | "I'll use [type]'s default set unless you want a different focus (outreach / discovery / sponsorship-pitch)" |
| **4** | Aggregation/widget preferences need confirmation | "Default widgets for this report type are [list]; want to add/remove anything?" |
| **4** | Final JSON-shape validation surfaced unresolved issues | "Can't ship config because [reason]. Fix [thing]?" |

Skills that follow up are skills users trust. Silent assumptions are silent regressions.

## Data Sources & What They Own

| Source | Authoritative For | Connection |
|---|---|---|
| **`tl db pg`** | Live data: topics, channels, brands, sponsorships, sponsorship-history M2M | tl-cli ≥ v0.6.2; sandboxed read-only SELECT, mandatory `LIMIT/OFFSET`, max 500 rows |
| **`references/intelligence_schema.json`** | Canonical filterset shape for types 1/2/3 (filter fields, defaults, validation rules) | Static file; consulted in Phase 2 (compose + validate) and Phase 4 (final JSON-shape validation) |
| **`references/sponsorship_schema.json`** | Canonical filterset shape for type 8 (status IDs, owner fields, date filters, filters_json semantics) | Static file; consulted in Phase 2 (compose + validate) and Phase 4 (final JSON-shape validation) |
| **`references/columns_<type>.md`** | Available columns + intent-driven default sets per ReportType | Static; consulted in Phase 3 |
| **`references/widgets.md`** | Widget aggregator catalog (intelligence + sponsorship), default sets, type-8 axis branching | Static; consulted in Phase 4 |
| **Conditional tools** (T1–T5) | Dynamic enrichment of the unified schema | Markdown files in `tools/` |

**Trust hierarchy:** `tl db pg` for any "does this row exist / how many" question; the schema files for filter shape and validation rules; the column files for "what's available to display." If a tool's resolved ID disagrees with the user's name (e.g., emoji-stripped match), surface the discrepancy rather than silently substitute.

## Quick Start

### Run the skill on a query (in a Claude Code session that has this skill loaded)

```
USER: Build me a report of gaming channels with 100K+ subscribers in English
```

Claude follows this SKILL.md, executing each phase in order. No external command needed — the skill IS the orchestration; `tl db pg` is invoked from within Phase 2/3/4 as needed; tools fire conditionally per their criteria.

> **Note**: how the final config is committed (DB insert path vs. UI paste vs. another mechanism) is being addressed separately. For now Phase 4 produces the validated JSON + takeaways and stops there.

## Reference Files

Load on-demand — don't read all upfront:

**Schema canonical sources** (consulted in Phase 2 + Phase 4)
- **[references/intelligence_schema.json](references/intelligence_schema.json)** — Filterset + filters_json shape for types 1 (CONTENT), 2 (BRANDS), 3 (CHANNELS). Filter field types, defaults (`days_ago: 730` when keyword_groups present, `channel_formats: [4]`, `sort: -reach`), enum constants (publish_status, content_aspects, channel_formats), validation rules (no `topics` field — translates to keyword_groups; required vs optional fields; mutually-exclusive options).
- **[references/sponsorship_schema.json](references/sponsorship_schema.json)** — Filterset shape for type 8 (SPONSORSHIPS). Distinct from intelligence_schema: no keyword_groups, status IDs (0–9), owner fields (owner_sales_id, owner_advertiser_id, owner_publisher_id), filters_json conventions, date-axis branching (send_date for proposal-stage statuses; purchase_date for sold).

**Available columns per ReportType** (consulted in Phase 3)
- **[references/columns_content.md](references/columns_content.md)** — Type 1: video-level columns. Each column block: display_name, backend_code, when-to-use, default-on flag.
- **[references/columns_brands.md](references/columns_brands.md)** — Type 2: brand-aggregated columns.
- **[references/columns_channels.md](references/columns_channels.md)** — Type 3: channel-level columns. Includes intent-driven default sets: discovery / outreach / sponsorship-pitch.
- **[references/columns_sponsorships.md](references/columns_sponsorships.md)** — Type 8: deal-level columns. Includes Channel-info columns reused from type 3 (TL Channel Summary, Topic Descriptions, Subscribers, USA Share, Demographics - Age Median).

**Widget catalog** (consulted in Phase 4)
- **[references/widgets.md](references/widgets.md)** — Aggregator keys split by intelligence (types 1/2/3) vs sponsorship (type 8) catalog. Default 5-widget sets per ReportType, intent-driven swap patterns, type-8 axis branching (`send_date` for pipeline, `purchase_date` for won deals), `histogram_bucket_size` rules.

**Filter semantics (cross-cutting)**
- **[references/report_glossary.md](references/report_glossary.md)** — Vocabulary disambiguation across the whole skill: report-type synonyms (uploads = content; channels = creators; campaign report ⇒ ambiguous), TL-specific terminology (Reach / PV / VG / MSN / TPP / MBN), deal-stage jargon (booked = sold = status 3; pipeline = active non-sold), field-pair disambiguation (reach vs projected_views vs youtube_views), defaults, filter-source decisions (typed field vs `filters_json`), common pitfalls.
- **[references/sortable_columns.json](references/sortable_columns.json)** — Sort metadata per column (asc-only / desc-only / both). Consulted in Phase 3's sort selection.

**Conditional tools** (loaded only when Phase 2 invokes them)
- **[tools/topic_matcher.md](tools/topic_matcher.md)** — Topic verdicts against live `thoughtleaders_topics`.
- **[tools/keyword_research.md](tools/keyword_research.md)** — ES-validated keyword set when no topic anchor exists.
- **[tools/database_query.md](tools/database_query.md)** — Cross-reference query: resolves a prerequisite condition into a set of IDs that the main FilterSet includes/excludes.
- **[tools/name_resolver.md](tools/name_resolver.md)** — Progressive name → entity_id matching with ambiguity surface.
- **[tools/similar_channels.md](tools/similar_channels.md)** — Look-alike helper: emits `filters_json.similar_to_channels` for the platform's vector-similarity engine.
- **[tools/sample_judge.md](tools/sample_judge.md)** — Sample inspection inside Phase 2's validation step (channel-name based; intelligence reports only). Catches substring noise (G11-class) before the FilterSet ships to Phase 3.
- **[tools/column_builder.md](tools/column_builder.md)** — Phase 3's column-selection prompt. Same builder-prompt pattern as `widget_builder`: explicit inputs, JSON output schema, selection process (defaults → intent additions → niche additions → sort validation → formula proactivity), worked examples per report type, hard rules. Consumes `references/columns_<type>.md` as the catalog.
- **[tools/widget_builder.md](tools/widget_builder.md)** — Phase 4's widget-selection prompt. Mirrors v1's widget-builder approach: selection guidelines, intent-driven swaps, type-8 axis branching, and worked examples per report type. Consumes `references/widgets.md` as the catalog.

**Examples & golden corpus**
- **[examples/golden_queries.md](examples/golden_queries.md)** — Representative NL inputs covering all four report types and the full mode space (proceed / alternatives / vague). Used during M9 shadow-mode comparison.

## Pagination Defaults (Phase 3 applies these unless USER_QUERY overrides)

| ReportType | Page size | Sort default | Notes |
|---|---|---|---|
| 1 (CONTENT) | 50 | `-views` | Per-video; longer pages tolerable |
| 2 (BRANDS) | 25 | `-doc_count` | Aggregated rows; smaller pages |
| 3 (CHANNELS) | 25 | `-reach` (default) / `-publication_date_max` (outreach intent) | Sort branches on intent_signal |
| 8 (SPONSORSHIPS) | 50 | `-purchase_date` (sold) / `-send_date` (proposal stages) | Axis branches on `publish_status` per sponsorship_schema |

## Safety

- **`tl db pg`**: read-only SELECT only. The skill never attempts INSERT/UPDATE/DELETE through this surface. Mandatory `LIMIT n OFFSET m`, max 500 rows. Forbidden function list: `random`, `pg_sleep`, `current_user`, `version`, `pg_read_file`, `lo_export`, `dblink`, `current_setting`, `set_config`.
- **Tool warnings**: every tool that resolves names with non-exact matching MUST surface the match-quality in `_routing_metadata.tool_warnings`. Phase 4 surfaces these in takeaway insights — silent name-substitution is forbidden.
- **Follow-ups over assumptions**: when a phase encounters ambiguity that affects the output, the skill MUST ask rather than guess. Phase-by-phase trigger list is in the "Follow-Up Interactions" section above.

## Self-Improvement

After every significant report-build task, ask:

1. **New filter field encountered or schema mismatch with the dashboard?** → Update `references/intelligence_schema.json` or `references/sponsorship_schema.json`.
2. **New column requested that isn't in the column list?** → Add to `references/columns_<type>.md` with `display_name`, `backend_code`, when-to-use.
3. **Conditional tool fired wrongly (false positive or false negative)?** → Refine the criterion in this SKILL.md's "Conditional Tool Invocation" section AND in the tool's own front-matter.
4. **Name resolution failed silently?** → Update `tools/name_resolver.md` matching strategy. Surface the discrepancy in tool warnings; never silently substitute.
5. **Pagination, sort, or aggregation default felt wrong?** → Update the "Pagination Defaults" table above + `references/columns_<type>.md` intent-default tables.
6. **Sample judge mis-routed (silent ship of bad sample, or false `looks_wrong`)?** → Update `tools/sample_judge.md` thresholds.
7. **Follow-up trigger missed (skill assumed instead of asking)?** → Add the trigger to the "Follow-Up Interactions" table; codify the question wording.
8. **New takeaway insight worth standardizing?** → Add to Phase 4's takeaway-composition rules in this SKILL.md.

The reference files are the source of truth for schemas and columns. SKILL.md is the orchestration spec. Tools are conditional sub-routines. Each layer's responsibility stays separate; bleeding logic across layers (e.g., column rules into the schema file) creates the duplication this architecture is designed to avoid.
