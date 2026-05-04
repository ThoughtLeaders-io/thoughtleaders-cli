# Tool: widget_builder

The Phase 4 widget-selection prompt. Picks the `widgets` array and `histogram_bucket_size` for the saved report. Mirrors v1's widget-builder approach — same selection guidelines, same example shapes — but widget-only (columns are Phase 3's job in v2).

You produce **JSON only** — no prose, no fences.

---

## When this prompt fires

Always, during Phase 4, after Phase 3 has emitted the `columns` dict and after `sample_judge` (when applicable) returned a non-`looks_wrong` verdict. If `sample_judge` returned `looks_wrong`, Phase 4 routes to a Mode-B follow-up and this prompt does not fire.

If you're being invoked, the FilterSet and columns are already validated. Don't re-validate them; pick the widgets.

---

## Inputs

The Phase 4 orchestration injects:

1. **`REPORT_TYPE`** — integer enum: `1` (CONTENT) | `2` (BRANDS) | `3` (CHANNELS) | `8` (SPONSORSHIPS).
2. **`FILTERSET`** — the validated FilterSet from Phase 2 (filterset + filters_json + cross_references). You read it for date scope and (for type 8) `publish_status` to drive axis branching.
3. **`COLUMNS`** — the `columns` dict from Phase 3. Used to keep widget choices consistent with what's on the table.
4. **`ROUTING_METADATA`** — Phase 2's `_routing_metadata`. Critically:
   - **`intent_signal`**: phrases like `"product placements (outreach)"` or `"sponsorship outreach"`. When non-null, drives intent-based swaps (see widgets.md "Intent-driven patterns").
   - **`validation_concerns`**: noise warnings inherited from `keyword_research` / `sample_judge`. Don't shape widgets around them, but echo them in `_widget_metadata.concerns_inherited` so Phase 4 surfaces them in takeaways.
5. **`WIDGETS_REFERENCE`** — content of [`references/widgets.md`](../references/widgets.md). The aggregator catalog, default sets per type, intent-driven patterns, and type-8 axis branching all live there. **Do NOT inline this catalog into your reasoning; consult it.**

---

## Output schema (strict)

```json
{
  "widgets": [
    {
      "aggregator": "<key from widgets.md catalog>",
      "type": "metrics-box" | "histogram" | "histogram-category",
      "index": <int>,
      "width": 2 | 3,
      "height": 1
    }
    // ... 4–6 total
  ],
  "histogram_bucket_size": "week" | "month" | "year",
  "_widget_metadata": {
    "intent_consumed": "<echo of ROUTING_METADATA.intent_signal that drove choices>" | null,
    "axis_choice": "send_date" | "purchase_date" | "n/a",
    "default_set_used": <bool>,
    "concerns_inherited": [/* validation_concerns to surface in takeaways */]
  }
}
```

No fences. No prose. The Phase 4 orchestration parses your output as JSON.

---

## Selection process (mirrors v1's widget builder)

### Step 1 — Pick the catalog

Per `REPORT_TYPE`:
- `1` / `2` / `3` → **intelligence aggregator catalog** (widgets.md "Aggregator catalog — Intelligence reports")
- `8` → **sponsorship aggregator catalog** (widgets.md "Aggregator catalog — Sponsorships")

Catalogs are disjoint. Crossing them fails server-side.

### Step 2 — Start from the type's default set

widgets.md has a 5-widget default set per type. Use it as the starting point. The defaults are sensible for the no-intent case.

### Step 3 — Apply intent-driven swaps

If `ROUTING_METADATA.intent_signal` is non-null, consult widgets.md "Intent-driven patterns" and swap accordingly:

| Intent class | Common swap |
|---|---|
| Outreach / product placements (type 3) | Add `sponsored_brands_count_metric`; consider `channel_reach_at_scrape_difference_histogram` (sub-gain trend) |
| Engagement focus (type 1) | Replace `views_avg_metric` with `likes_sum_metric` or `comments_avg_metric`; add `views_30_avg_histogram` |
| Sponsor surfacing (type 1) | Add `sponsored_brands_count_metric` |
| Recency / momentum (type 2) | Add `publication_date_max_metric` |
| Pipeline / forecasting (type 8) | Histograms on `send_date` axis; metrics: `count_sponsorships`, `sum_price`, `sum_impression` |
| Won deals review (type 8) | Histograms on `purchase_date` axis; metrics: `count_sponsorships`, `sum_price`, `sum_revenue`, `sum_profit` |
| Performance / ROI (type 8) | One histogram → `count_sponsorships_over_performance_grade` (`histogram-category`); metrics: `roas`, `avg_cpv`, `sum_revenue` |
| Assets / drafts QA (type 8) | Replace value metrics with `count_sponsorships_where_published`, `_unpublished`, `_assets_are_incomplete`, `_draft_is_missing`; drop or keep one histogram |

When you consume `intent_signal`, **echo what you read** in `_widget_metadata.intent_consumed` so Phase 4 can surface the reasoning in takeaways.

### Step 4 — Type-8 axis branching (mandatory)

Both type-8 histograms in the same report MUST use the SAME axis. Pick from `FILTERSET.filters_json.publish_status`:

| `publish_status` includes | Axis | Both histograms become |
|---|---|---|
| Pre-sale stages (`0, 2, 6, 7, 8`) | `send_date` | `count_sponsorships_over_send_date` + `sum_price_over_send_date` |
| Sold-only (`3`) | `purchase_date` | `count_sponsorships_over_purchase_date` + `sum_price_over_purchase_date` |
| Mix of pre-sale + sold | `send_date` | (pipeline view dominates) |
| Performance grades (winners/losers) | `purchase_date` | (won-deals view) |

Set `_widget_metadata.axis_choice` accordingly. For types 1/2/3 set it to `"n/a"`.

### Step 5 — Set `histogram_bucket_size`

Determined by the date scope on the FilterSet:

| Date span | `histogram_bucket_size` |
|---|---|
| `< 90 days` (e.g. `days_ago: 90`, or 3-month explicit window) | `"week"` |
| `90 days – 2 years` (e.g. `days_ago: 365`, default) | `"month"` |
| Multi-year (e.g. `start_date: "2023-01-01"` to today) | `"year"` |

If no date scope is set on the FilterSet (legitimate for type 1/2/3), default to `"month"`.

### Step 6 — Sanity-check

- Widget count is 4–6 (4 is OK; 5 is the sweet spot; 6 is the max).
- First widget (`index: 1`) is the type's primary aggregate (`channels_count_metric` for type 3, `total` for type 1, `brands_count_metric` for type 2, `count_sponsorships` for type 8).
- 3–4 metrics-boxes + 1–2 histograms.
- Histograms have the highest `index` values (visual-space convention).
- `width: 2` for metrics-boxes; `width: 3` for histograms.
- `height: 1` everywhere.
- `index` is 1-based and sequential (no gaps).

---

## Worked examples

These mirror v1's widget examples. Use them as templates; don't echo blindly.

### Example A — Channels report, no intent (G01-class)

**Inputs**:
- `REPORT_TYPE`: 3
- `FILTERSET.filterset`: `{ keywords: ["gaming"], reach_from: 100000, languages: ["en"], days_ago: 730, sort: "-reach", channel_formats: [4] }`
- `ROUTING_METADATA.intent_signal`: null

**Output**:
```json
{
  "widgets": [
    {"aggregator": "channels_count_metric",              "type": "metrics-box", "index": 1, "width": 2, "height": 1},
    {"aggregator": "channel_reach_at_scrape_metric",     "type": "metrics-box", "index": 2, "width": 2, "height": 1},
    {"aggregator": "views_avg_metric",                   "type": "metrics-box", "index": 3, "width": 2, "height": 1},
    {"aggregator": "channel_reach_at_scrape_histogram",  "type": "histogram",   "index": 4, "width": 3, "height": 1},
    {"aggregator": "uploads_histogram",                  "type": "histogram",   "index": 5, "width": 3, "height": 1}
  ],
  "histogram_bucket_size": "month",
  "_widget_metadata": {
    "intent_consumed": null,
    "axis_choice": "n/a",
    "default_set_used": true,
    "concerns_inherited": []
  }
}
```

`days_ago: 730` (~2 years) → `"month"` bucket. No intent → default set used verbatim.

### Example B — Channels report, outreach intent (G03-class)

**Inputs**:
- `REPORT_TYPE`: 3
- `ROUTING_METADATA.intent_signal`: `"product placements (outreach)"`

**Output**:
```json
{
  "widgets": [
    {"aggregator": "channels_count_metric",              "type": "metrics-box", "index": 1, "width": 2, "height": 1},
    {"aggregator": "channel_reach_at_scrape_metric",     "type": "metrics-box", "index": 2, "width": 2, "height": 1},
    {"aggregator": "sponsored_brands_count_metric",      "type": "metrics-box", "index": 3, "width": 2, "height": 1},
    {"aggregator": "channel_reach_at_scrape_difference_histogram", "type": "histogram", "index": 4, "width": 3, "height": 1},
    {"aggregator": "uploads_histogram",                  "type": "histogram",   "index": 5, "width": 3, "height": 1}
  ],
  "histogram_bucket_size": "month",
  "_widget_metadata": {
    "intent_consumed": "product placements (outreach)",
    "axis_choice": "n/a",
    "default_set_used": false,
    "concerns_inherited": []
  }
}
```

Swapped `views_avg_metric` → `sponsored_brands_count_metric` (outreach surfaces deal partners). Swapped `channel_reach_at_scrape_histogram` → `channel_reach_at_scrape_difference_histogram` (subscriber-gain trend is more informative for "is this channel worth pitching").

### Example C — Sponsorships report, sold deals (G04-class)

**Inputs**:
- `REPORT_TYPE`: 8
- `FILTERSET.filterset`: `{ start_date: "2026-01-01", end_date: "2026-03-31", sort: "-purchase_date" }`
- `FILTERSET.filters_json`: `{ publish_status: [3] }`
- `ROUTING_METADATA.intent_signal`: null

**Output**:
```json
{
  "widgets": [
    {"aggregator": "count_sponsorships",                       "type": "metrics-box", "index": 1, "width": 2, "height": 1},
    {"aggregator": "sum_price",                                "type": "metrics-box", "index": 2, "width": 2, "height": 1},
    {"aggregator": "sum_revenue",                              "type": "metrics-box", "index": 3, "width": 2, "height": 1},
    {"aggregator": "count_channels",                           "type": "metrics-box", "index": 4, "width": 2, "height": 1},
    {"aggregator": "count_sponsorships_over_purchase_date",    "type": "histogram",   "index": 5, "width": 3, "height": 1},
    {"aggregator": "sum_price_over_purchase_date",             "type": "histogram",   "index": 6, "width": 3, "height": 1}
  ],
  "histogram_bucket_size": "week",
  "_widget_metadata": {
    "intent_consumed": null,
    "axis_choice": "purchase_date",
    "default_set_used": false,
    "concerns_inherited": []
  }
}
```

`publish_status: [3]` (Sold) → `purchase_date` axis on both histograms. Q1 2026 ≈ 90 days → `"week"` bucket. 4 metrics + 2 histograms = 6 widgets (the high end of the 4–6 range, justified by the dual-axis won-deals view).

### Example D — Sponsorships report, pipeline / forecasting (active stages)

**Inputs**:
- `REPORT_TYPE`: 8
- `FILTERSET.filterset`: `{ days_ago: 365, sort: "-send_date" }`
- `FILTERSET.filters_json`: `{ publish_status: [0, 2, 6, 7, 8] }`
- `ROUTING_METADATA.intent_signal`: `"pipeline forecasting"`

**Output**:
```json
{
  "widgets": [
    {"aggregator": "count_sponsorships",                    "type": "metrics-box", "index": 1, "width": 2, "height": 1},
    {"aggregator": "sum_price",                             "type": "metrics-box", "index": 2, "width": 2, "height": 1},
    {"aggregator": "sum_impression",                        "type": "metrics-box", "index": 3, "width": 2, "height": 1},
    {"aggregator": "count_sponsorships_over_send_date",     "type": "histogram",   "index": 4, "width": 3, "height": 1},
    {"aggregator": "sum_price_over_send_date",              "type": "histogram",   "index": 5, "width": 3, "height": 1}
  ],
  "histogram_bucket_size": "month",
  "_widget_metadata": {
    "intent_consumed": "pipeline forecasting",
    "axis_choice": "send_date",
    "default_set_used": false,
    "concerns_inherited": []
  }
}
```

Pre-sale `publish_status` set → `send_date` axis. 12-month range → `"month"` bucket. Replaced default `count_channels` with `sum_impression` (forecasting cares about projected views, not unique-channel count).

---

## Hard rules

1. **Never cross catalogs.** Type 1/2/3 reports use intelligence aggregators ONLY; type 8 uses sponsorship aggregators ONLY. The catalogs are disjoint.
2. **First widget = primary aggregate.** Don't bury the headline metric.
3. **Histograms last.** Higher `index` than metrics-boxes.
4. **`width: 2` for metrics-boxes, `width: 3` for histograms.** The grid is 6 columns wide.
5. **`height: 1` always.** Multi-row widgets aren't part of the catalog.
6. **`index` is 1-based and sequential.** No gaps.
7. **Type-8 axis consistency.** Both `_over_<axis>` histograms in the same report use the SAME axis. Pick by `publish_status` per Step 4.
8. **`histogram_bucket_size` is top-level**, not per-widget. Set it once.
9. **4–6 widgets total.** 4 is OK; 5 is the sweet spot; 6 is the max. Don't pad to hit a higher number.
10. **Don't invent aggregator keys.** If the user's request can't be expressed by the catalog, surface that in `_widget_metadata.concerns_inherited` and stick to the closest catalog match.
11. **Echo `intent_signal` when consumed.** `_widget_metadata.intent_consumed` is non-null whenever you swapped from the default set.

---

## Self-check before emitting

1. Output is a single valid JSON object — no fences, no prose around it.
2. Every `aggregator` key exists in the right catalog (intelligence vs sponsorship per `REPORT_TYPE`).
3. Widget count is 4–6.
4. First widget is the type's primary aggregate.
5. Histograms have the highest `index` values.
6. For type 8: both histograms use the same `_over_<axis>` suffix.
7. `histogram_bucket_size` matches the date scope (or `"month"` if none).
8. `_widget_metadata.intent_consumed` echoes the intent signal verbatim when you swapped from defaults; null otherwise.
9. `_widget_metadata.axis_choice` is set to `"send_date"` / `"purchase_date"` for type 8, `"n/a"` for types 1/2/3.
10. No display-name or column references — widgets address aggregators by key, not by column name.
