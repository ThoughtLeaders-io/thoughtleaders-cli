# Widgets

Phase 4 reference. Widgets are the charts and metric boxes above the data table on a saved report.

> **Schema source of truth**: [`intelligence_widget_schema.json`](intelligence_widget_schema.json) (types 1/2/3), [`sponsorship_widget_schema.json`](sponsorship_widget_schema.json) (type 8). Both define default sets, intent overrides, axis branching, and per-type aggregator catalogs. `widget_builder.md` consumes the schema matching the report type.

Phase 4 emits a `widgets` array of `{aggregator, type, index, width, height}` objects + a top-level `histogram_bucket_size`. **Every widget must add value to the user's prompt** — don't pad to a higher count.

## Widget JSON shape

```json
{ "aggregator": "<from catalog>", "type": "metrics-box" | "histogram" | "histogram-category",
  "index": <1-based, sequential>, "width": 2 | 3, "height": 1 }
```

Defaults: metrics-boxes → `width: 2`; histograms → `width: 3`. `height` is always `1`. Grid is 6 columns wide.

`histogram_bucket_size` (top-level, applies to all histograms):

| Date range | `histogram_bucket_size` |
|---|---|
| < 90 days | `"week"` |
| 90 days – 2 years | `"month"` (default) |
| Multi-year | `"year"` |

## Selection guidelines

1. 4–6 widgets per report (less = empty; more = clutter)
2. Mix metrics-boxes and histograms (good pattern: 3–4 metrics + 1–2 histograms)
3. First widget = primary aggregate for the report's purpose
4. Histograms last (higher `index`)
5. Never cross catalogs (intelligence aggregators on type-1/2/3, sponsorship aggregators on type-8 — disjoint)
6. `histogram_bucket_size` matches the date scope

---

## Aggregator catalog — Intelligence reports (types 1, 2, 3)

### Views on videos
- `views_sum_metric` (metrics-box) — total views
- `views_sum_histogram` (histogram) — views over time by publish date
- `views_avg_metric` (metrics-box) — avg views per video
- `views_avg_histogram` (histogram) — avg views over time
- `views_median_metric` (metrics-box) — median views per video
- `views_median_histogram` (histogram) — median views over time
- `views_last_value_metric` (metrics-box) — views on most recent video

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
- `channel_reach_last_28_days` (metrics-box) — subscriber change last 28 days

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
- `count_sponsorships_where_winner` (metrics-box) — winning count
- `count_sponsorships_where_loser` (metrics-box) — losing count
- `sum_price_where_winner` (metrics-box) — total price of winners
- `sum_price_over_performance_grade` (histogram-category) — price by grade

### Assets & drafts
- `count_sponsorships_where_unpublished` (metrics-box) — unpublished count
- `count_sponsorships_where_published` (metrics-box) — published count
- `count_sponsorships_where_assets_are_incomplete` (metrics-box) — incomplete assets count
- `count_sponsorships_where_draft_is_missing` (metrics-box) — missing drafts count

---

## Default widget sets per ReportType (5 widgets each, index 1-5)

Per-widget `type`/`width`/`height` follow the global defaults above (metrics-box width 2, histogram width 3, height 1). Listed as `index. aggregator (type)`:

**Type 1 (CONTENT)** — 1. `total` (M), 2. `views_sum_metric` (M), 3. `views_avg_metric` (M), 4. `uploads_histogram` (H), 5. `views_sum_histogram` (H)

**Type 2 (BRANDS)** — 1. `brands_count_metric` (M), 2. `total` (M), 3. `views_sum_metric` (M), 4. `brands_count_histogram` (H), 5. `views_sum_histogram` (H)

**Type 3 (CHANNELS)** — 1. `channels_count_metric` (M), 2. `channel_reach_at_scrape_metric` (M), 3. `views_avg_metric` (M), 4. `channel_reach_at_scrape_histogram` (H), 5. `uploads_histogram` (H)

**Type 8 (SPONSORSHIPS)** — 1. `count_sponsorships` (M), 2. `sum_price` (M), 3. `count_channels` (M), 4. `count_sponsorships_over_<axis>` (H), 5. `sum_price_over_<axis>` (H). `<axis>` per branching table below.

---

## Intent-driven patterns

| Report type | Intent | Adjustment |
|---|---|---|
| Type 3 | outreach / product placements | Add `sponsored_brands_count_metric`; consider swapping a histogram for `channel_reach_at_scrape_difference_histogram` |
| Type 1 | engagement focus | Replace `views_avg_metric` with `likes_sum_metric` or `comments_avg_metric`; consider `views_30_avg_histogram` |
| Type 1 | sponsor-surfacing | Add `sponsored_brands_count_metric`; keep `total` + `views_sum_metric` for context |
| Type 2 | recency / momentum | Add `publication_date_max_metric` (surfaces "last mention") |
| Type 8 | pipeline / forecasting | Axis: `send_date`. Metrics: `count_sponsorships`, `sum_price`, `sum_impression` |
| Type 8 | won deals review | Axis: `purchase_date`. Metrics: `count_sponsorships`, `sum_price`, `sum_revenue`, `sum_profit` |
| Type 8 | performance / ROI | Replace one histogram with `count_sponsorships_over_performance_grade` (`histogram-category`). Metrics emphasize `roas`, `avg_cpv`, `sum_revenue` |
| Type 8 | assets / drafts QA | Replace value metrics with `count_sponsorships_where_published`, `_where_unpublished`, `_where_assets_are_incomplete`, `_where_draft_is_missing`. Drop or keep one histogram |

## Type-8 axis branching

Two date axes — `send_date` (scheduled) and `purchase_date` (won). Histograms branch on deal stage:

| `filters_json.publish_status` includes | Use axis |
|---|---|
| Pre-sale (0, 2, 6, 7, 8) | `send_date` (pipeline view) |
| Sold (3) only | `purchase_date` (won-deals view) |
| Mix of pre-sale + sold | `send_date` (pipeline view dominates) |
| Performance grades (winners/losers) | `purchase_date` |

Both `_over_<axis>` histograms in the same report use the SAME axis — don't mix within one report.

## Hard rules

1. Never cross catalogs (intelligence ↔ sponsorship aggregators are disjoint; server fails on the wrong catalog).
2. First widget = primary aggregate; don't bury the headline.
3. Histograms last.
4. `width: 2` for metrics-boxes; `width: 3` for histograms. Grid is 6 columns.
5. `height: 1` always.
6. `index` 1-based and sequential, no gaps.
7. `histogram_bucket_size` is top-level (one per report), not per-widget.
8. Type-8 axis consistency — both `_over_<axis>` histograms in one report share the axis.
9. Don't invent aggregator keys — surface a follow-up if the catalog can't express the user's request.
