---
name: tl-creator-brief
tl-blurb: creator self-disclosure profile, and its connections to a brand
description: >
  Mine a YouTube creator's own transcripts, socials and the web for the
  places they talk about THEMSELVES — history, family, pets, habits, tastes —
  and build a reusable creator profile. Optionally map that profile's real
  connections to a named brand. Triggers: "creator profile", "what do we know
  about [creator]", "find self references", "creator brand connection",
  "personal angle for [channel]", "creator brief", "/tl-creator-brief".
---

# Creator Profile & Connections

Two modes, one contract:

- **PROFILE** (channel only, no brand needed): build
  `tl-creator-profiles/<channel_id>-profile.md` — the stable contract other
  skills and personas consume. Spec: `references/profile-spec.md`.
- **CONNECT** (channel + brand): load (or build) the profile, do a
  deliberately light brand read, and write
  `<channel_id>-<brand_id>-connections.md`, a ranked connection map. A no-fit
  verdict is a valid output.

Read `references/code-reuse.md` before running anything. The attribution
doctrine lives in `references/evidence-rules.md`; the transcript pipeline in
`references/transcript-mining.md`. Bulk-safe by construction: per-channel
output paths, no `cd` anywhere, so many channels can run concurrently.

## Resolve — basic and instant

A unique identifier (URL, @handle, YouTube ID) resolves directly via
`tl channels find`, done. A bare name gets one fuzzy search; if one candidate
clearly dominates (exact name, an order of magnitude more reach, recently
active), auto-pick it and say so; otherwise show the top 3–4 (name, subs,
URL, last upload) and ask — one question, no tie-break machinery. Localized
sister channels (`- Spanish`, `- Deutsch`) are excluded by default and
listed. Brand (CONNECT only): `tl brands find`; a rebrand returns several IDs
— carry them all.

**Plan gate:** `tl whoami --json` → `organization.plan`. `Intelligence` and
`Superuser` proceed. A known lower tier: say so and stop before building a
corpus that cannot be read. An unrecognised value: name it and continue —
tier names change.

## PROFILE pipeline

1. **Fetch + identity, in parallel.** Two independent lanes run
   simultaneously:
   - `scripts/fetch_corpus.py --channel <id>` — one paged sweep brings every
     transcript home (details: `references/transcript-mining.md`).
   - **Identity & socials lane**, in a cheap subagent: (a) the channel's own
     metadata via `scripts/channel_context.py`; (b) a web search on the
     creator's and channel's names, top results actually read; (c) the
     channel's social links opened and read — the personal life often lives
     on a different platform than the content. Facts land with
     `social`/`web` provenance and URLs, never dressed as quotes; a platform
     that blocks reading is reported "linked but unread". Names and handles
     found here feed the scan's `--host-terms`.
   - **Second channels are part of this lane.** `channel_context.py` emits
     `second_channel_candidates` (YouTube links and "my second channel"
     phrasing from the channel's own pointers); also check the channel
     page's featured/linked channels while reading it. When a personal,
     vlog or podcast second channel surfaces, resolve it with
     `tl channels find` and run the fetch + scan over it too — a smaller
     second channel is often the densest self-disclosure source. Facts
     mined there carry the second channel's provenance; a candidate that
     can't be resolved or read is reported "linked but unread".
2. **Channel context brief.** `channel_context.py --corpus ...` measures
   format from the transcripts (first-person density, interview markers); a
   model read of a small sample calls the label with evidence. Not a gate —
   nothing exits early.
3. **Recall pass.** `scripts/selftalk_scan.py --corpus ... --host-terms ...`
   ranks windows locally and writes rank-ordered ~50-window batches. Nothing
   with first-person content is hard-rejected; lexicons only rank.
4. **Model layer.** Fan the batches out to the `gem-classifier` agent
   (haiku) **in parallel**; sonnet confirms the gems (verbatim check,
   attribution reasoning, entity corrections). New entities ("my dog Luna")
   trigger a free local re-scan with `--entity-terms`. Raw transcripts never
   enter the orchestrating context.
5. **Emit** the profile per `references/profile-spec.md`: versioned
   frontmatter, facts by life domain with provenance and confidence,
   sensitive flags, coverage header, "absence is not evidence".

## CONNECT pipeline

1. **Brand read — four parallel lanes, all cheap subagents, one-shot:**
   - **TL data**: `tl brands find` + category + product description, plus
     `scripts/brand_reads.py` — the recency-ordered ad-read sample (weight
     the newest era; an old read can describe a dead product or CTA). Search
     phonetic brand-name variants so mangled reads still count.
   - **Sponsorship patterns**: who the brand sponsors across the corpus, and
     above all *personalization precedents* — moments creators already tie
     this brand to their own lives. Direct evidence of which connection types
     the brand converts. Public signals only — never other clients' internal
     proposals or deal terms.
   - **Web**: website + search results actually read + recent news: current
     positioning, product lines, stated audience.
   - **Brand social**: the brand's own Instagram/X/TikTok — campaign themes,
     how they use creators, and the brand's personal surface (founder story,
     office dog, a championed cause). Connections run both directions.
2. **Connection pass.** Put the profile next to the brand read. Three types —
   **direct** (fact ↔ product), **adjacent** (lifestyle fit), **category
   precedent** (one channel-scoped probe of brand-category terms for moments
   the creator already does what the product enables). Follow-up queries are
   **confirm-only**: they deepen a candidate connection, never invent one.
   Emit per `references/profile-spec.md`.

## Guardrails

- **Read-only.** Nothing is sent to anyone; output comes back for review.
- **No prices, costs, rate cards or deal terms in any output**, ever.
- **Not ad copy.** Connection material, not words to read aloud.
- **Sensitive domains** (health, beliefs, children, precise location) are
  flagged and excluded from connections by default.
- **Verbatim or not at all**; a partial quote match never publishes.
- **An empty answer is a real answer** — "no evidence found", with the
  coverage numbers that bound it.
