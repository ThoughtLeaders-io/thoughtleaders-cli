# Output specification

## Deliverables

Under `<profiles>` (SKILL.md, Conventions), never inside the skill:

- `<channel_id>-facts.jsonl`: the ledger, one per creator. Line 1 is the
  meta record; every other line is one verified fact. This is the interface
  other skills and CONNECT runs read. Read and write it only through
  `scripts/store_io.py` (`read_ledger`, `write_ledger`).
- `<channel_id>-<brand_id>-connections.html` and its body-only twin
  `….fragment.html`: the one page per brand, rendered by
  `scripts/build_html.py` from `<corpus>/connections-<brand_id>.md`.
- `<brand>-creator-brief-<creator>.html` and its fragment, when the creator
  brief was asked for (`creator-brief-template.md`).

Working files (passages, batches, returns, clusters, merge input and
decisions, the markdown sources, `people.json`) live under
`<profiles>/.corpus/<channel_id>/`. PROFILE mode ends with the
ledger's absolute path and fact count in chat. Name every file from resolved
ids; return paths, never content.

## The ledger

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
 "last_seen": "2025-02-14",
 "recurrence": 3,
 "confidence": "confirmed",
 "sensitivity": "none",
 "sensitive": false,
 "speaker": "host",
 "people": [{"name": "Luna", "relation": null}],
 "superseded_by": null,
 "selected": true,
 "members": ["dQw4w9WgXcQ:497", "9bZkp7q19f0:1210", "3JZ_D3ELwOQ:88"]}
```

| Field | Values and meaning |
|---|---|
| `domain` | `origin`, `family`, `pets`, `home`, `work`, `money`, `health`, `habits`, `tastes`, `beliefs`, `relationships`, `other` |
| `provenance` | `transcript`, `social`, `web`, `bio`. A `social`, `web` or `bio` fact carries `source_url` and `seen_date` instead of `quote`, `video`, `start`, `url`; a `bio` fact also carries `source_excerpt` (cut mechanically from the stored bio) and `corroborated_by` when a transcript fact confirmed it; an uncorroborated one carries `unverified_bio: true`, is never selected, and at `clinical`, `children` or `location` never enters the ledger |
| `quote` | verbatim, source language, exact-verified by `verify_quotes.py`. A non-English quote may carry `gloss`, the labelled English translation |
| `published`, `last_seen` | the quoted upload's date; the newest upload date among the fact's evidence (script-computed). A fact is recent inside the last 24 months of the run date |
| `recurrence` | distinct videos or sources, never snippet count |
| `confidence` | `confirmed` or `unconfirmed` (`evidence-rules.md`). Dropped facts never enter |
| `sensitivity`, `sensitive` | the tier (`none`, `lifestyle`, `clinical`, `children`, `location`) and the derived boolean, true for `clinical`, `children`, `location`. Never set the boolean on its own |
| `speaker` | `host`, `cohost` (the second named host), `shared` (a "we" line about the hosts' shared life) |
| `people` | the people the quote names, `[{"name", "relation"}]`; `<corpus>/people.json` rolls them up across the ledger |
| `superseded_by` | the newer fact's id when latest wins; the old fact stays as history |
| `ended` | true when the merge shard found a claim stated as current is now over; history, never selected, never on a page |
| `staged`, `staged_only`, `probe` | the title read as a prank, challenge, stunt or skit; no non-staged upload confirms the claim (so `unconfirmed`, never selected, never on a page); what the search found |
| `hook_only` | the claim was found only in a staged upload's first 60 seconds and in no other video; `unconfirmed` |
| `dated` | present when the script turned "X years ago" in the claim into a year |
| `selected` | true on at most 40 facts: the shard's confirmed picks ranked, then confirmed facts by recurrence and recency; never `unconfirmed` or `ended`, never `children` or `location`, never `clinical` below three videos, never `staged_only`, never an uncorroborated bio fact. A thin ledger selects fewer |
| `members` | the passage keys (`<video_id>:<window start>`) the fact was built from; a refresh matches by these, never by `start` |

## The meta record (line 1)

```json
{"schema": "tl-creator-meta/v2", "channel_id": 123456, "channel_name": "…",
 "generated_at": "2026-09-02", "corpus_window": ["2016-03-01", "2026-08-20"],
 "coverage": {"videos_with_transcript": 287, "videos_matched": 141, "passages": 2252,
              "windows_judged": 500, "gems": 310, "facts": 91},
 "format": "solo", "format_evidence": "…", "lanes": "transcripts",
 "context": {"websites": [], "social_links": [], "second_channel_candidates": []},
 "latest_video_date": "2026-08-29", "rounds": 1, "facts_file": "123456-facts.jsonl"}
```

Written by `scripts/ledger_meta.py write`, never by hand. `write --from`
refuses (exit 2) a transcript fact whose `verify.match` is not `exact`.
`corpus_window` is the span of the videos whose passages were stored;
`coverage` is counted from the build's own files; `lanes` is `transcripts`
or `transcripts+socials`; `latest_video_date` is what the reuse check counts
uploads after. On a refresh the header's descriptive fields carry over
unless passed again.

## Reuse

`python3 scripts/ledger_meta.py check --channel <id> [--lanes …] [--rebuild] [--no-refresh] [--max-new-videos 5] [--max-age-days 60]`

| Decision | When |
|---|---|
| `reuse` | at most 5 uploads since the ledger and it is at most 60 days old |
| `refresh` | more uploads, an older ledger, a failed count, or the run asks for socials and the ledger has none: one incremental round (`transcript-mining.md`, 6) |
| `build` | no ledger, no meta header, or `--rebuild` |

The announcement line is repeated to the user verbatim. `--no-refresh`
forces reuse; `--rebuild` forces a build. Never reuse silently, never refuse
a rebuild.

## CONNECT: the connection map

`<corpus>/connections-<brand_id>.md`, frontmatter `schema:
tl-creator-connections/v2`, `channel_id`, `channel_name`, `brand_id`,
`brand_name`, `facts_file`, `brand_read_date`. Sections, in this order; the
section order is the ranking:

1. `## About <creator name>`: two or three sentences on the person behind
   the premise. The renderer prints the platform's description under it; do
   not restate it, and do not list facts.
2. `## Thesis`: three or four sentences on why these two fit. On a thin fit
   it says "thin fit" and names the one or two angles and what to confirm.
3. `## About <brand name>`: two or three neutral sentences from the
   brand-site lane and the platform's category description only. Never a
   sponsored-read snippet, a price or another client's data.
4. One `## <title> · **<type>** · **<strength>**` section per connection,
   strongest first. Type: `direct` (fact to product), `adjacent` (lifestyle
   fit), `category precedent` (the creator already does what the product
   enables, from the probe). Strength: `strong` when the quoted fact itself
   names what the brand offers and `last_seen` is inside 24 months; `thin`
   when the link runs through the channel's format or a generic trait, or
   the fact is older (then the year is stated). At most two thin cards. Each
   section holds, in order: the creator's words as a `>` quote with its
   `&t=` link on a `>` continuation line (a ledger fact's verified quote, or
   a probe window on a precedent card); what the brand offers that meets it,
   with the lane it came from; one line on how it could be used; at most
   one labelled sample read; one Do line and one Do not line, both
   concrete.
5. `## Where this could go wrong`: always present, always last. Reads the
   whole ledger, withheld tiers and old or ended facts included, and names
   the kind of fact, never its detail.

A fact used to argue against the brand's category is never a card. Facts at
tier `children` or `location` never appear in a card; `clinical` facts only
with three or more videos (`evidence-rules.md`). `unconfirmed`, `ended`,
superseded and `staged_only` facts are never quoted. IF nothing honestly
connects: the About sections, a no-fit verdict in prose, what was searched,
and no cards.

## CONNECT: the creator brief

Opt-in. The writer reads `<corpus>/creator-brief-input-<brand_id>.json`
(`talking_points`, `promoting`, `brand_brief`, `supplied`), the map and the
whole ledger, and writes `<corpus>/creator-brief-<brand_id>.md` with
frontmatter `schema: tl-creator-brief/v1`, `channel_name`, `brand_name`,
`talking_points_supplied`. Layouts, rules and the example are in
`creator-brief-template.md`.

## The page

`build_html.py` renders the map as one fixed template: thesis, who they are
(the `selected` facts), people they mention, timeline, the creator's own
unverified words when the bio lane left any, about the brand, the numbered
cards, where this could go wrong, and the ledger's honesty strip (counts,
tiers, coverage, format, lanes, linked platforms). `--check` enforces the
map rules above and exits 3 with the problems; fix the markdown, never the
checker. Publish the fragment where the host allows; give the user the
page's absolute path.

## Never in any file

Prices, costs, rate cards, deal terms, other clients' internal data,
performance grades. One labelled sample-read line per connection is the only
ad copy allowed: no scripts, CTA wording or alternates.
