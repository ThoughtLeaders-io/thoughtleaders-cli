# Reuse what exists

Do not write new code for anything here. It exists, it is tested, and an
agent that regenerates it is slower and less correct every run.

| Need | Call |
|---|---|
| Resolve a channel or brand name to an ID | `tl channels find` / `tl brands find`, never `ILIKE` on a name |
| All tl data access from scripts | `skills/_shared/tl_cli.py` — stdin-passed bodies, timeouts, loud failures |
| Fetch a channel's whole transcript corpus | `scripts/fetch_corpus.py` (this skill) |
| Rank corpus windows for the model layer | `scripts/selftalk_scan.py` (this skill) |
| Channel identity + measured format stats | `scripts/channel_context.py` (this skill) |
| A brand's past sponsorship reads | `scripts/brand_reads.py` (this skill) |
| Verify + timestamp a quote | `scripts/quote_timestamp.py` (this skill) |
| Transcript text around a keyword hit | `skills/tl-keyword-research/scripts/fetch_context.py` (already strips caption XML) |
| Topic to validated keyword filter | the `tl-keyword-research` skill |
| Schema and field names | `skills/tl/references/postgres-schema.md`, `elasticsearch-schema.md` |

## How this skill's scripts are built

Every script imports the shared wrapper via a `sys.path` hook computed from
its own `__file__` — **no `cd` into any skill directory, ever**. Outputs go
under per-channel paths (`tl-creator-profiles/.corpus/<channel_id>/`), so
many channels can run concurrently without colliding. Scripts never swallow a
query failure into an empty result: errors abort loudly.

## Gotchas that will break a run

- **`tl db es` returns `{"results": [...]}`**, not the native Elasticsearch
  `hits.hits` shape. The shared wrapper unwraps it.
- **Pass query bodies on stdin** (`tl db es -`), never argv — a big ids list
  breaks the argv path. The shared wrapper does this.
- **Channel documents are duplicated in Elasticsearch** — every
  channel-document query needs `"collapse": {"field": "id"}`.
- **The channel's raw `description` is usually boilerplate**; the generated
  profile (`ai.description`) is the identity field worth reading.
  `channel_context.py` returns both.
- **`query_string` is blocked** on Elasticsearch; use `multi_match`.
- **`brand_mentions` is nested**: query it with a `nested` query, and
  re-check `type` and `field` on every element of the returned list — the
  doc-level match does not mean each mention matched. A `(0,0)` span is a
  detection with no position; never pad it into a claim about the video's
  opening. A `description` hit is the affiliate link, not speech.
- **Detected sponsored mentions include affiliate reads.** An affiliate read
  that describes the product still describes the product; one that only drops
  a link is visible from the absence of words.
- **The ES highlight feature is stripped by the CLI** — timestamps never come
  from highlights; they come from stored cue offsets in the local corpus.
