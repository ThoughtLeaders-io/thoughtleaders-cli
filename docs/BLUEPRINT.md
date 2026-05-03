# v2 AI Report Builder — Blueprint

**Single-page end-to-end reference.** When you need the narrative, see [SKILL_ARCHITECTURE.md](SKILL_ARCHITECTURE.md). When you need diagrams, see [SKILL_VISUAL_ARCHITECTURE.md](SKILL_VISUAL_ARCHITECTURE.md). When you need today's state, see [SKILL_STATUS_2026-04-29.md](SKILL_STATUS_2026-04-29.md). This doc is the **blueprint** — contracts, data shapes, status, decisions — in tabular form.

**Last updated:** 2026-04-29 (after M2 ship)

---

## 1. The system in one sentence

A Claude skill living in `tl-cli/skills/tl-report-build/` that takes a natural-language report request, runs a 5-phase orchestration locally in the user's Claude session, and produces a complete TL saved-report config — using `tl db pg` raw SQL as its only data plane.

---

## 2. The pipeline as contracts

Each phase has explicit inputs (`I`), outputs (`O`), the deliverable file, and current status. **Contracts between phases are the API** — downstream phases trust the shapes upstream phases emit.

| Phase | Name | I → O | Deliverable | Status |
|---|---|---|---|---|
| **1** | Report Type Selection | `NL_QUERY` → `ReportType` enum | (in `SKILL.md` flow rules) | M3-bundled |
| **2a** | Topic Matcher | `NL_QUERY` + `TOPICS[]` (live) → `verdicts[]` + `summary` | `prompts/topic_matcher.md` | ✓ M2 |
| **2b** | Keyword Research (conditional) | `NL_QUERY` + matched topics' keywords → validated `KeywordSet` | `prompts/keyword_research.md` | M3 part 1 |
| **2c** | Filter Builder, Pass A | `NL_QUERY` + `verdicts` + `KeywordSet` + schema → `partial_FilterSet` | `prompts/filter_builder.md` | M3 part 2 |
| **3** | Validation Loop | `partial_FilterSet` → `db_count` + `db_sample` → accept/retry | `SKILL.md` flow rules + retry instructions | M4 |
| **4** | Column/Widget Builder, Pass B | validated `FilterSet` + `ReportType` → `complete_report_config` | `prompts/column_widget_builder.md` | M5 |
| **5** | Display / Save | `complete_report_config` → JSON to user (prototype); POST later | `SKILL.md` flow rules | M6 |

**Phase 2b — when it runs (strict rule):**

```
RUN 2b iff:    report_type ∈ {1, 2, 3}  AND  summary.strong_matches.length == 0
SKIP 2b iff:   report_type == 8 (SPONSORSHIPS)
                OR
                summary.strong_matches.length >= 1   (use topic's curated keywords directly)
```

In plain English: **Phase 2b only runs when Phase 2a's match is bad** — i.e., no strong topic verdict exists. If 2a returned ≥1 `strong` match, that topic's `keywords[]` array is already ES-validated (that's how topics were seeded — `pipeline_analysis_v1` methodology), so we trust it directly without re-generating.

| 2a result | report_type | 2b runs? | Why |
|---|---|---|---|
| ≥1 strong match | 1/2/3 | ✗ skip | trust topic's curated keywords |
| no strong (weak-only or all-none) | 1/2/3 | ✓ run | only filter signal Phase 2c will get |
| any | 8 (SPONSORSHIPS) | ✗ skip | no ES content matching for deals |

The weak-only case (no strong, but some weak) falls through to "run 2b" because weak means "topic is tangentially related, not primary intent" — we still need fresh keywords for the primary intent. The weak verdicts can still be surfaced to the user in Phase 5 as "did you also mean...?"

**What about query-specific terms within a strong-match query?** (e.g., G02 "AI **tutorial** channels" — Topic 96 strong, but "tutorial" is specific.) Phase 2c (Filter Builder) handles this — it has the NL query and can emit additional content-field-targeted keywords inline alongside the topic filter. We don't run 2b just to add supplemental terms; that would be redundant with what 2c does anyway.

---

## 3. Data shapes (the contracts in JSON)

### 3.1 `NL_QUERY` — input
A single string. The user's natural-language request.
```
"Build me a report of gaming channels with 100K+ subscribers in English"
```

### 3.2 `ReportType` enum (Phase 1 output)
```
CONTENT       = 1   // videos / uploads
BRANDS        = 2   // brand intelligence reports
CHANNELS      = 3   // YouTube channels (default)
SPONSORSHIPS  = 8   // deals / matches / proposals (skips keyword research)
```

### 3.3 `Topic` — fetched live from `thoughtleaders_topics`
```json
{
  "id": 96,
  "name": "Artificial Intelligence",
  "description": "...",
  "keywords": ["artificial intelligence", "AI tools", ...]
}
```
Schema (from `information_schema`): `id INT NOT NULL`, `name VARCHAR NOT NULL`, `description VARCHAR`, `keywords JSONB`, `source VARCHAR`, `created_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ`.

### 3.4 `Verdict` (Phase 2a output, one per topic)
```json
{
  "topic_id": 98,
  "topic_name": "PC Games",
  "verdict": "strong" | "weak" | "none",
  "reasoning": "User said '<phrase>'; matches topic keyword '<kw>'.",
  "matching_keywords": ["gaming"]
}
```

### 3.5 `MatcherOutput` (Phase 2a → Phase 2b)
```json
{
  "query": "<echo of NL_QUERY>",
  "verdicts": [Verdict, ...],   // one entry per Topic in TOPICS
  "summary": {
    "strong_matches": [98],
    "weak_matches": [],
    "no_match": false           // true iff no strong AND no weak
  }
}
```

### 3.6 `KeywordSet` (Phase 2b → Phase 2c)

Output of the conditional Keyword Research phase. Skipped for SPONSORSHIPS(8); empty when 2a covers everything (rare).

```json
{
  "core_head":   ["crypto", "bitcoin"],
  "sub_segment": ["DeFi", "Web3", "ethereum"],
  "long_tail":   ["how to invest in crypto 2026", "best crypto exchange"],
  "content_fields": ["title", "summary", "channel_description"],
  "recommended_operator": "OR",                            // "AND" if user said "and"/"both"
  "validated": [
    { "keyword": "crypto",   "db_count": 14523, "ok": true  },
    { "keyword": "DeFi",     "db_count": 892,   "ok": true  },
    { "keyword": "Web3",     "db_count": 1340,  "ok": true  },
    { "keyword": "rugpull",  "db_count": 0,     "ok": false, "pruned_reason": "zero db_count" }
  ]
}
```
Each candidate is validated by a `tl db pg COUNT(*)` query against the relevant fact table (channels for type 3, articles for type 1, etc.) before inclusion. Zero-count keywords are pruned upfront (catches v1's silent-zero surprise).

### 3.7 `partial_FilterSet` (Phase 2c → Phase 3)

A subset of the platform's `dashboard.models.FilterSet` schema — **filters only**, no columns/widgets.

**⚠️ Critical**: v1's FilterSet has **NO `topics` field**. Topic IDs are v2 routing metadata only — they get translated into head keywords from each topic's `keywords[]` array and emitted as `keyword_groups`. Confirmed 2026-04-29 against `_v1_system_prompt_REFERENCE.txt`.

```json
{
  "report_type": 3,
  "keyword_groups": [
    { "text": "gaming", "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false }
  ],
  "keyword_operator": "OR",
  "channel_formats": [4],
  "reach_from": 100000,
  "languages": ["en"],
  "days_ago": 730,
  "sort": "-reach",
  "brand_names": [],
  "exclude_brand_names": [],
  "channel_names": [],
  "exclude_channel_names": []
}
```

**Schema notes** (verified against `_v1_system_prompt_REFERENCE.txt` and `create_report.py`):
- **No `topics` field** — only `keyword_groups` derived from topic keyword arrays
- **`keyword_groups`** — list of `{text, content_fields, exclude}`. Each distinct term is its OWN entry; never combine with OR in `text`
- **`keyword_operator`** — `"AND"` or `"OR"` (default OR), combines multiple `keyword_groups` entries
- **`reach_from`/`reach_to`** — subscriber count (NOT `min_subscribers`)
- **`languages`** — list of ISO codes (NOT singular `language`)
- **`days_ago`** — REQUIRED when `keyword_groups` present (default 730; avoids ES timeouts)
- **`sort`** — REQUIRED, lives inside `filterset` (not top-level); default `"-reach"` for type 3
- **`brand_names`/`channel_names`** — string lists; backend resolves to IDs (NOT numeric ID arrays)
- **Cross-references** (`exclude_proposed_to_brand`, etc.) live at the **TOP LEVEL** of the response, NOT inside `filterset`

**Authoritative example**: see [`E2E_WALKTHROUGH_G03.md`](E2E_WALKTHROUGH_G03.md) Appendix A for a complete report config.

### 3.8 Validation result (Phase 3)
```json
{
  "db_count": 247,
  "db_sample": [{"id": 1234, "name": "..."}],
  "verdict": "ok" | "empty" | "too_broad",
  "feedback_for_filter_builder": "..."   // present only if retry
}
```

### 3.9 `complete_report_config` (Phase 4 → Phase 5)
```json
{
  "report_title": "Gaming Channels 100K+ English",
  "report_type": 3,
  "filterset": { /* partial_FilterSet from Phase 2b, validated in Phase 3 */ },
  "columns": ["name", "subscribers", "language", "..."],
  "widgets": [{"type": "bar_chart", "field": "subscribers", "..."}],
  "user_email": "<from tl whoami>"
}
```

---

## 4. The data plane (one table)

**Status as of 2026-04-29**: local CLI upgraded to v0.6.2; **`tl db pg` works end-to-end on the user's machine**. The interim `pg_query.py` path is now the *fallback*, not the default.

| Need | Primary (tl-cli ≥ v0.6.2) | Fallback (no sandbox access) |
|---|---|---|
| Live topics fetch | `tl db pg --json "SELECT id, name, description, keywords FROM thoughtleaders_topics ORDER BY id LIMIT 100 OFFSET 0"` | `python ~/Desktop/ThoughtLeader/thoughtleaders-skills/tl-data/scripts/pg_query.py "..." --format json` |
| Schema discovery | `tl db pg --json "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='channels' LIMIT 200 OFFSET 0"` | `python pg_query.py "..." --format json` |
| `db_count` | `tl db pg --json "SELECT COUNT(*) FROM ... WHERE ... LIMIT 1 OFFSET 0"` | `python pg_query.py "..." --format json` |
| `db_sample` | `tl db pg --json "SELECT ... LIMIT 10 OFFSET 0"` | `python pg_query.py "..." --format json` |
| Auth/user | `tl whoami` (works in v0.4.0+) | unchanged |
| Save (later) | **`tl reports create` removed by policy** — save mechanism TBD; prototype displays JSON only | TBD |

**⚠️ Response shape — `tl db pg` vs `pg_query.py`** (skill orchestration must normalize):
- `tl db pg --json` → `{"results": [...]}` envelope; orchestration extracts `.results`
- `pg_query.py --format json` → bare `[...]` array
- Phase prompts (e.g. `topic_matcher.md`) expect the bare array; SKILL.md flow normalizes before invoking the prompt

**`tl db pg` constraints** (also self-enforced when using the fallback):
- Mandatory `LIMIT n OFFSET m` on every query, max 500 rows
- Read-only SELECT — no DDL/DML, no multi-statement
- No top-level `UNION`/`INTERSECT`/`EXCEPT` (wrap in CTE)
- Forbidden functions: `random`, `pg_sleep`, `current_user`, `version`, `pg_read_file`, `lo_export`, `dblink`, `current_setting`, `set_config`

**`tl db pg` constraints** (also self-enforced on `pg_query.py`):
- Mandatory `LIMIT n OFFSET m` on every query, max 500 rows
- Read-only SELECT — no DDL/DML, no multi-statement
- No top-level `UNION`/`INTERSECT`/`EXCEPT` (wrap in CTE)
- Forbidden functions: `random`, `pg_sleep`, `current_user`, `version`, `pg_read_file`, `lo_export`, `dblink`, `current_setting`, `set_config`

---

## 5. CLI surface — IN vs OUT

The v2 skill uses **only these commands** (per the 2026-04-23 daily: higher-level commands "are layers that duplicate schema knowledge + joins on top of these primitives"):

| Status | Command | Purpose |
|---|---|---|
| ✅ IN | `tl ask "<NL>"` | Skill entry point |
| ✅ IN | `tl db pg --json "<SQL>"` | Postgres data plane |
| ✅ IN | `tl db es --json "<query>"` | Elasticsearch (super-user, coming) |
| ✅ IN | `tl db fb --json "<SQL>"` | Firebolt (super-user, coming) |
| ✅ IN | `tl whoami`, `tl balance` | Auth + credit awareness |
| ❌ OUT | `tl describe show <r>` | Replaced by `information_schema` queries |
| ❌ OUT | `tl channels`, `tl brands`, `tl sponsorships`, `tl uploads` | Replaced by raw SQL |
| ❌ REMOVED BY POLICY | `tl reports create` | Save action no longer available via CLI; Phase 5 displays JSON, save handled via platform UI / TBD mechanism |
| ⚠ STILL AVAILABLE | `tl reports run` | Reading existing saved reports unaffected |

(All "OUT" commands continue to exist in the CLI for human use; the skill just doesn't call them.)

---

## 6. Milestone map (M1 → M11)

| M | Title | Status | Key deliverable | Exit signal |
|---|---|---|---|---|
| **1** | Skill scaffolding | ✓ done | folder structure, `SKILL.md` stub, `sortable_columns.json`, `_v1_system_prompt_REFERENCE.txt`, `golden_queries.md` | skill loads when triggered |
| **2** | Topic Matcher prompt | ✓ done | `prompts/topic_matcher.md` + rehearsal artifact | 8/10 defensible verdicts on goldens (achieved 10/10) |
| **3** | Filter Builder + Keyword Research | ⏳ next; constraints pre-locked in stub | **two prompts**: `prompts/keyword_research.md` (Phase 2b — conditional, ES-validated keyword set) + `prompts/filter_builder.md` (Phase 2c — sliced from 999-line v1 prompt). `prompts/filter_builder.md` **stub already in place** with HARD CONSTRAINTS C1–C10 pre-locked (no `topics` field on output; v1 schema rules; type-8 special-casing; etc.) — M3 fleshes the prompt body without relaxing constraints. Phase 1 type-selection rules folded in. | golden queries produce schema-valid partial FilterSets, including off-taxonomy goldens (G09) via the keyword-only path |
| **4** | Validation loop | pending | retry logic in `SKILL.md`; `db_count`/`db_sample` SQL rules | pathological queries self-correct in ≤2 retries |
| **5** | Column/Widget Builder Pass B | pending | `prompts/column_widget_builder.md` | configs include sensible columns/widgets per report type |
| **6** | End-to-end output (display) | pending | full pipeline runs to a complete config JSON | golden queries produce a defensible config end-to-end |
| **7** | Mixpanel corpus eval | pending | ~100 real NL queries hand-rated | failure cases categorized |
| **8** | Refinement pipeline (Creator/Judge/Coder) | pending | offline eval branch | skill measurably improves across iterations |
| **9** | Shadow-mode calibration | pending | run vs v1 in parallel without showing v2 to users | v2 matches/beats v1 on agreed metrics |
| **10** | Promote (and optionally add CLI cmds) | pending | v2 becomes default; evaluate `tl preview` | v1 server pipeline retired |
| **11** | Sunset legacy | pending | v1 `create-report` skill deprecated | v1 code removed |

---

## 7. Decisions locked (date-stamped)

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-21 | Raw SQL execution path is the way (over per-entity API endpoints) | Daily call: API backend was hitting token-overuse / massive sequential-call problems |
| 2026-04-23 | Three minimal endpoints (PG/ES/FB), not one unified | Code-level joins are faster than server waiting on all three; higher-level commands are duplicative |
| 2026-04-23 | David's UVP thesis: "joins across data stores" is the unique value | The v2 skill is the user-facing manifestation of this |
| 2026-04-27 | Skill-first prototyping pivot | Build new flows as Claude skills end-to-end before any Python; AI Report Builder v2 is the first |
| 2026-04-28 | Topics table reseeded, 10 topics live (IDs 96–105, 182 keywords) | Pipeline-grounded methodology v2; source tag `pipeline_analysis_v1` |
| 2026-04-29 | Skill data plane is `tl db pg` raw SQL — zero new CLI subcommands required | `tl db pg` shipped to sandbox; `tl topics list` wrapper rejected as redundant |
| 2026-04-29 | `tl describe show` and entity commands (`tl channels` etc.) are EXCLUDED from the v2 skill surface | They're "layers that duplicate schema knowledge"; skill goes straight to PG |
| 2026-04-29 | Topics fetched live every invocation; no bundled snapshot | Topics table is actively migrating (fresh data 2026-04-28); snapshot would drift |
| 2026-04-29 | Single LLM call per phase (no v1-style 3-call cascade) | Subprocess hops + multiple LLM calls were artifacts of v1's server-side architecture |
| 2026-04-29 | Validation is `db_count` + `db_sample` SQL, NOT v1's Critic/Judge/Revise LLM loop | DB ground-truth beats LLM-only post-hoc reasoning |
| 2026-04-29 | Keyword research: inline reasoning + `db_count` fallback (no subprocess to v1's `validate_keywords.py`/`prune_keywords.py`) | Subprocess hops add cost without earning their keep when LLM + DB ground-truth are available inline |
| 2026-04-29 | Schema discovery cadence: per-invocation, no cache layer | `information_schema` queries are cheap; cache invalidation > cache value |
| 2026-04-29 | `system_prompt.txt` (999 lines) is ported verbatim into `_v1_system_prompt_REFERENCE.txt`, sliced incrementally as M3+ lands | Avoid losing institutional FilterSet knowledge to a rewrite |
| 2026-04-29 | **Q5 resolved — DB only**: skill does NOT ship with read access to `evals/topics/seed_topics_v1.json` (richer per-topic context). Topics seen via `tl db pg` only. | Cleaner boundary; live data is the source of truth; eval files are for the v2 *team*, not the runtime skill |
| 2026-04-29 | **Q6 resolved — local CLI upgraded to v0.6.2**, `tl db pg` works end-to-end. Primary data plane swapped from `pg_query.py` → `tl db pg`. Fallback retained for users without sandbox access. | Local validation succeeded; no need to wait for broader rollout |
| 2026-04-29 | **Q7 resolved — abandon `nerya/opus-4-7-report-builder` branch in `thoughtleaders-skills`** (zero commits ahead of `main`; despite the name, no v2 report-builder work exists on it; stale checkpoint from earlier exploration). The v2 home is `tl-cli/skills/tl-report-build/` only. | Eliminate two-canonical-homes confusion |

---

## 8. Open questions (still TBD)

User answer 2026-04-29: Q5/Q6/Q7 resolved (see decisions log). Q1–Q4 deferred until M3+ when context becomes clearer.

| # | Question | Where it surfaces | Default if I had to ship today |
|---|---|---|---|
| Q1 | Skill state across phases — runtime memory? scratch table? session store? | M3+ when we need to pass state between Phase 2b retries | Session-runtime memory; no persistent store |
| Q2 | Multi-topic disambiguation — when matcher returns 2+ strong, ask user or auto-AND/OR? | M3 (Filter Builder reads `summary.strong_matches`) | Auto-OR with surfaced "did you also mean...?" hint |
| Q3 | Clarification vs assume for ambiguous queries | M3+ flow logic | Make best guess, surface assumptions, offer "want me to adjust?" |
| Q4 | IAB taxonomy — coarser navigation layer when topic matching is weak? | M3 (or later) | Out of scope for prototype |
| ~~Q5~~ | ~~Eval-file access — `seed_topics_v1.json`?~~ | — | **Resolved 2026-04-29: DB only** |
| ~~Q6~~ | ~~When to upgrade tl-cli to get `tl db pg`?~~ | — | **Resolved 2026-04-29: v0.6.2 installed, working** |
| ~~Q7~~ | ~~What to do with `nerya/opus-4-7-report-builder`?~~ | — | **Resolved 2026-04-29: abandon (stale, zero commits ahead of main)** |

---

## 9. File map (everything in one view)

### Skill itself (`tl-cli/skills/tl-report-build/`)
```
SKILL.md                                  ← orchestration + flow rules
data/
  sortable_columns.json                   ← M1: column metadata, ported from v1
prompts/
  _v1_system_prompt_REFERENCE.txt         ← M1: 999-line v1 reference, port-verbatim
  topic_matcher.md                        ← M2: Phase 2a prompt (strict JSON output)
  filter_builder.md                       ← M3 (next)
  column_widget_builder.md                ← M5
examples/
  golden_queries.md                       ← M1: 10 hand-curated NL queries
  topic_matcher_rehearsal.md              ← M2: 10/10 exit signal evidence
```

### Spec docs (`tl-cli/docs/`)
```
SKILL_ARCHITECTURE.md                     ← long-form architecture
SKILL_VISUAL_ARCHITECTURE.md              ← diagrams
SKILL_V1_VS_V2_PHASES_1_2_3.md            ← v1 audit + porting plan
SKILL_STATUS_2026-04-29.md                ← snapshot of current state
BLUEPRINT.md                              ← THIS FILE — single-page reference
```

### External (referenced, not in this repo)
```
~/Desktop/ThoughtLeader/thoughtleaders-skills/
  create-report/                          ← v1 reference, frozen until M11 sunset
  keyword-research/                       ← v1 4-stage pipeline; v2 may reuse stages 3+4
  tl-data/scripts/pg_query.py             ← interim DB transport until tl db pg ships broadly
~/Desktop/ThoughtLeader/thoughtleaders/
  evals/topics/                           ← seed_topics_v1.json, METHODOLOGY_v2.md, brand verdicts
  thoughtleaders/views/topics.py          ← REST endpoint exposing topics (not used by v2)
  dashboard/models.py:FilterSet           ← target object the skill produces
```

---

## 10. Reference docs cross-walk (when to read which)

| If you want to … | Read |
|---|---|
| Understand WHY the v2 architecture is what it is | [SKILL_ARCHITECTURE.md](SKILL_ARCHITECTURE.md) |
| See the architecture as pictures | [SKILL_VISUAL_ARCHITECTURE.md](SKILL_VISUAL_ARCHITECTURE.md) |
| Compare v2 plan to v1 reality, phase by phase | [SKILL_V1_VS_V2_PHASES_1_2_3.md](SKILL_V1_VS_V2_PHASES_1_2_3.md) |
| Know what's done / blocked / next as of today | [SKILL_STATUS_2026-04-29.md](SKILL_STATUS_2026-04-29.md) |
| **See the whole pipeline as contracts + state in one page** | **this file (`BLUEPRINT.md`)** |

---

## 11. End-to-end flow examples

Two grounding walkthroughs — one with topic match, one off-taxonomy (the path that depends on Phase 2b being explicit).

### 11a. Topic-match path — G01

**Input**: `tl ask "Build me a report of gaming channels with 100K+ subscribers in English"`

**Phase 1** → CHANNELS (3) (string heuristics)

**Phase 2a** runs `tl db pg "SELECT ... FROM thoughtleaders_topics ..."` then applies `topic_matcher.md` → `{summary: {strong_matches: [98], no_match: false}, verdicts: [...]}`

**Phase 2b — Keyword Research SKIPPED** because `strong_matches.length >= 1`. Topic 98's curated `keywords[]` array (`["gaming", "esports", ...]`) is the ES-validated set, no re-generation needed.

**Phase 2c — Filter Builder** translates Topic 98's curated keywords into `keyword_groups`, plus structured filters from the NL query:
```json
{
  "report_type": 3,
  "keyword_groups": [
    {"text": "gaming", "content_fields": ["title","summary","channel_description","channel_topic_description"], "exclude": false}
  ],
  "keyword_operator": "OR",
  "channel_formats": [4],
  "reach_from": 100000,
  "languages": ["en"],
  "days_ago": 730,
  "sort": "-reach"
}
```
Note: there is **no `topics: [98]` field** — Topic 98 is v2 routing metadata; the platform sees only the keyword_groups derived from its `keywords[]` array.

**Phase 3** validates via `tl db pg COUNT(*) ...` → 247 rows → ok → proceed.

**Phase 4** chooses columns/widgets via `column_widget_builder.md` → complete config.

**Phase 5** displays JSON. Save mechanism TBD — `tl reports create` was removed by policy; Phase 5's user message points to the platform UI's report-import surface (or whichever internal save mechanism is current).

### 11b. Off-taxonomy path — G09

**Input**: `tl ask "Find me crypto / Web3 channels"`

**Phase 1** → CHANNELS (3)

**Phase 2a** → `{summary: {strong_matches: [], weak_matches: [], no_match: true}, verdicts: [/* all none */]}`. Critically, the matcher does NOT force-fit Topic 97 (Personal Investing).

**Phase 2b — Keyword Research RUNS** because `strong_matches` is empty (and type ≠ 8). With no topics matched, this is the *only* filter signal Phase 2c will get. LLM proposes candidates `["crypto", "bitcoin", "ethereum", "DeFi", "Web3", "NFT", ...]`. Each gets a `tl db pg COUNT(*) FROM thoughtleaders_channel WHERE ... LIKE '%<kw>%' LIMIT 1 OFFSET 0` validation. Pruned set:
```json
{
  "core_head": ["crypto", "bitcoin"],
  "sub_segment": ["Web3", "DeFi", "ethereum"],
  "long_tail": ["how to buy bitcoin 2026", "best crypto wallet"],
  "content_fields": ["title", "summary", "channel_description"],
  "recommended_operator": "OR",
  "validated": [
    {"keyword": "crypto", "db_count": 14523, "ok": true},
    {"keyword": "Web3", "db_count": 1340, "ok": true},
    {"keyword": "rugpull", "db_count": 0, "ok": false, "pruned_reason": "zero db_count"}
  ]
}
```

**Phase 2c — Filter Builder** uses NO `topics:` filter; only the validated keyword set:
```json
{
  "report_type": 3,
  "keywords": [
    {"terms": ["crypto", "bitcoin", "Web3", "DeFi"], "content_fields": ["title", "summary", "channel_description"]}
  ],
  "keyword_operator": "OR"
}
```

**Phase 3** validates → if non-zero, proceed; if zero, retry Phase 2b with feedback "broaden keyword candidates."

**Phase 4–5** as before.

This is the path that Phase 2b makes explicit — without it, off-taxonomy queries would have no filter signal.

---

## 12. The goldens process — where they fit in the pipeline

The 10 hand-curated queries in [`golden_queries.md`](../skills/tl-report-build/examples/golden_queries.md) are not a one-off test set; they're the **operational test harness for the entire skill lifecycle**. They show up at five distinct points:

| Stage | When | What happens to the goldens |
|---|---|---|
| **A. Per-milestone rehearsal** | Every prompt-shipping milestone (M2 done, M3–M6 next) | Manual hand-walk: I (or whoever builds the prompt) follows the prompt against each golden, emits the contract output, hand-rates against the rubric. Artifact: `examples/<phase>_rehearsal.md`. **M2 example**: [`topic_matcher_rehearsal.md`](../skills/tl-report-build/examples/topic_matcher_rehearsal.md) — 10/10 defensible. |
| **B. Exit signals** | At every milestone | Each milestone's exit signal is phrased as "X/Y defensible on goldens" (e.g. M2: 8/10; M3: keyword sets non-empty + filter sets schema-valid for all 10; M6: end-to-end config makes sense for all 10) |
| **C. Mixpanel corpus eval** | M7 | Goldens get *augmented* with ~100 real user queries from `#ai-report-builder` Slack history + Mixpanel logs. Same skill, much wider input set. Outputs hand-rated; failures categorized (matcher / keyword / filter / column errors). |
| **D. Refinement pipeline input** | M8 | The Creator agent runs the full skill against `goldens ∪ Mixpanel_corpus`. Judge agent scores per-output against assertion-style rubrics. Coder agent proposes prompt edits. Loop iterates until held-out test set scores hold. |
| **E. Shadow-mode regression** | M9 + post-launch | Goldens become the stable test set the skill must keep passing as prompts evolve. v2 outputs compared against v1 outputs on goldens to measure agreement. |

### How the goldens grow per phase

Each milestone adds new rehearsal artifacts that exercise *that phase's* output for each golden:

| File (in `skills/tl-report-build/examples/`) | Created in | Format |
|---|---|---|
| `golden_queries.md` | M1 ✓ | The 10 queries themselves + per-query expected outputs (refined over time) |
| `topic_matcher_rehearsal.md` | M2 ✓ | Phase 2a verdict JSON + hand-rating per golden |
| `keyword_research_rehearsal.md` | M3 (new) | Phase 2b validated `KeywordSet` per golden (esp. critical for G09 off-taxonomy) |
| `filter_builder_rehearsal.md` | M3 (new) | Phase 2c partial FilterSet per golden |
| `validation_rehearsal.md` | M4 (new) | Phase 3 `db_count` + `db_sample` per golden |
| `column_widget_rehearsal.md` | M5 (new) | Phase 4 columns/widgets per golden |
| `e2e_rehearsal.md` | M6 (new) | Full pipeline output (complete report config) per golden |

Each new rehearsal artifact is committed alongside its prompt deliverable — that's the milestone exit signal. The blueprint expects 7 rehearsal artifacts by M6.

### Goldens vs Mixpanel corpus — what's the difference

- **Goldens** (~10–20 by M3): hand-curated for *coverage* — every interesting case (multi-topic, off-taxonomy, AND-vs-OR, vague-input, brand exclusion, sponsorship synonym) gets at least one golden. Stable; rarely change.
- **Mixpanel corpus** (~100 by M7): real user phrasings from production. Captures *distribution* — what people actually type. Grows over time; refreshed periodically.

By M8 the refinement pipeline runs both. By M9 calibration uses both. By post-launch goldens are the regression set; Mixpanel is the canary.

### The G09 case (why this matters)

`golden_queries.md` G09 ("Find me crypto / Web3 channels") is the **canonical exercise of the Phase 2b path**. Without Phase 2b made explicit:
- 2a returns `no_match: true`
- 2c (Filter Builder) gets no filter signal
- → output FilterSet is empty → `db_count = 0` always → infinite retry → fail

With Phase 2b explicit:
- 2a returns `no_match: true`
- 2b generates+validates a keyword set from scratch
- 2c uses the keyword set as the *only* filter → meaningful output
- `db_count` validates → success

Every milestone's rehearsal must cover G09 as the smoke test for the keyword-only path.

---

**That's the whole system.** Everything else (refinement pipeline, calibration, Python port) is post-prototype.

---

## 13. API tools — utilities Phase 2c emits and Phase 3 invokes

Some FilterSet fields aren't directly executable SQL — they require resolution or expansion via API-like operations. Phase 2c emits them as strings/declarations; Phase 3 (or the platform at execution time) calls these **API tools** to materialize them.

| Tool | Signature | Used by | Status |
|---|---|---|---|
| `resolve_brand_names` | `(names: list[str]) → dict[name, brand_id]` | Phase 3 cross-refs; type-8 brand_names | ✓ `tl db pg` against `thoughtleaders_brand` |
| `resolve_channel_names` | `(names: list[str]) → dict[name, channel_id]` | Phase 3 channel filters; similar_to_channels existence check | ✓ `tl db pg` against `thoughtleaders_channel` |
| `resolve_cross_references` | `(refs: list[CrossRef]) → {exclude_ids, include_ids}` | Phase 3 prelim; G05 pattern | ✓ `tl db pg` JOIN on `thoughtleaders_adlink` |
| `expand_similar_channels` | `(seeds: list[str]) → list[channel_id]` | Phase 3 prelim; "creators like X" pattern | ✗ requires embedding service; **prototype passes through, platform resolves at report-execution time**. v1 implementation: `thoughtleaders-skills/create-report/scripts/find_similar_channels.py` (342 lines) |
| `validate_keyword_via_es` | `(keyword, content_fields) → {count, sample}` | Phase 2b candidate validation, Phase 3 | ✗ requires `tl db es` (super-user only initially); prototype uses `tl db pg ILIKE` proxy with substring-noise warnings |

### Where each tool fires in the flow

```
Phase 2c (Filter Builder)
   │  emits FilterSet fields that REQUIRE these tools downstream:
   │    - brand_names, exclude_brand_names                    → resolve_brand_names later
   │    - channel_names, exclude_channel_names                → resolve_channel_names later
   │    - similar_to_channels                                 → expand_similar_channels later
   │    - cross_references[*].brand_names, channel_names      → resolve_cross_references later
   ▼
Phase 3 (Validation Loop) — orchestrates the actual calls
   │  Step 3.1.5 — Resolution (preliminary, before main predicate):
   │    1. Resolve brand/channel names to IDs (1–2 tl db pg queries; batched)
   │    2. Resolve cross_references → exclude_ids / include_ids
   │    3. For similar_to_channels: verify seed channels exist (existence check
   │       only — actual vector similarity defers to report-execution time
   │       since prototype lacks embedding access)
   │    4. Compose final SQL predicate with resolved IDs injected
   ▼
Phase 3 main count/sample, threshold, sample_judge, decision (unchanged)
```

### The Phase 3 prototype contract for `similar_to_channels`

Per filter_builder.md rule D10: when the skill emits `similar_to_channels: ["MrBeast"]`, it **also skips `keyword_groups`** because vector similarity captures topic relevance.

But that means Phase 3's normal pipeline (translate keyword_groups to ILIKE → count → sample → judge) has nothing to validate against. Three options:

1. **Existence check only** (current prototype default) — verify named seeds exist in `thoughtleaders_channel`; `db_count` is "the platform will resolve at runtime"; `sample_judge` skipped. Decision: `proceed` automatically. Risk: silent ship if MrBeast is misspelled.
2. **Defer to platform at execution** — same as 1, but Phase 5's user-facing message is explicit: "Similarity expansion happens server-side; preview not available in skill prototype."
3. **Wire `expand_similar_channels` API tool when available** — once the platform exposes a similarity endpoint via the CLI (e.g. `tl similar channels:MrBeast`), Phase 3 calls it to get the expanded ID list, then runs normal `db_count`/`db_sample`/`sample_judge` on those IDs.

**Current prototype uses option 2.** Option 3 is M5+ work, contingent on the platform exposing the endpoint.

### Implication for the recap

API tools are an **architectural class**, not a phase. They're called by Phase 2c (declaratively, via the FilterSet fields it emits) and Phase 3 (imperatively, as preliminary resolution). Three of five exist today via `tl db pg`; two are deferred to the platform until ES and similarity endpoints ship.

When v1 is ported to Python (M9+):
- The 3 SQL-resolvable tools become Django ORM helpers
- `expand_similar_channels` wraps v1's `find_similar_channels.py` directly
- `validate_keyword_via_es` calls the existing ES client
