# Evidence rules

The profile is written to be consumed by other skills and forwarded to real
people. Every rule here exists to stop a wrong quote, or an invented one,
leaving this session. This file is the single home of the attribution
doctrine — nothing else restates it.

## What counts as self-disclosure

A gem is one lasting fact about the creator as a person, in the creator's
own voice. A first-person search is not the test. A window is a gem only if
all three hold:

1. **About the person, not the content.** The fact is about the creator's
   life: where they are from, family, home, pets, work history, money,
   health, beliefs, standing habits and tastes, relationships. A verdict on
   the thing this video is about is not a gem: the dish, the workout, the
   game, the product, the news story. A standing trait is, even when it is
   obvious from the channel: a cooking host saying they have loved cooking
   since childhood is a gem. Obvious is not a reason to skip; a profile that
   never mentions cooking on a cooking channel is wrong.
2. **True off camera and next year.** Skip anything that exists only because
   the video exists, and anything true only today: production notes, what
   they did this morning, how they feel about this take, a reaction to this
   one dish. A habit or taste counts when it is stated as recurring or
   long-standing. "I've never liked cilantro" is a gem. "This dish is S tier"
   is not.
3. **The creator's own voice, settled.** The creator speaking about their
   own life, including when a guest or co-host interviews them on their own
   channel. Never a guest, co-host, crew member, street interviewee, read-out
   comment, quoted speech, sarcasm, hypothetical, or a role played in a skit.
   If you cannot settle whose voice it is, it is not a gem. A missed gem
   costs less than a wrong one.

The channel as a job counts only when the fact is biographical: when they
started, what they quit to do it, how it changed their money or health, who
works with them. The feeling of making this week's episode does not.

Political and social opinions the creator states as their own are gems in
every channel type. Opinions on the video's subject are not.

Cast wide across domains and narrow on lasting. A trivial standing taste is
a gem. A momentary reaction, however personal it sounds, is not. Material
with no bearing on any brand belongs in the profile; the unrelated detail is
where the good connections come from, and CONNECT narrows later with its
own inputs.

## Attribution

Captions carry no speaker labels, so whose mouth a line came out of is a
judgement the classifier makes from the format and the deterministic features
— which are inputs, never verdicts.

- **Solo format**: one voice holds the transcript. A window that passes the
  three-part test is the host's; no feature is required, and demanding one is
  what turns a solo channel into an empty profile. A classifier verdict of
  `speaker_guess: "unclear"` on a declared-solo channel therefore publishes
  as the host — with confidence capped at `unconfirmed` — unless the window
  text itself names or implies another voice (a guest, a quoted person, a
  clip), in which case it is dropped as unattributable. A window carrying a
  `second_voice_hint` (the host named in the third person or spoken to, next
  to the first-person line) IS that case, found deterministically: on a solo
  label it takes the shared-voice rules below, never the solo rule.
- **Interview / multi-host / reaction**: most self-disclosure in the
  transcript belongs to the other voice. `host_anchor` (the host naming
  themselves in the window: "it's Eric", "my name is") and `in_sponsor_read`
  argue host. A `second_voice_hint` argues the other way. Guest-ambiguous
  windows drop; `speaker_guess: "unclear"` is an honest answer, and unclear
  windows never publish as the host's.
- **A crew channel is multi-host, whatever the label says.** When a large
  share of the kept windows name the host in the third person
  (`third_person_host_share` in the fetch summary, above about a quarter),
  other people hold the microphone for much of the transcript, and the solo
  rule would hand their lives to the host. The format call says `multi_host`
  and the shared-voice rules apply.
- **Recurrence** (the same rare phrase across several uploads) argues host on
  an interview channel — guests change between uploads, the host does not.
  **On a multi-host channel recurrence alone must never confirm**: both hosts
  recur, so a recurring passage still needs another signal or an in-window
  naming before it counts as one host's.
- **Ad reads are dual-use.** A sponsored span is spoken by the host, never by
  a guest or reacted material — the strongest single-voice signal there is.
  Simultaneously, the *sponsored-product claims* inside a read are scripted
  and are banned as a gem source. A personal aside inside a read (a trip, a
  family visit, a childhood story, a merch line) stays eligible at confidence
  `likely`, and when the sponsor is the host's own company the read is work
  disclosure, not an exclusion. `confirmed` still needs the fact outside reads.

- **Detector output is evidence about detection, not about the video.** A
  detected mention with a `(0,0)` span has no position — never pad it into a
  claim about the video's opening. A `summary`-field hit (the creator-written
  upload description) is the affiliate link, not speech. And an affiliate read that only drops a link describes
  nothing; one that describes the product is still a scripted read, so the
  ad-read rule above applies.
- **Identity reads come from the generated profile.** A channel's raw
  `description` is usually subscribe-boilerplate; the platform's generated
  profile (`ai.description`) is the identity field worth reading.
  `channel_context.py` returns both, labelled.

- **A staged premise is a format hint, not a verdict.** A prank, challenge,
  stunt or skit upload (`format_hint: staged`, from the title) is still one
  voice, so attribution is unchanged. But a durable claim stated inside it
  (a spouse, a pregnancy, a move, a new job) may be the premise. The
  extractor reports it at `likely`; `authenticate.py` searches the channel
  for the same claim in non-staged uploads before the merge; the merge shard
  decides with that evidence. Found elsewhere: the fact is the person's.
  Found only inside staged uploads: kept in the ledger at `unconfirmed`,
  marked `staged_only`, never on a brand-facing page. **Nothing is dropped
  for being uncertain.**
- **Contradictions are settled on dated evidence, not on the two lines in
  view.** Two facts in one domain that cannot both be current (two homes, a
  husband and a boyfriend) are probed the same way, and the newest dated
  evidence wins: the newest upload saying each, then the identity lane's
  `seen_date` when the creator's own profile corroborates one side. The
  older fact stays as history. When neither side is newer, or both recur
  into the present, both stay at `unconfirmed` and neither supersedes.
- **Merging quotes into one fact requires one speaker.** Two windows from
  the same interview video are not the same voice by default — a host's
  origin story at minute 6 and a guest's at minute 90 sit in one transcript.
  Merge only quotes that each independently attribute to the host; a window
  that merely *continues the video* of an attributed one proves nothing.

Every fact carries a confidence bucket, and the bucket travels into the
output:

| Bucket | What puts it here |
|---|---|
| **Confirmed** | Solo-format pass, a host-anchored window, or a fact corroborated across lanes (a transcript mention AND the creator's own social profile) — cross-lane corroboration is the top tier. |
| **Unconfirmed** | The classifier believes it is the host but no rule above settles it (e.g. weak-anchor material on an interview channel). Kept, and labelled. Never silently dropped, never silently promoted. |
| **Dropped** | Speaker unclear on a shared-voice format, or ad-read-only. Counted in the profile's caveats, never shown as a fact. |

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
  `partial`, fix the quote to what the captions actually hold or drop it —
  never publish the original words against a partial match, because a shared
  opening with a different tail is how a fabricated quote gets a real
  timestamp.
- `match: "none"`: retry with a spelling or phonetic variant; still none,
  the quote does not publish. `cues: 0` means the video has no stored
  transcript — a coverage gap, not evidence.

## Provenance

Every fact names its lane, and lanes never masquerade as each other:

- `transcript` — verbatim quote, `&t=` link, video date.
- `social` — profile URL and seen-date. A fact read off Instagram is not a
  quote and is never dressed as one.
- `web` — source URL. Same rule.

## Sensitivity — a tier, not a flag

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
  states in their own voice are ordinary self-disclosure at tier `none` —
  on a commentary channel they are the profile's core. What they are not is
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
**distinct videos or sources, never snippet count** — one video windowed
thrice is one occurrence.

## Honesty rules

- Transcript coverage is partial (~50–70% of uploads is normal). The profile
  header prints the ratio and the line "absence is not evidence".
- No diarization exists; interview-format confidence is capped and the
  profile says so.
- An empty result is a real answer. "No evidence found" — with the coverage
  numbers that bound the claim — is correct and forwardable. A profile
  assembled from unattributable guesses is worse than nothing.
- If the profile holds nothing that honestly connects to a brand, CONNECT says
  exactly that, shows what was searched, and stops. A no-fit verdict is a
  valid output.
