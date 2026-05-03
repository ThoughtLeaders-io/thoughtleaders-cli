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
    │   prototype: print JSON; saving handled outside the skill per current policy
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

## Phase 3 — Validation Loop (how to invoke)

Phase 3 is the **only mandatory non-LLM-dominated phase**. It takes the partial FilterSet from Phase 2c, translates it to SQL, runs `tl db pg`, applies threshold rules, runs the [`sample_judge.md`](prompts/sample_judge.md) sub-step on samples, and decides `proceed | retry | alternatives | fail`.

### Step 3.1 — Translate FilterSet to SQL

Determined by `report_type`. The skill builds two queries: `db_count` (returns scalar) and `db_sample` (returns up to 10 rows).

#### Type 3 (CHANNELS) — most common path

Predicate template (assembled from `filterset` fields):
```sql
is_active = TRUE
  AND (<keyword_groups predicate>)        -- if non-empty
  AND <reach_from / reach_to>             -- if set
  AND language IN (<languages>)           -- if set
  AND <demographic predicates>            -- if set
  AND <date predicates from days_ago>     -- if set
```

`<keyword_groups predicate>`:
- For each non-excluded `keyword_groups` entry → `(description ILIKE '%<text>%' OR channel_name ILIKE '%<text>%')`
- Combine entries with `keyword_operator` (AND or OR)
- For each `exclude: true` entry → wrap in `AND NOT (description ILIKE ... OR channel_name ILIKE ...)` — independent of `keyword_operator`

Final SQL shape:
```sql
-- db_count
SELECT COUNT(*) FROM thoughtleaders_channel WHERE <predicate> LIMIT 1 OFFSET 0
-- db_sample
SELECT id, channel_name, reach FROM thoughtleaders_channel WHERE <predicate> ORDER BY reach DESC NULLS LAST LIMIT 10 OFFSET 0
```

#### Type 1 (CONTENT) — videos/uploads

Production runs against ES; for the prototype, fall back to a channel-level proxy with the same predicate against `thoughtleaders_channel` and emit a `_validation.note: "type 1 prototype validation uses channel-level proxy; production will use ES word-boundary scoring"` so Phase 5 can surface it.

#### Type 2 (BRANDS)

Same prototype proxy as Type 1: query `thoughtleaders_channel` with the keyword predicate. The brand-level filtering happens in production via ES; for prototype validation, channel-level smoke check is sufficient.

#### Type 8 (SPONSORSHIPS) — completely different schema

```sql
SELECT COUNT(*) FROM thoughtleaders_adlink al
  LEFT JOIN thoughtleaders_channel c ON al.channel_id = c.id
  LEFT JOIN thoughtleaders_brand b ON al.brand_id = b.id
WHERE
  al.publish_status IN (<filters_json.publish_status>)   -- mandatory; default active set
  AND al.created_at BETWEEN <start_date> AND <end_date>  -- if dates given
  AND b.id IN (<resolved brand_ids>)                     -- if brand_names set
  AND c.id IN (<resolved channel_ids>)                   -- if channel_names set
LIMIT 1 OFFSET 0
```

`brand_names` and `channel_names` are *strings* in v1's FilterSet — Phase 3 resolves them to IDs via a preliminary `tl db pg` query against `thoughtleaders_brand` / `thoughtleaders_channel` before composing the main predicate.

### Step 3.2 — Run `db_count` (with timeout retry)

```
tl db pg --json "<count_sql>"
```

If the query times out:
1. Drop the `channel_name ILIKE` half of each keyword predicate (description-only)
2. Retry once
3. If still times out: split the predicate by `AND` and run each as a separate baseline query, then estimate intersection arithmetically
4. If that fails too: emit `decision: "fail"` with diagnostic in `_validation.errors`

This is the **serial-with-retry orchestration rule** from M3 findings. `tl db pg` timeouts surfaced repeatedly during M3 rehearsals; the skill must defend against them.

### Step 3.3 — Apply threshold rules

```
db_count    →  classification    →  next step
─────────────────────────────────────────────
0           →  empty             →  Step 3.5 (retry — broaden)
1–4         →  very_narrow       →  Step 3.4 (sample inspection); proceed with warning
5–50        →  narrow            →  Step 3.4 (sample inspection); proceed with note
51–10000    →  normal            →  Step 3.4 (sample inspection)
10001–50000 →  broad             →  Step 3.4 (sample inspection); proceed with narrow-suggest
> 50000     →  too_broad         →  Step 3.5 (retry — narrow)
```

Calibration source: M3 Part 3 rehearsal where every golden's actual count fell into one of these buckets and the right decision was clear.

### Step 3.4 — Run `db_sample`, then `sample_judge`

```
tl db pg --json "<sample_sql>"
```

Pipe the sample (up to 10 rows) into the sample_judge prompt:
1. Load [`prompts/sample_judge.md`](prompts/sample_judge.md)
2. Inject `USER_QUERY`, `DB_SAMPLE`, and `VALIDATION_CONCERNS` (inherited from Phase 2c's `_routing_metadata.validation_concerns`)
3. Parse JSON output: `{judgment, reasoning, noise_signals, matching_signals}`

Decision based on judgment:
- `matches_intent` → `decision: "proceed"`, route to Phase 4
- `looks_wrong` → `decision: "alternatives"`, skip Phase 4, route to Phase 5 with structured user prompt
- `uncertain` → `decision: "alternatives"` with the user prompt favoring "Refine" — surface ambiguity rather than silently shipping

### Step 3.5 — Retry orchestration (cap: 3)

When `db_count` is `empty` or `too_broad`, emit structured feedback to whichever upstream phase produced the failing FilterSet:

| Source | Retry target | Feedback shape |
|---|---|---|
| matched topics (Phase 2c) | Phase 2c | `{issue, suggestion, previous_filterset}`; suggest supplement with more keywords from `topic.keywords[]` (beyond head) or relax operator AND→OR |
| KEYWORD_SET (Phase 2b) | Phase 2b | `{issue, suggestion}`; suggest broader candidates or different sub_segment terms |

Cap at **3 retries total** across both phases. After 3, emit `decision: "fail"` with diagnostic — better to honestly fail than infinite-loop.

**What does NOT trigger retry**:
- `sample_judge` returning `looks_wrong` — this is a substantive failure (data sparsity or noise), not a shape failure. Retrying would just produce more noise. Go straight to `alternatives`.
- `db_count` in the `narrow` (1–4) bucket — proceed with warning; retry would lose the small but real signal.

### Step 3.6 — Compose decision output

```json
{
  "decision": "proceed" | "retry" | "alternatives" | "fail",
  "validation": {
    "db_count": <int>,
    "db_sample": [<channels>],
    "count_classification": "empty" | "very_narrow" | "narrow" | "normal" | "broad" | "too_broad",
    "sample_judgment": "matches_intent" | "looks_wrong" | "uncertain" | null,
    "sample_judgment_reasoning": "<from sample_judge>",
    "validation_concerns": [/* accumulated from Phase 2b + Phase 3 */],
    "errors": [/* if fail */]
  },
  "feedback_for_retry": { /* present iff decision == "retry" */ },
  "alternatives_for_user": { /* present iff decision == "alternatives" */ }
}
```

Phase 4 reads `decision == "proceed"` to know it's safe to run. Phase 5 reads `alternatives_for_user` to construct the user prompt.

### Phase 3 edge cases

| Edge case | Behavior |
|---|---|
| Multi-step query (G10) | Phase 3 runs `source_query` first, extracts `channel_ids`, then runs main report's count/sample with `apply_as` injection. Two `tl db pg` queries instead of one. |
| Cross-references (G05) | Resolve brand names → brand IDs via `tl db pg` against `thoughtleaders_brand` first; then resolve cross-reference channel set; then main predicate. Adds 1–2 preliminary queries. |
| Brand/channel name lookups | All string-name resolutions happen in Phase 3 (not Phase 2c). v1's schema treats them as strings; v1's backend resolved to IDs. v2 must replicate that resolution explicitly. |
| Inherited `validation_concerns` | Pass through to `sample_judge`'s `VALIDATION_CONCERNS` input verbatim. The prompt biases toward `looks_wrong` when these are present and confirmed in samples. |
| Type 8 with no date filter | Reject upfront (`decision: "fail"`) — sponsorship queries without dates are unbounded and meaningless. v1's `multi_step_query` rule for source_query (line 116) requires explicit dates; same applies here. |

### Phase 3 contract (downstream consumers)

- **Phase 4 (Column/Widget Builder)** runs ONLY when `decision == "proceed"`. Reads `_routing_metadata.intent_signal` and the validated FilterSet.
- **Phase 5 (Display)** runs in three modes:
  - `proceed` path — assemble the full config from Phases 2c + 4
  - `alternatives` path — present the structured user prompt (save anyway / refine / cancel)
  - `fail` path — present the diagnostic to the user with no save option
- **`validation_concerns`** propagates into Phase 5's user-facing message — the user should see noise warnings, narrow-result notes, and sample-judgment reasoning.

---

## Phase 4 — Column/Widget Builder (how to invoke)

Runs ONLY when Phase 3's `decision == "proceed"`. Skipped on `alternatives` and `fail`.

### Step 4.1 — Load inputs

- `REPORT_TYPE` (from Phase 1)
- `FILTERSET` (validated, from Phase 2c via Phase 3)
- `ROUTING_METADATA` (from Phase 2c — including `intent_signal` and `validation_concerns`)
- `SORTABLE_COLUMNS`: read [`data/sortable_columns.json`](data/sortable_columns.json)

### Step 4.2 — Apply [`prompts/column_widget_builder.md`](prompts/column_widget_builder.md)

Single LLM call. Produces `{ columns, widgets, histogram_bucket_size, refinement_suggestions, _phase4_metadata }`.

### Step 4.3 — Validate against W1–W9

The prompt's 12-point self-check fires before emit. Orchestration does a sanity pass on the JSON shape (no missing required fields per `report_type`'s default column list) but trusts the prompt.

### Phase 4 contract

- Phase 5 reads `columns`, `widgets`, `refinement_suggestions`, `histogram_bucket_size` to assemble the saved-report config
- Phase 5 reads `_phase4_metadata.intent_consumed` and `_phase4_metadata.concerns_surfaced` to construct the user-facing message ("here's why these columns" + "noise warnings")

---

## Phase 5 — Display / Save (how to invoke)

Phase 5 is **the only phase with branching modes**, driven by Phase 3's `decision`. No new LLM call; templated user messaging plus orchestration.

### Mode A — `decision: "proceed"` (the happy path)

Phase 5 assembles the complete report config in v1's authoritative shape:

```json
{
  "action": "create_report",
  "report_title": "<derived from query and topics>",
  "report_description": "<1–3 sentences summarizing intent + filters>",
  "summary": "<one sentence>",
  "report_type": <int>,
  "filterset": { /* from Phase 2c, post-Phase 3 validation */ },
  "filters_json": { /* from Phase 2c */ },
  "cross_references": [ /* from Phase 2c, top-level */ ],
  "columns": { /* from Phase 4 */ },
  "widgets": [ /* from Phase 4 */ ],
  "histogram_bucket_size": "...",
  "refinement_suggestions": [ /* from Phase 4 */ ]
}
```

Plus internal-only `_validation` metadata (stripped before any future POST):

```json
{
  "_validation": {
    "db_count": <int>,
    "db_sample_size": <int>,
    "count_classification": "narrow" | "normal" | "broad" | ...,
    "sample_judgment": "matches_intent",
    "phase_2a": "<verdict summary>",
    "phase_2b": "skipped" | "<keyword count>",
    "phase_2c_retries": 0,
    "phase_3_retries": 0,
    "validation_concerns": [...]
  }
}
```

User-facing message template:

> Built a report config for **"<original NL_QUERY>"** — matches **<db_count>** <entity>.
>
> [If `_phase4_metadata.intent_consumed` non-null:]
> Optimized for **<intent>**: emphasized columns like <list 3 outreach-relevant column names>.
>
> [If `validation_concerns` non-empty:]
> ⚠️ **Worth knowing**: <each concern stated plainly>
>
> [If `count_classification == "narrow"`:]
> 📌 The result is narrow (<count> matches). Consider broadening if you expected more.
>
> If this looks right, the config above is ready to save.
>
> **Save behavior is runtime-dependent** (the skill is TL-internal — no external-customer flow exists):
> - **If `TL_DATABASE_URI` is set with `santaclaw_ro` (or equivalent) creds** → the orchestration invokes a `create_report.py`-style direct INSERT via the `campaign_maker` RLS policy. Report is created atomically in one transaction. This is the path SantaClaw and the legacy v1 create-report skill use.
> - **Otherwise** → save is unavailable from the skill. The TL-superuser web-UI AI Report Builder is the alternative for human admins, but it's a separate codepath the skill doesn't drive.
>
> The CLI's `tl reports create` server-side endpoint is slated for removal per the current API-cleanup policy; not a recommended save target. Otherwise tell me what to change — see refinement suggestions below.

### Mode B — `decision: "alternatives"` (looks_wrong or uncertain)

Phase 4 is skipped. Phase 5 receives the alternatives payload from Phase 3 and presents structured choices:

> ⚠️ I built a filter for **"<original NL_QUERY>"** but the validation surfaces a problem:
>
> - <Phase 3.4 sample_judge.reasoning, citing 2–3 specific channel_names from db_sample>
> - [If validation_concerns non-empty:] This confirms the noise warning from Phase 2b (<concern>).
> - <db_count and what fraction looks plausible>
>
> **Three options:**
> 1. **Save anyway** — useful if you want to inspect the long tail manually
> 2. **Refine** — give me a different angle (e.g., "<refine-suggestion-1>", "<refine-suggestion-2>")
> 3. **Cancel** — TL data may not have meaningful coverage for this niche

Refine suggestions are *generated* from `_routing_metadata.weak_matched_topic_ids` (if any) and the failing FilterSet's structure. Templated, not LLM.

If the user picks "Save anyway", Phase 4 runs *now* (deferred from before) with `validation_concerns` heavily surfaced in `_phase4_metadata`. Phase 5 then enters Mode A but with a header noise warning.

### Mode C — `decision: "fail"` (3 retries exhausted, or hard error)

Phase 4 skipped. Phase 5 shows the diagnostic and offers no save option:

> ❌ I couldn't build a sensible report for **"<original NL_QUERY>"**.
>
> Diagnosis:
> - <retry count> retries; each returned <empty | too_broad | timeout> (<details>)
> - <validation_concerns surfaced>
>
> What you could try:
> - <suggestion based on failure mode>
> - <fallback approach (e.g., "describe the channels you have in mind directly")>

### Mode D — Vague query (Phase 1 asks first)

This isn't really a Phase 5 mode — it fires before Phase 1 even completes. The skill's flow rules in this `SKILL.md` document recognize a vague query and emit a `follow_up` action without invoking later phases. See G06 in the rehearsal artifacts.

### Save behavior

**Prototype save model** (TL-internal; no external-customer save flow exists):
- The skill always *displays* the JSON config in Mode A — config is the canonical artifact regardless of save path.
- **Path 3 (direct DB INSERT via `campaign_maker`)** is the surviving write path:
  - When `TL_DATABASE_URI` is set in the runtime (e.g. SantaClaw, TL team member's local Claude Code session with shared `santaclaw_ro` creds) → the skill invokes a `create_report.py`-style transaction: filterset INSERT + M2M rows for brands/channels + campaign INSERT, all atomic, all enforced by RLS.
  - When `TL_DATABASE_URI` is absent → save is unavailable from the skill. Manual creation via the platform UI's AI Report Builder feature (superuser-only) is the only TL-internal alternative, and it's a separate Django codepath the skill doesn't drive.
- **Path 1 (`tl reports create` CLI → server-side orchestration)** is being removed per the API-cleanup policy. Not a save target the skill should suggest.
- **Path 2 (web UI's AI Report Builder)** is superuser-gated and uses Django ORM (not `campaign_maker`); separate concern, not part of skill scope.

### Phase 5 contract

- Mode A → user sees full config; save behavior runtime-dependent (Path 3 `campaign_maker` direct INSERT if `TL_DATABASE_URI` set; otherwise display-only — superuser UI is a manual alternative for humans)
- Mode B → user picks save anyway / refine / cancel; refine routes back to Phase 1 with feedback; save anyway runs Phase 4 + emits Mode A output with warnings
- Mode C → user sees diagnostic; no commit action available
- Mode D → user gets follow-up question; pipeline halts pending answer

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
- [x] **M3 part 1**: `prompts/keyword_research.md` (Phase 2b — conditional, ES-validated keyword set; the only filter signal for off-taxonomy queries) + rehearsal artifact ([`keyword_research_rehearsal.md`](examples/keyword_research_rehearsal.md)) — **22/22 defensible across 4 off-taxonomy paths**
- [x] **M3 part 4**: G11–G13 added to `golden_queries.md`; rehearsal extended
- [x] **M3 part 2**: `prompts/filter_builder.md` body (529 lines) — 13 reasoning dimensions D1–D11 + D-S/D-M/D-X, 5 worked examples (G01/G03/G04/G09/G10), 15-point self-check tied to HARD CONSTRAINTS C1–C10
- [x] **M3 part 3**: [`examples/filter_builder_rehearsal.md`](examples/filter_builder_rehearsal.md) — all 13 goldens; **13/13 self-check defensible**; 12/13 produce non-zero Phase 3 results (G11 sparse in TL data — surfaced as expected)
- **M3 ✓ DONE**
- [x] **M4 part 1**: `prompts/sample_judge.md` (Phase 3 sub-step) + 4-golden rehearsal — G11 regression test passing
- [x] **M4 part 2**: SKILL.md "Phase 3 — Validation Loop (how to invoke)" section
- [x] **M4 part 3**: full Phase 3 rehearsal across all 13 goldens — **13/13 reach a clean decision**; G11 + G02 both routed to `alternatives`; threshold rules calibrated against live db_counts
- **M4 ✓ DONE**
- [x] **M5**: `prompts/column_widget_builder.md` (Phase 4) — 12-point self-check tied to W1–W9 hard rules; `intent_signal` and `validation_concerns` threading; type-3/8 column-set bifurcation. Rehearsal: [`column_widget_rehearsal.md`](examples/column_widget_rehearsal.md) — **5/5 defensible** across distinct paths
- [x] **M6**: Phase 5 (Display/Save) flow rules in SKILL.md — 4 modes (proceed / alternatives / fail / vague). Full e2e rehearsal: [`e2e_rehearsal.md`](examples/e2e_rehearsal.md) — **13/13 goldens reach a user-facing output**; G02 + G11 routed to Mode B (silent-ship blocked); G06 routed to Mode D (Phase 1 asks first)
- **M5 + M6 ✓ DONE — prototype skill is functionally complete end-to-end**
- [skip] M7: Mixpanel corpus eval — deferred (requires Mixpanel API access)
- [x] **M8 Part 1**: `prompts/judge.md` + [`examples/judge_calibration.md`](examples/judge_calibration.md) — assertion-style scorer; 12-class failure taxonomy; calibrated G01/G11/G06; synthetic-fail correctly identifies primary phase + suggested direction. Creator + Coder roles documented as methodology only.
- [x] **M9 methodology**: [`examples/m9_shadow_mode_methodology.md`](examples/m9_shadow_mode_methodology.md) — 6 comparison dimensions (report_type / FilterSet fields / db_count / db_sample / column choice / Mode), aggregated metric targets, expected-divergence catalog (where v2 *legitimately* differs from v1), promote-or-iterate decision criteria. **Actual run is operational, deferred to deployment phase.**
- ⏳ **M9 run, M10, M11**: deployment / operational milestones. Not skill construction. The skill is functionally complete after M8 Part 1.
- [ ] M4: validation loop logic (translate FilterSet to SQL, run db_count/db_sample, retry rules)
- [ ] M5: `prompts/column_widget_builder.md` — Phase 4 columns/widgets
- [ ] M6: end-to-end output (display config; save action TBD pending new policy-compliant save mechanism)

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
