---
name: tl-creator-brief
tl-blurb: creator self-disclosure profile, and its connections to a brand
description: >
  Mine a YouTube creator's own transcripts (and, opt-in, their socials and the
  web) for the places they talk about THEMSELVES, their history, family, pets,
  habits and tastes, and build a reusable creator profile. Optionally map that
  profile's real connections to a named brand. Triggers: "creator profile",
  "what do we know about [creator]", "find self references", "creator brand
  connection", "personal angle for [channel]", "creator brief",
  "/tl-creator-brief".
---

# Creator Profile & Connections

Two modes, one contract:

- **PROFILE** (channel only): build the ledger
  `tl-creator-profiles/<channel_id>-facts.jsonl`: line 1 the meta record
  (when, over which videos, what it found), then one verified fact per line.
  Other skills and CONNECT consume it. No human page: PROFILE ends with two
  lines in chat, the ledger's absolute path and its fact count.
- **CONNECT** (channel + brand): reuse or build the ledger, read the brand
  lightly, and render the one human page,
  `tl-creator-profiles/<channel_id>-<brand_id>-connections.html`. A no-fit
  verdict is a valid output, and so is a thin fit.

`<skill>` is this skill's own directory (the installed plugin's copy); every
command is `python3 <skill>/scripts/…`. Outputs land under the **invocation
directory**, never inside the skill. At the start of the run, print that
directory's absolute path once; if it sits inside a git checkout, say so once (the
outputs are client-adjacent data and must not be committed). `<corpus>` is
`tl-creator-profiles/.corpus/<channel_id>/`, the working directory.

Detail lives in three references; open the one you need:
`references/transcript-mining.md` (script flags, the extractor and merge
contracts, the authentication probe, the incremental round),
`references/profile-spec.md` (ledger and meta formats, the connection map's
sections, strength tags, the page), `references/evidence-rules.md` (what
counts, attribution, staged premises, sensitivity).

Standing rules: scripts reach the platform only through
`skills/_shared/tl_data.py`; names resolve via `tl channels find` /
`tl brands find`, never a name match in a query; no `cd`; per-channel paths.
Agent names below are written `<plugin>:gem-classifier` and
`<plugin>:merge-shard`, where `<plugin>` is the installed plugin's namespace
(`tl-cli` in production, `tl-cli-pr91` on a side-by-side test install).

## Start the run

Resolve, plan gate, channel context and the reuse check were four turns with
no judgment between them, and a turn between two stages costs more than most
of these stages do. They are one command:

```bash
python3 <skill>/scripts/start_run.py --channel <ref> [--brand <ref>] \
  [--host-terms "<surname>,<company>"] [--reserve <N>] \
  [--lanes transcripts+socials] [--rebuild] [--no-refresh]
```

`<ref>` is a URL, @handle, YouTube ID, numeric TL id or a name. One JSON
summary on stdout, every stage's own `FUNNEL` line on stderr.

- **Exit 4: a name did not resolve to one record, and nothing else ran.**
  The candidates are on stdout under `ask` and `candidates`: show the top 3
  or 4, ask once, call again with the id. A channel that already resolved is
  handed back with them, so the re-ask does not pay for it twice. Resolution
  itself belongs to `tl channels find` / `tl brands find`, which auto-pick a
  dominant candidate; never match a name in a query. A rebrand, or a name
  that resolves to more than one record (an apostrophe variant, a stub next
  to an enriched record), returns several brand IDs: carry them all into
  every brand lane.
- **`plan` and `plan_ok` are on the summary, and the rule is still yours**:
  `Intelligence` or `Superuser` proceeds, a known lower tier stops with a
  message, an unrecognised value is named and continues. The gate is bounded
  at 20 s with one retry inside the script (macOS has no `timeout`); when it
  cannot be reached, `plan_note` is `plan gate: unreachable, continued` and
  the run goes on.
- **`announcement` is the ledger's own line**: repeat it to the user
  verbatim. `decision` is `reuse`, `refresh` or `build`, and it is never
  silent. See "Reuse" below for what each one means.
- **Host terms are the one judgment in the opening, so they are not
  guessed.** With no `--host-terms` the command stops after the reuse check
  and hands back `identity`: the channel name, the About text, the generated
  profile, the websites, the social links and the second-channel candidates.
  Take the terms from it (surname, company, former role, anything the About
  text or the profile names) and run PROFILE step 1 in your next message.
  The channel name alone is not host terms: HopeScope ran with
  `"HopeScope,Hope"` and took 22 anchor soft mismatches.
- **`--host-terms` given, the opening is one turn**: the command runs the
  bounded fetch and the context stats too, and `ran` says which stages went.
  Pass it only when the request already names the terms.

The full context is written to `<corpus>/context-full.json` either way, so
anything `identity` leaves out is one Read away.

## Socials lane (opt-in)

The question is what the fan-out searches, not whether a separate stage runs.
Finding the creator's links is part of channel context either way (step 0);
what this gates is whether the fan-out that reads the transcripts also opens
those links and searches the web. It runs only when asked for:

- `--socials`, "include socials", "add web": ON, no question.
- `--no-socials`, "transcripts only": OFF, no question.
- Nothing said and the run is interactive: ask once, before any fetch, the
  default first:

  > **What should the fan-out read?**
  > - **Transcripts only** (default): the creator's own videos are the only
  >   source. Faster, and every fact carries a timestamped quote.
  > - **Transcripts, socials and web**: the same fan-out also opens the links
  >   on the channel page and searches the creator's names, for facts the
  >   videos never state and for cross-lane confirmation.

- Autonomous, unattended, or a fast run: OFF, nothing asked.

This is the only turn in the run that waits on a person, and it comes before
any fetch so the answer can size `--reserve`. The completion lines say whether
the socials half ran. *(socials ON)* below means only when it is on.

## Reuse: every run starts here

`start_run.py` runs the check (`ledger_meta.py check --channel <id>
[--lanes …] [--rebuild] [--no-refresh]`, if you ever need it on its own).
A found ledger gives one announcement line, which you repeat to the user
verbatim, and a `decision`:

- `reuse`: CONNECT goes straight to the brand read; PROFILE reports the
  ledger as it is.
- `refresh`: run one incremental round (`transcript-mining.md`, "Incremental
  round"), then continue.
- `build`: run the PROFILE pipeline.

Never reuse silently; never refuse `--rebuild`.

## PROFILE pipeline

Every stage prints a `FUNNEL` line to stderr; they are for debugging, not a
deliverable. The stages are `identity` and `context` (both
`channel_context.py`), `fetch_cues`, `assemble`, `cluster`, `merge-prepare`,
`merge`, `authenticate`, `verify`, and on the CONNECT side `brand_read`
(`brand_reads.py`) and `render` or `check` (`build_html.py`). Read them off
the command you just ran rather than opening the file it wrote. Scripts that
take under a second are chained with `&&` in one command: a turn between two
scripts costs more than the scripts.

0. **Channel context first.** `start_run.py` has already done this
   (`channel_context.py --channel <id> > <corpus>/context-full.json`, if you
   ever need it on its own) and handed back the `identity` block. Read that
   block, not the file, unless it leaves out something you need.

   This is the platform's own record of the channel: name, About text, the
   AI profile, sibling-channel candidates, language, and the creator's own
   links. Read it and take the host terms from it (surname, company, former
   role, anything the About text or AI profile names). The old order asked
   for the surname at fetch time and only produced it afterwards; HopeScope
   ran with `"HopeScope,Hope"` and 22 anchor soft-mismatches.

   **Identity discovery happens here, not in a lane of its own.** The links
   come from both stores at once: `websites` is the labelled header links the
   creator wrote on their own channel page (a personal site, a company), and
   `social_links` unions the platform keys from Postgres with the index's flat
   list, deduped. The sites are where the identity lane starts, because the
   site says who the person is and links the socials worth reading. Emails are
   dropped; a contact address is not a fact about a person.

   Both stores come back empty on plenty of channels, and an empty pair is a
   real answer, not a failure. Say so once and carry on: the identity lane
   then has the channel name, the About text and the AI profile and nothing
   else, and it must be told that, or it will read the AI profile as the whole
   truth about the person. Alexa Rivera (2026-09-10) had `{}` in Postgres and
   `[]` in the index; the lane was handed only the AI profile, whose emphasis
   on recent uploads led it to rule out the correct creator and return nothing.

1. **Fetch the cue passages**, and spawn the lanes that need only the ids.
   *(Already run if you passed `--host-terms` to `start_run.py`: check `ran`
   on its summary and go to step 2.)*

   ```bash
   python3 <skill>/scripts/fetch_cues.py --channel <id> \
     --host-terms "<surname>,<company>" --reserve <N>
   ```

   On a `refresh` decision, add the round flags from the start summary's
   `check`: `--round <next_round> --since <latest_video_date> --exclude
   <corpus>/classified.jsonl` (`transcript-mining.md`, "Incremental round").

   Writes `<corpus>/windows.jsonl.gz`, `<corpus>/batches/batch-NNN.json` (one
   file per extractor agent, sized to fill one wave of the host's agent cap)
   and `<corpus>/corpus.jsonl.gz`. `--out` names the parent, not the channel
   directory. `--reserve` is one slot per agent that will be running during
   the extraction fan-out: **3 for the brand lanes on a CONNECT build**, plus
   1 when the socials lane is on, 0 on a plain PROFILE run.
   - On an English-language channel, non-English transcript tracks are
     YouTube auto-dubs, not the creator's words: the fetch excludes them and
     reports `dubbed_excluded`. A non-English channel keeps its own-language
     sampling.
   - **CONNECT build: spawn the three brand lanes in this same message**
     (their brief is under "CONNECT pipeline", step 1). They need only the
     channel and brand ids, they run while the fetch and the extraction run,
     and they are in before the merge decisions are.
   - Second channels are reported, never mined, unless the user asks. A
     deeper round (`--exclude <corpus>/classified.jsonl`, `transcript-mining.md`
     "Entity expansion") is never taken on the skill's own initiative.

2. **Context stats, format call, prompts.** First the stats over the fetched
   passages:

   ```bash
   python3 <skill>/scripts/channel_context.py --channel <id> \
     --corpus <corpus>/corpus.jsonl.gz --per-video-out <corpus>/per-video.jsonl \
     > <corpus>/context-full.json
   ```

   This pass also writes `name_candidates`: the other names the creator calls
   themselves, harvested from the passages just fetched. Each row carries the
   distinct-video count, whether the name was said outright ("my name is …",
   "call me …") and whether it is a short relative of the channel name. **The
   variants are the identity lane's search terms**, because the name on the
   channel is often not the name the audience, the press or their own profiles
   use: "Alexa Rivera" is Lexi, "Patterrz" is Pat, "Airrack" is Eric. A row
   that is not a variant is somebody else the creator named on camera, useful
   for confirming an identity and never for searching one. These are search
   terms only; a name reaches the ledger solely as a transcript fact with its
   own quote.

   **Call the format from that command's own `FUNNEL stage=context` line**,
   not from a Read of the file it just wrote: the line carries every number
   the call is made from (`videos`, `fp_density_median`,
   `interview_marker_videos`, `question_density`, `title_hint_videos`,
   `staged_share`, `likely_faceless`). Open `context-full.json` only when the
   line is genuinely ambiguous, since that Read is a turn of its own and a
   turn costs more than the stage did.

   Call the format (`solo`, `interview`, `multi_host`, `faceless_scripted`)
   with one line of evidence that also names `staged_share` when it is above
   0.1 ("solo, 22% of titles are staged premises"); the stats are a hint,
   never a gate. Then write the context block and render every batch's
   message in one chain:

   ```bash
   python3 <skill>/scripts/channel_context.py --from <corpus>/context-full.json \
     --format-label <label> --format-evidence "<evidence>" \
     [--host-names "<a>,<b>"] [--known-facts "<x>;<y>"] \
     --write-context <corpus>/context.json && \
   for b in <corpus>/batches/batch-*.json; do n=$(basename "$b" .json); \
     python3 <skill>/scripts/extractor_prompt.py --batch "$b" \
       --context <corpus>/context.json \
       --write-to <corpus>/returns/$n.extract.json --out <corpus>/prompts/$n.md; \
   done
   ```

3. **One fan-out: transcripts and identity in the SAME message.** One
   `<plugin>:gem-classifier` agent per `<corpus>/prompts/batch-NNN.md`, plus
   *(socials ON)* the identity lane, all spawned in a single assistant message
   with nothing else in flight. This is the run's only extraction fan-out;
   sourcing the creator is one act, not a transcript stage with a socials
   stage bolted beside it. The extractors cannot start earlier than this, as
   their prompt files do not exist until step 2 has rendered them, so this is
   the first moment all three sources can go out together.

   The extractor prompt is two lines: read that one file and follow it
   exactly; one Write, then the one-line receipt. Never paste the message in,
   never two batches per agent, never one at a time, never poll or sleep. If
   the agent name does not resolve, use `general-purpose` with `model: sonnet`
   and say so. The cap is `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (20 when
   unset), which `--reserve` has already been sized against.

   - *(socials ON)* The identity lane: `general-purpose`, **`model: sonnet`**,
     about 8 lookups. Its prompt carries, from `context-full.json`, the
     `websites` and `social_links` step 0 found, the channel name, **every
     `name_candidates` variant**, **the About text and the AI profile**, and
     the host terms and format label the run has called. It opens the sites
     first, then the socials they link, then a web search. Put the
     `social`/`web` fact record and its enums from `profile-spec.md` in its
     prompt, or it invents labels that `expand` rejects.
   - **Search the names the creator uses, not only the channel's.** Spend the
     first lookups on `<variant> <surname>` before the channel name, because
     the channel name is what a namesake will outrank you on and the nickname
     is what the profiles are actually under. A link-in-bio aggregator
     (Linktree, hoo.be, Beacons) found this way is the highest-value hit on a
     channel that lists nothing, since it is the creator's own index of every
     profile they own: read it and take the links from it. Searching "Alexa
     Rivera Instagram" returns a same-named creator; "Lexi Rivera Instagram"
     returns `@lexibrookerivera` and a Linktree at `AlexaBrookeRivera`, which
     is the name on the channel and the nickname in one string.
   - **Confirm the identity before reporting a single fact.** The cheapest
     proof is a link back: an aggregator or profile that points at the channel
     under investigation has identified itself, and no further checking is
     needed. Alexa Rivera's aggregator lists Instagram, TikTok, X, Facebook and
     Patreon, and its YouTube link is `/c/AlexaRivera`, the channel the run
     started from. Failing a link back, confirm against the non-variant
     `name_candidates` and the recurring co-stars in the titles: a profile is
     the right person when the people around it are the people in the videos.
     Say in one line which candidate you accepted and what confirmed it. On a
     mismatch return no facts and name the candidate you rejected and why, so
     the run reports an empty lane rather than a wrong one.
   - A contact address found on any of these pages is not a fact about the
     person and never travels, matching the rule the link harvest already
     applies to the channel's own header.
   - **Tell it what the platform record is worth.** The About text is often
     YouTube's default placeholder, and the AI profile describes the recent
     catalogue, not the person: both are context to search from, never the
     identity itself, and neither is a fact. A lane that treats the AI profile
     as the description of the creator will reject the right person for not
     matching it.
   - **It is the one lane with transcript evidence available**, because it now
     runs beside the extractors rather than ahead of them. When the linked
     stores were empty, name the recurring people, places and formats the run
     has already seen in the titles, so the lane has something to disambiguate
     a common name against. A wrong identity is worse than an empty lane: on a
     mismatch it returns no facts and says which candidate it rejected and why.
   - What it has when the extractors finish is what the merge pass gets; the
     rest is reported "linked but unread".

4. **Assemble, cluster, prepare, authenticate: one command.** As soon as the
   receipts are in:

   ```bash
   python3 <skill>/scripts/assemble_extracts.py --batches <corpus>/batches \
     --returns <corpus>/returns --out <corpus> > <corpus>/assemble.json && \
   python3 <skill>/scripts/cluster_gems.py --in <corpus>/gems.jsonl > <corpus>/cluster.json && \
   python3 <skill>/scripts/merge_pass.py prepare --clustered <corpus>/gems-clustered.jsonl \
     --format <label> --channel <id> --out <corpus> > <corpus>/prepare.json
   ```

   Assemble cuts every quote out of the window text (verbatim by
   construction) and exits 0 while coverage is at least 0.95. Exit 3 stops
   the chain: re-judge exactly the windows in `respawn.json` with
   `extractor_prompt.py --indexes … --write-to <corpus>/returns/batch-NNN.extract.r2.json`,
   one agent per batch, then re-run. Never edit a return file by hand.
   `prepare` sizes the shards itself (clusters / 40, floor 1, ceiling 6;
   shards hold whole life domains) and, with `--channel`, runs
   `authenticate.py`: every staged-premise claim in a durable domain and
   every pair of contradicting clusters gets one channel-scoped query, and
   the evidence lands on the merge-input line (`staged`, `conflicts_with`,
   `probe`). `prepare.json` lists the shard files and sizes. Spawn the merge
   agents in the same message that reads this result.

5. **Merge pass: sharded agents decide, the script builds the ledger.**
   One `<plugin>:merge-shard` agent per file in `prepare.json` (`merge-input-N.jsonl`,
   or `merge-input.jsonl` when there is one), all in one message. The agent
   pins **Opus, deliberately**; shard it rather than downgrade it. If the
   agent name does not resolve, use `general-purpose` with `model: opus`,
   say so, and expect the two enum failures its brief exists to prevent: an
   invented `action` value, and a narrowed claim dated from the line's
   `published` field. Each reads its compact cluster lines, never the
   windows, and returns one JSON object of decisions (`keep` / `fold` /
   `drop`, `selected` picks, *(socials ON)* the lane's facts; contract in
   `transcript-mining.md`, Layer 4). Save each as
   `<corpus>/merge-decisions-r1-sN.json`. **Nothing is dropped for being
   uncertain**: a staged or contradicted claim is kept and judged on the
   probe's evidence, per `evidence-rules.md`.

   *(socials ON, more than one shard)* Split the lane's facts by life domain
   too, one slice per shard, so each agent judges the lane records that sit
   beside the clusters it can see and `corroborates` can reach them. `expand`
   unions the slices by `ref`, so a shard whose domains hold no lane record
   returns `"facts": []` and costs nothing. Socials OFF means no lane and
   nothing to divide. Then:

   ```bash
   python3 <skill>/scripts/merge_pass.py expand --clustered <corpus>/gems-clustered.jsonl \
     --decisions <corpus>/merge-decisions-r1-s1.json [--decisions …] \
     --format <label> --channel <id> --out <corpus>/facts.jsonl \
     > <corpus>/expand.json 2> <corpus>/expand.err && \
   python3 <skill>/scripts/verify_quotes.py --in <corpus>/facts.jsonl \
     --corpus <corpus>/corpus.jsonl.gz --channel-language <language from context-full.json> \
     > <corpus>/verify.json 2> <corpus>/verify.err
   ```

   **Socials OFF: put step 6's ledger write on the end of this same chain**
   and the whole tail is one turn. All three are scripts, and the last two
   stop on the same condition: `verify_quotes.py` exits 1 when any quote is
   partial, missing or dubbed, and `ledger_meta.py write --from` refuses
   (exit 2, nothing written) on exactly those facts. So `&&` stops where a
   fix is needed and nowhere else, and a clean verify writes the ledger
   without a turn in between. Socials ON keeps step 6 separate, because
   `--set-socials` has to record the lane's answer before the write.

   Expand exits 3 listing offending ids: re-ask for exactly those once as
   another `--decisions` file; on a second failure add `--fallback-original`.
   A supersession that points against the dated evidence (the superseded
   cluster's newest upload, or a lane record corroborating it, is newer than
   the superseder's) is one of those refusals, and the message carries the
   dates: hand it back to the shard as written. Never hand-patch a decision.
   Verify re-locates every quote; only exact matches publish, partial or
   none get fixed to the caption text or dropped, and a quote not in the
   channel's language (`dubbed`) never publishes.

6. **Write the ledger.** *(socials OFF: this is the command you already
   chained onto step 5, and this step is done.)*

   *(socials ON)* First record which linked platforms the lane actually
   opened, since only the lane knows and the honesty strip reports it:

   ```bash
   python3 <skill>/scripts/channel_context.py --set-socials <corpus>/context-full.json \
     --social-read "<links it opened>" --social-unread "<links it did not>"
   ```

   Skip it on a socials-OFF run. Without it the page cannot tell one link
   from another and reports every linked platform as read whenever the lane
   ran at all, including pages it never opened.

   ```bash
   python3 <skill>/scripts/ledger_meta.py write --channel <id> \
     --from <corpus>/facts.jsonl.verified.jsonl --channel-name "…" \
     --format <label> --format-evidence "…" --context <corpus>/context-full.json \
     [--lanes transcripts+socials]
   ```

   Refuses (exit 2, nothing written) any transcript fact whose verification
   is not `exact`. PROFILE ends here, with two lines: the ledger's absolute
   path and its fact count.

   The second line reports the socials half by what it actually did, never
   just on or off: `off, N linked platforms listed unread`, or `on, N websites
   opened, N sources read, N facts`. "On" with zero facts is a result the
   reader has to see, because the lane can run, read a source, reject the
   identity and return nothing; a bare "on" reads as though socials
   corroborated the ledger when it contributed nothing to it.

## Fast run

A run shape, not a flag: PROFILE only, the primary channel only, socials OFF
without asking, the default 300-window cap, one extraction round.

## CONNECT pipeline

Run the reuse check first. Then:

1. **Brand read: three agents in ONE message, as soon as the brand resolves.**
   On a build that is the fetch message (PROFILE step 1), so the lanes run
   under the extraction and are in before the merge; on a reuse it is
   immediately. All three are `general-purpose` with an explicit
   **`model: sonnet`**, never the inherited model, need only the channel and
   brand ids, and are quick and light by design: gathering brand information
   is background, not research. Each writes one file under `<corpus>/` and
   returns one line.
   - **TL data** (target under 60 s), writes `<corpus>/brand-tl.json`. Exactly
     these, nothing improvised: `tl brands find` for every brand id (category,
     product description, stated audience, sponsored topics);
     `python3 <skill>/scripts/brand_reads.py --brand <id> [--brand <id2>]` for
     the newest sponsored reads (those reads ARE the sponsorship patterns:
     what creators already say about the product on camera and the moments
     they tie it to their own lives); and for the eras, one `tl db es`
     aggregation, a `date_histogram` on `publication_date` by year over
     `sponsored_brand_mentions` for the brand ids with a `terms` sub-aggregation
     on `channel.name` (size 20). `tl brands history` is deprecated; do not
     use it. No web lookups.
   - **Brand site** (target under 90 s), writes `<corpus>/brand-site.json`
     with `status: read | fallback | unreachable`. The brand's own website
     (`website` from `tl brands find`) and ONLY the social accounts linked
     directly from that site: positioning, product lines, stated audience,
     founder story or cause, current campaign themes, how it uses creators.
     **One WebFetch per URL, and stop at the first failure per host**: no
     retries, no waiting out a timeout three times. If the site is
     unreachable, fall back in order: the platform's brand record (already in
     the TL-data lane's input), then ONE WebFetch of
     `https://en.wikipedia.org/wiki/<brand>` labelled `[web: wikipedia]`.
     Never search the web for the brand's socials, news or coverage.
   - **Category precedent probe** (target under 90 s), writes
     `<corpus>/category-probe.json`: a channel-scoped transcript search for
     moments the creator already does what the product enables, without
     naming the brand (for a hydration drink: the creator's own words on
     hangovers, workouts, travel dehydration). It picks its own terms, returns
     term counts plus the strongest windows with `&t=` links, and is
     confirm-only. Budget: at most 3 ES queries, `size` 10 or less each, one
     pass, no deepening, and **the file is written as soon as the third query
     returns**, whatever it holds, gaps in `coverage.note`. Every query in the
     foreground, never a background job.

2. **Connection pass.** Start when the merge decisions are saved and the
   TL-data lane is in. The site lane and the probe join if present; a lane
   still missing is named in the page's caveat section, never waited for.
   Follow-up queries are confirm-only. Write
   `<corpus>/connections-<brand_id>.md` with the frontmatter and sections in
   `profile-spec.md`, "CONNECT" (About creator, Thesis, About brand, one
   section per connection strongest first, Where this could go wrong last,
   written from the whole ledger including the withheld tiers, as kinds of
   fact, never details).
   - **The connection is the fact, not the format.** Every card quotes a
     ledger fact, and the quoted fact itself must name the thing the brand
     offers for the card to be **strong**; a link that runs through the
     channel's premise ("her format is unboxing, the brand ships drops") or a
     generic trait ("she talks about value") is **thin**. Each heading
     carries type and strength: `## … — **adjacent** · **thin**`. At most two
     thin cards; when no card is strong, the Thesis says **thin fit** in so
     many words, names the one or two honest angles and what to confirm
     first, and the page carries the verdict above the cards. No angle is
     padded to make a thin fit look full.
   - Each quote is a `>` block with its `&t=` link on a `>` continuation
     line, or `--check` fails it; a quote that matches no ledger fact, or a
     superseded or staged-only one, fails it too.

   Then:

   ```bash
   python3 <skill>/scripts/build_html.py --check --in <corpus>/connections-<brand_id>.md \
     --facts tl-creator-profiles/<id>-facts.jsonl && \
   python3 <skill>/scripts/build_html.py --in <corpus>/connections-<brand_id>.md \
     --facts tl-creator-profiles/<id>-facts.jsonl
   ```

   `--check` exits 3 listing what the map lacks and writes nothing. The
   render writes `tl-creator-profiles/<id>-<brand_id>-connections.html` and
   its body-only twin `…-connections.fragment.html`, and prints both
   **absolute** paths. Where the host has an Artifact tool, publish the
   fragment (the full page nests a document inside the tool's own shell and
   cannot be published); otherwise open the page (`open <absolute path>` on
   macOS). Give the user the absolute path of the page in either case.
   CONNECT ends there, with the path, the artifact link if any, and one line
   naming any brand lane that fell back or was unreachable.

## Guardrails

- **Read-only.** Nothing is sent to anyone; output comes back for review.
- **No prices, costs, rate cards or deal terms in any output**, ever.
- **One labelled sample read per connection at most.** No scripts, full
  reads, CTA wording or alternate versions.
- **Sensitivity is a tier** (`evidence-rules.md`): `clinical`, `children`
  and `location` stay out of connection angles by default, and they MUST be
  read for "Where this could go wrong", as the kind of fact, never the
  detail: knowing what not to say is half the brief. The extractor never
  tiers; a script hints and the merge pass decides. A lane record naming a
  person a withheld-tier transcript fact already names inherits that tier.
  Beliefs are not sensitive. No protected-trait inference, ever.
- **Nothing is dropped, demoted or superseded for being uncertain.** A
  staged-premise claim or a contradiction is checked against the whole
  channel (`authenticate.py`) and judged on dated evidence; what cannot be
  settled stays in the ledger at `unconfirmed`.
- **Verbatim or not at all**; a partial quote match never publishes, and a
  dubbed track is not the creator's words.
- **An empty answer is a real answer**: "no evidence found", with the
  coverage numbers that bound it.
