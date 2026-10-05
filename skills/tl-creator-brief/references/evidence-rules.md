# Evidence rules

The profile is written to be consumed by other skills and forwarded to real
people. Every rule here exists to stop a wrong quote, or an invented one,
leaving this session. This file is the single home of the attribution
doctrine, nothing else restates it.

## What counts as self-disclosure

A gem is one lasting fact about the creator as a person, in the creator's
own voice. A window is a gem only if all three hold:

1. **About the person, not the content.** Where they are from, family, home,
   pets, work history, money, health, beliefs, standing habits and tastes,
   relationships. A verdict on the video's subject (the dish, the workout,
   the game, the product, the news story) is not a gem. A standing trait is
   a gem even when the channel makes it obvious: a cooking host who has
   loved cooking since childhood. Judge every sentence, not the window's
   topic: a girlfriend named in a show intro, a childhood memory inside a
   list of games, a dog mentioned while building something are gems inside
   a content window.
2. **True off camera and next year.** Not a gem: production notes, day-of
   states ("hasn't showered yet today", "cut my hair yesterday", "dad texted
   me today"), how they feel about this take, a reaction to this one dish. A
   habit or taste is a gem when stated as recurring or long-standing: "I've
   never liked cilantro" is; "this dish is S tier" is not. The channel as a
   job counts only when biographical: when they started, what they quit to
   do it, how it changed their money or health, who works with them.
3. **The creator's own voice, settled by the Attribution rule below.** Never
   a guest, crew member, street interviewee, read-out comment, quoted
   speech, sarcasm, hypothetical, or a role played in a skit. The host's own
   narration about other people ("I flew to Mexico to meet my friend Dani")
   is the host's fact: the friend is the subject of the sentence, the host
   is the subject of the fact. A missed gem costs less than a wrong one.

Political and social opinions the creator states as their own are gems on
every channel type; opinions on the video's subject are not. Cast wide
across domains and narrow on lasting: a trivial standing taste is a gem, a
momentary reaction is not, and material with no bearing on any brand belongs
in the profile.

## Attribution

Captions carry no speaker labels. Whose line it is comes from the window
text and the format; flags are inputs, never verdicts. A first-person line
is the creator's only when the window shows it. Decide in this order:

1. **Someone else's**, when any sign holds: another person replies to the
   line as its listener; the line answers the creator's question; the
   speaker names or addresses the creator; the speaker calls the creator a
   friend or speaks of them in the third person (`second_voice_hint` finds
   this deterministically); someone new is introduced just before the line;
   the line comes from a stream, a call, or footage of another person; the
   life story does not fit the creator (a surgeon's residency on a
   woodworking channel). `speaker_guess: "guest"`; the line never enters
   the ledger.
2. **The creator's**, when any sign holds: the creator names themselves
   (`host_anchor`); the creator addresses their own audience or narrates the
   upload to them; the line matches a known fact of the creator's; the line
   sits inside a sponsor read (`in_sponsor_read`); on an interview channel,
   the same rare line recurs across uploads (guests change, the host does
   not). `speaker_guess: "host"`, `confidence: "confirmed"`,
   `speaker_evidence` names the sign.
3. **Shared-voice upload** (format interview or multi_host; `format_hint`
   interview_or_collab, reaction or staged; or a `second_voice_hint`): with
   no sign from 1 or 2, `speaker_guess: "unclear"`, and the line is dropped.
   On a multi-host channel recurrence alone never confirms: both hosts recur.
4. **Solo or faceless-scripted upload with no hint**: with no sign from 1,
   the line is the creator's. Say `unclear` only when the text suggests
   another voice you cannot place; an unclear line here publishes as the
   creator's at `unconfirmed`.

On a multi-host channel the second named host is `cohost`, with the name in
`speaker_evidence` when the window shows it (a self-naming, the other host
addressing them by name); a "we" line about the hosts' shared life is
`shared`. Shared facts exist only between named hosts: a guest's "we" is the
guest's.

**Staged upload** (`format_hint: staged`: a prank, challenge, stunt, fake or
pretend scenario, dating show or skit, from the title): a shared-voice
upload. A line said to win a game, set up a prank, play a character or get a
laugh is not disclosure unless the creator confirms it outside the bit. A
durable claim stated inside the premise (a spouse, a pregnancy, a move, a
new job, a death) may be the premise: report it at `likely` with
`speaker_evidence` naming the staged hint; never withhold it and never mark
it `hypothetical` on the title alone. Durable tastes, family names and
childhood stories told inside a challenge are still the person's. A later
stage searches the channel's non-staged uploads for the same claim and
decides with that evidence.

**Ad reads.** A sponsored span is spoken by the host, never by a guest or
reacted material. The sponsored-product claims inside it are scripted and
never a gem; a personal aside inside it (a trip, a family visit, a childhood
story, a merch line) is the host's at `confirmed`; a sponsor that is the
host's own company makes the read work disclosure.

## After extraction

Rules the scripts and the merge shard apply to what the extractor returned.

- **A crew channel is multi-host, whatever the label says.** When more than
  about a quarter of the kept windows name the host in the third person
  (`third_person_host_share` in the fetch summary), other people hold the
  microphone for much of the transcript: the format call says `multi_host`
  and the shared-voice rules apply.
- **A staged premise is checked, never guessed.** `authenticate.py`
  searches the channel for the claim in non-staged uploads before the merge;
  the merge shard decides with that evidence. Found elsewhere: the fact is
  the person's. Found only inside staged uploads: kept in the ledger at
  `unconfirmed`, marked `staged_only`, never on a brand-facing page. A claim
  found only in a staged upload's first 60 seconds, and in no other video, is
  the opening hook: `unconfirmed`.
- **Contradictions are settled on dated evidence, not on the two lines in
  view.** Two facts in one domain that cannot both be current (two homes, a
  husband and a boyfriend) are probed the same way, and the newest dated
  evidence wins: `last_seen` on each side (the newest upload saying it),
  then the identity lane's `seen_date` when the creator's own profile
  corroborates one side. The older fact stays as history. When neither side
  is newer, or both recur into the present, both stay at `unconfirmed` and
  neither supersedes.
- **Merging quotes into one fact requires one speaker.** Two windows from
  the same interview video are not the same voice by default: a host's
  origin story at minute 6 and a guest's at minute 90 sit in one transcript.
  Merge only quotes that each independently attribute to the host; a window
  that merely continues the video of an attributed one proves nothing.
- **Detector output is evidence about detection, not about the video.** A
  detected mention with a `(0,0)` span has no position: never pad it into a
  claim about the video's opening. A `summary`-field hit (the creator-written
  upload description) is the affiliate link, not speech. An affiliate read
  that only drops a link describes nothing; one that describes the product
  is a scripted read, so the ad-read rule applies.
- **Identity reads come from the generated profile.** A channel's raw
  `description` is usually subscribe-boilerplate; the platform's generated
  profile (`ai.description`) is the identity field worth reading.
  `channel_context.py` returns both, labelled.

Every fact carries a confidence bucket, and the bucket travels into the
output:

| Bucket | What puts it here |
|---|---|
| **Confirmed** | A line the Attribution rule gives the creator (a sign from step 2, or a solo upload with no sign of another voice), or a fact corroborated across lanes (a transcript mention AND the creator's own social profile or written bio). |
| **Unconfirmed** | The extractor's own doubt with a named reason (a staged premise found in no non-staged upload, a line that contradicts the channel's description, doubt about the voice); an unclear line on a solo upload; a claim found only in an opening hook; two facts that contradict with neither newer; a written bio or social record no video confirms; two first names a caption ran together. Kept in the ledger and labelled, never on a brand-facing page. |
| **Dropped** | Someone else's line, or unclear on a shared-voice upload. Counted in the profile's caveats, never shown as a fact. |

## The bio lane: the creator's own written words

The channel About box (and, when the socials lane is on, the profile bios it
read and confirmed) is a **provenance of its own: `bio`**. It is the most
explicit thing a creator ever says about themselves and the least verified, people write untrue, stale and aspirational things about themselves, and
nobody edits an About box. So the lane treats it as a lead with a source, not
as a fact:

| A bio fact that is… | at tier | becomes |
|---|---|---|
| corroborated by a transcript fact | `none`, `lifestyle` | **`confirmed`**, both sides, and usable like any confirmed fact |
| corroborated by a transcript fact | `clinical` | `confirmed`; the transcript side still answers to the repetition rule below, and the bio side is never `selected` |
| corroborated by a transcript fact | `children`, `location` | `confirmed` but withheld as usual, the tier decides the page, not the confidence |
| **uncorroborated** | `none`, `lifestyle` | stays `unconfirmed`, never a claim and never a connection angle; renders only under "In their own words (unverified)"; on a refresh it expires unless the About text still says it |
| **uncorroborated** | `clinical`, `children`, `location` | **dropped from the ledger entirely** |

- **Only a transcript fact corroborates a bio fact.** A second written source
  agreeing with the first is one source twice. A mention inside a staged
  premise does not count either: that is a cap the transcript lane already
  applied, and corroboration may not lift it from outside.
- **A written-source excerpt is not a quote.** A `bio` fact carries
  `source_excerpt`: the creator's own words, cut mechanically from the stored
  bio text, never written by a model, plus `source_url` and `seen_date` where
  a transcript fact carries `quote`, `video` and `start`. It publishes without
  quote marks around a timestamp and without a watch link, because there is no
  video behind it. The ban on `quote`/`video`/`start`/`url` on a non-transcript
  fact stands.
- **The About box is not a second, unfiltered channel to the page.** Once the
  lane has run, the raw About text is no longer reprinted beside the ledger:
  a claim the lane dropped must not arrive by the back door.
- The ES `ai.description` profile is NOT a bio source. It describes the recent
  catalogue, not the person, and it is not the creator's words.

## Quotes

- Verbatim or not at all. Bracketed proper-noun corrections are the only
  permitted edit, with the raw caption text noted.
- **A non-English quote publishes verbatim in its source language**, with an
  English gloss alongside labelled as a translation. The gloss is never the
  quote: verification (`verify_quotes.py`) always runs against the
  original words.
- Every quote carries its `&t=` link. The fetch attaches offsets at birth; a
  quote from anywhere else goes through `scripts/verify_quotes.py`.
- **A partial match is never a verification.** `verify_quotes.py` reports
  `match: "exact" | "partial" | "none"`; only `exact` publishes. On
  `partial`, fix the quote to what the captions actually hold or drop it, never publish the original words against a partial match, because a shared
  opening with a different tail is how a fabricated quote gets a real
  timestamp.
- `match: "none"`: retry with a spelling or phonetic variant; still none,
  the quote does not publish. `cues: 0` means the video has no stored
  transcript, a coverage gap, not evidence.

## Provenance

Every fact names its lane, and lanes never masquerade as each other:

- `transcript`: verbatim quote, `&t=` link, video date.
- `social`: profile URL and seen-date. A fact read off Instagram is not a
  quote and is never dressed as one.
- `web`: source URL. Same rule.

## Sensitivity: a tier, not a flag

Every fact carries a `sensitivity` tier. The binary "sensitive" flag it
replaces threw away the difference between "wears contacts" and "was
diagnosed with X", and that difference is the whole judgment:

| tier | what it holds | in CONNECT connection angles |
|---|---|---|
| `none` | ordinary disclosure, including beliefs, being a parent, city/country | yes |
| `lifestyle` | glasses/contacts, diet, fitness, weight change discussed openly, sleep, skincare, casual allergies, supplements | yes |
| `clinical` | diagnoses, mental-health conditions, medication, surgery, disability, fertility/pregnancy | only under the repetition rule below |
| `children` | a child's name, age, school | no, by default |
| `location` | street, neighbourhood, building | no, by default |

- **Beliefs are NOT sensitive.** Political and social opinions the creator
  states in their own voice are ordinary self-disclosure at tier `none`: on a commentary channel they are the profile's core. What they are not is
  an inference: record the stated opinion, never a conclusion about who the
  person is.
- **Only `clinical`, `children` and `location` are withheld from connection
  angles by default.** They still appear in the profile, so the human reading
  it knows they exist.
- **Withheld is withheld from angles, not from the warnings.** "Where this
  could go wrong" exists to say what NOT to pitch, and the withheld tiers are
  where that knowledge lives: a creator who talks about sobriety must not be
  handed a hangover-cure read, a creator with a chronic condition must not be
  asked to joke about it. So every tier, withheld ones included, is read when
  that section is written. State the risk at the level of the fact's kind,
  never its detail: "talks about their own sobriety" is the warning, the
  clinic and the dates are not; "has young children whose names come up" is
  the warning, the names are not; "has named where they live" is the
  warning, the street is not. Nothing in that section is an angle.
- **`clinical` is usable when the creator made it public themselves**: when
  they discuss it repeatedly (3+ distinct videos) or frame it as part of
  their story, it may be used in an angle. One passing mention never is.
  A human can always opt a withheld fact in deliberately; nothing opts itself
  in.
- **No protected-trait inference, ever**: the profile records what the
  creator said, not what a model concludes about who they are.

`sensitive: true` survives in the ledger as the derived boolean (true exactly
for the withheld tiers) so older readers keep working; the tier is the fact.

**Who tiers.** Not the extractor: its job is who is talking and what they
said, and a fact it withheld could never be protected or used later.
`assemble_extracts.py` attaches a keyword hint (`tier_hint.py`, protective by
design) to every gem; the merge shard sees it as `tier` on its input line and
owns the final call; `merge_pass.py expand` falls back to the hint when the
shard said nothing. So a run's tiers are decided once, at the end, with the
whole cluster in view.

## Contradictions and staleness

Latest wins, with dates: "moved to Austin" (2024) supersedes "live in LA"
(2021), and the superseded fact stays visible as history. Recurrence counts
**distinct videos or sources, never snippet count**: one video windowed
thrice is one occurrence.

Every transcript fact carries `last_seen`, the newest upload date among its
evidence, computed by the script. A claim stated as current that the
evidence shows is over (a marathon since run, a relationship since ended, a
job since left) is marked `ended` by the merge shard; past history ("used
to", "as a kid") never is. An `ended` fact stays in the ledger as
history, is never selected and is never quoted on a brand-facing page. A talking point or a strong
connection rests on a fact with `last_seen` inside the last 24 months of the
run date; an older fact supports a thin connection only with its year
stated; the Thesis and "Where this could go wrong" use every fact at any
age. A claim never repeats "X years ago": the script converts it to a year
from the upload date ("in about 2020, said in 2025"), and a claim about the
channel's own start takes the channel's start date when they disagree by a
year or more (the first upload, skipping at most five early uploads that a gap
of over a year separates from the rest).

## Honesty rules

- Transcript coverage is partial (50 to 70% of uploads is normal). The profile
  header prints the ratio and the line "absence is not evidence".
- No diarization exists; interview-format confidence is capped and the
  profile says so.
- An empty result is a real answer. "No evidence found", with the coverage
  numbers that bound the claim, is correct and forwardable. A profile
  assembled from unattributable guesses is worse than nothing.
- If the profile holds nothing that honestly connects to a brand, CONNECT says
  exactly that, shows what was searched, and stops. A no-fit verdict is a
  valid output.

## A third audience: the creator

The creator brief is read by the creator, in second person. That changes the
register and nothing else. What counts as evidence is the same: a quote is
the creator's own verified words with its timestamp, or it is not on the
page. Withheld tiers stay withheld whatever the section, and a fact the
connections page used only to say what not to say is never turned into a
talking point. The brand's lines are the brand's, verbatim; ours start
from the creator's own moment and join it to the brand's ask, or to the
product itself when the moment says something the brand's lines do not.
