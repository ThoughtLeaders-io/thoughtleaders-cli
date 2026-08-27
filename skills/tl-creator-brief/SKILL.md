---
name: tl-creator-brief
tl-blurb: creator self-reference profile, then connections to a brand
description: >
  Two things, for one YouTube creator and one brand. First, build a profile of
  the creator out of the places they talk about THEMSELVES in their own
  transcripts: their history, their work, how they learn, their habits and
  tastes, the offhand personal detail. Not their topic. Second, find the real
  connections between that profile and what a named brand offers. Takes no view
  on whether the creator is booked, pitched or merely being researched, and
  never asks. Triggers: "creator profile", "what do we know about [creator]",
  "find self references", "creator brand connection", "connections between
  [creator] and [brand]", "why this creator for [brand]", "personal angle for
  [channel]", "creator brief", "/tl-creator-brief".
---

# Creator Connections

Two outputs, in this order, and nothing else:

1. **The creator profile.** Every place the creator talks about themselves
   rather than about their subject. An offhand personal detail is the find. Their
   opinion on their own topic is not.
2. **The brand connections.** Where that profile overlaps with what a named
   brand offers, and what could be built on the overlap.

**One creator, one brand per run.** Batching is the caller's job, one line in
their own prompt or routine.

Read `references/code-reuse.md` before running anything.

## Step 1: resolve, then ask once

**Resolve to IDs. This step ends with a confirmed set of brand IDs and a
confirmed set of channel IDs, and everything downstream keys on those, never on
a name.** Both are sets, not single values:

- Brand: `tl whoami --json` settles it for a single-brand user. Otherwise
  `tl brands find` (never fuzzy-match, never `ILIKE`). Record the Postgres `id`
  from the brand row, which is what sponsored mentions key on.
- **Rebrands return more than one ID.** Earlier reads live under the old brand.
  Resolve former names and carry every ID forward together.
- Channel: `tl channels find`.
- **Interview, clips and localized sister channels (`- Spanish`, `- Deutsch`)
  are separate channels with separate audiences.** Resolve each, and confirm
  which are in scope before searching them.
- **Tie-break.** `tl channels find` routinely returns several matches and errors
  rather than choosing. Never auto-pick. Prefer an exact handle or URL match;
  otherwise put the top five (name, handle, subscribers, last upload) into the
  question batch.

**Plan.** The same `tl whoami --json` returns `organization.plan`; read it from
that call rather than making a second one. The tier gates whose data is readable:
`Intelligence` and above reach beyond the caller's own organisation, which is what
Step 3 needs on a channel they do not own and Step 4 on a brand that is not
theirs. Check it here so the skill does not build a corpus it cannot read.

- **`Intelligence` or `Superuser`.** Everything here is available. Proceed.
- **A known lower tier, currently `free` or `pro`.** Do not build a corpus that
  cannot be read. Name the tier, and carry the alternatives into the question
  batch below rather than asking separately: a channel the caller's own
  organisation owns is still readable, their own brand's reads are still
  readable, and brand-input options 2 and 3 need no cross-organisation read at
  all.
- **An unrecognised value.** Name it and continue. Tier names change, and a stale
  list in this file is not a reason to refuse a run.

**Ask once.** One consolidated prompt via whatever the host provides, a
structured question tool where one exists (`AskUserQuestion` in Claude Code),
otherwise a single message. Never drip questions, and never call a host-specific
tool by name without checking it exists.

1. **How to understand the brand.** Three options, and the answer is never
   assumed. See `references/brand-input.md`.
2. **Any channel tie-break** left over from the resolve step.
3. **What they already know about the creator personally.** "Nothing" is fine,
   Step 3 finds it.
4. **Only on a known lower tier**, which of the still-available paths they want,
   per the plan check above. Asked here, in the same prompt, never as a follow-up.

## Step 2: who is the creator, and what kind of channel is this

Before any transcript is touched. Three queries, and they give the transcript
search a target instead of a fishing licence.

```bash
cd <this skill>/scripts && python3 channel_profile.py --channel <channel_id>
```

Returns the channel's own about text, the platform's generated profile of it,
subscriber and upload counts, and the 20 most recent titles with durations.

**This step is not done until you have the host's name, or a finding that the
channel has no identifiable host.** The name is what makes the transcript scan
attributable, not background colour, so it is the output of this step.

- **A long profile can still name nobody**, so length is not the test.
  `identity_is_thin` reports short OR nameless, and either way:
- **run one web search**, of the form `who is <channel name>`, and one only. On a
  well known channel this returns the framing in a sentence, for example that a
  show is hosted by a named entrepreneur who founded a particular company. One
  sentence of framing does more for the search than the transcripts can.
- **Detect the channel format** from that material: interview show, solo
  talking head, faceless narrated or animated, multi-host, or reaction. The five
  formats and how far each can be trusted are in `references/evidence-rules.md`.
- **Format is per video, not only per channel.** One channel mixes them: a solo
  channel runs reaction episodes, an interview show posts monologues. Read the
  sampled titles for per-video formats too, since a title of the form "X Reacts
  to Y" marks a reaction episode whatever the channel usually does, and carry
  those per-video formats into Step 3. A video's own format decides the bucket
  for passages from it, and the channel's format is only the fallback.
- **If the format cannot support self-reference analysis, stop here** and return
  an empty creator profile with the detected format and the reason, per that
  same file. Do not continue into the transcript steps to produce something.

## Step 3: find the self-references

**Cap the corpus first.** Never scan a whole back catalogue.

```bash
python3 build_corpus.py --channel <channel_id> --max 40 --strategy spread
```

`spread` is the default and the right one here: it takes the most viewed upload
from each of 40 equal slices of the channel's whole history, so the sample is
neither all recent nor all old. The offhand personal detail is as likely to sit
in a five year old video as in last week's. `recent` and `top-views` exist for
callers who want them. The script reports what it left out; say so in the
output.

**Machine filter, then judge.** The filter is plain pattern matching, no model
involved, and it exists to cut a whole back catalogue of speech down to the
passages worth a human-grade read.

```bash
python3 build_corpus.py --channel <channel_id> --max 40 --strategy spread \
  | python3 selftalk_scan.py --host-terms "<distinctive facts about the host>"
```

**Passing the terms.** `--host-terms` takes facts distinctive to the host, their
surname, companies, funds, a named former role. Never generic possessives like
"my podcast" or "my company": anyone speaking can say those, so they discriminate
nothing and pull in a second voice. On a solo channel the anchor barely fires and
a low count there is expected, not a fault. Add `--domain-terms team,squad,roster`
on a games or sport channel, where "my team" is an object in the video's subject
matter rather than a fact about the speaker.

Candidates come back carrying their video, timestamp and link, so no separate
timestamping pass is needed.

**Fan out helper agents**, one per roughly 50 passages and never fewer than
four. How many passages get judged is what limits the profile, so if the pool
grows, add agents rather than tightening the caps. Leave `--max-per-video` at its
default.

**Deal the list out round-robin**, one passage to each agent in turn, rather than
cutting it into blocks. It arrives sorted with the best-attributed passages
first, so slicing hands all the strong material to the first agent and leaves the
rest with nothing but half-signals.

**If the host cannot spawn helper agents**, run the same batches one after
another, discarding each batch's raw text before the next so it does not
accumulate. Same sweep, same brief, just sequential.

**Never read transcripts in the main conversation.** The main conversation only
ever needs the findings.

Each agent gets the brief in `references/helper-brief.md`, with the placeholders
filled in from Step 2, and nothing else. **The brand is never named to them**,
which is why casting wide happens here and narrowing happens in Step 5.

Merge the returns, drop duplicates, and write the creator profile. **The
attribution bucket travels with every quote** into the output, so an unconfirmed
quote is never presented as a confirmed one.

## Step 4: understand the brand

Independent of Steps 2 and 3, so it can run alongside them. Run only the option
the user picked in Step 1. Full spec, including the past-sponsorships script and
both of its query paths: `references/brand-input.md`.

**There is no minimum number of reads.** The step exists to learn what the
product is, so one read that describes it does the job. There is no performance
ranking here either: which past read did well is a different question, and this
skill does not ask it.

## Step 5: find the connections

Now, and only now, put the profile next to the brand. For each connection: the
creator's own words it rests on, with a timestamped link, what the brand offers
that meets them, and the concrete thing that could be built on it. A personal
detail that happens to echo something the product already has is a connection;
the specific thing to build on that echo is what the reader is owed. Full shape:
`references/output-spec.md`.

**Keywords may confirm, never discover.** Where the profile has already
surfaced something that looks like a moment the product speaks to, one narrow
keyword probe to pin that moment down and timestamp it is fine. A keyword search
is never allowed to decide what gets looked for: it can only find what someone
already thought to name, and the connection worth having is the one nobody
thought of. That is also why Step 3 runs without knowing the brand.

If the profile is too thin to connect to the brand, the answer is **more of the
same wide sweep, never a narrower one**: raise `--max` and re-run Step 3 over
more of the catalogue. The filter has no idea what the brand is, so widening it
cannot bias it.

## Step 6: output

**Write the brief to a markdown file and return the path.** Not a chat message:
the brief is made to be picked up later and forwarded. Two files, named from the
resolved IDs so a re-run overwrites its own output:

- `creator-briefs/<channel_id>-profile.md`, the creator profile alone.
- `creator-briefs/<channel_id>-<brand_id>-brief.md`, the profile then the
  connections.

The profile is written separately because it is brand-independent, and the next
brand reuses it instead of repeating Steps 2 and 3. Look for it before Step 2 and
offer it, never reuse it silently.

Full spec, including the section order and the sweep-ran-dry line every run
carries: `references/output-spec.md`.

## Guardrails

- **Read-only.** Nothing is sent to anyone. Output comes back for review.
- **No prices, costs, rate cards or deal terms in the output**, ever. This is
  built to be forwarded.
- **Not ad copy.** The output is connection material. Nobody is handed words to
  read aloud.
- **No fabricated performance claims.** What was said on camera is observable.
  What an ad would do is not.
- **An empty answer is a real answer.** A stated "this channel format does not
  support self-reference profiling" is correct and useful. An invented profile
  is neither.
