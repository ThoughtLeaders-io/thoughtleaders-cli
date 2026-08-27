# Output specification

## Who reads it

Whoever ran the skill. Make no assumption about their role, and write nothing
that only makes sense to one kind of reader.

Assume it may be forwarded, including outside the company. That is what the
no-prices and verbatim-quotes rules are protecting against.

## Two sections, and the profile leads

**The creator profile is its own clearly visible top-level section.** It is
never folded into, collapsed inside, or reduced to a preamble for the brand
connections. It has standalone value: it is the thing nobody else can produce,
because it comes out of a searchable transcript corpus, and it is reusable for
any brand after this one.

### 1. The creator profile

- **Who they are**, in one or two lines, from the identity step. Not subscriber
  counts, which the reader can already see.
- **Detected channel format, and the confidence that follows from it.** Stated
  plainly, every run, per `evidence-rules.md`.
- **The self-references.** Verbatim, each with video title, date, a timestamped
  link, one short line on what it reveals, and its **attribution bucket**
  (confirmed or unconfirmed, per `evidence-rules.md`). Group them loosely by what
  they are about: history and origin, how they work and learn, beliefs, habits
  and tastes, life details. Material with nothing to do with the brand belongs
  here and is not to be trimmed for being off-brand.
- **Coverage**: how many uploads the channel has, how many were sampled and by
  which strategy, how many had no transcript.
- **Whether the sweep ran dry.** See below. This is not optional.

Where the format does not support the analysis, this section says so and names
the format, and there is nothing else in it. That is a complete answer.

### 2. The brand connections

Each connection is three things, in this order:

1. **The creator's own words**, verbatim and timestamped, from the profile
   above.
2. **What the brand offers** that meets it, and which brand-input source that
   came from.
3. **The thing that could be built on it.** Specific and concrete.

A connection with no quote behind it is not a connection. Cut it.

If the profile holds nothing that honestly meets the brand, say that, show what
was searched, and stop.

### Did the sweep run dry

Every run answers this, because "we found nothing" and "we did not look far
enough" are different answers and the reader cannot tell them apart on their own.

The sample is drawn in date order, so every detail found knows which video it
came from and where that video sat in the sample. Compare the last third of the
sampled videos against the first two thirds and ask one question: **did the last
third produce genuinely new details, or only restatements of what was already
found?**

- Only repeats: the sweep has run dry, and reading more uploads will not help.
- Still producing new material at the end: there is more in the catalogue.

State it in one line, with the counts: how many new details the final third
produced, how many were repeats, the conclusion that follows, and how many
uploads were not read.

Where there is more to find, name the way to get it: re-run Step 3 with a higher
`--max`. Never suggest narrowing the search to the brand's subject instead.

### Caveats

Transcript coverage, uploads not sampled, how many quotes were dropped as
unattributable, how many are carried as unconfirmed, the risk of crediting
another voice where the format has one, caption corrections, reads that failed
sponsorship verification, and anything inferred rather than found.

## Delivery: two files, and the paths come back

**The output is a markdown file, not a chat message.** Chat scrolls away and the
brief is meant to be picked up later, forwarded, and reused against the next
brand. So write the file, then return its path. A summary in chat is fine on top
of that, never instead of it.

Write **two** files, because the two sections have different lifespans:

| File | Contents | Why separate |
|---|---|---|
| `creator-briefs/<channel_id>-profile.md` | Section 1 only, the creator profile, complete and standalone. | It is brand-independent. The next brand reuses it without re-running Steps 2 and 3, which is the slow half of the run. |
| `creator-briefs/<channel_id>-<brand_id>-brief.md` | The whole brief: the profile section, then the brand connections. | The deliverable for this run. Self-contained, so forwarding it needs no second file. |

**Names are derived from the resolved IDs, never from names.** IDs came out of
Step 1 and are exact; channel and brand names are fuzzy, get punctuation, and
change on a rebrand. Where a rebrand gave several brand IDs, use the one the user
named. Deterministic naming is the point: a re-run overwrites its own file rather
than littering variants, and the profile cache is findable without a search.

Write into `creator-briefs/` under the directory the skill was invoked from, and
create it if it does not exist. Never write inside the skill's own directory,
which is version-controlled and is not a place for run output.

**Check for the cached profile before Step 2.** If
`creator-briefs/<channel_id>-profile.md` already exists, offer it: say when it
was written and what it covers, and ask whether to reuse it or re-run the sweep.
Reusing it skips straight to Step 4. Never reuse it silently, since a profile
written months ago has missed everything uploaded since, and never refuse to
re-run: a wider sweep over the same channel is the documented fix for a thin
profile.

## Never in the output

- Prices, costs, rate cards, deal terms, or anything internal to how the deal
  is bought and sold.
- Performance grades or renewal judgements.
- Words for the creator to read aloud. This is connection material, not ad copy.
