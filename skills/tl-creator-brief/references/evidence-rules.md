# Evidence rules

The profile is written to be consumed by other skills and forwarded to real
people. Every rule here exists to stop a wrong quote, or an invented one,
leaving this session. This file is the single home of the attribution
doctrine — nothing else restates it.

## What counts as self-disclosure

A first-person search is not the test. A window is a gem only if all three
hold:

1. **The speaker is the subject** — their own life, work, history, habits,
   relationships or tastes. Not the topic, not the audience, not the video.
2. **It would still be true if the video did not exist.** "I founded a
   marketing agency" is true off camera. "I'll show you in a second" exists
   only because the video exists.
3. **It discloses something the channel's premise does not already imply.**
   A geography host loving maps is nothing. "I trained as an accountant" is a
   find. A trivial personal taste ("I can't stand coffee") passes — that is
   exactly the kind of find this skill exists for.

Cast wide. Material with no bearing on any brand belongs in the profile; the
unrelated detail is where the good connections come from, and Mode B narrows
later with its own inputs.

## Attribution

Captions carry no speaker labels, so whose mouth a line came out of is a
judgement the classifier makes from the format and the deterministic features
— which are inputs, never verdicts.

- **Solo format**: one voice holds the transcript. A window that passes the
  three-part test is the host's; no feature is required, and demanding one is
  what turns a solo channel into an empty profile.
- **Interview / multi-host / reaction**: most self-disclosure in the
  transcript belongs to the other voice. `host_anchor` (a fuzzy hit on a fact
  distinctive to the host) and `in_sponsor_read` argue host. Guest-ambiguous
  windows drop; `speaker_guess: "unclear"` is an honest answer, and unclear
  windows never publish as the host's.
- **Recurrence** (the same rare phrase across several uploads) argues host on
  an interview channel — guests change between uploads, the host does not.
  **On a multi-host channel recurrence alone must never confirm**: both hosts
  recur, so a recurring passage still needs another signal or an in-window
  naming before it counts as one host's.
- **Ad reads are dual-use.** A sponsored span is spoken by the host, never by
  a guest or reacted material — the strongest single-voice signal there is.
  Simultaneously, a "fact" inside an ad read is scripted, so it is banned as a
  gem source: it only enters the profile if it recurs outside reads.

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
- Every quote carries its `&t=` link. The scan attaches offsets at birth; a
  quote from anywhere else goes through `scripts/quote_timestamp.py`.
- **A partial match is never a verification.** `quote_timestamp.py` reports
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

## Sensitive domains

Health, beliefs, children, and precise location are collected, flagged
`sensitive: true`, and **excluded from Mode B connections by default** — they
appear in the profile so the human reading it knows they exist, never in a
pitch angle unless a human deliberately opts one in. No protected-trait
inference, ever: the profile records what the creator said, not what a model
concludes about who they are.

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
- If the profile holds nothing that honestly connects to a brand, Mode B says
  exactly that, shows what was searched, and stops. A no-fit verdict is a
  valid output.
