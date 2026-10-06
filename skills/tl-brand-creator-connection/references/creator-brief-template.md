# The creator brief: template and rules

The second deliverable of a CONNECT run, written only when the user asked
for a version to send to the creator. It tells the creator what the brand
wants said and which of their own moments already say it, and it is attached
to an email as it is. The example brand and creator are invented.

## Layout

| The brand sent | The brief is | Input |
|---|---|---|
| Its own brief or talking points | the brand's document mirrored: headings, order and words kept, a For you block under each talking point a gem backs | `brand_brief` |
| Only the promoting line | the six sections built from the gems, as for Nothing; the promoting line opens The creative ask | `promoting`, `supplied: false` |
| Nothing | the six sections, built from the gems and the brand research | `supplied: false` |

### Mirrored

Nothing of the brand's is reworded, reordered or dropped; nothing of ours is
added outside the For you blocks (a heading mark or bullet may be restored
where the paste lost it). Under each talking point a gem backs, right after
the line:

```markdown
- Fresh roasted, shipped within two days

<!-- for-you -->
**For you: Your first coffee is already on camera**

Every build video opens with you grinding beans before you touch a tool.
Make that the segment: the Northwind bag arrives, you read the roast date out
loud, and the first grind of the morning is theirs.

> I have got this whole ritual now where the first thing I do before I touch
> a tool is grind the beans
> [Marta Builds, 2026-03-04](https://www.youtube.com/watch?v=EXAMPLE1&t=214s)
<!-- /for-you -->
```

A talking point no gem backs stays as written with nothing under it. A gem
that leads to the product but to none of the brand's lines is a creative
point: at most two, each its own block after the brand's last talking point.
The brand's requirements, don'ts and approval steps stay where the brand put
them; the defaults below are not added. The Must not list holds for our
words only.

### Six sections, in this order

| Section | Holds | Source |
|---|---|---|
| `## Who is <brand>` | two to four sentences: what the product is, who it is for, how it is used | the map's About-brand paragraph; the promoting line when it names a product |
| `## The creative ask` | what the ad is for and what to promote; the format when stated | the promoting line verbatim, then one or two sentences from the map's thesis |
| `## Key talking points` | one `### ` per point: our heading and body built on a moment of the creator's own, their quote as a `>` block with its timestamped link on a `>` continuation line, then, when the brand sent talking points, `**From <brand>'s brief:**` and the brand's lines that point covers, verbatim. When the brand sent talking points, one closing `### Also from <brand>` with the brand's lines no moment carries, verbatim | the brand's lines say what must be covered; the gems say what only this creator can say |
| `## Requirements` | the brand's mandatories, verbatim | the talking points, else the default below |
| `## Don't do` | the brand's don'ts verbatim, then the map's craft Do-not lines | the talking points, then the map |
| `## Creative approval process` | how the draft is reviewed and who says go | the talking points, else the default below |

An intro line before the first heading may name the creator, say what this
is, and say that every quote links to the second it was said.

## Rules

- Sort the brand's lines before writing: a mandatory under Requirements, a
  prohibition under Don't do, an approval step under Creative approval
  process, each once and verbatim. Only what the creator should say or show
  becomes a `###`. Nothing the brand wrote is dropped, reworded or softened.
- Start from the gems, not the brand's list. Read the map's thesis and cards
  and the whole ledger (family, origin, habits, tastes, work history all
  count; the page's two-thin-card cap does not apply), and pick the gems: a
  story with its people and details, a turning point, a thing they built, a
  habit kept for years, how they describe themselves. For each, ask what it
  lets this creator say about the product that no other creator could.
  Then place each brand line under the point whose gem backs it best.
- A moment is eligible when its fact is `confirmed` and `last_seen` is
  inside the last 24 months. An older or `ended` moment is background with
  its year, never a talking point. A video the channel made about a topic
  is not a moment of the creator's own.
- Pick the moment that backs the brand's line, not just a true one: would a
  viewer who heard it accept the brand's line as following from it? One
  sentence of the body makes the step from the moment to the product. A
  comparison ("you got better with practice, and so does the pan") is not
  that step. A research claim in the brand's brief goes under the point whose
  moment backs it.
- Each point gets a different moment. At least four points when the ledger
  holds four eligible moments; fewer when the brand wrote fewer lines than
  that plus two creative points. `### Also from <brand>` holds at most half
  of the brand's talking-point lines; when no eligible moment exists it holds
  everything and says "no natural moment".
- Write each point from its gem: the heading names it; two to four sentences
  say what they tell their audience and show on camera, using the moment's
  own specifics. The quote follows as proof; it never stands in for the
  point. Second person, the creator's register, what to cover, never the
  words to read.
- On a re-book, read the creator's past reads for the brand first
  (`brand-tl.json` `this_channel_reads`) and build on moments those reads did
  not use. The checker refuses a moment within 45 seconds of one of those
  reads, or of the brand's name in a sponsored video.
- Every quote is the creator's own words, verbatim, with its `&t=` link
  inside the blockquote. The checker refuses a quote that is neither a
  verified ledger fact nor one the map argued, and a link to another video
  or timestamp.
- The brief builds the brand up; it never sets the brand against another
  product, even one the creator uses.

**Must not:** prices, costs, rate cards, deal terms, performance grades;
scripts, full reads, alternate versions, CTA wording (the brand owns the
CTA); channel or brand ids, fact ids, filenames, the words ledger, probe,
strong, thin, precedent, sponsorship pattern, ad-read sample, or any
provenance label; other creators' names, reads or channels; anything from a
withheld tier (`children`, `location`, `clinical` below three videos);
anything written for the account manager (thesis hedges, "Where this could
go wrong", the honesty strip).

## When the brand sent no brief

Every point is a creative point from a gem, same bar as above. Product facts
come from the map's About-brand section only. No `**From <brand>'s brief:**`
and no `### Also from <brand>`; the checker refuses both. The creative ask
comes from the map's thesis, the promoting line first when given.
Requirements and Creative approval process use the defaults; Don't do holds
the map's craft don'ts. The render carries the label "built from the
creator's own material; no brand talking points supplied". A promoting line
alone is not a brand brief: no From block.

## ThoughtLeaders defaults

**Requirements:** record a new integration for each sponsored video, never
reuse a recording; show and use the product on camera while talking about
it; the CTA, tracking link and any code go at the top of the description,
above "Show more", and in the pinned comment.

**Creative approval process:** send the draft script or cut to your
ThoughtLeaders contact before publishing; the brand returns approval or
changes within three business days; publish only after written approval,
then share the live link.

## Frontmatter

```yaml
---
schema: tl-creator-brief/v1
channel_name: "Marta Builds"
brand_name: "Northwind Coffee"
talking_points_supplied: true
---
```

Nothing else. `talking_points_supplied` agrees with the input file's
`supplied`.

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

### Your first coffee is already on camera

Every build video opens with you grinding beans before you touch a tool.
Make that the segment: the Northwind bag arrives, you read the roast date out
loud, and the first grind of the morning is theirs. Your viewers already know
the ritual, so they will notice the bag before you name it.

> I have got this whole ritual now where the first thing I do before I touch
> a tool is grind the beans
> [Marta Builds, 2026-03-04](https://www.youtube.com/watch?v=EXAMPLE1&t=214s)

**From Northwind Coffee's brief:**

- Fresh roasted, shipped within two days

### The Sunday pot for the crew

Every big build ends with the neighbours who helped you sitting on the
tailgate while you make them coffee. That is the subscription's whole case,
told by you: the bag that turns up every month is the reason the Sunday pot
never runs dry. Film one of those Sundays, the crew and the pot, and say in
your own words why you stopped buying coffee the week you run out.

> whoever turns up to help on a sunday gets the good coffee that's the deal
> [Marta Builds, 2026-05-17](https://www.youtube.com/watch?v=EXAMPLE2&t=1290s)

**From Northwind Coffee's brief:**

- the new monthly subscription

### Also from Northwind Coffee

- Tasting notes printed on every bag

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

The check and render commands are in SKILL.md, CONNECT step 3. The render is
named `<brand>-creator-brief-<creator>.html`, by names, because it is an
attachment.
