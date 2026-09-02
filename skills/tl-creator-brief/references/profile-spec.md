# Output specification

## One ledger, one meta record, one designed page

A profile build leaves two durable files per creator in
`tl-creator-profiles/` under the invocation directory (create it if missing;
never write inside the skill's own directory):

- **`<channel_id>-facts.jsonl`** — the machine ledger, one fact per line.
  This is **the stable interface** other skills, personas and CONNECT runs
  consume. Full thoroughness lives here.
- **`<channel_id>-meta.json`** — what the build was: when, over which
  videos, how much it read, what it found. Written by
  `scripts/ledger_meta.py write`, never by hand. It is what a later run
  reads to decide whether the ledger is fresh enough to reuse.

The human surfaces are rendered from those two files by
`scripts/build_html.py` and are never the source of anything:

- **PROFILE** hands the user `<channel_id>-profile-ledger.html`, the ledger
  view — every verified fact with its citation and sensitivity tier, under
  the meta strip and the tallies. There is no prose one-pager any more:
  the thing a second brand reuses is the ledger, and a page that holds
  every fact is more useful to the person asking "what do we know about
  them" than a 400-word summary was.
- **CONNECT** hands the user `<channel_id>-<brand_id>-connections.html`, the
  only designed deliverable. Its source is `<channel_id>-<brand_id>-connections.md`
  (the ranked connection map), and its "who they are" section is rendered
  from the ledger at render time, never written by a model.

All outputs are files, never chat messages: chat scrolls away and these are
made to be picked up later. Return the paths, and name files from resolved
IDs only — IDs are exact, names are fuzzy and change on rebrands, and
deterministic names let a re-run overwrite its own output.

## The machine ledger: `<channel_id>-facts.jsonl`

One JSON object per line, only quote-verified and judgment-passed facts:

```json
{"fact_id": "f012",
 "claim": "adopted a rescue dog named Luna",
 "domain": "pets",
 "provenance": "transcript",
 "quote": "we finally adopted luna from the shelter last spring",
 "video": "48247:dQw4w9WgXcQ",
 "start": 512,
 "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=512s",
 "published": "2024-05-01",
 "recurrence": 3,
 "confidence": "confirmed",
 "sensitivity": "none",
 "sensitive": false,
 "superseded_by": null,
 "selected": true}
```

- `domain`: one of `origin`, `family`, `pets`, `home`, `work`, `money`,
  `health`, `habits`, `tastes`, `beliefs`, `relationships`, `other`.
- `provenance`: `transcript` | `social` | `web`, per `evidence-rules.md` —
  lanes never masquerade. `social`/`web` facts carry `source_url` and
  `seen_date` instead of `quote`/`video`/`start`/`url`.
- `quote`: verbatim, in the source language; exact-verified by
  `scripts/verify_quotes.py` before it lands here. A non-English quote may
  carry a `gloss` (English translation, labelled — never the quote itself).
- `recurrence`: distinct videos/sources, never snippet count.
- `confidence`: `confirmed` | `unconfirmed`, per `evidence-rules.md`
  (dropped facts never enter the ledger; their count goes in the run
  report). When the opt-in socials lane did not run there are no
  `social`/`web` facts, so cross-lane corroboration is unavailable: a fact
  reaches `confirmed` only on a transcript-side rule (solo format, or a
  host-anchored window), never by corroboration. That is a ceiling on the
  evidence, not a defect in the run — say so in the run report.
- `sensitivity`: `none` | `lifestyle` | `clinical` | `children` | `location`,
  per `evidence-rules.md`. `sensitive` is the **derived** boolean — true
  exactly for the withheld tiers (`clinical`, `children`, `location`) — kept
  so readers written against the old flag keep working. The tier is the fact;
  never set the boolean independently of it. Every fact carries the tier;
  the ledger view renders it as a badge and tallies it.
- `superseded_by`: the `fact_id` of the newer fact when latest-wins applies;
  superseded facts stay in the ledger as history.
- `selected`: true on the 15–20 strongest facts. Selection favors confirmed,
  recurring, cross-lane-corroborated and connection-fertile facts. The
  connections page's "who they are" section takes `selected` facts first,
  then the most recurring, so the pick still shapes what a brand-facing
  reader sees first.

CONNECT loads this file, not any markdown.

## The meta record: `<channel_id>-meta.json`

```json
{"schema": "tl-creator-meta/v1",
 "channel_id": 123456,
 "channel_name": "…",
 "generated_at": "2026-09-02",
 "corpus_window": ["2016-03-01", "2026-08-20"],
 "coverage": {"videos_with_transcript": 287, "videos_matched": 141,
              "passages": 2252, "windows_judged": 500, "gems": 310,
              "facts": 91},
 "format": "solo",
 "format_evidence": "fp density 41/1k words median; 2 videos with interview markers",
 "lanes": "transcripts",
 "context": {"social_links": ["https://instagram.com/…"],
             "second_channel_candidates": [{"name": "… Clips", "id": 123457}]},
 "latest_video_date": "2026-08-29",
 "rounds": 1,
 "facts_file": "123456-facts.jsonl",
 "credits_spent": 1840}
```

- `corpus_window`: earliest and latest publication date among the videos
  whose passages were stored — the span the ledger can speak for.
- `coverage`: `videos_with_transcript` (the channel's transcript-bearing
  uploads at fetch time), `videos_matched` (videos a cue passage came from),
  `passages` (windows fetched across all rounds), `windows_judged` (windows
  an extractor gave a verdict on), `gems`, `facts` (lines in the ledger).
  Every number is counted from the build's own files by
  `scripts/ledger_meta.py write`; a count it could not derive is 0 and the
  file it needed is named in `missing`.
- `format`: `solo` | `interview` | `multi_host` | `faceless_scripted`, with
  its evidence — the label the format call produced, passed in on `write`.
- `lanes`: `transcripts` or `transcripts+socials` — which creator-source
  lanes built the ledger. The reuse check compares it with what the current
  run asks for.
- `context`: the linked platforms and sibling-channel candidates from
  `channel_context.py` (`write --context <file>`), so the ledger view can
  list them: each platform as read or "linked but unread", each sibling as
  "not mined".
- `latest_video_date`: the channel's newest upload when the build fetched.
  The reuse check counts uploads after it.
- On a refresh, `write` carries `channel_name`, `format`, `format_evidence`,
  `lanes`, `context` and `credits_spent` over from the existing record unless
  they are passed again; only the counts are recomputed.
- `rounds`: extraction rounds so far (default: one per fetch summary in the
  corpus directory). An incremental refresh is round `rounds + 1`.
- `credits_spent`: optional, when the run tallied it.

## Reuse — a found ledger wins, with a freshness check

Every run, PROFILE or CONNECT, starts with one command:

```bash
python3 scripts/ledger_meta.py check --channel <id> [--lanes transcripts+socials] \
  [--rebuild] [--no-refresh] [--max-new-videos 5] [--max-age-days 60]
```

When `<channel_id>-facts.jsonl` + `<channel_id>-meta.json` exist it prints
one announcement line, which the run report repeats verbatim —

> Found a ledger for Sydney Watson built 2026-09-01 over 2016-03 → 2026-08-20,
> 91 facts. 3 videos uploaded since.

— and a JSON decision. The uploads count is one cheap index count after
`meta.latest_video_date`. The rule:

- **`reuse`** — at most 5 uploads since and the ledger is at most 60 days
  old (`--max-new-videos`, `--max-age-days`): use the ledger as is. CONNECT
  goes straight to the brand read; PROFILE re-renders the ledger view.
- **`refresh`** — more uploads than that, or an older ledger, or the count
  failed, or the run asks for the socials lane and the ledger was built from
  transcripts only (a ledger that read socials covers a transcripts-only
  request; the reverse does not): run ONE incremental round (SKILL.md, "Incremental refresh") —
  fetch with `--round N --exclude classified.jsonl`, extract only the new
  batches, assemble with `--append`, re-cluster, merge, verify, rewrite the
  ledger and the meta record. Cost scales with the new uploads, not the
  corpus.
- **`build`** — no ledger, an incomplete pair (facts without meta, or a v1
  or v2 profile that predates the meta record), or `--rebuild`: full build.

`--rebuild` forces a full build; `--no-refresh` forces reuse as is, whatever
is new. Never reuse silently — the announcement line is the user's notice
that the ledger predates today's uploads — and never refuse to rebuild.

## Mode B: `<channel_id>-<brand_id>-connections.md`

A ranked connection map, the source the connections page renders from.
Frontmatter:

```yaml
---
schema: tl-creator-connections/v2
channel_id: 123456
channel_name: "…"
brand_id: 50485
brand_name: "…"
facts_file: 123456-facts.jsonl
brand_read_date: 2026-09-02
---
```

Then one `## ` section per connection, strongest first — the section order
IS the ranking and the page numbers them — with the type as a bold tag on
the heading line: `## Runs on four hours of sleep — **direct**`. Each
section holds, in this order:

1. **The creator's own words** (or the social/web fact, labelled as such) —
   verbatim, timestamped, from the ledger, as a `>` quote with its `&t=`
   link.
2. **What the brand offers that meets it**, and which brand-read lane that
   came from (`[web]`, `[social: instagram]`, ad-read sample, sponsorship
   patterns).
3. **How this could be used** — one neutral line. Connection material, not ad
   copy; nobody is handed words to read aloud.

Types: **direct** (fact ↔ product), **adjacent** (lifestyle/context fit),
**category precedent** (the creator already does what the product enables,
from the confirm-only probe). Facts at sensitivity tier `children` or
`location` do not appear unless a human opted one in; `clinical` facts
appear only when the creator discusses them repeatedly (three or more
videos) or frames them as part of their own story, otherwise they too wait
for a human opt-in (`evidence-rules.md`). Beliefs are ordinary material.

If nothing honestly connects, the document has no `## ` sections: a
**no fit** verdict in prose, what was searched, and it stops — a no-fit
verdict is the deliverable, not a failure.

## HTML views

Both surfaces render via `scripts/build_html.py` — a deterministic template,
never hand-written per run. Markdown + JSONL remain canonical.

```bash
# PROFILE — the ledger view (paths as ledger_meta.py write printed them)
python3 scripts/build_html.py --facts tl-creator-profiles/<id>-facts.jsonl \
  --meta tl-creator-profiles/<id>-meta.json
# CONNECT — the connections page
python3 scripts/build_html.py --in tl-creator-profiles/<id>-<brand>-connections.md \
  --facts tl-creator-profiles/<id>-facts.jsonl --meta tl-creator-profiles/<id>-meta.json
```

- **`<channel_id>-profile-ledger.html`** (override `--ledger-out`): the
  meta strip (build date, corpus window, matched/transcript videos, passages
  judged, fact count, format, rounds), the tallies (confidence, sensitivity
  tiers with the withheld count — `clinical` counts as withheld only below
  three videos, per `evidence-rules.md` — and domains), every fact — claim,
  tier badge, quote, full citation, link; superseded facts say which fact
  replaced them — and then the other channels and platforms from `context`.
- **`<channel_id>-<brand_id>-connections.html`** (override `--out`): a
  **who they are** section — the top recurring facts by life domain (the
  `selected` facts first, then by recurrence; at most three per domain and
  twelve in all), each with a short verbatim quote and its link, the format
  label and the corpus window — above the ranked **connections**, one card
  per `## ` section with its type badge. Facts at tier `children` or
  `location` never enter the who-they-are section; `clinical` and
  `lifestyle` facts appear with their tier badge. Provenance labels in the
  markdown are kept: a connection map names its lanes.

When the host supports publishing artifacts, publish the connections page
(or, in PROFILE mode, the ledger view) so the user gets a link; the files in
`tl-creator-profiles/` are the durable copies.

## Never in any file

Prices, costs, rate cards, deal terms, other clients' internal data,
performance grades, or drafted ad copy. Every output is built to be
forwarded.
