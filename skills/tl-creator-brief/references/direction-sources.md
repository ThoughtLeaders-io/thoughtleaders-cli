# Direction sources (Lane A)

The user picks what drives the brief's direction in Step 1. The brand's own
campaign brief is one option, never the default. Run only what was picked.

| Source | What Lane A does |
|---|---|
| Past reads (default) | Sponsored mentions across the brand's sponsored videos, keyed on the Postgres brand `id` from Step 1, never a name |
| Brand-nominated favourites | Only the named videos, canonical regardless of age |
| Fresh talking points | Use what the brand submitted, ignore past reads except to flag a direct contradiction |
| Competitor or guide-brand reads | Resolve those brands to IDs the same way; label clearly as another brand's material |
| Positive-comment reads | `comment_scraper.py` over videos the brand appeared in, ranked by audience response to the ad segment; strip bots with `youtube-comment-classifier` first or the ranking measures spam |
| Campaign brief | Use it, and report where the evidence disagrees with it |

## Weighting past reads

Deterministic, not a judgment call:

- Last 12 months is canonical.
- Fewer than 3 reads in that window: widen to 24 months.
- Anything older is contrast only, and must be labelled historical.

Use `fetch_context.py --since` for the window rather than filtering afterwards.

## Output of the lane

The read skeleton (hook → problem → product → proof → CTA), recurring claims,
and what every read includes versus what varies.

## Two caveats, whichever source

- **Affiliate contamination.** Sponsored mentions group affiliate reads with paid
  ones, so verify a mention before treating it as the brand's own pitch.
- **No history is a finding.** Fall back to the brand's site and the Step 1
  answers, and say so in the output.
