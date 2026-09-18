---
name: tl-keyword-research
tl-blurb: build & validate keyword filter sets + evidence-checked channels, fast
description: |
  Turn a topic into a *validated* content filter and the results it selects. Invoke whenever the user wants to find videos or
  channels by what they are about — topics, concepts, niches, not IDs or names: "a group/set of keywords for <topic>", "keywords
  that represent <topic> content", "find content/channels about <topic>", "find investing channels" — or when you'd otherwise
  hand-compose a `tl db es` content search. It expands the topic into candidate keywords (with a gated web lookup for
  post-cutoff entities), probes Elasticsearch for every candidate in parallel (counts, where the matches live, match-centred
  snippets), judges the evidence inline against the user's stated intent, composes a boolean filter and refines it until the
  measured checks pass, and delivers a keyword-group filter set + a clickable report link + the results the user chose: trend
  data at the video level (matching uploads + prevalence), or channel targets tiered by topic intensity (core / recurring /
  one-off) and evidence-checked, or both. It ASKS which deliverable and which run mode (quick single pass vs deep refinement)
  the user wants whenever the request doesn't say — never a silent default; `autonomous` / `--auto` means deep + both
  deliverables with every pause skipped. Keyword-distribution output (counts per keyword) is OPT-IN — only when the user
  explicitly asks for "keyword counts / distribution / how common is X". Also invoke for HELP asks about this skill — "help",
  "how does keyword research work", "what are my options", "describe this skill" — answered free from the built-in guide, no
  queries run.
---

# tl-keyword-research — topic → validated filter set + the results you choose

Turn a fuzzy topic into a **precise, validated content filter** over our data — and whichever results the user actually wants from
it. The value is not brainstorming synonyms (a free YouTube search does that) — it's writing real **Boolean queries over the right
fields**, then **checking against the corpus that the matches are actually on-topic**. The division of labour is strict: **scripts
do everything deterministic** (queries, counts, strata, snippets, signals, coverage checks, tiers, links) and **you do the
judgment** — reading compact evidence sheets and writing verdicts. No judge sub-agents, no batch files: an evidence sheet is a few
thousand tokens and one turn of your attention.

The deliverable has one mandatory layer and two optional layers **the user chooses between** (never assume — see *Choosing the
path & deliverable*):

1. **The topic itself (always).** A filter set of keyword groups + a **clickable report link** that opens the platform with the
   filter applied (+ a persist config) — `build_report.py`. The topic and its prevalence (matching videos, distinct channels) is a
   complete deliverable on its own — a trend journalist writing "how big is this on YouTube" needs exactly this and may not want a
   channel list at all.
2. **Trend data (video level).** The matching uploads — sortable by date/views, windowed — via `search_videos.py`. A creator who
   covered the topic once counts here.
3. **Channel targets.** Channels classified by their **relationship to the topic** — core / recurring / occasional / one-off
   (`search_channels.py --intensity`) — then evidence-checked and flagged for sponsorability. Never assume "channels about the
   topic" means only channels *entirely* about it: for niche topics there may be almost none, and the real sponsorship market is
   channels that return to the topic repeatedly.

The **canonical artifact is the keyword-group filter set**: each group is a self-contained boolean query (an exclusion can be
scoped to its own arm — `("mythos 5" | mythos5) -keto` — which a flat CNF cannot express). The rendered boolean **expression** is
recorded alongside for provenance and re-runs verbatim via `search_channels.py --groups-file` / `search_videos.py --groups-file`.

> Read `references/elasticsearch-content-search.md` before writing queries — it covers the article-vs-channel doc types, the
> content fields (and ES's **legacy** channel field names), `simple_query_string` Boolean syntax, tokenization, the report-link
> keyword grammar, and how highlight fragments are fetched (`tl db es --highlight`).

`<SKILL_DIR>` below is this skill's directory (the one holding `SKILL.md`). `$RUN` is a fresh scratch directory for this run
(`mktemp -d`); every script call carries `--run-dir $RUN` so the ledger under `$RUN/events/` records each query, its elapsed time
and its numbers.

## When to invoke / skip

Invoke when the user wants **videos or channels by content** (topics, concepts, niches), gives seed keywords or an NL phrase to
widen into a content filter, or you're about to hand-compose a `tl db es` content search — delegate here first.

Skip when:
- The user has explicit channel/brand IDs or names → `tl channels find` / `tl brands find`.
- Intent maps cleanly to a curated recommender tag (e.g. "Cooking channels") → `tl recommender top-channels "<tag>"`. Don't
  re-discover curated tags by text match.

## Help mode — explain yourself on request, for free

When the user asks for help, what this skill does, how it works, what the options/parameters are, or to "describe the skill"
("help", "how does this work", "what can you do here", "what are my options", "explain the flow"): **run nothing** — no queries,
no scripts, zero credits. Read `references/help.md` and present it clearly, sized to what they asked (the full guide for "explain
how this works"; just the relevant slice for "what sorting options are there?"). Close by offering to start a run. Mid-run option
questions ("what does deep mean?", "what's the recurring tier?") get the same treatment — answer from the guide, then continue
where you paused.

## Choosing the path & deliverable — the user picks, never a silent default

Two choices shape the run, and both belong to the USER:

**Path** (how hard to refine):
- **Quick** — one expand → probe → judge → deliver pass, no refinement (about a minute). Even here, tokenization variants,
  entity-family expansion and evidence judgment are mandatory — speed never excuses a shallow synonym list.
- **Deep** — the full pipeline: composition and refinement until the measured checks pass (Stage 3, at most three rounds) plus
  materialization (Stage 4). Budget: **about five minutes of wall clock on a large model; the scripts themselves take under one
  minute** — the rest is your own turns, so follow the turn plan below. Deep means *the checks ran*, not *the clock ran*: a run
  that stops after one round because nothing is flagged is a complete deep run.

**Deliverable** (besides the filter + link, which are always included):
- **Trend data** — the matching videos + prevalence numbers (video level).
- **Channel targets** — channels tiered by topic intensity, evidence-checked, sponsorability-flagged.
- **Both.**

How to pick:

1. **The request names it → run it, no questions.** "quick"/"fast"/"just a starting set" → quick; "deep"/"thorough"/"take your
   time" → deep. "trend", "prevalence", "how big is this", "who's talking about it right now" → trend data; "channels to sponsor",
   "targets", "channels for [client]" → channel targets.
2. **Otherwise, ask before starting — ONE combined question** covering whichever of the two is unstated, with the trade in a line
   each (what each path checks and roughly how long it takes). **Recommend by topic shape** in the same question: an event,
   festival, launch, award, season or news moment ("Cannes Lions", "the Fable 5 launch") is a *trend* question first — channels
   rarely have such a moment as their identity, so say that and offer channel targets as the add-on; an evergreen niche
   ("retirement planning", "sourdough") is a *channel* question first. The recommendation is advice; the user's answer wins. Don't
   silently default: guessing quick hides what the skill can do; guessing deep spends time the user never asked for; and assuming
   the user wants a channel list when they wanted trend data (or vice versa) answers a question they didn't ask.
3. **Exception:** `autonomous` / `--auto` / "don't stop to ask" with no named path/deliverable means the **deep path, both
   deliverables, every pause skipped** — the user has asked for zero questions. For an event-shaped topic, still say in the
   delivery that the channel table is a by-product of a trend-shaped topic.

**Autonomy within the deep path:** the user can ask mid-run to run without pausing — skip the scope questions in Stages 2–3 and
record your assumption instead. The preference holds for the rest of the session unless revoked.

## The pipeline (you orchestrate; scripts measure; you judge)

| Stage | What happens | Tooling |
|---|---|---|
| 0 Intent | intent verbatim, relationship, operator, breadth, scope; entity lookup started in the background | `keyword-entity-resolver` agent (background) + `expand_entities.py` |
| 1 Expand | wide, deep, creative candidate generation | you |
| 2 Probe + judge | one parallel probe pass → sample sheet → your verdict file → applied | `probe.py --sheet` · `select_keywords.py --apply` |
| 3 Compose + refine | boolean groups per facet; measured residual/exclusion checks; refine only flagged weaknesses, ≤3 rounds | `probe.py --residual-vs / --exclude-phrase` |
| 4 Materialize | intensity tiers; trend videos; one evidence call for all channels → evidence sheet → your verdicts → merged table | `search_channels.py --intensity` · `search_videos.py` · `evidence.py --sheet` · `classify_channels.py --apply` |
| 5 Deliver | filter set + report link + chosen deliverables + budget line; offer to save | `build_report.py`, `tl-save-report` |

**Narrate the run.** One line at every stage transition — what you're doing, why, and the elapsed time so far (*"Stage 2 — probing
24 candidates in parallel (18s elapsed)"*). Never run a silent stage, and surface every drop/prune/failure as it happens, not just
at the end.

### Run rules — the clock is part of the contract

- **Foreground only.** Every script call is a plain foreground Bash call with a tool timeout of about 120 seconds (120000 ms) —
  never `run_in_background`, never a `sleep`, never a monitor. Each ES call inside the scripts has a 20s timeout, one retry on a
  transient error (rate limit / 5xx), and **no retry on a timeout**; probes and evidence run six calls at a time; identical bodies
  come back from a 24h disk cache. Expected wall clock: 25 candidates ≈ 10–20s; residual/exclusion checks on 10 groups ≈ 10s;
  intensity triage ≈ 5s; evidence for 200 channels ≈ 5s.
- **One flag per shell word.** Define single-value variables (`$INTENT`, `$SINCE`, `$DEADLINE`) and write every flag out
  literally. **Never put several flags in one shell variable; zsh passes it as a single word** — a run that used a combined scope
  variable sent `--content-type longform --since 2025-09-19` as ONE argument and the date window silently never applied. A
  *quoted* single-value variable (`--intent "$INTENT"`) is fine.
- **Keywords go last, after all flags.** The scripts accept positionals anywhere, but keeping them last keeps the command
  readable; a positional starting with `--` is rejected as a typo.
- **Give every script the run deadline.** Start the run with `DEADLINE=$(( $(date +%s) + 300 ))` and pass `--deadline-at
  $DEADLINE` to every script (quick path: 150). A script that would start an ES call past the deadline reports it under
  `unresolved` instead of calling. Delivery always states what was left unresolved.
- **A timed-out query is a finding, not a retry.** `failed` / `unresolved` entries name the candidate and the reason; narrow the
  query (fewer fields, a phrase instead of a bare term) or report it — never rerun the same body.
- **Transcript queries are the slow ones.** A boolean group with several `-"phrase"` exclusions or a long OR-union over
  `transcript` can take 20–30s alone (measured: 30.5s with `transcript` vs 3.7s on `title,summary`); six at once time out. The
  probe drops `transcript` automatically after a timeout and says so (`transcript_dropped`); when you see it, keep the group but
  measure it on `--fields title,summary`, or split the union.
- **A rate limit is not a loss.** `HTTP 429` is retried with backoff; if a probe still fails it is listed under `failed`, not
  silently gone — re-run just those candidates in the next call.
- **Large filters go in a file.** `--groups-file $RUN/groups.json` (the `{"groups":[{"text":…, "content_fields":[…],
  "exclude":true}]}` shape `build_report.py` takes) — per-group fields and excluded groups are honoured, so every measurement uses
  the same filter the link will select. Never quote twenty `--group` arguments in the shell; never use the `timeout` binary (macOS
  doesn't ship it).

#### Turn plan — mandatory, and the reason a run is five minutes not three

A measured run spent **50 seconds in scripts and five minutes in turns**. Every extra turn of yours costs about 30 seconds, so the
run is **exactly these turns**, and each Bash turn is **ONE call** (chain the commands with `&&`):

- **T1 — one Bash call:** `tl whoami`, `$RUN` (`mktemp -d`), `$INTENT`, `$SINCE` and `$DEADLINE`, the Stage 0 existence probe
  **and** the wide Stage 2 probe with `--sheet $RUN/sheet1.md`.
- **T2 — Read `$RUN/sheet1.md`.**
- **T3 — Write `$RUN/verdicts1.tsv` (and `$RUN/resolver.json` if the resolver has returned), then one Bash call:**
  `select_keywords.py --apply` + write `$RUN/groups.json` + the resolver-names probe (`expand_entities.py --probe-batch … <
  $RUN/resolver.json | probe.py --sheet $RUN/sheet2.md …`) + the round-1 measurement (`probe.py --groups-file $RUN/groups.json
  --residual-vs '<core>' --exclude-phrase … --sheet $RUN/sheet_r1.md`).
- **T4 — Read `$RUN/sheet2.md` and `$RUN/sheet_r1.md`** (both in this one turn).
- **T5 — only if a signal or an `unsure` is still open:** Write `$RUN/verdicts_r2.tsv`, then one Bash call (apply + re-measure).
- **T6 — one Bash call:** `search_channels.py --intensity --sheet` + `search_videos.py --sheet` (if the user chose trend data) +
  `evidence.py --sheet` (if the user chose channels).
- **T7 — Read the evidence sheet (and the video sheet).**
- **T8 — Write `$RUN/channel_verdicts.tsv`, then one Bash call:** `classify_channels.py --apply` + `build_report.py`.
- **T9 — deliver.**

**Never split those calls across turns. Never read a script's JSON when it wrote a sheet. Never restate a sheet in prose** — it is
already the readable form.

### Stage 0 — Intent, relationship, operator, breadth, scope

Keep the user's own sentence **verbatim as the intent** — it's the yardstick every judgment uses. Then state your assumptions so
the user can correct them:

- **Deliverable** — whichever the user chose above. Either way the research runs at **topic level** (videos are where the keywords
  live); channel-doc probes (`--level channel`) remain a tool for the existence check below.
- **Relationship being tested — name it.** *Coverage* ("channels that talk about retirement planning"), *participation* ("creators
  who went to Cannes Lions"), *attribute* ("creators who have a dog"), or *reporting* ("who covers Cannes Lions"). Coverage and
  reporting suit intensity tiers; an attribute is often established by **one** first-person statement and is usually
  transcript-led, so tiers mislead there — say which relationship you're testing and how the channel table should be read.
- **Existence check (channel deliverable):** one cheap channel-doc probe on the core term (`probe.py --level channel --samples 3
  "<core>"`). **Scope flags are ignored at channel level** (the script notes it on stderr), so passing or omitting them changes
  nothing. A tiny distinct-channel count means essentially no channel is *about* this topic — say so, and set expectations that
  the channel deliverable will be built from **recurring-coverage** channels, not identity matches. Never return a near-empty
  "core" list as if it were the whole answer, and never pad it.
- **Operator.** Default `OR` (union of a niche's facets); `AND` only for a true intersection ("both X and Y", composite nouns).
  Under AND, keep candidates *inside* the intersection — don't broaden each component independently.
- **Breadth judgment — say it back.** "Underwater basket weaving" returning a few dozen channels is a complete answer;
  "basketball" returning a few dozen is a miss. The probe's per-keyword **`channels`** count (distinct channels) is the measuring
  stick, and Stage 3's coverage check measures against this.
- **Scope — state it, then pin the date in a variable.** Everything is scoped to **YouTube uploads** and, at video level,
  **longform** by default; offer `--content-type all` (or `short`/`live`) if the user wants more. A date window (`--since`) is a
  *relevance* choice (current usage of the terms), not a speed lever — the index answers in about a second for any window. Set the
  run's variables once in T1 and write the scope flags out **literally** in every script call (probe, search_channels,
  search_videos, evidence) so nothing is measured or judged under a wider window than the one you stated:

  ```bash
  INTENT="<the user's sentence, verbatim>"
  SINCE=$(date -v-12m +%Y-%m-%d)          # one word — a date, not a flag list
  DEADLINE=$(( $(date +%s) + 300 ))
  # then on every call:  --content-type longform --since $SINCE
  ```

  A run that left the scope flags off the evidence call judged channels on uploads from 2011.

**Gated web entity resolution — in the background, only when memory can't.** Expansion is the one input drawn purely from model
knowledge, so it fails where knowledge does (the classic miss: expanding a launch to the company name and never generating the
product, its version, or its **sibling**). Trigger a web lookup ONLY when the topic names an entity that **postdates the knowledge
cutoff**, was **recently renamed/rebranded**, or is a **live trend / insider-jargon-dense niche** you cannot enumerate from
memory. For a topic you know cold (cooking, retirement planning, basketball), skip it. When the gate fires, say so and why, then
spawn **`keyword-entity-resolver`** (Agent tool, `subagent_type: keyword-entity-resolver`, `run_in_background: true`) so the noisy
page text never enters your context — and **carry on with Stage 1 and the first probe while it runs**. Its reply is a compact JSON
of *names* only:

```
topic: <the topic>
intent: <one sentence — what the user actually wants>
level: topic|channel
known: ["...", "..."]    # your own candidates so far — it fills the gaps
```

The agent returns that JSON as **agent text, not a file**. When it returns, **save the JSON block to `$RUN/resolver.json` with the
Write tool**, then turn the names into probe-ready candidates and probe them inside the T3 Bash call (the cache makes your earlier
candidates free to re-probe alongside), so T4 reads `sheet2.md` and `sheet_r1.md` together — no extra turn:

```bash
python3 <SKILL_DIR>/scripts/expand_entities.py --probe-batch \
  --existing "cannes lions" "advertising awards" < $RUN/resolver.json \
  | python3 <SKILL_DIR>/scripts/probe.py --sheet $RUN/sheet2.md --intent "$INTENT" \
    --content-type longform --since $SINCE --run-dir $RUN --deadline-at $DEADLINE
```

Non-batch mode also returns `collisions` (a polluter watch-list for the Stage 3 NOT-rescue) and `hashtags` (for optional
`hashtags` field targeting). **Web is for entity NAMES, never synonyms / breadth / validation** — breadth is the
distinct-`channels` count over our index, relevance is judged only from this index's evidence, and every web-sourced name earns
its place through the same probe + judgment as any other candidate (a hallucinated name probes to `documents: 0` and drops).

### Stage 1 — Expand: go wide, go deep, go creative

A shallow synonym list is the #1 failure mode. Coverage is won or lost here.

- **Decompose the topic into facets and expand each one.** An event/launch: lead-up → the launch → product specifics → **sibling &
  ecosystem products** → reactions → fallout → regulatory. A niche: sub-areas, tools, personas, jargon.
- **Expand every named entity into its whole family** — company, product line, model/version, codename, **sibling shipped
  alongside**. (Live miss: searching `anthropic` for the Claude Fable 5 launch missed `fable 5` (713 ch), `claude mythos` (620 ch
  — the sibling), and `mythos 5` (433 ch) — most of the topic.)
- **Generate tokenization variants for every name/number — with the script, not by hand.** The index tokenizes `fable5`, `fable
  5`/`fable-5`, and `fable five` as *different terms that miss each other's documents*. Run every named entity through
  `expand_entities.py --existing … --probe-batch --names "fable 5" "claude mythos"` (no web step needed) and probe what it prints
  — each family becomes one `("fable 5" | fable5 | "fable five")` group. No stemming either: expand inflections/plurals yourself
  (`invest`/`investing`/`investments` are distinct).
- **Other languages and registers.** If the topic has a natural non-English audience (a Spanish football term, a K-beauty
  routine), add the native spellings and the hashtag forms — they are separate candidates and get the same probe.
- **Candidates can be boolean groups, not just phrases** — a self-contained `simple_query_string` like `("fable 5" | fable5 |
  "claude fable")`, or a family carrying its own scoped de-noising `("mythos 5" | mythos5) -keto`.
- **Scale the candidate count to the topic.** A one-line niche: ~8–15. A multi-facet event: **30–50**, covering every family and
  its spelling variants. All of them go into ONE probe call — probes run in parallel, so breadth here costs seconds; what it costs
  *you* is one header line per candidate on the sheet.

Rules:
- **Never add the bare over-broad root** — single word *or* generic collocation. For "TikTok Shop" don't add `tiktok`; `supply
  chain risk` alone matches its own broad domain unless entity-qualified.
- **Mine the data, don't only brainstorm.** After the first probe, read the on-topic snippets for recurring terms you didn't think
  of and probe them in the next pass. This data-driven discovery is what a synonym list can't do.
- **Brands**: when the topic IS an entity/event, full entity-family expansion is mandatory. For a generic topic, don't drift into
  naming specific brands unless the seeds contain one (then adjacent brands in the category are fine). **No specific channel
  names** (`tl channels find`). No padding.

### Stage 2 — Probe and judge (`probe.py --sheet` → verdicts → `select_keywords.py --apply`)

One parallel probe pass answers, per candidate, *how much* it matches, *where* it matches, and *what* it matches — and writes the
sample sheet you judge from. Flags first, keywords last:

```bash
python3 <SKILL_DIR>/scripts/probe.py --level topic --samples 3 \
  --sheet $RUN/sheet1.md --intent "$INTENT" --content-type longform --since $SINCE \
  --run-dir $RUN --deadline-at $DEADLINE \
  "cannes lions" canneslions '"young lions" +cannes' "lions festival" > $RUN/probe1.json

# Boolean candidates via simple_query_string (default_operator=and is set for you)
python3 <SKILL_DIR>/scripts/probe.py --mode sqs --intent "$INTENT" … '("mythos 5" | mythos5) -keto'
# channel level (whole channels); JSON array on stdin also works
python3 <SKILL_DIR>/scripts/probe.py --level channel --intent "$INTENT" "cooking" "baking"
```

A candidate containing boolean operators is probed as a boolean group automatically — no `--mode sqs` needed for mixed lists.

Per keyword the JSON carries `documents`, **`channels`** (distinct channels — the measuring stick), `strata` (`title` /
`summary_only` / `transcript_only` document counts), `transcript_share`, `samples[]` (each with `stratum`, `channel_id`, `title`,
`date`, `url` and a **match-centred `snippet`** from ES highlight — the text around the actual match, in whichever field it
occurred), `subsumed_by`, recency (`stale` / `thin`) and code-computed `signals`. `failed` lists probes that errored or timed out;
`unresolved` lists probes skipped for the deadline. Neither is a dropped keyword.

**The sample sheet** (`$RUN/sheet1.md`) is the same evidence rendered for one read: per candidate a header line (counts, strata,
signals) and its snippets, marked `[title]` / `[summary]` / `[transcript]`, with the matched term shown as `«term»`. Samples are
chosen to be diagnostic, not flattering: the top-scored matches, plus **transcript-only** matches whenever that stratum is
material (`--transcript-samples`, default 2) — the field where the wrong sense hides. Read the sheet with the Read tool; **never
paste samples into your prose.** Candidates that matched nothing are collected at the bottom under `## no matches (0 docs)` — that
section IS their evidence, so you don't have to judge them one by one: a verdict for a no-match candidate is ignored rather than
treated as an error, and leaving them out of the verdict file is fine.

**Judge inline, then write the verdict file.** For every candidate, against the verbatim intent:

- `keep` — the snippets are the intended sense; the term earns a group.
- `drop` — the wrong sense, an unrelated domain, or a duplicate a broader kept term already covers (`subsumed_by`).
- `unsure` — the snippets don't settle it (too few, mixed, transcript-led with no transcript sample). `unsure` is a real verdict:
  it schedules a targeted look in Stage 3, it never silently becomes keep or drop.

Add an `exclude_hint` when you can name the polluting token or phrase (`"film festival"` for `cannes`), and `note` when the reason
isn't obvious. The rubric: judge the **match**, not the title — a video titled "Cannes 2026 vlog" whose snippet is the film
festival is a `drop` for the advertising festival; a snippet that quotes someone *else's* dog is not ownership. Three snippets are
a **sense check, not a precision measure** — never report "95% relevant" from three samples; report what the snippets showed and
what the strata say about where the matches live.

Write the verdicts with the Write tool — one TAB-separated line per candidate, the `keyword` string exactly as the probe output
spells it, `keyword<TAB>verdict[<TAB>exclude_hint][<TAB>note]` (`#` comments and blank lines are ignored). This is the cheapest
shape to write, so it is the default:

```
cannes lions	keep
cannes	drop	film festival	film festival dominates
lions festival	unsure		2 of 3 are the film festival
```

The JSON array is still accepted for the same file (`[{"keyword": "cannes lions", "verdict": "keep"}, …]`) — use it only when a
verdict needs a field the columns don't carry. The format is detected from the file's content, so the `.tsv` name is a convention,
not a switch.

Then apply — **the script enforces coverage, you don't count**:

```bash
python3 <SKILL_DIR>/scripts/select_keywords.py --apply --probe-file $RUN/probe1.json \
  --verdicts $RUN/verdicts1.tsv --run-dir $RUN > $RUN/selected1.json
```

Exit 0: every candidate has a verdict. Exit 2: the output lists `missing` candidates — judge them and apply again (don't hand-wave
them into keep). The output carries `kept` / `dropped` / `unsure` with counts, `groups` for Stage 5, `candidate_channels` /
`candidate_videos` from the kept keywords' samples, and a `fitness` block (candidates, judged, kept, dropped, unsure,
transcript-led, flagged) — the round's numbers; read them, don't estimate.

**Ask the user on scope, not relevance.** Two different questions hide here: *relevance* ("is this term's match on-topic?" — you
judge from snippets) and *scope* ("is this sub-topic part of what the user wants?" — the user's call). When a candidate family is
on-relevance but its scope is a genuine judgment — a sibling product, an adjacent model, a broad policy framing — surface 2–4
snippets and ask in or out (live: *"Mythos 5 is the sibling model launched alongside Fable 5 — include it?"*). Keep it to the few
families that swing the result; in autonomous mode record the assumption instead.

### Stage 3 — Compose and refine: measured, not ceremonial

You **research the topic by composing boolean queries and measuring them**. Round 1 composes the kept keywords into groups (one
per facet/family, with scoped exclusions from the `exclude_hint`s) and measures them; later rounds exist only to fix what the
measurements flag. **Stop when nothing is flagged** — or after three rounds, or at the deadline, whichever comes first, and say
which.

**Measure with the script, never by hand-composing queries:**

```bash
python3 <SKILL_DIR>/scripts/probe.py --groups-file $RUN/groups.json --samples 2 \
  --residual-vs '"cannes lions" | canneslions' --exclude-phrase "film festival" \
  --intent "$INTENT" --sheet $RUN/sheet_r1.md --content-type longform --since $SINCE \
  --run-dir $RUN --deadline-at $DEADLINE > $RUN/round1.json
```

Measure **the groups file you will deliver**, not a hand-retyped copy of it: per-group `content_fields` and excluded groups are
honoured, and a synthetic `union` row measures the whole filter in the same call. (Loose candidates can still be passed as
positionals with `--mode sqs`.)

Per candidate this reports `residual` (documents / channels it reaches that the core does not, with **residual samples** on the
sheet — the only honest place to judge a broad term), `marginal_share` (residual documents ÷ its own documents), `breadth_vs_core`
(its documents ÷ the core's) and, for each `--exclude-phrase`, `exclusion_checks` with the `delta_pct` the exclusion costs the
core. The core group measured against itself is marked `(core)` on the sheet and carries **no** `redundant` / `too_broad` signal —
its residual is zero by construction, so don't read that as a weakness. The **signals** are code-computed triage, not verdicts:

| Signal | Computed as | What to do |
|---|---|---|
| `redundant` | marginal_share < 5% | usually drop; keep only if it adds a distinct facet or clean examples |
| `too_broad` | breadth_vs_core ≥ 10× and marginal_share ≥ 80% | judge its **residual** samples; anchor or field-narrow before keeping |
| `transcript_led` | transcript_share ≥ 80% | judge only from transcript samples; if none, `unsure` |
| `over_cut` | an exclusion's `core_delta_pct` > 2% (> 5% = `blocked`); measured on the core, not on the candidate it cleans — it lives on the sheet's `core:` line and in the output's top-level `exclusions`, **never on a candidate** | exclude the multi-word **phrase** instead of the shared token |
| `stale` / `thin` | recency (see the reference) | keep with a visible tag or exclude; never drop silently |

The thresholds are defaults, not laws. **"The signals cleared"** has one meaning: no per-candidate `too_broad` / `redundant` /
`transcript_led` is left unresolved **and** no exclusion is `blocked`. Look for the first on the candidate rows and for the second
on the `core:` line — an exclusion verdict is never a property of a candidate.

**The move set** (mechanics + verified numbers in the reference):

- **Narrow** a noisy group: add a required dimension (`+(marketing | affiliate)`), target a field, or exclude the bad sense.
- **Expand** a thin one: mine emergent terms from on-topic snippets and from the evidence sheet's `adjacent_terms` later. Auto-add
  only terms that pass the same probe + judgment; widening beyond the stated intent (retirement → general investing) is a **scope
  change — ask the user first**. If the topic is genuinely niche and mining runs dry, a small result is the correct answer — say
  so rather than padding.
- **Judge marginal value on the residual, not the headline.** `_score` floats the relevant docs to the top of an unqualified
  sample and hides redundancy. **Don't dismiss a small clean residual** — ~20–50 genuinely-new on-intent channels earns a group; a
  report holds many groups at no cost.
- **NOT-rescue a polluted term — scoped to its own group.** Find the recurring token the off-intent docs share and exclude it
  *inside that family's group*: `("FIRE movement") -"Free Fire"`. A whole-filter exclusion over-cuts (live: scoping `-openclaw` to
  its arm kept 51 on-topic docs a global exclude lost). `--exclude-phrase` measures the cost on the core: a material drop means
  the token is shared — exclude the **phrase** (`-"film festival"` cut the Cannes core 4%; bare `-film` cut 24%).
- **AND-anchor a broad root.** A root too broad alone (`cannes`) is rescued by a mandatory anchor plus a domain OR-qualifier:
  `cannes +lions +(advertising | agency | campaign | "young lions") -"film festival"`. Non-adjacent AND reaches on-intent docs the
  phrase `"cannes lions"` structurally misses (live: +815 distinct channels, ~80% on-intent). Judge it on the residual.
- **Field-narrow rescue (title ≫ summary ≫ transcript).** `transcript` is by far the noisiest field, `title` the cleanest — a term
  too noisy corpus-wide can be clean restricted to titles. Probe it per-field (`--fields title` or `--fields title,summary`); if
  the title-only samples are clean, keep the group **with per-group `content_fields`** in the deliverable (`{"text": "cannes
  +advertising", "content_fields": ["title"]}` — a plain two-word group is an adjacent *phrase*; use `+` for a true AND).

**Coverage.** Measure the union once per round as ONE sqs candidate (`probe.py --mode sqs '<group1> | <group2> | …'` or the groups
file via `search_channels.py --intensity`, which reports `distinct_channels`) and compare it with the Stage 0 breadth judgment.
Keyword sets overlap; per-keyword `channels` don't sum.

**Each round, record one line** in your narration: the change, the numbers that moved, the decision. Re-judge only the candidates
whose evidence changed (new groups, residual samples, `unsure`s from the last round); write a fresh `verdicts_rN.tsv` for just
those and apply it with `--verdicts $RUN/verdicts1.tsv --verdicts $RUN/verdicts_r2.tsv` (later files override earlier ones per
keyword). **Backtracking is expected**: when a move reduced coverage or cleanliness, discard it and try another axis.

**Checkpoint (deep path, user present):** when the checks pass (or at round 3), present the rendered expression, the fitness
numbers and what changed, and ask: accept · adjust direction. If the user wants more, **interview them about the intent behind the
keywords** — which sense to include/exclude, must-have sub-topics, brands that must or must not count, language/recency
constraints — then fold the answers into the groups. **Autonomous mode** skips the checkpoint and notes that it did.

### Stage 4 — Materialize the chosen deliverables

Everything here takes the final filter verbatim from `$RUN/groups.json`, so what you deliver is exactly what the filter selects.
Write the groups file once (the `build_report.py` input shape) and point every call at it.

**Step 1 — Intensity triage (always, both deliverables): 2–3 ES calls.**

```bash
python3 <SKILL_DIR>/scripts/search_channels.py --intensity --groups-file $RUN/groups.json \
  --sheet $RUN/intensity.md --content-type longform --since $SINCE \
  --run-dir $RUN --deadline-at $DEADLINE > $RUN/intensity.json
```

`--sheet` writes the whole picture in a dozen lines — the distinct-channel total, the tier counts and the ten biggest matchers —
so read that, not the JSON. **Tiers cover the top 200 channels by matching uploads** (the aggregation's size); `distinct_channels`
is the corpus total, and everything past the cut is un-tiered by design. Say that when you show the summary — for an attribute
topic ("creators who have a dog") the long tail is most of the market, and a tier table that ignores it reads as if the topic were
small.

One aggregation call measures every channel's **relationship to the topic** — matching uploads (all-time + recent window) per
channel — a second computes each channel's topic share over the same date scope, and enrichment adds names + sponsorability.
Tiers:

- **core** — the topic is the channel's identity (recurring + share ≥ 50%)
- **recurring** — ≥3 matching uploads (tunable `--recurring-min`): channels that keep returning to the topic. **For niche topics
  this tier IS the sponsorship market** — say so plainly.
- **occasional** / **one_off** — count for trend math; usually wrong targets (except for *attribute* relationships, where one
  statement can be enough — say how you're reading them).

Show the tier summary before spending anything further — it's the cheapest honest picture of the topic's channel landscape.

**Step 2a — Trend data (if chosen): the videos + prevalence.**

```bash
python3 <SKILL_DIR>/scripts/search_videos.py --sort date --size 50 --sheet $RUN/videos.md \
  --groups-file $RUN/groups.json --content-type longform --since $SINCE \
  --run-dir $RUN --deadline-at $DEADLINE > $RUN/videos.json
python3 <SKILL_DIR>/scripts/search_videos.py --sort views --distinct-channels \
  --sheet $RUN/videos_top.md --groups-file $RUN/groups.json \
  --content-type longform --since $SINCE --run-dir $RUN --deadline-at $DEADLINE > $RUN/videos_top.json
```

`--sheet` is one line per video — date, views, channel (id) and title — with the totals in its header; read it instead of the
JSON. Videos come back with title, url, publication date, views/likes/duration, and the channel's name + subscribers. Headline
prevalence comes free from what you already ran: total matching videos + the intensity call's `distinct_channels`. Sense-check the
top titles against the intent; one-off channels COUNT here. For date-sorted feeds prefer `--fields title,summary` — under a
non-relevance sort, incidental transcript mentions surface as prominently as genuinely on-topic uploads. Tell the user when one
channel dominates and offer `--distinct-channels`. Run 2a and Step 1 back to back in one Bash call — they are independent.

**Step 2b — Channel targets (if chosen): one evidence call, one judgment.**

1. **Evidence for every selected channel in one pass.** `evidence.py` runs the delivered filter with a `terms` filter on the
   chosen channel ids and `collapse` on channel — one call per 100 channels — and returns each channel's best-matching upload with
   a **highlight snippet** from the field that matched. Prioritize by tier: core and recurring first, occasional if the user
   asked, one-offs only for attribute relationships.
   ```bash
   python3 <SKILL_DIR>/scripts/evidence.py --groups-file $RUN/groups.json \
     --channels-file $RUN/intensity.json --tiers core,recurring --max-channels 120 \
     --sheet $RUN/evidence.md --topic "$INTENT" --content-type longform --since $SINCE \
     --run-dir $RUN --deadline-at $DEADLINE > $RUN/evidence.json
   ```
   `--per-channel 2` fetches a second upload per channel (a second call excluding the first pass's videos) — use it for `mixed`
   verdicts you want to settle, not for everyone. Channels the filter no longer reaches are listed under `missing` (a backtrack
   signal if a strong channel is among them).
2. **Judge the evidence sheet inline.** Per channel: tier, matching uploads, share, and its snippet(s). Verdicts: `on_topic` (the
   intended sense, the channel's own voice), `mixed` (the term in both senses, or on-topic but incidental), `off_topic` (the wrong
   sense — the film festival, someone else's dog), `unknown` (snippet doesn't settle it). Add `adjacent_terms` when a snippet
   shows vocabulary the filter lacks — those are suggestions for the user, never automatic filter changes. Write one TAB-separated
   line per channel to `$RUN/channel_verdicts.tsv`, `channel_id<TAB>verdict[<TAB>evidence_quote][<TAB>adjacent_terms]`:
   ```
   12345	on_topic	…«Cannes Lions» Grand Prix…	young lions
   67890	off_topic	…the «Cannes» red carpet…
   ```
   The JSON array (`[{"channel_id": 123, "verdict": "on_topic", "evidence_quote": …}]`) is still accepted, and the two shapes can
   be mixed across `--verdicts` files.
3. **Merge — the script enforces coverage and the shape:**
   ```bash
   python3 <SKILL_DIR>/scripts/classify_channels.py --apply --evidence $RUN/evidence.json \
     --verdicts $RUN/channel_verdicts.tsv --intensity $RUN/intensity.json --run-dir $RUN
   ```
   Exit 2 lists only the channels that **have evidence and no verdict** — judge those and apply again. Channels with no evidence,
   failed, or never fetched never need a verdict and come back under `not_validated`. The output is the final table: `channels`
   (on_topic + mixed, tier × verdict × sponsorability), `excluded` (off_topic, always surfaced), `not_validated` (`no_evidence` /
   `unknown` / never fetched), pooled `adjacent_terms` with the channels that said them, and a sponsorability summary.
4. **Disposition:** keep `on_topic` AND `mixed` (labelled); exclude only clear `off_topic` — and surface the excluded list. Rank
   all, **flag don't filter** on sponsorability: the user decides what to do with unbookable matches. State how many channels were
   evidence-checked and how many were not.

### Stage 5 — Deliver (`build_report.py`)

Hand the validated groups to the builder — the same `$RUN/groups.json`:

```bash
python3 <SKILL_DIR>/scripts/build_report.py < $RUN/groups.json
# groups.json: {"operator":"OR","report_type":"channels","title":"Cannes Lions",
#   "groups":[{"text":"(\"cannes lions\" | canneslions)"},
#             {"text":"cannes +lions +(advertising | agency) -\"film festival\""},
#             {"text":"cannes +advertising","content_fields":["title"]},
#             {"text":"dropshipping","exclude":true}]}
```

It prunes union-redundant plain phrases (boolean groups are opaque — never pruned, never prune others), **translates boolean-group
SQS text into the web app's keyword grammar** (uppercase `AND`/`OR`/`NOT` + parens + quoted atoms — raw `|`/`+`/`-` are literal
text in a link; `*`/`~` are rejected, enumerate variants first), and emits `filter_set` (platform shape), `report_link`
(paste-ready URL, no saved record, no credits — **the default thing to hand the user**), `report_config` (for `tl reports create
--config-file <f> --yes`), `expression` (record it alongside any saved report) and `pruned` / `translated` — nothing happens
silently.

Show the user: the final keyword groups, the `report_link`, the chosen deliverables (videos with prevalence; the channel table
with verdicts and sponsorability), and **one budget line**: elapsed wall clock split into **script seconds vs your own turns**, ES
calls, channels evidence-checked, and anything `unresolved` or `unsure` — e.g. *"4m50s elapsed: 51s in scripts, the rest my turns
· 38 ES calls · 118 channels evidence-checked · 0 unresolved, 2 unsure"*. The script seconds and ES calls come from the ledger in
one line (each event carries `elapsed_seconds` and `es_calls` at top level):

```bash
python3 -c "import json,glob;e=[json.load(open(p)) for p in glob.glob('$RUN/events/*.json')];print(len(e),'calls',round(sum(x.get('elapsed_seconds') or 0 for x in e),1),'s',sum(x.get('es_calls') or 0 for x in e),'es')"
```

Then **offer** to save via `tl-save-report` / `tl reports create` — never save unprompted.

## Opt-in: keyword distribution

Only when the user explicitly asks for keyword counts / distribution / "how common is X", the probe's ranked counts ARE the
deliverable:

```bash
python3 <SKILL_DIR>/scripts/probe.py crypto bitcoin DeFi Web3 "smart contract"
```

Emits `{operator, level, fields, scope, keywords:[{keyword, count, …}]}` sorted descending — a superset of the old `{operator,
keywords:[{keyword, count}]}` envelope, so existing consumers keep working.

## Cost — tokens first, credits second

**Decisions in this skill are made on your token usage, never on ES credits.** Credits are cheap and the user has said so; your
context is the scarce resource, and it is spent almost entirely on the evidence sheets:

- a sample sheet for 25 candidates × 3 snippets ≈ 4–6K tokens;
- residual sheets are smaller (2 snippets per flagged candidate only);
- a channel evidence sheet is ≈ 60–80 tokens per channel — 200 channels ≈ 15K tokens, which is why `--tiers` and `--max-channels`
  exist: evidence-check the tiers that are the deliverable, and let `not_validated` say the rest.

ES pricing, for the record: a probe is one call per candidate (~1–2 credits plus a flat ~10 per highlighted sample row),
`--intensity` is 2–3 calls total, `evidence.py` is one call per 100 channels, identical bodies are cached for 24h
(`~/.cache/tl-keyword-research/`; `--no-cache` to force ES), and `build_report.py` / `expand_entities.py` / the web step are free.
`tl db es … --pricing` shows a ceiling, not the real charge.

## Self-check before you finish

1. Deliverable, **relationship**, operator, **scope** and **breadth judgment** stated and matching the intent; **path** and
   **deliverable** were the user's explicit choice, never a silent default.
2. Expansion went deep — facets, every entity's full family (company → product → model → codename → **sibling**), **tokenization
   variants**, other languages where natural, snippets mined for missed terms; no bare over-broad root survived unanchored; the
   resolver ran for a post-cutoff / renamed / trend / jargon-dense topic and its names were probed like any other candidate.
3. Every candidate got a verdict from its **snippets** against the verbatim intent; `unsure` resolved or reported;
   `select_keywords.py --apply` exited 0; genuine **scope** calls went to the user (or were recorded as assumptions).
4. Deep path: refinement ran until the **signals cleared** (or 3 rounds / the deadline — said which); broad terms judged on their
   **residual**; exclusions **measured** not to over-cut; rescues (scoped NOT, AND-anchor, field-narrow) tried before dropping a
   real term. Quick path: said so.
5. Coverage measured on the union against the intended breadth; any scope-widening was user-confirmed.
6. Intensity triage ran before any per-channel spend and its tier summary was shown; for channel targets the final table is
   `classify_channels.py`'s output, every evidenced channel has a verdict, only clear `off_topic` was excluded and surfaced,
   nothing filtered for being unbookable, and the evidence-checked vs not count is stated; for trend data the matching videos +
   prevalence were materialized and the top titles sense-checked.
7. Redundant terms pruned and reported; **stale** flagged; `thin` niches surfaced — nothing dropped silently.
8. Delivered: filter set **+** working `report_link` **+** the chosen results **+** the recorded `expression` **+** the budget
   line.
9. Turn plan followed: one Bash call or one Read/Write per step, nothing split across turns, no JSON read where a sheet exists, no
   sheet restated in prose, and the scope flags written out literally on every script call.
10. Every script ran in the foreground with the run deadline; nothing backgrounded, nothing retried a timed-out query, nothing
    saved without confirmation.
11. If the user requests a chart, create it as an SVG graphic.
