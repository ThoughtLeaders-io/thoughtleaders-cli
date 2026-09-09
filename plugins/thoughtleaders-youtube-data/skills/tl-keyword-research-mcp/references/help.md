# How the keyword research skill works — user guide

This is the canonical explanation to give a user who asks for help, a
description of the skill, its options, or how it works. Present it clearly
and conversationally (adapt length to what they asked); answering costs
nothing — no queries run in help mode.

## What it does

You give it a topic in plain words ("cannes lions", "budget meal prep",
"biohacking and longevity"). It turns that into a **precise, validated
search filter** over ThoughtLeaders' YouTube data — real boolean keyword
groups, tested against the live index so every keyword provably brings back
content that is *about* your topic, not just content containing the word —
and then returns whichever results you want from that filter.

## What you get

Always:
- **The filter set** — keyword groups you can reuse, plus a **clickable
  link** that opens a ThoughtLeaders report with the filter already applied
  (nothing is saved, no credits spent by clicking).
- The option to **save it as a named, shareable report**.

Your choice of results (it will ask if you don't say):
- **Trend data (video level)** — the matching uploads: newest first, biggest
  first, or most relevant; windowed by date; with prevalence numbers (how
  many videos, how many distinct channels). A creator who touched the topic
  once counts here. This is the "how big is this on YouTube / who's talking
  about it right now" answer.
- **Channel targets** — channels classified by their **relationship to the
  topic**, because very few channels are *entirely* about most topics:
  - **core** — the topic is the channel's identity (most of their uploads)
  - **recurring** — they return to the topic repeatedly (3+ matching
    uploads). For niche topics this tier is usually the real sponsorship
    market.
  - **occasional / one-off** — touched it once or twice; counted in trend
    math but usually not sponsorship targets.
  Channels come with sponsorship signals: subscribers, price, MSN
  membership, TPP status, outreach email on file, activity.
- **Both.**

## The two run modes

- **Quick** (~10–20 credits): one pass — expand the topic, test every
  candidate keyword against the index, validate the matches, deliver the
  filter + link. A solid starter filter in a couple of minutes.
- **Deep** (~60–120 credits): everything in quick, plus at least 3 rounds of
  refinement — narrowing noisy terms with scoped exclusions, rescuing broad
  terms with AND-anchors, mining the data for keywords you didn't think of,
  measuring real coverage — and then materializing and validating your
  chosen results. It checks in with you after round 3.

Say which one you want in your request ("quick" / "deep") or answer when
asked. Say **"run autonomously"** (or invoke with `autonomous` / `--auto`)
to skip all check-ins — that implies the deep run with both result types
unless you said otherwise.

## The flow (deep run)

1. **Set up** — it restates your topic verbatim as the measuring stick, asks
   anything unclear (run mode, results wanted), judges how broad the topic
   should be, and states the default scope: **YouTube longform uploads**
   (shorts/live on request). For topics newer than the model's knowledge or
   dense with insider jargon, it runs a small web lookup to learn the real
   entity names first.
2. **Expand** — it generates candidate keywords far beyond synonyms: every
   related product/brand family, spelling variants the search index treats
   as different words ("fable 5" vs "fable5"), and self-contained boolean
   groups.
3. **Probe** — one live query per candidate: how many videos, how many
   distinct channels, sample matches, and whether the term still brings back
   recent content or only an old back-catalogue.
4. **Validate** — cheap fast checks confirm each keyword's matches are
   genuinely about your topic (dropping "the word is there but the topic
   isn't"). Genuine judgment calls — like whether a sibling product counts —
   come to you with real example snippets.
5. **Refine (3+ rounds)** — the filter is narrowed, widened, and de-noised
   move by move, each round reported with what changed and why; after round
   3 you choose: accept, keep refining, or redirect.
6. **Materialize** — the cheap intensity triage tiers every channel first;
   then your chosen results are built: the trend feed and/or the channel
   table (tier × on-topic verdict × sponsorship flags).
7. **Deliver** — filter set, report link, results, and the recorded boolean
   expression so the exact filter can be re-run any time. Saving as a named
   report only happens if you say yes.

Throughout, it narrates each step and the credits spent so far — no silent
stages, nothing dropped without telling you.

## Options you can set in plain words

| You say | What it does |
|---|---|
| "quick" / "deep" | picks the run mode |
| "trend data" / "channels to sponsor" / "both" | picks the results |
| "run autonomously" | no check-ins; deep + both unless you said otherwise |
| "include shorts and live" | widens from the longform-only default |
| "newest first" / "biggest videos" / "since June" | sorts/windows the trend feed |
| "one video per channel" | dedupes the trend feed to each channel's best match |
| "only channels that cover it repeatedly" | focuses the channel table on the recurring tier (default threshold: 3+ matching uploads; say a number to change it) |
| "last 6 months" (recency) | changes the 12-month window used for "still active" checks |
| "title matches only" | restricts a keyword to titles — the cleanest field — instead of the default titles + video descriptions (the `summary` field) + transcripts |
| "exclude [sense/word]" | adds an exclusion, scoped so it doesn't over-cut |
| "broaden it" / "narrow it to X" | changes topic breadth mid-run |
| "save it as a report" | persists a named, shareable report |
| "keyword counts" / "how common is each keyword" | the opt-in distribution table (counts per keyword) instead of the full pipeline |

## Costs

Every live query costs credits (~1–2 each). Quick ≈ 10–20 credits; deep ≈
60–120 depending on how many channels get validated. The channel tier
triage is 2–3 queries total no matter how many channels. Clicking the
report link is free. Asking for help (this explanation) is free.

## Example prompts

- "quick: a keyword set for tiktok shop content" — starter filter, one pass
- "deep: find channels for [client] about home fragrance" — full pipeline,
  channel targets with tiers
- "how big is the GRWM trend on youtube right now? trend data only" —
  prevalence + newest matching uploads, no channel list
- "make a topic for cannes lions, run autonomously, both" — no pauses,
  everything delivered at the end
