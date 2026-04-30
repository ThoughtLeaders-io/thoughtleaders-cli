---
name: tl-report-build
description: |
  Build TL saved reports from natural-language requests via Claude orchestration on the user's machine.
  Triggers when the user says things like: "build a report about ...", "create a campaign for ...",
  "make a report on ...", "save a dashboard about ...", "find me channels for ...".
  Five-phase flow: Report Type Selection → Filter Builder Pass A → Validation Loop → Column/Widget Builder Pass B → Display config (or save).
  Data plane is `tl db pg` raw SQL (interim: `tl-data` skill's `pg_query.py` until `tl db pg` rolls out broadly).
  This is the v2 successor to the server-side `create-report` skill in `thoughtleaders-skills/`. v1 stays as the legacy reference until v2 is calibrated.
---

# tl-report-build (v2 prototype scaffolding — M1 stub)

Five-phase Claude-orchestrated flow for translating a natural-language request into a TL saved report config.

> **Status**: Milestone 1 scaffolding only. Phases 1–5 are described here but not yet implemented as prompts. Subsequent milestones add the prompts one by one.

---

## When this skill triggers

The user is asking for a saved TL report — not a quick lookup, not a Slack-post summary. Strong signals: "build", "create", "make", "save", "campaign", "dashboard", "report". Soft signals: "find me X channels", "show me deals where X" (these may just want a quick list — ask before invoking).

If unclear: ask the user `"Do you want a saved TL report, or just a list here in chat?"` before running the flow.

---

## The phases

```
NL query
    │
    ▼
Phase 1 — Report Type Selection         (no CLI calls; M3+)
    │   inference: CONTENT (1) | BRANDS (2) | CHANNELS (3) | SPONSORSHIPS (8)
    ▼
Phase 2a — Topic Matcher                (LLM call #1; M2 ✓)
    │   reads: live topics via tl db pg against thoughtleaders_topics
    │   produces: per-topic verdicts (strong | weak | none) + summary
    ▼
Phase 2b — Keyword Research             (LLM call #2 + tl db pg validation; M3 part 1)
    │   STRICT TRIGGER:
    │     RUN  iff  report_type ∈ {1,2,3}  AND  summary.strong_matches is empty
    │     SKIP if   strong topic match exists  (trust topic's curated keywords[])
    │     SKIP if   report_type == 8 (SPONSORSHIPS — no ES content matching)
    │   inputs:  NL query (no topic anchor; that's why we're here)
    │   produces: validated KeywordSet
    │             { core_head, sub_segment, long_tail, content_fields,
    │               recommended_operator, validated: [...] }
    │   logic:   LLM proposes candidates → tl db pg COUNT(*) per candidate
    │            → prune zero-count → emit set
    │   this is the ONLY filter signal Phase 2c gets in this branch
    ▼
Phase 2c — Filter Builder, Pass A       (LLM call #3; M3 part 2)
    │   reads: NL query + verdicts + KeywordSet + live schema (information_schema)
    │   produces: partial FilterSet (filters only — no columns/widgets yet)
    ▼
Phase 3 — Validation Loop               (MANDATORY; M4)
    │   db_count: tl db pg "SELECT COUNT(*) ... LIMIT 1 OFFSET 0"
    │   db_sample: tl db pg "SELECT ... LIMIT 10 OFFSET 0"
    │   if count == 0   → retry from Phase 2b/2c with feedback
    │   if count >> ok  → narrow filters
    │   else            → proceed to Phase 4
    │   cap: 3 retries
    ▼
Phase 4 — Column/Widget Builder, Pass B (LLM call #4; M5)
    │   reads: data/sortable_columns.json
    │   produces: full report config (filters + columns + widgets)
    ▼
Phase 5 — Display (prototype) / Save (later; M6)
    │   prototype: print JSON, suggest `tl reports create "<original prompt>"`
    │   later: auto-POST to /api/dashboard/campaigns/
```

---

## Phase 2a — Topic Matcher (how to invoke)

The matcher prompt lives at `prompts/topic_matcher.md`. To run Phase 2a:

1. **Fetch live topics** via the data plane:
   ```bash
   # Primary (tl-cli ≥ v0.6.2):
   tl db pg --json "SELECT id, name, description, keywords FROM thoughtleaders_topics ORDER BY id LIMIT 100 OFFSET 0"

   # Fallback (older CLI / no PG sandbox access):
   python ~/Desktop/ThoughtLeader/thoughtleaders-skills/tl-data/scripts/pg_query.py \
     "SELECT id, name, description, keywords FROM thoughtleaders_topics ORDER BY id LIMIT 100 OFFSET 0" \
     --format json
   ```

   **Response shape difference (important):**
   - `tl db pg --json` returns `{"results": [...]}` — extract `.results` before passing as `TOPICS` to the matcher
   - `pg_query.py --format json` returns a bare `[...]` array — pass directly as `TOPICS`
   - The matcher prompt expects `TOPICS` to be the bare array; the orchestration normalizes

2. **Load the matcher prompt**: `Read prompts/topic_matcher.md` and inject the contents as a system-style instruction.

3. **Run the LLM call** with:
   - `USER_QUERY` = the NL request
   - `TOPICS` = the JSON array from step 1

4. **Parse the output** as JSON. The matcher returns `{ query, verdicts, summary }`. Pass `verdicts` and `summary` to Phase 2b.

### Phase 2a contract (downstream consumers)

- **`summary.strong_matches`** is the canonical list of topic IDs whose `keywords[]` arrays Phase 2c will translate into `keyword_groups`. **There is no `topics:` field on v1's FilterSet** — topic IDs are v2 routing metadata only; the platform sees only the resolved `keyword_groups`.
- **`summary.weak_matches`** is informational — Phase 2c may surface these to the user as "did you also mean...?" but doesn't translate them to keyword_groups by default
- **`summary.no_match == true`** means the query is off-taxonomy. Phase 2b runs (per the strict trigger) and generates fresh `keyword_groups` from scratch; Phase 2c emits those directly as the only filter signal
- **`verdicts[i].matching_keywords`** is a strict subset of the corresponding topic's `keywords` array — Phase 2b can trust them as already-validated

### Phase 2a constraints (what the matcher must NOT do)

These are encoded in `prompts/topic_matcher.md`:
- Force a match when none fits (off-taxonomy must return all-`none`)
- Invent keywords that aren't in `topic.keywords`
- Pick one winner when multiple topics fit (multi-`strong` is correct and expected)
- Let report-type signals (`"partnership"`, `"sponsorship"`, `"deal"`) drive a verdict — those are Phase 1's concern

---

## CLI surface used by this skill (only these)

Per the 2026-04-23 daily call: the v2 skill uses the **3 DB endpoint commands plus `tl ask`** as primitives. Higher-level entity commands (`tl channels`, `tl describe`, etc.) are excluded — they're "layers that duplicate schema knowledge" on top of the primitives.

| Command | Purpose |
|---|---|
| `tl ask "<NL request>"` | Skill entry point |
| `tl db pg --json "<SQL>"` | Postgres data plane (live in sandbox) |
| `tl db es --json "<query>"` | Elasticsearch (super-user, coming) |
| `tl db fb --json "<SQL>"` | Firebolt (super-user, coming) |
| `tl whoami`, `tl balance` | Auth + credit awareness |

**Interim transport** (until `tl db pg` rolls out broadly): use the `tl-data` skill's `python scripts/pg_query.py "<SQL>"`. Same SQL, same DB; just a different invocation. Write SQL with `LIMIT n OFFSET m` and the forbidden-functions list compliance from day one so the swap to `tl db pg` is a one-line change.

**`tl db pg` constraints** (also enforced for `pg_query.py` SQL during prototype):
- Mandatory `LIMIT n OFFSET m` on every query, max 500 rows
- Read-only SELECT — no DDL/DML, no multi-statement
- No top-level `UNION`/`INTERSECT`/`EXCEPT` (wrap in CTE)
- Forbidden functions: `random`, `pg_sleep`, `current_user`, `version`, `pg_read_file`, `lo_export`, `dblink`, `current_setting`, `set_config`

---

## Files in this skill

```
tl-cli/skills/tl-report-build/
├── SKILL.md                               ← this file
├── prompts/
│   ├── _v1_system_prompt_REFERENCE.txt   ← copy of v1's 999-line system prompt; mark sections to keep/change/drop incrementally
│   ├── topic_matcher.md                   ← M2: query → topic verdicts (TODO)
│   ├── filter_builder.md                  ← M3: NL + topics + schema → partial FilterSet (TODO)
│   └── column_widget_builder.md           ← M5: filterset + report_type → columns + widgets (TODO)
├── data/
│   └── sortable_columns.json              ← copied from v1; column metadata for Phase 4
└── examples/
    └── golden_queries.md                  ← hand-curated NL queries for hand-validation
```

---

## Reference docs (in this repo)

Living at `tl-cli/docs/`:
- `../../docs/SKILL_ARCHITECTURE.md` — full v2 architecture
- `../../docs/SKILL_VISUAL_ARCHITECTURE.md` — diagrams
- `../../docs/SKILL_V1_VS_V2_PHASES_1_2_3.md` — v1→v2 comparison and porting plan for the first 3 phases
- `../../docs/SKILL_STATUS_2026-04-29.md` — current status snapshot

---

## Milestone status

- [x] **M1**: scaffolding — folder structure, this `SKILL.md`, ported `sortable_columns.json` + v1 `system_prompt.txt` reference, golden queries seed
- [x] **M2**: `prompts/topic_matcher.md` — Phase 2a topic-matcher prompt; `SKILL.md` Phase 2a invocation flow wired in
- [ ] **Next (M3)**: TWO prompts —
  - `prompts/keyword_research.md` (Phase 2b — conditional, ES-validated keyword set; **the only filter signal for off-taxonomy queries**)
  - `prompts/filter_builder.md` (Phase 2c — verdicts + keyword set + schema → partial FilterSet)
  - **Stub already in place** at `prompts/filter_builder.md` with the **HARD CONSTRAINTS** section pre-locked: no `topics:` field, topic→keyword_groups translation, v1 schema rules (C1–C10). M3 implementation flesh out the prompt body but **must not relax the constraints**.
- [ ] M4: validation loop logic (translate FilterSet to SQL, run db_count/db_sample, retry rules)
- [ ] M5: `prompts/column_widget_builder.md` — Phase 4 columns/widgets
- [ ] M6: end-to-end output (display config; suggest `tl reports create`)

---

## Stub behavior (until M3 lands)

When invoked today, the skill should:
1. Acknowledge the request
2. Run **Phase 1** (TODO — string-heuristic stub: detect SPONSORSHIPS via expanded keyword set; otherwise default to CHANNELS)
3. Run **Phase 2a** (Topic Matcher — implemented in M2):
   - Fetch live topics via `pg_query.py` (interim) or `tl db pg` (target)
   - Apply `prompts/topic_matcher.md` to produce verdicts
4. Display the verdicts to the user and explain: `"Phase 2b (Filter Builder) not yet implemented (M3). The matcher's verdicts above will drive filter selection once M3 lands."`
5. Exit cleanly

This lets the matcher be hand-tested on the goldens (and any new query) end-to-end before any other phase ships.
