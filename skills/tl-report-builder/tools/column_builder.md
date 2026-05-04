# Tool: column_builder

The Phase 3 column-selection prompt. Picks which columns the saved report displays and the dataset shape that hangs off them. Mirrors the same builder-prompt pattern as `widget_builder.md`: explicit inputs, JSON output schema, selection process, worked examples, and self-check.

You produce **JSON only** — no prose, no fences.

---

## When this prompt fires

Always, during Phase 3, after Phase 2 has emitted a validated FilterSet (`decision: "proceed"`). Skipped on `decision: "alternatives"` and `decision: "fail"` — those route directly to the user via Phase 2's Mode-B / fail follow-up.

If you're being invoked, the FilterSet has been validated against live data. Don't re-validate; pick the columns.

---

## Inputs

The Phase 3 orchestration injects:

1. **`REPORT_TYPE`** — integer enum: `1` (CONTENT) | `2` (BRANDS) | `3` (CHANNELS) | `8` (SPONSORSHIPS).
2. **`FILTERSET`** — the validated FilterSet from Phase 2 (filterset + filters_json + cross_references). You read it for niche-driven additions (a brand-mention filter → emit `Brands` column; a recent-activity filter → emit `Last Published`) and for sort validation.
3. **`ROUTING_METADATA`** — Phase 2's `_routing_metadata`. Critically:
   - **`intent_signal`**: phrases like `"product placements (outreach)"`, `"sponsorship outreach"`, `"audience-quality focus"`. When non-null, drives intent-based column additions.
   - **`tool_warnings`**: warnings from T1–T5 (e.g., `name_resolver` matched "Sanky" via emoji-stripped matching). Surface in `_column_metadata.concerns_surfaced` so Phase 4 can include them in takeaways.
   - **`validation_concerns`**: noise warnings from `keyword_research` / `sample_judge`. Same surfacing path.
4. **`COLUMNS_REFERENCE`** — content of `references/columns_<channels|content|brands|sponsorships>.md` for the report type. Lists default columns, full available column catalog, intent-driven additions table, and custom-formula variables. **Do NOT inline the catalog into your reasoning; consult it.**
5. **`SORTABLE_COLUMNS`** — content of `references/sortable_columns.json`. Per-column sort metadata (asc-only / desc-only / both) used to validate the FilterSet's `sort` field.

---

## Output schema (strict)

```json
{
  "columns": {
    "<Display Name>": { "display": true, "width": "default" | "wide" | "narrow" },
    "<Custom Column>": {
      "display": true,
      "custom": true,
      "formula": "{Variable} / {Other}",
      "cellType": "regular" | "usd" | "percent" | "textbox",
      "width": "default" | "wide" | "narrow"
    }
  },
  "dataset_structure": {
    "report_type": <int>,
    "page_size": <int>,
    "sort": "<field>" | "-<field>"
  },
  "pending_refinement_suggestions": [
    "<string — surfaced to user in Phase 4>"
  ],
  "_column_metadata": {
    "intent_consumed": "<echo of ROUTING_METADATA.intent_signal>" | null,
    "column_count": <int>,
    "default_set_used": <bool>,
    "concerns_surfaced": [/* tool_warnings + validation_concerns to surface in takeaways */],
    "ordering_strategy": "anchors_first_then_intent_then_context"
  }
}
```

No fences. No prose. The Phase 3 orchestration parses your output as JSON.

---

## Selection process

### Step 1 — Load the type's column file

Per `REPORT_TYPE`:
- `1` → `columns_content.md`
- `2` → `columns_brands.md`
- `3` → `columns_channels.md`
- `8` → `columns_sponsorships.md`

The file is delivered to you as `COLUMNS_REFERENCE`.

### Step 2 — Start from the type's default set

The "Defaults — always include" section of `COLUMNS_REFERENCE` lists the anchors. Type 3's anchors include `TL Channel Summary` (mandatory per `columns_channels.md`). Type 8's anchors are `Channel`, `Advertiser`, `Status`, `Price`, `Scheduled Date`. Always emit these unless the user explicitly contradicted them.

### Step 3 — Layer intent-driven additions

If `ROUTING_METADATA.intent_signal` is non-null, consult `COLUMNS_REFERENCE`'s "Intent-driven additions" table and add the matching columns. Common signals:

| Intent | Add columns |
|---|---|
| Outreach / product placements (type 3) | `Sponsorship Score`, `Sponsorships Sold`, `Brands Sold`, `Last Sold Sponsorship`, `Open Proposals Count`, `Outreach Email`, `USA Share`, `Demographics - Age Median` |
| Audience-quality / engagement focus (type 3) | `Engagement`, `Median Evergreenness`, `Trend`, `Volatility`, `Avg. Comments` |
| Growth / momentum (type 3) | `Last 28 Days Views %`, `Last 28 Days Subscribers %`, `Trend`, `Posts Per 90 Days` |
| Pricing / efficiency (type 3) | `Latest AdSpot Price`, `CPV Today`, `Last Known Cost`, `Projected Views` |
| Sponsor surfacing (type 1) | `Brands`, `Sponsored Brands`, `Advertiser`, `Price`, `CPV` |
| Engagement focus (type 1) | `Likes`, `Comments`, `Duration`, `Evergreen Score`, `Views at 30 days` |
| Recency / momentum (type 2) | `Last Mention`, `Last Published Upload`, `Mentions`, `Avg. Views` |
| Competitor research (type 2) | `Channels`, `Mentions`, `Last Mention`, `Avg. Views`, `Sponsor Time`, `Open Proposals Count` |
| Pipeline / forecasting (type 8) | `Status`, `Weighted price`, `Scheduled Date`, `Expected CPV`, `Projected Views`, `Owner Sales` |
| Won deals review (type 8) | `Status`, `Price`, `Cost`, `Revenue`, `Purchase Date`, `Publish Date`, `Conversions`, `Owner Sales` |
| Pacing / efficiency (type 8) | `Expected CPV`, `Current CPV`, `Views Guaranteed`, `Views Guarantee Days`, `Projected Views`, `Current Views` |

When you consume `intent_signal`, **echo what you read** in `_column_metadata.intent_consumed` so Phase 4 can surface the reasoning.

### Step 4 — Apply niche-driven additions

When `FILTERSET` anchors specific filters, pick 1–2 columns that surface those:

| FilterSet signal | Add column |
|---|---|
| `brand_mention_type` set, or `brands` non-empty | `Brands` (type 1) / `Brand` (type 2) |
| `days_ago` short or recent date scope | `Last Published` (type 3) / `Last 28 Days Views %` (type 3, growth-flavored) |
| `topics` set | `Topic Descriptions` (type 3) |
| Demographic filters set (`*_share`, `demographic_age`) | `USA Share`, `Male Share`, `Demographics - Age Median` |
| `face_on_screen` set | `Face On Screen` |
| Performance-grade filter set | `Performance Grade` (type 8) / `Sponsorship Score` (type 3) |
| `tl_sponsorships_only: true` | `Sponsorships Sold`, `Last Sold Sponsorship` (type 3 outreach surface) |

Don't dump all matching columns; pick 1–2 most informative.

### Step 5 — Validate sort

The FilterSet's `sort` MUST reference a column that's both:
1. Present in the emitted `columns` dict, AND
2. Has an allowed direction per `SORTABLE_COLUMNS` (some columns are asc-only or desc-only).

If the FilterSet's `sort` references a column you didn't emit, **add the column** (don't drop the sort) and flag in `_column_metadata.concerns_surfaced`. If the direction is invalid, surface a follow-up rather than silently fix.

### Step 6 — Order the columns

The order in the emitted `columns` dict IS the display order on the saved report. Apply this ordering strategy:

1. **Anchors first** — type-mandated default columns. For type 3: `Channel`, `TL Channel Summary`, `Subscribers`. For type 8: `Channel`, `Advertiser`, `Status`, `Price`, `Scheduled Date`. For type 1: `Date`, `Channel`, `Title`, `Views`. For type 2: `Brand`, `Mentions`, `Avg. Views`.
2. **Intent-driven block** — the columns added per `ROUTING_METADATA.intent_signal` (outreach surface / engagement surface / pricing surface / etc.). Group by theme so the user reading left-to-right sees the report's purpose.
3. **Niche-driven additions** — columns added because of specific FilterSet anchors (a brand-mention filter → `Brands`; a recent-activity filter → `Last Published`).
4. **Context columns last** — `Country`, `Language`, `Channel URL`, `Topic Descriptions`, generic identifiers. These are useful for verification but aren't the report's headline.

If a sort field references a column, it should be visible — pull it forward into the intent-driven block when needed.

### Step 7 — Set column widths

Most columns use the platform's default width. Deviate when the column's content is unusually wide or unusually narrow:

| Width | When to use | Examples |
|---|---|---|
| `wide` | Long-text or multi-line content | `TL Channel Summary`, `Topic Descriptions`, `Channel Description`, `Talking Points`, `Adops Notes`, `Publisher Notes`, `Sponsorship Example` |
| `narrow` | Compact numerics or single-tag fields | `Status`, `Match Grade`, `Performance Grade`, `Face On Screen`, `Country`, `Language` |
| `default` | Everything else | most columns |

Emit `"width": "wide"` or `"width": "narrow"` only when deviating; omit the key (or set `"width": "default"`) for everything else.

### Step 8 — Custom-formula proactivity

Per `COLUMNS_REFERENCE`'s "Suggested formulas" table, queue at least one custom-formula suggestion in `pending_refinement_suggestions`. Examples per intent:

| Intent | Suggested formula | `cellType` |
|---|---|---|
| Engagement spotting (type 3) | `{Avg. Views} / {Subscribers}` | `percent` |
| Outreach efficiency (type 3) | `{Cost} / {Projected Views}` | `usd` |
| ROAS check (type 8) | `{Price} ? {Revenue} / {Price} : 'N/A'` | `regular` |
| Profit signal (type 8) | `{Price} - {Cost}` (TL profit, not "margin") | `usd` |
| Default (no specific intent) | `{Avg. Views} / {Subscribers}` | `percent` |

**Do NOT silently activate a custom column.** Surface as a refinement suggestion; the user opts in (Phase 4 surfaces them in the takeaways message).

### Step 9 — Compose the dataset structure

Set `dataset_structure.report_type` and `dataset_structure.sort` (echoing the FilterSet's sort, or the type's default if unset). Set `page_size` per the pagination defaults:

| ReportType | Page size | Sort default (if FilterSet didn't set one) |
|---|---|---|
| 1 (CONTENT) | 50 | `-views` |
| 2 (BRANDS) | 25 | `-doc_count` |
| 3 (CHANNELS) | 25 | `-reach` (default) / `-publication_date_max` (outreach intent) |
| 8 (SPONSORSHIPS) | 50 | `-purchase_date` (sold) / `-send_date` (proposal stages) |

---

## Worked examples

### Example A — Channels report, no intent (G01-class)

**Inputs**:
- `REPORT_TYPE`: 3
- `FILTERSET.filterset`: `{ keywords: ["gaming"], reach_from: 100000, languages: ["en"], days_ago: 730, sort: "-reach", channel_formats: [4] }`
- `ROUTING_METADATA.intent_signal`: null
- `ROUTING_METADATA.tool_warnings`: []

**Output**:
```json
{
  "columns": {
    "Channel":              { "display": true },
    "TL Channel Summary":   { "display": true },
    "Subscribers":          { "display": true },
    "Total Views":          { "display": true },
    "Avg. Views":           { "display": true },
    "Engagement":           { "display": true },
    "Last Published":       { "display": true },
    "Country":              { "display": true },
    "Language":             { "display": true },
    "Channel URL":          { "display": true }
  },
  "dataset_structure": {
    "report_type": 3,
    "page_size": 25,
    "sort": "-reach"
  },
  "pending_refinement_suggestions": [
    "Add a 'Views Per Subscriber' custom formula column ({Avg. Views} / {Subscribers}, cellType: percent) to spot high-engagement channels"
  ],
  "_column_metadata": {
    "intent_consumed": null,
    "column_count": 10,
    "default_set_used": true,
    "concerns_surfaced": []
  }
}
```

10 columns: 3 anchors (`Channel`, `TL Channel Summary`, `Subscribers`) + 7 niche-relevant for a gaming-discovery report. No intent → defaults used. Sort echoes the FilterSet's `-reach`.

### Example B — Channels report, outreach intent (G03-class)

**Inputs**:
- `REPORT_TYPE`: 3
- `ROUTING_METADATA.intent_signal`: `"product placements (outreach)"`
- `ROUTING_METADATA.tool_warnings`: []

**Output**:
```json
{
  "columns": {
    "Channel":                   { "display": true },
    "TL Channel Summary":        { "display": true },
    "Subscribers":               { "display": true },
    "Brand Safety":              { "display": true },
    "Sponsorship Score":         { "display": true },
    "Sponsorships Sold":         { "display": true },
    "Brands Sold":               { "display": true },
    "Last Sold Sponsorship":     { "display": true },
    "Open Proposals Count":      { "display": true },
    "USA Share":                 { "display": true },
    "Demographics - Age Median": { "display": true },
    "Outreach Email":            { "display": true },
    "Channel URL":               { "display": true }
  },
  "dataset_structure": {
    "report_type": 3,
    "page_size": 25,
    "sort": "-publication_date_max"
  },
  "pending_refinement_suggestions": [
    "Add a 'Cost Per Projected View' custom formula ({Cost} / {Projected Views}, cellType: usd) — efficiency metric for product-placement budgeting",
    "Filter to channels with at least 1 prior sponsorship (Sponsorships Sold > 0) for warmer outreach"
  ],
  "_column_metadata": {
    "intent_consumed": "product placements (outreach)",
    "column_count": 13,
    "default_set_used": false,
    "concerns_surfaced": []
  }
}
```

13 columns — exceeds the 5–10 budget but justified by the outreach intent. Heavy on deal-history surface (`Sponsorship Score`, `Sponsorships Sold`, `Brands Sold`, `Last Sold Sponsorship`, `Open Proposals Count`, `Outreach Email`). Sort branches to `-publication_date_max` per pagination defaults' outreach-intent rule. Two refinement suggestions queued — one custom formula, one filter narrowing.

### Example C — Sponsorships report, won deals review (G04-class)

**Inputs**:
- `REPORT_TYPE`: 8
- `FILTERSET.filterset`: `{ start_date: "2026-01-01", end_date: "2026-03-31", sort: "-purchase_date" }`
- `FILTERSET.filters_json`: `{ publish_status: [3] }`
- `ROUTING_METADATA.intent_signal`: null

**Output**:
```json
{
  "columns": {
    "Channel":            { "display": true },
    "Advertiser":         { "display": true },
    "Status":             { "display": true },
    "Price":              { "display": true },
    "Cost":               { "display": true },
    "Revenue":            { "display": true },
    "Scheduled Date":     { "display": true },
    "Purchase Date":      { "display": true },
    "Owner Sales":        { "display": true },
    "Subscribers":        { "display": true }
  },
  "dataset_structure": {
    "report_type": 8,
    "page_size": 50,
    "sort": "-purchase_date"
  },
  "pending_refinement_suggestions": [
    "Add a 'TL profit' custom formula ({Price} - {Cost}, cellType: usd) — net profit per deal",
    "Add a 'ROAS' custom formula ({Price} ? {Revenue} / {Price} : 'N/A', cellType: regular) — return on ad spend"
  ],
  "_column_metadata": {
    "intent_consumed": null,
    "column_count": 10,
    "default_set_used": false,
    "concerns_surfaced": []
  }
}
```

Type-8 anchors (`Channel`, `Advertiser`, `Status`, `Price`, `Scheduled Date`) + sold-deals additions (`Cost`, `Revenue`, `Purchase Date`, `Owner Sales`) + one secondary channel-info column (`Subscribers`). Custom-formula suggestions queued in TL-glossary terms (`TL profit`, not "margin"; `ROAS` ratio).

### Example D — Channels report with name-resolver warning surfaced

**Inputs**:
- `REPORT_TYPE`: 3
- `FILTERSET.filterset`: `{ similar_to_channels via filters_json: ["Sanky"], reach_from: 50000 }`
- `ROUTING_METADATA.tool_warnings`: `["name_resolver matched 'Sanky' to 'Sanky' (1.2M reach, US) via emoji_stripped match — confirmed with user"]`

**Output**:
```json
{
  "columns": {
    "Channel":              { "display": true },
    "TL Channel Summary":   { "display": true },
    "Subscribers":          { "display": true },
    "Topic Descriptions":   { "display": true },
    "Engagement":           { "display": true },
    "Avg. Views":           { "display": true },
    "Country":              { "display": true },
    "Channel URL":          { "display": true }
  },
  "dataset_structure": {
    "report_type": 3,
    "page_size": 25,
    "sort": "-reach"
  },
  "pending_refinement_suggestions": [
    "Add a 'Views Per Subscriber' custom formula column ({Avg. Views} / {Subscribers}, cellType: percent) to spot high-engagement look-alikes"
  ],
  "_column_metadata": {
    "intent_consumed": null,
    "column_count": 8,
    "default_set_used": false,
    "concerns_surfaced": [
      "name_resolver matched 'Sanky' to 'Sanky' (1.2M reach, US) via emoji_stripped match — confirmed with user"
    ]
  }
}
```

Look-alike report (similar-to-channels intent). Added `Topic Descriptions` since vector similarity is topic-driven — helps the user verify why each channel matched. Tool warning passed through to `concerns_surfaced` so Phase 4 can include it in takeaways.

---

## Hard rules

1. **Display names match the column file exactly.** Case-sensitive, including spaces. The platform key-matches; typos silently drop. Never invent a display name.
2. **Pick 5–10 standard columns.** Intent-heavy reports may go up to 13 — flag the count in `_column_metadata.column_count`.
3. **`TL Channel Summary` is required for type 3.** It's the user's quick-evaluation surface (per `columns_channels.md`). Always present unless the user explicitly removes it.
4. **`Channel`, `Advertiser`, `Status` are type-8 anchors.** Always present.
5. **Don't cross catalogs.** Type-8 columns (`Status`, `Price`, `Match Grade`, etc.) are not interchangeable with type 1/2/3 columns. Each type's column file is the canonical list.
6. **Custom columns are suggestions, not silent additions.** Queue them in `pending_refinement_suggestions`; never emit `custom: true` columns unless the user explicitly asked for one.
7. **Sort validation is mandatory.** `dataset_structure.sort` must reference a column present in `columns` AND with an allowed direction in `SORTABLE_COLUMNS`. If a mismatch exists, add the column or surface a follow-up.
8. **`Latest AdSpot Price` over `TL Sponsorship Calc. Price`** when both could apply — the calc price is unreliable per `columns_channels.md`. Prefer `Latest AdSpot Price` for any pricing display on type 3.
9. **TL terminology in formula labels.** Use `TL profit` (not "margin"), `Net revenue` (not "margin"), `Reach` (not raw "subscribers"). Per `report_glossary.md`'s don't-use list.
10. **Echo `intent_signal` when consumed.** `_column_metadata.intent_consumed` is non-null whenever you swapped from the default set due to intent.
11. **Surface tool warnings.** `_column_metadata.concerns_surfaced` includes every entry from `ROUTING_METADATA.tool_warnings` and `ROUTING_METADATA.validation_concerns` that affected your column choices — Phase 4 reads this for takeaways.
12. **Order is part of the contract.** The order in the emitted `columns` dict IS the display order. Apply the anchors-first → intent-block → niche-additions → context-last strategy from Step 6. Don't shuffle randomly.
13. **Width hints only when deviating.** Only emit `"width": "wide"` for long-text columns and `"width": "narrow"` for compact ones. Default-width columns omit the key. Don't emit a width on every column — that's noise.

---

## Self-check before emitting

1. Output is a single valid JSON object — no fences, no prose around it.
2. Every key in `columns` matches a display name in the type's column file exactly (case-sensitive, including spaces).
3. Type-mandated anchors are present (type 3: `TL Channel Summary`; type 8: `Channel`, `Advertiser`, `Status`, `Price`, `Scheduled Date`).
4. Column count is 5–13. `_column_metadata.column_count` is set.
5. **Column order follows the strategy** — anchors first, then intent block, then niche additions, then context columns. Sort-target column is visible (in the intent block or earlier).
6. **Width hints only on deviation** — `"width": "wide"` for long-text content (`TL Channel Summary`, `Topic Descriptions`, `Channel Description`, etc.); `"width": "narrow"` for compact fields (`Status`, `Match Grade`, `Country`, `Language`); no width key for default.
7. No `custom: true` columns unless the user explicitly asked for one.
8. `dataset_structure.sort` references a column present in `columns` with an allowed direction.
9. `pending_refinement_suggestions` has at least one entry — typically a custom-formula suggestion.
10. `_column_metadata.intent_consumed` echoes the intent signal verbatim when you swapped from defaults; null otherwise.
11. `_column_metadata.concerns_surfaced` includes every tool_warning that affected column choice.
12. No cross-catalog mixing — type 1/2/3 columns and type-8 columns are not interchangeable.
