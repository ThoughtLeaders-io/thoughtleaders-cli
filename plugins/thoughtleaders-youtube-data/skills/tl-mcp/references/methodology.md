# Shared research terminology and methodology

<!-- Generated from selected public portions of skills/tl/SKILL.md. -->

- **Channels** — YouTube channels, but could also be podcasts
- **Brands** — Entities (usually companies / organizations, but could be narrowed down to individual brands of a company)
- **Uploads** — YouTube videos indexed from Elasticsearch
- **Snapshots** — historical time-series metrics for channels and videos (Firebolt)
- **Reports** — saved report configurations that can be re-run
- **Comments** — notes attached to sponsorships, channels, or brands
- **`projected_views`** (on channels) — projected views per video on that channel. Forward-looking estimate. May be null when not yet computed. ⚠️ NOT actual views and NOT ad-industry "impressions" (ads served).
- **`views`** (on sponsorships) — actual view count of the sold and published sponsored video, accessible when `article_id` is set.

## Sponsorship matching

Where possible, if searching for a sponsorship match between channels and brands, first search for what do similar brands sponsor / which brands is the channel usually sponsored by. The similarity judgement should be preferably based on similar topics, similar upload frequency, similar channel sizes, and only after all that, on demographics.
