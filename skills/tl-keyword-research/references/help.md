# How the keyword research skill works — user guide

This is the canonical explanation to give a user who asks for help, a description of
the skill, its options, or how it works. Present it clearly and conversationally
(adapt length to what they asked); answering costs nothing — no queries run in help
mode.

## What it does

You give it a topic in plain words ("cannes lions", "budget meal prep", "biohacking
and longevity"). It turns that into a **precise, validated search filter** over
ThoughtLeaders' YouTube data — real boolean keyword groups, tested against the live
index so every keyword provably brings back content that is *about* your topic, not
just content containing the word — and then returns whichever results you want from
that filter.

## What you get

Always:
- **The filter set** — keyword groups you can reuse, plus a **clickable link** that
  opens a ThoughtLeaders report with the filter already applied (nothing is saved
  until you ask).
- The option to **save it as a named, shareable report**.

Your choice of results (it asks if you don't say — see *Two choices* below):
- **Trend data (video level)** — the matching uploads: newest first, biggest first,
  or most relevant; windowed by date; with prevalence numbers (how many videos, how
  many distinct channels). A creator who touched the topic once counts here. This is
  the "how big is this on YouTube / who's talking about it right now" answer.
- **Channel targets** — channels classified by their **relationship to the topic**,
  because very few channels are *entirely* about most topics:
  - **core** — the topic is (most of) the channel's identity.
  - **recurring** — they return to the topic repeatedly (3+ matching uploads by
    default). For niche topics this tier is usually the real sponsorship market.
  - **occasional** / **one-off** — touched it once or twice; counted in trend math
    but usually not sponsorship targets. Each channel is then evidence-checked
    against the filter (see *What the verdicts mean* below) and comes with
    sponsorship signals: subscribers, price, MSN membership, TPP status, outreach
    email on file, activity.
- **Both.**

## Two choices — you make them, not a default

**Path** — how hard the filter gets refined:
- **Quick** — one pass: expand, test every candidate against the index, judge the
  matches, deliver. About a minute.
- **Deep** — the full pipeline: the filter is composed and then *measured* —
  residual/coverage/exclusion checks run against the live index — and refined only
  where a check flags a weakness, for **at most three rounds**. Deep means the
  checks ran, not that the clock ran: a round that flags nothing is a complete deep
  run. Budget: **about five minutes** of wall clock on a large model — the queries
  themselves take under a minute, and the rest is the model's own reading and
  judging, which is why the run follows a fixed turn plan (probe → read the sheet →
  judge → measure → materialize → deliver) instead of wandering.

**Results** — trend data, channel targets, or both.

Say either in your request ("quick" / "deep", "trend" / "channels to sponsor" /
"both") and it runs with no further questions. Leave one or both unstated and it
asks **once**, recommending by the shape of your topic: an event, launch, or news
moment ("Cannes Lions", a product launch) is usually a *trend* question first —
channels rarely have a one-off moment as their identity; an evergreen niche
("retirement planning", "sourdough") is usually a *channel* question first. The
recommendation is advice; your answer wins.

Say **"run autonomously"** (or invoke with `autonomous` / `--auto`) to skip every
check-in — that means the deep path, both result types, with each assumption along
the way stated rather than asked.

## The flow (deep path)

1. **Set up** — restates your topic verbatim as the measuring stick, says what
   relationship it's testing (does a channel *cover* the topic, *participate* in an
   event, *have* an attribute), states the default scope (YouTube longform uploads;
   shorts/live on request), and says how broad a result should look. For a topic
   newer than general knowledge or dense with insider jargon, it looks up the real
   entity names first.
2. **Probe, with snippets** — one live check per candidate keyword: how many videos,
   how many distinct channels, and a few short snippets showing *where* and *how* it
   matched — not just that it did.
3. **Judged inline** — each candidate gets a verdict straight from its snippets
   against your stated intent: kept, dropped (wrong sense, or a near-duplicate of a
   broader kept term), or `unsure` when the snippets don't settle it and always get
   a closer look. Genuine judgment calls, like whether a sibling product should
   count, come to you with snippets.
4. **Composed and measured** — the kept keywords become boolean groups (one per
   facet), each round measured against the index: how much a broad term adds beyond
   the core, whether an exclusion cuts too much on-topic content, whether coverage
   matches the expected breadth. Only what a measurement flags gets touched next
   round — up to three rounds, fewer if nothing flags.
5. **Tiers** — every channel the filter reaches is tiered by intensity (core /
   recurring / occasional / one-off) before anything more expensive runs.
6. **One evidence pass** — the channels you'd actually use (by tier) get checked
   against the *exact delivered filter*, in one pass, with a snippet proving the
   match. Each gets a verdict: on-topic, mixed (right idea but incidental, or both
   senses), or off-topic (excluded, always shown to you).
7. **Link** — filter set, report link, the results you chose, the recorded boolean
   expression (so the exact filter can be re-run any time), and a budget line:
   elapsed time, how many checks ran, how many channels were evidence-checked, and
   anything left `unresolved` or `unsure`. Saving as a named report only happens if
   you say yes.

Throughout, it narrates each step as it happens — no silent stages, nothing dropped
without telling you.

## Options you can set in plain words

| You say | What it does |
|---|---|
| "quick" / "deep" | picks the path |
| "trend data" / "channels to sponsor" / "both" | picks the results |
| "run autonomously" | no check-ins; deep + both unless you said otherwise |
| "include shorts and live" | widens from the longform-only default |
| "newest first" / "biggest videos" / "since June" | sorts/windows the trend feed |
| "one video per channel" | dedupes the trend feed to each channel's best match |
| "only channels that cover it repeatedly" | focuses the channel table on the recurring tier (default: 3+ matching uploads; say a number to change it) |
| "title matches only" | restricts a keyword to titles — the cleanest field — instead of titles + video descriptions + transcripts |
| "exclude [sense/word]" | adds an exclusion, scoped so it doesn't over-cut the rest of the filter |
| "broaden it" / "narrow it to X" | changes topic breadth mid-run |
| "save it as a report" | persists a named, shareable report |
| "keyword counts" / "how common is each keyword" | the opt-in distribution table (counts per keyword), instead of the full pipeline |

## What the verdicts mean

- **`keep` / `drop` / `unsure`** (keywords, step 3) — `unsure` means the snippets
  didn't settle it; it always gets a targeted second look, never a silent default
  either way.
- **`on_topic` / `mixed` / `off_topic`** (channels, step 6) — `mixed` channels are
  kept and labelled, not dropped; only clear `off_topic` channels are excluded, and
  the excluded list is always shown to you. `unknown` marks a channel whose snippet
  alone didn't settle it.
- **`not_validated`** — a channel that simply wasn't in the batch that got
  evidence-checked (by tier, or a size limit) — not a failed check.
- **`unresolved`** — a check that didn't run because time ran out first; named,
  never silently skipped.

The trade deep makes is **time, not credits**: more measured checks cost more wall
clock, not more spend. The channel-tier triage step is cheap no matter how many
channels exist, so it always runs first, before anything per-channel.

## Example prompts

- "quick: a keyword set for tiktok shop content" — starter filter, one pass
- "deep: find channels for [client] about home fragrance" — full pipeline, channel
  targets with tiers
- "how big is the GRWM trend on youtube right now? trend data only" — prevalence +
  newest matching uploads, no channel list
- "make a topic for cannes lions, run autonomously, both" — no pauses, everything
  delivered at the end
