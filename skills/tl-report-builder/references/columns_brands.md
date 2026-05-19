# Columns — Brands report (report_type = 2)

Phase 3 reference. Each row = one brand, aggregated across matching content. Phase 3 emits a `columns` dict: `display_name → {"display": true}` (plus optional `custom`/`formula`/`cellType`). Names are case-sensitive, spaces preserved — platform key-matches.

## Defaults — always include

- `Brand`
- `Mentions`
- `Avg. Views`

## Standard columns (pick 5–10 total, including defaults)

### Identity
- `Brand`, `Website`, `Description`, `Product Type`

### Reach metrics
- `Channels` — unique channels mentioning the brand
- `Mentions` — unique uploads the brand was mentioned in
- `Avg. Mentions` — average mentions per upload (when grouped by channel)

### Date markers
- `Last Mention`, `First Mention`
- `Sponsor Time` — span between first and last mention
- `Tracking Start` — when TL started tracking the brand

### Views aggregations
- `Views Sum`, `Avg. Views`, `Max. Views`, `Min. Views`

### Engagement aggregations
- `Likes Sum`, `Avg. Likes`
- `Avg. Comments`, `Comments Sum`
- `Avg. Duration`, `Avg. Evergreenness`
- `Deleted Content` — count of deleted/private videos that mentioned the brand

### Upload markers
- `Last Published Upload`, `First Published Upload`

### Sponsorship financials
- `Price Sum`, `Avg. price`
- `Cost Sum`, `Avg. cost`
- `Brand CPV`, `Publisher CPV`, `CPV`
- `Revenue`, `Conversions`

### TL pipeline / internal
- `Is Managed Services`, `Is Media Buying Network`
- `Owner Advertiser Emails`
- `Open Proposals Count`, `Weighted Price`

## Intent-driven additions

| Intent signal | Add columns |
|---|---|
| Competitor research / "who's sponsoring X niche" | `Channels`, `Mentions`, `Last Mention`, `Avg. Views`, `Sponsor Time`, `Open Proposals Count` |
| Cost / pricing analysis | `Price Sum`, `Avg. price`, `Brand CPV`, `Publisher CPV`, `CPV`, `Revenue` |
| Recency / momentum | `Last Mention`, `Last Published Upload`, `Mentions`, `Avg. Views` |
| Quality / fit assessment | `Description`, `Product Type`, `Website`, `Avg. Evergreenness`, `Avg. Comments` |
| TL book of business | `Is Managed Services`, `Is Media Buying Network`, `Owner Advertiser Emails`, `Open Proposals Count`, `Weighted Price` |
| Engagement focus | `Avg. Likes`, `Avg. Comments`, `Avg. Evergreenness`, `Avg. Duration` |

## Custom-formula variables

Wrap any standard column name above in `{}` (case-sensitive, spaces preserved) for custom-formula use. Platform parses `{Variable Name}` into JS at runtime.

### Suggested formulas

| Intent | Formula | `cellType` |
|---|---|---|
| Mentions density | `{Mentions} / {Channels}` | `regular` |
| Estimated CPM (rough) | `{Views Sum} / 1000 * 20` | `usd` |
| Avg. revenue per mention | `{Revenue} / {Mentions}` | `usd` |
| Engagement rate | `{Likes Sum} / {Views Sum}` | `percent` |
| Brand vs publisher CPV ratio | `{Brand CPV} / {Publisher CPV}` | `regular` |

Surface custom formulas as refinement suggestions; user opts in.

## Hard rules

1. `Brand` and `Mentions` are anchors — every Brands report needs both.
2. Don't include `Channels` + `Avg. Mentions` without `Mentions` — math gets confusing.
3. Financial columns only when intent calls for them (discovery queries don't need `Price Sum`/`CPV` — often null, pollute the view).
4. Display names match exactly — `Avg. price` and `Avg. cost` are lowercase `p`/`c`; `Avg. Mentions` is capitalized `M`.
5. Pick 5–10 standard columns unless intent justifies more (flag in `_phase3_metadata.column_count`).
