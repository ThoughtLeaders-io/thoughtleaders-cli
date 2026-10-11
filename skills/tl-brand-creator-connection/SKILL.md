---
name: tl-brand-creator-connection
tl-blurb: brand ↔ creator connections from a verified creator profile, plus an optional creator brief
description: |
  Find the honest connections between a brand and a YouTube creator, built
  on a reusable, evidence-backed profile from the creator's own words, with
  an optional creator brief the creator can work from. Invoke whenever the
  user asks for a "brand-creator connection", "creator-brand connection",
  "personal angle for [channel]", "creator profile", "what do we know about
  [creator]", "find self references", "creator brief", "creator talking
  points", "a brief I can send the creator", "creator-facing brief",
  "talking points for [channel]", or `/tl-brand-creator-connection`. It mines the
  creator's transcripts for first-person disclosures, verifies every retained
  quote against its timestamped source, resolves contradictions and
  sensitivity, and writes a reusable fact ledger. With a brand, it also
  researches the brand, produces a connection map a brand can read (a fit
  verdict and creative concepts built on the creator's own moments; thin fit
  and no fit are valid verdicts), and can produce a creator-ready brief
  whose talking points are built from the creator's own gems and lead to the
  brand: the brand's own brief mirrored when it sent one, a six-section
  fallback when it did not. Social and web identity research is OPT-IN;
  the creator-facing brief is OPT-IN and asks once for the brand's brief
  and what it is promoting. With neither choice stated, ask once
  for the missing choices before paid research; autonomous/fast runs use
  transcripts only and skip the creator-facing brief. Also invoke for HELP
  asks about this skill; explain the modes and choices without running
  queries.
---

# tl-brand-creator-connection: creator → verified profile → honest brand connection

## Scope

Use for: creator self-disclosure research, a reusable creator profile, an internal creator × brand fit assessment, talking points for a booked or proposed creator campaign.
Do not use for: channel discovery, performance or authenticity analysis, a brand brief with no creator, keyword research. Route those to the matching TL skill.

**Help requests** ("help", "how does this work", "what are the options"): run nothing, spend no credits. Explain PROFILE vs CONNECT, the socials option, the creator-brief option, the evidence and sensitivity rules, and the output files. Offer to start.

## Modes and outputs

| Mode | Input | Output |
|---|---|---|
| PROFILE | channel | `<profiles>/<channel_id>-facts.jsonl` (line 1 meta, then one verified fact per line) |
| CONNECT | channel + brand | ledger (reused or built) + `<profiles>/<channel_id>-<brand_id>-connections.html`. Thin fit and no fit are valid results. |
| CONNECT + brief (opt-in) | + brand talking points | also `<profiles>/<brand>-creator-brief-<creator>.html` |

## Conventions

- `<skill>` = this skill's directory. Run every script as `python3 <skill>/scripts/<name>.py`. Never `cd`.
- `<profiles>` = `tl-creator-profiles/` in the invocation directory, never inside the skill. IF the user names another folder, `<profiles>` = `<folder>/tl-creator-profiles`. Pass `--profiles-dir <profiles>` to `start_run.py` and `ledger_meta.py`, and write every path and link as an absolute path. At run start, print `<profiles>` as an absolute path once. IF it is inside a git checkout, say once that outputs must not be committed.
- `<corpus>` = `<profiles>/.corpus/<channel_id>/`.
- Resolve channel and brand names only with `tl channels find` / `tl brands find`. Never match a name inside a query.
- Every script prints one JSON summary on stdout and a `FUNNEL` line on stderr. Read results from that output, not from the files written. Chain scripts with `&&` in one command.
- IF a script exits 3 because an agent return failed validation: re-ask the agent for exactly the listed items. Never edit a return, decision or rejected-quote file by hand.
- References, open when the step names them: `transcript-mining.md` (script flags, extractor and merge contracts, incremental and corroboration rounds), `profile-spec.md` (ledger format, reuse thresholds, connection-map sections, page), `evidence-rules.md` (attribution, staged premises, sensitivity), `creator-brief-template.md` (creator brief layout).

**Model tiers.**

| Tier | Model | Used by |
|---|---|---|
| Extraction | provider's fast mid-tier (Sonnet) | `tl-cli:cast-sheet`, `tl-cli:gem-classifier`, bio lane, identity lane, three brand lanes |
| Judgment | provider's strongest (Opus) | `tl-cli:merge-shard` only |

Every generic subagent (bio, identity and brand lanes) is pinned to the extraction model explicitly, never the inherited model. These choices are fixed: never ask the user which agents or models to use. IF an agent name does not resolve, spawn the host's generic subagent pinned to the same tier's model and say so. Never use the cheapest model for extraction. Never downgrade the judgment tier; add shards instead.

## 1. Open the run

```bash
python3 <skill>/scripts/start_run.py --channel <ref> [--brand <ref>] \
  [--host-names "<a>,<b>"] [--reserve <N>] [--lanes transcripts+socials] \
  [--rebuild] [--no-refresh] [--creator-brief | --no-creator-brief] \
  [--talking-points <path or text>] [--promoting "<line>"] --profiles-dir <profiles>
```

`<ref>` = URL, @handle, YouTube ID, TL id or name. First call: channel, brand, and only the flags the request already decides.

Handle the summary in this order:

1. **Exit 4 (ambiguous name):** show the top 3-4 of `candidates`, ask once, re-run with the chosen id. IF a brand resolves to several ids (rebrand, duplicate record), pass all of them to every brand lane.
2. **`plan`:** `Intelligence` or `Superuser` → continue. Known lower tier → stop with a message. Unrecognised value → name it and continue. `plan gate: unreachable, continued` → continue.
3. **`announcement`:** repeat it to the user verbatim. It is empty on a first build (no ledger yet): say "No ledger yet: building from scratch." `decision` is `reuse`, `refresh` or `build`. Never reuse silently. Never refuse `--rebuild`.
4. **Ask the open choices** (next section) in ONE message, unless already decided or the run is autonomous/fast.
5. **Host names from `identity`:** IF `identity.cached_host_name` is set, that is the host's name: pass it (first name and full name) plus `identity.cached_host_aliases` as `--host-names` and skip the rest of this point. Otherwise take person-name aliases only: first name, full name, unambiguous surname, stated nickname, from the About text, the generated profile or `description_anchors.names` (what a recurring line of the channel's own upload descriptions calls the host). Never a brand, company, role, employer, product, topic, handle, promo code or the bare channel name (these drive speaker attribution and create false second-speaker hints). IF nothing names a person, pass `--host-names ""`: on a build, `start_run.py` then takes the name the host says on camera ("my name is …") in two or more uploads, or in one upload when the descriptions' promo codes and vanity links spell the same name, or the name a recurring description line gives the host; it fetches again with it and reports `host_names_found` with `host_names_source`. Pass those names as `--host-names` to every later command. IF still none, step 1b may report `host_names_from_cast` (a name the openings give the host in two or more videos): use it the same way. Never supply a name from memory.
6. **Second call** with `--host-names`, `--reserve`, `--lanes` and any brief flags. On `build`/`refresh` it runs the fetch and context stats and renders the cast-sheet prompts (see `ran` and `cast.prompts`); it adds the refresh round flags itself. On `reuse` it fetches nothing: CONNECT goes to CONNECT step 1, PROFILE reports the ledger as it is.

   `--reserve` = 1 (bio lane) + 3 on a CONNECT build (brand lanes) + 1 if socials ON.

   IF the second call exits 3 with `failed: fetch_cues` and the fetch reported `videos_with_transcript=0`: report a corpus gap (not a failure) and stop. Do not build a socials-only ledger.

`--talking-points` / `--promoting` imply `--creator-brief` and write `<corpus>/creator-brief-input-<brand_id>.json` verbatim. They never influence the ledger. `<corpus>/context-full.json` holds the full channel context if `identity` lacks something.

## 2. Open choices

Ask at most once, before any fetch, both questions in one message.

**Socials** (all modes, build or refresh only):
- `--socials`, "include socials", "add web" → ON. `--no-socials`, "transcripts only" → OFF. Autonomous/fast → OFF.
- Otherwise ask:
  > **What should the fan-out read?**
  > - **Transcripts only** (default): the creator's own videos only. Faster; every fact has a timestamped quote.
  > - **Transcripts, socials and web**: also opens the channel page's links and searches the creator's names.

**Creator brief** (CONNECT, only when the summary says `creator_brief: ask`; on `reuse` it is the only question):
  > **Do you want a version you can send to the creator, with talking points for the ad?**
  > - **No** (default): internal connections page only.
  > - **Yes**: also a creator-friendly brief.

IF Yes: one follow-up only: "Paste the brand's brief or talking points (or a file path), and what the brand is promoting. 'We have none' is fine." Pass the answers as `--talking-points` / `--promoting` on the second call. IF the user has no brief or talking points, omit `--talking-points`. Never ask separately for requirements, don'ts or approval process. Autonomous/fast → no brief; the completion line says so.

## 3. PROFILE pipeline (build or refresh)

IF `decision` is `refresh`: the steps below run as one incremental round (`transcript-mining.md`, "Incremental round"). Render and spawn only `<corpus>/batches-rN` into `returns-rN`/`prompts-rN`; pass `--append` to `assemble_extracts.py`; pass `--existing <profiles>/<id>-facts.jsonl --state <corpus>/merge-state.json` to `merge_pass.py prepare` and `expand`; pass `--rounds N` to `ledger_meta.py write`. Never run the build commands as written on a refresh: they rebuild the ledger from the new uploads alone.

**Step 1. Fetch.** Done by the second `start_run.py` call. IF it did not run (check `ran`), run `fetch_cues.py --channel <id> --host-names "…" --reserve <N> --out <profiles>/.corpus` with the round flags from `check` on a refresh (`transcript-mining.md`, "Incremental round").
- CONNECT build: spawn the three brand lanes (CONNECT step 1) in the same message as the fetch.
- Report second channels (`identity.second_channel_candidates`; the ones an earlier run cached carry source `cached`); never mine them unless asked. Never start an entity-expansion round on your own initiative.

**Step 1b. Cast sheet.** Who is on each video, from its own opening. In ONE message (the one that reads the second call's result), spawn one `tl-cli:cast-sheet` (extraction tier) per file in `cast.prompts`, each with the two-line prompt of step 3. When every receipt is in:

```bash
python3 <skill>/scripts/cast_sheet.py apply --sheets <corpus>/cast-sheets.json \
  --returns <corpus>/returns --batches <corpus>/batches --out <corpus>/cast.json \
  --host-names "<a>,<b>" --context-full <corpus>/context-full.json > <corpus>/cast-apply.json
```

On a refresh round N the files are `cast-sheets-rN.json`, `returns-rN` and `batches-rN`. Exit 3: re-spawn the sheets listed in `cast-respawn.json`, re-run apply. IF `cast.prompts` is empty (no openings could be read), skip this step and say so. Read `with_guests`, `formats` and `host_names_from_cast` from the summary: they are evidence for step 2, and `host_names_from_cast` fills empty host names (step 1, point 5). `host_name_cache` says what happened to the host's name on the channel record: a certain name (the sheets and a second source agree) is cached there as `ai_description.host_name` so the next run starts from it; `already set`, `skipped: not certain` and a missing or refused `tl-internal` are reported, never fixed by hand. Say the outcome in one line.

**Step 2. Format call and prompts.**
IF `identity.cached_format_label` is set, that is the label and `cached_format_label_evidence`, when present, its evidence (prefix the evidence with `cached:`; with none, the evidence is `cached:` alone), unless this run's `third_person_host_share` rule below or the cast sheet's majority contradicts it: then call it fresh and say the cache disagreed. Otherwise call the format from the `FUNNEL stage=context` line and the cast sheet's `formats`: `solo`, `interview`, `multi_host` or `faceless_scripted`, with one line of evidence. The stats are a hint, not a gate.
- IF `staged_share` > 0.1, name it in the evidence ("solo, 22% of titles are staged premises").
- IF the fetch's `third_person_host_share` > 0.25, the label is `multi_host`.
- IF most of the cast sheet's judged videos list a guest or a second host, the label is `interview` or `multi_host`, whichever the sheets say more often.

Then, in one chain (drop the `identity_prompt.py` command when socials is OFF):

```bash
python3 <skill>/scripts/channel_context.py --from <corpus>/context-full.json \
  --format-label <label> --format-evidence "<evidence>" \
  [--host-names "<a>,<b>"] [--known-facts "<x>;<y>"] \
  --write-context <corpus>/context.json && \
for b in <corpus>/batches/batch-*.json; do n=$(basename "$b" .json); \
  python3 <skill>/scripts/extractor_prompt.py --batch "$b" --context <corpus>/context.json \
    --write-to <corpus>/returns/$n.extract.json --out <corpus>/prompts/$n.md; done && \
python3 <skill>/scripts/identity_prompt.py render --from <corpus>/context-full.json \
  --context <corpus>/context.json \
  --write-to <corpus>/returns/identity.json --out <corpus>/prompts/identity.md
```

Bio lane, after the chain above returns (it reads `context.json`):

```bash
python3 <skill>/scripts/bio_lane.py batch --from <corpus>/context-full.json \
  --channel <id> --out <profiles>/.corpus && \
python3 <skill>/scripts/extractor_prompt.py --batch <corpus>/bio/batch-000.json \
  --context <corpus>/context.json --lane bio \
  --write-to <corpus>/bio/batch-000.extract.json --out <corpus>/prompts/bio.md
```

IF refresh AND `<corpus>/socials-bio.json` exists, add `--socials-bio <corpus>/socials-bio.json` to `bio_lane.py batch`. IF `bio_lane.py batch` reports `batches: []`, the second command fails harmlessly: skip the bio agent (step 3), `bio_lane.py facts` (step 4) and the corroboration round.

**Step 3. Fan-out.** In ONE message, spawn at extraction tier:
- one `tl-cli:gem-classifier` per `<corpus>/prompts/batch-NNN.md`;
- one `tl-cli:gem-classifier` for `<corpus>/prompts/bio.md`;
- IF socials ON: one generic subagent for `<corpus>/prompts/identity.md`.

Each agent's prompt is exactly: read `<file>` and follow it; one Write; reply with the one-line receipt. Never paste the file content, never two files per agent, never spawn one at a time, never poll or sleep. The merge uses whatever the identity lane has written when the extractors finish; the rest is reported "linked but unread".

**Step 4. Assemble, cluster, prepare.**

```bash
python3 <skill>/scripts/assemble_extracts.py --batches <corpus>/batches \
  --returns <corpus>/returns --out <corpus> > <corpus>/assemble.json && \
python3 <skill>/scripts/cluster_gems.py --in <corpus>/gems.jsonl > <corpus>/cluster.json && \
python3 <skill>/scripts/merge_pass.py prepare --clustered <corpus>/gems-clustered.jsonl \
  --format <label> --channel <id> --out <corpus> > <corpus>/prepare.json && \
python3 <skill>/scripts/bio_lane.py facts --batch <corpus>/bio/batch-000.json \
  --returns <corpus>/bio/batch-000.extract.json --out <corpus>/bio-facts.json \
  --prepare <corpus>/prepare.json
```

IF socials ON, append: `&& python3 <skill>/scripts/identity_prompt.py slice --returns <corpus>/returns/identity.json --prepare <corpus>/prepare.json --out <corpus>`

- Assemble exit 0 with `unjudged_windows` above 0: continue and report the count.
- Assemble exit 3: for each batch in `respawn.json`, re-run `extractor_prompt.py --indexes … --write-to <corpus>/returns/batch-NNN.extract.r2.json`, one agent per batch, then re-run the chain.
- Slice exit 3: re-ask the identity lane for the listed refs.

**Corroboration round** (build only; skip on fast runs and when the bio lane had no batches, and say which): run `python3 <skill>/scripts/bio_lane.py terms --facts <corpus>/bio-facts.json --channel <id> --out <profiles>/.corpus --round 2 --host-names "<host_names from <corpus>/context.json>"`, then every line of the `recipe` it prints, prefixing each script with `<skill>/scripts/`. `--append` is required. Then re-run `cluster_gems.py`, `merge_pass.py prepare` and `bio_lane.py facts --prepare` before step 5.

**Step 5. Merge.** In ONE message (the same one that reads the step 4 result), spawn one `tl-cli:merge-shard` (judgment tier) per shard file listed in `prepare.json`. Each message names its `<corpus>/bio-facts-sN.json` (omitted when the bio lane had no batches) and, IF socials ON, its `<corpus>/identity-facts-sN.json`. A line with `speaker: cohost` is the second host's fact and `shared` is both hosts'; they are judged like the host's, never folded into one person. Write each shard's reply, unchanged, to `<corpus>/merge-decisions-r1-sN.json` with one Write.

```bash
python3 <skill>/scripts/merge_pass.py expand --clustered <corpus>/gems-clustered.jsonl \
  --decisions <corpus>/merge-decisions-r1-s1.json [--decisions …] \
  --format <label> --channel <id> --out <corpus>/facts.jsonl \
  > <corpus>/expand.json 2> <corpus>/expand.err && \
python3 <skill>/scripts/verify_quotes.py --in <corpus>/facts.jsonl \
  --corpus <corpus>/corpus.jsonl.gz --channel-language <language> \
  --drop-unverified > <corpus>/verify.json 2> <corpus>/verify.err
```

IF socials OFF, append the step 6 ledger write to this chain.

- Expand exit 3: send the shard that judged them (SendMessage to the same agent) exactly the listed ids, including supersession date refusals; write its reply, unchanged, to `<corpus>/merge-decisions-r2-sN.json` and add it as another `--decisions`. A later run can list new ids, because the date check runs after the decision check: treat each new id the same way (`-r3-sN.json`). IF an id is listed a second time, add `--fallback-original`.
- Expand also writes `<corpus>/people.json` (one row per person the quotes name) and reports `ended`, `hook_only`, `dated_claims` and `two_names`.
- Report verify's `dropped` count and the path of `facts.jsonl.rejected.jsonl`. To inspect rejects instead, omit `--drop-unverified` (the ledger write will then refuse).

**Step 6. Write the ledger.**
IF socials ON, first:
```bash
python3 <skill>/scripts/channel_context.py --set-socials <corpus>/context-full.json \
  --social-read "<social_read from slice>" --social-unread "<social_unread from slice>"
```
Then:
```bash
python3 <skill>/scripts/ledger_meta.py write --channel <id> --profiles-dir <profiles> \
  --from <corpus>/facts.jsonl.verified.jsonl --channel-name "…" \
  --format <label> --format-evidence "…" --context <corpus>/context-full.json \
  --cast <corpus>/cast.json --host-names "<a>,<b>" [--lanes transcripts+socials]
```

The write also caches on the channel record what the next run can start from: `format_label` (when the cast sheets agree with the call), `host_aliases` (once the host's name is cached) and `sibling_channels`. Its `cache` field says per key `set`, `already set` or `skipped` and why; a cached value is never rewritten by a run, and a missing or refused `tl-internal` only shows there.

PROFILE completion, three lines:
1. The ledger's absolute path.
2. Fact count and what the socials lane did: `socials off, N linked platforms listed unread` or `socials on, N websites opened, N sources read, N facts`. Report "on" with 0 facts as such.
3. What was cached on the channel record this run (host name, format label, host aliases, sibling channels), from `host_name_cache` and `cache`.

**Fast run** (a run shape, not a flag): PROFILE only, primary channel only, socials OFF without asking, default selection, no corroboration round.

## 4. CONNECT pipeline

**Step 1. Brand lanes.** Spawn three generic subagents in ONE message, pinned to the extraction tier. Build: in the fetch message. Reuse: immediately. Each writes one file under `<corpus>/` and returns one line. Pass every brand id.

- **TL data** → `brand-tl.json` (target < 60 s). Run exactly:
  - `tl brands show <id> --json` per id. Use `company_description`, `what_it_does`, `offer`, `ideal_customers`, `type`, `website`, `sponsored_topics` (`sponsored_topics` is a hint to check against the reads, not a fact).
  - `python3 <skill>/scripts/brand_reads.py --brand <id> [--brand <id2>]` (the brand's newest sponsored reads) and `python3 <skill>/scripts/brand_reads.py --brand <id> --channel <channel_id> --max 50` (this creator's own past reads).
  - One `tl db es` aggregation with `"size": 0` over the brand's sponsored mentions: bucket by publication year, then by channel (top 20). Take the field names and the aggregation shape from `<plugin>/skills/tl/references/elasticsearch-schema.md` (the sponsored-mention query patterns and the aggregation example), never from memory. Resolve the channel ids to names with one lookup written from `<plugin>/skills/tl/references/postgres-schema.md` (the channel table), via `tl db pg`.
  - This channel's sponsors in the last 24 months: one `tl db es` aggregation with `"size": 0` over the channel's sponsored mentions, bucketed by brand (top 50), the brand names resolved with `tl brands show`; and one `tl db es` search of the channel's uploads from the same 24 months whose description carries a sponsor line ("partner", "sponsor", "thank you to"), returning each upload's title, publication date and that line. Field names and query shapes from the same `elasticsearch-schema.md`. A detection is a tag, not a deal: report it as tagged, with the description line when there is one.
  - Never `tl brands history`. No web lookups.
  - Write `{"brand": {<the show fields>}, "reads": [<rows of the first brand_reads.py call, unchanged>], "this_channel_reads": [<rows of the second, unchanged>], "by_year": {"<year>": <n>}, "top_channels": [{"id", "name", "count"}], "channel_sponsors": [{"id", "name", "videos", "last_seen"}], "description_tags": [{"video_id", "published", "title", "line"}], "notes": "…"}`. `--check` refuses the other channels' names in the creator brief, and any talking point inside a `this_channel_reads` read or within 45 seconds of it.
- **Brand site** → `brand-site.json`, `{"status": "read | fallback | unreachable", "urls_read": […], "positioning", "product_lines": […], "stated_audience", "cause", "campaign_themes": […], "creator_use", "notes"}` (target < 90 s). Read the `website` from `tl brands show` and only socials linked from that site: positioning, product lines, stated audience, founder story or cause, campaign themes, creator use. One WebFetch per URL; stop at the first failure per host. IF unreachable: use the platform brand record, then ONE WebFetch of `https://en.wikipedia.org/wiki/<brand>` labelled `[web: wikipedia]`. Never search the web for the brand.
- **Brand moments** → `category-probe.json` (target < 120 s). Channel-scoped transcript search for the creator's own moments, in two lists:
  - `windows`: the creator in the moment the product is used, or already doing what it enables (thirst on a stunt for a hydration brand, a late-night food run for a restaurant, a hideout that runs on a phone signal for a carrier), found by the product's use words.
  - `brand_windows`: the creator naming the brand or its products unpaid, found by the brand and product names, from uploads the brand did not sponsor.
  Return term counts and the strongest windows with `&t=` links, each with the upload's title and views. The `transcript` field is timed-text XML (`<text start="…">`, HTML entities escaped twice); a window is consecutive cues' text, `start` the first cue's seconds. Keep the creator's own lines: first person, or their narration of their own stunt. A line said by a friend, guest, contestant or commentator stays out, and so does a window that does not show who is speaking. Drop windows with a discount code or a link, and windows within 60 seconds of any `sponsored` `brand_mentions` span on that video (any brand). Max 8 ES queries, `size` ≤ 20, foreground only, no deepening. Write the file when the last query returns: `{"terms": {"<term>": <n>}, "windows": [{"video_id", "start", "published", "url", "title", "views", "text"}], "brand_windows": [<same shape>], "coverage": {"note": "…"}}`. `text` is the window's words; `--check` matches each lead quote and each quoted further moment against the windows or the ledger, and applies the recency rule to `published`. A window quote that becomes a talking point contains a first-person word (I, my, we, our).

**Step 2. Connection map.** Start when the merge decisions are saved and `brand-tl.json` exists. Do not wait for the other lanes; name a missing lane in the completion line. Follow-up queries may only confirm. Write `<corpus>/connections-<brand_id>.md` per `profile-spec.md`, "CONNECT", using the whole ledger, withheld tiers included.

The map is written for the brand: to judge the fit, or to pitch with. Look for the fit first. A no-fit verdict is for a pairing where nothing in the creator's moments meets what the brand sells.

Concept rules:
- Each concept is one piece of content the creator could make for the brand, built on a moment from their own videos. Heading: `## <name> · **<type>** · **<strength>**`. Type: `direct` (a ledger fact names what the brand offers), `adjacent` (a ledger fact about their life where the product fits), `category precedent` (a `windows` moment), `brand moment` (a `brand_windows` moment).
- The lead quote is a ledger fact or a lane window, verbatim: the quote alone on `>` lines, then one `>` line holding only `[<creator>, <YYYY-MM-DD>](<url>&t=<N>s)`, where the date is the quoted video's publish date. Nothing else inside the block.
- Then, in order: `The moment:` one sentence; two or three further moments, each `- [<YYYY-MM-DD>](<url>&t=<N>s) <what happens>: "<their words>"` with the words from a lane window or the ledger; `The concept:` the content they could make; at most one `Sample line (illustration only): "…"`; `Do:` and `Don't:`, both concrete.
- **strong** = the moment puts the creator where the product is used, or the brand already appears on the channel unpaid. **thin** = the link runs only through the channel's format or a generic trait. At most two thin concepts.
- The lead quote of a strong concept is from the last 24 months (a ledger fact's `last_seen`, a window's `published`). Older moments back a concept as dated backstory, with the year shown.
- A fact told to argue against what the brand sells is never a concept; it shapes the guardrails. IF the only product-naming facts are of that kind → no fit.
- `## Verdict` opens with `**Strong fit.**` when any concept is strong, `**Thin fit.**` when every concept is thin, `**No fit.**` with no concepts. Then three or four sentences on why, and a `Best-fit products:` line.
- `## About <creator>`: two or three sentences, then up to 10 lines `- f021+f010: <line>`, the facts a brand would want to know about the person, recent and past. Facts that say the same thing share one line, ids joined with `+`. A fact that only restates what the channel page shows (the posting schedule, the format) gives way to one about the person. A past phase is listed as the past.
- Every fact the page quotes or lists is `confirmed` and not `ended`; the page states what the videos show and asks the reader to check nothing with the creator's team.
- Write the map, then run `--check`. Each problem it prints is one line naming the rule broken: fix the markdown from that line. Never read the scripts to learn the rules.

```bash
python3 <skill>/scripts/build_html.py --check --in <corpus>/connections-<brand_id>.md \
  --facts <profiles>/<id>-facts.jsonl && \
python3 <skill>/scripts/build_html.py --in <corpus>/connections-<brand_id>.md \
  --facts <profiles>/<id>-facts.jsonl
```

`--check` exit 3: fix the markdown, never the checker. IF an Artifact tool exists, publish the `.fragment.html`; otherwise `open` the page. Without a brief, CONNECT completion: the page's absolute path, the artifact link if any, and one line naming any brand lane that fell back or was unreachable.

**Step 3. Creator brief** (only if `creator_brief: on`). IF the verdict is no fit, skip and say why. Otherwise read `<corpus>/creator-brief-input-<brand_id>.json`, the connection map, the whole ledger, and the creator's past reads for this brand in `brand-tl.json` `this_channel_reads` (never build a point on a moment from one).

1. Search the finished ledger only (no new retrieval). For each confirmed gem with `last_seen` inside the last 24 months that fits the brand (a story with people and details, a turning point, something they built, a long-kept habit, how they describe themselves), write the talking point only this creator could make about the product. An older or `ended` gem is background only, with its year, never a talking point.
2. Place each brand line under the point whose gem backs it best. A gem that leads to the product but to no brand line becomes a creative point under the promoting line.
3. Write `<corpus>/creator-brief-<brand_id>.md` per `creator-brief-template.md`:
   - IF `brand_brief` is set: the brand's document word for word, in their order, with a "For you" block (from one of this creator's gems) under each point a gem backs, and at most two creative blocks after their last point.
   - ELSE: the template's six sections, every point built from a gem. With no brief at all, product facts come from the map's About brand section and the rest follows "When the brand sent no brief".
4. Second person, every quote with its `&t=` link, none of the map's internal vocabulary.

```bash
python3 <skill>/scripts/build_html.py --brief --check --in <corpus>/creator-brief-<brand_id>.md \
  --facts <profiles>/<id>-facts.jsonl --connections <corpus>/connections-<brand_id>.md \
  --input <corpus>/creator-brief-input-<brand_id>.json && \
python3 <skill>/scripts/build_html.py --brief --in <corpus>/creator-brief-<brand_id>.md \
  --facts <profiles>/<id>-facts.jsonl --connections <corpus>/connections-<brand_id>.md \
  --input <corpus>/creator-brief-input-<brand_id>.json
```

Publish the fragment where possible. Completion: both absolute paths, artifact links if any, the brand-lane line.

## Guardrails

- Read-only. Nothing is sent to anyone, including the creator brief.
- No prices, costs, rate cards or deal terms in any output.
- At most one labelled sample read per connection ("you could" in the brief). No scripts, full reads, CTA wording or alternates.
- Internal material never reaches the creator brief: strength tags, provenance labels, verdict hedges, "Creative guardrails", "Good to know when booking". The brief never sets the brand against another product.
- Sensitivity tiers (`evidence-rules.md`): `clinical`, `children`, `location` are never connection angles, but MUST inform fit and the creative guardrails as a category-level guardrail ("keep the product away from talk of mood"), never the detail, never a talking point. A lane record naming a person that a withheld-tier fact names inherits that tier. Beliefs are not sensitive. Never infer a protected trait.
- Never drop, demote or supersede a fact for being uncertain; unsettled claims stay `unconfirmed` in the ledger and off every page. A line the window shows is someone else's is not uncertain: it never enters.
- Quotes are verbatim: the full displayed quote must be contained in its verified source. No partial matches, no dubbed tracks.
- IF a response is marked quota-truncated: stop before caching rows, advancing watermarks or publishing. Report the retry information.
- An empty result is reported as "no evidence found" with the coverage numbers.
