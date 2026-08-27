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
   rather than about their subject. A geography creator mentioning offhand that
   their favourite food is pizza is the find. Their view on borders is not.
2. **The brand connections.** Where that profile overlaps with what a named
   brand offers, and what could be built on the overlap.

**One creator, one brand per run.** Batching is the caller's job, one line in
their own prompt or routine.

**Booking is not this skill's business.** It never asks whether the creator is
booked, pitched or cold, and nothing it does changes based on the answer. Ad
copy, briefs, outreach and packaging are separate skills that sit on top of this
one. Keeping them out is what makes this one reusable.

Read `references/code-reuse.md` before running anything.

## Step 0: setup

**Plan.** This reads brand records and transcripts, which need Intelligence or
above. Check `organization.plan` in `tl whoami --json`. Proceed on `Intelligence`
or `Superuser`. Stop only on a known lower tier, naming the plan and what it
needs. On any other value, note the uncertainty and continue: the first query's
error is the source of truth, not a stale plan list.

**Helper agents.** Step 3 fans out to four of them. If the host cannot spawn
helper agents, run the four batches one after another instead, and discard each
batch's raw text before starting the next so it does not accumulate. Never read
transcripts in the main conversation: raw transcript text there is paid for
again on every later turn, which is the single largest cost in this skill.

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

**Ask once.** One consolidated prompt via whatever the host provides, a
structured question tool where one exists (`AskUserQuestion` in Claude Code),
otherwise a single message. Never drip questions, and never call a host-specific
tool by name without checking it exists.

1. **How to understand the brand.** Three options, and the answer is never
   assumed. See `references/brand-input.md`.
2. **Any channel tie-break** left over from the resolve step.
3. **What they already know about the creator personally.** "Nothing" is fine,
   Step 3 finds it.

## Step 2: who is the creator, and what kind of channel is this

Before any transcript is touched, because it costs almost nothing and it gives
the transcript search a target instead of a fishing licence.

```bash
cd <this skill>/scripts && python3 channel_profile.py --channel <channel_id>
```

Returns the channel's own about text, the platform's generated profile of it,
subscriber and upload counts, and the 20 most recent titles with durations.

- **If the profile text is thin or boilerplate, one web search**, of the form
  `who is <channel name>`, and one only. On a well known channel this returns
  the framing in a sentence, for example that a show is hosted by a named
  entrepreneur who founded a particular company. That framing makes the
  transcript search far more targeted and costs a fraction of discovering the
  same thing from transcripts.
- **Detect the channel format** from that material: interview show, solo
  talking head, faceless narrated or animated, or multi-host. The four formats
  and how far each can be trusted are in `references/evidence-rules.md`.
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

**Machine filter, then judge.** The filter is plain pattern matching, no model,
so it is effectively free, and it exists to cut the volume the model has to read
by roughly an order of magnitude.

```bash
python3 build_corpus.py --channel <channel_id> --max 40 --strategy spread \
  | python3 selftalk_scan.py
```

Candidates come back already carrying their video, timestamp and link, so no
separate timestamping pass is needed.

**Fan out four helper agents**, one per quarter of the candidate list. Each gets
this and nothing else:

> You are given a list of candidate lines from one YouTube channel's
> transcripts, each with a video id and a timestamp. Apply the self-reference
> test in `references/evidence-rules.md` to every line and return only the lines
> that pass all three parts of it. The channel format is `<format>`, so apply
> the attribution rule for that format; drop anything you cannot attribute to
> the channel's own host. For each line you keep, return the verbatim line, the
> video id, the timestamp, and one short phrase saying what it reveals about the
> creator. Return nothing else: no raw transcript, no commentary, no summary of
> the channel's topic. Do not search for further material beyond the list you
> were given.

**The helper agents are not told which brand this is for, and must not be.** A
helper that knows the brand filters to the brand without being asked, and the
pizza line never comes back. Casting wide happens here; narrowing to the brand
happens in Step 5.

Merge the four returns, drop duplicates, and write the creator profile.

## Step 4: understand the brand

Independent of Steps 2 and 3, so it can run alongside them. Run only the option
the user picked in Step 1. Full spec, including the past-sponsorships script and
the three-verified-reads floor: `references/brand-input.md`.

## Step 5: find the connections

Now, and only now, put the profile next to the brand. For each connection: the
creator's own words it rests on, with a timestamped link, and the concrete thing
that could be built on it. A creator who loves pizza and a brand whose in-app
scoring unit is called pies is a connection; real pizzas to users who hit a
hundred day streak on that creator's code is the thing built on it.

Where the profile suggests the creator already does on camera something the
product enables, one narrow extra probe for that moment is worth it. One probe,
capped, and only when the profile points at it.

## Step 6: output

The creator profile is its own clearly visible section and is never folded into
the brand connections. Full spec: `references/output-spec.md`.

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
