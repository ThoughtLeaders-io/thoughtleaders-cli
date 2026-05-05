# Columns — Brands report (report_type = 2)

Reference for Phase 3 (Columns Phase). Each row in a Brands report is one brand, aggregated across the matching content. Phase 3 reads this file to pick which columns appear in the saved report.

The output Phase 3 emits is a `columns` dict mapping display names → `{"display": true}`. Names below are the **exact display names** the platform expects — case-sensitive, including spaces.

---

## Defaults — always include

- `Brand`
- `Mentions`
- `Avg. Views`

---

## Standard columns (pick 5–10 total, including the defaults above)

### Identity
- `Brand`, `Website`, `Description`, `Product Type`

### Reach metrics
- `Channels` — count of unique channels mentioning the brand
- `Mentions` — count of unique uploads the brand was mentioned in
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

---

## Intent-driven additions

| Intent signal | Add columns |
|---|---|
| Competitor research / "who's sponsoring X niche" | `Channels`, `Mentions`, `Last Mention`, `Avg. Views`, `Sponsor Time`, `Open Proposals Count` |
| Cost / pricing analysis | `Price Sum`, `Avg. price`, `Brand CPV`, `Publisher CPV`, `CPV`, `Revenue` |
| Recency / momentum | `Last Mention`, `Last Published Upload`, `Mentions`, `Avg. Views` |
| Quality / fit assessment | `Description`, `Product Type`, `Website`, `Avg. Evergreenness`, `Avg. Comments` |
| TL book of business | `Is Managed Services`, `Is Media Buying Network`, `Owner Advertiser Emails`, `Open Proposals Count`, `Weighted Price` |
| Engagement focus | `Avg. Likes`, `Avg. Comments`, `Avg. Evergreenness`, `Avg. Duration` |

---

## Custom-formula variables (`{Variable Name}`)

Identity: `{Brand}`

Reach: `{Mentions}`, `{Channels}`, `{Avg. Mentions}`

Views: `{Views Sum}`, `{Avg. Views}`, `{Max. Views}`, `{Min. Views}`

Engagement: `{Likes Sum}`, `{Avg. Likes}`, `{Avg. Duration}`, `{Avg. Comments}`, `{Avg. Evergreenness}`, `{Deleted Content}`

Dates: `{Last Mention}`, `{First Mention}`, `{Sponsor Time}`

Sponsorship: `{Price Sum}`, `{Avg. price}`, `{Cost Sum}`, `{Avg. cost}`, `{Brand CPV}`, `{Publisher CPV}`, `{CPV}`, `{Revenue}`, `{Conversions}`

TL pipeline: `{Open Proposals Count}`, `{Weighted Price}`

### Suggested formulas

| Intent | Formula | `cellType` |
|---|---|---|
| Mentions density | `{Mentions} / {Channels}` | `regular` |
| Estimated CPM (rough) | `{Views Sum} / 1000 * 20` | `usd` |
| Avg. revenue per mention | `{Revenue} / {Mentions}` | `usd` |
| Engagement rate | `{Likes Sum} / {Views Sum}` | `percent` |
| Brand vs publisher CPV ratio | `{Brand CPV} / {Publisher CPV}` | `regular` |

Surface custom formulas in `refinement_suggestions`; the user opts in.

---

## Hard rules

1. **`Brand` and `Mentions` are anchors** — every Brands report needs both.
2. **Don't include both `Channels` AND `Avg. Mentions` without `Mentions`** — the math gets confusing.
3. **Financial columns only when intent calls for them.** A discovery query "who's sponsoring AI tools" doesn't need `Price Sum` / `CPV` — they're often null and pollute the view.
4. **Display names match exactly** — note `Avg. price` and `Avg. cost` are lowercase `p`/`c`; `Avg. Mentions` is capitalized `M`. The platform key-matches.
5. **Pick 5–10 standard columns** unless intent justifies more (flag in `_phase3_metadata.column_count`).
