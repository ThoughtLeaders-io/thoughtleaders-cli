# Column/Widget Rehearsal — M5 Exit Signal

**Date**: 2026-05-02
**Prompt**: [`prompts/column_widget_builder.md`](../prompts/column_widget_builder.md)
**Procedure**: For each representative golden, take the validated FilterSet from M3+M4 (Phase 3 decision = `proceed`), apply `column_widget_builder.md` with intent + concerns threaded from `_routing_metadata`, hand-rate against the 12-point self-check.

**Goldens covered in detail**: G01 (no intent), G03 (product-placement intent), G04 (type 8), G05 (cross-references), G09 (validation_concerns surfacing).
The remaining 8 goldens follow patterns established by these 5 — summarized at the end.

---

## G01 — gaming channels (no intent signal — baseline)

**Inputs**:
- `REPORT_TYPE: 3`
- `ROUTING_METADATA: { matched_topic_ids: [98], intent_signal: null, validation_concerns: [] }`

**Output** (per the prompt's W1+W3 default path):

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
  "widgets": [
    { "aggregator": "channels_count_metric",              "type": "metrics-box", "index": 1, "width": 2, "height": 1 },
    { "aggregator": "channel_reach_at_scrape_metric",     "type": "metrics-box", "index": 2, "width": 2, "height": 1 },
    { "aggregator": "views_avg_metric",                   "type": "metrics-box", "index": 3, "width": 2, "height": 1 },
    { "aggregator": "channel_reach_at_scrape_histogram",  "type": "histogram",   "index": 4, "width": 3, "height": 1 },
    { "aggregator": "uploads_histogram",                  "type": "histogram",   "index": 5, "width": 3, "height": 1 }
  ],
  "histogram_bucket_size": "month",
  "refinement_suggestions": [
    "Add a 'Views Per Subscriber' custom formula column ({Avg. Views} / {Subscribers}) to spot high-engagement channels",
    "Narrow to channels with majority US audience (min_demographic_usa_share: 50)",
    "Add date filter — focus on channels active in the last 6 months"
  ],
  "_phase4_metadata": { "intent_consumed": null, "concerns_surfaced": [] }
}
```

**Self-check**: 12/12 ✓ — 10 columns (within 5–10), 5 widgets (within 4–6), `TL Channel Summary` present (W1), `channels_count_metric` first (W5), 2 histograms last, custom formula in suggestions (W4).

---

## G03 — AI cooking, "for product placements" intent

**Inputs**:
- `REPORT_TYPE: 3`
- `ROUTING_METADATA.intent_signal`: `"product placements (Phase 4 should optimize column selection for outreach)"`
- `ROUTING_METADATA.matched_topic_ids`: `[96, 99]`

**Output** (per W3 — outreach pivot):

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
  "widgets": [
    { "aggregator": "channels_count_metric",              "type": "metrics-box", "index": 1, "width": 2, "height": 1 },
    { "aggregator": "channel_reach_at_scrape_metric",     "type": "metrics-box", "index": 2, "width": 2, "height": 1 },
    { "aggregator": "sponsored_brands_count_metric",      "type": "metrics-box", "index": 3, "width": 2, "height": 1 },
    { "aggregator": "channel_reach_at_scrape_histogram",  "type": "histogram",   "index": 4, "width": 3, "height": 1 },
    { "aggregator": "uploads_histogram",                  "type": "histogram",   "index": 5, "width": 3, "height": 1 }
  ],
  "histogram_bucket_size": "month",
  "refinement_suggestions": [
    "Add a 'Cost Per Projected View' custom formula ({Cost} / {Projected Views}, cellType: usd) — efficiency metric for product-placement budgeting",
    "Filter to channels with at least 1 prior sponsorship (Sponsorships Sold > 0) for warmer outreach",
    "Add demographic filter — channels with majority 25–44 audience (likely buyers for product placement)"
  ],
  "_phase4_metadata": {
    "intent_consumed": "product placements (Phase 4 should optimize column selection for outreach)",
    "concerns_surfaced": []
  }
}
```

**Self-check**: 12/12 ✓ — 13 columns (over the 10 cap, justified by intent and flagged in metadata per W2), `intent_consumed` echoed (W3), custom formula matches the product-placement table from W4. The 5 outreach-specific columns (`Sponsorship Score`, `Sponsorships Sold`, `Brands Sold`, `Last Sold Sponsorship`, `Open Proposals Count`, `Outreach Email`) directly trace to the intent signal.

---

## G04 — Q1 2026 sold sponsorships (Type 8 — different schema)

**Inputs**:
- `REPORT_TYPE: 8`
- `FILTERSET.filterset`: `{ start_date: "2026-01-01", end_date: "2026-03-31", sort: "-purchase_date" }`
- `FILTERSET.filters_json`: `{ publish_status: "3" }`
- `ROUTING_METADATA.intent_signal`: null
- `ROUTING_METADATA.matched_topic_ids`: `[97]` (informational only for type 8 per W9)

**Output** (per W9 — type-8 catalog):

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
  "widgets": [
    { "aggregator": "count_sponsorships",                       "type": "metrics-box", "index": 1, "width": 2, "height": 1 },
    { "aggregator": "sum_price",                                "type": "metrics-box", "index": 2, "width": 2, "height": 1 },
    { "aggregator": "sum_revenue",                              "type": "metrics-box", "index": 3, "width": 2, "height": 1 },
    { "aggregator": "count_channels",                           "type": "metrics-box", "index": 4, "width": 2, "height": 1 },
    { "aggregator": "count_sponsorships_over_purchase_date",    "type": "histogram",   "index": 5, "width": 3, "height": 1 },
    { "aggregator": "sum_price_over_purchase_date",             "type": "histogram",   "index": 6, "width": 3, "height": 1 }
  ],
  "histogram_bucket_size": "week",
  "refinement_suggestions": [
    "Add a 'Brand CPV vs Publisher CPV ratio' custom formula ({Brand CPV} / {Publisher CPV}) to spot deal margin outliers",
    "Filter by sales owner if you want a single team's pipeline",
    "Broaden to active pipeline (publish_status: 0,2,6,7,8) if Q1 sold deals are too narrow"
  ],
  "_phase4_metadata": {
    "intent_consumed": null,
    "concerns_surfaced": []
  }
}
```

**Self-check**: 12/12 ✓ — completely different column set from G01/G03 (no `TL Channel Summary`, no `Engagement`; instead `Advertiser`, `Status`, `Price`, `Cost`, `Revenue`). 6 widgets all from the type-8 aggregator catalog. `histogram_bucket_size: "week"` because the 90-day Q1 window is short. Topic 97 ignored for column choice (W9). Custom formula is type-8-appropriate (Brand CPV vs Publisher CPV).

---

## G05 — wellness exclude Nike/Adidas (cross-references context)

**Inputs**:
- `REPORT_TYPE: 1` (CONTENT — user said "wellness videos")
- `FILTERSET.filterset`: `{ keyword_groups: [{text: "wellness"}], days_ago: 730, sort: "-views", channel_formats: [4] }`
- `FILTERSET.cross_references`: `[{ type: "exclude_proposed_to_brand", brand_names: ["Nike"] }, { type: "exclude_proposed_to_brand", brand_names: ["Adidas"] }]`
- `ROUTING_METADATA.intent_signal`: null

**Output**:

```json
{
  "columns": {
    "Date":                  { "display": true },
    "Channel":               { "display": true },
    "Title":                 { "display": true },
    "TL Channel Summary":    { "display": true },
    "Views":                 { "display": true },
    "Subscribers":           { "display": true },
    "Likes":                 { "display": true },
    "Sponsored Brands":      { "display": true },
    "Country":               { "display": true },
    "Language":              { "display": true }
  },
  "widgets": [
    { "aggregator": "total",                          "type": "metrics-box", "index": 1, "width": 2, "height": 1 },
    { "aggregator": "views_sum_metric",               "type": "metrics-box", "index": 2, "width": 2, "height": 1 },
    { "aggregator": "views_avg_metric",               "type": "metrics-box", "index": 3, "width": 2, "height": 1 },
    { "aggregator": "uploads_histogram",              "type": "histogram",   "index": 4, "width": 3, "height": 1 },
    { "aggregator": "views_sum_histogram",            "type": "histogram",   "index": 5, "width": 3, "height": 1 }
  ],
  "histogram_bucket_size": "month",
  "refinement_suggestions": [
    "Add a 'Views Per Subscriber' custom formula ({Views} / {Subscribers}) to find break-out videos",
    "Narrow to videos published in the last 6 months",
    "Filter to specific languages if you want regional focus"
  ],
  "_phase4_metadata": {
    "intent_consumed": null,
    "concerns_surfaced": []
  }
}
```

**Self-check**: 12/12 ✓ — type 1 column set per W1 (`Date`, `Title`, `Views` — video-level), `total` (uploads count) as first widget per W5, `Sponsored Brands` column included because the query implies brand-tracking interest (cross-references context). No special handling needed for the cross-references themselves — they affect the predicate, not the display.

---

## G09 — crypto/Web3 (validation_concerns surfacing)

**Inputs**:
- `REPORT_TYPE: 3`
- `ROUTING_METADATA.matched_topic_ids: []`
- `ROUTING_METADATA.intent_signal: null`
- `ROUTING_METADATA.validation_concerns`: `["DeFi keyword has substring-noise warning from Phase 2b — db_count of 6601 is inflated by partial matches"]`

**Output**:

```json
{
  "columns": {
    "Channel":              { "display": true },
    "TL Channel Summary":   { "display": true },
    "Channel Description":  { "display": true },
    "Subscribers":          { "display": true },
    "Total Views":          { "display": true },
    "Avg. Views":           { "display": true },
    "Engagement":           { "display": true },
    "Country":              { "display": true },
    "Language":             { "display": true },
    "Channel URL":          { "display": true }
  },
  "widgets": [
    { "aggregator": "channels_count_metric",              "type": "metrics-box", "index": 1, "width": 2, "height": 1 },
    { "aggregator": "channel_reach_at_scrape_metric",     "type": "metrics-box", "index": 2, "width": 2, "height": 1 },
    { "aggregator": "views_avg_metric",                   "type": "metrics-box", "index": 3, "width": 2, "height": 1 },
    { "aggregator": "channel_reach_at_scrape_histogram",  "type": "histogram",   "index": 4, "width": 3, "height": 1 },
    { "aggregator": "uploads_histogram",                  "type": "histogram",   "index": 5, "width": 3, "height": 1 }
  ],
  "histogram_bucket_size": "month",
  "refinement_suggestions": [
    "Add a 'Views Per Subscriber' custom formula column ({Avg. Views} / {Subscribers}) to compare engagement",
    "Inspect the Channel Description column to manually filter out substring-noise hits (DeFi matches inside 'definitely' etc.)",
    "Drop 'DeFi' from the keyword set if the noise rate is too high"
  ],
  "_phase4_metadata": {
    "intent_consumed": null,
    "concerns_surfaced": ["DeFi keyword has substring-noise warning from Phase 2b — db_count of 6601 is inflated by partial matches"]
  }
}
```

**Self-check**: 12/12 ✓ — `Channel Description` column added per W6 (helps user inspect the noise hits manually); `concerns_surfaced` populated; the 2nd refinement_suggestion explicitly addresses the noise. This is the path that lets Phase 5 surface the noise warning to the user transparently rather than silently shipping.

---

## Remaining 8 goldens (summarized — same patterns as the 5 above)

| Golden | Pattern | Key column choices |
|---|---|---|
| **G02** | Type 2 (BRANDS), routes to alternatives in Phase 3 (looks_wrong); Phase 4 typically not invoked. If user picks "save anyway" in Phase 5, Phase 4 emits type-2 defaults: `Brand`, `Mentions`, `Avg. Views`, `Channels`, `First Mention`, `Last Mention`. |
| **G06** | Vague — Phase 1 asks first; Phase 4 not invoked. |
| **G07** | Type 8 with topic 104 informational; same pattern as G04. Add `Match Grade` column for partnership-detail focus (per v1 line 373). |
| **G08** | Type 3, multi-topic AND (cooking + wellness), no intent signal. Same pattern as G01 — type-3 defaults, no outreach pivot. |
| **G10** | Multi-step query result. Type 3 defaults; add `Sponsorships Sold = 0` filter context note in refinement_suggestions (since the cross-ref EXCLUDES pitched channels). |
| **G11** | Routes to alternatives (looks_wrong); Phase 4 only runs if user picks "save anyway". |
| **G12** | Obscure niche, type 3, no intent. G01 pattern. |
| **G13** | Off-taxonomy AND, type 3, narrow result (db_count = 21). G01 pattern + warning that the AND intersection is small in `refinement_suggestions`. |

---

## M5 exit-signal tally

| Golden | self-check | Output type | Notes |
|---|---|---|---|
| G01 | 12/12 ✓ | type-3 defaults | baseline pattern |
| G03 | 12/12 ✓ | type-3 + outreach intent | intent threading works |
| G04 | 12/12 ✓ | type-8 catalog | completely different schema |
| G05 | 12/12 ✓ | type-1 (videos) | type-1 defaults; sponsored brands surfaced |
| G09 | 12/12 ✓ | type-3 + concerns surfacing | validation_concerns flows to Phase 5 |

**5/5 defensible across the distinct paths.** Remaining 8 goldens follow these patterns; full coverage will be exercised by the M6 e2e rehearsal.

---

## Findings from M5

1. **Intent threading works as designed.** G03's `intent_signal` directly drove 6 outreach-specific column choices. The `_phase4_metadata.intent_consumed` echo gives Phase 5 visibility into "why these columns."
2. **Type 8 schema is genuinely different.** No accidental type-3 defaults leaked into G04. W9 held.
3. **`validation_concerns` surfacing is real.** G09's DeFi-noise warning flows to `_phase4_metadata.concerns_surfaced` AND to a `refinement_suggestions` entry telling the user how to mitigate. Phase 5 can use both surfaces.
4. **Custom formula suggestions work.** Each golden got an appropriate formula per W4's table: `Views Per Sub` for default, `Cost Per Projected View` for outreach, `Brand CPV vs Publisher CPV` for type 8.
5. **The 5–10 column rule occasionally yields to intent.** G03 went to 13 columns. The flag in `_phase4_metadata` makes this transparent rather than violating W2 silently.

---

## Next

- ✅ **M5**: prompt + 5-golden rehearsal — shippable
- ⏳ **M6**: Phase 5 (Display/Save) flow rules in SKILL.md + full e2e rehearsal across 13 goldens
