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

**Helper agents.** Step 3 fans out to as many as the passage pool needs, one per
roughly 50 passages and never fewer than four. If the host cannot spawn helper
agents, run the same batches one after another instead, and discard each batch's
raw text before starting the next so it does not accumulate. Sequential batches
change how long the step takes and nothing else: the batching, the round-robin
deal and the per-batch instructions are identical either way. **Never read
transcripts in the main conversation.** Raw transcript text there crowds out
everything else for the rest of the run, and the main conversation only ever
needs the findings.

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

- **A long profile can still name nobody.** Observed on a 19M-subscriber
  interview channel: several hundred words describing the show in detail, and
  the presenter is never mentioned. So length is not the test.
  `identity_is_thin` reports short OR nameless, and either way:
- **run one web search**, of the form `who is <channel name>`, and one only. On a
  well known channel this returns the framing in a sentence, for example that a
  show is hosted by a named entrepreneur who founded a particular company. One
  sentence of framing does more for the search than the transcripts can.
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

**Machine filter, then judge.** The filter is plain pattern matching, no model
involved, and it exists to cut a whole back catalogue of speech down to the
passages worth a human-grade read.

```bash
python3 build_corpus.py --channel <channel_id> --max 40 --strategy spread \
  | python3 selftalk_scan.py --host-terms "<distinctive facts about the host>"
```

**Choosing `--host-terms` is the difference between a usable result and a
useless one**, because it is the only mechanical way to tell the host's "I" from
a guest's. Use only things that are distinctively theirs: their surname, their
companies by name, their funds, a named former role, a specific place they have
said they lived.

**Never generic possessives.** "my podcast", "my company", "my business" all
look like host language and are not: guests have podcasts and companies too, and
on a real run those terms pulled in a guest describing his own show and another
describing his own firm. Generic terms poison the one signal that works.

Candidates come back already carrying their video, timestamp and link, so no
separate timestamping pass is needed.

**Fan out helper agents**, one per roughly 50 passages and never fewer than
four. The number of passages judged is the binding constraint on how rich the
profile is, not the number of videos read: two runs over the same 40 uploads,
differing only in which passages reached the judging step, produced 37 and 35
findings with only 21 in common, and 49 distinct facts between them. So do not
economise here by judging less.

**Leave `--max-per-video` at its default of 30**, and never lower it to trim the
pool. A two hour interview yields around 30 candidate passages, so a cap of 8
threw away roughly three quarters of the material in each long episode without
ever reading it. If the pool needs to grow, the answer is more agents, not a
tighter cap.

**Deal the list out round-robin**, one passage to each agent in turn, rather than
cutting it into blocks. It arrives sorted with the best-attributed passages
first, so slicing hands all the strong material to the first agent and leaves the
rest with nothing but half-signals.

Each agent gets this and nothing else:

> You are given a list of candidate passages from one YouTube channel's
> transcripts, each with a video id, a timestamp, and its attribution signals.
>
> The channel is `<channel name>`. Its format is `<format>`. The host is
> `<host name>`, and these are the facts already known about them:
> `<known facts from the identity step>`.
>
> Apply the three-part self-reference test in `references/evidence-rules.md` to
> every passage, and return only those that pass all three parts.
>
> Then attribute, into three buckets rather than a yes or no.
>
> - **Confirmed.** `host_anchor`, `in_sponsor_read`, or a `recurrence_videos` of
>   3 or more. These are strong signals that the host is speaking.
> - **Unconfirmed.** `weak_anchor`, which is first-person talk about running a
>   show or a business. Roughly half of these are a guest talking about their own
>   show or company. **Keep them and label them unconfirmed. Do not drop them.**
>   Dropping them has been measured twice and cost real findings both times, and
>   the label is what protects the reader, not the deletion.
> - **Unattributable.** No signal at all, and nothing in the surrounding lines
>   names the speaker. Drop these.
>
> On an interview channel most self-disclosure in the transcript belongs to the
> guest, so never upgrade a passage to confirmed by guessing. A quote presented as
> the host's when it was the guest's is the one error that discredits everything
> around it, and the bucket label is how that is avoided.
>
> For each passage you keep, return the verbatim words, the video id, the
> timestamp, one short phrase on what it reveals about the creator, and its
> attribution bucket. Then state how many you dropped and the most common reason.
>
> Return nothing else: no raw transcript, no commentary, no summary of the
> channel's topic. Do not look for further material beyond the list you were
> given.

**The helper agents are not told which brand this is for, and must not be.** A
helper that knows the brand filters to the brand without being asked, and the
pizza line never comes back. Casting wide happens here; narrowing to the brand
happens in Step 5.

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
creator's own words it rests on, with a timestamped link, and the concrete thing
that could be built on it. A creator who loves pizza and a brand whose in-app
scoring unit is called pies is a connection; real pizzas to users who hit a
hundred day streak on that creator's code is the thing built on it.

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

The creator profile is its own clearly visible section and is never folded into
the brand connections. Every run also states whether the sweep ran dry or whether
there is more to find. Full spec: `references/output-spec.md`.

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
