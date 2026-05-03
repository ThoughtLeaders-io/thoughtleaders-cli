# AI Report Builder v2 — Skill-First Architecture


> ⚠️ **Policy update (2026-05-02)**: `tl reports create` was removed from the CLI by policy. References to it in this doc reflect the architecture as designed before the change. Phase 5 now displays JSON only; saving is handled outside the skill (platform UI / TBD internal mechanism). See [SKILL.md](../skills/tl-report-build/SKILL.md) Phase 5 for current behavior.


**Status as of 2026-04-29**: Topics cache live in prod (and actively migrating). Channel-field bypass fix in review (PR #3937). `thoughtleaders-cli` shipped to PyPI; **raw SQL endpoint `tl db pg` is live in sandbox** (read-only, sandboxed, mandatory `LIMIT/OFFSET`). Skill prototype work begins now — the data plane is `tl db pg`, no new CLI subcommands required.

This document captures the v2 architecture as agreed across:
- **David's skill-first pivot** (2026-04-27 daily call)
- **David's Filtering Builder framing** (sync state machine + data-validation loops)
- **David's "joins across data stores" thesis** (2026-04-23: "the true UVP is the TL data skill's ability to handle joins between different data stores")
- **Topics cache reseed** (PRs #3928 + #3926, v2 methodology)
- **`tl db pg` raw SQL deployment** (Josef + Ivan, 2026-04-28/29)
- **Skill refinement pipeline** (Creator/Judge/Coder, eval-framework branch)

---

## 1. Where we are now (foundation)

### What's live in production
- **`thoughtleaders_topics` table** — 10 pipeline-grounded topics at IDs 96–105
- **Schema**: `id`, `created_at`, `updated_at`, `name`, `description`, `keywords` (JSONB), `source`
- **Source tag**: `pipeline_analysis_v1` for cohort-based future rollback
- **Keyword count**: 182 across 10 topics (17–21 per topic), all ES-validated

### What's in the repo (audit + methodology layer)
- `evals/topics/seed_topics_v1.json` — full evidence trail per topic (brands, channels, IAB, strength)
- `evals/topics/keyword_sets_v1.json` — keywords organized by tier (`core_head`/`sub_segment`/`long_tail`) with per-keyword evidence
- `evals/topics/METHODOLOGY_v2.md` — the curation playbook
- `evals/topics/brand_verdicts/` — per-brand cluster decisions with evidence
- `evals/topics/SEEDING_PLAN.md`, `AUDIT.md`, `V2_FINDINGS.md` — historical decision context

### What's not yet built
- The matcher (LLM classifier mapping NL queries → topic verdicts)
- The orchestrator (the flow that takes a query and produces a saved report)
- The skill prototype (the Claude-orchestrated dev environment for the above)

---

## 2. The skill-first vision

David's directive (2026-04-27): build the v2 AI Report Builder as a **Claude skill prototype**, not as Python in the platform. Python is the final translation step, not the starting point.

### Why
- **Faster iteration** — change a tool's behavior in seconds, not in PR cycles
- **Better system design** — see the full flow working before committing it to code
- **Avoid premature engineering** — don't build a `match_topic.py` that turns out to need a different API

### What the skill is
A Claude-orchestrated flow that uses purpose-built tools to:
1. Take a natural-language query from a user
2. Match the query against the Topics cache
3. Generate or refine keyword sets if needed
4. Build a `FilterSet` aligned with David's Filtering Builder framing
5. Preview the result against real DB / ES data
6. Refine until satisfied
7. Save as a report

### What the skill is NOT
- A real-time, in-app code path (that's the eventual Python port)
- A standalone agent product (it's a dev environment for building v2)
- A replacement for the existing legacy v1 NL search (that keeps running until v2 is calibrated)

---

## 3. The four tools the skill needs

### Tool 1 — Topic Matcher
**Purpose**: Given a user query, return verdicts on which seeded topics match.

**Inputs**:
- User NL query (string)
- Optional: filter context (e.g., already-selected report type)

**Outputs (per topic)**:
```json
{
  "topic_id": 96,
  "topic_name": "Artificial Intelligence",
  "verdict": "strong" | "weak" | "none",
  "reasoning": "<why>",
  "matching_keywords": ["AI tools", "machine learning"]
}
```

**Implementation** (no new CLI subcommands — `tl db pg` is live):
- Skill calls `tl db pg --json "SELECT id, name, description, keywords, source FROM thoughtleaders_topics ORDER BY id LIMIT 100 OFFSET 0"` to fetch the **live** topic cache at the moment of every query — no static snapshot, no drift. The Topics table is actively migrating (fresh data landed 2026-04-27); a bundled file would go stale within days.
- Claude in the user's session reads the live response and does LLM-as-classifier reasoning over it
- **No cosine embeddings** — David's directive: verdict-based reasoning, not similarity scores
- Note: `tl db pg` enforces a 500-row hard cap. Topics table is well under that (10 rows today, < 100 expected long-term), so a single query suffices.

### Tool 2 — Keyword Researcher
**Purpose**: Generate/refine keywords for a query that doesn't cleanly match an existing topic.

**Inputs**:
- User NL query
- Optional: current keyword candidate list to refine

**Outputs**:
- Keyword candidates organized into `core_head` / `sub_segment` / `long_tail`
- Validated via `tl db pg` `COUNT(*)` queries against the relevant fact tables (channels, uploads, articles)
- Disambiguation flags against existing seeded topics (read live via `tl db pg "SELECT ... FROM thoughtleaders_topics ..."`)

**Implementation** (no new `tl` commands):
- Claude prompt that reasons about candidate keywords from the brand evidence + live topic data (fetched via `tl db pg`)
- Validates each keyword by composing `tl db pg` `COUNT(*)` queries against the relevant tables
- Disambiguation against existing topics uses the live response, never a stale file
- The keyword-research logic that lives in `thoughtleaders/.claude/skills/keyword-research/` today gets re-expressed as Claude prompts in the v2 skill

### Tool 3 — Validation via existing entity queries
**Purpose**: Check whether a constructed FilterSet returns sensible data — count + sample rows.

**Inputs**:
- A partial or complete `FilterSet` (as JSON)

**Outputs**:
- Count of matching rows
- A handful of sample rows
- Used as a gate between Pass A (filters) and Pass B (columns/widgets)

**Implementation** (uses `tl db pg` — the live raw-SQL endpoint):
- The skill orchestration (in `SKILL.md`) translates FilterSet filters into a single SQL query and runs it via `tl db pg --json`:
  - **`db_count`**: `SELECT COUNT(*) FROM <fact_table> WHERE <filters_translated_to_sql> LIMIT 1 OFFSET 0`
  - **`db_sample`**: `SELECT <key_columns> FROM <fact_table> WHERE <filters> ORDER BY <id_or_date> LIMIT 10 OFFSET 0`
- Reads the JSON response and reasons over count + sample
- Per David's framing: this validation step is **mandatory**, not optional
- **Why SQL beats entity-CLI composition for validation**: the saved-report query the platform eventually runs is itself a SQL query. Validating with SQL is a closer rehearsal than composing `tl channels`/`tl uploads`/`tl sponsorships` filters.

**Constraints carried by `tl db pg` (must respect):**
- Mandatory `LIMIT n OFFSET m` on every query, max 500 rows
- No DDL/DML, no multi-statement, no top-level `UNION`/`INTERSECT`/`EXCEPT` (wrap in CTE if needed)
- Forbidden functions: `random`, `pg_sleep`, `current_user`, `version`, `pg_read_file`, `lo_export`, `dblink`, `current_setting`, `set_config`
- Read-only access to user-visible schemas + `information_schema` + `pg_catalog`
- Server-side issues being tracked separately (NaN/numeric/timezone) — see `db-pg-server-issues.md`; none affect the use cases above
- A future `tl db es` and `tl db fb` arrive on the same pattern (super-user only initially per 2026-04-29 deployment plan)

### Tool 4 — FilterSet Builder
**Purpose**: Translate the skill's intent into a concrete `FilterSet` object that matches the platform's saved-report schema.

**Inputs**:
- Selected report type (BRANDS, CONTENT, THOUGHTLEADERS, etc.)
- Selected topics (from Topic Matcher)
- Selected keywords (from Keyword Researcher)
- Other filters (date range, content category, demographics, etc.)

**Outputs**:
- A complete `FilterSet` JSON object — filters + columns + widgets
- Compatible with the platform's `dashboard.models.FilterSet` schema
- For the prototype: displayed for human review (not auto-saved)

**Implementation** (no new `tl` commands):
- The "tool" is a Claude prompt (`prompts/filter_builder.md` for Pass A, `prompts/column_widget_builder.md` for Pass B) — no Python code
- Schema discovery via `tl db pg` queries against `information_schema.columns` (no `tl describe show` — see Section 6 for why higher-level entity commands are excluded from the v2 surface)
- Critically: respects the **two-pass `build_config`** David specified (filters first via `prompts/filter_builder.md`, then columns/widgets via `prompts/column_widget_builder.md` — separate LLM calls, not bundled)
- Per David: validation between passes (Tool 3) is **mandatory** (the orchestrator in `SKILL.md` enforces this)
- Save path during prototype: skill displays the JSON; user runs `tl reports create "<original prompt>"` separately if they want to commit. Auto-save can be added once the skill is trusted.

---

## 4. The flow — David's Filtering Builder framing

The skill executes the report-building flow as a **sync state machine** with explicit phases. Each phase has its own validation gate.

```
┌───────────────────────────────────────────────────────────────────┐
│ Phase 1: Report Type Selection                                    │
│   Input: NL query                                                 │
│   Tool:  Topic Matcher (lightweight pass to infer report type)    │
│   Output: ReportType enum (CONTENT, BRANDS, THOUGHTLEADERS, ...)  │
└────────────────────────┬──────────────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────────────┐
│ Phase 2: Filter Selection (LLM Pass A)                            │
│   Input: NL query + selected ReportType                           │
│   Tool:  Topic Matcher → topics                                   │
│         + Keyword Researcher → keywords (if needed)               │
│         + FilterSet Builder → partial FilterSet                   │
│   Output: Partial FilterSet (filters only — no columns/widgets)   │
└────────────────────────┬──────────────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────────────┐
│ Phase 3: Validation Loop (mandatory, per David)                   │
│   Tool: API / Data Bridge                                         │
│     - db_count(filterset) → "matches N rows"                      │
│     - db_sample(filterset) → "here are 10 examples"               │
│   Decision:                                                       │
│     - If 0 results or unreasonable → loop back to Phase 2         │
│     - If results look good → proceed to Phase 4                   │
│     - If too many results → suggest narrowing in Phase 2          │
└────────────────────────┬──────────────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────────────┐
│ Phase 4: Column/Widget Selection (LLM Pass B)                     │
│   Input: Validated FilterSet + report type                        │
│   Tool: FilterSet Builder (extending with columns/widgets)        │
│   Output: Complete FilterSet + columns + widgets                  │
└────────────────────────┬──────────────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────────────┐
│ Phase 5: Save                                                     │
│   POST /api/dashboard/campaigns/                                  │
│   → returns saved report URL                                      │
└───────────────────────────────────────────────────────────────────┘
```

### Why two LLM passes (David's directive)
- **Pass A** focuses on filters — the matcher reasons about *what to include*
- **Pass B** focuses on display — the matcher reasons about *what to show*
- Bundling them confuses the LLM — it tries to optimize both simultaneously and does both worse
- Per David: split is mandatory, not stylistic

### Why the validation loop is mandatory
- A proposed FilterSet might syntactically valid but semantically broken (e.g., zero matches, ambiguous overlap)
- `db_count` + `db_sample` ground the next decision in real data
- Without this, the LLM hallucinates report configs that look plausible but don't work

---

## 5. The refinement pipeline (skill-improvement loop)

The skill itself is built and tuned via a separate flow on the `eval-framework` branch (per `project_eval_framework_pivot.md`).

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Creator   │ ──> │    Judge    │ ──> │    Coder    │
│   (skill)   │     │   (eval)    │     │  (refine)   │
└─────────────┘     └─────────────┘     └─────────────┘
       ▲                                       │
       └───────────────────────────────────────┘
                  iterate
```

**Creator agent** runs the skill against a query corpus (goldens + Mixpanel real-user queries from #ai-report-builder).

**Judge agent** scores each output against assertion-style eval scorers — *did the skill produce a sensible FilterSet? Did `db_count` show non-zero results? Did the column selection match the report type?*

**Coder agent** uses the Judge's scores to refine the skill's tools, prompts, or flow logic.

This loop runs offline, not in production. It's a dev-time tool for getting the skill ready before any Python port.

---

## 6. Where the skill lives — `tl-cli` only

**Decision (2026-04-28)**: develop the v2 skill exclusively in the `tl-cli` repo. The `thoughtleaders` repo's existing `.claude/skills/create-report/` stays as the v1 reference but receives no v2 work.

### What this means architecturally

The v2 flow inverts the current v1 architecture:

| Concern | v1 (today) | v2 (target) |
|---|---|---|
| Where orchestration runs | Server (`thoughtleaders/.claude/skills/create-report/scripts/`) | Client (Claude on user's machine, via `tl-cli` skill) |
| LLM provider | Server-side LLM service | Claude on the user's machine |
| Tool surface | Direct Python imports (Django ORM, ES client) | `tl` CLI subcommands (which call platform APIs) |
| User entry point | `tl reports create "<prompt>"` → server pipeline | `tl reports create "<prompt>"` → loads CLI skill, runs flow locally |
| Server's role | Orchestrator | Pure data API |

### Why CLI-only is the right call here

- **David's skill-first vision is fundamentally a client-side orchestration model.** The whole point is "Claude does the AI work, server provides data." Hosting the skill on the server contradicts that.
- **Iteration speed**: `tl-cli` is a small repo. Skill edits land instantly. No platform CI to wait on.
- **Clean separation of concerns**: server APIs get versioned, the skill above them iterates freely. The skill never imports platform code.
- **Forces the right API contracts**: if the skill needs something the server doesn't expose, that's a real API gap that should be addressed by adding endpoints — not by reaching past the boundary into Django.
- **No accidental coupling**: when v2 ports to Python later, the skill's tool calls map cleanly to platform API calls. The skill's logic lives in prompts + flow control, not in Python that imports Django.

### Constraint that comes with the choice

**The v2 skill uses only the 3 DB endpoint commands** plus `tl ask` as the entry point. Per the 2026-04-23 daily call: *"Higher-level commands (Brands, Channels) are just layers that duplicate schema knowledge + joins on top of these primitives."* The skill bypasses those layers and goes straight to the raw DB endpoints. The available surface:

- `tl ask "<NL query>"` — **the entry point for v2**. User types a natural-language request; the CLI (with the skill loaded) routes to local Claude orchestration.
- `tl db pg --json "<SQL>"` — **the canonical data plane (live in sandbox)**. Sandboxed read-only Postgres. Used for: live topics fetch, schema discovery via `information_schema`, validation `db_count`, validation `db_sample`. Mandatory `LIMIT/OFFSET`, max 500 rows.
- `tl db es --json "<query>"` — Elasticsearch endpoint (super-user only initially per 2026-04-29 deployment plan). Used by the skill once available.
- `tl db fb --json "<SQL>"` — Firebolt endpoint (super-user only initially). Time-series snapshots; not needed for the M1–M6 prototype.
- `tl whoami`, `tl balance` — auth + credit awareness (used by the skill to verify the user is signed in)

**Explicitly excluded from the v2 skill surface:**
- `tl describe show <resource>` — duplicative; replaced by `tl db pg` against `information_schema`
- `tl channels`, `tl brands`, `tl sponsorships`, `tl uploads` — duplicative; replaced by raw SQL
- These commands continue to exist in the CLI for human users; the skill just doesn't use them.

### How the skill works with the live CLI

**Topics data** — `tl db pg --json "SELECT id, name, description, keywords, source FROM thoughtleaders_topics ORDER BY id LIMIT 100 OFFSET 0"`. Live, every invocation, no drift. Originally we considered a snapshot file (rejected: drift) and then a `tl topics list` wrapper (rejected: redundant given `tl db pg`).

**Preview / validation** — `tl db pg --json "SELECT COUNT(*) FROM ... WHERE <filters> LIMIT 1 OFFSET 0"` for `db_count`; `tl db pg --json "SELECT ... LIMIT 10 OFFSET 0"` for `db_sample`. The skill writes the SQL itself, which is closer to what the saved-report path eventually executes than any entity-CLI composition.

**Schema discovery** — `tl db pg --json "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'channels' LIMIT 200 OFFSET 0"`. Inline, per-invocation as needed; no caching layer. `tl describe show` is **excluded** from the v2 surface (see Constraints subsection above).

**Save** — for the early prototype, the skill produces a complete FilterSet/columns/widgets JSON and displays it. The human reviews and uses `tl reports create "<original prompt>"` (or another existing save path) when ready. Once the skill is trusted, this becomes automatic.

This keeps prototype scope **purely on the skill side** — zero platform PRs required to start. Every primitive the skill needs already ships in `thoughtleaders-cli` v0.5.0+.

### Practical layout

```
tl-cli/skills/tl-report-build/                       ← v2 skill home
├── SKILL.md                                          ← entry point + flow description (high-level)
├── prompts/
│   ├── topic_matcher.md                              ← LLM Pass A: query → topic verdicts
│   ├── filter_builder.md                             ← LLM Pass A: query + topics → filters
│   └── column_widget_builder.md                      ← LLM Pass B: filterset → columns + widgets
├── data/
│   └── sortable_columns.json                         ← copied from existing TL repo skill (column metadata)
│                                                      (no topics file — fetched live via `tl topics list`)
└── examples/
    └── golden_queries.md                             ← test cases for hand-validation

tl-cli/skills/tl/                                     ← existing data-analyst skill
└── SKILL.md                                          ← unchanged

thoughtleaders/.claude/skills/create-report/         ← v1 reference, frozen
└── (unchanged; serves as legacy until sunset)
```

The skill is essentially **prompts + flow markdown + bundled snapshot data**. The "tools" it uses are existing `tl` subcommands invoked via Bash. No Python scripts in the skill itself, no new server endpoints, no new CLI subcommands — that's the prototype constraint.

### Zero cross-repo work for the prototype

Everything needed is already in place. With `tl db pg` live, no new CLI subcommands are required:

| Need | How it's met |
|---|---|
| User invokes the skill | `tl ask "<NL request>"` (existing CLI command) |
| Skill reads topic cache (live) | `tl db pg --json "SELECT ... FROM thoughtleaders_topics ..."` |
| Skill validates filters against real data | `tl db pg --json "SELECT COUNT(*) ..."` and `... LIMIT 10 OFFSET 0` |
| Skill reads schema of resources | `tl db pg` against `information_schema` (only — `tl describe` excluded from v2 surface) |
| Skill commits a saved report (later) | `tl reports create` (or display config and human commits) |

Future additions like `tl preview` (unified count+sample) are deferred until a real need surfaces during prototyping. ES and Firebolt SQL endpoints (`tl db es`, `tl db fb`) come online for super-users on the same pattern; the skill picks them up automatically when available.

### Why we don't do the hybrid approach (revised)

Earlier draft proposed hybrid (canonical in TL repo + thin wrapper in CLI). Rejected because:
- It hides the platform-API contract behind direct imports — the very seam we want clean
- It creates "magic" in the CLI: users see `tl reports create` but the work happens elsewhere
- It creates two homes of truth that can drift
- It conflicts with David's "Python is the final step" framing

CLI-only forces every cross-boundary call to be an explicit API call. That's the discipline the v2 architecture needs.

---

## 7. The boundary between skill and platform

### What lives in the skill (Claude-orchestrated, edit in seconds)
- Topic matching logic (the LLM-as-classifier)
- Keyword research orchestration
- Filter-builder reasoning (the two LLM passes)
- Validation loop logic
- Refinement decisions

### What lives in the platform (Python, in TL repo)
- `thoughtleaders_topics` table + schema (already live)
- ES indexes + the `_build_content_query` / `_batch_has_parent_queries` helpers (already live; PR #3937 fixes the topic path)
- CLI APIs the skill calls (`/api/cli/v1/...`)
- Saved-report endpoint (`POST /api/dashboard/campaigns/`)
- Auth, billing, usage tracking — all platform concerns

### The boundary contract
The skill **only** talks to the platform via:
- DB reads (`thoughtleaders_topics` for the matcher)
- CLI APIs (for previews + sample data)
- Saved-report POST (for final commit)

This means: **the skill can be entirely rewritten without touching platform code**, and vice versa. Clean seam.

---

## 8. Calibration + Python port (later phases)

Once the skill flow is working and the refinement pipeline produces good results:

### Phase A — Skill validates against production-like data
- Real queries from `#ai-report-builder` Slack history
- Real saved-report patterns from existing FilterSets
- Mixpanel logs of NL search usage

### Phase B — Translate validated skill logic to Python
- Replace the skill's LLM calls with platform LLM service (OpenRouter / direct Anthropic)
- Replace the skill's tool calls with direct DB / ES / API calls
- Wire into `orchestrate_preview.py` (or its v2 successor)

### Phase C — Flag flip
- Behind a feature flag (existing pattern in TL)
- Roll out to a small cohort
- Measure agreement between v1 and v2 paths
- Ramp to 100% if metrics hold

### Phase D — Sunset legacy
- Once v2 is canonical, retire the legacy v1 NL search code
- Reclaim the keyword-pipeline skill into the new v2 path

---

## 9. Open questions (worth flagging early)

### Q1 — Does the skill need its own DB / state?
The skill might want to maintain conversation state across phases (e.g., "user picked AI in Phase 2; remember that in Phase 4"). Decide whether this lives in the skill's runtime memory, in a scratch table in the platform DB, or in a session store.

### Q2 — How to handle multi-topic queries?
A query like "AI cooking shows" might match both AI and Cooking. The matcher needs to support multi-select with disambiguation rules (already documented in `keyword_sets_v1.json`'s `overlap_rules`).

### Q3 — When does the skill ask for clarification vs. assume?
Per David's framing, validation loops catch zero-result FilterSets. But what about ambiguous queries (e.g., "tech YouTubers" — Computing or AI?). Decide whether the skill prompts the user or makes its best guess + lets the user adjust.

### Q4 — Where does the IAB taxonomy fit?
Topics map to IAB Tier 2 today. Should the skill use IAB Tier 1 + Tier 2 as a coarser navigation layer when topic matching is weak?

### Q5 — Does the skill have access to the eval files?
The skill could read `seed_topics_v1.json` for richer per-topic context (brand evidence, channel patterns, etc.) than the DB exposes. Decide whether the skill ships with read access to that file (good for explainability) or only sees the DB (cleaner boundary).

---

## 10. Concrete next steps — milestones, not timelines

Sequenced by dependency, not by week. Each milestone unblocks the next; pace yourselves on the work.

**All work is in `tl-cli` repo.** Zero platform PRs required to start — `tl db pg` already provides everything. Entry point is `tl ask "<NL request>"`.

### Milestone 1 — Skill scaffolding
- Create `tl-cli/skills/tl-report-build/` directory
- Write a stub `SKILL.md` — entry point, describes the five-phase flow at a high level, declares the trigger conditions ("user mentions building/creating/saving a report")
- Copy `sortable_columns.json` from the TL repo's `create-report/data/` into `data/`
- Add an `examples/golden_queries.md` with ~20 hand-curated NL queries pulled from `#ai-report-builder` Slack
- (Topics fetched live via `tl db pg` SELECT — no snapshot file, no new CLI subcommand)

**Exit signal**: skill loads when a user types something like `tl ask "build me a report about gaming channels"`; the skill produces a "not yet implemented" stub response that lists the phases it would execute, plus a verified live `tl db pg` topics fetch dumped to stdout.

### Milestone 2 — Topic Matcher prompt
- Write `prompts/topic_matcher.md` — instructions for Claude on how to score a query against the live topics array (fetched via `tl db pg --json "SELECT id, name, description, keywords, source FROM thoughtleaders_topics ORDER BY id LIMIT 100 OFFSET 0"` at the start of every invocation)
- Output schema: per-topic verdict JSON (`strong` / `weak` / `none` + reasoning + matching keywords)
- The matcher reads the live response and reasons in-session — no static file, no drift
- Test against the golden queries from Milestone 1

**Exit signal**: for at least 80% of golden queries, the matcher produces a defensible verdict (subjective hand-rating).

### Milestone 3 — Filter-builder prompt (LLM Pass A)
- Write `prompts/filter_builder.md` — instructions for translating NL query + matched topics into a partial FilterSet
- Tools it composes: `tl db pg` against `information_schema.columns` for live schema discovery (no `tl describe` — excluded from v2 surface)
- Output: partial FilterSet JSON (filters only — no columns/widgets yet)

**Exit signal**: for the golden queries, the prompt produces FilterSet JSONs whose column references all resolve against the live `information_schema`.

### Milestone 4 — Validation loop via `tl db pg`
- Define orchestration in `SKILL.md`: after filter_builder produces a FilterSet → translate filters to a `tl db pg` SQL query →
  - `db_count`: `SELECT COUNT(*) FROM <table> WHERE <filters> LIMIT 1 OFFSET 0`
  - `db_sample`: `SELECT <key_cols> FROM <table> WHERE <filters> ORDER BY <id_or_date> LIMIT 10 OFFSET 0`
- If `count == 0` → re-prompt filter_builder with feedback
- If `count` is reasonable → proceed to Pass B
- Cap iterations at 3 to prevent infinite loops
- Mind the `tl db pg` constraints: every query needs `LIMIT/OFFSET`, max 500 rows, no top-level UNION, forbidden-function list

**Exit signal**: pathological queries (overly narrow keyword combinations) self-correct in ≤ 2 retries against real prod data via `tl db pg`.

### Milestone 5 — Column/widget prompt (LLM Pass B)
- Write `prompts/column_widget_builder.md` — given a validated FilterSet + report type, choose columns and widgets
- Tools it uses: `data/sortable_columns.json` for column metadata; `tl db pg` against `information_schema` if a live cross-check is needed
- Output: complete report config (filters + columns + widgets)

**Exit signal**: golden queries produce config JSONs that include sensible columns for the inferred report type.

### Milestone 6 — End-to-end output (display, no save)
- Skill's final phase produces the complete report config JSON
- For the prototype: display it for human review; suggest the user runs `tl reports create "<original prompt>"` if they want to actually save (or copy/paste the JSON via existing means)
- No automatic save during prototype — keeps the human in the loop

**Exit signal**: invoking the skill on a golden query end-to-end produces a config JSON that, when reviewed, makes sense for the prompt.

### Milestone 7 — Mixpanel corpus eval
- Pull ~100 real NL search queries from Mixpanel (last 30–90 days)
- Run the skill against each
- Manually rate outputs (does the produced config match user intent?)
- Categorize failures: matcher errors, builder errors, validation errors

**Exit signal**: documented set of failure cases with category counts.

### Milestone 8 — Refinement pipeline (Creator/Judge/Coder)
- Set up offline loop (likely on a new branch in `tl-cli`)
- Goldens + Mixpanel corpus as Creator inputs
- Eval scorers (FilterSet shape, real-count > 0 via `tl db pg`, column-type alignment) as Judge's assertion library
- Coder agent iterates on prompts based on Judge feedback

**Exit signal**: skill measurably improves across iterations on a held-out test set.

### Milestone 9 — Calibration in shadow mode
- Run skill against real users' v1 queries (without showing v2 output to users)
- Compare v2's config to what v1 produced
- Measure agreement; surface meaningful divergences

**Exit signal**: skill's outputs match or beat v1 on agreed metrics for a sustained window.

### Milestone 10 — Promote (and optionally add more tl commands)
- Once shadow-mode metrics hold, the skill becomes the canonical path
- *Now* is the time to evaluate adding `tl preview` (so validation is more efficient than composing entity queries) — but only if that gap actually hurts at this point
- Translate validated logic to platform Python (server-side, behind a feature flag) for users without Claude
- Ramp to 100%, deprecate v1 server pipeline

**Exit signal**: v2 is the only active path; v1 code is removed.

### Milestone 11 — Sunset legacy
- Retire `thoughtleaders/.claude/skills/create-report/` (the v1 reference)
- Promote useful skill artifacts (prompts, eval corpus, brand verdicts) to permanent doc locations
- Archive intermediate eval artifacts

---

## 11. References

### Memory files (auto-loaded for future sessions)
- `project_skill_first_pivot.md` — David's 2026-04-27 directive
- `project_filtering_builder_framing.md` — sync state machine + two-pass build_config
- `project_three_agent_flow.md` — Creator/Judge/Coder offline dev tool
- `project_eval_framework_pivot.md` — refinement pipeline architecture
- `project_topics_scrap_reseed.md` — Topics cache decision history

### Implementation evidence (in this repo)
- `evals/topics/METHODOLOGY_v2.md` — the topic curation playbook
- `evals/topics/seed_topics_v1.json` — live topics' full audit trail
- `evals/topics/V2_FINDINGS.md` — measurable-evidence corrections to v1
- `evals/topics/brand_verdicts/` — per-brand clustering decisions

### Code references (live in prod)
- `thoughtleaders/models.py:Topics` — schema
- `thoughtleaders/migrations/0490_topics_add_description_source_and_reseed.py` — destructive base
- `thoughtleaders/migrations/0491_load_pipeline_seed_topics.py` — seed data (frozen inline)
- `thoughtleaders/request_parsers/article.py:907` — runtime ES expansion path
- `thoughtleaders/views/topics.py` — REST endpoint exposing topics
- `dashboard/models.py:FilterSet` — the target object the skill produces

### CLI references (live)
- `thoughtleaders-cli` on PyPI (≥ v0.5.0) — https://pypi.org/project/thoughtleaders-cli/
- `tl db pg` — raw SQL endpoint (read-only, sandboxed); see `db-pg-server-issues.md` for tracked server-side issues (NaN/numeric/timezone) — none affect the skill's read paths
- `tl db es`, `tl db fb` — coming on the same pattern; super-user only initially per 2026-04-29 deployment plan

### External
- IAB Content Taxonomy v3 (Tier 1 / Tier 2) — used for topic-name alignment

---

## TL;DR

**`tl db pg` is live and `thoughtleaders-cli` is on PyPI.** The v2 AI Report Builder gets built as a **Claude skill in `tl-cli/skills/tl-report-build/`** — pure CLI, **zero new platform subcommands**. The skill's data plane is `tl db pg` raw SQL: live topics fetch, schema discovery against `information_schema`, validation `db_count`/`db_sample`. No drift, no snapshots, no platform PRs.

**Entry point**: `tl ask "<NL request>"` — natural-language CLI typing routes to the skill, which orchestrates locally in the user's Claude session.

**Tools** (all riding on existing CLI surface):
- **Topic Matcher** — `tl db pg "SELECT ... FROM thoughtleaders_topics ..."` (live)
- **Filter Builder Pass A** — `tl db pg` against `information_schema` for schema discovery
- **Validation** — `tl db pg "SELECT COUNT(*) ..."` and `... LIMIT 10 OFFSET 0` for sample
- **Column/Widget Builder Pass B** — produces final config
- **Save** — for prototype, displays JSON; user runs `tl reports create` if they want to commit

Refined offline via Creator/Judge/Coder against goldens + Mixpanel corpus. Once shadow-mode metrics hold, the skill becomes the default path. New CLI subcommands (`tl preview` for unified count+sample) get added at promotion time *only if needed* by then. Eventually ports to Python (server-side) behind a flag for users without Claude. ES (`tl db es`) and Firebolt (`tl db fb`) endpoints arrive on the same pattern — the skill picks them up for cross-store reasoning, in line with David's "joins between data stores" UVP thesis.

PR #3937 (channel-field bypass fix) is independent of this work — it cleans up runtime ES expansion so saved reports built with v2 produce correct results. The skill prototype itself starts immediately, no blockers.
