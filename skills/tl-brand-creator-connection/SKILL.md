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
  researches the brand, produces an internal connection map (including an
  honest thin-fit or no-fit verdict), and can produce a creator-ready brief
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
| Extraction | provider's fast mid-tier (Sonnet) | `tl-cli:gem-classifier`, bio lane, identity lane, three brand lanes |
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
5. **Host names from `identity`:** take person-name aliases only: first name, full name, unambiguous surname, stated nickname. Never a brand, company, role, employer, product, topic or the bare channel name (these drive speaker attribution and create false second-speaker hints). IF nothing in `identity` names a person, pass `--host-names ""`: on a build, `start_run.py` then takes the name the host says on camera ("my name is …") in two or more uploads, fetches again with it and reports it as `host_names_from_transcripts`; pass those names as `--host-names` to every later command. Never supply a name from memory.
6. **Second call** with `--host-names`, `--reserve`, `--lanes` and any brief flags. On `build`/`refresh` it runs the fetch and context stats (see `ran`); it adds the refresh round flags itself. On `reuse` it fetches nothing: CONNECT goes to CONNECT step 1, PROFILE reports the ledger as it is.

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
- Report second channels; never mine them unless asked. Never start an entity-expansion round on your own initiative.

**Step 2. Format call and prompts.**
Call the format from the `FUNNEL stage=context` line: `solo`, `interview`, `multi_host` or `faceless_scripted`, with one line of evidence. The stats are a hint, not a gate.
- IF `staged_share` > 0.1, name it in the evidence ("solo, 22% of titles are staged premises").
- IF the fetch's `third_person_host_share` > 0.25, the label is `multi_host`.

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
  [--lanes transcripts+socials]
```

PROFILE completion, two lines:
1. The ledger's absolute path.
2. Fact count and what the socials lane did: `socials off, N linked platforms listed unread` or `socials on, N websites opened, N sources read, N facts`. Report "on" with 0 facts as such.

**Fast run** (a run shape, not a flag): PROFILE only, primary channel only, socials OFF without asking, default selection, no corroboration round.

## 4. CONNECT pipeline

**Step 1. Brand lanes.** Spawn three generic subagents in ONE message, pinned to the extraction tier. Build: in the fetch message. Reuse: immediately. Each writes one file under `<corpus>/` and returns one line. Pass every brand id.

- **TL data** → `brand-tl.json` (target < 60 s). Run exactly:
  - `tl brands show <id> --json` per id. Use `company_description`, `what_it_does`, `offer`, `ideal_customers`, `type`, `website`, `sponsored_topics` (`sponsored_topics` is a hint to check against the reads, not a fact).
  - `python3 <skill>/scripts/brand_reads.py --brand <id> [--brand <id2>]` (the brand's newest sponsored reads) and `python3 <skill>/scripts/brand_reads.py --brand <id> --channel <channel_id> --max 50` (this creator's own past reads).
  - One `tl db es` aggregation with `"size": 0`: `term` filter on `sponsored_brand_mentions` with the id as a string (`{"term": {"sponsored_brand_mentions": "50485"}}`), `date_histogram` on `publication_date` by year, `terms` sub-aggregation on `channel.id` (size 20); resolve the ids with `SELECT id, channel_name FROM thoughtleaders_channel WHERE id IN (…) LIMIT 20` via `tl db pg`. There is no `brand.id` or `channel.name` field.
  - Never `tl brands history`. No web lookups.
  - Write `{"brand": {<the show fields>}, "reads": [<rows of the first brand_reads.py call, unchanged>], "this_channel_reads": [<rows of the second, unchanged>], "by_year": {"<year>": <n>}, "top_channels": [{"id", "name", "count"}], "notes": "…"}`. `--check` refuses the other channels' names in the creator brief, and any talking point inside a `this_channel_reads` read or within 45 seconds of it.
- **Brand site** → `brand-site.json`, `{"status": "read | fallback | unreachable", "urls_read": […], "positioning", "product_lines": […], "stated_audience", "cause", "campaign_themes": […], "creator_use", "notes"}` (target < 90 s). Read the `website` from `tl brands show` and only socials linked from that site: positioning, product lines, stated audience, founder story or cause, campaign themes, creator use. One WebFetch per URL; stop at the first failure per host. IF unreachable: use the platform brand record, then ONE WebFetch of `https://en.wikipedia.org/wiki/<brand>` labelled `[web: wikipedia]`. Never search the web for the brand.
- **Category precedent** → `category-probe.json` (target < 90 s). Channel-scoped transcript search for moments the creator already does what the product enables, without naming the brand. Return term counts and the strongest windows with `&t=` links. The `transcript` field is timed-text XML (`<text start="…">`, HTML entities escaped twice); a window is consecutive cues' text, `start` the first cue's seconds. Drop windows that name the brand, a discount code or a link, windows within 60 seconds of any `sponsored` `brand_mentions` span on that video (any brand), and videos whose description names the brand. Max 3 ES queries, `size` ≤ 10, foreground only, no deepening. Write the file when the third query returns: `{"terms": {"<term>": <n>}, "windows": [{"video_id", "start", "published", "url", "text"}], "coverage": {"note": "…"}}`. `text` is the window's words; `--check` matches each precedent card quote against it and applies the card recency rule to `published`. A precedent quote that becomes a talking point contains a first-person word (I, my, we, our).

**Step 2. Connection map.** Start when the merge decisions are saved and `brand-tl.json` exists. Do not wait for the other lanes; name a missing lane in the caveat section. Follow-up queries may only confirm. Write `<corpus>/connections-<brand_id>.md` per `profile-spec.md`, "CONNECT", using the whole ledger, withheld tiers included.

Card rules:
- Every card quotes a ledger fact, or for a category-precedent card a probe window, verbatim: the quote alone on `>` lines, then one `>` line holding only `[<creator>, <YYYY-MM-DD>](<url>&t=<N>s)`, where the date is the quoted video's publish date. Nothing else inside the block.
- A category-precedent card follows the strength and recency rules below, with the window's `published` in place of `last_seen`.
- Write the map, then run `--check`. Each problem it prints is one line naming the rule broken: fix the markdown from that line. Never read the scripts to learn the rules.
- **strong** = the quoted fact itself names what the brand offers. **thin** = the link runs through the channel's format or a generic trait. Heading: `## <title> · **<type>** · **<strength>**`.
- A fact told to argue against what the brand sells is never a card; it goes in "Where this could go wrong". IF the only product-naming facts are of that kind → no fit.
- A strong card rests on a fact with `last_seen` inside the last 24 months. An older fact carries a thin card only with its year stated. The Thesis and "Where this could go wrong" use every fact at any age. An `unconfirmed` or `ended` fact is never quoted on the page; `--check` refuses it.
- Max two thin cards. IF no card is strong: the Thesis says **thin fit**, names the one or two honest angles and what to confirm first, and the verdict sits above the cards. Never pad.

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
- Internal material never reaches the creator brief: strength tags, provenance labels, thesis hedges, "Where this could go wrong". The brief never sets the brand against another product.
- Sensitivity tiers (`evidence-rules.md`): `clinical`, `children`, `location` are never connection angles, but MUST inform fit and "Where this could go wrong" as a category-level warning, never the detail, never a talking point. A lane record naming a person that a withheld-tier fact names inherits that tier. Beliefs are not sensitive. Never infer a protected trait.
- Never drop, demote or supersede a fact for being uncertain; unsettled claims stay `unconfirmed` in the ledger and off every page. A line the window shows is someone else's is not uncertain: it never enters.
- Quotes are verbatim: the full displayed quote must be contained in its verified source. No partial matches, no dubbed tracks.
- IF a response is marked quota-truncated: stop before caching rows, advancing watermarks or publishing. Report the retry information.
- An empty result is reported as "no evidence found" with the coverage numbers.
