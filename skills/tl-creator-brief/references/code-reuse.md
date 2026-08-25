# Reuse what exists

Do not write new code for anything here. It exists, it is tested, and an agent
that regenerates it is slower, more expensive and less correct every run.

| Need | Call |
|---|---|
| Resolve a channel (handle, URL, name, id, `adlink:<id>`) | `resolve_channel.resolve(ref)` in `skills/tl-channel-authenticity/scripts/` |
| Recent uploads, already split longform / Shorts | the same return value |
| Any TL data read | `tl_cli.py` in that directory (`db_pg`, `db_es`, `db_fb`, `channels_show`, `preflight`) |
| Scrape a video's comments | `comment_scraper.py`, same directory |
| Organic versus bot comments | `youtube-comment-classifier` agent + `references/comment-patterns.md` |
| Topic → validated keyword filter | `tl-keyword-research/scripts/expand_entities.py` → `probe.py` → `select_keywords.py` |
| Transcript text around a hit | `tl-keyword-research/scripts/fetch_context.py` (already strips caption XML) |
| Timestamp for a quote | `scripts/quote_timestamp.py` (this skill) |
| Within-channel resonance | `scripts/resonance.py` (this skill) |
| Schema and field names | `skills/tl/references/postgres-schema.md`, `elasticsearch-schema.md` |

Run `python3 tl_cli.py preflight` before the lanes launch. It must print `OK`.

## Gotchas that will cost you a run

- **`resolve_channel.py` prints a summary, not JSON, when run as a CLI.** Import
  it:
  ```bash
  python3 -c "import json, resolve_channel as rc; print(json.dumps(rc.resolve('<ref>'), default=str))"
  ```
- **These scripts import siblings** (`tl_cli`, `_io_utf8`), so run them from
  their own `scripts/` directory.
- **`comment_scraper.py` sorts by recent, not popular**, because it was written
  to hunt bot padding. Ranking by sentiment on that sample is recency-weighted:
  say so in the caveats.
- **`fetch_context.py` searches `title,summary,transcript`.** A `summary` hit is
  the video description, usually the affiliate link, not speech. See
  `evidence-rules.md`.

## Anything genuinely missing

Write it once as a script in this skill's `scripts/`, never inline in a prompt
where it is regenerated every run.
