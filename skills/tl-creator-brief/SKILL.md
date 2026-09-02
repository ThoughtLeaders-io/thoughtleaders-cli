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

- **PROFILE** (channel only, no brand needed): build the reusable ledger —
  `tl-creator-profiles/<channel_id>-facts.jsonl` (the machine ledger other
  skills and CONNECT consume) plus `<channel_id>-meta.json` (when it was
  built, over which videos, what it found) — and hand the user its rendered
  view, `<channel_id>-profile-ledger.html`. Spec: `references/profile-spec.md`.
- **CONNECT** (channel + brand): reuse (or build) the ledger, do a
  deliberately light brand read, write `<channel_id>-<brand_id>-connections.md`
  (a ranked connection map) and render the one designed deliverable,
  `<channel_id>-<brand_id>-connections.html`, with a "who they are" section
  drawn from the ledger. A no-fit verdict is a valid output.

Every run starts the same way, whichever mode: **look for the ledger**
(`## Reuse` below). A found ledger is used and announced; it is rebuilt
only when it is stale or the user says `--rebuild`.

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

## Socials lane — ask up front, default OFF

The identity & socials lane (web search on the creator, their linked
Instagram/X/about pages actually opened and read) is **opt-in**. Ask once, at
the start of the run — before any fetch — as a single question with the
default first:

> **Run the socials/web identity lane?**
> - **No — transcripts only** (default): the creator's own videos are the
>   only source. Faster, and every fact carries a timestamped quote.
> - **Yes — add socials & web**: also search the web for the creator and read
>   their linked profiles, for facts the videos never state and for cross-lane
>   confirmation.

Do not ask when the answer is already settled:

- The initiating request states a preference ("include socials", "check their
  Instagram", "transcripts only", "no web") — honor it, say which lane shape
  you took, and move on.
- The run is **autonomous / no-pause** (`autonomous`, `--auto`, a scheduled or
  unattended run) or a **fast run** — the lane is OFF, no question asked.

Everything below marked *(socials lane ON)* applies only when the answer was
yes.

## Reuse — the found ledger wins

Before any fetch, one command:

```bash
python3 scripts/ledger_meta.py check --channel <id> [--rebuild] [--no-refresh]
```

Pass `--lanes transcripts+socials` when the socials lane is on. Found: it
prints ONE announcement line, which you repeat to the user verbatim, plus a
JSON `decision` — `reuse` (CONNECT skips fetch → extract → merge and lands at
the brand read; PROFILE re-renders the ledger view), `refresh` (run ONE
incremental round, below, then continue) or `build` (run the full PROFILE
pipeline). The thresholds, the flags and the announcement contract live in
`references/profile-spec.md`, "Reuse"; never reuse silently.

**Incremental refresh** (decision `refresh`, round `N` = the JSON's
`next_round`): `fetch_cues.py --channel <id> --host-terms "…" --round N
--exclude <corpus>/<id>/classified.jsonl` (only passages not yet judged are
batched, into `batches-rN/`); fan out extractors over those batches only;
`assemble_extracts.py --batches <corpus>/<id>/batches-rN --returns
<corpus>/<id>/returns-rN --out <corpus>/<id> --append`; re-cluster the whole
`gems.jsonl`; run the merge pass with the existing `<channel_id>-facts.jsonl`
as its starting ledger (keep fact_ids, add, supersede); verify; rewrite the
ledger; `ledger_meta.py write … --rounds N` (descriptive fields not passed
again are carried over from the record). Cost scales with the new uploads,
not the corpus.

## PROFILE pipeline

One retrieval flow, one extraction fan-out, then judgment. Every stage below
prints a `FUNNEL` line; the details live in `references/transcript-mining.md`.

1. **Fetch the cue passages — one script, 7–21 seconds.**

   ```bash
   python3 scripts/fetch_cues.py --channel <id> --host-terms "<surname>,<company>"
   ```

   It asks the index for the transcript passages around first-person cue
   phrases (`references/cue-phrases.txt`) and writes ranked, capped batches of
   25 windows plus a passage-only `corpus.jsonl.gz`. Channel size barely
   moves the clock — a 4,200-video channel costs the same few dozen small
   queries as a 300-video one. **The fetch never waits for anything.** When
   the socials lane is on, launch both in the SAME message; `--host-terms`
   for this first round come from the channel's own metadata and the user's
   request, and any name the lane turns up later feeds a **second round**
   (`--exclude`, step 3a), never a delayed first one.
   - *(socials lane ON)* the identity & socials subagent runs alongside:
     (a) channel metadata via `scripts/channel_context.py`; (b) a web search
     on the creator's and channel's names, top results actually read; (c) the
     channel's social links opened and read — the personal life often lives
     on a different platform than the content. Facts land with `social`/`web`
     provenance and URLs, never dressed as quotes. **Time-box it**: ~8
     lookups, one pass each, no crawling beyond a linked page. Whatever it
     has when the extraction finishes is what the merge pass gets; anything
     unreached is reported "linked but unread".
   - **Second channels: report, don't mine.** `channel_context.py` emits
     `second_channel_candidates`; each is resolved with `tl channels find`
     and listed in the ledger view's "Other channels and platforms" section
     (name, id). Mining one happens ONLY when the user asks — it roughly doubles
     the run.
   - **Lane OFF — what changes.** `channel_context.py` still runs and still
     reports `social_links` and `second_channel_candidates`: every linked
     platform is listed **"linked but unread"** — here because the lane was
     not run, not because reading failed. No `social`/`web` fact exists, so
     the ledger is transcript-only and cross-lane corroboration cannot raise
     anything (`references/profile-spec.md`). Say in the run report that the
     lane was off, and that turning it on is one re-run away.
2. **Channel context brief.** `channel_context.py --channel <id> --corpus ...`
   calls the format label (solo / interview / multi-host / faceless-scripted)
   with evidence. Its corpus stats are now measured over the fetched
   **passages**, not whole transcripts, so read them as a format hint, not a
   census. Not a gate — nothing exits early. Its stdout is the summary only;
   per-video stat rows go to a file via `--per-video-out`.
3. **Extraction fan-out — ~20 agents, one message.** Classification and
   extraction are the same pass. `ls <corpus>/<id>/batches/batch-*.json` is
   the work queue; spawn ONE `tl-cli:gem-classifier` agent per batch file, all
   of them as tool calls in a **single assistant message** (the harness runs
   at most 20 concurrently, so one round is 20 × 25 = 500 windows). Each agent
   gets: the path to `references/gem-classifier.md`, the context block
   verbatim, ONE batch path, and the path to write
   `returns/batch-NNN.extract.json`. It writes that file and returns one line.
   Agents take 2.3–8 minutes each; gem-dense channels run longer. Never spawn
   one at a time, never hand an agent two batches, never a transcript.
   - **3a. A deeper round is additive, not a re-run.** When 500 windows is not
     enough, or the socials lane turned up new host terms, run
     `fetch_cues.py --channel <id> --host-terms "…" --exclude
     <out>/classified.jsonl`: passages already judged are skipped, so the new
     batches are new material, and the round costs another fetch plus another
     fan-out.
4. **Assemble — a script, never a hand patch.**

   ```bash
   python3 scripts/assemble_extracts.py --batches <…>/batches \
     --returns <…>/returns --out <…>
   ```

   It validates the count contract, the echoed `start`, the enums, and cuts
   each quote out of the window text so every quote is verbatim by
   construction. It writes `classified.jsonl`, `gems.jsonl`,
   `candidates.jsonl` and `respawn.json`. **Branch on the exit code**: `0` =
   continue; `3` = `respawn.json` lists the windows that failed or were
   skipped — re-spawn exactly those as one mini-batch of extractor agents,
   re-run assemble, then continue. Never edit a return file by hand.
5. **Cluster the repeats — a script.** `scripts/cluster_gems.py --in
   gems.jsonl` writes `gems-clustered.jsonl` beside it, so a back-catalogue
   channel that has said "BioShock is my favorite game" in thirty videos costs
   the merge pass one read instead of thirty. Merge rules:
   `references/transcript-mining.md`, Layer 4. Do not hand-merge what the
   script left apart.
6. **Merge pass + verification.** ONE agent reads `gems-clustered.jsonl`
   (plus the identity lane's findings when that lane ran) — **never the
   windows, never a transcript** — and finalizes what a script cannot:
   recurrence from **distinct `video_id`s** among a cluster's members,
   deduplication across clusters, the sensitivity tier, superseded-fact
   resolution, the `selected` picks. It drops any candidate whose claim
   asserts more than its quote supports, and re-tiers sensitivity where the
   extractor missed an obvious case. It writes `facts.jsonl`
   (`references/profile-spec.md` shape). Then
   `scripts/verify_quotes.py --in facts.jsonl --corpus ...` re-checks every
   transcript quote against the stored passages: exact matches publish (their
   timestamps are authoritative), partial/none get fixed to the caption text
   or dropped.
7. **Emit** per `references/profile-spec.md`: copy the verified facts to
   `tl-creator-profiles/<channel_id>-facts.jsonl`, then

   ```bash
   python3 scripts/ledger_meta.py write --channel <id> --channel-name "…" \
     --format <label> --format-evidence "…" --context <channel_context.json> \
     [--lanes transcripts+socials]
   python3 scripts/build_html.py --facts tl-creator-profiles/<id>-facts.jsonl \
     --meta tl-creator-profiles/<id>-meta.json
   ```

   The meta record is counted from the build's files, never typed in;
   `--context` is `channel_context.py`'s output saved to a file, so the
   linked platforms ("linked but unread" when the lane was off) and sibling
   channels ("not mined") still reach the page. The ledger view
   `<channel_id>-profile-ledger.html` is PROFILE's human surface — every
   fact, its citation, its sensitivity tier, then the other channels and
   platforms. There is no prose one-pager. When running in a host with an Artifact tool, publish
   the ledger view so the user gets a link; the files in
   `tl-creator-profiles/` are the durable copies.

## Run report — the funnel, every run

Every PROFILE run ends with a funnel table in the **run report** (the CLI
answer to the user), never in the profile itself. Each stage script prints one
`FUNNEL stage=… key=value …` line to stderr; the two model stages are Claude
passes, so **they report their own counts in the same format**. Echo all six
lines, as they were emitted:

```
FUNNEL stage=fetch_cues videos_matched=… passages=… windows_capped=… batches=… sponsor_source=… elapsed_s=…
FUNNEL stage=extract batches=… agents=… windows=… gems=… respawned=… elapsed_s=…   ← you print this one
FUNNEL stage=assemble windows_expected=… windows_assembled=… gems=… respawn_windows=… elapsed_s=…
FUNNEL stage=cluster gems=… clusters=… merged=… elapsed_s=…
FUNNEL stage=merge clusters=… facts=… selected=… dropped=… elapsed_s=…            ← you print this one
FUNNEL stage=verify candidates=… verified=… rejected=… passed_through=… elapsed_s=…
```

Then one line naming the extraction shape and its cost:
`extraction: 20 sonnet agents × 25 windows, one round`. A second `--exclude`
round adds its own fetch/extract/assemble lines rather than replacing the
first round's. Cost and path belong in the run report **once, and never in the
profile**.

And one line saying whether the opt-in socials lane ran, always:
`socials lane: off (transcripts only) — N linked platforms listed unread` or
`socials lane: on — N sources read`. Off is the default, so it is never an
error to report; say it plainly, with "re-run with socials on" as the fix
when the user wants that coverage.

And, when a ledger was found, the reuse announcement line exactly as
`ledger_meta.py check` printed it, plus the decision it took (`reuse`,
`refresh` round N, or `build`).

Why this is mandatory: the connections page shows a dozen facts, while the
ledger holds every verified fact. A run that renders "9 facts" is not a
failed run until the funnel says which stage lost them — without the table
the user cannot tell selection from yield.

## Fast runs

A "fast run" is a run shape, not a script flag (no script takes `--fast`):
PROFILE only, the primary channel only (no second-channel mining), **the
socials lane off, without asking**, the default 500-window cap, and ONE
extraction round — no `--exclude` deepening. Wall clock is the fan-out: the
fetch is 7–21 s and the local scripts are seconds, so a run is roughly one
agent generation (2.3–8 minutes, longer on gem-dense channels) plus the merge
pass. Everything that could outrun that is bounded rather than skipped: the
20-agent round is the cap, the identity lane is time-boxed as in step 1 when
the user turned it on, and the merge pass stays at one agent. Report the
per-stage `elapsed_s` from the funnel lines so a slow run says which stage was
slow. A deeper pass (a second `--exclude` round, a second channel) is always
one re-run away and is never taken on the skill's own initiative.

## CONNECT pipeline

Run the `## Reuse` check first: `reuse` loads `<channel_id>-facts.jsonl` +
`<channel_id>-meta.json` as they are, `refresh` runs one incremental round,
`build` runs the PROFILE pipeline. Then:

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
   invent one. Write `<channel_id>-<brand_id>-connections.md` per
   `references/profile-spec.md` (one `## ` section per connection, strongest
   first, the type as a bold tag on the heading), then render the deliverable:

   ```bash
   python3 scripts/build_html.py \
     --in tl-creator-profiles/<id>-<brand>-connections.md \
     --facts tl-creator-profiles/<id>-facts.jsonl \
     --meta tl-creator-profiles/<id>-meta.json
   ```

   The page opens with **who they are** — the top recurring facts by domain
   and the format label, rendered from the ledger, never written by hand —
   above the ranked connection cards. Publish it as an artifact where the
   host supports one; it is the only page most users see.

## Guardrails

- **Read-only.** Nothing is sent to anyone; output comes back for review.
- **No prices, costs, rate cards or deal terms in any output**, ever.
- **Not ad copy.** Connection material, not words to read aloud.
- **Sensitivity is a tier, not a flag** (`evidence-rules.md`): every fact
  carries `none` | `lifestyle` | `clinical` | `children` | `location`.
  Beliefs are not sensitive. Only `clinical`, `children` and `location` are
  excluded from connection angles by default, and `clinical` is usable when
  the creator discusses it across 3+ videos or frames it as part of their
  story. No protected-trait inference, ever.
- **Verbatim or not at all**; a partial quote match never publishes.
- **An empty answer is a real answer** — "no evidence found", with the
  coverage numbers that bound it.
