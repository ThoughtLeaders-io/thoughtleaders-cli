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

- **PROFILE** (channel only, no brand needed): build the two-layer profile —
  `tl-creator-profiles/<channel_id>-facts.jsonl` (the machine ledger other
  skills and CONNECT consume) and `<channel_id>-profile.md` (a ~600–800-word
  human one-pager). Spec: `references/profile-spec.md`.
- **CONNECT** (channel + brand): load (or build) the facts ledger, do a
  deliberately light brand read, and write
  `<channel_id>-<brand_id>-connections.md`, a ranked connection map. A no-fit
  verdict is a valid output.

Two standing rules: all data access from scripts goes through the shared
wrapper (`skills/_shared/tl_data.py` — stdin-passed bodies, timeouts, loud
failures), and a channel or brand name resolves via `tl channels find` /
`tl brands find`, never `ILIKE` on a name. ES query gotchas live in the tl
skill's `references/elasticsearch-schema.md`; the attribution doctrine in
`references/evidence-rules.md`; the transcript pipeline in
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

1. **Fetch + identity, in parallel** — launch both lanes in the SAME
   message (the fetch command and the identity subagent as tool calls in one
   assistant message), so neither waits on the other:
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
   - **Second channels: report, don't mine.** `channel_context.py` emits
     `second_channel_candidates`; the lane resolves each with
     `tl channels find` and the profile's "Other channels" section lists
     them (name, id, video count). Mining a second channel happens ONLY when
     the user explicitly asks — it roughly doubles the run, so it is never
     an automatic decision. A candidate that can't be resolved or read is
     reported "linked but unread".
2. **Channel context brief.** `channel_context.py --corpus ...` measures
   format from the transcripts (first-person density, interview markers); a
   model read of a small sample calls the label with evidence. Not a gate —
   nothing exits early.
3. **Recall pass.** `scripts/selftalk_scan.py --corpus ... --host-terms ...`
   ranks windows locally and writes rank-ordered ~50-window batches. Nothing
   with first-person content is hard-rejected; lexicons only rank. The
   lexicons are English, so on non-English videos they neither rank nor
   drop: every window is kept for the model layer (`--lexicon auto`, the
   default — only ~half the transcript corpus is English). The scan caps
   the batched windows itself (`--max-windows`, default 500); its summary
   reports `windows_over_cap` for the coverage header. The classifiers
   judge in the source language.
4. **Classification — a script, not a fan-out.** Write the context block
   (channel, host names, known facts, format label + evidence) to
   `context.json`, then run `scripts/classify_gems.py --batches ...
   --context context.json`. It calls an OpenAI-compatible endpoint (env:
   `CREATOR_BRIEF_LLM_API_KEY`, `CREATOR_BRIEF_LLM_BASE_URL`,
   `CREATOR_BRIEF_LLM_MODEL`; reference config: OpenRouter +
   `deepseek/deepseek-v3.2`), resumable, JSON-mode enforced, and writes
   `classified.jsonl` + `gems.jsonl`. **State which path the run is on**: no
   API key configured → the script exits code 2 and the fallback is the
   `gem-classifier` agent fan-out (~5–10× the model spend; rules in
   `references/transcript-mining.md`, Layer 3). **Spot-check ~30 verdicts**
   (a mix of accepted and rejected) before trusting a fresh channel's run;
   systematic misses mean switch to the agent fallback.
5. **Fact pass + verification.** ONE small Claude pass (≤2 agents, or the
   main loop when the gem list is small) turns `gems.jsonl` + the identity
   lane's findings into candidate facts — claims, verbatim quote excerpts,
   attribution and sensitivity calls, superseded-fact resolution, the
   `selected` picks (details: `references/transcript-mining.md`, Layer 4).
   Then `scripts/verify_quotes.py --in candidates.jsonl --corpus ...`
   verbatim-verifies every quote locally: exact matches publish (their
   timestamps are authoritative), partial/none get fixed to the caption text
   or dropped. New entities ("my dog Luna") trigger a free local re-scan
   with `--entity-terms`; the classifier resumes over the new windows only.
   Raw transcripts never enter the orchestrating context.
6. **Emit** per `references/profile-spec.md`: the verified ledger
   `<channel_id>-facts.jsonl`, the ~600–800-word one-pager
   `<channel_id>-profile.md`, and the HTML view via
   `scripts/build_html.py --in <profile.md> --facts <facts.jsonl>`. When
   running in a host with an Artifact tool, publish the HTML so the user
   gets a link; the files in `tl-creator-profiles/` are the durable copies.

## CONNECT pipeline

Load `<channel_id>-facts.jsonl` (offer reuse per the spec's Reuse section;
build PROFILE first when it is missing). Then:

1. **Brand read — four lanes, all cheap subagents, all four spawned in ONE
   message, one-shot:**
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
2. **Connection pass.** Put the facts ledger next to the brand read. Three
   types — **direct** (fact ↔ product), **adjacent** (lifestyle fit),
   **category precedent** (one channel-scoped probe of brand-category terms
   for moments the creator already does what the product enables). Follow-up
   queries are **confirm-only**: they deepen a candidate connection, never
   invent one. Emit per `references/profile-spec.md`, then render the HTML
   view (`scripts/build_html.py --in <connections.md>`) and publish it as an
   artifact where the host supports one.

## Guardrails

- **Read-only.** Nothing is sent to anyone; output comes back for review.
- **No prices, costs, rate cards or deal terms in any output**, ever.
- **Not ad copy.** Connection material, not words to read aloud.
- **Sensitive domains** (health, beliefs, children, precise location) are
  flagged and excluded from connections by default.
- **Verbatim or not at all**; a partial quote match never publishes.
- **An empty answer is a real answer** — "no evidence found", with the
  coverage numbers that bound it.
