# The creator brief: template and rules

The creator brief is the second deliverable of a CONNECT run, produced only
when the user asked for a version they can send to the creator. The
connections page argues the fit to the account manager. This file tells the
creator what the brand wants said and which of their own moments already say
it. It is written to be attached to an email as it is.

It is condensed from the talking-points documents ThoughtLeaders already
sends creators (the standard talking-points template, the brand-authored
briefs with a do-and-do-not list, and the brief format with a checklist
approval flow). The example brand and creator below are invented.

## The six sections, in this order

The renderer requires all six, in this order, under these headings. The
first names the brand.

| Section | Holds | Source |
|---|---|---|
| `## Who is <brand>` | Two to four sentences a creator can read cold: what the product is, who it is for, how it is used | The connections page's About-brand paragraph, tightened. The user's "promoting" line when it adds a product name |
| `## The creative ask` | What this ad is for and what to promote; the format when the brand stated one | The user's "promoting" line, verbatim, then one or two sentences of framing from the connection map's thesis |
| `## Key talking points` | One `### ` per brand point. Under each: the creator's own quote as a `>` block with its timestamped link on a `>` continuation line, one line on how that moment meets the product, one "you could" suggestion | The user's talking points (each `###` names one verbatim). The connection map's cards for the moments. The ledger, read whole, when a point has no card |
| `## Requirements` | The brand's mandatories, verbatim, as bullets | The user's requirements only. With none supplied, the ThoughtLeaders defaults below |
| `## Don't do` | The brand's don'ts verbatim, then craft don'ts from the connections page | The user's don'ts. The page's Do-not lines, only those about craft |
| `## Creative approval process` | How the draft gets reviewed and who says go | The user's approval text verbatim, or the default below |

An intro line before the first heading is allowed: the creator's first name,
what this is, and that every quote links to the second it was said.

## Rules

**Must**

- Every quote is the creator's own words, verbatim, with its `&t=` link
  inside the blockquote. The checker refuses a quote that is neither a
  verified ledger fact nor one the connections map argued.
- Every supplied talking point appears verbatim as (or inside) one `###`,
  either carried by a quote or followed by a line that says "no natural
  moment" and what to do instead. Nothing the brand asked for is dropped
  silently, and nothing is reworded.
- Every supplied requirement and don't appears verbatim in its section.
- Second person, to the creator, in the creator's register. The "you could"
  line is a suggestion, never a script.
- Every creator-facing sentence follows one pattern: what the brand wants,
  what the creator has said, the idea that joins them.
- The brief builds the brand up. It never sets the brand against another
  product, app or game, even one the creator plays. A creator's quote may
  name another game; our text does not.

**Must not**

- Prices, costs, rate cards, deal terms, or performance grades.
- Scripts, full reads, alternate versions, or CTA wording. The brand owns
  the call to action; the brief may say the brand will supply it.
- Channel or brand ids, fact ids, filenames, the words ledger, probe,
  strong, thin, precedent, sponsorship pattern, ad-read sample, or any
  provenance label. Nothing that names the connections page.
- Other creators' names, ad reads or channels.
- Anything from a withheld sensitivity tier (`children`, `location`,
  `clinical` below three videos), whatever the section.
- Anything written for the account manager's eyes: the thesis's hedges, the
  "Where this could go wrong" section, the honesty strip.

## ThoughtLeaders defaults

Used only when the brand supplied nothing for the section. The header of an
unsupplied brief says so.

**Requirements, default**

- Please record a new integration for each sponsored video; do not reuse a
  previous recording.
- Show and use the product on camera while you talk about it.
- The call to action, the tracking link and any code the brand supplies go
  at the very top of the description, above "Show more", and in the pinned
  comment.

**Creative approval process, default**

Send your draft script or cut to your ThoughtLeaders contact before you
publish. The brand reviews it and comes back with approval or changes within
three business days. Publish only after written approval, then share the
live link with your contact.

## Frontmatter

```yaml
---
schema: tl-creator-brief/v1
channel_name: "Marta Builds"
brand_name: "Northwind Coffee"
talking_points_supplied: true
---
```

Nothing else. No ids, no file names. `talking_points_supplied` must agree
with the input file's `supplied`.

## Example, invented

```markdown
---
schema: tl-creator-brief/v1
channel_name: "Marta Builds"
brand_name: "Northwind Coffee"
talking_points_supplied: true
---

Marta, this is what Northwind Coffee would like covered, with the moments
from your own videos that already say it. Every quote links to the second
you said it.

## Who is Northwind Coffee

Northwind Coffee roasts single-origin beans in small batches and ships them
within two days of roasting. Most of its customers brew at home before work,
and the brand's whole pitch is that the first cup of the day should be the
best one.

## The creative ask

Northwind is promoting the new monthly subscription. One integration inside a
regular build video, as a segment of the video rather than a pause in it.

## Key talking points

### Fresh roasted, shipped within two days

> I have got this whole ritual now where the first thing I do before I touch
> a tool is grind the beans
> [Marta Builds, 2026-03-04](https://www.youtube.com/watch?v=EXAMPLE1&t=214s)

Your workshop morning already starts with coffee, on camera, before the
build. You could let that ritual be the segment: the bag arrives, the date on
it, the first grind.

### A subscription that fits how you actually drink it

No natural moment in your videos for this one. Worth saying straight: the
plan pauses and changes with a tap, and Northwind will send you the details
to show.

## Requirements

- Show the bag and the roast date on camera.
- Say the full name, Northwind Coffee, at least once.

## Don't do

- No health or energy claims.
- Do not read it like an ad break. It works as a segment of your build, in
  your own words.

## Creative approval process

Send your draft script or cut to your ThoughtLeaders contact before you
publish. Northwind reviews it and comes back with approval or changes within
three business days. Publish only after written approval, then share the
live link with your contact.
```

## Check and render

```bash
python3 <skill>/scripts/build_html.py --brief --check \
  --in <corpus>/creator-brief-<brand_id>.md \
  --facts tl-creator-profiles/<id>-facts.jsonl \
  --connections <corpus>/connections-<brand_id>.md \
  --input <corpus>/creator-brief-input-<brand_id>.json && \
python3 <skill>/scripts/build_html.py --brief \
  --in <corpus>/creator-brief-<brand_id>.md \
  --facts tl-creator-profiles/<id>-facts.jsonl \
  --connections <corpus>/connections-<brand_id>.md \
  --input <corpus>/creator-brief-input-<brand_id>.json
```

The render writes `tl-creator-profiles/<brand>-creator-brief-<creator>.html`
and its `.fragment.html` twin, named by names because the file is an
attachment, and prints both absolute paths.
