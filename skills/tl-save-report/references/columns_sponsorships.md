# Columns — Sponsorships report (report_type = 8)

Column catalogue for Sponsorships reports. Each row of the saved report = one sponsorship deal (AdLink). The emitted `columns` dict has shape `display_name → {"display": true}` (plus optional `custom` / `formula` / `cellType`). Display names are case-sensitive and preserve spaces — the platform key-matches exactly.

> Type 8 is **completely different** from types 1/2/3 — different rows, different catalog, different defaults. Don't reuse type-3 defaults like `TL Channel Summary` as primary columns; they're available but secondary.

## Defaults — always include

- `Channel`
- `Advertiser`
- `Status`
- `Price`
- `Scheduled Date`

## Standard columns (pick 5–10 total, including defaults)

### Identity / context
- `Channel`, `Advertiser`, `Sponsorship`, `Integration Type`
- `Status` — deal stage
- `URL`, `Sponsorship Example`, `Sponsored Link Status`
- `Talking Points`, `Adops Notes`, `Publisher Notes`
- `Match Grade` — matching engine score
- `Rejection Reason`

### Dates
- `Scheduled Date` — planned scheduled date
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

## Custom-formula variables

Wrap any standard column name above in `{}` (case-sensitive, spaces preserved). Platform parses `{Variable Name}` into JS at runtime.

### Suggested formulas

| Intent | Formula | `cellType` |
|---|---|---|
| Margin proxy (TL profit signal) | `{Price} - {Cost}` | `usd` |
| Brand-vs-Publisher CPV ratio | `{Expected CPV} ? {Current CPV} / {Expected CPV} : 'N/A'` | `regular` |
| ROAS check | `{Price} ? {Revenue} / {Price} : 'N/A'` | `regular` |
| Pacing % to guarantee | `{Views Guaranteed} ? {Current Views} / {Views Guaranteed} : 'N/A'` | `percent` |
| Time-to-publish lag | `{Publish Date} && {Purchase Date} ? ({Publish Date} - {Purchase Date}) : 'N/A'` | `regular` |
| Per-channel deal weight | `{Weighted price} / {Publish Count}` | `usd` |

Surface custom formulas as refinement suggestions; user opts in.

## Hard rules

1. `Channel`, `Advertiser`, `Status` are anchors. Every Sponsorships report needs all three.
2. Type 8 has its own catalog. Don't borrow type-3 defaults wholesale. `TL Channel Summary` / `Subscribers` are available but secondary; lead with deal-stage + financials.
3. Financial columns belong here. Unlike types 1/2/3 (intent-gated), type 8 IS about pricing — `Price` and `Status` are baseline.
4. Date columns: pick the one matching intent. Pipeline → `Scheduled Date`; won-deals → `Purchase Date`; activity feed → `Last Updated`. Don't include all.
5. `Match Grade` is the matching-engine score — useful for deal-quality fit questions, otherwise omit.
6. Use TL-glossary terms in formulas. TL says **Net revenue** / **TL profit**, not "margin." For profit signal, prefer `{Price} - {Cost}` rather than naming it "margin."
7. Display names match exactly — note `Weighted price` (lowercase `p`), `Gender (male %)` (parens included), `Demographics - Age Median` (spaces around `-`).
8. Pick 5–10 standard columns unless intent justifies more (the platform allows up to 13).
