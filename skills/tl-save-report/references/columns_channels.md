# Columns — Channels report (report_type = 3)

Column catalogue for Channels reports. Each row of the saved report = one YouTube channel. The emitted `columns` dict has shape `display_name → {"display": true}` (plus optional `custom` / `formula` / `cellType`). Display names are case-sensitive and preserve spaces — the platform key-matches exactly.

## Defaults — always include

User's quick-evaluation surface. Always emit unless user explicitly says otherwise:

- `Channel`
- `TL Channel Summary` — required per platform UX
- `Subscribers`

## Standard columns (pick 5–10 total, including defaults)

### Identity / context
- `Channel`, `Channel URL`, `Country`, `Language`, `Category`
- `Channel Description`, `Topic Descriptions`, `TL Channel Summary`
- `Brand Safety`, `Face On Screen`

### Volume / reach
- `Content` — count of matching uploads (when keyword/brand filters applied, this counts hits, not all uploads)
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
- `TL Sponsorship Calc. Price` — unreliable; only include if user asked for an estimate
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

## Intent-driven additions

Layer these on top of defaults when the user signal points at intent (outreach, audience-quality focus, growth, demographic targeting, pricing, brand-safety, etc.):

| Intent signal | Add columns |
|---|---|
| Outreach / product placements | `Sponsorship Score`, `Sponsorships Sold`, `Brands Sold`, `Last Sold Sponsorship`, `Open Proposals Count`, `Outreach Email`, `Preferred Email`, `USA Share`, `Demographics - Age Median` |
| Audience-quality focus | `Engagement`, `Median Evergreenness`, `Trend`, `Volatility`, `Avg. Comments` |
| Growth / momentum | `Last 28 Days Views %`, `Last 28 Days Subscribers %`, `Trend`, `Posts Per 90 Days` |
| Demographic targeting | `Male Share`, `USA Share`, `Demographics - Age Median` |
| Pricing / efficiency analysis | `Latest AdSpot Price`, `CPV Today`, `Last Known Cost`, `Projected Views` |
| Brand-safety vetting | `Brand Safety`, `Topic Descriptions`, `Face On Screen`, `TL Channel Summary` |
| Narrow-result reports | `Engagement`, `Sponsorship Score`, `TL Channel Summary` (help the user evaluate the small set) |

## Custom-formula variables

Wrap any standard column name above in `{}` (case-sensitive, spaces preserved). Platform parses `{Variable Name}` into JS at runtime.

### Suggested formulas (propose at least one in `refinement_suggestions`)

| Intent | Formula | `cellType` |
|---|---|---|
| Engagement spotting | `{Avg. Views} / {Subscribers}` | `percent` |
| Outreach efficiency | `{Cost} / {Projected Views}` | `usd` |
| Renewal-rate proxy | `{Sponsorships Sold} ? {Brands Sold} / {Sponsorships Sold} : 'N/A'` | `regular` |
| Audience-share to target demo | adapt `{USA Share}` or `{Male Share}` against the user's stated target | `percent` |

Don't silently activate a custom column — surface as a refinement suggestion; user opts in.

## Hard rules

1. `TL Channel Summary` is required. Always present in Channels reports.
2. `Content` is the matching-uploads count when filters are applied — don't create a custom column to replicate it.
3. Pick 5–10 standard columns; the platform allows up to 13 if intent calls for it (the dashboard's column rail starts to feel crowded past 10).
4. Display names match exactly — no `Subscribers ` (trailing space), `subscribers` (lowercase), or made-up names like `Sub Count`.
5. `Latest AdSpot Price` over `TL Sponsorship Calc. Price` — calc price is unreliable.
6. Exclude pricing columns unless intent is sponsorship/outreach/cost (noise on discovery reports).
