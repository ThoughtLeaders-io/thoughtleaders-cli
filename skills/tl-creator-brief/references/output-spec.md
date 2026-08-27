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

Worked example of the shape: the creator has said on camera that their favourite
food is pizza; the brand's in-app scoring unit is called pies; so instead of the
usual merch, send real pizzas to users who hit a hundred day streak on that
creator's code.

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

State it in one line, with numbers, for example: "the final third of the sample
produced 2 new details and 6 repeats, so the sweep has largely run dry", or "the
final third produced 9 new details, so there is more to find, and 478 uploads
were not read".

Where there is more to find, name the way to get it: re-run Step 3 with a higher
`--max`. Never suggest narrowing the search to the brand's subject instead.

### Caveats

Transcript coverage, uploads not sampled, how many quotes were dropped as
unattributable, how many are carried as unconfirmed, guest-attribution risk on an
interview channel, caption corrections, reads that failed sponsorship
verification, and anything inferred rather than found.

## Format

Markdown in chat. Return a file path as well if the caller asks for a file.

## Never in the output

- Prices, costs, rate cards, deal terms, or anything internal to how the deal
  is bought and sold.
- Performance grades or renewal judgements.
- Words for the creator to read aloud. This is connection material, not ad copy.
