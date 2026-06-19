---
name: tl-top-partnerships
description: External brand-user performance report. Ranks a brand's sponsorships by effective CPM once the sponsored videos went live, and compares live eCPM against the sold-date projection. Use whenever a brand user asks "which of my sponsorships performed best", "top partnerships this year", "best ROI deals", "effective CPM on my deals", "which sponsorships overperformed", "/top-partnerships", or any variation of "show me my best-performing sponsorships". This is the brand-side equivalent of internal performance reporting — fire it eagerly any time a brand wants to look back at their booked deals through a performance lens, even if they don't say the words "CPM" or "eCPM".
---

# Top Partnerships (Brand-side)

Helps a brand look back at their sold sponsorships and see which ones delivered the lowest effective CPM (eCPM) once the videos went live, vs the projection at sale.

## Triggers

- `/top-partnerships` — defaults to calendar YTD
- `/top-partnerships <range>` — e.g. `/top-partnerships 2025`, `/top-partnerships "last 12 months"`, `/top-partnerships "Q1 2026"`
- Natural language: "top partnerships this year", "best sponsorships", "which deals performed best", "effective CPM on my deals", "show me my best ROI sponsorships"

## What this skill computes

For every sold sponsorship the brand has where the video has actually gone live (has a `publish_date` and a non-null live `views` count):

- **Sold-date eCPM** = `price / projected_views_at_purchase_date * 1000`
  - The projection captured on the adlink at the moment the deal was sold. This is the eCPM the brand "agreed to."
- **Live eCPM** = `price / views * 1000`
  - The actual eCPM now that the video has accumulated views.
- **View ratio** = `views / projected_views_at_purchase_date`
  - >1 means the video out-delivered its projection.
- **Delta** = `live_eCPM - sold_date_eCPM`
  - Negative delta = the deal got *cheaper* per view than promised (good for the brand). Positive delta = the deal underdelivered.

It also pulls **future bookings** — any sponsorship that is sold, or open with the brand having reviewed it (`brand_approval` pending or approved), with a send date strictly after today — and tags each deal and each channel with the earliest future send date, or "Re-book - no future spot" if none exists. This turns the report into an actionable list, not just a backward look.

## Output

A Google Sheet with two tabs, owned by the caller's Google account:

- **By Deal** — one row per sponsorship, ranked by live eCPM (best first). Columns: rank, channel, title, video_url, send_date, publish_date, price, promised_views, live_views, view_ratio, sold_date_ecpm, live_ecpm, delta_ecpm, measurable, next_booking.
- **By Channel** — one row per channel, aggregated across all that channel's deals in range. Combined live eCPM is `sum(price) / sum(live_views) * 1000` (volume-weighted, not an average of CPMs). Sorted by combined live eCPM. Columns: channel, deals, measurable_deals, total_price_usd, total_promised_views, total_live_views, view_ratio, sold_date_ecpm, live_ecpm, delta_ecpm, next_booking.

In chat: a short summary + top-10 channels table + the sheet URL.

## Workflow

### Step 1 — Resolve the brand

Run `tl whoami --json` and read the `brands` array.

- One brand → use it silently.
- Zero brands → tell the user this skill is for brand-user profiles and stop.
- Multiple brands → ask which one. Don't guess.

### Step 2 — Resolve the time range

Default = calendar YTD (Jan 1 of the current year through today).

Accept these forms in the user's input:

- `2025` or `"2024"` → that full calendar year
- `"last 12 months"` → trailing 12 months ending today
- `"Q1 2026"`, `"Q4 2025"` → that quarter
- `"YTD"` → explicit current YTD
- Anything else → ask the user to clarify, don't silently pick

Convert to a `send-date-start` / `send-date-end` pair (YYYY-MM-DD strings). Use `send_date` as the time anchor because that is when the sponsorship actually ran for the brand — purchase_date can be months earlier.

### Step 3 — Run the script

```bash
python3 <SKILL_DIR>/scripts/top_partnerships.py \
  --brand "<BRAND_NAME>" \
  --send-date-start <YYYY-MM-DD> \
  --send-date-end <YYYY-MM-DD>
```

`<SKILL_DIR>` resolves to this skill's directory at invocation time (same convention as `tl-views-guarantee`, `tl-keyword-research`).

The script does everything: pulls sold deals in range (paginated), pulls all future bookings, computes per-deal and per-channel metrics, creates a Google Sheet with two tabs, shares it back to the caller, and prints a markdown summary plus the sheet URL.

It uses `tl` for data and `gws` for sheet creation. Both must be on PATH and authed.

### Step 4 — Present the result

Take the script's stdout as-is. It already contains:

1. **Summary line** — total sold deals, measurable count, median live eCPM, count overperforming.
2. **Top 10 channels by combined live eCPM** — markdown table with the Next booking column bolded when it says "Re-book."
3. **Sheet URL** — point the user at the two tabs.

If more than half the top-10 channels show "Re-book", call that out in one sentence as the headline action item. If most of the top channels already have follow-ups booked, congratulate briefly and stop.

Keep the writeup tight. No em dashes, no "just wanted to", no hedging. The data does the talking.

## Brand-user mode notes

- This skill assumes a brand-user `tl` auth. It uses only public CLI commands (`tl whoami`, `tl sponsorships list`) — no `tl db pg` and no Elasticsearch.
- The `tl sponsorships list` endpoint already filters to deals the calling profile is allowed to see, so passing `brand:"<name>"` is a belt-and-braces filter rather than a privacy boundary.
- View counts come from TL's own tracking on the `views` field returned by the CLI. They're the same numbers the brand sees in the TL dashboard, so the eCPMs are reconcilable with what they see in-app.
- Don't include creators' contact emails, internal notes, or owner_* fields in the brand-facing output. The script already drops them from the CSV.

## Edge cases worth mentioning to the user (only if they apply)

- A deal that ran very recently (last 14-28 days) may show a misleadingly high Live eCPM because views are still accumulating. Mention this only if more than half the top-10 deals have a send date inside the last 28 days.
- If the brand has zero measurable deals in the range, say so plainly and suggest broadening the range (e.g., last 12 months).
