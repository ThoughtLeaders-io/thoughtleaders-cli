---
name: tl-channels
description: Channel search and lookup. Find YouTube channels by category, subscribers, language, or other criteria.
---

# /tl-channels — Channel Search

The user wants to search or look up YouTube channels.

1. Run `tl describe show channels --json` to discover filters
2. Translate the user's request into a `tl channels` command
3. Execute and present results

Examples:
- "/tl-channels cooking channels over 100k" → `tl channels list category:cooking min-subs:100000`
- "/tl-channels 12345" → `tl channels show 12345`
- "/tl-channels English gaming channels" → `tl channels list category:gaming language:en`
- "/tl-channels mobile-first channels" → `tl channels list primary-device:mobile`
- "/tl-channels channels with majority US audience" → `tl channels list min-us-share:50`
- "/tl-channels mobile tech channels with US focus" → `tl channels list category:tech primary-device:mobile min-us-share:60`
- "/tl-channels channels similar to 12345" → `tl channels similar 12345 --limit 10`
- "/tl-channels look-alikes for Economics Explained at high similarity" → `tl channels similar "Economics Explained" min-score:0.85 --limit 10`
- "/tl-channels look-alikes including non-MSN" → `tl channels similar 12345 msn:both --limit 20`
- "/tl-channels look-alikes that are non-MSN only" → `tl channels similar 12345 msn:no --limit 20`
- "/tl-channels TPP look-alikes for 12345" → `tl channels similar 12345 tpp:yes --limit 20`
- "/tl-channels all TPP channels in cooking" → `tl channels list tpp:yes category:cooking`
- "/tl-channels channels that are NOT in TPP" → `tl channels list tpp:no`
- "/tl-channels MSN gaming channels" → `tl channels list msn:yes category:gaming`
- "/tl-channels non-MSN channels with 500k+ subs" → `tl channels list msn:no min-subs:500000`

Note: `tl channels list` and `tl channels similar` both support tri-state `msn:` and `tpp:` filters (`yes` / `no` / `both`). Defaults: `msn:yes` on `similar`, `msn:both` on `list`; `tpp:both` on both. Both values are also returned as boolean fields (`msn`, `tpp`) on every channel response — list, detail, and similar. Ambiguous name arguments return a 400 with candidate IDs listed.
