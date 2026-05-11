---
name: tl-report-build
description: Build a saved ThoughtLeaders report from a natural-language request. Triggers when the user asks to build, create, design, configure, or save a report; or when `tl ask` receives a report-building request. Orchestrates topic matching, filter construction, real-data validation, and column/widget selection — locally in the user's Claude session, against the existing `tl` CLI surface.
---

# ThoughtLeaders Report Builder (v2 prototype)

> **Status: Milestone 1 — scaffolding.** The phases below are described but not yet implemented. When triggered, this skill currently emits a stub response that names each phase it would run. Subsequent milestones fill in the prompts and orchestration.

## What this skill does

Given a natural-language request like *"build me a report about gaming channels in the US"*, this skill produces a complete report configuration (filters + columns + widgets) compatible with `tl reports create`. The user reviews the configuration and chooses whether to save.

This is the **client-side** report builder. Claude orchestrates the flow on the user's machine; the platform's role is reduced to data APIs (which `tl` already calls).

## When to trigger

Trigger on any of:

- The user asks to **build, create, design, configure, or save a report**
- The user says something like *"can you make me a dashboard for X"*, *"set up tracking for Y"*, *"I want to monitor Z"*
- `tl ask "<query>"` is invoked and the query reads as a report-building request rather than a one-shot data lookup

Do **not** trigger for one-shot data questions ("how many sold deals last week?") — those route to the `tl` data-analyst skill, which composes structured queries directly.

If the request is ambiguous between "answer this question" and "save a report that answers this question", ask the user which they want before running this skill.

## The flow (five phases)

This skill executes a sync state machine. Each phase has a clear input, output, and validation gate. Stop and ask the user if any phase produces a result you cannot defend.

### Phase 1 — Report Type Selection

**Input**: the user's NL request.

**Action**: classify the request into a report type (e.g. `CONTENT`, `BRANDS`, `THOUGHTLEADERS`, `CHANNELS`). Use the schema returned by `tl describe show reports` to confirm the available types.

**Output**: a single report-type label.

### Phase 2 — Filter Selection (LLM Pass A)

**Input**: NL request + selected report type.

**Action**:
1. **Topic match.** Read `data/topics_v1.json` (bundled snapshot of the seeded topic cache). Run `prompts/topic_matcher.md` to score each topic in the snapshot as `strong` / `weak` / `none`, with reasoning + matching keywords.
2. **Keyword research.** If no topic is `strong`, generate candidate keyword sets and validate each via `tl channels keyword:"<kw>" --json` or `tl uploads search:"<kw>" --json` to confirm the keyword returns non-zero results.
3. **Filter build.** Run `prompts/filter_builder.md` to translate matched topics + keywords + other request hints (date range, demographics, geo) into a partial FilterSet (filters only — no columns/widgets yet). Use `tl describe show <resource> --json` to discover the legal filter keys for the report type.

**Output**: a partial FilterSet (JSON) — filters only.

### Phase 3 — Validation Loop

**Input**: the partial FilterSet from Phase 2.

**Action**: translate the filters into the equivalent `tl` invocation and check real data:

| Report type focus | Validation command |
|---|---|
| Channel-side filters | `tl channels <filters> --json --limit 10` |
| Sponsorship-side filters | `tl sponsorships <filters> --json --limit 10` |
| Upload-side filters | `tl uploads <filters> --json --limit 10` |
| Brand-side filters | `tl brands <filters> --json --limit 10` |

Read `total` from the response envelope and the first 10 rows.

**Decision rules**:
- `total == 0` → loop back to Phase 2 with feedback ("filters too narrow; here is what was tried"). Cap at **3 retries**.
- `total` is reasonable for the request (judged by Claude in context, not a hard threshold) → proceed to Phase 4.
- `total` is enormous (e.g. millions of rows for a request that implies a small cohort) → loop back to Phase 2 to narrow.

This loop is **mandatory**, not optional. A FilterSet that has not been validated against real data must not advance.

**Output**: a validated FilterSet + a sample of rows (kept in working memory for Phase 4 context).

### Phase 4 — Column / Widget Selection (LLM Pass B)

**Input**: validated FilterSet + report type + sample rows.

**Action**: run `prompts/column_widget_builder.md` to pick the columns and widgets that best surface the answer the user asked for. Consult `data/sortable_columns.json` for column metadata (sortability, default direction, display name) and `tl describe show <resource> --json` for the full available column set.

This is a **separate LLM call** from Phase 2. Do not bundle filter selection and column/widget selection into one prompt — the model optimizes both worse when they are combined.

**Output**: a complete report configuration (filters + columns + widgets) as JSON.

### Phase 5 — Save (or display)

**Action during prototype**: display the complete configuration JSON for human review. Suggest the user run `tl reports create "<their original request>"` if they want to commit it. Do **not** auto-save during the prototype phase.

**Future**: once the skill is trusted via the offline refinement pipeline, this phase calls `tl reports create` directly with the constructed config.

## Tools the skill uses

The skill has **no Python and no new `tl` subcommands**. Every "tool" is a prompt or a composition of existing CLI calls:

| Tool | Implementation |
|---|---|
| Topic Matcher | `prompts/topic_matcher.md` reading `data/topics_v1.json` |
| Keyword Researcher | Reasoning over candidate keywords + validation via `tl channels keyword:"<kw>"` / `tl uploads search:"<kw>"` |
| Schema discovery | `tl describe show <resource> --json` |
| Validation (count + sample) | `tl channels` / `tl uploads` / `tl sponsorships` / `tl brands` with the candidate filters |
| Filter Builder (Pass A) | `prompts/filter_builder.md` |
| Column / Widget Builder (Pass B) | `prompts/column_widget_builder.md` + `data/sortable_columns.json` |
| Save | `tl reports create` (manual during prototype) |

If a real gap surfaces during prototyping (e.g. composing four entity queries to estimate a count gets unwieldy), that's a signal to add a new `tl` subcommand — but only at promotion time, not preemptively.

## Working files

```
skills/tl-report-build/
├── SKILL.md                            ← this file
├── prompts/
│   ├── topic_matcher.md                ← (Milestone 2)
│   ├── filter_builder.md               ← (Milestone 3)
│   └── column_widget_builder.md        ← (Milestone 5)
├── data/
│   ├── topics_v1.json                  ← topic cache snapshot (synced from prod)
│   └── sortable_columns.json           ← column metadata
└── examples/
    └── golden_queries.md               ← hand-curated test cases
```

## Stub behaviour during Milestone 1

Until the prompts in `prompts/` are written, when this skill is triggered:

1. Acknowledge the user's request.
2. List the five phases above as a checklist, marking each `[ ] not yet implemented`.
3. Suggest the user falls back to the legacy `tl ask` server-side path or the existing `tl reports create` flow.
4. Do not produce a fabricated FilterSet.

## Refinement (offline)

The skill itself is improved via a separate Creator/Judge/Coder loop run on goldens (`examples/golden_queries.md`) and real-user query corpora. That loop does **not** run when the skill is triggered by an end user — it's a dev-time tool. See the project architecture document for details.

## Constraints

- **CLI-only.** This skill never calls platform APIs directly. Everything goes through `tl`.
- **No new `tl` subcommands during the prototype.** Compose what exists.
- **No auto-save** during the prototype. Always display the config and let the user commit explicitly.
- **Validation loop is mandatory.** A FilterSet that has not been checked against real data with a real count must not advance to Phase 4.
- **Two LLM passes are mandatory.** Filter selection and column/widget selection are separate calls.
