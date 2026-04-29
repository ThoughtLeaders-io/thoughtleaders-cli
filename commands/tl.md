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
- "/tl cooking channels over 100k subs" → `tl db pg "SELECT id, channel_name, total_views FROM thoughtleaders_channel WHERE content_category = <COOKING_CODE> AND total_views >= 100000 ORDER BY total_views DESC LIMIT 50 OFFSET 0"`
- "/tl mobile-first US cooking channels" → `tl db pg "SELECT id, channel_name, demographic_usa_share FROM thoughtleaders_channel WHERE content_category = <COOKING_CODE> AND demographic_device_primary = 'mobile' AND demographic_usa_share >= 50 ORDER BY total_views DESC LIMIT 50 OFFSET 0"`
- "/tl Nike's sponsorship activity" → `tl brands show Nike`
- "/tl run my Q1 report" → `tl reports --json` then `tl reports run <id>`
- "/tl check my balance" → `tl balance`
- "/tl show sponsorship 12345" → `tl sponsorships show 12345`

If the request is complex and requires multiple queries, delegate to the tl-analyst agent.
