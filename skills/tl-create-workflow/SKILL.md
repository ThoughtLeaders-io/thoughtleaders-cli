---
name: tl-create-workflow
tl-blurb: design & stand up a sponsorship pipeline (workflow) from a goal
description: >
  Turn a sponsorship / sourcing goal into a structured, data-populated
  **Workflow** — an ordered funnel of report-stages that channels (or brands)
  move through, e.g. Sourced → Qualified → Get face on screen → Reach out →
  Contacted → Sold. Invoke when the user wants to build or set up a workflow or
  pipeline, design an outreach / acquisition funnel for a brand or campaign,
  turn an existing report into a workflow, or organise channel sourcing into
  stages. Triggers: "create a workflow", "build a pipeline / funnel", "set up
  outreach for <brand>", "turn this report into a workflow", "organise my
  sourcing into stages", "workflow for finding channels to sponsor <brand>",
  "build an acquisition funnel". It designs the funnel from the goal + the TL
  methodology, sources the entry stage with real data (delegating to
  tl-keyword-research / tl channels / tl recommender / guide-brand research),
  defines each stage as a query-or-list report, and hands back a create-ready
  blueprint + the exact in-app assembly steps — the tl CLI has no workflow
  endpoint, so the Workflow itself is assembled in the web app. Also answers
  HELP asks about how workflows work ("how do workflows work", "what's a
  query vs a list stage", "explain workflow stages") for free.
---

# tl-create-workflow — a sponsorship goal → a populated pipeline

Turn a fuzzy goal ("I need channels to sponsor **Magic Spoon**", "set up our
outreach funnel", "organise my sourcing") into a **Workflow**: an ordered chain
of report-**stages** that entities move through, with the **entry stage already
populated with the right channels** and every stage typed correctly. The value
is not drawing boxes — it's (a) designing the funnel from the **ThoughtLeaders
methodology** rather than a generic CRM template, (b) **sourcing the entry
stage with real data** so the pipeline starts full, not empty, and (c) getting
the **query-vs-list mechanics right** so the workflow doesn't break the way
hand-built ones do.

A workflow is **not a new kind of object** — every stage IS a saved Report
(campaign), chained in order. Understanding that is the whole game; read
`references/workflow-model.md` before you design anything.

> `<SKILL_DIR>` below is this skill's directory (the one holding `SKILL.md`).

## Hard rules

- **A stage is a Report.** A workflow = ordered Reports linked by
  `workflow_step_number`. There is no separate "stage" object. Design in terms
  of reports.
- **The entry stage is a QUERY; every later stage is a LIST.** This is the
  single most important rule and the #1 cause of broken hand-built workflows —
  see `references/workflow-model.md` (query vs list) and
  `references/pitfalls.md`. Never make stage 2+ a query.
- **Creating the workflow.** A CLI create endpoint —
  `POST /api/cli/v1/workflows/build` (Bearer) — turns the blueprint into a real
  workflow in one atomic call (the Bearer twin of the web builder; ships with
  backend PR #4192 and is invoked by a `tl workflow` command). A workflow made
  this way is identical to an in-app one and appears in the web list/detail
  immediately. **Until that endpoint + command are live**, this skill instead
  **designs + sources + emits a blueprint** and the user assembles it in the web
  app. Either path is in `references/creating-in-app.md`; the blueprint is the
  exact input the endpoint needs, so nothing is wasted. Do not claim a workflow
  was created unless the build call actually returned one — otherwise you
  prepared a blueprint.
- **Source with real data, never placeholder channels.** The entry stage must
  be filled from the index (delegate to `tl-keyword-research` /
  `tl channels find` / `tl recommender` / guide-brand research), never a made-up
  list. An empty pipeline is a failed deliverable.
- Do all data processing with the `utf-8` encoding explicitly in any script you
  write.

## Setup check

```bash
tl whoami        # confirms the CLI is authed and shows plan/limits
```
If this errors, tell the user to run `tl auth login` (or set `TL_API_KEY`).
Sourcing stages needs intelligence access on the org's plan; if `tl whoami`
shows no intelligence flag, say so — you can still design the funnel, but you
can't populate it from the index.

## When to invoke / skip

**Invoke** when the user wants to **stand up a pipeline**: build/set up a
workflow, design an outreach or acquisition funnel for a brand/campaign, turn a
report into a workflow, or organise sourcing into stages.

**Skip when:**
- They just want to *find* channels/brands/videos → `tl channels find`,
  `tl-keyword-research`, `tl recommender`. (You'll *use* these, but a lookup
  alone isn't a workflow.)
- They want to persist one flat list/report they already have →
  `tl-save-report`.
- They're asking about an **existing** workflow's data (counts, who's in which
  stage) → query it with `tl` directly.

## Help mode — explain workflows on request, for free

When the user asks what a workflow is, how stages work, query vs list, or "how
do I build one" as a *question* (not a request to build): **run nothing**. Read
`references/workflow-model.md` (+ `references/pitfalls.md` for the gotchas) and
explain, sized to the ask. Close by offering to design one. Mid-run questions
get the same treatment — answer, then resume.

## The build (you orchestrate; the tl CLI + sibling skills do the data work)

| Stage | What happens | Tooling |
|---|---|---|
| 0 Frame | goal, entity type, funnel shape, stage list — interview, don't assume | you + `references/methodology.md` |
| 1 Source the entry stage | fill stage 1 with the right channels/brands (a QUERY) | `tl-keyword-research` · `tl channels find` · `tl recommender` · guide-brand research |
| 2 Define the stages | each stage as a report config (query for stage 1, lists after) | you + `references/workflow-model.md` |
| 3 Blueprint | emit the create-ready plan: stage names, types, the entry filter, links | you |
| 4 Assemble | the exact in-app steps to build it (Convert → Add stage → link) | `references/creating-in-app.md` |
| 5 Deliver | blueprint + entry-stage report link + how to work the funnel | `tl-save-report` (for the entry report) |

**Narrate the run** — one line per stage transition, and surface every
assumption so the user can correct it. Sourcing spends credits (it's real ES
work); say roughly how much as you go, exactly like `tl-keyword-research`.

### Stage 0 — Frame the funnel (interview; never assume)

Two things decide everything, and both are the user's:

1. **The goal & entity.** What is this pipeline *for*, and does it move
   **channels** (usual), **brands**, or **sponsorships**? "Find channels to
   sponsor Magic Spoon" → a channel-acquisition funnel. "Work our brand
   prospects" → a brand funnel. The entity type fixes the workflow's
   `report_type` and can't be mixed later.
2. **The funnel shape.** How many stages and what they mean. Don't invent a
   generic "Lead → MQL → SQL" — derive it from the **ThoughtLeaders
   methodology** (`references/methodology.md`): the real sourcing funnel is
   *find the pool → qualify on value-vs-price → enrich (face-on-screen,
   contacts) → outreach → pipeline (proposed/pending/sold)*. Offer the canonical
   funnel below and let them cut/rename stages — the huddle's real stages are
   good defaults:

   > **Sourced** (query) → **Qualify** (list) → **Get face on screen** (list) →
   > **Reach out** (list) → **Contacted** (list) → **Proposed** (list)

   Stage names are just report titles — pick names the team will recognise
   (they persist on the campaign). Fewer, meaningful stages beat many empty
   ones.

State the goal, entity, and stage list back to the user before sourcing
anything.

### Stage 1 — Source the entry stage (the QUERY)

Stage 1 is the **pool**: the channels the funnel starts from, selected by a
*filter* (a query), not an explicit list. Pick the sourcing path from the goal —
this is where the methodology becomes data:

- **Sponsor a specific brand / product** → find the brand's category and its
  **guide brands** (proven sponsors / competitors), then their **winner
  channels** (TRUE renewals — the real signal), then **look-alikes**. Use
  `tl brands` research + `tl channels similar` / `tl recommender`.
- **A topic / niche** ("cooking channels for a kitchenware brand") →
  **`tl-keyword-research`** to turn the topic into a validated content filter +
  the channels it selects. Take its `report_link` / filter set as stage 1.
- **A known shortlist** → then stage 1 is really a *list*, and a workflow may be
  overkill — say so; `tl-save-report` might be all they need.

Deliver stage 1 as a **query report** (a filter set), and — because it's the
entry — it's fine and correct for it to be a query. Populate it, eyeball the
count and a sample, and confirm the breadth with the user (too broad → narrow
the filter; too thin → widen), exactly like keyword-research's breadth check.

### Stage 2 — Define the stages (query first, lists after)

For each downstream stage, the report is a **list**: it starts empty and fills
as the user bulk-selects entities in the previous stage and **Moves** them
forward. You don't pre-populate lists — you just create the (empty) list
reports with the right names and types.

- **Types must alternate correctly:** stage 1 = query; stages 2..N = lists.
  Re-check `references/workflow-model.md` if unsure how the platform infers
  query-vs-list from the FilterSet.
- **Columns per stage:** if a stage needs a specific column the team acts on
  (e.g. *Face On Screen* on the "Get face on screen" stage, *Outreach email* on
  "Reach out"), note it — columns are set per report.
- **Linked reports (include/exclude), sparingly:** a stage can pull in another
  report's entities (e.g. exclude "no email / captcha"). Keep this to **≤1–2
  layers of nesting** — deep chains are the documented performance + confusion
  trap (`references/pitfalls.md`). Prefer a flat stage over a clever nest.

### Stage 3 — Emit the blueprint

Hand the user a compact, create-ready plan:

```
Workflow: "Magic Spoon — channel sourcing"   (report_type: channels)
  1. Sourced            [QUERY]  ← <entry filter summary> · ~<N> channels · <report_link>
  2. Qualify            [list]   empty; move channels that pass value-vs-price
  3. Get face on screen [list]   empty; column: Face On Screen
  4. Reach out          [list]   empty; column: Outreach email; exclude → "No email / captcha"
  5. Contacted          [list]   empty
```

Include the **entry report link** (from keyword-research / `tl reports create`)
so stage 1 exists as a real, openable report before assembly.

### Stage 4 — Assemble in the web app

Workflows are built in-app (no CLI endpoint). Walk the user through
`references/creating-in-app.md`:

1. Open the **entry (Sourced) report** → **Convert to workflow** → name it. That
   report becomes **stage 1**.
2. **Add stage** for each downstream stage, in order, with the names from the
   blueprint (they save on the campaign — renames persist).
3. For any stage with a **linked report** (e.g. exclude "no email"), add it on
   that stage — keep nesting shallow.
4. Set per-stage **columns** where noted.
5. Work the funnel: on a stage, **filter** (e.g. by *Face On Screen*),
   **bulk-select**, **Move** to the next stage. Moving is non-destructive.

### Stage 5 — Deliver

Show: the funnel (stages, types, per-stage columns/links), the **entry-stage
report link** (populated), and the one-paragraph "how to work this funnel"
(filter → select → move). Offer to **save the entry report** via
`tl-save-report` if it isn't already saved. Never save or create anything the
user didn't ask for.

## Cost

Framing and blueprinting are free (no queries). **Sourcing stage 1 spends
credits** — that's real ES work delegated to `tl-keyword-research` /
`tl channels` / `tl recommender`; their own costs apply (keyword-research: ~10–20
credits quick, ~60–120 deep). Run `tl describe show db` for live rates. The
in-app assembly costs nothing (it's the user clicking in the platform).

## Self-check before you finish

1. You established the **goal**, the **entity type** (channels / brands /
   sponsorships → the workflow's `report_type`), and the **stage list** with the
   user — derived from the methodology, not a generic CRM funnel — and stated
   them back before sourcing.
2. **Stage 1 is a QUERY and it's populated** from real index data (not a
   placeholder list), with its breadth confirmed against the goal (narrowed /
   widened as needed). **Every stage after 1 is a LIST.** No stage 2+ is a query.
3. Any **linked reports** are ≤1–2 nesting layers; you preferred a flat stage
   over a deep nest, and flagged per-stage **columns** the team acts on.
4. The blueprint is **create-ready**: named stages, correct types, the entry
   filter summary + a working **report link**, and the in-app assembly steps.
5. You were explicit that the **Workflow is assembled in the web app** (the CLI
   can't create it) — you prepared it, you didn't claim to have created it.
6. You narrated the run and its credit spend, and saved / created **nothing**
   without the user's say-so.
7. If the user requests a diagram of the funnel, create it as an SVG graphic.
