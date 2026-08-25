# Evidence rules

The output is written to be forwarded. Every rule here exists to stop a wrong
quote reaching a creator.

## Spoken versus written

- Anything claimed as **spoken**: `fetch_context.py --fields transcript`, and
  discard every snippet whose `field` is not `transcript`.
- Descriptions have one use: confirming a sponsorship happened and reading the
  current CTA format. Separate call, labelled as such. Never merge the two
  result sets.

## Quotes

- Verbatim or not at all.
- **Timestamp every quote** with `scripts/quote_timestamp.py`:
  ```bash
  python3 scripts/quote_timestamp.py <channel_id>:<video_id> "the quote"
  ```
- `found: false` blocks publication. Retry with a spelling or phonetic variant;
  if it still fails, drop the quote.
- `cues: 0` on a miss means the video has no stored transcript at all. That is a
  coverage gap, counts towards the reported coverage rate, and is not evidence
  the creator never said it.

## Captions

- Coverage is partial. Report the rate. Absence is not evidence of absence.
- Auto-captions mangle proper nouns. Search spelling and phonetic variants
  before concluding zero hits. Observed: "Matiks" appears in transcripts as
  *Matics*, *Matx* and *Matis*, and never as itself.
- Corrections are never silent: corrected proper noun in square brackets, raw
  caption text noted in the caveats. Bracketed proper-noun fixes are the only
  permitted edit.
- No speaker labels. On interview channels verify from context that the *host*
  is speaking, and drop anything ambiguous.

## Figurative use

A raw category search returns mostly metaphor. Screen twice:

- **Channel level:** `keyword-context-classifier` with an explicit `TOPIC:` line
  for the product's literal sense and a `NOT:` line for the figurative ones.
  Example `NOT:` "puzzle" as a geopolitical problem, "memory" as historical
  memory, "brain" as rhetoric.
- **Snippet level:** that agent judges channels, not snippets, so it cannot pick
  quotes. Judge each snippet individually before it becomes a quote-bridge, and
  **report the survival count** ("30 hits, 4 literal"). That ratio is itself
  evidence of how close the creator is to the category.

## Competitor check

Both halves, or it misses:

```bash
tl sponsorships list channel:<channel_id> publish-date-start:<12 months ago> --md
```

covers TL-brokered deals, including live proposals other people own. For reads
bought outside TL, scan the channel's sponsored mentions in Elasticsearch over
the same window.

Compare against the competitor and guide brands named in Step 1. If none were
named, **ask** rather than inferring the competitor set from the category.

## The evidence decides the verdict

If there is no format precedent and no credible bridge, say exactly that, show
what was searched, and stop. At the research moment that is the whole answer and
a good one.
