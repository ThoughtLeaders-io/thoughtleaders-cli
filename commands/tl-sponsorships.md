---
name: tl-sponsorships
description: Quick sponsorship lookup. Query, filter, or show details for sponsorships.
---

# /tl-sponsorships — Sponsorship Lookup

The user wants to query sponsorships.

For **trivially simple lookups** (single ID, one or two filters the structured vocabulary already supports), use `tl sponsorships`:
1. Run `tl describe show sponsorships --json` to discover filters
2. Translate the user's request into a `tl sponsorships` command
3. Execute and present results

For **anything non-trivial** — aggregations (totals, group-bys, percentiles), joins (sponsorship + brand + channel + owner), multi-condition filtering the structured filters can't express, or fields the structured commands don't expose (raw `publish_status`, `weighted_price`, `tx_data`, etc.) — drop down to `tl db pg` against `thoughtleaders_adlink`. Run `tl schema pg` first to see the live column list.

If no specific request is given, run `tl sponsorships list --limit 10` to show recent sponsorships.

Examples (trivial — structured):
- "/tl-sponsorships pending with send dates in April" → `tl sponsorships list status:pending send-date:2026-04`
- "/tl-sponsorships Nike" → `tl sponsorships list brand:"Nike"`
- "/tl-sponsorships sold deals on mobile-first channels" → `tl sponsorships list status:sold primary-device:mobile`
- "/tl-sponsorships deals on channels with majority US audience" → `tl sponsorships list min-us-share:50`
- "/tl-sponsorships 12345" → `tl sponsorships show 12345`

Examples (non-trivial — raw `tl db pg`):
- "/tl-sponsorships total weighted pipeline by sales rep" → `tl db pg "SELECT owner_sales_id, SUM(weighted_price) AS pipeline FROM thoughtleaders_adlink WHERE publish_status IN (0,2,6,7,8) GROUP BY owner_sales_id ORDER BY pipeline DESC LIMIT 100 OFFSET 0"`
- "/tl-sponsorships sold deals this month with brand and channel name" → join `thoughtleaders_adlink` ↔ `adspot` ↔ `channel` ↔ `profile` ↔ `profile_brands` ↔ `brand` (see `references/postgres-schema.md`).

`tl sponsorships show <id> --json` returns extended detail fields beyond the list view, including: `impressions_guarantee`, `integration`, `publish_count`, `common_name`, `outreach_email`, nested `publisher` (first_name/last_name/email), nested `brand_contact` (first_name/last_name/email), and `brand.organization_name`.
