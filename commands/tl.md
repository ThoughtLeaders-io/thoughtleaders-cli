---
name: tl
description: Smart router for ThoughtLeaders data queries. Translates your request into the right tl CLI command(s).
---

# /tl — ThoughtLeaders Query Router

The user wants to query ThoughtLeaders data. Translate their request into the right `tl` CLI command.

## Steps

1. Identify which resource(s) the request is about (sponsorships, deals, channels, brands, uploads, snapshots, reports)
2. Discover the appropriate database structure, with `tl schema pg` and other commands, and formulate a raw database query solution first. Only use other commands like `tl sponsorships` if the user query is simple enough for it (run `tl describe show sponsorships` to see what it can do).
3. Translate the user's natural language into a `tl` command
4. Execute the command
5. Present results clearly

## Examples

- "/tl sold sponsorships for Nike in Q1" → `tl sponsorships list status:sold brand:"Nike" purchase-date-start:2026-01-01 purchase-date-end:2026-03-31`
- "/tl cooking channels over 100k subs" → `tl recommender top-channels "cooking" --limit 50` (then post-filter by `subscribers >= 100000` on the resulting IDs)
- "/tl mobile-first US cooking channels" → `tl recommender top-channels "cooking" --limit 100` (then narrow by `demographic_device_primary = 'mobile'` / `demographic_usa_share >= 50` with raw SQL on the resulting IDs)
- "/tl Nike's sponsorship activity" → `tl brands show Nike`
- "/tl run my Q1 report" → `tl reports --json` then `tl reports run <id>`
- "/tl check my balance" → `tl balance`
- "/tl show sponsorship 12345" → `tl sponsorships show 12345`

If the request is complex and requires multiple queries, delegate to the tl-analyst agent.
