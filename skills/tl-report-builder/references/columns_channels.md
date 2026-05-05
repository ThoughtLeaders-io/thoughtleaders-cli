# Columns — Channels report (report_type = 3)

Reference for Phase 3 (Columns Phase). Each row in a Channels report is one YouTube channel. Phase 3 reads this file to pick which columns appear in the saved report.

The output Phase 3 emits is a `columns` dict mapping display names → `{"display": true}` (plus optional `custom`/`formula`/`cellType` for custom columns). Names in this file are the **exact display names** the platform expects — case-sensitive, including spaces.

---

## Defaults — always include

These three are the user's quick-evaluation surface. Always emit them unless the user explicitly says otherwise:

- `Channel`
- `TL Channel Summary` — required per platform UX convention
- `Subscribers`

---

## Standard columns (pick 5–10 total, including the defaults above)

### Identity / context
- `Channel`, `Channel URL`, `Country`, `Language`, `Category`
- `Channel Description`, `Topic Descriptions`, `TL Channel Summary`
- `Brand Safety`, `Face On Screen`

### Volume / reach
- `Content` — count of matching uploads (when keyword/brand filters are applied, this counts hits, not all uploads)
- `Subscribers`
- `Total Views`, `Avg. Views`, `Max. Views`, `Min. Views`
- `Channel Total Views`, `Views Standard Deviation`
- `Projected Views`

### Recent performance (last 28 days)
- `Last 28 Days Views`, `Last 28 Days Views %`
- `Back Catalog Views`
- `Last 28 Days Subscribers`, `Last 28 Days Subscribers %`

### Engagement / quality
- `Likes`, `Avg. Likes`, `Avg. Comments`
- `Avg. Duration`
- `Median Evergreenness`, `Avg. Evergreenness`
- `Engagement`
- `Trend`, `Trend Shorts`, `Volatility`, `Volatility Shorts`

### Activity cadence
- `Last Published`, `First Published`
- `Posts Per 90 Days`, `Posts Per 90 Days Shorts`
- `Frequency`, `Deleted Content`

### Pricing
- `Latest AdSpot Price` — preferred pricing column
- `TL Sponsorship Calc. Price` — unreliable; only include if the user asked for an estimate
- `Last Known Cost`, `CPV Today`
- `Price`, `Cost`, `Revenue`, `Conversions`

### Demographics
- `Male Share`, `USA Share`
- `Demographics - Age Median`

### Sponsorship history (TL pipeline)
- `Sponsorships Sold`, `Sponsorships Published`
- `Brands Sold`, `Last Sold Sponsorship`
- `Open Proposals Count`, `Weighted Price Sum`
- `Sponsorship Score`

### Outreach
- `Outreach Email`, `Preferred Email`, `Confirmed Email`

---

## Intent-driven additions

When Phase 1 or the user signal points at a specific intent, layer these on top of the defaults:

| Intent signal | Add columns |
|---|---|
| Outreach / product placements | `Sponsorship Score`, `Sponsorships Sold`, `Brands Sold`, `Last Sold Sponsorship`, `Open Proposals Count`, `Outreach Email`, `Preferred Email`, `USA Share`, `Demographics - Age Median` |
| Audience-quality focus | `Engagement`, `Median Evergreenness`, `Trend`, `Volatility`, `Avg. Comments` |
| Growth / momentum focus | `Last 28 Days Views %`, `Last 28 Days Subscribers %`, `Trend`, `Posts Per 90 Days` |
| Demographic targeting | `Male Share`, `USA Share`, `Demographics - Age Median` |
| Pricing / efficiency analysis | `Latest AdSpot Price`, `CPV Today`, `Last Known Cost`, `Projected Views` |
| Brand-safety vetting | `Brand Safety`, `Topic Descriptions`, `Face On Screen`, `TL Channel Summary` |
| Narrow-result reports (small intersection) | `Engagement`, `Sponsorship Score`, `TL Channel Summary` — help the user evaluate the small set |

---

## Custom-formula variables (`{Variable Name}`)

Variables are case-sensitive and include spaces. Wrap in `{}` inside the formula string. The platform parses them into JS at runtime.

Identity: `{Channel}`, `{Country}`, `{Language}`, `{Category}`

Volume: `{Content}`, `{Subscribers}`, `{Total Views}`, `{Avg. Views}`, `{Max. Views}`, `{Min. Views}`, `{Projected Views}`, `{Channel Total Views}`, `{Views Standard Deviation}`

Growth (28d): `{Last 28 Days Views}`, `{Last 28 Days Views %}`, `{Back Catalog Views}`, `{Last 28 Days Subscribers}`, `{Last 28 Days Subscribers %}`

Engagement: `{Likes}`, `{Avg. Likes}`, `{Avg. Comments}`, `{Engagement}`, `{Median Evergreenness}`, `{Avg. Evergreenness}`, `{Avg. Duration}`

Trend: `{Trend}`, `{Trend Shorts}`, `{Volatility}`, `{Volatility Shorts}`

Activity: `{Last Published}`, `{First Published}`, `{Posts Per 90 Days}`, `{Posts Per 90 Days Shorts}`, `{Frequency}`

Pricing: `{Latest AdSpot Price}`, `{TL Sponsorship Calc. Price}`, `{Last Known Cost}`, `{CPV Today}`, `{Price}`, `{Cost}`, `{Revenue}`, `{Conversions}`

Demographics: `{Male Share}`, `{USA Share}`

Sponsorship history: `{Sponsorship Score}`, `{Sponsorships Sold}`, `{Sponsorships Published}`, `{Brands Sold}`

Brands: `{Brands}`, `{Sponsors}`

### Suggested formulas (Phase 3 should propose at least one in `refinement_suggestions`)

| Intent | Formula | `cellType` |
|---|---|---|
| Engagement spotting | `{Avg. Views} / {Subscribers}` | `percent` |
| Outreach efficiency | `{Cost} / {Projected Views}` | `usd` |
| Renewal-rate proxy | `{Sponsorships Sold} ? {Brands Sold} / {Sponsorships Sold} : 'N/A'` | `regular` |
| Audience-share to target demo | adapt `{USA Share}` or `{Male Share}` against the user's stated target | `percent` |

Don't silently activate a custom column. Surface it as a refinement suggestion; the user opts in.

---

## Hard rules

1. **`TL Channel Summary` is required.** Always present in Channels reports.
2. **`Content` is the matching-uploads count when filters are applied.** Don't create a custom column to replicate it — use the standard `Content` column.
3. **Pick 5–10 standard columns** (intent-heavy reports may go up to 13; flag the count in `_phase3_metadata.column_count` if you exceed 10).
4. **Display names match exactly.** No typos like `Subscribers ` (trailing space), `subscribers` (lowercase), or made-up names like `Sub Count`. The platform key-matches.
5. **`Latest AdSpot Price` over `TL Sponsorship Calc. Price`** — the calc price is unreliable.
6. **Exclude pricing columns** unless the user's intent is sponsorship/outreach/cost. They're noise on a discovery report.
