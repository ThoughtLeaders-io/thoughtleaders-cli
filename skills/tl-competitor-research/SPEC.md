# tl-competitor-research — SPEC

> **Status: Step 1 of 5** — E2E success definition only. Step 2 (workflow
> design + Report Builder composition points) is a follow-up. SKILL.md
> doesn't exist yet; this directory holds the spec the eventual skill
> will be measured against.

## Workflow intent

Translate a competitor-research goal — *"who is brand X sponsoring on
YouTube, and where could we go next?"* — into an actionable outreach
shortlist, by composing `tl-cli:tl-report-builder` as a component for
the data-fetch + cross-reference steps.

The workflow owns: the user-facing prompt vocabulary, brand resolution
across competitor + user's own brand, cross-referencing the two, ranking
adjacency, and synthesizing the answer.

The workflow does NOT own: report-config validation, FilterSet shape,
column selection, save mechanics — those stay in Report Builder.

## What "success" looks like (the E2E bar)

A workflow run is **successful** when the user gets, in a single reply,
all of the following without any manual follow-up step:

1. **A ranked, deduplicated list of channels** the competitor has run
   with — top 10 by frequency, with deal count + most recent send date
   + reach. (NOT one-row-per-deal raw data.)
2. **An "our relationship" annotation per channel**: *"never pitched"*,
   *"pitched but lost"*, *"active deal"*, *"do-not-contact"*.
3. **An outreach shortlist** — the subset of the competitor's channels
   the user has never pitched, ordered by adjacency to the user's
   brand (audience fit, niche overlap, reach band match).
4. **An exclusion list** — channels the user should NOT pitch (already
   in active pipeline, on do-not-contact, prior conflict).
5. **A saved TL report** the user can click into for full data drilling.

Time-to-answer: under 3 minutes from prompt to reply.

## Test prompt set (the 5 prompts this workflow must succeed on)

Step 1's deliverable is the test set itself, not the workflow yet.
These 5 prompts are what step 4 (test) will run against:

### Prompt 1 — explicit competitor + user's own brand
> *"Research Magic Spoon's YouTube footprint — where could Fusion go next?"*

- **Competitor**: Magic Spoon (cereal / breakfast vertical)
- **User's brand**: Fusion (Blackmagic Design)
- **Resolution**: workflow must read session context to know Fusion is
  the user's brand if not explicitly named
- **Expected success**: ranked Magic Spoon channel list + Fusion
  adjacency ranking + outreach shortlist excluding any Fusion has
  already pitched

### Prompt 2 — competitor only, infer user's brand from session
> *"Who is HelloFresh sponsoring on YouTube?"*

- **Competitor**: HelloFresh (meal-kit vertical)
- **User's brand**: not stated — workflow infers from session
- **Expected success**: same shape as prompt 1, with the workflow
  having decided which session-context brand to anchor adjacency to
  (or, if ambiguous, surfacing the choice as a clarifier)

### Prompt 3 — workflow-shaped intent without naming "research"
> *"What channels does Webull run with — could any of them work for us?"*

- **Competitor**: Webull (fintech vertical)
- **Intent shape**: question phrasing, not imperative
- **Expected success**: workflow triggers on the *"work for us"*
  framing (not on a "build me a report" framing), produces shortlist

### Prompt 4 — pre-resolved brand (skip brand-lookup)
> *"Show me [a specific brand ID]'s top YouTube spend partners"*

- **Competitor**: identified by ID, not name (no name resolution)
- **Expected success**: workflow skips the name-resolution step,
  goes straight to the competitor's deal data. Tests that the
  workflow doesn't blindly re-do work when the input is already
  resolved.

### Prompt 5 — niche-scoped competitor research
> *"Who's been pitching to cooking channels lately — any patterns?"*

- **Competitor**: not specified — the workflow must surface
  competitor brands as the OUTPUT, not consume them as input
- **Expected success**: workflow detects "find the competitors,
  then research them" intent, surfaces top brands sponsoring the
  niche, optionally lets the user pick one to drill into

## What does NOT qualify as success

The workflow run is **not successful** if the reply contains any of:

- ❌ Raw report data — one-row-per-deal, no aggregation or ranking
- ❌ A Phase 4 takeaway list that describes the report shape instead
  of answering the user's goal (*"the report has 47 rows across
  31 channels"* is report-shaped; *"top 10 channels with adjacency
  ranking"* is goal-shaped)
- ❌ A prompt back to the user that requires them to run a second
  workflow step manually (*"now run a separate report for your own
  brand and cross-reference"*)
- ❌ The user has to interpret two separate reports side-by-side to
  reach the answer
- ❌ More than 5 minutes wall-clock from prompt to reply
- ❌ Any of the v0.6.24 rule-compliance regressions (`Campaign #N`
  leak, `Reach` column header, `(id N)` row suffix, etc.)

## How we'll measure (step 4 ahead-of-time)

When step 4 (testing) runs:

| Prompt | E2E success criterion | Wall-clock budget |
|---|---|---|
| 1 | Outreach shortlist + adjacency + exclusions, named brands resolved | < 3 min |
| 2 | Same as 1, but with session-context brand resolution OR clarifier | < 3 min |
| 3 | Same as 1, triggered by goal-shaped (not report-shaped) prompt | < 3 min |
| 4 | Same as 1, but skips name-resolution step | < 2 min |
| 5 | Two-stage: surface competitor candidates, then drill into one | < 4 min |

All 5 must pass for the workflow to be considered "nailed" per
David's directive.

## What step 2 will define (not in this spec)

The next deliverable (step 2 of the template) is the **workflow
design** — answers to:

1. What's the workflow's user-facing surface (skill triggers,
   description shape, frontmatter)?
2. How does it invoke Report Builder?
   - As a sub-skill via natural-language hand-off?
   - As a sub-tool via a documented calling convention?
   - Which Report Builder components does it need access to:
     `name_resolver`, `similar_channels`, Type 2, Type 8, the
     validation loop, or some subset?
3. What's the synthesis step that turns 2-3 Report Builder outputs
   into the workflow's single reply?
4. What's the contract for adjacency ranking — by reach band? by
   demographic overlap? by topic similarity? by AI-summary
   similarity?
5. How does the workflow handle brand-name resolution failures,
   off-taxonomy niches, empty competitor footprints?
6. What changes (if any) does Report Builder itself need to support
   being invoked as a sub-tool (compose-mode? headless mode?)?

Each of those is a step-2 deliverable, separate PRs as needed.

## What step 3, 4, 5 will deliver (not in this spec)

- **Step 3**: build the workflow's SKILL.md based on step 2's design.
- **Step 4**: run all 5 prompts; record pass/fail per E2E criterion.
- **Step 5**: fix issues one at a time — each fix is its own PR;
  Report Builder gaps surface as PRs against `tl-cli:tl-report-builder`.

## Definition of "nailed"

All 5 prompts above pass their E2E criterion **and** the workflow has
been in live production use (i.e. invoked by the team for real work,
not just by the test set) for one full week without a manual fallback.

Per David's directive: not "the skill exists" — actual usage proof.
