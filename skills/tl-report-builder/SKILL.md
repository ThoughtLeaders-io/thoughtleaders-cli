---
name: tl-report-builder
description: Build TL saved-report configurations from natural-language requests. Generates a valid JSON campaign schema (filterset + columns + widgets + pagination) for the four report types — content (1), brands (2), channels (3), sponsorships (8) — plus a few key takeaway insights about the result. Use when a TL team member asks to build, create, or save a report. Triggers on phrasings like "build a report", "create a campaign", "make a report on", "save a dashboard for", "find me channels for outreach", "all sponsorships for X", "report on Y brand", "channels matching Z".
---

# TL Report Builder Skill

Translate natural-language report requests into the campaign config JSON the TL dashboard accepts (a `Campaign` + `FilterSet` payload, ready to commit). The skill owns the orchestration end-to-end; sub-tools are invoked conditionally from within the Schema phase based on explicit criteria. Every phase may pause for follow-up interaction with the user when input is ambiguous, incomplete, or invalid.

## Core Objective

Produce two artifacts on every successful run:

1. **A valid campaign config JSON** matching the platform's `dashboard.models.Campaign` + `dashboard.models.FilterSet` schemas. Ready to be POSTed to the report-creation API endpoint (and PUT for subsequent edits); the skill itself never writes to the database directly.
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
│   Routing:  see "Phase 1 — Report Type Selection (detail)" below for   │
│             the routing rules + authoritative G07 / G06 examples       │
│   ↘ FOLLOW-UP TRIGGER: report type ambiguous / input invalid → ask user │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │  ReportType
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 2 — Schema Phase + Validation                                     │
│   Input:    USER_QUERY, ReportType                                      │
│   Output:   { filterset, filters_json, cross_references,                │
│               _routing_metadata, _validation }                          │
│   Loads:    references/<intel|sponsorship>_filterset_schema.json        │
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
│             references/<intel|spons>_widget_schema.json (catalog +     │
│                  axis branching + intent overrides; for widget_builder) │
│             references/<intel|spons>_filterset_schema.json (final      │
│                  JSON-shape validation source of truth)                 │
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
│         – API-contract pre-check (type=2 DYNAMIC, valid report_type,   │
│           non-empty columns, sort references an emitted column)        │
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

There is no fifth phase. Phase 4's output IS the deliverable: a complete, validated campaign config + takeaways. The save step happens **outside the skill**, via a `POST` (create) or `PUT` (edit) to the report-creation API endpoint. The skill itself never writes to the database directly — reads use raw `tl db es` (intelligence reports — types 1/2/3) or raw `tl db pg` (sponsorship reports — type 8); writes go through the API.

> **Save-mechanism policy**: A new API endpoint is required for report creation. It will support both `POST` (initial create) and `PUT` (subsequent edits) so reports can be modified without redoing the four phases from scratch. Until the endpoint is built, the skill stops at producing the JSON config + takeaways; the calling environment handles whatever save mechanism is current. **Reads via `tl db es` / `tl db pg` (engine routed by report type — see Step 2.V1), writes via the API** is the architectural split.

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

Phase 1 emits `{ report_type: <int>, clarifying_questions: [...] | [] }`. Phase 2 reads `report_type` to pick the right schema (`intelligence_filterset_schema.json` for 1/2/3, `sponsorship_filterset_schema.json` for 8) and to gate which Phase 2 tools fire (e.g., `topic_matcher` skips for type 8; `keyword_research` skips for type 8).

## Conditional Tool Invocation

Tools are invoked **from inside Phase 2 to figure out what the filter should be** — not as reactions to an existing filter. The user's natural-language request rarely names every filter field directly; tools resolve the gaps:
- The user said "gaming channels" — `topic_matcher` figures out which topic ID(s) and curated keywords expand from that.
- The user said "channels we've already proposed to Logitech" — `database_query` figures out which channel IDs the cross-reference condition resolves to.
- The user said "MrBeast and PewDiePie" — `name_resolver` figures out the corresponding `channels` IDs.
- The user said "no strong topic match" — `keyword_research` figures out a keyword candidate set from scratch.

Each tool fires only when its criteria are explicitly met (no automatic / speculative invocation). Each may emit `warnings: [...]` that propagate through `_routing_metadata` to Phase 4's takeaways. Tools never reshape filters that have already been composed; they inform composition before validation.

### T1 — `tools/topic_matcher.md`
**Fires when**: `ReportType ∈ {1, 2, 3}` AND USER_QUERY mentions a topic concept that could plausibly map to a curated topic in `thoughtleaders_topics`.
**Skipped when**: `ReportType == 8` (sponsorships don't use topic matching at the SQL level) OR USER_QUERY is purely an entity-name lookup ("emails for these channels").
**Output**: per-topic verdicts (strong/weak/none) + summary. If `summary.strong_matches` non-empty, the topic's curated `keywords[]` array drives the FilterSet's `keywords` field (with per-position `content_fields` set via `keyword_content_fields_map` when a keyword targets a non-default match surface). Phase 2 may also emit the matched topic IDs directly via the FilterSet's `topics` field — both paths are valid; pick by intent.

### T2 — `tools/keyword_research.md`
**Fires when**: `ReportType ∈ {1, 2, 3}` AND `topic_matcher.summary.strong_matches.length == 0` AND no entity-name anchor is present in USER_QUERY (i.e., the user did not name specific channels or brands, and did not use look-alike phrasing like "similar to X").
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
**Behavior**: mirrors v1's widget-builder approach. Reads `REPORT_TYPE`, `FILTERSET`, `COLUMNS`, `ROUTING_METADATA`, plus the matching widget schema (`intelligence_widget_schema.json` for types 1/2/3, `sponsorship_widget_schema.json` for type 8). Picks 4–6 widgets that add value to the user's prompt; applies intent-driven swaps per the schema's `_tl_intent_overrides`; handles type-8 axis branching per `_tl_axis_branching`; sets `histogram_bucket_size`.
**Output**: `{ widgets: [...], histogram_bucket_size: "week"|"month"|"year", _widget_metadata: {...} }`.

## Sort field — which phase owns it

`sort` is a `FilterSet` field on the Django model, so **Phase 2 picks the value when composing the FilterSet** — defaulting to the type's pagination default (`-reach` for type 3, `-views` for type 1, `-doc_count` for type 2, `-purchase_date` / `-send_date` for type 8 per axis branching) unless the user's intent overrides (e.g., outreach intent on type 3 → `-publication_date_max`).

**Phase 3 doesn't pick the sort value — it validates it.** The sort field must reference a column that's both (a) present in the emitted `columns` dict AND (b) has an allowed direction per `sortable_columns.json`. If a mismatch exists, Phase 3 either adds the column (so the sort is valid) or surfaces a follow-up. Phase 3 never silently changes the sort value Phase 2 set.

This split means: **sort value = Phase 2; sort viability = Phase 3**.

## Phase 2 — Validation step (detail)

Phase 2's validation step is the **mandatory gate** between FilterSet composition and downstream phases. The skill MUST validate the composed FilterSet against live data before handing off to Phase 3 — silent emission of a broken FilterSet is the failure mode this step exists to prevent.

**What validation actually does** (in plain terms): once the FilterSet is composed, run a script that fetches the data those filters would actually return — both the **count of matching entities** (how many channels / uploads / brands / deals the predicate matches) and a **small sample of representative rows** (10 rows, ordered by the canonical sort). Then compare both back against the user's original prompt and judge: *would shipping this FilterSet plausibly complete the user's request?* If yes → proceed. If no → surface alternatives or fail rather than silently emit. The judgment is the validation gate's whole point.

### Step 2.V1 — Translate FilterSet to count + sample query

Determined by `report_type`. Phase 2 builds two queries: `db_count` (scalar) and `db_sample` (LIMIT 10). **The data plane depends on the report type:**

| ReportType | Primary engine | Why |
|---|---|---|
| 1 (CONTENT) | **Elasticsearch** (`tl db es`) | Content text search at scale — keyword/phrase matching across uploads is what ES is built for. |
| 2 (BRANDS) | **Elasticsearch** (`tl db es`) | Same — brand mention detection and aggregation runs on ES. |
| 3 (CHANNELS) | **Elasticsearch** (`tl db es`) | Channel description/topic search at scale. |
| 8 (SPONSORSHIPS) | **Postgres** (`tl db pg`) | AdLink relations + status / owner / date filters live in PG; sponsorships are not text-searched. |

The skill's previous "everything via `tl db pg`" framing was the v1 prototype's smoke-check assumption. Postgres lacks trigram / FTS indexes on `description` and times out on multi-keyword OR predicates against the full channels table. **Use ES as the primary plane for intelligence reports**; PG remains a narrow fallback only when (a) the report type is 8, or (b) ES is unavailable AND the FilterSet has tight indexed-column predicates (reach floor, single keyword, narrow language) so the PG CTE workaround can complete.

#### Intelligence reports (1 / 2 / 3) — Elasticsearch query

Compose an ES search body. The index is fixed server-side; the client only sends the search body. **The doc-type filter, target fields, sort, and `_source` differ per report type — pick the matching block below.**

##### Type 3 (CHANNELS) — search the channel doc type

**Critical**: the ES index is sharded by quarter (`tl-platform-{year}-{quarter}` per `skills/tl/references/elasticsearch-schema.md` line 38), and channel parent docs are duplicated across every quarter shard the channel was active in. Without deduplication, both `track_total_hits` and a flat sample return inflated/duplicated results — verified against live data (a 614-distinct-channel result inflated to 20,876 docs; sample of 10 returned 10 identical rows). Type-3 ES queries MUST use a `cardinality` aggregation for the count and `collapse` on `id` for the sample.

```json
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        { "term":  { "doc_type": "channel" } },
        { "term":  { "is_active": true } },
        { "terms": { "language": ["en"] } },
        { "terms": { "format":   [4] } },
        { "range": { "reach": { "gte": 100000 } } }
      ],
      "must": [
        {
          "multi_match": {
            "query":   "<keyword>",
            "type":    "phrase",
            "fields":  ["name", "description", "ai.description", "ai.topic_descriptions"]
          }
        }
      ]
    }
  },
  "aggs": {
    "distinct_channels": { "cardinality": { "field": "id" } }
  }
}
```

The `must` array carries one `multi_match` entry per keyword, combined per `keyword_operator`: AND → list every `multi_match` inside `must` (each is required); OR → move them to a sibling `should` array and add `"minimum_should_match": 1`. The example above shows the single-keyword case; multi-keyword extensions follow that pattern.

For `db_count` on type 3: read `aggregations.distinct_channels.value`, NOT `total`. The `total` field counts documents (channel-doc duplicates included); `distinct_channels` counts unique channel IDs.

For `db_sample` (size 10) on type 3: same `query` body, plus:
```json
{
  "size": 10,
  "sort": [{ "reach": "desc" }],
  "_source": ["id", "name", "reach", "description"],
  "collapse": { "field": "id" }
}
```

**`collapse: { field: "id" }`** returns the top doc per channel ID, deduplicating across quarter shards. Without it, the sample returns the same channel multiple times.

**Note**: ES returns `name` for channels; the orchestration aliases it to `channel_name` before passing to `sample_judge` so the row shape matches the contract.

##### Type 1 (CONTENT) — search the article doc type

```json
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        { "term":  { "doc_type": "article" } },
        { "terms": { "channel.language": ["en"] } },
        { "terms": { "channel.format":   [4] } },
        { "range": { "publication_date": { "gte": "now-180d/d" } } }
      ],
      "must": [
        {
          "multi_match": {
            "query":   "<keyword>",
            "type":    "phrase",
            "fields":  ["title", "summary", "content"]
          }
        }
      ]
    }
  }
}
```

For `db_sample` on type 1: `size: 10`, `sort: [{ "publication_date": "desc" }]` (or `[{ "views": "desc" }]` per intent), `_source: ["id", "title", "channel.id", "publication_date", "views"]`.

**Important — channel name is NOT on article docs.** Per `skills/tl/references/elasticsearch-schema.md`, the embedded `channel.*` object on article docs contains only `{ id, country, language, content_category, format, publication_id }` — no `channel.name`. Filtering or selecting `channel.name` returns nothing silently.

To populate `channel_name` for the type-1 `sample_judge` row contract, the orchestration does a single PG batch lookup after the ES sample returns:

```sql
SELECT id, channel_name FROM thoughtleaders_channel WHERE id = ANY(<distinct channel.id values from ES sample>) LIMIT 50 OFFSET 0
```

Then enriches each sample row: `{ id: <article id>, title: <title>, channel_name: <from PG>, views: <views>, publication_date: <publication_date> }`. If the orchestration skips this enrichment, `sample_judge` will receive type-1 rows without `channel_name` — the contract treats it as optional secondary context (the primary identifier for type 1 is `title`), so judgment still works but with less context.

##### Type 2 (BRANDS) — aggregate over articles, group by brand

Type 2 reports are brand-aggregated, so the ES query is an aggregation, not a flat search.

**`tl db es` accepts at most one aggregation per request, recursively.** Top-level + sub-agg counts as 2 and is rejected (per `skills/tl/references/elasticsearch-schema.md` line 28). Type-2 validation therefore needs **multiple separate ES calls**, not one nested aggregation. The orchestration runs them in sequence and merges client-side.

##### Call 1 — distinct-brand count (`db_count`)

```json
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        { "term":  { "doc_type": "article" } },
        { "terms": { "channel.language": ["en"] } },
        { "range": { "publication_date": { "gte": "now-180d/d" } } }
      ],
      "must": [
        { "multi_match": { "query": "<keyword>", "type": "phrase", "fields": ["title", "summary", "content"] } }
      ]
    }
  },
  "aggs": {
    "distinct_brands": { "cardinality": { "field": "sponsored_brand_mentions" } }
  }
}
```

The cardinality aggregation returns the count of distinct sponsored-brand IDs matching the query in `aggregations.distinct_brands.value`. **This is the canonical type-2 `db_count` path**; do NOT use `sum_other_doc_count` from a `terms` agg as a count proxy — it counts documents (mentions) outside the returned buckets, not distinct omitted brands.

##### Call 2 — top brands and per-brand mention counts (`db_sample`)

```json
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        { "term":  { "doc_type": "article" } },
        { "terms": { "channel.language": ["en"] } },
        { "range": { "publication_date": { "gte": "now-180d/d" } } }
      ],
      "must": [
        { "multi_match": { "query": "<keyword>", "type": "phrase", "fields": ["title", "summary", "content"] } }
      ]
    }
  },
  "aggs": {
    "by_brand": {
      "terms": { "field": "sponsored_brand_mentions", "size": 10 }
    }
  }
}
```

Each `by_brand` bucket has `key` (brand ID) and `doc_count` (mentions count for that brand within the filter set). **The bucket's `doc_count` IS the per-brand mentions count — use it directly; don't add a `value_count` sub-agg (would violate the one-agg limit).**

##### Optional Call 3 — channels-count per brand (one extra call per brand if needed)

If `sample_judge` needs the distinct-channels count per brand for richer judgment, the orchestration can run one additional ES call per top brand (small N, ≤ 10). **Reuse the full Call 2 query body and add the brand-ID filter** — otherwise the count covers all channels mentioning that brand in the date/language scope, ignoring the report's content predicate.

```json
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        { "term":  { "doc_type": "article" } },
        { "terms": { "channel.language": ["en"] } },
        { "range": { "publication_date": { "gte": "now-180d/d" } } },
        { "term":  { "sponsored_brand_mentions": "<brand_id>" } }
      ],
      "must": [
        { "multi_match": { "query": "<keyword>", "type": "phrase", "fields": ["title", "summary", "content"] } }
      ]
    }
  },
  "aggs": {
    "channels_count": { "cardinality": { "field": "channel.id" } }
  }
}
```

The query body is identical to Call 2 except (1) the `terms` agg over `sponsored_brand_mentions` is replaced by a `term` filter on a single brand ID, and (2) the aggregation is now `cardinality` over `channel.id`. The result lives in `aggregations.channels_count.value`.

**Most type-2 validations skip Call 3** — the bucket `doc_count` from Call 2 is sufficient signal for `sample_judge` to judge whether the brands look on-target for `USER_QUERY`. Run Call 3 only when a per-brand drill-down is part of the user's intent (e.g., the user explicitly asked "which brands are mentioned across the most channels").

---

**Field-source notes** (per `skills/tl/references/elasticsearch-schema.md`):
- The "sponsored vs organic" distinction is **which keyword array you aggregate over**, not a `brand_mention_type` filter. Use `sponsored_brand_mentions` (sponsored only), `organic_brand_mentions` (organic only), or `all_brand_mentions` (both). There is no `brand_mention_type` field in ES.
- The aggregation field is the keyword array name (e.g. `sponsored_brand_mentions`), NOT `brands.id`. The bucket keys are the brand IDs.
- **Brand names are not in ES** — neither `brands.name` nor a top_hits inside the agg will return them. After Call 2 returns the buckets, the orchestration does a PG batch lookup against `thoughtleaders_brand` to resolve names: `SELECT id, name FROM thoughtleaders_brand WHERE id = ANY(<bucket_keys>) LIMIT 50 OFFSET 0`.

**Sample-row shaping for `sample_judge`** — orchestration merges Call 2's buckets + PG name lookup into the type-2 contract:
```
{ id: bucket.key, brand_name: <from PG lookup>, mentions_count: bucket.doc_count,
  channels_count: <from Call 3 if run, else null>, last_mention_date: null }
```
`last_mention_date` is omitted in the standard path (would require yet another ES call per brand and isn't critical for `sample_judge`'s judgment).

---

The ES `multi_match` with `type: "phrase"` matches the keyword as a contiguous phrase in any of the listed fields (no substring noise — phrase matching respects word boundaries). This is the architectural fix for the G03-class noise (`AI` matching `Tamil`/`captain`).

#### Sponsorship reports (8) — Postgres query

Type 8 stays on Postgres because the data plane is the sponsorship deal record (relations + status + dates), not text search.

**Use the denormalized view `v_adspot_brand_profiles`, not raw `thoughtleaders_adlink`.** The base adlink table does NOT carry `brand_id` or `channel_id` columns — those relations live on the view. Direct joins like `JOIN thoughtleaders_brand ON adlink.brand_id = ...` will be rejected by the planner because the FK doesn't exist on adlink.

The view exposes one row per (adlink × brand × channel) and surfaces these columns the skill cares about:
- `adlink_id`, `adlink_publish_status`, `adlink_created_at`, `adlink_updated_at`
- `brand_id`, `brand_name`
- `channel_id`, `channel_name`, `channel_msn_join_date`
- `organization_id`, `organization_name`, `organization_is_managed_services`
- `adlink_owner_advertiser_email`, `adlink_owner_sales_email`

**Important: count and sample MUST be deduped by `adlink_id`.** The view holds one row per `(adlink × brand × channel)` — a single sponsorship that involves multiple brands or multiple channel relations produces multiple rows. Type-8 reports count sponsorship records (AdLinks), not view rows. **Always use `COUNT(DISTINCT adlink_id)` for `db_count` and dedupe samples by `adlink_id`.** A globally-confirmed 184 view rows correspond to fewer underlying adlinks — direct `COUNT(*)` overcounts those cases.

##### Date-scope mapping (deterministic — no intent branching)

The FilterSet exposes exactly TWO date pairs for type 8, each pinned to a single underlying column. Validation never tries to infer a "smart" date axis from intent — that would be undefined when intent is unset and would silently disagree with the user's framing.

Per `references/sponsorship_filterset_schema.json`:

| FilterSet field | Underlying column on `thoughtleaders_adlink` | Where it lives |
|---|---|---|
| `start_date` / `end_date` / `days_ago` | `send_date` | base table only (NOT on view) |
| `createdat_from` / `createdat_to` | `created_at` | exposed on the view as `adlink_created_at` |

**Hard rule: `start_date`/`end_date`/`days_ago` ALWAYS validate against `send_date`, regardless of report intent (sold, live, pipeline, anything).** Intent affects column choices and widget axis branching (per `_tl_axis_branching` in `sponsorship_widget_schema.json`) — it does NOT affect the validation date column. If a user genuinely needs a different date axis for filtering (purchase_date, publish_date, outreach_date, etc.), that has to be encoded in `filters_json` (server-interpreted) — the FilterSet itself has no first-class field for it, and validation should not invent one. v1's `_tl_axis_branching` is for displayed widgets, not for the data plane filter predicate.

This means there is exactly ONE branch in the validation query, based on which date pair the FilterSet uses:

##### Path A — `createdat_from` / `createdat_to` set (view-only)

```sql
-- db_count
SELECT COUNT(DISTINCT adlink_id) FROM v_adspot_brand_profiles
WHERE adlink_publish_status = ANY(<filters_json.publish_status>)
  AND adlink_created_at BETWEEN <createdat_from> AND <createdat_to>
  AND brand_id   = ANY(<resolved brand_ids>)     -- if brands set
  AND channel_id = ANY(<resolved channel_ids>)   -- if channels set
LIMIT 1 OFFSET 0
```

```sql
-- db_sample (DISTINCT ON dedupes by adlink_id; outer ORDER BY enforces canonical sort)
SELECT * FROM (
  SELECT DISTINCT ON (adlink_id)
         adlink_id, brand_name, channel_name, adlink_publish_status, adlink_created_at
  FROM v_adspot_brand_profiles
  WHERE adlink_publish_status = ANY(<filters_json.publish_status>)
    AND adlink_created_at BETWEEN <createdat_from> AND <createdat_to>
    AND brand_id   = ANY(<resolved brand_ids>)
    AND channel_id = ANY(<resolved channel_ids>)
  ORDER BY adlink_id, adlink_created_at DESC   -- inner: required for DISTINCT ON
) deduped
ORDER BY adlink_created_at DESC                 -- outer: canonical sort (newest first)
LIMIT 10 OFFSET 0
```

##### Path B — `start_date` / `end_date` / `days_ago` set (join base table for `send_date`)

```sql
-- db_count
SELECT COUNT(DISTINCT v.adlink_id)
FROM v_adspot_brand_profiles v
JOIN thoughtleaders_adlink al ON al.id = v.adlink_id
WHERE v.adlink_publish_status = ANY(<filters_json.publish_status>)
  AND al.send_date BETWEEN <start_date> AND <end_date>
  AND v.brand_id   = ANY(<resolved brand_ids>)
  AND v.channel_id = ANY(<resolved channel_ids>)
LIMIT 1 OFFSET 0
```

```sql
-- db_sample (DISTINCT ON dedupes by adlink_id; outer ORDER BY enforces canonical sort)
SELECT * FROM (
  SELECT DISTINCT ON (v.adlink_id)
         v.adlink_id, v.brand_name, v.channel_name, v.adlink_publish_status, al.send_date
  FROM v_adspot_brand_profiles v
  JOIN thoughtleaders_adlink al ON al.id = v.adlink_id
  WHERE v.adlink_publish_status = ANY(<filters_json.publish_status>)
    AND al.send_date BETWEEN <start_date> AND <end_date>
    AND v.brand_id   = ANY(<resolved brand_ids>)
    AND v.channel_id = ANY(<resolved channel_ids>)
  ORDER BY v.adlink_id, al.send_date DESC      -- inner: required for DISTINCT ON
) deduped
ORDER BY send_date DESC                          -- outer: canonical sort (newest first)
LIMIT 10 OFFSET 0
```

##### Channel filter applies to BOTH paths

If `<resolved channel_ids>` is set on the FilterSet, the predicate MUST appear in BOTH `db_count` and `db_sample`. Earlier drafts dropped it from the sample query — that's a regression: channel-filtered reports could surface validation samples outside the requested set.

##### Why the inner/outer split

`DISTINCT ON (adlink_id)` in PostgreSQL forces `ORDER BY adlink_id, ...` in the same SELECT — that's a syntactic requirement, not a stylistic choice. Putting `LIMIT 10` on that same query returns the 10 smallest adlink IDs (oldest pipeline entries by surrogate key), not the 10 most recent rows by date. Wrapping the dedupe in a subquery and applying the canonical sort + LIMIT in the outer SELECT is the only way to honor both the dedupe contract AND Phase 2's contract (line ~281: "10 rows, ordered by the canonical sort").

Date filter required (per Phase 2 edge-case rule — type-8 without dates is rejected upfront). No keyword ILIKE pattern; sponsorships filter by relations, not content text.

#### Postgres CTE fallback (smoke-check only)

If ES is unavailable for an intelligence-report validation AND the FilterSet has tight indexed predicates (reach floor + narrow language + small keyword set), the PG smoke-check uses the CTE pattern:

```sql
WITH filtered AS (
  SELECT id, channel_name, description, reach
  FROM thoughtleaders_channel
  WHERE is_active = TRUE
    AND <indexed-column predicates>
)
SELECT COUNT(*) FROM filtered
WHERE <keyword ILIKE predicate>
LIMIT 1 OFFSET 0
```

This pattern works only with substantial pre-filter pruning. **Don't use the CTE smoke-check as the production validation path** — its limits (timeouts on broad predicates, substring noise from ILIKE) are real and surfaced in the e2e findings. ES is the right tool.

### Step 2.V2 — Run the count query (with timeout / fallback handling)

```
# Intelligence report (1 / 2 / 3):
tl db es --json '<es_query_body>'

# Sponsorship report (8):
tl db pg --json "<count_sql>"
```

For ES queries:
- ES timeouts on intelligence searches are rare with proper `bool.filter` use; if one occurs, narrow the keyword set or tighten the indexed filters.
- ES phrase matching (`type: "phrase"`) handles substring-noise risk by default — no equivalent of the PG ILIKE `AI`-matches-`Tamil` problem.

For PG queries (type 8 or smoke-check fallback):
1. If a PG query times out, drop the `channel_name ILIKE` half of each keyword predicate (description-only).
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

### Step 2.V4 — Run sample query, then `sample_judge`

The sample runner branches by report type, mirroring Step 2.V2's count runner:

```
# Intelligence reports (1 / 2 / 3) — primary path:
tl db es --json '<es_query_body_with_size_10_and_sort>'

# Sponsorship reports (8) — primary path:
tl db pg --json "<sample_sql>"

# PG smoke-check fallback (intelligence only, when ES unavailable AND tight pre-filters):
tl db pg --json "<cte_sample_sql>"
```

For ES intelligence samples: same `bool.filter` + `multi_match phrase` body as the count, but `size: 10`, `sort: [{ "reach": "desc" }]` (or the canonical sort per type), and `_source` listing the type-appropriate fields (see `sample_judge` row-shape contract below).

Pipe the sample (≤ 10 rows) into `tools/sample_judge.md` with `USER_QUERY`, `DB_SAMPLE`, `REPORT_TYPE`, and `VALIDATION_CONCERNS` (inherited from `keyword_research`'s warnings, if any). The row shape in `DB_SAMPLE` differs per report type — see `tools/sample_judge.md` "Inputs" section for the type-specific contracts.

Decision based on judgment:
- `matches_intent` → `decision: "proceed"` — emit validated FilterSet to Phase 3.
- `looks_wrong` → `decision: "alternatives"` — Mode-B follow-up to user (save anyway / refine / cancel). Skip Phase 3 + Phase 4.
- `uncertain` → `decision: "alternatives"` favoring "Refine" — surface ambiguity rather than ship silently.

### Step 2.V5 — Retry orchestration (cap: 3)

When `db_count` is `empty` or `too_broad`, emit structured feedback to whichever upstream signal produced the failing FilterSet:

| Source | Retry target | Feedback shape |
|---|---|---|
| Matched topics → `keywords` field | re-compose FilterSet with broader keywords from `topic.keywords[]` (beyond head) or relax operator AND→OR | `{issue, suggestion, previous_filterset}` |
| `keyword_research` output | re-invoke T2 with the failing keywords + retry hint | `{issue, suggestion}` |

Cap at **3 retries total**. After 3, `decision: "fail"` with diagnostic — better to honestly fail than infinite-loop.

**What does NOT trigger retry**:
- `sample_judge` returning `looks_wrong` — substantive failure (data sparsity or noise), not a shape failure. Retrying produces more noise. Go straight to `alternatives`.
- `db_count` in `narrow` (1–4) — proceed with warning; retry would lose the small but real signal.

### Step 2.V6 — Compose decision output

Pseudo-shape (not runnable JSON — `<int>`, `|`-unions, and `/* notes */` are placeholders for the actual values the orchestration emits):

```text
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

### User-facing rendering (Mode B)

`alternatives_for_user` is internal state. When the skill surfaces it to the user, it MUST be rendered in plain English. Users have no idea what's under the hood.

**Forbidden in user-facing text** (these are internal terms, never show them):
- Phase numbers (`Phase 2`, `Phase 2b`, `Phase 3`, `Phase 4`)
- Tool / step names (`sample_judge`, `keyword_research`, `database_query`, `db_count`, `db_sample`, `validation_concerns`, `FilterSet`, `Step 2.V4`)
- Decision enums (`looks_wrong`, `matches_intent`, `decision: "alternatives"`)
- Bucket labels (`narrow`, `too_broad`, `count_classification`)

**Allowed**: specific channel / brand / video names from the sample, the user's own keywords, plain words like "results", "matches", "sample", "noise".

**Canonical user-facing rendering for the G11 example** (translate the JSON above into this — do NOT show the JSON):

> Hmm — I ran the search but the top results don't look right for **"channels about IRS tax debt forgiveness programs"**. The first 10 by reach are channels like **Cocomelon**, **Bad Bunny**, **Bruno Mars**, and **Selena Gomez** — music and kids' content, not tax/finance. The short word "IRS" is matching inside unrelated words in channel descriptions, which is pulling in a lot of noise.
>
> How do you want to proceed?
> 1. **Save it anyway** — if you want to dig through the long tail manually.
> 2. **Refine the search** — for example, drop "IRS" on its own and keep the longer phrases ("tax debt", "tax debt forgiveness", "tax debt relief").
> 3. **Cancel** — there may not be much coverage for this niche in the data.

Notice what's preserved (the actual sample names, the user's keywords, what went wrong in human terms) and what's stripped (every internal label). The same translation rule applies to Mode-C (failure) and any other follow-up message — name what the user sees, never name the machinery.

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

1. **Pick columns via `tools/column_builder.md`.** Inject `REPORT_TYPE`, `FILTERSET`, `ROUTING_METADATA`, the `references/columns_<type>.md` content, and `references/sortable_columns.json`. The builder owns four explicit decisions:
   - **Which columns to emit** — defaults + intent-driven additions + niche-driven additions, capped at 5–10 standard (up to 13 with intent justification).
   - **Column order** — anchors first (e.g. `Channel`, `TL Channel Summary` for type 3; `Channel`, `Advertiser`, `Status` for type 8), then identity columns, then the data columns the user's intent emphasizes (outreach surface / engagement surface / pricing surface), then context columns last. The order in the emitted `columns` dict IS the display order.
   - **Column width** — most columns use the platform's default width. Wide-text columns (`TL Channel Summary`, `Topic Descriptions`, `Channel Description`, `Talking Points`, `Adops Notes`) get wider; numeric / status columns get narrower. The builder emits a `width` hint per column when it deviates from the default.
   - **Custom column formulas** — propose at least one per type's "Suggested formulas" table (e.g. `{Avg. Views} / {Subscribers}` for type-3 engagement, `{Price} - {Cost}` for type-8 TL profit). Custom columns are surfaced as `pending_refinement_suggestions` for the user to opt into — never silently activated.
   The builder also validates the sort viability (per "Sort field — which phase owns it" above) and emits a `dataset_structure` with pagination defaults.
2. **Hand off to Phase 4.** The `pending_refinement_suggestions` carry through to Phase 4's takeaway message; the `columns` dict (with order and widths) plus `dataset_structure` feed `widget_builder` and final composition.

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
  - `references/intelligence_widget_schema.json` (types 1/2/3) and `references/sponsorship_widget_schema.json` (type 8) — JSON Schemas defining widget shape, the disjoint aggregator catalogs, default sets, intent overrides, and (for sponsorship) axis-branching rules. Consumed by `widget_builder`.
  - `references/widgets.md` — readable index pointing at the two schemas above.
  - `references/intelligence_filterset_schema.json` and `references/sponsorship_filterset_schema.json` — final JSON-shape validation source of truth.

### Process

1. **Pick widgets via `tools/widget_builder.md`.** Inject `REPORT_TYPE`, `FILTERSET`, `COLUMNS`, `ROUTING_METADATA`, and the matching widget schema (`references/intelligence_widget_schema.json` for types 1/2/3; `references/sponsorship_widget_schema.json` for type 8). The builder emits `{ widgets, histogram_bucket_size, _widget_metadata }`. **The selection rule is: emit only widgets that add value to the user's original prompt.** A widget earns its slot if it answers a question the user implicitly cares about (intent), surfaces a metric tied to a filter the user named (niche), or shows a trend over the date scope they specified. Don't pad to hit 6 — emit fewer (down to 4) if the extras don't answer something. The builder handles type-8 axis branching and intent-driven swaps per the schema's `_tl_intent_overrides`.
2. **FINAL JSON-shape validation pass.** Verify the composed config:
   - Every field in `filterset` exists in the schema and matches its declared type.
   - Every column in `columns` is in the type's column file.
   - Every aggregator in `widgets` is in the matching catalog (intelligence for 1/2/3, sponsorship for 8).
   - `sort` references an emitted column with allowed direction.
   - Type 8 has at least one date scope: `days_ago`, `start_date`/`end_date`, or `createdat_from`/`createdat_to`. (Either pair satisfies the requirement — they map to different underlying columns; see Step 2.V1's date-scope mapping. Phase 2 already enforces this upstream.)
   - When `cross_references` is present, `report_type ∈ {1, 3}`.
   - When `filters_json.similar_to_channels` is present, no overlapping `keywords` / `topics` fields.
   - `type = 2` (DYNAMIC) and `report_type ∈ {1, 2, 3, 8}` — Campaign-model contract for the API endpoint.
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

Pseudo-shape (not runnable JSON — `<int>`, `|`-unions, and `/* notes */` are placeholders for the actual values the orchestration emits):

```text
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
    "histogram_bucket_size": "week" | "month" | "year"
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
2. **`type: 2` (DYNAMIC) is the Campaign-model contract** for the reports the skill produces. The skill always emits `type: 2`; server-side fields like `created_by_campaign_maker` are filled by the API endpoint, not by the skill.
3. **Trust Phase 2's validation.** Phase 4 does NOT re-run db_count / db_sample / sample_judge — those already passed upstream. If Phase 2 emitted `decision: "proceed"`, the FilterSet is good. (Sample-judging is the architectural promise to catch silent ships of bad samples — it just lives in Phase 2 now.)
4. **JSON-shape validation rejection is a stop, not a warn.** If the final-shape validation finds an unfixable problem (column doesn't exist, aggregator from wrong catalog, missing required field), Phase 4 emits an error follow-up rather than emitting a partial config.
5. **Takeaways cite specifics.** Numbers, names, intent labels. Vague takeaways ("the report looks good") add no value.
6. **No new filters or columns in Phase 4.** Phase 4 doesn't reshape the FilterSet or add columns — it picks widgets, validates, and composes. Reshape requires looping back to Phase 2 or 3.
7. **Type-8 axis consistency.** Both `_over_<axis>` histograms in the same type-8 report use the SAME axis (per `sponsorship_widget_schema.json`'s `_tl_axis_branching`).

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
| **2** | Validation: sample_judge returned `looks_wrong` (G11-class noise) | Mode B prompt: save anyway / refine / cancel — plain English only, citing 2–3 specific sample names; never expose internal terms (phase numbers, tool names, `validation_concerns`, `db_count`, `looks_wrong`). See "User-facing rendering (Mode B)" in the Phase 2 section. |
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
| **`tl db es`** | Live content / channel / brand text search at scale (intelligence reports — types 1/2/3 primary validation engine) | tl-cli ≥ v0.6.2; sandboxed read-only ES search bodies; phrase-matching avoids the PG-ILIKE substring-noise problem |
| **`tl db pg`** | Live data: topics, sponsorships (AdLink relations — type 8 primary), small lookup queries; smoke-check fallback for intelligence reports when ES is unavailable AND the FilterSet pre-filters narrowly | tl-cli ≥ v0.6.2; sandboxed read-only SELECT, mandatory `LIMIT/OFFSET`, max 500 rows; CTE pattern required for any keyword-bearing intelligence query |
| **`references/intelligence_filterset_schema.json`** | Canonical filterset shape for types 1/2/3 (filter fields, defaults, validation rules) | Static file; consulted in Phase 2 (compose + validate) and Phase 4 (final JSON-shape validation) |
| **`references/sponsorship_filterset_schema.json`** | Canonical filterset shape for type 8 (status IDs, owner fields, date filters, filters_json semantics) | Static file; consulted in Phase 2 (compose + validate) and Phase 4 (final JSON-shape validation) |
| **`references/columns_<type>.md`** | Available columns + intent-driven default sets per ReportType | Static; consulted in Phase 3 |
| **`references/intelligence_widget_schema.json`** | Widget shape + aggregator catalog + default sets + intent overrides for types 1/2/3 | Static file; consulted in Phase 4 (compose) and Phase 4 (final JSON-shape validation) |
| **`references/sponsorship_widget_schema.json`** | Widget shape + aggregator catalog + default set + intent overrides + axis-branching rules for type 8 | Static file; consulted in Phase 4 (compose) and Phase 4 (final JSON-shape validation) |
| **`references/widgets.md`** | Readable index pointing at the two widget schemas | Static; convenience reference |
| **Conditional tools** (T1–T5) | Dynamic enrichment of the unified schema | Markdown files in `tools/` |

**Trust hierarchy:**
- For "does this row exist / how many" questions: **`tl db es`** for intelligence-report content / channel / brand search (types 1/2/3); **`tl db pg`** for sponsorship deal counts and small lookup queries (type 8 + topic / brand / channel name resolution).
- For filter shape and validation rules: the filterset + widget schema files (`*_filterset_schema.json` / `*_widget_schema.json`) — they're the ground truth for what's valid.
- For "what's available to display": the column files (`columns_<type>.md`) — they're the canonical list per report type.

If a tool's resolved ID disagrees with the user's name (e.g., emoji-stripped match), surface the discrepancy rather than silently substitute.

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
- **[references/intelligence_filterset_schema.json](references/intelligence_filterset_schema.json)** — Filterset + filters_json shape for types 1 (CONTENT), 2 (BRANDS), 3 (CHANNELS). Mirrors `dashboard.models.FilterSet` 1:1: keyword fields (`keywords`, `keyword_operator`, `content_fields`, `keyword_content_fields_map`, `keyword_exclude_map`), `topics` (ChoiceArrayField IntegerField), date scopes, demographic shares, channel-formats, languages, reach / projected_views / youtube_views ranges, M2M relations (channels / brands / networks), defaults (`languages: ["en"]`, `channel_formats: [4]`), and `_tl_intent_overrides` for intent-driven population.
- **[references/sponsorship_filterset_schema.json](references/sponsorship_filterset_schema.json)** — Filterset shape for type 8 (SPONSORSHIPS). Same model as intelligence schemas, different relevant slice: M2M relations (sponsorships / channels / brands), date scopes (send / purchase / created), `filters_json.publish_status` for deal-stage encoding, `tl_sponsorships_only` flag. Type-8 reports filter by relations, not content text — keyword fields are inert here.

**Available columns per ReportType** (consulted in Phase 3)
- **[references/columns_content.md](references/columns_content.md)** — Type 1: video-level columns. Each column block: display_name, backend_code, when-to-use, default-on flag.
- **[references/columns_brands.md](references/columns_brands.md)** — Type 2: brand-aggregated columns.
- **[references/columns_channels.md](references/columns_channels.md)** — Type 3: channel-level columns. Includes intent-driven default sets: discovery / outreach / sponsorship-pitch.
- **[references/columns_sponsorships.md](references/columns_sponsorships.md)** — Type 8: deal-level columns. Includes Channel-info columns reused from type 3 (TL Channel Summary, Topic Descriptions, Subscribers, USA Share, Demographics - Age Median).

**Widget catalog** (consulted in Phase 4)
- **[references/intelligence_widget_schema.json](references/intelligence_widget_schema.json)** — JSON Schema for widget objects on types 1/2/3 reports. Disjoint aggregator catalog; per-type default 5-widget sets (`_tl_default_widget_set_by_type`); intent overrides (`_tl_intent_overrides`); selection rules.
- **[references/sponsorship_widget_schema.json](references/sponsorship_widget_schema.json)** — JSON Schema for widget objects on type 8 reports. Disjoint aggregator catalog (sponsorship pipeline / live ads / performance / assets-drafts groupings); axis-branching rules (`_tl_axis_branching`: pipeline → `send_date`, sold → `purchase_date`); default 5-widget set; intent overrides for the major sponsorship views (forecasting / won-deals / ROI / assets QA).
- **[references/widgets.md](references/widgets.md)** — Readable index pointing at the two schemas above.

**Filter semantics (cross-cutting)**
- **[references/report_glossary.md](references/report_glossary.md)** — Vocabulary disambiguation across the whole skill: report-type synonyms (uploads = content; channels = creators; campaign report ⇒ ambiguous), TL-specific terminology (Reach / PV / VG / MSN / TPP / MBN), deal-stage jargon (booked = sold = status 3; pipeline = active non-sold), field-pair disambiguation (reach vs projected_views vs youtube_views), defaults, filter-source decisions (typed field vs `filters_json`), common pitfalls.
- **[references/sortable_columns.json](references/sortable_columns.json)** — Sort metadata per column (asc-only / desc-only / both). Consulted in Phase 3's sort selection.

**Conditional tools** (loaded only when Phase 2 invokes them)
- **[tools/topic_matcher.md](tools/topic_matcher.md)** — Topic verdicts against live `thoughtleaders_topics`.
- **[tools/keyword_research.md](tools/keyword_research.md)** — ES-validated keyword set when no topic anchor exists.
- **[tools/database_query.md](tools/database_query.md)** — Cross-reference query: resolves a prerequisite condition into a set of IDs that the main FilterSet includes/excludes.
- **[tools/name_resolver.md](tools/name_resolver.md)** — Progressive name → entity_id matching with ambiguity surface.
- **[tools/similar_channels.md](tools/similar_channels.md)** — Look-alike helper: emits `filters_json.similar_to_channels` for the platform's vector-similarity engine.
- **[tools/sample_judge.md](tools/sample_judge.md)** — Sample inspection inside Phase 2's validation step. Type-aware row contract: type 3 cites `channel_name`, type 1 cites `title`, type 2 cites `brand_name`. Intelligence reports only (skipped for type 8). Catches substring noise and intent mismatch (G11-class) before the FilterSet ships to Phase 3.
- **[tools/column_builder.md](tools/column_builder.md)** — Phase 3's column-selection prompt. Same builder-prompt pattern as `widget_builder`: explicit inputs, JSON output schema, selection process (defaults → intent additions → niche additions → sort validation → formula proactivity), worked examples per report type, hard rules. Consumes `references/columns_<type>.md` as the catalog.
- **[tools/widget_builder.md](tools/widget_builder.md)** — Phase 4's widget-selection prompt. Mirrors v1's widget-builder approach: selection guidelines, intent-driven swaps, type-8 axis branching, and worked examples per report type. Consumes the matching `*_widget_schema.json` (intelligence or sponsorship) as the catalog.

**Examples & golden corpus**
- **[examples/golden_queries.md](examples/golden_queries.md)** — 13 hand-curated NL inputs (G01–G13) covering all four report types and the full mode space (proceed / alternatives / vague). Documentation/regression corpus — not loaded at runtime. Test fixtures for shadow-mode comparison and skill maintenance. Note: G07 (`partnership` routing) and G11 (`IRS` substring noise) are inlined in SKILL.md's Phase 1 and Phase 2 detail sections as authoritative regression baselines.

## Pagination Defaults (Phase 3 applies these unless USER_QUERY overrides)

| ReportType | Page size | Sort default | Notes |
|---|---|---|---|
| 1 (CONTENT) | 50 | `-views` | Per-video; longer pages tolerable |
| 2 (BRANDS) | 25 | `-doc_count` | Aggregated rows; smaller pages |
| 3 (CHANNELS) | 25 | `-reach` (default) / `-publication_date_max` (outreach intent) | Sort branches on intent_signal |
| 8 (SPONSORSHIPS) | 50 | `-purchase_date` (sold) / `-send_date` (proposal stages) | Axis branches on `publish_status` per `sponsorship_widget_schema.json`'s `_tl_axis_branching` |

## Safety

- **`tl db pg`**: read-only SELECT only. The skill never attempts INSERT/UPDATE/DELETE through this surface. Mandatory `LIMIT n OFFSET m`, max 500 rows. Forbidden function list: `random`, `pg_sleep`, `current_user`, `version`, `pg_read_file`, `lo_export`, `dblink`, `current_setting`, `set_config`.
- **`tl db es`**: read-only search bodies only. Index is fixed server-side (no client-side index selection). Always include explicit `size` (default to small values; cap at the ES sandbox's allowed maximum). Use `bool.filter` for non-scoring constraints and `must` / `should` for keyword scoring. Never request `_source: false` then rely on stored fields the sandbox doesn't expose.
- **Tool warnings**: every tool that resolves names with non-exact matching MUST surface the match-quality in `_routing_metadata.tool_warnings`. Phase 4 surfaces these in takeaway insights — silent name-substitution is forbidden.
- **Follow-ups over assumptions**: when a phase encounters ambiguity that affects the output, the skill MUST ask rather than guess. Phase-by-phase trigger list is in the "Follow-Up Interactions" section above.

## Self-Improvement

After every significant report-build task, ask:

1. **New filter field encountered or schema mismatch with the dashboard?** → Update `references/intelligence_filterset_schema.json` or `references/sponsorship_filterset_schema.json`.
2. **New column requested that isn't in the column list?** → Add to `references/columns_<type>.md` with `display_name`, `backend_code`, when-to-use.
3. **Conditional tool fired wrongly (false positive or false negative)?** → Refine the criterion in this SKILL.md's "Conditional Tool Invocation" section AND in the tool's own front-matter.
4. **Name resolution failed silently?** → Update `tools/name_resolver.md` matching strategy. Surface the discrepancy in tool warnings; never silently substitute.
5. **Pagination, sort, or aggregation default felt wrong?** → Update the "Pagination Defaults" table above + `references/columns_<type>.md` intent-default tables.
6. **Sample judge mis-routed (silent ship of bad sample, or false `looks_wrong`)?** → Update `tools/sample_judge.md` thresholds.
7. **Follow-up trigger missed (skill assumed instead of asking)?** → Add the trigger to the "Follow-Up Interactions" table; codify the question wording.
8. **New takeaway insight worth standardizing?** → Add to Phase 4's takeaway-composition rules in this SKILL.md.

The reference files are the source of truth for schemas and columns. SKILL.md is the orchestration spec. Tools are conditional sub-routines. Each layer's responsibility stays separate; bleeding logic across layers (e.g., column rules into the schema file) creates the duplication this architecture is designed to avoid.
