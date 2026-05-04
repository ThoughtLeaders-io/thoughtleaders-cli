# Widgets

Reference for Phase 4 (Widget Phase). Widgets are the dashboard charts and metric boxes that appear above the data table on a saved report. Phase 4 reads this file to pick which widgets to emit.

The output Phase 4 emits is a `widgets` array of `{aggregator, type, index, width, height}` objects, plus a top-level `histogram_bucket_size`.

---

## Widget JSON shape

```json
{
  "aggregator": "<key from the catalogs below>",
  "type": "metrics-box" | "histogram" | "histogram-category",
  "index": <int>,           // 1-based display order, sequential
  "width": 2 | 3,            // grid column span (grid is 6 wide)
  "height": 1                // always 1
}
```

Widths: `2` for metrics-boxes, `2`–`3` for histograms.

`histogram_bucket_size` is set at the top level (not per widget) and applies to every histogram in the report:

| Date range | `histogram_bucket_size` |
|---|---|
| < 90 days | `"week"` |
| 90 days – 2 years | `"month"` (default) |
| Multi-year | `"year"` |

---

## Selection guidelines (cross-cutting)

1. **4–6 widgets per report.** Less feels empty; more clutters.
2. **Mix metrics-boxes and histograms.** Good pattern: 3–4 metrics-boxes + 1–2 histograms.
3. **First widget (index 1) is the most important aggregate** for the report's purpose — usually a count or a primary sum.
4. **Histograms go last** (higher `index`) — they take more visual space.
5. **Don't cross catalogs.** Type 1/2/3 reports use the intelligence aggregator catalog; type 8 uses the sponsorship catalog. They are not interchangeable.
6. **`histogram_bucket_size` matches the date scope** — see the table above.

---

## Aggregator catalog — Intelligence reports (types 1, 2, 3)

### Views on videos
- `views_sum_metric` (metrics-box) — total views across matching content
- `views_sum_histogram` (histogram) — views over time by publish date
- `views_avg_metric` (metrics-box) — average views per video
- `views_avg_histogram` (histogram) — average views over time
- `views_median_metric` (metrics-box) — median views per video
- `views_median_histogram` (histogram) — median views over time
- `views_last_value_metric` (metrics-box) — views on the most recent video

### Uploads & counts
- `total` (metrics-box) — total matching uploads
- `uploads_histogram` (histogram) — upload count over time
- `channels_count_metric` / `channel_count` (metrics-box) — unique channels
- `channels_count_histogram` (histogram) — channel count over time
- `brands_count_metric` / `brand_count` (metrics-box) — unique brands mentioned
- `brands_count_histogram` (histogram) — brands mentioned over time
- `sponsored_brands_count_metric` (metrics-box) — sponsoring brands
- `sponsored_brands_count_histogram` (histogram) — sponsoring brands over time

### Engagement
- `likes_sum_metric` (metrics-box) — total likes
- `likes_sum_histogram` (histogram) — likes over time
- `likes_avg_metric` (metrics-box) — avg likes per video
- `likes_avg_histogram` (histogram) — avg likes over time
- `comments_sum_metric` (metrics-box) — total comments
- `comments_avg_metric` (metrics-box) — avg comments per video

### Duration
- `duration_avg_metric` (metrics-box) — avg video duration
- `duration_avg_histogram` (histogram) — avg duration over time
- `duration_median_metric` (metrics-box) — median video duration

### Subscribers (channel-level)
- `channel_reach_at_scrape_metric` (metrics-box) — total subscribers across channels
- `channel_reach_at_scrape_histogram` (histogram) — subscriber growth over time
- `channel_reach_at_scrape_difference_histogram` (histogram) — subscriber gains over time
- `channel_reach_last_28_days` (metrics-box) — subscriber change in last 28 days

### Channel total views
- `channel_total_views_at_scrape_metric` (metrics-box) — total channel views
- `channel_total_views_at_scrape_histogram` (histogram) — channel views over time
- `channel_total_views_last_28_days` (metrics-box) — channel views change in 28 days

### Evergreen
- `evergreenness_avg_metric` (metrics-box) — avg evergreen score
- `evergreenness_median_metric` (metrics-box) — median evergreen score

### Publish date
- `publication_date_max_metric` (metrics-box) — most recent publish date
- `publication_date_min_metric` (metrics-box) — earliest publish date

### Early-life performance (views after N days)
- `views_7_avg_histogram` (histogram) — avg views at 7 days, over time
- `views_30_avg_histogram` (histogram) — avg views at 30 days, over time

---

## Aggregator catalog — Sponsorships (type 8)

### Core sponsorships
- `count_sponsorships` (metrics-box) — total sponsorship count
- `count_sponsorships_over_send_date` (histogram) — sponsorships scheduled over time
- `count_sponsorships_over_purchase_date` (histogram) — sponsorships purchased over time
- `sum_cost` (metrics-box) — total cost
- `sum_price` (metrics-box) — total price
- `sum_price_over_send_date` (histogram) — price scheduled over time
- `sum_price_over_purchase_date` (histogram) — price purchased over time
- `sum_profit` (metrics-box) — net profit (`price - cost`)
- `sum_impression` (metrics-box) — total projected views
- `count_channels` (metrics-box) — unique channels in deal set

### Live ads tracking
- `sum_views` (metrics-box) — actual views on published ads
- `sum_projected_views` (metrics-box) — projected views at day 30
- `avg_cpv` (metrics-box) — avg cost per view
- `sum_conversions` (metrics-box) — total conversions
- `sum_revenue` (metrics-box) — total revenue
- `avg_cpa` (metrics-box) — avg cost per acquisition
- `roas` (metrics-box) — return on ad spend

### Performance
- `count_sponsorships_over_performance_grade` (histogram-category) — sponsorships by grade
- `count_sponsorships_where_winner` (metrics-box) — winning sponsorship count
- `count_sponsorships_where_loser` (metrics-box) — losing sponsorship count
- `sum_price_where_winner` (metrics-box) — total price of winners
- `sum_price_over_performance_grade` (histogram-category) — price by grade

### Assets & drafts
- `count_sponsorships_where_unpublished` (metrics-box) — unpublished count
- `count_sponsorships_where_published` (metrics-box) — published count
- `count_sponsorships_where_assets_are_incomplete` (metrics-box) — incomplete assets count
- `count_sponsorships_where_draft_is_missing` (metrics-box) — missing drafts count

---

## Default widget sets per ReportType

When the user gives no widget preferences, emit these 5-widget defaults. Adjust based on intent (see "Intent-driven patterns" below).

### Type 1 (CONTENT) — default
```json
[
  {"aggregator": "total",                "type": "metrics-box", "index": 1, "width": 2, "height": 1},
  {"aggregator": "views_sum_metric",     "type": "metrics-box", "index": 2, "width": 2, "height": 1},
  {"aggregator": "views_avg_metric",     "type": "metrics-box", "index": 3, "width": 2, "height": 1},
  {"aggregator": "uploads_histogram",    "type": "histogram",   "index": 4, "width": 3, "height": 1},
  {"aggregator": "views_sum_histogram",  "type": "histogram",   "index": 5, "width": 3, "height": 1}
]
```

### Type 2 (BRANDS) — default
```json
[
  {"aggregator": "brands_count_metric",     "type": "metrics-box", "index": 1, "width": 2, "height": 1},
  {"aggregator": "total",                   "type": "metrics-box", "index": 2, "width": 2, "height": 1},
  {"aggregator": "views_sum_metric",        "type": "metrics-box", "index": 3, "width": 2, "height": 1},
  {"aggregator": "brands_count_histogram",  "type": "histogram",   "index": 4, "width": 3, "height": 1},
  {"aggregator": "views_sum_histogram",     "type": "histogram",   "index": 5, "width": 3, "height": 1}
]
```

### Type 3 (CHANNELS) — default
```json
[
  {"aggregator": "channels_count_metric",              "type": "metrics-box", "index": 1, "width": 2, "height": 1},
  {"aggregator": "channel_reach_at_scrape_metric",     "type": "metrics-box", "index": 2, "width": 2, "height": 1},
  {"aggregator": "views_avg_metric",                   "type": "metrics-box", "index": 3, "width": 2, "height": 1},
  {"aggregator": "channel_reach_at_scrape_histogram",  "type": "histogram",   "index": 4, "width": 3, "height": 1},
  {"aggregator": "uploads_histogram",                  "type": "histogram",   "index": 5, "width": 3, "height": 1}
]
```

### Type 8 (SPONSORSHIPS) — default
The first histogram axis branches on the user's date framing — see "Type-8 axis branching" below.

```json
[
  {"aggregator": "count_sponsorships",  "type": "metrics-box", "index": 1, "width": 2, "height": 1},
  {"aggregator": "sum_price",           "type": "metrics-box", "index": 2, "width": 2, "height": 1},
  {"aggregator": "count_channels",      "type": "metrics-box", "index": 3, "width": 2, "height": 1},
  {"aggregator": "count_sponsorships_over_<axis>",  "type": "histogram", "index": 4, "width": 3, "height": 1},
  {"aggregator": "sum_price_over_<axis>",            "type": "histogram", "index": 5, "width": 3, "height": 1}
]
```

---

## Intent-driven patterns

### Type 3 (CHANNELS) — outreach / product placements intent
Add `sponsored_brands_count_metric` to the metric line; consider replacing one histogram with `channel_reach_at_scrape_difference_histogram` (subscriber-gain trend).

### Type 1 (CONTENT) — engagement focus
Replace `views_avg_metric` with `likes_sum_metric` or `comments_avg_metric`; consider `views_30_avg_histogram` to show early-life trend.

### Type 1 (CONTENT) — sponsor-surfacing
Add `sponsored_brands_count_metric`; consider keeping `total` + `views_sum_metric` for context.

### Type 2 (BRANDS) — recency / momentum focus
Add `publication_date_max_metric` to surface "last mention." Useful when the user is auditing whether a brand is currently active.

### Type 8 (SPONSORSHIPS) — pipeline / forecasting
Histogram axis: `count_sponsorships_over_send_date` + `sum_price_over_send_date` (the schedule view). Metric line: `count_sponsorships`, `sum_price`, `sum_impression`.

### Type 8 (SPONSORSHIPS) — won deals review
Histogram axis: `count_sponsorships_over_purchase_date` + `sum_price_over_purchase_date`. Metric line: `count_sponsorships`, `sum_price`, `sum_revenue`, `sum_profit`.

### Type 8 (SPONSORSHIPS) — performance / ROI
Replace one of the histograms with `count_sponsorships_over_performance_grade` (`histogram-category` type). Metric line emphasizes `roas`, `avg_cpv`, `sum_revenue`.

### Type 8 (SPONSORSHIPS) — assets / drafts QA
Replace the value metrics with `count_sponsorships_where_published`, `count_sponsorships_where_unpublished`, `count_sponsorships_where_assets_are_incomplete`, `count_sponsorships_where_draft_is_missing`. Drop the histograms or keep just one.

---

## Type-8 axis branching

Type 8 reports have two date axes — `send_date` (scheduled) and `purchase_date` (when the deal was won). The histograms branch based on the deal stage filter:

| `filters_json.publish_status` includes | Use axis |
|---|---|
| Pre-sale stages (Proposed=0, Pending=2, Proposal Approved=6, Matched=7, Reached Out=8) | `send_date` — pipeline view |
| Sold (3) only | `purchase_date` — won-deals view |
| Mix of pre-sale + sold | `send_date` (pipeline view dominates) |
| Performance grades (winners/losers) | `purchase_date` |

Apply the chosen axis to BOTH histograms (`count_sponsorships_over_<axis>` and `sum_price_over_<axis>`) in the same report — don't mix axes within one report.

---

## Hard rules

1. **Never cross catalogs.** Sponsorship aggregators on a type-1/2/3 report — or vice versa — will fail server-side. The catalogs are disjoint.
2. **First widget = primary aggregate** for the report's purpose. Don't bury the headline.
3. **Histograms last.** Per v1 line 693 — visual-space convention.
4. **`width: 2` for metrics-boxes, `width: 3` for histograms.** The grid is 6 columns wide; this gives a clean 3-up metric line + 2-up histogram line.
5. **`height: 1` always.** Multi-row widgets aren't part of the catalog.
6. **`index` is 1-based and sequential.** No gaps.
7. **`histogram_bucket_size` is a top-level field**, not per-widget. Set it once for the whole report.
8. **Type-8 axis consistency.** Both `_over_<axis>` histograms in the same report use the SAME axis (send_date or purchase_date) — see the branching table above.
9. **Don't invent aggregator keys.** If the user's request can't be expressed by the catalog, surface a follow-up rather than emit a non-existent aggregator.
