# tl CLI recipes

Exact `tl` commands the skill issues, via `scripts/tl_cli.py`. Everything runs
through the `tl` CLI — no database credentials are used. (IDs below are
placeholders.)

## Auth / preflight
```bash
tl whoami            # must succeed
tl balance           # raw tl db * needs the Intelligence plan + credits
python3 tl_cli.py preflight
```

## Channel resolve (`resolve_channel.py`)
`tl_cli.channels_show` builds an exact PG query (not `tl channels show`, whose
curated public schema differs from the raw columns the skill reads):
```bash
tl db pg "SELECT id, channel_name, reach, content_category, language,
  total_views, country, ... FROM thoughtleaders_channel
  WHERE id = 1234567 ORDER BY reach DESC NULLS LAST LIMIT 10" --json
```
A numeric id resolves exactly; a name/handle matches via ILIKE on
`url`/`slug`/`channel_name`. If more than one row comes back the skill surfaces
the candidates (highest subscribers first) for the user to pick. `adlink:<id>`
first runs the adlink PG lookup (below), then resolves by its `channel_id`.

## Recent videos (Group A & C input)
```bash
tl db es '{"size":30,"_source":["id","title","publication_date","views",
  "likes","comments","duration","content_type","url"],
  "query":{"bool":{"must":[{"term":{"doc_type":"article"}},
  {"term":{"channel.id":1234567}},{"term":{"content_type":"longform"}}]}},
  "sort":[{"publication_date":{"order":"desc"}}]}' --json
```
Repeat with `content_type:"short"`. ES doc fields are `views`/`likes`/
`comments` (NOT `view_count`); `id` is `"<channel_id>:<video_id>"`.

## Peer cohort (Group A)
```bash
tl channels similar 1234567 --limit 24 --json          # preferred
# fallback when similar is empty:
tl db pg "SELECT id FROM thoughtleaders_channel
  WHERE content_category=10 AND language='en' AND is_active=true
  AND reach BETWEEN 100000 AND 300000
  AND last_published > (CURRENT_DATE - INTERVAL '60 days')
  AND id != 1234567 ORDER BY reach DESC LIMIT 25"
```
Then last-10-longform ES pull per peer; baseline cached 30d in
`references/peer-cohort-cache.json` keyed by
`content_category|language|reach_bucket`.

## View curves (Group B)
```bash
tl db fb "SELECT age, view_count, like_count, comment_count
  FROM article_metrics
  WHERE channel_id = 1234567 AND id = 'VIDEO_ID' ORDER BY age"
tl db fb "SELECT scrape_date, total_views, reach
  FROM channel_metrics WHERE id = 1234567 ORDER BY scrape_date"
```
**Always include `channel_id`** on `article_metrics` or it full-scans and
times out (leading index `(channel_id, id)`). `article_metrics.id` is the bare
YouTube id (use `SPLIT_PART(article_id,':',2)` from adlinks).

## Adlink drill-down (`adlink:<id>`)
```bash
tl db pg "SELECT a.id,a.publish_status,a.publish_date,a.send_date,a.price,
  a.cost,a.article_id,a.url,s.channel_id
  FROM thoughtleaders_adlink a
  JOIN thoughtleaders_adspot s ON a.ad_spot_id=s.id WHERE a.id=12345"
```

## Comments (Group C) — NOT a TL query
Scraped fresh from YouTube via `yt-dlp` with the **android** InnerTube player
client (`extractor_args.youtube.player_client=['android']`, `comment_sort=
['new']`). No cookies, no API key, no TL data. youtube-comment-downloader is
a last-resort fallback only.

## Gotchas
- `tl db *` returns JSON that may be a bare list or `{rows|data|results:[...]}`
  — `tl_cli._coerce_rows` handles both.
- DateTimeField filters: use `< next_day`, not `<= date` (TL pitfall).
- View-curve snapshots are sparse for old videos — `view_curves.py`
  interpolates (linear + log) rather than assuming daily points.
