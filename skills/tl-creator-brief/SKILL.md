---
name: tl-creator-brief
tl-blurb: creator-to-brand connection research and custom brief
description: >
  Find and evidence the connection between one YouTube creator and one brand,
  then shape it for the moment it is needed: a fit verdict before anyone reaches
  out, material to win the creator over, or a custom brief once the deal is
  signed. Mines the creator's own transcripts and their audience's comments for
  verbatim evidence, finds moments where they already do on camera what the
  product enables, and ranks which framings their audience rewards. Use at any
  stage of a creator-brand pairing, booked or not. Triggers: "is [creator] a fit
  for [brand]", "creator brand connection", "why this creator for [brand]",
  "custom brief for [creator]", "tailor our talking points to [channel]",
  "talking points for [creator]", "personalize the ad for [channel]", "how
  should [creator] pitch our product", "creator brief", "/tl-creator-brief".
---

# Creator Brief (creator-to-brand connection research)

Test, and where it holds prove, one claim: this creator has a real connection to
this product, in their own recorded words, and is a natural evangelist rather
than an ad-reader. The evidence is theirs, not ours.

**One brand, one creator per run.** Batching is the caller's job, one line in
their own prompt or routine.

**Three moments, same research, different framing.** Ask which applies, never
infer it, and never assume a booking:

1. **Research**: is the fit genuine, before anyone reaches out. A negative
   answer is a valid and useful result.
2. **Pitch**: material to win the creator over, or to argue for a larger spend.
3. **Booked**: the deal is signed and the creator needs a brief.

Read `references/code-reuse.md` before running anything. It lists what already
exists in this repo and must not be rewritten.

## Step 1: resolve, then ask once

**Plan.** This reads brand records and transcripts, which need Intelligence or
above. Check `organization.plan` in `tl whoami --json`. Proceed on `Intelligence`
or `Superuser`. Stop only on a known lower tier, naming the plan and what it
needs. On any other value, note the uncertainty and continue: the first query's
error is the source of truth, not a stale plan list.

**Resolve to IDs. This step ends with a confirmed set of brand IDs and a
confirmed set of channel IDs, and everything downstream keys on those, never on
a name.** Both are sets, not single values:

- Brand: `tl whoami --json` settles it for a single-brand user. Otherwise
  `tl brands find` (never fuzzy-match, never `ILIKE`). Record the Postgres `id`
  from the brand row, which is what sponsored mentions key on.
- **Rebrands return more than one ID.** Earlier reads live under the old brand.
  Resolve former names and carry every ID forward together.
- Channel: `resolve_channel.resolve(ref)` (see `references/code-reuse.md`).
- **Interview, clips and localized sister channels (`- Spanish`, `- Deutsch`)
  are separate channels with separate audiences.** Resolve each, and confirm
  which are in scope before searching them.
- **Tie-break.** `tl channels find` routinely returns several matches and errors
  rather than choosing. Never auto-pick. Prefer an exact handle or URL match;
  otherwise put the top five (name, handle, subscribers, last upload) into the
  question batch.

**Ask once.** One consolidated prompt via whatever the host provides, a
structured question tool where one exists (`AskUserQuestion` in Claude Code),
otherwise a single message. Never drip questions, and never call a host-specific
tool by name without checking it exists.

1. **Which moment**: research, pitch or booked.
2. **What drives the direction.** See `references/direction-sources.md`. Changes
   what Lane A does, so it cannot be assumed.
3. **Current offer and CTA** (pitch and booked). "Not settled yet" is a valid
   answer; Lane A then reports the CTA currently in use.
4. **Placement** (booked, optional): a specific upcoming video or topic, or open.
5. **What they know about the creator personally.** "Nothing" is fine, Lane B
   finds it.
6. **Hard mandatories** (booked): length, must-say claims, compliance limits.

## Step 2: research lanes

Lanes run as subagents so raw transcripts never enter the main conversation.
Each returns a digest plus pointers, nothing raw.

**Count and order.** One agent per lane, times the number of in-scope channels.
The number follows from Step 1, it is not fixed. The lanes are not independent:

- **A** and **B** have no dependencies. Start both immediately.
- **C** needs A's read skeleton and the keyword work. Start when A returns.
- **D** scores framings, so it needs C's framings. Start when C returns.

**Models.** D reads numbers and reports them: smallest, fastest model the host
has. A, B and C judge what speech means: most capable model available.

**Cost.** Query-heavy. Say so up front on a large back catalogue and offer to
narrow the window first.

**A. Brand direction**: the read skeleton, per the source the user picked.
Full spec in `references/direction-sources.md`.

**B. Creator on themselves**: verbatim self-referential quotes: business, team,
how they work and learn, origin story, beliefs, hobbies, life details. The
strongest bridges are often unrelated to the category (the dog, the chess habit).

**C. Creator on the category, and the audience on it**: every moment they touch
the brand's problem space.

- Discovery goes through `tl-keyword-research` whenever the problem space is a
  topic rather than a curated tag. Never hand-compose keyword sets.
- Screen the hits for figurative use, twice. See `references/evidence-rules.md`.
- The prize is a **format precedent**: a moment where they already do or
  advocate, on camera, what the product enables. One genuine precedent beats ten
  adjacent quotes.
- Read the comment sections of the videos this lane surfaces, and only those.
  An audience asking the creator for exactly this product is the strongest
  evidence there is.
- Run the competitor check (`references/evidence-rules.md`).

**D. Audience resonance**: `scripts/resonance.py`, fed the `resolve_channel`
output:

```bash
python3 -c "import json, resolve_channel as rc; print(json.dumps(rc.resolve('<ref>'), default=str))" \
  | python3 <this skill>/scripts/resonance.py
```

Cohorts are built by count, the 8 nearest-in-age uploads of the same format, not
by calendar window: a channel posting twice a month leaves fixed recent windows
with 2 or 3 uploads, so its newest videos score against nothing. Never share a
baseline across formats. `unscoreable` is never silently dropped.

All evidence handling, quoting and timestamping: `references/evidence-rules.md`.

## Step 3: deliver in two stages

Stage 1 in chat as soon as B, C and D return. Stage 2 as a markdown file with
the path returned. Full spec, section order and the affordability rule:
`references/output-spec.md`.

## Guardrails

- **Read-only.** Nothing is sent to anyone. Output comes back for review.
- **Never script the mouth.** The sample read demonstrates fit; the document must
  say the creator has creative freedom over every spoken word.
- **No economics in the document.** No prices, deal terms or other creators'
  terms. It is built to be forwarded. The Stage 1 affordability flag stays in
  chat.
- **No fabricated performance claims.** "This framing ran 3x the channel's
  baseline" is observable. "This ad will convert" is not.
