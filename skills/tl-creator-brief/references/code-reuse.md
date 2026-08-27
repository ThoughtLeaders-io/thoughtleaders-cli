# Reuse what exists

Do not write new code for anything here. It exists, it is tested, and an agent
that regenerates it is slower, more expensive and less correct every run.

| Need | Call |
|---|---|
| Resolve a channel or brand name to an ID | `tl channels find` / `tl brands find`, never `ILIKE` on a name |
| Channel identity, format signals, recent titles | `scripts/channel_profile.py` (this skill) |
| Pick a capped, spread sample of a channel's uploads | `scripts/build_corpus.py` (this skill) |
| Transcripts filtered to self-reference candidates | `scripts/selftalk_scan.py` (this skill) |
| A brand's past sponsorship reads | `scripts/brand_reads.py` (this skill) |
| Timestamp for a quote that did not come from the scan | `scripts/quote_timestamp.py` (this skill) |
| Transcript text around a keyword hit | `skills/tl-keyword-research/scripts/fetch_context.py` (already strips caption XML) |
| Topic to validated keyword filter | `tl-keyword-research/scripts/expand_entities.py` to `probe.py` to `select_keywords.py` |
| Any other TL data read | `tl db pg` / `tl db es` via the `tl` CLI |
| Schema and field names | `skills/tl/references/postgres-schema.md`, `elasticsearch-schema.md` |

## How this skill's scripts are built

All four shell out to the `tl` CLI directly and import nothing but the standard
library and each other. That is deliberate: the sibling skills' helpers
(`tl_cli.py`, `resolve_channel.py`) import their own siblings, so they only run
from their own `scripts/` directory and cannot be imported from here without a
path hack. `selftalk_scan.py` imports `fetch_cues` from `quote_timestamp.py`, so
run these from this skill's `scripts/` directory.

## Gotchas that will cost you a run

- **`tl db es` returns `{"results": [...]}`**, not the native Elasticsearch
  `hits.hits` shape. Read `results`.
- **Channel documents are duplicated in Elasticsearch.** Observed: 35 identical
  copies under one channel id. Every channel-document query needs
  `"collapse": {"field": "id"}` or it pays for all of them.
- **The channel's raw `description` is usually not a description.** Observed on
  a 19M-subscriber channel: the entire About text is a one-line nag about
  subscribing. The platform's generated profile (`ai.description`) is the field
  worth reading for identity. `channel_profile.py` returns both, in that order
  of preference.
- **`query_string` is blocked** on Elasticsearch. Use `multi_match` for text
  search. `match_phrase` on the transcript field does currently work, but the
  schema reference's guidance is to prefer `multi_match`, so do.
- **Detected sponsored mentions include affiliate reads.** Verify a mention is a
  genuine sponsorship before treating it as the brand's own pitch. See
  `brand-input.md`.
- **`resolve_channel.py` in the authenticity skill is not usable for the
  corpus.** It is hard-capped at the 30 newest uploads per format and carries no
  channel description, so it can neither sample across a back catalogue nor do
  the identity step. That is why `build_corpus.py` and `channel_profile.py`
  exist.
- **`fetch_context.py` searches `title,summary,transcript`.** A `summary` hit is
  the video description, usually the affiliate link, not speech. See
  `evidence-rules.md`.

## Anything genuinely missing

Write it once as a script in this skill's `scripts/`, never inline in a prompt
where it is regenerated every run.
