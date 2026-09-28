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

## Two layouts, one rule: the creator's gems come first

Which layout the brief takes depends on what the brand sent. In both, every
talking point written for the creator starts from one of their gems and
leads to the brand.

| The brand sent | The brief is | Input file |
|---|---|---|
| Its own brief or talking points, pasted or as a file | **The brand's brief, mirrored**: their document, headings, order and words kept, with a For you block under each talking point a gem backs | `brand_brief` holds the text as pasted |
| Only the line on what it is promoting | **The six sections**, every point a creative point under the promoting line | `promoting`, no `brand_brief` |
| Nothing | **The six sections**, the fallback, built from the gems and the brand research (see "When the brand sent no brief") | `supplied: false` |

The checker picks the layout from the input file, the same way.

## The brand's brief, mirrored

The page is the brand's own document. Nothing of theirs is reworded,
reordered or dropped, and nothing of ours is added outside the For you
blocks: no intro, no extra headings, no default sections. A heading mark or
a bullet may be added where the paste lost its formatting; a word may not
change. The checker compares the page, For you blocks removed, word for
word with `brand_brief` and names where it drifts.

Under each of the brand's talking points (what the creator should say or
show, not a requirement, a don't or an approval step) that a gem backs,
write one For you block, right after that line:

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

- The heading and the body are ours, built from the gem the way the rules
  below say. The quote is the proof. The block never repeats the brand's
  line, and its heading is never that line.
- A talking point no gem backs stays as the brand wrote it, with nothing
  under it. Never force a gem onto a line to fill the space.
- A gem that leads to the product but to none of the brand's lines is a
  creative point: at most two, each in its own For you block right after
  the brand's last talking point.
- Every block gets a different gem, and there are at least four blocks when
  the ledger holds four confirmed moments (fewer when the brand wrote fewer
  talking points than that, plus the two creative ones).
- The brand's requirements, don'ts and approval steps stay where the brand
  put them. The ThoughtLeaders defaults are not added.
- The Must not list below holds for our words in the blocks. The brand's
  own words are theirs, so a price or a CTA the brand wrote stays.

## The fallback: six sections, in this order

Used when the brand sent no brief of its own: only a promoting line, or
nothing. The renderer requires all six, in this order, under these
headings. The first names the brand.

| Section | Holds | Source |
|---|---|---|
| `## Who is <brand>` | Two to four sentences a creator can read cold: what the product is, who it is for, how it is used | The connections page's About-brand paragraph, tightened. The user's "promoting" line when it adds a product name |
| `## The creative ask` | What this ad is for and what to promote; the format when the brand stated one | The user's "promoting" line, verbatim, then one or two sentences of framing from the connection map's thesis |
| `## Key talking points` | One `### ` per talking point written for this creator: the heading and the body are ours, built on a moment of their own and aimed at their audience; then their quote as a `>` block with its timestamped link on a `>` continuation line; then `**From <brand>'s brief:**` and the brand's line or lines that point covers, verbatim (for a creative point, the brand's promoting line). One closing `### Also from <brand>` holds the brand's talking-point lines no moment carries, verbatim | The user's talking points say what must be covered. The creator's gems, read from the whole ledger and the map's cards, say what only this creator can say about the product, and how they cover what the brand asked for |
| `## Requirements` | The brand's mandatories, verbatim, as bullets | Whatever the pasted talking points state as required (deliverables, on-screen elements, timing). With none, the ThoughtLeaders defaults below |
| `## Don't do` | The brand's don'ts verbatim, then craft don'ts from the connections page | Whatever the pasted talking points forbid. The page's Do-not lines, only those about craft |
| `## Creative approval process` | How the draft gets reviewed and who says go | The pasted talking points when they describe one, otherwise the default below |

An intro line before the first heading is allowed: the creator's first name,
what this is, and that every quote links to the second it was said.

## Rules

The rules on gems, quotes and what never goes on the page hold in both
layouts, and in the mirrored one they apply to the For you blocks. The rules
on sorting the brand's lines, `**From <brand>'s brief:**` and `### Also from
<brand>` belong to the six sections.

**Must**

- Every quote is the creator's own words, verbatim, with its `&t=` link
  inside the blockquote. The checker refuses a quote that is neither a
  verified ledger fact nor one the connections map argued, and a link to any
  other video or timestamp than the one that fact or card carries.
- Sort the supplied lines before writing: a mandatory goes under
  Requirements, a prohibition under Don't do, an approval step under
  Creative approval process, each once and verbatim. Only what the creator
  should say or show becomes a `###`. A pasted full brief is sorted, never
  repeated.
- Start from the creator's gems, not from the brand's list. Before writing,
  read the connections map's thesis and cards and the whole ledger, and pick
  out the gems: what this creator has said about themselves, such as a story
  with its people and details, a turning point, a thing they built, a habit
  they have kept for years, or how they describe themselves ("a home cooking
  nerd"). The ledger was built brand-blind and this step never changes it:
  it only chooses, among the gems already there, the ones that best fit
  this brand. For each gem, ask what it lets this creator say about
  the product that no other creator could. Those answers are the talking
  points. Then place each of the brand's lines under the point whose gem
  backs it best.
- A gem can carry a point the brand did not write. When a gem leads
  naturally to the product but to none of the brand's lines, write it as a
  creative talking point, with the brand's promoting line (the one in The
  creative ask) under `**From <brand>'s brief:**`. These are often the
  strongest points in the brief: the brand's lines say what every creator
  must cover, the creative points say what only this one can.
- The creator's talking points are written for them, not copied from the
  brand. Write each point from its gem: the heading names it ("Your first coffee is
  already on camera"), and two to four sentences say what they tell their
  audience and show on camera, using the moment's own specifics (the
  person, the object, the creator's own joke) so the point could not be
  pasted into another creator's brief. The quote follows as the proof that
  it is theirs; it never stands in for the point.
- Pick the moment that best backs up the brand's line, not just a true one.
  The best moment is the creator already living what the brand claims (the
  creator who grinds beans on camera every morning, for a brand whose line
  is about the first cup). Test it: would a viewer who heard the moment
  accept the brand's line as following from it? If not, choose another
  moment, or leave the line in the closing list. One sentence of the body
  makes that step from the moment to the product; a story set beside the
  product with no step between them reads as nonsense, however true it is.
  A comparison is not that step either: "you got better with practice, and
  so does the pan" sets a moment beside the product and calls it a link.
- The brand's evidence needs backing too. A research point, study or claim
  in the brand's brief goes under the talking point whose moment backs it
  (the creator who says they are careful about what they read is the one to
  carry the study), not left for the closing list when a moment fits.
- On a re-book, do not repeat the last read. When the TL data lane's
  sponsored reads show this creator already ran a read for the brand, read
  it first and build on moments that read did not use. A moment said inside
  that read is the ad talking, not a gem: the checker reads the run's
  transcripts and refuses a moment in a video the brand sponsored when the
  brand's name sits within 45 seconds of it.
- Under every point, `**From <brand>'s brief:**` and the brand's line or
  lines it covers, verbatim, or the promoting line for a creative point.
  Group freely: one personal point can carry several of the brand's lines.
  The heading is never the brand's own line.
- Read the whole ledger, not only the map's cards: family, origin, habits,
  tastes and work history all count, and the page's two-thin-card cap does
  not apply here. A video the channel made about a topic is not a moment of
  the creator's own. Each point gets a different moment, and there are at
  least four points when the ledger holds four confirmed moments.
- What no moment carries goes, verbatim, in one closing `### Also from
  <brand>`: at most half of the brand's talking-point lines. When the ledger
  has no confirmed moment at all (a faceless or scripted channel), that list
  holds everything and says "no natural moment". The checker enforces all
  of this and names unused moments to try.
- A requirement, don't or approval step the brand wrote into its talking
  points appears verbatim in its section. Nothing the brand wrote is dropped,
  reworded or softened.
- Second person, to the creator, in the creator's register. A talking point
  says what to cover and how it is theirs, never the words to read.
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

## When the brand sent no brief

The user said yes to a creator brief but had no talking points to paste
(the input file's `supplied` is false). The six sections stay, and the
creator's gems lead the whole brief:

- Every talking point is a creative point: it starts from one of the
  creator's gems and leads to the product, the way a creative point does
  when there is a brief. Same bar: one gem per point, at least four points
  when the ledger holds four confirmed moments, and the body uses the gem's
  own details.
- What the product is and does comes from the connections page's About
  brand section, the brand research. A product claim in our text is one
  that section makes, never a guess.
- No `**From <brand>'s brief:**` label and no `### Also from <brand>`:
  nothing from the brand exists to quote. The checker refuses both.
- Who is <brand> comes from About brand. The creative ask comes from the
  connections page's Thesis, the promoting line first when the user gave
  one. Requirements and Creative approval process use the ThoughtLeaders
  defaults below. Don't do holds only the page's craft don'ts.
- The rendered brief carries the label "built from the creator's own
  material; no brand talking points supplied", so the creator and the
  account manager both know.

When the user gave only the promoting line and no talking points, the brief
counts as supplied: every point is a creative point under that line.

## ThoughtLeaders defaults

Used when the pasted talking points say nothing for the section. The user is
never asked for these separately.

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
