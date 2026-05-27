# Peer cohort

Group A's like:view / comment:view thresholds are **relative to a
niche-matched peer baseline**, not absolute — engagement norms vary wildly by
niche (gaming ≠ finance ≠ tech tutorials), so a fixed cutoff would
false-flag low-engagement-but-honest niches and miss high-engagement niches
being inflated.

## How the cohort is built (`peer_cohort.py`)

1. **Preferred:** `tl channels similar <id> --limit 24` (the recommender).
   Best niche match.
2. **Fallback** (recommender empty): PG cohort —
   same `content_category` + `language`, `is_active`, `reach` within ±50%,
   `last_published` within 60 days, excluding the subject channel.
3. For up to 12 peers, pull each peer's last 10 longforms via `tl db es`,
   require ≥5,000 aggregate views and ≥3 videos (skip dead peers).
4. Baseline = **median** of peers' like-rate and comment-rate, plus the 25th
   percentile for context.

A subject channel flags when its longform rate is **< 0.4× the peer median**.
0.4× is intentionally generous — we only fire on gross deviation, not normal
variance. (The origin fraud case ran 0.008× the median; real channels cluster
0.7–1.5×.)

## Caching

Result cached in `peer-cohort-cache.json` keyed by
`content_category|language|reach_bucket`, TTL 30 days. Buckets:
`<10k, 10-50k, 50-150k, 150-500k, 500k-1m, 1-5m, 5m+`. This avoids re-spending
recommender credits and re-querying ES on every run. Force a rebuild by
deleting the cache file or calling `get_baseline(ch, refresh=True)`.

## Last-resort fallback

If no usable peers at all (rare — niche too small / all peers dead), a generic
English-tech floor is used (`like 2%, comment 0.25%`) and `source` is recorded
as `fallback-generic` in the metrics so the report consumer knows the
baseline was weak. Prefer widening the reach band over trusting this.

## Caveats

- The PG fallback uses `content_category` which is coarse; the recommender
  (`tl channels similar`) is materially better — prefer it.
- Reach buckets are wide on purpose (engagement scales sub-linearly with
  size); don't narrow them without re-checking the false-positive rate on a
  known-clean channel.
