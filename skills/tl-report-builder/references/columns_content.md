# Columns — Content report (report_type = 1)

Reference for Phase 3 (Columns Phase). Each row in a Content report is one upload (video / article / podcast episode). Phase 3 reads this file to pick which columns appear in the saved report.

The output Phase 3 emits is a `columns` dict mapping display names → `{"display": true}` (plus optional `custom`/`formula`/`cellType` for custom columns). Names below are the **exact display names** the platform expects — case-sensitive, including spaces.

---

## Defaults — always include

- `Date`
- `Channel`
- `Title`
- `Views`

---

## Standard columns (pick 5–10 total, including the defaults above)

### Identity / context
- `Date`, `Channel`, `Title`, `Content`, `URL`, `Hashtags`, `Category`, `Country`, `Language`
- `TL Channel Summary` — useful when the user wants channel context per row

### View counts (current)
- `Views`, `Subscribers`
- `Likes`, `Comments`, `Duration`
- `Evergreen Score`

### View snapshots (early-life curve)
- `Views Curve`
- `Views at 2 days`, `Views at 7 days`, `Views at 14 days`, `Views at 30 days`
- `Views at 45 days`, `Views at 60 days`, `Views at 90 days`, `Views at 180 days`, `Views at 365 days`

### Projections
- `Video Projected Views` — projection at day 30 for this video
- `Channel Projected Views` — projection for the channel's next video

### Brands signal
- `Brands` — brands mentioned in the video
- `Sponsored Brands` — brands sponsoring this specific video

### Sponsorship-deal columns (only if a deal is attached)
- `Price`, `Cost`, `Revenue`, `CPV`, `Brand CPV`, `Publisher CPV`
- `Views Guarantee`, `Conversions`, `Advertiser`

### Other
- `Age` — days since upload
- `Deleted At`

---

## Intent-driven additions

| Intent signal | Add columns |
|---|---|
| Trend / growth analysis | `Views at 7 days`, `Views at 30 days`, `Video Projected Views`, `Evergreen Score` |
| Sponsor surfacing (which videos are sponsored) | `Brands`, `Sponsored Brands`, `Advertiser`, `Price`, `CPV` |
| Content quality / engagement | `Likes`, `Comments`, `Duration`, `Evergreen Score`, `Views at 30 days` |
| Cost / efficiency analysis | `Price`, `Cost`, `CPV`, `Brand CPV`, `Publisher CPV`, `Video Projected Views` |
| Recent vs back-catalog comparison | `Date`, `Age`, `Views`, `Views at 30 days`, `Views at 365 days` |
| Hashtag / topic discovery | `Title`, `Hashtags`, `Content`, `Category` |

---

## Custom-formula variables (`{Variable Name}`)

Identity / time: `{Date}`, `{Channel}`, `{Title}`, `{Content}`, `{Age}`, `{URL}`, `{Hashtags}`

Views: `{Views}`, `{Subscribers}`, `{Likes}`, `{Comments}`, `{Duration}`, `{Evergreen Score}`

View snapshots: `{Views at 2 days}`, `{Views at 7 days}`, `{Views at 14 days}`, `{Views at 30 days}`, `{Views at 45 days}`, `{Views at 60 days}`, `{Views at 90 days}`, `{Views at 180 days}`, `{Views at 365 days}`

Projections: `{Video Projected Views}`, `{Channel Projected Views}`

Sponsorship: `{Revenue}`, `{Price}`, `{Cost}`, `{CPV}`, `{Brand CPV}`, `{Publisher CPV}`, `{Views Guarantee}`, `{Conversions}`

### Suggested formulas

| Intent | Formula | `cellType` |
|---|---|---|
| Engagement per view | `{Likes} / {Views}` | `percent` |
| Beat-the-projection | `{Views} > {Video Projected Views} ? 'beat' : 'miss'` | `regular` |
| Per-subscriber reach | `{Views} / {Subscribers}` | `percent` |
| Comment intensity | `{Comments} / {Views}` | `percent` |
| Days since upload (alt) | `{Age}` is already days; combine with `{Views}` for `{Views} / {Age}` views-per-day | `regular` |
| Sponsorship efficiency | `{Cost} / {Views}` (current CPV) | `usd` |

Surface custom formulas in `refinement_suggestions`; the user opts in.

---

## Hard rules

1. **Date and Channel are anchors** — almost every Content report needs both.
2. **Don't dump every view-snapshot column.** Pick the 1–2 that match the date scope: short windows → `Views at 7 days` / `Views at 30 days`; longer → `Views at 90 days` / `Views at 365 days`.
3. **Sponsorship columns only if intent involves deals.** Discovery reports don't need `Price`/`CPV` — they're sparse and confuse the table.
4. **Display names match exactly.**
5. **Pick 5–10 standard columns** unless intent justifies more (flag in `_phase3_metadata.column_count`).
