# Columns — Sponsorships report (report_type = 8)

Reference for Phase 3 (Columns Phase). Each row in a Sponsorships report is one sponsorship deal (an AdLink). Phase 3 reads this file to pick which columns appear in the saved report.

The output Phase 3 emits is a `columns` dict mapping display names → `{"display": true}`. Names below are the **exact display names** the platform expects — case-sensitive, including spaces.

> Type 8 is **completely different** from types 1/2/3 — different rows, different column catalog, different default set. Don't reuse type-3 defaults like `TL Channel Summary` or `Subscribers` as primary columns; they're available but secondary here.

---

## Defaults — always include

- `Channel`
- `Advertiser`
- `Status`
- `Price`
- `Scheduled Date`

---

## Standard columns (pick 5–10 total, including the defaults above)

### Identity / context
- `Channel`, `Advertiser`, `Sponsorship`, `Integration Type`
- `Status` — deal stage
- `URL`, `Sponsorship Example`, `Sponsored Link Status`
- `Talking Points`, `Adops Notes`, `Publisher Notes`
- `Match Grade` — matching engine score
- `Rejection Reason`

### Dates
- `Scheduled Date` — planned send date
- `Publish Date` — actual publish
- `Purchase Date` — when the deal was won
- `Created`, `Last Updated`
- `Outreach Date`, `Proposal Presented Date`, `Rejected Date`

### Financial
- `Price`, `Cost`, `Weighted price`
- `Revenue`, `Conversions`, `Conversion Rate`
- `Expected CPV`, `Expected CPM`, `Current CPV`
- `CPA`, `ROAS`

### Views
- `Current Views`, `Projected Views`
- `Views Guaranteed`, `Views Guarantee Days`, `Views Guarantee Date`
- `Projected Views at Publish Date`
- `Publish Count`

### Channel-info (secondary on type 8)
- `TL Channel Summary`, `Topic Descriptions`, `Brand Safety`
- `Subscribers`, `Sponsorship Score`
- `Total Views`, `Engagement`, `Volatility`
- `Last Published`, `Country`, `Duration`
- `TL Sponsorship Calc. Price`, `Channel URL`

### Demographics
- `Gender (male %)`, `USA Share`, `Demographics - Age Median`

### People / ownership
- `Owner Advertiser`, `Owner Publisher`, `Owner Sales`
- `Publisher Email`, `Confirmed Email`

---

## Intent-driven additions

| Intent signal | Add columns |
|---|---|
| Pipeline / forecasting | `Status`, `Weighted price`, `Scheduled Date`, `Expected CPV`, `Projected Views`, `Owner Sales` |
| Sold / won deals review | `Status`, `Price`, `Cost`, `Revenue`, `Purchase Date`, `Publish Date`, `Conversions`, `Owner Sales` |
| Pacing / efficiency | `Expected CPV`, `Current CPV`, `Views Guaranteed`, `Views Guarantee Days`, `Projected Views`, `Current Views` |
| Performance / ROI | `Revenue`, `Conversions`, `Conversion Rate`, `CPA`, `ROAS`, `Current Views` |
| Account-manager view | `Owner Sales`, `Owner Advertiser`, `Owner Publisher`, `Status`, `Last Updated` |
| Quality / channel-fit review | `TL Channel Summary`, `Sponsorship Score`, `Brand Safety`, `Match Grade`, `Subscribers` |
| Outreach pipeline | `Outreach Date`, `Proposal Presented Date`, `Status`, `Confirmed Email`, `Publisher Email` |

---

## Custom-formula variables (`{Variable Name}`)

Identity: `{Channel}`, `{Advertiser}`

Financial: `{Price}`, `{Cost}`, `{Weighted price}`, `{Revenue}`, `{Conversions}`, `{Conversion Rate}`, `{CPA}`, `{ROAS}`, `{Expected CPV}`, `{Expected CPM}`, `{Current CPV}`

Views: `{Current Views}`, `{Projected Views}`, `{Projected Views at Publish Date}`, `{Views Guaranteed}`, `{Views Guarantee Days}`, `{Publish Count}`

Dates: `{Scheduled Date}`, `{Publish Date}`, `{Purchase Date}`, `{Created}`, `{Last Updated}`

Channel info: `{Subscribers}`, `{Sponsorship Score}`, `{Engagement}`, `{Volatility}`, `{Total Views}`, `{Match Grade}`

### Suggested formulas

| Intent | Formula | `cellType` |
|---|---|---|
| Margin proxy (TL profit signal) | `{Price} - {Cost}` | `usd` |
| Brand-vs-Publisher CPV ratio | `{Expected CPV} ? {Current CPV} / {Expected CPV} : 'N/A'` | `regular` |
| ROAS check | `{Price} ? {Revenue} / {Price} : 'N/A'` | `regular` |
| Pacing % to guarantee | `{Views Guaranteed} ? {Current Views} / {Views Guaranteed} : 'N/A'` | `percent` |
| Time-to-publish lag | `{Publish Date} && {Purchase Date} ? ({Publish Date} - {Purchase Date}) : 'N/A'` | `regular` |
| Per-channel deal weight | `{Weighted price} / {Publish Count}` | `usd` |

Surface custom formulas in `refinement_suggestions`; the user opts in.

---

## Hard rules

1. **`Channel`, `Advertiser`, `Status` are anchors.** Every Sponsorships report needs all three — they're how the user identifies a row.
2. **Type 8 has its own column catalog.** Don't borrow type-3 defaults wholesale. `TL Channel Summary` and `Subscribers` are available but secondary; lead with deal-stage + financials.
3. **Financial columns belong here.** Unlike types 1/2/3 where pricing is intent-gated, type 8 *is* about pricing — `Price` and `Status` are baseline.
4. **Date columns: pick the one that matches intent.** Pipeline view → `Scheduled Date`; won-deals review → `Purchase Date`; activity feed → `Last Updated`. Including all of them at once clutters the table.
5. **`Match Grade`** is the matching-engine score for the deal — useful when the user asks about deal-quality fit, otherwise omit.
6. **Use TL-glossary terms in formulas.** TL says **Net revenue** / **TL profit**, not "margin." For a profit signal, prefer `{Price} - {Cost}` rather than calling it "margin" in the column name.
7. **Display names match exactly** — note `Weighted price` (lowercase `p`), `Gender (male %)` (parens included), `Demographics - Age Median` (spaces around `-`).
8. **Pick 5–10 standard columns** unless intent justifies more (flag in `_phase3_metadata.column_count`).
