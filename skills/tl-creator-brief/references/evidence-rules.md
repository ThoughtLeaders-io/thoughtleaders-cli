# Evidence rules

The output is written to be forwarded. Every rule here exists to stop a wrong
quote, or an invented one, reaching someone outside this session.

## What counts as the creator talking about themselves

The whole first half of this skill rests on this distinction, so it is written
down rather than left to judgement. **A first-person search is not the test.**
"I think you should buy gold" and "I'll show you in a second" are both first
person and neither is worth anything.

A line qualifies only if it passes **all three**:

1. **Is the speaker the subject?** The line is about their own life, work,
   history, habits, relationships or tastes. Not about the topic, not about the
   audience, not about what happens next in the video.
2. **Would it still be true if the video did not exist?** "I founded a marketing
   agency" is true off camera. "I'll show you in a second" exists only because
   the video exists. "I think you should buy gold" is a claim about the world,
   not a fact about the speaker.
3. **Does it disclose something the channel's premise does not already imply?**
   A geography host saying "I love maps" discloses nothing. "I trained as an
   accountant" does.

Worked through:

| Line | Verdict |
|---|---|
| "I taught myself how to do this" | Passes. Speaker is the subject, true off camera, reveals a trait. |
| "I founded a marketing agency because..." | Passes. |
| "I consider myself an autodidact" | Passes. |
| "I can't stand coffee" | Passes. A trivial personal taste is exactly the kind of find this skill exists for. |
| "I think you should buy gold" | Fails 2. An opinion about the world. |
| "I'll show you in a second" | Fails 2. A stage direction. |
| "I love maps" on a geography channel | Fails 3. Implied by the premise. |

**Cast wide at this stage.** Do not filter to what looks useful for the brand.
The unrelated material is where the good connections come from, and narrowing to
the brand is a later step with its own inputs.

## Channel format decides how far to trust any of it

Transcripts carry no speaker labels, and the signal is worth wildly different
amounts depending on the format. Detect the format first, from the channel's
profile text, its recent titles and their durations, then apply the matching
rule.

| Format | Confidence | Rule |
|---|---|---|
| **Interview show with a named host** | Usable, and the best case for finding gems, because host self-talk is rare and stands out. But most self-talk on the channel belongs to the **guest**, so the trap is large. Roughly half the machine-filtered candidates that match a host anchor are still the guest. Expect lower recall than a solo channel, and say so. | Every quote carries an attribution bucket, per the buckets below. A candidate `selftalk_scan.py` anchored to the host is confirmed; a half-signal is kept and labelled unconfirmed; a candidate with no signal and no naming in the surrounding lines is dropped. State the guest-attribution risk in the caveats. |
| **Solo talking head** | Usable. No attribution risk, but first person is constant and mostly topic commentary. | All the weight sits on the three-part test. Expect a low survival rate and report it. |
| **Faceless narrated or animated** | Not usable. | Return an empty profile. The narrator may be hired and "I" may be a scripted persona belonging to nobody, so no line can be tied to an identifiable creator. |
| **Multi-host** | Barely usable. | Keep only lines where the speaker names themselves or is named in the surrounding context. Everything else is unattributable and gets dropped. |
| **Reaction** | Usable with the tightest rule of the five. The creator's own speech and the narration of the material being reacted to sit in the **same transcript with no labels**, and the reacted material is often the more talkative of the two. | A finding from a reaction video is **Unconfirmed** unless `host_anchor` or `in_sponsor_read` is true. Nothing else promotes it, because the second voice is not a guest who can be reasoned about but arbitrary third-party narration. |

**State the detected format and the confidence in the output**, every run.

## Format is a property of the video, not only of the channel

One channel routinely mixes formats: a solo channel runs reaction episodes, an
interview show posts solo monologues. So detect the format per video as well as
for the channel, and **the video's own format is what decides the bucket** for
passages from it. The channel's dominant format is the fallback where a video's
own format was not determined, never an override.

Titles carry most of this. A title of the form "X Reacts to Y" marks a reaction
episode whatever the channel usually does, and the reaction rule applies to
every passage from it. Where a video's format is genuinely unclear, treat it as
sharing the transcript with another voice, since that is the assumption that
cannot invent a quote.

## Attribution buckets

Attribution is three buckets, not a yes or no, because the middle bucket is real
and is where a measurable share of the findings live.

| Bucket | What puts it here | What happens to it |
|---|---|---|
| **Confirmed** | `host_anchor`, `in_sponsor_read`, or `recurrence_videos` of 3 or more. | Usable as the host's own words. |
| **Unconfirmed** | `weak_anchor`: first-person talk about running a show or a business. Where another voice shares the transcript, roughly half are that other voice. | **Kept, and labelled.** Never silently dropped, and never silently promoted. |
| **Unattributable** | No signal, and nothing nearby names the speaker. | Dropped, and counted in the caveats. |

On a **solo** video the buckets are not signal-driven at all: one voice holds the
transcript, so a passage that passes the three-part test is Confirmed and the
absence of `host_anchor` says nothing. Requiring a signal there is what turns a
solo channel into an empty profile. On a **reaction** video the ceiling is
Unconfirmed unless `host_anchor` or `in_sponsor_read` fires.

The label travels with the quote all the way into the output. That is what makes
the middle bucket safe to keep: the reader can see exactly which quotes are the
host beyond doubt and which are probable, and can weigh a connection built on
one differently from a connection built on the other.

## An empty profile is a valid answer

Where the format cannot support the analysis, return an empty creator profile
naming the detected format and why it defeats the method, and do not proceed
into the transcript steps to produce something anyway.

This output can be forwarded to a brand. "This channel's format does not support
self-reference profiling" is a correct and useful answer. A profile assembled
from low-confidence guesses presented as findings is not, and is worse than
nothing, because the reader cannot tell the difference.

## Spoken versus written

- Anything claimed as **spoken** must come from the transcript field. Discard
  every snippet whose field is not the transcript.
- Descriptions have one use: confirming a sponsorship happened and reading the
  current call-to-action format. Separate call, labelled as such. Never merge
  the two result sets.

## Quotes

- Verbatim or not at all.
- **Timestamp every quote.** `selftalk_scan.py` returns candidates already
  carrying their offset, so a quote that came through it needs no extra pass.
  For a quote from anywhere else:
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
- **No speaker labels.** Verify from surrounding context who is speaking, and
  sort the result into the three attribution buckets above. Ambiguous is a
  bucket, not a delete: only a passage with no signal and no naming nearby is
  dropped outright.

## Figurative use

If Step 5's narrow probe searches the brand's problem space, a raw category
search returns mostly metaphor. Judge each snippet individually before it
becomes a connection, and **report the survival count**: how many hits were
returned, and how many of those were literal rather than metaphor.
That ratio is itself evidence of how close the creator is to the category.

## The evidence decides the answer

If the profile holds nothing that genuinely connects to the brand, say exactly
that, show what was searched, and stop. Forcing a connection out of thin
material is the one failure mode that loses the reader's trust in every other
line of the output.
