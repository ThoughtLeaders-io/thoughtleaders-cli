---
name: tl-brands
description: Brand intelligence lookup. Search brands or research a brand's sponsorship activity and channel mentions.
---

# /tl-brands — Brand Intelligence

The user wants to search brands or research a brand's sponsorship activity. Requires Intelligence plan.

1. Run `tl describe show brands --json` to discover filters
2. Translate the user's request into a `tl brands` command
3. Execute and present results

## Search / Browse brands
- "/tl-brands list" → `tl brands list`
- "/tl-brands list tech brands" → `tl brands list category:tech`
- "/tl-brands list name Hello Fresh" → `tl brands list name:"Hello Fresh"`

## Research a specific brand
- "/tl-brands Nike" → `tl brands show Nike`
- "/tl-brands Nike on channel 12345" → `tl brands show Nike --channel 12345`
